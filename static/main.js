/* Desktop news library: podcast player, application logic, browser initialization. */
/* Cover player for local, audio-only Nikkei media. Native video is the fallback. */
window.decorateNikkeiPodcast = (video, article, descriptor) => {
  if (article.source_key !== 'nikkei' || !descriptor.isLocal || !descriptor.poster) return;
  const upgrade = () => {
    if (!video.isConnected || video.videoWidth || !Number.isFinite(video.duration) || video.duration <= 0) return;
    const player = document.createElement('div');
    player.className = 'web-podcast';
    player.setAttribute('role', 'group');
    player.setAttribute('aria-label', `${article.title} ポッドキャスト`);
    const cover = document.createElement('img');
    cover.className = 'web-podcast-cover';
    cover.src = descriptor.poster;
    cover.alt = '';
    const title = document.createElement('div');
    title.className = 'web-podcast-title';
    title.textContent = article.media_title || article.title;
    const controls = document.createElement('div');
    controls.className = 'web-podcast-controls';
    const icons = {
      play: '<path d="M8 5v14l11-7z"/>',
      pause: '<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>',
      volume: '<path d="M3 9v6h4l5 4V5L7 9zm12-2v10c3-2 3-8 0-10zm3-3v3c4 3 4 7 0 10v3c8-4 8-12 0-16z"/>',
      muted: '<path d="M3 9v6h4l5 4V5L7 9zm12-1 2-2 3 4 3-4 2 2-3 4 3 4-2 2-3-4-3 4-2-2 3-4z"/>',
      fullscreen: '<path d="M3 3h7v3H6v4H3zm11 0h7v7h-3V6h-4zM3 14h3v4h4v3H3zm15 0h3v7h-7v-3h4z"/>',
    };
    const icon = (button, name, label) => {
      button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name]}</svg>`;
      button.setAttribute('aria-label', label);
      button.title = label;
    };
    const button = (name, label) => {
      const element = document.createElement('button');
      element.type = 'button';
      icon(element, name, label);
      return element;
    };
    const play = button('play', 'ポッドキャストを再生');
    const mute = button('volume', 'ミュート');
    const volume = document.createElement('input');
    volume.type = 'range'; volume.min = '0'; volume.max = '1'; volume.step = '.05';
    volume.value = String(video.volume); volume.className = 'web-podcast-volume';
    volume.setAttribute('aria-label', 'ポッドキャストの音量');
    const seek = document.createElement('input');
    seek.type = 'range'; seek.min = '0'; seek.max = String(video.duration); seek.step = '.1';
    seek.className = 'web-podcast-seek';
    seek.setAttribute('aria-label', 'ポッドキャストの再生位置');
    const time = document.createElement('span');
    time.className = 'web-podcast-time';
    const speed = document.createElement('select');
    speed.className = 'web-podcast-speed';
    speed.setAttribute('aria-label', 'ポッドキャストの再生速度');
    [0.75, 1, 1.25, 1.5, 2].forEach(rate => speed.add(new Option(`${rate}x`, String(rate))));
    speed.value = String(video.playbackRate);
    const fullscreen = button('fullscreen', '全画面表示');
    fullscreen.hidden = !document.fullscreenEnabled;
    const status = document.createElement('span');
    status.className = 'web-podcast-status'; status.setAttribute('role', 'status'); status.hidden = true;
    const clock = value => {
      const seconds = Math.max(0, Math.floor(value || 0));
      return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    };
    const update = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      seek.max = String(duration); seek.value = String(video.currentTime);
      seek.disabled = duration <= 0;
      seek.style.setProperty('--podcast-progress', `${duration ? video.currentTime / duration * 100 : 0}%`);
      seek.setAttribute('aria-valuetext', `${clock(video.currentTime)} / ${clock(duration)}`);
      time.textContent = `${clock(video.currentTime)}　/　${clock(duration)}`;
      icon(play, video.paused ? 'play' : 'pause', video.paused ? 'ポッドキャストを再生' : 'ポッドキャストを一時停止');
      icon(mute, video.muted || !video.volume ? 'muted' : 'volume', video.muted ? 'ミュート解除' : 'ミュート');
      mute.setAttribute('aria-pressed', String(video.muted));
      volume.value = String(video.muted ? 0 : video.volume);
      speed.value = String(video.playbackRate);
    };
    const showError = message => { status.textContent = message; status.hidden = false; };
    play.onclick = async () => {
      if (!video.paused) { video.pause(); return; }
      try { await video.play(); status.hidden = true; }
      catch (_) { showError('音声を再生できません。もう一度お試しください。'); }
    };
    mute.onclick = () => { video.muted = !video.muted; };
    volume.oninput = () => { video.muted = false; video.volume = Number(volume.value); };
    seek.oninput = () => { video.currentTime = Number(seek.value); update(); };
    speed.onchange = () => { video.playbackRate = Number(speed.value); };
    fullscreen.onclick = async () => {
      try {
        if (document.fullscreenElement === player) await document.exitFullscreen();
        else await player.requestFullscreen();
      } catch (_) { showError('全画面表示を開始できませんでした。'); }
    };
    const onFullscreen = () => {
      fullscreen.setAttribute('aria-label', document.fullscreenElement === player ? '全画面表示を終了' : '全画面表示');
    };
    ['timeupdate', 'durationchange', 'play', 'pause', 'ended', 'volumechange', 'ratechange'].forEach(event => video.addEventListener(event, update));
    video.addEventListener('error', () => showError('音声ファイルを読み込めませんでした。'));
    document.addEventListener('fullscreenchange', onFullscreen);
    controls.append(seek, play, mute, volume, time, speed, fullscreen);
    player.append(cover, title, status, controls);
    video.replaceWith(player);
    video.controls = false; video.hidden = true;
    player.append(video);
    update();
    // Stop detached playback and release the document listener when leaving the article.
    const cleanup = new MutationObserver(() => {
      if (player.isConnected) return;
      video.pause();
      document.removeEventListener('fullscreenchange', onFullscreen);
      cleanup.disconnect();
    });
    cleanup.observe(document.body, {childList: true, subtree: true});
  };
  if (video.readyState >= 1) upgrade();
  else video.addEventListener('loadedmetadata', upgrade, {once: true});
};

;
const $ = (selector, root = document) => root.querySelector(selector);
const state = { article: null, currentView: "daily", voiceMode: "model", browserVoiceName: "", browserVoiceLabel: "ブラウザー", browserVoices: null, dailyMode: "automatic", editingVoiceId: null, editingBrowserVoice: false, editingSourceId: null, voiceSourceMode: "file", voices: [], newsSources: [], dailyContentTimer: null, dailyTaskTimer: null, dailyRereadTimer: null, rereadTracker: null, importTracker: null, dailyTaskRunning: false, articleAudio: null, browserSpeech: null, hlsPlayers: [], dictionaryReady: false, dictionaryActiveId: "", dictionarySearchTimer: null, dictionaryHistoryTimer: null, dictionarySearchController: null, dictionaryDetailController: null, dictionarySearchSequence: 0, dictionarySpeech: null, dictionarySpeechToken: 0, selectionLookupController: null, selectionLookupToken: 0, selectionLookupQuery: "", selectionLookupRect: null, selectionLookupRange: null, selectionLookupResults: [], selectionLookupActiveId: "", libraryBooks: [], libraryBook: null, libraryChapter: null, librarySort: "recent", libraryLookupChineseTranslations: true, libraryTaskId: null, libraryTaskTimer: null, libraryProgressTimer: null, libraryScrollHandler: null, librarySettingsKeydown: null, libraryTocOutsideClick: null, editingBookId: null };
const BOOK_X_ICON = '<svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 7-5 5"></path><path d="m9.5 7 5 5"></path><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19v15H6.5a2.5 2.5 0 0 0 0 5H19"></path></svg>';
const BOOK_EDIT_ICON = '<svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"></path></svg>';
const BOOK_TOC_ICON = '<svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M5 12h14M5 18h14"></path><path d="M3 6h.01M3 12h.01M3 18h.01"></path></svg>';
const BOOK_SETTINGS_ICON = '<svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10.35 2.5h3.3l.55 2.1 1.4.58 1.9-1.1 2.33 2.34-1.1 1.9.58 1.4 2.1.55v3.3l-2.1.55-.58 1.4 1.1 1.9-2.33 2.34-1.9-1.1-1.4.58-.55 2.1h-3.3l-.55-2.1-1.4-.58-1.9 1.1-2.33-2.34 1.1-1.9-.58-1.4-2.1-.55v-3.3l2.1-.55.58-1.4-1.1-1.9L6.5 4.08l1.9 1.1 1.4-.58z"></path><circle cx="12" cy="12" r="3.1"></circle></svg>';
const DICTIONARY_SOUND_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="dictionary-sound-body" d="M11 5 6 9H3v6h3l5 4V5Z"></path><path class="dictionary-sound-wave dictionary-sound-wave-inner" d="M15.5 8.5a5 5 0 0 1 0 7"></path><path class="dictionary-sound-wave dictionary-sound-wave-outer" d="M18 6a8.5 8.5 0 0 1 0 12"></path></svg>';
const DAILY_DATE_KEY = "fujimi-daily-snapshot-date";
const READER_ARTICLE_KEY = "fujimi-reader-article-id";
const READER_IMPORT_TASK_KEY = "fujimi-reader-import-task-id";
const BOOK_POSITION_KEY = "fujimi-book-position";
if ("scrollRestoration" in history) history.scrollRestoration = "manual";
const PLAYBACK_RATE_KEY = "fujimi-playback-rate";
const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
const DICTIONARY_HISTORY_KEY = "fujimi-dictionary-history";
const DICTIONARY_SEARCH_DELAY = 160;
const DICTIONARY_HISTORY_DELAY = 800;
if (!document.documentElement.dataset.mobileApp) {
  document.documentElement.dataset.mobileApp = window.FujimiMobile ? "true" : "false";
}

const MOBILE_VIEW_META = {
  daily: { kicker: "DAILY EDITION", title: "本日ノニュース", description: "いま起きていることを、ひとつずつ。" },
  reader: { kicker: "READING ROOM", title: "閲読室", description: "ひとつの記事を、ことばから深く読む。" },
  bookmarks: { kicker: "ARCHIVE", title: "收藏", description: "心に留めた記事を、いつでもここに。" },
  library: { kicker: "LIGHT NOVEL LIBRARY", title: "書架", description: "物語の続きを、いつでもここから。" },
  dictionary: { kicker: "LOCAL DICTIONARY", title: "辞書", description: "ひとつの言葉から、世界をひらく。" },
  settings: { kicker: "PREFERENCES", title: "設置", description: "読む時間を、自分らしく整える。" },
};
let mobileNavPreviousFocus = null;
let mobileSyncPollTimer = null;
let mobileNodeStatus = null;
let mobileWindowsCheck = null;
let deviceSyncPollTimer = null;
let deviceSyncStatus = null;
const redesignedReadingUi = document.documentElement.dataset.redesignApp === "true";

function syncMobileViewHeading(view) {
  const meta = MOBILE_VIEW_META[view] || { kicker: "PRIVATE NEWS LIBRARY", title: "富士見新聞文庫", description: "ニュースを、深く読む。" };
  const kicker = document.querySelector("#mobile-current-kicker");
  const title = document.querySelector("#mobile-current-view");
  const description = document.querySelector("#mobile-current-description");
  if (kicker) kicker.textContent = meta.kicker;
  if (title) title.textContent = meta.title;
  if (description) description.textContent = meta.description;
}

function isMobileDrawerLayout() {
  return document.documentElement.dataset.mobileApp === "true" && window.matchMedia("(max-width: 900px)").matches;
}

function setMobileNavOpen(open, { restoreFocus = true } = {}) {
  const sidebar = document.querySelector(".sidebar");
  const toggle = document.querySelector("#mobile-nav-toggle");
  const scrim = document.querySelector("#mobile-nav-scrim");
  if (!sidebar || !toggle || !scrim) return false;
  const shouldOpen = Boolean(open && isMobileDrawerLayout());
  const wasOpen = document.documentElement.dataset.mobileNavOpen === "true";
  document.documentElement.dataset.mobileNavOpen = String(shouldOpen);
  toggle.setAttribute("aria-expanded", String(shouldOpen));
  sidebar.setAttribute("aria-hidden", String(isMobileDrawerLayout() && !shouldOpen));
  sidebar.inert = isMobileDrawerLayout() && !shouldOpen;
  scrim.hidden = !shouldOpen;
  if (shouldOpen) {
    mobileNavPreviousFocus = document.activeElement;
    requestAnimationFrame(() => (sidebar.querySelector(".nav-button.active") || sidebar.querySelector(".nav-button"))?.focus());
  } else if (wasOpen && restoreFocus && mobileNavPreviousFocus instanceof HTMLElement) {
    mobileNavPreviousFocus.focus();
  }
  return wasOpen && !shouldOpen;
}

function syncMobileNavigationLayout() {
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;
  if (isMobileDrawerLayout()) {
    setMobileNavOpen(false, { restoreFocus: false });
    document.querySelectorAll(".settings-disclosure").forEach(disclosure => {
      if (disclosure.dataset.mobileInitialized !== "true") disclosure.open = false;
      disclosure.dataset.mobileInitialized = "true";
    });
  } else {
    document.documentElement.dataset.mobileNavOpen = "false";
    sidebar.removeAttribute("aria-hidden");
    sidebar.inert = false;
    const scrim = document.querySelector("#mobile-nav-scrim");
    if (scrim) scrim.hidden = true;
    document.querySelectorAll(".settings-disclosure").forEach(disclosure => {
      disclosure.open = true;
      delete disclosure.dataset.mobileInitialized;
    });
  }
}

function finishMobileAppBoot() {
  if (document.documentElement.dataset.mobileApp !== "true") {
    document.documentElement.classList.remove("mobile-app-booting");
    return;
  }
  requestAnimationFrame(() => {
    requestAnimationFrame(() => document.documentElement.classList.remove("mobile-app-booting"));
  });
}

function initializeSettingsLayout() {
  // The Android card layout must not replace the established PC settings page.
  $("#settings-view").classList.toggle("settings-design-a", Boolean(window.FujimiMobile));
  if (!window.FujimiMobile) {
    const actions = document.createElement("div");
    actions.className = "panel-actions";
    actions.append($("#active-voice-badge"), $("#add-voice"));
    $(".voice-panel > .panel-heading").append(actions);
    $(".daily-content-settings").append($("#daily-content-summary"));
    document.querySelectorAll(".settings-section-number, .voice-settings-actions, .daily-source-stat")
      .forEach(element => { element.hidden = true; });
    return;
  }
  if ($("#source-settings-disclosure")) return;
  $("#settings-view .section-head")?.classList.add("settings-page-head");
  // Keep the selected voice visible; source controls retain their existing disclosure.
  $("#settings-system-speech").hidden = typeof window.FujimiMobile.openSpeechSettings !== "function";

  const sourceList = $("#source-list");
  const sourceHeading = sourceList?.previousElementSibling;
  const sourceCount = $("#source-count");
  const addSource = $("#add-source");
  if (sourceList && sourceHeading?.classList.contains("settings-subheading") && sourceCount && addSource) {
    const disclosure = document.createElement("details");
    disclosure.id = "source-settings-disclosure";
    disclosure.className = "settings-disclosure";
    const summary = document.createElement("summary");
    summary.innerHTML = "<span><strong>ニュースソース</strong><small>设置每个来源的最低收录数</small></span>";
    summary.append(sourceCount);
    const action = document.createElement("div");
    action.className = "settings-disclosure-action";
    action.append(addSource);
    disclosure.append(summary, action, sourceList);
    sourceHeading.replaceWith(disclosure);
  }
}

window.__fujimiCloseMobileNav = () => setMobileNavOpen(false);
window.__fujimiCloseMobileDictionaryDetail = () => {
  if (!isMobileDrawerLayout()) return false;
  const view = $("#dictionary-view");
  if (!view?.classList.contains("dictionary-detail-open")) return false;
  closeMobileDictionaryDetail();
  return true;
};
window.__fujimiHandleBack = () => {
  if (closeAndroidSelect()) return true;
  if (redesignedReadingUi && $("#selection-lookup").classList.contains("is-mobile-article") && (!$("#selection-lookup").hidden || state.selectionLookupController)) {
    if ($("#selection-lookup").classList.contains("is-mobile-expanded")) {
      $("#selection-lookup").classList.remove("is-mobile-expanded");
      renderMobileLookupCard(mobileArticleLookupWord);
      return true;
    }
    hideSelectionLookup({ clearSelection: true, restoreFocus: true });
    return true;
  }
  const playerMenu = redesignedReadingUi ? document.querySelector('.audio-rate-menu:not([hidden]), .audio-listen-menu:not([hidden])') : null;
  if (playerMenu) {
    playerMenu.hidden = true;
    const trigger = playerMenu.closest('.article-audio-player').querySelector(playerMenu.classList.contains('audio-rate-menu') ? '.audio-rate-toggle' : '.audio-listen-toggle');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus({ preventScroll: true });
    return true;
  }
  const dialog = document.querySelector("dialog[open]");
  if (dialog) { dialog.close(); return true; }
  if (setMobileNavOpen(false)) return true;
  if (window.__fujimiCloseMobileDictionaryDetail()) return true;
  const menu = document.querySelector("details.voice-actions-menu[open], details.source-actions-menu[open]");
  if (menu) { menu.open = false; return true; }
  return false;
};
window.__fujimiRefreshNativeSettings = () => {
  if (state.currentView === "settings") {
    loadDesktopSettings();
    loadVoices();
  }
};
window.__fujimiNativeNotice = message => toast(String(message || "操作失败"), true);

// Keep the original select as the form/API source of truth. Only the actual
// Android bridge gets a page-owned list; mobile Web and desktop retain selects.
let activeAndroidSelect = null;
function closeAndroidSelect(restoreFocus = true) {
  const field = activeAndroidSelect;
  if (!field) return false;
  activeAndroidSelect = null;
  if (typeof field.list.hidePopover === 'function' && field.list.matches(':popover-open')) field.list.hidePopover();
  field.list.remove();
  field.trigger.setAttribute('aria-expanded', 'false');
  field.trigger.removeAttribute('aria-activedescendant');
  if (restoreFocus && field.trigger.isConnected && !field.trigger.disabled) field.trigger.focus({ preventScroll: true });
  return true;
}

function initializeAndroidSelects() {
  if (!window.FujimiMobile) return;
  document.documentElement.dataset.androidApp = 'true';
  const fields = new Map();
  const trackedOptions = new WeakSet();
  let sequence = 0;
  const enabled = (select, option) => !select.matches(':disabled') && !option.disabled && !option.parentElement?.disabled && !option.hidden;
  const position = field => {
    const rect = field.trigger.getBoundingClientRect();
    if (!rect.width || !rect.height || rect.bottom <= 0 || rect.top >= innerHeight) { closeAndroidSelect(false); return; }
    const below = Math.max(0, innerHeight - rect.bottom - 12);
    const above = Math.max(0, rect.top - 12);
    const upward = below < Math.min(field.list.scrollHeight, 192) && above > below;
    const height = Math.min(320, upward ? above : below);
    field.list.style.width = `${rect.width}px`;
    field.list.style.maxHeight = `${height}px`;
    field.list.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - rect.width - 8))}px`;
    field.list.style.top = `${upward ? rect.top - Math.min(field.list.scrollHeight, height) - 4 : rect.bottom + 4}px`;
  };
  const highlight = (field, index) => {
    field.active = index;
    [...field.list.children].forEach((row, i) => row.classList.toggle('is-active', i === index));
    const row = field.list.children[index];
    if (!row) { field.trigger.removeAttribute('aria-activedescendant'); return; }
    field.trigger.setAttribute('aria-activedescendant', row.id);
    if (row.offsetTop < field.list.scrollTop) field.list.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > field.list.scrollTop + field.list.clientHeight) field.list.scrollTop = row.offsetTop + row.offsetHeight - field.list.clientHeight;
  };
  const render = field => {
    const { select, list } = field;
    list.replaceChildren(...[...select.options].map((option, index) => {
      const row = document.createElement('div');
      row.id = `${list.id}-${index}`;
      row.className = 'android-select-option';
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(option.selected));
      row.setAttribute('aria-disabled', String(!enabled(select, option)));
      row.hidden = option.hidden;
      row.textContent = option.label;
      row.onclick = () => {
        if (!enabled(select, option)) return;
        const changed = select.selectedIndex !== index;
        select.selectedIndex = index;
        closeAndroidSelect();
        if (changed) {
          select.dispatchEvent(new Event('input', { bubbles: true }));
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
      };
      return row;
    }));
    position(field);
    const index = enabled(select, select.options[field.active] || {}) ? field.active : [...select.options].findIndex(option => enabled(select, option));
    highlight(field, index);
  };
  const sync = field => {
    const { select, trigger } = field;
    [...select.options].forEach(option => {
      if (trackedOptions.has(option)) return;
      trackedOptions.add(option);
      const descriptor = Object.getOwnPropertyDescriptor(HTMLOptionElement.prototype, 'selected');
      Object.defineProperty(option, 'selected', { configurable: true, get() { return descriptor.get.call(this); }, set(value) {
        descriptor.set.call(this, value);
        const owner = fields.get(this.closest('select'));
        if (owner) { owner.active = owner.select.selectedIndex; sync(owner); }
      } });
    });
    const text = select.selectedOptions[0]?.label || '请选择';
    if (trigger.textContent !== text) trigger.textContent = text;
    trigger.disabled = select.matches(':disabled');
    trigger.hidden = select.hidden;
    trigger.setAttribute('aria-required', String(select.required));
    if (activeAndroidSelect === field) {
      if (trigger.disabled || select.hidden || !trigger.getClientRects().length) closeAndroidSelect(false);
      else render(field);
    }
  };
  const open = field => {
    sync(field);
    if (field.trigger.disabled || field.trigger.hidden) return;
    if (activeAndroidSelect === field) { closeAndroidSelect(); return; }
    closeAndroidSelect(false);
    field.active = field.select.selectedIndex;
    (field.select.closest('dialog[open]') || document.body).append(field.list);
    activeAndroidSelect = field;
    field.trigger.setAttribute('aria-expanded', 'true');
    if (typeof field.list.showPopover === 'function') field.list.showPopover();
    render(field);
    field.trigger.focus({ preventScroll: true });
  };
  const enhance = select => {
    if (fields.has(select) || select.multiple || select.size > 1) return;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'android-select-trigger';
    trigger.dataset.androidSelect = select.id || `android-select-${++sequence}`;
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const label = select.labels?.[0]?.cloneNode(true);
    label?.querySelectorAll('select, button').forEach(node => node.remove());
    if (select.hasAttribute('aria-labelledby')) trigger.setAttribute('aria-labelledby', select.getAttribute('aria-labelledby'));
    else trigger.setAttribute('aria-label', select.getAttribute('aria-label') || label?.textContent.trim() || '选择');
    const list = document.createElement('div');
    list.id = `android-select-list-${++sequence}`;
    list.className = 'android-select-list';
    // Listbox rows use the combobox's focus; clicking a disabled row must not
    // strand keyboard navigation on the document. Touch scrolling stays native.
    list.onmousedown = event => event.preventDefault();
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', trigger.getAttribute('aria-label') || '选择');
    if (typeof list.showPopover === 'function') list.setAttribute('popover', 'manual');
    trigger.setAttribute('aria-controls', list.id);
    const field = { select, trigger, list, active: select.selectedIndex };
    fields.set(select, field);
    select.classList.add('android-native-select');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;
    select.after(trigger);
    // Programmatic value changes don't emit mutation/change events. Delegate to
    // the native accessors so assignments used by existing loaders stay intact.
    ['value', 'selectedIndex'].forEach(property => {
      const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, property);
      Object.defineProperty(select, property, { configurable: true, get() { return descriptor.get.call(this); }, set(value) { descriptor.set.call(this, value); field.active = this.selectedIndex; sync(field); } });
    });
    select.focus = options => trigger.focus(options);
    select.addEventListener('change', () => sync(field));
    select.addEventListener('input', () => sync(field));
    trigger.onclick = () => open(field);
    trigger.onkeydown = event => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' ', 'Escape', 'Tab'].includes(event.key)) return;
      if (event.key === 'Escape' || event.key === 'Tab') {
        if (activeAndroidSelect === field) { if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); } closeAndroidSelect(event.key === 'Escape'); }
        return;
      }
      event.preventDefault();
      if (activeAndroidSelect !== field) { open(field); return; }
      if (event.key === 'Enter' || event.key === ' ') { field.list.children[field.active]?.click(); return; }
      const indices = [...select.options].map((option, i) => enabled(select, option) ? i : -1).filter(i => i >= 0);
      const current = indices.indexOf(field.active);
      const next = event.key === 'Home' ? indices[0] : event.key === 'End' ? indices.at(-1) : indices[Math.max(0, Math.min(indices.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)))];
      highlight(field, next ?? -1);
    };
    sync(field);
  };
  document.querySelectorAll('select').forEach(enhance);
  const observer = new MutationObserver(records => {
    const changed = new Set();
    records.forEach(record => {
      const select = record.target instanceof Element ? record.target.closest('select') : record.target.parentElement?.closest('select');
      if (select && fields.has(select)) changed.add(fields.get(select));
      if (record.type === 'attributes' && record.target instanceof Element && !select) {
        record.target.querySelectorAll('select').forEach(node => { if (fields.has(node)) changed.add(fields.get(node)); });
      }
      record.addedNodes.forEach(node => {
        if (!(node instanceof Element)) return;
        if (node.matches('select')) enhance(node);
        node.querySelectorAll('select').forEach(enhance);
      });
    });
    fields.forEach((field, select) => {
      if (!select.isConnected) {
        if (activeAndroidSelect === field) closeAndroidSelect(false);
        field.trigger.remove(); field.list.remove(); fields.delete(select);
      } else if (select.nextElementSibling !== field.trigger) select.after(field.trigger);
    });
    changed.forEach(sync);
  });
  observer.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
  document.addEventListener('pointerdown', event => {
    if (activeAndroidSelect && !activeAndroidSelect.trigger.contains(event.target) && !activeAndroidSelect.list.contains(event.target)) closeAndroidSelect(false);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && activeAndroidSelect) { event.preventDefault(); event.stopImmediatePropagation(); closeAndroidSelect(); }
  }, true);
  document.addEventListener('cancel', event => {
    if (activeAndroidSelect) { event.preventDefault(); closeAndroidSelect(); }
  }, true);
  document.addEventListener('close', () => { if (activeAndroidSelect && !activeAndroidSelect.trigger.getClientRects().length) closeAndroidSelect(false); }, true);
  document.addEventListener('reset', () => queueMicrotask(() => fields.forEach(sync)), true);
  document.addEventListener('scroll', event => { if (activeAndroidSelect && event.target !== activeAndroidSelect.list) position(activeAndroidSelect); }, true);
  window.addEventListener('resize', () => { if (activeAndroidSelect) position(activeAndroidSelect); });
}
initializeAndroidSelects();
let hlsLibraryPromise = null;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (window.FujimiMobile?.request) {
    const multipart = options.body instanceof FormData ? await serializeMobileFormData(options.body) : null;
    const body = options.body == null || multipart ? null : String(options.body);
    const result = await mobileApiRequest(path, options.method || "GET", body, multipart);
    const parsed = result.body ? JSON.parse(result.body) : null;
    if (result.status < 200 || result.status >= 300) {
      if (result.status === 503) {
        const queued = queueMobileOfflineChange(path, options);
        if (queued) return queued;
      }
      const error = new Error(parsed?.detail || "请求失败");
      error.status = result.status;
      throw error;
    }
    return parsed;
  }
  const response = await fetch(path, { ...options, headers });
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const error = new Error(body.detail || "请求失败");
    error.status = response.status;
    throw error;
  }
  return body;
}

function queueMobileOfflineChange(path, options = {}) {
  if (!window.FujimiMobile?.queueChange) return null;
  const method = String(options.method || "GET").toUpperCase();
  const body = options.body ? JSON.parse(String(options.body)) : {};
  let entity = "";
  let action = options.mobileChangeAction || (method === "DELETE" ? "delete" : "upsert");
  let payload = body;
  let match = path.match(/^\/api\/books\/(\d+)\/progress$/);
  if (match && method === "PUT") {
    entity = "book_progress";
    payload = { ...body, book_id: Number(match[1]) };
  }
  match = path.match(/^\/api\/books\/(\d+)\/chapters\/(\d+)\/bookmarks$/);
  if (match && method === "POST") {
    entity = "book_bookmark";
    payload = { ...body, book_id: Number(match[1]), chapter_id: Number(match[2]) };
  }
  match = path.match(/^\/api\/articles\/(\d+)\/bookmarks$/);
  if (match && (method === "POST" || method === "DELETE")) {
    entity = "article_bookmark";
    payload = { ...body, article_id: Number(match[1]) };
  }
  if (!entity) return null;
  const operationId = window.FujimiMobile.queueChange(entity, action, JSON.stringify(payload));
  if (!operationId) return null;
  if (entity === "book_bookmark") return { queued: true, bookmarked: action !== "delete" };
  if (entity === "article_bookmark") return { queued: true, bookmarked: action !== "delete", ok: true };
  return { queued: true, ...payload };
}

const mobileCallbacks = new Map();
const mobileTtsCallbacks = new Map();
let mobileCallbackSequence = 0;
window.__fujimiMobileResolve = (callbackId, status, body) => {
  const callback = mobileCallbacks.get(callbackId);
  if (!callback) return;
  mobileCallbacks.delete(callbackId);
  callback({ status: Number(status) || 500, body: String(body || "") });
};
window.__fujimiTtsEvent = (utteranceId, event) => {
  const callback = mobileTtsCallbacks.get(utteranceId);
  if (!callback) return;
  callback(event);
  if (["done", "error", "stop"].includes(event)) mobileTtsCallbacks.delete(utteranceId);
};

function mobileSpeak(text, rate, callback, voiceName = "") {
  const id = `tts-${Date.now()}-${++mobileCallbackSequence}`;
  mobileTtsCallbacks.set(id, callback);
  if (window.FujimiMobile.speakWithVoice) window.FujimiMobile.speakWithVoice(String(text || ""), Number(rate) || 1, id, edgeVoiceId(voiceName));
  else window.FujimiMobile.speak(String(text || ""), Number(rate) || 1, id);
  return id;
}

function edgeVoiceId(voiceName = "") {
  const value = String(voiceName || "");
  if (value === "ja-JP-KeitaNeural" || /(?:Keita|圭太)/i.test(value)) return "ja-JP-KeitaNeural";
  if (value === "ja-JP-NanamiNeural" || /(?:Nanami|七海)/i.test(value)) return "ja-JP-NanamiNeural";
  return value;
}

function stopSpeechEngine() {
  if (window.FujimiMobile?.stopSpeaking) window.FujimiMobile.stopSpeaking();
  else if ("speechSynthesis" in window) speechSynthesis.cancel();
}

function mobileApiRequest(path, method, body, multipart = null) {
  return new Promise((resolve, reject) => {
    const callbackId = `mobile-${++mobileCallbackSequence}`;
    const timer = window.setTimeout(() => {
      mobileCallbacks.delete(callbackId);
      reject(new Error("本机请求超时，请重试。"));
    }, /^\/api\/articles\/\d+\/edge-tts$/.test(path) || path.startsWith("/api/pc-speech/") ? 600000 : path === "/api/settings/voice-file" ? 300000 : path.startsWith("/api/dictionary/") ? 120000 : 30000);
    mobileCallbacks.set(callbackId, result => { window.clearTimeout(timer); resolve(result); });
    try { window.FujimiMobile.request(JSON.stringify({ path, method, body, multipart }), callbackId); }
    catch (_error) {
      window.clearTimeout(timer);
      mobileCallbacks.delete(callbackId);
      reject(new Error("无法调用 Android 本机接口。"));
    }
  });
}

async function serializeMobileFormData(formData) {
  const entries = [];
  for (const [name, value] of formData.entries()) {
    if (value instanceof File) {
      const bytes = new Uint8Array(await value.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 32768) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
      }
      entries.push({ name, kind: "file", filename: value.name, type: value.type || "application/octet-stream", data: btoa(binary) });
    } else {
      entries.push({ name, kind: "text", value: String(value) });
    }
  }
  return entries;
}

function notice(message, isError = false) {
  const element = $("#notice");
  element.textContent = message;
  element.className = isError ? "error" : "";
}

function readerImportNotice(message = "", { isError = false, processing = false, progress = 0, total = 0, count = "" } = {}) {
  const element = $("#reader-import-notice");
  const progressValue = Math.max(0, Number(progress) || 0);
  const totalValue = Math.max(0, Number(total) || 0);
  $(".reader-import-message", element).textContent = message;
  $(".reader-import-count", element).textContent = count || (totalValue ? `${progressValue}/${totalValue}` : "");
  const bar = $(".reader-import-progress", element);
  bar.hidden = !processing || totalValue <= 0;
  bar.max = Math.max(1, totalValue);
  bar.value = Math.min(progressValue, Math.max(1, totalValue));
  element.className = `reader-import-notice${isError ? " is-error" : ""}${processing ? " is-processing" : ""}`;
  element.hidden = !message;
}

function rememberReaderArticle(article) {
  try {
    sessionStorage.setItem(READER_ARTICLE_KEY, JSON.stringify({
      id: Number(article.id),
      bookmark: Boolean(article.bookmark_context),
    }));
  } catch (_error) { /* Session storage is optional. */ }
}

function forgetReaderArticle() {
  try { sessionStorage.removeItem(READER_ARTICLE_KEY); } catch (_error) { /* Session storage is optional. */ }
}

function rememberedReaderArticle() {
  try {
    const stored = sessionStorage.getItem(READER_ARTICLE_KEY) || "";
    if (!stored) return null;
    if (stored.startsWith("{")) {
      const value = JSON.parse(stored);
      return Number.isInteger(Number(value.id)) && Number(value.id) > 0
        ? { id: Number(value.id), bookmark: Boolean(value.bookmark) }
        : null;
    }
    const id = Number.parseInt(stored, 10);
    return Number.isInteger(id) && id > 0 ? { id, bookmark: false } : null;
  } catch (_error) {
    return null;
  }
}

function articleApiPath(article, suffix = "") {
  const base = article.bookmark_context ? `/api/bookmarks/${article.id}` : `/api/articles/${article.id}`;
  return `${base}${suffix}`;
}

function rememberReaderImportTask(taskId) {
  try { sessionStorage.setItem(READER_IMPORT_TASK_KEY, taskId); } catch (_error) { /* Session storage is optional. */ }
}

function forgetReaderImportTask() {
  try { sessionStorage.removeItem(READER_IMPORT_TASK_KEY); } catch (_error) { /* Session storage is optional. */ }
}

function rememberedReaderImportTaskId() {
  try { return sessionStorage.getItem(READER_IMPORT_TASK_KEY) || ""; } catch (_error) { return ""; }
}

function rememberDailyDate(date) {
  try {
    if (date) sessionStorage.setItem(DAILY_DATE_KEY, date);
    else sessionStorage.removeItem(DAILY_DATE_KEY);
  } catch (_error) { /* Session storage is optional. */ }
}

function rememberedDailyDate() {
  try { return sessionStorage.getItem(DAILY_DATE_KEY) || ""; } catch (_error) { return ""; }
}

function toast(message, isError = false) {
  const region = $("#toast-region");
  const item = document.createElement("div");
  item.className = `toast${isError ? " is-error" : ""}`;
  item.textContent = message;
  region.append(item);
  requestAnimationFrame(() => item.classList.add("is-visible"));
  setTimeout(() => {
    item.classList.add("is-leaving");
    setTimeout(() => item.remove(), 220);
  }, 2600);
  return item;
}

function panelNotice(selector, message, isError = false) {
  const element = $(selector);
  element.textContent = message;
  element.className = `panel-notice${isError ? " error" : ""}`;
}

function panelError(selector, message = "") {
  const element = $(selector);
  element.textContent = message;
  element.hidden = !message;
}

let mobileArticleLookupTrigger = null;
let mobileArticleLookupWord = null;
// The native word card owns a transparent full-screen click layer behind its content.
const mobileLookupBackdrop = redesignedReadingUi ? document.createElement("div") : null;
if (mobileLookupBackdrop) {
  mobileLookupBackdrop.id = "mobile-lookup-backdrop";
  mobileLookupBackdrop.hidden = true;
  mobileLookupBackdrop.setAttribute("aria-hidden", "true");
  $("#selection-lookup").before(mobileLookupBackdrop);
  mobileLookupBackdrop.addEventListener("pointerdown", event => event.stopPropagation());
  mobileLookupBackdrop.addEventListener("click", event => {
    event.stopPropagation();
    // A second tap while the first query is pending does not start or cancel a query.
    if ($("#selection-lookup").hidden && state.selectionLookupController) return;
    hideSelectionLookup({ clearSelection: true });
  });
}

async function prepareMobileReadingLookup(root, contentSelector, textSelector) {
  if (!redesignedReadingUi) return;
  const content = root.querySelector(contentSelector);
  content.id = contentSelector === ".parallel" ? "moji-article-content" : "moji-book-content";
  content.dataset.mojiLookupRoot = "";
  const mark = (element, text) => {
    element.dataset.lookupQuery = text;
    element.tabIndex = 0;
    element.setAttribute("role", "button");
    element.setAttribute("aria-label", `「${text}」を調べる`);
  };
  const texts = [];
  content.querySelectorAll(textSelector).forEach(paragraph => {
    paragraph.removeAttribute("role");
    paragraph.removeAttribute("tabindex");
    paragraph.removeAttribute("aria-label");
    paragraph.closest(".paragraph").classList.add("moji-article-srt");
    paragraph.querySelectorAll("ruby").forEach(ruby => {
      if (ruby.closest("a, button") || ruby.parentElement.closest("ruby")) return;
      if (!ruby.querySelector("rb")) {
        const base = document.createElement("rb");
        Array.from(ruby.childNodes).filter(child => !child.matches?.("rt, rp")).forEach(child => base.append(child));
        ruby.prepend(base);
      }
      mark(ruby, ruby.querySelector("rb").textContent);
    });
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT, {
      acceptNode: text => text.parentElement.closest("ruby, rt, rp, a, button, .moji-toolkit-org") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    while (walker.nextNode()) texts.push(walker.currentNode);
  });
  await new Promise(requestAnimationFrame);
  if (!content.isConnected) return;
  window.MojiArticleLookup.mount(content, (text, word) => {
    // ArticleWebView.A strips the parenthesized suffix before calling the word dialog.
    const query = text.split("(")[0];
    if (query && word) showSelectionLookup(query, word.getBoundingClientRect(), null, word);
  }, () => root.querySelector(".article-audio-player")?.dataset.playing === "true");
  content.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key) || !event.target.matches("[data-lookup-query]")) return;
    event.preventDefault(); event.target.click();
  });
  try {
    const payload = await api("/api/dictionary/tokenize", { method: "POST", body: JSON.stringify({ texts: texts.map(text => text.textContent) }) });
    if (!content.isConnected) return;
    texts.forEach((text, index) => {
      const fragment = document.createDocumentFragment();
      (payload.tokens[index] || []).forEach(surface => {
        if (!/[\p{L}\p{N}]/u.test(surface)) { fragment.append(document.createTextNode(surface)); return; }
        const word = document.createElement("span"); word.className = "moji-toolkit-org";
        word.textContent = surface; mark(word, surface); fragment.append(word);
      });
      text.replaceWith(fragment);
    });
  } catch (error) { if (content.isConnected) toast(error.message, true); }
}

