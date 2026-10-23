/* Cài đặt chung → "Zalo — nhận yêu cầu quảng cáo": bật / tắt nghe tin nhóm Zalo (zca-js, KHÔNG chính thức, đăng nhập bằng
   tài khoản cá nhân — chỉ ĐỌC tin), quét QR đăng nhập, chọn nhóm theo dõi, chế độ tự xử lý tin (gom / luật / Claude).
   Thay đổi áp dụng ngay (không cần bấm Lưu). Trạng thái cập nhật trực tiếp qua sự kiện zalo_status.
   Dùng chung helper của app.js: $, api, esc, toast. */
(() => {
  'use strict';
  const Z = { st: null, q: '' };
  const STATUS = { off: ['Tắt', 'off'], installing: ['Đang cài zca-js…', 'wait'], starting: ['Đang khởi động…', 'wait'],
    need_qr: ['Cần quét QR', 'warn'], scanned: ['Đã quét — xác nhận trên điện thoại', 'warn'], connecting: ['Đang kết nối…', 'wait'],
    connected: ['Đang nghe', 'on'], reconnecting: ['Đang kết nối lại…', 'wait'], kicked: ['Bị ngắt (Zalo Web mở nơi khác)', 'bad'],
    error: ['Lỗi', 'bad'] };

  function html() {
    const s = Z.st;
    if (!s) return '<small class="muted">Đang tải…</small>';
    const [label, cls] = STATUS[s.enabled ? s.status : 'off'] || [s.status, 'wait'];
    const watched = new Set(s.watched || []);
    const q = Z.q.trim().toLowerCase();
    const groups = (s.groups || []).filter(g => !q || g.name.toLowerCase().includes(q));
    return `
      <div class="zl-head">
        <label class="mh-switch"><input type="checkbox" id="zlOn" ${s.enabled ? 'checked' : ''}><i></i><span>Nghe tin nhắn nhóm Zalo → tạo yêu cầu quảng cáo chờ duyệt</span></label>
        <span class="zl-pill ${cls}">${esc(label)}</span>
      </div>
      <div class="zl-warn">⚠ Dùng thư viện <b>zca-js không chính thức</b>, đăng nhập Zalo bằng <b>tài khoản cá nhân</b> — có thể trái điều khoản Zalo và bị khoá tài khoản.
        Nên dùng <b>tài khoản Zalo phụ</b> chỉ để theo dõi nhóm. App chỉ <b>đọc</b> tin, không gửi tin hay thao tác gì trên Zalo. Mở Zalo Web của tài khoản này ở nơi khác sẽ làm ngắt phiên nghe. Cần Node.js 18+.</div>
      ${s.enabled ? `
        ${s.message ? `<small class="zl-msg ${cls}">${esc(s.message)}</small>` : ''}
        ${s.status === 'connected' ? `<small class="muted">${s.last
            ? `📨 Tin gần nhất: <b>${esc(s.last.at.slice(11, 16))}</b> · nhóm ${esc(s.last.group)} · ${esc(s.last.from)}`
            : '📨 Chưa có tin mới từ nhóm đang nghe kể từ lúc kết nối.'}${s.ignored ? ` · bỏ qua ${s.ignored} tin của nhóm khác` : ''}
          <br>Tin do <b>chính tài khoản Zalo đang nghe</b> gửi sẽ không được nhận. Muốn thử, hãy gửi tin bằng tài khoản khác. Sticker / ảnh không có chữ cũng bị bỏ qua.</small>` : ''}
        ${s.status === 'need_qr' && s.qr ? `<div class="zl-qr"><img src="${esc(s.qr)}" alt="Mã QR đăng nhập Zalo"><small>Mở Zalo trên điện thoại → biểu tượng Quét QR → quét mã này.<br>Mã tự làm mới khi hết hạn.</small></div>` : ''}
        ${s.account || s.logged_in ? `<div class="zl-acc">👤 ${s.account ? `Đang dùng tài khoản Zalo <b>${esc(s.account)}</b>` : 'Đã có phiên đăng nhập đã lưu'}
          <span class="ar-sp"></span><button class="btn ghost sm" data-zl="logout" type="button">Đăng xuất Zalo</button></div>` : ''}
        <label class="field"><span>Tên nhóm cần nghe <small class="muted">(mỗi dòng 1 nhóm · không phân biệt dấu / hoa thường · gõ phần đầu tên cũng khớp)</small></span>
          <textarea id="zlNames" rows="2" placeholder="VIDEO, HÌNH ẢNH, BÀI VIẾT PR">${esc(s.group_names || '')}</textarea></label>
        ${(s.groups || []).length ? `<div class="zl-matched">${watched.size
            ? `✓ Chỉ nghe ${watched.size} nhóm: ${s.groups.filter(g => watched.has(g.id)).map(g => `<b>${esc(g.name)}</b>${g.members ? ` <small>(${g.members} TV)</small>` : ''}`).join(', ')}`
            : '<span class="warn-text">⚠ Chưa có nhóm nào khớp tên trên — kiểm tra lại tên, hoặc bấm ＋ ở danh sách nhóm bên dưới.</span>'}</div>
          <details class="zl-groups"><summary>Danh sách nhóm của tài khoản (${s.groups.length}) — bấm ＋ để thêm tên</summary>
            <div class="zl-ghead">${s.groups.length > 8 ? `<input id="zlSearch" type="search" placeholder="🔍 Tìm nhóm…" value="${esc(Z.q)}">` : ''}<span class="ar-sp"></span>
              <button class="btn ghost sm" data-zl="groups" type="button" title="Tải lại danh sách nhóm">↻ Tải lại</button></div>
            <div class="zl-glist">${groups.map(g => `<div class="zl-g ${watched.has(g.id) ? 'on' : ''}">${watched.has(g.id) ? '<i class="zl-ok">✓</i>' : `<button type="button" class="zl-add" data-zadd="${esc(g.name)}" title="Thêm tên nhóm này">＋</button>`}
              <span>${esc(g.name)}</span><small>${g.members ? `${g.members} TV` : ''}</small></div>`).join('') || '<small class="muted">Không có nhóm khớp</small>'}</div>
          </details>` : (s.status === 'connected' ? '<small class="muted">Đang tải danh sách nhóm…</small>' : '')}
        <label class="field"><span>Khi có tin mới trong nhóm theo dõi</span><select id="zlAuto">
          ${Object.entries(s.auto_modes || {}).map(([k, l]) => `<option value="${k}" ${s.auto === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
          <small class="muted">${s.auto === 'claude' ? 'Gom tin trong 45 giây rồi gửi Claude (claude.ai + MCP) một lần — dùng lượt Claude; vẫn chỉ tạo đề xuất chờ duyệt.'
            : s.auto === 'rules' ? 'Không tốn lượt AI. Tin không phải yêu cầu sẽ bị bỏ qua; tin khó hiểu có thể gửi Claude từ Trợ lý quảng cáo.'
            : 'Tin chỉ được gom vào hộp tin ở Trợ lý quảng cáo — bạn chọn tin để gửi Claude.'}</small></label>
        ${s.auto === 'claude' ? `<label class="check"><input type="checkbox" id="zlShow" ${s.show_claude !== false ? 'checked' : ''}> Hiện cửa sổ Claude khi tự gửi (để bấm cho phép công cụ MCP)</label>` : ''}
        ${s.error && s.status !== 'connected' ? `<small class="zl-err">Chi tiết: ${esc(s.error)}</small>` : ''}` : ''}`;
  }

  function paint() {
    const box = $('#zaloBox');
    if (!box) return;
    // giữ chữ đang gõ (tên nhóm / tìm kiếm) + danh sách nhóm đang mở khi trạng thái cập nhật vẽ lại khung
    const act = document.activeElement && ['zlSearch', 'zlNames'].includes(document.activeElement.id) ? document.activeElement : null;
    const keep = act ? { id: act.id, value: act.value, start: act.selectionStart, end: act.selectionEnd } : null;
    const det = box.querySelector('details.zl-groups');
    if (det) Z.open = det.open;
    box.innerHTML = html();
    if (Z.open && box.querySelector('details.zl-groups')) box.querySelector('details.zl-groups').open = true;
    if (keep && $(`#${keep.id}`)) {
      const i = $(`#${keep.id}`);
      i.value = keep.value; i.focus(); i.setSelectionRange(keep.start, keep.end);
    }
  }

  async function mount() {
    const box = $('#zaloBox');
    if (!box) return;
    paint();
    const res = await api('zalo_state');
    if (res.ok) { Z.st = res.state; paint(); }
    box.onchange = async e => {
      const t = e.target;
      let res = null;
      if (t.id === 'zlOn') {
        res = await api('zalo_enable', t.checked);
        if (res.ok && t.checked) toast('Đang bật nghe Zalo — lần đầu sẽ cài zca-js và hiện mã QR để đăng nhập', 'ok');
      } else if (t.id === 'zlNames') {
        res = await api('zalo_set_names', t.value);
      } else if (t.id === 'zlAuto' || t.id === 'zlShow') {
        res = await api('zalo_set_auto', $('#zlAuto').value, $('#zlShow') ? $('#zlShow').checked : true);
      }
      if (!res) return;
      if (!res.ok) return toast(res.error, 'error');
      Z.st = res.state; paint();
    };
    box.oninput = e => { if (e.target.id === 'zlSearch') { Z.q = e.target.value; paint(); } };
    box.onclick = async e => {
      const add = e.target.closest('[data-zadd]');
      if (add) {  // ＋ ở danh sách nhóm → thêm tên nhóm vào ô "Tên nhóm cần nghe"
        const names = ($('#zlNames').value || '').split('\n').map(x => x.trim()).filter(Boolean);
        if (!names.includes(add.dataset.zadd)) names.push(add.dataset.zadd);
        const res = await api('zalo_set_names', names.join('\n'));
        if (res.ok) { Z.st = res.state; paint(); toast(`Sẽ nghe nhóm “${add.dataset.zadd}”`, 'ok'); }
        return;
      }
      const b = e.target.closest('[data-zl]');
      if (!b) return;
      if (b.dataset.zl === 'logout') {
        if (!confirm('Đăng xuất Zalo khỏi app? (Xoá phiên đăng nhập đã lưu — lần sau phải quét QR lại)')) return;
        const res = await api('zalo_logout');
        if (res.ok) { Z.st = res.state; paint(); toast('Đã đăng xuất Zalo', 'ok'); }
      } else if (b.dataset.zl === 'groups') {
        await api('zalo_refresh_groups'); toast('Đang tải lại danh sách nhóm…', 'ok');
      }
    };
  }

  function update(st) {  // sự kiện zalo_status
    Z.st = { ...(Z.st || {}), ...st };
    paint();
  }

  window.ZaloSettings = { mount, update };
})();
