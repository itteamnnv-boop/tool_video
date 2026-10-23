/* Studio Muse AI · tab Thư viện + trình xem + ghép video (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, fmt, proj, sel, libSelVideos } = MH;  // khai báo ở core.js
  // hàm ở file khác — gọi qua MH lúc chạy
  const openDetail = (...a) => MH.openDetail(...a);

  // ------------------------------------------------------------ tab Thư viện + ghép video
  async function loadLibrary() {
    const res = await api('mhub_library', H.s.current);
    H.lib.items = res.ok ? res.items : [];
    H.lib.sel = H.lib.sel.filter(p => H.lib.items.some(i => i.path === p));
    renderLibrary();
  }
  function libSelect(k, e) {  // Ctrl + bấm: thêm / bỏ 1 ô · Shift + bấm: chọn cả dải từ ô bấm trước
    const items = H.lib.items;
    if (e.shiftKey && H.lib.anchor != null) {
      const [a, b] = [Math.min(H.lib.anchor, k), Math.max(H.lib.anchor, k)];
      const range = items.slice(a, b + 1).map(i => i.path);
      H.lib.sel = [...H.lib.sel, ...range.filter(p => !H.lib.sel.includes(p))];
    } else {
      const p = items[k].path;
      H.lib.sel = H.lib.sel.includes(p) ? H.lib.sel.filter(x => x !== p) : [...H.lib.sel, p];
      H.lib.anchor = k;
    }
    paintLibSel();
  }
  function libHead() {
    const items = H.lib.items;
    const vids = items.filter(i => i.video).length;
    const n = H.lib.sel.length, nv = libSelVideos().length;
    const others = H.s.projects.filter(p => p.id !== H.s.current);
    return `<div class="card mh-libhead ${n ? 'picking' : ''}"><b>Thư viện · ${esc(proj().name)}</b>
        ${n ? `<span class="mh-pill ok">Đã chọn ${n}${nv !== n ? ` · ${nv} video` : ''}</span>
          <button class="link" data-act="lib-none" type="button">Bỏ chọn</button>
          <span class="mh-top-sp"></span>
          ${others.length ? `<span class="mh-libmove"><small class="muted">Chuyển sang</small><select id="mhLibMoveTo">${others.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select>
            <button class="btn ghost sm" data-act="lib-move" type="button">↪ Chuyển</button></span>`
            : '<small class="muted">Tạo thêm dự án (nút Dự án) để chuyển file sang</small>'}`
        : `<small class="muted">${items.length} file · ${vids} video · kéo chuột để tô chọn nhiều · Ctrl/Shift + bấm để chọn</small>
          <span class="mh-top-sp"></span>`}
        <button class="btn ghost sm" data-act="lib-all" type="button" ${items.length && n < items.length ? '' : 'disabled'}>Chọn tất cả</button>
        <button class="btn ghost sm" data-act="lib-reload" type="button">Tải lại</button>
        <button class="btn primary sm" data-act="merge" type="button" ${nv >= 2 ? '' : 'disabled title="Chọn ít nhất 2 video"'}>🎞 Ghép video (${nv})</button></div>`;
  }
  // chỉ đổi lựa chọn → vẽ lại thanh trên + bật/tắt dấu chọn trên ô sẵn có (không dựng lại lưới → video không tải lại)
  function paintLibSel() {
    const head = $('#mhLibrary .mh-libhead');
    if (!head || !$('#mhLibrary .mh-libgrid')) return renderLibrary();
    head.outerHTML = libHead();
    const picked = new Set(H.lib.sel);
    $$('#mhLibrary .mh-libcell').forEach(cell => {
      const i = H.lib.items[+cell.dataset.libK];
      const on = !!i && picked.has(i.path);
      cell.querySelector('.mh-lib').classList.toggle('sel', on);
      const box = cell.querySelector('[data-lib-sel]');
      if (box) box.checked = on;
    });
  }
  function renderLibrary() {
    const items = H.lib.items;
    $('#mhLibrary').innerHTML = `${libHead()}
      <div class="img-grid mh-libgrid">${items.length ? items.map((i, k) => `<div class="mh-libcell" data-lib-k="${k}"><div class="img-tile mh-lib ${H.lib.sel.includes(i.path) ? 'sel' : ''}" data-lib-view="${k}" title="Bấm để ${i.video ? 'phát video' : 'xem ảnh'} · Ctrl/Shift + bấm để chọn">
          <img src="${esc(thumbUrl(i.url, 360))}" alt="" loading="lazy" decoding="async">${i.video ? '<i class="img-count">🎬</i><span class="mh-libplay">▶</span>' : ''}
          <label class="mh-libsel" title="Chọn"><input type="checkbox" data-lib-sel="${esc(i.path)}" ${H.lib.sel.includes(i.path) ? 'checked' : ''}></label>
          <div class="img-tile-bar"><small>${fmt(i.finished_at)}</small><button class="img-tile-btn" data-lib-open="${esc(i.path)}" title="Mở thư mục, chọn sẵn file" type="button">📂</button></div>
        </div><div class="mh-libcap" data-lib-view="${k}" title="${esc(i.label || i.name || '')}"><b>${esc(i.label || i.name || '')}</b><small>${esc(fmt(i.finished_at))}</small></div></div>`).join('') : '<div class="empty">Chưa có file — task xong sẽ hiện ở đây.</div>'}</div>`;
  }

  // xem / phát 1 file thư viện: ‹ › hoặc phím ← → để chuyển file
  function openLibViewer(k) {
    const items = H.lib.items;
    const i = items[k];
    if (!i) return;
    H.lib.view = k;
    const task = H.s.tasks.find(t => t.id === i.task);
    const picked = H.lib.sel.includes(i.path);
    openModal(`${i.video ? 'VIDEO' : 'ẢNH'} ${k + 1}/${items.length}`, i.label || i.name || (i.video ? 'Video' : 'Ảnh'), `<div class="iv" id="mhLibView">
        <div class="iv-stage">
          <button class="iv-nav prev" data-lv="${k - 1}" type="button" ${k > 0 ? '' : 'disabled'} aria-label="File trước">‹</button>
          ${i.video ? `<video src="${esc(i.url)}" controls autoplay playsinline></video>` : `<img src="${esc(i.url)}" alt="">`}
          <button class="iv-nav next" data-lv="${k + 1}" type="button" ${k < items.length - 1 ? '' : 'disabled'} aria-label="File sau">›</button>
        </div>
        <aside class="iv-info">
          <div class="iv-meta"><span>${i.video ? '🎬 Video' : '🖼 Ảnh'}</span><span>🕒 ${esc(fmt(i.finished_at))}</span>
            ${task && task.ratio ? `<span>▭ ${esc(task.ratio)}</span>` : ''}${task && task.account ? `<span>👤 ${esc((H.s.accounts.find(a => a.id === task.account) || {}).name || '')}</span>` : ''}
            <span class="mono">${esc(i.name || '')}</span></div>
          <div class="iv-prompt"><b>Prompt</b><p>${esc((task && task.prompt) || i.prompt || '')}</p></div>
          <div class="iv-actions">
            <button class="btn ghost sm" data-lv-act="folder" type="button">📂 Mở thư mục</button>
            <button class="btn ghost sm" data-lv-act="copy" type="button">⧉ Sao chép prompt</button>
            ${task ? '<button class="btn ghost sm" data-lv-act="task" type="button">☰ Xem task</button>' : ''}
            ${i.video ? `<button class="btn ${picked ? 'primary' : 'ghost'} sm" data-lv-act="pick" type="button">${picked ? '✓ Đã chọn để ghép' : '＋ Chọn để ghép'}</button>` : ''}
          </div>
        </aside></div>`);
    $('#modalCard').classList.add('wide-viewer');
    $('#modalBody').onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.lv !== undefined) return openLibViewer(+b.dataset.lv);
      const act = b.dataset.lvAct;
      if (act === 'folder') return api('mhub_open', i.path);
      if (act === 'copy') { await navigator.clipboard.writeText((task && task.prompt) || i.prompt || '').catch(() => {}); return toast('Đã sao chép prompt', 'ok'); }
      if (act === 'task') return openDetail(task.id);
      if (act === 'pick') {
        H.lib.sel = picked ? H.lib.sel.filter(x => x !== i.path) : [...H.lib.sel, i.path];
        paintLibSel();
        return openLibViewer(k);
      }
    };
  }
  function mergeDialog() {
    const order = libSelVideos();  // chỉ ghép video trong số đã chọn
    const nameOf = p => p.split(/[\\/]/).pop();
    H.merge = null;
    const paint = () => {
      openModal('THƯ VIỆN', 'Ghép video', `<div class="form">
        <div class="mh-merge">${order.map((p, i) => `<div class="mh-mrow"><span>${i + 1}.</span><b>${esc(nameOf(p))}</b>
          <button class="btn ghost sm" data-mv="${i}" data-d="-1" type="button" ${i ? '' : 'disabled'}>↑</button>
          <button class="btn ghost sm" data-mv="${i}" data-d="1" type="button" ${i < order.length - 1 ? '' : 'disabled'}>↓</button>
          <button class="btn ghost sm st-pdel" data-mrm="${i}" type="button">✕</button></div>`).join('')}</div>
        <label class="field"><span>Tên file</span><input id="mhMergeName" value="${esc(proj().name)} - ghep"></label>
        <div class="mh-progress hidden" id="mhMergeBar"><i></i><span></span></div>
        <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-mg-cancel type="button">Đóng</button>
          <button class="btn primary" data-mg-go type="button" ${order.length >= 2 ? '' : 'disabled'}>🎞 Ghép ${order.length} video</button></div></div>`, true);
      $('#modalBody').onclick = async e => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.mgCancel !== undefined) return closeModal();
        if (b.dataset.mv !== undefined) { const i = +b.dataset.mv; const j = i + +b.dataset.d; [order[i], order[j]] = [order[j], order[i]]; return paint(); }
        if (b.dataset.mrm !== undefined) { order.splice(+b.dataset.mrm, 1); return paint(); }
        if (b.dataset.mgGo !== undefined) {
          b.disabled = true;
          const res = await api('mhub_merge', order, $('#mhMergeName').value, H.s.current);
          if (!res.ok) { b.disabled = false; return toast(res.error, 'error'); }
          H.merge = { job: res.job.job, pct: 0 };
          paintMerge();
        }
      };
    };
    paint();
  }
  function paintMerge() {
    const bar = $('#mhMergeBar');
    if (!bar || !H.merge) return;
    bar.classList.remove('hidden');
    const pct = Math.max(0, H.merge.pct);
    bar.querySelector('i').style.width = `${pct}%`;
    bar.querySelector('span').textContent = H.merge.pct < 0 ? 'Lỗi' : H.merge.done ? 'Xong ✓' : `${pct}%`;
    if (H.merge.done && !H.merge.error) loadLibrary();
  }

  Object.assign(MH, { loadLibrary, libSelect, renderLibrary, paintLibSel, openLibViewer, mergeDialog, paintMerge });
})();
