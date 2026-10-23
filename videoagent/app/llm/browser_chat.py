"""Browser Mode: điều khiển trang chat AI (Gemini, Grok) bằng Chrome/Edge đã đăng nhập — không cần API key.

Mỗi model dùng các profile trình duyệt được gán trong "Profile trình duyệt" (app/browser_profiles.py) — mỗi profile là
một bộ tài khoản riêng; đăng nhập từng model trong từng profile một lần. Selector của các trang có thể đổi theo thời gian — chỉnh trong SITES bên dưới.
"""
import logging
import os
import threading
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from ..browser_profiles import DEFAULT_ID, profile_dir, profile_session
from .base import LLMError, LLMProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatSite:
    name: str
    url: str
    input_selectors: tuple
    response_selector: str
    # Số phần tử response_selector mới xuất hiện sau mỗi lần gửi (Grok đếm cả bong bóng của người dùng).
    bubbles_per_turn: int
    stop_selector: str
    # Trang bị Cloudflare chặn khi headless → chạy cửa sổ thật nhưng đặt ngoài màn hình.
    headless_ok: bool
    login_markers: tuple  # chuỗi xuất hiện trong URL/nội dung trang khi chưa đăng nhập
    prompt_suffix: str = ""  # dặn thêm cuối mỗi prompt (vd. Claude: trả lời ngay trong chat, không mở artifact)
    # Phần câu trả lời thật bên trong response_selector (bỏ khối suy nghĩ, nhãn đọc màn hình); "" = cả phần tử
    answer_selector: str = ""
    # trang mở cuộc trò chuyện MỚI cho mỗi lượt hỏi ("" = url); đăng nhập vẫn dùng url
    chat_url: str = ""


def _image_files(images: list) -> list[Path]:
    """Ảnh gửi kèm → đường dẫn file: nhận đường dẫn, hoặc (bytes, mime) như ảnh sản phẩm của màn Tạo video (ghi ra file
    tạm để nạp vào ô đính kèm của trang chat)."""
    import tempfile

    out, tmp = [], None
    for item in images or []:
        if isinstance(item, (tuple, list)) and item and isinstance(item[0], (bytes, bytearray)):
            tmp = tmp or Path(tempfile.mkdtemp(prefix="va_chat_img_"))
            mime = str(item[1] if len(item) > 1 else "image/png")
            path = tmp / f"img_{len(out) + 1}.{ {'image/jpeg': 'jpg', 'image/webp': 'webp'}.get(mime, 'png') }"
            path.write_bytes(item[0])
            out.append(path)
        elif Path(str(item)).is_file():
            out.append(Path(str(item)))
    return out


