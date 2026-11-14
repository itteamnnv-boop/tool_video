/* 🔌 Kết nối MCP — quản lý máy chủ MCP của app: thêm / sửa / xoá, kiểm tra kết nối, quyền từng công cụ (chỉ đọc mặc định
   được phép, công cụ có thể ghi mặc định chặn), thử gọi, nhật ký, nhập từ Claude Desktop. Trợ lý Canvas (ô 🔌) dùng các
   công cụ được phép ở đây. Token / header / biến môi trường không bao giờ gửi về giao diện (chỉ thấy “đã lưu”).
   Helper của app.js: $, api, esc, toast, state. Mở khoá quản trị: window.requireAdmin. */
(() => {
  'use strict';

  const M = { servers: [], logs: [], edit: null, open: new Set(), busy: {}, tries: {}, loaded: false };
  const root = () => $('#mcpBody');
  const PRESETS = [
    ['', '— Chọn mẫu (tuỳ chọn) —'],
    ['fs', 'Thư mục trên máy (filesystem — npx)'],
    ['fetch', 'Đọc trang web (fetch — uvx)'],
    ['http', 'Máy chủ MCP qua địa chỉ HTTP (có token)'],
  ];
  const ST = { ok: ['ok', '✓ Kết nối được'], error: ['bad', '✗ Lỗi'], unchecked: ['', '• Chưa kiểm tra'] };

  async function call(name, ...args) {
    try {
      const res = await api(name, ...args);
      if (res && res.ok === false && res.locked) {
        return (await window.requireAdmin('quản lý kết nối MCP')) ? call(name, ...args) : null;
      }
      if (!res || res.ok === false) { toast((res && res.error) || 'Lỗi', 'error'); return null; }
      return res;
    } catch (err) { toast(String(err), 'error'); return null; }
  }

  async function show() {
    const [a, b] = await Promise.all([call('mcp_list'), call('mcp_logs')]);
    if (a) M.servers = a.servers;
    if (b) M.logs = b.logs;
    M.loaded = true;
    render();
  }

  const put = s => { M.servers = M.servers.some(x => x.id === s.id) ? M.servers.map(x => (x.id === s.id ? s : x)) : [...M.servers, s]; };

  /* ---------------------------------------------------------------- vẽ */
  function render() {
    const el = root();
    if (!el) return;
    el.innerHTML = `
      <div class="mcp-head">
        <div><h2>🔌 Kết nối MCP</h2>
          <p class="muted">Nối app với nguồn dữ liệu qua <b>Model Context Protocol</b> (thư mục trên máy, cơ sở dữ liệu, Google Drive, CRM…).
          Trợ lý Claude trong Canvas (bật ô 🔌) chỉ được gọi các <b>công cụ bạn cho phép</b> ở đây. Công cụ chỉ đọc được phép sẵn; công cụ có thể
          thay đổi dữ liệu mặc định bị chặn. Token / mật khẩu chỉ lưu trên máy này.</p></div>
        <div class="mcp-head-acts">
          <button class="btn ghost sm" type="button" data-m="import" title="Thêm các máy chủ trong claude_desktop_config.json của Claude Desktop (chỉ đọc file đó)">⬇ Nhập từ Claude Desktop</button>
          <button class="btn ghost sm" type="button" data-m="reload">↻ Làm mới</button>
          <button class="btn primary sm" type="button" data-m="new">＋ Thêm kết nối</button></div>
      </div>
      ${M.edit ? formHtml(M.edit) : ''}
      <div class="mcp-list">${M.servers.length ? M.servers.map(cardHtml).join('')
        : M.loaded ? `<div class="mcp-empty">Chưa có kết nối nào. Bấm <b>＋ Thêm kết nối</b> hoặc <b>⬇ Nhập từ Claude Desktop</b>.</div>` : ''}</div>
      ${logsHtml()}`;
    bind(el);
  }

  function formHtml(f) {
    const rows = (list, kind) => list.map((r, i) => `<div class="mcp-pair">
        <input data-pair="${kind}" data-i="${i}" data-f="key" placeholder="${kind === 'env' ? 'TÊN_BIẾN' : 'Tên header (VD Authorization)'}" value="${esc(r.key || '')}">
        <input data-pair="${kind}" data-i="${i}" data-f="value" type="password" autocomplete="off"
          placeholder="${r.set ? '•••••• đã lưu — để trống giữ nguyên' : kind === 'env' ? 'giá trị' : 'VD Bearer …'}" value="${esc(r.value || '')}">
        <button class="link-btn" type="button" data-unpair="${kind}" data-i="${i}" title="Bỏ dòng này">✕</button></div>`).join('');
    return `<div class="mcp-form">
      <div class="mcp-form-head"><b>${f.id ? '✎ Sửa kết nối' : '＋ Kết nối mới'}</b>${f.id ? '' : `
        <select data-preset>${PRESETS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>`}</div>
      <div class="mcp-grid">
        <label>Tên<input data-ff="name" maxlength="60" value="${esc(f.name || '')}" placeholder="VD Kho dữ liệu sản phẩm"></label>
        <label>Kiểu<select data-ff="kind">
          <option value="stdio" ${f.kind !== 'http' ? 'selected' : ''}>Chạy lệnh trên máy (stdio)</option>
          <option value="http" ${f.kind === 'http' ? 'selected' : ''}>Địa chỉ HTTP (Streamable HTTP)</option></select></label>
      </div>
      ${f.kind === 'http' ? `
        <label>Địa chỉ<input data-ff="url" value="${esc(f.url || '')}" placeholder="https://…/mcp"></label>
        <div class="mcp-sub">Header (token xác thực…)</div>${rows(f.headers, 'headers')}
        <button class="link-btn" type="button" data-addpair="headers">＋ Thêm header</button>` : `
        <div class="mcp-grid">
          <label>Lệnh<input data-ff="command" value="${esc(f.command || '')}" placeholder="npx / uvx / python / đường dẫn .exe"></label>
          <label>Thư mục chạy (tuỳ chọn)<input data-ff="cwd" value="${esc(f.cwd || '')}"></label></div>
        <label>Tham số (mỗi dòng 1 tham số)<textarea data-ff="args" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;D:\\Du lieu">${esc((f.args || []).join('\n'))}</textarea></label>
        <div class="mcp-sub">Biến môi trường (API key…)</div>${rows(f.env, 'env')}
        <button class="link-btn" type="button" data-addpair="env">＋ Thêm biến</button>`}
      <div class="mcp-form-acts"><span class="muted">Lưu xong app tự <b>kiểm tra kết nối</b> và đọc danh sách công cụ.</span><span class="mcp-sp"></span>
        <button class="btn ghost sm" type="button" data-m="cancel">Huỷ</button>
        <button class="btn primary sm" type="button" data-m="save">💾 Lưu</button></div></div>`;
  }

  function badge(t) {
    return t.read_only === true ? '<span class="mcp-tag ro">chỉ đọc</span>'
      : t.destructive === true ? '<span class="mcp-tag rw">có thể xoá / ghi</span>'
        : t.read_only === false ? '<span class="mcp-tag rw">có thể ghi</span>' : '<span class="mcp-tag">chưa rõ</span>';
  }

  function cardHtml(s) {
    const [cls, label] = ST[s.status] || ST.unchecked;
    const busy = M.busy[s.id];
    const open = M.open.has(s.id);
    const where = s.kind === 'http' ? s.url : [s.command, ...(s.args || [])].join(' ');
    const secrets = [...(s.env || []), ...(s.headers || [])].map(x => `${esc(x.key)}${x.set ? ' ✓' : ' (trống)'}`).join(', ');
    return `<div class="mcp-card ${s.enabled ? '' : 'off'}" data-sid="${s.id}">
      <div class="mcp-card-top">
        <div class="mcp-title"><b>${esc(s.name)}</b><span class="mcp-kind">${s.kind === 'http' ? 'HTTP' : 'stdio'}</span>
          <span class="mcp-st ${cls}">${busy ? '<span class="cv-spin"></span> Đang kết nối…' : label}</span>
          ${s.server_info && s.server_info.name ? `<small class="muted">${esc(s.server_info.name)} ${esc(s.server_info.version || '')}</small>` : ''}</div>
        <div class="mcp-acts">
          <label class="cv-opt-check" title="Tắt = app không gọi máy chủ này"><input type="checkbox" data-flag="enabled" ${s.enabled ? 'checked' : ''}> Bật</label>
          <label class="cv-opt-check" title="Cho Trợ lý Claude trong Canvas dùng các công cụ được phép của kết nối này (khi bật ô 🔌)"><input type="checkbox" data-flag="assistant" ${s.assistant ? 'checked' : ''}> Dùng cho Trợ lý Canvas</label>
          <button class="btn ghost sm" type="button" data-act="check" ${busy ? 'disabled' : ''}>🔍 Kiểm tra kết nối</button>
          <button class="btn ghost sm" type="button" data-act="edit">✎ Sửa</button>
          <button class="btn ghost sm" type="button" data-act="del" title="Xoá kết nối">🗑</button></div></div>
      <div class="mcp-where"><code>${esc(where)}</code>${secrets ? `<small class="muted"> · bí mật: ${secrets}</small>` : ''}</div>
      ${s.error ? `<div class="mcp-err">⚠ ${esc(s.error)}</div>` : ''}
      ${s.tools.length ? `<button class="link-btn mcp-toggle" type="button" data-act="tools">${open ? '▾' : '▸'} Công cụ: ${s.allowed_count}/${s.tools.length} được phép${s.checked_at ? ` · kiểm tra lúc ${esc(s.checked_at.replace('T', ' '))}` : ''}</button>
        ${open ? `<div class="mcp-tools">${s.tools.map(t => toolHtml(s, t)).join('')}</div>` : ''}` : ''}
    </div>`;
  }

  function toolHtml(s, t) {
    const tr = M.tries[`${s.id}/${t.name}`];
    return `<div class="mcp-tool ${t.allowed ? 'on' : ''}">
      <div class="mcp-tool-row">
        <label class="cv-opt-check" title="Cho phép app / Trợ lý gọi công cụ này"><input type="checkbox" data-allow="${esc(t.name)}" ${t.allowed ? 'checked' : ''}></label>
        <code>${esc(t.name)}</code>${badge(t)}<span class="mcp-desc">${esc(t.description || t.title || '')}</span>
        <button class="link-btn" type="button" data-try="${esc(t.name)}" ${t.allowed ? '' : 'disabled title="Cho phép công cụ trước khi thử"'}>▶ Thử</button></div>
      ${tr ? `<div class="mcp-try">
        <label>Tham số (JSON)<textarea data-try-args="${esc(t.name)}" rows="3">${esc(tr.args)}</textarea></label>
        <div class="mcp-form-acts"><small class="muted mcp-schema">schema: ${esc(t.schema || '{}')}</small><span class="mcp-sp"></span>
          <button class="btn primary sm" type="button" data-run="${esc(t.name)}" ${tr.busy ? 'disabled' : ''}>${tr.busy ? 'Đang gọi…' : '▶ Gọi'}</button></div>
        ${tr.result ? `<pre class="mcp-out ${tr.result.ok ? '' : 'bad'}">${esc(tr.result.ok ? tr.result.text || '(trống)' : tr.result.error || tr.result.text)}</pre>` : ''}</div>` : ''}
    </div>`;
  }

  function logsHtml() {
    return `<details class="mcp-logs"><summary>📜 Nhật ký gọi gần đây (${M.logs.length})</summary>
      ${M.logs.length ? `<div class="mcp-log-acts"><button class="link-btn" type="button" data-m="clearlog">Xoá nhật ký</button></div>
      <table class="mcp-table"><tr><th>Lúc</th><th>Kết nối</th><th>Công cụ</th><th>Từ</th><th>Tham số</th><th>Kết quả</th></tr>
      ${M.logs.map(l => `<tr><td>${esc(String(l.at || '').replace('T', ' '))}</td><td>${esc(l.server)}</td><td><code>${esc(l.tool)}</code></td>
        <td>${esc(l.via || '')}</td><td><small>${esc(l.args || '')}</small></td>
        <td class="${l.ok ? 'ok' : 'bad'}">${l.ok ? `✓ ${l.chars} ký tự` : `✗ ${esc(l.error || '')}`}</td></tr>`).join('')}</table>`
        : '<p class="muted">Chưa có lần gọi nào.</p>'}</details>`;
  }

  /* ---------------------------------------------------------------- form */
  const blank = () => ({ id: '', name: '', kind: 'stdio', command: '', args: [], cwd: '', url: '', env: [], headers: [] });

  function readForm() {
    const f = M.edit;
    const box = root().querySelector('.mcp-form');
    if (!f || !box) return f;
    box.querySelectorAll('[data-ff]').forEach(i => {
      f[i.dataset.ff] = i.dataset.ff === 'args' ? i.value.split('\n').map(x => x.trim()).filter(Boolean) : i.value;
    });
    box.querySelectorAll('[data-pair]').forEach(i => { f[i.dataset.pair][+i.dataset.i][i.dataset.f] = i.value; });
    return f;
  }

  function preset(v) {
    const f = readForm();
    if (v === 'fs') Object.assign(f, { kind: 'stdio', name: f.name || 'Thư mục dữ liệu', command: 'npx',
      args: ['-y', '@modelcontextprotocol/server-filesystem', 'D:\\Du lieu'] });
    if (v === 'fetch') Object.assign(f, { kind: 'stdio', name: f.name || 'Đọc trang web', command: 'uvx', args: ['mcp-server-fetch'] });
    if (v === 'http') Object.assign(f, { kind: 'http', name: f.name || 'Máy chủ MCP', url: f.url || 'https://',
      headers: f.headers.length ? f.headers : [{ key: 'Authorization', value: '' }] });
    render();
  }

  async function save() {
    const f = readForm();
    const data = { ...f, env: f.env.filter(r => r.key), headers: f.headers.filter(r => r.key) };
    const res = await call('mcp_save', data);
    if (!res) return;
    put(res.server);
    M.edit = null;
    toast(`Đã lưu “${res.server.name}” — đang kiểm tra kết nối…`, 'ok');
    render();
    check(res.server.id);
  }

  /* ---------------------------------------------------------------- thao tác thẻ */
  async function check(sid) {
    M.busy[sid] = true;
    render();
    const res = await call('mcp_check', sid);
    delete M.busy[sid];
    if (res) {
      put(res.server);
      if (res.server.status === 'ok') {
        M.open.add(sid);
        toast(`Kết nối được — ${res.server.tools.length} công cụ, ${res.server.allowed_count} được phép`, 'ok');
      } else toast(res.server.error || 'Không kết nối được', 'error');
    }
    render();
  }

  async function allow(s, t, on) {
    if (on && t.read_only !== true && !confirm(`Công cụ “${t.name}” ${t.destructive ? 'có thể XOÁ / thay đổi' : 'có thể thay đổi'} dữ liệu`
      + ' (máy chủ không đánh dấu là chỉ đọc).\n\nCho phép app và Trợ lý Canvas gọi công cụ này?')) { render(); return; }
    const res = await call('mcp_allow', s.id, t.name, on);
    if (res) put(res.server);
    render();
  }

  function skeleton(schema) {  // tham số mẫu từ schema: {khoá bắt buộc: giá trị rỗng}
    try {
      const sc = JSON.parse(schema || '{}');
      const req = sc.required || Object.keys(sc.properties || {}).slice(0, 3);
      const out = {};
      req.forEach(k => {
        const p = (sc.properties || {})[k] || {};
        out[k] = p.type === 'number' || p.type === 'integer' ? 0 : p.type === 'boolean' ? false
          : p.type === 'array' ? [] : p.type === 'object' ? {} : '';
      });
      return JSON.stringify(out, null, 1);
    } catch { return '{}'; }
  }

  async function run(s, name) {
    const key = `${s.id}/${name}`;
    let args;
    try { args = JSON.parse((M.tries[key] && M.tries[key].args) || '{}'); } catch { toast('Tham số chưa đúng JSON', 'error'); return; }
    M.tries[key] = { ...M.tries[key], busy: true };
    render();
    const res = await call('mcp_call', s.id, name, args);
    M.tries[key] = { ...M.tries[key], busy: false, result: res ? res.result : { ok: false, error: 'Không gọi được' } };
    const lg = await call('mcp_logs');
    if (lg) M.logs = lg.logs;
    render();
  }

  function bind(el) {
    el.querySelectorAll('[data-m]').forEach(b => {
      b.onclick = async () => {
        const m = b.dataset.m;
        if (m === 'new') { M.edit = blank(); render(); }
        if (m === 'cancel') { M.edit = null; render(); }
        if (m === 'save') save();
        if (m === 'reload') show();
        if (m === 'clearlog' && confirm('Xoá toàn bộ nhật ký gọi MCP?')) { const r = await call('mcp_clear_logs'); if (r) { M.logs = []; render(); } }
        if (m === 'import') {
          const r = await call('mcp_import_desktop');
          if (!r) return;
          const { added, skipped } = r.imported;
          toast(added.length ? `Đã thêm ${added.length} kết nối: ${added.join(', ')}${skipped.length ? ` · bỏ qua ${skipped.length} (trùng tên)` : ''}`
            : 'Không có kết nối mới (đã có hết)', added.length ? 'ok' : '');
          show();
        }
      };
    });
    el.querySelectorAll('input, textarea, select').forEach(i => { i.addEventListener('keydown', e => e.stopPropagation()); });
    const form = el.querySelector('.mcp-form');
    if (form) {
      form.querySelector('[data-ff="kind"]').onchange = () => { readForm(); render(); };
      const pre = form.querySelector('[data-preset]');
      if (pre) pre.onchange = () => preset(pre.value);
      form.querySelectorAll('[data-addpair]').forEach(b => { b.onclick = () => { readForm()[b.dataset.addpair].push({ key: '', value: '' }); render(); }; });
      form.querySelectorAll('[data-unpair]').forEach(b => { b.onclick = () => { readForm()[b.dataset.unpair].splice(+b.dataset.i, 1); render(); }; });
    }
    el.querySelectorAll('.mcp-card').forEach(card => {
      const s = M.servers.find(x => x.id === card.dataset.sid);
      if (!s) return;
      card.querySelectorAll('[data-flag]').forEach(c => {
        c.onchange = async () => { const r = await call('mcp_flag', s.id, c.dataset.flag, c.checked); if (r) put(r.server); render(); };
      });
      card.querySelectorAll('[data-act]').forEach(b => {
        b.onclick = async () => {
          const a = b.dataset.act;
          if (a === 'check') check(s.id);
          if (a === 'tools') { if (M.open.has(s.id)) M.open.delete(s.id); else M.open.add(s.id); render(); }
          if (a === 'edit') {
            M.edit = { ...blank(), ...s, env: s.env.map(x => ({ key: x.key, value: '', set: x.set })),
              headers: s.headers.map(x => ({ key: x.key, value: '', set: x.set })) };
            render();
          }
          if (a === 'del' && confirm(`Xoá kết nối “${s.name}”? (token / cấu hình đã lưu của kết nối này cũng bị xoá)`)) {
            const r = await call('mcp_delete', s.id);
            if (r) { M.servers = M.servers.filter(x => x.id !== s.id); render(); }
          }
        };
      });
      card.querySelectorAll('[data-allow]').forEach(c => {
        c.onchange = () => allow(s, s.tools.find(t => t.name === c.dataset.allow), c.checked);
      });
      card.querySelectorAll('[data-try]').forEach(b => {
        b.onclick = () => {
          const key = `${s.id}/${b.dataset.try}`;
          if (M.tries[key]) delete M.tries[key];
          else M.tries[key] = { args: skeleton((s.tools.find(t => t.name === b.dataset.try) || {}).schema) };
          render();
        };
      });
      card.querySelectorAll('[data-try-args]').forEach(t => {  // giữ tham số đang gõ khi trang vẽ lại
        t.oninput = () => { const k = `${s.id}/${t.dataset.tryArgs}`; if (M.tries[k]) M.tries[k].args = t.value; };
      });
      card.querySelectorAll('[data-run]').forEach(b => { b.onclick = () => run(s, b.dataset.run); });
    });
  }

  window.McpPage = { show };
})();
