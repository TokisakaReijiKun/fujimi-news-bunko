(() => {
  "use strict";

  const design = document.body.dataset.design || "a";
  const icon = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const icons = {
    voice: icon("<path d=\"M5 10v4m4-7v10m4-13v16m4-13v10m4-7v4\"/>") ,
    daily: icon("<rect x=\"4\" y=\"5\" width=\"16\" height=\"15\" rx=\"2\"/><path d=\"M8 3v4m8-4v4M4 10h16\"/>") ,
    library: icon("<path d=\"M4 5h7v15H4zM11 5h4v15h-4zM16 5l4-1 3 15-4 1z\"/>") ,
    translate: icon("<path d=\"M3 5h12M9 3v2m-3 3c1 5 5 7 9 8M13 5c0 6-4 9-9 11m10 5 4-10 4 10m-6-4h4\"/>") ,
    pc: icon("<rect x=\"3\" y=\"4\" width=\"17\" height=\"12\" rx=\"2\"/><path d=\"M8 20h8m-4-4v4\"/>") ,
    network: icon("<path d=\"M3 8a15 15 0 0 1 18 0M6 12a10 10 0 0 1 12 0m-9 4a5 5 0 0 1 6 0\"/><circle cx=\"12\" cy=\"20\" r=\"1\"/>") ,
    storage: icon("<path d=\"M20 11a8 8 0 0 0-14.8-3M4 5v4h4M4 13a8 8 0 0 0 14.8 3M20 19v-4h-4\"/>")
  };
  const pill = (text, muted = false) => `<span class="pill${muted ? " muted" : ""}">${text}</span>`;
  const button = (text, action = "", secondary = false, disabled = false) => `<button type="button" class="btn${secondary ? " secondary" : ""}"${action ? ` data-action="${action}"` : ""}${disabled ? " disabled" : ""}>${text}</button>`;
  const field = (label, content) => `<label class="field"><span>${label}</span>${content}</label>`;
  const details = (summary, body) => `<details class="details"><summary>${summary}</summary><div class="details-body">${body}</div></details>`;
  const panel = (id, number, title, description, status, body, extra = "") => `<section class="settings-panel" id="${id}"><div class="panel-heading"><div><span class="section-number">${number}</span><h2>${title}</h2><p>${description}</p></div>${status ? pill(status, status === "未配置" || status === "尚未刷新") : ""}</div>${body}${extra}</section>`;

  const voice = panel("voice", "01 / VOICE", "声の形", "选择文章、书籍与词典的即时朗读声线。", "使用中", `<div class="voice-row"><span class="voice-mark">あ</span><div><strong>系统日语声线（ja）</strong><small>Android · 当前设备实际可用</small></div><button class="icon-button" type="button" data-action="voices" aria-label="选择声线">›</button></div><div class="button-row">${button("选择声线", "voices")}${button("系统朗读设置", "native-settings", true)}</div>`, details("声线管理", "连接 PC 后才显示 PC 上实际可用的声线；不可用的声线会明确报错，不静默替换。"));
  const sources = ["NHKニュース", "朝日新聞", "読売新聞", "日本経済新聞", "産経新聞", "Yahoo!ニュース"];
  const sourceRows = sources.map((source) => `<label class="source-row"><span>${source}</span><input type="number" value="1" min="0" max="5" aria-label="${source} 最低配额"></label>`).join("");
  const daily = panel("daily", "02 / DAILY", "日刊設定", "统一管理每日数量、新闻来源与生成方式。", "6 个来源", `<div class="daily-grid"><div class="daily-target"><label for="daily-target">每日新闻目标数</label><input id="daily-target" value="10" inputmode="numeric"></div><div class="daily-stat"><span>有效来源</span><strong>6 <small>个来源</small></strong></div></div>${details("调整各来源最低配额", sourceRows)}<div class="mode-block"><span class="field-caption">生成方式</span><div class="segmented"><button type="button" disabled>自動更新</button><button type="button" aria-pressed="true">手動生成</button></div><p class="helper">Android 定时调度尚未接入，当前可手动生成。</p></div><div class="task-note"><span class="status-dot"></span><div><strong>当前没有任务</strong><p>日刊采集任务尚未开始</p></div></div>${button("今すぐ生成", "generate", false, true)}`);
  const library = panel("library", "03 / LIBRARY", "書架表示", "选择书架首页的书籍排列方式。", "本机规则", `<div class="field"><label for="library-sort">並び順</label><select id="library-sort"><option>最近読んだ順</option><option>シリーズ・巻順</option><option>最近追加した順</option></select></div><div class="info-note">${icons.library}<p>打开书籍时，有书签优先定位书签，否则恢复本机自动进度。</p></div>`);
  const deepseek = `<div class="subsection"><div class="subheading"><div><h3>DeepSeek</h3><p>翻译密钥</p></div>${pill("未配置", true)}</div>${field("API 密钥", '<input type="password" placeholder="输入新密钥" autocomplete="off" aria-describedby="deepseek-help">')}<div class="button-row">${button("保存密钥", "save-key")}</div><p class="helper" id="deepseek-help">密钥仅加密保存在此手机，不参与同步。</p></div>`;
  const sync = `<div class="subsection"><div class="subheading"><div><h3>PC 协同</h3><p>连接状态与同步进度分别显示。</p></div>${pill("未配置", true)}</div>${field("私有局域网或 VPN 地址", '<input id="pc-endpoint" type="url" placeholder="https://192.168.1.20:8429" inputmode="url" autocomplete="off">')}<div class="button-row">${button("检测地址", "check-pc", true)}</div><p class="helper">仅限私有网络，不得暴露到公网。</p><div class="sync-box"><div class="sync-heading"><strong>同步</strong><span>0%</span></div><progress value="0" max="100" aria-label="同步进度"></progress><p>协同同步尚未接入</p><dl class="sync-stats"><div><dt>上次同步</dt><dd>尚未完成</dd></div><div><dt>待提交</dt><dd>0</dd></div><div><dt>本地缓存</dt><dd>0 B</dd></div></dl>${button("立即同步", "sync", false, true)}</div></div>`;
  const network = `<div class="subsection"><div class="subheading"><div><h3>网络与定时</h3><p>联网偏好与实际权限。</p></div></div><label class="switch-row"><span><strong>允许蜂窝网络</strong><small>关闭时仅使用不按流量计费的网络</small></span><input type="checkbox" role="switch" aria-label="允许蜂窝网络"><span class="switch-track" aria-hidden="true"></span></label><div class="permission-row"><div><strong>日刊闹钟</strong><span>自动调度尚未接入</span></div>${button("精确定时", "permission", true)}</div>${details("CST 调度说明", "按 UTC+8 执行。关机期间错过的任务不补跑。")}</div>`;
  const mobile = panel("mobile", "04 / ANDROID", "Android 本地节点", "本机设置、PC 协同与网络权限。", "本机运行", `<div class="mobile-sections">${deepseek}${sync}${network}</div>`);
  const system = panel("system", "05 / APP", "应用信息", "版本与本机文庫位置。", "1.0.1", `<dl class="about-list"><div><dt>APP 版本</dt><dd>1.0.1</dd></div><div><dt>包名</dt><dd>jp.fujimi.newsbunko.next</dd></div></dl>${details("本机文庫路径", '<code>/data/user/0/jp.fujimi.newsbunko.next/files/data</code>')}`);
  const refresh = panel("refresh", "06 / STORAGE", "文庫刷新", "以文件为事实来源，重新整理 SQLite 索引。", "尚未刷新", `<div class="storage-row">${icons.storage}<div><strong>FILES → INDEX</strong><span>检查文件、备份异常记录并刷新索引。</span></div></div><div class="button-row">${button("存储を反映", "refresh")}</div>`);
  const toolbar = `<nav class="prototype-bar"><a href="index.html">‹ 方案总览</a><label><span>UI DEMO</span><select aria-label="切换设计方案" data-design-select><option value="quiet-editorial.html"${design === "a" ? " selected" : ""}>A · 原版精修</option><option value="command-center.html"${design === "b" ? " selected" : ""}>B · 紧凑分组</option><option value="library-shelf.html"${design === "c" ? " selected" : ""}>C · 纸张细节</option></select></label></nav>`;
  const header = `<header class="app-header"><div><p class="eyebrow">富士見新聞文庫 / PREFERENCES</p><h1>設定 <span>Preferences</span></h1><p class="header-copy">読む時間を、自分らしく整える。</p></div><span class="device-badge"><i></i>Android 本机</span></header>`;
  document.getElementById("app").innerHTML = `${toolbar}<main class="settings-app design-${design}">${header}<div class="settings-stack">${voice}${daily}${library}${mobile}${system}${refresh}</div><p class="demo-foot">UI 概念演示 · 保留原版纵向设置顺序与功能入口</p></main><div class="toast" role="status" aria-live="polite" hidden></div>`;

  const toast = document.querySelector(".toast"); let timer;
  const notify = (message) => { toast.textContent = message; toast.hidden = false; clearTimeout(timer); timer = setTimeout(() => { toast.hidden = true; }, 3000); };
  document.querySelector("[data-design-select]").addEventListener("change", (event) => { location.href = event.target.value; });
  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]"); if (!action) return;
    const type = action.dataset.action;
    if (type === "voices") notify("Demo：正式版打开声线选择列表。");
    if (type === "native-settings") notify("Demo：正式版打开 Android 系统朗读设置。");
    if (type === "generate") notify("当前 Android 日刊生成不可用。");
    if (type === "save-key") notify("Demo：密钥字段未存储或发送。");
    if (type === "check-pc") { const input = document.querySelector("#pc-endpoint"); if (!input.value.trim()) { input.focus(); notify("请先输入 PC 地址。"); } else { notify(input.value.startsWith("https://") ? "Demo：未发起实际连接检测。" : "请使用 HTTPS 私网地址。"); } }
    if (type === "sync") notify("当前 Android 协同尚未接入。");
    if (type === "permission") notify("Demo：正式版打开精确定时权限页面。");
    if (type === "refresh") notify("Demo：未执行文庫刷新或修改文件。");
  });
})();
