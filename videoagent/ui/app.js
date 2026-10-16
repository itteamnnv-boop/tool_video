'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad2 = n => String(n).padStart(2, '0');
const api = (name, ...args) => window.pywebview.api[name](...args);

const STAGES = [['prepare', 'Chuẩn bị'], ['script', 'Kịch bản'], ['voice', 'Lời thoại'], ['visual', 'Dựng hình'], ['post', 'Hậu kỳ'], ['finish', 'Hoàn thiện']];
const FRAME_SIZE = { '9:16': [540, 960], '16:9': [960, 540], '1:1': [540, 540], '4:5': [540, 675] };
const ASPECT_LABELS = { '9:16': '9:16 — dọc', '16:9': '16:9 — ngang', '1:1': '1:1 — vuông', '4:5': '4:5 — feed' };
const PRESETS = [['custom', 'Tự chọn'], ['15', '15 giây'], ['30', '30 giây'], ['45', '45 giây'], ['60', '60 giây']];
const FORM_DEFAULT = {
  topic: '', genre: 'trailer', template: 'ai', provider: 'gemini_browser', show_browser: false,
  aspect: '9:16', preset: 'custom', seconds: 8, scenes: 4, voice: 'vi-VN-HoaiMyNeural', rate: '+0%',
  subtitles: true, bgm: true, layout_file: '', product_files: [],
  product_style: 'reel', brand: '', comment_name: '', comment_text: '',
  price: '', old_price: '', perk: '', contact: '', keep_audio: false,
  ai_values: {}, ai_duration: '', ai_resolution: '', gemini_mode: 'veo', browser_profile: '',
};
const PRODUCT_GENRE = 'product_layout';
const baseName = p => String(p).split(/[\\/]/).pop();
const MAX_LOG_LINES = 600;

const state = {
  boot: null, form: { ...FORM_DEFAULT }, running: false, autoScroll: true,
  videos: [], selected: null, detail: null, scene: null, rerenderOf: null,
};

window.addEventListener('pywebviewready', init);

async function init() {
  state.boot = await api('bootstrap');
  fillSelects();
  buildStepper();
  restoreForm();
  renderHeader();
  bindEvents();
  initSidebar();
  initImages();
  initFacebook();
  initAds();
  initProfiles();
  state.vt = makeTaskUI('video', 'v', { setProgress, setPill: setStatusPill, logEl: $('#log') });
  state.it = makeTaskUI('image', 'img', { setProgress: setImageProgress, setPill: setImagePill, logEl: $('#imgLog') });
  state.vt.update(state.boot.tasks || []);
  state.it.update(state.boot.image_tasks || []);
  setRunning(state.boot.running);
  await refreshVideos();
}

/* ------------------------------------------------------------------ sidebar & điều hướng */
const SIDEBAR_KEY = 'va.sidebar.collapsed';

