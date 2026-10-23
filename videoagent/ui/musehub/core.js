/* Studio Muse AI — dây chuyền Muse (backend app/muse_hub/, API mhub_*):
   thanh trên (dự án, trạng thái tài khoản, Chạy tiếp / Dừng tất cả / Thư mục) + 5 tab:
   Studio (soạn lệnh + hàng đợi) · Tư liệu · Kịch bản (storyboard — ui/studio.js) · Thư viện (+ ghép video) · Tài khoản.
   Tài khoản = profile trình duyệt đã gán Muse ở màn Profile trình duyệt. Dùng helper của app.js: $, $$, api, esc, toast… */
/* Tách theo tab: core.js (nạp đầu tiên) + studio.js, script.js, progress.js, sample.js, post.js, ladi.js, assets.js, library.js, accounts.js, events.js — dùng chung window.MH. */
(() => {
  'use strict';
  const MH = window.MH = window.MH || {};  // namespace chung của Studio Muse AI (ui/musehub/*.js)
  // hàm ở file khác — gọi qua MH lúc chạy
  const renderStudio = (...a) => MH.renderStudio(...a);
  const renderDetected = (...a) => MH.renderDetected(...a);
  const renderQueue = (...a) => MH.renderQueue(...a);
  const paintDetail = (...a) => MH.paintDetail(...a);
  const renderScript = (...a) => MH.renderScript(...a);
  const renderGroups = (...a) => MH.renderGroups(...a);
  const renderProgress = (...a) => MH.renderProgress(...a);
  const renderSample = (...a) => MH.renderSample(...a);
  const showPost = (...a) => MH.showPost(...a);
  const renderPostJobs = (...a) => MH.renderPostJobs(...a);
  const renderLadi = (...a) => MH.renderLadi(...a);
  const renderAssets = (...a) => MH.renderAssets(...a);
  const loadLibrary = (...a) => MH.loadLibrary(...a);
  const paintMerge = (...a) => MH.paintMerge(...a);
  const renderAccounts = (...a) => MH.renderAccounts(...a);
  const bind = (...a) => MH.bind(...a);

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
  const FILTERS = [['all', 'Tất cả'], ['queued', 'Chờ'], ['processing', 'Đang chạy'], ['succeeded', 'Xong'], ['failed', 'Lỗi'], ['cancelled', 'Đã huỷ']];
  // ------------------------------------------------------------ tab Kịch bản
  const sel = (id, list, cur) => `<select id="${id}">${list.map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  const parseVideos = text => String(text || '').split(/\n\s*\n/).map(b => b.split('\n').map(x => x.trim()).filter(Boolean)).filter(v => v.length);
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
  // ------------------------------------------------------------ tab Tiến trình: theo dõi mọi việc Muse đang / sắp / vừa làm
  const mmss = ms => { const s = Math.max(0, Math.round(ms / 1000)); return s >= 3600 ? `${Math.floor(s / 3600)}:${pad2(Math.floor(s / 60) % 60)}:${pad2(s % 60)}` : `${Math.floor(s / 60)}:${pad2(s % 60)}`; };
  const startOfDay = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const projName = id => (H.s.projects.find(p => p.id === (id || 'default')) || {}).name || 'Mặc định';
  const taskLabel = t => (t.role === 'storyboard' ? 'Storyboard' : t.scene ? `Cảnh ${t.scene}` : t.kind === 'video' ? 'Video' : 'Ảnh');
  const firstLine = t => String(t.prompt || '').split('\n')[0];
  // ------------------------------------------------------------ tab Video mẫu: phân tích video mẫu → kịch bản tương tự
  const nearestDur = secs => DURS.filter(d => d[0] !== 'per_scene').reduce((best, d) => (Math.abs(+d[0] - secs) < Math.abs(+best[0] - secs) ? d : best))[0];
  const CLOSE = [['close', 'Bám sát — cùng cấu trúc, nhịp'], ['inspire', 'Lấy ý tưởng — sáng tạo hơn']];
  // ------------------------------------------------------------ tab Hậu kỳ: ghép video + lồng tiếng + chuyển cảnh + hậu kỳ AI
  const POST_DEF = { name: '', aspect: '9:16', audio: 'tts', voice: 'vi-VN-HoaiMyNeural', rate: '+0%', subtitles: true, bgm: true,
    bgm_volume: 0.12, transition: 'smoothleft', transition_duration: 0.5, transition_sound: 'none', transition_volume: 0.15,
    post_ai: false, post_style: 'basic', post_subs: true, post_audio: true, logo: '', logo_url: '', logo_corner: 'tr' };
  const postSave = () => { try { localStorage.setItem('va.mhub.post', JSON.stringify({ clips: H.post.clips, form: H.post.form })); } catch { /* bỏ qua */ } };
  (() => { H.post.form = { ...POST_DEF }; try { const d = JSON.parse(localStorage.getItem('va.mhub.post') || 'null'); if (d) { H.post.clips = d.clips || []; H.post.form = { ...POST_DEF, ...(d.form || {}) }; } } catch { /* bỏ qua */ } })();
  const fileName = p => String(p || '').split(/[\\/]/).pop();
  const lineText = s => { const m = String(s || '').match(/Lời thoại:\s*[“"]([^”"]+)[”"]/); return m ? m[1].trim() : ''; };
  const sceneLabel = it => (it.role === 'storyboard' ? 'Storyboard' : it.scene ? `Cảnh ${it.scene}` : 'Video');
  const sceneLine = c => (c.visual && c.line ? `${c.visual} — Lời thoại: “${c.line}”` : c.visual || `Lời thoại: “${c.line}”`);
  // ------------------------------------------------------------ tab Tư liệu
  // ảnh gửi kèm 1 lệnh Muse cho 1 prompt (giống app/muse_hub.compose_images): người mẫu → nhân vật có tên → 1 ảnh luân phiên
  const nameHit = (name, text) => new RegExp(`(^|[^\\p{L}\\d])${name.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\p{L}\\d])`, 'u').test(` ${text.toLowerCase()} `);
  const libSelVideos = () => H.lib.sel.filter(p => (H.lib.items.find(i => i.path === p) || {}).video);

  Object.assign(MH, { show, update, renderAll, accountSummary, renderTop, TABS, METHODS, DURS, VOICES, MOTIONS, GSTATUS, H, fmt, day, prompts, proj, projTasks, FILTERS, sel, parseVideos, GFILTERS, gcat, projGroups, gNo, mmss, startOfDay, projName, taskLabel, firstLine, nearestDur, CLOSE, POST_DEF, postSave, fileName, lineText, sceneLabel, sceneLine, nameHit, libSelVideos });
  window.MuseHubPage = { show, update };
})();
