// Formal page assets with temporary content; verifies PC/mobile task placement and cold audio seeks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { fixture } = require('./verify_android_frontend.cjs');
const output = path.resolve(__dirname, '../build/qa/android-audio-ui');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const article = {
  id: 90001, title: '8月新規求人3.4%減　最低賃金引き上げ前、企業に採用控えの動き',
  url: 'https://example.test/audio-ui', source_name: '日本経済新聞', status: 'ready',
  published: '2026-10-02T11:30:00+09:00', voice_mode: 'browser', audio_status: 'browser',
  paragraphs: ['今日は新聞を読みます。', '二つ目の段落です。', '最後の段落です。'],
  translated_paragraphs: ['今天阅读报纸。', '这是第二段。', '这是最后一段。'],
};
// Valid small WAV, served slowly to exercise a paragraph click before metadata arrives.
const audio = Buffer.alloc(44 + 48000 * 2 * 6);
audio.write('RIFF'); audio.writeUInt32LE(audio.length - 8, 4); audio.write('WAVEfmt ', 8);
audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
audio.writeUInt32LE(48000, 24); audio.writeUInt32LE(96000, 28); audio.writeUInt16LE(2, 32);
audio.writeUInt16LE(16, 34); audio.write('data', 36); audio.writeUInt32LE(audio.length - 44, 40);
const saved = { ...article, audio_path: '/api/articles/90001/assets/audio/圭太.wav', audio_status: 'ready',
  audio_segments: article.paragraphs.map(() => ({ duration: 2, speech_start_offset: 0 })) };

async function verify(browser, width, native) {
  const { page, context, errors } = await fixture(browser, width, native);
  let requests = 0;
  await context.route('**/api/articles/90001/edge-tts', async route => {
    await pause(1400);
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ article: saved, cached: false }) });
  });
  await context.route('**/api/articles/90001/assets/audio/**', async route => {
    requests++;
    await pause(1400);
    await route.fulfill({ contentType: 'audio/wav', body: audio });
  });
  await page.evaluate(article => openArticleInReader(article), article);
  if (native) await page.locator('#reader-result .audio-player-toggle').click();
  else await page.evaluate(() => setRereadTask(document.querySelector('#reader-result article'), 'running', '音声生成を準備しています…', '', '', 0, 1));
  await page.locator('#reader-result .reread-task:not([hidden])').waitFor();
  const task = await page.evaluate(() => {
    const root = document.querySelector('#reader-result'), t = root.querySelector('.reread-task');
    return { taskTop: t.getBoundingClientRect().top, metadataBottom: root.querySelector('.article-meta').getBoundingClientRect().bottom,
      barHeight: t.querySelector('progress').getBoundingClientRect().height,
      width: document.documentElement.scrollWidth, viewport: innerWidth, notice: document.querySelector('#notice').textContent };
  });
  assert(task.taskTop >= task.metadataBottom); assert.equal(task.barHeight, 7);
  assert(task.width <= task.viewport); assert.equal(task.notice, '');
  await page.screenshot({ path: path.join(output, `task-${width}.png`), fullPage: true });
  if (native) {
    await page.waitForFunction(() => state.articleAudio?.audio?.currentTime > 0 && !state.articleAudio.audio.paused);
    assert.equal(await page.locator('#reader-result .reread-task').isVisible(), false);
    await page.evaluate(() => stopArticlePlayback());
    await page.evaluate(article => openArticleInReader(article), saved);
    assert.equal(await page.evaluate(() => state.articleAudio.audio.readyState), 0);
    await page.locator('#reader-result .japanese').nth(2).click();
    await page.waitForFunction(() => state.articleAudio?.audio?.currentTime >= 4 && !state.articleAudio.audio.paused);
    assert.equal(requests, 2, 'Clicking before metadata must not restart the audio request.');
    // Edge offsets are positions in the MP3 itself. Its trailing silence must
    // not stretch the beginning of the last paragraph from 4.0 to 4.8 seconds.
    await page.evaluate(article => openArticleInReader(article), {
      ...saved, audio_segments: [1, 3, 1].map(duration => ({ duration, speech_start_offset: 0, timing_source: 'edge_sentence' }))
    });
    await page.waitForFunction(() => state.articleAudio.audio.readyState >= 3 && state.articleAudio.timeline.length === 3);
    await page.evaluate(() => {
      state.articleAudio.seekParagraph(2);
    });
    await page.waitForFunction(() => !state.articleAudio.audio.seeking && state.articleAudio.audio.currentTime >= 4);
    const preciseSeek = await page.evaluate(() => {
      state.articleAudio.audio.pause();
      return { position: state.articleAudio.audio.currentTime, duration: state.articleAudio.audio.duration, timeline: state.articleAudio.timeline };
    });
    assert.equal(preciseSeek.timeline[2].speechStart, 4, 'Use the real Edge paragraph timestamp rather than scaling it by trailing silence.');
    assert(preciseSeek.position >= 4 && preciseSeek.position < 4.3, `Edge paragraph start must stay at 4 seconds, got ${JSON.stringify(preciseSeek)}`);
    // Both the media error event and rejected play promise must produce one transient Toast.
    await page.evaluate(() => {
      const c=state.articleAudio;
      c.audio.dispatchEvent(new Event('error'));
      reportArticleAudioError(c, new DOMException('fixture', 'NotSupportedError'));
    });
    await page.locator('.toast.is-visible').waitFor();
    await page.waitForFunction(() => Number(getComputedStyle(document.querySelector('.toast.is-visible')).opacity) > .99);
    const toast = await page.evaluate(() => {
      const t=document.querySelector('.toast.is-visible').getBoundingClientRect(), p=state.articleAudio.player.getBoundingClientRect();
      return { count: document.querySelectorAll('.toast.is-error').length, center: (t.left+t.right)/2, viewport: innerWidth, bottom: t.bottom, playerTop: p.top };
    });
    assert.equal(toast.count, 1); assert(Math.abs(toast.center-toast.viewport/2)<1); assert(toast.bottom<toast.playerTop);
    await page.screenshot({ path: path.join(output, `toast-${width}.png`) });
    await page.waitForFunction(() => !document.querySelector('.toast.is-error'));
  } else {
    await page.evaluate(article => openArticleInReader(article), {
      ...saved, audio_segments: [1, 3, 1].map(duration => ({ duration, speech_start_offset: 0, timing_source: 'edge_sentence' }))
    });
    await page.waitForFunction(() => state.articleAudio.audio.readyState >= 3 && state.articleAudio.timeline.length === 3);
    await page.locator('#reader-result .japanese').nth(2).click();
    await page.waitForFunction(() => !state.articleAudio.audio.seeking && !state.articleAudio.audio.paused && state.articleAudio.audio.currentTime >= 4);
    assert.equal(await page.evaluate(() => state.articleAudio.timeline[2].speechStart), 4);
  }
  assert.deepEqual(errors, []);
  await context.close();
  return { width, native, task, coldSeek: native };
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  try {
    const results = [];
    for (const [width, native] of [[375, true], [390, true], [1440, false]]) results.push(await verify(browser, width, native));
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify({ passed: results.length, output }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
