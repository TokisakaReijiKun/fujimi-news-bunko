const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { fixture } = require('./verify_mobile_app.cjs');
const out = path.resolve(__dirname, '../build/qa/voice-management');
async function verify(browser, width) {
  const f = await fixture(browser, width, true, { hasTouch: true, isMobile: true });
  const { context, page, errors } = f;
  const mode = { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural' };
  const catalog = [{ id: 'ja-JP-KeitaNeural', name: '圭太', available: true }, { id: 'ja-JP-NanamiNeural', name: '七海', available: true }];
  let voices = [{ id: 44, name: '既存の声', duration: 2, saved_audio_only: true }];
  const calls = [];
  const word = { id: '9009', spell: '会長', pron: 'かいちょう', excerpt: '会长。', definitions: [], examples: [] };
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), api = url.pathname.replace('/__fixture', '');
    const body = req.postData() ? req.postDataJSON() : {};
    let data;
    if (api === '/api/settings/voice-mode') data = mode;
    else if (api === '/api/browser-voices') data = catalog.filter(v => !v.hidden);
    else if (api === '/api/settings/voice-catalog') data = catalog;
    else if (api === '/api/settings/browser-voice') { Object.assign(mode, { mode: 'browser', browser_voice_name: body.name }); data = mode; }
    else if (api === '/api/settings/active-voice') { Object.assign(mode, { mode: 'voice', voice_id: body.voice_id }); data = mode; }
    else if (api === '/api/settings/browser-voices') {
      const voice = catalog.find(v => v.id === body.id);
      if (req.method() === 'DELETE') { voice.hidden = true; if (mode.browser_voice_name === voice.id && mode.mode === 'browser') mode.mode = 'none'; }
      else { voice.name = body.name; voice.hidden = false; }
      data = { ok: true };
    } else if (api === '/api/settings/voice-file') data = req.method() === 'POST' ? { file_token: 'selected-wave', filename: 'sample.wav', duration: 2 } : { ok: true };
    else if (api === '/api/settings/voices') {
      if (req.method() === 'POST') { voices.push({ id: 201, name: body.name, duration: 2 }); data = { ok: true }; }
      else data = voices.map(v => ({ ...v, active: mode.mode === 'voice' && mode.voice_id === v.id }));
    } else if (/^\/api\/settings\/voices\/\d+$/.test(api)) {
      const id = Number(api.split('/').pop());
      if (req.method() === 'DELETE') { voices = voices.filter(v => v.id !== id); if (mode.voice_id === id && mode.mode === 'voice') mode.mode = 'none'; }
      else voices.find(v => v.id === id).name = body.name;
      data = { ok: true };
    } else if (api === '/api/dictionary/words/9009') data = word;
    else if (api === '/api/dictionary/search') data = { results: [word] };
    else return route.fallback();
    calls.push({ api, method: req.method(), body }); return route.fulfill({ json: data });
  });
  page.on('dialog', dialog => dialog.accept());
  await page.evaluate(() => window.__fujimiNavigate('settings'));
  await page.locator('fujimi-app .settings-voice-select').click();
  const dialog = page.locator('fujimi-app dialog');
  await dialog.locator('.voice-manager-row').first().waitFor();
  assert.equal(await dialog.locator('.voice-manager-row').count(), 3);
  assert.equal(await dialog.locator('.voice-category').count(), 0);
  await dialog.locator('[data-voice-id="44"] .choice').click();
  await dialog.locator('[data-voice-id="44"] .choice[aria-pressed=true]').waitFor();
  await dialog.locator('[data-voice-id="44"]').getByRole('button', { name: '修改', exact: true }).click();
  await dialog.getByLabel('名称', { exact: true }).fill('新名称');
  await dialog.getByRole('button', { name: '选择音频', exact: true }).click();
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await dialog.locator('[data-voice-id="44"]').getByText('新名称', { exact: true }).waitFor();
  assert(calls.some(c => c.api.endsWith('/voices/44') && c.body.file_token === 'selected-wave'));
  await dialog.getByRole('button', { name: '添加声线', exact: true }).click();
  await dialog.getByLabel('名称', { exact: true }).fill('手机新声');
  await dialog.getByRole('button', { name: '选择音频', exact: true }).click();
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await dialog.locator('[data-voice-id="201"]').waitFor();
  await dialog.locator('[data-voice-id="201"]').getByRole('button', { name: '删除', exact: true }).click();
  await dialog.locator('[data-voice-id="201"]').waitFor({ state: 'detached' });
  await dialog.locator('[data-voice-id="ja-JP-KeitaNeural"]').getByRole('button', { name: '修改', exact: true }).click();
  await dialog.getByLabel('名称', { exact: true }).fill('我的圭太');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await dialog.getByText('我的圭太', { exact: true }).waitFor();
  await dialog.locator('[data-voice-id="ja-JP-NanamiNeural"]').getByRole('button', { name: '删除', exact: true }).click();
  await dialog.locator('[data-voice-id="ja-JP-NanamiNeural"]').waitFor({ state: 'detached' });
  await dialog.getByRole('button', { name: '添加声线', exact: true }).click();
  await dialog.locator('.voice-editor select').nth(0).selectOption('catalog', { force: true });
  await dialog.locator('.voice-editor select').nth(1).selectOption('ja-JP-NanamiNeural', { force: true });
  await dialog.getByLabel('名称', { exact: true }).fill('七海归来');
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await dialog.getByText('七海归来', { exact: true }).waitFor();
  assert(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
  await page.screenshot({ path: path.join(out, `voices-${width}.png`) });
  await dialog.locator('[data-voice-id="44"]').getByRole('button', { name: '删除', exact: true }).click();
  await dialog.locator('[data-voice-id="44"]').waitFor({ state: 'detached' });
  assert.equal(mode.mode, 'none');
  assert.equal(await page.locator('fujimi-app .settings-voice-name').textContent(), '朗読しない');
  await dialog.getByRole('button', { name: '閉じる', exact: true }).click();
  await page.evaluate(() => { localStorage.setItem('fujimi-dictionary-favorites', '["9009"]'); return window.__fujimiNavigate('dictionary'); });
  await page.locator('fujimi-app').getByRole('button', { name: '收藏', exact: true }).click();
  const favoritesPage = page.locator('fujimi-app .dictionary-favorites-page');
  await favoritesPage.getByText('会長', { exact: true }).waitFor();
  assert.equal(await dialog.isVisible(), false, 'Favorites must be an independent page');
  assert.equal(await page.evaluate(() => window.__fujimiApp.view), 'dictionary-favorites');
  await favoritesPage.locator('.word-favorite-open').click();
  await page.locator('#dictionary-view.dictionary-detail-open').waitFor();
  assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
  await favoritesPage.getByText('会長', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(out, `favorites-${width}.png`) });
  await favoritesPage.getByRole('button', { name: '取消收藏', exact: true }).click();
  await favoritesPage.getByText('暂无收藏词条', { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem('fujimi-dictionary-favorites')), '[]');
  await favoritesPage.getByRole('button', { name: '返回辞書', exact: true }).click();
  await page.locator('fujimi-app').getByRole('button', { name: '收藏', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  await context.close(); return { width, calls: calls.length, CRUD: true, favorites: true, errors };
}
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true,
    args: process.env.FUJIMI_TEST_LOW_MEMORY ? ['--disable-gpu', '--renderer-process-limit=1'] : [] });
  try { const results = []; for (const width of [375, 390]) results.push(await verify(browser, width)); fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results)); console.log(JSON.stringify(results)); }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
