// Isolated formal-page browser checks. No server or user data is read or changed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/qa/android-frontend');

async function fixture(browser, width, native, original = false) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const calls = [];
  const sources = ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'].map((name, i) => ({ id: i + 1, name, homepage: 'https://example.org/', minimum_count: 1, voice_mode: 'browser' }));
  const values = {
    'voice-mode': { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural', browser_voice_label: 'システム音声' },
    library: { sort: 'recent', lookup_chinese_translations: true },
    'daily-content': { target_count: 10, source_count: 6, required_count: 6 },
    'daily-schedule': { mode: 'manual', time: '00:00', scheduler_available: true }
  };
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__fixture/api/')) {
      const apiPath = url.pathname.replace('/__fixture', '');
      calls.push({ path: apiPath, method: request.method(), body: request.postData() });
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
      } else if (apiPath.startsWith('/api/settings/news-sources/')) {
        const source = sources.find(item => item.id === Number(key));
        if (request.method() === 'PUT') Object.assign(source, request.postDataJSON());
        data = source;
      } else if (apiPath === '/api/tasks/daily') data = { status: 'idle' };
      else data = [];
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    }
    let file = path.join(root, url.pathname);
    if (original && url.pathname === '/static/static.css') file = path.join(root, 'apk-original/static/styles.css');
    else if (!file.startsWith(path.join(root, 'static') + path.sep)) return route.fulfill({ status: 404, body: '' });
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
    return route.fulfill({ path: file });
  });
  if (native) await context.addInitScript(() => {
    window.FujimiMobile = {
      request: (raw, callback) => {
        const item = JSON.parse(raw);
        fetch('/__fixture' + item.path, { method: item.method, body: item.body, headers: { 'Content-Type': 'application/json' } }).then(async response => window.__fujimiMobileResolve(callback, response.status, await response.text()));
      },
      mobileStatus: () => JSON.stringify({ app_version: 'test', reference_voices_available: false, daily_generation_available: true, scheduler_available: true, exact_alarm: false, sync_available: false })
    };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8439/static/index.html#settings');
  await page.waitForFunction(() => document.querySelector('#voice-list').children.length > 0 && document.querySelector('#daily-source-total').textContent === '6 个来源');
  return { context, page, errors, values, calls };
}

async function geometry(page) {
  return page.evaluate(() => {
    const bar = document.querySelector('.mobile-app-bar');
    const title = document.querySelector('.mobile-app-bar-title');
    const shell = document.querySelector('.content-shell');
    const cards = [...document.querySelectorAll('#settings-view .settings-panel')].filter(e => !e.hidden);
    return { height: bar.getBoundingClientRect().height, kicker: getComputedStyle(document.querySelector('#mobile-current-kicker')).fontSize,
      title: getComputedStyle(document.querySelector('#mobile-current-view')).fontSize,
      brand: null,
      background: getComputedStyle(bar).backgroundImage,
      padding: getComputedStyle(shell).paddingTop,
      shellTop: shell.getBoundingClientRect().top, cardTop: cards[0].getBoundingClientRect().top,
      cards: cards.map(e => ({ left: e.getBoundingClientRect().left, top: e.getBoundingClientRect().top })),
      width: document.documentElement.scrollWidth, viewport: innerWidth };
  });
}

async function verify(browser, width, native) {
  const { context, page, errors, values, calls } = await fixture(browser, width, native);
  const layout = await geometry(page);
  assert(layout.width <= layout.viewport + 1, JSON.stringify(layout));
  assert(layout.cards.every((card, i) => !i || card.top > layout.cards[i - 1].top), '方案 A 必须保持单列卡片');
  if (native) {
    console.log(JSON.stringify({ width, layout }));
    assert.equal(layout.height, 112, 'APK 应用栏应保留原版页面标题栏高度');
    assert.equal(layout.cardTop, 130, '首卡应按原版标题栏与页面间距定位');
    const trigger = page.locator('[data-android-select="library-sort-setting"]');
    assert.equal(await trigger.count(), 1, 'APK 单选必须显示字段旁的 anchored dropdown，不触发原生 radio modal');
    assert.equal(await page.locator('#library-sort-setting').isVisible(), false);
    await trigger.click();
    const list = page.locator('.android-select-list:visible');
    assert.equal(await list.count(), 1);
    await page.screenshot({ path: path.join(output, `sort-open-${width}.png`) });
    const field = await trigger.boundingBox(), popup = await list.boundingBox();
    assert(Math.abs(field.x - popup.x) < 2 && Math.abs(field.width - popup.width) < 2, '下拉列表应对齐字段');
    assert(Math.abs(field.y + field.height + 4 - popup.y) < 2 || Math.abs(popup.y + popup.height + 4 - field.y) < 2, '下拉列表须锚定字段上/下方');
    await list.getByRole('option', { name: 'シリーズ・巻順', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#library-sort-setting').value === 'series');
    assert.equal(values.library.sort, 'series', '真实 change 处理器必须保存书架排序');
    await trigger.click();
    assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
    assert.equal(await list.count(), 0, 'Android 返回键先关闭下拉');
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
    await trigger.press('ArrowDown');
    assert.notEqual(await trigger.evaluate(el => getComputedStyle(el).outlineStyle), 'none', '键盘焦点必须可见');
    await page.keyboard.press('End');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#library-sort-setting').value === 'imported');
    assert.equal(values.library.sort, 'imported');
    await trigger.click();
    await page.keyboard.press('Escape');
    assert.equal(await list.count(), 0);
    await trigger.click();
    await page.locator('.mobile-app-bar-title').click();
    assert.equal(await list.count(), 0, '外部点击关闭下拉');
    await page.evaluate(() => { const s = document.querySelector('#library-sort-setting'); s.add(new Option('测试动态选项', 'dynamic')); s.value = 'dynamic'; });
    await page.waitForFunction(() => document.querySelector('[data-android-select="library-sort-setting"]').textContent.includes('测试动态选项'));
    await trigger.click();
    assert.equal(await list.getByRole('option', { name: '测试动态选项', exact: true }).count(), 1);
    await page.evaluate(() => { document.querySelector('#library-sort-setting').disabled = true; });
    await page.waitForFunction(() => document.querySelector('[data-android-select="library-sort-setting"]').disabled);
    assert.equal(await list.count(), 0);
    await page.evaluate(() => { const s = document.querySelector('#library-sort-setting'); s.disabled = false; s.value = 'imported'; });
    await page.click('#add-voice');
    await page.waitForFunction(() => !document.querySelector('#browser-voice-select').disabled);
    await page.locator('[data-android-select="browser-voice-select"]').click();
    await page.screenshot({ path: path.join(output, `voice-open-${width}.png`) });
    await list.getByRole('option', { name: /七海/ }).click();
    await page.click('#submit-voice');
    await page.waitForFunction(() => document.querySelector('#voice-list').textContent.includes('七海'));
    assert.equal(values['voice-mode'].browser_voice_name, 'ja-JP-NanamiNeural');
    await page.click('#add-voice');
    await page.locator('[data-android-select="browser-voice-select"]').click();
    assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
    assert.equal(await page.locator('#voice-dialog').evaluate(e => e.open), true, '返回键须先关列表，再关多字段编辑器');
    assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
    assert.equal(await page.locator('#voice-dialog').evaluate(e => e.open), false);
    await page.click('#source-settings-disclosure summary');
    await page.locator('#source-list .source-actions-menu summary').first().click();
    await page.locator('#source-list .edit').first().click();
    await page.locator('[data-android-select="source-editor-voice"]').click();
    await list.getByRole('option', { name: /全局|继承/ }).click();
    await page.click('#submit-source');
    await page.waitForFunction(() => !document.querySelector('#source-dialog').open);
    assert.equal(values['voice-mode'].browser_voice_name, 'ja-JP-NanamiNeural');
    assert(calls.some(call => call.path === '/api/settings/news-sources/1' && call.method === 'PUT'));
    // Newly inserted single selects must inherit the same behavior; multiple selects stay native.
    await page.evaluate(() => { const s = document.createElement('select'); s.id = 'dynamic-single'; s.setAttribute('aria-label', '动态控件'); s.add(new Option('一', '1')); s.add(new Option('二', '2')); document.querySelector('#settings-view').append(s); });
    await page.waitForFunction(() => document.querySelector('[data-android-select="dynamic-single"]'));
    assert.equal(await page.locator('#dynamic-single').isVisible(), false);
    const dynamicTrigger = page.locator('[data-android-select="dynamic-single"]');
    await page.evaluate(() => {
      const select = document.querySelector('#dynamic-single');
      const group = document.createElement('optgroup'); group.label = '不可用组'; group.disabled = true;
      group.append(new Option('不可选择', 'locked')); select.append(group);
      window.__dynamicChanges = 0; select.onchange = () => window.__dynamicChanges++;
    });
    await dynamicTrigger.click();
    await list.getByRole('option', { name: '不可选择', exact: true }).click({ force: true });
    assert.equal(await page.locator('#dynamic-single').inputValue(), '1');
    assert.equal(await page.evaluate(() => window.__dynamicChanges), 0, '禁用选项不可触发change');
    await page.keyboard.press('End'); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#dynamic-single').inputValue(), '2');
    assert.equal(await page.evaluate(() => window.__dynamicChanges), 1, '键盘须跳过禁用选项并仅提交一次change');
    await page.evaluate(() => { document.querySelector('#dynamic-single').options[0].selected = true; });
    await page.waitForFunction(() => document.querySelector('[data-android-select="dynamic-single"]').textContent === '一');
    await page.evaluate(() => {
      const form = document.createElement('form'); const fieldset = document.createElement('fieldset');
      document.querySelector('#settings-view').append(form); form.append(fieldset);
      fieldset.append(document.querySelector('#dynamic-single')); fieldset.disabled = true;
    });
    await page.waitForFunction(() => document.querySelector('[data-android-select="dynamic-single"]').disabled);
    await page.evaluate(() => { const s = document.querySelector('#dynamic-single'); s.parentElement.disabled = false; s.value = '2'; s.closest('form').reset(); });
    await page.waitForFunction(() => document.querySelector('[data-android-select="dynamic-single"]').textContent === '一');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('[data-android-select="library-sort-setting"]')?.textContent.includes('最近追加'));
    assert.equal(await page.locator('#library-sort-setting').inputValue(), 'imported', '刷新后使用已保存值');
  } else {
    assert.equal(await page.locator('.android-select-trigger').count(), 0, 'Web/PC 应保留原控件');
    assert.equal(await page.locator('#library-sort-setting').isVisible(), true);
  }
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, `settings-${native ? 'apk' : 'web'}-${width}.png`), fullPage: true });
  await context.close();
  return { width, native, layout, requests: calls.length };
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const results = [];
    for (const [width, native] of [[375, true], [390, true], [812, true], [390, false], [1440, false]]) results.push(await verify(browser, width, native));
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify({ passed: results.length, output }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
