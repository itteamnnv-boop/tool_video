/* Studio — ý tưởng → storyboard (sửa được) → làm từng cảnh (ảnh khung đầu → video AI) → ghép video dài
   (dùng chung helper của app.js: $, $$, api, esc, toast, state, profileOptions, siteOf).
   createStudioPage(CFG) tạo 1 màn: Studio (chọn model tự do) và Studio Muse AI (mọi bước dùng Muse — backend khoá model). */
function createStudioPage(CFG) {
  'use strict';
  const MUSE = !!CFG.muse;
  const museField = label => `<div class="field"><span>${label}</span><div class="st-muse-lock" title="Studio Muse AI dùng Muse cho mọi bước">🔒 Meta · Muse AI</div></div>`;

  const S = { meta: null, projects: [], cur: null, draft: null, dirty: false, tasks: {}, logs: [], progress: null, refs: [],
    batch: false, pendingRender: false };
  const STATUS = { draft: 'Nháp', running: 'Đang chạy', ready: 'Sẵn sàng làm video', done: 'Đã có video', error: 'Lỗi',
    cancelled: 'Đã dừng', interrupted: 'Bị gián đoạn' };
  const ideaLines = text => String(text || '').split('\n').map(x => x.replace(/^[\s\-•]+/, '').trim()).filter(x => x.length >= 10);
  const SCENE_STATUS = { frame_running: 'Đang tạo ảnh…', frame: 'Có ảnh — chờ clip', clip_running: 'Đang tạo clip…', done: '✓ Xong', error: 'Lỗi' };
  const clone = o => JSON.parse(JSON.stringify(o));

  async function show() {
    S.cast = null;  // tải lại danh sách nhân vật / layout (có thể vừa sửa ở màn Nhân vật & Layout)
    if (!S.meta) {
      const res = await api(CFG.api + 'meta');
      if (!res.ok) return toast(res.error, 'error');
      S.meta = res.meta;
    }
    await loadList();
    render();
  }

  async function loadList() {
    const res = await api(CFG.api + 'list');
    S.projects = res.ok ? res.projects : [];
    if (S.cur) S.cur = S.projects.find(p => p.id === S.cur.id) || null;
    if (S.cur && !S.dirty) S.draft = clone(S.cur);
  }

  // ------------------------------------------------------------ khung trang
  function render() {
    S.pendingRender = false;
    const inside = S.cur || S.view === 'new';
    $(CFG.body).innerHTML = `<div class="st-page">
      ${inside ? `<div class="st-crumbs"><button class="btn ghost sm" data-back type="button">← Tất cả dự án</button>
        <span class="muted">/</span><b>${esc(S.cur ? S.cur.name : 'Dự án mới')}</b></div>` : ''}
      <section class="st-main">${S.cur ? projectHtml() : S.view === 'new' ? newHtml() : listHtml()}</section></div>`;
    bind();
    refreshOpts();
  }

  // ------------------------------------------------------------ màn quản lý dự án
  const LIST_FILTERS = [['all', 'Tất cả'], ['running', 'Đang chạy'], ['todo', 'Chưa có video'], ['done', 'Đã có video']];
  function listedProjects() {
    const q = (S.q || '').trim().toLowerCase();
    const f = S.filter || 'all';
    return S.projects.filter(p => (!q || `${p.name} ${p.idea}`.toLowerCase().includes(q))
      && (f === 'all' || (f === 'running' && p.running) || (f === 'todo' && !p.running && !p.final_url) || (f === 'done' && p.final_url)));
  }
  function gridHtml() {
    const list = listedProjects();
    if (!list.length) return `<div class="empty">${S.projects.length ? 'Không có dự án khớp bộ lọc.' : 'Chưa có dự án — bấm “+ Dự án mới”.'}</div>`;
    return list.map(p => {
      const scenes = p.scenes || [];
      const thumb = (scenes.find(s => s.frame_url) || {}).frame_url;
      const clips = scenes.filter(s => s.clip_url).length;
      const secs = p.final_url ? Math.round((p.final || {}).duration || 0) : scenes.reduce((a, s) => a + (+s.seconds || 0), 0);
      const status = p.running ? 'running' : p.status;
      const date = String(p.created_at || '').slice(0, 10).split('-').reverse().join('/');
      return `<div class="st-pcard ${p.running ? 'running' : ''}">
        <button class="st-pthumb" data-open="${esc(p.id)}" type="button" title="Mở dự án">
          ${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy">` : '<span>🎬</span>'}
          <i class="st-pbadge ${esc(status)}">${esc(p.running ? 'Đang chạy' : STATUS[p.status] || p.status)}</i>
          ${p.final_url ? '<i class="st-pfinal">🎞 Có video</i>' : ''}</button>
        <div class="st-pbody">
          <button class="st-pname" data-open="${esc(p.id)}" type="button" title="${esc(p.name)}">${esc(p.name)}</button>
          <p class="st-pidea">${esc(p.idea || '')}</p>
          <div class="st-pmeta"><span>🎬 ${clips}/${scenes.length} cảnh</span>${secs ? `<span>⏱ ~${secs}s</span>` : ''}
            <span>▭ ${esc((p.options || {}).aspect || '9:16')}</span>${date ? `<span>📅 ${esc(date)}</span>` : ''}</div>
          <div class="st-pact"><button class="btn ghost sm" data-open="${esc(p.id)}" type="button">Mở</button>
            ${p.running ? '' : `<button class="btn ghost sm st-pdel" data-del-id="${esc(p.id)}" type="button" title="Xoá dự án">🗑</button>`}</div>
        </div></div>`;
    }).join('');
  }
  function listHtml() {
    const unfinished = S.projects.filter(p => !p.running && !p.final_url).length;
    const live = S.projects.filter(p => p.running).length;
    return `<div class="card st-lhead">
        <div class="st-lhead-top"><div><b class="st-ltitle">Dự án ${CFG.label}</b>${MUSE ? ' <span class="st-muse-badge">🔒 chỉ dùng Muse AI</span>' : ''} <span class="muted">${S.projects.length} dự án${live ? ` · <span class="st-live">●</span> ${live} đang chạy` : ''}</span></div>
          <div class="row st-lhead-act">
            ${unfinished ? `<button class="btn ghost" data-resume-all type="button" title="Viết storyboard / làm cảnh còn thiếu / ghép cho mọi dự án chưa có video">▶ Chạy tiếp ${unfinished} dự án</button>` : ''}
            <button class="btn primary" data-new type="button">+ Dự án mới</button></div></div>
        <div class="row st-lfilter"><input id="stSearch" type="search" placeholder="🔍 Tìm theo tên / ý tưởng…" value="${esc(S.q || '')}">
          <div class="st-chips">${LIST_FILTERS.map(([k, label]) => `<button class="chip-f ${(S.filter || 'all') === k ? 'active' : ''}" data-filter="${k}" type="button">${label}</button>`).join('')}</div></div>
      </div>
      <div class="st-grid" id="stGrid">${gridHtml()}</div>`;
  }

  // ------------------------------------------------------------ dialog Cài đặt dự án (nút ⚙ cạnh tên dự án)
  function optsDialogHtml() {
    const run = S.cur.running;
    return `${optionsHtml(S.draft.options, run)}
      <div class="modal-foot st-optfoot">${run ? '<small class="muted">Dự án đang chạy — chờ xong hoặc bấm Dừng để sửa cài đặt.</small>' : ''}
        <button class="btn ghost" data-act="opts-close" type="button">Đóng</button>
        ${run ? '' : '<button class="btn primary" data-act="opts-save" type="button">💾 Lưu cài đặt</button>'}</div>`;
  }

  function openOpts() {
    openModal(`DỰ ÁN · ${S.cur.name}`, 'Cài đặt dự án', `<div id="stOptsDlg" class="st-optdlg">${optsDialogHtml()}</div>`, true);
    bind($('#stOptsDlg'));
  }

  // Trang vẽ lại → vẽ lại dialog đang mở cho khớp (trừ khi đang gõ trong ô chữ của dialog, để không mất con trỏ)
  function refreshOpts() {
    const dlg = document.getElementById('stOptsDlg');
    if (!dlg) return;
    if (!S.cur) return closeModal();
    const a = document.activeElement;
    const typing = dlg.contains(a) && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && !['checkbox', 'radio', 'range'].includes(a.type)));
    if (!typing) dlg.innerHTML = optsDialogHtml();
  }

  function selectOptions(list, cur) {
    return list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(l)}</option>`).join('');
  }

  function profileSelect(id, site, cur, label) {
    return site && state.profiles && state.profileSites[site]
      ? `<label class="field"><span>${label}</span><select data-opt="${id}">${profileOptions(site, cur)}</select></label>` : '';
  }

  // Ràng buộc prompt: dự án cũ chưa có "bans" = cấm đủ cả 4 (giống app/studio.py negative_line)
  const bansOf = o => Array.isArray(o.bans) ? o.bans : (S.meta.bans || []).map(b => b.value);
  const BAN_EN = { text: 'no text', subtitles: 'no subtitles', logos: 'no logos', watermark: 'no watermark' };
  function negativeLine(o) {
    const parts = (S.meta.bans || []).map(b => b.value).filter(k => bansOf(o).includes(k)).map(k => BAN_EN[k]);
    const line = parts.length ? parts.join(', ').replace(/^n/, 'N') + '.' : '';
    let extra = (o.negative_extra || '').trim();
    if (extra) extra = extra[0].toUpperCase() + extra.slice(1) + (/[.!?]$/.test(extra) ? '' : '.');
    return [line, extra].filter(Boolean).join(' ');
  }

  // Logo thương hiệu (hiện khi bỏ tick "Không logo"): dự án đã có → lưu ngay lên máy chủ; dự án mới → gửi kèm lúc tạo
  function logoHtml(o, dis) {
    const url = S.cur ? S.cur.logo_url : '';
    const name = !S.cur && S.newLogo ? S.newLogo.split(/[\\/]/).pop() : '';
    const has = Boolean(url || name);
    return `<div class="st-logo">
      <div class="st-logo-thumb">${url ? `<img src="${esc(url)}" alt="Logo">` : `<span>${esc(name || 'Chưa có logo')}</span>`}</div>
      <div class="st-logo-side">
        <div class="row"><button class="btn ghost sm" data-logo-pick type="button" ${dis}>${has ? '↻ Đổi logo' : '⬆ Tải logo lên'}</button>
          ${has ? `<button class="btn ghost sm" data-logo-rm type="button" ${dis}>Bỏ logo</button>` : ''}</div>
        <label class="field"><span>Đóng logo lên video khi ghép</span><select data-opt="logo_overlay" ${dis || (has ? '' : 'disabled')}>${selectOptions((S.meta.logo_corners || []).map(x => [x.value, x.label]), o.logo_overlay || 'none')}</select></label>
        <small class="muted">${has ? 'Logo được gửi kèm model ảnh để vẽ vào khung đầu (bao bì, biển hiệu, đồng phục). Ảnh đã tạo trước đó → bấm ↻ Ảnh. Đóng logo lên góc là logo thật, chính xác 100%, áp dụng khi ghép / ghép lại.'
          : 'Nên dùng PNG nền trong suốt.'}</small>
      </div></div>`;
  }

  // Nhân vật / layout cố định (màn Nhân vật & Layout) — chọn hay không tuỳ dự án; tối đa 3 nhân vật, 1 layout
  const MAX_CAST = 3;
  function castHtml(o, dis) {
    if (!S.cast) {
      window.CastPage.items().then(items => { S.cast = items; refreshOpts(); if (!document.getElementById('stOptsDlg')) render(); });
      return '<div class="st-wide st-cast"><b>🧑 Nhân vật &amp; layout cố định</b><small class="muted">Đang tải…</small></div>';
    }
    const chars = (o.cast_characters || []).map(id => S.cast.character.find(x => x.id === id)).filter(Boolean);
    const layout = S.cast.layout.find(x => x.id === o.cast_layout);
    const combo = (S.cast.combo || []).find(x => x.id === o.cast_combo);
    const slot = (tab, label, items, none) => `<button class="st-slot ${items.length ? 'on' : ''}" data-cast-pick="${tab}" type="button" ${dis}>
        <span class="st-slot-k">${label}</span>
        <span class="st-slot-v"><span class="st-slot-imgs">${items.length ? items.map(castThumb).join('') : '<i>∅</i>'}</span>
          <span class="st-slot-n">${items.length ? items.map(x => esc(x.name)).join(', ') : none}</span></span></button>`;
    return `<div class="st-wide st-cast">
      <div class="st-cast-head"><b>🧑 Nhân vật &amp; layout cố định</b><small class="muted">tuỳ chọn — không chọn thì AI tự nghĩ</small>
        <button class="btn ghost sm" data-cast-pick="${(S.cast.combo || []).length ? 'combo' : 'character'}" type="button" ${dis}>✎ Chọn…</button></div>
      <div class="st-slots">
        ${(S.cast.combo || []).length ? slot('combo', 'Bộ kết hợp', combo ? [combo] : [], 'Không dùng') : ''}
        ${slot('character', `Nhân vật · ${chars.length}/${MAX_CAST}`, chars, 'AI tự nghĩ')}
        ${slot('layout', 'Layout / bối cảnh', layout ? [layout] : [], 'Không dùng')}
      </div>
      <small class="muted">Sửa nhân vật / layout ở màn <button class="link" data-goto-cast type="button">Nhân vật &amp; Layout</button> — dự án dùng bản mới nhất khi tạo ảnh.</small></div>`;
  }

  const castThumb = x => {
    const u = (x.starred[0] || x.images.find(i => i.exists) || {}).url;
    return u ? `<img src="${esc(u)}" alt="" loading="lazy">` : `<i>${x.kind === 'character' ? '🧑' : x.kind === 'combo' ? '🎭' : '🏞'}</i>`;
  };

  // Chọn nhân vật / layout / bộ kết hợp: lớp phủ riêng (nằm trên cả hộp Cài đặt dự án)
  const CAST_TABS = [['combo', '🎭 Bộ kết hợp', 'Nhân vật + layout + ảnh dàn cảnh — chọn là điền sẵn nhân vật và layout.'],
    ['character', '🧑 Nhân vật', `Tối đa ${MAX_CAST}: mô tả chép nguyên vào storyboard, ảnh ⭐ gửi kèm khi tạo ảnh khung đầu.`],
    ['layout', '🏞 Layout / bối cảnh', 'Mọi cảnh diễn ra trong bối cảnh này.']];

  function pickCast(kind, id) {
    const o = S.draft.options;
    if (kind === 'combo') {  // bộ kết hợp: điền sẵn nhân vật + layout của bộ
      const combo = (S.cast.combo || []).find(x => x.id === id);
      S.draft.options = combo ? { ...o, cast_combo: combo.id, cast_characters: (combo.characters || []).slice(0, MAX_CAST), cast_layout: combo.layout || '' }
        : { ...o, cast_combo: '' };
    } else if (kind === 'character') {
      const set = new Set(o.cast_characters || []);
      if (set.has(id)) set.delete(id); else if (set.size < MAX_CAST) set.add(id);
      S.draft.options = { ...o, cast_characters: [...set] };
    } else S.draft.options = { ...o, cast_layout: id };
    if (S.cur) markDirty();
    render();
    drawCastPicker();
  }

  function castPickerHtml() {
    const o = S.draft.options;
    const tabs = CAST_TABS.filter(([k]) => k !== 'combo' || (S.cast.combo || []).length);
    if (!tabs.some(([k]) => k === S.castTab)) S.castTab = tabs[0][0];
    const tab = S.castTab, q = (S.castQ || '').trim().toLowerCase();
    const chars = o.cast_characters || [];
    const current = tab === 'combo' ? o.cast_combo : o.cast_layout;
    const selected = x => (tab === 'character' ? chars.includes(x.id) : current === x.id);
    const all = S.cast[tab] || [];
    const items = all.filter(x => !q || `${x.name} ${x.summary || ''} ${x.description || ''}`.toLowerCase().includes(q));
    const card = x => {
      const on = selected(x);
      const full = tab === 'character' && !on && chars.length >= MAX_CAST;
      return `<button class="cp-item ${on ? 'on' : ''}" data-cp="${esc(x.id)}" type="button" ${full ? 'disabled title="Đã đủ 3 nhân vật — bỏ bớt để chọn"' : ''}>
        <span class="cp-img">${castThumb(x)}${on ? '<b class="cp-check">✓</b>' : ''}</span>
        <b class="cp-name">${esc(x.name)}</b><small>${esc(x.summary || x.description || x.idea || '')}</small></button>`;
    };
    const none = tab === 'character' || q ? '' : `<button class="cp-item cp-none ${current ? '' : 'on'}" data-cp="" type="button">
        <span class="cp-img"><i>∅</i>${current ? '' : '<b class="cp-check">✓</b>'}</span><b class="cp-name">Không dùng</b>
        <small>${tab === 'combo' ? 'Tự chọn nhân vật và layout' : 'AI tự nghĩ bối cảnh'}</small></button>`;
    const grid = !all.length ? `<div class="empty">Chưa có mục nào — tạo ở màn <button class="link" data-goto-cast type="button">Nhân vật &amp; Layout</button>.</div>`
      : items.length ? items.map(card).join('') : '<div class="empty">Không có mục khớp tìm kiếm.</div>';
    const nameOf = (kind, id) => ((S.cast[kind] || []).find(x => x.id === id) || {}).name || '';
    const count = k => (k === 'character' ? `${chars.length}/${MAX_CAST}` : (k === 'combo' ? o.cast_combo : o.cast_layout) ? '1' : '');
    return `<div class="cp-card" role="dialog" aria-label="Chọn nhân vật và layout">
      <div class="cp-head"><b>Nhân vật &amp; layout cố định</b><button class="cp-x" data-cp-close type="button" aria-label="Đóng">✕</button></div>
      <div class="cp-tabs">${tabs.map(([k, label]) => `<button class="cp-tab ${k === tab ? 'on' : ''}" data-cp-tab="${k}" type="button">${label}${count(k) ? ` <span>${count(k)}</span>` : ''}</button>`).join('')}
        <input id="cpSearch" type="search" placeholder="🔍 Tìm…" value="${esc(S.castQ || '')}"></div>
      <p class="cp-hint muted">${CAST_TABS.find(([k]) => k === tab)[2]}</p>
      <div class="cp-grid">${none}${grid}</div>
      <div class="cp-foot"><small class="muted">${[o.cast_combo && `Bộ: ${esc(nameOf('combo', o.cast_combo))}`,
        chars.length && `Nhân vật: ${chars.map(id => esc(nameOf('character', id))).join(', ')}`,
        o.cast_layout && `Layout: ${esc(nameOf('layout', o.cast_layout))}`].filter(Boolean).join(' · ') || 'Chưa chọn gì — AI tự nghĩ nhân vật và bối cảnh'}</small>
        <button class="btn ghost sm" data-cp-clear type="button">Bỏ chọn tất cả</button>
        <button class="btn primary" data-cp-close type="button">Xong</button></div></div>`;
  }

  function drawCastPicker() {
    const el = document.getElementById('stCastPicker');
    if (!el) return;
    const focus = document.activeElement && document.activeElement.id === 'cpSearch';
    el.innerHTML = castPickerHtml();
    if (focus) { const s = el.querySelector('#cpSearch'); s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  }

  function openCastPicker(tab) {
    S.castTab = tab; S.castQ = '';
    let el = document.getElementById('stCastPicker');
    if (!el) {
      el = document.createElement('div');
      el.id = 'stCastPicker';
      el.className = 'cp-overlay';
      document.body.appendChild(el);
      const close = () => { el.remove(); document.removeEventListener('keydown', onKey, true); };
      const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
      document.addEventListener('keydown', onKey, true);
      el.addEventListener('click', e => {
        if (e.target === el) return close();
        const t = e.target.closest('button');
        if (!t || t.disabled) return;
        if (t.dataset.cpClose !== undefined) return close();
        if (t.dataset.gotoCast !== undefined) { close(); closeModal(); return navigate('cast'); }
        if (t.dataset.cpTab) { S.castTab = t.dataset.cpTab; S.castQ = ''; return drawCastPicker(); }
        if (t.dataset.cpClear !== undefined) {
          S.draft.options = { ...S.draft.options, cast_combo: '', cast_characters: [], cast_layout: '' };
          if (S.cur) markDirty();
          render(); return drawCastPicker();
        }
        if (t.dataset.cp !== undefined) return pickCast(S.castTab, t.dataset.cp);
      });
      el.addEventListener('input', e => { if (e.target.id === 'cpSearch') { S.castQ = e.target.value; drawCastPicker(); } });
    }
    drawCastPicker();
  }

  // HyperFrames (đồ hoạ động dựng trên máy): cần Node.js 22+ và ffprobe; lần đầu app tự cài gói npm
  const hfReady = () => S.hf && S.hf.node_ok && S.hf.ffprobe;
  function hfStatusText() {
    if (!S.hf) {
      api('hyperframes_status').then(r => { if (r.ok) { S.hf = r.status; refreshOpts(); if (!document.getElementById('stOptsDlg')) render(); } });
      return 'Đang kiểm tra Node.js / FFmpeg…';
    }
    const h = S.hf;
    if (!h.node_ok) return `⚠ Cần Node.js 22 trở lên (máy đang: ${esc(h.node || 'chưa cài')}) — tải ở nodejs.org rồi mở lại app.`;
    if (!h.ffprobe) return '⚠ Cần FFmpeg có ffprobe trong PATH (Windows: winget install Gyan.FFmpeg) rồi mở lại app.';
    return `✓ Node.js ${esc(h.node)} · FFmpeg sẵn sàng · ${h.installed ? `HyperFrames ${esc(h.version)} đã cài`
      : `lần chạy đầu app tự cài HyperFrames ${esc(h.version)} (cần internet)`}. Model viết HTML + GSAP, máy bạn dựng video (~3 phút cho 1 phút video); lỗi thì quay về phụ đề thường.`;
  }

  // Hậu kỳ AI sau bước ghép (mặc định Claude trình duyệt): công tắc lớn bật / tắt + 2 phần phụ đề / âm thanh
  function postHtml(o, dis) {
    const m = S.meta;
    const on = Boolean(o.post_ai);
    const model = m.text_models.find(x => x.id === (MUSE ? 'muse_browser' : o.post_model || 'claude_browser')) || m.text_models[0];
    return `<div class="st-wide st-post ${on ? 'on' : ''}">
      <label class="st-post-head"><input type="checkbox" class="st-switch" data-opt="post_ai" ${on ? 'checked' : ''} ${dis}>
        <b>✨ Hậu kỳ AI sau bước ghép</b><span class="st-post-state">${on ? 'ĐANG BẬT' : 'ĐANG TẮT'}</span></label>
      <small class="muted">Model chat (mặc định <b>Claude trình duyệt</b>) đọc lời dẫn rồi chọn từ khoá để tô nổi trên phụ đề, gắn hiệu ứng âm thanh vào đúng từ, viết câu hook đầu video và chọn mức nhạc nền. App tự áp dụng khi ghép; model lỗi thì vẫn ghép bình thường.</small>
      ${on ? `<div class="st-post-body">
        ${MUSE ? museField('Model hậu kỳ') : `<label class="field"><span>Model hậu kỳ</span><select data-opt="post_model" ${dis}>${m.text_models.map(x => `<option value="${esc(x.id)}" ${model && x.id === model.id ? 'selected' : ''}>${esc(x.name)}${x.ready ? '' : ' — chưa có khoá'}</option>`).join('')}</select></label>`}
        ${profileSelect('post_profile', model && model.site, o.post_profile, 'Profile model hậu kỳ')}
        <label class="field st-wide"><span>Kiểu hậu kỳ</span><select data-opt="post_style" ${dis}>${selectOptions((m.post_styles || []).map(x => [x.value, x.label]), o.post_style || 'basic')}</select></label>
        ${o.post_style === 'hyperframes' ? `<small class="st-wide st-hf ${hfReady() ? 'ok' : ''}">${hfStatusText()}</small>` : ''}
        <label class="check st-wide"><input type="checkbox" data-opt="post_subs" ${o.post_subs !== false ? 'checked' : ''} ${dis}> <span><b>Phụ đề nổi bật</b> — tô vàng + phóng to từ khoá, chữ bật lên từng dòng, hook ở đầu video</span></label>
        <label class="check st-wide"><input type="checkbox" data-opt="post_audio" ${o.post_audio !== false ? 'checked' : ''} ${dis}> <span><b>Âm thanh nổi bật</b> — hiệu ứng (pop, ding, impact…) đúng lúc nói từ khoá, nhạc nền tự nhỏ khi có lời</span></label>
        ${o.post_subs !== false && !o.subtitles ? '<small class="warn-text st-wide">Phụ đề đang tắt — bật “Phụ đề” để dùng phụ đề nổi bật.</small>' : ''}
      </div>` : ''}
    </div>`;
  }

  // 🎬 Video tham khảo: dự án đang mở → S.draft.ref_video; form Dự án mới → S.newRefVideo
  const rvGet = () => (S.cur ? (S.draft || {}).ref_video : S.newRefVideo) || null;
  const rvSet = v => { if (S.cur) S.draft.ref_video = v; else S.newRefVideo = v; };
  const VISION = id => id === 'gemini_browser' || id === 'gemini_api' || String(id).startsWith('api:');
  function refVideoHtml(o, dis) {
    const m = S.meta;
    const rv = rvGet();
    const model = MUSE ? 'muse_browser' : S.rvModel || 'gemini_browser';
    const sheet = rv && (rv.sheet_url || (S.cur && S.cur.ref_video_url));
    return `<div class="st-wide st-refvid"><div class="row st-refvid-head"><b>🎬 Video tham khảo</b>
        <small class="muted">tuỳ chọn — dán link hoặc chọn file video để phân tích hook, cấu trúc, nhịp, phong cách làm ý tưởng</small></div>
      <label class="check"><input type="checkbox" data-opt="ref_video_use" ${o.ref_video_use ? 'checked' : ''} ${dis} ${rv ? '' : 'disabled'}>
        Dùng video tham khảo khi viết storyboard ${rv ? '' : '<small class="muted">(phân tích video trước)</small>'}</label>
      <div class="row st-refvid-src"><input id="stRvSrc" placeholder="Dán link YouTube / TikTok / Facebook / Instagram… hoặc chọn file" value="${esc((rv && rv.source) || S.rvSource || '')}" ${dis}>
        <button class="btn ghost sm" data-rv-pick type="button" ${dis}>📁 Chọn file</button>
        <button class="btn primary sm" data-rv-go type="button" ${dis}>🔍 Phân tích</button></div>
      <div class="grid2"><label class="field"><span>Model phân tích ${VISION(model) ? '<small class="muted">· xem cả hình</small>' : '<small class="warn-text">· chỉ đọc tiêu đề / mô tả / phụ đề</small>'}</span>
          ${MUSE ? '<div class="st-muse-lock">🔒 Meta · Muse AI</div>' : `<select data-rv-model ${dis}>${m.text_models.map(x => `<option value="${esc(x.id)}" ${x.id === model ? 'selected' : ''}>${VISION(x.id) ? '👁 ' : ''}${esc(x.name)}</option>`).join('')}</select>`}</label>
        <label class="field"><span>Cách dùng</span><select data-opt="ref_video_mode" ${dis}>${selectOptions((m.ref_video_modes || []).map(x => [x.value, x.label]), o.ref_video_mode || 'inspire')}</select></label></div>
      ${rv ? `<div class="st-refvid-res">${sheet ? `<img src="${esc(sheet)}" alt="Khung hình chính của video tham khảo">` : ''}
        <div class="st-refvid-brief"><div class="row"><b>${esc(rv.title || 'Video tham khảo')}</b><small class="muted">${Math.round(rv.duration || 0)} giây${rv.vision ? ' · đã xem hình' : ' · chỉ đọc chữ'}</small>
          ${dis ? '' : '<button class="link" data-rv-clear type="button">Bỏ video</button>'}</div>
          <textarea data-rv-brief rows="9" ${dis} title="Sửa được — storyboard dùng nguyên văn phần này">${esc(rv.brief || '')}</textarea></div></div>` : ''}
      <small class="muted">Model 👁 xem được ảnh khung hình (Gemini trình duyệt / API, Claude / OpenAI API); model khác chỉ đọc tiêu đề, mô tả, phụ đề. Video từ link chỉ dùng để phân tích, app không lưu lại. Storyboard được dặn không chép nguyên văn lời thoại, thương hiệu, nhân vật của video tham khảo.</small>
    </div>`;
  }

  function optionsHtml(o, locked) {
    const m = S.meta;
    const textModel = m.text_models.find(x => x.id === o.model) || m.text_models[0];
    const img = m.image_engines[o.image_engine] || {};
    const vid = m.video_engines[o.video_engine] || {};
    const dis = locked ? 'disabled' : '';
    return `<div class="st-opts">
      ${refVideoHtml(o, dis)}
      ${castHtml(o, dis)}
      <label class="field"><span>Độ dài video</span><select data-opt="length" ${dis}>${selectOptions(m.lengths.map(n => [n, `~${n} giây (${(m.length_scenes || {})[n] || Math.max(m.scenes[0], Math.min(m.scenes[1], Math.round(n / 8)))} cảnh)`]), o.length)}</select></label>
      <label class="field"><span>Phong cách hình ảnh (tuỳ chọn)</span><input data-opt="style" value="${esc(o.style || '')}" placeholder="VD: điện ảnh, ánh sáng ấm, phim Hàn" ${dis}></label>
      <label class="field"><span>Tỉ lệ khung hình</span><select data-opt="aspect" ${dis} title="Áp dụng cho storyboard, ảnh khung đầu, clip và video ghép">${selectOptions((m.aspects || []).map(x => [x.value, x.label]), o.aspect || '9:16')}</select></label>
      <label class="field"><span>Chất lượng clip</span><select data-opt="quality" ${dis} title="Độ phân giải yêu cầu model video tạo — model không hỗ trợ thì tự dùng mức gần nhất">${selectOptions((m.qualities || []).map(x => [x.value, x.label]), o.quality || '720p')}</select></label>
      ${MUSE ? museField('Model viết storyboard') : `<label class="field"><span>Model viết storyboard</span><select data-opt="model" ${dis}>${m.text_models.map(x => `<option value="${esc(x.id)}" ${x.id === o.model ? 'selected' : ''}>${esc(x.name)}${x.ready ? '' : ' — chưa có khoá'}</option>`).join('')}</select></label>`}
      ${profileSelect('text_profile', textModel && textModel.site, o.text_profile, 'Profile viết storyboard')}
      <label class="check st-wide"><input type="checkbox" data-opt="prompt_polish" ${o.prompt_polish ? 'checked' : ''} ${dis}> ✨ Chuốt prompt từng cảnh bằng AI sau khi viết storyboard
        <small>Model viết lại prompt ảnh / chuyển động chi tiết hơn (góc máy, ánh sáng, ống kính, hành động) — thêm 1 lượt hỏi model</small></label>
      ${MUSE ? museField('Model ảnh khung đầu') : `<label class="field"><span>Model ảnh khung đầu</span><select data-opt="image_engine" ${dis}>${selectOptions(Object.entries(m.image_engines).map(([k, v]) => [k, v.name]), o.image_engine)}</select></label>`}
      ${img.browser ? profileSelect('image_profile', siteOf(o.image_engine), o.image_profile, 'Profile tạo ảnh') : ''}
      <label class="field st-wide"><span>Kiểu dựng cảnh</span><select data-opt="scene_style" ${dis}>${selectOptions((m.scene_styles || []).map(x => [x.value, x.label]), o.scene_style || 'video')}</select></label>
      ${o.scene_style === 'whiteboard' ? `
      <label class="field"><span>Chất lượng whiteboard</span><select data-opt="wb_quality" ${dis}>${selectOptions([['fast', 'Nhanh — cạnh dài 1080px'], ['hd', 'Nét — cạnh dài 1920px (~3 lần lâu hơn)']], o.wb_quality || 'fast')}</select></label>
      <label class="check"><input type="checkbox" data-opt="wb_hand" ${o.wb_hand !== false ? 'checked' : ''} ${dis}> Hiện bàn tay cầm bút</label>
      <p class="hint st-wide">Whiteboard: model ảnh vẽ line-art nền giấy kem cho từng cảnh, máy bạn dựng tay vẽ lần lượt từng ý đúng lúc lời dẫn được đọc (bộ dựng mã nguồn mở srt-whiteboard-animation — lần đầu app tự tải + cài, cần Python 3). Dùng giọng đọc AI; không cần model video.</p>`
      : `${MUSE ? museField('Model video từng cảnh · 5/10s') : `<label class="field"><span>Model video từng cảnh</span><select data-opt="video_engine" ${dis}>${selectOptions(Object.entries(m.video_engines).map(([k, v]) => [k, `${v.name} · ${v.durations.join('/')}`]), o.video_engine)}</select></label>`}
      ${o.video_engine.endsWith('_browser') ? profileSelect('video_profile', siteOf(o.video_engine), o.video_profile, 'Profile tạo video') : ''}`}
      ${o.scene_style === 'whiteboard' ? '' : `      <label class="check st-wide st-dub"><input type="checkbox" data-opt="dub" ${o.dub !== false ? 'checked' : ''} ${dis}> Lồng tiếng AI (giọng đọc máy)
        <small>${o.dub !== false ? 'Tắt để dùng giọng nói gốc của video được tạo' : 'Đang dùng giọng nói gốc: nhân vật nói lời dẫn ngay trong clip — cần model video có tiếng (Grok, Veo, Muse…). Clip tạo trước khi tắt không có lời nói → làm lại clip.'}</small></label>`}
      <label class="check st-wide"><input type="checkbox" data-opt="lock_outfit" ${o.lock_outfit !== false ? 'checked' : ''} ${dis}> Giữ nguyên trang phục nhân vật ở mọi cảnh
        <small>${o.lock_outfit !== false ? 'Khuôn mặt luôn được khoá. Tắt để trang phục đổi theo mô tả từng cảnh.' : 'Khuôn mặt vẫn khoá; trang phục đổi theo mô tả từng cảnh (làm lại ảnh khung đầu để áp dụng).'}</small></label>
      ${o.dub !== false || o.scene_style === 'whiteboard' ? `<label class="field"><span>Giọng đọc</span><select data-opt="voice" ${dis}>${selectOptions(m.voices.map(v => [v.id, v.name]), o.voice)}</select></label>
      <label class="field"><span>Tốc độ đọc</span><select data-opt="rate" ${dis}>${selectOptions(m.rates.map(r => [r, r]), o.rate)}</select></label>` : ''}
      <label class="check"><input type="checkbox" data-opt="subtitles" ${o.subtitles ? 'checked' : ''} ${dis}> Phụ đề</label>
      <label class="check"><input type="checkbox" data-opt="bgm" ${o.bgm ? 'checked' : ''} ${dis}> Nhạc nền</label>
      <div class="st-wide st-rules"><b>Ràng buộc prompt <small>(ảnh khung đầu &amp; clip)</small></b>
        <div class="st-bans">${(m.bans || []).map(b => `<label class="check"><input type="checkbox" data-ban="${esc(b.value)}" ${bansOf(o).includes(b.value) ? 'checked' : ''} ${dis}> ${esc(b.label)}</label>`).join('')}</div>
        ${bansOf(o).includes('logos') ? '' : logoHtml(o, dis)}
        <label class="field"><span>Cấm thêm (tiếng Anh, tuỳ chọn)</span><input data-opt="negative_extra" value="${esc(o.negative_extra || '')}" placeholder="VD: no extra fingers, no blurry faces" ${dis}></label>
        <label class="check"><input type="checkbox" data-opt="ref_note" ${o.ref_note !== false ? 'checked' : ''} ${dis}> Thêm câu mô tả ảnh tham chiếu <small class="muted">(Reference images are attached in this order — …)</small></label>
        ${o.ref_note !== false ? `<label class="field"><span>Vai trò ảnh tham chiếu (tiếng Anh)</span><input data-opt="ref_prompt" value="${esc(o.ref_prompt || m.ref_prompt_default || '')}" ${dis}></label>` : ''}
        <small class="hint st-rules-preview">Câu cấm sẽ gửi: <code>${esc(negativeLine(o) || '(không có)')}</code></small>
      </div>
      ${postHtml(o, dis)}
      <div class="st-wide st-trans"><b>Chuyển cảnh khi ghép</b>
        <label class="field"><span>Kiểu chuyển cảnh</span><select data-opt="transition" ${dis}>${selectOptions((m.transitions || []).map(x => [x.value, x.label]), o.transition || 'fade')}</select></label>
        <label class="field"><span>Thời lượng</span><select data-opt="transition_duration" ${dis}>${selectOptions((m.durations || [0.5]).map(x => [x, `${x} giây`]), o.transition_duration || 0.5)}</select></label>
        <label class="field"><span>Âm chuyển cảnh</span><span class="row st-sfx"><select data-opt="transition_sound" ${dis}>${selectOptions((m.sounds || []).map(x => [x.value, x.label]), o.transition_sound || 'whoosh')}</select>
          <button class="btn ghost sm" data-sfx-preview type="button" title="Nghe thử âm đã chọn">🔊</button></span></label>
        <label class="field"><span>Âm lượng âm chuyển cảnh · <output>${Math.round((o.transition_volume ?? 0.6) * 100)}%</output></span><input type="range" min="0" max="1.5" step="0.05" data-opt="transition_volume" value="${o.transition_volume ?? 0.6}" ${dis}></label>
      </div>
      <p class="hint st-wide">${esc(vid.note || '')}</p></div>`;
  }

  function newHtml() {
    const d = S.draft && !S.draft.id ? S.draft : (S.draft = { name: '', idea: '', options: {
      length: 60, style: '', model: MUSE ? 'muse_browser' : 'chatgpt_browser', text_profile: '', image_engine: MUSE ? 'muse_browser' : S.meta.default_image_engine,
      image_profile: '', video_engine: 'grok_browser', video_profile: '', voice: 'vi-VN-HoaiMyNeural', rate: '+0%',
      subtitles: true, bgm: true, auto: true, show_browser: false, dub: true } });
    const n = ideaLines(d.idea).length;
    return `<div class="card"><div class="card-title">DỰ ÁN MỚI
        <div class="st-mode"><button class="${S.batch ? '' : 'on'}" data-mode="one" type="button">Một video</button>
          <button class="${S.batch ? 'on' : ''}" data-mode="batch" type="button">Hàng loạt</button></div></div>
      <label class="field"><span>${S.batch ? `Ý tưởng — <b>mỗi dòng là 1 video</b> (tối đa 20) · <span id="stCount">${n} video</span>` : 'Ý tưởng video *'}</span>
        <textarea id="stIdea" rows="${S.batch ? 8 : 5}" placeholder="${S.batch
          ? 'Mỗi dòng 1 ý tưởng, VD:\nBác nông dân cứu vườn sầu riêng bị suy nhờ phân bón hữu cơ\nCô chủ đại lý giới thiệu BOSS 1 cho lúa đẻ nhánh khoẻ\nSo sánh ruộng bón và không bón BOSS 1 sau 30 ngày'
          : 'VD: Câu chuyện bác nông dân miền Tây cứu vườn sầu riêng bị suy nhờ phân bón hữu cơ, kết thúc bằng mùa trái bội thu…'}">${esc(d.idea)}</textarea></label>
      <label class="field"><span>${S.batch ? 'Tiền tố tên dự án (tuỳ chọn, VD “BOSS 1” → BOSS 1 #1, #2…)' : 'Tên dự án (tuỳ chọn)'}</span><input id="stName" value="${esc(d.name)}"></label>
      <div class="field"><span>Ảnh tham chiếu nhân vật / sản phẩm (giữ nhất quán giữa các cảnh)</span>
        <div class="row st-refs">${S.refs.map((r, i) => `<span class="camp-chip">${esc(r.split(/[\\/]/).pop())}<button data-rmref="${i}" type="button">✕</button></span>`).join('')}
          <button class="btn ghost sm" data-addref type="button">+ Chọn ảnh…</button></div></div>
      ${optionsHtml(d.options, false)}
      ${S.batch ? '<p class="hint">Hàng loạt luôn tự làm trọn: viết storyboard → tạo ảnh + clip từng cảnh → ghép. Các dự án xếp hàng chạy song song theo giới hạn trong Cài đặt; ảnh / clip chạy song song theo số profile trình duyệt của từng model.</p>'
        : `<label class="check st-auto"><input type="checkbox" data-opt="auto" ${d.options.auto ? 'checked' : ''}> Tự làm video luôn sau khi có storyboard (bỏ bước duyệt)</label>`}
      <button class="btn primary big st-go" data-create type="button">${S.batch ? `Tạo <span id="stGoN">${n}</span> video →` : 'Tạo storyboard →'}</button></div>`;
  }

  // Thẻ Video hoàn chỉnh: hậu kỳ AI tiếp trên video đã xong (dùng lại clip — chỉ hậu kỳ + ghép lại)
  function finalPostHtml(p, run) {
    const post = (p.final || {}).post || {};
    const done = Boolean(post.at);
    const model = (S.meta.text_models.find(x => x.id === post.model) || {}).name || post.model || '';
    const info = done
      ? `${esc(model)}${post.hyperframes ? ' · 🎞 HyperFrames đồ hoạ động' : ''} · ${post.words} từ tô nổi · ${post.cues} hiệu ứng âm thanh${post.hook ? ` · hook “${esc(post.hook)}”` : ''}`
      : 'Video chưa hậu kỳ — AI (mặc định Claude trình duyệt) chọn từ khoá tô nổi, hiệu ứng âm thanh, câu hook rồi ghép lại. Dùng lại clip đã có, không tạo lại cảnh.';
    return `<div class="st-final-post ${done ? 'done' : ''}">
      <div><b>${done ? '✨ Đã hậu kỳ AI' : '✨ Hậu kỳ AI'}</b><small class="muted">${info}</small></div>
      ${run ? '' : done
        ? '<button class="btn ghost sm" data-act="post" data-what="fresh" type="button" title="Bỏ gợi ý cũ, hỏi AI gợi ý mới rồi ghép lại">↻ Hậu kỳ lại (gợi ý mới)</button>'
        : '<button class="btn primary sm" data-act="post" type="button">✨ Chạy hậu kỳ AI</button>'}
    </div>`;
  }

  function projectHtml() {
    const p = S.cur, d = S.draft, run = p.running;
    const durations = (S.meta.video_engines[d.options.video_engine] || { durations: ['10s'] }).durations.map(x => parseInt(x, 10));
    const total = d.scenes.reduce((a, s) => a + (+s.seconds || 0), 0);
    const ready = d.scenes.length && d.scenes.every(s => s.clip_url);
    const failed = p.scenes.filter(s => s.status === 'error').map(s => s.index);
    const doneN = p.scenes.filter(s => s.clip_url).length;
    const o = d.options;
    const vid = S.meta.video_engines[o.video_engine] || {};
    const img = S.meta.image_engines[o.image_engine] || {};
    const chip = (icon, text, title = '') => `<span class="st-stat" title="${esc(title)}">${icon} ${text}</span>`;
    return `<div class="card st-hero">
        <div class="st-hero-top">
          <div class="st-title"><input id="stTitle" value="${esc(d.name)}" ${run ? 'disabled' : ''} aria-label="Tên dự án">
            <span class="tag ${esc(p.status)}">${esc(STATUS[p.status] || p.status)}</span></div>
          <div class="st-hero-tools">
            ${run ? '' : '<button class="icon-btn" data-act="clone" type="button" title="Nhân bản dự án (giữ ý tưởng / storyboard / cả ảnh + clip)" aria-label="Nhân bản dự án">⧉</button>'}
            <button class="icon-btn st-gear" data-act="settings" type="button" title="Cài đặt dự án (model, giọng đọc, ràng buộc prompt, chuyển cảnh…)" aria-label="Cài đặt dự án">⚙</button>
            ${run ? '' : '<button class="icon-btn st-del" data-act="delete" type="button" title="Xoá dự án" aria-label="Xoá dự án">🗑</button>'}
          </div>
        </div>
        ${ideaHtml(p, d, run)}
        <div class="st-stats">
          ${d.scenes.length ? chip('🎬', `${d.scenes.length} cảnh`) + chip('⏱', `~${total} giây`) : chip('📝', 'Chưa có storyboard')}
          ${d.scenes.length ? chip('🎞', `${doneN}/${p.scenes.length} clip`, 'Số cảnh đã có clip') : ''}
          ${chip('▭', esc(`${o.aspect || '9:16'} · ${o.quality || '720p'}`), 'Tỉ lệ khung hình · chất lượng clip')}${chip('🖼', esc(img.name || o.image_engine), 'Model ảnh khung đầu')}${o.scene_style === 'whiteboard' ? chip('✍', 'Whiteboard vẽ tay', 'Kiểu dựng cảnh') : chip('🎥', esc(vid.name || o.video_engine), 'Model video từng cảnh')}
          ${chip('🗣', o.dub === false && o.scene_style !== 'whiteboard' ? 'Giọng gốc' : 'Lồng tiếng AI')}
          ${p.cloned_from ? chip('⧉', 'Bản sao', 'Dự án được nhân bản') : ''}
        </div>
        <div class="st-actions">
          <div class="st-actions-main">
          ${run ? '<button class="btn danger" data-act="cancel" type="button">■ Dừng</button>' : `
            <button class="btn primary" data-act="make" type="button" ${d.scenes.length ? '' : 'disabled'}>▶ Làm video</button>
            ${failed.length ? `<button class="btn ghost" data-act="retry" data-idx="${failed.join(',')}" type="button">↻ Làm lại ${failed.length} cảnh lỗi</button>` : ''}
            <button class="btn ghost" data-act="assemble" type="button" ${ready ? '' : 'disabled'} title="Ghép lại với giọng đọc / phụ đề / nhạc mới (dùng lại clip)">⧉ Ghép lại</button>
            ${d.scenes.length ? '<button class="btn ghost" data-act="polish" type="button" title="Model viết lại prompt ảnh / chuyển động từng cảnh chi tiết hơn (giữ nhân vật, câu chuyện). Cảnh đổi prompt ảnh phải làm lại ảnh + clip">✨ Chuốt prompt</button>' : ''}
            ${d.scenes.length ? '<button class="btn ghost" data-act="storyboard" type="button" title="Viết lại storyboard từ ý tưởng (thay các cảnh hiện tại)">↻ Viết lại storyboard</button>'
              : '<button class="btn primary" data-act="storyboard" type="button">✍ Viết storyboard</button>'}
            ${S.dirty ? '<button class="btn primary st-save" data-act="save" type="button">💾 Lưu thay đổi</button>' : ''}`}
          </div>
          ${run ? '' : `<div class="st-actions-side">
            <label class="check st-postchip ${o.post_ai ? 'on' : ''}" title="Hậu kỳ AI sau bước ghép: model chat (mặc định Claude trình duyệt) làm phụ đề + âm thanh nổi bật — chỉnh chi tiết ở ⚙"><input type="checkbox" data-opt="post_ai" ${o.post_ai ? 'checked' : ''}> ✨ Hậu kỳ AI: <b>${o.post_ai ? 'Bật' : 'Tắt'}</b></label>
          </div>`}
        </div>
        ${p.error ? `<div class="camp-banner bad">${esc(p.error)}</div>` : ''}
        ${p.status === 'interrupted' ? '<div class="camp-banner">Lần chạy trước bị gián đoạn (app đã tắt) — bấm ▶ Làm video để chạy tiếp các cảnh còn thiếu.</div>' : ''}
      </div>
      <div id="stLive">${liveHtml(run)}</div>
      ${p.final_url ? `<div class="card st-final"><div class="card-title">VIDEO HOÀN CHỈNH <span class="tag">${Math.round(p.final.duration || 0)} giây · có trong Thư viện video</span></div>
        <div class="st-final-body"><video src="${esc(p.final_url)}" controls playsinline></video>
          <div class="st-final-side">
            ${finalPostHtml(p, run)}
            <div class="row st-final-act"><button class="btn ghost sm" data-act="open-folder" type="button">📂 Mở thư mục chứa video</button></div>
            <small class="muted mono">${esc(p.final.job_id || '')}/final.mp4</small>
          </div></div></div>` : ''}
      <div class="card"><div class="card-title">NHÂN VẬT & PHONG CÁCH <small class="muted">— dùng chung cho mọi cảnh để nhất quán</small></div>
        <div class="grid2"><label class="field"><span>${((d.bible || {}).characters || []).length ? "Sản phẩm / đạo cụ chính (tiếng Anh)" : "Nhân vật / sản phẩm"}</span><textarea data-bible="nhan_vat" rows="3" ${run ? 'disabled' : ''}>${esc((d.bible || {}).nhan_vat || '')}</textarea></label>
          <label class="field"><span>Phong cách hình ảnh</span><textarea data-bible="phong_cach" rows="3" ${run ? 'disabled' : ''}>${esc((d.bible || {}).phong_cach || '')}</textarea></label></div>
        ${charactersHtml(d, run)}</div>
      <div class="st-board-head"><b>STORYBOARD · ${d.scenes.length} cảnh · ~${total} giây hình</b>
        ${run ? '' : '<button class="btn ghost sm" data-act="add-scene" type="button">+ Thêm cảnh</button>'}</div>
      <div class="st-board asp-${{ '16:9': 'wide', '1:1': 'square' }[o.aspect] || 'tall'}">${d.scenes.map((s, i) => sceneHtml(s, i, durations, run)).join('')
        || `<div class="empty">${run ? 'Đang viết storyboard…' : 'Chưa có storyboard — bấm ✍ Viết storyboard (hoặc sửa ý tưởng rồi “Lưu &amp; viết lại storyboard”).'}</div>`}</div>`;
  }

  // Ý tưởng: xem / sửa ngay trên trang rồi lưu, hoặc lưu + viết lại storyboard
  function ideaHtml(p, d, run) {
    if (!S.editIdea || run) {
      return `<div class="st-idea-box"><p class="st-idea">${esc(d.idea || p.idea)}</p>
        ${run ? '' : '<button class="link" data-act="edit-idea" type="button">✎ Sửa ý tưởng</button>'}</div>`;
    }
    return `<div class="st-idea-box editing">
      <textarea id="stIdeaEdit" rows="4" placeholder="Mô tả ý tưởng video…">${esc(S.ideaDraft ?? d.idea ?? p.idea)}</textarea>
      <div class="row st-idea-act">
        <small class="muted">Viết lại storyboard sẽ thay các cảnh hiện tại — muốn giữ bản cũ thì bấm ⧉ Nhân bản trước.</small>
        <button class="btn ghost sm" data-act="idea-cancel" type="button">Huỷ</button>
        <button class="btn ghost sm" data-act="idea-save" type="button">💾 Lưu ý tưởng</button>
        <button class="btn primary sm" data-act="idea-rerun" type="button">↻ Lưu &amp; viết lại storyboard</button>
      </div></div>`;
  }

  // Tiến trình (giống trang Tạo video): các bước + thanh % + trạng thái + nhật ký.
  // Vẽ lại riêng phần này khi có log (không vẽ lại cả trang → video đang xem không bị tải lại)
  const STAGES = [['script', 'Storyboard'], ['frame', 'Ảnh khung đầu'], ['clip', 'Clip cảnh'], ['ai', 'Hậu kỳ AI'],
    ['post', 'Ghép video'], ['finish', 'Hoàn tất']];
  function liveHtml(run) {
    if (!run && !S.logs.length) return '';
    const pr = S.progress || { pct: 0, status: run ? 'Đang chờ tới lượt' : '', stage: '' };
    const pct = Math.round(+pr.pct || 0);
    const stages = STAGES.filter(([id]) => id !== 'ai' || (S.draft && S.draft.options.post_ai) || pr.stage === 'ai');
    const cur = stages.findIndex(([id]) => id === pr.stage);
    const finished = !run && pct >= 100;
    return `<div class="card st-prog ${run ? 'running' : ''}">
      <div class="card-title">TIẾN TRÌNH <span class="status-pill mono ${run ? '' : finished ? 'ok' : ''}">${run ? 'Đang chạy' : finished ? 'Hoàn tất' : 'Đã dừng'}</span></div>
      <div class="stepper st-stepper">${stages.map(([id, label], i) =>
        `<div class="step ${finished || i < cur ? 'done' : ''} ${run && i === cur ? 'active' : ''}"><i></i><span>${label}</span></div>`).join('')}</div>
      <div class="progress"><div class="bar"><i style="width:${pct}%"></i></div><span class="mono">${pct}%</span></div>
      ${pr.status ? `<div class="status-box">${esc(pr.status)}</div>` : ''}
      <div class="log-card"><div class="log-head"><span>NHẬT KÝ XỬ LÝ</span><span class="muted mono">${S.logs.length} dòng</span></div>
        <div class="log mono st-log">${S.logs.map(l => `<div class="ln ${esc(l.level || 'info')}">${esc(l.time || '')} ${esc(l.message)}</div>`).join('') || '<div class="ln muted">Chưa có nhật ký</div>'}</div></div>
    </div>`;
  }

  function paintLive() {
    const box = $('#stLive');
    if (!box || !S.cur) return;
    box.innerHTML = liveHtml(S.cur.running);
    const lg = box.querySelector('.st-log');
    if (lg) lg.scrollTop = lg.scrollHeight;  // tự cuộn tới dòng mới nhất
  }

  // giống app/studio.py speech_seconds: số giây cần để nói hết lời của cảnh
  function speechSeconds(s) {
    const texts = (s.lines || []).map(l => l.text || '').filter(t => t.trim());
    if (!texts.length && (s.narration || '').trim()) texts.push(s.narration);
    const words = texts.reduce((a, t) => a + t.trim().split(/\s+/).length, 0);
    return words ? words / 2.6 + 0.35 * Math.max(0, texts.length - 1) + 1 : 0;
  }

  function speechWarn(s, durations) {
    const need = speechSeconds(s);
    if (need <= (+s.seconds || 0) + 0.05) return '';
    const longest = Math.max(...durations);
    return `<small class="warn-text st-speech-warn">⚠ Lời thoại cần ~${Math.ceil(need)}s nhưng cảnh ${s.seconds}s — ${need > longest
      ? `rút gọn lời hoặc tách cảnh (clip tối đa ${longest}s)` : `chọn ≥ ${durations.filter(d => d >= need)[0]}s`} để không bị ngắt câu</small>`;
  }

  function sceneHtml(s, i, durations, run) {
    const dis = run ? 'disabled' : '';
    const lines = (s.lines || []).length;
    return `<div class="card st-scene ${esc(s.status || '')}" data-i="${i}">
      <div class="st-media">${s.clip_url ? `<video src="${esc(s.clip_url)}" controls muted playsinline poster="${esc(s.frame_url || '')}"></video>`
        : s.frame_url ? `<img src="${esc(s.frame_url)}" alt="">` : `<span>${s.status === 'frame_running' ? 'Đang tạo ảnh…' : 'Chưa có ảnh'}</span>`}
        <em>${i + 1}</em>${SCENE_STATUS[s.status] ? `<b class="st-badge ${esc(s.status)}">${esc(SCENE_STATUS[s.status])}</b>` : ''}</div>
      <div class="st-fields st-col-story">
        <div class="st-scene-head"><input data-sf="title" value="${esc(s.title || '')}" ${dis} aria-label="Tiêu đề cảnh" title="${esc(s.title || '')}">
          <select data-sf="seconds" ${dis} aria-label="Số giây">${durations.map(n => `<option value="${n}" ${n === +s.seconds ? 'selected' : ''}>${n}s</option>`).join('')}</select></div>
        ${s.error ? `<small class="warn-text">${esc(s.error)}</small>` : ''}
        ${speechWarn(s, durations)}
        ${sceneCastHtml(s, dis)}
        ${lines ? linesHtml(s, dis) : `<label class="field"><span>Lời đọc (tiếng Việt)</span><textarea data-sf="narration" rows="2" ${dis}>${esc(s.narration || '')}</textarea></label>`}
        <div class="st-voice"><span>${lines ? 'Giọng dẫn chuyện' : 'Giọng đọc'}</span>
          <select data-sf="speaker" ${dis} title="Giọng lời dẫn của cảnh — lồng tiếng AI đổi cao độ/tốc độ theo vai; giọng gốc: dặn model video nói đúng kiểu giọng">${selectOptions((S.meta.speakers || []).map(x => [x.value, x.label]), s.speaker || '')}</select>
          <button class="btn ghost sm" data-voice-preview type="button" title="Nghe thử lời đọc với giọng này (lồng tiếng AI)">🔊</button>
          ${lines || dis ? '' : '<button class="btn ghost sm" data-line-add type="button" title="Chia lời đọc thành các câu thoại, mỗi câu một nhân vật / giọng">+ Thoại nhiều nhân vật</button>'}</div>
      </div>
      <div class="st-fields st-col-prompt">
        <label class="field"><span>Khung hình đầu (prompt ảnh)</span><textarea data-sf="image_prompt" rows="3" ${dis}>${esc(s.image_prompt || '')}</textarea></label>
        <label class="field"><span>Chuyển động / máy quay</span><textarea data-sf="motion_prompt" rows="2" ${dis}>${esc(s.motion_prompt || '')}</textarea></label>
        ${run ? '' : `<div class="row st-scene-act">
          <button class="btn ghost sm" data-scene="frame" type="button" title="Tạo lại ảnh khung đầu">↻ Ảnh</button>
          <button class="btn ghost sm" data-scene="clip" type="button" ${s.frame_url ? '' : 'disabled'} title="Tạo lại clip">↻ Clip</button>
          <span class="st-act-gap"></span>
          <button class="btn ghost sm" data-move="-1" type="button" ${i ? '' : 'disabled'} title="Lên">↑</button>
          <button class="btn ghost sm" data-move="1" type="button" title="Xuống">↓</button>
          <button class="btn ghost sm st-pdel" data-del-scene type="button" title="Xoá cảnh">🗑</button></div>`}
      </div></div>`;
  }

  // ------------------------------------------------------------ hồ sơ nhân vật + lời thoại nhiều giọng
  const charsOf = d => ((d.bible || (d.bible = {})).characters || (d.bible.characters = []));
  function charactersHtml(d, run) {
    const chars = (d.bible || {}).characters || [];
    const dis = run ? 'disabled' : '';
    const voices = (S.meta.speakers || []).filter(x => x.value);
    return `<div class="st-chars"><div class="row st-chars-head"><b>👥 Hồ sơ nhân vật &amp; giọng lồng tiếng</b>
        <small class="muted">khoá khuôn mặt, tuổi, trang phục ở mọi cảnh · mỗi nhân vật một giọng</small>
        ${run ? '' : `<button class="btn ghost sm" data-char-add type="button" ${chars.length >= 8 ? 'disabled' : ''}>+ Nhân vật</button>`}</div>
      ${chars.map((c, i) => `<div class="st-char" data-ci="${i}">
        <div class="row st-char-top"><input data-char="name" value="${esc(c.name)}" placeholder="Tên nhân vật" ${dis}>
          <select data-char="voice" ${dis} title="Giọng lồng tiếng của nhân vật">${selectOptions([['', 'Giọng mặc định của dự án'], ...voices.map(x => [x.value, x.label])], c.voice || '')}</select>
          <button class="btn ghost sm" data-char-preview type="button" title="Nghe thử giọng nhân vật">🔊</button>
          ${run ? '' : '<button class="btn ghost sm" data-char-del type="button" title="Xoá nhân vật">✕</button>'}</div>
        <div class="grid2"><label class="field"><span>Ngoại hình cố định (tiếng Anh: tuổi, khuôn mặt, tóc, vóc dáng)</span><textarea data-char="look" rows="2" ${dis}>${esc(c.look || '')}</textarea></label>
          <label class="field"><span>Trang phục cố định (tiếng Anh: áo, quần / váy, màu, phụ kiện)</span><textarea data-char="outfit" rows="2" ${dis}>${esc(c.outfit || '')}</textarea></label></div></div>`).join('')
        || '<small class="muted">Chưa có hồ sơ nhân vật — viết storyboard mới sẽ tự tạo, hoặc bấm “+ Nhân vật”.</small>'}</div>`;
  }

  function sceneCastHtml(s, dis) {
    const chars = (S.draft.bible || {}).characters || [];
    if (!chars.length) return '';
    const on = Array.isArray(s.cast) ? s.cast : chars.map(c => c.name);
    return `<div class="row st-sc-cast"><span>Trong khung hình</span>${chars.map(c => `<button class="st-chip-sm ${on.includes(c.name) ? 'on' : ''}" data-sc-cast="${esc(c.name)}" type="button" ${dis}>${esc(c.name)}</button>`).join('')}</div>`;
  }

  function linesHtml(s, dis) {
    const chars = (S.draft.bible || {}).characters || [];
    const who = [['', '🎙 Người dẫn chuyện'], ...chars.map(c => [c.name, c.name])];
    return `<div class="st-lines"><div class="st-lines-head"><span>Lời thoại <small class="muted">· mỗi câu một giọng</small></span>
        ${dis ? '' : '<button class="link" data-line-add type="button">+ Câu thoại</button>'}</div>
      ${(s.lines || []).map((l, k) => `<div class="st-line" data-li="${k}">
        <select data-line="who" ${dis}>${selectOptions(who, l.who || '')}</select>
        <input data-line="text" value="${esc(l.text || '')}" placeholder="Câu nói (tiếng Việt)" ${dis}>
        <input data-line="tone" value="${esc(l.tone || '')}" placeholder="Cảm xúc" ${dis}>
        <button class="btn ghost sm" data-line-preview type="button" title="Nghe thử câu này">🔊</button>
        ${dis ? '' : '<button class="btn ghost sm" data-line-del type="button" title="Xoá câu">✕</button>'}</div>`).join('')}</div>`;
  }

  const linesNarration = lines => lines.map(l => l.text).filter(Boolean).join(' ');

  function renameCharacter(d, oldName, newName) {
    for (const sc of d.scenes) {
      (sc.lines || []).forEach(l => { if (l.who === oldName) l.who = newName; });
      if (Array.isArray(sc.cast)) sc.cast = sc.cast.map(n => (n === oldName ? newName : n));
    }
  }

  async function previewVoice(btn, text, speaker) {
    btn.disabled = true;
    const res = await api(CFG.api + 'voice_preview', text, speaker || '', S.draft.options.voice, S.draft.options.rate);
    btn.disabled = false;
    if (!res.ok) return toast(res.error, 'error');
    new Audio(res.data).play();
  }

  // ------------------------------------------------------------ sự kiện
  function markDirty() {
    if (!S.cur) return;
    if (!S.dirty) { S.dirty = true; render(); }
  }

  // Gắn sự kiện cho trang Studio, hoặc cho khung Cài đặt dự án trong dialog (#stOptsDlg — mất cùng dialog khi đóng)
  function bind(root = $(CFG.body)) {
    root.oninput = e => {
      const t = e.target;
      const d = S.draft;
      if (t.dataset.rvBrief !== undefined) { const rv = rvGet(); if (rv) { rv.brief = t.value; markDirty(); } return; }
      if (t.id === 'stSearch') { S.q = t.value; const g = root.querySelector('#stGrid'); if (g) g.innerHTML = gridHtml(); return; }
      if (t.id === 'stRvSrc') { S.rvSource = t.value; return; }
      if (t.id === 'stIdea') {
        d.idea = t.value;
        if (S.batch) {  // cập nhật số video ngay khi gõ (không vẽ lại cả form)
          const n = ideaLines(d.idea).length;
          if ($('#stCount')) $('#stCount').textContent = `${n} video`;
          if ($('#stGoN')) $('#stGoN').textContent = n;
        }
      }
      else if (t.id === 'stIdeaEdit') S.ideaDraft = t.value;  // sửa ý tưởng: chỉ lưu khi bấm Lưu
      else if (t.id === 'stName' || t.id === 'stTitle') { d.name = t.value; if (t.id === 'stTitle') markDirty(); }
      else if (t.dataset.bible) { d.bible = { ...(d.bible || {}), [t.dataset.bible]: t.value }; markDirty(); }
      else if (t.dataset.sf && t.tagName !== 'SELECT') { d.scenes[+t.closest('[data-i]').dataset.i][t.dataset.sf] = t.value; markDirty(); }
      else if (t.dataset.char && t.tagName !== 'SELECT') {  // hồ sơ nhân vật
        const c = charsOf(d)[+t.closest('[data-ci]').dataset.ci];
        if (t.dataset.char === 'name') renameCharacter(d, c.name, t.value.trim());
        c[t.dataset.char] = t.dataset.char === 'name' ? t.value.trim() : t.value;
        markDirty();
      } else if (t.dataset.line && t.tagName !== 'SELECT') {  // câu thoại
        const sc = d.scenes[+t.closest('[data-i]').dataset.i];
        sc.lines[+t.closest('[data-li]').dataset.li][t.dataset.line] = t.value;
        sc.narration = linesNarration(sc.lines);
        markDirty();
      }
    };
    root.onchange = e => {
      const t = e.target;
      const d = S.draft;
      if (t.dataset.rvModel !== undefined) { S.rvModel = t.value; return render(); }
      if (t.dataset.opt) {
        const num = ['transition_duration', 'transition_volume'].includes(t.dataset.opt);
        d.options = { ...d.options, [t.dataset.opt]: t.type === 'checkbox' ? t.checked : num ? +t.value : t.value };
        if (t.dataset.opt === 'transition_volume' && t.closest('label').querySelector('output')) {
          t.closest('label').querySelector('output').textContent = `${Math.round(t.value * 100)}%`;
        }
        if (S.cur) markDirty();
        if (['model', 'image_engine', 'video_engine', 'scene_style', 'dub', 'lock_outfit', 'ref_note', 'negative_extra', 'post_ai', 'post_model',
          'post_subs', 'subtitles', 'post_style'].includes(t.dataset.opt)) render();
      } else if (t.dataset.ban) {  // ràng buộc prompt: bật/tắt từng thứ bị cấm trong hình
        const all = (S.meta.bans || []).map(b => b.value);
        const on = new Set(bansOf(d.options));
        if (t.checked) on.add(t.dataset.ban); else on.delete(t.dataset.ban);
        d.options = { ...d.options, bans: all.filter(k => on.has(k)) };
        if (S.cur) markDirty();
        render();
      } else if (t.dataset.sf === 'seconds') { d.scenes[+t.closest('[data-i]').dataset.i].seconds = +t.value; markDirty(); }
      else if (t.dataset.sf === 'speaker') { d.scenes[+t.closest('[data-i]').dataset.i].speaker = t.value; markDirty(); }
      else if (t.dataset.char === 'voice') { charsOf(d)[+t.closest('[data-ci]').dataset.ci].voice = t.value; markDirty(); }
      else if (t.dataset.line === 'who') {
        d.scenes[+t.closest('[data-i]').dataset.i].lines[+t.closest('[data-li]').dataset.li].who = t.value; markDirty();
      }
    };
    root.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.rvPick !== undefined) {
        const files = await api('pick_files', 'video');
        if (files.length) { S.rvSource = files[0]; const box = root.querySelector('#stRvSrc'); if (box) box.value = files[0]; }
        return;
      }
      if (t.dataset.rvGo !== undefined) {
        const src = ((root.querySelector('#stRvSrc') || {}).value || '').trim();
        if (!src) return toast('Dán link video hoặc chọn file trước', 'warn');
        const label = t.textContent;
        t.disabled = true; t.textContent = '⏳ Đang phân tích… (1–3 phút)';
        const opts = (S.draft || {}).options || {};
        const res = await api(CFG.api + 'analyze_video', src, MUSE ? 'muse_browser' : S.rvModel || 'gemini_browser', '', !!opts.show_browser);
        t.disabled = false; t.textContent = label;
        if (!res.ok) return toast(res.error, 'error');
        rvSet(res.result);
        if (S.draft) S.draft.options = { ...S.draft.options, ref_video_use: true };
        toast('Đã phân tích video tham khảo — sửa tóm tắt nếu cần; storyboard sẽ dùng phần này', 'ok');
        markDirty(); return render();
      }
      if (t.dataset.rvClear !== undefined) {
        rvSet(null);
        if (S.draft) S.draft.options = { ...S.draft.options, ref_video_use: false };
        markDirty(); return render();
      }
      if (t.dataset.new !== undefined) { S.cur = null; S.draft = null; S.dirty = false; S.refs = []; S.newLogo = ''; S.newRefVideo = null; S.logs = []; S.view = 'new'; return render(); }
      if (t.dataset.back !== undefined) {
        if (S.dirty && !confirm('Có thay đổi chưa lưu — bỏ thay đổi và quay lại danh sách dự án?')) return;
        S.cur = null; S.draft = null; S.dirty = false; S.logs = []; S.view = 'list'; S.editIdea = false;
        await loadList(); return render();
      }
      if (t.dataset.filter) { S.filter = t.dataset.filter; return render(); }
      if (t.dataset.delId) {
        const p = S.projects.find(x => x.id === t.dataset.delId);
        if (!p || !confirm(`Xoá dự án “${p.name}” và toàn bộ ảnh / clip của nó? Video đã ghép trong Thư viện video vẫn giữ.`)) return;
        const res = await api(CFG.api + 'delete', p.id);
        if (!res.ok) return toast(res.error, 'error');
        await loadList(); toast('Đã xoá dự án', 'ok'); return render();
      }
      if (t.dataset.mode) { S.batch = t.dataset.mode === 'batch'; return render(); }
      if (t.dataset.charAdd !== undefined) { charsOf(S.draft).push({ name: `Nhân vật ${charsOf(S.draft).length + 1}`, look: '', outfit: '', voice: '' }); markDirty(); return render(); }
      if (t.dataset.charDel !== undefined) {
        const chars = charsOf(S.draft);
        const c = chars[+t.closest('[data-ci]').dataset.ci];
        if (!confirm(`Xoá nhân vật “${c.name}”? Câu thoại của nhân vật này chuyển sang người dẫn chuyện.`)) return;
        chars.splice(chars.indexOf(c), 1);
        renameCharacter(S.draft, c.name, '');
        S.draft.scenes.forEach(sc => { if (Array.isArray(sc.cast)) sc.cast = sc.cast.filter(Boolean); });
        markDirty(); return render();
      }
      if (t.dataset.charPreview !== undefined) {
        const c = charsOf(S.draft)[+t.closest('[data-ci]').dataset.ci];
        return previewVoice(t, `Xin chào, mình là ${c.name || 'nhân vật mới'}. Rất vui được gặp mọi người!`, c.voice);
      }
      if (t.dataset.scCast !== undefined) {  // bật / tắt nhân vật có mặt trong khung hình của cảnh
        const sc = S.draft.scenes[+t.closest('[data-i]').dataset.i];
        const all = charsOf(S.draft).map(c => c.name);
        const on = new Set(Array.isArray(sc.cast) ? sc.cast : all);
        if (on.has(t.dataset.scCast)) on.delete(t.dataset.scCast); else on.add(t.dataset.scCast);
        sc.cast = all.filter(n => on.has(n));
        markDirty(); return render();
      }
      if (t.dataset.lineAdd !== undefined) {
        const sc = S.draft.scenes[+t.closest('[data-i]').dataset.i];
        if (!(sc.lines || []).length && (sc.narration || '').trim()) sc.lines = [{ who: '', text: sc.narration.trim(), tone: '' }];
        else (sc.lines = sc.lines || []).push({ who: (charsOf(S.draft)[0] || {}).name || '', text: '', tone: '' });
        markDirty(); return render();
      }
      if (t.dataset.lineDel !== undefined) {
        const sc = S.draft.scenes[+t.closest('[data-i]').dataset.i];
        sc.lines.splice(+t.closest('[data-li]').dataset.li, 1);
        sc.narration = linesNarration(sc.lines);
        markDirty(); return render();
      }
      if (t.dataset.linePreview !== undefined) {
        const sc = S.draft.scenes[+t.closest('[data-i]').dataset.i];
        const l = sc.lines[+t.closest('[data-li]').dataset.li];
        const c = charsOf(S.draft).find(x => x.name === l.who);
        return previewVoice(t, l.text, l.who ? (c || {}).voice : sc.speaker);
      }
      if (t.dataset.voicePreview !== undefined) {  // nghe thử lời đọc cảnh với vai giọng đang chọn
        const sc = S.draft.scenes[+t.closest('[data-i]').dataset.i];
        t.disabled = true;
        const res = await api(CFG.api + 'voice_preview', sc.narration || '', sc.speaker || '', S.draft.options.voice, S.draft.options.rate);
        t.disabled = false;
        if (!res.ok) return toast(res.error, 'error');
        return new Audio(res.data).play();
      }
      if (t.dataset.sfxPreview !== undefined) {  // nghe thử âm chuyển cảnh đang chọn
        const sel = t.closest('.st-sfx').querySelector('select');
        const res = await api('transition_sound_preview', sel.value);
        if (!res.ok) return toast(res.error, 'error');
        if (!res.data) return toast('Không có âm (đang chọn “Không có” / “Ngẫu nhiên”)', 'warn');
        const audio = new Audio(res.data);
        audio.volume = Math.min(1, +(S.draft.options.transition_volume ?? 0.6));
        return audio.play();
      }
      if (t.dataset.resumeAll !== undefined) {
        if (S.dirty && !confirm('Có thay đổi chưa lưu ở dự án đang mở — vẫn chạy tiếp tất cả?')) return;
        t.disabled = true;
        const res = await api(CFG.api + 'resume_all');
        t.disabled = false;
        if (!res.ok) return toast(res.error, 'error');
        const r = res.result;
        toast(r.started.length ? `Đã xếp hàng ${r.started.length} dự án` + (r.skipped.length ? ` · bỏ qua ${r.skipped.length}` : '') : 'Không có dự án nào cần chạy tiếp', r.started.length ? 'ok' : 'warn');
        await loadList(); return render();
      }
      if (t.dataset.open) return open(t.dataset.open);
      if (t.dataset.addref !== undefined) {
        const files = await api('pick_files', 'images_multi');
        S.refs = [...new Set([...S.refs, ...files])].slice(0, 6);
        return render();
      }
      if (t.dataset.rmref !== undefined) { S.refs.splice(+t.dataset.rmref, 1); return render(); }
      if (t.dataset.gotoCast !== undefined) { closeModal(); return navigate('cast'); }
      if (t.dataset.castPick) return openCastPicker(t.dataset.castPick);  // hộp chọn nhân vật / layout / bộ kết hợp
      if (t.dataset.logoPick !== undefined || t.dataset.logoRm !== undefined) {  // tải lên / bỏ logo thương hiệu
        let path = '';
        if (t.dataset.logoPick !== undefined) {
          const files = await api('pick_files', 'image');
          if (!files || !files.length) return;
          path = files[0];
        }
        if (!S.cur) { S.newLogo = path; return render(); }
        const res = await api(CFG.api + 'set_logo', S.cur.id, path);
        if (!res.ok) return toast(res.error, 'error');
        S.cur = res.project;
        if (S.dirty) S.draft.logo_url = S.cur.logo_url; else S.draft = clone(S.cur);
        toast(path ? 'Đã tải logo lên' : 'Đã bỏ logo', 'ok');
        return render();
      }
      if (t.dataset.create !== undefined) return create(t);
      const card = t.closest('[data-i]');
      if (card && t.dataset.scene) return start('scenes', [+card.dataset.i + 1], t.dataset.scene);
      if (card && t.dataset.move) {
        const i = +card.dataset.i, j = i + +t.dataset.move;
        if (j < 0 || j >= S.draft.scenes.length) return;
        [S.draft.scenes[i], S.draft.scenes[j]] = [S.draft.scenes[j], S.draft.scenes[i]];
        S.dirty = true; return render();
      }
      if (card && t.dataset.delScene !== undefined) {
        if (!confirm('Xoá cảnh này khỏi storyboard?')) return;
        S.draft.scenes.splice(+card.dataset.i, 1); S.dirty = true; return render();
      }
      const act = t.dataset.act;
      if (act === 'add-scene') {
        S.draft.scenes.push({ title: `Cảnh ${S.draft.scenes.length + 1}`, narration: '', image_prompt: '', motion_prompt: '', seconds: 10 });
        S.dirty = true; return render();
      }
      if (act === 'save') return save(true);
      if (act === 'settings') return openOpts();
      if (act === 'clone') return openClone();
      if (act === 'edit-idea') { S.editIdea = true; S.ideaDraft = S.draft.idea || S.cur.idea; render(); $('#stIdeaEdit') && $('#stIdeaEdit').focus(); return; }
      if (act === 'idea-cancel') { S.editIdea = false; S.ideaDraft = null; return render(); }
      if (act === 'idea-save' || act === 'idea-rerun') {
        const idea = String(S.ideaDraft ?? '').trim();
        if (idea.length < 10) return toast('Ý tưởng quá ngắn (ít nhất 1 câu)', 'warn');
        if (act === 'idea-rerun' && S.draft.scenes.length
          && !confirm('Viết lại storyboard từ ý tưởng mới? Các cảnh hiện tại (kể cả ảnh / clip) sẽ bị thay thế.')) return;
        S.draft.idea = idea; S.dirty = true;
        if (!(await save(false))) return;
        S.editIdea = false; S.ideaDraft = null;
        if (act === 'idea-rerun') return start('storyboard');
        toast('Đã lưu ý tưởng', 'ok');
        return render();
      }
      if (act === 'opts-close') return closeModal();
      if (act === 'opts-save') {
        if (await save(false)) { closeModal(); toast('Đã lưu cài đặt dự án', 'ok'); }
        return;
      }
      if (act === 'open-folder') {
        const res = await api('open_video_folder', S.cur.final.job_id);
        if (!res.ok) toast(res.error, 'error');
        return;
      }
      if (act === 'retry') return start('make', t.dataset.idx.split(',').map(Number), 'both');  // làm lại cảnh lỗi rồi ghép
      if (act === 'cancel') { await api(CFG.api + 'cancel', S.cur.id); return toast('Đang dừng…', 'warn'); }
      if (act === 'delete') {
        if (!confirm('Xoá dự án Studio này (ảnh, clip của dự án)? Video đã ghép trong Thư viện video vẫn giữ.')) return;
        const res = await api(CFG.api + 'delete', S.cur.id);
        if (!res.ok) return toast(res.error, 'error');
        S.cur = null; S.draft = null; await loadList(); return render();
      }
      if (act === 'storyboard' && S.draft.scenes.length
        && !confirm('Viết lại storyboard từ ý tưởng? Các cảnh hiện tại sẽ bị thay thế.')) return;
      if (act === 'post') return start('post', [], t.dataset.what || 'both');  // hậu kỳ AI tiếp trên video đã xong
      if (act === 'polish' && !confirm('Chuốt prompt: model viết lại prompt ảnh / chuyển động của mọi cảnh. Cảnh đổi prompt ảnh sẽ phải làm lại ảnh + clip. Tiếp tục?')) return;
      if (['make', 'assemble', 'storyboard', 'polish'].includes(act)) return start(act);
    };
  }

  async function open(id) {
    if (S.dirty && !confirm('Có thay đổi chưa lưu — bỏ thay đổi?')) return;
    S.cur = S.projects.find(p => p.id === id) || null;
    S.draft = S.cur ? clone(S.cur) : null;
    S.dirty = false; S.logs = []; S.progress = null; S.editIdea = false; S.ideaDraft = null;
    render();
    if (!S.cur) return;
    const res = await api(CFG.api + 'logs', id);  // dự án đang chạy (hoặc vừa xong) → hiện lại tiến trình + nhật ký
    if (res.ok && res.task && S.cur && S.cur.id === id) {
      S.tasks[res.task.id] = id;
      S.logs = res.logs || [];
      S.progress = { pct: res.task.pct, status: res.task.status_text, stage: res.task.stage };
      paintLive();
    }
  }

  // ------------------------------------------------------------ nhân bản dự án
  const CLONE_MODES = [
    ['idea', 'Chỉ ý tưởng + cài đặt', 'Viết storyboard mới từ đầu — sửa ý tưởng ngay sau khi nhân bản rồi chạy lại.'],
    ['storyboard', 'Ý tưởng + storyboard', 'Giữ nhân vật, phong cách và các cảnh (lời đọc, prompt) — tạo ảnh / clip mới.'],
    ['media', 'Toàn bộ, kèm ảnh + clip', 'Giữ cả ảnh và clip đã tạo — làm biến thể: sửa vài cảnh, đổi giọng / nhạc / hậu kỳ rồi ghép.'],
  ];
  function openClone() {
    const p = S.cur;
    // ảnh tham chiếu của bản sao: mặc định giữ ảnh của dự án gốc; bỏ (✕) hoặc thêm ảnh mới
    let refs = (p.refs || []).map((path, i) => ({ path, url: (p.refs_view || [])[i] || '' }));
    const refsHtml = () => `${refs.map((r, i) => `<span class="st-clone-ref" title="${esc(r.path)}">
        ${r.url ? `<img src="${esc(r.url)}" alt="">` : '<i>🖼</i>'}<small>${esc(r.path.split(/[\\/]/).pop())}</small>
        <button data-clone-rmref="${i}" type="button" title="Bỏ ảnh này">✕</button></span>`).join('')}
      ${refs.length < 6 ? '<button class="st-clone-ref st-clone-add" data-clone-addref type="button"><b>+</b><small>Thêm ảnh</small></button>' : ''}`;
    openModal('NHÂN BẢN DỰ ÁN', p.name, `<div id="stCloneDlg" class="st-clone">
      <label class="field"><span>Tên dự án mới</span><input id="stCloneName" value="${esc(p.name)} (bản sao)"></label>
      <div class="st-clone-opts">${CLONE_MODES.map(([v, title, desc]) => `<label class="st-clone-opt">
        <input type="radio" name="stCloneMode" value="${v}" ${v === 'storyboard' ? 'checked' : ''}><span><b>${title}</b><small class="muted">${desc}</small></span></label>`).join('')}</div>
      <div class="field"><span>Ảnh tham chiếu cho bản sao (nhân vật / sản phẩm, tối đa 6) — bỏ ✕ ảnh cũ hoặc thêm ảnh mới</span>
        <div class="st-clone-refs" id="stCloneRefs">${refsHtml()}</div></div>
      <small class="muted">Luôn chép kèm: cài đặt dự án, logo. Không chép video hoàn chỉnh.</small>
      <div class="modal-foot st-optfoot"><button class="btn ghost" data-clone-cancel type="button">Huỷ</button>
        <button class="btn primary" data-clone-go type="button">⧉ Nhân bản</button></div></div>`, true);
    $('#stCloneDlg').onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.cloneCancel !== undefined) return closeModal();
      if (t.dataset.cloneRmref !== undefined) { refs.splice(+t.dataset.cloneRmref, 1); $('#stCloneRefs').innerHTML = refsHtml(); return; }
      if (t.dataset.cloneAddref !== undefined) {
        const files = await api('pick_files', 'images_multi');
        const have = new Set(refs.map(r => r.path));
        refs = [...refs, ...files.filter(f => !have.has(f)).map(f => ({ path: f, url: '' }))].slice(0, 6);
        $('#stCloneRefs').innerHTML = refsHtml();
        return;
      }
      if (t.dataset.cloneGo === undefined) return;
      const mode = ($('#stCloneDlg input[name=stCloneMode]:checked') || {}).value || 'storyboard';
      t.disabled = true;
      const res = await api(CFG.api + 'clone', p.id, mode, $('#stCloneName').value, refs.map(r => r.path));
      t.disabled = false;
      if (!res.ok) return toast(res.error, 'error');
      closeModal();
      if (S.dirty) S.dirty = false;  // đã hỏi trước khi mở dialog
      await loadList();
      await open(res.project.id);
      if (mode === 'idea') { S.editIdea = true; S.ideaDraft = res.project.idea; render(); }
      toast(`Đã nhân bản → “${res.project.name}”${mode === 'idea' ? ' — sửa ý tưởng rồi bấm “Lưu & viết lại storyboard”' : ''}`, 'ok');
    };
  }

  async function create(btn) {
    const d = S.draft;
    if (S.batch) return createBatch(btn);
    if ((d.idea || '').trim().length < 10) return toast('Hãy mô tả ý tưởng video', 'warn');
    btn.disabled = true;
    const res = await api(CFG.api + 'create', { idea: d.idea, name: d.name, refs: S.refs, logo: S.newLogo || '', options: d.options,
      ref_video: S.newRefVideo || null });
    btn.disabled = false;
    if (!res.ok) return toast(res.error, 'error');
    S.tasks[res.result.task] = res.result.project.id;
    S.cur = res.result.project; S.draft = clone(S.cur); S.dirty = false; S.refs = []; S.newLogo = ''; S.newRefVideo = null; S.logs = [];
    S.progress = { pct: 0, status: 'Đang viết storyboard' };
    toast(d.options.auto ? 'Đang viết storyboard rồi tự làm video…' : 'Đang viết storyboard…', 'ok');
    await loadList();
    render();
  }

  async function createBatch(btn) {
    const d = S.draft;
    const n = ideaLines(d.idea).length;
    if (!n) return toast('Nhập ít nhất 1 ý tưởng (mỗi dòng 1 ý tưởng, tối thiểu 1 câu)', 'warn');
    if (n > 20) return toast(`Tối đa 20 ý tưởng mỗi lần (đang có ${n})`, 'warn');
    if (!confirm(`Tạo ${n} video? Mỗi video sẽ tự viết storyboard, tạo ảnh + clip từng cảnh rồi ghép — dùng lượt của các model đã chọn.`)) return;
    btn.disabled = true;
    const res = await api(CFG.api + 'create_batch', { idea: d.idea, name: d.name, refs: S.refs, logo: S.newLogo || '', options: d.options,
      ref_video: S.newRefVideo || null });
    btn.disabled = false;
    if (!res.ok) return toast(res.error, 'error');
    res.result.tasks.forEach((task, i) => { S.tasks[task] = res.result.projects[i].id; });
    S.draft = null; S.refs = []; S.newLogo = ''; S.cur = null;
    toast(`Đã tạo ${res.result.projects.length} dự án — đang xếp hàng làm video`, 'ok');
    await loadList();
    render();
  }

  async function save(notify) {
    const d = S.draft;
    const res = await api(CFG.api + 'save', S.cur.id, { name: d.name, idea: d.idea, options: d.options, bible: d.bible,
      ref_video: d.ref_video || null,
      scenes: d.scenes.map(s => ({ index: s.index, title: s.title, narration: s.narration, speaker: s.speaker || '', image_prompt: s.image_prompt,
        motion_prompt: s.motion_prompt, seconds: s.seconds, lines: s.lines || [],
        ...(Array.isArray(s.cast) ? { cast: s.cast } : {}) })) });
    if (!res.ok) { toast(res.error, 'error'); return false; }
    S.cur = res.project; S.draft = clone(S.cur); S.dirty = false;
    if (notify) toast('Đã lưu storyboard', 'ok');
    render();
    return true;
  }

  async function start(action, indexes = [], what = 'both') {
    if (S.dirty && !(await save(false))) return;
    const res = await api(CFG.api + 'start', S.cur.id, action, indexes, what);
    if (!res.ok) return toast(res.error, 'error');
    S.tasks[res.task] = S.cur.id;
    S.logs = []; S.progress = { pct: 0, status: 'Đang chờ tới lượt' };
    toast({ make: indexes.length ? `Đang làm lại ${indexes.length} cảnh rồi ghép video…` : 'Đang làm các cảnh rồi ghép video…',
      assemble: 'Đang ghép video…', storyboard: 'Đang viết lại storyboard…',
      scenes: 'Đang làm lại cảnh…',
      post: what === 'fresh' ? 'Đang hỏi AI gợi ý hậu kỳ mới rồi ghép lại…' : 'Đang chạy hậu kỳ AI rồi ghép lại…' }[action], 'ok');
  }

  // ------------------------------------------------------------ sự kiện backend (studio_*)
  function update(event, data) {
    const visible = !$(CFG.page).classList.contains('hidden');
    if (event === 'studio_update') {
      const i = S.projects.findIndex(p => p.id === data.id);
      if (i >= 0) S.projects[i] = data; else S.projects.unshift(data);
      if (S.cur && S.cur.id === data.id) { S.cur = data; if (!S.dirty) S.draft = clone(data); }
    } else if (event === 'studio_tasks') {  // biết tác vụ nào thuộc dự án nào (kể cả tác vụ chạy từ "Chạy tiếp tất cả")
      (data.tasks || []).forEach(t => { if (t.studio) S.tasks[t.id] = t.studio; });
      return;
    } else if (event === 'studio_log' || event === 'studio_progress') {
      if (!S.cur || S.tasks[data.task] !== S.cur.id) return;
      if (event === 'studio_log') S.logs.push(data);
      else S.progress = { pct: data.pct, status: data.status, stage: data.stage };
      if (visible) paintLive();  // chỉ vẽ lại khung tiến trình / nhật ký
      return;
    } else if (event === 'studio_done' || event === 'studio_error' || event === 'studio_cancelled') {
      if (event === 'studio_error') toast(`${CFG.label}: ${data.message}`, 'error');
      if (event === 'studio_done' && data.result && data.result.status === 'done') toast(`${CFG.label}: video đã xong — có trong Thư viện video`, 'ok');
      loadList().then(() => { if (visible) render(); });
      return;
    } else return;
    const typing = document.activeElement && document.activeElement.closest && document.activeElement.closest(`${CFG.body} textarea, ${CFG.body} input`);
    // đang xem video (cảnh / video hoàn chỉnh) → chờ dừng xem rồi mới vẽ lại, không làm video tải lại giữa chừng
    const playing = [...document.querySelectorAll(`${CFG.body} video`)].some(v => !v.paused && !v.ended);
    if (visible && (typing || playing)) { S.pendingRender = true; return; }
    if (visible) render();
  }

  // video dừng / hết → vẽ lại phần đã hoãn
  document.addEventListener('pause', e => {
    if (S.pendingRender && e.target.closest && e.target.closest(CFG.body) && !$(CFG.page).classList.contains('hidden')) render();
  }, true);

  return { show, update };
}

window.StudioPage = createStudioPage({ body: '#studioBody', page: '#page-studio', api: 'studio_', label: 'Studio' });
window.MuseStudioPage = createStudioPage({ body: '#mstudioBody', page: '#page-mstudio', api: 'mstudio_', label: 'Studio Muse AI', muse: true });