function initSidebar() {
  state.view = 'create';
  $('#sbTplCount').textContent = state.boot.template_count;
  $('#sbVersion').textContent = `VideoAgent v${state.boot.version}`;
  try {  // nhớ trạng thái thu gọn (localStorage có thể bị chặn)
    $('#sidebar').classList.toggle('collapsed', localStorage.getItem(SIDEBAR_KEY) === '1');
  } catch { /* bỏ qua */ }
  $('#sbToggle').onclick = () => {
    const collapsed = $('#sidebar').classList.toggle('collapsed');
    try { localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0'); } catch { /* bỏ qua */ }
    requestAnimationFrame(fitFrame);
  };
  $$('.sb-item[data-view]').forEach(item => { item.onclick = () => navigate(item.dataset.view); });
}

function navigate(view) {
  if (view === 'settings') return openSettings();
  if (view === 'folder') return api('open_output_dir');
  const previous = state.view;
  state.view = view;
  if (view === 'create' && previous === 'library') switchTab('progress');
  $$('.sb-item[data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  const workspace = view === 'create' || view === 'library';
  $('#workspace').classList.toggle('hidden', !workspace);
  $('#workspace').classList.toggle('library', view === 'library');
  $('#page-templates').classList.toggle('hidden', view !== 'templates');
  $('#imgWorkspace').classList.toggle('hidden', view !== 'images');
  $('#page-facebook').classList.toggle('hidden', view !== 'facebook');
  if (view === 'facebook') refreshFacebook();
  $('#page-ads').classList.toggle('hidden', view !== 'ads');
  if (view === 'ads') refreshAds();
  $('#page-profiles').classList.toggle('hidden', view !== 'profiles');
  if (view === 'profiles') refreshProfiles();
  if (view === 'images') refreshImages();
  $('#page-help').classList.toggle('hidden', view !== 'help');
  if (view === 'library') switchTab('results');
  if (view === 'templates') {
    const current = findTemplate(state.form.template);
    mountTemplateBrowser($('#tplPageBody'), choice => {
      setTemplate(choice);
      navigate('create');
      toast(`Đã chọn template: ${state.form.genre === PRODUCT_GENRE ? 'Theo layout mẫu' : templateLabel(choice)}`, 'ok');
    }, current && current.kind === 'ai_video' ? 'ai_video' : 'all');
  }
}

/* ------------------------------------------------------------------ tạo hình ảnh */
const IMG_STAGES = [['prepare', 'Chuẩn bị'], ['send', 'Gửi prompt'], ['generate', 'Tạo ảnh'], ['download', 'Lưu ảnh'], ['finish', 'Hoàn thiện']];
const IMG_DEFAULT = { engine: '', template: '', vars: {}, prompt: '', aspect: '9:16', count: 1, quality: 'auto', refs: [], show_browser: false, browser_profile: '' };

function imgTemplate() {
  return state.boot.image_templates.find(t => t.id === state.img.template) || null;
}

function initImages() {
  const b = state.boot;
  state.img = { ...IMG_DEFAULT, engine: b.default_image_engine, ...(b.settings.last_image_form || {}) };
  if (!b.image_engines[state.img.engine]) state.img.engine = b.default_image_engine;
  state.img.vars = state.img.vars || {};
  $('#imgEngine').innerHTML = Object.entries(b.image_engines)
    .map(([id, e]) => `<option value="${id}">${esc(e.name)}${id === b.default_image_engine ? ' — mặc định' : ''}</option>`).join('');
  $('#imgTemplate').innerHTML = '<option value="">✎ Tự nhập prompt</option>'
    + b.image_templates.map(t => `<option value="${esc(t.id)}">🖼 ${esc(t.name)}</option>`).join('');
  $('#imgEngine').value = state.img.engine;
  $('#imgTemplate').value = imgTemplate() ? state.img.template : '';
  $('#imgPrompt').value = state.img.prompt || '';
  $('#imgQuality').value = state.img.quality || 'auto';
  $('#imgShowBrowser').checked = !!state.img.show_browser;

  $('#imgEngine').onchange = e => { state.img.engine = e.target.value; renderImageForm(); saveImageForm(); };
  $('#imgTemplate').onchange = e => { state.img.template = e.target.value; renderImageForm(); saveImageForm(); };
  $('#imgPrompt').oninput = e => { state.img.prompt = e.target.value; saveImageForm(); };
  $('#imgAspect').onchange = e => { state.img.aspect = e.target.value; updateImageEstimate(); saveImageForm(); };
  $('#imgCount').onchange = e => { state.img.count = parseInt(e.target.value, 10); updateImageEstimate(); saveImageForm(); };
  $('#imgQuality').onchange = e => { state.img.quality = e.target.value; saveImageForm(); };
  $('#imgShowBrowser').onchange = e => { state.img.show_browser = e.target.checked; saveImageForm(); };
  $('#imgPickRefs').onclick = async () => {
    const files = await api('pick_files', 'images_multi');
    if (!files.length) return;
    state.img.refs = [...new Set([...(state.img.refs || []), ...files])];
    renderImageRefs();
    saveImageForm();
  };
  $('#imgRefs').onclick = e => {
    const btn = e.target.closest('[data-ref]');
    if (!btn) return;
    state.img.refs.splice(parseInt(btn.dataset.ref, 10), 1);
    renderImageRefs();
    saveImageForm();
  };
  initPinterest();
  $('#imgCreateBtn').onclick = onCreateImage;
  $('#imgLoginBtn').onclick = () => browserLogin(state.img.engine, $('#imgBrowserProfile').value);
  $('#imgStepper').innerHTML = IMG_STAGES.map(([id, label]) => `<div class="step" data-stage="${id}"><i></i><span>${label}</span></div>`).join('');
  $$('.tab[data-imgtab]').forEach(t => { t.onclick = () => switchImageTab(t.dataset.imgtab); });
  $('#imgReload').onclick = refreshImages;
  $('#imgOpenRoot').onclick = () => api('open_images_folder', '');
  $('#imgGallery').onclick = onImageGalleryClick;
  renderImageForm();
  setImageRunning(b.image_running);
  refreshImages();
}

let imgSaveTimer = null;
function saveImageForm() {
  clearTimeout(imgSaveTimer);
  imgSaveTimer = setTimeout(() => api('save_settings', { last_image_form: state.img }), 600);
}

function renderImageForm() {
  const spec = state.boot.image_engines[state.img.engine];
  fillProfileSelects();
  $('#imgEngineNote').innerHTML = `Model: <b>${esc(spec.name)}</b><small>${esc(spec.note)}</small>`;
  const aspect = spec.aspects.includes(state.img.aspect) ? state.img.aspect : spec.aspects[0];
  $('#imgAspect').innerHTML = spec.aspects.map(a => `<option>${a}</option>`).join('');
  $('#imgAspect').value = aspect;
  const fit = spec.counts.filter(c => c <= (state.img.count || 1));
  $('#imgCount').innerHTML = spec.counts.map(c => `<option value="${c}">${c} ảnh</option>`).join('');
  $('#imgCount').value = String(fit.length ? fit[fit.length - 1] : spec.counts[0]);
  $('#imgQualityBox').classList.toggle('hidden', !spec.quality);
  $('#imgBrowserBox').classList.toggle('hidden', !spec.browser);
  updateImageEstimate();
  const t = imgTemplate();
  $('#imgPromptBox').classList.toggle('hidden', !!t);
  $('#imgPreviewBox').classList.toggle('hidden', !t);
  const vars = t ? (state.img.vars[t.id] || (state.img.vars[t.id] = {})) : {};
  if (t) t.variables.forEach(v => { if (vars[v.key] == null && v.default) vars[v.key] = v.default; });
  $('#imgVars').innerHTML = t ? t.variables.map(v => `
    <label class="field"><span>${esc(v.label)} <code>{${esc(v.key)}}</code>${v.required === false ? '' : ' *'}</span>
      <input data-imgvar="${esc(v.key)}" placeholder="${esc(v.placeholder || '')}" value="${esc(vars[v.key] || '')}"></label>`).join('')
    + ((t.attachments || []).some(a => a.default)
      ? `<div class="ref-row"><img class="att-thumb" src="/tpl/${encodeURIComponent(t.id)}/asset/${encodeURIComponent(t.attachments.find(a => a.default).default)}" alt=""><small>Ảnh mẫu của template được gửi kèm làm tham chiếu</small></div>` : '')
    : '';
  $$('input[data-imgvar]').forEach(input => input.addEventListener('input', () => {
    vars[input.dataset.imgvar] = input.value;
    renderImagePreview();
    saveImageForm();
  }));
  renderImagePreview();
  renderImageRefs();
}

function updateImageEstimate() {
  const spec = state.boot.image_engines[state.img.engine];
  $('#imgEstimate').textContent = `${$('#imgCount').value || 1} ảnh · ${$('#imgAspect').value || ''}`;
  const pin = state.img.pin;
  $('#imgEstimateModel').textContent = spec.name + (pin && pin.on ? ` · + Pinterest (${pin.picks?.length || pin.count || 3} ảnh)` : '');
}

function switchImageTab(tab) {
  $$('.tab[data-imgtab]').forEach(t => t.classList.toggle('active', t.dataset.imgtab === tab));
  $('#img-view-progress').classList.toggle('hidden', tab !== 'progress');
  $('#img-view-results').classList.toggle('hidden', tab !== 'results');
}

function setImageProgress({ pct, status, stage }) {
  $('#imgProgressFill').style.width = `${pct}%`;
  $('#imgProgressPct').textContent = `${Math.round(pct)}%`;
  if (status) $('#imgStatusBox').textContent = status;
  const current = IMG_STAGES.findIndex(([id]) => id === stage);
  $$('#imgStepper .step').forEach((el, i) => {
    el.classList.toggle('done', i < current || (pct >= 100 && i < IMG_STAGES.length - 1));
    el.classList.toggle('active', i === current);
  });
}

function setImagePill(text, level = '') {
  $('#imgStatusPill').textContent = text;
  $('#imgStatusPill').className = `status-pill mono ${level}`;
}

function renderImagePreview() {
  const t = imgTemplate();
  if (!t) return;
  const own = state.img.vars[t.id] || {};
  const filled = t.prompt.replace(/\{(\w+)\}/g, (m, key) => {
    const spec = t.variables.find(v => v.key === key);
    if (!spec) return m;
    return (own[key] || '').trim() || (spec.required === false ? '' : m);
  });
  $('#imgPreview').value = filled.split('\n').filter(l => !/^\s*[“"'‘]\s*[”"'’]\s*$/.test(l)).join('\n');
}

function renderImageRefs() {
  const spec = state.boot.image_engines[state.img.engine];
  const refs = state.img.refs || [];
  $('#imgRefs').innerHTML = refs.length
    ? refs.map((p, i) => `<div class="ref-row"><small title="${esc(p)}">${esc(baseName(p))}</small>
        <button class="btn ghost sq" type="button" data-ref="${i}" title="Bỏ">✕</button></div>`).join('')
      + (refs.length > spec.max_images ? `<small class="muted">${esc(spec.name)} chỉ nhận ${spec.max_images} ảnh — ảnh thừa sẽ bị bỏ qua.</small>` : '')
    : '<small class="muted">Chưa có — thêm ảnh sản phẩm/nhân vật để AI giữ đúng hình dáng.</small>';
}

/* ---------- tham khảo ảnh Pinterest ---------- */
const PIN_MAX = 6;

function pinState() {
  return state.img.pin || (state.img.pin = { on: false, keyword: '', count: 3, results: [], picks: [] });
}

function initPinterest() {
  const pin = pinState();
  $('#pinOn').checked = !!pin.on;
  $('#pinKeyword').value = pin.keyword || '';
  $('#pinCount').value = String(pin.count || 3);
  $('#pinOn').onchange = e => {
    pin.on = e.target.checked;
    if (pin.on && !pin.keyword) {  // gợi ý từ khoá từ template / prompt
      const t = imgTemplate();
      pin.keyword = t ? t.name : ($('#imgPrompt').value || '').split(/\s+/).slice(0, 6).join(' ');
      $('#pinKeyword').value = pin.keyword;
    }
    renderPinterest();
    saveImageForm();
  };
  $('#pinKeyword').oninput = e => { pin.keyword = e.target.value; saveImageForm(); };
  $('#pinKeyword').onkeydown = e => { if (e.key === 'Enter') searchPinterest(); };
  $('#pinCount').onchange = e => {
    pin.count = parseInt(e.target.value, 10);
    pin.picks = pin.picks.slice(0, pin.count);
    for (const r of pin.results) {  // thiếu thì bổ sung ảnh kế tiếp
      if (pin.picks.length >= pin.count) break;
      if (!pin.picks.includes(r.url)) pin.picks.push(r.url);
    }
    renderPinterest();
    saveImageForm();
  };
  $('#pinSearchBtn').onclick = searchPinterest;
  $('#pinGrid').onclick = e => {
    const item = e.target.closest('.pin-item');
    if (!item) return;
    const url = item.dataset.url;
    if (pin.picks.includes(url)) pin.picks = pin.picks.filter(u => u !== url);
    else if (pin.picks.length < PIN_MAX) pin.picks.push(url);
    else return toast(`Chọn tối đa ${PIN_MAX} ảnh Pinterest`, 'warn');
    pin.count = Math.max(1, pin.picks.length);
    $('#pinCount').value = String(pin.count);
    renderPinterest();
    saveImageForm();
  };
  renderPinterest();
}

async function searchPinterest() {
  const pin = pinState();
  pin.keyword = $('#pinKeyword').value.trim();
  if (!pin.keyword) { toast('Hãy nhập từ khoá tìm ảnh', 'warn'); $('#pinKeyword').focus(); return; }
  const btn = $('#pinSearchBtn');
  btn.disabled = true;
  btn.textContent = 'Đang tìm…';
  $('#pinStatus').textContent = `Đang tìm “${pin.keyword}” trên Pinterest…`;
  try {
    const res = await api('search_pinterest', pin.keyword, 18);
    if (!res.ok) { toast(res.error, 'error'); $('#pinStatus').textContent = res.error; return; }
    pin.results = res.results;
    pin.picks = res.results.slice(0, pin.count || 3).map(r => r.url);
    renderPinterest();
    saveImageForm();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Tìm ảnh';
  }
}

function renderPinterest() {
  const pin = pinState();
  $('#pinBox').classList.toggle('hidden', !pin.on);
  $('#pinOffHint').classList.toggle('hidden', !!pin.on);
  $('#pinGrid').innerHTML = (pin.results || []).map(r => `
    <button class="pin-item ${pin.picks.includes(r.url) ? 'on' : ''}" type="button" data-url="${esc(r.url)}" title="${esc(r.alt || '')}">
      <img src="${esc(r.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer"><i>✓</i></button>`).join('');
  if (pin.results && pin.results.length) {
    $('#pinStatus').textContent = `${pin.results.length} ảnh · đã chọn ${pin.picks.length} — bấm ảnh để chọn / bỏ chọn.`;
  }
  updateImageEstimate();
}

function imageForm() {
  const t = imgTemplate();
  const pin = pinState();
  return {
    pinterest: { on: !!pin.on, keyword: ($('#pinKeyword').value || '').trim(), count: parseInt($('#pinCount').value, 10),
                 urls: pin.results && pin.results.length ? pin.picks : [] },
    engine: state.img.engine, template: t ? t.id : '', variables: t ? { ...(state.img.vars[t.id] || {}) } : {},
    prompt: $('#imgPrompt').value, aspect: $('#imgAspect').value, count: parseInt($('#imgCount').value, 10),
    quality: $('#imgQuality').value, refs: state.img.refs || [], show_browser: $('#imgShowBrowser').checked,
    browser_profile: $('#imgBrowserProfile').classList.contains('hidden') ? '' : $('#imgBrowserProfile').value,
  };
}

async function onCreateImage() {
  const form = imageForm();
  const t = imgTemplate();
  if (!t && !form.prompt.trim()) { toast('Hãy nhập mô tả ảnh', 'warn'); $('#imgPrompt').focus(); return; }
  if (t) {
    const missing = t.variables.filter(v => v.required !== false && !(form.variables[v.key] || '').trim());
    if (missing.length) { toast(`Hãy điền: ${missing.map(v => v.label).join(', ')}`, 'warn'); return; }
  }
  if (form.pinterest.on && !form.pinterest.keyword && !form.pinterest.urls.length) {
    toast('Nhập từ khoá tìm ảnh Pinterest (hoặc tắt tham khảo Pinterest)', 'warn'); $('#pinKeyword').focus(); return;
  }
  const res = await api('start_image_job', { ...form, vars: state.img.vars, pin: state.img.pin });
  if (!res.ok) return toast(res.error, 'error');
  switchImageTab('progress');
  state.it.select(res.task);
  toast('Đã thêm tác vụ tạo ảnh', 'ok');
}

function setImageRunning(running) {
  state.imgRunning = running;
  const n = state.it ? state.it.active().length : 0;
  $('#imgCreateBtn').textContent = n ? `Thêm ảnh → (${n} đang xử lý)` : 'Tạo ảnh →';
  $('#sbImgRunning').classList.toggle('hidden', !running);
}

async function refreshImages() {
  state.images = await api('list_images');
  $('#sbImageCount').textContent = state.images.length;
  $('#imgTabCount').textContent = state.images.length;
  $('#imgTotal').textContent = `${state.images.length} bộ ảnh`;
  const ratio = a => { const [w, h] = String(a || '1:1').split(':').map(Number); return w && h ? `${w}/${h}` : '1'; };
  $('#imgGallery').innerHTML = state.images.length ? state.images.map(set => `
    <div class="img-set" data-id="${esc(set.id)}">
      <div class="img-set-head">
        <div><b>${esc(set.title)}</b><small>${esc(set.engine_name || set.engine)} · ${esc(set.aspect)} · ${fmtTime(set.created_at)}</small>
          <p title="${esc(set.prompt)}">${esc(set.prompt)}</p></div>
        <div class="row">
          <button class="btn ghost sq" data-act="folder" title="Mở thư mục">↗</button>
          <button class="btn danger sq" data-act="delete" title="Xoá">🗑</button>
        </div>
      </div>
      <div class="img-thumbs" style="--ar:${ratio(set.aspect)}">
        ${set.files.map(f => `<img src="${esc(f.url)}" data-full="${esc(f.url)}" alt="" loading="lazy">`).join('')}
      </div>
    </div>`).join('') : '<div class="empty">Chưa có ảnh nào. Nhập mô tả hoặc chọn template rồi bấm “Tạo ảnh”.</div>';
}

async function onImageGalleryClick(e) {
  const set = e.target.closest('.img-set');
  if (!set) return;
  const img = e.target.closest('img[data-full]');
  if (img) return openModal('ẢNH', set.querySelector('b').textContent, `<div class="viewer"><img src="${esc(img.dataset.full)}" alt=""></div>`, true);
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'folder') return api('open_images_folder', set.dataset.id);
  if (act === 'delete') {
    if (!confirm('Xoá bộ ảnh này (xoá cả file trên ổ đĩa)?')) return;
    const r = await api('delete_images', set.dataset.id);
    if (!r.ok) return toast(r.error, 'error');
    refreshImages();
  }
}

/* ------------------------------------------------------------------ fanpage Facebook */
function initFacebook() {
  $('#fbSaveApp').onclick = () => fbAction($('#fbSaveApp'), 'Đang kiểm tra…', 'fb_save_app',
    [$('#fbAppId').value, $('#fbAppSecret').value, $('#fbVersion').value], 'Đã kết nối App Meta');
  $('#fbOpenExplorer').onclick = () => api('open_url', (state.fb && state.fb.explorer_url) || 'https://developers.facebook.com/tools/explorer/');
  $('#fbConnect').onclick = async () => {
    if (!$('#fbToken').value.trim()) { toast('Hãy dán User Access Token từ Graph API Explorer', 'warn'); $('#fbToken').focus(); return; }
    await fbAction($('#fbConnect'), 'Đang kiểm tra token…', 'fb_connect_token', [$('#fbToken').value], 'Đã kết nối và tải danh sách Fanpage');
    if (state.fb && state.fb.logged_in) $('#fbToken').value = '';  // token đã lưu ở backend, không giữ trên giao diện
  };
  $('#fbLogout').onclick = () => fbAction($('#fbLogout'), 'Đang ngắt…', 'fb_logout', [], 'Đã ngắt kết nối Facebook');
  $('#fbLoadPages').onclick = () => fbAction($('#fbLoadPages'), 'Đang tải…', 'fb_load_pages', [], 'Đã tải danh sách Fanpage');
  $('#fbPages').onclick = onFbPageClick;
  refreshFacebook();
}

async function refreshFacebook() {
  const res = await api('fb_state');
  if (res.ok) renderFacebook(res.fb);
}

async function fbAction(btn, busyText, method, args, okText) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = busyText;
  try {
    const res = await api(method, ...args);
    if (!res.ok) return toast(res.error, 'error');
    renderFacebook(res.fb);
    if (okText) toast(okText, 'ok');
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

function renderFacebook(fb) {
  state.fb = fb;
  $('#fbAppId').value = fb.app_id || '';
  $('#fbVersion').value = fb.graph_version || 'v21.0';
  $('#fbAppSecret').placeholder = fb.has_secret ? '•••••••• (đã lưu — để trống để giữ nguyên)' : 'App Secret';
  $('#fbAppTag').textContent = fb.app_name ? `✓ ${fb.app_name}` : 'tuỳ chọn';
  const user = fb.user;
  const expiry = fb.token_expires_at ? `hết hạn ${fmtTime(fb.token_expires_at)}`
    : 'token ngắn hạn (~1–2 giờ) — nhập App Meta để đổi dài hạn';
  $('#fbUser').innerHTML = user
    ? `${user.picture ? `<img src="${esc(user.picture)}" alt="">` : ''}<div><b>${esc(user.name)}</b><br>
       <small>${fb.long_lived ? '✓ Token dài hạn · ' : ''}${esc(expiry)}</small></div>`
    : '<span>Chưa kết nối — dán User Access Token rồi bấm “Kết nối & tải Fanpage”.</span>';
  $('#fbPerms').innerHTML = fb.logged_in
    ? (fb.permissions || []).filter(p => p.startsWith('pages_') || p === 'business_management').map(p => `<code>✓ ${esc(p)}</code>`).join('')
      + (fb.missing_permissions || []).map(p => `<code class="miss" title="Thiếu quyền — thêm trong Graph API Explorer rồi tạo token mới">✕ ${esc(p)}</code>`).join('')
    : '';
  $('#fbLogout').classList.toggle('hidden', !fb.logged_in);
  $('#fbLoadPages').disabled = !fb.logged_in;
  const pages = fb.pages || [];
  const connected = pages.filter(p => p.connected).length;
  $('#sbFbCount').textContent = connected;
  $('#fbPagesTotal').textContent = pages.length ? `③ ${pages.length} Fanpage · đã kết nối ${connected}` : '③ Chưa có fanpage';
  $('#fbPages').innerHTML = pages.length ? pages.map(p => `
    <div class="fb-page ${p.connected ? 'on' : ''}" data-id="${esc(p.id)}">
      ${p.picture ? `<img src="${esc(p.picture)}" alt="">` : '<img alt="">'}
      <div class="info"><b>${esc(p.name)}</b>
        <small>${esc(p.category || '')}${p.fan_count != null ? ` · ${Number(p.fan_count).toLocaleString('vi-VN')} người theo dõi` : ''} · ID ${esc(p.id)}</small></div>
      <label class="check"><input type="checkbox" data-act="connect" ${p.connected ? 'checked' : ''}> Kết nối</label>
      <button class="btn ghost sm" data-act="post" ${p.connected ? '' : 'disabled'}>Đăng bài</button>
      ${p.link ? `<button class="btn ghost sq" data-act="open" title="Mở page">↗</button>` : ''}
    </div>`).join('')
    : `<div class="empty">${fb.logged_in ? 'Không có Fanpage nào — kiểm tra quyền pages_show_list và các page đã chọn khi tạo token.'
      : 'Dán User Access Token để tải các Fanpage bạn quản lý.'}</div>`;
}

async function onFbPageClick(e) {
  const row = e.target.closest('.fb-page');
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!row || !act) return;
  const page = state.fb.pages.find(p => p.id === row.dataset.id);
  if (act === 'connect') {
    const res = await api('fb_set_connected', page.id, e.target.checked);
    if (res.ok) renderFacebook(res.fb); else toast(res.error, 'error');
  } else if (act === 'open') {
    window.open(page.link, '_blank');
  } else if (act === 'post') {
    openFbPost(page);
  }
}

function openFbPost(page) {
  let file = '';
  openModal('ĐĂNG BÀI', page.name, `
    <div class="form">
      <label class="field"><span>Nội dung bài đăng</span><textarea id="fbMsg" rows="5" placeholder="Viết nội dung…"></textarea></label>
      <div class="asset-row"><div class="asset-info"><b>Ảnh / video (tuỳ chọn)</b><small id="fbFile">Chưa chọn — chỉ đăng chữ</small></div>
        <div class="row"><button class="btn ghost" id="fbPickFile" type="button">Chọn file…</button>
          <button class="btn ghost sq" id="fbClearFile" type="button" title="Bỏ chọn">✕</button></div></div>
      <div class="modal-foot"><button class="btn primary" id="fbSend" type="button">Đăng lên ${esc(page.name)}</button></div>
    </div>`, true);
  $('#modalBody').onclick = null;
  $('#fbPickFile').onclick = async () => {
    const files = await api('pick_files', 'media');
    if (files.length) { file = files[0]; $('#fbFile').textContent = baseName(file); $('#fbFile').classList.add('set'); }
  };
  $('#fbClearFile').onclick = () => { file = ''; $('#fbFile').textContent = 'Chưa chọn — chỉ đăng chữ'; };
  $('#fbSend').onclick = async () => {
    const btn = $('#fbSend');
    btn.disabled = true;
    btn.textContent = file ? 'Đang tải lên…' : 'Đang đăng…';
    const res = await api('fb_post', page.id, $('#fbMsg').value, file);
    btn.disabled = false;
    btn.textContent = `Đăng lên ${page.name}`;
    if (!res.ok) return toast(res.error, 'error');
    closeModal();
    toast(`Đã đăng lên ${res.post.page}`, 'ok');
  };
}

/* ------------------------------------------------------------------ hàng đợi tác vụ (video & ảnh) */
const TASK_STATUS = { queued: 'Đang chờ', running: 'Đang chạy', done: 'Hoàn tất', error: 'Lỗi', cancelled: 'Đã dừng' };

function makeTaskUI(kind, p, { setProgress, setPill, logEl }) {
  const ui = { kind, tasks: [], selected: '' };
  const byId = id => ui.tasks.find(t => t.id === id);
  ui.active = () => ui.tasks.filter(t => t.status === 'queued' || t.status === 'running');
  ui.render = () => {
    const running = ui.tasks.filter(t => t.status === 'running').length;
    const queued = ui.tasks.filter(t => t.status === 'queued').length;
    $(`#${p}TaskSummary`).textContent = ui.tasks.length
      ? `${running} đang chạy · ${queued} đang chờ · ${ui.tasks.length - running - queued} đã xong` : 'Chưa có tác vụ';
    $(`#${p}TaskStopAll`).classList.toggle('hidden', !(running + queued));
    $(`#${p}TaskClear`).classList.toggle('hidden', ui.tasks.length === running + queued);
    $(`#${p}TaskList`).innerHTML = ui.tasks.slice().reverse().map(t => `
      <div class="task ${t.status} ${t.id === ui.selected ? 'sel' : ''}" data-task="${esc(t.id)}" title="${esc(t.title)}">
        <i class="task-dot"></i>
        <div class="task-main"><b>${esc(t.title)}</b>
          <small>${esc(TASK_STATUS[t.status] || t.status)}${t.status === 'running' ? ` · ${esc(t.status_text || '')}` : ''}${t.error ? ` · ${esc(t.error)}` : ''}</small>
          <div class="task-bar"><i style="width:${t.status === 'done' ? 100 : t.pct || 0}%"></i></div></div>
        <span class="mono task-pct">${t.status === 'done' ? '✓' : `${Math.round(t.pct || 0)}%`}</span>
        ${t.status === 'queued' || t.status === 'running' ? '<button class="btn ghost sq task-stop" data-stop title="Dừng tác vụ này">■</button>' : ''}
      </div>`).join('');
    $(`#${p}TaskPanel`).classList.toggle('no-tasks', !ui.tasks.length);
  };
  const pill = t => setPill(TASK_STATUS[t.status], t.status === 'error' ? 'error' : t.status === 'cancelled' ? 'warn' : '');
  ui.showSelected = async () => {
    const t = byId(ui.selected);
    ui.shown = t ? t.id : '';
    logEl.innerHTML = '';
    if (!t) { setProgress({ pct: 0, status: 'Chưa có tác vụ', stage: '' }); setPill('Sẵn sàng'); return; }
    setProgress({ pct: t.status === 'done' ? 100 : t.pct, status: t.error || t.status_text, stage: t.stage });
    pill(t);
    const logs = await api('task_logs', kind, t.id);
    if (ui.selected !== t.id) return;
    logEl.innerHTML = '';
    logs.forEach(l => ui.appendLog(l));
  };
  ui.select = id => {
    ui.selected = id;
    ui.pending = !byId(id);  // tác vụ mới: chờ sự kiện danh sách tới rồi mới hiển thị
    ui.render();
    if (!ui.pending) ui.showSelected();
  };
  ui.update = list => {
    ui.tasks = list;
    if (!byId(ui.selected) && !ui.pending) {
      const next = ui.active()[0] || ui.tasks[ui.tasks.length - 1];
      ui.selected = next ? next.id : '';
      ui.showSelected();
    } else if (byId(ui.selected) && ui.shown !== ui.selected) {
      ui.pending = false;  // tác vụ vừa thêm đã có trong danh sách → hiển thị tiến trình/log của nó
      ui.showSelected();
    }
    ui.render();
    const t = byId(ui.selected);
    if (t) pill(t);
  };
  ui.appendLog = entry => {
    const line = document.createElement('div');
    line.className = `ln ${entry.level || 'info'}`;
    line.innerHTML = `<span class="t">${esc(entry.time)}</span><i class="dot"></i><span class="msg">${esc(entry.message)}</span>`;
    logEl.appendChild(line);
    while (logEl.children.length > MAX_LOG_LINES) logEl.firstChild.remove();
    if (state.autoScroll || kind === 'image') logEl.scrollTop = logEl.scrollHeight;
  };
  ui.onLog = entry => { if (entry.task === ui.selected) ui.appendLog(entry); };
  ui.onProgress = d => {
    const t = byId(d.task);
    if (t) {
      Object.assign(t, { pct: d.pct, status_text: d.status, stage: d.stage });
      const el = $(`#${p}TaskList [data-task="${CSS.escape(d.task)}"]`);
      if (el) {
        el.querySelector('.task-bar i').style.width = `${d.pct}%`;
        el.querySelector('.task-pct').textContent = `${Math.round(d.pct)}%`;
        el.querySelector('small').textContent = `${TASK_STATUS.running} · ${d.status || ''}`;
      }
    }
    if (d.task === ui.selected) setProgress(d);
  };
  $(`#${p}TaskList`).onclick = async e => {
    const row = e.target.closest('[data-task]');
    if (!row) return;
    if (e.target.closest('[data-stop]')) {
      await api(kind === 'image' ? 'cancel_image_job' : 'cancel_job', row.dataset.task);
      toast('Đang dừng tác vụ…', 'warn');
      return;
    }
    ui.select(row.dataset.task);
  };
  $(`#${p}TaskStopAll`).onclick = async () => {
    if (!confirm(`Dừng tất cả ${ui.active().length} tác vụ đang chạy/chờ?`)) return;
    await api(kind === 'image' ? 'cancel_image_job' : 'cancel_job', '');
  };
  $(`#${p}TaskClear`).onclick = async () => { const r = await api('clear_tasks', kind); if (r.ok) ui.update(r.tasks); };
  return ui;
}

/* ------------------------------------------------------------------ profile trình duyệt */
async function browserLogin(engine, profileId) {
  const res = await api('browser_login', engine, profileId || '');
  if (!res.ok) toast(res.error, 'error');
}

const PROFILE_CHANNELS = [['', 'Theo Cài đặt chung'], ['chrome', 'Google Chrome'], ['msedge', 'Microsoft Edge'], ['chromium', 'Chromium (Playwright)']];
const siteOf = id => String(id || '').replace(/_browser$/, '');

function initProfiles() {
  state.profiles = state.boot.profiles || [];
  state.profileSites = state.boot.profile_sites || {};
  $('#profNewSites').innerHTML = Object.entries(state.profileSites)
    .map(([s, n]) => `<label class="chip-check"><input type="checkbox" value="${s}"><span>${esc(n)}</span></label>`).join('');
  $('#profNewChannel').innerHTML = PROFILE_CHANNELS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  $('#profCreate').onclick = async () => {
    const name = $('#profName').value.trim();
    if (!name) { toast('Nhập tên profile', 'warn'); $('#profName').focus(); return; }
    const sites = $$('#profNewSites input:checked').map(i => i.value);
    const res = await api('profiles_create', name, sites, $('#profNewChannel').value);
    if (!res.ok) return toast(res.error, 'error');
    $('#profName').value = '';
    $$('#profNewSites input').forEach(i => { i.checked = false; });
    renderProfiles(res.profiles);
    toast(`Đã thêm profile “${name}” — bấm Đăng nhập ở từng model để đăng nhập tài khoản`, 'ok');
  };
  $('#profList').onclick = onProfileClick;
  $('#profList').onchange = onProfileChange;
  $('#browserProfile').onchange = e => { state.form.browser_profile = e.target.value; onFormChange(); };
  $('#imgBrowserProfile').onchange = e => { state.img.browser_profile = e.target.value; saveImageForm(); };
  renderProfiles(state.profiles);
}

async function refreshProfiles() {
  const res = await api('profiles_list');
  if (res.ok) renderProfiles(res.profiles);
}

function renderProfiles(profiles) {
  state.profiles = profiles;
  $('#sbProfileCount').textContent = profiles.length;
  const sites = state.profileSites;
  $('#profSites').innerHTML = Object.entries(sites).map(([s, n]) => {
    const list = profiles.filter(p => p.sites.includes(s));
    const busy = list.filter(p => p.busy).length;
    return `<div class="prof-site ${list.length ? '' : 'none'}"><small>${esc(n)}</small><b>${list.length} profile</b>
      <span>${list.length ? `chạy song song tối đa ${list.length}${busy ? ` · ${busy} đang bận` : ''}` : 'chưa gán — tác vụ sẽ báo lỗi'}</span></div>`;
  }).join('');
  $('#profList').innerHTML = profiles.map(p => `
    <div class="card prof ${p.busy ? 'busy' : ''}" data-profile="${esc(p.id)}">
      <div class="prof-top">
        <input class="prof-name" data-field="name" value="${esc(p.name)}" maxlength="40" title="Bấm để đổi tên">
        ${p.busy ? `<span class="prof-busy">● Đang dùng: ${esc(p.busy)}</span>` : '<span class="prof-free">Rảnh</span>'}
        <select data-field="channel" title="Trình duyệt của profile">${PROFILE_CHANNELS.map(([v, l]) => `<option value="${v}" ${v === (p.channel || '') ? 'selected' : ''}>${l}</option>`).join('')}</select>
        ${p.id === 'default' ? '<span class="tag">MẶC ĐỊNH</span>' : '<button class="btn danger sm" data-act="delete" type="button">Xoá</button>'}
      </div>
      <div class="prof-models">${Object.entries(sites).map(([s, n]) => `
        <div class="prof-model ${p.sites.includes(s) ? 'on' : ''}">
          <label class="chip-check"><input type="checkbox" data-site="${s}" ${p.sites.includes(s) ? 'checked' : ''}><span>${esc(n)}</span></label>
          <button class="btn ghost sm" data-act="login" data-site="${s}" type="button" ${p.busy ? 'disabled' : ''}>Đăng nhập</button>
        </div>`).join('')}</div>
      <small class="muted mono">ID ${esc(p.id)}${p.exists ? '' : ' · chưa mở lần nào'}</small>
    </div>`).join('');
  fillProfileSelects();
}

async function onProfileClick(e) {
  const card = e.target.closest('[data-profile]');
  const btn = e.target.closest('[data-act]');
  if (!card || !btn) return;
  const id = card.dataset.profile;
  const prof = state.profiles.find(p => p.id === id);
  if (btn.dataset.act === 'login') {
    const res = await api('browser_login', `${btn.dataset.site}_browser`, id);
    if (!res.ok) toast(res.error, 'error');
  } else if (btn.dataset.act === 'delete') {
    if (!confirm(`Xoá profile “${prof.name}”?\nToàn bộ phiên đăng nhập (cookie) của profile này sẽ bị xoá khỏi máy.`)) return;
    const res = await api('profiles_delete', id);
    if (!res.ok) return toast(res.error, 'error');
    renderProfiles(res.profiles);
    toast('Đã xoá profile', 'ok');
  }
}

async function onProfileChange(e) {
  const card = e.target.closest('[data-profile]');
  if (!card) return;
  const id = card.dataset.profile;
  let res;
  if (e.target.dataset.site) {
    const sites = $$('input[data-site]', card).filter(i => i.checked).map(i => i.dataset.site);
    res = await api('profiles_update', id, null, sites, null);
  } else if (e.target.dataset.field === 'name') {
    res = await api('profiles_update', id, e.target.value, null, null);
  } else if (e.target.dataset.field === 'channel') {
    res = await api('profiles_update', id, null, null, e.target.value);
  }
  if (!res) return;
  if (!res.ok) { toast(res.error, 'error'); return refreshProfiles(); }
  renderProfiles(res.profiles);
}

/** Ô chọn profile trong form Tạo video / Tạo ảnh — chỉ hiện với model chạy bằng trình duyệt. */
function fillProfileSelects() {
  if (!state.profiles) return;
  const fill = (sel, engine, current) => {
    const site = siteOf(engine);
    const isBrowser = String(engine || '').endsWith('_browser') && !!state.profileSites[site];
    sel.classList.toggle('hidden', !isBrowser);
    if (!isBrowser) return;
    const assigned = state.profiles.filter(p => p.sites.includes(site));
    const others = state.profiles.filter(p => !p.sites.includes(site));
    sel.innerHTML = `<option value="">Tự chọn profile rảnh (${assigned.length})</option>`
      + assigned.map(p => `<option value="${esc(p.id)}">👤 ${esc(p.name)}${p.busy ? ' · đang bận' : ''}</option>`).join('')
      + (others.length ? `<optgroup label="Chưa gán cho ${esc(state.profileSites[site])}">${others.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</optgroup>` : '');
    sel.value = state.profiles.some(p => p.id === current) ? current : '';
  };
  fill($('#browserProfile'), $('#provider').value, state.form.browser_profile);
  if (state.img) fill($('#imgBrowserProfile'), state.img.engine, state.img.browser_profile);
}

/* ------------------------------------------------------------------ quảng cáo Facebook */
const ADS_LEVELS = { campaign: 'Chiến dịch', adset: 'Nhóm quảng cáo', ad: 'Quảng cáo' };
const ADS_CHILD = { campaign: 'adset', adset: 'ad' };
const ADS_STATUS = {
  ACTIVE: 'Đang chạy', PAUSED: 'Tạm dừng', CAMPAIGN_PAUSED: 'CD tạm dừng', ADSET_PAUSED: 'Nhóm tạm dừng',
  PENDING_REVIEW: 'Chờ duyệt', IN_PROCESS: 'Đang xử lý', WITH_ISSUES: 'Có lỗi', DISAPPROVED: 'Bị từ chối',
  PREAPPROVED: 'Đã duyệt trước', ARCHIVED: 'Lưu trữ', DELETED: 'Đã xoá', PENDING_BILLING_INFO: 'Thiếu thanh toán',
};
const ADS_RANGE_KEY = 'va.ads.range';

function initAds() {
  state.ads = { status: null, accounts: [], account: '', range: 'last_7d', path: [], data: null, loaded: false };
  try { state.ads.range = localStorage.getItem(ADS_RANGE_KEY) || 'last_7d'; } catch { /* bỏ qua */ }
  $('#adsRange').value = state.ads.range;
  $('#adsRange').onchange = e => {
    state.ads.range = e.target.value;
    try { localStorage.setItem(ADS_RANGE_KEY, state.ads.range); } catch { /* bỏ qua */ }
    loadAdsData();
  };
  $('#adsAccount').onchange = e => { state.ads.account = e.target.value; state.ads.path = []; loadAdsData(); };
  $('#adsRefresh').onclick = () => refreshAds(true);
  $('#adsOpenManager').onclick = () => {
    const acc = state.ads.accounts.find(a => a.id === state.ads.account);
    api('open_url', `https://adsmanager.facebook.com/adsmanager/manage/campaigns${acc ? `?act=${acc.account_id}` : ''}`);
  };
  $('#adsCreate').onclick = openAdsCreate;
  $('#adsCrumbs').onclick = e => {
    const btn = e.target.closest('[data-depth]');
    if (!btn) return;
    state.ads.path = state.ads.path.slice(0, +btn.dataset.depth);
    loadAdsData();
  };
  $('#adsTable').onclick = onAdsTableClick;
  $('#adsTable').onchange = onAdsTableChange;
}

function adsMoney(v, cur = (state.ads.data && state.ads.data.currency) || '') {
  if (v == null) return '—';
  try { return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: cur || 'VND', maximumFractionDigits: cur === 'VND' ? 0 : 2 }).format(v); }
  catch { return `${Number(v).toLocaleString('vi-VN')} ${cur}`; }
}
const adsNum = v => (v ? Number(v).toLocaleString('vi-VN') : '0');
const adsPct = v => `${Number(v || 0).toLocaleString('vi-VN', { maximumFractionDigits: 2 })}%`;

async function refreshAds(force = false) {
  const st = await api('ads_status');
  state.ads.status = st.ads;
  const miss = st.ads.missing_permissions;
  const alert = $('#adsAlert');
  if (!st.ads.logged_in) {
    alert.innerHTML = 'Chưa kết nối Facebook. Vào <b>Fanpage Facebook</b>, dán User Access Token có quyền <code>ads_read</code> <code>ads_management</code>.'
      + '<button class="btn ghost sm" data-go="facebook">Đến Fanpage Facebook</button>';
  } else if (miss.length) {
    alert.innerHTML = `Token thiếu quyền ${miss.map(p => `<code>${p}</code>`).join(' ')} — thêm trong Graph API Explorer, tạo token mới rồi dán lại ở mục Fanpage Facebook.`
      + '<button class="btn ghost sm" data-go="facebook">Đến Fanpage Facebook</button>';
  }
  alert.classList.toggle('hidden', st.ads.logged_in && !miss.length);
  alert.onclick = e => { if (e.target.closest('[data-go]')) navigate('facebook'); };
  $('#adsCreate').disabled = !st.ads.logged_in;
  if (!st.ads.logged_in) { renderAdsEmpty('Kết nối Facebook để xem tài khoản quảng cáo.'); return; }
  if (state.ads.loaded && !force) return;
  renderAdsEmpty('Đang tải tài khoản quảng cáo…');
  const res = await api('ads_accounts');
  if (!res.ok) { renderAdsEmpty(res.error); return toast(res.error, 'error'); }
  state.ads.accounts = res.accounts;
  state.ads.loaded = true;
  if (!res.accounts.some(a => a.id === state.ads.account)) {
    state.ads.account = (res.accounts.find(a => a.active) || res.accounts[0] || {}).id || '';
    state.ads.path = [];
  }
  $('#adsAccount').innerHTML = res.accounts.length
    ? res.accounts.map(a => `<option value="${esc(a.id)}">${esc(a.name || a.account_id)} · ${esc(a.currency)}${a.active ? '' : ' (không hoạt động)'}</option>`).join('')
    : '<option value="">Không có tài khoản quảng cáo</option>';
  $('#adsAccount').value = state.ads.account;
  if (!state.ads.account) return renderAdsEmpty('Tài khoản Facebook này chưa có tài khoản quảng cáo nào (hoặc token chưa có quyền ads_read).');
  await loadAdsData();
}

function renderAdsEmpty(text) {
  $('#adsKpis').innerHTML = '';
  $('#adsCrumbs').innerHTML = '';
  $('#adsAccountInfo').innerHTML = '';
  $('#adsTable').innerHTML = `<tbody><tr><td class="l"><div class="empty">${esc(text)}</div></td></tr></tbody>`;
}

async function loadAdsData() {
  const ads = state.ads;
  if (!ads.account) return;
  const acc = ads.accounts.find(a => a.id === ads.account) || {};
  $('#adsAccountInfo').innerHTML = [
    acc.business && `Doanh nghiệp: <b>${esc(acc.business)}</b>`,
    `Đã chi tổng: <b>${esc(adsMoney(acc.amount_spent, acc.currency))}</b>`,
    acc.spend_cap != null && `Giới hạn chi tiêu: <b>${esc(adsMoney(acc.spend_cap, acc.currency))}</b>`,
    acc.timezone && `Múi giờ: ${esc(acc.timezone)}`,
    !acc.active && '<span class="bad">Tài khoản không hoạt động (bị khoá / thiếu thanh toán)</span>',
  ].filter(Boolean).join(' · ');
  const level = ads.path.length ? ADS_CHILD[ads.path[ads.path.length - 1].level] : 'campaign';
  const parent = ads.path.length ? ads.path[ads.path.length - 1].id : '';
  renderAdsCrumbs(level);
  $('#adsTable').innerHTML = '<tbody><tr><td class="l"><div class="empty">Đang tải số liệu…</div></td></tr></tbody>';
  const req = `${ads.account}|${level}|${parent}|${ads.range}`;
  ads.req = req;
  const [ov, list] = await Promise.all([
    ads.path.length ? Promise.resolve(null) : api('ads_overview', ads.account, ads.range),
    api('ads_list', ads.account, level, parent, ads.range),
  ]);
  if (ads.req !== req) return;  // người dùng đã đổi bộ lọc trong lúc tải
  if (!list.ok) { renderAdsEmpty(list.error); return toast(list.error, 'error'); }
  ads.data = list.data;
  if (ov && ov.ok) ads.overview = ov.overview;
  renderAdsKpis(ads.path.length ? sumInsights(list.data.items) : (ads.overview || {}).insights);
  renderAdsTable();
  if (level === 'campaign') $('#sbAdsCount').textContent = list.data.items.filter(i => i.effective_status === 'ACTIVE').length;
}

function sumInsights(items) {
  const s = { spend: 0, impressions: 0, reach: 0, clicks: 0, result: null };
  items.forEach(i => { s.spend += i.insights.spend; s.impressions += i.insights.impressions; s.reach += i.insights.reach; s.clicks += i.insights.clicks; });
  s.ctr = s.impressions ? s.clicks / s.impressions * 100 : 0;
  s.cpc = s.clicks ? s.spend / s.clicks : 0;
  s.cpm = s.impressions ? s.spend / s.impressions * 1000 : 0;
  s.frequency = s.reach ? s.impressions / s.reach : 0;
  return s;
}

function renderAdsCrumbs(level) {
  const path = state.ads.path;
  $('#adsCrumbs').innerHTML = [`<button data-depth="0" class="${path.length ? '' : 'cur'}">Tất cả chiến dịch</button>`,
    ...path.map((p, i) => `<span class="muted">›</span><button data-depth="${i + 1}" class="${i === path.length - 1 ? 'cur' : ''}" title="${esc(p.name)}">${esc(p.name.length > 40 ? `${p.name.slice(0, 40)}…` : p.name)}</button>`),
  ].join('') + `<span class="muted" style="margin-left:auto">${ADS_LEVELS[level]}</span>`;
}

function renderAdsKpis(ins) {
  if (!ins) { $('#adsKpis').innerHTML = ''; return; }
  const kpi = (label, value, main) => `<div class="ads-kpi ${main ? 'main' : ''}"><small>${label}</small><b title="${esc(value)}">${esc(value)}</b></div>`;
  $('#adsKpis').innerHTML = kpi('Chi tiêu', adsMoney(ins.spend), true) + kpi('Tiếp cận', adsNum(ins.reach))
    + kpi('Lượt hiển thị', adsNum(ins.impressions)) + kpi('Lượt nhấp', adsNum(ins.clicks)) + kpi('CTR', adsPct(ins.ctr))
    + kpi('CPC', adsMoney(ins.cpc)) + kpi('CPM', adsMoney(ins.cpm))
    + (ins.result ? kpi(`Kết quả (${ins.result.label})`, adsNum(ins.result.count)) : '');
}

function renderAdsTable() {
  const { level, items } = state.ads.data;
  const hasBudget = level !== 'ad';
  const head = `<thead><tr><th class="l">Bật</th><th class="l">${ADS_LEVELS[level]}</th><th class="l">Trạng thái</th>
    ${hasBudget ? '<th>Ngân sách</th>' : ''}<th>Chi tiêu</th><th>Kết quả</th><th>Chi phí/KQ</th><th>Tiếp cận</th>
    <th>Hiển thị</th><th>Nhấp</th><th>CTR</th><th>CPC</th></tr></thead>`;
  if (!items.length) {
    $('#adsTable').innerHTML = `${head}<tbody><tr><td class="l" colspan="12"><div class="empty">Chưa có ${ADS_LEVELS[level].toLowerCase()} nào.</div></td></tr></tbody>`;
    return;
  }
  const rows = items.map(i => {
    const ins = i.insights;
    const budget = i.daily_budget != null ? `<span class="ads-budget" data-act="budget" title="Bấm để đổi ngân sách/ngày">${esc(adsMoney(i.daily_budget))}/ngày</span>`
      : i.lifetime_budget != null ? `${esc(adsMoney(i.lifetime_budget))} trọn đời` : '<span class="muted" title="Ngân sách đặt ở cấp khác">—</span>';
    const sub = level === 'campaign' ? i.objective.replace('OUTCOME_', '') : level === 'adset' ? i.optimization_goal : (i.post_id ? `Bài viết ${i.post_id}` : '');
    const toggleable = ['ACTIVE', 'PAUSED'].includes(i.status);
    return `<tr data-id="${esc(i.id)}">
      <td class="l"><label class="switch" title="${i.status === 'ACTIVE' ? 'Tắt' : 'Bật'}"><input type="checkbox" data-act="status" ${i.status === 'ACTIVE' ? 'checked' : ''} ${toggleable ? '' : 'disabled'}><span></span></label></td>
      <td class="l"><div class="ads-name">${i.thumbnail ? `<img src="${esc(i.thumbnail)}" alt="">` : ''}<div>
        <a class="${ADS_CHILD[level] ? 'drill' : ''}" data-act="drill" title="${esc(i.name)}">${esc(i.name)}</a><small>${esc(sub)} · ID ${esc(i.id)}</small></div></div></td>
      <td class="l"><span class="ads-st ${esc(i.effective_status)}">${esc(ADS_STATUS[i.effective_status] || i.effective_status)}</span></td>
      ${hasBudget ? `<td>${budget}</td>` : ''}
      <td><b>${esc(adsMoney(ins.spend))}</b></td>
      <td>${ins.result ? `${adsNum(ins.result.count)}<br><small class="muted">${esc(ins.result.label)}</small>` : '—'}</td>
      <td>${ins.result && ins.result.count ? esc(adsMoney(ins.spend / ins.result.count)) : '—'}</td>
      <td>${adsNum(ins.reach)}</td><td>${adsNum(ins.impressions)}</td><td>${adsNum(ins.clicks)}</td>
      <td>${adsPct(ins.ctr)}</td><td>${ins.cpc ? esc(adsMoney(ins.cpc)) : '—'}</td></tr>`;
  }).join('');
  const t = sumInsights(items);
  const foot = `<tfoot><tr><td class="l"></td><td class="l">Tổng ${items.length} ${ADS_LEVELS[level].toLowerCase()}</td><td></td>${hasBudget ? '<td></td>' : ''}
    <td>${esc(adsMoney(t.spend))}</td><td></td><td></td><td>${adsNum(t.reach)}</td><td>${adsNum(t.impressions)}</td>
    <td>${adsNum(t.clicks)}</td><td>${adsPct(t.ctr)}</td><td>${t.cpc ? esc(adsMoney(t.cpc)) : '—'}</td></tr></tfoot>`;
  $('#adsTable').innerHTML = head + `<tbody>${rows}</tbody>` + foot;
}

function adsItem(el) {
  const id = el.closest('tr[data-id]')?.dataset.id;
  return state.ads.data.items.find(i => i.id === id);
}

async function onAdsTableClick(e) {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act || act === 'status') return;
  const item = adsItem(e.target);
  if (!item) return;
  const level = state.ads.data.level;
  if (act === 'drill' && ADS_CHILD[level]) {
    state.ads.path.push({ level, id: item.id, name: item.name });
    loadAdsData();
  } else if (act === 'budget') {
    const cur = state.ads.data.currency;
    const value = prompt(`Ngân sách mỗi ngày mới cho “${item.name}” (${cur}):`, item.daily_budget);
    if (value == null || value.trim() === '' || Number(value) === item.daily_budget) return;
    const amount = Number(value.replace(/[.,\s](?=\d{3}\b)/g, '').replace(',', '.'));
    if (!(amount > 0)) return toast('Ngân sách phải là số lớn hơn 0', 'warn');
    if (!confirm(`Đổi ngân sách “${item.name}” từ ${adsMoney(item.daily_budget)} thành ${adsMoney(amount)}/ngày?\nThay đổi có hiệu lực ngay và ảnh hưởng chi phí thật.`)) return;
    const res = await api('ads_set_budget', state.ads.account, item.id, amount);
    if (!res.ok) return toast(res.error, 'error');
    item.daily_budget = res.result.daily_budget;
    renderAdsTable();
    toast('Đã đổi ngân sách', 'ok');
  }
}

