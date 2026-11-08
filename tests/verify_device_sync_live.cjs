// Run only against run_device_sync_fixture.py and an isolated Android emulator.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const output = path.resolve(__dirname, '../build/qa/device-sync');
const host = process.env.FUJIMI_TEST_PC_BASE || 'http://127.0.0.1:18428';
assert(/^http:\/\/127\.0\.0\.1:18\d{3}$/.test(host), 'Acceptance requires an isolated local server');
const adb = 'C:/Android/Sdk/platform-tools/adb.exe';
const emulator = process.env.FUJIMI_TEST_EMULATOR || 'emulator-5554';
assert(/^emulator-\d+$/.test(emulator));
const device = (...args) => execFileSync(adb, ['-s', emulator, ...args], { timeout: 30000 });

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  let socket;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(host + '/#settings');
    await page.locator('#device-sync-enabled').waitFor({ state: 'visible' });
    await page.check('#device-sync-enabled');
    await page.waitForFunction(() => document.querySelector('#device-sync-qr').naturalWidth > 100 && !document.querySelector('#device-sync-details').hidden);
    const pairing = await (await fetch(host + '/api/settings/device-sync')).json();
    assert(pairing.enabled && /^\d{6}$/.test(pairing.pairing_code));
    fs.writeFileSync(path.join(output, 'real-qr.png'), Buffer.from(await (await fetch(host + pairing.qr_url)).arrayBuffer()));
    await page.locator('#device-sync-panel').screenshot({ path: path.join(output, 'pc-live.png') });

    const targets = await (await fetch('http://127.0.0.1:9229/json/list')).json();
    const target = targets.find(x => x.url.startsWith('https://appassets.androidplatform.net/'));
    assert(target);
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
    });
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timed out')); }, 30000);
      pending.set(id, result => { clearTimeout(timer); result.error ? reject(new Error(JSON.stringify(result.error))) : resolve(result.result); });
      socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const waitFor = async (expression, timeout = 20000) => {
      const end = Date.now() + timeout;
      while (Date.now() < end) {
        if (await evaluate(`Boolean(${expression})`)) return;
        await new Promise(resolve => setTimeout(resolve, 200));
      }
      throw new Error('Timed out: ' + expression);
    };
    const touch = async selector => {
      const point = await evaluate(`(() => { const e=document.querySelector(${JSON.stringify(selector)}); if(!e || e.disabled)throw Error('Control unavailable'); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); const x=r.left+r.width/2,y=r.top+r.height/2; if(!e.contains(document.elementFromPoint(x,y)))throw Error('Control obscured');return {x,y}; })()`);
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, radiusX: 1, radiusY: 1 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    };
    await evaluate(`location.hash='#settings'`);
    await waitFor(`document.querySelector('#mobile-windows-code') && !document.querySelector('#mobile-settings-panel').hidden`);
    if (!await evaluate(`document.querySelector('#mobile-allow-cellular').checked`)) await touch('#mobile-allow-cellular');
    await evaluate(`(() => { for(const [id,value] of ${JSON.stringify([['mobile-windows-address', pairing.url], ['mobile-windows-code', pairing.pairing_code]])}){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}})()`);
    await touch('#mobile-save-windows');
    await waitFor(`!document.querySelector('#mobile-save-windows').disabled`, 45000);
    const connection = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
    assert(connection.paired, connection.connection_detail);
    await waitFor(`!document.querySelector('#mobile-sync-now').disabled`);
    console.log('Manual pairing passed');

    const before = await evaluate(`api('/api/daily?date=2026-10-17')`);
    assert(before.articles.some(a => a.title === '同步验收・Androidから'), 'Seed the phone fixture before acceptance');
    await touch('#mobile-sync-now');
    await waitFor(`['completed','partial','failed'].includes(JSON.parse(FujimiMobile.mobileStatus()).sync_state)`, 120000);
    const state = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
    assert.equal(state.sync_state, 'completed', state.sync_detail);
    const daily = await evaluate(`api('/api/daily?date=2026-10-17')`);
    assert(daily.articles.some(a => a.title === '同步验收・PCから'));
    const pcDaily = await (await fetch(host + '/api/daily?date=2026-10-17')).json();
    assert(pcDaily.articles.some(a => a.title === '同步验收・Androidから'), 'Phone article did not reach the PC');
    const books = await evaluate(`api('/api/books')`);
    const book = books.books.find(b => b.title === '同期した本');
    assert(book);
    await evaluate(`openBook(${book.id})`);
    await waitFor(`document.querySelector('.book-chapter-body').textContent.includes('これは同期した本の本文です。')`);
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(output, 'android-live-book.png'), Buffer.from(screenshot.data, 'base64'));
    await evaluate(`location.hash='#settings'`);
    await waitFor(`!document.querySelector('#mobile-settings-panel').hidden`);
    await touch('#mobile-scan-windows');
    const end = Date.now() + 10000;
    let camera = false;
    while (Date.now() < end) {
      const activities = device('shell', 'dumpsys', 'activity', 'activities').toString();
      if (activities.includes('CaptureActivity')) { camera = true; break; }
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    assert(camera, 'Scanner activity did not launch');
    device('shell', 'input', 'keyevent', '4');
    await waitFor(`!document.querySelector('#mobile-scan-windows').disabled`);
    await touch('#mobile-sync-now');
    await waitFor(`['completed','partial','failed'].includes(JSON.parse(FujimiMobile.mobileStatus()).sync_state)`, 120000);
    const repeat = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
    assert.equal(repeat.sync_state, 'completed', repeat.sync_detail);
    const results = { manualPairing: true, sync: state.sync_state, phoneArticleCount: daily.articles.length, pcArticleCount: pcDaily.articles.length,
      articleVisible: true, bookReadable: true, scannerLaunchAndCancel: true, repeat: repeat.sync_state };
    fs.writeFileSync(path.join(output, 'live-results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results));
  } finally { socket?.close(); await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
