/* Throwaway, isolated visual prototype. No production API or storage access. */
const names = { daily: '本日ノニュース', reader: '閲読室', bookmarks: '收藏', library: '書架', dictionary: '辞書', settings: '設置', article: '文章阅读', book: '书籍阅读', more: '导航展开' };
const phone = document.querySelector('#phone');
const main = document.querySelector('#main');
const drawer = document.querySelector('#drawer');
const scrim = document.querySelector('#scrim');
const more = document.querySelector('#more');
let lastFocus = null;
let demoRoute = 'daily';
function showDrawer(open) {
  if (open) lastFocus = document.activeElement;
  drawer.hidden = !open;
  scrim.hidden = !open;
  more.setAttribute('aria-expanded', String(open));
  main.inert = open;
  document.querySelector('#navigation').inert = open;
  document.querySelector('#appbar').inert = open;
  if (open) document.querySelector('#close-drawer').focus({ preventScroll: true });
  else if (lastFocus?.isConnected) lastFocus.focus({ preventScroll: true });
}
function render() {
  const requested = location.hash.slice(1) || new URLSearchParams(location.search).get('view') || 'daily';
  demoRoute = Object.hasOwn(names, requested) ? requested : 'daily';
  const contentRoute = demoRoute === 'more' ? 'daily' : demoRoute;
  showDrawer(false);
  main.replaceChildren(document.querySelector(`template#${contentRoute}`).content.cloneNode(true));
  phone.classList.toggle('reading', ['article', 'book'].includes(contentRoute));
  document.querySelectorAll('[data-route]').forEach(link => {
    if (link.dataset.route === contentRoute) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (['bookmarks', 'settings', 'more'].includes(demoRoute)) more.setAttribute('aria-current', 'page');
  else more.removeAttribute('aria-current');
  main.scrollTop = 0;
  document.title = `${names[demoRoute]} · 富士見新聞文庫设计稿`;
  if (demoRoute === 'more') showDrawer(true);
  else if (location.hash) main.focus({ preventScroll: true });
  requestAnimationFrame(() => requestAnimationFrame(reportLayout));
}
const messages = {
  history: ['历史日期', '这里预留现有历史日刊选择器的位置。本稿仅展示布局，未读取真实日刊。'],
  import: ['导入文章', '设计稿未连接新闻导入接口。正式版本会继续显示验证、翻译与媒体保存的真实进度。'],
  paste: ['粘贴正文', '此入口对应已有正文导入表单；本稿只呈现入口，不会保存文章。'],
  example: ['阅读室示例', '对应现有增加示例功能，本设计稿未写入示例库。'],
  book: ['EPUBを追加', '保留现有入口。Android 本机 EPUB 导入尚未接入，正式版本应显示不可用说明。'],
  speech: ['词典朗读', '此处展示朗读按钮位置。设计稿未合成或播放音频。'],
  voice: ['声の形', '正式界面继续使用现有声线选择流程。这里的七海为排版示意，不代表本机设置。'],
  generate: ['今すぐ生成', '本稿未启动日刊任务。正式版本继续使用真实任务状态和中止入口。'],
  pair: ['PC 協同', '本稿未请求配对或同步。正式流程仍为同一网络中配对后手动补齐文库。'],
  refresh: ['文庫刷新', '本稿不会读取或重建文库索引。'],
  origin: ['原站打开', '此文章为合成排版示意，没有对应新闻原站。'],
  audio: ['朗读设计示意', '这是播放器的视觉设计稿，未连接音频服务，未播放朗读。'],
  listen: ['听读', '此处保留现有听读模式入口。当前设计稿未连接音频服务。'],
  contents: ['目次', '上　先生と私\n中　両親と私\n下　先生と遺書\n\n本稿仅展示章节目录入口。']
};
more.addEventListener('click', () => showDrawer(true));
document.querySelector('#close-drawer').addEventListener('click', () => showDrawer(false));
scrim.addEventListener('click', () => showDrawer(false));
document.addEventListener('keydown', event => {
  if (drawer.hidden) return;
  if (event.key === 'Escape') showDrawer(false);
  if (event.key === 'Tab') {
    const controls = [...drawer.querySelectorAll('button,a')];
    const first = controls[0]; const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
document.addEventListener('click', event => {
  const target = event.target.closest('[data-dialog],.translation-toggle,.bookmark-toggle,.rate-toggle');
  if (!target) return;
  if (target.matches('[data-dialog]')) {
    const [title, copy] = messages[target.dataset.dialog];
    document.querySelector('#dialog-title').textContent = title;
    document.querySelector('#dialog-copy').textContent = copy;
    document.querySelector('#demo-dialog').showModal();
  } else if (target.matches('.translation-toggle')) {
    const active = target.getAttribute('aria-pressed') !== 'true';
    target.setAttribute('aria-pressed', String(active));
    document.querySelectorAll('.translation,.reading-subtitle').forEach(element => { element.hidden = !active; });
  } else if (target.matches('.bookmark-toggle')) {
    const active = target.getAttribute('aria-pressed') !== 'true';
    target.setAttribute('aria-pressed', String(active));
    target.setAttribute('aria-label', active ? '取消收藏文章（设计示意）' : '收藏文章（设计示意）');
  } else if (target.matches('.rate-toggle')) {
    const rates = ['1.0×', '1.25×', '1.5×'];
    target.textContent = rates[(rates.indexOf(target.textContent) + 1) % rates.length];
  }
});
document.addEventListener('submit', event => {
  if (event.target.id !== 'dictionary-form') return;
  event.preventDefault();
  const query = document.querySelector('#dictionary-query').value.trim();
  const matches = ['木漏れ日', 'こもれび', 'komorebi', '阳光'].includes(query);
  document.querySelector('.word-detail').hidden = !matches;
  document.querySelector('.result-summary').lastElementChild.textContent = matches ? '1 件' : '0 件 · 示例词条：木漏れ日';
});
function reportLayout() {
  let metrics = document.querySelector('#layout-metrics');
  if (!metrics) { metrics = document.createElement('script'); metrics.id = 'layout-metrics'; metrics.type = 'application/json'; document.body.append(metrics); }
  const visibleControls = [...main.querySelectorAll('button,a,input,select,summary')].filter(element => element.checkVisibility());
  const bounds = phone.getBoundingClientRect();
  metrics.textContent = JSON.stringify({ route: demoRoute, viewport: innerWidth, phoneWidth: bounds.width,
    documentWidth: document.documentElement.scrollWidth, mainWidth: main.clientWidth, mainScrollWidth: main.scrollWidth,
    overflow: visibleControls.filter(element => { const rect = element.getBoundingClientRect(); return rect.left < bounds.left - 1 || rect.right > bounds.right + 1; }).map(element => element.textContent.trim()),
    smallControls: visibleControls.filter(element => { const rect = element.getBoundingClientRect(); return (rect.width < 43 || rect.height < 43) && !element.closest('.daily-date,.reading-byline'); }).map(element => element.textContent.trim()),
    navigation: [...document.querySelectorAll('#navigation a')].map(element => element.hash),
    mocked: true });
}
window.addEventListener('hashchange', render);
window.addEventListener('resize', reportLayout);
document.fonts.ready.then(reportLayout);
render();