async function onAdsTableChange(e) {
  if (e.target.dataset.act !== 'status') return;
  const input = e.target;
  const item = adsItem(input);
  const status = input.checked ? 'ACTIVE' : 'PAUSED';
  const msg = status === 'ACTIVE'
    ? `BẬT “${item.name}”?\nQuảng cáo sẽ bắt đầu chạy và tiêu tiền thật từ tài khoản quảng cáo.`
    : `Tạm dừng “${item.name}”?`;
  if (!confirm(msg)) { input.checked = !input.checked; return; }
  input.disabled = true;
  const res = await api('ads_set_status', item.id, status);
  input.disabled = false;
  if (!res.ok) { input.checked = !input.checked; return toast(res.error, 'error'); }
  toast(status === 'ACTIVE' ? 'Đã bật — Facebook có thể cần duyệt trước khi chạy' : 'Đã tạm dừng', 'ok');
  loadAdsData();
}

const POST_TYPES = {
  added_photos: ['photo', '🖼 Ảnh'], added_video: ['video', '🎬 Video'], shared_story: ['text', '🔗 Chia sẻ'],
  mobile_status_update: ['text', '✎ Trạng thái'], created_note: ['text', '✎ Ghi chú'], published_story: ['text', '✎ Bài viết'],
};
const postKind = t => (POST_TYPES[t] || ['text'])[0];

