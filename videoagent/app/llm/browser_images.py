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
from .browser_chat import PENDING_JS, SEND_BUTTONS, SITES, _launch
from .uploads import attach_files, wait_send_ready, wait_uploads
from .gemini_veo import _enable_tool, _find_box, _upload_images
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
                _upload_images(page, images, log)
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
                # đính kèm + xác minh ảnh hiện trong ô soạn + chờ tải lên xong; không được ảnh nào → dừng, KHÔNG gửi
                # prompt trơn (ChatGPT sẽ đòi ảnh hoặc tạo sai người / sản phẩm, tốn lượt)
                shown = attach_files(page, images, log, check_cancel=check_cancel)
                if not shown:
                    raise LLMError("Không đính kèm được ảnh tham chiếu lên ChatGPT (ảnh không hiện trong ô soạn) — "
                                   "chưa gửi prompt để tránh tạo sai ảnh. Bật “Hiện Chrome” để xem rồi thử lại.")
                log(f"Đã đính kèm {shown}/{len(images)} ảnh tham chiếu lên ChatGPT")
            # ChatGPT hay chỉ tạo 1 ảnh/tin nhắn (hoặc gom vào khối trượt chỉ tải ảnh đang hiện) →
            # xin từng ảnh một trong cùng cuộc trò chuyện, mỗi lượt chờ đúng 1 ảnh mới.
            results = []
            for i in range(count):
                check_cancel()
                # ảnh trước vừa hiện nhưng ChatGPT có thể vẫn đang trả lời (nút Dừng) → Enter không gửi được.
                # Chờ xong hẳn rồi mới chụp danh sách ảnh cũ (bản nét cuối của ảnh trước không bị tính là ảnh mới).
                _chatgpt_idle(page, check_cancel, log)
                before = set(_images(page, CHATGPT_SCOPE, CHATGPT_EXCLUDE))
                if i == 0:
                    message = (f"Hãy tạo 1 hình ảnh tỉ lệ {aspect} theo mô tả sau. Chỉ trả về ảnh, không giải thích. "
                               f"{CHATGPT_SELF_ADJUST}\n" + prompt)
                else:
                    message = (f"Tạo thêm 1 phiên bản khác của ảnh trên (cùng yêu cầu, tỉ lệ {aspect}, bố cục/góc máy "
                               f"khác một chút). Chỉ trả về ảnh. {CHATGPT_SELF_ADJUST}")
                previous = _chatgpt_last_reply(page)
                _chatgpt_send(page, site, message, check_cancel, log)
                log(f"Đã gửi prompt — ChatGPT đang tạo ảnh {i + 1}/{count} (thường mất 30–90 giây)…")
                src = _chatgpt_wait_image(page, site, before, previous, timeout_s, check_cancel, log)
                results.append(_download(ctx, page, src))
                log(f"Đã nhận ảnh {i + 1}/{count} từ ChatGPT")
            return results
        finally:
            _close(ctx)


CHATGPT_SELF_ADJUST = ("Nếu có chi tiết không phù hợp chính sách, hãy tự điều chỉnh sang phiên bản nhẹ nhàng hơn "
                       "và tạo ảnh luôn, không cần hỏi lại.")
CHATGPT_AUTO_REPLY = ("Có, bạn cứ làm theo hướng bạn vừa đề xuất và tạo ảnh luôn nhé (giữ đúng tỉ lệ khung hình), "
                      "không cần hỏi lại.")
CHATGPT_MAX_AUTO = 2  # số lần tự đồng ý tối đa cho 1 ảnh
# ChatGPT hỏi lại / đề xuất phương án khác (thay vì tạo ảnh) → tự đồng ý; từ chối hẳn → báo lỗi kèm câu trả lời
CHATGPT_OFFER = re.compile(r"(\?|bạn có muốn|muốn mình|có thể thử|mình có thể|phiên bản|thay vì|would you like|"
                           r"do you want|shall i|should i|i can (?:try|create|make)|instead)", re.I)
CHATGPT_WORKING = re.compile(r"(creating image|generating|đang tạo (hình )?ảnh|image created|đã tạo ảnh)", re.I)
CHATGPT_REPLY_JS = """() => {
  const msgs = [...document.querySelectorAll("[data-message-author-role='assistant']")];
  return msgs.length ? msgs[msgs.length - 1].innerText : '';
}"""


def _chatgpt_busy(page) -> bool:
    try:
        busy = page.locator(CHATGPT_BUSY)
        return bool(busy.count()) and busy.first.is_visible()
    except PWError:
        return False


