/* Studio Muse AI · tab Kịch bản: form, danh sách video, chi tiết (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { METHODS, DURS, VOICES, MOTIONS, GSTATUS, H, fmt, sel, parseVideos, GFILTERS, gcat, projGroups, gNo } = MH;  // khai báo ở core.js
  // hàm ở file khác — gọi qua MH lúc chạy
  const renderTop = (...a) => MH.renderTop(...a);

  function renderScript() {
    $('#mhScript').innerHTML = `<div class="mk-wrap">
      <section class="card mk-form" id="mhKForm"></section>
      <div class="mk-bar" id="mhGBar"></div>
      <div class="mk-main"><section class="card mk-table" id="mhGroups"></section><section class="card mk-detail" id="mhGDetail"></section></div>
      <section class="card mk-foot" id="mhGFoot"></section></div>`;
    renderKForm();
    renderGroups();
  }

  // xem trước đánh số: mỗi khối (cách 1 dòng trống) = 1 video, số nối tiếp các video đã có trong dự án
  function kOutline() {
    const vids = parseVideos(H.k.text);
    if (!vids.length) return '';
    const start = H.s.groups.filter(g => (g.project || 'default') === H.s.current).reduce((m, g) => Math.max(m, g.no || 0), 0);
    const mult = Math.max(1, H.k.images.length) * Math.max(1, H.k.versions);
    return `${vids.map((v, i) => {
      const a = start + i * Math.max(1, H.k.versions) + 1;
      const label = mult > 1 && H.k.images.length <= 1 ? `#${String(a).padStart(2, '0')}–${String(a + H.k.versions - 1).padStart(2, '0')}` : `#${String(a).padStart(2, '0')}`;
      return `<div class="mk-oline"><b class="mk-no">${mult > 1 && H.k.images.length > 1 ? `Video ${i + 1}` : label}</b><span>${esc(v[0])}</span><small>${v.length} cảnh</small></div>`;
    }).join('')}${H.k.images.length > 1 ? `<small class="muted">× ${H.k.images.length} ảnh sản phẩm — mỗi ảnh 1 bộ, số nối tiếp theo thứ tự ảnh</small>` : ''}`;
  }
  function kCount() {
    const k = H.k;
    if (k.mode === 'image') return `${k.images.length} ảnh → ${k.images.length * k.versions} video`;
    const vids = parseVideos(k.text);
    const sets = Math.max(1, k.images.length);
    return `${vids.length} video · ${vids.reduce((n, v) => n + v.length, 0)} cảnh${sets > 1 ? ` × ${sets} ảnh` : ''}${k.versions > 1 ? ` × ${k.versions} bản` : ''}`;
  }
  function renderKForm() {
    const k = H.k;
    const script = k.mode === 'script';
    const chars = [['', 'Không dùng'], ...H.s.characters.map(c => [c.id, c.name])];
    const perScene = script && k.duration === 'per_scene';
    $('#mhKForm').innerHTML = `
      <div class="mk-left">
        <div class="mh-seg">${[['script', 'Kịch bản'], ['image', 'Từ ảnh']].map(([m, l]) => `<button class="${k.mode === m ? 'on' : ''}" data-kmode="${m}" type="button">${l}</button>`).join('')}</div>
        ${script ? `<textarea id="mhKText" placeholder="VD:&#10;0-10s: Cô gái Việt giơ hộp giữa kho hàng đầy ắp, cận cảnh lung linh đèn Noel&#10;10-20s: Cả gia đình quây quần mở quà hộp lịch Giáng Sinh&#10;&#10;Mỗi dòng 1 cảnh · cách 1 dòng trống để sang video tiếp theo" title="Mỗi dòng là 1 cảnh · cách 1 dòng trống để sang video tiếp theo">${esc(k.text)}</textarea>`
        : `<div class="field"><span>Gợi ý chuyển động <small class="muted">(chọn nhiều được)</small></span>
            <div class="mh-chips">${MOTIONS.map(([m, l]) => `<button class="chip-f ${k.motions.includes(m) ? 'active' : ''}" data-motion="${m}" type="button">${l}</button>`).join('')}</div></div>
          <label class="field"><span>Ghi chú thêm (tuỳ chọn)</span><input id="mhKNote" value="${esc(k.note)}" placeholder="VD: nền gỗ, ánh sáng ấm"></label>`}
        <small class="mh-detected" id="mhKCount">${esc(kCount())}</small>
        ${script ? `<div class="mk-outline" id="mhKOutline">${kOutline()}</div>` : ''}
      </div>
      <div class="mk-right">
        ${script ? `<label class="field mk-span3"><span>Cách làm</span>${sel('mhKMethod', METHODS, k.method)}</label>` : ''}
        <label class="field"><span>Tỉ lệ</span>${sel('mhKRatio', [['9:16', '9:16 · Dọc (TikTok, Reels)'], ['16:9', '16:9 · Ngang (YouTube)'], ['1:1', '1:1 · Vuông']], k.ratio)}</label>
        ${script ? `<label class="field"><span>Thời lượng</span>${sel('mhKDur', DURS, k.duration)}</label>` : ''}
        <label class="field ${script ? '' : 'mk-span2'}" title="Thêm vào đầu mọi lệnh gửi Muse"><span>Tiền tố câu lệnh</span><input id="mhKPrefix" value="${esc(k.prefix)}" placeholder="VD: Tạo video chân thực:"></label>
        <label class="field"><span>Giọng đọc</span>${sel('mhKVoice', VOICES, k.voice)}</label>
        <label class="field"><span>Người dẫn</span>${sel('mhKPresenter', [['', 'Theo giọng đọc'], ['female', 'Nữ'], ['male', 'Nam']], k.presenter)}</label>
        <label class="field" title="Gửi kèm ảnh nhân vật (tab Tư liệu) để mọi video giữ đúng 1 gương mặt người dẫn"><span>Nhân vật dẫn</span>${sel('mhKChar', chars, k.character)}</label>
        ${script ? `<div class="field" title="${perScene ? 'Các cảnh 10s làm xong sẽ tự ghép thành 1 video' : 'Chỉ dùng khi Thời lượng = Từng cảnh 10s'}"><span>Từng cảnh</span>
          <label class="check mk-check ${perScene ? '' : 'off'}"><input type="checkbox" id="mhKMerge" ${k.merge ? 'checked' : ''} ${perScene ? '' : 'disabled'}> Tự ghép khi xong</label></div>` : ''}
        <div class="field" title="Video xong thì bốc ngẫu nhiên 1 bài trong thư mục nhạc nền, lót nhỏ dưới giọng đọc. Giữ cả bản không nhạc."><span>Nhạc nền <button class="link mk-link" data-act="bgm-pick" type="button" title="${esc(H.s.bgm_dir)}">đổi thư mục</button></span>
          <div class="mk-inline"><label class="check mk-check"><input type="checkbox" id="mhKBgm" ${k.bgm ? 'checked' : ''}> Ghép nhạc</label>
            <button class="btn ghost sm" data-act="bgm-open" type="button" title="${esc(H.s.bgm_dir)}">Thư mục</button></div></div>
        <label class="field" title="Muse làm lại N lần để chọn bản đẹp nhất"><span>Số bản / video</span><input id="mhKVersions" type="number" min="1" max="5" value="${k.versions}"></label>
      </div>
      <div class="mk-bottom">
        <div class="mk-drop" id="mhKDrop">
          <div class="mk-drop-text"><b>Ảnh sản phẩm ${script ? '(tuỳ chọn)' : ''}</b>
            <small>Kéo thả hoặc chọn nhiều ảnh: ${script ? 'mỗi ảnh làm ra 1 bộ video riêng' : 'mỗi ảnh = 1 video'}.</small></div>
          ${k.images.length ? `<div class="mh-thumbs">${k.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt="" title="${esc(im.name || '')}"><button data-krm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}</div>
            <button class="link" data-act="k-clear-img" type="button">Bỏ hết</button>` : ''}
          <button class="btn ghost sm" data-act="k-add-img" type="button">Chọn ảnh</button>
        </div>
        <div class="mk-go"><button class="btn ghost" data-act="k-preview" type="button" title="Xem trước nội dung sẽ gửi Muse">Xem lệnh</button>
          <button class="btn primary" data-act="k-queue" type="button">Đưa vào hàng đợi</button></div>
      </div>`;
  }
  function kForm() {
    const k = H.k;
    return { mode: k.mode, text: k.text, method: k.method, ratio: k.ratio, duration: k.duration, prefix: k.prefix, voice: k.voice,
      presenter: k.presenter, character: k.character, merge: k.merge, bgm: k.bgm, versions: k.versions,
      product_images: k.images.map(i => i.path), motions: k.motions, note: k.note };
  }
  function previewDialog(items) {
    openModal('XEM LỆNH', 'Lệnh sẽ gửi Muse', `<div class="mh-preview">${items.map((p, i) => `<div class="mh-prev">
        <b>${i + 1}. ${p.kind === 'image' ? '🖼 Storyboard (ảnh)' : `🎬 Video${p.scene ? ` · cảnh ${p.scene}` : ''} · ${p.duration}s`}</b>
        <small class="muted">${p.images} ảnh đính kèm${p.status === 'waiting' ? ' · chờ storyboard xong' : ''}</small>
        <pre>${esc(p.prompt)}</pre></div>`).join('') || '<div class="empty">Không có lệnh nào</div>'}</div>`);
  }
  function groupStatus(g) {
    if (g.tasks.some(t => t.status === 'review')) return ['warn', 'Chờ duyệt storyboard'];
    if (g.tasks.some(t => t.status === 'processing')) return ['run', 'Đang chạy trên Muse'];
    if (g.status === 'running') return ['', 'Chờ'];
    return [{ done: 'ok', failed: 'bad', running: '', finishing: 'run', cancelled: '' }[g.status] || '', GSTATUS[g.status] || g.status];
  }

  // nhóm lọc: Chờ / Đang làm / Xong / Lỗi
  function renderGroups() {
    const box = $('#mhGroups');
    if (!box) return;
    const G = H.g;
    const all = projGroups();
    const ids = new Set(all.map(g => g.id));
    [...G.sel].forEach(id => { if (!ids.has(id)) G.sel.delete(id); });
    if (G.cur && !ids.has(G.cur)) G.cur = null;
    const list = all.filter(g => G.filter === 'all' || gcat(g) === G.filter);
    const count = k => (k === 'all' ? all.length : all.filter(g => gcat(g) === k).length);
    const mark = t => ({ succeeded: '✓', failed: '✕', processing: '▶', review: '?', cancelled: '–' }[t.status] || '·');
    $('#mhGBar').innerHTML = `<div class="mh-chips">${GFILTERS.map(([k, l]) => `<button class="chip-f ${G.filter === k ? 'active' : ''}" data-gfilter="${k}" type="button">${l} <span>${count(k)}</span></button>`).join('')}</div>
      <span class="mh-top-sp"></span>
      <button class="btn ghost sm" data-act="g-clear-done" type="button" ${all.some(g => g.status === 'done') ? '' : 'disabled'}>Bỏ video đã xong</button>
      <button class="btn ghost sm" data-act="folder" type="button">Thư mục video</button>`;
    box.innerHTML = `<div class="mk-thead"><span>#</span><span>Video</span><span>Trạng thái</span><span>Thao tác</span></div>
      <div class="mk-rows">${list.length ? list.map((g, i) => { const [lvl, txt] = groupStatus(g); return `<div class="mk-row ${G.cur === g.id ? 'on' : ''}" data-gcur="${esc(g.id)}">
          <span class="mk-num"><input type="checkbox" data-gsel="${esc(g.id)}" ${G.sel.has(g.id) ? 'checked' : ''}><b class="mk-no">${gNo(g) || i + 1}</b></span>
          <div class="mk-video">${g.storyboard ? `<img class="mk-thumb" src="${esc(g.storyboard.url)}" alt="">` : `<span class="mk-thumb ph">${g.mode === 'image' ? '🖼' : '🎬'}</span>`}
            <div class="mh-tbody"><p><b>${esc(g.title)}</b>${g.versions > 1 ? ` <small class="muted">· bản ${g.version}/${g.versions}</small>` : ''}</p>
              <small>${esc(g.ratio)} · ${esc(g.duration === 'per_scene' ? 'từng cảnh 10s' : `${g.duration}s`)}${g.bgm ? ' · 🎵' : ''}</small>
              <div class="mh-gsteps">${g.tasks.map(t => `<span class="mh-gstep ${esc(t.status)}">${t.role === 'storyboard' ? 'SB' : t.scene ? `C${t.scene}` : 'V'} ${mark(t)}</span>`).join('')}</div></div></div>
          <span><span class="mh-pill ${lvl}">${esc(txt)}</span></span>
          <span class="mk-acts">${g.tasks.some(t => t.status === 'review') ? `<button class="btn primary sm" data-gapprove="${esc(g.id)}" type="button">Duyệt</button>` : ''}
            ${g.outputs.length ? `<button class="btn ghost sm" data-gopen="${esc(g.outputs[0].path)}" type="button" title="Mở thư mục chứa video">Mở</button>` : ''}
            <button class="btn ghost sm st-pdel" data-gdel="${esc(g.id)}" type="button" title="Xoá video này khỏi danh sách (file đã tải vẫn giữ)">Xoá</button></span>
        </div>`; }).join('') : `<div class="mk-empty"><b>${all.length ? 'Không có video khớp bộ lọc' : 'Chưa có video nào'}</b>
          <small>${all.length ? 'Chọn bộ lọc khác ở trên.' : 'Soạn kịch bản ở trên rồi bấm “Đưa vào hàng đợi”.'}</small></div>`}</div>`;
    renderGDetail();
    renderGFoot(all);
  }
  function renderGDetail() {
    const el = $('#mhGDetail');
    if (!el) return;
    const g = H.s.groups.find(x => x.id === H.g.cur);
    if (!g) { el.innerHTML = '<div class="mk-empty"><small>Bấm vào một video trong danh sách để xem chi tiết.</small></div>'; return; }
    const [lvl, txt] = groupStatus(g);
    const tasks = g.tasks.map(t => ({ ...t, ...(H.s.tasks.find(x => x.id === t.id) || {}) }));
    const failed = tasks.filter(t => ['failed', 'cancelled'].includes(t.status)).map(t => t.id);
    const out = g.outputs[0];
    el.innerHTML = `<div class="mk-dhead"><b>${gNo(g) ? `<span class="mk-no">${gNo(g)}</span> ` : ''}${esc(g.title)}</b><span class="mh-pill ${lvl}">${esc(txt)}</span></div>
      <small class="muted">${esc((METHODS.find(m => m[0] === g.method) || ['', 'Từ ảnh'])[1])} · ${esc(g.ratio)} · ${esc(g.duration === 'per_scene' ? 'từng cảnh 10s' : `${g.duration}s`)}${g.bgm ? ' · nhạc nền' : ''} · ${fmt(g.created_at)}</small>
      ${out && out.url ? `<video class="mk-player" src="${esc(out.url)}" controls preload="metadata"></video>`
        : g.storyboard ? `<img class="mk-player zoom" src="${esc(g.storyboard.url)}" alt="" data-zoom="${esc(g.storyboard.url)}">` : ''}
      ${g.outputs.length ? `<div class="mh-gouts">${g.outputs.map(o => `<button class="btn ghost sm" data-gopen="${esc(o.path)}" type="button" title="${esc(o.name)}">📂 ${esc(o.name.length > 34 ? `${o.name.slice(0, 32)}…` : o.name)}</button>`).join('')}</div>` : ''}
      ${g.error ? `<div class="mh-err-box">${esc(g.error)}</div>` : ''}
      ${(g.scenes || []).length ? `<div class="mk-scenes">${g.scenes.map((s, i) => `<div><span>${g.mode === 'image' ? 'Lệnh' : `Cảnh ${i + 1}`}</span><p>${esc(s)}</p></div>`).join('')}</div>` : ''}
      <div class="mk-tasks">${tasks.map(t => `<button class="mk-task" data-task-open="${esc(t.id)}" type="button" title="Xem nhật ký">
          <span class="mh-gstep ${esc(t.status)}">${t.role === 'storyboard' ? 'Storyboard' : t.scene ? `Cảnh ${t.scene}` : 'Video'}</span>
          <span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status] || t.status)}</span>
          ${t.error ? `<small class="mh-err">${esc(t.error.slice(0, 140))}</small>` : ''}</button>`).join('')}</div>
      <div class="ab-row">${g.tasks.some(t => t.status === 'review') ? `<button class="btn primary sm" data-gapprove="${esc(g.id)}" type="button">✓ Duyệt storyboard</button>` : ''}
        ${failed.length ? `<button class="btn ghost sm" data-gretry="${esc(failed.join(','))}" type="button">↻ Chạy lại phần lỗi</button>` : ''}
        <button class="btn ghost sm st-pdel" data-gdel="${esc(g.id)}" type="button">🗑 Xoá video</button></div>`;
  }
  function renderGFoot(all) {
    const el = $('#mhGFoot');
    if (!el) return;
    const n = H.g.sel.size;
    const running = !H.s.stopped && all.some(g => gcat(g) === 'running');
    const left = all.filter(g => ['queued', 'running'].includes(gcat(g))).length;
    el.innerHTML = `<div class="mk-foot-l"><button class="btn ghost sm" data-act="g-sel-all" type="button" ${all.length ? '' : 'disabled'}>Chọn tất cả</button>
        <button class="btn ghost sm" data-act="g-sel-none" type="button" ${n ? '' : 'disabled'}>Bỏ chọn</button>
        <button class="link danger" data-act="g-del-sel" type="button" ${n ? '' : 'disabled'}>Xoá đã chọn (${n})</button>
        <button class="link danger" data-act="g-del-all" type="button" ${all.length ? '' : 'disabled'}>Xoá hết</button></div>
      <div class="mk-foot-c"><button class="link" data-act="stop" type="button" ${running ? '' : 'disabled'}>Dừng</button>
        <button class="btn primary" data-act="resume" type="button">Bắt đầu render trên Muse</button></div>
      <div class="mk-foot-r"><b>${H.s.stopped ? 'Đã dừng' : running ? 'Đang chạy' : 'Chưa chạy'}</b> · ${left ? `${left} video chờ / đang làm` : `${all.length} video`}</div>`;
  }
  async function deleteGroups(ids, label) {
    if (!ids.length || !confirm(`Xoá ${label} khỏi danh sách (file đã tải vẫn giữ)?`)) return;
    for (const id of ids) await api('mhub_group_delete', id);
    ids.forEach(id => H.g.sel.delete(id));
    const st = await api('mhub_state'); if (st.ok) H.s = st.state;
    renderTop(); renderGroups();
  }
  async function dropImages(files) {
    const out = [];
    for (const f of files.filter(x => /^image\/(png|jpeg|webp)$/.test(x.type))) {
      const dataUrl = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r.readAsDataURL(f); });
      const res = await api('mhub_import_data', f.name, dataUrl);
      if (!res.ok) toast(res.error, 'error'); else out.push(...res.images);
    }
    if (!out.length && files.length) toast('Chỉ nhận ảnh PNG / JPG / WEBP', 'warn');
    return out;
  }

  Object.assign(MH, { renderScript, kOutline, kCount, renderKForm, kForm, previewDialog, groupStatus, renderGroups, renderGDetail, renderGFoot, deleteGroups, dropImages });
})();
