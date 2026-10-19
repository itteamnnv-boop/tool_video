/* 🤖 Trợ lý quảng cáo Meta — 2 màn:
   1) Quản lý chiến lược: thống kê, tìm / lọc, lưới thẻ chiến lược (mở, nhân bản, xoá);
   2) Bàn làm việc của 1 chiến lược: chat với model (trình duyệt / API) → model điền form → gửi duyệt →
      tạo tạm dừng / lên lịch / chạy ngay (2 cách cuối tiêu tiền thật → hộp xác nhận riêng).
   Dùng chung helper của app.js: $, api, esc, toast, openModal, closeModal, state, profileOptions, navigate. */
(() => {
  'use strict';

  const A = { meta: null, plans: [], cur: null, accounts: null, accountsError: '', posts: {}, busy: false,
    model: 'chatgpt_browser', profile: '', showBrowser: false, interestHits: [], bound: false, q: '', filter: 'all' };
  const QUICK = ['Phân tích fanpage và đề xuất bài nên chạy quảng cáo',
    'Tối ưu để có nhiều tương tác và tin nhắn hỏi giá',
    'Ngân sách 200.000đ/ngày trong 7 ngày, khách hàng nông dân miền Tây',
    'Giải thích vì sao chọn các thông số này'];
  const LIVE = ['paused', 'scheduled', 'running'];
  const FIELD = { account_id: 'tài khoản', page_id: 'fanpage', post_id: 'bài viết', objective: 'mục tiêu', name: 'tên', daily_budget: 'ngân sách',
    days: 'số ngày', start_at: 'giờ bắt đầu', countries: 'quốc gia', age_min: 'tuổi từ', age_max: 'tuổi đến', gender: 'giới tính', interests: 'sở thích' };
  const FILTERS = [['all', 'Tất cả'], ['draft', 'Nháp'], ['pending', 'Chờ duyệt'], ['scheduled', 'Đã lên lịch'],
    ['running', 'Đang chạy'], ['paused', 'Tạm dừng'], ['error', 'Lỗi']];

  async function show() {
    if (!A.bound) { bind(); A.bound = true; }
    if (!A.meta) {
      const res = await api('adbot_meta');
      if (!res.ok) return toast(res.error, 'error');
      A.meta = res;
      if (!res.models.some(m => m.id === A.model)) A.model = (res.models.find(m => m.ready) || res.models[0] || {}).id || '';
    }
    await loadPlans();
    if (A.cur) await open(A.cur.id);
    render();
    if (A.accounts === null) loadAccounts();
  }

  async function loadPlans() {
    const res = await api('adbot_list');
    A.plans = res.ok ? res.plans : [];
  }

  async function loadAccounts() {
    A.accounts = [];
    const res = await api('ads_accounts');
    A.accounts = res.ok ? (res.accounts || []) : [];
    A.accountsError = res.ok ? '' : res.error;
    render();
  }

  async function loadPosts(pageId) {
    if (!pageId || A.posts[pageId]) return;
    A.posts[pageId] = { loading: true, posts: [] };
    const res = await api('ads_page_posts', pageId, '');
    A.posts[pageId] = { posts: res.ok ? ((res.posts || {}).posts || []) : [], error: res.ok ? '' : res.error };
    render();
  }

  async function open(id) {
    const res = await api('adbot_get', id);
    if (!res.ok) { A.cur = null; return toast(res.error, 'error'); }
    A.cur = res.plan;
    loadPosts(A.cur.form.page_id);
  }

  // ------------------------------------------------------------ tiện ích
  const statusLabel = s => (A.meta.statuses || {})[s] || s;
  const fmt = n => (n === '' || n == null ? '' : Number(n).toLocaleString('vi-VN'));
  const locked = () => LIVE.includes(A.cur.status);
  const accountOf = f => (A.accounts || []).find(a => a.id === f.account_id) || {};
  const currencyOf = accountId => ((A.accounts || []).find(a => a.id === accountId) || {}).currency || '';
  const objName = k => { const o = A.meta.objectives[k]; return (o && o.name) || o || k || ''; };
  const dmy = iso => (iso ? String(iso).slice(0, 16).replace('T', ' ').replace(/^(\d{4})-(\d\d)-(\d\d)/, '$3/$2/$1') : '');
  const adsManagerUrl = (accountId, campaignId) =>
    `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=${encodeURIComponent(String(accountId || '').replace('act_', ''))}`
    + (campaignId ? `&selected_campaign_ids=${encodeURIComponent(campaignId)}` : '');

  function render() {
    const box = $('#adbotBody');
    if (!box || !A.meta) return;
    const draft = ($('#abMsg') || {}).value || '';
    const head = $('#page-adbot .page-head');
    if (head) head.classList.toggle('hidden', !!A.cur);  // bàn làm việc: nhường chỗ cho chat + form
    box.innerHTML = A.cur ? workHtml() : listHtml();
    const input = $('#abMsg');
    if (input && draft) input.value = draft;
    const log = box.querySelector('.ab-msgs');
    if (log) log.scrollTop = log.scrollHeight;
  }

  // ------------------------------------------------------------ màn 1: quản lý chiến lược
  function listed() {
    const q = A.q.trim().toLowerCase();
    return A.plans.filter(p => (A.filter === 'all' || p.status === A.filter)
      && (!q || `${p.name} ${p.strategy || ''} ${p.post_preview || ''}`.toLowerCase().includes(q)));
  }

  function gridHtml() {
    const list = listed();
    if (!list.length) return `<div class="empty">${A.plans.length ? 'Không có chiến lược khớp bộ lọc.' : 'Chưa có chiến lược — bấm “+ Chiến lược mới” rồi trò chuyện với trợ lý.'}</div>`;
    return list.map(p => {
      const cur = p.currency || currencyOf(p.account_id);
      const total = (+p.budget || 0) * (+p.days || 0);
      const live = LIVE.includes(p.status);
      return `<div class="st-pcard ab-card ${esc(p.status)}">
        <button class="st-pthumb" data-open="${esc(p.id)}" type="button" title="Mở chiến lược">
          ${p.post_picture ? `<img src="${esc(p.post_picture)}" alt="" loading="lazy">` : '<span>📣</span>'}
          <i class="st-pbadge ab-badge ${esc(p.status)}">${esc(statusLabel(p.status))}</i>
          ${p.messages ? `<i class="st-pfinal">💬 ${Math.ceil(p.messages / 2)}</i>` : ''}</button>
        <div class="st-pbody">
          <button class="st-pname" data-open="${esc(p.id)}" type="button" title="${esc(p.name)}">${esc(p.name)}</button>
          <p class="st-pidea">${esc(p.strategy || p.post_preview || 'Chưa có chiến lược — mở để trò chuyện với trợ lý')}</p>
          <div class="st-pmeta">
            ${p.objective ? `<span>🎯 ${esc(objName(p.objective))}</span>` : ''}
            ${p.budget ? `<span>💰 ${fmt(p.budget)}${cur ? ' ' + esc(cur) : ''}/ngày × ${p.days}</span>` : '<span>💰 chưa có ngân sách</span>'}
            ${total ? `<span>Σ tối đa ${fmt(total)}${cur ? ' ' + esc(cur) : ''}</span>` : ''}
            <span>👥 ${esc(p.countries || 'VN')} · ${esc(p.ages || '')}${p.interests ? ` · ${p.interests} sở thích` : ''}</span>
            ${p.start_at ? `<span>🗓 ${esc(dmy(p.start_at))}</span>` : ''}
            ${p.approved_by && live ? `<span>✅ ${esc(p.approved_by)} · ${esc(dmy(p.approved_at))}</span>` : ''}
          </div>
          ${p.status === 'error' && p.error ? `<small class="ab-err ab-clamp">${esc(p.error)}</small>` : ''}
          <div class="st-pact"><button class="btn ${p.status === 'pending' ? 'primary' : 'ghost'} sm" data-open="${esc(p.id)}" type="button">${p.status === 'pending' ? 'Duyệt' : 'Mở'}</button>
            ${live && p.campaign_id ? `<button class="btn ghost sm" data-am="${esc(p.account_id)}|${esc(p.campaign_id)}" type="button" title="Mở trong Ads Manager">↗</button>` : ''}
            <button class="btn ghost sm" data-clone="${esc(p.id)}" type="button" title="Nhân bản thành bản nháp mới">⧉</button>
            ${live ? '' : `<button class="btn ghost sm st-pdel" data-del-id="${esc(p.id)}" type="button" title="Xoá">🗑</button>`}</div>
        </div></div>`;
    }).join('');
  }

  function listHtml() {
    const count = s => A.plans.filter(p => p.status === s).length;
    const runningBudget = A.plans.filter(p => p.status === 'running')
      .reduce((m, p) => { const c = p.currency || currencyOf(p.account_id) || ''; m[c] = (m[c] || 0) + (+p.budget || 0); return m; }, {});
    const spend = Object.entries(runningBudget).filter(([, v]) => v).map(([c, v]) => `${fmt(v)}${c ? ' ' + c : ''}`).join(' + ');
    const stats = [['📋', `${A.plans.length} chiến lược`], ['⏳', `${count('pending')} chờ duyệt`], ['🗓', `${count('scheduled')} đã lên lịch`],
      ['▶', `${count('running')} đang chạy`], ['⏸', `${count('paused')} tạm dừng`]];
    return `<div class="st-page">
      <div class="card st-lhead">
        <div class="st-lhead-top"><div class="ab-lhead-title"><b class="st-ltitle">Chiến lược quảng cáo</b>
          <div class="st-stats">${stats.map(([i, t]) => `<span class="st-stat">${i} ${t}</span>`).join('')}
            ${spend ? `<span class="st-stat ab-spend">💰 ${esc(spend)}/ngày đang chạy</span>` : ''}
            ${count('error') ? `<span class="st-stat ab-stat-err">⚠ ${count('error')} lỗi</span>` : ''}</div></div>
          <div class="row st-lhead-act">
            <button class="btn ghost" data-go-ads type="button">📊 Quảng cáo Facebook</button>
            <button class="btn primary" data-new type="button">+ Chiến lược mới</button></div></div>
        ${bannersHtml()}
        <div class="row st-lfilter"><input id="abSearch" type="search" placeholder="🔍 Tìm theo tên / chiến lược / bài viết…" value="${esc(A.q)}">
          <div class="st-chips">${FILTERS.map(([k, label]) => {
            const n = k === 'all' ? A.plans.length : count(k);
            return `<button class="chip-f ${A.filter === k ? 'active' : ''}" data-filter="${k}" type="button">${label}${n ? ` <span>${n}</span>` : ''}</button>`;
          }).join('')}</div></div>
      </div>
      <div class="st-grid" id="abGrid">${gridHtml()}</div></div>`;
  }

  function bannersHtml() {
    const ads = A.meta.ads || {};
    return `${ads.logged_in === false ? '<div class="ab-banner bad">Chưa kết nối Facebook — vào Fanpage Facebook để kết nối.</div>'
      : (ads.missing_permissions || []).length ? `<div class="ab-banner">Token Facebook thiếu quyền: ${esc(ads.missing_permissions.join(', '))} — cấp thêm ở Fanpage Facebook.</div>` : ''}
      ${A.accountsError ? `<div class="ab-banner bad">${esc(A.accountsError)}</div>` : ''}`;
  }

  // ------------------------------------------------------------ màn 2: bàn làm việc của 1 chiến lược
  function workHtml() {
    return `<div class="st-page">
      <div class="st-crumbs ab-crumbs"><button class="btn ghost sm" data-back type="button">← Tất cả chiến lược</button>
        <span class="muted">/</span><input id="abName" value="${esc(A.cur.name)}" ${locked() ? 'disabled' : ''} aria-label="Tên chiến lược">
        <span class="ab-status ${esc(A.cur.status)}">${esc(statusLabel(A.cur.status))}</span>
        <span class="ab-crumb-act">
          <button class="btn ghost sm" data-clone="${esc(A.cur.id)}" type="button" title="Nhân bản thành bản nháp mới">⧉ Nhân bản</button>
          ${locked() ? '' : `<button class="btn ghost sm st-pdel" data-del-id="${esc(A.cur.id)}" type="button" title="Xoá chiến lược">🗑</button>`}</span></div>
      ${bannersHtml()}
      <div class="ab-work">${chatHtml()}${formHtml()}</div></div>`;
  }

  function chatHtml() {
    const models = A.meta.models;
    const m = models.find(x => x.id === A.model) || {};
    const profiles = m.site && state.profiles && (state.profileSites || {})[m.site]
      ? `<select data-ab-profile title="Profile trình duyệt">${profileOptions(m.site, A.profile)}</select>` : '';
    return `<section class="card ab-chat">
      <div class="ab-chat-head"><b>💬 Trợ lý AI</b>
        <select data-ab-model title="Model phân tích">${models.map(x => `<option value="${esc(x.id)}" ${x.id === A.model ? 'selected' : ''}>${esc(x.name)}${x.ready ? '' : ' — chưa sẵn sàng'}</option>`).join('')}</select>
        ${profiles}</div>
      <div class="ab-msgs">${A.cur.chat.length ? A.cur.chat.map(msg => `<div class="ab-msg ${msg.role === 'user' ? 'user' : 'assistant'}">
          <div class="ab-bubble">${esc(msg.text)}</div>
          ${msg.role !== 'user' && (msg.changed || []).length ? `<small class="ab-changed">✓ Đã điền: ${msg.changed.map(k => esc(FIELD[k] || k)).join(', ')}</small>` : ''}</div>`).join('')
        : `<div class="ab-hello"><b>Bắt đầu thế nào?</b><br>Mô tả sản phẩm, khách hàng mục tiêu, khu vực, ngân sách và mục tiêu (tương tác, tiếp cận, xem video…).
          Trợ lý đọc fanpage, chọn bài phù hợp và <b>điền form bên phải</b> — bạn kiểm tra rồi mới duyệt. Trợ lý <b>không tự chạy</b> quảng cáo.</div>`}
        ${A.busy ? '<div class="ab-msg assistant"><div class="ab-bubble ab-typing">⏳ Model đang phân tích… (model trình duyệt mất 1–3 phút)</div></div>' : ''}</div>
      ${locked() ? '<div class="ab-locked">Quảng cáo đã tạo trên Meta — bấm “⧉ Nhân bản” để lên chiến lược tương tự.</div>' : `
      <div class="ab-quick">${QUICK.map(q => `<button class="ab-q" data-quick="${esc(q)}" type="button" ${A.busy ? 'disabled' : ''}>${esc(q)}</button>`).join('')}</div>
      <div class="ab-input"><textarea id="abMsg" rows="2" placeholder="Nhập yêu cầu… (Ctrl+Enter để gửi)" ${A.busy ? 'disabled' : ''}></textarea>
        <button class="btn primary" data-send type="button" ${A.busy ? 'disabled' : ''}>Gửi</button></div>`}
    </section>`;
  }

  function formHtml() {
    const f = A.cur.form;
    const dis = locked() || A.busy ? 'disabled' : '';
    const pages = (A.meta.ads || {}).pages || [];
    const cur = accountOf(f).currency || '';
    const postState = A.posts[f.page_id] || {};
    const post = (postState.posts || []).find(p => p.id === f.post_id)
      || (f.post_id && (f.post_preview || f.post_picture) ? { message: f.post_preview, picture: f.post_picture } : null);
    const budget = +f.daily_budget || 0;
    const opt = (pairs, v) => pairs.map(([k, l]) => `<option value="${esc(k)}" ${String(k) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');
    const chosen = new Set((f.interests || []).map(i => i.id));
    const extra = [...A.interestHits, ...(A.cur.interest_options || [])]
      .filter((o, i, all) => !chosen.has(o.id) && all.findIndex(x => x.id === o.id) === i);
    const postOpts = (postState.posts || []).map(p => [p.id, `${(p.message || '(không có chữ)').replace(/\s+/g, ' ').slice(0, 70)} · ${p.reactions || 0}❤ ${p.comments || 0}💬`]);
    if (f.post_id && !postOpts.some(o => o[0] === f.post_id)) postOpts.unshift([f.post_id, (f.post_preview || `Bài ${f.post_id}`).slice(0, 70)]);
    const objectives = Object.keys(A.meta.objectives).map(k => [k, objName(k)]);
    return `<section class="ab-form">
      <div class="card ab-sec"><div class="ab-sec-title"><i>1</i> Bài quảng cáo</div>
        ${postState.error ? `<div class="ab-banner bad">${esc(postState.error)}</div>` : ''}
        <div class="ab-grid">
          <label class="field"><span>Tài khoản quảng cáo</span><select data-f="account_id" ${dis}>${opt([['', A.accounts === null || (A.accounts.length === 0 && !A.accountsError) ? 'Đang tải… / chưa có' : '— Chọn —'], ...(A.accounts || []).map(a => [a.id, `${a.name} (${a.currency})`])], f.account_id)}</select></label>
          <label class="field"><span>Fanpage</span><select data-f="page_id" ${dis}>${opt([['', '— Chọn —'], ...pages.map(p => [p.id, p.name])], f.page_id)}</select></label>
        </div>
        <label class="field"><span>Bài viết ${postState.loading ? '· đang tải…' : ''}</span>
          <select data-f="post_id" ${dis}>${opt([['', f.page_id ? '— Chọn bài (trợ lý có thể gợi ý) —' : 'Chọn fanpage trước'], ...postOpts], f.post_id)}</select></label>
        ${post ? `<div class="ab-post">${post.picture ? `<img src="${esc(post.picture)}" alt="">` : ''}<p>${esc((post.message || '').slice(0, 280))}</p></div>` : ''}
      </div>
      <div class="card ab-sec"><div class="ab-sec-title"><i>2</i> Mục tiêu & ngân sách</div>
        <div class="ab-grid">
          <label class="field"><span>Mục tiêu</span><select data-f="objective" ${dis}>${opt(objectives, f.objective)}</select></label>
          <label class="field"><span>Tên chiến dịch</span><input data-f="name" value="${esc(f.name || '')}" ${dis} placeholder="Tự đặt nếu để trống"></label>
          <label class="field"><span>Ngân sách / ngày ${cur ? `(${esc(cur)})` : ''}</span><input data-f="daily_budget" type="number" min="0" step="1000" value="${esc(f.daily_budget)}" ${dis}></label>
          <label class="field"><span>Số ngày chạy</span><input data-f="days" type="number" min="1" max="90" value="${esc(f.days)}" ${dis}></label>
          <label class="field ab-wide"><span>Giờ bắt đầu (trống = sớm nhất khi duyệt)</span><input data-f="start_at" type="datetime-local" value="${esc(f.start_at || '')}" ${dis}></label>
        </div></div>
      <div class="card ab-sec"><div class="ab-sec-title"><i>3</i> Đối tượng</div>
        <div class="ab-grid ab-grid3">
          <label class="field"><span>Quốc gia (mã 2 chữ)</span><input data-f="countries" value="${esc(f.countries)}" ${dis}></label>
          <label class="field"><span>Độ tuổi</span><span class="ab-age"><input data-f="age_min" type="number" min="13" max="65" value="${esc(f.age_min)}" ${dis}><i>–</i><input data-f="age_max" type="number" min="13" max="65" value="${esc(f.age_max)}" ${dis}></span></label>
          <label class="field"><span>Giới tính</span><select data-f="gender" ${dis}>${opt([['all', 'Tất cả'], ['male', 'Nam'], ['female', 'Nữ']], f.gender)}</select></label>
        </div>
        <div class="field"><span>Sở thích (nhắm mục tiêu chi tiết)</span>
          <div class="ab-chips">${(f.interests || []).map(i => `<span class="ab-chip on">${esc(i.name || i.id)}${dis ? '' : `<button data-int-del="${esc(i.id)}" type="button" title="Bỏ">✕</button>`}</span>`).join('') || '<small class="ab-muted">Chưa chọn — Meta tự mở rộng đối tượng</small>'}</div>
          ${extra.length && !dis ? `<div class="ab-chips">${extra.slice(0, 18).map(o => `<button class="ab-chip" data-int-add="${esc(o.id)}" data-name="${esc(o.name)}" type="button" title="${esc(o.path || '')}${o.size ? ` · ~${fmt(o.size)} người` : ''}">+ ${esc(o.name)}</button>`).join('')}</div>` : ''}
          ${dis ? '' : '<div class="ab-int-search"><input id="abIntQ" placeholder="Tìm sở thích của Meta (vd. Agriculture, Fertilizer)"><button class="btn ghost sm" data-int-search type="button">Tìm</button></div>'}</div>
      </div>
      ${A.cur.strategy || A.cur.kpi ? `<div class="card ab-sec ab-strategy"><div class="ab-sec-title"><i>4</i> Chiến lược của trợ lý</div>
        ${A.cur.strategy ? `<p>${esc(A.cur.strategy)}</p>` : ''}${A.cur.kpi ? `<p><b>Dự kiến:</b> ${esc(A.cur.kpi)} <small class="ab-muted">(ước lượng của AI)</small></p>` : ''}</div>` : ''}
      <div class="card ab-dock">
        <div class="ab-summary">💰 ${budget ? `<b>${fmt(budget)} ${esc(cur)}</b>/ngày × <b>${f.days}</b> ngày = tối đa <b>${fmt(budget * f.days)} ${esc(cur)}</b>` : 'Chưa nhập ngân sách'}
          <small>${f.start_at ? `bắt đầu ${esc(dmy(f.start_at))}` : 'bắt đầu sớm nhất khi duyệt'}</small></div>
        ${actionsHtml()}
      </div>
    </section>`;
  }

  function actionsHtml() {
    const s = A.cur.status;
    const ap = A.cur.approval || {};
    if (LIVE.includes(s)) {
      const r = ap.result || {};
      return `<div class="ab-done"><b>✅ ${esc(statusLabel(s))}</b> · duyệt bởi ${esc(ap.by || '')} lúc ${esc(dmy(ap.at))}
        <small class="ab-mono">Chiến dịch ${esc(r.campaign_id || '')} · nhóm ${esc(r.adset_id || '')} · quảng cáo ${esc(r.ad_id || '')}</small>
        <div class="ab-row"><button class="btn ghost sm" data-am="${esc(A.cur.form.account_id)}|${esc(r.campaign_id || '')}" type="button">Mở Ads Manager ↗</button>
          <button class="btn ghost sm" data-go-ads type="button">Xem ở Quảng cáo Facebook</button></div></div>`;
    }
    if (s === 'pending') {
      return `<div class="ab-approve"><small class="ab-muted">⏳ Chờ duyệt — chọn cách chạy (sửa form sẽ đưa về nháp)</small>
        <div class="ab-row"><button class="btn ghost" data-approve="paused" type="button" title="Tạo chiến dịch ở trạng thái tạm dừng — chưa tốn tiền">⏸ Tạo (tạm dừng)</button>
          <button class="btn ghost" data-approve="schedule" type="button" ${A.cur.form.start_at ? '' : 'disabled title="Nhập giờ bắt đầu ở tương lai để lên lịch"'}>🗓 Lên lịch</button>
          <button class="btn primary" data-approve="now" type="button">▶ Chạy ngay</button></div></div>`;
    }
    return `<div class="ab-approve">
      ${s === 'error' && ap.error ? `<small class="ab-err">Lỗi tạo quảng cáo: ${esc(ap.error)}</small>` : ''}
      <div class="ab-row"><button class="btn primary" data-submit type="button" ${A.busy ? 'disabled' : ''}>📨 Gửi duyệt</button>
      <small class="ab-muted">Sau đó chọn: tạo tạm dừng / lên lịch / chạy ngay.</small></div></div>`;
  }

  // ------------------------------------------------------------ thao tác
  async function saveForm(patch) {
    const res = await api('adbot_save', A.cur.id, { form: { ...A.cur.form, ...patch } });
    if (!res.ok) { toast(res.error, 'error'); return render(); }
    A.cur = res.plan;
    await loadPlans();
    render();
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text || A.busy || !A.cur) return;
    const id = A.cur.id;
    A.busy = true;
    A.cur.chat = [...A.cur.chat, { role: 'user', text }];
    const input = $('#abMsg');
    if (input) input.value = '';
    render();
    const res = await api('adbot_chat', id, text, A.model, A.profile, A.showBrowser);
    A.busy = false;
    if (!res.ok) toast(res.error, 'error');
    await loadPlans();
    if (A.cur && A.cur.id === id) {
      if (res.ok) A.cur = res.plan; else await open(id);
      if (A.cur) loadPosts(A.cur.form.page_id);
    } else if (res.ok) {
      toast(`Trợ lý đã trả lời “${res.plan.name}”`, 'ok');
    }
    render();
  }

  function approveDialog(mode) {
    const f = A.cur.form;
    const acc = accountOf(f);
    const cur = acc.currency || '';
    const total = (+f.daily_budget || 0) * f.days;
    const what = {
      paused: 'Tạo chiến dịch ở trạng thái TẠM DỪNG — chưa tốn tiền, bạn tự bật trong Ads Manager khi sẵn sàng.',
      schedule: `Lên lịch: quảng cáo TỰ CHẠY lúc ${dmy(f.start_at)} và tiêu tiền thật.`,
      now: 'Chạy NGAY sau khi tạo (vài phút, sau khi Meta duyệt nội dung) và tiêu tiền thật.',
    }[mode];
    openModal('DUYỆT QUẢNG CÁO', A.cur.name, `<div class="ab-confirm">
      <p>${esc(what)}</p>
      <ul><li>Tài khoản: <b>${esc(acc.name || f.account_id)}</b></li>
        <li>Mục tiêu: <b>${esc(objName(f.objective))}</b> · ${f.days} ngày · ${esc(f.countries)} · ${f.age_min}–${f.age_max} tuổi</li>
        <li>Ngân sách: <b>${fmt(f.daily_budget)} ${esc(cur)}/ngày</b> → tối đa <b>${fmt(total)} ${esc(cur)}</b></li></ul>
      ${mode === 'paused' ? '' : '<label class="check ab-agree"><input type="checkbox" id="abAgree"> Tôi đã kiểm tra và đồng ý chạy quảng cáo, chấp nhận chi phí trên</label>'}
      <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-ab-cancel type="button">Huỷ</button>
        <button class="btn primary" data-ab-go type="button">${{ paused: '⏸ Tạo (tạm dừng)', schedule: '🗓 Xác nhận lên lịch', now: '▶ Xác nhận chạy ngay' }[mode]}</button></div></div>`, true);
    const body = $('#modalBody');
    body.querySelector('[data-ab-cancel]').onclick = closeModal;
    const go = body.querySelector('[data-ab-go]');
    go.onclick = async () => {
      const agreed = mode === 'paused' || ($('#abAgree') || {}).checked;
      if (!agreed) return toast('Tick ô xác nhận đồng ý chi phí trước', 'warn');
      go.disabled = true; go.textContent = 'Đang tạo trên Meta…';
      const res = await api('adbot_approve', A.cur.id, mode, mode !== 'paused');
      closeModal();
      if (!res.ok) { toast(res.error, 'error'); await open(A.cur.id); await loadPlans(); return render(); }
      A.cur = res.plan;
      await loadPlans();
      render();
      toast({ paused: 'Đã tạo chiến dịch (tạm dừng)', schedule: 'Đã lên lịch chạy quảng cáo', now: 'Đã tạo quảng cáo — sẽ chạy sau khi Meta duyệt' }[mode], 'ok');
    };
  }

  async function remove(id) {
    const p = A.plans.find(x => x.id === id) || A.cur || {};
    if (!confirm(`Xoá chiến lược “${p.name || ''}”?`)) return;
    await api('adbot_delete', id);
    if (A.cur && A.cur.id === id) A.cur = null;
    await loadPlans();
    render();
  }

  function bind() {
    const box = $('#adbotBody');
    box.addEventListener('click', async e => {
      const t = e.target.closest('button');
      if (!t || t.disabled) return;
      const d = t.dataset;
      if (d.new !== undefined) {
        const res = await api('adbot_create', {});
        if (!res.ok) return toast(res.error, 'error');
        A.cur = res.plan; A.interestHits = [];
        await loadPlans(); loadPosts(A.cur.form.page_id); return render();
      }
      if (d.open) { A.interestHits = []; await open(d.open); return render(); }
      if (d.back !== undefined) { A.cur = null; A.interestHits = []; await loadPlans(); return render(); }
      if (d.filter) { A.filter = d.filter; return render(); }
      if (d.clone) {
        const res = await api('adbot_clone', d.clone);
        if (!res.ok) return toast(res.error, 'error');
        A.cur = res.plan; A.interestHits = [];
        await loadPlans(); loadPosts(A.cur.form.page_id); render();
        return toast('Đã nhân bản thành bản nháp mới', 'ok');
      }
      if (d.delId) return remove(d.delId);
      if (d.am !== undefined) { const [acc, camp] = d.am.split('|'); return api('open_url', adsManagerUrl(acc, camp)); }
      if (d.goAds !== undefined) return navigate('ads');
      if (!A.cur) return;
      if (d.send !== undefined) return send(($('#abMsg') || {}).value);
      if (d.quick) return send(d.quick);
      if (d.intDel) return saveForm({ interests: A.cur.form.interests.filter(i => i.id !== d.intDel) });
      if (d.intAdd) return saveForm({ interests: [...A.cur.form.interests, { id: d.intAdd, name: d.name }] });
      if (d.intSearch !== undefined) {
        const q = (($('#abIntQ') || {}).value || '').trim();
        if (!q) return;
        const res = await api('adbot_interests', q);
        if (!res.ok) return toast(res.error, 'error');
        A.interestHits = res.items || [];
        if (!A.interestHits.length) toast('Không tìm thấy sở thích phù hợp', 'warn');
        return render();
      }
      if (d.submit !== undefined) {
        const res = await api('adbot_submit', A.cur.id);
        if (!res.ok) return toast(res.error, 'warn');
        A.cur = res.plan; await loadPlans(); render();
        return toast('Đã gửi duyệt — chọn cách chạy bên dưới', 'ok');
      }
      if (d.approve) return approveDialog(d.approve);
    });
    box.addEventListener('input', e => {
      if (e.target.id !== 'abSearch') return;
      A.q = e.target.value;
      const g = $('#abGrid');
      if (g) g.innerHTML = gridHtml();
    });
    box.addEventListener('change', async e => {
      const t = e.target;
      if (t.dataset.abModel !== undefined) { A.model = t.value; A.profile = ''; return render(); }
      if (t.dataset.abProfile !== undefined) { A.profile = t.value; return; }
      if (t.dataset.abShow !== undefined) { A.showBrowser = t.checked; return; }
      if (!A.cur) return;
      if (t.id === 'abName') {
        const res = await api('adbot_save', A.cur.id, { name: t.value });
        if (res.ok) { A.cur = res.plan; await loadPlans(); render(); }
        return;
      }
      if (t.dataset.f) {
        const key = t.dataset.f;
        if (key === 'page_id') { loadPosts(t.value); return saveForm({ page_id: t.value, post_id: '', post_preview: '', post_picture: '' }); }
        if (key === 'post_id') {  // lưu kèm xem trước + ảnh bài để thẻ chiến lược hiện đúng bài
          const post = ((A.posts[A.cur.form.page_id] || {}).posts || []).find(p => p.id === t.value) || {};
          return saveForm({ post_id: t.value, post_preview: (post.message || '').replace(/\s+/g, ' ').slice(0, 300), post_picture: post.picture || '' });
        }
        return saveForm({ [key]: t.value });
      }
    });
    box.addEventListener('keydown', e => {
      if (e.target.id === 'abMsg' && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(e.target.value); }
      if (e.target.id === 'abIntQ' && e.key === 'Enter') { e.preventDefault(); box.querySelector('[data-int-search]').click(); }
    });
  }

  window.AdBotPage = { show };
})();