SITES = {
    "doubao": ChatSite(
        name="Doubao", url="https://www.doubao.com/chat/",
        input_selectors=("[data-testid='chat_input_input']", "div[contenteditable='true']", "textarea"),
        response_selector="[data-testid='receive_message']", bubbles_per_turn=1,
        stop_selector="[data-testid*='stop' i]", headless_ok=False,
        login_markers=("扫码登录", "登录后即可"),
    ),
    "gemini": ChatSite(
        name="Gemini",
        url="https://gemini.google.com/app",
        input_selectors=(
            "rich-textarea div.ql-editor[contenteditable='true']",
            "div[contenteditable='true'][role='textbox']",
            "textarea",
        ),
        response_selector="model-response message-content",
        bubbles_per_turn=1,
        stop_selector="button[aria-label*='Stop'], button[aria-label*='Dừng']",
        headless_ok=True,
        login_markers=("accounts.google.com",),
    ),
    "grok": ChatSite(
        name="Grok",
        url="https://grok.com/",
        input_selectors=(
            "div.ProseMirror[contenteditable='true']",
            "div[contenteditable='true'][aria-label*='Grok']",
            "textarea[aria-label*='Grok']",
        ),
        response_selector="div.message-bubble",
        bubbles_per_turn=2,
        stop_selector="button[aria-label*='Stop'], button[aria-label*='Dừng']",
        headless_ok=False,
        login_markers=("Sign up to continue", "Sign in to continue", "accounts.x.ai"),
    ),
    # ChatGPT (chatgpt.com) — dùng cho Tạo hình ảnh qua trình duyệt (OpenAI Browser).
    "chatgpt": ChatSite(
        name="ChatGPT",
        url="https://chatgpt.com/",
        input_selectors=("#prompt-textarea", "div[contenteditable='true']", "textarea"),
        response_selector="[data-message-author-role='assistant']",
        bubbles_per_turn=1,
        stop_selector="button[data-testid='stop-button']",
        headless_ok=False,
        login_markers=("auth.openai.com", "Log in to get smarter responses"),
    ),
    # Dola (dola.com, ByteDance). Selector câu trả lời theo cấu trúc Doubao — chưa kiểm chứng khi đã đăng nhập.
    "dola": ChatSite(
        name="Dola",
        url="https://www.dola.com/chat/",
        input_selectors=(
            "[data-testid='chat_input_input']",
            "div[contenteditable='true']",
            "textarea",
        ),
        response_selector="[data-testid='receive_message']",
        bubbles_per_turn=1,
        stop_selector="[data-testid*='stop' i], button[aria-label*='Stop' i]",
        headless_ok=False,
        login_markers=("Continue with Google", "Scan QR code with Dola App"),
    ),
    # Muse (muse.ai, trợ lý AI của Meta — Muse Image / Muse Video). Selector theo cấu trúc chung, chưa kiểm chứng
    # khi đã đăng nhập; câu trả lời chữ dùng cơ chế dự phòng đọc chữ trên trang (_page_answer).
    "muse": ChatSite(
        name="Muse",
        url="https://muse.ai/",
        chat_url="https://muse.ai/thread/new",  # cuộc trò chuyện mới (side chat) — không dùng "Main chat" có lịch sử cũ
        input_selectors=(
            "textarea[aria-label='Message']",  # ô nhập "Main chat" (kiểm chứng 10/2026 khi làm Muse Image/Video)
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
            "textarea",
        ),
        response_selector="main [data-message-author-role='assistant'], main [data-testid*='assistant' i]",
        bubbles_per_turn=1,
        stop_selector="button[aria-label*='Stop' i], button[aria-label*='Dừng' i]",
        headless_ok=False,
        login_markers=("Log in or create an account", "Mobile number or email"),
        # Muse là trợ lý làm được việc khác (tạo ảnh/video, gửi email…) → viết storyboard / content chỉ trả lời bằng chữ
        prompt_suffix=("\n\n(Chỉ trả lời bằng văn bản ngay trong khung chat — không tạo ảnh, video, không dùng công cụ "
                       "hay thực hiện hành động nào khác.)"),
    ),
    # Claude (claude.ai, Anthropic) — chỉ viết chữ (kịch bản, storyboard, content, prompt). Mỗi câu trả lời là
    # div[data-testid=assistant-message][data-is-streaming] gồm: h2.sr-only "Claude responded: <tóm tắt, mất ký tự _>",
    # khối suy nghĩ (data-cds=TurnStatus) và nội dung thật trong data-cds=Prose. Prose hiển thị markdown nên " bị đổi
    # thành “ ” → dặn để JSON trong khối code (giữ nguyên ký tự); extract_json cũng tự sửa ngoặc cong.
    # Bài dài có thể bị đưa sang artifact → dặn trả lời ngay trong chat.
    "claude": ChatSite(
        name="Claude",
        url="https://claude.ai/new",
        input_selectors=(
            "div.ProseMirror[contenteditable='true']",
            "div[contenteditable='true'][aria-label*='prompt' i]",
            "div[contenteditable='true']",
            "textarea",
        ),
        response_selector="[data-testid='assistant-message'], div[data-is-streaming]:not([data-testid])",
        answer_selector="[data-cds='Prose'], .font-claude-response",
        bubbles_per_turn=1,
        stop_selector="button[aria-label*='Stop' i], button[aria-label*='Dừng' i], div[data-is-streaming='true']",
        headless_ok=False,
        login_markers=("claude.ai/login", "Continue with Google", "Continue with email"),
        prompt_suffix="\n\n(Trả lời trực tiếp trong khung chat — không tạo artifact, file hay tài liệu riêng. "
                      "Nếu câu trả lời là JSON thì đặt toàn bộ JSON trong MỘT khối code ```json.)",
    ),
}

