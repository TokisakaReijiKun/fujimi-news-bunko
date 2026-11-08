// Real WebView acceptance. Root starts the isolated fixture/latest APK and forwards CDP.
// No service/emulator launch, API mocking, direct native playback, or user-library access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const host = process.env.FUJIMI_TEST_PC_BASE || 'http://127.0.0.1:18428';
const cdp = process.env.FUJIMI_TEST_CDP_BASE || 'http://127.0.0.1:9229';
const output = path.resolve(__dirname, '../build/qa/synced-audio');
assert(/^http:\/\/127\.0\.0\.1:18\d{3}$/.test(host), 'Use the isolated fixture on an 18xxx port.');
assert(/^http:\/\/127\.0\.0\.1:\d+$/.test(cdp), 'Use a local forwarded WebView CDP port.');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const edge = 'ja-JP-KeitaNeural';
let socket;

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const fixture = await (await fetch(host + '/api/test/synced-audio-fixture')).json();
  assert.equal(fixture.fixture, 'synced-audio-v1');
  const targets = await (await fetch(cdp + '/json/list')).json();
  const target = targets.find(value => value.url.startsWith('https://appassets.androidplatform.net/'));
  assert(target, 'Open the current APK and forward its WebView debugging socket first.');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(String(event.data));
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
  const touch = async (selector, fraction = .5) => {
    const point = await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled)throw Error('Control unavailable: '+${JSON.stringify(selector)});e.scrollIntoView({block:'center',behavior:'instant'});const r=e.getBoundingClientRect();const x=r.left+r.width*${fraction},y=r.top+r.height/2;if(!r.width||!r.height||!e.contains(document.elementFromPoint(x,y)))throw Error('Control obscured: '+${JSON.stringify(selector)});return {x,y};})()`);
    await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ ...point, radiusX: 1, radiusY: 1 }] });
    await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  };
  const choose = async (selector, value) => {
    // Dynamic article controls are enhanced by a MutationObserver after insertion.
    await waitFor(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return e && !e.disabled && e.nextElementSibling?.classList.contains('android-select-trigger') && !e.nextElementSibling.disabled && [...e.options].some(o=>o.value===${JSON.stringify(value)} && !o.disabled && !o.hidden);})()`);
    const item = await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});const index=[...e.options].findIndex(o=>o.value===${JSON.stringify(value)}&&!o.disabled);const trigger=e.nextElementSibling;return {trigger:'.android-select-trigger[aria-controls="'+trigger.getAttribute('aria-controls')+'"]',row:'#'+trigger.getAttribute('aria-controls')+' .android-select-option:nth-child('+(index+1)+')'};})()`);
    await touch(item.trigger);
    await waitFor(`document.querySelector(${JSON.stringify(item.trigger)}).getAttribute('aria-expanded')==='true' && document.querySelector(${JSON.stringify(item.row)})?.getAttribute('aria-disabled')==='false'`);
    await touch(item.row);
    await waitFor(`document.querySelector(${JSON.stringify(selector)}).value===${JSON.stringify(value)} && document.querySelector(${JSON.stringify(item.trigger)}).getAttribute('aria-expanded')==='false'`);
  };
  const screenshot = async filename => {
    const image = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(output, filename), Buffer.from(image.data, 'base64'));
  };
  const nativeStatus = () => evaluate(`JSON.parse(FujimiMobile.mediaStatus())`);
  const setBrowser = async (name, label) => evaluate(`(async()=>{const value=await api('/api/settings/browser-voice',{method:'PUT',body:JSON.stringify(${JSON.stringify({ name, label })})});applyBrowserVoiceSettings(value);return value;})()`);
  const normalizedPath = url => {
    const value = new URL(url, 'https://appassets.androidplatform.net');
    assert.equal(value.origin, 'https://appassets.androidplatform.net');
    assert.equal(value.hash, '', 'Filename # must be encoded, not treated as a URL fragment.');
    assert.equal(value.search, '');
    return decodeURIComponent(value.pathname);
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await waitFor(`typeof api==='function' && window.FujimiMobile?.mediaStatus`);

  // Pair and manually synchronize through the official settings controls.
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
  assert((await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`)).paired);
  await waitFor(`!document.querySelector('#mobile-sync-now').disabled`);
  await touch('#mobile-sync-now');
  await waitFor(`['completed','partial','failed'].includes(JSON.parse(FujimiMobile.mobileStatus()).sync_state)`, 120000);
  const sync = await evaluate(`JSON.parse(FujimiMobile.mobileStatus())`);
  assert.equal(sync.sync_state, 'completed', sync.sync_detail);

  // A stored custom recording must survive an unrelated global default Edge choice.
  await setBrowser(edge, '圭太');
  await evaluate(`(() => {window.__syncedAudioQA={requests:[],edgeCalls:[],errors:[]};const original=window.api;window.api=async function(path,options={}){const item={path,method:options.method||'GET',body:options.body||''};__syncedAudioQA.requests.push(item);try{return await original.apply(this,arguments);}catch(error){item.error=String(error.message);throw error;}};if(typeof mobileSpeak==='function'){const speak=mobileSpeak;window.mobileSpeak=function(){__syncedAudioQA.edgeCalls.push(true);return speak.apply(this,arguments);};}addEventListener('error',event=>__syncedAudioQA.errors.push(String(event.message)));})()`);
  const daily = await evaluate(`api('/api/daily?date=${fixture.date}')`);
  const article = daily.articles.find(value => value.url === fixture.article.url);
  assert(article, 'The synthetic legacy news article was not synced.');
  const books = await evaluate(`api('/api/books')`);
  const book = books.books.find(value => value.title === fixture.book.title);
  assert(book, 'The synthetic legacy book was not synced.');
  const articlePath = `/api/articles/${article.id}/assets/${fixture.article.recording.path}`;
  const bookPath = `/api/books/${book.id}/audio/${fixture.book.recording.path}`;
  const articleApi = `/api/articles/${article.id}`;
  const chapterApi = `/api/books/${book.id}/chapters/${fixture.book.chapter_id}`;
  const fresh = await evaluate(`api(${JSON.stringify(articleApi)})`);
  assert.equal(fresh.audio_status, 'ready');
  assert.equal(normalizedPath(fresh.audio_path), articlePath);
  const chapter = await evaluate(`api(${JSON.stringify(chapterApi)})`);
  assert.equal(chapter.chapter.audio.status, 'ready');
  assert.equal(normalizedPath(chapter.chapter.audio.url), bookPath);

  const playback = async (kind, root, expectedPath) => {
    await waitFor(`state.articleAudio?.mobileNative && state.articleAudio.root.closest(${JSON.stringify(root)}) && !document.querySelector(${JSON.stringify(root + ' .article-audio-player')}).hidden`);
    assert.equal(normalizedPath(await evaluate(`state.articleAudio.mediaSource`)), expectedPath);
    assert.equal(await evaluate(`state.articleAudio.audio.getAttribute('src')`), null, 'Media3 must own the long WAV without a second WebView decoder.');
    const player = root + ' .article-audio-player';
    await touch(player + ' .audio-player-toggle');
    await waitFor(`(()=>{const s=JSON.parse(FujimiMobile.mediaStatus());return s.playing && s.position>.4 && !s.error;})()`);
    const first = await nativeStatus();
    await delay(750);
    const advancing = await nativeStatus();
    assert(advancing.position > first.position + .3, JSON.stringify({ first, advancing }));
    assert(Math.abs(advancing.duration - 90) < .1, 'The actual full 90-second WAV must be decoded.');
    await screenshot(kind + '-playing.png');
    await touch(player + ' .audio-player-toggle');
    await waitFor(`!JSON.parse(FujimiMobile.mediaStatus()).playing`);
    const paused = await nativeStatus();
    await delay(500);
    assert(Math.abs((await nativeStatus()).position - paused.position) < .2, 'Paused audio keeps advancing.');
    await touch(player + ' .audio-player-progress', .65);
    await waitFor(`(()=>{const s=JSON.parse(FujimiMobile.mediaStatus());return s.position>45 && s.position<75 && !s.playing && !s.error;})()`);
    const sought = await nativeStatus();
    await screenshot(kind + '-paused-seek.png');
    await touch(player + ' .audio-player-toggle');
    await waitFor(`(()=>{const s=JSON.parse(FujimiMobile.mediaStatus());return s.playing && s.position>${sought.position + .3} && !s.error;})()`);
    const resumed = await nativeStatus();
    await touch(player + ' .audio-player-toggle');
    await waitFor(`!JSON.parse(FujimiMobile.mediaStatus()).playing`);
    console.log(kind + ': real Media3 play, advancing position, pause, seek, resume passed.');
    return { path: expectedPath, first, advancing, paused, sought, resumed, noWebViewDecoder: true };
  };

  await evaluate(`location.hash='#daily'`);
  await waitFor(`state.currentView==='daily' && document.querySelector('#history-select').options.length`);
  await choose('#history-select', fixture.date);
  await waitFor(`document.querySelector('#daily-list [data-article-id="${article.id}"] button')`);
  await touch(`#daily-list [data-article-id="${article.id}"] button`);
  const newsPlayback = await playback('news', '#reader-result', articlePath);

  await evaluate(`location.hash='#library'`);
  await waitFor(`state.currentView==='library' && !document.querySelector('#library-home').hidden && [...document.querySelectorAll('#library-home .book-card h3')].some(e=>e.textContent===${JSON.stringify(fixture.book.title)})`);
  await evaluate(`(() => {const card=[...document.querySelectorAll('#library-home .book-card')].find(e=>e.querySelector('h3')?.textContent===${JSON.stringify(fixture.book.title)});card.dataset.syncedAudioQa='book';})()`);
  await touch('#library-home [data-synced-audio-qa="book"]');
  await waitFor(`state.libraryChapter?.book.id===${book.id} && !document.querySelector('#book-reader').hidden`);
  const bookPlayback = await playback('book', '#book-reader', bookPath);
  const ordinary = await evaluate(`__syncedAudioQA`);
  assert.equal(ordinary.edgeCalls.length, 0, 'Ordinary saved-audio playback invoked Edge.');
  assert(!ordinary.requests.some(item => item.method === 'POST' && /\/(?:reread|edge-tts|tts|browser-speech)(?:\?|$)/.test(item.path)), JSON.stringify(ordinary.requests));
  const globalMode = await evaluate(`api('/api/settings/voice-mode')`);
  assert.equal(globalMode.mode, 'browser');
  assert.equal(globalMode.browser_voice_name, edge);

  // Explicitly request absent Alpha audio, then verify ordinary GET still retains the old recording.
  await setBrowser(fixture.missing_voice.id, fixture.missing_voice.name);
  await evaluate(`location.hash='#daily'`);
  await waitFor(`state.currentView==='daily' && document.querySelector('#daily-list [data-article-id="${article.id}"] button')`);
  await touch(`#daily-list [data-article-id="${article.id}"] button`);
  await waitFor(`document.querySelector('#reader-result .reread-voice')?.options.length>1`);
  await touch('#reader-result .reread-link');
  await waitFor(`!document.querySelector('#reader-result .reread-panel').hidden`);
  await choose('#reader-result .reread-voice', 'browser');
  await touch('#reader-result .reread');
  await waitFor(`document.querySelector('#reader-result .reread-task.is-failed') && /PC/.test(document.querySelector('#reader-result .reread-task').textContent)`);
  const missingNewsDetail = await evaluate(`document.querySelector('#reader-result .reread-task').textContent`);
  await screenshot('news-explicit-missing.png');
  const retainedNews = await evaluate(`api(${JSON.stringify(articleApi)})`);
  assert.equal(retainedNews.audio_status, 'ready');
  assert.equal(normalizedPath(retainedNews.audio_path), articlePath);
  const missingBook = await evaluate(`(async()=>{try{await api(${JSON.stringify(chapterApi + '/reread')},{method:'POST',body:JSON.stringify(${JSON.stringify({ mode: 'browser', browser_voice_name: fixture.missing_voice.id })})});return {unexpectedSuccess:true};}catch(error){return {detail:String(error.message)};}})()`);
  assert(!missingBook.unexpectedSuccess && /PC/.test(missingBook.detail), JSON.stringify(missingBook));
  const retainedBook = await evaluate(`api(${JSON.stringify(chapterApi)})`);
  assert.equal(retainedBook.chapter.audio.status, 'ready');
  assert.equal(normalizedPath(retainedBook.chapter.audio.url), bookPath);
  await setBrowser(edge, '圭太');
  const observed = await evaluate(`__syncedAudioQA`);
  assert.equal(observed.edgeCalls.length, 0);
  assert(!observed.requests.some(item => /\/(?:edge-tts|browser-speech)(?:\?|$)/.test(item.path)), JSON.stringify(observed.requests));
  assert.deepEqual(observed.errors, []);
  const results = { fixture: fixture.fixture, manualSync: sync.sync_state, defaultVoiceDuringPlayback: globalMode,
    newsPlayback, bookPlayback, ordinaryPlaybackGenerationRequests: 0,
    explicitMissing: { news: missingNewsDetail, book: missingBook.detail, ordinaryGetRetainsOriginal: true },
    requestEvidence: observed.requests };
  fs.writeFileSync(path.join(output, 'live-results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => socket?.close());
