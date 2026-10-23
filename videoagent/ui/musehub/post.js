/* Studio Muse AI · tab Hậu kỳ (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, fmt, proj, projName, postSave, fileName, lineText, sceneLabel } = MH;  // khai báo ở core.js

  function hfText(h) {
    if (!h) return 'Không kiểm tra được Node.js / FFmpeg';
    if (!h.node_ok) return `⚠ Cần Node.js 22 trở lên (máy đang: ${esc(h.node || 'chưa cài')}) — tải ở nodejs.org rồi mở lại app.`;
    if (!h.ffprobe) return '⚠ Cần FFmpeg có ffprobe trong PATH (Windows: winget install Gyan.FFmpeg) rồi mở lại app.';
    return `✓ Node.js ${esc(h.node)} · FFmpeg sẵn sàng · ${h.installed ? `HyperFrames ${esc(h.version)} đã cài` : `lần chạy đầu app tự cài HyperFrames ${esc(h.version)} (cần internet)`}. Muse viết HTML + GSAP, máy bạn dựng video (~3 phút cho 1 phút video); lỗi thì quay về phụ đề thường.`;
  }
  async function showPost() {
    const P = H.post;
    if (!P.meta) {
      const [m, hf] = await Promise.all([api('mhub_post_meta'), api('hyperframes_status')]);
      if (!m.ok) return toast(m.error, 'error');
      P.meta = m.meta; P.hf = hf.ok ? hf.status : null;
    }
    const st = await api('mhub_post_state');
    if (st.ok) P.state = st.state;
    renderPost();
  }
  function renderPost() {
    const el = $('#mhPost');
    if (!el || !H.post.meta) return;
    el.innerHTML = `<div class="pp-main"><section class="card pp-clips" id="mhPostClips"></section><section class="card pp-opts" id="mhPostOpts"></section></div>
      <section class="card pp-jobs" id="mhPostJobs"></section>`;
    renderPostClips(); renderPostOpts(); renderPostJobs();
  }
  function renderPostClips() {
    const P = H.post;
    const box = $('#mhPostClips');
    if (!box) return;
    const needText = P.form.audio !== 'mute';
    const total = P.clips.reduce((n, c) => n + (c.dur || 0), 0);
    box.innerHTML = `<div class="mh-card-head"><b>Cảnh ghép</b><small class="muted">${P.clips.length} video${total ? ` · ~${Math.round(total)}s` : ''} · kéo ⋮⋮ để đổi thứ tự</small>
        <span class="mh-top-sp"></span>
        <button class="btn ghost sm" data-act="pp-lib" type="button">＋ Từ Thư viện</button>
        <button class="btn ghost sm" data-act="pp-pick" type="button">＋ Từ máy</button>
        ${P.clips.length ? '<button class="link danger" data-act="pp-clear" type="button">Xoá hết</button>' : ''}</div>
      <div class="pp-list">${P.clips.length ? P.clips.map((c, i) => `<div class="pp-clip" data-pp-row="${i}">
          <span class="pp-grip" draggable="true" data-pp-drag="${i}" title="Kéo để đổi thứ tự">⋮⋮<b>${i + 1}</b></span>
          ${c.url ? `<video src="${esc(c.url)}" muted preload="metadata" data-pp-dur="${i}"></video>` : '<span class="pp-ph" title="Video trên máy">🎬</span>'}
          <div class="pp-body"><div class="pp-name"><b title="${esc(c.path)}">${esc(c.title || fileName(c.path))}</b><small class="muted" id="ppDur${i}">${c.dur ? `${c.dur.toFixed(1)}s` : ''}</small></div>
            ${needText ? `<textarea data-pp-text="${i}" rows="2" placeholder="${P.form.audio === 'tts' ? 'Lời đọc cho cảnh này (lồng tiếng AI + phụ đề). Để trống = cảnh không lời' : 'Lời thoại trong clip (để làm phụ đề) — tuỳ chọn'}">${esc(c.text || '')}</textarea>` : ''}</div>
          <div class="pp-acts"><button class="btn ghost sm" data-pp-up="${i}" type="button" ${i ? '' : 'disabled'} title="Lên">↑</button>
            <button class="btn ghost sm" data-pp-down="${i}" type="button" ${i < P.clips.length - 1 ? '' : 'disabled'} title="Xuống">↓</button>
            <button class="btn ghost sm st-pdel" data-pp-rm="${i}" type="button" title="Bỏ">✕</button></div>
        </div>`).join('') : `<div class="mk-empty"><b>Chưa có video nào</b><small>Thêm video từ Thư viện của Studio Muse AI hoặc từ máy, sắp xếp thứ tự rồi bấm “Ghép & hậu kỳ”.</small></div>`}</div>`;
  }
  function renderPostOpts() {
    const P = H.post, f = P.form, m = P.meta;
    const box = $('#mhPostOpts');
    if (!box) return;
    const opts = (list, cur) => list.map(x => (typeof x === 'object' ? [x.value ?? x.id, x.label ?? x.name] : [x, x]))
      .map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? 'selected' : ''}>${esc(l)}</option>`).join('');
    box.innerHTML = `
      <div class="pp-row2"><label class="field"><span>Tên video</span><input data-pf="name" value="${esc(f.name)}" placeholder="Video hậu kỳ"></label>
        <label class="field"><span>Tỉ lệ khung</span><select data-pf="aspect">${opts(m.aspects, f.aspect)}</select></label></div>
      <div class="field"><span>Âm thanh</span><div class="mh-seg sm pp-seg">${m.audio_modes.map(a => `<button class="${f.audio === a.value ? 'on' : ''}" data-pp-audio="${a.value}" type="button">${esc(a.label)}</button>`).join('')}</div></div>
      ${f.audio === 'tts' ? `<div class="pp-row3"><label class="field"><span>Giọng đọc</span><select data-pf="voice">${opts(m.voices, f.voice)}</select></label>
        <label class="field"><span>Tốc độ đọc</span><select data-pf="rate">${opts(m.rates, f.rate)}</select></label>
        <div class="field"><span>&nbsp;</span><button class="btn ghost sm" data-act="pp-voice" type="button">▶ Nghe thử</button></div></div>`
      : `<small class="muted">${f.audio === 'original' ? 'Giữ nguyên giọng nói / âm thanh gốc trong từng clip; nhạc nền tự nhỏ lại để không lấn tiếng gốc.' : 'Không có giọng nói — chỉ nhạc nền và âm chuyển cảnh.'}</small>`}
      <div class="pp-checks"><label class="check"><input type="checkbox" data-pf="subtitles" ${f.subtitles ? 'checked' : ''}> Phụ đề</label>
        <label class="check"><input type="checkbox" data-pf="bgm" ${f.bgm ? 'checked' : ''}> Nhạc nền</label>
        ${f.bgm ? `<label class="pp-range" title="Âm lượng nhạc nền"><input type="range" data-pf="bgm_volume" min="0" max="0.4" step="0.01" value="${f.bgm_volume}"><small id="ppBgmVol">${Math.round(f.bgm_volume * 100)}%</small></label>
          <button class="btn ghost sm" data-act="bgm-open" type="button" title="${esc(H.s.bgm_dir)}">📂 Nhạc</button>` : ''}</div>
      <div class="pp-box"><b class="pp-h">Chuyển cảnh khi ghép</b>
        <div class="pp-row4"><label class="field"><span>Kiểu chuyển cảnh</span><select data-pf="transition">${opts(m.transitions, f.transition)}</select></label>
          <label class="field"><span>Thời lượng</span><select data-pf="transition_duration">${opts(m.durations.map(d => ({ value: d, label: `${String(d).replace('.', ',')} giây` })), f.transition_duration)}</select></label>
          <label class="field"><span>Âm chuyển cảnh</span><div class="pp-inline"><select data-pf="transition_sound">${opts(m.sounds, f.transition_sound)}</select>
            <button class="btn ghost sm" data-act="pp-sound" type="button" title="Nghe thử âm chuyển cảnh">🔊</button></div></label>
          <label class="field"><span>Âm lượng âm chuyển · <b id="ppSndVol">${Math.round(f.transition_volume * 100)}%</b></span>
            <input type="range" data-pf="transition_volume" min="0" max="1.5" step="0.05" value="${f.transition_volume}"></label></div></div>
      <div class="pp-box ${f.post_ai ? 'on' : ''}"><div class="pp-aihead"><label class="mh-switch"><input type="checkbox" data-pf="post_ai" ${f.post_ai ? 'checked' : ''}><i></i> <b>✨ Hậu kỳ AI sau bước ghép</b></label>
          <span class="mh-pill ${f.post_ai ? 'ok' : ''}">${f.post_ai ? 'ĐANG BẬT' : 'ĐANG TẮT'}</span></div>
        <small class="muted">Muse đọc lời dẫn + nội dung từng cảnh: viết câu hook đầu video, tô nổi từ khoá trên phụ đề, gắn hiệu ứng âm thanh, chọn mức nhạc nền. Cảnh không lời vẫn có hook + hiệu ứng; HyperFrames dựng đồ hoạ động cả khi không lời. Muse lỗi thì vẫn ghép bình thường.</small>
        ${f.post_ai ? `<label class="field"><span>Kiểu hậu kỳ</span><select data-pf="post_style">${opts(m.post_styles, f.post_style)}</select></label>
          ${f.post_style === 'hyperframes' ? `<small class="pp-hf ${P.hf && P.hf.node_ok && P.hf.ffprobe ? 'ok' : ''}">${hfText(P.hf)}</small>` : ''}
          <div class="pp-checks"><label class="check"><input type="checkbox" data-pf="post_subs" ${f.post_subs ? 'checked' : ''}> Phụ đề nổi bật</label>
            <label class="check"><input type="checkbox" data-pf="post_audio" ${f.post_audio ? 'checked' : ''}> Âm thanh nổi bật</label></div>` : ''}</div>
      ${(() => {  // đóng logo: ô logo · khung video thu nhỏ đúng tỉ lệ, bấm góc để chọn vị trí · tóm tắt
        const corners = m.logo_corners || [];
        const label = (corners.find(c => c.value === f.logo_corner) || {}).label || '';
        const ratio = { '16:9': '16 / 9', '1:1': '1 / 1' }[f.aspect] || '9 / 16';
        return `<div class="pp-box pp-logo ${f.logo ? 'on' : ''}" data-pp-logo-drop>
        <div class="pp-logohead"><b class="pp-h">🏷 Đóng logo lên video</b>
          <span class="mh-pill ${f.logo ? 'ok' : ''}">${f.logo ? `Đang đóng · ${esc(label)}` : 'Chưa có logo'}</span></div>
        <div class="pp-logogrid">
          <div class="pp-logocard">${f.logo ? `<span class="pp-logoimg" title="Logo"><img src="${esc(f.logo_url)}" alt=""></span>
              <div class="pp-logobtns"><button class="btn ghost sm" data-act="pp-logo" type="button">Đổi</button><button class="btn ghost sm st-pdel" data-act="pp-logo-rm" type="button">Bỏ</button></div>`
            : `<button class="pp-logoadd" data-act="pp-logo" type="button"><b>＋</b>Chọn logo<small>hoặc kéo thả ảnh</small></button>`}</div>
          <div class="pp-frame ${f.logo ? '' : 'off'}" style="aspect-ratio:${ratio}" title="Bấm vào góc để chọn vị trí logo">
            ${corners.map(c => `<button class="pp-corner ${c.value} ${f.logo_corner === c.value ? 'on' : ''}" data-pp-corner="${c.value}" type="button" title="${esc(c.label)}" ${f.logo ? '' : 'disabled'}>
              ${f.logo_corner === c.value && f.logo ? `<img src="${esc(f.logo_url)}" alt="">` : '<i></i>'}</button>`).join('')}
            <span class="pp-subzone">phụ đề</span></div>
          <div class="pp-logonote"><b>${f.logo ? esc(label) : 'Vị trí logo'}</b>
            <small class="muted">Bấm vào góc trong khung để đổi vị trí. Logo rộng ~${f.aspect === '16:9' ? '10' : '18'}% khung, cách mép một khoảng an toàn, góc dưới chừa chỗ phụ đề.</small>
            <small class="muted">PNG nền trong suốt đẹp nhất · đóng sau cùng (cả khi dùng HyperFrames).</small></div>
        </div></div>`;
      })()}
      <button class="btn primary pp-go" data-act="pp-start" type="button" ${P.clips.length ? '' : 'disabled'}>🎬 Ghép & hậu kỳ${P.clips.length ? ` (${P.clips.length} cảnh)` : ''}</button>`;
  }
  function renderPostJobs() {
    const P = H.post;
    const box = $('#mhPostJobs');
    if (!box) return;
    const st = P.state || { jobs: [], done: [] };
    const live = st.jobs.filter(j => ['queued', 'running'].includes(j.status) || (['failed', 'cancelled'].includes(j.status) && Date.now() - j.created_at < 3600e3));
    clearTimeout(P.poll);  // dự phòng sự kiện: còn video đang làm → hỏi lại trạng thái mỗi 2 giây
    if (st.jobs.some(j => ['queued', 'running'].includes(j.status))) {
      P.poll = setTimeout(async () => {
        if (H.tab !== 'post') return;
        const r = await api('mhub_post_state');
        if (r.ok) { P.state = r.state; renderPostJobs(); }
      }, 2000);
    }
    const SL = { queued: 'Chờ', running: 'Đang làm', failed: 'Lỗi', cancelled: 'Đã dừng', done: 'Xong' };
    box.innerHTML = `${live.length ? `<div class="mp-title"><b>Đang hậu kỳ</b></div>
      <div class="pp-live">${live.map(j => `<div class="mp-run pp-job"><div class="mp-run-top"><span class="mh-status ${j.status === 'running' ? 'processing' : j.status === 'failed' ? 'failed' : 'queued'}">${SL[j.status]}</span>
          <p><b>${esc(j.name)}</b> · ${j.clips} cảnh · ${esc(j.stage)}</p><b class="mp-time">${j.pct}%</b>
          ${['queued', 'running'].includes(j.status) ? `<button class="btn ghost sm" data-pp-cancel="${esc(j.id)}" type="button">■ Dừng</button>` : ''}</div>
        <div class="mp-bar"><i style="width:${j.pct}%"></i></div>
        ${j.error ? `<small class="mh-err">${esc(j.error)}</small>` : `<small class="mp-last">${esc(((j.log || []).slice(-1)[0] || '').replace(/^\d\d:\d\d:\d\d\s*/, ''))}</small>`}</div>`).join('')}</div>` : ''}
      <div class="mp-title"><b>Video hậu kỳ đã làm</b><small class="muted">${st.done.length} video · cũng có trong Thư viện video</small></div>
      <div class="pp-done">${st.done.length ? st.done.map((d, i) => `<figure class="pp-out">
          <video src="${esc(d.url)}" controls preload="metadata"></video>
          <figcaption><div><b title="${esc(d.title)}">${esc(d.title)}</b><small class="muted">${Math.round(d.duration)}s · ${esc(d.aspect)} · ${d.clips} cảnh${d.post && d.post.model ? ' · ✨ AI' : ''}</small></div>
            <button class="btn ghost sm" data-pp-open="${esc(d.path)}" type="button" title="Mở thư mục, chọn sẵn file">📂</button></figcaption>
          <div class="pp-outacts"><button class="btn ghost sm" data-pp-redo="${i}" type="button" title="Nạp lại cảnh + lời đọc + thiết lập của video này để chỉnh và ghép bản mới">✎ Hậu kỳ lại</button>
            <button class="btn ghost sm" data-pp-useclip="${i}" type="button" title="Thêm cả video này vào danh sách cảnh (hậu kỳ chồng lên / ghép nối)">＋ Dùng làm cảnh</button></div></figure>`).join('')
        : '<small class="mp-idle">Chưa có video hậu kỳ nào.</small>'}</div>`;
  }
  async function postAddFiles(paths) {
    if (!paths || !paths.length) return;
    const r = await api('mhub_post_probe', paths);
    const durs = r.ok ? Object.fromEntries(r.items.map(x => [x.path, x.duration])) : {};
    H.post.clips = [...H.post.clips, ...paths.map(p => ({ path: p, url: '', title: fileName(p).replace(/\.\w+$/, ''), text: '', dur: durs[p] || 0 }))].slice(0, 40);
    postSave(); renderPostClips(); renderPostOpts();
  }

  // chọn video cho Hậu kỳ: nhóm theo kịch bản (cảnh đúng thứ tự) + lọc dự án; số trên ô = thứ tự ghép
  async function postLibDialog(project = H.s.current) {
    const r = await api('mhub_post_sources', project);
    if (!r.ok) return toast(r.error, 'error');
    const src = r.sources;
    const items = [];   // mọi video chọn được (chỉ số = data-ppi)
    const order = [];   // chỉ số theo thứ tự đã chọn
    const add = (v, extra) => items.push({ ...v, ...extra }) - 1;
    const tile = (k, label, sub) => `<button class="pp-tile" data-ppi="${k}" type="button" title="${esc(items[k].title)}">
        <img src="${esc(thumbUrl(items[k].url, 320))}" alt="" loading="lazy" decoding="async"><span class="pp-badge"></span>
        <span class="pp-tlabel">${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ''}</button>`;
    const proj = p => (project ? '' : ` · ${projName(p)}`);
    const singles = [];  // kịch bản chỉ 1 video → chung 1 lưới (tên + giờ bên dưới), khỏi mỗi kịch bản 1 khối
    const groupsHtml = src.groups.map(g => {
      const all = g.lines.map(lineText).filter(Boolean).join(' ');
      if (g.scenes.length + g.outputs.length === 1) {
        const v = g.scenes[0] || { ...g.outputs[0], video: true };
        singles.push(tile(add(v, { title: g.title, text: all }), g.title, `${fmt(v.finished_at || g.created_at)}${proj(g.project)}`));
        return '';
      }
      const ids = g.scenes.map(s => add(s, { title: `${g.title} · ${sceneLabel(s)}`, text: s.role === 'scene' ? lineText(g.lines[s.scene - 1]) : all }));
      const outs = g.outputs.map(o => add({ ...o, video: true }, { title: `${g.title} · ${(o.label || 'bản ghép').toLowerCase()}`, text: all }));
      return `<section class="pp-grp"><div class="pp-grphead"><b>🎬 ${esc(g.title)}</b>
          <small class="muted">${g.versions > 1 ? `bản ${g.version}/${g.versions} · ` : ''}${g.scenes.length} cảnh · ${esc(fmt(g.created_at))}${project ? '' : ` · ${esc(projName(g.project))}`}</small>
          <span class="mh-top-sp"></span>${ids.length > 1 ? `<button class="btn ghost sm" data-ppg="${ids.join(',')}" type="button">＋ Chọn cả kịch bản (đúng thứ tự cảnh)</button>` : ''}</div>
        <div class="pp-tiles">${ids.map(k => tile(k, sceneLabel(items[k]), String(g.lines[items[k].scene - 1] || '').replace(/\s+—\s+Lời thoại:.*/, '').slice(0, 70) || fmt(items[k].finished_at))).join('')}${outs.map(k => tile(k, items[k].label || 'Bản đã ghép', '')).join('')}</div></section>`;
    }).join('');
    const otherIds = src.others.map(o => add(o, { title: o.label || fileName(o.path).replace(/\.\w+$/, ''), text: '' }));
    const projOpts = H.s.projects.map(p => `<option value="${esc(p.id)}" ${p.id === project ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
    openModal('THƯ VIỆN', 'Chọn video để hậu kỳ', `<div class="pp-pickbar">
        <label class="field"><span>Dự án</span><select id="ppProj"><option value="" ${project ? '' : 'selected'}>Tất cả dự án</option>${projOpts}</select></label>
        <small class="muted">Bấm vào video để chọn — <b>số trên ô là thứ tự ghép</b>; bấm lại để bỏ. Video theo kịch bản đã xếp sẵn Cảnh 1, 2, 3…</small></div>
      <div class="pp-pickwrap">${groupsHtml}
        ${singles.length + otherIds.length ? `<section class="pp-grp pp-flat"><div class="pp-grphead"><b>Video</b><small class="muted">${singles.length + otherIds.length} video · theo số kịch bản, rồi video lẻ mới nhất trước</small></div>
          <div class="pp-tiles">${singles.join('')}${otherIds.map(k => tile(k, items[k].title, fmt(items[k].finished_at) + proj(items[k].project))).join('')}</div></section>` : ''}
        ${items.length ? '' : '<div class="empty">Dự án này chưa có video nào.</div>'}</div>
      <div class="ab-row pp-pickfoot"><small id="ppPickInfo" class="muted"></small><span class="mh-top-sp"></span>
        <button class="btn ghost sm" id="ppPickClear" type="button">Bỏ chọn</button>
        <button class="btn primary" id="ppLibAdd" type="button">Thêm 0 video</button></div>`);
    const paint = () => {
      $$('#modalBody .pp-tile').forEach(b => {
        const n = order.indexOf(+b.dataset.ppi);
        b.classList.toggle('on', n >= 0);
        b.querySelector('.pp-badge').textContent = n >= 0 ? n + 1 : '';
      });
      $('#ppPickInfo').textContent = order.length ? `Đã chọn ${order.length} video — ghép theo thứ tự số` : 'Chưa chọn video nào';
      $('#ppLibAdd').disabled = !order.length;
      $('#ppLibAdd').textContent = `Thêm ${order.length} video`;
    };
    paint();
    $('#modalBody').onchange = e => { if (e.target.id === 'ppProj') postLibDialog(e.target.value); };
    $('#modalBody').onclick = e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.ppi !== undefined) {
        const k = +b.dataset.ppi, n = order.indexOf(k);
        if (n >= 0) order.splice(n, 1); else order.push(k);
        return paint();
      }
      if (b.dataset.ppg) { b.dataset.ppg.split(',').map(Number).forEach(k => { if (!order.includes(k)) order.push(k); }); return paint(); }
      if (b.id === 'ppPickClear') { order.length = 0; return paint(); }
      if (b.id === 'ppLibAdd') {
        H.post.clips = [...H.post.clips, ...order.map(k => ({ path: items[k].path, url: items[k].url, title: items[k].title, text: items[k].text || '', desc: items[k].prompt || '' }))].slice(0, 40);
        postSave(); closeModal(); renderPostClips(); renderPostOpts();
      }
    };
  }
  async function postStart() {
    const P = H.post;
    if (!P.clips.length) return toast('Thêm ít nhất 1 video', 'warn');
    const noText = !P.clips.some(c => (c.text || '').trim());
    if (P.form.audio === 'tts' && noText && !confirm('Chưa nhập lời đọc cho cảnh nào — video sẽ không có giọng đọc. Vẫn ghép?')) return;
    if (P.form.post_ai && noText) toast('Chưa có lời đọc / lời thoại → Hậu kỳ AI không tô từ khoá được; Muse làm hook + hiệu ứng âm thanh + mức nhạc theo nội dung cảnh' + (P.form.post_style === 'hyperframes' ? ' và HyperFrames dựng đồ hoạ động (hook, tiêu đề, thẻ kết)' : ''), 'warn');
    const r = await api('mhub_post_start', { ...P.form, clips: P.clips.map(c => ({ path: c.path, text: c.text, title: c.title, url: c.url, desc: c.desc || '' })), show_browser: !!H.s.settings.show_browser });
    if (!r.ok) return toast(r.error, 'error');
    toast('Đã đưa vào hậu kỳ — theo dõi tiến độ bên dưới', 'ok');
    const st = await api('mhub_post_state');
    if (st.ok) P.state = st.state;
    renderPostJobs();
    const jobs = $('#mhPostJobs');
    if (jobs) jobs.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  Object.assign(MH, { hfText, showPost, renderPost, renderPostClips, renderPostOpts, renderPostJobs, postAddFiles, postLibDialog, postStart });
})();
