"""Tạo ảnh bằng trình duyệt đã đăng nhập: Gemini ('Tạo hình ảnh'), Grok Imagine (Image), Dola AI Creation (Image)."""
import base64
import json
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from . import dola_video as dola
from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import SITES, _launch
from .gemini_veo import _enable_tool, _find_box, _upload_image
from .grok_imagine import (FETCH_BLOB_JS, IMAGINE_URL, LOGIN_ERROR, PROGRESS_JS, PROMPT_BOX, _attach_images,
                           _choose_option, type_multiline)

# Ảnh kết quả: ảnh đủ lớn đã tải xong (bỏ icon, avatar, ảnh xem trước nhỏ), trong vùng `scope`,
# trừ ảnh nằm trong `exclude` (vd. ảnh tham chiếu trong tin nhắn của người dùng)
IMAGES_JS = """({scope, exclude}) => [...document.querySelectorAll(scope ? scope + ' img' : 'img')]
  .filter(i => i.complete && i.naturalWidth >= 400 && i.naturalHeight >= 400)
  .filter(i => !exclude || !i.closest(exclude))
  .map(i => i.currentSrc || i.src).filter(Boolean)"""
# Lấy điểm ảnh từ <img> qua canvas — dùng khi blob: đã bị thu hồi khiến fetch() lỗi "Failed to fetch"
CANVAS_JS = """src => {
  const img = [...document.images].find(i => (i.currentSrc || i.src) === src);
  if (!img || !img.naturalWidth) return null;
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  c.getContext('2d').drawImage(img, 0, 0);
  try { return c.toDataURL('image/png').split(',')[1]; } catch (e) { return null; }
}"""
# ChatGPT đặt ảnh tạo ra trong khối riêng (có nút Edit/Share), không nằm trong tin nhắn trợ lý →
# tìm trong toàn vùng hội thoại, trừ tin nhắn người dùng, ô soạn tin, thanh bên.
CHATGPT_SCOPE = "main"
# Ảnh tham chiếu người dùng gửi có alt "User attachment" (không nằm trong khung data-message-author-role=user)
CHATGPT_EXCLUDE = "[data-message-author-role='user'], form, nav, header, img[alt*='attachment' i]"
CHATGPT_GENERATED = "[data-testid*='generated-image']"  # khối ảnh ChatGPT tạo ra (alt "Generated image N")
CHATGPT_BUSY = "button[data-testid='stop-button']"
CHATGPT_LOGIN = "button[data-testid='login-button']"
GEMINI_SCOPE = "model-response"
GEMINI_IMAGE_TOOL = re.compile(r"(Tạo hình ảnh|Create image|Image)", re.I)
GROK_IMAGE_MODE = "button[role='radio'][aria-label='Image']"
DOLA_IMAGE_TAB = "[data-testid='creation-skill-switch-tab-image']"
DOLA_IMAGE_RATIO = "[data-testid='chat_input_action_image_creation_ratio']"


def _open(pw, channel: str, show_browser: bool, offscreen: bool, profile: dict | None = None):
    try:
        return _launch(pw, channel, visible=show_browser, offscreen=offscreen and not show_browser, profile=profile)
    except PWError as exc:
        raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc


