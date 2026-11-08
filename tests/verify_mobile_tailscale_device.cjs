// Dedicated QA emulator only; never logs in or contacts the user's PC.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../build/qa/mobile-tailscale');
const adb = (...args) => execFileSync('C:/Android/Sdk/platform-tools/adb.exe', ['-s', 'emulator-5554', ...args], { timeout: 15000 });

(async () => {
  assert.match(adb('emu', 'avd', 'name').toString(), /fujimi-redesign-api35/);
  const pid = adb('shell', 'pidof', 'jp.fujimi.newsbunko.next').toString().trim();
  assert.match(pid, /^\d+$/);
  adb('forward', 'tcp:9224', `localabstract:webview_devtools_remote_${pid}`);
  let socket;
  try {
    const targets = await (await fetch('http://127.0.0.1:9224/json/list')).json();
    const target = targets.find(t => t.url.includes('appassets.androidplatform.net'));
    assert(target, 'Formal Android WebView must be loaded');
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let sequence = 0;
    const pending = new Map();
    socket.onmessage = event => { const result = JSON.parse(event.data); pending.get(result.id)?.(result); };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timeout')); }, 30000);
      pending.set(id, response => { clearTimeout(timer); pending.delete(id); response.error ? reject(new Error(JSON.stringify(response.error))) : resolve(response.result); });
      socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
      return response.result.value;
    };
    const waitFor = async expression => {
      const end = Date.now() + 30000;
      while (Date.now() < end) { if (await evaluate(expression)) return; await new Promise(resolve => setTimeout(resolve, 250)); }
      throw new Error('Condition timeout: ' + expression);
    };
    const root = "document.querySelector('fujimi-app').shadowRoot";
    const touch = async selector => {
      const point = await evaluate(`(()=>{const e=${root}.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, radiusX: 1, radiusY: 1 }] });
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    };
    await waitFor('Boolean(window.__fujimiApp?.ready)');
    assert.equal(await evaluate('JSON.parse(FujimiMobile.mobileStatus()).paired'), false);
    await evaluate("window.__fujimiNavigate('settings')");
    await touch('.sync-entry');
    await waitFor(`Boolean(${root}.querySelector('dialog[open] [aria-label="PCの接続先"]'))`);
    await evaluate(`(()=>{const d=${root}.querySelector('dialog');for(const [label,value] of [['PCの接続先','http://100.101.102.103:8429'],['6桁のペアリングコード','123456']]){const input=d.querySelector('[aria-label="'+label+'"]');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}})()`);
    await touch('dialog button[type=submit]');
    await waitFor('Boolean(mobileWindowsCheck && mobileWindowsCheck.timer === null)');
    let opened = false;
    for (let count = 0; count < 30; count++) {
      const activities = adb('shell', 'dumpsys', 'activity', 'activities').toString();
      if (/topResumedActivity[^\n]*com\.tailscale\.ipn/.test(activities)) { opened = true; break; }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    assert(opened, 'Clicking connect must foreground the actual Tailscale app');
    fs.writeFileSync(path.join(out, 'tailscale-opened.png'), adb('exec-out', 'screencap', '-p'));
    // Cancel the QA emulator's first-run VPN consent instead of granting it.
    await new Promise(resolve => setTimeout(resolve, 2000));
    let returned = false;
    for (let count = 0; count < 20; count++) {
      const activities = adb('shell', 'dumpsys', 'activity', 'activities').toString();
      if (/topResumedActivity[^\n]*com\.android\.vpndialogs/.test(activities)) adb('shell', 'input', 'keyevent', '4');
      if (/topResumedActivity[^\n]*jp\.fujimi\.newsbunko\.next/.test(activities)) { returned = true; break; }
      adb('shell', 'am', 'start', '-n', 'jp.fujimi.newsbunko.next/.MainActivity');
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    assert(returned, 'Document app must actually return to the foreground');
    await waitFor('!mobileWindowsCheck');
    await waitFor(`Boolean(${root}.querySelector('dialog > .toast.is-error:not([hidden])'))`);
    assert.match(await evaluate(`${root}.querySelector('dialog > .toast').textContent`), /Tailscale.*VPN/);
    assert.equal(await evaluate('JSON.parse(FujimiMobile.mobileStatus()).paired'), false);
    assert.equal(await evaluate(`${root}.querySelector('dialog button[type=submit]').disabled`), false);
    assert.equal(await evaluate(`${root}.querySelectorAll('dialog .source-feedback,dialog .sync-copy-feedback,dialog .app-sheet-feedback').length`), 0);
    assert.match(adb('shell', 'dumpsys', 'activity', 'activities').toString(), /topResumedActivity[^\n]*jp\.fujimi\.newsbunko\.next/);
    fs.writeFileSync(path.join(out, 'android-vpn-toast.png'), adb('exec-out', 'screencap', '-p'));
    console.log('Real Android WebView: connect opened Tailscale; returning without login failed honestly in a toast and restored the form.');
  } finally {
    socket?.close();
    adb('forward', '--remove', 'tcp:9224');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