function selectionTextWithoutRuby(selection) {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return "";
  const fragment = selection.getRangeAt(0).cloneContents();
  fragment.querySelectorAll("rt, rp").forEach(node => node.remove());
  const wrapper = document.createElement("div");
  wrapper.append(fragment);
  // EPUB markup can split a word with regular, full-width, or zero-width whitespace.
  return (wrapper.textContent || "").replace(/[\s\u200B\u2060\uFEFF]+/gu, "").trim();
}

function selectionLookupEligible(selection, eventTarget) {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return false;
  if (!(eventTarget instanceof Element)) return false;
  if ($("#selection-lookup").contains(eventTarget)) return false;
  if (eventTarget.closest("button, a, input, textarea, select, [contenteditable='true'], dialog")) return false;
  const ancestor = selection.getRangeAt(0).commonAncestorContainer;
  const element = ancestor.nodeType === Node.ELEMENT_NODE ? ancestor : ancestor.parentElement;
  if (!state.libraryLookupChineseTranslations && element?.closest(".book-block-zh")) return false;
  return Boolean(element?.closest(".article-detail, .dictionary-detail, .news-card, .book-chapter-body"));
}

function hideSelectionLookup({ clearSelection = false, restoreFocus = false } = {}) {
  const trigger = mobileArticleLookupTrigger;
  mobileArticleLookupTrigger = null;
  mobileArticleLookupWord = null;
  if (state.selectionLookupController) state.selectionLookupController.abort();
  state.selectionLookupController = null;
  state.selectionLookupToken += 1;
  state.selectionLookupQuery = "";
  state.selectionLookupRect = null;
  state.selectionLookupRange = null;
  state.selectionLookupResults = [];
  state.selectionLookupActiveId = "";
  const popover = $("#selection-lookup");
  popover.classList.remove("is-detail", "is-size-locked", "is-mobile-article", "is-mobile-expanded");
  $("#selection-lookup-close").textContent = "×";
  delete popover.dataset.singleResult;
  popover.style.height = "";
  popover.hidden = true;
  popover.removeAttribute("aria-modal");
  if (mobileLookupBackdrop) mobileLookupBackdrop.hidden = true;
  if (clearSelection) window.getSelection()?.removeAllRanges();
  if (restoreFocus && trigger?.isConnected) trigger.focus({ preventScroll: true });
}

function positionSelectionLookup() {
  const popover = $("#selection-lookup");
  const rect = state.selectionLookupRect;
  if (popover.hidden || !rect) return;
  if (popover.classList.contains("is-mobile-article")) return;
  const margin = 12;
  const gap = 9;
  const width = Math.min(360, window.innerWidth - margin * 2);
  popover.style.width = `${width}px`;
  const left = Math.max(margin, Math.min(window.innerWidth - width - margin, rect.left + rect.width / 2 - width / 2));
  const height = popover.offsetHeight;
  let top = rect.bottom + gap;
  if (top + height > window.innerHeight - margin) top = Math.max(margin, rect.top - height - gap);
  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

function repositionSelectionLookup() {
  const popover = $("#selection-lookup");
  if (popover.hidden) return;
  const range = state.selectionLookupRange;
  if (range) {
    const rangeRect = range.getBoundingClientRect();
    state.selectionLookupRect = {
      left: rangeRect.left,
      right: rangeRect.right,
      top: rangeRect.top,
      bottom: rangeRect.bottom,
      width: rangeRect.width,
      height: rangeRect.height,
    };
  }
  positionSelectionLookup();
}

function selectionLookupResult(result) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "selection-lookup-result";
  const heading = document.createElement("span");
  const spell = document.createElement("strong");
  spell.textContent = result.spell || "";
  const pronunciation = document.createElement("small");
  pronunciation.textContent = [result.pron, result.accent].filter(Boolean).join(" ");
  heading.append(spell, pronunciation);
  const excerpt = document.createElement("p");
  excerpt.textContent = result.excerpt || "释义未收录";
  button.append(heading, excerpt);
  button.onclick = () => loadSelectionLookupDetail(result.id);
  return button;
}

function renderSelectionLookupResults(results = state.selectionLookupResults) {
  $("#selection-lookup").classList.remove("is-detail");
  const target = $("#selection-lookup-results");
  if (results.length) {
    target.replaceChildren(...results.map(selectionLookupResult));
  } else {
    const empty = document.createElement("p");
    empty.className = "selection-lookup-status";
    empty.textContent = "該当する語が見つかりません。";
    target.replaceChildren(empty);
  }
  requestAnimationFrame(positionSelectionLookup);
}

function mobileLookupIcon(name) {
  const image = document.createElement("img");
  image.src = `/static/lookup_assets/${name}.png`;
  image.alt = "";
  return image;
}

function renderMobileLookupCard(word) {
  mobileArticleLookupWord = word;
  const panel = $("#selection-lookup");
  panel.classList.add("is-detail");
  $("#selection-lookup-close").replaceChildren(mobileLookupIcon("nav_icon_close"));
  const card = document.createElement("article");
  card.className = "selection-lookup-detail moji-lookup-card";
  const title = document.createElement("header");
  title.className = "moji-lookup-title";
  const spell = document.createElement("strong"); spell.textContent = word.spell;
  const pron = word.pron || (word.sections || []).find(section => section.pron)?.pron
    || (mobileArticleLookupTrigger?.dataset.lookupQuery === word.spell
      ? [...mobileArticleLookupTrigger.querySelectorAll("rt")].map(rt => rt.textContent).join("") : "");
  const reading = document.createElement("span");
  reading.textContent = pron ? ` | ${pron}` : "";
  const accent = document.createElement("span");
  accent.textContent = String(word.accent ?? "").replace(/\d+/g, value => Number(value) === 0 ? "⓪" : Number(value) <= 20 ? String.fromCodePoint(0x2460 + Number(value) - 1) : value);
  title.append(spell, reading, accent);
  const originalCard = word.moji_card;
  if (originalCard) title.textContent = originalCard.title;
  const meta = document.createElement("div"); meta.className = "moji-lookup-meta";
  const part = document.createElement("span"); part.className = "moji-lookup-part";
  part.textContent = [...new Set((word.details || []).flatMap(item => item.partOfSpeech || []))].join("・");
  if (originalCard) part.textContent = originalCard.partOfSpeech;
  if (originalCard?.partOfSpeechColor) part.style.setProperty('--moji-part-color', '#' + (originalCard.partOfSpeechColor >>> 0).toString(16).padStart(8, '0').slice(2));
  part.hidden = !part.textContent;
  const tools = document.createElement("div"); tools.className = "moji-lookup-tools";
  const favorite = document.createElement("button"); favorite.type = "button"; favorite.className = "moji-lookup-favorite";
  const key = "fujimi-dictionary-favorites";
  let favorites;
  const updateFavorite = () => {
    const saved = favorites.includes(String(word.id));
    favorite.setAttribute("aria-pressed", String(saved));
    favorite.setAttribute("aria-label", saved ? "取消收藏词语" : "收藏词语");
    favorite.replaceChildren(mobileLookupIcon(saved ? "ic_common_collected" : "ic_common_collect"));
  };
  try {
    favorites = JSON.parse(localStorage.getItem(key) || "[]");
    if (!Array.isArray(favorites)) throw new Error("收藏记录无法读取");
    updateFavorite();
  } catch (_) { favorite.disabled = true; favorite.setAttribute("aria-label", "收藏记录无法读取"); favorite.append(mobileLookupIcon("ic_common_collect")); }
  favorite.onclick = () => {
    const next = favorites.includes(String(word.id)) ? favorites.filter(id => id !== String(word.id)) : [...favorites, String(word.id)];
    try { localStorage.setItem(key, JSON.stringify(next)); favorites = next; updateFavorite(); }
    catch (_) { toast("收藏保存失败。", true); }
  };
  const speech = dictionarySpeechButton(originalCard?.speechText || pron || word.spell, "单词发音");
  speech.replaceChildren(mobileLookupIcon("ic_voice_high_red"));
  tools.append(favorite, speech); meta.append(part, tools);
  const meaning = document.createElement("div"); meaning.className = "moji-lookup-meaning"; meaning.tabIndex = 0;
  // Moji's WordExpandView joins Chinese and Japanese Subdetails; examples stay in the detail view.
  const meanings = dictionaryDefinitionGroups(word.definitions || []).map(group => {
    const zh = group.zh.map(item => item.title || "").join("\n");
    const ja = group.ja.map(item => item.title || "").join("\n");
    return zh + (ja ? `（${ja}）` : "");
  }).filter(Boolean);
  meaning.textContent = meanings.join("\n\n") || word.excerpt || "释义未收录";
  if (originalCard) meaning.textContent = originalCard.meaning;
  const actions = document.createElement("footer"); actions.className = "moji-lookup-actions";
  const action = (text, icon, run) => {
    const button = document.createElement("button"); button.type = "button";
    button.append(mobileLookupIcon(icon), document.createTextNode(text)); button.onclick = run; return button;
  };
  actions.append(action("详情", "ic_common_display", () => {
    panel.classList.add("is-mobile-expanded");
    $("#selection-lookup-close").textContent = "×";
    renderSelectionLookupDetail(word);
  }), action("MOJi辞書", "ic_common_search", () => {
    if (!window.FujimiMobile?.openMojiDictionary?.(state.selectionLookupQuery)) toast("未能打开 MOJi辞書，请确认已安装。", true);
  }));
  card.append(title, meta, meaning, actions);
  $("#selection-lookup-results").replaceChildren(card);
}

function renderSelectionLookupDetail(word) {
  if ($("#selection-lookup").classList.contains("is-mobile-article") && !$("#selection-lookup").classList.contains("is-mobile-expanded")) return renderMobileLookupCard(word);
  $("#selection-lookup").classList.add("is-detail");
  const target = $("#selection-lookup-results");
  const article = document.createElement("article");
  article.className = "selection-lookup-detail";
  const back = document.createElement("button");
  back.type = "button";
  back.className = "selection-lookup-back";
  back.textContent = "← 検索結果";
  back.onclick = returnSelectionLookupResults;
  if ($("#selection-lookup").classList.contains("is-mobile-expanded")) {
    back.textContent = "返回";
    back.onclick = () => { $("#selection-lookup").classList.remove("is-mobile-expanded"); renderMobileLookupCard(word); };
  }
  const header = document.createElement("header");
  const title = document.createElement("strong");
  title.textContent = word.spell || "";
  const pronunciation = document.createElement("small");
  const readings = [...new Set((word.sections || []).map(section => section.pron).filter(Boolean))];
  pronunciation.textContent = [readings.join(" / ") || word.pron, word.accent].filter(Boolean).join(" ");
  const titleLine = document.createElement("div");
  titleLine.className = "selection-lookup-word-title";
  const spokenWord = readings[0] || word.pron || word.spell;
  titleLine.append(title, pronunciation);
  header.append(titleLine, dictionarySpeechButton(spokenWord, "単語を読む"));
  article.append(back, header);

  const sections = Array.isArray(word.sections) ? word.sections : [];
  if (sections.length) {
    const structured = document.createElement("div");
    structured.className = "selection-lookup-structured";
    appendDictionarySections(structured, sections);
    article.append(structured);
  } else {
    const definitions = dictionaryDefinitionGroups(word.definitions);
    definitions.forEach((group, index) => {
      const row = document.createElement("section");
      row.className = "dictionary-sense";
      const number = document.createElement("span");
      number.className = "dictionary-sense-number";
      number.textContent = String(index + 1);
      const content = document.createElement("div");
      content.className = "dictionary-sense-content";
      group.zh.forEach(item => appendDictionaryDefinition(content, item, "zh"));
      group.ja.forEach(item => appendDictionaryDefinition(content, item, "ja"));
      row.append(number, content);
      article.append(row);
    });
    if ((word.examples || []).length) {
      const examples = document.createElement("section");
      examples.className = "dictionary-examples";
      const heading = document.createElement("h4");
      heading.textContent = "例文";
      examples.append(heading);
      appendDictionaryExamples(examples, word.examples);
      article.append(examples);
    }
  }
  if (!sections.length && !(word.definitions || []).length && !(word.examples || []).length) {
    const excerpt = document.createElement("p");
    excerpt.className = "selection-lookup-status";
    excerpt.textContent = word.excerpt || "释义未收录";
    article.append(excerpt);
  }
  if (word.etymology) {
    const etymology = document.createElement("section");
    etymology.className = "dictionary-etymology";
    const heading = document.createElement("h4");
    heading.textContent = "語源";
    const text = document.createElement("p");
    text.textContent = word.etymology;
    etymology.append(heading, text);
    article.append(etymology);
  }
  target.replaceChildren(article);
  requestAnimationFrame(positionSelectionLookup);
}

function lockSelectionLookupSize() {
  const popover = $("#selection-lookup");
  if (popover.classList.contains("is-mobile-article")) return;
  if (popover.hidden || popover.classList.contains("is-size-locked")) return;
  const height = Math.min(popover.getBoundingClientRect().height, window.innerHeight - 24);
  popover.style.height = `${Math.round(height)}px`;
  popover.classList.add("is-size-locked");
}

function returnSelectionLookupResults() {
  if (state.selectionLookupController) state.selectionLookupController.abort();
  state.selectionLookupController = null;
  state.selectionLookupToken += 1;
  state.selectionLookupActiveId = "";
  renderSelectionLookupResults();
}

async function loadSelectionLookupDetail(id) {
  if (state.selectionLookupController) state.selectionLookupController.abort();
  lockSelectionLookupSize();
  const token = ++state.selectionLookupToken;
  const controller = new AbortController();
  state.selectionLookupController = controller;
  state.selectionLookupActiveId = id;
  $("#selection-lookup").classList.add("is-detail");
  const target = $("#selection-lookup-results");
  const loading = document.createElement("p");
  loading.className = "selection-lookup-status";
  loading.textContent = "词条を読み込んでいます…";
  target.replaceChildren(loading);
  try {
    const word = await api(`/api/dictionary/words/${encodeURIComponent(id)}`, { signal: controller.signal });
    if (token === state.selectionLookupToken) renderSelectionLookupDetail(word);
  } catch (error) {
    if (error.name === "AbortError" || token !== state.selectionLookupToken) return;
    const failed = document.createElement("div");
    failed.className = "selection-lookup-detail-error";
    const back = document.createElement("button");
    back.type = "button";
    back.className = "selection-lookup-back";
    back.textContent = "← 検索結果";
    back.onclick = returnSelectionLookupResults;
    const message = document.createElement("p");
    message.className = "selection-lookup-status error";
    message.textContent = error.message;
    failed.append(back, message);
    target.replaceChildren(failed);
  } finally {
    if (state.selectionLookupController === controller) state.selectionLookupController = null;
    if (token === state.selectionLookupToken) requestAnimationFrame(positionSelectionLookup);
  }
}

async function openSelectionLookupInDictionary(id = "") {
  const query = state.selectionLookupQuery;
  const activeId = id || state.selectionLookupActiveId;
  hideSelectionLookup({ clearSelection: true });
  if (!query) return;
  await showView("dictionary");
  await searchDictionary(query, { syncInput: true, remember: "now" });
  if (activeId) await loadDictionaryDetail(activeId);
}

async function showSelectionLookup(query, rect, range = null, mobileTrigger = null) {
  if (mobileTrigger && mobileLookupBackdrop && !mobileLookupBackdrop.hidden) return;
  hideSelectionLookup();
  mobileArticleLookupTrigger = mobileTrigger;
  $("#selection-lookup").classList.toggle("is-mobile-article", Boolean(mobileTrigger));
  if (mobileTrigger && mobileLookupBackdrop) {
    mobileLookupBackdrop.hidden = false;
    $("#selection-lookup").setAttribute("aria-modal", "true");
  }
  state.selectionLookupQuery = query;
  state.selectionLookupRect = rect;
  state.selectionLookupRange = range;
  state.selectionLookupResults = [];
  state.selectionLookupActiveId = "";
  const token = ++state.selectionLookupToken;
  const controller = new AbortController();
  state.selectionLookupController = controller;
  $("#selection-lookup-query").textContent = query;
  const resultsElement = $("#selection-lookup-results");
  if (!mobileTrigger) {
    const loading = document.createElement("p");
    loading.className = "selection-lookup-status";
    loading.textContent = "検索中…";
    resultsElement.replaceChildren(loading);
    $("#selection-lookup").hidden = false;
    requestAnimationFrame(positionSelectionLookup);
  }
  try {
    if (mobileTrigger) {
      const word = await api(`/api/dictionary/clickDetail?q=${encodeURIComponent(query)}`, { signal: controller.signal });
      if (token !== state.selectionLookupToken) return;
      if (word.moji_card === null) { hideSelectionLookup(); return; }
      state.selectionLookupActiveId = word.id;
      state.selectionLookupResults = [word];
      $("#selection-lookup").dataset.singleResult = "true";
      renderMobileLookupCard(word);
      $("#selection-lookup").hidden = false;
      return;
    }
    const payload = await api(`/api/dictionary/search?q=${encodeURIComponent(query)}`, { signal: controller.signal });
    if (token !== state.selectionLookupToken) return;
    const results = (payload.results || []).slice(0, 4);
    state.selectionLookupResults = results;
    renderSelectionLookupResults(results);
  } catch (error) {
    if (error.name === "AbortError" || token !== state.selectionLookupToken) return;
    if (mobileTrigger) {
      hideSelectionLookup();
      if (error.status !== 404) toast(error.message, true);
      return;
    }
    const failed = document.createElement("p");
    failed.className = "selection-lookup-status error";
    failed.textContent = error.message;
    resultsElement.replaceChildren(failed);
  } finally {
    if (state.selectionLookupController === controller) state.selectionLookupController = null;
    if (token === state.selectionLookupToken) requestAnimationFrame(positionSelectionLookup);
  }
}

function handleSelectionLookup(event) {
  if (event.button !== 0 || $("#selection-lookup").contains(event.target)) return;
  if (event.target === mobileLookupBackdrop) return;
  if (redesignedReadingUi && event.target.closest("[data-moji-lookup-root]")) return;
  setTimeout(() => {
    const selection = window.getSelection();
    if (!selectionLookupEligible(selection, event.target)) {
      hideSelectionLookup();
      return;
    }
    const query = selectionTextWithoutRuby(selection);
    if (!query || query.length > 60 || !/[\p{L}\p{N}]/u.test(query)) {
      hideSelectionLookup();
      return;
    }
    const rangeRect = selection.getRangeAt(0).getBoundingClientRect();
    if (!rangeRect.width && !rangeRect.height) return;
    showSelectionLookup(query, {
      left: rangeRect.left,
      right: rangeRect.right,
      top: rangeRect.top,
      bottom: rangeRect.bottom,
      width: rangeRect.width,
      height: rangeRect.height,
    }, selection.getRangeAt(0).cloneRange());
  }, 0);
}

function escapeText(value = "") {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function formatPublishedAt(value) {
  if (!value) return "发布时间未知";
  const published = new Date(value);
  if (Number.isNaN(published.getTime())) return value;
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(published);
}

function isVisible(article) {
  return article.status === "ready";
}

function stopRereadTracking() {
  if (state.rereadTracker) state.rereadTracker.cancelled = true;
  state.rereadTracker = null;
}

function destroyHlsPlayers() {
  state.hlsPlayers.forEach(player => player.destroy());
  state.hlsPlayers = [];
}

function mobileMediaUrl(value, fallbackPrefix = "") {
  if (!value) return "";
  const remote = value.startsWith("http://") || value.startsWith("https://");
  const fallback = remote || value.startsWith("/") ? value : `${fallbackPrefix}${value}`;
  if (remote || !window.FujimiMobile?.resolveMediaUrl) return fallback;
  return window.FujimiMobile.resolveMediaUrl(value)
    || window.FujimiMobile.resolveMediaUrl(fallback)
    || fallback;
}

function nhkVideoDescriptor(value) {
  const descriptor = { source: value, poster: "", isHls: false, isEmbed: false, isLocal: false };
  if (!value.startsWith("http://") && !value.startsWith("https://") && !value.startsWith("/")) {
    descriptor.source = mobileMediaUrl(value, "/api/media/");
    descriptor.isLocal = true;
    return descriptor;
  }
  if (value.startsWith("/api/")) {
    descriptor.source = mobileMediaUrl(value);
    descriptor.isLocal = true;
    descriptor.isHls = descriptor.source.toLowerCase().split("?", 1)[0].endsWith(".m3u8");
    return descriptor;
  }
  try {
    const parsed = new URL(value, window.location.href);
    if (parsed.hostname === "news.web.nhk" && parsed.pathname.includes("/player/index.html")) {
      descriptor.source = parsed.searchParams.get("mrurl") || value;
      const poster = parsed.searchParams.get("mrposter");
      if (poster) descriptor.poster = new URL(poster, "https://news.web.nhk").href;
    } else if (parsed.hostname === "players.brightcove.net" && parsed.pathname.endsWith("/index.html")) {
      descriptor.isEmbed = true;
    }
  } catch (_error) {
    if (!value.startsWith("/")) descriptor.source = `/api/media/${value}`;
  }
  descriptor.isHls = descriptor.source.toLowerCase().split("?", 1)[0].endsWith(".m3u8");
  return descriptor;
}

function loadHlsLibrary() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (hlsLibraryPromise) return hlsLibraryPromise;
  hlsLibraryPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://news.web.nhk/assets/players/npl/v3/libs/hls.js/hls.js";
    script.onload = () => window.Hls ? resolve(window.Hls) : reject(new Error("HLS player unavailable"));
    script.onerror = () => reject(new Error("HLS player failed to load"));
    document.head.append(script);
  });
  return hlsLibraryPromise;
}

function attachVideoSource(video, descriptor) {
  if (descriptor.poster) video.poster = descriptor.poster;
  if (!descriptor.isHls) {
    video.src = descriptor.source;
    return;
  }
  loadHlsLibrary().then(Hls => {
    if (!video.isConnected) return;
    if (!Hls.isSupported()) {
      video.src = descriptor.source;
      return;
    }
    const player = new Hls();
    state.hlsPlayers.push(player);
    player.loadSource(descriptor.source);
    player.attachMedia(video);
  }).catch(() => {
    video.src = descriptor.source;
    video.dataset.mediaError = "true";
  });
}

function resetReaderRoom({ forget = true } = {}) {
  stopRereadTracking();
  stopArticlePlayback(true);
  destroyHlsPlayers();
  state.article = null;
  $("#reader-result").replaceChildren();
  $("#reader-view").classList.remove("is-reading");
  $("#reader-import-workspace").hidden = false;
  readerImportNotice();
  if (forget) {
    forgetReaderArticle();
    forgetReaderImportTask();
    if (state.importTracker) state.importTracker.cancelled = true;
  }
  notice("");
}

function exitReaderRoom() {
  resetReaderRoom();
  toast("已退出阅读");
}

async function restoreReaderArticle() {
  if (state.article) {
    if (!redesignedReadingUi) { resumeArticlePlayback(); return true; }
    const root = $("#reader-result .article-detail");
    if (root?.classList.contains("has-audio-player") && !resumeArticlePlayback(root)) {
      resetReaderAudio(root);
      setupArticleAudio(state.article, root);
    }
    return true;
  }
  const remembered = rememberedReaderArticle();
  if (!remembered) return false;
  readerImportNotice("前回の記事を開いています…", { processing: true });
  try {
    const article = await api(remembered.bookmark ? `/api/bookmarks/${remembered.id}` : `/api/articles/${remembered.id}`);
    openArticle(article, $("#reader-result"));
    return true;
  } catch (error) {
    forgetReaderArticle();
    if (error.status === 404) {
      readerImportNotice("気になる記事から、新しい発見を。");
    } else {
      readerImportNotice(error.message, { isError: true });
    }
    return false;
  }
}

async function trackReaderImport(taskId) {
  if (!taskId) return false;
  if (state.importTracker?.taskId === taskId && !state.importTracker.cancelled) return true;
  if (state.importTracker) state.importTracker.cancelled = true;
  const tracker = { taskId, cancelled: false };
  state.importTracker = tracker;
  const form = $("#import-form");
  const button = $("button[type='submit']", form);
  button.disabled = true;
  form.setAttribute("aria-busy", "true");
  try {
    while (!tracker.cancelled) {
      const task = await api(`/api/import/tasks/${taskId}`);
      if (tracker.cancelled) return false;
      if (task.status === "failed") throw new Error(task.message || "处理失败");
      if (task.status === "completed") {
        forgetReaderImportTask();
        readerImportNotice();
        openArticle(task.article, $("#reader-result"));
        toast(isVisible(task.article) ? "导入处理已完成" : "处理未完成，新闻正文暂不显示", !isVisible(task.article));
        return true;
      }
      const completed = Number(task.completed || 0);
      const total = Number(task.total || 0);
      readerImportNotice(task.message || "記事を処理しています…", {
        processing: true,
        progress: completed,
        total,
        count: total ? `${completed}/${total}${task.stage === "tts" ? " 段" : ""}` : "",
      });
      await new Promise(resolve => setTimeout(resolve, 350));
    }
  } catch (error) {
    forgetReaderImportTask();
    readerImportNotice(error.message, { isError: true });
  } finally {
    if (state.importTracker === tracker) state.importTracker = null;
    button.disabled = false;
    form.removeAttribute("aria-busy");
  }
  return false;
}

function restoreReaderImportTask() {
  const taskId = rememberedReaderImportTaskId();
  if (taskId) trackReaderImport(taskId);
}

async function showView(view, { historyMode = "push", resetReader = false, restoreReader = true } = {}) {
  setMobileNavOpen(false, { restoreFocus: false });
  hideSelectionLookup();
  if (state.currentView === "library" && view !== "library" && state.libraryChapter && !$("#book-reader").hidden) {
    await persistBookProgress($("#book-reader"), state.libraryChapter);
    if (state.libraryProgressTimer) {
      clearTimeout(state.libraryProgressTimer);
      state.libraryProgressTimer = null;
    }
  }
  if (view !== "dictionary") stopDictionarySpeech();
  if (redesignedReadingUi ? (view !== state.currentView || (view !== "reader" && view !== "library")) : (view !== "reader" && view !== "library")) {
    suspendArticlePlayback();
    stopRereadTracking();
  }
  if (view !== "daily" && state.dailyRereadTimer) {
    clearTimeout(state.dailyRereadTimer);
    state.dailyRereadTimer = null;
  }
  if (view === "reader" && resetReader) resetReaderRoom({ forget: false });
  state.currentView = view;
  syncMobileViewHeading(view);
  document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  document.querySelectorAll(".view").forEach(section => { section.hidden = section.id !== `${view}-view`; });
  const existingLibraryRoute = libraryRoute();
  const rememberedBookRoute = state.libraryChapter?.book?.id && state.libraryChapter?.chapter?.id
    ? `#library/book/${state.libraryChapter.book.id}/chapter/${state.libraryChapter.chapter.id}`
    : "";
  const routeHash = view === "library" ? (existingLibraryRoute ? location.hash : rememberedBookRoute || "#library") : `#${view}`;
  if (historyMode === "push" && (history.state?.view !== view || location.hash !== routeHash)) history.pushState({ view }, "", routeHash);
  if (historyMode === "replace") history.replaceState({ view }, "", routeHash);
  if (view === "reader" && (!redesignedReadingUi || restoreReader)) {
    const restored = await restoreReaderArticle();
    if (!restored) restoreReaderImportTask();
  }
  if (view === "daily") await loadDaily();
  if (view === "bookmarks") await loadBookmarks();
  if (view === "library") await loadLibrary();
  if (view === "dictionary") await loadDictionary();
  if (view === "settings") {
    notice("");
    await Promise.all([loadVoices(), loadNewsSources(), loadDailySettings(), loadLibrarySettings(), loadDesktopSettings(), taskStatus()]);
  }
}

function dictionaryHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(DICTIONARY_HISTORY_KEY) || "[]");
    return Array.isArray(value) ? value.filter(item => typeof item === "string" && item.trim()).slice(0, 8) : [];
  } catch (_error) {
    return [];
  }
}

function rememberDictionaryQuery(query) {
  const history = [query, ...dictionaryHistory().filter(item => item !== query)].slice(0, 8);
  try { localStorage.setItem(DICTIONARY_HISTORY_KEY, JSON.stringify(history)); } catch (_error) { /* Local storage is optional. */ }
  renderDictionaryHistory();
}

function forgetDictionaryQuery(query) {
  const history = dictionaryHistory().filter(item => item !== query);
  try { localStorage.setItem(DICTIONARY_HISTORY_KEY, JSON.stringify(history)); } catch (_error) { /* Local storage is optional. */ }
  renderDictionaryHistory();
}

function rememberDictionaryQueryLater(query) {
  if (state.dictionaryHistoryTimer) clearTimeout(state.dictionaryHistoryTimer);
  state.dictionaryHistoryTimer = setTimeout(() => {
    state.dictionaryHistoryTimer = null;
    if ($("#dictionary-query").value.trim() === query) rememberDictionaryQuery(query);
  }, DICTIONARY_HISTORY_DELAY);
}

function setDictionaryHistoryOpen(open) {
  $("#dictionary-history-panel").hidden = !open;
  $("#dictionary-query").setAttribute("aria-expanded", String(open));
}

function dictionaryHistoryItem(query) {
  const row = document.createElement("div");
  row.className = "dictionary-history-item";
  const search = document.createElement("button");
  search.type = "button";
  search.className = "dictionary-history-query";
  search.textContent = query;
  search.onclick = () => {
    setDictionaryHistoryOpen(false);
    searchDictionary(query, { remember: "now" });
  };
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "dictionary-history-remove";
  remove.setAttribute("aria-label", `検索履歴から「${query}」を削除`);
  remove.title = "履歴から削除";
  remove.textContent = "×";
  remove.onclick = () => {
    forgetDictionaryQuery(query);
    requestAnimationFrame(() => {
      $("#dictionary-query").focus();
      setDictionaryHistoryOpen(true);
    });
  };
  row.append(search, remove);
  return row;
}

function renderDictionaryHistory() {
  const history = dictionaryHistory();
  const target = $("#dictionary-history");
  target.replaceChildren(...history.map(dictionaryHistoryItem));
  $("#dictionary-history-empty").hidden = history.length > 0;
}

function resetDictionarySpeechButton(button) {
  if (!button) return;
  button.classList.remove("is-speaking");
  button.setAttribute("aria-label", button.dataset.playLabel || "朗读");
  button.title = button.dataset.playLabel || "朗读";
}

function stopDictionarySpeech() {
  state.dictionarySpeechToken += 1;
  const active = state.dictionarySpeech;
  active?.abort?.abort();
  active?.audio?.pause();
  if (active?.url) URL.revokeObjectURL(active.url);
  stopSpeechEngine();
  resetDictionarySpeechButton(active?.button);
  state.dictionarySpeech = null;
}

async function synthesizeDesktopOnlineSpeech(text, voice, signal) {
  const response = await fetch('/api/desktop/edge-speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: voice.id }),
    signal,
  });
  if (!response.ok) throw new Error('在线声线暂不可用，请检查网络后重试。');
  return response.blob();
}

async function synthesizeLocalBrowserSpeech(text, voice, signal) {
  const response = await fetch('/api/browser-speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice: voice.id }),
    signal,
  });
  if (!response.ok) {
    let detail = '本地声线暂不可用，请检查模型文件和 Tokyo 运行环境。';
    try { detail = (await response.json()).detail || detail; } catch (_) { /* keep generic detail */ }
    throw new Error(detail);
  }
  return response.blob();
}

async function speakDictionaryText(text, button) {
  const spokenText = String(text || "").trim();
  if (!spokenText) return;
  if (!window.FujimiMobile?.speak && !("speechSynthesis" in window)
      && !(typeof localBrowserVoice === "function" && localBrowserVoice(state.browserVoiceName))) return toast("当前设备不支持语音朗读。", true);
  if (state.dictionarySpeech?.button === button) {
    stopDictionarySpeech();
    return;
  }
  stopDictionarySpeech();
  const token = ++state.dictionarySpeechToken;
  try {
    const mode = await api("/api/settings/voice-mode");
    if (token !== state.dictionarySpeechToken) return;
    applyBrowserVoiceSettings(mode);
  } catch (_error) {
    if (token !== state.dictionarySpeechToken) return;
  }
  if (window.FujimiMobile?.speak) {
    const dictionaryVoice = edgeVoiceId(state.browserVoiceName);
    // Dictionary speech uses the configured browser voice independently of article/reference mode.
    if (localBrowserVoice(dictionaryVoice)?.saved_audio_only) return toast("当前系统声线仅可播放已保存音频；词典即时朗读请选择圭太或七海。", true);
    button.classList.add("is-speaking");
    button.setAttribute("aria-label", "停止朗读");
    button.title = "停止朗读";
    state.dictionarySpeech = { button, token, utterance: null };
    mobileSpeak(spokenText, 1, event => {
      if (state.dictionarySpeech?.token !== token) return;
      if (event === "error") toast(state.browserVoiceName === 'android:system' ? "系统朗读失败，请检查手机文字转语音设置及日语音声。" : "Edge 在线朗读失败，请检查网络后重试。", true);
      if (["done", "error", "stop"].includes(event)) {
        resetDictionarySpeechButton(button);
        state.dictionarySpeech = null;
      }
    }, dictionaryVoice);
    return;
  }
  const voice = await resolveJapaneseBrowserVoice({ persistDefault: true });
  if (token !== state.dictionarySpeechToken) return;
  if (!voice) {
    toast("未检测到可用的 Edge 在线声线，已阻止使用未知系统声线朗读日文。请检查网络后重试。", true);
    return;
  }
  if (voice.local) {
    if (spokenText.length > 4000) {
      toast('词典朗读文本过长，请缩短后重试。', true);
      return;
    }
    const abort = new AbortController();
    state.dictionarySpeech = { button, token, abort, audio: null, url: null };
    button.classList.add('is-speaking');
    button.setAttribute('aria-label', '停止朗读');
    button.title = '停止朗读';
    try {
      const blob = await synthesizeLocalBrowserSpeech(spokenText, voice, abort.signal);
      if (token !== state.dictionarySpeechToken) return;
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      state.dictionarySpeech.audio = audio;
      state.dictionarySpeech.url = url;
      audio.onended = () => { if (token === state.dictionarySpeechToken) stopDictionarySpeech(); };
      audio.onerror = () => {
        if (token !== state.dictionarySpeechToken) return;
        stopDictionarySpeech();
        toast('本地声线音频播放失败。', true);
      };
      await audio.play();
    } catch (error) {
      if (token !== state.dictionarySpeechToken && abort.signal.aborted) return;
      stopDictionarySpeech();
      toast(error.message || '本地声线合成失败。', true);
    }
    return;
  }
  if (voice.id) {
    if (spokenText.length > 4000) {
      toast('词典朗读文本过长，请缩短后重试。', true);
      return;
    }
    const abort = new AbortController();
    state.dictionarySpeech = { button, token, abort, audio: null, url: null };
    button.classList.add('is-speaking');
    button.setAttribute('aria-label', '停止朗读');
    button.title = '停止朗读';
    try {
      const blob = await synthesizeDesktopOnlineSpeech(spokenText, voice, abort.signal);
      if (token !== state.dictionarySpeechToken) return;
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      state.dictionarySpeech.audio = audio;
      state.dictionarySpeech.url = url;
      audio.onended = () => { if (token === state.dictionarySpeechToken) stopDictionarySpeech(); };
      audio.onerror = () => {
        if (token === state.dictionarySpeechToken) {
          stopDictionarySpeech();
          toast('在线朗读音频播放失败。', true);
        }
      };
      await audio.play();
    } catch (error) {
      if (token === state.dictionarySpeechToken) {
        stopDictionarySpeech();
        toast(error.message || '在线朗读失败。', true);
      }
    }
    return;
  }
  const utterance = new SpeechSynthesisUtterance(spokenText);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  utterance.rate = 1;
  const finish = () => {
    if (state.dictionarySpeech?.token !== token) return;
    resetDictionarySpeechButton(button);
    state.dictionarySpeech = null;
  };
  utterance.onstart = () => {
    if (token !== state.dictionarySpeechToken) return;
    button.classList.add("is-speaking");
    button.setAttribute("aria-label", "停止朗读");
    button.title = "停止朗读";
  };
  utterance.onend = finish;
  utterance.onerror = event => {
    const isCurrentSpeech = state.dictionarySpeech?.token === token && token === state.dictionarySpeechToken;
    finish();
    if (isCurrentSpeech && !["canceled", "interrupted"].includes(event.error)) {
      toast("浏览器朗读失败，请检查系统语音设置。", true);
    }
  };
  state.dictionarySpeech = { button, token, utterance };
  speechSynthesis.speak(utterance);
}

function dictionarySpeechButton(text, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "dictionary-speech-button";
  button.dataset.playLabel = label;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.innerHTML = DICTIONARY_SOUND_ICON;
  button.addEventListener("click", () => speakDictionaryText(text, button));
  return button;
}

function dictionaryDefinitionGroups(definitions = []) {
  const groups = new Map();
  definitions.forEach(definition => {
    const key = definition.detailsId || definition.id;
    const group = groups.get(key) || { zh: [], ja: [] };
    if (definition.lang === "zh-CN") group.zh.push(definition);
    else group.ja.push(definition);
    groups.set(key, group);
  });
  return [...groups.values()];
}

function appendDictionaryDefinition(target, definition, language) {
  const wrapper = document.createElement("div");
  wrapper.className = `dictionary-definition dictionary-definition-${language}`;
  const title = document.createElement("p");
  title.textContent = definition.title;
  wrapper.append(title);
  if (definition.context) {
    const context = document.createElement("small");
    context.textContent = definition.context;
    wrapper.append(context);
  }
  if ((definition.conjunctions || []).length) {
    const forms = document.createElement("small");
    forms.className = "dictionary-conjugations";
    forms.textContent = definition.conjunctions.join(" · ");
    wrapper.append(forms);
  }
  target.append(wrapper);
}

