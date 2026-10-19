'use strict';

window.SeedanceStudio = (() => {
  let studio = null, mode = 'text', pending = false, configTimer, mediaSignature = '', activeTab = 'queue';
  const selectedMedia = new Set();
  const activeStates = ['preparing', 'attaching', 'submitting', 'submitted', 'generating', 'downloading'];
  const retryStates = ['failed', 'cancelled', 'interrupted'];
  const labels = { queued: 'Đang chờ', preparing: 'Chuẩn bị', attaching: 'Đính kèm ảnh', submitting: 'Đang gửi', submitted: 'Đã gửi', generating: 'Đang tạo video', media_ready: 'Video sẵn sàng', downloading: 'Đang tải', completed: 'Đã tải', failed: 'Lỗi', cancelled: 'Đã dừng', interrupted: 'Bị gián đoạn' };
  const fields = { provider: 'sdProvider', model: 'sdModel', generationRoute: 'sdRoute', aspectRatio: 'sdAspect', duration: 'sdDuration', preset: 'sdPreset', prefix: 'sdPrefix', tabsPerProfile: 'sdTabs', delaySeconds: 'sdDelay', timeoutSeconds: 'sdTimeout', directCreate: 'sdDirect', showBrowser: 'sdShowBrowser', autoDownload: 'sdAutoDownload', zipMode: 'sdZipMode', preferUnwatermarked: 'sdMaster' };
  const checks = ['directCreate', 'showBrowser', 'autoDownload', 'zipMode', 'preferUnwatermarked'];
  const empty = (title, text) => `<div class="sd-empty"><b>${esc(title)}</b><p>${esc(text)}</p></div>`;
  const selectedProfiles = () => $$('#sdProfiles input:checked').map(el => el.value);

  function config() {
    const result = { mode, profileIds: selectedProfiles() };
    Object.entries(fields).forEach(([key, id]) => { result[key] = checks.includes(key) ? $('#' + id).checked : $('#' + id).value; });
    return result;
  }

  async function action(name, data = {}, quiet = false) {
    try {
      const res = await api('seedance_action', name, data);
      if (!res.ok) throw new Error(res.error || 'Không thực hiện được thao tác');
      update(res.studio);
      return res;
    } catch (error) {
      if (!quiet) toast(error.message || String(error), 'error');
      return null;
    }
  }

  async function refresh() {
    try {
      const res = await api('seedance_state');
      if (res.ok) {
        update(res.studio);
        renderProfiles(selectedProfiles());
      }
    } catch (error) { toast(error.message, 'error'); }
  }

  function restore(cfg) {
    mode = cfg.mode;
    Object.entries(fields).forEach(([key, id]) => {
      if (checks.includes(key)) $('#' + id).checked = !!cfg[key];
      else $('#' + id).value = cfg[key];
    });
    renderProfiles(cfg.profileIds);
    renderModes();
    renderStyles();
    syncRouteOptions();
  }

  function syncRouteOptions() {
    const videoRoute = $('#sdRoute').value !== 'chat' && ($('#sdModel').value === '2.5' || $('#sdRoute').value === 'video');
    const legacy = $('#sdDuration option[value="15s"]');
    if (legacy) legacy.disabled = videoRoute;
    if (videoRoute && $('#sdDuration').value === '15s') $('#sdDuration').value = '10s';
  }

  function renderStyles() {
    const selected = $('#sdPreset').value;
    $$('[data-sd-style]').forEach(button => { const active = button.dataset.sdStyle === selected; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); });
    $('#sdStyleDescription').textContent = selected ? (studio.presetPrompts || {})[selected] || '' : 'Chọn phong cách để áp dụng khi gửi các cảnh. Bấm lại phong cách đang chọn để dùng prompt gốc.';
  }

  function renderProfiles(ids) {
    if (!studio) return;
    const provider = $('#sdProvider').value;
    const profiles = studio.profiles.filter(p => p.sites.includes(provider));
    $('#sdProfiles').innerHTML = profiles.map(p => `<label class="sd-check"><input type="checkbox" value="${esc(p.id)}" ${ids.includes(p.id) ? 'checked' : ''} ${studio.running ? 'disabled' : ''}><span>${esc(p.name)}</span><small class="${p.busy ? 'busy' : ''}">${p.busy ? 'Đang bận' : 'Sẵn sàng'}</small></label>`).join('') || '<p class="sd-hint">Chưa có profile cho nhà cung cấp này. Thêm trong Quản lý profile.</p>';
  }

  function renderModes() {
    $$('[data-sd-mode]').forEach(el => el.classList.toggle('active', el.dataset.sdMode === mode));
    renderPairing();
  }

  function renderPairing() {
    if (!studio) return;
    const jobs = studio.jobs.filter(j => j.status === 'queued');
    const paired = jobs.filter(j => j.imageId && studio.images.some(i => i.id === j.imageId));
    const reserved = new Set(paired.map(j => j.imageId));
    const available = studio.images.filter(i => i.status === 'queued' && !reserved.has(i.id));
    const count = paired.length + Math.min(jobs.length - paired.length, available.length);
    $('#sdPairing').classList.toggle('hidden', mode !== 'image');
    $('#sdPairing').textContent = `${count} cặp ảnh–cảnh sẵn sàng · ${jobs.length - count} cảnh chưa ghép · ${Math.max(0, available.length - (jobs.length - paired.length))} ảnh dư. Chỉ chạy các cặp có đủ dữ liệu.`;
  }

  function update(data) {
    if (!data) return;
    studio = data;
    const c = studio.counts;
    $('#sdStats').innerHTML = [['total', 'TỔNG CẢNH'], ['queued', 'ĐANG CHỜ'], ['submitted', 'ĐÃ GỬI'], ['ready', 'CẢNH CÓ VIDEO'], ['downloaded', 'VIDEO ĐÃ TẢI']]
      .map(([key, label]) => `<div class="sd-stat ${key === 'ready' ? 'accent' : ''}"><span>${label}</span><b>${c[key]}</b></div>`).join('');
    $('#sdStatus').textContent = studio.running ? '● Đang xử lý' : c.failed ? `${c.failed} cảnh cần kiểm tra` : 'Sẵn sàng';
    const accountLimits = Object.entries(studio.accountLimits || {});
    $('#sdLimitBanner').classList.toggle('hidden', !accountLimits.length);
    $('#sdLimitBanner').innerHTML = accountLimits.map(([id,notice]) => `<div><b>${esc((studio.profiles.find(p => p.id === id) || {}).name || id)} · ${esc(notice.code)}</b><p>${esc(notice.message)}</p></div>`).join('');
    $('#sdStatus').classList.toggle('running', studio.running);
    $('#sbSeedanceRunning').classList.toggle('hidden', !studio.running);
    $('#sdStart').disabled = studio.running || pending || !c.queued;
    $('#sdStop').disabled = !studio.running;
    $('#sdZip').disabled = studio.exporting || !studio.media.length || !!(studio.cleaning || []).length;
    $('#sdZip').textContent = studio.exporting ? 'Đang xuất ZIP…' : selectedMedia.size ? `↓ ZIP (${selectedMedia.size})` : '↓ Xuất ZIP';
    $('#sdRunSummary').textContent = studio.running ? 'Batch đang chạy' : `${c.queued} cảnh trong hàng đợi`;
    $('#sdWorkerSummary').textContent = studio.workers.length ? studio.workers.map(w => w.id).join(' · ') : 'Checkpoint được lưu tự động trên máy.';
    $$('.sd-config input,.sd-config select,[data-sd-mode],[data-sd-style],#sdAddPrompts,#sdPromptFile,#sdAddImages,#sdClearImages,#sdClearJobs,#sdRetryAll,#sdHistory,#sdLogin').forEach(el => { el.disabled = studio.running; });
    $('#sdAutoDownload').disabled = studio.running || $('#sdZipMode').checked;
    renderJobs(); renderImages(); renderMedia(); renderPairing();
    const log = $('#sdLogs'), atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 50;
    log.textContent = studio.events.map(e => `${new Date(e.timestamp).toLocaleTimeString('vi-VN')}  ${e.level === 'error' ? 'LỖI ' : ''}${e.jobId ? '[' + e.jobId.slice(0, 6) + '] ' : ''}${e.code ? e.code + ' · ' : ''}${e.message}`).join('\n') || 'Chưa có sự kiện. Nhập kịch bản để bắt đầu.';
    if (atBottom) log.scrollTop = log.scrollHeight;
  }

  function renderJobs() {
    if (!studio) return;
    const filter = $('#sdJobFilter').value, search = $('#sdSearch').value.trim().toLocaleLowerCase();
    const rows = studio.jobs.filter(j => (!search || (j.title + ' ' + j.text).toLocaleLowerCase().includes(search)) &&
      (filter === 'all' || (filter === 'active' ? activeStates.includes(j.status) : filter === 'failed' ? retryStates.includes(j.status) : filter === 'submitted' ? !!j.submittedAt : j.status === filter)));
    $('#sdJobs').innerHTML = rows.map(j => {
      const index = studio.jobs.indexOf(j) + 1;
      const badge = activeStates.includes(j.status) ? 'active' : retryStates.includes(j.status) ? 'error' : ['media_ready', 'completed'].includes(j.status) ? 'ready' : '';
      return `<article class="sd-job" data-job="${esc(j.id)}"><span class="sd-job-index">${String(index).padStart(2, '0')}</span><div class="sd-job-body"><div class="sd-job-head"><b title="${esc(j.title)}">${esc(j.title)}</b><span class="sd-badge ${badge}">${esc(labels[j.status] || j.status)}</span></div><p>${esc(j.text)}</p><details><summary>Xem đầy đủ / cấu hình</summary><p>${esc(j.text)}</p><div class="sd-job-meta">${esc(j.workerId || '')}${j.config ? ' · ' + esc(j.config.model + ' / ' + j.config.duration + ' / ' + j.config.aspectRatio) : ''} · Lần chạy ${j.attempt}${j.imageId ? ' · Có ảnh tham chiếu' : ''}</div>${j.chatUrl ? `<button class="sd-text-btn" data-job-act="chat">Mở cuộc trò chuyện ↗</button>` : ''}</details>${j.error ? `<p class="sd-job-error">${esc(j.code)} · ${esc(j.error)}</p>` : ''}</div><div class="sd-job-actions">${j.status === 'queued' ? `<button class="sd-text-btn" data-job-act="send" ${studio.running ? 'disabled' : ''}>Gửi cảnh</button><button class="sd-text-btn" data-job-act="edit" ${studio.running ? 'disabled' : ''}>Sửa</button>` : ''}${retryStates.includes(j.status) ? `<button class="sd-text-btn" data-job-act="retry" ${studio.running ? 'disabled' : ''}>Thử lại</button>` : ''}<button class="sd-text-btn sd-red" data-job-act="delete" ${studio.running ? 'disabled' : ''}>Xoá</button></div></article>`;
    }).join('') || empty(studio.jobs.length ? 'Không có cảnh phù hợp' : 'Câu chuyện bắt đầu từ một prompt', studio.jobs.length ? 'Thử đổi bộ lọc hoặc từ khoá tìm kiếm.' : 'Thêm kịch bản phía trên. Mỗi cảnh sẽ có trạng thái, video và nhật ký riêng.');
  }

  function renderImages() {
    if (!studio) return;
    const filter = $('#sdImageFilter').value;
    $('#sdImages').innerHTML = [...studio.images].sort((a,b) => a.order - b.order).filter(i => filter === 'all' || i.status === filter).map((i, index) =>
      `<article class="sd-image" data-image="${esc(i.id)}"><img src="${esc(i.url)}" loading="lazy" alt="${esc(i.name)}"><div class="sd-image-info"><b title="${esc(i.name)}">${index + 1}. ${esc(i.name)}</b><small>${(i.size / 1024 / 1024).toFixed(1)} MB · ${i.status === 'attached' ? 'Đã đính kèm' : 'Đang chờ'}</small><div class="sd-toolbar"><button class="sd-text-btn" data-image-act="up" aria-label="Đưa ảnh lên" ${studio.running ? 'disabled' : ''}>↑</button><button class="sd-text-btn" data-image-act="down" aria-label="Đưa ảnh xuống" ${studio.running ? 'disabled' : ''}>↓</button><button class="sd-text-btn" data-image-act="reset" ${studio.running ? 'disabled' : ''}>Dùng lại</button><button class="sd-text-btn sd-red" data-image-act="delete" ${studio.running ? 'disabled' : ''}>Xoá</button></div></div></article>`
    ).join('') || empty('Thư viện ảnh tham chiếu', 'Thêm ảnh hoặc kéo thả vào đây. Ảnh được chép vào kho riêng của app và giữ lại sau khi khởi động lại.');
  }

  function renderMedia() {
    const signature = JSON.stringify([studio.media, studio.running, studio.cleaning]);
    if (signature === mediaSignature) return;
    mediaSignature = signature;
    $('#sdMedia').innerHTML = studio.media.map(m => `<article class="sd-video" data-media="${esc(m.id)}"><div class="sd-video-preview"><button class="sd-text-btn" data-media-act="preview">▶ Xem video</button></div><div class="sd-video-info"><label class="sd-check"><input type="checkbox" data-media-select="${esc(m.id)}" ${selectedMedia.has(m.id) ? 'checked' : ''}><b title="${esc(m.title)}">${esc(m.title)}</b></label><p>${m.path ? `${esc(m.width)}×${esc(m.height)} · ${Number(m.duration || 0).toFixed(1)}s · Đã tải` : 'Chưa kiểm tra thông số file'}<br>${esc(m.source || 'provider')} · ${esc(m.provider)}${m.sceneId ? ' · Cảnh ' + esc(m.sceneId.slice(0,6)) : ' · Lịch sử'}<br>${m.cleanPath ? '✓ Đã xử lý vùng watermark' : m.watermarkStatus === 'master_requested' ? 'Bản master từ nhà cung cấp · chưa kiểm tra pixel' : m.watermarkStatus === 'watermarked' ? 'Bản preview có watermark' : 'Watermark chưa xác minh'}</p>${m.error ? `<p class="sd-red">${esc(m.error)}</p>` : ''}<div class="sd-toolbar"><button class="sd-text-btn" data-media-act="download">↓ MP4</button>${m.path ? '<button class="sd-text-btn" data-media-act="open">Mở file ↗</button>' : ''}<button class="sd-text-btn" data-media-act="watermark" ${(studio.cleaning || []).includes(m.id) ? 'disabled' : ''}>${(studio.cleaning || []).includes(m.id) ? 'Đang gỡ watermark…' : 'Gỡ watermark'}</button><button class="sd-text-btn" data-media-act="chat">Chat ↗</button><button class="sd-text-btn" data-media-act="link" ${studio.running ? 'disabled' : ''}>Gắn cảnh</button></div></div></article>`).join('') || empty('Video sẽ xuất hiện tại đây', 'Bắt đầu tạo video hoặc dán URL cuộc trò chuyện rồi chọn Quét lịch sử để thu lại video đã có.');
  }

  function saveConfig() {
    clearTimeout(configTimer);
    configTimer = setTimeout(() => action('config', config()), 350);
  }

  function openLogoTool(media) {
    if (!media.path) return toast('Bấm ↓ MP4 để tải video trước khi gỡ watermark', 'error');
    const aspect = Number(media.width) / Number(media.height) || 16 / 9;
    openModal('SEEDANCE STUDIO PRO', 'Gỡ watermark · Chọn vùng logo', `
      <p class="sd-hint">Kéo để khoanh vùng logo cố định trên khung hình. Vùng chọn được nội suy từ các pixel xung quanh và có thể mềm hơn nền. MP4 gốc được giữ nguyên.</p>
      <div class="sd-logo-frame" id="sdLogoFrame" style="width:${Math.min(640,360 * aspect)}px;aspect-ratio:${aspect}">
        <video id="sdLogoVideo" src="${esc(media.localUrl || media.url)}" muted preload="metadata"></video><div id="sdLogoCanvas" aria-label="Kéo để chọn vùng logo"><i id="sdLogoRect"></i></div>
      </div>
      <label class="field"><span>Chọn khung hình tham chiếu</span><input id="sdLogoSeek" type="range" min="0" max="${Math.max(0.1,Number(media.duration || 15) - 0.1)}" step="0.1" value="0"></label>
      <div class="sd-logo-values">${[['x','Trái (%)',78],['y','Trên (%)',86],['w','Rộng (%)',20],['h','Cao (%)',12]].map(([key,label,value]) => `<label class="field"><span>${label}</span><input id="sdLogo-${key}" type="number" min="0" max="100" step="0.1" value="${value}"></label>`).join('')}</div>
      <div class="sd-toolbar"><button class="btn primary" id="sdRemoveLogo">Gỡ watermark →</button><span class="sd-hint">Tạo file _clean.mp4, giữ nguyên kích thước và âm thanh.</span></div>`);
    const video = $('#sdLogoVideo'), canvas = $('#sdLogoCanvas'), rectangle = $('#sdLogoRect');
    const values = () => Object.fromEntries(['x','y','w','h'].map(key => [key, Number($('#sdLogo-' + key).value) / 100]));
    const draw = () => { const r = values(); Object.assign(rectangle.style, { left:r.x * 100 + '%', top:r.y * 100 + '%', width:r.w * 100 + '%', height:r.h * 100 + '%' }); };
    ['x','y','w','h'].forEach(key => { $('#sdLogo-' + key).oninput = draw; });
    draw();
    $('#sdLogoSeek').oninput = e => { video.currentTime = Number(e.target.value); };
    let start = null;
    const point = e => { const b = canvas.getBoundingClientRect(); return {x:Math.max(0,Math.min(1,(e.clientX - b.left) / b.width)),y:Math.max(0,Math.min(1,(e.clientY - b.top) / b.height))}; };
    canvas.onpointerdown = e => { start = point(e); canvas.setPointerCapture(e.pointerId); };
    canvas.onpointermove = e => {
      if (!start) return;
      const end = point(e), r = {x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),w:Math.abs(end.x-start.x),h:Math.abs(end.y-start.y)};
      Object.entries(r).forEach(([k,v]) => { $('#sdLogo-' + k).value = (v * 100).toFixed(1); }); draw();
    };
    canvas.onpointerup = () => { start = null; };
    canvas.onpointercancel = () => { start = null; };
    $('#sdRemoveLogo').onclick = async () => {
      $('#sdRemoveLogo').disabled = true;
      const result = await action('watermark', {id:media.id,rectangle:values()});
      if (result) closeModal(); else $('#sdRemoveLogo').disabled = false;
    };
  }

  async function importText() {
    if (pending) return;
    const text = $('#sdPromptText').value.trim();
    if (!text) return toast('Nhập ít nhất một cảnh', 'error');
    pending = true;
    try {
      const res = await action('import', { text });
      if (res) { $('#sdPromptText').value = ''; promptCount(); toast(`Đã thêm ${res.result} cảnh`, 'ok'); }
    } finally { pending = false; update(studio); }
  }

  function promptCount() {
    const text = $('#sdPromptText').value.replace(/\r\n?/g, '\n').trim();
    const parts = /\n[ \t]*\n/.test(text) ? text.split(/\n[ \t]*\n+/) : text.split('\n');
    $('#sdPromptCount').textContent = parts.filter(p => p.trim()).length + ' cảnh';
    try { localStorage.setItem('va.seedance.draft', text); } catch { /* optional draft cache */ }
  }

  async function importFiles(files) {
    if (studio.running) return toast('Dừng batch trước khi nhập file', 'error');
    for (const file of files) {
      if (!/\.(txt|text|csv|json)$/i.test(file.name)) { toast('Chỉ nhận kịch bản TXT, CSV hoặc JSON', 'error'); continue; }
      if (file.size > 2_000_000) { toast('Kịch bản tối đa 2 MB/file', 'error'); continue; }
      const res = await action('import', { text: await file.text(), filename: file.name });
      if (res) toast(`Đã nhập ${res.result} cảnh từ ${file.name}`, 'ok');
    }
  }

  async function importImageFiles(files) {
    if (studio.running) return;
    for (const file of files) {
      if (file.size > 25 * 1024 * 1024) { toast(`${file.name}: vượt quá 25 MB`, 'error'); continue; }
      const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
      const res = await action('image_data', { name: file.name, dataUrl });
      if (res?.result?.errors?.length) toast(res.result.errors.join('; '), 'error');
    }
  }

  function bindDrop(element, handler) {
    element.addEventListener('dragover', e => { e.preventDefault(); element.classList.add('sd-drop-active'); });
    element.addEventListener('dragleave', () => element.classList.remove('sd-drop-active'));
    element.addEventListener('drop', e => { e.preventDefault(); element.classList.remove('sd-drop-active'); handler([...e.dataTransfer.files]).catch(error => toast(error.message, 'error')); });
  }

  async function start(ids) {
    if (pending || studio.running) return;
    pending = true; $('#sdStart').disabled = true;
    clearTimeout(configTimer);
    try { await action('start', { config: config(), ids }); }
    finally { pending = false; update(studio); }
  }

  async function retry(id) {
    const jobs = studio.jobs.filter(j => (id === 'all' || j.id === id) && retryStates.includes(j.status));
    if (jobs.some(j => j.submittedAt || j.submissionAttempted || ['SUBMISSION_UNCERTAIN', 'INTERRUPTED', 'RENDER_TIMEOUT'].includes(j.code))) {
      if (!confirm('Một số cảnh đã bấm gửi hoặc đang render khi bị gián đoạn. Kiểm tra cuộc trò chuyện hoặc quét lịch sử trước để tránh tạo trùng. Đưa các cảnh này về hàng đợi?')) return;
    }
    await action('job', { id, action: 'retry' });
  }

  async function init() {
    const res = await api('seedance_state');
    if (!res.ok) return;
    studio = res.studio;
    $('#sdPreset').insertAdjacentHTML('beforeend', Object.entries(studio.presets).map(([id,label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join(''));
    $('#sdStyleChips').innerHTML = Object.entries(studio.presets).map(([id,label]) => `<button type="button" data-sd-style="${esc(id)}" aria-pressed="false">${esc(label)}</button>`).join('');
    restore(studio.config);
    try { $('#sdPromptText').value = localStorage.getItem('va.seedance.draft') || ''; } catch { /* optional */ }
    promptCount(); update(studio);
    Object.values(fields).forEach(id => $('#' + id).addEventListener('change', () => {
      if (id === 'sdProvider') renderProfiles(studio.config.profileIds);
      if (id === 'sdPreset') renderStyles();
      if (id === 'sdModel' || id === 'sdRoute') syncRouteOptions();
      $('#sdAutoDownload').disabled = $('#sdZipMode').checked;
      saveConfig();
    }));
    $('#sdProfiles').addEventListener('change', saveConfig);
    $$('[data-sd-style]').forEach(button => { button.onclick = () => { $('#sdPreset').value = $('#sdPreset').value === button.dataset.sdStyle ? '' : button.dataset.sdStyle; renderStyles(); saveConfig(); }; });
    $$('[data-sd-mode]').forEach(el => { el.onclick = () => { mode = el.dataset.sdMode; renderModes(); saveConfig(); }; });
    $$('[data-sd-tab]').forEach(el => { el.onclick = () => {
      activeTab = el.dataset.sdTab;
      $$('[data-sd-tab]').forEach(t => { const active = t === el; t.classList.toggle('active', active); t.setAttribute('aria-selected', String(active)); });
      $$('.sd-view').forEach(view => view.classList.toggle('hidden', view.id !== 'sdView-' + activeTab));
    }; });
    $('#sdPromptText').oninput = promptCount;
    $('#sdPromptText').onkeydown = e => { if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); importText(); } };
    $('#sdAddPrompts').onclick = importText;
    $('#sdPromptFile').onchange = async e => { await importFiles([...e.target.files]); e.target.value = ''; };
    bindDrop($('.sd-input-card'), importFiles);
    bindDrop($('#sdView-images'), importImageFiles);
    $('#sdAddImages').onclick = async () => {
      const paths = await api('pick_files', 'seedance_images');
      if (paths.length) { const result = await action('images', { paths }); if (result?.result?.errors?.length) toast(result.result.errors.join('; '), 'error'); }
    };
    $('#sdClearImages').onclick = () => { if (confirm('Xoá toàn bộ ảnh trong thư viện Studio?')) action('image', { id: 'all', action: 'delete' }); };
    $('#sdClearJobs').onclick = () => { if (confirm('Xoá toàn bộ kịch bản và hàng đợi? Các video đã lưu vẫn được giữ lại.')) action('job', { id: 'all', action: 'delete' }); };
    $('#sdRetryAll').onclick = () => retry('all');
    $('#sdJobs').onclick = async e => {
      const button = e.target.closest('[data-job-act]'); if (!button) return;
      const job = studio.jobs.find(j => j.id === button.closest('[data-job]').dataset.job);
      const act = button.dataset.jobAct;
      if (act === 'send') return start([job.id]);
      if (act === 'chat') return api('open_url', job.chatUrl);
      if (act === 'retry') return retry(job.id);
      if (act === 'edit') {
        openModal('SEEDANCE STUDIO PRO', 'Sửa cảnh', `<label class="field"><span>Nội dung cảnh</span><textarea id="sdEditText" rows="9">${esc(job.text)}</textarea></label><div class="sd-toolbar"><button class="btn primary" id="sdSaveEdit">Lưu cảnh</button></div>`, true);
        $('#sdSaveEdit').onclick = async () => { const result = await action('job', { id: job.id, action: 'edit', text: $('#sdEditText').value }); if (result) closeModal(); };
        return;
      }
      await action('job', { id: job.id, action: act });
    };
    $('#sdImages').onclick = e => { const btn = e.target.closest('[data-image-act]'); if (btn) action('image', { id: btn.closest('[data-image]').dataset.image, action: btn.dataset.imageAct }); };
    $('#sdMedia').onclick = async e => {
      const btn = e.target.closest('[data-media-act]'); if (!btn) return;
      const m = studio.media.find(m => m.id === btn.closest('[data-media]').dataset.media);
      if (btn.dataset.mediaAct === 'chat') return api('open_url', m.chatUrl);
      if (btn.dataset.mediaAct === 'watermark') return openLogoTool(m);
      if (btn.dataset.mediaAct === 'preview') {
        const video = document.createElement('video'); video.controls = true; video.preload = 'metadata'; video.src = m.cleanUrl || m.localUrl || m.url;
        btn.closest('.sd-video-preview').replaceChildren(video); return;
      }
      if (btn.dataset.mediaAct === 'link') {
        openModal('SEEDANCE STUDIO PRO', 'Gắn video với cảnh', `<label class="field"><span>Chọn cảnh khớp với video đã kiểm tra</span><select id="sdLinkScene">${studio.jobs.map((j,index) => `<option value="${esc(j.id)}" ${j.id === m.sceneId ? 'selected' : ''}>${index + 1}. ${esc(j.title)}</option>`).join('')}</select></label><div class="sd-toolbar"><button class="btn primary" id="sdConfirmLink">Gắn cảnh</button></div>`, true);
        $('#sdConfirmLink').onclick = async () => { const result = await action('link', { id: m.id, sceneId: $('#sdLinkScene').value }); if (result) closeModal(); };
        return;
      }
      await action(btn.dataset.mediaAct, { id: m.id });
    };
    $('#sdMedia').onchange = e => {
      const id = e.target.dataset.mediaSelect;
      if (id) { if (e.target.checked) selectedMedia.add(id); else selectedMedia.delete(id); $('#sdZip').textContent = selectedMedia.size ? `↓ ZIP (${selectedMedia.size})` : '↓ Xuất ZIP'; }
    };
    $('#sdJobFilter').onchange = renderJobs; $('#sdSearch').oninput = renderJobs; $('#sdImageFilter').onchange = renderImages;
    $('#sdStart').onclick = () => start(); $('#sdStop').onclick = () => action('stop');
    $('#sdZip').onclick = () => action('zip', { ids: [...selectedMedia] });
    $('#sdHistory').onclick = () => action('history', { config: { ...config(), profileIds: selectedProfiles().slice(0, 1), tabsPerProfile: 1 }, url: $('#sdHistoryUrl').value.trim() });
    $('#sdRefresh').onclick = refresh; $('#sdRefreshProfiles').onclick = refresh;
    $('#sdManageProfiles').onclick = () => navigate('profiles');
    $('#sdFolder').onclick = () => api('open_output_dir');
    $('#sdExport').onclick = async () => { const result = await action('export'); if (result) toast(`Đã lưu dự án: ${result.result}`, 'ok'); };
    $('#sdLogin').onclick = async () => {
      const profiles = selectedProfiles();
      if (!profiles.length) return toast('Chọn một profile để đăng nhập', 'error');
      const result = await api('browser_login', $('#sdProvider').value + '_browser', profiles[0]);
      if (!result.ok) toast(result.error, 'error');
    };
  }
  return { init, refresh, update };
})();
