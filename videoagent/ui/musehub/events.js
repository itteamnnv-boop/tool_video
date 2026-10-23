/* Studio Muse AI · sự kiện (click / change / input / kéo thả) cho mọi tab (tách từ musehub.js — dùng chung window.MH + helper của app.js). */
(() => {
  'use strict';
  const MH = window.MH;
  const { H, prompts, projTasks, sel, projGroups, POST_DEF, postSave, fileName } = MH;  // khai báo ở core.js
  const kForm = (...a) => MH.kForm(...a);  // ở script.js
  // hàm ở file khác — gọi qua MH lúc chạy
  const show = (...a) => MH.show(...a);
  const renderAll = (...a) => MH.renderAll(...a);
  const renderTop = (...a) => MH.renderTop(...a);
  const composeCount = (...a) => MH.composeCount(...a);
  const renderCompose = (...a) => MH.renderCompose(...a);
  const renderDetected = (...a) => MH.renderDetected(...a);
  const visibleTasks = (...a) => MH.visibleTasks(...a);
  const renderQueue = (...a) => MH.renderQueue(...a);
  const openDetail = (...a) => MH.openDetail(...a);
  const kOutline = (...a) => MH.kOutline(...a);
  const kCount = (...a) => MH.kCount(...a);
  const renderKForm = (...a) => MH.renderKForm(...a);
  const previewDialog = (...a) => MH.previewDialog(...a);
  const renderGroups = (...a) => MH.renderGroups(...a);
  const deleteGroups = (...a) => MH.deleteGroups(...a);
  const dropImages = (...a) => MH.dropImages(...a);
  const renderProgress = (...a) => MH.renderProgress(...a);
  const renderSample = (...a) => MH.renderSample(...a);
  const samplePrepare = (...a) => MH.samplePrepare(...a);
  const sampleWrite = (...a) => MH.sampleWrite(...a);
  const sampleForms = (...a) => MH.sampleForms(...a);
  const renderPost = (...a) => MH.renderPost(...a);
  const renderPostClips = (...a) => MH.renderPostClips(...a);
  const renderPostOpts = (...a) => MH.renderPostOpts(...a);
  const renderPostJobs = (...a) => MH.renderPostJobs(...a);
  const postAddFiles = (...a) => MH.postAddFiles(...a);
  const postLibDialog = (...a) => MH.postLibDialog(...a);
  const postStart = (...a) => MH.postStart(...a);
  const renderLadi = (...a) => MH.renderLadi(...a);
  const ladiForms = (...a) => MH.ladiForms(...a);
  const ladiGenerate = (...a) => MH.ladiGenerate(...a);
  const renderAssetTry = (...a) => MH.renderAssetTry(...a);
  const renderAssets = (...a) => MH.renderAssets(...a);
  const pickImages = (...a) => MH.pickImages(...a);
  const charDialog = (...a) => MH.charDialog(...a);
  const tplDialog = (...a) => MH.tplDialog(...a);
  const projectsDialog = (...a) => MH.projectsDialog(...a);
  const loadLibrary = (...a) => MH.loadLibrary(...a);
  const libSelect = (...a) => MH.libSelect(...a);
  const renderLibrary = (...a) => MH.renderLibrary(...a);
  const paintLibSel = (...a) => MH.paintLibSel(...a);
  const openLibViewer = (...a) => MH.openLibViewer(...a);
  const mergeDialog = (...a) => MH.mergeDialog(...a);
  const renderAccounts = (...a) => MH.renderAccounts(...a);

  // ------------------------------------------------------------ sự kiện
  function bind() {
    H.bound = true;
    const page = $('#page-mstudio');
    page.addEventListener('click', async e => {
      if (e.target.closest('#mstudioBody')) return;  // tab Kịch bản do ui/studio.js xử lý
      const b = e.target.closest('button, [data-tab-go], [data-zoom]');
      if (!b) {
        const row = e.target.closest('.mh-task');
        if (row && !e.target.matches('input')) openDetail(row.dataset.task);
        const lv = e.target.closest('[data-lib-view]');
        if (lv && !e.target.closest('.mh-libsel')) {
          if (H.lib.justMarq) return;  // vừa tô khối xong — không mở trình xem
          if (e.ctrlKey || e.metaKey || e.shiftKey) return libSelect(+lv.dataset.libView, e);
          return openLibViewer(+lv.dataset.libView);
        }
        const pt = e.target.closest('[data-ptask]');
        if (pt) return openDetail(pt.dataset.ptask);
        const grow = e.target.closest('.mk-row');
        if (grow && !e.target.matches('input')) { H.g.cur = grow.dataset.gcur; return renderGroups(); }
        return;
      }
      const d = b.dataset;
      if (d.tab || d.tabGo) {
        H.tab = d.tab || d.tabGo;
        try { localStorage.setItem('va.mhub.tab', H.tab); } catch { /* bỏ qua */ }
        return renderAll();
      }
      const act = d.act;
      if (act === 'projects') return projectsDialog();
      if (act === 'stop') { if (!confirm('Dừng tất cả: huỷ task đang chạy và tạm dừng hàng đợi?')) return; H.s = (await api('mhub_stop')).state; return renderAll(); }
      if (act === 'resume') { H.s = (await api('mhub_resume')).state; toast('Hàng đợi đang chạy', 'ok'); return renderAll(); }
      if (act === 'folder') return api('mhub_open', '');
      if (act === 'open-settings') return openSettings();
      if (d.kind) { H.c.kind = d.kind; return renderCompose(); }
      if (act === 'idea-go') {
        const c = H.c;
        if (!c.idea.trim()) return toast('Nhập ý tưởng / kịch bản trước', 'warn');
        c.ideaBusy = true; renderCompose();
        const r = await api('mhub_timeline', { idea: c.idea, count: c.ideaCount, seconds: c.duration, ratio: c.ratio, style: c.ideaStyle }, !!H.s.settings.show_browser);
        c.ideaBusy = false;
        if (!r.ok) { renderCompose(); return toast(r.error, 'error'); }
        const block = r.result.prompts.join('\n\n');  // dòng trống = tách task
        c.text = c.text.trim() ? `${c.text.trim()}\n\n${block}` : block;
        renderCompose();
        return toast(`Muse đã viết ${r.result.prompts.length} prompt timeline — xem / sửa rồi bấm “Thêm task vào hàng đợi”`, 'ok');
      }
      if (d.pair) { H.c.pairing = d.pair; return renderCompose(); }
      if (d.rmImg !== undefined) { H.c.images.splice(+d.rmImg, 1); return renderCompose(); }
      if (act === 'add-img') { H.c.images = [...H.c.images, ...await pickImages()]; return renderCompose(); }
      if (act === 'save-tpl') { if (!H.c.text.trim()) return toast('Ô prompt đang trống', 'warn'); return tplDialog(null, H.c.text); }
      if (act === 'add-tasks') {
        const res = await api('mhub_add', { kind: H.c.kind, ratio: H.c.ratio, duration: H.c.duration, prompts: prompts(H.c.text), images: H.c.images.map(i => i.path), pairing: H.c.pairing });
        if (!res.ok) return toast(res.error, 'error');
        toast(`Đã thêm ${res.result.created.length} task vào hàng đợi`, 'ok');
        H.c.text = ''; H.c.images = [];
        const st = await api('mhub_state');  // vẽ ngay hàng đợi mới (không chờ sự kiện từ backend)
        if (st.ok) H.s = st.state;
        renderTop(); renderCompose(); return renderQueue();
      }
      if (d.filter) { H.filter = d.filter; return renderQueue(); }
      if (act === 'sel-failed' || act === 'sel-queued') {
        const st = act === 'sel-failed' ? 'failed' : 'queued';
        H.sel = new Set(projTasks().filter(t => t.status === st).map(t => t.id));
        return renderQueue();
      }
      if (d.bulk) {
        if (d.bulk === 'delete' && !confirm(`Xoá ${H.sel.size} task (file đã tải vẫn giữ)?`)) return;
        const res = await api('mhub_tasks', [...H.sel], d.bulk);
        if (res.ok) H.s = res.state;
        if (d.bulk === 'delete') H.sel.clear();
        return renderQueue();
      }
      // kịch bản
      if (d.kmode) { H.k.mode = d.kmode; return renderKForm(); }
      if (d.motion) { const m = d.motion; H.k.motions = H.k.motions.includes(m) ? H.k.motions.filter(x => x !== m) : [...H.k.motions, m]; return renderKForm(); }
      if (act === 'k-add-img') { H.k.images = [...H.k.images, ...await pickImages()].slice(0, 30); return renderKForm(); }
      if (act === 'k-clear-img') { H.k.images = []; return renderKForm(); }
      if (d.krm !== undefined) { H.k.images.splice(+d.krm, 1); return renderKForm(); }
      if (act === 'bgm-open') return api('mhub_bgm', 'open');
      if (act === 'bgm-pick') { const r = await api('mhub_bgm', 'pick'); if (r.ok && r.state) { H.s = r.state; renderKForm(); } return; }
      if (act === 'k-preview' || act === 'k-queue') {
        const res = await api('mhub_script', { ...kForm(), dry: act === 'k-preview' });
        if (!res.ok) return toast(res.error, 'error');
        if (act === 'k-preview') return previewDialog(res.result.preview);
        toast(`Đã đưa ${res.result.groups} video (${res.result.created.length} lệnh Muse) vào hàng đợi`, 'ok');
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        renderTop(); return renderGroups();
      }
      if (d.gapprove) { const r = await api('mhub_approve', d.gapprove); if (!r.ok) return toast(r.error, 'error'); H.s = r.state; toast('Đã duyệt — video vào hàng đợi', 'ok'); return renderGroups(); }
      if (d.gdel) return deleteGroups([d.gdel], 'video này');
      if (d.gopen) return api('mhub_open', d.gopen);
      if (d.gfilter) { H.g.filter = d.gfilter; return renderGroups(); }
      if (d.gretry) { const r = await api('mhub_tasks', d.gretry.split(','), 'retry'); if (r.ok) H.s = r.state; toast('Đã đưa phần lỗi chạy lại', 'ok'); return renderGroups(); }
      if (d.taskOpen) return openDetail(d.taskOpen);
      // tiến trình
      if (d.pall !== undefined) { H.prog.all = d.pall === '1'; return renderProgress(); }
      if (d.pcancel) { const r = await api('mhub_tasks', [d.pcancel], 'cancel'); if (r.ok) H.s = r.state; return renderProgress(); }
      if (d.pretry || d.pretryFailed) { const r = await api('mhub_tasks', (d.pretry || d.pretryFailed).split(','), 'retry'); if (r.ok) H.s = r.state; toast('Đã đưa vào hàng đợi chạy lại', 'ok'); return renderProgress(); }
      if (d.openTaskFile) return api('mhub_open', d.openTaskFile);
      if (act === 'g-sel-all') { projGroups().forEach(g => H.g.sel.add(g.id)); return renderGroups(); }
      if (act === 'g-sel-none') { H.g.sel.clear(); return renderGroups(); }
      if (act === 'g-del-sel') return deleteGroups([...H.g.sel], `${H.g.sel.size} video đã chọn`);
      if (act === 'g-del-all') return deleteGroups(projGroups().map(g => g.id), 'tất cả video của dự án');
      if (act === 'g-clear-done') {
        for (const g of projGroups().filter(x => x.status === 'done')) await api('mhub_group_delete', g.id);
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        return renderGroups();
      }
      if (d.zoom) return openModal('STORYBOARD', 'Ảnh storyboard', `<div class="viewer"><img src="${esc(d.zoom)}" alt=""></div>`);
      // LadiPage
      if (act === 'ladi-go') { H.ladi.url = ($('#mhLadiUrl') || {}).value || ''; if (!H.ladi.url.trim()) return toast('Dán link landing page trước', 'warn'); return ladiGenerate(); }
      if (act === 'ladi-text') { H.ladi.showText = !H.ladi.showText; return renderLadi(); }
      if (d.limg) {
        const u = d.limg, L = H.ladi;
        if (L.picked.includes(u)) L.picked = L.picked.filter(x => x !== u);
        else if (L.picked.length + L.local.length >= 3) return toast('Chọn tối đa 3 ảnh sản phẩm', 'warn');
        else L.picked = [...L.picked, u];
        return renderLadi();
      }
      if (act === 'ladi-add-img') { H.ladi.local = [...H.ladi.local, ...await pickImages()].slice(0, 3); return renderLadi(); }
      if (d.lrm !== undefined) { H.ladi.local.splice(+d.lrm, 1); return renderLadi(); }
      if (act === 'ladi-all') { H.ladi.checked = new Set(H.ladi.scripts.scripts.map((_, i) => i)); return renderLadi(); }
      if (act === 'ladi-preview' || act === 'ladi-queue') {
        const forms = await ladiForms(act === 'ladi-preview');
        if (!forms) return;
        const all = [];
        let groups = 0;
        for (const f of forms) {
          const r = await api('mhub_script', f);
          if (!r.ok) return toast(r.error, 'error');
          if (f.dry) all.push(...r.result.preview); else groups += r.result.groups;
        }
        if (act === 'ladi-preview') return previewDialog(all);
        toast(`Đã đưa ${groups} video vào hàng đợi — xem ở tab Kịch bản`, 'ok');
        H.tab = 'script';
        return show();
      }
      // hậu kỳ
      if (act === 'pp-lib') return postLibDialog();
      if (act === 'pp-pick') return postAddFiles(await api('pick_files', 'videos'));
      if (act === 'pp-clear') { if (!confirm('Bỏ hết video khỏi danh sách cảnh?')) return; H.post.clips = []; postSave(); renderPostClips(); return renderPostOpts(); }
      if (d.ppUp !== undefined || d.ppDown !== undefined) {
        const i = +(d.ppUp ?? d.ppDown), j = d.ppUp !== undefined ? i - 1 : i + 1, c = H.post.clips;
        [c[i], c[j]] = [c[j], c[i]]; postSave(); return renderPostClips();
      }
      if (d.ppRm !== undefined) { H.post.clips.splice(+d.ppRm, 1); postSave(); renderPostClips(); return renderPostOpts(); }
      if (d.ppAudio) { H.post.form.audio = d.ppAudio; postSave(); renderPostClips(); return renderPostOpts(); }
      if (act === 'pp-voice') {
        const f = H.post.form, text = (H.post.clips.find(c => (c.text || '').trim()) || {}).text || '';
        const r = await api('studio_voice_preview', text, '', f.voice, f.rate);
        if (!r.ok) return toast(r.error, 'error');
        return new Audio(r.data).play().catch(() => {});
      }
      if (act === 'pp-sound') {
        const r = await api('transition_sound_preview', H.post.form.transition_sound);
        if (!r.ok) return toast(r.error, 'error');
        if (!r.data) return toast('Đang chọn “không có” âm chuyển cảnh', 'warn');
        const a = new Audio(r.data); a.volume = Math.min(1, H.post.form.transition_volume); return a.play().catch(() => {});
      }
      if (act === 'pp-start') return postStart();
      if (act === 'pp-logo') {
        const [im] = await pickImages();
        if (!im) return;
        Object.assign(H.post.form, { logo: im.path, logo_url: im.url });
        postSave(); return renderPostOpts();
      }
      if (d.ppCorner) { H.post.form.logo_corner = d.ppCorner; postSave(); return renderPostOpts(); }
      if (act === 'pp-logo-rm') { Object.assign(H.post.form, { logo: '', logo_url: '' }); postSave(); return renderPostOpts(); }
      if (d.ppCancel) { const r = await api('mhub_post_cancel', d.ppCancel); if (r.ok) { H.post.state = r.state; renderPostJobs(); } return; }
      if (d.ppRedo !== undefined) {
        const v = H.post.state.done[+d.ppRedo], f = v && v.form;
        if (!f || !(f.clips || []).length) return toast('Video này không còn dữ liệu cảnh để hậu kỳ lại — dùng “＋ Dùng làm cảnh”', 'warn');
        if (H.post.clips.length && !confirm(`Thay ${H.post.clips.length} cảnh đang soạn bằng ${f.clips.length} cảnh của “${v.title}”?`)) return;
        const opts = Object.fromEntries(Object.entries(f.options || {}).filter(([k]) => k in POST_DEF));
        const n = H.post.state.done.filter(x => x.title.replace(/ \(bản \d+\)$/, '') === v.title.replace(/ \(bản \d+\)$/, '')).length + 1;
        H.post.clips = f.clips.map(c => ({ path: c.path, url: c.url || '', title: c.title || fileName(c.path), text: c.text || '', desc: c.desc || '' }));
        H.post.form = { ...POST_DEF, ...opts, name: `${v.title.replace(/ \(bản \d+\)$/, '')} (bản ${n})` };
        postSave(); renderPost();
        $('#mhPost').scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (f.rebuilt && opts.audio === 'original') toast('Video làm trước bản cập nhật: các cảnh đã chuẩn hoá không còn tiếng gốc — chọn Lồng tiếng AI hoặc Không lời', 'warn');
        return toast(`Đã nạp ${f.clips.length} cảnh + thiết lập — chỉnh rồi bấm “Ghép & hậu kỳ” để ra bản mới (bản cũ giữ nguyên)`, 'ok');
      }
      if (d.ppUseclip !== undefined) {
        const v = H.post.state.done[+d.ppUseclip];
        if (!v) return;
        H.post.clips = [...H.post.clips, { path: v.path, url: v.url, title: v.title, text: '', dur: v.duration }].slice(0, 40);
        postSave(); renderPostClips(); renderPostOpts();
        $('#mhPostClips').scrollIntoView({ behavior: 'smooth', block: 'start' });
        return toast(`Đã thêm “${v.title}” vào danh sách cảnh`, 'ok');
      }
      if (d.ppOpen) { const r = await api('mhub_post_open', d.ppOpen); if (!r.ok) toast(r.error, 'error'); return; }
      // video mẫu
      if (act === 'smp-pick') { const f = await api('pick_files', 'video'); if (f && f.length) return samplePrepare(f[0]); return; }
      if (act === 'smp-go') return samplePrepare((($('#mhSmpUrl') || {}).value || '').trim());
      if (act === 'smp-sheet') { H.smp.showSheet = !H.smp.showSheet; return renderSample(); }
      if (act === 'smp-add-img') { H.smp.images = [...H.smp.images, ...await pickImages()].slice(0, 2); return renderSample(); }
      if (d.srm !== undefined) { H.smp.images.splice(+d.srm, 1); return renderSample(); }
      if (act === 'smp-add-doc') {
        const files = await api('pick_files', 'docs');
        if (!files || !files.length) return;
        const r = await api('mhub_sample_docs', files);
        if (!r.ok) return toast(r.error, 'error');
        const have = new Set(H.smp.docs.map(x => x.path));
        H.smp.docs = [...H.smp.docs, ...r.docs.filter(x => !have.has(x.path))].slice(0, 5);
        return renderSample();
      }
      if (d.sdocRm !== undefined) { H.smp.docs.splice(+d.sdocRm, 1); return renderSample(); }
      if (act === 'smp-write') return sampleWrite();
      if (act === 'smp-all') { H.smp.checked = new Set(H.smp.scripts.scripts.map((_, i) => i)); return renderSample(); }
      if (act === 'smp-preview' || act === 'smp-queue') {
        const all = [];
        let groups = 0;
        for (const f of sampleForms(act === 'smp-preview')) {
          const r = await api('mhub_script', f);
          if (!r.ok) return toast(r.error, 'error');
          if (f.dry) all.push(...r.result.preview); else groups += r.result.groups;
        }
        if (act === 'smp-preview') return previewDialog(all);
        toast(`Đã đưa ${groups} video vào hàng đợi — xem ở tab Kịch bản / Tiến trình`, 'ok');
        H.tab = 'script';
        return show();
      }
      // tư liệu
      if (d.tplUse) {
        const tp = H.s.templates.find(x => x.id === d.tplUse);
        if (!tp) return;
        H.c.text = H.c.text.trim() ? `${H.c.text.trim()}\n\n${tp.text}` : tp.text;
        H.tab = 'studio';
        try { localStorage.setItem('va.mhub.tab', H.tab); } catch { /* bỏ qua */ }
        renderAll();
        return toast(`Đã chèn mẫu “${tp.name}” vào ô Prompt`, 'ok');
      }
      if (d.charCopy) { navigator.clipboard.writeText(d.charCopy).then(() => toast(`Đã sao chép “${d.charCopy}” — dán vào prompt để tự gắn ảnh`, 'ok'), () => {}); return; }
      if (act === 'char-new') return charDialog(null);
      if (d.charEdit) return charDialog(H.s.characters.find(c => c.id === d.charEdit));
      if (d.modelChar !== undefined) {  // chọn nhân vật làm người mẫu cố định ("" = ảnh tải lên); chọn nhân vật thì tự bật
        const r = await api('mhub_asset', 'model', d.modelChar ? { character: d.modelChar, on: true } : { character: '' });
        if (!r.ok) { toast(r.error, 'error'); return; }
        H.s = r.state; renderAssets();
        toast(d.modelChar ? 'Đã dùng nhân vật làm người mẫu cố định' : 'Người mẫu cố định: dùng ảnh tải lên');
        return;
      }
      if (d.charDel) { if (!confirm('Xoá nhân vật?')) return; const r = await api('mhub_asset', 'character_delete', { id: d.charDel }); if (r.ok) { H.s = r.state; renderAssets(); } return; }
      if (act === 'tpl-new') return tplDialog(null);
      if (d.tplEdit) return tplDialog(H.s.templates.find(t => t.id === d.tplEdit));
      if (d.tplDel) { if (!confirm('Xoá mẫu prompt?')) return; const r = await api('mhub_asset', 'template_delete', { id: d.tplDel }); if (r.ok) { H.s = r.state; renderAssets(); } return; }
      if (d.assetAdd || d.assetRm) {
        const kind = d.assetAdd || d.assetRm;
        let list = H.s[kind].images.map(i => i.path);
        if (d.assetAdd) list = [...list, ...(await pickImages()).map(i => i.path)];
        else list.splice(+d.i, 1);
        const r = await api('mhub_asset', kind, { images: list });
        if (!r.ok) return toast(r.error, 'error');
        H.s = r.state;
        return renderAssets();
      }
      // thư viện
      if (act === 'lib-reload') return loadLibrary();
      if (act === 'lib-all') { H.lib.sel = H.lib.items.map(i => i.path); return paintLibSel(); }
      if (act === 'lib-none') { H.lib.sel = []; H.lib.anchor = null; return paintLibSel(); }
      if (act === 'lib-move') {
        const to = ($('#mhLibMoveTo') || {}).value;
        const name = (H.s.projects.find(p => p.id === to) || {}).name || '';
        if (!to || !confirm(`Chuyển ${H.lib.sel.length} file sang dự án “${name}”?\nVideo thuộc kịch bản sẽ chuyển CẢ kịch bản (mọi cảnh + bản ghép). File trên máy giữ nguyên chỗ.`)) return;
        const r = await api('mhub_move', H.lib.sel, to);
        if (!r.ok) return toast(r.error, 'error');
        const x = r.result;
        toast(`Đã chuyển ${x.tasks} file${x.groups ? ` (${x.groups} kịch bản${x.extra ? `, kèm ${x.extra} cảnh cùng kịch bản` : ''})` : ''} sang “${name}”`, 'ok');
        H.lib.sel = []; H.lib.anchor = null;
        const st = await api('mhub_state'); if (st.ok) H.s = st.state;
        renderTop();
        return loadLibrary();
      }
      if (act === 'merge') return mergeDialog();
      if (d.libOpen) return api('mhub_open', d.libOpen);
      // tài khoản
      if (d.mode) { const r = await api('mhub_settings', { mode: d.mode }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (act === 'quota-all') { api('mhub_quota', ''); return toast('Đang đọc hạn mức các tài khoản (mở muse.ai ẩn, không tốn lượt)…'); }
      if (act === 'add-account') { toast('Tạo profile mới, tick “Muse (Meta)” rồi bấm Đăng nhập — tài khoản tự hiện ở Studio Muse AI'); return navigate('profiles'); }
      if (d.accQuota) return api('mhub_quota', d.accQuota);
      if (d.accLogin) { const r = await api('mhub_login', d.accLogin); if (!r.ok) toast(r.error, 'error'); }
    });
    page.addEventListener('change', async e => {
      const t = e.target;
      if (t.closest('#mstudioBody')) return;
      if (t.id === 'mhProject') { const r = await api('mhub_project', 'select', t.value); if (r.ok) { H.s = r.state; H.sel.clear(); renderAll(); } return; }
      if (t.id === 'mhRatio') { H.c.ratio = t.value; return; }
      if (t.id === 'mhDur') { H.c.duration = +t.value; if (H.c.ideaOn) renderCompose(); return; }
      if (t.id === 'mhIdeaOn') { H.c.ideaOn = t.checked; return renderCompose(); }
      if (t.id === 'mhIdeaCount') { H.c.ideaCount = +t.value; return renderCompose(); }
      if (t.dataset.gsel) { if (t.checked) H.g.sel.add(t.dataset.gsel); else H.g.sel.delete(t.dataset.gsel); return renderGroups(); }
      const kmap = { mhKMethod: 'method', mhKRatio: 'ratio', mhKDur: 'duration', mhKVoice: 'voice', mhKChar: 'character', mhKPresenter: 'presenter' };
      if (kmap[t.id]) { H.k[kmap[t.id]] = t.value; if (t.id === 'mhKDur') renderKForm(); return; }
      if (t.id === 'mhKVersions') { H.k.versions = Math.max(1, Math.min(5, +t.value || 1)); $('#mhKCount').textContent = kCount(); const o = $('#mhKOutline'); if (o) o.innerHTML = kOutline(); return; }
      if (t.id === 'mhKMerge') { H.k.merge = t.checked; return; }
      if (t.id === 'mhKBgm') { H.k.bgm = t.checked; return; }
      if (t.id === 'mhLadiNoPrice') {
        if (H.ladi.scripts && !confirm('Đổi “Không đọc giá” sẽ sinh lại kịch bản (mất chữ đã sửa). Tiếp tục?')) { t.checked = !t.checked; return; }
        H.ladi.noPrice = t.checked;
        return H.ladi.page ? ladiGenerate() : undefined;
      }
      if (t.dataset.pf) {
        const key = t.dataset.pf;
        H.post.form[key] = t.type === 'checkbox' ? t.checked : t.type === 'range' || key === 'transition_duration' ? +t.value : t.value;
        postSave();
        if (['bgm', 'post_ai', 'post_style'].includes(key)) renderPostOpts();
        return;
      }
      if (t.dataset.scheck !== undefined) { const i = +t.dataset.scheck; if (t.checked) H.smp.checked.add(i); else H.smp.checked.delete(i); return renderSample(); }
      const smap = { mhSmpClose: 'closeness', mhSmpCount: 'count', mhSmpScenes: 'scenes', mhSmpRatio: 'ratio', mhSmpDur: 'duration' };
      if (smap[t.id]) { H.smp[smap[t.id]] = t.value; return; }
      if (t.id === 'mhSmpNoPrice') { H.smp.noPrice = t.checked; return; }
      if (t.dataset.lcheck !== undefined) { const i = +t.dataset.lcheck; if (t.checked) H.ladi.checked.add(i); else H.ladi.checked.delete(i); return renderLadi(); }
      if (t.id === 'mhTpl' && t.value) {
        const tp = H.s.templates.find(x => x.id === t.value);
        if (tp) { H.c.text = H.c.text.trim() ? `${H.c.text.trim()}\n\n${tp.text}` : tp.text; renderCompose(); }
        return;
      }
      if (t.dataset.hubToggle) {
        const r = await api('mhub_asset', t.dataset.hubToggle, { on: t.checked });
        if (r.ok) { H.s = r.state; if (H.tab === 'assets') renderAssets(); else renderCompose(); }
        return;
      }
      if (t.dataset.sel) { if (t.checked) H.sel.add(t.dataset.sel); else H.sel.delete(t.dataset.sel); return renderQueue(); }
      if (t.dataset.act === 'sel-all') { visibleTasks().forEach(x => (t.checked ? H.sel.add(x.id) : H.sel.delete(x.id))); return renderQueue(); }
      if (t.dataset.libSel) {
        const p = t.dataset.libSel;
        H.lib.sel = t.checked ? [...H.lib.sel, p] : H.lib.sel.filter(x => x !== p);
        H.lib.anchor = H.lib.items.findIndex(i => i.path === p);
        return paintLibSel();
      }
      if (t.dataset.set) { const r = await api('mhub_settings', { [t.dataset.set]: t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.setBool) { const r = await api('mhub_settings', { [t.dataset.setBool]: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); } return; }
      if (t.dataset.accOn) { const r = await api('mhub_account', t.dataset.accOn, { enabled: t.checked }); if (r.ok) { H.s = r.state; renderAccounts(); renderTop(); } return; }
      if (t.dataset.accThreads) { const r = await api('mhub_account', t.dataset.accThreads, { threads: +t.value }); if (r.ok) { H.s = r.state; renderAccounts(); } }
    });
    // Thư viện: kéo chuột tô khối để chọn nhiều (Ctrl / Shift khi kéo = thêm vào lựa chọn cũ)
    page.addEventListener('mousedown', e => {
      if (e.button !== 0 || !e.target.closest('#mhLibrary') || e.target.closest('.mh-libhead, input, label, button, select')) return;
      const start = { x: e.clientX, y: e.clientY }, add = e.ctrlKey || e.metaKey || e.shiftKey;
      const base = add ? [...H.lib.sel] : [];
      let box = null, hits = [];
      e.preventDefault();  // không bôi đen chữ / kéo ảnh
      const move = ev => {
        const x1 = Math.min(start.x, ev.clientX), y1 = Math.min(start.y, ev.clientY);
        const x2 = Math.max(start.x, ev.clientX), y2 = Math.max(start.y, ev.clientY);
        if (!box) {
          if (x2 - x1 < 6 && y2 - y1 < 6) return;  // chưa kéo đủ xa → vẫn là bấm thường
          box = document.createElement('div');
          box.className = 'mh-marquee';
          document.body.appendChild(box);
        }
        Object.assign(box.style, { left: `${x1}px`, top: `${y1}px`, width: `${x2 - x1}px`, height: `${y2 - y1}px` });
        hits = [];
        $$('#mhLibrary .mh-libcell').forEach(c => {
          const r = c.getBoundingClientRect();
          const on = r.left < x2 && r.right > x1 && r.top < y2 && r.bottom > y1;
          c.classList.toggle('marq', on);
          if (on) hits.push(+c.dataset.libK);
        });
      };
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        if (!box) return;
        box.remove();
        const paths = hits.map(k => H.lib.items[k].path);
        H.lib.sel = [...base, ...paths.filter(p => !base.includes(p))];
        if (hits.length) H.lib.anchor = hits[hits.length - 1];
        H.lib.justMarq = true;
        setTimeout(() => { H.lib.justMarq = false; }, 0);  // bỏ qua cú click ngay sau khi nhả chuột
        paintLibSel();
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
    document.addEventListener('keydown', e => {  // Thư viện: Ctrl+A chọn tất cả · Esc bỏ chọn
      if (H.tab !== 'library' || $('#page-mstudio').classList.contains('hidden') || !$('#modal').classList.contains('hidden')
        || /input|textarea|select/i.test(e.target.tagName)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { e.preventDefault(); H.lib.sel = H.lib.items.map(i => i.path); paintLibSel(); }
      if (e.key === 'Escape' && H.lib.sel.length) { H.lib.sel = []; H.lib.anchor = null; paintLibSel(); }
    });
    document.addEventListener('keydown', e => {  // ← → chuyển file trong trình xem thư viện
      if (!$('#mhLibView') || $('#modal').classList.contains('hidden') || /input|textarea|select/i.test(e.target.tagName)) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const k = H.lib.view + (e.key === 'ArrowLeft' ? -1 : 1);
        if (H.lib.items[k]) { e.preventDefault(); openLibViewer(k); }
      }
    });
    // Hậu kỳ: kéo ⋮⋮ để đổi thứ tự cảnh
    const ppRow = e => e.target.closest && e.target.closest('.pp-clip');
    const ppMark = (row, after) => { $$('#mhPostClips .pp-clip').forEach(r => r.classList.remove('drop-before', 'drop-after')); if (row) row.classList.add(after ? 'drop-after' : 'drop-before'); };
    page.addEventListener('dragstart', e => {
      const g = e.target.closest && e.target.closest('[data-pp-drag]');
      if (!g) return;
      H.post.drag = +g.dataset.ppDrag;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', g.dataset.ppDrag);
      const row = g.closest('.pp-clip');
      e.dataTransfer.setDragImage(row, 24, 24);
      setTimeout(() => row.classList.add('dragging'), 0);
    });
    page.addEventListener('dragover', e => {
      const row = ppRow(e);
      if (H.post.drag == null || !row) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      ppMark(row, e.clientY > r.top + r.height / 2);
    });
    page.addEventListener('drop', e => {
      const row = ppRow(e);
      if (H.post.drag == null || !row) return;
      e.preventDefault();
      const from = H.post.drag, r = row.getBoundingClientRect();
      let to = +row.dataset.ppRow + (e.clientY > r.top + r.height / 2 ? 1 : 0);
      if (from < to) to -= 1;
      H.post.drag = null;
      if (to !== from) { const [c] = H.post.clips.splice(from, 1); H.post.clips.splice(to, 0, c); postSave(); }
      renderPostClips();
    });
    page.addEventListener('dragend', () => { if (H.post.drag == null && !$('#mhPostClips .dragging')) return; H.post.drag = null; ppMark(null); $$('#mhPostClips .dragging').forEach(r => r.classList.remove('dragging')); });
    page.addEventListener('loadedmetadata', e => {  // thời lượng video trong danh sách cảnh hậu kỳ
      const i = e.target.dataset && e.target.dataset.ppDur;
      if (i === undefined || !H.post.clips[+i]) return;
      H.post.clips[+i].dur = e.target.duration || 0;
      const el = $(`#ppDur${i}`); if (el) el.textContent = `${(e.target.duration || 0).toFixed(1)}s`;
    }, true);
    // Hậu kỳ: kéo thả ảnh logo vào khung "Đóng logo"
    page.addEventListener('dragover', e => { const z = e.target.closest && e.target.closest('[data-pp-logo-drop]'); if (z && H.post.drag == null) { e.preventDefault(); z.classList.add('over'); } });
    page.addEventListener('dragleave', e => { const z = e.target.closest && e.target.closest('[data-pp-logo-drop]'); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = e.target.closest && e.target.closest('[data-pp-logo-drop]');
      if (!z) return;
      e.preventDefault(); z.classList.remove('over');
      const [im] = await dropImages([...e.dataTransfer.files]);
      if (im) { Object.assign(H.post.form, { logo: im.path, logo_url: im.url }); postSave(); renderPostOpts(); }
    });
    // Tư liệu: kéo thả ảnh vào khung Người mẫu cố định / Ảnh luân phiên
    const poolZone = e => e.target.closest && e.target.closest('[data-asset-drop]');
    page.addEventListener('dragover', e => { const z = poolZone(e); if (!z || H.post.drag != null) return; e.preventDefault(); z.classList.add('over'); });
    page.addEventListener('dragleave', e => { const z = poolZone(e); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = poolZone(e);
      if (!z) return;
      e.preventDefault();
      z.classList.remove('over');
      const kind = z.dataset.assetDrop, cap = kind === 'model' ? H.s.max_images : 20;
      const imgs = await dropImages([...e.dataTransfer.files]);
      if (!imgs.length) return;
      const list = [...H.s[kind].images.map(i => i.path), ...imgs.map(i => i.path)];
      if (list.length > cap) toast(`Tối đa ${cap} ảnh — bỏ ${list.length - cap} ảnh cuối`, 'warn');
      const r = await api('mhub_asset', kind, { images: list.slice(0, cap) });
      if (!r.ok) return toast(r.error, 'error');
      H.s = r.state; renderAssets();
    });
    page.addEventListener('toggle', e => { if (e.target.classList && e.target.classList.contains('smp-analysis')) H.smp.openAnalysis = e.target.open; }, true);
    // kéo thả ảnh sản phẩm vào ô "Ảnh sản phẩm" (tab Kịch bản)
    const dropZone = e => e.target.closest && e.target.closest('#mhKDrop');
    page.addEventListener('dragover', e => { const z = dropZone(e); if (!z) return; e.preventDefault(); z.classList.add('over'); });
    page.addEventListener('dragleave', e => { const z = dropZone(e); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
    page.addEventListener('drop', async e => {
      const z = dropZone(e);
      if (!z) return;
      e.preventDefault();
      z.classList.remove('over');
      const imgs = await dropImages([...e.dataTransfer.files]);
      if (imgs.length) { H.k.images = [...H.k.images, ...imgs].slice(0, 30); renderKForm(); }
    });
    page.addEventListener('input', e => {
      if (e.target.id === 'mhText') {
        H.c.text = e.target.value;
        const n = prompts(H.c.text).length;
        const go = $('#mhCompose .mh-go');
        go.disabled = !n;
        go.textContent = `＋ Thêm ${n || ''} task vào hàng đợi`;
        $('#mhCount').innerHTML = composeCount(n);
        renderDetected();
      }
      if (e.target.id === 'mhSearch') { H.q = e.target.value; renderQueue(); }
      if (e.target.id === 'mhIdea') H.c.idea = e.target.value;
      if (e.target.id === 'mhATryIn') { H.atry = e.target.value; renderAssetTry(); }
      if (e.target.id === 'mhAq') {
        H.aq = e.target.value; renderAssets();
        const el = $('#mhAq'); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
      }
      if (e.target.id === 'mhIdeaStyle') H.c.ideaStyle = e.target.value;
      if (e.target.id === 'mhKText') { H.k.text = e.target.value; $('#mhKCount').textContent = kCount(); const o = $('#mhKOutline'); if (o) o.innerHTML = kOutline(); }
      if (e.target.id === 'mhKPrefix') H.k.prefix = e.target.value;
      if (e.target.id === 'mhKNote') H.k.note = e.target.value;
      if (e.target.id === 'mhLadiUrl') H.ladi.url = e.target.value;
      if (e.target.id === 'mhSmpUrl') H.smp.source = e.target.value;
      if (e.target.dataset.ppText !== undefined) { H.post.clips[+e.target.dataset.ppText].text = e.target.value; postSave(); }
      if (e.target.dataset.pf === 'name') { H.post.form.name = e.target.value; postSave(); }
      if (e.target.dataset.pf === 'bgm_volume') { $('#ppBgmVol').textContent = `${Math.round(e.target.value * 100)}%`; }
      if (e.target.dataset.pf === 'transition_volume') { $('#ppSndVol').textContent = `${Math.round(e.target.value * 100)}%`; }
      if (e.target.id === 'mhSmpChange') H.smp.change = e.target.value;
      if (e.target.id === 'mhSmpTranscript') H.smp.transcript = e.target.value;
      const sl = e.target.dataset.sline || e.target.dataset.svis;
      if (sl) { const [i, j] = sl.split(':').map(Number); H.smp.scripts.scripts[i].scenes[j][e.target.dataset.sline ? 'line' : 'visual'] = e.target.value; }
      const ll = e.target.dataset.lline || e.target.dataset.lvis;
      if (ll) { const [i, j] = ll.split(':').map(Number); H.ladi.scripts.scripts[i].scenes[j][e.target.dataset.lline ? 'line' : 'visual'] = e.target.value; }
    });
  }

  Object.assign(MH, { bind });
})();
