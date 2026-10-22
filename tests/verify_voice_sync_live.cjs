// Real formal-page acceptance. Start the isolated PC fixture and latest emulator APK first.
// This script neither launches a service/emulator nor mocks any API or native response.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const host = process.env.FUJIMI_TEST_PC_BASE || 'http://127.0.0.1:18428';
const cdp = process.env.FUJIMI_TEST_CDP_BASE || 'http://127.0.0.1:9229';
const output = path.resolve(__dirname, '../build/qa/voice-sync');
assert(/^http:\/\/127\.0\.0\.1:18\d{3}$/.test(host), 'Use run_device_sync_fixture.py on an isolated 18xxx port.');
assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(cdp), 'Only local forwarded WebView debugging is allowed.');
const localIds = ['kokoro:jf_alpha', 'voicevox:8', 'voicevox:109', 'voicevox:107', 'voicevox:16', 'voicevox:69', 'voicevox:74', 'voicevox:89', 'voicevox:47'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const fixture = await (await fetch(host + '/api/test/voice-sync-fixture')).json();
  assert.equal(fixture.fixture, 'voice-sync-v1');
  assert(fixture.port >= 18000 && fixture.port <= 18999 && fixture.sync_port >= 18000 && fixture.sync_port <= 18999);
  assert.equal(fixture.voice.name, '同期テスト声線');
  const targets = await (await fetch(cdp + '/json/list')).json();
  const target = targets.find(value => value.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target, 'Open the latest APK in the isolated emulator and forward its WebView CDP port.');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  const network = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(String(event.data));
    if (message.method === 'Network.requestWillBeSent') network.push(message.params.request.url);
    if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timed out')); }, 30000);
    pending.set(id, message => { clearTimeout(timer); message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result); });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const waitFor = async (expression, timeout = 30000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      if (await evaluate(`(async()=>Boolean(await (${expression})))()`)) return;
      await delay(150);
    }
    throw new Error('Timed out: ' + expression);
  };
  const touch = async selector => {
    const point = await evaluate(`(() => {const element=document.querySelector(${JSON.stringify(selector)}); if(!element || element.disabled)throw Error('Control unavailable: '+${JSON.stringify(selector)}); element.scrollIntoView({block:'center',behavior:'instant'}); const rect=element.getBoundingClientRect(); const x=rect.left+rect.width/2,y=rect.top+rect.height/2; if(!rect.width || !rect.height || !element.contains(document.elementFromPoint(x,y)))throw Error('Control obscured: '+${JSON.stringify(selector)});return {x,y};})()`);
    await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, radiusX: 1, radiusY: 1 }] });
    await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  };
  const screenshot = async filename => {
    const image = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(output, filename), Buffer.from(image.data, 'base64'));
  };
  const installObservation = () => evaluate(`(() => {
    if(window.__voiceQA)return;
    window.__voiceQA={requests:[],edgeCalls:[],errors:[]};
    const original=window.api;
    window.api=async function(path,options={}){const record={path,method:options.method||'GET'}; window.__voiceQA.requests.push(record); try{return await original.apply(this,arguments);}catch(error){record.error=String(error.message);throw error;}};
    if(typeof window.mobileSpeak==='function'){const speak=window.mobileSpeak;window.mobileSpeak=function(){window.__voiceQA.edgeCalls.push({name:arguments[3]||''});return speak.apply(this,arguments);};}
    addEventListener('error',event=>window.__voiceQA.errors.push(String(event.message)));
  })()`);
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await waitFor(`typeof api==='function' && window.FujimiMobile?.mobileStatus`);

  // Perform the same explicit pairing and sync actions as the user, against the fixture only.
  await fetch(host + '/api/settings/device-sync', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: true }) });
  const pairing = await (await fetch(host + '/api/settings/device-sync')).json();
  assert(pairing.enabled && /^\d{6}$/.test(pairing.pairing_code));
  assert.equal(new URL(pairing.url).port, String(fixture.sync_port));
  await evaluate(`location.hash='#settings'`);
  await waitFor(`document.querySelector('#mobile-windows-code') && !document.querySelector('#mobile-settings-panel').hidden`);
  if (!await evaluate(`document.querySelector('#mobile-allow-cellular').checked`)) await touch('#mobile-allow-cellular');
  await evaluate(`(() => {for(const [id,value] of ${JSON.stringify([['mobile-windows-address', pairing.url], ['mobile-windows-code', pairing.pairing_code]])}){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}})()`);
  await touch('#mobile-save-windows');
  await waitFor(`!document.querySelector('#mobile-save-windows').disabled`, 45000);
  const connection = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
  assert(connection.paired, connection.connection_detail);
  await waitFor(`!document.querySelector('#mobile-sync-now').disabled`);
  await touch('#mobile-sync-now');
  await waitFor(`['completed','partial','failed'].includes(JSON.parse(FujimiMobile.mobileStatus()).sync_state)`, 120000);
  const sync = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
  assert.equal(sync.sync_state, 'completed', sync.sync_detail);
  console.log('Real manual voice sync completed.');

  const voices = await evaluate(`api('/api/settings/voices')`);
  const voice = voices.find(value => value.name === fixture.voice.name);
  assert(voice, 'The synced custom reference voice is absent from settings.');
  assert.equal(voice.id, fixture.voice.id);
  assert.equal(voice.read_only, true);
  assert.equal(voice.saved_audio_only, true);
  const catalog = await evaluate(`api('/api/browser-voices')`);
  for (const id of localIds) {
    const item = catalog.find(value => value.id === id);
    assert(item, 'Missing synced browser voice: ' + id);
    assert.equal(item.saved_audio_only, true, id);
    assert.equal(item.local, false, id);
    assert.equal(item.available, true, id);
  }
  const daily = await evaluate(`api('/api/daily?date=${fixture.date}')`);
  const article = daily.articles.find(value => value.url === fixture.article.url);
  const missing = daily.articles.find(value => value.url === fixture.missing.url);
  assert(article && missing, 'Both sound-bearing and sound-free fixture articles must be synced.');
  await installObservation();

  const showSettings = async () => {
    await evaluate(`stopArticlePlayback();location.hash='#settings'`);
    await waitFor(`document.querySelector('#settings-view').classList.contains('active') || state.currentView==='settings'`);
    await evaluate(`loadVoices()`);
    await waitFor(`[...document.querySelectorAll('#voice-list .voice-name')].some(e=>e.textContent===${JSON.stringify(fixture.voice.name)})`);
  };
  const markVoiceRow = async browser => {
    await evaluate(`(() => {document.querySelectorAll('[data-voice-qa]').forEach(e=>e.removeAttribute('data-voice-qa'));const row=[...document.querySelectorAll('#voice-list .voice-row')].find(e=>${browser ? "e.querySelector('.voice-mark')?.textContent==='B'" : `e.querySelector('.voice-name')?.textContent===${JSON.stringify(fixture.voice.name)}`});if(!row)throw Error('Voice row unavailable');row.dataset.voiceQa='selected';})()`);
  };
  const openRowAction = async action => {
    if (await evaluate(`Boolean(document.querySelector('[data-voice-qa] .voice-actions-menu'))`)) await touch('[data-voice-qa] .voice-actions-menu summary');
    await touch('[data-voice-qa] .' + action);
  };
  const useCustom = async () => {
    await showSettings();
    await markVoiceRow(false);
    if (!await evaluate(`document.querySelector('[data-voice-qa] .select').disabled`)) await openRowAction('select');
    await waitFor(`(async()=>{const m=await api('/api/settings/voice-mode');return m.mode==='voice' && m.voice_id===${voice.id};})()`);
    await screenshot('settings-custom.png');
  };
  const useAlpha = async () => {
    await showSettings();
    await markVoiceRow(true);
    await openRowAction('edit');
    await waitFor(`document.querySelector('#voice-dialog').open && !document.querySelector('#browser-voice-select').disabled`);
    const index = await evaluate(`[...document.querySelector('#browser-voice-select').options].findIndex(option=>option.value==='kokoro:jf_alpha' && !option.disabled)`);
    assert(index >= 0, 'アルファ is not selectable in the formal voice dialog.');
    await touch('.android-select-trigger[data-android-select="browser-voice-select"]');
    const optionSelector = await evaluate(`(() => {const trigger=document.querySelector('.android-select-trigger[data-android-select="browser-voice-select"]');return '#'+trigger.getAttribute('aria-controls')+' .android-select-option:nth-child(${index + 1})';})()`);
    await touch(optionSelector);
    await touch('#submit-voice');
    await waitFor(`!document.querySelector('#voice-dialog').open`);
    await waitFor(`(async()=>{const m=await api('/api/settings/voice-mode');return m.mode==='browser' && m.browser_voice_name==='kokoro:jf_alpha';})()`);
    await screenshot('settings-alpha.png');
  };
  const getArticle = id => evaluate(`api('/api/articles/${id}')`);
  const assetEvidence = async url => evaluate(`(async () => {
    const url=new URL(${JSON.stringify(url)},location.origin),parts=url.pathname.split('/'); if(url.origin!==location.origin || parts[1]!=='api' || parts[2]!=='articles' || !Number.isInteger(Number(parts[3])) || parts[4]!=='assets' || parts[5]!=='audio')throw Error('Unexpected audio URL');
    const response=await fetch(url); if(!response.ok)throw Error('Audio request failed: '+response.status);
    const bytes=await response.arrayBuffer(),view=new DataView(bytes);
    const ascii=(offset,count)=>String.fromCharCode(...new Uint8Array(bytes,offset,count));
    if(ascii(0,4)!=='RIFF' || ascii(8,4)!=='WAVE')throw Error('Not an actual WAV');
    let rate=0,channels=0,bits=0,dataOffset=0,dataSize=0;
    for(let offset=12;offset+8<=bytes.byteLength;){const kind=ascii(offset,4),size=view.getUint32(offset+4,true);if(kind==='fmt '){if(view.getUint16(offset+8,true)!==1)throw Error('Not PCM');channels=view.getUint16(offset+10,true);rate=view.getUint32(offset+12,true);bits=view.getUint16(offset+22,true);}if(kind==='data'){dataOffset=offset+8;dataSize=size;break;}offset+=8+size+(size%2);}
    if(channels!==1 || bits!==16 || !rate || !dataSize)throw Error('Unexpected WAV format');
    let crossings=0,last=0;const samples=dataSize/2;for(let i=0;i<samples;i++){const value=view.getInt16(dataOffset+i*2,true);if(last<=0 && value>0)crossings++;last=value;}
    const sha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
    return {path:decodeURIComponent(url.pathname),sha256,seconds:samples/rate,frequency:crossings/(samples/rate),bytes:bytes.byteLength};
  })()`);
  const play = async recording => {
    const value = await getArticle(article.id);
    assert.equal(value.audio_status, 'ready');
    const expectedPath = `/api/articles/${article.id}/assets/${recording.path}`;
    assert.equal(decodeURIComponent(new URL(value.audio_path, 'https://appassets.androidplatform.net').pathname), expectedPath);
    const evidence = await assetEvidence(value.audio_path);
    assert.equal(evidence.sha256, recording.sha256);
    assert.equal(evidence.seconds, recording.duration);
    assert(Math.abs(evidence.frequency - recording.frequency) < 2, JSON.stringify(evidence));
    await evaluate(`openArticleInReader(${JSON.stringify(value)})`);
    await waitFor(`state.articleAudio?.mobileNative && !document.querySelector('#reader-result .article-audio-player').hidden`);
    await touch('#reader-result .audio-player-toggle');
    await waitFor(`(()=>{const s=JSON.parse(FujimiMobile.mediaStatus());return s.playing && s.position>.25 && !s.error;})()`);
    const playback = await evaluate(`({status:JSON.parse(FujimiMobile.mediaStatus()),source:state.articleAudio.mediaSource})`);
    assert.equal(decodeURIComponent(new URL(playback.source).pathname), expectedPath);
    assert(Math.abs(playback.status.duration - recording.duration) < .05);
    await screenshot(`playing-${recording.mode}.png`);
    await evaluate(`stopArticlePlayback()`);
    console.log(`Actual local WAV playback passed: ${recording.name} (${recording.frequency} Hz).`);
    return { ...evidence, playback: playback.status, name: recording.name };
  };

  await useCustom();
  const customPlayback = await play(fixture.article.recordings.find(value => value.mode === 'voice'));
  await useAlpha();
  const alphaPlayback = await play(fixture.article.recordings.find(value => value.voice_id === 'kokoro:jf_alpha'));

  await send('Page.reload', { ignoreCache: true });
  await waitFor(`typeof api==='function' && !window.__voiceQA && document.readyState==='complete'`);
  await installObservation();
  const persisted = await evaluate(`api('/api/settings/voice-mode')`);
  assert.equal(persisted.mode, 'browser');
  assert.equal(persisted.browser_voice_name, 'kokoro:jf_alpha');
  await showSettings();
  assert((await evaluate(`document.querySelector('#active-voice-badge').textContent`)).includes('アルファ'));
  const reloadedPlayback = await play(fixture.article.recordings.find(value => value.voice_id === 'kokoro:jf_alpha'));

  const missingResults = [];
  for (const mode of ['browser', 'voice']) {
    if (mode === 'voice') await useCustom();
    const before = await evaluate(`({requests:__voiceQA.requests.length,edge:__voiceQA.edgeCalls.length})`);
    const value = await getArticle(missing.id);
    assert.equal(value.audio_status, 'unavailable');
    assert.equal(value.audio_path, '');
    assert(/(?:PC|电脑).*(?:生成|合成).*同步/.test(value.audio_unavailable_detail), value.audio_unavailable_detail);
    await evaluate(`openArticleInReader(${JSON.stringify(value)})`);
    await waitFor(`document.querySelector('#reader-result .reread-task') && !document.querySelector('#reader-result .reread-task').hidden && /(?:PC|电脑)/.test(document.querySelector('#reader-result .reread-task').textContent)`);
    await delay(500);
    const after = await evaluate(`({requests:__voiceQA.requests.slice(${before.requests}),edge:__voiceQA.edgeCalls.length,playing:JSON.parse(FujimiMobile.mediaStatus()).playing,playerHidden:document.querySelector('#reader-result .article-audio-player').hidden,detail:document.querySelector('#reader-result .reread-task').textContent})`);
    assert.equal(after.edge, before.edge, 'Missing saved audio must never invoke Edge speech.');
    assert(!after.requests.some(request => /\/(?:edge-tts|browser-speech)(?:\?|$)/.test(request.path)), JSON.stringify(after.requests));
    assert.equal(after.playing, false);
    assert.equal(after.playerHidden, true);
    await screenshot(`missing-${mode}.png`);
    missingResults.push({ mode, detail: after.detail, noEdgeRequests: true, playerHidden: true });
  }
  const observed = await evaluate(`__voiceQA`);
  assert.deepEqual(observed.errors, []);
  const results = { manualSync: sync.sync_state, customVoice: { name: voice.name, id: voice.id, saved_audio_only: voice.saved_audio_only },
    localBrowserIds: localIds, customPlayback, alphaPlayback, persisted: { mode: persisted.mode, browser_voice_name: persisted.browser_voice_name },
    reloadedPlayback, missing: missingResults,
    webViewAudioRequests: network.filter(url => /\/api\/articles\/\d+\/assets\/audio\//.test(url)).map(url => decodeURIComponent(new URL(url).pathname)) };
  fs.writeFileSync(path.join(output, 'live-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => socket?.close());
