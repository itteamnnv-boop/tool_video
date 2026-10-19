/* Nhân vật & Layout cố định — lên ý tưởng, AI viết mô tả, tạo ảnh chân dung / góc mặt / cơ thể / sheet nhân vật,
   phương án layout, sửa ảnh theo lời dặn, ⭐ ảnh dùng cho Studio.
   Dùng chung helper của app.js: $, api, esc, toast, openModal, state, profileOptions, siteOf. */
(() => {
  'use strict';

  const C = { meta: null, tab: 'character', items: { character: [], layout: [], combo: [] }, cur: null, draft: null, dirty: false,
    presets: [], prompts: {}, open: {}, gen: { engine: 'chatgpt_browser', profile: '', show_browser: false, aspect: '9:16', count: 2 },
    text: { model: 'chatgpt_browser', profile: '' }, refine: null, checked: {},
    tasks: [], logs: {}, fetched: {}, sel: '', shown: '' };  // tiến trình: tác vụ cast_, nhật ký theo tác vụ
  const ACTIVE = ['queued', 'running'];
  const TASK_STAGES = {
    image: [['prepare', 'Chuẩn bị'], ['image', 'Tạo ảnh'], ['save', 'Lưu ảnh'], ['finish', 'Hoàn tất']],
    text: [['prepare', 'Chuẩn bị'], ['text', 'AI viết mô tả'], ['save', 'Lưu mô tả'], ['finish', 'Hoàn tất']],
  };
  const TASK_STATUS = { queued: 'Đang chờ', running: 'Đang chạy', done: 'Hoàn tất', error: 'Lỗi', cancelled: 'Đã dừng' };
  const KIND_LABEL = { character: 'Nhân vật', layout: 'Layout', combo: 'Kết hợp' };
  const KINDS = ['character', 'layout', 'combo'];
  const NEW_LABEL = { character: 'Nhân vật mới', layout: 'Layout mới', combo: 'Kết hợp mới' };
  const ICON = { character: '🧑', layout: '🏞', combo: '🎬' };
  const INTRO = {
    character: ['🧑 Nhân vật cố định', 'Tạo nhân vật dùng lại nhiều video: viết ý tưởng → AI viết mô tả cố định → tải ảnh hoặc tạo chân dung → tạo góc mặt, cơ thể, sheet nhân vật (prompt của template “Nhảy theo trend”) → sửa ảnh tới khi ưng → ⭐ ảnh dùng cho Studio.'],
    layout: ['🏞 Layout cố định', 'Tạo bối cảnh cố định: viết ý tưởng (hoặc tải layout mẫu) → AI viết mô tả → chọn thành phần giao diện (TikTok, livestream, giỏ hàng, khung chat…) nếu cần → tạo phương án → sửa ảnh tới khi ưng → ⭐ chốt ảnh.'],
    combo: ['🎬 Kết hợp nhân vật + layout', 'Chọn nhân vật và layout đã có, mô tả hành động / dàn cảnh → tạo ảnh đặt nhân vật vào bối cảnh (ảnh ⭐ của nhân vật và layout gửi kèm) → sửa tới khi ưng → ⭐ chốt. Studio chọn bộ kết hợp là dùng luôn cả nhân vật, layout và ảnh dàn cảnh.'],
  };
  const clone = o => JSON.parse(JSON.stringify(o));

  async function show() {
    if (!C.meta) {
      const res = await api('cast_meta');
      if (!res.ok) return toast(res.error, 'error');
      C.meta = res;
    }
    await loadList();
    const res = await api('cast_tasks');
    if (res.ok) C.tasks = res.tasks;
    render();
  }

  async function loadList() {
    for (const kind of KINDS) {
      const res = await api('cast_list', kind);
      if (res.ok) C.items[kind] = res.items;
    }
    if (C.cur) {
      C.cur = C.items[C.cur.kind].find(x => x.id === C.cur.id) || null;
      if (C.cur && !C.dirty) C.draft = clone(C.cur);
    }
  }

  // ------------------------------------------------------------ khung trang
  function render() {
    const list = C.items[C.tab];
    $('#castBody').innerHTML = `<div class="cs-layout">
      <aside class="card cs-list">
        <div class="cs-tabs">${KINDS.map(k => `<button class="${C.tab === k ? 'on' : ''}" data-tab="${k}" type="button">${KIND_LABEL[k]} <b>${C.items[k].length}</b></button>`).join('')}</div>
        <button class="btn primary cs-new" data-act="new" type="button">+ ${NEW_LABEL[C.tab]}</button>
        ${list.length ? list.map(itemRow).join('') : `<div class="empty">Chưa có ${KIND_LABEL[C.tab].toLowerCase()} nào.</div>`}
      </aside>
      <section class="cs-main">${C.cur && C.cur.kind === C.tab ? editorHtml() : introHtml()}</section></div>`;
    bind();
    paintLive();
  }

  // ------------------------------------------------------------ tiến trình (giống trang Tạo video)
  // tác vụ của mục đang mở (chưa mở mục nào → mọi tác vụ), mới nhất trước
  function myTasks() {
    return C.tasks.filter(t => !C.cur || t.cast === C.cur.id).slice().reverse();
  }

  function liveHtml() {
    const list = myTasks();
    if (!list.length) {
      C.shown = '';
      return `<div class="card st-prog cs-prog"><div class="card-title">TIẾN TRÌNH</div>
        <div class="empty">Chưa có tác vụ — bấm ✨ để AI viết mô tả hoặc tạo ảnh, tiến trình hiện ở đây.</div></div>`;
    }
    const t = list.find(x => x.id === C.sel) || list.find(x => ACTIVE.includes(x.status)) || list[0];
    C.shown = t.id;
    const run = ACTIVE.includes(t.status);
    const stages = TASK_STAGES[String(t.title).startsWith('Mô tả') ? 'text' : 'image'];
    const finished = t.status === 'done';
    const pct = finished ? 100 : Math.round(+t.pct || 0);
    const cur = stages.findIndex(([id]) => id === t.stage);
    const logs = C.logs[t.id] || [];
    const status = t.status === 'error' ? (t.error || 'Lỗi') : t.status === 'queued' ? 'Đang chờ tới lượt' : (t.status_text || '');
    return `<div class="card st-prog cs-prog ${run ? 'running' : ''}">
      <div class="card-title">TIẾN TRÌNH <span class="status-pill mono ${finished ? 'ok' : t.status === 'error' ? 'bad' : ''}">${TASK_STATUS[t.status] || t.status}</span></div>
      ${list.length > 1 ? `<div class="cs-task-tabs">${list.slice(0, 8).map(x => `<button class="${x.id === t.id ? 'on' : ''}" data-task="${esc(x.id)}" type="button" title="${esc(x.title)}">
        <i class="cs-dot ${esc(x.status)}"></i>${esc(String(x.title).split(' · ')[0])}</button>`).join('')}</div>` : ''}
      <div class="cs-task-title">${esc(t.title)}</div>
      <div class="stepper st-stepper">${stages.map(([id, label], i) =>
        `<div class="step ${finished || i < cur ? 'done' : ''} ${run && i === cur ? 'active' : ''}"><i></i><span>${label}</span></div>`).join('')}</div>
      <div class="progress"><div class="bar"><i style="width:${pct}%"></i></div><span class="mono">${pct}%</span></div>
      ${status ? `<div class="status-box ${t.status === 'error' ? 'bad' : ''}">${esc(status)}</div>` : ''}
      <div class="log-card"><div class="log-head"><span>NHẬT KÝ XỬ LÝ</span>
        ${run ? `<button class="link" data-stop="${esc(t.id)}" type="button">■ Dừng</button>` : `<span class="muted mono">${logs.length} dòng</span>`}</div>
        <div class="log mono st-log">${logs.map(l => `<div class="ln ${esc(l.level || 'info')}">${esc(l.time || '')} ${esc(l.message)}</div>`).join('') || '<div class="ln muted">Chưa có nhật ký</div>'}</div></div>
    </div>`;
  }

  // vẽ lại riêng thẻ tiến trình (không vẽ lại cả trang → không mất chữ đang gõ)
  function paintLive() {
    const box = $('#csLive');
    if (!box) return;
    box.innerHTML = liveHtml();
    const lg = box.querySelector('.st-log');
    if (lg) lg.scrollTop = lg.scrollHeight;
    const id = C.shown;
    if (id && !C.fetched[id]) {  // tác vụ chạy từ trước khi mở trang → lấy đủ nhật ký một lần
      C.fetched[id] = true;
      api('cast_task_logs', id).then(r => { if (r.ok) { C.logs[id] = r.logs; if (C.shown === id) paintLive(); } });
    }
  }

  function itemRow(x) {
    const thumb = (x.starred[0] || x.images.find(i => i.exists) || {}).url;
    return `<button class="cs-item ${C.cur && C.cur.id === x.id ? 'on' : ''}" data-open="${esc(x.id)}" type="button">
      <span class="cs-thumb">${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy">` : ICON[x.kind]}</span>
      <span class="cs-item-text"><b>${esc(x.name)}</b><small>${esc((x.summary || x.idea || 'Chưa có mô tả').slice(0, 70))}</small>
        <small>⭐ ${x.starred.length} ảnh dùng cho Studio${x.pending.length ? ` · <span class="cs-spin">⏳ ${x.pending.length}</span>` : ''}</small></span></button>`;
  }

  function introHtml() {
    return `<div class="cs-work">
      <div class="card cs-intro">
        <h3>${INTRO[C.tab][0]}</h3>
        <p class="muted">${INTRO[C.tab][1]}</p>
        <p class="muted">Ở Studio → ⚙ Cài đặt dự án → <b>Nhân vật &amp; layout cố định</b> để dùng (hoặc không).</p>
        <button class="btn primary" data-act="new" type="button">+ ${NEW_LABEL[C.tab]}</button></div>
      <aside class="cs-side"><div id="csLive"></div></aside></div>`;
  }

  // cột phải: tiến trình + ảnh ⭐ đang dùng cho Studio
  function sideHtml(x) {
    const st = x.starred;
    return `<aside class="cs-side"><div id="csLive"></div>
      <div class="card cs-starbox"><div class="card-title">⭐ DÙNG CHO STUDIO <small class="muted">${st.length} ảnh</small></div>
        ${st.length ? `<div class="cs-stars">${st.slice(0, 6).map(im => `<button class="cs-img" data-view="${esc(im.url)}" type="button" title="${esc(im.label || '')}"><img src="${esc(im.url)}" alt=""></button>`).join('')}</div>`
          : '<small class="muted">Chưa chốt ảnh nào — bấm ⭐ trên ảnh ở mục Ảnh đã tạo.</small>'}</div></aside>`;
  }

  // ------------------------------------------------------------ trình sửa
  function textModelSelect() {
    const models = C.meta.text_models;
    const m = models.find(x => x.id === C.text.model) || models[0];
    return `<label class="field"><span>Model viết mô tả</span><select data-text="model">${models.map(x => `<option value="${esc(x.id)}" ${x.id === C.text.model ? 'selected' : ''}>${esc(x.name)}${x.ready ? '' : ' — chưa có khoá'}</option>`).join('')}</select></label>
      ${m && m.site && state.profiles && (state.profileSites || {})[m.site] ? `<label class="field"><span>Profile</span><select data-text="profile">${profileOptions(m.site, C.text.profile)}</select></label>` : ''}`;
  }

  function engineRow(layout) {
    const eng = C.meta.image_engines[C.gen.engine] || {};
    return `<div class="cs-gen-row">
      <label class="field"><span>Model tạo ảnh</span><select data-gen="engine">${Object.entries(C.meta.image_engines).map(([k, v]) => `<option value="${esc(k)}" ${k === C.gen.engine ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></label>
      ${eng.browser && state.profiles && (state.profileSites || {})[siteOf(C.gen.engine)] ? `<label class="field"><span>Profile</span><select data-gen="profile">${profileOptions(siteOf(C.gen.engine), C.gen.profile)}</select></label>` : ''}
      ${layout ? `<label class="field"><span>Tỉ lệ</span><select data-gen="aspect">${(eng.aspects || ['9:16']).map(a => `<option ${a === C.gen.aspect ? 'selected' : ''}>${a}</option>`).join('')}</select></label>
        <label class="field"><span>Số phương án</span><select data-gen="count">${(eng.counts || [1]).map(n => `<option ${String(n) === String(C.gen.count) ? 'selected' : ''}>${n}</option>`).join('')}</select></label>` : ''}
      <label class="check"><input type="checkbox" data-gen="show_browser" ${C.gen.show_browser ? 'checked' : ''}> Hiện Chrome</label></div>`;
  }

  // Bộ kết hợp: chọn nhân vật (tối đa N) + 1 layout từ danh sách đã có
  function membersHtml(d) {
    const max = C.meta.max_combo_chars || 3;
    const chars = d.characters || [];
    const chip = (x, on, attr, disabled) => `<button class="st-cast-chip ${on ? 'on' : ''}" ${attr}="${esc(x.id)}" type="button" ${disabled ? 'disabled' : ''}>
      ${(x.starred[0] || {}).url ? `<img src="${esc(x.starred[0].url)}" alt="">` : `<i>${ICON[x.kind]}</i>`}${esc(x.name)}${on ? ' ✓' : ''}${x.starred.length ? '' : ' <small class="warn-text">chưa có ảnh ⭐</small>'}</button>`;
    const products = C.cur.products || [];
    const maxP = C.meta.max_products || 3;
    return `<div class="card cs-step"><div class="card-title"><span class="cs-n">1</span> CHỌN NHÂN VẬT, LAYOUT &amp; SẢN PHẨM</div>
      <span class="muted">Nhân vật (tối đa ${max}) — ảnh ⭐ của mỗi nhân vật được gửi kèm:</span>
      <div class="st-cast-row">${C.items.character.map(x => chip(x, chars.includes(x.id), 'data-member-char', !chars.includes(x.id) && chars.length >= max)).join('')
        || '<small class="muted">Chưa có nhân vật — tạo ở tab Nhân vật.</small>'}</div>
      <span class="muted">Layout / bối cảnh (1):</span>
      <div class="st-cast-row">${C.items.layout.map(x => chip(x, d.layout === x.id, 'data-member-layout', false)).join('')
        || '<small class="muted">Chưa có layout — tạo ở tab Layout.</small>'}</div>
      <span class="muted">Ảnh sản phẩm (tuỳ chọn, tối đa ${maxP}) — nhân vật cầm / giới thiệu đúng sản phẩm này; giữ nguyên bao bì, nhãn, logo:</span>
      <div class="cs-products">${products.map(im => `<div class="cs-prod" data-img="${esc(im.name)}">
          <button class="cs-img" data-view="${esc(im.url)}" type="button" title="Xem lớn"><img src="${esc(im.url)}" alt=""></button>
          <button class="cs-prod-del" data-del-img type="button" title="Bỏ ảnh sản phẩm">✕</button></div>`).join('')}
        ${products.length < maxP ? '<button class="cs-prod cs-prod-add" data-act="upload-product" type="button"><b>+</b><small>Chọn ảnh sản phẩm</small></button>' : ''}</div>
      <small class="muted">Studio dùng bộ kết hợp này cũng gửi kèm ảnh sản phẩm (tối đa 2) khi tạo ảnh khung đầu.</small></div>`;
  }

  // Layout: thành phần giao diện mạng xã hội (tick) + tên kênh + bình luận thật của khách
  function uiHtml(d) {
    const ui = d.ui || {}, on = ui.elements || [];
    return `<div class="card cs-step"><div class="card-title"><span class="cs-n">3</span> THÀNH PHẦN GIAO DIỆN <small class="muted">— tuỳ chọn: phủ giao diện mạng xã hội lên bối cảnh</small></div>
      <div class="cs-ui">${(C.meta.ui_elements || []).map(e => `<label class="check"><input type="checkbox" data-ui-el="${e.key}" ${on.includes(e.key) ? 'checked' : ''}> ${esc(e.label)}</label>`).join('')}</div>
      ${on.length ? `<div class="grid2"><label class="field"><span>Tên kênh / trang (hiện trên giao diện)</span><input data-ui="channel" value="${esc(ui.channel || '')}" placeholder="VD: Phân bón KF"></label>
        <label class="field"><span>Bình luận thật của khách (mỗi dòng 1 bình luận, tối đa 8)</span><textarea data-ui="comments" rows="3" placeholder="VD: Còn hàng không shop?&#10;Ship về Cần Thơ được không ạ?">${esc(ui.comments || '')}</textarea></label></div>
        <small class="muted">Chỉ dùng bình luận thật — để trống thì chữ trong bong bóng sẽ mờ, không đọc được; app không tự bịa bình luận, lượt thích hay số người xem. Icon vẽ theo phong cách của các ứng dụng (model có thể không vẽ đúng logo). Khi dùng ở Studio, bỏ tick “Không chữ / Không logo” trong Ràng buộc prompt để giữ giao diện.</small>` : ''}
    </div>`;
  }

  function editorHtml() {
    const d = C.draft, x = C.cur, char = x.kind === 'character', combo = x.kind === 'combo';
    if (combo) return comboHtml(d, x);
    const base = x.images.filter(i => i.kind === 'base');
    const others = x.images.filter(i => i.kind !== 'base');
    return `${heroHtml(d, x)}<div class="cs-work"><div class="cs-col">
      <div class="card cs-step"><div class="card-title"><span class="cs-n">1</span> Ý TƯỞNG &amp; MÔ TẢ CỐ ĐỊNH</div>
        <label class="field"><span>Ý tưởng (tiếng Việt, viết tự nhiên)</span><textarea data-d="idea" rows="3" placeholder="${char
          ? 'VD: Cô giáo tiếng Anh trẻ 27 tuổi, dễ thương, tóc dài đen buộc nửa đầu, hay mặc áo len pastel…'
          : 'VD: Lớp học mầm non tươi sáng, tường pastel, bảng trắng ở giữa, kệ thú bông bên phải, ánh sáng sáng sớm…'}">${esc(d.idea || '')}</textarea></label>
        <div class="cs-gen-row">${textModelSelect()}
          <button class="btn primary" data-act="describe" type="button" ${x.pending.some(p => p.label.startsWith('AI')) ? 'disabled' : ''}>✨ AI viết mô tả</button></div>
        <label class="field"><span>Mô tả cố định (tiếng Anh) — Studio chép nguyên vào storyboard và prompt ảnh</span><textarea data-d="description" rows="5" placeholder="Bấm ✨ AI viết mô tả hoặc tự viết">${esc(d.description || '')}</textarea></label>
        <label class="field"><span>Tóm tắt (tiếng Việt)</span><input data-d="summary" value="${esc(d.summary || '')}"></label>
      </div>
      ${char ? `<div class="card cs-step"><div class="card-title"><span class="cs-n">2</span> ẢNH GỐC <small class="muted">— khuôn mặt chuẩn để tạo các góc</small></div>
        <div class="cs-gallery">${base.map(tile).join('')}${pendingTiles('Chân dung')}</div>
        <div class="row cs-acts"><button class="btn ghost" data-act="upload" type="button">⬆ Tải ảnh lên</button>
          <button class="btn ghost" data-gen-preset="portrait" type="button">✨ Tạo chân dung từ mô tả</button></div>
        ${engineRow(false)}</div>` : ''}
      ${char ? '' : `<div class="card cs-step"><div class="card-title"><span class="cs-n">2</span> LAYOUT MẪU <small class="muted">— tuỳ chọn: tải ảnh mẫu lên để dùng ngay, hoặc để AI tạo phương án bám theo bố cục mẫu</small></div>
        ${base.length ? `<div class="cs-gallery">${base.map(tile).join('')}</div>` : ''}
        <div class="row cs-acts"><button class="btn ghost" data-act="upload" type="button">⬆ Tải layout mẫu lên</button>
          <small class="muted">${base.length ? `${base.length} ảnh mẫu — ⭐ ảnh mẫu thì Studio dùng luôn; phương án tạo mới sẽ giữ bố cục của ảnh mẫu.` : 'PNG / JPG / WEBP — ảnh bối cảnh, bố cục, moodboard…'}</small></div></div>`}
      ${char ? '' : uiHtml(d)}
      <div class="card cs-step"><div class="card-title"><span class="cs-n">${char ? 3 : 4}</span> ${char ? 'GÓC MẶT, CƠ THỂ &amp; SHEET NHÂN VẬT' : 'PHƯƠNG ÁN LAYOUT'}</div>
        ${char ? presetsHtml() : `${engineRow(true)}${layoutPromptHtml()}
          <button class="btn primary" data-gen-preset="layout" type="button">✨ Tạo phương án</button>`}
      </div></div>${sideHtml(x)}</div>
      ${galleryHtml(others, char ? 4 : 5)}`;
  }

  function galleryHtml(images, n) {
    return `<div class="card cs-step"><div class="card-title"><span class="cs-n">${n}</span> ẢNH ĐÃ TẠO <small class="muted">— ⭐ = dùng cho Studio · ✎ = sửa ảnh theo lời dặn</small></div>
      ${images.length || pendingTiles() ? `<div class="cs-gallery">${pendingTiles(null, 'Chân dung')}${[...images].reverse().map(tile).join('')}</div>` : '<div class="empty">Chưa có ảnh.</div>'}
    </div>`;
  }

  function heroHtml(d, x) {
    const thumb = (x.starred[0] || x.images.find(i => i.exists && i.kind !== 'product') || {}).url;
    const chip = (icon, text) => `<span class="cs-chip">${icon} ${text}</span>`;
    return `<div class="card cs-hero">
        <div class="cs-hero-top">
          <span class="cs-hero-thumb">${thumb ? `<img src="${esc(thumb)}" alt="">` : ICON[x.kind]}</span>
          <div class="cs-hero-name"><input id="csName" value="${esc(d.name)}" aria-label="Tên">
            <div class="cs-chips"><span class="tag">${KIND_LABEL[x.kind]}</span>
              ${chip('⭐', `${x.starred.length} ảnh dùng cho Studio`)}${chip('🖼', `${x.images.filter(i => i.kind !== 'product').length} ảnh`)}
              ${x.kind === 'combo' ? chip('📦', `${(x.products || []).length} sản phẩm`) : ''}
              ${x.pending.length ? `<span class="cs-chip run">⏳ ${x.pending.length} đang chạy <button class="link" data-act="cancel-all" type="button">Dừng</button></span>` : ''}</div></div>
          <div class="cs-hero-act">
            ${C.dirty ? '<button class="btn primary sm" data-act="save" type="button">💾 Lưu</button>' : '<small class="muted">Đã lưu</small>'}
            <button class="icon-btn" data-act="duplicate" type="button" title="Nhân bản">⧉</button>
            <button class="icon-btn cs-del" data-act="delete" type="button" title="Xoá">🗑</button></div></div>
        ${x.error ? `<div class="camp-banner bad">${esc(x.error)}</div>` : ''}
      </div>`;
  }

  function comboHtml(d, x) {
    return `${heroHtml(d, x)}<div class="cs-work"><div class="cs-col">${membersHtml(d)}
      <div class="card cs-step"><div class="card-title"><span class="cs-n">2</span> HÀNH ĐỘNG / DÀN CẢNH</div>
        <label class="field"><span>Ý tưởng (tiếng Việt)</span><textarea data-d="idea" rows="3" placeholder="VD: Sale KF đứng giữa vườn, tay cầm bao phân, tươi cười giới thiệu, nhìn thẳng ống kính">${esc(d.idea || '')}</textarea></label>
        <div class="cs-gen-row">${textModelSelect()}
          <button class="btn primary" data-act="describe" type="button" ${x.pending.some(p => p.label.startsWith('AI')) ? 'disabled' : ''}>✨ AI viết dàn cảnh</button></div>
        <label class="field"><span>Dàn cảnh (tiếng Anh) — vị trí, tư thế, hành động, góc máy</span><textarea data-d="description" rows="4" placeholder="Bấm ✨ AI viết dàn cảnh hoặc tự viết (để trống thì dùng ý tưởng)">${esc(d.description || '')}</textarea></label>
        <label class="field"><span>Tóm tắt (tiếng Việt)</span><input data-d="summary" value="${esc(d.summary || '')}"></label>
      </div>
      <div class="card cs-step"><div class="card-title"><span class="cs-n">3</span> TẠO ẢNH KẾT HỢP</div>
        ${engineRow(true)}${layoutPromptHtml('combo')}
        <button class="btn primary" data-gen-preset="combo" type="button">✨ Tạo ảnh kết hợp</button></div>
      </div>${sideHtml(x)}</div>
      ${galleryHtml(x.images.filter(i => i.kind !== 'product'), 4)}`;
  }

  function presetsHtml() {
    const rows = C.presets.filter(p => p.key !== 'portrait');
    return `<div class="cs-presets">${rows.map(p => `<div class="cs-preset">
        <label class="check"><input type="checkbox" data-check="${p.key}" ${C.checked[p.key] ? 'checked' : ''}> <b>${esc(p.label)}</b></label>
        <span class="tag">${esc(p.aspect)}</span>${p.custom || C.prompts[p.key] !== undefined ? '<span class="tag cs-custom">đã sửa prompt</span>' : ''}
        <button class="link" data-toggle="${p.key}" type="button">${C.open[p.key] ? 'Ẩn prompt' : '✎ Prompt'}</button>
        <button class="btn ghost sm" data-gen-preset="${p.key}" type="button">Tạo</button>
        ${C.open[p.key] ? `<textarea class="cs-prompt" data-prompt="${p.key}" rows="${p.key === 'sheet' ? 12 : 5}">${esc(C.prompts[p.key] ?? p.prompt)}</textarea>
          <div class="row cs-prompt-act"><button class="link" data-reset="${p.key}" type="button">↺ Prompt mẫu</button><small class="muted">Prompt sửa được lưu cùng nhân vật khi bấm 💾 Lưu.</small></div>` : ''}
      </div>`).join('')}</div>
      <div class="row cs-acts"><button class="btn primary" data-act="gen-checked" type="button">✨ Tạo các góc đã tick (${Object.values(C.checked).filter(Boolean).length})</button>
        <small class="muted">Các góc dùng ảnh gốc làm tham chiếu khuôn mặt; mỗi góc là 1 tác vụ trong hàng đợi Tạo hình ảnh (dùng model ở bước 2).</small></div>`;
  }

  function layoutPromptHtml(key = 'layout') {
    const p = C.presets[0] || { prompt: '' };
    return `<div class="cs-preset"><b>${key === 'combo' ? 'Prompt tạo ảnh kết hợp' : 'Prompt tạo phương án'}</b>
      <button class="link" data-toggle="${key}" type="button">${C.open[key] ? 'Ẩn prompt' : '✎ Xem / sửa prompt'}</button>
      ${C.open[key] ? `<textarea class="cs-prompt" data-prompt="${key}" rows="${key === 'combo' ? 9 : 6}">${esc(C.prompts[key] ?? p.prompt)}</textarea>` : ''}</div>`;
  }

  // ô “đang tạo”: only = chỉ nhãn bắt đầu bằng chuỗi này; skip = bỏ nhãn bắt đầu bằng chuỗi này
  function pendingTiles(only, skip) {
    return C.cur.pending.filter(p => !p.label.startsWith('AI') && (!only || p.label.startsWith(only)) && (!skip || !p.label.startsWith(skip)))
      .map(p => `<div class="cs-tile pending"><span>⏳</span><small>${esc(p.label)}</small></div>`).join('');
  }

  function tile(im) {
    const char = C.cur.kind === 'character';
    return `<div class="cs-tile ${im.starred ? 'star' : ''}" data-img="${esc(im.name)}">
      <button class="cs-img" data-view="${esc(im.url)}" type="button" title="Xem lớn">${im.exists ? `<img src="${esc(im.url)}" alt="" loading="lazy">` : '<span>Thiếu file</span>'}</button>
      <small class="cs-tile-label" title="${esc(im.prompt || '')}">${esc(im.label || '')}</small>
      <div class="cs-tile-act">
        <button class="${im.starred ? 'on' : ''}" data-star type="button" title="${im.starred ? 'Bỏ khỏi Studio' : 'Dùng cho Studio'}">⭐</button>
        ${char ? `<button class="${im.kind === 'base' ? 'on' : ''}" data-base type="button" title="${im.kind === 'base' ? 'Bỏ khỏi ảnh gốc' : 'Dùng làm ảnh gốc (tham chiếu khuôn mặt)'}">👤</button>` : ''}
        <button data-refine type="button" title="Sửa ảnh theo lời dặn">✎</button>
        <button data-del-img type="button" title="Xoá ảnh">🗑</button></div>
      ${C.refine === im.name ? `<div class="cs-refine"><textarea data-refine-text rows="2" placeholder="VD: tóc dài hơn, mặc áo len màu kem, cười tươi hơn…"></textarea>
        <div class="row"><button class="btn ghost sm" data-refine-cancel type="button">Huỷ</button><button class="btn primary sm" data-refine-go type="button">✨ Sửa ảnh</button></div></div>` : ''}
    </div>`;
  }

  // ------------------------------------------------------------ sự kiện
  // gõ chữ: đánh dấu chưa lưu nhưng không vẽ lại (giữ con trỏ) — chỉ đổi chữ “Đã lưu” thành nút Lưu
  function markDirtySoft() {
    if (C.dirty) return;
    C.dirty = true;
    const hint = $('#castBody .cs-hero-top small.muted');
    if (hint) hint.outerHTML = '<button class="btn primary sm" data-act="save" type="button">💾 Lưu</button>';
  }

  async function save(quiet) {
    const d = C.draft;
    const res = await api('cast_save', C.cur.kind, C.cur.id, { name: d.name, idea: d.idea, description: d.description,
      summary: d.summary, ...(C.cur.kind === 'character' ? { prompts: C.prompts } : {}),
      ...(C.cur.kind === 'combo' ? { characters: d.characters || [], layout: d.layout || '' } : {}),
      ...(C.cur.kind === 'layout' ? { ui: d.ui || {} } : {}) });
    if (!res.ok) { toast(res.error, 'error'); return false; }
    C.cur = res.item; C.draft = clone(res.item); C.dirty = false;
    await loadList(); await loadPresets(); render();
    if (!quiet) toast('Đã lưu', 'ok');
    return true;
  }

  async function open(id) {
    if (C.dirty && !confirm('Có thay đổi chưa lưu — bỏ thay đổi?')) return;
    C.cur = C.items[C.tab].find(x => x.id === id) || null;
    C.draft = C.cur ? clone(C.cur) : null;
    C.dirty = false; C.refine = null; C.open = {}; C.checked = {};
    C.prompts = C.cur ? { ...(C.cur.prompts || {}) } : {};
    await loadPresets();
    render();
  }

  async function loadPresets() {
    if (!C.cur) return;
    const res = await api('cast_presets', C.cur.kind, C.cur.id);
    C.presets = res.ok ? res.presets : [];
  }

  async function generate(preset, extra = {}) {
    if (C.dirty && !(await save(true))) return false;
    const layout = C.cur.kind !== 'character';  // layout + kết hợp: chọn tỉ lệ, số ảnh
    const req = { preset, prompt: preset === 'refine' ? '' : (C.prompts[preset] ?? ''), engine: C.gen.engine,
      profile: C.gen.profile, show_browser: C.gen.show_browser, aspect: layout ? C.gen.aspect : undefined,
      count: layout ? +C.gen.count : 1, ...extra };
    const res = await api('cast_generate', C.cur.kind, C.cur.id, req);
    if (!res.ok) { toast(res.error, 'error'); return false; }
    if (res.task) { C.sel = res.task; paintLive(); }  // thẻ Tiến trình theo tác vụ vừa giao
    return true;
  }

  function bind() {
    const root = $('#castBody');
    root.oninput = e => {
      const t = e.target;
      if (t.id === 'csName') { C.draft.name = t.value; markDirtySoft(); }
      else if (t.dataset.d) { C.draft[t.dataset.d] = t.value; markDirtySoft(); }
      else if (t.dataset.prompt) { C.prompts[t.dataset.prompt] = t.value; if (C.cur.kind === 'character') markDirtySoft(); }
      else if (t.dataset.ui) { C.draft.ui = { ...(C.draft.ui || {}), [t.dataset.ui]: t.value }; markDirtySoft(); }
    };
    root.onchange = e => {
      const t = e.target;
      if (t.dataset.text) { C.text[t.dataset.text] = t.value; if (t.dataset.text === 'model') { C.text.profile = ''; render(); } }
      else if (t.dataset.gen) {
        C.gen[t.dataset.gen] = t.type === 'checkbox' ? t.checked : t.value;
        if (t.dataset.gen === 'engine') { C.gen.profile = ''; render(); }
      } else if (t.dataset.check) { C.checked[t.dataset.check] = t.checked; render(); }
      else if (t.dataset.uiEl) {  // layout: bật / tắt thành phần giao diện
        const ui = { ...(C.draft.ui || {}) };
        const set = new Set(ui.elements || []);
        if (t.checked) set.add(t.dataset.uiEl); else set.delete(t.dataset.uiEl);
        C.draft.ui = { ...ui, elements: (C.meta.ui_elements || []).map(e => e.key).filter(k => set.has(k)) };
        C.dirty = true; render();
      }
    };
    root.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.tab) {
        if (C.dirty && !confirm('Có thay đổi chưa lưu — bỏ thay đổi?')) return;
        C.tab = t.dataset.tab; C.cur = null; C.dirty = false; return render();
      }
      if (t.dataset.open) return open(t.dataset.open);
      if (t.dataset.task) { C.sel = t.dataset.task; return paintLive(); }
      if (t.dataset.stop) { await api('cast_cancel', t.dataset.stop); return toast('Đang dừng…', 'warn'); }
      if (t.dataset.view) return openModal('ẢNH', C.cur.name, `<div class="viewer"><img src="${esc(t.dataset.view)}" alt=""></div>`, true);
      if (t.dataset.memberChar !== undefined || t.dataset.memberLayout !== undefined) {  // bộ kết hợp: chọn thành viên
        const d = C.draft;
        if (t.dataset.memberChar !== undefined) {
          const set = new Set(d.characters || []);
          if (set.has(t.dataset.memberChar)) set.delete(t.dataset.memberChar);
          else if (set.size < (C.meta.max_combo_chars || 3)) set.add(t.dataset.memberChar);
          d.characters = [...set];
        } else d.layout = d.layout === t.dataset.memberLayout ? '' : t.dataset.memberLayout;
        C.dirty = true; return render();
      }
      if (t.dataset.toggle) { C.open[t.dataset.toggle] = !C.open[t.dataset.toggle]; return render(); }
      if (t.dataset.reset) { delete C.prompts[t.dataset.reset]; C.dirty = true; return render(); }
      if (t.dataset.genPreset) {
        t.disabled = true;
        if (await generate(t.dataset.genPreset)) toast('Đã giao tạo ảnh — xem Tiến trình bên phải', 'ok');
        t.disabled = false;
        return;
      }
      const tileEl = t.closest('[data-img]');
      const name = tileEl && tileEl.dataset.img;
      if (name && (t.dataset.star !== undefined || t.dataset.base !== undefined || t.dataset.delImg !== undefined)) {
        const im = C.cur.images.find(i => i.name === name);
        if (t.dataset.delImg !== undefined && !confirm('Xoá ảnh này?')) return;
        const opts = t.dataset.star !== undefined ? { starred: !im.starred }
          : t.dataset.base !== undefined ? { base: im.kind !== 'base' } : { remove: true };
        const res = await api('cast_set_image', C.cur.kind, C.cur.id, name, opts);
        if (!res.ok) return toast(res.error, 'error');
        return applyItem(res.item, true);
      }
      if (name && t.dataset.refine !== undefined) { C.refine = name; render(); const ta = $('[data-refine-text]'); if (ta) ta.focus(); return; }
      if (t.dataset.refineCancel !== undefined) { C.refine = null; return render(); }
      if (t.dataset.refineGo !== undefined) {
        const instruction = ($('[data-refine-text]') || {}).value || '';
        const im = C.cur.images.find(i => i.name === C.refine) || {};
        const aspect = im.preset === 'sheet' ? '16:9' : ['face_front', 'face_34', 'face_side', 'expressions', 'portrait'].includes(im.preset) ? '1:1'
          : C.cur.kind === 'layout' ? C.gen.aspect : '9:16';
        if (await generate('refine', { source: C.refine, instruction, aspect, count: 1 })) {
          C.refine = null; render(); toast('Đang sửa ảnh — ảnh mới hiện ở đầu danh sách', 'ok');
        }
        return;
      }
      const act = t.dataset.act;
      if (act === 'new') {
        if (C.dirty && !confirm('Có thay đổi chưa lưu — bỏ thay đổi?')) return;
        const res = await api('cast_create', C.tab, {});
        if (!res.ok) return toast(res.error, 'error');
        C.dirty = false; await loadList(); return open(res.item.id);
      }
      if (act === 'save') return save();
      if (act === 'duplicate') {
        const res = await api('cast_duplicate', C.cur.kind, C.cur.id);
        if (!res.ok) return toast(res.error, 'error');
        await loadList(); return open(res.item.id);
      }
      if (act === 'delete') {
        if (!confirm(`Xoá ${KIND_LABEL[C.cur.kind].toLowerCase()} “${C.cur.name}” và toàn bộ ảnh? Dự án Studio đang dùng sẽ bỏ qua mục này.`)) return;
        await api('cast_delete', C.cur.kind, C.cur.id); C.cur = null; C.dirty = false; await loadList(); return render();
      }
      if (act === 'upload' || act === 'upload-product') {
        const res = await api('cast_add_photos', C.cur.kind, C.cur.id, null, act === 'upload-product' ? 'product' : '');
        if (!res.ok) return toast(res.error, 'error');
        if (res.item) applyItem(res.item, true);
        return;
      }
      if (act === 'describe') {
        if (C.dirty && !(await save(true))) return;
        const res = await api('cast_describe', C.cur.kind, C.cur.id, { model: C.text.model, profile: C.text.profile, show_browser: C.gen.show_browser });
        if (!res.ok) return toast(res.error, 'error');
        if (res.task) { C.sel = res.task; paintLive(); }
        return toast('AI đang viết mô tả — xem Tiến trình bên phải', 'ok');
      }
      if (act === 'gen-checked') {
        const keys = Object.keys(C.checked).filter(k => C.checked[k]);
        if (!keys.length) return toast('Tick các góc muốn tạo', 'warn');
        let ok = 0;
        for (const k of keys) if (await generate(k)) ok += 1;
        if (ok) toast(`Đã giao tạo ${ok} góc — xem Tiến trình bên phải`, 'ok');
        return;
      }
      if (act === 'cancel-all') { for (const p of C.cur.pending) await api('cast_cancel', p.task); toast('Đang dừng…', 'warn'); }
    };
  }

  // cập nhật 1 mục (từ máy chủ); đang gõ thì chưa vẽ lại để không mất con trỏ
  function applyItem(item, force) {
    const list = C.items[item.kind];
    const i = list.findIndex(x => x.id === item.id);
    if (i >= 0) list[i] = item; else list.unshift(item);
    if (C.cur && C.cur.id === item.id) {
      C.cur = item;
      if (!C.dirty) C.draft = clone(item);
    }
    if ($('#page-cast').classList.contains('hidden')) return;
    const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest('#castBody textarea, #castBody input[type=text], #castBody input:not([type])');
    if (force || !typing) render();
  }

  // ------------------------------------------------------------ sự kiện backend (cast_*)
  function update(event, data) {
    if (event === 'cast_tasks') { C.tasks = data.tasks || []; return paintLive(); }
    if (event === 'cast_log') {
      (C.logs[data.task] || (C.logs[data.task] = [])).push(data);
      if (data.task === C.shown) paintLive();
      return;
    }
    if (event === 'cast_progress') {
      const t = C.tasks.find(x => x.id === data.task);
      if (t) Object.assign(t, { pct: data.pct, status_text: data.status, stage: data.stage });
      if (data.task === C.shown) paintLive();
      return;
    }
    if (event === 'cast_update') {
      if (C.cur && C.cur.id === data.id && !C.dirty) { loadPresets().then(() => applyItem(data)); return; }
      return applyItem(data);
    }
    if (event === 'cast_error') toast(`Nhân vật & Layout: ${data.message}`, 'error');
    if (event === 'cast_done' && data.result && data.result.added) toast(`Đã tạo xong ${data.result.added} ảnh`, 'ok');
  }

  window.CastPage = {
    show, update,
    async items() { await loadList(); return C.items; },
  };
})();
