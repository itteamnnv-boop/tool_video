/* Màn hình Workflow — 4 bước: 01 Thiết kế (kéo thả block, nối dây) · 02 Cấu hình AI · 03 Chạy tự động · 04 Tái sử dụng.
   Dùng chung helper của app.js: $, $$, api, esc, toast, openModal, closeModal, fmtTime. */
(() => {
  'use strict';

  const NODE_W = 236;
  const W = {
    meta: null, presets: [], list: [], running: [], wf: null, sel: null, view: { x: 40, y: 30, z: 1 },
    issues: [], run: null, runs: [], tab: 'progress', logs: [], taskId: '', saveTimer: null, validateTimer: null,
    saving: false, dirty: false, inited: false, flowOpen: new Set(),
  };
  const STATUS = { pending: 'Chờ', running: 'Đang chạy', done: 'Xong', error: 'Lỗi', skipped: 'Bỏ qua', queued: 'Đang chờ',
    cancelled: 'Đã dừng', waiting: 'Chờ duyệt', cached: 'Dùng lại' };
  const TYPE_LABEL = { text: 'Văn bản', images: 'Ảnh', video: 'Video', any: 'Bất kỳ', post: 'Bài viết' };
  let FB = null;  // {pages, accounts, accounts_error} cho ô chọn của block Facebook

  async function ensureFb(force = false) {
    if (FB && !force) return FB;
    const res = await api('wf_fb_options');
    FB = res.ok ? res : { pages: [], accounts: [], accounts_error: res.error };
    return FB;
  }
  let STUDIO = null;  // [{id, name, ...}] dự án Studio — block Video dài từ storyboard lấy cài đặt

  async function ensureStudio(force = false) {
    if (STUDIO && !force) return STUDIO;
    const res = await api('studio_list');
    STUDIO = res.ok ? res.projects.map(p => ({ id: p.id, name: p.name, scenes: (p.scenes || []).length, logo: !!p.logo_url })) : [];
    return STUDIO;
  }
  let TPL = null;  // {templates, categories} cho block Tạo video
  let tplLoading = null;

  async function ensureTpl(force = false) {
    if (TPL && !force) return TPL;
    if (!tplLoading || force) {
      tplLoading = api('wf_video_templates').then(res => {
        TPL = res.ok ? res : { templates: [], categories: [] };
        tplLoading = null;
        return TPL;
      });
    }
    return tplLoading;
  }
  const tplById = id => (TPL && id ? TPL.templates.find(t => t.id === id) : null);
  let LOCK = {};  // ô cấu hình bị template cố định (tỉ lệ khung, model) khi vẽ bảng bên phải
  const tplLock = cfg => {
    const t = tplById(cfg.template);
    if (!t) return {};
    return { ...(t.options.aspect ? { aspect: t.options.aspect } : {}), ...(t.video_engine ? { engine: t.video_engine } : {}) };
  };
  // Xem trước prompt template: điền biến (tô màu), bỏ dòng chứa biến tuỳ chọn để trống — giống lúc chạy
  function flowPreview(raw, vars) {
    return String(raw || '').split('\n')
      .filter(line => !Object.entries(vars).some(([k, v]) => !v && line.includes(`{${k}}`)))
      .map(line => esc(line).replace(/\{(\w+)\}/g, (all, k) => (k in vars ? `<mark>${esc(vars[k])}</mark>` : all))).join('\n');
  }
  const slotKind = a => (a.keep_video ? 'video' : a.video ? 'image_or_video' : 'image');
  const fileName = p => String(p || '').split(/[\\/]/).pop();
  // Một ô file của template: file đã chọn, hoặc ghi chú sẽ lấy từ dây nối / ảnh mẫu
  function slotHtml(a, value, wired, pickAttr, rmAttr) {
    const port = a.keep_video ? 'videos' : 'images';
    const fallback = wired.has(port) || (a.video && wired.has('videos'))
      ? `lấy từ dây nối vào cổng “${a.keep_video ? 'Video tham chiếu' : 'Ảnh tham chiếu'}”`
      : a.has_default ? 'dùng ảnh mẫu của template' : a.required ? '<span class="bad">bắt buộc — chưa có file</span>' : 'không bắt buộc';
    return `<div class="wf-slot ${value ? 'has' : ''}"><div class="wf-slot-head"><i>${a.keep_video ? '🎞' : a.video ? '🖼🎞' : '🖼'}</i>
        <b>${esc(a.label)}${a.required ? ' <b class="req">*</b>' : ''}</b></div>
      ${a.hint ? `<small class="muted">${esc(a.hint)}</small>` : ''}
      <div class="wf-files">${value ? `<span class="camp-chip">${esc(fileName(value))}<button ${rmAttr} type="button">✕</button></span>` : `<small class="muted">Trống → ${fallback}</small>`}
        <button class="btn ghost sm" ${pickAttr} data-kind="${slotKind(a)}" type="button">${value ? 'Đổi file…' : `+ Chọn ${a.keep_video ? 'video' : a.video ? 'ảnh/video' : 'ảnh'}…`}</button></div></div>`;
  }
  const pinThumb = url => String(url).replace(/\/(\d+x|originals)\//, '/236x/');
  const spec = type => W.meta.types[type];
  const nodeById = id => W.wf.nodes.find(n => n.id === id);
  // Block Đăng bài: loại đầu ra chọn được làm tài nguyên (giống workflow/nodes.py SOURCE_PORT)
  const SRC_TYPES = { text: 'caption', images: 'media', video: 'media' };
  const isFb = n => n.type === 'fb_post' || n.type === 'fb_schedule';
  function descendants(id) {  // block nằm sau id (theo dây thật) — không cho chọn để tránh vòng lặp
    const found = new Set(), stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      W.wf.edges.forEach(e => { if (e.from === cur && !found.has(e.to)) { found.add(e.to); stack.push(e.to); } });
    }
    return found;
  }
  const cfgOf = n => ({ ...Object.fromEntries(spec(n.type).fields.map(f => [f.key, f.default])), ...(n.config || {}) });

  // ================================================================ khởi tạo
  function show() {
    const want = W.wantId;
    W.wantId = null;
    W.showing = (async () => {
      if (!W.inited) await init();
      await refreshList();
      if (want && (!W.wf || W.wf.id !== want || W.dirty)) { if (W.dirty) await save(); await openWorkflow(want); }
      else if (!W.wf && W.list.length) await openWorkflow(W.list[0].id);
      else { renderAll(); if (W.wf) applyView(); }
    })();
    return W.showing;
  }

  async function init() {
    const res = await api('wf_meta');
    W.meta = res.meta;
    W.presets = res.presets;
    W.running = res.running;
    W.inited = true;
    renderPalette();
    bindTop();
    bindCanvas();
    document.addEventListener('keydown', onKey);
  }

  async function refreshList() {
    const res = await api('wf_list');
    W.list = res.workflows;
    W.running = res.running;
    $('#sbWfCount').textContent = W.list.length;
    $('#sbWfRunning').classList.toggle('hidden', !W.running.length);
    $('#wfSelect').innerHTML = (W.list.length ? '' : '<option value="">— Chưa có workflow —</option>')
      + W.list.map(w => `<option value="${esc(w.id)}" ${W.wf && W.wf.id === w.id ? 'selected' : ''}>${esc(w.name)} · ${w.nodes} block</option>`).join('');
  }

  async function openWorkflow(id) {
    const res = await api('wf_get', id);
    if (!res.ok) return toast(res.error, 'error');
    W.wf = res.workflow;
    W.issues = res.workflow.issues || [];
    W.sel = null;
    W.run = null;
    W.logs = [];
    W.dirty = false;
    const runs = await api('wf_runs', id);
    W.runs = runs.ok ? runs.runs : [];
    if (W.runs.length) await loadRun(W.runs[0].id, true);
    await refreshList();
    renderAll();
    fitView();
  }

  async function loadRun(runId, silent = false) {
    const res = await api('wf_run_get', W.wf.id, runId);
    if (!res.ok) { if (!silent) toast(res.error, 'error'); return; }
    W.run = res.run;
  }

  // ================================================================ lưu & kiểm tra (tự động)
  function changed({ validate = true } = {}) {
    W.dirty = true;
    $('#wfSaved').textContent = 'Chưa lưu…';
    $('#wfSaved').className = 'wf-saved dirty';
    clearTimeout(W.saveTimer);
    W.saveTimer = setTimeout(save, 900);
    if (validate) { clearTimeout(W.validateTimer); W.validateTimer = setTimeout(revalidate, 400); }
  }

  async function save() {
    if (!W.wf || W.saving) return false;
    W.saving = true;
    clearTimeout(W.saveTimer);
    const res = await api('wf_save', { id: W.wf.id, name: W.wf.name, desc: W.wf.desc, nodes: W.wf.nodes, edges: W.wf.edges });
    W.saving = false;
    if (!res.ok) { toast(res.error, 'error'); return false; }
    W.wf = { ...W.wf, id: res.workflow.id, updated_at: res.workflow.updated_at, last_run: res.workflow.last_run };
    W.issues = res.workflow.issues;
    W.dirty = false;
    $('#wfSaved').textContent = '✓ Đã lưu';
    $('#wfSaved').className = 'wf-saved';
    await refreshList();
    renderSteps();
    renderIssueMarks();
    return true;
  }

  async function revalidate() {
    if (!W.wf) return;
    const res = await api('wf_validate', { nodes: W.wf.nodes, edges: W.wf.edges });
    if (!res.ok) return;
    W.issues = res.issues;
    renderSteps();
    renderIssueMarks();
    if (!W.sel) renderInspector();
    else if (W.sel.type === 'node') {  // chỉ cập nhật phần lỗi của block đang chọn (không vẽ lại cả form đang nhập)
      const box = $('#wfInspector .wf-insp-issues');
      if (box) box.innerHTML = issuesHtml(W.issues.filter(i => i.node === W.sel.id));
    }
    if (W.tab === 'issues') renderTray();
  }

  const issuesHtml = list => list.map(i => `<div class="wf-issue ${i.level}">${i.level === 'error' ? '✕' : '!'} ${esc(i.message)}</div>`).join('');

  // ================================================================ thanh trên: 4 bước + thao tác
  function bindTop() {
    $('#wfSelect').onchange = async e => { if (W.dirty) await save(); if (e.target.value) openWorkflow(e.target.value); };
    $('#wfName').oninput = e => { if (W.wf) { W.wf.name = e.target.value; changed({ validate: false }); } };
    $('#wfNew').onclick = openNewDialog;
    $('#wfBack').onclick = async () => { if (W.dirty) await save(); navigate('wf-list'); };
    $('#wfDup').onclick = async () => {
      if (!W.wf) return;
      await save();
      const res = await api('wf_duplicate', W.wf.id);
      if (!res.ok) return toast(res.error, 'error');
      toast('Đã nhân bản workflow', 'ok');
      openWorkflow(res.workflow.id);
    };
    $('#wfDel').onclick = async () => {
      if (!W.wf) return;
      if (!confirm(`Xoá workflow “${W.wf.name}”?\n(Kết quả các lần chạy trước vẫn được giữ trong thư mục video.)`)) return;
      const res = await api('wf_delete', W.wf.id);
      if (!res.ok) return toast(res.error, 'error');
      W.wf = null;
      await refreshList();
      if (W.list.length) openWorkflow(W.list[0].id); else renderAll();
    };
    $('#wfRun').onclick = () => (isRunning() ? stopRun() : startRun());
    $('#wfSteps').onclick = e => {
      const step = e.target.closest('[data-step]')?.dataset.step;
      if (step === '1') { $('#wfPalette').classList.add('pulse'); setTimeout(() => $('#wfPalette').classList.remove('pulse'), 1200); }
      if (step === '2') {
        const bad = W.issues.find(i => i.level === 'error' && i.node);
        if (bad) select({ type: 'node', id: bad.node }); else { W.tab = 'issues'; renderTray(); }
      }
      if (step === '3') startRun();
      if (step === '4') { W.tab = 'history'; renderTray(); }
    };
  }

  const isRunning = () => !!(W.wf && W.running.includes(W.wf.id));

  function stepStates() {
    const wf = W.wf;
    const nodes = wf ? wf.nodes.length : 0;
    const edges = wf ? wf.edges.length : 0;
    const errors = W.issues.filter(i => i.level === 'error').length;
    const last = wf && wf.last_run;
    const running = isRunning();
    return [
      { n: '01', title: 'Thiết kế Workflow', sub: nodes ? `${nodes} block · ${edges} dây nối` : 'Kéo thả block, nối thành dây chuyền',
        state: nodes >= 2 && edges >= 1 ? 'done' : 'active' },
      { n: '02', title: 'Cấu hình AI', sub: !nodes ? 'Chọn model, viết prompt từng bước' : errors ? `${errors} chỗ cần cấu hình` : 'Đã cấu hình đủ',
        state: !nodes ? '' : errors ? 'warn' : 'done' },
      { n: '03', title: 'Chạy tự động', sub: running ? 'Đang chạy tuần tự…' : last ? `Lần gần nhất: ${STATUS[last.status] || last.status}` : 'Bấm ▶ Chạy',
        state: running ? 'running' : last ? (last.status === 'done' ? 'done' : 'warn') : '' },
      { n: '04', title: 'Tái sử dụng', sub: last && last.status === 'done' ? 'Đổi input → chạy lại' : 'Lưu 1 lần, chạy mãi mãi',
        state: last && last.status === 'done' ? 'done' : '' },
    ];
  }

  function renderSteps() {
    $('#wfSteps').innerHTML = stepStates().map((s, i) => `${i ? '<i class="wf-step-line"></i>' : ''}
      <button class="wf-step ${s.state}" data-step="${i + 1}" type="button" title="${esc(s.sub)}">
        <span class="wf-step-no">${s.state === 'done' ? '✓' : s.n}</span>
        <span class="wf-step-text"><b>${esc(s.title)}</b><small>${esc(s.sub)}</small></span></button>`).join('');
    const run = $('#wfRun');
    run.textContent = isRunning() ? '■ Dừng' : '▶ Chạy';
    run.classList.toggle('stop', isRunning());
    run.disabled = !W.wf;
    if (document.activeElement !== $('#wfName')) $('#wfName').value = W.wf ? W.wf.name : '';
    $('#wfName').disabled = !W.wf;
    $('#wfDup').disabled = $('#wfDel').disabled = !W.wf;
  }

  function openNewDialog() {
    openModal('WORKFLOW MỚI', 'Bắt đầu từ…', `<div class="mrows">
      <button class="mrow" data-preset="" type="button"><span class="micon">＋</span><span class="mtext"><b>Workflow trống</b><small>Tự kéo thả block từ đầu</small></span></button>
      ${W.presets.map(p => `<button class="mrow" data-preset="${esc(p.id)}" type="button"><span class="micon">⚡</span>
        <span class="mtext"><b>${esc(p.name)}</b><small>${esc(p.desc)} · ${p.nodes} block</small></span></button>`).join('')}</div>`, true);
    $('#modalBody').onclick = async e => {
      const row = e.target.closest('[data-preset]');
      if (!row) return;
      if (W.dirty) await save();
      const res = row.dataset.preset ? await api('wf_from_preset', row.dataset.preset)
        : await api('wf_save', { name: 'Workflow mới', nodes: [], edges: [] });
      if (!res.ok) return toast(res.error, 'error');
      closeModal();
      await openWorkflow(res.workflow.id);
      toast(row.dataset.preset ? 'Đã tạo workflow từ mẫu — kiểm tra cấu hình từng block rồi bấm Chạy' : 'Đã tạo workflow trống', 'ok');
    };
  }

  // ================================================================ 01 · bảng block (kéo vào canvas)
  function renderPalette() {
    const t = W.meta.types;
    $('#wfPalette').innerHTML = '<div class="wf-pal-head"><b>BLOCK</b><small>Kéo vào canvas hoặc bấm để thêm</small></div>'
      + W.meta.groups.map(([g, label]) => `<div class="wf-pal-group"><small>${esc(label)}</small>
        ${Object.entries(t).filter(([, s]) => s.group === g).map(([k, s]) => `
          <div class="wf-pal-item g-${g}" draggable="true" data-type="${k}" title="${esc(s.desc)}">
            <i>${esc(s.icon)}</i><span><b>${esc(s.name)}</b><small>${esc(s.desc)}</small></span></div>`).join('')}</div>`).join('');
    $('#wfPalette').addEventListener('dragstart', e => {
      const item = e.target.closest('[data-type]');
      if (item) e.dataTransfer.setData('text/wf-type', item.dataset.type);
    });
    $('#wfPalette').onclick = e => {
      const item = e.target.closest('[data-type]');
      if (!item || !W.wf) return;
      const r = $('#wfCanvas').getBoundingClientRect();
      const p = toWorld(r.left + r.width / 2, r.top + r.height / 3);
      addNode(item.dataset.type, p.x - NODE_W / 2 + (Math.random() * 60 - 30), p.y + (Math.random() * 60 - 30));
    };
  }

  function addNode(type, x, y, config) {
    if (!W.wf) return null;
    let i = W.wf.nodes.length + 1;
    while (nodeById(`n${i}`)) i += 1;
    const node = { id: `n${i}`, type, x: Math.round(x), y: Math.round(y),
      config: config ? JSON.parse(JSON.stringify(config)) : Object.fromEntries(spec(type).fields.map(f => [f.key, f.default])) };
    W.wf.nodes.push(node);
    renderCanvas();
    select({ type: 'node', id: node.id });
    changed();
    return node;
  }

  // ================================================================ canvas: vẽ block + dây
  const toWorld = (cx, cy) => {
    const r = $('#wfCanvas').getBoundingClientRect();
    return { x: (cx - r.left - W.view.x) / W.view.z, y: (cy - r.top - W.view.y) / W.view.z };
  };

  function applyView() {
    $('#wfWorld').style.transform = `translate(${W.view.x}px,${W.view.y}px) scale(${W.view.z})`;
    $('#wfZoomPct').textContent = `${Math.round(W.view.z * 100)}%`;
    $('#wfCanvas').style.backgroundPosition = `${W.view.x}px ${W.view.y}px`;
    $('#wfCanvas').style.backgroundSize = `${22 * W.view.z}px ${22 * W.view.z}px`;
  }

  function fitView() {
    const r = $('#wfCanvas').getBoundingClientRect();
    if (!W.wf || !W.wf.nodes.length || !r.width) { W.view = { x: 40, y: 30, z: 1 }; applyView(); return; }
    const xs = W.wf.nodes.map(n => n.x), ys = W.wf.nodes.map(n => n.y);
    const minX = Math.min(...xs) - 30, minY = Math.min(...ys) - 30;
    const maxX = Math.max(...xs) + NODE_W + 30, maxY = Math.max(...ys) + 240;
    const z = Math.max(0.3, Math.min(1.05, Math.min(r.width / (maxX - minX), r.height / (maxY - minY))));
    W.view = { z, x: (r.width - (maxX - minX) * z) / 2 - minX * z, y: (r.height - (maxY - minY) * z) / 2 - minY * z };
    applyView();
  }

  function nodeSummary(n) {
    const c = cfgOf(n);
    const m = W.meta;
    switch (n.type) {
      case 'input_text': return c.text ? esc(String(c.text).slice(0, 90)) : '<i class="muted">Chưa nhập nội dung</i>';
      case 'input_image': case 'input_video':
        return (c.files || []).length ? `${c.files.length} file · ${esc(c.files.map(f => f.split(/[\\/]/).pop()).join(', ').slice(0, 60))}` : '<i class="muted">Chưa chọn file</i>';
      case 'ai_text': {
        const prov = m.types.ai_text.fields[0].options.find(o => o.value === c.provider);
        return `<b>${esc(c.provider === 'claude_api' ? c.model : (prov ? prov.label : c.provider))}</b><br>${esc(String(c.prompt || '').slice(0, 70))}`;
      }
      case 'gen_image': return `<b>${esc((m.image_engines[c.engine] || {}).name || c.engine)}</b><br>${esc(c.aspect)} · ${esc(c.count)} ảnh${(c.refs || []).length ? ` · 📎 ${c.refs.length} ảnh tham chiếu` : ''}${c.pinterest ? ` · 📌 Pinterest${(c.pin_urls || []).length ? ` (${c.pin_urls.length} ảnh chọn)` : ''}` : ''}`;
      case 'gen_video': {
        if (c.template && !TPL) ensureTpl().then(() => renderCanvas());
        const t = tplById(c.template);
        const eng = t && t.video_engine ? t.video_engine : c.engine;
        const filled = t ? t.attachments.filter(a => (c.att || {})[a.key]).length : 0;
        return `<b>${esc((m.video_engines[eng] || {}).name || eng)}</b><br>${c.template ? `Template: <b>${esc(t ? t.name : (TPL ? '⚠ đã bị xoá' : '…'))}</b>${t && t.steps.length ? ` · ${t.steps.length + 1} bước` : ''}${c.prompt_override || Object.keys(c.step_prompts || {}).length ? ' · ✎ prompt đã sửa' : ''}${c.ask_vars ? ' · <span class="warn-text">hỏi khi chạy</span>' : ''}<br>`
          + (t && t.attachments.length ? `📎 ${filled}/${t.attachments.length} file chọn sẵn<br>` : '') : ''}${esc(t && t.options.aspect ? t.options.aspect : c.aspect)} · ${esc(c.duration)} · ${esc(c.resolution)}`;
      }
      case 'concat_video': {
        const label = (key, v) => ((spec('concat_video').fields.find(f => f.key === key).options || []).find(o => o.value === v) || {}).label || v;
        return `Khung ${esc(c.aspect)} · nối theo thứ tự dây<br>${c.transition && c.transition !== 'none' ? `🎞 ${esc(label('transition', c.transition))} ${esc(c.transition_duration)}s` : 'Cắt thẳng'}`
          + (c.transition_sound && c.transition_sound !== 'none' ? ` · 🔊 ${esc(label('transition_sound', c.transition_sound))}` : '');
      }
      case 'output': return `Thư mục: <b>${esc(c.name)}</b>`;
      case 'fb_post': case 'fb_schedule': {
        const page = FB && FB.pages.find(p => p.id === c.page_id);
        const sched = n.type === 'fb_schedule' || c.timing === 'app';
        const when = sched ? `${n.type === 'fb_schedule' && c.via !== 'app' ? '🗓 FB hẹn ' : '⏰ lên lịch '}${c.mode === 'at' ? `lúc ${esc(String(c.publish_at || '?').replace('T', ' '))}` : `sau ${esc(c.delay_hours)} giờ`}` : 'đăng ngay';
        const pt = (m.types[n.type].fields.find(f => f.key === 'post_type') || { options: [] }).options.find(o => o.value === (c.post_type || 'feed'));
        const srcs = (c.sources || []).filter(s => nodeById(s.node)).length;
        return `<b>${esc(page ? page.name : c.page_id ? `Page ${c.page_id}` : 'Chưa chọn Fanpage')}</b><br>${esc(pt ? pt.label : '')}<br>${when}${c.confirm ? ' · cần duyệt' : ' · <span class="warn-text">tự đăng</span>'}${srcs ? ` · 📎 ${srcs} tài nguyên` : ''}`;
      }
      case 'fb_ad': return `<b>${esc(c.daily_budget)}/ngày · ${esc(c.days)} ngày</b><br>${esc(c.countries)} · ${esc(c.age_min)}–${esc(c.age_max)} tuổi · tạo ở trạng thái tạm dừng`;
      default: return '';
    }
  }

  function nodeHtml(n) {
    const s = spec(n.type);
    const st = W.run && W.run.nodes[n.id] ? W.run.nodes[n.id] : null;
    const status = st ? st.status : '';
    const ask = (n.type.startsWith('input_') && cfgOf(n).ask) ? '<span class="wf-ask" title="Hỏi lại khi chạy">↻ input</span>' : '';
    return `<div class="wf-node g-${s.group} ${W.sel && W.sel.type === 'node' && W.sel.id === n.id ? 'sel' : ''} ${status ? `st-${status}` : ''}"
        data-node="${esc(n.id)}" style="left:${n.x}px;top:${n.y}px;width:${NODE_W}px">
      <div class="wf-node-head" data-drag><i>${esc(s.icon)}</i><b>${esc(s.name)}</b>${ask}
        <span class="wf-node-st" title="${esc(st && st.error ? st.error : '')}">${status ? esc(STATUS[status] || status) : ''}</span>
        <button class="wf-node-play" data-test-node="${esc(n.id)}" type="button" title="Chạy thử block này">▶</button></div>
      <div class="wf-node-body" data-drag>${nodeSummary(n)}</div>
      ${st && st.error ? `<div class="wf-node-err">${esc(st.error)}</div>` : ''}
      <div class="wf-ports">
        <div class="wf-ports-in">${s.inputs.map(p => `<div class="wf-port in t-${p.type}" data-port="${p.key}" data-ptype="${p.type}" title="${esc(TYPE_LABEL[p.type])}${p.multi ? ' · nhận nhiều dây' : ''}"><i></i><span>${esc(p.label)}</span></div>`).join('')}</div>
        <div class="wf-ports-out">${s.outputs.map(p => `<div class="wf-port out t-${p.type}" data-port="${p.key}" data-ptype="${p.type}" title="Kéo để nối · ${esc(TYPE_LABEL[p.type])}"><span>${esc(p.label)}</span><i></i></div>`).join('')}</div>
      </div>
      <span class="wf-node-id mono">${esc(n.id)}</span>
    </div>`;
  }

  function renderCanvas() {
    const has = W.wf && W.wf.nodes.length;
    $('#wfEmpty').classList.toggle('hidden', !W.wf || !!has);
    $('#wfEmptyPresets').innerHTML = W.presets.map(p => `<button class="btn ghost sm" data-quick="${esc(p.id)}" type="button">${esc(p.name)}</button>`).join(' ');
    $('#wfNodes').innerHTML = W.wf ? W.wf.nodes.map(nodeHtml).join('') : '';
    renderIssueMarks();
    renderEdges();
    applyView();
  }

  function portPos(nodeId, port, side) {
    const node = nodeById(nodeId);
    const el = $(`#wfNodes [data-node="${CSS.escape(nodeId)}"] .wf-port.${side}[data-port="${CSS.escape(port)}"] i`);
    if (!el || !node) return null;
    const nodeEl = el.closest('.wf-node');
    let x = el.offsetLeft + el.offsetWidth / 2, y = el.offsetTop + el.offsetHeight / 2;
    for (let p = el.offsetParent; p && p !== nodeEl; p = p.offsetParent) { x += p.offsetLeft; y += p.offsetTop; }
    return { x: node.x + x, y: node.y + y };
  }

  const curve = (a, b) => {
    const dx = Math.max(60, Math.abs(b.x - a.x) / 2);
    return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
  };

  function renderEdges(temp) {
    if (!W.wf) { $('#wfEdges').innerHTML = ''; return; }
    const runNodes = W.run ? W.run.nodes : {};
    const parts = W.wf.edges.map((e, i) => {
      const a = portPos(e.from, e.out, 'out'), b = portPos(e.to, e.in, 'in');
      if (!a || !b) return '';
      const type = (spec(nodeById(e.from).type).outputs.find(p => p.key === e.out) || {}).type || 'any';
      const flowing = runNodes[e.to] && runNodes[e.to].status === 'running';
      const sel = W.sel && W.sel.type === 'edge' && W.sel.id === i;
      return `<g class="wf-edge t-${type} ${sel ? 'sel' : ''} ${flowing ? 'flow' : ''}" data-edge="${i}">
        <path class="hit" d="${curve(a, b)}"/><path class="line" d="${curve(a, b)}"/></g>`;
    });
    W.wf.nodes.filter(isFb).forEach(n => (cfgOf(n).sources || []).forEach(src => {
      const from = nodeById(src.node);
      const out = from && spec(from.type).outputs.find(p => p.key === src.port);
      if (!out || !SRC_TYPES[out.type]) return;
      const a = portPos(src.node, src.port, 'out'), b = portPos(n.id, SRC_TYPES[out.type], 'in');
      if (a && b) parts.push(`<g class="wf-edge t-${out.type} virtual"><path class="line" d="${curve(a, b)}"/></g>`);
    }));
    if (temp) parts.push(`<path class="wf-edge-temp t-${temp.type}" d="${curve(temp.a, temp.b)}"/>`);
    $('#wfEdges').innerHTML = parts.join('');
  }

  function renderIssueMarks() {
    const bad = new Set(W.issues.filter(i => i.level === 'error' && i.node).map(i => i.node));
    $$('#wfNodes .wf-node').forEach(el => el.classList.toggle('has-issue', bad.has(el.dataset.node)));
  }

  // ================================================================ tương tác canvas
  function bindCanvas() {
    const canvas = $('#wfCanvas');
    canvas.addEventListener('dragover', e => { if (e.dataTransfer.types.includes('text/wf-type')) e.preventDefault(); });
    canvas.addEventListener('drop', e => {
      const type = e.dataTransfer.getData('text/wf-type');
      if (!type || !W.wf) return;
      e.preventDefault();
      const p = toWorld(e.clientX, e.clientY);
      addNode(type, p.x - NODE_W / 2, p.y - 24);
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const r = canvas.getBoundingClientRect();
      const before = toWorld(e.clientX, e.clientY);
      W.view.z = Math.max(0.35, Math.min(1.8, W.view.z * (e.deltaY < 0 ? 1.1 : 0.9)));
      W.view.x = e.clientX - r.left - before.x * W.view.z;
      W.view.y = e.clientY - r.top - before.y * W.view.z;
      applyView();
    }, { passive: false });
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('click', async e => {
      const quick = e.target.closest('[data-quick]');
      if (!quick) return;
      const res = await api('wf_from_preset', quick.dataset.quick);
      if (res.ok) openWorkflow(res.workflow.id); else toast(res.error, 'error');
    });
    canvas.addEventListener('dblclick', e => { if (e.target.closest('[data-node]')) $('#wfInspector').querySelector('textarea, input, select')?.focus(); });
    $('.wf-zoom').onclick = e => {
      const z = e.target.closest('[data-zoom]')?.dataset.zoom;
      if (!z) return;
      if (z === 'fit') return fitView();
      const r = canvas.getBoundingClientRect();
      const c = toWorld(r.left + r.width / 2, r.top + r.height / 2);
      W.view.z = Math.max(0.35, Math.min(1.8, W.view.z * (z === '1' ? 1.15 : 0.87)));
      W.view.x = r.width / 2 - c.x * W.view.z;
      W.view.y = r.height / 2 - c.y * W.view.z;
      applyView();
    };
  }

  function onPointerDown(e) {
    if (!W.wf || e.button !== 0 || e.target.closest('.wf-zoom, .wf-empty')) return;
    const play = e.target.closest('[data-test-node]');
    if (play) { e.stopPropagation(); e.preventDefault(); testNode(play.dataset.testNode); return; }
    const canvas = $('#wfCanvas');
    const port = e.target.closest('.wf-port.out');
    const drag = e.target.closest('[data-drag]');
    const nodeEl = e.target.closest('[data-node]');
    const edgeEl = e.target.closest('[data-edge]');
    canvas.focus({ preventScroll: true });
    if (port) return startConnect(e, port);
    if (edgeEl) { select({ type: 'edge', id: +edgeEl.dataset.edge }); return; }
    if (nodeEl) {
      if (!W.sel || W.sel.id !== nodeEl.dataset.node) select({ type: 'node', id: nodeEl.dataset.node });
      if (!drag) return;
      const node = nodeById(nodeEl.dataset.node);
      const start = { x: e.clientX, y: e.clientY, nx: node.x, ny: node.y };
      let moved = false;
      canvas.setPointerCapture(e.pointerId);
      canvas.onpointermove = ev => {
        node.x = Math.round(start.nx + (ev.clientX - start.x) / W.view.z);
        node.y = Math.round(start.ny + (ev.clientY - start.y) / W.view.z);
        const el = $(`#wfNodes [data-node="${CSS.escape(node.id)}"]`);
        el.style.left = `${node.x}px`; el.style.top = `${node.y}px`;
        moved = true;
        renderEdges();
      };
      canvas.onpointerup = () => { canvas.onpointermove = canvas.onpointerup = null; if (moved) changed({ validate: false }); };
      return;
    }
    // nền: kéo để di chuyển, bấm (không kéo) để bỏ chọn
    const start = { x: e.clientX, y: e.clientY, vx: W.view.x, vy: W.view.y };
    let moved = false;
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add('panning');
    canvas.onpointermove = ev => {
      W.view.x = start.vx + ev.clientX - start.x;
      W.view.y = start.vy + ev.clientY - start.y;
      moved = moved || Math.abs(ev.clientX - start.x) + Math.abs(ev.clientY - start.y) > 3;
      applyView();
    };
    canvas.onpointerup = () => {
      canvas.onpointermove = canvas.onpointerup = null;
      canvas.classList.remove('panning');
      if (!moved) select(null);
    };
  }

  function startConnect(e, portEl) {
    const canvas = $('#wfCanvas');
    const from = portEl.closest('[data-node]').dataset.node;
    const out = portEl.dataset.port;
    const type = portEl.dataset.ptype;
    const a = portPos(from, out, 'out');
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add('connecting');
    $$('#wfNodes .wf-port.in').forEach(p => {
      const ok = p.closest('[data-node]').dataset.node !== from && (p.dataset.ptype === 'any' || p.dataset.ptype === type);
      p.classList.toggle('can', ok);
      p.classList.toggle('cannot', !ok);
    });
    canvas.onpointermove = ev => renderEdges({ a, b: toWorld(ev.clientX, ev.clientY), type });
    canvas.onpointerup = ev => {
      canvas.onpointermove = canvas.onpointerup = null;
      canvas.classList.remove('connecting');
      // Thả trúng cổng (cả dòng chữ), hoặc "hút" vào cổng hợp lệ gần nhất trong 28px — dễ nối khi canvas thu nhỏ
      let target = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.wf-port.in');
      if (!target) {
        let best = 28;
        $$('#wfNodes .wf-port.in.can i').forEach(dot => {
          const r = dot.getBoundingClientRect();
          const d = Math.hypot(r.left + r.width / 2 - ev.clientX, r.top + r.height / 2 - ev.clientY);
          if (d < best) { best = d; target = dot.closest('.wf-port.in'); }
        });
      }
      $$('#wfNodes .wf-port.in').forEach(p => p.classList.remove('can', 'cannot'));
      if (target && target.closest('[data-node]').dataset.node !== from) {
        const to = target.closest('[data-node]').dataset.node;
        const inp = target.dataset.port;
        if (target.dataset.ptype !== 'any' && target.dataset.ptype !== type) {
          toast(`Không nối được: ${TYPE_LABEL[type]} → ${TYPE_LABEL[target.dataset.ptype]}`, 'warn');
        } else if (W.wf.edges.some(x => x.from === from && x.out === out && x.to === to && x.in === inp)) {
          toast('Hai cổng này đã được nối', 'warn');
        } else {
          const portSpec = spec(nodeById(to).type).inputs.find(p => p.key === inp);
          if (!portSpec.multi) W.wf.edges = W.wf.edges.filter(x => !(x.to === to && x.in === inp));
          W.wf.edges.push({ from, out, to, in: inp });
          changed();
          if (W.sel && W.sel.type === 'node') renderInspector();
        }
      }
      renderEdges();
    };
  }

  function select(sel) {
    W.sel = sel;
    $$('#wfNodes .wf-node').forEach(el => el.classList.toggle('sel', !!sel && sel.type === 'node' && el.dataset.node === sel.id));
    renderEdges();
    renderInspector();
  }

  function removeSelected() {
    if (!W.sel || !W.wf) return;
    if (W.sel.type === 'node') {
      const id = W.sel.id;
      W.wf.nodes = W.wf.nodes.filter(n => n.id !== id);
      W.wf.edges = W.wf.edges.filter(e => e.from !== id && e.to !== id);
    } else {
      W.wf.edges.splice(W.sel.id, 1);
    }
    W.sel = null;
    renderCanvas();
    renderInspector();
    changed();
  }

  function onKey(e) {
    if ($('#page-workflow').classList.contains('hidden') || !$('#modal').classList.contains('hidden')) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if ((e.key === 'Delete' || e.key === 'Backspace') && !typing && W.sel) { e.preventDefault(); removeSelected(); }
    if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
    if (e.key === 'Escape' && !typing) select(null);
  }

  // ================================================================ 02 · bảng cấu hình (bên phải)
  function fieldVisible(f, cfg) {
    if (!f.when) return true;
    return Object.entries(f.when).every(([k, vals]) => (vals === '*' ? (Array.isArray(cfg[k]) ? cfg[k].length > 0 : !!cfg[k]) : (Array.isArray(vals) ? vals : [vals]).includes(cfg[k])));
  }

  function fieldHtml(f, cfg) {
    const v = cfg[f.key];
    if (f.type === 'textarea') return `<label class="field"><span>${esc(f.label)}</span><textarea data-f="${f.key}" rows="${f.key === 'prompt' ? 7 : f.key === 'template' ? 12 : 4}">${esc(v ?? '')}</textarea></label>`;
    if (f.type === 'select' && LOCK[f.key]) {
      const o = f.options.find(x => String(x.value) === String(LOCK[f.key])) || { label: LOCK[f.key] };
      return `<label class="field"><span>${esc(f.label)} <small class="muted">· theo template</small></span><select disabled><option>${esc(o.label)}</option></select></label>`;
    }
    if (f.type === 'select') return `<label class="field"><span>${esc(f.label)}</span><select data-f="${f.key}">${f.options.map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`;
    if (f.type === 'check') return `<label class="check"><input type="checkbox" data-f="${f.key}" ${v ? 'checked' : ''}> ${esc(f.label)}</label>`;
    if (f.type === 'number') return `<label class="field"><span>${esc(f.label)}</span><input type="number" min="0" step="any" data-f="${f.key}" value="${esc(v ?? '')}"></label>`;
    if (f.type === 'datetime') return `<label class="field"><span>${esc(f.label)}</span><input type="datetime-local" data-f="${f.key}" value="${esc(v ?? '')}"></label>`;
    if (f.type === 'video_template') {
      const cur = tplById(v);
      const m = W.meta;
      const out = cur ? [cur.options.aspect, cur.options.duration, cur.options.resolution].filter(Boolean).join(' · ') : '';
      const head = !TPL ? '<div class="muted">Đang tải template…</div>'
        : cur ? `<div class="wf-tpl-cur"><div class="wf-tpl-cur-thumb">${cur.has_thumb ? `<img src="/tpl/${encodeURIComponent(cur.id)}/thumb" alt="">` : '<span>🎬</span>'}</div>
            <div><b>${esc(cur.name)}</b><small>${esc(cur.description || '')}</small>
              <div class="wf-tpl-tags"><span class="badge ai">Video AI</span>${cur.user ? '<span class="badge">Của bạn</span>' : ''}
                ${cur.steps.length ? `<span class="badge">${cur.steps.length + 1} bước</span>` : ''}</div></div></div>
          <div class="wf-tpl-out"><b>Video đầu ra theo template:</b> ${esc(out || 'theo cấu hình block')}
            ${cur.video_engine ? ` · model cố định <b>${esc((m.video_engines[cur.video_engine] || {}).name || cur.video_engine)}</b>` : ''}
            ${cur.steps.length ? `<ol class="wf-tpl-steps">${cur.steps.map(s => `<li>${esc(s.label)}${s.engine ? ` <small>(${esc((m.image_engines[s.engine] || {}).name || s.engine)})</small>` : ''}</li>`).join('')}<li>Tạo video</li></ol>` : ''}</div>`
          : v ? '<div class="wf-issue error">✕ Template đã bị xoá — chọn template khác</div>'
            : '<div class="muted">Không dùng template — video tạo từ prompt tự do.</div>';
      return `<div class="field"><span>${esc(f.label)}</span>${head}
        <div class="row wf-tpl-actions"><button class="btn primary sm" data-tpl-pick type="button">${cur ? '⇄ Đổi template' : '▦ Chọn template…'}</button>
          ${v ? '<button class="btn ghost sm" data-tpl-clear type="button">Bỏ template</button>' : ''}
          <button class="btn ghost sm" data-tpl="new" type="button">+ Tạo template</button>
          ${cur ? (cur.user ? '<button class="btn ghost sm" data-tpl="edit" type="button">✎ Sửa</button>'
            : '<button class="btn ghost sm" data-tpl="copy" type="button">⧉ Bản sao để sửa</button>') : ''}</div></div>`;
    }
    if (f.type === 'template_flow') {
      const t = tplById(cfg.template);
      if (!t) return '';
      const m = W.meta;
      const vars = Object.fromEntries(t.variables.map(x => [x.key, String((cfg.vars || {})[x.key] || x.default || '').trim()]));
      Object.entries(t.computed || {}).forEach(([k, pattern]) => {  // biến tự ghép, vd. {FULL_SCRIPT} = các câu thoại
        vars[k] = pattern.replace(/\{(\w+)\}/g, (all, key) => vars[key] ?? '').replace(/\s+/g, ' ').trim();
      });
      // ô tham chiếu là video + model nhận được video → template dùng prompt riêng cho video tham chiếu
      const videoRef = !!t.video_prompt && (m.video_engines[t.video_engine || cfg.engine] || {}).video_input
        && t.attachments.some(a => a.send_video && /\.(mp4|mov|webm|m4v)$/i.test((cfg.att || {})[a.key] || ''));
      if (cfg.var_input && W.sel && W.wf.edges.some(e => e.to === W.sel.id && e.in === 'prompt')) vars[cfg.var_input] = '⟨văn bản từ dây Prompt⟩';
      const labelOf = key => (t.attachments.find(a => a.key === key) || t.steps.find(x => x.key === key) || { label: key }).label;
      const stepPrompts = cfg.step_prompts || {};
      const vEng = t.video_engine || cfg.engine;
      const videoIns = t.video_inputs.length ? t.video_inputs : t.attachments.map(a => ({ key: a.key }));
      const box = (no, key, title, meta, inputs, raw, edited) => `<div class="wf-flow-step">
          <div class="wf-flow-head"><span class="no">${no}</span><div><b>${esc(title)}</b><small>${meta}</small></div></div>
          ${inputs.length ? `<div class="wf-flow-in"><small>Đầu vào:</small> ${inputs.map(i => `<span class="camp-chip">${esc(labelOf(i.key))}</span>`).join('')}</div>` : ''}
          <details data-flow="${esc(key)}" ${W.flowOpen.has(key) ? 'open' : ''}><summary>Prompt ${key === 'main' ? 'tạo video' : 'bước này'}${edited ? ' <span class="warn-text">· đã sửa cho block này</span>' : ''}</summary>
            <pre class="wf-flow-prompt">${flowPreview(raw, vars)}</pre>
            <div class="row wf-flow-actions"><button class="btn ghost sm" data-flow-edit="${esc(key)}" type="button">✎ Sửa prompt</button>
              ${edited ? `<button class="btn ghost sm" data-flow-reset="${esc(key)}" type="button">↺ Dùng prompt gốc</button>` : ''}</div></details></div>`;
      return `<div class="field wf-flow"><span>${esc(f.label)} <small class="muted">· ${t.steps.length + 1} bước</small></span>
        ${t.steps.map((x, i) => box(i + 1, x.key, x.label, `${esc((m.image_engines[x.engine || vEng] || {}).name || x.engine || vEng)} · khung ${esc(x.aspect || '9:16')}`,
          x.inputs, stepPrompts[x.key] || x.prompt, !!stepPrompts[x.key])).join('')}
        ${box(t.steps.length + 1, 'main', 'Tạo video', `${esc((m.video_engines[vEng] || {}).name || vEng)} · ${esc(t.options.aspect || cfg.aspect)} · ${esc(cfg.duration)} · ${esc(cfg.resolution)}`,
          videoIns, cfg.prompt_override || (videoRef ? t.video_prompt : t.prompt), !!cfg.prompt_override)}
        ${t.video_prompt ? `<small class="muted">${videoRef ? '🎞 Đang dùng prompt cho VIDEO tham chiếu (gửi nguyên video cho model).'
          : 'Chọn video ở ô tham chiếu (model Grok / Dola) để dùng prompt bám sát chuyển động của video.'}</small>` : ''}
        <small class="muted">Phần <mark>tô màu</mark> là thông tin bạn nhập. Cuối prompt app tự thêm câu mô tả vai trò từng ảnh/video theo thứ tự gửi.</small></div>`;
    }
    if (f.type === 'template_files') {
      const t = tplById(cfg.template);
      if (!t || !t.attachments.length) return '';
      const files = cfg.att || {};
      const wired = W.sel ? new Set(W.wf.edges.filter(e => e.to === W.sel.id).map(e => e.in)) : new Set();
      return `<div class="field wf-tpl-files"><span>${esc(f.label)}${cfg.ask_vars ? ' <small class="warn-text">· sẽ hỏi lại khi chạy</small>' : ''}</span>
        ${t.attachments.map(a => slotHtml(a, files[a.key], wired, `data-att-pick="${esc(a.key)}"`, `data-att-rm="${esc(a.key)}"`)).join('')}</div>`;
    }
    if (f.type === 'template_vars') {
      const t = tplById(cfg.template);
      if (!t || !t.variables.length) return '';
      const vals = cfg.vars || {};
      return `<div class="field wf-tpl-vars"><span>${esc(f.label)}${cfg.ask_vars ? ' <small class="warn-text">· sẽ hỏi lại khi chạy</small>' : ''}</span>
        ${t.variables.map(x => `<label class="wf-var"><small>${esc(x.label)}${x.required !== false ? ' <b class="req">*</b>' : ''}</small>
          ${cfg.var_input === x.key ? '<em class="muted">Lấy từ dây Prompt</em>'
            : `<input data-var="${esc(x.key)}" value="${esc(vals[x.key] || '')}" placeholder="${esc(x.default || x.placeholder || '')}">`}</label>`).join('')}
        ${t.variables.some(x => x.default) ? '<small class="muted">Để trống = dùng giá trị mặc định (chữ mờ).</small>' : ''}</div>`;
    }
    if (f.type === 'template_var') {
      const t = tplById(cfg.template);
      if (!t || !t.variables.length) return '';
      return `<label class="field"><span>${esc(f.label)}</span><select data-f="${f.key}">
        <option value="">— Không (ghép vào cuối prompt làm ghi chú) —</option>
        ${t.variables.map(x => `<option value="${esc(x.key)}" ${x.key === v ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select></label>`;
    }
    if (f.type === 'pinterest') {
      const urls = v || [];
      return `<div class="field"><span>${esc(f.label)}</span>
        ${urls.length ? `<div class="wf-pins">${urls.map((u, i) => `<span class="wf-pin"><img src="${esc(pinThumb(u))}" alt="" referrerpolicy="no-referrer" loading="lazy"><button data-pin-rm="${i}" type="button" title="Bỏ ảnh">✕</button></span>`).join('')}</div>` : ''}
        <button class="btn ghost sm" data-pin-search type="button">🔍 Tìm & chọn ảnh Pinterest…</button>
        <small class="muted">${urls.length ? `Dùng đúng ${urls.length} ảnh đã chọn.` : 'Chưa chọn ảnh — khi chạy app tự tìm theo từ khoá. Ảnh Pinterest chỉ dùng để tham khảo bố cục, màu sắc.'}</small></div>`;
    }
    if (f.type === 'fb_page' || f.type === 'ad_account') {
      const list = FB ? (f.type === 'fb_page' ? FB.pages : FB.accounts) : null;
      const empty = f.type === 'fb_page' ? 'Chưa có Fanpage nào bật Kết nối' : (FB && FB.accounts_error ? 'Chưa đọc được tài khoản quảng cáo' : 'Không có tài khoản quảng cáo');
      return `<label class="field"><span>${esc(f.label)} <button class="link" data-reload-fb type="button">↻ tải lại</button></span>
        <select data-f="${f.key}">${list === null ? '<option>Đang tải…</option>'
          : `<option value="">— Chọn —</option>${list.map(o => `<option value="${esc(o.id)}" ${o.id === v ? 'selected' : ''}>${esc(o.name)}${o.currency ? ` · ${esc(o.currency)}` : ''}</option>`).join('')}`}</select>
        ${list && !list.length ? `<small class="warn-text">${esc(empty)}${f.type === 'ad_account' && FB.accounts_error ? ` — ${esc(FB.accounts_error)}` : ''}</small>` : ''}</label>`;
    }
    if (f.type === 'studio_preset') {  // block Video dài từ storyboard: lấy toàn bộ cài đặt của 1 dự án Studio
      const p = STUDIO && STUDIO.find(x => x.id === v);
      return `<label class="field"><span>${esc(f.label)} <button class="link" data-reload-studio type="button">↻ tải lại</button></span>
        <select data-f="${f.key}">${STUDIO === null ? '<option>Đang tải…</option>'
          : `<option value="">— Không dùng: chỉnh ở các ô bên dưới —</option>${STUDIO.map(x => `<option value="${esc(x.id)}" ${x.id === v ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}`}</select>
        <small class="muted">${v ? (p ? `Dùng toàn bộ cài đặt của “${esc(p.name)}”${p.logo ? ' (kèm logo)' : ''}: model, giọng, ràng buộc prompt, chuyển cảnh, hậu kỳ… — sửa ở màn <button class="link" data-open-studio type="button">Studio</button> → ⚙.`
          : '<span class="warn-text">Không còn dự án này — chọn lại.</span>')
          : 'Mỗi lần chạy tạo 1 dự án mới trong màn Studio (xem / sửa cảnh / ghép lại được sau).'}</small></label>`;
    }
    if (f.type === 'flow_sources') {
      const me = W.sel ? W.sel.id : '';
      const below = descendants(me);
      const cur = v || [];
      const opts = [];
      W.wf.nodes.forEach(n => {
        if (n.id === me || below.has(n.id)) return;
        spec(n.type).outputs.forEach(o => { if (SRC_TYPES[o.type]) opts.push({ n, o }); });
      });
      const rows = opts.map(({ n, o }) => {
        const i = cur.findIndex(x => x.node === n.id && x.port === o.key);
        return `<label class="wf-src ${i >= 0 ? 'on' : ''}"><input type="checkbox" data-src="${esc(n.id)}|${esc(o.key)}" ${i >= 0 ? 'checked' : ''}>
          <i class="wf-src-dot t-${o.type}"></i><span><b>${esc(spec(n.type).name)}</b> <small class="mono">${esc(n.id)}</small><br><small>${esc(o.label)} · ${o.type === 'text' ? 'dùng làm caption' : 'ảnh/video để đăng'}</small></span>
          ${i >= 0 ? `<em title="Thứ tự dùng">${i + 1}</em>` : ''}</label>`;
      }).join('');
      return `<div class="field"><span>${esc(f.label)}</span>${opts.length ? `<div class="wf-sources">${rows}</div>`
        : '<div class="muted">Chưa có block nào tạo văn bản / ảnh / video phía trước block này.</div>'}
        <small class="muted">Tick theo thứ tự muốn dùng (số bên phải). Dây nối tay vẫn dùng được; trên canvas tài nguyên chọn hiện dạng dây nét đứt.</small></div>`;
    }
    if (f.type === 'files') return `<div class="field"><span>${esc(f.label)}</span><div class="wf-files">${(v || []).map((p, i) => `<span class="camp-chip">${esc(p.split(/[\\/]/).pop())}<button data-rmfile="${f.key}:${i}" type="button">✕</button></span>`).join('')}
      <button class="btn ghost sm" data-pick="${f.key}" data-kind="${esc(f.kind)}" data-single="${f.single ? 1 : 0}" type="button">+ Chọn file…</button></div></div>`;
    return `<label class="field"><span>${esc(f.label)}</span><input data-f="${f.key}" value="${esc(v ?? '')}"></label>`;
  }

  function engineNote(n, cfg) {
    if (n.type === 'gen_video') {
      const e = W.meta.video_engines[cfg.engine];
      if (!e) return '';
      const off = [['aspect', 'aspects', 'tỉ lệ'], ['duration', 'durations', 'thời lượng'], ['resolution', 'resolutions', 'độ phân giải']].filter(([k, l]) => !e[l].includes(cfg[k]));
      return `<div class="wf-note">${esc(e.note)}<br><small>Hỗ trợ: ${esc(e.aspects.join(', '))} · ${esc(e.durations.join(', '))} · ${esc(e.resolutions.join(', '))} · tối đa ${e.max_images} ảnh.</small>
        ${off.length ? `<b class="warn">Sẽ tự đổi ${off.map(x => x[2]).join(', ')} về giá trị gần nhất model hỗ trợ.</b>` : ''}</div>`;
    }
    if (n.type === 'gen_image') { const e = W.meta.image_engines[cfg.engine]; return e ? `<div class="wf-note">${esc(e.note)}</div>` : ''; }
    if (n.type === 'ai_text') {
      return `<div class="wf-note">${cfg.provider === 'claude_api' ? 'Dùng khoá Anthropic ở Cài đặt → API & kết nối; có bật fallback khi bộ lọc an toàn từ chối.'
        : 'Dùng tài khoản đã đăng nhập (Profile trình duyệt).'} Viết <code>{{input}}</code> để chèn văn bản đầu vào.</div>`;
    }
    return '';
  }

  function renderInspector() {
    const box = $('#wfInspector');
    if (!W.wf) { box.innerHTML = '<div class="empty">Bấm “+ Mới” để tạo workflow đầu tiên.</div>'; return; }
    if (W.sel && W.sel.type === 'node' && nodeById(W.sel.id)) {
      const n = nodeById(W.sel.id);
      if (n.type.startsWith('fb_') && !FB) ensureFb().then(() => { renderInspector(); renderCanvas(); });
      if (n.type === 'gen_video' && !TPL) ensureTpl().then(() => { renderInspector(); renderCanvas(); });
      if (n.type === 'studio_video' && !STUDIO) ensureStudio().then(() => renderInspector());
      const s = spec(n.type);
      const cfg = cfgOf(n);
      const issues = W.issues.filter(i => i.node === n.id);
      const wiredIn = W.wf.edges.filter(e => e.to === n.id);
      const st = W.run && W.run.nodes[n.id];
      box.innerHTML = `<div class="wf-insp-head g-${s.group}"><i>${esc(s.icon)}</i><div><b>${esc(s.name)}</b><small>${esc(s.desc)} · <span class="mono">${esc(n.id)}</span></small></div></div>
        <div class="wf-insp-issues">${issuesHtml(issues)}</div>
        <div class="form wf-form">${(LOCK = n.type === 'gen_video' ? tplLock(cfg) : {}, s.fields.filter(f => fieldVisible(f, cfg)).map(f => fieldHtml(f, cfg)).join(''))}</div>
        ${engineNote(n, cfg)}
        ${s.inputs.length ? `<div class="wf-insp-sec"><small>CỔNG VÀO</small>${s.inputs.map(p => {
          const ws = wiredIn.filter(e => e.in === p.key);
          return `<div class="wf-wire"><i class="t-${p.type}"></i><b>${esc(p.label)}</b><span>${ws.length ? ws.map(e => `${esc(spec(nodeById(e.from).type).name)} (${esc(e.from)})`).join(', ') : '<span class="muted">chưa nối</span>'}</span></div>`;
        }).join('')}</div>` : ''}
        ${st && st.outputs && Object.keys(st.outputs).length ? `<div class="wf-insp-sec"><small>KẾT QUẢ LẦN CHẠY ${esc(W.run.id)}</small>${outputsHtml(st.outputs)}</div>` : ''}
        <div class="wf-insp-sec wf-test"><small>CHẠY THỬ</small>
          <p class="muted">Chỉ chạy block này. Block phía trước dùng lại kết quả lần chạy trước nếu cấu hình không đổi.</p>
          <button class="btn primary sm" data-act="test-node" type="button" ${isRunning() ? 'disabled' : ''}>▶ Chạy thử block này</button></div>
        <div class="row wf-insp-actions"><button class="btn ghost sm" data-act="dup-node" type="button">⧉ Nhân đôi</button>
          <button class="btn danger sm" data-act="del-node" type="button">Xoá block</button></div>`;
    } else if (W.sel && W.sel.type === 'edge' && W.wf.edges[W.sel.id]) {
      const e = W.wf.edges[W.sel.id];
      box.innerHTML = `<div class="wf-insp-head"><i>⟶</i><div><b>Dây nối</b><small>${esc(spec(nodeById(e.from).type).name)} → ${esc(spec(nodeById(e.to).type).name)}</small></div></div>
        <p class="muted mono">${esc(e.from)}.${esc(e.out)} → ${esc(e.to)}.${esc(e.in)}</p>
        <button class="btn danger sm" data-act="del-edge" type="button">Xoá dây nối</button>`;
    } else {
      const errors = W.issues.filter(i => i.level === 'error');
      box.innerHTML = `<div class="wf-insp-head"><i>⚙</i><div><b>Thông tin workflow</b><small>Chọn 1 block để cấu hình</small></div></div>
        <label class="field"><span>Mô tả</span><textarea id="wfDesc" rows="3" placeholder="Workflow này dùng để…">${esc(W.wf.desc || '')}</textarea></label>
        <div class="wf-stats"><span><b>${W.wf.nodes.length}</b> block</span><span><b>${W.wf.edges.length}</b> dây</span><span><b>${W.runs.length}</b> lần chạy</span></div>
        <div class="wf-insp-sec"><small>KIỂM TRA · ${errors.length ? `${errors.length} lỗi` : 'sẵn sàng chạy'}</small>
          ${W.issues.length ? W.issues.map(i => `<div class="wf-issue ${i.level}" ${i.node ? `data-goto="${esc(i.node)}"` : ''}>${i.level === 'error' ? '✕' : '!'} ${i.node ? `<b>${esc(i.node)}</b> ` : ''}${esc(i.message)}</div>`).join('')
            : '<div class="wf-issue ok">✓ Không có lỗi — bấm ▶ Chạy</div>'}</div>
        <div class="wf-insp-sec"><small>CÁCH DÙNG</small><ol class="wf-guide">
          <li><b>Thiết kế:</b> kéo block vào canvas; kéo từ cổng ra (phải) sang cổng vào (trái) để nối.</li>
          <li><b>Cấu hình AI:</b> chọn block → chọn model (Grok, Veo, Seedance, Claude…), viết prompt.</li>
          <li><b>Chạy:</b> bấm ▶ Chạy — các block chạy lần lượt theo dây; theo dõi ở khay dưới.</li>
          <li><b>Tái sử dụng:</b> bật “Hỏi lại khi chạy” ở block đầu vào → mỗi lần chỉ đổi input.</li></ol></div>`;
    }
    bindInspector();
  }

  function bindFlow(box) {
    $$('details[data-flow]', box).forEach(d => {  // nhớ bước nào đang mở khi vẽ lại bảng
      d.ontoggle = () => (d.open ? W.flowOpen.add(d.dataset.flow) : W.flowOpen.delete(d.dataset.flow));
    });
  }

  function bindInspector() {
    const box = $('#wfInspector');
    bindFlow(box);
    box.oninput = e => {
      if (e.target.id === 'wfDesc') { W.wf.desc = e.target.value; changed({ validate: false }); return; }
      if (e.target.dataset.src && W.sel && W.sel.type === 'node') {
        const n = nodeById(W.sel.id);
        const [node, port] = e.target.dataset.src.split('|');
        let list = (cfgOf(n).sources || []).filter(x => !(x.node === node && x.port === port) && nodeById(x.node));
        if (e.target.checked) list = [...list, { node, port }];
        n.config = { ...cfgOf(n), sources: list };
        renderCanvas(); renderInspector(); changed();
        return;
      }
      const vk = e.target.dataset.var;
      if (vk && W.sel && W.sel.type === 'node') {
        const n = nodeById(W.sel.id);
        n.config = { ...cfgOf(n), vars: { ...(cfgOf(n).vars || {}), [vk]: e.target.value } };
        const flow = box.querySelector('.wf-flow');  // xem trước prompt template cập nhật ngay khi gõ
        if (flow) { flow.outerHTML = fieldHtml(spec(n.type).fields.find(x => x.type === 'template_flow'), cfgOf(n)); bindFlow(box); }
        changed();
        return;
      }
      const f = e.target.dataset.f;
      if (!f || !W.sel || W.sel.type !== 'node') return;
      const n = nodeById(W.sel.id);
      n.config = { ...cfgOf(n), [f]: e.target.type === 'checkbox' ? e.target.checked : e.target.value };
      if (f === 'template') applyTemplate(n);
      const el = $(`#wfNodes [data-node="${CSS.escape(n.id)}"]`);
      if (el) { el.outerHTML = nodeHtml(n); renderIssueMarks(); renderEdges(); }
      if (e.target.tagName === 'SELECT' || e.target.type === 'checkbox') renderInspector();
      changed();
    };
    box.onclick = async e => {
      if (e.target.closest('[data-reload-fb]')) { e.preventDefault(); await ensureFb(true); renderInspector(); renderCanvas(); return; }
      if (e.target.closest('[data-reload-studio]')) { e.preventDefault(); await ensureStudio(true); renderInspector(); return; }
      if (e.target.closest('[data-open-studio]')) { e.preventDefault(); return navigate('studio'); }
      const tb = e.target.closest('[data-tpl]');
      if (tb) return openTemplateEditor(tb.dataset.tpl);
      if (e.target.closest('[data-tpl-pick]')) return openTemplatePicker();
      const fe = e.target.closest('[data-flow-edit]');
      if (fe) return openFlowEditor(fe.dataset.flowEdit);
      const fr = e.target.closest('[data-flow-reset]');
      if (fr) { setFlowPrompt(nodeById(W.sel.id), fr.dataset.flowReset, ''); return toast('Đã dùng lại prompt gốc của template', 'ok'); }
      if (e.target.closest('[data-tpl-clear]')) {
        const n = nodeById(W.sel.id);
        n.config = { ...cfgOf(n), template: '' };
        renderCanvas(); renderInspector(); changed();
        return;
      }
      const ap = e.target.closest('[data-att-pick]');
      const ar = e.target.closest('[data-att-rm]');
      if (ap || ar) {
        const n = nodeById(W.sel.id);
        const att = { ...(cfgOf(n).att || {}) };
        if (ap) {
          const files = await api('pick_files', ap.dataset.kind);
          if (!files.length) return;
          att[ap.dataset.attPick] = files[0];
        } else delete att[ar.dataset.attRm];
        n.config = { ...cfgOf(n), att };
        renderCanvas(); renderInspector(); changed();
        return;
      }
      if (e.target.closest('[data-pin-search]')) return openPinPicker();
      const prm = e.target.closest('[data-pin-rm]');
      if (prm) {
        const n = nodeById(W.sel.id);
        const urls = [...(cfgOf(n).pin_urls || [])];
        urls.splice(+prm.dataset.pinRm, 1);
        n.config = { ...cfgOf(n), pin_urls: urls };
        renderCanvas(); renderInspector(); changed();
        return;
      }
      const goto = e.target.closest('[data-goto]');
      if (goto) return select({ type: 'node', id: goto.dataset.goto });
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'del-node' || act === 'del-edge') return removeSelected();
      if (act === 'dup-node') { const n = nodeById(W.sel.id); addNode(n.type, n.x + 40, n.y + 70, n.config); return; }
      if (act === 'test-node') return testNode(W.sel.id);
      const pick = e.target.closest('[data-pick]');
      if (pick) {
        const files = await api('pick_files', pick.dataset.kind);
        if (!files.length) return;
        const n = nodeById(W.sel.id);
        const key = pick.dataset.pick;
        n.config = { ...cfgOf(n), [key]: pick.dataset.single === '1' ? files.slice(0, 1) : [...new Set([...(cfgOf(n)[key] || []), ...files])] };
        renderCanvas(); renderInspector(); changed();
        return;
      }
      const rm = e.target.closest('[data-rmfile]');
      if (rm) {
        const [key, i] = rm.dataset.rmfile.split(':');
        const n = nodeById(W.sel.id);
        const list = [...(cfgOf(n)[key] || [])];
        list.splice(+i, 1);
        n.config = { ...cfgOf(n), [key]: list };
        renderCanvas(); renderInspector(); changed();
      }
    };
  }

  // ================================================================ 03 · chạy · 04 · tái sử dụng (đổi input khi chạy)
  async function startRun() {
    if (!W.wf || isRunning()) return;
    if (!(await save())) return;
    await ensureTpl();
    const asks = W.wf.nodes.filter(n => n.type.startsWith('input_') && cfgOf(n).ask);
    const tplAsks = W.wf.nodes.filter(n => n.type === 'gen_video' && cfgOf(n).template && cfgOf(n).ask_vars && tplById(cfgOf(n).template));
    const blocking = W.issues.filter(i => i.level === 'error' && ![...asks, ...tplAsks].some(n => n.id === i.node));
    if (blocking.length) {
      W.tab = 'issues'; renderTray();
      if (blocking[0].node) select({ type: 'node', id: blocking[0].node });
      return toast(`Còn ${blocking.length} lỗi cấu hình — xem tab Kiểm tra`, 'warn');
    }
    if (!asks.length && !tplAsks.length) return doRun({});
    const wiredVar = n => W.wf.edges.some(e => e.to === n.id && e.in === 'prompt') ? cfgOf(n).var_input : '';
    const values = {};
    openModal('CHẠY WORKFLOW', `Input cho lần chạy · ${W.wf.name}`, `<div class="form">
      <p class="muted">Đổi input rồi bấm Chạy — các block còn lại giữ nguyên cấu hình (bước 04 · Tái sử dụng).</p>
      ${asks.map(n => {
        const c = cfgOf(n);
        values[n.id] = n.type === 'input_text' ? { text: c.text || '' } : { files: [...(c.files || [])] };
        return n.type === 'input_text'
          ? `<label class="field"><span>${esc(c.label || 'Văn bản')} <small class="mono muted">${esc(n.id)}</small></span><textarea data-ask="${esc(n.id)}" rows="4">${esc(c.text || '')}</textarea></label>`
          : `<div class="field"><span>${esc(c.label || 'File')} <small class="mono muted">${esc(n.id)}</small></span><div class="wf-files"><span data-askfiles="${esc(n.id)}"></span>
              <button class="btn ghost sm" data-askpick="${esc(n.id)}" data-kind="${esc(spec(n.type).fields.find(f => f.type === 'files').kind)}" data-single="${n.type === 'input_video' ? 1 : 0}" type="button">+ Chọn file…</button></div></div>`;
      }).join('')}
      ${tplAsks.map(n => {
        const c = cfgOf(n); const t = tplById(c.template);
        values[n.id] = { vars: { ...(c.vars || {}) }, att: { ...(c.att || {}) } };
        const fields = t.variables.filter(x => x.key !== wiredVar(n));
        const wiredPorts = new Set(W.wf.edges.filter(e => e.to === n.id).map(e => e.in));
        return `<div class="wf-ask-tpl"><div class="wf-ask-tpl-head">▶ Tạo video · template <b>${esc(t.name)}</b> <small class="mono muted">${esc(n.id)}</small></div>
          ${fields.map(x => `<label class="field"><span>${esc(x.label)}${x.required !== false ? ' <b class="req">*</b>' : ''}</span>
            <input data-askvar="${esc(n.id)}|${esc(x.key)}" value="${esc(values[n.id].vars[x.key] || '')}" placeholder="${esc(x.default || x.placeholder || '')}"></label>`).join('')}
          ${t.attachments.map(a => `<div data-askslot="${esc(n.id)}|${esc(a.key)}">${slotHtml(a, values[n.id].att[a.key], wiredPorts,
              `data-askatt="${esc(n.id)}|${esc(a.key)}"`, `data-askatt-rm="${esc(n.id)}|${esc(a.key)}"`)}</div>`).join('')}
          ${!fields.length && !t.attachments.length ? '<small class="muted">Không còn thông tin nào cần nhập.</small>' : ''}</div>`;
      }).join('')}
      <label class="check"><input type="checkbox" id="wfKeepInputs" checked> Lưu input này làm mặc định cho lần sau</label>
      <div class="modal-foot"><button class="btn primary" id="wfGo" type="button">▶ Chạy workflow</button></div></div>`, true);
    const drawFiles = () => $$('[data-askfiles]').forEach(el => {
      const id = el.dataset.askfiles;
      el.innerHTML = values[id].files.map((p, i) => `<span class="camp-chip">${esc(p.split(/[\\/]/).pop())}<button data-askrm="${esc(id)}:${i}" type="button">✕</button></span>`).join('')
        || '<span class="muted">Chưa chọn file</span>';
    });
    drawFiles();
    $('#modalBody').oninput = e => {
      if (e.target.dataset.ask) values[e.target.dataset.ask].text = e.target.value;
      if (e.target.dataset.askvar) { const [id, k] = e.target.dataset.askvar.split('|'); values[id].vars[k] = e.target.value; }
    };
    $('#modalBody').onclick = async e => {
      const pick = e.target.closest('[data-askpick]');
      if (pick) {
        const files = await api('pick_files', pick.dataset.kind);
        if (files.length) {
          const id = pick.dataset.askpick;
          values[id].files = pick.dataset.single === '1' ? files.slice(0, 1) : [...new Set([...values[id].files, ...files])];
          drawFiles();
        }
        return;
      }
      const sa = e.target.closest('[data-askatt]'), sr = e.target.closest('[data-askatt-rm]');
      if (sa || sr) {
        const [id, key] = (sa ? sa.dataset.askatt : sr.dataset.askattRm).split('|');
        if (sa) {
          const files = await api('pick_files', sa.dataset.kind);
          if (!files.length) return;
          values[id].att[key] = files[0];
        } else delete values[id].att[key];
        const n = nodeById(id); const t = tplById(cfgOf(n).template); const a = t.attachments.find(x => x.key === key);
        const wiredPorts = new Set(W.wf.edges.filter(x => x.to === id).map(x => x.in));
        $(`[data-askslot="${CSS.escape(id + '|' + key)}"]`).innerHTML = slotHtml(a, values[id].att[key], wiredPorts,
          `data-askatt="${esc(id)}|${esc(key)}"`, `data-askatt-rm="${esc(id)}|${esc(key)}"`);
        return;
      }
      const rm = e.target.closest('[data-askrm]');
      if (rm) { const [id, i] = rm.dataset.askrm.split(':'); values[id].files.splice(+i, 1); drawFiles(); return; }
      if (e.target.closest('#wfGo')) {
        for (const n of tplAsks) {  // thông tin bắt buộc của template còn trống → không chạy
          const t = tplById(cfgOf(n).template);
          const wiredPorts = new Set(W.wf.edges.filter(x => x.to === n.id).map(x => x.in));
          const miss = t.variables.filter(x => x.required !== false && x.key !== wiredVar(n) && !String(values[n.id].vars[x.key] || x.default || '').trim());
          const missFiles = t.attachments.filter(a => a.required && !a.has_default && !values[n.id].att[a.key]
            && !(a.keep_video ? wiredPorts.has('videos') : wiredPorts.has('images') || (a.video && wiredPorts.has('videos'))));
          if (miss.length) { $(`[data-askvar="${CSS.escape(n.id + '|' + miss[0].key)}"]`)?.focus(); return toast(`Hãy điền: ${miss.map(x => x.label).join(', ')}`, 'warn'); }
          if (missFiles.length) return toast(`Hãy chọn: ${missFiles.map(a => a.label).join(', ')}`, 'warn');
        }
        if ($('#wfKeepInputs').checked) {
          Object.entries(values).forEach(([id, v]) => { const n = nodeById(id); n.config = { ...cfgOf(n), ...v }; });
          renderCanvas();
          await save();
        }
        closeModal();
        doRun(values);
      }
    };
  }

  // Chọn template → lấy tỉ lệ / thời lượng / độ phân giải gợi ý của template.
  function applyTemplate(n) {
    const t = tplById(cfgOf(n).template);
    const opts = t ? Object.fromEntries(Object.entries(t.options || {}).filter(([k, val]) => ['aspect', 'duration', 'resolution'].includes(k) && val)) : {};
    // prompt đã sửa thuộc về template cũ → bỏ khi đổi template
    n.config = { ...cfgOf(n), ...opts, ...(t && t.video_engine ? { engine: t.video_engine } : {}), var_input: '', prompt_override: '', step_prompts: {} };
    renderCanvas();
  }

  // Prompt template sửa riêng cho block: key 'main' = prompt tạo video, còn lại = prompt của bước tạo ảnh
  function setFlowPrompt(n, key, text) {
    const cfg = cfgOf(n);
    if (key === 'main') n.config = { ...cfg, prompt_override: text };
    else {
      const steps = { ...(cfg.step_prompts || {}) };
      if (text) steps[key] = text; else delete steps[key];
      n.config = { ...cfg, step_prompts: steps };
    }
    renderCanvas(); renderInspector(); changed();
  }

  function openFlowEditor(key) {
    const n = nodeById(W.sel.id);
    const cfg = cfgOf(n);
    const t = tplById(cfg.template);
    const step = key === 'main' ? null : t.steps.find(x => x.key === key);
    const orig = step ? step.prompt : t.prompt;
    const cur = step ? ((cfg.step_prompts || {})[key] || orig) : (cfg.prompt_override || orig);
    openModal('PROMPT TEMPLATE', `${step ? step.label : 'Tạo video'} · ${t.name}`, `<div class="form">
      <p class="muted">Chỉ sửa cho block này — template gốc không đổi.${t.variables.length ? ` Giữ các biến ${t.variables.map(x => `<code>{${esc(x.key)}}</code>`).join(' ')} để app tự điền thông tin.` : ''}</p>
      <textarea id="wfFlowText" class="mono wf-flow-edit" rows="20">${esc(cur)}</textarea>
      <div class="modal-foot"><button class="btn ghost" id="wfFlowOrig" type="button">Lấy lại prompt gốc</button>
        <button class="btn primary" id="wfFlowSave" type="button">Lưu prompt</button></div></div>`);
    $('#modalBody').oninput = null;
    $('#modalBody').onclick = e => {
      if (e.target.id === 'wfFlowOrig') { $('#wfFlowText').value = orig; return; }
      if (e.target.id === 'wfFlowSave') {
        const text = $('#wfFlowText').value.trim();
        if (!text) return toast('Prompt không được để trống — bấm “Lấy lại prompt gốc”', 'warn');
        W.flowOpen.add(key);
        setFlowPrompt(n, key, text === String(orig).trim() ? '' : text);
        closeModal();
        toast('Đã lưu prompt cho block này', 'ok');
      }
    };
  }

  // Bộ chọn template dạng thẻ — giống cửa sổ "Chọn Template" ở trang Tạo video
  async function openTemplatePicker() {
    const n = nodeById(W.sel.id);
    await ensureTpl();
    const list = TPL.templates;
    const cats = (TPL.categories || []).filter(c => list.some(t => t.category === c.id));
    const chip = (key, label, count) => `<button class="chip-f" data-filter="${esc(key)}" type="button">${esc(label)}<span>${count}</span></button>`;
    const card = t => {
      const cat = cats.find(c => c.id === t.category);
      const o = t.options || {};
      const active = cfgOf(n).template === t.id;
      const thumb = t.has_thumb ? `<img src="/tpl/${encodeURIComponent(t.id)}/thumb" alt="" loading="lazy">`
        : `<div class="poster"><span class="poster-icon">🎬</span><b>${esc(t.name)}</b><small>Grok / Gemini Veo · ${esc(o.aspect || '')} · ${esc(o.duration || '')}</small></div>`;
      const files = t.attachments.length ? `<code>📎 ${t.attachments.length} ${t.attachments.some(a => a.keep_video) ? 'ảnh/video' : 'ảnh'} tham chiếu</code>` : '';
      return `<button class="tpl-card ${active ? 'active' : ''}" data-choice="${esc(t.id)}" type="button">
        <div class="tpl-thumb">${thumb}</div>
        <div class="meta"><div class="badges"><span class="badge ai">Video AI · Grok / Gemini</span>${cat ? `<span class="badge">${esc(cat.name)}</span>` : ''}
            ${t.user ? '<span class="badge">Của bạn</span>' : ''}${t.steps.length ? `<span class="badge">${t.steps.length + 1} bước</span>` : ''}</div>
          <b>${esc(t.name)}</b><small>${esc(t.description || '')}</small>
          ${t.variables.length || files ? `<div class="vars">${t.variables.map(x => `<code>{${esc(x.key)}}</code>`).join(' ')} ${files}</div>` : ''}
          <span class="use">${active ? '✓ Đang dùng' : 'Dùng template →'}</span></div></button>`;
    };
    openModal(`${list.length} TEMPLATE · ${cats.length} NHÓM`, 'Chọn Template', `<div class="chips tpl-chips">
        ${chip('all', 'Tất cả', list.length)}${list.some(t => t.user) ? chip('user', '★ Của bạn', list.filter(t => t.user).length) : ''}
        ${cats.map(c => chip(c.id, `${c.icon || ''} ${c.name}`, list.filter(t => t.category === c.id).length)).join('')}</div>
      <div class="tpl-grid wf-tpl-grid"></div>
      <div class="modal-foot"><button class="btn ghost" data-tpl-none type="button">Không dùng template</button>
        <button class="btn ghost" data-tpl-new type="button">+ Tạo template mới</button></div>`);
    const draw = filter => {
      $$('#modalBody .tpl-chips .chip-f').forEach(c => c.classList.toggle('active', c.dataset.filter === filter));
      const items = list.filter(t => filter === 'all' || (filter === 'user' ? t.user : t.category === filter));
      $('#modalBody .wf-tpl-grid').innerHTML = items.map(card).join('') || '<div class="empty">Nhóm này chưa có template.</div>';
    };
    draw('all');
    $('#modalBody').oninput = null;
    $('#modalBody').onclick = e => {
      const c = e.target.closest('.chip-f');
      if (c) return draw(c.dataset.filter);
      if (e.target.closest('[data-tpl-new]')) { closeModal(); return openTemplateEditor('new'); }
      const pick = e.target.closest('.tpl-card');
      if (!pick && !e.target.closest('[data-tpl-none]')) return;
      n.config = { ...cfgOf(n), template: pick ? pick.dataset.choice : '' };
      if (pick) applyTemplate(n);
      closeModal(); renderCanvas(); renderInspector(); changed();
    };
  }

  async function openTemplateEditor(mode) {
    const n = nodeById(W.sel.id);
    const cfg = cfgOf(n);
    await ensureTpl();
    const cur = tplById(cfg.template);
    const src = mode === 'new' ? null : cur;
    const fieldOpts = key => spec('gen_video').fields.find(f => f.key === key).options;
    const d = {
      id: mode === 'edit' && cur ? cur.id : '',
      name: src ? (mode === 'copy' ? `${src.name} (bản sao)` : src.name) : '',
      description: src ? src.description : '',
      category: src ? src.category : 'general',
      prompt: src ? src.prompt : (cfg.prompt || ''),
      options: src ? { aspect: cfg.aspect, duration: cfg.duration, resolution: cfg.resolution, ...src.options }
        : { aspect: cfg.aspect, duration: cfg.duration, resolution: cfg.resolution },
      variables: src ? src.variables.map(x => ({ ...x })) : [],
      attachments: src ? src.attachments.map(a => ({ ...a, required: mode === 'copy' && a.has_default ? false : a.required })) : [],
    };
    const keys = () => [...new Set([...d.prompt.matchAll(/\{(\w+)\}/g)].map(m => m[1]))];
    const varRow = key => {
      let x = d.variables.find(v => v.key === key);
      if (!x) { x = { key, label: key, default: '', required: true }; d.variables.push(x); }
      return `<div class="wf-tv-row"><code>{${esc(key)}}</code>
        <input data-tv="${esc(key)}|label" value="${esc(x.label || '')}" placeholder="Tên hiển thị khi nhập">
        <input data-tv="${esc(key)}|default" value="${esc(x.default || '')}" placeholder="Giá trị mặc định">
        <label class="check"><input type="checkbox" data-tv="${esc(key)}|required" ${x.required !== false ? 'checked' : ''}> Bắt buộc</label></div>`;
    };
    const drawVars = () => {
      const ks = keys();
      $('#tplVars').innerHTML = ks.length ? ks.map(varRow).join('')
        : '<div class="muted">Chưa có biến. Viết <code>{TenBien}</code> trong prompt (vd. <code>{SanPham}</code>, <code>{Slogan}</code>) — mỗi biến thành 1 ô người dùng nhập.</div>';
    };
    const drawAtt = () => {
      $('#tplAtt').innerHTML = d.attachments.map((a, i) => `<div class="wf-tv-row att"><b>${i + 1}</b>
        <input data-ta="${i}|label" value="${esc(a.label || '')}" placeholder="Tên ô ảnh (vd. Ảnh sản phẩm)">
        <input data-ta="${i}|prompt" value="${esc(a.prompt || '')}" placeholder="Cách dùng ảnh (tiếng Anh), vd. keep this exact product packaging">
        <label class="check"><input type="checkbox" data-ta="${i}|required" ${a.required ? 'checked' : ''}> Bắt buộc</label>
        <button class="btn ghost sm" data-ta-rm="${i}" type="button">✕</button></div>`).join('')
        || '<div class="muted">Không bắt buộc. Ảnh nối vào cổng “Ảnh tham chiếu” sẽ khớp lần lượt với các ô ảnh này.</div>';
    };
    const sel = (key, val, options) => `<select data-k="${key}">${options.map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(val) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
    openModal('TEMPLATE VIDEO', mode === 'edit' ? `Sửa template · ${d.name}` : 'Tạo template video', `<div class="form wf-tpl-editor">
      <div class="grid2"><label class="field"><span>Tên template *</span><input data-k="name" value="${esc(d.name)}" placeholder="vd. Quảng cáo phân bón 15 giây"></label>
        <label class="field"><span>Nhóm</span>${sel('category', d.category, (TPL.categories || []).map(c => ({ value: c.id, label: c.name })))}</label></div>
      <label class="field"><span>Mô tả ngắn</span><input data-k="description" value="${esc(d.description)}" placeholder="Template dùng để…"></label>
      <div class="grid3"><label class="field"><span>Tỉ lệ</span>${sel('aspect', d.options.aspect, fieldOpts('aspect'))}</label>
        <label class="field"><span>Thời lượng</span>${sel('duration', d.options.duration, fieldOpts('duration'))}</label>
        <label class="field"><span>Độ phân giải</span>${sel('resolution', d.options.resolution, fieldOpts('resolution'))}</label></div>
      <label class="field"><span>Prompt * — viết <code>{TenBien}</code> ở chỗ cần điền thông tin</span>
        <textarea data-k="prompt" rows="10" placeholder="Create a vertical 9:16 advertising video for {SanPham}. Voice-over: “{Slogan}”…">${esc(d.prompt)}</textarea></label>
      <div class="wf-plan-sec"><small>THÔNG TIN TEMPLATE YÊU CẦU (tự nhận từ prompt)</small><div id="tplVars"></div></div>
      <div class="wf-plan-sec"><small>Ô ẢNH THAM CHIẾU</small><div id="tplAtt"></div>
        <button class="btn ghost sm" id="tplAddAtt" type="button">+ Thêm ô ảnh</button></div>
      <div class="modal-foot">${mode === 'edit' ? '<button class="btn danger" id="tplDel" type="button">Xoá template</button>' : ''}
        <span class="muted">Lưu ở thư mục dữ liệu của app · dùng được cả ở trang Tạo video</span>
        <button class="btn primary" id="tplSave" type="button">Lưu template</button></div></div>`);
    drawVars(); drawAtt();
    let timer = null;
    $('#modalBody').oninput = e => {
      const k = e.target.dataset.k, tv = e.target.dataset.tv, ta = e.target.dataset.ta;
      const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
      if (k && ['aspect', 'duration', 'resolution'].includes(k)) d.options[k] = val;
      else if (k) d[k] = val;
      if (k === 'prompt') { clearTimeout(timer); timer = setTimeout(drawVars, 400); }
      if (tv) { const [key, prop] = tv.split('|'); const x = d.variables.find(v => v.key === key); if (x) x[prop] = val; }
      if (ta) { const [i, prop] = ta.split('|'); d.attachments[+i][prop] = val; }
    };
    $('#modalBody').onclick = async e => {
      if (e.target.id === 'tplAddAtt') { d.attachments.push({ label: '', prompt: '', required: false }); drawAtt(); return; }
      const rm = e.target.closest('[data-ta-rm]');
      if (rm) { d.attachments.splice(+rm.dataset.taRm, 1); drawAtt(); return; }
      if (e.target.id === 'tplDel') {
        if (!confirm(`Xoá template “${d.name}”? Block đang dùng template này sẽ chuyển về prompt tự do.`)) return;
        const res = await api('wf_delete_video_template', d.id);
        if (!res.ok) return toast(res.error, 'error');
        await ensureTpl(true);
        W.wf.nodes.filter(x => x.type === 'gen_video' && cfgOf(x).template === d.id).forEach(x => { x.config = { ...cfgOf(x), template: '' }; });
        closeModal(); renderCanvas(); renderInspector(); changed();
        return toast('Đã xoá template', 'ok');
      }
      if (e.target.id === 'tplSave') {
        clearTimeout(timer);
        const ks = keys();
        const res = await api('wf_save_video_template', { ...d, variables: d.variables.filter(v => ks.includes(v.key)) });
        if (!res.ok) return toast(res.error, 'error');
        await ensureTpl(true);
        n.config = { ...cfgOf(n), template: res.template.id };
        applyTemplate(n);
        closeModal(); renderInspector(); changed();
        toast(`Đã lưu template “${res.template.name}”`, 'ok');
      }
    };
  }

  async function openPinPicker() {
    const n = nodeById(W.sel.id);
    const cfg = cfgOf(n);
    let chosen = [...(cfg.pin_urls || [])];
    let results = chosen.map(url => ({ url, thumb: pinThumb(url) }));
    const MAX = 6;
    const draw = () => {
      $('#wfPinGrid').innerHTML = results.length ? results.map(r => `<button class="wf-pin-cell ${chosen.includes(r.url) ? 'on' : ''}" data-url="${esc(r.url)}" type="button" title="${esc(r.alt || '')}">
          <img src="${esc(r.thumb)}" alt="" referrerpolicy="no-referrer" loading="lazy"><i>${chosen.includes(r.url) ? chosen.indexOf(r.url) + 1 : ''}</i></button>`).join('')
        : '<div class="muted">Nhập từ khoá (nên dùng tiếng Anh) rồi bấm Tìm. Ảnh chỉ dùng để tham khảo bố cục, màu sắc — không sao chép.</div>';
      $('#wfPinCount').textContent = `Đã chọn ${chosen.length}/${MAX}`;
    };
    openModal('PINTEREST', 'Tìm ảnh tham khảo', `<div class="form">
      <div class="row wf-pin-search"><input id="wfPinQ" value="${esc(cfg.pin_keyword || '')}" placeholder="vd. fertilizer bag product photo green field">
        <button class="btn primary" id="wfPinGo" type="button">Tìm</button></div>
      <div id="wfPinGrid" class="wf-pin-grid"></div>
      <div class="modal-foot"><span class="muted" id="wfPinCount"></span><button class="btn ghost" id="wfPinClear" type="button">Bỏ chọn (tự tìm khi chạy)</button>
        <button class="btn primary" id="wfPinUse" type="button">Dùng ảnh đã chọn</button></div></div>`);
    draw();
    const search = async () => {
      const q = $('#wfPinQ').value.trim();
      if (!q) return toast('Nhập từ khoá tìm ảnh', 'warn');
      const btn = $('#wfPinGo'); btn.disabled = true; btn.textContent = 'Đang tìm…';
      $('#wfPinGrid').innerHTML = '<div class="muted">Đang tìm trên Pinterest (trình duyệt ẩn, khoảng 10–20 giây)…</div>';
      const res = await api('search_pinterest', q, 24);
      btn.disabled = false; btn.textContent = 'Tìm';
      if (!res.ok) { $('#wfPinGrid').innerHTML = `<div class="bad">${esc(res.error)}</div>`; return; }
      results = [...chosen.map(url => results.find(r => r.url === url) || { url, thumb: pinThumb(url) }),
        ...res.results.filter(r => !chosen.includes(r.url))];
      draw();
    };
    $('#modalBody').onkeydown = e => { if (e.key === 'Enter' && e.target.id === 'wfPinQ') search(); };
    $('#modalBody').oninput = null;
    $('#modalBody').onclick = e => {
      if (e.target.id === 'wfPinGo') return search();
      const cell = e.target.closest('[data-url]');
      if (cell) {
        const url = cell.dataset.url;
        if (chosen.includes(url)) chosen = chosen.filter(u => u !== url);
        else if (chosen.length >= MAX) return toast(`Chọn tối đa ${MAX} ảnh`, 'warn');
        else chosen.push(url);
        return draw();
      }
      if (e.target.id === 'wfPinClear') { chosen = []; return draw(); }
      if (e.target.id === 'wfPinUse') {
        const q = $('#wfPinQ').value.trim();
        n.config = { ...cfgOf(n), pin_urls: chosen, pin_keyword: q || cfg.pin_keyword || '' };
        closeModal(); renderCanvas(); renderInspector(); changed();
      }
    };
  }

  async function doRun(overrides) {
    started(await api('wf_run', W.wf.id, overrides), 'Workflow đang chạy tuần tự — bạn có thể làm việc khác');
  }

  function started(res, message) {
    if (!res.ok) return toast(res.error, 'error');
    W.taskId = res.result.task;
    W.logs = [];
    W.running = [...new Set([...W.running, W.wf.id])];
    W.tab = 'progress';
    toast(message, 'ok');
    renderSteps();
    renderTray();
    renderInspector();
  }

  // Chạy thử 1 block: xem trước block nào chạy thật / dùng lại kết quả cũ, rồi chạy.
  async function testNode(id) {
    if (!W.wf || !nodeById(id)) return;
    if (isRunning()) return toast('Workflow đang chạy — chờ xong hoặc bấm Dừng', 'warn');
    if (!(await save())) return;
    const target = nodeById(id);
    let fresh = false;
    const name = nid => { const n = nodeById(nid); return `<span class="nm">${n ? esc(spec(n.type).name) : ''}<small class="mono muted">${esc(nid)}</small></span>`; };
    const draw = async () => {
      const res = await api('wf_test_plan', W.wf.id, id, fresh);
      if (!res.ok) { closeModal(); return toast(res.error, 'error'); }
      const p = res.plan;
      const execNodes = p.execute.map(nodeById).filter(Boolean);
      const warns = [];
      if (execNodes.some(n => n.type === 'fb_post' || n.type === 'fb_schedule')) warns.push('Có block đăng bài sẽ chạy thật: bài được đăng/hẹn giờ lên Fanpage (vẫn dừng chờ bạn duyệt nếu bật “Duyệt trước khi đăng”).');
      if (execNodes.some(n => n.type === 'fb_ad')) warns.push('Block Tạo quảng cáo sẽ tạo quảng cáo thật ở trạng thái TẠM DỪNG (không tốn tiền cho tới khi bạn bật).');
      if (execNodes.some(n => ['gen_image', 'gen_video', 'ai_text'].includes(n.type))) warns.push('Block tạo ảnh/video/AI sẽ dùng lượt của tài khoản model đã chọn.');
      const asks = execNodes.filter(n => (n.type.startsWith('input_') && cfgOf(n).ask) || (n.type === 'gen_video' && cfgOf(n).template && cfgOf(n).ask_vars));
      if (asks.length) warns.push(`Block ${asks.map(n => n.id).join(', ')} chạy với input / thông tin template đang lưu (không hỏi lại).`);
      $('#modalBody').innerHTML = `<div class="form wf-test-plan">
        <div class="wf-plan-sec"><small>SẼ CHẠY (${p.execute.length})</small>${p.execute.map(nid => `<div class="wf-plan-row run"><i>▶</i>${name(nid)}${nid === id ? '<span class="camp-st approved">block thử</span>' : ''}</div>`).join('')}</div>
        ${Object.keys(p.cached).length ? `<div class="wf-plan-sec"><small>DÙNG LẠI KẾT QUẢ CŨ (${Object.keys(p.cached).length})</small>${Object.entries(p.cached).map(([nid, run]) => `<div class="wf-plan-row cached"><i>↺</i>${name(nid)}<span class="muted mono">lần chạy ${esc(run)}</span></div>`).join('')}</div>` : ''}
        ${p.execute.length > 1 && !fresh ? '<p class="muted">Các block phía trước chưa có kết quả dùng lại được (chưa chạy, đã đổi cấu hình hoặc file đã bị xoá) nên sẽ chạy kèm.</p>' : ''}
        ${warns.map(w => `<div class="wf-issue warn">! ${esc(w)}</div>`).join('')}
        <label class="check"><input type="checkbox" id="wfTestFresh" ${fresh ? 'checked' : ''}> Chạy lại cả các block phía trước (không dùng kết quả cũ)</label>
        <div class="modal-foot"><button class="btn primary" id="wfTestGo" type="button">▶ Chạy thử</button></div></div>`;
    };
    openModal('CHẠY THỬ BLOCK', `${spec(target.type).name} · ${id}`, '<div class="muted">Đang kiểm tra kết quả cũ…</div>', true);
    $('#modalBody').oninput = null;
    $('#modalBody').onclick = async e => {
      if (e.target.id === 'wfTestFresh') { fresh = e.target.checked; await draw(); return; }
      if (e.target.closest('#wfTestGo')) {
        e.target.closest('#wfTestGo').disabled = true;
        const res = await api('wf_run_node', W.wf.id, id, fresh);
        closeModal();
        started(res, `Đang chạy thử “${spec(target.type).name}”`);
      }
    };
    await draw();
  }

  async function stopRun() {
    if (!confirm('Dừng lần chạy hiện tại? (block đã xong vẫn giữ kết quả)')) return;
    await api('wf_cancel', W.wf.id);
    toast('Đang dừng…', 'warn');
  }

  function onEvent(event, data) {
    if (event === 'workflow_tasks') {
      W.running = [...new Set(data.tasks.filter(t => t.status === 'queued' || t.status === 'running').map(t => t.workflow))];
      $('#sbWfRunning').classList.toggle('hidden', !W.running.length);
      if (W.inited && !$('#page-workflow').classList.contains('hidden')) renderSteps();
      if (W.inited && !$('#page-wf-list').classList.contains('hidden')) showList();
      return;
    }
    if (!W.wf) return;
    if (event === 'workflow_run' && data.workflow === W.wf.id) {
      W.run = data;
      if (Object.values(data.nodes).some(s => s.status === 'waiting')) W.tab = 'progress';
      if (['done', 'error', 'cancelled'].includes(data.status)) finishRun(data);
      if ($('#page-workflow').classList.contains('hidden')) return;
      $$('#wfNodes .wf-node').forEach(el => { const n = nodeById(el.dataset.node); if (n) el.outerHTML = nodeHtml(n); });
      renderIssueMarks();
      renderEdges();
      if (W.tab !== 'history') renderTray();
      return;
    }
    if (event === 'workflow_log' && data.task === W.taskId) {
      W.logs.push(data);
      const log = $('#wfLog');
      if (log) {
        log.insertAdjacentHTML('beforeend', `<div class="ln ${esc(data.level || 'info')}"><span class="t">${esc(data.time)}</span><i class="dot"></i><span class="msg">${esc(data.message)}</span></div>`);
        log.scrollTop = log.scrollHeight;
      }
      return;
    }
    if (event === 'workflow_progress' && data.task === W.taskId) {
      const bar = $('#wfProgress i');
      if (bar) { bar.style.width = `${data.pct}%`; $('#wfProgressText').textContent = `${Math.round(data.pct)}% · ${data.status || ''}`; }
    }
  }

  async function finishRun(data) {
    if (!data.test) W.wf.last_run = { id: data.id, status: data.status, at: data.ended_at };
    W.running = W.running.filter(id => id !== W.wf.id);
    const runs = await api('wf_runs', W.wf.id);
    if (runs.ok) W.runs = runs.runs;
    if (data.status === 'done') { W.tab = 'results'; toast(data.test ? 'Chạy thử block xong — xem tab Kết quả' : `Workflow “${W.wf.name}” đã chạy xong`, 'ok'); }
    else if (data.status === 'error') toast(`Workflow lỗi: ${data.error}`, 'error');
    renderSteps();
    renderTray();
    renderInspector();
    refreshList();
  }

  // ================================================================ khay dưới: tiến trình · kết quả · lịch sử · kiểm tra
  // ================================================================ hộp thoại xem kết quả (ảnh lớn / phát video)
  const V = { items: [], index: 0 };

  document.addEventListener('click', e => {
    const fig = e.target.closest('.wf-out[data-media]');
    if (!fig) return;
    e.preventDefault();
    const scope = fig.closest('.wf-tray-body, #wfInspector, #modalBody') || document;
    // chỉ các ô đang hiện (bỏ ô trong "Kết quả từng block" đang thu gọn → không lặp file)
    const figs = [...scope.querySelectorAll('.wf-out[data-media]')].filter(f => f === fig || !f.closest('details:not([open])'));
    openViewer(figs.map(f => ({ kind: f.dataset.media, src: f.dataset.src, name: f.dataset.name,
      label: (f.closest('.wf-res-node') || { querySelector: () => null }).querySelector('small')?.textContent || '' })), figs.indexOf(fig));
  });

  function openViewer(items, index) {
    let el = $('#wfViewer');
    if (!el) {
      el = document.createElement('div');
      el.id = 'wfViewer';
      el.className = 'wf-viewer';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      document.body.appendChild(el);
      el.addEventListener('click', e => {
        if (e.target === el || e.target.classList.contains('wf-viewer-stage') || e.target.closest('[data-v-close]')) return closeViewer();
        if (e.target.closest('[data-v-prev]')) return viewerStep(-1);
        if (e.target.closest('[data-v-next]')) return viewerStep(1);
        const th = e.target.closest('[data-v-thumb]');
        if (th) { V.index = +th.dataset.vThumb; return drawViewer(); }
        if (e.target.closest('[data-v-folder]') && W.wf && W.run) api('wf_open_run', W.wf.id, W.run.id);
      });
    }
    V.items = items;
    V.index = Math.max(0, index);
    el.classList.remove('hidden');
    document.addEventListener('keydown', viewerKeys);
    drawViewer();
  }

  function drawViewer() {
    const it = V.items[V.index];
    const many = V.items.length > 1;
    $('#wfViewer').innerHTML = `<div class="wf-viewer-top">
        <div><b>${esc(it.name)}</b>${it.label ? `<small>${esc(it.label)}</small>` : ''}</div>
        <span class="muted">${many ? `${V.index + 1} / ${V.items.length}` : ''}</span>
        <div class="row">${W.run ? '<button class="btn ghost sm" data-v-folder type="button">📂 Mở thư mục</button>' : ''}
          <button class="icon-btn round" data-v-close type="button" title="Đóng (Esc)">✕</button></div></div>
      <div class="wf-viewer-stage">
        ${many ? '<button class="wf-viewer-nav prev" data-v-prev type="button" title="Trước (←)">‹</button>' : ''}
        ${it.kind === 'video' ? `<video src="${esc(it.src)}" controls autoplay playsinline></video>` : `<img src="${esc(it.src)}" alt="${esc(it.name)}">`}
        ${many ? '<button class="wf-viewer-nav next" data-v-next type="button" title="Sau (→)">›</button>' : ''}</div>
      ${many ? `<div class="wf-viewer-strip">${V.items.map((x, i) => `<button class="${i === V.index ? 'on' : ''}" data-v-thumb="${i}" type="button">
          ${x.kind === 'video' ? `<video src="${esc(x.src)}#t=0.5" muted preload="metadata"></video><i>▶</i>` : `<img src="${esc(x.src)}" alt="">`}</button>`).join('')}</div>` : ''}`;
  }

  function viewerStep(d) {
    V.index = (V.index + d + V.items.length) % V.items.length;
    drawViewer();
  }

  function viewerKeys(e) {
    if (e.key === 'Escape') { e.stopPropagation(); closeViewer(); }
    else if (e.key === 'ArrowLeft' && V.items.length > 1) viewerStep(-1);
    else if (e.key === 'ArrowRight' && V.items.length > 1) viewerStep(1);
  }

  function closeViewer() {
    const el = $('#wfViewer');
    if (el) { el.innerHTML = ''; el.classList.add('hidden'); }  // xoá nội dung để dừng video
    document.removeEventListener('keydown', viewerKeys);
  }

  function outputsHtml(outputs) {
    const items = [];
    Object.values(outputs || {}).forEach(v => (Array.isArray(v) ? v : [v]).forEach(x => items.push(x)));
    return `<div class="wf-outs">${items.map(o => {
      if (!o) return '';
      if (o.kind === 'video' || o.kind === 'image') {  // bấm để mở hộp thoại xem ảnh / phát video
        return `<figure class="wf-out" data-media="${o.kind}" data-src="${esc(o.url)}" data-name="${esc(o.name)}" title="Bấm để xem">
          <div class="wf-out-thumb">${o.kind === 'video' ? `<video src="${esc(o.url)}#t=0.5" muted preload="metadata"></video>` : `<img src="${esc(o.url)}" alt="" loading="lazy">`}
            <span class="wf-out-badge">${o.kind === 'video' ? '▶' : '⤢'}</span></div><figcaption>${esc(o.name)}</figcaption></figure>`;
      }
      if (o.kind === 'file') return `<figure class="wf-out file"><span>📄</span><figcaption>${esc(o.name)}</figcaption></figure>`;
      if (o.kind === 'text') return `<div class="wf-out-text">${esc(String(o.text).slice(0, 1200))}</div>`;
      if (o.kind === 'post') return `<div class="wf-out-post"><b>${o.queued ? `⏰ Đã lên lịch ${esc(o.when)} — sửa / đăng ngay ở Quản lý bài đăng` : o.scheduled ? `🗓 Đã hẹn giờ ${esc(o.when)}` : '📣 Đã đăng'}</b> · ${esc(o.page)}
        ${o.url ? `<a href="${esc(o.url)}" data-ext>${esc(o.url)}</a>` : `<span class="mono">${esc(o.post_id)}</span>`}<small>${esc(o.caption || '')}</small></div>`;
      return '';
    }).join('')}</div>`;
  }

  function renderTray() {
    const tray = $('#wfTray');
    if (!W.wf) { tray.innerHTML = ''; return; }
    const errors = W.issues.filter(i => i.level === 'error').length;
    const tabs = [['progress', 'Tiến trình'], ['results', 'Kết quả'], ['history', `Lịch sử chạy (${W.runs.length})`], ['issues', `Kiểm tra${errors ? ` (${errors})` : ''}`]];
    const run = W.run;
    let body = '';
    if (W.tab === 'progress') {
      const total = run ? run.order.filter(id => run.nodes[id].status !== 'cached').length : 0;
      const done = run ? run.order.filter(id => ['done', 'error', 'skipped'].includes(run.nodes[id].status)).length : 0;
      const pct = run ? (run.status === 'done' ? 100 : Math.round(100 * done / Math.max(1, total))) : 0;
      const waiting = run ? run.order.filter(id => run.nodes[id].status === 'waiting' && run.nodes[id].approval) : [];
      body = (waiting.map(id => {
        const a = run.nodes[id].approval;
        const files = (a.files || []).map(p => {
          const url = `/media/${p.replace(/\\/g, '/').split('/_workflows/')[1] ? `_workflows/${p.replace(/\\/g, '/').split('/_workflows/')[1]}` : ''}`;
          return /\.(mp4|mov|webm|m4v)$/i.test(p) ? `<video src="${esc(url)}" muted preload="metadata"></video>` : `<img src="${esc(url)}" alt="">`;
        }).join('');
        return `<div class="wf-approve" data-approval="${esc(id)}">
          <div class="wf-approve-head"><b>⏳ Chờ bạn duyệt ${a.kind === 'schedule' ? `hẹn giờ đăng lúc ${esc(a.when)}` : 'đăng bài'}</b>
            <span>Fanpage: <b>${esc(a.page)}</b> · block <span class="mono">${esc(id)}</span></span></div>
          <div class="wf-approve-body"><div class="wf-approve-media">${files || '<span class="muted">Bài chỉ có chữ</span>'}</div>
            <label class="field"><span>Caption (sửa được trước khi đăng)</span><textarea data-approve-caption rows="5">${esc(a.caption || '')}</textarea></label></div>
          <div class="row wf-approve-actions"><span class="muted">Bài sẽ ${a.kind === 'schedule' ? 'được hẹn giờ' : 'được đăng công khai'} ngay khi bạn bấm Đồng ý.</span>
            <button class="btn ghost" data-reject="${esc(id)}" type="button">Không đăng</button>
            <button class="btn primary" data-approve="${esc(id)}" type="button">${a.kind === 'schedule' ? '🗓 Đồng ý hẹn giờ' : '📣 Đồng ý đăng'}</button></div></div>`;
      }).join('')) + (run ? `<div class="wf-run-head"><span class="camp-st ${esc(run.status === 'done' ? 'approved' : run.status)}">${esc(STATUS[run.status] || run.status)}</span>
          <b>${run.test ? `Chạy thử ${esc(nodeById(run.test.target) ? spec(nodeById(run.test.target).type).name : run.test.target)} · ` : 'Lần chạy '}${esc(run.id)}</b><span class="muted">${run.started_at ? esc(fmtTime(run.started_at)) : ''}</span>
          <div class="wf-progress" id="wfProgress"><i style="width:${pct}%"></i></div><small class="muted" id="wfProgressText">${pct}% · ${done}/${total} block</small>
          <button class="btn ghost sm" data-open-run="${esc(run.id)}" type="button">Mở thư mục</button></div>
        <div class="wf-tray-split">
          <div class="wf-prog-nodes">${run.order.map((id, i) => {
            const n = nodeById(id); const st = run.nodes[id]; const s = n ? spec(n.type) : { icon: '?', name: id };
            return `<button class="wf-prog-node st-${esc(st.status)}" data-goto="${esc(id)}" type="button" title="${esc(st.error || '')}"><span>${i + 1}</span><i>${esc(s.icon)}</i><b>${esc(s.name)}</b><small>${esc(STATUS[st.status] || st.status)}</small></button>`;
          }).join('')}</div>
          <div class="log mono wf-log" id="wfLog">${W.logs.map(l => `<div class="ln ${esc(l.level || 'info')}"><span class="t">${esc(l.time)}</span><i class="dot"></i><span class="msg">${esc(l.message)}</span></div>`).join('')
            || '<div class="muted">Nhật ký chi tiết hiện khi bạn chạy workflow trong phiên này.</div>'}</div></div>`
        : '<div class="empty">Chưa chạy lần nào — bấm ▶ Chạy (bước 03).</div>');
    } else if (W.tab === 'results') {
      const nodes = run ? run.order.filter(id => run.nodes[id].status === 'done' && Object.keys(run.nodes[id].outputs || {}).length && nodeById(id)) : [];
      const outNode = run && run.test && nodes.includes(run.test.target) ? run.test.target : nodes.find(id => nodeById(id).type === 'output');
      const shown = outNode ? [outNode] : nodes.filter(id => !nodeById(id).type.startsWith('input_'));
      const block = id => `<div class="wf-res-node"><small>${esc(spec(nodeById(id).type).name)} · ${esc(id)}</small>${outputsHtml(run.nodes[id].outputs)}</div>`;
      body = shown.length ? shown.map(block).join('')
        + (outNode ? `<details class="camp-more"><summary>Kết quả từng block</summary>${nodes.filter(id => id !== outNode).map(block).join('')}</details>` : '')
        : '<div class="empty">Chưa có kết quả.</div>';
    } else if (W.tab === 'history') {
      body = W.runs.length ? `<div class="wf-runs">${W.runs.map(r => `<div class="wf-run ${run && run.id === r.id ? 'on' : ''}">
          <span class="camp-st ${esc(r.status === 'done' ? 'approved' : r.status)}">${esc(STATUS[r.status] || r.status)}</span>
          <b class="mono">${esc(r.id)}</b>${r.test ? `<span class="wf-test-tag">Chạy thử ${esc(nodeById(r.test.target) ? spec(nodeById(r.test.target).type).name : r.test.target)} · ${esc(r.test.target)}</span>` : ''}<span class="muted">${esc(fmtTime(r.started_at))}</span>${r.error ? `<small class="bad">${esc(r.error)}</small>` : ''}
          <span class="row"><button class="btn ghost sm" data-view-run="${esc(r.id)}" type="button">Xem kết quả</button><button class="btn ghost sm" data-open-run="${esc(r.id)}" type="button">Thư mục</button></span></div>`).join('')}</div>`
        : '<div class="empty">Chưa có lần chạy nào.</div>';
    } else {
      body = W.issues.length ? W.issues.map(i => `<div class="wf-issue ${i.level}" ${i.node ? `data-goto="${esc(i.node)}"` : ''}>${i.level === 'error' ? '✕' : '!'} ${i.node ? `<b>${esc(i.node)}</b> ` : ''}${esc(i.message)}</div>`).join('')
        : '<div class="wf-issue ok">✓ Workflow hợp lệ — sẵn sàng chạy.</div>';
    }
    tray.innerHTML = `<div class="wf-tray-tabs">${tabs.map(([k, l]) => `<button class="camp-tab ${W.tab === k ? 'on' : ''}" data-tray="${k}" type="button">${l}</button>`).join('')}</div>
      <div class="wf-tray-body">${body}</div>`;
    tray.onclick = async e => {
      const ext = e.target.closest('[data-ext]'); if (ext) { e.preventDefault(); api('open_url', ext.getAttribute('href')); return; }
      const ok = e.target.closest('[data-approve]'), no = e.target.closest('[data-reject]');
      if (ok || no) {
        const id = (ok || no).dataset.approve || (ok || no).dataset.reject;
        const caption = tray.querySelector(`[data-approval="${CSS.escape(id)}"] [data-approve-caption]`).value;
        if (ok && !confirm(`Xác nhận ${run.nodes[id].approval.kind === 'schedule' ? 'hẹn giờ đăng' : 'đăng công khai'} lên “${run.nodes[id].approval.page}”?`)) return;
        (ok || no).disabled = true;
        const res = await api('wf_approve', W.wf.id, run.id, id, !!ok, caption);
        if (!res.ok) { (ok || no).disabled = false; return toast(res.error, 'error'); }
        toast(ok ? 'Đã duyệt — đang đăng…' : 'Đã bỏ qua bài này', ok ? 'ok' : 'warn');
        return;
      }
      const t = e.target.closest('[data-tray]'); if (t) { W.tab = t.dataset.tray; renderTray(); return; }
      const g = e.target.closest('[data-goto]'); if (g) { select({ type: 'node', id: g.dataset.goto }); return; }
      const o = e.target.closest('[data-open-run]'); if (o) { api('wf_open_run', W.wf.id, o.dataset.openRun); return; }
      const v = e.target.closest('[data-view-run]');
      if (v) { await loadRun(v.dataset.viewRun); W.tab = 'results'; renderCanvas(); renderTray(); renderInspector(); }
    };
    const log = $('#wfLog'); if (log) log.scrollTop = log.scrollHeight;
  }

  function renderAll() {
    renderSteps();
    renderCanvas();
    renderInspector();
    renderTray();
    if (W.wf) { $('#wfSaved').textContent = W.dirty ? 'Chưa lưu…' : '✓ Đã lưu'; $('#wfSaved').className = `wf-saved ${W.dirty ? 'dirty' : ''}`; }
    else $('#wfSaved').textContent = '';
  }

  // ================================================================ màn hình Danh sách workflow
  const L = { bound: false, list: [], presets: [] };
  const GROUP_ICON = { input: 'g-input', ai: 'g-ai', create: 'g-create', output: 'g-output' };

  async function showList() {
    if (!W.inited) await init();
    const res = await api('wf_list');
    L.list = res.workflows;
    L.presets = res.presets || W.presets;
    W.running = res.running;
    $('#sbWfCount').textContent = L.list.length;
    $('#sbWfRunning').classList.toggle('hidden', !W.running.length);
    if (!L.bound) bindList();
    renderList();
  }

  function bindList() {
    L.bound = true;
    ['wflSearch', 'wflStatus', 'wflSort'].forEach(id => $(`#${id}`).addEventListener(id === 'wflSearch' ? 'input' : 'change', renderList));
    $('#wflNew').onclick = () => { navigate('workflow'); setTimeout(openNewDialog, 50); };
    $('#wflPresets').onclick = async e => {
      const p = e.target.closest('[data-preset]');
      if (!p) return;
      const res = await api('wf_from_preset', p.dataset.preset);
      if (!res.ok) return toast(res.error, 'error');
      toast(`Đã tạo “${res.workflow.name}” từ mẫu`, 'ok');
      openInEditor(res.workflow.id);
    };
    $('#wflGrid').onclick = async e => {
      const card = e.target.closest('[data-wf]');
      if (!card) return;
      const id = card.dataset.wf;
      const act = e.target.closest('[data-act]')?.dataset.act || 'open';
      if (act === 'open') return openInEditor(id);
      if (act === 'run') return openInEditor(id, true);
      if (act === 'dup') {
        const res = await api('wf_duplicate', id);
        if (!res.ok) return toast(res.error, 'error');
        toast('Đã nhân bản workflow', 'ok');
        return showList();
      }
      if (act === 'stop') { await api('wf_cancel', id); toast('Đang dừng…', 'warn'); return; }
      if (act === 'del') {
        const wf = L.list.find(w => w.id === id);
        if (!confirm(`Xoá workflow “${wf.name}”?\n(Kết quả các lần chạy trước vẫn được giữ trong thư mục video.)`)) return;
        const res = await api('wf_delete', id);
        if (!res.ok) return toast(res.error, 'error');
        if (W.wf && W.wf.id === id) W.wf = null;
        toast('Đã xoá workflow', 'ok');
        showList();
      }
    };
  }

  async function openInEditor(id, run = false) {
    W.wantId = id;
    navigate('workflow');
    await W.showing;
    if (run) startRun();
  }

  function renderList() {
    const q = $('#wflSearch').value.trim().toLowerCase();
    const st = $('#wflStatus').value;
    const sort = $('#wflSort').value;
    const status = w => (W.running.includes(w.id) ? 'running' : w.last_run ? w.last_run.status : 'never');
    let items = L.list.filter(w => (!q || `${w.name} ${w.desc}`.toLowerCase().includes(q)) && (!st || status(w) === st || (st === 'error' && status(w) === 'cancelled')));
    items = items.sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name, 'vi')
      : sort === 'run' ? ((b.last_run || {}).at || '').localeCompare((a.last_run || {}).at || '')
        : (b.updated_at || '').localeCompare(a.updated_at || ''));
    const today = new Date().toISOString().slice(0, 10);
    const stat = (label, value, cls = '') => `<div class="camp-stat ${cls}"><small>${label}</small><b>${value}</b></div>`;
    $('#wflStats').innerHTML = stat('Tổng workflow', L.list.length, 'main') + stat('Đang chạy', W.running.length)
      + stat('Chạy hôm nay', L.list.filter(w => ((w.last_run || {}).at || '').startsWith(today)).length)
      + stat('Lần chạy gần nhất lỗi', L.list.filter(w => (w.last_run || {}).status === 'error').length, L.list.some(w => (w.last_run || {}).status === 'error') ? 'warn' : '')
      + stat('Tổng lần chạy', L.list.reduce((s, w) => s + (w.runs || 0), 0));
    $('#wflGrid').innerHTML = items.length ? items.map(w => {
      const s = status(w);
      const chain = (w.types || []).slice(0, 9).map(t => {
        const sp = W.meta.types[t];
        return sp ? `<i class="${GROUP_ICON[sp.group]}" title="${esc(sp.name)}">${esc(sp.icon)}</i>` : '';
      }).join('<span class="wfl-arrow">›</span>') + ((w.types || []).length > 9 ? '<span class="muted">…</span>' : '');
      return `<div class="wfl-card ${s}" data-wf="${esc(w.id)}" role="button" tabindex="0">
        <div class="wfl-chain">${chain || '<span class="muted">Chưa có block</span>'}</div>
        <div class="wfl-body"><b title="${esc(w.name)}">${esc(w.name)}</b>
          <p>${esc(w.desc || 'Chưa có mô tả')}</p>
          <div class="wfl-meta"><span>${w.nodes} block · ${w.edges || 0} dây</span><span>${w.runs || 0} lần chạy</span>
            <span>Sửa ${esc(fmtTime(w.updated_at))}</span></div>
          <div class="wfl-status"><span class="camp-st ${esc(s === 'done' ? 'approved' : s === 'never' ? '' : s)}">${s === 'never' ? 'Chưa chạy' : esc(STATUS[s] || s)}</span>
            ${w.last_run && s !== 'running' ? `<small class="muted">${esc(fmtTime(w.last_run.at))}</small>` : ''}</div></div>
        <div class="wfl-actions">
          <button class="btn ghost sm" data-act="open" type="button">Mở</button>
          ${s === 'running' ? '<button class="btn danger sm" data-act="stop" type="button">■ Dừng</button>' : '<button class="btn primary sm" data-act="run" type="button">▶ Chạy</button>'}
          <button class="btn ghost sm sq" data-act="dup" type="button" title="Nhân bản">⧉</button>
          <button class="btn ghost sm sq" data-act="del" type="button" title="Xoá">🗑</button></div>
      </div>`;
    }).join('') : `<div class="empty">${L.list.length ? 'Không có workflow khớp bộ lọc.' : 'Chưa có workflow nào — bấm “+ Tạo workflow” hoặc chọn một mẫu bên dưới.'}</div>`;
    $('#wflPresets').innerHTML = (L.presets || []).map(p => `<button class="wfl-preset" data-preset="${esc(p.id)}" type="button">
      <b>⚡ ${esc(p.name)}</b><small>${esc(p.desc)}</small><span>${p.nodes} block · Dùng mẫu này →</span></button>`).join('');
  }

  window.WorkflowStudio = { show, showList, onEvent };
})();
