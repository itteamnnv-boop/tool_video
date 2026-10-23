/* Studio Muse AI · tab Video mẫu (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { METHODS, DURS, H, sel, mmss, nearestDur, CLOSE, sceneLine } = MH;  // khai báo ở core.js
  const kForm = (...a) => MH.kForm(...a);  // ở script.js

  function renderSample() {
    const M = H.smp;
    const s = M.sample;
    const step = n => (n === 1 ? 'on' : n === 2 ? (s ? 'on' : '') : n === 3 ? (M.scripts ? 'on' : '') : (M.checked.size ? 'on' : ''));
    const chip = (t, cls = '') => `<span class="mh-pill ${cls}">${t}</span>`;
    $('#mhSample').innerHTML = `<div class="card mh-ladihead"><b class="mh-h">📹 Tạo video từ video mẫu</b>
        <small class="muted">Chọn video mẫu (file trên máy hoặc link TikTok / YouTube / Facebook…). App tự cắt khung đổi cảnh, rồi Muse phân tích và viết kịch bản tương tự cho nội dung của bạn.</small>
        <div class="mh-steps">${['Chọn video mẫu', 'Đổi nội dung, đính kèm', 'Sửa kịch bản', 'Đưa vào hàng đợi'].map((x, i) => `<span class="${step(i + 1)}"><i>${i + 1}</i>${x}</span>`).join('')}</div>
        <div class="mh-row"><input id="mhSmpUrl" value="${esc(M.source)}" placeholder="Dán link video mẫu, hoặc bấm Chọn file">
          <button class="btn ghost" data-act="smp-pick" type="button" ${M.busy ? 'disabled' : ''}>📂 Chọn file</button>
          <button class="btn primary" data-act="smp-go" type="button" ${M.busy ? 'disabled' : ''}>${M.busy && !s ? esc(M.busy) : '🔍 Phân tích video'}</button></div>
        ${M.busy ? `<small class="muted">${esc(M.busy)}</small>` : ''}</div>
      ${s ? `<div class="card mk-form smp-form">
        <div class="mk-left">
          <div class="mh-card-head"><b>${esc(s.title)}</b><button class="link" data-act="smp-sheet" type="button">${M.showSheet ? 'Xem từng khung' : 'Xem ảnh lưới gửi Muse'}</button></div>
          <div class="smp-chips">${chip(`${Math.round(s.duration)} giây`)}${chip(esc(s.ratio))}${chip(`${s.cuts} lần cắt cảnh`)}${chip(`~${s.avg_shot}s / cảnh`)}
            ${chip(s.has_audio ? 'Có tiếng' : 'Không tiếng')}${s.subtitles ? chip('Có phụ đề', 'ok') : ''}</div>
          ${M.showSheet ? `<img class="smp-sheet" src="${esc(s.sheet_url)}" alt="" data-zoom="${esc(s.sheet_url)}">`
            : `<div class="smp-frames ${s.height > s.width ? 'vert' : ''}">${s.frames.map(f => `<button class="smp-frame" data-zoom="${esc(f.url)}" type="button"><img src="${esc(f.url)}" alt="" loading="lazy"><span>${mmss(f.t * 1000)}</span></button>`).join('')}</div>`}
        </div>
        <div class="mk-left">
          <label class="field"><span>Nội dung mới <small class="muted">— đổi gì so với video mẫu: sản phẩm, thông điệp, đối tượng, ưu đãi…</small></span>
            <textarea id="mhSmpChange" rows="4" placeholder="VD: Đổi thành quảng cáo phân bón hữu cơ Boss 1 cho bà con trồng lúa miền Tây. Nhấn mạnh lúa xanh, chắc hạt. Người dẫn nữ, giọng miền Nam.">${esc(M.change)}</textarea></label>
          <label class="field"><span>Lời thoại video mẫu <small class="muted">(tuỳ chọn${s.subtitles ? ' — đã lấy phụ đề từ link' : ' — dán vào để Muse hiểu rõ hơn'})</small></span>
            <textarea id="mhSmpTranscript" rows="2" placeholder="${s.subtitles ? 'Để trống = dùng phụ đề lấy từ link' : 'Dán lời thoại / chữ trên video mẫu nếu có'}">${esc(M.transcript)}</textarea></label>
          <div class="smp-opts">
            <label class="field"><span>Mức bám mẫu</span>${sel('mhSmpClose', CLOSE, M.closeness)}</label>
            <label class="field"><span>Số kịch bản</span>${sel('mhSmpCount', [['1', '1'], ['2', '2'], ['3', '3']], M.count)}</label>
            <label class="field"><span>Số cảnh / video</span>${sel('mhSmpScenes', [2, 3, 4, 5, 6, 8].map(n => [String(n), `${n} cảnh`]), M.scenes)}</label>
          </div>
          <div class="smp-attach">
            <div class="smp-att"><b>Ảnh sản phẩm / nhân vật <small class="muted">(≤2 — gửi kèm Muse và mọi video)</small></b>
              <div class="mh-thumbs">${M.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt="" title="${esc(im.name || '')}"><button data-srm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
                ${M.images.length < 2 ? '<button class="mh-add" data-act="smp-add-img" type="button">＋ Ảnh</button>' : ''}</div></div>
            <div class="smp-att"><b>Tài liệu <small class="muted">(.txt .md .csv .docx .srt — thông tin sản phẩm, kịch bản thô…)</small></b>
              <div class="smp-docs">${M.docs.map((d, i) => `<span class="smp-doc" title="${esc(d.preview)}">📄 ${esc(d.name)} <small>${d.chars.toLocaleString('vi-VN')} ký tự</small><button data-sdoc-rm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
                ${M.docs.length < 5 ? '<button class="btn ghost sm" data-act="smp-add-doc" type="button">＋ Tài liệu</button>' : ''}</div></div>
          </div>
          <div class="smp-go"><label class="mh-switch" title="Lời chốt không đọc số tiền, chỉ nói giá ưu đãi để ở link"><input type="checkbox" id="mhSmpNoPrice" ${M.noPrice ? 'checked' : ''}><i></i> Không đọc giá</label>
            <button class="btn primary" data-act="smp-write" type="button" ${M.busy ? 'disabled' : ''}>${M.busy && s ? esc(M.busy) : '✦ Muse phân tích & viết kịch bản'}</button></div>
        </div></div>` : ''}
      ${M.scripts ? `<div class="card mh-ladiscripts">
        ${M.analysis ? `<details class="smp-analysis" ${M.openAnalysis ? 'open' : ''}><summary><b>Muse phân tích video mẫu</b> <small class="muted">bấm để xem / ẩn</small></summary><pre class="mh-ladi-text">${esc(M.analysis)}</pre></details>` : ''}
        <div class="mh-card-head"><b>Kịch bản mới</b><small class="muted">sửa được lời thoại và hình từng cảnh trước khi đưa vào hàng đợi</small></div>
        <div class="mh-lscripts">${M.scripts.scripts.map((x, i) => `<div class="mh-lscript ${M.checked.has(i) ? 'on' : ''}">
            <label class="check"><input type="checkbox" data-scheck="${i}" ${M.checked.has(i) ? 'checked' : ''}> <b>${esc(x.title)}</b></label>
            ${x.angle ? `<small class="muted">${esc(x.angle)}</small>` : ''}
            ${x.scenes.map((c, j) => `<div class="mh-lscene"><span>Cảnh ${j + 1}</span>
              <textarea data-sline="${i}:${j}" rows="2" placeholder="Lời thoại">${esc(c.line)}</textarea>
              <textarea data-svis="${i}:${j}" rows="2" placeholder="Hình ảnh cảnh quay">${esc(c.visual)}</textarea></div>`).join('')}
          </div>`).join('')}</div>
        <div class="smp-queue">
          <label class="field"><span>Tỉ lệ <small class="muted">(theo video mẫu)</small></span>${sel('mhSmpRatio', [['9:16', '9:16 · Dọc'], ['16:9', '16:9 · Ngang'], ['1:1', '1:1 · Vuông']], M.ratio)}</label>
          <label class="field"><span>Thời lượng <small class="muted">(gần video mẫu)</small></span>${sel('mhSmpDur', DURS, M.duration)}</label>
          <small class="muted smp-note">Cách làm, giọng đọc, người dẫn, nhạc nền theo tab <button class="link" data-tab-go="script" type="button">Kịch bản</button>
            (${esc((METHODS.find(m => m[0] === H.k.method) || METHODS[0])[1].split(' ·')[0])}).</small>
          <span class="mh-top-sp"></span>
          <button class="btn ghost sm" data-act="smp-all" type="button">Tích cả</button>
          <button class="btn ghost" data-act="smp-preview" type="button" ${M.checked.size ? '' : 'disabled'}>Xem lệnh</button>
          <button class="btn primary" data-act="smp-queue" type="button" ${M.checked.size ? '' : 'disabled'}>＋ Đưa ${M.checked.size} kịch bản vào hàng đợi</button></div></div>` : ''}`;
  }
  async function samplePrepare(source) {
    const M = H.smp;
    if (!String(source || '').trim()) return toast('Dán link video mẫu hoặc chọn file', 'warn');
    M.source = source; M.busy = 'Đang lấy video và cắt khung hình…'; renderSample();
    const r = await api('mhub_sample_prepare', source);
    M.busy = '';
    if (!r.ok) { renderSample(); return toast(r.error, 'error'); }
    M.sample = r.sample; M.scripts = null; M.analysis = ''; M.checked = new Set();
    M.ratio = r.sample.ratio; M.duration = nearestDur(r.sample.duration);
    M.scenes = String([2, 3, 4, 5, 6, 8].reduce((b, n) => (Math.abs(n - (r.sample.cuts + 1)) < Math.abs(b - (r.sample.cuts + 1)) ? n : b), 3));
    renderSample();
  }
  async function sampleWrite() {
    const M = H.smp;
    if (!M.change.trim() && !M.docs.length) return toast('Nhập nội dung mới hoặc đính kèm tài liệu', 'warn');
    if (M.scripts && !confirm('Viết lại kịch bản (mất chữ đã sửa)?')) return;
    M.busy = 'Muse đang xem video mẫu và viết kịch bản (1–3 phút)…'; renderSample();
    const secs = M.duration === 'per_scene' ? +M.scenes * 10 : +M.duration;
    const r = await api('mhub_sample_scripts', M.sample.id, { change: M.change, transcript: M.transcript, closeness: M.closeness,
      count: +M.count, scenes: +M.scenes, seconds: secs, no_price: M.noPrice, images: M.images.map(i => i.path), docs: M.docs.map(d => d.path) },
      '', !!H.s.settings.show_browser);
    M.busy = '';
    if (!r.ok) { renderSample(); return toast(r.error, 'error'); }
    M.scripts = r.result; M.analysis = r.result.analysis || ''; M.openAnalysis = true;
    M.checked = new Set(M.scripts.scripts.map((_, i) => i));
    renderSample();
  }
  function sampleForms(dry) {
    const M = H.smp;
    return [...M.checked].sort().map(i => {
      const x = M.scripts.scripts[i];
      return { ...kForm(), mode: 'script', ratio: M.ratio, duration: M.duration, product_images: [], images: M.images.map(im => im.path),
        title: `${M.scripts.name || M.sample.title} · ${x.title}`, text: x.scenes.map(sceneLine).join('\n'), dry };
    });
  }

  Object.assign(MH, { renderSample, samplePrepare, sampleWrite, sampleForms });
})();
