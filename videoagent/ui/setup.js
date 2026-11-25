/* 🧰 Cài đặt công cụ — trạng thái mọi công cụ NGOÀI app (Node, Python + gói, ffmpeg, Claude Code, Codex, capcut-cli, skill
   TVC, Remotion, CapCut, Claude in Chrome…), cài / cập nhật online (winget / npm / pip) theo hàng đợi nền có nhật ký, cài
   skill từ file .skill, mở đăng nhập, xuất báo cáo cho người hỗ trợ. Helper của app.js: $, api, esc, toast, state,
   openSettings. Mở khoá quản trị: window.requireAdmin. */
(() => {
  'use strict';

  const S = { st: null, loading: false, poll: null, showLog: false, report: '', hinted: false };
  const root = () => $('#setupBody');
  const ICON = { ok: '✓', missing: '✗', old: '⚠', login: '🔑', unknown: '?' };
  const GROUP_IC = { base: '🧱', cli: '⌨', tvc: '🎬', extra: '➕' };

  async function call(name, ...args) {
    try {
      const res = await api(name, ...args);
      if (res && res.ok === false && res.locked) {
        return (await window.requireAdmin('cài đặt công cụ')) ? call(name, ...args) : null;
      }
      if (!res || res.ok === false) { toast((res && res.error) || 'Lỗi', 'error'); return null; }
      return res;
    } catch (err) { toast(String(err), 'error'); return null; }
  }

  async function show() {
    const r = await call('setup_state');
    if (r) S.st = r.state;
    render();
    if (!S.st || !S.st.checked) check();
    watch();
  }

  async function check(keys) {
    S.loading = true; render();
    const r = await call('setup_check', keys || null);
    S.loading = false;
    if (r) S.st = r.state;
    render(); badge();
  }

  /* ---------------------------------------------------------------- vẽ */
  function summaryHtml() {
    const s = (S.st && S.st.summary) || { ready: 0, need: 0, missing: 0, tvc_missing: [], auto: [] };
    const checked = !!(S.st && S.st.checked);
    const pct = s.need ? Math.round((s.ready / s.need) * 100) : 0;
    const job = (S.st && S.st.job) || {};
    const tvcOk = checked && !s.tvc_missing.length;
    return `<div class="stp-sum">
      <div class="stp-ring ${checked && !s.missing ? 'full' : ''}" style="--p:${checked ? pct : 0}"><b>${checked ? s.ready : '…'}<small>/${s.need || ''}</small></b></div>
      <div class="stp-sum-t"><h3>${!checked ? 'Đang kiểm tra máy này…' : s.missing ? `Còn thiếu ${s.missing} công cụ cần thiết` : 'Máy này đã đủ công cụ cần thiết'}</h3>
        <div class="stp-chips">
          <span class="stp-chip ${tvcOk ? 'ok' : checked ? 'bad' : ''}">🎬 Trợ lý TVC: ${tvcOk ? 'sẵn sàng' : checked ? `thiếu ${s.tvc_missing.length}` : '…'}</span>
          ${s.auto.length ? `<span class="stp-chip">⬇ ${s.auto.length} mục cài tự động được</span>` : ''}
          ${job.running ? '<span class="stp-chip run"><i class="stp-spin"></i> Đang cài…</span>' : ''}</div>
        ${s.tvc_missing.length ? `<small class="muted">Thiếu cho Trợ lý TVC: ${s.tvc_missing.map(esc).join(' · ')}</small>` : ''}</div>
      <div class="stp-acts">
        <button class="btn ghost sm" type="button" data-check ${S.loading || job.running ? 'disabled' : ''}>${S.loading ? '<i class="stp-spin"></i> Đang kiểm tra' : '↻ Kiểm tra lại'}</button>
        <button class="btn ghost sm" type="button" data-report ${checked ? '' : 'disabled'}>📋 Xuất báo cáo</button>
        <button class="btn primary sm" type="button" data-all ${!s.auto.length || job.running ? 'disabled' : ''}>⬇ Cài tất cả còn thiếu${s.auto.length ? ` (${s.auto.length})` : ''}</button></div></div>`;
  }

  function rowHtml(r, job) {
    const busy = job.running;
    const current = job.current === r.key;
    const queued = (job.queue || []).some(x => x.key === r.key);
    const acts = [];
    if (r.state === 'login' && r.login) acts.push(`<button class="btn primary sm" type="button" data-login="${esc(r.key)}">🔑 Đăng nhập</button>`);
    if (r.skill && r.bundle) {  // skill có trong gói cài: cài / cập nhật từ gói (không cần mạng); file .skill để cài bản khác
      if (r.state === 'missing') acts.push(`<button class="btn primary sm" type="button" data-install="${esc(r.key)}" ${busy ? 'disabled' : ''}>📦 Cài từ gói</button>`);
      if (r.state === 'ok' && r.bundle_diff) acts.push(`<button class="btn ghost sm" type="button" data-update="${esc(r.key)}" ${busy ? 'disabled' : ''} title="Thay bằng bản trong gói cài (bản đang có được đổi tên .bak-…, không xoá)">⟳ Cập nhật từ gói</button>`);
      acts.push(`<button class="btn ghost sm" type="button" data-skill title="Cài bản khác từ file .skill">📁 Từ file</button>`);
    } else {
      if (r.skill) acts.push(`<button class="btn ${r.state === 'ok' ? 'ghost' : 'primary'} sm" type="button" data-skill>${r.state === 'ok' ? '⟳ Cài lại từ file' : '📦 Chọn file .skill'}</button>`);
      if (r.can_install && (r.state === 'missing' || r.state === 'old')) acts.push(`<button class="btn primary sm" type="button" data-install="${esc(r.key)}" ${busy ? 'disabled' : ''}>⬇ ${r.state === 'old' ? 'Nâng cấp' : 'Cài'}</button>`);
      if (r.can_update && r.state === 'ok') acts.push(`<button class="btn ghost sm" type="button" data-update="${esc(r.key)}" ${busy ? 'disabled' : ''} title="Cập nhật lên bản mới nhất">⟳</button>`);
    }
    if (r.open && r.state !== 'ok') acts.push(`<button class="btn ghost sm" type="button" data-open="${esc(r.open)}">Mở cài đặt</button>`);
    if (r.url && r.state !== 'ok') acts.push(`<a class="btn ghost sm" href="${esc(r.url)}" title="Trang tải / hướng dẫn">Hướng dẫn ↗</a>`);
    const st = current ? 'run' : r.state;
    return `<div class="stp-row ${st}" data-row="${esc(r.key)}">
      <span class="stp-st ${st}" title="${esc(r.state_label || '')}">${current ? '<i class="stp-spin"></i>' : ICON[r.state] || '?'}</span>
      <div class="stp-main"><div class="stp-name"><b>${esc(r.name)}</b>${r.need ? '' : '<span class="stp-opt">tuỳ chọn</span>'}
          ${r.version ? `<span class="stp-ver">${esc(r.version)}</span>` : ''}${queued ? '<span class="stp-opt">trong hàng đợi</span>' : ''}</div>
        <div class="stp-meta">${(r.used || []).map(u => `<span>${esc(u)}</span>`).join('')}</div>
        ${r.detail || (r.state !== 'ok' && r.path) ? `<small class="stp-detail">${esc(r.detail || '')}${r.state !== 'ok' && r.path ? ` · ${esc(r.path)}` : ''}</small>` : ''}</div>
      <span class="stp-label ${st}">${esc(current ? 'Đang cài…' : r.state_label || '')}</span>
      <div class="stp-row-acts">${acts.join('')}</div></div>`;
  }

  function groupsHtml() {
    const st = S.st;
    if (!st) return '';
    const job = st.job || {};
    return Object.entries(st.groups).map(([g, label]) => {
      const rows = st.tools.filter(r => r.group === g);
      const ok = rows.filter(r => r.state === 'ok').length;
      return `<section class="stp-group"><header><span>${GROUP_IC[g] || ''}</span><h4>${esc(label)}</h4><small class="muted">${st.checked ? `${ok}/${rows.length} sẵn sàng` : ''}</small></header>
        ${rows.map(r => rowHtml(r, job)).join('')}</section>`;
    }).join('');
  }

  function jobHtml() {
    const job = (S.st && S.st.job) || {};
    if (!job.running && !(job.done || []).length) return '';
    const total = (job.done || []).length + (job.queue || []).length + (job.running && job.current ? 1 : 0);
    const done = (job.done || []).length;
    const bad = (job.done || []).filter(d => !d.ok);
    return `<section class="stp-job ${job.running ? 'run' : bad.length ? 'bad' : 'ok'}">
      <header><b>${job.running ? '<i class="stp-spin"></i> Đang cài' : bad.length ? `⚠ Xong, ${bad.length} mục lỗi` : '✓ Cài xong'}</b>
        <small class="muted">${done}/${total} mục</small><span class="stp-sp"></span>
        <button class="btn ghost sm" type="button" data-log>${S.showLog ? 'Ẩn nhật ký' : 'Xem nhật ký'}</button>
        ${job.running ? '<button class="btn ghost sm stp-stop" type="button" data-cancel>⏹ Dừng</button>' : ''}</header>
      <div class="stp-bar"><i style="width:${total ? Math.round((done / total) * 100) : 0}%"></i></div>
      ${bad.length ? `<ul class="stp-errs">${bad.map(d => `<li><b>${esc(d.name)}</b>: ${esc(d.error)}</li>`).join('')}</ul>` : ''}
      ${S.showLog ? `<pre class="stp-log" data-logbox>${esc((job.log || []).join('\n'))}</pre>` : ''}</section>`;
  }

  function render() {
    const el = root();
    if (!el) return;
    const old = el.querySelector('[data-logbox]');
    const atBottom = !old || old.scrollHeight - old.scrollTop - old.clientHeight < 40;
    const scroll = el.querySelector('.stp') ? el.querySelector('.stp').scrollTop : 0;
    el.innerHTML = `<div class="stp">
      <div class="stp-head"><span class="stp-logo">🧰</span><div><h2>Cài đặt công cụ</h2>
        <small class="muted">Công cụ ngoài app mà các màn cần trên máy này — cài online bằng winget / npm / pip (quyền người dùng thường)</small></div></div>
      ${summaryHtml()}${jobHtml()}
      <div class="stp-groups">${groupsHtml()}</div>
      ${S.report ? `<div class="stp-modal" data-close-report><div class="stp-modal-box"><header><b>📋 Báo cáo tình trạng máy</b><span class="stp-sp"></span>
          <button class="btn primary sm" type="button" data-copy>Chép</button><button class="btn ghost sm" type="button" data-close-report>Đóng</button></header>
        <small class="muted">Gửi cho người hỗ trợ. Không có token / cookie; thư mục người dùng rút gọn thành ~.</small>
        <textarea readonly data-report-text>${esc(S.report)}</textarea></div></div>` : ''}</div>`;
    el.querySelector('.stp').scrollTop = scroll;
    const log = el.querySelector('[data-logbox]');
    if (log && atBottom) log.scrollTop = log.scrollHeight;
    bind();
  }

  function badge() {
    const b = $('#sbSetupCount');
    const n = S.st && S.st.checked ? S.st.summary.missing : 0;
    if (!b) return;
    b.textContent = n;
    b.classList.toggle('hidden', !n);
    if (n && !S.hinted && state.view !== 'setup') {  // mở app trên máy thiếu công cụ → nhắc 1 lần
      S.hinted = true;
      toast(`Máy này còn thiếu ${n} công cụ cần thiết — mở 🧰 Cài đặt công cụ để cài`);
    }
  }

  /* ---------------------------------------------------------------- thao tác */
  async function install(keys, action) {
    const names = S.st.tools.filter(r => keys.includes(r.key)).map(r => `• ${r.name}`);
    const verb = action === 'update' ? 'Cập nhật' : 'Cài';
    if (!confirm(`${verb} ${names.length} mục sau trên máy này?\n(công cụ: tải bằng winget / npm / pip · skill: chép từ gói cài, bản cũ giữ lại .bak)\n\n${names.join('\n')}`)) return;
    const r = await call('setup_install', keys, action);
    if (r) { S.st = r.state; S.showLog = true; render(); watch(); }
  }

  function watch() {  // hàng đợi đang chạy → hỏi trạng thái mỗi giây (sự kiện setup_changed cũng vẽ lại)
    clearInterval(S.poll);
    if (!S.st || !S.st.job.running) return;
    S.poll = setInterval(async () => {
      const r = await api('setup_state').catch(() => null);
      if (!r || !r.ok) return;
      S.st = r.state;
      if (state.view === 'setup') render();
      if (!S.st.job.running) {
        clearInterval(S.poll);
        badge();
        const bad = S.st.job.done.some(d => !d.ok);
        toast(bad ? 'Cài xong, có mục lỗi — xem nhật ký' : 'Cài xong', bad ? 'error' : 'ok');
      }
    }, 1000);
  }

  function bind() {
    const el = root();
    const on = (sel, fn) => el.querySelectorAll(sel).forEach(b => { b.onclick = e => fn(b, e); });
    on('[data-check]', () => check());
    on('[data-all]', () => install(S.st.summary.auto, 'install'));
    on('[data-install]', b => install([b.dataset.install], 'install'));
    on('[data-update]', b => install([b.dataset.update], 'update'));
    on('[data-cancel]', async () => { const r = await call('setup_cancel'); if (r) { S.st = r.state; render(); } });
    on('[data-log]', () => { S.showLog = !S.showLog; render(); });
    on('[data-login]', async b => {
      const r = await call('setup_login', b.dataset.login);
      if (r) toast('Đã mở cửa sổ đăng nhập — làm xong bấm ↻ Kiểm tra lại', 'ok');
    });
    on('[data-skill]', async () => {
      const files = await api('pick_files', 'skill');
      if (!files || !files.length) return;
      const r = await call('setup_skill_install', files[0]);
      if (!r) return;
      S.st = r.state;
      toast(`Đã cài skill ${r.skill.name}${r.skill.backup ? ' (bản cũ giữ lại cạnh bên)' : ''}`, 'ok');
      render(); badge();
    });
    on('[data-open]', b => openSettings(b.dataset.open));
    on('[data-report]', async () => { const r = await call('setup_report'); if (r) { S.report = r.report; render(); } });
    on('[data-close-report]', (b, e) => { if (e.target === b) { S.report = ''; render(); } });
    on('[data-copy]', async () => {
      const ta = el.querySelector('[data-report-text]');
      try { await navigator.clipboard.writeText(ta.value); } catch { ta.select(); document.execCommand('copy'); }
      toast('Đã chép báo cáo', 'ok');
    });
  }

  async function update() {
    const r = await api('setup_state').catch(() => null);
    if (!r || !r.ok) return;
    S.st = r.state;
    badge();
    if (state.view === 'setup') render();
    if (S.st.job.running && !S.poll) watch();
  }

  window.SetupPage = { show, update };
})();
