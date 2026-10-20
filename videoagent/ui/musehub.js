/* Studio Muse AI — dây chuyền Muse (backend app/muse_hub.py, API mhub_*):
   thanh trên (dự án, trạng thái tài khoản, Chạy tiếp / Dừng tất cả / Thư mục) + 5 tab:
   Studio (soạn lệnh + hàng đợi) · Tư liệu · Kịch bản (storyboard — ui/studio.js) · Thư viện (+ ghép video) · Tài khoản.
   Tài khoản = profile trình duyệt đã gán Muse ở màn Profile trình duyệt. Dùng helper của app.js: $, $$, api, esc, toast… */
(() => {
  'use strict';

  const TABS = [['studio', '✦ Studio'], ['assets', '🗂 Tư liệu'], ['script', '🎬 Kịch bản'], ['ladi', '🛒 LadiPage'], ['sample', '📹 Video mẫu'],
    ['story', '🎞 Storyboard dài'], ['post', '🎚 Hậu kỳ'], ['progress', '📊 Tiến trình'], ['library', '🖼 Thư viện'], ['accounts', '👤 Tài khoản']];
  // Kịch bản: cách làm / thời lượng / giọng đọc (khớp app/muse_script.py)
  const METHODS = [['direct', 'Làm video thẳng · nhanh ~3 phút'], ['storyboard', 'Storyboard → tự làm video · đồng nhất, ~8 phút'],
    ['review', 'Storyboard → chờ tôi duyệt rồi làm video']];
  // Muse làm mỗi clip tối đa ~10 giây → dài hơn: app chia đoạn ≤ 10s (mỗi đoạn 1 lệnh) rồi tự ghép
  const DURS = [['10', '10 giây · 1 lệnh'], ['16', '16 giây · 2 đoạn tự ghép (2 × 8s)'], ['20', '20 giây · 2 đoạn tự ghép'],
    ['24', '24 giây · 3 đoạn tự ghép (3 × 8s)'], ['30', '30 giây · 3 đoạn tự ghép (3 × 10s)'], ['40', '40 giây · 4 đoạn tự ghép'],
    ['50', '50 giây · 5 đoạn tự ghép'], ['60', '60 giây · 6 đoạn tự ghép'], ['per_scene', 'Từng cảnh 10s · gửi lần lượt, app tự ghép']];
  const VOICES = [['none', 'Không lồng tiếng (giữ tiếng gốc)'], ['lipsync', 'Nhân vật tự nói — giọng Việt, khớp môi'],
    ['male_warm', 'Giọng nam · ấm, tin cậy'], ['male_energy', 'Giọng nam · trẻ, nhiều năng lượng'], ['male_deep', 'Giọng nam · trầm, thuyết phục'],
    ['female_warm', 'Giọng nữ · thân thiện, ấm áp'], ['female_bright', 'Giọng nữ · tươi sáng, dễ nghe'], ['female_fast', 'Giọng nữ · nhanh nhẹn, hợp TikTok']];
  const MOTIONS = [['zoom', '🔍 Zoom cận cảnh'], ['orbit', '🔄 Xoay 360°'], ['slide', '↔ Trượt ngang cinematic'], ['smoke', '🌫 Khói sương']];
  const GSTATUS = { running: 'Đang làm', finishing: 'Đang ghép…', done: 'Xong', failed: 'Lỗi', cancelled: 'Đã huỷ' };
  const H = {
    s: null, tab: 'studio', bound: false, sel: new Set(), q: '', filter: 'all',
    c: { kind: 'video', ratio: '9:16', duration: 10, text: '', images: [], pairing: 'shared', ideaOn: false, idea: '', ideaCount: 1, ideaStyle: '', ideaBusy: false },
    k: { mode: 'script', text: '', method: 'direct', ratio: '9:16', duration: '30', prefix: '', voice: 'none', presenter: '',
      character: '', merge: true, bgm: false, versions: 1, images: [], motions: ['zoom'], note: '' },
    ladi: { url: '', page: null, picked: [], local: [], scripts: null, checked: new Set(), noPrice: true, busy: '', showText: false },
    g: { filter: 'all', sel: new Set(), cur: null }, prog: { all: false }, post: { meta: null, hf: null, state: null, clips: [], form: {} },
    smp: { source: '', sample: null, busy: '', change: '', transcript: '', closeness: 'close', count: '3', scenes: '3', noPrice: true,
      images: [], docs: [], scripts: null, analysis: '', openAnalysis: false, checked: new Set(), ratio: '9:16', duration: '30', showSheet: false },
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
      else if (H.tab === 'progress') renderProgress();
      else if (H.tab === 'accounts' && !(document.activeElement && document.activeElement.closest('#mhAccounts input'))) renderAccounts();
      else if (H.tab === 'assets' && !(document.activeElement && document.activeElement.closest('#mhAssets'))) renderAssets();
      if (H.detail) paintDetail();
    } else if (event === 'mhub_log') {
      const t = H.s && H.s.tasks.find(x => x.id === data.id);
      if (t) { t.log = [...(t.log || []), data.line].slice(-40); if (H.detail === data.id) paintDetail(); }
      const pl = document.querySelector(`#mhProgress [data-plog="${CSS.escape(data.id)}"]`);
      if (pl) pl.textContent = String(data.line).replace(/^\d\d:\d\d:\d\d\s*/, '');
    } else if (event === 'mhub_post') {
      const P = H.post;
      if (!P.state) return;
      const i = P.state.jobs.findIndex(j => j.id === data.id);
      if (i >= 0) P.state.jobs[i] = data; else P.state.jobs.unshift(data);
      if (['done', 'failed', 'cancelled'].includes(data.status)) {
        if (data.status === 'done') toast(`Đã xong video hậu kỳ “${data.name}”`, 'ok');
        api('mhub_post_state').then(r => { if (r.ok) { P.state = r.state; if (H.tab === 'post') renderPostJobs(); } });
      }
      if (H.tab === 'post') renderPostJobs();
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
    if (H.tab === 'sample') renderSample();
    if (H.tab === 'story') window.MuseStudioPage.show();
    if (H.tab === 'progress') renderProgress();
    if (H.tab === 'post') showPost();
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
            <small>${esc(t.ratio || 'tự do')}${t.kind === 'video' && t.duration ? ` · ⏱ ${t.duration}s` : ''}${t.group && t.role === 'scene' ? ` · <b class="mh-part">Phần ${t.scene}/${H.s.tasks.filter(x => x.group === t.group && x.role === 'scene').length}</b>` : ''}${t.images.length ? ` · ${t.images.length} ảnh` : ''}${t.account ? ` · 👤 ${esc(accName(t.account))}` : ''}${t.attempts > 1 ? ` · lần ${t.attempts}` : ''} · ${fmt(t.created_at)}</small>
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

  // ------------------------------------------------------------ tab Kịch bản
  const sel = (id, list, cur) => `<select id="${id}">${list.map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const parseVideos = text => String(text || '').split(/\n\s*\n/).map(b => b.split('\n').map(x => x.trim()).filter(Boolean)).filter(v => v.length);

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
  const GFILTERS = [['all', 'Tất cả'], ['queued', 'Chờ'], ['running', 'Đang làm'], ['done', 'Xong'], ['failed', 'Lỗi']];
  const gcat = g => {
    if (g.status === 'done') return 'done';
    if (g.status === 'failed' || g.status === 'cancelled') return 'failed';
    if (g.status === 'finishing' || g.tasks.some(t => t.status === 'processing')) return 'running';
    return 'queued';
  };
  // đợt tạo mới nhất trên cùng; trong 1 đợt theo đúng số thứ tự kịch bản (#01 → #n)
  const projGroups = () => H.s.groups.filter(g => (g.project || 'default') === H.s.current)
    .sort((a, b) => (b.batch || 0) - (a.batch || 0) || (a.no || 0) - (b.no || 0) || b.created_at - a.created_at);
  const gNo = g => (g.no ? `#${String(g.no).padStart(2, '0')}` : '');

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

  // ------------------------------------------------------------ tab Tiến trình: theo dõi mọi việc Muse đang / sắp / vừa làm
  const mmss = ms => { const s = Math.max(0, Math.round(ms / 1000)); return s >= 3600 ? `${Math.floor(s / 3600)}:${pad2(Math.floor(s / 60) % 60)}:${pad2(s % 60)}` : `${Math.floor(s / 60)}:${pad2(s % 60)}`; };
  const startOfDay = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const projName = id => (H.s.projects.find(p => p.id === (id || 'default')) || {}).name || 'Mặc định';
  const taskLabel = t => (t.role === 'storyboard' ? 'Storyboard' : t.scene ? `Cảnh ${t.scene}` : t.kind === 'video' ? 'Video' : 'Ảnh');
  const firstLine = t => String(t.prompt || '').split('\n')[0];

  function avgSecs(kind) {  // thời gian trung bình 20 lượt xong gần nhất cùng loại → ước tính tiến độ
    const done = H.s.tasks.filter(t => t.kind === kind && t.status === 'succeeded' && t.started_at && t.finished_at > t.started_at)
      .sort((a, b) => b.finished_at - a.finished_at).slice(0, 20);
    if (!done.length) return kind === 'video' ? 180 : 60;
    return done.reduce((n, t) => n + (t.finished_at - t.started_at) / 1000, 0) / done.length;
  }

  function waitReason(t, ctx) {
    if (t.status === 'waiting') return 'Chờ storyboard xong';
    if (t.status === 'review') return 'Chờ bạn duyệt storyboard';
    if (H.s.stopped) return 'Hàng đợi đang dừng';
    if ((H.s.projects.find(p => p.id === (t.project || 'default')) || {}).paused) return 'Dự án đang tạm dừng';
    if (!ctx.usable) return 'Không có tài khoản Muse rảnh';
    if (ctx.free <= 0) return 'Chờ luồng trống';
    return 'Sắp chạy';
  }

  function renderProgress() {
    const el = $('#mhProgress');
    if (!el) return;
    const P = H.prog;
    const now = Date.now();
    const tasks = H.s.tasks.filter(t => P.all || (t.project || 'default') === H.s.current);
    const running = tasks.filter(t => t.status === 'processing');
    const pending = tasks.filter(t => ['queued', 'waiting', 'review'].includes(t.status)).sort((a, b) => a.created_at - b.created_at);
    const today = startOfDay();
    const doneToday = tasks.filter(t => t.status === 'succeeded' && t.finished_at >= today);
    const failToday = tasks.filter(t => t.status === 'failed' && t.finished_at >= today);
    const finished = tasks.filter(t => ['succeeded', 'failed', 'cancelled'].includes(t.status) && t.finished_at)
      .sort((a, b) => b.finished_at - a.finished_at).slice(0, 12);
    const accs = H.s.accounts.filter(a => a.enabled || a.running);
    const slots = accs.filter(a => a.enabled).reduce((n, a) => n + (+a.threads || 1), 0);
    const total = Math.min(slots, +H.s.settings.total_threads || slots);
    const allRunning = H.s.tasks.filter(t => t.status === 'processing').length;
    const ctx = { usable: H.s.accounts.some(a => a.enabled && a.usable), free: total - allRunning };
    const avg = { video: avgSecs('video'), image: avgSecs('image') };
    const avgOf = t => avg[t.kind === 'video' ? 'video' : 'image'];
    const accName = id => (H.s.accounts.find(a => a.id === id) || {}).name || '—';
    const stat = (cls, label, value, sub) => `<div class="mp-stat ${cls}"><small>${label}</small><b>${value}</b><span>${sub}</span></div>`;

    const runRow = t => {
      const spent = now - (t.started_at || now);
      const pct = Math.min(95, Math.round(spent / 10 / avgOf(t)));
      const last = ((t.log || []).slice(-1)[0] || 'Đang gửi lệnh cho Muse…').replace(/^\d\d:\d\d:\d\d\s*/, '');
      return `<div class="mp-run" data-ptask="${esc(t.id)}">
        <div class="mp-run-top"><span class="mh-gstep processing">${esc(taskLabel(t))}</span>
          <p title="${esc(t.prompt)}">${esc(firstLine(t))}</p>
          <b class="mp-time" data-since="${t.started_at || now}" data-avg="${avgOf(t)}">${mmss(spent)}</b>
          <button class="btn ghost sm" data-pcancel="${esc(t.id)}" type="button" title="Huỷ việc này">■ Huỷ</button></div>
        <div class="mp-bar"><i style="width:${pct}%"></i></div>
        <div class="mp-run-foot"><small class="mp-last" data-plog="${esc(t.id)}">${esc(last)}</small>
          <small class="muted">${P.all ? `${esc(projName(t.project))} · ` : ''}lần ${t.attempts || 1} · thường ~${mmss(avgOf(t) * 1000)}</small></div>
      </div>`;
    };

    const lanes = accs.map(a => {
      const mine = running.filter(t => t.account === a.id);
      const pct = a.quota ? Math.min(100, Math.round(a.quota.pct)) : null;
      const lvl = !a.enabled ? '' : mine.length ? 'run' : a.usable ? 'ok' : 'warn';
      const txt = !a.enabled ? 'Đã tắt' : mine.length ? 'Đang làm' : a.usable ? 'Rảnh' : 'Không dùng được';
      return `<section class="card mp-lane ${mine.length ? 'busy' : ''}">
        <div class="mp-lane-head"><b>👤 ${esc(a.name)}</b><span class="mh-pill ${lvl}">${txt}</span>
          <span class="mh-top-sp"></span><small class="muted">${a.running}/${a.threads || 1} luồng</small>
          ${pct != null ? `<span class="mh-qbar mp-quota ${pct >= 100 ? 'out' : pct >= 80 ? 'low' : ''}" title="Hạn mức tuần đã dùng ${pct}%"><i style="width:${pct}%"></i></span><small class="muted">${pct}%</small>` : ''}</div>
        ${mine.length ? mine.map(runRow).join('') : `<small class="mp-idle">${a.enabled ? (a.usable ? 'Rảnh — chờ việc mới trong hàng đợi' : esc(a.error || 'Hết hạn mức hoặc chưa đăng nhập')) : 'Bật lại ở tab Tài khoản'}</small>`}
      </section>`;
    }).join('') || '<div class="card mk-empty"><b>Chưa có tài khoản Muse</b><small>Thêm ở tab Tài khoản.</small></div>';
    const orphan = running.filter(t => !accs.some(a => a.id === t.account));

    el.innerHTML = `<div class="mp-head"><div class="mh-seg sm">${[[0, 'Dự án này'], [1, 'Tất cả dự án']].map(([v, l]) => `<button class="${+P.all === v ? 'on' : ''}" data-pall="${v}" type="button">${l}</button>`).join('')}</div>
        <small class="muted">${P.all ? `${H.s.projects.length} dự án` : esc(proj().name)} · cập nhật trực tiếp</small>
        <span class="mh-top-sp"></span>
        ${failToday.length ? `<button class="btn ghost sm" data-pretry-failed="${esc(failToday.map(t => t.id).join(','))}" type="button">↻ Chạy lại ${failToday.length} lỗi hôm nay</button>` : ''}
        ${H.s.stopped ? '<button class="btn primary sm" data-act="resume" type="button">▶ Chạy tiếp</button>' : '<button class="btn ghost sm mh-stop" data-act="stop" type="button">■ Dừng tất cả</button>'}</div>
      <div class="mp-stats">
        ${stat('run', 'Đang chạy', running.length, `${allRunning}/${total || 0} luồng toàn hệ thống`)}
        ${stat('', 'Đang chờ', pending.length, `${pending.filter(t => t.status === 'review').length} chờ duyệt · ${pending.filter(t => t.status === 'waiting').length} chờ storyboard`)}
        ${stat('ok', 'Xong hôm nay', doneToday.length, `${doneToday.filter(t => t.kind === 'video').length} video · ${doneToday.filter(t => t.kind !== 'video').length} ảnh`)}
        ${stat(failToday.length ? 'bad' : '', 'Lỗi hôm nay', failToday.length, failToday.length ? 'xem ở “Vừa xong”' : 'không có lỗi')}
        ${stat('', 'Thời gian TB / video', mmss(avg.video * 1000), `ảnh ${mmss(avg.image * 1000)}`)}
      </div>
      <div class="mp-main">
        <div class="mp-col"><div class="mp-title"><b>Đang xử lý theo tài khoản</b><small class="muted">${running.length} việc</small></div>${lanes}
          ${orphan.length ? `<section class="card mp-lane busy"><div class="mp-lane-head"><b>Tài khoản khác</b></div>${orphan.map(runRow).join('')}</section>` : ''}</div>
        <div class="mp-col">
          <section class="card mp-list"><div class="mp-title"><b>Sắp chạy</b><small class="muted">${pending.length} việc · theo thứ tự vào hàng</small></div>
            <div class="mp-items">${pending.length ? pending.slice(0, 30).map((t, i) => `<div class="mp-item" data-ptask="${esc(t.id)}"><span class="mp-n">${i + 1}</span>
              <div class="mh-tbody"><p>${esc(taskLabel(t))} · ${esc(firstLine(t))}</p>
                <small class="${t.status === 'review' ? 'mp-warn' : ''}">${esc(waitReason(t, ctx))}${P.all ? ` · ${esc(projName(t.project))}` : ''} · vào hàng ${fmt(t.created_at)}</small></div>
              ${t.status === 'review' && t.group ? `<button class="btn primary sm" data-gapprove="${esc(t.group)}" type="button">Duyệt</button>` : ''}</div>`).join('')
              + (pending.length > 30 ? `<small class="muted">… và ${pending.length - 30} việc nữa</small>` : '')
            : '<small class="mp-idle">Hàng đợi trống.</small>'}</div></section>
          <section class="card mp-list"><div class="mp-title"><b>Vừa xong</b><small class="muted">12 việc gần nhất</small></div>
            <div class="mp-items">${finished.length ? finished.map(t => `<div class="mp-item" data-ptask="${esc(t.id)}">
              <span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status] || t.status)}</span>
              <div class="mh-tbody"><p>${esc(taskLabel(t))} · ${esc(firstLine(t))}</p>
                <small>${t.started_at ? `mất ${mmss(t.finished_at - t.started_at)} · ` : ''}👤 ${esc(accName(t.account))} · ${fmt(t.finished_at)}</small>
                ${t.error && t.status !== 'succeeded' ? `<small class="mh-err">${esc(t.error.slice(0, 160))}</small>` : ''}</div>
              ${t.status === 'succeeded' && t.files.length ? `<button class="btn ghost sm" data-open-task-file="${esc(t.files[0].path)}" type="button" title="Mở thư mục chứa file">📂</button>`
                : t.status !== 'succeeded' ? `<button class="btn ghost sm" data-pretry="${esc(t.id)}" type="button" title="Chạy lại">↻</button>` : ''}</div>`).join('')
            : '<small class="mp-idle">Chưa có việc nào xong.</small>'}</div></section>
        </div>
      </div>`;
  }

  function tickProgress() {  // đồng hồ + thanh tiến độ chạy từng giây, không vẽ lại cả tab
    const page = $('#page-mstudio');
    if (H.tab !== 'progress' || !page || page.classList.contains('hidden')) return;
    const now = Date.now();
    $$('#mhProgress .mp-time').forEach(b => {
      const spent = now - +b.dataset.since;
      b.textContent = mmss(spent);
      const bar = b.closest('.mp-run').querySelector('.mp-bar i');
      if (bar) bar.style.width = `${Math.min(95, Math.round(spent / 10 / +b.dataset.avg))}%`;
    });
  }
  setInterval(tickProgress, 1000);

  // ------------------------------------------------------------ tab Video mẫu: phân tích video mẫu → kịch bản tương tự
  const nearestDur = secs => DURS.filter(d => d[0] !== 'per_scene').reduce((best, d) => (Math.abs(+d[0] - secs) < Math.abs(+best[0] - secs) ? d : best))[0];
  const CLOSE = [['close', 'Bám sát — cùng cấu trúc, nhịp'], ['inspire', 'Lấy ý tưởng — sáng tạo hơn']];

  function renderSample() {
    const M = H.smp;
    const s = M.sample;
    const step = n => (n === 1 ? 'on' : n === 2 ? (s ? 'on' : '') : n === 3 ? (M.scripts ? 'on' : '') : (M.checked.size ? 'on' : ''));
    const chip = (t, cls = '') => `<span class="mh-pill ${cls}">${t}</span>`;
    $('#mhSample').innerHTML = `<div class="card mh-ladihead"><b class="mh-h">📹 Tạo video từ video mẫu</b>
        <small class="muted">Chọn video mẫu (file trên máy hoặc link TikTok / YouTube / Facebook…). App tự cắt khung đổi cảnh, rồi Muse phân tích và viết kịch bản tương tự cho nội dung của bạn.</small>
        <div class="mh-steps">${['Chọn video mẫu', 'Đổi nội dung, đính kèm', 'Sửa kịch bản', 'Đưa vào hàng đợi'].map((x, i) => `<span class="${step(i + 1)}"><i>${i + 1}</i>${x}</span>`).join('')}</div>
        <div class="mh-row"><input id="mhSmpUrl" value="${esc(M.source)}" placeholder="Dán link video mẫu, hoặc bấm Chọn file">
          <button class="btn ghost" data-act="smp-pick" type="button" ${M.busy ? 'disabled' : ''}>📂 Chọn file</button>
          <button class="btn primary" data-act="smp-go" type="button" ${M.busy ? 'disabled' : ''}>${M.busy && !s ? esc(M.busy) : '🔍 Phân tích video'}</button></div>
        ${M.busy ? `<small class="muted">${esc(M.busy)}</small>` : ''}</div>
      ${s ? `<div class="card mk-form smp-form">
        <div class="mk-left">
          <div class="mh-card-head"><b>${esc(s.title)}</b><button class="link" data-act="smp-sheet" type="button">${M.showSheet ? 'Xem từng khung' : 'Xem ảnh lưới gửi Muse'}</button></div>
          <div class="smp-chips">${chip(`${Math.round(s.duration)} giây`)}${chip(esc(s.ratio))}${chip(`${s.cuts} lần cắt cảnh`)}${chip(`~${s.avg_shot}s / cảnh`)}
            ${chip(s.has_audio ? 'Có tiếng' : 'Không tiếng')}${s.subtitles ? chip('Có phụ đề', 'ok') : ''}</div>
          ${M.showSheet ? `<img class="smp-sheet" src="${esc(s.sheet_url)}" alt="" data-zoom="${esc(s.sheet_url)}">`
            : `<div class="smp-frames ${s.height > s.width ? 'vert' : ''}">${s.frames.map(f => `<button class="smp-frame" data-zoom="${esc(f.url)}" type="button"><img src="${esc(f.url)}" alt="" loading="lazy"><span>${mmss(f.t * 1000)}</span></button>`).join('')}</div>`}
        </div>
        <div class="mk-left">
          <label class="field"><span>Nội dung mới <small class="muted">— đổi gì so với video mẫu: sản phẩm, thông điệp, đối tượng, ưu đãi…</small></span>
            <textarea id="mhSmpChange" rows="4" placeholder="VD: Đổi thành quảng cáo phân bón hữu cơ Boss 1 cho bà con trồng lúa miền Tây. Nhấn mạnh lúa xanh, chắc hạt. Người dẫn nữ, giọng miền Nam.">${esc(M.change)}</textarea></label>
          <label class="field"><span>Lời thoại video mẫu <small class="muted">(tuỳ chọn${s.subtitles ? ' — đã lấy phụ đề từ link' : ' — dán vào để Muse hiểu rõ hơn'})</small></span>
            <textarea id="mhSmpTranscript" rows="2" placeholder="${s.subtitles ? 'Để trống = dùng phụ đề lấy từ link' : 'Dán lời thoại / chữ trên video mẫu nếu có'}">${esc(M.transcript)}</textarea></label>
          <div class="smp-opts">
            <label class="field"><span>Mức bám mẫu</span>${sel('mhSmpClose', CLOSE, M.closeness)}</label>
            <label class="field"><span>Số kịch bản</span>${sel('mhSmpCount', [['1', '1'], ['2', '2'], ['3', '3']], M.count)}</label>
            <label class="field"><span>Số cảnh / video</span>${sel('mhSmpScenes', [2, 3, 4, 5, 6, 8].map(n => [String(n), `${n} cảnh`]), M.scenes)}</label>
          </div>
          <div class="smp-attach">
            <div class="smp-att"><b>Ảnh sản phẩm / nhân vật <small class="muted">(≤2 — gửi kèm Muse và mọi video)</small></b>
              <div class="mh-thumbs">${M.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt="" title="${esc(im.name || '')}"><button data-srm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
                ${M.images.length < 2 ? '<button class="mh-add" data-act="smp-add-img" type="button">＋ Ảnh</button>' : ''}</div></div>
            <div class="smp-att"><b>Tài liệu <small class="muted">(.txt .md .csv .docx .srt — thông tin sản phẩm, kịch bản thô…)</small></b>
              <div class="smp-docs">${M.docs.map((d, i) => `<span class="smp-doc" title="${esc(d.preview)}">📄 ${esc(d.name)} <small>${d.chars.toLocaleString('vi-VN')} ký tự</small><button data-sdoc-rm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
                ${M.docs.length < 5 ? '<button class="btn ghost sm" data-act="smp-add-doc" type="button">＋ Tài liệu</button>' : ''}</div></div>
          </div>
          <div class="smp-go"><label class="mh-switch" title="Lời chốt không đọc số tiền, chỉ nói giá ưu đãi để ở link"><input type="checkbox" id="mhSmpNoPrice" ${M.noPrice ? 'checked' : ''}><i></i> Không đọc giá</label>
            <button class="btn primary" data-act="smp-write" type="button" ${M.busy ? 'disabled' : ''}>${M.busy && s ? esc(M.busy) : '✦ Muse phân tích & viết kịch bản'}</button></div>
        </div></div>` : ''}
      ${M.scripts ? `<div class="card mh-ladiscripts">
        ${M.analysis ? `<details class="smp-analysis" ${M.openAnalysis ? 'open' : ''}><summary><b>Muse phân tích video mẫu</b> <small class="muted">bấm để xem / ẩn</small></summary><pre class="mh-ladi-text">${esc(M.analysis)}</pre></details>` : ''}
        <div class="mh-card-head"><b>Kịch bản mới</b><small class="muted">sửa được lời thoại và hình từng cảnh trước khi đưa vào hàng đợi</small></div>
        <div class="mh-lscripts">${M.scripts.scripts.map((x, i) => `<div class="mh-lscript ${M.checked.has(i) ? 'on' : ''}">
            <label class="check"><input type="checkbox" data-scheck="${i}" ${M.checked.has(i) ? 'checked' : ''}> <b>${esc(x.title)}</b></label>
            ${x.angle ? `<small class="muted">${esc(x.angle)}</small>` : ''}
            ${x.scenes.map((c, j) => `<div class="mh-lscene"><span>Cảnh ${j + 1}</span>
              <textarea data-sline="${i}:${j}" rows="2" placeholder="Lời thoại">${esc(c.line)}</textarea>
              <textarea data-svis="${i}:${j}" rows="2" placeholder="Hình ảnh cảnh quay">${esc(c.visual)}</textarea></div>`).join('')}
          </div>`).join('')}</div>
        <div class="smp-queue">
          <label class="field"><span>Tỉ lệ <small class="muted">(theo video mẫu)</small></span>${sel('mhSmpRatio', [['9:16', '9:16 · Dọc'], ['16:9', '16:9 · Ngang'], ['1:1', '1:1 · Vuông']], M.ratio)}</label>
          <label class="field"><span>Thời lượng <small class="muted">(gần video mẫu)</small></span>${sel('mhSmpDur', DURS, M.duration)}</label>
          <small class="muted smp-note">Cách làm, giọng đọc, người dẫn, nhạc nền theo tab <button class="link" data-tab-go="script" type="button">Kịch bản</button>
            (${esc((METHODS.find(m => m[0] === H.k.method) || METHODS[0])[1].split(' ·')[0])}).</small>
          <span class="mh-top-sp"></span>
          <button class="btn ghost sm" data-act="smp-all" type="button">Tích cả</button>
          <button class="btn ghost" data-act="smp-preview" type="button" ${M.checked.size ? '' : 'disabled'}>Xem lệnh</button>
          <button class="btn primary" data-act="smp-queue" type="button" ${M.checked.size ? '' : 'disabled'}>＋ Đưa ${M.checked.size} kịch bản vào hàng đợi</button></div></div>` : ''}`;
  }

  async function samplePrepare(source) {
    const M = H.smp;
    if (!String(source || '').trim()) return toast('Dán link video mẫu hoặc chọn file', 'warn');
    M.source = source; M.busy = 'Đang lấy video và cắt khung hình…'; renderSample();
    const r = await api('mhub_sample_prepare', source);
    M.busy = '';
    if (!r.ok) { renderSample(); return toast(r.error, 'error'); }
    M.sample = r.sample; M.scripts = null; M.analysis = ''; M.checked = new Set();
    M.ratio = r.sample.ratio; M.duration = nearestDur(r.sample.duration);
    M.scenes = String([2, 3, 4, 5, 6, 8].reduce((b, n) => (Math.abs(n - (r.sample.cuts + 1)) < Math.abs(b - (r.sample.cuts + 1)) ? n : b), 3));
    renderSample();
  }

  async function sampleWrite() {
    const M = H.smp;
    if (!M.change.trim() && !M.docs.length) return toast('Nhập nội dung mới hoặc đính kèm tài liệu', 'warn');
    if (M.scripts && !confirm('Viết lại kịch bản (mất chữ đã sửa)?')) return;
    M.busy = 'Muse đang xem video mẫu và viết kịch bản (1–3 phút)…'; renderSample();
    const secs = M.duration === 'per_scene' ? +M.scenes * 10 : +M.duration;
    const r = await api('mhub_sample_scripts', M.sample.id, { change: M.change, transcript: M.transcript, closeness: M.closeness,
      count: +M.count, scenes: +M.scenes, seconds: secs, no_price: M.noPrice, images: M.images.map(i => i.path), docs: M.docs.map(d => d.path) },
      '', !!H.s.settings.show_browser);
    M.busy = '';
    if (!r.ok) { renderSample(); return toast(r.error, 'error'); }
    M.scripts = r.result; M.analysis = r.result.analysis || ''; M.openAnalysis = true;
    M.checked = new Set(M.scripts.scripts.map((_, i) => i));
    renderSample();
  }

  function sampleForms(dry) {
    const M = H.smp;
    return [...M.checked].sort().map(i => {
      const x = M.scripts.scripts[i];
      return { ...kForm(), mode: 'script', ratio: M.ratio, duration: M.duration, product_images: [], images: M.images.map(im => im.path),
        title: `${M.scripts.name || M.sample.title} · ${x.title}`, text: x.scenes.map(sceneLine).join('\n'), dry };
    });
  }

  // ------------------------------------------------------------ tab Hậu kỳ: ghép video + lồng tiếng + chuyển cảnh + hậu kỳ AI
  const POST_DEF = { name: '', aspect: '9:16', audio: 'tts', voice: 'vi-VN-HoaiMyNeural', rate: '+0%', subtitles: true, bgm: true,
    bgm_volume: 0.12, transition: 'smoothleft', transition_duration: 0.5, transition_sound: 'none', transition_volume: 0.15,
    post_ai: false, post_style: 'basic', post_subs: true, post_audio: true, logo: '', logo_url: '', logo_corner: 'tr' };
  const postSave = () => { try { localStorage.setItem('va.mhub.post', JSON.stringify({ clips: H.post.clips, form: H.post.form })); } catch { /* bỏ qua */ } };
  (() => { H.post.form = { ...POST_DEF }; try { const d = JSON.parse(localStorage.getItem('va.mhub.post') || 'null'); if (d) { H.post.clips = d.clips || []; H.post.form = { ...POST_DEF, ...(d.form || {}) }; } } catch { /* bỏ qua */ } })();
  const fileName = p => String(p || '').split(/[\\/]/).pop();

  function hfText(h) {
    if (!h) return 'Không kiểm tra được Node.js / FFmpeg';
    if (!h.node_ok) return `⚠ Cần Node.js 22 trở lên (máy đang: ${esc(h.node || 'chưa cài')}) — tải ở nodejs.org rồi mở lại app.`;
    if (!h.ffprobe) return '⚠ Cần FFmpeg có ffprobe trong PATH (Windows: winget install Gyan.FFmpeg) rồi mở lại app.';
    return `✓ Node.js ${esc(h.node)} · FFmpeg sẵn sàng · ${h.installed ? `HyperFrames ${esc(h.version)} đã cài` : `lần chạy đầu app tự cài HyperFrames ${esc(h.version)} (cần internet)`}. Muse viết HTML + GSAP, máy bạn dựng video (~3 phút cho 1 phút video); lỗi thì quay về phụ đề thường.`;
  }

  async function showPost() {
    const P = H.post;
    if (!P.meta) {
      const [m, hf] = await Promise.all([api('mhub_post_meta'), api('hyperframes_status')]);
      if (!m.ok) return toast(m.error, 'error');
      P.meta = m.meta; P.hf = hf.ok ? hf.status : null;
    }
    const st = await api('mhub_post_state');
    if (st.ok) P.state = st.state;
    renderPost();
  }

  function renderPost() {
    const el = $('#mhPost');
    if (!el || !H.post.meta) return;
    el.innerHTML = `<div class="pp-main"><section class="card pp-clips" id="mhPostClips"></section><section class="card pp-opts" id="mhPostOpts"></section></div>
      <section class="card pp-jobs" id="mhPostJobs"></section>`;
    renderPostClips(); renderPostOpts(); renderPostJobs();
  }

  function renderPostClips() {
    const P = H.post;
    const box = $('#mhPostClips');
    if (!box) return;
    const needText = P.form.audio !== 'mute';
    const total = P.clips.reduce((n, c) => n + (c.dur || 0), 0);
    box.innerHTML = `<div class="mh-card-head"><b>Cảnh ghép</b><small class="muted">${P.clips.length} video${total ? ` · ~${Math.round(total)}s` : ''} · kéo ⋮⋮ để đổi thứ tự</small>
        <span class="mh-top-sp"></span>
        <button class="btn ghost sm" data-act="pp-lib" type="button">＋ Từ Thư viện</button>
        <button class="btn ghost sm" data-act="pp-pick" type="button">＋ Từ máy</button>
        ${P.clips.length ? '<button class="link danger" data-act="pp-clear" type="button">Xoá hết</button>' : ''}</div>
      <div class="pp-list">${P.clips.length ? P.clips.map((c, i) => `<div class="pp-clip" data-pp-row="${i}">
          <span class="pp-grip" draggable="true" data-pp-drag="${i}" title="Kéo để đổi thứ tự">⋮⋮<b>${i + 1}</b></span>
          ${c.url ? `<video src="${esc(c.url)}" muted preload="metadata" data-pp-dur="${i}"></video>` : '<span class="pp-ph" title="Video trên máy">🎬</span>'}
          <div class="pp-body"><div class="pp-name"><b title="${esc(c.path)}">${esc(c.title || fileName(c.path))}</b><small class="muted" id="ppDur${i}">${c.dur ? `${c.dur.toFixed(1)}s` : ''}</small></div>
            ${needText ? `<textarea data-pp-text="${i}" rows="2" placeholder="${P.form.audio === 'tts' ? 'Lời đọc cho cảnh này (lồng tiếng AI + phụ đề). Để trống = cảnh không lời' : 'Lời thoại trong clip (để làm phụ đề) — tuỳ chọn'}">${esc(c.text || '')}</textarea>` : ''}</div>
          <div class="pp-acts"><button class="btn ghost sm" data-pp-up="${i}" type="button" ${i ? '' : 'disabled'} title="Lên">↑</button>
            <button class="btn ghost sm" data-pp-down="${i}" type="button" ${i < P.clips.length - 1 ? '' : 'disabled'} title="Xuống">↓</button>
            <button class="btn ghost sm st-pdel" data-pp-rm="${i}" type="button" title="Bỏ">✕</button></div>
        </div>`).join('') : `<div class="mk-empty"><b>Chưa có video nào</b><small>Thêm video từ Thư viện của Studio Muse AI hoặc từ máy, sắp xếp thứ tự rồi bấm “Ghép & hậu kỳ”.</small></div>`}</div>`;
  }

  function renderPostOpts() {
    const P = H.post, f = P.form, m = P.meta;
    const box = $('#mhPostOpts');
    if (!box) return;
    const opts = (list, cur) => list.map(x => (typeof x === 'object' ? [x.value ?? x.id, x.label ?? x.name] : [x, x]))
      .map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');
    box.innerHTML = `
      <div class="pp-row2"><label class="field"><span>Tên video</span><input data-pf="name" value="${esc(f.name)}" placeholder="Video hậu kỳ"></label>
        <label class="field"><span>Tỉ lệ khung</span><select data-pf="aspect">${opts(m.aspects, f.aspect)}</select></label></div>
      <div class="field"><span>Âm thanh</span><div class="mh-seg sm pp-seg">${m.audio_modes.map(a => `<button class="${f.audio === a.value ? 'on' : ''}" data-pp-audio="${a.value}" type="button">${esc(a.label)}</button>`).join('')}</div></div>
      ${f.audio === 'tts' ? `<div class="pp-row3"><label class="field"><span>Giọng đọc</span><select data-pf="voice">${opts(m.voices, f.voice)}</select></label>
        <label class="field"><span>Tốc độ đọc</span><select data-pf="rate">${opts(m.rates, f.rate)}</select></label>
        <div class="field"><span>&nbsp;</span><button class="btn ghost sm" data-act="pp-voice" type="button">▶ Nghe thử</button></div></div>`
      : `<small class="muted">${f.audio === 'original' ? 'Giữ nguyên giọng nói / âm thanh gốc trong từng clip; nhạc nền tự nhỏ lại để không lấn tiếng gốc.' : 'Không có giọng nói — chỉ nhạc nền và âm chuyển cảnh.'}</small>`}
      <div class="pp-checks"><label class="check"><input type="checkbox" data-pf="subtitles" ${f.subtitles ? 'checked' : ''}> Phụ đề</label>
        <label class="check"><input type="checkbox" data-pf="bgm" ${f.bgm ? 'checked' : ''}> Nhạc nền</label>
        ${f.bgm ? `<label class="pp-range" title="Âm lượng nhạc nền"><input type="range" data-pf="bgm_volume" min="0" max="0.4" step="0.01" value="${f.bgm_volume}"><small id="ppBgmVol">${Math.round(f.bgm_volume * 100)}%</small></label>
          <button class="btn ghost sm" data-act="bgm-open" type="button" title="${esc(H.s.bgm_dir)}">📂 Nhạc</button>` : ''}</div>
      <div class="pp-box"><b class="pp-h">Chuyển cảnh khi ghép</b>
        <div class="pp-row4"><label class="field"><span>Kiểu chuyển cảnh</span><select data-pf="transition">${opts(m.transitions, f.transition)}</select></label>
          <label class="field"><span>Thời lượng</span><select data-pf="transition_duration">${opts(m.durations.map(d => ({ value: d, label: `${String(d).replace('.', ',')} giây` })), f.transition_duration)}</select></label>
          <label class="field"><span>Âm chuyển cảnh</span><div class="pp-inline"><select data-pf="transition_sound">${opts(m.sounds, f.transition_sound)}</select>
            <button class="btn ghost sm" data-act="pp-sound" type="button" title="Nghe thử âm chuyển cảnh">🔊</button></div></label>
          <label class="field"><span>Âm lượng âm chuyển · <b id="ppSndVol">${Math.round(f.transition_volume * 100)}%</b></span>
            <input type="range" data-pf="transition_volume" min="0" max="1.5" step="0.05" value="${f.transition_volume}"></label></div></div>
      <div class="pp-box ${f.post_ai ? 'on' : ''}"><div class="pp-aihead"><label class="mh-switch"><input type="checkbox" data-pf="post_ai" ${f.post_ai ? 'checked' : ''}><i></i> <b>✨ Hậu kỳ AI sau bước ghép</b></label>
          <span class="mh-pill ${f.post_ai ? 'ok' : ''}">${f.post_ai ? 'ĐANG BẬT' : 'ĐANG TẮT'}</span></div>
        <small class="muted">Muse đọc lời dẫn + nội dung từng cảnh: viết câu hook đầu video, tô nổi từ khoá trên phụ đề, gắn hiệu ứng âm thanh, chọn mức nhạc nền. Cảnh không lời vẫn có hook + hiệu ứng; HyperFrames dựng đồ hoạ động cả khi không lời. Muse lỗi thì vẫn ghép bình thường.</small>
        ${f.post_ai ? `<label class="field"><span>Kiểu hậu kỳ</span><select data-pf="post_style">${opts(m.post_styles, f.post_style)}</select></label>
          ${f.post_style === 'hyperframes' ? `<small class="pp-hf ${P.hf && P.hf.node_ok && P.hf.ffprobe ? 'ok' : ''}">${hfText(P.hf)}</small>` : ''}
          <div class="pp-checks"><label class="check"><input type="checkbox" data-pf="post_subs" ${f.post_subs ? 'checked' : ''}> Phụ đề nổi bật</label>
            <label class="check"><input type="checkbox" data-pf="post_audio" ${f.post_audio ? 'checked' : ''}> Âm thanh nổi bật</label></div>` : ''}</div>
      ${(() => {  // đóng logo: ô logo · khung video thu nhỏ đúng tỉ lệ, bấm góc để chọn vị trí · tóm tắt
        const corners = m.logo_corners || [];
        const label = (corners.find(c => c.value === f.logo_corner) || {}).label || '';
        const ratio = { '16:9': '16 / 9', '1:1': '1 / 1' }[f.aspect] || '9 / 16';
        return `<div class="pp-box pp-logo ${f.logo ? 'on' : ''}" data-pp-logo-drop>
        <div class="pp-logohead"><b class="pp-h">🏷 Đóng logo lên video</b>
          <span class="mh-pill ${f.logo ? 'ok' : ''}">${f.logo ? `Đang đóng · ${esc(label)}` : 'Chưa có logo'}</span></div>
        <div class="pp-logogrid">
          <div class="pp-logocard">${f.logo ? `<span class="pp-logoimg" title="Logo"><img src="${esc(f.logo_url)}" alt=""></span>
              <div class="pp-logobtns"><button class="btn ghost sm" data-act="pp-logo" type="button">Đổi</button><button class="btn ghost sm st-pdel" data-act="pp-logo-rm" type="button">Bỏ</button></div>`
            : `<button class="pp-logoadd" data-act="pp-logo" type="button"><b>＋</b>Chọn logo<small>hoặc kéo thả ảnh</small></button>`}</div>
          <div class="pp-frame ${f.logo ? '' : 'off'}" style="aspect-ratio:${ratio}" title="Bấm vào góc để chọn vị trí logo">
            ${corners.map(c => `<button class="pp-corner ${c.value} ${f.logo_corner === c.value ? 'on' : ''}" data-pp-corner="${c.value}" type="button" title="${esc(c.label)}" ${f.logo ? '' : 'disabled'}>
              ${f.logo_corner === c.value && f.logo ? `<img src="${esc(f.logo_url)}" alt="">` : '<i></i>'}</button>`).join('')}
            <span class="pp-subzone">phụ đề</span></div>
          <div class="pp-logonote"><b>${f.logo ? esc(label) : 'Vị trí logo'}</b>
            <small class="muted">Bấm vào góc trong khung để đổi vị trí. Logo rộng ~${f.aspect === '16:9' ? '10' : '18'}% khung, cách mép một khoảng an toàn, góc dưới chừa chỗ phụ đề.</small>
            <small class="muted">PNG nền trong suốt đẹp nhất · đóng sau cùng (cả khi dùng HyperFrames).</small></div>
        </div></div>`;
      })()}
      <button class="btn primary pp-go" data-act="pp-start" type="button" ${P.clips.length ? '' : 'disabled'}>🎬 Ghép & hậu kỳ${P.clips.length ? ` (${P.clips.length} cảnh)` : ''}</button>`;
  }

  function renderPostJobs() {
    const P = H.post;
    const box = $('#mhPostJobs');
    if (!box) return;
    const st = P.state || { jobs: [], done: [] };
    const live = st.jobs.filter(j => ['queued', 'running'].includes(j.status) || (['failed', 'cancelled'].includes(j.status) && Date.now() - j.created_at < 3600e3));
    clearTimeout(P.poll);  // dự phòng sự kiện: còn video đang làm → hỏi lại trạng thái mỗi 2 giây
    if (st.jobs.some(j => ['queued', 'running'].includes(j.status))) {
      P.poll = setTimeout(async () => {
        if (H.tab !== 'post') return;
        const r = await api('mhub_post_state');
        if (r.ok) { P.state = r.state; renderPostJobs(); }
      }, 2000);
    }
    const SL = { queued: 'Chờ', running: 'Đang làm', failed: 'Lỗi', cancelled: 'Đã dừng', done: 'Xong' };
    box.innerHTML = `${live.length ? `<div class="mp-title"><b>Đang hậu kỳ</b></div>
      <div class="pp-live">${live.map(j => `<div class="mp-run pp-job"><div class="mp-run-top"><span class="mh-status ${j.status === 'running' ? 'processing' : j.status === 'failed' ? 'failed' : 'queued'}">${SL[j.status]}</span>
          <p><b>${esc(j.name)}</b> · ${j.clips} cảnh · ${esc(j.stage)}</p><b class="mp-time">${j.pct}%</b>
          ${['queued', 'running'].includes(j.status) ? `<button class="btn ghost sm" data-pp-cancel="${esc(j.id)}" type="button">■ Dừng</button>` : ''}</div>
        <div class="mp-bar"><i style="width:${j.pct}%"></i></div>
        ${j.error ? `<small class="mh-err">${esc(j.error)}</small>` : `<small class="mp-last">${esc(((j.log || []).slice(-1)[0] || '').replace(/^\d\d:\d\d:\d\d\s*/, ''))}</small>`}</div>`).join('')}</div>` : ''}
      <div class="mp-title"><b>Video hậu kỳ đã làm</b><small class="muted">${st.done.length} video · cũng có trong Thư viện video</small></div>
      <div class="pp-done">${st.done.length ? st.done.map((d, i) => `<figure class="pp-out">
          <video src="${esc(d.url)}" controls preload="metadata"></video>
          <figcaption><div><b title="${esc(d.title)}">${esc(d.title)}</b><small class="muted">${Math.round(d.duration)}s · ${esc(d.aspect)} · ${d.clips} cảnh${d.post && d.post.model ? ' · ✨ AI' : ''}</small></div>
            <button class="btn ghost sm" data-pp-open="${esc(d.path)}" type="button" title="Mở thư mục, chọn sẵn file">📂</button></figcaption>
          <div class="pp-outacts"><button class="btn ghost sm" data-pp-redo="${i}" type="button" title="Nạp lại cảnh + lời đọc + thiết lập của video này để chỉnh và ghép bản mới">✎ Hậu kỳ lại</button>
            <button class="btn ghost sm" data-pp-useclip="${i}" type="button" title="Thêm cả video này vào danh sách cảnh (hậu kỳ chồng lên / ghép nối)">＋ Dùng làm cảnh</button></div></figure>`).join('')
        : '<small class="mp-idle">Chưa có video hậu kỳ nào.</small>'}</div>`;
  }

  async function postAddFiles(paths) {
    if (!paths || !paths.length) return;
    const r = await api('mhub_post_probe', paths);
    const durs = r.ok ? Object.fromEntries(r.items.map(x => [x.path, x.duration])) : {};
    H.post.clips = [...H.post.clips, ...paths.map(p => ({ path: p, url: '', title: fileName(p).replace(/\.\w+$/, ''), text: '', dur: durs[p] || 0 }))].slice(0, 40);
    postSave(); renderPostClips(); renderPostOpts();
  }

  // chọn video cho Hậu kỳ: nhóm theo kịch bản (cảnh đúng thứ tự) + lọc dự án; số trên ô = thứ tự ghép
  const lineText = s => { const m = String(s || '').match(/Lời thoại:\s*[“"]([^”"]+)[”"]/); return m ? m[1].trim() : ''; };
  const sceneLabel = it => (it.role === 'storyboard' ? 'Storyboard' : it.scene ? `Cảnh ${it.scene}` : 'Video');

  async function postLibDialog(project = H.s.current) {
    const r = await api('mhub_post_sources', project);
    if (!r.ok) return toast(r.error, 'error');
    const src = r.sources;
    const items = [];   // mọi video chọn được (chỉ số = data-ppi)
    const order = [];   // chỉ số theo thứ tự đã chọn
    const add = (v, extra) => items.push({ ...v, ...extra }) - 1;
    const tile = (k, label, sub) => `<button class="pp-tile" data-ppi="${k}" type="button" title="${esc(items[k].title)}">
        <video src="${esc(items[k].url)}" muted preload="metadata"></video><span class="pp-badge"></span>
        <span class="pp-tlabel">${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ''}</button>`;
    const proj = p => (project ? '' : ` · ${projName(p)}`);
    const singles = [];  // kịch bản chỉ 1 video → chung 1 lưới (tên + giờ bên dưới), khỏi mỗi kịch bản 1 khối
    const groupsHtml = src.groups.map(g => {
      const all = g.lines.map(lineText).filter(Boolean).join(' ');
      if (g.scenes.length + g.outputs.length === 1) {
        const v = g.scenes[0] || { ...g.outputs[0], video: true };
        singles.push(tile(add(v, { title: g.title, text: all }), g.title, `${fmt(v.finished_at || g.created_at)}${proj(g.project)}`));
        return '';
      }
      const ids = g.scenes.map(s => add(s, { title: `${g.title} · ${sceneLabel(s)}`, text: s.role === 'scene' ? lineText(g.lines[s.scene - 1]) : all }));
      const outs = g.outputs.map(o => add({ ...o, video: true }, { title: `${g.title} · ${(o.label || 'bản ghép').toLowerCase()}`, text: all }));
      return `<section class="pp-grp"><div class="pp-grphead"><b>🎬 ${esc(g.title)}</b>
          <small class="muted">${g.versions > 1 ? `bản ${g.version}/${g.versions} · ` : ''}${g.scenes.length} cảnh · ${esc(fmt(g.created_at))}${project ? '' : ` · ${esc(projName(g.project))}`}</small>
          <span class="mh-top-sp"></span>${ids.length > 1 ? `<button class="btn ghost sm" data-ppg="${ids.join(',')}" type="button">＋ Chọn cả kịch bản (đúng thứ tự cảnh)</button>` : ''}</div>
        <div class="pp-tiles">${ids.map(k => tile(k, sceneLabel(items[k]), String(g.lines[items[k].scene - 1] || '').replace(/\s+—\s+Lời thoại:.*/, '').slice(0, 70) || fmt(items[k].finished_at))).join('')}${outs.map(k => tile(k, items[k].label || 'Bản đã ghép', '')).join('')}</div></section>`;
    }).join('');
    const otherIds = src.others.map(o => add(o, { title: o.label || fileName(o.path).replace(/\.\w+$/, ''), text: '' }));
    const projOpts = H.s.projects.map(p => `<option value="${esc(p.id)}" ${p.id === project ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
    openModal('THƯ VIỆN', 'Chọn video để hậu kỳ', `<div class="pp-pickbar">
        <label class="field"><span>Dự án</span><select id="ppProj"><option value="" ${project ? '' : 'selected'}>Tất cả dự án</option>${projOpts}</select></label>
        <small class="muted">Bấm vào video để chọn — <b>số trên ô là thứ tự ghép</b>; bấm lại để bỏ. Video theo kịch bản đã xếp sẵn Cảnh 1, 2, 3…</small></div>
      <div class="pp-pickwrap">${groupsHtml}
        ${singles.length + otherIds.length ? `<section class="pp-grp pp-flat"><div class="pp-grphead"><b>Video</b><small class="muted">${singles.length + otherIds.length} video · theo số kịch bản, rồi video lẻ mới nhất trước</small></div>
          <div class="pp-tiles">${singles.join('')}${otherIds.map(k => tile(k, items[k].title, fmt(items[k].finished_at) + proj(items[k].project))).join('')}</div></section>` : ''}
        ${items.length ? '' : '<div class="empty">Dự án này chưa có video nào.</div>'}</div>
      <div class="ab-row pp-pickfoot"><small id="ppPickInfo" class="muted"></small><span class="mh-top-sp"></span>
        <button class="btn ghost sm" id="ppPickClear" type="button">Bỏ chọn</button>
        <button class="btn primary" id="ppLibAdd" type="button">Thêm 0 video</button></div>`);
    const paint = () => {
      $$('#modalBody .pp-tile').forEach(b => {
        const n = order.indexOf(+b.dataset.ppi);
        b.classList.toggle('on', n >= 0);
        b.querySelector('.pp-badge').textContent = n >= 0 ? n + 1 : '';
      });
      $('#ppPickInfo').textContent = order.length ? `Đã chọn ${order.length} video — ghép theo thứ tự số` : 'Chưa chọn video nào';
      $('#ppLibAdd').disabled = !order.length;
      $('#ppLibAdd').textContent = `Thêm ${order.length} video`;
    };
    paint();
    $('#modalBody').onchange = e => { if (e.target.id === 'ppProj') postLibDialog(e.target.value); };
    $('#modalBody').onclick = e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.ppi !== undefined) {
        const k = +b.dataset.ppi, n = order.indexOf(k);
        if (n >= 0) order.splice(n, 1); else order.push(k);
        return paint();
      }
      if (b.dataset.ppg) { b.dataset.ppg.split(',').map(Number).forEach(k => { if (!order.includes(k)) order.push(k); }); return paint(); }
      if (b.id === 'ppPickClear') { order.length = 0; return paint(); }
      if (b.id === 'ppLibAdd') {
        H.post.clips = [...H.post.clips, ...order.map(k => ({ path: items[k].path, url: items[k].url, title: items[k].title, text: items[k].text || '', desc: items[k].prompt || '' }))].slice(0, 40);
        postSave(); closeModal(); renderPostClips(); renderPostOpts();
      }
    };
  }

  async function postStart() {
    const P = H.post;
    if (!P.clips.length) return toast('Thêm ít nhất 1 video', 'warn');
    const noText = !P.clips.some(c => (c.text || '').trim());
    if (P.form.audio === 'tts' && noText && !confirm('Chưa nhập lời đọc cho cảnh nào — video sẽ không có giọng đọc. Vẫn ghép?')) return;
    if (P.form.post_ai && noText) toast('Chưa có lời đọc / lời thoại → Hậu kỳ AI không tô từ khoá được; Muse làm hook + hiệu ứng âm thanh + mức nhạc theo nội dung cảnh' + (P.form.post_style === 'hyperframes' ? ' và HyperFrames dựng đồ hoạ động (hook, tiêu đề, thẻ kết)' : ''), 'warn');
    const r = await api('mhub_post_start', { ...P.form, clips: P.clips.map(c => ({ path: c.path, text: c.text, title: c.title, url: c.url, desc: c.desc || '' })), show_browser: !!H.s.settings.show_browser });
    if (!r.ok) return toast(r.error, 'error');
    toast('Đã đưa vào hậu kỳ — theo dõi tiến độ bên dưới', 'ok');
    const st = await api('mhub_post_state');
    if (st.ok) P.state = st.state;
    renderPostJobs();
    const jobs = $('#mhPostJobs');
    if (jobs) jobs.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
  // ảnh gửi kèm 1 lệnh Muse cho 1 prompt (giống app/muse_hub.compose_images): người mẫu → nhân vật có tên → 1 ảnh luân phiên
  const nameHit = (name, text) => new RegExp(`(^|[^\\p{L}\\d])${name.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\p{L}\\d])`, 'u').test(` ${text.toLowerCase()} `);
  function assetPlan(text) {
    const s = H.s, out = [];
    const push = (im, src) => { if (im && !out.some(x => x.path === im.path)) out.push({ ...im, src }); };
    if (s.model.on) s.model.images.forEach(im => push(im, 'Người mẫu'));
    const named = text.trim() ? s.characters.filter(ch => ch.name && nameHit(ch.name, text)) : [];
    named.forEach(ch => ch.images.forEach(im => push(im, ch.name)));
    if (s.rotate.on && s.rotate.images.length) push(s.rotate.images[(s.rotate.idx || 0) % s.rotate.images.length], 'Luân phiên');
    return { all: out, sent: out.slice(0, s.max_images), dropped: out.slice(s.max_images), named };
  }

  function renderAssetTry() {
    const el = $('#mhATry');
    if (!el) return;
    const s = H.s, max = s.max_images;
    const p = assetPlan(H.atry || '');
    const fixed = s.model.on ? Math.min(max, s.model.images.length) : 0;  // người mẫu cố định luôn đứng đầu
    const free = Math.max(0, max - fixed);
    el.innerHTML = `<div class="ma-slots">${Array.from({ length: max }, (_, i) => {
        const im = p.sent[i];
        return im ? `<figure class="ma-slot on"><img src="${esc(im.url)}" alt=""><figcaption><b>${i + 1}</b> ${esc(im.src)}</figcaption></figure>`
          : `<figure class="ma-slot"><span>${i + 1}</span><figcaption>${H.atry ? 'trống — cho ảnh tham chiếu của task' : 'còn trống'}</figcaption></figure>`;
      }).join('')}</div>
      <div class="ma-notes">
        ${p.named.length ? `<span class="ma-ok">✓ Nhận ra nhân vật: ${p.named.map(c => `<b>${esc(c.name)}</b>`).join(', ')}</span>` : (H.atry ? '<span class="muted">Không thấy tên nhân vật nào trong câu thử</span>' : '')}
        ${p.dropped.length ? `<span class="ma-warn">⚠ Muse nhận tối đa ${max} ảnh — ${p.dropped.length} ảnh bị bỏ (${p.dropped.map(x => esc(x.src)).join(', ')})</span>` : ''}
        ${!free ? `<span class="ma-warn">⚠ Người mẫu cố định đã dùng hết ${max} chỗ — ảnh nhân vật, ảnh luân phiên, ảnh tham chiếu của task sẽ không được gửi. Giảm ảnh người mẫu hoặc tắt.</span>`
          : `<span class="muted">${fixed ? `Người mẫu cố định luôn chiếm ${fixed}/${max} chỗ · ` : ''}${free} chỗ còn lại dành lần lượt cho nhân vật → ảnh luân phiên → ảnh tham chiếu của task</span>`}
      </div>`;
  }

  function renderAssets() {
    const s = H.s, max = s.max_images;
    const q = (H.aq || '').trim().toLowerCase();
    const chars = s.characters.filter(ch => !q || ch.name.toLowerCase().includes(q));
    const tpls = s.templates.filter(t => !q || `${t.name} ${t.text}`.toLowerCase().includes(q));
    const nextRot = s.rotate.images.length ? (s.rotate.idx || 0) % s.rotate.images.length : -1;
    const pool = (kind, list, cap, title, desc, icon) => `<section class="card ma-pool ${s[kind].on ? 'on' : ''}" data-asset-drop="${kind}">
        <div class="ma-poolhead"><span class="ma-ico">${icon}</span><div><b>${title}</b><small class="muted">${desc}</small></div>
          <label class="mh-switch"><input type="checkbox" data-hub-toggle="${kind}" ${s[kind].on ? 'checked' : ''}><i></i><span class="ma-state">${s[kind].on ? 'Đang bật' : 'Tắt'}</span></label></div>
        <div class="ma-imgs">${list.map((im, i) => `<span class="ma-img ${kind === 'rotate' && i === nextRot && s.rotate.on ? 'next' : ''}" data-zoom="${esc(im.url)}">
            <img src="${esc(im.url)}" alt=""><i>${i + 1}</i>${kind === 'rotate' && i === nextRot && s.rotate.on ? '<em>Kế tiếp</em>' : ''}
            <button data-asset-rm="${kind}" data-i="${i}" type="button" title="Bỏ ảnh">✕</button></span>`).join('')}
          ${list.length < cap ? `<button class="ma-add" data-asset-add="${kind}" type="button"><b>＋</b><small>Thêm ảnh<br>hoặc kéo thả</small></button>` : ''}</div>
        <small class="muted ma-count">${list.length}/${cap} ảnh${kind === 'model' ? ' · gắn vào MỌI lệnh khi bật' : ' · mỗi lệnh lấy 1 ảnh kế tiếp, xoay vòng'}</small></section>`;
    $('#mhAssets').innerHTML = `
      <section class="card ma-head">
        <div class="ma-headl"><b class="mh-h">Ảnh gửi kèm mỗi lệnh Muse</b>
          <small class="muted">Muse nhận tối đa ${max} ảnh / lệnh, lấy theo thứ tự ưu tiên:</small>
          <div class="ma-order"><span class="${s.model.on ? 'on' : ''}">① Người mẫu cố định</span><span>② Nhân vật có tên trong prompt</span>
            <span class="${s.rotate.on ? 'on' : ''}">③ Ảnh luân phiên</span><span>④ Ảnh tham chiếu của task</span></div>
          <label class="field ma-try"><span>Thử prompt — xem ảnh nào sẽ được gửi kèm</span>
            <input id="mhATryIn" value="${esc(H.atry || '')}" placeholder="VD: ${esc((s.characters[0] || {}).name || 'Lan')} cầm bao phân bón trên cánh đồng lúa"></label></div>
        <div class="ma-headr" id="mhATry"></div>
      </section>
      <div class="ma-grid">
        <div class="ma-col">
          <section class="card ma-sec"><div class="ma-sechead"><b>🧑 Nhân vật</b><small class="muted">${s.characters.length} nhân vật · gõ đúng tên trong prompt → tự gắn ảnh (≤ 3 ảnh / nhân vật)</small>
              <span class="mh-top-sp"></span>${s.characters.length + s.templates.length > 6 ? `<input id="mhAq" type="search" value="${esc(H.aq || '')}" placeholder="🔍 Tìm nhân vật / mẫu…">` : ''}</div>
            <div class="ma-chars">${chars.map(ch => `<div class="ma-char">
                <button class="ma-cover" type="button" data-char-edit="${esc(ch.id)}" title="Sửa nhân vật">${ch.images[0] ? `<img src="${esc(ch.images[0].url)}" alt="">` : '<span>🧑</span>'}
                  ${ch.images.length > 1 ? `<span class="ma-mini">${ch.images.slice(1).map(im => `<img src="${esc(im.url)}" alt="">`).join('')}</span>` : ''}</button>
                <div class="ma-cbody"><b title="${esc(ch.name)}">${esc(ch.name)}</b><small class="muted">${ch.images.length ? `${ch.images.length} ảnh` : '⚠ chưa có ảnh'}</small>
                  <button class="ma-chip" data-char-copy="${esc(ch.name)}" type="button" title="Sao chép tên để gõ vào prompt">⧉ ${esc(ch.name)}</button></div>
                <div class="ma-acts"><button class="btn ghost sm" data-char-edit="${esc(ch.id)}" type="button">Sửa</button>
                  <button class="btn ghost sm st-pdel" data-char-del="${esc(ch.id)}" type="button" title="Xoá nhân vật">🗑</button></div></div>`).join('')}
              <button class="ma-new" data-act="char-new" type="button"><b>＋</b>Nhân vật mới<small>tên + tối đa 3 ảnh khuôn mặt</small></button></div></section>
          <section class="card ma-sec"><div class="ma-sechead"><b>📝 Mẫu prompt</b><small class="muted">${s.templates.length} mẫu · dùng nhanh ở tab Studio</small></div>
            <div class="ma-tpls">${tpls.map(t => {
                const who = s.characters.filter(ch => ch.name && nameHit(ch.name, t.text));
                return `<div class="ma-tpl"><div class="ma-tbody"><b>${esc(t.name)}</b><p>${esc(t.text)}</p>
                  ${who.length ? `<div class="ma-who">${who.map(ch => `<span>🧑 ${esc(ch.name)}</span>`).join('')}</div>` : ''}</div>
                  <div class="ma-acts"><button class="btn primary sm" data-tpl-use="${esc(t.id)}" type="button" title="Chèn vào ô Prompt ở tab Studio">↪ Dùng ở Studio</button>
                    <button class="btn ghost sm" data-tpl-edit="${esc(t.id)}" type="button">Sửa</button>
                    <button class="btn ghost sm st-pdel" data-tpl-del="${esc(t.id)}" type="button" title="Xoá mẫu">🗑</button></div></div>`;
              }).join('')}
              <button class="ma-new row" data-act="tpl-new" type="button"><b>＋</b>Mẫu prompt mới<small>lưu câu lệnh hay dùng — chèn bằng 1 bấm</small></button></div></section>
        </div>
        <div class="ma-col">
          ${pool('model', s.model.images, max, 'Người mẫu cố định', 'Gắn vào mọi lệnh — giữ 1 gương mặt / sản phẩm xuyên suốt', '👤')}
          ${pool('rotate', s.rotate.images, 20, 'Ảnh luân phiên', 'Mỗi lệnh lấy 1 ảnh kế tiếp — đa dạng bối cảnh / sản phẩm', '🔁')}
        </div>
      </div>`;
    renderAssetTry();
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

  const libSelVideos = () => H.lib.sel.filter(p => (H.lib.items.find(i => i.path === p) || {}).video);

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
    renderLibrary();
  }

  function renderLibrary() {
    const items = H.lib.items;
    const vids = items.filter(i => i.video).length;
    const n = H.lib.sel.length, nv = libSelVideos().length;
    const others = H.s.projects.filter(p => p.id !== H.s.current);
    $('#mhLibrary').innerHTML = `<div class="card mh-libhead ${n ? 'picking' : ''}"><b>Thư viện · ${esc(proj().name)}</b>
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
        <button class="btn primary sm" data-act="merge" type="button" ${nv >= 2 ? '' : 'disabled title="Chọn ít nhất 2 video"'}>🎞 Ghép video (${nv})</button></div>
      <div class="img-grid mh-libgrid">${items.length ? items.map((i, k) => `<div class="mh-libcell" data-lib-k="${k}"><div class="img-tile mh-lib ${H.lib.sel.includes(i.path) ? 'sel' : ''}" data-lib-view="${k}" title="Bấm để ${i.video ? 'phát video' : 'xem ảnh'} · Ctrl/Shift + bấm để chọn">
          ${i.video ? `<video src="${esc(i.url)}" muted preload="metadata"></video><i class="img-count">🎬</i><span class="mh-libplay">▶</span>` : `<img src="${esc(i.url)}" alt="" loading="lazy">`}
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
        renderLibrary();
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

  // ------------------------------------------------------------ tab Tài khoản
  function quotaHtml(a) {
    const q = a.quota;
    if (!q) return `<small class="muted">${a.checking ? 'Đang đọc hạn mức…' : 'Chưa có số liệu hạn mức — bấm “Hạn mức”'}</small>`;
    const pct = Math.min(100, Math.round(q.pct));
    const num = n => Number(n).toLocaleString('vi-VN');
    const week = `<div class="mh-qrow"><span class="mh-qlabel">Hạn mức tuần</span>
        <div class="mh-qbar ${pct >= 100 ? 'out' : pct >= 80 ? 'low' : ''}" title="Đã dùng ${pct}%"><i style="width:${pct}%"></i></div>
        <b class="mh-qval">${pct}%</b></div>
      <small>${esc(q.tier || 'Muse')} · đã dùng ${pct}% tuần${q.resets_at ? ` · đặt lại ${day(q.resets_at)}` : ''}</small>`;
    if (q.topup_left == null) return `<div class="mh-quota">${week}</div>`;
    // Additional token (token bổ sung): thanh = phần CÒN LẠI; hết hạn mức tuần thì Muse dùng token này
    const left = Math.max(0, Math.min(100, Math.round(q.topup_left * 100)));
    const nums = q.topup_balance != null && q.topup_total ? `còn ${num(q.topup_balance)} / ${num(q.topup_total)}` : (q.topup_label || '');
    const using = pct >= 100 && left > 0;
    return `<div class="mh-quota">${week}
      <div class="mh-qrow"><span class="mh-qlabel">Additional token</span>
        <div class="mh-qbar topup ${left <= 0 ? 'out' : left < 30 ? 'low' : ''}" title="Token bổ sung còn ${left}%"><i style="width:${left}%"></i></div>
        <b class="mh-qval">${left}%</b></div>
      <small>Token bổ sung ${esc(nums)}${using ? ' · <span class="mh-qusing">đang dùng (hết hạn mức tuần)</span>' : ''}${left <= 0 ? ' · đã hết' : ''}</small></div>`;
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
        const lv = e.target.closest('[data-lib-view]');
        if (lv && !e.target.closest('.mh-libsel')) {
          if (H.lib.justMarq) return;  // vừa tô khối xong — không mở trình xem
          if (e.ctrlKey || e.metaKey || e.shiftKey) return libSelect(+lv.dataset.libView, e);
          return openLibViewer(+lv.dataset.libView);
        }
        const pt = e.target.closest('[data-ptask]');
        if (pt) return openDetail(pt.dataset.ptask);
        const grow = e.target.closest('.mk-row');
        if (grow && !e.target.matches('input')) { H.g.cur = grow.dataset.gcur; return renderGroups(); }
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
      if (act === 'idea-go') {
        const c = H.c;
        if (!c.idea.trim()) return toast('Nhập ý tưởng / kịch bản trước', 'warn');
        c.ideaBusy = true; renderCompose();
        const r = await api('mhub_timeline', { idea: c.idea, count: c.ideaCount, seconds: c.duration, ratio: c.ratio, style: c.ideaStyle }, !!H.s.settings.show_browser);
        c.ideaBusy = false;
        if (!r.ok) { renderCompose(); return toast(r.error, 'error'); }
        const block = r.result.prompts.join('\n\n');  // dòng trống = tách task
        c.text = c.text.trim() ? `${c.text.trim()}\n\n${block}` : block;
        renderCompose();
        return toast(`Muse đã viết ${r.result.prompts.length} prompt timeline — xem / sửa rồi bấm “Thêm task vào hàng đợi”`, 'ok');
      }
      if (d.pair) { H.c.pairing = d.pair; return renderCompose(); }
      if (d.rmImg !== undefined) { H.c.images.splice(+d.rmImg, 1); return renderCompose(); }
      if (act === 'add-img') { H.c.images = [...H.c.images, ...await pickImages()]; return renderCompose(); }
      if (act === 'save-tpl') { if (!H.c.text.trim()) return toast('Ô prompt đang trống', 'warn'); return tplDialog(null, H.c.text); }
      if (act === 'add-tasks') {
        const res = await api('mhub_add', { kind: H.c.kind, ratio: H.c.ratio, duration: H.c.duration, prompts: prompts(H.c.text), images: H.c.images.map(i => i.path), pairing: H.c.pairing });
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
      if (d.gdel) return deleteGroups([d.gdel], 'video này');
      if (d.gopen) return api('mhub_open', d.gopen);
      if (d.gfilter) { H.g.filter = d.gfilter; return renderGroups(); }
      if (d.gretry) { const r = await api('mhub_tasks', d.gretry.split(','), 'retry'); if (r.ok) H.s = r.state; toast('Đã đưa phần lỗi chạy lại', 'ok'); return renderGroups(); }
      if (d.taskOpen) return openDetail(d.taskOpen);
      // tiến trình
      if (d.pall !== undefined) { H.prog.all = d.pall === '1'; return renderProgress(); }
      if (d.pcancel) { const r = await api('mhub_tasks', [d.pcancel], 'cancel'); if (r.ok) H.s = r.state; return renderProgress(); }
      if (d.pretry || d.pretryFailed) { const r = await api('mhub_tasks', (d.pretry || d.pretryFailed).split(','), 'retry'); if (r.ok) H.s = r.state; toast('Đã đưa vào hàng đợi chạy lại', 'ok'); return renderProgress(); }
      if (d.openTaskFile) return api('mhub_open', d.openTaskFile);
      if (act === 'g-sel-all') { projGroups().forEach(g => H.g.sel.add(g.id)); return renderGroups(); }
      if (act === 'g-sel-none') { H.g.sel.clear(); return renderGroups(); }
      if (act === 'g-del-sel') return deleteGroups([...H.g.sel], `${H.g.sel.size} video đã chọn`);
      if (act === 'g-del-all') return deleteGroups(projGroups().map(g => g.id), 'tất cả video của dự án');
      if (act === 'g-clear-done') {
        for (const g of projGroups().filter(x => x.status === 'done')) await api('mhub_group_delete', g.id);
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
      // hậu kỳ
      if (act === 'pp-lib') return postLibDialog();
      if (act === 'pp-pick') return postAddFiles(await api('pick_files', 'videos'));
      if (act === 'pp-clear') { if (!confirm('Bỏ hết video khỏi danh sách cảnh?')) return; H.post.clips = []; postSave(); renderPostClips(); return renderPostOpts(); }
      if (d.ppUp !== undefined || d.ppDown !== undefined) {
        const i = +(d.ppUp ?? d.ppDown), j = d.ppUp !== undefined ? i - 1 : i + 1, c = H.post.clips;
        [c[i], c[j]] = [c[j], c[i]]; postSave(); return renderPostClips();
      }
      if (d.ppRm !== undefined) { H.post.clips.splice(+d.ppRm, 1); postSave(); renderPostClips(); return renderPostOpts(); }
      if (d.ppAudio) { H.post.form.audio = d.ppAudio; postSave(); renderPostClips(); return renderPostOpts(); }
      if (act === 'pp-voice') {
        const f = H.post.form, text = (H.post.clips.find(c => (c.text || '').trim()) || {}).text || '';
        const r = await api('studio_voice_preview', text, '', f.voice, f.rate);
        if (!r.ok) return toast(r.error, 'error');
        return new Audio(r.data).play().catch(() => {});
      }
      if (act === 'pp-sound') {
        const r = await api('transition_sound_preview', H.post.form.transition_sound);
        if (!r.ok) return toast(r.error, 'error');
        if (!r.data) return toast('Đang chọn “không có” âm chuyển cảnh', 'warn');
        const a = new Audio(r.data); a.volume = Math.min(1, H.post.form.transition_volume); return a.play().catch(() => {});
      }
      if (act === 'pp-start') return postStart();
      if (act === 'pp-logo') {
        const [im] = await pickImages();
        if (!im) return;
        Object.assign(H.post.form, { logo: im.path, logo_url: im.url });
        postSave(); return renderPostOpts();
      }
      if (d.ppCorner) { H.post.form.logo_corner = d.ppCorner; postSave(); return renderPostOpts(); }
      if (act === 'pp-logo-rm') { Object.assign(H.post.form, { logo: '', logo_url: '' }); postSave(); return renderPostOpts(); }
      if (d.ppCancel) { const r = await api('mhub_post_cancel', d.ppCancel); if (r.ok) { H.post.state = r.state; renderPostJobs(); } return; }
      if (d.ppRedo !== undefined) {
        const v = H.post.state.done[+d.ppRedo], f = v && v.form;
        if (!f || !(f.clips || []).length) return toast('Video này không còn dữ liệu cảnh để hậu kỳ lại — dùng “＋ Dùng làm cảnh”', 'warn');
        if (H.post.clips.length && !confirm(`Thay ${H.post.clips.length} cảnh đang soạn bằng ${f.clips.length} cảnh của “${v.title}”?`)) return;
        const opts = Object.fromEntries(Object.entries(f.options || {}).filter(([k]) => k in POST_DEF));
        const n = H.post.state.done.filter(x => x.title.replace(/ \(bản \d+\)$/, '') === v.title.replace(/ \(bản \d+\)$/, '')).length + 1;
        H.post.clips = f.clips.map(c => ({ path: c.path, url: c.url || '', title: c.title || fileName(c.path), text: c.text || '', desc: c.desc || '' }));
        H.post.form = { ...POST_DEF, ...opts, name: `${v.title.replace(/ \(bản \d+\)$/, '')} (bản ${n})` };
        postSave(); renderPost();
        $('#mhPost').scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (f.rebuilt && opts.audio === 'original') toast('Video làm trước bản cập nhật: các cảnh đã chuẩn hoá không còn tiếng gốc — chọn Lồng tiếng AI hoặc Không lời', 'warn');
        return toast(`Đã nạp ${f.clips.length} cảnh + thiết lập — chỉnh rồi bấm “Ghép & hậu kỳ” để ra bản mới (bản cũ giữ nguyên)`, 'ok');
      }
      if (d.ppUseclip !== undefined) {
        const v = H.post.state.done[+d.ppUseclip];
        if (!v) return;
        H.post.clips = [...H.post.clips, { path: v.path, url: v.url, title: v.title, text: '', dur: v.duration }].slice(0, 40);
        postSave(); renderPostClips(); renderPostOpts();
        $('#mhPostClips').scrollIntoView({ behavior: 'smooth', block: 'start' });
        return toast(`Đã thêm “${v.title}” vào danh sách cảnh`, 'ok');
      }
      if (d.ppOpen) { const r = await api('mhub_post_open', d.ppOpen); if (!r.ok) toast(r.error, 'error'); return; }
      // video mẫu
      if (act === 'smp-pick') { const f = await api('pick_files', 'video'); if (f && f.length) return samplePrepare(f[0]); return; }
      if (act === 'smp-go') return samplePrepare((($('#mhSmpUrl') || {}).value || '').trim());
      if (act === 'smp-sheet') { H.smp.showSheet = !H.smp.showSheet; return renderSample(); }
      if (act === 'smp-add-img') { H.smp.images = [...H.smp.images, ...await pickImages()].slice(0, 2); return renderSample(); }
      if (d.srm !== undefined) { H.smp.images.splice(+d.srm, 1); return renderSample(); }
      if (act === 'smp-add-doc') {
        const files = await api('pick_files', 'docs');
        if (!files || !files.length) return;
        const r = await api('mhub_sample_docs', files);
        if (!r.ok) return toast(r.error, 'error');
        const have = new Set(H.smp.docs.map(x => x.path));
        H.smp.docs = [...H.smp.docs, ...r.docs.filter(x => !have.has(x.path))].slice(0, 5);
        return renderSample();
      }
      if (d.sdocRm !== undefined) { H.smp.docs.splice(+d.sdocRm, 1); return renderSample(); }
      if (act === 'smp-write') return sampleWrite();
      if (act === 'smp-all') { H.smp.checked = new Set(H.smp.scripts.scripts.map((_, i) => i)); return renderSample(); }
      if (act === 'smp-preview' || act === 'smp-queue') {
        const all = [];
        let groups = 0;
        for (const f of sampleForms(act === 'smp-preview')) {
          const r = await api('mhub_script', f);
          if (!r.ok) return toast(r.error, 'error');
          if (f.dry) all.push(...r.result.preview); else groups += r.result.groups;
        }
        if (act === 'smp-preview') return previewDialog(all);
        toast(`Đã đưa ${groups} video vào hàng đợi — xem ở tab Kịch bản / Tiến trình`, 'ok');
        H.tab = 'script';
        return show();
      }
      // tư liệu
      if (d.tplUse) {
        const tp = H.s.templates.find(x => x.id === d.tplUse);
        if (!tp) return;
        H.c.text = H.c.text.trim() ? `${H.c.text.trim()}\n\n${tp.text}` : tp.text;
        H.tab = 'studio';
        try { localStorage.setItem('va.mhub.tab', H.tab); } catch { /* bỏ qua */ }
        renderAll();
        return toast(`Đã chèn mẫu “${tp.name}” vào ô Prompt`, 'ok');
      }
      if (d.charCopy) { navigator.clipboard.writeText(d.charCopy).then(() => toast(`Đã sao chép “${d.charCopy}” — dán vào prompt để tự gắn ảnh`, 'ok'), () => {}); return; }
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
      if (act === 'lib-all') { H.lib.sel = H.lib.items.map(i => i.path); return renderLibrary(); }
      if (act === 'lib-none') { H.lib.sel = []; H.lib.anchor = null; return renderLibrary(); }
      if (act === 'lib-move') {
        const to = ($('#mhLibMoveTo') || {}).value;
        const name = (H.s.projects.find(p => p.id === to) || {}).name || '';
        if (!to || !confirm(`Chuyển ${H.lib.sel.length} file sang dự án “${name}”?\nVideo thuộc kịch bản sẽ chuyển CẢ kịch bản (mọi cảnh + bản ghép). File trên máy giữ nguyên chỗ.`)) return;
        const r = await api('mhub_move', H.lib.sel, to);
        if (!r.ok) return toast(r.error, 'error');
        const x = r.result;
        toast(`Đã chuyển ${x.tasks} file${x.groups ? ` (${x.groups} kịch bản${x.extra ? `, kèm ${x.extra} cảnh cùng kịch bản` : ''})` : ''} sang “${name}”`, 'ok');
        H.lib.sel = []; H.lib.anchor = null;
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        renderTop();
        return loadLibrary();
      }
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
      if (t.id === 'mhDur') { H.c.duration = +t.value; if (H.c.ideaOn) renderCompose(); return; }
      if (t.id === 'mhIdeaOn') { H.c.ideaOn = t.checked; return renderCompose(); }
      if (t.id === 'mhIdeaCount') { H.c.ideaCount = +t.value; return renderCompose(); }
      if (t.dataset.gsel) { if (t.checked) H.g.sel.add(t.dataset.gsel); else H.g.sel.delete(t.dataset.gsel); return renderGroups(); }
      const kmap = { mhKMethod: 'method', mhKRatio: 'ratio', mhKDur: 'duration', mhKVoice: 'voice', mhKChar: 'character', mhKPresenter: 'presenter' };
      if (kmap[t.id]) { H.k[kmap[t.id]] = t.value; if (t.id === 'mhKDur') renderKForm(); return; }
      if (t.id === 'mhKVersions') { H.k.versions = Math.max(1, Math.min(5, +t.value || 1)); $('#mhKCount').textContent = kCount(); const o = $('#mhKOutline'); if (o) o.innerHTML = kOutline(); return; }
      if (t.id === 'mhKMerge') { H.k.merge = t.checked; return; }
      if (t.id === 'mhKBgm') { H.k.bgm = t.checked; return; }
      if (t.id === 'mhLadiNoPrice') {
        if (H.ladi.scripts && !confirm('Đổi “Không đọc giá” sẽ sinh lại kịch bản (mất chữ đã sửa). Tiếp tục?')) { t.checked = !t.checked; return; }
        H.ladi.noPrice = t.checked;
        return H.ladi.page ? ladiGenerate() : undefined;
      }
      if (t.dataset.pf) {
        const key = t.dataset.pf;
        H.post.form[key] = t.type === 'checkbox' ? t.checked : t.type === 'range' || key === 'transition_duration' ? +t.value : t.value;
        postSave();
        if (['bgm', 'post_ai', 'post_style'].includes(key)) renderPostOpts();
        return;
      }
      if (t.dataset.scheck !== undefined) { const i = +t.dataset.scheck; if (t.checked) H.smp.checked.add(i); else H.smp.checked.delete(i); return renderSample(); }
      const smap = { mhSmpClose: 'closeness', mhSmpCount: 'count', mhSmpScenes: 'scenes', mhSmpRatio: 'ratio', mhSmpDur: 'duration' };
      if (smap[t.id]) { H.smp[smap[t.id]] = t.value; return; }
      if (t.id === 'mhSmpNoPrice') { H.smp.noPrice = t.checked; return; }
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
        H.lib.anchor = H.lib.items.findIndex(i => i.path === p);
        return renderLibrary();
      }
      if (t.dataset.set) { const r = await api('mhub_settings', { [t.dataset.set]: t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.setBool) { const r = await api('mhub_settings', { [t.dataset.setBool]: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.accOn) { const r = await api('mhub_account', t.dataset.accOn, { enabled: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); renderTop(); } return; }
      if (t.dataset.accThreads) { const r = await api('mhub_account', t.dataset.accThreads, { threads: +t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } }
    });
    // Thư viện: kéo chuột tô khối để chọn nhiều (Ctrl / Shift khi kéo = thêm vào lựa chọn cũ)
    page.addEventListener('mousedown', e => {
      if (e.button !== 0 || !e.target.closest('#mhLibrary') || e.target.closest('.mh-libhead, input, label, button, select')) return;
      const start = { x: e.clientX, y: e.clientY }, add = e.ctrlKey || e.metaKey || e.shiftKey;
      const base = add ? [...H.lib.sel] : [];
      let box = null, hits = [];
      e.preventDefault();  // không bôi đen chữ / kéo ảnh
      const move = ev => {
        const x1 = Math.min(start.x, ev.clientX), y1 = Math.min(start.y, ev.clientY);
        const x2 = Math.max(start.x, ev.clientX), y2 = Math.max(start.y, ev.clientY);
        if (!box) {
          if (x2 - x1 < 6 && y2 - y1 < 6) return;  // chưa kéo đủ xa → vẫn là bấm thường
          box = document.createElement('div');
          box.className = 'mh-marquee';
          document.body.appendChild(box);
        }
        Object.assign(box.style, { left: `${x1}px`, top: `${y1}px`, width: `${x2 - x1}px`, height: `${y2 - y1}px` });
        hits = [];
        $$('#mhLibrary .mh-libcell').forEach(c => {
          const r = c.getBoundingClientRect();
          const on = r.left < x2 && r.right > x1 && r.top < y2 && r.bottom > y1;
          c.classList.toggle('marq', on);
          if (on) hits.push(+c.dataset.libK);
        });
      };
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        if (!box) return;
        box.remove();
        const paths = hits.map(k => H.lib.items[k].path);
        H.lib.sel = [...base, ...paths.filter(p => !base.includes(p))];
        if (hits.length) H.lib.anchor = hits[hits.length - 1];
        H.lib.justMarq = true;
        setTimeout(() => { H.lib.justMarq = false; }, 0);  // bỏ qua cú click ngay sau khi nhả chuột
        renderLibrary();
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
    document.addEventListener('keydown', e => {  // Thư viện: Ctrl+A chọn tất cả · Esc bỏ chọn
      if (H.tab !== 'library' || $('#page-mstudio').classList.contains('hidden') || !$('#modal').classList.contains('hidden')
        || /input|textarea|select/i.test(e.target.tagName)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { e.preventDefault(); H.lib.sel = H.lib.items.map(i => i.path); renderLibrary(); }
      if (e.key === 'Escape' && H.lib.sel.length) { H.lib.sel = []; H.lib.anchor = null; renderLibrary(); }
    });
    document.addEventListener('keydown', e => {  // ← → chuyển file trong trình xem thư viện
      if (!$('#mhLibView') || $('#modal').classList.contains('hidden') || /input|textarea|select/i.test(e.target.tagName)) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const k = H.lib.view + (e.key === 'ArrowLeft' ? -1 : 1);
        if (H.lib.items[k]) { e.preventDefault(); openLibViewer(k); }
      }
    });
    // Hậu kỳ: kéo ⋮⋮ để đổi thứ tự cảnh
    const ppRow = e => e.target.closest && e.target.closest('.pp-clip');
    const ppMark = (row, after) => { $$('#mhPostClips .pp-clip').forEach(r => r.classList.remove('drop-before', 'drop-after')); if (row) row.classList.add(after ? 'drop-after' : 'drop-before'); };
    page.addEventListener('dragstart', e => {
      const g = e.target.closest && e.target.closest('[data-pp-drag]');
      if (!g) return;
      H.post.drag = +g.dataset.ppDrag;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', g.dataset.ppDrag);
      const row = g.closest('.pp-clip');
      e.dataTransfer.setDragImage(row, 24, 24);
      setTimeout(() => row.classList.add('dragging'), 0);
    });
    page.addEventListener('dragover', e => {
      const row = ppRow(e);
      if (H.post.drag == null || !row) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      ppMark(row, e.clientY > r.top + r.height / 2);
    });
    page.addEventListener('drop', e => {
      const row = ppRow(e);
      if (H.post.drag == null || !row) return;
      e.preventDefault();
      const from = H.post.drag, r = row.getBoundingClientRect();
      let to = +row.dataset.ppRow + (e.clientY > r.top + r.height / 2 ? 1 : 0);
      if (from < to) to -= 1;
      H.post.drag = null;
      if (to !== from) { const [c] = H.post.clips.splice(from, 1); H.post.clips.splice(to, 0, c); postSave(); }
      renderPostClips();
    });
    page.addEventListener('dragend', () => { if (H.post.drag == null && !$('#mhPostClips .dragging')) return; H.post.drag = null; ppMark(null); $$('#mhPostClips .dragging').forEach(r => r.classList.remove('dragging')); });
    page.addEventListener('loadedmetadata', e => {  // thời lượng video trong danh sách cảnh hậu kỳ
      const i = e.target.dataset && e.target.dataset.ppDur;
      if (i === undefined || !H.post.clips[+i]) return;
      H.post.clips[+i].dur = e.target.duration || 0;
      const el = $(`#ppDur${i}`); if (el) el.textContent = `${(e.target.duration || 0).toFixed(1)}s`;
    }, true);
    // Hậu kỳ: kéo thả ảnh logo vào khung "Đóng logo"
    page.addEventListener('dragover', e => { const z = e.target.closest && e.target.closest('[data-pp-logo-drop]'); if (z && H.post.drag == null) { e.preventDefault(); z.classList.add('over'); } });
    page.addEventListener('dragleave', e => { const z = e.target.closest && e.target.closest('[data-pp-logo-drop]'); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = e.target.closest && e.target.closest('[data-pp-logo-drop]');
      if (!z) return;
      e.preventDefault(); z.classList.remove('over');
      const [im] = await dropImages([...e.dataTransfer.files]);
      if (im) { Object.assign(H.post.form, { logo: im.path, logo_url: im.url }); postSave(); renderPostOpts(); }
    });
    // Tư liệu: kéo thả ảnh vào khung Người mẫu cố định / Ảnh luân phiên
    const poolZone = e => e.target.closest && e.target.closest('[data-asset-drop]');
    page.addEventListener('dragover', e => { const z = poolZone(e); if (!z || H.post.drag != null) return; e.preventDefault(); z.classList.add('over'); });
    page.addEventListener('dragleave', e => { const z = poolZone(e); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = poolZone(e);
      if (!z) return;
      e.preventDefault();
      z.classList.remove('over');
      const kind = z.dataset.assetDrop, cap = kind === 'model' ? H.s.max_images : 20;
      const imgs = await dropImages([...e.dataTransfer.files]);
      if (!imgs.length) return;
      const list = [...H.s[kind].images.map(i => i.path), ...imgs.map(i => i.path)];
      if (list.length > cap) toast(`Tối đa ${cap} ảnh — bỏ ${list.length - cap} ảnh cuối`, 'warn');
      const r = await api('mhub_asset', kind, { images: list.slice(0, cap) });
      if (!r.ok) return toast(r.error, 'error');
      H.s = r.state; renderAssets();
    });
    page.addEventListener('toggle', e => { if (e.target.classList && e.target.classList.contains('smp-analysis')) H.smp.openAnalysis = e.target.open; }, true);
    // kéo thả ảnh sản phẩm vào ô "Ảnh sản phẩm" (tab Kịch bản)
    const dropZone = e => e.target.closest && e.target.closest('#mhKDrop');
    page.addEventListener('dragover', e => { const z = dropZone(e); if (!z) return; e.preventDefault(); z.classList.add('over'); });
    page.addEventListener('dragleave', e => { const z = dropZone(e); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = dropZone(e);
      if (!z) return;
      e.preventDefault();
      z.classList.remove('over');
      const imgs = await dropImages([...e.dataTransfer.files]);
      if (imgs.length) { H.k.images = [...H.k.images, ...imgs].slice(0, 30); renderKForm(); }
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
      if (e.target.id === 'mhIdea') H.c.idea = e.target.value;
      if (e.target.id === 'mhATryIn') { H.atry = e.target.value; renderAssetTry(); }
      if (e.target.id === 'mhAq') {
        H.aq = e.target.value; renderAssets();
        const el = $('#mhAq'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
      }
      if (e.target.id === 'mhIdeaStyle') H.c.ideaStyle = e.target.value;
      if (e.target.id === 'mhKText') { H.k.text = e.target.value; $('#mhKCount').textContent = kCount(); const o = $('#mhKOutline'); if (o) o.innerHTML = kOutline(); }
      if (e.target.id === 'mhKPrefix') H.k.prefix = e.target.value;
      if (e.target.id === 'mhKNote') H.k.note = e.target.value;
      if (e.target.id === 'mhLadiUrl') H.ladi.url = e.target.value;
      if (e.target.id === 'mhSmpUrl') H.smp.source = e.target.value;
      if (e.target.dataset.ppText !== undefined) { H.post.clips[+e.target.dataset.ppText].text = e.target.value; postSave(); }
      if (e.target.dataset.pf === 'name') { H.post.form.name = e.target.value; postSave(); }
      if (e.target.dataset.pf === 'bgm_volume') { $('#ppBgmVol').textContent = `${Math.round(e.target.value * 100)}%`; }
      if (e.target.dataset.pf === 'transition_volume') { $('#ppSndVol').textContent = `${Math.round(e.target.value * 100)}%`; }
      if (e.target.id === 'mhSmpChange') H.smp.change = e.target.value;
      if (e.target.id === 'mhSmpTranscript') H.smp.transcript = e.target.value;
      const sl = e.target.dataset.sline || e.target.dataset.svis;
      if (sl) { const [i, j] = sl.split(':').map(Number); H.smp.scripts.scripts[i].scenes[j][e.target.dataset.sline ? 'line' : 'visual'] = e.target.value; }
      const ll = e.target.dataset.lline || e.target.dataset.lvis;
      if (ll) { const [i, j] = ll.split(':').map(Number); H.ladi.scripts.scripts[i].scenes[j][e.target.dataset.lline ? 'line' : 'visual'] = e.target.value; }
    });
  }

  window.MuseHubPage = { show, update };
})();
