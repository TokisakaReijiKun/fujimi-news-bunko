// Formal-page regression with synthetic WAV/text; never touches user content.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { fixture } = require('./verify_android_frontend.cjs');

const wav = Buffer.alloc(44 + 8000 * 2 * 6);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
const url = `data:audio/wav;base64,${wav.toString('base64')}`;
const paragraphs = ['前の段落です。', 'クリックした段落です。', '最後の段落です。'];
const segments = [2.0000000000000004, 2, 1.9999999999999996].map(duration => ({ duration, speech_start_offset: 0 }));

async function verify(browser, width, kind) {
  const { context, page, errors } = await fixture(browser, width, false);
  try {
    if (process.argv.includes('--desktop-package')) {
      const assets = path.resolve(__dirname, '../dist/FujimiShinbunBunko/_internal/static');
      await context.route('**/static/**', route => {
        const file = path.join(assets, new URL(route.request().url()).pathname.slice('/static/'.length));
        return fs.existsSync(file) ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
      });
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#voice-list').children.length > 0);
    }
    await page.evaluate(async ({ kind, url, paragraphs, segments }) => {
      if (kind === 'news') {
        await openArticleInReader({ id: 90001, title: '段落境界のテスト', source_name: 'テスト',
          url: 'https://example.test/boundary', status: 'ready', paragraphs,
          audio_status: 'ready', audio_path: '/api/audio/boundary.wav', audio_segments: segments });
        state.articleAudio.audio.src = url;
      } else {
        await showView('library');
        const chapter = { id: 1, title: '第一章', voice_mode: 'model',
          audio: { status: 'ready', url, segments },
          blocks: paragraphs.map((text_ja, i) => ({ id: i + 1, block_index: i, kind: 'paragraph', text_ja })) };
        await renderBookReader({ book: { id: 90002, title: '段落境界のテスト', author: 'テスト',
          parser_version: 2, chapters: [chapter], bookmarks: [], progress: {} }, chapter }, { startAtBeginning: true });
      }
    }, { kind, url, paragraphs, segments });
    await page.waitForFunction(() => state.articleAudio?.audio.readyState >= 3 && state.articleAudio.timeline.length === 3);
    // Pause immediately when the actual browser seek completes, so subsequent
    // playback cannot hide an incorrect highlight at the rounded boundary.
    await page.evaluate(() => {
      const c = state.articleAudio;
      window.__boundaryPlayCalls = 0;
      window.__boundaryHighlights = [];
      const highlight = setActiveAudioParagraph;
      setActiveAudioParagraph = (root, index) => {
        if (root === c.root) window.__boundaryHighlights.push(index);
        highlight(root, index);
      };
      const play = c.audio.play.bind(c.audio);
      c.audio.play = () => { window.__boundaryPlayCalls++; return play(); };
      c.audio.addEventListener('seeked', () => c.audio.pause(), { once: true });
    });
    const root = kind === 'news' ? '#reader-result' : '#book-reader';
    await page.locator(`${root} .paragraph[data-audio-index="1"] ${kind === 'news' ? '.japanese' : '.book-block-ja'}`).click();
    await page.waitForFunction(() => !state.articleAudio.audio.seeking && state.articleAudio.audio.currentTime > 0 && state.articleAudio.audio.paused);
    const result = await page.evaluate(() => {
      const c = state.articleAudio;
      const active = () => [...c.root.querySelectorAll('.is-audio-active')].map(el => Number(el.dataset.audioIndex));
      const atBoundary = active();
      const highlights = [...window.__boundaryHighlights];
      const reportedTime = c.audio.currentTime;
      const targetStart = c.timeline[1].start;
      // The tolerance must not move an ordinary position in the prior paragraph.
      renderNativeArticleAudio({ ...c, mobileNative: true,
        mobileStatus: { duration: c.audio.duration, position: targetStart - .001, playing: false } });
      const beforeBoundary = active();
      renderNativeArticleAudio(c);
      return { atBoundary, beforeBoundary, reportedTime, targetStart, playCalls: window.__boundaryPlayCalls,
        highlights,
        overflow: document.documentElement.scrollWidth > innerWidth };
    });
    assert(result.reportedTime < result.targetStart, 'Exercise the browser rounding that originally highlighted the previous paragraph.');
    assert.deepEqual(result.atBoundary, [1], 'Only the clicked paragraph should be highlighted at the boundary.');
    assert(result.highlights.length > 0 && result.highlights.every(index => index === 1),
      `No intermediate event should highlight the previous paragraph: ${JSON.stringify(result.highlights)}`);
    assert.deepEqual(result.beforeBoundary, [0], 'Positions 1 ms before the boundary still belong to the previous paragraph.');
    assert.equal(result.playCalls, 1, 'Clicking the paragraph must invoke actual audio playback.');
    assert.equal(result.overflow, false);
    const repeated = await page.evaluate(async () => {
      const c = state.articleAudio;
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
      const traces = [];
      for (let attempt = 0; attempt < 20; attempt++) {
        c.audio.pause();
        const reset = new Promise(resolve => c.audio.addEventListener('seeked', resolve, { once: true }));
        c.audio.currentTime = 1;
        await reset;
        if (attempt % 2) await c.audio.play();
        window.__boundaryHighlights = [];
        c.root.querySelector('.paragraph[data-audio-index="1"] .japanese, .paragraph[data-audio-index="1"] .book-block-ja').click();
        await wait(80);
        c.audio.pause();
        traces.push([...window.__boundaryHighlights]);
      }
      return traces;
    });
    assert(repeated.every(trace => trace.length > 0 && trace.every(index => index === 1)),
      `Repeated jumps must not flash the previous paragraph: ${JSON.stringify(repeated)}`);
    assert.deepEqual(errors, []);
    return { width, kind, repeatedJumps: repeated.length, ...result };
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  try {
    const results = [];
    for (const width of [1440, 375, 390]) {
      for (const kind of ['news', 'book']) results.push(await verify(browser, width, kind));
    }
    console.log(JSON.stringify({ passed: results.length, results }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