function postRow(p, selected) {
  const [, typeLabel] = POST_TYPES[p.type] || ['text', '✎ Bài viết'];
  const stat = (icon, v, title) => (v == null ? '' : `<span title="${title}">${icon} ${Number(v).toLocaleString('vi-VN')}</span>`);
  const badge = p.eligible === false ? '<span class="ads-elig no">Không đủ ĐK quảng cáo</span>'
    : p.eligible ? '<span class="ads-elig">✓ Quảng cáo được</span>' : '';
  return `
    <div class="ads-post ${selected ? 'on' : ''} ${p.eligible === false ? 'off' : ''}" data-post="${esc(p.id)}" role="button" tabindex="0">
      <span class="ads-radio"></span>
      <div class="ads-thumb">${p.picture ? `<img src="${esc(p.picture)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{textContent:'Không có ảnh'}))">` : '<span>Không có ảnh</span>'}
        ${postKind(p.type) === 'video' ? '<i>▶</i>' : ''}</div>
      <div class="ads-post-body">
        <p>${esc(p.message || '(không có nội dung chữ)')}</p>
        <div class="ads-post-meta">
          <span class="ads-type">${typeLabel}</span>
          <span title="Ngày đăng">🕒 ${esc(fmtTime(p.created_time))}</span>
          ${stat('👍', p.reactions, 'Cảm xúc')}${stat('💬', p.comments, 'Bình luận')}${stat('↗', p.shares, 'Chia sẻ')}
          ${badge}
        </div>
        <small class="mono muted">ID ${esc(p.id)}</small>
      </div>
      ${p.link ? `<button class="btn ghost sm" type="button" data-open="${esc(p.link)}" title="Xem bài trên Facebook">Xem ↗</button>` : ''}
    </div>`;
}

