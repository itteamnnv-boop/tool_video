"""Qwen Chat (chat.qwen.ai) · chế độ Create Video — tạo video bằng trình duyệt đã đăng nhập Qwen (profile gán "Qwen").

Cấu trúc trang (11/2026): nút [aria-label='Select Mode'] mở menu [role=menuitem] (Create Image / Create Video / …); sau khi
chọn, ô soạn có chip "Create Video ×" + các ô thả xuống .qwen-chat-v2-dropdown-menu-select (model, tỉ lệ "16:9" …);
ô soạn textarea.message-input-textarea; ô tải file input#filesUpload. Giao diện đổi thì sửa hằng số bên dưới.
"""
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import _launch
from .grok_imagine import FETCH_BLOB_JS, VIDEOS_JS, _download

SITE = "qwen"
URL = "https://chat.qwen.ai/"
PROMPT_BOX = "textarea.message-input-textarea, textarea[placeholder]"
MODE_BUTTON = "[aria-label='Select Mode'], .mode-select-open"
MENU_ITEM = "[role='menuitem'], [role='menuitemradio'], [role='option']"
DROPDOWN = ".qwen-chat-v2-dropdown-menu-select"
SEND_BTN = "button[aria-label*='Send' i], #send-message-button"
LOGIN_BTN = "button:text-is('Log in'), button:text-is('Sign in')"
LOGIN_ERROR = "Chưa đăng nhập Qwen — vào Profile trình duyệt, gán “Qwen” cho profile rồi bấm Đăng nhập (chat.qwen.ai)"
RATIO = re.compile(r"^\s*\d{1,2}:\d{1,2}\s*$")
SECONDS = re.compile(r"^\s*\d{1,2}\s*s(ec)?\s*$", re.I)
ERROR_WORDS = ("limit", "quota", "exceeded", "failed", "try again", "violat", "sensitive", "not supported",
               "unable to generate", "couldn't generate", "something went wrong", "insufficient")
ERROR_JS = """(words) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const nodes = [...document.querySelectorAll("[role='alert'], [class*='toast' i], [class*='notification' i], "
    + "[class*='error' i], [class*='message-tip' i]")];
  const turns = document.querySelectorAll("[class*='response-message' i], [class*='chat-response' i], [class*='assistant' i]");
  if (turns.length) nodes.push(turns[turns.length - 1]);
  for (const n of nodes) {
    if (!vis(n) || n.querySelector('video')) continue;
    const t = (n.innerText || '').trim(), low = t.toLowerCase();
    if (t && t.length < 500 && words.some(w => low.includes(w))) return t;
  }
  return '';
}"""
MODE_ON_JS = """() => {
  const box = document.querySelector('textarea.message-input-textarea, textarea[placeholder]');
  const area = box ? (box.closest('.message-input-container') || box.parentElement.parentElement) : document.body;
  const ph = (box && box.getAttribute('placeholder') || '').toLowerCase();
  return ph.includes('video') || [...area.querySelectorAll('*')].some(e => e.children.length === 0
    && /^\\s*create video\\s*$/i.test(e.textContent || ''));
}"""
MIN_VIEW_WIDTH = 160
EXPECT_S = 300


def generate_video(prompt: str, out_path: Path, *, aspect: str = "16:9", duration: str = "5s", resolution: str = "",
                   channel: str = "chrome", show_browser: bool = False, images: list[Path] | None = None, log=print,
                   check_cancel=lambda: None, on_progress=None, timeout_s: int = 1500) -> None:
    with profile_session(SITE) as prof, sync_playwright() as pw:
        try:
            ctx = _launch(pw, channel, visible=show_browser, offscreen=not show_browser, profile=prof)
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWError:
                pass
            box = page.locator(PROMPT_BOX).first
            try:
                box.wait_for(state="visible", timeout=30_000)
            except PWError as exc:
                raise LLMError("Không thấy ô soạn của Qwen (giao diện có thể đã đổi) — bật “Hiện cửa sổ Chrome” để xem") \
                    from exc
            page.wait_for_timeout(1500)
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)
            _video_mode(page)
            if aspect and not _pick(page, RATIO, aspect):
                log(f"Không đặt được tỉ lệ {aspect} trên Qwen — dùng mặc định", "warn")
            secs = str(duration or "").rstrip("s")
            if secs and _has(page, SECONDS) and not _pick(page, SECONDS, secs, suffix=True):
                log(f"Không đặt được thời lượng {duration} trên Qwen — dùng mặc định", "warn")
            if images:
                _attach(page, images, log, check_cancel)

            before = {v["src"] for v in page.evaluate(VIDEOS_JS)}
            box = page.locator(PROMPT_BOX).first
            box.click()
            box.fill(prompt)
            page.wait_for_timeout(500)
            _send(page, box)
            page.wait_for_timeout(3000)
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)
            log("Đã gửi prompt — Qwen đang tạo video…")
            src = _wait_for_video(page, before, timeout_s, check_cancel, on_progress)
            data = _fetch(ctx, page, src)
            if len(data) < 20_000:
                raise LLMError("File video tải về từ Qwen không hợp lệ")
            Path(out_path).write_bytes(data)
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def _needs_login(page) -> bool:
    try:
        return page.locator(LOGIN_BTN).first.is_visible() or page.get_by_text("Log in", exact=True).first.is_visible()
    except PWError:
        return False


