/* Studio Muse AI · tab Tài khoản (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, day } = MH;  // khai báo ở core.js

  // ------------------------------------------------------------ tab Tài khoản
  function quotaHtml(a) {
    const q = a.quota;
    if (!q) return `<small class="muted">${a.checking ? 'Đang đọc hạn mức…' : 'Chưa có số liệu hạn mức — bấm “Hạn mức”'}</small>`;
    const pct = Math.min(100, Math.round(q.pct));
    const num = n => Number(n).toLocaleString('vi-VN');
    const week = `<div class="mh-qrow"><span class="mh-qlabel">Hạn mức tuần</span>
        <div class="mh-qbar ${pct >= 100 ? 'out' : pct >= 80 ? 'low' : ''}" title="Đã dùng ${pct}%"><i style="width:${pct}%"></i></div>
        <b class="mh-qval">${pct}%</b></div>
      <small>${esc(q.tier || 'Muse')} · đã dùng ${pct}% tuần${q.resets_at ? ` · đặt lại ${day(q.resets_at)}` : ''}</small>`;
    if (q.topup_left == null) return `<div class="mh-quota">${week}</div>`;
    // Additional token (token bổ sung): thanh = phần CÒN LẠI; hết hạn mức tuần thì Muse dùng token này
    const left = Math.max(0, Math.min(100, Math.round(q.topup_left * 100)));
    const nums = q.topup_balance != null && q.topup_total ? `còn ${num(q.topup_balance)} / ${num(q.topup_total)}` : (q.topup_label || '');
    const using = pct >= 100 && left > 0;
    return `<div class="mh-quota">${week}
      <div class="mh-qrow"><span class="mh-qlabel">Additional token</span>
        <div class="mh-qbar topup ${left <= 0 ? 'out' : left < 30 ? 'low' : ''}" title="Token bổ sung còn ${left}%"><i style="width:${left}%"></i></div>
        <b class="mh-qval">${left}%</b></div>
      <small>Token bổ sung ${esc(nums)}${using ? ' · <span class="mh-qusing">đang dùng (hết hạn mức tuần)</span>' : ''}${left <= 0 ? ' · đã hết' : ''}</small></div>`;
  }
  function statusOf(a) {
    if (!a.enabled) return ['', 'Tắt'];
    if (a.logged_in === false) return ['bad', 'Chưa đăng nhập'];
    if (a.running) return ['run', `Đang chạy ${a.running}`];
    if (a.checking) return ['', 'Đang kiểm tra…'];
    if (!a.usable) return ['warn', 'Hết hạn mức — nghỉ'];
    if (a.weekly_out) return ['warn', 'Hết tuần · dùng token'];
    return ['ok', 'Sẵn sàng'];
  }
  function renderAccounts() {
    const s = H.s.settings;
    const accs = H.s.accounts;
    const num = (k, label, min, max) => `<label class="field"><span>${label}</span><input type="number" min="${min}" max="${max}" data-set="${k}" value="${esc(s[k])}"></label>`;
    $('#mhAccounts').innerHTML = `<div class="card mh-acchead"><div><b class="mh-h">Tài khoản Muse</b>
        <small class="muted">Dùng profile Muse của hệ thống (Profile trình duyệt) — mỗi tài khoản 1 Chrome riêng, chạy song song. Đăng nhập 1 lần, app nhớ phiên.</small></div>
        <span class="mh-top-sp"></span>
        <button class="btn ghost sm" data-act="quota-all" type="button" title="Mở muse.ai ẩn ở từng profile, đọc % hạn mức tuần (không tốn lượt)">Kiểm tra hạn mức</button>
        <button class="btn primary sm" data-act="add-account" type="button">＋ Thêm tài khoản</button></div>
      <div class="card mh-settings">
        <div class="mh-grid">${num('max_accounts', 'TK chạy đồng thời', 1, 20)}${num('total_threads', 'Tổng luồng', 1, 50)}
          <div class="field"><span>Chia việc</span><div class="mh-seg">${[['rotate', 'Luân phiên'], ['sequential', 'Lần lượt']].map(([k, l]) => `<button class="${s.mode === k ? 'on' : ''}" data-mode="${k}" type="button">${l}</button>`).join('')}</div></div>
          ${num('limit_image', 'Giới hạn ảnh (phút)', 1, 60)}${num('limit_video', 'Giới hạn video (phút)', 5, 120)}${num('retries', 'Tự thử lại khi lỗi', 0, 3)}</div>
        <label class="mh-switch"><input type="checkbox" data-set-bool="use_topup" ${s.use_topup ? 'checked' : ''}><i></i> Dùng token bổ sung khi hết hạn mức tuần</label>
        <label class="mh-switch"><input type="checkbox" data-set-bool="keep_going" ${s.keep_going ? 'checked' : ''}><i></i> Hết hạn mức &amp; token vẫn tạo tiếp (chậm hơn)</label>
        <small class="muted">Hiện / ẩn cửa sổ Chrome: chỉnh chung ở <button class="link" data-act="open-settings" type="button">Cài đặt</button>.</small>
        <small class="muted">Luân phiên: task mới vào tài khoản ít việc nhất, dùng ít hạn mức nhất. Lần lượt: lấp đầy luồng tài khoản trên trước rồi mới sang tài khoản dưới. Tài khoản hết hạn mức (và không được dùng token) tự nghỉ tới ngày đặt lại.</small></div>
      ${accs.length ? accs.map(a => { const [lvl, txt] = statusOf(a); return `<div class="card mh-acc ${a.enabled ? '' : 'off'}">
          <label class="mh-switch" title="Bật / tắt tài khoản"><input type="checkbox" data-acc-on="${esc(a.id)}" ${a.enabled ? 'checked' : ''}><i></i></label>
          <div class="mh-accname"><b>${esc(a.name)}</b><span class="mh-pill ${lvl}">● ${esc(txt)}</span></div>
          <div class="mh-accq">${quotaHtml(a)}${a.error ? `<small class="mh-err">${esc(a.error)}</small>` : ''}</div>
          <select data-acc-threads="${esc(a.id)}" title="Số task chạy cùng lúc trên tài khoản này">${[1, 2, 3, 4, 5].map(n => `<option value="${n}" ${a.threads === n ? 'selected' : ''}>${n} luồng</option>`).join('')}</select>
          <button class="btn ghost sm" data-acc-login="${esc(a.id)}" type="button" title="Mở Chrome của tài khoản để đăng nhập / xem">Hiện Chrome</button>
          <button class="btn ghost sm" data-acc-quota="${esc(a.id)}" type="button" ${a.checking || a.running ? 'disabled' : ''}>Hạn mức</button></div>`; }).join('')
        : '<div class="card empty">Chưa có profile nào gán Muse — bấm “＋ Thêm tài khoản” để tạo profile trong màn Profile trình duyệt, tick Muse rồi đăng nhập.</div>'}`;
  }

  Object.assign(MH, { quotaHtml, statusOf, renderAccounts });
})();