function openAdsCreate() {
  const ads = state.ads;
  const st = ads.status || {};
  const pages = st.pages || [];
  if (!ads.account) return toast('Chưa có tài khoản quảng cáo', 'warn');
  if (!pages.length) return toast('Chưa có Fanpage — tải danh sách Fanpage ở mục Fanpage Facebook trước', 'warn');
  const acc = ads.accounts.find(a => a.id === ads.account) || {};
  const cur = acc.currency || 'VND';
  const form = { page_id: pages[0].id, post_id: '' };
  openModal('TẠO QUẢNG CÁO', 'Quảng cáo bài viết Fanpage', `
    <div class="form">
      <div class="ads-form">
        <label class="field"><span>Tài khoản quảng cáo</span><input value="${esc(acc.name || acc.account_id)} · ${esc(cur)}" disabled></label>
        <label class="field"><span>Fanpage</span><select id="adPage">${pages.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></label>
        <div class="field full"><span>Chọn bài viết để quảng cáo</span>
          <div class="ads-post-tools"><input id="adPostSearch" placeholder="Tìm theo nội dung bài viết…">
            <select id="adPostType"><option value="">Mọi loại bài</option><option value="photo">Ảnh</option><option value="video">Video</option><option value="text">Chữ / khác</option></select></div>
          <div class="ads-posts" id="adPosts"><div class="empty">Đang tải bài viết…</div></div>
          <div class="ads-post-foot"><span class="muted" id="adPostCount"></span><button class="btn ghost sm hidden" id="adPostMore" type="button">Tải thêm bài viết</button></div></div>
        <label class="field full"><span>Tên chiến dịch</span><input id="adName" placeholder="Để trống = tự đặt tên"></label>
        <label class="field"><span>Mục tiêu</span><select id="adObjective">${Object.entries(st.objectives || {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
        <label class="field"><span>Ngân sách mỗi ngày (${esc(cur)})</span><input id="adBudget" type="number" min="1" value="${cur === 'VND' ? 100000 : 5}"></label>
        <label class="field"><span>Số ngày chạy</span><input id="adDays" type="number" min="1" max="90" value="7"></label>
        <label class="field"><span>Quốc gia (mã, cách nhau dấu phẩy)</span><input id="adCountries" value="VN"></label>
        <label class="field"><span>Tuổi từ</span><input id="adAgeMin" type="number" min="13" max="65" value="22"></label>
        <label class="field"><span>Đến</span><input id="adAgeMax" type="number" min="13" max="65" value="55"></label>
        <label class="field"><span>Giới tính</span><select id="adGender"><option value="all">Tất cả</option><option value="male">Nam</option><option value="female">Nữ</option></select></label>
        <div class="field"><span>Tổng dự kiến</span><b id="adTotal" style="padding-top:10px"></b></div>
      </div>
      <div class="ads-note">Quảng cáo được tạo ở trạng thái <b>TẠM DỪNG</b> — không tiêu tiền. Kiểm tra trong bảng hoặc Ads Manager rồi bật công tắc khi sẵn sàng.</div>
      <div class="modal-foot"><button class="btn primary" id="adSubmit" type="button">Tạo quảng cáo (tạm dừng)</button></div>
    </div>`, true);
  $('#modalBody').onclick = null;
  const total = () => { $('#adTotal').textContent = adsMoney((+$('#adBudget').value || 0) * (+$('#adDays').value || 0), cur); };
  $('#adBudget').oninput = total; $('#adDays').oninput = total; total();
  let posts = [], after = '';
  const renderPosts = () => {
    const q = $('#adPostSearch').value.trim().toLowerCase();
    const type = $('#adPostType').value;
    const shown = posts.filter(p => (!q || p.message.toLowerCase().includes(q)) && (!type || postKind(p.type) === type));
    $('#adPostCount').textContent = posts.length ? `Hiển thị ${shown.length}/${posts.length} bài${after ? ' (còn bài cũ hơn)' : ''}` : '';
    $('#adPostMore').classList.toggle('hidden', !after);
    $('#adPosts').innerHTML = shown.length ? shown.map(p => postRow(p, p.id === form.post_id)).join('')
      : `<div class="empty">${posts.length ? 'Không có bài viết khớp bộ lọc.' : 'Page chưa có bài viết — dùng “Đăng bài” ở mục Fanpage trước.'}</div>`;
  };
  const loadPosts = async (more = false) => {
    if (!more) { form.post_id = ''; posts = []; after = ''; $('#adPosts').innerHTML = '<div class="empty">Đang tải bài viết…</div>'; }
    const btn = $('#adPostMore');
    btn.disabled = true;
    const res = await api('ads_page_posts', form.page_id, more ? after : '');
    btn.disabled = false;
    if (!res.ok) { if (more) return toast(res.error, 'error'); $('#adPosts').innerHTML = `<div class="empty">${esc(res.error)}</div>`; return; }
    posts = posts.concat(res.posts.posts);
    after = res.posts.after;
    renderPosts();
  };
  $('#adPage').onchange = e => { form.page_id = e.target.value; loadPosts(); };
  $('#adPostSearch').oninput = renderPosts;
  $('#adPostType').onchange = renderPosts;
  $('#adPostMore').onclick = () => loadPosts(true);
  $('#adPosts').onclick = e => {
    if (e.target.closest('[data-open]')) { e.stopPropagation(); api('open_url', e.target.closest('[data-open]').dataset.open); return; }
    const row = e.target.closest('[data-post]');
    if (!row) return;
    const p = posts.find(x => x.id === row.dataset.post);
    if (p && p.eligible === false) return toast('Facebook báo bài này không đủ điều kiện quảng cáo', 'warn');
    form.post_id = row.dataset.post;
    $$('#adPosts .ads-post').forEach(x => x.classList.toggle('on', x === row));
  };
  loadPosts();
  $('#adSubmit').onclick = async () => {
    if (!form.post_id) return toast('Hãy chọn một bài viết', 'warn');
    const btn = $('#adSubmit');
    btn.disabled = true;
    btn.textContent = 'Đang tạo chiến dịch…';
    const res = await api('ads_create_boost', {
      account_id: ads.account, page_id: form.page_id, post_id: form.post_id, name: $('#adName').value,
      objective: $('#adObjective').value, daily_budget: $('#adBudget').value, days: $('#adDays').value,
      countries: $('#adCountries').value, age_min: $('#adAgeMin').value, age_max: $('#adAgeMax').value, gender: $('#adGender').value,
    });
    btn.disabled = false;
    btn.textContent = 'Tạo quảng cáo (tạm dừng)';
    if (!res.ok) return toast(res.error, 'error');
    closeModal();
    toast(`Đã tạo “${res.result.name}” (đang tạm dừng) — bật công tắc khi sẵn sàng`, 'ok');
    state.ads.path = [];
    loadAdsData();
  };
}

/* ------------------------------------------------------------------ form */
function fillSelects() {
  const b = state.boot;
  $('#aspect').innerHTML = b.aspects.map(a => `<option value="${a}">${ASPECT_LABELS[a] || a}</option>`).join('');
  $('#preset').innerHTML = PRESETS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  $('#voice').innerHTML = b.voices.map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');
  $('#rate').innerHTML = b.rates.map(r => `<option value="${r}">${r === '+0%' ? 'Bình thường' : r}</option>`).join('');
}

function restoreForm() {
  const s = state.boot.settings;
  state.form = { ...FORM_DEFAULT, provider: s.provider || FORM_DEFAULT.provider, ...(s.last_form || {}) };
  const f = state.form;
  $('#topic').value = f.topic;
  $('#provider').value = f.provider;
  $('#showBrowser').checked = !!f.show_browser;
  $('#aspect').value = f.aspect;
  $('#preset').value = f.preset;
  $('#seconds').value = f.seconds;
  $('#scenes').value = f.scenes;
  $('#voice').value = f.voice;
  $('#rate').value = f.rate;
  $('#subtitles').checked = !!f.subtitles;
  $('#bgm').checked = !!f.bgm;
  $('#productStyle').value = f.product_style;
  $('#brand').value = f.brand;
  $('#commentName').value = f.comment_name;
  $('#commentText').value = f.comment_text;
  $('#price').value = f.price;
  $('#oldPrice').value = f.old_price;
  $('#perk').value = f.perk;
  $('#contact').value = f.contact;
  $('#keepAudio').checked = !!f.keep_audio;
  $('#geminiMode').value = f.gemini_mode || 'veo';
  $('#aiDuration').value = f.ai_duration || '15s';
  $('#aiResolution').value = f.ai_resolution || '720p';
  $('#geminiModel').value = s.gemini_model || '';
  $('#geminiKey').value = s.gemini_api_key || '';
  updateLabels();
  updateProviderUI();
  updateEstimate();
}

function readForm() {
  return {
    ...state.form,
    topic: $('#topic').value,
    provider: $('#provider').value,
    show_browser: $('#showBrowser').checked,
    browser_profile: $('#browserProfile').classList.contains('hidden') ? '' : $('#browserProfile').value,
    aspect: $('#aspect').value,
    preset: $('#preset').value,
    seconds: parseFloat($('#seconds').value) || 8,
    scenes: parseInt($('#scenes').value, 10) || 1,
    voice: $('#voice').value,
    rate: $('#rate').value,
    subtitles: $('#subtitles').checked,
    bgm: $('#bgm').checked,
    product_style: $('#productStyle').value,
    brand: $('#brand').value,
    comment_name: $('#commentName').value,
    comment_text: $('#commentText').value,
    price: $('#price').value,
    old_price: $('#oldPrice').value,
    perk: $('#perk').value,
    contact: $('#contact').value,
    keep_audio: $('#keepAudio').checked,
    ai_values: state.form.ai_values || {},
    // biến + ảnh của template AI đang chọn (backend đọc 2 khoá này)
    variables: currentAiTemplate() ? { ...aiValues(currentAiTemplate()).variables } : {},
    attachments: currentAiTemplate() ? { ...aiValues(currentAiTemplate()).attachments } : {},
    // mong muốn của người dùng/template; backend tự chuẩn hoá theo engine (renderAiEngine hiện giá trị đã chuẩn hoá)
    ai_duration: state.form.ai_duration,
    ai_resolution: state.form.ai_resolution,
    gemini_mode: $('#geminiMode').value,
  };
}

let persistTimer = null;
function persistForm() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => api('save_settings', { last_form: state.form }), 600);
}

function onFormChange(e) {
  if (e && (e.target.id === 'preset' || e.target.id === 'seconds')) applyPreset();
  state.form = readForm();
  updateProviderUI();
  fillProfileSelects();
  updateAssetsUI();
  updateAiUI();
  updateEstimate();
  persistForm();
}

/* ---------- template video AI (Grok Imagine) ---------- */
function findTemplate(id) {
  return allTemplates().find(t => t.id === id) || null;
}

function currentAiTemplate() {
  const t = findTemplate(state.form.template);
  return t && t.kind === 'ai_video' && state.form.genre !== PRODUCT_GENRE ? t : null;
}

// Mỗi template AI giữ biến/ảnh riêng (các template có thể trùng tên khoá như TenSanPham, product)
function aiValues(t) {
  const all = state.form.ai_values || (state.form.ai_values = {});
  return all[t.id] || (all[t.id] = { variables: {}, attachments: {} });
}


