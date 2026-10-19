/* Studio Muse AI — dây chuyền Muse (backend app/muse_hub.py, API mhub_*):
   thanh trên (dự án, trạng thái tài khoản, Chạy tiếp / Dừng tất cả / Thư mục) + 5 tab:
   Studio (soạn lệnh + hàng đợi) · Tư liệu · Kịch bản (storyboard — ui/studio.js) · Thư viện (+ ghép video) · Tài khoản.
   Tài khoản = profile trình duyệt đã gán Muse ở màn Profile trình duyệt. Dùng helper của app.js: $, $$, api, esc, toast… */
(() => {
  'use strict';

  const TABS = [['studio', '✦ Studio'], ['assets', '🗂 Tư liệu'], ['script', '🎬 Kịch bản'], ['ladi', '🛒 LadiPage'],
    ['story', '🎞 Storyboard dài'], ['library', '🖼 Thư viện'], ['accounts', '👤 Tài khoản']];
  // Kịch bản: cách làm / thời lượng / giọng đọc (khớp app/muse_script.py)
  const METHODS = [['direct', 'Làm video thẳng · nhanh ~3 phút'], ['storyboard', 'Storyboard → tự làm video · đồng nhất, ~8 phút'],
    ['review', 'Storyboard → chờ tôi duyệt rồi làm video']];
  const DURS = [['10', '10 giây · gộp 1 lệnh'], ['16', '16 giây · gộp 1 lệnh (2 cảnh × 8s)'], ['20', '20 giây · gộp 1 lệnh'],
    ['24', '24 giây · gộp 1 lệnh (3 cảnh × 8s)'], ['30', '30 giây · gộp 1 lệnh (3 cảnh × 10s)'], ['40', '40 giây · gộp 1 lệnh'],
    ['50', '50 giây · gộp 1 lệnh'], ['60', '60 giây · gộp 1 lệnh'], ['per_scene', 'Từng cảnh 10s · gửi lần lượt, app tự ghép']];
  const VOICES = [['none', 'Không lồng tiếng (giữ tiếng gốc)'], ['lipsync', 'Nhân vật tự nói — giọng Việt, khớp môi'],
    ['male_warm', 'Giọng nam · ấm, tin cậy'], ['male_energy', 'Giọng nam · trẻ, nhiều năng lượng'], ['male_deep', 'Giọng nam · trầm, thuyết phục'],
    ['female_warm', 'Giọng nữ · thân thiện, ấm áp'], ['female_bright', 'Giọng nữ · tươi sáng, dễ nghe'], ['female_fast', 'Giọng nữ · nhanh nhẹn, hợp TikTok']];
  const MOTIONS = [['zoom', '🔍 Zoom cận cảnh'], ['orbit', '🔄 Xoay 360°'], ['slide', '↔ Trượt ngang cinematic'], ['smoke', '🌫 Khói sương']];
  const GSTATUS = { running: 'Đang làm', finishing: 'Đang ghép…', done: 'Xong', failed: 'Lỗi', cancelled: 'Đã huỷ' };
  const H = {
    s: null, tab: 'studio', bound: false, sel: new Set(), q: '', filter: 'all',
    c: { kind: 'video', ratio: '9:16', text: '', images: [], pairing: 'shared' },
    k: { mode: 'script', text: '', method: 'direct', ratio: '9:16', duration: '30', prefix: '', voice: 'none', presenter: '',
      character: '', merge: true, bgm: false, versions: 1, images: [], motions: ['zoom'], note: '' },
    ladi: { url: '', page: null, picked: [], local: [], scripts: null, checked: new Set(), noPrice: true, busy: '', showText: false },
    lib: { items: [], sel: [] }, merge: null, detail: null,
  };
  try { H.tab = localStorage.getItem('va.mhub.tab') || 'studio'; } catch { /* bỏ qua */ }

  const fmt = ms => { if (!ms) return ''; const d = new Date(ms); return `${pad2(d.getHours())}:${pad2(d.getMinutes())} ${d.getDate()}/${d.getMonth() + 1}`; };
  const day = ms => { if (!ms) return ''; const d = new Date(ms); return `${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`; };
  const prompts = text => String(text || '').split(/\n\s*\n/).map(x => x.trim()).filter(Boolean);
  const proj = () => H.s.projects.find(p => p.id === H.s.current) || H.s.projects[0];
  const projTasks = () => H.s.tasks.filter(t => (t.project || 'default') === H.s.current);

  async function show() {
    if (!H.bound) bind();
    const res = await api('mhub_state');
    if (!res.ok) return toast(res.error, 'error');
    H.s = res.state;
    renderAll();
  }

  function update(event, data) {
    if (event === 'mhub_state') {
      H.s = data;
      if (!$('#page-mstudio') || $('#page-mstudio').classList.contains('hidden')) return;
      renderTop();
      if (H.tab === 'studio') { renderQueue(); renderDetected(); }
      else if (H.tab === 'script') renderGroups();
      else if (H.tab === 'accounts' && !(document.activeElement && document.activeElement.closest('#mhAccounts input'))) renderAccounts();
      else if (H.tab === 'assets' && !(document.activeElement && document.activeElement.closest('#mhAssets'))) renderAssets();
      if (H.detail) paintDetail();
    } else if (event === 'mhub_log') {
      const t = H.s && H.s.tasks.find(x => x.id === data.id);
      if (t) { t.log = [...(t.log || []), data.line].slice(-40); if (H.detail === data.id) paintDetail(); }
    } else if (event === 'mhub_merge') {
      H.merge = data;
      paintMerge();
      if (data.done) {
        toast(data.error ? `Ghép video lỗi: ${data.error}` : 'Đã ghép xong video', data.error ? 'error' : 'ok');
        if (!data.error) api('mhub_open', data.path);
      }
    }
  }

  // ------------------------------------------------------------ khung trang
  function renderAll() {
    renderTop();
    $('#mhTabs').innerHTML = TABS.map(([k, l]) => `<button class="mh-tab ${H.tab === k ? 'on' : ''}" data-tab="${k}" type="button">${l}</button>`).join('');
    $$('#page-mstudio .mh-panel').forEach(p => p.classList.toggle('hidden', p.dataset.panel !== H.tab));
    if (H.tab === 'studio') renderStudio();
    if (H.tab === 'assets') renderAssets();
    if (H.tab === 'script') renderScript();
    if (H.tab === 'ladi') renderLadi();
    if (H.tab === 'story') window.MuseStudioPage.show();
    if (H.tab === 'library') loadLibrary();
    if (H.tab === 'accounts') renderAccounts();
  }

  function accountSummary() {
    const accs = H.s.accounts;
    if (!accs.length) return ['bad', 'Chưa có profile Muse'];
    const on = accs.filter(a => a.enabled);
    if (!on.length) return ['bad', 'Chưa bật tài khoản nào'];
    const ready = on.filter(a => a.usable);
    const running = accs.reduce((n, a) => n + a.running, 0);
    if (!ready.length) return ['warn', 'Tài khoản: không có TK rảnh'];
    return ['ok', `${ready.length}/${on.length} tài khoản sẵn sàng${running ? ` · ${running} đang chạy` : ''}`];
  }

  function renderTop() {
    const [lvl, text] = accountSummary();
    const p = proj();
    const counts = projTasks().reduce((m, t) => { m[t.status] = (m[t.status] || 0) + 1; return m; }, {});
    $('#mhTop').innerHTML = `<div class="mh-top">
      <b class="mh-title">✦ Studio Muse AI</b>
      <select id="mhProject" title="Dự án đang mở">${H.s.projects.map(x => `<option value="${esc(x.id)}" ${x.id === H.s.current ? 'selected' : ''}>${esc(x.name)}${x.paused ? ' (tạm dừng)' : ''}</option>`).join('')}</select>
      <button class="btn ghost sm" data-act="projects" type="button">Dự án</button>
      <span class="mh-pill ${lvl}" data-tab-go="accounts" title="Mở tab Tài khoản">● ${esc(text)}</span>
      ${counts.processing ? `<span class="mh-pill run">▶ ${counts.processing} đang chạy</span>` : ''}
      ${counts.queued ? `<span class="mh-pill">⏳ ${counts.queued} chờ</span>` : ''}
      ${p && p.paused ? '<span class="mh-pill warn">Dự án đang tạm dừng</span>' : ''}
      ${H.s.stopped ? '<span class="mh-pill bad">Hàng đợi đã dừng</span>' : ''}
      <span class="mh-top-sp"></span>
      <button class="btn ${H.s.stopped ? 'primary' : 'ghost'} sm" data-act="resume" type="button">▶ Chạy tiếp</button>
      <button class="btn ghost sm mh-stop" data-act="stop" type="button">■ Dừng tất cả</button>
      <button class="btn ghost sm" data-act="folder" type="button">📂 Thư mục</button>
    </div>`;
  }

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
        <select id="mhRatio" title="Tỉ lệ khung hình">${['', ...H.s.ratios].map(r => `<option value="${r}" ${c.ratio === r ? 'selected' : ''}>${r || 'Tỉ lệ: tự do'}</option>`).join('')}</select></div>
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
        <label class="mh-switch"><input type="checkbox" data-hub-toggle="model" ${H.s.model.on ? 'checked' : ''}><i></i> Người mẫu cố định <small>${H.s.model.images.length} ảnh</small></label>
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

  const FILTERS = [['all', 'Tất cả'], ['queued', 'Chờ'], ['processing', 'Đang chạy'], ['succeeded', 'Xong'], ['failed', 'Lỗi'], ['cancelled', 'Đã huỷ']];
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
            <small>${esc(t.ratio || 'tự do')}${t.images.length ? ` · ${t.images.length} ảnh` : ''}${t.account ? ` · 👤 ${esc(accName(t.account))}` : ''}${t.attempts > 1 ? ` · lần ${t.attempts}` : ''} · ${fmt(t.created_at)}</small>
            ${t.error && t.status !== 'succeeded' ? `<small class="mh-err">${esc(t.error.slice(0, 180))}</small>` : ''}</div>
          <div class="mh-tfiles">${t.files.slice(0, 2).map(f => (f.video ? `<video src="${esc(f.url)}" muted preload="metadata"></video>` : `<img src="${esc(f.url)}" alt="">`)).join('')}</div>
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
    el.innerHTML = `<div class="mh-detail">
      <div class="mh-dmeta"><span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status])}</span><span>${t.kind === 'video' ? '🎬 Video' : '🖼 Ảnh'}</span>
        <span>▭ ${esc(t.ratio || 'tự do')}</span><span>👤 ${esc(acc)}</span><span>Lần chạy: ${t.attempts}</span><span>${fmt(t.created_at)}</span></div>
      <div class="iv-prompt"><b>Prompt</b><p>${esc(t.prompt)}</p></div>
      ${t.image_urls.length ? `<div class="mh-thumbs">${t.image_urls.map(u => `<span class="mh-thumb"><img src="${esc(u)}" alt=""></span>`).join('')}</div>` : ''}
      ${(t.notes || []).length ? `<small class="muted">${t.notes.map(esc).join(' · ')}</small>` : ''}
      ${t.error ? `<div class="mh-err-box">${esc(t.error)}</div>` : ''}
      ${t.files.length ? `<div class="mh-dfiles">${t.files.map(f => `<figure>${f.video ? `<video src="${esc(f.url)}" controls></video>` : `<img src="${esc(f.url)}" alt="">`}
        <button class="btn ghost sm" data-open-file="${esc(f.path)}" type="button">📂 Mở thư mục</button></figure>`).join('')}</div>` : ''}
      <div class="mh-log">${(t.log || []).map(l => `<div>${esc(l)}</div>`).join('') || '<small class="muted">Chưa có nhật ký</small>'}</div>
      <div class="ab-row">${['failed', 'cancelled', 'succeeded'].includes(t.status) ? '<button class="btn ghost sm" data-dt="retry" type="button">↻ Chạy lại</button>' : ''}
        ${['queued', 'processing'].includes(t.status) ? '<button class="btn ghost sm" data-dt="cancel" type="button">■ Huỷ</button>' : ''}
        <button class="btn ghost sm st-pdel" data-dt="delete" type="button">🗑 Xoá task</button></div></div>`;
    const lg = el.querySelector('.mh-log');
    lg.scrollTop = lg.scrollHeight;
    $('#modalBody').onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.openFile) return api('mhub_open', b.dataset.openFile);
      if (b.dataset.dt) {
        if (b.dataset.dt === 'delete' && !confirm('Xoá task này (file đã tải vẫn giữ)?')) return;
        await api('mhub_tasks', [t.id], b.dataset.dt);
        if (b.dataset.dt === 'delete') { H.detail = null; closeModal(); }
      }
    };
  }

  // ------------------------------------------------------------ tab Kịch bản
  const sel = (id, list, cur) => `<select id="${id}">${list.map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const parseVideos = text => String(text || '').split(/\n\s*\n/).map(b => b.split('\n').map(x => x.trim()).filter(Boolean)).filter(v => v.length);

  function renderScript() {
    $('#mhScript').innerHTML = '<div class="mh-studio"><section class="card mh-compose" id="mhKForm"></section><section class="card mh-queue" id="mhGroups"></section></div>';
    renderKForm();
    renderGroups();
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
    const chars = [['', '— Không dùng —'], ...H.s.characters.map(c => [c.id, c.name])];
    $('#mhKForm').innerHTML = `
      <div class="mh-seg">${[['script', '📝 Kịch bản'], ['image', '🖼 Từ ảnh']].map(([m, l]) => `<button class="${k.mode === m ? 'on' : ''}" data-kmode="${m}" type="button">${l}</button>`).join('')}</div>
      ${k.mode === 'script' ? `<label class="field"><span>Kịch bản <small class="muted">— mỗi dòng là 1 cảnh · cách 1 dòng trống để sang video tiếp theo</small></span>
        <textarea id="mhKText" rows="8" placeholder="Cô gái cầm bao phân bón đứng giữa cánh đồng lúa, mỉm cười&#10;Cận cảnh hạt phân rơi xuống gốc lúa&#10;Lúa xanh tốt, cô gái giơ ngón cái — chốt: mua ngay hôm nay&#10;&#10;(video thứ 2…)">${esc(k.text)}</textarea></label>`
      : `<div class="field"><span>Gợi ý chuyển động <small class="muted">(chọn nhiều được)</small></span>
          <div class="mh-chips">${MOTIONS.map(([m, l]) => `<button class="chip-f ${k.motions.includes(m) ? 'active' : ''}" data-motion="${m}" type="button">${l}</button>`).join('')}</div></div>
        <label class="field"><span>Ghi chú thêm (tuỳ chọn)</span><input id="mhKNote" value="${esc(k.note)}" placeholder="VD: nền gỗ, ánh sáng ấm"></label>`}
      <small class="mh-detected" id="mhKCount">${esc(kCount())}</small>
      <div class="mh-kgrid">
        ${k.mode === 'script' ? `<label class="field mh-wide"><span>Cách làm</span>${sel('mhKMethod', METHODS, k.method)}</label>` : ''}
        <label class="field"><span>Tỉ lệ</span>${sel('mhKRatio', [['9:16', '9:16 · Dọc (TikTok, Reels)'], ['16:9', '16:9 · Ngang (YouTube)'], ['1:1', '1:1 · Vuông']], k.ratio)}</label>
        ${k.mode === 'script' ? `<label class="field"><span>Thời lượng</span>${sel('mhKDur', DURS, k.duration)}</label>` : ''}
        <label class="field mh-wide"><span>Tiền tố câu lệnh <small class="muted">(thêm vào đầu mọi lệnh)</small></span><input id="mhKPrefix" value="${esc(k.prefix)}" placeholder="VD: Phong cách quảng cáo TikTok, ánh sáng tự nhiên"></label>
        <label class="field"><span>Giọng đọc</span>${sel('mhKVoice', VOICES, k.voice)}</label>
        <div class="field"><span>Người dẫn</span><div class="mh-seg sm">${[['', 'Theo giọng đọc'], ['female', 'Nữ'], ['male', 'Nam']].map(([v, l]) => `<button class="${k.presenter === v ? 'on' : ''}" data-presenter="${v}" type="button">${l}</button>`).join('')}</div></div>
        <label class="field" title="Gửi kèm ảnh nhân vật (tab Tư liệu) để mọi video giữ đúng 1 gương mặt người dẫn"><span>Nhân vật dẫn</span>${sel('mhKChar', chars, k.character)}</label>
        <label class="field"><span>Số bản / video <small class="muted">(Muse làm lại N lần để chọn)</small></span><input id="mhKVersions" type="number" min="1" max="5" value="${k.versions}"></label>
      </div>
      ${k.mode === 'script' && k.duration === 'per_scene' ? `<label class="mh-switch"><input type="checkbox" id="mhKMerge" ${k.merge ? 'checked' : ''}><i></i> Từng cảnh → tự ghép khi xong</label>` : ''}
      <div class="mh-row"><label class="mh-switch" title="Video xong thì bốc ngẫu nhiên 1 bài trong thư mục Nhạc nền, lót nhỏ dưới giọng đọc. Giữ cả bản không nhạc."><input type="checkbox" id="mhKBgm" ${k.bgm ? 'checked' : ''}><i></i> Nhạc nền</label>
        <button class="btn ghost sm" data-act="bgm-open" type="button">📂 Thư mục nhạc nền</button>
        <button class="link" data-act="bgm-pick" type="button" title="${esc(H.s.bgm_dir)}">Đổi thư mục</button></div>
      <div class="field"><span>Ảnh sản phẩm ${k.mode === 'script' ? '<small class="muted">(tuỳ chọn — mỗi ảnh làm ra 1 bộ video riêng)</small>' : '<small class="muted">(mỗi ảnh = 1 video)</small>'}</span>
        <div class="mh-thumbs">${k.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt=""><button data-krm="${i}" type="button">✕</button></span>`).join('')}
          <button class="mh-add" data-act="k-add-img" type="button">＋ Ảnh</button>
          ${k.images.length ? '<button class="link" data-act="k-clear-img" type="button">Bỏ hết ảnh</button>' : ''}</div></div>
      <div class="mh-row"><button class="btn ghost" data-act="k-preview" type="button">👁 Xem lệnh</button>
        <button class="btn primary mh-go" data-act="k-queue" type="button">＋ Đưa vào hàng đợi</button></div>`;
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
    return [{ done: 'ok', failed: 'bad', running: '', finishing: 'run', cancelled: '' }[g.status] || '', GSTATUS[g.status] || g.status];
  }

  function renderGroups() {
    const box = $('#mhGroups');
    if (!box) return;
    const groups = H.s.groups.filter(g => (g.project || 'default') === H.s.current).sort((a, b) => b.created_at - a.created_at);
    const mark = t => ({ succeeded: '✓', failed: '✕', processing: '▶', review: '?', cancelled: '–' }[t.status] || '·');
    box.innerHTML = `<div class="mh-qhead"><b>Video</b><small class="muted">${esc(proj().name)} · ${groups.length} video</small>
        <span class="mh-top-sp"></span>
        ${groups.some(g => g.status === 'done') ? '<button class="btn ghost sm" data-act="g-clear-done" type="button">Bỏ video đã xong</button>' : ''}
        <button class="btn ${H.s.stopped ? 'primary' : 'ghost'} sm" data-act="resume" type="button">▶ Bắt đầu render trên Muse</button></div>
      <div class="mh-rows">${groups.length ? groups.map(g => { const [lvl, txt] = groupStatus(g); return `<div class="mh-group">
          ${g.storyboard ? `<img class="mh-gsb" src="${esc(g.storyboard.url)}" alt="" title="Storyboard" data-zoom="${esc(g.storyboard.url)}">` : `<span class="mh-gsb ph">${g.mode === 'image' ? '🖼' : '🎬'}</span>`}
          <div class="mh-tbody"><p><b>${esc(g.title)}</b>${g.versions > 1 ? ` <small class="muted">· bản ${g.version}/${g.versions}</small>` : ''}</p>
            <small>${esc((METHODS.find(m => m[0] === g.method) || ['', 'Từ ảnh'])[1].split(' ·')[0])} · ${esc(g.ratio)} · ${esc(g.duration === 'per_scene' ? 'từng cảnh 10s' : `${g.duration}s`)}${g.bgm ? ' · 🎵 nhạc nền' : ''}</small>
            <div class="mh-gsteps">${g.tasks.map(t => `<span class="mh-gstep ${esc(t.status)}" title="${esc(t.role === 'storyboard' ? 'Storyboard' : t.scene ? `Cảnh ${t.scene}` : 'Video')} · ${esc(H.s.statuses[t.status] || t.status)}${t.error ? ` · ${esc(t.error)}` : ''}">${t.role === 'storyboard' ? 'SB' : t.scene ? `C${t.scene}` : 'V'} ${mark(t)}</span>`).join('')}</div>
            ${g.error ? `<small class="mh-err">${esc(g.error)}</small>` : ''}
            ${g.outputs.length ? `<div class="mh-gouts">${g.outputs.map(o => `<button class="btn ghost sm" data-gopen="${esc(o.path)}" type="button" title="${esc(o.name)}">🎞 ${esc(o.name.length > 34 ? `${o.name.slice(0, 32)}…` : o.name)}</button>`).join('')}</div>` : ''}</div>
          <div class="mh-gact"><span class="mh-pill ${lvl}">${esc(txt)}</span>
            ${g.tasks.some(t => t.status === 'review') ? `<button class="btn primary sm" data-gapprove="${esc(g.id)}" type="button">✓ Duyệt storyboard</button>` : ''}
            <button class="btn ghost sm st-pdel" data-gdel="${esc(g.id)}" type="button" title="Xoá video này khỏi danh sách (file đã tải vẫn giữ)">🗑</button></div>
        </div>`; }).join('') : '<div class="empty">Chưa có video — viết kịch bản bên trái rồi bấm “Đưa vào hàng đợi”.</div>'}</div>`;
  }

  // ------------------------------------------------------------ tab LadiPage
  function renderLadi() {
    const L = H.ladi;
    const p = L.page;
    const step = n => (n === 1 ? 'on' : n === 2 ? (p ? 'on' : '') : n === 3 ? (L.scripts ? 'on' : '') : (L.checked.size ? 'on' : ''));
    $('#mhLadi').innerHTML = `<div class="card mh-ladihead"><b class="mh-h">🛒 Từ LadiPage ra kịch bản video</b>
        <small class="muted">Dán link landing page: lấy ảnh gốc, giá, nội dung và để Muse viết 3 kịch bản phân cảnh.</small>
        <div class="mh-steps">${['Dán link', 'Chọn ảnh sản phẩm', 'Sửa kịch bản, chọn cách làm', 'Đưa vào hàng đợi'].map((s, i) => `<span class="${step(i + 1)}"><i>${i + 1}</i>${s}</span>`).join('')}</div>
        <div class="mh-row"><input id="mhLadiUrl" value="${esc(L.url)}" placeholder="https://shop.vidu.vn/san-pham">
          <button class="btn primary" data-act="ladi-go" type="button" ${L.busy ? 'disabled' : ''}>${L.busy || '🔍 Quét và sinh kịch bản'}</button></div>
        ${L.busy ? '<small class="muted">Đang xử lý — đọc trang rồi nhờ Muse viết kịch bản (1–3 phút)…</small>' : ''}</div>
      ${p ? `<div class="card mh-ladiprod"><div class="mh-card-head"><b>${esc(p.name)}</b>${p.prices.length ? `<span class="mh-pill">${esc(p.prices.slice(0, 3).join(' · '))}</span>` : ''}
          <button class="link" data-act="ladi-text" type="button">${L.showText ? 'Ẩn' : 'Xem'} chữ gốc trên trang</button></div>
        ${L.showText ? `<pre class="mh-ladi-text">${esc(p.text)}</pre>` : ''}
        <span class="muted">Kho ảnh sản phẩm (${p.images.length}) — bấm chọn 1–3 ảnh rõ sản phẩm nhất (viền xanh). Ảnh được gửi kèm mọi video để Muse giữ đúng sản phẩm.</span>
        <div class="mh-ladiimgs">${p.images.map(u => `<button class="mh-limg ${L.picked.includes(u) ? 'on' : ''}" data-limg="${esc(u)}" type="button"><img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer"></button>`).join('')}
          ${L.local.map((im, i) => `<span class="mh-limg on local"><img src="${esc(im.url)}" alt=""><button data-lrm="${i}" type="button">✕</button></span>`).join('')}
          <button class="mh-add" data-act="ladi-add-img" type="button">＋ Ảnh từ máy</button></div></div>` : ''}
      ${L.scripts ? `<div class="card mh-ladiscripts"><div class="mh-card-head"><b>Kịch bản</b><small class="muted">sửa được lời thoại và hình từng cảnh trước khi đưa vào hàng đợi</small>
          <label class="mh-switch" title="Lời chốt không đọc số tiền, chỉ nói giá ưu đãi để ở link. Đổi là sinh lại kịch bản (mất chữ đã sửa)."><input type="checkbox" id="mhLadiNoPrice" ${L.noPrice ? 'checked' : ''}><i></i> Không đọc giá</label></div>
        <div class="mh-lscripts">${L.scripts.scripts.map((s, i) => `<div class="mh-lscript ${L.checked.has(i) ? 'on' : ''}">
            <label class="check"><input type="checkbox" data-lcheck="${i}" ${L.checked.has(i) ? 'checked' : ''}> <b>${esc(s.title)}</b></label>
            ${s.angle ? `<small class="muted">${esc(s.angle)}</small>` : ''}
            ${s.scenes.map((c, j) => `<div class="mh-lscene"><span>Cảnh ${j + 1}</span>
              <textarea data-lline="${i}:${j}" rows="2" placeholder="Lời thoại">${esc(c.line)}</textarea>
              <textarea data-lvis="${i}:${j}" rows="2" placeholder="Hình ảnh cảnh quay">${esc(c.visual)}</textarea></div>`).join('')}
          </div>`).join('')}</div>
        <small class="muted">Cách làm, tỉ lệ, thời lượng, giọng đọc, người dẫn, nhạc nền lấy theo thiết lập ở tab <button class="link" data-tab-go="script" type="button">Kịch bản</button>
          (${esc((METHODS.find(m => m[0] === H.k.method) || METHODS[0])[1].split(' ·')[0])} · ${esc(H.k.ratio)} · ${esc((DURS.find(d => d[0] === H.k.duration) || DURS[4])[1].split(' ·')[0])}).</small>
        <div class="mh-row"><button class="btn ghost" data-act="ladi-preview" type="button" ${L.checked.size ? '' : 'disabled'}>👁 Xem lệnh sẽ gửi Muse</button>
          <button class="btn ghost sm" data-act="ladi-all" type="button">Tích cả</button>
          <button class="btn primary" data-act="ladi-queue" type="button" ${L.checked.size ? '' : 'disabled'}>＋ Đưa ${L.checked.size} kịch bản đã tích vào hàng đợi</button></div></div>` : ''}`;
  }

  const sceneLine = c => (c.visual && c.line ? `${c.visual} — Lời thoại: “${c.line}”` : c.visual || `Lời thoại: “${c.line}”`);

  async function ladiImages() {  // ảnh đã chọn trên trang → tải về máy; + ảnh từ máy
    const L = H.ladi;
    let web = [];
    if (L.picked.length) {
      const r = await api('mhub_ladi_images', L.picked);
      if (!r.ok) { toast(r.error, 'error'); return null; }
      web = r.images;
    }
    return [...web, ...L.local].slice(0, H.s.max_images);
  }

  async function ladiForms(dry) {
    const L = H.ladi;
    const imgs = await ladiImages();
    if (imgs === null) return null;
    return [...L.checked].sort().map(i => {
      const s = L.scripts.scripts[i];
      return { ...kForm(), mode: 'script', product_images: [], images: imgs.map(x => x.path), title: `${L.scripts.name || L.page.name} · ${s.title}`,
        text: s.scenes.map(sceneLine).join('\n'), dry };
    });
  }

  async function ladiGenerate() {
    const L = H.ladi;
    L.busy = 'Đang đọc trang…'; renderLadi();
    let r = await api('mhub_ladi_fetch', L.url);
    if (!r.ok) { L.busy = ''; renderLadi(); return toast(r.error, 'error'); }
    L.page = r.page; L.picked = r.page.images.slice(0, 2); L.scripts = null; L.checked = new Set();
    L.busy = 'Muse đang viết kịch bản…'; renderLadi();
    const secs = H.k.duration === 'per_scene' ? 30 : +H.k.duration;
    r = await api('mhub_ladi_scripts', L.page, L.noPrice, Math.max(2, Math.min(6, Math.round(secs / 10))), secs, '', !!H.s.settings.show_browser);
    L.busy = '';
    if (!r.ok) { renderLadi(); return toast(r.error, 'error'); }
    L.scripts = r.result;
    L.checked = new Set(L.scripts.scripts.map((_, i) => i));
    renderLadi();
  }

  // ------------------------------------------------------------ tab Tư liệu
  function renderAssets() {
    const s = H.s;
    const imgs = (list, kind) => `<div class="mh-thumbs">${list.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt="">
        <button data-asset-rm="${kind}" data-i="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
      <button class="mh-add" data-asset-add="${kind}" type="button">＋ Ảnh</button></div>`;
    $('#mhAssets').innerHTML = `<div class="mh-assets">
      <section class="card"><div class="mh-card-head"><b>🧑 Nhân vật</b><small class="muted">gõ đúng tên trong prompt → tự gắn ảnh (≤ 3 ảnh / nhân vật)</small>
          <button class="btn primary sm" data-act="char-new" type="button">＋ Nhân vật</button></div>
        ${s.characters.length ? s.characters.map(ch => `<div class="mh-char"><b>${esc(ch.name)}</b>
            <div class="mh-thumbs">${ch.images.map(im => `<span class="mh-thumb"><img src="${esc(im.url)}" alt=""></span>`).join('') || '<small class="muted">chưa có ảnh</small>'}</div>
            <button class="btn ghost sm" data-char-edit="${esc(ch.id)}" type="button">Sửa</button>
            <button class="btn ghost sm st-pdel" data-char-del="${esc(ch.id)}" type="button">🗑</button></div>`).join('') : '<div class="empty">Chưa có nhân vật.</div>'}</section>
      <section class="card"><div class="mh-card-head"><b>📝 Mẫu prompt</b><small class="muted">chèn nhanh ở tab Studio</small>
          <button class="btn primary sm" data-act="tpl-new" type="button">＋ Mẫu</button></div>
        ${s.templates.length ? s.templates.map(t => `<div class="mh-tpl"><div><b>${esc(t.name)}</b><p>${esc(t.text)}</p></div>
            <button class="btn ghost sm" data-tpl-edit="${esc(t.id)}" type="button">Sửa</button>
            <button class="btn ghost sm st-pdel" data-tpl-del="${esc(t.id)}" type="button">🗑</button></div>`).join('') : '<div class="empty">Chưa có mẫu prompt.</div>'}</section>
      <section class="card"><div class="mh-card-head"><b>👤 Người mẫu cố định</b><small class="muted">bật → gắn vào MỌI task (≤ 3 ảnh)</small>
          <label class="mh-switch"><input type="checkbox" data-hub-toggle="model" ${s.model.on ? 'checked' : ''}><i></i>${s.model.on ? 'Đang bật' : 'Tắt'}</label></div>
        ${imgs(s.model.images, 'model')}</section>
      <section class="card"><div class="mh-card-head"><b>🔁 Ảnh luân phiên</b><small class="muted">bật → mỗi task lấy 1 ảnh kế tiếp (≤ 20 ảnh)</small>
          <label class="mh-switch"><input type="checkbox" data-hub-toggle="rotate" ${s.rotate.on ? 'checked' : ''}><i></i>${s.rotate.on ? 'Đang bật' : 'Tắt'}</label></div>
        ${imgs(s.rotate.images, 'rotate')}${s.rotate.images.length ? `<small class="muted">Ảnh kế tiếp: số ${((s.rotate.idx || 0) % s.rotate.images.length) + 1}</small>` : ''}</section>
    </div>`;
  }

  async function pickImages() {
    const files = await api('pick_files', 'images_multi');
    if (!files || !files.length) return [];
    const res = await api('mhub_import', files);
    if (!res.ok) { toast(res.error, 'error'); return []; }
    return res.images;
  }

  function charDialog(ch) {
    const data = { id: ch ? ch.id : '', name: ch ? ch.name : '', images: ch ? [...ch.images] : [] };
    const paint = () => {
      openModal('TƯ LIỆU', ch ? 'Sửa nhân vật' : 'Nhân vật mới', `<div class="form">
        <label class="field"><span>Tên (gõ đúng tên này trong prompt để tự gắn ảnh)</span><input id="mhCharName" value="${esc(data.name)}" placeholder="VD: Lan"></label>
        <div class="field"><span>Ảnh (≤ 3)</span><div class="mh-thumbs">${data.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt=""><button data-ci-rm="${i}" type="button">✕</button></span>`).join('')}
          ${data.images.length < 3 ? '<button class="mh-add" data-ci-add type="button">＋ Ảnh</button>' : ''}</div></div>
        <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-ci-cancel type="button">Huỷ</button><button class="btn primary" data-ci-save type="button">💾 Lưu</button></div></div>`, true);
      $('#modalBody').onclick = async e => {
        const b = e.target.closest('button');
        if (!b) return;
        data.name = $('#mhCharName').value;
        if (b.dataset.ciCancel !== undefined) return closeModal();
        if (b.dataset.ciRm !== undefined) { data.images.splice(+b.dataset.ciRm, 1); return paint(); }
        if (b.dataset.ciAdd !== undefined) { data.images = [...data.images, ...await pickImages()].slice(0, 3); return paint(); }
        if (b.dataset.ciSave !== undefined) {
          const res = await api('mhub_asset', 'character', { id: data.id, name: data.name, images: data.images.map(i => i.path) });
          if (!res.ok) return toast(res.error, 'error');
          closeModal(); H.s = res.state; renderAssets();
        }
      };
    };
    paint();
  }

  function tplDialog(t, text = '') {
    openModal('TƯ LIỆU', t ? 'Sửa mẫu prompt' : 'Mẫu prompt mới', `<div class="form">
      <label class="field"><span>Tên mẫu</span><input id="mhTplName" value="${esc(t ? t.name : '')}"></label>
      <label class="field"><span>Nội dung</span><textarea id="mhTplText" rows="8">${esc(t ? t.text : text)}</textarea></label>
      <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-tp-cancel type="button">Huỷ</button><button class="btn primary" data-tp-save type="button">💾 Lưu</button></div></div>`, true);
    $('#modalBody').onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.tpCancel !== undefined) return closeModal();
      if (b.dataset.tpSave !== undefined) {
        const res = await api('mhub_asset', 'template', { id: t ? t.id : '', name: $('#mhTplName').value, text: $('#mhTplText').value });
        if (!res.ok) return toast(res.error, 'error');
        closeModal(); H.s = res.state; renderAll(); toast('Đã lưu mẫu prompt', 'ok');
      }
    };
  }

  function projectsDialog() {
    const paint = () => {
      openModal('STUDIO MUSE AI', 'Dự án', `<div class="form">
        ${H.s.projects.map(p => `<div class="mh-proj ${p.id === H.s.current ? 'on' : ''}">
          <input data-pj-name="${esc(p.id)}" value="${esc(p.name)}" ${p.id === 'default' ? 'disabled' : ''}>
          <small class="muted">${H.s.tasks.filter(t => (t.project || 'default') === p.id).length} task</small>
          <button class="btn ghost sm" data-pj-open="${esc(p.id)}" type="button">${p.id === H.s.current ? '✓ Đang mở' : 'Mở'}</button>
          <button class="btn ghost sm" data-pj-pause="${esc(p.id)}" type="button">${p.paused ? '▶ Chạy tiếp' : '⏸ Tạm dừng'}</button>
          ${p.id === 'default' ? '' : `<button class="btn ghost sm st-pdel" data-pj-del="${esc(p.id)}" type="button">🗑</button>`}</div>`).join('')}
        <div class="ab-row"><input id="mhNewProj" placeholder="Tên dự án mới"><button class="btn primary sm" data-pj-add type="button">＋ Thêm dự án</button></div>
        <small class="muted">Tạm dừng: task chờ của dự án không chạy (task đang chạy vẫn chạy xong). Xoá dự án: huỷ + xoá task của dự án, file đã tải vẫn giữ.</small></div>`, true);
      const call = async (...args) => { const r = await api('mhub_project', ...args); if (!r.ok) return toast(r.error, 'error'); H.s = r.state; paint(); renderAll(); };
      $('#modalBody').onclick = e => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.pjAdd !== undefined) return call('add', '', $('#mhNewProj').value);
        if (b.dataset.pjOpen) return call('select', b.dataset.pjOpen);
        if (b.dataset.pjPause) return call('pause', b.dataset.pjPause);
        if (b.dataset.pjDel && confirm('Xoá dự án và toàn bộ task của dự án (file đã tải vẫn giữ)?')) return call('delete', b.dataset.pjDel);
      };
      $('#modalBody').onchange = e => { if (e.target.dataset.pjName) call('rename', e.target.dataset.pjName, e.target.value); };
    };
    paint();
  }

  // ------------------------------------------------------------ tab Thư viện + ghép video
  async function loadLibrary() {
    const res = await api('mhub_library', H.s.current);
    H.lib.items = res.ok ? res.items : [];
    H.lib.sel = H.lib.sel.filter(p => H.lib.items.some(i => i.path === p));
    renderLibrary();
  }

  function renderLibrary() {
    const items = H.lib.items;
    const vids = items.filter(i => i.video).length;
    $('#mhLibrary').innerHTML = `<div class="card mh-libhead"><b>Thư viện · ${esc(proj().name)}</b>
        <small class="muted">${items.length} file · ${vids} video${H.lib.sel.length ? ` · đã chọn ${H.lib.sel.length} video để ghép` : ' · tick ô ở góc video để chọn ghép'}</small>
        <span class="mh-top-sp"></span>
        <button class="btn ghost sm" data-act="lib-reload" type="button">Tải lại</button>
        <button class="btn primary sm" data-act="merge" type="button" ${H.lib.sel.length >= 2 ? '' : 'disabled title="Chọn ít nhất 2 video"'}>🎞 Ghép video (${H.lib.sel.length})</button></div>
      <div class="img-grid mh-libgrid">${items.length ? items.map(i => `<div class="img-tile mh-lib ${H.lib.sel.includes(i.path) ? 'sel' : ''}" title="${esc(i.prompt)}">
          ${i.video ? `<video src="${esc(i.url)}" muted preload="metadata"></video><i class="img-count">🎬</i>` : `<img src="${esc(i.url)}" alt="" loading="lazy">`}
          ${i.video ? `<label class="mh-libsel" title="Chọn để ghép"><input type="checkbox" data-lib-sel="${esc(i.path)}" ${H.lib.sel.includes(i.path) ? 'checked' : ''}></label>` : ''}
          <div class="img-tile-bar"><small>${fmt(i.finished_at)}</small><button class="img-tile-btn" data-lib-open="${esc(i.path)}" title="Mở thư mục, chọn sẵn file" type="button">📂</button></div>
        </div>`).join('') : '<div class="empty">Chưa có file — task xong sẽ hiện ở đây.</div>'}</div>`;
  }

  function mergeDialog() {
    const order = [...H.lib.sel];
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

  // ------------------------------------------------------------ tab Tài khoản
  function quotaHtml(a) {
    const q = a.quota;
    if (!q) return `<small class="muted">${a.checking ? 'Đang đọc hạn mức…' : 'Chưa có số liệu hạn mức — bấm “Hạn mức”'}</small>`;
    const pct = Math.min(100, Math.round(q.pct));
    return `<div class="mh-quota"><div class="mh-qbar ${pct >= 100 ? 'out' : pct >= 80 ? 'low' : ''}"><i style="width:${pct}%"></i></div>
      <small>${esc(q.tier || 'Muse')} · đã dùng ${pct}% tuần${q.resets_at ? ` · đặt lại ${day(q.resets_at)}` : ''}${q.topup_left != null ? ` · token bổ sung còn ${Math.round(q.topup_left * 100)}%` : ''}</small></div>`;
  }

  function statusOf(a) {
    if (!a.enabled) return ['', 'Tắt'];
    if (a.logged_in === false) return ['bad', 'Chưa đăng nhập'];
    if (a.running) return ['run', `Đang chạy ${a.running}`];
    if (a.checking) return ['', 'Đang kiểm tra…'];
    if (!a.usable) return ['warn', 'Hết hạn mức — nghỉ'];
    if (a.weekly_out) return ['warn', 'Hết tuần · dùng token'];
    return ['ok', 'Sẵn sàng'];
  }

  function renderAccounts() {
    const s = H.s.settings;
    const accs = H.s.accounts;
    const num = (k, label, min, max) => `<label class="field"><span>${label}</span><input type="number" min="${min}" max="${max}" data-set="${k}" value="${esc(s[k])}"></label>`;
    $('#mhAccounts').innerHTML = `<div class="card mh-acchead"><div><b class="mh-h">Tài khoản Muse</b>
        <small class="muted">Dùng profile Muse của hệ thống (Profile trình duyệt) — mỗi tài khoản 1 Chrome riêng, chạy song song. Đăng nhập 1 lần, app nhớ phiên.</small></div>
        <span class="mh-top-sp"></span>
        <button class="btn ghost sm" data-act="quota-all" type="button" title="Mở muse.ai ẩn ở từng profile, đọc % hạn mức tuần (không tốn lượt)">Kiểm tra hạn mức</button>
        <button class="btn primary sm" data-act="add-account" type="button">＋ Thêm tài khoản</button></div>
      <div class="card mh-settings">
        <div class="mh-grid">${num('max_accounts', 'TK chạy đồng thời', 1, 20)}${num('total_threads', 'Tổng luồng', 1, 50)}
          <div class="field"><span>Chia việc</span><div class="mh-seg">${[['rotate', 'Luân phiên'], ['sequential', 'Lần lượt']].map(([k, l]) => `<button class="${s.mode === k ? 'on' : ''}" data-mode="${k}" type="button">${l}</button>`).join('')}</div></div>
          ${num('limit_image', 'Giới hạn ảnh (phút)', 1, 60)}${num('limit_video', 'Giới hạn video (phút)', 5, 120)}${num('retries', 'Tự thử lại khi lỗi', 0, 3)}</div>
        <label class="mh-switch"><input type="checkbox" data-set-bool="use_topup" ${s.use_topup ? 'checked' : ''}><i></i> Dùng token bổ sung khi hết hạn mức tuần</label>
        <label class="mh-switch"><input type="checkbox" data-set-bool="keep_going" ${s.keep_going ? 'checked' : ''}><i></i> Hết hạn mức &amp; token vẫn tạo tiếp (chậm hơn)</label>
        <small class="muted">Hiện / ẩn cửa sổ Chrome: chỉnh chung ở <button class="link" data-act="open-settings" type="button">Cài đặt</button>.</small>
        <small class="muted">Luân phiên: task mới vào tài khoản ít việc nhất, dùng ít hạn mức nhất. Lần lượt: lấp đầy luồng tài khoản trên trước rồi mới sang tài khoản dưới. Tài khoản hết hạn mức (và không được dùng token) tự nghỉ tới ngày đặt lại.</small></div>
      ${accs.length ? accs.map(a => { const [lvl, txt] = statusOf(a); return `<div class="card mh-acc ${a.enabled ? '' : 'off'}">
          <label class="mh-switch" title="Bật / tắt tài khoản"><input type="checkbox" data-acc-on="${esc(a.id)}" ${a.enabled ? 'checked' : ''}><i></i></label>
          <div class="mh-accname"><b>${esc(a.name)}</b><span class="mh-pill ${lvl}">● ${esc(txt)}</span></div>
          <div class="mh-accq">${quotaHtml(a)}${a.error ? `<small class="mh-err">${esc(a.error)}</small>` : ''}</div>
          <select data-acc-threads="${esc(a.id)}" title="Số task chạy cùng lúc trên tài khoản này">${[1, 2, 3, 4, 5].map(n => `<option value="${n}" ${a.threads === n ? 'selected' : ''}>${n} luồng</option>`).join('')}</select>
          <button class="btn ghost sm" data-acc-login="${esc(a.id)}" type="button" title="Mở Chrome của tài khoản để đăng nhập / xem">Hiện Chrome</button>
          <button class="btn ghost sm" data-acc-quota="${esc(a.id)}" type="button" ${a.checking || a.running ? 'disabled' : ''}>Hạn mức</button></div>`; }).join('')
        : '<div class="card empty">Chưa có profile nào gán Muse — bấm “＋ Thêm tài khoản” để tạo profile trong màn Profile trình duyệt, tick Muse rồi đăng nhập.</div>'}`;
  }

  // ------------------------------------------------------------ sự kiện
  function bind() {
    H.bound = true;
    const page = $('#page-mstudio');
    page.addEventListener('click', async e => {
      if (e.target.closest('#mstudioBody')) return;  // tab Kịch bản do ui/studio.js xử lý
      const b = e.target.closest('button, [data-tab-go], [data-zoom]');
      if (!b) {
        const row = e.target.closest('.mh-task');
        if (row && !e.target.matches('input')) openDetail(row.dataset.task);
        return;
      }
      const d = b.dataset;
      if (d.tab || d.tabGo) {
        H.tab = d.tab || d.tabGo;
        try { localStorage.setItem('va.mhub.tab', H.tab); } catch { /* bỏ qua */ }
        return renderAll();
      }
      const act = d.act;
      if (act === 'projects') return projectsDialog();
      if (act === 'stop') { if (!confirm('Dừng tất cả: huỷ task đang chạy và tạm dừng hàng đợi?')) return; H.s = (await api('mhub_stop')).state; return renderAll(); }
      if (act === 'resume') { H.s = (await api('mhub_resume')).state; toast('Hàng đợi đang chạy', 'ok'); return renderAll(); }
      if (act === 'folder') return api('mhub_open', '');
      if (act === 'open-settings') return openSettings();
      if (d.kind) { H.c.kind = d.kind; return renderCompose(); }
      if (d.pair) { H.c.pairing = d.pair; return renderCompose(); }
      if (d.rmImg !== undefined) { H.c.images.splice(+d.rmImg, 1); return renderCompose(); }
      if (act === 'add-img') { H.c.images = [...H.c.images, ...await pickImages()]; return renderCompose(); }
      if (act === 'save-tpl') { if (!H.c.text.trim()) return toast('Ô prompt đang trống', 'warn'); return tplDialog(null, H.c.text); }
      if (act === 'add-tasks') {
        const res = await api('mhub_add', { kind: H.c.kind, ratio: H.c.ratio, prompts: prompts(H.c.text), images: H.c.images.map(i => i.path), pairing: H.c.pairing });
        if (!res.ok) return toast(res.error, 'error');
        toast(`Đã thêm ${res.result.created.length} task vào hàng đợi`, 'ok');
        H.c.text = ''; H.c.images = [];
        const st = await api('mhub_state');  // vẽ ngay hàng đợi mới (không chờ sự kiện từ backend)
        if (st.ok) H.s = st.state;
        renderTop(); renderCompose(); return renderQueue();
      }
      if (d.filter) { H.filter = d.filter; return renderQueue(); }
      if (act === 'sel-failed' || act === 'sel-queued') {
        const st = act === 'sel-failed' ? 'failed' : 'queued';
        H.sel = new Set(projTasks().filter(t => t.status === st).map(t => t.id));
        return renderQueue();
      }
      if (d.bulk) {
        if (d.bulk === 'delete' && !confirm(`Xoá ${H.sel.size} task (file đã tải vẫn giữ)?`)) return;
        const res = await api('mhub_tasks', [...H.sel], d.bulk);
        if (res.ok) H.s = res.state;
        if (d.bulk === 'delete') H.sel.clear();
        return renderQueue();
      }
      // kịch bản
      if (d.kmode) { H.k.mode = d.kmode; return renderKForm(); }
      if (d.motion) { const m = d.motion; H.k.motions = H.k.motions.includes(m) ? H.k.motions.filter(x => x !== m) : [...H.k.motions, m]; return renderKForm(); }
      if (d.presenter !== undefined) { H.k.presenter = d.presenter; return renderKForm(); }
      if (act === 'k-add-img') { H.k.images = [...H.k.images, ...await pickImages()].slice(0, 30); return renderKForm(); }
      if (act === 'k-clear-img') { H.k.images = []; return renderKForm(); }
      if (d.krm !== undefined) { H.k.images.splice(+d.krm, 1); return renderKForm(); }
      if (act === 'bgm-open') return api('mhub_bgm', 'open');
      if (act === 'bgm-pick') { const r = await api('mhub_bgm', 'pick'); if (r.ok && r.state) { H.s = r.state; renderKForm(); } return; }
      if (act === 'k-preview' || act === 'k-queue') {
        const res = await api('mhub_script', { ...kForm(), dry: act === 'k-preview' });
        if (!res.ok) return toast(res.error, 'error');
        if (act === 'k-preview') return previewDialog(res.result.preview);
        toast(`Đã đưa ${res.result.groups} video (${res.result.created.length} lệnh Muse) vào hàng đợi`, 'ok');
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        renderTop(); return renderGroups();
      }
      if (d.gapprove) { const r = await api('mhub_approve', d.gapprove); if (!r.ok) return toast(r.error, 'error'); H.s = r.state; toast('Đã duyệt — video vào hàng đợi', 'ok'); return renderGroups(); }
      if (d.gdel) { if (!confirm('Xoá video này khỏi danh sách (file đã tải vẫn giữ)?')) return; const r = await api('mhub_group_delete', d.gdel); if (r.ok) { H.s = r.state; renderGroups(); } return; }
      if (d.gopen) return api('mhub_open', d.gopen);
      if (act === 'g-clear-done') {
        for (const g of H.s.groups.filter(x => x.status === 'done' && (x.project || 'default') === H.s.current)) await api('mhub_group_delete', g.id);
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        return renderGroups();
      }
      if (d.zoom) return openModal('STORYBOARD', 'Ảnh storyboard', `<div class="viewer"><img src="${esc(d.zoom)}" alt=""></div>`);
      // LadiPage
      if (act === 'ladi-go') { H.ladi.url = ($('#mhLadiUrl') || {}).value || ''; if (!H.ladi.url.trim()) return toast('Dán link landing page trước', 'warn'); return ladiGenerate(); }
      if (act === 'ladi-text') { H.ladi.showText = !H.ladi.showText; return renderLadi(); }
      if (d.limg) {
        const u = d.limg, L = H.ladi;
        if (L.picked.includes(u)) L.picked = L.picked.filter(x => x !== u);
        else if (L.picked.length + L.local.length >= 3) return toast('Chọn tối đa 3 ảnh sản phẩm', 'warn');
        else L.picked = [...L.picked, u];
        return renderLadi();
      }
      if (act === 'ladi-add-img') { H.ladi.local = [...H.ladi.local, ...await pickImages()].slice(0, 3); return renderLadi(); }
      if (d.lrm !== undefined) { H.ladi.local.splice(+d.lrm, 1); return renderLadi(); }
      if (act === 'ladi-all') { H.ladi.checked = new Set(H.ladi.scripts.scripts.map((_, i) => i)); return renderLadi(); }
      if (act === 'ladi-preview' || act === 'ladi-queue') {
        const forms = await ladiForms(act === 'ladi-preview');
        if (!forms) return;
        const all = [];
        let groups = 0;
        for (const f of forms) {
          const r = await api('mhub_script', f);
          if (!r.ok) return toast(r.error, 'error');
          if (f.dry) all.push(...r.result.preview); else groups += r.result.groups;
        }
        if (act === 'ladi-preview') return previewDialog(all);
        toast(`Đã đưa ${groups} video vào hàng đợi — xem ở tab Kịch bản`, 'ok');
        H.tab = 'script';
        return show();
      }
      // tư liệu
      if (act === 'char-new') return charDialog(null);
      if (d.charEdit) return charDialog(H.s.characters.find(c => c.id === d.charEdit));
      if (d.charDel) { if (!confirm('Xoá nhân vật?')) return; const r = await api('mhub_asset', 'character_delete', { id: d.charDel }); if (r.ok) { H.s = r.state; renderAssets(); } return; }
      if (act === 'tpl-new') return tplDialog(null);
      if (d.tplEdit) return tplDialog(H.s.templates.find(t => t.id === d.tplEdit));
      if (d.tplDel) { if (!confirm('Xoá mẫu prompt?')) return; const r = await api('mhub_asset', 'template_delete', { id: d.tplDel }); if (r.ok) { H.s = r.state; renderAssets(); } return; }
      if (d.assetAdd || d.assetRm) {
        const kind = d.assetAdd || d.assetRm;
        let list = H.s[kind].images.map(i => i.path);
        if (d.assetAdd) list = [...list, ...(await pickImages()).map(i => i.path)];
        else list.splice(+d.i, 1);
        const r = await api('mhub_asset', kind, { images: list });
        if (!r.ok) return toast(r.error, 'error');
        H.s = r.state;
        return renderAssets();
      }
      // thư viện
      if (act === 'lib-reload') return loadLibrary();
      if (act === 'merge') return mergeDialog();
      if (d.libOpen) return api('mhub_open', d.libOpen);
      // tài khoản
      if (d.mode) { const r = await api('mhub_settings', { mode: d.mode }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (act === 'quota-all') { api('mhub_quota', ''); return toast('Đang đọc hạn mức các tài khoản (mở muse.ai ẩn, không tốn lượt)…'); }
      if (act === 'add-account') { toast('Tạo profile mới, tick “Muse (Meta)” rồi bấm Đăng nhập — tài khoản tự hiện ở Studio Muse AI'); return navigate('profiles'); }
      if (d.accQuota) return api('mhub_quota', d.accQuota);
      if (d.accLogin) { const r = await api('mhub_login', d.accLogin); if (!r.ok) toast(r.error, 'error'); }
    });
    page.addEventListener('change', async e => {
      const t = e.target;
      if (t.closest('#mstudioBody')) return;
      if (t.id === 'mhProject') { const r = await api('mhub_project', 'select', t.value); if (r.ok) { H.s = r.state; H.sel.clear(); renderAll(); } return; }
      if (t.id === 'mhRatio') { H.c.ratio = t.value; return; }
      const kmap = { mhKMethod: 'method', mhKRatio: 'ratio', mhKDur: 'duration', mhKVoice: 'voice', mhKChar: 'character' };
      if (kmap[t.id]) { H.k[kmap[t.id]] = t.value; if (t.id === 'mhKDur') renderKForm(); return; }
      if (t.id === 'mhKVersions') { H.k.versions = Math.max(1, Math.min(5, +t.value || 1)); $('#mhKCount').textContent = kCount(); return; }
      if (t.id === 'mhKMerge') { H.k.merge = t.checked; return; }
      if (t.id === 'mhKBgm') { H.k.bgm = t.checked; return; }
      if (t.id === 'mhLadiNoPrice') {
        if (H.ladi.scripts && !confirm('Đổi “Không đọc giá” sẽ sinh lại kịch bản (mất chữ đã sửa). Tiếp tục?')) { t.checked = !t.checked; return; }
        H.ladi.noPrice = t.checked;
        return H.ladi.page ? ladiGenerate() : undefined;
      }
      if (t.dataset.lcheck !== undefined) { const i = +t.dataset.lcheck; if (t.checked) H.ladi.checked.add(i); else H.ladi.checked.delete(i); return renderLadi(); }
      if (t.id === 'mhTpl' && t.value) {
        const tp = H.s.templates.find(x => x.id === t.value);
        if (tp) { H.c.text = H.c.text.trim() ? `${H.c.text.trim()}\n\n${tp.text}` : tp.text; renderCompose(); }
        return;
      }
      if (t.dataset.hubToggle) {
        const r = await api('mhub_asset', t.dataset.hubToggle, { on: t.checked });
        if (r.ok) { H.s = r.state; if (H.tab === 'assets') renderAssets(); else renderCompose(); }
        return;
      }
      if (t.dataset.sel) { if (t.checked) H.sel.add(t.dataset.sel); else H.sel.delete(t.dataset.sel); return renderQueue(); }
      if (t.dataset.act === 'sel-all') { visibleTasks().forEach(x => (t.checked ? H.sel.add(x.id) : H.sel.delete(x.id))); return renderQueue(); }
      if (t.dataset.libSel) {
        const p = t.dataset.libSel;
        H.lib.sel = t.checked ? [...H.lib.sel, p] : H.lib.sel.filter(x => x !== p);
        return renderLibrary();
      }
      if (t.dataset.set) { const r = await api('mhub_settings', { [t.dataset.set]: t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.setBool) { const r = await api('mhub_settings', { [t.dataset.setBool]: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.accOn) { const r = await api('mhub_account', t.dataset.accOn, { enabled: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); renderTop(); } return; }
      if (t.dataset.accThreads) { const r = await api('mhub_account', t.dataset.accThreads, { threads: +t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } }
    });
    page.addEventListener('input', e => {
      if (e.target.id === 'mhText') {
        H.c.text = e.target.value;
        const n = prompts(H.c.text).length;
        const go = $('#mhCompose .mh-go');
        go.disabled = !n;
        go.textContent = `＋ Thêm ${n || ''} task vào hàng đợi`;
        $('#mhCount').innerHTML = composeCount(n);
        renderDetected();
      }
      if (e.target.id === 'mhSearch') { H.q = e.target.value; renderQueue(); }
      if (e.target.id === 'mhKText') { H.k.text = e.target.value; $('#mhKCount').textContent = kCount(); }
      if (e.target.id === 'mhKPrefix') H.k.prefix = e.target.value;
      if (e.target.id === 'mhKNote') H.k.note = e.target.value;
      if (e.target.id === 'mhLadiUrl') H.ladi.url = e.target.value;
      const ll = e.target.dataset.lline || e.target.dataset.lvis;
      if (ll) { const [i, j] = ll.split(':').map(Number); H.ladi.scripts.scripts[i].scenes[j][e.target.dataset.lline ? 'line' : 'visual'] = e.target.value; }
    });
  }

  window.MuseHubPage = { show, update };
})();
