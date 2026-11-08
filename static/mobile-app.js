/* Mobile app shell over the persistent Android library and native readers. */
(() => {
  'use strict';
  if (document.documentElement.dataset.redesignApp !== 'true') return;
  // Reuse the Demo's Japanese form copy without replacing the already-bound controls.
  for (const selector of ['#web-text-dialog', '#web-example-editor']) {
    const dialog = document.querySelector(selector);
    dialog.querySelector('.section-kicker').textContent = '本文の取り込み';
    dialog.querySelector('.icon-button').setAttribute('aria-label', '閉じる');
    dialog.querySelector('.web-text-fields label:first-child > span').textContent = 'タイトル';
    dialog.querySelector('.web-text-fields label:nth-child(2) > span').textContent = '日本語の本文';
    dialog.querySelector('button.quiet').textContent = 'キャンセル';
    const voice = dialog.querySelector('select'); voice.setAttribute('aria-label', '読み上げ音声');
    if (voice.nextElementSibling?.matches('.android-select-trigger')) voice.nextElementSibling.setAttribute('aria-label', '読み上げ音声');
    if (voice.options.length === 1 && !voice.options[0].value) voice.options[0].textContent = '音声を読み込み中…';
  }
  const textDialog = document.querySelector('#web-text-dialog');
  textDialog.querySelector('#web-example-trigger').textContent = '例文を使う';
  textDialog.querySelector('#web-example-add').textContent = '例文を追加';
  textDialog.querySelector('[type=submit]').textContent = '保存して読む';
  textDialog.querySelector('.web-runtime-note').textContent = window.FujimiMobile
    ? 'Androidでの本文取り込みは未対応です。保存済みの文章は閲読室から読めます。'
    : 'ふりがなを自動で付けて保存します。本文の語句を選んで調べたり、ブラウザーで読み上げたりできます。';
  textDialog.querySelector('#web-example-save-toast').textContent = '例文を保存しました';
  const exampleDialog = document.querySelector('#web-example-editor');
  exampleDialog.querySelector('#web-example-editor-title').textContent = '例文を追加';
  exampleDialog.querySelector('.web-example-voice-row > span').textContent = '読み上げ音声';
  exampleDialog.querySelector('.web-example-storage-note').textContent = window.FujimiMobile
    ? 'Androidでの例文追加・更新は未対応です。'
    : '例文は端末に保存します。同じタイトルで保存すると、本文と読み上げ音声を更新します。';
  exampleDialog.querySelector('[type=submit]').textContent = '例文を保存';
  // Only the app clone uses the approved compact opening; the desktop template remains unchanged.
  const articleTemplate = document.querySelector('#article-template').content.querySelector('.article-detail');
  const oldOpening = articleTemplate.querySelector('.article-top');
  if (oldOpening) {
    const opening = document.createElement('template');
    opening.innerHTML = `<header class="article-heading">
        <h1 class="title"></h1>
        <div class="article-utility" role="group" aria-label="記事の情報と操作">
          <div class="article-imprint"><div class="article-publisher"><a class="origin" target="_blank" rel="noreferrer" title="原文のサイトを開く"><span class="source"></span></a></div><p class="published"></p></div>
          <div class="translation-switch">
            <button data-mode="parallel" class="translation-menu-toggle" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="訳文の表示"><span>訳文</span></button>
            <div class="translation-menu" role="menu" hidden><button class="retranslate quiet" type="button" hidden>再翻訳</button><span class="translation-task-status" role="status"></span></div>
          </div>
          <div class="reread-popover-wrap"><button class="reread-link" type="button" aria-label="読み返し" title="読み返し" aria-haspopup="dialog" aria-expanded="false"><svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10a8 8 0 1 1 1.4 7M4 5v5h5"/><path d="m11 9 4 3-4 3z"/></svg></button><section class="reread-panel" role="dialog" aria-label="読み返し" hidden><h3>読み返し</h3><p>声線を選び、段落ごとに音声を生成し直します。</p><div class="reread-controls"><select class="reread-voice" aria-label="読み返しに使う声線"></select><div class="reread-actions"><button class="reread">再生成</button><button class="cancel-reread danger-outline" type="button" hidden>中止</button></div></div></section></div>
          <button class="bookmark" type="button" aria-label="お気に入り" title="お気に入り" aria-pressed="false"><svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4Z"/></svg></button>
          <button class="copy-original" type="button" aria-label="原文をコピー" title="原文をコピー"><svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 4H6a2 2 0 0 0-2 2v10"/></svg></button>
        </div>
        <button class="exit-reader" type="button" aria-label="一覧に戻る" hidden></button>
      </header>`;
    articleTemplate.prepend(opening.content);
    oldOpening.remove();
    articleTemplate.querySelector(':scope > .title')?.remove();
    articleTemplate.querySelector(':scope > .article-meta')?.remove();
    if (window.FujimiMobile) articleTemplate.querySelector('.origin').removeAttribute('target');
  }
  const host = document.createElement('fujimi-app');
  const root = host.attachShadow({ mode: 'open' });
  const sheetStyle = document.createElement('link'); sheetStyle.rel = 'stylesheet'; sheetStyle.href = '/static/mobile-app.css?v=20261108-voice-playback';
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
    if (action) result.addEventListener('click', event => Promise.resolve().then(() => action(event)).catch(error => notify(error.message, true)));
    return result;
  }
  function iconButton(name, label, action) {
    const result = button('', action, 'icon-button'); result.append(icon(name)); result.setAttribute('aria-label', label); return result;
  }
  const cache = { days: [], daily: null, books: [], bookmarks: [], voices: [], catalog: [], mode: {}, library: {}, schedule: {}, dailyConfig: {}, sources: [], sync: {}, examples: [], stats: {} };
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
  readingBar.append(iconButton('back', '一覧に戻る', () => leaveReading()), node('span', '', '日刊'), node('span', 'reader-brand', '富士見新聞文庫'));
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
    const parent = modal.open ? modal : root;
    if (toast.parentNode !== parent) parent.append(toast);
    toast.textContent = message;
    toast.hidden = false;
    toast.classList.toggle('is-error', error);
    toast.setAttribute('role', error ? 'alert' : 'status');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
  }
  window.__fujimiNativeNotice = (message, error = true) => notify(String(message || '操作できませんでした。'), error);
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
  modal.addEventListener('close', stopReferencePreview);
  modal.addEventListener('cancel', event => {
    if (!modal.querySelector('.voice-catalog-list')) return;
    event.preventDefault(); voiceSheet().catch(error => notify(error.message, true));
  });
  modal.addEventListener('close', () => {
    clearTimeout(syncRefreshTimer); window.FujimiAppSettings?.stop();
    const status = window.FujimiAppSettings?.status() || {};
    const sync = q('.settings-page .sync-entry-copy small'); if (sync) sync.textContent = deviceStatus(status);
    const services = q('[data-app-services] .setting-value>span'); if (services) services.textContent = status.deepseek_configured ? '設定済み' : '未設定';
  });
  modal.addEventListener('click', event => {
    if (event.target !== modal) return;
    const rect = modal.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close();
  });
  function sheet(title, build, description = '') {
    clearTimeout(syncRefreshTimer);
    window.FujimiAppSettings?.stop();
    modal.classList.remove('settings-sheet', 'voice-sheet');
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
    cache.days = await api('/api/days');
    if (ui.date && !cache.days.includes(ui.date)) ui.date = '';
    const date = ui.date || cache.days[0];
    if (!date) {
      page.append(heading('本日ノニュース', slogans.daily), empty('今日の一篇は、これから。', '日刊を作成して、読む時間をはじめましょう。', 'news'), button('日刊を作成', dailyTaskSheet, 'primary'));
      return;
    }
    cache.daily = await api('/api/daily?date=' + encodeURIComponent(date));
    const top = node('div', 'daily-heading'); top.append(heading('本日ノニュース', slogans.daily));
    const issue = node('div', 'daily-issue');
    const dateValue = new Date(date + 'T00:00:00+08:00');
    issue.append(node('p', '', new Intl.DateTimeFormat('ja-JP', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'Asia/Shanghai' }).format(dateValue)));
    const actions = node('div', 'daily-actions');
    const history = button('過去の日刊', historySheet, 'text-button'); history.prepend(icon('calendar'));
    actions.append(iconButton('news', '日刊を更新', dailyTaskSheet), history); issue.append(actions); top.append(issue); page.append(top);
    const list = node('section', 'news-list'); list.setAttribute('aria-label', '日刊文章');
    cache.daily.articles.forEach((article, index) => list.append(articleCard(article, index === 0))); page.append(list);
  }
  async function dailyTaskSheet() {
    let current = await api('/api/tasks/daily');
    const body = settingsSheet('日刊の更新', body => {
      body.classList.add('app-task');
      const title = node('p', 'app-task-title'); title.setAttribute('role', 'status');
      const progress = node('progress'); progress.max = 100; progress.setAttribute('aria-label', '日刊の更新状況');
      const detail = node('p', 'app-task-detail');
      const feedback = node('p', 'source-feedback'); feedback.hidden = true; feedback.setAttribute('role', 'alert');
      const actions = node('div', 'app-task-actions');
      const start = button('今すぐ作成', async () => {
        start.disabled = true; feedback.hidden = true;
        try { await api('/api/daily/generate', { method: 'POST' }); await poll(); }
        catch (error) { feedback.textContent = error.message; feedback.hidden = false; start.disabled = false; }
      }, 'primary');
      const cancel = button('中止', async () => {
        cancel.disabled = true;
        try { await api('/api/tasks/daily', { method: 'DELETE' }); await poll(); }
        catch (error) { feedback.textContent = error.message; feedback.hidden = false; cancel.disabled = false; }
      }, 'pill-action');
      actions.append(start, cancel); body.append(title, progress, detail, feedback, actions);
      const render = task => {
        const running = task.status === 'running';
        title.textContent = ({ running: '日刊を作成しています', completed: '日刊ができました', partial: '一部の記事を保存しました', failed: '更新できませんでした', cancelled: '更新を中止しました', interrupted: '更新が中断されました' })[task.status] || '今日のニュースを集める。';
        progress.hidden = !running && task.status !== 'completed';
        progress.value = task.status === 'completed' ? 100 : Math.max(0, Math.min(99, Number(task.percent) || 0));
        const errors = (task.errors || []).map(error => typeof error === 'string' ? error : error.detail || error.message || '').filter(Boolean);
        detail.textContent = [task.message, task.total ? `${task.completed || 0} / ${task.total} 篇` : '', ...errors].filter(Boolean).join('\n');
        start.hidden = running; start.disabled = running; cancel.hidden = !running; cancel.disabled = !running;
      };
      async function poll() {
        clearTimeout(syncRefreshTimer);
        if (!modal.open || !body.isConnected) return;
        try {
          current = await api('/api/tasks/daily');
          if (!modal.open || !body.isConnected) return;
          render(current);
          if (current.status === 'running') syncRefreshTimer = setTimeout(poll, 1000);
          else {
            cache.daily = null; cache.days = await api('/api/days'); ui.date = '';
            if (ui.view === 'daily') await showPage('daily', { push: false });
          }
        } catch (error) { feedback.textContent = error.message; feedback.hidden = false; }
      }
      render(current);
      if (current.status === 'running') syncRefreshTimer = setTimeout(poll, 1000);
    });
  }
  function historySheet() {
    sheet('過去の日刊', body => {
      cache.days.forEach(date => body.append(choice(date, '', date === (ui.date || cache.days[0]), () => { ui.date = date; modal.close(); showPage('daily', { push: false }); })));
    }, '保存済みの日刊を選んでください。');
  }
  async function bookmarksPage(page) {
    cache.bookmarks = await api('/api/bookmarks');
    page.append(heading('お気に入り', slogans.bookmarks));
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
        const all = [...(cache.daily?.articles || []), ...await api('/api/bookmarks')];
        if (!cache.daily && cache.days.length) all.push(...(await api('/api/daily?date=' + cache.days[0])).articles);
        const normalized = value => { const url = new URL(value); url.hash = ''; return url.href.replace(/\/$/, ''); };
        const article = all.find(item => item.url && normalized(item.url) === normalized(input.value.trim()));
        if (article) await enterArticle(article);
        else { error.textContent = '日刊やお気に入りに記事が見つかりません'; error.hidden = false; }
      } catch { error.textContent = '記事を開けませんでした しばらくしてから、もう一度お試しください'; error.hidden = false; }
      finally { submit.disabled = false; }
    });
    intro.append(form, node('div', 'reader-divider', 'または'));
    const paste = button('本文を貼り付ける', () => { q('dialog')?.close(); document.querySelector('#open-web-text-dialog').click(); }, 'paste-action'); paste.prepend(icon('paste')); intro.append(paste);
    page.append(intro);
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
    const add = button('导入', importBookSheet, 'pill-action'); add.prepend(icon('plus')); add.setAttribute('aria-label', '导入 EPUB');
    page.append(heading('書架', slogans.library, add));
    if (!cache.books.length) { page.append(empty('本棚に、一冊を。', 'PCと文庫をつなぐと、保存した本をここで読めます。')); return; }
    const shelf = node('section', 'shelf'); shelf.setAttribute('aria-label', '电子书书架');
    cache.books.forEach(book => {
      const tile = button('', () => enterBook(book), 'book-tile'); tile.dataset.bookId = book.id;
      if (book.cover_url) { const image = node('img'); image.src = book.cover_url; image.alt = book.title + 'の表紙'; image.loading = 'eager'; tile.append(image); }
      else tile.append(node('span', 'no-cover', book.title));
      tile.append(node('h3', '', book.title), node('p', '', book.author)); shelf.append(tile);
    });
    page.append(shelf);
  }
  function importBookSheet() {
    if (!window.FujimiMobile) { document.querySelector('#book-files').click(); return; }
    settingsSheet('EPUB を追加', body => {
      body.append(node('p', 'settings-info', 'AndroidでのEPUBファイル取り込みは未対応です。PCで取り込んだ書籍は、設定の「文庫互联」から同期できます。'));
      body.append(button('閉じる', () => modal.close(), 'primary'));
    });
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
    dictionaryPreviewPage.querySelector('.dictionary-home-welcome').hidden = !welcome;
  }
  new MutationObserver(updateDictionaryHome).observe(nativeDictionary, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden']
  });

  function dictionaryContext(page) {
    const original = getComputedStyle(nativeDictionaryContainer);
    nativeDictionary.style.font = original.font;
    nativeDictionary.style.color = 'var(--ink)';
    for (const [property, value] of Object.entries(window.__nativeDictionaryTheme || {})) {
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
    const favorites = button('收藏', () => showPage('dictionary-favorites'), 'pill-action'); favorites.prepend(icon('bookmark'));
    intro.append(heading('辞書', slogans.dictionary, favorites));
    const slot = node('slot');
    slot.name = 'native-dictionary';
    const welcome = node('div', 'dictionary-home-welcome');
    const copy = node('div');
    copy.append(node('h2', '', 'ことばを知る。読む世界が、広がる。'), node('p', '', '気になったことばを、ここから。'));
    welcome.append(node('span', '', '語'), copy);
    page.append(intro, slot, welcome);
    dictionaryContext(page);
    await showView('dictionary', { historyMode: 'none' });
    updateDictionaryHome();
  }
  async function dictionaryFavoritesPage(page) {
      const title = node('div', 'favorites-page-heading');
      title.append(iconButton('back', '返回辞書', () => history.back()), node('h1', '', '收藏词条'));
      const body = node('div', 'word-favorites'); page.append(title, body);
      let ids;
      try { ids = JSON.parse(localStorage.getItem('fujimi-dictionary-favorites') || '[]'); if (!Array.isArray(ids)) throw new Error(); }
      catch { body.append(node('p', 'error-note', '收藏记录无法读取。')); return; }
      if (!ids.length) { body.append(node('p', 'status-note', '暂无收藏词条')); return; }
      ids.forEach(id => {
        const row = node('div', 'word-favorite-row'); row.dataset.wordId = String(id);
        const open = button('読み込み中…', null, 'word-favorite-open'); open.disabled = true;
        const remove = iconButton('close', '取消收藏', () => {
          const latest = JSON.parse(localStorage.getItem('fujimi-dictionary-favorites') || '[]');
          localStorage.setItem('fujimi-dictionary-favorites', JSON.stringify(latest.filter(value => String(value) !== String(id))));
          row.remove(); if (!body.children.length) body.append(node('p', 'status-note', '暂无收藏词条'));
        });
        row.append(open, remove); body.append(row);
        api('/api/dictionary/words/' + encodeURIComponent(id)).then(word => {
          if (!row.isConnected) return;
          open.replaceChildren(node('strong', '', word.spell), node('small', '', word.pron || '')); open.disabled = false;
          open.onclick = async () => {
            try {
              await showPage('dictionary');
              ui.dictionaryReturnView = 'dictionary-favorites';
              await loadDictionaryDetail(word.id, { reveal: true });
            } catch (error) { notify(error.message, true); }
          };
        }).catch(() => { open.textContent = '词条无法读取'; });
      });
  }
  async function settingsPage(page) {
    [cache.mode, cache.voices, cache.library, cache.schedule, cache.dailyConfig, cache.sources, cache.sync] = await Promise.all([
      api('/api/settings/voice-mode'), api('/api/settings/voices'), api('/api/settings/library'), api('/api/settings/daily-schedule'), api('/api/settings/daily-content'), api('/api/settings/news-sources'), Promise.resolve(window.FujimiAppSettings?.status() || {})]);
    page.append(heading('設定', slogans.settings));
    const voice = selectedVoice();
    const voiceName = voice?.name || '朗読しない';
    const card = node('div', 'settings-voice');
    const preview = iconButton('speaker', voiceName + 'を試聴', () => cache.mode.mode === 'voice' ? playReferencePreview(voice, preview) : speakDictionaryText('こんにちは。今日はいい天気ですね。', preview));
    preview.innerHTML = DICTIONARY_SOUND_ICON;
    preview.classList.add('dictionary-speech-button', 'settings-voice-preview'); preview.setAttribute('aria-pressed', 'false');
    preview.dataset.playLabel = voiceName + 'を試聴'; preview.title = preview.dataset.playLabel;
    preview.disabled = !voice || (cache.mode.mode === 'browser' && Boolean(voice.saved_audio_only));
    if (preview.disabled) { preview.title = 'この端末では試聴できません'; preview.setAttribute('aria-label', voiceName + 'はこの端末では試聴できません'); }
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
    (control.closest('.settings-voice, .voice-manager-row') || modal).append(audio);
    control.setAttribute('aria-pressed', 'true'); control.setAttribute('aria-busy', 'true');
    control.setAttribute('aria-label', voice.name + 'の試聴を停止'); control.title = voice.name + 'の試聴を停止';
    control.classList.add('is-speaking');
    const fail = () => {
      if (referencePreview !== active) return;
      stopReferencePreview(); notify('音声を再生できません。', true);
    };
    audio.onended = () => { if (referencePreview === active) stopReferencePreview(); };
    audio.onerror = fail;
    audio.src = '/api/settings/voices/' + voice.id + '/reference';
    try { await audio.play(); if (referencePreview === active) control.removeAttribute('aria-busy'); }
    catch { fail(); }
  }
  async function refreshVoiceSettings() {
    await loadVoices();
    [cache.mode, cache.voices, cache.catalog] = await Promise.all([api('/api/settings/voice-mode'), api('/api/settings/voices'), api('/api/browser-voices')]);
  }
  async function returnToVoices(message = '') {
    modal.close(); await showPage('settings', { push: false }); await voiceSheet(); if (message) notify(message);
  }
  function voicePreviewButton(voice) {
    const control = iconButton('speaker', voice.name + 'を試聴', () => {
      if (voice.kind === 'reference') return playReferencePreview(voice, control);
      if (state.dictionarySpeech?.button === control) return stopDictionarySpeech();
      stopReferencePreview(); stopDictionarySpeech();
      if (!window.FujimiMobile?.speakWithVoice) return speakDictionaryText('こんにちは。今日はいい天気ですね。', control);
      const token = ++state.dictionarySpeechToken;
      state.dictionarySpeech = { button: control, token };
      control.classList.add('is-speaking'); control.setAttribute('aria-label', '試聴を停止');
      mobileSpeak('こんにちは。今日はいい天気ですね。', 1, event => {
        if (state.dictionarySpeech?.token !== token) return;
        if (event === 'error') notify('音声を再生できません。端末の音声設定と接続を確認してください。', true);
        if (['done', 'error', 'stop'].includes(event)) { resetDictionarySpeechButton(control); state.dictionarySpeech = null; }
      }, voice.id);
    });
    control.innerHTML = DICTIONARY_SOUND_ICON; control.classList.add('dictionary-speech-button', 'voice-preview');
    control.dataset.playLabel = voice.name + 'を試聴'; control.title = control.dataset.playLabel;
    control.disabled = voice.available === false || Boolean(voice.saved_audio_only && voice.kind !== 'reference');
    if (control.disabled) control.title = voice.unavailable_detail || 'この音声の試聴にはPCで作成した音声が必要です';
    return control;
  }
  async function voiceActions(voice) {
    stopReferencePreview(); stopDictionarySpeech();
    settingsSheet(voice.name, body => {
      const actions = node('div', 'voice-action-list');
      actions.append(button('声線を編集', () => voiceEditor(voice)), button('削除', async () => {
        if (!confirm('「' + voice.name + '」を削除しますか？')) return;
        await api(voice.kind === 'browser' ? '/api/settings/browser-voices' : '/api/settings/voices/' + voice.id,
          { method: 'DELETE', body: JSON.stringify({ id: voice.id }) });
        await returnToVoices('削除しました');
      }, 'voice-delete'), button('一覧に戻る', voiceSheet));
      body.append(actions);
    });
  }
  async function selectReadingVoice(voice) {
    if (voice.kind === 'browser') await api('/api/settings/browser-voice', { method: 'PUT', body: JSON.stringify({ name: voice.id, label: voice.name }) });
    else await api('/api/settings/active-voice', { method: 'PUT', body: JSON.stringify({ voice_id: voice.id }) });
    modal.close(); await loadVoices(); await showPage('settings', { push: false });
  }
  function appendVoiceRow(body, voice, options = {}) {
    const row = node('div', 'voice-manager-row'); row.dataset.voiceId = String(options.id || voice.id);
    const active = options.active ?? (voice.kind === 'browser' ? cache.mode.mode === 'browser' && cache.mode.browser_voice_name === voice.id : cache.mode.mode === 'voice' && Number(cache.mode.voice_id) === Number(voice.id));
    const select = choice(options.label || voice.name, options.subtitle || (voice.available === false ? '端末で日本語の音声を有効にしてください' : ''), active,
      options.select || (() => selectReadingVoice(voice)), options.available ?? voice.available !== false);
    if (voice.available === false) select.title = voice.unavailable_detail || 'この端末では利用できません';
    row.append(voicePreviewButton(voice), select);
    if (options.manage || (options.manageable !== false && !voice.read_only && voice.id !== 'android:system')) {
      const more = button('', options.manage || (() => voiceActions(voice)), 'icon-button voice-more');
      more.setAttribute('aria-label', options.manage ? 'システム音声を変更' : voice.name + 'の操作');
      if (options.manage) more.append(icon('next'));
      else more.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';
      row.append(more);
    }
    body.append(row);
  }
  async function browserVoiceSheet() {
    stopReferencePreview(); stopDictionarySpeech(); await refreshVoiceSettings();
    settingsSheet('システム音声', body => {
      const list = node('div', 'voice-catalog-list');
      cache.catalog.filter(voice => voice.id !== 'android:system').forEach(voice => appendVoiceRow(list, { ...voice, kind: 'browser' }, { manageable: false, active: voice.id === edgeVoiceId(cache.mode.browser_voice_name) }));
      if (!cache.catalog.length) list.append(node('p', 'status-note', '利用できる音声がありません'));
      body.append(list);
    });
    modal.classList.add('voice-sheet');
    const back = iconButton('back', '声線一覧に戻る', voiceSheet); back.classList.add('voice-catalog-back');
    modal.querySelector('.sheet-head').prepend(back);
  }
  async function voiceSheet() {
    stopReferencePreview(); stopDictionarySpeech(); await refreshVoiceSettings();
    settingsSheet('朗読の音声', body => {
      const list = node('div', 'voice-main-list');
      const current = cache.catalog.find(voice => voice.id === cache.mode.browser_voice_name);
      const browser = { ...(current || { id: cache.mode.browser_voice_name || 'android:system', name: cache.mode.browser_voice_label || '音声を選ぶ', available: false }), kind: 'browser' };
      appendVoiceRow(list, browser, { id: 'browser', label: browser.id === 'android:system' ? 'システム音声' : 'システム音声（' + browser.name + '）',
        active: cache.mode.mode === 'browser', available: true, manage: browserVoiceSheet,
        select: async () => {
          if (!current || current.available === false) return browserVoiceSheet();
          await selectReadingVoice(browser);
        } });
      cache.voices.forEach(voice => appendVoiceRow(list, { ...voice, kind: 'reference' }));
      body.append(list);
    });
    modal.classList.add('voice-sheet');
    const add = iconButton('plus', '声線を追加', () => voiceEditor()); add.classList.add('voice-add');
    const header = modal.querySelector('.sheet-head'); header.insertBefore(add, header.lastElementChild);
  }
  async function voiceEditor(voice = null) {
    stopReferencePreview(); stopDictionarySpeech();
    const catalog = (await api('/api/settings/voice-catalog')).filter(item => !item.read_only && item.id !== 'android:system');
    settingsSheet(voice ? '声線を編集' : '声線を追加', body => {
      const form = node('form', 'sheet-form voice-editor');
      const nameLabel = node('label', '', '名前'); const name = node('input', 'field'); name.required = true; name.maxLength = 80; name.value = voice?.name || ''; nameLabel.append(name);
      const sourceLabel = node('label', '', '音源'); const source = node('select', 'field'); source.setAttribute('aria-label', '音源');
      source.append(new Option('音声ファイル', 'file'), new Option('音声URL', 'url'));
      if (!voice || voice.kind === 'browser') source.append(new Option('既存の声線', 'catalog'));
      source.value = voice?.kind === 'browser' ? 'catalog' : 'file'; sourceLabel.append(source);
      const catalogLabel = node('label', '', '声線'); const catalogSelect = node('select', 'field'); catalogSelect.setAttribute('aria-label', '声線');
      catalog.forEach(item => catalogSelect.append(new Option(item.name, item.id))); catalogSelect.disabled = Boolean(voice);
      if (voice?.kind === 'browser') catalogSelect.value = voice.id;
      catalogLabel.append(catalogSelect);
      const urlLabel = node('label', '', '音声URL'); const url = node('input', 'field'); url.type = 'url'; url.placeholder = 'https://…/voice.wav'; url.autocomplete = 'off'; url.maxLength = 4096; urlLabel.append(url);
      const audioLabel = node('div', 'voice-file-row'); const filename = node('span', 'voice-file-name', voice?.kind === 'reference' ? '現在の音声を使用' : '');
      let token = '', loadedUrl = '';
      const pick = button('ファイルを選ぶ', async () => {
        pick.disabled = true;
        try {
          const chosen = await api('/api/settings/voice-file', { method: 'POST', body: '{}' });
          if (chosen.cancelled) return;
          if (!form.isConnected || !modal.open) { await api('/api/settings/voice-file', { method: 'DELETE', body: JSON.stringify({ file_token: chosen.file_token }) }); return; }
          token = chosen.file_token; loadedUrl = ''; filename.textContent = chosen.filename;
          if (!name.value) name.value = chosen.filename.replace(/\.wav$/i, '');
        } finally { pick.disabled = false; }
      }, 'pill-action');
      audioLabel.append(pick, filename);
      const constraint = node('p', 'voice-file-hint', 'WAV · 1–120秒 · 20 MiBまで');
      const discard = () => { if (token) api('/api/settings/voice-file', { method: 'DELETE', body: JSON.stringify({ file_token: token }) }).catch(() => {}); };
      modal.addEventListener('close', discard, { once: true });
      const sync = () => {
        audioLabel.hidden = source.value !== 'file'; urlLabel.hidden = source.value !== 'url'; catalogLabel.hidden = source.value !== 'catalog'; constraint.hidden = source.value === 'catalog';
        url.required = source.value === 'url'; url.disabled = source.value !== 'url';
      };
      source.onchange = sync; sync();
      catalogSelect.onchange = () => { if (!voice) name.value = catalogSelect.selectedOptions[0]?.textContent || ''; };
      const feedback = node('p', 'voice-editor-error'); feedback.hidden = true; feedback.setAttribute('role', 'alert');
      form.addEventListener('input', () => { feedback.hidden = true; });
      form.addEventListener('change', () => { feedback.hidden = true; });
      const actions = node('div', 'voice-editor-actions'); const save = node('button', 'primary', '保存'); save.type = 'submit';
      actions.append(button('戻る', async () => { modal.removeEventListener('close', discard); discard(); await voiceSheet(); }, 'pill-action'), save);
      form.append(nameLabel, sourceLabel, catalogLabel, audioLabel, urlLabel, constraint, feedback, actions); body.append(form);
      form.onsubmit = async event => {
        event.preventDefault(); if (!form.reportValidity()) return;
        feedback.hidden = true;
        if (source.value === 'file' && !token && (!voice || voice.kind === 'browser')) { feedback.textContent = '音声ファイルを選んでください'; feedback.hidden = false; return; }
        save.disabled = true; pick.disabled = true; source.disabled = true;
        try {
          if (source.value === 'url' && (!token || loadedUrl !== url.value.trim())) {
            const chosen = await api('/api/settings/voice-file', { method: 'POST', body: JSON.stringify({ audio_url: url.value.trim() }) });
            token = chosen.file_token; loadedUrl = url.value.trim();
          }
          if (!form.isConnected || !modal.open) { discard(); return; }
          const browser = voice ? voice.kind === 'browser' : source.value === 'catalog';
          const path = browser ? '/api/settings/browser-voices' : '/api/settings/voices' + (voice ? '/' + voice.id : '');
          const payload = { name: name.value.trim() };
          if (browser) payload.id = voice?.id || catalogSelect.value;
          if (source.value !== 'catalog' && token) payload.file_token = token;
          await api(path, { method: voice ? 'PUT' : 'POST', body: JSON.stringify(payload) });
          token = ''; modal.removeEventListener('close', discard); await returnToVoices('保存しました');
        } catch (error) {
          if (!form.isConnected) return;
          feedback.textContent = error.message; feedback.hidden = false; save.disabled = false; pick.disabled = false; source.disabled = false;
        }
      };
    });
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
            address.href = url.href; address.rel = 'noopener noreferrer';
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
    }, '指定した時刻に日刊を作成します。');
  }
  function sortSheet() {
    settingsSheet('書架の並び順', body => {
      for (const [value, label] of [['recent', '最近読んだ順'], ['series', 'シリーズ順'], ['imported', '追加した順']]) body.append(choice(label, '', cache.library.sort === value, async () => {
        cache.library = await api('/api/settings/library', { method: 'PUT', body: JSON.stringify({ ...cache.library, sort: value }) }); await loadLibrarySettings(); modal.close(); await showPage('settings', { push: false });
      }));
    });
  }
  function deviceStatus(status) {
    if (status.sync_state === 'running') return '同期中';
    if (status.windows_status === 'checking') return '接続を確認中';
    return status.paired && status.windows_status === 'ready' ? '接続済み' : status.paired ? '未接続' : '端末を接続';
  }
  function settingsHelpers() {
    return { node, button, icon, iconButton, notify, onLibraryChanged: async () => {
      cache.days = await api('/api/days'); cache.daily = null; cache.books = []; cache.examples = []; ui.date = '';
    } };
  }
  function deviceSheet() {
    settingsSheet('文庫互联', body => {
      window.FujimiAppSettings.renderSync(body, settingsHelpers());
      body.append(button('翻訳と通信', servicesSheet, 'text-button'));
    });
  }
  function servicesSheet() {
    settingsSheet('翻訳と通信', body => window.FujimiAppSettings.renderServices(body, settingsHelpers()));
  }
  function maintenanceSheet() {
    settingsSheet('文庫の点検', body => {
      body.append(node('p', 'settings-info', '記事と書籍のファイルを確認し、文庫の索引を整理します。'));
      body.append(node('p', 'settings-info', 'Androidでの文庫刷新は未対応です。PCの設定から「文庫刷新」を実行してください。'), button('閉じる', () => modal.close(), 'primary'));
    });
  }
  function prepareArticleHeading() {
    const article = document.querySelector('#reader-result .article-detail');
    if (!article || article.dataset.appHeading === 'ready') return;
    article.dataset.appHeading = 'ready';
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
    readingBar.querySelector('span').textContent = { daily: '日刊', reader: '閲読室', bookmarks: 'お気に入り' }[returnTo] || '日刊';
    ui.returnView = returnTo; ui.reading = 'article'; host.setAttribute('reading', 'article'); document.documentElement.dataset.nativeReading = 'article';
    window.scrollTo({ top: 0, behavior: 'auto' });
    updateInspect();
  }
  function prepareBookReader() {
    const reader = document.querySelector('#book-reader');
    const chrome = reader?.querySelector('.book-reader-chrome');
    if (!chrome || chrome.dataset.appBook === 'ready') return;
    chrome.dataset.appBook = 'ready';
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

  }
  async function enterBook(book) {
    stopDictionarySpeech();
    if (window.FujimiMobile) await loadVoices();
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
    await persistReadingPosition();
    const wasBook = ui.reading === 'book';
    stopArticlePlayback(); ui.reading = ''; if (wasBook) document.querySelector('#book-reader').hidden = true;
    host.removeAttribute('reading'); delete document.documentElement.dataset.nativeReading;
    await showPage(ui.returnView || 'daily'); window.scrollTo({ top: 0, behavior: 'auto' });
  }
  async function persistReadingPosition() {
    if (ui.reading !== 'book') return;
    const reader = document.querySelector('#book-reader');
    if (state.libraryProgressTimer) { clearTimeout(state.libraryProgressTimer); state.libraryProgressTimer = null; }
    await persistBookProgress(reader, state.libraryChapter);
    if (state.libraryScrollHandler) {
      window.removeEventListener('scroll', state.libraryScrollHandler);
      reader?.querySelector('.book-chapter-body')?.removeEventListener('scroll', state.libraryScrollHandler);
      state.libraryScrollHandler = null;
    }
  }
  async function showPage(view, { push = true } = {}) {
    if (!ui.loaded) return;
    if (!['daily', 'reader', 'library', 'dictionary', 'dictionary-favorites', 'settings', 'bookmarks'].includes(view)) view = 'daily';
    await persistReadingPosition();
    if (!ui.reading) positions.set(ui.view, main.scrollTop);
    stopReferencePreview(); stopDictionarySpeech(); window.FujimiAppSettings?.stop(); if (ui.reading) stopArticlePlayback();
    const wasBook = ui.reading === 'book';
    ui.reading = ''; if (wasBook) document.querySelector('#book-reader').hidden = true;
    host.removeAttribute('reading'); delete document.documentElement.dataset.nativeReading;
    nativeDictionary.hidden = view !== 'dictionary';
    ui.dictionaryReturnView = ''; ui.view = view; const request = ++ui.request;
    main.classList.toggle('native-dictionary-main', view === 'dictionary');
    const navigationView = view === 'bookmarks' ? 'settings' : view === 'dictionary-favorites' ? 'dictionary' : view;
    nav.querySelectorAll('button').forEach(item => { if (item.dataset.view === navigationView) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); });
    if (push && location.hash !== '#app/' + view) history.pushState({ redesignView: view }, '', '#app/' + view);
    const page = node('div', 'page ' + view + '-page'); page.append(node('p', 'loading', '文庫をひらいています。')); main.replaceChildren(page);
    try {
      const content = node('div', 'page ' + view + '-page');
      await { daily: dailyPage, reader: readerPage, library: libraryPage, dictionary: dictionaryPage, 'dictionary-favorites': dictionaryFavoritesPage, settings: settingsPage, bookmarks: bookmarksPage }[view](content);
      if (request !== ui.request) return; main.replaceChildren(content);
      requestAnimationFrame(() => { main.scrollTop = positions.get(view) || 0; main.focus({ preventScroll: true }); updateInspect(); });
    } catch (error) { if (request === ui.request) page.replaceChildren(heading('文庫に接続できません。'), node('p', 'error-note', error.message), button('再読み込み', () => showPage(view, { push: false }), 'primary')); }
  }
  function updateInspect() {
    window.__fujimiApp = { view: ui.view, reading: ui.reading, ready: ui.loaded };
  }
  new MutationObserver(() => {
    prepareArticleHeading();
    if (document.documentElement.dataset.nativeReading === 'book') prepareBookReader();
    if (ui.reading === 'book' && document.querySelector('#book-reader')?.hidden) leaveReading();
    if (ui.reading === 'article' && !document.querySelector('#reader-result .article-detail')) leaveReading();
  }).observe(document.querySelector('.content-shell'), { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  window.addEventListener('popstate', () => { const match = location.hash.match(/^#app\/([^/]+)/); if (match && ui.loaded) showPage(match[1], { push: false }); });
  window.addEventListener('fujimi:dictionary-detail-close', () => {
    if (ui.dictionaryReturnView === 'dictionary-favorites') { ui.dictionaryReturnView = ''; history.back(); }
  });
  window.addEventListener('pagehide', () => { stopReferencePreview(); stopDictionarySpeech(); window.FujimiAppSettings?.stop(); clearTimeout(syncRefreshTimer); });
  window.__fujimiAppRoot = root;
  window.__fujimiNavigate = view => showPage(view);
  const nativeHandleBack = window.__fujimiHandleBack;
  window.__fujimiHandleBack = () => {
    if (modal.open) {
      if (modal.querySelector('.voice-catalog-list')) voiceSheet().catch(error => notify(error.message, true));
      else modal.close();
      return true;
    }
    if ((ui.reading || ui.view === 'dictionary' || document.querySelector('dialog[open]')) && nativeHandleBack?.()) return true;
    if (ui.reading === 'book') {
      const reader = document.querySelector('#book-reader');
      const panel = reader?.querySelector('.book-settings-panel:not([hidden]), .book-toc:not([hidden])');
      if (panel) { panel.querySelector('.close-book-settings, :scope > div button')?.click(); return true; }
    }
    if (ui.reading) { leaveReading(); return true; }
    // Page navigation follows the WebView history, as it did before the app shell.
    return false;
  };
  window.addEventListener('fujimi:library-changed', async () => {
    cache.daily = null; cache.days = await api('/api/days');
    if (!ui.reading && ui.view !== 'settings') showPage(ui.view, { push: false });
  });
  async function boot() {
    main.append(node('p', 'loading', '文庫をひらいています。'));
    try {
      [cache.days, cache.mode, cache.voices, cache.catalog, cache.library, cache.stats, cache.dailyConfig, cache.schedule, cache.sources] = await Promise.all([
        api('/api/days'), api('/api/settings/voice-mode'), api('/api/settings/voices'), api('/api/browser-voices'), api('/api/settings/library'), api('/api/dictionary/stats'),
        api('/api/settings/daily-content'), api('/api/settings/daily-schedule'), api('/api/settings/news-sources')]);
      cache.books = (await api('/api/books')).books;
      if (cache.days.length) cache.daily = await api('/api/daily?date=' + encodeURIComponent(cache.days[0]));
      ui.loaded = true;
      if (!location.hash.startsWith('#app/')) history.replaceState({ redesignView: 'daily' }, '', '#app/daily');
      await showPage(location.hash.match(/^#app\/([^/]+)/)?.[1] || 'daily', { push: false });
    } catch (error) { main.replaceChildren(node('div', 'empty', '文庫を開けませんでした：' + error.message)); }
  }
  boot();
})();
