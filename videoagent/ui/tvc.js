/* 🎬 Trợ lý TVC — Claude Code điều khiển mọi bước theo skill tvc-livestream-capcut (như chạy trong Claude Code ở D:\CapCut);
   app chỉ hiển thị + tiếp nhận: khung chat (tin Claude, thẻ hoạt động gom các công cụ, câu hỏi lựa chọn → thẻ bấm, hộp xin
   quyền), đính ảnh người mẫu / sản phẩm (chép vào <gốc>\_input\…), thanh tiến độ 6 chặng + bảng dự án chia tab (chỉ đọc).
   Khung dựng 1 lần; mỗi phần (đầu trang, tiến độ, chat, thanh soạn, bảng dự án) vẽ lại riêng → video không tải lại, không mất
   chữ đang gõ. Helper của app.js: $, api, esc, toast, state. Mở khoá quản trị: window.requireAdmin. */
(() => {
  'use strict';

  const T = { st: null, chats: [], env: null, cfg: null, projects: [], proj: null, projName: '', browse: false, chatId: null, showCfg: false,
    af: { show: false, meta: null, web: null, inputs: { san_pham_ten: '', link: '', shop: '', yeu_cau: '', cong_cu: 'grok', anh_nguoi_mau: [], anh_san_pham: [], anh_tu_web: false },
      cfg: { variants: 2, threshold: 7, retries: 2, max_cost: 5, fb_page: '', fb_autopost: false } },
    showHist: (() => { try { return localStorage.getItem('tvcHistOpen') === '1'; } catch { return false; } })(), showHidden: false, ptab: 'overview', picks: {}, others: {}, pub: {}, open: new Set(), openTool: new Set(), attach: [] };
  const root = () => $('#tvcBody');
  const q = sel => root() && root().querySelector(sel);
  const STEPS = [['y_tuong', 'Thông tin SP'], ['script', 'Kịch bản'], ['images_done', 'Ảnh cảnh'], ['clips_done', 'Clip nói'],
    ['draft', 'Draft CapCut'], ['preview', 'Xem trước'], ['fb', 'Bài Facebook'], ['ads', 'Quảng cáo']];
  const TABS = [['overview', 'Tổng quan'], ['script', 'Kịch bản'], ['media', 'Ảnh & Clip'], ['fb', '📣 Bài FB'], ['ads', '📈 Quảng cáo'], ['eval', '🏆 Đánh giá'], ['idea', 'Ý tưởng']];
  const ADS_ST = { idea: ['draft', 'Có gợi ý'], pending: ['wait', 'Chờ duyệt'], draft: ['draft', 'Nháp'], paused: ['ok', 'Đã tạo · tạm dừng'],
    scheduled: ['ok', 'Đã lên lịch'], running: ['ok', 'Đang chạy'], error: ['err', 'Lỗi tạo'], cancelled: ['', 'Đã huỷ'] };
  const ADS_DONE = ['paused', 'scheduled', 'running'];
  const FB_ST = { draft: ['draft', 'Bản nháp'], pending: ['wait', 'Chờ duyệt'], posted: ['ok', 'Đã đăng'], error: ['err', 'Lỗi đăng'] };
  const FB_TOOLS = { fb_pages: 'Xem Fanpage', fb_create_post: 'Lưu bài chờ duyệt', fb_publish: 'Đăng bài',
    fb_ad_accounts: 'Xem tài khoản quảng cáo', fb_ad_request: 'Tạo yêu cầu quảng cáo' };
  const CHROME = { screenshot: 'Chụp màn hình', left_click: 'Bấm chuột', type: 'Gõ chữ', key: 'Nhấn phím', scroll: 'Cuộn trang',
    zoom: 'Phóng to xem', wait: 'Chờ trang', navigate: 'Mở trang', find: 'Tìm trên trang', file_upload: 'Tải ảnh lên',
    javascript_tool: 'Đọc trang', tabs_create_mcp: 'Mở tab mới', tabs_context_mcp: 'Xem các tab', tabs_close_mcp: 'Đóng tab',
    browser_batch: 'Chuỗi thao tác', read_page: 'Đọc trang', get_page_text: 'Đọc chữ trên trang' };
  const TOOLS = { Bash: ['⌨', 'Chạy lệnh'], PowerShell: ['⌨', 'Chạy lệnh'], Read: ['📄', 'Đọc file'], Write: ['✍', 'Ghi file'],
    Edit: ['✍', 'Sửa file'], MultiEdit: ['✍', 'Sửa file'], WebFetch: ['🌐', 'Đọc trang web'], WebSearch: ['🔎', 'Tìm trên web'],
    Skill: ['🧩', 'Nạp skill'], Glob: ['📁', 'Tìm file'], Grep: ['🔎', 'Tìm trong file'], TodoWrite: ['☑', 'Cập nhật việc cần làm'],
    Task: ['🤖', 'Tác tử phụ'], Agent: ['🤖', 'Tác tử phụ'], ToolSearch: ['🧰', 'Nạp công cụ'] };

  async function call(name, ...args) {
    try {
      const res = await api(name, ...args);
      if (res && res.ok === false && res.locked) {
        return (await window.requireAdmin('dùng Trợ lý TVC')) ? call(name, ...args) : null;
      }
      if (!res || res.ok === false) { toast((res && res.error) || 'Lỗi', 'error'); return null; }
      return res;
    } catch (err) { toast(String(err), 'error'); return null; }
  }

  async function show() {
    const [a, b, c, d] = await Promise.all([call('tvc_chat_state'), call('tvc_chats'), call('tvc_env'), call('tvc_list')]);
    if (a) T.st = a.state;
    if (b) T.chats = b.chats;
    if (c) T.env = c.env;
    if (d) T.projects = d.projects;
    T.chatId = null;  // vào lại màn → gắn bảng kết quả theo hội thoại đang mở
    syncChat(false);
    render();
    loadProject();
  }

  /* ---------------------------------------------------------------- kết quả theo từng hội thoại */
  const curChat = () => (T.st && T.st.chat) || null;
  function chatProjects() {  // dự án hội thoại đã làm (mới nhất trước)
    const c = curChat();
    if (!c) return [];
    const list = (c.projects || []).filter(Boolean);
    if (c.project && !list.includes(c.project)) list.unshift(c.project);
    return list;
  }
  const tabKey = () => `tvcTab:${(curChat() || {}).id || 'new'}`;
  function saveTab() { try { localStorage.setItem(tabKey(), T.ptab); } catch { /* chỉ trong phiên */ } }
  function syncChat(load = true) {
    // hội thoại đổi (mới / mở lại / xoá / gửi tin đầu) → bảng kết quả về đúng dự án của hội thoại, tab đã xem lần trước
    const c = curChat();
    const id = c ? c.id : '';
    if (id === T.chatId) return;
    T.chatId = id;
    T.browse = false;
    T.projName = (c && c.project) || '';
    let tab = 'overview';
    try { tab = localStorage.getItem(tabKey()) || 'overview'; } catch { /* mặc định */ }
    T.ptab = TABS.some(([k]) => k === tab) ? tab : 'overview';
    T.proj = null;
    if (load) loadProject();
  }

  /* ---------------------------------------------------------------- văn bản Claude (markdown gọn) */
  function md(text) {
    let h = esc(text || '');
    h = h.replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    h = h.replace(/^#{1,4} (.+)$/gm, '<span class="tvcc-h">$1</span>');
    h = h.replace(/^\s*[-*] (.+)$/gm, '<span class="tvcc-li">$1</span>');
    h = h.replace(/((?:^\|.*\|[ \t]*(?:\n|$)){2,})/gm, block => {  // bảng markdown → bảng HTML
      const rows = block.trim().split('\n').filter(r => !/^\|\s*:?-{2,}/.test(r));
      return `<table>${rows.map((r, i) => `<tr>${r.replace(/^\||\|\s*$/g, '').split('|').map(c => (i ? `<td>${c.trim()}</td>` : `<th>${c.trim()}</th>`)).join('')}</tr>`).join('')}</table>`;
    });
    return h.replace(/\n/g, '<br>').replace(/<br>(<\/?(?:pre|table|tr|span class="tvcc-(?:h|li)"))/g, '$1').replace(/(<\/span>)<br>/g, '$1');
  }

  function toolLabel(m) {
    const name = String(m.tool || '');
    if (name.startsWith('mcp__claude-in-chrome__')) {
      const short = name.slice('mcp__claude-in-chrome__'.length);
      let act = '';
      try { act = (JSON.parse(m.text || '{}') || {}).action || ''; } catch { /* mô tả không phải JSON */ }
      return ['🌐', `Chrome · ${CHROME[act] || CHROME[short] || short}`];
    }
    if (name.startsWith('mcp__vibe_fb__')) return ['📣', `Facebook · ${FB_TOOLS[name.slice(14)] || name.slice(14)}`];
    if (/facebookads/i.test(name.replace(/_/g, ''))) return ['📈', `Ads · ${name.split('__').pop().replace(/^ads_/, '').replace(/_/g, ' ')}`];
    if (/nnv/i.test(name)) return ['🗄', `Tra NNV · ${name.split('__').pop()}`];
    if (name.startsWith('mcp__')) return ['🔌', name.replace(/^mcp__(claude_ai_)?/, '').replace(/__/g, ' · ')];
    return TOOLS[name] || ['🔧', name];
  }

  /* ---------------------------------------------------------------- tin nhắn */
  function pubVal(m) {
    const c = m.card || {};
    T.pub[m.rid] = T.pub[m.rid] || { caption: c.caption || '', kind: c.kind || 'reel', page_id: c.page_id || ((c.pages || [])[0] || {}).id || '' };
    return T.pub[m.rid];
  }

  function publishHtml(m) {
    const c = m.card || {};
    const done = !!m.answered;
    const v = pubVal(m);
    const page = (c.pages || []).find(p => p.id === v.page_id) || {};
    const media = v.kind === 'poster' ? (c.poster ? `<img src="${esc(c.poster)}" data-zoom="${esc(c.poster)}" alt="">` : '')
      : (c.video ? `<video src="${esc(c.video)}" controls preload="metadata"></video>` : '');
    const res = done ? `<div class="tvcc-answered ${/^✗/.test(m.answered) ? 'no' : /^⏳|^🕘/.test(m.answered) ? 'wait' : ''}">${esc(m.answered)}${m.url ? ` · <a href="${esc(m.url)}">Mở bài trên Facebook ↗</a>` : ''}</div>` : '';
    return `<div class="tvcc-ask pub ${done ? 'done' : ''}"><div class="tvcc-ask-h"><span class="tvcc-ask-ic">📣</span><div><b>${esc(m.text || 'Xác nhận đăng bài')}</b>
        <small>Dự án ${esc(c.project || '')} · chỉ đăng khi bạn bấm “Đăng ngay”</small></div></div>
      <div class="tvcc-pub">
        <div class="tvcc-fbpost"><div class="tvcc-fbpost-h"><span class="tvcc-fbav">${esc((page.name || 'F').slice(0, 1))}</span><div><b>${esc(page.name || 'Chọn Fanpage')}</b><small>Vừa xong · 🌐</small></div></div>
          ${done ? `<div class="tvcc-fbpost-t">${md(v.caption)}</div>` : `<textarea class="tvcc-other tvcc-pub-cap" data-pub-cap="${esc(m.rid)}" rows="7">${esc(v.caption)}</textarea>`}
          <div class="tvcc-fbpost-m ${v.kind === 'poster' ? 'img' : ''}">${media || '<span class="muted">Không có file</span>'}</div></div>
        ${done ? '' : `<div class="tvcc-pub-side">
          <label>Fanpage<select data-pub-page="${esc(m.rid)}">${(c.pages || []).map(p => `<option value="${esc(p.id)}" ${p.id === v.page_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
          <div class="tvcc-pub-kinds"><span>Kiểu đăng</span>${(c.kinds || []).map(k => {
            const off = (k.value === 'poster' && !c.poster) || (k.value !== 'poster' && !c.video);
            return `<button type="button" class="tvcc-opt ${v.kind === k.value ? 'on' : ''}" ${off ? 'disabled' : ''} data-pub-kind="${esc(m.rid)}" data-k="${esc(k.value)}"><b>${esc(k.label)}</b></button>`;
          }).join('')}</div>
          ${c.poster && v.kind !== 'poster' ? `<div class="tvcc-pub-keep"><img src="${esc(c.poster)}" data-zoom="${esc(c.poster)}" alt=""><small class="muted">Poster lưu sẵn trong bài (Quản lý bài đăng) để chạy quảng cáo / đăng sau</small></div>` : ''}
        </div>`}
      </div>
      ${done ? res : `<div class="tvcc-ask-acts"><small class="muted">Sửa nội dung ngay trong khung bài viết</small><span class="tvcc-sp"></span>
        <button class="btn ghost sm" type="button" data-pub-go="${esc(m.rid)}" data-go="0" title="Không đăng — bài nằm ở Chờ duyệt trong Quản lý bài đăng">🕘 Để sau</button>
        <button class="btn primary sm" type="button" data-pub-go="${esc(m.rid)}" data-go="1">📣 Đăng ngay</button></div>`}</div>`;
  }

  const money = (n, cur) => (n === '' || n == null ? '—' : `${Number(n).toLocaleString('vi-VN')}${cur ? ` ${cur}` : ''}`);

  function adSummaryHtml(s) {
    s = s || {};
    const kv = [['Tài khoản', s.account], ['Mục tiêu', s.objective], ['Ngân sách / ngày', money(s.daily_budget, s.currency)],
      ['Thời gian', `${s.days || '—'} ngày${s.start_at ? ` · từ ${s.start_at.replace('T', ' ')}` : ''}`], ['Khu vực', s.countries],
      ['Độ tuổi · giới tính', `${s.ages || ''} · ${s.gender || ''}`], ['Sở thích', (s.interests || []).join(', ') || 'Không giới hạn']];
    return `<div class="tvcc-adkv">${kv.map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v || '—')}</b></div>`).join('')}</div>
      ${s.strategy ? `<div class="tvcc-adtxt"><span>Chiến lược</span>${md(s.strategy)}</div>` : ''}
      ${s.kpi ? `<div class="tvcc-adtxt"><span>KPI ước lượng</span>${md(s.kpi)}</div>` : ''}`;
  }

  function adCardHtml(m) {
    const ads = (T.proj && T.proj.name === m.project && T.proj.ads) || null;
    const live = ads && ads.plan_id === m.plan_id ? ads.status : 'pending';
    const [cls, label] = ADS_ST[live] || ['', live];
    return `<div class="tvcc-ask adplan ${live !== 'pending' ? 'done' : ''}"><div class="tvcc-ask-h"><span class="tvcc-ask-ic">📈</span><div><b>${esc(m.text || 'Yêu cầu quảng cáo')}</b>
        <small>Dự án ${esc(m.project || '')} · ${esc((m.summary || {}).name || '')} · chưa tạo gì trên Facebook cho tới khi bạn duyệt</small></div>
        <span class="tvcc-sp"></span><span class="tvcc-fbbadge ${cls}">${esc(label)}</span></div>
      ${adSummaryHtml(m.summary)}
      <div class="tvcc-ask-acts"><small class="muted">Duyệt ở Trợ lý quảng cáo: tạo TẠM DỪNG (mặc định) / lên lịch / chạy ngay</small><span class="tvcc-sp"></span>
        ${live === 'pending' ? `<button class="btn ghost sm tvcc-deny" type="button" data-ad-cancel="${esc(m.project)}">✗ Huỷ yêu cầu</button>` : ''}
        ${live !== 'cancelled' ? `<button class="btn primary sm" type="button" data-ad-open="${esc(m.plan_id)}">📈 Mở để duyệt</button>` : ''}</div></div>`;
  }

  function askHtml(m) {
    const done = !!m.answered;
    if (m.kind === 'publish') return publishHtml(m);
    if (m.kind === 'permission') {
      return `<div class="tvcc-ask perm ${done ? 'done' : ''}"><div class="tvcc-ask-h"><span class="tvcc-ask-ic">🔐</span><div><b>${esc(m.text)}</b>
          <small>${esc(toolLabel(m)[1])} — thao tác ngoài phạm vi tự cho phép, cần bạn quyết định</small></div></div>
        ${m.detail ? `<pre>${esc(m.detail)}</pre>` : ''}${m.reason ? `<small class="muted">${esc(m.reason)}</small>` : ''}
        ${done ? `<div class="tvcc-answered ${/^✗/.test(m.answered) ? 'no' : ''}">${esc(m.answered)}</div>` : `<div class="tvcc-ask-acts">
          <button class="btn primary sm" type="button" data-perm="${esc(m.rid)}" data-allow="1">✓ Cho phép</button>
          <button class="btn ghost sm" type="button" data-perm="${esc(m.rid)}" data-allow="1" data-always="1" title="Không hỏi lại công cụ ${esc(m.tool || '')} trong phiên này">✓ Luôn cho phép (phiên này)</button>
          <span class="tvcc-sp"></span><button class="btn ghost sm tvcc-deny" type="button" data-perm="${esc(m.rid)}" data-allow="0">✗ Từ chối</button></div>`}</div>`;
    }
    const qs = m.questions || [];
    return `<div class="tvcc-ask ${done ? 'done' : ''}" data-q-rid="${esc(m.rid)}"><div class="tvcc-ask-h"><span class="tvcc-ask-ic">❓</span><div><b>Claude cần bạn chọn</b>
        <small>${qs.length > 1 ? `${qs.length} câu hỏi` : 'Bấm 1 lựa chọn hoặc nhập câu trả lời khác'}</small></div></div>
      ${qs.map((qq, qi) => {
        const picked = (T.picks[m.rid] || {})[qi] || [];
        return `<div class="tvcc-q">${qq.header ? `<span class="tvcc-chip">${esc(qq.header)}</span>` : ''}<div class="tvcc-q-t">${esc(qq.question || '')}${qq.multiSelect ? ' <small class="muted">(chọn nhiều)</small>' : ''}</div>
          <div class="tvcc-opts">${(qq.options || []).map((o, oi) => `<button type="button" class="tvcc-opt ${picked.includes(oi) ? 'on' : ''}" ${done ? 'disabled' : ''}
            data-opt="${esc(m.rid)}" data-qi="${qi}" data-oi="${oi}" title="${esc(o.description || '')}"><b>${esc(o.label || '')}</b>${o.description ? `<small>${esc(o.description)}</small>` : ''}</button>`).join('')}</div>
          ${done ? '' : `<input class="tvcc-other" data-other="${esc(m.rid)}" data-qi="${qi}" placeholder="Hoặc nhập câu trả lời khác…" value="${esc((T.others[m.rid] || {})[qi] || '')}">`}</div>`;
      }).join('')}
      ${done ? `<div class="tvcc-answered">✓ ${esc(m.answered)}</div>` : `<div class="tvcc-ask-acts"><span class="tvcc-sp"></span><button class="btn primary sm" type="button" data-q-send="${esc(m.rid)}">Gửi trả lời ➤</button></div>`}</div>`;
  }

  function toolLine(m) {
    const [ic, label] = toolLabel(m);
    const st = m.status === 'ok' ? '✓' : m.status === 'error' ? '✗' : '';
    const open = T.openTool.has(m.id);
    return `<div class="tvcc-tool ${m.status || 'running'} ${m.sub ? 'sub' : ''}" data-tool-open="${esc(m.id)}"><span class="st">${st || '<i class="tvcc-spin"></i>'}</span>
      <span class="ic">${ic}</span><b>${esc(label)}</b>${m.auto ? '<span class="tvcc-autotag" title="Chế độ tự động đã tự duyệt thao tác này">tự duyệt</span>' : ''}<span class="tx">${esc(m.text || '')}</span><small>${esc(m.at || '')}</small>${open && m.result ? `<pre>${esc(m.result)}</pre>` : ''}</div>`;
  }

  function actHtml(g) {
    const n = g.items.length;
    const running = g.items.some(x => !x.status || x.status === 'running');
    const errs = g.items.filter(x => x.status === 'error').length;
    const last = g.items[n - 1];
    const open = T.open.has(g.id);
    return `<div class="tvcc-act ${running ? 'run' : ''} ${open ? 'open' : ''}">
      <button class="tvcc-act-h" type="button" data-act="${esc(g.id)}"><span class="tvcc-act-ic">${running ? '<i class="tvcc-spin"></i>' : errs ? '⚠' : '✓'}</span>
        <b>${n} thao tác</b><span class="tvcc-act-cur">${toolLabel(last)[0]} ${esc(toolLabel(last)[1])}${running ? '…' : ''}</span>
        ${errs ? `<em>${errs} lỗi</em>` : ''}${g.items.some(x => x.auto) ? `<span class="tvcc-autotag">${g.items.filter(x => x.auto).length} tự duyệt</span>` : ''}<span class="tvcc-sp"></span><i class="tvcc-chev">▾</i></button>
      ${open ? `<div class="tvcc-act-list">${g.items.map(toolLine).join('')}</div>` : ''}</div>`;
  }

  function msgHtml(m) {
    if (m.role === 'user') return `<div class="tvcc-msg user"><div class="tvcc-bubble">${md(m.text)}</div><small>${esc(m.at || '')}</small></div>`;
    if (m.role === 'assistant') {
      const files = (m.files || []).length ? `<div class="tvcc-files">${m.files.map(f => `<figure class="${f.kind}">${
        f.kind === 'image' ? `<img src="${esc(f.url)}" data-zoom="${esc(f.url)}" alt="" loading="lazy">`
          : f.kind === 'video' ? `<video src="${esc(f.url)}" controls preload="metadata"></video>` : `<audio src="${esc(f.url)}" controls preload="none"></audio>`
      }<figcaption title="${esc(f.path)}">${esc(f.path.split(/[\\/]/).pop())}</figcaption></figure>`).join('')}</div>` : '';
      return `<div class="tvcc-msg bot"><span class="tvcc-av">C</span><div class="tvcc-col"><div class="tvcc-bubble">${md(m.text)}${files}</div><small>Claude · ${esc(m.at || '')}</small></div></div>`;
    }
    if (m.role === 'ask') return askHtml(m);
    if (m.role === 'card' && m.kind === 'adplan') return adCardHtml(m);
    if (m.role === 'card' && m.kind === 'autosum') return autoSumHtml(m);
    return `<div class="tvcc-sys ${m.error ? 'err' : ''} ${m.auto ? 'auto' : ''}">${esc(m.text || '')}</div>`;
  }

  function autoSumHtml(m) {
    const tk = m.tong_ket || {};
    const has = tk.diem !== undefined && tk.diem !== null && tk.diem !== '';
    const ok = has && tk.dat !== false && Number(tk.diem) >= Number(m.threshold || 0);
    return `<div class="tvcc-ask autosum ${ok ? 'good' : has ? 'warn' : ''}"><div class="tvcc-ask-h"><span class="tvcc-ask-ic">🏆</span><div><b>Tổng kết lượt tự động${m.project ? ` · ${esc(m.project)}` : ''}</b>
        <small>${m.error ? 'Lượt dừng giữa chừng — xem tin cuối của Claude' : 'Claude đã làm xong lượt tự động'}</small></div><span class="tvcc-sp"></span>
        ${has ? `<span class="tvcc-score ${ok ? 'ok' : 'bad'}">${Number(tk.diem).toFixed(1)}<small>/10</small></span>` : ''}</div>
      <div class="tvcc-adkv">
        <div><span>Kết quả</span><b>${has ? (ok ? '✓ Đạt ngưỡng' : '⚠ Chưa đạt ngưỡng') : 'Chưa có bảng điểm'} (${esc(m.threshold)}/10)</b></div>
        <div><span>Tự duyệt</span><b>${esc(m.approved || 0)} thao tác</b></div>
        <div><span>Đã chặn</span><b>${esc(m.blocked || 0)} thao tác</b></div>
        <div><span>Chi phí lượt</span><b>~$${Number(m.cost || 0).toFixed(2)} / $${esc(m.max_cost)}</b></div></div>
      ${tk.ghi_chu ? `<div class="tvcc-adtxt"><span>Ghi chú</span>${md(tk.ghi_chu)}</div>` : ''}
      ${m.video && m.video.url ? `<div class="tvcc-files"><figure class="video"><video src="${esc(m.video.url)}" controls preload="metadata"></video><figcaption>Video cuối</figcaption></figure></div>` : ''}
      <div class="tvcc-ask-acts"><span class="tvcc-sp"></span><button class="btn ghost sm" type="button" data-goto-eval>🏆 Xem bảng điểm chi tiết</button></div></div>`;
  }

  function heroHtml() {
    const sug = [['🛒', 'Video livestream bán hàng', 'Làm video livestream bán hàng cho sản phẩm (mã: …), link web: …'],
      ['✨', 'Dùng Muse thay cho Grok', 'Làm TVC livestream bằng Muse thay cho Grok cho sản phẩm …'],
      ['🎵', 'Sửa dự án đã có', 'Mở lại dự án … và đổi nhạc nền'],
      ['📣', 'Bài Facebook cho dự án', 'Tạo bài Facebook hoàn chỉnh (nội dung, poster, video) cho dự án … rồi đăng lên Fanpage'],
      ['📈', 'Gợi ý quảng cáo cho bài vừa đăng', 'Gợi ý setup quảng cáo cho bài Facebook vừa đăng của dự án … và tạo yêu cầu quảng cáo']];
    return `<div class="tvcc-hero"><div class="tvcc-hero-ic">🎬</div><h3>Bạn nói ý tưởng — Claude lo phần còn lại</h3>
      <p class="muted">Claude Code làm đúng quy trình skill <code>tvc-livestream-capcut</code>: hỏi thông tin, tra sản phẩm, viết kịch bản, tạo ảnh, tạo clip nói, dựng draft CapCut.</p>
      <div class="tvcc-flow"><div><i>1</i><b>Bạn mô tả</b><small>Sản phẩm, link web, ảnh người mẫu + sản phẩm</small></div><span>→</span>
        <div><i>2</i><b>Claude làm theo skill</b><small>Hỏi bạn khi cần chọn / cần quyền</small></div><span>→</span>
        <div><i>3</i><b>Nhận draft CapCut</b><small>Timeline sửa được + bản xem trước MP4</small></div></div>
      <div class="tvcc-sugs">${sug.map(([ic, t, s]) => `<button type="button" class="tvcc-sug" data-sug="${esc(s)}"><span>${ic}</span><div><b>${esc(t)}</b><small>${esc(s)}</small></div></button>`).join('')}</div></div>`;
  }

  function messagesHtml() {
    const st = T.st || {};
    const chat = st.chat;
    if (!chat || !chat.messages.length) return heroHtml();
    const out = [];
    let group = null;
    for (const m of chat.messages) {
      if (m.role === 'tool') {
        if (!group) { group = { id: m.id, items: [] }; out.push(group); }
        group.items.push(m);
      } else { group = null; out.push(m); }
    }
    const typing = st.running && !(st.pending || []).length && !(out.length && out[out.length - 1].items)
      ? '<div class="tvcc-typing"><span class="tvcc-av">C</span><i></i><i></i><i></i></div>' : '';
    return out.map(x => (x.items ? actHtml(x) : msgHtml(x))).join('') + typing;
  }

  /* ---------------------------------------------------------------- đầu trang / tiến độ / thanh soạn */
  function pill() {
    const st = T.st || {};
    if ((st.pending || []).length) return ['wait', '⏸ Chờ bạn trả lời'];
    if (st.running) return ['run', 'Claude đang làm…'];
    if (st.connected) return ['on', 'Phiên đang mở'];
    return ['off', 'Chưa mở phiên'];
  }

  function headHtml() {
    const chat = T.st && T.st.chat;
    const [cls, text] = pill();
    return `<div class="tvcc-brand"><span class="tvcc-logo">🎬</span><div><h2>Trợ lý TVC</h2>
        <small class="muted" title="Claude Code chạy skill tvc-livestream-capcut trong ${esc((T.env && T.env.root) || 'D:\\CapCut')}">Claude Code · tvc-livestream-capcut · ${esc((T.env && T.env.root) || 'D:\\CapCut')}</small></div></div>
      <span class="tvcc-pill ${cls}"><i></i>${text}</span>${chat && chat.auto && chat.auto.on ? '<span class="tvcc-pill auto" title="Claude tự duyệt các bước của quy trình">🤖 Tự động</span>' : ''}
      <span class="tvcc-sp"></span>
      ${chat && chat.messages.length ? `<div class="tvcc-title" title="${esc(chat.title)}">${esc(chat.title)}${chat.cost ? `<small>~$${Number(chat.cost).toFixed(2)}</small>` : ''}</div>` : ''}
      <button class="btn ghost sm ${T.showHist ? 'on' : ''}" type="button" data-hist title="Hội thoại đã có — mở lại = tiếp tục đúng phiên Claude Code cũ">🕘 Lịch sử${T.chats.length ? ` <b>${T.chats.length}</b>` : ''}</button>
      <button class="btn primary sm" type="button" data-new>＋ Hội thoại mới</button>
      ${chat && chat.messages.length ? '<button class="btn ghost sm tvcc-icon" type="button" data-del title="Xoá hội thoại này khỏi app">🗑</button>' : ''}
      <button class="btn ghost sm tvcc-icon ${T.showCfg ? 'on' : ''}" type="button" data-cfg title="Cài đặt">⚙</button>`;
  }

  function extraHtml() {
    const e = T.env;
    const bad = [];
    if (e) {
      if (!e.claude) bad.push('chưa có claude.exe (cài Claude Code native)');
      if (!e.sdk) bad.push('thiếu thư viện claude-agent-sdk');
      if (!e.skills['tvc-livestream-capcut']) bad.push('chưa có skill tvc-livestream-capcut trong ~/.claude/skills');
    }
    const cur = T.st && T.st.chat && T.st.chat.id;
    const hiddenN = T.chats.filter(c => c.hidden).length;
    const list = T.chats.filter(c => !c.hidden || T.showHidden);
    const card = c => `<div role="button" tabindex="0" class="tvcc-hist-i ${c.id === cur ? 'on' : ''} ${c.hidden ? 'hid' : ''}" data-chat-open="${esc(c.id)}">
        <b>${esc(c.title || c.id)}</b><small>${c.project ? `<span class="tvcc-chip on">${esc(c.project)}</span>` : ''}${esc((c.updated || '').slice(5, 16))} · ${c.turns || 0} lượt${c.cost ? ` · ~$${Number(c.cost).toFixed(2)}` : ''}</small>
        <button type="button" class="tvcc-hist-hide" data-chat-hide="${esc(c.id)}" data-h="${c.hidden ? '0' : '1'}" title="${c.hidden ? 'Hiện lại trong dải lịch sử' : 'Ẩn khỏi dải lịch sử (không xoá)'}">${c.hidden ? '👁 Bỏ ẩn' : '👁 Ẩn'}</button></div>`;
    const tools = `<div class="tvcc-hist-tools">${hiddenN ? `<button type="button" class="tvcc-hist-btn ${T.showHidden ? 'on' : ''}" data-hist-hidden>${T.showHidden ? 'Giấu hội thoại đã ẩn' : `Hiện ${hiddenN} đã ẩn`}</button>` : ''}
        <button type="button" class="tvcc-hist-btn" data-hist title="Thu gọn dải lịch sử">▴ Thu gọn</button></div>`;
    const hist = !T.chats.length ? '' : T.showHist
      ? `<div class="tvcc-histbox"><div class="tvcc-hist">${list.length ? list.map(card).join('') : '<small class="muted">Mọi hội thoại đang ẩn.</small>'}</div>${tools}</div>`
      : `<button type="button" class="tvcc-hist-mini" data-hist>🕘 ${T.chats.length - hiddenN} hội thoại${hiddenN ? ` · ${hiddenN} đã ẩn` : ''} <span>▾ Mở</span></button>`;
    const c = T.cfg;
    const cfg = T.showCfg && c ? `<div class="tvcc-cfg"><label>Thư mục làm việc của Claude <span class="row"><input data-c="tvc_root" value="${esc(c.values.tvc_root)}" placeholder="${esc(c.root)}"><button class="btn ghost sm" type="button" data-pick-root>📁</button></span></label>
      <label>Model Claude (trống = mặc định của Claude Code) <input data-c="tvc_claude_model" value="${esc(c.values.tvc_claude_model)}" placeholder="mặc định"></label>
      <label>🏆 Bộ tiêu chí chấm điểm (chế độ tự động) — mỗi dòng 1 tiêu chí, trống = bộ mặc định
        <textarea data-c="tvc_rubric" rows="6" placeholder="${esc(((T.af.meta && T.af.meta.rubric) || []).join('\n'))}">${esc(c.values.tvc_rubric || '')}</textarea></label>
      <div class="row"><span class="tvcc-sp"></span><button class="btn ghost sm" type="button" data-cfg>Đóng</button><button class="btn primary sm" type="button" data-cfg-save>Lưu</button></div></div>` : '';
    return `${bad.length ? `<div class="tvcc-warn">⚠ ${bad.map(esc).join(' · ')}</div>` : ''}${hist}${cfg}`;
  }

  function stepsHtml() {
    const s = (T.proj && T.proj.state) || {};
    const done = STEPS.map(([k]) => (k === 'fb' ? s.fb === 'posted' : k === 'ads' ? ADS_DONE.includes(s.ads) : !!s[k]));
    const cur = done.indexOf(false);
    const active = T.st && T.st.running && T.proj && T.st.chat && T.st.chat.project === T.proj.name ? cur : -1;
    const sub = { images_done: s.images, clips_done: s.clips, fb: s.fb && s.fb !== 'posted' ? (FB_ST[s.fb] || [])[1] : '',
      ads: s.ads && !ADS_DONE.includes(s.ads) ? (ADS_ST[s.ads] || [])[1] : '' };
    return `<div class="tvcc-steps-name">${T.proj ? `<b>${esc(T.proj.name)}</b>` : '<span class="muted">Chưa có dự án</span>'}</div>
      ${STEPS.map(([k, label], i) => `<div class="tvcc-step ${done[i] ? 'done' : ''} ${active === i ? 'active' : ''}"><i>${done[i] ? '✓' : i + 1}</i><span>${esc(label)}${sub[k] ? ` <small>${esc(sub[k])}</small>` : ''}</span></div>`).join('<em></em>')}`;
  }

  function chipsHtml() {
    return T.attach.map((a, i) => `<span class="tvcc-att"><i>${a.kind === 'nguoi_mau' ? '🧑' : '📦'}</i>${a.kind === 'nguoi_mau' ? 'Người mẫu' : 'Sản phẩm'}: ${esc(a.path.split(/[\\/]/).pop())}<button type="button" data-att-del="${i}" title="Bỏ khỏi tin nhắn">✕</button></span>`).join('');
  }

  function cbarHtml() {
    const st = T.st || {};
    return `<button class="tvcc-attach" type="button" data-up="nguoi_mau" title="Chép ảnh vào _input\\nguoi_mau và đính vào tin nhắn">📎 Ảnh người mẫu</button>
      <button class="tvcc-attach" type="button" data-up="san_pham" title="Chép ảnh vào _input\\san_pham và đính vào tin nhắn">📎 Ảnh sản phẩm</button>
      ${st.chat && st.chat.auto && st.chat.auto.on
        ? '<button class="tvcc-attach tvcc-auto on" type="button" data-auto-off title="Tắt tự động — các bước sau hỏi lại bạn">🤖 Đang tự động · Tắt</button>'
        : `<button class="tvcc-attach tvcc-auto ${T.af.show ? 'on' : ''}" type="button" data-auto-form title="Điền đủ đầu vào rồi để Claude tự làm toàn bộ quy trình">🤖 Tự động toàn bộ</button>`}
      <span class="tvcc-sp"></span><small class="muted">Enter gửi · Shift+Enter xuống dòng · mỗi tin dùng lượt gói Claude</small>
      ${st.running ? '<button class="tvcc-stop" type="button" data-stop title="Dừng lượt Claude đang làm">⏹ Dừng</button>' : ''}
      <button class="tvcc-send" type="button" data-send title="Gửi">➤</button>`;
  }

  /* ---------------------------------------------------------------- bảng dự án (chỉ đọc, chia tab) */
  function projectHtml() {
    const info = Object.fromEntries(T.projects.map(p => [p.name, p]));
    const names = T.browse ? T.projects.map(p => p.name) : chatProjects();
    const opts = names.map(n => `<option value="${esc(n)}" ${n === T.projName ? 'selected' : ''}>${esc(n)}${info[n] ? ` · ${esc(info[n].updated)}` : ''}</option>`).join('');
    const head = `<div class="tvcc-phead ${T.browse ? 'browse' : ''}">${T.browse ? '<span class="tvcc-browse-tag" title="Chỉ xem — không gắn vào hội thoại này">📂 Dự án khác</span>' : ''}
        ${names.length ? `<select data-proj title="${T.browse ? 'Mọi dự án trong thư mục gốc (chỉ xem)' : 'Dự án của hội thoại này'}">${opts}</select>` : '<span class="tvcc-phead-empty">Kết quả của hội thoại này</span>'}
        ${T.browse ? '<button class="btn ghost sm" type="button" data-pback title="Về kết quả của hội thoại đang mở">↩ Về hội thoại</button>'
          : '<button class="btn ghost sm" type="button" data-pbrowse title="Xem dự án khác trong thư mục gốc (chỉ xem, không gắn vào hội thoại)">📂 Dự án khác</button>'}
        <button class="btn ghost sm tvcc-icon" type="button" data-prefresh title="Tải lại">↻</button></div>`;
    const p = T.proj;
    if (!p) {
      return T.browse || names.length
        ? `${head}<div class="tvcc-pempty"><span>📁</span><b>Không đọc được dự án</b><small class="muted">Thư mục dự án có thể đã bị đổi tên / xoá — bấm ↻ để tải lại.</small></div>`
        : `${head}<div class="tvcc-pempty"><span>📁</span><b>Chưa có kết quả</b><small class="muted">Kết quả của hội thoại này (ảnh, clip, bản xem trước, bài Facebook…) sẽ hiện ở đây khi Claude bắt đầu làm dự án.</small>
          <button class="btn ghost sm" type="button" data-pbrowse>📂 Xem dự án khác</button></div>`;
    }
    const s = p.state;
    const ids = Object.keys(p.images);
    const clips = p.du_an.clips || [];
    const tabs = `<nav class="tvcc-tabs">${TABS.map(([k, l]) => `<button type="button" class="${T.ptab === k ? 'on' : ''}" data-ptab="${k}">${l}</button>`).join('')}</nav>`;
    let body = '';
    if (T.ptab === 'overview') {
      const cover = p.preview ? `<video src="${esc(p.preview)}" controls preload="metadata"></video>`
        : p.images[ids[0]] ? `<img src="${esc(p.images[ids[0]])}&thumb=480" alt=""><span class="tvcc-phone-note">Chưa có bản xem trước</span>`
          : '<span class="tvcc-phone-note">Chưa có bản xem trước</span>';
      body = `<div class="tvcc-phone">${cover}</div>
        <div class="tvcc-pacts"><button class="btn ghost sm" type="button" data-popen="project">📂 Thư mục</button>
          ${p.draft_dir ? `<button class="btn ghost sm" type="button" data-popen="draft" title="${esc(p.draft_dir)}">🎬 Draft CapCut</button>` : ''}
          ${s.preview ? '<button class="btn ghost sm" type="button" data-popen="preview">▶ Mở file MP4</button>' : ''}</div>
        ${p.draft_name ? `<div class="tvcc-kv"><span>Draft</span><b>${esc(p.draft_name)}</b></div>` : ''}
        ${p.du_an.shop_name ? `<div class="tvcc-kv"><span>Shop</span><b>${esc(p.du_an.shop_name)}</b></div>` : ''}
        <div class="tvcc-kv"><span>Ảnh / Clip</span><b>${esc(s.images || '0')} · ${esc(s.clips || '0')}</b></div>
        ${p.inputs.san_pham || p.inputs.nguoi_mau ? `<div class="tvcc-inputs">${['nguoi_mau', 'san_pham'].map(k => (p.inputs[k] ? `<figure><img src="${esc(p.inputs[k])}&thumb=200" data-zoom="${esc(p.inputs[k])}" alt=""><figcaption>${k === 'nguoi_mau' ? 'Người mẫu' : 'Sản phẩm'}</figcaption></figure>` : '')).join('')}</div>` : ''}`;
    } else if (T.ptab === 'script') {
      body = clips.some(c => c.dialogue) ? `<div class="tvcc-script">${clips.map(c => `<div class="tvcc-clipcard"><div><span class="tvcc-badge">${esc(c.id)}</span><small class="muted">${String(c.dialogue || '').trim().split(/\s+/).filter(Boolean).length} từ</small></div>
        <p>${esc(c.dialogue || '')}</p>${c.display && c.display !== c.dialogue ? `<small class="muted">Phụ đề: ${esc(c.display)}</small>` : ''}</div>`).join('')}</div>`
        : '<div class="tvcc-pempty"><span>💬</span><small class="muted">Chưa có kịch bản.</small></div>';
    } else if (T.ptab === 'media') {
      body = ids.some(i => p.images[i] || p.clips[i]) ? `<div class="tvcc-grid">${ids.map(i => `<div class="tvcc-pair"><span class="tvcc-badge">${esc(i)}</span>
          ${p.images[i] ? `<img src="${esc(p.images[i])}&thumb=320" data-zoom="${esc(p.images[i])}" alt="" title="Ảnh cảnh ${esc(i)}">` : '<div class="tvcc-ph">ảnh</div>'}
          ${p.clips[i] ? `<video src="${esc(p.clips[i])}" controls preload="none" title="Clip nói ${esc(i)}"></video>` : '<div class="tvcc-ph">clip</div>'}</div>`).join('')}</div>`
        : '<div class="tvcc-pempty"><span>🖼</span><small class="muted">Chưa có ảnh cảnh / clip.</small></div>';
    } else if (T.ptab === 'fb') {
      const f = p.facebook || {};
      const [cls, label] = FB_ST[f.status] || ['', ''];
      body = f.status ? `<div class="tvcc-fbstat"><span class="tvcc-fbbadge ${cls}">${esc(label)}</span>${f.page ? `<small>${esc(f.page)}</small>` : ''}
          ${f.url ? `<a href="${esc(f.url)}">Mở bài ↗</a>` : ''}<span class="tvcc-sp"></span><small class="muted">${esc((f.updated || '').slice(5, 16))}</small></div>
        ${f.error ? `<div class="tvcc-sys err">${esc(f.error)}</div>` : ''}
        <div class="tvcc-fbpost"><div class="tvcc-fbpost-h"><span class="tvcc-fbav">${esc((f.page || 'F').slice(0, 1))}</span><div><b>${esc(f.page || 'Fanpage')}</b><small>${f.kind === 'reel' ? 'Reels' : 'Bài viết'} · 🌐</small></div></div>
          ${f.caption ? `<div class="tvcc-fbpost-t">${md(f.caption)}</div>` : '<div class="tvcc-fbpost-t muted">Chưa có nội dung.</div>'}
          ${f.kind === 'poster' ? '' : f.video ? `<div class="tvcc-fbpost-m"><video src="${esc(f.video)}" controls preload="none"></video></div>` : ''}
          ${f.poster ? `<div class="tvcc-fbpost-m img"><img src="${esc(f.poster)}" data-zoom="${esc(f.poster)}" alt="" title="Poster"></div>` : ''}</div>
        <div class="tvcc-pacts"><button class="btn ghost sm" type="button" data-popen="facebook">📂 Thư mục 09_facebook</button>
          ${f.status === 'posted' && !(p.ads || {}).status ? `<button class="btn ghost sm" type="button" data-sug="Gợi ý setup quảng cáo cho bài Facebook vừa đăng của dự án ${esc(p.name)} và tạo yêu cầu quảng cáo">📈 Gợi ý quảng cáo</button>` : ''}</div>`
        : `<div class="tvcc-pempty"><span>📣</span><b>Chưa có bài Facebook</b><small class="muted">Nhắn “Tạo bài Facebook cho dự án này” — Claude viết nội dung, làm poster, chọn video rồi hỏi bạn trước khi đăng.</small>
          <button class="btn ghost sm" type="button" data-sug="Tạo bài Facebook hoàn chỉnh (nội dung, poster, video) cho dự án ${esc(p.name)} rồi đăng lên Fanpage">📣 Gợi ý câu lệnh</button></div>`;
    } else if (T.ptab === 'eval') {
      body = evalHtml(p);
    } else if (T.ptab === 'ads') {
      const a = p.ads || {};
      const [cls, label] = ADS_ST[a.status] || ['', ''];
      const posted = (p.facebook || {}).status === 'posted';
      const sug = `Gợi ý setup quảng cáo cho bài Facebook vừa đăng của dự án ${p.name} và tạo yêu cầu quảng cáo`;
      body = a.status ? `<div class="tvcc-fbstat"><span class="tvcc-fbbadge ${cls}">${esc(label)}</span>${a.summary && a.summary.name ? `<small>${esc(a.summary.name)}</small>` : ''}
          <span class="tvcc-sp"></span><small class="muted">${esc((a.created || '').slice(5, 16))}</small></div>
        ${a.error ? `<div class="tvcc-sys err">${esc(a.error)}</div>` : ''}
        ${a.plan_id && a.status !== 'cancelled' ? `<div class="tvcc-adbox">${adSummaryHtml(a.summary)}<div class="tvcc-pacts">
          <button class="btn primary sm" type="button" data-ad-open="${esc(a.plan_id)}">📈 Mở Trợ lý quảng cáo</button>
          ${a.status === 'pending' ? `<button class="btn ghost sm tvcc-deny" type="button" data-ad-cancel="${esc(p.name)}">✗ Huỷ yêu cầu</button>` : ''}</div></div>` : ''}
        ${a.goi_y ? `<div class="tvcc-yt"><span class="tvcc-h">Gợi ý setup của Claude</span><br>${md(a.goi_y)}</div>` : ''}
        ${!a.plan_id || a.status === 'cancelled' ? `<div class="tvcc-pacts"><button class="btn ghost sm" type="button" data-sug="${esc(sug)}">📈 Nhờ Claude tạo yêu cầu quảng cáo</button></div>` : ''}`
        : `<div class="tvcc-pempty"><span>📈</span><b>Chưa có gợi ý quảng cáo</b><small class="muted">${posted ? 'Bài Facebook đã đăng — nhờ Claude gợi ý setup (mục tiêu, ngân sách, đối tượng) dựa trên số liệu tài khoản, rồi tạo yêu cầu quảng cáo chờ bạn duyệt.' : 'Đăng bài Facebook trước (tab 📣 Bài FB), sau đó nhờ Claude gợi ý quảng cáo.'}</small>
          ${posted ? `<button class="btn ghost sm" type="button" data-sug="${esc(sug)}">📈 Gợi ý câu lệnh</button>` : ''}</div>`;
    } else {
      body = p.y_tuong ? `<div class="tvcc-yt">${md(p.y_tuong)}</div>` : '<div class="tvcc-pempty"><span>📝</span><small class="muted">Chưa có ghi chú ý tưởng.</small></div>';
    }
    return `${head}${tabs}<div class="tvcc-pbody">${body}</div>`;
  }

  /* ---------------------------------------------------------------- dựng khung + vẽ từng phần */
  function render() {
    const el = root();
    if (!el) return;
    if (!el.querySelector('.tvcc')) {
      el.innerHTML = `<div class="tvcc"><header class="tvcc-head" data-head></header><div data-extra></div>
        <div class="tvcc-steps" data-steps></div>
        <div class="tvcc-main">
          <section class="tvcc-chat"><div class="tvcc-msgs" data-msgs></div><div data-autobox></div>
            <div class="tvcc-composer"><div class="tvcc-atts" data-chips></div>
              <textarea data-input rows="2" placeholder="Nhắn cho Claude…"></textarea>
              <div class="tvcc-cbar" data-cbar></div></div></section>
          <aside class="tvcc-proj" data-projbox></aside>
        </div></div>`;
      const input = q('[data-input]');
      input.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
      input.oninput = () => { input.style.height = 'auto'; input.style.height = `${Math.min(180, input.scrollHeight)}px`; };
    }
    drawHead(); drawSteps(); drawMessages(true); drawBar(); drawAuto(); drawProject();
  }

  function drawHead() {
    const h = q('[data-head]');
    if (!h) return;
    h.innerHTML = headHtml();
    q('[data-extra]').innerHTML = extraHtml();
    bindHead();
  }

  function drawSteps() { const s = q('[data-steps]'); if (s) s.innerHTML = stepsHtml(); }

  function drawMessages(force) {
    const box = q('[data-msgs]');
    if (!box) return;
    const act = document.activeElement;
    if (!force && act && act.classList && act.classList.contains('tvcc-other') && box.contains(act)) {
      act.onblur = () => drawMessages();  // đang gõ câu trả lời khác → vẽ lại khi rời ô (không mất con trỏ)
      return;
    }
    const near = force || box.scrollHeight - box.scrollTop - box.clientHeight < 200;
    box.innerHTML = messagesHtml();
    bindMsgs();
    if (near) box.scrollTop = box.scrollHeight;
  }

  /* ---------------------------------------------------------------- 🤖 phiếu tự động toàn bộ */
  function autoMissing() {
    const i = T.af.inputs;
    const miss = [];
    if (!i.san_pham_ten.trim()) miss.push('tên / mã sản phẩm');
    if (!i.anh_nguoi_mau.length) miss.push('ảnh người mẫu');
    if (!i.anh_san_pham.length && !(i.anh_tu_web && /^https?:\/\//.test(i.link.trim()))) miss.push(i.anh_tu_web ? 'link web (để Claude tự lấy ảnh)' : 'ảnh sản phẩm');
    if (T.af.cfg.fb_autopost && !T.af.cfg.fb_page) miss.push('Fanpage để tự đăng');
    return miss;
  }

  function autoHtml() {
    const { inputs: i, cfg: c, meta } = T.af;
    const pages = (meta && meta.pages) || [];
    const rubric = (meta && meta.rubric) || [];
    const imgs = (kind, list) => list.map((p, k) => `<span class="tvcc-att"><i>${kind === 'nguoi_mau' ? '🧑' : '📦'}</i>${esc(p.split(/[\\/]/).pop())}<button type="button" data-af-del="${kind}" data-k="${k}" title="Bỏ">✕</button></span>`).join('');
    const miss = autoMissing();
    const field = (key, label, ph, req) => `<label><span>${esc(label)}${req ? ' <em>*</em>' : ''}</span><input data-af="${key}" value="${esc(i[key])}" placeholder="${esc(ph)}"></label>`;
    return `<div class="tvcc-autof">
      <header><span class="tvcc-ask-ic">🤖</span><div><b>Tự động toàn bộ</b><small>Điền đủ đầu vào → Claude tự duyệt mọi bước, mỗi chặng tạo ${c.variants} phương án, chấm theo bộ tiêu chí và giữ bản tốt nhất</small></div>
        <span class="tvcc-sp"></span><button class="btn ghost sm tvcc-icon" type="button" data-auto-form title="Đóng">✕</button></header>
      <div class="tvcc-autof-grid">
        ${field('san_pham_ten', 'Sản phẩm / mã', 'VD Boss 1 Đạm Nano (ONNV162)', true)}
        ${field('link', 'Link web sản phẩm', 'https://…', false)}
        ${field('shop', 'Tên shop / hotline', 'VD Phân bón NNV · 09xx', false)}
        <label>Clip nói bằng<select data-af="cong_cu"><option value="grok" ${i.cong_cu !== 'muse' ? 'selected' : ''}>Grok Imagine (Chrome)</option><option value="muse" ${i.cong_cu === 'muse' ? 'selected' : ''}>Muse (muse.ai)</option></select></label>
        <div class="tvcc-autof-img"><span>Ảnh người mẫu <em>*</em></span><div>${imgs('nguoi_mau', i.anh_nguoi_mau)}<button class="tvcc-attach" type="button" data-af-up="nguoi_mau">📎 Chọn ảnh</button></div></div>
        <div class="tvcc-autof-img"><span>Ảnh sản phẩm ${i.anh_tu_web ? '' : '<em>*</em>'}</span><div>${imgs('san_pham', i.anh_san_pham)}<button class="tvcc-attach" type="button" data-af-up="san_pham">📎 Chọn ảnh</button>
          <button class="tvcc-attach" type="button" data-af-web ${/^https?:\/\//.test(i.link.trim()) ? '' : 'disabled'} title="Tìm ảnh sản phẩm trên trang ở ô Link web sản phẩm">🌐 Lấy từ web</button></div>
          <label class="tvcc-autof-chk"><input type="checkbox" data-af-webauto ${i.anh_tu_web ? 'checked' : ''}> Để Claude tự lấy ảnh sản phẩm từ link khi chạy</label></div>
        ${webPickHtml()}
        <label class="wide">Yêu cầu thêm<textarea data-af="yeu_cau" rows="2" placeholder="Độ dài, giọng vùng miền, ưu đãi, điều cần tránh…">${esc(i.yeu_cau)}</textarea></label>
      </div>
      <div class="tvcc-autof-opts">
        <label>Phương án / chặng<select data-afc="variants">${[1, 2, 3].map(n => `<option value="${n}" ${+c.variants === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
        <label>Ngưỡng điểm<input type="number" min="1" max="10" step="0.5" data-afc="threshold" value="${esc(c.threshold)}"></label>
        <label>Làm lại tối đa<input type="number" min="0" max="5" data-afc="retries" value="${esc(c.retries)}"></label>
        <label>Giới hạn chi phí ($)<input type="number" min="0.5" max="100" step="0.5" data-afc="max_cost" value="${esc(c.max_cost)}"></label>
        <label>Fanpage<select data-afc="fb_page"><option value="">— không chọn (dừng ở thẻ xác nhận) —</option>${pages.map(p => `<option value="${esc(p.id)}" ${p.id === c.fb_page ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
        <label class="tvcc-autof-chk ${c.fb_page ? '' : 'off'}"><input type="checkbox" data-afc="fb_autopost" ${c.fb_autopost ? 'checked' : ''} ${c.fb_page ? '' : 'disabled'}> Tự đăng lên Fanpage này (không hỏi lại)</label>
      </div>
      <details class="tvcc-autof-rub"><summary>🏆 Bộ tiêu chí chấm điểm (${rubric.length}) — sửa ở ⚙ Cài đặt</summary><ol>${rubric.map(r => `<li>${esc(r)}</li>`).join('')}</ol></details>
      <footer><small class="${miss.length ? 'tvcc-autof-miss' : 'muted'}" data-af-miss>${miss.length ? `Còn thiếu: ${esc(miss.join(', '))}` : 'Đủ đầu vào. Vẫn chặn: lệnh nguy hiểm, ghi ngoài thư mục gốc, thao tác Ads có ghi; yêu cầu quảng cáo chỉ ở Chờ duyệt.'}</small>
        <span class="tvcc-sp"></span><button class="btn primary sm" type="button" data-af-go ${miss.length ? 'disabled' : ''}>▶ Chạy tự động</button></footer></div>`;
  }

  function webPickHtml() {
    const w = T.af.web;
    if (!w) return '';
    const head = `<div class="tvcc-webpick-h"><b>🌐 Ảnh trên trang</b>${w.title ? `<small class="muted">${esc(w.title)}</small>` : ''}<span class="tvcc-sp"></span>
      <button class="btn ghost sm tvcc-icon" type="button" data-af-wclose title="Đóng">✕</button></div>`;
    if (w.loading) return `<div class="tvcc-webpick wide">${head}<small class="muted"><i class="tvcc-spin"></i> Đang đọc trang…</small></div>`;
    if (w.error) return `<div class="tvcc-webpick wide">${head}<small class="tvcc-autof-miss">${esc(w.error)}</small></div>`;
    return `<div class="tvcc-webpick wide">${head}
      <div class="tvcc-webpick-grid">${w.images.map((u, k) => `<button type="button" class="tvcc-webimg ${w.picked.has(k) ? 'on' : ''}" data-af-wpick="${k}" title="${esc(u)}">
        <img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer"><i>${w.picked.has(k) ? '✓' : ''}</i></button>`).join('')}</div>
      <div class="tvcc-webpick-f"><small class="muted">Bấm để chọn / bỏ — ảnh tải về &lt;gốc TVC&gt;\\_input\\san_pham</small><span class="tvcc-sp"></span>
        <button class="btn primary sm" type="button" data-af-wsave ${w.picked.size ? '' : 'disabled'}>${w.saving ? '<i class="tvcc-spin"></i> Đang tải…' : `Dùng ${w.picked.size} ảnh đã chọn`}</button></div></div>`;
  }

  function drawAuto() {
    const box = q('[data-autobox]');
    if (!box) return;
    const chat = T.st && T.st.chat;
    const on = T.af.show && !(chat && chat.auto && chat.auto.on);
    box.innerHTML = on ? autoHtml() : '';
    if (on) bindAuto(box);
  }

  function autoReady(box) {  // gõ chữ: chỉ cập nhật dòng "còn thiếu" + nút chạy (không vẽ lại cả phiếu)
    const miss = autoMissing();
    const m = box.querySelector('[data-af-miss]');
    const go = box.querySelector('[data-af-go]');
    if (m) { m.textContent = miss.length ? `Còn thiếu: ${miss.join(', ')}` : 'Đủ đầu vào — bấm Chạy tự động.'; m.className = miss.length ? 'tvcc-autof-miss' : 'muted'; }
    if (go) go.disabled = !!miss.length;
    const web = box.querySelector('[data-af-web]');
    if (web) web.disabled = !/^https?:\/\//.test(T.af.inputs.link.trim());
  }

  function bindAuto(box) {
    box.querySelectorAll('[data-af]').forEach(inp => {
      inp.oninput = inp.onchange = () => { T.af.inputs[inp.dataset.af] = inp.value; autoReady(box); };
    });
    box.querySelectorAll('[data-afc]').forEach(inp => {
      inp.onchange = () => {
        const k = inp.dataset.afc;
        T.af.cfg[k] = inp.type === 'checkbox' ? inp.checked : inp.value;
        if (k === 'fb_page' && !inp.value) T.af.cfg.fb_autopost = false;
        if (k === 'variants' || k === 'fb_page' || k === 'fb_autopost') drawAuto(); else autoReady(box);
      };
    });
    box.querySelectorAll('[data-af-up]').forEach(b => {
      b.onclick = async () => {
        const files = await api('pick_files', 'images_multi');
        if (!files || !files.length) return;
        const r = await call('tvc_chat_upload', b.dataset.afUp, files);
        if (!r) return;
        T.af.inputs[b.dataset.afUp === 'nguoi_mau' ? 'anh_nguoi_mau' : 'anh_san_pham'].push(...r.files);
        drawAuto();
      };
    });
    const webBtn = box.querySelector('[data-af-web]');
    if (webBtn) {
      webBtn.onclick = async () => {
        const link = T.af.inputs.link.trim();
        T.af.web = { loading: true };
        drawAuto();
        const r = await api('tvc_web_images', link).catch(err => ({ ok: false, error: String(err) }));
        T.af.web = r && r.ok ? { images: r.web.images, title: r.web.title, picked: new Set([0]) }
          : { error: (r && r.error) || 'Không đọc được trang' };
        drawAuto();
      };
    }
    const webAuto = box.querySelector('[data-af-webauto]');
    if (webAuto) webAuto.onchange = () => { T.af.inputs.anh_tu_web = webAuto.checked; drawAuto(); };
    box.querySelectorAll('[data-af-wpick]').forEach(b => {
      b.onclick = () => { const k = +b.dataset.afWpick; const p = T.af.web.picked; if (p.has(k)) p.delete(k); else p.add(k); drawAuto(); };
    });
    box.querySelectorAll('[data-af-wclose]').forEach(b => { b.onclick = () => { T.af.web = null; drawAuto(); }; });
    const wsave = box.querySelector('[data-af-wsave]');
    if (wsave) {
      wsave.onclick = async () => {
        const w = T.af.web;
        const urls = [...w.picked].sort((a, b) => a - b).map(k => w.images[k]);
        w.saving = true; drawAuto();
        const r = await call('tvc_web_images_save', urls, 'san_pham');
        w.saving = false;
        if (!r) { drawAuto(); return; }
        T.af.inputs.anh_san_pham.push(...r.files);
        T.af.web = null;
        toast(`Đã lấy ${r.files.length} ảnh sản phẩm từ web`, 'ok');
        drawAuto();
      };
    }
    box.querySelectorAll('[data-af-del]').forEach(b => {
      b.onclick = () => { T.af.inputs[b.dataset.afDel === 'nguoi_mau' ? 'anh_nguoi_mau' : 'anh_san_pham'].splice(+b.dataset.k, 1); drawAuto(); };
    });
    box.querySelectorAll('[data-auto-form]').forEach(b => { b.onclick = () => { T.af.show = false; drawAuto(); drawBar(); }; });
    const go = box.querySelector('[data-af-go]');
    if (go) {
      go.onclick = async () => {
        if (autoMissing().length) return;
        const c = T.af.cfg;
        const page = ((T.af.meta && T.af.meta.pages) || []).find(p => p.id === c.fb_page);
        const msg = `Chạy TỰ ĐỘNG toàn bộ quy trình?\n\n• Claude tự duyệt mọi bước (trừ thao tác nguy hiểm / ngoài thư mục gốc / Ads có ghi)\n• ${c.variants} phương án mỗi chặng, ngưỡng ${c.threshold}/10, làm lại tối đa ${c.retries} lần\n• Giới hạn chi phí $${c.max_cost}\n• Facebook: ${c.fb_autopost && page ? `TỰ ĐĂNG lên “${page.name}”` : 'dừng ở thẻ xác nhận để bạn duyệt'}\n• Quảng cáo: chỉ tạo yêu cầu Chờ duyệt`;
        if (!confirm(msg)) return;
        const r = await call('tvc_auto_start', T.af.inputs, { ...c, variants: +c.variants, threshold: +c.threshold, retries: +c.retries, max_cost: +c.max_cost });
        if (!r) return;
        T.st = r.state; T.af.show = false;
        syncChat();
        drawHead(); drawMessages(true); drawBar(); drawAuto();
        const b = await call('tvc_chats');
        if (b) { T.chats = b.chats; drawHead(); }
      };
    }
  }

  function evalHtml(p) {
    const d = p.danh_gia || {};
    if (d.error) return `<div class="tvcc-sys err">${esc(d.error)}</div>`;
    const tc = d.tieu_chi || [];
    if (!tc.length) return `<div class="tvcc-pempty"><span>🏆</span><b>Chưa có bảng điểm</b><small class="muted">Chạy 🤖 Tự động toàn bộ — Claude tạo nhiều phương án, chấm theo bộ tiêu chí và giữ bản tốt nhất; bảng điểm hiện ở đây.</small></div>`;
    const ng = Number(d.nguong || 0);
    const sc = v => `<span class="tvcc-score ${Number(v) >= ng ? 'ok' : 'bad'}">${Number(v).toFixed(1)}</span>`;
    const chips = diem => `<div class="tvcc-evchips">${(diem || []).map((v, k) => `<span class="${Number(v) >= ng ? '' : 'low'}" title="${esc(tc[k] || '')}">${k + 1}·${esc(v)}</span>`).join('')}</div>`;
    const media = pa => (pa.url ? (/\.(mp4|mov|webm)/i.test(pa.file) ? `<video src="${esc(pa.url)}" preload="none" controls></video>` : `<img src="${esc(pa.url)}&thumb=200" data-zoom="${esc(pa.url)}" alt="">`) : '<div class="tvcc-ph">—</div>');
    const tk = d.tong_ket || {};
    const vid = d.video || {};
    return `<div class="tvcc-evsum">${tk.diem !== undefined ? sc(tk.diem) : ''}<div><b>${tk.dat === false ? '⚠ Chưa đạt ngưỡng' : '✓ Tổng kết'} · ngưỡng ${esc(ng)}/10</b>${tk.ghi_chu ? `<small>${esc(tk.ghi_chu)}</small>` : ''}</div></div>
      <details class="tvcc-autof-rub"><summary>Bộ tiêu chí (${tc.length})</summary><ol>${tc.map(t => `<li>${esc(t)}</li>`).join('')}</ol></details>
      ${vid.tb !== undefined ? `<div class="tvcc-evch"><div class="tvcc-evh"><b>🎬 Video cuối</b>${sc(vid.tb)}</div>${chips(vid.diem)}${vid.nhan_xet ? `<small class="muted">${esc(vid.nhan_xet)}</small>` : ''}</div>` : ''}
      ${(d.chang || []).map(ch => `<div class="tvcc-evch"><div class="tvcc-evh"><b>${esc(ch.ten || '')}${ch.clip ? ` · ${esc(ch.clip)}` : ''}</b><small class="muted">${(ch.phuong_an || []).length} phương án</small></div>
        ${(ch.phuong_an || []).map(pa => `<div class="tvcc-evpa ${pa.chon ? 'pick' : ''}">${media(pa)}<div><div class="tvcc-evh">${pa.chon ? '<span class="tvcc-autotag pick">✓ Đã chọn</span>' : ''}${pa.tb !== undefined ? sc(pa.tb) : ''}</div>
          ${chips(pa.diem)}${pa.ly_do ? `<small class="muted">${esc(pa.ly_do)}</small>` : ''}</div></div>`).join('')}</div>`).join('')}`;
  }

  function drawBar() {
    const b = q('[data-cbar]');
    if (!b) return;
    q('[data-chips]').innerHTML = chipsHtml();
    b.innerHTML = cbarHtml();
    bindBar();
  }

  function drawProject() {
    const box = q('[data-projbox]');
    if (!box) return;
    box.innerHTML = projectHtml();
    bindProject();
    drawSteps();
  }

  async function loadProject() {
    if (!T.projName) { T.proj = null; drawProject(); return; }
    const r = await api('tvc_get', T.projName).catch(() => null);
    const next = r && r.ok ? r.project : null;
    const same = JSON.stringify(next) === JSON.stringify(T.proj);  // không đổi → không vẽ lại (video đang phát không bị ngắt)
    T.proj = next;
    if (!same) {
      drawProject();
      if (q('.tvcc-ask.adplan')) drawMessages();  // thẻ yêu cầu quảng cáo hiện trạng thái thật của kế hoạch
    } else drawSteps();
  }

  /* ---------------------------------------------------------------- thao tác */
  function zoom(url) {
    const box = document.createElement('div');
    box.className = 'tvcc-light';
    box.innerHTML = `<img src="${esc(url)}" alt="">`;
    box.onclick = () => box.remove();
    document.body.appendChild(box);
  }

  async function send(preset) {
    const input = q('[data-input]');
    const typed = String(preset !== undefined ? preset : input.value).trim();
    const att = T.attach.map(a => `Mình đã chép ${a.kind === 'nguoi_mau' ? 'ảnh người mẫu' : 'ảnh sản phẩm'} vào: ${a.path}`).join('\n');
    const text = [typed, att].filter(Boolean).join('\n');
    if (!text) return;
    const r = await call('tvc_chat_send', text);
    if (!r) return;
    T.st = r.state;
    syncChat();  // tin đầu tạo hội thoại mới → bảng kết quả của hội thoại mới (trống)
    T.attach = [];
    input.value = ''; input.style.height = 'auto';
    drawHead(); drawMessages(true); drawBar();
    const b = await call('tvc_chats');
    if (b) { T.chats = b.chats; drawHead(); }
  }

  function bindMsgs() {
    const el = root();
    el.querySelectorAll('[data-perm]').forEach(b => {
      b.onclick = async () => {
        const r = await call('tvc_chat_answer', b.dataset.perm, { allow: b.dataset.allow === '1', always: b.dataset.always === '1' });
        if (r) { T.st = r.state; drawHead(); drawMessages(); drawBar(); }
      };
    });
    el.querySelectorAll('[data-opt]').forEach(b => {
      b.onclick = () => {
        const rid = b.dataset.opt, qi = +b.dataset.qi, oi = +b.dataset.oi;
        const m = T.st.chat.messages.find(x => x.rid === rid);
        const qq = (m.questions || [])[qi] || {};
        T.picks[rid] = T.picks[rid] || {};
        const cur = (T.picks[rid][qi] = T.picks[rid][qi] || []);
        if (qq.multiSelect) { const k = cur.indexOf(oi); if (k >= 0) cur.splice(k, 1); else cur.push(oi); } else { cur.splice(0, cur.length, oi); }
        drawMessages();
      };
    });
    el.querySelectorAll('[data-other]').forEach(i => {
      i.oninput = () => { T.others[i.dataset.other] = T.others[i.dataset.other] || {}; T.others[i.dataset.other][+i.dataset.qi] = i.value; };
    });
    el.querySelectorAll('[data-q-send]').forEach(b => {
      b.onclick = async () => {
        const rid = b.dataset.qSend;
        const m = T.st.chat.messages.find(x => x.rid === rid);
        const answers = {};
        (m.questions || []).forEach((qq, qi) => {
          const other = ((T.others[rid] || {})[qi] || '').trim();
          const picked = ((T.picks[rid] || {})[qi] || []).map(oi => ((qq.options || [])[oi] || {}).label).filter(Boolean);
          const val = other || picked.join(', ');
          if (val) answers[qq.question] = val;
        });
        if (!Object.keys(answers).length) return toast('Chọn hoặc nhập câu trả lời', 'error');
        const r = await call('tvc_chat_answer', rid, { answers });
        if (r) { T.st = r.state; drawHead(); drawMessages(); drawBar(); }
      };
    });
    const pubMsg = rid => T.st.chat.messages.find(x => x.rid === rid);
    el.querySelectorAll('[data-pub-cap]').forEach(i => { i.oninput = () => { pubVal(pubMsg(i.dataset.pubCap)).caption = i.value; }; });
    el.querySelectorAll('[data-pub-page]').forEach(s => { s.onchange = () => { pubVal(pubMsg(s.dataset.pubPage)).page_id = s.value; drawMessages(true); }; });
    el.querySelectorAll('[data-pub-kind]').forEach(b => { b.onclick = () => { pubVal(pubMsg(b.dataset.pubKind)).kind = b.dataset.k; drawMessages(true); }; });
    el.querySelectorAll('[data-pub-go]').forEach(b => {
      b.onclick = async () => {
        const rid = b.dataset.pubGo, go = b.dataset.go === '1';
        const v = pubVal(pubMsg(rid));
        if (go) {
          if (!v.page_id) return toast('Chọn Fanpage', 'error');
          if (!v.caption.trim()) return toast('Nội dung bài trống', 'error');
          const page = ((pubMsg(rid).card || {}).pages || []).find(p => p.id === v.page_id) || {};
          if (!confirm(`Đăng bài lên Fanpage “${page.name || v.page_id}” ngay bây giờ?`)) return;
        }
        const r = await call('tvc_chat_answer', rid, { publish: go, ...v });
        if (r) { T.st = r.state; drawHead(); drawMessages(true); drawBar(); }
      };
    });
    bindAds(el.querySelector('.tvcc-msgs'));
    el.querySelectorAll('[data-goto-eval]').forEach(b => {
      b.onclick = () => { T.ptab = 'eval'; saveTab(); T.proj = null; loadProject(); };
    });
    el.querySelectorAll('[data-act]').forEach(b => {
      b.onclick = () => { const id = b.dataset.act; if (T.open.has(id)) T.open.delete(id); else T.open.add(id); drawMessages(); };
    });
    el.querySelectorAll('[data-tool-open]').forEach(t => {
      t.onclick = () => { const id = t.dataset.toolOpen; if (T.openTool.has(id)) T.openTool.delete(id); else T.openTool.add(id); drawMessages(); };
    });
    el.querySelectorAll('.tvcc-msgs [data-zoom]').forEach(i => { i.onclick = () => zoom(i.dataset.zoom); });
    el.querySelectorAll('[data-sug]').forEach(b => {
      b.onclick = () => { const i = q('[data-input]'); i.value = b.dataset.sug; i.focus(); i.oninput(); };
    });
  }

  function bindAds(box) {
    if (!box) return;
    box.querySelectorAll('[data-ad-open]').forEach(b => {
      b.onclick = () => {
        if (window.AdBotPage && window.AdBotPage.openPlan) window.AdBotPage.openPlan(b.dataset.adOpen);
        else navigate('adbot');
      };
    });
    box.querySelectorAll('[data-ad-cancel]').forEach(b => {
      b.onclick = async () => {
        if (!confirm('Huỷ yêu cầu quảng cáo này? (xoá kế hoạch chờ duyệt — chưa có gì trên Facebook)')) return;
        const r = await call('tvc_ad_cancel', b.dataset.adCancel);
        if (r) { toast('Đã huỷ yêu cầu quảng cáo', 'ok'); T.proj = null; loadProject(); }
      };
    });
  }

  function bindProject() {
    const el = root();
    const sel = el.querySelector('[data-proj]');
    if (sel) sel.onchange = () => { T.projName = sel.value; T.proj = null; loadProject(); };
    el.querySelectorAll('.tvcc-proj [data-pbrowse]').forEach(b => {
      b.onclick = async () => {  // xem dự án khác: chỉ xem, không gắn vào hội thoại
        const d = await call('tvc_list');
        if (d) T.projects = d.projects;
        T.browse = true;
        if (!T.projects.some(p => p.name === T.projName)) T.projName = T.projects.length ? T.projects[0].name : '';
        T.proj = null; loadProject();
      };
    });
    el.querySelectorAll('.tvcc-proj [data-pback]').forEach(b => {
      b.onclick = () => { T.browse = false; T.projName = (curChat() || {}).project || ''; T.proj = null; loadProject(); };
    });
    const ref = el.querySelector('[data-prefresh]');
    if (ref) ref.onclick = async () => { const d = await call('tvc_list'); if (d) T.projects = d.projects; T.proj = null; loadProject(); };
    el.querySelectorAll('[data-ptab]').forEach(b => { b.onclick = () => { T.ptab = b.dataset.ptab; saveTab(); drawProject(); }; });
    el.querySelectorAll('[data-popen]').forEach(b => { b.onclick = () => call('tvc_open', T.projName, b.dataset.popen); });
    el.querySelectorAll('.tvcc-proj [data-zoom]').forEach(i => { i.onclick = () => zoom(i.dataset.zoom); });
    bindAds(el.querySelector('.tvcc-proj'));
    el.querySelectorAll('.tvcc-proj [data-sug]').forEach(b => {
      b.onclick = () => { const i = q('[data-input]'); i.value = b.dataset.sug; i.focus(); i.oninput(); };
    });
  }

  function bindBar() {
    const el = root();
    const on = (sel, fn) => el.querySelectorAll(sel).forEach(b => { b.onclick = () => fn(b); });
    on('[data-send]', () => send());
    on('[data-stop]', async () => { await call('tvc_chat_stop'); });
    on('[data-up]', async b => {
      const files = await api('pick_files', 'images_multi');
      if (!files || !files.length) return;
      const r = await call('tvc_chat_upload', b.dataset.up, files);
      if (!r) return;
      r.files.forEach(path => T.attach.push({ kind: b.dataset.up, path }));
      drawBar();
      q('[data-input]').focus();
    });
    on('[data-att-del]', b => { T.attach.splice(+b.dataset.attDel, 1); drawBar(); });
    on('[data-auto-form]', async () => {
      T.af.show = !T.af.show;
      if (T.af.show) {
        const r = await call('tvc_auto_meta');
        if (r) T.af.meta = r.meta;
      }
      drawBar(); drawAuto();
    });
    on('[data-auto-off]', async () => {
      if (!confirm('Tắt tự động? Lượt đang chạy vẫn tiếp tục nhưng các bước sau sẽ hỏi lại bạn (muốn dừng hẳn bấm ⏹ Dừng).')) return;
      const r = await call('tvc_auto_stop');
      if (r) { T.st = r.state; drawHead(); drawMessages(); drawBar(); }
    });
  }

  function bindHead() {
    const el = root();
    const on = (sel, fn) => el.querySelectorAll(sel).forEach(b => { b.onclick = () => fn(b); });
    const busy = () => T.st && T.st.running;
    on('[data-new]', async () => {
      if (busy() && !confirm('Claude đang làm — mở hội thoại mới sẽ đóng phiên hiện tại. Tiếp tục?')) return;
      const r = await call('tvc_chat_new');
      if (r) { T.st = r.state; T.picks = {}; T.others = {}; syncChat(); drawHead(); drawSteps(); drawMessages(true); drawBar(); }
    });
    on('[data-del]', async () => {
      if (!confirm('Xoá hội thoại này khỏi app? (thư mục dự án giữ nguyên)')) return;
      const r = await call('tvc_chat_delete', T.st.chat.id);
      if (!r) return;
      T.chats = r.chats;
      const s = await call('tvc_chat_state');
      if (s) T.st = s.state;
      syncChat();
      drawHead(); drawMessages(true); drawBar();
    });
    on('[data-hist]', () => {
      T.showHist = !T.showHist;
      try { localStorage.setItem('tvcHistOpen', T.showHist ? '1' : '0'); } catch { /* không lưu được → chỉ trong phiên */ }
      drawHead();
    });
    on('[data-hist-hidden]', () => { T.showHidden = !T.showHidden; drawHead(); });
    el.querySelectorAll('[data-chat-hide]').forEach(b => {
      b.onclick = async e => {
        e.stopPropagation();  // không mở hội thoại
        const r = await call('tvc_chat_hide', b.dataset.chatHide, b.dataset.h === '1');
        if (r) { T.chats = r.chats; drawHead(); }
      };
    });
    el.querySelectorAll('[data-chat-open]').forEach(c => {
      c.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); c.click(); } };
    });
    on('[data-chat-open]', async b => {
      if (busy() && !confirm('Claude đang làm — mở hội thoại khác sẽ đóng phiên hiện tại. Tiếp tục?')) return;
      const r = await call('tvc_chat_open', b.dataset.chatOpen);
      if (!r) return;
      T.st = r.state; T.picks = {}; T.others = {};
      syncChat();
      drawHead(); drawMessages(true); drawBar();
    });
    on('[data-cfg]', async () => {
      T.showCfg = !T.showCfg;
      if (T.showCfg) { const r = await call('tvc_settings_get'); if (r) T.cfg = r; }
      drawHead();
    });
    on('[data-pick-root]', async () => { const r = await call('tvc_pick_root'); if (r) { T.cfg = r; drawHead(); } });
    on('[data-cfg-save]', async () => {
      const values = {};
      el.querySelectorAll('[data-c]').forEach(i => { values[i.dataset.c] = i.value; });
      const r = await call('tvc_settings_save', values);
      if (r) { T.cfg = r; T.showCfg = false; toast('Đã lưu — áp dụng cho phiên Claude mới', 'ok'); show(); }
    });
  }

  /* ---------------------------------------------------------------- sự kiện từ Python */
  let projTimer = null;
  function refreshProjectSoon() {
    clearTimeout(projTimer);
    projTimer = setTimeout(async () => {
      const d = await api('tvc_list').catch(() => null);
      if (d && d.ok) T.projects = d.projects;
      loadProject();
    }, 1500);
  }

  function update(event, data) {
    if (!data || !T.st) return;
    const chat = T.st.chat;
    const here = state.view === 'tvc';
    if (event === 'tvc_chat') {
      if (!chat || data.chat !== chat.id) return;
      const i = chat.messages.findIndex(m => m.id === data.msg.id);
      if (i >= 0) chat.messages[i] = data.msg; else chat.messages.push(data.msg);
      if (here) drawMessages();
      if (data.msg.role === 'tool' && data.msg.status && data.msg.status !== 'running' && here) refreshProjectSoon();
      return;
    }
    if (event === 'tvc_chat_state') {
      Object.assign(T.st, { running: data.running, connected: data.connected, pending: data.pending });
      if (chat && data.project) chat.project = data.project;
      if (here) { drawHead(); drawSteps(); drawMessages(); drawBar(); }
      return;
    }
    if (event === 'tvc_chat_project' && chat && data.chat === chat.id) {
      if (data.project) chat.project = data.project;
      if (data.projects) chat.projects = data.projects;
      if (!T.browse && data.project && T.projName !== data.project) { T.projName = data.project; T.proj = null; }
      if (here) drawProject();
      refreshProjectSoon();
    }
  }

  window.TvcPage = { show, update };
})();