# Chữ của câu trả lời: nếu có sel thì chỉ lấy các khối khớp sel (nối lại); luôn bỏ chữ của nhãn ẩn .sr-only
# (vd. Claude "Claude responded: …" — bản tóm tắt bị cắt, chứa nửa JSON làm hỏng việc đọc JSON).
ANSWER_TEXT_JS = """(e, sel) => {
  const parts = sel ? [...e.querySelectorAll(sel)].filter(x => !x.parentElement.closest(sel)) : [];
  const nodes = parts.length ? parts : [e];
  return nodes.map(node => {
    let t = node.innerText || '';
    for (const s of node.querySelectorAll('.sr-only')) {
      const x = (s.innerText || '').trim();
      if (x) t = t.replace(x, '');
    }
    return t.trim();
  }).filter(Boolean).join('\\n\\n');
}"""
FOCUSED_INPUT_JS = """() => {
  const el = document.activeElement;
  return !!el && el.isConnected && (el.isContentEditable || el.tagName === 'TEXTAREA');
}"""
OFFSCREEN_ARG = "--window-position=-32000,-32000"
SEND_BUTTONS = ("[data-testid='send-button'], #composer-submit-button, button[aria-label*='Send' i], "
                "button[aria-label*='Gửi' i], button[data-testid*='send' i]")
# Prompt còn nằm trong ô soạn thảo đang focus (chưa gửi đi)?
PENDING_JS = """(probe) => {
  const els = [document.activeElement, ...document.querySelectorAll('textarea, [contenteditable="true"]')];
  return els.some(e => e && ((e.value || e.innerText || '').replace(/\\s+/g, ' ').includes(probe)));
}"""
PAGE_JUNK = (r"ChatGPT can make mistakes", r"ChatGPT có thể mắc lỗi", r"Ask anything", r"Hỏi bất kỳ điều gì",
             r"Check important info", r"Gemini can make mistakes", r"Grok can make mistakes",
             r"Do you like this personality\??", r"Bạn có thích tính cách này",
             r"Claude can make mistakes", r"Claude có thể mắc lỗi", r"Reply to Claude", r"Trả lời Claude")
ANSWER_PREFIX = re.compile(r"^\s*(ChatGPT said:|ChatGPT đã nói:|Gemini said:|Grok said:|Claude said:|Claude đã nói:)\s*", re.I)


_flagged: set = set()  # cửa sổ app đã ẩn icon taskbar (để trả lại nếu sau này nó lên màn hình / không còn là của app)