function updateAiUI() {
  const t = currentAiTemplate();
  $('#aiVideoCard').classList.toggle('hidden', !t);
  if (!t) return;
  $('#aiTplName').textContent = t.name;
  renderAiEngine(t);
  const box = $('#aiVars');
  if (box.dataset.tpl !== t.id) {
    box.dataset.tpl = t.id;
    const vars = aiValues(t).variables;
    t.variables.forEach(v => { if (vars[v.key] == null && v.default) vars[v.key] = v.default; });
    box.innerHTML = t.variables.map(v => `
      <label class="field"><span>${esc(v.label)} <code>{${esc(v.key)}}</code>${v.required === false ? '' : ' *'}</span>
        <input data-var="${esc(v.key)}" placeholder="${esc(v.placeholder || '')}" value="${esc(vars[v.key] || '')}"></label>`).join('');
    $$('input[data-var]', box).forEach(input => input.addEventListener('input', () => {
      aiValues(t).variables[input.dataset.var] = input.value;
      renderAiPrompt();
      persistForm();
    }));
  }
  renderAiAttachments(t);
  renderAiPrompt();
}

// Engine tạo video = Provider AI đang chọn (grok_browser / gemini_browser / gemini_api)
function aiEngine() {
  const provider = $('#provider').value;
  return state.boot.video_engines[provider] ? provider : null;
}

const secondsOf = v => parseInt(v, 10) || 0;
const geminiRegular = () => aiEngine() === 'gemini_browser' && $('#geminiMode').value === 'regular';

function renderAiEngine(t) {
  const engine = aiEngine();
  const spec = engine && state.boot.video_engines[engine];
  const appRender = geminiRegular();  // Gemini Browser · Video thông thường: app tự dựng
  const line = $('#aiEngine');
  line.classList.toggle('bad', !spec);
  line.innerHTML = !spec
    ? '<b>Chưa có engine tạo video</b><small>Đổi Provider AI sang Grok Browser, Gemini Browser, Dola Browser hoặc Gemini API.</small>'
    : appRender
      ? '<b>Gemini · video thông thường</b><small>Gemini viết kịch bản theo prompt template; app tự dựng hình, giọng đọc, nhạc, phụ đề. Thời lượng & tỉ lệ theo mục Khung hình & thời lượng. Ảnh sản phẩm (nếu chọn) được đưa vào video.</small>'
      : `Engine: <b>${esc(spec.name)}</b><small>${esc(spec.note)}</small>`;
  $('#geminiModeBox').classList.toggle('hidden', !(spec && spec.regular_mode));
  $('#aiOptions').classList.toggle('hidden', !spec || appRender);
  if (!spec || appRender) return;
  // thời lượng: giá trị lớn nhất không vượt quá mong muốn (của người dùng hoặc template)
  const wantD = state.form.ai_duration || t.options.duration;
  const fit = spec.durations.filter(d => secondsOf(d) <= secondsOf(wantD));
  $('#aiDuration').innerHTML = spec.durations.map(d => `<option>${d}</option>`).join('');
  $('#aiDuration').value = fit.length ? fit[fit.length - 1] : spec.durations[0];
  const wantR = state.form.ai_resolution || t.options.resolution;
  $('#aiResolution').innerHTML = spec.resolutions.map(r => `<option>${r}</option>`).join('');
  $('#aiResolution').value = spec.resolutions.includes(wantR) ? wantR
    : (spec.resolutions.includes('720p') ? '720p' : spec.resolutions[spec.resolutions.length - 1]);
}

function renderAiAttachments(t) {
  const specs = t.attachments || [];
  const files = aiValues(t).attachments;
  $('#aiAttachBox').classList.toggle('hidden', !specs.length);
  $('#aiAttach').innerHTML = specs.map(a => {
    const own = files[a.key];
    const preview = !own && a.default
      ? `<img class="att-thumb" src="/tpl/${encodeURIComponent(t.id)}/asset/${encodeURIComponent(a.default)}" alt="">` : '';
    const note = own ? baseName(own) : a.default ? 'Ảnh mẫu của template (bấm Chọn… để thay)' : (a.hint || 'Chưa chọn');
    return `
    <div class="asset-row">
      ${preview}
      <div class="asset-info"><b>${esc(a.label)}</b>
        <small class="${own || a.default ? 'set' : ''}" title="${esc(own || '')}">${esc(note)}</small></div>
      <div class="row">
        <button class="btn ghost" type="button" data-pick="${esc(a.key)}" data-video="${a.video ? '1' : ''}">Chọn…</button>
        <button class="btn ghost sq" type="button" data-clear="${esc(a.key)}" title="${a.default ? 'Về ảnh mẫu' : 'Bỏ chọn'}">✕</button>
      </div>
    </div>`;
  }).join('');
}

// Giống app/pipeline/ai_video.reference_sentence — câu mô tả vai trò ảnh theo thứ tự gửi lên Grok
function referenceSentence(t) {
  const files = aiValues(t).attachments;
  const specs = (t.attachments || []).filter(a => files[a.key] || a.default);
  if (!specs.length) return '';
  return ' Reference images are attached in this order — '
    + specs.map((s, i) => `image ${i + 1} = ${s.role}: ${s.prompt}`).join('; ') + '.';
}

function renderAiPrompt() {
  const t = currentAiTemplate();
  if (!t) return;
  // Giống ai_video.fill_prompt: biến tuỳ chọn để trống → rỗng, bỏ dòng chỉ còn “”; biến bắt buộc trống → giữ {Bien}
  const own = aiValues(t).variables;
  const filled = t.prompt.replace(/\{(\w+)\}/g, (m, key) => {
    const spec = t.variables.find(v => v.key === key);
    if (!spec) return m;
    const value = (own[key] || '').trim();
    return value || (spec.required === false ? '' : m);
  });
  $('#aiPrompt').value = filled.split('\n').filter(l => !/^\s*[“"'‘]\s*[”"'’]\s*$/.test(l)).join('\n') + referenceSentence(t);
}

async function onAiAttachClick(e) {
  const t = currentAiTemplate();
  const pick = e.target.closest('[data-pick]');
  const clear = e.target.closest('[data-clear]');
  if (!t || !(pick || clear)) return;
  if (pick) {
    const files = await api('pick_files', pick.dataset.video ? 'image_or_video' : 'image');
    if (!files.length) return;
    aiValues(t).attachments[pick.dataset.pick] = files[0];
  } else {
    delete aiValues(t).attachments[clear.dataset.clear];
  }
  renderAiAttachments(t);
  renderAiPrompt();
  persistForm();
}

function applyPreset() {
  const preset = $('#preset').value;
  if (preset === 'custom') return;
  const seconds = parseFloat($('#seconds').value) || 8;
  $('#scenes').value = Math.max(1, Math.min(20, Math.round(parseInt(preset, 10) / seconds)));
}

function updateProviderUI() {
  const p = $('#provider').value;
  const isBrowser = p.endsWith('_browser');
  $('#browserBox').classList.toggle('hidden', !isBrowser);
  if (isBrowser) {
    $('#browserLabel').textContent = { grok_browser: 'Grok Browser', dola_browser: 'Dola Browser' }[p] || 'Gemini Browser';
  }
  $('#modelBox').classList.toggle('hidden', p !== 'gemini_api');
  $('#keyBox').classList.toggle('hidden', p !== 'gemini_api');
}

function updateEstimate() {
  const f = state.form;
  if (currentAiTemplate() && !geminiRegular()) {
    $('#estimate').textContent = `1 video AI · ~${$('#aiDuration').value || f.ai_duration || '15s'}`;
    return;
  }
  $('#estimate').textContent = `${f.scenes} khung · ~${Math.round(f.scenes * f.seconds)}s`;
  const s = f.seconds;
  $('#pacingHint').textContent = s < 6 ? 'Nhịp nhanh. Ít lời, chuyển cảnh dồn dập.'
    : s <= 9 ? 'Mức trung bình. Cảnh nhiều lời sẽ dài hơn, ít lời ngắn hơn.'
    : 'Nhịp chậm. Hợp kể chuyện, giải thích.';
}

function allTemplates() {
  return state.boot.categories.flatMap(c => c.templates);
}

function templateLabel(choice) {
  if (choice === 'ai') return 'AI chọn template';
  if (choice === 'random') return 'Ngẫu nhiên toàn bộ';
  if (choice.startsWith('category:')) {
    const cat = state.boot.categories.find(c => c.id === choice.slice(9));
    return `Ngẫu nhiên · ${cat ? cat.name : ''}`;
  }
  const t = allTemplates().find(x => x.id === choice);
  return t ? t.name : 'AI chọn template';
}

function updateLabels() {
  const g = state.boot.genres.find(x => x.id === state.form.genre) || state.boot.genres[0];
  $('#genreLabel').textContent = g.name;
  const productMode = state.form.genre === PRODUCT_GENRE;
  $('#templateLabel').textContent = productMode ? 'Theo layout mẫu' : templateLabel(state.form.template);
  $('#templatePicker').disabled = productMode;
  updateAssetsUI();
  updateAiUI();
}

function updateAssetsUI() {
  const f = state.form;
  $('#assetsCard').classList.toggle('hidden', f.genre !== PRODUCT_GENRE);
  const layout = $('#layoutName');
  layout.textContent = f.layout_file ? baseName(f.layout_file) : 'Chưa chọn — dùng layout showcase mặc định';
  layout.classList.toggle('set', !!f.layout_file);
  layout.title = f.layout_file || '';
  const style = f.product_style;
  const people = style === 'presenter' || style === 'reel';
  const hasVideo = (f.product_files || []).some(p => /\.(mp4|mov|webm|m4v)$/i.test(p));
  $('#productsLabel').textContent = people ? 'Video / ảnh người bán cầm sản phẩm' : 'Ảnh sản phẩm';
  $('#commentBox').classList.toggle('hidden', !people);
  $('#keepAudioBox').classList.toggle('hidden', !(people && hasVideo));
  $('#assetsHint').textContent = {
    reel: 'Video quay dọc (hoặc ảnh) người bán giới thiệu sản phẩm — mỗi khung lấy một đoạn tiếp theo. Giá, giá cũ, ưu đãi hiện ở khung cuối kèm lời mời bình luận “TƯ VẤN”. Nhập tên sản phẩm và công dụng vào ô Nội dung.',
    presenter: 'Ảnh/video dọc người mẫu cầm sản phẩm (mỗi khung một file, xoay vòng). Bình luận để trống thì không hiện bong bóng. Nhập tên, công dụng vào ô Nội dung.',
  }[style] || 'Layout là ảnh (PNG/JPG/WEBP) thì dùng làm nền và lấy tông màu; là file HTML thì dùng làm template. Ảnh sản phẩm (tối đa 10) lần lượt xuất hiện qua các khung. Nhập tên, giá, ưu đãi vào ô Nội dung.';
  const products = $('#productNames');
  const files = f.product_files || [];
  products.textContent = files.length ? `${files.length} file · ${files.map(baseName).join(', ')}` : 'Chưa chọn (bắt buộc)';
  products.classList.toggle('set', files.length > 0);
  products.title = files.join('\n');
}

async function pickAssets(kind) {
  const files = await api('pick_files', kind);
  if (!files.length) return;
  if (kind === 'layout') state.form.layout_file = files[0];
  else state.form.product_files = files.slice(0, 10);
  if (kind === 'products' && files.length > 10) toast('Chỉ lấy 10 ảnh đầu tiên', 'warn');
  updateAssetsUI();
  onFormChange();
}

/* ------------------------------------------------------------------ header & license */
function renderHeader() {
  const s = state.boot.settings;
  $('#outDirChip').textContent = `Video lưu tại: ${s.output_dir}`;
  $('#outDirChip').title = `${s.output_dir}\n(bấm để đổi thư mục)`;
  renderLicense(state.boot.license);
}

function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '' : `${d.getDate()}/${d.getMonth() + 1}/${d.getFullYear()}`;
}

function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())} ${fmtDate(iso)}`;
}

function renderLicense(lic) {
  state.boot.license = lic;
  const chip = $('#licenseChip');
  chip.classList.toggle('bad', !lic.active);
  if (lic.dev) chip.textContent = 'Chế độ phát triển';
  else if (!lic.active) chip.textContent = lic.message || 'Chưa kích hoạt';
  else chip.textContent = lic.days_left != null ? `Còn ${lic.days_left} ngày · ${fmtDate(lic.expires_at)}` : 'Đã kích hoạt';
  const user = lic.user || {};
  $('#userName').textContent = user.name || 'Đăng nhập ITNNV';
  const avatar = $('#userAvatar');
  if (user.avatar) avatar.innerHTML = `<img src="${esc(user.avatar)}" alt="">`;
  else avatar.textContent = (user.name || 'V').split(/\s+/).map(w => w[0]).slice(-2).join('').toUpperCase();
}

async function licenseLogin() {
  toast('Đang mở trình duyệt để đăng nhập ITNNV…');
  const res = await api('license_login');
  if (res.ok) { renderLicense(res.license); toast('Đăng nhập thành công', 'ok'); }
  else toast(res.error, 'error');
}

/* ------------------------------------------------------------------ backend events */
window.__onBackend = ({ event, data }) => {
  switch (event) {
    // ---- tạo video (nhiều tác vụ song song — mọi sự kiện kèm data.task)
    case 'tasks':
      state.vt.update(data.tasks);
      setRunning(state.vt.active().length > 0);
      break;
    case 'log': state.vt.onLog(data); break;
    case 'progress': state.vt.onProgress(data); break;
    case 'done': {
      const v = data.result || {};
      toast(`Đã xong video: ${v.title || ''}`, 'ok');
      const reopen = state.rerenderOf && state.rerenderOf.task === data.task ? state.rerenderOf : null;
      if (reopen) state.rerenderOf = null;
      refreshVideos().then(() => {
        if (reopen && state.detail && state.detail.id === reopen.id) openDetail(reopen.id, reopen.index);
      });
      break;
    }
    case 'error': toast(data.message, 'error'); break;
    // ---- tạo ảnh
    case 'image_tasks':
      state.it.update(data.tasks);
      setImageRunning(state.it.active().length > 0);
      break;
    case 'image_log': state.it.onLog(data); break;
    case 'image_progress': state.it.onProgress(data); break;
    case 'image_done':
      toast(`Đã tạo ${((data.result || {}).files || []).length} ảnh`, 'ok');
      refreshImages();
      break;
    case 'image_error': toast(data.message, 'error'); break;
    case 'profiles': renderProfiles(data.profiles); break;
    case 'license': renderLicense(data); break;
    case 'toast': toast(data.message, data.level); break;
  }
};

function setRunning(running) {
  state.running = running;
  const n = state.vt ? state.vt.active().length : 0;
  $('#createBtn').textContent = n ? `Thêm video → (${n} đang xử lý)` : 'Tạo video →';
  $('#sbRunning').classList.toggle('hidden', !running);
}

function setStatusPill(text, level = '') {
  const pill = $('#statusPill');
  pill.textContent = text;
  pill.className = `status-pill mono ${level}`;
}

function buildStepper() {
  $('#stepper').innerHTML = STAGES.map(([id, label]) => `<div class="step" data-stage="${id}"><i></i><span>${label}</span></div>`).join('');
}

function setProgress({ pct, status, stage }) {
  $('#progressFill').style.width = `${pct}%`;
  $('#progressPct').textContent = `${Math.round(pct)}%`;
  if (status) $('#statusBox').textContent = status;
  const current = STAGES.findIndex(([id]) => id === stage);
  $$('#stepper .step').forEach((el, i) => {
    el.classList.toggle('done', i < current || (pct >= 100 && i < STAGES.length - 1));
    el.classList.toggle('active', i === current);
  });
}


/* ------------------------------------------------------------------ tabs & results */
function switchTab(tab) {
  $$('.tab[data-tab]').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  showView(tab === 'progress' ? 'progress' : 'results');
}

function showView(view) {
  ['progress', 'results', 'detail'].forEach(v => $(`#view-${v}`).classList.toggle('hidden', v !== view));
  if (view !== 'detail') { state.detail = null; state.scene = null; $('#stage').innerHTML = ''; }
  if (view !== 'results') $('#player').pause();
}

