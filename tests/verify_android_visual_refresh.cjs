// Formal-page visual/interaction QA. All APIs and content are synthetic; no server,
// device storage, credentials, or user library is accessed. `before` reads HEAD.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const phase = process.argv[2] || 'after';
const previewOnly = process.argv.includes('--preview');
assert(['before', 'after'].includes(phase), 'Use before or after');
const output = path.join(root, 'build/qa/android-visual-refresh', phase);
const mainAssets = ['index.html', 'static.css', 'main.js', 'book-reader.css', 'book-reader.js', 'browser-speech.js'];
const assets = new Map(mainAssets.map(name => {
  const relative = `static/${name}`;
  return [`/${relative}`, phase === 'before'
    ? execFileSync('git', ['show', `HEAD:${relative}`], { cwd: root, maxBuffer: 8 * 1024 * 1024 })
    : fs.readFileSync(path.join(root, relative))];
}));
const mime = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript', '.svg': 'image/svg+xml' };
const names = ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'];
const paragraphs = [
  '秋の光が差し込む図書館で、地域の人たちが新しい読書の時間を楽しんでいます。',
  '静かな閲覧室には、子どもから大人まで自由に手に取れる本が並びます。言葉を通して、まだ知らない世界へ。',
  '担当者は「一冊との出会いが、毎日の小さな楽しみになればうれしい」と話しています。'
];
const translated = [
  '秋日阳光照进图书馆，居民们正在享受新的阅读时光。',
  '安静的阅览室里，摆放着供孩子和成人自由取阅的书。通过文字，走向尚未了解的世界。',
  '负责人说：“如果与一本书的相遇能成为日常的小小乐趣，我们会很高兴。”'
];
const titles = ['まちの図書館、秋を読む小さな時間', '暮らしを支える地域のつながり、新しい取り組み始まる', '夜空に広がる星を観測 子どもたちが科学に親しむ', '地域交通の未来を考える 市民と企業が対話', '日本の四季をたどる、小さな旅の記録', '文化を次の世代へ 商店街で開かれた秋の催し'];
const articles = titles.map((title, i) => ({
  id: i + 1, title, source_name: names[i], source_key: ['nhk', 'asahi', 'yomiuri', 'nikkei', 'sankei', 'yahoo'][i],
  url: `https://example.test/visual-fixture/${i + 1}`, status: 'ready', published_at: '2026-10-22T08:30:00+09:00',
  paragraphs, original_text: paragraphs.join('\n\n'), translated_paragraphs: translated, full_translation: translated.join('\n\n'),
  furigana_paragraphs: [paragraphs[0].replace('図書館', '<ruby>図書館<rt>としょかん</rt></ruby>'), ...paragraphs.slice(1)],
  image_paths: [], video_urls: [], voice_mode: 'browser', audio_status: 'browser', bookmarked: i < 3, tags: ['暮らし・文化', '地域', '科学'][i % 3]
}));
const books = ['雨の日の喫茶室', '山と風の便り', '星をつなぐ旅 第一巻', '星をつなぐ旅 第二巻', '言葉のある風景', '小さな庭の季節'].map((title, i) => ({
  id: i + 101, title, author: ['水野 由紀', '森川 直人', '青山 つむぎ'][i % 3], series: i === 2 || i === 3 ? '星をつなぐ旅' : '', volume: i === 2 ? '1' : i === 3 ? '2' : '',
  cover_url: `/__fixture/cover/${i}.svg`, parser_version: 2, reading_revision: 1,
  chapters: [{ id: 1, title: '第一章 窓辺の時間', source_href: 'chapter1.xhtml', nav_depth: 0 }, { id: 2, title: '第二章 新しい便り', source_href: 'chapter2.xhtml', nav_depth: 0 }],
  progress: { chapter_id: 1, block_index: 0, reading_mode: 'horizontal', language_mode: 'parallel' }, bookmarks: []
}));
const words = ['木漏れ日', '木立', '木の葉'].map((spell, i) => ({
  id: String(i + 701), spell, pron: ['こもれび', 'こだち', 'このは'][i], accent: '④', romaji: ['komorebi', 'kodachi', 'konoha'][i], tags: '#名詞',
  excerpt: ['透过树叶空隙洒下的阳光。', '成丛的树木，树丛。', '树叶，叶片。'][i],
  sections: [{ word: spell, pron: ['こもれび', 'こだち', 'このは'][i], senses: [{ number: '1', meaning: ['透过树叶空隙洒下的阳光。', '成丛的树木，树丛。', '树叶，叶片。'][i], examples: [{ title: '木漏れ日の中をゆっくり歩く。', notationTitle: '在从树叶间洒落的阳光中慢慢散步。' }] }] }]
}));

