// Read and operate the debug APK's actual WebView on the isolated emulator.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const output = path.resolve(__dirname, '../build/qa/settings-a-release');

(async () => {
  const target = (await (await fetch('http://127.0.0.1:9229/json/list')).json()).find(item => item.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target, 'No debug WebView target found');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
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
  try {
    await evaluate("(async()=>{await showView('settings');await new Promise(r=>setTimeout(r,900));return true})()");
    const result = await evaluate(`(() => {
      const cards=[...document.querySelectorAll('#settings-view .settings-panel')].filter(e=>!e.hidden);
      return {
        version:document.querySelector('#mobile-app-version').textContent,
        width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,
        headings:cards.map(e=>e.querySelector('h3').textContent),
        radius:getComputedStyle(cards[0]).borderRadius,
        selectedVoice:document.querySelector('#voice-list').textContent.trim(),
        canChooseVoice:!document.querySelector('#add-voice').disabled,
        syncDisabled:document.querySelector('#mobile-sync-now').disabled,
        generateDisabled:document.querySelector('#generate-daily').disabled,
        sourceCount:document.querySelector('#daily-source-total').textContent,
        infoVisible:!document.querySelector('#mobile-app-settings-panel').hidden
      };
    })()`);
    assert.equal(result.version, '1.0.2');
    assert(result.scrollWidth <= result.width + 1);
    assert.equal(result.canChooseVoice, true);
    assert.equal(result.syncDisabled, true);
    assert.equal(result.generateDisabled, true);
    assert.equal(result.infoVisible, true);
    assert.equal(result.headings.length, 6);
    fs.mkdirSync(output, { recursive: true });
    await evaluate('window.scrollTo(0,0);true');
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(output, 'native-settings-a-top.png'), Buffer.from(screenshot.data, 'base64'));
    await evaluate("document.querySelector('#add-voice').click();true");
    await evaluate("new Promise(resolve=>{const poll=()=>{if(!document.querySelector('#browser-voice-select').disabled)return resolve(true);setTimeout(poll,100)};poll()})");
    const selection = await evaluate("({open:document.querySelector('#voice-dialog').open,values:[...document.querySelector('#browser-voice-select').options].map(e=>e.value)})");
    assert.equal(selection.open, true);
    assert(selection.values.includes('ja-JP-KeitaNeural') && selection.values.includes('ja-JP-NanamiNeural'));
    await evaluate("document.querySelector('#cancel-voice-dialog').click();true");
    fs.writeFileSync(path.join(output, 'native-results.json'), JSON.stringify({ ...result, voiceDialog: selection }, null, 2));
    console.log(JSON.stringify({ ...result, voiceDialog: selection }, null, 2));
  } finally { socket.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
