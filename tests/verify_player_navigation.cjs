// Formal page regression: returning to a reader restores its own player, and
// an open navigation drawer covers the player. All content and APIs are fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const { fixture } = require('./verify_android_frontend.cjs');
const output = path.resolve(__dirname, '../build/qa/player-navigation');
const paragraphs = ['空を見上げると、青く澄んでいた。', '朝の風を感じながら歩く。', '今日も新しい一日が始まる。'];
const segments = paragraphs.map(() => ({ duration: 4, speech_start_offset: 0, timing_source: 'edge_sentence' }));
const wav = Buffer.alloc(44 + 8000 * 2 * 12);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);

async function verify(browser, width, engine) {
  const { context, page, errors, values } = await fixture(browser, width, width < 900 && engine !== 'browser');
  if (engine === 'browser') values['voice-mode'].browser_voice_name = 'QA Japanese';
  const failures = [];
  const check = (condition, message) => { if (!condition) failures.push(message); };
  try {
    page.setDefaultTimeout(8000);
    if (width < 900 && engine === 'browser') await page.evaluate(() => {
      document.documentElement.dataset.mobileApp = 'true';
      syncMobileNavigationLayout();
    });
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: width === 390 ? 'dark' : 'light' });
    await context.route('**/api/audio/navigation.wav', route => route.fulfill({ contentType: 'audio/wav', body: wav }));
    await page.evaluate(engine => {
      if (engine === 'media3') {
        window.__media = { playing: false, position: 0, duration: 12, ended: false };
        window.__mediaCalls = [];
        Object.assign(window.FujimiMobile, {
          playMedia(url, position) { __mediaCalls.push({ url, position }); Object.assign(__media, { playing: true, position }); return true; },
          mediaStatus: () => JSON.stringify(__media), pauseMedia() { __media.playing = false; },
          stopMedia() { __media.playing = false; }, seekMedia(position) { __media.position = position; }, setMediaRate() {}
        });
      }
      if (engine === 'browser') {
        window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
        Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
          speak(utterance) { utterance.onstart?.(); }, cancel() {}, pause() {}, resume() {},
          getVoices: () => [{ name: 'QA Japanese', lang: 'ja-JP' }], addEventListener() {}
        } });
        resolveJapaneseBrowserVoice = async () => ({ name: 'QA Japanese', lang: 'ja-JP' });
        state.browserVoiceName = 'QA Japanese';
      }
    }, engine);
    const audioPath = engine === 'media3' ? '/api/books/99001/audio/qa.wav' : '/api/audio/navigation.wav';
    const chapter = { id: 1, title: '第一章', voice_mode: engine === 'browser' ? 'browser' : 'voice',
      audio: engine === 'browser' ? null : { url: audioPath, segments }, blocks: paragraphs.map((text, i) => ({
        id: `p${i}`, block_index: i, kind: 'paragraph', text_ja: text, html: `<p>${text}</p>`, text_zh: '合成测试译文。'
      })) };
    const payload = { book: { id: 99001, title: '导航测试书籍', parser_version: 2,
      reading_revision: 1, chapters: [chapter], bookmarks: [], progress: {} }, chapter };
    await context.route('**/api/books/99001/chapters/1', route => route.fulfill({ json: payload }));
    await context.route('**/api/books/99001/progress', route => route.fulfill({
      json: { ...payload.book, progress: route.request().postDataJSON() }
    }));
    await page.evaluate(async () => { await showView('library'); await navigateBookChapter(99001, 1); });
    const bookPlayer = page.locator('#book-reader .article-audio-player');
    assert(await bookPlayer.isVisible(), 'Fixture must start with a usable book player');

    async function play(selector) {
      if (await page.evaluate(() => state.browserSpeech?.playing || state.articleAudio &&
        (state.articleAudio.mobileNative ? window.__media.playing : !state.articleAudio.audio.paused))) return;
      await page.locator(`${selector} .audio-player-toggle`).click();
      try {
        await page.waitForFunction(() => state.browserSpeech?.playing || state.articleAudio &&
          (state.articleAudio.mobileNative ? window.__media.playing : !state.articleAudio.audio.paused));
      } catch (error) {
        const actual = await page.evaluate(() => ({ voice: state.browserVoiceName, browser: state.browserSpeech && {
          voice: state.browserSpeech.browserVoiceName, playing: state.browserSpeech.playing, started: state.browserSpeech.started,
          cancelled: state.browserSpeech.cancelled, text: state.browserSpeech.text
        }, notice: document.querySelector('#notice').textContent, errors: [...document.querySelectorAll('.toast')].map(el => el.textContent) }));
        throw new Error(`${error.message}: ${JSON.stringify(actual)}`);
      }
    }
    await play('#book-reader');
    await page.evaluate(() => showView('settings'));
    check(await page.evaluate(() => !state.browserSpeech?.playing &&
      (!state.articleAudio || (state.articleAudio.mobileNative ? !window.__media.playing : state.articleAudio.audio.paused))),
    'Leaving a reading view must pause its audio');
    await page.evaluate(() => showView('library'));
    check(await bookPlayer.isVisible(), 'Returning from settings must restore the book player');
    if (await bookPlayer.isVisible()) await play('#book-reader');
    await page.screenshot({ path: path.join(output, `${width}-${engine}-book-return.png`) });

    // Reopening the chapter gives the following independent scenario a fresh player.
    await page.evaluate(() => navigateBookChapter(99001, 1, { historyMode: 'replace' }));
    await page.evaluate(() => {
      const root = document.querySelector('#book-reader');
      setBookLanguageMode(root, 'click');
      root.querySelector('.book-block-zh').click();
      window.__bookBody = root.querySelector('.book-chapter-body');
    });
    const article = { id: 99002, title: '导航测试新闻', source_name: '合成検証', status: 'ready', paragraphs,
      translated_paragraphs: ['一。', '二。', '三。'], full_translation: '合成测试译文。',
      audio_status: engine === 'browser' ? 'browser' : 'ready', audio_segments: segments,
      audio_path: engine === 'browser' ? '' : engine === 'media3' ? '/api/articles/99002/assets/audio/qa.wav' : audioPath };
    await page.evaluate(article => openArticleInReader(article), article);
    const newsPlayer = page.locator('#reader-result .article-audio-player');
    assert(await newsPlayer.isVisible(), 'Fixture must start with a usable news player');
    await page.evaluate(() => {
      const root = document.querySelector('#reader-result .article-detail');
      setArticleTranslationView(root, 'hide');
      window.__newsBody = root.querySelector('.parallel');
    });
    await play('#reader-result');
    await page.evaluate(() => showView('library'));
    check(await bookPlayer.isVisible(), 'Returning from news must restore the book player');
    check(await page.evaluate(() => (state.articleAudio || state.browserSpeech)?.root.id === 'book-reader'),
      'Book controls must belong to the book rather than the hidden news article');
    check(await page.evaluate(() => document.querySelector('#book-reader .book-chapter-body') === window.__bookBody &&
      document.querySelector('#book-reader .book-block-zh').dataset.translationRevealed === 'true'),
      'Restoring book audio must preserve the reading content and revealed translations');
    await page.evaluate(() => showView('reader'));
    check(await newsPlayer.isVisible(), 'Returning from a book must restore the news player');
    const newsOwnsPlayer = await page.evaluate(() => Boolean((state.articleAudio || state.browserSpeech)?.root.closest('#reader-result')));
    check(newsOwnsPlayer,
      'News controls must belong to the news article rather than the hidden book');
    check(await page.evaluate(() => document.querySelector('#reader-result .parallel') === window.__newsBody &&
      document.querySelector('#reader-result .article-detail').dataset.translationMode === 'hide'),
      'Restoring news audio must preserve the reading content and translation mode');
    if (newsOwnsPlayer && await newsPlayer.isVisible()) await play('#reader-result');
    if (engine === 'media3') {
      await page.evaluate(() => { window.__mediaCalls = []; });
      await page.locator('#reader-result .japanese').nth(1).click();
      const jumps = await page.evaluate(() => window.__mediaCalls);
      check(jumps.length === 1 && jumps[0].position === 4 && jumps[0].url.includes('/articles/99002/'),
        'A paragraph click after restoration must seek the current article exactly once');
    }

    if (width < 900) {
      await page.locator('#mobile-nav-toggle').click();
      await page.waitForFunction(() => document.querySelector('.sidebar').contains(document.activeElement));
      const overlap = await page.evaluate(() => {
        const player = document.querySelector('#reader-result .article-audio-player').getBoundingClientRect();
        const sidebar = document.querySelector('.sidebar');
        return {
          drawer: sidebar.contains(document.elementFromPoint(40, player.bottom - 20)),
          scrim: document.elementFromPoint(innerWidth - 5, player.top + 10)?.id === 'mobile-nav-scrim',
          focus: sidebar.contains(document.activeElement)
        };
      });
      check(overlap.drawer, 'An open navigation drawer must cover the player');
      check(overlap.scrim, 'The navigation scrim must cover the player outside the drawer');
      check(overlap.focus, 'Drawer focus must stay inside the menu');
      await page.screenshot({ path: path.join(output, `${width}-${engine}-drawer.png`) });
      await page.locator('#mobile-nav-close').click();
      check(await newsPlayer.isVisible(), 'Closing the drawer must leave the news player available');
      check(await page.locator('#mobile-nav-toggle').evaluate(el => el === document.activeElement), 'Closing the drawer must restore focus');
    }
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'The page must not overflow horizontally');
    check(errors.length === 0, `No page errors: ${errors.join(', ')}`);
    return { width, engine, failures };
  } finally { await context.close(); }
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true,
    args: ['--autoplay-policy=no-user-gesture-required', '--disable-gpu', '--renderer-process-limit=2'] });
  try {
    const results = [];
    for (const width of [375, 390, 1440]) {
      for (const engine of width < 900 ? ['html', 'media3', 'browser'] : ['html', 'browser']) {
        if (process.argv.includes('--browser-only') && engine !== 'browser') continue;
        const result = await verify(browser, width, engine);
        results.push(result); console.log(JSON.stringify(result));
      }
    }
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    assert.equal(results.flatMap(result => result.failures).length, 0, 'Player navigation regressions');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
