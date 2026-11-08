/* A fresh mobile interface, using the running library and its native readers. */
(() => {
  'use strict';
  const host = document.createElement('fujimi-preview');
  const root = host.attachShadow({ mode: 'open' });
  const sheetStyle = document.createElement('link'); sheetStyle.rel = 'stylesheet'; sheetStyle.href = '/next-ui.css?v=2.46';
  root.append(sheetStyle);
  const node = (tag, className = '', text) => {
    const result = document.createElement(tag); if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  };
  const q = selector => root.querySelector(selector);
  const icons = {
    news: 'M5 4h15v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8h3m0-4v14M9 8h7M9 12h7M9 16h4',
    book: 'M12 6v14M3 4c4-1 6 0 9 2 3-2 5-3 9-2v14c-4-1-6 0-9 2-3-2-5-3-9-2Z',
    shelf: 'M4 5h4v14H4zM10 5h4v14h-4zM16 6l3-1 4 13-4 1zM2 21h21',
    search: 'M15 15l5 5M16.5 10a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0',
    settings: 'M10.35 2.5h3.3l.55 2.1 1.4.58 1.9-1.1 2.33 2.34-1.1 1.9.58 1.4 2.1.55v3.3l-2.1.55-.58 1.4 1.1 1.9-2.33 2.34-1.9-1.1-1.4.58-.55 2.1h-3.3l-.55-2.1-1.4-.58-1.9 1.1-2.33-2.34 1.1-1.9-.58-1.4-2.1-.55v-3.3l2.1-.55.58-1.4-1.1-1.9L6.5 4.08l1.9 1.1 1.4-.58z M15.1 12a3.1 3.1 0 1 1-6.2 0 3.1 3.1 0 0 1 6.2 0Z',
    bookmark: 'M6 3h12v18l-6-4-6 4Z', next: 'm9 5 7 7-7 7', back: 'm15 5-7 7 7 7',
    close: 'm6 6 12 12M6 18 18 6', plus: 'M12 5v14M5 12h14', minus: 'M5 12h14',
    link: 'm9 15 6-6m-8 4-2 2a4 4 0 0 0 6 6l3-3m3-7 2-2a4 4 0 0 0-6-6l-3 3',
    paste: 'M8 5H4v16h16V5h-4M8 3h8v5H8zM8 12h8M8 16h5',
    speaker: 'M3 9h4l5-4v14l-5-4H3Zm13-1c3 2 3 6 0 8m3-11c5 4 5 10 0 14',
    check: 'm5 12 4 4L19 6', calendar: 'M5 5h14v16H5zM8 2v6m8-6v6M5 10h14',
    arrow: 'M5 12h14m-5-5 5 5-5 5', play: 'm9 5 10 7-10 7Z',
    computer: 'M3 4h18v13H3zM8 21h8m-4-4v4',
    phone: 'M7 2h10v20H7zM10 5h4m-3 14h2',
    copy: 'M8 8h12v13H8zM16 8V3H3v13h5',
    scan: 'M3 8V3h5m8 0h5v5M3 16v5h5m8 0h5v-5M8 8h3v3H8zm5 5h3v3h-3zM8 16h3m5-8v3'
  };
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', icons[name]); svg.append(path); return svg;
  }
  function button(text, action, className = '') {
    const result = node('button', className); result.type = 'button';
    if (text) result.textContent = text;
    if (action) result.addEventListener('click', event => Promise.resolve(action(event)).catch(error => notify(error.message, true)));
    return result;
  }
  function iconButton(name, label, action) {
    const result = button('', action, 'icon-button'); result.append(icon(name)); result.setAttribute('aria-label', label); return result;
  }
  const cache = { days: [], daily: null, books: [], bookmarks: [], voices: [], catalog: [], mode: {}, library: {}, schedule: {}, dailyConfig: {}, sources: [], sync: {}, examples: [], stats: {} };
  // Bookmarks are editable in this preview session without writing to the library.
  const previewBookBookmarks = new Map();
  const libraryApi = window.api;
  window.api = async (path, options) => {
    const bookmarkRoute = path.match(/^\/api\/books\/(\d+)\/chapters\/(\d+)\/bookmarks$/);
    if (bookmarkRoute && options?.method === 'POST') {
      const [, bookId, chapterId] = bookmarkRoute.map(Number);
      const { block_index } = JSON.parse(options.body);
      const { book, chapter } = await libraryApi(`/api/books/${bookId}/chapters/${chapterId}`);
      const block = chapter.blocks.find(item => item.block_index === block_index);
      if (!block || !bookBlockSupportsBookmark(chapter, block)) throw new Error('この段落にしおりを挟めません。');
      const [current] = previewBookBookmarks.get(bookId) ?? book.bookmarks ?? [];
      const bookmarked = current?.chapter_id !== chapterId || current?.block_index !== block_index;
      previewBookBookmarks.set(bookId, bookmarked ? [{
        chapter_id: chapterId, block_index, excerpt: (block.text_ja || block.text_zh || '').slice(0, 500)
      }] : []);
      return { bookmarked };
    }
    const result = await libraryApi(path, options);
    if (/^\/api\/books(?:\?|$|\/\d+(?:$|\/chapters\/\d+$))/.test(path)) {
      for (const book of result.books || [result.book || result]) {
        if (previewBookBookmarks.has(book.id)) book.bookmarks = previewBookBookmarks.get(book.id);
      }
    }
    return result;
  };
  const slogans = {
    daily: 'いま起きていることを、ひとつずつ。',
    reader: 'ひとつの記事を、ことばから深く読む',
    bookmarks: '心に留めた記事を、いつでもここに。',
    library: '物語の続きを、いつでもここから。',
    dictionary: 'ひとつの言葉から、世界をひらく。',
    settings: '読む時間を、自分らしく整える。'
  };
  const ui = { view: 'daily', reading: '', returnView: 'daily', date: '', loaded: false, request: 0 };
  let main, nav, modal, toast, toastTimer, syncRefreshTimer, referencePreview;
  const positions = new Map();
  const layout = node('div', 'layout');
  const masthead = node('header', 'masthead');
  const brand = button('', () => showPage('daily'), 'brand'); brand.setAttribute('aria-label', '富士見新聞文庫、日刊へ戻る');
  const brandCopy = node('span', 'brand-copy'); brandCopy.append(node('span', 'brand-name', '富士見新聞文庫'), node('small', 'brand-slogan', 'ニュースを、深く読む。'));
  brand.append(node('span', 'seal', '富士\n見'), brandCopy);
  masthead.append(brand);
  const readingBar = node('header', 'reader-bar');
  readingBar.append(iconButton('back', '返回列表', () => leaveReading()), node('span', '', '日刊'), node('span', 'reader-brand', '富士見新聞文庫'));
  main = node('main', 'page-main'); main.tabIndex = -1;
  nav = node('nav', 'bottom-nav'); nav.setAttribute('aria-label', 'メインナビゲーション');
  const navigation = [['daily', 'news', '日刊'], ['reader', 'book', '閲読室'], ['library', 'shelf', '書架'], ['dictionary', 'search', '辞書'], ['settings', 'settings', '設定']];
  for (const [view, glyph, label] of navigation) {
    const item = button('', () => showPage(view)); item.dataset.view = view; item.append(icon(glyph), node('span', '', label)); nav.append(item);
  }
  layout.append(masthead, readingBar, main, nav); root.append(layout);
  modal = node('dialog'); modal.setAttribute('aria-labelledby', 'sheet-title'); root.append(modal);
  toast = node('div', 'toast'); toast.hidden = true; toast.setAttribute('role', 'status'); root.append(toast);
  document.body.append(host);
  function notify(message, error = false) {
    toast.textContent = message;
    toast.hidden = false;
    toast.classList.toggle('is-error', error);
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
  }
  const noticeRegion = document.querySelector('#toast-region');
  const bookmarkMessages = new Set(['已收藏', '已取消收藏']);
  new MutationObserver(records => {
    if (ui.reading !== 'article' || !records.some(record => record.addedNodes.length)) return;
    const bookmarkNotices = [...noticeRegion.children].filter(notice =>
      notice.matches('.toast:not(.is-error)') && bookmarkMessages.has(notice.textContent)
    );
    bookmarkNotices.slice(0, -1).forEach(notice => notice.remove());
  }).observe(noticeRegion, { childList: true });
  modal.addEventListener('close', stopDictionarySpeech);
  modal.addEventListener('close', () => clearTimeout(syncRefreshTimer));
  modal.addEventListener('click', event => {
    if (event.target !== modal) return;
    const rect = modal.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close();
  });
  function sheet(title, build, description = '') {
    clearTimeout(syncRefreshTimer);
    modal.classList.remove('settings-sheet');
    const body = node('div', 'sheet-body');
    const heading = node('header', 'sheet-head');
    const titleNode = node('h2', '', title); titleNode.id = 'sheet-title';
    heading.append(titleNode, iconButton('close', '閉じる', () => modal.close()));
    modal.replaceChildren(node('div', 'sheet-handle'), heading, body);
    if (description) body.append(node('p', 'sheet-description', description));
    build(body);
    if (!modal.open) modal.showModal();
    return body;
  }
  function settingsSheet(title, build, description = '') {
    const body = sheet(title, build, description);
    modal.classList.add('settings-sheet');
    return body;
  }
  function explanation(title, text) {
    sheet(title, body => { body.append(button('知道了', () => modal.close(), 'primary')); }, text);
  }
  function heading(title, subtitle = '', action = null) {
    const result = node('header', 'page-heading'); const copy = node('div'); copy.append(node('h1', '', title));
    if (subtitle) copy.append(node('p', '', subtitle)); result.append(copy); if (action) result.append(action); return result;
  }
  function sectionLabel(title, detail = '') {
    const result = node('div', 'section-label'); result.append(node('h2', '', title)); if (detail) result.append(node('span', '', detail)); return result;
  }
  function empty(title, copy, glyph = 'book') {
    const result = node('section', 'empty'); result.append(icon(glyph), node('h2', '', title));
    if (copy) result.append(node('p', '', copy));
    return result;
  }
  function settingRow(label, value, action, className = '') {
    const row = button('', action, 'setting-row ' + className);
    const current = node('span', 'setting-value'); current.append(node('span', '', value), icon('next'));
    row.append(node('span', '', label), current); return row;
  }
  function group(title, ...rows) {
    const result = node('section', 'setting-group'); const list = node('div', 'setting-list'); list.append(...rows);
    result.append(node('h2', 'setting-group-title', title), list); return result;
  }
  function choice(label, subtitle, selected, action, available = true) {
    const row = button('', action, 'choice'); row.setAttribute('aria-pressed', String(selected)); row.disabled = !available;
    const copy = node('span'); copy.append(node('strong', '', label)); if (subtitle) copy.append(node('small', '', subtitle));
    const checked = node('span', 'check'); checked.append(icon('check')); row.append(copy, checked); return row;
  }
  function localVoice() { return cache.catalog.find(voice => voice.id === cache.mode.browser_voice_name); }
  function selectedVoice() {
    if (cache.mode.mode === 'voice') return cache.voices.find(voice => Number(voice.id) === Number(cache.mode.voice_id));
    if (cache.mode.mode === 'browser') return localVoice() || { name: browserVoiceShortName(cache.mode.browser_voice_name) || cache.mode.browser_voice_name };
    return null;
  }
  function published(article) {
    if (!article.published_at) return '';
    const date = new Date(article.published_at);
    if (Number.isNaN(date.getTime())) return String(article.published_at).slice(0, 16);
    return new Intl.DateTimeFormat('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }).format(date);
  }
  function articleCard(article, featured = false) {
    const image = article.image_paths?.find(path => typeof path === 'string' && path.startsWith('/api/'));
    const card = button('', () => enterArticle(article), 'news-item' + (featured ? ' featured' : '') + (image ? '' : ' no-image'));
    card.dataset.articleId = article.id; card.setAttribute('aria-label', article.title);
    const meta = node('div', 'news-meta'); meta.append(node('span', 'source', article.source_name), node('time', '', published(article)));
    card.append(meta, node('h2', '', article.title));
    if (image) { const photo = node('img', 'news-image'); photo.src = image; photo.alt = article.image_captions?.[0] || ''; photo.loading = featured ? 'eager' : 'lazy'; card.append(photo); }
    return card;
  }
  async function dailyPage(page) {
    const date = ui.date || cache.days[0];
    if (!date) { page.append(heading('本日ノニュース', slogans.daily), empty('今日の一篇は、これから。', '文库中还没有已保存的日刊。', 'news')); return; }
    if (!cache.daily || cache.daily.date !== date) cache.daily = await api('/api/daily?date=' + encodeURIComponent(date));
    const top = node('div', 'daily-heading'); top.append(heading('本日ノニュース', slogans.daily));
    const issue = node('div', 'daily-issue');
    const dateValue = new Date(date + 'T00:00:00+08:00');
    issue.append(node('p', '', new Intl.DateTimeFormat('ja-JP', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'Asia/Shanghai' }).format(dateValue)));
    const history = button('历史日刊', historySheet, 'text-button'); history.prepend(icon('calendar')); issue.append(history); top.append(issue); page.append(top);
    const list = node('section', 'news-list'); list.setAttribute('aria-label', '日刊文章');
    cache.daily.articles.forEach((article, index) => list.append(articleCard(article, index === 0))); page.append(list);
  }
  function historySheet() {
    sheet('歴史の日刊', body => {
      cache.days.forEach(date => body.append(choice(date, '', date === (ui.date || cache.days[0]), () => { ui.date = date; modal.close(); showPage('daily', { push: false }); })));
    }, '选择文库中已保存的日期。');
  }
  async function bookmarksPage(page) {
    cache.bookmarks = await api('/api/bookmarks');
    page.append(heading('收藏', slogans.bookmarks));
    if (!cache.bookmarks.length) {
      const blank = node('section', 'empty bookmark-empty');
      blank.append(node('h2', '', '心に留めた一篇を、\nいつまでも。')); page.append(blank); return;
    }
    page.append(sectionLabel('保存した記事', `${cache.bookmarks.length} 篇`));
    const list = node('section', 'news-list saved-list'); cache.bookmarks.forEach(article => list.append(articleCard(article))); page.append(list);
  }
  async function readerPage(page) {
    cache.examples = await api('/api/examples');
    page.append(heading('閲読室', slogans.reader));
    const intro = node('section', 'reader-intro');
    const mark = node('div', 'intro-mark'); mark.append(icon('link'), node('h2', '', '一篇から、読みはじめる'));
    intro.append(mark, node('p', '', '日刊やお気に入りにある記事のURLから、すぐに読めます'));
    const form = node('form', 'link-form');
    const label = node('label', 'field-label', '記事のURL'); label.htmlFor = 'room-url';
    const input = node('input', 'field'); input.id = 'room-url'; input.type = 'url'; input.placeholder = 'https://…'; input.required = true;
    const submit = node('button', 'primary', '記事を開く'); submit.type = 'submit'; submit.append(icon('arrow'));
    const error = node('p', 'error-note'); error.hidden = true;
    form.append(label, input, submit, error);
    form.addEventListener('submit', async event => {
      event.preventDefault(); error.hidden = true; submit.disabled = true;
      try {
        if (!cache.daily) cache.daily = await api('/api/daily?date=' + cache.days[0]);
        const all = [...cache.daily.articles, ...await api('/api/bookmarks')];
        const normalized = value => { const url = new URL(value); url.hash = ''; return url.href.replace(/\/$/, ''); };
        const article = all.find(item => item.url && normalized(item.url) === normalized(input.value.trim()));
        if (article) await enterArticle(article);
        else { error.textContent = '日刊やお気に入りに記事が見つかりません 新しい記事は本アプリで取り込めます'; error.hidden = false; }
      } catch { error.textContent = '記事を開けませんでした しばらくしてから、もう一度お試しください'; error.hidden = false; }
      finally { submit.disabled = false; }
    });
    intro.append(form, node('div', 'reader-divider', 'または'));
    const paste = button('本文を貼り付ける', () => { q('dialog')?.close(); document.querySelector('#open-web-text-dialog').click(); }, 'paste-action'); paste.prepend(icon('paste')); intro.append(paste); page.append(intro);
    page.append(sectionLabel('保存した文章', `${cache.examples.length} 件`));
    if (!cache.examples.length) page.append(node('p', 'status-note', '閲読室で保存した文章がここに並びます'));
    cache.examples.forEach(example => {
      const row = button('', () => openStoredText(example), 'stored-text');
      row.append(node('span', 'text-cover', String(example.title || '文').slice(0, 1)));
      const copy = node('span', 'stored-copy');
      copy.append(node('h3', '', example.title), node('p', '', `${String(example.text || '').length.toLocaleString('ja-JP')} 字${example.translated_paragraphs?.length ? ' ・ 訳文あり' : ''}`));
      row.append(copy, icon('next')); page.append(row);
    });
  }
  async function openStoredText(example) {
    const paragraphs = String(example.text || '').split(/\n\s*\n|\n/).map(text => text.trim()).filter(Boolean);
    const translations = example.translated_paragraphs || [];
    sheet(example.title, body => {
      const prose = node('article', 'saved-prose');
      paragraphs.forEach((text, index) => { prose.append(node('p', 'saved-ja', text)); if (translations.length === paragraphs.length && translations[index]) prose.append(node('p', 'saved-zh', translations[index])); });
      if (translations.length && translations.length !== paragraphs.length) { prose.append(node('p', 'status-note', '原文と訳文の段落数が異なるため、訳文は原文の後にまとめて表示します。')); translations.forEach(text => prose.append(node('p', 'saved-zh', text))); }
      body.append(prose);
    });
  }
  async function libraryPage(page) {
    cache.books = (await api('/api/books?sort=' + encodeURIComponent(cache.library.sort || 'recent'))).books;
    const add = button('导入', () => explanation('EPUB を追加', '当前展示你的真实书架。导入新书请在正式应用中执行，预览会保留文库原状。'), 'pill-action'); add.prepend(icon('plus')); add.setAttribute('aria-label', '导入 EPUB');
    page.append(heading('書架', slogans.library, add));
    if (!cache.books.length) { page.append(empty('本棚に、一冊を。', '正式应用导入的电子书会出现在这里。')); return; }
    page.append(sectionLabel('我的书籍', `${cache.books.length} 册`));
    const shelf = node('section', 'shelf'); shelf.setAttribute('aria-label', '电子书书架');
    cache.books.forEach(book => {
      const tile = button('', () => enterBook(book), 'book-tile'); tile.dataset.bookId = book.id;
      if (book.cover_url) { const image = node('img'); image.src = book.cover_url; image.alt = book.title + '的封面'; image.loading = 'eager'; tile.append(image); }
      else tile.append(node('span', 'no-cover', book.title));
      tile.append(node('h3', '', book.title), node('p', '', book.author)); shelf.append(tile);
    });
    page.append(shelf);
  }
  const nativeDictionary = document.querySelector('#dictionary-view');
  const nativeDictionaryContainer = nativeDictionary.parentElement;
  nativeDictionary.slot = 'native-dictionary';
  host.append(nativeDictionary);
  const dictionaryQuery = nativeDictionary.querySelector('#dictionary-query');
  const dictionaryQueryPlaceholder = dictionaryQuery.placeholder;
  const dictionaryQueryShell = nativeDictionary.querySelector('.dictionary-query-shell');
  const dictionarySearchIcon = icon('search');
  dictionarySearchIcon.classList.add('dictionary-home-search-icon');
  const dictionarySearchSubmit = button('', null, 'dictionary-home-submit');
  dictionarySearchSubmit.type = 'submit';
  dictionarySearchSubmit.setAttribute('aria-label', '検索');
  dictionarySearchSubmit.append(icon('arrow'));
  dictionaryQueryShell.prepend(dictionarySearchIcon);
  dictionaryQueryShell.append(dictionarySearchSubmit);
  let dictionaryPreviewPage;

  function updateDictionaryHome() {
    if (ui.view !== 'dictionary' || !dictionaryPreviewPage) return;
    const detailOpen = nativeDictionary.classList.contains('dictionary-detail-open')
      || (!isMobileDrawerLayout() && nativeDictionary.querySelector('.dictionary-word-header'));
    const home = !detailOpen;
    const welcome = home && !nativeDictionary.querySelector('#dictionary-query').value.trim()
      && nativeDictionary.querySelector('#dictionary-result-heading').hidden;
    nativeDictionary.toggleAttribute('data-dictionary-home', home);
    nativeDictionary.toggleAttribute('data-dictionary-welcome', welcome);
    dictionaryPreviewPage.classList.toggle('is-home', home);
    dictionaryQuery.placeholder = home ? '調べたい言葉' : dictionaryQueryPlaceholder;
    dictionaryPreviewPage.querySelector('.dictionary-home-heading').hidden = !home;
    dictionaryPreviewPage.querySelector('.dictionary-home-help').hidden = !welcome;
    dictionaryPreviewPage.querySelector('.dictionary-home-welcome').hidden = !welcome;
  }
  new MutationObserver(updateDictionaryHome).observe(nativeDictionary, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden']
  });

  function dictionaryContext(page) {
    const original = getComputedStyle(nativeDictionaryContainer);
    nativeDictionary.style.font = original.font;
    nativeDictionary.style.color = 'var(--ink)';
    for (const [property, value] of Object.entries(window.__nativeDictionaryTheme)) {
      nativeDictionary.style.setProperty(property, value);
    }
    nativeDictionary.style.setProperty('--paper', getComputedStyle(host).getPropertyValue('--paper'));
    page.style.paddingInline = original.paddingLeft + ' ' + original.paddingRight;
    page.style.background = 'var(--paper)';
  }

  async function dictionaryPage(page) {
    page.className = 'native-dictionary-page';
    dictionaryPreviewPage = page;
    const intro = node('div', 'dictionary-home-heading');
    intro.append(heading('辞書', slogans.dictionary), node('p', 'dictionary-home-count',
      Number(cache.stats.entries || 0).toLocaleString('ja-JP') + ' 語 · ' + (cache.stats.dictionary || '日中辞典')));
    const slot = node('slot');
    slot.name = 'native-dictionary';
    const welcome = node('div', 'dictionary-home-welcome');
    const copy = node('div');
    copy.append(node('h2', '', 'ことばを知る。読む世界が、広がる。'), node('p', '', '在阅读中遇见的词，都可以来这里查。'));
    welcome.append(node('span', '', '語'), copy);
    page.append(intro, slot, node('p', 'dictionary-home-help', '日本語・かな・ローマ字・中文释义'), welcome);
    dictionaryContext(page);
    await showView('dictionary', { historyMode: 'none' });
    updateDictionaryHome();
  }
  async function settingsPage(page) {
    [cache.mode, cache.voices, cache.library, cache.schedule, cache.dailyConfig, cache.sources, cache.sync] = await Promise.all([
      api('/api/settings/voice-mode'), api('/api/settings/voices'), api('/api/settings/library'), api('/api/settings/daily-schedule'), api('/api/settings/daily-content'), api('/api/settings/news-sources'), api('/api/settings/device-sync').catch(() => ({ status: 'error' }))]);
    page.append(heading('設定', slogans.settings));
    const voice = selectedVoice();
    const voiceName = voice?.name || '朗読しない';
    const card = node('div', 'settings-voice');
    const preview = iconButton('speaker', voiceName + 'の参照音声を再生', () => playReferencePreview(voice, preview));
    preview.innerHTML = DICTIONARY_SOUND_ICON;
    preview.classList.add('dictionary-speech-button', 'settings-voice-preview'); preview.setAttribute('aria-pressed', 'false');
    preview.dataset.playLabel = voiceName + 'の参照音声を再生'; preview.title = preview.dataset.playLabel;
    preview.disabled = cache.mode.mode !== 'voice' || !voice?.id;
    if (preview.disabled) { preview.title = 'この音声には参照音声がありません'; preview.setAttribute('aria-label', voiceName + 'には参照音声がありません'); }
    const change = button('', voiceSheet, 'settings-voice-select');
    change.setAttribute('aria-label', '朗読の音声を変更、' + voiceName);
    change.append(node('strong', 'settings-voice-name', voiceName), icon('next'));
    card.append(preview, change);
    page.append(card);
    const time = cache.schedule.mode === 'automatic' ? '毎日 ' + cache.schedule.time + ' CST' : '手動';
    page.append(group('日刊',
      settingRow('記事数', `${cache.dailyConfig.target_count} 篇`, dailyCountSheet),
      settingRow('ニュースソース', `${cache.sources.length} 件`, sourcesSheet),
      settingRow('更新方法', time, scheduleSheet)));
    page.append(group('読書',
      settingRow('書架の並び順', librarySortName(), sortSheet),
      settingRow('保存した記事', '一覧を見る', () => showPage('bookmarks'))));
    const connect = button('', deviceSheet, 'sync-entry');
    const devices = node('span', 'sync-entry-devices'); devices.append(icon('computer'), icon('link'), icon('phone'));
    const copy = node('span', 'sync-entry-copy');
    copy.append(node('strong', '', '端末をつなぐ'), node('small', '', deviceStatus(cache.sync)));
    connect.append(devices, copy, icon('next'));
    page.append(group('文庫互联', connect,
      settingRow('文庫の点検', '操作説明', maintenanceSheet)));
    page.append(node('p', 'settings-preview-note', '設定の変更は、このプレビュー内に一時保存されます。'));
  }
  function librarySortName() { return { recent: '最近読んだ順', imported: '追加した順', series: 'シリーズ順' }[cache.library.sort] || cache.library.sort || '最近読んだ順'; }
  function stopReferencePreview() {
    const active = referencePreview; referencePreview = null;
    if (!active) return;
    active.audio.onended = active.audio.onerror = null;
    active.audio.pause(); active.audio.removeAttribute('src'); active.audio.load(); active.audio.remove();
    active.button.setAttribute('aria-pressed', 'false'); active.button.removeAttribute('aria-busy');
    active.button.setAttribute('aria-label', active.button.dataset.playLabel); active.button.title = active.button.dataset.playLabel;
    active.button.classList.remove('is-speaking');
  }
  async function playReferencePreview(voice, control) {
    if (referencePreview?.button === control) { stopReferencePreview(); return; }
    stopReferencePreview(); stopDictionarySpeech();
    const audio = node('audio', 'voice-reference-audio'); audio.hidden = true; audio.preload = 'none';
    const active = { audio, button: control }; referencePreview = active;
    control.closest('.settings-voice').append(audio);
    control.setAttribute('aria-pressed', 'true'); control.setAttribute('aria-busy', 'true');
    control.setAttribute('aria-label', voice.name + 'の参照音声を停止'); control.title = voice.name + 'の参照音声を停止';
    control.classList.add('is-speaking');
    const fail = () => {
      if (referencePreview !== active) return;
      stopReferencePreview(); notify('参照音声を再生できません。', true);
    };
    audio.onended = () => { if (referencePreview === active) stopReferencePreview(); };
    audio.onerror = fail;
    audio.src = '/api/preview/voices/' + voice.id + '/reference';
    try { await audio.play(); if (referencePreview === active) control.removeAttribute('aria-busy'); }
    catch { fail(); }
  }
  function voiceSheet() {
    stopReferencePreview();
    settingsSheet('朗読の音声', body => {
      body.append(node('h3', 'voice-category', 'ローカル音声'));
      cache.catalog.forEach(voice => body.append(choice(voice.name, voice.available ? '' : 'この端末では利用できません', cache.mode.mode === 'browser' && cache.mode.browser_voice_name === voice.id,
        async () => {
          cache.mode = await api('/api/settings/browser-voice', { method: 'PUT', body: JSON.stringify({ name: voice.id, label: 'ブラウザー' }) });
          await loadVoices(); modal.close(); await showPage('settings', { push: false }); notify(voice.name + 'に変更しました。');
        }, voice.available)));
      body.append(node('h3', 'voice-category', '参照音声'));
      cache.voices.forEach(voice => body.append(choice(voice.name, '', cache.mode.mode === 'voice' && Number(cache.mode.voice_id) === Number(voice.id), async () => {
        cache.mode = await api('/api/settings/active-voice', { method: 'PUT', body: JSON.stringify({ voice_id: voice.id, browser: false, disabled: false }) });
        await loadVoices(); modal.close(); await showPage('settings', { push: false }); notify(voice.name + 'に変更しました。');
      })));
    }, 'ニュース・読書・辞書の読み上げに使用します。');
  }
  function dailyCountSheet() {
    const required = cache.sources.reduce((sum, source) => sum + source.minimum_count, 0);
    settingsSheet('日刊の記事数', body => {
      const form = node('form', 'sheet-form'); form.noValidate = true;
      const label = node('label', '', '一日に読む記事数');
      const input = node('input', 'field'); input.type = 'number'; input.min = Math.max(1, required); input.max = 500; input.required = true; input.value = cache.dailyConfig.target_count; label.append(input);
      const validate = () => input.setCustomValidity(Number.isInteger(input.valueAsNumber) && input.valueAsNumber < required ? `最低合計の${required}篇以上にしてください。` : '');
      input.addEventListener('input', validate); validate();
      const feedback = node('p', 'source-feedback'); feedback.hidden = true; feedback.setAttribute('role', 'alert');
      const save = node('button', 'primary', '保存'); save.type = 'submit'; form.append(label, feedback, save);
      form.onsubmit = async event => {
        event.preventDefault(); validate(); if (!form.reportValidity()) return;
        save.disabled = true; feedback.hidden = true;
        try {
          cache.dailyConfig = await api('/api/settings/daily-content', { method: 'PUT', body: JSON.stringify({ target_count: input.valueAsNumber }) });
          if (!modal.open || q('.sheet-form') !== form) return;
          modal.close(); await showPage('settings', { push: false });
        } catch (error) { feedback.textContent = error.message; feedback.hidden = false; save.disabled = false; }
      };
      body.append(form);
    }, `各ソースの最低合計：${required} 篇`);
  }
  function sourcesSheet() {
    settingsSheet('ニュースソース', body => {
      const form = node('form', 'source-form'); form.noValidate = true;
      const inputs = new Map();
      const steppers = new Map();
      const target = cache.dailyConfig.target_count;
      const total = node('p', 'source-total');
      const feedback = node('p', 'source-feedback'); feedback.hidden = true; feedback.setAttribute('role', 'alert');
      const save = node('button', 'primary', '保存'); save.type = 'submit';
      let busy = false;
      const updateTotal = () => {
        const values = [...inputs.values()].map(input => input.valueAsNumber);
        const valid = values.every(value => Number.isInteger(value) && value >= 0 && value <= 100);
        const sum = valid ? values.reduce((sum, value) => sum + value, 0) : NaN;
        const over = valid && sum > target;
        total.textContent = `最低合計 ${valid ? sum : '—'} / ${target} 篇`;
        total.classList.toggle('is-error', over);
        feedback.textContent = over ? `最低記事数の合計は、記事数（${target}篇）以内にしてください。` : '';
        feedback.hidden = !over;
        save.disabled = busy || over;
        for (const [id, input] of inputs) {
          const others = [...inputs].filter(([otherId]) => otherId !== id).map(([, other]) => other.valueAsNumber);
          const otherSum = others.every(value => Number.isInteger(value) && value >= 0 && value <= 100) ? others.reduce((sum, value) => sum + value, 0) : NaN;
          const maximum = Number.isFinite(otherSum) ? Math.max(0, Math.min(100, target - otherSum)) : 100;
          input.max = maximum;
          input.setCustomValidity(Number.isFinite(input.valueAsNumber) && input.valueAsNumber > maximum ? `他のソースと合わせて${target}篇以内にしてください。` : '');
          const { minus, plus } = steppers.get(id);
          input.disabled = busy;
          minus.disabled = busy || !Number.isInteger(input.valueAsNumber) || input.valueAsNumber <= 0;
          plus.disabled = busy || !valid || sum >= target || input.valueAsNumber >= maximum;
        }
      };
      cache.sources.forEach(source => {
        const row = node('div', 'source-row source-editor-row');
        const identity = node('div', 'source-identity');
        const name = node('label', '', source.name);
        const address = node('a', 'source-homepage', source.homepage);
        try {
          const url = new URL(source.homepage);
          if (['http:', 'https:'].includes(url.protocol)) {
            address.href = url.href; address.target = '_blank'; address.rel = 'noopener noreferrer';
            address.setAttribute('aria-label', source.name + 'のサイトを開く');
          }
        } catch { /* Keep an invalid address visible as text. */ }
        identity.append(name, address);
        const input = node('input'); input.type = 'number'; input.inputMode = 'numeric'; input.min = 0; input.max = 100; input.step = 1; input.required = true;
        input.value = source.minimum_count; input.id = 'source-minimum-' + source.id; input.setAttribute('aria-label', source.name + 'の最低記事数');
        name.htmlFor = input.id; inputs.set(source.id, input);
        const stepper = node('div', 'source-stepper');
        const minus = iconButton('minus', source.name + 'を1篇減らす', () => step(-1));
        const plus = iconButton('plus', source.name + 'を1篇増やす', () => step(1));
        function step(amount) {
          if (!Number.isInteger(input.valueAsNumber)) { input.reportValidity(); return; }
          input.value = Math.max(0, input.valueAsNumber + amount); updateTotal();
        }
        steppers.set(source.id, { minus, plus });
        input.addEventListener('input', updateTotal);
        stepper.append(minus, input, plus); row.append(identity, stepper); form.append(row);
      });
      const footer = node('div', 'source-form-footer');
      footer.append(total, feedback, save); form.append(footer); updateTotal();
      form.onsubmit = async event => {
        event.preventDefault();
        updateTotal();
        if (!form.reportValidity()) return;
        const changes = cache.sources.map(source => ({ id: source.id, old: source.minimum_count, next: inputs.get(source.id).valueAsNumber }))
          .filter(source => source.old !== source.next).sort((a, b) => (a.next - a.old) - (b.next - b.old));
        busy = true; updateTotal();
        try {
          for (const change of changes) {
            const updated = await api('/api/settings/news-sources/' + change.id, { method: 'PUT', body: JSON.stringify({ minimum_count: change.next }) });
            Object.assign(cache.sources.find(source => source.id === change.id), updated);
          }
          if (!modal.open || q('.source-form') !== form) return;
          modal.close(); await showPage('settings', { push: false });
        } catch (error) {
          if (!modal.open || q('.source-form') !== form) return;
          busy = false; updateTotal(); feedback.textContent = error.message; feedback.hidden = false;
        }
      };
      body.append(form);
    }, '各ソースから収録する、一日あたりの最低記事数。');
  }
  function scheduleSheet() {
    settingsSheet('日刊の更新', body => {
      const form = node('form', 'sheet-form'); const options = node('div', 'sheet-options'); let mode = cache.schedule.mode;
      const automatic = button('自動更新', () => { mode = 'automatic'; sync(); }); const manual = button('手動', () => { mode = 'manual'; sync(); });
      options.append(automatic, manual); const label = node('label', '', '更新時刻（CST・UTC+8）'); const input = node('input', 'field'); input.type = 'time'; input.value = cache.schedule.time || '00:00'; label.append(input);
      function sync() { automatic.setAttribute('aria-pressed', String(mode === 'automatic')); manual.setAttribute('aria-pressed', String(mode === 'manual')); label.hidden = mode !== 'automatic'; }
      sync(); const save = node('button', 'primary', '保存'); save.type = 'submit'; form.append(options, label, save);
      form.onsubmit = async event => { event.preventDefault(); save.disabled = true; try { cache.schedule = await api('/api/settings/daily-schedule', { method: 'PUT', body: JSON.stringify({ mode, time: input.value || '00:00' }) }); modal.close(); await showPage('settings', { push: false }); } catch (error) { notify(error.message, true); save.disabled = false; } }; body.append(form);
    }, '自動更新では、指定した時刻に日刊を作成します。設定はプレビュー内に保存されます。');
  }
  function sortSheet() {
    settingsSheet('書架の並び順', body => {
      for (const [value, label] of [['recent', '最近読んだ順'], ['series', 'シリーズ順'], ['imported', '追加した順']]) body.append(choice(label, '', cache.library.sort === value, async () => {
        cache.library = await api('/api/settings/library', { method: 'PUT', body: JSON.stringify({ ...cache.library, sort: value }) }); await loadLibrarySettings(); modal.close(); await showPage('settings', { push: false });
      }));
    });
  }
  function deviceStatus(status) {
    if (status.status === 'error') return '接続を確認してください';
    if (status.enabled !== true) return '同期は未設定です';
    const count = Array.isArray(status.paired_devices) ? status.paired_devices.length : 0;
    return count ? `${count} 台とペアリング済み` : 'ペアリング待ち';
  }
  async function deviceSheet() {
    let status;
    try { status = await api('/api/settings/device-sync'); }
    catch { status = { status: 'error' }; }
    renderDeviceSheet(status);
  }
  function renderDeviceSheet(status) {
    cache.sync = status;
    const summary = q('.settings-page .sync-entry-copy small');
    if (summary) summary.textContent = deviceStatus(status);
    const body = settingsSheet('文庫互联', body => {
      body.classList.add('sync-sheet');
      const enabled = status.enabled === true && status.status !== 'error';
      const pairingReady = enabled && /^\d{6}$/.test(status.pairing_code) && Boolean(status.url);
      const state = node('div', 'sync-status');
      state.dataset.state = status.status || 'disabled';
      state.append(node('span', 'sync-status-dot'), node('span', '', deviceStatus(status)));
      body.append(state, node('p', 'sync-intro', 'パソコンとスマートフォンに、同じ文庫を。'));

      const pairing = node('section', 'sync-pairing'); pairing.setAttribute('aria-label', 'ペアリング情報');
      const qr = node('div', 'sync-qr');
      const fallback = node('span', 'sync-qr-placeholder'); fallback.append(icon('scan'));
      fallback.append(node('small', '', pairingReady ? 'QRコードを読み込み中' : 'QRコード'));
      qr.append(fallback);
      if (pairingReady) {
        const image = node('img'); image.alt = 'Androidで読み取るペアリング用QRコード';
        image.onload = () => { fallback.hidden = true; };
        image.onerror = () => { image.remove(); fallback.querySelector('small').textContent = '読み込めませんでした'; };
        image.src = '/api/settings/device-sync/qr'; qr.append(image);
      }
      const instructions = node('div', 'sync-pairing-copy');
      instructions.append(node('h3', '', 'Androidでスキャン'));
      instructions.append(node('p', '', pairingReady ? '同じネットワークに接続し、Androidの設定から読み取ります。' : '正式アプリで同期を有効にすると、接続情報が表示されます。'));
      const code = node('div', 'sync-code'); code.setAttribute('aria-label', pairingReady ? '6桁のペアリングコード ' + status.pairing_code : 'ペアリングコード未発行');
      for (const digit of pairingReady ? status.pairing_code : '------') code.append(node('span', '', digit));
      instructions.append(node('span', 'sync-code-label', 'ペアリングコード'), code);
      pairing.append(qr, instructions); body.append(pairing);

      const address = node('div', 'sync-address');
      const addressCopy = node('div');
      addressCopy.append(node('span', '', '接続先'), node('strong', '', pairingReady ? status.url : 'まだ発行されていません'));
      address.append(addressCopy);
      const feedback = node('p', 'sync-copy-feedback'); feedback.hidden = true; feedback.setAttribute('role', 'status');
      if (pairingReady) address.append(iconButton('copy', '接続先をコピー', async () => {
        try { await navigator.clipboard.writeText(status.url); feedback.textContent = '接続先をコピーしました。'; }
        catch { feedback.textContent = 'コピーできませんでした。接続先を選択してコピーしてください。'; }
        feedback.hidden = false;
      }));
      body.append(address, feedback);
      if (enabled && !pairingReady || status.status === 'error') body.append(node('p', 'sync-error', '接続情報を取得できません。正式アプリの接続状態を確認してください。'));

      const peers = Array.isArray(status.paired_devices) ? status.paired_devices : [];
      const peerHeading = node('div', 'sync-section-title');
      peerHeading.append(node('h3', '', 'ペアリング済みの端末'), node('span', '', `${peers.length} 台`));
      body.append(peerHeading);
      if (peers.length) {
        const list = node('ul', 'sync-peers');
        for (const peer of peers) {
          const item = node('li'); item.append(icon('phone'), node('span', '', peer.name || 'Android'), node('small', '', 'ペアリング済み')); list.append(item);
        }
        body.append(list);
      } else {
        const empty = node('div', 'sync-empty');
        empty.append(icon('phone'), node('span', '', '接続した端末がここに表示されます。')); body.append(empty);
      }
      const scope = node('section', 'sync-scope'); scope.append(node('h3', '', '同期できるもの'));
      const items = node('div', 'sync-scope-items');
      for (const [glyph, text] of [['news', '記事・お気に入り'], ['book', '電子書籍'], ['paste', '保存した本文'], ['speaker', '参照音声']]) {
        const item = node('span'); item.append(icon(glyph), node('span', '', text)); items.append(item);
      }
      scope.append(items); body.append(scope);
      body.append(node('p', 'sync-footnote', '同期はAndroid側から実行します。各端末の読書位置はそのまま保たれます。'));
    });
    const refresh = async () => {
      if (!modal.open || q('.sync-sheet') !== body) return;
      let updated;
      try { updated = await api('/api/settings/device-sync'); }
      catch { updated = { status: 'error' }; }
      if (!modal.open || q('.sync-sheet') !== body) return;
      if (JSON.stringify(updated) !== JSON.stringify(status)) { renderDeviceSheet(updated); return; }
      syncRefreshTimer = setTimeout(refresh, 3000);
    };
    syncRefreshTimer = setTimeout(refresh, 3000);
  }
  function maintenanceSheet() {
    settingsSheet('文庫の点検', body => {
      body.append(node('p', 'settings-info', '記事と書籍のファイルを確認し、文庫の索引を整理します。'));
      body.append(node('p', 'settings-info', '実行する場合は、正式アプリの設定から「文庫刷新」を開いてください。'), button('閉じる', () => modal.close(), 'primary'));
    });
  }
  function prepareArticleHeading() {
    const article = document.querySelector('#reader-result .article-detail');
    if (!article || article.dataset.previewHeading === 'ready') return;
    article.dataset.previewHeading = 'ready';
    const origin = article.querySelector('.origin');
    if (origin.hidden) origin.before(article.querySelector('.source'));
    const title = article.querySelector('.title');
    const titleText = title.textContent;
    const titleContent = document.createDocumentFragment();
    const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('ja', { granularity: 'word' }) : null;
    const appendTitleText = value => {
      if (!segmenter) { titleContent.append(document.createTextNode(value)); return; }
      for (const part of segmenter.segment(value)) {
        titleContent.append(part.isWordLike && part.segment.length > 1 && part.segment.length <= 10 ? node('span', 'title-unit', part.segment) : document.createTextNode(part.segment));
      }
    };
    let offset = 0;
    for (const match of titleText.matchAll(/\d+(?:[,.]\d+)*(?:兆|億|万)?(?:人|歳|年|月|日|時|分|秒|件|社|円|%|％)/g)) {
      appendTitleText(titleText.slice(offset, match.index)); titleContent.append(node('span', 'title-unit', match[0]));
      offset = match.index + match[0].length;
    }
    appendTitleText(titleText.slice(offset)); title.replaceChildren(titleContent);
    const reread = article.querySelector('.reread-panel');
    const rereadLink = article.querySelector('.reread-link');
    article.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || event.defaultPrevented || reread.hidden) return;
      event.preventDefault(); reread.hidden = true; rereadLink.setAttribute('aria-expanded', 'false'); rereadLink.focus();
    });
  }
  async function enterArticle(article) {
    stopDictionarySpeech();
    const returnTo = ui.view;
    const payload = await api(`${article.bookmark_context ? '/api/bookmarks/' : '/api/articles/'}${article.id}`);
    await openArticleInReader(payload);
    prepareArticleHeading();
    readingBar.querySelector('span').textContent = { daily: '日刊', reader: '閲読室', bookmarks: '收藏' }[returnTo] || '日刊';
    ui.returnView = returnTo; ui.reading = 'article'; host.setAttribute('reading', 'article'); document.documentElement.dataset.nativeReading = 'article';
    window.scrollTo({ top: 0, behavior: 'auto' });
    updateInspect();
  }
  function updateBookScrollRail() {
    if (document.documentElement.dataset.nativeReading !== 'book') return;
    const reader = document.querySelector('#book-reader');
    const rail = reader.querySelector('.epub-scroll-rail');
    if (!rail) return;
    const vertical = reader.classList.contains('is-vertical');
    const scroll = vertical ? reader.querySelector('.book-chapter-body') : document.scrollingElement;
    const extent = vertical ? scroll.scrollWidth - scroll.clientWidth : scroll.scrollHeight - scroll.clientHeight;
    if (rail.hidden !== (extent <= 0)) rail.hidden = extent <= 0;
    const offset = vertical ? Math.abs(scroll.scrollLeft) : scroll.scrollTop;
    const position = extent > 0 ? Math.min(1000, Math.round(1000 * offset / extent)) : 0;
    const control = rail.querySelector('input');
    control.value = position;
    control.setAttribute('aria-valuetext', `${position / 10}%`);
    rail.style.setProperty('--epub-scroll-progress', `${position / 10}%`);
  }
  const bookRailResize = new ResizeObserver(updateBookScrollRail);
  window.addEventListener('scroll', updateBookScrollRail, { passive: true });
  window.addEventListener('resize', updateBookScrollRail, { passive: true });
  function prepareBookReader() {
    const reader = document.querySelector('#book-reader');
    const chrome = reader?.querySelector('.book-reader-chrome');
    if (!chrome || chrome.dataset.previewBook === 'ready') return;
    chrome.dataset.previewBook = 'ready';
    const back = chrome.querySelector('.back-to-library');
    const title = chrome.querySelector('.book-reader-title');
    const contents = chrome.querySelector('.toggle-book-toc');
    const settings = chrome.querySelector('.toggle-book-settings');
    const picker = chrome.querySelector('.book-reader-chapter-picker');
    const select = picker.querySelector('select');
    const chapter = reader.querySelector('.book-chapter');
    chapter.querySelector(':scope > h1').remove();

    back.replaceChildren(icon('back'));
    contents.replaceChildren(icon('book'));
    settings.replaceChildren(icon('settings'));
    chrome.prepend(back);
    const titleDetail = title.querySelector(':scope > div');
    titleDetail.querySelector(':scope > span').hidden = true;
    picker.hidden = true;

    const toc = reader.querySelector('.book-toc');
    const tocHeading = toc.querySelector('strong');
    tocHeading.id = toc.id + '-heading';
    toc.setAttribute('aria-labelledby', tocHeading.id);
    const entries = new Set([...toc.querySelectorAll('[data-chapter-id]')].map(entry => entry.dataset.chapterId));
    const missing = [...select.options].filter(option => !entries.has(option.value));
    for (const option of missing) {
      const entry = button(option.textContent, () => {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      });
      entry.dataset.chapterId = option.value;
      if (option.selected) { entry.classList.add('active'); entry.setAttribute('aria-current', 'location'); }
      toc.append(entry);
    }
    const frontEntry = toc.querySelector('[data-chapter-id]');
    if (frontEntry && /^Chapter\s*\d+$/i.test(frontEntry.textContent.trim())) frontEntry.textContent = '表紙・巻頭';
    const tocClose = toc.querySelector(':scope > div button');
    tocClose.replaceChildren(icon('close'));
    contents.addEventListener('click', () => requestAnimationFrame(() => {
      if (toc.hidden) return;
      const active = toc.querySelector('[aria-current]') || tocClose;
      active.focus({ preventScroll: true });
      if (active !== tocClose) active.scrollIntoView({ block: 'nearest' });
    }));

    const settingsPanel = reader.querySelector('.book-settings-panel');
    settingsPanel.querySelector('.section-kicker')?.remove();
    settingsPanel.querySelector('.book-settings-checkbox')?.closest('.book-settings-section').remove();
    settingsPanel.querySelector('.close-book-settings').replaceChildren(icon('close'));
    settingsPanel.querySelector('[data-language-mode="click"]').textContent = 'タップで表示';
    settingsPanel.querySelector('.book-voice option[value="model"]').textContent = '既定の音声';

    for (const original of chapter.querySelectorAll('.book-block-ja')) original.lang = 'ja';
    for (const translation of chapter.querySelectorAll('.book-block-zh')) {
      translation.lang = 'zh-CN';
      const prompt = translation.querySelector('.translation-placeholder');
      if (prompt) { prompt.lang = 'ja'; prompt.textContent = '訳文を表示'; }
    }
    for (const bookmark of chapter.querySelectorAll('.book-block-bookmark')) {
      const original = bookmark.parentElement.querySelector('.book-block-ja');
      original.append(bookmark);
      bookmark.addEventListener('keydown', event => {
        // Let the button activate without also seeking to the parent paragraph.
        if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
      });
    }
    const openingArt = chapter.querySelector('.book-chapter-body > .book-block-image:first-child img');
    if (openingArt) openingArt.loading = 'eager';

    const body = chapter.querySelector('.book-chapter-body');
    const rail = node('div', 'epub-scroll-rail');
    const control = node('input');
    control.type = 'range';
    control.min = '0';
    control.max = '1000';
    control.setAttribute('aria-label', '章のスクロール位置');
    control.addEventListener('input', () => {
      const fraction = control.valueAsNumber / 1000;
      if (reader.classList.contains('is-vertical')) {
        body.scrollLeft = -fraction * (body.scrollWidth - body.clientWidth);
      } else {
        const scroll = document.scrollingElement;
        scroll.scrollTop = fraction * (scroll.scrollHeight - scroll.clientHeight);
      }
    });
    rail.append(control);
    reader.append(rail);
    body.addEventListener('scroll', updateBookScrollRail, { passive: true });
    bookRailResize.disconnect();
    bookRailResize.observe(body);
    updateBookScrollRail();
  }
  async function enterBook(book) {
    stopDictionarySpeech();
    await showView('library');
    // The native progress restore must measure the redesigned page from its first frame.
    document.documentElement.dataset.nativeReading = 'book';
    try {
      await openBook(book.id);
      if (document.querySelector('#book-reader').hidden) return;
      prepareBookReader();
      ui.returnView = 'library'; ui.reading = 'book'; host.setAttribute('reading', 'book'); updateInspect();
    } finally {
      if (ui.reading !== 'book') delete document.documentElement.dataset.nativeReading;
    }
  }
  async function leaveReading() {
    stopArticlePlayback(); ui.reading = ''; host.removeAttribute('reading'); delete document.documentElement.dataset.nativeReading;
    await showPage(ui.returnView || 'daily'); window.scrollTo({ top: 0, behavior: 'auto' });
  }
  async function showPage(view, { push = true } = {}) {
    if (!ui.loaded) return;
    if (!['daily', 'reader', 'library', 'dictionary', 'settings', 'bookmarks'].includes(view)) view = 'daily';
    if (!ui.reading) positions.set(ui.view, main.scrollTop);
    stopReferencePreview(); stopDictionarySpeech(); if (ui.reading) stopArticlePlayback();
    ui.reading = ''; host.removeAttribute('reading'); delete document.documentElement.dataset.nativeReading;
    nativeDictionary.hidden = view !== 'dictionary';
    ui.view = view; const request = ++ui.request;
    main.classList.toggle('native-dictionary-main', view === 'dictionary');
    const navigationView = view === 'bookmarks' ? 'settings' : view;
    nav.querySelectorAll('button').forEach(item => { if (item.dataset.view === navigationView) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); });
    if (push && location.hash !== '#preview/' + view) history.pushState({ redesignView: view }, '', '#preview/' + view);
    const page = node('div', 'page ' + view + '-page'); page.append(node('p', 'loading', '文庫をひらいています。')); main.replaceChildren(page);
    try {
      const content = node('div', 'page ' + view + '-page');
      await { daily: dailyPage, reader: readerPage, library: libraryPage, dictionary: dictionaryPage, settings: settingsPage, bookmarks: bookmarksPage }[view](content);
      if (request !== ui.request) return; main.replaceChildren(content);
      requestAnimationFrame(() => { main.scrollTop = positions.get(view) || 0; main.focus({ preventScroll: true }); updateInspect(); });
    } catch (error) { if (request === ui.request) page.replaceChildren(heading('文庫に接続できません。'), node('p', 'error-note', error.message), button('重新读取', () => showPage(view, { push: false }), 'primary')); }
  }
  function updateInspect() {
    window.__newPreview = { version: 2, view: ui.view, reading: ui.reading, ready: ui.loaded, live: true,
      counts: { articles: cache.daily?.articles?.length || 0, books: cache.books.length, dictionary: cache.stats.entries, localVoices: cache.catalog.length, references: cache.voices.length } };
  }
  new MutationObserver(() => {
    prepareArticleHeading();
    if (document.documentElement.dataset.nativeReading === 'book') prepareBookReader();
    if (ui.reading === 'book' && document.querySelector('#book-reader')?.hidden) leaveReading();
    if (ui.reading === 'article' && !document.querySelector('#reader-result .article-detail')) leaveReading();
  }).observe(document.querySelector('.content-shell'), { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  window.addEventListener('popstate', () => { const match = location.hash.match(/^#preview\/([^/]+)/); if (match && ui.loaded) showPage(match[1], { push: false }); });
  window.addEventListener('pagehide', () => { stopReferencePreview(); stopDictionarySpeech(); });
  window.__redesignRoot = root;
  window.__redesignNavigate = view => showPage(view);
  async function boot() {
    main.append(node('p', 'loading', '文庫をひらいています。'));
    try {
      [cache.days, cache.mode, cache.voices, cache.catalog, cache.library, cache.stats, cache.dailyConfig, cache.schedule, cache.sources] = await Promise.all([
        api('/api/days'), api('/api/settings/voice-mode'), api('/api/settings/voices'), api('/api/browser-voices'), api('/api/settings/library'), api('/api/dictionary/stats'),
        api('/api/settings/daily-content'), api('/api/settings/daily-schedule'), api('/api/settings/news-sources')]);
      cache.books = (await api('/api/books')).books;
      if (cache.days.length) cache.daily = await api('/api/daily?date=' + encodeURIComponent(cache.days[0]));
      ui.loaded = true; await showPage(location.hash.match(/^#preview\/([^/]+)/)?.[1] || 'daily', { push: false });
    } catch (error) { main.replaceChildren(node('div', 'empty', '真实文库未能加载：' + error.message)); }
  }
  boot();
})();
