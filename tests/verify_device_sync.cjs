// Exercise the formal settings page; network/native boundaries use isolated fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/qa/device-sync');

async function verify(browser, width, mobile) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  let enabled = false;
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      let value = [];
      if (url.pathname === '/api/settings/device-sync') {
        if (request.method() === 'PUT') enabled = request.postDataJSON().enabled;
        value = { enabled, url: enabled ? 'http://192.168.1.20:8429' : '', pairing_code: enabled ? '012345' : '',
          status: enabled ? 'waiting' : 'disabled', paired_devices: [], qr_url: '/api/settings/device-sync/qr' };
      } else if (url.pathname.endsWith('/qr')) {
        return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220"><rect width="220" height="220" fill="white"/></svg>' });
      } else if (url.pathname.endsWith('/health')) value = { status: 'ok' };
      else if (url.pathname.endsWith('/voice-mode')) value = { mode: 'browser' };
      else if (url.pathname.endsWith('/library')) value = { sort: 'recent' };
      else if (url.pathname.endsWith('/daily-schedule')) value = { mode: 'manual', time: '00:00' };
      else if (url.pathname.endsWith('/daily-content')) value = { target_count: 10, source_count: 0, required_count: 0 };
      else if (url.pathname.endsWith('/tasks/daily')) value = { status: 'idle' };
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
    }
    const file = path.join(root, url.pathname);
    return file.startsWith(path.join(root, 'static') + path.sep) && fs.existsSync(file)
      ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
  });
  if (mobile) await context.addInitScript(() => {
    const status = { app_version: 'test', data_path: '/test/data', windows_status: 'unconfigured', paired: false,
      sync_available: false, sync_state: 'idle', reference_voices_available: false, daily_generation_available: true };
    window.pairRequests = [];
    window.FujimiMobile = {
      mobileStatus: () => JSON.stringify(status),
      request(raw, callback) {
        const req = JSON.parse(raw);
        fetch(req.path, { method: req.method, body: req.body }).then(async r => window.__fujimiMobileResolve(callback, r.status, await r.text()));
      },
      pairWindows(url, code, callback) {
        window.pairRequests.push({ url, code });
        Object.assign(status, { server_url: url, paired: true, windows_status: 'ready', sync_available: true });
        setTimeout(() => window.__fujimiWindowsCheckResult(callback, true, '配对成功'), 10);
      },
      scanWindowsPairing(callback) {
        setTimeout(() => window.__fujimiWindowsCheckResult(callback, false, '已取消扫码'), 10);
      },
      setServerUrl(url) { Object.assign(status, { server_url: url, paired: false, windows_status: 'unconfigured', sync_available: false }); return true; },
    };
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://127.0.0.1:8439/static/index.html#settings');
  if (mobile) {
    await page.locator('#mobile-windows-code').waitFor({ state: 'visible', timeout: 2000 });
    await page.fill('#mobile-windows-address', 'http://192.168.1.20:8429');
    await page.fill('#mobile-windows-code', '123');
    await page.click('#mobile-save-windows');
    assert.equal(await page.evaluate(() => pairRequests.length), 0);
    await page.fill('#mobile-windows-code', '012345');
    await page.click('#mobile-save-windows');
    await page.waitForFunction(() => !document.querySelector('#mobile-save-windows').disabled);
    assert.deepEqual(await page.evaluate(() => pairRequests), [{ url: 'http://192.168.1.20:8429', code: '012345' }]);
    assert.equal(await page.locator('#mobile-sync-now').isDisabled(), false);
    assert.equal(await page.inputValue('#mobile-windows-code'), '');
    await page.click('#mobile-scan-windows');
    await page.waitForFunction(() => document.querySelector('#mobile-windows-result').textContent.includes('取消'));
    assert.equal(await page.locator('#mobile-save-windows').isDisabled(), false);
    assert.equal(await page.locator('#mobile-scan-windows').isDisabled(), false);
  } else {
    await page.locator('#device-sync-enabled').waitFor({ state: 'visible', timeout: 2000 });
    await page.check('#device-sync-enabled');
    await page.waitForFunction(() => document.querySelector('#device-sync-code').textContent === '012345');
    assert.equal(await page.locator('#device-sync-url').textContent(), 'http://192.168.1.20:8429');
    assert.equal(await page.locator('#device-sync-qr').isVisible(), true);
    await page.uncheck('#device-sync-enabled');
    await page.waitForFunction(() => document.querySelector('#device-sync-details').hidden);
    await page.check('#device-sync-enabled');
    await page.waitForFunction(() => !document.querySelector('#device-sync-details').hidden);
  }
  const layout = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth,
    outside: [...document.querySelectorAll('#settings-view input,#settings-view button')].filter(e => e.getClientRects().length && (e.getBoundingClientRect().right > innerWidth + 1 || e.getBoundingClientRect().left < 0)).map(e => e.id) }));
  assert(layout.width <= layout.viewport + 1, JSON.stringify(layout));
  assert.deepEqual(layout.outside, []);
  assert.deepEqual(errors, []);
  await page.screenshot({ path: path.join(output, `${mobile ? 'android' : 'pc'}-${width}.png`), fullPage: true });
  await context.close();
  return { mobile, width, layout };
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const results = [];
    for (const [width, mobile] of [[1440, false], [375, false], [375, true], [390, true]]) results.push(await verify(browser, width, mobile));
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