function appendDictionaryMeaning(target, sense) {
  const meaning = document.createElement("p");
  meaning.className = "dictionary-sense-meaning";
  const parts = Array.isArray(sense.meaningParts) ? sense.meaningParts : [];
  if (parts.length) {
    parts.forEach(part => {
      const element = document.createElement(part.kind === "emphasis" ? "strong" : "span");
      if (part.kind === "label") element.className = "dictionary-meaning-label";
      if (part.kind === "white-square" || part.kind === "black-square") {
        element.className = `dictionary-meaning-badge dictionary-meaning-badge-${part.kind}`;
      }
      element.textContent = part.text;
      meaning.append(element);
    });
  } else {
    meaning.textContent = sense.meaning || "";
  }
  if (meaning.textContent) target.append(meaning);
}

function appendDictionaryExamples(target, examples = []) {
  if (!examples.length) return;
  const list = document.createElement("div");
  list.className = "dictionary-sense-examples";
  examples.forEach(example => {
    const row = document.createElement("div");
    row.className = "dictionary-example";
    if (example.title) {
      const line = document.createElement("div");
      line.className = "dictionary-example-line";
      const japanese = document.createElement("p");
      japanese.className = "dictionary-example-ja";
      japanese.textContent = example.title;
      line.append(japanese, dictionarySpeechButton(example.title, "例文を読む"));
      row.append(line);
    }
    if (example.notationTitle) {
      const chinese = document.createElement("p");
      chinese.className = "dictionary-example-zh";
      chinese.textContent = example.notationTitle;
      row.append(chinese);
    }
    list.append(row);
  });
  target.append(list);
}

function appendDictionaryNotes(target, notes = []) {
  notes.forEach(note => {
    const row = document.createElement("aside");
    row.className = "dictionary-note";
    const kind = document.createElement("span");
    kind.textContent = note.kind || "補足";
    const text = document.createElement("p");
    text.textContent = note.text;
    row.append(kind, text);
    target.append(row);
  });
}

function appendDictionarySenses(target, senses = [], { compact = false } = {}) {
  if (!senses.length) return;
  const list = document.createElement("div");
  list.className = `dictionary-senses${compact ? " dictionary-senses-compact" : ""}`;
  senses.forEach(sense => {
    const row = document.createElement("section");
    row.className = `dictionary-sense${sense.number ? "" : " dictionary-sense-unnumbered"}`;
    if (sense.number) {
      const number = document.createElement("span");
      number.className = "dictionary-sense-number";
      number.textContent = sense.number;
      row.append(number);
    }
    const content = document.createElement("div");
    content.className = "dictionary-sense-content";
    appendDictionaryMeaning(content, sense);
    appendDictionaryExamples(content, sense.examples || []);
    appendDictionaryNotes(content, sense.notes || []);
    row.append(content);
    list.append(row);
  });
  target.append(list);
}

function appendDictionarySubheads(target, subheads = []) {
  if (!subheads.length) return;
  const wrapper = document.createElement("section");
  wrapper.className = "dictionary-subheads";
  const heading = document.createElement("h4");
  const types = [...new Set(subheads.map(item => item.type).filter(Boolean))];
  heading.textContent = types.join("・") || "複合語";
  wrapper.append(heading);
  subheads.forEach(subhead => {
    const article = document.createElement("article");
    article.className = "dictionary-subhead";
    const subheadHeader = document.createElement("header");
    const word = document.createElement("h5");
    word.textContent = subhead.word;
    subheadHeader.append(word, dictionarySpeechButton(subhead.word, "複合語を読む"));
    if (subhead.type) {
      const type = document.createElement("span");
      type.textContent = subhead.type;
      subheadHeader.prepend(type);
    }
    article.append(subheadHeader);
    appendDictionarySenses(article, subhead.senses || [], { compact: true });
    appendDictionaryNotes(article, subhead.notes || []);
    wrapper.append(article);
  });
  target.append(wrapper);
}

function appendDictionarySections(target, sections = []) {
  const wrapper = document.createElement("div");
  wrapper.className = "dictionary-entry-sections";
  sections.forEach((section, index) => {
    const sectionElement = document.createElement("section");
    sectionElement.className = "dictionary-entry-section";
    if (sections.length > 1) {
      const heading = document.createElement("header");
      const word = document.createElement("h4");
      word.textContent = section.word;
      const pron = document.createElement("span");
      pron.textContent = section.pron;
      heading.append(word, pron);
      sectionElement.append(heading);
    } else if (index === 0 && section.pron) {
      sectionElement.dataset.pron = section.pron;
    }
    appendDictionarySenses(sectionElement, section.senses || []);
    appendDictionaryNotes(sectionElement, section.notes || []);
    appendDictionarySubheads(sectionElement, section.subheads || []);
    wrapper.append(sectionElement);
  });
  target.append(wrapper);
}

function renderDictionaryDetail(word) {
  stopDictionarySpeech();
  const target = $("#dictionary-detail");
  const sections = Array.isArray(word.sections) ? word.sections : [];
  const header = document.createElement("header");
  header.className = "dictionary-word-header";
  const reading = document.createElement("p");
  reading.className = "dictionary-word-reading";
  const readings = [...new Set(sections.map(section => section.pron).filter(Boolean))];
  reading.textContent = [readings.join(" / ") || word.pron, word.accent].filter(Boolean).join(" ");
  const title = document.createElement("h3");
  title.textContent = word.spell;
  const titleLine = document.createElement("div");
  titleLine.className = "dictionary-word-title";
  const spokenWord = readings[0] || word.pron || word.spell;
  titleLine.append(title, dictionarySpeechButton(spokenWord, "単語を読む"));
  const meta = document.createElement("p");
  meta.className = "dictionary-word-meta";
  const tags = String(word.tags || "").split("#").map(item => item.trim()).filter(Boolean);
  meta.textContent = [word.romaji, ...tags].filter(Boolean).join(" · ");
  header.append(reading, titleLine);
  if (meta.textContent) header.append(meta);
  const back = document.createElement("button");
  back.type = "button";
  back.className = "dictionary-detail-back quiet";
  back.textContent = "検索結果";
  back.setAttribute("aria-label", "検索結果へ戻る");
  back.title = "検索結果へ戻る";
  back.onclick = () => closeMobileDictionaryDetail();
  const context = document.createElement("div");
  context.className = "dictionary-detail-context";
  const source = document.createElement("span");
  source.className = "dictionary-detail-source";
  source.textContent = $("#dictionary-stats").textContent;
  context.append(source, back);
  const nodes = [context, header];
  if (sections.length) {
    const structured = document.createElement("div");
    appendDictionarySections(structured, sections);
    nodes.push(structured);
  } else if (word.excerpt) {
    const excerpt = document.createElement("p");
    excerpt.className = "dictionary-word-excerpt";
    excerpt.textContent = word.excerpt;
    nodes.push(excerpt);
  }
  const groups = sections.length ? [] : dictionaryDefinitionGroups(word.definitions);
  if (groups.length) {
    const senses = document.createElement("div");
    senses.className = "dictionary-senses";
    groups.forEach((group, index) => {
      const sense = document.createElement("section");
      sense.className = "dictionary-sense";
      const number = document.createElement("span");
      number.textContent = String(index + 1);
      const content = document.createElement("div");
      group.zh.forEach(item => appendDictionaryDefinition(content, item, "zh"));
      group.ja.forEach(item => appendDictionaryDefinition(content, item, "ja"));
      sense.append(number, content);
      senses.append(sense);
    });
    nodes.push(senses);
  }
  if ((word.details || []).length) {
    const grammar = document.createElement("p");
    grammar.className = "dictionary-grammar";
    grammar.textContent = word.details
      .flatMap(item => item.partOfSpeech || [])
      .map(value => String(value).trim())
      .filter(value => value && !/^\d+$/u.test(value))
      .join(" · ");
    if (grammar.textContent) nodes.push(grammar);
  }
  if (!sections.length && (word.examples || []).length) {
    const examples = document.createElement("section");
    examples.className = "dictionary-examples";
    const heading = document.createElement("h4");
    heading.textContent = "例文";
    examples.append(heading);
    word.examples.forEach(example => {
      const row = document.createElement("div");
      const line = document.createElement("div");
      line.className = "dictionary-example-line";
      const text = document.createElement("p");
      text.textContent = example.title;
      line.append(text, dictionarySpeechButton(example.title, "例文を読む"));
      row.append(line);
      if (example.notationTitle) {
        const notation = document.createElement("small");
        notation.textContent = example.notationTitle;
        row.append(notation);
      }
      examples.append(row);
    });
    nodes.push(examples);
  }
  if (word.etymology) {
    const etymology = document.createElement("section");
    etymology.className = "dictionary-etymology";
    const heading = document.createElement("h4");
    heading.textContent = "語源";
    const text = document.createElement("p");
    text.textContent = word.etymology;
    etymology.append(heading, text);
    nodes.push(etymology);
  }
  target.replaceChildren(...nodes);
}

function cancelDictionaryDetail() {
  if (!state.dictionaryDetailController) return;
  state.dictionaryDetailController.abort();
  state.dictionaryDetailController = null;
}

function closeMobileDictionaryDetail({ restoreFocus = true } = {}) {
  const view = $("#dictionary-view");
  const wasOpen = view.classList.contains("dictionary-detail-open");
  view.classList.remove("dictionary-detail-open");
  if (!wasOpen || !isMobileDrawerLayout()) return;
  if (redesignedReadingUi) window.dispatchEvent(new Event("fujimi:dictionary-detail-close"));
  const selector = '.dictionary-result[data-id="' + CSS.escape(String(state.dictionaryActiveId || "")) + '"]';
  const active = document.querySelector(selector);
  requestAnimationFrame(() => {
    $(".dictionary-workspace", view)?.scrollIntoView({ block: "start", behavior: "auto" });
    if (restoreFocus) active?.focus({ preventScroll: true });
  });
}

async function loadDictionaryDetail(id, { reveal = false } = {}) {
  cancelDictionaryDetail();
  const controller = new AbortController();
  state.dictionaryDetailController = controller;
  state.dictionaryActiveId = id;
  if (reveal && isMobileDrawerLayout()) $("#dictionary-view").classList.add("dictionary-detail-open");
  document.querySelectorAll(".dictionary-result").forEach(item => item.classList.toggle("is-active", item.dataset.id === id));
  $("#dictionary-detail").innerHTML = '<p class="dictionary-status">词条を読み込んでいます…</p>';
  try {
    const word = await api(`/api/dictionary/words/${encodeURIComponent(id)}`, { signal: controller.signal });
    if (state.dictionaryDetailController === controller) {
      renderDictionaryDetail(word);
      if (reveal && isMobileDrawerLayout()) {
        requestAnimationFrame(() => $("#dictionary-detail").scrollIntoView({ block: "start", behavior: "auto" }));
      }
    }
  } catch (error) {
    if (error.name !== "AbortError" && state.dictionaryDetailController === controller) {
      $("#dictionary-detail").innerHTML = `<p class="dictionary-status error">${escapeText(error.message)}</p>`;
    }
  } finally {
    if (state.dictionaryDetailController === controller) state.dictionaryDetailController = null;
  }
}

function renderDictionaryResults(results) {
  const target = $("#dictionary-results");
  if (!results.length) {
    target.innerHTML = '<p class="dictionary-status">該当する言葉は見つかりませんでした。</p>';
    return;
  }
  target.replaceChildren(...results.map(result => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dictionary-result";
    button.dataset.id = result.id;
    const top = document.createElement("span");
    const spell = document.createElement("strong");
    spell.textContent = result.spell;
    const pron = document.createElement("small");
    pron.textContent = [result.pron, result.accent].filter(Boolean).join(" ");
    top.append(spell, pron);
    const excerpt = document.createElement("span");
    excerpt.textContent = result.excerpt || "释义未收录";
    button.append(top, excerpt);
    button.onclick = () => loadDictionaryDetail(result.id, { reveal: true });
    return button;
  }));
}

async function searchDictionary(rawQuery, { syncInput = true, remember = "now" } = {}) {
  const query = String(rawQuery || "").trim();
  stopDictionarySpeech();
  if (syncInput) $("#dictionary-query").value = query;
  if (state.dictionarySearchTimer) {
    clearTimeout(state.dictionarySearchTimer);
    state.dictionarySearchTimer = null;
  }
  if (state.dictionarySearchController) state.dictionarySearchController.abort();
  cancelDictionaryDetail();
  const sequence = ++state.dictionarySearchSequence;
  state.dictionaryActiveId = "";
  closeMobileDictionaryDetail({ restoreFocus: false });
  if (!query) {
    if (state.dictionaryHistoryTimer) {
      clearTimeout(state.dictionaryHistoryTimer);
      state.dictionaryHistoryTimer = null;
    }
    $("#dictionary-result-heading").hidden = true;
    $("#dictionary-result-count").textContent = "";
    $("#dictionary-results").replaceChildren();
    $("#dictionary-detail").innerHTML = '<div class="dictionary-empty"><span>語</span><p>調べたい言葉との出会いを、ここから。</p></div>';
    return;
  }
  const controller = new AbortController();
  state.dictionarySearchController = controller;
  $("#dictionary-result-heading").hidden = false;
  $("#dictionary-result-count").textContent = "検索中";
  $("#dictionary-results").innerHTML = '<p class="dictionary-status">本地词库を検索しています…</p>';
  try {
    const payload = await api(`/api/dictionary/search?q=${encodeURIComponent(query)}`, { signal: controller.signal });
    if (sequence !== state.dictionarySearchSequence) return;
    $("#dictionary-result-count").textContent = `${payload.results.length} 件`;
    renderDictionaryResults(payload.results);
    if (remember === "now") rememberDictionaryQuery(query);
    else if (remember === "later") rememberDictionaryQueryLater(query);
    if (payload.results[0] && !isMobileDrawerLayout()) await loadDictionaryDetail(payload.results[0].id);
    else if (payload.results[0]) $("#dictionary-detail").innerHTML = '<p class="dictionary-status">词条を選ぶと、詳しい释义を表示します。</p>';
    else $("#dictionary-detail").innerHTML = '<div class="dictionary-empty"><span>?</span><p>別の言葉で探してみましょう。</p></div>';
  } catch (error) {
    if (error.name !== "AbortError" && sequence === state.dictionarySearchSequence) {
      $("#dictionary-result-heading").hidden = true;
      $("#dictionary-result-count").textContent = "";
      $("#dictionary-results").innerHTML = `<p class="dictionary-status error">${escapeText(error.message)}</p>`;
    }
  } finally {
    if (state.dictionarySearchController === controller) state.dictionarySearchController = null;
  }
}

function scheduleDictionarySearch(event) {
  const query = event.currentTarget.value;
  setDictionaryHistoryOpen(false);
  if (state.dictionarySearchTimer) clearTimeout(state.dictionarySearchTimer);
  if (state.dictionaryHistoryTimer) {
    clearTimeout(state.dictionaryHistoryTimer);
    state.dictionaryHistoryTimer = null;
  }
  if (state.dictionarySearchController) state.dictionarySearchController.abort();
  cancelDictionaryDetail();
  if (!query.trim()) {
    searchDictionary("", { syncInput: false, remember: "never" });
    return;
  }
  state.dictionarySearchTimer = setTimeout(() => {
    state.dictionarySearchTimer = null;
    searchDictionary(query, { syncInput: false, remember: "later" });
  }, DICTIONARY_SEARCH_DELAY);
}

async function loadDictionary() {
  renderDictionaryHistory();
  if (state.dictionaryReady) return;
  try {
    const stats = await api("/api/dictionary/stats");
    const entryCount = Number(stats.entries ?? stats.entry_count ?? 0);
    const summary = entryCount.toLocaleString("ja-JP") + " 語 · " + (stats.dictionary || "日中辞典");
    $("#dictionary-stats").textContent = summary;
    $("#dictionary-result-library").textContent = summary;
    state.dictionaryReady = true;
  } catch (error) {
    $("#dictionary-stats").textContent = "词库读取失败";
    $("#dictionary-result-library").textContent = "词库读取失败";
    $("#dictionary-results").innerHTML = `<p class="dictionary-status error">${escapeText(error.message)}</p>`;
  }
}

function submitDictionarySearch(event) {
  event.preventDefault();
  setDictionaryHistoryOpen(false);
  searchDictionary($("#dictionary-query").value, { remember: "now" });
}

function processingArticle(article) {
  const panel = document.createElement("article");
  panel.className = "processing-panel";
  if (["excluded_paid", "invalid"].includes(article.status)) {
    panel.innerHTML = `<div class="article-top"><span class="source">${escapeText(article.source_name)}</span><button class="exit-reader icon-tool" type="button" aria-label="退出阅读">${BOOK_X_ICON}</button></div><h3>${escapeText(article.title)}</h3><p>${escapeText(article.failure_reason || "本文已移出文库，请在原站查看。")}</p><a class="origin" href="${escapeText(article.url)}" target="_blank" rel="noreferrer">原站打开 ↗</a>`;
    $(".exit-reader", panel).onclick = exitReaderRoom;
    return panel;
  }
  const progress = article.audio_status === "processing" ? `正在生成第 ${article.audio_progress || 0}/${article.audio_total || 0} 段。` : "首次 TTS 未完成，新闻正文暂不显示。";
  panel.innerHTML = `<div class="article-top"><span class="source">${escapeText(article.source_name)}</span><button class="exit-reader icon-tool" type="button" aria-label="退出阅读" title="退出阅读">${BOOK_X_ICON}</button></div><h3>${escapeText(article.title)}</h3><p>${escapeText(progress)}</p><p class="error">${escapeText(article.failure_reason || (article.audio_status === "failed" ? "TTS 生成失败。" : ""))}</p><a class="origin" href="${escapeText(article.url)}" target="_blank" rel="noreferrer">原站打开 ↗</a>`;
  $(".exit-reader", panel).onclick = exitReaderRoom;
  return panel;
}

const LOCAL_BROWSER_VOICES = [
  { id: "kokoro:jf_alpha", provider: "kokoro", name: "アルファ", lang: "ja-JP", local: true },
  { id: "voicevox:8", provider: "voicevox", name: "春日部つむぎ", lang: "ja-JP", local: true },
  { id: "voicevox:109", provider: "voicevox", name: "東北イタコ", lang: "ja-JP", local: true },
  { id: "voicevox:107", provider: "voicevox", name: "東北ずん子", lang: "ja-JP", local: true },
  { id: "voicevox:16", provider: "voicevox", name: "九州そら", lang: "ja-JP", local: true },
  { id: "voicevox:69", provider: "voicevox", name: "満別花丸", lang: "ja-JP", local: true },
  { id: "voicevox:74", provider: "voicevox", name: "琴詠ニア", lang: "ja-JP", local: true },
  { id: "voicevox:89", provider: "voicevox", name: "Voidoll", lang: "ja-JP", local: true },
  { id: "voicevox:47", provider: "voicevox", name: "ナースロボ＿タイプＴ", lang: "ja-JP", local: true },
];

function localBrowserVoices() {
  return typeof state !== "undefined" && state.browserVoices !== null && state.browserVoices !== undefined
    ? state.browserVoices : LOCAL_BROWSER_VOICES;
}

function localBrowserVoice(voiceId = "") {
  return localBrowserVoices().find(voice => voice.id === voiceId) || null;
}