def _disabled(el) -> bool:
    try:
        return el.get_attribute("aria-disabled") == "true" or "disabled" in (el.get_attribute("class") or "")
    except PWError:
        return False


def _mode_on(page) -> bool:
    try:
        return bool(page.evaluate(MODE_ON_JS))
    except PWError:
        return False


def _video_mode(page) -> None:
    """Select Mode → Create Video; kiểm tra chip "Create Video" đã hiện trong ô soạn."""
    if _mode_on(page):
        return
    try:
        page.locator(MODE_BUTTON).first.click(timeout=5000)
        item = page.locator(MENU_ITEM).filter(has_text=re.compile(r"^\s*Create Video", re.I)).first
        item.wait_for(state="visible", timeout=5000)
        if _disabled(item):  # mục xám: khách chưa đăng nhập / tài khoản chưa được dùng → báo ngay, không bấm chờ
            page.keyboard.press("Escape")
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)
            raise LLMError("“Create Video” của Qwen đang bị khoá (mục màu xám) — profile này chưa đăng nhập Qwen, hoặc "
                           "tài khoản chưa được dùng / đã hết lượt tạo video. Mở Profile trình duyệt → Qwen → Đăng nhập "
                           "để kiểm tra")
        item.click(timeout=5000)
    except PWError as exc:
        raise LLMError("Không tìm thấy chế độ “Create Video” của Qwen (tài khoản chưa được dùng, hoặc giao diện đã đổi) "
                       "— bật “Hiện cửa sổ Chrome” để xem") from exc
    for _ in range(10):
        page.wait_for_timeout(500)
        if _mode_on(page):
            return
    raise LLMError("Đã chọn “Create Video” nhưng Qwen không chuyển sang chế độ tạo video (cần đăng nhập / tài khoản chưa "
                   "được dùng tạo video)")


def _dropdowns(page, pattern) -> list:
    out = []
    boxes = page.locator(DROPDOWN)
    for i in range(boxes.count()):
        d = boxes.nth(i)
        try:
            if d.is_visible() and pattern.match((d.inner_text() or "").strip()):
                out.append(d)
        except PWError:
            continue
    return out


def _has(page, pattern) -> bool:
    return bool(_dropdowns(page, pattern))


def _pick(page, pattern, value: str, suffix: bool = False) -> bool:
    """Ô thả xuống có nhãn khớp `pattern` (vd "16:9", "5s") → chọn mục `value`."""
    found = _dropdowns(page, pattern)
    if not found:
        return False
    want = re.compile(rf"^\s*{re.escape(value)}{r'\s*s(ec)?' if suffix else ''}(?![\d:])", re.I)
    d = found[0]
    try:
        if want.match((d.inner_text() or "").strip()):
            return True
        d.click(timeout=3000)
        items = page.locator(MENU_ITEM)
        items.first.wait_for(state="visible", timeout=4000)
        for i in range(items.count()):
            it = items.nth(i)
            if it.is_visible() and want.match((it.inner_text() or "").strip()):
                it.click()
                page.wait_for_timeout(500)
                return want.match((d.inner_text() or "").strip()) is not None
        page.keyboard.press("Escape")
    except PWError:
        pass
    return False


