// Offline comparison with the existing pre-Tailscale PC build. No real app, VPN or library is accessed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const { fixture } = require('./verify_mobile_app.cjs');
const baseline = path.resolve(__dirname, '../build/tts-nikkei-release/FujimiShinbunBunko/_internal/static');
const output = path.resolve(__dirname, '../build/qa/pc-scope-restore');

async function capture(browser, original, width) {
  const { context, page, errors } = await fixture(browser, width, false);
  try {
    if (original) {
      for (const name of ['index.html', 'main.js', 'static.css', 'book-reader.css']) {
        await context.route('**/static/' + name + '*', route => route.fulfill({ path: path.join(baseline, name) }));
      }
      await page.reload();
    }
    await page.evaluate(async () => {
      await openArticleInReader({ id: 95001, status: 'ready', url: 'https://example.test/pc-layout', title: 'PCの読み方を保つ', source_name: '合成検証', published_at: '2026-11-05T09:00:00+09:00',
        paragraphs: ['図書館で本を読みます。', '次の段落です。'], furigana_paragraphs: ['<ruby>図書館<rt>としょかん</rt></ruby>で本を読みます。', '次の段落です。'],
        translated_paragraphs: ['在图书馆读书。', '下一段。'], full_translation: '在图书馆读书。\n\n下一段。', image_paths: [], audio_status: 'disabled' });
    });
    const measure = kind => page.evaluate(kind => {
      const root = document.querySelector(kind === 'article' ? '#reader-result .article-detail' : '#book-reader');
      const player = root.querySelector('.article-audio-player'); player.hidden = false;
      renderAudioPlayerChrome(player, { playing: false, current: 0, duration: 183, progress: 0, maximum: 183, paragraphCount: 2 });
      const style = element => {
        const c = getComputedStyle(element), r = element.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height, font: c.font, color: c.color,
          background: c.backgroundColor, border: c.border, radius: c.borderRadius, padding: c.padding, margin: c.margin,
          position: c.position, display: c.display, shadow: c.boxShadow, leading: c.lineHeight };
      };
      return { player: style(player), toggle: style(player.querySelector('.audio-player-toggle')),
        rate: style(player.querySelector('.audio-rate-toggle')), timeline: style(player.querySelector('.audio-player-timeline')),
        original: style(root.querySelector(kind === 'article' ? '.japanese' : '.book-block-ja')),
        translation: style(root.querySelector(kind === 'article' ? '.chinese' : '.book-block-zh')),
        controls: [...player.querySelectorAll('button')].map(e => [e.className, e.textContent.trim(), e.getAttribute('aria-label')]),
        overflow: document.documentElement.scrollWidth > innerWidth };
    }, kind);
    const article = await measure('article');
    await page.evaluate(async () => { await showView('library'); await openBook(98001); });
    await page.locator('#book-reader .book-block-ja').first().waitFor();
    const book = await measure('book');
    assert.deepEqual(errors, [], 'No PC runtime errors');
    return { width, article, book };
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const results = [];
    for (const width of [1100, 1440]) {
      const before = await capture(browser, true, width), after = await capture(browser, false, width);
      assert.deepEqual(after, before, width + 'px PC reading layout, typography and controls must match the original PC build');
      results.push(after);
    }
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'reading-baseline-comparison.json'), JSON.stringify(results, null, 2));
    console.log('Original PC article/book controls, player geometry and typography restored at 1100/1440px.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