function coverSvg(index) {
  const colors = ['#385b4b', '#647464', '#4b6175', '#687d86', '#9b715e', '#93866b'];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="420" height="600" viewBox="0 0 420 600"><rect width="420" height="600" fill="${colors[index % colors.length]}"/><rect x="25" y="25" width="370" height="550" rx="2" fill="none" stroke="#ede7d5" opacity=".5"/><path d="M0 430Q80 350 180 430T420 410V600H0Z" fill="#e4ddc9" opacity=".24"/><circle cx="300" cy="180" r="65" fill="#e4ddc9" opacity=".2"/><text x="210" y="270" text-anchor="middle" fill="#f7f4e9" font-family="serif" font-size="25">${books[index % books.length].title}</text><text x="210" y="320" text-anchor="middle" fill="#e8e4d8" font-family="serif" font-size="16">${books[index % books.length].author}</text><text x="210" y="520" text-anchor="middle" fill="#e8e4d8" font-family="serif" font-size="13" letter-spacing="4">FUJIMI BUNKO</text></svg>`;
}

async function fixture(browser, width, colorScheme) {
  const native = width < 900;
  const context = await browser.newContext({ viewport: { width, height: width === 812 ? 390 : width < 900 ? 844 : 1000 }, colorScheme, reducedMotion: 'reduce', locale: 'ja-JP', deviceScaleFactor: 1 });
  const errors = [], missing = [], calls = [];
  const values = {
    'voice-mode': { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural', browser_voice_label: '圭太' },
    library: { sort: 'recent', lookup_chinese_translations: true },
    'daily-content': { target_count: 10, source_count: 6, required_count: 6 },
    'daily-schedule': { mode: 'manual', time: '08:00', scheduler_available: true }
  };
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/__fixture/cover/')) return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: coverSvg(Number(url.pathname.match(/(\d+)\.svg$/)[1])) });
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/__fixture/api/')) {
      const apiPath = url.pathname.replace('/__fixture', '');
      calls.push({ path: apiPath, method: request.method() });
      const key = apiPath.split('/').pop();
      let data;
      if (apiPath === '/api/health') data = { status: 'ok', tts: 'browser' };
      else if (apiPath === '/api/days') data = ['2026-10-22', '2026-10-21'];
      else if (apiPath === '/api/daily') data = { date: '2026-10-22', articles, generation_running: false };
      else if (apiPath === '/api/bookmarks') data = articles.slice(0, 3).map(article => ({ ...article, bookmark_context: true }));
      else if (/^\/api\/(articles|bookmarks)\/\d+$/.test(apiPath)) data = articles.find(article => article.id === Number(key));
      else if (apiPath === '/api/tasks/daily') data = { status: 'idle' };
      else if (apiPath === '/api/books') data = { books };
      else if (apiPath === '/api/books/tasks') data = { tasks: [] };
      else if (/^\/api\/books\/\d+$/.test(apiPath)) data = books.find(book => book.id === Number(key));
      else if (/^\/api\/books\/\d+\/chapters\/\d+$/.test(apiPath)) {
        const match = apiPath.match(/books\/(\d+)\/chapters\/(\d+)/), book = books.find(item => item.id === Number(match[1]));
        data = { book, chapter: { ...book.chapters.find(item => item.id === Number(match[2])), voice_mode: 'browser', audio: { status: 'browser' }, blocks: [...paragraphs, ...paragraphs].map((text, i) => ({ id: `p${i}`, block_index: i, kind: 'paragraph', text_ja: text, text_zh: translated[i % 3], bilingual_pair: true })) } };
      } else if (/^\/api\/books\/\d+\/progress$/.test(apiPath)) {
        const book = books.find(item => item.id === Number(apiPath.split('/')[3]));
        data = { ...book, progress: request.postDataJSON() };
      } else if (apiPath === '/api/dictionary/stats') data = { entries: 159396, dictionary: '日中辞典' };
      else if (apiPath === '/api/dictionary/search') data = { results: words };
      else if (/^\/api\/dictionary\/words\//.test(apiPath)) data = words.find(word => word.id === key);
      else if (apiPath === '/api/examples') data = [{ id: 'sample-reading', title: '窓辺の読書', text: paragraphs.join('\n\n'), translation: translated.join('\n\n') }];
      else if (apiPath === '/api/browser-voices') data = [{ id: 'ja-JP-KeitaNeural', name: '圭太', available: true }, { id: 'ja-JP-NanamiNeural', name: '七海', available: true }];
      else if (apiPath === '/api/settings/voices') data = [];
      else if (apiPath === '/api/settings/news-sources') data = names.map((name, i) => ({ id: i + 1, name, homepage: `https://example.test/source/${i}`, minimum_count: 1, voice_mode: 'browser' }));
      else if (apiPath === '/api/settings/device-sync') data = { enabled: false, paired_devices: 0 };
      else if (apiPath === '/api/settings/browser-voice') {
        const item = request.postDataJSON();
        data = Object.assign(values['voice-mode'], { browser_voice_name: item.name, browser_voice_label: item.label });
      } else if (apiPath.startsWith('/api/settings/') && values[key]) {
        if (request.method() === 'PUT') Object.assign(values[key], request.postDataJSON());
        data = values[key];
      } else {
        missing.push(`${request.method()} ${apiPath}`);
        return route.fulfill({ status: 501, contentType: 'application/json', body: JSON.stringify({ error: `Unimplemented visual fixture: ${apiPath}` }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    }
    if (assets.has(url.pathname)) return route.fulfill({ status: 200, contentType: mime[path.extname(url.pathname)], body: assets.get(url.pathname) });
    const file = path.resolve(root, '.' + url.pathname);
    if (file.startsWith(path.join(root, 'static') + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
    if (url.pathname !== '/favicon.ico') missing.push(`ASSET ${url.pathname}`);
    return route.fulfill({ status: 404, body: '' });
  });
  await context.addInitScript(({ native }) => {
    sessionStorage.setItem('fujimi-reader-article-id', '1');
    localStorage.setItem('fujimi-dictionary-history', JSON.stringify(['木漏れ日', '物語', '季節']));
    if (!native) return;
    window.FujimiMobile = {
      request: (raw, callback) => {
        const item = JSON.parse(raw);
        fetch('/__fixture' + item.path, { method: item.method, body: item.body, headers: { 'Content-Type': 'application/json' } })
          .then(async response => window.__fujimiMobileResolve(callback, response.status, await response.text()));
      },
      mobileStatus: () => JSON.stringify({ app_version: '1.0.12 · QA', data_path: '/storage/emulated/0/富士見新聞文庫/data', reference_voices_available: false, daily_generation_available: true, scheduler_available: true, exact_alarm: false, schedule_precision: 'inexact', sync_available: true, windows_status: 'unconfigured', sync_state: 'idle', allow_cellular: false, cache_bytes: 3145728 }),
      resolveMediaUrl: value => value
    };
  }, { native });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8439/static/index.html#daily');
  await page.locator('#daily-list .news-card').first().waitFor();
  await page.waitForFunction(() => !document.documentElement.classList.contains('mobile-app-booting'));
  return { page, context, native, errors, missing, calls, values };
}

async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function geometry(page, selector) {
  return page.evaluate(selector => {
    const region = document.querySelector(selector);
    const visible = element => {
      const rect = element.getBoundingClientRect(), style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && !element.closest('[hidden], [inert]');
    };
    const actions = [...region.querySelectorAll('button, input:not([type="hidden"]), select, a[href], [role="button"], summary')].filter(visible).map(element => {
      const rect = element.getBoundingClientRect();
      return { name: element.getAttribute('aria-label') || element.textContent.trim().slice(0, 60) || element.getAttribute('placeholder') || element.id, left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width), height: Math.round(rect.height), disabled: Boolean(element.disabled) };
    });
    return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, regionWidth: region.getBoundingClientRect().width, actions, overflow: actions.filter(action => action.left < -1 || action.right > innerWidth + 1) };
  }, selector);
}

async function capture(page, name, selector, evidence, { viewport = false } = {}) {
  // Let real transient feedback finish; do not remove or restyle product DOM.
  await page.waitForFunction(() => !document.querySelector('#toast-region .toast'));
  await settle(page);
  if (!viewport) await page.evaluate(() => window.scrollTo(0, 0));
  const layout = await geometry(page, selector);
  evidence.screens.push({ name, ...layout });
  if (layout.scrollWidth > layout.width + 1 || layout.overflow.length) evidence.failures.push({ name, reason: 'horizontal overflow', width: layout.width, scrollWidth: layout.scrollWidth, actions: layout.overflow });
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: !viewport });
}

