/* Thông báo chung — nút 🔔 trên thanh tiêu đề (số chưa đọc), bấm để bật / tắt bảng thông báo. Mỗi tác vụ của mọi màn vừa
   xong / lỗi → 1 thông báo + thẻ báo nổi góc phải; bấm để xem nhanh kết quả (video phát ở khung nổi, ảnh xem phóng to),
   mở thư mục, hoặc mở đúng màn. Nguồn dữ liệu: jobs.js gọi Notify.feed(system_progress) mỗi lần cập nhật — so trạng thái
   lần trước để biết tác vụ nào vừa kết thúc. Danh sách lưu ở localStorage (chỉ máy này, mất cũng không sao). */
(() => {
  'use strict';
  const KEY = 'va.notify', MAX = 60;
  const N = { list: [], known: null, open: false, filter: 'all' };
  const btn = () => $('#notifyBtn');
  const keyOf = i => `${i.source}:${i.id}`;

  try { N.list = JSON.parse(localStorage.getItem(KEY) || '[]').slice(0, MAX); } catch { N.list = []; }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(N.list.slice(0, MAX))); } catch { /* bỏ qua */ } };
  const ago = ms => {
    const m = Math.round((Date.now() - ms) / 60000);
    return m < 1 ? 'vừa xong' : m < 60 ? `${m} phút trước` : m < 1440 ? `${Math.floor(m / 60)} giờ trước` : `${Math.floor(m / 1440)} ngày trước`;
  };

  // ------------------------------------------------------------ nhận dữ liệu tiến trình
  function feed(data) {
    const items = [...data.active, ...data.recent];
    const first = N.known === null;
    const prev = N.known || new Map();
    N.known = new Map(items.map(i => [keyOf(i), i.status]));
    const fresh = [];
    for (const i of data.recent) {
      if (i.grouped || !['done', 'failed'].includes(i.status)) continue;  // đoạn của video kịch bản → báo khi cả video xong
      const k = keyOf(i);
      if (N.list.some(n => n.key === k)) continue;
      const was = prev.get(k);
      if (!first && was && was === i.status) continue;
      // lần đầu mở app: tác vụ đã xong từ trước → đưa vào danh sách nhưng coi như đã đọc, không báo nổi
      const note = { key: k, source: i.source, label: i.label, view: i.view, tab: i.tab || '', id: i.id, title: i.title,
        status: i.status, text: i.status === 'failed' ? i.text : '', at: i.finished || Date.now(), results: i.results || [],
        folder: i.folder || null, url: i.url || '', read: first };
      N.list.unshift(note);
      if (!first) fresh.push(note);
    }
    if (fresh.length || first) {
      N.list.sort((a, b) => b.at - a.at);
      N.list = N.list.slice(0, MAX);
      save();
    }
    fresh.slice(0, 3).forEach(pop);
    paintBadge();
    if (N.open && fresh.length) paint();
  }

  function paintBadge() {
    const n = N.list.filter(x => !x.read).length;
    const badge = $('#notifyCount');
    if (!badge) return;
    badge.textContent = n > 99 ? '99+' : n;
    badge.classList.toggle('hidden', !n);
    btn().classList.toggle('unread', n > 0);
    btn().title = n ? `Thông báo — ${n} chưa xem` : 'Thông báo';
  }

  // ------------------------------------------------------------ xem nhanh kết quả
  function view(note, k = 0) {
    const r = note.results[k];
    if (!r) return openScreen(note.view, note.tab);
    if (r.kind === 'video') return window.MiniVideo.open(r.url, 0, { view: note.view, tab: note.tab });
    openModal('Ảnh', note.title, `<div class="nt-imgview"><img src="${esc(r.url)}" alt=""></div>`);
  }
  async function folder(note) {
    const r = await api(note.folder.api, ...note.folder.args);
    if (r && r.ok === false) toast(r.error, 'error');
  }
  const find = k => N.list.find(n => n.key === k);
  function act(b) {
    const note = find(b.dataset.ntKey);
    if (!note) return;
    note.read = true; save(); paintBadge();
    const a = b.dataset.nt;
    if (a === 'view') view(note, +(b.dataset.k || 0));
    else if (a === 'folder') folder(note);
    else if (a === 'link') api('open_url', note.url);
    else if (a === 'go') { toggle(false); openScreen(note.view, note.tab); }  // openScreen ở minivideo.js
    else if (a === 'del') { N.list = N.list.filter(n => n !== note); save(); paintBadge(); paint(); }
  }

  const thumbs = (n, big) => n.results.length ? `<div class="nt-thumbs ${big ? 'big' : ''}">${n.results.map((r, k) => `<button type="button" class="nt-th" data-nt="view" data-nt-key="${esc(n.key)}" data-k="${k}" title="${r.kind === 'video' ? 'Phát video' : 'Xem ảnh'}">
      <img src="${esc(thumbUrl(r.url, 200))}" alt="" loading="lazy" decoding="async">${r.kind === 'video' ? '<i>▶</i>' : ''}</button>`).join('')}</div>` : '';
  const actions = n => `<div class="nt-acts">
      ${n.results.length ? `<button type="button" class="nt-b main" data-nt="view" data-nt-key="${esc(n.key)}">${n.results[0].kind === 'video' ? '▶ Xem video' : '🖼 Xem ảnh'}</button>` : ''}
      ${n.folder ? `<button type="button" class="nt-b" data-nt="folder" data-nt-key="${esc(n.key)}" title="Mở thư mục, chọn sẵn file">📂 Thư mục</button>` : ''}
      ${n.url ? `<button type="button" class="nt-b main" data-nt="link" data-nt-key="${esc(n.key)}" title="Mở bài trên Facebook">↗ Xem bài</button>` : ''}
      <button type="button" class="nt-b" data-nt="go" data-nt-key="${esc(n.key)}" title="Mở màn ${esc(n.label)}">↗ ${esc(n.label)}</button></div>`;

  // thẻ báo nổi khi có tác vụ vừa xong (tự ẩn sau 8 giây, rê chuột vào thì giữ)
  function pop(note) {
    let stack = $('#ntStack');
    if (!stack) { stack = document.createElement('div'); stack.id = 'ntStack'; document.body.appendChild(stack); }
    const el = document.createElement('div');
    el.className = `nt-pop ${note.status}`;
    el.innerHTML = `<div class="nt-pophead"><span class="nt-ico">${note.status === 'failed' ? '⚠' : '✓'}</span>
        <div><small>${esc(note.label)} · ${note.status === 'failed' ? 'Lỗi' : 'Đã xong'}</small><b title="${esc(note.title)}">${esc(note.title)}</b></div>
        <button type="button" class="nt-popx" title="Đóng">✕</button></div>
      ${note.text ? `<p class="nt-err">${esc(note.text)}</p>` : ''}${thumbs(note, false)}${actions(note)}`;
    stack.prepend(el);
    let timer = 0;
    const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 220); };
    const arm = () => { clearTimeout(timer); timer = setTimeout(close, 8000); };
    el.addEventListener('mouseenter', () => clearTimeout(timer));
    el.addEventListener('mouseleave', arm);
    el.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.classList.contains('nt-popx')) return close();
      act(b); close();
    });
    arm();
    while (stack.children.length > 3) stack.lastChild.remove();
  }

  // ------------------------------------------------------------ bảng thông báo
  function paint() {
    const box = $('#notifyPanel');
    const list = N.list.filter(n => N.filter === 'all' || (N.filter === 'failed' ? n.status === 'failed' : n.results.length));
    const chip = (k, t, c) => `<button type="button" class="jb-chip ${N.filter === k ? 'on' : ''}" data-nt-filter="${k}">${t} <b>${c}</b></button>`;
    box.innerHTML = `<div class="jb-head"><b>Thông báo</b><span class="jb-sum">${N.list.length ? `${N.list.length} thông báo` : ''}</span>
        ${N.list.length ? '<button type="button" class="link nt-clear" data-nt-clear title="Xoá mọi thông báo">Xoá hết</button>' : ''}
        <button type="button" class="jb-close" data-nt-close title="Đóng (Esc)">✕</button></div>
      ${N.list.length ? `<div class="jb-filters">${chip('all', 'Tất cả', N.list.length)}${chip('result', 'Có kết quả', N.list.filter(n => n.results.length).length)}${chip('failed', 'Lỗi', N.list.filter(n => n.status === 'failed').length)}</div>` : ''}
      <div class="jb-list">${list.length ? list.map(n => `<div class="nt-row ${n.status} ${n.read ? '' : 'new'}">
          <span class="nt-ico">${n.status === 'failed' ? '⚠' : '✓'}</span>
          <div class="nt-main"><div class="jb-top"><b title="${esc(n.title)}">${esc(n.title)}</b><span class="jb-time">${ago(n.at)}</span>
              <button type="button" class="nt-del" data-nt="del" data-nt-key="${esc(n.key)}" title="Xoá thông báo">✕</button></div>
            ${n.text ? `<p class="nt-err">${esc(n.text)}</p>` : ''}${thumbs(n, true)}${actions(n)}</div></div>`).join('')
        : `<div class="jb-empty">${N.list.length ? 'Không có thông báo ở mục này' : '🔔 Chưa có thông báo — tác vụ xong / lỗi sẽ báo ở đây'}</div>`}</div>`;
  }

  function place() {
    const p = $('#notifyPanel'), r = btn().getBoundingClientRect();
    const w = Math.min(460, innerWidth - 16);
    p.style.width = `${w}px`;
    p.style.left = `${Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8))}px`;
    p.style.top = `${r.bottom + 6}px`;
  }
  function toggle(show = !N.open) {
    if (!$('#notifyPanel')) return;
    N.open = show;
    btn().classList.toggle('active', show);
    $('#notifyPanel').classList.toggle('hidden', !show);
    if (show) {
      if (window.JobsPanel) window.JobsPanel.toggle(false);
      place(); paint();
      N.list.forEach(n => { n.read = true; });  // mở bảng = đã xem (mục mới vẫn tô sáng tới lần mở sau)
      save(); paintBadge();
    }
  }

  function init() {
    if (!btn() || $('#notifyPanel')) return;
    const panel = document.createElement('div');
    panel.id = 'notifyPanel';
    panel.className = 'jb-panel nt-panel hidden';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Thông báo');
    document.body.appendChild(panel);
    btn().addEventListener('click', e => { e.stopPropagation(); toggle(); });
    panel.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.ntClose !== undefined) return toggle(false);
      if (b.dataset.ntClear !== undefined) { if (!confirm('Xoá mọi thông báo?')) return; N.list = []; save(); paintBadge(); return paint(); }
      if (b.dataset.ntFilter) { N.filter = b.dataset.ntFilter; return paint(); }
      if (b.dataset.nt) { act(b); if (b.dataset.nt !== 'del' && b.dataset.nt !== 'go') paint(); }
    });
    document.addEventListener('pointerdown', e => {
      if (N.open && !e.target.closest('#notifyPanel, #notifyBtn, #modal, #miniVideo')) toggle(false);
    });
    document.addEventListener('keydown', e => { if (N.open && e.key === 'Escape' && $('#modal').classList.contains('hidden')) toggle(false); });
    addEventListener('resize', () => { if (N.open) place(); });
    paintBadge();
  }

  window.addEventListener('pywebviewready', () => setTimeout(init, 200));
  window.Notify = { feed, toggle };
})();