function japaneseBrowserVoices() {
  if (!("speechSynthesis" in window)) return [];
  const seen = new Set();
  return speechSynthesis.getVoices().filter(voice => /^ja(?:-|_|$)/i.test(voice.lang)).filter(voice => {
    if (isHiddenBrowserVoiceName(voice.name)) return false;
    const key = `${voice.name}\u0000${voice.lang}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const HIDDEN_BROWSER_VOICE_NAMES = new Set(["haruka", "ichiro", "sayaka", "ayumi"]);

function isHiddenBrowserVoiceName(voiceName = "") {
  const match = String(voiceName).match(/^Microsoft\s+(.+?)(?:\s+Online|\s+Desktop|\s+-\s+Japanese|\s*\()/i);
  const shortName = (match?.[1] || String(voiceName)).trim().toLowerCase();
  return HIDDEN_BROWSER_VOICE_NAMES.has(shortName);
}

function desktopOnlineVoices() {
  return window.FujimiDesktop ? [
    { name: "Microsoft Keita Online (Natural) - Japanese (Japan)", id: "ja-JP-KeitaNeural" },
    { name: "Microsoft Nanami Online (Natural) - Japanese (Japan)", id: "ja-JP-NanamiNeural" },
  ] : [];
}

function desktopOnlineVoice(name) {
  if (window.FujimiMobile?.request && ["ja-JP-KeitaNeural", "ja-JP-NanamiNeural"].includes(name)) return { id: name };
  return desktopOnlineVoices().find(voice => voice.name === name || voice.id === name) || null;
}

function applyBrowserVoiceSettings(mode) {
  if (mode.mode) state.voiceMode = mode.mode;
  state.browserVoiceName = mode.browser_voice_name || "";
  state.browserVoiceLabel = mode.browser_voice_label || "ブラウザー";
}

function mobileVoiceNeedsPc(browserName = state.browserVoiceName) {
  return Boolean(window.FujimiMobile && (state.voiceMode === "voice" || localBrowserVoice(browserName)?.saved_audio_only));
}

function configuredBrowserVoice() {
  const voices = japaneseBrowserVoices();
  return preferredJapaneseBrowserVoice(voices);
}

function preferredJapaneseBrowserVoice(voices = japaneseBrowserVoices(), preferredName = state.browserVoiceName) {
  return voices.find(voice => voice.name === preferredName)
    || voices.find(voice => voice.default)
    || voices.find(voice => /(?:^|\s)Nanami(?:\s|$)/i.test(voice.name))
    || voices.find(voice => /(?:^|\s)Keita(?:\s|$)/i.test(voice.name))
    || voices[0]
    || null;
}

function waitForJapaneseBrowserVoice(timeout = 3000, preferredName = '') {
  const requestedName = preferredName || state.browserVoiceName;
  const selectedName = isHiddenBrowserVoiceName(requestedName) ? '' : requestedName;
  const choose = () => selectedName
    ? japaneseBrowserVoices().find(voice => voice.name === selectedName) || null
    : preferredJapaneseBrowserVoice(japaneseBrowserVoices());
  const ready = choose();
  if (ready || !("speechSynthesis" in window)) return Promise.resolve(ready);
  return new Promise(resolve => {
    let complete = false;
    let interval = null;
    let timer = null;
    const finish = voice => {
      if (complete) return;
      complete = true;
      if (interval) clearInterval(interval);
      if (timer) clearTimeout(timer);
      speechSynthesis.removeEventListener("voiceschanged", refresh);
      resolve(voice);
    };
    const refresh = () => {
      const voice = choose();
      if (voice) finish(voice);
    };
    speechSynthesis.addEventListener("voiceschanged", refresh);
    interval = setInterval(refresh, 100);
    timer = setTimeout(() => finish(null), timeout);
    refresh();
  });
}

async function resolveJapaneseBrowserVoice({ persistDefault = false, preferredName = '' } = {}) {
  const requestedName = preferredName || state.browserVoiceName;
  const local = typeof localBrowserVoice === "function" ? localBrowserVoice(requestedName) : null;
  if (local) return local;
  const selectedName = isHiddenBrowserVoiceName(requestedName) ? '' : requestedName;
  const online = desktopOnlineVoice(selectedName)
    || (isHiddenBrowserVoiceName(requestedName) ? desktopOnlineVoices()[0] : null);
  if (online && selectedName) return online;
  const voice = online || await waitForJapaneseBrowserVoice(3000, selectedName);
  if (!voice) return null;
  if (selectedName) return voice;
  state.browserVoiceName = voice.name;
  if (persistDefault) {
    try {
      await api("/api/settings/browser-voice", {
        method: "PUT",
        body: JSON.stringify({ name: voice.name, label: state.browserVoiceLabel || "ブラウザー" }),
      });
    } catch (_error) {
      // The selected in-memory voice still prevents a system-language fallback.
    }
  }
  return voice;
}

async function initializeBrowserVoice() {
  try {
    const mode = await api("/api/settings/voice-mode");
    applyBrowserVoiceSettings(mode);
    try {
      const catalog = await api("/api/browser-voices");
      if (Array.isArray(catalog)) state.browserVoices = catalog;
    } catch (_error) { state.browserVoices = []; }
    if (window.FujimiMobile?.speak) {
      if (mode.mode === "voice") return;
      const available = state.browserVoices.filter(voice => voice.available !== false);
      const selected = available.find(voice => voice.id === edgeVoiceId(state.browserVoiceName))
        || (!state.browserVoiceName ? available.find(voice => voice.default) || available[0] : null);
      if (selected && state.browserVoiceName !== selected.id) {
        applyBrowserVoiceSettings(await api("/api/settings/browser-voice", { method: "PUT", body: JSON.stringify({ name: selected.id, label: "システム音声" }) }));
        if (state.currentView === "settings") loadVoices();
      }
      return;
    }
    await resolveJapaneseBrowserVoice({ persistDefault: true });
  } catch (_error) {
    // A later dictionary action retries the same safe voice resolution.
  }
}

function browserVoiceShortName(voiceName = "") {
  const local = typeof localBrowserVoice === "function" ? localBrowserVoice(voiceName) : null;
  if (local) return local.name;
  const match = voiceName.match(/^Microsoft\s+(.+?)(?:\s+Online|\s+Desktop|\s+-\s+Japanese|\s*\()/i);
  const shortName = (match?.[1] || voiceName).trim();
  return ({ Nanami: "七海", Keita: "圭太", "ja-JP-NanamiNeural": "七海", "ja-JP-KeitaNeural": "圭太" })[shortName]
    || ({ "ja-JP-NanamiNeural": "七海", "ja-JP-KeitaNeural": "圭太" })[voiceName]
    || shortName;
}

function exampleVoiceChoices(voices, modeSettings, browserName, currentChoice) {
  const browserChoice = browserName ? `browser:${encodeURIComponent(browserName)}` : '';
  const localChoices = typeof localBrowserVoices === 'function'
    ? localBrowserVoices().filter(voice => voice.available !== false).map(voice => ({ label: voice.name, value: `browser:${encodeURIComponent(voice.id)}` }))
    : [];
  const options = [
    ...localChoices,
    ...(browserChoice && !localChoices.some(option => option.value === browserChoice)
      ? [{ label: browserVoiceShortName(browserName), value: browserChoice }] : []),
    ...voices.map(voice => ({ label: voice.name, value: `voice:${voice.id}` })),
  ];
  const activeVoice = voices.find(voice => voice.active);
  const savedBrowserChoice = modeSettings.browser_voice_name
    ? `browser:${encodeURIComponent(modeSettings.browser_voice_name)}` : '';
  const activeChoice = modeSettings.mode === 'voice' && activeVoice
    ? `voice:${activeVoice.id}` : savedBrowserChoice && options.some(option => option.value === savedBrowserChoice)
      ? savedBrowserChoice : browserChoice || (activeVoice ? `voice:${activeVoice.id}` : options[0]?.value || '');
  const choice = currentChoice === 'browser' ? browserChoice || activeChoice
    : currentChoice && currentChoice !== 'inherit' ? currentChoice : activeChoice;
  if (choice.startsWith('browser:') && !options.some(option => option.value === choice)) {
    options.push({ label: browserVoiceShortName(decodeURIComponent(choice.slice(8))), value: choice });
  }
  return { options, choice };
}

async function populateRereadVoices(select, article) {
  const [voices, modeSettings] = await Promise.all([api("/api/settings/voices"), api("/api/settings/voice-mode")]);
  applyBrowserVoiceSettings(modeSettings);
  const selectedBrowserName = browserVoiceShortName(state.browserVoiceName);
  const browserLabel = redesignedReadingUi ? (localBrowserVoice(state.browserVoiceName)?.name || selectedBrowserName || "音声") : selectedBrowserName ? `ブラウザー音声（${selectedBrowserName}）` : "ブラウザー音声";
  select.replaceChildren(
    new Option(browserLabel, "browser"),
    ...voices.map(voice => new Option(voice.name, `voice:${voice.id}`)),
  );
  const mode = article.audio_voice_mode || "model";
  const value = mode === "voice" && article.audio_voice_id
    ? `voice:${article.audio_voice_id}`
    : "browser" === mode ? "browser" : "model";
  if ([...select.options].some(option => option.value === value)) select.value = value;
}

function copyWithoutRuby(event) {
  const selection = window.getSelection();
  if (!event.clipboardData || !selection || selection.isCollapsed || selection.rangeCount === 0) return;
  const fragment = selection.getRangeAt(0).cloneContents();
  fragment.querySelectorAll("ruby").forEach(ruby => {
    const base = [...ruby.childNodes]
      .filter(node => !(node.nodeType === Node.ELEMENT_NODE && ["RT", "RP"].includes(node.tagName)))
      .map(node => node.textContent || "")
      .join("")
      .replace(/[ \t]*[\r\n]+[ \t]*/g, "");
    ruby.replaceWith(document.createTextNode(base));
  });
  const wrapper = document.createElement("div");
  wrapper.append(fragment);
  event.clipboardData.setData("text/plain", wrapper.textContent || "");
  event.clipboardData.setData("text/html", wrapper.innerHTML);
  event.preventDefault();
}

function setArticleTranslationView(root, mode = "show") {
  const parallel = $(".parallel", root);
  const full = $(".full-translation", root);
  const showTranslation = mode === "show" || mode === "full" || mode === "click";
  const clickToReveal = mode === "click";
  root.dataset.translationMode = mode;
  root.dataset.translationVisible = String(showTranslation);
  parallel.hidden = mode === "full";
  full.hidden = !(showTranslation && mode === "full");
  root.querySelectorAll(".parallel .chinese").forEach(element => {
    if (!element.dataset.translationText) element.dataset.translationText = element.textContent || "";
    let translationMain = element.querySelector(".translation-main");
    let translationPlaceholder = element.querySelector(".translation-placeholder");
    if (!translationMain) {
      translationMain = document.createElement("span");
      translationMain.className = "translation-main";
      translationMain.textContent = element.dataset.translationText;
      translationPlaceholder = document.createElement("span");
      translationPlaceholder.className = "translation-placeholder";
      translationPlaceholder.innerHTML = '<span class="text">［クリックで表示］</span>';
      element.replaceChildren(translationMain, translationPlaceholder);
    }
    if (!clickToReveal) element.dataset.translationRevealed = "false";
    let pointerStart = null;
    element.onpointerdown = event => {
      pointerStart = { x: event.clientX, y: event.clientY };
      element.dataset.translationDrag = "false";
    };
    element.onpointermove = event => {
      if (!pointerStart) return;
      if (Math.abs(event.clientX - pointerStart.x) > 3 || Math.abs(event.clientY - pointerStart.y) > 3) {
        element.dataset.translationDrag = "true";
      }
    };
    element.onpointerup = () => {
      pointerStart = null;
      window.setTimeout(() => { element.dataset.translationDrag = "false"; }, 0);
    };
    element.onpointercancel = () => {
      pointerStart = null;
      element.dataset.translationDrag = "false";
    };
    element.onclick = event => {
      event.stopPropagation();
      if (!clickToReveal) return;
      const selection = window.getSelection();
      const draggedToSelect = element.dataset.translationDrag === "true";
      element.dataset.translationDrag = "false";
      if (draggedToSelect || (selection && !selection.isCollapsed)) return;
      element.dataset.translationRevealed = String(element.dataset.translationRevealed !== "true");
      setArticleTranslationView(root, "click");
    };
    element.onkeydown = event => {
      if (!clickToReveal || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      event.stopPropagation();
      element.click();
    };
    element.hidden = mode === "hide";
    const revealed = clickToReveal && element.dataset.translationRevealed === "true";
    element.classList.toggle("moji-article-translation", showTranslation);
    element.classList.toggle("isHidden", mode === "hide");
    element.classList.toggle("isShow", mode !== "click" && mode !== "hide");
    element.classList.toggle("isClickHidden", clickToReveal && !revealed);
    element.classList.toggle("translation-reveal", clickToReveal);
    element.classList.toggle("is-revealed", revealed);
    element.tabIndex = clickToReveal ? 0 : -1;
    element.setAttribute("role", clickToReveal ? "button" : "presentation");
    if (clickToReveal) element.setAttribute("aria-label", revealed ? "クリックで隠す" : "クリックで表示");
    else element.removeAttribute("aria-label");
    translationMain.textContent = element.dataset.translationText;
  });
  const toggle = $(".translation-menu-toggle", root);
  const label = $(".translation-menu-label", toggle);
  const labels = { show: "訳文を表示", hide: "訳文を隠す", full: "訳文のみ", click: "クリックで表示" };
  if (label) label.textContent = labels[mode] || labels.show;
  if (toggle) {
    toggle.setAttribute("aria-label", labels[mode] || labels.show);
    toggle.title = labels[mode] || labels.show;
  }
  root.querySelectorAll(".translation-menu [data-translation-mode]").forEach(button => {
    button.setAttribute("aria-checked", String(button.dataset.translationMode === mode));
  });
}

function articleDetail(article) {
  stopArticlePlayback(true);
  destroyHlsPlayers();
  state.article = article;
  if (!isVisible(article)) return processingArticle(article);
  const fragment = $("#article-template").content.cloneNode(true);
  const root = $(".article-detail", fragment);
  root.dataset.sourceKey = article.source_key || "";
  $(".source", root).textContent = article.source_name;
  $(".title", root).textContent = article.title;
  $(".published", root).textContent = formatPublishedAt(article.published_at);
  $(".origin", root).href = article.url;
  $(".origin", root).hidden = !article.url;
  const translatedParagraphs = article.translated_paragraphs || [];
  const translationFailed = translatedParagraphs.length < (article.paragraphs || []).length || !article.full_translation;
  const translationMaintenance = $(".translation-maintenance", root);
  translationMaintenance.hidden = !translationFailed;
  $(".failure", root).textContent = translationFailed ? "翻訳がまだ完了していません。" : "";
  $(".retranslate", root).hidden = !translationFailed;

  const media = $(".media", root);
  if (article.media_warnings?.length) {
    const warning = document.createElement("p");
    warning.className = "web-reader-note";
    warning.setAttribute("role", "status");
    warning.textContent = [...new Set(article.media_warnings)].join(" ");
    media.before(warning);
  }
  const imagePaths = article.image_paths || [];
  const imagePositions = article.image_positions || [];
  const imageLinks = article.image_links || [];
  const hasImagePositions = imagePositions.length === imagePaths.length;
  const videoUrls = article.video_urls || [];
  const videoDescriptors = videoUrls.map(nhkVideoDescriptor);
  const createImageFigure = (path, index) => {
    const figure = document.createElement("figure");
    figure.className = "media-item";
    const image = document.createElement("img");
    image.src = (redesignedReadingUi ? /^\/api\/(?:articles|bookmarks)\//.test(path) : path.startsWith("/api/articles/")) ? path : `/api/media/${path}`;
    image.alt = (article.image_captions || [])[index] || article.title;
    const link = imageLinks[index];
    if (link) {
      const anchor = document.createElement("a");
      anchor.className = "media-link";
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
      anchor.append(image);
      figure.append(anchor);
    } else {
      figure.append(image);
    }
    const caption = (article.image_captions || [])[index];
    if (caption) {
      const figcaption = document.createElement("figcaption");
      figcaption.textContent = caption;
      figure.append(figcaption);
    }
    return figure;
  };
  let topImageIndexes = imagePaths.map((_path, index) => index)
    .filter(index => !hasImagePositions || Number(imagePositions[index]) < 0);
  if (["nhk", "nikkei"].includes(article.source_key) && videoDescriptors.some(item => item.isLocal || item.poster) && topImageIndexes.length === 1) {
    const posterPath = imagePaths[topImageIndexes[0]];
    videoDescriptors.forEach(item => { item.poster = (redesignedReadingUi ? /^\/api\/(?:articles|bookmarks)\//.test(posterPath) : posterPath.startsWith("/api/articles/")) ? posterPath : `/api/media/${posterPath}`; });
    topImageIndexes = [];
  }
  media.classList.toggle("media-single", topImageIndexes.length === 1 && !videoUrls.length);
  const remoteVideoFallback = videoDescriptors.find(item => !item.isLocal);
  const hasLocalVideo = videoDescriptors.some(item => item.isLocal);
  const displayedVideos = hasLocalVideo
    ? videoDescriptors.filter(item => item.isLocal)
    : videoDescriptors;
  const createVideoFrame = descriptor => {
    const frame = document.createElement("iframe");
    frame.className = "media-video-embed";
    frame.src = descriptor.source;
    frame.title = `${article.title} 動画`;
    frame.allow = "encrypted-media; fullscreen; picture-in-picture";
    frame.allowFullscreen = true;
    frame.loading = "lazy";
    return frame;
  };
  media.classList.toggle("media-video-single", displayedVideos.length === 1 && topImageIndexes.length === 0);
  topImageIndexes.forEach(index => media.append(createImageFigure(imagePaths[index], index)));
  displayedVideos.forEach(descriptor => {
    if (descriptor.isEmbed) {
      media.append(createVideoFrame(descriptor));
      return;
    }
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    if (descriptor.isLocal && remoteVideoFallback) {
      video.addEventListener("error", () => {
        if (remoteVideoFallback.isEmbed) {
          video.replaceWith(createVideoFrame(remoteVideoFallback));
          return;
        }
        const fallbackVideo = document.createElement("video");
        fallbackVideo.controls = true;
        fallbackVideo.preload = "metadata";
        fallbackVideo.playsInline = true;
        attachVideoSource(fallbackVideo, remoteVideoFallback);
        video.replaceWith(fallbackVideo);
      }, { once: true });
    }
    video.addEventListener("error", () => {
      if (video.isConnected) toast("视频文件未同步完整或无法解码。", true);
    }, { once: true });
    attachVideoSource(video, descriptor);
    media.append(video);
    window.decorateNikkeiPodcast?.(video, article, descriptor);
  });
  media.hidden = topImageIndexes.length === 0 && videoUrls.length === 0;

  const parallel = $(".parallel", root);
  const inlineImages = new Map();
  if (hasImagePositions) {
    imagePositions.forEach((position, index) => {
      if (Number(position) < 0) return;
      const target = Math.min((article.paragraphs || []).length, Math.max(0, Number(position)));
      inlineImages.set(target, [...(inlineImages.get(target) || []), index]);
    });
  }
  const appendInlineImages = position => {
    const indexes = inlineImages.get(position) || [];
    if (!indexes.length) return;
    const row = document.createElement("div");
    row.className = `media article-inline-media${indexes.length === 1 ? " media-single" : ""}`;
    indexes.forEach(index => row.append(createImageFigure(imagePaths[index], index)));
    parallel.append(row);
  };
  (article.paragraphs || []).forEach((paragraph, index) => {
    appendInlineImages(index);
    const section = document.createElement("section");
    section.className = "paragraph";
    section.dataset.audioIndex = String(index);
    const paragraphKind = (article.paragraph_kinds || [])[index] || "paragraph";
    if (paragraphKind === "box" || paragraphKind === "box-plain") section.classList.add("paragraph-box");
    if (paragraphKind.startsWith("heading")) {
      section.classList.add("paragraph-heading");
      if (paragraphKind === "heading-2" || paragraphKind === "heading-3") {
        section.classList.add(`paragraph-${paragraphKind}`);
      }
    }
    const japanese = document.createElement("div");
    japanese.className = "japanese";
    japanese.tabIndex = 0;
    japanese.setAttribute("role", "button");
    japanese.setAttribute("aria-label", `第 ${index + 1} 段から再生`);
    japanese.innerHTML = (article.furigana_paragraphs || [])[index] || escapeText(paragraph);
    const chinese = document.createElement("p");
    chinese.className = "chinese";
    chinese.textContent = (article.translated_paragraphs || [])[index] || "訳文はまだ生成されていません。";
    section.append(japanese, chinese);
    parallel.append(section);
  });
  appendInlineImages((article.paragraphs || []).length);
  prepareMobileReadingLookup(root, ".parallel", ".japanese");
  $(".full-translation", root).textContent = article.full_translation || "全文訳はまだ生成されていません。";
  setArticleTranslationView(root, "show");

  const bookmarkButton = $(".bookmark", root);
  renderBookmarkButton(bookmarkButton, Boolean(article.bookmarked));
  bookmarkButton.onclick = () => toggleBookmark(article, bookmarkButton);
  $(".copy-original", root).onclick = async () => {
    try {
      await navigator.clipboard.writeText(article.original_text || article.paragraphs.join("\n\n"));
      toast("原文已复制");
    } catch (_error) {
      toast("复制失败，请检查浏览器权限", true);
    }
  };
  $(".exit-reader", root).onclick = exitReaderRoom;
  setupArticleAudio(article, root);
  const voiceSelect = $(".reread-voice", root);
  populateRereadVoices(voiceSelect, article).catch(error => setRereadTask(root, "failed", "声線を読み込めませんでした。", "", error.message));
  const rereadLink = $(".reread-link", root);
  const rereadPanel = $(".reread-panel", root);
  const translationToggle = $(".translation-menu-toggle", root);
  const translationMenu = $(".translation-menu", root);
  translationToggle.classList.remove("icon-tool");
  translationToggle.innerHTML = '<span class="translation-menu-label"></span><span class="translation-menu-chevron" aria-hidden="true"></span>';
  translationMenu.innerHTML = '<button type="button" data-translation-mode="show" role="menuitemradio">訳文を表示</button><button type="button" data-translation-mode="click" role="menuitemradio">クリックで表示</button><button type="button" data-translation-mode="hide" role="menuitemradio">訳文を隠す</button><button type="button" data-translation-mode="full" role="menuitemradio">訳文のみ</button><button class="retranslate quiet" type="button" hidden>再翻訳</button><span class="translation-task-status" role="status"></span>';
  translationMenu.id = `translation-menu-${article.id}`;
  root.querySelectorAll(".translation-switch button[data-mode]").forEach(button => {
    button.setAttribute("aria-controls", translationMenu.id);
  });
  setArticleTranslationView(root, "show");
  rereadLink.onclick = () => {
    const open = rereadPanel.hidden;
    rereadPanel.hidden = !open;
    rereadLink.setAttribute("aria-expanded", String(open));
    if (open) translationMenu.hidden = true;
  };
  const setTranslationMenuOpen = (open, { focusItem = false } = {}) => {
    translationMenu.hidden = !open;
    translationToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      rereadPanel.hidden = true;
      rereadLink.setAttribute("aria-expanded", "false");
      if (focusItem) {
        const activeItem = translationMenu.querySelector('[aria-checked="true"]');
        (activeItem || translationMenu.querySelector("[data-translation-mode]"))?.focus();
      }
    }
  };
  translationToggle.onclick = () => {
    const open = translationMenu.hidden;
    setTranslationMenuOpen(open);
  };
  translationToggle.onkeydown = event => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    setTranslationMenuOpen(true, { focusItem: true });
  };
  translationMenu.onkeydown = event => {
    const items = [...translationMenu.querySelectorAll("[data-translation-mode]")];
    const current = items.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setTranslationMenuOpen(false);
      translationToggle.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[(current + step + items.length) % items.length]?.focus();
  };
  root.addEventListener("click", event => {
    if (!event.target.closest(".reread-popover-wrap")) {
      rereadPanel.hidden = true;
      rereadLink.setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest(".translation-switch")) {
      setTranslationMenuOpen(false);
    }
  });
  const rereadButton = $(".reread", root);
  rereadButton.disabled = ["pending", "processing"].includes(article.audio_status);
  rereadButton.onclick = () => {
    rereadPanel.hidden = true;
    rereadLink.setAttribute("aria-expanded", "false");
    rereadArticle(article, voiceSelect.value, $("#reader-result"), root);
  };
  const initialTts = ["pending", "processing"].includes(article.audio_status);
  const cancelRereadAction = () => cancelReread(article, $("#reader-result"), root, initialTts ? "initial" : "reread");
  $(".cancel-reread", root).onclick = cancelRereadAction;
  $(".reread-task-cancel", root).onclick = cancelRereadAction;
  $(".retranslate", root).onclick = () => retranslateArticle(article.id, $("#reader-result"), root);
  root.querySelectorAll(".translation-menu button[data-translation-mode]").forEach(button => {
    button.onclick = () => {
      setArticleTranslationView(root, button.dataset.translationMode);
      setTranslationMenuOpen(false);
      translationToggle.focus();
    };
  });
  return root;
}

function openArticle(article, target) {
  stopRereadTracking();
  $("#reader-view").classList.add("is-reading");
  $("#reader-import-workspace").hidden = true;
  rememberReaderArticle(article);
  target.replaceChildren(articleDetail(article));
  const root = $(".article-detail", target);
  const initialTts = ["pending", "processing"].includes(article.audio_status);
  if (root && initialTts) {
    const current = Number(article.audio_progress || 0);
    const total = Number(article.audio_total || (article.paragraphs || []).length || 0);
    const detail = article.audio_task_detail || (article.audio_status === "processing" ? "生成状況を確認しています…" : "朗読の順番を待っています…");
    setRereadTask(root, "running", detail, total ? `${current}/${total}` : "準備中", "", current, total || 1, { cancellable: true });
    startRereadTracking(article, target, root, "initial");
  } else if (root && article.audio_status === "replacing") {
    const current = Number(article.audio_progress || 0);
    const total = Number(article.audio_total || 0);
    setRereadTask(root, "running", article.audio_task_detail || "生成状況を確認しています…", total ? `${current}/${total}` : "", "", current, total || 1, { cancellable: true });
    startRereadTracking(article, target, root, "reread");
  } else if (root && ["failed", "replace_failed"].includes(article.audio_status)) {
    setRereadTask(root, "failed", article.audio_task_detail || "朗読生成に失敗しました。再試行してください。");
  } else if (root && article.audio_unavailable_detail && !redesignedReadingUi) {
    setRereadTask(root, "failed", article.audio_unavailable_detail);
  }
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function openArticleInReader(article) {
  await showView("reader", redesignedReadingUi ? { resetReader: false, restoreReader: false } : { resetReader: false });
  openArticle(article, $("#reader-result"));
}

function setRereadTask(root, status, label, count = "", detail = "", current = 0, total = 1, { cancellable = false } = {}) {
  const task = $(".reread-task", root);
  if (!task) return;
  task.hidden = redesignedReadingUi && status === "failed";
  task.classList.toggle("is-failed", status === "failed");
  $(".reread-task-label", task).textContent = status === "failed" && detail ? `${label} ${detail}` : label;
  const taskCancelButton = $(".reread-task-cancel", task);
  const progress = $("progress", task);
  progress.max = Math.max(1, total);
  progress.value = Math.max(0, current);
  const button = $(".reread", root);
  const cancelButton = $(".cancel-reread", root);
  const voiceSelect = $(".reread-voice", root);
  const isRunning = status === "running";
  const isCancelling = root.dataset.rereadCancelling === "true";
  if (button) {
    button.hidden = isRunning;
    button.disabled = isRunning;
  }
  if (cancelButton) {
    cancelButton.hidden = !isRunning || !cancellable;
    cancelButton.disabled = isCancelling;
  }
  if (taskCancelButton) {
    taskCancelButton.hidden = !isRunning || !cancellable;
    taskCancelButton.disabled = isCancelling;
  }
  if (voiceSelect) voiceSelect.disabled = isRunning;
  if (redesignedReadingUi && status === "failed") toast(detail || label, true);
}

async function generateMobilePcSpeech(root, selection, { autoplay = false, paragraph = 0 } = {}) {
  if (root.pcSpeechJob) return;
  const book = root.id === "book-reader" ? state.libraryChapter : null;
  const article = book ? null : state.article;
  if (!book && !article) throw new Error("朗读正文不可用。");
  const body = { kind: book ? "book" : "article", id: book ? book.book.id : article.id,
    chapter_id: book?.chapter.id, selection };
  const job = { id: "", cancelled: false }; root.pcSpeechJob = job;
  const toggle = $(".audio-player-toggle", root);
  if (toggle) { toggle.disabled = true; toggle.setAttribute("aria-busy", "true"); }
  try {
    setRereadTask(root, "running", "PCで朗読を準備しています…", "", "", 0, 1);
    let result = await api("/api/pc-speech/start", { method: "POST", body: JSON.stringify(body) });
    job.id = result.task_id || "";
    while (!["ready", "completed"].includes(result.status)) {
      if (["failed", "interrupted", "cancelled"].includes(result.status)) {
        if (result.status === "cancelled") return;
        throw new Error(result.message || "PC 朗读生成失败，请重试。");
      }
      if (!job.id) throw new Error("PC 未返回朗读任务。");
      if (job.cancelled) return;
      setRereadTask(root, "running", result.message || "PCで朗読を生成しています…", "", "",
        Number(result.completed || 0), Number(result.total || 1), { cancellable: true });
      await new Promise(resolve => setTimeout(resolve, 800));
      result = await api(`/api/pc-speech/tasks/${job.id}`);
    }
    if (job.cancelled || !root.isConnected
        || (book ? state.libraryChapter !== book || !isBookReaderActive(root) : state.article !== article || document.documentElement.dataset.nativeReading !== "article")) return;
    if (book) await navigateBookChapter(book.book.id, book.chapter.id, { historyMode: "replace" });
    else openArticle(result.article || await api(articleApiPath(article)), root.parentElement);
    if (autoplay && state.articleAudio?.root.isConnected) state.articleAudio.seekParagraph(paragraph);
  } finally {
    if (root.pcSpeechJob === job) root.pcSpeechJob = null;
    if (toggle?.isConnected) { toggle.disabled = false; toggle.removeAttribute("aria-busy"); }
    if (root.isConnected && $(".reread-task", root)) $(".reread-task", root).hidden = true;
  }
}

function mobileSpeechSelection(voiceValue = "") {
  if (voiceValue.startsWith("voice:")) return { mode: "voice", voice_id: Number(voiceValue.slice(6)) };
  if (voiceValue === "browser") return { mode: "browser", browser_voice_name: state.browserVoiceName };
  return { mode: voiceValue || "model" };
}

function mobileSelectionNeedsPc(selection) {
  if (!window.FujimiMobile?.request) return false;
  if (selection.mode === "voice") return true;
  if (selection.mode === "browser") return Boolean(localBrowserVoice(selection.browser_voice_name)?.saved_audio_only);
  return ["model", "inherit"].includes(selection.mode) && mobileVoiceNeedsPc();
}

function reportArticleAudioError(controller, error) {
  if (state.articleAudio !== controller || !controller.root.isConnected) return;
  if (error?.name === "AbortError" && controller.audio.paused) return;
  if (controller.errorToast?.isConnected) return;
  controller.errorToast = toast("音频播放失败，请重试。", true);
}

async function rereadArticle(article, voiceValue, target, root) {
  try {
    let browserName = voiceValue === "browser" ? state.browserVoiceName : "";
    if (voiceValue === "browser" && !browserName) {
      const selected = await resolveJapaneseBrowserVoice({ persistDefault: true });
      browserName = selected?.id || selected?.name || "";
      if (!browserName) throw new Error("利用できる日本語のブラウザー音声がありません。");
    }
    const sharedOnlineVoice = (window.FujimiDesktop || window.FujimiMobile?.request) && voiceValue === "browser" ? desktopOnlineVoice(browserName) : null;
    if (sharedOnlineVoice) {
      setRereadTask(root, "running", "オンライン音声を生成して保存しています…", "", "", 0, 1, { cancellable: false });
      const result = await api(`/api/articles/${article.id}/edge-tts`, {
        method: "POST", body: JSON.stringify({ voice: sharedOnlineVoice.id }),
      });
      openArticle(result.article, target);
      if (!window.FujimiMobile?.request) toast(result.cached ? "保存済みの朗読を読み込みました。" : "オンライン音声を保存しました。");
      return;
    }
    const mode = voiceValue.startsWith("voice:") ? "voice" : voiceValue;
    const voiceId = mode === "voice" ? Number(voiceValue.split(":", 2)[1]) : null;
    const selection = { mode, voice_id: voiceId, browser_voice_name: browserName };
    if (mobileSelectionNeedsPc(selection)) {
      await generateMobilePcSpeech(root, selection);
      return;
    }
    setRereadTask(root, "running", window.FujimiMobile ? "保存済みの朗読を確認しています…" : "音声生成を準備しています…", "", "", 0, 1, { cancellable: !window.FujimiMobile });
    const result = await api(articleApiPath(article, "/reread"), { method: "POST", body: JSON.stringify({ mode, voice_id: voiceId, browser_voice_name: browserName }) });
    if (result.status === "ready") {
      stopRereadTracking();
      openArticle(result.article, target);
      toast(mode === "browser" && !result.cached ? "ブラウザー音声を保存しました。" : "保存済みの朗読を読み込みました。");
      return;
    }
    if (result.status === "browser") {
      openArticle(result.article, target);
      toast("ブラウザー音声の保存には声線の選択が必要です。", true);
      return;
    }
    startRereadTracking(article, target, root, "reread");
  } catch (error) {
    setRereadTask(root, "failed", "読み返しを開始できませんでした。", "", error.message);
  }
}

async function cancelReread(article, target, root, mode = "reread") {
  if (root.pcSpeechJob) {
    const job = root.pcSpeechJob;
    if (job.id) await api(`/api/pc-speech/tasks/${job.id}`, { method: "DELETE" });
    job.cancelled = true;
    return;
  }
  if (root.dataset.rereadCancelling === "true") return;
  root.dataset.rereadCancelling = "true";
  const button = $(".cancel-reread", root);
  const taskButton = $(".reread-task-cancel", root);
  if (button) button.disabled = true;
  if (taskButton) taskButton.disabled = true;
  const initial = mode === "initial";
  setRereadTask(root, "running", "朗読音声の生成を中止しています…", "", "", 0, 1, { cancellable: true });
  if (button) button.disabled = true;
  if (taskButton) taskButton.disabled = true;
  try {
    const result = await api(articleApiPath(article, initial ? "/tts" : "/reread"), { method: "DELETE" });
    stopRereadTracking();
    openArticle(result.article || await api(articleApiPath(article)), target);
    toast(result.status === "cancelled"
      ? "朗読音声の生成を中止しました"
      : "実行中の生成はありません");
  } catch (error) {
    setRereadTask(root, "failed", "朗読音声の生成を中止できませんでした。", "", error.message);
    if (button) button.disabled = false;
    if (taskButton) taskButton.disabled = false;
  }
  delete root.dataset.rereadCancelling;
}

function startRereadTracking(article, target, root, mode = "reread") {
  stopRereadTracking();
  const tracker = { articleId: article.id, bookmark: Boolean(article.bookmark_context), mode, cancelled: false };
  state.rereadTracker = tracker;
  pollReread(article, target, root, tracker)
    .catch(error => {
      if (!tracker.cancelled) {
        const label = tracker.mode === "initial" ? "読み上げ音声の生成に失敗しました。" : "読み返しの生成に失敗しました。";
        setRereadTask(root, "failed", label, "", error.message);
      }
    })
    .finally(() => {
      if (state.rereadTracker === tracker) state.rereadTracker = null;
    });
}

async function pollReread(articleReference, target, root, tracker) {
  while (!tracker.cancelled && root.isConnected) {
    await new Promise(resolve => setTimeout(resolve, 800));
    if (tracker.cancelled) return;
    const article = await api(articleApiPath(articleReference));
    if (tracker.cancelled) return;
    const current = Number(article.audio_progress || 0);
    const total = Number(article.audio_total || (article.paragraphs || []).length || 0);
    const initial = tracker.mode === "initial";
    if (["cancelled", "interrupted", "failed"].includes(article.audio_task_status)) {
      openArticle(article, target);
      if (article.audio_task_status !== "cancelled") setRereadTask($(".article-detail", target), "failed", article.audio_task_detail || "朗読生成が中断されました。再試行してください。");
      return;
    }
    const completedStatuses = ["ready", "browser", "disabled"];
    if (completedStatuses.includes(article.audio_status)) {
      openArticle(article, target);
      toast(initial ? "読み上げ音声の準備が完了しました" : "読み返し音声の準備が完了しました");
      return;
    }
    const runningDetail = article.audio_task_detail || (initial && article.audio_status === "pending"
      ? "朗読の順番を待っています…"
      : "生成状況を確認しています…");
    setRereadTask(root, "running", runningDetail, total ? `${current}/${total}` : "準備中", "", current, total || 1, { cancellable: true });
    if (initial && article.audio_status === "failed") throw new Error("読み上げ音声の生成に失敗しました。");
    if (!initial && article.audio_status === "replace_failed") throw new Error("読み返しの生成に失敗しました。元の音声は残されています。");
  }
}

async function retranslateArticle(articleId, target, root) {
  const button = $(".retranslate", root);
  const status = $(".translation-task-status", root);
  button.disabled = true;
  status.textContent = "再翻訳を開始しています…";
  status.classList.remove("error");
  try {
    await api(`/api/articles/${articleId}/retranslate`, { method: "POST" });
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 800));
      const task = await api(`/api/articles/${articleId}/translation-task`);
      status.textContent = task.message || "再翻訳しています…";
      if (task.status === "completed") {
        const article = await api(`/api/articles/${articleId}`);
        openArticle(article, target);
        const nextStatus = $(".translation-task-status", target);
        nextStatus.textContent = "再翻訳が完了しました。";
        return;
      }
      if (task.status === "failed") throw new Error(task.message || "再翻訳に失敗しました。");
    }
    throw new Error("再翻訳はバックグラウンドで続いています。");
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
    button.disabled = false;
  }
}

async function loadDaily(date = null) {
  if (state.dailyRereadTimer) {
    clearTimeout(state.dailyRereadTimer);
    state.dailyRereadTimer = null;
  }
  try {
    const days = await api("/api/days");
    const select = $("#history-select");
    select.replaceChildren(...days.map(day => new Option(day, day)));
    const requestedDate = date || rememberedDailyDate();
    const selectedDate = days.includes(requestedDate) ? requestedDate : "";
    if (requestedDate && !selectedDate) rememberDailyDate("");
    const today = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
    if (!selectedDate && !days.includes(today)) {
      const task = await api("/api/tasks/daily");
      const running = task.status === "running";
      state.dailyTaskRunning = running;
      if (running) {
        $("#daily-list").innerHTML = '<p class="empty">本日のニュースを準備しています。完成した記事から順に並びます。</p>';
        if (state.currentView === "daily") state.dailyRereadTimer = setTimeout(() => loadDaily(), 800);
        return;
      }
    }
    const chosen = selectedDate || select.value;
    if (!chosen) {
      const task = await api("/api/tasks/daily");
      const running = task.status === "running";
      state.dailyTaskRunning = running;
      $("#daily-list").innerHTML = `<p class="empty">${running ? "本日のニュースを準備しています。まもなくここに並びます。" : "本日のニュースはまだ届いていません。設定から日刊を生成できます。"}</p>`;
      if (running && state.currentView === "daily") state.dailyRereadTimer = setTimeout(() => loadDaily(), 800);
      return;
    }
    select.value = chosen;
    rememberDailyDate(chosen);
    const snapshot = await api(`/api/daily?date=${encodeURIComponent(chosen)}`);
    $("#snapshot-meta").textContent = "いま起きていることを、ひとつずつ。";
    const list = $("#daily-list");
    if (!snapshot.articles.length) { list.innerHTML = '<p class="empty">本日のニュースを準備しています。まもなくここに並びます。</p>'; }
    else {
      const cards = snapshot.articles.map(article => {
      const card = list.querySelector(`[data-article-id="${Number(article.id)}"]`) || document.createElement("article");
      card.className = "news-card";
      card.dataset.articleId = String(article.id);
      const current = Number(article.audio_progress || 0);
      const total = Number(article.audio_total || 0);
      const firstTts = ["pending", "processing"].includes(article.audio_status);
      const rereading = article.audio_status === "replacing";
      const audioLabel = article.audio_status === "disabled" ? "朗読なし" : article.audio_status === "browser" ? "ブラウザー音声" : article.audio_status === "failed" ? "朗読生成に失敗" : article.audio_status === "replace_failed" ? "読み返しに失敗" : "全文音声";
      const taskDetail = article.audio_task_detail || (article.audio_status === "pending" ? "朗読の順番を待っています…" : "生成状況を確認しています…");
      const audioState = firstTts || rereading
        ? `<div class="card-tts-progress" role="status"><div><span>${escapeText(taskDetail)}</span><span>${total ? `${current}/${total}` : "準備中"}</span></div><progress max="${Math.max(1, total)}" value="${current}"></progress></div>`
        : `<p class="muted">假名 · ${article.translated_paragraphs?.length ? "翻译 · " : ""}${audioLabel}</p>`;
      if (!card.querySelector("button")) {
        card.innerHTML = '<span class="source"></span><h3></h3><div class="card-audio-state"></div><button>阅读する</button>';
      }
      $(".source", card).textContent = article.source_name;
      $("h3", card).textContent = article.title;
      const audioStateNode = $(".card-audio-state", card);
      if (audioStateNode.dataset.state !== audioState) {
        audioStateNode.innerHTML = audioState;
        audioStateNode.dataset.state = audioState;
      }
      $("button", card).onclick = () => openArticleInReader(article);
      return card;
      });
      if (cards.length !== list.children.length || cards.some((card, index) => card !== list.children[index])) list.replaceChildren(...cards);
    }
    select.onchange = () => {
      rememberDailyDate(select.value);
      loadDaily(select.value);
    };
    if ((snapshot.generation_running || snapshot.articles.some(article => ["pending", "processing", "replacing"].includes(article.audio_status))) && state.currentView === "daily") {
      state.dailyRereadTimer = setTimeout(() => loadDaily(chosen), 800);
    }
  } catch (error) { notice(error.message, true); }
}

async function importUrl(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("button[type='submit']", form);
  button.disabled = true;
  form.setAttribute("aria-busy", "true");
  readerImportNotice("処理を準備しています…", { processing: true, progress: 0, total: 4 });
  try {
    const task = await api("/api/import/tasks", { method: "POST", body: JSON.stringify({ url: $("#article-url").value }) });
    rememberReaderImportTask(task.task_id);
    await trackReaderImport(task.task_id);
  } catch (error) {
    forgetReaderImportTask();
    readerImportNotice(error.message, { isError: true });
  } finally {
    if (!state.importTracker) {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  }
}

function renderBookmarkButton(button, bookmarked) {
  const label = bookmarked ? "取消收藏" : "收藏";
  button.classList.toggle("is-bookmarked", bookmarked);
  button.setAttribute("aria-pressed", String(bookmarked));
  button.setAttribute("aria-label", label);
  button.title = label;
}

async function toggleBookmark(article, button) {
  const bookmarked = button.getAttribute("aria-pressed") === "true";
  button.disabled = true;
  try {
    if (bookmarked) {
      await api(`/api/articles/${article.id}/bookmarks`, { method: "DELETE" });
    } else {
      await api(`/api/articles/${article.id}/bookmarks`, { method: "POST", body: JSON.stringify({ tags: "", note: "" }) });
    }
    article.bookmarked = !bookmarked;
    renderBookmarkButton(button, article.bookmarked);
    toast(article.bookmarked ? "已收藏" : "已取消收藏");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function formatSpeechTime(seconds) {
  const safe = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function savedPlaybackRate() {
  try {
    const value = Number(localStorage.getItem(PLAYBACK_RATE_KEY) || 1);
    return PLAYBACK_RATES.includes(value) ? value : 1;
  } catch (_error) {
    return 1;
  }
}

function rememberPlaybackRate(rate) {
  try { localStorage.setItem(PLAYBACK_RATE_KEY, String(rate)); } catch (_error) { /* Local storage is optional. */ }
}

function applyNativePlaybackRate(audio, rate) {
  const value = PLAYBACK_RATES.includes(Number(rate)) ? Number(rate) : 1;
  audio.defaultPlaybackRate = value;
  audio.playbackRate = value;
  return value;
}

function setActiveAudioParagraph(root, index = -1) {
  root.querySelectorAll(".paragraph[data-audio-index]").forEach(section => {
    const active = Number(section.dataset.audioIndex) === index;
    section.classList.toggle("is-audio-active", active);
    if (redesignedReadingUi) section.classList.toggle("--active", active);
    if (active) section.setAttribute("aria-current", "true");
    else section.removeAttribute("aria-current");
  });
}

function prepareAudioPlayer(root) {
  if (!redesignedReadingUi) return $(".article-audio-player", root);
  root.audioPlayerBindings?.abort();
  root.audioPlayerBindings = new AbortController();
  return $(".article-audio-player", root);
}

function resetReaderAudio(root) {
  stopArticlePlayback();
  // Replace only audio controls; keep the reading content and its UI state.
  const oldPlayer = $(".article-audio-player", root);
  const player = $("#article-template").content.querySelector(".article-audio-player").cloneNode(true);
  player.setAttribute("aria-label", oldPlayer.getAttribute("aria-label"));
  oldPlayer.replaceWith(player);
  const audio = $("audio.audio, audio.book-audio", root);
  const replacement = audio.cloneNode(false);
  replacement.removeAttribute("src");
  audio.replaceWith(replacement);
}

function setupArticleAudio(article, root) {
  const audio = $(".audio", root);
  const hasAudio = Boolean(article.audio_path) && !["browser", "disabled", "unavailable"].includes(article.audio_status);
  if (hasAudio) {
    audio.src = mobileMediaUrl(article.audio_path, "/api/audio/");
    setupNativeArticlePlayer(article, root, audio);
  } else if (article.audio_status === "browser" && !article.audio_unavailable_detail
      || window.FujimiMobile?.request && article.audio_unavailable_detail) {
    setupBrowserArticlePlayer(article, root);
  }
}

function bindParagraphSeeking(root, seek) {
  root.querySelectorAll(".paragraph[data-audio-index]").forEach(section => {
    const seekTarget = section.querySelector(".japanese") || section;
    const jump = event => {
      if (event.target.closest('a[href]')) return;
      if (redesignedReadingUi && (root.querySelector(".article-audio-player")?.dataset.playing !== "true" || section.classList.contains("is-audio-active"))) return;
      if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
      if (event.type === "click" && !window.getSelection()?.isCollapsed) return;
      event.preventDefault();
      event.stopPropagation();
      seek(Number(section.dataset.audioIndex));
    };
    const options = redesignedReadingUi ? { signal: root.audioPlayerBindings.signal } : undefined;
    seekTarget.addEventListener("click", jump, options);
    seekTarget.addEventListener("keydown", jump, options);
  });
}

function configureOriginalPlaybackRate(root, initialRate, onChange) {
  const toggle = $(".audio-rate-toggle", root);
  const value = $(".audio-rate-value", toggle);
  const menu = $(".audio-rate-menu", root);
  const render = rate => {
    toggle.setAttribute("aria-label", `播放速度，当前 ${rate} 倍`);
    value.textContent = `${Number.isInteger(rate) ? rate.toFixed(1) : rate}x`;
    menu.querySelectorAll("button[data-rate]").forEach(button => {
      button.setAttribute("aria-checked", String(Number(button.dataset.rate) === rate));
    });
  };
  const close = () => {
    menu.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  };
  toggle.onclick = event => {
    event.stopPropagation();
    menu.hidden = !menu.hidden;
    toggle.setAttribute("aria-expanded", String(!menu.hidden));
  };
  menu.querySelectorAll("button[data-rate]").forEach(button => {
    button.onclick = () => {
      const rate = Number(button.dataset.rate);
      rememberPlaybackRate(rate);
      render(rate);
      close();
      onChange(rate);
    };
  });
  root.addEventListener("click", event => { if (!event.target.closest(".audio-rate-control")) close(); });
  render(initialRate);
}

function configurePlaybackRate(root, initialRate, onChange) {
  if (!redesignedReadingUi) return configureOriginalPlaybackRate(root, initialRate, onChange);
  const toggle = $(".audio-rate-toggle", root);
  const value = $(".audio-rate-value", toggle);
  const menu = $(".audio-rate-menu", root);
  const render = rate => {
    toggle.setAttribute("aria-label", `播放速度，当前 ${rate} 倍`);
    value.textContent = `${Number.isInteger(rate) ? rate.toFixed(1) : rate}x`;
    menu.querySelectorAll("button[data-rate]").forEach(button => {
      button.setAttribute("aria-checked", String(Number(button.dataset.rate) === rate));
    });
  };
  const close = () => {
    menu.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  };
  toggle.onclick = event => {
    event.stopPropagation();
    $(".audio-listen-menu", root).hidden = true;
    $(".audio-listen-toggle", root).setAttribute("aria-expanded", "false");
    menu.hidden = !menu.hidden;
    toggle.setAttribute("aria-expanded", String(!menu.hidden));
  };
  menu.querySelectorAll("button[data-rate]").forEach(button => {
    button.onclick = () => {
      const rate = Number(button.dataset.rate);
      rememberPlaybackRate(rate);
      render(rate);
      close();
      toggle.focus({ preventScroll: true });
      onChange(rate);
    };
  });
  root.addEventListener("click", event => { if (!event.target.closest(".audio-rate-control")) close(); }, { signal: root.audioPlayerBindings.signal });
  toggle.addEventListener("keydown", event => {
    if (event.key !== "ArrowDown") return;
    event.preventDefault();
    menu.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    menu.querySelector('[aria-checked="true"]')?.focus();
  });
  menu.addEventListener("keydown", event => {
    const buttons = [...menu.querySelectorAll("button[data-rate]")];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      toggle.focus({ preventScroll: true });
    } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 }[event.key] || 0;
      const target = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + step + buttons.length) % buttons.length;
      buttons[target].focus();
    }
  });
  render(initialRate);
}

function bindPlayerParagraphButtons(player, seekParagraph) {
  if (!redesignedReadingUi) return;
  for (const [selector, step] of [[".audio-player-previous", -1], [".audio-player-next", 1]]) {
    $(selector, player).onclick = () => {
      const target = Number(player.dataset.paragraphIndex || 0) + step;
      if (target >= 0 && target < Number(player.dataset.paragraphCount || 0)) seekParagraph(target);
    };
  }
  const root = player.closest('#book-reader, .article-detail');
  const toggle = $(".audio-listen-toggle", player);
  const menu = $(".audio-listen-menu", player);
  const buttons = [...menu.querySelectorAll('button')];
  const close = () => {
    menu.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  };
  const open = () => {
    $(".audio-rate-menu", player).hidden = true;
    $(".audio-rate-toggle", player).setAttribute('aria-expanded', 'false');
    const original = root.id === 'book-reader' ? root.dataset.languageMode === 'ja' : root.dataset.translationMode === 'hide';
    buttons.forEach(button => {
      if (button.dataset.listeningMode) button.setAttribute('aria-checked', String((button.dataset.listeningMode === 'original') === original));
    });
    menu.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  };
  toggle.onclick = event => { event.stopPropagation(); if (menu.hidden) open(); else close(); };
  toggle.onkeydown = event => { if (event.key === 'ArrowDown') { event.preventDefault(); open(); buttons[0].focus(); } };
  buttons.forEach(button => {
    button.onclick = () => {
      const mode = button.dataset.listeningMode;
      if (mode) {
        if (root.id === 'book-reader') setBookLanguageMode(root, mode === 'original' ? 'ja' : 'parallel');
        else setArticleTranslationView(root, mode === 'original' ? 'hide' : 'show');
      } else seekParagraph(Number(player.dataset.paragraphIndex || 0));
      close();
      toggle.focus({ preventScroll: true });
    };
  });
  menu.onkeydown = event => {
    const index = buttons.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); toggle.focus(); }
    else if (['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
    }
  };
  player.addEventListener('click', event => {
    if (!event.target.closest('.audio-listen-toggle, .audio-listen-menu')) close();
  });
}

function playbackParagraphIndex(segments, position) {
  // Newlines between speech segments still belong to the preceding paragraph.
  for (let index = segments.length - 1; index > 0; index -= 1) {
    if (position + 0.000001 >= segments[index].start) return index;
  }
  return 0;
}

function renderOriginalAudioPlayerChrome(player, { playing, current, duration, progress, maximum }) {
  const toggle = $(".audio-player-toggle", player);
  const icon = $(".audio-player-toggle-icon", toggle);
  const safeMaximum = Math.max(1, Number(maximum) || 1);
  const safeProgress = Math.max(0, Math.min(safeMaximum, Number(progress) || 0));
  toggle.setAttribute("aria-label", playing ? "暂停朗读" : "播放朗读");
  toggle.title = playing ? "暂停朗读" : "播放朗读";
  icon.src = `/static/player_assets/ic_player_${playing ? "play" : "stop"}.png`;
  $(".audio-player-current", player).textContent = formatSpeechTime(current);
  $(".audio-player-duration", player).textContent = formatSpeechTime(duration);
  $(".audio-player-progress-fill", player).style.width = `${safeProgress / safeMaximum * 100}%`;
}

function renderAudioPlayerChrome(player, { playing, current, duration, progress, maximum, paragraphIndex = 0, paragraphCount = 0 }) {
  if (!redesignedReadingUi) return renderOriginalAudioPlayerChrome(player, { playing, current, duration, progress, maximum });
  const toggle = $(".audio-player-toggle", player);
  const safeMaximum = Math.max(1, Number(maximum) || 1);
  const safeProgress = Math.max(0, Math.min(safeMaximum, Number(progress) || 0));
  toggle.setAttribute("aria-label", playing ? "暂停朗读" : "播放朗读");
  toggle.title = playing ? "暂停朗读" : "播放朗读";
  player.dataset.playing = String(Boolean(playing));
  player.dataset.paragraphIndex = String(paragraphIndex);
  player.dataset.paragraphCount = String(paragraphCount);
  $(".audio-player-previous", player).disabled = paragraphCount < 2 || paragraphIndex <= 0;
  $(".audio-player-next", player).disabled = paragraphCount < 2 || paragraphIndex >= paragraphCount - 1;
  $(".audio-player-replay", player).disabled = paragraphCount < 1;
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const artwork = [
    ['.audio-player-toggle-icon', `ic_player_${playing ? 'play' : 'stop'}${dark ? '_dark' : ''}`],
    ['.audio-player-previous img', `ic_player_prev${dark ? '_dark' : ''}`],
    ['.audio-player-next img', `ic_player_next${dark ? '_dark' : ''}`],
    ['.audio-rate-toggle img', `ic_player_set${dark ? '_dark' : ''}`],
    ['.audio-listen-toggle img', dark ? 'ic_common_listen_and_read_dark' : 'ic_common_listen_read'],
  ];
  artwork.forEach(([selector, name]) => {
    const image = $(selector, player);
    const source = `/static/player_assets/${name}.png`;
    if (image.getAttribute('src') !== source) image.src = source;
  });
  $(".audio-player-current", player).textContent = formatSpeechTime(current);
  $(".audio-player-duration", player).textContent = formatSpeechTime(duration);
  $(".audio-player-progress-fill", player).style.width = `${safeProgress / safeMaximum * 100}%`;
}

function audioTimeline(paragraphs, storedSegments, duration) {
  const exact = Array.isArray(storedSegments)
    && storedSegments.length === paragraphs.length
    && storedSegments.every(value => Number(typeof value === "object" ? value?.duration : value) > 0);
  const values = exact
    ? storedSegments.map(value => {
      const segment = typeof value === "object" ? value : { duration: value };
      return {
        duration: Number(segment.duration),
        speechStartOffset: Math.max(0, Number(segment.speech_start_offset) || 0),
      };
    })
    : paragraphs.map(paragraph => ({ duration: Math.max(1, String(paragraph || "").replace(/\s+/g, "").length), speechStartOffset: 0 }));
  const sum = values.reduce((total, value) => total + value.duration, 0) || 1;
  // Edge's sentence offsets already address the saved MP3. Decoder estimates
  // and trailing silence must not move its paragraph starts.
  const edgeTimings = exact && storedSegments.every(segment => segment?.timing_source === "edge_sentence");
  const scale = !edgeTimings && Number.isFinite(duration) && duration > 0 ? duration / sum : 1;
  let cursor = 0;
  return values.map(value => {
    const start = cursor;
    cursor += value.duration * scale;
    return { start, end: cursor, speechStart: Math.min(cursor, start + value.speechStartOffset * scale) };
  });
}

function renderNativeArticleAudio(controller) {
  const { audio, player, root } = controller;
  if (!controller.mobileNative && audio.playbackRate !== controller.rate) applyNativePlaybackRate(audio, controller.rate);
  const duration = controller.mobileNative
    ? Number(controller.mobileStatus?.duration || (Number.isFinite(audio.duration) ? audio.duration : 0))
    : (Number.isFinite(audio.duration) ? audio.duration : 0);
  const position = Math.max(0, controller.mobileNative ? Number(controller.mobileStatus?.position || 0) : (audio.currentTime || 0));
  const current = Math.min(duration || 0, position);
  const playing = controller.mobileNative ? Boolean(controller.mobileStatus?.playing) : (!audio.paused && !audio.ended);
  const progress = $(".audio-player-progress", player);
  progress.max = Math.max(1, duration);
  progress.value = current;
  renderAudioPlayerChrome(player, {
    playing, current, duration, progress: current, maximum: duration,
    paragraphIndex: controller.pendingParagraph ?? playbackParagraphIndex(controller.timeline, position),
    paragraphCount: controller.paragraphCount,
  });
  // Media seeks round to microseconds; accumulated paragraph starts may be slightly larger.
  const boundaryTime = current + 0.000001;
  const active = controller.started
    ? controller.timeline.findIndex(segment => boundaryTime >= segment.start && boundaryTime < segment.end)
    : -1;
  setActiveAudioParagraph(root, active);
}

function setupMobileMediaPlayer(article, root, audio) {
  const player = prepareAudioPlayer(root);
  // Media3 owns native playback on Android. Keep the WebView from opening the
  // same WAV in a second decoder, which can exhaust memory during long reads.
  const mediaSource = audio.currentSrc || audio.src;
  audio.pause();
  audio.preload = "none";
  audio.removeAttribute("src");
  audio.load();
  const controller = { root, player, audio, mediaSource, timeline: [], paragraphCount: (article.paragraphs || []).length, started: false, rate: savedPlaybackRate(), mobileNative: true, mobileStatus: { playing: false, position: 0, duration: 0 }, mobileError: "", timer: null };
  state.articleAudio = controller;
  root.classList.add("has-audio-player");
  player.hidden = false;
  const rebuildTimeline = () => {
    const duration = Number(controller.mobileStatus.duration || (Number.isFinite(audio.duration) ? audio.duration : 0));
    controller.timeline = audioTimeline(article.paragraphs || [], article.audio_segments || [], duration);
    renderNativeArticleAudio(controller);
  };
  const refresh = () => {
    controller.mobileStatus = JSON.parse(window.FujimiMobile.mediaStatus());
    if (controller.mobileStatus.error && controller.mobileStatus.error !== controller.mobileError) {
      controller.mobileError = controller.mobileStatus.error;
      reportArticleAudioError(controller);
    }
    controller.started = controller.started || controller.mobileStatus.playing || controller.mobileStatus.position > 0;
    rebuildTimeline();
    if (controller.mobileStatus.ended) controller.started = false;
  };
  configurePlaybackRate(root, controller.rate, rate => {
    controller.rate = rate;
    window.FujimiMobile.setMediaRate(rate);
    renderNativeArticleAudio(controller);
  });
  controller.timer = window.setInterval(refresh, 300);
  $(".audio-player-toggle", player).onclick = () => {
    if (controller.mobileStatus.playing) {
      window.FujimiMobile.pauseMedia();
      // Keep the Web player responsive while the Media3 service reports its next state.
      controller.mobileStatus.playing = false;
      controller.started = true;
    } else {
      const position = controller.mobileStatus.ended ? 0 : Number(controller.mobileStatus.position || 0);
      const accepted = window.FujimiMobile.playMedia(controller.mediaSource, position, controller.rate);
      if (!accepted) {
        reportArticleAudioError(controller);
      } else {
        controller.mobileError = "";
        controller.mobileStatus.playing = true;
        controller.mobileStatus.ended = false;
        controller.started = true;
      }
    }
    renderNativeArticleAudio(controller);
    window.setTimeout(refresh, 120);
  };
  const progress = $(".audio-player-progress", player);
  progress.oninput = () => {
    const position = Number(progress.value);
    controller.mobileStatus.position = position;
    window.FujimiMobile.seekMedia(position);
    controller.started = true;
    renderNativeArticleAudio(controller);
  };
  const seekParagraph = index => {
    const bounded = Math.max(0, Math.min((article.paragraphs || []).length - 1, index));
    const position = controller.timeline[bounded]?.speechStart || 0;
    const accepted = window.FujimiMobile.playMedia(controller.mediaSource, position, controller.rate);
    if (!accepted) {
      reportArticleAudioError(controller);
      return;
    }
    controller.mobileStatus.position = position;
    controller.mobileStatus.playing = true;
    controller.mobileStatus.ended = false;
    controller.started = true;
    if (redesignedReadingUi) renderNativeArticleAudio(controller);
  };
  bindParagraphSeeking(root, seekParagraph);
  bindPlayerParagraphButtons(player, seekParagraph);
  controller.seekParagraph = seekParagraph;
  rebuildTimeline();
}

function setupNativeArticlePlayer(article, root, audio) {
  if (window.FujimiMobile?.playMedia && /\/api\/(?:(?:articles|bookmarks)\/\d+\/assets|books\/\d+)\/audio\//.test(audio.src)) return setupMobileMediaPlayer(article, root, audio);
  const player = prepareAudioPlayer(root);
  const controller = { root, player, audio, timeline: [], paragraphCount: (article.paragraphs || []).length, started: false, pendingParagraph: null, rate: savedPlaybackRate() };
  state.articleAudio = controller;
  root.classList.add("has-audio-player");
  player.hidden = false;
  applyNativePlaybackRate(audio, controller.rate);
  configurePlaybackRate(root, controller.rate, rate => {
    controller.rate = applyNativePlaybackRate(audio, rate);
    renderNativeArticleAudio(controller);
  });
  const enforcePlaybackRate = () => applyNativePlaybackRate(audio, controller.rate);
  const rebuildTimeline = () => {
    if (audio.readyState < 1) return;
    controller.timeline = audioTimeline(article.paragraphs || [], article.audio_segments || [], audio.duration);
    if (controller.pendingParagraph !== null) {
      const index = controller.pendingParagraph;
      controller.pendingParagraph = null;
      audio.currentTime = controller.timeline[index]?.speechStart || 0;
      controller.started = true;
    }
    renderNativeArticleAudio(controller);
  };
  audio.addEventListener("loadedmetadata", () => { enforcePlaybackRate(); rebuildTimeline(); });
  audio.addEventListener("error", () => reportArticleAudioError(controller));
  audio.addEventListener("canplay", enforcePlaybackRate);
  audio.addEventListener("durationchange", rebuildTimeline);
  audio.addEventListener("timeupdate", () => renderNativeArticleAudio(controller));
  audio.addEventListener("play", () => { enforcePlaybackRate(); controller.started = true; renderNativeArticleAudio(controller); });
  audio.addEventListener("pause", () => renderNativeArticleAudio(controller));
  audio.addEventListener("ended", () => { controller.started = false; setActiveAudioParagraph(root); renderNativeArticleAudio(controller); });
  $(".audio-player-toggle", player).onclick = () => {
    if (audio.ended) audio.currentTime = 0;
    if (audio.paused) {
      audio.play().catch(error => reportArticleAudioError(controller, error));
    }
    else audio.pause();
  };
  const progress = $(".audio-player-progress", player);
  progress.oninput = () => {
    audio.currentTime = Number(progress.value);
    controller.started = true;
    renderNativeArticleAudio(controller);
  };
  const seekParagraph = index => {
    const bounded = Math.max(0, Math.min((article.paragraphs || []).length - 1, index));
    if (audio.readyState < 1) {
      controller.pendingParagraph = bounded;
    } else {
      audio.currentTime = controller.timeline[bounded]?.speechStart || 0;
      controller.started = true;
    }
    audio.play().catch(error => reportArticleAudioError(controller, error));
    if (redesignedReadingUi) renderNativeArticleAudio(controller);
  };
  bindParagraphSeeking(root, seekParagraph);
  bindPlayerParagraphButtons(player, seekParagraph);
  controller.seekParagraph = seekParagraph;
  if (audio.readyState >= 1) rebuildTimeline();
  else renderNativeArticleAudio(controller);
}

function browserSpeechModel(paragraphs) {
  const segments = [];
  let text = "";
  paragraphs.forEach((paragraph, index) => {
    if (index) text += "\n";
    const start = text.length;
    text += String(paragraph || "").trim();
    segments.push({ start, end: text.length });
  });
  return { text, segments };
}

function renderBrowserSpeech(controller) {
  const root = controller.root;
  const totalLength = Math.max(1, controller.text.length);
  const progress = Math.max(0, Math.min(totalLength, controller.index));
  const duration = controller.duration / controller.rate;
  const player = $(".article-audio-player", root);
  player.hidden = false;
  $(".audio-player-progress", player).max = totalLength;
  $(".audio-player-progress", player).value = progress;
  renderAudioPlayerChrome(player, {
    playing: controller.playing,
    current: duration * progress / totalLength,
    duration,
    progress,
    maximum: totalLength,
    paragraphIndex: playbackParagraphIndex(controller.segments, progress),
    paragraphCount: controller.segments.length,
  });
  const active = controller.started && controller.speechReady !== false && progress < totalLength
    ? controller.segments.findIndex(segment => progress >= segment.start && progress <= segment.end)
    : -1;
  setActiveAudioParagraph(root, active);
}

function stopBrowserSpeech(hidePlayer = true) {
  const controller = state.browserSpeech;
  if (!controller) return;
  controller.cancelled = true;
  clearInterval(controller.timer);
  stopDesktopOnlineAudio(controller);
  stopLocalBrowserAudio(controller);
  stopSpeechEngine();
  controller.index = 0;
  controller.playing = false;
  controller.paused = false;
  controller.started = false;
  renderBrowserSpeech(controller);
  setActiveAudioParagraph(controller.root);
  if (hidePlayer) $(".article-audio-player", controller.root).hidden = true;
  state.browserSpeech = null;
}

function stopArticlePlayback(hidePlayer = true) {
  const controller = state.articleAudio;
  if (controller) {
    if (controller.mobileNative) {
      clearInterval(controller.timer);
      window.FujimiMobile.stopMedia();
    } else controller.audio.pause();
    controller.started = false;
    setActiveAudioParagraph(controller.root);
    if (hidePlayer) controller.player.hidden = true;
    state.articleAudio = null;
  }
  stopBrowserSpeech(hidePlayer);
}

function suspendArticlePlayback() {
  const nativeController = state.articleAudio;
  if (nativeController) {
    if (nativeController.mobileNative) {
      window.FujimiMobile.pauseMedia();
      nativeController.mobileStatus.playing = false;
    }
    else nativeController.audio.pause();
    nativeController.started = false;
    setActiveAudioParagraph(nativeController.root);
    nativeController.player.hidden = true;
  }
  const browserController = state.browserSpeech;
  if (browserController) {
    clearInterval(browserController.timer);
    stopDesktopOnlineAudio(browserController);
    stopLocalBrowserAudio(browserController);
    stopSpeechEngine();
    browserController.playing = false;
    browserController.paused = false;
    browserController.started = false;
    browserController.needsRestart = true;
    browserController.cancelled = false;
    setActiveAudioParagraph(browserController.root);
    $(".article-audio-player", browserController.root).hidden = true;
  }
}

function resumeArticlePlayback(root) {
  let restored = false;
  const nativeController = state.articleAudio;
  if (nativeController?.root.isConnected && (!redesignedReadingUi || nativeController.root === root)) {
    nativeController.player.hidden = false;
    renderNativeArticleAudio(nativeController);
    restored = true;
  }
  const browserController = state.browserSpeech;
  if (browserController?.root.isConnected && (!redesignedReadingUi || browserController.root === root)) {
    $(".article-audio-player", browserController.root).hidden = false;
    renderBrowserSpeech(browserController);
    restored = true;
  }
  return restored;
}

function startBrowserSpeechTimer(controller) {
  clearInterval(controller.timer);
  controller.lastTick = performance.now();
  controller.timer = setInterval(() => {
    const now = performance.now();
    const elapsed = (now - controller.lastTick) / 1000;
    controller.lastTick = now;
    if (!controller.playing || controller.paused || controller.cancelled) return;
    controller.index = advanceBrowserSpeechIndex(controller, elapsed);
    renderBrowserSpeech(controller);
  }, 250);
}

function stopDesktopOnlineAudio(controller) {
  controller.onlineAbort?.abort();
  controller.onlineAbort = null;
  controller.onlineAudio?.pause();
  controller.onlineAudio = null;
  if (controller.onlineUrl) URL.revokeObjectURL(controller.onlineUrl);
  controller.onlineUrl = null;
}

function stopLocalBrowserAudio(controller) {
  controller.localAbort?.abort();
  controller.localAbort = null;
  controller.localAudio?.pause();
  controller.localAudio = null;
  if (controller.localUrl) URL.revokeObjectURL(controller.localUrl);
  controller.localUrl = null;
}

async function speakLocalBrowserChunk(controller, voice, token) {
  if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
  const start = Math.round(controller.index);
  if (start >= controller.text.length) {
    controller.playing = false;
    controller.started = false;
    renderBrowserSpeech(controller);
    return;
  }
  const text = controller.text.slice(start, start + 1200);
  const abort = new AbortController();
  controller.localAbort = abort;
  try {
    const blob = await synthesizeLocalBrowserSpeech(text, voice, abort.signal);
    if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    controller.localUrl = url;
    controller.localAudio = audio;
    audio.playbackRate = controller.rate;
    audio.ontimeupdate = () => {
      if (controller.token !== token || !Number.isFinite(audio.duration) || !audio.duration) return;
      controller.index = start + text.length * audio.currentTime / audio.duration;
      renderBrowserSpeech(controller);
    };
    audio.onended = () => {
      if (controller.token !== token) return;
      stopLocalBrowserAudio(controller);
      controller.index = start + text.length;
      renderBrowserSpeech(controller);
      void speakLocalBrowserChunk(controller, voice, token);
    };
    audio.onerror = () => {
      if (controller.token !== token) return;
      stopLocalBrowserAudio(controller);
      controller.playing = false;
      controller.needsRestart = true;
      renderBrowserSpeech(controller);
      notice('本地声线音频播放失败。', true);
    };
    await audio.play();
  } catch (error) {
    if (controller.token !== token || abort.signal.aborted) return;
    stopLocalBrowserAudio(controller);
    controller.playing = false;
    controller.needsRestart = true;
    renderBrowserSpeech(controller);
    notice(error.message || '本地声线合成失败。', true);
  }
}

async function speakDesktopOnlineChunk(controller, voice, token) {
  if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
  const start = Math.round(controller.index);
  if (start >= controller.text.length) {
    controller.playing = false;
    controller.started = false;
    renderBrowserSpeech(controller);
    return;
  }
  const text = controller.text.slice(start, start + 1200);
  const abort = new AbortController();
  controller.onlineAbort = abort;
  try {
    const blob = await synthesizeDesktopOnlineSpeech(text, voice, abort.signal);
    if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    controller.onlineUrl = url;
    controller.onlineAudio = audio;
    audio.playbackRate = controller.rate;
    audio.ontimeupdate = () => {
      if (controller.token !== token || !Number.isFinite(audio.duration) || !audio.duration) return;
      controller.index = start + text.length * audio.currentTime / audio.duration;
      renderBrowserSpeech(controller);
    };
    audio.onended = () => {
      if (controller.token !== token) return;
      stopDesktopOnlineAudio(controller);
      controller.index = start + text.length;
      renderBrowserSpeech(controller);
      void speakDesktopOnlineChunk(controller, voice, token);
    };
    audio.onerror = () => {
      if (controller.token !== token) return;
      stopDesktopOnlineAudio(controller);
      controller.playing = false;
      controller.needsRestart = true;
      renderBrowserSpeech(controller);
      notice('在线朗读音频播放失败。', true);
    };
    await audio.play();
  } catch (error) {
    if (controller.token !== token || abort.signal.aborted) return;
    stopDesktopOnlineAudio(controller);
    controller.playing = false;
    controller.needsRestart = true;
    renderBrowserSpeech(controller);
    notice(error.message || '在线朗读失败。', true);
  }
}

async function speakBrowserSpeech(controller, startIndex = 0) {
  const bookVoice = controller.root.id === "book-reader" ? $(".book-voice", controller.root)?.value : "";
  if (bookVoice ? mobileSelectionNeedsPc(mobileSpeechSelection(bookVoice)) : mobileVoiceNeedsPc(controller.browserVoiceName || state.browserVoiceName)) {
    try {
      const selection = await api("/api/settings/voice-mode");
      const paragraph = Math.max(0, controller.segments.findIndex(segment => startIndex >= segment.start && startIndex < segment.end));
      await generateMobilePcSpeech(controller.root, bookVoice ? mobileSpeechSelection(bookVoice) : selection, { autoplay: true, paragraph });
    } catch (error) { setRereadTask(controller.root, "failed", error.message || "PC 朗读失败。"); }
    return;
  }
  if (window.FujimiMobile?.request && controller.article?.id) {
    if (controller.savingAudio) return;
    controller.savingAudio = true;
    const button = $(".audio-player-toggle", controller.root);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    setRereadTask(controller.root, "running", "音声生成を準備しています…", "", "", 0, 1, { cancellable: false });
    const target = controller.root.parentElement;
    const paragraph = Math.max(0, controller.segments.findIndex(segment => startIndex >= segment.start && startIndex < segment.end));
    try {
      const result = await api(`/api/articles/${controller.article.id}/edge-tts`, {
        method: "POST", body: JSON.stringify({ voice: controller.browserVoiceName || state.browserVoiceName }),
      });
      if (state.browserSpeech !== controller || !controller.root.isConnected) return;
      openArticle(result.article, target);
      const player = state.articleAudio;
      if (player?.root.isConnected) player.seekParagraph(paragraph);
    } catch (error) {
      if (controller.root.isConnected) setRereadTask(controller.root, "failed", "音声生成に失敗しました。", "", error.message);
    } finally {
      controller.savingAudio = false;
      if (button.isConnected) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        renderBrowserSpeech(controller);
      }
    }
    return;
  }
  stopDesktopOnlineAudio(controller);
  stopLocalBrowserAudio(controller);
  stopSpeechEngine();
  controller.cancelled = false;
  controller.index = Math.max(0, Math.min(controller.text.length, Math.round(startIndex)));
  controller.offset = controller.index;
  controller.paused = false;
  controller.playing = true;
  controller.started = true;
  controller.speechReady = true;
  controller.needsRestart = false;
  controller.token += 1;
  const token = controller.token;
  const browserVoice = window.FujimiMobile?.speak ? null : await resolveJapaneseBrowserVoice({ persistDefault: true, preferredName: controller.browserVoiceName || '' });
  if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
  if (!window.FujimiMobile?.speak && !browserVoice) {
    controller.playing = false;
    controller.started = false;
    controller.needsRestart = true;
    renderBrowserSpeech(controller);
    notice(controller.browserVoiceName ? "此示例选择的 Edge 声线不可用，请重新选择声线。" : "未检测到 Edge 在线声线，请检查网络后重试。", true);
    return;
  }
  if (browserVoice?.local) {
    controller.hasBoundaryEvents = true;
    renderBrowserSpeech(controller);
    void speakLocalBrowserChunk(controller, browserVoice, token);
    return;
  }
  if (browserVoice?.id) {
    controller.hasBoundaryEvents = true;
    renderBrowserSpeech(controller);
    void speakDesktopOnlineChunk(controller, browserVoice, token);
    return;
  }
  const finish = () => {
    if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
    controller.index = controller.text.length;
    controller.playing = false;
    controller.paused = false;
    controller.started = false;
    controller.speechReady = false;
    clearInterval(controller.timer);
    renderBrowserSpeech(controller);
  };
  const fail = error => {
    const event = typeof error === "string" ? { error } : error;
    if (event.error === "canceled" || state.browserSpeech !== controller || controller.token !== token) return;
    controller.playing = false;
    controller.paused = false;
    clearInterval(controller.timer);
    renderBrowserSpeech(controller);
    notice("浏览器朗读失败，请检查系统语音设置。", true);
  };
  if (!window.FujimiMobile?.speak) {
    controller.hasBoundaryEvents = true;
    controller.speechReady = false;
    // A boundary can announce the next paragraph before its audio starts.
    const speakParagraph = (paragraphIndex, position) => {
      const segment = controller.segments[paragraphIndex];
      if (!segment) return finish();
      const start = Math.max(segment.start, position);
      if (start >= segment.end) return speakParagraph(paragraphIndex + 1, controller.segments[paragraphIndex + 1]?.start || controller.text.length);
      const speech = new SpeechSynthesisUtterance(controller.text.slice(start, segment.end));
      speech.voice = browserVoice;
      speech.lang = browserVoice.lang;
      speech.rate = controller.rate;
      speech.onstart = () => {
        if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
        controller.index = start;
        controller.speechReady = true;
        renderBrowserSpeech(controller);
      };
      speech.onboundary = event => {
        if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
        controller.index = Math.min(segment.end, Math.max(controller.index, start + event.charIndex));
        renderBrowserSpeech(controller);
      };
      speech.onend = () => {
        if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
        controller.index = segment.end;
        controller.speechReady = false;
        renderBrowserSpeech(controller);
        speakParagraph(paragraphIndex + 1, controller.segments[paragraphIndex + 1]?.start || controller.text.length);
      };
      speech.onerror = fail;
      controller.utterance = speech;
      speechSynthesis.speak(speech);
    };
    renderBrowserSpeech(controller);
    const first = controller.segments.findIndex(segment => segment.end > controller.index);
    speakParagraph(first < 0 ? controller.segments.length : first, controller.index);
    return;
  }
  controller.hasBoundaryEvents = false;
  controller.utterance = null;
  startBrowserSpeechTimer(controller);
  renderBrowserSpeech(controller);
  controller.nativeTtsId = mobileSpeak(controller.text.slice(controller.offset), controller.rate, event => {
    if (state.browserSpeech !== controller || controller.token !== token || controller.cancelled) return;
    if (event === "done") finish();
    else if (event === "error") fail("error");
  }, controller.browserVoiceName || "");
}

function setupBrowserArticlePlayer(article, root) {
  if (!window.FujimiMobile?.speak && !window.speechSynthesis && !(typeof localBrowserVoice === "function" && localBrowserVoice(state.browserVoiceName))) return notice("当前设备不支持语音朗读", true);
  const model = browserSpeechModel(article.paragraphs || []);
  if (!model.text) return notice("没有可朗读的正文", true);
  const player = prepareAudioPlayer(root);
  root.classList.add("has-audio-player");
  player.hidden = false;
  const charactersPerSecond = 6.4;
  const controller = {
    root,
    text: model.text,
    article,
    textLength: model.text.length,
    segments: model.segments,
    index: 0,
    offset: 0,
    duration: Math.max(1, model.text.length / charactersPerSecond),
    charactersPerSecond,
    rate: savedPlaybackRate(),
    browserVoiceName: article.example_browser_voice_name || state.browserVoiceName || '',
    hasBoundaryEvents: false,
    playing: false,
    paused: false,
    started: false,
    needsRestart: false,
    cancelled: false,
    timer: null,
    token: 0,
    lastTick: performance.now(),
    utterance: null,
  };
  state.browserSpeech = controller;
  configurePlaybackRate(root, controller.rate, rate => {
    controller.rate = rate;
    if (controller.playing) speakBrowserSpeech(controller, controller.index);
    else if (controller.paused) {
      stopSpeechEngine();
      controller.playing = false;
      controller.needsRestart = true;
    }
    renderBrowserSpeech(controller);
  });
  $(".audio-player-toggle", player).onclick = () => {
    if (controller.index >= controller.text.length) controller.index = 0;
    if (!controller.started || controller.needsRestart) {
      speakBrowserSpeech(controller, controller.index);
    } else if (controller.paused) {
      if (window.FujimiMobile?.speak) speakBrowserSpeech(controller, controller.index);
      else if (controller.localAudio) {
        controller.localAudio.play().catch(() => notice('本地声线音频播放失败。', true));
        controller.paused = false;
        controller.playing = true;
        renderBrowserSpeech(controller);
      }
      else if (controller.onlineAudio) {
        controller.onlineAudio.play().catch(() => notice('在线朗读音频播放失败。', true));
        controller.paused = false;
        controller.playing = true;
        renderBrowserSpeech(controller);
      }
      else {
        speechSynthesis.resume();
        controller.paused = false;
        controller.playing = true;
        controller.lastTick = performance.now();
        renderBrowserSpeech(controller);
      }
    } else {
      if (window.FujimiMobile?.speak) {
        window.FujimiMobile.stopSpeaking();
        controller.needsRestart = true;
      } else if (controller.localAudio) controller.localAudio.pause();
      else if (controller.onlineAudio) controller.onlineAudio.pause();
      else speechSynthesis.pause();
      controller.paused = true;
      controller.playing = false;
      renderBrowserSpeech(controller);
    }
  };
  const progress = $(".audio-player-progress", player);
  progress.oninput = () => {
    if (controller.playing) {
      if (window.FujimiMobile?.speak) window.FujimiMobile.stopSpeaking();
      else if (controller.localAudio) stopLocalBrowserAudio(controller);
      else if (controller.onlineAudio) stopDesktopOnlineAudio(controller);
      else speechSynthesis.pause();
    }
    controller.paused = true;
    controller.playing = false;
    controller.started = true;
    controller.needsRestart = true;
    controller.index = Number(progress.value);
    renderBrowserSpeech(controller);
  };
  progress.onchange = () => speakBrowserSpeech(controller, Number(progress.value));
  const seekParagraph = index => {
    const bounded = Math.max(0, Math.min(controller.segments.length - 1, index));
    speakBrowserSpeech(controller, controller.segments[bounded]?.start || 0);
  };
  bindParagraphSeeking(root, seekParagraph);
  bindPlayerParagraphButtons(player, seekParagraph);
  renderBrowserSpeech(controller);
}

async function loadBookmarks() {
  try {
    const articles = await api("/api/bookmarks");
    const list = $("#bookmarks-list");
    if (!articles.length) { list.innerHTML = '<p class="empty">心に残る一篇を、ここへ。</p>'; return; }
    list.replaceChildren(...articles.map(article => {
      const card = document.createElement("article");
      card.className = "news-card bookmark-card";
      card.innerHTML = `<button class="bookmark-card-toggle bookmark icon-tool is-bookmarked" type="button" aria-label="取消收藏" aria-pressed="true" title="取消收藏"><svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg></button><span class="source">${escapeText(article.source_name)}</span><h3>${escapeText(article.title)}</h3><p class="muted">${escapeText(article.tags || "无标签")}</p><button class="bookmark-read" type="button">阅读する</button>`;
      $(".bookmark-read", card).onclick = () => openArticleInReader(article);
      $(".bookmark-card-toggle", card).onclick = async () => {
        try {
          await api(`/api/articles/${article.id}/bookmarks`, { method: "DELETE" });
          toast("已取消收藏");
          await loadBookmarks();
        } catch (error) { toast(error.message, true); }
      };
      return card;
    }));
  } catch (error) { notice(error.message, true); }
}

async function generateDaily() {
  try {
    const result = await api("/api/daily/generate", { method: "POST" });
    panelError("#schedule-error");
    if (result.status === "already_exists") {
      renderTaskStatus({ status: "completed", stage: "complete", percent: 100, message: "今日日刊已生成", completed: 1, total: 1 });
    } else if (result.status === "started" || result.status === "already_running") {
      state.dailyTaskRunning = true;
      renderTaskStatus({ status: "running", stage: "starting", percent: 0, message: "正在准备生成日刊ニュース", completed: 0, total: 0 });
      taskStatus();
    }
  } catch (error) { panelError("#schedule-error", error.message); }
}

async function stopDailyGeneration({ notify = true } = {}) {
  const button = $("#cancel-daily");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/tasks/daily", { method: "DELETE" });
    if (state.dailyTaskTimer) clearTimeout(state.dailyTaskTimer);
    state.dailyTaskTimer = null;
    state.dailyTaskRunning = false;
    renderTaskStatus(result.task || { status: "cancelled", stage: "cancelled", percent: 0, message: "日刊ニュースの生成を中止しました" });
    if (result.status === "cancelled") {
      await Promise.all([loadDays(), loadDaily()]);
    }
    if (notify) toast(result.status === "cancelled" ? "日刊ニュースの生成を中止しました" : "実行中の生成はありません");
    return result;
  } catch (error) {
    panelError("#schedule-error", error.message);
    if (button) button.disabled = false;
    throw error;
  }
}

const taskStageNames = {
  starting: "准备任务",
  collecting: "提取公开候选",
  selecting: "选择日刊",
  processing: "后处理日刊",
  media: "保存媒体",
  enhancing: "生成假名与翻译",
  tts: "生成朗读",
  complete: "处理完成",
  partial: "本轮公开候选不足",
  interrupted: "上次任务被中断",
  cancelled: "生成已中止",
  failed: "处理失败",
  idle: "当前没有任务",
};

function renderTaskStatus(task) {
  const container = $("#task-status");
  const running = task.status === "running";
  const completed = Number(task.completed || 0);
  const total = Number(task.total || 0);
  const segmentCompleted = Number(task.segment_completed || 0);
  const segmentTotal = Number(task.segment_total || 0);
  const count = total ? `${Math.min(completed, total)}/${total}` : "";
  const segment = segmentTotal ? `段落 ${Math.min(segmentCompleted, segmentTotal)}/${segmentTotal}` : "";
  const current = task.current ? String(task.current) : "";
  container.classList.toggle("is-idle", task.status === "idle");
  container.classList.toggle("is-running", running);
  container.classList.toggle("is-failed", ["failed", "partial"].includes(task.status));
  $("#task-stage").textContent = taskStageNames[task.stage] || task.message || "处理任务";
  $("#task-count").textContent = count;
  $("#task-progress").value = Math.max(0, Math.min(100, Number(task.percent || 0)));
  const lastError = task.errors?.length ? `最近错误：${task.errors[task.errors.length - 1]}` : "";
  const candidateStats = Object.values(task.candidate_stats || {});
  const candidateSummary = candidateStats.length
    ? `候选验证：公开 ${candidateStats.reduce((sum, stats) => sum + Number(stats.public || 0), 0)} 篇` +
      (candidateStats.some(stats => Number(stats.invalid_excluded || 0) || Number(stats.network_failed || 0))
        ? `，不可用 ${candidateStats.reduce((sum, stats) => sum + Number(stats.invalid_excluded || 0) + Number(stats.network_failed || 0), 0)} 篇`
        : "")
    : "";
  const selected = Number(task.selected || 0);
  const selection = running && selected ? `已选 ${selected}/${total} 篇` : "";
  $("#task-detail").textContent = [task.message, selection, segment, running ? current : "", candidateSummary, lastError]
    .filter(Boolean).join(" · ");
  const generateButton = $("#generate-daily");
  const cancelButton = $("#cancel-daily");
  generateButton.hidden = running;
  generateButton.disabled = running || mobileNodeStatus?.daily_generation_available === false;
  cancelButton.hidden = !running;
  cancelButton.disabled = false;
}

async function taskStatus() {
  if (state.dailyTaskTimer) clearTimeout(state.dailyTaskTimer);
  try {
    const result = await api("/api/tasks/daily");
    const wasRunning = state.dailyTaskRunning;
    state.dailyTaskRunning = result.status === "running";
    renderTaskStatus(result);
    panelError("#schedule-error");
    if (state.dailyTaskRunning) state.dailyTaskTimer = setTimeout(taskStatus, 800);
    else if (wasRunning && ["completed", "partial"].includes(result.status)) {
      await loadDaily();
    }
  } catch (error) {
    panelError("#schedule-error", error.message);
    state.dailyTaskTimer = setTimeout(taskStatus, 2000);
  }
}

function selectDailyMode(mode) {
  state.dailyMode = mode;
  document.querySelectorAll("#daily-mode button").forEach(button => button.classList.toggle("active", button.dataset.mode === mode));
  const timeRow = $("#daily-time-row");
  timeRow.hidden = false;
  timeRow.classList.toggle("is-inactive", mode !== "automatic");
  timeRow.setAttribute("aria-hidden", String(mode !== "automatic"));
  $("#daily-update-time").disabled = mode !== "automatic";
}

function renderDailySchedule(schedule) {
  selectDailyMode(schedule.mode);
  $("#daily-update-time").value = schedule.time;
  const automatic = schedule.mode === "automatic";
  $("#schedule-state").textContent = automatic ? "自動更新" : "手動生成";
  $("#schedule-sidebar-summary").innerHTML = automatic ? `日刊：${escapeText(schedule.time)} CST 自動<br>完成した記事から順次公開` : "日刊：手動生成<br>完成した記事から順次公開";
  const nextRun = schedule.next_run ? new Date(schedule.next_run).toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" }) : null;
  const precision = schedule.schedule_precision === "window" ? "（系统时间窗口，可能延后）" : "";
  $("#schedule-summary").textContent = schedule.scheduler_available === false ? "Android 日刊采集与自动调度尚未接入。" : automatic ? `每天 ${schedule.time}（CST）自动更新${precision}${nextRun ? `；下次安排：${nextRun} CST` : ""}${schedule.background_detail ? `。${schedule.background_detail}` : ""}` : "自动更新已关闭。需要时使用“今すぐ生成”。";
  const automaticButton = $("#daily-mode [data-mode='automatic']");
  if (automaticButton) automaticButton.disabled = schedule.scheduler_available === false;
}

async function loadDailySettings() {
  try { renderDailySchedule(await api("/api/settings/daily-schedule")); panelError("#schedule-error"); }
  catch (error) { panelError("#schedule-error", error.message); }
}

function renderLibrarySettings(settings) {
  state.librarySort = settings.sort || "recent";
  // Keep the current choice when an older running backend does not return this field.
  if (typeof settings.lookup_chinese_translations === "boolean") {
    state.libraryLookupChineseTranslations = settings.lookup_chinese_translations;
  }
  const select = $("#library-sort-setting");
  if (select) select.value = state.librarySort;
}

async function loadLibrarySettings() {
  try {
    renderLibrarySettings(await api("/api/settings/library"));
    panelError("#library-settings-error");
  } catch (error) { panelError("#library-settings-error", error.message); }
}

async function updateLibrarySettings() {
  const select = $("#library-sort-setting");
  if (!select) return;
  try {
    renderLibrarySettings(await api("/api/settings/library", { method: "PUT", body: JSON.stringify({ sort: select.value, lookup_chinese_translations: state.libraryLookupChineseTranslations }) }));
    panelError("#library-settings-error");
  } catch (error) {
    panelError("#library-settings-error", error.message);
    await loadLibrarySettings();
  }
}

async function updateLibraryChineseLookup(checked) {
  const previous = state.libraryLookupChineseTranslations;
  state.libraryLookupChineseTranslations = checked;
  try {
    renderLibrarySettings(await api("/api/settings/library", { method: "PUT", body: JSON.stringify({ sort: state.librarySort, lookup_chinese_translations: checked }) }));
    panelError("#library-settings-error");
  } catch (error) {
    state.libraryLookupChineseTranslations = previous;
    panelError("#library-settings-error", error.message);
    await loadLibrarySettings();
  }
}

async function updateDailySettings() {
  try {
    const schedule = await api("/api/settings/daily-schedule", { method: "PUT", body: JSON.stringify({ mode: state.dailyMode, time: $("#daily-update-time").value || "00:00" }) });
    renderDailySchedule(schedule);
    panelError("#schedule-error");
  } catch (error) {
    panelError("#schedule-error", error.message);
    await loadDailySettings();
  }
}

async function refreshStorage() {
  const button = $("#refresh-storage");
  button.disabled = true;
  button.textContent = "刷新中…";
  panelError("#refresh-error");
  try {
    const result = await api("/api/settings/refresh-storage", { method: "POST" });
    const invalid = result.invalid_article_folders.length + result.invalid_bookmark_folders.length + (result.invalid_book_records?.length || 0);
    const cleanupFailed = result.backup_cleanup_failed?.length || 0;
    const logCleanupFailed = result.log_cleanup_failed?.length || 0;
    const cleanup = `；SQLite 已整理，清理备份 ${result.backups_removed || 0} 个${cleanupFailed ? `，失败 ${cleanupFailed} 个` : ""}`;
    $("#refresh-result").textContent = `扫描 ${result.articles_scanned} 篇；新增 ${result.articles_added}，更新 ${result.articles_updated}，删除 ${result.articles_removed}；收藏同步 ${result.bookmarks_updated}，删除 ${result.bookmarks_removed}；书架扫描 ${result.books_scanned || 0} 册，清理 ${result.books_removed || 0} 册；章节音频缓存清理 ${result.book_audio_caches_removed || 0} 条${cleanup}${invalid ? `；异常目录 ${invalid}` : ""}`;
    $("#refresh-result").textContent += `；清理日志 ${result.logs_removed || 0} 个${logCleanupFailed ? `，失败 ${logCleanupFailed} 个` : ""}`;
    if (result.book_records_backup) $("#refresh-result").textContent += "；已备份失效书籍记录";
    const library = await api(`/api/books?sort=${encodeURIComponent(state.librarySort || "recent")}`);
    const bookIds = new Set((library.books || []).map(book => Number(book.id)));
    if (state.libraryChapter && !bookIds.has(Number(state.libraryChapter.book.id))) {
      if (state.libraryProgressTimer) clearTimeout(state.libraryProgressTimer);
      if (state.libraryTaskTimer) clearTimeout(state.libraryTaskTimer);
      state.libraryProgressTimer = null;
      state.libraryTaskTimer = null;
      stopArticlePlayback();
      state.libraryChapter = null;
      state.libraryBook = null;
      state.libraryTaskId = null;
      $("#book-reader").replaceChildren();
      $("#book-reader").hidden = true;
    }
    if (state.libraryBook && !bookIds.has(Number(state.libraryBook.id))) state.libraryBook = null;
    if (state.editingBookId && !bookIds.has(Number(state.editingBookId))) closeBookEditor();
    renderLibrary(library);
    await Promise.all([loadDaily(), loadBookmarks()]);
  } catch (error) {
    panelError("#refresh-error", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "存储を反映";
  }
}

async function loadVoices() {
  try {
    const [voices, mode] = await Promise.all([api("/api/settings/voices"), api("/api/settings/voice-mode")]);
    try {
      const catalog = await api("/api/browser-voices");
      if (Array.isArray(catalog)) state.browserVoices = catalog;
    } catch (_error) { state.browserVoices = []; }
    const list = $("#voice-list");
    list.replaceChildren();
    const activeVoice = voices.find(voice => voice.active);
    state.voices = voices;
    state.voiceMode = mode.mode;
    applyBrowserVoiceSettings(mode);
    const fallbackBrowserVoice = configuredBrowserVoice();
    const selectedBrowserName = browserVoiceShortName(state.browserVoiceName || fallbackBrowserVoice?.name || "");
    const browserTitle = window.FujimiMobile
      ? `システム音声${selectedBrowserName ? `（${selectedBrowserName}）` : "（未选择）"}`
      : `${state.browserVoiceLabel}音声${selectedBrowserName ? `（${selectedBrowserName}）` : ""}`;
    // $("#active-voice-badge").textContent = mode.mode === "browser" ? browserTitle : mode.mode === "voice" && activeVoice ? activeVoice.name : "未选择声线";
    $("#active-voice-badge").textContent =
      mode.mode === "browser"
          ? window.FujimiMobile ? `システム音声${selectedBrowserName ? `（${selectedBrowserName}）` : ""}` : (selectedBrowserName || "ブラウザー")
        : mode.mode === "voice" && activeVoice
          ? activeVoice.name
          : "未选择声线";

    const appendVoice = (voice, { isBrowser = false } = {}) => {
      const row = document.createElement("div");
      row.className = "voice-row";
      const active = isBrowser ? mode.mode === "browser" : mode.mode === "voice" && voice.active;
      if (isMobileDrawerLayout()) {
        row.innerHTML = `<span class="voice-mark">${isBrowser ? "B" : escapeText(voice.name.slice(0, 1))}</span><span class="voice-copy"><span class="voice-name">${escapeText(voice.name)}</span>${active ? '<span class="voice-detail">使用中</span>' : ""}</span><details class="voice-actions-menu"><summary aria-label="管理${escapeText(voice.name)}" title="管理声线"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.7"></circle><circle cx="12" cy="12" r="1.7"></circle><circle cx="19" cy="12" r="1.7"></circle></svg></summary><span class="voice-actions"><button class="select ${active ? "" : "quiet"}" ${active ? "disabled" : ""}>${active ? "使用中" : "使用"}</button><button class="edit quiet">修改</button>${isBrowser ? "" : '<button class="delete quiet">删除</button>'}</span></details>`;
      } else {
        row.innerHTML = `<span class="voice-mark">${isBrowser ? "B" : escapeText(voice.name.slice(0, 1))}</span><span class="voice-copy"><span class="voice-name">${escapeText(voice.name)}</span></span><span class="voice-actions"><button class="select ${active ? "" : "quiet"}" ${active ? "disabled" : ""}>${active ? "使用中" : "使用"}</button><button class="edit quiet">修改</button>${isBrowser ? "" : '<button class="delete quiet">删除</button>'}</span>`;
      }
      $(".select", row).onclick = async () => {
        $(".voice-actions-menu", row)?.removeAttribute("open");
        try {
          await api("/api/settings/active-voice", { method: "PUT", body: JSON.stringify({ voice_id: isBrowser ? null : voice.id, disabled: false, browser: isBrowser }) });
          await loadVoices();
          panelError("#voice-error");
        } catch (error) { panelError("#voice-error", error.message); }
      };
      const editButton = $(".edit", row);
      const readOnly = Boolean(window.FujimiMobile && voice.read_only);
      editButton.hidden = readOnly;
      editButton.onclick = () => {
        $(".voice-actions-menu", row)?.removeAttribute("open");
        if (isBrowser) openBrowserVoiceDialog();
        else openVoiceDialog(voice);
      };
      const deleteButton = $(".delete", row);
      if (deleteButton) deleteButton.hidden = readOnly;
      if (deleteButton) deleteButton.onclick = async () => {
        $(".voice-actions-menu", row)?.removeAttribute("open");
        if (!confirm(`删除声线“${voice.name}”？`)) return;
        try {
          await api(`/api/settings/voices/${voice.id}`, { method: "DELETE" });
          await Promise.all([loadVoices(), loadNewsSources()]);
          panelError("#voice-error");
        } catch (error) { panelError("#voice-error", error.message); }
      };
      if (window.FujimiMobile && voice.saved_audio_only) {
        const detail = $(".voice-detail", row) || document.createElement("span");
        detail.className = "voice-detail";
        detail.textContent = `${active ? "使用中 · " : ""}播放已同步音频`;
        $(".voice-copy", row).append(detail);
      }
      list.append(row);
    };
    appendVoice({ id: null, name: browserTitle, saved_audio_only: localBrowserVoice(state.browserVoiceName)?.saved_audio_only }, { isBrowser: true });
    voices.forEach(voice => appendVoice(voice));
  } catch (error) { panelError("#voice-error", error.message); }
}

