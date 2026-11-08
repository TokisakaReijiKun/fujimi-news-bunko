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
const device = (...args) => {
  try { return execFileSync(adb, ['-s', serial, ...args], { timeout: 30000 }).toString().trim(); }
  catch (error) { if (args.includes('pidof')) return ''; throw error; }
};
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
  const target = await until(async () => {
    try { return (await (await fetch('http://127.0.0.1:9233/json/list')).json()).find(x => x.url.startsWith('https://appassets.androidplatform.net/')); }
    catch { return false; } // A fresh WebView may not have opened its debugger socket yet.
  });
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
    socket.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
  });
  const tap = async selector => {
    const point = await evaluate(`(() => { const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:Math.round((r.left+r.width/2)*devicePixelRatio),y:Math.round((Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2*devicePixelRatio)};})()`);
    device('shell', 'input', 'tap', String(point.x), String(point.y));
  };
  const local = fs.mkdtempSync(path.join(os.tmpdir(), 'fujimi-saved-audio-'));
  const title = '音声3.4%20保存の一時検証-' + Date.now();
  const folder = '/storage/emulated/0/富士見新聞文庫/data/articles/2099-01-02/' + title;
  let created = false, voiceBefore, readerBefore, rateBefore;
  try {
    await until(() => evaluate('typeof api === "function" && typeof state !== "undefined" && Boolean(state.browserVoiceName)'));
    voiceBefore = await evaluate('api("/api/settings/voice-mode")');
    readerBefore = await evaluate('sessionStorage.getItem(READER_ARTICLE_KEY)');
    rateBefore = await evaluate('localStorage.getItem("fujimi-playback-rate")');
    await evaluate(`api('/api/settings/browser-voice',{method:'PUT',body:JSON.stringify({name:'ja-JP-KeitaNeural',label:'システム音声'})}).then(applyBrowserVoiceSettings)`);
    const days = await evaluate('api("/api/days")');
    const articles = (await Promise.all(days.map(day => evaluate(`api(${JSON.stringify('/api/daily?date=' + day)})`)))).flatMap(x => x.articles || []);
    const id = Math.max(0, ...articles.map(x => Number(x.id))) + 100;
    const paragraphs = ['今日は図書館で新聞を読みます。'.repeat(82), '二つ目の段落です。ここでは日本のニュースについて話します。経済や社会の記事も読みます。', '最後の段落です。図書館の本を棚に戻して、家に帰ります。また明日も新聞を読みましょう。'];
    let cursor = 0;
    const spans = paragraphs.map(p => { const start=cursor; cursor+=Array.from(p).length; const end=cursor; cursor+=2; return [start,end]; });
    const texts = { 'original.txt': paragraphs.join('\n\n'), 'translation.txt': '', 'furigana.html': '' };
    const specs = {};
    for (const [name, text] of Object.entries(texts)) {
      fs.writeFileSync(path.join(local, name), text);
      specs[name] = { sha256: crypto.createHash('sha256').update(text).digest('hex'), field: name === 'original.txt' ? 'paragraphs' : name === 'translation.txt' ? 'translated_paragraphs' : 'furigana_paragraphs', paragraphs: name === 'original.txt' ? spans : [] };
    }
    const manifest = { schema_version: 1, revision: 1, article: { id, title, url: 'https://example.test/saved-audio-' + id, source_name: '一時検証', status: 'ready', voice_mode: 'browser', edition_dates: ['2099-01-02'], created_at: '2099-01-02T00:00:00+08:00', bookmarked: false }, text_files: specs, assets: [] };
    fs.writeFileSync(path.join(local, 'article.json'), JSON.stringify(manifest));
    device('shell', 'mkdir', '-p', folder + '/audio', folder + '/media'); created = true;
    for (const name of Object.keys(texts).concat('article.json')) device('push', path.join(local, name), folder + '/' + name);
    await evaluate(`window.__audioQaCalls=[];window.__audioQaOriginalApi=api;api=async function(...args){window.__audioQaCalls.push({path:args[0],method:args[1]?.method||'GET'});return window.__audioQaOriginalApi(...args)};void 0`);
    await evaluate(`window.__audioQaErrors=[];window.__audioQaPlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){const element=this;return window.__audioQaPlay.call(this).catch(error=>{window.__audioQaErrors.push({name:error.name,code:element.error?.code,readyState:element.readyState,networkState:element.networkState,src:element.src});throw error;});};void 0`);
    const open = () => evaluate(`api('/api/articles/${id}').then(openArticleInReader)`);
    await open();
    await tap('#reader-result .audio-player-toggle');
    const task = await evaluate(`(() => { const r=document.querySelector('#reader-result');const t=r.querySelector('.reread-task');return {visible:!t.hidden,label:t.textContent.trim(),belowMetadata:t.getBoundingClientRect().top>=r.querySelector('.article-meta').getBoundingClientRect().bottom,notice:document.querySelector('#notice').textContent};})()`);
    assert.equal(task.visible, true); assert.equal(task.belowMetadata, true); assert.equal(task.notice, '');
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'generating.png'), execFileSync(adb, ['-s', serial, 'exec-out', 'screencap', '-p']));
    await until(() => evaluate('Boolean(state.articleAudio?.mobileNative && state.articleAudio.mediaSource)'), 120000);
    const firstPlayback = await until(() => evaluate('(() => {const s=JSON.parse(FujimiMobile.mediaStatus());return s.position>0.2&&s.playing?{playing:true}:s.error?{error:s.error}:false})()'));
    assert.equal(firstPlayback.playing, true, JSON.stringify(firstPlayback));
    assert.equal(await evaluate('document.querySelector(".toast.is-visible")?.textContent || ""'), '', '文章音频不应弹全局成功提示');
    const saved = await evaluate(`api('/api/articles/${id}')`);
    assert.equal(saved.audio_status, 'ready'); assert.equal(saved.audio_voice_name, 'ja-JP-KeitaNeural');
    assert.equal(saved.audio_segments.length, paragraphs.length);
    assert(saved.audio_path.endsWith(encodeURIComponent('圭太_' + title + '.mp3')));
    const before = device('shell', 'sha256sum', folder + '/audio/圭太_' + title + '.mp3').split(/\s/)[0];
    const originalHash = device('shell', 'sha256sum', folder + '/original.txt').split(/\s/)[0];
    assert.equal(originalHash, specs['original.txt'].sha256);
    const duration = await evaluate('JSON.parse(FujimiMobile.mediaStatus()).duration');
    assert(duration > 120, 'Long audio must exercise chunked synthesis and seeking beyond the first chunk.');
    assert.equal(await evaluate('document.querySelector("#reader-result .reread-task").hidden'), true);
    assert.equal(await evaluate('document.querySelector("#notice").textContent'), '');
    await evaluate('stopArticlePlayback();void 0');
    const postsBefore = await evaluate('window.__audioQaCalls.filter(x=>x.path.endsWith("/edge-tts") && x.method==="POST").length');
    assert.equal(postsBefore, 1);
    // Fail any synthesis request while allowing article reads and the saved MP3 stream.
    await evaluate('api=async function(...args){if(args[0].endsWith("/edge-tts"))throw new Error("Network blocked by verification");return window.__audioQaOriginalApi(...args)};void 0');
    await open();
    await tap('#reader-result .audio-player-toggle');
    await until(() => evaluate('(() => {const s=JSON.parse(FujimiMobile.mediaStatus());return s.position>0.2&&s.playing})()'));
    await tap('#reader-result .parallel .paragraph:nth-child(2) .japanese');
    const seek = await until(() => evaluate('(() => {const s=JSON.parse(FujimiMobile.mediaStatus()),start=state.articleAudio.timeline[1]?.speechStart;return s.playing&&s.position>=start?{position:s.position,paragraphStart:start}:false})()'));
    const jumps = [];
    for (const paragraph of [0, 2, 0, 1, 2, 1]) {
      await tap(`#reader-result .paragraph[data-audio-index="${paragraph}"] .japanese`);
      const initial = await until(() => evaluate(`(() => {const s=JSON.parse(FujimiMobile.mediaStatus()),start=state.articleAudio.timeline[${paragraph}].speechStart;return s.playing&&Math.abs(s.position-start)<2?{time:s.position,start}:false})()`));
      await pause(1200);
      const continuing = await evaluate(`(() => {const s=JSON.parse(FujimiMobile.mediaStatus());return {time:s.position,paused:!s.playing,error:s.error||null,active:document.querySelector('#reader-result .is-audio-active')?.dataset.audioIndex}})()`);
      assert(continuing.time>initial.time+0.5, 'After a paragraph jump, decoding must continue: '+JSON.stringify({paragraph,initial,continuing}));
      assert.equal(continuing.paused,false); assert.equal(continuing.error,null); assert.equal(continuing.active,String(paragraph));
      jumps.push({paragraph,initial,continuing});
    }
    await tap('#reader-result .audio-player-toggle');
    await until(() => evaluate('!JSON.parse(FujimiMobile.mediaStatus()).playing'));
    await tap('#reader-result .audio-player-toggle');
    await until(() => evaluate('JSON.parse(FujimiMobile.mediaStatus()).playing'));
    await tap('#reader-result .audio-rate-toggle');
    await tap('#reader-result .audio-rate-menu button[data-rate="1.5"]');
    await until(() => evaluate('JSON.parse(FujimiMobile.mediaStatus()).rate===1.5'));
    assert.deepEqual(await evaluate('window.__audioQaErrors'), [], 'Real touches must not reject play or seek.');
    const after = device('shell', 'sha256sum', folder + '/audio/圭太_' + title + '.mp3').split(/\s/)[0];
    assert.equal(before, after);
    fs.writeFileSync(path.join(output, 'playing.png'), execFileSync(adb, ['-s', serial, 'exec-out', 'screencap', '-p']));
    // Missing audio must report one transient bottom Toast even when both load and play fail.
    await evaluate(`FujimiMobile.pauseMedia();state.articleAudio.mediaSource=${JSON.stringify('https://appassets.androidplatform.net' + saved.audio_path.replace(/[^/]+$/, 'qa-missing.mp3'))};void 0`);
    await until(() => evaluate('!state.articleAudio.mobileStatus.playing'));
    await tap('#reader-result .audio-player-toggle');
    const failure = await until(() => evaluate(`(() => {const t=document.querySelector('.toast.is-error.is-visible');if(!t)return false;const r=t.getBoundingClientRect(),p=state.articleAudio.player.getBoundingClientRect();return {count:document.querySelectorAll('.toast.is-error').length,center:(r.left+r.right)/2,viewport:innerWidth,bottom:r.bottom,playerTop:p.top};})()`));
    assert.equal(failure.count, 1); assert(Math.abs(failure.center-failure.viewport/2)<1); assert(failure.bottom<failure.playerTop);
    fs.writeFileSync(path.join(output, 'failure.png'), execFileSync(adb, ['-s', serial, 'exec-out', 'screencap', '-p']));
    const evidence = { device: serial, input: 'adb input tap; CDP evaluations do not grant userGesture', version: await evaluate('JSON.parse(FujimiMobile.mobileStatus()).app_version'), data: await evaluate('JSON.parse(FujimiMobile.mobileStatus()).data_path'), task, duration, firstClickSynthesisRequests: postsBefore, filename: '圭太_' + title + '.mp3', sha256: after, paragraphs: saved.audio_segments.length, firstClickStartsPlayback: true, savedPlayback: true, replayWithoutSynthesis: true, paragraphSeek: seek, jumps, pauseResume: true, playbackRate: 1.5, failure, originalUnchanged: true };
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } finally {
    try {
      await evaluate('stopArticlePlayback();if(window.__audioQaOriginalApi)api=window.__audioQaOriginalApi;if(window.__audioQaPlay)HTMLMediaElement.prototype.play=window.__audioQaPlay;void 0');
      if (voiceBefore) await evaluate(`api('/api/settings/browser-voice',{method:'PUT',body:JSON.stringify({name:${JSON.stringify(voiceBefore.browser_voice_name)},label:${JSON.stringify(voiceBefore.browser_voice_label)}})}).then(applyBrowserVoiceSettings)`);
      if (readerBefore !== undefined) await evaluate(`sessionStorage.${readerBefore === null ? 'removeItem(READER_ARTICLE_KEY)' : 'setItem(READER_ARTICLE_KEY,' + JSON.stringify(readerBefore) + ')'};void 0`);
      if (rateBefore !== undefined) await evaluate(`localStorage.${rateBefore === null ? 'removeItem("fujimi-playback-rate")' : 'setItem("fujimi-playback-rate",' + JSON.stringify(rateBefore) + ')'};void 0`);
      await evaluate('showView("daily")');
    } catch {}
    socket.close();
    if (created) device('shell', 'rm', '-r', folder);
    fs.rmSync(local, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
