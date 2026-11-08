// Production page with temporary API fixtures; never reads the active library.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { fixture } = require('./verify_mobile_app.cjs');
const out = path.resolve(__dirname, '../build/qa/mobile-word-lookup');
const text = '日本でニュースを読みます。遅い電車です。東京へ行きます。';
const html = '<ruby>日本<rt>にほん</rt></ruby>で<strong>ニュース</strong>を読みます。遅い電車です。東京へ行きます。';
const words = {
  '日本': { id: '1', spell: '日本', pron: 'にほん', excerpt: '日本，亚洲国家。' },
  'ニュース': { id: '2', spell: 'ニュース', pron: 'ニュース', excerpt: '新闻，消息。' },
  '遅い': { id: '3', spell: '遅い', pron: 'おそい', excerpt: '慢，迟。' },
  '東京ドーム': { id: '4', spell: '東京ドーム', pron: 'とうきょうドーム', excerpt: '东京巨蛋。' }
};
async function verify(browser, width) {
  const { context, page, errors } = await fixture(browser, width, true, { isMobile: true, hasTouch: true });
  const queries = [];
  await page.evaluate(() => {
    const OriginalSegmenter = Intl.Segmenter;
    Intl.Segmenter = function (...args) {
      if (new Error().stack.includes('prepareMobileReadingLookup')) throw new Error('Reader lookup must use the original IPADIC segmentation');
      return new OriginalSegmenter(...args);
    };
  });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const api = url.pathname.replace('/__fixture', '');
    if (api === '/api/dictionary/tokenize') {
      const texts = JSON.parse(route.request().postData()).texts;
      const boundaries = { 'で': ['で'], 'ニュース': ['ニュース'], 'を読みます。遅い電車です。東京へ行きます。': ['を', '読み', 'ます', '。', '遅い', '電車', 'です', '。', '東京', 'へ', '行き', 'ます', '。'] };
      return route.fulfill({ json: { tokens: texts.map(text => boundaries[text] || [text]) } });
    }
    if (api === '/api/articles/90001') return route.fulfill({ json: { id: 90001, title: '点詞テスト', source_name: 'NHKニュース', status: 'ready', voice_mode: 'none', audio_status: 'disabled', paragraphs: [text, '日本。'], furigana_paragraphs: [html, '<ruby>日本<rt>にほん</rt></ruby>。'], translated_paragraphs: ['在东京读新闻。', '日本。'] } });
    if (api === '/api/dictionary/clickDetail') {
      const query = url.searchParams.get('q'); queries.push(query);
      if (query === '遅い') await new Promise(resolve => setTimeout(resolve, 250));
      const word = words[query];
      return route.fulfill(word ? { json: { ...word, accent: '0', moji_card: { title: `${word.spell} | ${word.pron} 0`, partOfSpeech: '名', meaning: word.excerpt + '\n\n', speechText: word.spell }, details: [{ partOfSpeech: ['名'] }], definitions: [{ id: word.id, lang: 'zh-CN', title: word.excerpt }], examples: [{ title: '検証の例文。', notationTitle: '仅详情显示的例句。' }] } } : { status: 404, json: { detail: '該当する語が見つかりません。' } });
    }
    if (api === '/api/dictionary/search') {
      const query = url.searchParams.get('q'); queries.push(query);
      if (query === '遅い') await new Promise(resolve => setTimeout(resolve, 250));
      return route.fulfill({ json: { results: query === '東京' ? [words['東京ドーム']] : words[query] ? [words[query]] : [] } });
    }
    if (api.startsWith('/api/dictionary/words/')) {
      const word = Object.values(words).find(w => w.id === api.split('/').pop());
      return route.fulfill({ json: { ...word, accent: '0', details: [{ partOfSpeech: ['名'] }], definitions: [{ id: word.id, lang: 'zh-CN', title: word.excerpt }], examples: [{ title: '検証の例文。', notationTitle: '仅详情显示的例句。' }] } });
    }
    return route.fallback();
  });
  await page.locator('fujimi-app').getByText('合成テスト記事', { exact: true }).first().click();
  await page.waitForFunction(() => window.__fujimiApp.reading === 'article');
  const original = page.locator('#reader-result .japanese').first();
  const tokyo = original.locator('[data-lookup-query="日本"]');
  assert.equal(await tokyo.count(), 1, 'Ruby words must become directly tappable');
  assert.equal(await original.locator('rt [data-lookup-query]').count(), 0, 'Reading annotations must not become separate lookup terms');
  await original.locator('[data-lookup-query="遅い"]').waitFor();
  assert.deepEqual(await original.locator('[data-lookup-query]').evaluateAll(nodes => nodes.map(node => node.dataset.lookupQuery).filter(query => !/[\p{L}\p{N}]/u.test(query))), [], 'Punctuation and whitespace must not become lookup buttons');
  assert.equal(await original.evaluate(element => { const copy = element.cloneNode(true); copy.querySelectorAll('rt, rp').forEach(node => node.remove()); return copy.textContent; }), text, 'Removing punctuation buttons must preserve the article text');
  await page.evaluate(() => {
    window.__qaSeeks = 0;
    const article = document.querySelector('#reader-result .article-detail');
    article.audioPlayerBindings = new AbortController();
    bindParagraphSeeking(article, () => window.__qaSeeks++);
  });
  await tokyo.evaluate(element => { const range = document.createRange(); range.selectNodeContents(element.querySelector('rb')); getSelection().removeAllRanges(); getSelection().addRange(range); });
  await tokyo.locator('rt').tap();
  const panel = page.locator('#selection-lookup');
  await panel.locator('.selection-lookup-detail').waitFor();
  assert.equal(queries.at(-1), '日本');
  assert.equal(await page.evaluate(() => getSelection().isCollapsed), true, 'The original handler clears an existing selection and still looks up the tapped word');
  assert.match(await panel.textContent(), /日本/);
  assert.equal(await page.evaluate(() => window.__qaSeeks), 0, 'Tapping a word must not seek playback');
  const box = await panel.boundingBox();
  assert.equal(Math.round(box.x), 16, 'Use the original floating card inset');
  assert.equal(Math.round(box.width), width - 32);
  assert.equal(Math.round(box.height), 246);
  assert.equal(await panel.evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(28, 28, 30)');
  assert.equal(await panel.locator('.dictionary-examples').count(), 0, 'The compact card contains meanings, not the full entry');
  assert.equal(await panel.locator('.moji-lookup-title').textContent(), '日本 | にほん 0');
  assert.equal(await panel.locator('.moji-lookup-meaning').textContent(), words['日本'].excerpt + '\n\n');
  assert.equal(await panel.locator('.moji-lookup-actions button').count(), 2);
  assert(await panel.locator('.moji-lookup-meaning').evaluate(element => {
    const original = element.textContent;
    element.textContent = (original + '\n').repeat(40);
    element.scrollTop = 80;
    const works = element.scrollHeight > element.clientHeight && element.scrollTop > 0;
    element.textContent = original;
    return works;
  }), 'Long meanings scroll inside the fixed card');
  await panel.locator('.moji-lookup-favorite').click();
  assert.equal(await panel.locator('.moji-lookup-favorite').getAttribute('aria-pressed'), 'true');
  await panel.getByRole('button', { name: '详情', exact: true }).click();
  assert(await panel.locator('.dictionary-examples').isVisible());
  assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
  assert(await panel.locator('.moji-lookup-card').isVisible());
  await page.evaluate(() => { window.FujimiMobile.openMojiDictionary = word => { window.__mojiWord = word; return true; }; });
  await panel.getByRole('button', { name: 'MOJi辞書', exact: true }).click();
  assert.equal(await page.evaluate(() => window.__mojiWord), '日本');
  assert(box.y > 400 && box.y + box.height <= 845, 'Lookup must remain at the bottom');
  assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
  assert(await panel.isHidden());
  assert.equal(await page.evaluate(() => window.__fujimiApp.reading), 'article');
  await original.locator('[data-lookup-query="遅い"]').tap();
  await tokyo.tap();
  await panel.locator('.selection-lookup-detail').waitFor();
  await page.waitForTimeout(350);
  assert.equal(await panel.locator('.moji-lookup-favorite').getAttribute('aria-pressed'), 'true');
  assert.equal(await panel.locator('.moji-lookup-title').textContent(), '日本 | にほん 0');
  await page.locator('#selection-lookup-close').click();
  await original.locator('[data-lookup-query="東京"]').tap();
  await page.waitForFunction(() => mobileCallbacks.size === 0 && document.querySelector('#selection-lookup').hidden);
  assert(await panel.isHidden(), 'An unavailable word must not open a custom candidate menu');
  for (let index = 0; index < 3; index++) {
    await original.locator('[data-lookup-query="で"]').tap();
    await page.waitForFunction(() => mobileCallbacks.size === 0 && document.querySelector('#selection-lookup').hidden);
  }
  assert.equal(await page.locator('#toast-region .toast').count(), 0, 'Ordinary dictionary misses must remain silent, including repeated taps');
  assert(await panel.isHidden());
  await original.locator('[data-lookup-query="ニュース"]').focus();
  await page.keyboard.press('Enter');
  await panel.locator('.selection-lookup-detail').waitFor();
  assert.equal(await panel.locator('.moji-lookup-title').textContent(), 'ニュース | ニュース 0');
  assert.equal(await page.evaluate(() => window.__qaSeeks), 0);
  await page.locator('#selection-lookup-close').click();
  const beforeSeek = queries.length;
  await page.evaluate(() => {
    const article = document.querySelector('#reader-result .article-detail');
    article.querySelector('.article-audio-player').dataset.playing = 'true';
    setActiveAudioParagraph(article, 1);
  });
  await tokyo.tap();
  assert.equal(await page.evaluate(() => window.__qaSeeks), 1, 'During playback, tapping another paragraph must seek as in the original');
  assert.equal(queries.length, beforeSeek);
  await page.evaluate(() => setActiveAudioParagraph(document.querySelector('#reader-result .article-detail'), 0));
  await tokyo.tap();
  await panel.locator('.selection-lookup-detail').waitFor();
  assert.equal(queries.at(-1), '日本', 'Tapping the playing paragraph opens the original word card');
  assert.equal(await page.evaluate(() => window.__qaSeeks), 1);
  assert.deepEqual(errors, []);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(out, `lookup-${width}.png`) });
  // EPUB and news must enter the same word-click bridge; Chinese stays untouched.
  await context.route('**/*', async route => {
    const api = new URL(route.request().url()).pathname.replace('/__fixture', '');
    if (api !== '/api/books/98001/chapters/1') return route.fallback();
    const chapter = { id: 1, title: '第一章', block_count: 1, voice_mode: 'none', blocks: [{ id: 'p0', block_index: 0, kind: 'paragraph', text_ja: text, html: '<p>' + html + '</p>', text_zh: '这段译文不应被分词。', bilingual_pair: true }] };
    const book = { id: 98001, title: '合成テスト書籍', author: '検証', parser_version: 2, reading_revision: 1, chapters: [chapter], toc: [{ title: '第一章', chapter_id: 1, depth: 0 }], bookmarks: [], progress: {} };
    return route.fulfill({ json: { book, chapter } });
  });
  await page.evaluate(() => window.__fujimiNavigate('library'));
  await page.locator('fujimi-app .book-tile').first().click();
  await page.waitForFunction(() => window.__fujimiApp.reading === 'book');
  const bookWord = page.locator('#book-reader .book-block-ja [data-lookup-query="日本"]');
  await bookWord.waitFor({ timeout: 2000 });
  assert.equal(await page.locator('#book-reader .book-block-zh [data-lookup-query]').count(), 0);
  await bookWord.locator('rt').tap();
  await panel.locator('.moji-lookup-card').waitFor();
  assert.equal(queries.at(-1), '日本');
  assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
  assert.equal(await page.evaluate(() => window.__fujimiApp.reading), 'book');
  assert(await panel.isHidden());
  await page.evaluate(() => setBookReadingMode(document.querySelector('#book-reader'), 'vertical'));
  await bookWord.locator('rt').tap();
  await panel.locator('.moji-lookup-card').waitFor();
  assert.equal(queries.at(-1), '日本');
  assert.deepEqual(errors, []);
  await context.close();
  return { width, queries, bottom: box, errors };
}
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const results = [];
    for (const width of [375, 390]) results.push(await verify(browser, width));
    const { context, page, errors } = await fixture(browser, 1440, false);
    await page.locator('#daily-view .news-card').first().waitFor();
    await page.evaluate(async () => { await openArticleInReader({ id: 9, status: 'ready', title: 'Desktop', paragraphs: ['日本でニュースを読みます。'], furigana_paragraphs: ['<ruby>日本<rt>にほん</rt></ruby>でニュースを読みます。'], translated_paragraphs: [], voice_mode: 'none', audio_status: 'disabled' }); });
    assert.equal(await page.locator('[data-lookup-query]').count(), 0, 'Desktop must retain its existing selection lookup');
    await page.locator('#reader-result .japanese').evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element.querySelector('ruby'));
      const selected = getSelection(); selected.removeAllRanges(); selected.addRange(range);
      element.dispatchEvent(new MouseEvent('mouseup', { button: 0, bubbles: true }));
    });
    await page.locator('#selection-lookup').waitFor();
    assert.equal(await page.locator('#selection-lookup-query').textContent(), '日本');
    assert.equal(await page.locator('#selection-lookup').evaluate(el => el.classList.contains('is-mobile-article')), false);
    assert.deepEqual(errors, []); await context.close();
    fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