function renderDailyContentSettings(content) {
  $("#daily-target-count").value = content.target_count;
  $("#daily-source-total").textContent = `${content.source_count} 个来源`;
  $("#daily-content-summary").textContent = `${content.source_count} 个来源；各来源最低配额共 ${content.required_count} 篇，其余 ${Math.max(0, content.target_count - content.required_count)} 篇按时效与主题补足。`;
}

function sourceVoiceValue(source) {
  return source?.voice_mode === "voice" && source.voice_id ? `voice:${source.voice_id}` : source?.voice_mode || "inherit";
}

function sourceVoiceSettings(value) {
  if (value.startsWith("voice:")) return { voice_mode: "voice", voice_id: Number(value.split(":", 2)[1]) };
  return { voice_mode: value, voice_id: null };
}

function populateSourceVoiceSelect(select, selected = "inherit") {
  select.replaceChildren(
    new Option("沿用全局声线", "inherit"),
    new Option("模型默认声线", "model"),
    new Option(window.FujimiMobile ? "システム音声" : "ブラウザー音声", "browser"),
    new Option("朗読なし", "none"),
    ...state.voices.map(voice => new Option(voice.name, `voice:${voice.id}`)),
  );
  if (window.FujimiMobile && (mobileNodeStatus?.reference_synthesis_available ?? mobileNodeStatus?.reference_voices_available) === false) {
    const model = [...select.options].find(option => option.value === "model");
    if (model) model.disabled = true;
  }
  select.value = [...select.options].some(option => option.value === selected) ? selected : "inherit";
}

