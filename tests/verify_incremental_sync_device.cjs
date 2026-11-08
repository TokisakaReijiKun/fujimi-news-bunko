// Dedicated QA emulator only; never logs in or contacts the user's PC.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const out = path.resolve(__dirname, '../build/qa/sync-fast');
const endpoint = process.env.FUJIMI_SYNC_TEST_ENDPOINT || 'http://10.0.2.2:18429';
const adb = (...args) => execFileSync('C:/Android/Sdk/platform-tools/adb.exe', ['-s', 'emulator-5554', ...args], { timeout: 15000 });

(async () => {
  assert.match(adb('emu', 'avd', 'name').toString(), /fujimi-redesign-api35/);
  const pid = adb('shell', 'pidof', 'jp.fujimi.newsbunko.next').toString().trim();
  assert.match(pid, /^\d+$/);
  adb('forward', 'tcp:9225', `localabstract:webview_devtools_remote_${pid}`);
  let socket;
  try {
    const targets = await (await fetch('http://127.0.0.1:9225/json/list')).json();
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
    await evaluate("new Promise(resolve=>{const dialog=document.querySelector('fujimi-app').shadowRoot.querySelector('dialog');if(dialog.open){dialog.addEventListener('close',resolve,{once:true});dialog.close();}else resolve();})");
    await evaluate("FujimiMobile.setAllowCellular(true);FujimiMobile.setServerUrl('');window.__fujimiNavigate('settings')");
    await touch('.sync-entry');
    await waitFor(`Boolean(${root}.querySelector('dialog[open] [aria-label="PCの接続先"]'))`);
    await evaluate(`(()=>{const d=${root}.querySelector('dialog');for(const [label,value] of [['PCの接続先',${JSON.stringify(endpoint)}],['6桁のペアリングコード','123456']]){const input=d.querySelector('[aria-label="'+label+'"]');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}})()`);
    await touch('dialog button[type=submit]');
    await waitFor('JSON.parse(FujimiMobile.mobileStatus()).paired');
    const metrics=path.join(out,'runtime.json');
    const run=async label=>{
      await waitFor(`Boolean(${root}.querySelector('dialog .app-task-actions .primary:not(:disabled)'))`);
      const before=JSON.parse(fs.readFileSync(metrics,'utf8')), stamp=fs.statSync(metrics).mtimeMs;
      const started=Date.now();await touch('dialog .app-task-actions .primary');
      const deadline=Date.now()+60000;
      while(fs.statSync(metrics).mtimeMs<=stamp){if(Date.now()>deadline)throw new Error('No sync request started');await new Promise(r=>setTimeout(r,100));}
      await waitFor("!['idle','running','queued'].includes(JSON.parse(FujimiMobile.mobileStatus()).sync_state)");
      const state=await evaluate('JSON.parse(FujimiMobile.mobileStatus())');
      assert.equal(state.sync_state,'completed',state.sync_detail);
      const after=JSON.parse(fs.readFileSync(metrics,'utf8'));
      return {label,elapsed_ms:Date.now()-started,pulls:after.pulls-before.pulls,uploads:after.uploads-before.uploads,download_bytes:after.download_bytes-before.download_bytes,upload_bytes:after.upload_bytes-before.upload_bytes,detail:state.sync_detail};
    };
    const first=await run('first');
    assert(first.download_bytes>8*1024*1024,'First sync includes the 8 MiB recording');
    const repeat=await run('unchanged');
    assert.equal(repeat.pulls+repeat.uploads,0,'Unchanged libraries must not request any content bundle');
    assert.equal(repeat.download_bytes+repeat.upload_bytes,0);
    fs.writeFileSync(path.join(out,'add-audio.flag'),'test-only');
    const delta=await run('new-1MiB-audio');
    assert.equal(delta.pulls,1);
    assert(delta.download_bytes>1024*1024 && delta.download_bytes<1100000,'Only new audio plus small metadata should be downloaded');
    const settled=await run('unchanged-after-addition');
    assert.equal(settled.pulls+settled.uploads,0);
    fs.writeFileSync(path.join(out,'performance.json'),JSON.stringify({first,repeat,delta,settled},null,2));
    fs.writeFileSync(path.join(out,'android-completed.png'),adb('exec-out','screencap','-p'));
    await evaluate('FujimiMobile.setAllowCellular(false)');
    console.log(JSON.stringify({first,repeat,delta,settled}));
  } finally {
    socket?.close();
    adb('forward','--remove','tcp:9225');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