def _hide_offscreen_from_taskbar() -> None:
    """Windows: cửa sổ Chrome chạy ngoài màn hình (OFFSCREEN_ARG) vẫn hiện icon trên thanh taskbar → đổi thành
    cửa sổ công cụ (WS_EX_TOOLWINDOW) để ẩn icon. Chỉ đụng cửa sổ Chrome nằm ngoài màn hình, không đụng Chrome của người dùng."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_style.restype = ctypes.c_ssize_t
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    set_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]

    def restyle(hwnd, style, show_cmd):
        user32.ShowWindow(hwnd, 0)  # đổi kiểu cửa sổ khi đang ẩn thì taskbar mới cập nhật
        set_style(hwnd, GWL_EXSTYLE, style)
        user32.ShowWindow(hwnd, show_cmd)

    def visit(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1" or not user32.IsWindowVisible(hwnd):
            return True
        style = get_style(hwnd, GWL_EXSTYLE)
        # Xét VỊ TRÍ BÌNH THƯỜNG (không phải toạ độ hiện tại): cửa sổ thu nhỏ — hoặc đang trong lúc thu nhỏ — Windows
        # báo toạ độ -32000, TRÙNG vị trí "ngoài màn hình" → trước đây Chrome của người dùng bị ẩn nhầm thành ô nhỏ.
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
        ours = wp.rcNormalPosition.left <= -20000  # Chrome chạy ẩn của app (mở ở ngoài màn hình)
        iconic = user32.IsIconic(hwnd)
        if not ours:
            # Chrome của người dùng / Chrome đang "Hiện": không ẩn; bị ẩn nhầm (bản cũ / do app) → trả lại nút taskbar.
            # Chỉ gỡ khi cửa sổ thu nhỏ hoặc chính app đã gắn cờ (menu / popup của Chrome tự có cờ này — giữ nguyên).
            if style & WS_EX_TOOLWINDOW and (iconic or hwnd in _flagged):
                restyle(hwnd, style & ~WS_EX_TOOLWINDOW, 7 if iconic else 8)  # 7: vẫn thu nhỏ · 8: SW_SHOWNA
                _flagged.discard(hwnd)
            return True
        if iconic:
            user32.ShowWindow(hwnd, 4)  # Chrome ẩn của app bị thu nhỏ (Win+D…) → về lại ngoài màn hình, không cướp focus
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.left > -20000:  # Chrome của app vừa được đưa lên màn hình ("Hiện") → giữ nguyên
            return True
        if not style & WS_EX_TOOLWINDOW:
            # SW_SHOWNOACTIVATE: hiện lại (vẫn ngoài màn hình), không cướp focus
            restyle(hwnd, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW, 4)
            _flagged.add(hwnd)
        return True

    user32.EnumWindows(proc(visit), 0)


_offscreen = {"open": 0, "running": False}
_taskbar_lock = threading.Lock()


def _pool_hidden() -> bool:
    """Còn Chrome mở sẵn (kiểu HaoHao) đang chạy ẩn ngoài màn hình → tiếp tục ẩn icon taskbar."""
    from . import chrome_pool

    return keepalive_mode() and not show_browser_setting() and chrome_pool.any_alive()


def _ensure_taskbar_watch() -> None:
    if os.name != "nt":
        return
    with _taskbar_lock:
        if not _offscreen["running"]:
            _offscreen["running"] = True
            threading.Thread(target=_taskbar_watch, daemon=True, name="hide-chrome-taskbar").start()


def _taskbar_watch() -> None:
    while True:
        with _taskbar_lock:
            if _offscreen["open"] <= 0 and not _pool_hidden():
                _offscreen.update(open=0, running=False)
                return
        try:
            _hide_offscreen_from_taskbar()
        except Exception:  # API Windows lỗi → bỏ qua, chỉ là icon taskbar
            pass
        time.sleep(0.4)


def _track_offscreen(ctx) -> None:
    """Đếm cửa sổ Chrome đang chạy ngoài màn hình; còn cửa sổ nào thì luồng nền còn ẩn icon taskbar."""
    if os.name != "nt":
        return
    with _taskbar_lock:
        _offscreen["open"] += 1
        if not _offscreen["running"]:
            _offscreen["running"] = True
            threading.Thread(target=_taskbar_watch, daemon=True, name="hide-chrome-taskbar").start()

    def closed(*_):
        with _taskbar_lock:
            _offscreen["open"] -= 1

    ctx.on("close", closed)


def keepalive_mode() -> bool:
    """Cài đặt "Giữ Chrome mở sẵn cho mỗi tài khoản" (kiểu HaoHao) — chỉ có hiệu lực ở chế độ Chrome thật (CDP)."""
    from ..config import settings

    return bool(settings.get("browser_keepalive"))


def cdp_mode() -> bool:
    """Cài đặt chung "Cách điều khiển Chrome": cdp = Chrome thật, chỉ cờ tối thiểu (mặc định); playwright = cách cũ."""
    from ..config import settings

    return (settings.get("browser_engine") or "cdp") == "cdp"


# Chrome thật (CDP): chỉ các cờ cần cho tự động hoá ổn định — không cờ thử nghiệm / tắt tiện ích / keychain giả của
# Playwright, không headless, cửa sổ kích thước thật (không giả lập viewport). CDP vẫn qua đường ống nội bộ (pipe),
# không mở cổng mạng.
REAL_CHROME_ARGS = ("--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                    "--disable-blink-features=AutomationControlled", "--window-size=1280,1043")


def _launch_real_chrome(pw, channel: str, folder: Path, offscreen: bool):
    args = [f"--user-data-dir={folder}", "--remote-debugging-pipe", *REAL_CHROME_ARGS]
    if offscreen:
        args.append(OFFSCREEN_ARG)
    args.append("about:blank")
    kwargs = dict(user_data_dir=str(folder), headless=False, no_viewport=True, ignore_default_args=True, args=args)
    if channel and channel != "chromium":
        kwargs["channel"] = channel
    return pw.chromium.launch_persistent_context(**kwargs)


def show_browser_setting() -> bool:
    """Cài đặt chung "Hiện cửa sổ Chrome" (màn Cài đặt) — áp cho MỌI model chạy qua trình duyệt."""
    from ..config import settings

    return bool(settings.get("show_browser"))


def _launch(pw, channel: str, *, visible: bool, offscreen: bool = False, profile: dict | None = None,
            always_visible: bool = False):
    """Mở Chrome với thư mục profile đang giữ (profile_session). Profile có thể đặt trình duyệt riêng (Chrome/Edge).
    Hiện hay ẩn theo cài đặt chung (màn Cài đặt), không theo từng màn: bật → cửa sổ hiện trên màn hình; tắt → cửa sổ
    thật nhưng nằm ngoài màn hình + ẩn icon taskbar (nơi cần cửa sổ) hoặc headless. always_visible: cửa sổ đăng nhập."""
    real = cdp_mode()
    show = always_visible or show_browser_setting()
    if show:
        visible, offscreen = True, False
    else:  # Chrome thật (CDP) không bao giờ chạy headless: ẩn = cửa sổ ngoài màn hình + ẩn icon taskbar
        offscreen, visible = offscreen or visible or real, False
    folder = profile["dir"] if profile else profile_dir(DEFAULT_ID)
    folder.mkdir(parents=True, exist_ok=True)
    channel = (profile or {}).get("channel") or channel
    from . import chrome_pool

    if real and keepalive_mode() and not always_visible:  # kiểu HaoHao: dùng lại Chrome mở sẵn của profile
        ctx = chrome_pool.connect(pw, folder, channel or "chrome", REAL_CHROME_ARGS, show=show)
        if not show:
            _ensure_taskbar_watch()
        return ctx
    chrome_pool.stop(folder)  # cửa sổ đăng nhập / chế độ khác: không để 2 Chrome giữ cùng 1 profile
    if real:
        ctx = _launch_real_chrome(pw, channel, folder, offscreen)
        if offscreen:
            _track_offscreen(ctx)
        return ctx
    args = ["--disable-blink-features=AutomationControlled"]
    if offscreen:
        args.append(OFFSCREEN_ARG)
    kwargs = dict(
        user_data_dir=str(folder),
        headless=not (visible or offscreen),
        viewport={"width": 1280, "height": 900},
        args=args,
        ignore_default_args=["--enable-automation"],
    )
    if channel and channel != "chromium":
        kwargs["channel"] = channel
    ctx = pw.chromium.launch_persistent_context(**kwargs)
    if offscreen:
        _track_offscreen(ctx)
    return ctx


class BrowserChatProvider(LLMProvider):
    def __init__(self, site: str, channel: str = "chrome", show_browser: bool = False, timeout_s: int = 240) -> None:
        if site not in SITES:
            raise LLMError(f"Không hỗ trợ trang chat '{site}'")
        self.site = SITES[site]
        self.name = f"{site}_browser"
        self.channel = channel or "chrome"
        self.show_browser = show_browser
        self.timeout_s = timeout_s
        # tiếp tục 1 cuộc trò chuyện có sẵn (VD claude.ai/chat/<id>) thay vì mở chat mới; last_url = link chat sau khi trả lời
        self.start_url = ""
        self.last_url = ""
        self.last_attached = 0  # số ảnh đã đính kèm ở lượt gửi gần nhất

    @property
    def supports_images(self) -> bool:
        """Trang chat đính kèm được ảnh: Gemini (menu tải lên riêng), ChatGPT / Claude / Grok (ô đính kèm của khung soạn).
        Trước đây chỉ Gemini → ảnh sản phẩm gửi cho ChatGPT bị bỏ lặng lẽ."""
        return self.site in (SITES["gemini"], SITES["chatgpt"], SITES["claude"], SITES["grok"])

    def generate(self, prompt: str, images: list | None = None, complete=None) -> str:
        """complete(text) -> bool (tuỳ chọn): câu trả lời coi là XONG chỉ khi điều kiện đúng (vd. JSON đọc được, đủ phần).
        Tránh lấy câu trả lời viết dở khi model dừng để suy nghĩ / nút Stop của trang đổi giao diện."""
        site = self.site
        prompt += site.prompt_suffix
        with profile_session(self.name.removesuffix("_browser")) as prof, sync_playwright() as pw:
            try:
                ctx = _launch(pw, self.channel, visible=self.show_browser, offscreen=not site.headless_ok, profile=prof)
            except PWError as exc:
                raise LLMError(f"Không mở được trình duyệt '{self.channel}': {exc}") from exc
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(self.start_url or site.chat_url or site.url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PWError:
                    pass
                if self.start_url:  # nhắn tiếp thread cũ: chờ các tin cũ hiện đủ rồi mới đếm (tránh lấy nhầm trả lời cũ)
                    self._settle_count(page, site.response_selector)
                before = page.locator(site.response_selector).count()
                self._focus_input(page)
                self.last_attached = 0
                if images and self.supports_images:
                    say = lambda msg, level="info": log.warning(msg) if level == "warn" else log.info(msg)  # noqa: E731
                    files = _image_files(images)[:10]
                    if site is SITES["gemini"]:
                        from .gemini_veo import _upload_images

                        self.last_attached = _upload_images(page, files, say)
                    else:  # ChatGPT / Claude / Grok: nạp vào ô đính kèm của khung soạn + xác minh ảnh đã hiện
                        from .uploads import attach_files

                        self.last_attached = attach_files(page, files, say)
                        if not self.last_attached:
                            raise LLMError(f"Không đính kèm được ảnh lên {site.name} (ảnh không hiện trong ô soạn) — "
                                           "chưa gửi prompt. Bật “Hiện cửa sổ Chrome” để xem rồi thử lại, hoặc đổi sang Gemini.")
                        say(f"Đã đính kèm {self.last_attached} ảnh lên {site.name}")
                    self._focus_input(page)
                elif images:
                    log.warning("%s không đính kèm được ảnh — chỉ gửi chữ", site.name)
                page.keyboard.insert_text(prompt)
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
                self._ensure_sent(page, prompt)
                answer = self._wait_answer(page, before, prompt, complete)
                self.last_url = page.url
                return answer
            finally:
                ctx.close()

    def _login_error(self) -> LLMError:
        return LLMError(f"Chưa đăng nhập {self.site.name} (hoặc giao diện {self.site.name} thay đổi). "
                        f"Bấm 'Đăng nhập' để đăng nhập.")

    def _needs_login(self, page) -> bool:
        if any(marker in page.url for marker in self.site.login_markers):
            return True
        try:
            body = page.inner_text("body", timeout=2_000)
        except PWError:
            return False
        return any(marker in body for marker in self.site.login_markers)

    def _focus_input(self, page) -> None:
        """Click vào ô nhập. Trang có thể hiện ô tạm rồi thay bằng ô soạn thảo thật khi tải xong,
        nên click ngắn + thử lại, và chỉ coi là xong khi con trỏ thực sự nằm trong ô nhập."""
        deadline = time.time() + 45
        while time.time() < deadline:
            if any(marker in page.url for marker in self.site.login_markers):
                break
            for selector in self.site.input_selectors:
                loc = page.locator(selector).first
                try:
                    if not (loc.count() and loc.is_visible()):
                        continue
                    loc.click(timeout=3_000)
                    page.wait_for_timeout(400)
                    if page.evaluate(FOCUSED_INPUT_JS):
                        return
                except PWError:
                    continue  # phần tử bị thay thế trong lúc trang khởi tạo — thử lại
            page.wait_for_timeout(700)
        raise self._login_error()

    def _ensure_sent(self, page, prompt: str) -> None:
        """Enter có thể chỉ xuống dòng (giao diện mới) → nếu prompt vẫn nằm trong ô soạn thảo thì bấm nút Gửi."""
        page.wait_for_timeout(1500)
        probe = " ".join(prompt.split())[:40]
        try:
            pending = page.evaluate(PENDING_JS, probe)
        except PWError:
            return
        if not pending:
            return
        button = page.locator(SEND_BUTTONS).first
        try:
            if button.count() and button.is_enabled():
                button.click(timeout=3_000)
        except PWError:
            pass

    def _page_answer(self, page, prompt: str) -> str:
        """Dự phòng khi selector câu trả lời không còn đúng: lấy chữ xuất hiện SAU tin nhắn của mình trên trang."""
        try:
            text = page.evaluate(f"() => ({ANSWER_TEXT_JS})(document.querySelector('main') || document.body, '')")
        except PWError:
            return ""
        flat = " ".join(text.split())
        tail = " ".join(prompt.split())[-40:]
        at = flat.rfind(tail)
        if at < 0:
            return ""
        answer = flat[at + len(tail):]
        for junk in PAGE_JUNK:  # chữ giao diện cố định ở cuối trang
            answer = re.split(junk, answer, flags=re.I)[0]
        return ANSWER_PREFIX.sub("", answer).strip()  # nhãn đọc màn hình "ChatGPT said:" đứng trước câu trả lời

    def _waiting_permission(self, page) -> bool:
        """Claude đang chờ người dùng cho phép dùng công cụ MCP? (chỉ đọc giao diện, không bấm gì)"""
        if self.site.name != "Claude":
            return False
        try:
            return bool(page.evaluate(PERMISSION_JS))
        except PWError:
            return False

    def _hold_for_permission(self, page, state: dict) -> bool:
        """Đang chờ quyền → gia hạn thời gian chờ + nhắc 1 lần trong log tác vụ. True = đang chờ (đừng coi là xong)."""
        if not self._waiting_permission(page):
            return False
        now = time.time()
        if not state.get("since"):
            state["since"] = now
            from ..browser_profiles import _ctx

            msg = (f"{self.site.name} đang chờ bạn cho phép dùng công cụ (MCP) — mở cửa sổ {self.site.name} để bấm cho phép "
                   "(nên chọn “Always allow” cho các công cụ CHỈ ĐỌC; app không tự bấm)")
            log.warning(msg)
            if _ctx().get("log"):
                _ctx()["log"](msg, "warn")
        if now - state["since"] < PERMISSION_WAIT_MAX:
            state["deadline"] = max(state["deadline"], now + 120)
        return True

    def _wait_answer(self, page, before: int, prompt: str, complete=None) -> str:
        site = self.site
        started = time.time()
        hold = {"deadline": started + self.timeout_s}
        ok = (lambda text: True) if complete is None else (lambda text: _safe_complete(complete, text))
        responses = page.locator(site.response_selector)
        echo = prompt.strip()[:60]
        fallback, last_fb, stable_fb = False, "", time.time()
        while responses.count() < before + site.bubbles_per_turn:
            if self._needs_login(page):
                raise self._login_error()
            waiting = self._hold_for_permission(page, hold)
            if time.time() > hold["deadline"]:
                if fallback and last_fb:
                    return last_fb
                sent = self._page_answer(page, prompt) or self._prompt_on_page(page, prompt)
                raise LLMError(f"{site.name} không phản hồi (hết thời gian chờ)" if sent else
                               f"Chưa gửi được tin nhắn tới {site.name} — ô soạn thảo/nút gửi của trang có thể đã đổi")
            if time.time() - started > 25 and not waiting:  # selector không thấy câu trả lời → đọc chữ mới trên trang
                fallback = True
                text = self._page_answer(page, prompt)
                stop = page.locator(site.stop_selector)
                generating = stop.count() > 0 and stop.first.is_visible()
                if text != last_fb:
                    last_fb, stable_fb = text, time.time()
                elif text and not generating and time.time() - stable_fb > 3 and ok(text):
                    return text
                elif complete is not None and text and not generating and time.time() - stable_fb > GIVE_UP_STABLE:
                    return text  # trả lời xong nhưng không đúng yêu cầu (vd. hỏi lại) → để bên gọi thử lại, khỏi chờ hết giờ
            page.wait_for_timeout(700)
        last, stable_since = "", time.time()
        while time.time() < hold["deadline"]:
            try:  # chỉ phần trả lời thật (bỏ khối suy nghĩ, nhãn ẩn đọc màn hình)
                text = responses.last.evaluate(ANSWER_TEXT_JS, site.answer_selector)
            except PWError:  # phần tử bị vẽ lại giữa chừng → đọc lại vòng sau
                text = last
            if text.strip().startswith(echo):  # vẫn là bong bóng câu hỏi của mình
                text = ""
            stop = page.locator(site.stop_selector)
            generating = stop.count() > 0 and stop.first.is_visible()
            if self._hold_for_permission(page, hold):  # chờ người dùng cho phép công cụ → chưa xong
                stable_since = time.time()
                page.wait_for_timeout(700)
                continue
            # trang báo tin đã viết xong (claude.ai: data-is-streaming="false") → nhận ngay khi đủ nội dung, khỏi chờ đứng yên
            try:
                finished = responses.last.get_attribute("data-is-streaming") == "false"
            except PWError:
                finished = False
            if text != last:
                last, stable_since = text, time.time()
            if text.strip() and not generating and finished and time.time() - stable_since > 0.4 and ok(text):
                return text
            if text.strip() and not generating and time.time() - stable_since > 2.5 and ok(text):
                return text
            if complete is not None and text.strip() and not generating and time.time() - stable_since > (
                    8 if finished else GIVE_UP_STABLE):
                return text  # đã xong nhưng không đúng yêu cầu (vd. hỏi lại) → để bên gọi xử lý, khỏi chờ lâu
            page.wait_for_timeout(400)
        if last.strip():
            return last
        raise LLMError(f"{site.name} không trả về nội dung")

    @staticmethod
    def _settle_count(page, selector: str, quiet: float = 1.2, limit: float = 15.0) -> None:
        """Chờ số tin trên trang ngừng tăng (thread cũ đang tải dần các tin) — tối đa `limit` giây."""
        start = time.time()
        last, since = -1, time.time()
        while time.time() - start < limit:
            try:
                n = page.locator(selector).count()
            except PWError:
                n = last
            if n != last:
                last, since = n, time.time()
            elif n > 0 and time.time() - since >= quiet:
                return
            page.wait_for_timeout(250)

    @staticmethod
    def _prompt_on_page(page, prompt: str) -> bool:
        try:
            flat = " ".join(page.evaluate("() => (document.querySelector('main') || document.body).innerText").split())
        except PWError:
            return False
        return " ".join(prompt.split())[-40:] in flat


# Claude (claude.ai) gọi công cụ MCP (VD connector quảng cáo) có thể dừng hỏi quyền "Allow once / Always allow".
# App KHÔNG tự bấm cho phép (có thể là công cụ thay đổi dữ liệu) — chỉ nhận ra để chờ người dùng bấm, không bỏ cuộc.
PERMISSION_JS = r"""() => [...document.querySelectorAll('button')].some(b => b.offsetParent !== null &&
  /^(allow once|always allow|allow for this chat|cho phép( một lần)?|luôn cho phép)$/i.test((b.innerText || '').trim()))"""
PERMISSION_WAIT_MAX = 15 * 60  # chờ người dùng cho phép tối đa 15 phút

GIVE_UP_STABLE = 60  # giây: câu trả lời đứng yên lâu mà vẫn chưa "xong" theo điều kiện → coi như model đã trả lời xong


def _safe_complete(complete, text: str) -> bool:
    try:
        return bool(complete(text))
    except Exception:  # điều kiện lỗi (vd. JSON dở) = chưa xong
        return False


def open_login_window(site: str, channel: str = "chrome", timeout_s: int = 900, url: str = "") -> None:
    """Mở trang ở chế độ có giao diện để người dùng đăng nhập; trả về khi người dùng đóng cửa sổ.
    Profile lấy theo task_context (profile chỉ định) hoặc profile rảnh đầu tiên được gán cho site."""
    target = SITES.get(site)
    if target is None:
        raise LLMError(f"Không hỗ trợ trang chat '{site}'")
    with profile_session(site, "Đăng nhập") as prof, sync_playwright() as pw:
        ctx = _launch(pw, channel, visible=True, profile=prof, always_visible=True)  # đăng nhập: luôn hiện
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url or target.url, wait_until="domcontentloaded")
            try:
                page.wait_for_event("close", timeout=timeout_s * 1000)
            except PWError:
                pass
        finally:
            try:
                ctx.close()
            except PWError:
                pass