def _goto(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PWError:
        pass


def _images(page, scope: str, exclude: str = "") -> list[str]:
    return page.evaluate(IMAGES_JS, {"scope": scope, "exclude": exclude})


def _wait_for_images(page, before: set, count: int, timeout_s: int, check_cancel, log, *, scope: str = "",
                     busy: str = "", exclude: str = "", prefer: str = "") -> list[str]:
    """Chờ ảnh mới xuất hiện và ổn định (đủ số lượng, hết % tiến trình, hết trạng thái 'đang tạo')."""
    deadline = time.time() + timeout_s
    stable, since, last_pct = (), 0.0, None
    while time.time() < deadline:
        check_cancel()
        pct = page.evaluate(PROGRESS_JS)
        if pct is not None and pct != last_pct:
            log(f"Đang tạo ảnh {pct}%")
        last_pct = pct
        generating = bool(busy) and page.locator(busy).count() > 0 and page.locator(busy).first.is_visible()
        fresh = list(dict.fromkeys(src for src in _images(page, scope, exclude) if src not in before))
        if prefer:  # có ảnh trong khối ưu tiên (vd. khối ảnh tạo ra của ChatGPT) thì chỉ lấy các ảnh đó
            preferred = [src for src in _images(page, prefer) if src in fresh]
            fresh = preferred or fresh
        if fresh:
            key = tuple(fresh)
            if key != stable:
                stable, since = key, time.time()
            elif not generating and ((len(fresh) >= count and pct is None and time.time() - since > 3)
                                     or time.time() - since > 20):
                return fresh[:count]
        page.wait_for_timeout(2000)
    seen = page.evaluate("() => [...document.images].filter(i => i.naturalWidth >= 400).length")
    raise LLMError(f"Chưa nhận được ảnh (hết thời gian chờ) — trang có {seen} ảnh lớn, {len(stable)} ảnh mới "
                   "nhận diện được. Thử tích 'Hiện trình duyệt' để xem trang.")


def _download(ctx, page, src: str) -> bytes:
    """Tải ảnh kết quả, thử lần lượt: data: → HTTP (cookie phiên) → fetch blob → canvas → chụp phần tử."""
    if src.startswith("data:"):
        return base64.b64decode(src.split(",", 1)[1])
    if not src.startswith("blob:"):
        try:
            resp = ctx.request.get(src, headers={"Referer": page.url}, timeout=120_000)
            if resp.ok and len(resp.body()) > 1000:
                return resp.body()
        except PWError:
            pass
    else:
        try:
            return base64.b64decode(page.evaluate(FETCH_BLOB_JS, src))
        except PWError:
            pass  # blob đã bị thu hồi / khác ngữ cảnh → lấy qua canvas
    data = page.evaluate(CANVAS_JS, src)
    if data:
        return base64.b64decode(data)
    img = page.locator(f"img[src={json.dumps(src)}]").first  # cuối cùng: chụp chính phần tử ảnh
    if img.count():
        return img.screenshot(type="png")
    raise LLMError("Không tải được ảnh kết quả từ trang web")


def gemini_images(prompt: str, *, aspect: str, count: int, images: list[Path], channel: str, show_browser: bool,
                  log, check_cancel, timeout_s: int = 600) -> list[bytes]:
    site = SITES["gemini"]
    with profile_session("gemini") as prof, sync_playwright() as pw:
        ctx = _open(pw, channel, show_browser, offscreen=False, profile=prof)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _goto(page, site.url)
            box = _find_box(page, site)
            _enable_tool(page, GEMINI_IMAGE_TOOL, LLMError("Không tìm thấy công cụ 'Tạo hình ảnh' trên Gemini"))
            if images:
                _upload_image(page, images[0], log)
            before = set(_images(page, GEMINI_SCOPE))
            box.click()
            type_multiline(page, f"Tạo hình ảnh tỉ lệ {aspect}: {prompt}")
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            log("Đã gửi prompt — Gemini đang tạo ảnh…")
            srcs = _wait_for_images(page, before, 1, timeout_s, check_cancel, log, scope=GEMINI_SCOPE,
                                    busy=site.stop_selector)
            return [_download(ctx, page, src) for src in srcs]
        finally:
            _close(ctx)


def grok_images(prompt: str, *, aspect: str, count: int, images: list[Path], channel: str, show_browser: bool,
                log, check_cancel, timeout_s: int = 600) -> list[bytes]:
    with profile_session("grok") as prof, sync_playwright() as pw:
        ctx = _open(pw, channel, show_browser, offscreen=True, profile=prof)  # grok.com chặn headless (Cloudflare)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _goto(page, IMAGINE_URL)
            box = page.locator(PROMPT_BOX).first
            try:
                box.wait_for(state="visible", timeout=20_000)
            except PWError as exc:
                raise LLMError(LOGIN_ERROR) from exc
            if images:
                _attach_images(page, images, log)
            mode = page.locator(GROK_IMAGE_MODE).first
            if mode.count() and mode.get_attribute("aria-checked") != "true":
                mode.click()
                page.wait_for_timeout(800)
            if not _choose_option(page, "Aspect Ratio", aspect):
                log(f"Không đặt được tỉ lệ {aspect} trên Grok — app sẽ cắt lại", "warn")
            if count > 1:
                _choose_option(page, "Image Count", f"×{count}")
            before = set(_images(page, ""))
            box.click()
            type_multiline(page, prompt)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            log("Đã gửi prompt — Grok Imagine đang tạo ảnh…")
            srcs = _wait_for_images(page, before, count, timeout_s, check_cancel, log)
            return [_download(ctx, page, src) for src in srcs]
        finally:
            _close(ctx)


def dola_images(prompt: str, *, aspect: str, count: int, images: list[Path], channel: str, show_browser: bool,
                log, check_cancel, timeout_s: int = 600) -> list[bytes]:
    with profile_session("dola") as prof, sync_playwright() as pw:
        ctx = _open(pw, channel, show_browser, offscreen=True, profile=prof)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _goto(page, dola.CREATION_URL)
            page.wait_for_timeout(2000)
            for selector in dola.DISMISS:
                try:
                    page.locator(selector).first.click(timeout=1500)
                except PWError:
                    pass
            if dola._needs_login(page):
                raise LLMError(dola.LOGIN_ERROR)
            tab = page.locator(DOLA_IMAGE_TAB).first
            if tab.count() and tab.get_attribute("aria-selected") != "true":
                tab.click()
                page.wait_for_timeout(1000)
            if not dola._choose(page, DOLA_IMAGE_RATIO, aspect):
                log(f"Không đặt được tỉ lệ {aspect} trên Dola — app sẽ cắt lại", "warn")
            if images:
                dola._attach_images(page, images, log)
            before = set(_images(page, ""))
            page.locator(dola.PROMPT_BOX).first.click()
            type_multiline(page, prompt)
            page.wait_for_timeout(400)
            send = page.locator(dola.SEND_BTN).first
            if send.count() and send.is_enabled():
                send.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(2500)
            if dola._needs_login(page):
                raise LLMError(dola.LOGIN_ERROR)
            log("Đã gửi prompt — Dola (Seedream) đang tạo ảnh…")
            srcs = _wait_for_images(page, before, count, timeout_s, check_cancel, log)
            return [_download(ctx, page, src) for src in srcs]
        finally:
            _close(ctx)


def chatgpt_images(prompt: str, *, aspect: str, count: int, images: list[Path], channel: str, show_browser: bool,
                   log, check_cancel, timeout_s: int = 600) -> list[bytes]:
    """OpenAI qua trình duyệt: nhờ ChatGPT (chatgpt.com, tài khoản đã đăng nhập) tạo ảnh trong cuộc trò chuyện."""
    site = SITES["chatgpt"]
    with profile_session("chatgpt") as prof, sync_playwright() as pw:
        ctx = _open(pw, channel, show_browser, offscreen=True, profile=prof)  # chatgpt.com hay chặn headless
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _goto(page, site.url)
            box = _find_box(page, site)
            login = page.locator(CHATGPT_LOGIN).first
            if login.count() and login.is_visible():
                raise LLMError("Chưa đăng nhập ChatGPT — chọn model 'OpenAI · ChatGPT (trình duyệt)' và bấm 'Đăng nhập'.")
            if images:
                log(f"Đang tải {len(images)} ảnh tham chiếu lên ChatGPT…")
                if not _set_files(page, images, log):
                    log("Không tìm thấy ô tải ảnh trên ChatGPT — bỏ qua ảnh tham chiếu", "warn")
                page.wait_for_timeout(3000)
            # ChatGPT hay chỉ tạo 1 ảnh/tin nhắn (hoặc gom vào khối trượt chỉ tải ảnh đang hiện) →
            # xin từng ảnh một trong cùng cuộc trò chuyện, mỗi lượt chờ đúng 1 ảnh mới.
            results = []
            for i in range(count):
                check_cancel()
                before = set(_images(page, CHATGPT_SCOPE, CHATGPT_EXCLUDE))
                box = _find_box(page, site)
                box.click()
                if i == 0:
                    message = (f"Hãy tạo 1 hình ảnh tỉ lệ {aspect} theo mô tả sau. Chỉ trả về ảnh, không giải thích.\n"
                               + prompt)
                else:
                    message = (f"Tạo thêm 1 phiên bản khác của ảnh trên (cùng yêu cầu, tỉ lệ {aspect}, bố cục/góc máy "
                               "khác một chút). Chỉ trả về ảnh.")
                type_multiline(page, message)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                log(f"Đã gửi prompt — ChatGPT đang tạo ảnh {i + 1}/{count} (thường mất 30–90 giây)…")
                src = _wait_for_images(page, before, 1, timeout_s, check_cancel, log, scope=CHATGPT_SCOPE,
                                       busy=CHATGPT_BUSY, exclude=CHATGPT_EXCLUDE, prefer=CHATGPT_GENERATED)[0]
                results.append(_download(ctx, page, src))
                log(f"Đã nhận ảnh {i + 1}/{count} từ ChatGPT")
            return results
        finally:
            _close(ctx)


def _set_files(page, files: list[Path], log) -> bool:
    """Đưa file vào ô tải lên của trang. Bỏ qua ô chụp camera ([capture], vd 'Take a photo' của ChatGPT);
    ưu tiên ô nhận nhiều file, nếu chỉ có ô 1 file thì tải từng ảnh một."""
    multi = page.locator("input[type='file'][multiple]:not([capture])").first
    if multi.count():
        multi.set_input_files([str(p) for p in files])
        return True
    single = page.locator("input[type='file']:not([capture])").first
    if not single.count():
        return False
    for path in files:
        single.set_input_files(str(path))
        page.wait_for_timeout(1500)  # chờ trang nhận file trước khi gửi file tiếp theo
    return True


def _close(ctx) -> None:
    try:
        ctx.close()
    except PWError:
        pass
