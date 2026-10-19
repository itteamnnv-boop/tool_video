"""Dola/Doubao browser adapter. Selectors are based on the supplied extension.

No request rewriting, cookie swapping or automatic submission retries. Each lane
submits one scene at a time so a newly discovered video has an unambiguous owner.
"""
import base64
import re
import time
from urllib.parse import urlsplit, parse_qs

from .domain import StudioError, format_prompt
from .media import is_watermarked_url, master_api_url, url_is_master
from .notices import NOTICE_HELP, classify_notice

PROVIDER_URLS = {"dola": "https://www.dola.com/chat/", "doubao": "https://www.doubao.com/chat/"}
VIDEO_URLS = {provider: url + "create-image" for provider, url in PROVIDER_URLS.items()}
VIDEO_PANEL = '[data-input-engine-actionbar-render-entry-key="creation-video-generation-params-panel"]:visible'
EDITORS = '.tiptap.ProseMirror:visible, .ProseMirror:visible, [data-testid="chat_input_input"]:visible, textarea:visible, [contenteditable="true"]:visible'
SEND = '#flow-end-msg-send:visible, button[class*="send-msg-btn"]:visible, [data-testid="chat_input_send_button"]:visible, button[aria-label*="send" i]:visible, button[aria-label*="gửi" i]:visible'
MENU = '[role="menuitem"]:visible, [role="option"]:visible, [role="menuitemradio"]:visible, .semi-dropdown-item:visible, [data-slot="dropdown-menu-item"]:visible'
UPLOAD_BUTTON = ('[data-testid="upload_file_button"]:visible, button[aria-label*="upload" i]:visible, '
                 'button[aria-label*="attach" i]:visible, button:visible:text-is("+")')
# Tag the composer box: closest ancestor of the editor that also holds the send or upload button.
MARK_COMPOSER_JS = r"""ed => {
  document.querySelectorAll('[data-va-composer]').forEach(e => e.removeAttribute('data-va-composer'));
  const SEL = '[data-testid="chat_input_send_button"],[data-testid="upload_file_button"],#flow-end-msg-send,button[class*="send"]';
  let n = ed;
  for (let i = 0; n && n !== document.body && i < 20; i++, n = n.parentElement) if (n.querySelector(SEL)) break;
  (n && n !== document.body ? n : ed.parentElement).setAttribute('data-va-composer', '1');
}"""
# Images / background images / file chips currently shown in the composer box.
MEDIA_SNAPSHOT_JS = r"""box => {
  const out = [];
  for (const el of box.querySelectorAll('*')) {
    if (el.tagName === 'IMG' && el.getBoundingClientRect().width) out.push('img:' + (el.currentSrc || el.src));
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== 'none' && /url\(/.test(bg)) out.push('bg:' + bg.slice(0, 300));
  }
  return out;
}"""
IS_EDITABLE_JS ="e => e.isContentEditable || ['TEXTAREA', 'INPUT'].includes(e.tagName)"
MODE_ATTR = "data-va-mode-chip"
MODE_WAIT_SECONDS = 20
VIDEO_CONTROLS = {
    "model": '[data-input-engine-actionbar-control-key="video-model"]:visible, [data-testid="chat_input_action_video-model"]:visible',
    "duration": '[data-input-engine-actionbar-control-key="video-duration"]:visible, [data-testid="chat_input_action_video-duration"]:visible',
    "ratio": '[data-input-engine-actionbar-control-key="video-ratio"]:visible, [data-testid="chat_input_action_video-ratio"]:visible',
}
MODE_TARGETS = {"pro": re.compile(r"^(?:Pro|专业|Chuyên sâu)\b|2\.5", re.I),
                "fast": re.compile(r"^(?:Fast|Nhanh|快速)\b|2\.0", re.I)}
