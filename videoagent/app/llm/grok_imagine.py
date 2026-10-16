"""Grok Imagine (grok.com/imagine): tạo video AI từ prompt bằng trình duyệt đã đăng nhập Grok.

Selector lấy từ giao diện Grok Imagine (10/2026): nút radio "Video", các nút "Aspect Ratio", "Video duration",
"Video resolution" mở menu [role=menuitemradio]; ô nhập là div.ProseMirror. Giao diện đổi thì sửa hằng số bên dưới.
"""
import base64
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import SITES, _launch

IMAGINE_URL = "https://grok.com/imagine"
PROMPT_BOX = "div.ProseMirror[contenteditable='true']"
VIDEO_MODE = "button[role='radio'][aria-label='Video']"
UPLOAD_INPUT_MULTI = "input[type='file'][multiple]"
UPLOAD_INPUT = "input[type='file']"
PREVIEW_IMG = "img[src^='blob:'], img[src^='data:image']"
OPTION_BUTTONS = {"aspect": "Aspect Ratio", "duration": "Video duration", "resolution": "Video resolution"}
VIDEOS_JS = """() => [...document.querySelectorAll('video')]
  .map(v => ({src: v.currentSrc || v.src || '', dur: isFinite(v.duration) ? v.duration : 0}))
  .filter(v => v.src)"""
PROGRESS_JS = """() => {
  const m = (document.querySelector('main') || document.body).innerText.match(/(\\d{1,3})\\s?%/);
  return m ? parseInt(m[1], 10) : null;
}"""
FETCH_BLOB_JS = """async src => {
  const bytes = new Uint8Array(await (await fetch(src)).arrayBuffer());
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
}"""
LOGIN_ERROR = "Chưa đăng nhập Grok hoặc giao diện Grok Imagine đã thay đổi — chọn Grok Browser và bấm 'Đăng nhập'."


