/* Block "Tạo content bài viết" — viết bài đăng Facebook theo mẫu, đúng thông tin sản phẩm
   (dùng chung helper của app.js: $, $$, api, esc, toast, state, profileOptions, siteOf). */
(() => {
  'use strict';

  const CT = { meta: null, form: null, result: null, history: [], busy: false, saveTimer: null };
  // ô nào hiện thành textarea nhiều dòng
  const MULTILINE = new Set(['benefits', 'problem', 'notes']);

  function defaults() {
    const saved = ((state.boot || {}).settings || {}).content_form || {};
    return { model: 'chatgpt_browser', browser_profile: '', count: 2, extra: '', template: '', product: {}, ...saved };
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
    const hist = await api('content_history');
    CT.history = hist.ok ? hist.items : [];
    render();
  }

  function modelOptions() {
    const groups = {};
    CT.meta.models.forEach(m => (groups[m.group] = groups[m.group] || []).push(m));
    return Object.entries(groups).map(([g, list]) => `<optgroup label="${esc(g)}">${list.map(m =>
      `<option value="${esc(m.id)}" ${m.id === CT.form.model ? 'selected' : ''}>${esc(m.name)}${m.ready ? '' : ' — chưa có khoá'}</option>`).join('')}</optgroup>`).join('');
  }

  function render() {
    const f = CT.form;
    const model = CT.meta.models.find(m => m.id === f.model) || CT.meta.models[0];
    const fields = CT.meta.fields;
    $('#contentBody').innerHTML = `
      <div class="ct-grid">
        <div class="ct-form">
          <div class="card">
            <div class="card-title">MODEL</div>
            <label class="field"><span>Model viết bài</span><select id="ctModel">${modelOptions()}</select></label>
            <p class="hint">${esc(model.note || '')}${model.ready ? '' : ' — <b>chưa sẵn sàng</b>'}</p>
            ${model.site && state.profiles && state.profileSites[model.site]
              ? `<label class="field fb-gap"><span>Profile trình duyệt</span><select id="ctProfile">${profileOptions(model.site, f.browser_profile)}</select></label>` : ''}
          </div>
          <div class="card">
            <div class="card-title">THÔNG TIN SẢN PHẨM <span class="tag">nguồn sự thật duy nhất</span></div>
            ${(CT.meta.products || []).length ? `<label class="field"><span>Lấy từ Thư viện sản phẩm</span><select id="ctLib">
              <option value="">— Chọn để điền nhanh —</option>${CT.meta.products.map(p => `<option value="${esc(p.id)}">${esc(p.name)}${p.code ? ` · ${esc(p.code)}` : ''}</option>`).join('')}</select></label>` : ''}
            <div class="ct-fields">${Object.entries(fields).map(([k, d]) => `
              <label class="field ${MULTILINE.has(k) ? 'ct-wide' : ''}"><span>${esc(d.label)}${d.required ? ' *' : ''}</span>
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
          ${renderResult(CT.result, true)}
          <div class="card"><div class="card-title">LỊCH SỬ <span class="tag">${CT.history.length}</span></div>
            ${CT.history.length ? CT.history.slice(0, 30).map(h => `<div class="ct-hist" data-hist="${esc(h.id)}">
              <b>${esc(h.product)}</b><small>${esc(h.at)} · ${esc(h.model_name)} · ${h.variants.length} bài
                ${h.variants.some(v => v.issues.length) ? '<span class="ct-bad">có cảnh báo</span>' : '<span class="ct-ok">đạt</span>'}</small>
              <span class="row"><button class="btn ghost sm" data-open="${esc(h.id)}" type="button">Xem</button>
                <button class="btn ghost sm" data-del="${esc(h.id)}" type="button">Xoá</button></span></div>`).join('')
              : '<div class="empty">Chưa có bài nào.</div>'}</div>
        </div>
      </div>`;
    bind();
  }

  function renderResult(r, current) {
    if (!r) return '<div class="card ct-empty"><div class="empty">Nhập thông tin sản phẩm rồi bấm <b>Viết bài</b>. Kết quả và kiểm tra thông tin hiện ở đây.</div></div>';
    return `<div class="card"><div class="card-title">${current ? 'KẾT QUẢ' : 'BÀI ĐÃ VIẾT'} <span class="tag">${esc(r.model_name)} · ${esc(r.seconds)} giây${r.usd ? ` · ~$${Number(r.usd).toFixed(4)}` : ''}</span></div>
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
    f.model = $('#ctModel').value;
    f.browser_profile = $('#ctProfile') ? $('#ctProfile').value : '';
    f.product = Object.fromEntries($$('[data-pf]').map(el => [el.dataset.pf, el.value]));
    f.template = $('#ctTemplate').value;
    f.count = +$('#ctCount').value;
    f.extra = $('#ctExtra').value.trim();
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

  function bind() {
    const root = $('#contentBody');
    root.oninput = e => { if (e.target.closest('.ct-form')) { readForm(); persist(); } };
    root.onchange = e => {
      if (e.target.id === 'ctLib') return fillFromLibrary(e.target.value);
      if (!e.target.closest('.ct-form')) return;
      readForm();
      persist();
      if (e.target.id === 'ctModel') render();
    };
    root.onclick = async e => {
      const t = e.target;
      if (t.id === 'ctResetTpl') { CT.form.template = CT.meta.template; persist(); render(); return; }
      if (t.id === 'ctGo') return generate();
      if (t.dataset.copy !== undefined) {
        const box = t.closest('.ct-variant').querySelector('textarea');
        try { await navigator.clipboard.writeText(box.value); } catch { box.select(); document.execCommand('copy'); }
        toast('Đã sao chép bài viết', 'ok');
        return;
      }
      if (t.dataset.open) { CT.result = CT.history.find(h => h.id === t.dataset.open) || null; render(); return; }
      if (t.dataset.del) {
        if (!confirm('Xoá bài này khỏi lịch sử?')) return;
        const res = await api('content_delete', t.dataset.del);
        if (res.ok) { CT.history = res.items; if (CT.result && CT.result.id === t.dataset.del) CT.result = null; render(); }
      }
    };
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
    toast(warn ? 'Đã viết xong — có cảnh báo về thông tin, xem bên dưới mỗi bài' : 'Đã viết xong, thông tin khớp', warn ? 'warn' : 'ok');
    render();
  }

  window.ContentStudio = { show };
})();
