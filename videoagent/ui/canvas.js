/* Canvas — bảng node ảnh / video kiểu Kling Canvas.
   Node Ảnh: prompt → model ảnh (ảnh nối vào = ảnh tham chiếu để sửa / ghép). Node Video: ảnh nối vào = khung đầu → model video.
   Node Tải lên: ảnh của bạn. Kéo nền = di chuyển, cuộn = phóng to / thu nhỏ, kéo cổng ＋ sang node khác = nối. */
/* createCanvasPage(CFG) tạo 1 màn: Canvas (mỗi khối tự chọn model) và 🎬 Grok Canvas (bảng riêng, model định sẵn
   ở ⚙ Model của màn — chữ / ảnh ChatGPT, video Grok Imagine, trợ lý điều phối Claude; backend khoá model lúc chạy). */
function createCanvasPage(CFG) {
  const C = { meta: null, boards: [], board: null, sel: '', view: { x: 80, y: 60, k: 0.9 }, promptT: null,
    logs: {}, flash: {}, trayClosed: '' };
  const body = () => $(CFG.body);
  const FLOWSCREEN = !!CFG.flow;  // 🎬 màn Grok Canvas (tên kỹ thuật cũ: flow / fcanvas)
  const KIND = { image: '🖼 Ảnh', video: '🎬 Video', upload: '⬆ Ảnh tải lên' };
  const KIND_NAME = { image: 'Ảnh', video: 'Video', upload: 'Ảnh tải lên' };
  const GROUP_VI = { input: 'Đầu vào', ai: 'AI xử lý', create: 'Tạo nội dung', output: 'Đầu ra' };  // nhóm khối (menu Khối, ô cấu hình)
  const STATUS = { queued: 'Đang chờ', running: 'Đang tạo', done: 'Xong', error: 'Lỗi', idle: '' };

  async function call(name, ...args) {
    try {
      // màn Canvas Google Flow: canvas_* → fcanvas_* (cùng hàm, chạy trên bảng riêng / model định sẵn)
      const res = await api(name.startsWith('canvas_') ? CFG.api + name.slice(7) : name, ...args);
      if (res && res.ok === false && res.locked) {  // hết phiên mở khoá khi đang sửa → hỏi mật khẩu rồi làm tiếp
        return (await window.requireAdmin('tiếp tục chỉnh sửa quy trình Canvas')) ? call(name, ...args) : null;
      }
      if (res && res.ok === false) { toast(res.error || 'Lỗi', 'error'); return null; }
      // mọi thao tác sửa trả bảng kèm trạng thái ↶ hoàn tác / ↷ làm lại → cập nhật 2 nút trên thanh trên
      const b = res && (res.board || (res.result && res.result.board));
      if (b && b.undo && C.board && b.id === C.board.id) { C.board.undo = b.undo; drawUndo(); }
      return res;
    } catch (err) { toast(String(err), 'error'); return null; }
  }

  /* ---------------------------------------------------------------- vào trang */
  async function show() {
    // tải lại mỗi lần vào trang: ô chọn của khối 🔌 Tra cứu MCP lấy kết nối / công cụ mới nhất từ màn Kết nối MCP
    const res = await call('canvas_meta');
    if (res) C.meta = res.meta;
    if (!C.meta) return;
    if (FLOWSCREEN) await loadTemplates();  // 🎞 mẫu video
    if (C.board) return renderBoard();
    await listBoards();
  }

  // ================================================================ màn danh sách (kiểu Danh sách workflow)
  const KIND_ICON = { image: '🖼', upload: '⬆', video: '🎬' };
  // 🎥 khối Google Flow = node Video cố định model Google Flow (dùng chung tách lời / ghép / dây nối của khối Video)
  const FLOW = 'flow_browser';
  const isFlow = n => !!n && n.kind === 'video' && n.engine === FLOW;
  const kindIconOf = n => (isFlow(n) ? '🎥' : KIND_ICON[n.kind]);
  const kindNameOf = n => (isFlow(n) ? 'Google Flow' : KIND_NAME[n.kind]);
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
      <div class="cv-home-head"><div>${FLOWSCREEN ? `<small class="eyebrow">GROK CANVAS</small><h2>Grok Canvas</h2>
        <p class="muted">Như Canvas, model định sẵn: ${modelLine()} — đổi ở ⚙ Model.</p>`
        : `<small class="eyebrow">CANVAS</small><h2>Danh sách Canvas</h2>
        <p class="muted">Bảng sáng tạo kiểu Kling — tạo ảnh, video, viết content, đăng bài trên 1 bảng; chạy lại cả quy trình ngay tại đây.</p>`}</div>
        <div class="row">${FLOWSCREEN ? '<button class="btn ghost" data-tpl-lib="" title="Mẫu video: phong cách + Master Prompt + khung cảnh — khối Video chỉ cần vật liệu + lời thoại">🎞 Mẫu video</button>' : ''}${FLOWSCREEN ? '<button class="btn ghost" data-cv="models" title="Model định sẵn của màn này: viết / xử lý, tạo ảnh, tạo video, trợ lý điều phối + profile trình duyệt">⚙ Model</button>' : ''}
          <button class="btn ghost" data-cv="tasks" title="Quản lý tác vụ: 1 flow chạy nhiều tác vụ (đầu vào riêng, hàng đợi)">📋 Tác vụ</button>
          <button class="btn ghost" data-cv="import" title="Chuyển 1 Workflow đã lưu hoặc quy trình mẫu thành Canvas">⇩ Từ Workflow / mẫu</button>
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
    root.querySelector('[data-cv="tasks"]').onclick = () => tasksView('');
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
        <div class="cv-bcard-st">${status}</div>${schedLine(b.schedule)}</div>
      <div class="cv-bcard-foot"><button class="btn ghost sm" data-act-b="open" type="button">Mở</button><span class="cv-sp"></span>
        ${b.running ? '<button class="btn ghost sm" data-act-b="stop" type="button">⏹ Dừng</button>'
          : '<button class="btn primary sm" data-act-b="run" type="button" title="Chạy cả quy trình (dùng lại kết quả không đổi)">▶ Chạy</button>'}
        <button class="btn ghost sm" data-act-b="task" type="button" title="＋ Tạo tác vụ: chạy flow này với đầu vào riêng (nhiều tác vụ cùng lúc / hàng đợi)">＋📋</button>
        <button class="btn ghost sm ${b.schedule && b.schedule.on ? 'on' : ''}" data-act-b="sched" type="button" title="Lập lịch chạy tự động">⏰</button>
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
    if (what === 'task') return taskDialog(bid);
    if (what === 'sched') {
      if (!(await window.requireAdmin('lập lịch chạy quy trình Canvas'))) return;
      return scheduleDialog(bid, b ? b.name : bid, (b || {}).schedule, () => listBoards());
    }
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
    if (what === 'run' && FLOWSCREEN) return runAsTask(bid, true);  // 🎬 Grok Canvas: ▶ Chạy = tạo tác vụ → màn Tác vụ
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
        try { ok = await askInputs(plan.ask, { fromList: true }); } finally { C.board = prev; }
        if (!ok) return;
        res = await call('canvas_preview', bid, 'all', '', false);
        if (!res) return;
        plan = res.plan;
      }
      if (!plan.run.length && !plan.issues.some(i => i.level === 'error')) { toast('Mọi khối đã có kết quả mới nhất — không cần chạy'); return; }
      // bảng xem trước như trong Canvas: khối nào chạy, vì sao, tốn lượt gì; bỏ chọn khối không muốn làm lại
      const run = await runDialog(bid, 'all', '', false, plan, {
        onGo: async id => {
          if ((await openBoard(bid)) === false) return;
          const res2 = await call('canvas_preview', bid, 'all', '', false);
          if (res2) { C.issues = Object.fromEntries(res2.plan.issues.map(i => [i.node, i])); drawAll(); showIssues(res2.plan.issues); }
          focusNode(id);
        } });
      if (run) {
        const rec = ((run.board || {}).runs || []).slice(-1)[0];
        const total = rec ? Object.keys(rec.nodes || {}).length : plan.run.length;
        toast(`Đang chạy ${total} khối…`, 'ok');
        const cur = C.boards.find(x => x.id === bid);
        if (cur) { cur.running = true; cur.flow = { done: 0, total }; drawCards(); }
      }
    }
  }

  /* ---- ⏰ lập lịch chạy */
  const SCHED_MODES = { daily: 'Hằng ngày', weekly: 'Các thứ trong tuần', interval: 'Cứ mỗi … (lặp lại)', once: 'Một lần' };
  const SCHED_DAYS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];
  const SCHED_EVERY = [[15, '15 phút'], [30, '30 phút'], [60, '1 giờ'], [120, '2 giờ'], [180, '3 giờ'], [360, '6 giờ'], [720, '12 giờ'], [1440, '24 giờ']];
  const fmtAt = iso => (iso ? `${String(iso).slice(11, 16)} ${String(iso).slice(8, 10)}/${String(iso).slice(5, 7)}` : '');

  function schedLine(s) {
    if (!s || (!s.on && !s.last_note)) return '';
    return `<div class="cv-bcard-sched ${s.on ? 'on' : ''}" title="${esc(s.last_note || '')}">⏰ ${s.on
      ? `${esc(s.desc || '')}${s.next_at ? ` · lần tới <b>${esc(fmtAt(s.next_at))}</b>` : ''}` : 'Lịch đang tắt'}
      ${s.last_note ? `<small>${esc(s.last_note)}</small>` : ''}</div>`;
  }

  function scheduleDialog(bid, name, cur, onSaved) {
    const today = new Date();
    const pad = n => String(n).padStart(2, '0');
    const s = { on: true, mode: 'daily', time: '08:00', date: `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`,
      days: [0, 1, 2, 3, 4], every_min: 60, fresh: true, ...(cur || {}) };
    if (!cur) s.on = true;
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import';
    box.innerHTML = `<div class="cv-import-box cv-ask-box cv-sched-box"><div class="cv-side-head"><b>⏰ Lập lịch chạy · ${esc(name)}</b><button class="btn ghost sm" data-x type="button">✕</button></div>
      <label class="cv-opt-check"><input type="checkbox" data-s="on" ${s.on ? 'checked' : ''}> <b>Bật lịch chạy tự động</b></label>
      <div class="cv-sched-grid">
        <label class="field"><span>Lặp lại</span><select data-s="mode">${Object.entries(SCHED_MODES).map(([k, v]) => `<option value="${k}" ${k === s.mode ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
        <label class="field" data-show="daily weekly once"><span>Giờ chạy</span><input type="time" data-s="time" value="${esc(s.time)}"></label>
        <label class="field" data-show="once"><span>Ngày</span><input type="date" data-s="date" value="${esc(s.date || '')}"></label>
        <label class="field" data-show="interval"><span>Mỗi</span><select data-s="every_min">${SCHED_EVERY.map(([v, l]) => `<option value="${v}" ${Number(s.every_min) === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      </div>
      <div class="field" data-show="weekly"><span>Các thứ</span><div class="cv-sched-days">${SCHED_DAYS.map((d, i) =>
        `<label class="${(s.days || []).includes(i) ? 'on' : ''}"><input type="checkbox" data-day="${i}" ${(s.days || []).includes(i) ? 'checked' : ''}>${d}</label>`).join('')}</div></div>
      <label class="cv-opt-check"><input type="checkbox" data-s="fresh" ${s.fresh !== false ? 'checked' : ''}> Làm lại từ đầu mỗi lần <small class="muted">(tạo nội dung mới — tốn lượt model; bỏ chọn = chỉ chạy khối có thay đổi)</small></label>
      <small class="muted cv-sched-note">Chỉ chạy khi app đang mở; lỡ giờ vì tắt app thì bỏ qua lượt đó (không chạy bù). Khối Đăng bài vẫn chờ bạn duyệt (trừ khối đã bật tự đăng);
        khối “Hỏi khi chạy” dùng giá trị đã lưu sẵn.</small>
      ${cur && cur.last_note ? `<div class="cv-sched-last">Lượt trước: ${esc(cur.last_note)}</div>` : ''}
      <div class="row" style="justify-content:flex-end;margin-top:8px">
        ${cur && cur.on ? '<button class="btn danger sm" data-off type="button">Tắt lịch</button><span class="cv-sp"></span>' : ''}
        <button class="btn ghost sm" data-x type="button">Huỷ</button>
        <button class="btn primary sm" data-save type="button">Lưu lịch</button></div></div>`;
    const q = sel => box.querySelector(sel);
    const sync = () => {
      const mode = q('[data-s="mode"]').value;
      box.querySelectorAll('[data-show]').forEach(el => el.classList.toggle('hidden', !el.dataset.show.split(' ').includes(mode)));
      box.querySelectorAll('.cv-sched-days label').forEach(l => l.classList.toggle('on', l.querySelector('input').checked));
    };
    box.onchange = sync;
    sync();
    const save = async cfg => {
      const res = await call('canvas_schedule', bid, cfg);
      if (!res) return;
      box.remove();
      const sc = res.board.schedule || {};
      toast(sc.on ? `Đã lưu lịch — lần chạy tới: ${fmtAt(sc.next_at)}` : 'Đã tắt lịch chạy', 'ok');
      if (onSaved) onSaved(res.board);
    };
    q('[data-save]').onclick = () => {
      const cfg = { on: q('[data-s="on"]').checked, mode: q('[data-s="mode"]').value, time: q('[data-s="time"]').value,
        date: q('[data-s="date"]').value, every_min: Number(q('[data-s="every_min"]').value), fresh: q('[data-s="fresh"]').checked,
        days: [...box.querySelectorAll('[data-day]:checked')].map(x => Number(x.dataset.day)) };
      if (cfg.on && cfg.fresh && !confirm('Mỗi lần chạy theo lịch sẽ TẠO LẠI toàn bộ quy trình (tốn lượt model ảnh / video / chữ). Lưu lịch?')) return;
      save(cfg);
    };
    const off = q('[data-off]');
    if (off) off.onclick = () => save({ on: false });
    box.querySelectorAll('[data-x]').forEach(x => { x.onclick = () => box.remove(); });
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
    C.multi = new Set();
    renderBoard();
    fitView();
  }

  /* ---------------------------------------------------------------- khung bảng */
  function renderBoard() {
    const b = C.board;
    body().innerHTML = `<div class="cv-wrap">
      <div class="cv-top">
        <button class="cv-tbtn" data-cv="home" title="Về danh sách Canvas">⌂</button>
        <div class="cv-top-title">
          <input class="cv-name" value="${esc(b.name)}" maxlength="80" title="Đổi tên Canvas">
          <span class="muted cv-count"></span>
        </div>
        <span class="cv-flow"></span>
        <span class="cv-sp"></span>
        <div class="cv-top-actions">
          <div class="cv-undo"><button class="cv-tbtn" data-cv="undo" disabled>↶</button><button class="cv-tbtn" data-cv="redo" disabled>↷</button></div>
          <span class="cv-top-sep"></span>
          <div class="cv-split">
            <button class="btn primary sm cv-run-btn" data-cv="run" title="Chạy cả quy trình theo thứ tự dây nối — xem trước khối nào chạy (vì sao, tốn lượt gì) rồi mới bắt đầu; khối đã có kết quả mà không đổi gì thì dùng lại (không tốn lượt)">▶ Chạy toàn bộ</button>
            <button class="btn primary sm cv-run-more" data-cv="runmenu" title="Kiểu chạy khác">▾</button>
          </div>
          <span class="cv-top-sep"></span>
          <div class="cv-seg">
            <button data-cv="sched" title="Lập lịch chạy tự động (một lần / hằng ngày / các thứ / cứ N phút)"><i>⏰</i><span>Lịch</span></button>
            <button data-cv="assist" title="Trợ lý Claude: điều phối quy trình, đánh giá kết quả, đề xuất sửa (bạn bấm Áp dụng mới thay đổi)"><i>🤖</i><span>Trợ lý</span></button>
            <button data-cv="history" title="Các lần chạy quy trình"><i>🕘</i><span>Lịch sử</span></button>
            <button data-cv="folder" title="Mở thư mục lưu file của Canvas này"><i>📁</i><span>Thư mục</span></button>
            ${FLOWSCREEN ? `<button data-cv="models" title="Model định sẵn: ${esc(modelLine())}"><i>⚙</i><span>Model</span></button>` : ''}
          </div>
          <span class="cv-top-sep"></span>
          <button class="cv-tbtn danger" data-cv="del" title="Xoá Canvas này">🗑</button>
        </div>
      </div>
      <div class="cv-stage" tabindex="0">
        <div class="cv-world"><div class="cv-groups"></div><svg class="cv-edges"></svg><div class="cv-nodes"></div></div>
        <div class="cv-tools hidden"></div>
        <div class="cv-side hidden"></div>
        <div class="cv-assist hidden"></div>
        <div class="cv-menu hidden"></div>
        <div class="cv-empty ${b.nodes.length ? 'hidden' : ''}">
          <i class="cv-empty-ic">🧩</i>
          <b>Bắt đầu Canvas</b><span class="muted">Thêm node Ảnh (viết prompt → tạo ảnh) hoặc tải ảnh của bạn lên rồi nối sang Video;<br>hoặc chọn khối quy trình (văn bản, AI viết, hậu kỳ, đăng bài…).</span>
          <div class="row"><button class="btn primary sm" data-add="image">🖼 Thêm ảnh</button><button class="btn ghost sm" data-add="upload">⬆ Tải ảnh lên</button><button class="btn ghost sm" data-empty-blocks>🧩 Chọn khối…</button></div>
          <small class="muted">Kéo nền để di chuyển · cuộn để phóng to · kéo cổng ＋ sang khối khác để nối</small>
        </div>
      </div>
      <div class="cv-tray hidden"></div>
      <div class="cv-dock">
        <button data-add="image" title="Thêm node Ảnh (tạo ảnh từ prompt)"><i>🖼</i><small>Ảnh</small></button>
        <button data-add="video" title="Thêm node Video (nối 1 ảnh vào làm khung đầu)"><i>🎬</i><small>Video</small></button>
        ${FLOWSCREEN ? '' : `<button data-add="flow" title="Khối Google Flow: tạo video Veo 8 giây có tiếng trên labs.google/flow (tài khoản Google đã đăng nhập, tốn tín dụng Flow). Nối ảnh, ý tưởng, lời thoại như khối Video — lời dài tự tách nhiều video rồi ghép"><i>🎥</i><small>Flow</small></button>`}
        <button data-add="upload" title="Tải ảnh trên máy lên"><i>⬆</i><small>Tải lên</small></button>
        <button data-angles="character" title="Góc nhân vật: từ ảnh người mẫu tạo 1 bảng 5 góc (trước, ¾, nghiêng, sau, cận mặt) — nối vào Video / Storyboard để giữ đúng mặt, trang phục ở mọi góc máy. Đang chọn 1 ảnh thì tự nối ảnh đó vào"><i>🧍</i><small>Góc NV</small></button>
        <button data-angles="product" title="Góc sản phẩm: từ ảnh sản phẩm tạo 1 bảng 5 góc (trước, ¾, cạnh, sau, trên) — nối vào Video / Storyboard để giữ đúng bao bì, nhãn ở mọi góc máy. Đang chọn 1 ảnh thì tự nối ảnh đó vào"><i>📦</i><small>Góc SP</small></button>
        <button data-blocks class="cv-dock-main" title="Các khối như Workflow: Văn bản, AI viết, Tạo content, Ghép video, Video dài, Whiteboard, Đăng bài, Lên lịch, Quảng cáo · Nhóm / ghi chú"><i>🧩</i><small>Khối</small></button>
        <span class="cv-dock-sep"></span>
        <button data-arrange title="Tự sắp xếp các khối theo luồng dây nối: trái → phải, khối cùng bước xếp dọc; Nhóm giữ các khối bên trong và co lại vừa khít. Bấm lại trong 15 giây để hoàn tác"><i>⇆</i><small>Sắp xếp</small></button>
        <button data-selmode title="Quét chọn nhiều khối: bật lên thì kéo trên nền để quét chọn (tắt = kéo để di chuyển bảng). Lúc nào cũng dùng được: Shift + kéo trên nền để quét · Ctrl / Shift + bấm khối để thêm / bớt · Ctrl + A chọn tất cả · Esc bỏ chọn"><i>⬚</i><small>Quét chọn</small></button>
        <span class="cv-dock-sep"></span>
        <div class="cv-zoomer">
          <button data-zoom="-" title="Thu nhỏ">−</button><span class="cv-zoom"></span><button data-zoom="+" title="Phóng to">＋</button>
          <button data-zoom="fit" title="Vừa khung — xem toàn bộ node">⤢</button>
        </div>
      </div>
    </div>`;
    const root = body();
    // 📋 bảng chạy của 1 tác vụ → ⌂ về màn Tác vụ
    root.querySelector('[data-cv="home"]').onclick = () => (C.board && C.board.task_of ? tasksView() : listBoards());
    root.querySelector('[data-empty-blocks]').onclick = e => { e.stopPropagation(); showBlocks(root.querySelector('[data-blocks]')); };
    root.querySelector('[data-cv="folder"]').onclick = () => call('canvas_open_folder', b.id);
    root.querySelector('[data-cv="del"]').onclick = deleteBoard;
    root.querySelector('[data-cv="run"]').onclick = () => runFlow('all', '', false);
    root.querySelector('[data-cv="runmenu"]').onclick = e => {
      e.stopPropagation();
      popMenu(e.currentTarget, [['fresh', '⟳ Làm lại tất cả', 'Tạo mới MỌI khối từ đầu (tốn lượt model) — trừ khối 🔒 đã khoá'],
        ['errors', '↻ Chạy lại khối lỗi / chưa xong', 'Như Chạy toàn bộ: chỉ chạy khối lỗi, chưa chạy hoặc đã đổi']], key => {
        if (key === 'fresh') runFlow('all', '', true);
        if (key === 'errors') runFlow('all', '', false);
      });
    };
    root.querySelector('[data-cv="undo"]').onclick = () => undoStep(false);
    root.querySelector('[data-cv="redo"]').onclick = () => undoStep(true);
    root.querySelector('[data-cv="history"]').onclick = () => toggleHistory();
    root.querySelector('[data-cv="assist"]').onclick = () => toggleAssist();
    root.querySelector('[data-cv="sched"]').onclick = async () => {
      if (!(await window.requireAdmin('lập lịch chạy quy trình Canvas'))) return;
      scheduleDialog(C.board.id, C.board.name, C.board.schedule, board => { if (C.board) C.board.schedule = board.schedule; });
    };
    C.assist = { open: false, chat: null, sending: false, status: '' };
    C.undoArrange = null;  // hoàn tác sắp xếp chỉ cho bảng đang mở
    clearTimeout(C.undoT);
    const name = root.querySelector('.cv-name');
    name.onchange = async () => { const res = await call('canvas_rename', b.id, name.value); if (res) C.board.name = res.board.name; };
    root.querySelectorAll('[data-add]').forEach(el => { el.onclick = () => addAt(el.dataset.add); });
    root.querySelectorAll('[data-angles]').forEach(el => { el.onclick = () => addAngles(el.dataset.angles); });
    root.querySelector('[data-blocks]').onclick = e => {  // bấm lại = đóng
      e.stopPropagation();
      const m = root.querySelector('.cv-menu');
      if (m && !m.classList.contains('hidden') && m.classList.contains('cv-menu-blocks')) return hideMenu();
      showBlocks(e.currentTarget);
    };
    bindMenuClose();
    root.querySelector('[data-arrange]').onclick = () => (C.undoArrange ? undoArrange() : arrange());
    const selBtn = root.querySelector('[data-selmode]');
    selBtn.classList.toggle('on', !!C.selMode);
    selBtn.onclick = () => { C.selMode = !C.selMode; selBtn.classList.toggle('on', C.selMode); root.querySelector('.cv-stage').classList.toggle('selmode', C.selMode); };
    root.querySelector('.cv-stage').classList.toggle('selmode', !!C.selMode);
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
  const nameOf = n => (n.kind === 'wf' ? `${wspec(n).icon} ${wspec(n).name}` : isFlow(n) ? '🎥 Google Flow' : KIND[n.kind]);
  const labelOf = n => (n && n.title ? n.title : n ? nameOf(n) : '');  // tên riêng (đặt ở ô Tên) hoặc tên loại
  const tagOf = x => `<b>${esc(x.id)}</b>${x.title ? ` · ${esc(x.title)}` : ''}`;
  const titleInput = n => `<input class="cv-title" data-title value="${esc(n.title || '')}" maxlength="60" placeholder="Đặt tên khối (VD: Thông tin sản phẩm, Lời thoại cảnh 1)…" title="Tên riêng của khối — dễ phân biệt khi chạy, trong nhật ký và khi nhờ trợ lý">`;
  /** Đầu ô cấu hình: biểu tượng · loại khối · mã khối · nút đóng (bỏ chọn). */
  const panelHead = (n, sub) => `<div class="cv-panel-head"><span class="cv-node-ic">${esc(n.kind === 'wf' ? wspec(n).icon : kindIconOf(n))}</span>
    <div class="cv-panel-ttl"><b>${esc(n.kind === 'wf' ? wspec(n).name : kindNameOf(n))}</b><small>${esc(n.id)}${sub ? ` · ${esc(sub)}` : ''}</small></div>
    <button class="cv-x" data-close-panel type="button" title="Đóng (Esc)">✕</button></div>`;
  const bindPanelHead = panel => { const x = panel.querySelector('[data-close-panel]'); if (x) x.onclick = () => selectNode(''); };
  /* ---- ⇢ đầu vào của khối: vai trò từng dây ("cổng có tên"), thứ tự, bỏ nối */
  // 📎 khối Ảnh: vai trò ảnh tham chiếu (backend dặn model giữ đúng mặt / sản phẩm / nền / phong cách)
  const IMG_REFS = [['character', '🧍', 'Nhân vật'], ['product', '📦', 'Sản phẩm'], ['scene', '🏞', 'Bối cảnh'], ['style', '🎨', 'Phong cách']];
  const ROLE_OPTS = {
    image: [['', 'Tham chiếu chung'], ...IMG_REFS.map(([v, i, l]) => [v, `${i} ${l}`])],
    product_studio: [['', 'Tự nhận theo tên'], ['character', '🧍 Nhân vật'], ['product', '📦 Sản phẩm']],
    video: [['', 'Tự động'], ['first', 'Khung đầu'], ['ref', 'Tham chiếu']],
    edit_pro: [['', 'Tự động'], ['main', 'Video chính'], ['clip', 'Clip minh hoạ']],
  };
  const iconOf = x => (x.kind === 'wf' ? (wspec(x) || {}).icon || '🧩' : kindIconOf(x) || '•');
  function inputsHtml(n) {
    const ins = (n.inputs || []).map(node).filter(Boolean);
    if (!ins.length) return '';
    const key = n.kind === 'wf' ? n.wtype : n.kind;
    const opts = ROLE_OPTS[key];
    const roles = n.roles || {};
    const roleFor = x => opts && (((key === 'video' || key === 'image' || key === 'product_studio') && isPic(x)) || (key === 'edit_pro' && outTypes(x).has('video')));
    return `<div class="cv-ins"><div class="cv-ins-head"><b>⇢ Đầu vào (${ins.length})</b><small class="muted">${ins.length > 1 ? 'thứ tự = thứ tự gửi model / ghép' : ''}</small></div>
      ${ins.map((x, i) => `<div class="cv-in-row"><span class="cv-node-ic">${esc(iconOf(x))}</span>
        <span class="cv-in-name" title="${esc(labelOf(x))}"><code>${esc(x.id)}</code> ${esc(labelOf(x))}</span>
        ${roleFor(x) ? `<select data-role="${esc(x.id)}" title="Vai trò của đầu vào này">${opts.map(([v, l]) => `<option value="${v}" ${(roles[x.id] || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>` : ''}
        ${ins.length > 1 ? `<button data-in-move="${i}:-1" type="button" title="Đưa lên" ${i ? '' : 'disabled'}>↑</button><button data-in-move="${i}:1" type="button" title="Đưa xuống" ${i < ins.length - 1 ? '' : 'disabled'}>↓</button>` : ''}
        <button data-in-rm="${esc(x.id)}" type="button" title="Bỏ nối (hoàn tác được)">✕</button></div>`).join('')}</div>`;
  }
  function drawInputs(panel, n) {
    const box = panel.querySelector('.cv-ins-box');
    if (!box) return;
    box.innerHTML = inputsHtml(n);
    box.querySelectorAll('[data-role]').forEach(s => {
      s.onchange = () => setOption(n.id, 'roles', { ...(node(n.id).roles || {}), [s.dataset.role]: s.value });
    });
    box.querySelectorAll('[data-in-move]').forEach(b => {
      b.onclick = async () => {
        const [i, d] = b.dataset.inMove.split(':').map(Number);
        const ids = [...(node(n.id).inputs || [])].filter(x => node(x));
        if (i + d < 0 || i + d >= ids.length) return;
        [ids[i], ids[i + d]] = [ids[i + d], ids[i]];
        const res = await call('canvas_reorder_inputs', C.board.id, n.id, ids);
        if (res) { C.board = res.board; drawAll(); }
      };
    });
    box.querySelectorAll('[data-in-rm]').forEach(b => {
      b.onclick = async () => {
        const res = await call('canvas_connect', C.board.id, b.dataset.inRm, n.id, false);
        if (res) { C.board = res.board; drawAll(); toast(`Đã bỏ nối ${b.dataset.inRm} → ${n.id} — Ctrl+Z để hoàn tác`, 'ok'); }
      };
    });
  }

  /** Dòng báo 🔒 ngay dưới đầu ô cấu hình khi khối đang khoá (sửa prompt chỉ có tác dụng khi mở khoá). */
  function lockNote(panel, n) {
    let note = panel.querySelector('.cv-lock-note');
    if (!n.locked) { if (note) note.remove(); return; }
    if (!note) {
      note = document.createElement('div');
      note.className = 'cv-lock-note';
      const head = panel.querySelector('.cv-panel-head');
      if (head) head.after(note); else panel.prepend(note);
    }
    note.innerHTML = '🔒 <b>Đang khoá kết quả</b> — chạy quy trình luôn giữ nguyên kết quả này (kể cả Làm lại tất cả). Sửa prompt / cấu hình chỉ có tác dụng khi mở khoá.';
  }
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

  const POST_KIND = { feed: 'Bài viết', text: 'Bài viết chữ', media: 'Ảnh / video', reel: 'Reels', story: 'Story',
    link: 'Chia sẻ link', dark: 'Bài ẩn (quảng cáo)' };
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
    const state = p.pending ? ['wait', '📥 Chờ duyệt'] : p.queued ? ['wait', `🕒 Hẹn đăng ${p.when || ''}`] : p.scheduled ? ['wait', `🗓 Facebook hẹn ${p.when || ''}`] : ['ok', '✓ Đã đăng'];
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
        <b>📣 Duyệt ${esc(ap.kind === 'schedule' ? `hẹn giờ ${ap.when || ''}` : 'đăng bài')}${ap.page ? ` lên “${esc(ap.page)}”` : ' — chọn Fanpage bên dưới'}</b>
        <small class="muted">${esc(ap.post_type_label || '')}</small>
        ${ap.link ? `<div class="cv-post-link" title="${esc(ap.link)}">🔗 ${esc(shortUrl(ap.link))}</div>` : ''}
        ${(ap.media_urls || []).length ? `<div class="cv-ap-media">${ap.media_urls.map(u => (/\.(mp4|mov|webm|m4v)/i.test(u)
          ? `<video src="${esc(u)}" muted></video>` : `<img src="${esc(thumbUrl(u, 200))}" alt="">`)).join('')}</div>` : ''}
        ${ap.choose_page ? `<label class="cv-ap-page" title="Khối chưa chọn Fanpage — chọn trang để đăng bài này"><span>📣 Đăng lên Fanpage</span><select data-ap-page>
          <option value="">— Chọn Fanpage —</option>${(ap.pages || []).map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select>
          ${(ap.pages || []).length ? '' : '<small class="warn-text">Chưa có Fanpage nào bật Kết nối (Cài đặt → Facebook · Meta)</small>'}</label>` : ''}
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
    const flags = [n.locked ? ['🔒', 'Đã khoá kết quả — chạy quy trình giữ nguyên'] : null, qcFlag(n),
      n.ask ? ['❓', 'Hỏi lại các ô này mỗi lần chạy'] : null, n.optional ? ['✏', 'Không bắt buộc nhập — để trống vẫn chạy'] : null,
      n.auto_post ? ['🚀', 'Tự đăng không cần duyệt'] : null,
      n.to_posts && !n.auto_post && ['fb_post', 'fb_schedule'].includes(n.wtype) ? ['📥', 'Lưu vào Quản lý bài đăng — chờ duyệt'] : null];
    const st = n.status === 'waiting' ? 'Chờ duyệt' : busy ? `${Math.round(n.pct || 0)}%` : STATUS[n.status] || '';
    return `<div class="cv-card">${nodeHead(n, s.icon, n.title || s.name, n.title ? s.name : '', flags, st)}
      <div class="cv-media wf ${url ? 'has-video' : ''}">${body}${n.status === 'running' ? `<div class="cv-prog"><i style="width:${Math.max(3, Math.round(n.pct || 0))}%"></i></div>` : ''}${busy && (url || out.text) ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
      ${n.status === 'error' && (url || out.text) ? `<div class="cv-err">⚠ ${esc(n.error || '')}</div>` : ''}
      ${n.status === 'idle' && n.error ? `<div class="cv-err muted">${esc(n.error)}</div>` : ''}</div>
      ${ins.length ? `<button class="cv-port in" title="Nhận: ${esc(ins.join(', '))}" type="button"></button>` : ''}
      ${s.outputs.length ? `<button class="cv-port out" title="Đưa ra: ${esc(s.outputs.map(o => o.label).join(', '))} — kéo sang node khác để nối · bấm để tạo tiếp" type="button">＋</button>` : ''}`;
  }

  /** Thanh tiêu đề của thẻ khối: biểu tượng · tên (tên riêng, loại khối hiện khi rê chuột) · cờ (❓ 🚀 💬) · mã khối · trạng thái. */
  function nodeHead(n, icon, name, sub, flags, st) {
    return `<div class="cv-node-head"><span class="cv-node-ic" title="${esc(sub || name)}">${esc(icon)}</span>
      <span class="cv-node-name" title="${esc(sub ? `${name} · ${sub}` : name)}">${esc(name)}</span>
      ${(flags || []).filter(Boolean).map(([ic, tip]) => `<i class="cv-node-flag" title="${esc(tip)}">${ic}</i>`).join('')}
      <code class="cv-node-id" title="Mã khối — dùng khi nhắc tới khối này (nhật ký, trợ lý)">${esc(n.id)}</code>
      <em class="cv-st ${esc(n.status || '')}">${esc(st)}</em></div>`;
  }

  /** Thẻ cảnh tách từ Storyboard: dưới ảnh bìa (hoặc dưới video khi không có ảnh bìa) hiện mô tả + lời thoại của cảnh. */
  function sceneCap(n) {
    const src = node(n.cover_of || n.scene_of || '');
    if (!src || (n.scene_of && (n.inputs || []).some(i => (node(i) || {}).cover_of))) return '';  // video đã có ảnh bìa hiện
    const sc = sceneOf(src, n);
    if (!sc || !sc.noi_dung) return '';
    const line = String(sc.loi || '').trim();
    const meta = [['💡', sc.y_tuong, 'Ý tưởng'], ['🎥', sc.goc_quay, 'Góc quay']].filter(x => x[1])
      .map(([ic, v, tip]) => `<p class="cv-scene-meta" title="${esc(tip)}: ${esc(v)}">${ic} ${esc(v)}</p>`).join('');
    return `<div class="cv-scene-cap"><p class="cv-scene-desc"><b>Cảnh ${esc(n.scene)}</b>${esc(sc.noi_dung)}</p>${meta}
      ${line ? `<p class="cv-scene-line" title="${esc(line)}">💬 ${esc(line)}</p>` : '<p class="cv-scene-line muted">🔇 Cảnh không lời</p>'}</div>`;
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
          : n.kind === 'upload' ? `<b>🖼</b><small>${(n.inputs || []).length ? `Chưa có ảnh — sẽ lấy ảnh sản phẩm từ ${esc(n.inputs.join(', '))} (Tra cứu web);<br>web không có ảnh thì bấm ⬆ Chọn ảnh`
            : n.ask ? 'Chưa có ảnh — sẽ hỏi chọn ảnh khi chạy quy trình' : 'Chưa có ảnh — bấm ⬆ Chọn ảnh'}</small>`
          : n.kind === 'video' && n.chain_from && node(n.chain_from) ? `<b>⛓</b><small>Quay tiếp từ khung cuối ${esc(node(n.chain_from).title || n.chain_from).split(' · ')[0]}<br>— liền mạch, ảnh bìa làm tham chiếu</small>`
          : n.kind === 'video' && (n.inputs || []).some(i => (node(i) || {}).cover_of) ? '<b>🎬</b><small>Quay từ ảnh bìa bên trái —<br>ưng ảnh bìa rồi bấm ▶ Chạy toàn bộ</small>'
          : isFlow(n) ? '<b>🎥</b><small>📎 Thêm ảnh nhân vật / sản phẩm,<br>viết cảnh + lời thoại rồi bấm Tạo</small>'
          : n.kind === 'video' ? '<b>🎬</b><small>Nối 1 ảnh vào làm khung đầu,<br>viết chuyển động rồi bấm Tạo</small>'
            : `<b>🖼</b><small>${promptSrc(n) && promptSrc(n) !== 'own' ? `Prompt lấy từ ${esc(promptSrc(n))} — bấm Tạo<br>(hoặc ▶ Chạy toàn bộ)`
              : dialogueSources(n).length && promptSrc(n) !== 'own' ? 'Prompt = chữ từ khối nối vào<br>+ phần viết thêm — bấm Tạo' : 'Viết prompt rồi bấm Tạo'}</small>`}</div>`;
    const variants = (n.urls || []).length > 1 ? `<div class="cv-variants">${n.urls.map((u, i) =>
      `<img src="${esc(thumbUrl(u, 120))}" data-pick="${i}" class="${i === (n.pick || 0) ? 'on' : ''}" alt="" draggable="false">`).join('')}</div>` : '';
    const kindName = kindNameOf(n);
    const flags = [n.locked ? ['🔒', 'Đã khoá kết quả — chạy quy trình giữ nguyên'] : null, qcFlag(n),
      n.ask ? ['❓', n.kind === 'upload' ? 'Hỏi chọn ảnh mỗi lần chạy' : 'Hỏi lại prompt mỗi lần chạy'] : null,
      n.optional ? ['✏', 'Không bắt buộc nhập — để trống vẫn chạy'] : null,
      (n.dialogue || '').trim() ? ['💬', 'Có lời thoại'] : null, (n.vers || []).length ? ['🕘', `${n.vers.length} phiên bản trước`] : null];
    return `<div class="cv-card${isFlow(n) ? ' cv-gflow' : ''}">${nodeHead(n, kindIconOf(n), n.title || kindName, n.title ? kindName : '', flags,
      busy ? `${Math.round(n.pct || 0)}%` : STATUS[n.status] || '')}${refStrip(n)}
      <div class="cv-media" style="aspect-ratio:${1 / ratio(n)}">${media}${n.status === 'running' ? `<div class="cv-prog"><i style="width:${Math.max(3, Math.round(n.pct || 0))}%"></i></div>` : ''}${busy && url ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
      ${n.status === 'error' && url ? `<div class="cv-err">⚠ ${esc(n.error || '')}</div>` : ''}
      ${variants}${sceneCap(n)}</div>
      ${n.kind !== 'upload' ? '<button class="cv-port in" title="Ảnh nối vào (kéo từ cổng ＋ của ảnh khác sang đây)" type="button"></button>'
        : '<button class="cv-port in" title="Nối khối 🌐 Tra cứu web vào đây: tìm được ảnh sản phẩm thì thay ảnh này, không có thì nhắc bạn tải ảnh lên" type="button"></button>'}
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
    el.className = `cv-node ${n.kind} st-${n.status || 'idle'}${n.id === C.sel ? ' sel' : ''}${multi().has(n.id) ? ' msel' : ''}${n.status === 'error' ? ' err' : ''}${C.flash && C.flash[n.id] ? ' flash' : ''}${(C.issues || {})[n.id] ? ' issue' : ''}${n.locked ? ' locked' : ''}`;
    el.style.left = `${n.x}px`;
    el.style.top = `${n.y}px`;
    el.style.width = `${widthOf(n)}px`;
    el.innerHTML = nodeHtml(n);
    const media = el.querySelector('.cv-media');  // cổng nối nằm ngang tâm khung ảnh / nội dung (dưới thanh tiêu đề)
    if (media && media.offsetHeight) el.style.setProperty('--port-y', `${media.offsetTop + media.offsetHeight / 2}px`);  // bảng đang ẩn → đo = 0, giữ mặc định
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
          const pageSel = ap.querySelector('[data-ap-page]');  // 📣 khối chưa chọn Fanpage → chọn lúc duyệt
          if (yes && pageSel && !pageSel.value) { pageSel.focus(); return toast('Chọn Fanpage để đăng bài này', 'warn'); }
          const pageName = pageSel && pageSel.value ? pageSel.selectedOptions[0].textContent.trim() : '';
          if (yes && !confirm(pageName ? `Đăng bài này lên Fanpage “${pageName}”?` : 'Đăng bài này lên Fanpage?')) return;
          const cap = ap.querySelector('[data-ap-caption]');
          if (await call('canvas_approve', C.board.id, n.id, yes, cap ? cap.value : null, pageSel ? pageSel.value : '')) toast(yes ? 'Đã duyệt — đang đăng…' : 'Đã bỏ qua bài đăng', yes ? 'ok' : '');
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
    drawUndo();
  }

  function anchor(id, side) {
    const el = body().querySelector(`[data-node="${id}"]`);
    const n = node(id);
    if (!el || !n) return null;
    const media = el.querySelector('.cv-media');
    const y = n.y + (media ? media.offsetTop + media.offsetHeight / 2 : el.offsetHeight / 2);  // = tâm cổng nối (--port-y)
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
    const add = e.ctrlKey || e.metaKey;  // Ctrl + quét → cộng thêm vào các khối đang chọn
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
      if (q.w < 4 && q.h < 4) { if (!add) setMulti([]); return; }  // bấm (không kéo) trên nền → bỏ chọn
      const hits = C.board.nodes.filter(n => {  // chạm khung là chọn (không cần nằm trọn trong khung)
        const s = sizeOf(n);
        return n.x < q.x + q.w && n.x + s.w > q.x && n.y < q.y + q.h && n.y + s.h > q.y;
      }).map(n => n.id);
      setMulti(add ? [...new Set([...multi(), ...(C.sel ? [C.sel] : []), ...hits])] : hits);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  /* ---------------------------------------------------------------- thanh công cụ + ô prompt của node đang chọn */
  function selectNode(id) {
    if (id && multi().size) { C.multi = new Set(); body().querySelectorAll('.cv-node.msel').forEach(el => el.classList.remove('msel')); }
    if (C.gsel) {
      C.gsel = '';
      body().querySelectorAll('.cv-group.sel').forEach(el => el.classList.remove('sel'));
    }
    C.sel = id;
    body().querySelectorAll('.cv-node').forEach(el => el.classList.toggle('sel', el.dataset.node === id));
    hideMenu();
    drawPanel(true);
    if (id) { keepClear(id); placeTools(); }  // đặt lại thanh công cụ khi ô cấu hình đã hiện (né cột phải)
  }

  /** Ô cấu hình neo cột phải → khối vừa chọn bị ô (hoặc Trợ lý) che thì trượt canvas sang trái cho khối lộ ra. */
  function keepClear(id) {
    const root = body();
    const n = node(id);
    const el = n && root.querySelector(`[data-node="${id}"]`);
    const panel = root.querySelector('.cv-panel');
    const stage = root.querySelector('.cv-stage');
    if (!el || !panel || !stage) return;
    const r = stage.getBoundingClientRect();
    const edge = panel.getBoundingClientRect().left - r.left - 24;  // mép trái ô cấu hình (toạ độ sân khấu)
    const x1 = C.view.x + n.x * C.view.k, x2 = x1 + el.offsetWidth * C.view.k;
    if (x2 <= edge || edge < 160) return;
    const dx = Math.min(x2 - edge, Math.max(0, x1 - 24));  // khối rộng hơn chỗ trống → giữ mép trái trong màn hình
    if (dx <= 0) return;
    const world = root.querySelector('.cv-world');
    world.classList.add('glide');
    C.view.x -= dx;
    applyView();
    placeTools();
    setTimeout(() => world.classList.remove('glide'), 260);
  }

  function optionsHtml(n) {
    const m = C.meta;
    const sel = (key, items, value, label) => `<label title="${esc(label)}"><select data-f="${key}">${items.map(([v, t]) =>
      `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
    if (isFlow(n)) {  // 🎥 khối Google Flow: không chọn model; video Veo 8 giây có tiếng — bố cục như bảng cài đặt Flow
      const spec = m.video_engines[FLOW] || { aspects: ['9:16', '16:9'] };
      const ASP = { '9:16': ['▯', 'Dọc 9:16'], '16:9': ['▭', 'Ngang 16:9'], '1:1': ['□', 'Vuông 1:1'] };
      return `<div class="cv-flow-set"><div class="cv-flow-set-h">⚙ Cài đặt video</div>
        <div class="cv-seg2" role="radiogroup" title="Tỉ lệ khung hình">${spec.aspects.map(a => `<button type="button" data-set="aspect" data-val="${esc(a)}"
          class="${n.aspect === a ? 'on' : ''}" aria-pressed="${n.aspect === a}"><i>${(ASP[a] || ['▢'])[0]}</i>${esc((ASP[a] || [, a])[1])}</button>`).join('')}</div>
        <div class="cv-flow-chips" title="${esc(spec.note || '')}"><span>🎥 Veo</span><span>⏱ 8 giây</span><span>1 kết quả</span><span>🔊 có tiếng</span></div>
        ${sel('voice', (m.voices || []).map(v => [v.value, `🗣 ${v.label}`]), n.voice || '', 'Giọng đọc lời thoại')}
        <label class="cv-opt-check" title="Tắt: mọi ảnh là thành phần (Ingredients) — Flow tự dựng cảnh mới giữ đúng người / sản phẩm"><input type="checkbox" data-f="first_frame" ${n.first_frame !== false ? 'checked' : ''}> Ảnh đầu làm khung mở đầu</label>
        ${askCheck(n)}</div>`;
    }
    // 🎥 màn Canvas Google Flow: model định sẵn → nhãn thay ô chọn model
    const lockTag = kind => `<span class="cv-flow-tag" title="Model định sẵn của màn — đổi ở ⚙ Model">⚙ ${esc(((m.flow || {}).names || {})[kind] || '')}</span>`;
    if (n.kind === 'video') {
      const spec = m.video_engines[n.engine] || Object.values(m.video_engines)[0];
      return (FLOWSCREEN && !n.part_of ? tplHtml(n) : '') + (FLOWSCREEN ? lockTag('video') : sel('engine', Object.entries(m.video_engines).filter(([k]) => k !== FLOW).map(([k, v]) => [k, v.name]), n.engine, 'Model video'))
        + sel('aspect', spec.aspects.map(a => [a, a]), n.aspect, 'Tỉ lệ')
        + sel('duration', spec.durations.map(d => [d, d.replace('s', ' giây')]), n.duration, 'Thời lượng')
        + sel('resolution', spec.resolutions.map(r => [r, r]), n.resolution, 'Độ phân giải')
        + sel('voice', (m.voices || []).map(v => [v.value, `🗣 ${v.label}`]), n.voice || '', 'Giọng đọc lời thoại')
        + `<label class="cv-opt-check" title="Tắt: mọi ảnh nối vào đều là ảnh tham chiếu (model tự dựng cảnh mới)"><input type="checkbox" data-f="first_frame" ${n.first_frame !== false ? 'checked' : ''}> Ảnh đầu làm khung mở đầu</label>`
        + askCheck(n);
    }
    const spec = m.image_engines[n.engine] || Object.values(m.image_engines)[0];
    return (FLOWSCREEN ? lockTag('image') : sel('engine', Object.entries(m.image_engines).map(([k, v]) => [k, v.name]), n.engine, 'Model ảnh'))
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
      const roles = n.roles || {};  // vai trò từng ảnh (giống backend _video_images): "Khung đầu" đứng đầu, "Tham chiếu" không làm khung đầu
      const pinned = pics.find(p => roles[p.id] === 'first') || (n.first_frame !== false ? pics.find(p => roles[p.id] !== 'ref') : null) || null;
      const list = pics.filter(p => p !== pinned);
      const first = pinned;
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
      if (multi().size > 1) drawMultiTools();
      return;
    }
    // thanh công cụ nổi (toạ độ màn hình, không phóng theo zoom)
    const has = (n.urls || []).length > 0;
    const busy = isBusy(n);
    const vers = (n.vers || []).length;
    const lockable = canLock(n);
    const groupsHtml = [[  // nhóm nút cách nhau bằng vạch: tạo tiếp · xem / lấy kết quả · chạy / khoá · dừng / xoá
      isPic(n) && has ? '<button data-act="to-video" title="Tạo node Video dùng ảnh này làm khung đầu">🎬 Tạo video</button>' : '',
      isPic(n) && has ? '<button data-act="edit" title="Tạo node Ảnh mới dùng ảnh này làm tham chiếu (sửa, đổi bối cảnh, thêm sản phẩm…)">🖌 Sửa ảnh</button>' : '',
      isPic(n) && has ? '<button data-act="upscale" title="Phóng to 2× trên máy (không tốn lượt model)">⤢ 2×</button>' : '',
      isPic(n) && !busy ? '<button data-act="replace" title="Chọn ảnh khác trên máy thay cho ảnh này — giữ nguyên dây nối, node phía sau sẽ dùng ảnh mới (ảnh cũ vào 🕘 Phiên bản)">🔄 Thay ảnh</button>' : '',
    ], [
      has ? '<button data-act="view" title="Xem lớn">⛶ Xem</button>' : '',
      has ? '<button data-act="download" title="Lưu file về máy">⬇ Tải về</button>' : '',
      n.kind === 'wf' && (n.out || {}).text ? '<button data-act="copy" title="Sao chép chữ kết quả">📋 Sao chép</button>' : '',
      (n.out || {}).folder ? '<button data-act="open-result" title="Mở thư mục khối Kết quả đã gom">📁 Mở thư mục</button>' : '',
      ((n.out || {}).post || {}).url ? '<button data-act="view-post" title="Mở bài đã đăng trong cửa sổ trình duyệt nhỏ">👁 Xem bài</button>' : '',
      vers ? `<button data-act="versions" title="${vers} kết quả trước của khối này — xem và chọn lại bản cũ">🕘 ${vers}</button>` : '',
      n.log_at ? '<button data-act="log" title="Nhật ký lần chạy gần nhất của khối này">📜</button>' : '',
    ], [
      n.kind !== 'upload' && !(n.kind === 'wf' && n.wtype === 'input_text') ? '<button data-act="run-menu" title="Chạy đến khối này (các khối phía trước + khối này) hoặc từ khối này trở đi">▶ Chạy ▾</button>' : '',
      lockable ? `<button data-act="lock" class="${n.locked ? 'on' : ''}" title="${n.locked ? 'Mở khoá — lần chạy sau tạo lại khối này nếu prompt / đầu vào đã đổi'
        : 'Khoá kết quả — chạy quy trình (kể cả Làm lại tất cả, trợ lý tự làm lại) luôn giữ nguyên kết quả này'}">${n.locked ? '🔓 Mở khoá' : '🔒 Khoá'}</button>` : '',
      n.kind !== 'upload' ? '<button data-act="dup" title="Nhân bản node (giữ prompt, model, nối)">⧉ Nhân bản</button>' : '',
      n.kind !== 'upload' && !busy ? '<button data-act="convert" title="Đổi khối này sang loại khác tại chỗ — giữ mã khối, vị trí, tên, chữ và các dây nối còn hợp (hoàn tác được)">🔁 Đổi khối</button>' : '',
    ], [
      busy ? '<button data-act="cancel" class="warn" title="Dừng tạo">⏹ Dừng</button>' : '',
      '<button data-act="del" class="danger" title="Xoá node (phím Delete) — hoàn tác được bằng ↶ / Ctrl+Z">🗑</button>',
    ]].map(g => g.filter(Boolean).join('')).filter(Boolean);
    tools.innerHTML = groupsHtml.join('<i class="cv-tools-sep"></i>');
    tools.classList.remove('hidden');
    tools.querySelectorAll('[data-act]').forEach(b => { b.onclick = e => { e.stopPropagation(); act(b.dataset.act, n.id, b); }; });
    placeTools();
    // ô prompt dưới node (nằm trong world → kéo / zoom theo node)
    if (n.kind === 'upload') return drawUploadPanel(n);
    if (n.kind === 'wf') return drawWfPanel(n);
    if (!panel || panel.dataset.for !== n.id) {
      if (panel) panel.remove();
      panel = document.createElement('div');
      panel.className = `cv-panel${isFlow(n) ? ' cv-panel-flow' : ''}`;  // 🎥 khối Google Flow: bố cục riêng
      panel.dataset.for = n.id;
      panel.onpointerdown = e => e.stopPropagation();
      panel.onwheel = e => e.stopPropagation();
      root.querySelector('.cv-stage').appendChild(panel);  // neo cột phải (như Trợ lý), không theo zoom
      panel.innerHTML = `${panelHead(n, n.kind === 'video' ? 'tạo video từ ảnh / prompt'
        : n.angles === 'character' ? 'bảng 5 góc nhân vật — nối vào Video / Storyboard'
          : n.angles === 'product' ? 'bảng 5 góc sản phẩm — nối vào Video / Storyboard' : 'tạo ảnh từ prompt')}${titleInput(n)}<div class="cv-in-note"></div><div class="cv-ins-box"></div>
        ${n.kind === 'image' && !n.angles ? `<div class="cv-refs-add" title="Chọn ảnh trên máy → đính kèm ngay trong khối này (hiện nhỏ trên thẻ) với vai trò — model giữ đúng nhân vật / sản phẩm / bối cảnh / phong cách"><b>📎 Ảnh tham chiếu</b>
          ${IMG_REFS.map(([r, i, l]) => `<button class="btn ghost sm" data-ref-add="${r}" type="button">${i} ${l}</button>`).join('')}</div>
          <div class="cv-refs-list"></div>` : ''}
        ${isFlow(n) && !n.part_of ? `<div class="cv-flow-sec"><div class="cv-refs-add" title="Ảnh thành phần gửi Google Flow (tối đa 3): chọn ảnh trên máy → đính kèm ngay trong khối (hiện nhỏ trên thẻ)"><b>📎 Thành phần</b>
          ${IMG_REFS.slice(0, 3).map(([r, i, l]) => `<button class="btn ghost sm" data-ref-add="${r}" type="button">${i} ${l}</button>`).join('')}</div>
          <div class="cv-refs-list"></div><small class="muted">Ảnh nối dây vào khối cũng được gửi kèm · Flow nhận tối đa 3 ảnh</small></div>` : ''}
        <div class="cv-dialogue-head cv-prompt-head"><b>✎ Prompt</b>
          <select data-prompt-src title="Lấy prompt từ khối chữ đang nối vào (Văn bản, AI viết…), viết trực tiếp, hoặc ghép cả hai"></select></div>
        <textarea placeholder="${n.kind === 'video' ? 'Mô tả chuyển động: người làm gì, máy quay thế nào (VD: cô gái mỉm cười giới thiệu sản phẩm, máy đứng yên)…'
          : 'Mô tả ảnh muốn tạo (VD: Ảnh đang livestream trên TikTok, có thiết bị và trưng bày các sản phẩm)…'}"></textarea>
        ${n.kind === 'video' ? `<div class="cv-dialogue"><div class="cv-dialogue-head"><b>💬 Lời thoại</b>
            <select data-dlg-src title="Lấy lời thoại từ khối chữ đang nối vào (Văn bản, AI viết…) hoặc tự nhập"></select><small data-dlg-count></small>
            <button class="btn ghost sm hidden" data-dlg-split type="button" title="Tách lời thoại ở cuối câu thành nhiều node Video (mỗi node nói kịp trong clip, cùng ảnh / prompt), nối sẵn vào khối phía sau — không tốn lượt AI">✂ Tách</button></div>
          <textarea data-dlg rows="3" placeholder="Câu nhân vật nói trong video (tiếng Việt, đúng nguyên văn). Mỗi dòng 1 câu; nhiều người: Tên: câu nói"></textarea>
          <label class="cv-opt-check cv-auto-split${FLOWSCREEN && n.template ? ' hidden' : ''}" title="Khi chạy, lời thoại dài hơn mức nói kịp trong clip → app tự tách ở cuối câu thành nhiều video (cùng ảnh / prompt), quay từng video rồi ghép lại thành 1 — không hỏi lại, không tốn lượt AI để tách"><input type="checkbox" data-auto-split ${n.auto_split === false ? '' : 'checked'}> ✂ Lời dài → tự tách nhiều video rồi ghép thành 1</label></div>` : ''}
        <div class="cv-opts"></div><div class="cv-qc-box"></div>
        <div class="cv-panel-row cv-panel-foot"><span class="cv-sp"></span>
          <button class="btn ghost sm" data-p="enhance" title="Nhờ model chữ (Cài đặt → Model AI) viết lại prompt chi tiết hơn">✨ Viết lại prompt</button>
          <button class="btn primary sm" data-p="go"></button></div>`;
      bindPanelHead(panel);
      panel.querySelectorAll('[data-ref-add]').forEach(b => { b.onclick = () => addInlineRef(n.id, b.dataset.refAdd); });
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
        dlg.onchange = async () => {  // gõ xong (rời ô) → lời dài thì tự tách ngay
          if (dlg.readOnly) return;
          clearTimeout(C.dlgT);
          await call('canvas_update_nodes', C.board.id, [{ id: n.id, dialogue: dlg.value }]);
          autoSplit(n.id);
        };
      }
      bindTitle(panel, n.id);
      const splitBtn = panel.querySelector('[data-dlg-split]');
      if (splitBtn) splitBtn.onclick = () => splitVideo(n.id);
      const autoBox = panel.querySelector('[data-auto-split]');
      if (autoBox) {
        autoBox.onchange = async () => {
          await setOption(n.id, 'auto_split', autoBox.checked);
          dialogueCount(panel, node(n.id));
          if (autoBox.checked) autoSplit(n.id);
        };
      }
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
    const head = n.part_of ? node(n.part_of) : null;  // ✂ video con: ảnh + ý tưởng + lời lấy từ khối Video chung
    const fromNode = !!(psrc && psrc !== 'own') || !!head;
    const modeChanged = ta.readOnly !== fromNode;  // vừa đổi nguồn → luôn thay chữ trong ô (kể cả khi ô đang focus)
    ta.readOnly = fromNode;
    ta.classList.toggle('from-src', fromNode);
    ta.placeholder = fromNode ? `Khối ${psrc} chưa có chữ — chạy khối đó trước, hoặc ▶ Chạy toàn bộ`
      : psrc === '' && ptexts.length ? 'Viết thêm (không bắt buộc) — được ghép sau chữ từ khối nối vào…'
        : n.kind === 'video' ? 'Mô tả chuyển động: người làm gì, máy quay thế nào (VD: cô gái mỉm cười giới thiệu sản phẩm, máy đứng yên)…'
          : n.angles === 'character' ? '🧍 Nối ảnh nhân vật vào — app tự tạo bảng 5 góc (trước, ¾, nghiêng, sau, cận mặt). Ghi thêm nếu cần (VD: giữ nguyên sơ mi trắng, chân váy đen)…'
            : n.angles === 'product' ? '📦 Nối ảnh sản phẩm vào — app tự tạo bảng 5 góc (trước, ¾, cạnh, sau, trên). Ghi thêm nếu cần (VD: xô nhựa trắng 22kg, nắp có quai)…'
              : 'Mô tả ảnh muốn tạo (VD: Ảnh đang livestream trên TikTok, có thiết bị và trưng bày các sản phẩm)…';
    if (head) ta.placeholder = `🔗 Phần ${n.part} của khối Video chung ${head.id} — dùng ảnh + ý tưởng / prompt của khối đó (sửa ở khối chung)`;
    const wantPrompt = head ? '' : fromNode ? sourceText(node(psrc), n, 'prompt') : (n.prompt || '');
    if ((modeChanged || fromNode || document.activeElement !== ta) && ta.value !== wantPrompt) ta.value = wantPrompt;
    panel.querySelector('[data-p="enhance"]').disabled = fromNode;
    panel.querySelector('.cv-in-note').innerHTML = inputsNote(n) + (n.stage && !busy ? ` · <i>${esc(n.stage)}</i>` : '');
    drawInputs(panel, n);
    panel.querySelector('.cv-opts').innerHTML = optionsHtml(n);
    drawRefsList(panel, n);
    drawQc(panel, n);
    const dlg = panel.querySelector('[data-dlg]');
    if (dlg) {
      const srcSel = panel.querySelector('[data-dlg-src]');
      const srcs = dialogueSources(n);
      srcSel.innerHTML = `<option value="">✍ Tự nhập</option>${srcs.map(x => `<option value="${esc(x.id)}" ${x.id === n.dialogue_src ? 'selected' : ''}>
        Lấy từ ${esc(x.id)} · ${esc(labelOf(x))}</option>`).join('')}`;
      srcSel.disabled = !srcs.length;
      srcSel.title = srcs.length ? 'Lấy lời thoại từ khối chữ đang nối vào, hoặc tự nhập' : 'Nối khối Văn bản / AI viết vào node này để lấy lời thoại từ đó';
      srcSel.onchange = async () => { await setOption(n.id, 'dialogue_src', srcSel.value); autoSplit(n.id); };
      const fromSrc = !!(n.dialogue_src && node(n.dialogue_src)) || !!head;
      dlg.readOnly = fromSrc;
      dlg.classList.toggle('from-src', fromSrc);
      if (head) srcSel.disabled = true;
      const autoRow = panel.querySelector('.cv-auto-split');
      if (autoRow) autoRow.classList.toggle('hidden', !!head);
      dlg.placeholder = fromSrc ? `Khối ${n.dialogue_src} chưa có chữ — chạy nó trước, hoặc ▶ Chạy toàn bộ`
        : 'Câu nhân vật nói trong video (tiếng Việt, đúng nguyên văn). Mỗi dòng 1 câu; nhiều người: Tên: câu nói';
      const want = head || !n.dialogue_src ? (n.dialogue || '') : sourceText(node(n.dialogue_src), n, 'loi');
      if (document.activeElement !== dlg && dlg.value !== want) dlg.value = want;
      dialogueCount(panel, n);
    }
    panel.querySelectorAll('[data-f]').forEach(s => {
      s.onchange = async () => {
        await setOption(n.id, s.dataset.f, s.type === 'checkbox' ? s.checked : s.value);
        if (n.kind === 'video' && s.dataset.f === 'duration') autoSplit(n.id);  // clip ngắn lại → lời có thể thành dài
      };
    });
    panel.querySelectorAll('[data-set]').forEach(b => {  // nút chọn dạng bấm (tỉ lệ khối Google Flow)
      b.onclick = async () => {
        if (b.classList.contains('on')) return;
        await setOption(n.id, b.dataset.set, b.dataset.val);
        if (b.dataset.set === 'build') autoSplit(n.id);  // 🎞 đổi sang Tách khối → tách ngay nếu lời dài
      };
    });
    const go = panel.querySelector('[data-p="go"]');
    go.textContent = busy ? `⏹ Dừng (${Math.round(n.pct || 0)}%)` : n.locked ? '🔒 Đã khoá' : has ? '↻ Tạo lại' : '✦ Tạo';
    go.classList.toggle('danger', busy);
    go.disabled = !!n.locked && !busy;
    go.title = n.locked ? 'Khối đang khoá — bấm 🔓 Mở khoá trên thanh công cụ để tạo lại' : '';
    lockNote(panel, n);
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
    if (f.type === 'heygen_avatar' || f.type === 'heygen_voice') {  // 🧑‍💼 danh sách tải từ HeyGen (lưu trên máy)
      const opts = f.options || [];
      const cur = String(v ?? '');
      const known = opts.some(o => String(o.value) === cur);
      return `<label class="field"><span>${esc(f.label)} <button class="link" data-heygen-reload type="button" title="Lấy avatar / giọng từ tài khoản HeyGen (không tốn credit)">↻ tải từ HeyGen</button></span>
        <select data-c="${f.key}">${opts.map(o => `<option value="${esc(o.value)}" ${String(o.value) === cur ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}${known ? '' : `<option value="${esc(cur)}" selected>${esc(cur)} (đã chọn)</option>`}</select>
        ${f.loaded ? '' : '<small class="muted">Chưa tải danh sách — bấm ↻ tải từ HeyGen (cần HeyGen API key ở Cài đặt)</small>'}</label>`;
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
      root.querySelector('.cv-stage').appendChild(panel);  // neo cột phải (như Trợ lý), không theo zoom
    }
    const busy = isBusy(n);
    const cfg = n.config || {};
    const ins = (n.inputs || []).map(node).filter(Boolean);
    const needSrc = s.fields.some(f => ['fb_page', 'ad_account', 'studio_preset'].includes(f.type));
    if (fresh) {
      if (needSrc && (!SRC.fb || !SRC.studio)) loadSources().then(() => { if (C.sel === n.id) drawWfPanel(node(n.id), true); });
      const keep = document.activeElement && panel.contains(document.activeElement) ? document.activeElement.dataset.c : '';
      panel.innerHTML = `${panelHead(n, GROUP_VI[s.group] || '')}${titleInput(n)}<div class="cv-in-note">${esc(s.desc)}${ins.length ? '' : s.inputs.length
          ? `<br>Nối vào: ${s.inputs.map(p => esc(p.label)).join(' · ')}` : ''}</div><div class="cv-ins-box"></div>
        ${n.wtype === 'product_studio' ? `<div class="cv-refs-add" title="Chọn ảnh trên máy → khối ảnh tải lên, nối vào và đặt vai trò — dùng làm Character Lock / Product Lock cho mọi cảnh"><b>📎 Ảnh tham chiếu</b>
          ${IMG_REFS.slice(0, 2).map(([r, i, l]) => `<button class="btn ghost sm" data-ref-add="${r}" type="button">${i} ${l}</button>`).join('')}</div>` : ''}
        ${n.wtype === 'input_video' ? '' : `<label class="cv-opt-check cv-ask-toggle" title="Mỗi lần chạy quy trình, app hỏi lại các ô của khối này (sửa được trước khi chạy)"><input type="checkbox" data-ask-toggle ${n.ask ? 'checked' : ''}> ❓ Hỏi lại các ô này mỗi lần chạy quy trình</label>${askFieldsHtml(n)}`}
        <label class="cv-opt-check" title="Bật: các ô bắt buộc (prompt, chủ đề…) để trống vẫn chạy — không chặn quy trình"><input type="checkbox" data-opt-toggle ${n.optional ? 'checked' : ''}> ✏ Không bắt buộc nhập</label>
        <div class="cv-wf-fields">${s.fields.filter(f => fieldVisible(f, cfg)).map(f => fieldHtml(f, cfg)
          + (n.wtype === 'post_video' && f.key === 'script' ? `<div class="cv-panel-row cv-listen"><button class="btn sm" data-listen ${busy ? 'disabled' : ''}
            title="Nghe tiếng thật trong video đầu vào (Gemini API) — không nghe được thì lấy lời thoại đã giao cho khối Video nguồn — rồi điền vào ô Lời đọc / phụ đề để bạn sửa">🎧 Phân tích lời thoại từ video</button>
          <small class="muted">Để trống → tự phân tích khi chạy</small></div>` : '')).join('')}</div>
        ${s.outputs.some(o => o.type === 'text') && (n.out || {}).text !== undefined && n.wtype !== 'input_text' ? `<label class="field"><span>Kết quả — sửa được trước khi dùng tiếp</span>
          <textarea data-out rows="6">${esc((n.out || {}).text || '')}</textarea></label>` : ''}
        ${['fb_post', 'fb_schedule'].includes(n.wtype) ? `<label class="cv-opt-check cv-auto-post ${n.auto_post ? 'on' : ''}" title="Bật: khi chạy, khối này đăng / hẹn giờ thẳng lên Fanpage, không dừng chờ bạn duyệt"><input type="checkbox" data-auto-post ${n.auto_post ? 'checked' : ''}> 🚀 Tự đăng không cần duyệt</label>
          <small class="${n.auto_post ? 'warn-text' : 'muted'}">${n.auto_post ? '⚠ Khi chạy sẽ ĐĂNG THẲNG lên Fanpage, không hỏi lại — tắt ô trên nếu muốn xem trước.'
            : n.to_posts ? '📥 Không đăng ngay: bài được lưu vào Quản lý bài đăng ở mục “Chờ duyệt” (có thông báo 🔔 + chuông) — Canvas chạy tiếp, bạn duyệt & đăng ở đó.'
            : '🔒 Dừng chờ bạn bấm “Đồng ý đăng” trên node trước khi đăng.'}</small>
          ${n.auto_post ? '' : `<label class="cv-opt-check cv-to-posts ${n.to_posts ? 'on' : ''}" title="Bật: không dừng chờ trên node — lưu bài vào Quản lý bài đăng (Chờ duyệt) và báo bạn"><input type="checkbox" data-to-posts ${n.to_posts ? 'checked' : ''}> 📥 Lưu vào Quản lý bài đăng — chờ duyệt</label>`}` : ''}
        ${n.wtype === 'fb_ad' ? '<small class="muted">Quảng cáo tạo ở trạng thái TẠM DỪNG — bật ở mục Quảng cáo Facebook khi sẵn sàng.</small>' : ''}
        ${n.wtype === 'product_studio' ? studioHtml(n) : ''}${n.qc_required ? '<div class="cv-qc-box"></div>' : ''}
        <div class="cv-panel-row cv-panel-foot"><span class="cv-sp"></span><button class="btn primary sm" data-p="go"></button></div>`;
      panel.querySelectorAll('[data-ref-add]').forEach(b => { b.onclick = () => addRef(n.id, b.dataset.refAdd); });
      bindStudio(panel, n);
      drawQc(panel, n);
      bindPanelHead(panel);
      panel.querySelectorAll('[data-c]').forEach(el => {
        const key = el.dataset.c;
        const field = s.fields.find(f => f.key === key);
        const value = () => (el.type === 'checkbox' ? el.checked : el.value);
        const redraw = el.tagName === 'SELECT' || el.type === 'checkbox' || s.fields.some(f => f.when && key in f.when);
        el.oninput = () => saveConfig(n.id, { [key]: value() }, false);
        el.onchange = () => saveConfig(n.id, { [key]: value() }, redraw && field);
      });
      bindTitle(panel, n.id);
      const optToggle = panel.querySelector('[data-opt-toggle]');  // ✏ không bắt buộc nhập
      if (optToggle) optToggle.onchange = () => setOption(n.id, 'optional', optToggle.checked);
      const askToggle = panel.querySelector('[data-ask-toggle]');
      if (askToggle) {
        askToggle.onchange = async () => {  // bật / tắt hỏi → vẽ lại bảng để hiện / ẩn ô chọn “Ô hỏi khi chạy”
          await setOption(n.id, 'ask', askToggle.checked);
          const p = body().querySelector('.cv-panel');
          if (p && p.dataset.for === n.id) { p.remove(); drawPanel(); }
        };
      }
      const toPosts = panel.querySelector('[data-to-posts]');
      if (toPosts) {
        toPosts.onchange = async () => { await setOption(n.id, 'to_posts', toPosts.checked); drawWfPanel(node(n.id), true); };
      }
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
      panel.querySelectorAll('[data-heygen-reload]').forEach(b => {
        b.onclick = async e => {
          e.preventDefault();
          b.disabled = true;
          b.textContent = 'Đang tải…';
          const r = await call('canvas_heygen_lists', true);
          if (r && C.meta.wf_types.heygen_video) {
            C.meta.wf_types.heygen_video.fields = r.fields;
            toast(`Đã tải ${r.avatars} avatar · ${r.voices} giọng từ HeyGen`, 'ok');
          }
          if (C.sel === n.id) drawWfPanel(node(n.id), true);
        };
      });
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
      const listen = panel.querySelector('[data-listen]');
      if (listen) {
        listen.onclick = async () => {
          const cur = String((node(n.id).config || {}).script || '').trim();
          if (cur && !confirm('Thay nội dung ô Lời đọc / phụ đề bằng lời thoại phân tích từ video đầu vào?')) return;
          const label = listen.textContent;
          listen.disabled = true;
          listen.textContent = '⏳ Đang phân tích…';
          const res = await call('canvas_analyze_dialogue', C.board.id, n.id);
          listen.disabled = false;
          listen.textContent = label;
          if (!res) return;
          C.board = res.result.board;
          drawWfPanel(node(n.id), true);
          toast('Đã điền lời thoại vào ô Lời đọc / phụ đề — sửa lại nếu cần', 'ok');
        };
      }
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
    go.textContent = busy ? `⏹ Dừng${n.status === 'waiting' ? '' : ` (${Math.round(n.pct || 0)}%)`}` : n.locked ? '🔒 Đã khoá'
      : n.status === 'done' ? '↻ Chạy lại' : '▶ Chạy';
    go.classList.toggle('danger', busy);
    go.disabled = !!n.locked && !busy;
    go.title = n.locked ? 'Khối đang khoá — bấm 🔓 Mở khoá trên thanh công cụ để chạy lại' : '';
    lockNote(panel, n);
    drawInputs(panel, n);
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
      panel.onwheel = e => e.stopPropagation();
      root.querySelector('.cv-stage').appendChild(panel);  // neo cột phải (như Trợ lý), không theo zoom
    }
    const has = (n.urls || []).length > 0;
    const web = (n.inputs || []).filter(i => node(i));
    panel.innerHTML = `${panelHead(n, 'ảnh của bạn')}${titleInput(n)}<div class="cv-in-note">${has ? (String(n.made || '').startsWith('Ảnh sản phẩm lấy từ web') ? `🖼 ${esc(n.made)}` : 'Ảnh đã tải sẵn — dùng cho mọi lần chạy') : 'Chưa có ảnh'}${n.ask ? ' · <b>❓ sẽ hỏi chọn ảnh khi chạy quy trình</b>' : ''}
      ${web.length ? `<br>🌐 Nối từ <b>${esc(web.join(', '))}</b> (Tra cứu web): mỗi lần khối đó chạy, tìm được ảnh sản phẩm thì <b>thay ảnh này</b> (ảnh cũ vào 🕘 Phiên bản); không có thì ${has ? 'giữ ảnh đang có' : '<b>bạn cần tải ảnh lên</b>'}.` : ''}
      ${n.status === 'error' && n.error ? `<br><span class="warn-text">⚠ ${esc(n.error)}</span>` : ''}</div>
      <div class="cv-panel-row cv-panel-foot"><label class="cv-opt-check" title="Mỗi lần ▶ Chạy toàn bộ / Đến đây / Từ đây, app hỏi chọn ảnh cho đầu vào này (vd. mỗi lần 1 sản phẩm khác)"><input type="checkbox" data-up-ask ${n.ask ? 'checked' : ''}> ❓ Hỏi chọn ảnh mỗi lần chạy</label>
        <label class="cv-opt-check" title="Không chọn ảnh vẫn chạy — khối phía sau chạy không có ảnh này"><input type="checkbox" data-up-opt ${n.optional ? 'checked' : ''}> ✏ Không bắt buộc</label>
        <span class="cv-sp"></span><button class="btn ${has ? 'ghost' : 'primary'} sm" data-up-pick type="button">⬆ ${has ? 'Chọn ảnh khác…' : 'Chọn ảnh…'}</button></div>`;
    bindPanelHead(panel);
    bindTitle(panel, n.id);
    panel.querySelector('[data-up-pick]').onclick = () => act('replace', n.id);
    panel.querySelector('[data-up-ask]').onchange = e => setOption(n.id, 'ask', e.target.checked);
    panel.querySelector('[data-up-opt]').onchange = e => setOption(n.id, 'optional', e.target.checked);
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
  // node Video tách từ Storyboard (n.scene = k): chỉ lấy phần của cảnh k (prompt / lời thoại), không phải cả storyboard
  const sceneOf = (src, n) => (src && ['storyboard_video', 'product_studio'].includes(src.wtype) && n && n.scene ? ((src.out || {}).scenes || [])[n.scene - 1] || {} : null);
  const sourceText = (src, n, key) => {
    const sc = sceneOf(src, n);
    if (sc) return sc[key] || '';
    return !src ? '' : src.wtype === 'input_text' && !(src.out || {}).text ? (src.config || {}).text || '' : (src.out || {}).text || '';
  };
  const spokenText = n => (n.dialogue_src && node(n.dialogue_src) ? sourceText(node(n.dialogue_src), n, 'loi') : n.dialogue || '');
  const typedDialogue = dlg => (dlg && !dlg.readOnly ? { dialogue: dlg.value } : {});  // lấy từ khối → không ghi đè chữ tự nhập

  async function splitVideo(id) {
    // ✂ lời thoại dài → nhiều node Video (cùng ảnh / prompt, mỗi node 1 đoạn nói kịp), nối sẵn vào khối phía sau
    await savePanelNow();
    const res = await call('canvas_split_video', C.board.id, id);
    if (!res) return null;
    C.board = res.result.board;
    drawAll();
    const r = res.result;
    toast(`✂ Đã tách lời thoại thành ${r.parts} video (${r.nodes.join(', ')})${r.merge ? `, ghép lại thành 1 ở ${r.merge}` : ''}${r.unlinked.length ? ` — ${r.unlinked.join(', ')} đã đủ 10 đầu vào, chưa nối thêm được (nối tay nếu cần)` : ''}. Hoàn tác: Ctrl+Z`, 'ok');
    return r;
  }

  async function autoSplit(id) {
    // ✂ tự tách ngay khi lời thoại (tự nhập / lấy từ khối kịch bản) dài hơn mức nói kịp — không cần bấm nút
    const n = node(id);
    const tplSplit = n && n.template && n.build === 'split';  // 🎞 mẫu "Tách khối": luôn tự tách
    if (!n || n.kind !== 'video' || (n.auto_split === false && !tplSplit) || isBusy(n)) return null;
    const res = await call('canvas_auto_split', C.board.id, id);
    const r = res && res.result;
    if (!r || !r.split) return null;
    C.board = r.board;
    drawAll();
    toast(r.parts ? `✂ Lời thoại dài → đã tự tách ${r.parts} video con từ ${id} (${r.nodes.join(', ')})${r.merge ? `, ghép lại thành 1 ở ${r.merge}` : ''} — khối chung giữ nguyên. Hoàn tác: Ctrl+Z`
      : `✂ Lời thoại ${id} đã vừa 1 clip — bỏ các video con, khối chung tự quay`, 'ok');
    return r;
  }

  function dialogueCount(panel, n) {
    // đếm chữ lời thoại (bỏ "Tên:" đầu dòng) so với số chữ nói kịp trong thời lượng clip
    const el = panel.querySelector('[data-dlg-count]');
    if (!el) return;
    const words = String(spokenText(n)).replace(/^[^:\n]{1,30}:\s*/gm, '').split(/\s+/).filter(Boolean).length;
    const secs = parseInt(String(n.duration || '10s'), 10) || 10;
    const limit = Math.max(4, Math.floor((secs - 1) * ((C.meta && C.meta.words_per_sec) || 3.2)));
    el.className = words > limit ? 'warn-text' : 'muted';
    const split = panel.querySelector('[data-dlg-split]');
    if (split) {  // ✂ lời dài → gợi ý tách (số video thật do app tính khi tách, cắt ở cuối câu)
      split.classList.toggle('hidden', !(words > limit) || isBusy(n) || n.auto_split !== false);  // tự tách bật → không cần nút
      split.textContent = `✂ Tách thành ~${Math.ceil(words / limit)} video`;
    }
    const kids = (C.board.nodes || []).filter(x => x.part_of === n.id).length;
    const tplOne = FLOWSCREEN && n.template && n.build !== 'split';  // 🎞 mẫu Không tách: khối tự chia + ghép bên trong
    if (split && tplOne) split.classList.add('hidden');
    const long = kids ? ` — ✂ đã chia ${kids} video con` : tplOne ? ` — 🎞 tự chia ~${Math.ceil(words / limit)} đoạn rồi ghép trong khối` : n.auto_split === false ? ' — dài, dễ nói vội / bị cắt' : ` — tự tách ~${Math.ceil(words / limit)} video rồi ghép`;
    if (kids) el.className = 'muted';
    el.textContent = n.part_of ? `phần ${n.part} · ${words}/${limit} chữ — sửa lời ở khối chung ${n.part_of}`
      : words ? `${words}/${limit} chữ cho ${secs} giây${words > limit ? long : ''}` : `nói kịp ~${limit} chữ trong ${secs} giây`;
  }

  function placeTools() {
    const root = body();
    const tools = root.querySelector('.cv-tools');
    const n = node(C.sel);
    const el = n && root.querySelector(`[data-node="${n.id}"]`);
    if (tools && !n && multi().size > 1 && !tools.classList.contains('hidden')) {
      const b = multiBox();
      tools.style.left = `${C.view.x + (b.x1 + b.x2) / 2 * C.view.k}px`;
      tools.style.top = `${C.view.y + b.y1 * C.view.k - 12}px`;
      return;
    }
    if (!tools || !el || tools.classList.contains('hidden')) return;
    const { x, y, k } = C.view;
    let left = x + (n.x + el.offsetWidth / 2) * k;
    const panel = root.querySelector('.cv-panel');  // không đè lên ô cấu hình cột phải
    if (panel) left = Math.max(tools.offsetWidth / 2 + 8, Math.min(left, panel.offsetLeft - 10 - tools.offsetWidth / 2));
    tools.style.left = `${left}px`;
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

  /* ================================================================ 🎬 Product Video Studio · ✅ kiểm duyệt */
  const QC_VI = { empty: 'Chưa có clip', pending: '⏳ Chờ duyệt', approved: '✅ Đã duyệt', rejected: '❌ Từ chối' };
  const QC_DEFAULT = ['Khuôn mặt nhân vật đúng bộ ảnh tham chiếu', 'Trang phục, kiểu tóc và vóc dáng nhất quán',
    'Hình dáng bao bì, nắp và màu sắc đúng', 'Nhãn, logo, chữ và tên sản phẩm không bị biến dạng hoặc thay đổi',
    'Công dụng, thành phần và thông điệp đã được phê duyệt', 'Lời thoại chính xác, phát âm phù hợp',
    'Không có sản phẩm, logo hoặc vật thể ngoài ý muốn', 'Bố cục / tỷ lệ khung hình phù hợp nền tảng đăng tải'];
  const qcFlag = n => (n.qc_required && n.qc_state && n.qc_state !== 'empty'
    ? [{ pending: '⏳', approved: '✅', rejected: '❌' }[n.qc_state] || '⏳', `${n.qc_final ? 'Bản cuối' : 'Clip'}: ${QC_VI[n.qc_state] || ''}`] : null);
  const qcOwner = n => node(n.scene_of || n.studio_of || n.concat_of || '');
  const approver = () => { try { return localStorage.getItem('cv-qc-by') || ''; } catch { return ''; } };

  function studioHtml(n) {  // khối Studio: sao chép storyboard / prompt (dán vào Grok / Flow nếu làm tay)
    const st = (n.out || {}).studio;
    if (!st) return `<small class="muted">🎬 Chạy khối → AI chia cảnh, mỗi cảnh 1 khối Video (${FLOWSCREEN ? 'Grok · quay từ ảnh bìa đã duyệt' : 'Google Flow'}), duyệt từng clip rồi mới ghép.</small>`;
    return `<div class="cv-studio">
      <div class="cv-panel-row"><button class="btn ghost sm" data-studio-copy="all" type="button" title="Toàn bộ storyboard: cảnh, lời thoại, prompt">📋 Sao chép storyboard + prompt</button>
        <button class="btn ghost sm" data-studio-copy="prompts" type="button" title="Chỉ prompt tiếng Anh từng cảnh — dán vào ${FLOWSCREEN ? 'Grok Imagine' : 'Google Flow'} nếu làm tay">📋 Chỉ prompt tiếng Anh</button></div></div>`;
  }

  function bindStudio(panel, n) {
    panel.querySelectorAll('[data-studio-copy]').forEach(b => {
      b.onclick = async () => {
        const cur = node(n.id);
        const st = (cur.out || {}).studio || {};
        const text = b.dataset.studioCopy === 'all' ? String((cur.out || {}).text || '')
          : (st.prompts || []).map((p, i) => `Scene ${i + 1}:\n${p}`).join('\n\n');
        try { await navigator.clipboard.writeText(text); toast('📋 Đã sao chép', 'ok'); } catch { toast('Không sao chép được — chọn chữ ở ô Kết quả', 'warn'); }
      };
    });
  }

  function qcHtml(n) {
    const st = n.qc_state || 'empty';
    const q = n.qc || {};
    const owner = qcOwner(n);
    const list = (((owner || {}).out || {}).studio || {}).checklist || QC_DEFAULT;
    const same = st === q.status;
    const done = new Set(same ? q.checks || [] : []);
    const hist = (q.history || []).slice(-6).reverse();
    return `<div class="cv-qc ${st}"><div class="cv-qc-head"><b>✅ Kiểm duyệt ${n.qc_final ? 'bản cuối (trước khi đăng)' : 'clip'}</b>
        <span class="cv-qc-st">${QC_VI[st] || st}</span></div>
      ${st === 'empty' ? '<small class="muted">Chưa có kết quả — tạo xong rồi duyệt</small>' : `
      <div class="cv-qc-list">${list.map(x => `<label class="cv-opt-check"><input type="checkbox" data-qc-check value="${esc(x)}" ${done.has(x) ? 'checked' : ''}> ${esc(x)}</label>`).join('')}</div>
      <textarea data-qc-notes rows="2" placeholder="Nhận xét — bắt buộc ghi lý do khi từ chối (VD: nhãn bị méo, sai khuôn mặt)">${esc(same ? q.notes || '' : '')}</textarea>
      <div class="cv-panel-row"><input data-qc-by placeholder="Người duyệt" value="${esc(approver())}">
        <button class="btn primary sm" data-qc-do="approved" type="button">✅ Duyệt</button>
        <button class="btn ghost sm" data-qc-do="rejected" type="button">❌ Từ chối</button>
        ${q.status && q.status !== 'pending' ? '<button class="btn ghost sm" data-qc-do="reset" type="button" title="Bỏ quyết định">↺</button>' : ''}</div>`}
      ${hist.length ? `<details class="cv-qc-hist"><summary>Lịch sử duyệt (${(q.history || []).length})</summary>${hist.map(h =>
        `<div><b>${esc(QC_VI[h.status] || h.status)}</b> · ${esc(h.by || '—')} · ${esc(String(h.at || '').slice(0, 16))}${h.notes ? ` — ${esc(h.notes)}` : ''}</div>`).join('')}</details>` : ''}
      <small class="muted">Video AI không bảo đảm tuyệt đối đúng khuôn mặt / chữ trên nhãn — đối chiếu ảnh gốc trước khi duyệt.</small></div>`;
  }

  function drawQc(panel, n) {
    const box = panel && panel.querySelector('.cv-qc-box');
    if (!box) return;
    if (!n.qc_required) { box.innerHTML = ''; return; }
    const sig = JSON.stringify([n.qc_state, (n.qc || {}).at, (n.files || [])[0]]);
    if (box.dataset.sig === sig) return;  // không vẽ lại khi đang tích / gõ nhận xét
    box.dataset.sig = sig;
    box.innerHTML = qcHtml(n);
    box.querySelectorAll('[data-qc-do]').forEach(b => {
      b.onclick = async () => {
        const decision = b.dataset.qcDo;
        const checks = [...box.querySelectorAll('[data-qc-check]')];
        const picked = checks.filter(c => c.checked).map(c => c.value);
        const notes = (box.querySelector('[data-qc-notes]') || {}).value || '';
        const by = ((box.querySelector('[data-qc-by]') || {}).value || '').trim();
        if (decision === 'approved' && picked.length < checks.length
            && !confirm(`Mới tích ${picked.length}/${checks.length} mục checklist. Vẫn duyệt ${n.id}?`)) return;
        if (decision === 'rejected' && !notes.trim()) { toast('Ghi lý do từ chối vào ô nhận xét', 'warn'); return; }
        try { localStorage.setItem('cv-qc-by', by); } catch { /* bộ nhớ trình duyệt bị chặn */ }
        const res = await call('canvas_qc', C.board.id, n.id, decision, notes, picked, by);
        if (!res) return;
        C.board = res.board;
        drawAll();
        const cur = node(n.id);
        box.dataset.sig = '';
        drawQc(panel, cur);
        toast(`${n.id}: ${QC_VI[cur.qc_state] || decision}`, decision === 'approved' ? 'ok' : '');
      };
    });
  }

  /* ---- 📎 ảnh tham chiếu đính kèm NGAY trong khối Ảnh: ảnh nhỏ trên thẻ + danh sách đổi vai trò / bỏ trong ô cấu hình */
  const refIcon = role => (IMG_REFS.find(r => r[0] === role) || ['', '📎', 'Tham chiếu chung']);
  function refStrip(n) {
    const refs = n.ref_urls || [];
    const tc = tplChip(n);
    const chips = tc || isFlow(n) ? tc + (isFlow(n) ? `<div class="cv-flow-card-chips"><span>Veo</span><span>${esc(n.duration || '8s').replace('s', ' giây')}</span><span>${esc(n.aspect || '9:16')}</span>${refs.length ? `<span>📎 ${refs.length}</span>` : ''}</div>` : '') : '';
    if (!refs.length) return chips;
    return chips + refStripImgs(refs);
  }
  function refStripImgs(refs) {
    return `<div class="cv-refstrip">${refs.map(r => { const [, i, l] = refIcon(r.role);
      return `<span class="cv-refthumb" title="${esc(l)}"><img src="${esc(thumbUrl(r.url, 120))}" alt="" draggable="false"><i>${i}</i></span>`; }).join('')}</div>`;
  }
  function drawRefsList(panel, n) {
    const box = panel.querySelector('.cv-refs-list');
    if (!box) return;
    const refs = n.ref_urls || [];
    const sig = JSON.stringify(refs.map(r => [r.file, r.role]));
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig;
    box.innerHTML = refs.map((r, k) => `<div class="cv-refrow"><img src="${esc(thumbUrl(r.url, 120))}" alt="">
      <select data-ref-role="${k}" title="Ảnh này dùng để">${[['', '📎 Tham chiếu chung'], ...IMG_REFS.map(([v, i, l]) => [v, `${i} ${l}`])]
        .map(([v, l]) => `<option value="${v}" ${(r.role || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn ghost sm" data-ref-rm="${k}" type="button" title="Bỏ ảnh này (↶ hoàn tác được)">✕</button></div>`).join('');
    const save = async list => {
      const res = await call('canvas_update_nodes', C.board.id, [{ id: n.id, ref_files: list }]);
      if (res) { C.board = res.board; drawAll(); drawPanel(); }
    };
    const cur = () => (node(n.id).ref_urls || []).map(r => ({ file: r.file, role: r.role }));
    box.querySelectorAll('[data-ref-role]').forEach(s => {
      s.onchange = () => { const list = cur(); list[+s.dataset.refRole].role = s.value; save(list); };
    });
    box.querySelectorAll('[data-ref-rm]').forEach(b => {
      b.onclick = () => save(cur().filter((_, k) => k !== +b.dataset.refRm));
    });
  }
  async function addInlineRef(id, role) {
    if (!C.board || !node(id)) return;
    const res = await call('canvas_add_ref', C.board.id, id, role);
    if (!res || !res.result) return;  // không chọn ảnh
    C.board = res.result.board;
    C.sel = id;
    drawAll();
    drawPanel();
    const [, , label] = refIcon(role);
    toast(`📎 Đã đính kèm ảnh ${label.toLowerCase()} vào ${id} — bấm Tạo`, 'ok');
  }

  /** 📎 khối Ảnh → chọn ảnh trên máy làm tham chiếu `role` (nhân vật / sản phẩm / bối cảnh / phong cách): tạo khối ảnh tải
      lên bên trái, đặt tên theo vai trò, nối vào khối Ảnh và đặt vai trò cho dây đó (↶ hoàn tác từng bước). */
  async function addRef(id, role) {
    const n = node(id);
    if (!C.board || !n) return;
    const [, icon, label] = IMG_REFS.find(r => r[0] === role) || ['', '📎', 'Tham chiếu'];
    const before = new Set(C.board.nodes.map(x => x.id));
    // đặt dưới khối tham chiếu cuối cùng (theo chiều cao thật trên bảng — ảnh dọc cao hơn) để không chồng lên nhau
    const last = (n.inputs || []).map(node).filter(x => x && x.kind === 'upload').pop();
    const el = last && body().querySelector(`[data-node="${last.id}"]`);
    const y = last ? last.y + (el ? el.offsetHeight : 420) + 40 : n.y;
    const up = await call('canvas_upload', C.board.id, last ? last.x : n.x - 360, y);
    if (!up || !up.result) return;  // không chọn ảnh
    const added = up.result.board.nodes.filter(x => !before.has(x.id) && x.kind === 'upload');
    let res = null;
    for (const a of added) {
      await call('canvas_connect', C.board.id, a.id, id, true);
      res = await call('canvas_update_nodes', C.board.id, [{ id: a.id, title: `${icon} ${label}` }]);
    }
    const cur = res && res.board ? res.board.nodes.find(x => x.id === id) : null;
    const roles = { ...((cur || n).roles || {}) };
    added.forEach(a => { roles[a.id] = role; });
    res = await call('canvas_update_nodes', C.board.id, [{ id, roles }]);
    if (!res) return;
    C.board = res.board;
    C.sel = id;
    body().querySelector('.cv-panel')?.remove();
    drawAll();
    drawPanel(true);
    toast(`📎 Đã thêm ${added.length} ảnh ${label.toLowerCase()} vào ${id} — bấm Tạo`, 'ok');
  }

  // 🧍 / 📦 khối Ảnh preset "bảng nhiều góc" — đang chọn 1 ảnh (tải lên / ảnh đã tạo) thì nối ảnh đó vào luôn
  async function addAngles(kind) {
    if (!C.board) return;
    const sel = C.sel && node(C.sel);
    const src = sel && ['image', 'upload'].includes(sel.kind) ? sel : null;
    const at = src ? { x: src.x + 400, y: src.y } : {};
    await addAt('image', { ...at, inputs: src ? [src.id] : [] });
    const id = C.sel;
    if (!id || (src && id === src.id)) return;
    const title = kind === 'character' ? '🧍 Góc nhân vật' : '📦 Góc sản phẩm';
    const res = await call('canvas_update_nodes', C.board.id, [{ id, angles: kind, title, aspect: '16:9' }]);
    if (res) { C.board = res.board; body().querySelector('.cv-panel')?.remove(); drawAll(); drawPanel(true); }
    toast(src ? `${title}: đã nối ảnh ${src.id} — bấm Tạo` : `${title}: nối ảnh ${kind === 'character' ? 'người mẫu' : 'sản phẩm'} vào rồi bấm Tạo`, 'ok');
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

  async function act(what, id, btn) {
    const n = node(id);
    if (!n) return;
    const bid = C.board.id;
    if (what === 'run-menu') {
      return popMenu(btn, [['to', '▶ Chạy đến khối này', 'Các khối phía trước còn thiếu / đã đổi + khối này'],
        ['from', '⏩ Chạy từ khối này trở đi', 'Khối này + mọi khối phía sau']], k => runFlow(k, id, false));
    }
    if (what === 'lock') {
      const res = await call('canvas_lock', bid, id, !n.locked);
      if (res) {
        C.board = res.result.board;
        drawAll();
        toast(n.locked ? `🔓 Đã mở khoá ${id}` : `🔒 Đã khoá ${id} — chạy quy trình sẽ giữ nguyên kết quả này`, 'ok');
      }
      return;
    }
    if (what === 'versions') return versionsMenu(n, btn);
    if (what === 'convert') return convertMenu(n, btn);
    if (what === 'log') {
      const res = await call('canvas_log', bid, 'node', id);
      if (res) logDialog(`📜 Nhật ký lần chạy gần nhất · ${id}${n.title ? ` · ${n.title}` : ''}`, res.entries);
      return;
    }
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
    if (what === 'del') {  // hoàn tác được (↶ / Ctrl+Z trả lại khối cùng kết quả) → chỉ hỏi lại khi khối đang khoá / đang chạy
      if (n.locked && !confirm(`Khối ${id} đang 🔒 khoá — vẫn xoá?`)) return;
      if (isBusy(n) && !confirm(`Khối ${id} đang chạy — dừng và xoá?`)) return;
      const res = await call('canvas_delete_node', bid, id);
      if (res) { C.board = res.board; C.sel = ''; drawAll(); toast(`Đã xoá ${id} — bấm ↶ hoặc Ctrl+Z để hoàn tác`, 'ok'); }
    }
  }

  // khoá được: khối đã có kết quả và có tạo nội dung bằng model (không phải khối nhập / đăng bài / kết quả)
  const canLock = n => n.status === 'done' && n.kind !== 'upload' && !['input_text', 'input_video', 'fb_post', 'fb_schedule', 'fb_ad', 'output'].includes(n.wtype);

  /** 🔁 Đổi khối: chọn loại mới — đổi tại chỗ (giữ mã, vị trí, tên, chữ, dây nối hợp kiểu); kết quả cũ bỏ, ↶ hoàn tác được. */
  function convertMenu(n, anchorEl) {
    const menu = body().querySelector('.cv-menu');
    const stage = body().querySelector('.cv-stage');
    if (!menu || !stage) return;
    if (!menu.classList.contains('hidden') && C.menuFor === `conv:${n.id}`) { hideMenu(); return; }
    C.menuFor = `conv:${n.id}`;
    anchorEl.dataset.menuAnchor = '1';
    const cur = n.kind === 'wf' ? `wf:${n.wtype}` : isFlow(n) ? 'flow' : n.kind;
    const types = Object.entries(C.meta.wf_types).filter(([, s]) => s.menu !== 'hidden');
    const item = (key, icon, name, desc) => `<button data-conv="${esc(key)}" type="button" ${key === cur ? 'disabled' : ''}
        title="${esc(desc)}"><i>${esc(icon)}</i><span><b>${esc(name)}${key === cur ? ' · đang dùng' : ''}</b><small>${esc(desc)}</small></span></button>`;
    menu.className = 'cv-menu cv-menu-blocks';
    const media = item('image', KIND_ICON.image, 'Ảnh', 'Tạo ảnh từ prompt / ảnh tham chiếu')
      + item('video', KIND_ICON.video, 'Video', 'Tạo video từ ảnh / prompt')
      + (FLOWSCREEN ? '' : item('flow', '🎥', 'Google Flow', 'Video Veo 8 giây có tiếng trên Google Flow (tài khoản Google, tốn tín dụng Flow)'));
    menu.innerHTML = `<div class="cv-menu-title">🔁 Đổi khối ${esc(n.id)}<small class="muted">giữ mã, vị trí, tên, chữ và dây nối còn hợp — kết quả cũ bỏ (↶ hoàn tác được)</small></div>`
      + Object.entries(GROUP_VI).map(([g, label]) => {  // Ảnh / Video đứng đầu nhóm Tạo nội dung
        const rows = types.filter(([, s]) => s.group === g).map(([k, s]) => item(`wf:${k}`, s.icon, s.name, s.desc)).join('');
        const all = (g === 'create' ? media : '') + rows;
        return all ? `<b>${esc(label)}</b>${all}` : '';
      }).join('');
    menu.classList.remove('hidden');
    const s = stage.getBoundingClientRect(), r = anchorEl.getBoundingClientRect();
    menu.style.left = '0px';
    menu.style.top = '0px';
    menu.style.left = `${Math.max(8, Math.min(s.width - menu.offsetWidth - 8, r.left - s.left))}px`;
    menu.style.top = `${Math.max(8, Math.min(s.height - menu.offsetHeight - 8, r.bottom - s.top + 6))}px`;
    menu.querySelectorAll('[data-conv]:not([disabled])').forEach(b => {
      b.onclick = async () => {
        const key = b.dataset.conv;
        if (n.locked && !confirm(`Khối ${n.id} đang 🔒 khoá — đổi loại sẽ bỏ kết quả đã chốt. Vẫn đổi?`)) return;
        hideMenu();
        const [kind, wtype] = key.startsWith('wf:') ? ['wf', key.slice(3)] : [key, ''];
        const res = await call('canvas_convert', C.board.id, n.id, kind, wtype);
        if (!res) return;
        const r2 = res.result;
        C.board = r2.board;
        C.sel = n.id;
        const panel = body().querySelector('.cv-panel');
        if (panel) panel.remove();  // bảng cấu hình của loại cũ
        drawAll();
        const lost = [...(r2.lost_in || []).map(i => `${i} → ${n.id}`), ...(r2.lost_out || []).map(i => `${n.id} → ${i}`)];
        toast(`🔁 ${n.id}: ${r2.old} → ${r2.name}${r2.kept_text ? ' · giữ chữ' : ''}`
          + (lost.length ? ` · gỡ ${lost.length} dây không hợp (${lost.join(', ')})` : '') + ' — ↶ để hoàn tác', lost.length ? '' : 'ok');
      };
    });
  }

  /** 🕘 Phiên bản: kết quả trước của khối (ảnh / video / chữ) — xem, chọn lại bản cũ (bản đang có được cất vào danh sách). */
  function versionsMenu(n, anchorEl) {
    const menu = body().querySelector('.cv-menu');
    const stage = body().querySelector('.cv-stage');
    if (!menu || !stage) return;
    if (!menu.classList.contains('hidden') && C.menuFor === `vers:${n.id}`) { hideMenu(); return; }
    C.menuFor = `vers:${n.id}`;
    anchorEl.dataset.menuAnchor = '1';
    const video = n.kind === 'video' || (n.out || {}).video;
    const thumb = (urls, pick) => {
      const u = urls[Math.min(pick || 0, Math.max(0, urls.length - 1))];
      if (!u) return '<span class="cv-ver-ph">📝</span>';
      return video ? `<video src="${esc(u)}#t=0.4" muted preload="metadata"></video>` : `<img src="${esc(thumbUrl(u, 200))}" alt="">`;
    };
    const fmt = t => (t ? `${String(t).slice(11, 16)} ${String(t).slice(8, 10)}/${String(t).slice(5, 7)}` : '');
    menu.className = 'cv-menu cv-vers';
    menu.innerHTML = `<div class="cv-menu-title">🕘 Phiên bản · ${esc(n.id)}<small class="muted">chọn lại 1 bản cũ — bản đang dùng được cất vào đây</small></div>
      <div class="cv-ver cur">${thumb(n.urls || [], n.pick)}<div><b>Đang dùng</b><small>${esc(fmt(n.done_at))}</small>
        ${n.made ? `<small class="cv-ver-p" title="${esc(n.made)}">${esc(n.made)}</small>` : ''}${(n.out || {}).text && !video ? `<small class="cv-ver-t">${esc(String(n.out.text).slice(0, 160))}</small>` : ''}</div></div>
      ${(n.vers || []).map((v, i) => `<div class="cv-ver">${thumb(v.urls || [], v.pick)}<div><b>Bản ${i + 1} trước</b><small>${esc(fmt(v.at))}</small>
        ${v.prompt ? `<small class="cv-ver-p" title="${esc(v.prompt)}">${esc(v.prompt)}</small>` : ''}${v.text ? `<small class="cv-ver-t">${esc(v.text.slice(0, 160))}</small>` : ''}
        <button class="btn ghost sm" data-ver="${i}" type="button" ${isBusy(n) ? 'disabled' : ''}>Dùng bản này</button></div></div>`).join('')}`;
    const s = stage.getBoundingClientRect(), r = anchorEl.getBoundingClientRect();
    menu.style.left = '0px';
    menu.style.top = '0px';
    menu.style.left = `${Math.max(8, Math.min(s.width - menu.offsetWidth - 8, r.left - s.left))}px`;
    menu.style.top = `${Math.max(8, Math.min(s.height - menu.offsetHeight - 8, r.bottom - s.top + 6))}px`;
    menu.querySelectorAll('[data-ver]').forEach(b => {
      b.onclick = async () => {
        const res = await call('canvas_restore_version', C.board.id, n.id, Number(b.dataset.ver));
        if (!res) return;
        hideMenu();
        C.board = res.result.board;
        drawAll();
        const after = C.board.nodes.filter(x => (x.inputs || []).includes(n.id)).length;
        toast(`Đã dùng lại phiên bản cũ của ${n.id}${after ? ` — ${after} khối phía sau sẽ chạy lại ở lần chạy tới` : ''}`, 'ok');
      };
    });
  }

  /** 📜 Xem nhật ký đã lưu (lượt chạy / lần chạy gần nhất của khối). */
  function logDialog(title, entries) {
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import';
    const lines = (entries || []).map(e => `<div class="${esc(e.level || '')}"><span>${esc(e.time || '')}</span> ${esc(e.message || '')}</div>`).join('');
    box.innerHTML = `<div class="cv-import-box cv-log-box"><div class="cv-side-head"><b>${esc(title)}</b><button class="btn ghost sm" data-x type="button">✕</button></div>
      <div class="cv-log-lines">${lines || '<div class="muted">Chưa có nhật ký (lượt chạy trước khi có bản cập nhật này không lưu nhật ký).</div>'}</div>
      <div class="row cv-run-foot"><small class="muted">${(entries || []).length} dòng</small><span class="cv-sp"></span>
        <button class="btn ghost sm" data-copy type="button">📋 Sao chép</button><button class="btn primary sm" data-x type="button">Đóng</button></div></div>`;
    const close = () => { document.removeEventListener('keydown', onKey, true); box.remove(); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    box.querySelectorAll('[data-x]').forEach(b => { b.onclick = close; });
    box.onclick = e => { if (e.target === box) close(); };
    box.querySelector('[data-copy]').onclick = async () => {
      try { await navigator.clipboard.writeText((entries || []).map(e => `${e.time || ''} ${e.message || ''}`).join('\n')); toast('Đã sao chép nhật ký', 'ok'); }
      catch (err) { toast('Không sao chép được', 'error'); }
    };
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(box);
    const list = box.querySelector('.cv-log-lines');
    list.scrollTop = list.scrollHeight;
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
      ['wf:ai_text', '✦ AI viết (mô tả ảnh, viết prompt)'], ['wf:storyboard_video', '🧭 Storyboard (ảnh làm tham chiếu)'],
      ['wf:heygen_video', '🧑‍💼 Video HeyGen (người trong ảnh nói)']],
    video: [['wf:post_video', '🎞 Hậu kỳ video (Claude + Remotion)'], ['wf:edit_pro', '✨ Edit Pro (video nói chuyện → Reels sang trọng)'],
      ['vid-ref', '🎬 Video mới dùng video này làm tham chiếu'], ['wf:fb_post', '📣 Đăng / lên lịch bài Facebook'],
      ['wf:concat_video', '⧉ Ghép video'], ['wf:dub_vieneu', '🎙 Lồng tiếng VieNeu']],
    text: [['img-from-text', '🖼 Ảnh từ chữ này (làm prompt)'], ['vid-dialogue', '🎬 Video dùng chữ này làm lời thoại'], ['wf:heygen_video', '🧑‍💼 Video HeyGen (avatar đọc chữ này)'],['wf:ai_text', '✦ AI viết / xử lý tiếp'], ['wf:web_research', '🌐 Tra cứu web về chủ đề này'], ['wf:content_post', '📝 Tạo content bài viết'],
      ['wf:fb_post', '📣 Đăng bài (làm caption)'], ['wf:storyboard_video', '🧭 Storyboard → tách mỗi cảnh 1 node Video'],
      ['wf:whiteboard_video', '✍ Whiteboard']],
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
    menu.className = 'cv-menu';
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
    const groups = GROUP_VI;
    const types = Object.entries(C.meta.wf_types);
    const item = (attrs, icon, name, desc) => `<button ${attrs} title="${esc(desc)}"><i>${esc(icon)}</i><span><b>${esc(name)}</b><small>${esc(desc)}</small></span></button>`;
    menu.className = 'cv-menu cv-menu-blocks';
    // 🎥 nhóm Google Flow (đầu menu): các khối của quy trình Flow — không lặp lại ở nhóm khác
    // 🎬 màn Grok Canvas: cùng nhóm nhưng video = khối Video (Grok Imagine), không có khối Google Flow
    const FLOW_WF = ['product_studio', 'concat_video', 'dub_vieneu', 'post_video'].filter(k => C.meta.wf_types[k]);
    const flowGroup = (FLOWSCREEN ? `<b class="cv-menu-flow">🎬 Grok Video</b>`
      + item('data-blk-node="video"', '🎬', 'Video (Grok)', 'Video Grok Imagine 6 / 10 / 15 giây — nối ảnh khung đầu (nhân vật + sản phẩm), viết chuyển động + lời thoại; lời dài tự tách nhiều video rồi ghép')
      : `<b class="cv-menu-flow">🎥 Google Flow</b>`
      + item('data-blk-node="flow"', '🎥', 'Google Flow', 'Video Veo 8 giây có tiếng trên Google Flow — nối ảnh nhân vật / sản phẩm, viết cảnh + lời thoại; lời dài tự tách nhiều video rồi ghép'))
      + FLOW_WF.slice(0, 1).map(k => item(`data-blk="${k}"`, C.meta.wf_types[k].icon, C.meta.wf_types[k].name, C.meta.wf_types[k].desc)).join('')
      + item('data-blk-node="image"', '🖼', 'Ảnh', 'Tạo ảnh khung đầu / ảnh tham chiếu (📎 đính kèm nhân vật, sản phẩm ngay trong khối)')
      + FLOW_WF.slice(1).map(k => item(`data-blk="${k}"`, C.meta.wf_types[k].icon, C.meta.wf_types[k].name, C.meta.wf_types[k].desc)).join('');
    const adv = types.filter(([k, s]) => s.menu === 'advanced' && !FLOW_WF.includes(k));
    menu.innerHTML = `<div class="cv-menu-title">🧩 Thêm khối<small class="muted">bấm để thêm vào bảng, rồi kéo cổng ＋ để nối</small></div>` + flowGroup + Object.entries(groups).map(([g, label]) => {
      const rows = types.filter(([k, s]) => s.group === g && !s.menu && !FLOW_WF.includes(k));  // khối ẩn / nâng cao / nhóm Flow không lặp lại
      // Ảnh đầu vào = node ⬆ ảnh tải lên của Canvas (chọn được nhiều ảnh, mỗi ảnh 1 node)
      const extra = g === 'input' ? item('data-blk-upload', '🖼', 'Ảnh đầu vào', 'Ảnh sản phẩm, nhân vật, ảnh tham chiếu — chọn nhiều ảnh trên máy') : '';
      return rows.length || extra ? `<b>${esc(label)}</b>${extra}${rows.map(([k, s]) => item(`data-blk="${k}"`, s.icon, s.name, s.desc)).join('')}` : '';
    }).join('') + `<b>Bố cục</b>${item('data-blk-group', '▢', 'Nhóm / ghi chú', 'Khung màu có tên + ghi chú (như sticky note n8n); kéo nhóm thì các node bên trong đi theo. Đang chọn 1 node → bọc quanh node đó; chọn nhiều → bọc cả nhóm')}`
      + (adv.length ? `<button class="cv-menu-more" data-blk-adv type="button">${C.advOpen ? '▾' : '▸'} Khối nâng cao (${adv.length})</button>
        ${C.advOpen ? adv.map(([k, s]) => item(`data-blk="${k}"`, s.icon, s.name, s.desc)).join('') : ''}` : '');
    const stage = body().querySelector('.cv-stage').getBoundingClientRect();
    const r = anchorEl.getBoundingClientRect();
    menu.classList.remove('hidden');
    menu.style.left = `${r.left - stage.left - 40}px`;
    menu.style.top = `${Math.max(8, r.top - stage.top - menu.offsetHeight - 10)}px`;
    menu.querySelectorAll('[data-blk]').forEach(b => { b.onclick = () => { hideMenu(); addAt('wf', { wtype: b.dataset.blk }); }; });
    menu.querySelectorAll('[data-blk-node]').forEach(b => { b.onclick = () => { hideMenu(); addAt(b.dataset.blkNode); }; });
    const up = menu.querySelector('[data-blk-upload]');
    if (up) up.onclick = () => { hideMenu(); addAt('upload', { empty: true }); };
    const more = menu.querySelector('[data-blk-adv]');
    if (more) more.onclick = e => { e.stopPropagation(); C.advOpen = !C.advOpen; showBlocks(anchorEl); };
    menu.querySelector('[data-blk-group]').onclick = () => { hideMenu(); return multi().size > 1 ? multiAct('group') : addGroup(); };
  }

  /* ---------------------------------------------------------------- ⇆ tự sắp xếp theo luồng dây nối */
  const ARR = { gapX: 110, gapY: 50, padX: 30, padTop: 64, padBottom: 36 };

  /** Xếp tầng (trái → phải theo dây nối): items [{id, w, h, y}], edges [[từ, tới]] → {id: {x, y}} tính từ (0, 0).
   *  Cột = bước dài nhất từ khối đầu; trong cột xếp theo vị trí trung bình của khối nối vào (ít dây chéo), căn giữa dọc. */
  function layered(items, edges) {
    const ids = items.map(i => i.id);
    const ins = Object.fromEntries(ids.map(id => [id, []]));
    edges.forEach(([a, b]) => { if (a !== b && ins[b] && ins[a] && !ins[b].includes(a)) ins[b].push(a); });
    const depth = Object.fromEntries(ids.map(id => [id, 0]));
    for (let k = 0; k < ids.length; k++) {  // vòng lặp giới hạn → dây nối vòng không treo
      let changed = false;
      ids.forEach(id => ins[id].forEach(a => { if (depth[a] + 1 > depth[id] && depth[a] + 1 < ids.length) { depth[id] = depth[a] + 1; changed = true; } }));
      if (!changed) break;
    }
    const cols = [];
    items.forEach(it => { (cols[depth[it.id]] = cols[depth[it.id]] || []).push(it); });
    const rank = {};
    const pos = {};
    let x = 0;
    const heights = [];
    cols.forEach((col, c) => {
      if (!col) return;
      const bary = it => (ins[it.id].length ? ins[it.id].reduce((s, a) => s + (rank[a] ?? 0), 0) / ins[it.id].length : Infinity);
      col.sort((p, q) => (c ? bary(p) - bary(q) : 0) || p.y - q.y);
      col.forEach((it, i) => { rank[it.id] = i; });
      heights[c] = col.reduce((s, it) => s + it.h, 0) + ARR.gapY * (col.length - 1);
    });
    const tall = Math.max(0, ...heights.filter(h => h != null));
    cols.forEach((col, c) => {
      if (!col) return;
      let y = (tall - heights[c]) / 2;
      col.forEach(it => { pos[it.id] = { x, y }; y += it.h + ARR.gapY; });
      x += Math.max(...col.map(it => it.w)) + ARR.gapX;
    });
    return pos;
  }

  async function arrange() {
    const b = C.board;
    if (!b || !b.nodes.length) return;
    if (b.nodes.some(isBusy) && !confirm('Có khối đang chạy — vẫn sắp xếp lại vị trí?')) return;
    const edges = b.nodes.flatMap(n => (n.inputs || []).map(i => [i, n.id]));
    // mỗi node thuộc nhóm nhỏ nhất chứa nó; nhóm = 1 đơn vị (các khối bên trong xếp riêng rồi bọc khung vừa khít)
    const gs = groups().slice().sort((p, q) => p.w * p.h - q.w * q.h);
    const owner = {};
    b.nodes.forEach(n => { const g = gs.find(x => inGroup(x, n)); if (g) owner[n.id] = g.id; });
    const units = [];
    const unitOf = {};
    const inner = {};
    gs.forEach(g => {
      const ms = b.nodes.filter(n => owner[n.id] === g.id);
      if (!ms.length) { units.push({ id: `g:${g.id}`, w: g.w, h: g.h, y: g.y }); return; }  // nhóm chỉ ghi chú: giữ cỡ
      const rel = layered(ms.map(n => ({ id: n.id, ...sizeOf(n), y: n.y })), edges);
      inner[g.id] = rel;
      const w = Math.max(...ms.map(n => rel[n.id].x + sizeOf(n).w)) + 2 * ARR.padX;
      const h = Math.max(...ms.map(n => rel[n.id].y + sizeOf(n).h)) + ARR.padTop + ARR.padBottom;
      units.push({ id: `g:${g.id}`, w, h, y: g.y });
      ms.forEach(n => { unitOf[n.id] = `g:${g.id}`; });
    });
    b.nodes.filter(n => !owner[n.id]).forEach(n => { units.push({ id: n.id, ...sizeOf(n), y: n.y }); unitOf[n.id] = n.id; });
    const pos = layered(units, edges.map(([a, c]) => [unitOf[a], unitOf[c]]));
    // gốc: góc trên-trái hiện tại của cả bảng (không nhảy đi chỗ khác)
    const ox = Math.min(...b.nodes.map(n => n.x), ...gs.map(g => g.x));
    const oy = Math.min(...b.nodes.map(n => n.y), ...gs.map(g => g.y));
    C.undoArrange = { nodes: b.nodes.map(n => ({ id: n.id, x: n.x, y: n.y })), groups: gs.map(g => ({ id: g.id, x: g.x, y: g.y, w: g.w, h: g.h })) };
    const gpatch = [];
    units.forEach(u => {
      const p = pos[u.id];
      const x = Math.round(ox + p.x), y = Math.round(oy + p.y);
      if (!u.id.startsWith('g:')) { const n = node(u.id); n.x = x; n.y = y; return; }
      const g = group(u.id.slice(2));
      Object.assign(g, { x, y, w: Math.round(u.w), h: Math.round(u.h) });
      const moves = [];
      Object.entries(inner[g.id] || {}).forEach(([id, r]) => {
        const n = node(id);
        n.x = Math.round(x + ARR.padX + r.x);
        n.y = Math.round(y + ARR.padTop + r.y);
        moves.push({ id, x: n.x, y: n.y });
      });
      gpatch.push([g.id, { x: g.x, y: g.y, w: g.w, h: g.h }, moves]);
    });
    await saveLayout(b.nodes.filter(n => !owner[n.id]), gpatch);
    drawAll();
    fitView();
    armUndo();
    toast('Đã sắp xếp các khối — bấm “↶ Hoàn tác” trong 15 giây nếu muốn trở lại', 'ok');
  }

  async function saveLayout(loose, gpatch) {
    const bid = C.board.id;
    if (loose.length) await call('canvas_update_nodes', bid, loose.map(n => ({ id: n.id, x: n.x, y: n.y })));
    for (const [gid, patch, moves] of gpatch) {
      const res = await call('canvas_update_group', bid, gid, patch, moves);
      if (res && C.board && C.board.id === bid) C.board.groups = res.board.groups;
    }
  }

  function armUndo() {
    const btn = body().querySelector('[data-arrange]');
    if (btn) btn.innerHTML = '↶<small>Hoàn tác</small>';
    clearTimeout(C.undoT);
    C.undoT = setTimeout(() => {
      C.undoArrange = null;
      const b2 = body().querySelector('[data-arrange]');
      if (b2) b2.innerHTML = '⇆<small>Sắp xếp</small>';
    }, 15000);
  }

  async function undoArrange() {
    const u = C.undoArrange;
    C.undoArrange = null;
    clearTimeout(C.undoT);
    const btn = body().querySelector('[data-arrange]');
    if (btn) btn.innerHTML = '⇆<small>Sắp xếp</small>';
    if (!u || !C.board) return;
    u.nodes.forEach(p => { const n = node(p.id); if (n) { n.x = p.x; n.y = p.y; } });
    const gpatch = u.groups.filter(p => group(p.id)).map(p => { Object.assign(group(p.id), p); return [p.id, { x: p.x, y: p.y, w: p.w, h: p.h }, []]; });
    await saveLayout(C.board.nodes, gpatch);
    drawAll();
    toast('Đã trả lại vị trí cũ', 'ok');
  }
  const hideMenu = () => { const m = body().querySelector('.cv-menu'); if (m) m.classList.add('hidden'); };
  /** Menu (Khối / Tạo tiếp) đóng khi bấm bất kỳ đâu ngoài menu (kể cả thanh bên) hoặc nhấn Esc — gắn 1 lần cho cả trang. */
  function bindMenuClose() {
    if (C.menuBound) return;
    C.menuBound = true;
    const open = () => { const m = body() && body().querySelector('.cv-menu'); return m && !m.classList.contains('hidden') ? m : null; };
    document.addEventListener('pointerdown', e => {
      const m = open();
      if (m && !e.target.closest('.cv-menu') && !e.target.closest('[data-blocks], [data-menu-anchor]')) hideMenu();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && open()) hideMenu();
      // ↶ Ctrl+Z / ↷ Ctrl+Y (Ctrl+Shift+Z) khi đang ở Canvas mà không gõ chữ trong ô nhập (ô nhập tự hoàn tác chữ)
      const page = document.querySelector(CFG.page);
      if (!C.board || !page || page.classList.contains('hidden') || !(e.ctrlKey || e.metaKey)) return;
      if (e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"], .cv-assist')) return;
      if (document.querySelector('.cv-lightbox')) return;  // đang mở hộp thoại
      const k = e.key.toLowerCase();
      if (k === 'z' && !e.shiftKey) { e.preventDefault(); undoStep(false); }
      else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); undoStep(true); }
    });
  }

  /** Menu nhỏ thả xuống từ 1 nút (▾ Chạy, ▶ Chạy ▾ của khối…): items = [[key, nhãn, mô tả]]. Bấm lại nút = đóng. */
  function popMenu(anchorEl, items, onPick) {
    const menu = body().querySelector('.cv-menu');
    const stage = body().querySelector('.cv-stage');
    if (!menu || !stage) return;
    const id = anchorEl.dataset.cv || anchorEl.dataset.act || '';
    if (!menu.classList.contains('hidden') && C.menuFor === id) { hideMenu(); return; }
    anchorEl.dataset.menuAnchor = '1';
    C.menuFor = id;
    menu.className = 'cv-menu cv-menu-pop';
    menu.innerHTML = items.map(([k, label, desc]) => `<button data-pop="${esc(k)}" type="button"><b>${esc(label)}</b>${desc ? `<small>${esc(desc)}</small>` : ''}</button>`).join('');
    const s = stage.getBoundingClientRect(), r = anchorEl.getBoundingClientRect();
    menu.style.left = '0px';
    menu.style.top = '0px';
    const w = menu.offsetWidth;
    menu.style.left = `${Math.max(8, Math.min(s.width - w - 8, r.right - s.left - w))}px`;
    menu.style.top = `${Math.max(8, r.bottom - s.top + 6)}px`;
    menu.querySelectorAll('[data-pop]').forEach(b => { b.onclick = () => { hideMenu(); onPick(b.dataset.pop); }; });
  }

  /** Nút ↶ ↷ trên thanh trên: tên bước sẽ hoàn tác / làm lại (lấy từ bảng mỗi lần sửa). */
  function drawUndo() {
    const u = (C.board && C.board.undo) || {};
    const root = body();
    if (!root) return;
    const ub = root.querySelector('[data-cv="undo"]'), rb = root.querySelector('[data-cv="redo"]');
    if (!ub || !rb) return;
    ub.disabled = !u.undo;
    rb.disabled = !u.redo;
    ub.title = u.undo ? `Hoàn tác: ${u.undo} (Ctrl+Z)` : 'Chưa có thao tác nào để hoàn tác (Ctrl+Z)';
    rb.title = u.redo ? `Làm lại: ${u.redo} (Ctrl+Y)` : 'Không có thao tác nào để làm lại (Ctrl+Y)';
  }

  async function undoStep(redo) {
    if (!C.board) return;
    if (!redo) await savePanelNow();  // đang gõ dở: lưu trước, để bước hoàn tác tính cả chữ vừa gõ
    const u = C.board.undo || {};
    if (!(redo ? u.redo : u.undo)) { toast(redo ? 'Không có thao tác nào để làm lại' : 'Chưa có thao tác nào để hoàn tác'); return; }
    const res = await call(redo ? 'canvas_redo' : 'canvas_undo', C.board.id);
    if (!res) return;
    C.board = res.result.board;
    if (C.sel && !node(C.sel)) C.sel = '';
    C.multi = new Set([...multi()].filter(id => node(id)));
    const panel = body().querySelector('.cv-panel');
    if (panel) panel.remove();  // ô cấu hình dựng lại theo prompt / cấu hình vừa trả lại
    drawAll();
    toast(`${redo ? '↷ Đã làm lại' : '↶ Đã hoàn tác'}: ${res.result.label}`, 'ok');
  }

  /* ---------------------------------------------------------------- kéo, nối, zoom */
  function applyView() {
    const root = body();
    const world = root.querySelector('.cv-world');
    if (!world) return;
    const { x, y, k } = C.view;
    world.style.transform = `translate(${x}px, ${y}px) scale(${k})`;
    const stage = root.querySelector('.cv-stage');
    stage.style.backgroundPosition = `${x}px ${y}px, 0 0`;  // lớp 1: lưới chấm theo zoom / kéo; lớp 2: ánh sáng nền cố định
    stage.style.backgroundSize = `${22 * k}px ${22 * k}px, 100% 100%`;
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
      if ((e.key === 'a' || e.key === 'A') && (e.ctrlKey || e.metaKey)) { e.preventDefault(); return setMulti(C.board.nodes.map(n => n.id)); }
      if ((e.key === 'Delete' || e.key === 'Backspace') && multi().size > 1) return multiAct('del');
      if (e.key === 'Escape' && multi().size) setMulti([]);
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
      if (nodeEl && (e.ctrlKey || e.metaKey || e.shiftKey)) { stage.focus(); return toggleMulti(nodeEl.dataset.node); }
      if (nodeEl && multi().has(nodeEl.dataset.node) && multi().size > 1) return dragMulti(e, nodeEl.dataset.node);
      if (nodeEl) return dragNode(e, nodeEl.dataset.node);
      const groupEl = e.target.closest('.cv-group');
      if (groupEl && !e.shiftKey && !C.selMode) return groupPointer(e, groupEl.dataset.group);
      if (e.shiftKey || e.ctrlKey || e.metaKey || C.selMode) { stage.focus(); selectNode(''); return marquee(e); }
      stage.focus();
      if (multi().size) setMulti([]);
      selectNode('');
      const start = { x: e.clientX, y: e.clientY, vx: C.view.x, vy: C.view.y };
      stage.classList.add('panning');
      const move = ev => { C.view.x = start.vx + ev.clientX - start.x; C.view.y = start.vy + ev.clientY - start.y; applyView(); };
      const up = () => { stage.classList.remove('panning'); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    };
  }

  /* ---------------------------------------------------------------- chọn nhiều khối (quét chọn / Ctrl + bấm) */
  const multi = () => C.multi || (C.multi = new Set());
  const sizeOf = n => { const el = body().querySelector(`[data-node="${n.id}"]`); return { w: el ? el.offsetWidth : 240, h: el ? el.offsetHeight : 300 }; };

  function setMulti(ids) {
    const list = [...new Set(ids)].filter(id => node(id));
    if (list.length === 1) { C.multi = new Set(); paintMulti(); return selectNode(list[0]); }
    C.multi = new Set(list);
    if (C.sel) selectNode('');
    paintMulti();
  }

  function toggleMulti(id) {  // Ctrl / Shift + bấm khối: thêm / bớt (khối đang chọn đơn cũng tính vào)
    const m = new Set([...multi(), ...(C.sel ? [C.sel] : [])]);
    if (m.has(id)) m.delete(id); else m.add(id);
    setMulti([...m]);
  }

  function paintMulti() {
    const m = multi();
    body().querySelectorAll('.cv-node').forEach(el => el.classList.toggle('msel', m.has(el.dataset.node)));
    drawPanel();
  }

  function multiBox() {
    const b = { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity };
    multi().forEach(id => {
      const n = node(id);
      if (!n) return;
      const s = sizeOf(n);
      b.x1 = Math.min(b.x1, n.x); b.y1 = Math.min(b.y1, n.y); b.x2 = Math.max(b.x2, n.x + s.w); b.y2 = Math.max(b.y2, n.y + s.h);
    });
    return b;
  }

  function drawMultiTools() {
    const tools = body().querySelector('.cv-tools');
    if (!tools) return;
    const ids = [...multi()];
    const busy = ids.some(id => isBusy(node(id)));
    tools.innerHTML = `<span class="cv-tools-count">☑ ${ids.length} khối</span>
      <button data-m="dup" title="Nhân bản cả nhóm — dây nối giữa các khối đã chọn chuyển sang bản sao">⧉ Nhân bản</button>
      <button data-m="group" title="Bọc các khối đã chọn vào 1 Nhóm / ghi chú">▢ Gom nhóm</button>
      <button data-m="clear" title="Bỏ chọn (Esc)">✕ Bỏ chọn</button>
      <button data-m="del" class="danger" title="Xoá các khối đã chọn (phím Delete)" ${busy ? 'disabled' : ''}>🗑 Xoá</button>`;
    tools.classList.remove('hidden');
    tools.querySelectorAll('[data-m]').forEach(b => { b.onclick = () => multiAct(b.dataset.m); });
    placeTools();
  }

  async function multiAct(what) {
    const ids = [...multi()].filter(id => node(id));
    if (!ids.length || !C.board) return;
    if (what === 'clear') return setMulti([]);
    if (what === 'group') {
      const b = multiBox();
      await addGroup({ x: b.x1 - 30, y: b.y1 - 64, w: b.x2 - b.x1 + 60, h: b.y2 - b.y1 + 100, title: `Nhóm ${ids.length} khối` });
      return setMulti([]);
    }
    if (what === 'dup') {
      const res = await call('canvas_duplicate_nodes', C.board.id, ids);
      if (!res) return;
      C.board = res.result.board;
      C.multi = new Set(res.result.nodes);  // chọn luôn các bản sao để kéo đi chỗ khác
      drawAll();
      paintMulti();
      return toast(`Đã nhân bản ${res.result.nodes.length} khối — kéo để đặt chỗ khác`, 'ok');
    }
    if (what === 'del') {
      if (ids.some(id => isBusy(node(id)))) return toast('Có khối đang chạy — dừng trước khi xoá', 'warn');
      const withFiles = ids.filter(id => (node(id).urls || []).length || (node(id).out || {}).text).length;
      const locked = ids.filter(id => node(id).locked).length;
      if (!confirm(`Xoá ${ids.length} khối đã chọn${withFiles ? ` (${withFiles} khối đã có kết quả)` : ''}${locked ? ` — có ${locked} khối đang 🔒 khoá` : ''}?\n\nHoàn tác được bằng ↶ / Ctrl+Z.`)) return;
      const res = await call('canvas_delete_nodes', C.board.id, ids);
      if (!res) return;
      C.board = res.board;
      C.multi = new Set();
      drawAll();
      toast(`Đã xoá ${ids.length} khối — bấm ↶ hoặc Ctrl+Z để hoàn tác`, 'ok');
    }
  }

  function dragMulti(e, id) {  // kéo 1 khối trong nhóm đang chọn → cả nhóm đi theo; bấm không kéo → chọn riêng khối đó
    const start = { x: e.clientX, y: e.clientY };
    const items = [...multi()].map(node).filter(Boolean).map(n => ({ n, x: n.x, y: n.y, el: body().querySelector(`[data-node="${n.id}"]`) }));
    let moved = false;
    const move = ev => {
      const dx = (ev.clientX - start.x) / C.view.k, dy = (ev.clientY - start.y) / C.view.k;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      items.forEach(it => {
        it.n.x = Math.round(it.x + dx);
        it.n.y = Math.round(it.y + dy);
        if (it.el) { it.el.style.left = `${it.n.x}px`; it.el.style.top = `${it.n.y}px`; }
      });
      drawEdges();
      placeTools();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) {
        call('canvas_update_nodes', C.board.id, items.map(it => ({ id: it.n.id, x: it.n.x, y: it.n.y })));
        if (groups().length) drawGroups();
      } else setMulti([id]);
      body().querySelector('.cv-stage').focus({ preventScroll: true });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
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

  function droppedHtml(m) {
    if (!m.dropped) return '';
    const why = (m.dropped_why || []).join(' · ');
    return `<small class="muted" ${why ? `title="${esc(why)}"` : ''}>Bỏ ${m.dropped} đề xuất không hợp lệ${why ? `: ${esc(why)}` : ''}</small>`;
  }

  function builtHtml(m) {
    if (!m.built) return '';
    const b = m.built;
    return `<div class="cv-as-built ${b.errors.length ? 'warn' : 'ok'}">🧩 Đã dựng ${b.done} thao tác lên Canvas${b.errors.length
      ? ` · ${b.errors.length} lỗi<ul>${b.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ' — kiểm tra rồi bấm ▶ Chạy toàn bộ'}</div>`;
  }

  function opsHtml(m) {
    const ops = m.ops || [];
    if (!ops.length) return droppedHtml(m);
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
      ${droppedHtml(m)}</div>`;
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
        ? `<div class="cv-as-msg user${m.auto ? ' auto' : ''}">${esc(m.text)}${m.images ? `<small>📎 kèm ${m.images} ảnh kết quả</small>` : ''}${(m.files || []).length ? `<small>📄 ${esc(m.files.join(', '))}</small>` : ''}${m.mcp ? '<small>🔌 cho đọc dữ liệu qua MCP</small>' : ''}</div>`
        : m.error ? `<div class="cv-as-msg err">⚠ ${esc(m.error)}</div>`
          : `<div class="cv-as-msg bot">${autoTag(m)}${m.text ? noteHtml(m.text) : ''}${(m.mcp_reads || []).length ? `<small class="cv-as-reads">🔌 Đã đọc: ${m.mcp_reads.map(r => `${r.ok ? '✓' : '✗'} ${esc(r.server)} · ${esc(r.tool)}`).join(' · ')}</small>` : ''}${evalHtml(m.eval)}${reworkHtml(m)}${builtHtml(m)}${opsHtml(m)}</div>`)).join('')
        : `<div class="cv-as-intro"><b>Claude đọc toàn bộ Canvas này</b> (khối, prompt, kết quả, lỗi) và có thể xem ảnh kết quả để:
            <ul><li>chấm điểm, chỉ lỗi từng node</li><li>đề xuất sửa prompt / model / thêm & nối khối</li><li>gợi ý bước tiếp theo</li></ul>
            Đề xuất chỉ thay đổi Canvas khi bạn bấm <b>Áp dụng</b>; chạy luôn hỏi xác nhận. Dùng tài khoản claude.ai đã đăng nhập trong app.</div>`}</div>
      <div class="cv-as-status ${C.assist.sending ? '' : 'hidden'}"><span class="cv-spin"></span><span class="cv-as-status-text">${esc(C.assist.status || 'Đang hỏi Claude…')}</span></div>
      <div class="cv-as-quick">${AS_QUICK.map(([l, t], i) => `<button type="button" data-as-q="${i}" title="${esc(t)}">${esc(l)}</button>`).join('')}</div>
      <div class="cv-as-input"><textarea data-as-text rows="3" placeholder="Hỏi trợ lý… (VD: Ảnh n3 có hợp quảng cáo TikTok không? Viết lại prompt cho đẹp hơn)"></textarea>
        <div class="cv-as-files">${(C.assist.files || []).map((f, i) => `<span class="cv-as-file" title="${esc(f.path)}">📄 ${esc(f.name)}<button type="button" data-as-unfile="${i}" title="Bỏ file này">✕</button></span>`).join('')}
          <button class="link-btn" type="button" data-as-files title="Ảnh (gửi kèm để Claude xem), video .mp4 .mov .webm (gửi ảnh lưới khung hình có mốc giây) hoặc tài liệu .txt .md .csv .json .docx .srt .vtt (đọc thành chữ) — tối đa 8 file">📎 Đính kèm file</button></div>
        <div class="cv-as-row"><label class="cv-opt-check" title="Gửi ảnh kết quả + 1 khung hình mỗi video (tối đa 6) để Claude xem và chấm"><input type="checkbox" data-as-attach ${C.assist.attach === false ? '' : 'checked'}> 📎 Kèm ảnh kết quả</label>
          <label class="cv-opt-check" title="Bật: Claude DỰNG THẬT lên Canvas — thêm khối, viết prompt, chọn model, nối dây ngay (không cần bấm Áp dụng). Không tự chạy."><input type="checkbox" data-as-build ${C.assist.build ? 'checked' : ''}> 🧩 Dựng thật lên Canvas</label>
          <label class="cv-opt-check" title="Claude đọc dữ liệu qua (1) các kết nối ở màn 🔌 Kết nối MCP của app (chỉ công cụ bạn cho phép, app gọi giúp) và (2) connector MCP trên claude.ai (Drive / Sheets, Canva…) — CHỈ ĐỌC, không tạo / sửa / xoá gì. Connector claude.ai lần đầu có thể hỏi cho phép: bật 🖥 Trình duyệt: hiện để bấm."><input type="checkbox" data-as-mcp ${state.boot.settings.assist_mcp ? 'checked' : ''}> 🔌 Đọc dữ liệu qua MCP</label>
          <button class="link-btn cv-as-browser" type="button" data-as-browser title="Hiện / ẩn cửa sổ trình duyệt dùng chung cho cả app — đổi ở Cài đặt → Trình duyệt">🖥 Trình duyệt: ${state.boot.settings.show_browser ? 'hiện' : 'ẩn'}</button>
          <span class="cv-sp"></span><button class="btn primary sm" type="button" data-as="send" ${C.assist.sending ? 'disabled' : ''}>${C.assist.sending ? 'Đang chờ…' : 'Gửi ➤'}</button></div>
        <input class="cv-as-mcp-note ${state.boot.settings.assist_mcp ? '' : 'hidden'}" data-as-mcp-note maxlength="400" placeholder="🔌 Nguồn dữ liệu cho Claude đọc (tuỳ chọn) — VD: Drive thư mục “Sản phẩm”, bảng giá trên Google Sheets" value="${esc(state.boot.settings.assist_mcp_note || '')}"></div>`;
    const mcpBox = box.querySelector('[data-as-mcp]'), mcpNote = box.querySelector('[data-as-mcp-note]');
    mcpBox.onchange = () => { state.boot.settings.assist_mcp = mcpBox.checked; mcpNote.classList.toggle('hidden', !mcpBox.checked); };
    mcpNote.onkeydown = e => e.stopPropagation();
    mcpNote.oninput = () => { state.boot.settings.assist_mcp_note = mcpNote.value; };
    const ta = box.querySelector('[data-as-text]');
    ta.value = draft;
    ta.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendAssist(); };
    const buildBox = box.querySelector('[data-as-build]');
    buildBox.onchange = () => { C.assist.build = buildBox.checked; C.assist.buildSet = true; };
    ta.oninput = () => {  // gõ "dựng …" → tự bật Dựng thật (trừ khi bạn đã tự bật / tắt ô này)
      if (C.assist.buildSet) return;
      C.assist.build = /dựng/i.test(ta.value);
      buildBox.checked = C.assist.build;
    };
    box.querySelector('[data-as-attach]').onchange = e => { C.assist.attach = e.target.checked; };
    box.querySelector('[data-as-files]').onclick = async () => {
      const res = await call('canvas_assist_pick_files');
      if (!res || !res.files.length) return;
      const have = new Set((C.assist.files || []).map(f => f.path));
      C.assist.files = [...(C.assist.files || []), ...res.files.filter(f => !have.has(f.path))].slice(0, 8);
      drawAssist();
    };
    box.querySelectorAll('[data-as-unfile]').forEach(b => {
      b.onclick = () => { C.assist.files.splice(+b.dataset.asUnfile, 1); drawAssist(); };
    });
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
        if (text.endsWith(': ')) {
          if (/^Dựng/.test(text)) { C.assist.build = true; C.assist.buildSet = true; buildBox.checked = true; }
          ta.value = text; ta.focus(); ta.setSelectionRange(text.length, text.length); return;
        }
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
    const build = !!C.assist.build;  // khoá Admin: call() tự hỏi mật khẩu khi backend báo locked
    C.assist.sending = true;
    C.assist.status = build ? 'Đang nhờ Claude dựng quy trình…' : 'Đang hỏi Claude…';
    C.assist.chat = C.assist.chat || { messages: [] };
    const files = C.assist.files || [];
    C.assist.chat.messages = [...C.assist.chat.messages, { role: 'user', text: build ? `🧩 ${text}` : text, images: 0,
      files: files.map(f => f.name) }];
    C.assist.files = [];
    ta.value = '';
    C.assist.build = false;  // mỗi lượt dựng bật lại (tránh lượt hỏi sau vô tình sửa Canvas)
    C.assist.buildSet = false;
    drawAssist(true);
    const st = state.boot.settings;
    const res = await call('canvas_assist_send', bid, text, C.assist.attach !== false, false, build, files.map(f => f.path),
      !!st.assist_mcp, st.assist_mcp_note || '');
    if (!C.board || C.board.id !== bid) return;  // đã rời Canvas này trong lúc chờ
    C.assist.sending = false;
    if (res) C.assist.chat = res.chat;
    else { const again = await call('canvas_assist_get', bid); if (again) C.assist.chat = again.chat; }
    if (build) {  // khối Claude vừa dựng → vẽ lại bảng
      const opened = await call('canvas_open', bid);
      if (opened && C.board && C.board.id === bid) { C.board = opened.board; drawAll(); }
    }
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
    const isAdd = o => o.op === 'add_node' || o.op === 'add_frame';  // tạo khối (khung video / khối mới) trước rồi mới nối
    const order = [...m.ops.keys()].sort((a, b) => isAdd(m.ops[b]) - isAdd(m.ops[a]) || a - b);
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

  /** Lưu ngay prompt / lời thoại / cấu hình đang gõ dở ở ô đang mở (trước khi chạy, trước khi hoàn tác). */
  async function savePanelNow() {
    clearTimeout(C.promptT);
    const panel = body().querySelector('.cv-panel');
    if (!C.board || !panel || !node(panel.dataset.for)) return;
    const n = node(panel.dataset.for);
    const ta = panel.querySelector('textarea:not([data-c]):not([data-out])');
    clearTimeout(C.dlgT);
    const dlg = panel.querySelector('[data-dlg]');
    const patch = { id: n.id, ...(n.kind === 'wf' ? { config: n.config || {} } : { prompt: ta && !ta.readOnly ? ta.value : n.prompt }),
      ...typedDialogue(dlg) };
    await call('canvas_update_nodes', C.board.id, [patch]);
  }

  async function runFlow(mode, target, fresh, asked) {
    if (!C.board) return;
    await savePanelNow();
    if (FLOWSCREEN && mode === 'all') {  // 🎬 Grok Canvas: luôn chạy toàn bộ
      // flow → tạo 1 tác vụ rồi sang màn Tác vụ; bảng của 1 tác vụ → chạy ngay trên bảng đó
      return C.board.task_of ? runAllDirect(C.board.id, asked) : runAsTask(C.board.id, false);
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
    if (!plan.run.length && !plan.issues.some(i => i.level === 'error')) {
      toast(`Mọi khối đã có kết quả mới nhất — không cần chạy${plan.held.length ? ` (🔒 ${plan.held.length} khối đang khoá)` : ''}. Muốn tạo lại: ▾ → ⟳ Làm lại tất cả`);
      return;
    }
    const run = await runDialog(C.board.id, mode, target, fresh, plan, {
      onGo: id => { focusNode(id); showIssues(plan.issues); } });
    if (!run) return;
    C.board = run.board;
    C.issues = {};
    drawAll();
    const rec = runs()[runs().length - 1];
    toast(`Đang chạy ${rec ? Object.keys(rec.nodes || {}).length : ''} khối…`);
  }

  /** 🎬 Grok Canvas: ▶ Chạy toàn bộ = chạy thẳng MỌI khối, làm lại từ đầu — không có bảng chọn khối / xem trước.
   *  Vẫn hỏi các khối “❓ Hỏi khi chạy”; còn lỗi (khối không “✏ Không bắt buộc nhập”) → liệt kê lỗi, không chạy. */
  async function runAllDirect(bid, asked, fromList = false) {
    let res = await call('canvas_preview', bid, 'all', '', true);
    if (!res) return null;
    let plan = res.plan;
    if (!asked && (plan.ask || []).length) {
      let ok = false;
      if (fromList) {
        const opened = await call('canvas_open', bid);
        if (!opened) return null;
        const prev = C.board;
        C.board = opened.board;
        try { ok = await askInputs(plan.ask, { fromList: true }); } finally { C.board = prev; }
      } else {
        ok = await askInputs(plan.ask);
      }
      if (!ok) return null;
      res = await call('canvas_preview', bid, 'all', '', true);
      if (!res) return null;
      plan = res.plan;
    }
    const errors = plan.issues.filter(i => i.level === 'error');
    if (errors.length) {
      if (fromList && (await openBoard(bid)) === false) return null;
      C.issues = Object.fromEntries(plan.issues.map(i => [i.node, i]));
      drawAll();
      showIssues(plan.issues);
      toast(`Còn ${errors.length} lỗi cần sửa trước khi chạy (hoặc bật “✏ Không bắt buộc nhập” cho khối đó)`, 'error');
      return null;
    }
    const run = await call('canvas_run_flow', bid, 'all', '', true, []);
    if (!run) return null;
    const rec = ((run.board || {}).runs || []).slice(-1)[0];
    const total = rec ? Object.keys(rec.nodes || {}).length : plan.run.length;
    if (!fromList && C.board && C.board.id === bid) {
      C.board = run.board;
      C.issues = {};
      drawAll();
    }
    toast(`▶ Đang chạy toàn bộ ${total} khối…`, 'ok');
    return { run, total };
  }

  /** 🎬 Grok Canvas: ▶ Chạy (thẻ flow / trong bảng) = tạo 1 TÁC VỤ chạy toàn bộ flow rồi tự sang màn 📋 Tác vụ.
   *  Hỏi các khối “❓ Hỏi khi chạy” trước (giá trị nhập thành đầu vào của tác vụ); còn lỗi → liệt kê lỗi, không tạo. */
  async function runAsTask(bid, fromList) {
    let res = await call('canvas_preview', bid, 'all', '', true);
    if (!res) return null;
    let plan = res.plan;
    const opened = await call('canvas_open', bid);
    if (!opened) return null;
    const prev = C.board;
    if (fromList) C.board = opened.board;
    try {
      if ((plan.ask || []).length && !(await askInputs(plan.ask, { fromList }))) return null;
      res = await call('canvas_preview', bid, 'all', '', true);
      if (!res) return null;
      plan = res.plan;
      const errors = plan.issues.filter(i => i.level === 'error');
      if (errors.length) {
        if (fromList) { C.board = prev; if ((await openBoard(bid)) === false) return null; }
        C.issues = Object.fromEntries(plan.issues.map(i => [i.node, i]));
        drawAll();
        showIssues(plan.issues);
        toast(`Còn ${errors.length} lỗi cần sửa trước khi chạy (hoặc bật “✏ Không bắt buộc nhập” cho khối đó)`, 'error');
        return null;
      }
      // đầu vào của tác vụ = giá trị các ô “❓ Hỏi khi chạy” vừa nhập (tên tác vụ lấy từ ô chữ đầu tiên)
      const flow = (await call('canvas_open', bid) || {}).board || opened.board;
      const inputs = {};
      flow.nodes.filter(n => n.ask && n.kind !== 'upload').forEach(n => {
        if (n.kind === 'wf') {
          const keys = wspec(n).fields.filter(f => ASK_TYPES.includes(f.type) && f.key !== 'ask' && askOn(n, f.key)).map(f => f.key);
          const config = Object.fromEntries(keys.filter(k => k in (n.config || {})).map(k => [k, n.config[k]]));
          if (Object.keys(config).length) inputs[n.id] = { config };
        } else {
          inputs[n.id] = { ...(askOn(n, 'prompt') ? { prompt: n.prompt || '' } : {}),
            ...(n.kind === 'video' && askOn(n, 'dialogue') && !n.dialogue_src ? { dialogue: n.dialogue || '' } : {}) };
        }
      });
      const out = await call('canvas_task_create', bid, [{ inputs }]);
      if (!out) return null;
      toast('▶ Đã tạo tác vụ chạy toàn bộ — xem ở 📋 Tác vụ', 'ok');
      C.board = prev;
      tasksView(bid);
      return out;
    } finally {
      if (C.board === opened.board && fromList) C.board = prev;
    }
  }

  const fmtSecs = s => (s >= 90 ? `~${Math.round(s / 60)} phút` : s > 0 ? `~${s} giây` : '');

  /** Bảng xem trước lượt chạy (thay hộp xác nhận chữ): khối nào chạy + vì sao + tốn lượt model gì + thời gian ước tính
   *  (theo lần chạy trước); bỏ chọn khối không muốn làm lại → giữ kết quả cũ của nó, tính lại kế hoạch ngay. Có lỗi → nêu
   *  lỗi, cho bỏ khối lỗi khỏi lượt này. Trả kết quả canvas_run_flow khi đã bắt đầu chạy, null khi huỷ. */
  function runDialog(bid, mode, target, fresh, plan0, opts = {}) {
    return new Promise(resolve => {
      const skip = new Set();
      let plan = plan0;
      const box = document.createElement('div');
      box.className = 'cv-lightbox cv-import cv-run-dlg';
      const title = mode === 'all' ? (fresh ? '⟳ Làm lại tất cả' : '▶ Chạy toàn bộ') : mode === 'to' ? `▶ Chạy đến ${target}` : `⏩ Chạy từ ${target}`;
      const lab = id => (plan.labels || {})[id] || { name: id, kind: '', title: '' };
      const icon = l => (l.kind === 'wf' ? (((C.meta && C.meta.wf_types) || {})[l.wtype] || {}).icon || '🧩' : KIND_ICON[l.kind] || '•');
      const head = id => { const l = lab(id); return `<span class="cv-node-ic">${esc(icon(l))}</span>
        <span class="cv-run-main"><span><b>${esc(l.title || l.name)}</b> <code>${esc(id)}</code>${l.title ? ` <em>${esc(l.name)}</em>` : ''}</span>`; };
      const runRow = id => {
        const info = (plan.info || {})[id] || {}, why = (plan.why || {})[id] || {};
        const use = (info.usage || []).map(([l, k]) => `${l}${k > 1 ? ` ×${k}` : ''}`).join(' · ');
        return `<label class="cv-run-row"><input type="checkbox" data-run="${esc(id)}" checked>${head(id)}
          <small class="why why-${esc(why.code || '')}">${esc(why.text || '')}${(why.up || []).length ? `: ${esc(why.up.join(', '))}` : ''}</small></span>
          <span class="cv-run-meta">${use ? `<small>${esc(use)}</small>` : ''}${info.secs ? `<small>${esc(fmtSecs(info.secs))}</small>` : ''}</span></label>`;
      };
      const offRow = id => {
        const blocked = plan.blocked.includes(id), mine = skip.has(id);
        return `<label class="cv-run-row off"><input type="checkbox" data-run="${esc(id)}" ${mine ? '' : 'disabled'}>${head(id)}
          <small class="why">${blocked ? 'Bỏ — khối phía trước không chạy mà chưa có kết quả' : mine ? 'Bạn bỏ chọn — giữ kết quả cũ' : '🔒 Đang khoá nhưng chưa có kết quả'}</small></span></label>`;
      };
      const keepRow = (id, why) => `<div class="cv-run-row keep">${head(id)}<small class="why">${esc(why)}</small></span></div>`;
      const close = value => { document.removeEventListener('keydown', onKey, true); box.remove(); resolve(value); };
      const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(null); } };
      const recalc = async () => {
        const res = await call('canvas_preview', bid, mode, target, !!fresh, [...skip]);
        if (res) { plan = res.plan; render(); }
      };
      const render = () => {
        const errors = plan.issues.filter(i => i.level === 'error'), warns = plan.issues.filter(i => i.level === 'warn');
        const est = plan.est || {}, off = plan.skipped.length + plan.blocked.length, keep = plan.held.length + plan.reuse.length;
        const names = ids => ids.map(id => (lab(id).title ? `${id} (${lab(id).title})` : id)).join(', ');
        const scroll = (box.querySelector('.cv-run-list') || {}).scrollTop || 0;
        box.innerHTML = `<div class="cv-import-box cv-run-box">
          <div class="cv-side-head"><b>${esc(title)}</b><button class="btn ghost sm" data-x type="button">✕</button></div>
          <div class="cv-run-sum"><span class="cv-chip main">${plan.run.length} khối sẽ chạy</span>
            ${keep ? `<span class="cv-chip">♻ ${keep} giữ nguyên${plan.held.length ? ` (🔒 ${plan.held.length} khoá)` : ''}</span>` : ''}
            ${off ? `<span class="cv-chip off">⏭ ${off} bỏ qua</span>` : ''}
            ${est.secs || est.unknown ? `<span class="cv-chip">⏱ ${est.secs ? fmtSecs(est.secs) : ''}${est.unknown ? `${est.secs ? ' + ' : ''}${est.unknown} khối chưa có số liệu` : ''}</span>` : ''}</div>
          ${(plan.usage || []).length ? `<div class="cv-run-use"><small class="muted">Tốn lượt</small>${plan.usage.map(([l, k]) =>
            `<span class="cv-chip use ${l.startsWith('Trên máy') ? 'local' : ''}">${esc(l)} <b>×${k}</b></span>`).join('')}</div>` : ''}
          ${errors.length ? `<div class="cv-run-errs"><b>⚠ Cần sửa trước khi chạy</b>${errors.map(i => `<div class="cv-issue error"><b>${esc(i.node || 'Quy trình')}</b><span>${esc(i.message)}</span>
            <div class="row">${i.node && plan.run.includes(i.node) ? `<button class="btn ghost sm" data-skip-err="${esc(i.node)}" type="button">Bỏ khối này ở lượt này</button>` : ''}
              ${i.node && opts.onGo ? `<button class="btn ghost sm" data-go-err="${esc(i.node)}" type="button">Đến khối để sửa</button>` : ''}</div></div>`).join('')}</div>` : ''}
          ${plan.posts.length ? `<div class="cv-run-note">📣 ${esc(names(plan.posts))}: app DỪNG CHỜ bạn duyệt trên khối trước khi đăng; quảng cáo tạo ở trạng thái tạm dừng.</div>` : ''}
          ${(plan.review_posts || []).length ? `<div class="cv-run-note">📥 ${esc(names(plan.review_posts))}: lưu bài vào Quản lý bài đăng (Chờ duyệt) — không đăng ngay, có thông báo khi bài sẵn sàng.</div>` : ''}
          ${(plan.auto_posts || []).length ? `<div class="cv-run-note danger">🚀 TỰ ĐĂNG KHÔNG CẦN DUYỆT: ${esc(names(plan.auto_posts))} — bài lên Fanpage ngay khi tới lượt.</div>` : ''}
          ${warns.map(w => `<div class="cv-run-note">⚠ ${esc(w.node)}: ${esc(w.message)}${w.split ? ` <button class="btn ghost sm" data-split-warn="${esc(w.node)}" type="button">✂ Tách thành ${w.split} video</button>` : ''}</div>`).join('')}
          <div class="cv-run-list">${plan.run.map(runRow).join('')}${[...plan.skipped, ...plan.blocked].map(offRow).join('')}
            ${plan.run.length || off ? '' : '<p class="muted">Không còn khối nào cần chạy.</p>'}</div>
          ${keep ? `<details class="cv-run-keep"><summary>Giữ nguyên kết quả (${keep})</summary>
            ${plan.held.map(id => keepRow(id, '🔒 Đã khoá')).join('')}${plan.reuse.map(id => keepRow(id, '♻ Không đổi — dùng lại kết quả')).join('')}</details>` : ''}
          <div class="row cv-run-foot"><small class="muted">Bỏ chọn 1 khối = giữ kết quả cũ của nó ở lượt này (không tốn lượt)</small><span class="cv-sp"></span>
            <button class="btn ghost sm" data-x type="button">Huỷ</button>
            <button class="btn primary sm" data-go type="button" ${plan.run.length && !errors.length ? '' : 'disabled'}>▶ Chạy ${plan.run.length} khối</button></div></div>`;
        const list = box.querySelector('.cv-run-list');
        if (list) list.scrollTop = scroll;
        box.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => close(null); });
        box.querySelectorAll('[data-run]').forEach(cb => {
          cb.onchange = () => { if (cb.checked) skip.delete(cb.dataset.run); else skip.add(cb.dataset.run); recalc(); };
        });
        box.querySelectorAll('[data-skip-err]').forEach(b => { b.onclick = () => { skip.add(b.dataset.skipErr); recalc(); }; });
        box.querySelectorAll('[data-split-warn]').forEach(b => { b.onclick = async () => { b.disabled = true; if (await splitVideo(b.dataset.splitWarn)) recalc(); else b.disabled = false; }; });
        box.querySelectorAll('[data-go-err]').forEach(b => { b.onclick = () => { close(null); opts.onGo(b.dataset.goErr); }; });
        box.querySelector('[data-go]').onclick = async e => {
          const btn = e.currentTarget;
          btn.disabled = true;
          const run = await call('canvas_run_flow', bid, mode, target, !!fresh, [...skip]);
          if (run) close(run); else btn.disabled = false;
        };
      };
      render();
      document.addEventListener('keydown', onKey, true);
      document.body.appendChild(box);
    });
  }

  const inputFile = n => (n.kind === 'upload' ? mediaUrl(n) : ((n.config || {}).files || [])[0] || '');

  const isFileInput = n => n.kind === 'upload' || n.wtype === 'input_video';
  const ASK_TYPES = ['text', 'textarea', 'select', 'check', 'number', 'datetime', 'fb_page', 'ad_account', 'studio_preset'];
  const askCheck = n => `<label class="cv-opt-check" title="Mỗi lần ▶ Chạy toàn bộ / Đến đây / Từ đây, app hỏi lại prompt của node này trước khi chạy"><input type="checkbox" data-f="ask" ${n.ask ? 'checked' : ''}> ❓ Hỏi khi chạy</label>`
    + `<label class="cv-opt-check" title="Bật: để trống prompt / lời thoại vẫn chạy — không chặn quy trình"><input type="checkbox" data-f="optional" ${n.optional ? 'checked' : ''}> ✏ Không bắt buộc nhập</label>`
    + askFieldsHtml(n);

  /* ❓ chọn ô hỏi khi chạy: node.ask_fields = các ô được hỏi (rỗng = mọi ô) — chọn ở bảng cấu hình hoặc ngay trong hộp hỏi */
  function askCandidates(n) {
    if (n.kind === 'wf') return wspec(n).fields.filter(f => ASK_TYPES.includes(f.type) && f.key !== 'ask').map(f => ({ key: f.key, label: f.label }));
    if (n.kind === 'image') return [{ key: 'prompt', label: 'Prompt' }];
    if (n.kind === 'video') return [{ key: 'prompt', label: 'Prompt' }, { key: 'dialogue', label: 'Lời thoại' }];
    return [];
  }
  const askOn = (n, key) => !(n.ask_fields || []).length || n.ask_fields.includes(key);
  function askFieldsHtml(n, open = false) {
    const all = askCandidates(n);
    if (!n.ask || all.length < 2) return '';
    const on = all.filter(f => askOn(n, f.key)).length;
    return `<details class="cv-ask-fields" data-askf-node="${esc(n.id)}" ${open ? 'open' : ''}>
      <summary title="Chọn các ô app hỏi bạn nhập mỗi lần chạy quy trình (kể cả chạy từ Danh sách Canvas) — ô không chọn dùng giá trị đã lưu">⚙ Ô hỏi khi chạy: <b>${on === all.length ? 'tất cả' : `${on}/${all.length}`}</b></summary>
      <div class="cv-ask-fields-list">${all.map(f => `<label class="cv-opt-check"><input type="checkbox" data-askf="${esc(f.key)}" ${askOn(n, f.key) ? 'checked' : ''}> ${esc(f.label)}</label>`).join('')}</div></details>`;
  }
  document.addEventListener('change', async e => {
    const cb = e.target.closest && e.target.closest('[data-askf]');
    const box = cb && cb.closest('[data-askf-node]');
    const pg = document.querySelector(CFG.page);  // 2 màn Canvas cùng nằm trong trang: chỉ màn đang hiện xử lý
    if (box && (!pg || pg.classList.contains('hidden'))) return;
    const n = box && C.board && node(box.dataset.askfNode);
    if (!n) return;
    const boxes = [...box.querySelectorAll('[data-askf]')];
    const picked = boxes.filter(x => x.checked).map(x => x.dataset.askf);
    if (!picked.length) { cb.checked = true; toast('Giữ ít nhất 1 ô để hỏi — hoặc tắt “❓ Hỏi khi chạy”', 'warn'); return; }
    const list = picked.length === boxes.length ? [] : picked;
    const res = await call('canvas_update_nodes', C.board.id, [{ id: n.id, ask_fields: list }]);
    if (!res) return;
    C.board = res.board;
    const sum = box.querySelector('summary b');
    if (sum) sum.textContent = list.length ? `${list.length}/${boxes.length}` : 'tất cả';
    document.dispatchEvent(new CustomEvent('cv-askf', { detail: n.id }));
  });

  async function askInputs(ids, { fromList = false } = {}) {
    // fromList: chạy từ Danh sách Canvas → chỉ nhập các ô đã chọn, KHÔNG cho đổi “⚙ Ô hỏi khi chạy” (chỉ sửa trong Canvas)
    const askPick = (n, open) => (fromList ? '' : askFieldsHtml(n, open));
    // hộp hỏi khi chạy: khối bật "❓ Hỏi khi chạy" → sửa prompt / cấu hình; ảnh / video đầu vào → chọn file
    // ↕ thứ tự hiển thị: node.ask_pos (đã sắp xếp trước đó) rồi mới tới thứ tự chạy
    const list = ids.map(node).filter(Boolean).map((n, i) => [n, i])
      .sort((a, b) => ((a[0].ask_pos ?? 1e3) - (b[0].ask_pos ?? 1e3)) || a[1] - b[1]).map(x => x[0]);
    if (list.some(n => n.kind === 'wf' && wspec(n).fields.some(f => ['fb_page', 'ad_account', 'studio_preset'].includes(f.type)))) {
      await loadSources();
    }
    return new Promise(resolve => {
      const box = document.createElement('div');
      box.className = 'cv-lightbox cv-import';
      const title = n => `<div class="cv-ask-title"><b>${esc(n.title || nameOf(n))}</b> <small class="muted">${esc(n.id)} · ${esc(nameOf(n))}</small>${n.optional ? ' <small class="cv-opt-tag" title="Để trống vẫn chạy">✏ không bắt buộc</small>' : ''}</div>`;
      const fileInner = n => {
        const f = inputFile(n);
        const video = n.kind !== 'upload';
        return `<span class="cv-ask-thumb">${f ? (video ? '🎞' : `<img src="${esc(thumbUrl(f, 160))}" alt="">`) : '—'}</span>
          <div>${title(n)}<small class="${f ? 'muted' : 'warn-text'}">${f ? (video ? esc(String(f).split(/[\\/]/).pop()) : 'Đang dùng ảnh hiện tại') : 'Chưa có file — bắt buộc chọn'}</small></div>
          <button class="btn ${f ? 'ghost' : 'primary'} sm" data-pick-in="${esc(n.id)}" type="button">${video ? '🎞 Chọn video…' : '🖼 Chọn ảnh…'}</button>`;
      };
      // ❓ chỉ hiện các ô đã chọn (node.ask_fields); khung “⚙ Ô hỏi khi chạy” cuối mỗi khối đổi lựa chọn ngay tại đây.
      // keep = giá trị đang gõ dở (vẽ lại khối sau khi đổi lựa chọn không làm mất chữ)
      const row = (n, keep = {}, open = false) => {
        if (isFileInput(n)) return `<div class="cv-ask-row" data-file-row="${esc(n.id)}">${fileInner(n)}</div>`;
        if (n.kind !== 'wf') {
          const linked = n.kind === 'video' && n.dialogue_src && node(n.dialogue_src);
          return `<div class="cv-ask-block" data-ask-media="${esc(n.id)}">${title(n)}
            ${askOn(n, 'prompt') ? `<textarea data-ask-prompt="${esc(n.id)}" rows="3" placeholder="Prompt cho lần chạy này…">${esc(keep.prompt ?? n.prompt ?? '')}</textarea>` : ''}
            ${n.kind !== 'video' || !askOn(n, 'dialogue') ? ''
              : linked ? `<small class="muted">💬 Lời thoại lấy từ khối ${esc(n.dialogue_src)} — sửa ở khối đó</small>`
                : `<small class="muted">💬 Lời thoại (mỗi dòng 1 câu; nhiều người: Tên: câu nói)</small>
              <textarea data-ask-dialogue="${esc(n.id)}" rows="2" placeholder="Để trống = không thoại">${esc(keep.dialogue ?? n.dialogue ?? '')}</textarea>`}
            ${askPick(n, open)}</div>`;
        }
        const cfg = { ...(n.config || {}), ...keep };
        const fields = wspec(n).fields.filter(f => ASK_TYPES.includes(f.type) && f.key !== 'ask' && fieldVisible(f, cfg) && askOn(n, f.key));
        return `<div class="cv-ask-block" data-ask-wf="${esc(n.id)}">${title(n)}<div class="cv-wf-fields">${fields.map(f => fieldHtml(f, cfg)).join('')
          || '<small class="muted">Không có ô nào cần hỏi ở lượt này</small>'}</div>
          ${['fb_post', 'fb_schedule'].includes(n.wtype) ? `<label class="cv-opt-check cv-auto-post ${n.auto_post ? 'on' : ''}"><input type="checkbox" data-ask-auto="${esc(n.id)}" ${n.auto_post ? 'checked' : ''}>
            🚀 Tự đăng không cần duyệt <small class="muted">(lần này và các lần chạy sau)</small></label>` : ''}
          ${askPick(n, open)}</div>`;
      };
      box.innerHTML = `<div class="cv-import-box cv-ask-box"><div class="cv-side-head"><b>❓ Kiểm tra trước khi chạy</b><button class="btn ghost sm" data-x type="button">✕</button></div>
        <p class="muted">Các khối bật “Hỏi khi chạy”: sửa prompt / thông tin / chọn file cho lần chạy này. Khối nào đổi thì nó và các khối phía sau sẽ chạy lại.${list.length > 1 ? ' Kéo ⠿ hoặc bấm ▲ ▼ để sắp xếp (chỉ đổi thứ tự hiển thị, không đổi thứ tự chạy).' : ''}</p>
        <div class="cv-ask-list">${list.map(n => list.length > 1 ? `<div class="cv-ask-item" data-ask-id="${esc(n.id)}">
          <div class="cv-ask-move"><button type="button" data-ask-up title="Lên trên">▲</button><span class="cv-ask-grip" title="Kéo để sắp xếp">⠿</span><button type="button" data-ask-down title="Xuống dưới">▼</button></div>
          <div class="cv-ask-body">${row(n)}</div></div>` : row(n)).join('')}</div>
        <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn ghost sm" data-x type="button">Huỷ</button>
          <button class="btn primary sm" data-go type="button">▶ Tiếp tục chạy</button></div></div>`;
      const go = box.querySelector('[data-go]');
      // ảnh / video đầu vào bắt buộc chọn — trừ khối ✏ không bắt buộc
      const refresh = () => { go.disabled = !list.every(n => !isFileInput(n) || node(n.id).optional || inputFile(node(n.id))); };
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
      // đổi “⚙ Ô hỏi khi chạy” (đã lưu ở bộ xử lý chung) → vẽ lại khối đó, giữ chữ đang gõ ở các ô còn hiện
      const onAskf = e => {
        const id = e.detail;
        const blk = box.querySelector(`[data-ask-wf="${id}"], [data-ask-media="${id}"]`);
        if (!blk || !node(id)) return;
        const keep = {};
        blk.querySelectorAll('[data-c]').forEach(el => { keep[el.dataset.c] = el.type === 'checkbox' ? el.checked : el.value; });
        const p = blk.querySelector('[data-ask-prompt]'), d = blk.querySelector('[data-ask-dialogue]');
        if (p) keep.prompt = p.value;
        if (d) keep.dialogue = d.value;
        blk.outerHTML = row(node(id), keep, true);
        bindAuto(box.querySelector(`[data-ask-wf="${id}"], [data-ask-media="${id}"]`));
      };
      document.addEventListener('cv-askf', onAskf);
      const bindAuto = scope => scope && scope.querySelectorAll('[data-ask-auto]').forEach(cb => {
        cb.onchange = () => {
          const n = node(cb.dataset.askAuto);
          const pageSel = box.querySelector(`[data-ask-wf="${cb.dataset.askAuto}"] [data-c="page_id"]`);
          const page = pageSel && pageSel.selectedOptions[0] ? pageSel.selectedOptions[0].textContent.trim() : 'đã chọn';
          if (cb.checked && !confirm(`Bật TỰ ĐĂNG cho khối ${n.id}${n.title ? ` (${n.title})` : ''}?\n\nKhi chạy, bài sẽ được đăng thẳng lên Fanpage “${page}” mà KHÔNG dừng chờ bạn duyệt nội dung.`)) cb.checked = false;
          cb.closest('.cv-auto-post').classList.toggle('on', cb.checked);
        };
      });
      bindAuto(box);
      refresh();
      // ↕ sắp xếp các khối trong hộp (nút ↑ ↓ hoặc kéo ⠿) → lưu node.ask_pos, lần sau hiện đúng thứ tự (giữ chữ đang gõ)
      const listEl = box.querySelector('.cv-ask-list');
      const saveOrder = async () => {
        const order = [...listEl.querySelectorAll(':scope > .cv-ask-item')].map(el => el.dataset.askId);
        const res = await call('canvas_update_nodes', C.board.id, order.map((id, i) => ({ id, ask_pos: i })));
        if (res) C.board = res.board;
      };
      listEl.querySelectorAll(':scope > .cv-ask-item').forEach(item => {
        item.querySelector('[data-ask-up]').onclick = () => {
          const prev = item.previousElementSibling;
          if (prev) { listEl.insertBefore(item, prev); saveOrder(); }
        };
        item.querySelector('[data-ask-down]').onclick = () => {
          const next = item.nextElementSibling;
          if (next) { listEl.insertBefore(next, item); saveOrder(); }
        };
        const grip = item.querySelector('.cv-ask-grip');
        grip.onmousedown = () => { item.draggable = true; };
        item.ondragstart = e => { item.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', item.dataset.askId); };
        item.ondragend = () => { item.draggable = false; item.classList.remove('dragging'); listEl.querySelectorAll('.drop-before,.drop-after').forEach(x => x.classList.remove('drop-before', 'drop-after')); saveOrder(); };
        item.ondragover = e => {
          const dragging = listEl.querySelector('.cv-ask-item.dragging');
          if (!dragging || dragging === item) return;
          e.preventDefault();
          const r = item.getBoundingClientRect();
          const after = e.clientY > r.top + r.height / 2;
          listEl.insertBefore(dragging, after ? item.nextElementSibling : item);
        };
      });
      document.addEventListener('mouseup', () => listEl.querySelectorAll('.cv-ask-item[draggable="true"]:not(.dragging)').forEach(x => { x.draggable = false; }), { once: true });
      const close = ok => { document.removeEventListener('cv-askf', onAskf); box.remove(); resolve(ok); };
      box.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => close(false); });
      go.onclick = async () => {
        const patches = [];
        box.querySelectorAll('[data-ask-media]').forEach(blk => {  // chỉ các ô đang hỏi (prompt / lời thoại)
          const ta = blk.querySelector('[data-ask-prompt]'), dlg = blk.querySelector('[data-ask-dialogue]');
          if (ta || dlg) patches.push({ id: blk.dataset.askMedia, ...(ta ? { prompt: ta.value } : {}), ...(dlg ? { dialogue: dlg.value } : {}) });
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
        close(true);
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
    // nhiều khối chạy song song: current = "n3, n5" → cộng phần đã xong của từng khối đang chạy
    const curIds = rec.status === 'running' && rec.current ? String(rec.current).split(/,\s*/) : [];
    const part = curIds.reduce((a, id) => a + (node(id) && rec.nodes[id] === 'running' ? (node(id).pct || 0) / 100 : 0), 0);
    const pct = ids.length ? Math.round(100 * (finished + part) / ids.length) : 0;
    if (!(C.logs[rec.task] || []).length && rec.status !== 'running' && !(C.logFetched || {})[rec.id]) {
      // mở lại app / bảng: nhật ký trong bộ nhớ đã mất → đọc bản đã lưu ra file của lượt này
      C.logFetched = { ...(C.logFetched || {}), [rec.id]: true };
      const bid = C.board.id;
      call('canvas_log', bid, 'run', rec.id).then(r => {
        if (r && r.entries.length && C.board && C.board.id === bid) { C.logs[rec.task] = r.entries; drawTray(); }
      });
    }
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
          : `<div class="muted">${rec.status === 'running' ? 'Đang bắt đầu…' : 'Chưa có nhật ký cho lượt này'}</div>`}</div></div>`;
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
      ${list.length ? list.map(r => `<div class="cv-run ${esc(r.status)}"><div class="cv-run-top"><div><b>${RUN_ICON[r.status] || ''} ${esc(r.label)}</b>
          <small class="muted">${esc(r.at)}${r.ended ? ` → ${esc(r.ended.slice(11))}` : ''} · ${esc(RUN_VI[r.status] || r.status)}</small></div>
          <button class="btn ghost sm" data-runlog="${esc(r.id)}" type="button" title="Nhật ký chi tiết của lượt chạy này">📜 Nhật ký</button></div>
        <div class="cv-run-nodes">${Object.entries(r.nodes || {}).map(([id, s]) => `<button class="cv-run-node ${esc(s)}" data-go="${esc(id)}" title="${esc(labelOf(node(id)) + ' · ' + s)}" type="button">${RUN_ICON[s] || ''} ${esc(id)}${node(id) && node(id).title ? ` · ${esc(node(id).title)}` : ''}</button>`).join('')}
          ${(r.reused || []).length ? `<small class="muted">♻ dùng lại: ${r.reused.map(esc).join(', ')}</small>` : ''}
          ${(r.held || []).length ? `<small class="muted">🔒 giữ: ${r.held.map(esc).join(', ')}</small>` : ''}
          ${(r.skipped || []).length ? `<small class="muted">⏭ bỏ qua: ${r.skipped.map(esc).join(', ')}</small>` : ''}</div></div>`).join('')
        : '<p class="muted">Chưa chạy quy trình lần nào — bấm ▶ Chạy toàn bộ.</p>'}`;
    side.classList.remove('hidden');
    side.querySelector('[data-close]').onclick = () => side.classList.add('hidden');
    side.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => focusNode(b.dataset.go); });
    side.querySelectorAll('[data-runlog]').forEach(b => {
      b.onclick = async () => {
        const r = list.find(x => x.id === b.dataset.runlog);
        const res = await call('canvas_log', C.board.id, 'run', b.dataset.runlog);
        if (res) logDialog(`📜 Nhật ký · ${r ? r.label : b.dataset.runlog}${r ? ` · ${r.at}` : ''}`, res.entries.length ? res.entries : (C.logs[(r || {}).task] || []));
      };
    });
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
      const item = document.querySelector(`.sb-item[data-view="${CFG.view}"]`);
      if (item) item.classList.toggle('cv-busy-dot', busy);
      return;
    }
    if (event === 'canvas_schedule') {  // bộ hẹn giờ vừa chạy / lùi / bỏ lượt → cập nhật thẻ (lần tới, kết quả lượt trước)
      if (C.board && data.board === C.board.id) C.board.schedule = { ...(C.board.schedule || {}), ...data.schedule };
      const card = !C.board && C.boards.find(x => x.id === data.board);
      if (card) { card.schedule = { ...(card.schedule || {}), ...data.schedule }; drawCards(); }
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
      if (data.reload) {  // tự điều phối vừa thêm khối / nối dây → vẽ lại bảng
        const bid = C.board.id;
        call('canvas_open', bid).then(r => { if (r && C.board && C.board.id === bid) { C.board = r.board; drawAll(); } });
      }
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
    if (event === 'canvas_drop' && C.board && data.board === C.board.id) {  // Storyboard ít cảnh hơn → gỡ khối cảnh thừa
      const gone = new Set(data.nodes || []);
      C.board.nodes = C.board.nodes.filter(n => !gone.has(n.id));
      for (const n of C.board.nodes) n.inputs = (n.inputs || []).filter(i => !gone.has(i));
      for (const id of gone) C.multi?.delete(id);
      if (gone.has(C.sel)) C.sel = '';
      drawAll();
      return;
    }
    if (event === 'canvas_node' && C.board && data.board === C.board.id) {
      const i = C.board.nodes.findIndex(n => n.id === data.node.id);
      if (i < 0) {  // node do app tạo (Storyboard tách cảnh → node Video + khối Ghép) → thêm vào bảng
        C.board.nodes.push(data.node);
        drawAll();
        return;
      }
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

  // ================================================================ 🎥 màn Canvas Google Flow: ⚙ Model định sẵn
  function modelLine() {
    const f = (C.meta && C.meta.flow) || {};
    const n = f.names || {};
    return `viết / xử lý ${n.text || 'ChatGPT'} · ảnh ${n.image || 'ChatGPT'} · video ${n.video || 'Grok'} · điều phối ${n.assist || 'Claude'}`;
  }

  /* ---------------------------------------------------------------- 🎞 mẫu video (Grok Canvas) */
  async function loadTemplates() {
    const res = await call('canvas_video_templates');
    if (res) C.tpls = res;
    return C.tpls;
  }
  const tplOf = id => ((C.tpls || {}).templates || []).find(t => t.id === id) || null;
  function tplChip(n) {
    const t = n.kind === 'video' && !n.part_of && n.template ? tplOf(n.template) : null;
    if (!t) return '';
    return `<div class="cv-flow-card-chips cv-tpl-chips"><span>${esc(t.icon)} ${esc(t.name)}</span>`
      + `<span>${n.build === 'split' ? '✂ Tách khối' : '🎬 Tự chia + ghép'}</span></div>`;
  }
  function tplHtml(n) {
    const list = (C.tpls || {}).templates || [];
    const t = n.template ? tplOf(n.template) : null;
    const secs = parseInt(n.duration || '10', 10) || 10;
    const opts = `<option value="">— Không dùng mẫu (Video thường) —</option>`
      + list.map(x => `<option value="${esc(x.id)}" ${x.id === n.template ? 'selected' : ''}>${esc(x.icon)} ${esc(x.name)}${x.user && !x.builtin ? ' (của bạn)' : ''}</option>`).join('');
    const head = `<div class="cv-tpl-sec"><div class="cv-tpl-h"><b>🎞 Mẫu video</b>
      <button class="btn ghost sm" type="button" data-tpl-lib="${esc(n.id)}" title="Xem / sửa / tạo mẫu: phong cách, Master Prompt, khung cảnh">📚 Thư viện mẫu</button></div>
      <label title="Chọn mẫu → khối chỉ cần ảnh vật liệu + lời thoại"><select data-f="template">${opts}</select></label>`;
    if (!t) return `${head}<small class="muted">Chọn 1 mẫu: chỉ cần nối ảnh vật liệu (nhân vật, sản phẩm, bối cảnh) + lời thoại — khối tự làm video chuyên nghiệp.</small></div>`;
    const cont = ((C.tpls || {}).continuity || {})[t.continuity] || '';
    const mats = (t.materials || []).map(k => ((C.tpls || {}).materials || {})[k]).filter(Boolean).join(' · ');
    return `${head}<small class="muted">${esc(t.desc)}</small>
      <div class="cv-flow-chips"><span>${esc(cont.split('—')[0].trim())}</span><span>~${t.segments} cảnh mẫu</span><span>${secs} giây / đoạn</span></div>
      ${mats ? `<small class="muted">Vật liệu nên có: ${esc(mats)}</small>` : ''}
      <div class="cv-seg2" role="radiogroup" title="Cách dựng video dài">
        <button type="button" data-set="build" data-val="one" class="${n.build !== 'split' ? 'on' : ''}" aria-pressed="${n.build !== 'split'}"><i>🎬</i>Không tách</button>
        <button type="button" data-set="build" data-val="split" class="${n.build === 'split' ? 'on' : ''}" aria-pressed="${n.build === 'split'}"><i>✂</i>Tách khối</button></div>
      <small class="muted">${n.build === 'split'
    ? 'Lời dài → mỗi đoạn 1 khối Video con + khối Ghép (xem / tạo lại từng đoạn). Mỗi khối con lấy khung cảnh của mẫu.'
    : 'Khối tự chia lời thành các đoạn vừa 1 clip, quay lần lượt rồi ghép thành 1 video. Đoạn lỗi → chạy lại chỉ quay đoạn đó.'}</small>
      ${n.build !== 'split' ? `<label class="cv-opt-check" title="Tắt: điền prompt theo khung cảnh của mẫu (không tốn lượt model chữ)"><input type="checkbox" data-f="tpl_ai" ${n.tpl_ai !== false ? 'checked' : ''}> ✍ AI viết prompt từng đoạn (1 lượt ${esc(((C.meta.flow || {}).names || {}).text || 'ChatGPT')})</label>` : ''}</div>`;
  }

  async function templatesDialog(forNode) {
    if (!(await loadTemplates())) return;
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import cv-tpl-dlg';
    let edit = null;  // mẫu đang sửa (bản nháp)
    const T = () => C.tpls;
    const target = forNode && C.board ? node(forNode) : null;
    const close = () => box.remove();
    const drawList = () => {
      const list = T().templates || [];
      box.innerHTML = `<div class="cv-import-box cv-tpl-box"><div class="cv-side-head"><b>🎞 Thư viện mẫu video</b>
        <button class="btn ghost sm" data-x type="button">✕</button></div>
        <p class="muted">Mẫu = phong cách hình + Master Prompt + khung cảnh quay + kiểu nối cảnh. Khối Video chọn mẫu chỉ cần ảnh vật liệu + lời thoại.${target ? ` Đang chọn mẫu cho khối <b>${esc(target.id)}</b>.` : ''}</p>
        <div class="cv-tpl-grid">${list.map(t => `<div class="cv-tpl-card${target && target.template === t.id ? ' on' : ''}" data-tid="${esc(t.id)}">
          <div class="cv-tpl-card-h"><i>${esc(t.icon)}</i><b>${esc(t.name)}</b>
            <small class="cv-tpl-badge">${t.builtin ? (t.edited ? 'Có sẵn · đã sửa' : 'Có sẵn') : 'Của bạn'}</small></div>
          <small class="muted">${esc(t.desc)}</small>
          <div class="cv-flow-chips"><span>${t.continuity === 'flow' ? '⛓ Liền mạch' : '✂ Cắt cảnh'}</span><span>${t.shots.length} khung cảnh</span></div>
          <div class="row">${target ? `<button class="btn primary sm" type="button" data-use="${esc(t.id)}">Dùng cho ${esc(target.id)}</button>` : ''}
            <button class="btn ghost sm" type="button" data-edit="${esc(t.id)}">✏ Sửa</button>
            <button class="btn ghost sm" type="button" data-dup="${esc(t.id)}">⧉ Nhân bản</button>
            ${t.user ? `<button class="btn ghost sm" type="button" data-del="${esc(t.id)}">${t.builtin ? '↺ Về mặc định' : '🗑 Xoá'}</button>` : ''}</div></div>`).join('')}</div>
        <div class="row cv-run-foot"><button class="btn ghost sm" type="button" data-new>＋ Mẫu mới</button><span class="cv-sp"></span>
          <button class="btn ghost sm" data-x type="button">Đóng</button></div></div>`;
      box.querySelectorAll('[data-x]').forEach(b => { b.onclick = close; });
      box.querySelectorAll('[data-use]').forEach(b => {
        b.onclick = async () => {
          close();
          await setOption(target.id, 'template', b.dataset.use);
          toast(`🎞 ${target.id}: dùng mẫu “${(tplOf(b.dataset.use) || {}).name || ''}”`, 'ok');
        };
      });
      box.querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => { edit = JSON.parse(JSON.stringify(tplOf(b.dataset.edit))); drawEdit(); }; });
      box.querySelectorAll('[data-dup]').forEach(b => {
        b.onclick = () => { const src = tplOf(b.dataset.dup); edit = { ...JSON.parse(JSON.stringify(src)), id: '', name: `${src.name} (bản sao)`, builtin: false, user: false }; drawEdit(); };
      });
      box.querySelectorAll('[data-del]').forEach(b => {
        b.onclick = async () => {
          const t = tplOf(b.dataset.del);
          if (!confirm(t.builtin ? `Bỏ bản sửa, đưa “${t.name}” về mặc định?` : `Xoá mẫu “${t.name}”?`)) return;
          const res = await call('canvas_video_template_delete', t.id);
          if (res) { C.tpls.templates = res.templates; drawList(); if (C.board) { drawAll(); drawPanel(); } }
        };
      });
      box.querySelector('[data-new]').onclick = () => {
        edit = { id: '', name: '', icon: '🎞', desc: '', continuity: 'cut', segments: 3, materials: ['character', 'product'],
          style: '', master: '', shots: [''], builtin: false, user: false };
        drawEdit();
      };
    };
    const drawEdit = () => {
      const e = edit;
      const mats = T().materials || {};
      box.innerHTML = `<div class="cv-import-box cv-tpl-box"><div class="cv-side-head"><b>${e.id ? `✏ Sửa mẫu “${esc(e.name)}”` : '＋ Mẫu mới'}</b>
        <button class="btn ghost sm" data-back type="button">← Thư viện</button></div>
        ${e.builtin ? '<p class="muted">Mẫu có sẵn: lưu = lưu bản sửa của bạn (bấm “↺ Về mặc định” ở thư viện để bỏ).</p>' : ''}
        <div class="inline"><label class="field" style="max-width:80px"><span>Biểu tượng</span><input data-e="icon" value="${esc(e.icon)}" maxlength="4"></label>
          <label class="field" style="flex:1"><span>Tên mẫu *</span><input data-e="name" value="${esc(e.name)}" maxlength="80"></label></div>
        <label class="field"><span>Mô tả ngắn</span><input data-e="desc" value="${esc(e.desc)}" maxlength="300"></label>
        <div class="inline"><label class="field" style="flex:1"><span>Kiểu nối cảnh</span><select data-e="continuity">${Object.entries(T().continuity || {}).map(([k, v]) =>
          `<option value="${esc(k)}" ${k === e.continuity ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
          <label class="field" style="max-width:150px"><span>Số đoạn khi không có lời</span><input data-e="segments" type="number" min="1" max="${T().max_segments || 12}" value="${esc(e.segments)}"></label></div>
        <div class="field"><span>Vật liệu nên có</span><div class="inline">${Object.entries(mats).map(([k, v]) =>
          `<label class="cv-opt-check"><input type="checkbox" data-mat="${esc(k)}" ${(e.materials || []).includes(k) ? 'checked' : ''}> ${esc(v)}</label>`).join('')}</div></div>
        <label class="field"><span>🎨 Phong cách hình (tiếng Anh — gắn vào prompt mọi đoạn)</span><textarea data-e="style" rows="2">${esc(e.style)}</textarea></label>
        <label class="field"><span>🧠 Master Prompt (hướng dẫn AI viết prompt từng đoạn)</span><textarea data-e="master" rows="4">${esc(e.master)}</textarea></label>
        <label class="field"><span>🎬 Khung cảnh quay — mỗi dòng 1 cảnh (đoạn đầu = dòng đầu, đoạn cuối = dòng cuối, giữa xoay vòng)</span><textarea data-e="shots" rows="5">${esc((e.shots || []).join('\n'))}</textarea></label>
        <div class="row cv-run-foot"><span class="cv-sp"></span><button class="btn ghost sm" data-back type="button">Huỷ</button>
          <button class="btn primary sm" data-save type="button">Lưu mẫu</button></div></div>`;
      box.querySelectorAll('[data-back]').forEach(b => { b.onclick = () => { edit = null; drawList(); }; });
      box.querySelector('[data-save]').onclick = async () => {
        const val = k => box.querySelector(`[data-e="${k}"]`).value;
        const tpl = { id: e.id, name: val('name'), icon: val('icon'), desc: val('desc'), continuity: val('continuity'),
          segments: Number(val('segments')) || 3, style: val('style'), master: val('master'),
          shots: val('shots').split('\n').map(x => x.trim()).filter(Boolean),
          materials: [...box.querySelectorAll('[data-mat]:checked')].map(x => x.dataset.mat) };
        if (!tpl.name.trim()) return toast('Nhập tên mẫu', 'error');
        if (!tpl.shots.length) return toast('Nhập ít nhất 1 khung cảnh', 'error');
        const res = await call('canvas_video_template_save', tpl);
        if (!res) return;
        C.tpls.templates = res.templates;
        toast(`🎞 Đã lưu mẫu “${res.template.name}”`, 'ok');
        edit = null;
        drawList();
        if (C.board) { drawAll(); drawPanel(); }
      };
    };
    drawList();
    box.onclick = ev => { if (ev.target === box) close(); };
    document.body.appendChild(box);
  }


  /* ================================================================ 📋 màn Tác vụ: 1 flow chạy nhiều tác vụ */
  const TASK_BADGE = { queued: '⏳ Đang chờ', running: '▶ Đang chạy', reviewing: '🤖 Trợ lý đang chấm', done: '✔ Xong',
    partial: 'Xong 1 phần', error: '✖ Lỗi', cancelled: '⏹ Đã dừng', interrupted: '⚠ Gián đoạn' };
  const AUTO_VI = { reviewing: 'đang chấm', reworking: 'đang làm lại', passed: 'đạt', failed: 'chưa đạt', stopped: 'đã dừng' };
  function autoLine(a) {  // 🤖 tự điều phối của 1 tác vụ: vòng, điểm, nhận xét
    if (!a || (!a.on && !a.status)) return '';
    const st = AUTO_VI[a.status] || (a.on ? 'chờ chạy xong để chấm' : '');
    const score = a.score != null ? ` · ${a.score}/10${a.pass_score ? ` (đạt ≥ ${a.pass_score})` : ''}` : '';
    return `<small class="cv-task-auto ${esc(a.status || '')}" title="${esc(a.note || '')}">🤖 Tự điều phối: ${esc(st)}${a.round ? ` · vòng làm lại ${a.round}/${a.rounds}` : ''}${score}${a.note ? ` — ${esc(String(a.note).slice(0, 120))}` : ''}</small>`;
  }
  const T = { q: '', flow: '', status: '', timer: null, data: null };
  const fmtSize = b => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : b >= 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);
  const tasksVisible = () => !!body() && !!body().querySelector('.cv-tasks') && !document.querySelector(CFG.page).classList.contains('hidden');

  async function tasksView(flowFilter) {
    C.board = null;
    C.sel = '';
    if (flowFilter !== undefined) T.flow = flowFilter;
    body().innerHTML = `<div class="cv-home cv-tasks">
      <div class="cv-home-head"><div><small class="eyebrow">${FLOWSCREEN ? 'GROK CANVAS' : 'CANVAS'} · TÁC VỤ</small><h2>📋 Quản lý tác vụ</h2>
        <p class="muted">Mỗi tác vụ là 1 bản chạy riêng của flow với đầu vào riêng — 1 flow chạy được nhiều tác vụ, kết quả không đè nhau, flow gốc giữ nguyên.</p></div>
        <div class="row"><button class="btn ghost" data-t="home" type="button">⌂ Danh sách Canvas</button>
          <button class="btn primary" data-t="new" type="button">＋ Tạo tác vụ</button></div></div>
      <div class="cv-stats cv-task-stats"></div>
      <div class="cv-filter"><input data-tf="q" placeholder="Tìm theo tên tác vụ / đầu vào…" value="${esc(T.q)}">
        <select data-tf="flow"></select>
        <select data-tf="status">${[['', 'Mọi trạng thái'], ...Object.entries(TASK_BADGE)].map(([v, t]) => `<option value="${v}" ${T.status === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
        <label class="cv-task-par" title="Số tác vụ chạy cùng lúc — còn lại chờ, tự chạy khi có chỗ. Khối dùng chung 1 model trình duyệt vẫn chạy lần lượt.">Chạy cùng lúc
          <select data-tf="parallel">${[1, 2, 3, 4, 5, 6].map(n => `<option value="${n}">${n}</option>`).join('')}</select></label>
        <button class="btn ghost sm" data-t="stopall" type="button">⏹ Dừng tất cả</button>
        <button class="btn ghost sm" data-t="clear" type="button">🧹 Xoá tác vụ đã xong</button></div>
      <div class="cv-task-list"><p class="muted">Đang tải…</p></div></div>`;
    const root = body();
    root.querySelector('[data-t="home"]').onclick = () => { stopTaskPoll(); listBoards(); };
    root.querySelector('[data-t="new"]').onclick = async () => {
      const flows = (await call('canvas_list') || {}).boards || [];
      if (!flows.length) return toast('Chưa có flow nào — tạo Canvas trước', 'warn');
      const pick = T.flow && flows.find(f => f.id === T.flow) ? T.flow : flows.length === 1 ? flows[0].id : await chooseFlow(flows);
      if (pick) taskDialog(pick);
    };
    root.querySelectorAll('[data-tf]').forEach(el => {
      el.oninput = el.onchange = async () => {
        if (el.dataset.tf === 'parallel') {
          const res = await call('canvas_task_parallel', Number(el.value));
          if (res) toast(`Chạy cùng lúc tối đa ${res.parallel} tác vụ`, 'ok');
          return refreshTasks();
        }
        T[el.dataset.tf] = el.value;
        drawTasks();
      };
    });
    root.querySelector('[data-t="stopall"]').onclick = async () => {
      if (!confirm('Dừng mọi tác vụ đang chạy / đang chờ?')) return;
      const res = await call('canvas_task_cancel_all');
      if (res) { toast(`Đã dừng ${res.cancelled} tác vụ`, 'ok'); refreshTasks(); }
    };
    root.querySelector('[data-t="clear"]').onclick = async () => {
      if (!confirm('Xoá mọi tác vụ đã xong (kèm ảnh / video kết quả của chúng)?')) return;
      const res = await call('canvas_task_clear', ['done']);
      if (res) { toast(`Đã xoá ${res.removed} tác vụ`, 'ok'); refreshTasks(); }
    };
    await refreshTasks();
    stopTaskPoll();
    T.timer = setInterval(() => { if (tasksVisible()) refreshTasks(); else stopTaskPoll(); }, 2500);
  }
  function stopTaskPoll() { if (T.timer) clearInterval(T.timer); T.timer = null; }

  async function refreshTasks() {
    const res = await call('canvas_tasks', '');
    if (!res || !tasksVisible()) return;
    T.data = res.result;
    const s = T.data.stats;
    const stat = (label, value, main) => `<div class="cv-stat ${main ? 'main' : ''}"><small>${esc(label)}</small><b>${value}</b></div>`;
    body().querySelector('.cv-task-stats').innerHTML = stat('Tổng tác vụ', s.total, true) + stat('Đang chạy', s.running + (s.reviewing || 0))
      + stat('Đang chờ', s.queued) + stat('Xong', s.done + s.partial) + stat('Lỗi / dừng', s.error + s.cancelled + s.interrupted)
      + stat('Dung lượng', fmtSize(T.data.tasks.reduce((a, x) => a + (x.size || 0), 0)));
    const fsel = body().querySelector('[data-tf="flow"]');
    fsel.innerHTML = [['', 'Mọi flow'], ...T.data.flows.map(f => [f.id, f.name])]
      .map(([v, t]) => `<option value="${esc(v)}" ${T.flow === v ? 'selected' : ''}>${esc(t)}</option>`).join('');
    body().querySelector('[data-tf="parallel"]').value = String(T.data.parallel);
    drawTasks();
  }

  function drawTasks() {
    const box = body().querySelector('.cv-task-list');
    if (!box || !T.data) return;
    const q = T.q.trim().toLowerCase();
    const list = T.data.tasks.filter(x => (!T.flow || x.flow === T.flow) && (!T.status || x.status === T.status)
      && (!q || `${x.name} ${x.inputs.map(i => i.value).join(' ')}`.toLowerCase().includes(q)));
    box.innerHTML = list.map(x => {
      const pct = x.total ? Math.round(100 * x.done / x.total) : 0;
      const live = ['running', 'queued', 'reviewing'].includes(x.status);
      return `<div class="cv-task ${esc(x.status)}" data-tid="${esc(x.id)}">
        <div class="cv-task-res">${x.results.length ? x.results.map(r => r.video
          ? `<a href="${esc(r.url)}" target="_blank" title="${esc(r.title)}"><video src="${esc(r.url)}" muted preload="metadata"></video><i>▶</i></a>`
          : `<a href="${esc(r.url)}" target="_blank" title="${esc(r.title)}"><img src="${esc(thumbUrl(r.url, 200))}" alt=""></a>`).join('') : '<span class="muted">—</span>'}</div>
        <div class="cv-task-main"><div class="row"><b>${esc(x.name)}</b><span class="cv-badge ${esc(x.status)}">${TASK_BADGE[x.status] || esc(x.status)}</span></div>
          <small class="muted">Flow: ${esc(x.flow_name)} · tạo ${esc(fmtTime(x.created_at))}${x.started_at ? ` · bắt đầu ${esc(fmtTime(x.started_at))}` : ''}${x.ended_at ? ` · kết thúc ${esc(fmtTime(x.ended_at))}` : ''} · ${fmtSize(x.size || 0)}</small>
          ${x.total ? `<div class="cv-task-bar"><i style="width:${pct}%"></i></div><small class="muted">${x.done}/${x.total} khối${x.current && x.status === 'running' ? ` · đang chạy: ${esc(x.current)}` : ''}</small>` : ''}
          ${x.inputs.length ? `<div class="cv-task-in">${x.inputs.slice(0, 6).map(i => `<span title="${esc(i.label)}">${esc(i.value)}</span>`).join('')}</div>` : ''}
          ${autoLine(x.auto)}
          ${x.error ? `<small class="warn-text">${esc(x.error)}</small>` : ''}</div>
        <div class="cv-task-act">
          <button class="btn ghost sm" data-ta="open" type="button" title="Mở bảng chạy của tác vụ (xem / làm lại khối)">Mở</button>
          <button class="btn ghost sm ${x.auto && x.auto.on ? 'on' : ''}" data-ta="assist" type="button" title="🤖 Trợ lý của tác vụ: chat với Claude, chấm kết quả, bật / tắt Tự điều phối">🤖 Trợ lý</button>
          ${live ? '<button class="btn ghost sm" data-ta="stop" type="button">⏹ Dừng</button>'
            : x.status === 'done' ? ''
              : '<button class="btn primary sm" data-ta="resume" type="button" title="Chạy tiếp — chỉ chạy khối chưa xong / lỗi">▶ Chạy tiếp</button>'}
          <button class="btn ghost sm" data-ta="dup" type="button" title="Tạo tác vụ mới cùng đầu vào (sửa trước khi tạo)">⧉</button>
          <button class="btn ghost sm" data-ta="folder" type="button" title="Mở thư mục kết quả">📁</button>
          <button class="btn ghost sm" data-ta="del" type="button" title="Xoá tác vụ">🗑</button></div></div>`;
    }).join('') || `<p class="muted">${T.data.tasks.length ? 'Không có tác vụ nào khớp bộ lọc.' : 'Chưa có tác vụ — bấm “＋ Tạo tác vụ” hoặc nút “＋ Tác vụ” trên thẻ flow.'}</p>`;
    box.querySelectorAll('[data-ta]').forEach(b => {
      b.onclick = () => taskAction(b.dataset.ta, b.closest('[data-tid]').dataset.tid);
    });
  }

  async function taskAction(what, tid) {
    const x = (T.data.tasks || []).find(t => t.id === tid);
    if (what === 'open') { stopTaskPoll(); return openBoard(tid); }
    if (what === 'assist') {  // 🤖 mở bảng của tác vụ + khung Trợ lý
      stopTaskPoll();
      if ((await openBoard(tid)) === false) return;
      return toggleAssist(true);
    }
    if (what === 'folder') return call('canvas_open_folder', tid);
    if (what === 'stop') { if (await call('canvas_task_cancel', tid)) toast('Đã dừng tác vụ', 'ok'); return refreshTasks(); }
    if (what === 'resume') { if (await call('canvas_task_resume', tid)) toast('Đã xếp hàng chạy tiếp', 'ok'); return refreshTasks(); }
    if (what === 'dup' && x) return taskDialog(x.flow, { name: `${x.name} (2)`, raw: x.raw });
    if (what === 'del') {
      if (!confirm(`Xoá tác vụ “${x ? x.name : tid}” và ảnh / video kết quả của nó?`)) return;
      if (await call('canvas_task_delete', tid)) toast('Đã xoá tác vụ', 'ok');
      return refreshTasks();
    }
  }

  function chooseFlow(flows) {
    return new Promise(resolve => {
      const box = document.createElement('div');
      box.className = 'cv-lightbox cv-import';
      box.innerHTML = `<div class="cv-import-box"><div class="cv-side-head"><b>Chọn flow để tạo tác vụ</b><button class="btn ghost sm" data-x type="button">✕</button></div>
        ${flows.map(f => `<button class="cv-import-row" data-f="${esc(f.id)}" type="button"><b>${esc(f.name)}</b><small class="muted">${f.nodes} khối · ${f.runs} lần chạy</small></button>`).join('')}</div>`;
      const done = v => { box.remove(); resolve(v); };
      box.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => done(''); });
      box.querySelectorAll('[data-f]').forEach(b => { b.onclick = () => done(b.dataset.f); });
      box.onclick = e => { if (e.target === box) done(''); };
      document.body.appendChild(box);
    });
  }

  /* ＋ tạo tác vụ: các ô “❓ Hỏi khi chạy” của flow (+ ảnh tải lên) → 1 tác vụ, hoặc hàng loạt: mỗi dòng của 1 ô = 1 tác vụ */
  async function taskDialog(bid, preset = {}) {
    const res = await call('canvas_open', bid);
    if (!res) return;
    const flow = res.board;
    const raw = preset.raw || {};
    const ar = await call('canvas_assist_get', bid);  // 🤖 Tự điều phối mặc định theo Trợ lý của flow
    const fauto = (ar && ar.chat && ar.chat.auto) || {};
    const nodes = flow.nodes.filter(n => n.ask || n.kind === 'upload');
    const prev = C.board;
    C.board = flow;  // fieldHtml / wspec đọc meta khối theo bảng đang mở
    const cfgOf = n => ({ ...(n.config || {}), ...((raw[n.id] || {}).config || {}) });
    const textFields = [];
    const block = n => {
      const head = `<div class="cv-ask-title"><b>${esc(n.title || nameOf(n))}</b> <small class="muted">${esc(n.id)} · ${esc(nameOf(n))}</small></div>`;
      if (n.kind === 'upload') {
        const file = (raw[n.id] || {}).file || '';
        return `<div class="cv-ask-block" data-tk-up="${esc(n.id)}" data-file="${esc(file)}">${head}
          <div class="row"><small class="muted" data-tk-fname>${file ? esc(file.split(/[\\/]/).pop()) : 'Dùng ảnh hiện tại của flow'}</small><span class="cv-sp"></span>
          <button class="btn ghost sm" data-tk-pick type="button">🖼 Chọn ảnh khác…</button></div></div>`;
      }
      if (n.kind !== 'wf') {
        if (askOn(n, 'prompt')) textFields.push([`${n.id}|prompt`, `${n.title || nameOf(n)} · Prompt`]);
        if (n.kind === 'video' && askOn(n, 'dialogue') && !n.dialogue_src) textFields.push([`${n.id}|dialogue`, `${n.title || nameOf(n)} · Lời thoại`]);
        return `<div class="cv-ask-block" data-tk-media="${esc(n.id)}">${head}
          ${askOn(n, 'prompt') ? `<textarea data-tk-prompt rows="2" placeholder="Prompt…">${esc((raw[n.id] || {}).prompt ?? n.prompt ?? '')}</textarea>` : ''}
          ${n.kind === 'video' && askOn(n, 'dialogue') && !n.dialogue_src ? `<textarea data-tk-dialogue rows="2" placeholder="Lời thoại…">${esc((raw[n.id] || {}).dialogue ?? n.dialogue ?? '')}</textarea>` : ''}</div>`;
      }
      const cfg = cfgOf(n);
      const fields = wspec(n).fields.filter(f => ASK_TYPES.includes(f.type) && f.key !== 'ask' && fieldVisible(f, cfg) && askOn(n, f.key));
      fields.filter(f => ['text', 'textarea'].includes(f.type)).forEach(f => textFields.push([`${n.id}|config.${f.key}`, `${n.title || nameOf(n)} · ${f.label}`]));
      return `<div class="cv-ask-block" data-tk-wf="${esc(n.id)}">${head}<div class="cv-wf-fields">${fields.map(f => fieldHtml(f, cfg)).join('') || '<small class="muted">Không có ô nào</small>'}</div></div>`;
    };
    const blocksHtml = nodes.map(block).join('');
    C.board = prev;
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import';
    box.innerHTML = `<div class="cv-import-box cv-ask-box"><div class="cv-side-head"><b>＋ Tạo tác vụ · ${esc(flow.name)}</b><button class="btn ghost sm" data-x type="button">✕</button></div>
      <p class="muted">Đầu vào riêng của tác vụ (các khối bật “❓ Hỏi khi chạy” + ảnh tải lên). Flow gốc giữ nguyên.</p>
      <label class="field"><span>Tên tác vụ (để trống = lấy giá trị ô đầu tiên)</span><input data-tk-name value="${esc(preset.name || '')}"></label>
      ${textFields.length ? `<details class="cv-task-batch"><summary>📚 Tạo hàng loạt — mỗi dòng 1 tác vụ</summary>
        <label class="field"><span>Ô thay đổi theo từng dòng</span><select data-tk-bfield>${textFields.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></label>
        <label class="field"><span>Mỗi dòng = 1 tác vụ (tối đa 50); các ô khác dùng chung giá trị bên dưới</span><textarea data-tk-lines rows="5" placeholder="VD:\nPHÂN BÓN KINGER 1\nPHÂN BÓN QUEEN 2"></textarea></label></details>` : ''}
      ${blocksHtml || '<p class="muted">Flow không có khối “❓ Hỏi khi chạy” — tác vụ chạy đúng như flow (bật “Hỏi khi chạy” ở khối để nhập đầu vào riêng).</p>'}
      <details class="cv-task-batch cv-task-autobox" ${fauto.on ? 'open' : ''}><summary>🤖 Tự điều phối ${fauto.on ? '<b>(đang bật theo flow)</b>' : ''}</summary>
        <p class="muted">Chạy xong → Claude chấm theo tiêu chí; khối chưa đạt được sửa prompt / cấu hình rồi chạy lại (không chạy lại khối Đăng bài / Quảng cáo), tới khi đạt hoặc hết số vòng. Mỗi vòng tốn 1 lượt Claude + lượt tạo lại ảnh / video.</p>
        <label class="cv-opt-check"><input type="checkbox" data-tk-auto ${fauto.on ? 'checked' : ''}> Bật tự điều phối cho tác vụ này</label>
        <label class="field"><span>Tiêu chí đạt *</span><textarea data-tk-crit rows="3" placeholder="VD: Ảnh đúng nhân vật + đúng bao bì sản phẩm, video 9:16 rõ nét, lời thoại đúng tên sản phẩm…">${esc(fauto.criteria || '')}</textarea></label>
        <div class="inline"><label class="field"><span>Điểm đạt (5–10)</span><input data-tk-pass type="number" min="5" max="10" step="0.5" value="${esc(fauto.pass_score ?? 8)}"></label>
          <label class="field"><span>Số vòng làm lại (1–3)</span><input data-tk-rounds type="number" min="1" max="3" value="${esc(fauto.rounds ?? 2)}"></label></div></details>
      <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn ghost sm" data-x type="button">Huỷ</button>
        <button class="btn primary sm" data-go type="button">＋ Tạo &amp; xếp hàng chạy</button></div></div>`;
    const close = () => box.remove();
    box.querySelectorAll('[data-x]').forEach(b => { b.onclick = close; });
    box.querySelectorAll('[data-tk-pick]').forEach(b => {
      b.onclick = async () => {
        const files = await api('pick_files', 'image');
        if (!files || !files.length) return;
        const blk = b.closest('[data-tk-up]');
        blk.dataset.file = files[0];
        blk.querySelector('[data-tk-fname]').textContent = files[0].split(/[\\/]/).pop();
      };
    });
    const linesEl = box.querySelector('[data-tk-lines]');
    const goBtn = box.querySelector('[data-go]');
    if (linesEl) linesEl.oninput = () => {
      const n = linesEl.value.split('\n').filter(x => x.trim()).length;
      goBtn.textContent = n > 1 ? `＋ Tạo ${Math.min(50, n)} tác vụ` : '＋ Tạo & xếp hàng chạy';
    };
    goBtn.onclick = async () => {
      const inputs = {};
      box.querySelectorAll('[data-tk-wf]').forEach(blk => {
        const config = {};
        blk.querySelectorAll('[data-c]').forEach(el => { config[el.dataset.c] = el.type === 'checkbox' ? el.checked : el.value; });
        inputs[blk.dataset.tkWf] = { config };
      });
      box.querySelectorAll('[data-tk-media]').forEach(blk => {
        const p = blk.querySelector('[data-tk-prompt]'), d = blk.querySelector('[data-tk-dialogue]');
        inputs[blk.dataset.tkMedia] = { ...(p ? { prompt: p.value } : {}), ...(d ? { dialogue: d.value } : {}) };
      });
      box.querySelectorAll('[data-tk-up]').forEach(blk => { if (blk.dataset.file) inputs[blk.dataset.tkUp] = { file: blk.dataset.file }; });
      const name = box.querySelector('[data-tk-name]').value.trim();
      const lines = linesEl ? linesEl.value.split('\n').map(x => x.trim()).filter(Boolean).slice(0, 50) : [];
      const autoOn = box.querySelector('[data-tk-auto]').checked;
      const auto = { on: autoOn, criteria: box.querySelector('[data-tk-crit]').value.trim(),
        pass_score: Number(box.querySelector('[data-tk-pass]').value) || 8, rounds: Number(box.querySelector('[data-tk-rounds]').value) || 2 };
      if (autoOn && !auto.criteria) { box.querySelector('[data-tk-crit]').focus(); return toast('Nhập tiêu chí đạt để bật tự điều phối', 'warn'); }
      let items = [{ name, inputs, auto }];
      if (lines.length) {
        const [nid, path] = box.querySelector('[data-tk-bfield]').value.split('|');
        items = lines.map(line => {
          const copy = JSON.parse(JSON.stringify(inputs));
          copy[nid] = copy[nid] || {};
          if (path.startsWith('config.')) copy[nid].config = { ...(copy[nid].config || {}), [path.slice(7)]: line };
          else copy[nid][path] = line;
          return { name: lines.length > 1 ? '' : name, inputs: copy, auto };
        });
      }
      goBtn.disabled = true;
      const out = await call('canvas_task_create', bid, items);
      goBtn.disabled = false;
      if (!out) return;
      close();
      toast(`Đã tạo ${out.created.length} tác vụ — chạy theo hàng đợi`, 'ok');
      tasksView(bid);
    };
    box.onclick = e => { if (e.target === box) close(); };
    document.body.appendChild(box);
  }

  async function modelsDialog() {
    const res = await call('fcanvas_models_get');
    if (!res) return;
    const ROWS = [['text', '✍ Viết / xử lý / viết prompt', 'Khối AI viết, Tra cứu web, Tạo content, Storyboard, Hậu kỳ… và nút Viết lại prompt'],
      ['image', '🖼 Tạo ảnh', 'Khối Ảnh (khung đầu, ảnh sản phẩm, góc nhân vật…)'],
      ['video', '🎬 Tạo video', 'Khối Video + cảnh Product Video Studio — mặc định Grok Imagine (6 / 10 / 15 giây)'],
      ['assist', '🤖 Điều phối (Trợ lý)', 'Trợ lý dựng quy trình, chấm kết quả, tự điều phối']];
    const m = res.models;
    const profOpts = (kind, cur) => {
      const model = m[kind];
      const site = ((res.options[kind] || []).find(o => o.value === model) || {}).site || '';
      const list = res.profiles.filter(p => !site || (p.sites || []).includes(site));
      return `<option value="">Tự chọn profile rảnh${site ? '' : ' (model API: không cần)'}</option>${list.map(p =>
        `<option value="${esc(p.id)}" ${p.id === cur ? 'selected' : ''}>👤 ${esc(p.name)}</option>`).join('')}`;
    };
    const box = document.createElement('div');
    box.className = 'cv-lightbox cv-import cv-models-dlg';
    const draw = () => {
      box.innerHTML = `<div class="cv-import-box cv-models-box"><div class="cv-side-head"><b>⚙ Model của Grok Canvas</b>
        <button class="btn ghost sm" data-x type="button">✕</button></div>
        <p class="muted">Mọi khối trên các bảng của màn này dùng các model dưới đây (khối không còn ô chọn model). Đổi model → khối chạy lại ở lần chạy sau.</p>
        ${ROWS.map(([k, label, hint]) => `<label class="field"><span>${esc(label)} <small class="muted">— ${esc(hint)}</small></span>
          <div class="inline set-model-row"><select data-m="${k}">${(res.options[k] || []).map(o => `<option value="${esc(o.value)}" ${o.value === m[k] ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>
          <select data-p="${k}">${profOpts(k, m[`${k}_profile`])}</select></div></label>`).join('')}
        <div class="row cv-run-foot"><span class="cv-sp"></span><button class="btn ghost sm" data-x type="button">Huỷ</button>
          <button class="btn primary sm" data-save type="button">Lưu</button></div></div>`;
      box.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => box.remove(); });
      box.querySelectorAll('[data-m]').forEach(s => { s.onchange = () => { m[s.dataset.m] = s.value; m[`${s.dataset.m}_profile`] = ''; draw(); }; });
      box.querySelectorAll('[data-p]').forEach(s => { s.onchange = () => { m[`${s.dataset.p}_profile`] = s.value; }; });
      box.querySelector('[data-save]').onclick = async () => {
        const values = {};
        ROWS.forEach(([k]) => { values[`fcanvas_model_${k}`] = m[k]; values[`fcanvas_profile_${k}`] = m[`${k}_profile`] || ''; });
        const saved = await call('fcanvas_models_save', values);
        if (!saved) return;
        box.remove();
        const meta = await call('canvas_meta');
        if (meta) C.meta = meta.meta;
        toast(`⚙ Đã lưu model: ${modelLine()}`, 'ok');
        if (C.board) { const r = await call('canvas_open', C.board.id); if (r) { C.board = r.board; renderBoard(); } } else listBoards();
      };
    };
    draw();
    box.onclick = e => { if (e.target === box) box.remove(); };
    document.body.appendChild(box);
  }
  document.addEventListener('click', e => {  // nút ⚙ Model (danh sách + thanh bảng) của màn này
    const b = FLOWSCREEN && e.target.closest && e.target.closest('[data-cv="models"]');
    if (b && body() && body().contains(b)) modelsDialog();
    const t = FLOWSCREEN && e.target.closest && e.target.closest('[data-tpl-lib]');  // 🎞 Thư viện mẫu video
    if (t && body() && body().contains(t)) templatesDialog(t.dataset.tplLib || '');
  });

  return { show, update, openBoard };
}
window.CanvasPage = createCanvasPage({ body: '#canvasBody', page: '#page-canvas', view: 'canvas', api: 'canvas_' });
window.FlowCanvasPage = createCanvasPage({ body: '#fcanvasBody', page: '#page-fcanvas', view: 'fcanvas', api: 'fcanvas_', flow: true });
