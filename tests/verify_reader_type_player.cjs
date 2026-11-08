// Reader typography contract on formal assets; all content/API data is synthetic.
// No user library, service, device, or paid speech endpoint is accessed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const { fixture } = require('./verify_android_frontend.cjs');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/qa/reader-type-player');
const ruby = '<ruby>木漏れ日<rt>こもれび</rt></ruby>の中を、ゆっくり歩きます。';
const original = '木漏れ日の中を、ゆっくり歩きます。';
const translation = '在树叶间洒落的阳光中，慢慢散步。';
const article = {
  id: 98001, title: '窓辺で読む、一日の便り', source_name: '合成検証', source_key: 'nhk',
  status: 'ready', url: 'https://example.test/reader-typography', audio_status: 'disabled',
  paragraphs: ['見出しを保つ', original, original], paragraph_kinds: ['heading-2', 'paragraph', 'paragraph'],
  furigana_paragraphs: ['見出しを保つ', ruby, ruby],
  translated_paragraphs: ['保留标题层级', translation, translation], full_translation: translation + '\n\n' + translation
};
function bookPayload(parserVersion) {
  const chapter = { id: 1, title: '第一章 木漏れ日', voice_mode: 'none', blocks: [
    { id: 'heading', block_index: 0, kind: 'heading', text_ja: '小さな見出し', html: '<h2>小さな見出し</h2>' },
    { id: 'body1', block_index: 1, kind: 'paragraph', text_ja: original, html: `<p>${ruby}</p>`, text_zh: translation, bilingual_pair: true },
    { id: 'body2', block_index: 2, kind: 'paragraph', text_ja: original, html: `<p>${ruby}</p>`, text_zh: translation, bilingual_pair: true }
  ] };
  return { book: { id: 98002 + parserVersion, title: '窓辺の本', author: '合成検証', parser_version: parserVersion,
    reading_revision: 1, chapters: [chapter], bookmarks: [], progress: {} }, chapter };
}

async function measure(page, kind, mode) {
  return page.evaluate(({ kind, mode }) => {
    const isNews = kind === 'news';
    const region = document.querySelector(isNews ? '#reader-result .article-detail' : '#book-reader');
    if (isNews) setArticleTranslationView(region, { parallel: 'show', click: 'click', ja: 'hide', zh: 'full' }[mode]);
    else setBookLanguageMode(region, mode);
    const body = region.querySelector(isNews ? '.paragraph[data-audio-index="1"] .japanese' : '.book-block[data-block-index="1"] .book-block-ja');
    const translated = region.querySelector(isNews ? '.paragraph[data-audio-index="1"] .chinese' : '.book-block[data-block-index="1"] .book-block-zh');
    if (mode === 'click') translated.click();
    const metrics = element => {
      if (!element) return null;
      const css = getComputedStyle(element), rect = element.getBoundingClientRect();
      return { fontSize: parseFloat(css.fontSize), lineHeight: parseFloat(css.lineHeight), display: css.display,
        visible: rect.width > 0 && rect.height > 0 && css.visibility !== 'hidden' && !element.closest('[hidden]'),
        color: css.color, fontWeight: css.fontWeight };
    };
    return { kind, mode, rootSize: parseFloat(getComputedStyle(document.documentElement).fontSize),
      ja: metrics(body), zh: metrics(isNews && mode === 'zh' ? region.querySelector('.full-translation') : translated),
      ruby: metrics(body.querySelector('rt')), translationMain: metrics(translated.querySelector('.translation-main')),
      placeholder: metrics(translated.querySelector('.translation-placeholder')),
      heading: metrics(region.querySelector(isNews ? '.paragraph-heading .japanese' : '.book-block-heading h2')),
      title: metrics(region.querySelector(isNews ? ':scope > .title' : '.book-chapter > h1')),
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      revealed: translated.dataset.translationRevealed === 'true' };
  }, { kind, mode });
}

