/* Nhóm chức năng "Chiến dịch" — phòng marketing AI 6 vai trò (dùng chung helper của app.js: $, $$, api, esc, toast, openModal…). */
(() => {
  'use strict';

  const C = {
    view: '', overview: null, lib: null, models: [], keys: {}, detail: null, cid: '', tab: 'brief',
    libTab: 'products', histTab: 'posts', form: null, fbPages: [], logs: [], refreshTimer: null, detailOpen: false,
  };
  const STATUS = { draft: 'Nháp', running: 'Đang chạy', waiting: 'Chờ bạn', approved: 'Đã duyệt', posted: 'Đã đăng',
    error: 'Lỗi', cancelled: 'Đã huỷ', done: 'Hoàn tất' };
  const STAGE_STATUS = { pending: 'Chờ', running: 'Đang chạy', done: 'Xong', error: 'Lỗi', waiting: 'Chờ bạn', skipped: 'Bỏ qua' };
  const ROLE_NAMES = { 'truong-phong-marketing': 'Trưởng phòng', 'nv-y-tuong': 'NV ý tưởng', 'nv-content': 'NV content',
    'nv-hinh-anh': 'NV hình ảnh', 'nv-dang-bai-facebook': 'NV đăng bài', 'nv-video': 'NV video', 'he-thong': 'Hệ thống' };
  const TABS = [['brief', 'Brief'], ['ideas', '5 ý tưởng'], ['content', 'Content'], ['images', 'Ảnh'], ['web', 'Thông tin web'],
    ['review', 'Đánh giá'], ['post', 'Đăng bài'], ['report', 'Báo cáo']];
  const STAGE_TAB = { 1: 'brief', 2: 'ideas', 3: 'ideas', 4: 'content', 5: 'images', 6: 'images', '6b': 'images', 7: 'review',
    '7b': 'post', '7c': 'post', 8: 'report' };
  const libUrl = rel => `/campaign-lib/${rel.split('/').map(encodeURIComponent).join('/')}`;
  const money = v => `$${Number(v || 0).toFixed(Number(v || 0) < 1 ? 4 : 2)}`;
  // Giống campaign/pipeline.TEXT_ENGINES: model ảnh vẽ chữ tiếng Việt đọc được
  const TEXT_ENGINES = ['openai_api', 'chatgpt_browser', 'gemini_api', 'gemini_browser'];
  // Giống campaign/media.py
  const VIDEO_KINDS = { auto: 'Trưởng phòng tự chọn (khuyên dùng)', sale: 'Video bán hàng — từ ảnh + ảnh sản phẩm, giọng đọc, phụ đề, giá',
    explainer: 'Video kiến thức — giải thích / top mẹo, có giọng đọc', template: 'Video AI theo template ngành hàng (Grok)',
    ai: 'Video AI từ ảnh — Grok làm ảnh chính chuyển động' };
  const POST_TYPES = { album: 'Album ảnh', video: 'Video', anh: 'Ảnh đơn' };
  const toLocalInput = v => String(v || '').replace(' ', 'T');
  const fromLocalInput = v => String(v || '').replace('T', ' ').slice(0, 16);
  const linesOf = text => String(text || '').split('\n').map(s => s.trim()).filter(Boolean);
  // Giống campaign/ai.provider_of: model gpt-* / o<số> → OpenAI, còn lại → Anthropic (Claude)
  const PROVIDER_NAMES = { anthropic: 'Anthropic', openai: 'OpenAI' };
  const providerOf = model => /^(gpt-|o\d)/.test(model || '') ? 'openai' : 'anthropic';
  /** Nhà cung cấp mà các vai trò đang dùng nhưng chưa có khoá API (chưa nạp thư viện → chỉ xét Anthropic). */
  const missingKeys = () => {
    const roles = Object.values((C.lib && C.lib.roles) || {});
    const used = new Set(roles.length ? roles.map(r => providerOf(r.model)) : ['anthropic']);
    return [...used].filter(p => !C.keys[p]).map(p => PROVIDER_NAMES[p]);
  };

  // ================================================================ Markdown tối giản (chỉ để hiển thị)
  function md(text) {
    const out = [];
    let inCode = false;
    for (const raw of String(text || '').replace(/\r/g, '').split('\n')) {
      if (raw.startsWith('```')) { out.push(inCode ? '</pre>' : '<pre class="md-pre">'); inCode = !inCode; continue; }
      if (inCode) { out.push(esc(raw) + '\n'); continue; }
      const line = esc(raw).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/(https?:\/\/[^\s<)|]+)/g, '<a href="$1" data-ext>$1</a>');
      if (/^#{1,6}\s/.test(raw)) {
        const n = Math.min(raw.match(/^#+/)[0].length + 1, 5);
        out.push(`<h${n}>${line.replace(/^#+\s*/, '')}</h${n}>`);
      } else if (/^\s*\|/.test(raw)) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(raw)) continue;
        out.push(`<table class="md-table"><tr>${line.trim().replace(/^\||\|$/g, '').split('|').map(c => `<td>${c.trim()}</td>`).join('')}</tr></table>`);
      } else if (/^\s*[-*•]\s/.test(raw)) out.push(`<div class="md-li">${line.replace(/^\s*[-*•]\s/, '')}</div>`);
      else if (!raw.trim()) out.push('<div class="md-gap"></div>');
      else out.push(`<p>${line}</p>`);
    }
    if (inCode) out.push('</pre>');
    return out.join('').replace(/<\/table><table class="md-table">/g, '');
  }

  // ================================================================ điều hướng & sự kiện
  async function show(view) {
    C.view = view;
    if (view === 'camp-list') { await loadOverview(); if (C.cid && C.detailOpen) openDetail(C.cid); else showList(); }
    if (view === 'camp-new') await renderForm();
    if (view === 'camp-lib') await renderLibrary();
    if (view === 'camp-history') await renderHistory();
  }

  function onEvent(event, data) {
    if (event === 'campaign_log') {
      if (data.campaign === C.cid && C.detailOpen) { C.logs.push(data); appendLog(data); }
      return;
    }
    if (event === 'campaign_update') {
      clearTimeout(C.refreshTimer);  // gom nhiều cập nhật liên tiếp thành 1 lần tải lại
      C.refreshTimer = setTimeout(async () => {
        await loadOverview();
        if (C.view !== 'camp-list') return;
        if (C.detailOpen && data.id === C.cid) openDetail(C.cid, true);
        else if (!C.detailOpen) renderList();
      }, 300);
    }
    if (event === 'campaign_error') toast(data.message, 'error');
  }

  async function loadOverview() {
    const res = await api('campaign_overview');
    if (!res.ok) return;
    C.overview = res;
    C.keys = res.keys;
    $('#sbCampCount').textContent = res.campaigns.length;
    $('#sbCampRunning').classList.toggle('hidden', !res.running.length);
  }

  async function loadLibrary() {
    const res = await api('camp_library');
    if (res.ok) { C.lib = res.library; C.models = res.models; C.keys = res.keys; C.imageEngine = res.image_engine; }
    return C.lib;
  }

  // ================================================================ B. danh sách chiến dịch
  function showList() {
    C.detailOpen = false;
    $('#campListView').classList.remove('hidden');
    $('#campDetailView').classList.add('hidden');
    renderList();
  }

  function renderList() {
    const o = C.overview;
    if (!o) return;
    const s = o.stats;
    const stat = (label, value, cls = '') => `<div class="camp-stat ${cls}"><small>${label}</small><b>${value}</b></div>`;
    $('#campStats').innerHTML = stat('Chiến dịch tuần này', s.week, 'main') + stat('Đang chạy', s.running)
      + stat('Chờ bạn xử lý', s.waiting, s.waiting ? 'warn' : '') + stat('Bài đã đăng', s.posts)
      + stat('Chi phí API ước tính', money(s.cost_usd)) + stat('Tổng chiến dịch', s.total);
    const sel = $('#campFilterStatus');
    if (sel.options.length < 2) {  // gắn sự kiện một lần
      sel.innerHTML += Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
      ['campSearch', 'campFilterStatus', 'campFilterProduct', 'campFilterDate'].forEach(id => {
        $(`#${id}`).addEventListener(id === 'campSearch' ? 'input' : 'change', renderList);
      });
      $('#campGrid').onclick = e => { const card = e.target.closest('[data-cid]'); if (card) openDetail(card.dataset.cid); };
      $$('[data-go-view]').forEach(b => { b.onclick = () => navigate(b.dataset.goView); });
    }
    const products = [...new Set(o.campaigns.map(c => c.product).filter(Boolean))];
    const prodSel = $('#campFilterProduct');
    const cur = prodSel.value;
    prodSel.innerHTML = '<option value="">Mọi sản phẩm</option>' + products.map(p => `<option>${esc(p)}</option>`).join('');
    prodSel.value = products.includes(cur) ? cur : '';
    const q = $('#campSearch').value.trim().toLowerCase();
    const st = $('#campFilterStatus').value;
    const days = +$('#campFilterDate').value;
    const since = days ? new Date(Date.now() - days * 864e5).toISOString().slice(0, 19) : '';
    const list = o.campaigns.filter(c => (!q || c.name.toLowerCase().includes(q)) && (!st || c.status === st)
      && (!prodSel.value || c.product === prodSel.value) && (!since || (c.created_at || '') >= since));
    $('#campGrid').innerHTML = list.length ? list.map(c => `
      <div class="camp-card" data-cid="${esc(c.id)}" role="button" tabindex="0">
        <div class="camp-thumb">${c.thumb ? `<img src="/media/_campaigns/${esc(c.id)}/${esc(c.thumb)}" alt="" loading="lazy">` : '<span>Chưa có ảnh</span>'}
          <span class="camp-st ${esc(c.status)}">${esc(STATUS[c.status] || c.status)}</span>
          ${o.running.includes(c.id) ? '<i class="camp-live" title="Đang chạy"></i>' : ''}</div>
        <div class="camp-card-body">
          <b title="${esc(c.name)}">${esc(c.name)}</b>
          <small>${esc(c.product || 'Chưa gắn sản phẩm')}</small>
          <div class="camp-card-meta"><span>${esc(fmtTime(c.created_at))}</span>
            ${c.version > 1 ? `<span class="tag">v${c.version}</span>` : ''}
            ${c.verdict ? `<span class="camp-verdict ${c.verdict === 'DUYET' ? 'ok' : 'bad'}">${c.verdict === 'DUYET' ? '✓ Duyệt' : 'Cần sửa'}</span>` : ''}
            ${c.posts ? `<span>📣 ${c.posts}</span>` : ''}<span class="mono">${money((c.cost || {}).usd)}</span></div>
          ${c.waiting ? `<div class="camp-wait">⏳ ${esc(c.waiting.message || '')}</div>` : ''}
        </div>
      </div>`).join('')
      : `<div class="empty">${o.campaigns.length ? 'Không có chiến dịch khớp bộ lọc.' : 'Chưa có chiến dịch nào — bấm “+ Tạo chiến dịch”.'}</div>`;
  }

  // ================================================================ D. chi tiết chiến dịch
  async function openDetail(cid, keepScroll = false) {
    const res = await api('campaign_get', cid);
    if (!res.ok) { toast(res.error, 'error'); return showList(); }
    const scroll = $('#page-camp-list').scrollTop;
    const logScroll = $('#campLog') ? $('#campLog').scrollTop : null;
    C.cid = cid;
    C.detail = res.campaign;
    C.logs = res.campaign.logs || [];
    C.detailOpen = true;
    C.fbPages = res.campaign.fb_pages || [];
    $('#campListView').classList.add('hidden');
    $('#campDetailView').classList.remove('hidden');
    const drafts = keepScroll ? saveDrafts() : null;
    renderDetail();
    if (drafts) restoreDrafts(drafts);
    if (keepScroll) { $('#page-camp-list').scrollTop = scroll; if (logScroll === null) $('#campLog').scrollTop = 1e9; }
  }

  // Giữ chữ người dùng đang gõ (trả lời câu hỏi, caption) khi chi tiết tự làm mới
  function saveDrafts() {
    return { answers: $('#campAnswers')?.value, captions: $$('#campPanel [data-caption]').map(t => t.value) };
  }
  function restoreDrafts(d) {
    if (d.answers && $('#campAnswers')) $('#campAnswers').value = d.answers;
    $$('#campPanel [data-caption]').forEach((t, i) => { if (d.captions[i] !== undefined && !t.readOnly) t.value = d.captions[i]; });
  }

  const stageList = () => (C.overview && C.overview.stages) || [];

  function renderDetail() {
    const d = C.detail;
    const running = d.running;
    const cost = d.cost || {};
    const canResume = !running && ['error', 'cancelled'].includes(d.status);
    $('#campDetailView').innerHTML = `
      <div class="camp-detail-head">
        <button class="btn ghost" data-act="back" type="button">← Danh sách</button>
        <div class="camp-title"><b>${esc(d.name)}</b>
          <small class="mono">${esc(d.id)}${d.version > 1 ? ` · phiên bản ${d.version}` : ''}${d.parent ? ` · từ ${esc(d.parent)}` : ''}</small></div>
        <span class="camp-st big ${esc(d.status)}">${esc(STATUS[d.status] || d.status)}</span>
        <div class="row camp-actions">
          ${canResume ? '<button class="btn primary sm" data-act="resume" type="button">▶ Chạy tiếp</button>' : ''}
          ${running ? '<button class="btn danger sm" data-act="cancel" type="button">■ Huỷ</button>' : ''}
          <button class="btn ghost sm" data-act="rerun" type="button" ${running ? 'disabled' : ''}>Chạy lại từ…</button>
          <button class="btn ghost sm" data-act="dup" type="button">Nhân bản</button>
          <button class="btn ghost sm" data-act="folder" type="button">Thư mục</button>
          <button class="btn ghost sm" data-act="zip" type="button">Tải ZIP</button>
        </div>
      </div>
      <div class="camp-steps">${stageList().map(s => {
        const st = (d.stages[s.key] || {}).status || 'pending';
        return `<button class="camp-step ${st}" data-stage="${s.key}" type="button" title="${esc(s.file || '')}">
          <i>${st === 'done' ? '✓' : st === 'error' ? '!' : st === 'skipped' ? '–' : st === 'waiting' ? '⏳' : s.key}</i>
          <span>${esc(s.name)}</span><small>${esc(ROLE_NAMES[s.role] || '')} · ${esc(STAGE_STATUS[st] || st)}</small></button>`;
      }).join('')}</div>
      ${renderBanner(d)}
      <div class="camp-detail-body">
        <div class="camp-main">
          <div class="camp-tabs">${TABS.map(([k, l]) => `<button class="camp-tab ${C.tab === k ? 'on' : ''}" data-tab="${k}" type="button">${l}</button>`).join('')}</div>
          <div class="camp-panel" id="campPanel">${renderTab()}</div>
        </div>
        <aside class="camp-side">
          <div class="card camp-cost"><div class="card-title">CHI PHÍ ƯỚC TÍNH</div>
            <div class="camp-cost-row"><span>AI (Claude / OpenAI)</span><b>${money(cost.usd)}</b></div>
            <div class="camp-cost-row"><span>Token vào / ra</span><b class="mono">${(cost.tokens_in || 0).toLocaleString('vi-VN')} / ${(cost.tokens_out || 0).toLocaleString('vi-VN')}</b></div>
            <div class="camp-cost-row"><span>Lượt gọi AI</span><b>${cost.calls || 0}</b></div>
            <div class="camp-cost-row"><span>Ảnh / video đã tạo</span><b>${cost.images || cost.grok_images || 0} / ${cost.videos || 0}</b></div></div>
          <div class="log-card camp-log"><div class="log-head"><span>NHẬT KÝ CHẠY</span>${running ? '<span class="camp-live-text">● trực tiếp</span>' : ''}</div>
            <div class="log mono" id="campLog"></div></div>
        </aside>
      </div>`;
    C.logs.slice(-300).forEach(appendLog);
    bindDetail();
  }

  function appendLog(entry) {
    const log = $('#campLog');
    if (!log) return;
    const line = document.createElement('div');
    line.className = `ln ${entry.level || 'info'}`;
    line.innerHTML = `<span class="t">${esc(entry.time)}</span><i class="dot"></i><span class="msg">${esc(entry.message)}</span>`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  function renderBanner(d) {
    const w = d.waiting;
    if (d.status === 'error') {
      const stage = Object.entries(d.stages).find(([, v]) => v.status === 'error');
      return `<div class="camp-banner bad"><div><b>Lỗi${stage ? ` ở chặng ${stage[0]}` : ''}:</b> ${esc(stage ? stage[1].error : 'không rõ')}</div>
        <button class="btn primary sm" data-act="resume" type="button">▶ Chạy tiếp</button></div>`;
    }
    if (!w) return '';
    if (w.kind === 'brief_questions') {
      return `<div class="camp-banner warn col"><b>⏳ ${esc(w.message)}</b>
        <ol class="camp-questions">${(w.payload || []).map(q => `<li>${esc(q)}</li>`).join('')}</ol>
        <textarea id="campAnswers" rows="4" placeholder="Trả lời từng câu (VD: 1. Giá KM 299.000đ  2. Không có quy cách…)"></textarea>
        <div class="row"><button class="btn primary" data-act="answer" type="button">Gửi câu trả lời & chạy tiếp</button></div></div>`;
    }
    if (w.kind === 'pick_idea') {
      return `<div class="camp-banner warn col"><b>⏳ ${esc(w.message)}</b><div class="camp-ideas grid">${(w.payload || d.ideas || []).map(idea => `
        <div class="camp-idea"><span class="camp-idea-no">${esc(idea.so)}</span><b>${esc(idea.ten || '')}</b>
          <p>${esc(idea.thong_diep || '')}</p><small>${esc(idea.mo_ta || '')}</small>
          <button class="btn primary sm" data-act="pick" data-no="${esc(idea.so)}" type="button">Chọn ý tưởng này</button></div>`).join('')}</div></div>`;
    }
    if (w.kind === 'review_stop' || w.kind === 'post_stop') {
      return `<div class="camp-banner warn col"><b>⏳ ${esc(w.message)}</b>
        <ul class="camp-fixes">${(w.payload || []).map(f => `<li><b>${esc(ROLE_NAMES[f.nhan_vien] || f.nhan_vien || '')}</b>${f.anh ? ` · ${esc(f.anh)}` : ''}: ${esc(f.noi_dung || '')}</li>`).join('')}</ul>
        <div class="row"><button class="btn primary" data-act="approve" type="button">Tôi đã xem — cho đi tiếp</button>
          <button class="btn ghost" data-act="rerun" type="button">Chạy lại từ chặng…</button></div></div>`;
    }
    if (w.kind === 'publish') {
      return `<div class="camp-banner ok"><div><b>✓ Kế hoạch đăng đã sẵn sàng.</b> Kiểm tra từng bài ở tab <b>Đăng bài</b>, đánh dấu Fanpage/bài rồi bấm <b>Đồng ý đăng</b>.</div>
        <button class="btn primary sm" data-tab="post" type="button">Xem kế hoạch đăng</button></div>`;
    }
    return `<div class="camp-banner warn">⏳ ${esc(w.message || '')}</div>`;
  }

  function fileBlock(name, empty) {
    const text = (C.detail.files || {})[name];
    return text ? `<div class="md">${md(text)}</div>` : `<div class="empty">${empty}</div>`;
  }

  function renderTab() {
    const d = C.detail;
    switch (C.tab) {
      case 'brief': return fileBlock('00-brief.md', 'Chưa có brief.');
      case 'ideas': return `${(d.ideas || []).length ? `<div class="camp-ideas grid">${d.ideas.map(i => `
          <div class="camp-idea ${String(i.so) === String(d.chosen_idea) ? 'chosen' : ''}"><span class="camp-idea-no">${esc(i.so)}</span>
            <b>${esc(i.ten || '')}</b><p>${esc(i.thong_diep || '')}</p><small>${esc(i.mo_ta || '')}</small>
            ${String(i.so) === String(d.chosen_idea) ? '<span class="tag">✓ ĐƯỢC CHỌN</span>' : ''}</div>`).join('')}</div>` : ''}
        <details class="camp-more" ${!(d.ideas || []).length ? 'open' : ''}><summary>01-y-tuong.md</summary>${fileBlock('01-y-tuong.md', 'Chưa có ý tưởng.')}</details>
        <details class="camp-more"><summary>02-chon-y-tuong.md</summary>${fileBlock('02-chon-y-tuong.md', 'Chưa chọn ý tưởng.')}</details>`;
      case 'content': return d.content_html ? `
        <div class="row camp-tools">
          <button class="btn ghost sm" data-act="edit-content" type="button">✎ Sửa trực tiếp</button>
          <button class="btn ghost sm" data-act="rewrite" type="button" ${d.running ? 'disabled' : ''}>↻ Viết lại</button>
          ${d.has_pdf ? '<button class="btn ghost sm" data-act="open-file" data-file="03-content.pdf" type="button">Mở PDF</button>' : ''}
          <button class="btn ghost sm" data-act="open-file" data-file="03-content.html" type="button">Mở HTML</button></div>
        <iframe class="camp-frame" src="${esc(d.content_html)}?v=${esc(d.updated_at || '')}"></iframe>` : fileBlock('03-content.md', 'Chưa có content.');
      case 'images': return renderImagesTab();
      case 'web': return fileBlock('thong-tin-web.md', ((d.product || {}).links || []).length ? 'Chưa đọc trang web.' : 'Chiến dịch không có link trang web sản phẩm.');
      case 'review': {
        const v = d.verdict;
        return `${v ? `<div class="camp-verdict-box ${v.verdict === 'DUYET' ? 'ok' : 'bad'}"><b>${v.verdict === 'DUYET' ? '✓ DUYỆT' : '✕ CẦN SỬA'}</b>
          <span>Điểm: <b>${esc(v.score ?? '—')}</b></span>${v.manual ? '<span class="tag">người dùng tự duyệt</span>' : ''}
          <span>Vòng sửa đã dùng: ${d.revision || 0}/1</span></div>
          ${(v.fixes || []).length ? `<ul class="camp-fixes">${v.fixes.map(f => `<li><b>${esc(ROLE_NAMES[f.nhan_vien] || f.nhan_vien || '')}</b>${f.anh ? ` · ${esc(f.anh)}` : ''}: ${esc(f.noi_dung || '')}</li>`).join('')}</ul>` : ''}` : ''}
          ${fileBlock('06-danh-gia.md', 'Trưởng phòng chưa duyệt.')}`;
      }
      case 'post': return renderPostTab();
      case 'report': return fileBlock('bao-cao.md', 'Chưa có báo cáo (chặng 8).');
      default: return '';
    }
  }

  function renderImagesTab() {
    const d = C.detail;
    const inputs = d.inputs_view || {};
    const thumbs = (urls, label) => urls.length ? `<div class="camp-inputs"><small>${label}</small><div>${urls.map(u => `<img src="${esc(u)}" alt="">`).join('')}</div></div>` : '';
    return `<div class="camp-images">${(d.images_view || []).map(im => `
        <div class="camp-image">
          <div class="camp-image-frame">${im.exists ? `<img src="${esc(im.url)}" alt="${esc(im.key)}">` : '<span>Chưa có ảnh</span>'}</div>
          <div class="camp-image-info"><b>${esc(im.name ? `${im.name} (${im.key})` : im.key)}</b>${im.idea ? `<p>${esc(im.idea)}</p>` : ''}
            ${(im.variant_urls || []).length > 1 ? `<div class="camp-variants"><small>Phương án (trưởng phòng chọn ${esc(im.picked)}/${esc(im.variants)}):</small>
              <div>${im.variant_urls.map((u, i) => `<img class="${i + 1 === im.picked ? 'on' : ''}" src="${esc(u)}" alt="">`).join('')}</div></div>` : ''}
            ${im.label ? `<div class="camp-label ${im.label.khop ? 'ok' : im.label.khop === false ? 'bad' : ''}">So nhãn: ${im.label.khop ? '✓ khớp' : im.label.khop === false ? '✕ chưa khớp' : '—'}
              <small>${esc(im.label.nhan_xet || '')}</small></div>` : ''}
            ${im.refs ? `<small class="muted">Ảnh mẫu đã gửi (theo thứ tự): ${esc(im.refs.join(', '))}</small>` : ''}
            ${im.prompt ? `<details class="camp-more"><summary>Prompt đã gửi model ảnh${im.engine ? ` (${esc(engineName(im.engine))})` : ''}</summary><pre class="md-pre">${esc(im.prompt)}</pre></details>` : ''}
            <div class="row camp-tools">
              ${im.extra ? '' : `<button class="btn ghost sm" data-act="redraw" data-key="${esc(im.key)}" type="button" ${d.running ? 'disabled' : ''}>↻ Vẽ lại ảnh này</button>`}
              ${im.exists ? `<button class="btn ghost sm" data-act="open-file" data-file="05-hinh-anh/${esc(im.key)}.png" type="button">Mở</button>` : ''}
            </div></div>
        </div>`).join('')}</div>
      ${renderVideoBox(d)}
      ${thumbs(inputs.products || [], 'Ảnh sản phẩm (luôn là ảnh mẫu đầu tiên)')}${thumbs(inputs.refs || [], 'Ảnh tham chiếu')}${thumbs(inputs.models || [], 'Người mẫu')}
      <details class="camp-more"><summary>Ý tưởng ảnh (y-tuong-anh.md)</summary>${fileBlock('05-hinh-anh/y-tuong-anh.md', 'Chưa có.')}</details>`;
  }

  function engineName(id) {
    return ((typeof state !== 'undefined' && state.boot && state.boot.image_engines) || {})[id]?.name || id;
  }

  function renderVideoBox(d) {
    const o = d.options || {};
    const videos = d.videos_view || [];
    if (!o.video && !videos.length) return '';
    const kind = !o.video_kind || o.video_kind === 'auto' ? 'trưởng phòng chọn loại' : (VIDEO_KINDS[o.video_kind] || '').split(' — ')[0];
    return `<div class="card camp-video"><div class="card-title">VIDEO <span class="tag">${esc(kind)}</span></div>
      ${videos.length ? `<div class="camp-videos">${videos.map(v => `<figure><video src="${esc(v.url)}" controls playsinline></video>
        <figcaption><b>${esc(v.key)}</b> · ${esc(v.label || '')}${v.template ? ` · ${esc(v.template)}` : ''}
          <button class="btn ghost sm" data-act="open-file" data-file="${esc(v.file)}" type="button">Mở</button></figcaption></figure>`).join('')}</div>`
        : '<div class="empty">Chưa có video — chặng 6b tạo sau khi có ảnh.</div>'}
      <div class="row camp-tools">
        <button class="btn ghost sm" data-act="remake-video" type="button" ${d.running || !(d.images_view || []).some(i => i.exists) ? 'disabled' : ''}>↻ Làm lại video</button></div></div>`;
  }

  function renderPostTab() {
    const d = C.detail;
    const waitingPublish = d.waiting && d.waiting.kind === 'publish';
    const plan = d.plan || [];
    const pages = C.fbPages;
    const posted = d.posts || [];
    return `${(d.options || {}).no_post ? '<div class="camp-banner">Chiến dịch chọn “Không đăng”.</div>' : ''}
      ${posted.length ? `<div class="card camp-posted-card"><div class="card-title">ĐÃ ĐĂNG</div>${posted.map(p => `<div class="camp-posted ${p.url ? 'ok' : 'bad'}">
        <b>STT ${esc(p.stt)}</b> · ${esc(POST_TYPES[p.loai] || '')} · ${esc(p.page || p.page_id || '')} · ${p.scheduled ? `<span class="tag">hẹn giờ ${esc(p.scheduled)}</span> ` : ''}${p.url ? `<a href="${esc(p.url)}" data-ext>${esc(p.url)}</a>` : p.id ? esc(p.id) : `LỖI — ${esc(p.error || '')}`}
        <small>${esc(fmtTime(p.at))} · ${esc(p.by || '')}</small></div>`).join('')}</div>` : ''}
      ${(d.ads || []).length ? `<div class="card camp-posted-card"><div class="card-title">QUẢNG CÁO <span class="tag">TẠM DỪNG — bật ở trang Quảng cáo Facebook</span></div>${d.ads.map(a => `<div class="camp-posted ${a.ad_id ? 'ok' : 'bad'}">
        <b>${esc(a.page || a.page_id || '')}</b> · ${a.ad_id ? `quảng cáo ${esc(a.ad_id)} · mục tiêu ${esc(a.objective || '')}` : `LỖI — ${esc(a.error || '')}`}</div>`).join('')}</div>` : ''}
      ${plan.length ? `<div class="camp-plan">${plan.map(p => `
        <div class="card camp-post" data-stt="${esc(p.stt)}">
          <div class="camp-post-head">
            ${waitingPublish ? '<label class="check"><input type="checkbox" data-pick checked> Đăng bài này</label>' : ''}
            <b>STT ${esc(p.stt)} · ${esc(POST_TYPES[p.loai] || p.loai || 'Album ảnh')}</b>
            <select data-page ${waitingPublish ? '' : 'disabled'}>${pages.length ? pages.map(pg => `<option value="${esc(pg.id)}" ${pg.id === p.page_id ? 'selected' : ''}>${esc(pg.name)}</option>`).join('')
              : `<option value="${esc(p.page_id)}">${esc(p.page || 'Chưa kết nối Fanpage')}</option>`}</select></div>
          <div class="camp-post-files">${(p.files || []).map(f => /\.(mp4|mov|webm|m4v)$/i.test(f)
            ? `<video src="/media/_campaigns/${esc(d.id)}/${esc(f)}" muted playsinline controls></video>`
            : `<img src="/media/_campaigns/${esc(d.id)}/${esc(f)}" alt="">`).join('')}</div>
          <label class="field camp-when"><span>Giờ đăng <small class="muted">(trống = đăng ngay khi bạn đồng ý)</small></span>
            <input type="datetime-local" data-when value="${esc(toLocalInput(p.gio_dang))}" ${waitingPublish ? '' : 'disabled'}></label>
          <textarea data-caption rows="8" ${waitingPublish ? '' : 'readonly'}>${esc(p.caption || '')}</textarea>
        </div>`).join('')}</div>
        ${waitingPublish ? `<div class="camp-publish"><span class="muted">Chỉ đăng khi bạn bấm và xác nhận lần 2. Ứng dụng ghi lại ai đồng ý và lúc nào.</span>
          <button class="btn primary" data-act="publish" type="button">Đồng ý đăng…</button></div>` : ''}`
      : '<div class="empty">Chưa có kế hoạch đăng (chặng 7b).</div>'}
      <details class="camp-more"><summary>ke-hoach-dang.md</summary>${fileBlock('08-dang-bai/ke-hoach-dang.md', 'Chưa có.')}</details>`;
  }

  function bindDetail() {
    $('#campDetailView').onclick = async e => {
      const ext = e.target.closest('[data-ext]');
      if (ext) { e.preventDefault(); api('open_url', ext.getAttribute('href')); return; }
      const tab = e.target.closest('[data-tab]');
      if (tab) { C.tab = tab.dataset.tab; renderDetail(); return; }
      const step = e.target.closest('[data-stage]');
      if (step) { C.tab = STAGE_TAB[step.dataset.stage] || C.tab; renderDetail(); return; }
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      const act = btn.dataset.act;
      const d = C.detail;
      const run = async (method, args, okText) => {
        btn.disabled = true;
        const res = await api(method, ...args);
        btn.disabled = false;
        if (!res.ok) { toast(res.error, 'error'); return null; }
        if (okText) toast(okText, 'ok');
        return res;
      };
      if (act === 'back') { showList(); await loadOverview(); renderList(); }
      else if (act === 'resume') { if (await run('campaign_resume', [d.id], 'Đã chạy tiếp chiến dịch')) openDetail(d.id); }
      else if (act === 'cancel') { if (confirm('Huỷ chiến dịch đang chạy? (file đã làm vẫn được giữ)')) await run('campaign_cancel', [d.id], 'Đang huỷ…'); }
      else if (act === 'rerun') openRerun();
      else if (act === 'dup') {
        if (!confirm('Nhân bản: tạo chiến dịch mới với cùng yêu cầu và ảnh đầu vào, chạy lại từ đầu?')) return;
        const res = await run('campaign_duplicate', [d.id], 'Đã nhân bản chiến dịch');
        if (res) openDetail(res.result.id);
      } else if (act === 'folder') run('campaign_open', [d.id, '']);
      else if (act === 'zip') { const res = await run('campaign_zip', [d.id]); if (res) toast(`Đã tạo ZIP: ${res.path}`, 'ok'); }
      else if (act === 'open-file') run('campaign_open', [d.id, btn.dataset.file]);
      else if (act === 'answer') {
        const text = $('#campAnswers').value.trim();
        if (!text) { toast('Hãy trả lời các câu hỏi', 'warn'); return; }
        if (await run('campaign_answer', [d.id, text], 'Đã gửi câu trả lời — trưởng phòng viết lại brief')) openDetail(d.id);
      } else if (act === 'pick') {
        if (await run('campaign_pick_idea', [d.id, +btn.dataset.no], `Đã chọn ý tưởng ${btn.dataset.no}`)) openDetail(d.id);
      } else if (act === 'approve') {
        if (!confirm('Bạn tự duyệt và cho dây chuyền đi tiếp dù trưởng phòng vẫn CẦN SỬA?')) return;
        if (await run('campaign_approve_manually', [d.id], 'Đã cho đi tiếp')) openDetail(d.id);
      } else if (act === 'edit-content') openContentEditor();
      else if (act === 'rewrite') {
        const note = prompt('Yêu cầu viết lại (để trống = viết bản mới cùng ý tưởng):', '');
        if (note === null) return;
        if (await run('campaign_rewrite_content', [d.id, note], 'NV content đang viết lại…')) openDetail(d.id);
      } else if (act === 'redraw') {
        const note = prompt(`Yêu cầu khi vẽ lại ảnh ${btn.dataset.key} (để trống = vẽ lại theo chỉ đạo cũ):`, '');
        if (note === null) return;
        if (await run('campaign_redraw', [d.id, btn.dataset.key, note], `Đang vẽ lại ảnh ${btn.dataset.key} (chỉ ảnh này)`)) openDetail(d.id);
      } else if (act === 'remake-video') {
        if (await run('campaign_remake_video', [d.id], 'Đang làm lại video (xem tiến trình ở trang Tạo video)')) openDetail(d.id);
      } else if (act === 'publish') confirmPublish();
    };
  }

  function openRerun() {
    const d = C.detail;
    const stages = stageList().filter(s => s.key !== '0' && s.key !== '7c');
    openModal('CHẠY LẠI', 'Chạy lại từ chặng…', `<div class="form">
      <p class="muted">Không ghi đè chiến dịch này: ứng dụng tạo <b>phiên bản mới</b>, chép file các chặng trước rồi chạy lại từ chặng bạn chọn.</p>
      <div class="mrows">${stages.map(s => `<button class="mrow" data-from="${s.key}" type="button"><span class="micon">${esc(s.key)}</span>
        <span class="mtext"><b>${esc(s.name)}</b><small>${esc(ROLE_NAMES[s.role] || '')} · ${esc(s.file || '')}</small></span></button>`).join('')}</div></div>`, true);
    $('#modalBody').onclick = async e => {
      const row = e.target.closest('[data-from]');
      if (!row) return;
      const res = await api('campaign_rerun_from', d.id, row.dataset.from);
      if (!res.ok) return toast(res.error, 'error');
      closeModal();
      toast(`Đã tạo phiên bản mới, chạy từ chặng ${row.dataset.from}`, 'ok');
      openDetail(res.result.id);
    };
  }

  function openContentEditor() {
    const d = C.detail;
    openModal('CONTENT', 'Sửa trực tiếp content', `<div class="form">
      <p class="muted">Sửa xong bấm Lưu: ứng dụng tự xuất lại HTML + PDF, bản cũ cất vào thư mục <code>_cu/</code>.</p>
      <textarea id="campContentText" rows="22" class="mono">${esc(d.files['03-content.md'] || '')}</textarea>
      <div class="modal-foot"><button class="btn primary" id="campContentSave" type="button">Lưu & xuất lại HTML/PDF</button></div></div>`);
    $('#modalBody').onclick = null;
    $('#campContentSave').onclick = async () => {
      const btn = $('#campContentSave');
      btn.disabled = true; btn.textContent = 'Đang xuất PDF…';
      const res = await api('campaign_save_content', d.id, $('#campContentText').value);
      btn.disabled = false; btn.textContent = 'Lưu & xuất lại HTML/PDF';
      if (!res.ok) return toast(res.error, 'error');
      closeModal();
      toast('Đã lưu content và xuất lại HTML/PDF', 'ok');
      openDetail(d.id);
    };
  }

  function confirmPublish() {
    const d = C.detail;
    const items = $$('#campPanel .camp-post').filter(el => el.querySelector('[data-pick]')?.checked).map(el => ({
      stt: +el.dataset.stt, page_id: el.querySelector('[data-page]').value, caption: el.querySelector('[data-caption]').value,
      page: el.querySelector('[data-page]').selectedOptions[0]?.textContent || '',
      gio_dang: fromLocalInput(el.querySelector('[data-when]')?.value),
    }));
    if (!items.length) return toast('Hãy đánh dấu ít nhất 1 bài', 'warn');
    if (items.some(i => !i.page_id)) return toast('Có bài chưa chọn Fanpage — kết nối Fanpage ở mục Fanpage Facebook', 'warn');
    openModal('XÁC NHẬN LẦN 2', 'Đăng lên Facebook?', `<div class="form">
      <div class="camp-banner warn">Bài sẽ được đăng <b>công khai</b> lên các Fanpage dưới đây khi bạn bấm xác nhận (bài có giờ hẹn: Facebook tự đăng đúng giờ).
        ${((d.options || {}).boost || {}).on ? '<br>Sau khi đăng, ứng dụng tạo <b>quảng cáo ở trạng thái TẠM DỪNG</b> cho bài tốt nhất mỗi page — không tốn tiền cho tới khi bạn bật ở trang Quảng cáo.' : ''}</div>
      <ul class="camp-fixes">${items.map(i => `<li><b>STT ${i.stt}</b> → ${esc(i.page)}${i.gio_dang ? ` · <b>hẹn ${esc(i.gio_dang)}</b>` : ' · đăng ngay'} · ${esc(i.caption.split('\n')[0].slice(0, 80))}</li>`).join('')}</ul>
      <div class="modal-foot row"><button class="btn ghost" id="campPubCancel" type="button">Huỷ</button>
        <button class="btn primary" id="campPubGo" type="button">Xác nhận đăng ${items.length} bài</button></div></div>`, true);
    $('#modalBody').onclick = null;
    $('#campPubCancel').onclick = closeModal;
    $('#campPubGo').onclick = async () => {
      const btn = $('#campPubGo');
      btn.disabled = true; btn.textContent = 'Đang đăng…';
      const res = await api('campaign_publish', d.id, items.map(({ stt, page_id, caption, gio_dang }) => ({ stt, page_id, caption, gio_dang })), true);
      closeModal();
      if (!res.ok) return toast(res.error, 'error');
      const ok = res.result.results.filter(r => r.id).length;
      toast(`Đã đăng ${ok}/${items.length} bài${ok < items.length ? ' — xem lỗi ở tab Đăng bài' : ''}`, ok ? 'ok' : 'error');
      C.tab = 'post';
      openDetail(d.id);
    };
  }

  // ================================================================ C. tạo chiến dịch
  async function renderForm() {
    await loadLibrary();
    const fb = await api('fb_state');
    const pages = fb.ok ? fb.fb.pages.filter(p => p.connected) : [];
    const lib = C.lib;
    const f = C.form || (C.form = { product_files: [], ref_files: [], model_files: [], lib_refs: [], lib_models: [], pages: pages.map(p => p.id), product: {}, links: [] });
    const styles = lib.styles || [];
    $('#campForm').innerHTML = `
      ${missingKeys().length ? `<div class="camp-banner bad"><div>Chưa có <b>khoá ${missingKeys().join(' / ')} API</b> — các vai trò AI dùng nhà cung cấp này chưa chạy được.</div>
        <button class="btn ghost sm" data-open-settings type="button">Nhập khoá ở Cài đặt</button></div>` : ''}
      <div class="camp-form-grid">
        <div class="card camp-span">
          <div class="card-title">MÔ TẢ CHIẾN DỊCH <span class="tag">bắt buộc</span></div>
          <textarea id="cfDesc" rows="6" placeholder="Sản phẩm, khách hàng mục tiêu, kênh (Facebook/TikTok), mục tiêu chiến dịch…">${esc(f.description || '')}</textarea>
          <label class="field fb-gap"><span>Tên chiến dịch (tuỳ chọn)</span><input id="cfName" value="${esc(f.name || '')}" placeholder="Để trống = lấy theo tên sản phẩm"></label>
        </div>
        <div class="card">
          <div class="card-title">SẢN PHẨM</div>
          <label class="field"><span>Chọn từ Thư viện sản phẩm</span><select id="cfProduct"><option value="">— Nhập sản phẩm mới —</option>
            ${(lib.products || []).map(p => `<option value="${esc(p.id)}" ${p.id === f.product_id ? 'selected' : ''}>${esc(p.name)}${p.code ? ` · ${esc(p.code)}` : ''}</option>`).join('')}</select></label>
          <div class="grid2 fb-gap">
            ${[['name', 'Tên sản phẩm'], ['code', 'Mã SP'], ['spec', 'Quy cách'], ['price', 'Giá gốc'], ['sale_price', 'Giá khuyến mãi'], ['promo', 'Khuyến mãi'], ['hotline', 'Hotline']]
              .map(([k, l]) => `<label class="field"><span>${l}</span><input data-pf="${k}" value="${esc((f.product || {})[k] || '')}" placeholder="Không bắt buộc"></label>`).join('')}
          </div>
          <label class="field fb-gap"><span>Link trang web sản phẩm (mỗi dòng 1 link)</span><textarea id="cfLinks" rows="2" placeholder="https://…">${esc((f.links || []).join('\n'))}</textarea></label>
          <p class="hint">Để trống giá/mã/khuyến mãi thì content bỏ dòng đó — hệ thống không tự bịa.</p>
        </div>
        <div class="card">
          <div class="card-title">ẢNH</div>
          ${fileRow('product_files', 'Ảnh sản phẩm thật', 'PNG/JPG/WEBP (WEBP tự đổi sang PNG) — luôn là ảnh mẫu đầu tiên gửi model ảnh')}
          ${fileRow('ref_files', 'Ảnh tham chiếu', 'Bám bố cục, góc máy, ánh sáng, bảng màu')}
          ${(lib.refs || []).length ? `<div class="field"><span>…hoặc chọn từ Thư viện tham chiếu</span><div class="camp-pick">${lib.refs.map(r => `
            <button class="camp-pick-item ${f.lib_refs.includes(r.file) ? 'on' : ''}" data-libref="${esc(r.file)}" type="button" title="${esc((r.tags || []).join(', '))}">
              <img src="${libUrl('refs/' + r.file)}" alt=""></button>`).join('')}</div></div>` : '<p class="hint">Thư viện tham chiếu trống — không upload thì ứng dụng tự lấy ảnh tham khảo bố cục trên Pinterest.</p>'}
          ${fileRow('model_files', 'Ảnh người mẫu (không bắt buộc)', 'Không có thì lấy từ thư viện, hoặc model ảnh tự tạo gương mặt khác')}
          ${(lib.models || []).length ? `<div class="field"><span>…hoặc chọn người mẫu</span><div class="camp-pick">${lib.models.map(m => `
            <button class="camp-pick-item ${f.lib_models.includes(m.id) ? 'on' : ''}" data-libmodel="${esc(m.id)}" type="button" title="${esc(m.name)}">
              <img src="${libUrl('models/' + m.file)}" alt=""><small>${esc(m.name)}</small></button>`).join('')}</div></div>` : ''}
        </div>
        <div class="card">
          <div class="card-title">PHONG CÁCH & TUỲ CHỌN</div>
          <label class="field"><span>Phong cách nhân vật</span><select id="cfStyle">${styles.map(s => `<option ${s.name === (f.style || 'Sexy táo bạo') && !f.style_custom ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}
            <option value="__custom" ${f.style_custom ? 'selected' : ''}>Tự nhập…</option></select></label>
          <input id="cfStyleCustom" class="fb-gap ${f.style_custom ? '' : 'hidden'}" placeholder="Mô tả phong cách" value="${esc(f.style_custom || '')}">
          <div class="camp-checks">
            <label class="check"><input type="checkbox" id="cfSelfPick" ${f.self_pick ? 'checked' : ''}> Tôi tự chọn ý tưởng</label>
            <label class="check"><input type="checkbox" id="cfNoPost" ${f.no_post ? 'checked' : ''}> Không đăng</label>
            <label class="check"><input type="checkbox" id="cfVideo" ${f.video ? 'checked' : ''}> Có video</label>
          </div>
          ${renderMediaOptions(f)}
          <div class="field fb-gap"><span>Fanpage đăng bài</span>${pages.length ? `<div class="camp-pages">${pages.map(p => `
            <label class="chip-check"><input type="checkbox" value="${esc(p.id)}" data-page ${f.pages.includes(p.id) ? 'checked' : ''}><span>${esc(p.name)}</span></label>`).join('')}</div>`
            : '<p class="hint">Chưa kết nối Fanpage — vẫn tạo chiến dịch được; kết nối ở mục Fanpage Facebook trước khi đăng.</p>'}</div>
        </div>
      </div>
      <div class="camp-submit">
        <span class="muted">Một chiến dịch thường chạy ~10 phút. Ứng dụng <b>không bao giờ tự đăng</b> — bạn duyệt và bấm đồng ý ở bước cuối.</span>
        <button class="btn primary big" id="cfSubmit" type="button">Bắt đầu chiến dịch →</button>
      </div>`;
    bindForm();
  }

  /** Ảnh & video của chiến dịch chạy bằng trang Tạo hình ảnh / Tạo video: chọn model ảnh, loại video và profile. */
  function renderMediaOptions(f) {
    const boot = (typeof state !== 'undefined' && state.boot) || {};
    const engines = boot.image_engines || {};
    const g = sharedModels();  // model ảnh: dùng chung (Cài đặt → Model AI)
    const engine = engines[g.image] ? g.image : (engines[C.imageEngine] ? C.imageEngine : Object.keys(engines)[0] || '');
    f.image_engine = engine;
    f.image_profile = g.image_profile;
    const spec = engines[engine] || {};
    const textOk = TEXT_ENGINES.includes(engine);
    const kind = VIDEO_KINDS[f.video_kind] ? f.video_kind : 'auto';
    const profileSel = (id, site, current, label) => state.profiles && state.profileSites[site]
      ? `<label class="field fb-gap"><span>${label}</span><select id="${id}">${profileOptions(site, current)}</select></label>`
      : `<input type="hidden" id="${id}" value="">`;
    const sched = f.schedule || {};
    const boost = f.boost || {};
    const accounts = C.adsAccounts || [];
    return `<div id="cfMedia">
      ${sharedModelField('Model tạo ảnh', 'image')}
      <p class="hint">${textOk ? 'Model này vẽ được chữ tiếng Việt — tiêu đề và giá được vẽ luôn trên ảnh; có thêm poster khi hợp ngành hàng.' : 'Model này vẽ chữ tiếng Việt chưa chuẩn — ảnh không có chữ quảng cáo, không làm poster.'}
        Mỗi ảnh quảng cáo tạo 2 phương án để trưởng phòng chọn, kèm 1 ảnh sản phẩm studio. ${esc(spec.note || '')}</p>
      <div class="${f.video ? '' : 'hidden'}">
        <label class="field fb-gap"><span>Loại video <small class="muted">(trang Tạo video · tối đa 2 video)</small></span><select id="cfVideoKind">
          ${Object.entries(VIDEO_KINDS).map(([v, l]) => `<option value="${v}" ${v === kind ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field fb-gap ${['auto', 'sale'].includes(kind) ? '' : 'hidden'}"><span>Kiểu video bán hàng mặc định</span><select id="cfVideoStyle">
          ${[['presenter', 'Người mẫu giới thiệu'], ['showcase', 'Sản phẩm nổi'], ['reel', 'Reel bán hàng']].map(([v, l]) => `<option value="${v}" ${v === (f.video_style || 'presenter') ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        ${profileSel('cfVideoProfile', 'grok', f.video_profile, 'Profile Grok (video AI)')}
        <p class="hint">Video bán hàng / kiến thức: kịch bản do Provider AI ở trang Tạo video viết, brand lấy theo tên Fanpage. Video AI: cần đăng nhập Grok. Trưởng phòng yêu cầu vẽ lại ảnh thì video tự làm lại.</p>
      </div>
      <label class="check fb-gap"><input type="checkbox" id="cfSchedule" ${sched.on ? 'checked' : ''}> Hẹn giờ đăng (rải bài vào khung giờ vàng)</label>
      <div class="${sched.on ? '' : 'hidden'}"><label class="field"><span>Rải trong số ngày</span>
        <input type="number" id="cfScheduleDays" min="1" max="14" value="${esc(sched.days || 3)}"></label></div>
      <label class="check fb-gap"><input type="checkbox" id="cfBoost" ${boost.on ? 'checked' : ''}> Tạo quảng cáo sau khi đăng <span class="tag">TẠM DỪNG</span></label>
      <div class="${boost.on ? '' : 'hidden'}">
        <label class="field"><span>Tài khoản quảng cáo</span><select id="cfAdAccount">${accounts.length
          ? accounts.map(a => `<option value="${esc(a.id)}" ${a.id === boost.account_id ? 'selected' : ''}>${esc(a.name)} · ${esc(a.currency || '')}</option>`).join('')
          : `<option value="">${C.adsError ? esc(C.adsError) : 'Đang tải…'}</option>`}</select></label>
        <div class="grid2 fb-gap">
          <label class="field"><span>Ngân sách / ngày</span><input id="cfAdBudget" value="${esc(boost.daily_budget || '')}" placeholder="VD: 100000"></label>
          <label class="field"><span>Số ngày</span><input type="number" id="cfAdDays" min="1" max="30" value="${esc(boost.days || 3)}"></label>
          <label class="field"><span>Tuổi từ</span><input type="number" id="cfAdAgeMin" min="13" max="65" value="${esc(boost.age_min || 18)}"></label>
          <label class="field"><span>đến</span><input type="number" id="cfAdAgeMax" min="13" max="65" value="${esc(boost.age_max || 65)}"></label>
          <label class="field"><span>Quốc gia (mã, phẩy)</span><input id="cfAdCountries" value="${esc(boost.countries || 'VN')}"></label>
        </div>
        <p class="hint">Mỗi page chạy quảng cáo cho 1 bài tốt nhất (ưu tiên video → mục tiêu ThruPlay; ảnh → tương tác). Bài hẹn giờ chưa lên trang nên tạo quảng cáo sau ở trang Quảng cáo.</p>
      </div></div>`;
  }

  /** Tài khoản quảng cáo (trang Quảng cáo Facebook) cho tuỳ chọn "Tạo quảng cáo sau khi đăng". */
  async function loadAdAccounts() {
    const res = await api('ads_accounts');
    C.adsAccounts = res.ok ? (res.accounts || []).filter(a => a.active !== false) : [];
    C.adsError = res.ok ? (C.adsAccounts.length ? '' : 'Không có tài khoản quảng cáo') : res.error;
    if ($('#cfMedia')) { readForm(); $('#cfMedia').outerHTML = renderMediaOptions(C.form); }
  }

  function fileRow(key, label, hint) {
    const files = C.form[key] || [];
    return `<div class="field camp-files"><span>${label}</span>
      <div class="camp-chips">${files.map((p, i) => `<span class="camp-chip">${esc(p.split(/[\\/]/).pop())}<button data-rm="${key}:${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
        <button class="btn ghost sm" data-pick-files="${key}" type="button">+ Chọn ảnh…</button></div><small class="muted">${hint}</small></div>`;
  }

  function readForm() {
    const f = C.form;
    f.description = $('#cfDesc').value;
    f.name = $('#cfName').value;
    f.product_id = $('#cfProduct').value;
    f.product = Object.fromEntries($$('[data-pf]').map(i => [i.dataset.pf, i.value.trim()]));
    f.links = linesOf($('#cfLinks').value);
    f.style_custom = $('#cfStyle').value === '__custom' ? $('#cfStyleCustom').value.trim() : '';
    f.style = f.style_custom || ($('#cfStyle').value === '__custom' ? 'Sexy táo bạo' : $('#cfStyle').value);
    f.self_pick = $('#cfSelfPick').checked;
    f.no_post = $('#cfNoPost').checked;
    f.video = $('#cfVideo').checked;
    const g = sharedModels();
    f.image_engine = g.image;
    f.image_profile = g.image_profile;
    f.video_kind = $('#cfVideoKind').value;
    f.video_style = $('#cfVideoStyle').value;
    f.video_profile = $('#cfVideoProfile').value;
    f.schedule = { on: $('#cfSchedule').checked, days: +$('#cfScheduleDays').value || 3 };
    f.boost = { on: $('#cfBoost').checked, account_id: $('#cfAdAccount').value, daily_budget: $('#cfAdBudget').value.trim(),
      days: +$('#cfAdDays').value || 3, age_min: +$('#cfAdAgeMin').value || 18, age_max: +$('#cfAdAgeMax').value || 65,
      countries: $('#cfAdCountries').value.trim() || 'VN' };
    f.pages = $$('[data-page]').filter(i => i.checked).map(i => i.value);
    return f;
  }

  function bindForm() {
    const root = $('#campForm');
    root.onchange = e => {
      readForm();
      if (e.target.id === 'cfProduct') {
        const p = (C.lib.products || []).find(x => x.id === e.target.value);
        if (p) { C.form.product = Object.fromEntries(['name', 'code', 'spec', 'price', 'sale_price', 'promo', 'hotline'].map(k => [k, p[k] || ''])); C.form.links = p.links || []; renderForm(); }
      }
      if (e.target.id === 'cfStyle') $('#cfStyleCustom').classList.toggle('hidden', e.target.value !== '__custom');
      if (['cfVideo', 'cfVideoKind', 'cfSchedule', 'cfBoost'].includes(e.target.id)) $('#cfMedia').outerHTML = renderMediaOptions(C.form);
      if (e.target.id === 'cfBoost' && e.target.checked && !C.adsAccounts) loadAdAccounts();
    };
    root.onclick = async e => {
      if (e.target.closest('[data-open-settings]')) { navigate('settings'); return; }
      const go = e.target.closest('[data-go-lib]');
      if (go) { C.libTab = go.dataset.goLib; navigate('camp-lib'); return; }
      const pick = e.target.closest('[data-pick-files]');
      if (pick) {
        readForm();
        const files = await api('pick_files', 'images_multi');
        if (files.length) { const k = pick.dataset.pickFiles; C.form[k] = [...new Set([...(C.form[k] || []), ...files])]; renderForm(); }
        return;
      }
      const rm = e.target.closest('[data-rm]');
      if (rm) { readForm(); const [k, i] = rm.dataset.rm.split(':'); C.form[k].splice(+i, 1); renderForm(); return; }
      const ref = e.target.closest('[data-libref]');
      if (ref) { readForm(); toggle(C.form.lib_refs, ref.dataset.libref); ref.classList.toggle('on'); return; }
      const model = e.target.closest('[data-libmodel]');
      if (model) { readForm(); toggle(C.form.lib_models, model.dataset.libmodel); model.classList.toggle('on'); return; }
      if (e.target.closest('#cfSubmit')) submitForm();
    };
  }

  function toggle(list, value) {
    const i = list.indexOf(value);
    if (i >= 0) list.splice(i, 1); else list.push(value);
  }

  async function submitForm() {
    const f = readForm();
    if (f.description.trim().length < 10) { toast('Hãy mô tả chiến dịch (sản phẩm, khách hàng, kênh, mục tiêu)', 'warn'); $('#cfDesc').focus(); return; }
    if (missingKeys().length) { toast(`Chưa có khoá ${missingKeys().join(' / ')} API — nhập ở Cài đặt → API & kết nối`, 'warn'); navigate('settings'); return; }
    if (!f.ref_files.length && !f.lib_refs.length && !(C.lib.refs || []).length
      && !confirm('Chưa có ảnh tham chiếu (upload hoặc thư viện). Chặng làm ảnh sẽ dừng lại chờ bạn bổ sung. Vẫn tạo?')) return;
    const btn = $('#cfSubmit');
    btn.disabled = true; btn.textContent = 'Đang tạo…';
    const res = await api('campaign_create', f);
    btn.disabled = false; btn.textContent = 'Bắt đầu chiến dịch →';
    if (!res.ok) return toast(res.error, 'error');
    toast('Đã tạo chiến dịch — dây chuyền đang chạy', 'ok');
    C.form = null;
    C.cid = res.result.id;
    C.detailOpen = true;
    C.tab = 'brief';
    navigate('camp-list');
  }

  // ================================================================ G. thư viện
  const LIB_TABS = [['products', 'Sản phẩm'], ['refs', 'Ảnh tham chiếu'], ['models', 'Người mẫu'], ['styles', 'Phong cách nhân vật'],
    ['template', 'Mẫu content'], ['roles', 'Vai trò AI']];

  async function renderLibrary() {
    await loadLibrary();
    const lib = C.lib;
    const counts = { products: lib.products.length, refs: lib.refs.length, models: lib.models.length, styles: lib.styles.length };
    $('#campLibTabs').innerHTML = LIB_TABS.map(([k, l]) => `<button class="camp-tab ${C.libTab === k ? 'on' : ''}" data-libtab="${k}" type="button">${l}${counts[k] !== undefined ? ` <span class="mono">${counts[k]}</span>` : ''}${k === 'roles' && missingKeys().length ? ' <span class="camp-dot-bad"></span>' : ''}</button>`).join('');
    $('#campLibTabs').onclick = e => { const t = e.target.closest('[data-libtab]'); if (t) { C.libTab = t.dataset.libtab; renderLibrary(); } };
    const body = $('#campLibBody');
    if (C.libTab === 'products') {
      body.innerHTML = `<div class="results-head"><span class="muted">${lib.products.length} sản phẩm · dùng để chọn nhanh khi tạo chiến dịch và để so nhãn</span>
        <button class="btn primary" data-lib="add-product" type="button">+ Thêm sản phẩm</button></div>
        <div class="camp-lib-grid">${lib.products.map(p => `<div class="card camp-lib-card">
          <div class="camp-lib-imgs">${(p.images || []).slice(0, 3).map(f => `<img src="${libUrl(`products/${p.id}/${f}`)}" alt="">`).join('') || '<span>Chưa có ảnh</span>'}</div>
          <b>${esc(p.name)}</b><small>${[p.code && `Mã ${p.code}`, p.spec, p.price && `Giá ${p.price}`, p.sale_price && `KM ${p.sale_price}`, p.hotline].filter(Boolean).map(esc).join(' · ') || '—'}</small>
          <div class="row"><button class="btn ghost sm" data-lib="edit-product" data-id="${esc(p.id)}" type="button">Sửa</button>
            <button class="btn danger sm" data-lib="del-product" data-id="${esc(p.id)}" type="button">Xoá</button></div></div>`).join('') || '<div class="empty">Chưa có sản phẩm.</div>'}</div>`;
    } else if (C.libTab === 'refs') {
      body.innerHTML = `<div class="results-head"><span class="muted">${lib.refs.length} ảnh · bắt buộc có ảnh tham chiếu để làm ảnh</span>
        <div class="row"><input id="refTags" placeholder="Thẻ cho ảnh sắp tải: TikTok, poster, bình luận…" style="width:300px"><button class="btn primary" data-lib="add-refs" type="button">+ Tải ảnh lên</button></div></div>
        <div class="camp-ref-grid">${lib.refs.map(r => `<div class="camp-ref"><img src="${libUrl('refs/' + r.file)}" alt="">
          <div class="camp-ref-tags">${(r.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('') || '<small class="muted">chưa gắn thẻ</small>'}</div>
          <div class="row"><button class="btn ghost sm" data-lib="tag-ref" data-file="${esc(r.file)}" type="button">Gắn thẻ</button>
            <button class="btn danger sm" data-lib="del-ref" data-file="${esc(r.file)}" type="button">Bỏ</button></div></div>`).join('') || '<div class="empty">Chưa có ảnh tham chiếu.</div>'}</div>`;
    } else if (C.libTab === 'models') {
      body.innerHTML = `<div class="results-head"><span class="muted">${lib.models.length} người mẫu · chỉ sửa/xoá khi bạn xác nhận</span>
        <button class="btn primary" data-lib="add-model" type="button">+ Thêm người mẫu</button></div>
        <div class="camp-ref-grid">${lib.models.map(m => `<div class="camp-ref"><img src="${libUrl('models/' + m.file)}" alt="">
          <b>${esc(m.name)}</b><small class="muted">${esc(m.profile || '')}</small>
          <div class="row"><button class="btn ghost sm" data-lib="edit-model" data-id="${esc(m.id)}" type="button">Sửa</button>
            <button class="btn danger sm" data-lib="del-model" data-id="${esc(m.id)}" type="button">Xoá</button></div></div>`).join('') || '<div class="empty">Chưa có người mẫu.</div>'}</div>`;
    } else if (C.libTab === 'styles') {
      body.innerHTML = `<p class="muted">Danh sách phong cách nhân vật khi tạo chiến dịch; phần mô tả được đưa vào prompt vẽ ảnh.</p>
        <div class="camp-styles" id="styleList">${lib.styles.map(styleRow).join('')}</div>
        <div class="row fb-gap"><button class="btn ghost" data-lib="add-style" type="button">+ Thêm phong cách</button>
          <button class="btn primary" data-lib="save-styles" type="button">Lưu phong cách</button></div>`;
    } else if (C.libTab === 'template') {
      body.innerHTML = `<p class="muted">Khung bài bán hàng NV content bắt buộc theo. Lưu lại thì bản cũ được cất vào thư mục <code>_cu/</code>.</p>
        <textarea id="tplText" class="mono" rows="24">${esc(lib.template)}</textarea>
        <div class="row fb-gap"><button class="btn primary" data-lib="save-template" type="button">Lưu mẫu content</button></div>`;
    } else if (C.libTab === 'roles') {
      body.innerHTML = renderRoles();
    }
    body.onclick = onLibClick;
  }

  const styleRow = s => `<div class="card camp-style" data-style><div class="camp-style-row"><label class="field"><span>Tên</span><input data-sname value="${esc(s.name)}"></label>
    <button class="btn danger sm" data-lib="del-style" type="button">Xoá</button></div>
    <label class="field fb-gap"><span>Mô tả đưa vào prompt</span><textarea data-sprompt rows="2">${esc(s.prompt)}</textarea></label></div>`;

  function renderRoles() {
    const roles = C.lib.roles;
    const tag = ok => ok ? '<span class="tag">✓ đã có</span>' : '<span class="tag bad">chưa có</span>';
    const modelOptions = current => Object.entries(PROVIDER_NAMES).map(([p, name]) => {
      const list = [...new Set([current, ...C.models])].filter(m => providerOf(m) === p);
      return `<optgroup label="${name}${C.keys[p] ? '' : ' (chưa có khoá)'}">${list.map(m => `<option ${m === current ? 'selected' : ''}>${esc(m)}</option>`).join('')}</optgroup>`;
    }).join('');
    return `<div class="card camp-key">
        <div class="card-title">KHOÁ API AI</div>
        <p class="hint">Mỗi vai trò chọn model Claude (Anthropic) hoặc GPT (OpenAI) ở ô Model bên dưới — chỉ cần khoá của nhà cung cấp đang dùng.
          Khoá API nhập ở <b>Cài đặt → API &amp; kết nối</b> (không nhập ở màn hình này).</p>
        <div class="row camp-keys"><span>Anthropic (Claude) ${tag(C.keys.anthropic)}</span><span>OpenAI (GPT) ${tag(C.keys.openai)}</span>
          <button class="btn ghost sm" data-lib="open-settings" type="button">Mở Cài đặt</button></div>
        <p class="hint">Ảnh và video: dùng trang Tạo hình ảnh / Tạo video (chọn model khi tạo chiến dịch). Đăng bài: token Facebook ở Cài đặt → API &amp; kết nối, bật Fanpage ở mục Fanpage Facebook.</p></div>
      ${Object.entries(roles).map(([rid, r]) => `<div class="card camp-role" data-role="${esc(rid)}">
        <div class="camp-role-head"><b>${esc(r.name)}</b><small class="mono">${esc(rid)}</small>${r.web ? '<span class="tag">web search</span>' : ''}
          <span class="camp-role-sel"><select data-rmodel title="Model">${modelOptions(r.model)}</select>
          <select data-reffort title="Effort">${['low', 'medium', 'high', 'xhigh', 'max'].map(v => `<option ${v === r.effort ? 'selected' : ''}>${v}</option>`).join('')}</select></span></div>
        <small class="muted">${r.source ? `Nguồn: ${esc(r.source)}` : 'System prompt'} · ${(r.prompt || '').length.toLocaleString('vi-VN')} ký tự · ${(r.versions || []).length} phiên bản cũ</small>
        <details class="camp-more"><summary>Sửa system prompt</summary>
          <textarea data-rprompt class="mono" rows="16">${esc(r.prompt || '')}</textarea>
          ${(r.versions || []).length ? `<div class="camp-versions"><small>Phiên bản cũ:</small>${r.versions.map((v, i) => `<button class="btn ghost sm" data-lib="load-version" data-i="${i}" type="button">${esc(fmtTime(v.at))}</button>`).join('')}</div>` : ''}
        </details>
        <div class="row"><button class="btn primary sm" data-lib="save-role" type="button">Lưu vai trò</button></div></div>`).join('')}`;
  }

  async function onLibClick(e) {
    const btn = e.target.closest('[data-lib]');
    if (!btn) return;
    const act = btn.dataset.lib;
    const done = (res, msg) => { if (!res.ok) { toast(res.error, 'error'); return false; } if (msg) toast(msg, 'ok'); renderLibrary(); return true; };
    if (act === 'add-product' || act === 'edit-product') return openProductForm(C.lib.products.find(p => p.id === btn.dataset.id));
    if (act === 'del-product') { if (confirm('Xoá sản phẩm khỏi thư viện?')) done(await api('camp_delete_product', btn.dataset.id), 'Đã xoá'); return; }
    if (act === 'add-refs') {
      const files = await api('pick_files', 'images_multi');
      if (files.length) done(await api('camp_add_refs', files, ($('#refTags').value || '').split(',')), `Đã thêm ${files.length} ảnh tham chiếu`);
      return;
    }
    if (act === 'tag-ref') {
      const ref = C.lib.refs.find(r => r.file === btn.dataset.file);
      const value = prompt('Thẻ (cách nhau dấu phẩy):', (ref.tags || []).join(', '));
      if (value !== null) done(await api('camp_update_ref', ref.file, value.split(',')), 'Đã lưu thẻ');
      return;
    }
    if (act === 'del-ref') { if (confirm('Bỏ ảnh này khỏi thư viện? (file ảnh vẫn giữ trên đĩa)')) done(await api('camp_delete_ref', btn.dataset.file), 'Đã bỏ khỏi thư viện'); return; }
    if (act === 'add-model' || act === 'edit-model') return openModelForm(C.lib.models.find(m => m.id === btn.dataset.id));
    if (act === 'del-model') { if (confirm('Xoá người mẫu này khỏi thư viện?')) done(await api('camp_delete_model', btn.dataset.id), 'Đã xoá'); return; }
    if (act === 'add-style') { $('#styleList').insertAdjacentHTML('beforeend', styleRow({ name: '', prompt: '' })); return; }
    if (act === 'del-style') { btn.closest('[data-style]').remove(); return; }
    if (act === 'save-styles') {
      const items = $$('#styleList [data-style]').map(el => ({ name: el.querySelector('[data-sname]').value, prompt: el.querySelector('[data-sprompt]').value }));
      done(await api('camp_save_styles', items), 'Đã lưu phong cách');
      return;
    }
    if (act === 'save-template') { done(await api('camp_save_template', $('#tplText').value), 'Đã lưu mẫu content'); return; }
    if (act === 'open-settings') { navigate('settings'); return; }
    const card = btn.closest('[data-role]');
    if (act === 'save-role') {
      done(await api('camp_save_role', card.dataset.role, card.querySelector('[data-rprompt]').value,
        card.querySelector('[data-rmodel]').value, card.querySelector('[data-reffort]').value), 'Đã lưu vai trò (bản cũ được giữ trong lịch sử)');
      return;
    }
    if (act === 'load-version') {
      const res = await api('camp_role_version', card.dataset.role, +btn.dataset.i);
      if (res.ok) { card.querySelector('[data-rprompt]').value = res.prompt; toast('Đã nạp phiên bản cũ vào ô — bấm Lưu vai trò để dùng lại', 'ok'); }
    }
  }

  function openProductForm(p) {
    p = p || { images: [] };
    const keepImages = [...(p.images || [])];
    let newImages = [];
    const fields = [['name', 'Tên sản phẩm *'], ['code', 'Mã SP'], ['spec', 'Quy cách'], ['price', 'Giá gốc'], ['sale_price', 'Giá khuyến mãi'], ['promo', 'Khuyến mãi'], ['hotline', 'Hotline']];
    const draw = () => {
      $('#pfImages').innerHTML = keepImages.map((f, i) => `<span class="camp-chip"><img src="${libUrl(`products/${p.id}/${f}`)}" alt="">${esc(f)}<button data-keep="${i}" type="button">✕</button></span>`).join('')
        + newImages.map((f, i) => `<span class="camp-chip">${esc(f.split(/[\\/]/).pop())}<button data-new="${i}" type="button">✕</button></span>`).join('');
    };
    openModal('THƯ VIỆN · SẢN PHẨM', p.id ? 'Sửa sản phẩm' : 'Thêm sản phẩm', `<div class="form">
      <div class="grid2">${fields.map(([k, l]) => `<label class="field"><span>${l}</span><input data-pfield="${k}" value="${esc(p[k] || '')}"></label>`).join('')}</div>
      <label class="field"><span>Link web (mỗi dòng 1 link)</span><textarea data-pfield="links" rows="2">${esc((p.links || []).join('\n'))}</textarea></label>
      <label class="field"><span>Mô tả nhãn (dùng để so nhãn sau khi tạo ảnh)</span><textarea data-pfield="label" rows="3" placeholder="Màu bao bì, chữ lớn, khối lượng…">${esc(p.label || '')}</textarea></label>
      <div class="field"><span>Ảnh sản phẩm thật</span><div class="camp-chips" id="pfImages"></div><button class="btn ghost sm" id="pfPick" type="button">+ Chọn ảnh…</button></div>
      <div class="modal-foot"><button class="btn primary" id="pfSave" type="button">Lưu sản phẩm</button></div></div>`, true);
    draw();
    $('#modalBody').onclick = async e => {
      const k = e.target.closest('[data-keep]'); if (k) { keepImages.splice(+k.dataset.keep, 1); draw(); return; }
      const n = e.target.closest('[data-new]'); if (n) { newImages.splice(+n.dataset.new, 1); draw(); return; }
      if (e.target.closest('#pfPick')) { const files = await api('pick_files', 'images_multi'); newImages = [...newImages, ...files]; draw(); return; }
      if (e.target.closest('#pfSave')) {
        const item = { id: p.id || '', images: keepImages };
        $$('[data-pfield]').forEach(el => { item[el.dataset.pfield] = el.dataset.pfield === 'links' ? linesOf(el.value) : el.value; });
        const res = await api('camp_save_product', item, newImages);
        if (!res.ok) return toast(res.error, 'error');
        closeModal(); toast('Đã lưu sản phẩm', 'ok'); renderLibrary();
      }
    };
  }

  function openModelForm(m) {
    m = m || {};
    let image = '';
    openModal('THƯ VIỆN · NGƯỜI MẪU', m.id ? `Sửa: ${m.name}` : 'Thêm người mẫu', `<div class="form">
      <label class="field"><span>Tên (VD: Sếp Hoàng)</span><input id="mfName" value="${esc(m.name || '')}"></label>
      <label class="field"><span>Hồ sơ / mô tả</span><textarea id="mfProfile" rows="3">${esc(m.profile || '')}</textarea></label>
      <div class="field"><span>Ảnh</span><div class="row">${m.file ? `<img class="camp-model-img" src="${libUrl('models/' + m.file)}" alt="">` : ''}
        <span id="mfFile" class="muted">${m.file ? 'Giữ ảnh hiện tại' : 'Chưa chọn'}</span><button class="btn ghost sm" id="mfPick" type="button">Chọn ảnh…</button></div></div>
      <div class="modal-foot"><button class="btn primary" id="mfSave" type="button">Lưu</button></div></div>`, true);
    $('#modalBody').onclick = async e => {
      if (e.target.closest('#mfPick')) { const files = await api('pick_files', 'image'); if (files.length) { image = files[0]; $('#mfFile').textContent = image.split(/[\\/]/).pop(); } return; }
      if (e.target.closest('#mfSave')) {
        if (m.id && !confirm('Lưu thay đổi hồ sơ người mẫu?')) return;
        const res = await api('camp_save_model', { id: m.id || '', name: $('#mfName').value, profile: $('#mfProfile').value }, image);
        if (!res.ok) return toast(res.error, 'error');
        closeModal(); toast('Đã lưu người mẫu', 'ok'); renderLibrary();
      }
    };
  }

  // ================================================================ I. lịch sử & chi phí
  async function renderHistory() {
    const res = await api('campaign_history');
    if (!res.ok) return;
    const tabs = [['posts', `Lịch sử đăng (${res.posts.length})`], ['cost', 'Chi phí theo chiến dịch'], ['calls', `Nhật ký gọi AI (${res.calls.length})`]];
    $('#campHistTabs').innerHTML = tabs.map(([k, l]) => `<button class="camp-tab ${C.histTab === k ? 'on' : ''}" data-hist="${k}" type="button">${l}</button>`).join('');
    $('#campHistTabs').onclick = e => { const t = e.target.closest('[data-hist]'); if (t) { C.histTab = t.dataset.hist; renderHistory(); } };
    const table = (head, rows) => `<div class="ads-table-wrap"><table class="ads-table camp-table"><thead><tr>${head.map(h => `<th class="l">${h}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('') || `<tr><td class="l" colspan="${head.length}"><div class="empty">Chưa có dữ liệu.</div></td></tr>`}</tbody></table></div>`;
    let html = '';
    if (C.histTab === 'posts') {
      html = table(['Ngày', 'Chiến dịch', 'Fanpage', 'Bài', 'Link', 'Người bấm đăng'], res.posts.map(p => `<tr>
        <td class="l">${esc(fmtTime(p.at))}</td><td class="l">${esc(p.campaign_name || p.campaign)}</td><td class="l">${esc(p.page || p.page_id)}</td>
        <td class="l">STT ${esc(p.stt ?? '')}</td><td class="l">${p.url ? `<a href="${esc(p.url)}" data-ext>${esc(p.url)}</a>` : '—'}</td><td class="l">${esc(p.by || '')}</td></tr>`));
    } else if (C.histTab === 'cost') {
      const rows = Object.entries(res.per_campaign).sort((a, b) => (b[1].created_at || '').localeCompare(a[1].created_at || ''));
      const total = rows.reduce((s, [, c]) => s + (c.usd || 0), 0);
      html = `<div class="camp-stats">${[['Tổng chi phí AI', money(total), 'main'], ['Số chiến dịch', rows.length],
        ['Ảnh đã tạo', rows.reduce((s, [, c]) => s + (c.images || 0), 0)], ['Lượt gọi AI', rows.reduce((s, [, c]) => s + (c.calls || 0), 0)]]
        .map(([l, v, cls]) => `<div class="camp-stat ${cls || ''}"><small>${l}</small><b>${v}</b></div>`).join('')}</div>`
        + table(['Chiến dịch', 'Ngày', 'Token vào', 'Token ra', 'Lượt gọi AI', 'Ảnh', 'Chi phí'], rows.map(([id, c]) => `<tr>
        <td class="l">${esc(c.name)}<br><small class="muted mono">${esc(id)}</small></td><td class="l">${esc(fmtTime(c.created_at))}</td>
        <td class="l">${(c.tokens_in || 0).toLocaleString('vi-VN')}</td><td class="l">${(c.tokens_out || 0).toLocaleString('vi-VN')}</td>
        <td class="l">${c.calls || 0}</td><td class="l">${c.images || 0}</td><td class="l"><b>${money(c.usd)}</b></td></tr>`));
    } else {
      html = table(['Thời gian', 'Chiến dịch', 'Vai trò', 'Model', 'Token vào / ra', 'Web search', 'Giây', 'Chi phí'], res.calls.map(c => `<tr>
        <td class="l">${esc(fmtTime(c.at))}</td><td class="l mono">${esc(c.campaign)}</td><td class="l">${esc(ROLE_NAMES[c.role] || c.role)}</td>
        <td class="l mono">${esc(c.model)}</td><td class="l">${(c.tokens_in || 0).toLocaleString('vi-VN')} / ${(c.tokens_out || 0).toLocaleString('vi-VN')}</td>
        <td class="l">${c.web_searches || 0}</td><td class="l">${esc(c.seconds)}</td><td class="l">${money(c.usd)}</td></tr>`));
    }
    $('#campHistBody').innerHTML = html;
    $('#campHistBody').onclick = e => { const a = e.target.closest('[data-ext]'); if (a) { e.preventDefault(); api('open_url', a.getAttribute('href')); } };
  }

  window.CampaignStudio = { show, onEvent };
  window.addEventListener('pywebviewready', () => setTimeout(loadOverview, 600));
})();
