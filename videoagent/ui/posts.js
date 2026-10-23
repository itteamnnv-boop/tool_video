/* Quản lý bài đăng Facebook — lưu mọi bài (kèm ảnh / video), sửa, đăng lại lên nhiều Fanpage (đăng ngay / lên lịch app
   tự đăng — sửa, đổi lịch, đăng ngay được / hẹn giờ trên Facebook).
   Dùng chung helper của app.js: $, $$, api, esc, toast, openModal, closeModal, baseName. */
(() => {
  'use strict';

  const P = { posts: [], types: [], schedulable: [], filter: 'all', source: '', q: '', pages: [] };
  const STATUS = { draft: 'Nháp', queued: 'Lên lịch', missed: 'Lỡ lịch', posted: 'Đã đăng', scheduled: 'Hẹn giờ FB', error: 'Lỗi' };
  const FILTERS = [['all', 'Tất cả'], ['queued', 'Lên lịch'], ['draft', 'Nháp'], ['posted', 'Đã đăng'], ['scheduled', 'Hẹn giờ FB'], ['error', 'Lỗi']];
  const inFilter = (p, f) => f === 'all' || p.status === f || (f === 'queued' && p.status === 'missed');  // lỡ lịch nằm trong Lên lịch
  // "còn 2 giờ 5 phút" / "quá giờ 3 phút"
  const left = at => {
    const s = Math.round(at - Date.now() / 1000), a = Math.abs(s);
    const txt = a < 60 ? `${a} giây` : a < 3600 ? `${Math.round(a / 60)} phút` : a < 86400 ? `${Math.floor(a / 3600)} giờ ${Math.round((a % 3600) / 60)} phút`
      : `${Math.floor(a / 86400)} ngày ${Math.round((a % 86400) / 3600)} giờ`;
    return s >= 0 ? `còn ${txt}` : `quá giờ ${txt}`;
  };
  // giá trị cho <input type="datetime-local"> theo giờ máy
  const localInput = sec => { const d = new Date(sec * 1000); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

  async function show() {
    await load();
    render();
  }

  async function load() {
    const res = await api('post_list');
    if (!res.ok) return toast(res.error, 'error');
    P.posts = res.posts; P.types = res.types; P.schedulable = res.schedulable;
    const badge = $('#sbPostCount');
    if (badge) badge.textContent = P.posts.length;
  }

  async function loadPages() {
    const res = await api('fb_state');
    P.pages = res.ok ? (res.fb.pages || []) : [];
  }

  // ------------------------------------------------------------ danh sách
  function visible() {
    const q = P.q.trim().toLowerCase();
    const list = P.posts.filter(p => inFilter(p, P.filter) && (!P.source || p.source === P.source)
      && (!q || `${p.title} ${p.caption} ${(p.publishes || []).map(x => x.page).join(' ')}`.toLowerCase().includes(q)));
    return P.filter === 'queued' ? list.sort((a, b) => (a.schedule ? a.schedule.at : 0) - (b.schedule ? b.schedule.at : 0)) : list;
  }

  function render() {
    const counts = Object.fromEntries(FILTERS.map(([k]) => [k, P.posts.filter(p => inFilter(p, k)).length]));
    const sources = [...new Map(P.posts.map(p => [p.source, p.source_label])).entries()];
    const list = visible();
    $('#postsBody').innerHTML = `<div class="ps-toolbar card">
        <div class="ps-filters">${FILTERS.map(([k, label]) => `<button class="ps-chip ${P.filter === k ? 'on' : ''}" data-filter="${k}" type="button">${label} <b>${counts[k]}</b></button>`).join('')}</div>
        <div class="ps-tools">
          <input id="psSearch" type="search" placeholder="Tìm theo nội dung, Fanpage…" value="${esc(P.q)}">
          <select id="psSource"><option value="">Mọi nguồn</option>${sources.map(([k, l]) => `<option value="${esc(k)}" ${P.source === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
          <button class="btn primary" data-act="new" type="button">+ Bài mới</button>
        </div>
      </div>
      <div class="ps-grid">${list.map(cardHtml).join('') || `<div class="empty ps-empty">${P.posts.length
        ? 'Không có bài nào khớp bộ lọc.'
        : 'Chưa có bài đăng nào. Bài đăng từ Fanpage, Workflow, Chiến dịch sẽ tự lưu ở đây — hoặc bấm “+ Bài mới” để soạn bài.'}</div>`}</div>`;
    bind();
  }

  function thumbHtml(p) {
    const m = (p.media || [])[0];
    if (!m) return `<div class="ps-thumb text"><span>${esc((p.caption || p.title || '').slice(0, 90))}</span></div>`;
    if (!m.exists) return '<div class="ps-thumb missing"><span>Thiếu file</span></div>';
    return `<div class="ps-thumb"><img src="${esc(thumbUrl(m.url, 360))}" alt="" loading="lazy" decoding="async">${m.video ? '<i class="ps-play">▶</i>' : ''}${p.media.length > 1 ? `<em>+${p.media.length - 1}</em>` : ''}</div>`;
  }

  function cardHtml(p) {
    const last = p.last_publish;
    const lastText = last ? (last.error ? `Lỗi lần cuối · ${esc(last.page)}` : `${last.scheduled ? 'Hẹn ' + esc(last.scheduled) : esc(last.at)} · ${esc(last.page)}`) : 'Chưa đăng lần nào';
    return `<div class="card ps-card" data-id="${esc(p.id)}">
      ${thumbHtml(p)}
      <div class="ps-body">
        <div class="ps-tags"><span class="ps-status ${esc(p.status)}">${esc(STATUS[p.status] || p.status)}</span>
          <span class="ps-type" title="${esc(p.type_label)}">${esc(String(p.type_label).replace(/\s*\(.*\)\s*$/, ''))}</span>
          <span class="ps-icons">${last && last.url ? '<button class="ps-ic" data-act="open" type="button" title="Mở bài trên Facebook">↗</button>' : ''}
            <button class="ps-ic ps-del" data-act="delete" type="button" title="Xoá khỏi danh sách (không xoá bài trên Facebook)">🗑</button></span></div>
        <b class="ps-title" title="${esc(p.title)}">${esc(p.title)}</b>
        <p class="ps-caption">${esc(p.caption || '(không có chữ)')}</p>
        <small class="muted">${esc(p.source_label)}${p.source_name ? ' · ' + esc(p.source_name) : ''}</small>
        <small class="muted">${p.posted_count ? `Đã đăng ${p.posted_count} lần · ` : ''}${lastText}</small>
        ${p.schedule ? `<div class="ps-sched ${p.status === 'missed' ? 'missed' : ''}">
            <b>⏰ ${esc(p.schedule.when)}</b><span data-left="${p.schedule.at}">${p.status === 'missed' ? 'lỡ lịch — chưa đăng' : left(p.schedule.at)}</span>
            <small>→ ${esc((p.schedule.pages || []).join(', '))}</small></div>` : ''}
        ${p.auto && !p.auto.ok && p.auto.error ? `<small class="warn-text ps-autoerr" title="${esc(p.auto.error)}">⚠ ${esc(p.auto.how)}: ${esc(p.auto.error)}</small>` : ''}
        <div class="ps-actions">${p.schedule ? `
          <button class="btn primary sm" data-act="now" type="button" title="Đăng ngay lên ${esc((p.schedule.pages || []).join(', '))}, không chờ tới giờ">➤ Đăng ngay</button>
          <button class="btn ghost sm" data-act="publish" type="button" title="Đổi giờ / Fanpage">⏱ Đổi lịch</button>
          <button class="btn ghost sm" data-act="edit" type="button">✎ Sửa</button>
          <button class="btn ghost sm" data-act="unsched" type="button" title="Huỷ lịch — bài về Nháp">✕ Huỷ lịch</button>` : `
          <button class="btn primary sm" data-act="publish" type="button">${p.posted_count ? '↻ Đăng lại' : '➤ Đăng'}</button>
          <button class="btn ghost sm" data-act="edit" type="button">✎ Sửa</button>`}
        </div>
      </div></div>`;
  }

  function bind() {
    const root = $('#postsBody');
    root.oninput = e => {
      if (e.target.id === 'psSearch') {
        P.q = e.target.value;
        const pos = e.target.selectionStart;
        render();
        const s = $('#psSearch'); s.focus(); s.setSelectionRange(pos, pos);
      }
    };
    root.onchange = e => { if (e.target.id === 'psSource') { P.source = e.target.value; render(); } };
    root.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.filter) { P.filter = t.dataset.filter; return render(); }
      const card = t.closest('[data-id]');
      const post = card ? P.posts.find(p => p.id === card.dataset.id) : null;
      const act = t.dataset.act;
      if (act === 'new') return openEditor(null);
      if (!post) return;
      if (act === 'edit') return openEditor(post);
      if (act === 'publish') return openPublish(post);
      if (act === 'open') return api('open_url', post.last_publish.url);
      if (act === 'now') {
        const pages = (post.schedule.pages || []).join(', ');
        if (!confirm(`Đăng ngay “${post.title}” lên ${pages}?\n\nKhông chờ tới giờ hẹn ${post.schedule.when}.`)) return;
        t.disabled = true; t.textContent = 'Đang đăng…';
        const res = await api('post_publish_now', post.id, true);
        await load(); render();
        if (!res.ok) return toast(res.error, 'error');
        const bad = res.result.results.filter(r => r.error);
        return toast(res.result.error && !res.result.results.length ? res.result.error
          : bad.length ? `Lỗi: ${bad.map(b => `${b.page}: ${b.error}`).join('; ')}` : `Đã đăng lên ${pages}`, bad.length || res.result.error ? 'error' : 'ok');
      }
      if (act === 'unsched') {
        if (!confirm(`Huỷ lịch đăng “${post.title}” (${post.schedule.when})? Bài vẫn giữ trong danh sách.`)) return;
        const res = await api('post_unschedule', post.id);
        if (!res.ok) return toast(res.error, 'error');
        await load(); render(); return toast('Đã huỷ lịch đăng', 'ok');
      }
      if (act === 'delete') {
        if (!confirm('Xoá bài này khỏi Quản lý bài đăng (kèm bản sao ảnh / video)? Bài đã đăng trên Facebook vẫn giữ nguyên.')) return;
        const res = await api('post_delete', post.id);
        if (!res.ok) return toast(res.error, 'error');
        await load(); render(); toast('Đã xoá bài khỏi danh sách', 'ok');
      }
    };
  }

  // ------------------------------------------------------------ soạn / sửa bài
  function openEditor(post) {
    const d = post ? { id: post.id, title: post.title, caption: post.caption, kind: post.kind, files: post.media.map(m => m.path) }
      : { id: '', title: '', caption: '', kind: 'feed', files: [] };
    const draw = () => {
      $('#psEditor').innerHTML = `
        <label class="field"><span>Tên bài (để quản lý)</span><input data-e="title" value="${esc(d.title)}" placeholder="VD: BOSS 1 — video cứu vườn"></label>
        <label class="field"><span>Kiểu bài</span><select data-e="kind">${P.types.map(t => `<option value="${t.value}" ${t.value === d.kind ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}</select></label>
        ${d.kind === 'media' || d.kind === 'story' ? '<small class="hint">Kiểu này không đăng chữ — nội dung chỉ để bạn ghi chú.</small>' : ''}
        <label class="field"><span>Nội dung bài viết <small class="muted" id="psCount">${d.caption.length} ký tự</small></span>
          <textarea data-e="caption" rows="8" placeholder="Viết nội dung bài đăng…">${esc(d.caption)}</textarea></label>
        ${d.kind === 'text' ? '' : `<div class="field"><span>Ảnh / video (tối đa 10 ảnh, hoặc 1 video)</span>
          <div class="ps-media">${d.files.map((f, i) => `<span class="ps-mchip">${/\.(mp4|mov|webm|m4v)$/i.test(f) ? '🎬' : '🖼'} ${esc(baseName(f))}<button data-rm="${i}" type="button" title="Bỏ">✕</button></span>`).join('')}
            <button class="btn ghost sm" data-pick type="button">+ Chọn ảnh / video…</button></div></div>`}
        ${post && post.schedule ? `<div class="ps-sched inline"><b>⏰ Đang lên lịch ${esc(post.schedule.when)}</b><small>→ ${esc((post.schedule.pages || []).join(', '))} · lưu sửa đổi vẫn giữ lịch, tới giờ đăng nội dung mới</small></div>` : ''}
        ${post && (post.publishes || []).length ? `<div class="field"><span>Lịch sử đăng</span><div class="ps-history">${historyHtml(post)}</div></div>` : ''}
        <div class="modal-foot ps-foot">
          <button class="btn ghost" data-close type="button">Huỷ</button>
          <button class="btn ghost" data-save type="button">💾 Lưu bài</button>
          <button class="btn primary" data-save-publish type="button">${post && post.schedule ? '💾 Lưu &amp; đổi lịch…' : '💾 Lưu &amp; đăng…'}</button>
        </div>`;
    };
    openModal(post ? 'SỬA BÀI ĐĂNG' : 'BÀI MỚI', post ? post.title : 'Soạn bài đăng Facebook', '<div id="psEditor" class="ps-editor"></div>', true);
    draw();
    const body = $('#psEditor');
    body.oninput = e => {
      const k = e.target.dataset.e;
      if (!k) return;
      d[k] = e.target.value;
      if (k === 'caption') $('#psCount').textContent = `${d.caption.length} ký tự`;
    };
    body.onchange = e => { if (e.target.dataset.e === 'kind') { d.kind = e.target.value; draw(); } };
    body.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.url) return api('open_url', t.dataset.url);
      if (t.dataset.close !== undefined) return closeModal();
      if (t.dataset.rm !== undefined) { d.files.splice(+t.dataset.rm, 1); return draw(); }
      if (t.dataset.pick !== undefined) {
        const files = await api('pick_files', 'products');
        d.files = [...new Set([...d.files, ...files])].slice(0, 10);
        return draw();
      }
      if (t.dataset.save !== undefined || t.dataset.savePublish !== undefined) {
        t.disabled = true;
        const res = await api('post_save', d);
        t.disabled = false;
        if (!res.ok) return toast(res.error, 'error');
        closeModal();
        await load(); render();
        toast('Đã lưu bài', 'ok');
        if (t.dataset.savePublish !== undefined) openPublish(P.posts.find(p => p.id === res.post.id) || res.post);
      }
    };
  }

  function historyHtml(post) {
    return [...post.publishes].reverse().map(x => `<div class="ps-hrow ${x.error ? 'bad' : ''}">
      <b>${esc(x.page || x.page_id)}</b>
      <small>${esc(x.at)}${x.scheduled ? ` · hẹn ${esc(x.scheduled)}` : ''}${x.by ? ` · ${esc(x.by)}` : ''}</small>
      ${x.error ? `<small class="warn-text">${esc(x.error)}</small>` : x.url ? `<button class="link" data-url="${esc(x.url)}" type="button">${esc(x.url)}</button>` : ''}
    </div>`).join('');
  }

  // ------------------------------------------------------------ đăng / đăng lại (luôn cần xác nhận)
  async function openPublish(post) {
    await loadPages();
    const pages = P.pages.filter(p => p.connected);
    const canSchedule = P.schedulable.includes(post.kind);
    const sch = post.schedule;
    const nextHour = Math.ceil(Date.now() / 3600000) * 3600 + 3600;  // mặc định: tròn giờ sau
    const st = sch ? { pages: new Set(sch.page_ids), when: 'app', at: localInput(sch.at > Date.now() / 1000 + 60 ? sch.at : nextHour) }  // lỡ lịch → gợi ý giờ mới
      : { pages: new Set(), when: 'now', at: localInput(nextHour) };
    const draw = () => {
      const n = st.pages.size;
      $('#psPublish').innerHTML = `
        <div class="ps-pub-preview">${thumbHtml(post)}<div><span class="ps-type">${esc(post.type_label)}</span>
          <b>${esc(post.title)}</b><p class="ps-caption">${esc(post.caption || '(không có chữ)')}</p></div></div>
        <div class="field"><span>Đăng lên Fanpage (${n} đã chọn)</span>
          ${pages.length ? `<div class="ps-pages">${pages.map(p => `<label class="check ps-page ${st.pages.has(p.id) ? 'on' : ''}">
            <input type="checkbox" data-page="${esc(p.id)}" ${st.pages.has(p.id) ? 'checked' : ''}> ${esc(p.name)}</label>`).join('')}</div>`
            : '<div class="warn-text">Chưa có Fanpage nào bật “Kết nối” — vào Fanpage Facebook để kết nối.</div>'}</div>
        <div class="field"><span>Thời điểm</span><div class="ps-whens">
          <label class="ps-wopt ${st.when === 'now' ? 'on' : ''}"><input type="radio" name="psWhen" value="now" ${st.when === 'now' ? 'checked' : ''}>
            <b>➤ Đăng ngay</b><small>Đăng luôn khi bấm nút</small></label>
          <label class="ps-wopt ${st.when === 'app' ? 'on' : ''}"><input type="radio" name="psWhen" value="app" ${st.when === 'app' ? 'checked' : ''}>
            <b>⏰ Lên lịch</b><small>App tự đăng đúng giờ · sửa bài, đổi lịch, đăng ngay được · cần mở app lúc tới giờ</small></label>
          <label class="ps-wopt ${st.when === 'at' ? 'on' : ''} ${canSchedule ? '' : 'disabled'}"><input type="radio" name="psWhen" value="at" ${st.when === 'at' ? 'checked' : ''} ${canSchedule ? '' : 'disabled'}>
            <b>🗓 Hẹn giờ trên Facebook</b><small>${canSchedule ? 'Facebook tự đăng kể cả khi tắt app · 10 phút → 30 ngày · gửi rồi không sửa từ app được' : 'Story không hẹn giờ trên Facebook được'}</small></label></div>
          ${st.when !== 'now' ? `<div class="ps-at"><input type="datetime-local" id="psAt" value="${esc(st.at)}">
            <span class="muted" id="psAtLeft">${st.at && !isNaN(new Date(st.at)) ? left(new Date(st.at).getTime() / 1000) : ''}</span></div>` : ''}
          ${st.when === 'app' ? '<small class="muted">Mở app trễ hơn giờ hẹn quá 15 phút thì bài KHÔNG tự đăng — chuyển “Lỡ lịch” để bạn quyết định.</small>' : ''}</div>
        ${post.posted_count ? `<div class="field"><span>Đã đăng trước đó</span><div class="ps-history">${historyHtml(post)}</div></div>` : ''}
        <label class="check ps-confirm"><input type="checkbox" id="psConfirm"> <span>Tôi xác nhận ${st.when === 'now' ? 'đăng' : st.when === 'app' ? 'lên lịch đăng' : 'hẹn giờ'} bài này lên <b>${n}</b> Fanpage</span></label>
        <div class="modal-foot ps-foot"><button class="btn ghost" data-close type="button">Huỷ</button>
          <button class="btn primary" data-go type="button" ${n ? '' : 'disabled'}>${st.when === 'at' ? '🗓 Hẹn giờ trên Facebook' : st.when === 'app' ? (sch ? '⏰ Lưu lịch mới' : '⏰ Lên lịch') : '➤ Đăng ngay'}</button></div>`;
    };
    openModal(post.posted_count ? 'ĐĂNG LẠI' : 'ĐĂNG BÀI', post.title, '<div id="psPublish" class="ps-publish"></div>', true);
    draw();
    const box = $('#psPublish');
    box.onchange = e => {
      const t = e.target;
      if (t.dataset.page) { if (t.checked) st.pages.add(t.dataset.page); else st.pages.delete(t.dataset.page); return draw(); }
      if (t.name === 'psWhen') { st.when = t.value; return draw(); }
      if (t.id === 'psAt') { st.at = t.value; const l = $('#psAtLeft'); if (l) l.textContent = isNaN(new Date(st.at)) ? '' : left(new Date(st.at).getTime() / 1000); }
    };
    box.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.url) return api('open_url', t.dataset.url);
      if (t.dataset.close !== undefined) return closeModal();
      if (t.dataset.go === undefined) return;
      if (!$('#psConfirm').checked) return toast('Tick ô xác nhận trước khi đăng', 'warn');
      let at = null;
      if (st.when !== 'now') {
        const ms = new Date(st.at).getTime();
        if (!st.at || isNaN(ms)) return toast('Chọn ngày giờ hẹn đăng', 'warn');
        at = Math.floor(ms / 1000);
      }
      if (st.when === 'app') {
        t.disabled = true;
        const res = await api('post_schedule', post.id, [...st.pages], at, true);
        if (!res.ok) { draw(); return toast(res.error, 'error'); }
        closeModal(); P.filter = 'queued';
        await load(); render();
        return toast(`Đã lên lịch đăng lúc ${res.post.schedule.when} lên ${st.pages.size} Fanpage`, 'ok');
      }
      t.disabled = true; t.textContent = 'Đang đăng…';
      const res = await api('post_publish', post.id, [...st.pages], true, at);
      if (!res.ok) { draw(); return toast(res.error, 'error'); }
      const ok = res.result.results.filter(r => !r.error).length;
      const bad = res.result.results.filter(r => r.error);
      closeModal();
      await load(); render();
      toast(bad.length ? `Đăng được ${ok}/${res.result.results.length} Fanpage — lỗi: ${bad.map(b => `${b.page}: ${b.error}`).join('; ')}`
        : `${at ? 'Đã hẹn giờ' : 'Đã đăng'} lên ${ok} Fanpage`, bad.length ? (ok ? 'warn' : 'error') : 'ok');
    };
  }

  setInterval(() => $$('#postsBody [data-left]').forEach(el => { el.textContent = left(+el.dataset.left); }), 30000);

  window.PostsPage = { show, reload: async () => { await load(); if (!$('#page-posts').classList.contains('hidden')) render(); } };
  window.addEventListener('pywebviewready', () => setTimeout(load, 1500));  // số bài trên menu ngay khi mở app
})();
