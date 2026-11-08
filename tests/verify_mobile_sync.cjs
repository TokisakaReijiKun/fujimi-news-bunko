// Synthetic native responses; never connects to the user's PC or VPN.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { fixture } = require('./verify_mobile_app.cjs');
const out = path.resolve(__dirname, '../build/qa/mobile-tailscale');

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    for (const width of [375, 390]) {
      const { context, page, errors } = await fixture(browser, width);
      if (process.env.FUJIMI_QA_ASSETS) {
        const assets = path.resolve(process.env.FUJIMI_QA_ASSETS);
        await context.route('**/static/**', route => {
          const file = path.resolve(assets, '.' + new URL(route.request().url()).pathname);
          assert(file.startsWith(assets + path.sep));
          return route.fulfill({ path: file });
        });
        await page.reload();
        await page.waitForFunction(() => window.__fujimiApp?.ready);
      }
      await page.evaluate(() => {
        window.FujimiMobile.pairWindows = (_address, _code, id) => {
          window.__fujimiWindowsCheckPhase?.(id, 'tailscale');
          setTimeout(() => window.__fujimiWindowsCheckResult(id, false, 'Tailscaleにログインして接続してください。'), 1200);
        };
      });
      await page.evaluate(() => window.__fujimiNavigate('settings'));
      await page.locator('fujimi-app .sync-entry').click();
      const dialog = page.locator('fujimi-app dialog');
      await dialog.getByLabel('PCの接続先', { exact: true }).fill('http://100.69.147.24:8429');
      await dialog.getByLabel('6桁のペアリングコード', { exact: true }).fill('123456');
      await dialog.getByRole('button', { name: '接続', exact: true }).click();
      assert.equal(await page.evaluate(() => mobileWindowsCheck?.timer), null, 'Tailscale login must pause the short network timeout');
      await page.waitForFunction(() => !mobileWindowsCheck);
      await page.waitForFunction(() => document.querySelector('fujimi-app').shadowRoot.querySelector('dialog > .toast.is-error:not([hidden])'));
      assert.equal(await dialog.locator('.toast').textContent(), 'Tailscaleにログインして接続してください。');
      assert.equal(await dialog.locator('.source-feedback, .sync-copy-feedback, .app-sheet-feedback').count(), 0);
      assert(await dialog.getByRole('button', { name: '接続', exact: true }).isEnabled());
      assert.equal(await page.evaluate(() => {
        const dialog = document.querySelector('fujimi-app').shadowRoot.querySelector('dialog');
        return dialog.scrollWidth <= dialog.clientWidth + 1 && document.documentElement.scrollWidth <= innerWidth;
      }), true);
      await page.screenshot({ path: path.join(out, `sync-toast-${width}.png`) });
      await dialog.getByRole('button', { name: '翻訳と通信', exact: true }).click();
      await dialog.getByLabel('モバイル通信を許可').click();
      assert(await dialog.locator('.toast:not([hidden])').isVisible());
      assert.equal(await dialog.locator('.source-feedback, .sync-copy-feedback, .app-sheet-feedback').count(), 0);
      assert.deepEqual(errors, []);
      await context.close();
    }
    const { context, page, errors } = await fixture(browser, 1440, false);
    assert.equal(await page.locator('fujimi-app').count(), 0);
    assert.equal(await page.locator('#mobile-app-settings-panel').isVisible(), false);
    assert.deepEqual(errors, []);
    await context.close();
    console.log('Mobile sync: toast feedback, modal layering, repeat actions, 375/390px and PC isolation passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