async function refreshVideos() {
  state.videos = await api('list_videos');
  $('#videoCount').textContent = state.videos.length;
  $('#sbVideoCount').textContent = state.videos.length;
  $('#resultsCount').textContent = `${state.videos.length} video`;
  renderVideoList();
  const sel = state.videos.find(v => v.id === state.selected) || state.videos[0];
  if (sel) selectVideo(sel.id, false);
}

const aspectClass = a => (a === '16:9' ? 'landscape' : a === '1:1' || a === '4:5' ? 'square' : '');

function renderVideoList() {
  const list = $('#videoList');
  if (!state.videos.length) {
    list.innerHTML = '<div class="empty">Chưa có video nào. Nhập nội dung rồi bấm “Tạo video”.</div>';
    return;
  }
  list.innerHTML = state.videos.map(v => `
    <div class="vitem ${state.selected === v.id ? 'active' : ''}" data-id="${esc(v.id)}">
      <div class="vthumb ${aspectClass(v.aspect)}">${v.thumb_url ? `<img src="${esc(v.thumb_url)}" alt="">` : ''}</div>
      <div class="vinfo">
        <b title="${esc(v.title)}">${esc(v.title)}</b>
        <small class="mono">${esc(v.aspect)} · ${v.duration}s · ${v.scene_count} khung</small>
        <small class="mono tpl">◉ ${esc(v.template_name)}</small>
        <small class="mono">🔊 voice${v.bgm ? ' · ✦ SFX' : ''}${v.subtitles ? ' · CC' : ''} · ${fmtTime(v.created_at)}</small>
        ${v.has_final ? '' : '<small class="warn">Chưa xuất xong</small>'}
      </div>
      <div class="vactions">
        <button class="btn ghost sm" data-act="detail">Chi tiết</button>
        <div class="row">
          <button class="btn ghost sq" data-act="open" title="Mở file">↗</button>
          <button class="btn danger sq" data-act="delete" title="Xoá">🗑</button>
        </div>
      </div>
    </div>`).join('');
}

function selectVideo(id, autoplay = true) {
  state.selected = id;
  $$('.vitem').forEach(el => el.classList.toggle('active', el.dataset.id === id));
  const v = state.videos.find(x => x.id === id);
  const player = $('#player');
  const has = v && v.final_url;
  player.classList.toggle('hidden', !has);
  $('#playerEmpty').classList.toggle('hidden', !!has);
  if (has && player.getAttribute('src') !== v.final_url) {
    player.src = v.final_url;
    if (autoplay) player.play().catch(() => {});
  }
}

async function onVideoListClick(e) {
  const item = e.target.closest('.vitem');
  if (!item) return;
  const id = item.dataset.id;
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'detail') return openDetail(id);
  if (act === 'open') { const r = await api('open_video', id); if (!r.ok) toast(r.error, 'error'); return; }
  if (act === 'delete') {
    if (!confirm('Xoá video này khỏi thư viện (xoá cả file trên ổ đĩa)?')) return;
    const r = await api('delete_video', id);
    if (!r.ok) return toast(r.error, 'error');
    if (state.selected === id) { state.selected = null; $('#player').removeAttribute('src'); }
    return refreshVideos();
  }
  selectVideo(id);
}

/* ------------------------------------------------------------------ detail */
async function openDetail(id, sceneIndex) {
  const res = await api('get_video', id);
  if (!res.ok) return toast(res.error, 'error');
  showView('detail');
  $$('.tab[data-tab]').forEach(t => t.classList.toggle('active', t.dataset.tab === 'results'));
  const v = state.detail = res.video;
  $('#detailTitle').textContent = v.title;
  $('#detailMeta').textContent = `${v.aspect} · ${v.duration}s · ${v.scene_count} cảnh · voice · ${v.template_name}`;
  $('#htmlEditor').value = '';
  const scene = sceneIndex && v.scenes.find(s => s.index === sceneIndex);
  if (scene) selectScene(scene); else showFinal();
}

function renderFilmstrip() {
  const v = state.detail;
  const active = state.scene ? state.scene.index : 0;
  const film = (index, thumb, label) => `
    <button class="film ${active === index ? 'active' : ''}" data-index="${index}">
      <div class="fthumb">${thumb ? `<img src="${esc(thumb)}" alt="">` : ''}</div><span>${label}</span>
    </button>`;
  $('#filmstrip').innerHTML = film(0, v.thumb_url, 'FINAL')
    + v.scenes.map(s => film(s.index, s.thumb_url, `${pad2(s.index)} scene_${s.index}`)).join('');
}

function showFinal() {
  state.scene = null;
  const v = state.detail;
  $('#stage').innerHTML = v.final_url
    ? `<video src="${esc(v.final_url)}" controls autoplay></video>`
    : '<div class="empty">Video chưa xuất xong</div>';
  $('#sceneLabel').textContent = 'FINAL — chọn một cảnh để sửa HTML';
  renderFilmstrip();
}

function selectScene(scene) {
  state.scene = scene;
  $('#sceneLabel').textContent = `${pad2(scene.index)} · scene_${scene.index} · ${scene.duration}s`;
  $('#htmlEditor').value = '';
  if (scene.html_url) showSceneFrame({ src: scene.html_url });
  else $('#stage').innerHTML = scene.video_url  // video AI: không có HTML cảnh
    ? `<video src="${esc(scene.video_url)}" controls autoplay></video>` : '<div class="empty">Cảnh này không có HTML</div>';
  renderFilmstrip();
}

function showSceneFrame({ src, srcdoc }) {
  const [w, h] = FRAME_SIZE[state.detail.aspect] || FRAME_SIZE['9:16'];
  const stage = $('#stage');
  stage.innerHTML = `<div class="frame-wrap"><iframe sandbox="allow-scripts"></iframe>
    <button class="replay" title="Phát lại">↻</button></div>`;
  const iframe = $('iframe', stage);
  iframe.style.width = `${w}px`;
  iframe.style.height = `${h}px`;
  if (srcdoc != null) iframe.srcdoc = srcdoc; else iframe.src = src;
  $('.replay', stage).onclick = () => showSceneFrame({ src, srcdoc });
  fitFrame();
}

function fitFrame() {
  const stage = $('#stage');
  const wrap = $('.frame-wrap', stage);
  if (!wrap) return;
  const iframe = $('iframe', wrap);
  const w = parseFloat(iframe.style.width), h = parseFloat(iframe.style.height);
  const scale = Math.min(stage.clientWidth / w, stage.clientHeight / h);
  wrap.style.width = `${w * scale}px`;
  wrap.style.height = `${h * scale}px`;
  iframe.style.transform = `scale(${scale})`;
}

function requireScene() {
  if (!state.scene) { toast('Chọn một cảnh trong dải bên dưới trước', 'warn'); return false; }
  return true;
}

async function onViewHtml() {
  if (!requireScene()) return;
  if (!state.scene.html_url) return toast('Video AI không có HTML cảnh', 'warn');
  const r = await api('get_scene_html', state.detail.id, state.scene.index);
  if (r.ok) $('#htmlEditor').value = r.html; else toast(r.error, 'error');
}

function onApplyHtml() {
  if (!requireScene()) return;
  const html = $('#htmlEditor').value;
  if (!html.trim()) return toast('Bấm “Xem HTML” để tải HTML cảnh trước', 'warn');
  // srcdoc không có URL gốc → thêm <base> để ảnh tương đối (../../assets/...) vẫn tải được
  const base = `<base href="${location.origin}${state.scene.html_url.split('?')[0]}">`;
  showSceneFrame({ srcdoc: /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, m => m + base) : base + html });
}

async function onSaveHtml() {
  if (!requireScene()) return;
  const html = $('#htmlEditor').value;
  if (!html.trim()) return toast('Không có HTML để lưu', 'warn');
  const r = await api('save_scene_html', state.detail.id, state.scene.index, html);
  if (!r.ok) return toast(r.error, 'error');
  toast('Đã lưu HTML cảnh — bấm “Render lại” để xuất MP4 mới', 'ok');
  showSceneFrame({ src: `${state.scene.html_url.split('?')[0]}?v=${Date.now()}` });
}

async function onRerender() {
  if (!requireScene()) return;
  const r = await api('rerender_scene', state.detail.id, state.scene.index);
  if (!r.ok) return toast(r.error, 'error');
  state.rerenderOf = { id: state.detail.id, index: state.scene.index, task: r.task };
  toast(`Đang render lại cảnh ${state.scene.index} — xem ở tab Tiến trình`);
}

/* ------------------------------------------------------------------ modals */
function openModal(eyebrow, title, html, narrow = false) {
  $('#modalEyebrow').textContent = eyebrow;
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = html;
  $('#modalCard').classList.toggle('narrow', narrow);
  $('#modal').classList.remove('hidden');
}

function closeModal() {
  $('#modal').classList.add('hidden');
  $('#modalBody').innerHTML = '';
}

const mrow = (key, icon, title, desc, count, active) => `
  <button class="mrow ${active ? 'active' : ''}" data-key="${esc(key)}">
    <span class="micon">${icon}</span>
    <span class="mtext"><b>${esc(title)}</b><small>${esc(desc)}</small></span>
    ${count != null ? `<span class="mcount">${count}</span><span class="chev">›</span>` : ''}
  </button>`;

function openGenreModal() {
  const genres = state.boot.genres;
  openModal(`${genres.length} THỂ LOẠI`, 'Chọn thể loại',
    `<div class="mrows">${genres.map(g => mrow(g.id, '◫', g.name, g.desc, null, g.id === state.form.genre)).join('')}</div>`, true);
  $('#modalBody').onclick = e => {
    const row = e.target.closest('.mrow');
    if (!row) return;
    state.form.genre = row.dataset.key;
    updateLabels();
    onFormChange();
    closeModal();
  };
}

function setTemplate(choice) {
  state.form.template = choice;
  const t = findTemplate(choice);
  if (t && t.kind === 'ai_video') {  // dùng tuỳ chọn mặc định của template (renderAiEngine chỉnh theo engine)
    state.form.ai_duration = t.options.duration || '';
    state.form.ai_resolution = t.options.resolution || '';
  }
  updateLabels();
  onFormChange();
  closeModal();
}

/* ---------- bộ chọn template dạng thẻ ---------- */
const filterChip = (key, label, count) => `<button class="chip-f" data-filter="${esc(key)}">${esc(label)}<span>${count}</span></button>`;

function specialCard(choice, icon, title, desc, active) {
  return `<button class="tpl-card ${active ? 'active' : ''}" data-choice="${esc(choice)}">
    <div class="tpl-thumb rand">${icon}</div>
    <div class="meta"><div class="badges"><span class="badge">Tự động</span></div>
      <b>${esc(title)}</b><small>${esc(desc)}</small><span class="use">${active ? '✓ Đang dùng' : 'Chọn →'}</span></div>
  </button>`;
}

function templateCard(t, active) {
  const cat = state.boot.categories.find(c => c.id === t.category);
  const ai = t.kind === 'ai_video';
  const opts = t.options || {};
  const thumb = t.has_thumb
    ? `<img src="/tpl/${encodeURIComponent(t.id)}/thumb" alt="">`
    : ai
      ? `<div class="poster"><span class="poster-icon">🎬</span><b>${esc(t.name)}</b>
           <small>Grok / Gemini Veo · ${esc(opts.aspect || '')} · ${esc(opts.duration || '')}</small></div>`
      : `<iframe loading="lazy" src="/tpl/${encodeURIComponent(t.id)}/preview?aspect=9:16" tabindex="-1"></iframe>`;
  const attach = ai && (t.attachments || []).length
    ? `<code>📎 ${t.attachments.length} ảnh tham chiếu</code>` : '';
  const vars = ai && (t.variables.length || attach)
    ? `<div class="vars">${t.variables.map(v => `<code>{${esc(v.key)}}</code>`).join(' ')} ${attach}</div>` : '';
  return `<button class="tpl-card ${active ? 'active' : ''}" data-choice="${esc(t.id)}">
    <div class="tpl-thumb">${thumb}</div>
    <div class="meta">
      <div class="badges"><span class="badge ${ai ? 'ai' : 'html'}">${ai ? 'Video AI · Grok / Gemini' : 'HTML động'}</span>
        ${cat ? `<span class="badge">${esc(cat.name)}</span>` : ''}</div>
      <b>${esc(t.name)}</b><small>${esc(t.description)}</small>${vars}
      <span class="use">${active ? '✓ Đang dùng' : 'Dùng template →'}</span>
    </div>
  </button>`;
}