def _chatgpt_idle(page, check_cancel, log, timeout_s: int = 150) -> None:
    """Chờ ChatGPT trả lời xong lượt trước (hết nút Dừng). Quá giờ thì vẫn đi tiếp (_chatgpt_send tự gửi lại)."""
    deadline, warned = time.time() + timeout_s, False
    while _chatgpt_busy(page) and time.time() < deadline:
        check_cancel()
        if not warned:
            log("ChatGPT vẫn đang trả lời lượt trước — chờ xong rồi mới gửi yêu cầu tiếp")
            warned = True
        page.wait_for_timeout(1000)


def _chatgpt_send(page, site, message: str, check_cancel, log, tries: int = 4) -> None:
    """Gõ + gửi rồi KIỂM TRA đã gửi thật: prompt còn nằm trong ô soạn thảo (Enter bị bỏ qua vì ChatGPT đang bận /
    giao diện mới Enter chỉ xuống dòng) → chờ hết bận, bấm nút Gửi. Vẫn không gửi được → báo lỗi thay vì treo."""
    _chatgpt_idle(page, check_cancel, log)
    _find_box(page, site).click()
    type_multiline(page, message)
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    probe = " ".join(message.split())[:40]
    for attempt in range(tries):
        page.wait_for_timeout(1500)
        check_cancel()
        try:
            if not page.evaluate(PENDING_JS, probe):
                return
        except PWError:
            return
        if attempt == 0:
            log("Prompt chưa được gửi đi — chờ ChatGPT rảnh / ảnh đính kèm tải xong rồi bấm nút Gửi", "warn")
        _chatgpt_idle(page, check_cancel, log, timeout_s=60)
        # nút Gửi khoá vì ảnh đính kèm chưa tải xong → chờ (tối đa 3 phút), không tính là một lần gửi hỏng
        wait_uploads(page, log, check_cancel=check_cancel)
        wait_send_ready(page, SEND_BUTTONS, log, check_cancel=check_cancel)
        try:
            button = page.locator(SEND_BUTTONS).first
            if button.count() and button.is_visible() and button.is_enabled():
                button.click(timeout=3_000)
            else:
                _find_box(page, site).click()
                page.keyboard.press("Enter")
        except PWError:
            pass
    raise LLMError("Không gửi được yêu cầu lên ChatGPT (chữ vẫn nằm trong ô nhập) — bật “Hiện Chrome” để xem rồi thử lại")


def _chatgpt_last_reply(page) -> str:
    try:
        return " ".join(page.evaluate(CHATGPT_REPLY_JS).split())
    except PWError:
        return ""


def _chatgpt_wait_image(page, site, before: set, previous: str, timeout_s: int, check_cancel, log) -> str:
    """Chờ ảnh ChatGPT tạo. Mỗi 30 giây chưa có ảnh thì xem ChatGPT có trả lời bằng CHỮ không (câu trả lời mới, đã
    đứng yên qua 2 lần kiểm tra, không còn đang tạo): hỏi lại / đề xuất phương án nhẹ nhàng hơn → tự trả lời đồng ý
    (tối đa CHATGPT_MAX_AUTO lần); từ chối hẳn → báo lỗi kèm câu ChatGPT nói (thay vì chờ tới hết giờ)."""
    deadline = time.time() + timeout_s
    replies, seen = 0, ""
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise LLMError("ChatGPT chưa tạo xong ảnh (hết thời gian chờ)")
        try:
            return _wait_for_images(page, before, 1, min(30, left), check_cancel, log, scope=CHATGPT_SCOPE,
                                    busy=CHATGPT_BUSY, exclude=CHATGPT_EXCLUDE, prefer=CHATGPT_GENERATED)[0]
        except LLMError:
            pass  # 30 giây chưa có ảnh → xem ChatGPT đang nói gì
        busy = page.locator(CHATGPT_BUSY)
        if busy.count() and busy.first.is_visible():
            continue
        text = _chatgpt_last_reply(page)
        if not text or text == previous or CHATGPT_WORKING.search(text):
            continue
        if text != seen:  # câu trả lời mới → đợi thêm 1 lượt cho chắc ChatGPT đã nói xong (và ảnh không tới sau)
            seen = text
            continue
        if replies < CHATGPT_MAX_AUTO and CHATGPT_OFFER.search(text):
            from . import offers

            replies += 1
            # đề xuất / hỏi lại → form duyệt cho người dùng (hoặc tự đồng ý, theo ⚙ Cài đặt)
            reply = offers.resolve("ChatGPT", text, log, check_cancel, "ảnh")
            previous, seen = text, ""
            _chatgpt_send(page, site, reply, check_cancel, log)
            continue
        raise LLMError(f"ChatGPT không tạo ảnh — ChatGPT trả lời: “{text[:240]}”")


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