def generate_video(prompt: str, out_path: Path, *, aspect: str = "9:16", duration: str = "15s",
                   resolution: str = "720p", channel: str = "chrome", show_browser: bool = False,
                   images: list[Path] | None = None, log=print, check_cancel=lambda: None, on_progress=None,
                   timeout_s: int = 900) -> None:
    with profile_session("grok") as prof, sync_playwright() as pw:
        try:
            ctx = _launch(pw, channel, visible=show_browser, offscreen=not show_browser, profile=prof)
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(IMAGINE_URL, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWError:
                pass
            box = page.locator(PROMPT_BOX).first
            try:
                box.wait_for(state="visible", timeout=20_000)
            except PWError as exc:
                raise LLMError(LOGIN_ERROR) from exc
            if any(marker in page.url for marker in SITES["grok"].login_markers):
                raise LLMError(LOGIN_ERROR)

            if images:
                _attach_images(page, images, log)
            _select_video_mode(page)  # chọn sau khi tải ảnh: tải ảnh có thể làm Grok đổi chế độ
            for key, value in (("aspect", aspect), ("duration", duration), ("resolution", resolution)):
                if value and not _choose_option(page, OPTION_BUTTONS[key], value):
                    log(f"Không đặt được {OPTION_BUTTONS[key]} = {value} trên Grok — dùng mặc định của Grok", "warn")

            before = {v["src"] for v in page.evaluate(VIDEOS_JS)}
            box.click()
            type_multiline(page, prompt)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            log("Đã gửi prompt — Grok Imagine đang tạo video…")
            src = _wait_for_video(page, before, timeout_s, check_cancel, on_progress)
            data = _download(ctx, page, src)
            if len(data) < 20_000:
                raise LLMError("File video tải về từ Grok không hợp lệ")
            Path(out_path).write_bytes(data)
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def type_multiline(page, text: str) -> None:
    """Gõ prompt nhiều dòng: Shift+Enter để xuống dòng trong ô soạn (Enter thường sẽ gửi đi)."""
    for i, line in enumerate(text.split("\n")):
        if i:
            page.keyboard.press("Shift+Enter")
        if line:
            page.keyboard.insert_text(line)


def _attach_images(page, images: list[Path], log) -> None:
    """Tải ảnh tham chiếu lên ô đính kèm (input nhận nhiều ảnh), chờ ảnh hiện trong ô soạn prompt."""
    file_input = page.locator(UPLOAD_INPUT_MULTI).first
    if not file_input.count():
        file_input = page.locator(UPLOAD_INPUT).first
        if not file_input.count():
            raise LLMError("Không tìm thấy ô tải ảnh trên Grok Imagine")
        if len(images) > 1:
            log(f"Grok chỉ nhận 1 ảnh ở ô này — chỉ gửi ảnh đầu tiên ({Path(images[0]).name})", "warn")
            images = images[:1]
    before = page.locator(PREVIEW_IMG).count()
    file_input.set_input_files([str(p) for p in images])
    log(f"Đang tải {len(images)} ảnh tham chiếu lên Grok…")
    deadline = time.time() + 60
    while time.time() < deadline:
        if page.locator(PREVIEW_IMG).count() >= before + len(images):
            page.wait_for_timeout(1500)  # chờ upload xong hẳn
            return
        page.wait_for_timeout(700)
    log("Không thấy ảnh xem trước sau khi tải lên — vẫn tiếp tục", "warn")


def _select_video_mode(page) -> None:
    btn = page.locator(VIDEO_MODE).first
    if not btn.count():
        raise LLMError("Không tìm thấy chế độ Video trên Grok Imagine (tài khoản có thể chưa được dùng video)")
    if btn.get_attribute("aria-checked") != "true":
        btn.click()
        page.wait_for_timeout(800)


def _current_value(btn) -> str:
    return btn.inner_text().strip().split("\n")[0].strip()


def _choose_option(page, label: str, value: str) -> bool:
    btn = page.locator(f"button[aria-label='{label}']").first
    try:
        if not btn.count():
            return False
        if _current_value(btn) == value:
            return True
        btn.click()
        items = page.locator("[role='menuitemradio']")
        items.first.wait_for(state="visible", timeout=4_000)
        # Mỗi mục gồm giá trị + mô tả ("9:16" + "Vertical"); textContent dính liền "9:16Vertical"
        # nên so theo dòng đầu của innerText, hoặc tiền tố không theo sau bởi chữ số (tránh 1:1 ~ 1:16).
        pattern = re.compile(rf"^\s*{re.escape(value)}(?!\d)")
        for i in range(items.count()):
            item = items.nth(i)
            if item.inner_text().strip().split("\n")[0].strip() == value or pattern.match(item.text_content() or ""):
                item.click()
                page.wait_for_timeout(400)
                return _current_value(btn) == value
        page.keyboard.press("Escape")
        return False
    except PWError:
        return False


def _wait_for_video(page, before: set, timeout_s: int, check_cancel, on_progress) -> str:
    """Chờ video mới xuất hiện và ổn định (không còn % tiến trình) rồi trả về src."""
    deadline = time.time() + timeout_s
    last_pct, stable_src, stable_since = None, "", 0.0
    while time.time() < deadline:
        check_cancel()
        pct = page.evaluate(PROGRESS_JS)
        if pct is not None and pct != last_pct and on_progress:
            on_progress(min(pct, 99))
        last_pct = pct
        fresh = [v for v in page.evaluate(VIDEOS_JS) if v["src"] not in before and v["dur"] >= 1]
        if fresh:
            src = fresh[-1]["src"]
            if src != stable_src:
                stable_src, stable_since = src, time.time()
            elif (pct is None and time.time() - stable_since > 4) or time.time() - stable_since > 30:
                return src
        page.wait_for_timeout(2500)
    raise LLMError("Grok Imagine chưa tạo xong video (hết thời gian chờ)")


def _download(ctx, page, src: str) -> bytes:
    if src.startswith("blob:"):
        return base64.b64decode(page.evaluate(FETCH_BLOB_JS, src))
    resp = ctx.request.get(src, headers={"Referer": "https://grok.com/"}, timeout=180_000)
    if not resp.ok:
        raise LLMError(f"Không tải được video từ Grok (HTTP {resp.status})")
    return resp.body()