UPLOAD_INPUT = "input#filesUpload"
# ảnh / thẻ file vừa đính kèm trong khung soạn (Qwen vẽ thẻ file, ảnh từ CDN — không chỉ img blob:)
ATTACHED_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 8 && r.height > 8; };
  return [...document.querySelectorAll("img, video, [class*='file' i], [class*='image-item' i], [class*='upload' i], "
    + "[class*='attach' i], [style*='background-image']")].filter(e => e.tagName !== 'INPUT' && vis(e)).length;
}"""
# khung soạn lúc đính kèm thất bại → đưa vào thông báo lỗi để sửa đúng chỗ
COMPOSER_JS = """() => {
  const box = document.querySelector('textarea.message-input-textarea, textarea[placeholder]');
  const area = box ? (box.closest('.message-input-wrapper') || box.closest('.message-input-container') || box.parentElement) : null;
  return area ? (area.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160) : '';
}"""
UPLOAD_URL = re.compile(r"upload|aliyuncs|\.oss|oss-|/files?(/|\?|$)|/sts\b", re.I)
UPLOAD_MENU = re.compile(r"^\s*Upload", re.I)


def _attached(page) -> int:
    try:
        return int(page.evaluate(ATTACHED_JS) or 0)
    except PWError:
        return 0


def _attach(page, images: list[Path], log, check_cancel) -> None:
    from .uploads import attach_files, wait_uploads

    log(f"Đang tải {len(images)} ảnh lên Qwen…")
    files = [str(p) for p in images]
    sent = []  # yêu cầu tải lên máy chủ Qwen (dấu hiệu chắc chắn nhất là ảnh đã được nhận)

    def on_request(req):
        if req.method in ("POST", "PUT") and UPLOAD_URL.search(req.url):
            sent.append(req.url)

    page.on("request", on_request)
    try:
        ways = []
        if page.locator(UPLOAD_INPUT).count():
            ways.append(("ô tải file", lambda: page.locator(UPLOAD_INPUT).first.set_input_files(files, timeout=60_000)))
        ways.append(("menu ＋ → Upload attachment", lambda: _upload_via_menu(page, files)))
        for name, way in ways:
            before = _attached(page)
            try:
                way()
            except PWError as exc:
                log(f"Qwen: đính kèm qua {name} không được ({str(exc).splitlines()[0][:80]})", "warn")
                continue
            deadline = time.time() + 25
            while time.time() < deadline:
                check_cancel()
                if sent or _attached(page) > before:
                    break
                err = page.evaluate(ERROR_JS, list(ERROR_WORDS))
                if err:
                    raise LLMError(f"Qwen không nhận ảnh: {' '.join(err.split())[:200]}")
                page.wait_for_timeout(700)
            if sent or _attached(page) > before:
                wait_uploads(page, log, check_cancel=check_cancel)
                page.wait_for_timeout(1500)
                log(f"Đã đính kèm {len(images)} ảnh lên Qwen ({name})")
                break
        else:
            if attach_files(page, images, log, check_cancel=check_cancel):
                pass
            else:
                try:
                    seen = page.evaluate(COMPOSER_JS)
                except PWError:
                    seen = ""
                raise LLMError("Không đính kèm được ảnh lên Qwen — chưa gửi prompt (Qwen không tải ảnh lên, không hiện "
                               f"ảnh). Ô soạn đang hiện: “{seen or 'trống'}”. Bật “Hiện cửa sổ Chrome” để xem rồi thử lại")
    finally:
        page.remove_listener("request", on_request)
    if not _mode_on(page):  # tải ảnh có thể làm Qwen thoát chế độ video → chọn lại
        _video_mode(page)


def _upload_via_menu(page, files: list) -> None:
    """＋ (Select Mode) → "Upload attachment" → hộp chọn file."""
    with page.expect_file_chooser(timeout=8000) as chooser:
        page.locator(MODE_BUTTON).first.click(timeout=4000)
        item = page.locator(MENU_ITEM).filter(has_text=UPLOAD_MENU).first
        item.wait_for(state="visible", timeout=4000)
        item.click(timeout=4000)
    chooser.value.set_files(files)


def _send(page, box) -> None:
    box.press("Enter")
    page.wait_for_timeout(1500)
    try:
        if (box.input_value() or "").strip():  # chưa gửi (Enter bị chặn) → bấm nút gửi
            btn = page.locator(SEND_BTN).first
            if btn.count() and btn.is_enabled():
                btn.click(timeout=3000)
    except PWError:
        pass


def _wait_for_video(page, before: set, timeout_s: int, check_cancel, on_progress) -> str:
    t0 = time.time()
    stable, since = "", 0.0
    while time.time() - t0 < timeout_s:
        check_cancel()
        fresh = [v for v in page.evaluate(VIDEOS_JS)
                 if v["src"] not in before and v.get("w", 0) >= MIN_VIEW_WIDTH and v.get("dur", 0) >= 1]
        if fresh:
            src = fresh[-1]["src"]
            if src != stable:
                stable, since = src, time.time()
            elif time.time() - since > 5:
                return src
        else:
            err = page.evaluate(ERROR_JS, list(ERROR_WORDS))
            if err:
                raise LLMError(f"Qwen báo lỗi: {' '.join(err.split())[:300]}")
        if on_progress:
            on_progress(min(95, int(100 * (time.time() - t0) / EXPECT_S)))
        page.wait_for_timeout(2500)
    raise LLMError("Qwen chưa tạo xong video (hết thời gian chờ)")


def _fetch(ctx, page, src: str) -> bytes:
    import base64

    if src.startswith("blob:"):
        return base64.b64decode(page.evaluate(FETCH_BLOB_JS, src))
    try:
        resp = ctx.request.get(src, headers={"Referer": URL}, timeout=180_000)
        if resp.ok:
            return resp.body()
    except PWError:
        pass
    return _download(ctx, page, src)
