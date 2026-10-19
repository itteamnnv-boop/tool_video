"""Chờ trang chat (ChatGPT, Gemini, Grok, Dola, Muse) tải xong file đính kèm trước khi gửi prompt.

Ảnh xem trước hiện ngay khi chọn file (ảnh trong máy), còn việc tải lên máy chủ chạy sau — trong lúc đó trang hiện
vòng xoay / thanh tiến trình trên ảnh và thường khoá nút Gửi. Gửi sớm thì tin nhắn bị bỏ qua hoặc mất ảnh.
"""
import re
import time

from playwright.sync_api import Error as PWError

# dấu hiệu "đang tải lên" quanh ảnh xem trước / trong ô soạn tin
UPLOADING = ", ".join((
    "[role='progressbar']", "progress", "[aria-busy='true']", "circle[stroke-dasharray]", ".animate-spin",
    "mat-progress-spinner", "mat-progress-bar", "mat-spinner", "[class*='spinner' i]", "[class*='uploading' i]",
    "[aria-label*='Uploading' i]", "[aria-label*='Đang tải' i]", "[aria-label*='Loading' i]",
))
PREVIEWS = "img[src^='blob:'], img[src^='data:image'], video[src^='blob:']"
COMPOSER = "#prompt-textarea, [contenteditable='true'], textarea"
BUSY_JS = """([busySel, previewSel, composerSel]) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const up = (e, n) => { let r = e; for (let i = 0; i < n && r.parentElement; i++) r = r.parentElement; return r; };
  const roots = new Set();
  for (const p of document.querySelectorAll(previewSel)) if (vis(p)) roots.add(p.closest('form') || up(p, 5));
  for (const c of document.querySelectorAll(composerSel)) if (vis(c)) roots.add(c.closest('form') || up(c, 6));
  return [...roots].some(r => [...r.querySelectorAll(busySel)].some(vis));
}"""


def uploading(page) -> bool:
    try:
        return bool(page.evaluate(BUSY_JS, [UPLOADING, PREVIEWS, COMPOSER]))
    except PWError:
        return False


def wait_uploads(page, log, *, timeout_s: int = 180, settle_ms: int = 1500, check_cancel=None) -> bool:
    """Chờ hết dấu hiệu đang tải lên (ổn định settle_ms). Quá giờ → cảnh báo rồi vẫn đi tiếp (không báo lỗi)."""
    start, calm, warned = time.time(), None, False
    while time.time() - start < timeout_s:
        if check_cancel:
            check_cancel()
        if uploading(page):
            calm = None
            if not warned and time.time() - start > 2:
                log("Đang chờ tải xong file đính kèm…")
                warned = True
        else:
            calm = calm or time.time()
            if (time.time() - calm) * 1000 >= settle_ms:
                if warned:
                    log(f"Đã tải xong file đính kèm ({time.time() - start:.0f} giây)")
                return True
        page.wait_for_timeout(500)
    log(f"File đính kèm tải quá {timeout_s // 60} phút — vẫn thử gửi", "warn")
    return False


ATTACH_COUNT_JS = """(composerSel) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const up = (e, n) => { let r = e; for (let i = 0; i < n && r.parentElement; i++) r = r.parentElement; return r; };
  const c = [...document.querySelectorAll(composerSel)].find(vis);
  if (!c) return 0;
  const root = c.closest('form') || up(c, 6);
  const imgs = [...root.querySelectorAll('img, video')].filter(vis).length;
  const tiles = [...root.querySelectorAll("[data-testid*='attachment' i], [data-testid*='file-tile' i]")].filter(vis).length;
  return Math.max(imgs, tiles);
}"""
FILE_INPUTS = "input[type='file']:not([capture])"
PLUS_BUTTONS = ("button[data-testid='composer-plus-btn'], button[aria-label*='Add photos' i], "
                "button[aria-label*='Attach' i], button[aria-label*='Upload' i], button[aria-label*='Thêm' i], "
                "button[aria-label*='Đính kèm' i]")
