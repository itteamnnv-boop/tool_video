/* 🎯 Trợ lý nuôi kênh — trình bày kiểu Chiến dịch: Claude (trình duyệt) làm theo SKILL điều phối (📘 sửa được), hướng dẫn
   bạn cung cấp thông tin (băng "⏳ cần thêm thông tin" + câu hỏi), điền dần 📋 Hồ sơ; đủ thông tin → ▶ Chạy quy trình hoàn
   chỉnh Ảnh → Video → Hậu kỳ → Đăng bài trên bảng Canvas riêng của kênh. Dải chặng, kết quả từng chặng, duyệt bài đăng,
   chỗ còn thiếu (VD Fanpage) đều trên màn này. Dùng class camp-* (campaign.css) + .cv-as-* (canvas.css).
   Helper của app.js: $, api, esc, toast, state, navigate, openSettings. Sự kiện: canvas_assist / canvas_flow / canvas_node. */
(() => {
  'use strict';

  const C = { list: [], cid: '', board: null, chat: null, fields: null, tab: 'brief', sending: false, status: '', files: [],
    attach: true, build: false, draft: '', answer: '', autoOpen: false, issues: null, pages: null, reload: null };
  const root = () => $('#channelBody');
  const QUICK = [
    ['🚀 Bắt đầu việc mới', 'Tôi muốn làm nội dung mới cho kênh. Hãy hướng dẫn tôi cung cấp những thông tin cần thiết theo skill.'],
    ['📋 Tổng hợp hồ sơ', 'Tổng hợp lại toàn bộ hồ sơ yêu cầu đã trao đổi, chỉ ra còn thiếu gì trước khi chạy.'],
    ['💡 Gợi ý phương án', 'Gợi ý 2–3 phương án ý tưởng cho việc này (hook 3 giây đầu, góc nhìn, thông điệp) và khuyên chọn 1.'],
    ['📊 Đánh giá kết quả', 'Đánh giá kết quả lần chạy gần nhất theo hồ sơ đã chốt: chấm từng khối, chỉ lỗi cụ thể, đề xuất sửa và chạy lại đúng khối cần làm lại.'],
  ];
  const BUILD_MSG = 'Hồ sơ đã đủ — hãy dựng TOÀN BỘ quy trình theo hồ sơ (ảnh → video → hậu kỳ → caption → đăng bài), dùng đúng các node tài nguyên đã có, rồi cho chạy.';
  const TABS = [['brief', '📋 Hồ sơ'], ['chat', '💬 Trao đổi'], ['images', '🖼 Ảnh'], ['videos', '🎬 Video & hậu kỳ'], ['post', '📣 Đăng bài']];
  const STEPS = [['info', 'Thu thập thông tin', 'brief'], ['plan', 'Kế hoạch & dựng', 'chat'], ['images', 'Ảnh', 'images'],
    ['videos', 'Video', 'videos'], ['edit', 'Hậu kỳ', 'videos'], ['post', 'Đăng bài', 'post']];
  const STEP_ST = { pending: 'Chờ', running: 'Đang chạy', done: 'Xong', error: 'Lỗi', waiting: 'Chờ bạn', skipped: 'Không dùng' };
  const RUN_ST = { running: ['run', '⏳ Đang chạy'], done: ['ok', '✓ Xong'], partial: ['warn', '◐ Xong một phần'],
    error: ['bad', '✗ Có lỗi'], cancelled: ['', '⏹ Đã dừng'] };
  const NODE_ST = { idle: 'chưa chạy', queued: '⏳ chờ', running: '▶ đang chạy', done: '✓ xong', error: '✗ lỗi', skipped: '↷ bỏ qua',
    waiting: '✋ chờ bạn duyệt' };
  const AUTO_ST = { reviewing: ['run', '⏳ Đang chấm'], reworking: ['run', '🔁 Đang làm lại'], passed: ['ok', '✓ Đạt'],
    failed: ['bad', '✗ Chưa đạt'], stopped: ['', '⏹ Đã dừng'] };
  const RES = n => n.kind === 'upload' || n.wtype === 'input_video';
  const IS = { images: n => n.kind === 'image', videos: n => n.kind === 'video', edit: n => n.wtype === 'post_video' || n.wtype === 'concat_video',
    caption: n => ['content_post', 'ai_text', 'web_research'].includes(n.wtype), post: n => ['fb_post', 'fb_schedule'].includes(n.wtype) };

  const band = d => (d == null ? '' : d >= 8 ? 'good' : d >= 5 ? 'mid' : 'bad');
  const nodes = () => (C.board ? C.board.nodes : []);
  const nodeOf = id => nodes().find(n => n.id === id);
  const titleOf = n => (n ? n.title || n.wtype || n.kind : '');
  const iconOf = n => (!n ? '•' : n.kind === 'wf' ? ({ post_video: '🎞', concat_video: '⧉', fb_post: '📣', fb_schedule: '🗓', content_post: '📝',
    ai_text: '✦', web_research: '🌐', input_video: '🎞', input_text: '✎' }[n.wtype] || '⚙') : { image: '🖼', upload: '⬆', video: '🎬' }[n.kind] || '•');
  const isVid = u => /\.(mp4|mov|webm|m4v)(\?|$)/i.test(u);
  const stamp = at => String(at || '').replace('T', ' ');  // giờ tin nhắn ("…T10:00") và lần chạy Canvas ("… 10:00") cùng dạng
  const lastRun = () => { const r = (C.board && C.board.runs) || []; return r[r.length - 1] || null; };
  const running = () => ((C.board && C.board.runs) || []).some(r => r.status === 'running');

  function noteHtml(text) {
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>').replace(/`(.+?)`/g, '<code>$1</code>');
    const out = [];
    let list = false;
    String(text || '').split('\n').forEach(line => {
      const li = /^\s*(?:[-*•]|\d+[.)])\s+(.*)/.exec(line);
      if (li) { if (!list) { out.push('<ul>'); list = true; } out.push(`<li>${inline(li[1])}</li>`); return; }
      if (list) { out.push('</ul>'); list = false; }
      const h = /^(#{1,3})\s+(.*)/.exec(line);
      out.push(h ? `<h${h[1].length + 3}>${inline(h[2])}</h${h[1].length + 3}>` : line.trim() ? `<p>${inline(line)}</p>` : '');
    });
    if (list) out.push('</ul>');
    return out.join('');
  }

  async function call(name, ...args) {
    const res = await api(name, ...args);
    if (!res || !res.ok) { toast((res && res.error) || 'Lỗi', 'error'); return null; }
    return res;
  }

  /* ---------------------------------------------------------------- hồ sơ yêu cầu (Claude điền dần) */
  function brief() {
    const msgs = ((C.chat && C.chat.messages) || []).filter(m => m.role === 'assistant' && m.brief);
    const fields = {};
    msgs.forEach(m => Object.entries(m.brief.fields || {}).forEach(([k, v]) => { if (String(v).trim()) fields[k] = v; else if (!(k in fields)) fields[k] = ''; }));
    const last = msgs[msgs.length - 1];
    const lastBot = [...((C.chat && C.chat.messages) || [])].reverse().find(m => m.role === 'assistant' && !m.error);
    return { fields, missing: last ? last.brief.missing || [] : [], ready: !!(last && last.brief.ready), started: msgs.length > 0, lastBot };
  }

  const filled = v => { const s = String(v || '').trim().toLowerCase(); return s && !['chưa có', 'chưa rõ', '?'].includes(s); };

  /* ---------------------------------------------------------------- trạng thái chặng / tổng */
  function groupState(list) {
    if (!list.length) return 'pending';
    const st = list.map(n => n.status || 'idle');
    if (st.includes('error')) return 'error';
    if (st.includes('waiting')) return 'waiting';
    if (st.some(s => s === 'running' || s === 'queued')) return 'running';
    if (st.every(s => s === 'done')) return 'done';
    return 'pending';
  }

  function stepState(key, b) {
    const pipe = nodes().filter(n => !RES(n));
    if (key === 'info') return b.ready || pipe.length ? 'done' : b.started ? 'waiting' : 'pending';
    if (key === 'plan') return pipe.length ? 'done' : b.ready ? 'waiting' : 'pending';
    const list = key === 'post' ? nodes().filter(n => IS.post(n) || IS.caption(n)) : nodes().filter(IS[key]);
    if (!list.length) return pipe.length ? 'skipped' : 'pending';
    return groupState(list);
  }

  function overall(b) {
    if (nodes().some(n => n.status === 'waiting')) return ['waiting', 'Chờ bạn duyệt'];
    if (running()) return ['running', 'Đang chạy'];
    if (C.issues) return ['waiting', 'Cần bổ sung'];
    const r = lastRun();
    if (r && r.status === 'done') return ['done', 'Hoàn tất'];
    if (r && ['error', 'partial'].includes(r.status)) return ['error', 'Có lỗi'];
    if (b.ready) return ['approved', 'Sẵn sàng chạy'];
    return ['', b.started ? 'Đang thu thập thông tin' : 'Mới tạo'];
  }

  /* ---------------------------------------------------------------- danh sách kênh */
  async function show() {
    if (!C.fields) { const m = await call('ch_meta'); if (m) C.fields = m.brief_fields; }
    if (C.cid) return open(C.cid);
    await loadList();
  }

  async function loadList() {
    const res = await call('ch_list');
    if (!res) return;
    C.list = res.channels;
    C.cid = '';
    C.board = null;
    root().innerHTML = `<div class="ch-head"><div><small class="eyebrow">TRỢ LÝ NUÔI KÊNH</small><h2>Chiến dịch nội dung của kênh</h2>
        <p class="muted">Bạn chỉ giao việc — <b>Claude</b> (claude.ai trên trình duyệt) làm theo <b>skill điều phối</b>: hướng dẫn bạn cung cấp
        thông tin (ảnh sản phẩm, nhân vật, góc máy, lời thoại, Fanpage…), điền <b>hồ sơ yêu cầu</b>, đủ thông tin thì <b>chạy trọn quy trình</b>
        Ảnh → Video → Hậu kỳ → Đăng bài. Bài đăng luôn chờ bạn duyệt.</p></div>
        <div class="ch-head-acts"><button class="btn ghost" type="button" data-ch-skill>📘 Skill điều phối</button>
          <button class="btn primary" type="button" data-ch-new>＋ Chiến dịch mới</button></div></div>
      <div class="ch-grid">${C.list.map(c => `<button class="ch-card" type="button" data-ch-open="${esc(c.id)}">
          <div class="ch-cover">${c.thumb ? `<img src="${esc(c.thumb)}" alt="">` : '<span>🎯</span>'}</div>
          <b>${esc(c.name)}</b><small class="muted">${c.nodes} khối · ${c.runs} lần chạy${c.running ? ' · <span class="ch-live">đang chạy</span>' : ''}</small></button>`).join('')
        || '<div class="ch-empty muted">Chưa có chiến dịch nào — bấm <b>＋ Chiến dịch mới</b>, Claude sẽ hướng dẫn bạn cung cấp thông tin.</div>'}</div>`;
    root().querySelector('[data-ch-new]').onclick = async () => {
      const res2 = await call('ch_create', '');
      if (!res2) return;
      C.tab = 'brief';
      await open(res2.board.id);  // băng "Bắt đầu" hướng dẫn bước đầu — chưa tự gửi gì cho Claude (không tốn lượt)
    };
    root().querySelector('[data-ch-skill]').onclick = () => openSkill();
    root().querySelectorAll('[data-ch-open]').forEach(b => { b.onclick = () => { C.tab = 'brief'; open(b.dataset.chOpen); }; });
  }

  async function open(cid) {
    const [b, a] = await Promise.all([api('canvas_open', cid), api('canvas_assist_get', cid)]);
    if (!b || !b.ok || !a || !a.ok) { toast((b && b.error) || (a && a.error) || 'Không mở được chiến dịch', 'error'); return loadList(); }
    if (C.cid !== cid) Object.assign(C, { files: [], draft: '', answer: '', status: '', issues: null });
    C.cid = cid;
    C.board = b.board;
    C.chat = a.chat;
    C.sending = !!a.chat.busy;
    render();
  }

  /* ---------------------------------------------------------------- 1 chiến dịch */
  function render() {
    const box = root();
    const keep = saveInputs();
    const b = brief();
    const [cls, label] = overall(b);
    box.innerHTML = `<div class="camp-detail-head">
        <button class="btn ghost" type="button" data-ch-back>← Danh sách</button>
        <div class="camp-title"><input class="ch-name" data-ch-name value="${esc(C.board.name)}" maxlength="80" title="Tên chiến dịch — sửa trực tiếp">
          <small class="mono">${nodes().filter(n => !RES(n)).length} khối · ${(C.board.runs || []).length} lần chạy</small></div>
        <span class="camp-st big ${cls}">${esc(label)}</span>
        <div class="row camp-actions">
          ${running() ? '<button class="btn danger sm" type="button" data-ch-cancel>■ Dừng</button>'
            : `<button class="btn primary sm" type="button" data-ch-full ${b.ready || nodes().some(n => !RES(n)) ? '' : 'disabled title="Claude chưa xác nhận đủ thông tin — trả lời các câu hỏi trước"'}>▶ Chạy quy trình hoàn chỉnh</button>`}
          <button class="btn ghost sm" type="button" data-ch-skill>📘 Skill</button>
          <button class="btn ghost sm" type="button" data-ch-canvas title="Xem / sửa quy trình đã dựng trên Canvas">🗺 Canvas</button>
          <button class="btn ghost sm" type="button" data-ch-del>Xoá</button></div></div>
      <div class="camp-steps">${STEPS.map(([k, name, tab], i) => {
        const st = stepState(k, b);
        return `<button class="camp-step ${st}" type="button" data-go-tab="${tab}"><i>${st === 'done' ? '✓' : st === 'error' ? '!' : st === 'waiting' ? '⏳' : st === 'skipped' ? '–' : i + 1}</i>
          <span>${esc(name)}</span><small>${esc(STEP_ST[st] || st)}</small></button>`;
      }).join('')}</div>
      ${bannerHtml(b)}
      <div class="camp-detail-body">
        <div class="camp-main">
          <div class="camp-tabs">${TABS.map(([k, l]) => `<button class="camp-tab ${C.tab === k ? 'on' : ''}" type="button" data-tab="${k}">${l}${tabCount(k)}</button>`).join('')}</div>
          <div class="camp-panel ch-panel">${tabHtml(b)}</div>
        </div>
        <aside class="camp-side">${sideHtml()}</aside>
      </div>`;
    restoreInputs(keep);
    bind();
  }

  function tabCount(k) {
    const n = k === 'images' ? nodes().filter(IS.images).length : k === 'videos' ? nodes().filter(x => IS.videos(x) || IS.edit(x)).length
      : k === 'post' ? nodes().filter(x => IS.post(x) || IS.caption(x)).length : k === 'chat' ? ((C.chat && C.chat.messages) || []).length : 0;
    return n ? ` <span class="mono">${n}</span>` : '';
  }

  /* ---- băng thông báo (giống Chiến dịch): việc bạn cần làm ngay */
  function bannerHtml(b) {
    const wait = nodes().find(n => n.status === 'waiting' && n.approval);
    if (wait) {
      return `<div class="camp-banner warn"><div><b>✋ Bài đăng “${esc(titleOf(wait))}” chờ bạn duyệt</b> — kiểm tra ảnh / video và caption trước khi đăng.</div>
        <button class="btn primary sm" type="button" data-go-tab="post">Xem &amp; duyệt</button></div>`;
    }
    if (C.issues) return issuesHtml();
    if (C.sending) {
      return `<div class="camp-banner"><div class="row"><span class="cv-spin"></span><b data-ch-status>${esc(C.status || 'Claude đang trả lời…')}</b></div></div>`;
    }
    if (running()) {
      const r = lastRun();
      const ids = Object.keys(r.nodes || {});
      return `<div class="camp-banner"><div class="row"><span class="cv-spin"></span><b>Đang chạy quy trình</b>
        <span class="muted">${ids.filter(id => r.nodes[id] === 'done').length}/${ids.length} khối xong${r.current ? ` · đang làm “${esc(titleOf(nodeOf(r.current)))}”` : ''}</span></div></div>`;
    }
    const r = lastRun();
    if (r && r.status === 'done') {
      return `<div class="camp-banner ok"><div><b>✓ Quy trình hoàn chỉnh đã chạy xong.</b> Xem kết quả ở các tab, nhờ Claude đánh giá hoặc giao việc mới.</div>
        <div class="row"><button class="btn ghost sm" type="button" data-q="3">📊 Nhờ Claude đánh giá</button><button class="btn ghost sm" type="button" data-q="0">🚀 Việc mới</button></div></div>`;
    }
    if (r && ['error', 'partial'].includes(r.status)) {
      const bad = Object.keys(r.nodes || {}).filter(id => r.nodes[id] === 'error').map(id => nodeOf(id)).filter(Boolean);
      return `<div class="camp-banner bad"><div><b>Lần chạy có lỗi:</b> ${bad.map(n => `${esc(titleOf(n))} — ${esc(n.error || 'lỗi')}`).join('; ') || 'xem tab kết quả'}</div>
        <div class="row"><button class="btn ghost sm" type="button" data-ask-errors>🤖 Nhờ Claude sửa</button><button class="btn primary sm" type="button" data-ch-run>▶ Chạy tiếp</button></div></div>`;
    }
    if (b.ready) {
      return `<div class="camp-banner ok"><div><b>✓ Đã đủ thông tin.</b> ${nodes().some(n => !RES(n)) ? 'Quy trình đã dựng — bấm chạy để tạo ảnh, video, hậu kỳ và bài đăng.'
        : 'Claude sẽ dựng toàn bộ quy trình theo hồ sơ rồi chạy.'}</div>
        <button class="btn primary sm" type="button" data-ch-full>▶ Chạy quy trình hoàn chỉnh</button></div>`;
    }
    const bot = b.lastBot;
    if (!bot) {
      return `<div class="camp-banner warn"><div><b>⏳ Bắt đầu:</b> nhờ Claude hướng dẫn những thông tin cần cung cấp, hoặc mô tả ngay việc bạn muốn làm ở ô bên dưới.</div>
        <button class="btn primary sm" type="button" data-q="0">🚀 Bắt đầu</button></div>${answerBox('Mô tả việc cần làm — VD: Video Reels giới thiệu phân bón Boss 1, nhân vật em Linh, đăng Fanpage tối nay')}`;
    }
    return `<div class="camp-banner warn col"><b>⏳ Claude cần thêm thông tin</b>
      ${bot.text ? `<details class="ch-bot-say" ${b.missing.length ? '' : 'open'}><summary>💬 Claude nói…</summary><div class="cv-as-msg bot">${noteHtml(bot.text)}</div></details>` : ''}
      ${b.missing.length ? `<ol class="camp-questions">${b.missing.map(q => `<li>${esc(q)}</li>`).join('')}</ol>` : ''}
      ${answerBox('Trả lời từng câu (VD: 1. 3 cảnh, dọc 9:16  2. Giọng nữ miền Nam…) — đính kèm ảnh sản phẩm / nhân vật nếu được hỏi')}</div>`;
  }

  function answerBox(placeholder) {
    return `<div class="ch-answer"><textarea data-ch-answer rows="3" placeholder="${esc(placeholder)}"></textarea>
      <div class="cv-as-files">${C.files.map((f, i) => `<span class="cv-as-file" title="${esc(f.path)}">📄 ${esc(f.name)}<button type="button" data-unfile="${i}" title="Bỏ file này">✕</button></span>`).join('')}
        <button class="link-btn" type="button" data-files title="Ảnh / video: thêm vào chiến dịch làm tài nguyên (sản phẩm, nhân vật, góc máy…) và gửi Claude xem. Tài liệu .txt .md .docx…: đọc thành chữ.">📎 Đính kèm ảnh / video / tài liệu</button></div>
      <div class="row"><span class="cv-sp"></span><button class="btn primary sm" type="button" data-ch-answer-send>Gửi câu trả lời ➤</button></div></div>`;
  }

  function issuesHtml() {
    const items = C.issues.items;
    const pages = (C.pages || {}).pages || [];
    return `<div class="camp-banner warn col"><b>⚠ Cần bổ sung trước khi chạy (${items.length})</b>
      ${items.map(i => {
        const n = nodeOf(i.node);
        const pick = /fanpage/i.test(i.message) && ['fb_post', 'fb_schedule'].includes(i.wtype);
        return `<div class="ch-issue"><span>${esc(iconOf(n))} <b>${esc(i.title || i.node)}</b> — ${esc(i.message)}</span>
          ${pick ? `<select data-ch-page="${esc(i.node)}"><option value="">— Chọn Fanpage —</option>${pages.map(p => `<option value="${esc(p.id)}" ${((n || {}).config || {}).page_id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
            ${pages.length ? '' : '<small>Chưa kết nối Facebook — vào Fanpage Facebook để kết nối</small>'}` : ''}</div>`;
      }).join('')}
      <div class="row"><button class="btn primary sm" type="button" data-ch-run>▶ Chạy lại</button>
        <button class="btn ghost sm" type="button" data-ask-issues>🤖 Nhờ Claude xử lý</button></div></div>`;
  }

  /* ---- các tab */
  function tabHtml(b) {
    if (C.tab === 'chat') return chatHtml();
    if (C.tab === 'images') return gridHtml(nodes().filter(IS.images), 'Chưa có ảnh — khi chạy quy trình, ảnh từng cảnh hiện ở đây.');
    if (C.tab === 'videos') return gridHtml(nodes().filter(n => IS.videos(n) || IS.edit(n)), 'Chưa có video — video từng cảnh và bản hậu kỳ hiện ở đây.');
    if (C.tab === 'post') return gridHtml(nodes().filter(n => IS.caption(n) || IS.post(n)), 'Chưa có caption / bài đăng.');
    const res = nodes().filter(RES);
    const keys = Object.keys(C.fields || {});
    const extra = Object.keys(b.fields).filter(k => !keys.includes(k));
    return `<div class="ch-brief">${[...keys, ...extra].map(k => {
        const v = b.fields[k];
        const ok = filled(v);
        return `<div class="ch-field ${ok ? 'ok' : 'miss'}"><div class="ch-field-head"><i>${ok ? '✓' : '!'}</i><b>${esc((C.fields || {})[k] || k)}</b></div>
          <div class="ch-field-val">${ok ? noteHtml(v) : '<span class="muted">Chưa có — Claude sẽ hỏi</span>'}</div></div>`;
      }).join('')}</div>
      <div class="ch-res"><div class="ch-row"><b>Tài nguyên đã cung cấp</b><small class="muted">${res.length} file</small><span class="cv-sp"></span>
        <button class="link-btn" type="button" data-files>📎 Thêm ảnh / video</button></div>
        <div class="ch-media">${res.map(n => (n.urls || []).length && !isVid(n.urls[0])
          ? `<figure><img src="${esc(n.urls[0])}" alt="" data-zoom="${esc(n.urls[0])}"><figcaption>${esc(n.id)} · ${esc(titleOf(n))}</figcaption></figure>`
          : `<figure><div class="ch-ph">🎞</div><figcaption>${esc(n.id)} · ${esc(titleOf(n))}</figcaption></figure>`).join('') || '<small class="muted">Chưa có — đính kèm ảnh sản phẩm / nhân vật / góc máy mẫu khi trả lời Claude.</small>'}</div>
        ${C.files.length ? '<small class="muted">File đã chọn sẽ gửi cùng câu trả lời / tin nhắn tiếp theo.</small>' : ''}</div>`;
  }

  function gridHtml(list, empty) {
    if (!list.length) return `<div class="empty">${empty}</div>`;
    return `<div class="ch-results">${list.map(n => nodeCard(n)).join('')}</div>`;
  }

  function nodeCard(n) {
    const urls = n.urls || [];
    const vids = urls.filter(isVid);
    const imgs = urls.filter(u => !isVid(u));
    const text = (n.out || {}).text;
    const st = n.status || 'idle';
    return `<div class="ch-node ${esc(st)}"><div class="ch-node-head"><span>${iconOf(n)}</span><b>${esc(titleOf(n))}</b><small class="muted">${esc(n.id)}</small>
        <span class="ch-node-st ${esc(st)}">${NODE_ST[st] || esc(st)}${st === 'running' && n.pct ? ` · ${Math.round(n.pct)}%` : ''}</span></div>
      ${n.error && st !== 'done' ? `<p class="ch-err">⚠ ${esc(n.error)}</p>` : ''}
      ${imgs.length ? `<div class="ch-media">${imgs.slice(0, 6).map(u => `<img src="${esc(u)}" alt="" data-zoom="${esc(u)}">`).join('')}</div>` : ''}
      ${vids.length ? `<div class="ch-media">${vids.slice(0, 2).map(u => `<video src="${esc(u)}" controls preload="metadata"></video>`).join('')}</div>` : ''}
      ${text ? `<details class="ch-text" data-k="txt-${esc(n.id)}" ${IS.caption(n) ? 'open' : ''}><summary>Xem chữ (${text.length} ký tự)</summary><pre>${esc(text)}</pre></details>` : ''}
      ${n.status === 'waiting' && n.approval ? approvalHtml(n) : ''}
      ${n.prompt ? `<details class="ch-text" data-k="pr-${esc(n.id)}"><summary>Prompt</summary><pre>${esc(n.prompt)}</pre></details>` : ''}</div>`;
  }

  function approvalHtml(n) {
    const a = n.approval || {};
    return `<div class="ch-approve" data-approve="${esc(n.id)}"><div><b>✋ Bài đăng chờ bạn duyệt</b>${a.page ? ` — Fanpage <b>${esc(a.page)}</b>` : ''}${a.post_type ? ` · ${esc(a.post_type)}` : ''}</div>
      ${(a.media_urls || []).length ? `<div class="ch-media">${a.media_urls.slice(0, 4).map(u => (isVid(u)
        ? `<video src="${esc(u)}" controls preload="metadata"></video>` : `<img src="${esc(u)}" alt="" data-zoom="${esc(u)}">`)).join('')}</div>` : ''}
      <textarea data-ap-caption rows="5">${esc(a.caption || '')}</textarea>
      <div class="row"><button class="btn primary sm" type="button" data-ap-ok>✓ Đồng ý đăng</button>
        <button class="btn ghost sm" type="button" data-ap-no>✗ Từ chối</button><small class="muted">Sửa caption trước khi đồng ý nếu cần.</small></div></div>`;
  }

  /* ---- tab Trao đổi: cuộc trò chuyện đầy đủ + đề xuất + lần chạy */
  function chatHtml() {
    const rows = (C.chat.messages || []).map(m => ({ at: stamp(m.at), m }));
    (C.board.runs || []).forEach((run, i, all) => rows.push({ at: stamp(run.at), run, latest: i === all.length - 1 }));
    rows.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
    return `<div class="ch-chat">
      <div class="cv-as-msgs">${rows.map(r => (r.m ? msgHtml(r.m) : runHtml(r.run, r.latest))).join('') || '<div class="cv-as-intro">Chưa có trao đổi.</div>'}</div>
      <div class="cv-as-quick">${QUICK.map(([l, t], i) => `<button type="button" data-q="${i}" title="${esc(t)}">${esc(l)}</button>`).join('')}
        <span class="cv-sp"></span><button type="button" data-chat-new title="Cuộc trò chuyện mới (Claude đọc lại skill + quy trình hiện tại)">⟲ Trò chuyện mới</button></div>
      <div class="cv-as-input"><textarea data-chat-input rows="2" placeholder="Nhắn Claude… (Ctrl+Enter để gửi)"></textarea>
        <div class="cv-as-row"><label class="cv-opt-check" title="Gửi ảnh kết quả + 1 khung hình mỗi video (tối đa 6) để Claude xem và chấm"><input type="checkbox" data-attach ${C.attach ? 'checked' : ''}> 📎 Kèm ảnh kết quả</label>
          <label class="cv-opt-check" title="Đề xuất của Claude được dựng ngay lên quy trình (không cần bấm Áp dụng). Không tự chạy."><input type="checkbox" data-build ${C.build ? 'checked' : ''}> 🧩 Dựng luôn</label>
          <button class="link-btn" type="button" data-files>📎 Đính kèm</button>
          <button class="link-btn cv-as-browser" type="button" data-browser>🖥 Trình duyệt: ${state.boot.settings.show_browser ? 'hiện' : 'ẩn'}</button>
          <span class="cv-sp"></span><button class="btn primary sm" type="button" data-chat-send ${C.sending ? 'disabled' : ''}>${C.sending ? 'Đang chờ…' : 'Gửi ➤'}</button></div></div></div>`;
  }

  function msgHtml(m) {
    if (m.role === 'user') {
      return `<div class="cv-as-msg user${m.auto ? ' auto' : ''}">${esc(m.text)}${m.images ? `<small>📎 kèm ${m.images} ảnh kết quả</small>` : ''}${(m.files || []).length ? `<small>📄 ${esc(m.files.join(', '))}</small>` : ''}${(m.kept || []).length ? `<small>📌 Đã thêm vào chiến dịch: ${m.kept.map(k => `${esc(k.node)} (${esc(k.name)})`).join(', ')}</small>` : ''}</div>`;
    }
    if (m.error) return `<div class="cv-as-msg err">⚠ ${esc(m.error)}</div>`;
    const ev = m.eval;
    const evHtml = ev ? `<div class="cv-as-eval">${ev.diem != null ? `<div class="cv-as-score ${band(ev.diem)}"><b>${ev.diem}</b><small>/10</small></div>` : ''}
      <div class="cv-as-eval-body">${ev.tom_tat ? `<p>${esc(ev.tom_tat)}</p>` : ''}${(ev.van_de || []).length ? `<ul>${ev.van_de.map(v => `<li>${esc(v)}</li>`).join('')}</ul>` : ''}
        ${(ev.node || []).length ? `<div class="cv-as-nodes">${ev.node.map(x => `<button type="button" class="${band(x.diem)}">${esc(iconOf(nodeOf(x.id)))} ${esc(titleOf(nodeOf(x.id)) || x.id)}${x.diem != null ? ` · ${x.diem}` : ''}<small>${esc(x.nhan_xet)}</small></button>`).join('')}</div>` : ''}</div></div>` : '';
    const auto = m.auto && m.auto.passed !== undefined ? `<div class="cv-as-auto-tag ${m.auto.passed ? 'ok' : 'bad'}">🤖 Tự chấm · <b>${m.auto.passed ? 'ĐẠT' : 'CHƯA ĐẠT'}</b>${m.auto.score != null ? ` · ${m.auto.score}/10` : ''}</div>` : '';
    const built = m.built ? `<div class="cv-as-built ${m.built.errors.length ? 'warn' : 'ok'}">🧩 Đã dựng ${m.built.done} thao tác${m.built.errors.length ? ` · ${m.built.errors.length} lỗi<ul>${m.built.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}</div>` : '';
    return `<div class="cv-as-msg bot">${auto}${m.text ? noteHtml(m.text) : ''}${evHtml}${built}${opsHtml(m)}</div>`;
  }

  function opsHtml(m) {
    const ops = m.ops || [];
    if (!ops.length) return m.dropped ? `<small class="muted">Bỏ ${m.dropped} đề xuất không hợp lệ</small>` : '';
    const pending = ops.filter(o => !o.applied && o.op !== 'run');
    return `<div class="cv-as-ops"><div class="cv-as-ops-head"><b>Đề xuất (${ops.length})</b><span class="cv-sp"></span>
        ${pending.length ? `<button class="btn ghost sm" type="button" data-as-all="${esc(m.id)}">Áp dụng tất cả</button>
          <button class="btn primary sm" type="button" data-as-buildrun="${esc(m.id)}">🧩 Dựng &amp; ▶ Chạy</button>` : ''}</div>
      <details class="ch-ops-list" data-k="ops-${esc(m.id)}" ${ops.length <= 5 ? 'open' : ''}><summary>${pending.length ? `${pending.length} thao tác chưa áp dụng` : 'Đã áp dụng hết'}</summary>
      ${ops.map((op, i) => `<div class="cv-as-op ${op.applied ? 'done' : ''}">
        <div class="cv-as-op-txt"><b>${esc(op.label)}</b>${op.ly_do ? `<small>${esc(op.ly_do)}</small>` : ''}
          ${op.prompt || op.text ? `<details><summary>Xem nội dung</summary><pre>${esc(op.prompt || op.text)}</pre></details>` : ''}</div>
        ${op.applied ? '<span class="cv-as-ok">✓</span>' : op.op === 'run' ? '<button class="btn ghost sm" type="button" data-ch-run>▶ Chạy</button>'
          : `<button class="btn primary sm" type="button" data-as-apply="${esc(m.id)}" data-i="${i}">Áp dụng</button>`}</div>`).join('')}</details></div>`;
  }

  function runHtml(run, latest) {
    const [cls, txt] = RUN_ST[run.status] || ['', run.status];
    const ids = Object.keys(run.nodes || {});
    return `<div class="ch-run ${latest ? cls : 'old'}"><div class="ch-run-head"><b>▶ ${esc(run.label || 'Chạy quy trình')}</b><span class="ch-run-st ${cls}">${txt}</span>
      <small class="muted">${ids.filter(id => run.nodes[id] === 'done').length}/${ids.length} khối · ${esc(stamp(run.at).slice(11, 16))}</small></div></div>`;
  }

  /* ---- cột phải: tiến độ + tự điều phối */
  function sideHtml() {
    const r = lastRun();
    const ids = r ? Object.keys(r.nodes || {}) : [];
    const a = { on: false, criteria: '', pass_score: 8, rounds: 2, attach: true, ...(C.chat.auto || {}) };
    const st = C.chat.auto_state || {};
    const [acls, atxt] = AUTO_ST[st.status] || ['', ''];
    return `<div class="card ch-progress"><div class="card-title">TIẾN ĐỘ LẦN CHẠY</div>
        ${r ? `<div class="ch-run-head"><b>${esc(r.label)}</b><span class="ch-run-st ${(RUN_ST[r.status] || [''])[0]}">${(RUN_ST[r.status] || ['', r.status])[1]}</span></div>
          ${ids.map(id => { const n = nodeOf(id); const s = n && n.status === 'waiting' ? 'waiting' : r.nodes[id];
            return n ? `<div class="ch-prog-row"><span>${iconOf(n)} ${esc(titleOf(n))}</span><span class="ch-node-st ${esc(s)}">${NODE_ST[s] || esc(s)}</span></div>` : ''; }).join('')}`
          : '<small class="muted">Chưa chạy lần nào.</small>'}</div>
      <div class="cv-as-auto ${a.on ? 'on' : ''}">
        <div class="cv-as-auto-head"><label class="cv-opt-check" title="Sau mỗi lần chạy, Claude chấm theo tiêu chí và tự giao khối chưa đạt làm lại">
            <input type="checkbox" data-auto-on ${a.on ? 'checked' : ''}> <b>🤖 Tự điều phối</b></label>
          ${a.on && atxt ? `<span class="cv-as-auto-st ${acls}">${atxt}</span>` : !a.on ? '<small class="muted">tắt</small>' : ''}
          <span class="cv-sp"></span>${['reviewing', 'reworking'].includes(st.status) ? '<button class="btn danger sm" type="button" data-auto-stop>⏹</button>' : ''}
          <button class="btn ghost sm" type="button" data-auto-edit>${C.autoOpen ? '▴' : '⚙ Tiêu chí'}</button></div>
        <div class="cv-as-auto-body ${C.autoOpen ? '' : 'hidden'}">
          <textarea data-auto-criteria rows="3" placeholder="Tiêu chí đạt — VD: đúng bao Boss 1 & logo; đúng khuôn mặt em Linh; phụ đề đúng chính tả; caption có giá + SĐT…">${esc(a.criteria)}</textarea>
          <div class="cv-as-row"><label>Đạt <select data-auto-score>${[6, 7, 8, 9].map(n => `<option value="${n}" ${Number(a.pass_score) === n ? 'selected' : ''}>${n}/10</option>`).join('')}</select></label>
            <label>Làm lại <select data-auto-rounds>${[1, 2, 3].map(n => `<option value="${n}" ${Number(a.rounds) === n ? 'selected' : ''}>${n} vòng</option>`).join('')}</select></label>
            <label class="cv-opt-check"><input type="checkbox" data-auto-attach ${a.attach ? 'checked' : ''}> 📎</label>
            <span class="cv-sp"></span><button class="btn primary sm" type="button" data-auto-save>Lưu</button></div>
          <small class="muted">Chạy xong → Claude chấm; khối chưa đạt được giao sửa và <b>tự chạy lại</b> (tốn lượt model). Không tự chạy lại khối Đăng bài.</small></div></div>`;
  }

  /* ---------------------------------------------------------------- giữ chữ đang gõ khi vẽ lại */
  function saveInputs() {
    const r = root();
    const get = sel => { const el = r.querySelector(sel); return el ? el.value : undefined; };
    const active = document.activeElement;
    const focus = active && r.contains(active) && active.tagName === 'TEXTAREA'
      ? { sel: active.hasAttribute('data-ch-answer') ? '[data-ch-answer]' : active.hasAttribute('data-chat-input') ? '[data-chat-input]' : '', a: active.selectionStart, b: active.selectionEnd } : null;
    const answer = get('[data-ch-answer]');
    const input = get('[data-chat-input]');
    if (answer !== undefined) C.answer = answer;
    if (input !== undefined) C.draft = input;
    const msgs = r.querySelector('.cv-as-msgs');
    return { focus, scroll: msgs ? [msgs.scrollTop, msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80] : null,
      open: [...r.querySelectorAll('details[data-k][open]')].map(d => d.dataset.k),
      closed: [...r.querySelectorAll('details[data-k]:not([open])')].map(d => d.dataset.k) };
  }

  function restoreInputs(k) {
    const r = root();
    const answer = r.querySelector('[data-ch-answer]');
    if (answer) answer.value = C.answer;
    const input = r.querySelector('[data-chat-input]');
    if (input) input.value = C.draft;
    k.open.forEach(key => { const d = r.querySelector(`details[data-k="${CSS.escape(key)}"]`); if (d) d.open = true; });
    k.closed.forEach(key => { const d = r.querySelector(`details[data-k="${CSS.escape(key)}"]`); if (d) d.open = false; });
    if (k.focus && k.focus.sel) { const el = r.querySelector(k.focus.sel); if (el) { el.focus(); el.setSelectionRange(k.focus.a, k.focus.b); } }
    const msgs = r.querySelector('.cv-as-msgs');
    if (msgs) msgs.scrollTop = !k.scroll || k.scroll[1] ? msgs.scrollHeight : k.scroll[0];
  }

  /* ---------------------------------------------------------------- sự kiện giao diện */
  function bind() {
    const r = root();
    const cid = C.cid;
    const on = (sel, fn) => r.querySelectorAll(sel).forEach(el => { el.onclick = e => fn(el, e); });
    on('[data-ch-back]', () => loadList());
    r.querySelector('[data-ch-name]').onchange = async e => { const res = await call('canvas_rename', cid, e.target.value); if (res) C.board = res.board; };
    on('[data-ch-full]', () => runFull());
    on('[data-ch-run]', () => runAll(false));
    on('[data-ch-cancel]', () => call('canvas_cancel_flow', cid));
    on('[data-ch-skill]', () => openSkill());
    on('[data-ch-canvas]', async () => { navigate('canvas'); await window.CanvasPage.show(); window.CanvasPage.openBoard(cid); });
    on('[data-ch-del]', async () => {
      if (!confirm(`Xoá chiến dịch “${C.board.name}” cùng quy trình, kết quả và cuộc trò chuyện?`)) return;
      if (await call('ch_delete', cid)) loadList();
    });
    on('[data-tab]', el => { saveInputs(); C.tab = el.dataset.tab; render(); });
    on('[data-go-tab]', el => { saveInputs(); C.tab = el.dataset.goTab; render(); });
    on('[data-q]', el => send(QUICK[+el.dataset.q][1], false, ''));
    on('[data-files]', async () => {
      const res = await call('canvas_assist_pick_files');
      if (!res || !res.files.length) return;
      saveInputs();
      const have = new Set(C.files.map(f => f.path));
      C.files = [...C.files, ...res.files.filter(f => !have.has(f.path))].slice(0, 8);
      render();
    });
    on('[data-unfile]', el => { saveInputs(); C.files.splice(+el.dataset.unfile, 1); render(); });
    on('[data-ch-answer-send]', () => { const ta = r.querySelector('[data-ch-answer]'); send(ta.value, false, 'answer'); });
    const ans = r.querySelector('[data-ch-answer]');
    if (ans) ans.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(ans.value, false, 'answer'); };
    const input = r.querySelector('[data-chat-input]');
    if (input) input.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(input.value, C.build, 'chat-input'); };
    on('[data-chat-send]', () => send(r.querySelector('[data-chat-input]').value, C.build, 'chat-input'));
    const att = r.querySelector('[data-attach]');
    if (att) att.onchange = e => { C.attach = e.target.checked; };
    const bld = r.querySelector('[data-build]');
    if (bld) bld.onchange = e => { C.build = e.target.checked; };
    on('[data-browser]', () => openSettings('browser'));
    on('[data-chat-new]', async () => {
      if ((C.chat.messages || []).length && !confirm('Bắt đầu cuộc trò chuyện mới? (Lịch sử trò chuyện và hồ sơ sẽ được xoá — quy trình, kết quả vẫn giữ)')) return;
      const res = await call('canvas_assist_clear', cid);
      if (res) { C.chat = res.chat; render(); }
    });
    on('[data-as-apply]', el => applyOps(el.dataset.asApply, [+el.dataset.i], false));
    on('[data-as-all]', el => applyOps(el.dataset.asAll, null, false));
    on('[data-as-buildrun]', el => applyOps(el.dataset.asBuildrun, null, true));
    on('[data-zoom]', el => zoom(el.dataset.zoom));
    on('[data-ask-issues]', () => send('Khi chạy, app báo quy trình còn thiếu:\n' + C.issues.items.map(i => `- ${i.title || i.node} (${i.node}): ${i.message}`).join('\n')
      + '\nHãy hướng dẫn tôi cung cấp thông tin cần thiết hoặc đề xuất sửa để chạy được.', false, ''));
    on('[data-ask-errors]', () => {
      const bad = nodes().filter(n => n.status === 'error');
      send('Lần chạy vừa rồi bị lỗi:\n' + bad.map(n => `- ${titleOf(n)} (${n.id}): ${n.error || 'lỗi'}`).join('\n') + '\nHãy giải thích ngắn và đề xuất sửa để chạy tiếp.', false, '');
    });
    r.querySelectorAll('[data-approve]').forEach(card => {
      const nid = card.dataset.approve;
      const decide = async ok => {
        const caption = card.querySelector('[data-ap-caption]').value;
        if (ok && !confirm('Đăng bài này lên Fanpage?')) return;
        const res = await call('canvas_approve', cid, nid, ok, caption);
        if (res) { toast(ok ? 'Đã đồng ý — app đang đăng bài' : 'Đã từ chối bài đăng', ok ? 'ok' : ''); scheduleReload(); }
      };
      card.querySelector('[data-ap-ok]').onclick = () => decide(true);
      card.querySelector('[data-ap-no]').onclick = () => decide(false);
    });
    r.querySelectorAll('[data-ch-page]').forEach(sel => {
      sel.onchange = async () => { if (await call('canvas_update_nodes', cid, [{ id: sel.dataset.chPage, config: { page_id: sel.value } }])) toast('Đã chọn Fanpage', 'ok'); };
    });
    bindAuto(r);
  }

  function autoForm(r) {
    return { criteria: r.querySelector('[data-auto-criteria]').value, pass_score: Number(r.querySelector('[data-auto-score]').value),
      rounds: Number(r.querySelector('[data-auto-rounds]').value), attach: r.querySelector('[data-auto-attach]').checked };
  }

  async function saveAuto(cfg, msg) {
    const res = await call('canvas_assist_auto', C.cid, cfg);
    if (res) { C.chat = res.chat; if (msg) toast(msg, 'ok'); }
    render();
  }

  function bindAuto(r) {
    const onBox = r.querySelector('[data-auto-on]');
    onBox.onchange = () => {
      const f = autoForm(r);
      if (!onBox.checked) return saveAuto({ on: false }, 'Đã tắt tự điều phối');
      if (!f.criteria.trim()) { onBox.checked = false; C.autoOpen = true; render(); return toast('Nhập tiêu chí đạt trước khi bật tự điều phối', 'warn'); }
      if (!confirm(`Bật TỰ ĐIỀU PHỐI?\n\nSau mỗi lần chạy, Claude chấm kết quả theo tiêu chí (đạt từ ${f.pass_score}/10). Khối chưa đạt sẽ được giao sửa và TỰ CHẠY LẠI — tối đa ${f.rounds} vòng, TỐN LƯỢT model.\n\nKhông tự chạy lại khối Đăng bài.`)) { onBox.checked = false; return; }
      saveAuto({ ...f, on: true }, 'Đã bật tự điều phối');
    };
    r.querySelector('[data-auto-save]').onclick = () => saveAuto(autoForm(r), 'Đã lưu tiêu chí');
    r.querySelector('[data-auto-edit]').onclick = () => { saveInputs(); C.autoOpen = !C.autoOpen; render(); };
    const stop = r.querySelector('[data-auto-stop]');
    if (stop) stop.onclick = async () => { const res = await call('canvas_assist_stop', C.cid); if (res) { C.chat = res.chat; render(); } };
  }

  /* ---------------------------------------------------------------- thao tác */
  async function send(text, build, from) {
    text = String(text || '').trim();
    if (!text || C.sending) return false;
    const cid = C.cid;
    const files = C.files;
    C.sending = true;
    C.status = build ? 'Claude đang dựng quy trình theo hồ sơ…' : 'Claude đang đọc và trả lời…';
    C.chat.messages = [...(C.chat.messages || []), { role: 'user', text, at: '9999', images: 0, files: files.map(f => f.name) }];
    if (from === 'answer') C.answer = '';
    if (from === 'chat-input') C.draft = '';
    C.files = [];
    C.build = false;
    render();
    const res = await api('ch_chat', cid, text, C.attach, files.map(f => f.path), !!build);
    if (C.cid !== cid) return false;  // đã rời chiến dịch này trong lúc chờ
    C.sending = false;
    let ok = !!(res && res.ok);
    if (ok) C.chat = res.chat;
    else {
      if (res && res.locked) toast(res.error, 'error'); else toast((res && res.error) || 'Lỗi', 'error');
      const again = await api('canvas_assist_get', cid);
      if (again && again.ok) C.chat = again.chat;
    }
    const b = await api('canvas_open', cid);  // đính kèm / dựng → quy trình đã đổi
    if (b && b.ok && C.cid === cid) C.board = b.board;
    render();
    return ok;
  }

  /** Áp dụng đề xuất (idxs = null: mọi đề xuất chưa áp dụng, khối mới trước) → (run) chạy cả quy trình. */
  async function applyOps(mid, idxs, run) {
    const m = (C.chat.messages || []).find(x => x.id === mid);
    if (!m) return false;
    const isAdd = o => o.op === 'add_node' || o.op === 'add_frame';
    const order = idxs || [...m.ops.keys()].filter(i => !m.ops[i].applied && m.ops[i].op !== 'run')
      .sort((a, b) => isAdd(m.ops[b]) - isAdd(m.ops[a]) || a - b);
    const errors = [];
    for (const i of order) {
      const res = await api('canvas_assist_apply', C.cid, mid, i);
      if (res && res.locked) { toast(res.error, 'error'); return false; }
      if (!res || !res.ok) { errors.push(`${m.ops[i].label}: ${(res && res.error) || 'lỗi'}`); continue; }
      C.board = res.result.board;
      C.chat = res.result.chat;
    }
    if (errors.length) toast(`${errors.length} đề xuất không áp dụng được: ${errors[0]}`, 'error');
    render();
    if (run) await runAll(false);
    return true;
  }

  /** ▶ Chạy quy trình hoàn chỉnh: chưa dựng → nhờ Claude dựng toàn bộ theo hồ sơ (Dựng luôn) → chạy; đã dựng → áp dụng
   *  đề xuất còn chờ (nếu có) → chạy. */
  async function runFull() {
    const pending = [...(C.chat.messages || [])].reverse().find(m => m.role === 'assistant' && (m.ops || []).some(o => !o.applied && o.op !== 'run'));
    if (!nodes().some(n => !RES(n))) {
      if (pending) return applyOps(pending.id, null, true);
      if (!await send(BUILD_MSG, true, '')) return;
      if (!nodes().some(n => !RES(n))) return toast('Claude chưa dựng được quy trình — xem tab Trao đổi', 'warn');
      return runAll(false);
    }
    if (pending && confirm('Claude còn đề xuất chưa áp dụng — áp dụng trước khi chạy?')) return applyOps(pending.id, null, true);
    return runAll(false);
  }

  async function runAll(fresh) {
    const res = await call('ch_run', C.cid, fresh);
    if (!res) return;
    if (res.issues.length) {
      if (!C.pages) { const p = await api('wf_fb_options'); C.pages = p && p.ok ? p : { pages: [] }; }
      C.issues = { items: res.issues };
      render();
      return;
    }
    C.issues = null;
    C.board = res.board;
    render();
  }

  function zoom(url) {
    const box = document.createElement('div');
    box.className = 'cv-lightbox';
    box.innerHTML = `<img src="${esc(url)}" alt=""><button class="btn ghost sm" type="button">✕ Đóng</button>`;
    box.onclick = e => { if (e.target === box || e.target.tagName === 'BUTTON') box.remove(); };
    document.body.appendChild(box);
  }

  /* ---------------------------------------------------------------- 📘 skill điều phối */
  async function openSkill() {
    const res = await call('ch_skill_get');
    if (!res) return;
    const box = document.createElement('div');
    box.className = 'ch-modal';
    box.innerHTML = `<div class="ch-modal-card"><div class="ch-row"><b>📘 Skill điều phối của Claude</b>
        <small class="ch-skill-tag ${res.skill.custom ? 'custom' : ''}">${res.skill.custom ? 'bản bạn đã sửa' : 'bản mặc định'}</small><span class="cv-sp"></span>
        <button class="btn ghost sm" type="button" data-sk="close">✕</button></div>
      <p class="muted">Claude đọc hướng dẫn này ở đầu mỗi cuộc trò chuyện của mọi chiến dịch: hỏi những gì, gợi ý thế nào, tổng hợp hồ sơ
        ra sao, dựng quy trình gồm những khối nào. Sửa xong bấm Lưu — áp dụng từ cuộc trò chuyện mới (⟲ Trò chuyện mới).</p>
      <textarea data-sk-text spellcheck="false">${esc(res.skill.text)}</textarea>
      <div class="ch-row"><button class="btn ghost sm" type="button" data-sk="reset">↺ Khôi phục mặc định</button><span class="cv-sp"></span>
        <button class="btn ghost sm" type="button" data-sk="close">Huỷ</button><button class="btn primary sm" type="button" data-sk="save">Lưu skill</button></div></div>`;
    document.body.appendChild(box);
    const close = () => box.remove();
    box.querySelectorAll('[data-sk="close"]').forEach(b => { b.onclick = close; });
    box.onclick = e => { if (e.target === box) close(); };
    box.querySelector('[data-sk="save"]').onclick = async () => {
      const r = await call('ch_skill_save', box.querySelector('[data-sk-text]').value);
      if (r) { toast('Đã lưu skill — bấm ⟲ Trò chuyện mới để Claude dùng bản mới', 'ok'); close(); }
    };
    box.querySelector('[data-sk="reset"]').onclick = async () => {
      if (!confirm('Bỏ bản đã sửa, dùng lại skill mặc định?')) return;
      const r = await call('ch_skill_reset');
      if (r) { box.querySelector('[data-sk-text]').value = r.skill.text; box.querySelector('.ch-skill-tag').textContent = 'bản mặc định'; toast('Đã khôi phục skill mặc định', 'ok'); }
    };
  }

  /* ---------------------------------------------------------------- sự kiện backend (bảng Canvas của chiến dịch) */
  function scheduleReload() {
    clearTimeout(C.reload);  // nhiều sự kiện liên tiếp (từng khối chạy xong) → gộp 1 lần tải lại
    C.reload = setTimeout(async () => {
      const cid = C.cid;
      if (!cid) return;
      const [b, a] = await Promise.all([api('canvas_open', cid), api('canvas_assist_get', cid)]);
      if (C.cid !== cid || !b || !b.ok || !a || !a.ok) return;
      saveInputs();
      C.board = b.board;
      if (!C.sending) C.chat = a.chat;  // đang chờ Claude trả lời → giữ tin nhắn tạm, tải lại khi xong
      if ((C.board.runs || []).length && C.issues && running()) C.issues = null;
      render();
    }, 400);
  }

  function update(event, data) {
    if (!data || data.board !== C.cid || !C.board) return;
    if (event === 'canvas_assist') {
      C.status = data.text;
      const el = root().querySelector('[data-ch-status]');
      if (el) el.textContent = data.text;
      if (!C.sending) scheduleReload();  // tự điều phối chấm / giao làm lại → có tin nhắn mới
      return;
    }
    scheduleReload();
  }

  window.ChannelPage = { show, update };
})();
