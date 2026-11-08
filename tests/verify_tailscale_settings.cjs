// Offline UI contract: all requests use isolated fixtures; no VPN or desktop service is contacted.
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');
const { fixture } = require('./verify_mobile_app.cjs');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const { context, page, errors } = await fixture(browser, 1440, false);
    const off = { enabled: false, url: '', pairing_code: '', status: 'disabled', paired_devices: [], network: '', tailscale_status: '', login_url: '' };
    let status = { ...off }, phase = 'pending', release;
    await context.route('**/api/settings/device-sync', async route => {
      let code = 200;
      if (route.request().method() === 'PUT') {
        if (!route.request().postDataJSON().enabled) status = { ...off };
        else if (phase === 'pending') {
          await new Promise(resolve => release = resolve);
          status = { ...off, enabled: true, url: 'http://100.101.102.103:8429', pairing_code: '012345',
            status: 'waiting', network: 'tailscale', tailscale_status: 'ready', detail: '手机连接同一 Tailscale 网络后配对。' };
        } else {
          status = { ...off, status: 'error', network: 'tailscale', tailscale_status: 'login_required',
            detail: '请先登录 Tailscale，再重新开启。', login_url: 'https://login.tailscale.com/a/offline-test' };
          code = 503;
        }
      }
      await route.fulfill({ status: code, json: status });
    });
    await page.evaluate(() => showView('settings'));
    const toggle = page.locator('#device-sync-enabled');
    await toggle.waitFor({ state: 'visible' });
    await toggle.check();
    await page.waitForFunction(() => document.querySelector('#device-sync-enabled').disabled);
    assert.equal(await toggle.getAttribute('aria-busy'), 'true');
    assert((await page.locator('#device-sync-state').textContent()).includes('正在准备'));
    assert(await page.locator('#device-sync-details').isHidden());
    release();
    await page.waitForFunction(() => !document.querySelector('#device-sync-enabled').disabled);
    assert.equal(await page.locator('#device-sync-url').textContent(), 'http://100.101.102.103:8429');
    assert.equal(await page.locator('#device-sync-code').textContent(), '012345');
    assert(await page.locator('#device-sync-details').isVisible());
    assert(await page.locator('#device-sync-login').isHidden());

    await toggle.uncheck();
    await page.waitForFunction(() => !document.querySelector('#device-sync-enabled').disabled);
    assert(await page.locator('#device-sync-details').isHidden());
    assert.equal(await page.locator('#device-sync-state').textContent(), '未开启');

    phase = 'login'; await toggle.check();
    await page.waitForFunction(() => document.querySelector('#device-sync-state').textContent.includes('等待 Tailscale 登录'));
    assert.equal(await toggle.isChecked(), false);
    assert(await page.locator('#device-sync-error').isVisible());
    assert(await page.locator('#device-sync-details').isHidden());
    assert.equal(await page.locator('#device-sync-login').getAttribute('href'), 'https://login.tailscale.com/a/offline-test');
    assert(await page.locator('#device-sync-login').isVisible());
    for (const value of ['javascript:alert(1)', 'https://login.tailscale.com.evil.test/a/fake', 'https://other.test/a/fake']) {
      status.login_url = value;
      await page.evaluate(() => loadDeviceSyncSettings());
      assert(await page.locator('#device-sync-login').isHidden());
      assert.equal(await page.locator('#device-sync-login').getAttribute('href'), null);
    }
    assert.deepEqual(errors, []);
    await context.close();
    console.log('Offline Tailscale UI states: pending, ready, disabled, login-required and safe link handling passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