UPLOAD_MENU = re.compile(r"(photo|file|upload|image|ảnh|tệp|tải lên)", re.I)


def attachment_count(page) -> int:
    """Số ảnh / tệp đính kèm đang hiện trong khung soạn tin (ô nhập + vùng xem trước của nó)."""
    try:
        return int(page.evaluate(ATTACH_COUNT_JS, COMPOSER) or 0)
    except PWError:
        return 0


def attach_files(page, files: list, log, *, check_cancel=None, per_try_s: int = 20) -> int:
    """Đính kèm file vào khung soạn và XÁC MINH ảnh đã hiện ở đó (trả về số ảnh mới hiện).
    Thử lần lượt các ô <input type=file> (bỏ ô chụp camera, ưu tiên ô nhận nhiều file); không ô nào làm ảnh hiện
    → bấm nút ＋ / Đính kèm của khung soạn và nạp file qua hộp chọn file. Có ảnh rồi thì chờ tải lên xong."""
    files = [str(f) for f in files]
    want, base = len(files), attachment_count(page)

    def shown_after(seconds: float) -> int:
        end = time.time() + seconds
        while time.time() < end:
            if check_cancel:
                check_cancel()
            if attachment_count(page) - base >= want:
                break
            page.wait_for_timeout(600)
        return attachment_count(page) - base

    def done(n: int, how: str) -> int:
        if n < want:
            log(f"Chỉ đính kèm được {n}/{want} ảnh ({how})", "warn")
        wait_uploads(page, log, check_cancel=check_cancel)
        return n

    inputs = page.locator(FILE_INPUTS)
    order = sorted(range(inputs.count()), key=lambda i: inputs.nth(i).get_attribute("multiple") is None)
    for i in order:
        inp = inputs.nth(i)
        accept = (inp.get_attribute("accept") or "").lower()
        if accept and not re.search(r"image|\*|png|jpe?g|webp", accept):
            continue
        try:
            if inp.get_attribute("multiple") is not None:
                inp.set_input_files(files, timeout=60_000)
            else:
                for f in files:
                    page.locator(FILE_INPUTS).nth(i).set_input_files(f, timeout=60_000)
                    page.wait_for_timeout(1200)
        except PWError:
            continue
        n = shown_after(per_try_s)
        if n > 0:
            return done(n, f"ô tải {i + 1}")
    # dự phòng: nút ＋ → (menu) tải ảnh / tệp → hộp chọn file
    plus = page.locator(PLUS_BUTTONS).first
    if plus.count():
        try:
            with page.expect_file_chooser(timeout=8_000) as chooser:
                plus.click(timeout=3_000)
                page.wait_for_timeout(600)
                items = page.locator("[role='menuitem'], [role='option'], [role='menu'] button")
                for k in range(items.count()):
                    if UPLOAD_MENU.search(items.nth(k).inner_text() or ""):
                        items.nth(k).click(timeout=3_000)
                        break
            chooser.value.set_files(files)
            n = shown_after(per_try_s * 2)
            if n > 0:
                return done(n, "nút ＋")
        except PWError:
            pass
        page.keyboard.press("Escape")
    return 0


def wait_send_ready(page, send_selector: str, log, *, timeout_s: int = 180, check_cancel=None) -> bool:
    """Nút Gửi đang khoá (thường do file đính kèm chưa tải xong) → chờ nút mở lại."""
    start, warned = time.time(), False
    while time.time() - start < timeout_s:
        if check_cancel:
            check_cancel()
        try:
            btn = page.locator(send_selector).first
            if btn.count() and btn.is_visible() and btn.is_enabled() and btn.get_attribute("aria-disabled") != "true":
                return True
        except PWError:
            pass
        if not warned and time.time() - start > 2:
            log("Nút Gửi đang khoá (file đính kèm chưa tải xong?) — chờ…")
            warned = True
        page.wait_for_timeout(500)
    return False
