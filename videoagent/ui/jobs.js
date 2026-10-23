/* Tiến trình chung của hệ thống — nút ⏳ trên thanh tiêu đề (số tác vụ đang chạy / chờ), bấm để bật / tắt bảng gom mọi
   tác vụ của các màn: Tạo video, Tạo ảnh, Studio, Studio Muse AI, Chiến dịch, Workflow, Nhân vật & Layout, Seedance.
   Bấm tên nguồn → mở màn đó; ■ → dừng tác vụ. Dữ liệu: api system_progress (chỉ đọc bộ nhớ, gọi thường xuyên vẫn nhẹ). */
(() => {
  'use strict';
  const J = { open: false, data: null, timer: 0, tick: 0, pending: 0, filter: 'all', ready: false };
  const STATUS = { running: 'Đang chạy', queued: 'Đang chờ', done: 'Xong', failed: 'Lỗi', cancelled: 'Đã huỷ' };
  const btn = () => $('#jobsBtn');

  const clock = ms => {
    const s = Math.max(0, Math.floor(ms / 1000));
    return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
      : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  };
  const ago = ms => {
    const m = Math.round((Date.now() - ms) / 60000);
    return !ms ? '' : m < 1 ? 'vừa xong' : m < 60 ? `${m} phút trước` : `${Math.floor(m / 60)} giờ trước`;
  };

  async function refresh() {
    clearTimeout(J.pending); J.pending = 0;
    const res = await api('system_progress');
    if (!res || !res.ok) return;
    J.data = res;
    paintBadge();
    if (window.Notify) window.Notify.feed(res);  // thông báo tác vụ vừa xong (notify.js)
    if (J.open) paint();
  }
  // sự kiện backend đến dồn dập (log, tiến độ) → gom lại, tối đa ~1 lần / 0,7 giây
  const soon = () => { if (J.ready && !J.pending) J.pending = setTimeout(refresh, 700); };

  function paintBadge() {
    const d = J.data, n = d.running + d.queued;
    const b = btn();
    b.classList.toggle('busy', d.running > 0);
    const badge = $('#jobsCount');
    badge.textContent = n;
    badge.classList.toggle('hidden', !n);
    b.title = n ? `Tiến trình hệ thống — ${d.running} đang chạy · ${d.queued} đang chờ` : 'Tiến trình hệ thống — không có tác vụ nào đang chạy';
  }

  function row(i) {
    const live = i.status === 'running' || i.status === 'queued';
    const bar = i.status === 'running' && i.pct > 0;
    return `<div class="jb-row ${i.status}">
        <span class="jb-dot" title="${STATUS[i.status] || ''}"></span>
        <div class="jb-main">
          <div class="jb-top"><b title="${esc(i.title)}">${esc(i.title || '(không tên)')}</b>
            ${i.started && i.status === 'running' ? `<span class="jb-time mono" data-since="${i.started}">${clock(Date.now() - i.started)}</span>` : ''}
            ${!live && (i.finished || i.created) ? `<span class="jb-time">${ago(i.finished || i.created)}</span>` : ''}</div>
          ${bar ? `<div class="jb-bar"><i style="width:${Math.min(100, i.pct).toFixed(0)}%"></i></div>` : ''}
          <div class="jb-sub"><button type="button" class="jb-src" data-jb-go="${esc(i.view)}" data-jb-tab="${esc(i.tab || '')}" title="Mở màn ${esc(i.label)}">${esc(i.label)} ↗</button>
            <span class="jb-text" title="${esc(i.text)}">${bar ? `${i.pct.toFixed(0)}% · ` : ''}${esc(i.text || STATUS[i.status] || '')}</span></div>
        </div>
        ${live && i.cancel ? `<button type="button" class="jb-x" data-jb-stop="${esc(i.source)}" data-id="${esc(i.id)}" title="Dừng tác vụ này">■</button>` : ''}
      </div>`;
  }

  function paint() {
    const box = $('#jobsPanel');
    if (!J.data) { box.innerHTML = '<div class="jb-empty">Đang tải…</div>'; return; }
    const d = J.data;
    const act = d.active.filter(i => J.filter === 'all' || i.status === J.filter);
    const chip = (k, t, n) => `<button type="button" class="jb-chip ${J.filter === k ? 'on' : ''}" data-jb-filter="${k}">${t} <b>${n}</b></button>`;
    const by = {};  // theo nguồn: Studio Muse AI 3 · Tạo video 1 …
    d.active.forEach(i => { by[i.label] = (by[i.label] || 0) + 1; });
    box.innerHTML = `<div class="jb-head"><b>Tiến trình hệ thống</b>
        <span class="jb-sum">${d.running ? `<em>${d.running}</em> đang chạy` : 'Không có tác vụ đang chạy'}${d.queued ? ` · ${d.queued} đang chờ` : ''}</span>
        <button type="button" class="jb-close" data-jb-close title="Đóng (Esc)">✕</button></div>
      ${d.active.length ? `<div class="jb-filters">${chip('all', 'Tất cả', d.active.length)}${chip('running', 'Đang chạy', d.running)}${chip('queued', 'Đang chờ', d.queued)}
        <span class="jb-by">${Object.entries(by).map(([k, n]) => `${esc(k)} ${n}`).join(' · ')}</span></div>` : ''}
      <div class="jb-list">
        ${act.length ? act.map(row).join('') : `<div class="jb-empty">${d.active.length ? 'Không có tác vụ ở mục này' : '✓ Hệ thống đang rảnh — chưa có tác vụ nào chạy'}</div>`}
        ${d.recent.length ? `<div class="jb-sec">Gần đây</div>${d.recent.map(row).join('')}` : ''}
      </div>`;
  }

  function place() {
    const p = $('#jobsPanel'), r = btn().getBoundingClientRect();
    const w = Math.min(440, innerWidth - 16);
    p.style.width = `${w}px`;
    p.style.left = `${Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8))}px`;
    p.style.top = `${r.bottom + 6}px`;
  }

  function toggle(show = !J.open) {
    J.open = show;
    btn().classList.toggle('active', show);
    $('#jobsPanel').classList.toggle('hidden', !show);
    clearInterval(J.timer); clearInterval(J.tick);
    if (show) {
      if (window.Notify) window.Notify.toggle(false);
      place();
      paint();
      refresh();
      J.timer = setInterval(refresh, 1500);
      J.tick = setInterval(() => $$('#jobsPanel [data-since]').forEach(el => { el.textContent = clock(Date.now() - Number(el.dataset.since)); }), 1000);
    } else {
      J.timer = setInterval(refresh, 5000);  // bảng đóng: chỉ cập nhật số trên nút
    }
  }

  function init() {
    if (J.ready || !btn()) return;
    J.ready = true;
    const panel = document.createElement('div');
    panel.id = 'jobsPanel';
    panel.className = 'jb-panel hidden';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Tiến trình hệ thống');
    document.body.appendChild(panel);
    btn().addEventListener('click', e => { e.stopPropagation(); toggle(); });
    panel.addEventListener('click', async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.jbClose !== undefined) return toggle(false);
      if (t.dataset.jbFilter) { J.filter = t.dataset.jbFilter; return paint(); }
      if (t.dataset.jbGo) {
        toggle(false);
        openScreen(t.dataset.jbGo, t.dataset.jbTab);  // ở minivideo.js
        return;
      }
      if (t.dataset.jbStop) {
        t.disabled = true;
        const r = await api('system_cancel', t.dataset.jbStop, t.dataset.id);
        if (!r.ok) toast(r.error, 'error'); else toast('Đã gửi lệnh dừng');
        refresh();
      }
    });
    document.addEventListener('pointerdown', e => {
      if (J.open && !e.target.closest('#jobsPanel') && !e.target.closest('#jobsBtn')) toggle(false);
    });
    document.addEventListener('keydown', e => { if (J.open && e.key === 'Escape') toggle(false); });
    addEventListener('resize', () => { if (J.open) place(); });
    toggle(false);
    refresh();
  }

  // nghe sự kiện backend (bọc hàm của app.js) → số trên nút cập nhật ngay khi tác vụ bắt đầu / xong
  const orig = window.__onBackend;
  if (typeof orig === 'function') window.__onBackend = msg => { try { return orig(msg); } finally { soon(); } };
  window.addEventListener('pywebviewready', () => setTimeout(init, 300));
  window.JobsPanel = { refresh, toggle };
})();
