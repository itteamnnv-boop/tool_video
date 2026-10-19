"""Dola (dola.com) · AI Creation → Video (Seedance): tạo video từ prompt bằng trình duyệt đã đăng nhập Dola.

Selector lấy từ trang /chat/create-image (10/2026): tab [data-testid=creation-skill-switch-tab-video], nút
thời lượng [data-testid=chat_input_action_video-duration] (5s/10s), tỉ lệ [data-testid=chat_input_action_video-ratio]
(menu [role=menuitem]), ô tải ảnh input[type=file][multiple]. Giao diện đổi thì sửa hằng số bên dưới.
"""
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import SITES, _launch
from .grok_imagine import PREVIEW_IMG, VIDEOS_JS, _download, _wait_for_video, type_multiline

CREATION_URL = "https://www.dola.com/chat/create-image"
VIDEO_TAB = "[data-testid='creation-skill-switch-tab-video']"
DURATION_BTN = "[data-testid='chat_input_action_video-duration']"
RATIO_BTN = "[data-testid='chat_input_action_video-ratio']"
MENU_ITEM = "[role='menuitem'], [role='menuitemradio'], [role='option']"
PROMPT_BOX = "[data-testid='chat_input_input'], div[contenteditable='true']"
SEND_BTN = "[data-testid='chat_input_send_button']"
UPLOAD_INPUT = "input[type='file'][multiple]:not([capture]), input[type='file']:not([capture])"
DISMISS = ("[data-testid='cookie_banner_notice']",)
LOGIN_ERROR = "Chưa đăng nhập Dola — chọn Provider 'Dola Browser' và bấm 'Đăng nhập'."


def generate_video(prompt: str, out_path: Path, *, aspect: str = "9:16", duration: str = "10s",
                   resolution: str = "", channel: str = "chrome", show_browser: bool = False,
                   images: list[Path] | None = None, log=print, check_cancel=lambda: None, on_progress=None,
                   timeout_s: int = 900) -> None:
    with profile_session("dola") as prof, sync_playwright() as pw:
        try:
            ctx = _launch(pw, channel, visible=show_browser, offscreen=not show_browser, profile=prof)
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(CREATION_URL, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWError:
                pass
            page.wait_for_timeout(2000)
            for selector in DISMISS:
                try:
                    page.locator(selector).first.click(timeout=1500)
                except PWError:
                    pass
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)

            tab = page.locator(VIDEO_TAB).first
            try:
                tab.click(timeout=10_000)
            except PWError as exc:
                raise LLMError("Không tìm thấy tab Video trên Dola AI Creation (giao diện có thể đã đổi)") from exc
            page.wait_for_timeout(1200)
            if not _choose(page, RATIO_BTN, aspect):
                log(f"Không đặt được tỉ lệ {aspect} trên Dola — dùng mặc định", "warn")
            if duration and not _choose(page, DURATION_BTN, duration):
                log(f"Không đặt được thời lượng {duration} trên Dola — dùng mặc định", "warn")
            if images:
                _attach_images(page, images, log)

            before = {v["src"] for v in page.evaluate(VIDEOS_JS)}
            box = page.locator(PROMPT_BOX).first
            box.click()
            type_multiline(page, prompt)
            page.wait_for_timeout(400)
            send = page.locator(SEND_BTN).first
            if send.count() and send.is_enabled():
                send.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(2500)
            if _needs_login(page):
                raise LLMError(LOGIN_ERROR)
            log("Đã gửi prompt — Dola (Seedance) đang tạo video…")
            src = _wait_for_video(page, before, timeout_s, check_cancel, on_progress)
            data = _download(ctx, page, src)
            if len(data) < 20_000:
                raise LLMError("File video tải về từ Dola không hợp lệ")
            Path(out_path).write_bytes(data)
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def _needs_login(page) -> bool:
    try:
        body = page.inner_text("body", timeout=3_000)
    except PWError:
        return False
    return any(marker in body for marker in SITES["dola"].login_markers)


def _choose(page, button: str, value: str) -> bool:
    btn = page.locator(button).first
    try:
        if not btn.count():
            return False
        if (btn.inner_text() or "").strip() == value:
            return True
        btn.click()
        items = page.locator(MENU_ITEM)
        items.first.wait_for(state="visible", timeout=4_000)
        # mục có thể kèm mô tả, vd "9:16 (mobile wallpaper, portrait)" → so phần đầu, không theo sau bởi chữ số
        pattern = re.compile(rf"^\s*{re.escape(value)}(?!\d)")
        for i in range(items.count()):
            item = items.nth(i)
            if item.is_visible() and pattern.match(item.inner_text() or ""):
                item.click()
                page.wait_for_timeout(500)
                return True
        page.keyboard.press("Escape")
    except PWError:
        pass
    return False


def _attach_images(page, images: list[Path], log) -> None:
    file_input = page.locator(UPLOAD_INPUT).first
    if not file_input.count():
        log("Không tìm thấy ô tải ảnh trên Dola — bỏ qua ảnh tham chiếu", "warn")
        return
    before = page.locator(PREVIEW_IMG).count()
    if file_input.get_attribute("multiple") is not None:
        file_input.set_input_files([str(p) for p in images])
    else:  # ô chỉ nhận 1 file → tải lần lượt
        for path in images:
            file_input.set_input_files(str(path))
            page.wait_for_timeout(1500)
    log(f"Đang tải {len(images)} ảnh tham chiếu lên Dola…")
    deadline = time.time() + 60
    while time.time() < deadline and page.locator(PREVIEW_IMG).count() < before + len(images):
        page.wait_for_timeout(700)
    page.wait_for_timeout(1000)
    from .uploads import attach_files, wait_uploads

    if page.locator(PREVIEW_IMG).count() <= before:  # không ảnh nào vào ô soạn → thử cách khác, không được thì dừng
        log("Chưa thấy ảnh nào trong ô soạn Dola — thử đính kèm lại", "warn")
        if not attach_files(page, images, log):
            raise LLMError("Không đính kèm được ảnh lên Dola (ảnh không hiện trong ô soạn) — chưa gửi prompt. "
                           "Bật “Hiện Chrome” để xem rồi thử lại.")
    wait_uploads(page, log)  # chờ tải lên máy chủ xong rồi mới gửi
