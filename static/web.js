/* Small browser adaptation layer; APK UI remains the source of truth. */
(() => {
  const media = window.matchMedia('(max-width: 900px)');
  media.addEventListener('change', () => {
    document.documentElement.dataset.mobileApp = String(media.matches);
    syncMobileNavigationLayout();
    finishMobileAppBoot();
    if (state.currentView === 'settings') { loadVoices(); loadNewsSources(); }
  });
  document.documentElement.classList.remove('mobile-app-booting');
  document.querySelector('#article-url').setAttribute('aria-label', '新闻文章网址');
  const workspace = document.querySelector('#reader-import-workspace');
  const panel = document.createElement('details');
  panel.className = 'web-text-import';
  panel.innerHTML = `<summary>本文を貼り付ける · 粘贴正文</summary>
    <form id="web-text-form">
      <label>标题<input name="title" required maxlength="500" autocomplete="off"></label>
      <label>日文正文<textarea name="text" required placeholder="ここに読みたい文章を貼り付けてください。"></textarea></label>
      <p class="web-runtime-note">自动添加假名并保存到本地。可选中正文中的词语查词，也可使用浏览器朗读。</p>
      <p class="web-import-error" role="alert" hidden></p>
      <div class="web-form-actions"><button type="submit">保存并阅读</button><button type="button" class="quiet web-example">填入示例</button></div>
    </form>`;
  workspace.append(panel);
  panel.querySelector('.web-example').onclick = () => {
    panel.querySelector('[name="title"]').value = '読書の時間（操作示例）';
    panel.querySelector('[name="text"]').value = '朝の静かな時間に、本を開きました。窓の外では、小さな鳥が歌っています。\n\n知らない言葉に出会ったら、辞書で調べてみましょう。一つの言葉から、新しい世界が広がります。\n\nこれは閲読室の使い方を確認するための例文です。実際のニュースではありません。';
  };
  panel.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('[type="submit"]');
    const error = form.querySelector('[role="alert"]');
    button.disabled = true;
    button.textContent = '正在保存…';
    error.hidden = true;
    try {
      const values = new FormData(form);
      const article = await api('/api/articles/text', {method: 'POST', body: JSON.stringify({title: values.get('title'), text: values.get('text')})});
      openArticle(article, document.querySelector('#reader-result'));
      panel.open = false;
      toast('已保存，可选词查词或开始朗读。');
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = '保存并阅读';
    }
  };
  const note = document.createElement('p');
  note.className = 'web-runtime-note';
  note.textContent = 'Web 本地版 · 词典与阅读可离线使用。日刊自动更新仅在本地服务运行期间执行。';
  document.querySelector('#settings-view .section-head').after(note);
  const addVoice = document.querySelector('#add-voice');
  addVoice.disabled = true;
  addVoice.title = 'Irodori 服务尚未接入；可修改下方浏览器声线。';
  const voiceHelp = document.createElement('p');
  voiceHelp.className = 'web-runtime-note';
  voiceHelp.textContent = '当前使用浏览器日语语音。Irodori 自定义声线尚未接入。';
  document.querySelector('.voice-overview').before(voiceHelp);
  document.querySelector('.refresh-panel .panel-heading p').textContent = '校验文章文件并重建新闻、收藏索引；同步书架，备份后清理已删除书籍目录的记录。不会删除现有文件。';
  document.querySelector('.refresh-panel .status-badge').textContent = 'FILES → INDEX';
  api('/api/health').then(health => {
    note.textContent += health.translation_configured ? ' 翻译已配置，处理时会发送正文到 DeepSeek。' : ' 翻译未配置，章节处理仅生成假名。';
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