function inspect(sample, scale, failures) {
  const problems = [];
  const equal = (actual, expected, label) => { if (!Number.isFinite(actual) || Math.abs(actual - expected) > .05) problems.push(`${label}: ${actual} instead of ${expected}`); };
  equal(sample.ja.fontSize, 16 * scale, 'original font');
  equal(sample.ja.lineHeight, 32 * scale, 'original line-height');
  equal(sample.zh.fontSize, 16 * scale, 'translation font');
  equal(sample.zh.lineHeight, 28 * scale, 'translation line-height');
  equal(sample.ruby.fontSize, 16 * scale * .58, 'ruby font');
  if (sample.translationMain && sample.mode !== 'zh') {
    equal(sample.translationMain.fontSize, 16 * scale, 'translation text font');
    equal(sample.translationMain.lineHeight, 28 * scale, 'translation text line-height');
  }
  if (sample.mode === 'click') {
    equal(sample.placeholder.fontSize, 16 * scale, 'click placeholder font');
    equal(sample.placeholder.lineHeight, 28 * scale, 'click placeholder line-height');
    if (!sample.revealed) problems.push('click translation was not revealed');
  }
  if (sample.mode !== 'zh' && (!sample.heading || sample.heading.fontSize <= sample.ja.fontSize)) problems.push('section heading lost its larger type hierarchy');
  if (!sample.title || sample.title.fontSize <= sample.ja.fontSize) problems.push('article/book title lost its larger type hierarchy');
  if ((sample.mode !== 'zh') !== sample.ja.visible) problems.push('original visibility differs from selected language mode');
  if ((sample.mode !== 'ja') !== sample.zh.visible) problems.push('translation visibility differs from selected language mode');
  if (sample.scrollWidth > sample.width + 1) problems.push(`horizontal overflow: ${sample.scrollWidth}/${sample.width}`);
  if (problems.length) failures.push({ kind: sample.kind, mode: sample.mode, scale, problems });
}

async function verifyFonts(browser, width, colorScheme) {
  const { context, page, errors } = await fixture(browser, width, width < 900);
  const result = { width, colorScheme, samples: [], failures: [] };
  try {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
    for (const scale of [1, 1.25]) {
      await page.evaluate(scale => document.documentElement.style.fontSize = `${scale * 100}%`, scale);
      await page.evaluate(article => openArticleInReader(article), article);
      for (const mode of ['parallel', 'click', 'ja', 'zh']) {
        const sample = await measure(page, 'news', mode);
        result.samples.push({ scale, ...sample }); inspect(sample, scale, result.failures);
      }
      for (const version of [2, 1]) {
        const payload = bookPayload(version);
        await page.evaluate(async payload => { await showView('library'); await renderBookReader(payload, { startAtBeginning: true }); }, payload);
        for (const mode of ['parallel', 'click', 'ja', 'zh']) {
          const sample = await measure(page, version === 2 ? 'epub' : 'legacy', mode);
          result.samples.push({ scale, ...sample }); inspect(sample, scale, result.failures);
        }
      }
    }
    if (errors.length) result.failures.push({ kind: 'runtime', errors });
  } catch (error) { result.failures.push({ kind: 'harness', error: error.message, stack: error.stack }); }
  finally { await context.close(); }
  console.log(JSON.stringify({ width, colorScheme, samples: result.samples.length, failures: result.failures.length, firstFailure: result.failures[0] }));
  return result;
}

const wav = Buffer.alloc(44 + 8000 * 2 * 90);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28); wav.writeUInt16LE(2, 32);
wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);

