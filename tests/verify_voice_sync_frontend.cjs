// Formal Android settings/readers with isolated native/network fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
    let mode = { mode: 'browser', browser_voice_name: 'kokoro:jf_alpha', browser_voice_label: 'システム音声' };
    const voices = [{ id: 12345, name: '同期テスト声線', read_only: true, saved_audio_only: true }];
    const catalog = [
      { id: 'ja-JP-KeitaNeural', name: '圭太', provider: 'edge-tts', available: true, default: true },
      { id: 'kokoro:jf_alpha', name: 'アルファ', provider: 'kokoro', available: true, saved_audio_only: true },
    ];
    const writes = [];
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (url.pathname.startsWith('/api/')) {
        let value = [];
        if (req.method() !== 'GET') writes.push(url.pathname);
        if (url.pathname.endsWith('/voice-mode')) value = mode;
        else if (url.pathname.endsWith('/voices')) value = voices.map(v => ({ ...v, active: mode.mode === 'voice' && mode.voice_id === v.id }));
        else if (url.pathname === '/api/browser-voices') value = catalog;
        else if (url.pathname.endsWith('/active-voice')) {
          const body = req.postDataJSON();
          mode = { ...mode, mode: body.browser ? 'browser' : 'voice', voice_id: body.voice_id };
          value = mode;
        } else if (url.pathname.endsWith('/browser-voice')) {
          mode = { ...mode, mode: 'browser', browser_voice_name: req.postDataJSON().name };
          value = mode;
        } else if (url.pathname.endsWith('/health')) value = { status: 'ok', tts_details: { enabled: false } };
        else if (url.pathname.endsWith('/daily-content')) value = { target_count: 10, source_count: 0, required_count: 0 };
        else if (url.pathname.endsWith('/daily-schedule')) value = { mode: 'manual', time: '00:00' };
        else if (url.pathname.endsWith('/library')) value = { sort: 'recent' };
        else if (url.pathname.endsWith('/daily')) value = { articles: [] };
        else if (url.pathname.endsWith('/tasks/daily')) value = { status: 'idle' };
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
      }
      const file = path.join(root, url.pathname);
      return file.startsWith(path.join(root, 'static') + path.sep) && fs.existsSync(file)
        ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
    });
    await context.addInitScript(() => {
      window.__mediaCalls = [];
      window.__mediaState = { playing: false, position: 0, duration: 90, error: '' };
      window.FujimiMobile = {
        request(raw, id) { const r = JSON.parse(raw); fetch(r.path, { method: r.method, body: r.body }).then(async res => window.__fujimiMobileResolve(id, res.status, await res.text())); },
        speak() { throw Error('Unexpected Edge fallback'); },
        playMedia(url, position, rate) { window.__mediaCalls.push({ url, position, rate }); window.__mediaState = { playing: true, position, duration: 90, rate, error: '' }; return true; },
        mediaStatus: () => JSON.stringify(window.__mediaState),
        pauseMedia() { window.__mediaState.playing = false; },
        stopMedia() { window.__mediaState = { playing: false, position: 0, duration: 0, error: '' }; },
        seekMedia(position) { window.__mediaState.position = position; },
        setMediaRate(rate) { window.__mediaState.rate = rate; },
        mobileStatus: () => JSON.stringify({ paired: true, sync_available: true, sync_state: 'completed', reference_voices_available: true, app_version: 'test' }),
      };
    });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8439/static/index.html#settings');
    await page.waitForFunction(() => document.querySelectorAll('.voice-row').length === 2);
    assert.equal(mode.browser_voice_name, 'kokoro:jf_alpha', 'Loading settings must retain a synchronized PC voice');
    assert(!writes.includes('/api/settings/browser-voice'), 'Initialization must not switch back to Edge');
    const custom = page.locator('.voice-row').filter({ hasText: '同期テスト声線' });
    assert.equal(await custom.locator('.edit').isVisible(), false);
    assert.equal(await custom.locator('.delete').isVisible(), false);
    await custom.locator('summary').click();
    await custom.locator('.select').click();
    await page.waitForFunction(() => document.querySelector('#active-voice-badge').textContent === '同期テスト声線');
    assert.equal(mode.mode, 'voice');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#active-voice-badge').textContent === '同期テスト声線');
    assert.equal(mode.mode, 'voice');
    voices.push({ id: 12346, name: '追加声線', read_only: true, saved_audio_only: true });
    await page.evaluate(() => window.__fujimiRefreshNativeSettings());
    await page.waitForFunction(() => document.querySelectorAll('.voice-row').length === 3);
    const detail = '所选声线尚无已同步音频，请先在 PC 生成后同步。';
    await page.evaluate(detail => {
      showView('reader');
      openArticle({ id: 1, status: 'ready', title: '音声テスト', paragraphs: ['音声を確認します。'], audio_status: 'unavailable', audio_voice_mode: 'voice', audio_voice_id: 12345, audio_path: '', audio_unavailable_detail: detail }, document.querySelector('#reader-result'));
    }, detail);
    await page.getByText(detail, { exact: true }).waitFor({ state: 'visible' });
    assert(!writes.some(p => p.endsWith('/edge-tts')));
    const bookAudioUrl = '/api/books/9/audio/' + encodeURIComponent('同期声線_第1章 #50%.wav');
    await page.evaluate(async url => {
      showView('library');
      await renderBookReader({
        book: { id: 9, title: '同期した本', chapters: [{ id: 1, title: '第1章' }], progress: {}, bookmarks: [] },
        chapter: { id: 1, title: '第1章', voice_mode: 'voice', voice_id: 12345,
          blocks: [{ id: 'b1', text_ja: '同期した本の音声です。', html: '<p>同期した本の音声です。</p>' }],
          audio: { status: 'ready', voice_id: 12345, url, segments: [] } },
      });
    }, bookAudioUrl);
    assert.equal(await page.evaluate(() => state.articleAudio?.mobileNative), true, 'Saved book recordings must use the same native Media3 player as news');
    await page.locator('#book-reader .audio-player-toggle').click();
    assert.equal(await page.evaluate(() => new URL(__mediaCalls.at(-1).url).pathname), bookAudioUrl);
    assert(!writes.some(p => /\/(reread|edge-tts|browser-speech)$/.test(p)), 'Playing a synced book must never generate audio');
    await page.evaluate(() => stopArticlePlayback());
    assert.deepEqual(errors, []);
    console.log('PC voice selection, persistence, refresh, read-only actions and missing-audio feedback passed');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
