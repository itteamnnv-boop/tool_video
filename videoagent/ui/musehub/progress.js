/* Studio Muse AI · tab Tiến trình (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, fmt, proj, mmss, startOfDay, projName, taskLabel, firstLine } = MH;  // khai báo ở core.js

  function avgSecs(kind) {  // thời gian trung bình 20 lượt xong gần nhất cùng loại → ước tính tiến độ
    const done = H.s.tasks.filter(t => t.kind === kind && t.status === 'succeeded' && t.started_at && t.finished_at > t.started_at)
      .sort((a, b) => b.finished_at - a.finished_at).slice(0, 20);
    if (!done.length) return kind === 'video' ? 180 : 60;
    return done.reduce((n, t) => n + (t.finished_at - t.started_at) / 1000, 0) / done.length;
  }
  function waitReason(t, ctx) {
    if (t.status === 'waiting') return 'Chờ storyboard xong';
    if (t.status === 'review') return 'Chờ bạn duyệt storyboard';
    if (H.s.stopped) return 'Hàng đợi đang dừng';
    if ((H.s.projects.find(p => p.id === (t.project || 'default')) || {}).paused) return 'Dự án đang tạm dừng';
    if (!ctx.usable) return 'Không có tài khoản Muse rảnh';
    if (ctx.free <= 0) return 'Chờ luồng trống';
    return 'Sắp chạy';
  }
  function renderProgress() {
    const el = $('#mhProgress');
    if (!el) return;
    const P = H.prog;
    const now = Date.now();
    const tasks = H.s.tasks.filter(t => P.all || (t.project || 'default') === H.s.current);
    const running = tasks.filter(t => t.status === 'processing');
    const pending = tasks.filter(t => ['queued', 'waiting', 'review'].includes(t.status)).sort((a, b) => a.created_at - b.created_at);
    const today = startOfDay();
    const doneToday = tasks.filter(t => t.status === 'succeeded' && t.finished_at >= today);
    const failToday = tasks.filter(t => t.status === 'failed' && t.finished_at >= today);
    const finished = tasks.filter(t => ['succeeded', 'failed', 'cancelled'].includes(t.status) && t.finished_at)
      .sort((a, b) => b.finished_at - a.finished_at).slice(0, 12);
    const accs = H.s.accounts.filter(a => a.enabled || a.running);
    const slots = accs.filter(a => a.enabled).reduce((n, a) => n + (+a.threads || 1), 0);
    const total = Math.min(slots, +H.s.settings.total_threads || slots);
    const allRunning = H.s.tasks.filter(t => t.status === 'processing').length;
    const ctx = { usable: H.s.accounts.some(a => a.enabled && a.usable), free: total - allRunning };
    const avg = { video: avgSecs('video'), image: avgSecs('image') };
    const avgOf = t => avg[t.kind === 'video' ? 'video' : 'image'];
    const accName = id => (H.s.accounts.find(a => a.id === id) || {}).name || '—';
    const stat = (cls, label, value, sub) => `<div class="mp-stat ${cls}"><small>${label}</small><b>${value}</b><span>${sub}</span></div>`;

    const runRow = t => {
      const spent = now - (t.started_at || now);
      const pct = Math.min(95, Math.round(spent / 10 / avgOf(t)));
      const last = ((t.log || []).slice(-1)[0] || 'Đang gửi lệnh cho Muse…').replace(/^\d\d:\d\d:\d\d\s*/, '');
      return `<div class="mp-run" data-ptask="${esc(t.id)}">
        <div class="mp-run-top"><span class="mh-gstep processing">${esc(taskLabel(t))}</span>
          <p title="${esc(t.prompt)}">${esc(firstLine(t))}</p>
          <b class="mp-time" data-since="${t.started_at || now}" data-avg="${avgOf(t)}">${mmss(spent)}</b>
          <button class="btn ghost sm" data-pcancel="${esc(t.id)}" type="button" title="Huỷ việc này">■ Huỷ</button></div>
        <div class="mp-bar"><i style="width:${pct}%"></i></div>
        <div class="mp-run-foot"><small class="mp-last" data-plog="${esc(t.id)}">${esc(last)}</small>
          <small class="muted">${P.all ? `${esc(projName(t.project))} · ` : ''}lần ${t.attempts || 1} · thường ~${mmss(avgOf(t) * 1000)}</small></div>
      </div>`;
    };

    const lanes = accs.map(a => {
      const mine = running.filter(t => t.account === a.id);
      const pct = a.quota ? Math.min(100, Math.round(a.quota.pct)) : null;
      const lvl = !a.enabled ? '' : mine.length ? 'run' : a.usable ? 'ok' : 'warn';
      const txt = !a.enabled ? 'Đã tắt' : mine.length ? 'Đang làm' : a.usable ? 'Rảnh' : 'Không dùng được';
      return `<section class="card mp-lane ${mine.length ? 'busy' : ''}">
        <div class="mp-lane-head"><b>👤 ${esc(a.name)}</b><span class="mh-pill ${lvl}">${txt}</span>
          <span class="mh-top-sp"></span><small class="muted">${a.running}/${a.threads || 1} luồng</small>
          ${pct != null ? `<span class="mh-qbar mp-quota ${pct >= 100 ? 'out' : pct >= 80 ? 'low' : ''}" title="Hạn mức tuần đã dùng ${pct}%"><i style="width:${pct}%"></i></span><small class="muted">${pct}%</small>` : ''}</div>
        ${mine.length ? mine.map(runRow).join('') : `<small class="mp-idle">${a.enabled ? (a.usable ? 'Rảnh — chờ việc mới trong hàng đợi' : esc(a.error || 'Hết hạn mức hoặc chưa đăng nhập')) : 'Bật lại ở tab Tài khoản'}</small>`}
      </section>`;
    }).join('') || '<div class="card mk-empty"><b>Chưa có tài khoản Muse</b><small>Thêm ở tab Tài khoản.</small></div>';
    const orphan = running.filter(t => !accs.some(a => a.id === t.account));

    el.innerHTML = `<div class="mp-head"><div class="mh-seg sm">${[[0, 'Dự án này'], [1, 'Tất cả dự án']].map(([v, l]) => `<button class="${+P.all === v ? 'on' : ''}" data-pall="${v}" type="button">${l}</button>`).join('')}</div>
        <small class="muted">${P.all ? `${H.s.projects.length} dự án` : esc(proj().name)} · cập nhật trực tiếp</small>
        <span class="mh-top-sp"></span>
        ${failToday.length ? `<button class="btn ghost sm" data-pretry-failed="${esc(failToday.map(t => t.id).join(','))}" type="button">↻ Chạy lại ${failToday.length} lỗi hôm nay</button>` : ''}
        ${H.s.stopped ? '<button class="btn primary sm" data-act="resume" type="button">▶ Chạy tiếp</button>' : '<button class="btn ghost sm mh-stop" data-act="stop" type="button">■ Dừng tất cả</button>'}</div>
      <div class="mp-stats">
        ${stat('run', 'Đang chạy', running.length, `${allRunning}/${total || 0} luồng toàn hệ thống`)}
        ${stat('', 'Đang chờ', pending.length, `${pending.filter(t => t.status === 'review').length} chờ duyệt · ${pending.filter(t => t.status === 'waiting').length} chờ storyboard`)}
        ${stat('ok', 'Xong hôm nay', doneToday.length, `${doneToday.filter(t => t.kind === 'video').length} video · ${doneToday.filter(t => t.kind !== 'video').length} ảnh`)}
        ${stat(failToday.length ? 'bad' : '', 'Lỗi hôm nay', failToday.length, failToday.length ? 'xem ở “Vừa xong”' : 'không có lỗi')}
        ${stat('', 'Thời gian TB / video', mmss(avg.video * 1000), `ảnh ${mmss(avg.image * 1000)}`)}
      </div>
      <div class="mp-main">
        <div class="mp-col"><div class="mp-title"><b>Đang xử lý theo tài khoản</b><small class="muted">${running.length} việc</small></div>${lanes}
          ${orphan.length ? `<section class="card mp-lane busy"><div class="mp-lane-head"><b>Tài khoản khác</b></div>${orphan.map(runRow).join('')}</section>` : ''}</div>
        <div class="mp-col">
          <section class="card mp-list"><div class="mp-title"><b>Sắp chạy</b><small class="muted">${pending.length} việc · theo thứ tự vào hàng</small></div>
            <div class="mp-items">${pending.length ? pending.slice(0, 30).map((t, i) => `<div class="mp-item" data-ptask="${esc(t.id)}"><span class="mp-n">${i + 1}</span>
              <div class="mh-tbody"><p>${esc(taskLabel(t))} · ${esc(firstLine(t))}</p>
                <small class="${t.status === 'review' ? 'mp-warn' : ''}">${esc(waitReason(t, ctx))}${P.all ? ` · ${esc(projName(t.project))}` : ''} · vào hàng ${fmt(t.created_at)}</small></div>
              ${t.status === 'review' && t.group ? `<button class="btn primary sm" data-gapprove="${esc(t.group)}" type="button">Duyệt</button>` : ''}</div>`).join('')
              + (pending.length > 30 ? `<small class="muted">… và ${pending.length - 30} việc nữa</small>` : '')
            : '<small class="mp-idle">Hàng đợi trống.</small>'}</div></section>
          <section class="card mp-list"><div class="mp-title"><b>Vừa xong</b><small class="muted">12 việc gần nhất</small></div>
            <div class="mp-items">${finished.length ? finished.map(t => `<div class="mp-item" data-ptask="${esc(t.id)}">
              <span class="mh-status ${esc(t.status)}">${esc(H.s.statuses[t.status] || t.status)}</span>
              <div class="mh-tbody"><p>${esc(taskLabel(t))} · ${esc(firstLine(t))}</p>
                <small>${t.started_at ? `mất ${mmss(t.finished_at - t.started_at)} · ` : ''}👤 ${esc(accName(t.account))} · ${fmt(t.finished_at)}</small>
                ${t.error && t.status !== 'succeeded' ? `<small class="mh-err">${esc(t.error.slice(0, 160))}</small>` : ''}</div>
              ${t.status === 'succeeded' && t.files.length ? `<button class="btn ghost sm" data-open-task-file="${esc(t.files[0].path)}" type="button" title="Mở thư mục chứa file">📂</button>`
                : t.status !== 'succeeded' ? `<button class="btn ghost sm" data-pretry="${esc(t.id)}" type="button" title="Chạy lại">↻</button>` : ''}</div>`).join('')
            : '<small class="mp-idle">Chưa có việc nào xong.</small>'}</div></section>
        </div>
      </div>`;
  }
  function tickProgress() {  // đồng hồ + thanh tiến độ chạy từng giây, không vẽ lại cả tab
    const page = $('#page-mstudio');
    if (H.tab !== 'progress' || !page || page.classList.contains('hidden')) return;
    const now = Date.now();
    $$('#mhProgress .mp-time').forEach(b => {
      const spent = now - +b.dataset.since;
      b.textContent = mmss(spent);
      const bar = b.closest('.mp-run').querySelector('.mp-bar i');
      if (bar) bar.style.width = `${Math.min(95, Math.round(spent / 10 / +b.dataset.avg))}%`;
    });
  }
  setInterval(tickProgress, 1000);

  Object.assign(MH, { avgSecs, waitReason, renderProgress, tickProgress });
})();
