/* Video nổi (popup) — đang xem video mà chuyển sang màn khác / đóng hộp thoại / đổi tab thì video tự thu về khung nổi góc
   màn hình, phát tiếp đúng chỗ. Theo dõi chung mọi <video> (không cần từng màn tự gọi): video đang phát mà bị gỡ khỏi trang
   hoặc bị ẩn → mở khung nổi. Bỏ qua video tắt tiếng không có thanh điều khiển (ảnh động xem trước). */
(() => {
  'use strict';
  let cur = null;     // { el, from: { view, tab } } — video trên trang đang phát
  let pop = null;     // khung nổi
  let timer = 0;

  const preview = el => el.muted && !el.controls;
  const watchable = el => el instanceof HTMLVideoElement && !el.closest('#miniVideo') && !preview(el);
  const shown = el => el.isConnected && el.getClientRects().length > 0 && !el.closest('.hidden');
  const where = () => ({
    view: typeof state !== 'undefined' ? state.view : '',
    tab: (document.querySelector('.mh-tab.on') || {}).dataset?.tab || '',
  });
  const label = from => {
    const item = from.view && document.querySelector(`.sb-item[data-view="${from.view}"]`);
    const name = item ? item.textContent.replace(/\s+/g, ' ').trim() : 'màn trước';
    const tab = from.view === 'mstudio' && from.tab ? document.querySelector(`.mh-tab[data-tab="${from.tab}"]`) : null;
    return tab ? `${name} · ${tab.textContent.trim()}` : name;
  };

  function track(el) {
    cur = { el, from: where() };
    clearInterval(timer);
    // màn bị ẩn (class / display:none) hay vẽ lại (video bị gỡ, trình duyệt tự dừng — sự kiện không tới document) → dò nhẹ
    timer = setInterval(check, 400);
  }
  function untrack() { cur = null; clearInterval(timer); timer = 0; }
  function check() {
    if (!cur) return;
    const { el } = cur;
    if (el.ended || (el.paused && el.isConnected)) return untrack();  // người dùng tự dừng / xem hết
    if (shown(el)) return;
    const now = where();
    if (now.view !== cur.from.view || now.tab !== cur.from.tab) return popOut(el, cur.from);  // đã sang màn / tab khác
    // vẫn ở màn cũ: LUÔN dừng video cũ trước (video chỉ bị ẩn vẫn phát tiếng — không còn nút nào để tắt)
    const src = el.currentSrc || el.src, time = el.currentTime;
    const detached = !el.isConnected;
    try { el.pause(); } catch { /* bỏ qua */ }
    untrack();
    if (!detached) return;  // bị ẩn (đóng khung / thu gọn) = người dùng thôi xem → không tự phát video khác
    // màn tự vẽ lại (video bị gỡ, thay bằng video mới cùng nguồn) → phát tiếp đúng chỗ trên video mới
    const again = [...document.querySelectorAll('video')].find(x => x !== el && watchable(x) && shown(x) && (x.currentSrc || x.src) === src);
    if (again) {
      try { again.currentTime = time; } catch { /* bỏ qua */ }
      again.play().catch(() => {});
    }
  }

  function popOut(el, from) {
    const src = el.currentSrc || el.src;
    const time = el.currentTime || 0;
    const ratio = el.videoWidth && el.videoHeight ? el.videoWidth / el.videoHeight : 16 / 9;
    untrack();
    if (!src) return;
    try { el.pause(); } catch { /* bỏ qua */ }
    open(src, time, from, ratio);
  }

  function open(src, time, from, ratio = 16 / 9) {
    close();
    pop = document.createElement('div');
    pop.id = 'miniVideo';
    pop.className = `mv ${ratio < 1 ? 'tall' : ''}`;
    pop.innerHTML = `<div class="mv-bar" title="Kéo để di chuyển"><span class="mv-ico">▶</span><b class="mv-from"></b>
        <button type="button" data-mv="back" title="Quay lại màn đang xem video">↩</button>
        ${document.pictureInPictureEnabled ? '<button type="button" data-mv="pip" title="Picture-in-Picture — nổi trên cả cửa sổ khác">⧉</button>' : ''}
        <button type="button" data-mv="close" title="Đóng">✕</button></div>
      <video controls playsinline></video>`;
    pop.querySelector('.mv-from').textContent = label(from || {});
    const v = pop.querySelector('video');
    v.addEventListener('loadedmetadata', () => {
      if (v.videoWidth && v.videoHeight) pop && pop.classList.toggle('tall', v.videoWidth < v.videoHeight);  // video dọc → khung hẹp
      try { v.currentTime = time || 0; } catch { /* bỏ qua */ } v.play().catch(() => {}); }, { once: true });
    v.src = src;
    pop._from = from || {};
    document.body.appendChild(pop);
    drag(pop, pop.querySelector('.mv-bar'));
    pop.addEventListener('click', e => {
      const b = e.target.closest('[data-mv]');
      if (!b) return;
      if (b.dataset.mv === 'close') close();
      else if (b.dataset.mv === 'pip') v.requestPictureInPicture().catch(err => toast(`Không mở được PiP: ${err.message}`, 'error'));
      else if (b.dataset.mv === 'back') goBack(pop._from, v.currentTime, src);
    });
  }

  function close() {
    if (!pop) return;
    const v = pop.querySelector('video');
    if (document.pictureInPictureElement === v) document.exitPictureInPicture().catch(() => {});
    v.pause(); v.removeAttribute('src'); v.load();
    pop.remove(); pop = null;
  }

  function goBack(from, time, src) {
    openScreen(from.view, from.tab);
    setTimeout(() => {
      // video gốc còn trên màn (vd. trình xem Kết quả) → đóng khung nổi, phát tiếp đúng chỗ; không còn (trình xem đã đóng,
      // màn vẽ lại) → giữ khung nổi phát tiếp
      const same = [...document.querySelectorAll('video')].find(x => watchable(x) && shown(x) && (x.currentSrc || x.src) === src);
      if (!same) return;
      const at = pop ? pop.querySelector('video').currentTime : time;
      close();
      try { same.currentTime = at; } catch { /* bỏ qua */ }
      same.play().catch(() => {});
    }, 300);
  }

  function drag(box, handle) {
    handle.addEventListener('pointerdown', e => {
      if (e.target.closest('button')) return;
      const r = box.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      handle.setPointerCapture(e.pointerId);
      const move = ev => {
        const x = Math.min(Math.max(0, ev.clientX - dx), innerWidth - r.width);
        const y = Math.min(Math.max(0, ev.clientY - dy), innerHeight - r.height);
        Object.assign(box.style, { left: `${x}px`, top: `${y}px`, right: 'auto', bottom: 'auto' });
      };
      const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
    });
  }

  // Chỉ 1 video có tiếng được phát cùng lúc: video nào bắt đầu phát → dừng mọi video khác đang phát, kể cả video "ma"
  // (đã bị gỡ khỏi trang / bị ẩn nhưng vẫn phát tiếng — trước đây phải tắt app mới hết).
  const playing = new Set();
  function stopOthers(keep) {
    for (const v of [...playing]) {
      if (v === keep) continue;
      try { v.pause(); } catch { /* bỏ qua */ }
      playing.delete(v);
    }
  }
  // play không nổi bọt → bắt ở pha capture trên document
  document.addEventListener('play', e => {
    const el = e.target;
    if (!(el instanceof HTMLVideoElement) || preview(el)) return;
    stopOthers(el);
    playing.add(el);
    if (!el._mvWatch) {  // gắn thẳng vào phần tử: sự kiện của video đã bị gỡ khỏi trang không tới document
      el._mvWatch = true;
      const done = () => playing.delete(el);
      el.addEventListener('pause', done);
      el.addEventListener('ended', done);
      el.addEventListener('emptied', done);
    }
    if (pop && el !== pop.querySelector('video')) pop.querySelector('video').pause();  // tránh 2 tiếng cùng lúc
    if (watchable(el)) track(el);
  }, true);

  // mở 1 màn (+ tab của Studio Muse AI). Màn Muse vẽ tab bất đồng bộ theo H.tab → đặt trước khi chuyển màn.
  function openScreen(view, tab = '') {
    if (!view || typeof navigate !== 'function') return;
    if (view === 'mstudio' && tab && window.MH && window.MH.H) {
      window.MH.H.tab = tab;
      try { localStorage.setItem('va.mhub.tab', tab); } catch { /* bỏ qua */ }
    }
    if (state.view !== view) navigate(view);
    const b = tab && document.querySelector(`.mh-tab[data-tab="${tab}"]`);
    if (b && !b.classList.contains('on')) b.click();
  }

  window.openScreen = openScreen;
  window.MiniVideo = { open, close };
})();