async function navigate(page, view, native) {
  if (native) await page.locator('#mobile-nav-toggle').click();
  await page.locator(`.nav-button[data-view="${view}"]`).click();
  await page.locator(`#${view}-view`).waitFor({ state: 'visible' });
  const waits = { daily: '#daily-list .news-card', reader: '#reader-result .article-detail', bookmarks: '#bookmarks-list .news-card', library: '#library-series .book-card', dictionary: '#dictionary-stats', settings: '#voice-list .voice-card' };
  if (view === 'settings') await page.waitForFunction(() => document.querySelector('#voice-list').children.length && document.querySelector('#daily-source-total').textContent === '6 个来源');
  else if (view === 'dictionary') await page.waitForFunction(() => document.querySelector('#dictionary-stats').textContent.includes('159,396'));
  else await page.locator(waits[view]).first().waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page);
}

async function verify(browser, width, colorScheme) {
  const current = await fixture(browser, width, colorScheme);
  const { page, context, native, errors, missing, calls, values } = current;
  const label = `${native ? 'android' : 'desktop'}-${width}-${colorScheme}`;
  const evidence = { label, screens: [], checks: [], failures: [] };
  try {
    for (const view of ['daily', 'reader', 'bookmarks', 'library', 'dictionary', 'settings']) {
      await navigate(page, view, native);
      if (view === 'dictionary') {
        await page.locator('#dictionary-query').fill('木');
        await page.locator('#dictionary-query').press('Enter');
        await page.locator('.dictionary-result').first().waitFor();
        await page.locator('#dictionary-query').blur();
      }
      await capture(page, `${label}-${view}`, `#${view}-view`, evidence);
      if (view === 'reader') {
        assert.equal(await page.locator('#reader-result .paragraph').count(), 3);
        const toggle = page.locator('#reader-result .translation-menu-toggle');
        await toggle.click();
        await page.locator('#reader-result [data-translation-mode="hide"]').click();
        assert.equal(await page.locator('#reader-result .chinese:visible').count(), 0);
        await toggle.click();
        await page.locator('#reader-result [data-translation-mode="show"]').click();
        evidence.checks.push('article translation hide/show');
        await page.locator('#reader-result .exit-reader').click();
        await page.waitForFunction(() => !document.querySelector('#reader-result').children.length || !document.querySelector('#reader-result .article-detail'));
        await capture(page, `${label}-reader-empty`, '#reader-view', evidence);
      }
      if (view === 'library') {
        await page.locator('#library-series .series-card').click();
        await page.locator('#library-series-books .book-card').first().waitFor();
        await capture(page, `${label}-series`, '#library-view', evidence);
        await page.locator('#back-to-library').click();
        await page.locator('#library-series .book-card').first().click();
        await page.locator('#book-reader .book-block').first().waitFor();
        await capture(page, `${label}-book-reader`, '#book-reader', evidence);
        await page.locator('#book-reader .back-to-library').click();
        evidence.checks.push('series and book open/return');
      }
      if (view === 'dictionary') {
        await page.locator('.dictionary-result').first().click();
        await page.locator('.dictionary-word-title').waitFor();
        await capture(page, `${label}-dictionary-detail`, '#dictionary-view', evidence);
        if (native) {
          assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
          await page.waitForFunction(() => !document.querySelector('#dictionary-view').classList.contains('dictionary-detail-open'));
          evidence.checks.push('dictionary Android back');
        }
      }
    }
    if (native) {
      const trigger = page.locator('[data-android-select="library-sort-setting"]');
      await trigger.click();
      await capture(page, `${label}-sort-menu`, '#settings-view', evidence, { viewport: true });
      await page.locator('.android-select-list:visible').getByRole('option', { name: 'シリーズ・巻順', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('#library-sort-setting').value === 'series');
      assert.equal(values.library.sort, 'series');
      await page.locator('#add-voice').click();
      await page.locator('#voice-dialog').waitFor({ state: 'visible' });
      await capture(page, `${label}-voice-dialog`, '#voice-dialog', evidence, { viewport: true });
      assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
      const nav = page.locator('#mobile-nav-toggle');
      await nav.click();
      await page.waitForFunction(() => document.querySelector('.nav-button.active') === document.activeElement);
      assert.equal(await nav.getAttribute('aria-expanded'), 'true');
      assert.equal(await page.locator('#primary-sidebar').evaluate(element => element.inert), false);
      if (width === 812) {
        const reachable = [];
        for (const view of ['daily', 'reader', 'bookmarks', 'library', 'dictionary', 'settings']) {
          const item = page.locator(`#primary-sidebar .nav-button[data-view="${view}"]`);
          await item.click({ trial: true });
          const bounds = await item.boundingBox();
          assert(bounds.y >= 0 && bounds.y + bounds.height <= 390, `Landscape drawer action clipped: ${view}`);
          reachable.push({ view, top: Math.round(bounds.y), bottom: Math.round(bounds.y + bounds.height) });
        }
        evidence.checks.push({ landscapeDrawerReachability: reachable });
      }
      await capture(page, `${label}-drawer`, '#primary-sidebar', evidence, { viewport: true });
      const focused = await page.evaluate(() => ({ outline: getComputedStyle(document.activeElement).outlineStyle, shadow: getComputedStyle(document.activeElement).boxShadow }));
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.querySelector('#primary-sidebar').contains(document.activeElement)), true);
      await page.locator('#primary-sidebar .nav-button').last().focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#mobile-nav-close').evaluate(element => element === document.activeElement), true);
      await page.keyboard.press('Shift+Tab');
      assert.equal(await page.locator('#primary-sidebar .nav-button').last().evaluate(element => element === document.activeElement), true);
      assert.equal(await page.evaluate(() => window.__fujimiHandleBack()), true);
      assert.equal(await nav.getAttribute('aria-expanded'), 'false');
      assert.equal(await page.locator('#primary-sidebar').evaluate(element => element.inert), true);
      assert.equal(await nav.evaluate(element => element === document.activeElement), true);
      evidence.checks.push('sort persisted through API', 'voice dialog Android back', 'drawer focus/tab/back/restoration', focused);
    } else {
      assert.equal(await page.locator('.android-select-trigger').count(), 0);
      evidence.checks.push('desktop keeps standard select');
    }
    const motion = await page.evaluate(() => ({
      requested: matchMedia('(prefers-reduced-motion: reduce)').matches,
      transitions: ['.sidebar', '.mobile-nav-scrim', '.news-card', '.book-cover'].map(selector => {
        const element = document.querySelector(selector), css = element && getComputedStyle(element);
        return { selector, duration: css?.transitionDuration || '0s', animation: css?.animationName || 'none' };
      })
    }));
    assert(motion.requested);
    assert(motion.transitions.every(item => item.duration.split(',').every(value => parseFloat(value) <= 0.0001) && item.animation === 'none'), JSON.stringify(motion));
    evidence.checks.push({ reducedMotion: motion });
    if (width === 390) {
      await page.addStyleTag({ content: 'html { font-size: 125% !important; }' });
      for (const view of ['daily', 'dictionary', 'settings']) {
        await navigate(page, view, native);
        await capture(page, `${label}-${view}-text125`, `#${view}-view`, evidence);
      }
      evidence.checks.push({ textScale: 'html font-size:125%', computedRootSize: await page.evaluate(() => getComputedStyle(document.documentElement).fontSize) });
    }
    if (errors.length) evidence.failures.push({ reason: 'page errors', errors });
    if (missing.length) evidence.failures.push({ reason: 'unhandled fixture API/assets', missing });
    evidence.requests = calls.length;
  } catch (error) {
    evidence.failures.push({ reason: error.message, stack: error.stack });
    await page.screenshot({ path: path.join(output, `${label}-failure.png`), fullPage: true });
  } finally { await context.close(); }
  console.log(JSON.stringify({ label, screenshots: evidence.screens.length, failures: evidence.failures }));
  return evidence;
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const results = [];
  try {
    if (previewOnly) {
      for (const color of ['light', 'dark']) {
        const current = await fixture(browser, 390, color);
        const evidence = { label: `final-android-390-${color}`, screens: [], checks: [], failures: [] };
        try {
          const shadow = await current.page.locator('#primary-sidebar').evaluate(element => getComputedStyle(element).boxShadow);
          assert.equal(shadow, 'none', 'Closed drawer must not cast a shadow into the page');
          await capture(current.page, `${evidence.label}-daily`, '#daily-view', evidence);
          evidence.checks.push('closed drawer has no leaking shadow');
          assert.deepEqual(current.errors, []);
          assert.deepEqual(current.missing, []);
          results.push(evidence);
        } finally { await current.context.close(); }
      }
    } else {
      for (const width of [375, 390, 812, 1440]) for (const color of ['light', 'dark']) results.push(await verify(browser, width, color));
    }
  } finally { await browser.close(); }
  const failures = results.flatMap(result => result.failures);
  const report = { phase, source: phase === 'before' ? 'git HEAD' : 'working tree snapshot at script start', assets: Object.fromEntries([...assets].map(([name, content]) => [name, crypto.createHash('sha256').update(content).digest('hex')])), results, failures: failures.length };
  fs.writeFileSync(path.join(output, previewOnly ? 'final-preview.json' : 'results.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ phase, runs: results.length, screenshots: results.reduce((total, result) => total + result.screens.length, 0), failures: failures.length, output }));
  if (phase === 'after') assert.equal(failures.length, 0, 'See results.json for layout or interaction failures');
})().catch(error => { console.error(error); process.exitCode = 1; });
