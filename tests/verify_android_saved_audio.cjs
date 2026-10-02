// Live formal WebView verification on an emulator. Only this run's synthetic article is written.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const adb = 'C:/Android/Sdk/platform-tools/adb.exe';
const serial = process.env.FUJIMI_QA_SERIAL || 'emulator-5554';
assert(serial.startsWith('emulator-'), 'This test uses a temporary fixture on an emulator only.');
const pkg = 'jp.fujimi.newsbunko.next';
const device = (...args) => execFileSync(adb, ['-s', serial, ...args], { timeout: 30000 }).toString().trim();
const output = path.resolve(__dirname, '../build/qa/android-saved-audio');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, limit = 30000) {
  const end = Date.now() + limit;
  while (Date.now() < end) { const value = await read(); if (value) return value; await pause(200); }
  throw new Error('Saved audio verification timed out.');
}

(async () => {
  device('shell', 'am', 'start', '-n', pkg + '/.MainActivity');
  const pid = await until(() => device('shell', 'pidof', pkg));
  device('forward', 'tcp:9233', 'localabstract:webview_devtools_remote_' + pid);
  const target = await until(async () => (await (await fetch('http://127.0.0.1:9233/json/list')).json()).find(x => x.url.startsWith('https://appassets.androidplatform.net/')));
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('WebView debugger connection timeout')), 10000);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', error => { clearTimeout(timer); reject(error); }, { once: true });
  });
  const callbacks = new Map(); let sequence = 0;
  socket.addEventListener('message', e => { const value = JSON.parse(String(e.data)); if (callbacks.has(value.id)) { callbacks.get(value.id)(value); callbacks.delete(value.id); } });
  const evaluate = expression => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { callbacks.delete(id); reject(new Error('WebView evaluation timeout')); }, 90000);
    callbacks.set(id, value => {
      clearTimeout(timer);
      if (value.error || value.result?.exceptionDetails) reject(new Error(JSON.stringify(value.error || value.result.exceptionDetails)));
      else resolve(value.result.result.value);
    });
    socket.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, userGesture: true, awaitPromise: true, returnByValue: true } }));
  });
  const local = fs.mkdtempSync(path.join(os.tmpdir(), 'fujimi-saved-audio-'));
  const title = '音声保存の一時検証-' + Date.now();
  const folder = '/storage/emulated/0/富士見新聞文庫/data/articles/2099-01-02/' + title;
  let created = false, voiceBefore, readerBefore;
  try {
    await until(() => evaluate('typeof api === "function" && typeof state !== "undefined" && Boolean(state.browserVoiceName)'));
    voiceBefore = await evaluate('api("/api/settings/voice-mode")');
    readerBefore = await evaluate('sessionStorage.getItem(READER_ARTICLE_KEY)');
    await evaluate(`api('/api/settings/browser-voice',{method:'PUT',body:JSON.stringify({name:'ja-JP-KeitaNeural',label:'システム音声'})}).then(applyBrowserVoiceSettings)`);
    const days = await evaluate('api("/api/days")');
    const articles = (await Promise.all(days.map(day => evaluate(`api(${JSON.stringify('/api/daily?date=' + day)})`)))).flatMap(x => x.articles || []);
    const id = Math.max(0, ...articles.map(x => Number(x.id))) + 100;
    const paragraphs = ['今日は晴れです。', '明日は図書館に行きます。'];
    const texts = { 'original.txt': paragraphs.join('\n\n'), 'translation.txt': '', 'furigana.html': '' };
    const specs = {};
    for (const [name, text] of Object.entries(texts)) {
      fs.writeFileSync(path.join(local, name), text);
      specs[name] = { sha256: crypto.createHash('sha256').update(text).digest('hex'), field: name === 'original.txt' ? 'paragraphs' : name === 'translation.txt' ? 'translated_paragraphs' : 'furigana_paragraphs', paragraphs: name === 'original.txt' ? [[0, paragraphs[0].length], [paragraphs[0].length + 2, text.length]] : [] };
    }
    const manifest = { schema_version: 1, revision: 1, article: { id, title, url: 'https://example.test/saved-audio-' + id, source_name: '一時検証', status: 'ready', voice_mode: 'browser', edition_dates: ['2099-01-02'], created_at: '2099-01-02T00:00:00+08:00', bookmarked: false }, text_files: specs, assets: [] };
    fs.writeFileSync(path.join(local, 'article.json'), JSON.stringify(manifest));
    device('shell', 'mkdir', '-p', folder + '/audio', folder + '/media'); created = true;
    for (const name of Object.keys(texts).concat('article.json')) device('push', path.join(local, name), folder + '/' + name);
    await evaluate(`window.__audioQaCalls=[];window.__audioQaOriginalApi=api;api=async function(...args){window.__audioQaCalls.push({path:args[0],method:args[1]?.method||'GET'});return window.__audioQaOriginalApi(...args)};void 0`);
    const open = () => evaluate(`api('/api/articles/${id}').then(openArticleInReader)`);
    await open();
    await evaluate('document.querySelector("#reader-result .audio-player-toggle").click()');
    await until(() => evaluate('Boolean(state.articleAudio?.audio?.currentTime > 0.2 && !state.articleAudio.audio.paused)'));
    const saved = await evaluate(`api('/api/articles/${id}')`);
    assert.equal(saved.audio_status, 'ready'); assert.equal(saved.audio_voice_name, 'ja-JP-KeitaNeural');
    assert.equal(saved.audio_segments.length, 2);
    assert(saved.audio_path.endsWith(encodeURIComponent('圭太_' + title + '.mp3')));
    const before = device('shell', 'sha256sum', folder + '/audio/圭太_' + title + '.mp3').split(/\s/)[0];
    const originalHash = device('shell', 'sha256sum', folder + '/original.txt').split(/\s/)[0];
    assert.equal(originalHash, specs['original.txt'].sha256);
    await evaluate('stopArticlePlayback();void 0');
    const postsBefore = await evaluate('window.__audioQaCalls.filter(x=>x.path.endsWith("/edge-tts") && x.method==="POST").length');
    assert.equal(postsBefore, 1);
    // Fail any synthesis request while allowing article reads and the saved MP3 stream.
    await evaluate('api=async function(...args){if(args[0].endsWith("/edge-tts"))throw new Error("Network blocked by verification");return window.__audioQaOriginalApi(...args)};void 0');
    await open();
    await evaluate('document.querySelector("#reader-result .audio-player-toggle").click()');
    await until(() => evaluate('Boolean(state.articleAudio?.audio?.currentTime > 0.2 && !state.articleAudio.audio.paused)'));
    await evaluate('document.querySelectorAll("#reader-result .japanese")[1].click()');
    const seek = await until(() => evaluate('state.articleAudio && state.articleAudio.audio.currentTime >= state.articleAudio.timeline[1]?.speechStart ? {position:state.articleAudio.audio.currentTime,paragraphStart:state.articleAudio.timeline[1].speechStart}:false'));
    const after = device('shell', 'sha256sum', folder + '/audio/圭太_' + title + '.mp3').split(/\s/)[0];
    assert.equal(before, after);
    fs.mkdirSync(output, { recursive: true });
    const evidence = { device: serial, version: await evaluate('JSON.parse(FujimiMobile.mobileStatus()).app_version'), data: await evaluate('JSON.parse(FujimiMobile.mobileStatus()).data_path'), firstClickSynthesisRequests: postsBefore, filename: '圭太_' + title + '.mp3', sha256: after, paragraphs: saved.audio_segments.length, savedPlayback: true, replayWithoutSynthesis: true, paragraphSeek: seek, originalUnchanged: true };
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } finally {
    try {
      await evaluate('stopArticlePlayback();if(window.__audioQaOriginalApi)api=window.__audioQaOriginalApi;void 0');
      if (voiceBefore) await evaluate(`api('/api/settings/browser-voice',{method:'PUT',body:JSON.stringify({name:${JSON.stringify(voiceBefore.browser_voice_name)},label:${JSON.stringify(voiceBefore.browser_voice_label)}})}).then(applyBrowserVoiceSettings)`);
      if (readerBefore !== undefined) await evaluate(`sessionStorage.${readerBefore === null ? 'removeItem(READER_ARTICLE_KEY)' : 'setItem(READER_ARTICLE_KEY,' + JSON.stringify(readerBefore) + ')'};void 0`);
      await evaluate('showView("daily")');
    } catch {}
    socket.close();
    if (created) device('shell', 'rm', '-r', folder);
    fs.rmSync(local, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