function newsSourcePayload(source, minimumCount, voiceValue) {
  return {
    name: source.name,
    homepage: source.homepage,
    minimum_count: minimumCount,
    ...sourceVoiceSettings(voiceValue),
  };
}

async function loadNewsSources() {
  try {
    const [sources, content, voices] = await Promise.all([
      api("/api/settings/news-sources"),
      api("/api/settings/daily-content"),
      api("/api/settings/voices"),
    ]);
    state.newsSources = sources;
    state.voices = voices;
    $("#source-count").textContent = `${sources.length} 个来源`;
    renderDailyContentSettings(content);
    const list = $("#source-list");
    list.replaceChildren();
    if (!sources.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "尚未添加新闻来源。";
      list.append(empty);
    }
    sources.forEach(source => {
      const row = document.createElement("div");
      row.className = "source-row";
      if (isMobileDrawerLayout()) {
        row.innerHTML = `<span class="source-mark">${escapeText(source.name.slice(0, 1))}</span><span class="source-details"><strong>${escapeText(source.name)}</strong><a target="_blank" rel="noreferrer"></a></span><label class="source-minimum"><span>最少</span><input type="number" inputmode="numeric" min="0" max="100" value="${source.minimum_count}" aria-label="${escapeText(source.name)} 最少新闻数"></label><details class="source-actions-menu"><summary aria-label="管理${escapeText(source.name)}" title="管理来源"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.7"></circle><circle cx="12" cy="12" r="1.7"></circle><circle cx="19" cy="12" r="1.7"></circle></svg></summary><span class="source-actions"><button class="edit quiet">修改</button><button class="delete quiet">删除</button></span></details>`;
      } else {
        row.innerHTML = `<span class="source-mark">${escapeText(source.name.slice(0, 1))}</span><span class="source-details"><strong>${escapeText(source.name)}</strong><a target="_blank" rel="noreferrer"></a></span><label class="source-minimum">至少 <input type="number" min="0" max="100" value="${source.minimum_count}" aria-label="${escapeText(source.name)} 最少新闻数"></label><span class="source-actions"><button class="edit quiet">修改</button><button class="delete quiet">删除</button></span>`;
      }
      const link = $("a", row);
      link.href = source.homepage;
      link.textContent = source.homepage;
      const minimumInput = $(".source-minimum input", row);
      let minimumTimer = null;
      minimumInput.oninput = () => {
        if (minimumTimer) clearTimeout(minimumTimer);
        minimumTimer = setTimeout(async () => {
          const minimumCount = Number.parseInt(minimumInput.value, 10);
          if (!Number.isInteger(minimumCount) || minimumCount < 0 || minimumCount > 100) {
            panelError("#source-error", "来源最低新闻数须在 0 至 100 之间。");
            minimumInput.value = source.minimum_count;
            return;
          }
          try {
            await api(`/api/settings/news-sources/${source.id}`, {
              method: "PUT",
              body: JSON.stringify(newsSourcePayload(source, minimumCount, sourceVoiceValue(source))),
            });
            await loadNewsSources();
          } catch (error) {
            panelError("#source-error", error.message);
            minimumInput.value = source.minimum_count;
          }
        }, 350);
      };
      $(".edit", row).onclick = () => {
        $(".source-actions-menu", row)?.removeAttribute("open");
        openSourceDialog(source);
      };
      $(".delete", row).onclick = async () => {
        $(".source-actions-menu", row)?.removeAttribute("open");
        if (!confirm(`删除新闻来源“${source.name}”？`)) return;
        try {
          await api(`/api/settings/news-sources/${source.id}`, { method: "DELETE" });
          await loadNewsSources();
          panelError("#source-error");
        } catch (error) { panelError("#source-error", error.message); }
      };
      list.append(row);
    });
    panelError("#source-error");
  } catch (error) { panelError("#source-error", error.message); }
}

async function updateDailyContentSettings() {
  const targetCount = Number.parseInt($("#daily-target-count").value, 10);
  if (!Number.isInteger(targetCount)) {
    panelError("#source-error", "请输入有效的新闻数量。");
    return;
  }
  try {
    const content = await api("/api/settings/daily-content", {
      method: "PUT",
      body: JSON.stringify({ target_count: targetCount }),
    });
    renderDailyContentSettings(content);
    panelError("#source-error");
  } catch (error) {
    panelError("#source-error", error.message);
    const content = await api("/api/settings/daily-content");
    renderDailyContentSettings(content);
  }
}

function scheduleDailyContentUpdate() {
  if (state.dailyContentTimer) clearTimeout(state.dailyContentTimer);
  state.dailyContentTimer = setTimeout(() => {
    state.dailyContentTimer = null;
    updateDailyContentSettings();
  }, 350);
}

function openSourceDialog(source = null) {
  state.editingSourceId = source?.id ?? null;
  $("#source-editor-form").reset();
  $("#source-editor-name").value = source?.name || "";
  $("#source-editor-homepage").value = source?.homepage || "";
  $("#source-editor-minimum").value = source?.minimum_count ?? 1;
  populateSourceVoiceSelect($("#source-editor-voice"), sourceVoiceValue(source));
  $("#source-dialog-title").textContent = source ? "修改新闻来源" : "添加新闻来源";
  $("#submit-source").textContent = source ? "保存修改" : "添加";
  panelNotice("#source-editor-notice", "");
  $("#source-dialog").showModal();
  $("#source-editor-name").focus();
}

function closeSourceDialog() {
  $("#source-dialog").close();
  state.editingSourceId = null;
}

async function submitSourceEditor(event) {
  event.preventDefault();
  const name = $("#source-editor-name").value.trim();
  const homepage = $("#source-editor-homepage").value.trim();
  const minimumCount = Number.parseInt($("#source-editor-minimum").value, 10);
  const voice = sourceVoiceSettings($("#source-editor-voice").value);
  if (!name || !homepage) return panelNotice("#source-editor-notice", "请输入来源名称和网址。", true);
  if (!Number.isInteger(minimumCount) || minimumCount < 0 || minimumCount > 100) return panelNotice("#source-editor-notice", "来源最低新闻数须在 0 至 100 之间。", true);
  try {
    const editing = state.editingSourceId !== null;
    await api(editing ? `/api/settings/news-sources/${state.editingSourceId}` : "/api/settings/news-sources", {
      method: editing ? "PUT" : "POST",
      body: JSON.stringify({ name, homepage, minimum_count: minimumCount, ...voice }),
    });
    closeSourceDialog();
    await loadNewsSources();
  } catch (error) { panelNotice("#source-editor-notice", error.message, true); }
}

function setVoiceSourceMode(mode) {
  state.voiceSourceMode = mode;
  document.querySelectorAll("#voice-source-mode button").forEach(button => button.classList.toggle("active", button.dataset.sourceMode === mode));
  $("#voice-editor-file-row").hidden = mode !== "file";
  $("#voice-editor-url-row").hidden = mode !== "url";
  $("#voice-editor-hint").textContent = state.editingVoiceId
    ? "不选择新音频时，只修改声线名称。"
    : mode === "file" ? "请选择用于参考的音频文件。" : "请输入可直接下载的音频网址。";
}

function setBrowserVoiceEditor(enabled) {
  state.editingBrowserVoice = enabled;
  $("#voice-editor-name-row").hidden = false;
  $("#voice-editor-name").required = true;
  $("#voice-source-mode").hidden = enabled;
  $("#browser-voice-row").hidden = !enabled;
  $("#voice-editor-file-row").hidden = enabled || state.voiceSourceMode !== "file";
  $("#voice-editor-url-row").hidden = enabled || state.voiceSourceMode !== "url";
  $("#voice-editor-hint").hidden = enabled;
}

async function populateBrowserVoiceSelect() {
  const select = $("#browser-voice-select");
  const mobile = typeof window !== "undefined" && Boolean(window.FujimiMobile);
  select.disabled = true;
  $("#submit-voice").disabled = true;
  select.replaceChildren(new Option("正在检测日语声线…", ""));
  panelNotice("#voice-editor-notice", "");
  let local = typeof localBrowserVoices === "function" ? localBrowserVoices() : [];
  if (typeof api === "function") {
    try {
      const catalog = await api("/api/browser-voices");
      if (Array.isArray(catalog)) {
        state.browserVoices = catalog;
        local = catalog;
      }
    } catch (_error) {
      state.browserVoices = [];
      local = [];
    }
  }
  if (!mobile && !(typeof localBrowserVoice === "function" && localBrowserVoice(state.browserVoiceName))
      && !desktopOnlineVoice(state.browserVoiceName)) await waitForJapaneseBrowserVoice();
  if (!state.editingBrowserVoice) return;
  const voices = japaneseBrowserVoices();
  const selected = voices.find(voice => voice.name === state.browserVoiceName)
    || (!state.browserVoiceName || isHiddenBrowserVoiceName(state.browserVoiceName) ? preferredJapaneseBrowserVoice(voices) : null);
  const online = desktopOnlineVoices();
  const localOptions = local.map(voice => {
    const option = new Option(`${voice.name}${voice.available === false ? "（资源不可用）" : mobile && voice.saved_audio_only ? "（已同步音频）" : ""}`, voice.id);
    option.disabled = voice.available === false;
    return option;
  });
  const options = [...localOptions, ...online, ...voices].map(voice => voice instanceof Option ? voice : new Option(browserVoiceShortName(voice.name), voice.name));
  if (state.browserVoiceName && !selected && !isHiddenBrowserVoiceName(state.browserVoiceName)) {
    if (!online.some(voice => voice.name === state.browserVoiceName)
        && !local.some(voice => voice.id === state.browserVoiceName)) {
      const unavailable = new Option(`${browserVoiceShortName(state.browserVoiceName)}（当前设备不可用）`, state.browserVoiceName);
      unavailable.disabled = true;
      options.unshift(unavailable);
    }
  }
  select.replaceChildren(...options);
  if (selected) select.value = selected.name;
  else if (state.browserVoiceName && !isHiddenBrowserVoiceName(state.browserVoiceName)) select.value = state.browserVoiceName;
  select.disabled = options.length === 0;
  const updateSubmit = () => {
    const localAvailable = local.some(voice => voice.id === select.value && voice.available !== false);
    $("#submit-voice").disabled = !(localAvailable || [...online, ...voices].some(voice => voice.name === select.value));
  };
  select.onchange = updateSubmit;
  updateSubmit();
  panelNotice("#voice-editor-notice", options.length ? "" : mobile ? "未检测到 Edge 在线声线，请检查网络后重试。" : "未检测到日语声线。请检查网络或安装 Windows 日语语音包。", options.length === 0);
}

function openVoiceDialog(voice = null) {
  state.editingVoiceId = voice?.id ?? null;
  $("#voice-editor-form").reset();
  setBrowserVoiceEditor(false);
  $("#voice-editor-name").value = voice?.name || "";
  $("#voice-dialog-title").textContent = voice ? "修改声线" : "添加声线";
  $("#submit-voice").textContent = voice ? "保存修改" : "添加";
  $("#submit-voice").disabled = false;
  panelNotice("#voice-editor-notice", "");
  setVoiceSourceMode("file");
  $("#voice-dialog").showModal();
  $("#voice-editor-name").focus();
}

function openBrowserVoiceDialog() {
  state.editingVoiceId = null;
  $("#voice-editor-form").reset();
  setBrowserVoiceEditor(true);
  $("#voice-editor-name").value = state.browserVoiceLabel || "ブラウザー";
  $("#voice-dialog-title").textContent = window.FujimiMobile ? "选择系统声线" : "修改浏览器声线";
  $("#submit-voice").textContent = "保存修改";
  $("#native-speech-settings").hidden = true;
  populateBrowserVoiceSelect();
  $("#voice-dialog").showModal();
  $("#browser-voice-select").focus();
}

function closeVoiceDialog() {
  $("#voice-dialog").close();
  state.editingVoiceId = null;
  state.editingBrowserVoice = false;
}

async function submitVoiceEditor(event) {
  event.preventDefault();
  if (state.editingBrowserVoice) {
    const name = $("#browser-voice-select").value;
    const label = $("#voice-editor-name").value.trim();
    if (!name) return panelNotice("#voice-editor-notice", "请选择浏览器声线。", true);
    if (!label) return panelNotice("#voice-editor-notice", "请输入声线名称。", true);
    try {
      const local = typeof localBrowserVoice === "function" ? localBrowserVoice(name) : null;
      const localAvailable = local && local.available !== false;
      if (!localAvailable && window.FujimiDesktop && ![...desktopOnlineVoices(), ...japaneseBrowserVoices()].some(voice => voice.name === name)) {
        throw new Error("当前设备没有此声线，请选择可用的日语声线。");
      }
      if (!localAvailable && !window.FujimiDesktop && !japaneseBrowserVoices().some(voice => voice.name === name)) {
        throw new Error("当前设备没有此声线，请选择可用的日语声线。");
      }
      await api("/api/settings/browser-voice", { method: "PUT", body: JSON.stringify({ name, label }) });
      state.browserVoiceName = name;
      state.browserVoiceLabel = label;
      closeVoiceDialog();
      await loadVoices();
      toast(window.FujimiMobile ? "系统音声已更新。" : "浏览器声线已更新。");
    } catch (error) { panelNotice("#voice-editor-notice", error.message, true); }
    return;
  }
  const editing = state.editingVoiceId !== null;
  const name = $("#voice-editor-name").value.trim();
  const file = $("#voice-editor-file").files[0];
  const url = $("#voice-editor-url").value.trim();
  if (!name) return panelNotice("#voice-editor-notice", "请输入声线名称。", true);
  if (!editing && state.voiceSourceMode === "file" && !file) return panelNotice("#voice-editor-notice", "请选择音频文件。", true);
  if (!editing && state.voiceSourceMode === "url" && !url) return panelNotice("#voice-editor-notice", "请输入音频网址。", true);
  try {
    if (state.voiceSourceMode === "file") {
      const data = new FormData();
      data.append("name", name);
      if (file) data.append("file", file);
      await api(editing ? `/api/settings/voices/${state.editingVoiceId}` : "/api/settings/voices", { method: editing ? "PUT" : "POST", body: data });
    } else if (editing) {
      await api(`/api/settings/voices/${state.editingVoiceId}/from-url`, { method: "PUT", body: JSON.stringify({ name, url: url || null }) });
    } else {
      await api("/api/settings/voices/from-url", { method: "POST", body: JSON.stringify({ name, url }) });
    }
    closeVoiceDialog();
    await Promise.all([loadVoices(), loadNewsSources()]);
    panelError("#voice-error");
  } catch (error) { panelNotice("#voice-editor-notice", error.message, true); }
}

