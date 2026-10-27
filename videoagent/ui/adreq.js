/* 📨 Trợ lý quảng cáo → tab "Yêu cầu từ nhóm": TRÒ CHUYỆN với Claude (claude.ai đã kết nối MCP quảng cáo Meta).
   Bên trái: khung chat (dán tin nhắn nhóm hoặc hỏi tự do) — mỗi lượt gửi cho Claude, tiếp tục đúng cuộc trò chuyện trên
   claude.ai; Claude chỉ ĐỌC dữ liệu qua MCP, trả lời + đề xuất việc cần làm. Bên phải: thẻ CHỜ DUYỆT tạo từ đề xuất
   (app kiểm chứng id với tài khoản) → tick / đổi nhóm → Duyệt mới thực hiện. Thao tác tiêu tiền (💸) cần xác nhận riêng.
   Dùng chung helper của app.js: $, $$, api, esc, toast, openModal, closeModal. */
(() => {
  'use strict';
  const TAB_KEY = 'va.ad.tab';
  const ALL = '__all__';  // phạm vi "tất cả tài khoản quảng cáo"
  const accName = id => (id === ALL ? 'Tất cả tài khoản' : ((R.accounts.find(a => a.id === id) || {}).name || id || ''));
  const R = { meta: null, list: [], accounts: [], account: '', filter: 'todo', q: '', showBrowser: true,
    chats: [], chat: null, sending: false, status: '', statusWarn: false, editing: null, rawOpen: new Set(), flash: '',
    zalo: null, zaloOpen: false, zaloSel: new Set(), zaloSending: false };
  const FILTERS = [['todo', 'Chờ duyệt'], ['done', 'Đã xử lý'], ['rejected', 'Từ chối'], ['all', 'Tất cả']];
  const SUGGEST = ['Rà soát tài khoản 7 ngày qua — nhóm nào đang chi nhiều mà ít kết quả?',
    'Quảng cáo nào đang bị từ chối hoặc có lỗi?',
    'Nhóm nào đang tắt nhưng trước đó có kết quả tốt, nên bật lại?',
    'Tóm tắt chi tiêu hôm nay theo từng page'];
  const inFilter = (r, f) => f === 'all' || (f === 'todo' ? ['new', 'proposed', 'error', 'partial'].includes(r.status)
    : f === 'done' ? r.status === 'done' : r.status === f);
  const ST_CLASS = { new: 'wait', proposed: 'wait', done: 'ok', partial: 'warn', error: 'bad', rejected: 'off' };
  const EFF = s => ({ ACTIVE: ['Đang chạy', 'on'], PAUSED: ['Tạm dừng', 'off'], CAMPAIGN_PAUSED: ['Chiến dịch dừng', 'off'],
    ADSET_PAUSED: ['Nhóm dừng', 'off'], PENDING_REVIEW: ['Chờ duyệt', 'wait'], WITH_ISSUES: ['Có lỗi', 'bad'],
    DISAPPROVED: ['Bị từ chối', 'bad'], ARCHIVED: ['Lưu trữ', 'off'] }[s] || [s || '—', 'off']);
  const tag = s => { const [t, c] = EFF(s); return `<span class="ar-eff ${c}">${esc(t)}</span>`; };
  const hhmm = at => `${(at || '').slice(11, 16)} ${(at || '').slice(8, 10)}/${(at || '').slice(5, 7)}`;

  // tô màu JSON (khoá / chuỗi / số / true-false-null) — chữ đã esc từng mảnh
  function hlJson(code) {
    let out = '', at = 0;
    const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
    for (let m; (m = re.exec(code));) {
      out += esc(code.slice(at, m.index));
      if (m[1]) out += m[2] ? `<span class="j-key">${esc(m[1])}</span>${esc(m[2])}` : `<span class="j-str">${esc(m[1])}</span>`;
      else if (m[3]) out += `<span class="j-lit">${m[3]}</span>`;
      else out += `<span class="j-num">${m[0]}</span>`;
      at = re.lastIndex;
    }
    return out + esc(code.slice(at));
  }
  // thẻ code kiểu claude.ai: thanh tiêu đề (ngôn ngữ · sao chép · thu gọn) + nội dung tô màu; dài thì thu gọn sẵn
  function codeCard(lang, code) {
    code = String(code || '').replace(/\s+$/, '');
    let pretty = code;
    if (/^json$/i.test(lang) || (!lang && /^\s*[{[]/.test(code))) {
      try { pretty = JSON.stringify(JSON.parse(code), null, 2); lang = 'json'; } catch { /* để nguyên */ }
    }
    const lines = pretty.split('\n').length;
    const empty = /^\{\s*"yeu_cau":\s*\[\s*\]\s*\}$/.test(pretty.replace(/\s+/g, ' ').trim());
    return `<div class="ac-code ${lines > 14 ? 'folded' : ''}">
      <div class="ac-code-head"><span class="ac-lang">${esc(lang || 'code')}</span>${empty ? '<small>không có đề xuất</small>' : lines > 1 ? `<small>${lines} dòng</small>` : ''}
        <span class="ar-sp"></span>
        <button type="button" data-code="copy" title="Sao chép">⧉ Sao chép</button>
        ${lines > 14 ? '<button type="button" data-code="fold" title="Thu gọn / mở rộng">Mở rộng ▾</button>' : ''}</div>
      <pre><code>${lang === 'json' ? hlJson(pretty) : esc(pretty)}</code></pre></div>`;
  }
  // markdown tối giản cho lời Claude: khối ```code```, **đậm**, *nghiêng*, `mã`, gạch đầu dòng, xuống dòng
  function md(text) {
    const blocks = [];
    const src = String(text || '').replace(/```(\w*)[ \t]*\n?([\s\S]*?)```/g, (_, lang, code) => `\u0000${blocks.push(codeCard(lang, code)) - 1}\u0000`);
    return esc(src).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<i>$2</i>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .split('\n').map(l => (/^\s*[-•*]\s+/.test(l) ? `<li>${l.replace(/^\s*[-•*]\s+/, '')}</li>` : /^\u0000\d+\u0000$/.test(l.trim()) ? l.trim() : l ? `<p>${l}</p>` : ''))
      .join('').replace(/(<li>.*?<\/li>)+/g, m => `<ul>${m}</ul>`)
      .replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]);
  }

  // ------------------------------------------------------------ tab trên màn Trợ lý quảng cáo
  function tabNow() { try { return localStorage.getItem(TAB_KEY) || 'requests'; } catch { return 'requests'; } }
  function applyTab(tab) {
    try { localStorage.setItem(TAB_KEY, tab); } catch { /* bỏ qua */ }
    $$('#adTabs [data-adtab]').forEach(b => b.classList.toggle('on', b.dataset.adtab === tab));
    $('#adreqBody').classList.toggle('hidden', tab !== 'requests');
    $('#adbotBody').classList.toggle('hidden', tab === 'requests');
    if (tab === 'requests') { show(); requestAnimationFrame(fit); }  // vừa hiện màn → đo lại chiều cao
  }

  async function show() {
    if (!R.meta) {
      const m = await api('adreq_meta');
      if (!m.ok) return toast(m.error, 'error');
      R.meta = m; R.account = ALL;  // mở app: mặc định làm việc trên TẤT CẢ tài khoản (chọn 1 tài khoản nếu muốn)
      api('ads_accounts').then(res => {
        R.accounts = res.ok ? res.accounts || [] : [];
        render();
      });
    }
    await Promise.all([load(), loadChats(), api('zalo_state').then(r => { if (r.ok) R.zalo = r.state; })]);
    if (!R.chat && R.chats[0]) await openChat(R.chats[0].id, false);
    render();
  }
  async function load() {
    const res = await api('adreq_list');
    R.list = res.ok ? res.requests : [];
    const n = R.list.filter(r => inFilter(r, 'todo')).length;
    const b = $('#adreqBadge');
    if (b) { b.textContent = n; b.classList.toggle('hidden', !n); }
  }
  async function loadChats() {
    const res = await api('adchat_list');
    R.chats = res.ok ? res.chats : [];
  }
  async function openChat(id, draw = true) {
    const res = await api('adchat_get', id);
    if (!res.ok) { R.chat = null; return toast(res.error, 'error'); }
    R.chat = res.chat;
    if (R.chat.account_id) R.account = R.chat.account_id;
    if (draw) render();
  }

  // ------------------------------------------------------------ vẽ
  function render() {
    const box = $('#adreqBody');
    if (!box || !R.meta) return;
    const draft = ($('#acInput') || {}).value || '';
    const scroll = $('#acMsgs') ? $('#acMsgs').scrollTop : null;
    box.innerHTML = `<div class="ac-wrap">${chatHtml()}${sideHtml()}</div>`;
    fit();
    const input = $('#acInput');
    if (input && draft) input.value = draft;
    const msgs = $('#acMsgs');
    if (msgs) msgs.scrollTop = scroll === null || R.sending ? msgs.scrollHeight : scroll;
    if (R.flash) {  // vừa bấm vào đề xuất trong chat → cuộn tới thẻ
      const el = $(`.ar-card[data-rid="${CSS.escape(R.flash)}"]`);
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.add('flash'); }
      R.flash = '';
    }
  }

  // khung chat + cột duyệt cao vừa khít màn hình: đo vị trí thật (tiêu đề / tab phía trên đổi chiều cao) thay vì trừ số cố định
  function fit() {
    const wrap = $('.ac-wrap');
    if (!wrap || !wrap.offsetParent) return;
    if (matchMedia('(max-width:1150px)').matches) { wrap.style.height = ''; return; }  // 1 cột: để CSS lo
    const page = wrap.closest('.panel.page');
    const top = wrap.getBoundingClientRect().top + (page ? page.scrollTop : 0);
    const bottom = page ? parseFloat(getComputedStyle(page).paddingBottom) || 0 : 0;
    wrap.style.height = `${Math.max(420, Math.floor(innerHeight - top - bottom))}px`;
  }
  addEventListener('resize', () => requestAnimationFrame(fit));

  function chatHtml() {
    const c = R.chat;
    const msgs = (c && c.messages) || [];
    return `<section class="card ac-chat">
      <header class="ac-head">
        <div class="ac-who"><span class="ac-avatar">✳</span><div><b>Claude · Trợ lý quảng cáo</b>
          <small>claude.ai + MCP Meta Ads · chỉ đọc, đề xuất để bạn duyệt</small></div></div>
        <select id="acChats" title="Cuộc trò chuyện">${c ? '' : '<option value="">— Cuộc trò chuyện mới —</option>'}${R.chats.map(x => `<option value="${esc(x.id)}" ${c && c.id === x.id ? 'selected' : ''}>${esc(x.title)} · ${esc(hhmm(x.updated_at))}</option>`).join('')}</select>
        <button class="ac-ic" data-ac="new" type="button" title="Cuộc trò chuyện mới">＋</button>
        ${c ? '<button class="ac-ic" data-ac="del-chat" type="button" title="Xoá cuộc trò chuyện">🗑</button>' : ''}
      </header>
      <div class="ac-bar">
        <select id="arAccount" title="Phạm vi tài khoản quảng cáo Claude được xem và đề xuất">
          <option value="${ALL}" ${R.account === ALL ? 'selected' : ''}>🌐 Tất cả tài khoản${R.accounts.length ? ` (${R.accounts.length})` : ''}</option>
          ${R.accounts.map(a => `<option value="${esc(a.id)}" ${a.id === R.account ? 'selected' : ''}>${esc(a.name)} · ${esc(a.id)}</option>`).join('')}
          ${R.account !== ALL && R.account && !R.accounts.some(a => a.id === R.account) ? `<option value="${esc(R.account)}" selected>${esc(R.account)}</option>` : ''}</select>
        <label class="check ac-show" title="Claude có thể hỏi quyền dùng công cụ MCP — hiện cửa sổ để bạn bấm cho phép (app không tự bấm)"><input type="checkbox" id="arShow" ${R.showBrowser ? 'checked' : ''}> Hiện cửa sổ Claude</label>
        <span class="ar-sp"></span>
        <button class="btn ghost sm" data-ar="refresh" type="button" title="Tải lại danh sách nhóm / quảng cáo từ Meta">↻ Dữ liệu QC</button>
      </div>
      ${zaloStrip()}
      <div class="ac-msgs" id="acMsgs">
        ${msgs.length ? msgs.map(msgHtml).join('') : `<div class="ac-empty"><span class="ac-avatar big">✳</span>
          <b>Hỏi Claude về quảng cáo của bạn</b><small>Dán tin nhắn giao việc từ nhóm chat, hoặc hỏi tự do. Claude tra số liệu thật qua MCP rồi đề xuất — bạn duyệt ở cột bên phải.</small>
          <div class="ac-suggest">${SUGGEST.map(s => `<button type="button" data-suggest="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`}
        ${R.sending ? `<div class="ac-msg bot"><span class="ac-avatar">✳</span><div class="ac-bubble typing"><i></i><i></i><i></i>
          <small class="${R.statusWarn ? 'warn' : ''}">${esc(R.status || 'Claude đang đọc dữ liệu quảng cáo…')}</small></div></div>` : ''}
      </div>
      <div class="ac-input">
        <textarea id="acInput" rows="3" placeholder="Nhắn cho Claude… (dán tin nhắn nhóm, hoặc hỏi: nhóm nào đang chi nhiều mà ít kết quả?) — Enter để gửi, Shift+Enter xuống dòng" ${R.sending ? 'disabled' : ''}></textarea>
        <button class="ac-send" data-ac="send" type="button" ${R.sending ? 'disabled' : ''} title="Gửi (Enter)">➤</button>
      </div>
    </section>`;
  }

  // dải "📥 Tin nhóm Zalo": trạng thái nghe + hộp tin; tick tin → gửi Claude phân tích (zalo_listener.py)
  const ZST = { new: ['Mới', 'wait'], done: ['Đã tạo yêu cầu', 'ok'], skipped: ['Bỏ qua', 'off'], error: ['Lỗi', 'bad'], sending: ['Đang gửi Claude…', 'wait'] };
  function zaloStrip() {
    const z = R.zalo;
    if (!z || !z.enabled) return '<div class="zs-bar off"><span>📥 Nhận yêu cầu tự động từ nhóm Zalo</span><span class="ar-sp"></span><button class="link" data-ac="zalo-settings" type="button">Bật trong Cài đặt →</button></div>';
    const live = z.status === 'connected';
    const box = (z.inbox || []).slice(0, 30);
    const canSend = m => ['new', 'skipped', 'error'].includes(m.status);
    return `<div class="zs-bar ${live ? 'on' : 'warn'}">
        <button class="zs-toggle" data-ac="zalo-toggle" type="button">📥 Zalo ${live ? `· đang nghe ${(z.watched || []).length} nhóm${z.last ? ` · tin gần nhất ${esc(z.last.at.slice(11, 16))}` : ''}` : `· ${esc(z.message || z.status)}`}
          ${z.new ? `<b class="ar-badge">${z.new}</b>` : ''}<i>${R.zaloOpen ? '▴' : '▾'}</i></button>
        <span class="ar-sp"></span>${R.zaloOpen && R.zaloSel.size ? `<button class="btn primary sm" data-ac="zalo-send" type="button" ${R.zaloSending ? 'disabled' : ''}>✳ Gửi ${R.zaloSel.size} tin cho Claude</button>` : ''}
      </div>
      ${R.zaloOpen ? `<div class="zs-list">${box.length ? box.map(m => {
          const [lab, cls] = ZST[m.status] || [m.status, 'off'];
          return `<label class="zs-msg ${R.zaloSel.has(m.id) ? 'on' : ''}">${canSend(m) ? `<input type="checkbox" data-zm="${esc(m.id)}" ${R.zaloSel.has(m.id) ? 'checked' : ''}>` : '<i class="zs-dot"></i>'}
            <span class="zs-body"><span class="zs-meta"><b>${esc(m.from || '?')}</b> · ${esc(m.group_name)} · ${esc((m.at || '').slice(11, 16))}<em class="ar-eff ${cls}">${esc(lab)}</em></span>
            <span class="zs-text">${esc(m.text)}</span>${m.note ? `<small class="muted">${esc(m.note)}</small>` : ''}</span></label>`;
        }).join('') : '<small class="muted zs-empty">Chưa có tin nào từ các nhóm đang theo dõi.</small>'}</div>` : ''}`;
  }

  function msgHtml(m, i) {
    if (m.role === 'user') return `<div class="ac-msg me"><div class="ac-bubble">${esc(m.text)}</div><small class="ac-at">${esc(hhmm(m.at))}</small></div>`;
    if (m.error) {
      return `<div class="ac-msg bot"><span class="ac-avatar">✳</span><div class="ac-bubble err">⚠ ${esc(m.error)}
        <button class="link" data-ac="retry" data-i="${i}" type="button">↻ Gửi lại</button></div></div>`;
    }
    const reqs = (m.requests || []).map(id => R.list.find(r => r.id === id)).filter(Boolean);
    return `<div class="ac-msg bot"><span class="ac-avatar">✳</span><div class="ac-col">
      <div class="ac-bubble">${md(m.text)}${m.json ? codeCard('json', m.json) : ''}</div>
      ${reqs.length ? `<div class="ac-props"><small>📋 ${reqs.length} đề xuất chờ duyệt</small>${reqs.map(r => `<button type="button" class="ac-prop ${ST_CLASS[r.status] || ''}" data-goto="${esc(r.id)}">
        <span>${esc((r.parsed.group || r.raw || 'Yêu cầu').slice(0, 60))}</span><em>${esc(R.meta.statuses[r.status] || r.status)}</em></button>`).join('')}</div>` : ''}
      <small class="ac-at">${esc(hhmm(m.at))}</small></div></div>`;
  }

  function sideHtml() {
    const q = R.q.trim().toLowerCase();
    const list = R.list.filter(r => inFilter(r, R.filter) && (!q || `${r.raw} ${JSON.stringify(r.parsed)} ${r.analysis || ''}`.toLowerCase().includes(q)));
    const counts = Object.fromEntries(FILTERS.map(([k]) => [k, R.list.filter(r => inFilter(r, k)).length]));
    return `<section class="ac-side">
      <div class="ar-bar">
        <div class="ar-filters">${FILTERS.map(([k, l]) => `<button class="ar-chip ${R.filter === k ? 'on' : ''}" data-arf="${k}" type="button">${l} <b>${counts[k]}</b></button>`).join('')}</div>
        <input id="arSearch" type="search" placeholder="🔍 Tìm…" value="${esc(R.q)}">
      </div>
      <div class="ar-list">${list.length ? list.map(card).join('') : `<div class="empty">${R.list.length ? 'Không có yêu cầu nào ở mục này.'
        : 'Chưa có đề xuất — trò chuyện với Claude bên trái, các việc Claude đề xuất sẽ hiện ở đây để bạn duyệt.'}</div>`}</div>
    </section>`;
  }

  function card(r) {
    const p = r.parsed || {};
    const live = !['done', 'rejected'].includes(r.status);
    const ops = r.ops || [];
    const pending = ops.filter(o => o.state !== 'done');
    const checked = pending.filter(o => o.checked).length;
    const spend = pending.some(o => o.checked && o.spend);
    const target = (r.candidates || []).find(c => c.id === r.target);
    const acts = (p.actions || []).map(a => `<span class="ar-act ${a}">${esc(R.meta.actions[a] || a)}</span>`).join('');
    return `<article class="card ar-card ${ST_CLASS[r.status] || ''}" data-rid="${esc(r.id)}">
      <header class="ar-head">
        <div class="ar-who"><b>${esc(p.sender || (r.source === 'claude' ? 'Claude đề xuất' : 'Không rõ người gửi'))}</b>${p.for_whom ? `<small>cho ${esc(p.for_whom)}</small>` : ''}</div>
        <small class="muted">${esc(hhmm(r.created_at))}</small>
        ${r.origin && r.origin.zalo_group ? `<span class="ar-zalo" title="Từ tin nhóm Zalo">📥 ${esc(r.origin.zalo_group)}</span>` : ''}
        ${r.account_id ? `<span class="ar-acc" title="${esc(r.account_id)}">🏷 ${esc(accName(r.account_id))}</span>` : ''}
        ${r.source === 'claude' ? '<span class="ar-src claude" title="Claude + MCP Ads phân tích">✳ Claude</span>' : ''}
        <span class="ar-st ${ST_CLASS[r.status] || ''}">${esc(R.meta.statuses[r.status] || r.status)}</span>
        <button class="ar-ic" data-ar="del" type="button" title="Xoá khỏi danh sách">🗑</button>
      </header>
      <div class="ar-grid">
        <div class="ar-col">
          ${r.raw ? `<div class="ar-raw ${R.rawOpen.has(r.id) ? 'open' : ''}" data-ar="raw" title="Bấm để xem đủ">${esc(r.raw)}</div>` : ''}
          ${r.analysis ? `<div class="ar-analysis"><small>✳ Claude phân tích</small><p>${esc(r.analysis)}</p></div>` : ''}
          ${R.editing === r.id ? editForm(r) : `<div class="ar-facts">
            ${p.page ? `<div><span>Page</span><b>${esc(p.page)}</b>${r.page_match ? `<em class="ok">✓ ${esc(r.page_match.name)}</em>` : '<em class="bad">✕ chưa khớp</em>'}</div>` : ''}
            ${p.group ? `<div><span>Nhóm</span><b>${esc(p.group)}</b></div>` : ''}
            ${(p.codes || []).length ? `<div><span>Mã SP</span><b>${p.codes.map(c => `<code>${esc(c)}</code>`).join(' ')}</b></div>` : ''}
            <div><span>Việc</span><b class="ar-acts">${acts}</b></div>
            ${(p.links || []).map(u => `<div><span>Link</span><b><a href="${esc(u)}" class="ar-link" title="Mở link trong cửa sổ nhỏ">${esc(u)}</a></b></div>`).join('')}
            ${live ? '<button class="link ar-editbtn" data-ar="edit" type="button">✎ Sửa phân tích</button>' : ''}</div>`}
          ${(r.candidates || []).length ? `<label class="ar-field"><span>Nhóm quảng cáo khớp ${target ? tag(target.effective_status) : ''}</span>
            <select data-ar="target" ${live ? '' : 'disabled'}>${r.candidates.map(c => `<option value="${esc(c.id)}" ${c.id === r.target ? 'selected' : ''}>${esc(c.name)} · ${esc(EFF(c.effective_status)[0])} · ${c.ads} QC</option>`).join('')}</select></label>` : ''}
          ${(r.posts || []).map(ps => `<div class="ar-post"><small class="muted">Bài trong link ${ps.post_id ? `· <code>${esc(ps.post_id)}</code>` : '· chưa xác định'}</small>
            ${ps.ads.length ? ps.ads.map(a => `<div class="ar-adrow">${tag(a.status)}<span>${esc(a.name)}</span></div>`).join('') : '<small class="muted">Chưa có quảng cáo nào dùng bài này</small>'}</div>`).join('')}
          <div class="ar-ops"><small class="ar-opshead">Thao tác đề xuất</small>${ops.length ? ops.map(o => opRow(o, live)).join('') : '<small class="muted">Chưa có thao tác đề xuất.</small>'}</div>
          ${(r.issues || []).length ? `<ul class="ar-issues">${r.issues.map(i => `<li>⚠ ${esc(i)}</li>`).join('')}</ul>` : ''}
          ${r.reply ? `<div class="ar-reply"><small class="muted">Trả lời nhóm</small><p>${esc(r.reply)}</p>
            <button class="btn ghost sm" data-ar="copy" type="button">⧉ Sao chép</button></div>` : ''}
        </div>
      </div>
      ${live ? `<footer class="ar-foot">
        ${spend ? '<span class="ar-spend">💸 Có thao tác tiêu tiền</span>' : ''}
        <span class="ar-sp"></span>
        <button class="btn ghost sm" data-ar="reject" type="button">✕ Từ chối</button>
        <button class="btn primary sm" data-ar="run" type="button" ${checked ? '' : 'disabled'}>✓ Duyệt & thực hiện (${checked})</button></footer>` : ''}
    </article>`;
  }

  function opRow(o, live) {
    const done = o.state === 'done', bad = o.state === 'error';
    return `<div class="ar-op ${done ? 'done' : bad ? 'bad' : ''}">
      ${done ? '<i class="ar-ok">✓</i>' : `<input type="checkbox" data-op="${esc(o.id)}" ${o.checked ? 'checked' : ''} ${live ? '' : 'disabled'} aria-label="Chọn thao tác">`}
      <span>${esc(o.label)}${o.spend ? ' <em class="ar-money" title="Tiêu tiền thật">💸</em>' : ''}${o.unverified ? ' <em class="ar-unv" title="id không có trong tài khoản">⚠ chưa kiểm chứng</em>' : ''}
        ${o.result ? `<small class="${bad ? 'warn-text' : 'muted'}">${esc(o.result)}</small>` : ''}</span>
      ${o.type === 'create_ad' && !done && live ? `<label class="ar-run" title="Bật = quảng cáo chạy ngay (tiêu tiền). Tắt = tạo ở trạng thái tạm dừng"><input type="checkbox" data-run="${esc(o.id)}" ${o.run ? 'checked' : ''}> chạy ngay</label>` : ''}
    </div>`;
  }

  function editForm(r) {
    const p = r.parsed;
    return `<div class="ar-edit">
      <label class="ar-field"><span>Page</span><input data-e="page" value="${esc(p.page || '')}"></label>
      <label class="ar-field"><span>Tên nhóm</span><input data-e="group" value="${esc(p.group || '')}"></label>
      <label class="ar-field"><span>Mã SP (cách nhau dấu phẩy)</span><input data-e="codes" value="${esc((p.codes || []).join(', '))}"></label>
      <label class="ar-field"><span>Link bài</span><textarea data-e="links" rows="2">${esc((p.links || []).join('\n'))}</textarea></label>
      <div class="ar-field"><span>Việc cần làm</span><div class="ar-actpick">${Object.entries(R.meta.actions).map(([k, l]) => `<label><input type="checkbox" data-ea="${k}" ${(p.actions || []).includes(k) ? 'checked' : ''}> ${esc(l)}</label>`).join('')}</div></div>
      <div class="ar-editfoot"><button class="btn ghost sm" data-ar="cancel-edit" type="button">Huỷ</button>
        <button class="btn primary sm" data-ar="save-edit" type="button">↻ Đối chiếu lại</button></div></div>`;
  }

  // ------------------------------------------------------------ chat
  async function send(text) {
    text = String(text || '').trim();
    if (!text || R.sending) return;
    R.account = ($('#arAccount') || {}).value || R.account;
    if (!R.account) return toast('Chưa có tài khoản quảng cáo — kiểm tra quyền ads_read ở Cài đặt → Facebook', 'warn');
    if (!R.chat) {
      const res = await api('adchat_new', R.account);
      if (!res.ok) return toast(res.error, 'error');
      R.chat = res.chat;
    }
    const d = new Date(), z = n => String(n).padStart(2, '0');  // giờ máy (giống backend), không phải UTC
    const at = `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
    R.chat.messages = [...(R.chat.messages || []), { role: 'user', text, at }];
    R.sending = true; R.status = ''; R.statusWarn = false;
    $('#acInput') && ($('#acInput').value = '');
    render();
    const res = await api('adchat_send', R.chat.id, text, R.account, R.showBrowser);
    R.sending = false;
    await Promise.all([load(), loadChats()]);
    await openChat(R.chat.id, false);
    render();
    if (!res.ok) return toast(res.error, 'error');
    const n = res.result.requests.length;
    if (n) toast(`Claude đề xuất ${n} việc — xem và duyệt ở cột bên phải`, 'ok');
  }

  function status(data) {  // sự kiện adchat_status: Claude đang trả lời / đang chờ quyền công cụ
    if (!R.sending || !data) return;
    R.status = data.text; R.statusWarn = data.level === 'warn';
    const el = $('.ac-bubble.typing small');
    if (el) { el.textContent = R.status; el.classList.toggle('warn', R.statusWarn); }
  }

  // ------------------------------------------------------------ duyệt / thực hiện
  const findReq = el => { const c = el.closest('[data-rid]'); return c ? R.list.find(r => r.id === c.dataset.rid) : null; };
  const replace = req => { R.list = R.list.map(r => (r.id === req.id ? req : r)); };

  async function saveOps(req, extra = {}) {
    const box = $(`.ar-card[data-rid="${CSS.escape(req.id)}"]`);
    const checked = [...box.querySelectorAll('[data-op]:checked')].map(i => i.dataset.op);
    const run = [...box.querySelectorAll('[data-run]:checked')].map(i => i.dataset.run);
    const res = await api('adreq_set_ops', req.id, { checked, run, ...extra });
    if (!res.ok) return toast(res.error, 'error');
    replace(res.request); render();
  }

  async function execute(req) {
    const todo = req.ops.filter(o => o.checked && o.state !== 'done');
    const spend = todo.filter(o => o.spend);
    if (spend.length) {
      if (!await confirmSpend(req, todo)) return;
    } else if (!confirm(`Thực hiện ${todo.length} thao tác trên Meta?\n\n${todo.map(o => `• ${o.label}`).join('\n')}`)) return;
    const btn = $(`.ar-card[data-rid="${CSS.escape(req.id)}"] [data-ar="run"]`);
    if (btn) { btn.disabled = true; btn.textContent = 'Đang thực hiện…'; }
    const res = await api('adreq_execute', req.id, true, spend.length > 0);
    if (!res.ok) { toast(res.error, 'error'); return render(); }
    replace(res.request); await load(); render();
    const bad = res.request.ops.filter(o => o.state === 'error').length;
    toast(bad ? `Có ${bad} thao tác lỗi — xem chi tiết trong thẻ` : 'Đã thực hiện xong', bad ? 'warn' : 'ok');
  }

  function confirmSpend(req, todo) {
    return new Promise(resolve => {
      openModal('XÁC NHẬN TIÊU TIỀN', 'Bật / chạy quảng cáo', `<div class="ar-confirm">
        <p>Các thao tác sau sẽ <b>bật hoặc chạy quảng cáo — tiêu tiền thật</b> theo ngân sách đang đặt trên Meta:</p>
        <ul>${todo.map(o => `<li class="${o.spend ? 'spend' : ''}">${o.spend ? '💸 ' : ''}${esc(o.label)}</li>`).join('')}</ul>
        <label class="check"><input type="checkbox" id="arAgree"> <span>Tôi đồng ý bật / chạy quảng cáo cho yêu cầu này</span></label>
        <div class="modal-foot"><button class="btn ghost" id="arNo" type="button">Huỷ</button><button class="btn primary" id="arYes" type="button">✓ Thực hiện</button></div></div>`, true);
      $('#arNo').onclick = () => { closeModal(); resolve(false); };
      $('#arYes').onclick = () => {
        if (!$('#arAgree').checked) return toast('Tick ô đồng ý trước', 'warn');
        closeModal(); resolve(true);
      };
    });
  }

  function bind() {
    const box = $('#adreqBody');
    box.addEventListener('click', async e => {
      const cb = e.target.closest('[data-code]');  // thẻ code: sao chép / thu gọn
      if (cb) {
        const card = cb.closest('.ac-code');
        if (cb.dataset.code === 'fold') { const f = card.classList.toggle('folded'); cb.textContent = f ? 'Mở rộng ▾' : 'Thu gọn ▴'; return; }
        return navigator.clipboard.writeText(card.querySelector('pre').innerText).then(() => {
          cb.textContent = '✓ Đã chép'; setTimeout(() => { cb.textContent = '⧉ Sao chép'; }, 1500);
        }).catch(() => toast('Không chép được — bôi đen nội dung rồi Ctrl+C', 'warn'));
      }
      const t = e.target.closest('[data-ar], [data-arf], [data-ac], [data-suggest], [data-goto], a.ar-link');
      if (!t) return;
      if (t.matches('a.ar-link')) { e.preventDefault(); return api('open_url', t.getAttribute('href')); }
      if (t.tagName === 'SELECT') return;  // đổi lựa chọn xử lý ở sự kiện change
      if (t.dataset.suggest) return send(t.dataset.suggest);
      if (t.dataset.goto) { R.filter = 'all'; R.flash = t.dataset.goto; return render(); }
      if (t.dataset.arf) { R.filter = t.dataset.arf; return render(); }
      const ac = t.dataset.ac;
      if (ac === 'send') return send($('#acInput').value);
      if (ac === 'zalo-settings') return openSettings('zalo');
      if (ac === 'zalo-toggle') { R.zaloOpen = !R.zaloOpen; return render(); }
      if (ac === 'zalo-send') {
        R.zaloSending = true; render();
        toast(`Đang gửi ${R.zaloSel.size} tin Zalo cho Claude…`, 'ok');
        const res = await api('zalo_send_claude', [...R.zaloSel]);
        R.zaloSending = false; R.zaloSel.clear();
        if (res.ok) R.zalo = res.state;
        await Promise.all([load(), loadChats()]);
        if (R.chat) await openChat(R.chat.id, false);
        render();
        return toast(res.ok ? `Claude đề xuất ${(res.result.requests || []).length} việc — xem cột bên phải` : res.error, res.ok ? 'ok' : 'error');
      }
      if (ac === 'new') { R.chat = null; return render(); }
      if (ac === 'del-chat') {
        if (!confirm('Xoá cuộc trò chuyện này? (Các thẻ đề xuất vẫn giữ)')) return;
        await api('adchat_delete', R.chat.id); R.chat = null; await loadChats(); return render();
      }
      if (ac === 'retry') {
        const m = R.chat.messages.slice(0, +t.dataset.i).reverse().find(x => x.role === 'user');
        if (m) return send(m.text);
        return;
      }
      const act = t.dataset.ar, req = findReq(t);
      if (act === 'refresh') {
        R.account = $('#arAccount').value;
        const res = await api('adreq_refresh', R.account);
        return toast(res.ok ? `Đã tải lại: ${res.index.adsets} nhóm, ${res.index.ads} quảng cáo` : res.error, res.ok ? 'ok' : 'error');
      }
      if (!req) return;
      if (act === 'raw') { if (R.rawOpen.has(req.id)) R.rawOpen.delete(req.id); else R.rawOpen.add(req.id); return render(); }
      if (act === 'edit') { R.editing = req.id; return render(); }
      if (act === 'cancel-edit') { R.editing = null; return render(); }
      if (act === 'save-edit') {
        const cardEl = t.closest('[data-rid]');
        const data = Object.fromEntries([...cardEl.querySelectorAll('[data-e]')].map(i => [i.dataset.e, i.value]));
        data.actions = [...cardEl.querySelectorAll('[data-ea]:checked')].map(i => i.dataset.ea);
        t.disabled = true;
        const res = await api('adreq_update', req.id, data, R.account || req.account_id);
        if (!res.ok) { t.disabled = false; return toast(res.error, 'error'); }
        R.editing = null; replace(res.request); return render();
      }
      if (act === 'run') return execute(req);
      if (act === 'reject') {
        const res = await api('adreq_reject', req.id);
        if (res.ok) { replace(res.request); await load(); render(); }
        return;
      }
      if (act === 'del') {
        if (!confirm('Xoá đề xuất này khỏi danh sách? (Không thay đổi gì trên Meta)')) return;
        await api('adreq_delete', [req.id]); await load(); return render();
      }
      if (act === 'copy') navigator.clipboard.writeText(req.reply).then(() => toast('Đã sao chép — dán vào nhóm chat', 'ok'));
    });
    box.addEventListener('change', async e => {
      const t = e.target;
      if (t.id === 'acChats') { if (t.value) await openChat(t.value); return; }
      if (t.id === 'arShow') { R.showBrowser = t.checked; return; }
      if (t.dataset.zm) { if (t.checked) R.zaloSel.add(t.dataset.zm); else R.zaloSel.delete(t.dataset.zm); return render(); }
      if (t.id === 'arAccount') { R.account = t.value; return; }
      const req = findReq(t);
      if (!req) return;
      if (t.dataset.op || t.dataset.run) return saveOps(req);
      if (t.dataset.ar === 'target') return saveOps(req, { target: t.value });
    });
    box.addEventListener('keydown', e => {
      if (e.target.id === 'acInput' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(e.target.value); }
    });
    box.addEventListener('input', e => {
      if (e.target.id !== 'arSearch') return;
      R.q = e.target.value;
      const pos = e.target.selectionStart;
      render();
      const s = $('#arSearch'); s.focus(); s.setSelectionRange(pos, pos);
    });
    $('#adTabs').addEventListener('click', e => { const b = e.target.closest('[data-adtab]'); if (b) applyTab(b.dataset.adtab); });
  }

  // gắn vào màn Trợ lý quảng cáo: mỗi lần mở màn → mở lại đúng tab lần trước
  const orig = window.AdBotPage && window.AdBotPage.show;
  let bound = false;
  if (orig) {
    window.AdBotPage.show = async (...a) => {
      if (!bound) { bound = true; bind(); }
      const r = await orig(...a);
      applyTab(tabNow());
      return r;
    };
  }
  function zalo(st) {  // sự kiện zalo_status
    R.zalo = st;
    if (!$('#adreqBody') || $('#adreqBody').classList.contains('hidden') || R.sending) return;
    const scroll = $('#acMsgs') ? $('#acMsgs').scrollTop : 0;
    render();
    if ($('#acMsgs')) $('#acMsgs').scrollTop = scroll;
  }
  async function reload() {  // sự kiện adreq_changed: có yêu cầu mới (VD từ tin Zalo)
    await load();
    if (R.meta && !R.sending && $('#adreqBody') && !$('#adreqBody').classList.contains('hidden')) render();
  }

  window.AdReqPage = { show, applyTab, status, zalo, reload };
})();
