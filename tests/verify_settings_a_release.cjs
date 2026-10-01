// Render the formal page with isolated API fixtures; never opens the user's data library.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/qa/settings-a-release');

async function verify(browser, width, native) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const calls = [];
  const sources = ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'].map((name, i) => ({ id: i + 1, name, homepage: 'https://example.org/', minimum_count: 1, voice_mode: 'browser' }));
  const values = {
    'voice-mode': { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural', browser_voice_label: 'システム音声' },
    'library': { sort: 'recent', lookup_chinese_translations: true },
    'daily-content': { target_count: 10, source_count: 6, required_count: 6 },
    'daily-schedule': { mode: 'manual', time: '00:00', scheduler_available: !native }
  };
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__fixture/api/')) {
      const apiPath = url.pathname.replace('/__fixture', '');
      calls.push({ path: apiPath, method: request.method() });
      const key = apiPath.split('/').pop();
      let data;
      if (apiPath === '/api/health') data = { status: 'ok', tts: 'browser' };
      else if (apiPath === '/api/browser-voices') data = [{ id: 'ja-JP-KeitaNeural', name: '圭太', available: true }, { id: 'ja-JP-NanamiNeural', name: '七海', available: true }];
      else if (key === 'news-sources') data = sources;
      else if (key === 'voices') data = [];
      else if (values[key]) {
        if (request.method() === 'PUT') Object.assign(values[key], request.postDataJSON());
        data = values[key];
      } else if (apiPath === '/api/settings/browser-voice') {
        const payload = request.postDataJSON();
        Object.assign(values['voice-mode'], { browser_voice_name: payload.name, browser_voice_label: payload.label });
        data = values['voice-mode'];
      } else if (apiPath === '/api/settings/refresh-storage') data = { articles: 0, bookmarks: 0, books: 0, removed: 0, errors: [] };
      else if (apiPath === '/api/tasks/daily') data = { status: 'idle' };
      else data = [];
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    }
    const file = path.join(root, url.pathname);
    if (!file.startsWith(path.join(root, 'static') + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ path: file });
  });
  if (native) await context.addInitScript(() => {
    const status = { app_version: '1.0.2', data_path: '/data/user/0/jp.fujimi.newsbunko.next/files/data', windows_status: 'unconfigured', sync_available: false, sync_state: 'unavailable', sync_stage: '协同同步尚未接入', sync_detail: '配对与文库合并尚未完成；连接检测不会传输文库。', reference_voices_available: false, daily_generation_available: false, scheduler_available: false, exact_alarm: false };
    window.FujimiMobile = {
      request: (raw, callback) => {
        const item = JSON.parse(raw);
        fetch('/__fixture' + item.path, { method: item.method, body: item.body, headers: { 'Content-Type': 'application/json' } }).then(async response => window.__fujimiMobileResolve(callback, response.status, await response.text()));
      },
      mobileStatus: () => JSON.stringify(status),
      setAllowCellular: value => { status.allow_cellular = value; return true; },
      setDeepSeekKey: () => { status.deepseek_configured = true; return true; },
      clearDeepSeekKey: () => { status.deepseek_configured = false; return true; },
      setServerUrl: value => { status.server_url = value; return true; }
    };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8439/static/index.html#settings');
  await page.waitForFunction(() => document.querySelector('#voice-list').children.length > 0 && document.querySelector('#daily-source-total').textContent === '6 个来源');
  if (native) await page.waitForFunction(() => !document.querySelector('#mobile-app-settings-panel').hidden);
  const layout = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('#settings-view .settings-panel')].filter(e => !e.hidden);
    return {
      viewport: document.documentElement.clientWidth, width: document.documentElement.scrollWidth,
      cards: nodes.map(e => ({ title: e.querySelector('h3').textContent, left: e.getBoundingClientRect().left, top: e.getBoundingClientRect().top, radius: getComputedStyle(e).borderRadius })),
      badControls: [...document.querySelectorAll('#settings-view button,#settings-view input,#settings-view select')].filter(e => e.getClientRects().length && (e.getBoundingClientRect().right > innerWidth + 1 || e.getBoundingClientRect().left < 0)).map(e => e.id)
    };
  });
  assert(layout.width <= layout.viewport + 1, JSON.stringify(layout));
  assert.deepEqual(layout.badControls, []);
  assert(layout.cards.every((card, i) => !i || card.top > layout.cards[i - 1].top), 'Settings must stay vertical');
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, `settings-${native ? 'android' : 'web'}-${width}.png`), fullPage: true });
  if (native) {
    assert.equal(await page.locator('#mobile-app-version').textContent(), '1.0.2');
    assert.equal(await page.locator('#mobile-sync-now').isDisabled(), true);
    await page.click('#add-voice');
    await page.waitForFunction(() => !document.querySelector('#browser-voice-select').disabled);
    await page.selectOption('#browser-voice-select', 'ja-JP-NanamiNeural');
    await page.click('#submit-voice');
    await page.waitForFunction(() => document.querySelector('#voice-list').textContent.includes('七海'));
    await page.selectOption('#library-sort-setting', 'series');
    await page.waitForFunction(() => document.querySelector('#library-sort-setting').value === 'series');
    await page.fill('#daily-target-count', '12');
    await page.waitForFunction(() => document.querySelector('#daily-content-summary').textContent.includes('其余 6'));
    await page.click('#source-settings-disclosure summary');
    assert.equal(await page.locator('#source-list').isVisible(), true);
    await page.click('#mobile-allow-cellular');
    assert.equal(await page.locator('#mobile-allow-cellular').isChecked(), true);
    await page.click('.settings-path-disclosure summary');
    assert.equal(await page.locator('#mobile-data-path').isVisible(), true);
    await page.screenshot({ path: path.join(output, `settings-android-${width}-expanded.png`), fullPage: true });
  }
  await context.close();
  return { native, width, layout, requests: calls.length };
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const results = [];
    for (const [width, native] of [[375, true], [390, true], [812, true], [1440, false]]) results.push(await verify(browser, width, native));
    fs.writeFileSync(path.join(output, 'layout-results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify({ passed: results.length, output }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
