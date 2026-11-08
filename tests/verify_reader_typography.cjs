// Compare rendered article and EPUB typography through the production application.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const rubyText = '<ruby><rb>東京</rb><rt>とうきょう</rt></ruby>を歩きます。';
const typography = ['font', 'size', 'leading', 'color', 'opacity'];

async function measure(page, kind) {
  return page.evaluate(kind => {
    const book = kind === 'book';
    const root = document.querySelector(book ? '#book-reader' : '.article-detail');
    const originals = root.querySelectorAll(book ? '.book-block-ja' : '.japanese');
    const ja = originals[0], zh = root.querySelector(book ? '.book-block-zh' : '.chinese');
    const style = element => {
      const value = getComputedStyle(element), rect = element.getBoundingClientRect();
      return { font: value.fontFamily, size: value.fontSize, leading: value.lineHeight, color: value.color, opacity: value.opacity, transform: value.transform,
        left: rect.left, width: rect.width, top: rect.top, height: rect.height, paddingRight: value.paddingRight };
    };
    return { ja: style(ja), zh: style(zh), ruby: style(ja.querySelector('rt')), translation: style(zh.querySelector('.translation-main') || zh),
      withinGroup: zh.getBoundingClientRect().top - ja.getBoundingClientRect().bottom,
      betweenGroups: originals[1].getBoundingClientRect().top - zh.getBoundingClientRect().bottom,
      bookmark: book ? style(root.querySelector('.book-block-bookmark')) : null,
      customRail: root.querySelectorAll('.epub-scroll-rail').length };
  }, kind);
}

function sameTypography(actual, expected, label) {
  for (const target of ['ja', 'zh', 'ruby', 'translation']) {
    for (const key of typography) assert.equal(actual[target][key], expected[target][key], label + ' ' + target + '.' + key);
  }
  assert.equal(actual.ruby.transform, expected.ruby.transform, label + ' ruby baseline');
  assert.equal(actual.withinGroup, expected.withinGroup, label + ' original/translation gap');
  assert.equal(actual.betweenGroups, expected.betweenGroups, label + ' paragraph gap');
  for (const target of ['ja', 'zh']) {
    assert.equal(actual[target].left, expected[target].left, label + ' ' + target + ' left gutter');
    assert.equal(actual[target].width, expected[target].width, label + ' ' + target + ' text width');
  }
}

async function verifyReaderTypography(browser, width, createFixture) {
  const factory = createFixture || require('./verify_mobile_app.cjs').fixture;
  const { context, page, errors } = await factory(browser, width);
  try {
    await page.evaluate(() => window.__fujimiNavigate('daily'));
    await page.locator('fujimi-app .news-item').first().click();
    await page.waitForFunction(() => window.__fujimiApp.reading === 'article');
    await page.locator('.article-detail .japanese').first().evaluate((element, html) => { element.innerHTML = html; }, rubyText);
    await page.evaluate(() => {
      document.querySelector('.article-detail').dataset.translationVisible = 'true';
      const translation = document.querySelector('.article-detail .chinese');
      translation.classList.remove('isHidden', 'isClickHidden'); translation.classList.add('isShow');
    });
    const article = await measure(page, 'article');
    await page.evaluate(() => window.__fujimiHandleBack());
    await page.waitForFunction(() => !window.__fujimiApp.reading);
    await page.evaluate(() => window.__fujimiNavigate('library'));
    await page.locator('fujimi-app .book-tile').first().click();
    await page.waitForFunction(() => window.__fujimiApp.reading === 'book');
    await page.locator('#book-reader .book-block-ja p').first().evaluate((element, html) => { element.innerHTML = html; }, rubyText);
    const book = await measure(page, 'book');
    sameTypography(book, article, width + 'px');
    assert.equal(book.customRail, 0, 'Custom reader scrollbar removed');
    assert.equal(book.ja.paddingRight, '0px', 'Bookmark does not narrow the reading column');
    assert(book.bookmark.left >= book.ja.left + book.ja.width, 'Bookmark stays in the right gutter');
    assert(book.bookmark.left + book.bookmark.width <= width, 'Bookmark remains within the viewport');
    assert.equal(await page.locator('#book-reader .book-chapter-body').evaluate(element => getComputedStyle(element).scrollbarWidth), 'none');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarWidth), 'none');

    const formatting = await page.locator('#book-reader .book-block-ja p').first().evaluate(element => {
      element.style.cssText = 'text-align:center;text-indent:1em;font-size:125%;font-weight:bold;font-style:italic';
      const value = getComputedStyle(element);
      return { align: value.textAlign, indent: value.textIndent, size: value.fontSize, weight: value.fontWeight, slant: value.fontStyle };
    });
    assert.deepEqual(formatting, { align: 'center', indent: '20px', size: '20px', weight: '700', slant: 'italic' });
    await page.locator('#book-reader .book-block-ja p').first().evaluate(element => element.removeAttribute('style'));

    await page.evaluate(() => setBookReadingMode(document.querySelector('#book-reader'), 'vertical'));
    const vertical = await page.locator('#book-reader .book-chapter-body').evaluate(element => {
      element.querySelector('.book-block-ja p').textContent = '縦書きのスクロールを確認します。'.repeat(100);
      element.scrollLeft = -100;
      return { scrollbar: getComputedStyle(element).scrollbarWidth, scrollable: element.scrollWidth > element.clientWidth, offset: element.scrollLeft };
    });
    assert.equal(vertical.scrollbar, 'none'); assert(vertical.scrollable); assert(vertical.offset < 0, 'Native vertical scrolling still works');
    assert.deepEqual(errors, []);
    return { width, article, book, nativeScrollbarsHidden: true, verticalScrollWorks: true, explicitEpubFormattingPreserved: true };
  } finally { await context.close(); }
}

async function verifyDesktopReaderUnchanged(browser, createFixture) {
  const factory = createFixture || require('./verify_mobile_app.cjs').fixture;
  const { context, page, errors } = await factory(browser, 1440, false);
  try {
    await page.evaluate(async () => { await showView('library'); await openBook(98001); });
    await page.locator('#book-reader .book-block-ja').first().waitFor();
    const snapshot = () => page.evaluate(() => {
      const result = {};
      for (const selector of ['.app-shell', '.sidebar', '#book-reader .book-block-ja', '#book-reader .book-block-zh']) {
        const element = document.querySelector(selector), value = getComputedStyle(element), rect = element.getBoundingClientRect();
        result[selector] = [value.display, value.fontFamily, value.fontSize, value.lineHeight, value.color, rect.left, rect.width];
      }
      return result;
    });
    const before = await snapshot();
    for (const name of ['mobile-reader.css', 'mobile-epub.css']) await page.addStyleTag({ content: fs.readFileSync(path.join(__dirname, '../static', name), 'utf8') });
    assert.deepEqual(await snapshot(), before, 'Untagged desktop typography and layout unchanged');
    assert.equal(await page.locator('fujimi-app').count(), 0); assert.deepEqual(errors, []);
    return { width: 1440, desktopUnchanged: true };
  } finally { await context.close(); }
}

module.exports = { verifyReaderTypography, verifyDesktopReaderUnchanged };
if (require.main === module) (async () => {
  const { chromium } = require('playwright-core');
  const browser = await chromium.launch({ executablePath: process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const results = [];
    for (const width of [375, 390]) results.push(await verifyReaderTypography(browser, width));
    results.push(await verifyDesktopReaderUnchanged(browser));
    const output = path.join(__dirname, '../build/qa/mobile-app'); fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'reader-typography-results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
