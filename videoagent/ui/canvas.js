/* Canvas — bảng node ảnh / video kiểu Kling Canvas.
   Node Ảnh: prompt → model ảnh (ảnh nối vào = ảnh tham chiếu để sửa / ghép). Node Video: ảnh nối vào = khung đầu → model video.
   Node Tải lên: ảnh của bạn. Kéo nền = di chuyển, cuộn = phóng to / thu nhỏ, kéo cổng ＋ sang node khác = nối. */
window.CanvasPage = (() => {
  const C = { meta: null, boards: [], board: null, sel: '', view: { x: 80, y: 60, k: 0.9 }, promptT: null,
    logs: {}, flash: {}, trayClosed: '' };
  const body = () => $('#canvasBody');
  const KIND = { image: '🖼 Ảnh', video: '🎬 Video', upload: '⬆ Ảnh tải lên' };
  const STATUS = { queued: 'Đang chờ', running: 'Đang tạo', done: 'Xong', error: 'Lỗi', idle: '' };

  async function call(name, ...args) {
    try {
      const res = await api(name, ...args);
      if (res && res.ok === false && res.locked) {  // hết phiên mở khoá khi đang sửa → hỏi mật khẩu rồi làm tiếp
        return (await window.requireAdmin('tiếp tục chỉnh sửa quy trình Canvas')) ? call(name, ...args) : null;
      }
      if (res && res.ok === false) { toast(res.error || 'Lỗi', 'error'); return null; }
      return res;
    } catch (err) { toast(String(err), 'error'); return null; }
  }

  /* ---------------------------------------------------------------- vào trang */
  async function show() {
    if (!C.meta) {
      const res = await call('canvas_meta');
      if (!res) return;
      C.meta = res.meta;
    }
    if (C.board) return renderBoard();
    await listBoards();
  }

  // ================================================================ màn danh sách (kiểu Danh sách workflow)
  const KIND_ICON = { image: '🖼', upload: '⬆', video: '🎬' };
  const kindIcon = k => KIND_ICON[k] || ((C.meta && C.meta.wf_types[k]) || {}).icon || '•';
  const L = { q: '', status: '', sort: 'updated', presets: null };
  const RUN_BADGE = { done: 'Xong', error: 'Lỗi', partial: 'Xong 1 phần', cancelled: 'Đã dừng', running: 'Đang chạy' };
  const fmtTime = t => (t ? `${String(t).slice(11, 19)} ${String(t).slice(8, 10)}/${String(t).slice(5, 7)}/${String(t).slice(0, 4)}` : '');

  async function listBoards() {
    const res = await call('canvas_list');
    C.boards = res ? res.boards : [];
    C.board = null;
    C.sel = '';
    if (L.presets === null) {
      const src = await call('canvas_sources');
      L.presets = src ? src.sources.presets : [];
    }
    const stat = (label, value, main) => `<div class="cv-stat ${main ? 'main' : ''}"><small>${esc(label)}</small><b>${value}</b></div>`;
    const bs = C.boards;
    body().innerHTML = `<div class="cv-home">
      <div class="cv-home-head"><div><small class="eyebrow">CANVAS</small><h2>Danh sách Canvas</h2>
        <p class="muted">Bảng sáng tạo kiểu Kling — tạo ảnh, video, viết content, đăng bài trên 1 bảng; chạy lại cả quy trình ngay tại đây.</p></div>
        <div class="row"><button class="btn ghost" data-cv="import" title="Chuyển 1 Workflow đã lưu hoặc quy trình mẫu thành Canvas">⇩ Từ Workflow / mẫu</button>
          <button class="btn primary" data-cv="new">＋ Tạo Canvas</button></div></div>
      <div class="cv-stats">${stat('Tổng canvas', bs.length, true)}${stat('Đang chạy', bs.filter(b => b.running).length)}
        ${stat('Chạy hôm nay', bs.reduce((a, b) => a + (b.runs_today || 0), 0))}
        ${stat('Lần chạy gần nhất lỗi', bs.filter(b => b.last_run && ['error', 'partial'].includes(b.last_run.status)).length)}
        ${stat('Tổng lần chạy', bs.reduce((a, b) => a + (b.runs || 0), 0))}</div>
      <div class="cv-filter"><input data-l="q" placeholder="Tìm theo tên Canvas…" value="${esc(L.q)}">
        <select data-l="status">${[['', 'Mọi trạng thái'], ['running', 'Đang chạy'], ['done', 'Lần gần nhất: xong'], ['error', 'Lần gần nhất: lỗi'], ['never', 'Chưa chạy']]
          .map(([v, t]) => `<option value="${v}" ${L.status === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
        <select data-l="sort">${[['updated', 'Sửa gần nhất'], ['run', 'Chạy gần nhất'], ['name', 'Tên A → Z'], ['nodes', 'Nhiều node nhất']]
          .map(([v, t]) => `<option value="${v}" ${L.sort === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="cv-bgrid"></div>
      <h4 class="cv-sec">MẪU CÓ SẴN</h4>
      <div class="cv-presets">${(L.presets || []).map(p => `<button class="cv-preset" data-preset="${esc(p.id)}" type="button">
        <b>⚡ ${esc(p.name)}</b><small class="muted">${esc(p.desc)}</small><em>${p.nodes} khối · Dùng mẫu này →</em></button>`).join('')}</div></div>`;
    const root = body();
    root.querySelector('[data-cv="new"]').onclick = createBoard;
    root.querySelector('[data-cv="import"]').onclick = importDialog;
    root.querySelectorAll('[data-l]').forEach(el => {
      el.oninput = () => { L[el.dataset.l] = el.value; drawCards(); };
    });
    root.querySelectorAll('[data-preset]').forEach(b => {
      b.onclick = async () => {
        if (!(await window.requireAdmin('tạo quy trình Canvas từ mẫu'))) return;
        const out = await call('canvas_import', 'preset', b.dataset.preset);
        if (!out) return;
        C.board = out.result.board;
        renderBoard();
        fitView();
        toast('Đã tạo Canvas từ mẫu', 'ok');
      };
    });
    drawCards();
  }

  function boardCard(b) {
    const lr = b.last_run;
    const live = b.running && b.flow ? b.flow : null;
    const chain = (b.chain || []).map(k => `<span class="cv-chip-ic">${esc(kindIcon(k))}</span>`).join('<i>›</i>');
    const status = b.running ? `<span class="cv-badge running">⏳ Đang chạy${live ? ` ${live.done}/${live.total}` : ''}</span>`
      : lr ? `<span class="cv-badge ${esc(lr.status)}">${esc(RUN_BADGE[lr.status] || lr.status)}</span> <small class="muted">${esc(fmtTime(lr.ended || lr.at))}</small>`
        : '<small class="muted">Chưa chạy lần nào</small>';
    return `<div class="cv-bcard ${b.running ? 'running' : ''}" data-bid="${esc(b.id)}">
      <div class="cv-bcard-top" data-act-b="open">${b.thumb ? `<img src="${esc(thumbUrl(b.thumb, 420))}" alt="">` : ''}
        <div class="cv-chain">${chain || '<small class="muted">Chưa có node</small>'}</div></div>
      <div class="cv-bcard-body"><b>${esc(b.name)}</b>
        <small class="muted">${b.nodes} node · ${b.edges} dây · ${b.runs} lần chạy · Sửa ${esc(fmtTime(b.updated_at))}</small>
        <div class="cv-bcard-st">${status}</div></div>
      <div class="cv-bcard-foot"><button class="btn ghost sm" data-act-b="open" type="button">Mở</button><span class="cv-sp"></span>
        ${b.running ? '<button class="btn ghost sm" data-act-b="stop" type="button">⏹ Dừng</button>'
          : '<button class="btn primary sm" data-act-b="run" type="button" title="Chạy cả quy trình (dùng lại kết quả không đổi)">▶ Chạy</button>'}
        <button class="btn ghost sm" data-act-b="dup" type="button" title="Nhân bản Canvas">⧉</button>
        <button class="btn ghost sm" data-act-b="del" type="button" title="Xoá Canvas">🗑</button></div></div>`;
  }

  function drawCards() {
    const grid = body().querySelector('.cv-bgrid');
    if (!grid) return;
    const q = L.q.trim().toLowerCase();
    const st = b => (b.running ? 'running' : !b.last_run ? 'never' : ['error', 'partial'].includes(b.last_run.status) ? 'error' : b.last_run.status);
    const sorters = {
      updated: (a, b) => String(b.updated_at).localeCompare(String(a.updated_at)),
      run: (a, b) => String((b.last_run || {}).at || '').localeCompare(String((a.last_run || {}).at || '')),
      name: (a, b) => a.name.localeCompare(b.name, 'vi'),
      nodes: (a, b) => b.nodes - a.nodes,
    };
    const list = C.boards.filter(b => (!q || b.name.toLowerCase().includes(q)) && (!L.status || st(b) === L.status)).sort(sorters[L.sort] || sorters.updated);
    grid.innerHTML = list.map(boardCard).join('') || `<p class="muted">${C.boards.length ? 'Không có Canvas nào khớp bộ lọc.' : 'Chưa có Canvas nào — bấm “＋ Tạo Canvas” hoặc dùng 1 mẫu bên dưới.'}</p>`;
    grid.querySelectorAll('[data-act-b]').forEach(el => {
      el.onclick = () => boardAction(el.dataset.actB, el.closest('[data-bid]').dataset.bid);
    });
  }

  async function boardAction(what, bid) {
    const b = C.boards.find(x => x.id === bid);
    if (what === 'open') return openBoard(bid);
    if (what === 'dup') {
      if (!(await window.requireAdmin('nhân bản quy trình Canvas'))) return;
      if (await call('canvas_duplicate_board', bid)) { toast('Đã nhân bản Canvas', 'ok'); listBoards(); }
      return;
    }
    if (what === 'del') {
      if (!(await window.requireAdmin('xoá quy trình Canvas'))) return;
      if (!confirm(`Xoá Canvas “${b ? b.name : bid}” và mọi ảnh / video trong đó?`)) return;
      if (await call('canvas_delete', bid)) { toast('Đã xoá Canvas', 'ok'); listBoards(); }
      return;
    }
    if (what === 'stop') { if (confirm('Dừng quy trình đang chạy?')) await call('canvas_cancel_flow', bid); return; }
    if (what === 'run') {
      // chạy ngay từ danh sách, không mở Canvas: khối “Hỏi khi chạy” → hộp hỏi hiện ngay tại đây; còn lỗi → liệt kê lỗi
      let res = await call('canvas_preview', bid, 'all', '', false);
      if (!res) return;
      let plan = res.plan;
      if ((plan.ask || []).length) {
        const opened = await call('canvas_open', bid);
        if (!opened) return;
        const prev = C.board;
        C.board = opened.board;  // hộp hỏi đọc node của Canvas này (màn danh sách không vẽ node nên không ảnh hưởng)
        let ok = false;
        try { ok = await askInputs(plan.ask); } finally { C.board = prev; }
        if (!ok) return;
        res = await call('canvas_preview', bid, 'all', '', false);
        if (!res) return;
        plan = res.plan;
      }
      if (plan.issues.some(i => i.level === 'error')) return listIssues(bid, b ? b.name : bid, plan.issues);
      if (!plan.run.length) { toast('Mọi node đã có kết quả mới nhất — không cần chạy'); return; }
      const msg = [`Chạy “${b ? b.name : bid}”:`, `• ${plan.run.length} node sẽ chạy, ${plan.reuse.length} node dùng lại kết quả`,
        plan.posts.length ? '• Có khối đăng bài / quảng cáo: app DỪNG CHỜ bạn duyệt trên node (mở Canvas khi có thông báo).' : '',
        (plan.auto_posts || []).length ? `• 🚀 TỰ ĐĂNG KHÔNG CẦN DUYỆT: ${plan.auto_posts.join(', ')}` : '',
        ...plan.issues.filter(i => i.level === 'warn').map(w => `⚠ ${w.node}: ${w.message}`)].filter(Boolean).join('\n');
      if (!confirm(msg)) return;
      if (await call('canvas_run_flow', bid, 'all', '', false)) {
        toast(`Đang chạy ${plan.run.length} node…`, 'ok');
        const cur = C.boards.find(x => x.id === bid);
        if (cur) { cur.running = true; cur.flow = { done: 0, total: plan.run.length }; drawCards(); }
      }
    }
  }

  /** Màn danh sách: quy trình còn lỗi → liệt kê lỗi ngay tại đây (mở Canvas chỉ khi bạn muốn sửa). */
  function listIssues(bid, name, issues) {
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import';
    box.innerHTML = `<div class="cv-import-box cv-ask-box"><div class="cv-side-head"><b>⚠ “${esc(name)}” chưa chạy được</b><button class="btn ghost sm" data-x type="button">✕</button></div>
      <p class="muted">Sửa các lỗi sau rồi bấm ▶ Chạy lại:</p>
      ${issues.map(i => `<div class="cv-issue ${esc(i.level)}"><b>${esc(i.node || 'Quy trình')}</b><span>${esc(i.message)}</span></div>`).join('')}
      <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn ghost sm" data-x type="button">Đóng</button>
        <button class="btn primary sm" data-open type="button">Mở Canvas để sửa</button></div></div>`;
    box.querySelectorAll('[data-x]').forEach(x => { x.onclick = () => box.remove(); });
    box.querySelector('[data-open]').onclick = async () => {
      box.remove();
      if ((await openBoard(bid)) === false) return;
      const res = await call('canvas_preview', bid, 'all', '', false);
      if (res) { C.issues = Object.fromEntries(res.plan.issues.map(i => [i.node, i])); drawAll(); showIssues(res.plan.issues); }
    };
    box.onclick = e => { if (e.target === box) box.remove(); };
    document.body.appendChild(box);
  }

  function listFlowEvent(data) {
    // màn danh sách: cập nhật thẻ khi quy trình đang chạy / vừa xong
    const b = C.boards.find(x => x.id === data.board);
    if (!b) return;
    const states = Object.values(data.run.nodes || {});
    const running = data.run.status === 'running';
    const wasRunning = b.running;
    b.running = running;
    b.flow = { done: states.filter(x => ['done', 'error', 'skipped'].includes(x)).length, total: states.length };
    b.last_run = { id: data.run.id, label: data.run.label, status: data.run.status, at: data.run.at, ended: data.run.ended };
    if (wasRunning && !running) listBoards();  // xong: tải lại số liệu (lần chạy, ảnh đại diện…)
    else drawCards();
  }

  async function createBoard() {
    if (!(await window.requireAdmin('tạo quy trình Canvas'))) return;
    const res = await call('canvas_create', '');
    if (res) { C.board = res.board; C.view = { x: 80, y: 60, k: 0.9 }; renderBoard(); }
  }

  async function openBoard(bid) {
    if (!(await window.requireAdmin('mở và chỉnh sửa quy trình Canvas'))) return false;  // ▶ Chạy ở danh sách không cần
    const res = await call('canvas_open', bid);
    if (!res) return;
    C.board = res.board;
    C.sel = '';
    renderBoard();
    fitView();
  }

  /* ---------------------------------------------------------------- khung bảng */
  function renderBoard() {
    const b = C.board;
    body().innerHTML = `<div class="cv-wrap">
      <div class="cv-top">
        <button class="btn ghost sm" data-cv="home" title="Danh sách Canvas">⌂</button>
        <input class="cv-name" value="${esc(b.name)}" maxlength="80" title="Đổi tên Canvas">
        <span class="muted cv-count"></span>
        <span class="cv-flow"></span>
        <span class="cv-sp"></span>
        <button class="btn primary sm" data-cv="run" title="Chạy cả quy trình theo thứ tự dây nối — node đã có kết quả mà không đổi gì thì dùng lại (không tốn lượt)">▶ Chạy toàn bộ</button>
        <button class="btn ghost sm" data-cv="rerun" title="Làm lại MỌI node từ đầu (tạo mới hết — tốn lượt model)">⟳ Làm lại tất cả</button>
        <button class="btn ghost sm" data-cv="assist" title="Trợ lý Claude: điều phối quy trình, đánh giá kết quả, đề xuất sửa (bạn bấm Áp dụng mới thay đổi)">🤖 Trợ lý</button>
        <button class="btn ghost sm" data-cv="history" title="Các lần chạy quy trình">🕘 Lịch sử</button>
        <button class="btn ghost sm" data-cv="folder" title="Mở thư mục lưu file của Canvas này">📁 Thư mục</button>
        <button class="btn ghost sm" data-cv="del" title="Xoá Canvas này">🗑 Xoá</button>
      </div>
      <div class="cv-stage" tabindex="0">
        <div class="cv-world"><div class="cv-groups"></div><svg class="cv-edges"></svg><div class="cv-nodes"></div></div>
        <div class="cv-tools hidden"></div>
        <div class="cv-side hidden"></div>
        <div class="cv-assist hidden"></div>
        <div class="cv-menu hidden"></div>
        <div class="cv-empty ${b.nodes.length ? 'hidden' : ''}">
          <b>Bắt đầu Canvas</b><span class="muted">Thêm node Ảnh (viết prompt → tạo ảnh) hoặc tải ảnh của bạn lên, rồi nối sang node Video.</span>
          <div><button class="btn primary sm" data-add="image">🖼 Thêm ảnh</button> <button class="btn ghost sm" data-add="upload">⬆ Tải ảnh lên</button></div>
        </div>
      </div>
      <div class="cv-tray hidden"></div>
      <div class="cv-dock">
        <button data-add="image" title="Thêm node Ảnh (tạo ảnh từ prompt)">🖼<small>Ảnh</small></button>
        <button data-add="video" title="Thêm node Video (nối 1 ảnh vào làm khung đầu)">🎬<small>Video</small></button>
        <button data-add="upload" title="Tải ảnh trên máy lên">⬆<small>Tải lên</small></button>
        <button data-blocks title="Các khối như Workflow: Văn bản, AI viết, Tạo content, Ghép video, Video dài, Whiteboard, Đăng bài, Lên lịch, Quảng cáo">🧩<small>Khối</small></button>
        <button data-group title="Nhóm / ghi chú (như sticky note n8n): khung màu có tên + ghi chú; kéo nhóm thì các node bên trong đi theo. Đang chọn 1 node → bọc quanh node đó. Mẹo: Shift + kéo trên nền để gom nhiều node">▢<small>Nhóm</small></button>
        <span class="cv-dock-sep"></span>
        <button data-zoom="-" title="Thu nhỏ">−</button><span class="cv-zoom"></span><button data-zoom="+" title="Phóng to">＋</button>
        <button data-zoom="fit" title="Vừa khung — xem toàn bộ node">⤢</button>
      </div>
    </div>`;
    const root = body();
    root.querySelector('[data-cv="home"]').onclick = listBoards;
    root.querySelector('[data-cv="folder"]').onclick = () => call('canvas_open_folder', b.id);
    root.querySelector('[data-cv="del"]').onclick = deleteBoard;
    root.querySelector('[data-cv="run"]').onclick = () => runFlow('all', '', false);
    root.querySelector('[data-cv="rerun"]').onclick = () => runFlow('all', '', true);
    root.querySelector('[data-cv="history"]').onclick = () => toggleHistory();
    root.querySelector('[data-cv="assist"]').onclick = () => toggleAssist();
    C.assist = { open: false, chat: null, sending: false, status: '' };
    const name = root.querySelector('.cv-name');
    name.onchange = async () => { const res = await call('canvas_rename', b.id, name.value); if (res) C.board.name = res.board.name; };
    root.querySelectorAll('[data-add]').forEach(el => { el.onclick = () => addAt(el.dataset.add); });
    root.querySelector('[data-blocks]').onclick = e => { e.stopPropagation(); showBlocks(e.currentTarget); };
    root.querySelector('[data-group]').onclick = () => addGroup();
    root.querySelectorAll('[data-zoom]').forEach(el => {
      el.onclick = () => (el.dataset.zoom === 'fit' ? fitView() : zoomBy(el.dataset.zoom === '+' ? 1.2 : 1 / 1.2));
    });
    bindStage(root.querySelector('.cv-stage'));
    drawAll();
  }

  async function deleteBoard() {
    if (!confirm(`Xoá Canvas “${C.board.name}” và mọi ảnh / video trong đó?`)) return;
    if (await call('canvas_delete', C.board.id)) { toast('Đã xoá Canvas', 'ok'); listBoards(); }
  }

  /* ---------------------------------------------------------------- vẽ node + đường nối */
  const node = id => (C.board ? C.board.nodes.find(n => n.id === id) : null);
  const ratio = n => {
    const [w, h] = String(n.aspect || '9:16').split(':').map(Number);
    return w && h ? h / w : 16 / 9;
  };
  const defaultWidth = n => (n.kind === 'wf' ? 300 : ratio(n) < 1 ? 340 : 230);
  const widthOf = n => (n.kind !== 'wf' && n.w ? n.w : defaultWidth(n));  // Ảnh / Video / Tải lên: kéo góc để đổi cỡ
  const wspec = n => (n.kind === 'wf' ? C.meta.wf_types[n.wtype] : null);
  const nameOf = n => (n.kind === 'wf' ? `${wspec(n).icon} ${wspec(n).name}` : KIND[n.kind]);
  const labelOf = n => (n && n.title ? n.title : n ? nameOf(n) : '');  // tên riêng (đặt ở ô Tên) hoặc tên loại
  const tagOf = x => `<b>${esc(x.id)}</b>${x.title ? ` · ${esc(x.title)}` : ''}`;
  const titleInput = n => `<input class="cv-title" data-title value="${esc(n.title || '')}" maxlength="60" placeholder="Tên khối — VD: Thông tin sản phẩm, Lời thoại cảnh 1 (dễ phân biệt khi chạy)">`;
  function bindTitle(panel, id) {
    const inp = panel.querySelector('[data-title]');
    if (!inp) return;
    inp.onkeydown = e => { if (e.key === 'Enter') inp.blur(); };
    inp.onchange = async () => {
      const res = await call('canvas_update_nodes', C.board.id, [{ id, title: inp.value.trim() }]);
      if (res) { C.board = res.board; drawNode(node(id)); drawEdges(); }
    };
  }
  const outTypes = n => (n.kind === 'wf' ? new Set(wspec(n).outputs.map(o => o.type))
    : new Set([n.kind === 'video' ? 'video' : 'images']));
  const inTypes = n => {
    if (n.kind === 'upload') return new Set();
    if (n.kind === 'video') return new Set(['images', 'video', 'text']);
    if (n.kind !== 'wf') return new Set(['images', 'text']);
    return new Set(wspec(n).inputs.flatMap(p => (p.type === 'any' ? ['images', 'video'] : [p.type])));
  };
  const TYPE_VI = { text: 'chữ', images: 'ảnh', video: 'video', post: 'bài đăng' };
  const mediaUrl = n => (n.urls || [])[Math.min(n.pick || 0, Math.max(0, (n.urls || []).length - 1))] || '';
  const isBusy = n => ['queued', 'running', 'waiting'].includes(n.status);
  const isPic = n => n.kind === 'image' || n.kind === 'upload';

  const POST_KIND = { feed: 'Bài viết', text: 'Bài viết chữ', media: 'Ảnh / video', reel: 'Reels', story: 'Story' };
  const shortUrl = u => {
    const s = String(u || '').replace(/^https?:\/\/(www\.|m\.)?/, '');
    return s.length > 34 ? `${s.slice(0, 24)}…${s.slice(-7)}` : s;
  };

  /** Khung xem trước của thẻ bài đăng: video → khung hình đầu của file video (không dùng <img> cho .mp4);
      ảnh → ảnh thu nhỏ; không có / tải lỗi → khung chữ gọn (không hiện biểu tượng ảnh vỡ). */
  function postMedia(p, video) {
    const ph = `<div class="cv-post-ph"><b>${video ? '🎬' : '🖼'}</b><small>${video ? 'Bài video' : 'Bài ảnh'} — bấm 👁 Xem bài để xem trên Facebook</small></div>`;
    const fail = "this.closest('.cv-post-media').classList.add('broken')";
    if (!p.thumb) return video || p.media === 'image' ? `<div class="cv-post-media broken">${ph}</div>` : '';
    const isVideoFile = /\.(mp4|mov|webm|m4v|mkv)(\?|#|$)/i.test(p.thumb);
    const inner = isVideoFile
      ? `<video src="${esc(p.thumb)}#t=0.5" muted playsinline preload="metadata" onerror="${fail}"></video>`
      : `<img src="${esc(thumbUrl(p.thumb, 480))}" alt="" draggable="false" onerror="${fail}">`;
    return `<div class="cv-post-media">${inner}${video || isVideoFile ? '<span class="cv-post-play">▶</span>' : ''}${ph}</div>`;
  }

  function postCard(p) {
    // thẻ bài đăng kiểu Facebook: Fanpage, loại bài, thời gian, trạng thái, ảnh / khung hình, caption, link + nút
    const page = p.page || 'Fanpage';
    const when = p.at ? `${String(p.at).slice(11, 16)} ${String(p.at).slice(8, 10)}/${String(p.at).slice(5, 7)}` : '';
    const state = p.queued ? ['wait', `🕒 Hẹn đăng ${p.when || ''}`] : p.scheduled ? ['wait', `🗓 Facebook hẹn ${p.when || ''}`] : ['ok', '✓ Đã đăng'];
    const video = p.media === 'video' || p.post_type === 'reel';
    return `<div class="cv-post">
      <div class="cv-post-head"><span class="cv-post-av">${esc(page.trim().charAt(0).toUpperCase() || 'F')}</span>
        <div class="cv-post-who"><b>${esc(page)}</b><small>${esc(POST_KIND[p.post_type] || 'Bài viết')}${when ? ` · ${esc(when)}` : ''}</small></div>
        <span class="cv-post-st ${state[0]}">${esc(state[1].trim())}</span></div>
      ${postMedia(p, video)}
      ${p.caption ? `<p class="cv-post-cap">${esc(p.caption)}</p>` : ''}
      ${p.url ? `<div class="cv-post-link" title="${esc(p.url)}">🔗 ${esc(shortUrl(p.url))}</div>
        <div class="cv-post-actions"><button data-view-post type="button" title="Mở bài trong cửa sổ trình duyệt nhỏ (giữ đăng nhập Facebook)">👁 Xem bài</button>
          <button data-copy-link type="button">📋 Sao chép link</button></div>`
        : p.queued ? '<small class="muted cv-post-note">Sửa / đăng ngay ở màn Quản lý bài đăng</small>' : ''}</div>`;
  }

  function wfNodeHtml(n) {
    const s = wspec(n);
    const busy = isBusy(n);
    const out = n.out || {};
    const url = mediaUrl(n);
    const cfgText = n.wtype === 'input_text' ? (n.config || {}).text : '';
    const ap = n.status === 'waiting' ? n.approval || {} : null;
    const body = ap ? `<div class="cv-approve">
        <b>📣 Duyệt ${esc(ap.kind === 'schedule' ? `hẹn giờ ${ap.when || ''}` : 'đăng bài')} lên “${esc(ap.page || '')}”</b>
        <small class="muted">${esc(ap.post_type_label || '')}</small>
        ${(ap.media_urls || []).length ? `<div class="cv-ap-media">${ap.media_urls.map(u => (/\.(mp4|mov|webm|m4v)/i.test(u)
          ? `<video src="${esc(u)}" muted></video>` : `<img src="${esc(thumbUrl(u, 200))}" alt="">`)).join('')}</div>` : ''}
        ${ap.post_type === 'media' || ap.post_type === 'story' ? '' : `<textarea data-ap-caption rows="5">${esc(ap.caption || '')}</textarea>`}
        <div class="row"><button class="btn primary sm" data-ap="yes" type="button">✓ Đồng ý đăng</button>
          <button class="btn ghost sm" data-ap="no" type="button">✕ Không đăng</button></div></div>`
      : url ? `<video src="${esc(url)}" muted loop playsinline preload="metadata"></video>`
        : out.post ? postCard(out.post)
        : out.text ? `<div class="cv-wf-text">${esc(out.text)}</div>`
          : cfgText ? `<div class="cv-wf-text muted">${esc(cfgText)}</div>`
            : `<div class="cv-ph">${busy ? `<div class="cv-spin"></div><b>${Math.round(n.pct || 0)}%</b><small>${esc(n.stage || STATUS[n.status])}</small>`
              : n.status === 'error' ? `<b>⚠ Lỗi</b><small>${esc(n.error || '')}</small>`
                : `<b>${esc(s.icon)}</b><small>${esc(s.desc)}</small>`}</div>`;
    const ins = s.inputs.map(p => TYPE_VI[p.type === 'any' ? 'images' : p.type] && p.label).filter(Boolean);
    return `<div class="cv-node-label"><span title="${esc(nameOf(n))}">${esc(n.title ? `${wspec(n).icon} ${n.title}` : nameOf(n))}${n.ask ? ' · ❓' : ''}${n.auto_post ? ' · 🚀' : ''}</span>
        <em class="cv-st ${esc(n.status || '')}">${n.status === 'waiting' ? 'Chờ duyệt' : busy ? `${Math.round(n.pct || 0)}%` : esc(STATUS[n.status] || '')}</em></div>
      <div class="cv-media wf ${url ? 'has-video' : ''}">${body}${n.status === 'running' ? `<div class="cv-prog"><i style="width:${Math.max(3, Math.round(n.pct || 0))}%"></i></div>` : ''}${busy && (url || out.text) ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
      ${n.status === 'error' && (url || out.text) ? `<div class="cv-err">⚠ ${esc(n.error || '')}</div>` : ''}
      ${n.status === 'idle' && n.error ? `<div class="cv-err muted">${esc(n.error)}</div>` : ''}
      ${ins.length ? `<button class="cv-port in" title="Nhận: ${esc(ins.join(', '))}" type="button"></button>` : ''}
      ${s.outputs.length ? `<button class="cv-port out" title="Đưa ra: ${esc(s.outputs.map(o => o.label).join(', '))} — kéo sang node khác để nối · bấm để tạo tiếp" type="button">＋</button>` : ''}`;
  }

  function nodeHtml(n) {
    if (n.kind === 'wf') return wfNodeHtml(n);
    const url = mediaUrl(n);
    const busy = isBusy(n);
    const media = url
      ? (n.kind === 'video' ? `<video src="${esc(url)}" muted loop playsinline preload="metadata"></video>`
        : `<img src="${esc(n.kind === 'upload' ? url : thumbUrl(url, 640))}" alt="" draggable="false">`)
      : `<div class="cv-ph">${busy ? `<div class="cv-spin"></div><b>${Math.round(n.pct || 0)}%</b><small>${esc(n.stage || STATUS[n.status])}</small>`
        : n.status === 'error' ? `<b>⚠ Lỗi</b><small>${esc(n.error || '')}</small>`
          : n.kind === 'upload' ? `<b>🖼</b><small>${n.ask ? 'Chưa có ảnh — sẽ hỏi chọn ảnh khi chạy quy trình' : 'Chưa có ảnh — bấm ⬆ Chọn ảnh'}</small>`
          : n.kind === 'video' ? '<b>🎬</b><small>Nối 1 ảnh vào làm khung đầu,<br>viết chuyển động rồi bấm Tạo</small>'
            : `<b>🖼</b><small>${promptSrc(n) && promptSrc(n) !== 'own' ? `Prompt lấy từ ${esc(promptSrc(n))} — bấm Tạo<br>(hoặc ▶ Chạy toàn bộ)`
              : dialogueSources(n).length && promptSrc(n) !== 'own' ? 'Prompt = chữ từ khối nối vào<br>+ phần viết thêm — bấm Tạo' : 'Viết prompt rồi bấm Tạo'}</small>`}</div>`;
    const variants = (n.urls || []).length > 1 ? `<div class="cv-variants">${n.urls.map((u, i) =>
      `<img src="${esc(thumbUrl(u, 120))}" data-pick="${i}" class="${i === (n.pick || 0) ? 'on' : ''}" alt="" draggable="false">`).join('')}</div>` : '';
    return `<div class="cv-node-label"><span>${KIND[n.kind]}${n.ask ? ' · ❓' : ''}${(n.dialogue || '').trim() ? ' · 💬' : ''}${n.title ? ` · ${esc(n.title)}` : ''}</span>
        <em class="cv-st ${esc(n.status || '')}">${busy ? `${Math.round(n.pct || 0)}%` : esc(STATUS[n.status] || '')}</em></div>
      <div class="cv-media" style="aspect-ratio:${1 / ratio(n)}">${media}${n.status === 'running' ? `<div class="cv-prog"><i style="width:${Math.max(3, Math.round(n.pct || 0))}%"></i></div>` : ''}${busy && url ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
      ${n.status === 'error' && url ? `<div class="cv-err">⚠ ${esc(n.error || '')}</div>` : ''}
      ${variants}
      ${n.kind !== 'upload' ? '<button class="cv-port in" title="Ảnh nối vào (kéo từ cổng ＋ của ảnh khác sang đây)" type="button"></button>' : ''}
      <button class="cv-port out" title="${n.kind === 'video' ? 'Đưa video ra: kéo sang Đăng bài, Lên lịch, Ghép video, Video khác, Kết quả…' : 'Đưa ảnh ra: kéo sang node khác để nối'} · bấm để tạo tiếp" type="button">＋</button>`;
  }

  function drawNode(n) {
    const holder = body().querySelector('.cv-nodes');
    if (!holder) return;
    let el = holder.querySelector(`[data-node="${n.id}"]`);
    if (!el) {
      el = document.createElement('div');
      el.dataset.node = n.id;
      holder.appendChild(el);
    }
    el.className = `cv-node ${n.kind} st-${n.status || 'idle'}${n.id === C.sel ? ' sel' : ''}${n.status === 'error' ? ' err' : ''}${C.flash && C.flash[n.id] ? ' flash' : ''}${(C.issues || {})[n.id] ? ' issue' : ''}`;
    el.style.left = `${n.x}px`;
    el.style.top = `${n.y}px`;
    el.style.width = `${widthOf(n)}px`;
    el.innerHTML = nodeHtml(n);
    if (n.kind !== 'wf') {
      el.insertAdjacentHTML('beforeend', '<i class="cv-node-resize" title="Kéo để phóng to / thu nhỏ khối · nhấp đúp để về cỡ mặc định"></i>');
      el.querySelector('.cv-node-resize').ondblclick = e => { e.stopPropagation(); resizeNodeTo(n.id, 0); };
    }
    el.querySelectorAll('[data-pick]').forEach(img => {
      img.onpointerdown = e => e.stopPropagation();
      img.onclick = () => pick(n.id, Number(img.dataset.pick));
    });
    const view = el.querySelector('[data-view-post]');
    if (view) {
      view.onpointerdown = e => e.stopPropagation();
      view.onclick = () => act('view-post', n.id);
    }
    const copy = el.querySelector('[data-copy-link]');
    if (copy) {
      copy.onpointerdown = e => e.stopPropagation();
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(((n.out || {}).post || {}).url || ''); toast('Đã sao chép link bài đăng', 'ok'); }
        catch (err) { toast('Không sao chép được', 'error'); }
      };
    }
    const ap = el.querySelector('.cv-approve');
    if (ap) {
      ap.onpointerdown = e => e.stopPropagation();
      ap.onwheel = e => e.stopPropagation();
      ap.querySelectorAll('[data-ap]').forEach(b => {
        b.onclick = async () => {
          const yes = b.dataset.ap === 'yes';
          if (yes && !confirm('Đăng bài này lên Fanpage?')) return;
          const cap = ap.querySelector('[data-ap-caption]');
          if (await call('canvas_approve', C.board.id, n.id, yes, cap ? cap.value : null)) toast(yes ? 'Đã duyệt — đang đăng…' : 'Đã bỏ qua bài đăng', yes ? 'ok' : '');
        };
      });
    }
    const vid = el.querySelector('video');
    if (vid) { el.onmouseenter = () => vid.play().catch(() => {}); el.onmouseleave = () => vid.pause(); }
  }

  function drawAll() {
    const root = body();
    if (!C.board || !root.querySelector('.cv-nodes')) return;
    const ids = new Set(C.board.nodes.map(n => n.id));
    root.querySelectorAll('.cv-node').forEach(el => { if (!ids.has(el.dataset.node)) el.remove(); });
    drawGroups();
    C.board.nodes.forEach(drawNode);
    root.querySelector('.cv-empty').classList.toggle('hidden', C.board.nodes.length > 0 || groups().length > 0);
    root.querySelector('.cv-count').textContent = `${C.board.nodes.length} node${groups().length ? ` · ${groups().length} nhóm` : ''}`;
    applyView();
    drawEdges();
    drawPanel();
    drawFlow();
  }

  function anchor(id, side) {
    const el = body().querySelector(`[data-node="${id}"]`);
    const n = node(id);
    if (!el || !n) return null;
    const media = el.querySelector('.cv-media');
    const y = n.y + (media ? media.offsetTop + media.offsetHeight / 2 : el.offsetHeight / 2);
    return { x: side === 'out' ? n.x + el.offsetWidth : n.x, y };
  }

  function drawEdges(temp) {
    const svg = body().querySelector('.cv-edges');
    if (!svg || !C.board) return;
    const curve = (a, b) => {
      const dx = Math.max(60, Math.abs(b.x - a.x) / 2);
      return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
    };
    const paths = [];
    C.board.nodes.forEach(n => {
      (n.inputs || []).forEach(src => {
        const a = anchor(src, 'out'), b = anchor(n.id, 'in');
        const flow = n.status === 'running' ? ' flow' : n.status === 'waiting' ? ' flow wait' : '';
        if (a && b) paths.push(`<path class="cv-edge${flow}" data-edge="${esc(src)}>${esc(n.id)}" d="${curve(a, b)}"><title>Bấm để bỏ nối</title></path>`);
      });
      if (n.source && node(n.source)) {
        const a = anchor(n.source, 'out'), b = anchor(n.id, 'in');
        if (a && b) paths.push(`<path class="cv-edge soft" d="${curve(a, b)}"></path>`);
      }
    });
    if (temp) paths.push(`<path class="cv-edge temp" d="${curve(temp.a, temp.b)}"></path>`);
    svg.innerHTML = paths.join('');
    svg.querySelectorAll('[data-edge]').forEach(p => {
      p.onpointerdown = e => e.stopPropagation();
      p.onclick = async () => {
        const [src, dst] = p.dataset.edge.split('>');
        if (!confirm('Bỏ nối giữa 2 node này?')) return;
        const res = await call('canvas_connect', C.board.id, src, dst, false);
        if (res) { C.board = res.board; drawAll(); }
      };
    });
  }

  /* ---------------------------------------------------------------- nhóm / ghi chú (kiểu sticky note n8n) */
  const GROUP_COLORS = { yellow: 'Vàng', green: 'Xanh lá', blue: 'Xanh dương', purple: 'Tím', red: 'Đỏ', gray: 'Xám' };
  const groups = () => (C.board && C.board.groups) || [];
  const group = id => groups().find(g => g.id === id);
  // node thuộc nhóm khi góc trên-trái của node nằm trong khung nhóm (như n8n: kéo node vào khung là vào nhóm)
  const inGroup = (g, n) => n.x >= g.x && n.y >= g.y && n.x < g.x + g.w && n.y < g.y + g.h;
  const members = g => (C.board ? C.board.nodes.filter(n => inGroup(g, n)) : []);

  /** Ghi chú dạng markdown gọn: # tiêu đề, - gạch đầu dòng, **đậm**, *nghiêng*, `mã`. */
  function noteHtml(text) {
    const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>').replace(/`(.+?)`/g, '<code>$1</code>');
    const out = [];
    let list = false;
    String(text || '').split('\n').forEach(line => {
      const li = /^\s*[-*•]\s+(.*)/.exec(line);
      if (li) { if (!list) { out.push('<ul>'); list = true; } out.push(`<li>${inline(li[1])}</li>`); return; }
      if (list) { out.push('</ul>'); list = false; }
      const h = /^(#{1,3})\s+(.*)/.exec(line);
      out.push(h ? `<h${h[1].length + 3}>${inline(h[2])}</h${h[1].length + 3}>` : line.trim() ? `<p>${inline(line)}</p>` : '<p class="sp"></p>');
    });
    if (list) out.push('</ul>');
    return out.join('');
  }

  function drawGroups() {
    const holder = body().querySelector('.cv-groups');
    if (!holder || !C.board) return;
    holder.innerHTML = groups().map(g => {
      const count = members(g).length;
      return `<div class="cv-group c-${esc(g.color || 'yellow')}${g.id === C.gsel ? ' sel' : ''}" data-group="${esc(g.id)}"
          style="left:${g.x}px;top:${g.y}px;width:${g.w}px;height:${g.h}px">
        <div class="cv-group-head">
          <input class="cv-group-title" data-gtitle value="${esc(g.title || '')}" size="${Math.max(8, (g.title || '').length + 1)}" maxlength="80" placeholder="Tên nhóm" title="Đổi tên nhóm">
          <span class="cv-group-count">${count ? `${count} node` : ''}</span>
          <span class="cv-group-tools">${Object.entries(GROUP_COLORS).map(([c, label]) =>
            `<button type="button" class="cv-swatch c-${c}${c === (g.color || 'yellow') ? ' on' : ''}" data-gcolor="${c}" title="Màu ${label}"></button>`).join('')}
            <button type="button" class="cv-gbtn" data-gnote-edit title="Viết ghi chú">✎</button>
            <button type="button" class="cv-gbtn" data-gdel title="Xoá nhóm (giữ các node bên trong)">🗑</button></span>
        </div>
        <div class="cv-group-note" data-gnote title="Nhấp đúp để viết ghi chú">${g.note ? noteHtml(g.note) : '<span class="cv-group-hint">Nhấp đúp để viết ghi chú…</span>'}</div>
        <i class="cv-group-resize" data-gresize title="Kéo để đổi cỡ nhóm"></i>
      </div>`;
    }).join('');
    holder.querySelectorAll('[data-gtitle]').forEach(inp => {
      inp.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter' || e.key === 'Escape') inp.blur(); };
      inp.onchange = () => saveGroup(inp.closest('[data-group]').dataset.group, { title: inp.value });
    });
    holder.ondblclick = e => {
      const el = e.target.closest('[data-group]');
      if (el && !e.target.closest('input, textarea, button')) editNote(el.dataset.group);
    };
  }

  function selectGroup(gid) {
    if (C.sel) selectNode('');
    C.gsel = gid;
    body().querySelectorAll('.cv-group').forEach(el => el.classList.toggle('sel', el.dataset.group === gid));
  }

  async function saveGroup(gid, patch) {
    const res = await call('canvas_update_group', C.board.id, gid, patch, []);
    if (res) { C.board = res.board; drawGroups(); }
  }

  async function addGroup(rect) {
    if (!C.board) return;
    let box = rect;
    const sel = !box && node(C.sel);
    if (sel) {  // đang chọn 1 node → bọc quanh node đó
      const el = body().querySelector(`[data-node="${sel.id}"]`);
      box = { x: sel.x - 30, y: sel.y - 64, w: (el ? el.offsetWidth : 240) + 60, h: (el ? el.offsetHeight : 300) + 100, title: labelOf(sel) };
    }
    if (!box) {
      const r = body().querySelector('.cv-stage').getBoundingClientRect();
      box = { x: Math.round((r.width / 2 - C.view.x) / C.view.k - 220), y: Math.round((r.height / 3 - C.view.y) / C.view.k - 140), w: 440, h: 280 };
    }
    const res = await call('canvas_add_group', C.board.id, { title: 'Nhóm mới', ...box });
    if (!res || !res.result) return;
    C.board = res.result.board;
    drawAll();
    selectGroup(res.result.group);
    const inp = body().querySelector(`[data-group="${res.result.group}"] [data-gtitle]`);
    if (inp) { inp.focus(); inp.select(); }
  }

  async function deleteGroup(gid) {
    const g = group(gid);
    if (!g) return;
    if ((g.note || members(g).length) && !confirm(`Xoá nhóm “${g.title || g.id}”? Các node bên trong vẫn giữ nguyên.`)) return;
    const res = await call('canvas_delete_group', C.board.id, gid);
    if (res) { C.board = res.board; C.gsel = ''; drawAll(); }
  }

  function editNote(gid) {
    const g = group(gid);
    const box = body().querySelector(`[data-group="${gid}"] [data-gnote]`);
    if (!g || !box || box.querySelector('textarea')) return;
    selectGroup(gid);
    box.innerHTML = `<textarea placeholder="Ghi chú cho nhóm… (# tiêu đề, - gạch đầu dòng, **đậm**, *nghiêng*) · Ctrl + Enter để xong">${esc(g.note || '')}</textarea>`;
    const ta = box.querySelector('textarea');
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.onkeydown = e => {
      e.stopPropagation();
      if (e.key === 'Escape') { ta.onblur = null; drawGroups(); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ta.blur();
    };
    ta.onblur = async () => { await saveGroup(gid, { note: ta.value }); fitNote(gid); };
  }

  /** Ghi chú dài đè lên node trong nhóm → nới khung nhóm lên trên cho đủ chỗ (node giữ nguyên chỗ). */
  function fitNote(gid) {
    const g = group(gid);
    const el = body().querySelector(`[data-group="${gid}"]`);
    const inside = g ? members(g) : [];
    if (!el || !inside.length) return;
    const need = el.querySelector('.cv-group-head').offsetHeight + el.querySelector('.cv-group-note').scrollHeight + 14;
    const room = Math.min(...inside.map(n => n.y)) - g.y;
    if (need > room) saveGroup(gid, { y: g.y - Math.ceil(need - room), h: g.h + Math.ceil(need - room) });
  }

  function groupPointer(e, gid) {
    const t = e.target;
    const color = t.closest('[data-gcolor]');
    if (color) return saveGroup(gid, { color: color.dataset.gcolor });
    if (t.closest('[data-gdel]')) return deleteGroup(gid);
    if (t.closest('[data-gnote-edit]')) { e.preventDefault(); return editNote(gid); }
    selectGroup(gid);
    if (t.closest('input, textarea')) return;
    if (t.closest('[data-gresize]')) return resizeGroup(e, gid);
    return dragGroup(e, gid);
  }

  function dragGroup(e, gid) {
    const g = group(gid);
    const inside = members(g).map(n => ({ n, x: n.x, y: n.y }));
    const start = { x: e.clientX, y: e.clientY, gx: g.x, gy: g.y };
    const el = body().querySelector(`[data-group="${gid}"]`);
    let moved = false;
    const move = ev => {
      const dx = (ev.clientX - start.x) / C.view.k, dy = (ev.clientY - start.y) / C.view.k;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      g.x = Math.round(start.gx + dx);
      g.y = Math.round(start.gy + dy);
      el.style.left = `${g.x}px`;
      el.style.top = `${g.y}px`;
      inside.forEach(m => {
        m.n.x = Math.round(m.x + dx);
        m.n.y = Math.round(m.y + dy);
        const ne = body().querySelector(`[data-node="${m.n.id}"]`);
        if (ne) { ne.style.left = `${m.n.x}px`; ne.style.top = `${m.n.y}px`; }
      });
      drawEdges();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) call('canvas_update_group', C.board.id, gid, { x: g.x, y: g.y }, inside.map(m => ({ id: m.n.id, x: m.n.x, y: m.n.y })));
      body().querySelector('.cv-stage').focus({ preventScroll: true });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  function resizeGroup(e, gid) {
    const g = group(gid);
    const start = { x: e.clientX, y: e.clientY, w: g.w, h: g.h };
    const el = body().querySelector(`[data-group="${gid}"]`);
    const move = ev => {
      g.w = Math.max(180, Math.round(start.w + (ev.clientX - start.x) / C.view.k));
      g.h = Math.max(110, Math.round(start.h + (ev.clientY - start.y) / C.view.k));
      el.style.width = `${g.w}px`;
      el.style.height = `${g.h}px`;
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      saveGroup(gid, { w: g.w, h: g.h });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /** Shift + kéo trên nền: khung chọn → gom các node nằm trọn trong khung vào nhóm mới (khung trống đủ lớn → nhóm / ghi chú trống). */
  function marquee(e) {
    const world = body().querySelector('.cv-world');
    const a = toWorld(e);
    let b = a;
    const box = document.createElement('div');
    box.className = 'cv-marquee';
    world.appendChild(box);
    const rect = () => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) });
    const move = ev => {
      b = toWorld(ev);
      const q = rect();
      Object.assign(box.style, { left: `${q.x}px`, top: `${q.y}px`, width: `${q.w}px`, height: `${q.h}px` });
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      box.remove();
      const q = rect();
      const size = n => { const el = body().querySelector(`[data-node="${n.id}"]`); return { w: el ? el.offsetWidth : 240, h: el ? el.offsetHeight : 300 }; };
      const hits = C.board.nodes.filter(n => { const s = size(n); return n.x >= q.x && n.y >= q.y && n.x + s.w <= q.x + q.w && n.y + s.h <= q.y + q.h; });
      if (hits.length) {
        const x1 = Math.min(...hits.map(n => n.x)), y1 = Math.min(...hits.map(n => n.y));
        const x2 = Math.max(...hits.map(n => n.x + size(n).w)), y2 = Math.max(...hits.map(n => n.y + size(n).h));
        return addGroup({ x: x1 - 30, y: y1 - 64, w: x2 - x1 + 60, h: y2 - y1 + 100, title: `Nhóm ${hits.length} node` });
      }
      if (q.w > 120 && q.h > 80) return addGroup({ x: Math.round(q.x), y: Math.round(q.y), w: Math.round(q.w), h: Math.round(q.h) });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /* ---------------------------------------------------------------- thanh công cụ + ô prompt của node đang chọn */
  function selectNode(id) {
    if (C.gsel) {
      C.gsel = '';
      body().querySelectorAll('.cv-group.sel').forEach(el => el.classList.remove('sel'));
    }
    C.sel = id;
    body().querySelectorAll('.cv-node').forEach(el => el.classList.toggle('sel', el.dataset.node === id));
    hideMenu();
    drawPanel(true);
  }

  function optionsHtml(n) {
    const m = C.meta;
    const sel = (key, items, value, label) => `<label title="${esc(label)}"><select data-f="${key}">${items.map(([v, t]) =>
      `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
    if (n.kind === 'video') {
      const spec = m.video_engines[n.engine] || Object.values(m.video_engines)[0];
      return sel('engine', Object.entries(m.video_engines).map(([k, v]) => [k, v.name]), n.engine, 'Model video')
        + sel('aspect', spec.aspects.map(a => [a, a]), n.aspect, 'Tỉ lệ')
        + sel('duration', spec.durations.map(d => [d, d.replace('s', ' giây')]), n.duration, 'Thời lượng')
        + sel('resolution', spec.resolutions.map(r => [r, r]), n.resolution, 'Độ phân giải')
        + sel('voice', (m.voices || []).map(v => [v.value, `🗣 ${v.label}`]), n.voice || '', 'Giọng đọc lời thoại')
        + `<label class="cv-opt-check" title="Tắt: mọi ảnh nối vào đều là ảnh tham chiếu (model tự dựng cảnh mới)"><input type="checkbox" data-f="first_frame" ${n.first_frame !== false ? 'checked' : ''}> Ảnh đầu làm khung mở đầu</label>`
        + askCheck(n);
    }
    const spec = m.image_engines[n.engine] || Object.values(m.image_engines)[0];
    return sel('engine', Object.entries(m.image_engines).map(([k, v]) => [k, v.name]), n.engine, 'Model ảnh')
      + sel('aspect', spec.aspects.map(a => [a, a]), n.aspect, 'Tỉ lệ')
      + sel('count', spec.counts.map(c => [c, `${c} ảnh`]), n.count, 'Số ảnh mỗi lần')
      + askCheck(n);
  }

  function inputsNote(n) {
    const ins = (n.inputs || []).map(node).filter(Boolean);
    const pics = ins.filter(isPic);
    const texts = ins.filter(x => x.kind === 'wf' && outTypes(x).has('text') && !outTypes(x).has('video') && x.id !== n.dialogue_src);
    const psrc = promptSrc(n);
    const textNote = (psrc === 'own' ? (texts.length ? ` · Chỉ dùng prompt viết trực tiếp (bỏ qua chữ từ ${texts.map(tagOf).join(', ')})` : '')
      : psrc ? ` · Prompt lấy từ ${tagOf(node(psrc))}`
        : texts.length ? ` · Chữ từ ${texts.map(tagOf).join(', ')} được ghép vào đầu prompt` : '')
      + (n.kind === 'video' && n.dialogue_src && node(n.dialogue_src) ? ` · 💬 Lời thoại lấy từ ${tagOf(node(n.dialogue_src))}` : '');
    if (n.kind === 'video') {
      // chia file giống backend (video_plan): ảnh đầu = khung mở đầu (nếu bật), ảnh sau = tham chiếu, 1 video tham chiếu
      const spec = C.meta.video_engines[n.engine] || {};
      const vids = ins.filter(x => outTypes(x).has('video'));
      let room = Math.max(1, spec.max_images || 1) - (vids.length ? 1 : 0);
      const list = [...pics];
      const first = list.length && n.first_frame !== false ? list.shift() : null;
      if (first) room -= 1;
      const refs = list.splice(0, Math.max(0, Math.min(5, room)));
      const b = tagOf;
      const parts = [first ? `Khung đầu: ${b(first)}` : '', refs.length ? `Tham chiếu: ${refs.map(b).join(', ')}` : '',
        vids.length ? `Video tham chiếu: ${b(vids[0])}${spec.video_input ? '' : ' <i>(model này chỉ lấy 1 khung hình — nên chọn Grok / Dola)</i>'}` : '',
        list.length || vids.length > 1 ? `<span class="warn-text">Bỏ ${list.length + Math.max(0, vids.length - 1)} file thừa — ${esc(spec.name || '')} nhận tối đa ${spec.max_images} file</span>` : ''].filter(Boolean);
      return (parts.length ? parts.join(' · ') : '⚠ Chưa có file — kéo cổng ＋ của ảnh / video sang node này (nối được nhiều file)') + textNote;
    }
    return (pics.length ? `Ảnh tham chiếu: ${pics.map(tagOf).join(', ')} — prompt nói rõ cần sửa / ghép gì`
      : 'Nối ảnh khác vào để sửa ảnh / ghép sản phẩm, nhân vật') + textNote;
  }

  function drawPanel(focus) {
    const root = body();
    const tools = root.querySelector('.cv-tools');
    if (!tools) return;
    const n = node(C.sel);
    let panel = root.querySelector('.cv-panel');
    if (!n) {
      tools.classList.add('hidden');
      if (panel) panel.remove();
      return;
    }
    // thanh công cụ nổi (toạ độ màn hình, không phóng theo zoom)
    const has = (n.urls || []).length > 0;
    const busy = isBusy(n);
    tools.innerHTML = [
      isPic(n) && has ? '<button data-act="to-video" title="Tạo node Video dùng ảnh này làm khung đầu">🎬 Tạo video</button>' : '',
      isPic(n) && has ? '<button data-act="edit" title="Tạo node Ảnh mới dùng ảnh này làm tham chiếu (sửa, đổi bối cảnh, thêm sản phẩm…)">🖌 Sửa ảnh</button>' : '',
      isPic(n) && has ? '<button data-act="upscale" title="Phóng to 2× trên máy (không tốn lượt model)">⤢ Phóng to 2×</button>' : '',
      isPic(n) && !busy ? '<button data-act="replace" title="Chọn ảnh khác trên máy thay cho ảnh này — giữ nguyên dây nối, node phía sau sẽ dùng ảnh mới">🔄 Thay ảnh</button>' : '',
      has ? '<button data-act="view" title="Xem lớn">⛶ Xem</button>' : '',
      has ? '<button data-act="download" title="Lưu file về máy">⬇ Tải về</button>' : '',
      n.kind === 'wf' && (n.out || {}).text ? '<button data-act="copy" title="Sao chép chữ kết quả">📋 Sao chép</button>' : '',
      (n.out || {}).folder ? '<button data-act="open-result" title="Mở thư mục khối Kết quả đã gom">📁 Mở thư mục</button>' : '',
      ((n.out || {}).post || {}).url ? '<button data-act="view-post" title="Mở bài đã đăng trong cửa sổ trình duyệt nhỏ">👁 Xem bài</button>' : '',
      n.kind !== 'upload' && !(n.kind === 'wf' && n.wtype === 'input_text') ? '<button data-act="run-to" title="Chạy các node phía trước + node này (dùng lại kết quả không đổi)">▶ Đến đây</button>' : '',
      n.kind !== 'upload' ? '<button data-act="run-from" title="Chạy node này + mọi node phía sau">⏩ Từ đây</button>' : '',
      n.kind !== 'upload' ? '<button data-act="dup" title="Nhân bản node (giữ prompt, model, nối)">⧉</button>' : '',
      busy ? '<button data-act="cancel" title="Dừng tạo">⏹ Dừng</button>' : '',
      '<button data-act="del" class="danger" title="Xoá node (phím Delete)">🗑</button>',
    ].join('');
    tools.classList.remove('hidden');
    tools.querySelectorAll('[data-act]').forEach(b => { b.onclick = () => act(b.dataset.act, n.id); });
    placeTools();
    // ô prompt dưới node (nằm trong world → kéo / zoom theo node)
    if (n.kind === 'upload') return drawUploadPanel(n);
    if (n.kind === 'wf') return drawWfPanel(n);
    if (!panel || panel.dataset.for !== n.id) {
      if (panel) panel.remove();
      panel = document.createElement('div');
      panel.className = 'cv-panel';
      panel.dataset.for = n.id;
      panel.onpointerdown = e => e.stopPropagation();
      panel.onwheel = e => e.stopPropagation();
      root.querySelector('.cv-nodes').appendChild(panel);
      panel.innerHTML = `${titleInput(n)}<div class="cv-in-note"></div>
        <div class="cv-dialogue-head cv-prompt-head"><b>✎ Prompt</b>
          <select data-prompt-src title="Lấy prompt từ khối chữ đang nối vào (Văn bản, AI viết…), viết trực tiếp, hoặc ghép cả hai"></select></div>
        <textarea placeholder="${n.kind === 'video' ? 'Mô tả chuyển động: người làm gì, máy quay thế nào (VD: cô gái mỉm cười giới thiệu sản phẩm, máy đứng yên)…'
          : 'Mô tả ảnh muốn tạo (VD: Ảnh đang livestream trên TikTok, có thiết bị và trưng bày các sản phẩm)…'}"></textarea>
        ${n.kind === 'video' ? `<div class="cv-dialogue"><div class="cv-dialogue-head"><b>💬 Lời thoại</b>
            <select data-dlg-src title="Lấy lời thoại từ khối chữ đang nối vào (Văn bản, AI viết…) hoặc tự nhập"></select><small data-dlg-count></small></div>
          <textarea data-dlg rows="3" placeholder="Câu nhân vật nói trong video (tiếng Việt, đúng nguyên văn). Mỗi dòng 1 câu; nhiều người: Tên: câu nói"></textarea></div>` : ''}
        <div class="cv-panel-row"><div class="cv-opts"></div><span class="cv-sp"></span>
          <button class="btn ghost sm" data-p="enhance" title="Nhờ model chữ (Cài đặt → Model AI) viết lại prompt chi tiết hơn">✨</button>
          <button class="btn primary sm" data-p="go"></button></div>`;
      const ta = panel.querySelector('textarea');
      ta.value = n.prompt || '';
      ta.oninput = () => {
        if (ta.readOnly) return;
        const cur = node(n.id);
        if (cur) cur.prompt = ta.value;
        clearTimeout(C.promptT);
        C.promptT = setTimeout(() => call('canvas_update_nodes', C.board.id, [{ id: n.id, prompt: ta.value }]), 600);
      };
      ta.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(n.id); };
      const dlg = panel.querySelector('[data-dlg]');
      if (dlg) {
        dlg.value = n.dialogue || '';
        dlg.oninput = () => {
          if (dlg.readOnly) return;
          const cur = node(n.id);
          if (cur) cur.dialogue = dlg.value;
          dialogueCount(panel, cur || n);
          clearTimeout(C.dlgT);
          C.dlgT = setTimeout(() => call('canvas_update_nodes', C.board.id, [{ id: n.id, dialogue: dlg.value }]), 600);
        };
      }
      bindTitle(panel, n.id);
      panel.querySelector('[data-p="enhance"]').onclick = () => enhance(n.id);
      panel.querySelector('[data-p="go"]').onclick = () => (isBusy(node(n.id)) ? act('cancel', n.id) : generate(n.id));
      if (focus) setTimeout(() => ta.focus(), 30);
    }
    const ta = panel.querySelector('textarea');
    // nguồn prompt: ghép (mặc định) | chỉ viết trực tiếp | lấy từ 1 khối chữ đang nối vào (ô prompt chỉ đọc, hiện chữ khối đó)
    const psel = panel.querySelector('[data-prompt-src]');
    const ptexts = dialogueSources(n);
    const psrc = promptSrc(n);
    psel.innerHTML = ptexts.length
      ? `<option value="">✚ Ghép: chữ từ khối nối vào + phần viết thêm</option><option value="own">✍ Chỉ dùng prompt viết trực tiếp</option>
        ${ptexts.map(x => `<option value="${esc(x.id)}">⇢ Lấy từ ${esc(x.id)} · ${esc(labelOf(x))}</option>`).join('')}`
      : '<option value="">✍ Viết trực tiếp — nối khối Văn bản / AI viết vào để lấy prompt từ khối đó</option>';
    psel.value = psrc === 'own' || ptexts.some(x => x.id === psrc) ? psrc : '';
    psel.disabled = !ptexts.length;
    psel.onchange = () => setOption(n.id, 'prompt_src', psel.value);
    const fromNode = !!(psrc && psrc !== 'own');
    const modeChanged = ta.readOnly !== fromNode;  // vừa đổi nguồn → luôn thay chữ trong ô (kể cả khi ô đang focus)
    ta.readOnly = fromNode;
    ta.classList.toggle('from-src', fromNode);
    ta.placeholder = fromNode ? `Khối ${psrc} chưa có chữ — chạy khối đó trước, hoặc ▶ Chạy toàn bộ`
      : psrc === '' && ptexts.length ? 'Viết thêm (không bắt buộc) — được ghép sau chữ từ khối nối vào…'
        : n.kind === 'video' ? 'Mô tả chuyển động: người làm gì, máy quay thế nào (VD: cô gái mỉm cười giới thiệu sản phẩm, máy đứng yên)…'
          : 'Mô tả ảnh muốn tạo (VD: Ảnh đang livestream trên TikTok, có thiết bị và trưng bày các sản phẩm)…';
    const wantPrompt = fromNode ? sourceText(node(psrc)) : (n.prompt || '');
    if ((modeChanged || fromNode || document.activeElement !== ta) && ta.value !== wantPrompt) ta.value = wantPrompt;
    panel.querySelector('[data-p="enhance"]').disabled = fromNode;
    panel.querySelector('.cv-in-note').innerHTML = inputsNote(n) + (n.stage && !busy ? ` · <i>${esc(n.stage)}</i>` : '');
    panel.querySelector('.cv-opts').innerHTML = optionsHtml(n);
    const dlg = panel.querySelector('[data-dlg]');
    if (dlg) {
      const srcSel = panel.querySelector('[data-dlg-src]');
      const srcs = dialogueSources(n);
      srcSel.innerHTML = `<option value="">✍ Tự nhập</option>${srcs.map(x => `<option value="${esc(x.id)}" ${x.id === n.dialogue_src ? 'selected' : ''}>
        Lấy từ ${esc(x.id)} · ${esc(labelOf(x))}</option>`).join('')}`;
      srcSel.disabled = !srcs.length;
      srcSel.title = srcs.length ? 'Lấy lời thoại từ khối chữ đang nối vào, hoặc tự nhập' : 'Nối khối Văn bản / AI viết vào node này để lấy lời thoại từ đó';
      srcSel.onchange = () => setOption(n.id, 'dialogue_src', srcSel.value);
      const fromSrc = !!(n.dialogue_src && node(n.dialogue_src));
      dlg.readOnly = fromSrc;
      dlg.classList.toggle('from-src', fromSrc);
      dlg.placeholder = fromSrc ? `Khối ${n.dialogue_src} chưa có chữ — chạy nó trước, hoặc ▶ Chạy toàn bộ`
        : 'Câu nhân vật nói trong video (tiếng Việt, đúng nguyên văn). Mỗi dòng 1 câu; nhiều người: Tên: câu nói';
      const want = fromSrc ? sourceText(node(n.dialogue_src)) : (n.dialogue || '');
      if (document.activeElement !== dlg && dlg.value !== want) dlg.value = want;
      dialogueCount(panel, n);
    }
    panel.querySelectorAll('[data-f]').forEach(s => { s.onchange = () => setOption(n.id, s.dataset.f, s.type === 'checkbox' ? s.checked : s.value); });
    const go = panel.querySelector('[data-p="go"]');
    go.textContent = busy ? `⏹ Dừng (${Math.round(n.pct || 0)}%)` : has ? '↻ Tạo lại' : '✦ Tạo';
    go.classList.toggle('danger', busy);
    const el = root.querySelector(`[data-node="${n.id}"]`);
    panel.style.left = `${n.x}px`;
    panel.style.top = `${n.y + (el ? el.offsetHeight : 300) + 14}px`;
    panel.style.width = `${Math.max(440, el ? el.offsetWidth : 300)}px`;
  }

  /* ---------------------------------------------------------------- ô cấu hình node khối (dựng từ fields của Workflow) */
  const SRC = { fb: null, studio: null };
  async function loadSources(force) {
    if (force || !SRC.fb) {
      const res = await api('wf_fb_options');
      SRC.fb = res && res.ok ? res : { pages: [], accounts: [], accounts_error: (res && res.error) || '' };
    }
    if (force || !SRC.studio) {
      const res = await api('studio_list');
      SRC.studio = res && res.ok ? res.projects.map(p => ({ id: p.id, name: p.name })) : [];
    }
  }

  function fieldVisible(f, cfg) {
    if (!f.when) return true;
    return Object.entries(f.when).every(([k, vals]) => (vals === '*' ? (Array.isArray(cfg[k]) ? cfg[k].length > 0 : !!cfg[k])
      : (Array.isArray(vals) ? vals : [vals]).includes(cfg[k])));
  }

  function fieldHtml(f, cfg) {
    const v = cfg[f.key];
    const lab = `<span>${esc(f.label)}</span>`;
    if (f.type === 'textarea') return `<label class="field">${lab}<textarea data-c="${f.key}" rows="${f.key === 'template' ? 8 : 4}">${esc(v ?? '')}</textarea></label>`;
    if (f.type === 'select') return `<label class="field">${lab}<select data-c="${f.key}">${f.options.map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`;
    if (f.type === 'check') return `<label class="check"><input type="checkbox" data-c="${f.key}" ${v ? 'checked' : ''}> ${esc(f.label)}</label>`;
    if (f.type === 'number') return `<label class="field">${lab}<input type="number" min="0" step="any" data-c="${f.key}" value="${esc(v ?? '')}"></label>`;
    if (f.type === 'datetime') return `<label class="field">${lab}<input type="datetime-local" data-c="${f.key}" value="${esc(v ?? '')}"></label>`;
    if (f.type === 'fb_page' || f.type === 'ad_account') {
      const list = SRC.fb ? (f.type === 'fb_page' ? SRC.fb.pages : SRC.fb.accounts) : null;
      return `<label class="field"><span>${esc(f.label)} <button class="link" data-reload-src type="button">↻ tải lại</button></span>
        <select data-c="${f.key}">${list === null ? '<option>Đang tải…</option>' : `<option value="">— Chọn —</option>${list.map(o =>
          `<option value="${esc(o.id)}" ${o.id === v ? 'selected' : ''}>${esc(o.name)}${o.currency ? ` · ${esc(o.currency)}` : ''}</option>`).join('')}`}</select>
        ${list && !list.length ? `<small class="warn-text">${f.type === 'fb_page' ? 'Chưa có Fanpage nào bật Kết nối (mục Fanpage Facebook)' : `Không có tài khoản quảng cáo${SRC.fb.accounts_error ? ` — ${esc(SRC.fb.accounts_error)}` : ''}`}</small>` : ''}</label>`;
    }
    if (f.type === 'studio_preset') {
      const list = SRC.studio;
      return `<label class="field">${lab}<select data-c="${f.key}">${list === null ? '<option>Đang tải…</option>'
        : `<option value="">— Không dùng: chỉnh ở các ô bên dưới —</option>${list.map(x => `<option value="${esc(x.id)}" ${x.id === v ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}`}</select></label>`;
    }
    if (f.type === 'files') {
      return `<div class="field">${lab}<div class="cv-files">${(v || []).map((p, i) => `<span class="camp-chip">${esc(String(p).split(/[\\/]/).pop())}<button data-rmfile="${f.key}:${i}" type="button">✕</button></span>`).join('')}
        <button class="btn ghost sm" data-pickfile="${f.key}" data-kind="${esc(f.kind)}" data-single="${f.single ? 1 : 0}" type="button">+ Chọn file…</button></div></div>`;
    }
    return `<label class="field">${lab}<input data-c="${f.key}" value="${esc(v ?? '')}"></label>`;
  }

  function saveConfig(id, patch, redraw) {
    const n = node(id);
    n.config = { ...(n.config || {}), ...patch };
    clearTimeout(C.promptT);
    C.promptT = setTimeout(() => call('canvas_update_nodes', C.board.id, [{ id, config: n.config }]), redraw ? 0 : 500);
    if (redraw) { drawNode(n); drawEdges(); drawWfPanel(n, true); } else if (n.wtype === 'input_text') drawNode(n);
  }

  function drawWfPanel(n, rebuild) {
    const root = body();
    const s = wspec(n);
    let panel = root.querySelector('.cv-panel');
    const fresh = !panel || panel.dataset.for !== n.id || rebuild;
    if (!panel || panel.dataset.for !== n.id) {
      if (panel) panel.remove();
      panel = document.createElement('div');
      panel.className = 'cv-panel wf';
      panel.dataset.for = n.id;
      panel.onpointerdown = e => e.stopPropagation();
      panel.onwheel = e => e.stopPropagation();
      root.querySelector('.cv-nodes').appendChild(panel);
    }
    const busy = isBusy(n);
    const cfg = n.config || {};
    const ins = (n.inputs || []).map(node).filter(Boolean);
    const needSrc = s.fields.some(f => ['fb_page', 'ad_account', 'studio_preset'].includes(f.type));
    if (fresh) {
      if (needSrc && (!SRC.fb || !SRC.studio)) loadSources().then(() => { if (C.sel === n.id) drawWfPanel(node(n.id), true); });
      const keep = document.activeElement && panel.contains(document.activeElement) ? document.activeElement.dataset.c : '';
      panel.innerHTML = `${titleInput(n)}<div class="cv-in-note">${esc(s.desc)}${ins.length ? `<br>Nhận từ: ${ins.map(tagOf).join(', ')}` : s.inputs.length
          ? `<br>Nối vào: ${s.inputs.map(p => esc(p.label)).join(' · ')}` : ''}</div>
        ${n.wtype === 'input_video' ? '' : `<label class="cv-opt-check cv-ask-toggle" title="Mỗi lần chạy quy trình, app hỏi lại các ô của khối này (sửa được trước khi chạy)"><input type="checkbox" data-ask-toggle ${n.ask ? 'checked' : ''}> ❓ Hỏi lại các ô này mỗi lần chạy quy trình</label>`}
        <div class="cv-wf-fields">${s.fields.filter(f => fieldVisible(f, cfg)).map(f => fieldHtml(f, cfg)).join('')}</div>
        ${s.outputs.some(o => o.type === 'text') && (n.out || {}).text !== undefined && n.wtype !== 'input_text' ? `<label class="field"><span>Kết quả — sửa được trước khi dùng tiếp</span>
          <textarea data-out rows="6">${esc((n.out || {}).text || '')}</textarea></label>` : ''}
        ${['fb_post', 'fb_schedule'].includes(n.wtype) ? `<label class="cv-opt-check cv-auto-post ${n.auto_post ? 'on' : ''}" title="Bật: khi chạy, khối này đăng / hẹn giờ thẳng lên Fanpage, không dừng chờ bạn duyệt"><input type="checkbox" data-auto-post ${n.auto_post ? 'checked' : ''}> 🚀 Tự đăng không cần duyệt</label>
          <small class="${n.auto_post ? 'warn-text' : 'muted'}">${n.auto_post ? '⚠ Khi chạy sẽ ĐĂNG THẲNG lên Fanpage, không hỏi lại — tắt ô trên nếu muốn xem trước.'
            : '🔒 Dừng chờ bạn bấm “Đồng ý đăng” trên node trước khi đăng.'}</small>` : ''}
        ${n.wtype === 'fb_ad' ? '<small class="muted">Quảng cáo tạo ở trạng thái TẠM DỪNG — bật ở mục Quảng cáo Facebook khi sẵn sàng.</small>' : ''}
        <div class="cv-panel-row"><span class="cv-sp"></span><button class="btn primary sm" data-p="go"></button></div>`;
      panel.querySelectorAll('[data-c]').forEach(el => {
        const key = el.dataset.c;
        const field = s.fields.find(f => f.key === key);
        const value = () => (el.type === 'checkbox' ? el.checked : el.value);
        const redraw = el.tagName === 'SELECT' || el.type === 'checkbox' || s.fields.some(f => f.when && key in f.when);
        el.oninput = () => saveConfig(n.id, { [key]: value() }, false);
        el.onchange = () => saveConfig(n.id, { [key]: value() }, redraw && field);
      });
      bindTitle(panel, n.id);
      const askToggle = panel.querySelector('[data-ask-toggle]');
      if (askToggle) askToggle.onchange = () => setOption(n.id, 'ask', askToggle.checked);
      const autoPost = panel.querySelector('[data-auto-post]');
      if (autoPost) {
        autoPost.onchange = async () => {
          const cur = node(n.id);
          const page = ((SRC.fb || {}).pages || []).find(p => p.id === (cur.config || {}).page_id);
          if (autoPost.checked && !confirm(`Bật TỰ ĐĂNG cho khối ${n.id}${cur.title ? ` (${cur.title})` : ''}?\n\nKhi chạy, bài sẽ được đăng${n.wtype === 'fb_schedule' ? ' / hẹn giờ' : ''} thẳng lên Fanpage “${page ? page.name : 'đã chọn'}” mà KHÔNG dừng chờ bạn duyệt nội dung.`)) {
            autoPost.checked = false;
            return;
          }
          await setOption(n.id, 'auto_post', autoPost.checked);
          drawWfPanel(node(n.id), true);
        };
      }
      panel.querySelectorAll('[data-reload-src]').forEach(b => { b.onclick = async () => { await loadSources(true); drawWfPanel(node(n.id), true); }; });
      panel.querySelectorAll('[data-pickfile]').forEach(b => {
        b.onclick = async () => {
          const res = await call('canvas_pick_files', b.dataset.kind);
          if (!res || !res.files.length) return;
          const cur = node(n.id).config[b.dataset.pickfile] || [];
          saveConfig(n.id, { [b.dataset.pickfile]: b.dataset.single === '1' ? res.files.slice(0, 1) : [...cur, ...res.files] }, true);
        };
      });
      panel.querySelectorAll('[data-rmfile]').forEach(b => {
        b.onclick = () => {
          const [key, i] = b.dataset.rmfile.split(':');
          saveConfig(n.id, { [key]: (node(n.id).config[key] || []).filter((_, j) => j !== Number(i)) }, true);
        };
      });
      const out = panel.querySelector('[data-out]');
      if (out) {
        out.oninput = () => {
          node(n.id).out = { ...(node(n.id).out || {}), text: out.value };
          clearTimeout(C.promptT);
          C.promptT = setTimeout(() => call('canvas_update_nodes', C.board.id, [{ id: n.id, out_text: out.value }]), 600);
        };
      }
      panel.querySelector('[data-p="go"]').onclick = () => (isBusy(node(n.id)) ? act('cancel', n.id) : runWf(n.id));
      if (keep) { const el = panel.querySelector(`[data-c="${keep}"]`); if (el) el.focus(); }
    }
    const go = panel.querySelector('[data-p="go"]');
    go.textContent = busy ? `⏹ Dừng${n.status === 'waiting' ? '' : ` (${Math.round(n.pct || 0)}%)`}` : n.status === 'done' ? '↻ Chạy lại' : '▶ Chạy';
    go.classList.toggle('danger', busy);
    const el = root.querySelector(`[data-node="${n.id}"]`);
    panel.style.left = `${n.x}px`;
    panel.style.top = `${n.y + (el ? el.offsetHeight : 300) + 14}px`;
    panel.style.width = `${Math.max(400, el ? el.offsetWidth : 300)}px`;
  }

  function drawUploadPanel(n) {
    // Ảnh đầu vào: tải sẵn ảnh, hoặc ❓ hỏi chọn ảnh mỗi lần chạy quy trình
    const root = body();
    let panel = root.querySelector('.cv-panel');
    if (!panel || panel.dataset.for !== n.id) {
      if (panel) panel.remove();
      panel = document.createElement('div');
      panel.className = 'cv-panel';
      panel.dataset.for = n.id;
      panel.onpointerdown = e => e.stopPropagation();
      root.querySelector('.cv-nodes').appendChild(panel);
    }
    const has = (n.urls || []).length > 0;
    panel.innerHTML = `${titleInput(n)}<div class="cv-in-note">${has ? 'Ảnh đã tải sẵn — dùng cho mọi lần chạy' : 'Chưa có ảnh'}${n.ask ? ' · <b>❓ sẽ hỏi chọn ảnh khi chạy quy trình</b>' : ''}</div>
      <div class="cv-panel-row"><button class="btn ${has ? 'ghost' : 'primary'} sm" data-up-pick type="button">⬆ ${has ? 'Chọn ảnh khác…' : 'Chọn ảnh…'}</button>
        <label class="cv-opt-check" title="Mỗi lần ▶ Chạy toàn bộ / Đến đây / Từ đây, app hỏi chọn ảnh cho đầu vào này (vd. mỗi lần 1 sản phẩm khác)"><input type="checkbox" data-up-ask ${n.ask ? 'checked' : ''}> ❓ Hỏi chọn ảnh mỗi lần chạy</label></div>`;
    bindTitle(panel, n.id);
    panel.querySelector('[data-up-pick]').onclick = () => act('replace', n.id);
    panel.querySelector('[data-up-ask]').onchange = e => setOption(n.id, 'ask', e.target.checked);
    const el = root.querySelector(`[data-node="${n.id}"]`);
    panel.style.left = `${n.x}px`;
    panel.style.top = `${n.y + (el ? el.offsetHeight : 300) + 14}px`;
    panel.style.width = `${Math.max(380, el ? el.offsetWidth : 300)}px`;
  }

  async function runWf(id) {
    clearTimeout(C.promptT);
    const n = node(id);
    const payload = { id, config: n.config || {} };
    if ((n.out || {}).text !== undefined) payload.out_text = n.out.text;
    await call('canvas_update_nodes', C.board.id, [payload]);
    if (['fb_post', 'fb_schedule', 'fb_ad'].includes(n.wtype)
      && !confirm(n.wtype === 'fb_ad' ? 'Tạo quảng cáo (trạng thái TẠM DỪNG, chưa tiêu tiền) cho bài viết nối vào?'
        : n.auto_post ? '🚀 Chạy khối TỰ ĐĂNG? Bài sẽ được đăng thẳng lên Fanpage, KHÔNG dừng chờ duyệt.'
          : 'Chạy khối đăng bài? App sẽ dừng chờ bạn duyệt nội dung trước khi đăng.')) return;
    const res = await call('canvas_generate', C.board.id, id);
    if (res) { C.board = res.board; drawAll(); }
  }

  // khối chữ nối vào node Video dùng làm nguồn lời thoại được (Văn bản, AI viết, Tạo content…)
  const dialogueSources = n => (n.inputs || []).map(node).filter(x => x && x.kind === 'wf' && outTypes(x).has('text') && !outTypes(x).has('video'));
  // nguồn prompt của node Ảnh / Video ('' = ghép, 'own' = chỉ viết trực tiếp, id = khối nối vào; khối đã bỏ nối → '')
  const promptSrc = n => { const s = n.prompt_src || ''; return s === 'own' || (s && (n.inputs || []).includes(s) && node(s)) ? s : ''; };
  const sourceText = src => (!src ? '' : src.wtype === 'input_text' && !(src.out || {}).text ? (src.config || {}).text || '' : (src.out || {}).text || '');
  const spokenText = n => (n.dialogue_src && node(n.dialogue_src) ? sourceText(node(n.dialogue_src)) : n.dialogue || '');
  const typedDialogue = dlg => (dlg && !dlg.readOnly ? { dialogue: dlg.value } : {});  // lấy từ khối → không ghi đè chữ tự nhập

  function dialogueCount(panel, n) {
    // đếm chữ lời thoại (bỏ "Tên:" đầu dòng) so với số chữ nói kịp trong thời lượng clip
    const el = panel.querySelector('[data-dlg-count]');
    if (!el) return;
    const words = String(spokenText(n)).replace(/^[^:\n]{1,30}:\s*/gm, '').split(/\s+/).filter(Boolean).length;
    const secs = parseInt(String(n.duration || '10s'), 10) || 10;
    const limit = Math.max(4, Math.floor((secs - 1) * ((C.meta && C.meta.words_per_sec) || 3.2)));
    el.className = words > limit ? 'warn-text' : 'muted';
    el.textContent = words ? `${words}/${limit} chữ cho ${secs} giây${words > limit ? ' — dài, dễ nói vội / bị cắt' : ''}` : `nói kịp ~${limit} chữ trong ${secs} giây`;
  }

  function placeTools() {
    const root = body();
    const tools = root.querySelector('.cv-tools');
    const n = node(C.sel);
    const el = n && root.querySelector(`[data-node="${n.id}"]`);
    if (!tools || !el || tools.classList.contains('hidden')) return;
    const { x, y, k } = C.view;
    tools.style.left = `${x + (n.x + el.offsetWidth / 2) * k}px`;
    tools.style.top = `${y + n.y * k - 12}px`;
  }

  async function setOption(id, key, value) {
    const n = node(id);
    n[key] = key === 'count' ? Number(value) : value;
    // prompt / lời thoại đang gõ (chưa kịp lưu) lưu cùng lúc — ô vẽ lại theo dữ liệu đã lưu, không mất chữ vừa gõ
    const extra = {};
    const panel = body().querySelector('.cv-panel');
    if (panel && panel.dataset.for === id && n.kind !== 'wf') {
      const ta = panel.querySelector('textarea:not([data-dlg])');
      const dlg = panel.querySelector('[data-dlg]');
      if (ta && !ta.readOnly) { clearTimeout(C.promptT); extra.prompt = ta.value; }
      if (dlg) { clearTimeout(C.dlgT); Object.assign(extra, typedDialogue(dlg)); }
    }
    const res = await call('canvas_update_nodes', C.board.id, [{ id, ...extra, [key]: n[key] }]);
    if (res) { C.board = res.board; drawNode(node(id)); drawEdges(); drawPanel(); }
  }

  async function pick(id, i) {
    const res = await call('canvas_update_nodes', C.board.id, [{ id, pick: i }]);
    if (res) { C.board = res.board; drawAll(); }
  }

  /* ---------------------------------------------------------------- hành động */
  async function addAt(kind, opts = {}) {
    if (!C.board) return;
    const r = body().querySelector('.cv-stage').getBoundingClientRect();
    const spot = freeSpot(opts.x ?? Math.round((r.width / 2 - C.view.x) / C.view.k - 120),
      opts.y ?? Math.round((r.height / 3 - C.view.y) / C.view.k - 120));
    const { x, y } = spot;
    const res = kind === 'upload' && !opts.empty ? await call('canvas_upload', C.board.id, x, y)
      : await call('canvas_add_node', C.board.id, kind, x, y, opts.inputs || [], opts.prompt || '', opts.wtype || '');
    if (!res || !res.result) return;
    C.board = res.result.board;
    C.sel = res.result.node.id;
    drawAll();
    drawPanel(true);
  }

  function freeSpot(x, y) {
    // node mới không chồng lên node cũ (kể cả ô prompt bên dưới): dịch sang phải tới chỗ trống
    const W = 360, H = 560;
    const boxes = C.board.nodes.map(n => {
      const el = body().querySelector(`[data-node="${n.id}"]`);
      return { x: n.x, y: n.y, w: el ? el.offsetWidth : 240, h: (el ? el.offsetHeight : 400) + 180 };
    });
    const hit = (px, py) => boxes.some(b => px < b.x + b.w + 40 && px + W > b.x - 40 && py < b.y + b.h && py + H > b.y);
    let px = x;
    for (let i = 0; i < 40 && hit(px, y); i += 1) px += 120;
    return { x: px, y };
  }

  function rightOf(n) {
    const el = body().querySelector(`[data-node="${n.id}"]`);
    return { x: n.x + (el ? el.offsetWidth : 240) + 140, y: n.y };
  }

  async function act(what, id) {
    const n = node(id);
    if (!n) return;
    const bid = C.board.id;
    if (what === 'to-video') return addAt('video', { ...rightOf(n), inputs: [id] });
    if (what === 'edit') return addAt('image', { ...rightOf(n), inputs: [id] });
    if (what === 'view') return lightbox(n);
    if (what === 'download') {
      const res = await call('canvas_download', bid, id);
      if (res && res.path) toast(`Đã lưu: ${res.path}`, 'ok');
      return;
    }
    if (what === 'upscale') {
      toast('Đang phóng to 2×…');
      const res = await call('canvas_upscale', bid, id);
      if (res) { C.board = res.result.board; C.sel = res.result.node.id; drawAll(); toast('Đã phóng to 2× (node mới bên phải)', 'ok'); }
      return;
    }
    if (what === 'dup') {
      const res = await call('canvas_duplicate', bid, id);
      if (res) { C.board = res.result.board; C.sel = res.result.node.id; drawAll(); }
      return;
    }
    if (what === 'cancel') { await call('canvas_cancel', bid, id); return; }
    if (what === 'replace') {
      const res = await call('canvas_replace_image', bid, id);
      if (res && res.result) {
        C.board = res.result.board;
        drawAll();
        const after = C.board.nodes.filter(x => (x.inputs || []).includes(id)).length;
        toast(`Đã thay ảnh${after ? ` — ${after} node phía sau sẽ dùng ảnh mới ở lần chạy tới` : ''}`, 'ok');
      }
      return;
    }
    if (what === 'run-to') return runFlow('to', id, false);
    if (what === 'run-from') return runFlow('from', id, false);
    if (what === 'open-result') { await call('canvas_open_result', bid, id); return; }
    if (what === 'view-post') {  // cửa sổ trình duyệt nhỏ, dọc, sát mép phải (giữ đăng nhập Facebook của Chrome)
      const url = ((n.out || {}).post || {}).url;
      if (url) await call('open_url', url, true);
      return;
    }
    if (what === 'copy') {
      try { await navigator.clipboard.writeText((n.out || {}).text || ''); toast('Đã sao chép', 'ok'); } catch (err) { toast('Không sao chép được', 'error'); }
      return;
    }
    if (what.startsWith('wf:')) return addAt('wf', { ...rightOf(n), inputs: [id], wtype: what.slice(3) });
    if (what === 'del') {
      if ((n.urls || []).length && !confirm('Xoá node này và kết quả của nó?')) return;
      const res = await call('canvas_delete_node', bid, id);
      if (res) { C.board = res.board; C.sel = ''; drawAll(); }
    }
  }

  async function generate(id) {
    clearTimeout(C.promptT);
    const n = node(id);
    const panel = body().querySelector('.cv-panel');
    clearTimeout(C.dlgT);
    const dlg = panel && panel.dataset.for === id ? panel.querySelector('[data-dlg]') : null;
    if (panel && panel.dataset.for === id && !panel.querySelector('textarea').readOnly) n.prompt = panel.querySelector('textarea').value;
    Object.assign(n, typedDialogue(dlg));
    await call('canvas_update_nodes', C.board.id, [{ id, prompt: n.prompt || '', ...typedDialogue(dlg) }]);
    const res = await call('canvas_generate', C.board.id, id);
    if (res) { C.board = res.board; drawAll(); }
  }

  async function enhance(id) {
    clearTimeout(C.promptT);
    const panel = body().querySelector('.cv-panel');
    if (panel && panel.dataset.for === id && !panel.querySelector('textarea').readOnly) await call('canvas_update_nodes', C.board.id, [{ id, prompt: panel.querySelector('textarea').value }]);
    const res = await call('canvas_enhance', C.board.id, id, '');
    if (res) toast('✨ Đang nhờ model chữ viết lại prompt (model trình duyệt mất 1–2 phút)…');
  }

  function lightbox(n) {
    const url = mediaUrl(n);
    const box = document.createElement('div');
    box.className = 'cv-lightbox';
    box.innerHTML = `${/\.(mp4|mov|webm|m4v)(\?|$)/i.test(url) ? `<video src="${esc(url)}" controls autoplay></video>` : `<img src="${esc(url)}" alt="">`}
      <button class="btn ghost sm" type="button">✕ Đóng</button>`;
    box.onclick = e => { if (e.target === box || e.target.tagName === 'BUTTON') box.remove(); };
    document.body.appendChild(box);
  }

  /* ---------------------------------------------------------------- menu ＋ (tạo tiếp từ ảnh) */
  // gợi ý bước tiếp theo theo kiểu dữ liệu node đưa ra
  const NEXT = {
    images: [['to-video', '🎬 Video từ ảnh này'], ['edit', '🖌 Ảnh mới dùng ảnh này làm tham chiếu'], ['wf:fb_post', '📣 Đăng bài Facebook'],
      ['wf:ai_text', '✦ AI viết (mô tả ảnh, viết prompt)'], ['wf:studio_video', '🎬 Video dài từ storyboard']],
    video: [['wf:dub_vieneu', '🎙 Lồng tiếng VieNeu'], ['wf:post_video', '🎞 Hậu kỳ video (Claude + Remotion)'], ['vid-ref', '🎬 Video mới dùng video này làm tham chiếu'], ['wf:fb_post', '📣 Đăng bài Facebook'],
      ['wf:fb_schedule', '🗓 Lên lịch đăng'], ['wf:concat_video', '⧉ Ghép video']],
    text: [['img-from-text', '🖼 Ảnh từ chữ này (làm prompt)'], ['vid-dialogue', '🎬 Video dùng chữ này làm lời thoại'], ['wf:ai_text', '✦ AI viết / xử lý tiếp'], ['wf:content_post', '📝 Tạo content bài viết'],
      ['wf:fb_post', '📣 Đăng bài (làm caption)'], ['wf:studio_video', '🎬 Video dài từ storyboard'], ['wf:whiteboard_video', '✍ Whiteboard']],
    post: [['wf:fb_ad', '🎯 Tạo quảng cáo (tạm dừng)']],
    collect: [['wf:output', '★ Gom vào khối Kết quả']],
  };

  function showMenu(id, sx, sy) {
    const menu = body().querySelector('.cv-menu');
    const n = node(id);
    const ready = n.kind === 'wf' ? n.status === 'done' || n.wtype === 'input_text' : (n.urls || []).length > 0;
    const seen = new Set();
    const kinds = [...outTypes(n), ...(n.wtype === 'output' ? [] : ['collect'])];
    const items = kinds.flatMap(t => NEXT[t] || []).filter(([k]) => !seen.has(k) && seen.add(k));
    menu.innerHTML = `<b>Tạo tiếp từ ${esc(n.id)} · ${esc(nameOf(n))}</b>
      ${items.map(([k, label]) => `<button data-m="${k}" ${ready || k.startsWith('wf:') || k === 'img-from-text' ? '' : 'disabled'}>${esc(label)}</button>`).join('')}
      ${ready ? '' : '<small class="muted">Nối trước được — chạy node này xong thì node sau mới có dữ liệu</small>'}`;
    menu.style.left = `${sx}px`;
    menu.style.top = `${sy}px`;
    menu.classList.remove('hidden');
    menu.querySelectorAll('[data-m]').forEach(b => {
      b.onclick = () => {
        hideMenu();
        if (b.dataset.m === 'img-from-text') return addAt('image', { ...rightOf(n), inputs: [id] });
        if (b.dataset.m === 'vid-ref') return addAt('video', { ...rightOf(n), inputs: [id] });
        if (b.dataset.m === 'vid-dialogue') {
          return addAt('video', { ...rightOf(n), inputs: [id] }).then(() => { if (C.sel && C.sel !== id) setOption(C.sel, 'dialogue_src', id); });
        }
        act(b.dataset.m, id);
      };
    });
  }

  function showBlocks(anchorEl) {
    const menu = body().querySelector('.cv-menu');
    const groups = { input: 'Đầu vào', ai: 'AI xử lý', create: 'Tạo nội dung', output: 'Đầu ra' };
    const types = Object.entries(C.meta.wf_types);
    menu.innerHTML = Object.entries(groups).map(([g, label]) => {
      const rows = types.filter(([, s]) => s.group === g);
      // Ảnh đầu vào = node ⬆ ảnh tải lên của Canvas (chọn được nhiều ảnh, mỗi ảnh 1 node)
      const extra = g === 'input' ? '<button data-blk-upload title="Ảnh sản phẩm, nhân vật, ảnh tham chiếu — chọn nhiều ảnh trên máy">🖼 Ảnh đầu vào</button>' : '';
      return rows.length || extra ? `<b>${esc(label)}</b>${extra}${rows.map(([k, s]) => `<button data-blk="${k}" title="${esc(s.desc)}">${esc(s.icon)} ${esc(s.name)}</button>`).join('')}` : '';
    }).join('');
    const stage = body().querySelector('.cv-stage').getBoundingClientRect();
    const r = anchorEl.getBoundingClientRect();
    menu.classList.remove('hidden');
    menu.style.left = `${r.left - stage.left - 40}px`;
    menu.style.top = `${Math.max(8, r.top - stage.top - menu.offsetHeight - 10)}px`;
    menu.querySelectorAll('[data-blk]').forEach(b => { b.onclick = () => { hideMenu(); addAt('wf', { wtype: b.dataset.blk }); }; });
    const up = menu.querySelector('[data-blk-upload]');
    if (up) up.onclick = () => { hideMenu(); addAt('upload', { empty: true }); };
  }
  const hideMenu = () => { const m = body().querySelector('.cv-menu'); if (m) m.classList.add('hidden'); };

  /* ---------------------------------------------------------------- kéo, nối, zoom */
  function applyView() {
    const root = body();
    const world = root.querySelector('.cv-world');
    if (!world) return;
    const { x, y, k } = C.view;
    world.style.transform = `translate(${x}px, ${y}px) scale(${k})`;
    const stage = root.querySelector('.cv-stage');
    stage.style.backgroundPosition = `${x}px ${y}px`;
    stage.style.backgroundSize = `${22 * k}px ${22 * k}px`;
    root.querySelector('.cv-zoom').textContent = `${Math.round(k * 100)}%`;
    placeTools();
  }

  function zoomBy(f, cx, cy) {
    const r = body().querySelector('.cv-stage').getBoundingClientRect();
    const px = cx ?? r.width / 2, py = cy ?? r.height / 2;
    const k = Math.min(2.5, Math.max(0.2, C.view.k * f));
    C.view.x = px - (px - C.view.x) * (k / C.view.k);
    C.view.y = py - (py - C.view.y) * (k / C.view.k);
    C.view.k = k;
    applyView();
  }

  function fitView() {
    const root = body();
    const stage = root.querySelector('.cv-stage');
    if (!stage || !C.board || !(C.board.nodes.length || groups().length)) return;
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    groups().forEach(g => { x1 = Math.min(x1, g.x); y1 = Math.min(y1, g.y); x2 = Math.max(x2, g.x + g.w); y2 = Math.max(y2, g.y + g.h); });
    C.board.nodes.forEach(n => {
      const el = root.querySelector(`[data-node="${n.id}"]`);
      x1 = Math.min(x1, n.x); y1 = Math.min(y1, n.y);
      x2 = Math.max(x2, n.x + (el ? el.offsetWidth : 240)); y2 = Math.max(y2, n.y + (el ? el.offsetHeight : 300));
    });
    const r = stage.getBoundingClientRect();
    const k = Math.min(1.2, Math.max(0.2, Math.min((r.width - 120) / (x2 - x1 || 1), (r.height - 200) / (y2 - y1 || 1))));
    C.view = { k, x: (r.width - (x2 - x1) * k) / 2 - x1 * k, y: 60 - y1 * k };
    applyView();
  }

  function toWorld(e) {
    const r = body().querySelector('.cv-stage').getBoundingClientRect();
    return { x: (e.clientX - r.left - C.view.x) / C.view.k, y: (e.clientY - r.top - C.view.y) / C.view.k };
  }

  function bindStage(stage) {
    stage.onwheel = e => {
      if (e.target.closest('.cv-assist')) return;  // cuộn khung trợ lý, không zoom
      if (e.target.closest('.cv-group-note')) {  // cuộn ghi chú dài / ô đang viết, không zoom
        const sc = e.target.closest('textarea') || e.target.closest('.cv-group-note');
        if (sc.scrollHeight > sc.clientHeight) return;
      }
      e.preventDefault();
      const r = stage.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
    };
    stage.onkeydown = e => {
      if (e.target !== stage) return;
      if ((e.key === 'Delete' || e.key === 'Backspace') && C.sel) act('del', C.sel);
      else if ((e.key === 'Delete' || e.key === 'Backspace') && C.gsel) deleteGroup(C.gsel);
      if (e.key === 'Escape') selectNode('');
    };
    stage.onpointerdown = e => {
      if (e.button !== 0 || e.target.closest('.cv-tools, .cv-menu, .cv-empty, .cv-panel, .cv-assist')) return;
      hideMenu();
      const portEl = e.target.closest('.cv-port.out');
      const nodeEl = e.target.closest('.cv-node');
      if (portEl && nodeEl) return dragConnect(e, nodeEl.dataset.node);
      if (nodeEl && e.target.closest('.cv-node-resize')) return resizeNode(e, nodeEl.dataset.node);
      if (nodeEl) return dragNode(e, nodeEl.dataset.node);
      const groupEl = e.target.closest('.cv-group');
      if (groupEl) return groupPointer(e, groupEl.dataset.group);
      if (e.shiftKey) { selectNode(''); return marquee(e); }
      stage.focus();
      selectNode('');
      const start = { x: e.clientX, y: e.clientY, vx: C.view.x, vy: C.view.y };
      stage.classList.add('panning');
      const move = ev => { C.view.x = start.vx + ev.clientX - start.x; C.view.y = start.vy + ev.clientY - start.y; applyView(); };
      const up = () => { stage.classList.remove('panning'); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    };
  }

  function dragNode(e, id) {
    const n = node(id);
    const start = { x: e.clientX, y: e.clientY, nx: n.x, ny: n.y };
    const el = body().querySelector(`[data-node="${id}"]`);
    let moved = false;
    const move = ev => {
      const dx = (ev.clientX - start.x) / C.view.k, dy = (ev.clientY - start.y) / C.view.k;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      n.x = Math.round(start.nx + dx);
      n.y = Math.round(start.ny + dy);
      el.style.left = `${n.x}px`;
      el.style.top = `${n.y}px`;
      drawEdges();
      if (C.sel === id) drawPanel();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) { call('canvas_update_nodes', C.board.id, [{ id, x: n.x, y: n.y }]); if (groups().length) drawGroups(); }
      else if (C.sel !== id) selectNode(id);
      body().querySelector('.cv-stage').focus({ preventScroll: true });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /** Kéo góc dưới-phải node Ảnh / Video / Tải lên → đổi chiều rộng (chiều cao theo tỉ lệ khung), lưu vào node.w. */
  function resizeNode(e, id) {
    e.stopPropagation();
    const n = node(id);
    const el = body().querySelector(`[data-node="${id}"]`);
    const start = { x: e.clientX, w: widthOf(n) };
    const move = ev => {
      n.w = Math.max(120, Math.min(800, Math.round(start.w + (ev.clientX - start.x) / C.view.k)));
      el.style.width = `${n.w}px`;
      drawEdges();
      if (C.sel === id) drawPanel();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (n.w !== start.w) resizeNodeTo(id, n.w);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  async function resizeNodeTo(id, w) {
    const res = await call('canvas_update_nodes', C.board.id, [{ id, w }]);
    if (res) { C.board = res.board; drawNode(node(id)); drawEdges(); if (C.sel === id) drawPanel(); if (groups().length) drawGroups(); }
  }

  function dragConnect(e, src) {
    e.stopPropagation();
    const a = anchor(src, 'out');
    const start = { x: e.clientX, y: e.clientY };
    let moved = false;
    const move = ev => {
      if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 5) return;
      moved = true;
      drawEdges({ a, b: toWorld(ev) });
    };
    const up = async ev => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (!moved) {  // bấm (không kéo) → menu tạo tiếp
        const r = body().querySelector('.cv-stage').getBoundingClientRect();
        return showMenu(src, ev.clientX - r.left + 10, ev.clientY - r.top);
      }
      const target = document.elementFromPoint(ev.clientX, ev.clientY);
      const dst = target && target.closest('.cv-node');
      drawEdges();
      if (!dst || dst.dataset.node === src) return;
      const res = await call('canvas_connect', C.board.id, src, dst.dataset.node, true);
      if (res) { C.board = res.board; drawAll(); }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /* ---------------------------------------------------------------- 🤖 trợ lý Claude: điều phối + đánh giá */
  const AS_QUICK = [
    ['📊 Đánh giá kết quả', 'Đánh giá kết quả hiện tại của quy trình (ảnh / video / chữ / bài đăng): chấm điểm từng node, chỉ ra lỗi cụ thể và đề xuất sửa.'],
    ['✨ Đề xuất cải thiện', 'Xem toàn bộ quy trình và đề xuất cách cải thiện (prompt, model, thứ tự khối) để kết quả tốt hơn mà tốn ít lượt tạo nhất.'],
    ['🧭 Bước tiếp theo', 'Quy trình đang ở bước nào? Tôi nên làm gì tiếp theo (chạy node nào, sửa gì trước khi đăng)?'],
    ['🧩 Dựng quy trình…', 'Dựng giúp tôi quy trình: '],
  ];

  async function toggleAssist(force) {
    const box = body().querySelector('.cv-assist');
    if (!box) return;
    C.assist.open = force ?? !C.assist.open;
    box.classList.toggle('hidden', !C.assist.open);
    body().querySelector('[data-cv="assist"]').classList.toggle('on', C.assist.open);
    if (!C.assist.open) return;
    const side = body().querySelector('.cv-side');
    if (side) side.classList.add('hidden');
    box.onwheel = e => e.stopPropagation();
    if (!C.assist.sending) {  // mở khung → luôn tải bản mới (tự điều phối có thể đã thêm vòng chấm khi khung đóng)
      const res = await call('canvas_assist_get', C.board.id);
      C.assist.chat = res ? res.chat : (C.assist.chat || { messages: [] });
      C.assist.sending = !!C.assist.chat.busy;
    }
    drawAssist(true);
  }

  /* ---- tự điều phối: chạy xong → Claude chấm theo tiêu chí → khối chưa đạt được giao làm lại (tự chạy lại) */
  const AUTO_ST = { reviewing: ['run', '⏳ Đang chấm'], reworking: ['run', '🔁 Đang làm lại'], passed: ['ok', '✓ Đạt'],
    failed: ['bad', '✗ Chưa đạt'], stopped: ['', '⏹ Đã dừng'] };

  function autoHtml(chat) {
    const a = { on: false, criteria: '', pass_score: 8, rounds: 2, attach: true, ...(chat.auto || {}) };
    const st = chat.auto_state || {};
    const [cls, txt] = AUTO_ST[st.status] || ['', ''];
    const active = ['reviewing', 'reworking'].includes(st.status);
    const open = !!C.assist.autoOpen;  // thu gọn mặc định — không chiếm chỗ của khung chat
    return `<div class="cv-as-auto ${a.on ? 'on' : ''}">
      <div class="cv-as-auto-head"><label class="cv-opt-check" title="Sau mỗi lần chạy quy trình, Claude chấm theo tiêu chí và tự giao khối chưa đạt làm lại">
          <input type="checkbox" data-auto-on ${a.on ? 'checked' : ''}> <b>🤖 Tự điều phối</b></label>
        ${a.on && txt ? `<span class="cv-as-auto-st ${cls}">${txt}${st.round ? ` · vòng ${st.round}/${a.rounds}` : ''}</span>`
          : !a.criteria ? '<small class="muted">chưa có tiêu chí</small>' : !a.on ? '<small class="muted">đang tắt</small>' : ''}
        <span class="cv-sp"></span>
        ${active ? '<button class="btn danger sm" type="button" data-auto-stop title="Dừng chấm / làm lại">⏹ Dừng</button>' : ''}
        <button class="btn ghost sm" type="button" data-auto-edit>${open ? '▴ Thu gọn' : '⚙ Tiêu chí'}</button></div>
      <div class="cv-as-auto-body ${open ? '' : 'hidden'}">
        <textarea data-auto-criteria rows="4" placeholder="Tiêu chí đạt — VD: Ảnh thấy rõ xô BOSS 1 ở giữa, chữ tiếng Việt đúng dấu; video 9:16 có người cầm sản phẩm, không méo hình; caption có giá + SĐT, không sai chính tả…">${esc(a.criteria)}</textarea>
        <div class="cv-as-row"><label>Điểm đạt <select data-auto-score>${[6, 7, 8, 9].map(n => `<option value="${n}" ${Number(a.pass_score) === n ? 'selected' : ''}>${n}/10</option>`).join('')}</select></label>
          <label>Làm lại tối đa <select data-auto-rounds>${[1, 2, 3].map(n => `<option value="${n}" ${Number(a.rounds) === n ? 'selected' : ''}>${n} vòng</option>`).join('')}</select></label>
          <label class="cv-opt-check"><input type="checkbox" data-auto-attach ${a.attach ? 'checked' : ''}> 📎 Kèm ảnh</label>
          <span class="cv-sp"></span><button class="btn primary sm" type="button" data-auto-save>Lưu</button></div>
        <small class="muted">Chạy xong → Claude chấm; khối chưa đạt được giao sửa và <b>tự chạy lại</b> (tốn lượt model). Không tự chạy lại khối Đăng bài / Lên lịch / Quảng cáo.</small>
      </div></div>`;
  }

  function autoForm(box) {
    return { criteria: box.querySelector('[data-auto-criteria]').value, pass_score: Number(box.querySelector('[data-auto-score]').value),
      rounds: Number(box.querySelector('[data-auto-rounds]').value), attach: box.querySelector('[data-auto-attach]').checked };
  }

  async function saveAuto(cfg, msg) {
    const res = await call('canvas_assist_auto', C.board.id, cfg);
    if (res) { C.assist.chat = res.chat; drawAssist(); if (msg) toast(msg, 'ok'); }
    else drawAssist();
  }

  function bindAuto(box) {
    const on = box.querySelector('[data-auto-on]');
    if (!on) return;
    on.onchange = () => {
      const f = autoForm(box);
      if (!on.checked) return saveAuto({ on: false }, 'Đã tắt tự điều phối');
      if (!f.criteria.trim()) {
        on.checked = false;
        C.assist.autoOpen = true;
        drawAssist();
        toast('Nhập tiêu chí đạt trước khi bật tự điều phối', 'warn');
        return box.querySelector('[data-auto-criteria]') && body().querySelector('[data-auto-criteria]').focus();
      }
      if (!confirm(`Bật TỰ ĐIỀU PHỐI cho Canvas này?\n\nSau mỗi lần chạy quy trình, Claude chấm kết quả theo tiêu chí (đạt từ ${f.pass_score}/10). Khối chưa đạt sẽ được giao yêu cầu sửa và TỰ CHẠY LẠI — tối đa ${f.rounds} vòng, TỐN LƯỢT model ảnh / video.\n\nKhông tự chạy lại khối Đăng bài / Lên lịch / Quảng cáo. Bấm ⏹ Dừng bất cứ lúc nào.`)) {
        on.checked = false;
        return;
      }
      saveAuto({ ...f, on: true }, 'Đã bật tự điều phối — chạy quy trình để Claude bắt đầu chấm');
    };
    box.querySelector('[data-auto-save]').onclick = () => saveAuto(autoForm(box), 'Đã lưu tiêu chí');
    box.querySelector('[data-auto-edit]').onclick = () => {
      const body0 = box.querySelector('.cv-as-auto-body');
      C.assist.autoOpen = body0.classList.contains('hidden');
      drawAssist();
    };
    box.querySelector('[data-auto-criteria]').onkeydown = e => e.stopPropagation();
    const stop = box.querySelector('[data-auto-stop]');
    if (stop) {
      stop.onclick = async () => {
        const res = await call('canvas_assist_stop', C.board.id);
        if (res) { C.assist.chat = res.chat; drawAssist(); }
      };
    }
  }

  function autoTag(m) {
    if (!m.auto || m.auto.passed === undefined) return '';
    const a = m.auto;
    return `<div class="cv-as-auto-tag ${a.passed ? 'ok' : 'bad'}">🤖 Tự chấm${a.round ? ` sau vòng làm lại ${a.round}` : ''} ·
      <b>${a.passed ? 'ĐẠT' : 'CHƯA ĐẠT'}</b>${a.score != null ? ` · ${a.score}/10` : ''}</div>`;
  }

  function reworkHtml(m) {
    const a = m.auto || {};
    const list = a.rework || [];
    return (list.length ? `<div class="cv-as-rework"><b>🔁 Đã giao làm lại (đang chạy lại):</b><div class="cv-as-nodes">${list.map(x =>
      `<button type="button" data-as-node="${esc(x.node)}" class="mid" title="Bấm để tới node">${esc(x.label)}<small>${esc(x.yeu_cau || 'Prompt / cấu hình mới')}</small></button>`).join('')}</div></div>` : '')
      + (a.note ? `<div class="cv-as-note">${esc(a.note)}</div>` : '');
  }

  function evalHtml(ev) {
    if (!ev) return '';
    const band = d => (d == null ? '' : d >= 8 ? 'good' : d >= 5 ? 'mid' : 'bad');
    return `<div class="cv-as-eval">${ev.diem != null ? `<div class="cv-as-score ${band(ev.diem)}"><b>${ev.diem}</b><small>/10</small></div>` : ''}
      <div class="cv-as-eval-body">${ev.tom_tat ? `<p>${esc(ev.tom_tat)}</p>` : ''}
        ${ev.van_de.length ? `<ul>${ev.van_de.map(v => `<li>${esc(v)}</li>`).join('')}</ul>` : ''}
        ${ev.node.length ? `<div class="cv-as-nodes">${ev.node.map(x => `<button type="button" data-as-node="${esc(x.id)}" class="${band(x.diem)}"
          title="Bấm để tới node">${esc(x.id)}${x.diem != null ? ` · ${x.diem}` : ''}<small>${esc(x.nhan_xet)}</small></button>`).join('')}</div>` : ''}</div></div>`;
  }

  function opsHtml(m) {
    const ops = m.ops || [];
    if (!ops.length) return m.dropped ? `<small class="muted">Bỏ ${m.dropped} đề xuất không hợp lệ</small>` : '';
    const pending = ops.filter(o => !o.applied && o.op !== 'run').length;
    return `<div class="cv-as-ops"><div class="cv-as-ops-head"><b>Đề xuất (${ops.length})</b>
        ${pending > 1 ? `<button class="btn ghost sm" type="button" data-as-all="${esc(m.id)}" title="Áp dụng lần lượt mọi đề xuất chưa áp dụng (trừ ▶ Chạy)">Áp dụng tất cả</button>` : ''}</div>
      ${ops.map((op, i) => `<div class="cv-as-op ${op.applied ? 'done' : ''}">
        <div class="cv-as-op-txt"><b>${esc(op.label)}</b>${op.ly_do ? `<small>${esc(op.ly_do)}</small>` : ''}
          ${op.prompt || op.text ? `<details><summary>Xem nội dung</summary><pre>${esc(op.prompt || op.text)}</pre></details>` : ''}
          ${op.config ? `<details><summary>Xem cấu hình</summary><pre>${esc(JSON.stringify(op.config, null, 2))}</pre></details>` : ''}</div>
        ${op.applied ? '<span class="cv-as-ok" title="Đã áp dụng">✓</span>'
          : op.op === 'run' ? `<button class="btn ghost sm" type="button" data-as-run="${esc(m.id)}" data-i="${i}">▶ Chạy</button>`
            : `<button class="btn primary sm" type="button" data-as-apply="${esc(m.id)}" data-i="${i}">Áp dụng</button>`}</div>`).join('')}
      ${m.dropped ? `<small class="muted">Bỏ ${m.dropped} đề xuất không hợp lệ</small>` : ''}</div>`;
  }

  function drawAssist(scroll) {
    const box = body().querySelector('.cv-assist');
    if (!box || !C.assist.open) return;
    const msgs = (C.assist.chat || {}).messages || [];
    const keep = box.querySelector('[data-as-text]');
    const draft = keep ? keep.value : '';
    const oldList = box.querySelector('.cv-as-msgs');
    const oldScroll = oldList ? oldList.scrollTop : 0;  // vẽ lại (VD sau Áp dụng) giữ nguyên chỗ đang xem
    box.innerHTML = `<div class="cv-as-head"><b>🤖 Trợ lý Claude</b><small class="muted">điều phối · đánh giá</small><span class="cv-sp"></span>
        <button class="btn ghost sm" type="button" data-as="new" title="Cuộc trò chuyện mới (gửi lại toàn bộ quy trình cho Claude)">⟲ Mới</button>
        <button class="btn ghost sm" type="button" data-as="close" title="Đóng">✕</button></div>
      ${autoHtml(C.assist.chat || {})}
      <div class="cv-as-msgs">${msgs.length ? msgs.map(m => (m.role === 'user'
        ? `<div class="cv-as-msg user${m.auto ? ' auto' : ''}">${esc(m.text)}${m.images ? `<small>📎 kèm ${m.images} ảnh kết quả</small>` : ''}</div>`
        : m.error ? `<div class="cv-as-msg err">⚠ ${esc(m.error)}</div>`
          : `<div class="cv-as-msg bot">${autoTag(m)}${m.text ? noteHtml(m.text) : ''}${evalHtml(m.eval)}${reworkHtml(m)}${opsHtml(m)}</div>`)).join('')
        : `<div class="cv-as-intro"><b>Claude đọc toàn bộ Canvas này</b> (khối, prompt, kết quả, lỗi) và có thể xem ảnh kết quả để:
            <ul><li>chấm điểm, chỉ lỗi từng node</li><li>đề xuất sửa prompt / model / thêm & nối khối</li><li>gợi ý bước tiếp theo</li></ul>
            Đề xuất chỉ thay đổi Canvas khi bạn bấm <b>Áp dụng</b>; chạy luôn hỏi xác nhận. Dùng tài khoản claude.ai đã đăng nhập trong app.</div>`}</div>
      <div class="cv-as-status ${C.assist.sending ? '' : 'hidden'}"><span class="cv-spin"></span><span class="cv-as-status-text">${esc(C.assist.status || 'Đang hỏi Claude…')}</span></div>
      <div class="cv-as-quick">${AS_QUICK.map(([l, t], i) => `<button type="button" data-as-q="${i}" title="${esc(t)}">${esc(l)}</button>`).join('')}</div>
      <div class="cv-as-input"><textarea data-as-text rows="3" placeholder="Hỏi trợ lý… (VD: Ảnh n3 có hợp quảng cáo TikTok không? Viết lại prompt cho đẹp hơn)"></textarea>
        <div class="cv-as-row"><label class="cv-opt-check" title="Gửi ảnh kết quả + 1 khung hình mỗi video (tối đa 6) để Claude xem và chấm"><input type="checkbox" data-as-attach ${C.assist.attach === false ? '' : 'checked'}> 📎 Kèm ảnh kết quả</label>
          <button class="link-btn cv-as-browser" type="button" data-as-browser title="Hiện / ẩn cửa sổ trình duyệt dùng chung cho cả app — đổi ở Cài đặt → Trình duyệt">🖥 Trình duyệt: ${state.boot.settings.show_browser ? 'hiện' : 'ẩn'}</button>
          <span class="cv-sp"></span><button class="btn primary sm" type="button" data-as="send" ${C.assist.sending ? 'disabled' : ''}>${C.assist.sending ? 'Đang chờ…' : 'Gửi ➤'}</button></div></div>`;
    const ta = box.querySelector('[data-as-text]');
    ta.value = draft;
    ta.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendAssist(); };
    box.querySelector('[data-as-attach]').onchange = e => { C.assist.attach = e.target.checked; };
    box.querySelector('[data-as-browser]').onclick = () => openSettings('browser');
    box.querySelector('[data-as="send"]').onclick = () => sendAssist();
    box.querySelector('[data-as="close"]').onclick = () => toggleAssist(false);
    box.querySelector('[data-as="new"]').onclick = async () => {
      if (msgs.length && !confirm('Bắt đầu cuộc trò chuyện mới với trợ lý? (Lịch sử trò chuyện của Canvas này sẽ được xoá)')) return;
      const res = await call('canvas_assist_clear', C.board.id);
      if (res) { C.assist.chat = res.chat; drawAssist(); }
    };
    box.querySelectorAll('[data-as-q]').forEach(b => {
      b.onclick = () => {
        const [, text] = AS_QUICK[+b.dataset.asQ];
        if (text.endsWith(': ')) { ta.value = text; ta.focus(); ta.setSelectionRange(text.length, text.length); return; }
        ta.value = text;
        sendAssist();
      };
    });
    box.querySelectorAll('[data-as-node]').forEach(b => { b.onclick = () => focusNode(b.dataset.asNode); });
    bindAuto(box);
    box.querySelectorAll('[data-as-apply]').forEach(b => { b.onclick = () => applyAssist(b.dataset.asApply, +b.dataset.i); });
    box.querySelectorAll('[data-as-all]').forEach(b => { b.onclick = () => applyAllAssist(b.dataset.asAll); });
    box.querySelectorAll('[data-as-run]').forEach(b => {
      b.onclick = () => {
        const m = msgs.find(x => x.id === b.dataset.asRun);
        const op = m && m.ops[+b.dataset.i];
        if (!op) return;
        if (op.mode === 'all') return runFlow('all', '', false);
        return runFlow(op.mode === 'from' ? 'from' : 'to', op.node, false);
      };
    });
    const list = box.querySelector('.cv-as-msgs');
    list.scrollTop = scroll ? list.scrollHeight : oldScroll;
  }

  async function sendAssist() {
    const box = body().querySelector('.cv-assist');
    const ta = box && box.querySelector('[data-as-text]');
    const text = ta ? ta.value.trim() : '';
    if (!text || C.assist.sending) return;
    const bid = C.board.id;
    C.assist.sending = true;
    C.assist.status = 'Đang hỏi Claude…';
    C.assist.chat = C.assist.chat || { messages: [] };
    C.assist.chat.messages = [...C.assist.chat.messages, { role: 'user', text, images: 0 }];
    ta.value = '';
    drawAssist(true);
    const res = await call('canvas_assist_send', bid, text, C.assist.attach !== false);
    if (!C.board || C.board.id !== bid) return;  // đã rời Canvas này trong lúc chờ
    C.assist.sending = false;
    if (res) C.assist.chat = res.chat;
    else { const again = await call('canvas_assist_get', bid); if (again) C.assist.chat = again.chat; }
    drawAssist(true);
  }

  async function applyAssist(mid, i) {
    const res = await call('canvas_assist_apply', C.board.id, mid, i);
    if (!res) return false;
    C.board = res.result.board;
    C.assist.chat = res.result.chat;
    drawAll();
    drawAssist();
    if (res.result.node && node(res.result.node)) {
      C.flash = { ...(C.flash || {}), [res.result.node]: 1 };
      drawNode(node(res.result.node));
      setTimeout(() => { if (C.flash) delete C.flash[res.result.node]; }, 1500);
    }
    return true;
  }

  async function applyAllAssist(mid) {
    const m = ((C.assist.chat || {}).messages || []).find(x => x.id === mid);
    if (!m) return;
    // thêm khối mới trước (đề xuất nối / sửa có thể nhắc tới khối mới), rồi các đề xuất còn lại theo thứ tự
    const order = [...m.ops.keys()].sort((a, b) => (m.ops[b].op === 'add_node') - (m.ops[a].op === 'add_node') || a - b);
    for (const i of order) {
      const cur = ((C.assist.chat || {}).messages || []).find(x => x.id === mid).ops[i];
      if (cur.applied || cur.op === 'run') continue;
      if (!(await applyAssist(mid, i))) return;
    }
    toast('Đã áp dụng các đề xuất của trợ lý', 'ok');
  }

  /* ---------------------------------------------------------------- sự kiện từ backend */
  /* ---------------------------------------------------------------- chạy cả quy trình (như Workflow) */
  const RUN_ICON = { queued: '·', running: '⏳', done: '✓', error: '✕', skipped: '↷', cancelled: '⏹', partial: '◐' };
  const RUN_VI = { running: 'đang chạy', done: 'xong', error: 'có lỗi', partial: 'xong một phần', cancelled: 'đã dừng' };
  const runs = () => (C.board && C.board.runs) || [];

  async function runFlow(mode, target, fresh, asked) {
    if (!C.board) return;
    clearTimeout(C.promptT);
    const panel = body().querySelector('.cv-panel');  // lưu prompt / cấu hình đang gõ trước khi chạy
    if (panel && node(panel.dataset.for)) {
      const n = node(panel.dataset.for);
      const ta = panel.querySelector('textarea:not([data-c]):not([data-out])');
      clearTimeout(C.dlgT);
      const dlg = panel.querySelector('[data-dlg]');
      const patch = { id: n.id, ...(n.kind === 'wf' ? { config: n.config || {} } : { prompt: ta && !ta.readOnly ? ta.value : n.prompt }),
        ...typedDialogue(dlg) };
      await call('canvas_update_nodes', C.board.id, [patch]);
    }
    const res = await call('canvas_preview', C.board.id, mode, target, !!fresh);
    if (!res) return;
    const plan = res.plan;
    if (!asked && (plan.ask || []).length) {  // ❓ đầu vào hỏi khi chạy: chọn ảnh / video trước, rồi tính lại kế hoạch
      if (!(await askInputs(plan.ask))) return;
      return runFlow(mode, target, fresh, true);
    }
    C.issues = Object.fromEntries(plan.issues.map(i => [i.node, i]));
    drawAll();
    const errors = plan.issues.filter(i => i.level === 'error');
    if (errors.length) return showIssues(plan.issues);
    if (!plan.run.length) { toast('Mọi node đã có kết quả mới nhất — không cần chạy (bấm ⟳ Làm lại tất cả để tạo lại)'); return; }
    const warns = plan.issues.filter(i => i.level === 'warn');
    const what = mode === 'all' ? 'cả quy trình' : mode === 'to' ? `đến ${target}` : `từ ${target}`;
    const msg = [`Chạy ${what}${fresh ? ' — LÀM LẠI TẤT CẢ' : ''}:`, `• ${plan.run.length} node sẽ chạy: ${plan.run.map(id => (node(id) && node(id).title ? `${id} (${node(id).title})` : id)).join(' → ')}`,
      plan.reuse.length ? `• ${plan.reuse.length} node dùng lại kết quả cũ (không tốn lượt): ${plan.reuse.join(', ')}` : '',
      plan.posts.length ? `• Có khối đăng bài / quảng cáo (${plan.posts.join(', ')}): app sẽ DỪNG CHỜ bạn duyệt trên node trước khi đăng; quảng cáo tạo ở trạng thái tạm dừng.` : '',
      (plan.auto_posts || []).length ? `• 🚀 TỰ ĐĂNG KHÔNG CẦN DUYỆT: ${plan.auto_posts.map(id => (node(id) && node(id).title ? `${id} (${node(id).title})` : id)).join(', ')} — bài sẽ lên Fanpage ngay khi tới lượt.` : '',
      ...warns.map(w => `⚠ ${w.node}: ${w.message}`)].filter(Boolean).join('\n');
    if (!confirm(msg)) return;
    const run = await call('canvas_run_flow', C.board.id, mode, target, !!fresh);
    if (run) { C.board = run.board; C.issues = {}; drawAll(); toast(`Đang chạy ${plan.run.length} node…`); }
  }

  const inputFile = n => (n.kind === 'upload' ? mediaUrl(n) : ((n.config || {}).files || [])[0] || '');

  const isFileInput = n => n.kind === 'upload' || n.wtype === 'input_video';
  const ASK_TYPES = ['text', 'textarea', 'select', 'check', 'number', 'datetime', 'fb_page', 'ad_account', 'studio_preset'];
  const askCheck = n => `<label class="cv-opt-check" title="Mỗi lần ▶ Chạy toàn bộ / Đến đây / Từ đây, app hỏi lại prompt của node này trước khi chạy"><input type="checkbox" data-f="ask" ${n.ask ? 'checked' : ''}> ❓ Hỏi khi chạy</label>`;

  async function askInputs(ids) {
    // hộp hỏi khi chạy: khối bật "❓ Hỏi khi chạy" → sửa prompt / cấu hình; ảnh / video đầu vào → chọn file
    const list = ids.map(node).filter(Boolean);
    if (list.some(n => n.kind === 'wf' && wspec(n).fields.some(f => ['fb_page', 'ad_account', 'studio_preset'].includes(f.type)))) {
      await loadSources();
    }
    return new Promise(resolve => {
      const box = document.createElement('div');
      box.className = 'cv-lightbox cv-import';
      const title = n => `<div class="cv-ask-title"><b>${esc(n.title || nameOf(n))}</b> <small class="muted">${esc(n.id)} · ${esc(nameOf(n))}</small></div>`;
      const fileInner = n => {
        const f = inputFile(n);
        const video = n.kind !== 'upload';
        return `<span class="cv-ask-thumb">${f ? (video ? '🎞' : `<img src="${esc(thumbUrl(f, 160))}" alt="">`) : '—'}</span>
          <div>${title(n)}<small class="${f ? 'muted' : 'warn-text'}">${f ? (video ? esc(String(f).split(/[\\/]/).pop()) : 'Đang dùng ảnh hiện tại') : 'Chưa có file — bắt buộc chọn'}</small></div>
          <button class="btn ${f ? 'ghost' : 'primary'} sm" data-pick-in="${esc(n.id)}" type="button">${video ? '🎞 Chọn video…' : '🖼 Chọn ảnh…'}</button>`;
      };
      const row = n => {
        if (isFileInput(n)) return `<div class="cv-ask-row" data-file-row="${esc(n.id)}">${fileInner(n)}</div>`;
        if (n.kind !== 'wf') {
          return `<div class="cv-ask-block">${title(n)}<textarea data-ask-prompt="${esc(n.id)}" rows="3" placeholder="Prompt cho lần chạy này…">${esc(n.prompt || '')}</textarea>
            ${n.kind === 'video' && n.dialogue_src && node(n.dialogue_src) ? `<small class="muted">💬 Lời thoại lấy từ khối ${esc(n.dialogue_src)} — sửa ở khối đó</small>`
              : n.kind === 'video' ? `<small class="muted">💬 Lời thoại (mỗi dòng 1 câu; nhiều người: Tên: câu nói)</small>
              <textarea data-ask-dialogue="${esc(n.id)}" rows="2" placeholder="Để trống = không thoại">${esc(n.dialogue || '')}</textarea>` : ''}</div>`;
        }
        const cfg = n.config || {};
        const fields = wspec(n).fields.filter(f => ASK_TYPES.includes(f.type) && f.key !== 'ask' && fieldVisible(f, cfg));
        return `<div class="cv-ask-block" data-ask-wf="${esc(n.id)}">${title(n)}<div class="cv-wf-fields">${fields.map(f => fieldHtml(f, cfg)).join('')
          || '<small class="muted">Khối này không có ô nào để sửa</small>'}</div>
          ${['fb_post', 'fb_schedule'].includes(n.wtype) ? `<label class="cv-opt-check cv-auto-post ${n.auto_post ? 'on' : ''}"><input type="checkbox" data-ask-auto="${esc(n.id)}" ${n.auto_post ? 'checked' : ''}>
            🚀 Tự đăng không cần duyệt <small class="muted">(lần này và các lần chạy sau)</small></label>` : ''}</div>`;
      };
      box.innerHTML = `<div class="cv-import-box cv-ask-box"><div class="cv-side-head"><b>❓ Kiểm tra trước khi chạy</b><button class="btn ghost sm" data-x type="button">✕</button></div>
        <p class="muted">Các khối bật “Hỏi khi chạy”: sửa prompt / thông tin / chọn file cho lần chạy này. Khối nào đổi thì nó và các khối phía sau sẽ chạy lại.</p>
        ${list.map(row).join('')}
        <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn ghost sm" data-x type="button">Huỷ</button>
          <button class="btn primary sm" data-go type="button">▶ Tiếp tục chạy</button></div></div>`;
      const go = box.querySelector('[data-go]');
      const refresh = () => { go.disabled = !list.every(n => !isFileInput(n) || inputFile(node(n.id))); };
      const bindPick = scope => scope.querySelectorAll('[data-pick-in]').forEach(b => {
        b.onclick = async () => {
          const res = await call('canvas_pick_input', C.board.id, b.dataset.pickIn);
          if (!res || !res.result) return;
          C.board = res.result.board;
          drawAll();
          const rowEl = box.querySelector(`[data-file-row="${b.dataset.pickIn}"]`);
          rowEl.innerHTML = fileInner(node(b.dataset.pickIn));
          bindPick(rowEl);
          refresh();
        };
      });
      bindPick(box);
      box.querySelectorAll('[data-ask-auto]').forEach(cb => {
        cb.onchange = () => {
          const n = node(cb.dataset.askAuto);
          const pageSel = box.querySelector(`[data-ask-wf="${cb.dataset.askAuto}"] [data-c="page_id"]`);
          const page = pageSel && pageSel.selectedOptions[0] ? pageSel.selectedOptions[0].textContent.trim() : 'đã chọn';
          if (cb.checked && !confirm(`Bật TỰ ĐĂNG cho khối ${n.id}${n.title ? ` (${n.title})` : ''}?\n\nKhi chạy, bài sẽ được đăng thẳng lên Fanpage “${page}” mà KHÔNG dừng chờ bạn duyệt nội dung.`)) cb.checked = false;
          cb.closest('.cv-auto-post').classList.toggle('on', cb.checked);
        };
      });
      refresh();
      box.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { box.remove(); resolve(false); }; });
      go.onclick = async () => {
        const patches = [];
        box.querySelectorAll('[data-ask-prompt]').forEach(ta => {
          const dlg = box.querySelector(`[data-ask-dialogue="${ta.dataset.askPrompt}"]`);
          patches.push({ id: ta.dataset.askPrompt, prompt: ta.value, ...(dlg ? { dialogue: dlg.value } : {}) });
        });
        box.querySelectorAll('[data-ask-wf]').forEach(blk => {
          const n = node(blk.dataset.askWf);
          const config = { ...(n.config || {}) };
          blk.querySelectorAll('[data-c]').forEach(el => { config[el.dataset.c] = el.type === 'checkbox' ? el.checked : el.value; });
          const auto = blk.querySelector('[data-ask-auto]');
          patches.push({ id: n.id, config, ...(auto ? { auto_post: auto.checked } : {}) });
        });
        if (patches.length) {
          const res = await call('canvas_update_nodes', C.board.id, patches);
          if (!res) return;
          C.board = res.board;
          drawAll();
        }
        box.remove();
        resolve(true);
      };
      document.body.appendChild(box);
    });
  }

  function showIssues(list) {
    const side = body().querySelector('.cv-side');
    side.innerHTML = `<div class="cv-side-head"><b>⚠ Sửa trước khi chạy</b><button class="btn ghost sm" data-close type="button">✕</button></div>
      ${list.map(i => `<button class="cv-issue ${i.level}" data-go="${esc(i.node)}" type="button"><b>${esc(i.node || 'Quy trình')}</b>
        ${node(i.node) ? `<small>${esc(labelOf(node(i.node)))}</small>` : ''}<span>${esc(i.message)}</span></button>`).join('')}`;
    side.classList.remove('hidden');
    side.querySelector('[data-close]').onclick = () => { side.classList.add('hidden'); C.issues = {}; drawAll(); };
    side.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => focusNode(b.dataset.go); });
  }

  function focusNode(id) {
    const n = node(id);
    const el = n && body().querySelector(`[data-node="${id}"]`);
    if (!el) return;
    const r = body().querySelector('.cv-stage').getBoundingClientRect();
    C.view.x = r.width / 2 - (n.x + el.offsetWidth / 2) * C.view.k;
    C.view.y = r.height / 3 - n.y * C.view.k;
    applyView();
    selectNode(id);
  }

  function drawFlow() {
    const chip = body().querySelector('.cv-flow');
    if (!chip || !C.board) return;
    const rec = runs()[runs().length - 1];
    if (!rec) { chip.innerHTML = ''; return; }
    const states = Object.values(rec.nodes || {});
    const done = states.filter(s => ['done', 'error', 'skipped'].includes(s)).length;
    chip.className = `cv-flow ${rec.status}`;
    chip.innerHTML = rec.status === 'running'
      ? `⏳ ${esc(rec.label)} · ${done}/${states.length}${rec.current ? ` · đang chạy <b>${esc(rec.current)}</b>` : ''} <button class="btn ghost sm" data-stop-flow type="button">⏹ Dừng</button>`
      : `${RUN_ICON[rec.status] || ''} Lần chạy gần nhất: ${esc(RUN_VI[rec.status] || rec.status)} · ${esc((rec.ended || rec.at || '').slice(11, 16))}`;
    const stop = chip.querySelector('[data-stop-flow]');
    if (stop) stop.onclick = async () => { if (confirm('Dừng quy trình đang chạy?')) await call('canvas_cancel_flow', C.board.id); };
    drawTray();
  }

  function drawTray() {
    // khay tiến trình như Workflow: tiến độ tổng, chip từng node, nhật ký chạy trực tiếp
    const tray = body().querySelector('.cv-tray');
    if (!tray || !C.board) return;
    const rec = runs()[runs().length - 1];
    if (!rec || (rec.status !== 'running' && C.trayClosed === rec.id)) { tray.classList.add('hidden'); return; }
    const ids = Object.keys(rec.nodes || {});
    const finished = ids.filter(id => ['done', 'error', 'skipped'].includes(rec.nodes[id])).length;
    const cur = rec.status === 'running' && rec.current ? node(rec.current) : null;
    const part = cur && rec.nodes[cur.id] === 'running' ? (cur.pct || 0) / 100 : 0;
    const pct = ids.length ? Math.round(100 * (finished + part) / ids.length) : 0;
    const logs = (C.logs[rec.task] || []).slice(-80);
    tray.className = `cv-tray ${rec.status}`;
    tray.innerHTML = `<div class="cv-tray-head"><b>${RUN_ICON[rec.status] || ''} ${esc(rec.label)}</b>
        <span class="muted">${finished}/${ids.length} node · ${rec.status === 'running' ? `${pct}%` : esc(RUN_VI[rec.status] || rec.status)}</span>
        <div class="cv-tray-bar"><i style="width:${rec.status === 'running' ? pct : 100}%"></i></div>
        ${rec.status === 'running' ? '<button class="btn ghost sm" data-tray-stop type="button">⏹ Dừng</button>'
          : '<button class="btn ghost sm" data-tray-x type="button">✕</button>'}</div>
      <div class="cv-tray-body"><div class="cv-tray-nodes">${ids.map(id => {
        const n = node(id);
        const st = rec.status === 'running' && n && n.status === 'waiting' ? 'waiting' : rec.nodes[id];
        const extra = st === 'running' && n ? ` · ${Math.round(n.pct || 0)}%` : st === 'waiting' ? ' · chờ duyệt' : '';
        return `<button class="cv-tray-node ${esc(st)}" data-go="${esc(id)}" type="button"><span>${st === 'waiting' ? '✋' : RUN_ICON[st] || ''}</span>
          <b>${esc(id)}</b><small>${esc(labelOf(n))}${extra}</small></button>`;
      }).join('')}${(rec.reused || []).length ? `<small class="muted">♻ dùng lại: ${rec.reused.map(esc).join(', ')}</small>` : ''}</div>
        <div class="cv-tray-log">${logs.length ? logs.map(l => `<div class="${esc(l.level || '')}"><span>${esc(l.time || '')}</span> ${esc(l.message || '')}</div>`).join('')
          : '<div class="muted">Đang bắt đầu…</div>'}</div></div>`;
    tray.classList.remove('hidden');
    const log = tray.querySelector('.cv-tray-log');
    log.scrollTop = log.scrollHeight;
    tray.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => focusNode(b.dataset.go); });
    const stop = tray.querySelector('[data-tray-stop]');
    if (stop) stop.onclick = async () => { if (confirm('Dừng quy trình đang chạy?')) await call('canvas_cancel_flow', C.board.id); };
    const x = tray.querySelector('[data-tray-x]');
    if (x) x.onclick = () => { C.trayClosed = rec.id; tray.classList.add('hidden'); };
  }

  function toggleHistory(force) {
    const side = body().querySelector('.cv-side');
    if (!force && !side.classList.contains('hidden') && side.dataset.view === 'history') { side.classList.add('hidden'); return; }
    side.dataset.view = 'history';
    const list = [...runs()].reverse();
    side.innerHTML = `<div class="cv-side-head"><b>🕘 Lịch sử chạy</b><button class="btn ghost sm" data-close type="button">✕</button></div>
      ${list.length ? list.map(r => `<div class="cv-run ${esc(r.status)}"><div><b>${RUN_ICON[r.status] || ''} ${esc(r.label)}</b>
          <small class="muted">${esc(r.at)}${r.ended ? ` → ${esc(r.ended.slice(11))}` : ''} · ${esc(RUN_VI[r.status] || r.status)}</small></div>
        <div class="cv-run-nodes">${Object.entries(r.nodes || {}).map(([id, s]) => `<button class="cv-run-node ${esc(s)}" data-go="${esc(id)}" title="${esc(labelOf(node(id)) + ' · ' + s)}" type="button">${RUN_ICON[s] || ''} ${esc(id)}${node(id) && node(id).title ? ` · ${esc(node(id).title)}` : ''}</button>`).join('')}
          ${(r.reused || []).length ? `<small class="muted">dùng lại: ${r.reused.map(esc).join(', ')}</small>` : ''}</div></div>`).join('')
        : '<p class="muted">Chưa chạy quy trình lần nào — bấm ▶ Chạy toàn bộ.</p>'}`;
    side.classList.remove('hidden');
    side.querySelector('[data-close]').onclick = () => side.classList.add('hidden');
    side.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => focusNode(b.dataset.go); });
  }

  async function importDialog() {
    if (!(await window.requireAdmin('tạo quy trình Canvas từ Workflow / mẫu'))) return;
    const res = await call('canvas_sources');
    if (!res) return;
    const { workflows, presets } = res.sources;
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import';
    box.innerHTML = `<div class="cv-import-box"><div class="cv-side-head"><b>⇩ Tạo Canvas từ Workflow / quy trình mẫu</b><button class="btn ghost sm" data-close type="button">✕</button></div>
      <p class="muted">Giữ bố cục và dây nối. Tạo ảnh / Tạo video → node Ảnh / Video của Canvas; Ảnh đầu vào → ảnh tải lên.</p>
      <b class="cv-import-h">Quy trình mẫu</b>${presets.map(p => `<button class="cv-import-row" data-src="preset" data-ref="${esc(p.id)}" type="button"><b>${esc(p.name)}</b><small class="muted">${esc(p.desc)} · ${p.nodes} khối</small></button>`).join('')}
      <b class="cv-import-h">Workflow đã lưu</b>${workflows.length ? workflows.map(w => `<button class="cv-import-row" data-src="workflow" data-ref="${esc(w.id)}" type="button"><b>${esc(w.name || w.id)}</b><small class="muted">${w.nodes} khối</small></button>`).join('')
        : '<p class="muted">Chưa có Workflow nào.</p>'}</div>`;
    document.body.appendChild(box);
    box.querySelector('[data-close]').onclick = () => box.remove();
    box.onclick = e => { if (e.target === box) box.remove(); };
    box.querySelectorAll('[data-src]').forEach(b => {
      b.onclick = async () => {
        const out = await call('canvas_import', b.dataset.src, b.dataset.ref);
        if (!out) return;
        box.remove();
        C.board = out.result.board;
        C.sel = '';
        renderBoard();
        fitView();
        toast('Đã tạo Canvas từ quy trình', 'ok');
        if (out.result.notes.length) alert(`Lưu ý khi chuyển sang Canvas:\n• ${out.result.notes.join('\n• ')}`);
      };
    });
  }

  function update(event, data) {
    if (event === 'canvas_tasks') {  // chấm nhấp nháy ở mục Canvas trên thanh bên khi có tác vụ đang chạy
      const busy = (data.tasks || []).some(t => t.status === 'queued' || t.status === 'running');
      const item = document.querySelector('.sb-item[data-view="canvas"]');
      if (item) item.classList.toggle('cv-busy-dot', busy);
      return;
    }
    if (event === 'canvas_assist' && C.board && data.board === C.board.id) {  // trạng thái trợ lý (đang hỏi Claude…)
      if (C.assist) C.assist.status = data.text;
      const st = body().querySelector('.cv-as-status-text');
      if (st) st.textContent = data.text;
      if (['ok', 'warn', 'error'].includes(data.level) || String(data.text).startsWith('🔁')) toast(data.text, data.level === 'info' ? '' : data.level);
      if (data.refresh && C.assist && C.assist.open && !C.assist.sending) {  // tự điều phối thêm vòng mới → tải lại khung chat
        const bid = C.board.id;
        call('canvas_assist_get', bid).then(r => { if (r && C.board && C.board.id === bid) { C.assist.chat = r.chat; drawAssist(true); } });
      } else if (data.refresh && C.assist) C.assist.chat = null;  // đóng khung → lần mở sau tải mới
      return;
    }
    if (event === 'canvas_log' && data.task) {
      (C.logs[data.task] = C.logs[data.task] || []).push(data);
      if (C.logs[data.task].length > 300) C.logs[data.task].splice(0, 100);
      const rec = runs()[runs().length - 1];
      if (rec && rec.task === data.task) drawTray();
      return;
    }
    if (event === 'canvas_flow' && !C.board && body() && body().querySelector('.cv-bgrid')) return listFlowEvent(data);
    if (event === 'canvas_flow' && C.board && data.board === C.board.id) {
      const list = C.board.runs || (C.board.runs = []);
      const i = list.findIndex(r => r.id === data.run.id);
      const before = i >= 0 ? list[i].status : '';
      if (i >= 0) list[i] = data.run; else list.push(data.run);
      drawFlow();
      const side = body().querySelector('.cv-side');
      if (side && !side.classList.contains('hidden') && side.dataset.view === 'history') toggleHistory(true);
      if (before === 'running' && data.run.status !== 'running') {
        toast(`Quy trình: ${RUN_VI[data.run.status] || data.run.status}`, data.run.status === 'done' ? 'ok' : data.run.status === 'error' ? 'error' : '');
      }
      return;
    }
    if (event === 'canvas_node' && C.board && data.board === C.board.id) {
      const i = C.board.nodes.findIndex(n => n.id === data.node.id);
      if (i < 0) return;
      const before = C.board.nodes[i];
      const keep = data.node.kind === 'wf' ? { config: before.config } : {};  // ô cấu hình đang gõ dở: giữ bản trên màn hình
      C.board.nodes[i] = { ...data.node, ...keep, x: before.x, y: before.y };
      const n = C.board.nodes[i];
      drawNode(n);
      drawEdges();
      if (C.sel === n.id) {
        const panel = body().querySelector('.cv-panel');
        const typing = panel && panel.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
        // khối: trạng thái / kết quả đổi → dựng lại ô (hiện chữ AI vừa viết) — trừ khi bạn đang gõ trong ô
        if (n.kind === 'wf' && (before.status !== n.status || (before.out || {}).text !== (n.out || {}).text) && !typing) drawWfPanel(n, true);
        else drawPanel();
      }
      if (n.status === 'done' && before.status !== 'done') {
        toast(`${nameOf(n)} ${n.id}: xong`, 'ok');
        C.flash[n.id] = true;  // loé sáng 1 nhịp khi vừa xong
        drawNode(n);
        setTimeout(() => { delete C.flash[n.id]; const cur = node(n.id); if (cur) drawNode(cur); }, 1400);
      }
      const rec = runs()[runs().length - 1];
      if (rec && rec.status === 'running') drawTray();
      if (n.status === 'idle' && before.status !== 'idle' && n.error) toast(`${nameOf(n)} ${n.id}: ${n.error}`);
    } else if (event === 'canvas_error' && data.message) {
      toast(`Canvas: ${data.message}`, 'error');
    }
  }

  return { show, update };
})();
