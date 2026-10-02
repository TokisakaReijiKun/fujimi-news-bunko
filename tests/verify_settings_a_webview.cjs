// Operate the debug APK's actual WebView on an isolated emulator, never a phone.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const output = path.resolve(__dirname, '../build/qa/settings-a-release');
const adb = process.env.FUJIMI_TEST_ADB || 'C:/Android/Sdk/platform-tools/adb.exe';
const emulator = process.env.FUJIMI_TEST_EMULATOR || 'emulator-5584';
assert(/^emulator-\d+$/.test(emulator), 'Device acceptance requires an isolated emulator');
const device = (...args) => execFileSync(adb, ['-s', emulator, ...args], { timeout: 30000 });
const metricsOnly = process.argv.includes('--metrics-only');

(async () => {
  const targets = await (await fetch('http://127.0.0.1:9229/json/list')).json();
  const target = targets.find(item => item.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target, 'No debug WebView target; forward tcp:9229 to the current WebView PID first');
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
  const waitFor = async condition => {
    const until = Date.now() + 20000;
    while (Date.now() < until) {
      if (await evaluate(`Boolean(${condition})`)) return;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('WebView condition timed out: ' + condition);
  };
  const touch = async selector => {
    const point = await evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element || element.disabled) throw new Error('Missing/disabled touch target');
      element.scrollIntoView({block:'center',inline:'nearest'});
      const rect=element.getBoundingClientRect(), x=rect.left+rect.width/2, y=rect.top+rect.height/2;
      if (!rect.width || !rect.height || x<0 || y<0 || x>innerWidth || y>innerHeight) throw new Error('Unreachable touch target');
      if (!element.contains(document.elementFromPoint(x,y))) throw new Error('Touch target is covered');
      return {x,y};
    })()`);
    await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, radiusX: 1, radiusY: 1 }] });
    await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  };
  const choose = async (id, value) => {
    await touch(`[data-android-select="${id}"]`);
    await waitFor(`document.querySelector('[data-android-select="${id}"]').getAttribute('aria-expanded')==='true'`);
    const optionId = await evaluate(`(() => {
      const select=document.getElementById(${JSON.stringify(id)});
      const index=[...select.options].findIndex(option=>option.value===${JSON.stringify(value)});
      if (index<0 || select.options[index].disabled) throw new Error('Requested option is unavailable');
      const trigger=document.querySelector('[data-android-select="${id}"]');
      return document.getElementById(trigger.getAttribute('aria-controls')).children[index].id;
    })()`);
    await touch('#' + optionId);
    await waitFor(`document.getElementById(${JSON.stringify(id)}).value===${JSON.stringify(value)}`);
  };
  const snapshot = async name => {
    const png = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(output, name + '.png'), Buffer.from(png.data, 'base64'));
  };
  let original;
  try {
    fs.mkdirSync(output, { recursive: true });
    await evaluate("(async()=>{await showView('settings');window.scrollTo(0,0);return true})()");
    await waitFor("document.querySelector('#voice-list').children.length>0 && !document.querySelector('#mobile-app-settings-panel').hidden");
    const result = await evaluate(`(() => {
      const cards=[...document.querySelectorAll('#settings-view .settings-panel')].filter(e=>!e.hidden);
      const probe=document.createElement('div');probe.style.cssText='position:fixed;opacity:0;pointer-events:none;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)';document.body.append(probe);
      const safeTop=parseFloat(getComputedStyle(probe).paddingTop), safeBottom=parseFloat(getComputedStyle(probe).paddingBottom);probe.remove();
      const bounds=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,width:r.width,height:r.height}};
      const font=selector=>{const s=getComputedStyle(document.querySelector(selector));return {fontSize:s.fontSize,lineHeight:s.lineHeight,marginTop:s.marginTop}};
      return {
        version:document.querySelector('#mobile-app-version').textContent,
        width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,innerHeight:innerHeight,dpr:devicePixelRatio,
        safeTop,safeBottom,bar:bounds('.mobile-app-bar'),kicker:font('#mobile-current-kicker'),title:font('#mobile-current-view'),description:bounds('#mobile-current-description'),
        shellPadding:getComputedStyle(document.querySelector('.content-shell')).paddingTop,firstCard:bounds('#settings-view .settings-panel'),
        headings:cards.map(e=>e.querySelector('h3').textContent),radius:getComputedStyle(cards[0]).borderRadius,
        selectedVoice:document.querySelector('#voice-list').textContent.trim(),canChooseVoice:!document.querySelector('#add-voice').disabled,
        syncDisabled:document.querySelector('#mobile-sync-now').disabled,generateDisabled:document.querySelector('#generate-daily').disabled,
        automaticDisabled:document.querySelector('#daily-mode [data-mode=automatic]').disabled,
        sourceCount:document.querySelector('#daily-source-total').textContent,infoVisible:!document.querySelector('#mobile-app-settings-panel').hidden
      };
    })()`);
    await snapshot('native-settings-a-top');
    fs.writeFileSync(path.join(output, 'native-settings-screen.png'), device('exec-out', 'screencap', '-p'));
    device('shell', 'uiautomator', 'dump', '/sdcard/fujimi-header-qa.xml');
    const hierarchy = device('shell', 'cat', '/sdcard/fujimi-header-qa.xml').toString('utf8');
    const webviewNode = (hierarchy.match(/<node\b[^>]*>/g) || []).find(node => node.includes('class="android.webkit.WebView"'));
    const bounds = webviewNode?.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);
    const nativeBounds = bounds ? { left: Number(bounds[1]), top: Number(bounds[2]), right: Number(bounds[3]), bottom: Number(bounds[4]) } : null;
    result.nativeBounds = nativeBounds;
    result.nativeDensity = device('shell', 'wm', 'density').toString('utf8').trim();
    if (nativeBounds) {
      const scale = (nativeBounds.right - nativeBounds.left) / result.width;
      result.nativePixelsPerCssPixel = scale;
      result.firstCardScreenY = nativeBounds.top + result.firstCard.top * scale;
      result.cssSafeTopScreenPixels = result.safeTop * scale;
      result.possibleDuplicateTopInset = nativeBounds.top > 0 && result.safeTop > 0;
    }
    if (metricsOnly) {
      fs.writeFileSync(path.join(output, 'native-header-metrics.json'), JSON.stringify(result, null, 2));
      console.log(JSON.stringify(result, null, 2));
      return;
    }
    assert.equal(result.version, '1.0.5');
    assert(result.scrollWidth <= result.width + 1);
    assert.equal(result.canChooseVoice, true);
    assert.equal(result.syncDisabled, true);
    assert.equal(result.generateDisabled, false);
    assert.equal(result.automaticDisabled, false);
    assert.equal(result.infoVisible, true);
    assert.equal(result.headings.length, 6);
    assert.equal(result.bar.height, 112 + result.safeTop, 'APK保留原版页面标题栏高112px');
    assert.equal(result.kicker.fontSize, '10.88px');
    assert.equal(result.title.fontSize, '21.12px');
    assert.equal(result.safeTop, 0, '原生父容器已避让系统栏，页面不应再叠加同一顶部safe-area');
    original = await evaluate("(async()=>({library:await api('/api/settings/library'),voice:await api('/api/settings/voice-mode')}))()");
    const chosenSort = original.library.sort === 'series' ? 'imported' : 'series';
    const chosenVoice = original.voice.browser_voice_name === 'ja-JP-NanamiNeural' ? 'ja-JP-KeitaNeural' : 'ja-JP-NanamiNeural';
    const chosenLabel = chosenVoice === 'ja-JP-KeitaNeural' ? '圭太' : '七海';
    await choose('library-sort-setting', chosenSort);
    await waitFor(`state.librarySort===${JSON.stringify(chosenSort)}`);
    assert.equal(await evaluate("(async()=>(await api('/api/settings/library')).sort)()"), chosenSort);
    await touch('#add-voice');
    await waitFor("!document.querySelector('#browser-voice-select').disabled");
    await touch('[data-android-select="browser-voice-select"]');
    await snapshot('native-voice-dropdown-open');
    assert.equal(await evaluate("document.querySelector('#browser-voice-select').getClientRects().length"), 0, 'APK隐藏原select以阻止原生radio modal');
    device('shell', 'input', 'keyevent', '4');
    await waitFor("document.querySelector('[data-android-select=browser-voice-select]').getAttribute('aria-expanded')==='false'");
    assert.equal(await evaluate("document.querySelector('#voice-dialog').open"), true, '系统返回先关闭列表');
    await choose('browser-voice-select', chosenVoice);
    await touch('#submit-voice');
    await waitFor(`!document.querySelector('#voice-dialog').open && document.querySelector('#voice-list').textContent.includes(${JSON.stringify(chosenLabel)})`);
    assert.equal(await evaluate("(async()=>(await api('/api/settings/voice-mode')).browser_voice_name)()"), chosenVoice);
    await send('Page.reload', { ignoreCache: true });
    await waitFor(`typeof window.api==='function' && document.querySelector('#voice-list').textContent.includes(${JSON.stringify(chosenLabel)}) && document.querySelector('#library-sort-setting').value===${JSON.stringify(chosenSort)}`);
    await touch('#add-voice');
    await waitFor("document.querySelector('#voice-dialog').open");
    device('shell', 'input', 'keyevent', '4');
    await waitFor("!document.querySelector('#voice-dialog').open");
    const schedule = await evaluate("api('/api/settings/daily-schedule')");
    assert.equal(schedule.scheduler_available, true);
    fs.writeFileSync(path.join(output, 'native-results.json'), JSON.stringify({ ...result, dropdown: 'passed', persistence: 'passed', androidBack: 'passed', scheduleAvailable: schedule.scheduler_available }, null, 2));
    console.log(JSON.stringify({ ...result, dropdown: 'passed', persistence: 'passed', androidBack: 'passed', scheduleAvailable: schedule.scheduler_available }, null, 2));
  } finally {
    try {
      if (original) {
        const libraryRequest = { method: 'PUT', body: JSON.stringify(original.library) };
        const voiceRequest = { method: 'PUT', body: JSON.stringify({ name: original.voice.browser_voice_name, label: original.voice.browser_voice_label }) };
        await evaluate(`(async()=>{await api('/api/settings/library',${JSON.stringify(libraryRequest)});await api('/api/settings/browser-voice',${JSON.stringify(voiceRequest)});await showView('settings');return true})()`);
      }
    } finally { socket.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