function libraryRoute() {
  const seriesMatch = location.hash.match(/^#library\/series\/(.+)$/);
  if (seriesMatch) return { kind: "series", series: decodeURIComponent(seriesMatch[1]) };
  const bookMatch = location.hash.match(/^#library\/book\/(\d+)\/chapter\/(\d+)(?:\?(.+))?$/);
  if (!bookMatch) return null;
  const parameters = new URLSearchParams(bookMatch[3] || "");
  return { kind: "book", bookId: Number(bookMatch[1]), chapterId: Number(bookMatch[2]), anchor: parameters.get("anchor") || "" };
}

function bookAssetUrl(bookId, asset) {
  return `/api/books/${bookId}/assets/${String(asset || "").split("/").map(encodeURIComponent).join("/")}`;
}

function bookCover(book) {
  const coverUrl = book.cover_url || (window.FujimiMobile && book.id ? `/api/books/${book.id}/cover` : "");
  if (coverUrl) return `<img src="${escapeText(coverUrl)}" alt="${escapeText(book.title)}の表紙">`;
  return `<div class="book-cover-placeholder" aria-hidden="true"><span>BOOK</span><strong>${escapeText((book.title || "無").slice(0, 2))}</strong></div>`;
}

function replaceMissingBookImage(image, label = "图片暂不可用") {
  if (!image || image.dataset.missingHandled) return;
  image.dataset.missingHandled = "true";
  const placeholder = document.createElement("span");
  placeholder.className = "book-media-missing";
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", label);
  placeholder.textContent = label;
  image.replaceWith(placeholder);
}

function bookCard(book) {
  const card = document.createElement("article");
  card.className = "book-card";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `${book.title}を読む`);
  card.innerHTML = `<div class="book-cover">${bookCover(book)}</div><div class="book-card-copy"><h3>${escapeText(book.title)}</h3></div>`;
  $(".book-cover img", card)?.addEventListener("error", event => replaceMissingBookImage(event.currentTarget, "封面暂不可用"));
  card.onclick = () => openBook(book.id);
  card.onkeydown = event => {
    if (event.target !== card || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    openBook(book.id);
  };
  return card;
}

function seriesCard(series, books) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "series-card";
  card.setAttribute("aria-label", `${series}を開く`);
  const covers = books.slice(0, 3).map((book, index) => `<span class="series-card-cover series-card-cover-${index + 1}">${bookCover(book)}</span>`).join("");
  card.innerHTML = `<span class="series-card-covers">${covers}</span><span class="series-card-copy"><strong>${escapeText(series)}</strong><small>${books.length} 冊</small></span>`;
  card.onclick = () => openLibrarySeries(series);
  return card;
}

function sortSeriesBooks(books) {
  return [...books].sort((a, b) => String(a.volume || "").localeCompare(String(b.volume || ""), "ja", { numeric: true }) || String(a.title || "").localeCompare(String(b.title || ""), "ja"));
}

function renderLibraryHome(books) {
  const container = $("#library-series");
  if (!books.length) {
    container.innerHTML = '<p class="library-empty">次の物語は、ここにある。</p>';
    return;
  }
  const groups = new Map();
  books.forEach(book => {
    const key = book.series || "__standalone__";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(book);
  });
  const items = [];
  groups.forEach((itemsInGroup, series) => {
    if (series === "__standalone__") items.push(...itemsInGroup.map(bookCard));
    else items.push(seriesCard(series, itemsInGroup));
  });
  const grid = document.createElement("div");
  grid.className = "book-grid library-home-grid";
  grid.replaceChildren(...items);
  container.replaceChildren(grid);
}

function renderLibrarySeries(books, series) {
  const matching = books.filter(book => String(book.series || "") === series);
  $("#library-series-title").textContent = series;
  $("#library-series-count").textContent = `${matching.length} 冊`;
  const grid = $("#library-series-books");
  grid.replaceChildren(...sortSeriesBooks(matching).map(bookCard));
  if (!matching.length) {
    const empty = document.createElement("p");
    empty.className = "library-empty";
    empty.textContent = "このシリーズには書籍がありません。";
    grid.replaceChildren(empty);
  }
}

function renderLibrary(payload, { series = "" } = {}) {
  const books = payload.books || [];
  state.libraryBooks = books;
  $("#library-count").textContent = `${books.length} 冊`;
  $("#library-home").hidden = Boolean(series);
  $("#library-series-detail").hidden = !series;
  if (series) renderLibrarySeries(books, series);
  else renderLibraryHome(books);
}

async function loadLibrary({ forceHome = false } = {}) {
  const route = !forceHome && libraryRoute();
  if (route?.kind === "book") {
    const reader = $("#book-reader");
    const current = state.libraryChapter;
    if (current && reader.isConnected && Number(current.book.id) === route.bookId && Number(current.chapter.id) === route.chapterId) {
      reader.hidden = false;
      $("#library-home").hidden = true;
      $("#library-series-detail").hidden = true;
      if (redesignedReadingUi && reader.classList.contains("has-audio-player") && !resumeArticlePlayback(reader)) {
        resetReaderAudio(reader);
        setupBookAudio(current, reader);
      }
      const position = rememberedBookPosition(route.bookId, route.chapterId);
      if (position && Number.isFinite(Number(position.scrollY))) {
        requestAnimationFrame(() => window.scrollTo({ top: Math.max(0, Number(position.scrollY)), behavior: "auto" }));
      }
      return;
    }
    return navigateBookChapter(route.bookId, route.chapterId, { historyMode: "none", anchor: route.anchor });
  }
  stopArticlePlayback();
  $("#book-reader").hidden = true;
  try {
    const payload = await api(`/api/books?sort=${encodeURIComponent(state.librarySort || "recent")}`);
    renderLibrary(payload, { series: route?.kind === "series" ? route.series : "" });
    await loadBookTasks();
  } catch (error) { toast(error.message, true); }
}

async function openLibrarySeries(series) {
  history.pushState({ view: "library", series }, "", `#library/series/${encodeURIComponent(series)}`);
  await loadLibrary();
}

async function openBook(bookId) {
  const book = await api(`/api/books/${bookId}`);
  const position = selectBookReadingPosition(book);
  const chapterId = position.chapterId;
  if (!chapterId) return toast("この書籍には読める章がありません。", true);
  await navigateBookChapter(bookId, chapterId, {
    blockIndex: position.blockIndex,
    startAtBeginning: position.startAtBeginning,
  });
}

function originalBookAudioPlayerMarkup() {
  return `<div class="article-audio-player" role="group" aria-label="章の朗読プレーヤー" hidden><div class="audio-player-timeline"><div class="audio-player-seek"><span class="audio-player-progress-fill"></span><input class="audio-player-progress" type="range" min="0" max="1" value="0" step="0.1" aria-label="朗読進度"></div><time class="audio-player-current">0:00</time><time class="audio-player-duration">0:00</time></div><button class="audio-player-toggle audio-icon-button" type="button" aria-label="朗読を再生" title="再生または一時停止"><img class="audio-player-toggle-icon" src="/static/player_assets/ic_player_stop.png" alt=""></button><div class="audio-rate-control"><button class="audio-rate-toggle" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="再生速度" title="再生速度"><img src="/static/player_assets/ic_player_set.png" alt=""><span class="audio-rate-value" aria-hidden="true">1.0x</span></button><div class="audio-rate-menu" role="menu" hidden>${PLAYBACK_RATES.map(rate => `<button type="button" role="menuitemradio" data-rate="${rate}">${rate}×</button>`).join("")}</div></div></div>`;
}

function bookAudioPlayerMarkup() {
  if (!redesignedReadingUi) return originalBookAudioPlayerMarkup();
  const player = $("#article-template").content.querySelector(".article-audio-player").cloneNode(true);
  player.setAttribute("aria-label", "章の朗読プレーヤー");
  return player.outerHTML;
}

function bookVoiceOptions(chapter) {
  const options = [new Option("默认声线", "model"), new Option(redesignedReadingUi ? (localBrowserVoice(state.browserVoiceName)?.name || browserVoiceShortName(state.browserVoiceName) || "音声") : `ブラウザー音声（${state.browserVoiceLabel || "ブラウザー"}）`, "browser")];
  state.voices.forEach(voice => options.push(new Option(voice.name, `voice:${voice.id}`)));
  const selected = chapter.voice_mode === "voice" ? `voice:${chapter.voice_id}` : chapter.voice_mode;
  options.forEach(option => { option.selected = option.value === selected; });
  return options;
}

function currentBookBlock(root) {
  const blocks = [...root.querySelectorAll(".book-block")];
  if (root.classList.contains('is-vertical')) {
    const viewport = root.querySelector('.book-chapter-body')?.getBoundingClientRect();
    if (viewport) return blocks.reduce((best, block) => Math.abs(block.getBoundingClientRect().right - viewport.right) < Math.abs(best.getBoundingClientRect().right - viewport.right) ? block : best, blocks[0]);
  }
  const reference = Math.max(120, window.innerHeight * .3);
  return blocks.reduce((best, block) => Math.abs(block.getBoundingClientRect().top - reference) < Math.abs(best.getBoundingClientRect().top - reference) ? block : best, blocks[0]);
}

function isBookReaderActive(root = $("#book-reader")) {
  return state.currentView === "library" && !$("#library-view").hidden && !root?.hidden;
}

function rememberBookPosition(payload, block, scrollOffset) {
  if (!payload?.book?.id || !payload?.chapter?.id) return;
  const position = {
    bookId: Number(payload.book.id),
    chapterId: Number(payload.chapter.id),
    blockIndex: Number(block?.dataset.blockIndex || 0),
    scrollOffset: Number(scrollOffset) || 0,
    scrollY: Math.max(0, Math.round(window.scrollY || window.pageYOffset || 0)),
    scrollLeft: document.querySelector('#book-reader .book-chapter-body')?.scrollLeft || 0,
    revision: payload.book.reading_revision || payload.book.parser_version || 1,
  };
  state.libraryReturnPosition = position;
  try { sessionStorage.setItem(BOOK_POSITION_KEY, JSON.stringify(position)); } catch (_error) { /* Session storage is optional. */ }
}

function rememberedBookPosition(bookId, chapterId) {
  const position = state.libraryReturnPosition;
  const expectedRevision = state.libraryChapter?.book?.reading_revision || state.libraryChapter?.book?.parser_version || 1;
  if (position && (position.revision || 1) === expectedRevision && Number(position.bookId) === Number(bookId) && Number(position.chapterId) === Number(chapterId)) return position;
  try {
    const stored = JSON.parse(sessionStorage.getItem(BOOK_POSITION_KEY) || "null");
    return stored && (stored.revision || 1) === expectedRevision && Number(stored.bookId) === Number(bookId) && Number(stored.chapterId) === Number(chapterId) ? stored : null;
  } catch (_error) { return null; }
}

async function loadDesktopSettings() {
  const panel = $("#desktop-settings-panel");
  const mobilePanel = $("#mobile-settings-panel");
  if (!panel) return;
  if (window.FujimiMobile?.mobileStatus) {
    $("#device-sync-panel").hidden = true;
    panel.hidden = true;
    mobilePanel.hidden = false;
    $("#android-sync-settings").hidden = false;
    $("#android-local-settings").hidden = false;
    try {
      const status = JSON.parse(window.FujimiMobile.mobileStatus());
      renderMobileNodeStatus(status);
      if (["queued", "running"].includes(status.sync_state)) scheduleMobileSyncPoll();
    } catch (_error) {
      $("#mobile-service-status").textContent = "状态读取失败";
      $("#mobile-sync-detail").textContent = "无法读取本机状态，请重新打开应用。";
      $("#mobile-sync-now").disabled = true;
    }
    return;
  }
  await loadDeviceSyncSettings();
  try {
    const health = await api("/api/health");
    if (!window.pywebview?.api) {
      panel.hidden = true;
      return;
    }
    const settings = await window.pywebview.api.get_desktop_settings();
    panel.hidden = false;
    $("#desktop-project-root").textContent = settings.project_root || "未设置";
    $("#desktop-data-path").textContent = settings.data_dir || "未设置";
    $("#desktop-python-path").textContent = settings.python_executable || "未设置";
    panelError("#desktop-settings-error");
  } catch (error) {
    panel.hidden = false;
    panelError("#desktop-settings-error", error.message || "无法读取桌面设置");
  }
}

function renderDeviceSyncSettings(status) {
  deviceSyncStatus = status;
  $("#device-sync-enabled").checked = Boolean(status.enabled);
  const available = Boolean(status.enabled && status.url && status.pairing_code);
  $("#device-sync-details").hidden = !available;
  $("#device-sync-url").textContent = available ? status.url : "";
  $("#device-sync-code").textContent = available ? status.pairing_code : "";
  const qr = $("#device-sync-qr");
  if (available) {
    const version = `${status.url}|${status.pairing_code}`;
    if (qr.dataset.version !== version) {
      qr.src = `${status.qr_url || '/api/settings/device-sync/qr'}?v=${Date.now()}`;
      qr.dataset.version = version;
    }
  } else {
    qr.removeAttribute("src");
    delete qr.dataset.version;
  }
  const count = Array.isArray(status.paired_devices) ? status.paired_devices.length : Number(status.paired_devices) || 0;
  const inactive = status.status === "connecting" ? "正在连接 Tailscale…"
    : status.tailscale_status === "login_required" ? "等待 Tailscale 登录"
    : status.tailscale_status === "error" ? "Tailscale 连接失败" : "未开启";
  $("#device-sync-state").textContent = status.enabled ? (count ? `已配对 ${count} 台设备` : "等待手机配对") : inactive;
  $("#device-sync-state").dataset.enabled = String(Boolean(status.enabled));
  const login = $("#device-sync-login");
  if (login) {
    login.hidden = true; login.removeAttribute("href");
    if (status.tailscale_status === "login_required" && status.login_url) {
      try {
        const url = new URL(status.login_url);
        if (url.protocol === "https:" && url.hostname === "login.tailscale.com" && !url.port &&
            !url.username && !url.password && !url.search && !url.hash && url.pathname.startsWith("/a/")) {
          login.href = url.href; login.hidden = false;
        }
      } catch (_error) { /* Login can still be completed in the Tailscale app. */ }
    }
  }
  $("#device-sync-detail").textContent = status.detail || (status.enabled
    ? "在 Android 的 Windows 同步中扫码，或输入以上地址和配对码。配对后由手机点击“立即同步”。"
    : "开启后，在 Android 的 Windows 同步中连接。");
}

async function loadDeviceSyncSettings() {
  const panel = $("#device-sync-panel");
  if (!panel || window.FujimiMobile?.mobileStatus) return;
  window.clearTimeout(deviceSyncPollTimer);
  deviceSyncPollTimer = null;
  panel.hidden = false;
  try {
    const status = await api("/api/settings/device-sync");
    renderDeviceSyncSettings(status);
    panelError("#device-sync-error");
    if ((status.enabled || status.status === "connecting") && state.currentView === "settings") {
      deviceSyncPollTimer = window.setTimeout(() => {
        if (state.currentView === "settings") loadDeviceSyncSettings();
      }, 3000);
    }
  } catch (error) { panelError("#device-sync-error", error.message || "无法读取同步状态"); }
}

async function toggleDeviceSync() {
  const toggle = $("#device-sync-enabled");
  const enabled = toggle.checked;
  toggle.disabled = true;
  toggle.setAttribute("aria-busy", "true");
  window.clearTimeout(deviceSyncPollTimer);
  $("#device-sync-state").textContent = enabled ? "正在准备配对…" : "正在关闭配对…";
  $("#device-sync-state").dataset.enabled = "false";
  if (!enabled) $("#device-sync-details").hidden = true;
  const login = $("#device-sync-login"); if (login) login.hidden = true;
  panelError("#device-sync-error");
  try {
    const status = await api("/api/settings/device-sync", { method: "PUT", body: JSON.stringify({ enabled }) });
    renderDeviceSyncSettings(status);
    panelError("#device-sync-error");
    if (status.enabled || status.status === "connecting") deviceSyncPollTimer = window.setTimeout(loadDeviceSyncSettings, 3000);
  } catch (error) {
    try { renderDeviceSyncSettings(await api("/api/settings/device-sync")); }
    catch (_statusError) { toggle.checked = Boolean(deviceSyncStatus?.enabled); }
    panelError("#device-sync-error", error.message || "同步服务未能启动，请重试。");
  } finally { toggle.disabled = false; toggle.removeAttribute("aria-busy"); }
}

async function copyDeviceSyncValue(selector) {
  const value = $(selector).textContent;
  if (!value) return;
  try { await navigator.clipboard.writeText(value); toast("已复制"); }
  catch (_error) { toast("复制失败，请选中内容手动复制。", true); }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = -1;
  do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unit]}`;
}

function renderMobileNodeStatus(status) {
  mobileNodeStatus = status;
  $("#mobile-runtime-summary").textContent = status.article_index_error || "本机运行 · Windows 可选";
  $("#mobile-service-status").textContent = status.startup_error ? "初始化失败" : status.article_index_error ? "索引待修复" : "本机就绪";
  const address = $("#mobile-windows-address");
  if (!address.dataset.dirty && !mobileWindowsCheck) address.value = status.server_url || "";
  $("#mobile-deepseek-status").textContent = status.deepseek_configured ? "已保存" : "未配置";
  $("#mobile-clear-deepseek").hidden = !status.deepseek_configured || !window.FujimiMobile?.clearDeepSeekKey;
  $("#mobile-allow-cellular").checked = Boolean(status.allow_cellular);

  const windowsLabels = {
    unconfigured: "未配置",
    offline: "离线",
    checking: "检测中",
    syncing: "同步中",
    ready: status.paired ? "已配对" : "可用",
  };
  const windowsMessages = {
    unconfigured: "尚未填写 PC 地址。",
    offline: "地址已保存，但当前未连上；本地功能不受影响。",
    checking: "正在连接 Windows…",
    syncing: "已连接，正在交换本地与电脑端修改。",
    ready: status.paired ? "已配对，点击“立即同步”传输文庫。" : "节点可用，请输入配对码连接。",
  };
  const windowsState = status.windows_status || "unconfigured";
  const windowsBadge = $("#mobile-windows-state");
  windowsBadge.textContent = windowsLabels[windowsState] || "未配置";
  windowsBadge.dataset.state = windowsState;
  const windowsResult = $("#mobile-windows-result");
  if (!mobileWindowsCheck) windowsResult.textContent = status.connection_detail || windowsMessages[windowsState] || windowsMessages.unconfigured;
  windowsResult.dataset.state = windowsState;
  $("#mobile-clear-windows").hidden = !status.server_url;

  const syncState = status.sync_state || "idle";
  const configured = Boolean(status.server_url);
  const active = ["queued", "running"].includes(syncState);
  const progress = Math.max(0, Math.min(100, Number(status.sync_progress) || 0));
  const defaultStage = configured ? "尚未同步" : "等待配置";
  const defaultDetail = status.paired ? "点击“立即同步”传输文庫。" : "扫码或输入地址与配对码连接 Windows。";
  $("#mobile-sync-stage").textContent = status.sync_stage || defaultStage;
  $("#mobile-sync-percent").textContent = `${Math.round(progress)}%`;
  const progressTrack = $("#mobile-sync-progress");
  progressTrack.dataset.state = syncState;
  progressTrack.setAttribute("aria-valuenow", String(Math.round(progress)));
  $("span", progressTrack).style.width = `${progress}%`;
  $("#mobile-sync-detail").textContent = status.sync_detail || defaultDetail;
  $("#mobile-sync-last").textContent = status.last_sync_at ? new Date(status.last_sync_at).toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "尚未完成";
  $("#mobile-sync-pending").textContent = String(Number(status.pending_changes) || 0);
  $("#mobile-sync-cache").textContent = formatBytes(Number(status.cache_bytes) || 0);
  const syncButton = $("#mobile-sync-now");
  syncButton.disabled = !configured || active || status.sync_available === false || Boolean(mobileWindowsCheck);
  syncButton.textContent = active ? "同步中…" : "立即同步";
  syncButton.setAttribute("aria-busy", String(active));

  const nextAlarm = status.next_alarm ? `${new Date(status.next_alarm).toLocaleString([], { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })} CST` : "未安排";
  $("#mobile-alarm-status").textContent = status.scheduler_available === false
    ? `${status.exact_alarm ? "精确闹钟权限已授权" : "精确闹钟权限未授权"} · 调度尚未接入`
    : status.alarm_error || `${status.schedule_precision === "exact" ? "精确" : "系统时间窗口"} · ${nextAlarm}`;
  $("#mobile-exact-alarm").hidden = Boolean(status.exact_alarm);
  $("#mobile-app-info").hidden = !status.app_version && !status.data_path;
  $("#mobile-app-settings-panel").hidden = $("#mobile-app-info").hidden;
  $("#mobile-app-version-badge").textContent = status.app_version || "未知";
  $("#mobile-app-version").textContent = status.app_version || "未知";
  $("#mobile-data-path").textContent = status.data_path || "未知";
  if (status.daily_generation_available === false) {
    $("#generate-daily").disabled = true;
    $("#generate-daily").title = "Android 日刊采集尚未接入";
  } else if (status.daily_generation_available === true) {
    $("#generate-daily").disabled = state.dailyTaskRunning;
    $("#generate-daily").title = "在此手机上独立采集日刊";
  }
  if (status.reference_voices_available === false) {
    $("#add-voice").textContent = "选择声线";
    $("#add-voice").onclick = openBrowserVoiceDialog;
    $("#add-voice").disabled = false;
    $("#add-voice").title = "选择日语声线";
    $("#voice-editor-hint").textContent = "圭太／七海可在线生成，PC 声线播放已同步音频。";
    const hint = $("#voice-settings-disclosure summary small");
    if (hint) hint.textContent = "选择圭太或七海在线声线";
  }
}

function scheduleMobileSyncPoll() {
  if (mobileSyncPollTimer) return;
  mobileSyncPollTimer = window.setTimeout(pollMobileSyncStatus, 700);
}

function stopMobileSyncPoll() {
  if (mobileSyncPollTimer) window.clearTimeout(mobileSyncPollTimer);
  mobileSyncPollTimer = null;
}

function pollMobileSyncStatus() {
  mobileSyncPollTimer = null;
  if (!window.FujimiMobile?.mobileStatus || $("#mobile-settings-panel")?.hidden) return;
  try {
    const status = JSON.parse(window.FujimiMobile.mobileStatus());
    renderMobileNodeStatus(status);
    if (["queued", "running"].includes(status.sync_state)) scheduleMobileSyncPoll();
  } catch (_error) {
    $("#mobile-sync-detail").textContent = "暂时无法读取同步状态。";
  }
}

function updateMobileCellularSetting() {
  const input = $("#mobile-allow-cellular");
  try {
    if (!window.FujimiMobile?.setAllowCellular(input.checked)) throw new Error("网络设置保存失败。");
    toast(input.checked ? "已允许按流量计费的网络" : "已限制为不按流量计费的网络");
    loadDesktopSettings();
  } catch (error) {
    input.checked = Boolean(mobileNodeStatus?.allow_cellular);
    toast(error.message || "网络设置保存失败", true);
  }
}

function startMobileSync() {
  const accepted = Boolean(window.FujimiMobile?.syncNow());
  if (!accepted) {
    const detail = mobileNodeStatus?.sync_detail || "请先连接 Windows。";
    $("#mobile-sync-detail").textContent = detail;
    toast(detail, true);
    return;
  }
  renderMobileNodeStatus({
    ...mobileNodeStatus,
    server_url: $("#mobile-windows-address").value.trim(), windows_status: "syncing",
    deepseek_configured: $("#mobile-deepseek-status").textContent !== "未配置",
    allow_cellular: $("#mobile-allow-cellular").checked, sync_state: "queued",
    sync_stage: "准备同步", sync_progress: 0, sync_detail: "任务已加入队列。",
    pending_changes: Number($("#mobile-sync-pending").textContent) || 0,
  });
  stopMobileSyncPoll();
  scheduleMobileSyncPoll();
}

function saveMobileDeepSeekKey() {
  const input = $("#mobile-deepseek-key");
  const value = input.value.trim();
  const result = $("#mobile-deepseek-result");
  input.removeAttribute("aria-invalid");
  try {
    if (!value) throw new Error("请输入新密钥；已有密钥未更改。");
    if (!window.FujimiMobile?.setDeepSeekKey(value)) throw new Error("密钥未能保存，请检查格式与设备存储。");
    input.value = "";
    result.textContent = "已在此手机加密保存。";
    result.dataset.state = "ready";
    loadDesktopSettings();
  } catch (error) {
    result.textContent = error.message || "密钥保存失败。";
    result.dataset.state = "error";
    input.setAttribute("aria-invalid", "true");
  }
}

function clearMobileDeepSeekKey() {
  if (!window.confirm("清除此手机保存的 DeepSeek 密钥？")) return;
  const result = $("#mobile-deepseek-result");
  try {
    if (!window.FujimiMobile?.clearDeepSeekKey()) throw new Error("密钥清除失败。");
    $("#mobile-deepseek-key").value = "";
    $("#mobile-deepseek-key").removeAttribute("aria-invalid");
    result.textContent = "已清除本机密钥。";
    result.dataset.state = "ready";
    loadDesktopSettings();
  } catch (error) { result.textContent = error.message || "密钥清除失败。"; result.dataset.state = "error"; }
}

function saveMobileWindowsAddress(event) {
  event?.preventDefault();
  const input = $("#mobile-windows-address");
  const value = input.value.trim();
  const code = $("#mobile-windows-code");
  if (mobileWindowsCheck) return;
  input.removeAttribute("aria-invalid");
  code.removeAttribute("aria-invalid");
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname)) throw new Error();
  } catch (_error) {
    $("#mobile-windows-result").textContent = "请输入 PC 显示的连接地址，例如 http://192.168.1.20:8429。";
    $("#mobile-windows-result").dataset.state = "error";
    input.setAttribute("aria-invalid", "true");
    input.focus();
    return;
  }
  if (!/^\d{6}$/.test(code.value.trim())) {
    $("#mobile-windows-result").textContent = "请输入 PC 显示的 6 位配对码。";
    $("#mobile-windows-result").dataset.state = "error";
    code.setAttribute("aria-invalid", "true");
    code.focus();
    return;
  }
  beginMobilePairing(false, value, code.value.trim());
}

function beginMobilePairing(scan, address = "", code = "") {
  if (mobileWindowsCheck) return;
  const input = $("#mobile-windows-address");
  const codeInput = $("#mobile-windows-code");
  const button = $("#mobile-save-windows");
  const scanButton = $("#mobile-scan-windows");
  button.disabled = true;
  scanButton.disabled = true;
  button.textContent = scan ? "连接" : "连接中…";
  button.setAttribute("aria-busy", "true");
  scanButton.setAttribute("aria-busy", String(scan));
  input.disabled = true;
  codeInput.disabled = true;
  $("#mobile-clear-windows").disabled = true;
  $("#mobile-sync-now").disabled = true;
  $("#mobile-windows-result").textContent = scan ? "请扫描 PC 的文庫互联二维码。" : "正在与 Windows 配对…";
  $("#mobile-windows-result").dataset.state = "syncing";
  const callbackId = `setup-${Date.now()}`;
  const finish = (success, message) => {
    if (mobileWindowsCheck?.id !== callbackId) return;
    window.clearTimeout(mobileWindowsCheck.timer);
    mobileWindowsCheck = null;
    button.disabled = false;
    scanButton.disabled = false;
    $("#mobile-clear-windows").disabled = false;
    button.textContent = "连接";
    button.setAttribute("aria-busy", "false");
    scanButton.setAttribute("aria-busy", "false");
    input.disabled = false;
    codeInput.disabled = false;
    if (success) codeInput.value = "";
    $("#mobile-windows-result").textContent = message || (success ? "配对成功，可以开始同步。" : "连接失败，请检查 PC 服务和配对码。");
    $("#mobile-windows-result").dataset.state = success ? "ready" : "offline";
    try {
      const status = JSON.parse(window.FujimiMobile.mobileStatus());
      delete input.dataset.dirty;
      status.connection_detail = message;
      if (!success && status.windows_status === "checking") status.windows_status = "offline";
      renderMobileNodeStatus(status);
    } catch (_error) { $("#mobile-sync-now").disabled = true; }
  };
  mobileWindowsCheck = { id: callbackId, finish, timer: scan ? null : window.setTimeout(() => finish(false, "连接超时，请检查 PC 服务和网络后重试。"), 45000) };
  window.__fujimiWindowsCheckPhase = (id, phase) => {
    if (mobileWindowsCheck?.id !== id) return;
    window.clearTimeout(mobileWindowsCheck.timer);
    mobileWindowsCheck.timer = phase === 'connecting' ? window.setTimeout(() => finish(false, "连接超时，请检查 PC 服务和网络后重试。"), 45000) : null;
    window.dispatchEvent(new CustomEvent('fujimi-pairing-phase', { detail: { phase } }));
  };
  window.__fujimiWindowsCheckResult = (id, success, message) => {
    if (mobileWindowsCheck?.id === id) finish(Boolean(success), message || (success ? "配对成功。" : "配对失败。"));
  };
  try {
    const bridge = window.FujimiMobile;
    if (scan) {
      if (!bridge?.scanWindowsPairing) throw new Error("当前 APK 不支持扫码，请更新安装包。");
      if (bridge.scanWindowsPairing(callbackId) === false) throw new Error("相机无法启动，请使用地址和配对码连接。");
    } else {
      if (!bridge?.pairWindows) throw new Error("当前 APK 不支持配对，请更新安装包。");
      if (bridge.pairWindows(address, code, callbackId) === false) throw new Error("配对任务未能启动，请重试。");
    }
  } catch (error) { finish(false, error.message || "无法连接 Windows。"); }
}

function clearMobileWindowsAddress() {
  try {
    if (!window.FujimiMobile?.setServerUrl("")) throw new Error("地址清除失败。");
  } catch (error) { toast(error.message || "地址清除失败。", true); return; }
  if (mobileWindowsCheck) mobileWindowsCheck.finish(false, "连接已取消。");
  delete $("#mobile-windows-address").dataset.dirty;
  $("#mobile-windows-address").removeAttribute("aria-invalid");
  $("#mobile-windows-address").value = "";
  $("#mobile-windows-code").value = "";
  $("#mobile-windows-result").textContent = "尚未填写 PC 地址。";
  $("#mobile-windows-result").dataset.state = "unconfigured";
  stopMobileSyncPoll();
  toast("已清除 Windows 地址");
  loadDesktopSettings();
}

function requestMobileExactAlarm() {
  try {
    if (!window.FujimiMobile?.requestExactAlarmPermission()) throw new Error();
  } catch (_error) { toast("系统无法打开精确闹钟设置。", true); }
}

async function openDesktopFolder(kind) {
  try {
    const result = kind === "data"
      ? await window.pywebview.api.open_data_dir()
      : await window.pywebview.api.open_log_dir();
    if (!result.ok) throw new Error("无法打开文件夹");
    panelError("#desktop-settings-error");
  } catch (error) {
    panelError("#desktop-settings-error", error.message || "无法打开文件夹");
  }
}

function captureBookPosition(root, payload = state.libraryChapter) {
  if (!payload || !root?.isConnected || !isBookReaderActive(root)) return;
  const block = currentBookBlock(root);
  rememberBookPosition(payload, block, block ? block.getBoundingClientRect().top : 0);
}

function updateBookReaderProgress(payload, root) {
  const indicator = $(".book-reader-progress", root);
  if (!indicator || !payload?.book?.chapters?.length) return;
  const chapters = payload.book.chapters;
  const chapterIndex = chapters.findIndex(chapter => Number(chapter.id) === Number(payload.chapter?.id));
  if (chapterIndex < 0) return;
  const currentBlock = currentBookBlock(root);
  const atEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
  const chapterBlocks = Number(payload.chapter.block_count || chapters[chapterIndex].block_count || 0);
  const blockIndex = atEnd && chapterBlocks ? chapterBlocks - 1 : Number(currentBlock?.dataset.blockIndex ?? payload.book.progress?.block_index ?? 0);
  const bookmark = (payload.book.bookmarks || []).find(item => Number(item.chapter_id) === Number(payload.chapter?.id));
  const position = bookmark ? Number(bookmark.block_index) : blockIndex;
  const percent = chapterProgressPercent({ block_count: chapterBlocks }, position);
  const label = `${payload.chapter.title}（${percent.toFixed(2)}%）`;
  indicator.textContent = label;
  indicator.setAttribute("aria-label", `読書進捗 ${label}`);
}

async function persistBookProgress(root, payload = state.libraryChapter) {
  if (!payload || !root?.isConnected || !isBookReaderActive(root)) return;
  const block = currentBookBlock(root);
  const scrollOffset = block ? block.getBoundingClientRect().top : 0;
  rememberBookPosition(payload, block, scrollOffset);
  const progress = payload.book.progress || {};
  const browserPosition = state.browserSpeech?.root === root ? state.browserSpeech.index : null;
  const audioTime = state.libraryChapter === payload ? (browserPosition ?? state.articleAudio?.audio?.currentTime ?? progress.audio_time ?? 0) : (progress.audio_time || 0);
  try {
    const book = await api(`/api/books/${payload.book.id}/progress`, {
      method: "PUT",
      body: JSON.stringify({ chapter_id: payload.chapter.id, block_index: Number(block?.dataset.blockIndex || 0), scroll_offset: scrollOffset, scroll_left: $(".book-chapter-body", root)?.scrollLeft || 0, audio_time: audioTime, reading_mode: progress.reading_mode || "horizontal", language_mode: progress.language_mode || "parallel" }),
    });
    payload.book.progress = book.progress;
    updateBookReaderProgress(payload, root);
  } catch (_error) { /* Reading must not be interrupted by progress persistence. */ }
}

function scheduleBookProgress(root) {
  if (state.libraryProgressTimer) clearTimeout(state.libraryProgressTimer);
  const payload = state.libraryChapter;
  state.libraryProgressTimer = setTimeout(() => persistBookProgress(root, payload), 450);
}

function normalizeBookParagraphIndent(element) {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    node.nodeValue = node.nodeValue.replace(/^[\s　]+/, "");
    if (node.nodeValue) return;
    node = walker.nextNode();
  }
}

function setBookTranslationReveal(root, mode) {
  const clickToReveal = mode === "click";
  root.querySelectorAll(".book-block-zh").forEach(element => {
    if (!element.dataset.translationText) element.dataset.translationText = element.textContent || "";
    if (!element.dataset.translationText) return;
    let translationMain = element.querySelector(".translation-main");
    let translationPlaceholder = element.querySelector(".translation-placeholder");
    if (!translationMain) {
      translationMain = document.createElement("span");
      translationMain.className = "translation-main";
      translationMain.textContent = element.dataset.translationText;
      translationPlaceholder = document.createElement("span");
      translationPlaceholder.className = "translation-placeholder";
      // translationPlaceholder.textContent = "クリックで訳文を表示";
      translationPlaceholder.textContent = "［クリックで表示］";
      element.replaceChildren(translationMain, translationPlaceholder);
    }
    if (!clickToReveal) element.dataset.translationRevealed = "false";
    let pointerStart = null;
    element.onpointerdown = event => {
      pointerStart = { x: event.clientX, y: event.clientY };
      element.dataset.translationDrag = "false";
    };
    element.onpointermove = event => {
      if (!pointerStart) return;
      if (Math.abs(event.clientX - pointerStart.x) > 3 || Math.abs(event.clientY - pointerStart.y) > 3) element.dataset.translationDrag = "true";
    };
    element.onpointerup = () => {
      pointerStart = null;
      window.setTimeout(() => { element.dataset.translationDrag = "false"; }, 0);
    };
    element.onpointercancel = () => {
      pointerStart = null;
      element.dataset.translationDrag = "false";
    };
    element.onclick = event => {
      event.stopPropagation();
      if (!clickToReveal) return;
      const selection = window.getSelection();
      const draggedToSelect = element.dataset.translationDrag === "true";
      element.dataset.translationDrag = "false";
      if (draggedToSelect || (selection && !selection.isCollapsed)) return;
      element.dataset.translationRevealed = String(element.dataset.translationRevealed !== "true");
      setBookTranslationReveal(root, "click");
    };
    element.onkeydown = event => {
      if (!clickToReveal || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      element.click();
    };
    const revealed = clickToReveal && element.dataset.translationRevealed === "true";
    element.classList.toggle("book-translation-reveal", clickToReveal);
    element.classList.toggle("is-click-hidden", clickToReveal && !revealed);
    element.classList.toggle("is-revealed", revealed);
    element.tabIndex = clickToReveal ? 0 : -1;
    element.setAttribute("role", clickToReveal ? "button" : "presentation");
    if (clickToReveal) element.setAttribute("aria-label", revealed ? "クリックで訳文を隠す" : "クリックで訳文を表示");
    else element.removeAttribute("aria-label");
    translationMain.textContent = element.dataset.translationText;
  });
}

function setBookReadingMode(root, mode) {
  const progress = state.libraryChapter.book.progress || (state.libraryChapter.book.progress = {});
  progress.reading_mode = mode;
  root.classList.toggle("is-vertical", mode === "vertical");
  root.querySelectorAll("[data-reading-mode]").forEach(button => button.classList.toggle("active", button.dataset.readingMode === mode));
  scheduleBookProgress(root);
}

function setBookLanguageMode(root, mode) {
  const progress = state.libraryChapter.book.progress || (state.libraryChapter.book.progress = {});
  progress.language_mode = mode;
  root.dataset.languageMode = mode;
  setBookTranslationReveal(root, mode);
  root.querySelectorAll("[data-language-mode]").forEach(button => button.classList.toggle("active", button.dataset.languageMode === mode));
  scheduleBookProgress(root);
}

function closeBookToc(root, { restoreFocus = false } = {}) {
  const toc = $(".book-toc", root);
  const trigger = $(".toggle-book-toc", root);
  if (!toc || toc.hidden) return;
  toc.hidden = true;
  trigger?.setAttribute("aria-expanded", "false");
  if (restoreFocus) trigger?.focus();
}

function openBookToc(root) {
  const toc = $(".book-toc", root);
  const trigger = $(".toggle-book-toc", root);
  if (!toc) return;
  toc.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
}

function closeBookSettings(root, { restoreFocus = true } = {}) {
  const panel = $(".book-settings-panel", root);
  const trigger = $(".toggle-book-settings", root);
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  $(".book-settings-scrim", root)?.setAttribute("hidden", "");
  root.classList.remove("settings-open");
  trigger?.setAttribute("aria-expanded", "false");
  if (restoreFocus) trigger?.focus();
}

function openBookSettings(root) {
  const panel = $(".book-settings-panel", root);
  const trigger = $(".toggle-book-settings", root);
  if (!panel) return;
  panel.hidden = false;
  $(".book-settings-scrim", root)?.removeAttribute("hidden");
  root.classList.add("settings-open");
  trigger?.setAttribute("aria-expanded", "true");
  requestAnimationFrame(() => $("select, button", panel)?.focus());
}

function toggleBookSettings(root) {
  const panel = $(".book-settings-panel", root);
  if (!panel) return;
  if (panel.hidden) openBookSettings(root);
  else closeBookSettings(root);
}

async function toggleBookBlockBookmark(button, block) {
  const payload = state.libraryChapter;
  try {
    const wasBookmarked = button.classList.contains("is-bookmarked");
    const result = await api(`/api/books/${payload.book.id}/chapters/${payload.chapter.id}/bookmarks`, { method: "POST", body: JSON.stringify({ block_index: block.block_index, excerpt: block.text_ja || block.text_zh || "" }), mobileChangeAction: wasBookmarked ? "delete" : "upsert" });
    if (result.bookmarked) {
      button.closest('#book-reader')?.querySelectorAll('.book-block-bookmark').forEach(other => {
        if (other !== button) {
          other.classList.remove('is-bookmarked');
          other.setAttribute('aria-pressed', 'false');
        }
      });
    }
    button.classList.toggle("is-bookmarked", result.bookmarked);
    button.setAttribute("aria-pressed", String(result.bookmarked));
    toast(result.bookmarked ? "しおりを挟みました。" : "しおりを外しました。");
    if (!result.queued) {
      payload.book = await api(`/api/books/${payload.book.id}`);
      updateBookReaderProgress(payload, button.closest('#book-reader'));
    }
  } catch (error) { toast(error.message, true); }
}

function hasBookJapaneseScript(value) {
  return /[\u3040-\u30ff]/.test(String(value || ""));
}

function isLikelyBookChinese(value) {
  const text = String(value || "").trim();
  return Boolean(text) && !hasBookJapaneseScript(text) && /[\u3400-\u9fff]/.test(text)
    && /[我你他她它们这那是的了在有不与为来去将从再视线转回前方迈步听海浪声沿着堤防虽然后家需要思考时间昨晚那件事开始也是终点老实说现在没办法接受现实有没有正确选择状况不会改变一直翻搅记忆后悔即使如此还是努力无法整合思考塑造成形状回神已经来到门前连句回来都说穿过大门走进自己房间]/.test(text);
}

function normalizeBookBlocks(blocks) {
  const normalized = [];
  let pendingChinese = "";
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    const next = blocks[index + 1];
    if (block.kind === "paragraph" && isLikelyBookChinese(block.text_ja) && next?.kind === "paragraph" && hasBookJapaneseScript(next.text_ja)) {
      pendingChinese = block.text_ja;
      continue;
    }
    if (block.kind === "paragraph" && hasBookJapaneseScript(block.text_ja)) {
      const inheritedChinese = pendingChinese;
      pendingChinese = inheritedChinese ? (block.text_zh || "") : "";
      normalized.push(inheritedChinese ? { ...block, text_zh: inheritedChinese } : block);
      continue;
    }
    if (pendingChinese) {
      normalized.push({ ...block, text_ja: "", text_zh: pendingChinese, original_language: "zh" });
      pendingChinese = "";
    }
    normalized.push(block);
  }
  if (pendingChinese) normalized.push({ kind: "paragraph", block_index: blocks.length, block_key: `block-${blocks.length + 1}`, text_ja: "", text_zh: pendingChinese, original_language: "zh" });
  return normalized;
}

function renderBookBlocks(payload, root) {
  const bookmarks = new Set((payload.book.bookmarks || []).filter(item => Number(item.chapter_id) === Number(payload.chapter.id)).map(item => Number(item.block_index)));
  let audioIndex = 0;
  const body = $(".book-chapter-body", root);
  const blocks = payload.book.parser_version >= 2 ? (payload.chapter.blocks || []) : normalizeBookBlocks(payload.chapter.blocks || []);
  // Temporarily disable spacer DOM generation. Remove this filter to restore EPUB blank lines.
  // Keep stored blocks and their indexes unchanged so reading progress remains stable.
  body.replaceChildren(...blocks.filter(block => block.kind !== "spacer").map(block => {
    const section = document.createElement("section");
    section.className = `paragraph book-block book-block-${block.kind}`;
    section.classList.toggle('book-source-pair', Boolean(block.bilingual_pair && block.text_zh));
    section.dataset.blockIndex = block.block_index;
    section.id = `book-block-${block.id}`;
    if (block.text_ja) {
      section.dataset.audioIndex = audioIndex++;
      section.tabIndex = 0;
    }
    const japanese = document.createElement("div");
    japanese.className = "book-block-ja";
    japanese.innerHTML = block.furigana_html || block.html || escapeText(block.text_ja || "");
    // EPUB illustrations may be wrapped in navigation links; display them as static images.
    japanese.querySelectorAll("a").forEach(link => {
      if (!link.querySelector("img") || link.textContent.trim()) return;
      for (const attribute of ["href", "data-book-href", "target", "rel", "tabindex", "role"]) {
        link.removeAttribute(attribute);
      }
    });
    if (block.kind === "paragraph" && !(payload.book.parser_version >= 2)) normalizeBookParagraphIndent(japanese);
    japanese.querySelectorAll("ruby").forEach(ruby => {
      if (ruby.querySelector(":scope > rb")) return;
      const base = document.createElement("rb");
      [...ruby.childNodes]
        .filter(node => !(node.nodeType === Node.ELEMENT_NODE && ["RT", "RP"].includes(node.tagName)))
        .forEach(node => base.append(node));
      ruby.insertBefore(base, ruby.firstChild);
    });
    const chinese = document.createElement("p");
    chinese.className = "book-block-zh";
    chinese.textContent = block.text_zh || "";
    if (block.kind === "paragraph" && !(payload.book.parser_version >= 2)) normalizeBookParagraphIndent(chinese);
    if (!block.text_zh) chinese.hidden = true;
    const bookmark = document.createElement("button");
    bookmark.type = "button";
    bookmark.className = `book-block-bookmark${bookmarks.has(Number(block.block_index)) ? " is-bookmarked" : ""}`;
    bookmark.setAttribute("aria-label", "この段落にしおりを挟む");
    bookmark.setAttribute("aria-pressed", String(bookmarks.has(Number(block.block_index))));
    bookmark.title = "しおり";
    bookmark.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>';
    bookmark.onclick = event => { event.stopPropagation(); toggleBookBlockBookmark(bookmark, block); };
    for (const id of (block.anchor_ids || [])) {
      if (!japanese.querySelector(`[id="${CSS.escape(id)}"]`)) {
        const anchor = document.createElement('span'); anchor.id = id; anchor.className = 'book-source-anchor';
        japanese.prepend(anchor);
      }
    }
    section.append(japanese, chinese);
    if (bookBlockSupportsBookmark(payload.chapter, block)) section.append(bookmark);
    return section;
  }));
  body.querySelectorAll("img[data-book-asset]").forEach(image => {
    image.src = bookAssetUrl(payload.book.id, image.dataset.bookAsset);
    image.loading = "lazy";
    image.addEventListener("error", () => replaceMissingBookImage(image, "插图暂不可用"), { once: true });
  });
  const chaptersByHref = new Map();
  payload.book.chapters.forEach(chapter => {
    (chapter.source_hrefs || [chapter.source_href]).forEach(href => chaptersByHref.set(href, chapter));
  });
  body.querySelectorAll("a[data-book-href]").forEach(link => {
    const [href, fragment] = link.dataset.bookHref.split("#");
    const target = (payload.book.chapters || []).find(ch => (ch.id === payload.chapter.id && (ch.source_hrefs || [ch.source_href]).includes(href))) || chaptersByHref.get(href);
    if (!target) return;
    link.href = `#library/book/${payload.book.id}/chapter/${target.id}${fragment ? `?anchor=${encodeURIComponent(fragment)}` : ""}`;
    link.onclick = event => { event.preventDefault(); navigateBookChapter(payload.book.id, target.id, { anchor: fragment || "" }); };
  });
  prepareMobileReadingLookup(root, ".book-chapter-body", ".book-block-ja");
}

function setupBookAudio(payload, root) {
  const paragraphs = payload.chapter.blocks.filter(block => block.text_ja).map(block => block.text_ja);
  const audio = $(".book-audio", root);
  if (payload.chapter.audio_unavailable_detail) {
    if (window.FujimiMobile?.request) setupBrowserArticlePlayer({ paragraphs }, root);
    else setRereadTask(root, "failed", payload.chapter.audio_unavailable_detail);
    return;
  }
  if (payload.chapter.audio?.url && payload.chapter.voice_mode !== "none"
      && (payload.chapter.voice_mode !== "browser" || payload.chapter.audio.voice_id == null && payload.chapter.audio.voice_name)) {
    audio.src = mobileMediaUrl(payload.chapter.audio.url);
    setupNativeArticlePlayer({ paragraphs, audio_segments: payload.chapter.audio.segments || [] }, root, audio);
    if (Number(payload.book.progress?.chapter_id) === Number(payload.chapter.id) && payload.book.progress?.audio_time) audio.currentTime = Number(payload.book.progress.audio_time);
    audio.addEventListener("timeupdate", () => scheduleBookProgress(root));
  } else if (payload.chapter.voice_mode === "browser") {
    setupBrowserArticlePlayer({ paragraphs }, root);
    if (state.browserSpeech?.root === root && Number(payload.book.progress?.chapter_id) === Number(payload.chapter.id)) {
      state.browserSpeech.index = Math.max(0, Math.min(state.browserSpeech.text.length, Number(payload.book.progress?.audio_time || 0)));
      renderBrowserSpeech(state.browserSpeech);
    }
  }
}

async function startBookTaskTracking(taskId, root) {
  const taskBox = $(".book-task", root);
  const trackedBook = state.libraryChapter;
  const generateButton = $(".generate-book-audio", root);
  generateButton.disabled = true;
  state.libraryTaskId = taskId;
  taskBox.dataset.taskId = taskId;
  closeBookSettings(root);
  try {
    while (root.isConnected && state.currentView === "library" && state.libraryChapter === trackedBook) {
      const task = await api(`/api/books/tasks/${taskId}`);
      taskBox.hidden = false;
      $("strong", taskBox).textContent = task.message || "処理しています…";
      const progress = $("progress", taskBox);
      progress.max = Math.max(1, Number(task.total || 1));
      progress.value = Number(task.completed || 0);
      $(".cancel-book-task", taskBox).hidden = !["queued", "running", "cancelling"].includes(task.status);
      if (["completed", "failed", "cancelled", "duplicate", "interrupted"].includes(task.status)) {
        if (task.status === "completed") {
          toast("処理が完了しました。");
          await navigateBookChapter(state.libraryChapter.book.id, state.libraryChapter.chapter.id, { historyMode: "replace" });
        } else if (["failed", "interrupted"].includes(task.status)) {
          if (redesignedReadingUi) taskBox.hidden = true;
          toast(task.message, true);
        } else if (task.status === "cancelled") {
          taskBox.hidden = true;
        }
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 700));
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (state.libraryChapter === trackedBook) generateButton.disabled = false;
    if (state.libraryTaskId === taskId) state.libraryTaskId = null;
    if (taskBox.dataset.taskId === taskId) delete taskBox.dataset.taskId;
  }
}

async function generateBookChapterAudio(root) {
  const payload = state.libraryChapter;
  const value = $(".book-voice", root).value;
  const [mode, rawId] = value.split(":");
  try {
    let browserName = mode === "browser" ? state.browserVoiceName : "";
    if (mode === "browser" && !browserName) {
      const selected = await resolveJapaneseBrowserVoice({ persistDefault: true });
      browserName = selected?.id || selected?.name || "";
      if (!browserName) throw new Error("利用できる日本語のブラウザー音声がありません。");
    }
    if (mobileSelectionNeedsPc({ mode, browser_voice_name: browserName })) {
      await generateMobilePcSpeech(root, { mode, voice_id: rawId ? Number(rawId) : null, browser_voice_name: browserName });
      return;
    }
    const taskBox = $(".book-task", root);
    taskBox.hidden = false;
    $(".reread-task-label", taskBox).textContent = "音声生成を準備しています…";
    const progress = $("progress", taskBox);
    progress.max = 1;
    progress.value = 0;
    $(".cancel-book-task", taskBox).hidden = false;
    const result = await api(`/api/books/${payload.book.id}/chapters/${payload.chapter.id}/reread`, { method: "POST", body: JSON.stringify({ mode, voice_id: rawId ? Number(rawId) : null, browser_voice_name: browserName }) });
    if (result.status === "browser") {
      await navigateBookChapter(payload.book.id, payload.chapter.id, { historyMode: "replace" });
      toast("ブラウザー音声を設定しました。");
    } else if (result.status === "ready") {
      await navigateBookChapter(payload.book.id, payload.chapter.id, { historyMode: "replace" });
      toast(mode === "browser" && !result.cached ? "ブラウザー音声を保存しました。" : "キャッシュ済みの朗読を読み込みました。");
    } else if (result.task_id) startBookTaskTracking(result.task_id, root);
  } catch (error) {
    $(".book-task", root).hidden = true;
    toast(error.message, true);
  }
}

function setupBookReaderChrome(payload, root, chapterIndex) {
  const header = $(".book-reader-header", root);
  const oldTop = $(".book-reader-top", root);
  const oldHeading = $(".book-chapter-heading", root);
  const oldReaderSettings = $(".book-reader-settings", root);
  const oldLearningTools = $(".book-learning-tools", root);
  if (!header || !oldTop || !oldHeading || !oldReaderSettings || !oldLearningTools) return;

  const back = $(".back-to-library", oldTop);
  const title = $("div", oldTop);
  const toc = $(".toggle-book-toc", oldHeading);
  const tocPanel = $(".book-toc", root);
  const chapterSelect = $(".book-chapter-select", oldHeading);
  const chapterCount = $("span", oldHeading);
  if (!back || !title || !toc || !tocPanel || !chapterSelect || !chapterCount) return;
  const chrome = document.createElement("div");
  chrome.className = "book-reader-chrome";
  const titleBlock = document.createElement("div");
  titleBlock.className = "book-reader-title";
  titleBlock.append(title);
  const chapterBlock = document.createElement("div");
  chapterBlock.className = "book-reader-chapter-picker";
  chapterCount.className = "book-chapter-count";
  chapterBlock.append(chapterSelect, chapterCount);
  toc.innerHTML = `${BOOK_TOC_ICON}<span>目次</span>`;
  toc.setAttribute("aria-label", "目次");
  toc.setAttribute("title", "目次");
  toc.setAttribute("aria-controls", `book-toc-${payload.book.id}`);
  toc.setAttribute("aria-expanded", "false");
  toc.classList.remove("quiet");
  toc.classList.add("icon-tool", "book-reader-tool");
  tocPanel.id = `book-toc-${payload.book.id}`;
  const settingsToggle = document.createElement("button");
  settingsToggle.type = "button";
  settingsToggle.className = "toggle-book-settings icon-tool book-reader-tool";
  settingsToggle.setAttribute("aria-label", "読書設定");
  settingsToggle.setAttribute("title", "読書設定");
  settingsToggle.setAttribute("aria-controls", `book-settings-${payload.book.id}`);
  settingsToggle.setAttribute("aria-expanded", "false");
  settingsToggle.innerHTML = `${BOOK_SETTINGS_ICON}<span>設定</span>`;
  chrome.append(titleBlock, chapterBlock, toc, settingsToggle, back);

  const scrim = document.createElement("div");
  scrim.className = "book-settings-scrim";
  scrim.hidden = true;
  const panel = document.createElement("aside");
  panel.className = "book-settings-panel";
  panel.id = `book-settings-${payload.book.id}`;
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "読書設定");
  panel.innerHTML = '<header class="book-settings-panel-head"><div><span class="section-kicker">READING SETTINGS</span><h2>読書設定</h2></div><button class="close-book-settings icon-tool" type="button" aria-label="読書設定を閉じる" title="読書設定を閉じる">×</button></header>';

  const readingSection = document.createElement("section");
  readingSection.className = "book-settings-section";
  readingSection.innerHTML = '<h3>読む</h3>';
  const readingLabel = document.createElement("div");
  readingLabel.className = "book-settings-label";
  readingLabel.textContent = "組み方向";
  const languageLabel = document.createElement("div");
  languageLabel.className = "book-settings-label";
  languageLabel.textContent = "表示";
  readingSection.append(readingLabel, oldReaderSettings.querySelector(".segmented"), languageLabel, oldReaderSettings.querySelector(".book-language-switch"));

  const audioSection = document.createElement("section");
  audioSection.className = "book-settings-section";
  audioSection.innerHTML = '<h3>朗読</h3>';
  const voiceLabel = document.createElement("label");
  voiceLabel.className = "book-settings-label";
  voiceLabel.textContent = "この章の声線";
  voiceLabel.append(oldLearningTools.querySelector(".book-voice"));
  const audioActions = document.createElement("div");
  audioActions.className = "book-settings-actions";
  audioActions.append(oldLearningTools.querySelector(".generate-book-audio"));
  audioSection.append(voiceLabel, audioActions);

  const learningSection = document.createElement("section");
  learningSection.className = "book-settings-section";
  learningSection.innerHTML = '<h3>学習</h3>';
  const learningActions = document.createElement("div");
  learningActions.className = "book-settings-actions book-settings-actions-stack";
  learningActions.append(oldLearningTools.querySelector(".enhance-book-chapter"));
  const clearEnrichment = document.createElement("button");
  clearEnrichment.type = "button";
  clearEnrichment.className = "clear-book-chapter-enrichment danger-outline";
  clearEnrichment.textContent = "この章の処理結果を消去";
  clearEnrichment.onclick = async () => {
    try {
      clearEnrichment.disabled = true;
      await api(`/api/books/${payload.book.id}/chapters/${payload.chapter.id}/enrichment`, { method: "DELETE" });
      toast("本章の処理結果を消去しました。");
      await navigateBookChapter(payload.book.id, payload.chapter.id, { historyMode: "replace" });
    } catch (error) {
      toast(error.message, true);
    } finally {
      clearEnrichment.disabled = false;
    }
  };
  learningActions.append(clearEnrichment);
  learningSection.append(learningActions);

  const dictionarySection = document.createElement("section");
  dictionarySection.className = "book-settings-section";
  dictionarySection.innerHTML = '<h3>辞書</h3>';
  const chineseLookup = document.createElement("label");
  chineseLookup.className = "book-settings-checkbox";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.libraryLookupChineseTranslations;
  checkbox.setAttribute("aria-label", "訳文でも辞書を引く");
  chineseLookup.append(checkbox, document.createTextNode("訳文でも辞書を引く"));
  checkbox.onchange = async () => {
    await updateLibraryChineseLookup(checkbox.checked);
    checkbox.checked = state.libraryLookupChineseTranslations;
  };
  dictionarySection.append(chineseLookup);
  panel.append(readingSection, audioSection, learningSection, dictionarySection);
  oldTop.remove();
  oldHeading.remove();
  oldReaderSettings.remove();
  oldLearningTools.remove();
  header.prepend(chrome);
  root.append(scrim, panel);

  settingsToggle.onclick = () => toggleBookSettings(root);
  scrim.onclick = () => closeBookSettings(root);
  $(".close-book-settings", panel).onclick = () => closeBookSettings(root);
  if (state.libraryTocOutsideClick) document.removeEventListener("click", state.libraryTocOutsideClick);
  state.libraryTocOutsideClick = event => {
    if (tocPanel.hidden) return;
    const target = event.target;
    if (target instanceof Node && (tocPanel.contains(target) || toc.contains(target))) return;
    closeBookToc(root);
  };
  document.addEventListener("click", state.libraryTocOutsideClick);
  if (state.librarySettingsKeydown) root.removeEventListener("keydown", state.librarySettingsKeydown);
  state.librarySettingsKeydown = event => {
    if (event.key !== "Escape") return;
    if (!panel.hidden) {
      event.preventDefault();
      closeBookSettings(root);
    } else if (!tocPanel.hidden) {
      event.preventDefault();
      closeBookToc(root, { restoreFocus: true });
    }
  };
  root.addEventListener("keydown", state.librarySettingsKeydown);
  chapterCount.textContent = `${chapterIndex + 1}/${payload.book.chapters.length}`;
}

