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
    ['api', '🔑', 'Khoá API & model API', 'Anthropic, OpenAI, Gemini'],
    ['facebook', '📣', 'Facebook · Meta', 'Token, App ID / Secret'],
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
      case 'models': return `<div id="setModels"><p class="hint">Đang tải danh sách model…</p></div>
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
        <label class="field"><span>Khi model trình duyệt (Muse, ChatGPT…) đề xuất phương án khác thay vì tạo ảnh / video</span>
          <select id="setOfferMode">${opt([['ask', 'Hỏi tôi — hiện form duyệt (không trả lời sau 3 phút thì tự đồng ý)'], ['auto', 'Tự đồng ý đề xuất']], s.offer_mode || 'ask')}</select></label>`;
      case 'browser': return `
        <label class="field"><span>Cách điều khiển Chrome</span><select id="setBrowserEngine">
          ${opt([['cdp', 'Chrome thật (CDP) — ít cờ tự động hoá, khuyên dùng'], ['playwright', 'Playwright — cách cũ (có thể chạy headless)']], s.browser_engine || 'cdp')}</select></label>
        <label class="field"><span>Trình duyệt cho Gemini / Grok / Dola Browser</span>
          <select id="setChannel">${opt([['chrome', 'Google Chrome'], ['msedge', 'Microsoft Edge'], ['chromium', 'Chromium (Playwright)']], s.browser_channel)}</select></label>
        <label class="check"><input type="checkbox" id="setShowBrowser" ${s.show_browser ? 'checked' : ''}> Hiện cửa sổ Chrome khi model chạy qua trình duyệt</label>
        <label class="check"><input type="checkbox" id="setKeepAlive" ${s.browser_keepalive ? 'checked' : ''}> Giữ Chrome mở sẵn cho mỗi tài khoản (chỉ với Chrome thật)</label>
        <details class="set-more"><summary>Giải thích</summary>
          <p class="hint">Chrome thật giữ “vân tay” giống Chrome bạn dùng hằng ngày nên ít bị Muse, Grok, Gemini… nghi là bot; gặp lỗi thì chuyển về Playwright.
            Giữ Chrome mở sẵn: lượt sau nhanh hơn, phiên đăng nhập luôn sẵn; rảnh 20 phút tự đóng, thoát app thì đóng hết (cổng gỡ lỗi chỉ trên 127.0.0.1).
            Ẩn cửa sổ: Chrome chạy ngoài màn hình, không hiện icon taskbar — cửa sổ đăng nhập luôn hiện.</p></details>`;
      case 'api': return `
        <p class="hint set-first">Mọi khoá API chỉ nhập tại đây — các màn hình khác chỉ hiện trạng thái. Khoá lưu trên máy này.</p>
        <label class="field"><span>Anthropic API key — Claude (Chiến dịch, Content, Workflow)</span><input id="setAnthropicKey" type="password" value="${esc(s.anthropic_api_key || '')}" placeholder="sk-ant-…" autocomplete="off"></label>
        <label class="field"><span>OpenAI API key — GPT Image + GPT viết bài</span><input id="setOpenAIKey" type="password" value="${esc(s.openai_api_key || '')}" placeholder="sk-…" autocomplete="off"></label>
        <label class="field"><span>Gemini API key — Gemini / Veo / Nano Banana</span><input id="setKey" type="password" value="${esc(s.gemini_api_key)}" placeholder="AIza…" autocomplete="off"></label>
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
        <button class="btn ghost" id="fbSaveApp" type="button">Lưu & kiểm tra App</button>`;
      case 'zalo': return '<div id="zaloBox" class="zl-box"></div>';
      case 'profiles': return `<p class="hint set-first">Mỗi profile là một Chrome riêng với tài khoản đăng nhập riêng. Gán profile cho model (Gemini, Grok, ChatGPT, Dola, Muse…) —
          khi tạo video / ảnh, app tự chọn profile <b>rảnh</b> của model đó, nên nhiều profile = nhiều tác vụ chạy song song.</p>
        <div id="setProfilesSlot"></div>`;
      case 'security': return SET.lockOff ? `
        <p class="hint set-first">Khoá Admin <b>đang tắt</b> vì app đang chạy từ mã nguồn (<code>python main.py</code>) — Cài đặt và
          chỉnh sửa Canvas mở tự do. Bản build (file .exe / .app) luôn bật khoá bằng mật khẩu quản trị.</p>` : `
        <p class="hint set-first">Cài đặt được khoá bằng mật khẩu quản trị — tự khoá lại sau ${SET.ttl || 15} phút không thao tác và khi thoát app.
          Bấm <b>🔒 Khoá</b> trên thanh để khoá ngay.</p>
        <div class="field"><span>Đổi mật khẩu quản trị</span>
          <input id="secOld" type="password" placeholder="Mật khẩu hiện tại" autocomplete="current-password"></div>
        <div class="grid2">
          <input id="secNew" type="password" placeholder="Mật khẩu mới (ít nhất 4 ký tự)" autocomplete="new-password">
          <input id="secNew2" type="password" placeholder="Nhập lại mật khẩu mới" autocomplete="new-password">
        </div>
        <button class="btn ghost" id="secChange" type="button">Đổi mật khẩu</button>`;
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
    $('#setNav').innerHTML = BLOCKS.map(([id, icon, title, desc]) => `
      <button class="set-nav-item" type="button" data-set-go="${id}"><span class="set-nav-ic">${icon}</span>
        <span><b>${esc(title)}</b><small>${esc(desc)}</small></span></button>`).join('');
    $('#setBody').innerHTML = BLOCKS.map(([id, icon, title, desc, wide]) => `
      <section class="set-block ${wide ? 'wide' : ''}" id="setBlock-${id}" data-block="${id}">
        <header class="set-block-head"><span class="set-block-ic">${icon}</span>
          <div><h3>${esc(title)}</h3><small>${esc(desc)}${INSTANT.includes(id) ? ' · <i>áp dụng ngay</i>' : ''}</small></div></header>
        <div class="set-block-body form">${blockBody(id)}</div>
      </section>`).join('');
    const pane = $('#profPane');
    if (pane) $('#setProfilesSlot').appendChild(pane);
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
    const messy = [['#setOpenAIKey', 'OpenAI'], ['#setAnthropicKey', 'Anthropic'], ['#setKey', 'Gemini']]
      .filter(([id]) => $(id) && /\s/.test($(id).value.trim())).map(([, name]) => name);
    if (messy.length) toast(`Khoá ${messy.join(', ')} có khoảng trắng / chữ thừa — đã tự lấy phần khoá đầu tiên. Kiểm tra lại nếu vẫn báo sai khoá.`, 'warn');
    const values = {
      cleanup_temp: $('#setCleanup').checked,
      splash_seconds: Number($('#setSplash').value),
      show_browser: $('#setShowBrowser').checked,
      browser_engine: $('#setBrowserEngine').value,
      browser_keepalive: $('#setKeepAlive').checked,
      browser_channel: $('#setChannel').value,
      gemini_model: $('#setModel').value.trim(),
      veo_model: $('#setVeoModel').value.trim() || 'veo-3.1-generate-preview',
      openai_api_key: $('#setOpenAIKey').value.trim(),
      anthropic_api_key: $('#setAnthropicKey').value.trim(),
      openai_image_model: $('#setOpenAIModel').value.trim() || 'gpt-image-1',
      gemini_image_model: $('#setGeminiImgModel').value.trim() || 'gemini-2.5-flash-image',
      gemini_api_key: $('#setKey').value.trim(),
      fps: parseInt($('#setFps').value, 10),
      max_parallel_video: parseInt($('#setParVideo').value, 10),
      max_parallel_image: parseInt($('#setParImage').value, 10),
      offer_mode: $('#setOfferMode').value,
      bgm_volume: Math.max(0, Math.min(1, parseFloat($('#setBgmVol').value) || 0)),
      music_dir: $('#setMusic').value,
      license_server: $('#setServer').value.trim(),
      ...readModelSettings(),
    };
    const before = sharedModels();
    state.boot.settings = await api('save_settings', values);
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
