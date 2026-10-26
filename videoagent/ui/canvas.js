/* Canvas — bảng node ảnh / video kiểu Kling Canvas.
   Node Ảnh: prompt → model ảnh (ảnh nối vào = ảnh tham chiếu để sửa / ghép). Node Video: ảnh nối vào = khung đầu → model video.
   Node Tải lên: ảnh của bạn. Kéo nền = di chuyển, cuộn = phóng to / thu nhỏ, kéo cổng ＋ sang node khác = nối. */
window.CanvasPage = (() => {
  const C = { meta: null, boards: [], board: null, sel: '', view: { x: 80, y: 60, k: 0.9 }, promptT: null };
  const body = () => $('#canvasBody');
  const KIND = { image: '🖼 Ảnh', video: '🎬 Video', upload: '⬆ Ảnh tải lên' };
  const STATUS = { queued: 'Đang chờ', running: 'Đang tạo', done: 'Xong', error: 'Lỗi', idle: '' };

  async function call(name, ...args) {
    try {
      const res = await api(name, ...args);
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

  async function listBoards() {
    const res = await call('canvas_list');
    C.boards = res ? res.boards : [];
    C.board = null;
    C.sel = '';
    body().innerHTML = `<div class="cv-home">
      <div class="cv-home-head"><div><h2>Canvas</h2><p class="muted">Bảng sáng tạo kiểu Kling: tạo ảnh bằng model ảnh của hệ thống, nối ảnh sang node Video để
        làm chuyển động, nối nhiều ảnh để sửa / ghép. Mỗi node chạy trong hàng đợi Tạo hình ảnh / Tạo video.</p></div>
        <button class="btn primary" data-cv="new">＋ Canvas mới</button></div>
      <div class="cv-grid">${C.boards.map(b => `<button class="cv-card" data-open="${esc(b.id)}">
        <span class="cv-card-thumb">${b.thumb ? `<img src="${esc(thumbUrl(b.thumb, 360))}" alt="">` : '<i>🎨</i>'}</span>
        <b>${esc(b.name)}</b><small class="muted">${b.nodes} node · ${esc(b.updated_at)}</small></button>`).join('')
        || '<p class="muted">Chưa có Canvas nào — bấm “＋ Canvas mới”.</p>'}</div></div>`;
    body().querySelector('[data-cv="new"]').onclick = createBoard;
    body().querySelectorAll('[data-open]').forEach(el => { el.onclick = () => openBoard(el.dataset.open); });
  }

  async function createBoard() {
    const res = await call('canvas_create', '');
    if (res) { C.board = res.board; C.view = { x: 80, y: 60, k: 0.9 }; renderBoard(); }
  }

  async function openBoard(bid) {
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
        <span class="cv-sp"></span>
        <button class="btn ghost sm" data-cv="folder" title="Mở thư mục lưu file của Canvas này">📁 Thư mục</button>
        <button class="btn ghost sm" data-cv="del" title="Xoá Canvas này">🗑 Xoá</button>
      </div>
      <div class="cv-stage" tabindex="0">
        <div class="cv-world"><svg class="cv-edges"></svg><div class="cv-nodes"></div></div>
        <div class="cv-tools hidden"></div>
        <div class="cv-menu hidden"></div>
        <div class="cv-empty ${b.nodes.length ? 'hidden' : ''}">
          <b>Bắt đầu Canvas</b><span class="muted">Thêm node Ảnh (viết prompt → tạo ảnh) hoặc tải ảnh của bạn lên, rồi nối sang node Video.</span>
          <div><button class="btn primary sm" data-add="image">🖼 Thêm ảnh</button> <button class="btn ghost sm" data-add="upload">⬆ Tải ảnh lên</button></div>
        </div>
      </div>
      <div class="cv-dock">
        <button data-add="image" title="Thêm node Ảnh (tạo ảnh từ prompt)">🖼<small>Ảnh</small></button>
        <button data-add="video" title="Thêm node Video (nối 1 ảnh vào làm khung đầu)">🎬<small>Video</small></button>
        <button data-add="upload" title="Tải ảnh trên máy lên">⬆<small>Tải lên</small></button>
        <button data-blocks title="Các khối như Workflow: Văn bản, AI viết, Tạo content, Ghép video, Video dài, Whiteboard, Đăng bài, Lên lịch, Quảng cáo">🧩<small>Khối</small></button>
        <span class="cv-dock-sep"></span>
        <button data-zoom="-" title="Thu nhỏ">−</button><span class="cv-zoom"></span><button data-zoom="+" title="Phóng to">＋</button>
        <button data-zoom="fit" title="Vừa khung — xem toàn bộ node">⤢</button>
      </div>
    </div>`;
    const root = body();
    root.querySelector('[data-cv="home"]').onclick = listBoards;
    root.querySelector('[data-cv="folder"]').onclick = () => call('canvas_open_folder', b.id);
    root.querySelector('[data-cv="del"]').onclick = deleteBoard;
    const name = root.querySelector('.cv-name');
    name.onchange = async () => { const res = await call('canvas_rename', b.id, name.value); if (res) C.board.name = res.board.name; };
    root.querySelectorAll('[data-add]').forEach(el => { el.onclick = () => addAt(el.dataset.add); });
    root.querySelector('[data-blocks]').onclick = e => { e.stopPropagation(); showBlocks(e.currentTarget); };
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
  const widthOf = n => (n.kind === 'wf' ? 300 : ratio(n) < 1 ? 340 : 230);
  const wspec = n => (n.kind === 'wf' ? C.meta.wf_types[n.wtype] : null);
  const nameOf = n => (n.kind === 'wf' ? `${wspec(n).icon} ${wspec(n).name}` : KIND[n.kind]);
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
        : out.text ? `<div class="cv-wf-text">${esc(out.text)}</div>`
          : cfgText ? `<div class="cv-wf-text muted">${esc(cfgText)}</div>`
            : `<div class="cv-ph">${busy ? `<div class="cv-spin"></div><b>${Math.round(n.pct || 0)}%</b><small>${esc(n.stage || STATUS[n.status])}</small>`
              : n.status === 'error' ? `<b>⚠ Lỗi</b><small>${esc(n.error || '')}</small>`
                : `<b>${esc(s.icon)}</b><small>${esc(s.desc)}</small>`}</div>`;
    const ins = s.inputs.map(p => TYPE_VI[p.type === 'any' ? 'images' : p.type] && p.label).filter(Boolean);
    return `<div class="cv-node-label"><span>${esc(nameOf(n))}</span>
        <em class="cv-st ${esc(n.status || '')}">${n.status === 'waiting' ? 'Chờ duyệt' : busy ? `${Math.round(n.pct || 0)}%` : esc(STATUS[n.status] || '')}</em></div>
      <div class="cv-media wf ${url ? 'has-video' : ''}">${body}${busy && (url || out.text) ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
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
          : n.kind === 'video' ? '<b>🎬</b><small>Nối 1 ảnh vào làm khung đầu,<br>viết chuyển động rồi bấm Tạo</small>'
            : '<b>🖼</b><small>Viết prompt rồi bấm Tạo</small>'}</div>`;
    const variants = (n.urls || []).length > 1 ? `<div class="cv-variants">${n.urls.map((u, i) =>
      `<img src="${esc(thumbUrl(u, 120))}" data-pick="${i}" class="${i === (n.pick || 0) ? 'on' : ''}" alt="" draggable="false">`).join('')}</div>` : '';
    return `<div class="cv-node-label"><span>${KIND[n.kind]}${n.title ? ` · ${esc(n.title)}` : ''}</span>
        <em class="cv-st ${esc(n.status || '')}">${busy ? `${Math.round(n.pct || 0)}%` : esc(STATUS[n.status] || '')}</em></div>
      <div class="cv-media" style="aspect-ratio:${1 / ratio(n)}">${media}${busy && url ? `<div class="cv-busy"><div class="cv-spin"></div>${Math.round(n.pct || 0)}%</div>` : ''}</div>
      ${n.status === 'error' && url ? `<div class="cv-err">⚠ ${esc(n.error || '')}</div>` : ''}
      ${variants}
      ${n.kind !== 'upload' ? '<button class="cv-port in" title="Ảnh nối vào (kéo từ cổng ＋ của ảnh khác sang đây)" type="button"></button>' : ''}
      ${n.kind !== 'video' ? '<button class="cv-port out" title="Kéo sang node khác để nối · bấm để tạo tiếp" type="button">＋</button>' : ''}`;
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
    el.className = `cv-node ${n.kind}${n.id === C.sel ? ' sel' : ''}${n.status === 'error' ? ' err' : ''}`;
    el.style.left = `${n.x}px`;
    el.style.top = `${n.y}px`;
    el.style.width = `${widthOf(n)}px`;
    el.innerHTML = nodeHtml(n);
    el.querySelectorAll('[data-pick]').forEach(img => {
      img.onpointerdown = e => e.stopPropagation();
      img.onclick = () => pick(n.id, Number(img.dataset.pick));
    });
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
    C.board.nodes.forEach(drawNode);
    root.querySelector('.cv-empty').classList.toggle('hidden', C.board.nodes.length > 0);
    root.querySelector('.cv-count').textContent = `${C.board.nodes.length} node`;
    applyView();
    drawEdges();
    drawPanel();
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
        if (a && b) paths.push(`<path class="cv-edge" data-edge="${esc(src)}>${esc(n.id)}" d="${curve(a, b)}"><title>Bấm để bỏ nối</title></path>`);
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

  /* ---------------------------------------------------------------- thanh công cụ + ô prompt của node đang chọn */
  function selectNode(id) {
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
        + `<label class="cv-opt-check" title="Tắt: mọi ảnh nối vào đều là ảnh tham chiếu (model tự dựng cảnh mới)"><input type="checkbox" data-f="first_frame" ${n.first_frame !== false ? 'checked' : ''}> Ảnh đầu làm khung mở đầu</label>`;
    }
    const spec = m.image_engines[n.engine] || Object.values(m.image_engines)[0];
    return sel('engine', Object.entries(m.image_engines).map(([k, v]) => [k, v.name]), n.engine, 'Model ảnh')
      + sel('aspect', spec.aspects.map(a => [a, a]), n.aspect, 'Tỉ lệ')
      + sel('count', spec.counts.map(c => [c, `${c} ảnh`]), n.count, 'Số ảnh mỗi lần');
  }

  function inputsNote(n) {
    const ins = (n.inputs || []).map(node).filter(Boolean);
    const pics = ins.filter(isPic);
    const texts = ins.filter(x => x.kind === 'wf' && outTypes(x).has('text') && !outTypes(x).has('video'));
    const textNote = texts.length ? ` · Chữ từ ${texts.map(x => `<b>${esc(x.id)}</b>`).join(', ')} được thêm vào đầu prompt` : '';
    if (n.kind === 'video') {
      // chia file giống backend (video_plan): ảnh đầu = khung mở đầu (nếu bật), ảnh sau = tham chiếu, 1 video tham chiếu
      const spec = C.meta.video_engines[n.engine] || {};
      const vids = ins.filter(x => outTypes(x).has('video'));
      let room = Math.max(1, spec.max_images || 1) - (vids.length ? 1 : 0);
      const list = [...pics];
      const first = list.length && n.first_frame !== false ? list.shift() : null;
      if (first) room -= 1;
      const refs = list.splice(0, Math.max(0, Math.min(5, room)));
      const b = x => `<b>${esc(x.id)}</b>`;
      const parts = [first ? `Khung đầu: ${b(first)}` : '', refs.length ? `Tham chiếu: ${refs.map(b).join(', ')}` : '',
        vids.length ? `Video tham chiếu: ${b(vids[0])}${spec.video_input ? '' : ' <i>(model này chỉ lấy 1 khung hình — nên chọn Grok / Dola)</i>'}` : '',
        list.length || vids.length > 1 ? `<span class="warn-text">Bỏ ${list.length + Math.max(0, vids.length - 1)} file thừa — ${esc(spec.name || '')} nhận tối đa ${spec.max_images} file</span>` : ''].filter(Boolean);
      return (parts.length ? parts.join(' · ') : '⚠ Chưa có file — kéo cổng ＋ của ảnh / video sang node này (nối được nhiều file)') + textNote;
    }
    return (pics.length ? `Ảnh tham chiếu: ${pics.map(x => `<b>${esc(x.id)}</b>`).join(', ')} — prompt nói rõ cần sửa / ghép gì`
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
      has ? '<button data-act="view" title="Xem lớn">⛶ Xem</button>' : '',
      has ? '<button data-act="download" title="Lưu file về máy">⬇ Tải về</button>' : '',
      n.kind === 'wf' && (n.out || {}).text ? '<button data-act="copy" title="Sao chép chữ kết quả">📋 Sao chép</button>' : '',
      n.kind !== 'upload' ? '<button data-act="dup" title="Nhân bản node (giữ prompt, model, nối)">⧉</button>' : '',
      busy ? '<button data-act="cancel" title="Dừng tạo">⏹ Dừng</button>' : '',
      '<button data-act="del" class="danger" title="Xoá node (phím Delete)">🗑</button>',
    ].join('');
    tools.classList.remove('hidden');
    tools.querySelectorAll('[data-act]').forEach(b => { b.onclick = () => act(b.dataset.act, n.id); });
    placeTools();
    // ô prompt dưới node (nằm trong world → kéo / zoom theo node)
    if (n.kind === 'upload') { if (panel) panel.remove(); return; }
    if (n.kind === 'wf') return drawWfPanel(n);
    if (!panel || panel.dataset.for !== n.id) {
      if (panel) panel.remove();
      panel = document.createElement('div');
      panel.className = 'cv-panel';
      panel.dataset.for = n.id;
      panel.onpointerdown = e => e.stopPropagation();
      panel.onwheel = e => e.stopPropagation();
      root.querySelector('.cv-nodes').appendChild(panel);
      panel.innerHTML = `<div class="cv-in-note"></div>
        <textarea placeholder="${n.kind === 'video' ? 'Mô tả chuyển động: người làm gì, máy quay thế nào (VD: cô gái mỉm cười giới thiệu sản phẩm, máy đứng yên)…'
          : 'Mô tả ảnh muốn tạo (VD: Ảnh đang livestream trên TikTok, có thiết bị và trưng bày các sản phẩm)…'}"></textarea>
        <div class="cv-panel-row"><div class="cv-opts"></div><span class="cv-sp"></span>
          <button class="btn ghost sm" data-p="enhance" title="Nhờ model chữ (Cài đặt → Model AI) viết lại prompt chi tiết hơn">✨</button>
          <button class="btn primary sm" data-p="go"></button></div>`;
      const ta = panel.querySelector('textarea');
      ta.value = n.prompt || '';
      ta.oninput = () => {
        const cur = node(n.id);
        if (cur) cur.prompt = ta.value;
        clearTimeout(C.promptT);
        C.promptT = setTimeout(() => call('canvas_update_nodes', C.board.id, [{ id: n.id, prompt: ta.value }]), 600);
      };
      ta.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(n.id); };
      panel.querySelector('[data-p="enhance"]').onclick = () => enhance(n.id);
      panel.querySelector('[data-p="go"]').onclick = () => (isBusy(node(n.id)) ? act('cancel', n.id) : generate(n.id));
      if (focus) setTimeout(() => ta.focus(), 30);
    }
    const ta = panel.querySelector('textarea');
    if (document.activeElement !== ta && ta.value !== (n.prompt || '')) ta.value = n.prompt || '';
    panel.querySelector('.cv-in-note').innerHTML = inputsNote(n) + (n.stage && !busy ? ` · <i>${esc(n.stage)}</i>` : '');
    panel.querySelector('.cv-opts').innerHTML = optionsHtml(n);
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
      panel.innerHTML = `<div class="cv-in-note">${esc(s.desc)}${ins.length ? `<br>Nhận từ: ${ins.map(x => `<b>${esc(x.id)}</b>`).join(', ')}` : s.inputs.length
          ? `<br>Nối vào: ${s.inputs.map(p => esc(p.label)).join(' · ')}` : ''}</div>
        <div class="cv-wf-fields">${s.fields.filter(f => fieldVisible(f, cfg)).map(f => fieldHtml(f, cfg)).join('')}</div>
        ${s.outputs.some(o => o.type === 'text') && (n.out || {}).text !== undefined && n.wtype !== 'input_text' ? `<label class="field"><span>Kết quả — sửa được trước khi dùng tiếp</span>
          <textarea data-out rows="6">${esc((n.out || {}).text || '')}</textarea></label>` : ''}
        ${['fb_post', 'fb_schedule'].includes(n.wtype) ? '<small class="muted">🔒 Luôn dừng chờ bạn bấm “Đồng ý đăng” trên node trước khi đăng.</small>' : ''}
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

  async function runWf(id) {
    clearTimeout(C.promptT);
    const n = node(id);
    const payload = { id, config: n.config || {} };
    if ((n.out || {}).text !== undefined) payload.out_text = n.out.text;
    await call('canvas_update_nodes', C.board.id, [payload]);
    if (['fb_post', 'fb_schedule', 'fb_ad'].includes(n.wtype)
      && !confirm(n.wtype === 'fb_ad' ? 'Tạo quảng cáo (trạng thái TẠM DỪNG, chưa tiêu tiền) cho bài viết nối vào?'
        : 'Chạy khối đăng bài? App sẽ dừng chờ bạn duyệt nội dung trước khi đăng.')) return;
    const res = await call('canvas_generate', C.board.id, id);
    if (res) { C.board = res.board; drawAll(); }
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
    const res = await call('canvas_update_nodes', C.board.id, [{ id, [key]: n[key] }]);
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
    const res = kind === 'upload' ? await call('canvas_upload', C.board.id, x, y)
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
    if (panel && panel.dataset.for === id) n.prompt = panel.querySelector('textarea').value;
    await call('canvas_update_nodes', C.board.id, [{ id, prompt: n.prompt || '' }]);
    const res = await call('canvas_generate', C.board.id, id);
    if (res) { C.board = res.board; drawAll(); }
  }

  async function enhance(id) {
    clearTimeout(C.promptT);
    const panel = body().querySelector('.cv-panel');
    if (panel && panel.dataset.for === id) await call('canvas_update_nodes', C.board.id, [{ id, prompt: panel.querySelector('textarea').value }]);
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
    video: [['vid-ref', '🎬 Video mới dùng video này làm tham chiếu'], ['wf:fb_post', '📣 Đăng bài Facebook'],
      ['wf:fb_schedule', '🗓 Lên lịch đăng'], ['wf:concat_video', '⧉ Ghép video']],
    text: [['img-from-text', '🖼 Ảnh từ chữ này (làm prompt)'], ['wf:ai_text', '✦ AI viết / xử lý tiếp'], ['wf:content_post', '📝 Tạo content bài viết'],
      ['wf:fb_post', '📣 Đăng bài (làm caption)'], ['wf:studio_video', '🎬 Video dài từ storyboard'], ['wf:whiteboard_video', '✍ Whiteboard']],
    post: [['wf:fb_ad', '🎯 Tạo quảng cáo (tạm dừng)']],
  };

  function showMenu(id, sx, sy) {
    const menu = body().querySelector('.cv-menu');
    const n = node(id);
    const ready = n.kind === 'wf' ? n.status === 'done' || n.wtype === 'input_text' : (n.urls || []).length > 0;
    const seen = new Set();
    const items = [...outTypes(n)].flatMap(t => NEXT[t] || []).filter(([k]) => !seen.has(k) && seen.add(k));
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
      return rows.length ? `<b>${esc(label)}</b>${rows.map(([k, s]) => `<button data-blk="${k}" title="${esc(s.desc)}">${esc(s.icon)} ${esc(s.name)}</button>`).join('')}` : '';
    }).join('');
    const stage = body().querySelector('.cv-stage').getBoundingClientRect();
    const r = anchorEl.getBoundingClientRect();
    menu.classList.remove('hidden');
    menu.style.left = `${r.left - stage.left - 40}px`;
    menu.style.top = `${Math.max(8, r.top - stage.top - menu.offsetHeight - 10)}px`;
    menu.querySelectorAll('[data-blk]').forEach(b => { b.onclick = () => { hideMenu(); addAt('wf', { wtype: b.dataset.blk }); }; });
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
    if (!stage || !C.board || !C.board.nodes.length) return;
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
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
      e.preventDefault();
      const r = stage.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
    };
    stage.onkeydown = e => {
      if (e.target !== stage) return;
      if ((e.key === 'Delete' || e.key === 'Backspace') && C.sel) act('del', C.sel);
      if (e.key === 'Escape') selectNode('');
    };
    stage.onpointerdown = e => {
      if (e.button !== 0 || e.target.closest('.cv-tools, .cv-menu, .cv-empty, .cv-panel')) return;
      hideMenu();
      const portEl = e.target.closest('.cv-port.out');
      const nodeEl = e.target.closest('.cv-node');
      if (portEl && nodeEl) return dragConnect(e, nodeEl.dataset.node);
      if (nodeEl) return dragNode(e, nodeEl.dataset.node);
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
      if (moved) call('canvas_update_nodes', C.board.id, [{ id, x: n.x, y: n.y }]);
      else if (C.sel !== id) selectNode(id);
      body().querySelector('.cv-stage').focus({ preventScroll: true });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
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

  /* ---------------------------------------------------------------- sự kiện từ backend */
  function update(event, data) {
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
      if (n.status === 'done' && before.status !== 'done') toast(`${nameOf(n)} ${n.id}: xong`, 'ok');
      if (n.status === 'idle' && before.status !== 'idle' && n.error) toast(`${nameOf(n)} ${n.id}: ${n.error}`);
    } else if (event === 'canvas_error' && data.message) {
      toast(`Canvas: ${data.message}`, 'error');
    }
  }

  return { show, update };
})();