async function renderBookReader(payload, { blockId = null, blockIndex = null, anchor = "", startAtBeginning = false } = {}) {
  stopArticlePlayback();
  state.libraryBook = payload.book;
  state.libraryChapter = payload;
  const root = $("#book-reader");
  $("#library-home").hidden = true;
  $("#library-series-detail").hidden = true;
  root.hidden = false;
  const chapterIndex = payload.book.chapters.findIndex(item => Number(item.id) === Number(payload.chapter.id));
  const previous = payload.book.chapters[chapterIndex - 1];
  root.dataset.parserVersion = String(payload.book.parser_version || 1);
  root.classList.toggle('is-frontmatter', Boolean(payload.chapter.is_frontmatter));
  const next = payload.book.chapters[chapterIndex + 1];
  root.innerHTML = `<article class="book-reader-shell"><header class="book-reader-header"><div class="book-reader-top"><button class="back-to-library icon-tool" type="button" aria-label="書架に戻る" title="書架に戻る">${BOOK_X_ICON}</button><div><span>${escapeText([payload.book.series, payload.book.volume ? `第 ${payload.book.volume} 巻` : ""].filter(Boolean).join(" · ") || "LIGHT NOVEL")}</span><h2>${escapeText(payload.book.title)}</h2><p class="book-reader-author"><span class="book-reader-author-name">${escapeText(payload.book.author || "")}</span><span class="book-reader-progress" role="status"></span></p></div></div><div class="book-chapter-heading"><button class="toggle-book-toc quiet" type="button">目次</button><select class="book-chapter-select" aria-label="章を選択">${payload.book.chapters.map(chapter => `<option value="${chapter.id}"${Number(chapter.id) === Number(payload.chapter.id) ? " selected" : ""}>${escapeText(chapter.title)}</option>`).join("")}</select><span>${chapterIndex + 1}/${payload.book.chapters.length}</span></div><div class="book-reader-settings"><div class="segmented compact"><button type="button" data-reading-mode="horizontal">横書き</button><button type="button" data-reading-mode="vertical">縦書き</button></div><div class="segmented compact book-language-switch"><button type="button" data-language-mode="parallel">日中対照</button><button type="button" data-language-mode="click">クリックで表示</button><button type="button" data-language-mode="ja">日本語</button><button type="button" data-language-mode="zh">中文</button></div></div><div class="book-learning-tools"><select class="book-voice" aria-label="この章の声線"></select><button class="generate-book-audio" type="button">${payload.chapter.audio?.status === "ready" ? "朗読を再生成" : "朗読を生成"}</button><button class="enhance-book-chapter quiet" type="button">この章を処理</button></div><div class="book-task reread-task" role="status" hidden><div><strong class="reread-task-label"></strong><button class="cancel-book-task reread-task-cancel" type="button" aria-label="処理を中止" title="処理を中止">×</button></div><progress max="1" value="0"></progress></div></header><aside class="book-toc" hidden><div><strong>目次</strong><button type="button" aria-label="目次を閉じる">×</button></div>${payload.book.chapters.map(chapter => `<button type="button" data-chapter-id="${chapter.id}" data-depth="${Math.max(0, Number(chapter.nav_depth || 0))}" class="${Number(chapter.id) === Number(payload.chapter.id) ? "active" : ""}">${escapeText(chapter.title)}</button>`).join("")}</aside><main class="book-chapter"><h1>${escapeText(payload.chapter.title)}</h1><div class="book-chapter-body"></div></main><footer class="book-chapter-footer"><button class="previous-chapter quiet" type="button"${previous ? "" : " disabled"}>← 前の章</button><button class="next-chapter" type="button"${next ? "" : " disabled"}>次の章 →</button></footer><audio class="book-audio" preload="metadata"></audio>${bookAudioPlayerMarkup()}</article>`;
  if (payload.chapter.show_heading === false) $(".book-chapter > h1", root).hidden = true;
  setupBookReaderChrome(payload, root, chapterIndex);
  setupBookNavigation(payload, root);
  const bookTask = $(".book-task", root);
  $(".book-voice", root).replaceChildren(...bookVoiceOptions(payload.chapter));
  $(".book-voice", root).onchange = async event => {
    const [mode, rawId] = event.target.value.split(":");
    try {
      await api(`/api/books/${payload.book.id}/chapters/${payload.chapter.id}/voice`, { method: "PUT", body: JSON.stringify({ mode, voice_id: rawId ? Number(rawId) : null }) });
      payload.chapter.voice_mode = mode;
      payload.chapter.voice_id = rawId ? Number(rawId) : null;
    } catch (error) { toast(error.message, true); }
  };
  renderBookBlocks(payload, root);
  const progress = payload.book.progress || {};
  setBookReadingMode(root, progress.reading_mode || "horizontal");
  setBookLanguageMode(root, progress.language_mode || "parallel");
  updateBookReaderProgress(payload, root);
  $(".back-to-library", root).onclick = async () => {
    scheduleBookProgress(root);
    const target = payload.book.series ? `#library/series/${encodeURIComponent(payload.book.series)}` : "#library";
    history.pushState({ view: "library" }, "", target);
    await loadLibrary();
  };
  $(".book-chapter-select", root).onchange = event => navigateBookChapter(payload.book.id, Number(event.target.value), {startAtBeginning:true});
  $(".toggle-book-toc", root).onclick = () => openBookToc(root);
  $(".book-toc > div button", root).onclick = () => closeBookToc(root, { restoreFocus: true });
  root.querySelectorAll(".book-toc [data-chapter-id]").forEach(button => { button.onclick = () => navigateBookChapter(payload.book.id, Number(button.dataset.chapterId), {anchor: button.dataset.anchor || "", startAtBeginning: !button.dataset.anchor}); });
  root.querySelectorAll("[data-reading-mode]").forEach(button => { button.onclick = () => setBookReadingMode(root, button.dataset.readingMode); });
  root.querySelectorAll("[data-language-mode]").forEach(button => { button.onclick = () => setBookLanguageMode(root, button.dataset.languageMode); });
  $(".previous-chapter", root).onclick = () => previous && navigateBookChapter(payload.book.id, previous.id);
  $(".next-chapter", root).onclick = () => next && navigateBookChapter(payload.book.id, next.id);
  $(".generate-book-audio", root).onclick = () => generateBookChapterAudio(root);
  $(".enhance-book-chapter", root).onclick = async () => {
    try {
      const result = await api(`/api/books/${payload.book.id}/chapters/${payload.chapter.id}/enhance`, { method: "POST" });
      startBookTaskTracking(result.task_id, root);
    } catch (error) { toast(error.message, true); }
  };
  $(".cancel-book-task", root).onclick = async () => {
    if (root.pcSpeechJob) {
      const job = root.pcSpeechJob;
      if (job.id) await api(`/api/pc-speech/tasks/${job.id}`, { method: "DELETE" });
      job.cancelled = true;
      return;
    }
    const cancelButton = $(".cancel-book-task", root);
    let taskId = bookTask.dataset.taskId || state.libraryTaskId;
    if (!taskId) {
      const tasks = await api("/api/books/tasks");
      const running = (tasks.tasks || []).find(task => Number(task.book_id) === Number(payload.book.id) && Number(task.chapter_id) === Number(payload.chapter.id) && ["queued", "running", "cancelling"].includes(task.status));
      taskId = running?.id || "";
    }
    if (!taskId) {
      toast("中止できる処理が見つかりませんでした。", true);
      return;
    }
    cancelButton.disabled = true;
    $(".reread-task-label", bookTask).textContent = "音声生成を中止しています…";
    try {
      const result = await api(`/api/books/tasks/${taskId}`, { method: "DELETE" });
      if (state.libraryTaskId === taskId) state.libraryTaskId = null;
      delete bookTask.dataset.taskId;
      bookTask.hidden = true;
      await navigateBookChapter(payload.book.id, payload.chapter.id, { historyMode: "replace" });
      toast(result.status === "cancelled" ? "音声生成を中止しました。" : "実行中の処理はありません。");
    } catch (error) {
      toast(error.message, true);
      cancelButton.disabled = false;
    }
  };
  if (state.libraryScrollHandler) window.removeEventListener("scroll", state.libraryScrollHandler);
  state.libraryScrollHandler = () => {
    if (state.libraryChapter === payload && isBookReaderActive(root)) {
      updateBookReaderProgress(payload, root);
      captureBookPosition(root, payload);
      scheduleBookProgress(root);
    }
  };
  window.addEventListener("scroll", state.libraryScrollHandler, { passive: true });
  $(".book-chapter-body", root).addEventListener("scroll", state.libraryScrollHandler, {passive:true});
  setupBookAudio(payload, root);
  if (["failed", "interrupted"].includes(payload.chapter.audio_task?.status)) {
    bookTask.hidden = redesignedReadingUi;
    $(".reread-task-label", bookTask).textContent = payload.chapter.audio_task.message;
    $(".cancel-book-task", bookTask).hidden = true;
    if (redesignedReadingUi) toast(payload.chapter.audio_task.message, true);
  }
  api("/api/books/tasks").then(tasks => {
    const running = (tasks.tasks || []).find(task => Number(task.book_id) === Number(payload.book.id) && Number(task.chapter_id) === Number(payload.chapter.id) && ["queued", "running", "cancelling"].includes(task.status));
    if (running) startBookTaskTracking(running.id, root);
  }).catch(() => { });
  requestAnimationFrame(() => {
    if (startAtBeginning) {
      window.scrollTo({ top: 0, behavior: "auto" });
      updateBookReaderProgress(payload, root);
      return;
    }
    const escapedAnchor = anchor && window.CSS?.escape ? CSS.escape(anchor) : "";
    const remembered = !startAtBeginning && !escapedAnchor && !blockId && blockIndex === null ? rememberedBookPosition(payload.book.id, payload.chapter.id) : null;
    const restoreBlockIndex = blockIndex !== null
      ? Number(blockIndex)
      : remembered ? Number(remembered.blockIndex || 0) : (Number(progress.chapter_id) === Number(payload.chapter.id) ? Number(progress.block_index || 0) : 0);
    const sameSavedChapter = Number(progress.chapter_id) === Number(payload.chapter.id);
    const restoreOffset = remembered ? Number(remembered.scrollOffset || 0) : sameSavedChapter ? Number(progress.scroll_offset || 0) : 0;
    progress.scroll_offset = Number(progress.scroll_offset || 0);
    const shouldRestore = !startAtBeginning && Boolean(escapedAnchor || blockId || blockIndex !== null || (sameSavedChapter && payload.book.last_read_at) || remembered);
    const target = shouldRestore ? (escapedAnchor ? $(`#${escapedAnchor}`, root) : blockId ? $(`#book-block-${blockId}`, root) : $(`.book-block[data-block-index="${restoreBlockIndex}"]`, root)) : null;
    if (!target) {
      window.scrollTo({top:0,behavior:'auto'});
      updateBookReaderProgress(payload, root);
      return;
    }
    let userMoved = false;
    const cancelRestore = () => { userMoved = true; };
    root.addEventListener('wheel', cancelRestore, {once:true, passive:true});
    root.addEventListener('touchstart', cancelRestore, {once:true, passive:true});
    const restore = () => {
      if (!root.isConnected || userMoved || state.libraryChapter !== payload) return;
      if (root.classList.contains('is-vertical') && !escapedAnchor && !blockId && blockIndex === null) {
        $(".book-chapter-body", root).scrollLeft = remembered?.scrollLeft ?? progress.scroll_left ?? 0;
        updateBookReaderProgress(payload, root); return;
      }
      if (!escapedAnchor && !blockId && blockIndex === null && Number.isFinite(restoreOffset)) {
        const desiredTop = target.getBoundingClientRect().top + window.scrollY - restoreOffset;
        window.scrollTo({ top: Math.max(0, desiredTop), behavior: "auto" });
      } else {
        target.scrollIntoView({ block: "center", behavior: "auto" });
      }
      updateBookReaderProgress(payload, root);
    };
    restore();
    requestAnimationFrame(restore);
    window.setTimeout(restore, 120);
    root.querySelectorAll("img").forEach(image => {
      if (!image.complete) image.addEventListener("load", restore, { once: true });
    });
  });
}

async function navigateBookChapter(bookId, chapterId, { historyMode = "push", blockId = null, blockIndex = null, anchor = "", startAtBeginning = false } = {}) {
  try {
    const current = state.libraryChapter;
    const isCurrentChapter = current && Number(current.book.id) === Number(bookId) && Number(current.chapter.id) === Number(chapterId);
    if (current && !isCurrentChapter && isBookReaderActive()) await persistBookProgress($("#book-reader"), current);
    const chapterHash = `#library/book/${bookId}/chapter/${chapterId}${anchor ? `?anchor=${encodeURIComponent(anchor)}` : ""}`;
    if (historyMode === "push") history.pushState({ view: "library", bookId, chapterId }, "", chapterHash);
    else if (historyMode === "replace") history.replaceState({ view: "library", bookId, chapterId }, "", chapterHash);
    const requestId = state.bookNavigationSequence = (state.bookNavigationSequence || 0) + 1;
    const payload = await api(`/api/books/${bookId}/chapters/${chapterId}`);
    if (requestId !== state.bookNavigationSequence) return;
    if (!state.voices.length) await loadVoices();
    if (requestId !== state.bookNavigationSequence) return;
    await renderBookReader(payload, { blockId, blockIndex, anchor, startAtBeginning });
  } catch (error) {
    toast(error.message, true);
    history.replaceState({ view: "library" }, "", "#library");
    await loadLibrary({ forceHome: true });
  }
}

async function uploadBooks(files) {
  const selected = [...files].filter(file => file.name.toLowerCase().endsWith(".epub"));
  if (!selected.length) return toast("EPUB ファイルを選択してください。", true);
  const data = new FormData();
  selected.forEach(file => data.append("files", file));
  try {
    const result = await api("/api/books/import", { method: "POST", body: data });
    result.rejected?.forEach(item => toast(`${item.file_name}: ${item.message}`, true));
    toast(`${result.tasks.length} 冊の取り込みを開始しました。`);
    await loadLibrary({ forceHome: true });
  } catch (error) { toast(error.message, true); }
}

function renderBookImportTasks(tasks) {
  const active = tasks.filter(task => task.kind === "import" && ["queued", "running", "cancelling"].includes(task.status));
  const target = $("#book-import-tasks");
  target.hidden = !active.length;
  target.replaceChildren(...active.map(task => {
    const item = document.createElement("div");
    item.className = "book-import-task";
    item.innerHTML = `<div><strong>${escapeText(task.file_name || "EPUB")}</strong><span>${escapeText(task.message || "待機中")}</span><small>${task.total ? `${task.completed}/${task.total}` : ""}</small></div><progress max="${Math.max(1, Number(task.total || 1))}" value="${Number(task.completed || 0)}"></progress><button type="button" class="danger-outline">中止</button>`;
    $("button", item).onclick = () => api(`/api/books/tasks/${task.id}`, { method: "DELETE" }).then(loadBookTasks).catch(error => toast(error.message, true));
    return item;
  }));
  return active.length > 0;
}

async function loadBookTasks() {
  if (state.libraryTaskTimer) clearTimeout(state.libraryTaskTimer);
  try {
    const payload = await api("/api/books/tasks");
    const running = renderBookImportTasks(payload.tasks || []);
    if (running && state.currentView === "library") state.libraryTaskTimer = setTimeout(async () => {
      const before = (payload.tasks || []).filter(task => task.kind === "import" && ["queued", "running", "cancelling"].includes(task.status)).length;
      await loadBookTasks();
      const next = await api("/api/books/tasks");
      const after = (next.tasks || []).filter(task => task.kind === "import" && ["queued", "running", "cancelling"].includes(task.status)).length;
      if (before && !after) loadLibrary();
    }, 800);
  } catch (_error) { /* Import status will be retried when the shelf is reopened. */ }
}

async function openBookEditor(bookId) {
  try {
    const book = await api(`/api/books/${bookId}`);
    state.editingBookId = bookId;
    $("#book-editor-form").reset();
    $("#book-editor-id").value = bookId;
    $("#book-editor-title").value = book.title;
    $("#book-editor-author").value = book.author || "";
    $("#book-editor-series").value = book.series || "";
    $("#book-editor-volume").value = book.volume || "";
    $("#book-editor-path").textContent = `data/${book.storage_folder}`;
    panelNotice("#book-editor-notice", "");
    $("#book-editor-dialog").showModal();
    $("#book-editor-title").focus();
  } catch (error) { toast(error.message, true); }
}

function closeBookEditor() {
  $("#book-editor-dialog").close();
  state.editingBookId = null;
}

async function submitBookEditor(event) {
  event.preventDefault();
  const bookId = state.editingBookId;
  if (!bookId) return;
  try {
    const book = await api(`/api/books/${bookId}`, { method: "PUT", body: JSON.stringify({ title: $("#book-editor-title").value.trim(), author: $("#book-editor-author").value.trim(), series: $("#book-editor-series").value.trim(), volume: $("#book-editor-volume").value.trim() }) });
    const cover = $("#book-editor-cover").files[0];
    if (cover) {
      const data = new FormData();
      data.append("file", cover);
      await api(`/api/books/${bookId}/cover`, { method: "PUT", body: data });
    }
    closeBookEditor();
    toast(book.moved ? `書籍を data/${book.new_path} へ移動しました。` : "書籍情報を更新しました。");
    const route = libraryRoute();
    if (route?.kind === "book" && state.libraryChapter) await navigateBookChapter(bookId, state.libraryChapter.chapter.id, { historyMode: "replace" });
    else await loadLibrary();
  } catch (error) { panelNotice("#book-editor-notice", error.message, true); }
}

async function deleteEditedBook() {
  const bookId = state.editingBookId;
  if (!bookId || !window.confirm("この本を書架とローカル保存から削除しますか？")) return;
  try {
    await api(`/api/books/${bookId}`, { method: "DELETE" });
    closeBookEditor();
    stopArticlePlayback();
    state.libraryBook = null;
    state.libraryChapter = null;
    history.replaceState({ view: "library" }, "", "#library");
    await loadLibrary({ forceHome: true });
    toast("書架から削除しました。");
  } catch (error) { panelNotice("#book-editor-notice", error.message, true); }
}

function currentRouteView() {
  if (location.hash.startsWith("#library")) return "library";
  const view = location.hash.slice(1);
  return ["daily", "reader", "bookmarks", "dictionary", "settings"].includes(view) ? view : "daily";
}

$("#import-form").addEventListener("submit", importUrl);
$("#dictionary-search-form").addEventListener("submit", submitDictionarySearch);
$("#dictionary-query").addEventListener("input", scheduleDictionarySearch);
$("#dictionary-query").addEventListener("focus", () => setDictionaryHistoryOpen(true));
$("#dictionary-query").addEventListener("keydown", event => {
  if (event.key === "Escape") setDictionaryHistoryOpen(false);
});
$("#dictionary-search-form").addEventListener("focusout", event => {
  if (!event.currentTarget.contains(event.relatedTarget)) setDictionaryHistoryOpen(false);
});
document.addEventListener("pointerdown", event => {
  if (!$("#dictionary-search-form").contains(event.target)) setDictionaryHistoryOpen(false);
  if (!$("#selection-lookup").contains(event.target)) hideSelectionLookup();
});
document.addEventListener("mouseup", handleSelectionLookup);
$("#selection-lookup-close").onclick = () => hideSelectionLookup({ clearSelection: true, restoreFocus: true });
$("#selection-lookup-more").onclick = () => openSelectionLookupInDictionary();
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("#selection-lookup").hidden) hideSelectionLookup({ clearSelection: true, restoreFocus: true });
});
document.addEventListener("scroll", event => {
  if (!$("#selection-lookup").contains(event.target)) requestAnimationFrame(repositionSelectionLookup);
}, true);
window.addEventListener("resize", () => requestAnimationFrame(repositionSelectionLookup));
$("#voice-editor-form").addEventListener("submit", submitVoiceEditor);
if ("speechSynthesis" in window) speechSynthesis.addEventListener("voiceschanged", () => {
  if (state.editingBrowserVoice) populateBrowserVoiceSelect();
});
$("#source-editor-form").addEventListener("submit", submitSourceEditor);
$("#book-editor-form").addEventListener("submit", submitBookEditor);
$("#close-book-editor").onclick = closeBookEditor;
$("#cancel-book-editor").onclick = closeBookEditor;
$("#delete-book").onclick = deleteEditedBook;
$("#book-editor-dialog").addEventListener("close", () => { state.editingBookId = null; });
$("#book-editor-dialog").addEventListener("click", event => { if (event.target === $("#book-editor-dialog")) closeBookEditor(); });
$("#add-books").onclick = () => $("#book-files").click();
$("#back-to-library").onclick = async () => {
  history.pushState({ view: "library" }, "", "#library");
  await loadLibrary({ forceHome: true });
};
$("#book-files").onchange = event => { uploadBooks(event.target.files); event.target.value = ""; };
$("#library-sort-setting").onchange = updateLibrarySettings;
$("#open-desktop-data").onclick = () => openDesktopFolder("data");
$("#open-desktop-logs").onclick = () => openDesktopFolder("logs");
$("#mobile-allow-cellular").onchange = updateMobileCellularSetting;
$("#mobile-sync-now").onclick = startMobileSync;
$("#mobile-save-deepseek").onclick = saveMobileDeepSeekKey;
$("#mobile-clear-deepseek").onclick = clearMobileDeepSeekKey;
$("#mobile-pair-form").onsubmit = saveMobileWindowsAddress;
$("#mobile-scan-windows").onclick = () => beginMobilePairing(true);
$("#device-sync-enabled").onchange = toggleDeviceSync;
$("#device-sync-copy-url").onclick = () => copyDeviceSyncValue("#device-sync-url");
$("#device-sync-copy-code").onclick = () => copyDeviceSyncValue("#device-sync-code");
$("#device-sync-qr").onerror = () => panelError("#device-sync-error", "二维码加载失败，可使用连接地址和配对码连接。");
$("#mobile-windows-code").oninput = event => event.target.removeAttribute("aria-invalid");
$("#mobile-windows-address").oninput = event => { event.target.dataset.dirty = "true"; event.target.removeAttribute("aria-invalid"); };
$("#mobile-clear-windows").onclick = clearMobileWindowsAddress;
$("#mobile-exact-alarm").onclick = requestMobileExactAlarm;
$("#generate-daily").onclick = generateDaily;
$("#cancel-daily").onclick = () => stopDailyGeneration().catch(() => { });
$("#refresh-storage").onclick = refreshStorage;
$("#add-voice").onclick = () => openVoiceDialog();
$("#add-source").onclick = () => openSourceDialog();
$("#close-voice-dialog").onclick = closeVoiceDialog;
$("#cancel-voice-dialog").onclick = closeVoiceDialog;
$("#native-speech-settings").onclick = () => window.FujimiMobile?.openSpeechSettings();
$("#settings-system-speech").onclick = () => window.FujimiMobile?.openSpeechSettings();
$("#voice-dialog").addEventListener("close", () => { state.editingVoiceId = null; });
$("#voice-dialog").addEventListener("click", event => { if (event.target === $("#voice-dialog")) closeVoiceDialog(); });
$("#close-source-dialog").onclick = closeSourceDialog;
$("#cancel-source-dialog").onclick = closeSourceDialog;
$("#source-dialog").addEventListener("close", () => { state.editingSourceId = null; });
$("#source-dialog").addEventListener("click", event => { if (event.target === $("#source-dialog")) closeSourceDialog(); });
$("#daily-target-count").oninput = scheduleDailyContentUpdate;
document.addEventListener("copy", copyWithoutRuby);
document.querySelectorAll("#daily-mode button").forEach(button => { button.onclick = async () => { selectDailyMode(button.dataset.mode); await updateDailySettings(); }; });
$("#daily-update-time").onchange = updateDailySettings;
document.querySelectorAll("#voice-source-mode button").forEach(button => { button.onclick = () => setVoiceSourceMode(button.dataset.sourceMode); });
document.querySelectorAll(".nav-button").forEach(button => { button.onclick = () => showView(button.dataset.view); });
const mobileNavToggle = $("#mobile-nav-toggle");
const mobileNavClose = $("#mobile-nav-close");
const mobileNavScrim = $("#mobile-nav-scrim");
if (mobileNavToggle) mobileNavToggle.onclick = () => setMobileNavOpen(true);
if (mobileNavClose) mobileNavClose.onclick = () => setMobileNavOpen(false);
if (mobileNavScrim) mobileNavScrim.onclick = () => setMobileNavOpen(false);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") setMobileNavOpen(false);
});
window.addEventListener("resize", syncMobileNavigationLayout);
const mobileMoreButton = $("#mobile-more-button");
const mobileMoreMenu = $("#mobile-more-menu");
if (mobileMoreButton && mobileMoreMenu) {
  mobileMoreButton.onclick = () => {
    mobileMoreMenu.hidden = !mobileMoreMenu.hidden;
    mobileMoreButton.setAttribute("aria-expanded", String(!mobileMoreMenu.hidden));
  };
  mobileMoreMenu.querySelectorAll(".nav-button").forEach(button => {
    button.onclick = () => {
      mobileMoreMenu.hidden = true;
      mobileMoreButton.setAttribute("aria-expanded", "false");
      showView(button.dataset.view);
    };
  });
}
window.addEventListener("popstate", event => {
  showView(currentRouteView(), { historyMode: "none", resetReader: false });
});
const initialView = currentRouteView();
initializeSettingsLayout();
syncMobileNavigationLayout();
finishMobileAppBoot();
loadDailySettings();
loadLibrarySettings();
initializeBrowserVoice();
showView(initialView, { historyMode: "replace", resetReader: false });

;
/* Browser initialization and accessible navigation. */
(() => {
  const media = window.matchMedia('(max-width: 900px)');
  media.addEventListener('change', () => {
    document.documentElement.dataset.mobileApp = String(media.matches);
    syncMobileNavigationLayout();
    finishMobileAppBoot();
    if (state.currentView === 'settings') { loadVoices(); loadNewsSources(); }
  });
  document.documentElement.classList.remove('mobile-app-booting');
  const textDialog = document.querySelector('#web-text-dialog');
  const textDialogTrigger = document.querySelector('#open-web-text-dialog');
  const textForm = document.querySelector('#web-text-form');
  const closeTextDialog = () => { if (textDialog.open) textDialog.close(); };
  textDialogTrigger.onclick = () => {
    textDialogTrigger.setAttribute('aria-expanded', 'true');
    textDialog.showModal();
    requestAnimationFrame(() => textForm.querySelector('[name="title"]').focus());
    loadExamples();
    loadExampleVoices();
  };
  document.querySelector('#close-web-text-dialog').onclick = closeTextDialog;
  document.querySelector('#cancel-web-text-dialog').onclick = closeTextDialog;
  textDialog.addEventListener('close', () => {
    closeExampleMenu();
    textDialogTrigger.setAttribute('aria-expanded', 'false');
    textDialogTrigger.focus({ preventScroll: true });
  });
  const textExampleTrigger = textDialog.querySelector('#web-example-trigger');
  const textExampleOptions = textDialog.querySelector('#web-example-options');
  const addExampleButton = textDialog.querySelector('#web-example-add');
  const exampleStorageError = textDialog.querySelector('#web-example-storage-error');
  const exampleEditor = document.querySelector('#web-example-editor');
  const exampleForm = document.querySelector('#web-example-form');
  const exampleEditorError = exampleEditor.querySelector('[role="alert"]');
  const exampleTitle = exampleForm.querySelector('[name="title"]');
  const exampleText = exampleForm.querySelector('[name="text"]');
  const exampleVoiceSelect = exampleForm.querySelector('#web-example-voice');
  const articleVoiceSelect = textForm.querySelector('#web-text-voice');
  const articleTitle = textForm.querySelector('[name="title"]');
  const articleText = textForm.querySelector('[name="text"]');
  const articleExampleId = textForm.querySelector('[name="example_id"]');
  const detachExample = () => { articleExampleId.value = ''; };
  articleTitle.addEventListener('input', detachExample);
  articleText.addEventListener('input', detachExample);
  const articleVoiceMode = textForm.querySelector('[name="voice_mode"]');
  const articleVoiceId = textForm.querySelector('[name="voice_id"]');
  const articleBrowserVoiceName = textForm.querySelector('[name="browser_voice_name"]');
  const exampleSavedToast = textDialog.querySelector('#web-example-save-toast');
  let exampleSavedToastTimer = null;
  let examples = [];
  let voiceLoadSequence = 0;
  let defaultVoiceChoice = '';
  let browserVoiceChoice = '';
  let examplesLoadPromise = null;
  let focusArticleAfterSave = false;
  const showExampleSavedToast = () => {
    if (!exampleSavedToast) return;
    if (exampleSavedToastTimer) clearTimeout(exampleSavedToastTimer);
    exampleSavedToast.hidden = false;
    exampleSavedToast.classList.remove('is-leaving');
    requestAnimationFrame(() => exampleSavedToast.classList.add('is-visible'));
    exampleSavedToastTimer = setTimeout(() => {
      exampleSavedToast.classList.add('is-leaving');
      setTimeout(() => {
        exampleSavedToast.hidden = true;
        exampleSavedToast.classList.remove('is-visible', 'is-leaving');
      }, 220);
    }, 2600);
  };
  const closeExampleMenu = () => {
    textExampleOptions.hidden = true;
    textExampleTrigger.setAttribute('aria-expanded', 'false');
  };
  const choiceForExample = item => item.voice_mode === 'browser' && item.browser_voice_name
    ? `browser:${encodeURIComponent(item.browser_voice_name)}`
    : item.voice_mode === 'voice' && item.voice_id ? `voice:${item.voice_id}` : (item.voice_mode || 'inherit');
  const setArticleVoice = choice => {
    const [mode, raw] = String(choice || 'inherit').split(':', 2);
    articleVoiceMode.value = mode === 'browser' || mode === 'voice' || mode === 'none' ? mode : 'inherit';
    articleVoiceId.value = mode === 'voice' ? raw || '' : '';
    articleBrowserVoiceName.value = mode === 'browser' ? decodeURIComponent(raw || '') : '';
  };
  const ensureVoiceOption = (select, value, label) => {
    if ([...select.options].some(option => option.value === value)) return;
    select.add(new Option(label, value));
  };
  const fillExample = example => {
    articleExampleId.value = example.id;
    articleTitle.value = example.title;
    articleText.value = example.text;
    const savedChoice = choiceForExample(example);
    const choice = savedChoice === 'inherit' ? defaultVoiceChoice || articleVoiceSelect.value
      : savedChoice === 'browser' ? browserVoiceChoice || defaultVoiceChoice : savedChoice;
    if (choice) {
      ensureVoiceOption(articleVoiceSelect, choice, '已保存的声线（当前不可用）');
      articleVoiceSelect.value = choice;
      setArticleVoice(choice);
    }
    closeExampleMenu();
    articleText.focus();
  };
  const renderExamples = () => {
    textExampleOptions.querySelectorAll('[data-example-id]').forEach(button => button.remove());
    examples.forEach(example => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.exampleId = example.id;
      button.textContent = example.title;
      button.title = example.title;
      button.onclick = () => fillExample(example);
      addExampleButton.before(button);
    });
  };
  const loadExamples = () => {
    if (examplesLoadPromise) return examplesLoadPromise;
    examplesLoadPromise = (async () => {
      try {
        examples = await api('/api/examples');
        renderExamples();
        // Keep the legacy browser copy intact. The server backs it up before importing.
        const legacyKey = 'fujimi-reader-examples-v1';
        const markerKey = 'fujimi-reader-examples-file-migrated-v1';
        const raw = localStorage.getItem(legacyKey);
        if (raw && raw !== localStorage.getItem(markerKey)) {
          examples = await api('/api/examples/migrate', { method: 'POST', body: JSON.stringify({ examples: JSON.parse(raw) }) });
          renderExamples();
          localStorage.setItem(markerKey, raw);
        }
        exampleStorageError.hidden = true;
      } catch (error) {
        exampleStorageError.textContent = `示例读取或旧数据迁移失败：${error.message}；旧数据已保留。`;
        exampleStorageError.hidden = false;
      }
    })().finally(() => { examplesLoadPromise = null; });
    return examplesLoadPromise;
  };
  const loadExampleVoices = async () => {
    const sequence = ++voiceLoadSequence;
    try {
      const [voices, modeSettings] = await Promise.all([api('/api/settings/voices'), api('/api/settings/voice-mode')]);
      applyBrowserVoiceSettings(modeSettings);
      try {
        const catalog = await api('/api/browser-voices');
        state.browserVoices = Array.isArray(catalog) ? catalog : [];
      } catch (_error) { state.browserVoices = []; }
      if (!localBrowserVoice(state.browserVoiceName)) await waitForJapaneseBrowserVoice();
      if (sequence !== voiceLoadSequence) return;
      const browserName = localBrowserVoice(state.browserVoiceName)?.id
        || preferredJapaneseBrowserVoice()?.name || state.browserVoiceName || '';
      const defaults = exampleVoiceChoices(voices, modeSettings, browserName, 'inherit');
      defaultVoiceChoice = defaults.choice;
      browserVoiceChoice = browserName ? `browser:${encodeURIComponent(browserName)}` : '';
      for (const select of [articleVoiceSelect, exampleVoiceSelect]) {
        const { options, choice } = exampleVoiceChoices(voices, modeSettings, browserName, select.value);
        select.replaceChildren(...options.map(option => new Option(option.label, option.value)));
        if (choice && !options.some(option => option.value === choice)) {
          ensureVoiceOption(select, choice, '已保存的声线（当前不可用）');
        }
        select.value = choice;
        if (select === articleVoiceSelect) setArticleVoice(choice);
      }
    } catch (error) {
      exampleStorageError.textContent = `声线读取失败：${error.message}`;
      exampleStorageError.hidden = false;
    }
  };
  loadExamples();
  loadExampleVoices();
  textDialog.addEventListener('click', event => {
    if (event.target === textDialog) {
      closeTextDialog();
      return;
    }
    if (!event.target.closest('.web-example-menu')) closeExampleMenu();
  });
  textDialog.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || textExampleOptions.hidden) return;
    event.preventDefault();
    closeExampleMenu();
    textExampleTrigger.focus();
  });
  textExampleTrigger.onclick = () => {
    const expanded = textExampleTrigger.getAttribute('aria-expanded') === 'true';
    textExampleOptions.hidden = expanded;
    textExampleTrigger.setAttribute('aria-expanded', String(!expanded));
    if (!expanded) loadExamples();
  };
  addExampleButton.onclick = () => {
    closeExampleMenu();
    exampleForm.reset();
    exampleTitle.value = articleTitle.value;
    exampleText.value = articleText.value;
    const choice = articleVoiceSelect.value || defaultVoiceChoice;
    if (choice) {
      ensureVoiceOption(exampleVoiceSelect, choice, '已保存的声线（当前不可用）');
      exampleVoiceSelect.value = choice;
    }
    exampleEditorError.hidden = true;
    exampleEditor.showModal();
    requestAnimationFrame(() => exampleTitle.focus());
  };
  const closeExampleEditor = () => { if (exampleEditor.open) exampleEditor.close(); };
  document.querySelector('#close-web-example-editor').onclick = closeExampleEditor;
  document.querySelector('#cancel-web-example-editor').onclick = closeExampleEditor;
  exampleEditor.addEventListener('close', () => {
    (focusArticleAfterSave ? articleText : textExampleTrigger).focus({ preventScroll: true });
    focusArticleAfterSave = false;
  });
  exampleForm.onsubmit = async event => {
    event.preventDefault();
    const title = exampleTitle.value.trim();
    const text = exampleText.value.trim();
    const showError = message => {
      exampleEditorError.textContent = message;
      exampleEditorError.hidden = false;
    };
    if (!title || !text) { showError('请填写标题和日文正文。'); return; }
    const saveButton = exampleForm.querySelector('[type="submit"]');
    if (saveButton.disabled) return;
    saveButton.disabled = true;
    exampleEditorError.hidden = true;
    const [mode, raw] = String(exampleVoiceSelect.value || 'inherit').split(':', 2);
    const payload = { title, text, voice_mode: mode === 'browser' || mode === 'voice' || mode === 'none' ? mode : 'inherit', voice_id: mode === 'voice' ? Number(raw) : null, browser_voice_name: mode === 'browser' ? decodeURIComponent(raw || '') : '' };
    try {
      const saved = await api('/api/examples', { method: 'POST', body: JSON.stringify(payload) });
      examples = [...examples.filter(item => item.title !== saved.title), saved];
      renderExamples();
      fillExample(saved);
      focusArticleAfterSave = true;
      closeExampleEditor();
      showExampleSavedToast();
    } catch (error) {
      showError(error.message || '示例保存失败。');
    } finally {
      saveButton.disabled = false;
    }
  };
  articleVoiceSelect.onchange = () => setArticleVoice(articleVoiceSelect.value);
  textForm.addEventListener('reset', closeExampleMenu);
  textForm.onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('[type="submit"]');
    const error = form.querySelector('[role="alert"]');
    error.hidden = true;
    button.disabled = true;
    button.textContent = '正在保存…';
    try {
      const values = new FormData(form);
      const article = await api('/api/articles/text', {method: 'POST', body: JSON.stringify({
        title: values.get('title'),
        text: values.get('text'),
        example_id: values.get('example_id') || '',
        voice_mode: values.get('voice_mode') || 'inherit',
        voice_id: values.get('voice_id') ? Number(values.get('voice_id')) : null,
        browser_voice_name: values.get('browser_voice_name') || '',
      })});
      closeTextDialog();
      openArticle(article, document.querySelector('#reader-result'));
      toast('已保存，可选词查词或开始朗读。');
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = '保存并阅读';
    }
  };
  const addVoice = document.querySelector('#add-voice');
  addVoice.disabled = !window.FujimiMobile;
  addVoice.title = window.FujimiMobile ? '选择日语声线' : '正在检查 Irodori 服务…';
  document.querySelector('.refresh-panel .status-badge').textContent = 'FILES → INDEX';
  api('/api/health').then(health => {
    addVoice.disabled = !window.FujimiMobile && !health.tts_details?.enabled;
    addVoice.title = window.FujimiMobile ? '选择日语声线' : health.tts_details?.enabled ? '添加参考音频声线' : 'Irodori 尚未启用。';
  }).catch(() => {});

  // Trap keyboard focus in the mobile navigation drawer and restore it on close.
  document.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || document.documentElement.dataset.mobileNavOpen !== 'true') return;
    const items = [...document.querySelectorAll('#primary-sidebar button')].filter(el => el.offsetParent !== null);
    if (!items.length) return;
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
  });
})();
