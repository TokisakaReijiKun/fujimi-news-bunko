// Formal Android assets with isolated API fixtures; no user library is accessed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const root = path.resolve(__dirname, '..');
const staticRoot = path.resolve(process.env.FUJIMI_TEST_STATIC_ROOT || path.join(root, 'static'));
const out = path.join(root, 'build/qa/mobile-app');
const text = '木漏れ日の中を、ゆっくり歩きます。';

async function fixture(browser, width, native = true, contextOptions = {}) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, ...contextOptions });
  const values = {
    'voice-mode': { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural', browser_voice_label: 'システム音声' },
    library: { sort: 'recent', lookup_chinese_translations: true },
    'daily-content': { target_count: 10, source_count: 6, required_count: 6 },
    'daily-schedule': { mode: 'manual', time: '00:00', scheduler_available: true }
  };
  const sources = ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'].map((name, i) => ({ id: i + 1, name, homepage: 'https://example.test/' + i, minimum_count: 1, voice_mode: 'browser' }));
  const article = { id: 90001, title: '合成テスト記事', source_name: 'NHKニュース', status: 'ready', url: 'https://example.test/article', published_at: '2026-11-04T09:00:00+09:00', voice_mode: 'none', audio_status: 'disabled', paragraphs: [text, text], furigana_paragraphs: [text, text], translated_paragraphs: ['合成测试译文。', '第二段译文。'], image_paths: [] };
  const chapter = { id: 1, title: '第一章', block_count: 2, voice_mode: 'none', blocks: [0, 1].map(i => ({ id: 'p' + i, block_index: i, kind: 'paragraph', text_ja: text, html: '<p>' + text + '</p>', text_zh: '合成测试译文。', bilingual_pair: true })) };
  const book = { id: 98001, title: '合成テスト書籍', author: '検証', parser_version: 2, reading_revision: 1, chapters: [chapter], toc: [{ title: '第一章', chapter_id: 1, depth: 0 }], bookmarks: [], progress: {} };
  const calls = [];
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    const api = url.pathname.replace('/__fixture', '');
    if (api.startsWith('/api/')) {
      calls.push({ path: api, method: request.method() });
      let data;
      const key = api.split('/').pop();
      if (api === '/api/health') data = { status: 'ok', runtime: 'android', tts: 'browser' };
      else if (api === '/api/browser-voices') data = [{ id: 'ja-JP-KeitaNeural', name: '圭太', available: true }, { id: 'ja-JP-NanamiNeural', name: '七海', available: true }];
      else if (api === '/api/settings/voices') data = [];
      else if (api === '/api/settings/news-sources') data = sources;
      else if (api.startsWith('/api/settings/news-sources/')) { data = sources.find(s => s.id === Number(key)); if (request.method() === 'PUT') Object.assign(data, request.postDataJSON()); }
      else if (values[key]) { if (request.method() === 'PUT') Object.assign(values[key], request.postDataJSON()); data = values[key]; }
      else if (api === '/api/settings/browser-voice') { Object.assign(values['voice-mode'], { browser_voice_name: request.postDataJSON().name }); data = values['voice-mode']; }
      else if (api === '/api/days') data = ['2026-11-04'];
      else if (api === '/api/daily') data = { date: '2026-11-04', articles: [article] };
      else if (api === '/api/tasks/daily') data = { status: 'idle' };
      else if (api === '/api/bookmarks') data = [{ ...article, bookmark_context: true }];
      else if (/\/api\/(articles|bookmarks)\/90001$/.test(api)) data = article;
      else if (api === '/api/books') data = { books: [book] };
      else if (api === '/api/books/98001') data = book;
      else if (api === '/api/books/98001/chapters/1') data = { book, chapter };
      else if (api === '/api/books/98001/progress') { book.progress = request.postDataJSON(); data = book; }
      else if (api === '/api/examples') data = [{ id: 'fixture', title: '保存した文章', text, translated_paragraphs: ['合成测试译文。'] }];
      else if (api === '/api/dictionary/stats') data = { entries: 159396, dictionary: '日中辞典' };
      else if (api === '/api/dictionary/tokenize') data = { tokens: request.postDataJSON().texts.map(value => [value]) };
      else data = [];
      return route.fulfill({ status: 200, json: data });
    }
    const file = path.resolve(staticRoot, '.' + url.pathname.substring('/static'.length));
    if (!url.pathname.startsWith('/static/') || !file.startsWith(staticRoot + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
    return route.fulfill({ path: file });
  });
  if (native) await context.addInitScript(() => {
    window.FujimiMobile = {
      request(raw, callback) { const req = JSON.parse(raw); fetch('/__fixture' + req.path, { method: req.method, body: req.body, headers: { 'Content-Type': 'application/json' } }).then(async r => window.__fujimiMobileResolve(callback, r.status, await r.text())); },
      mobileStatus: () => JSON.stringify({ app_version: 'test', data_path: '/test-library', paired: false, windows_status: 'unconfigured', sync_available: false, sync_state: 'unavailable', deepseek_configured: false, allow_cellular: false, exact_alarm: true, scheduler_available: true, daily_generation_available: true, reference_voices_available: true }),
      setAllowCellular: () => true
    };
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://127.0.0.1:8439/static/index.html');
  if (native) await page.waitForFunction(() => window.__fujimiApp?.ready);
  return { context, page, errors, values, sources, calls };
}

async function verify(browser, width) {
  const { context, page, errors, sources, values, calls } = await fixture(browser, width);
  const navigate = view => page.evaluate(v => window.__fujimiNavigate(v), view);
  await navigate('library');
  assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), false, 'Plain page navigation belongs to WebView history');
  await page.goBack();
  await page.waitForFunction(() => window.__fujimiApp.view === 'daily');
  for (const view of ['daily', 'reader', 'library', 'dictionary', 'settings', 'bookmarks']) {
    await navigate(view);
    const dimensions = await page.evaluate(() => { const main = document.querySelector('fujimi-app').shadowRoot.querySelector('.page-main'); return [document.documentElement.scrollWidth <= innerWidth, main.scrollWidth <= main.clientWidth + 1]; });
    assert(dimensions.every(Boolean), view + ' overflows');
    if (width === 390) await page.screenshot({ path: path.join(out, view + '-390.png') });
  }
  await navigate('library');
  const library = page.locator('fujimi-app .library-page');
  const importBook = library.getByRole('button', { name: '导入 EPUB', exact: true });
  assert(await importBook.isVisible());
  assert.equal(await library.getByRole('button', { name: 'PCと文庫を同期', exact: true }).count(), 0);
  assert.equal(await library.locator('.section-label').count(), 0);
  await importBook.click();
  assert.equal(await page.locator('fujimi-app dialog h2').textContent(), 'EPUB を追加');
  assert.match(await page.locator('fujimi-app dialog').textContent(), /未対応/);
  await page.locator('fujimi-app dialog').getByRole('button', { name: '閉じる', exact: true }).first().click();
  await navigate('reader');
  assert(await page.locator('fujimi-app .reader-divider').isVisible());
  await page.locator('fujimi-app').getByRole('button', { name: '本文を貼り付ける', exact: true }).click();
  assert(await page.locator('#web-text-dialog').isVisible(), 'Paste entry must open the existing text form on Android');
  await page.locator('#close-web-text-dialog').click();
  await navigate('daily');
  const issue = page.locator('fujimi-app .daily-issue');
  const update = issue.getByRole('button', { name: '日刊を更新', exact: true });
  const history = issue.getByRole('button', { name: '過去の日刊', exact: true });
  const updateBox = await update.boundingBox(), historyBox = await history.boundingBox();
  assert(updateBox.x + updateBox.width <= historyBox.x, 'Daily update belongs to the left of history');
  assert.equal(updateBox.y, historyBox.y, 'Both daily controls share one row');
  assert.equal(await history.evaluate(element => {
    const label = [...element.childNodes].find(node => node.nodeType === Node.TEXT_NODE);
    const range = document.createRange(); range.selectNodeContents(label);
    return range.getClientRects().length;
  }), 1, '過去の日刊 must remain a complete line');
  await update.click();
  await page.locator('fujimi-app dialog').getByRole('button', { name: '今すぐ作成', exact: true }).waitFor({ state: 'visible' });
  await page.locator('fujimi-app dialog').getByRole('button', { name: '閉じる', exact: true }).click();
  await navigate('settings');
  const settings = page.locator('fujimi-app .settings-page'), dialog = page.locator('fujimi-app dialog');
  assert.equal((await settings.locator('.settings-voice').boundingBox()).height, 56);
  assert.equal(await settings.locator('.settings-voice button').count(), 2);
  assert.equal(await settings.getByRole('button', { name: /文庫の場所|翻訳と通信/ }).count(), 0);
  await settings.locator('.sync-entry').click();
  await dialog.getByRole('button', { name: '翻訳と通信', exact: true }).click();
  assert(await dialog.getByLabel('DeepSeek APIキー').isVisible(), 'Existing native configuration must remain reachable');
  assert(await dialog.getByLabel('モバイル通信を許可').isVisible());
  await dialog.getByRole('button', { name: '閉じる', exact: true }).click();
  await settings.getByRole('button', { name: /文庫の点検/ }).click();
  assert.equal(await dialog.locator('h2').textContent(), '文庫の点検');
  await dialog.getByRole('button', { name: '閉じる', exact: true }).first().click();
  await settings.getByRole('button', { name: /ニュースソース/ }).click();
  assert.equal(await dialog.locator('.source-homepage').count(), 6);
  await dialog.locator('.source-form input').first().fill('5');
  assert.equal(await dialog.locator('button[aria-label$="増やす"]:not(:disabled)').count(), 0);
  await dialog.locator('.source-form input').first().fill('6');
  assert(await dialog.getByRole('button', { name: '保存', exact: true }).isDisabled());
  await dialog.getByRole('button', { name: '閉じる', exact: true }).click();
  await navigate('daily'); await page.locator('fujimi-app .news-item').first().click();
  await page.waitForFunction(() => window.__fujimiApp.reading === 'article');
  assert(await page.locator('#reader-result .article-detail').isVisible());
  assert(await page.locator('#reader-result .article-heading h1.title').isVisible());
  assert.equal(await page.locator('#reader-result .article-top, #reader-result .article-meta').count(), 0);
  assert((await page.locator('#reader-result .article-utility .published').textContent()).includes('2026'));
  assert((await page.locator('#reader-result .article-utility').boundingBox()).height <= 56);
  const articlePlayers = {};
  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme });
    articlePlayers[colorScheme] = await inspectPlayer(page, '#reader-result .article-detail');
    if (width === 390) await page.locator('#reader-result .article-audio-player').screenshot({ path: path.join(out, `article-player-${colorScheme}-390.png`) });
  }
  await page.emulateMedia({ colorScheme: 'light' });
  assert(await page.evaluate(() => window.__fujimiHandleBack()));
  await page.waitForFunction(() => !window.__fujimiApp.reading);
  await navigate('library'); await page.locator('fujimi-app .book-tile').first().click();
  await page.waitForFunction(() => window.__fujimiApp.reading === 'book');
  assert(await page.locator('#book-reader .book-reader-chrome').isVisible());
  await page.locator('#book-reader .toggle-book-settings').click();
  assert.equal(await page.locator('#book-reader .book-voice').evaluate(select => select.hidden), false);
  assert(await page.locator('#book-reader .book-settings-panel').getByRole('combobox', { name: 'この章の声線', exact: true }).isVisible(), 'Chapter voice selector must not be replaced by static text');
  assert(await page.locator('#book-reader .enhance-book-chapter').isVisible(), 'Chapter processing must not be hidden');
  assert(await page.locator('#book-reader .generate-book-audio').isVisible());
  assert.doesNotMatch(await page.locator('#book-reader .generate-book-audio').textContent(), /保存した朗読を読み込む/);
  await page.locator('#book-reader .close-book-settings').click();
  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme });
    const bookPlayer = await inspectPlayer(page, '#book-reader');
    assert.deepEqual(articlePlayers[colorScheme], bookPlayer, 'News and book playback controls must share appearance and geometry in ' + colorScheme);
    assert.equal(bookPlayer.tapHighlight, 'rgba(0, 0, 0, 0)', 'Touching play must not show the WebView blue rectangle');
    if (width === 390) await page.locator('#book-reader .article-audio-player').screenshot({ path: path.join(out, `book-player-${colorScheme}-390.png`) });
  }
  await page.emulateMedia({ colorScheme: 'light' });
  assert.equal(await page.locator('#book-reader .epub-scroll-rail').count(), 0);
  assert(await page.evaluate(() => window.__fujimiHandleBack()));
  await page.waitForFunction(() => !window.__fujimiApp.reading);
  assert(await page.evaluate(() => document.querySelector('#book-reader').hidden && state.libraryScrollHandler === null && state.libraryProgressTimer === null));
  const progressWrites = calls.filter(call => call.path.endsWith('/progress') && call.method === 'PUT').length;
  await page.evaluate(() => window.dispatchEvent(new Event('scroll'))); await page.waitForTimeout(600);
  assert.equal(calls.filter(call => call.path.endsWith('/progress') && call.method === 'PUT').length, progressWrites);
  assert.deepEqual(errors, []);
  assert(sources.every(s => s.minimum_count === 1)); assert.equal(values['daily-content'].target_count, 10);
  await context.close(); return { width, views: 6, readers: 2, back: true, quotas: true, sharedPlayer: ['light', 'dark'], blueTapHighlight: false, scrollRail: false };
}

