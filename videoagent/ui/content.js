/* Block "Tạo content bài viết" — 2 màn:
   📚 Quản lý content: tìm / lọc mọi bài đã viết, xem, sửa tay (tự kiểm tra lại thông tin), sao chép, xoá, viết lại từ bài cũ.
   ✍ Tạo content: viết bài đăng Facebook theo mẫu, đúng thông tin sản phẩm (nhập tay / thư viện / từ link).
   (dùng chung helper của app.js: $, $$, api, esc, toast, state, profileOptions, siteOf). */
(() => {
  'use strict';

  const CT = { meta: null, form: null, result: null, history: [], busy: false, saveTimer: null,
    src: 'manual', link: { busy: false, info: null, filled: new Set() },
    screen: 'create', mf: { q: '', product: '', model: '', status: '' }, sel: new Set(), cur: null };
  try { CT.screen = localStorage.getItem('va.content.screen') || 'create'; } catch { /* bỏ qua */ }
  // ô nào hiện thành textarea nhiều dòng
  const MULTILINE = new Set(['benefits', 'problem', 'notes']);

  function defaults() {
    const saved = ((state.boot || {}).settings || {}).content_form || {};
    return { model: 'chatgpt_browser', browser_profile: '', count: 2, extra: '', template: '', product: {}, link_url: '', ...saved };
  }

  function persist() {
    clearTimeout(CT.saveTimer);
    CT.saveTimer = setTimeout(() => api('save_settings', { content_form: CT.form }), 600);
  }

  async function show() {
    if (!CT.meta) {
      const res = await api('content_models');
      if (!res.ok) return toast(res.error, 'error');
      CT.meta = res;
      CT.form = defaults();
      if (!CT.form.template) CT.form.template = res.template;
    }
    await loadModelMeta();  // tên model dùng chung
    const hist = await api('content_history');
    CT.history = hist.ok ? hist.items : [];
    render();
  }

  document.addEventListener('va:settings', () => { const b = $('#contentBody'); if (CT.meta && b && b.offsetParent) render(); });

  function setScreen(s) {
    CT.screen = s;
    try { localStorage.setItem('va.content.screen', s); } catch { /* bỏ qua */ }
    render();
  }

  function render() {
    $('#contentBody').innerHTML = `<div class="ct-screens">
        <button class="${CT.screen === 'manage' ? 'on' : ''}" data-screen="manage" type="button">📚 Quản lý content <span>${CT.history.length}</span></button>
        <button class="${CT.screen === 'create' ? 'on' : ''}" data-screen="create" type="button">✍ Tạo content</button></div>
      <div id="ctScreen"></div>`;
    if (CT.screen === 'manage') renderManage(); else renderCreate();
    bind();
  }

  // ================================================================ Quản lý content
  const status = h => (h.variants.some(v => v.issues.length) ? 'warn' : 'ok');
  const firstLines = t => String(t || '').split('\n').map(x => x.trim()).filter(Boolean).slice(0, 2).join(' · ');

  function filtered() {
    const f = CT.mf, q = f.q.trim().toLowerCase();
    return CT.history.filter(h => (!f.product || h.product === f.product) && (!f.model || h.model_name === f.model)
      && (!f.status || (f.status === 'edited' ? !!h.edited_at : status(h) === f.status))
      && (!q || `${h.product} ${h.variants.map(v => v.text).join(' ')}`.toLowerCase().includes(q)));
  }

  function renderManage() {
    const uniq = key => [...new Set(CT.history.map(h => h[key]).filter(Boolean))];
    const sel = (id, cur, all, list) => `<select id="${id}"><option value="">${all}</option>${list.map(([v, l]) => `<option value="${esc(v)}" ${cur === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
    $('#ctScreen').innerHTML = `<div class="ct-mgr">
      <div class="card ct-mgrbar">
        <input id="ctQ" type="search" value="${esc(CT.mf.q)}" placeholder="🔍 Tìm theo sản phẩm hoặc nội dung bài…">
        ${sel('ctFProduct', CT.mf.product, 'Mọi sản phẩm', uniq('product').map(x => [x, x]))}
        ${sel('ctFModel', CT.mf.model, 'Mọi model', uniq('model_name').map(x => [x, x]))}
        ${sel('ctFStatus', CT.mf.status, 'Mọi trạng thái', [['ok', '✓ Đạt'], ['warn', '⚠ Có cảnh báo'], ['edited', '✎ Đã sửa tay']])}
        <span class="ct-sp"></span>
        <button class="btn primary" data-screen="create" type="button">＋ Tạo content mới</button>
      </div>
      <div class="ct-mgrgrid"><div class="card ct-list" id="ctList"></div><div class="card ct-detail" id="ctDetail"></div></div></div>`;
    renderList();
    renderDetail();
  }

  function renderList() {
    const el = $('#ctList');
    if (!el) return;
    const list = filtered();
    if (CT.cur && !CT.history.some(h => h.id === CT.cur)) CT.cur = null;
    if (!CT.cur && list.length) CT.cur = list[0].id;
    [...CT.sel].forEach(id => { if (!CT.history.some(h => h.id === id)) CT.sel.delete(id); });
    const all = list.length && list.every(h => CT.sel.has(h.id));
    el.innerHTML = `<div class="ct-listhead"><label class="check"><input type="checkbox" id="ctSelAll" ${all ? 'checked' : ''}> Chọn tất cả</label>
        <small class="muted">${list.length}/${CT.history.length} bài</small><span class="ct-sp"></span>
        ${CT.sel.size ? `<button class="btn ghost sm ct-danger" id="ctDelSel" type="button">🗑 Xoá ${CT.sel.size} bài đã chọn</button>` : ''}</div>
      <div class="ct-rows">${list.length ? list.map(h => `<div class="ct-item ${CT.cur === h.id ? 'on' : ''}" data-cur="${esc(h.id)}">
          <input type="checkbox" data-sel="${esc(h.id)}" ${CT.sel.has(h.id) ? 'checked' : ''}>
          <div class="ct-itembody"><div class="ct-itemtop"><b>${esc(h.product || '(không tên)')}</b>
              <span class="ct-chip ${status(h)}">${status(h) === 'ok' ? '✓ Đạt' : '⚠ Cảnh báo'}</span>${h.edited_at ? '<span class="ct-chip edited">✎ Đã sửa</span>' : ''}</div>
            <p>${esc(firstLines((h.variants[0] || {}).text))}</p>
            <small class="muted">${esc(h.at)} · ${esc(h.model_name)} · ${h.variants.length} phiên bản</small></div></div>`).join('')
        : `<div class="ct-empty2"><b>${CT.history.length ? 'Không có bài khớp bộ lọc' : 'Chưa có bài viết nào'}</b>
            <small>${CT.history.length ? 'Đổi từ khoá / bộ lọc.' : 'Sang “✍ Tạo content” để viết bài đầu tiên.'}</small></div>`}</div>`;
  }

  function renderDetail() {
    const el = $('#ctDetail');
    if (!el) return;
    const h = CT.history.find(x => x.id === CT.cur);
    if (!h) { el.innerHTML = '<div class="ct-empty2"><small>Chọn một bài trong danh sách để xem, sửa, sao chép.</small></div>'; return; }
    const p = (h.form || {}).product || {};
    const facts = [['Giá', p.price], ['SĐT', p.hotline], ['Website', p.website], ['Địa chỉ', p.address], ['Quy cách', p.spec], ['Khuyến mãi', p.promo]].filter(([, v]) => v);
    el.innerHTML = `<div class="ct-dhead"><div><b>${esc(h.product || '(không tên)')}</b>
          <small class="muted">${esc(h.at)} · ${esc(h.model_name)} · ${esc(h.seconds)} giây${h.usd ? ` · ~$${Number(h.usd).toFixed(4)}` : ''}${h.edited_at ? ` · sửa lúc ${esc(h.edited_at)}` : ''}</small></div>
        <span class="ct-sp"></span>
        <button class="btn ghost sm" data-rewrite="${esc(h.id)}" type="button" title="Nạp thông tin sản phẩm + mẫu của bài này sang màn Tạo content">↻ Viết lại từ bài này</button>
        <button class="btn ghost sm ct-danger" data-del="${esc(h.id)}" type="button">🗑 Xoá</button></div>
      ${facts.length ? `<div class="ct-facts">${facts.map(([k, v]) => `<span><small>${k}</small>${esc(v)}</span>`).join('')}</div>`
        : (h.form ? '' : '<small class="muted">Bài viết trước khi có Quản lý content — không lưu thông tin sản phẩm, sửa tay sẽ không kiểm tra lại được.</small>')}
      ${h.variants.map((v, i) => `<div class="ct-variant" data-vi="${i}">
        <div class="ct-variant-head"><b>Phiên bản ${i + 1}</b>${v.edited ? '<span class="ct-chip edited">✎ đã sửa</span>' : ''}
          <small class="muted" data-len="${i}">${v.text.length} ký tự</small>
          <button class="btn ghost sm" data-copy="${i}" type="button">Sao chép</button>
          <button class="btn primary sm" data-save="${i}" type="button" disabled>Lưu sửa</button></div>
        <textarea class="ct-text" data-edit="${i}" rows="${Math.min(22, v.text.split('\n').length + 1)}">${esc(v.text)}</textarea>
        ${v.issues.length ? `<ul class="ct-issues">${v.issues.map(x => `<li>⚠ ${esc(x)}</li>`).join('')}</ul>`
          : '<div class="ct-pass">✓ Đúng giá, số điện thoại, website, địa chỉ; không có con số lạ</div>'}</div>`).join('')}`;
  }

  function rewriteFrom(id) {
    const h = CT.history.find(x => x.id === id);
    if (!h) return;
    const f = h.form;
    if (f) {
      Object.assign(CT.form, { product: { ...f.product }, extra: f.extra || '', count: f.count || CT.form.count,
        template: f.template || CT.form.template, link_url: f.link_url || CT.form.link_url,
        model: CT.meta.models.some(m => m.id === f.model) ? f.model : CT.form.model });
      toast(`Đã nạp thông tin “${h.product}” — chỉnh rồi bấm Viết bài`, 'ok');
    } else {
      CT.form.product = { ...CT.form.product, name: h.product };
      toast('Bài cũ chỉ còn tên sản phẩm — hãy nhập lại các thông tin còn lại', 'warn');
    }
    CT.result = null;
    CT.src = 'manual';
    CT.link = { busy: false, info: null, filled: new Set() };
    persist();
    setScreen('create');
  }

  async function saveEdit(i) {
    const h = CT.history.find(x => x.id === CT.cur);
    const box = $(`#ctDetail [data-edit="${i}"]`);
    if (!h || !box) return;
    const res = await api('content_update', h.id, i, box.value);
    if (!res.ok) return toast(res.error, 'error');
    CT.history = CT.history.map(x => (x.id === h.id ? res.entry : x));
    renderList(); renderDetail();
    const issues = res.entry.variants[i].issues.length;
    toast(issues ? `Đã lưu — còn ${issues} cảnh báo về thông tin` : 'Đã lưu bài sửa · thông tin khớp', issues ? 'warn' : 'ok');
  }

  // ================================================================ Tạo content
  function renderCreate() {
    const f = CT.form;
    const g = sharedModels();  // model viết bài: dùng chung (Cài đặt → Model AI)
    Object.assign(f, { model: g.text, browser_profile: g.text_profile });
    const model = CT.meta.models.find(m => m.id === f.model) || CT.meta.models[0];
    const fields = CT.meta.fields;
    $('#ctScreen').innerHTML = `
      <div class="ct-grid">
        <div class="ct-form">
          <div class="card">
            <div class="card-title">MODEL</div>
            ${sharedModelField('Model viết bài', 'text')}
            <p class="hint">${esc(model.note || '')}${model.ready ? '' : ' — <b>chưa sẵn sàng</b>'}</p>
          </div>
          <div class="card">
            <div class="card-title">THÔNG TIN SẢN PHẨM <span class="tag">nguồn sự thật duy nhất</span></div>
            <div class="ct-src">${[['manual', '✍ Nhập tay'], ['link', '🔗 Từ link']].map(([k, l]) => `<button class="${CT.src === k ? 'on' : ''}" data-src="${k}" type="button">${l}</button>`).join('')}</div>
            ${CT.src === 'link' ? `<div class="ct-link">
              <label class="field"><span>Link trang sản phẩm (LadiPage, website bán hàng…)</span>
                <div class="ct-linkrow"><input id="ctLinkUrl" value="${esc(f.link_url || '')}" placeholder="https://shop.vidu.vn/san-pham">
                  <button class="btn primary" id="ctLinkGo" type="button" ${CT.link.busy ? 'disabled' : ''}>${CT.link.busy ? 'Đang đọc…' : '🔍 Đọc trang & điền thông tin'}</button></div></label>
              <p class="hint">App đọc chữ trên trang, model đang chọn ở trên trích ra các ô bên dưới. Giá, số điện thoại, website, địa chỉ phải có thật trên trang — không khớp thì bỏ trống, AI không tự bịa. ${CT.link.busy && model.site ? 'Model trình duyệt thường mất 1–2 phút.' : ''}</p>
              ${CT.link.info ? `<div class="ct-linkinfo"><b>✓ Đã điền ${CT.link.info.filled.length} ô từ “${esc(CT.link.info.page.name)}”</b>
                <small>${esc(CT.link.info.filled.join(' · '))}</small>
                ${CT.link.info.dropped.length ? `<small class="ct-bad">Bỏ trống vì không thấy nguyên văn trên trang: ${esc(CT.link.info.dropped.join(', '))}</small>` : ''}
                <small class="muted">Kiểm tra lại các ô được đánh dấu rồi bấm Viết bài.</small></div>` : ''}</div>`
            : (CT.meta.products || []).length ? `<label class="field"><span>Lấy từ Thư viện sản phẩm</span><select id="ctLib">
              <option value="">— Chọn để điền nhanh —</option>${CT.meta.products.map(p => `<option value="${esc(p.id)}">${esc(p.name)}${p.code ? ` · ${esc(p.code)}` : ''}</option>`).join('')}</select></label>` : ''}
            <div class="ct-fields">${Object.entries(fields).map(([k, d]) => `
              <label class="field ${MULTILINE.has(k) ? 'ct-wide' : ''} ${CT.link.filled.has(k) ? 'ct-filled' : ''}"><span>${esc(d.label)}${d.required ? ' *' : ''}</span>
                ${MULTILINE.has(k) ? `<textarea data-pf="${k}" rows="${k === 'benefits' ? 4 : 2}">${esc(f.product[k] || '')}</textarea>`
                  : `<input data-pf="${k}" value="${esc(f.product[k] || '')}">`}</label>`).join('')}</div>
            <p class="hint">Giá, số điện thoại, website, địa chỉ được chép <b>nguyên văn</b>. Ô để trống thì bài bỏ dòng đó — AI không tự bịa.</p>
          </div>
          <div class="card">
            <div class="card-title">MẪU BÀI VIẾT</div>
            <textarea id="ctTemplate" rows="12" class="mono">${esc(f.template)}</textarea>
            <div class="row ct-row"><button class="btn ghost sm" id="ctResetTpl" type="button">Khôi phục mẫu gốc</button>
              <small class="muted">AI bắt chước bố cục, emoji, giọng văn — không chép thông tin sản phẩm của mẫu.</small></div>
            <div class="grid2 fb-gap">
              <label class="field"><span>Số phiên bản</span><select id="ctCount">${Array.from({ length: CT.meta.max_variants }, (_, i) => i + 1)
                .map(n => `<option ${n === +f.count ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
              <label class="field"><span>Yêu cầu thêm (tuỳ chọn)</span><input id="ctExtra" value="${esc(f.extra)}" placeholder="VD: nhấn mạnh mùa mưa, giọng miền Tây"></label>
            </div>
            <button class="btn primary big ct-go" id="ctGo" type="button" ${CT.busy ? 'disabled' : ''}>${CT.busy ? 'Đang viết…' : 'Viết bài →'}</button>
            ${CT.busy && model.site ? '<p class="hint">Model trình duyệt thường mất 1–2 phút.</p>' : ''}
          </div>
        </div>
        <div class="ct-out">
          ${renderResult(CT.result)}
          <div class="card"><div class="card-title">GẦN ĐÂY <span class="tag">${CT.history.length}</span>
              <button class="link ct-more" data-screen="manage" type="button">Quản lý tất cả →</button></div>
            ${CT.history.length ? CT.history.slice(0, 6).map(h => `<div class="ct-hist">
              <b>${esc(h.product)}</b><small>${esc(h.at)} · ${esc(h.model_name)} · ${h.variants.length} bài
                ${status(h) === 'warn' ? '<span class="ct-bad">có cảnh báo</span>' : '<span class="ct-ok">đạt</span>'}</small>
              <span class="row"><button class="btn ghost sm" data-open="${esc(h.id)}" type="button">Mở</button></span></div>`).join('')
              : '<div class="empty">Chưa có bài nào.</div>'}</div>
        </div>
      </div>`;
  }

  function renderResult(r) {
    if (!r) return '<div class="card ct-empty"><div class="empty">Nhập thông tin sản phẩm rồi bấm <b>Viết bài</b>. Kết quả và kiểm tra thông tin hiện ở đây — bài cũng được lưu ở <b>📚 Quản lý content</b>.</div></div>';
    return `<div class="card"><div class="card-title">KẾT QUẢ <span class="tag">${esc(r.model_name)} · ${esc(r.seconds)} giây${r.usd ? ` · ~$${Number(r.usd).toFixed(4)}` : ''}</span>
        <button class="link ct-more" data-open="${esc(r.id)}" type="button">Mở trong Quản lý →</button></div>
      <small class="muted">${esc(r.product)} · ${esc(r.at)}</small>
      ${r.variants.map((v, i) => `<div class="ct-variant">
        <div class="ct-variant-head"><b>Phiên bản ${i + 1}</b><small class="muted">${v.text.length} ký tự</small>
          <button class="btn ghost sm" data-copy="${i}" type="button">Sao chép</button></div>
        <textarea class="ct-text" data-text="${i}" rows="${Math.min(22, v.text.split('\n').length + 1)}">${esc(v.text)}</textarea>
        ${v.issues.length ? `<ul class="ct-issues">${v.issues.map(x => `<li>⚠ ${esc(x)}</li>`).join('')}</ul>`
          : '<div class="ct-pass">✓ Đúng giá, số điện thoại, website, địa chỉ; không có con số lạ</div>'}</div>`).join('')}</div>`;
  }

  function readForm() {
    const f = CT.form;
    if (!$('#ctTemplate')) return f;
    const g = sharedModels();
    Object.assign(f, { model: g.text, browser_profile: g.text_profile });
    f.product = Object.fromEntries($$('[data-pf]').map(el => [el.dataset.pf, el.value]));
    f.template = $('#ctTemplate').value;
    f.count = +$('#ctCount').value;
    f.extra = $('#ctExtra').value.trim();
    if ($('#ctLinkUrl')) f.link_url = $('#ctLinkUrl').value.trim();
    return f;
  }

  function fillFromLibrary(id) {
    const p = (CT.meta.products || []).find(x => x.id === id);
    if (!p) return;
    const price = p.sale_price || p.price || '';
    Object.assign(CT.form.product, {
      name: p.name || '', spec: p.spec || '', price, promo: p.promo || '', hotline: p.hotline || '',
      website: (p.links || [])[0] || CT.form.product.website || '',
      notes: [p.sale_price && p.price ? `Giá gốc ${p.price}, giá khuyến mãi ${p.sale_price}` : '', p.label ? `Nhãn: ${p.label}` : '']
        .filter(Boolean).join('. ') || CT.form.product.notes || '',
    });
    persist();
    render();
  }

  // ================================================================ sự kiện (cả 2 màn)
  function bind() {
    const root = $('#contentBody');
    root.oninput = e => {
      const t = e.target;
      if (t.id === 'ctQ') { CT.mf.q = t.value; return renderList(); }
      if (t.dataset.edit !== undefined) {  // sửa bài ở Quản lý → bật nút Lưu
        const h = CT.history.find(x => x.id === CT.cur), i = +t.dataset.edit;
        $(`#ctDetail [data-save="${i}"]`).disabled = !h || t.value === h.variants[i].text;
        $(`#ctDetail [data-len="${i}"]`).textContent = `${t.value.length} ký tự`;
        return;
      }
      if (t.closest('.ct-form')) { readForm(); persist(); }
    };
    root.onchange = e => {
      const t = e.target;
      const fmap = { ctFProduct: 'product', ctFModel: 'model', ctFStatus: 'status' };
      if (fmap[t.id]) { CT.mf[fmap[t.id]] = t.value; return renderList(); }
      if (t.id === 'ctSelAll') { filtered().forEach(h => (t.checked ? CT.sel.add(h.id) : CT.sel.delete(h.id))); return renderList(); }
      if (t.dataset.sel) { if (t.checked) CT.sel.add(t.dataset.sel); else CT.sel.delete(t.dataset.sel); return renderList(); }
      if (t.id === 'ctLib') return fillFromLibrary(t.value);
      if (!t.closest('.ct-form')) return;
      readForm();
      persist();
    };
    root.onclick = async e => {
      const t = e.target.closest('button, .ct-item') || e.target;
      if (t.dataset.screen) { readForm(); return setScreen(t.dataset.screen); }
      if (t.classList.contains('ct-item') && !e.target.matches('input')) { CT.cur = t.dataset.cur; renderList(); return renderDetail(); }
      if (t.id === 'ctResetTpl') { CT.form.template = CT.meta.template; persist(); render(); return; }
      if (t.id === 'ctGo') return generate();
      if (t.dataset.src) { readForm(); CT.src = t.dataset.src; render(); return; }
      if (t.id === 'ctLinkGo') return fromLink();
      if (t.dataset.copy !== undefined) {
        const box = t.closest('.ct-variant').querySelector('textarea');
        try { await navigator.clipboard.writeText(box.value); } catch { box.select(); document.execCommand('copy'); }
        toast('Đã sao chép bài viết', 'ok');
        return;
      }
      if (t.dataset.save !== undefined) return saveEdit(+t.dataset.save);
      if (t.dataset.rewrite) return rewriteFrom(t.dataset.rewrite);
      if (t.dataset.open) { CT.cur = t.dataset.open; readForm(); return setScreen('manage'); }
      if (t.dataset.del) {
        if (!confirm('Xoá bài này?')) return;
        const res = await api('content_delete', t.dataset.del);
        if (res.ok) { CT.history = res.items; if (CT.result && CT.result.id === t.dataset.del) CT.result = null; render(); }
        return;
      }
      if (t.id === 'ctDelSel') {
        if (!confirm(`Xoá ${CT.sel.size} bài đã chọn?`)) return;
        const res = await api('content_delete_many', [...CT.sel]);
        if (res.ok) { CT.history = res.items; CT.sel.clear(); render(); toast('Đã xoá', 'ok'); }
      }
    };
  }

  async function fromLink() {
    const f = readForm();
    if (!f.link_url) return toast('Dán link trang sản phẩm trước', 'warn');
    const model = CT.meta.models.find(m => m.id === f.model);
    if (model && !model.ready) return toast(`${model.name}: ${model.note}`, 'warn');
    CT.link.busy = true;
    render();
    const res = await api('content_from_link', f.link_url, f.model, f.browser_profile);
    CT.link.busy = false;
    if (!res.ok) { render(); return toast(res.error, 'error'); }
    const r = res.result;
    // ô trang có thông tin → thay; ô trang không có → giữ giá trị đang nhập (VD: hotline, người tư vấn cố định)
    Object.entries(r.product).forEach(([k, v]) => { if (v) f.product[k] = v; });
    CT.link.filled = new Set(Object.keys(r.product).filter(k => r.product[k] && k !== 'notes'));
    CT.link.info = r;
    persist();
    render();
    toast(`Đã điền ${r.filled.length} ô từ trang — kiểm tra lại rồi bấm Viết bài`, r.dropped.length ? 'warn' : 'ok');
  }

  async function generate() {
    const f = readForm();
    const missing = Object.entries(CT.meta.fields).filter(([k, d]) => d.required && !(f.product[k] || '').trim()).map(([, d]) => d.label);
    if (missing.length) return toast(`Hãy nhập: ${missing.join(', ')}`, 'warn');
    const model = CT.meta.models.find(m => m.id === f.model);
    if (model && !model.ready) return toast(`${model.name}: ${model.note}`, 'warn');
    CT.busy = true;
    render();
    const res = await api('content_generate', f);
    CT.busy = false;
    if (!res.ok) { render(); return toast(res.error, 'error'); }
    CT.result = res.result;
    CT.history = [res.result, ...CT.history.filter(h => h.id !== res.result.id)];
    const warn = res.result.variants.some(v => v.issues.length);
    toast(warn ? 'Đã viết xong — có cảnh báo về thông tin, xem bên dưới mỗi bài' : 'Đã viết xong, thông tin khớp · đã lưu vào Quản lý content', warn ? 'warn' : 'ok');
    render();
  }

  window.ContentStudio = { show };
})();
