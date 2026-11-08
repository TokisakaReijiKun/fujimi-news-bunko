/* Isolated interaction demo: sample content + namespaced browser state only. */
(() => {
  'use strict';
  const STORAGE_KEY = 'fujimi-mobile-design-demo-v1';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function icon(name) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    node.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(node.namespaceURI, 'use');
    use.setAttribute('href', '#i-' + name);
    node.append(use);
    return node;
  }
  function button(text, action, className = 'secondary') {
    const node = el('button', className, text);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  const defaults = { saved: ['bookshop'], custom: [], translation: 'parallel', rate: 1, sort: 'recent', progress: {}, date: '2026-11-01' };
  let stored = {};
  let storageAvailable = true;
  try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch { storageAvailable = false; }
  const state = { ...JSON.parse(JSON.stringify(defaults)), ...stored };
  if (!Array.isArray(state.saved)) state.saved = [...defaults.saved];
  if (!Array.isArray(state.custom)) state.custom = [];
  if (!state.progress || typeof state.progress !== 'object') state.progress = {};
  let content, manifest, main, phone, modal, drawer, more, activePath = '', articleReturn = 'daily';
  let media = null;
  let wordAudio = null;
  let toastTimer;
  let drawerFocus;
  const positions = new Map();
  const mediaPositions = new Map();
  const names = { daily: '本日ノニュース', reader: '閲読室', bookmarks: '收藏', library: '書架', dictionary: '辞書', settings: '設置' };
  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch { storageAvailable = false; }
  }
  function toast(message) {
    const notice = $('#demo-toast');
    notice.textContent = message;
    notice.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { notice.hidden = true; }, 3500);
  }
  function articles() { return [...content.articles, ...state.custom]; }
  function articleById(id) { return articles().find(item => item.id === id); }
  function clone(name) { return $('template#' + name).content.cloneNode(true); }
  function navigate(path) {
    if (location.hash === '#' + path) render();
    else location.hash = path;
  }
  function showDrawer(open) {
    if (open) drawerFocus = document.activeElement;
    drawer.hidden = !open;
    $('#scrim').hidden = !open;
    more.setAttribute('aria-expanded', String(open));
    main.inert = open;
    $('#navigation').inert = open;
    $('#appbar').inert = open;
    if (open) $('#close-drawer').focus({ preventScroll: true });
    else if (drawerFocus?.isConnected) drawerFocus.focus({ preventScroll: true });
  }
  function openModal(title, build) {
    stopWordAudio();
    const section = el('div', 'demo-sheet-content');
    const close = button('', () => modal.close(), 'icon-button dialog-close');
    close.setAttribute('aria-label', '关闭'); close.append(icon('close'));
    section.append(close, el('h2', '', title));
    build(section);
    modal.replaceChildren(section);
    if (!modal.open) modal.showModal();
  }
  function explain(title, copy) {
    openModal(title, root => {
      root.append(el('p', '', copy), button('返回 Demo', () => modal.close(), 'primary'));
    });
  }
  function setText(selector, value, root = main) { const target = $(selector, root); if (target) target.textContent = value; }
  function meta(article) {
    const node = el('div', 'article-meta');
    node.append(el('span', '', article.source), el('time', '', article.time));
    return node;
  }
  function newsRow(article, saved = false) {
    const link = el('a', saved ? 'saved-article' : 'news-row');
    link.href = '#article/' + article.id;
    if (saved) {
      link.append(meta(article), el('h2', '', article.title), el('p', '', article.summary || article.titleZh || '自分のことばを読む。'));
      const foot = el('div', 'article-foot');
      foot.append(el('span', '', article.category), icon('bookmark'));
      link.append(foot);
    } else {
      const copy = el('div');
      copy.append(meta(article), el('h3', '', article.title), el('p', '', article.category));
      link.append(copy);
      const art = el('div', 'mini-art ' + (article.art || 'books-art'));
      if (article.art === 'rail-art') art.append(el('span', '', '駅'));
      else for (let i = 0; i < 4; i++) art.append(el('i'));
      link.append(art);
    }
    return link;
  }
  function daily() {
    main.append(clone('daily'));
    const dates = {
      '2026-11-01': ['令和八年 十一月一日', '日曜日', ['kyoto', 'bookshop', 'railway']],
      '2026-10-31': ['令和八年 十月三十一日', '土曜日', ['bookshop', 'morning', 'kyoto']],
      '2026-10-30': ['令和八年 十月三十日', '金曜日', ['railway', 'rain', 'bookshop']]
    };
    const selected = dates[state.date] || dates['2026-11-01'];
    const list = selected[2].map(articleById);
    const lead = list[0];
    setText('.edition span:first-child', selected[0]); setText('.edition span:last-child', selected[1]);
    const dateLabel = $('.daily-date>b');
    const [, month, day] = state.date.split('-');
    dateLabel.replaceChildren(document.createTextNode(String(Number(month))), el('span', '', '月'), document.createTextNode(day), el('span', '', '日'));
    const leadLink = $('.lead'); leadLink.href = '#article/' + lead.id;
    setText('.lead h2', lead.title); setText('.lead>p', lead.summary);
    $('.lead .article-meta').replaceWith(meta(lead));
    setText('.lead .article-foot>span:first-child', lead.category);
    setText('.lead .article-foot>span:last-child', '全文を読む');
    setText('.section-label>span', `${list.length} 篇 · 示例日刊`);
    $$('.news-row', main).forEach(item => item.remove());
    const note = $('.end-note');
    list.slice(1).forEach(article => note.before(newsRow(article)));
    note.textContent = 'Demo 示例文章 · 非真实新闻报道';
  }
  function bookmarks() {
    main.append(clone('bookmarks'));
    const saved = state.saved.map(articleById).filter(Boolean);
    $('.count-mark').replaceChildren(document.createTextNode(String(saved.length)), el('span', '', '篇'));
    $$('.saved-article', main).forEach(item => item.remove());
    const container = $('.bookmarks-page');
    saved.forEach(article => container.append(newsRow(article, true)));
    if (!saved.length) {
      const empty = el('div', 'demo-empty');
      empty.append(icon('bookmark'), el('h2', '', '最初の一篇を、ここに。'), el('p', '', '打开一篇文章，点右上角书签，就能在这里再次找到它。'), button('去读日刊', () => navigate('daily'), 'primary'));
      container.append(empty);
    }
  }
  function reader() {
    main.append(clone('reader'));
    const input = $('#article-link');
    input.value = 'https://demo.fujimi.local/kyoto';
    input.setAttribute('aria-label', '演示文章链接');
    $('.import-panel>p').textContent = '先用示例链接，试试导入后的阅读流程。';
    const rows = $$('.example-row');
    rows[0].href = '#article/morning'; rows[1].href = '#article/rain';
  }
  function cover(book) {
    const node = el('div', 'book-cover ' + book.cover);
    node.append(el('span', '', book.author), el('b', '', book.title), el('i', '', '文庫'));
    return node;
  }
  function library() {
    main.append(clone('library'));
    const books = [...content.books];
    if (state.sort === 'title') books.sort((a, b) => a.title.localeCompare(b.title, 'ja'));
    const last = Object.keys(state.progress).sort((a, b) => state.progress[b].last - state.progress[a].last)[0];
    const book = content.books.find(item => item.id === last) || books[0];
    const progress = state.progress[book.id] || { chapter: 0, fraction: 0 };
    const chapter = book.chapters[progress.chapter] || book.chapters[0];
    const link = $('.continue-book');
    link.href = `#book/${book.id}/${progress.chapter || 0}`;
    link.querySelector('.book-cover').replaceWith(cover(book));
    setText('.continue-copy h2', book.title); setText('.continue-copy p', book.author);
    setText('.continue-copy>small', chapter.title);
    $('.read-progress>i').style.width = `${Math.max(3, (progress.fraction || 0) * 100)}%`;
    setText('.section-label>span', `${books.length} 冊`);
    const grid = $('.book-grid'); grid.replaceChildren();
    for (const item of books) {
      if (item.id === book.id) continue;
      const card = el('a', 'book-item');
      card.href = '#book/' + item.id + '/0';
      card.append(cover(item), el('h3', '', item.title), el('p', '', item.author));
      grid.append(card);
    }
    setText('.end-note', '内置示例书架 · 封面为原创排版');
  }
  function settings() {
    main.append(clone('settings'));
    setText('.voice-summary h2', manifest.voice.name);
    setText('.voice-summary p', 'Demo 实际播放的本地日语声线');
    setText('.end-note', '这里的选择仅作用于 Demo。');
    const row = $('.setting-row');
    row.replaceChildren(el('span', '', '示例日刊文章数'), el('b', '', '3 篇'));
    const select = $('#sort');
    select.replaceChildren(new Option('最近読んだ順', 'recent'), new Option('タイトル順', 'title'));
    select.value = state.sort;
    select.addEventListener('change', () => {
      state.sort = select.value; persist();
      select.closest('details').querySelector('summary>span:last-child').firstChild.textContent = select.selectedOptions[0].textContent;
      toast('Demo 书架排序已更新');
    });
    const sortValue = $('summary>span:last-child', select.closest('details'));
    sortValue.firstChild.textContent = select.selectedOptions[0].textContent;
    $('details>p', select.closest('details')).textContent = '回到書架，可以查看新的排列。';
    const details = $$('.setting-section details');
    const source = details[0];
    source.querySelector('p').textContent += '。当前 Demo 使用 3 篇合成文章。';
    setText('.refresh-section h2', 'Demo 数据');
    const reset = $('.refresh-button'); reset.dataset.dialog = 'reset';
    reset.childNodes.forEach(node => { if (node.nodeType === Node.TEXT_NODE) node.textContent = '重置演示文库'; });
  }
  function dictionary() {
    main.append(clone('dictionary'));
    const form = $('#dictionary-form');
    const query = $('#dictionary-query');
    form.addEventListener('submit', event => { event.preventDefault(); lookup(query.value); });
    $('.dictionary-note').textContent = '6 个完整示例词条 · 支持日文 / 假名 / 罗马字 / 中文';
    lookup(query.value);
  }
  function lookup(query) {
    const normalized = query.trim().toLowerCase();
    const found = content.words.filter(word => [word.word, word.kana, word.romaji, word.meaning].some(value => value.toLowerCase().includes(normalized)));
    const old = $('.demo-word-results'); if (old) old.remove();
    const results = el('div', 'demo-word-results');
    found.forEach(word => results.append(button(word.word + '　' + word.kana, () => showWord(word), 'demo-word-result')));
    $('.result-summary').after(results);
    setText('.result-summary>span:last-child', `${found.length} 件`);
    if (found.length) showWord(found[0]);
    else {
      const detail = $('.word-detail'); detail.replaceChildren();
      detail.append(el('h2', '', 'まだ出会っていない言葉。'), el('p', 'demo-no-result', 'Demo 可查：木漏れ日、季節、栞、余白、秋、本。'));
    }
  }
  function showWord(word) {
    const template = clone('dictionary');
    const detail = $('.word-detail', template);
    $('.word-kana', detail).textContent = word.kana;
    $('.word-heading h2', detail).textContent = word.word;
    $('.part-of-speech', detail).textContent = word.pos;
    $('.definition>p', detail).textContent = word.meaning;
    $('.dictionary-example p[lang=ja]', detail).textContent = word.ja;
    $('.dictionary-example p[lang=zh]', detail).textContent = word.zh;
    $('.pronunciation', detail).removeAttribute('data-dialog');
    $('.pronunciation', detail).setAttribute('aria-label', '朗读' + word.word);
    $('.pronunciation', detail).addEventListener('click', () => playWord(word.id));
    $('.word-detail').replaceWith(detail);
  }
  function article(id) {
    const item = articleById(id);
    if (!item) return notFound();
    main.append(clone('article'));
    $('.reading-tools>a').href = '#' + articleReturn;
    setText('.reading-tools>span', names[articleReturn] || '閲読室');
    const root = $('.reading-content');
    root.querySelector('.article-meta').replaceWith(meta(item));
    setText('.reading-content h1', item.title);
    setText('.reading-subtitle', item.titleZh || '粘贴正文 · Demo 文库');
    setText('.reading-byline>span', item.category + ' · 示例文章');
    $('.reading-byline .text-button').textContent = '文章信息';
    const figure = $('figure'); figure.hidden = !item.image;
    $$('.paragraph', root).forEach(node => node.remove());
    const note = $('.end-note', root);
    item.paragraphs.forEach((part, index) => {
      const paragraph = el('div', 'paragraph'); paragraph.dataset.paragraph = index;
      paragraph.append(el('p', '')); paragraph.firstChild.lang = 'ja'; paragraph.firstChild.textContent = part.ja;
      if (part.zh) { const translated = el('p', 'translation', part.zh); translated.lang = 'zh'; paragraph.append(translated); }
      note.before(paragraph);
    });
    note.textContent = item.custom ? '你的粘贴正文 · 仅保存在 Demo 中' : 'Demo 合成文章 · 用于体验阅读与朗读';
    const saved = state.saved.includes(id);
    $('.bookmark-toggle').setAttribute('aria-pressed', String(saved));
    $('.bookmark-toggle').setAttribute('aria-label', saved ? '取消收藏文章' : '收藏文章');
    $('.bookmark-toggle').addEventListener('click', () => {
      const isSaved = state.saved.includes(id);
      state.saved = isSaved ? state.saved.filter(value => value !== id) : [id, ...state.saved];
      persist();
      $('.bookmark-toggle').setAttribute('aria-pressed', String(!isSaved));
      $('.bookmark-toggle').setAttribute('aria-label', isSaved ? '收藏文章' : '取消收藏文章');
      toast(isSaved ? '已从 Demo 收藏移除' : storageAvailable ? '已加入 Demo 收藏' : '已加入本次演示收藏，刷新后不保留');
    });
    $('.translation-toggle').addEventListener('click', () => {
      state.translation = state.translation === 'parallel' ? 'original' : 'parallel'; persist(); applyTranslation();
    });
    applyTranslation();
    installPlayer('article:' + item.id);
  }
  function applyTranslation() {
    const hidden = state.translation === 'original';
    $$('.translation,.reading-subtitle', main).forEach(node => { node.hidden = hidden; });
    $('.translation-toggle')?.setAttribute('aria-pressed', String(!hidden));
  }
  function book(id, chapterIndex) {
    const item = content.books.find(value => value.id === id);
    const chapter = item?.chapters[chapterIndex];
    if (!chapter) return notFound();
    main.append(clone('book'));
    setText('.reading-tools>span', item.title);
    const root = $('.book-prose'); root.replaceChildren();
    root.append(el('p', 'book-part', item.author + '　' + item.title), el('h1', '', chapter.title), el('span', 'chapter-number', String(chapterIndex + 1)));
    chapter.paragraphs.forEach((text, index) => { const part = el('p', 'demo-book-paragraph', text); part.dataset.paragraph = index; root.append(part); });
    const controls = el('div', 'demo-chapter-controls');
    const previous = button('前の章', () => navigate(`book/${id}/${chapterIndex - 1}`)); previous.disabled = chapterIndex === 0;
    const next = button('次の章', () => navigate(`book/${id}/${chapterIndex + 1}`)); next.disabled = chapterIndex === item.chapters.length - 1;
    controls.append(previous, next); root.append(controls);
    root.append(el('p', 'end-note', id === 'kokoro' ? '首章为公版节选 · 后章为原创交互示例' : '富士見文庫 · 原创演示短篇'));
    $('.book-bottom').remove();
    const player = $('.reading-player', clone('article'));
    $('.reading-page').append(player);
    const toc = $('.reading-tools>button'); toc.dataset.dialog = 'contents';
    const earlier = state.progress[id];
    state.progress[id] = { chapter: chapterIndex, fraction: earlier?.chapter === chapterIndex ? earlier.fraction || 0 : 0, last: Date.now() }; persist();
    root.addEventListener('scroll', () => {
      state.progress[id].fraction = Math.min(1, root.scrollTop / Math.max(1, root.scrollHeight - root.clientHeight));
      persist();
    }, { passive: true });
    installPlayer(`book:${id}:${chapterIndex}`);
  }
  function notFound() {
    const block = el('div', 'demo-empty');
    block.append(el('h1', '', '这一页还没有写下。'), button('返回日刊', () => navigate('daily'), 'primary'));
    main.append(block);
  }
  function formatTime(value) { return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`; }
  function stopWordAudio() { if (wordAudio) { wordAudio.pause(); wordAudio = null; } }
  function stopMedia() {
    if (media) {
      mediaPositions.set(media.key, { index: media.index, time: media.audio.currentTime || 0 });
      media.audio.pause(); media.audio.removeAttribute('src'); media.audio.load(); media = null;
    }
    stopWordAudio();
  }
  function elapsed(session) { return session.segments.slice(0, session.index).reduce((sum, part) => sum + part.duration, 0) + (session.audio.currentTime || 0); }
  function updatePlayer() {
    if (!media || !$('.reading-player')) return;
    const session = media;
    const time = elapsed(session);
    $('.player-top>span:last-child').textContent = `${formatTime(time)} / ${formatTime(session.total)}`;
    $('.demo-seek').value = String(time);
    $('.play-button use').setAttribute('href', session.audio.paused ? '#i-play' : '#i-pause');
    $('.play-button').setAttribute('aria-label', session.audio.paused ? '播放朗读' : '暂停朗读');
    $('.play-button').setAttribute('aria-pressed', String(!session.audio.paused));
    $('.demo-previous').disabled = session.index === 0 && time < .5;
    $('.demo-next').disabled = session.index >= session.segments.length - 1;
    $$('[data-paragraph]', main).forEach(node => node.classList.toggle('speaking-paragraph', Number(node.dataset.paragraph) === session.index && !session.audio.paused));
  }
  async function playCurrent() {
    if (!media) return toast('这篇自定义正文没有预制音频，可先体验内置文章的朗读。');
    const session = media;
    stopWordAudio();
    try { await session.audio.play(); if (media === session) updatePlayer(); }
    catch { if (media === session) toast('当前浏览器未能播放音频，请再次点播放或检查声音权限。'); }
  }
  function loadSegment(index, position = 0, play = false) {
    const session = media;
    if (!session || index < 0 || index >= session.segments.length) return;
    session.index = index;
    session.audio.src = session.segments[index].url;
    session.audio.playbackRate = state.rate;
    session.audio.addEventListener('loadedmetadata', () => {
      if (media === session && session.index === index) { session.audio.currentTime = Math.min(position, session.audio.duration || 0); updatePlayer(); }
    }, { once: true });
    session.audio.load();
    if (play) playCurrent();
    updatePlayer();
  }
  function installPlayer(key) {
    const root = $('.reading-player');
    const parts = manifest.groups[key] || [];
    root.dataset.audioKey = key;
    root.setAttribute('aria-label', '日语朗读播放器');
    $('.player-top>span:first-child').replaceChildren(icon('volume'), document.createTextNode(manifest.voice.name), el('span', 'muted', '· 朗読'));
    const progress = $('.player-progress');
    const range = el('input', 'demo-seek'); range.type = 'range'; range.min = 0; range.step = .1;
    range.max = String(parts.reduce((sum, part) => sum + part.duration, 0)); range.value = 0;
    range.setAttribute('aria-label', '朗读播放位置'); progress.replaceWith(range);
    $('.player-controls>div>button:first-child').classList.add('demo-previous');
    $('.player-controls>div>button:last-child').classList.add('demo-next');
    $('.play-button').removeAttribute('data-dialog');
    $('.demo-previous').removeAttribute('data-dialog'); $('.demo-next').removeAttribute('data-dialog');
    $('.player-controls>.text-button:first-child').removeAttribute('data-dialog');
    $('.rate-toggle').textContent = state.rate.toFixed(2).replace(/0$/, '') + '×';
    $('.rate-toggle').setAttribute('aria-label', '选择播放速度');
    $('.rate-toggle').addEventListener('click', rateSheet);
    const listening = $('.player-controls>.text-button:first-child'); listening.setAttribute('aria-pressed', 'false');
    listening.addEventListener('click', () => {
      const enabled = !phone.classList.contains('listen-mode');
      phone.classList.toggle('listen-mode', enabled); listening.setAttribute('aria-pressed', String(enabled));
      listening.textContent = enabled ? '退出听读' : '听读';
      toast(enabled ? '听读模式：收起配图，跟随当前段落' : '已返回普通阅读');
    });
    if (!parts.length) {
      $('.play-button').addEventListener('click', () => toast('这篇正文没有预制音频；请试试内置文章。'));
      $('.demo-previous').disabled = true; $('.demo-next').disabled = true; range.disabled = true;
      $('.player-top>span:last-child').textContent = '未生成音频';
      return;
    }
    const audio = new Audio(); audio.preload = 'metadata';
    media = { key, segments: parts, index: 0, total: parts.reduce((sum, part) => sum + part.duration, 0), audio };
    const session = media;
    for (const event of ['timeupdate', 'play', 'pause', 'loadedmetadata']) audio.addEventListener(event, () => { if (media === session) updatePlayer(); });
    audio.addEventListener('error', () => { if (media === session) { toast('示例音频读取失败，请刷新 Demo 后重试。'); updatePlayer(); } });
    audio.addEventListener('ended', () => {
      if (media !== session) return;
      if (session.index < parts.length - 1) loadSegment(session.index + 1, 0, true);
      else { updatePlayer(); toast('这一篇，听完了。'); }
    });
    const saved = mediaPositions.get(key); loadSegment(saved?.index || 0, saved?.time || 0);
    $('.play-button').addEventListener('click', () => {
      if (audio.paused) { if (audio.ended && session.index === parts.length - 1) loadSegment(0); playCurrent(); }
      else audio.pause();
    });
    $('.demo-previous').addEventListener('click', () => loadSegment(Math.max(0, session.index - 1), 0, !audio.paused));
    $('.demo-next').addEventListener('click', () => loadSegment(session.index + 1, 0, !audio.paused));
    range.addEventListener('input', () => {
      let remaining = Number(range.value); let index = 0;
      while (index < parts.length - 1 && remaining >= parts[index].duration) remaining -= parts[index++].duration;
      loadSegment(index, remaining, !audio.paused);
    });
  }
  function rateSheet() {
    openModal('朗読の速さ', root => {
      const list = el('div', 'demo-choices');
      for (const rate of [.75, 1, 1.25, 1.5, 2]) {
        const choice = button(rate + '×', () => {
          state.rate = rate; persist(); if (media) media.audio.playbackRate = rate;
          if ($('.rate-toggle')) $('.rate-toggle').textContent = rate + '×'; modal.close();
        });
        choice.setAttribute('aria-pressed', String(state.rate === rate)); list.append(choice);
      }
      root.append(el('p', '', '调整当前音频的实际播放速度。'), list);
    });
  }
  function playWord(id) {
    const segment = manifest.groups['word:' + id]?.[0];
    if (!segment) return toast('这个词条暂没有示例音频。');
    media?.audio.pause(); stopWordAudio();
    const audio = new Audio(segment.url); wordAudio = audio;
    audio.play().then(() => toast('正在朗读 · ' + manifest.voice.name)).catch(() => toast('浏览器无法播放词条音频，请检查声音权限。'));
  }
  function historySheet() {
    openModal('历史日刊', root => {
      root.append(el('p', '', '选择一份示例日刊，体验历史日期切换。'));
      for (const date of ['2026-11-01', '2026-10-31', '2026-10-30']) {
        const choice = button(date + (date === state.date ? '　✓' : ''), () => { state.date = date; persist(); modal.close(); navigate('daily'); }, 'demo-choice-row');
        root.append(choice);
      }
    });
  }
  function pasteSheet() {
    openModal('ことばを置いて、読む時間へ。', root => {
      root.append(el('p', '', '粘贴一段日文，在 Demo 中实际保存并阅读。'));
      const form = el('form', 'demo-paste-form');
      const titleLabel = el('label', '', '文章标题'); titleLabel.htmlFor = 'demo-title';
      const title = el('input'); title.id = 'demo-title'; title.required = true; title.maxLength = 120; title.placeholder = '例如：今日の手紙';
      const textLabel = el('label', '', '日文正文'); textLabel.htmlFor = 'demo-text';
      const text = el('textarea'); text.id = 'demo-text'; text.required = true; text.maxLength = 10000; text.rows = 7;
      text.value = '今日は、少しだけ遠回りをして帰りました。\n\nいつもの町にも、まだ知らない風景がありました。';
      const submit = el('button', 'primary', '保存并阅读'); submit.type = 'submit';
      form.append(titleLabel, title, textLabel, text, submit);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!title.value.trim() || !text.value.trim()) return;
        const item = { id: 'custom-' + Date.now(), title: title.value.trim(), source: '粘贴正文', date: '2026-11-01', time: '', category: '自分の文章', custom: true, paragraphs: text.value.trim().split(/\n\s*\n|\n/).filter(Boolean).map(ja => ({ ja })) };
        state.custom.push(item); persist(); articleReturn = 'reader'; modal.close(); navigate('article/' + item.id);
      });
      root.append(form);
    });
  }
  function contentsSheet() {
    const [, id, index] = activePath.split('/');
    const item = content.books.find(book => book.id === id);
    if (!item) return;
    openModal('目次 · ' + item.title, root => {
      item.chapters.forEach((chapter, chapterIndex) => {
        root.append(button(chapter.title + (Number(index) === chapterIndex ? '　✓' : ''), () => { modal.close(); navigate(`book/${id}/${chapterIndex}`); }, 'demo-choice-row'));
      });
    });
  }
  const dialogActions = {
    history: historySheet, paste: pasteSheet, example: pasteSheet, contents: contentsSheet,
    import: () => {
      const value = $('#article-link').value.trim();
      try {
        const url = new URL(value);
        const id = url.pathname.replace(/^\//, '');
        if (url.hostname !== 'demo.fujimi.local' || !articleById(id)) throw new Error('sample');
        articleReturn = 'reader'; navigate('article/' + id);
      } catch { toast('Demo 支持预填的示例链接；也可以点“粘贴正文”体验阅读。'); }
    },
    origin: () => explain('文章信息', '这是为交互 Demo 编写的合成文章，没有对应原站。可以实际切换译文、收藏并播放日语朗读。'),
    book: () => explain('EPUBを追加', '当前 Demo 使用内置示例书籍。正式 Android 的本机 EPUB 导入尚未接入，此处不会假装导入成功。'),
    voice: () => openModal('声の形', root => {
      root.append(el('p', '', 'Demo 使用本地生成的真实日语音频。当前声线：' + manifest.voice.name + '。'), button('试听「木漏れ日」', () => playWord('komorebi'), 'primary'));
    }),
    generate: () => { state.date = '2026-11-01'; persist(); navigate('daily'); toast('已打开 11 月 1 日的示例日刊'); },
    pair: () => explain('PC 協同', '演示文库没有连接电脑。正式版本在同一网络中配对后，可手动双向补齐文库。'),
    reset: () => openModal('重置演示文库', root => {
      root.append(el('p', '', '清除这个 Demo 中的收藏、粘贴文章和阅读位置，恢复初始示例。'), button('重置 Demo', () => { Object.assign(state, JSON.parse(JSON.stringify(defaults))); persist(); positions.clear(); mediaPositions.clear(); modal.close(); navigate('daily'); toast('Demo 已恢复初始状态'); }, 'primary'));
    })
  };
  function rememberPosition() {
    const scroll = $('.reading-content') || main;
    positions.set(activePath, scroll.scrollTop);
  }
  function render() {
    if (activePath) rememberPosition();
    stopMedia();
    if (modal.open) modal.close();
    showDrawer(false);
    const path = location.hash.slice(1) || 'daily';
    const [view, id, index] = path.split('/');
    activePath = path;
    main.replaceChildren(); main.scrollTop = 0;
    phone.classList.toggle('reading', ['article', 'book'].includes(view)); phone.classList.remove('listen-mode');
    const routes = { daily, reader, bookmarks, library, dictionary, settings };
    if (routes[view]) routes[view]();
    else if (view === 'article') article(id);
    else if (view === 'book') book(id, Number(index || 0));
    else notFound();
    $$('#navigation [aria-current]').forEach(node => node.removeAttribute('aria-current'));
    const current = $(`#navigation [data-route="${Object.hasOwn(names, view) ? view : ''}"]`);
    if (current) current.setAttribute('aria-current', 'page');
    if (['settings', 'bookmarks'].includes(view)) more.setAttribute('aria-current', 'page');
    document.title = (names[view] || (view === 'book' ? '書籍を読む' : '記事を読む')) + ' · 交互 Demo';
    requestAnimationFrame(() => {
      const scroll = $('.reading-content') || main;
      const savedPosition = view === 'book' ? (state.progress[id]?.fraction || 0) * Math.max(0, scroll.scrollHeight - scroll.clientHeight) : 0;
      scroll.scrollTop = positions.has(path) ? positions.get(path) : savedPosition;
      main.focus({ preventScroll: true });
      reportDemo();
    });
  }
  function reportDemo() {
    window.__demoState = { route: activePath, saved: [...state.saved], audioKey: media?.key || null, playing: media ? !media.audio.paused : false };
    const bounds = phone.getBoundingClientRect();
    window.__demoLayout = { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, mainWidth: main.clientWidth, mainScrollWidth: main.scrollWidth, phoneWidth: bounds.width };
  }
  async function boot() {
    const responses = await Promise.all(['screen.html', 'demo-content.json', 'demo-audio/manifest.json'].map(url => fetch(url)));
    if (responses.some(response => !response.ok)) throw new Error('demo assets');
    const html = await responses[0].text(); content = await responses[1].json(); manifest = await responses[2].json();
    const source = new DOMParser().parseFromString(html, 'text/html');
    $$('script', source).forEach(node => node.remove());
    document.body.replaceChildren(...[...source.body.childNodes].map(node => document.importNode(node, true)));
    const banner = el('header', 'demo-banner');
    banner.append(el('span', '', '富士見新聞文庫'), el('span', '', '交互 Demo · 独立示例文库'));
    const link = el('a', '', '设计看板'); link.href = 'index.html'; banner.append(link); document.body.prepend(banner);
    phone = $('#phone'); main = $('#main'); modal = $('#demo-dialog'); drawer = $('#drawer'); more = $('#more');
    $('.bar-note').textContent = '交互 Demo';
    $('.statusbar>b').textContent = 'Demo';
    const notice = el('div', 'demo-toast'); notice.id = 'demo-toast'; notice.setAttribute('role', 'status'); notice.hidden = true; phone.append(notice);
    const pause = document.createElementNS('http://www.w3.org/2000/svg', 'symbol'); pause.id = 'i-pause'; pause.setAttribute('viewBox', '0 0 24 24');
    const path = document.createElementNS(pause.namespaceURI, 'path'); path.setAttribute('d', 'M7 5h4v14H7zM15 5h4v14h-4z'); pause.append(path); $('.symbols').append(pause);
    more.addEventListener('click', () => showDrawer(true)); $('#close-drawer').addEventListener('click', () => showDrawer(false)); $('#scrim').addEventListener('click', () => showDrawer(false));
    document.addEventListener('click', event => {
      const action = event.target.closest('[data-dialog]');
      if (action && dialogActions[action.dataset.dialog]) { event.preventDefault(); dialogActions[action.dataset.dialog](); }
      const articleLink = event.target.closest('a[href^="#article/"]');
      if (articleLink && names[activePath]) articleReturn = activePath;
    });
    document.addEventListener('keydown', event => {
      if (drawer.hidden) return;
      if (event.key === 'Escape') showDrawer(false);
      if (event.key === 'Tab') {
        const controls = $$('a,button', drawer); const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    });
    modal.addEventListener('click', event => { if (event.target === modal) { const bounds = modal.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) modal.close(); } });
    modal.addEventListener('close', stopWordAudio);
    window.addEventListener('hashchange', render); window.addEventListener('resize', reportDemo);
    window.addEventListener('pagehide', stopMedia);
    render(); window.__demoReady = true;
    window.__demoInspect = () => { reportDemo(); return { ...window.__demoState, layout: window.__demoLayout, audio: media ? { paused: media.audio.paused, currentTime: media.audio.currentTime, duration: media.audio.duration, rate: media.audio.playbackRate, index: media.index, total: media.total } : null }; };
  }
  boot().catch(() => {
    document.body.replaceChildren(el('p', 'loading-demo', 'Demo 暂未加载完成。请通过本地 Demo 地址打开，或刷新重试。'));
  });
})();