function openTemplateModal() {
  const cats = state.boot.categories.filter(c => c.templates.length);
  const current = findTemplate(state.form.template);
  openModal(`${allTemplates().length} TEMPLATE · ${cats.length} NHÓM`, 'Chọn Template', '');
  mountTemplateBrowser($('#modalBody'), setTemplate, current && current.kind === 'ai_video' ? 'ai_video' : 'all');
}

// Bộ lọc nhóm + lưới thẻ template — dùng chung cho cửa sổ chọn template và trang Template ở sidebar
function mountTemplateBrowser(root, onChoose, filter = 'all') {
  const cats = state.boot.categories.filter(c => c.templates.length);
  const templates = allTemplates();
  const aiCount = templates.filter(t => t.kind === 'ai_video').length;
  root.innerHTML = `
    <div class="chips tpl-chips">
      ${filterChip('all', 'Tất cả', templates.length)}
      ${aiCount ? filterChip('ai_video', '🎬 Video AI (Grok / Gemini)', aiCount) : ''}
      ${cats.map(c => filterChip(c.id, `${c.icon} ${c.name}`, c.templates.length)).join('')}
    </div>
    <div class="tpl-grid"></div>`;
  renderTemplateGrid(root, filter);
  root.onclick = e => {
    const chip = e.target.closest('.chip-f');
    if (chip) return renderTemplateGrid(root, chip.dataset.filter);
    const card = e.target.closest('.tpl-card');
    if (card) onChoose(card.dataset.choice);
  };
}

function renderTemplateGrid(root, filter) {
  $$('.tpl-chips .chip-f', root).forEach(c => c.classList.toggle('active', c.dataset.filter === filter));
  const sel = state.form.template;
  let items = allTemplates();
  const special = [];
  if (filter === 'all') {
    special.push(specialCard('ai', '✦', 'AI chọn template', 'AI đọc nội dung và chọn template HTML phù hợp nhất', sel === 'ai'));
    special.push(specialCard('random', '⚡', 'Ngẫu nhiên toàn bộ', 'Bốc bất kỳ một template HTML', sel === 'random'));
  } else if (filter === 'ai_video') {
    items = items.filter(t => t.kind === 'ai_video');
  } else {
    items = items.filter(t => t.category === filter);
    const htmlCount = items.filter(t => t.kind === 'html').length;
    if (htmlCount > 1) {
      special.push(specialCard(`category:${filter}`, '⚡', 'Ngẫu nhiên trong nhóm',
        `Bốc 1 trong ${htmlCount} template HTML`, sel === `category:${filter}`));
    }
  }
  $('.tpl-grid', root).innerHTML = special.join('') + items.map(t => templateCard(t, sel === t.id)).join('');
  $$('.tpl-grid .tpl-thumb iframe', root).forEach(fr => {
    fr.style.transform = `scale(${fr.parentElement.clientWidth / 540})`;
  });
}

function openSettings() {
  const s = state.boot.settings;
  const lic = state.boot.license;
  const opt = (list, cur) => list.map(([v, l]) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${l}</option>`).join('');
  openModal('CÀI ĐẶT', 'Cài đặt', `
    <div class="form">
      <div class="sec">LƯU TRỮ</div>
      <div class="field"><span>Thư mục lưu video</span>
        <div class="inline"><input id="setOut" value="${esc(s.output_dir)}" readonly><button class="btn ghost" id="setOutPick">Chọn…</button></div></div>
      <label class="check"><input type="checkbox" id="setCleanup" ${s.cleanup_temp ? 'checked' : ''}> Dọn file tạm sau khi render</label>
      <div class="sec">AI</div>
      <div class="grid2">
        <label class="field"><span>Trình duyệt cho Gemini/Grok/Dola Browser</span>
          <select id="setChannel">${opt([['chrome', 'Google Chrome'], ['msedge', 'Microsoft Edge'], ['chromium', 'Chromium (Playwright)']], s.browser_channel)}</select></label>
        <label class="field"><span>Gemini model (API)</span><input id="setModel" value="${esc(s.gemini_model)}"></label>
      </div>
      <label class="field"><span>Veo model (tạo video AI bằng Gemini API)</span><input id="setVeoModel" value="${esc(s.veo_model || '')}" placeholder="veo-3.1-generate-preview"></label>
      <div class="sec">TẠO HÌNH ẢNH</div>
      <label class="field"><span>OpenAI API key (model chính của Tạo hình ảnh)</span><input id="setOpenAIKey" type="password" value="${esc(s.openai_api_key || '')}" placeholder="sk-…"></label>
      <div class="grid2">
        <label class="field"><span>OpenAI image model</span><input id="setOpenAIModel" value="${esc(s.openai_image_model || '')}" placeholder="gpt-image-1"></label>
        <label class="field"><span>Gemini image model (API)</span><input id="setGeminiImgModel" value="${esc(s.gemini_image_model || '')}" placeholder="gemini-2.5-flash-image"></label>
      </div>
      <label class="field"><span>Gemini API key</span><input id="setKey" type="password" value="${esc(s.gemini_api_key)}"></label>
      <div class="sec">VIDEO &amp; ÂM THANH</div>
      <div class="grid2">
        <label class="field"><span>FPS</span><select id="setFps">${opt([[24, '24 fps'], [30, '30 fps'], [60, '60 fps']], s.fps)}</select></label>
        <label class="field"><span>Số video tạo song song</span><select id="setParVideo">${opt([1, 2, 3, 4, 5, 6].map(n => [n, `${n} luồng`]), s.max_parallel_video || 2)}</select></label>
        <label class="field"><span>Số tác vụ ảnh song song</span><select id="setParImage">${opt([1, 2, 3, 4, 5, 6].map(n => [n, `${n} luồng`]), s.max_parallel_image || 2)}</select></label>
        <label class="field"><span>Âm lượng nhạc nền (0–1)</span><input id="setBgmVol" type="number" min="0" max="1" step="0.01" value="${s.bgm_volume}"></label>
      </div>
      <div class="field"><span>Thư mục nhạc nền (trống = nhạc nền tự tổng hợp)</span>
        <div class="inline"><input id="setMusic" value="${esc(s.music_dir)}" readonly><button class="btn ghost" id="setMusicPick">Chọn…</button><button class="btn ghost" id="setMusicClear">Xoá</button></div></div>
      <div class="sec">LICENSE ITNNV</div>
      <label class="field"><span>License server (trống = chế độ phát triển)</span><input id="setServer" value="${esc(s.license_server)}" placeholder="https://…"></label>
      <div class="lic-row"><span>${esc(lic.dev ? 'Chế độ phát triển — bỏ qua license' : (lic.active ? `Đã kích hoạt · ${lic.user?.email || ''}` : lic.message))}</span>
        <div class="row"><button class="btn ghost" id="licLogin">Đăng nhập Google</button><button class="btn ghost" id="licLogout">Đăng xuất</button></div></div>
      <div class="modal-foot"><button class="btn primary" id="setSave">Lưu cài đặt</button></div>
    </div>`, true);
  $('#modalBody').onclick = null;
  $('#setOutPick').onclick = async () => {
    state.boot.settings = await api('pick_output_dir');
    $('#setOut').value = state.boot.settings.output_dir;
    renderHeader();
    refreshVideos();
  };
  $('#setMusicPick').onclick = async () => {
    state.boot.settings = await api('pick_music_dir');
    $('#setMusic').value = state.boot.settings.music_dir;
  };
  $('#setMusicClear').onclick = () => { $('#setMusic').value = ''; };
  $('#licLogin').onclick = async () => { await saveSettings(false); licenseLogin(); };
  $('#licLogout').onclick = async () => { const r = await api('license_logout'); renderLicense(r.license); };
  $('#setSave').onclick = () => saveSettings(true);
}

async function saveSettings(close) {
  const values = {
    cleanup_temp: $('#setCleanup').checked,
    browser_channel: $('#setChannel').value,
    gemini_model: $('#setModel').value.trim(),
    veo_model: $('#setVeoModel').value.trim() || 'veo-3.1-generate-preview',
    openai_api_key: $('#setOpenAIKey').value.trim(),
    openai_image_model: $('#setOpenAIModel').value.trim() || 'gpt-image-1',
    gemini_image_model: $('#setGeminiImgModel').value.trim() || 'gemini-2.5-flash-image',
    gemini_api_key: $('#setKey').value.trim(),
    fps: parseInt($('#setFps').value, 10),
    max_parallel_video: parseInt($('#setParVideo').value, 10),
    max_parallel_image: parseInt($('#setParImage').value, 10),
    bgm_volume: Math.max(0, Math.min(1, parseFloat($('#setBgmVol').value) || 0)),
    music_dir: $('#setMusic').value,
    license_server: $('#setServer').value.trim(),
  };
  state.boot.settings = await api('save_settings', values);
  $('#geminiModel').value = values.gemini_model;
  $('#geminiKey').value = values.gemini_api_key;
  const r = await api('license_refresh');
  renderLicense(r.license);
  renderHeader();
  if (close) { closeModal(); toast('Đã lưu cài đặt', 'ok'); }
}

/* ------------------------------------------------------------------ actions */
async function onCreate() {
  const form = readForm();
  const aiTemplate = currentAiTemplate();
  if (aiTemplate) {
    if (!aiEngine()) { toast('Template video AI cần Provider AI: Grok Browser, Gemini Browser, Dola Browser hoặc Gemini API', 'warn'); return; }
    const missing = aiTemplate.variables.filter(v => v.required !== false && !(form.variables[v.key] || '').trim());
    if (missing.length) { toast(`Hãy điền: ${missing.map(v => v.label).join(', ')}`, 'warn'); return; }
  } else {
    if (!form.topic.trim()) { toast('Hãy nhập nội dung video', 'warn'); $('#topic').focus(); return; }
    if (form.genre === PRODUCT_GENRE && !(form.product_files || []).length) { toast('Hãy chọn ít nhất 1 ảnh/video sản phẩm', 'warn'); return; }
  }
  if (form.provider === 'gemini_api' && !$('#geminiKey').value.trim()) { toast('Nhập Gemini API key trước', 'warn'); return; }
  const res = await api('start_job', form);
  if (!res.ok) return toast(res.error, 'error');
  if (state.view !== 'create') navigate('create');
  switchTab('progress');
  state.vt.select(res.task);
  const busy = state.vt.tasks.filter(x => x.status === 'running').length >= (state.boot.settings.max_parallel_video || 2);
  toast(busy ? 'Đã thêm vào hàng đợi — sẽ chạy khi có luồng trống' : 'Đã bắt đầu tác vụ video', 'ok');
}

let toastTimer = null;
function toast(message, level = '') {
  const el = $('#toast');
  el.textContent = message;
  el.className = `toast ${level}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), level === 'error' ? 6000 : 3500);
}

function bindEvents() {
  $$('.config-scroll input, .config-scroll select, .config-scroll textarea').forEach(el => {
    if (el.id === 'geminiModel' || el.id === 'geminiKey') return;
    if (el.id === 'aiDuration' || el.id === 'aiResolution') {  // chỉ đổi mong muốn khi người dùng tự chọn
      el.addEventListener('change', () => {
        state.form[el.id === 'aiDuration' ? 'ai_duration' : 'ai_resolution'] = el.value;
        onFormChange();
      });
      return;
    }
    el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', onFormChange);
  });
  $('#geminiModel').addEventListener('change', e => api('save_settings', { gemini_model: e.target.value.trim() }));
  $('#geminiKey').addEventListener('change', e => api('save_settings', { gemini_api_key: e.target.value.trim() }));
  $('#topic').addEventListener('keydown', e => { if (e.key === 'Enter' && e.ctrlKey) onCreate(); });

  $('#genrePicker').onclick = openGenreModal;
  $('#templatePicker').onclick = openTemplateModal;
  $('#geminiLoginBtn').onclick = () => browserLogin($('#provider').value, $('#browserProfile').value);
  $('#createBtn').onclick = onCreate;
  $('#aiAttach').addEventListener('click', onAiAttachClick);
  $('#copyPromptBtn').onclick = () => {
    $('#aiPrompt').select();
    document.execCommand('copy');
    toast('Đã sao chép prompt', 'ok');
  };
  $('#pickLayoutBtn').onclick = () => pickAssets('layout');
  $('#pickProductsBtn').onclick = () => pickAssets('products');
  $('#clearLayoutBtn').onclick = () => { state.form.layout_file = ''; updateAssetsUI(); onFormChange(); };
  $('#clearProductsBtn').onclick = () => { state.form.product_files = []; updateAssetsUI(); onFormChange(); };

  $('#settingsBtn').onclick = openSettings;
  $('#outDirChip').onclick = async () => {
    state.boot.settings = await api('pick_output_dir');
    renderHeader();
    refreshVideos();
  };
  $('#licenseChip').onclick = () => (state.boot.license.active ? openSettings() : licenseLogin());
  $('#userChip').onclick = () => (state.boot.license.dev || state.boot.license.active ? openSettings() : licenseLogin());

  $$('.tab[data-tab]').forEach(t => {
    t.onclick = () => {
      if (t.dataset.tab === 'progress' && state.view === 'library') return navigate('create');
      switchTab(t.dataset.tab);
    };
  });
  $('#autoScrollBtn').onclick = e => {
    state.autoScroll = !state.autoScroll;
    e.target.classList.toggle('on', state.autoScroll);
  };

  $('#videoList').addEventListener('click', onVideoListClick);
  $('#openFolderBtn').onclick = () => api('open_output_dir');
  $('#reloadBtn').onclick = refreshVideos;

  $('#backBtn').onclick = () => switchTab('results');
  $('#openFileBtn').onclick = () => state.detail && api('open_video', state.detail.id);
  $('#watchFinalBtn').onclick = () => state.detail && showFinal();
  $('#filmstrip').addEventListener('click', e => {
    const film = e.target.closest('.film');
    if (!film) return;
    const index = parseInt(film.dataset.index, 10);
    if (index === 0) showFinal(); else selectScene(state.detail.scenes.find(s => s.index === index));
  });
  $('#viewHtmlBtn').onclick = onViewHtml;
  $('#applyHtmlBtn').onclick = onApplyHtml;
  $('#saveHtmlBtn').onclick = onSaveHtml;
  $('#rerenderBtn').onclick = onRerender;
  new ResizeObserver(fitFrame).observe($('#stage'));

  $('#modalClose').onclick = closeModal;
  $('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
}