# Find the smallest visible element whose text (minus chevrons) is just a mode name, inside the lowest composer area,
# then tag its closest clickable ancestor so Playwright can target it.
MODE_CHIP_JS = r"""() => {
  const NAME = /^(Pro|Fast|Nhanh|Thinking|Expert|专业|快速|思考|Chuyên sâu)$/i;
  const clean = t => (t || '').replace(/[›>⌄▾▼›⌄]/g, ' ').replace(/\s+/g, ' ').trim();
  const hits = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('nav,aside,header,[class*="sidebar"]')) continue;
    if (!NAME.test(clean(el.innerText))) continue;
    if ([...el.children].some(c => NAME.test(clean(c.innerText)))) continue;  // keep the innermost match
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.width > 260) continue;
    hits.push({el, y: r.y});
  }
  if (!hits.length) return '';
  hits.sort((a, b) => b.y - a.y);  // composer sits at the bottom of the chat
  let el = hits[0].el;
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    if (n.matches('button,[role="button"],[role="combobox"],[aria-haspopup]') || getComputedStyle(n).cursor === 'pointer') { el = n; break; }
  }
  document.querySelectorAll('[data-va-mode-chip]').forEach(e => e.removeAttribute('data-va-mode-chip'));
  const id = 'm' + Date.now();
  el.setAttribute('data-va-mode-chip', id);
  return id;
}"""
# After opening the chip: find the menu option whose first line is the wanted mode (menus often add a description
# line, e.g. "Fast · Answers quickly"). The option lives in a portal layer, so search the whole page but skip the chip.
MODE_OPTION_JS = r"""(want) => {
  const RX = want === 'pro' ? /^(Pro|专业|Chuyên sâu)\b/i : /^(Fast|Nhanh|快速)\b/i;
  const chip = document.querySelector('[data-va-mode-chip]');
  const hits = [];
  for (const el of document.querySelectorAll('body *')) {
    if (chip && (chip === el || chip.contains(el) || el.contains(chip))) continue;
    const first = (el.innerText || '').split('\n').map(s => s.trim()).filter(Boolean)[0] || '';
    if (!RX.test(first) || (el.innerText || '').length > 120) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    hits.push(el);
  }
  // Prefer the outermost clickable row (menuitem/option/button/pointer) among the matches.
  const clickable = hits.filter(el => el.matches('[role^="menuitem"],[role="option"],button,[role="button"],li') || getComputedStyle(el).cursor === 'pointer');
  const el = (clickable.length ? clickable : hits)[0];
  if (!el) return '';
  const id = 'o' + Date.now();
  el.setAttribute('data-va-mode-chip-option', id);
  return id;
}"""
ATTACHMENTS ='[class*="attachment"] img, [class*="upload"] img, [class*="preview"] img, [data-testid*="attachment"], img[src^="blob:"], img[src^="data:image"]'

# Read only the provider's rendered cards / React props; never traverse window.
HARVEST_JS = r"""() => {
  const out = [], seen = new WeakSet();
  const walk = (v, depth) => {
    if (!v || depth > 7 || out.length > 100) return;
    if (typeof v === 'string') {
      if (v.length < 200000 && /fallback_api|video_model/.test(v)) { try { walk(JSON.parse(v), depth + 1); } catch {} }
      return;
    }
    if (typeof v !== 'object' || seen.has(v)) return;
    seen.add(v);
    if (v.fallback_api || v.fallbackApi) out.push({fallbackApi:v.fallback_api || v.fallbackApi, keySeed:v.key_seed || '', providerVideoId:String(v.vid || v.video_id || ''),reportedModel:String(v.model_name || v.model_version || v.model_id || '')});
    if (Array.isArray(v)) { v.slice(0,80).forEach(x => walk(x,depth+1)); return; }
    for (const k of ['video_model','creationsVideoList','video','content_block','contentBlock','message','messages','data','payload','result','list','items','children']) if (v[k]) walk(v[k],depth+1);
  };
  for (const el of document.querySelectorAll('video,[class*="video-player"],[class*="block-video"],[class*="creation"],[class*="media-card"]')) {
    if (el.tagName === 'VIDEO') {
      const url = el.currentSrc || el.src || el.querySelector('source')?.src;
      if (url && /^https?:/.test(url)) out.push({url,source:'dom',width:el.videoWidth,height:el.videoHeight,duration:el.duration || null});
    }
    const key = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    let fiber = key && el[key];
    for (let i=0; fiber && i<25; i++,fiber=fiber.return) {
      walk(fiber.memoizedProps,0);
      let s=fiber.memoizedState;
      for(let j=0;s && j<10;j++,s=s.next) walk(s.memoizedState,0);
    }
  }
  return out;
}"""

DECODE_TOKEN_JS = r"""async ({token,seed}) => {
  const decode=s=>{for(const v of [s,s.replace(/[$@#]/g,c=>({'$':'+','@':'/','#':'='}[c]))]){try{return Uint8Array.from(atob(v.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(v.length/4)*4,'=')),c=>c.charCodeAt(0));}catch{}}return null;};
  const data=decode(token), bytes=decode(seed); if(!data || !bytes) return '';
  const h1=new Uint8Array(await crypto.subtle.digest('SHA-512',bytes.slice(0,32)));
  const salt=Uint8Array.from('4dd4c2e6b83162090e52b3c7a6733ba4'.match(/../g),s=>parseInt(s,16));
  const input=new Uint8Array(h1.length+salt.length);input.set(h1);input.set(salt,h1.length);
  const h2=new Uint8Array(await crypto.subtle.digest('SHA-512',input)),key=h2.slice(0,16),iv=h2.slice(16,32);
  const attempts=data[0]===168 && data[1]===0 && data[2]===1 && data[3]===0 ?
    [[data.slice(4),key,iv],[data.slice(4),iv,key],[data.slice(36),key,data.slice(20,36)],[data.slice(36),key,iv]] : [[data,key,iv]];
  for(const [payload,k,v] of attempts){if(!payload.length || payload.length%16)continue;try{
    const ck=await crypto.subtle.importKey('raw',k,'AES-CBC',false,['decrypt']);
    const url=new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-CBC',iv:v},ck,payload)).trim();
    if(/^https:\/\//.test(url))return url;
  }catch{}}return '';
}"""


