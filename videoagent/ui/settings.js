/* Cài đặt — màn hình riêng (không còn hộp thoại): menu nhóm bên trái + các khối độc lập, tìm nhanh, thanh Lưu cố định.
   Khối “Chức năng” bật / tắt từng mục menu (áp dụng ngay). Khối Zalo cũng áp dụng ngay; các khối khác bấm Lưu. */
(function () {
  const SET = { dirty: false, rendered: false };

  // [id, icon, tiêu đề, mô tả ngắn (hiện ở menu nhóm + đầu khối), rộng 2 cột?]
  const BLOCKS = [
    ['features', '🧩', 'Chức năng', 'Bật / tắt các mục trên menu', true],
    ['models', '🤖', 'Model AI dùng chung', 'Model viết, ảnh, video, hậu kỳ'],
    ['profiles', '👥', 'Profile trình duyệt', 'Tài khoản Chrome theo từng model', true],
    ['storage', '📁', 'Lưu trữ', 'Thư mục video, file tạm'],
    ['video', '🎬', 'Video & âm thanh', 'FPS, luồng song song, nhạc nền'],
    ['browser', '🌐', 'Trình duyệt', 'Cách điều khiển Chrome'],
    ['api', '🔑', 'Khoá API & model API', 'Anthropic, OpenAI, Gemini, HeyGen'],
    ['facebook', '📣', 'Facebook · Meta', 'Token, App ID / Secret, Fanpage', true],
    ['zalo', '💬', 'Zalo', 'Nhận yêu cầu quảng cáo'],
    ['ui', '🖥', 'Giao diện', 'Màn Loading'],
    ['security', '🔒', 'Bảo mật', 'Mật khẩu quản trị, khoá Cài đặt'],
    ['license', '🔐', 'License', 'Kích hoạt, đăng nhập'],
  ];

  const opt = (list, cur) => list.map(([v, l]) => `<option value="${v}" ${String(cur) === String(v) ? 'selected' : ''}>${l}</option>`).join('');

  /* ------------------------------------------------------------ menu bật / tắt */
  // mục luôn bật (không tắt được): Cài đặt — để luôn bật lại được các mục khác
  const LOCKED = ['settings'];

  /** Màn mở được: ưu tiên theo thứ tự prefer, không thì mục đầu tiên còn bật (bỏ qua mục chỉ là nút: Cài đặt, thư mục). */
  function firstView(...prefer) {
    const on = v => { const el = $(`.sb-item[data-view="${v}"]`); return el && !el.classList.contains('hidden'); };
    const hit = prefer.find(on);
    if (hit) return hit;
    const el = $$('.sb-item[data-view]').find(x => !x.classList.contains('hidden') && !['settings', 'folder'].includes(x.dataset.view));
    return el ? el.dataset.view : 'settings';
  }

  /** Danh sách mục menu đọc từ DOM: nhóm theo tiêu đề nhóm ở menu trái + nhóm “Thanh trên cùng”. */
  function menuItems() {
    const out = [];
    $$('#topnav .sb-item[data-view]').forEach(el => out.push({ el, group: 'THANH TRÊN CÙNG' }));
    let group = '';
    $$('#sidebar > *').forEach(el => {
      if (el.classList.contains('sb-group')) group = el.textContent.trim();
      else if (el.matches('.sb-item[data-view]')) out.push({ el, group });
    });
    return out.map(({ el, group }) => ({
      el, group, view: el.dataset.view,
      label: (el.querySelector('.sb-label') || el).textContent.trim(),
      desc: el.title && el.title !== (el.querySelector('.sb-label') || el).textContent.trim() ? el.title : '',
      icon: (el.querySelector('.sb-ic') || {}).innerHTML || '',
      def: el.dataset.defHidden !== '1',  // trạng thái mặc định (theo HTML lúc mở app)
    }));
  }

  function menuOn(item, menus) {
    if (LOCKED.includes(item.view)) return true;
    const v = (menus || {})[item.view];
    return v === undefined ? item.def : !!v;
  }

  /** Ẩn / hiện mục menu theo Cài đặt → Chức năng; tiêu đề nhóm ẩn khi cả nhóm tắt. */
  function applyMenus() {
    $$('.sb-item[data-view]').forEach(el => {  // ghi nhớ mặc định 1 lần (trước khi app đổi class hidden)
      if (el.dataset.defHidden === undefined) el.dataset.defHidden = el.classList.contains('hidden') ? '1' : '0';
    });
    const menus = state.boot.settings.menus || {};
    menuItems().forEach(it => it.el.classList.toggle('hidden', !menuOn(it, menus)));
    if (window.applyScreenLocks) window.applyScreenLocks();  // 🔒 biểu tượng khoá trên mục màn bị khoá
    let head = null, any = false;
    const close = () => { if (head) head.classList.toggle('hidden', !any); };
    $$('#sidebar > *').forEach(el => {
      if (el.classList.contains('sb-group')) { close(); head = el; any = false; }
      else if (el.matches('.sb-item[data-view]') && !el.classList.contains('hidden')) any = true;
    });
    close();
    if (state.view && !LOCKED.includes(state.view)) {
      const cur = $(`.sb-item[data-view="${state.view}"]`);
      if (cur && cur.classList.contains('hidden')) navigate(firstView('library', 'create'));
    }
  }

  function featuresHtml() {
    const menus = state.boot.settings.menus || {};
    const groups = {};
    menuItems().forEach(it => (groups[it.group || 'KHÁC'] = groups[it.group || 'KHÁC'] || []).push(it));
    const total = menuItems().filter(it => !LOCKED.includes(it.view));
    const on = total.filter(it => menuOn(it, menus)).length;
    return `<div class="set-feat-top"><span class="muted">Đang bật <b>${on}</b> / ${total.length} mục · tắt mục không dùng cho menu gọn hơn
        (dữ liệu vẫn giữ nguyên, bật lại là dùng tiếp).</span>
      <button class="btn ghost sm" type="button" data-feat-reset>↺ Mặc định</button></div>
      <div class="set-feat-groups">${Object.entries(groups).map(([g, items]) => `
        <div class="set-feat-group">
          <div class="set-feat-head"><span>${esc(g)}</span>
            <span class="row"><button class="link-btn" type="button" data-feat-all="${esc(g)}" data-on="1">Bật hết</button>
            <button class="link-btn" type="button" data-feat-all="${esc(g)}" data-on="0">Tắt hết</button></span></div>
          ${items.map(it => {
            const locked = LOCKED.includes(it.view);
            const checked = menuOn(it, menus);
            return `<label class="set-feat ${checked ? 'on' : ''} ${locked ? 'locked' : ''}" title="${esc(it.desc || it.label)}">
              <span class="set-feat-ic">${it.icon}</span>
              <span class="set-feat-txt"><b>${esc(it.label)}</b>${locked ? '<small>Luôn bật</small>' : it.def ? '' : '<small>Mặc định ẩn</small>'}</span>
              <span class="set-switch"><input type="checkbox" data-feat="${esc(it.view)}" ${checked ? 'checked' : ''} ${locked ? 'disabled' : ''}><i></i></span>
            </label>`;
          }).join('')}
        </div>`).join('')}</div>`;
  }

  /* ------------------------------------------------------------ 🧠 model chữ: Trình duyệt hay CLI (+ cài / đăng nhập ngay) */
  const CLI_SITE_VI = { claude: 'Claude', chatgpt: 'ChatGPT / OpenAI', gemini: 'Gemini', grok: 'Grok', muse: 'muse.ai' };
  // muse.ai (muse-cli): đăng nhập = cookie muse.ai — lấy từ profile Muse của app hoặc dán tay; trạng thái + nút riêng
  function museLoginHtml(c, py, busy) {
    const lg = c.muse_login || {};
    return `<div class="set-cli-muse">
      ${py.ok ? '' : `<small class="warn-text">✗ Chưa có Python 3.10+ (hoặc uv / pipx) để cài muse-cli${py.version ? ` — máy đang có Python ${esc(py.version)} (quá cũ)` : ''}</small>
        <button class="btn ghost sm" type="button" data-cli-act="python" data-cli-site="" ${busy ? 'disabled' : ''}>⬇ Cài Python</button>`}
      <small class="${lg.logged_in ? 'ok-text' : 'muted'}">${lg.logged_in ? `✓ Đã có đăng nhập muse.ai${lg.updated ? ` (lưu ${esc(lg.updated)})` : ''}` : '✗ Chưa đăng nhập muse-cli'}</small>
      <button class="btn ghost sm" type="button" data-muse-login="profile" ${c.installed ? '' : 'disabled'} title="Mở ẩn profile Muse của app, đọc cookie muse.ai rồi ghi cho muse-cli (không gửi tin nhắn)">🔑 Lấy từ profile Muse</button>
      <button class="btn ghost sm" type="button" data-muse-login="paste" ${c.installed ? '' : 'disabled'} title="Dán cookie muse.ai (cần hatch_sess) copy từ DevTools">📋 Dán cookie</button>
      <button class="btn ghost sm" type="button" data-muse-check ${c.installed && lg.logged_in ? '' : 'disabled'} title="muse-cli status — đọc danh tính, không gửi tin, không tốn lượt">✓ Kiểm tra</button>
      <div class="set-cli-paste hidden"><textarea rows="2" autocomplete="off" spellcheck="false" placeholder="hatch_sess=…; cookie_khac=…  (hoặc {&quot;hatch_sess&quot;: &quot;…&quot;})"></textarea>
        <button class="btn primary sm" type="button" data-muse-save>Lưu cookie</button></div>
      <small class="muted">muse-cli là công cụ cộng đồng (không chính thức của Meta), có thể hỏng khi muse.ai đổi giao thức → lượt đó tự chạy bằng trình duyệt. Cookie lưu ở <code>${esc(lg.file || '~/.config/muse-cli/cookies.txt')}</code>, không gửi đi đâu khác.</small></div>`;
  }
  let cliPoll = null;
  async function renderCliBox(refresh) {
    const box = $('#setCliBox');
    if (!box) return;
    const res = await api('llm_cli_status', !!refresh);
    if (!res || !res.ok || !$('#setCliBox')) return;
    const nd = res.node || {};
    const busy = res.job && res.job.running;
    const keep = {};  // giữ lựa chọn chưa lưu khi vẽ lại
    box.querySelectorAll('[data-cli-mode]').forEach(el => { keep[el.dataset.cliMode] = el.value; });
    const grokKey = $('#setGrokKey') ? $('#setGrokKey').value : '';
    box.innerHTML = `<div class="set-cli-node">${nd.npm ? `<small class="ok-text">✓ Node.js ${esc(nd.version || '')} · npm có sẵn</small>`
      : `<small class="warn-text">✗ Chưa có Node.js / npm — cần để cài Claude / Codex / Gemini / Grok CLI</small>
         <button class="btn ghost sm" type="button" data-cli-act="node" data-cli-site="" ${busy ? 'disabled' : ''}>⬇ Cài Node.js${nd.winget ? '' : ' (mở trang tải)'}</button>`}</div>
      <div class="set-cli-rows">${res.clis.map(c => {
        const py = res.python || {};
        const needNpm = (!!c.npm_pkg && !nd.npm) || (c.site === 'muse' && !py.ok);
        const mode = keep[c.site] || c.mode;
        return `<div class="set-cli-row" data-cli-row="${esc(c.site)}">
        <b>${esc(CLI_SITE_VI[c.site] || c.site)}</b>
        <small class="${c.installed ? 'ok-text' : 'muted'}" title="${esc(c.path || '')}">${c.installed ? `✓ ${esc(c.name)}${c.version ? ` · ${esc(c.version)}` : ''}` : `✗ Chưa cài ${esc(c.name)}`}</small>
        <select data-cli-mode="${esc(c.site)}" title="${esc(c.login)}">
          <option value="browser" ${mode !== 'cli' ? 'selected' : ''}>🌐 Trình duyệt</option>
          <option value="cli" ${mode === 'cli' ? 'selected' : ''} ${c.installed ? '' : 'disabled'}>🧠 CLI${c.installed ? '' : ' (chưa cài)'}</option></select>
        <span class="set-cli-btns">
          ${c.installed ? `<button class="btn ghost sm" type="button" data-cli-act="update" data-cli-site="${esc(c.site)}" ${busy ? 'disabled' : ''} title="Cập nhật lên bản mới nhất">⟳ Cập nhật</button>`
            : `<button class="btn primary sm" type="button" data-cli-act="install" data-cli-site="${esc(c.site)}" ${busy || needNpm ? 'disabled' : ''} title="${needNpm ? (c.site === 'muse' ? 'Cài Python trước' : 'Cài Node.js trước') : esc(c.install)}">⬇ Cài</button>`}
          ${c.can_login ? `<button class="btn ghost sm" type="button" data-cli-login="${esc(c.site)}" ${c.installed ? '' : 'disabled'} title="Mở cửa sổ Terminal để đăng nhập">🔑 Đăng nhập</button>` : ''}
          <button class="btn ghost sm" type="button" data-cli-test="${esc(c.site)}" ${c.installed ? '' : 'disabled'} title="Gửi 1 câu rất ngắn để kiểm tra CLI chạy + đã đăng nhập (tốn 1 lượt)">Thử</button></span>
        ${c.quota ? `<small class="warn-text set-cli-note" title="${esc(c.quota.msg || '')}">⏳ CLI hết lượt / hết credit đến ${esc(c.quota.until)} — việc chữ của hãng này đang tự chạy bằng trình duyệt
          <button class="btn ghost sm" type="button" data-cli-quota="${esc(c.site)}" title="Đã nạp thêm credit / đổi tài khoản → thử lại CLI ngay">↻ Thử lại CLI</button></small>` : ''}
        <small class="muted set-cli-note">${c.images ? 'Nhận được ảnh đính kèm' : 'Chưa nhận ảnh — lượt có ảnh chạy bằng trình duyệt'} · ${c.installed ? `Đăng nhập: ${esc(c.login)}` : `Lệnh cài: <code>${esc(c.install)}</code>`}${c.site === 'muse' ? ' · chỉ việc chữ, mỗi lượt 1 cuộc trò chuyện mới (tạo ảnh / video Muse vẫn qua trình duyệt)' : ''}</small>
        ${c.site === 'muse' ? museLoginHtml(c, py, busy) : ''}
        ${c.site === 'grok' ? `<label class="field set-cli-key"><span>xAI API key cho Grok CLI ${res.grok_key ? '<small class="ok-text">(đã lưu)</small>' : ''}</span>
          <input id="setGrokKey" type="password" autocomplete="off" placeholder="${res.grok_key ? '•••••••• (để trống = giữ nguyên)' : 'xai-…'}" value="${esc(grokKey)}"></label>` : ''}</div>`;
      }).join('')}</div>
      <div class="row"><button class="btn ghost sm" type="button" data-cli-refresh>↻ Kiểm tra lại</button></div>
      <div class="set-cli-job ${res.job && res.job.log && res.job.log.length ? '' : 'hidden'}">
        <div class="row"><b data-cli-job-title></b><span class="cv-sp"></span><button class="btn ghost sm" type="button" data-cli-cancel ${busy ? '' : 'hidden'}>⏹ Huỷ</button></div>
        <pre data-cli-log></pre></div>`;
    box.querySelectorAll('[data-cli-mode]').forEach(el => { el.onchange = () => setDirty(true); });
    if ($('#setGrokKey')) $('#setGrokKey').oninput = () => setDirty(true);
    box.querySelector('[data-cli-refresh]').onclick = () => renderCliBox(true);
    box.querySelectorAll('[data-cli-act]').forEach(b => {
      b.onclick = async () => {
        const site = b.dataset.cliSite, act = b.dataset.cliAct;
        const row = res.clis.find(c => c.site === site);
        const museCmd = act === 'update' ? 'muse-cli update' : 'uv tool install muse-cli / pipx install muse-cli / py -m pip install --user muse-cli (tuỳ máy có gì)';
        const what = act === 'node' ? 'Node.js (winget install OpenJS.NodeJS.LTS)'
          : act === 'python' ? 'Python 3.12 (winget install Python.Python.3.12)'
          : `${row.name}${act === 'update' ? ' lên bản mới nhất' : ''}\n\nLệnh: ${site === 'muse' ? museCmd : act === 'update' && row.npm_pkg ? `npm i -g ${row.npm_pkg}@latest` : row.install}`;
        if (!confirm(`${act === 'update' ? 'Cập nhật' : 'Cài'} ${what}\n\nChạy bằng quyền người dùng hiện tại${site === 'muse' ? ', tải gói muse-cli từ PyPI' : ', tải từ nguồn chính thức'}. Tiếp tục?`)) return;
        const r = await api('llm_cli_install', site, act);
        if (!r || !r.ok) return toast((r && r.error) || 'Không bắt đầu được', 'error');
        if (r.job && r.job.opened) { toast(`Máy chưa có winget — đã mở trang tải ${act === 'python' ? 'Python' : 'Node.js'}`, 'warn'); return; }
        watchCliJob();
      };
    });
    box.querySelectorAll('[data-cli-login]').forEach(b => {
      b.onclick = async () => {
        const r = await api('llm_cli_login', b.dataset.cliLogin);
        if (!r || !r.ok) return toast((r && r.error) || 'Không mở được cửa sổ đăng nhập', 'error');
        toast(`Đã mở cửa sổ đăng nhập (${r.command}) — đăng nhập xong bấm “Thử”`, 'ok');
      };
    });
    box.querySelector('[data-cli-cancel]').onclick = async () => { await api('llm_cli_cancel'); };
    box.querySelectorAll('[data-cli-quota]').forEach(b => {
      b.onclick = async () => { await api('llm_cli_quota_clear', b.dataset.cliQuota); toast('Lượt sau sẽ thử lại CLI', 'ok'); renderCliBox(false); };
    });
    const museDone = (r, b, label) => {
      if (b) { b.disabled = false; b.textContent = label; }
      if (!r || !r.ok) return toast((r && r.error) || 'muse-cli lỗi', 'error');
      const ck = r.check || {};
      toast(ck.ok ? `✓ muse-cli đã đăng nhập${ck.who ? ` (${ck.who})` : ''}` : `Đã lưu cookie nhưng kiểm tra chưa được: ${ck.error || ''}`, ck.ok ? 'ok' : 'warn');
      renderCliBox(true);
    };
    box.querySelectorAll('[data-muse-login]').forEach(b => {
      b.onclick = async () => {
        if (b.dataset.museLogin === 'paste') { box.querySelector('.set-cli-paste').classList.toggle('hidden'); return; }
        if (!confirm('Lấy đăng nhập muse.ai từ profile Muse của app cho muse-cli?\n\nApp mở ẩn profile Muse, vào muse.ai (chỉ đọc, không gửi tin nhắn), rồi ghi cookie đăng nhập vào file của muse-cli trên máy này. Bất kỳ ai dùng muse-cli trên máy đều dùng được tài khoản Muse này. Tiếp tục?')) return;
        const label = b.textContent; b.disabled = true; b.textContent = '⏳…';
        museDone(await api('llm_muse_login', 'profile', ''), b, label);
      };
    });
    const save = box.querySelector('[data-muse-save]');
    if (save) save.onclick = async () => {
      const ta = box.querySelector('.set-cli-paste textarea');
      const text = ta.value.trim();
      if (!/hatch_sess/.test(text)) return toast('Cookie cần có hatch_sess (DevTools → Application → Cookies → muse.ai)', 'error');
      const label = save.textContent; save.disabled = true; save.textContent = '⏳…';
      const r = await api('llm_muse_login', 'paste', text);
      if (r && r.ok) ta.value = '';
      museDone(r, save, label);
    };
    const chk = box.querySelector('[data-muse-check]');
    if (chk) chk.onclick = async () => {
      const label = chk.textContent; chk.disabled = true; chk.textContent = '⏳…';
      const r = await api('llm_muse_check');
      chk.disabled = false; chk.textContent = label;
      const ck = (r && r.check) || {};
      toast(ck.ok ? `✓ muse-cli đã đăng nhập${ck.who ? ` (${ck.who})` : ''}` : (ck.error || 'muse-cli lỗi'), ck.ok ? 'ok' : 'error');
    };
    box.querySelectorAll('[data-cli-test]').forEach(b => {
      b.onclick = async () => {
        const name = CLI_SITE_VI[b.dataset.cliTest] || b.dataset.cliTest;
        const isGrok = b.dataset.cliTest === 'grok';
        const typedKey = isGrok && $('#setGrokKey') ? $('#setGrokKey').value.trim() : '';
        if (isGrok && !typedKey && !res.grok_key) {  // chưa có key → không chạy CLI, chỉ nhắc nhập key
          $('#setGrokKey') && $('#setGrokKey').focus();
          return toast('Grok CLI cần xAI API key — nhập vào ô “xAI API key cho Grok CLI” bên dưới (lấy ở console.x.ai) rồi bấm Thử / Lưu', 'error');
        }
        if (!confirm(`Thử ${name} CLI: gửi 1 câu rất ngắn — tốn 1 lượt của ${name}${isGrok ? ' (tính tiền API xAI)' : ''}. Tiếp tục?`)) return;
        const label = b.textContent;
        b.disabled = true; b.textContent = '⏳…';
        const r = await api('llm_cli_test', b.dataset.cliTest, typedKey);
        b.disabled = false; b.textContent = label;
        if (!r || !r.ok) return toast((r && r.error) || 'CLI lỗi', 'error');
        toast(`✓ ${name} CLI trả lời “${r.reply}” sau ${r.secs}s`, 'ok');
      };
    });
    drawCliJob(res.job);
    if (busy) watchCliJob();
  }
  function drawCliJob(j) {
    const wrap = $('#setCliBox .set-cli-job');
    if (!wrap || !j || !(j.log || []).length) return;
    wrap.classList.remove('hidden');
    const who = j.action === 'node' ? 'Node.js' : j.action === 'python' ? 'Python' : (CLI_SITE_VI[j.site] || j.site);
    wrap.querySelector('[data-cli-job-title]').textContent = j.running ? `⏳ Đang ${j.action === 'update' ? 'cập nhật' : 'cài'} ${who}…`
      : j.ok ? `✓ Đã ${j.action === 'update' ? 'cập nhật' : 'cài'} ${who}` : `✗ ${who}: ${j.error || 'lỗi'}`;
    wrap.querySelector('[data-cli-cancel]').classList.toggle('hidden', !j.running);
    const pre = wrap.querySelector('[data-cli-log]');
    pre.textContent = (j.log || []).join('\n');
    pre.scrollTop = pre.scrollHeight;
  }
  function watchCliJob() {
    clearInterval(cliPoll);
    cliPoll = setInterval(async () => {
      if (!$('#setCliBox')) { clearInterval(cliPoll); return; }
      const r = await api('llm_cli_job');
      if (!r || !r.ok) return;
      drawCliJob(r.job);
      if (!r.job.running) {
        clearInterval(cliPoll);
        toast(r.job.ok ? '✓ Cài đặt xong' : `Cài đặt chưa xong: ${r.job.error || ''}`, r.job.ok ? 'ok' : 'error');
        renderCliBox(true);
      }
    }, 1000);
  }

  /* ------------------------------------------------------------ 🔒 khoá từng màn (Bảo mật) */
  const NO_LOCK = ['settings', 'help', 'folder', 'profiles'];  // nút / màn đã có khoá riêng
  function screenLocksHtml() {
    const locked = state.boot.settings.locked_screens || [];
    const items = menuItems().filter(it => !NO_LOCK.includes(it.view));
    return `<div class="set-scrlock"><div class="field"><span>🔒 Khoá màn hình</span>
      <small class="muted">Màn được khoá: bấm vào phải nhập mật khẩu quản trị (dùng chung với Cài đặt, tự khoá lại sau ${SET.ttl || 15} phút không
        thao tác). Fanpage Facebook / Quảng cáo / Quản lý bài đăng còn chặn luôn lệnh kết nối, sửa, đăng bài khi chưa mở khoá;
        đăng bài từ quy trình Canvas hoặc lịch đã duyệt vẫn chạy.${SET.lockOff ? ' <b>Đang chạy từ mã nguồn — khoá chỉ có hiệu lực ở bản build.</b>' : ''}</small></div>
      <div class="set-feat-groups"><div class="set-feat-group">${items.map(it => `<label class="set-feat ${locked.includes(it.view) ? 'on' : ''}" title="${esc(it.label)}">
        <span class="set-feat-ic">${it.icon}</span><span class="set-feat-txt"><b>${esc(it.label)}</b>${locked.includes(it.view) ? '<small>🔒 Đang khoá</small>' : ''}</span>
        <span class="set-switch"><input type="checkbox" data-scrlock="${esc(it.view)}" ${locked.includes(it.view) ? 'checked' : ''}><i></i></span></label>`).join('')}</div></div></div>`;
  }
  function bindScreenLocks() {
    const box = $('#setBlock-security');
    if (!box) return;
    box.querySelectorAll('[data-scrlock]').forEach(cb => {
      cb.onchange = async () => {
        const cur = new Set(state.boot.settings.locked_screens || []);
        if (cb.checked) cur.add(cb.dataset.scrlock); else cur.delete(cb.dataset.scrlock);
        state.boot.settings = await api('save_settings', { locked_screens: [...cur] });
        const saved = state.boot.settings.locked_screens || [];
        if (saved.includes(cb.dataset.scrlock) !== cb.checked) {
          cb.checked = !cb.checked;
          return toast('Cài đặt đang khoá — mở khoá Cài đặt rồi đổi lại', 'error');
        }
        cb.closest('.set-feat').classList.toggle('on', cb.checked);
        const txt = cb.closest('.set-feat').querySelector('.set-feat-txt');
        txt.querySelector('small') && txt.querySelector('small').remove();
        if (cb.checked) txt.insertAdjacentHTML('beforeend', '<small>🔒 Đang khoá</small>');
        if (window.applyScreenLocks) window.applyScreenLocks();
        toast(cb.checked ? '🔒 Đã khoá màn này' : 'Đã bỏ khoá màn này', 'ok');
      };
    });
  }

  async function saveMenus(menus) {
    state.boot.settings = await api('save_settings', { menus });
    applyMenus();
    const box = $('#setBlock-features .set-block-body');
    if (box) box.innerHTML = featuresHtml();
  }

  function bindFeatures() {
    const box = $('#setBlock-features');
    box.onchange = e => {
      const v = e.target.dataset.feat;
      if (!v) return;
      saveMenus({ ...(state.boot.settings.menus || {}), [v]: e.target.checked });
    };
    box.onclick = e => {
      const all = e.target.closest('[data-feat-all]');
      if (all) {
        const menus = { ...(state.boot.settings.menus || {}) };
        menuItems().filter(it => (it.group || 'KHÁC') === all.dataset.featAll && !LOCKED.includes(it.view))
          .forEach(it => { menus[it.view] = all.dataset.on === '1'; });
        return saveMenus(menus);
      }
      if (e.target.closest('[data-feat-reset]')) saveMenus({});
    };
  }

  /* ------------------------------------------------------------ nội dung từng khối */
  function blockBody(id) {
    const s = state.boot.settings;
    const lic = state.boot.license;
    switch (id) {
      case 'features': return featuresHtml();
      case 'models': return `<label class="check set-first" title="Tắt: chỉ dùng model trên trình duyệt (tài khoản đã đăng nhập) — ẩn mọi khoá API và model API; khối / cài đặt cũ đang chọn model API tự chạy bằng bản trình duyệt cùng hãng. Bật: hiện lại mục Khoá API & các model API (cần quyền quản trị)."><input type="checkbox" id="setUseApi" ${s.use_api_models ? 'checked' : ''}> 🔑 Dùng model qua API key <small class="muted">(đang ${s.use_api_models ? 'bật' : 'tắt — chỉ dùng model trình duyệt'})</small></label>
        ${s.use_api_models ? '' : '<p class="hint">Cần nhập khoá Anthropic / OpenAI / Gemini / <b>HeyGen</b> (khối 🧑‍💼 Video HeyGen)? Tick ô trên → bấm Lưu → mục <b>🔑 Khoá API &amp; model API</b> hiện ở cột trái.</p>'}
        <div id="setModels"><p class="hint">Đang tải danh sách model…</p></div>
        <p class="hint">Cài 1 lần — Studio, Nhân vật &amp; Layout, Viết content, Chiến dịch, Trợ lý quảng cáo dùng chung bộ model này.
          Trang đặc thù giữ lựa chọn riêng: Studio Muse AI (luôn Muse), Seedance, Workflow (từng nút). Tạo hình ảnh / Tạo video mặc định theo bộ này, vẫn đổi được từng lần.</p>`;
      case 'storage': return `
        <div class="field"><span>Thư mục lưu video</span>
          <div class="inline"><input id="setOut" value="${esc(s.output_dir)}" readonly><button class="btn ghost" id="setOutPick" type="button">Chọn…</button></div></div>
        <label class="check"><input type="checkbox" id="setCleanup" ${s.cleanup_temp ? 'checked' : ''}> Dọn file tạm sau khi render</label>`;
      case 'video': return `
        <div class="grid2">
          <label class="field"><span>FPS</span><select id="setFps">${opt([[24, '24 fps'], [30, '30 fps'], [60, '60 fps']], s.fps)}</select></label>
          <label class="field"><span>Âm lượng nhạc nền (0–1)</span><input id="setBgmVol" type="number" min="0" max="1" step="0.01" value="${s.bgm_volume}"></label>
          <label class="field"><span>Video tạo song song</span><select id="setParVideo">${opt([1, 2, 3, 4, 5, 6, 8, 10].map(n => [n, `${n} luồng (${n} Chrome)`]), s.max_parallel_video || 2)}</select></label>
          <label class="field"><span>Tác vụ ảnh song song</span><select id="setParImage">${opt([1, 2, 3, 4, 5, 6].map(n => [n, `${n} luồng`]), s.max_parallel_image || 2)}</select></label>
        </div>
        <div class="field"><span>Thư mục nhạc nền (trống = nhạc nền tự tổng hợp)</span>
          <div class="inline"><input id="setMusic" value="${esc(s.music_dir)}" readonly><button class="btn ghost" id="setMusicPick" type="button">Chọn…</button><button class="btn ghost" id="setMusicClear" type="button">Xoá</button></div></div>
        <label class="field"><span>🗣 Từ điển phát âm — tên riêng / thương hiệu giọng đọc hay đọc sai (mỗi dòng: viết = đọc). Áp cho VieNeu, giọng đọc Edge và lời thoại video; phụ đề vẫn giữ chữ gốc</span>
          <textarea id="setPronounce" rows="4" spellcheck="false" placeholder="KINGER = Kinh gơ&#10;NPK = en pê ca">${esc(s.pronounce ?? '')}</textarea></label>
        <label class="field"><span>Khi model trình duyệt (Muse, ChatGPT…) đề xuất phương án khác thay vì tạo ảnh / video</span>
          <select id="setOfferMode">${opt([['ask', 'Hỏi tôi — hiện form duyệt (không trả lời sau 3 phút thì tự đồng ý)'], ['auto', 'Tự đồng ý đề xuất']], s.offer_mode || 'ask')}</select></label>`;
      case 'browser': return `
        <label class="field"><span>Cách điều khiển Chrome</span><select id="setBrowserEngine">
          ${opt([['cdp', 'Chrome thật (CDP) — ít cờ tự động hoá, khuyên dùng'], ['playwright', 'Playwright — cách cũ (có thể chạy headless)']], s.browser_engine || 'cdp')}</select></label>
        <label class="field"><span>Trình duyệt cho Gemini / Grok / Dola Browser</span>
          <select id="setChannel">${opt([['chrome', 'Google Chrome'], ['msedge', 'Microsoft Edge'], ['chromium', 'Chromium (Playwright)']], s.browser_channel)}</select></label>
        <label class="check"><input type="checkbox" id="setShowBrowser" ${s.show_browser ? 'checked' : ''}> Hiện cửa sổ Chrome khi model chạy qua trình duyệt</label>
        <label class="check"><input type="checkbox" id="setKeepAlive" ${s.browser_keepalive ? 'checked' : ''}> Giữ Chrome mở sẵn cho mỗi tài khoản (chỉ với Chrome thật)</label>
        <div class="set-cli"><div class="field"><span>🧠 Cách gọi model chữ — Trình duyệt hay CLI</span>
          <small class="muted">Chọn CLI cho hãng nào thì mọi việc CHỮ của hãng đó (viết content, AI viết, storyboard, Trợ lý, chấm, phân tích video) chạy qua CLI
            dùng tài khoản đã đăng nhập — không mở Chrome. Tạo ảnh / video vẫn qua trình duyệt. CLI chạy trong thư mục tạm, chỉ trả lời chữ (không sửa file, không chạy lệnh).</small></div>
          <div id="setCliBox"><p class="hint">Đang kiểm tra CLI trên máy…</p></div>
          <label class="check"><input type="checkbox" id="setCliFallback" ${s.llm_cli_fallback !== false ? 'checked' : ''}> CLI lỗi (chưa cài, chưa đăng nhập, hết lượt…) → lượt đó tự chạy bằng trình duyệt</label></div>
        <details class="set-more"><summary>Giải thích</summary>
          <p class="hint">Chrome thật giữ “vân tay” giống Chrome bạn dùng hằng ngày nên ít bị Muse, Grok, Gemini… nghi là bot; gặp lỗi thì chuyển về Playwright.
            Giữ Chrome mở sẵn: lượt sau nhanh hơn, phiên đăng nhập luôn sẵn; rảnh 20 phút tự đóng, thoát app thì đóng hết (cổng gỡ lỗi chỉ trên 127.0.0.1).
            Ẩn cửa sổ: Chrome chạy ngoài màn hình, không hiện icon taskbar — cửa sổ đăng nhập luôn hiện.</p></details>`;
      case 'api': return `
        <p class="hint set-first">Mọi khoá API chỉ nhập tại đây — các màn hình khác chỉ hiện trạng thái. Khoá lưu trên máy này.</p>
        <label class="field"><span>Anthropic API key — Claude (Chiến dịch, Content, Workflow)</span><input id="setAnthropicKey" type="password" value="${esc(s.anthropic_api_key || '')}" placeholder="sk-ant-…" autocomplete="off"></label>
        <label class="field"><span>OpenAI API key — GPT Image + GPT viết bài</span><input id="setOpenAIKey" type="password" value="${esc(s.openai_api_key || '')}" placeholder="sk-…" autocomplete="off"></label>
        <label class="field"><span>Gemini API key — Gemini / Veo / Nano Banana</span><input id="setKey" type="password" value="${esc(s.gemini_api_key)}" placeholder="AIza…" autocomplete="off"></label>
        <label class="field"><span>HeyGen API key — khối 🧑‍💼 Video HeyGen (avatar đọc lời thoại)</span><input id="setHeyGenKey" type="password" value="${esc(s.heygen_api_key || '')}" placeholder="khoá ở app.heygen.com → Settings → API" autocomplete="off"></label>
        <div class="grid2">
          <label class="field"><span>Gemini model (API)</span><input id="setModel" value="${esc(s.gemini_model)}"></label>
          <label class="field"><span>Veo model</span><input id="setVeoModel" value="${esc(s.veo_model || '')}" placeholder="veo-3.1-generate-preview"></label>
          <label class="field"><span>OpenAI image model</span><input id="setOpenAIModel" value="${esc(s.openai_image_model || '')}" placeholder="gpt-image-1"></label>
          <label class="field"><span>Gemini image model</span><input id="setGeminiImgModel" value="${esc(s.gemini_image_model || '')}" placeholder="gemini-2.5-flash-image"></label>
        </div>`;
      case 'facebook': return `
        <div class="fb-user" id="setFbUser"></div>
        <div class="fb-perms" id="setFbPerms"></div>
        <label class="field"><span>User Access Token</span><textarea class="mono" id="fbToken" rows="2" spellcheck="false" placeholder="EAA…"></textarea></label>
        <div class="row set-wrap"><button class="btn primary" id="fbConnect" type="button">Kết nối & tải Fanpage</button>
          <button class="btn ghost" id="fbOpenExplorer" type="button">Graph API Explorer ↗</button>
          <button class="btn ghost" id="fbLogout" type="button">Ngắt kết nối</button></div>
        <details class="set-more"><summary>Lấy token thế nào?</summary>
          <p class="hint">Graph API Explorer → chọn Meta App → User Token với quyền <code>pages_show_list</code> <code>pages_read_engagement</code> <code>pages_manage_posts</code>
            (Quảng cáo: thêm <code>ads_read</code> <code>ads_management</code>) → Generate Access Token → dán vào ô trên.
            Nhập App ID + App Secret của đúng app đó để app tự đổi sang token dài hạn (~60 ngày).</p></details>
        <div class="grid2">
          <label class="field"><span>App ID</span><input id="fbAppId" placeholder="1234567890123456"></label>
          <label class="field"><span>Graph API version</span><input id="fbVersion" placeholder="v21.0"></label>
        </div>
        <label class="field"><span>App Secret</span><input id="fbAppSecret" type="password" placeholder="App Secret" autocomplete="off"></label>
        <button class="btn ghost" id="fbSaveApp" type="button">Lưu & kiểm tra App</button>
        <div class="set-fbpages"><div class="field"><span>📄 Fanpage — bật “Kết nối” cho trang muốn dùng và đăng bài</span></div>
          <div id="setFbPagesSlot"></div></div>`;
      case 'zalo': return '<div id="zaloBox" class="zl-box"></div>';
      case 'profiles': return `<p class="hint set-first">Mỗi profile là một Chrome riêng với tài khoản đăng nhập riêng. Gán profile cho model (Gemini, Grok, ChatGPT, Dola, Muse…) —
          khi tạo video / ảnh, app tự chọn profile <b>rảnh</b> của model đó, nên nhiều profile = nhiều tác vụ chạy song song.</p>
        <div id="setProfilesSlot"></div>`;
      case 'security': return SET.lockOff ? `
        <p class="hint set-first">Khoá Admin <b>đang tắt</b> vì app đang chạy từ mã nguồn (<code>python main.py</code>) — Cài đặt và
          chỉnh sửa Canvas mở tự do. Bản build (file .exe / .app) luôn bật khoá bằng mật khẩu quản trị.</p>` + screenLocksHtml() : `
        <p class="hint set-first">Cài đặt được khoá bằng mật khẩu quản trị — tự khoá lại sau ${SET.ttl || 15} phút không thao tác và khi thoát app.
          Bấm <b>🔒 Khoá</b> trên thanh để khoá ngay.</p>
        <div class="field"><span>Đổi mật khẩu quản trị</span>
          <input id="secOld" type="password" placeholder="Mật khẩu hiện tại" autocomplete="current-password"></div>
        <div class="grid2">
          <input id="secNew" type="password" placeholder="Mật khẩu mới (ít nhất 4 ký tự)" autocomplete="new-password">
          <input id="secNew2" type="password" placeholder="Nhập lại mật khẩu mới" autocomplete="new-password">
        </div>
        <button class="btn ghost" id="secChange" type="button">Đổi mật khẩu</button>` + screenLocksHtml();
      case 'ui': return `
        <label class="field"><span>Thời gian màn Loading khi mở app</span><select id="setSplash">
          ${opt([[0, 'Tắt — vào app ngay khi tải xong'], [1, '1 giây (mặc định)'], [2, '2 giây'], [3, '3 giây'], [5, '5 giây'], [8, '8 giây']], Number(s.splash_seconds ?? 1))}</select></label>
        <p class="hint">Thời gian tối thiểu tính từ lúc mở app — app tải lâu hơn thì màn Loading hiện tới khi xong. Áp dụng từ lần mở sau.</p>`;
      case 'license': return `
        <label class="field"><span>License server (trống = chế độ phát triển)</span><input id="setServer" value="${esc(s.license_server)}" placeholder="https://…"></label>
        <div class="lic-row"><span>${esc(lic.dev ? 'Chế độ phát triển — bỏ qua license' : (lic.active ? `Đã kích hoạt · ${lic.user?.email || ''}` : lic.message))}</span>
          <div class="row"><button class="btn ghost" id="licLogin" type="button">Đăng nhập Google</button><button class="btn ghost" id="licLogout" type="button">Đăng xuất</button></div></div>`;
      default: return '';
    }
  }

  // khối áp dụng ngay (không cần bấm Lưu) — không tính là “chưa lưu”
  const INSTANT = ['features', 'zalo', 'facebook', 'profiles', 'security'];

  // khối Profile dùng lại đúng giao diện màn Profile cũ (#profPane) — vẽ lại Cài đặt thì cất tạm về chỗ cũ, không mất
  function parkProfiles() {
    const pane = $('#profPane');
    if (pane && $('#page-profiles') && pane.parentElement !== $('#page-profiles')) $('#page-profiles').appendChild(pane);
    // 📣 danh sách Fanpage (giao diện màn Fanpage cũ, #fbPagesPane) — cất tạm về chỗ cũ khi vẽ lại / khoá Cài đặt
    const fb = $('#fbPagesPane'), home = $('#page-facebook .fb-layout');
    if (fb && home && fb.parentElement !== home) home.appendChild(fb);
  }

  /** Xoá nội dung Cài đặt khỏi màn hình (đang khoá → không để khoá API / token trong trang). */
  function clearContent() {
    parkProfiles();
    $('#setBody').innerHTML = '';
    $('#setNav').innerHTML = '';
    SET.rendered = false;
    SET.dirty = false;
  }

  async function lockState() {
    const res = await api('settings_lock_state');
    const st = res && res.ok ? res.lock : { has_password: true, unlocked: false, retry_in: 0, ttl_min: 15 };
    SET.ttl = st.ttl_min;
    SET.lockOff = !!st.disabled;  // chạy từ mã nguồn (python main.py): khoá Admin tắt — chỉ bản build mới khoá
    const btn = $('#setLockNow');
    if (btn) btn.classList.toggle('hidden', SET.lockOff);
    return st;
  }

  /** Biểu mẫu mật khẩu quản trị (lần đầu: tạo mật khẩu; sau đó: mở khoá) gắn vào box. ok() khi thành công. */
  function mountPassword(box, st, idp, { title, desc, cta, cancel }, ok) {
    const first = !st.has_password;
    box.innerHTML = `<form class="set-gate-card" autocomplete="off">
        <div class="set-gate-ic">🔒</div>
        <h3>${first ? 'Tạo mật khẩu quản trị' : title}</h3>
        <p class="muted">${first ? 'Cài đặt và việc chỉnh sửa quy trình Canvas được bảo vệ bằng mật khẩu quản trị (chứa khoá API, tài khoản Facebook, profile trình duyệt…). Đặt mật khẩu để chỉ người quản trị mở được. Mật khẩu được mã hoá (băm) và lưu trên máy này.' : desc}</p>
        <input type="password" id="${idp}Pw" placeholder="${first ? 'Mật khẩu mới (ít nhất 4 ký tự)' : 'Mật khẩu quản trị'}" autocomplete="${first ? 'new-password' : 'current-password'}">
        ${first ? `<input type="password" id="${idp}Pw2" placeholder="Nhập lại mật khẩu" autocomplete="new-password">` : ''}
        <small class="set-gate-err" id="${idp}Err">${st.retry_in ? `Nhập sai nhiều lần — thử lại sau ${st.retry_in} giây` : ''}</small>
        <div class="set-gate-actions">${cancel ? '<button class="btn ghost" type="button" data-cancel>Huỷ</button>' : ''}
          <button class="btn primary" type="submit">${first ? 'Tạo mật khẩu & tiếp tục' : cta}</button></div>
      </form>`;
    const q = sel => box.querySelector(sel);
    setTimeout(() => { if (q(`#${idp}Pw`)) q(`#${idp}Pw`).focus(); }, 30);
    if (cancel) q('[data-cancel]').onclick = cancel;
    q('form').onsubmit = async e => {
      e.preventDefault();
      const pw = q(`#${idp}Pw`).value;
      if (first && pw !== q(`#${idp}Pw2`).value) { q(`#${idp}Err`).textContent = 'Hai lần nhập không khớp'; return; }
      const res = first ? await api('settings_set_password', pw, '') : await api('settings_unlock', pw);
      if (!res.ok) { q(`#${idp}Err`).textContent = res.error; q(`#${idp}Pw`).select(); return; }
      if (first) toast('Đã tạo mật khẩu quản trị — từ giờ mở Cài đặt / sửa Canvas cần nhập mật khẩu này', 'ok');
      ok();
    };
  }

  /** Cổng mật khẩu của màn Cài đặt. keep = giữ nội dung đang sửa (hết phiên khi bấm Lưu). */
  function showGate(st, section, keep = false) {
    if (!keep) clearContent();
    const g = $('#setGate');
    g.classList.remove('hidden');
    mountPassword(g, st, 'gate', {
      title: keep ? 'Phiên Cài đặt đã hết hạn' : 'Đăng nhập Cài đặt',
      desc: `Nhập mật khẩu quản trị để mở Cài đặt. Tự khoá lại sau ${st.ttl_min} phút không thao tác.`,
      cta: 'Mở khoá',
    }, () => {
      if (keep && SET.rendered) { hideGate(); return toast('Đã mở khoá — bấm Lưu cài đặt lại', 'ok'); }
      openSettings(section);
    });
  }

  /** Thao tác cần quyền quản trị (VD sửa quy trình Canvas): đã mở khoá → true; chưa → hộp nhập mật khẩu, đúng → true. */
  window.requireAdmin = async function (what = 'chỉnh sửa') {
    const st = await lockState();
    if (st.unlocked) return true;
    return new Promise(resolve => {
      const wrap = document.createElement('div');
      wrap.className = 'set-gate set-gate-modal';
      document.body.appendChild(wrap);
      const done = v => { wrap.remove(); resolve(v); };
      mountPassword(wrap, st, 'adm', {
        title: 'Cần mở khoá',
        desc: `Nhập mật khẩu quản trị để ${what}. Dùng chung với Cài đặt — tự khoá lại sau ${st.ttl_min} phút không thao tác. Chạy quy trình không cần mở khoá.`,
        cta: 'Mở khoá', cancel: () => done(false),
      }, () => done(true));
      wrap.onkeydown = e => { if (e.key === 'Escape') done(false); };
      wrap.onclick = e => { if (e.target === wrap) done(false); };
    });
  };

  function hideGate() {
    $('#setGate').classList.add('hidden');
    $('#setGate').innerHTML = '';
  }

  function render() {
    parkProfiles();
    // 🔑 chỉ dùng model trình duyệt → khối Khoá API ẩn (vẫn nằm trong trang để Lưu đọc được ô; backend không ghi khoá)
    const hide = id => (id === 'api' && !state.boot.settings.use_api_models ? 'hidden' : '');
    $('#setNav').innerHTML = BLOCKS.map(([id, icon, title, desc]) => `
      <button class="set-nav-item ${hide(id)}" type="button" data-set-go="${id}"><span class="set-nav-ic">${icon}</span>
        <span><b>${esc(title)}</b><small>${esc(desc)}</small></span></button>`).join('');
    $('#setBody').innerHTML = BLOCKS.map(([id, icon, title, desc, wide]) => `
      <section class="set-block ${wide ? 'wide' : ''} ${hide(id)}" id="setBlock-${id}" data-block="${id}">
        <header class="set-block-head"><span class="set-block-ic">${icon}</span>
          <div><h3>${esc(title)}</h3><small>${esc(desc)}${INSTANT.includes(id) ? ' · <i>áp dụng ngay</i>' : ''}</small></div></header>
        <div class="set-block-body form">${blockBody(id)}</div>
      </section>`).join('');
    const pane = $('#profPane');
    if (pane) $('#setProfilesSlot').appendChild(pane);
    const fbPane = $('#fbPagesPane');
    if (fbPane && $('#setFbPagesSlot')) {
      $('#setFbPagesSlot').appendChild(fbPane);
      if (typeof refreshFacebook === 'function') refreshFacebook();
    }
    bind();
    SET.rendered = true;
    applyView();  // chỉ hiện tab đang chọn
    setDirty(false);
    if (typeof refreshProfiles === 'function') refreshProfiles();
  }

  function setDirty(on) {
    SET.dirty = on;
    $('#setDirty').classList.toggle('hidden', !on);
    $('#setSave').classList.toggle('pulse', on);
  }

  function bind() {
    const body = $('#setBody');
    const mark = e => {
      const block = e.target.closest('[data-block]');
      if (block && !INSTANT.includes(block.dataset.block)) setDirty(true);
    };
    body.oninput = mark;
    body.onchange = mark;
    $('#setOutPick').onclick = async () => {
      state.boot.settings = await api('pick_output_dir');
      $('#setOut').value = state.boot.settings.output_dir;
      renderHeader();
      refreshVideos();
    };
    $('#setMusicPick').onclick = async () => {
      state.boot.settings = await api('pick_music_dir');
      $('#setMusic').value = state.boot.settings.music_dir;
    };
    $('#setMusicClear').onclick = () => { $('#setMusic').value = ''; setDirty(true); };
    $('#licLogin').onclick = async () => { await saveSettings(false); licenseLogin(); };
    $('#licLogout').onclick = async () => { const r = await api('license_logout'); renderLicense(r.license); };
    bindFeatures();
    if ($('#secChange')) $('#secChange').onclick = async () => {  // không có khi khoá Admin tắt (chạy mã nguồn)
      if ($('#secNew').value !== $('#secNew2').value) return toast('Hai lần nhập mật khẩu mới không khớp', 'warn');
      const res = await api('settings_set_password', $('#secNew').value, $('#secOld').value);
      if (!res.ok) return toast(res.error, 'error');
      ['#secOld', '#secNew', '#secNew2'].forEach(id => { $(id).value = ''; });
      toast('Đã đổi mật khẩu quản trị', 'ok');
    };
    bindScreenLocks();
    renderCliBox(false);
    bindFbSettings();
    if (window.ZaloSettings) window.ZaloSettings.mount();
    renderModelSettings(false);
  }

  /* ------------------------------------------------------------ điều hướng trong trang + tìm kiếm */
  // mỗi nhóm cài đặt là 1 tab riêng: menu trái chọn tab, chỉ khối đó hiện (không cuộn cả trang).
  // Đang tìm kiếm → hiện mọi khối khớp từ khoá ở mọi tab; xoá từ khoá → về tab đang chọn.
  function goTo(id) {
    if (!$(`#setBlock-${id}`)) return;
    if ($('#setSearch').value) $('#setSearch').value = '';
    SET.tab = id;
    applyView();
  }

  function activeNav(id) {
    $$('.set-nav-item').forEach(b => b.classList.toggle('active', b.dataset.setGo === id));
  }

  const fold = t => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd');

  function filter() { applyView(); }

  function applyView() {
    if (!$(`#setBlock-${SET.tab}`)) SET.tab = BLOCKS[0][0];
    const k = fold($('#setSearch').value.trim());
    let shown = 0;
    $$('.set-block').forEach(b => {
      const show = k ? fold(b.textContent + ' ' + $$('input,select,textarea', b).map(x => x.placeholder || '').join(' ')).includes(k)
        : b.dataset.block === SET.tab;
      b.classList.toggle('hidden', !show);
      if (show) shown++;
    });
    $('#setBody').classList.toggle('tabbed', !k);
    $$('.set-nav-item').forEach(n => n.classList.toggle('dim', !!k && $(`#setBlock-${n.dataset.setGo}`).classList.contains('hidden')));
    $('#setEmpty').classList.toggle('hidden', shown > 0);
    activeNav(k ? '' : SET.tab);
    $('#setScroll').scrollTop = 0;
  }

  function init() {
    $('#setNav').onclick = e => { const b = e.target.closest('[data-set-go]'); if (b) goTo(b.dataset.setGo); };
    $('#setSearch').oninput = e => filter(e.target.value);
    $('#setSave').onclick = () => saveSettings(true);
    $('#setLockNow').onclick = async () => {
      if (SET.dirty && !confirm('Có thay đổi chưa lưu — khoá lại sẽ bỏ các thay đổi này?')) return;
      await api('settings_lock');
      toast('Đã khoá Cài đặt', 'ok');
      openSettings();
    };
    $('#setReload').onclick = () => {
      if (SET.dirty && !confirm('Bỏ các thay đổi chưa lưu và tải lại cài đặt?')) return;
      render();
    };
    document.addEventListener('keydown', e => {
      if (state.view === 'settings' && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveSettings(true); }
    });
  }

  /** Mở màn Cài đặt (section = id khối để cuộn tới, VD 'models', 'zalo'). Còn thay đổi chưa lưu thì giữ nguyên. */
  window.openSettings = async function (section) {
    if (state.view !== 'settings') navigate('settings');
    const st = await lockState();
    if (!st.unlocked) return showGate(st, section);
    hideGate();
    if (!SET.rendered || !SET.dirty) render();
    if (typeof section === 'string' && section) goTo(section);
    else applyView();
  };

  window.saveSettings = async function (done) {
    const st = await lockState();
    if (!st.unlocked) {  // hết 15 phút không thao tác → đăng nhập lại, giữ nguyên phần đang sửa
      toast('Phiên Cài đặt đã hết hạn — nhập mật khẩu rồi bấm Lưu lại', 'warn');
      return showGate(st, '', true);
    }
    // khoá API dán dính khoảng trắng / chữ thừa → backend chỉ giữ phần sk-… / AIza… đầu tiên; báo để người dùng biết
    const messy = [['#setOpenAIKey', 'OpenAI'], ['#setAnthropicKey', 'Anthropic'], ['#setKey', 'Gemini'], ['#setHeyGenKey', 'HeyGen']]
      .filter(([id]) => $(id) && /\s/.test($(id).value.trim())).map(([, name]) => name);
    if (messy.length) toast(`Khoá ${messy.join(', ')} có khoảng trắng / chữ thừa — đã tự lấy phần khoá đầu tiên. Kiểm tra lại nếu vẫn báo sai khoá.`, 'warn');
    const values = {
      cleanup_temp: $('#setCleanup').checked,
      splash_seconds: Number($('#setSplash').value),
      show_browser: $('#setShowBrowser').checked,
      browser_engine: $('#setBrowserEngine').value,
      browser_keepalive: $('#setKeepAlive').checked,
      ...Object.fromEntries($$('[data-cli-mode]').map(el => [`llm_mode_${el.dataset.cliMode}`, el.value])),  // 🧠 Trình duyệt / CLI
      ...($('#setCliFallback') ? { llm_cli_fallback: $('#setCliFallback').checked } : {}),
      ...($('#setGrokKey') && $('#setGrokKey').value.trim() ? { grok_cli_key: $('#setGrokKey').value.trim() } : {}),
      browser_channel: $('#setChannel').value,
      gemini_model: $('#setModel').value.trim(),
      veo_model: $('#setVeoModel').value.trim() || 'veo-3.1-generate-preview',
      openai_api_key: $('#setOpenAIKey').value.trim(),
      anthropic_api_key: $('#setAnthropicKey').value.trim(),
      openai_image_model: $('#setOpenAIModel').value.trim() || 'gpt-image-1',
      gemini_image_model: $('#setGeminiImgModel').value.trim() || 'gemini-2.5-flash-image',
      gemini_api_key: $('#setKey').value.trim(),
      ...($('#setHeyGenKey') ? { heygen_api_key: $('#setHeyGenKey').value.trim() } : {}),
      fps: parseInt($('#setFps').value, 10),
      max_parallel_video: parseInt($('#setParVideo').value, 10),
      max_parallel_image: parseInt($('#setParImage').value, 10),
      offer_mode: $('#setOfferMode').value,
      pronounce: $('#setPronounce').value,
      bgm_volume: Math.max(0, Math.min(1, parseFloat($('#setBgmVol').value) || 0)),
      music_dir: $('#setMusic').value,
      license_server: $('#setServer').value.trim(),
      use_api_models: !!($('#setUseApi') && $('#setUseApi').checked),
      ...readModelSettings(),
    };
    const before = sharedModels();
    const apiBefore = !!state.boot.settings.use_api_models;
    state.boot.settings = await api('save_settings', values);
    if (!!state.boot.settings.use_api_models !== apiBefore) {  // đổi chế độ model → tải lại để mọi danh sách model cập nhật
      toast(state.boot.settings.use_api_models ? 'Đã bật model qua API key — đang tải lại…' : 'Chỉ dùng model trình duyệt — đang tải lại…', 'ok');
      setDirty(false);
      setTimeout(() => location.reload(), 600);
      return;
    }
    $('#geminiModel').value = values.gemini_model;
    const r = await api('license_refresh');
    renderLicense(r.license);
    renderHeader();
    setDirty(false);
    if (done) toast('Đã lưu cài đặt', 'ok');
    document.dispatchEvent(new CustomEvent('va:settings'));  // các màn hình vẽ lại nhãn model dùng chung
    // Tạo hình ảnh / Tạo video: đổi model dùng chung → chọn luôn model đó (vẫn đổi được từng lần)
    const g = sharedModels();
    if (g.image !== before.image && $('#imgEngine') && state.boot.image_engines[g.image]) {
      $('#imgEngine').value = g.image;
      $('#imgEngine').dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (g.video !== before.video && $(`#provider option[value="${g.video}"]`)) {
      $('#provider').value = g.video;
      $('#provider').dispatchEvent(new Event('change', { bubbles: true }));
    }
  };

  window.SettingsPage = { init, applyMenus, firstView, isDirty: () => SET.dirty };
})();
