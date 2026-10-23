/* Studio Muse AI · tab Tư liệu + hộp thoại nhân vật / mẫu prompt / dự án (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, proj, nameHit } = MH;  // khai báo ở core.js
  // hàm ở file khác — gọi qua MH lúc chạy
  const renderAll = (...a) => MH.renderAll(...a);

  // người mẫu cố định: ảnh tải riêng, hoặc ảnh của 1 nhân vật được chọn (s.model.character)
  const modelHero = () => H.s.characters.find(ch => ch.id && ch.id === H.s.model.character) || null;
  const modelImages = () => { const h = modelHero(); return h ? h.images : H.s.model.images; };
  function assetPlan(text) {
    const s = H.s, out = [], hero = modelHero();
    const push = (im, src) => { if (im && !out.some(x => x.path === im.path)) out.push({ ...im, src }); };
    if (s.model.on) modelImages().forEach(im => push(im, hero ? `Người mẫu · ${hero.name}` : 'Người mẫu'));
    const named = text.trim() ? s.characters.filter(ch => ch.name && nameHit(ch.name, text)) : [];
    named.forEach(ch => ch.images.forEach(im => push(im, ch.name)));
    if (s.rotate.on && s.rotate.images.length) push(s.rotate.images[(s.rotate.idx || 0) % s.rotate.images.length], 'Luân phiên');
    return { all: out, sent: out.slice(0, s.max_images), dropped: out.slice(s.max_images), named };
  }
  function renderAssetTry() {
    const el = $('#mhATry');
    if (!el) return;
    const s = H.s, max = s.max_images;
    const p = assetPlan(H.atry || '');
    const fixed = s.model.on ? Math.min(max, modelImages().length) : 0;  // người mẫu cố định luôn đứng đầu
    const free = Math.max(0, max - fixed);
    el.innerHTML = `<div class="ma-slots">${Array.from({ length: max }, (_, i) => {
        const im = p.sent[i];
        return im ? `<figure class="ma-slot on"><img src="${esc(im.url)}" alt=""><figcaption><b>${i + 1}</b> ${esc(im.src)}</figcaption></figure>`
          : `<figure class="ma-slot"><span>${i + 1}</span><figcaption>${H.atry ? 'trống — cho ảnh tham chiếu của task' : 'còn trống'}</figcaption></figure>`;
      }).join('')}</div>
      <div class="ma-notes">
        ${p.named.length ? `<span class="ma-ok">✓ Nhận ra nhân vật: ${p.named.map(c => `<b>${esc(c.name)}</b>`).join(', ')}</span>` : (H.atry ? '<span class="muted">Không thấy tên nhân vật nào trong câu thử</span>' : '')}
        ${p.dropped.length ? `<span class="ma-warn">⚠ Muse nhận tối đa ${max} ảnh — ${p.dropped.length} ảnh bị bỏ (${p.dropped.map(x => esc(x.src)).join(', ')})</span>` : ''}
        ${!free ? `<span class="ma-warn">⚠ Người mẫu cố định đã dùng hết ${max} chỗ — ảnh nhân vật, ảnh luân phiên, ảnh tham chiếu của task sẽ không được gửi. Giảm ảnh người mẫu hoặc tắt.</span>`
          : `<span class="muted">${fixed ? `Người mẫu cố định luôn chiếm ${fixed}/${max} chỗ · ` : ''}${free} chỗ còn lại dành lần lượt cho nhân vật → ảnh luân phiên → ảnh tham chiếu của task</span>`}
      </div>`;
  }
  function renderAssets() {
    const s = H.s, max = s.max_images;
    const q = (H.aq || '').trim().toLowerCase();
    const chars = s.characters.filter(ch => !q || ch.name.toLowerCase().includes(q));
    const tpls = s.templates.filter(t => !q || `${t.name} ${t.text}`.toLowerCase().includes(q));
    const nextRot = s.rotate.images.length ? (s.rotate.idx || 0) % s.rotate.images.length : -1;
    const hero = modelHero();
    // nguồn người mẫu: ảnh tải riêng hoặc 1 nhân vật (ảnh nhân vật chỉ xem ở đây — sửa ở thẻ nhân vật)
    const modelSrc = () => `<div class="ma-msrc"><small class="muted">Nguồn</small>
        <button type="button" class="ma-msrc-b ${hero ? '' : 'on'}" data-model-char="">🖼 Ảnh tải lên</button>
        ${s.characters.map(ch => `<button type="button" class="ma-msrc-b ${hero && hero.id === ch.id ? 'on' : ''}" data-model-char="${esc(ch.id)}" title="Dùng nhân vật ${esc(ch.name)} làm người mẫu">${ch.images[0] ? `<img src="${esc(ch.images[0].url)}" alt="">` : '🧑'}${esc(ch.name)}</button>`).join('')}
        ${s.characters.length ? '' : '<small class="muted">· tạo nhân vật bên trái để chọn làm người mẫu</small>'}</div>`;
    const pool = (kind, list, cap, title, desc, icon, locked = false) => `<section class="card ma-pool ${s[kind].on ? 'on' : ''}" ${locked ? '' : `data-asset-drop="${kind}"`}>
        <div class="ma-poolhead"><span class="ma-ico">${icon}</span><div><b>${title}</b><small class="muted">${desc}</small></div>
          <label class="mh-switch"><input type="checkbox" data-hub-toggle="${kind}" ${s[kind].on ? 'checked' : ''}><i></i><span class="ma-state">${s[kind].on ? 'Đang bật' : 'Tắt'}</span></label></div>
        ${kind === 'model' ? modelSrc() : ''}
        <div class="ma-imgs">${list.map((im, i) => `<span class="ma-img ${kind === 'rotate' && i === nextRot && s.rotate.on ? 'next' : ''}" data-zoom="${esc(im.url)}">
            <img src="${esc(thumbUrl(im.url, 200))}" alt="" loading="lazy"><i>${i + 1}</i>${kind === 'rotate' && i === nextRot && s.rotate.on ? '<em>Kế tiếp</em>' : ''}
            ${locked ? '' : `<button data-asset-rm="${kind}" data-i="${i}" type="button" title="Bỏ ảnh">✕</button>`}</span>`).join('')}
          ${locked ? (list.length ? '' : '<span class="muted ma-empty">Nhân vật này chưa có ảnh</span>')
            : list.length < cap ? `<button class="ma-add" data-asset-add="${kind}" type="button"><b>＋</b><small>Thêm ảnh<br>hoặc kéo thả</small></button>` : ''}</div>
        <small class="muted ma-count">${locked ? `Ảnh của nhân vật <b>${esc(hero.name)}</b> · ${list.length} ảnh · sửa ở thẻ nhân vật`
          : `${list.length}/${cap} ảnh`}${kind === 'model' ? ' · gắn vào MỌI lệnh khi bật' : ' · mỗi lệnh lấy 1 ảnh kế tiếp, xoay vòng'}</small></section>`;
    $('#mhAssets').innerHTML = `
      <section class="card ma-head">
        <div class="ma-headl"><b class="mh-h">Ảnh gửi kèm mỗi lệnh Muse</b>
          <small class="muted">Muse nhận tối đa ${max} ảnh / lệnh, lấy theo thứ tự ưu tiên:</small>
          <div class="ma-order"><span class="${s.model.on ? 'on' : ''}">① Người mẫu cố định</span><span>② Nhân vật có tên trong prompt</span>
            <span class="${s.rotate.on ? 'on' : ''}">③ Ảnh luân phiên</span><span>④ Ảnh tham chiếu của task</span></div>
          <label class="field ma-try"><span>Thử prompt — xem ảnh nào sẽ được gửi kèm</span>
            <input id="mhATryIn" value="${esc(H.atry || '')}" placeholder="VD: ${esc((s.characters[0] || {}).name || 'Lan')} cầm bao phân bón trên cánh đồng lúa"></label></div>
        <div class="ma-headr" id="mhATry"></div>
      </section>
      <div class="ma-grid">
        <div class="ma-col">
          <section class="card ma-sec"><div class="ma-sechead"><b>🧑 Nhân vật</b><small class="muted">${s.characters.length} nhân vật · gõ đúng tên trong prompt → tự gắn ảnh (≤ 3 ảnh / nhân vật)</small>
              <span class="mh-top-sp"></span>${s.characters.length + s.templates.length > 6 ? `<input id="mhAq" type="search" value="${esc(H.aq || '')}" placeholder="🔍 Tìm nhân vật / mẫu…">` : ''}</div>
            <div class="ma-chars">${chars.map(ch => `<div class="ma-char">
                <button class="ma-cover" type="button" data-char-edit="${esc(ch.id)}" title="Sửa nhân vật">${ch.images[0] ? `<img src="${esc(ch.images[0].url)}" alt="">` : '<span>🧑</span>'}
                  ${ch.images.length > 1 ? `<span class="ma-mini">${ch.images.slice(1).map(im => `<img src="${esc(im.url)}" alt="">`).join('')}</span>` : ''}</button>
                <div class="ma-cbody"><b title="${esc(ch.name)}">${esc(ch.name)}</b><small class="muted">${ch.images.length ? `${ch.images.length} ảnh` : '⚠ chưa có ảnh'}</small>
                  <button class="ma-chip" data-char-copy="${esc(ch.name)}" type="button" title="Sao chép tên để gõ vào prompt">⧉ ${esc(ch.name)}</button></div>
                <div class="ma-acts">${hero && hero.id === ch.id
                    ? '<button class="btn ghost sm ma-hero on" data-model-char="" type="button" title="Đang là người mẫu cố định — bấm để bỏ">👤 Người mẫu</button>'
                    : `<button class="btn ghost sm ma-hero" data-model-char="${esc(ch.id)}" type="button" title="Dùng nhân vật này làm người mẫu cố định (gắn vào mọi lệnh)">👤 Làm người mẫu</button>`}
                  <button class="btn ghost sm" data-char-edit="${esc(ch.id)}" type="button">Sửa</button>
                  <button class="btn ghost sm st-pdel" data-char-del="${esc(ch.id)}" type="button" title="Xoá nhân vật">🗑</button></div></div>`).join('')}
              <button class="ma-new" data-act="char-new" type="button"><b>＋</b>Nhân vật mới<small>tên + tối đa 3 ảnh khuôn mặt</small></button></div></section>
          <section class="card ma-sec"><div class="ma-sechead"><b>📝 Mẫu prompt</b><small class="muted">${s.templates.length} mẫu · dùng nhanh ở tab Studio</small></div>
            <div class="ma-tpls">${tpls.map(t => {
                const who = s.characters.filter(ch => ch.name && nameHit(ch.name, t.text));
                return `<div class="ma-tpl"><div class="ma-tbody"><b>${esc(t.name)}</b><p>${esc(t.text)}</p>
                  ${who.length ? `<div class="ma-who">${who.map(ch => `<span>🧑 ${esc(ch.name)}</span>`).join('')}</div>` : ''}</div>
                  <div class="ma-acts"><button class="btn primary sm" data-tpl-use="${esc(t.id)}" type="button" title="Chèn vào ô Prompt ở tab Studio">↪ Dùng ở Studio</button>
                    <button class="btn ghost sm" data-tpl-edit="${esc(t.id)}" type="button">Sửa</button>
                    <button class="btn ghost sm st-pdel" data-tpl-del="${esc(t.id)}" type="button" title="Xoá mẫu">🗑</button></div></div>`;
              }).join('')}
              <button class="ma-new row" data-act="tpl-new" type="button"><b>＋</b>Mẫu prompt mới<small>lưu câu lệnh hay dùng — chèn bằng 1 bấm</small></button></div></section>
        </div>
        <div class="ma-col">
          ${pool('model', modelImages(), max, 'Người mẫu cố định', 'Gắn vào mọi lệnh — giữ 1 gương mặt / sản phẩm xuyên suốt', '👤', !!hero)}
          ${pool('rotate', s.rotate.images, 20, 'Ảnh luân phiên', 'Mỗi lệnh lấy 1 ảnh kế tiếp — đa dạng bối cảnh / sản phẩm', '🔁')}
        </div>
      </div>`;
    renderAssetTry();
  }
  async function pickImages() {
    const files = await api('pick_files', 'images_multi');
    if (!files || !files.length) return [];
    const res = await api('mhub_import', files);
    if (!res.ok) { toast(res.error, 'error'); return []; }
    return res.images;
  }
  function charDialog(ch) {
    const data = { id: ch ? ch.id : '', name: ch ? ch.name : '', images: ch ? [...ch.images] : [] };
    const paint = () => {
      openModal('TƯ LIỆU', ch ? 'Sửa nhân vật' : 'Nhân vật mới', `<div class="form">
        <label class="field"><span>Tên (gõ đúng tên này trong prompt để tự gắn ảnh)</span><input id="mhCharName" value="${esc(data.name)}" placeholder="VD: Lan"></label>
        <div class="field"><span>Ảnh (≤ 3)</span><div class="mh-thumbs">${data.images.map((im, i) => `<span class="mh-thumb"><img src="${esc(im.url)}" alt=""><button data-ci-rm="${i}" type="button">✕</button></span>`).join('')}
          ${data.images.length < 3 ? '<button class="mh-add" data-ci-add type="button">＋ Ảnh</button>' : ''}</div></div>
        <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-ci-cancel type="button">Huỷ</button><button class="btn primary" data-ci-save type="button">💾 Lưu</button></div></div>`, true);
      $('#modalBody').onclick = async e => {
        const b = e.target.closest('button');
        if (!b) return;
        data.name = $('#mhCharName').value;
        if (b.dataset.ciCancel !== undefined) return closeModal();
        if (b.dataset.ciRm !== undefined) { data.images.splice(+b.dataset.ciRm, 1); return paint(); }
        if (b.dataset.ciAdd !== undefined) { data.images = [...data.images, ...await pickImages()].slice(0, 3); return paint(); }
        if (b.dataset.ciSave !== undefined) {
          const res = await api('mhub_asset', 'character', { id: data.id, name: data.name, images: data.images.map(i => i.path) });
          if (!res.ok) return toast(res.error, 'error');
          closeModal(); H.s = res.state; renderAssets();
        }
      };
    };
    paint();
  }
  function tplDialog(t, text = '') {
    openModal('TƯ LIỆU', t ? 'Sửa mẫu prompt' : 'Mẫu prompt mới', `<div class="form">
      <label class="field"><span>Tên mẫu</span><input id="mhTplName" value="${esc(t ? t.name : '')}"></label>
      <label class="field"><span>Nội dung</span><textarea id="mhTplText" rows="8">${esc(t ? t.text : text)}</textarea></label>
      <div class="ab-row ab-confirm-foot"><button class="btn ghost" data-tp-cancel type="button">Huỷ</button><button class="btn primary" data-tp-save type="button">💾 Lưu</button></div></div>`, true);
    $('#modalBody').onclick = async e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.tpCancel !== undefined) return closeModal();
      if (b.dataset.tpSave !== undefined) {
        const res = await api('mhub_asset', 'template', { id: t ? t.id : '', name: $('#mhTplName').value, text: $('#mhTplText').value });
        if (!res.ok) return toast(res.error, 'error');
        closeModal(); H.s = res.state; renderAll(); toast('Đã lưu mẫu prompt', 'ok');
      }
    };
  }
  function projectsDialog() {
    const paint = () => {
      openModal('STUDIO MUSE AI', 'Dự án', `<div class="form">
        ${H.s.projects.map(p => `<div class="mh-proj ${p.id === H.s.current ? 'on' : ''}">
          <input data-pj-name="${esc(p.id)}" value="${esc(p.name)}" ${p.id === 'default' ? 'disabled' : ''}>
          <small class="muted">${H.s.tasks.filter(t => (t.project || 'default') === p.id).length} task</small>
          <button class="btn ghost sm" data-pj-open="${esc(p.id)}" type="button">${p.id === H.s.current ? '✓ Đang mở' : 'Mở'}</button>
          <button class="btn ghost sm" data-pj-pause="${esc(p.id)}" type="button">${p.paused ? '▶ Chạy tiếp' : '⏸ Tạm dừng'}</button>
          ${p.id === 'default' ? '' : `<button class="btn ghost sm st-pdel" data-pj-del="${esc(p.id)}" type="button">🗑</button>`}</div>`).join('')}
        <div class="ab-row"><input id="mhNewProj" placeholder="Tên dự án mới"><button class="btn primary sm" data-pj-add type="button">＋ Thêm dự án</button></div>
        <small class="muted">Tạm dừng: task chờ của dự án không chạy (task đang chạy vẫn chạy xong). Xoá dự án: huỷ + xoá task của dự án, file đã tải vẫn giữ.</small></div>`, true);
      const call = async (...args) => { const r = await api('mhub_project', ...args); if (!r.ok) return toast(r.error, 'error'); H.s = r.state; paint(); renderAll(); };
      $('#modalBody').onclick = e => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.pjAdd !== undefined) return call('add', '', $('#mhNewProj').value);
        if (b.dataset.pjOpen) return call('select', b.dataset.pjOpen);
        if (b.dataset.pjPause) return call('pause', b.dataset.pjPause);
        if (b.dataset.pjDel && confirm('Xoá dự án và toàn bộ task của dự án (file đã tải vẫn giữ)?')) return call('delete', b.dataset.pjDel);
      };
      $('#modalBody').onchange = e => { if (e.target.dataset.pjName) call('rename', e.target.dataset.pjName, e.target.value); };
    };
    paint();
  }

  Object.assign(MH, { modelHero, modelImages, assetPlan, renderAssetTry, renderAssets, pickImages, charDialog, tplDialog, projectsDialog });
})();