def allowed_url(url, provider=None):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        suffixes = ("dola.com", "doubao.com") if provider else (
            "dola.com", "doubao.com", "byteintlapi.com", "ibytedtos.com", "byteoversea.com",
            "byteimg.com", "bytedance.com", "doubaocdn.com", "volccdn.com", "volces.com",
            "snssdk.com", "tiktokcdn.com", "tiktokcdn-us.com", "bytevcloud.com", "bytefcdn.com")
        return parts.scheme == "https" and not parts.username and not parts.password and parts.port in (None, 443) and any(
            host == suffix or host.endswith("." + suffix) for suffix in ((provider + ".com",) if provider else suffixes))
    except (ValueError, TypeError):
        return False


def extract_media(data, decode_token=None, key_seed=""):
    """Decode plain/base64 provider URLs and prefer actual bitrate/size metadata."""
    found = []

    def walk(value, depth=0, seed=key_seed):
        if depth > 12:
            return
        if isinstance(value, list):
            for item in value[:200]:
                walk(item, depth + 1, seed)
        elif isinstance(value, dict):
            seed = value.get("key_seed") or seed
            for key in ("main_url", "play_url", "download_url"):
                token = value.get(key)
                if not isinstance(token, str):
                    continue
                url = token
                if token.startswith("qAAB") and seed and decode_token:
                    url = decode_token(token, seed)
                elif not url.startswith("https://"):
                    try:
                        url = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
                    except (ValueError, UnicodeDecodeError):
                        continue
                if allowed_url(url):
                    def num(k):
                        try:
                            return float(value.get(k) or 0)
                        except (TypeError, ValueError):
                            return 0
                    width, height = num("width") or num("vwidth"), num("height") or num("vheight")
                    found.append({"url": url, "source": "provider_response", "width": width,
                                  "height": height, "score": (num("bitrate") or num("real_bitrate")) + width * height})
            for v in value.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1, seed)

    walk(data)
    return sorted(found, key=lambda x: x["score"], reverse=True)


