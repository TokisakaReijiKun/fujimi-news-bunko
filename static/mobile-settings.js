/* Android settings use the existing native bridge; no preview state is stored here. */
(() => {
  'use strict';
  let session = null;

  function status() {
    try {
      const value = JSON.parse(window.FujimiMobile.mobileStatus());
      return value && typeof value === 'object' && !Array.isArray(value) ? value : { status_error: true };
    } catch { return { status_error: true }; }
  }

  function stop() {
    const previous = session; session = null;
    if (!previous) return;
    clearTimeout(previous.timer);
    for (const cleanup of previous.cleanup) cleanup();
  }

  function mount(body) {
    stop();
    const current = { body, timer: null, cleanup: [] }; session = current;
    return current;
  }

  function alive(current) {
    return session === current && current.body.isConnected && Boolean(current.body.closest('dialog')?.open);
  }

  function nativePairingPending() {
    return typeof mobileWindowsCheck !== 'undefined' && Boolean(mobileWindowsCheck);
  }

  function watch(current, update) {
    const tick = () => {
      if (!alive(current)) return;
      update(status());
      if (alive(current)) current.timer = setTimeout(tick, 700);
    };
    current.timer = setTimeout(tick, 0);
    const focus = () => {
      if (!alive(current)) return;
      clearTimeout(current.timer); tick();
    };
    window.addEventListener('focus', focus);
    current.cleanup.push(() => window.removeEventListener('focus', focus));
  }

  function renderSync(body, helpers) {
    const { node, button, icon, notify, onLibraryChanged } = helpers;
    const current = mount(body), initial = status();
    const layout = node('div', 'app-task');
    const badge = node('div', 'sync-status'), badgeLabel = node('span');
    badge.append(node('span', 'sync-status-dot'), badgeLabel);
    const feedback = node('p'); feedback.hidden = true;
    const addressPanel = node('div', 'sync-address'), addressCopy = node('div');
    const connectedAddress = node('strong');
    addressCopy.append(node('span', '', '接続先'), connectedAddress); addressPanel.append(addressCopy);

    const form = node('form', 'sheet-form'); form.noValidate = true;
    const scan = button('QRコードを読み取る', () => pair(true), 'primary'); scan.prepend(icon('scan'));
    const addressLabel = node('label', '', 'PCの接続先'), address = node('input', 'field');
    address.type = 'url'; address.required = true; address.autocomplete = 'off'; address.autocapitalize = 'off'; address.spellcheck = false;
    address.placeholder = 'PCに表示された接続先'; address.value = initial.server_url || ''; address.setAttribute('aria-label', 'PCの接続先');
    addressLabel.append(address);
    const codeLabel = node('label', '', '6桁のペアリングコード'), code = node('input', 'field');
    code.type = 'text'; code.inputMode = 'numeric'; code.pattern = '[0-9]{6}'; code.minLength = 6; code.maxLength = 6; code.required = true;
    code.autocomplete = 'one-time-code'; code.setAttribute('aria-label', '6桁のペアリングコード'); codeLabel.append(code);
    const connect = node('button', 'primary', '接続'); connect.type = 'submit';
    form.append(scan, addressLabel, codeLabel, connect);
    const progressPanel = node('section', 'app-task'), stage = node('p', 'app-task-title');
    const progressHeading = node('div', 'sync-section-title'), percentLabel = node('span');
    progressHeading.append(stage, percentLabel);
    const progress = node('progress'); progress.max = 100; progress.value = 0; progress.setAttribute('aria-label', '文庫の同期状況');
    const detail = node('p', 'app-task-detail'); progressPanel.append(progressHeading, progress, detail);
    const actions = node('div', 'app-task-actions');
    const sync = button('今すぐ同期', () => {
      try {
        if (!window.FujimiMobile?.syncNow()) {
          const latest = status();
          notify(latest.sync_detail || '同期を開始できません。接続を確認してください。', true);
          paint(latest); return;
        }
        notify('同期を開始しています。'); paint(status());
      } catch { notify('同期を開始できません。接続を確認してください。', true); }
    }, 'primary');
    const disconnect = button('接続を解除', () => {
      try {
        if (!window.FujimiMobile?.setServerUrl('')) throw new Error();
        const latest = status();
        if (latest.paired || latest.server_url) throw new Error();
        address.value = ''; code.value = ''; delete address.dataset.dirty;
        notify('接続を解除しました。'); paint(latest);
      } catch { notify('接続を解除できませんでした。', true); }
    }, 'pill-action');
    actions.append(sync, disconnect);
    layout.append(badge, addressPanel, form, progressPanel, actions);
    body.append(layout);
    let pairing = nativePairingPending();
    let nextConnectionProbe = 0;
    let previousSyncState = initial.sync_state || 'idle';
    const phase = event => {
      if (alive(current) && event.detail?.phase === 'tailscale') notify('Tailscaleを開きます。接続後に文庫へ戻ってください。');
    };
    window.addEventListener('fujimi-pairing-phase', phase);
    current.cleanup.push(() => window.removeEventListener('fujimi-pairing-phase', phase));

    address.addEventListener('input', () => { address.dataset.dirty = 'true'; address.setCustomValidity(''); });
    code.addEventListener('input', () => code.setCustomValidity(''));
    form.onsubmit = event => { event.preventDefault(); pair(false); };

    function pair(scanMode) {
      if (pairing || nativePairingPending()) return;
      if (!scanMode) {
        address.value = address.value.trim(); code.value = code.value.trim();
        address.setCustomValidity(''); code.setCustomValidity('');
        try {
          const url = new URL(address.value);
          if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) throw new Error();
        } catch { address.setCustomValidity('PCに表示された接続先を入力してください。'); }
        if (!/^\d{6}$/.test(code.value)) code.setCustomValidity('6桁のペアリングコードを入力してください。');
        if (!form.reportValidity()) return;
      }
      try {
        if (typeof beginMobilePairing !== 'function') throw new Error();
        pairing = true;
        notify(scanMode ? 'PCの文庫互联QRコードを読み取ってください。' : 'PCと接続しています。');
        beginMobilePairing(scanMode, address.value, code.value);
        paint(status());
      } catch { pairing = false; notify('接続を開始できませんでした。', true); paint(status()); }
    }

    function paint(value) {
      const pending = nativePairingPending();
      if (pairing && !pending) {
        pairing = false;
        if (value.paired) {
          code.value = ''; delete address.dataset.dirty;
          notify('ペアリングしました。同期を開始できます。');
        } else {
          const nativeResult = document.querySelector('#mobile-windows-result');
          notify(nativeResult?.textContent || value.connection_detail || '接続できませんでした。', true);
        }
      }
      pairing = pending || pairing;
      const active = ['queued', 'running'].includes(value.sync_state);
      const connected = value.paired && value.windows_status === 'ready';
      const checking = pairing || value.windows_status === 'checking';
      badge.dataset.state = value.status_error ? 'error' : connected ? 'paired' : checking ? 'waiting' : 'disabled';
      badgeLabel.textContent = value.status_error ? '接続状態を取得できません' : pairing ? 'ペアリング中' : checking ? '接続を確認中' : connected ? '接続済み' : '未接続';
      addressPanel.hidden = !value.paired; connectedAddress.textContent = value.server_url || '';
      form.hidden = Boolean(value.paired);
      if (!address.dataset.dirty && !pairing) address.value = value.server_url || '';
      address.disabled = code.disabled = connect.disabled = scan.disabled = pairing || Boolean(value.status_error);
      scan.setAttribute('aria-busy', String(pairing)); connect.setAttribute('aria-busy', String(pairing));
      actions.hidden = !value.paired;
      sync.disabled = !value.paired || (connected && value.sync_available === false) || active || pairing;
      sync.textContent = active ? '同期中' : '今すぐ同期'; sync.setAttribute('aria-busy', String(active));
      disconnect.disabled = pairing;
      const hasResult = active || ['completed', 'partial', 'failed'].includes(value.sync_state);
      progressPanel.hidden = !value.paired || !hasResult;
      const percent = Math.max(0, Math.min(100, Number(value.sync_progress) || 0));
      progress.value = percent; progress.setAttribute('aria-valuetext', Math.round(percent) + '%');
      percentLabel.textContent = Math.round(percent) + '%';
      const stageNames = { '读取文库清单': '文庫の内容を確認中', '接收 PC 文库': 'PCから受信中', '发送手机文库': 'PCへ送信中', '同步完成': '同期が完了しました', '部分同步完成': '一部の同期が完了しました', '同步失败': '同期できませんでした', '同步未完成': '同期は完了していません' };
      const labels = { completed: '同期が完了しました', partial: '一部の同期が完了しました', failed: '同期できませんでした', running: '同期中', queued: '同期を準備中' };
      stage.textContent = stageNames[value.sync_stage] || value.sync_stage || labels[value.sync_state] || '';
      detail.textContent = value.sync_detail || '';
      if (value.sync_state === 'failed') detail.setAttribute('role', 'alert'); else detail.setAttribute('role', 'status');
      if (['queued', 'running'].includes(previousSyncState) && ['completed', 'partial'].includes(value.sync_state)) {
        notify('');
        Promise.resolve(onLibraryChanged?.()).catch(() => { if (alive(current)) notify('文庫の表示を更新できませんでした。画面を開き直してください。', true); });
      }
      previousSyncState = value.sync_state || 'idle';
    }
    paint(initial); watch(current, value => {
      if (value.paired && !pairing && Date.now() >= nextConnectionProbe) {
        nextConnectionProbe = Date.now() + 3000;
        window.FujimiMobile?.refreshWindowsConnection?.();
      }
      paint(value);
    });
  }

  function renderServices(body, helpers) {
    const { node, button, notify } = helpers, current = mount(body), initial = status();
    const layout = node('div', 'app-task');
    const heading = node('div', 'sync-section-title'), configured = node('span');
    heading.append(node('h3', '', 'DeepSeek APIキー'), configured);
    const form = node('form', 'sheet-form'), label = node('label', '', 'APIキー');
    const input = node('input', 'field'); input.type = 'password'; input.autocomplete = 'new-password'; input.required = true; input.spellcheck = false; input.autocapitalize = 'off';
    input.placeholder = '新しいAPIキーを入力'; input.setAttribute('aria-label', 'DeepSeek APIキー'); label.append(input);
    const save = node('button', 'primary', '保存'); save.type = 'submit';
    const clear = button('保存済みのキーを削除', () => {
      if (!window.confirm('この端末のAPIキーを削除しますか？')) return;
      try {
        if (!window.FujimiMobile?.clearDeepSeekKey() || status().deepseek_configured) throw new Error();
        input.value = ''; notify('APIキーを削除しました。'); paint(status());
      } catch { notify('APIキーを削除できませんでした。', true); }
    }, 'text-button');
    const feedback = node('p'); feedback.hidden = true;
    form.append(label, save, clear);
    form.onsubmit = event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      save.disabled = true;
      try {
        if (!window.FujimiMobile?.setDeepSeekKey(input.value.trim()) || !status().deepseek_configured) throw new Error();
        input.value = ''; input.removeAttribute('aria-invalid'); notify('この端末にAPIキーを保存しました。'); paint(status());
      } catch { input.setAttribute('aria-invalid', 'true'); notify('APIキーを保存できませんでした。入力を確認してください。', true); }
      finally { save.disabled = false; }
    };
    const networkHeading = node('div', 'sync-section-title'); networkHeading.append(node('h3', '', 'ネットワーク'));
    const cellularLabel = node('label', 'app-checkbox', 'モバイル通信を許可');
    const cellular = node('input'); cellular.type = 'checkbox'; cellular.checked = Boolean(initial.allow_cellular); cellularLabel.append(cellular);
    cellular.onchange = () => {
      const requested = cellular.checked;
      try {
        if (!window.FujimiMobile?.setAllowCellular(requested) || Boolean(status().allow_cellular) !== requested) throw new Error();
        notify(requested ? 'モバイル通信を許可しました。' : 'Wi-Fiなどの定額回線で通信します。');
      } catch { cellular.checked = Boolean(status().allow_cellular); notify('通信設定を保存できませんでした。', true); }
    };
    const alarmSection = node('section', 'app-task'), alarmHeading = node('div', 'sync-section-title'), alarmState = node('p', 'settings-info');
    alarmHeading.append(node('h3', '', '更新時刻'));
    const exactAlarm = button('正確な時刻での更新を許可', () => {
      try {
        if (!window.FujimiMobile?.requestExactAlarmPermission()) throw new Error();
        notify('システム設定で許可してください。');
      } catch { notify('システム設定を開けませんでした。', true); }
    }, 'pill-action');
    alarmSection.append(alarmHeading, alarmState, exactAlarm);
    layout.append(heading, form, networkHeading, cellularLabel, alarmSection); body.append(layout);
    current.cleanup.push(() => { input.value = ''; });
    function paint(value) {
      configured.textContent = value.status_error ? '取得できません' : value.deepseek_configured ? '設定済み' : '未設定';
      clear.hidden = !value.deepseek_configured;
      cellular.checked = Boolean(value.allow_cellular);
      save.disabled = cellular.disabled = Boolean(value.status_error);
      alarmSection.hidden = value.scheduler_available === false;
      exactAlarm.hidden = Boolean(value.exact_alarm);
      alarmState.textContent = value.alarm_error || (value.exact_alarm ? '指定した時刻に日刊を更新できます。' : 'システムの時間枠で日刊を更新します。');
    }
    paint(initial); watch(current, paint);
  }

  function renderMaintenance(body, helpers) {
    const { node } = helpers; mount(body);
    const value = status(), panel = node('div', 'app-task'), address = node('div', 'sync-address'), copy = node('div');
    copy.append(node('span', '', '文庫の保存先'), node('strong', '', value.data_path || '保存先を取得できません')); address.append(copy); panel.append(address);
    if (value.article_index_error) {
      const error = node('p', 'source-feedback', value.article_index_error); error.setAttribute('role', 'alert'); panel.append(error);
    }
    body.append(panel);
  }

  window.FujimiAppSettings = { status, renderSync, renderServices, renderMaintenance, stop };
})();
