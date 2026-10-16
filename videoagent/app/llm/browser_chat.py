"""Browser Mode: điều khiển trang chat AI (Gemini, Grok) bằng Chrome/Edge đã đăng nhập — không cần API key.

Mỗi model dùng các profile trình duyệt được gán trong "Profile trình duyệt" (app/browser_profiles.py) — mỗi profile là
một bộ tài khoản riêng; đăng nhập từng model trong từng profile một lần. Selector của các trang có thể đổi theo thời gian — chỉnh trong SITES bên dưới.
"""
import time
from dataclasses import dataclass

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from ..browser_profiles import DEFAULT_ID, profile_dir, profile_session
from .base import LLMError, LLMProvider


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


SITES = {
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
}

FOCUSED_INPUT_JS = """() => {
  const el = document.activeElement;
  return !!el && el.isConnected && (el.isContentEditable || el.tagName === 'TEXTAREA');
}"""
OFFSCREEN_ARG = "--window-position=-32000,-32000"


def _launch(pw, channel: str, *, visible: bool, offscreen: bool = False, profile: dict | None = None):
    """Mở Chrome với thư mục profile đang giữ (profile_session). Profile có thể đặt trình duyệt riêng (Chrome/Edge)."""
    folder = profile["dir"] if profile else profile_dir(DEFAULT_ID)
    folder.mkdir(parents=True, exist_ok=True)
    channel = (profile or {}).get("channel") or channel
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
    return pw.chromium.launch_persistent_context(**kwargs)


class BrowserChatProvider(LLMProvider):
    def __init__(self, site: str, channel: str = "chrome", show_browser: bool = False, timeout_s: int = 240) -> None:
        if site not in SITES:
            raise LLMError(f"Không hỗ trợ trang chat '{site}'")
        self.site = SITES[site]
        self.name = f"{site}_browser"
        self.channel = channel or "chrome"
        self.show_browser = show_browser
        self.timeout_s = timeout_s

    def generate(self, prompt: str, images: list | None = None) -> str:  # chế độ trình duyệt không gửi ảnh
        site = self.site
        with profile_session(self.name.removesuffix("_browser")) as prof, sync_playwright() as pw:
            try:
                ctx = _launch(pw, self.channel, visible=self.show_browser, offscreen=not site.headless_ok, profile=prof)
            except PWError as exc:
                raise LLMError(f"Không mở được trình duyệt '{self.channel}': {exc}") from exc
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(site.url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PWError:
                    pass
                before = page.locator(site.response_selector).count()
                self._focus_input(page)
                page.keyboard.insert_text(prompt)
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
                return self._wait_answer(page, before, prompt)
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

    def _wait_answer(self, page, before: int, prompt: str) -> str:
        site = self.site
        deadline = time.time() + self.timeout_s
        responses = page.locator(site.response_selector)
        echo = prompt.strip()[:60]
        while responses.count() < before + site.bubbles_per_turn:
            if self._needs_login(page):
                raise self._login_error()
            if time.time() > deadline:
                raise LLMError(f"{site.name} không phản hồi (hết thời gian chờ)")
            page.wait_for_timeout(700)
        last, stable_since = "", time.time()
        while time.time() < deadline:
            text = responses.last.inner_text()
            if text.strip().startswith(echo):  # vẫn là bong bóng câu hỏi của mình
                text = ""
            stop = page.locator(site.stop_selector)
            generating = stop.count() > 0 and stop.first.is_visible()
            if text != last:
                last, stable_since = text, time.time()
            elif text.strip() and not generating and time.time() - stable_since > 2.5:
                return text
            page.wait_for_timeout(700)
        if last.strip():
            return last
        raise LLMError(f"{site.name} không trả về nội dung")


def open_login_window(site: str, channel: str = "chrome", timeout_s: int = 900, url: str = "") -> None:
    """Mở trang ở chế độ có giao diện để người dùng đăng nhập; trả về khi người dùng đóng cửa sổ.
    Profile lấy theo task_context (profile chỉ định) hoặc profile rảnh đầu tiên được gán cho site."""
    target = SITES.get(site)
    if target is None:
        raise LLMError(f"Không hỗ trợ trang chat '{site}'")
    with profile_session(site, "Đăng nhập") as prof, sync_playwright() as pw:
        ctx = _launch(pw, channel, visible=True, profile=prof)
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