class BrowserAdapter:
    def __init__(self, context, page, config, check_cancel, event):
        self.context, self.page, self.cfg = context, page, config
        self.check, self.event = check_cancel, event
        self.before_submit = check_cancel
        self.resolved = {}
        self.resolve_failures = {}
        self.response_media = {}
        self.request_count = 0
        self.video_mode = False
        self.model_evidence = {}
        page.on("response", self._response)

    def _response(self, response):
        # Only JSON video responses; ignore unrelated analytics and large payloads.
        try:
            if not allowed_url(response.url) or not re.search(r"video|creation|message|chat", response.url, re.I):
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            size = int(response.headers.get("content-length", "0"))
            if size > 2_000_000:
                return
            for item in extract_media(response.json()):
                self.response_media[item["url"].split("?", 1)[0]] = item
        except Exception:
            pass  # DOM collection remains available if a streaming response cannot be read.

    def open(self, url=""):
        self.check()
        direct = self.cfg.get("generationRoute", "auto") != "chat" and self.cfg["model"] == "2.5"
        direct = direct or self.cfg.get("generationRoute") == "video"
        history = bool(url)
        url = url or (VIDEO_URLS if direct else PROVIDER_URLS)[self.cfg["provider"]]
        if not allowed_url(url, self.cfg["provider"]):
            raise StudioError("INVALID_URL", "Chỉ mở lịch sử trên đúng nhà cung cấp đã chọn")
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if direct and not history:
            tab = self.page.locator('[data-testid="creation-skill-switch-tab-video"]').first
            try:
                tab.wait_for(state="visible", timeout=7000)
                tab.click(timeout=3000)
            except Exception:
                pass  # Some providers open directly in video mode and do not expose this tab.

    def editor(self):
        # Prefer the lowest visible editor outside navigation/search regions.
        editors = self.page.locator(EDITORS)
        candidates = []
        for i in range(editors.count()):
            el = editors.nth(i)
            if el.evaluate("e => !!e.closest('nav,aside,header,[class*=sidebar]')"):
                continue
            box = el.bounding_box()
            if box and box["width"] > 100:
                candidates.append((box["y"], el))
        if not candidates:
            return None
        el = max(candidates, key=lambda x: x[0])[1]
        # Dola's data-testid="chat_input_input" is a wrapper <div>; the real editor is the contenteditable inside it.
        if not el.evaluate(IS_EDITABLE_JS):
            inner = el.locator('[contenteditable="true"]:visible, textarea:visible, input[type="text"]:visible').first
            if not inner.count():
                return None
            el = inner
        return el

    def ready(self):
        text = self.page.locator("body").inner_text(timeout=3000)
        if re.search(r"Continue with Google|Scan QR code|Sign in to continue|扫码登录", text, re.I):
            raise StudioError("NOT_LOGGED_IN", "Chưa đăng nhập — bấm Đăng nhập cho profile đã chọn")
        return self.editor() is not None

    def _dismiss_banners(self):
        # Cookie banner ("Dola uses cookies… OK") can cover the composer controls.
        for selector in ('button:visible:text-is("OK")', 'button:visible:text-is("Accept")'):
            btn = self.page.locator(selector).first
            try:
                if btn.count():
                    btn.click(timeout=1500)
            except Exception:
                pass  # banner already gone

    def _mode_chip(self):
        """Locate the chat-mode chip (e.g. "Pro ›") by its visible text, whatever element type the page uses."""
        found = self.page.evaluate(MODE_CHIP_JS)
        return self.page.locator(f'[{MODE_ATTR}="{found}"]').first if found else None

    @staticmethod
    def _mode_label(el):
        return re.sub(r"[›>⌄▾▼\s]+", " ", el.inner_text()).strip()

    def configure(self):
        self.check()
        self._dismiss_banners()
        route = self.cfg.get("generationRoute", "auto")
        if self.video_mode and route != "chat" and not self.page.locator(VIDEO_CONTROLS["model"]).count():
            self.open()
        if route == "auto" and self.cfg["model"] == "2.5" and "/chat/create-image" in self.page.url:
            try:
                self.page.locator(VIDEO_CONTROLS["model"]).first.wait_for(state="visible", timeout=10000)
            except Exception as exc:
                raise StudioError("MODEL_UNSUPPORTED", "Workspace Video chưa có bộ chọn Seedance 2.5. Kiểm tra profile đã đăng nhập hoặc chọn luồng Pro/Fast chat.") from exc
        if route != "chat" and self.page.locator(VIDEO_CONTROLS["model"]).count():
            return self._configure_video()
        if route == "video":
            for role in ("tab", "button"):
                activate = self.page.get_by_role(role, name=re.compile(r"^(?:Create videos?|Tạo video|Video|视频生成|生成视频)$", re.I)).first
                if activate.count():
                    activate.click(timeout=5000)
                    self.page.wait_for_timeout(700)
                    break
            return self._configure_video()
        # Exit a specialized skill; Studio Pro uses the normal Pro/Fast chat flow.
        exit_skill = self.page.locator('[data-testid*="exit-skill"]:visible, .bg-g-exit-skill-btn-bg:visible').first
        if exit_skill.count():
            exit_skill.click(timeout=3000)
        self._dismiss_banners()
        pro = self.cfg["model"] == "2.5"
        target, want = (MODE_TARGETS["pro"], "Pro") if pro else (MODE_TARGETS["fast"], "Fast")
        # The composer (and its mode chip) renders after the page's JS finishes — wait instead of checking once.
        chip, deadline = None, time.monotonic() + MODE_WAIT_SECONDS
        while time.monotonic() < deadline:
            self.check()
            chip = self._mode_chip()
            if chip is not None:
                break
            self.page.wait_for_timeout(700)
        if chip is None:
            raise StudioError("MODEL_UNSUPPORTED", f"Không thấy chế độ {want}. Chọn luồng Video để kiểm tra model Seedance trực tiếp, hoặc đăng nhập lại.")
        if not target.search(self._mode_label(chip)):
            chip.click(timeout=3000)
            self.page.wait_for_timeout(700)
            option = self.page.evaluate(MODE_OPTION_JS, "pro" if pro else "fast")
            if not option:
                self.page.keyboard.press("Escape")
                raise StudioError("MODEL_UNSUPPORTED", f"Menu chế độ chat không có lựa chọn {want} cho tài khoản này")
            self.page.locator(f'[{MODE_ATTR}-option="{option}"]').first.click(timeout=3000)
            self.page.wait_for_timeout(700)
            chip = self._mode_chip() or chip
        if not target.search(self._mode_label(chip)):
            raise StudioError("MODEL_UNSUPPORTED", f"Đã chọn nhưng chưa xác minh được chế độ {want} trên trang")
        self.event(f"Đã xác minh chế độ chat {want}; thông số Seedance được gửi trong prompt.")
        self.video_mode = False
        self.model_evidence = {"generationRoute": "chat", "chatMode": want, "requestedVideoModel": self.cfg["model"], "videoModelVerified": False}
        return self.model_evidence

    def _select_video_value(self, key, pattern, label):
        control = self.page.locator(VIDEO_CONTROLS[key]).first
        if not control.count():
            raise StudioError("MODEL_UNSUPPORTED" if key == "model" else "CONFIG_UNSUPPORTED", f"Trang chưa cung cấp bộ chọn {label}")
        if not pattern.search(control.inner_text()):
            control.click(timeout=5000)
            option = self.page.locator(MENU).filter(has_text=pattern).first
            try:
                option.wait_for(state="visible", timeout=4000)
                option.click(timeout=3000)
            except Exception as exc:
                self.page.keyboard.press("Escape")
                raise StudioError("MODEL_UNSUPPORTED" if key == "model" else "CONFIG_UNSUPPORTED", f"Tài khoản/trang hiện tại không có {label}") from exc
        if not pattern.search(control.inner_text()):
            raise StudioError("CONFIG_UNSUPPORTED", f"Chưa xác minh được {label} sau khi chọn")

    def _configure_video(self):
        model = self.cfg["model"]
        self._select_video_value("model", re.compile(rf"(?<!\d){re.escape(model)}(?!\d)"), "Seedance " + model)
        if self.page.locator(VIDEO_PANEL).count():
            self._configure_video_panel()
        else:
            self._select_video_value("duration", re.compile(rf"(?<!\d){self.cfg['duration'][:-1]}\s*(?:s|秒|giây)(?!\w)", re.I), "thời lượng " + self.cfg["duration"])
            if self.cfg["aspectRatio"] != "none":
                self._select_video_value("ratio", re.compile(re.escape(self.cfg["aspectRatio"]) + r"(?!\d)"), "tỉ lệ " + self.cfg["aspectRatio"])
        self.video_mode = True
        self.model_evidence = {"generationRoute": "video", "requestedVideoModel": model, "videoModelVerified": True,
                               "videoModelLabel": self.page.locator(VIDEO_CONTROLS["model"]).first.inner_text()}
        self.event(f"Đã chọn Seedance {model} trực tiếp trong bộ chọn video, {self.cfg['duration']}, {self.cfg['aspectRatio']}")
        return self.model_evidence

    def _configure_video_panel(self):
        trigger = self.page.locator(VIDEO_PANEL).first
        trigger.click(timeout=5000)
        panel_id = trigger.get_attribute("aria-controls")
        panel = self.page.locator(f'[id="{panel_id}"]') if panel_id else self.page.get_by_role("menu").last
        try:
            panel.wait_for(state="visible", timeout=4000)
            ratio = self.cfg["aspectRatio"]
            if ratio != "none":
                button = panel.get_by_role("button", name=ratio, exact=True)
                if not button.count():
                    raise StudioError("CONFIG_UNSUPPORTED", f"Trang không cung cấp tỉ lệ {ratio}")
                button.click(timeout=3000)
            if not panel.is_visible():
                trigger.click(timeout=3000)
            slider = panel.get_by_role("slider").first
            if not slider.count():
                raise StudioError("CONFIG_UNSUPPORTED", "Không tìm thấy thanh chọn thời lượng video")
            section = slider.locator('xpath=ancestor::section[1]')
            labels = section.inner_text() + "\n" + "\n".join(section.locator("span").all_text_contents())
            numbers = [int(v) for v in re.findall(r"(?<!\d)(\d+)\s*s\b", labels, re.I)]
            if not numbers:
                raise StudioError("CONFIG_UNSUPPORTED", "Chưa đọc được giới hạn thời lượng trên trang")
            low, high, wanted = min(numbers), max(numbers), int(self.cfg["duration"][:-1])
            if not low <= wanted <= high:
                raise StudioError("CONFIG_UNSUPPORTED", f"Model trên tài khoản này cho phép {low}–{high}s; hãy chọn thời lượng trong khoảng này hoặc chuyển luồng chat.")
            minimum, maximum = float(slider.get_attribute("aria-valuemin")), float(slider.get_attribute("aria-valuemax"))
            steps = (maximum - minimum) * (wanted - low) / (high - low) if high != low else 0
            if abs(steps - round(steps)) > 0.01:
                raise StudioError("CONFIG_UNSUPPORTED", f"Không có mức thời lượng {wanted}s trên thanh chọn")
            slider.focus()
            slider.press("Home")
            for _ in range(round(steps)):
                self.check()
                slider.press("ArrowRight")
            current = float(slider.get_attribute("aria-valuenow"))
            if abs(current - minimum - steps) > 0.01:
                raise StudioError("CONFIG_UNSUPPORTED", "Chưa xác nhận được giá trị thanh thời lượng")
        finally:
            self.page.keyboard.press("Escape")
        if str(wanted) + "s" not in trigger.inner_text().replace(" ", ""):
            raise StudioError("CONFIG_UNSUPPORTED", "Thời lượng hiển thị chưa khớp lựa chọn")
        if ratio != "none" and ratio not in trigger.inner_text():
            raise StudioError("CONFIG_UNSUPPORTED", "Tỉ lệ hiển thị chưa khớp lựa chọn")

    def attach(self, image):
        self.check()
        editor = self.editor()
        if editor is None:
            raise StudioError("COMPOSER_NOT_FOUND", "Không tìm thấy trình soạn thảo để đính kèm ảnh")
        # The preview thumbnail renders in the composer box (the ancestor holding the send / "+" buttons), not next to
        # the ProseMirror node itself — so scope the check to that box.
        editor.evaluate(MARK_COMPOSER_JS)
        scope = self.page.locator("[data-va-composer]").first
        if not scope.count():
            raise StudioError("COMPOSER_NOT_FOUND", "Không xác định được khung soạn thảo để đính kèm ảnh")
        before = set(scope.evaluate(MEDIA_SNAPSHOT_JS))
        busy_sel = ('[aria-busy="true"]:visible, [role="progressbar"]:visible, [class*="uploading"]:visible, '
                    '[class*="loading"]:visible, [class*="progress"]:visible, [class*="spin"]:visible')
        busy_before = scope.locator(busy_sel).count()  # phần tử sẵn có trong khung soạn (không phải đang tải)
        path = str(image["path"])
        file_input = self._image_input()
        if file_input is not None:
            file_input.set_input_files(path, timeout=60000)
        else:
            # No input yet: the "+" button creates it / opens the OS file chooser — catch the chooser instead.
            button = self.page.locator(UPLOAD_BUTTON).first
            if not button.count():
                raise StudioError("ATTACHMENT_NOT_VERIFIED", "Không tìm thấy nút tải ảnh (+) cạnh trình soạn thảo")
            try:
                with self.page.expect_file_chooser(timeout=5000) as chooser:
                    button.click(timeout=3000)
                chooser.value.set_files(path)
            except Exception:
                file_input = self._image_input()
                if file_input is None:
                    self.page.keyboard.press("Escape")
                    raise StudioError("ATTACHMENT_NOT_VERIFIED", "Bấm nút + nhưng không mở được ô chọn ảnh") from None
                file_input.set_input_files(path, timeout=60000)
        # Ảnh lớn / mạng chậm: chờ preview tối đa 90 giây; có preview rồi thì chờ hết dấu hiệu đang tải tối đa 4 phút
        # (chỉ tính dấu hiệu MỚI xuất hiện so với trước khi đính kèm). Quá giờ mà đã có preview → vẫn gửi.
        start = time.monotonic()
        seen_at = None
        while True:
            self.check()
            current = set(scope.evaluate(MEDIA_SNAPSHOT_JS))
            busy = scope.locator(busy_sel).count() > busy_before
            shown = bool(current - before) or image["name"] in scope.inner_text()
            if shown and seen_at is None:
                seen_at = time.monotonic()
            if shown and not busy:
                return {"verified": True, "evidence": "new_attachment_preview", "name": image["name"]}
            if seen_at is not None and time.monotonic() - seen_at > 240:
                return {"verified": True, "evidence": "preview_shown_upload_slow", "name": image["name"]}
            if seen_at is None and time.monotonic() - start > 90:
                raise StudioError("ATTACHMENT_NOT_VERIFIED",
                                  "Sau 90 giây vẫn chưa thấy preview ảnh đính kèm; chưa gửi prompt")
            yield

    def _image_input(self):
        """Hidden <input type=file> that accepts images (Dola lists extensions: .png,.jpeg,.jpg,.webp…)."""
        inputs = self.page.locator('input[type="file"]:not([capture])')
        for i in range(inputs.count()):
            accept = (inputs.nth(i).get_attribute("accept") or "").lower()
            if not accept or "image" in accept or re.search(r"\.(png|jpe?g|webp)\b", accept):
                return inputs.nth(i)
        return None

    def _type_prompt(self, editor, formatted):
        """Textarea → fill. ProseMirror/tiptap → click, clear, insert text like a user, then verify it landed."""
        if editor.evaluate("e => e.tagName === 'TEXTAREA' || e.tagName === 'INPUT'"):
            editor.fill(formatted, timeout=5000)
            return
        editor.click(timeout=5000)
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Backspace")
        self.page.keyboard.insert_text(formatted)
        self.page.wait_for_timeout(300)
        probe = re.sub(r"\s+", " ", formatted)[:40]
        if probe not in re.sub(r"\s+", " ", editor.inner_text()):
            editor.fill(formatted, timeout=5000)  # fallback for editors that ignore synthetic typing
            if probe not in re.sub(r"\s+", " ", editor.inner_text()):
                raise StudioError("COMPOSER_NOT_FOUND", "Không nhập được prompt vào ô soạn thảo; chưa gửi")

    def submit(self, text, baseline=None):
        self.check()
        self.before_submit()
        editor = self.editor()
        if editor is None:
            raise StudioError("COMPOSER_NOT_FOUND", "Không tìm thấy trình soạn thảo")
        formatted = format_prompt(text, self.cfg, video_mode=self.video_mode)
        self._type_prompt(editor, formatted)
        self.check()
        sent = self.page.locator('[data-testid="send_message"], [data-message-author-role="user"], [class*="send-message"], [class*="send_message"], [data-testid="message_text_content"]').filter(has_text=formatted[:80])
        before = sent.count()
        before_url = self.page.url
        send = self.page.locator(SEND).first
        ready_deadline = time.monotonic() + 5
        while time.monotonic() < ready_deadline and (not send.count() or not send.is_enabled()):
            self.check()
            if baseline is not None:
                self.outcome_error(baseline)
            yield
        if not send.count() or not send.is_enabled():
            raise StudioError("SUBMIT_FAILED", "Không tìm thấy nút gửi sẵn sàng; chưa bấm gửi")
        # Commit once. A timeout after this point requires a manual check, never a retry.
        self.before_submit()
        send.click(timeout=5000, no_wait_after=True)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            self.check()
            if baseline is not None:
                self.outcome_error(baseline)
            current = self.editor()
            if current is not None:
                value = current.input_value() if current.evaluate("e => e.tagName === 'TEXTAREA' || e.tagName === 'INPUT'") else current.inner_text()
                echoed = sent.count() > before
                navigated_chat = self.video_mode and self.page.url != before_url and re.search(r"/chat/[^/?]+", self.page.url)
                if not value.strip() and (echoed or navigated_chat):
                    return
            yield
        raise StudioError("SUBMISSION_UNCERTAIN", "Đã bấm gửi nhưng chưa xác minh được tin nhắn; kiểm tra chat trước khi thử lại")

    def discover(self):
        self.check()
        items = list(self.response_media.values())
        for record in self.page.evaluate(HARVEST_JS):
            if record.get("url") and allowed_url(record["url"]):
                items.append(record)
            fallback = record.get("fallbackApi")
            if fallback and allowed_url(fallback):
                requested_api = master_api_url(fallback) if self.cfg.get("preferUnwatermarked", True) else fallback
                if requested_api not in self.resolved and time.monotonic() >= self.resolve_failures.get(requested_api, 0):
                    try:
                        response = self.context.request.get(requested_api, timeout=10000)
                        if response.ok:
                            seed = record.get("keySeed") or parse_qs(urlsplit(fallback).query).get("key_seed", [""])[0]
                            variants = extract_media(response.json(), self._decode_token, seed)
                            variants = [v for v in variants if not is_watermarked_url(v["url"])]
                            if variants:
                                self.resolved[requested_api] = {**variants[0], "providerVideoId": record.get("providerVideoId", ""),
                                    "fallbackApi": fallback, "source": "provider_master" if self.cfg.get("preferUnwatermarked", True) else "provider_response",
                                    "reportedModel": record.get("reportedModel", ""),
                                    "watermarkStatus": "master_requested" if self.cfg.get("preferUnwatermarked", True) else "unknown"}
                            else:
                                self.resolve_failures[requested_api] = time.monotonic() + 10
                    except Exception as exc:
                        if requested_api not in self.resolved:
                            self.resolve_failures[requested_api] = time.monotonic() + 10
                            self.event(f"Chưa resolve được video master: {type(exc).__name__}")
                if requested_api in self.resolved:
                    items.append(self.resolved[requested_api])
        unique = {}
        for item in items:
            url = item.get("url", "")
            if is_watermarked_url(url):
                # Keep preview provenance for the manual logo-removal tool; master is preferred below.
                item = {**item, "watermarkStatus": "watermarked"}
            elif url_is_master(url):
                item = {**item, "watermarkStatus": "master_requested"}
            key = item.get("providerVideoId") or url.split("?", 1)[0]
            unique[key] = {**item, "key": key}
        return sorted(unique.values(), key=lambda v: v.get("source") == "provider_master", reverse=True)

    def _decode_token(self, token, seed):
        try:
            return self.page.evaluate(DECODE_TOKEN_JS, {"token": token, "seed": seed})
        except Exception:
            return ""

    def notice_snapshot(self):
        return self.page.locator('[data-testid="receive_message"]:visible, [role="alert"]:visible, [role="dialog"]:visible, [class*="toast"]:visible').evaluate_all("""els => {
            const state = window.__vaSeedanceNotices ||= {ids:new WeakMap(),next:1};
            return els.map(el=>{if(!state.ids.has(el))state.ids.set(el,state.next++);return {id:state.ids.get(el),text:el.innerText || '',blocking:el.getAttribute('role')==='dialog'};});
        }""")

    def outcome_error(self, baseline):
        # Compare element identity + content: a repeated toast on a new node is still a fresh notice.
        previous = {(item["id"], item["text"]) for item in baseline}
        for item in self.notice_snapshot():
            if not item["blocking"] and (item["id"], item["text"]) in previous:
                continue
            code = classify_notice(item["text"])
            if code:
                raw = item["text"].strip()[:1000]
                raise StudioError(code, NOTICE_HELP[code] + "\nThông báo gốc: " + raw, provider_message=raw)

    def new_chat(self):
        self.check()
        if self.video_mode:
            self.open()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                self.check()
                if self.ready() and self.page.locator(VIDEO_CONTROLS["model"]).count():
                    self.resolved.clear()
                    self.resolve_failures.clear()
                    self.response_media.clear()
                    return
                yield
            raise StudioError("NEW_CHAT_FAILED", "Chưa mở lại được workspace tạo video")
        button = self.page.get_by_role("button", name=re.compile(r"New chat|Cuộc trò chuyện mới|新对话|开启新对话", re.I)).first
        if not button.count():
            button = self.page.get_by_role("link", name=re.compile(r"New chat|Cuộc trò chuyện mới|新对话", re.I)).first
        if not button.count():
            raise StudioError("NEW_CHAT_FAILED", "Không tìm thấy New Chat; đã dừng để tránh gửi nhầm cuộc trò chuyện")
        old = self.page.url
        button.click(timeout=5000)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            self.check()
            history = self.page.locator('[data-testid="receive_message"], [data-testid="send_message"]')
            if self.editor() is not None and (self.page.url != old or history.count() == 0):
                self.resolved.clear()
                self.resolve_failures.clear()
                self.response_media.clear()
                return
            yield
        raise StudioError("NEW_CHAT_FAILED", "Chưa xác nhận được cuộc trò chuyện mới; đã dừng")

    def execute(self, job, image, checkpoint, media_found):
        deadline = time.monotonic() + 40
        while not self.ready():
            self.check()
            if time.monotonic() > deadline:
                raise StudioError("COMPOSER_NOT_FOUND", "Editor chưa sẵn sàng; kiểm tra đăng nhập và giao diện trang")
            yield
        baseline = self.notice_snapshot()
        try:
            evidence = self.configure()
        except Exception:
            self.outcome_error(baseline)
            raise
        self.outcome_error(baseline)
        checkpoint("preparing", **(evidence or {}))
        before = {item["key"] for item in self.discover()}
        if image:
            checkpoint("attaching")
            evidence = yield from self.attach(image)
            checkpoint("attaching", attachmentEvidence=evidence)
        checkpoint("submitting", chatUrl=self.page.url)
        yield from self.submit(job["text"], baseline=baseline)
        checkpoint("submitted", submittedAt=time.time(), chatUrl=self.page.url)
        checkpoint("generating")
        deadline = time.monotonic() + self.cfg["timeoutSeconds"]
        preview_at = None
        while time.monotonic() < deadline:
            self.check()
            self.outcome_error(baseline)
            new = [item for item in self.discover() if item["key"] not in before]
            if new:
                if self.cfg.get("preferUnwatermarked", True):
                    master = [item for item in new if item.get("source") == "provider_master" or item.get("watermarkStatus") == "master_requested"]
                    if master:
                        new = master
                    else:
                        preview_at = preview_at or time.monotonic()
                        if time.monotonic() - preview_at < 20:
                            yield
                            continue
                        self.event("Chưa lấy được bản master; lưu video hiện có với trạng thái watermark chưa xác minh. Có thể dùng Gỡ watermark.")
                # One pending scene per lane. Keep additional outputs attached to that scene.
                for item in new:
                    media_found(item)
                return
            yield
        raise StudioError("RENDER_TIMEOUT", "Đã gửi nhưng hết thời gian chờ video; dùng Quét lịch sử để thu lại")

    def scan_history(self, media_found):
        previous, stable = None, 0
        for _ in range(50):
            self.check()
            for item in self.discover():
                media_found(item)
            position = self.page.evaluate("""() => {
                const nodes=[...document.querySelectorAll('main,[class*=scroll], [class*=chat]')];
                const el=nodes.filter(e=>e.scrollHeight>e.clientHeight+100).sort((a,b)=>b.clientHeight-a.clientHeight)[0] || document.scrollingElement;
                el.scrollTop=0; return [el.scrollHeight,el.scrollTop];
            }""")
            stable = stable + 1 if position == previous else 0
            if stable >= 4:
                return
            previous = position
            yield