async function verifyPlayer(browser, width, kind, engine) {
  const { context, page, errors } = await fixture(browser, width, engine === 'media3');
  const result = { width, kind, engine, failures: [] };
  const region = kind === 'news' ? '#reader-result' : '#book-reader';
  try {
    page.setDefaultTimeout(8000);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    if (width <= 900) await page.evaluate(() => document.documentElement.style.setProperty('--player-native-safe-area-bottom', '24px'));
    result.safeAreaBottom = width <= 900 ? 24 : 0;
    await context.route('**/api/audio/reader-type-player.wav', route => route.fulfill({ contentType: 'audio/wav', body: wav }));
    await page.evaluate(async ({ kind, engine, wavUrl, durationPending }) => {
      if (engine === 'media3') {
        window.__mediaCalls = [];
        window.__mediaState = { playing: false, position: 0, duration: durationPending ? 0 : 90, rate: 1, ended: false, error: '' };
        Object.assign(window.FujimiMobile, {
          playMedia(url, position, rate) { __mediaCalls.push({ url, position, rate }); Object.assign(__mediaState, { playing: true, position, rate, ended: false }); return true; },
          mediaStatus: () => JSON.stringify(__mediaState),
          pauseMedia() { __mediaState.playing = false; }, stopMedia() { __mediaState.playing = false; __mediaState.position = 0; },
          seekMedia(position) { __mediaState.position = position; }, setMediaRate(rate) { __mediaState.rate = rate; }
        });
      }
      if (engine === 'browser') {
        window.__speechCalls = [];
        // Native SpeechSynthesisUtterance.voice requires a browser-owned voice.
        // Mock both speech interfaces so this isolated fixture never uses the OS.
        window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
        Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
          speak(utterance) { __speechCalls.push({ text: utterance.text, rate: utterance.rate }); utterance.onstart?.(); },
          cancel() {}, pause() {}, resume() {}, getVoices: () => [{ name: 'QA Japanese', lang: 'ja-JP' }], addEventListener() {}
        } });
        resolveJapaneseBrowserVoice = async () => ({ name: 'QA Japanese', lang: 'ja-JP' });
        state.browserVoiceName = '';
        state.voiceMode = 'browser';
      }
      const paragraphs = ['一つ目の段落を読みます。', '二つ目の段落を読みます。', '三つ目の段落を読みます。'];
      const segments = paragraphs.map(() => ({ duration: durationPending ? 10 : 30, speech_start_offset: 0, timing_source: 'edge_sentence' }));
      const audioUrl = engine === 'media3'
        ? (kind === 'news' ? '/api/articles/98100/assets/audio/qa.wav' : '/api/books/98101/audio/qa.wav')
        : '/api/audio/reader-type-player.wav';
      if (kind === 'news') {
        await openArticleInReader({ id: 98100, title: '朗読の操作を確かめる', source_name: '合成検証', status: 'ready',
          paragraphs, translated_paragraphs: ['第一段。', '第二段。', '第三段。'], full_translation: '第一段。第二段。第三段。',
          audio_status: engine === 'browser' ? 'browser' : 'ready', audio_path: engine === 'browser' ? '' : audioUrl, audio_segments: segments });
      } else {
        await showView('library');
        const chapter = { id: 1, title: '第一章', voice_mode: engine === 'browser' ? 'browser' : 'model',
          blocks: paragraphs.map((text_ja, index) => ({ id: `p${index}`, block_index: index, kind: 'paragraph', text_ja, text_zh: '検証用の訳文。' })),
          audio: engine === 'browser' ? { status: 'browser' } : { status: 'ready', url: audioUrl, segments } };
        await renderBookReader({ book: { id: 98101, title: '朗読の本', parser_version: 2, chapters: [chapter], bookmarks: [], progress: {} }, chapter });
      }
      // Use an actual decoded data WAV as the existing paragraph-boundary test
      // does. A mocked HTTP 200 without Range responses cannot seek a long WAV.
      if (engine === 'html') state.articleAudio.audio.src = wavUrl;
    }, { kind, engine, wavUrl: `data:audio/wav;base64,${wav.toString('base64')}`, durationPending: engine === 'media3' && kind === 'news' && width === 375 });
    const player = page.locator(`${region} .article-audio-player`);
    await player.waitFor({ state: 'visible' });
    assert.equal(await player.locator('.audio-player-previous').count(), 1, 'Previous paragraph button must exist');
    assert.equal(await player.locator('.audio-player-next').count(), 1, 'Next paragraph button must exist');
    if (engine === 'html') await page.waitForFunction(() => state.articleAudio.audio.readyState >= 3 && state.articleAudio.timeline.length === 3);
    const previous = player.locator('.audio-player-previous'), next = player.locator('.audio-player-next'), toggle = player.locator('.audio-player-toggle');
    const isPlaying = () => page.evaluate(() => state.browserSpeech ? state.browserSpeech.playing : state.articleAudio.mobileNative ? state.articleAudio.mobileStatus.playing : !state.articleAudio.audio.paused);
    const active = index => page.waitForFunction(({ region, index }) => document.querySelector(`${region} .paragraph.is-audio-active`)?.dataset.audioIndex === String(index), { region, index });
    if (engine === 'media3' && kind === 'news' && width === 375) {
      await next.click();
      assert.equal(await player.getAttribute('data-paragraph-index'), '1', 'A pending native duration must not reset the selected paragraph');
      await next.click();
      assert.equal(await player.getAttribute('data-paragraph-index'), '2');
      assert.deepEqual(await page.evaluate(() => __mediaCalls.map(call => call.position)), [10, 20], 'Two next clicks must reach distinct paragraph starts before Media3 duration arrives');
      assert.equal(await next.isDisabled(), true);
      await previous.click(); await previous.click(); await toggle.click();
      await page.evaluate(() => { __mediaState.duration = 90; });
      await page.waitForFunction(() => state.articleAudio.mobileStatus.duration === 90);
      result.pendingDurationNavigation = true;
    }
    assert.equal(await previous.isDisabled(), true, 'At the first paragraph, previous is disabled');
    assert.equal(await next.isDisabled(), false);
    await toggle.click();
    await page.waitForFunction(() => state.browserSpeech ? state.browserSpeech.playing : state.articleAudio.mobileNative ? state.articleAudio.mobileStatus.playing : !state.articleAudio.audio.paused);
    await page.waitForFunction(region => document.querySelector(`${region} .audio-player-toggle img`)?.getAttribute('src') === '/static/player_assets/ic_player_play.png', region);
    await next.click(); await active(1);
    assert.equal(await isPlaying(), true, 'Next paragraph starts playback');
    await next.click(); await active(2);
    assert.equal(await next.isDisabled(), true, 'At the last paragraph, next is disabled');
    await next.evaluate(element => element.click());
    await active(2);
    await previous.click(); await active(1);
    await toggle.click();
    assert.equal(await isPlaying(), false, 'Play toggle pauses the active engine');
    await player.locator('.audio-rate-toggle').click();
    await player.locator('[data-rate="1.5"]').click();
    assert.equal(await page.evaluate(() => (state.browserSpeech || state.articleAudio).rate), 1.5);
    assert.equal(await page.evaluate(() => localStorage.getItem('fujimi-playback-rate')), '1.5');
    if (engine === 'html') assert.equal(await page.evaluate(() => state.articleAudio.audio.playbackRate), 1.5);
    if (engine === 'media3') assert.equal(await page.evaluate(() => __mediaState.rate), 1.5);
    const rateToggle = player.locator('.audio-rate-toggle');
    await rateToggle.focus();
    await rateToggle.press('ArrowDown');
    assert.equal(await player.locator('[data-rate="1.5"]').evaluate(element => element === document.activeElement), true, 'Opening the speed menu focuses the selected rate');
    await page.keyboard.press('End');
    assert.equal(await player.locator('[data-rate="2"]').evaluate(element => element === document.activeElement), true);
    await page.keyboard.press('Home');
    assert.equal(await player.locator('[data-rate="0.5"]').evaluate(element => element === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await player.locator('.audio-rate-menu').isHidden(), true);
    assert.equal(await rateToggle.evaluate(element => element === document.activeElement), true, 'Closing the speed menu restores trigger focus');
    await player.locator('.audio-player-progress').evaluate(element => { element.value = '0'; element.dispatchEvent(new Event('input', { bubbles: true })); element.dispatchEvent(new Event('change', { bubbles: true })); });
    await active(0);
    assert.equal(await previous.isDisabled(), true, 'Seeking to start restores the first-paragraph boundary');
    if (engine !== 'browser') await toggle.click();
    assert.equal(await isPlaying(), true, 'Playback resumes at the selected position');
    if (engine === 'browser') assert.equal(await page.evaluate(() => __speechCalls.at(-1).rate), 1.5);
    await toggle.click();
    assert.equal(await isPlaying(), false);
    await page.waitForFunction(region => document.querySelector(`${region} .audio-player-toggle img`)?.getAttribute('src') === '/static/player_assets/ic_player_stop.png', region);
    if (engine === 'browser' && kind === 'news' && width === 375) {
      const gaps = await page.evaluate(() => {
        const controller = state.browserSpeech;
        const segments = [{ start: 0, end: 4 }, { start: 5, end: 9 }, { start: 10, end: 14 }];
        const result = [4, 9].map(index => {
          renderBrowserSpeech({ ...controller, segments, index });
          const player = controller.root.querySelector('.article-audio-player');
          return { index: Number(player.dataset.paragraphIndex), nextDisabled: player.querySelector('.audio-player-next').disabled };
        });
        renderBrowserSpeech(controller);
        return result;
      });
      assert.deepEqual(gaps, [{ index: 0, nextDisabled: false }, { index: 1, nextDisabled: false }], 'Newline gaps remain in the preceding paragraph and keep next available');
      result.newlineGapNavigation = true;
    }
    const listenToggle = player.locator('.audio-listen-toggle'), listenMenu = player.locator('.audio-listen-menu');
    const languageMode = () => page.evaluate(({ region, kind }) => {
      const root = kind === 'news' ? document.querySelector(`${region} .article-detail`) : document.querySelector(region);
      return kind === 'news' ? root.dataset.translationMode : root.dataset.languageMode;
    }, { region, kind });
    await listenToggle.click();
    await listenMenu.locator('[data-listening-mode="original"]').click();
    assert.equal(await languageMode(), kind === 'news' ? 'hide' : 'ja', 'Listen to original hides the translation');
    await listenToggle.click();
    await listenMenu.locator('[data-listening-mode="parallel"]').click();
    assert.equal(await languageMode(), kind === 'news' ? 'show' : 'parallel', 'Parallel listening restores translations');
    await next.click(); await active(1); await toggle.click();
    await listenToggle.click();
    await listenMenu.locator('.audio-player-replay').click();
    await active(1);
    assert.equal(await isPlaying(), true, 'Replay restarts the current paragraph through the selected engine');
    assert.equal(await player.getAttribute('data-paragraph-index'), '1');
    await toggle.click();
    await previous.click(); await active(0); await toggle.click();
    await listenToggle.focus(); await listenToggle.press('ArrowDown');
    assert.equal(await listenMenu.locator('[data-listening-mode="original"]').evaluate(element => element === document.activeElement), true);
    await page.keyboard.press('Escape');
    assert.equal(await listenMenu.isHidden(), true);
    assert.equal(await listenToggle.evaluate(element => element === document.activeElement), true, 'Escape restores the listen trigger focus');
    await listenToggle.click();
    assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true, 'Android back handles the listening menu');
    assert.equal(await listenMenu.isHidden(), true);
    assert.equal(await listenToggle.evaluate(element => element === document.activeElement), true, 'Android back restores the listen trigger focus');
    result.listeningMenu = true;
    result.focusOutline = await listenToggle.evaluate(element => getComputedStyle(element).outlineColor);
    if (engine === 'html' && kind === 'news' && width === 375) await player.screenshot({ path: path.join(output, 'player-focus-news-375.png') });
    await player.locator('.audio-rate-toggle').click();
    await player.locator('[data-rate="1"]').click();
    await page.evaluate(() => document.activeElement?.blur());
    result.layout = await player.evaluate(element => {
      const rect = node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
      const selectors = ['.audio-player-current', '.audio-player-progress', '.audio-player-duration', '.audio-listen-toggle', '.audio-player-previous', '.audio-player-toggle', '.audio-player-next', '.audio-rate-toggle', '.audio-rate-value'];
      const css = getComputedStyle(element);
      const styles = Object.fromEntries(selectors.map(selector => {
        const style = getComputedStyle(element.querySelector(selector));
        return [selector, { background: style.backgroundColor, color: style.color, fontSize: parseFloat(style.fontSize) }];
      }));
      const images = Object.fromEntries(['.audio-listen-toggle', '.audio-player-previous', '.audio-player-toggle', '.audio-player-next', '.audio-rate-toggle'].map(selector => {
        const node = element.querySelector(`${selector} img`);
        return [selector, { ...rect(node), src: node.getAttribute('src'), loaded: node.complete && node.naturalWidth > 0, filter: getComputedStyle(node).filter }];
      }));
      return { player: rect(element), viewport: { width: innerWidth, clientWidth: document.documentElement.clientWidth, layoutRight: document.documentElement.getBoundingClientRect().right, height: innerHeight },
        surface: { background: css.backgroundColor, shadow: css.boxShadow, border: parseFloat(css.borderTopWidth), bottomRadius: css.borderBottomLeftRadius },
        styles, images, controls: Object.fromEntries(selectors.map(selector => [selector, rect(element.querySelector(selector))])) };
    });
    const { controls, images, styles, surface, player: panel } = result.layout;
    const near = (actual, expected, label, tolerance = 1) => assert(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} instead of ${expected}`);
    const centerX = rect => rect.x + rect.width / 2, centerY = rect => rect.y + rect.height / 2;
    const isNeutral = color => { const rgb = color.match(/[\d.]+/g)?.slice(0, 3).map(Number) || []; return rgb.length === 3 && Math.max(...rgb) - Math.min(...rgb) <= 3; };
    assert(isNeutral(result.focusOutline), 'Player keyboard focus uses neutral ink rather than the old green accent');
    assert(Object.values(controls).every(rect => rect.x >= -1 && rect.right <= width + 1 && rect.y >= 0 && rect.bottom <= result.layout.viewport.height + 1), 'Player controls stay within the viewport');
    assert(controls['.audio-player-progress'].y < controls['.audio-player-toggle'].y, 'Timeline occupies the first row');
    near(panel.x, width > 980 ? 248 : width > 900 ? 204 : 0, 'Panel starts at the screen/content edge');
    near(panel.right, result.layout.viewport.layoutRight, 'Panel reaches the right edge, excluding the reserved scrollbar gutter');
    near(panel.bottom, result.layout.viewport.height, 'Panel is flush to the bottom');
    assert.equal(surface.background, 'rgb(255, 255, 255)', 'The reference panel is white');
    assert.equal(surface.shadow, 'none', 'The reference panel has no floating-card shadow');
    assert.equal(surface.border, 0, 'The reference panel has no outlined card border');
    assert.equal(surface.bottomRadius, '0px', 'No rounded bottom leaves a floating outer gap');
    assert(Object.entries(styles).every(([selector, style]) => isNeutral(style.background) && (selector === '.audio-player-progress' || isNeutral(style.color))), 'Visible player controls retain neutral black/gray colors without green accents');
    near(controls['.audio-player-current'].x - panel.x, 16, 'Timeline left inset');
    near(panel.right - controls['.audio-player-duration'].right, 16, 'Timeline right inset');
    near(styles['.audio-player-current'].fontSize, 14, 'Timeline text size', .1);
    near(styles['.audio-player-duration'].fontSize, 14, 'Duration text size', .1);
    near(centerX(controls['.audio-player-toggle']), panel.x + panel.width / 2, 'Play is centered in the panel');
    near(centerY(controls['.audio-player-previous']), centerY(controls['.audio-player-toggle']), 'Previous/play vertical alignment');
    near(centerY(controls['.audio-player-next']), centerY(controls['.audio-player-toggle']), 'Next/play vertical alignment');
    near(controls['.audio-player-toggle'].x - controls['.audio-player-previous'].right, 10, 'Previous/play gap');
    near(controls['.audio-player-next'].x - controls['.audio-player-toggle'].right, 10, 'Play/next gap');
    for (const [selector, size, iconSize, asset] of [
      ['.audio-player-previous', 36, 16, 'ic_player_prev.png'], ['.audio-player-toggle', 40, 22, 'ic_player_stop.png'], ['.audio-player-next', 36, 16, 'ic_player_next.png']
    ]) {
      near(controls[selector].width, size, `${selector} original visual width`);
      near(controls[selector].height, size, `${selector} original visual height`);
      near(images[selector].width, iconSize, `${selector} glyph width`);
      near(images[selector].height, iconSize, `${selector} glyph height`);
      near(centerX(images[selector]), centerX(controls[selector]), `${selector} glyph horizontal center`);
      near(centerY(images[selector]), centerY(controls[selector]), `${selector} glyph vertical center`);
      assert.equal(images[selector].src, `/static/player_assets/${asset}`);
    }
    near(controls['.audio-listen-toggle'].width, 70, 'Listen/read entry width');
    near(controls['.audio-listen-toggle'].height, 38, 'Listen/read entry height');
    near(controls['.audio-listen-toggle'].x - panel.x, 20, 'Listen/read left inset');
    assert.equal(images['.audio-listen-toggle'].src, '/static/player_assets/ic_common_listen_read.png');
    near(centerY(images['.audio-listen-toggle']), centerY(controls['.audio-listen-toggle']), 'Listen/read image remains centered');
    near(images['.audio-rate-toggle'].width, 24, 'Original settings icon width');
    near(images['.audio-rate-toggle'].height, 24, 'Original settings icon height');
    assert.equal(images['.audio-rate-toggle'].src, '/static/player_assets/ic_player_set.png');
    assert(Object.entries(images).every(([selector, icon]) => icon.x >= controls[selector].x - 1 && icon.right <= controls[selector].right + 1 && icon.y >= controls[selector].y - 1 && icon.bottom <= controls[selector].bottom + 1), 'Original icons remain inside their controls');
    assert(Object.values(images).every(icon => icon.loaded && icon.filter === 'none'), 'All original PNG icons decode and remain untinted');
    near(styles['.audio-rate-value'].fontSize, 10, 'Rate corner badge text', .1);
    near(controls['.audio-rate-value'].x - images['.audio-rate-toggle'].x, 15, 'Rate badge is attached to the icon right shoulder');
    near(images['.audio-rate-toggle'].bottom - controls['.audio-rate-value'].bottom, 16, 'Rate badge sits against the icon upper-right corner without a vertical gap');
    assert(controls['.audio-rate-value'].x >= centerX(images['.audio-rate-toggle']) && controls['.audio-rate-value'].y < centerY(images['.audio-rate-toggle']), 'Rate is placed at the settings icon upper-right corner');
    if (engine === 'html') {
      await page.screenshot({ path: path.join(output, `player-${kind}-${width}.png`) });
      await player.screenshot({ path: path.join(output, `player-panel-${kind}-${width}.png`) });
      if (width <= 900) {
        await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
        await toggle.click(); await toggle.click();
        await page.waitForFunction(region => [...document.querySelectorAll(`${region} .article-audio-player img`)].every(icon => icon.complete && icon.naturalWidth > 0), region);
        const dark = await player.evaluate(element => ({ background: getComputedStyle(element).backgroundColor,
          icons: [...element.querySelectorAll('img')].map(icon => ({ src: icon.getAttribute('src'), filter: getComputedStyle(icon).filter })) }));
        assert.equal(dark.background, 'rgb(28, 28, 30)');
        assert(dark.icons.every(icon => /_dark\.png$/.test(icon.src) && icon.filter === 'none'), 'Dark mode uses original dark assets without CSS inversion');
        await page.screenshot({ path: path.join(output, `player-dark-${kind}-${width}.png`) });
        result.darkArtwork = true;
      }
    }
    assert.deepEqual(errors, []);
  } catch (error) {
    const stateAtFailure = await page.evaluate(() => ({
      native: state.articleAudio && { position: state.articleAudio.audio.currentTime, duration: state.articleAudio.audio.duration, started: state.articleAudio.started, timeline: state.articleAudio.timeline, pending: state.articleAudio.pendingParagraph, mobile: state.articleAudio.mobileStatus },
      browser: state.browserSpeech && { index: state.browserSpeech.index, playing: state.browserSpeech.playing },
      active: [...document.querySelectorAll('.paragraph.is-audio-active')].map(element => element.dataset.audioIndex),
      buttons: [...document.querySelectorAll('.article-audio-player:not([hidden])')].map(element => ({ ...element.dataset })),
      notices: [...document.querySelectorAll('.toast')].map(element => element.textContent)
    })).catch(() => null);
    result.failures.push({ error: error.message, stack: error.stack, stateAtFailure });
    await page.screenshot({ path: path.join(output, `failure-${engine}-${kind}-${width}.png`) }).catch(() => {});
  }
  finally { await context.close(); }
  console.log(JSON.stringify({ player: true, width, kind, engine, failures: result.failures }));
  return result;
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const assets = Object.fromEntries(['static/index.html', 'static/main.js', 'static/static.css', 'static/book-reader.css',
    ...fs.readdirSync(path.join(root, 'static/player_assets')).filter(name => name.endsWith('.png')).sort().map(name => `static/player_assets/${name}`)].map(file =>
    [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, file))).digest('hex')]));
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  const results = [];
  const playerResults = [];
  try {
    if (!process.argv.includes('--player-only')) for (const width of [375, 390, 1440]) for (const color of ['light', 'dark']) results.push(await verifyFonts(browser, width, color));
    const selectedCase = process.argv.find(argument => argument.startsWith('--case='))?.slice(7);
    if (!process.argv.includes('--fonts-only')) for (const width of [375, 390, 1440]) for (const kind of ['news', 'book']) for (const engine of ['html', 'media3', 'browser']) {
      if (!selectedCase || selectedCase.split(',').includes(`${engine}-${kind}-${width}`)) playerResults.push(await verifyPlayer(browser, width, kind, engine));
    }
  }
  finally { await browser.close(); }
  const failureCount = [...results, ...playerResults].reduce((sum, result) => sum + result.failures.length, 0);
  fs.writeFileSync(path.join(output, process.argv.includes('--fonts-only') ? 'font-results.json' : process.argv.includes('--player-only') ? 'player-results.json' : 'results.json'), JSON.stringify({ assets, results, playerResults, failureCount }, null, 2));
  console.log(JSON.stringify({ groups: results.length, samples: results.reduce((sum, result) => sum + result.samples.length, 0), playerCases: playerResults.length, failureCount, output }));
  assert.equal(failureCount, 0, 'Reader typography/player contract failed; see results JSON');
})().catch(error => { console.error(error); process.exitCode = 1; });