async function inspectPlayer(page, selector) {
  return page.evaluate(selector => {
    const root = document.querySelector(selector), player = root.querySelector('.article-audio-player');
    // Exercise the real shared player markup without synthesizing or downloading audio.
    root.classList.add('has-audio-player'); player.hidden = false;
    renderAudioPlayerChrome(player, { playing: true, current: 43, duration: 186, progress: 43, maximum: 186, paragraphIndex: 0, paragraphCount: 2 });
    const read = element => {
      const css = getComputedStyle(element), box = element.getBoundingClientRect();
      return { width: box.width, height: box.height, background: css.backgroundColor, color: css.color,
        radius: css.borderRadius, border: css.borderTopWidth, align: css.alignItems, font: css.font };
    };
    const toggle = player.querySelector('.audio-player-toggle');
    return { player: read(player), toggle: read(toggle), timeline: read(player.querySelector('.audio-player-timeline')),
      transport: read(player.querySelector('.audio-player-transport')), rate: read(player.querySelector('.audio-rate-toggle')),
      rateValue: read(player.querySelector('.audio-rate-value')), tapHighlight: getComputedStyle(toggle).webkitTapHighlightColor };
  }, selector);
}

module.exports = { fixture };
if (require.main === module) (async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const results = [];
    for (const width of [375, 390, 1100]) results.push(await verify(browser, width));
    const { context, page, errors } = await fixture(browser, 1440, false);
    assert.equal(await page.locator('fujimi-app').count(), 0); assert(await page.locator('.app-shell').isVisible()); assert.deepEqual(errors, []); await context.close();
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify(results, null, 2)); console.log(JSON.stringify(results));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
