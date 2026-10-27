/* Thư viện hình ảnh — giống Thư viện video: lưới ảnh bên trái + khung xem lớn bên phải (thông tin, prompt, thao tác).
   Dữ liệu dùng chung với Tạo hình ảnh (api list_images → state.images). */
(function () {
  const PREF_KEY = 'va.imglib';
  const CHUNK = 80;
  const L = { q: '', engine: '', sort: 'new', tiles: [], shown: 0, sel: -1, more: null, sig: '' };

  try { Object.assign(L, JSON.parse(localStorage.getItem(PREF_KEY) || '{}')); } catch { /* bỏ qua */ }
  const savePref = () => { try { localStorage.setItem(PREF_KEY, JSON.stringify({ sort: L.sort, engine: L.engine })); } catch { /* bỏ qua */ } };

  const fold = t => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd');

  function filtered() {
    const k = fold(L.q.trim());
    let sets = (state.images || []).filter(s => (!L.engine || s.engine === L.engine)
      && (!k || fold(`${s.title} ${s.prompt} ${s.engine_name || s.engine}`).includes(k)));
    if (L.sort === 'old') sets = sets.slice().reverse();
    return sets.flatMap(set => set.files.map((file, i) => ({ set, file, i })));
  }

  function fillEngines() {
    const names = {};
    (state.images || []).forEach(s => { names[s.engine] = s.engine_name || s.engine; });
    if (L.engine && !names[L.engine]) L.engine = '';
    $('#ilEngine').innerHTML = '<option value="">Mọi model</option>'
      + Object.entries(names).map(([v, n]) => `<option value="${esc(v)}" ${v === L.engine ? 'selected' : ''}>${esc(n)}</option>`).join('');
    $('#ilSort').value = L.sort;
  }

  /** Vẽ lại lưới (giữ ảnh đang chọn nếu còn). */
  function render() {
    if (!$('#page-imglib')) return;
    const sets = state.images || [];
    const total = sets.reduce((n, s) => n + s.files.length, 0);
    $('#ilCount').textContent = `${sets.length} bộ ảnh · ${total} ảnh`;
    fillEngines();
    const keep = L.tiles[L.sel];
    L.tiles = filtered();
    const sig = L.tiles.map(t => t.file.url).join('|');
    const grid = $('#ilGrid');
    if (sig !== L.sig || !grid.firstChild) {
      L.sig = sig;
      if (L.more) L.more.disconnect();
      if (!L.tiles.length) {
        grid.innerHTML = `<div class="empty">${sets.length ? 'Không có ảnh khớp bộ lọc.' : 'Chưa có ảnh nào — bấm “+ Tạo ảnh” để bắt đầu.'}</div>`;
      } else {
        grid.innerHTML = '<div class="il-tiles"></div><div class="il-more" aria-hidden="true"></div>';
        L.shown = 0;
        append();
        L.more = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) append(); }, { root: grid, rootMargin: '500px' });
        L.more.observe($('.il-more', grid));
      }
    }
    $('#ilShown').textContent = L.tiles.length === total ? '' : `Đang lọc: ${L.tiles.length} ảnh`;
    const again = keep ? L.tiles.findIndex(t => t.file.url === keep.file.url) : -1;
    select(again >= 0 ? again : (L.tiles.length ? 0 : -1), false);
  }

  function append() {
    const box = $('#ilGrid .il-tiles');
    if (!box || L.shown >= L.tiles.length) return;
    const from = L.shown, to = Math.min(from + CHUNK, L.tiles.length);
    box.insertAdjacentHTML('beforeend', L.tiles.slice(from, to).map((t, j) => `
      <button class="il-tile ${from + j === L.sel ? 'active' : ''}" type="button" data-k="${from + j}" title="${esc(t.set.title)}">
        <img src="${esc(thumbUrl(t.file.url, 360))}" alt="" loading="lazy" decoding="async">
        ${t.set.files.length > 1 ? `<i class="img-count">${t.i + 1}/${t.set.files.length}</i>` : ''}
        <span class="il-tile-meta">${esc(t.set.engine_name || t.set.engine)} · ${esc(t.set.aspect || '')}</span>
      </button>`).join(''));
    L.shown = to;
    if (to >= L.tiles.length && L.more) L.more.disconnect();
  }

  function select(k, scroll = true) {
    while (k >= L.shown && L.shown < L.tiles.length) append();  // chọn bằng phím tới ảnh chưa vẽ → vẽ thêm
    L.sel = k;
    $$('#ilGrid .il-tile').forEach(el => el.classList.toggle('active', +el.dataset.k === k));
    const t = L.tiles[k];
    const pane = $('#ilView');
    if (!t) { pane.innerHTML = '<div class="empty">Chọn một ảnh để xem</div>'; return; }
    const set = t.set;
    pane.innerHTML = `
      <div class="il-stage">
        <button class="iv-nav prev" type="button" data-il-go="${k - 1}" ${k > 0 ? '' : 'disabled'} aria-label="Ảnh trước">‹</button>
        <img src="${esc(t.file.url)}" alt="" data-il-act="zoom" title="Bấm để xem lớn">
        <button class="iv-nav next" type="button" data-il-go="${k + 1}" ${k < L.tiles.length - 1 ? '' : 'disabled'} aria-label="Ảnh sau">›</button>
      </div>
      <div class="il-info">
        <b class="il-title" title="${esc(set.title)}">${esc(set.title)}</b>
        <div class="iv-meta"><span>🎨 ${esc(set.engine_name || set.engine)}</span><span>▭ ${esc(set.aspect || '')}</span>
          <span>🕒 ${esc(fmtTime(set.created_at))}</span>
          ${set.files.length > 1 ? `<span>🖼 ảnh ${t.i + 1}/${set.files.length} của bộ</span>` : ''}<span class="mono">${esc(t.file.name)}</span></div>
        <div class="iv-prompt"><b>Prompt</b><p>${esc(set.prompt || '—')}</p></div>
        <div class="il-actions">
          <button class="btn ghost sm" type="button" data-il-act="copy">⧉ Sao chép prompt</button>
          <button class="btn ghost sm" type="button" data-il-act="reuse">↻ Tạo lại với prompt này</button>
          <button class="btn ghost sm" type="button" data-il-act="folder">📂 Mở thư mục</button>
          <button class="btn danger sm" type="button" data-il-act="delete">🗑 Xoá bộ ảnh</button>
        </div>
      </div>`;
    if (scroll) {
      const el = $(`#ilGrid .il-tile[data-k="${k}"]`);
      if (el) el.scrollIntoView({ block: 'nearest' });
    }
  }

  async function act(name) {
    const t = L.tiles[L.sel];
    if (!t) return;
    const set = t.set;
    if (name === 'copy') { await navigator.clipboard.writeText(set.prompt || '').catch(() => {}); return toast('Đã sao chép prompt', 'ok'); }
    if (name === 'folder') return api('open_images_folder', set.id, t.file.name);
    if (name === 'zoom') {  // xem lớn (cửa sổ xem ảnh có ‹ › như màn Tạo hình ảnh)
      state.imgTiles = L.tiles;
      state.imgSig = '';  // lưới ở màn Tạo hình ảnh dựng lại danh sách của nó khi quay lại
      return openImageViewer(L.sel);
    }
    if (name === 'reuse') {  // mở Tạo hình ảnh với prompt + model của bộ ảnh này
      state.img.template = '';
      state.img.prompt = set.prompt || '';
      if (state.boot.image_engines[set.engine]) state.img.engine = set.engine;
      $('#imgTemplate').value = '';
      $('#imgEngine').value = state.img.engine;
      $('#imgPrompt').value = state.img.prompt;
      renderImageForm();
      saveImageForm();
      navigate('images');
      return toast('Đã điền prompt — chỉnh rồi bấm “Tạo ảnh”', 'ok');
    }
    if (name === 'delete' && await deleteImageSet(set.id)) toast('Đã xoá bộ ảnh', 'ok');
  }

  function init() {
    $('#ilSearch').oninput = e => { L.q = e.target.value; render(); };
    $('#ilEngine').onchange = e => { L.engine = e.target.value; savePref(); render(); };
    $('#ilSort').onchange = e => { L.sort = e.target.value; savePref(); render(); };
    $('#ilReload').onclick = () => refreshImages();
    $('#ilOpenRoot').onclick = () => api('open_images_folder', '');
    $('#ilNew').onclick = () => navigate('images');
    $('#ilGrid').onclick = e => { const b = e.target.closest('.il-tile'); if (b) select(+b.dataset.k); };
    $('#ilGrid').ondblclick = e => { if (e.target.closest('.il-tile')) act('zoom'); };
    $('#ilView').onclick = e => {
      const go = e.target.closest('[data-il-go]');
      if (go) return select(+go.dataset.ilGo);
      const a = e.target.closest('[data-il-act]');
      if (a) act(a.dataset.ilAct);
    };
    document.addEventListener('keydown', e => {  // ← → chuyển ảnh, Delete xoá (khi không gõ chữ, không mở hộp thoại)
      if (state.view !== 'imglib' || !$('#modal').classList.contains('hidden')) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return;
      if (e.key === 'ArrowLeft' && L.sel > 0) { e.preventDefault(); select(L.sel - 1); }
      if (e.key === 'ArrowRight' && L.sel < L.tiles.length - 1) { e.preventDefault(); select(L.sel + 1); }
      if (e.key === 'Delete') act('delete');
    });
  }

  async function show() {
    if (!L.inited) { init(); L.inited = true; }
    render();
    await refreshImages();  // refreshImages gọi lại render() khi đang ở màn này
  }

  window.ImageLibrary = { show, render };
})();
