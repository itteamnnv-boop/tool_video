/* Quản lý bài đăng Facebook — lưu mọi bài (kèm ảnh / video), sửa, đăng lại lên nhiều Fanpage (đăng ngay / hẹn giờ).
   Dùng chung helper của app.js: $, $$, api, esc, toast, openModal, closeModal, baseName. */
(() => {
  'use strict';

  const P = { posts: [], types: [], schedulable: [], filter: 'all', source: '', q: '', pages: [] };
  const STATUS = { draft: 'Nháp', posted: 'Đã đăng', scheduled: 'Hẹn giờ', error: 'Lỗi' };
  const FILTERS = [['all', 'Tất cả'], ['draft', 'Nháp'], ['posted', 'Đã đăng'], ['scheduled', 'Hẹn giờ'], ['error', 'Lỗi']];

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
    return P.posts.filter(p => (P.filter === 'all' || p.status === P.filter) && (!P.source || p.source === P.source)
      && (!q || `${p.title} ${p.caption} ${(p.publishes || []).map(x => x.page).join(' ')}`.toLowerCase().includes(q)));
  }

  function render() {
    const counts = Object.fromEntries(FILTERS.map(([k]) => [k, k === 'all' ? P.posts.length : P.posts.filter(p => p.status === k).length]));
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
    return `<div class="ps-thumb">${m.video ? `<video src="${esc(m.url)}#t=0.5" muted preload="metadata"></video><i class="ps-play">▶</i>`
      : `<img src="${esc(m.url)}" alt="" loading="lazy">`}${p.media.length > 1 ? `<em>+${p.media.length - 1}</em>` : ''}</div>`;
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
        <div class="ps-actions">
          <button class="btn primary sm" data-act="publish" type="button">${p.posted_count ? '↻ Đăng lại' : '➤ Đăng'}</button>
          <button class="btn ghost sm" data-act="edit" type="button">✎ Sửa</button>
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
        ${post && (post.publishes || []).length ? `<div class="field"><span>Lịch sử đăng</span><div class="ps-history">${historyHtml(post)}</div></div>` : ''}
        <div class="modal-foot ps-foot">
          <button class="btn ghost" data-close type="button">Huỷ</button>
          <button class="btn ghost" data-save type="button">💾 Lưu bài</button>
          <button class="btn primary" data-save-publish type="button">💾 Lưu &amp; đăng…</button>
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
    const st = { pages: new Set(), when: 'now', at: '' };
    const draw = () => {
      const n = st.pages.size;
      $('#psPublish').innerHTML = `
        <div class="ps-pub-preview">${thumbHtml(post)}<div><span class="ps-type">${esc(post.type_label)}</span>
          <b>${esc(post.title)}</b><p class="ps-caption">${esc(post.caption || '(không có chữ)')}</p></div></div>
        <div class="field"><span>Đăng lên Fanpage (${n} đã chọn)</span>
          ${pages.length ? `<div class="ps-pages">${pages.map(p => `<label class="check ps-page ${st.pages.has(p.id) ? 'on' : ''}">
            <input type="checkbox" data-page="${esc(p.id)}" ${st.pages.has(p.id) ? 'checked' : ''}> ${esc(p.name)}</label>`).join('')}</div>`
            : '<div class="warn-text">Chưa có Fanpage nào bật “Kết nối” — vào Fanpage Facebook để kết nối.</div>'}</div>
        <div class="field"><span>Thời điểm</span><div class="ps-when">
          <label class="check"><input type="radio" name="psWhen" value="now" ${st.when === 'now' ? 'checked' : ''}> Đăng ngay</label>
          <label class="check ${canSchedule ? '' : 'disabled'}"><input type="radio" name="psWhen" value="at" ${st.when === 'at' ? 'checked' : ''} ${canSchedule ? '' : 'disabled'}> Hẹn giờ</label>
          ${st.when === 'at' ? `<input type="datetime-local" id="psAt" value="${esc(st.at)}">` : ''}
          ${canSchedule ? '' : '<small class="muted">Story không hẹn giờ được.</small>'}</div>
          ${st.when === 'at' ? '<small class="muted">Facebook cho hẹn từ 10 phút đến 30 ngày tính từ bây giờ.</small>' : ''}</div>
        ${post.posted_count ? `<div class="field"><span>Đã đăng trước đó</span><div class="ps-history">${historyHtml(post)}</div></div>` : ''}
        <label class="check ps-confirm"><input type="checkbox" id="psConfirm"> <span>Tôi xác nhận ${st.when === 'at' ? 'hẹn giờ' : 'đăng'} bài này lên <b>${n}</b> Fanpage</span></label>
        <div class="modal-foot ps-foot"><button class="btn ghost" data-close type="button">Huỷ</button>
          <button class="btn primary" data-go type="button" ${n ? '' : 'disabled'}>${st.when === 'at' ? '⏱ Hẹn giờ đăng' : '➤ Đăng ngay'}</button></div>`;
    };
    openModal(post.posted_count ? 'ĐĂNG LẠI' : 'ĐĂNG BÀI', post.title, '<div id="psPublish" class="ps-publish"></div>', true);
    draw();
    const box = $('#psPublish');
    box.onchange = e => {
      const t = e.target;
      if (t.dataset.page) { if (t.checked) st.pages.add(t.dataset.page); else st.pages.delete(t.dataset.page); return draw(); }
      if (t.name === 'psWhen') { st.when = t.value; return draw(); }
      if (t.id === 'psAt') st.at = t.value;
    };
    box.onclick = async e => {
      const t = e.target.closest('button');
      if (!t) return;
      if (t.dataset.url) return api('open_url', t.dataset.url);
      if (t.dataset.close !== undefined) return closeModal();
      if (t.dataset.go === undefined) return;
      if (!$('#psConfirm').checked) return toast('Tick ô xác nhận trước khi đăng', 'warn');
      let at = null;
      if (st.when === 'at') {
        const ms = new Date(st.at).getTime();
        if (!st.at || isNaN(ms)) return toast('Chọn ngày giờ hẹn đăng', 'warn');
        at = Math.floor(ms / 1000);
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

  window.PostsPage = { show, reload: async () => { await load(); if (!$('#page-posts').classList.contains('hidden')) render(); } };
  window.addEventListener('pywebviewready', () => setTimeout(load, 1500));  // số bài trên menu ngay khi mở app
})();
