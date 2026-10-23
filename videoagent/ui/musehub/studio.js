/* Studio Muse AI · tab Studio: soạn lệnh + hàng đợi + chi tiết task (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, fmt, prompts, proj, projTasks, FILTERS, sel } = MH;  // khai báo ở core.js

  // ------------------------------------------------------------ tab Studio: soạn lệnh + hàng đợi
  function renderStudio() {
    $('#mhStudio').innerHTML = '<div class="mh-studio"><section class="card mh-compose" id="mhCompose"></section><section class="card mh-queue" id="mhQueue"></section></div>';
    renderCompose();
    renderQueue();
  }
  function composeCount(n) {
    return `— mỗi khối cách nhau 1 dòng trống = 1 task · <b>${n}</b> task`;
  }
  function renderCompose() {
    const c = H.c;
    const n = prompts(c.text).length;
    $('#mhCompose').innerHTML = `
      <div class="mh-row"><div class="mh-seg">${[['image', '🖼 Tạo ảnh'], ['video', '🎬 Tạo video']].map(([k, l]) => `<button class="${c.kind === k ? 'on' : ''}" data-kind="${k}" type="button">${l}</button>`).join('')}</div>
        <select id="mhRatio" title="Tỉ lệ khung hình">${['', ...H.s.ratios].map(r => `<option value="${r}" ${c.ratio === r ? 'selected' : ''}>${r || 'Tỉ lệ: tự do'}</option>`).join('')}</select>
        ${c.kind === 'video' ? `<select id="mhDur" class="mh-dur" title="Độ dài mỗi video Muse tạo">${(H.s.video_seconds || [5, 10, 15, 20]).map(n => `<option value="${n}" ${+c.duration === n ? 'selected' : ''}>⏱ ${n} giây${n > 10 ? ` · ${Math.ceil(n / 10)} đoạn tự ghép` : ''}</option>`).join('')}</select>` : ''}</div>
      ${c.kind === 'video' ? `<div class="mh-ideabox ${c.ideaOn ? 'on' : ''}">
        <label class="mh-switch"><input type="checkbox" id="mhIdeaOn" ${c.ideaOn ? 'checked' : ''}><i></i> <b>✨ Viết prompt từ ý tưởng / kịch bản (Muse)</b></label>
        ${c.ideaOn ? `<textarea id="mhIdea" rows="4" placeholder="Nhập ý tưởng hoặc kịch bản thô. VD: Trạng Quỳnh ăn cỗ ở làng, quan huyện thách đố, Quỳnh đối đáp thông minh khiến cả làng cười…">${esc(c.idea)}</textarea>
          <div class="mh-row"><select id="mhIdeaCount" title="Số video (số prompt) Muse viết">${[1, 2, 3, 4, 5, 6, 8, 10].map(n => `<option value="${n}" ${+c.ideaCount === n ? 'selected' : ''}>${n} video</option>`).join('')}</select>
            <input id="mhIdeaStyle" value="${esc(c.ideaStyle)}" placeholder="Phong cách (tuỳ chọn): hoạt hình 3D, điện ảnh…"></div>
          <button class="btn primary sm mh-ideago" data-act="idea-go" type="button" ${c.ideaBusy ? 'disabled' : ''}>${c.ideaBusy ? 'Muse đang viết prompt… (1–3 phút)' : `✦ Muse viết prompt timeline · ${c.ideaCount} video × ${c.duration}s`}</button>
          <small class="muted">Mỗi video chia theo mốc giây (0–3s, 3–6s…) khớp độ dài ⏱ đã chọn. Prompt hiện vào ô bên dưới để sửa trước khi thêm vào hàng đợi.</small>`
        : '<small class="muted">Bật để nhập ý tưởng / kịch bản — Muse viết sẵn prompt video dạng timeline theo mốc giây.</small>'}</div>` : ''}
      <div class="mh-row"><select id="mhTpl"><option value="">— Chèn mẫu prompt —</option>${H.s.templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select>
        <button class="btn ghost sm" data-act="save-tpl" type="button" title="Lưu nội dung ô prompt thành mẫu">💾 Lưu làm mẫu</button></div>
      <label class="field"><span>Prompt <small class="muted" id="mhCount">${composeCount(n)}</small></span>
        <textarea id="mhText" rows="9" placeholder="Cô gái Việt Nam 25 tuổi cầm bao phân bón trên cánh đồng lúa, nắng sớm…&#10;&#10;(dòng trống = task mới)">${esc(c.text)}</textarea></label>
      <small class="mh-detected" id="mhDetected"></small>
      <div class="field"><span>Ảnh tham chiếu <small class="muted">(Muse nhận tối đa ${H.s.max_images} ảnh / lệnh, gồm cả người mẫu / nhân vật / ảnh luân phiên)</small></span>
        <div class="mh-thumbs">${c.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt="" title="${esc(im.name || '')}"><button data-rm-img="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
          <button class="mh-add" data-act="add-img" type="button">＋ Ảnh</button></div>
        ${c.images.length > 1 ? `<div class="mh-seg sm">${[['shared', 'Dùng chung (mọi prompt)'], ['pair', 'Ghép cặp (ảnh i ↔ prompt i)']].map(([k, l]) => `<button class="${c.pairing === k ? 'on' : ''}" data-pair="${k}" type="button">${l}</button>`).join('')}</div>` : ''}</div>
      <div class="mh-toggles">
        <label class="mh-switch"><input type="checkbox" data-hub-toggle="model" ${H.s.model.on ? 'checked' : ''}><i></i> Người mẫu cố định <small>${MH.modelHero() ? esc(MH.modelHero().name) : `${H.s.model.images.length} ảnh`}</small></label>
        <label class="mh-switch"><input type="checkbox" data-hub-toggle="rotate" ${H.s.rotate.on ? 'checked' : ''}><i></i> Ảnh luân phiên <small>${H.s.rotate.images.length} ảnh</small></label>
      </div>
      <button class="btn primary mh-go" data-act="add-tasks" type="button" ${n ? '' : 'disabled'}>＋ Thêm ${n || ''} task vào hàng đợi</button>`;
    renderDetected();
  }
  function renderDetected() {
    const el = $('#mhDetected');
    if (!el) return;
    const text = ` ${H.c.text.toLowerCase()} `;
    const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const names = H.s.characters.filter(ch => ch.name && new RegExp(`(^|[^\\p{L}\\d])${escRe(ch.name.toLowerCase())}($|[^\\p{L}\\d])`, 'u').test(text)).map(ch => ch.name);
    el.textContent = names.length ? `Nhân vật nhận ra: ${names.join(', ')} — tự gắn ảnh nhân vật`
      : (H.s.characters.length ? 'Gõ đúng tên nhân vật (tab Tư liệu) trong prompt để tự gắn ảnh' : '');
  }
  function visibleTasks() {
    const q = H.q.trim().toLowerCase();
    return projTasks().filter(t => (H.filter === 'all' || t.status === H.filter) && (!q || t.prompt.toLowerCase().includes(q)))
      .sort((a, b) => b.created_at - a.created_at);
  }
  function renderQueue() {
    const box = $('#mhQueue');
    if (!box) return;
    const all = projTasks();
    const list = visibleTasks();
    const ids = new Set(all.map(t => t.id));
    [...H.sel].forEach(id => { if (!ids.has(id)) H.sel.delete(id); });
    const accName = id => (H.s.accounts.find(a => a.id === id) || {}).name || '';
    const count = k => (k === 'all' ? all.length : all.filter(t => t.status === k).length);
    const n = H.sel.size;
    const focus = document.activeElement && document.activeElement.id === 'mhSearch';
    box.innerHTML = `<div class="mh-qhead"><b>Hàng đợi</b><small class="muted">${esc(proj().name)}</small>
        <input id="mhSearch" type="search" placeholder="🔍 Tìm prompt…" value="${esc(H.q)}"></div>
      <div class="mh-chips">${FILTERS.map(([k, l]) => `<button class="chip-f ${H.filter === k ? 'active' : ''}" data-filter="${k}" type="button">${l} <span>${count(k)}</span></button>`).join('')}</div>
      <div class="mh-bulk"><label class="check"><input type="checkbox" data-act="sel-all" ${list.length && list.every(t => H.sel.has(t.id)) ? 'checked' : ''}> Chọn tất cả</label>
        <button class="link" data-act="sel-failed" type="button">Chọn lỗi</button><button class="link" data-act="sel-queued" type="button">Chọn chưa chạy</button>
        <span class="mh-top-sp"></span>
        ${n ? `<small class="muted">${n} đã chọn</small>
          <button class="btn ghost sm" data-bulk="retry" type="button">↻ Chạy lại</button>
          <button class="btn ghost sm" data-bulk="cancel" type="button">■ Huỷ</button>
          <button class="btn ghost sm st-pdel" data-bulk="delete" type="button">🗑 Xoá</button>` : ''}</div>
      <div class="mh-rows">${list.length ? list.map(t => `<div class="mh-task ${esc(t.status)}" data-task="${esc(t.id)}">
          <input type="checkbox" data-sel="${esc(t.id)}" ${H.sel.has(t.id) ? 'checked' : ''}>
          <span class="mh-kind" title="${t.kind === 'video' ? 'Video' : 'Ảnh'}">${t.kind === 'video' ? '🎬' : '🖼'}</span>
          <div class="mh-tbody"><p>${esc(t.prompt)}</p>
            <small>${esc(t.ratio || 'tự do')}${t.kind === 'video' && t.duration ? ` · ⏱ ${t.duration}s` : ''}${t.group && t.role === 'scene' ? ` · <b class="mh-part">Phần ${t.scene}/${H.s.tasks.filter(x => x.group === t.group && x.role === 'scene').length}</b>` : ''}${t.images.length ? ` · ${t.images.length} ảnh` : ''}${t.account ? ` · 👤 ${esc(accName(t.account))}` : ''}${t.attempts > 1 ? ` · lần ${t.attempts}` : ''} · ${fmt(t.created_at)}</small>
            ${t.error && t.status !== 'succeeded' ? `<small class="mh-err">${esc(t.error.slice(0, 180))}</small>` : ''}</div>
          <div class="mh-tfiles">${t.files.slice(0, 2).map(f => `<img src="${esc(thumbUrl(f.url, 96))}" alt="" loading="lazy" decoding="async">`).join('')}</div>
          <span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status] || t.status)}</span>
        </div>`).join('') : `<div class="empty">${all.length ? 'Không có task khớp bộ lọc.' : 'Chưa có task — soạn prompt bên trái rồi bấm “Thêm vào hàng đợi”.'}</div>`}</div>`;
    if (focus) { const s = $('#mhSearch'); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  }
  function openDetail(id) {
    H.detail = id;
    openModal('TASK', 'Chi tiết task', '<div id="mhDetail"></div>');
    paintDetail();
  }
  function paintDetail() {
    const el = $('#mhDetail');
    const t = H.s.tasks.find(x => x.id === H.detail);
    if (!el || !t) { H.detail = null; return; }
    const acc = (H.s.accounts.find(a => a.id === t.account) || {}).name || '—';
    const vertical = /^(9:16|3:4|4:5)$/.test(t.ratio || '');
    const media = t.files.length
      ? t.files.map((f, i) => `<figure class="${i ? 'more' : ''}">${f.video ? `<video src="${esc(f.url)}" controls preload="metadata"></video>` : `<img src="${esc(f.url)}" alt="">`}
          <button class="btn ghost sm" data-open-file="${esc(f.path)}" type="button" title="Mở thư mục, chọn sẵn file">📂 Mở thư mục</button></figure>`).join('')
      : `<div class="mh-dph ${esc(t.status)}"><span>${t.kind === 'video' ? '🎬' : '🖼'}</span><small>${esc(H.s.statuses[t.status] || t.status)}${t.status === 'processing' ? '…' : ''}</small></div>`;
    const logOpen = el.querySelector('.mh-log');
    const stick = !logOpen || logOpen.scrollTop + logOpen.clientHeight >= logOpen.scrollHeight - 8;
    el.innerHTML = `<div class="mh-detail ${vertical ? 'vert' : 'wide'}">
      <div class="mh-dmedia">${media}</div>
      <div class="mh-dinfo">
        <div class="mh-dmeta"><span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status])}</span>
          <span>${t.kind === 'video' ? 'Video' : 'Ảnh'} · ${esc(t.ratio || 'tự do')}${t.kind === 'video' && t.duration ? ` · ${t.duration}s` : ''}</span><span title="Tài khoản Muse">👤 ${esc(acc)}</span>
          <span>Lần chạy ${t.attempts}</span><span>${fmt(t.created_at)}</span></div>
        ${t.error ? `<div class="mh-err-box">${esc(t.error)}</div>` : ''}
        <div class="mh-dsec"><div class="mh-dlabel"><b>Prompt</b><button class="link" data-copy-prompt type="button">Sao chép</button></div>
          <div class="mh-dprompt">${esc(t.prompt)}</div></div>
        ${t.image_urls.length ? `<div class="mh-dsec"><div class="mh-dlabel"><b>Ảnh đính kèm</b><small class="muted">${t.image_urls.length} ảnh</small></div>
          <div class="mh-thumbs">${t.image_urls.map(u => `<span class="mh-thumb sm" data-zoom="${esc(u)}"><img src="${esc(u)}" alt=""></span>`).join('')}</div></div>` : ''}
        ${(t.notes || []).length ? `<small class="muted">${t.notes.map(esc).join(' · ')}</small>` : ''}
        <div class="mh-dsec grow"><div class="mh-dlabel"><b>Nhật ký</b><small class="muted">${(t.log || []).length} dòng</small></div>
          <div class="mh-log">${(t.log || []).map(l => `<div>${esc(l)}</div>`).join('') || '<small class="muted">Chưa có nhật ký</small>'}</div></div>
        <div class="mh-dact"><button class="btn ghost sm st-pdel" data-dt="delete" type="button">🗑 Xoá task</button><span class="mh-top-sp"></span>
          ${['queued', 'processing'].includes(t.status) ? '<button class="btn ghost sm" data-dt="cancel" type="button">■ Huỷ</button>' : ''}
          ${['failed', 'cancelled', 'succeeded'].includes(t.status) ? '<button class="btn primary sm" data-dt="retry" type="button">↻ Chạy lại</button>' : ''}</div>
      </div></div>`;
    const lg = el.querySelector('.mh-log');
    if (stick) lg.scrollTop = lg.scrollHeight;
    $('#modalBody').onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.openFile) return api('mhub_open', b.dataset.openFile);
      if (b.dataset.copyPrompt !== undefined) { navigator.clipboard.writeText(t.prompt).then(() => toast('Đã sao chép prompt', 'ok'), () => toast('Không sao chép được', 'error')); return; }
      if (b.dataset.dt) {
        if (b.dataset.dt === 'delete' && !confirm('Xoá task này (file đã tải vẫn giữ)?')) return;
        await api('mhub_tasks', [t.id], b.dataset.dt);
        if (b.dataset.dt === 'delete') { H.detail = null; closeModal(); }
      }
    };
  }

  Object.assign(MH, { renderStudio, composeCount, renderCompose, renderDetected, visibleTasks, renderQueue, openDetail, paintDetail });
})();
