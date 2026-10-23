/* Studio Muse AI · tab LadiPage (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { METHODS, DURS, H, sceneLine } = MH;  // khai báo ở core.js
  const kForm = (...a) => MH.kForm(...a);  // ở script.js

  // ------------------------------------------------------------ tab LadiPage
  function renderLadi() {
    const L = H.ladi;
    const p = L.page;
    const step = n => (n === 1 ? 'on' : n === 2 ? (p ? 'on' : '') : n === 3 ? (L.scripts ? 'on' : '') : (L.checked.size ? 'on' : ''));
    $('#mhLadi').innerHTML = `<div class="card mh-ladihead"><b class="mh-h">🛒 Từ LadiPage ra kịch bản video</b>
        <small class="muted">Dán link landing page: lấy ảnh gốc, giá, nội dung và để Muse viết 3 kịch bản phân cảnh.</small>
        <div class="mh-steps">${['Dán link', 'Chọn ảnh sản phẩm', 'Sửa kịch bản, chọn cách làm', 'Đưa vào hàng đợi'].map((s, i) => `<span class="${step(i + 1)}"><i>${i + 1}</i>${s}</span>`).join('')}</div>
        <div class="mh-row"><input id="mhLadiUrl" value="${esc(L.url)}" placeholder="https://shop.vidu.vn/san-pham">
          <button class="btn primary" data-act="ladi-go" type="button" ${L.busy ? 'disabled' : ''}>${L.busy || '🔍 Quét và sinh kịch bản'}</button></div>
        ${L.busy ? '<small class="muted">Đang xử lý — đọc trang rồi nhờ Muse viết kịch bản (1–3 phút)…</small>' : ''}</div>
      ${p ? `<div class="card mh-ladiprod"><div class="mh-card-head"><b>${esc(p.name)}</b>${p.prices.length ? `<span class="mh-pill">${esc(p.prices.slice(0, 3).join(' · '))}</span>` : ''}
          <button class="link" data-act="ladi-text" type="button">${L.showText ? 'Ẩn' : 'Xem'} chữ gốc trên trang</button></div>
        ${L.showText ? `<pre class="mh-ladi-text">${esc(p.text)}</pre>` : ''}
        <span class="muted">Kho ảnh sản phẩm (${p.images.length}) — bấm chọn 1–3 ảnh rõ sản phẩm nhất (viền xanh). Ảnh được gửi kèm mọi video để Muse giữ đúng sản phẩm.</span>
        <div class="mh-ladiimgs">${p.images.map(u => `<button class="mh-limg ${L.picked.includes(u) ? 'on' : ''}" data-limg="${esc(u)}" type="button"><img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer"></button>`).join('')}
          ${L.local.map((im, i) => `<span class="mh-limg on local"><img src="${esc(im.url)}" alt=""><button data-lrm="${i}" type="button">✕</button></span>`).join('')}
          <button class="mh-add" data-act="ladi-add-img" type="button">＋ Ảnh từ máy</button></div></div>` : ''}
      ${L.scripts ? `<div class="card mh-ladiscripts"><div class="mh-card-head"><b>Kịch bản</b><small class="muted">sửa được lời thoại và hình từng cảnh trước khi đưa vào hàng đợi</small>
          <label class="mh-switch" title="Lời chốt không đọc số tiền, chỉ nói giá ưu đãi để ở link. Đổi là sinh lại kịch bản (mất chữ đã sửa)."><input type="checkbox" id="mhLadiNoPrice" ${L.noPrice ? 'checked' : ''}><i></i> Không đọc giá</label></div>
        <div class="mh-lscripts">${L.scripts.scripts.map((s, i) => `<div class="mh-lscript ${L.checked.has(i) ? 'on' : ''}">
            <label class="check"><input type="checkbox" data-lcheck="${i}" ${L.checked.has(i) ? 'checked' : ''}> <b>${esc(s.title)}</b></label>
            ${s.angle ? `<small class="muted">${esc(s.angle)}</small>` : ''}
            ${s.scenes.map((c, j) => `<div class="mh-lscene"><span>Cảnh ${j + 1}</span>
              <textarea data-lline="${i}:${j}" rows="2" placeholder="Lời thoại">${esc(c.line)}</textarea>
              <textarea data-lvis="${i}:${j}" rows="2" placeholder="Hình ảnh cảnh quay">${esc(c.visual)}</textarea></div>`).join('')}
          </div>`).join('')}</div>
        <small class="muted">Cách làm, tỉ lệ, thời lượng, giọng đọc, người dẫn, nhạc nền lấy theo thiết lập ở tab <button class="link" data-tab-go="script" type="button">Kịch bản</button>
          (${esc((METHODS.find(m => m[0] === H.k.method) || METHODS[0])[1].split(' ·')[0])} · ${esc(H.k.ratio)} · ${esc((DURS.find(d => d[0] === H.k.duration) || DURS[4])[1].split(' ·')[0])}).</small>
        <div class="mh-row"><button class="btn ghost" data-act="ladi-preview" type="button" ${L.checked.size ? '' : 'disabled'}>👁 Xem lệnh sẽ gửi Muse</button>
          <button class="btn ghost sm" data-act="ladi-all" type="button">Tích cả</button>
          <button class="btn primary" data-act="ladi-queue" type="button" ${L.checked.size ? '' : 'disabled'}>＋ Đưa ${L.checked.size} kịch bản đã tích vào hàng đợi</button></div></div>` : ''}`;
  }
  async function ladiImages() {  // ảnh đã chọn trên trang → tải về máy; + ảnh từ máy
    const L = H.ladi;
    let web = [];
    if (L.picked.length) {
      const r = await api('mhub_ladi_images', L.picked);
      if (!r.ok) { toast(r.error, 'error'); return null; }
      web = r.images;
    }
    return [...web, ...L.local].slice(0, H.s.max_images);
  }
  async function ladiForms(dry) {
    const L = H.ladi;
    const imgs = await ladiImages();
    if (imgs === null) return null;
    return [...L.checked].sort().map(i => {
      const s = L.scripts.scripts[i];
      return { ...kForm(), mode: 'script', product_images: [], images: imgs.map(x => x.path), title: `${L.scripts.name || L.page.name} · ${s.title}`,
        text: s.scenes.map(sceneLine).join('\n'), dry };
    });
  }
  async function ladiGenerate() {
    const L = H.ladi;
    L.busy = 'Đang đọc trang…'; renderLadi();
    let r = await api('mhub_ladi_fetch', L.url);
    if (!r.ok) { L.busy = ''; renderLadi(); return toast(r.error, 'error'); }
    L.page = r.page; L.picked = r.page.images.slice(0, 2); L.scripts = null; L.checked = new Set();
    L.busy = 'Muse đang viết kịch bản…'; renderLadi();
    const secs = H.k.duration === 'per_scene' ? 30 : +H.k.duration;
    r = await api('mhub_ladi_scripts', L.page, L.noPrice, Math.max(2, Math.min(6, Math.round(secs / 10))), secs, '', !!H.s.settings.show_browser);
    L.busy = '';
    if (!r.ok) { renderLadi(); return toast(r.error, 'error'); }
    L.scripts = r.result;
    L.checked = new Set(L.scripts.scripts.map((_, i) => i));
    renderLadi();
  }

  Object.assign(MH, { renderLadi, ladiImages, ladiForms, ladiGenerate });
})();
