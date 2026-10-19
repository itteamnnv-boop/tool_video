"""Muse (muse.ai — trợ lý AI của Meta, Muse Image / Muse Video): tạo ảnh và video qua trình duyệt đã đăng nhập.

Muse là trợ lý dạng chat: app gửi yêu cầu vào "Main chat" rồi chờ Muse trả kết quả.
Cấu trúc trang (kiểm chứng 10/2026, đã đăng nhập):
- ô nhập: textarea[aria-label="Message"]; ô tải file: input[type=file][multiple] (ẩn, nút "Attach file").
- khung chat: [role=log]; kết quả Muse tạo nằm trong data-testid="hatch-chat-attachment-presentation-video"
  (ảnh: …-image); video chỉ có ảnh bìa + nút "Download video" — nút này CHỈ hiện ở tin nhắn mới nhất,
  nên không đếm nút được → mỗi yêu cầu kèm một mã riêng ở cuối tin nhắn, chỉ nhận kết quả nằm SAU mã đó.
- bảng Activity bên phải: mỗi việc Muse làm là một dòng ("Create … / Created …") → dùng để báo tiến trình.
Muse là agent làm được việc khác (gửi email, mua hàng…) nên lời nhắn luôn giới hạn: chỉ tạo ảnh/video.
"""
import re
import time
import uuid
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError
from ..browser_profiles import profile_session
from .browser_chat import SITES, BrowserChatProvider, _launch
from .browser_images import _download as download_image
from .grok_imagine import _ensure_submitted, type_multiline
from .grok_imagine import _download as download_video

SITE = "muse"
# ô nhập "Main chat": giao diện tiếng Anh (aria-label Message) hoặc tiếng Việt (placeholder "Nhắn tin")
BOX = ("textarea[aria-label='Message'], textarea[aria-label='Tin nhắn'], textarea[aria-label*='Nhắn' i], "
       "textarea[placeholder*='Nhắn' i], textarea[placeholder*='Message' i]")
DOWNLOAD_VIDEO = "button[aria-label='Download video']"
TARGET = "[data-va-target]"  # khung video kết quả của yêu cầu này (app tự gắn để rê chuột / bấm)
# Kết quả nằm sau mã yêu cầu: số khung video, ảnh kết quả, chữ Muse trả lời (để báo tiến trình / lỗi)
AFTER_MARKER_JS = """marker => {
  const log = document.querySelector("[role='log']") || document.body;
  const walk = document.createTreeWalker(log, NodeFilter.SHOW_TEXT);
  let anchor = null;
  while (walk.nextNode()) if (walk.currentNode.textContent.includes(marker)) anchor = walk.currentNode.parentElement;
  if (!anchor) return {sent: false, videos: 0, images: [], text: ''};
  const after = el => !!el && !anchor.contains(el) && !!(anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const vids = [...log.querySelectorAll("[data-testid='hatch-chat-attachment-presentation-video']")].filter(after);
  document.querySelectorAll('[data-va-target]').forEach(e => e.removeAttribute('data-va-target'));
  if (vids.length) vids[vids.length - 1].setAttribute('data-va-target', '1');
  const images = [...log.querySelectorAll("[data-testid^='hatch-chat-attachment-presentation']:not([data-testid$='-video']) img")]
    .filter(after).filter(i => i.complete && i.naturalWidth >= 300).map(i => i.currentSrc || i.src);
  let text = '';
  const walk2 = document.createTreeWalker(log, NodeFilter.SHOW_TEXT);
  while (walk2.nextNode()) if (after(walk2.currentNode.parentElement)) text += walk2.currentNode.textContent + ' ';
  return {sent: true, videos: vids.length, images, text: text.replace(/\\s+/g, ' ').trim().slice(-300)};
}"""
# Dòng mới nhất ở bảng Activity (Muse đang làm gì)
ACTIVITY_JS = """() => {
  const panel = document.querySelector("[data-testid='hatch-status-panel-sliding-surface']");
  if (!panel) return '';
  const item = [...panel.querySelectorAll('button')].find(b => !b.getAttribute('aria-label') && b.innerText.includes('\\n'));
  return item ? item.innerText.split('\\n').slice(0, 2).join(' — ').trim() : '';
}"""
EXPECTED_S = 180  # thời gian tạo video ước lượng, chỉ để vẽ thanh tiến trình
OFFER_QUIET_S = 20  # chữ Muse đứng yên bao lâu (chưa có ảnh / video) thì xét có phải lời đề xuất / hỏi lại không
OFFER_MAX = 2       # số lần trả lời đề xuất tối đa cho một yêu cầu
ONLY_MEDIA = ("Chỉ tạo nội dung theo yêu cầu, không thực hiện việc nào khác (không gửi email, không mua hàng, "
              "không mở hay đăng lên trang web nào), không cần hỏi lại.")
LOGIN_ERROR = "Chưa đăng nhập Muse — vào 'Profile trình duyệt', gán Muse cho một profile rồi bấm 'Đăng nhập'."
CLOSED_ERROR = "Cửa sổ Muse đã bị đóng trong lúc chờ kết quả — chạy lại (video Muse đã tạo vẫn tải tay được trên muse.ai)"


def _open_chat(pw, channel: str, show_browser: bool, prof):
    try:
        ctx = _launch(pw, channel, visible=show_browser, offscreen=not show_browser, profile=prof)
    except PWError as exc:
        raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(SITES[SITE].url, wait_until="domcontentloaded", timeout=60_000)
    box = page.locator(BOX).first
    try:  # đã đăng nhập thì ô nhập hiện sau ~1 giây; trang chào (chưa đăng nhập) không có ô này
        box.wait_for(state="visible", timeout=30_000)
    except PWError:
        ctx.close()
        raise LLMError(LOGIN_ERROR) from None
    page.wait_for_timeout(1500)
    return ctx, page, box


def _attach(page, images: list[Path], log) -> None:
    if not images:
        return
    from .uploads import attach_files

    log(f"Đang tải {len(images)} ảnh tham chiếu lên Muse…")
    # đính kèm + xác minh ảnh hiện trong ô soạn + chờ tải lên xong; không được ảnh nào → dừng, không gửi prompt trơn
    shown = attach_files(page, images, log)
    if not shown:
        raise LLMError("Không đính kèm được ảnh tham chiếu lên Muse (ảnh không hiện trong ô soạn) — chưa gửi prompt. "
                       "Bật “Hiện Chrome” để xem rồi thử lại.")
    log(f"Đã đính kèm {shown}/{len(images)} ảnh tham chiếu lên Muse")


def _send(page, box, message: str) -> str:
    """Gửi tin nhắn kèm mã yêu cầu ở dòng cuối; trả về mã để tìm đúng kết quả của lần gửi này."""
    marker = f"[VA-{uuid.uuid4().hex[:8]}]"
    box.click()
    type_multiline(page, f"{message}\n{marker}")
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    _ensure_submitted(page, box, message)
    return marker


def _activity_now(page) -> str:
    """Dòng Activity hiện tại (bảng bên phải tải chậm hơn khung chat ~4 giây) — làm mốc trước khi gửi."""
    for _ in range(5):
        value = page.evaluate(ACTIVITY_JS)
        if value:
            return value
        page.wait_for_timeout(1500)
    return ""


def _watch(page, marker: str, done, timeout_s: int, check_cancel, log, on_progress=None, baseline: str = "",
           send=None, what: str = "ảnh") -> dict:
    """Theo dõi Muse: báo dòng Activity mới (khác mốc trước khi gửi) / chữ Muse trả lời vào nhật ký,
    tới khi done(state) đúng. send(message) -> marker: Muse không tạo mà ĐỀ XUẤT / hỏi lại (chữ đứng yên, chưa có
    ảnh / video) → hỏi người dùng qua form duyệt hoặc tự đồng ý (app/llm/offers.py), gửi trả lời và theo dõi tiếp.
    Trả về state kèm "marker" = mã yêu cầu cuối cùng (kết quả nằm sau mã này)."""
    from . import offers

    began = time.time()
    last_activity, last_text, state = baseline, "", {}
    quiet_text, quiet_since, replies = "", time.time(), 0
    while time.time() - began < timeout_s:
        check_cancel()
        try:
            state = page.evaluate(AFTER_MARKER_JS, marker)
            activity = page.evaluate(ACTIVITY_JS)
        except PWError as exc:
            raise LLMError(CLOSED_ERROR) from exc
        if activity and activity != last_activity:
            log(f"Muse: {activity}")
            last_activity = activity
        text = state.get("text", "")
        if text and text != last_text and len(text) > len(last_text) + 20:  # Muse viết thêm câu trả lời
            log(f"Muse trả lời: {text[-160:]}")
            last_text = text
        if done(state):
            return {**state, "marker": marker}
        if text != quiet_text:
            quiet_text, quiet_since = text, time.time()
        no_media = not state.get("images") and not state.get("videos")
        if (send and text and no_media and replies < OFFER_MAX and time.time() - quiet_since >= OFFER_QUIET_S
                and offers.looks_like_offer(text)):
            reply = offers.resolve("Muse", text, log, check_cancel, what)
            marker = send(reply)  # kết quả sau câu trả lời này
            replies += 1
            quiet_text, quiet_since, last_text = "", time.time(), ""
            log(f"Đã trả lời Muse ({replies}/{OFFER_MAX}) — chờ Muse tạo {what}…")
            continue
        if on_progress:
            on_progress(min(95, int((time.time() - began) / EXPECTED_S * 100)))
        try:
            page.wait_for_timeout(3000)
        except PWError as exc:
            raise LLMError(CLOSED_ERROR) from exc
    reply = state.get("text", "")
    raise LLMError(("Muse chưa trả về kết quả (hết thời gian chờ)" if state.get("sent") else
                    "Không thấy tin nhắn đã gửi trong khung chat Muse")
                   + (f" — Muse trả lời: “{reply[-200:]}”" if reply else ". Bật 'Hiện trình duyệt' để xem."))


def muse_images(prompt: str, *, aspect: str, count: int, images: list[Path], channel: str, show_browser: bool,
                log, check_cancel, timeout_s: int = 600) -> list[bytes]:
    with profile_session(SITE) as prof, sync_playwright() as pw:
        ctx, page, box = _open_chat(pw, channel, show_browser, prof)
        try:
            _attach(page, images, log)
            baseline = _activity_now(page)
            refs = " Dùng các ảnh đính kèm làm ảnh tham chiếu." if images else ""
            marker = _send(page, box, f"Hãy tạo {count} hình ảnh tỉ lệ {aspect} theo mô tả sau.{refs} {ONLY_MEDIA} "
                                      f"Chỉ trả về ảnh.\n{prompt}")
            log("Đã gửi prompt — Muse đang tạo ảnh…")
            state = _watch(page, marker, lambda s: len(s.get("images", [])) >= count, timeout_s, check_cancel, log,
                           baseline=baseline, send=lambda m: _send(page, box, m), what="ảnh")
            page.wait_for_timeout(3000)  # ảnh cuối tải xong
            srcs = page.evaluate(AFTER_MARKER_JS, state["marker"])["images"]
            return [download_image(ctx, page, src) for src in srcs[:count]]
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def muse_video(prompt: str, out_path: Path, *, channel: str = "chrome", show_browser: bool = False,
               aspect: str = "9:16", duration: str = "10s", resolution: str = "720p",
               images: list[Path] | None = None, log=print, check_cancel=lambda: None, on_progress=None,
               timeout_s: int = 900, refs_note: str | None = None) -> None:
    """refs_note: câu mô tả ảnh đính kèm thay cho mặc định (vd. ảnh 1 là storyboard, không phải khung mở đầu)."""
    with profile_session(SITE) as prof, sync_playwright() as pw:
        ctx, page, box = _open_chat(pw, channel, show_browser, prof)
        try:
            _attach(page, images or [], log)
            baseline = _activity_now(page)
            refs = (f" {refs_note}" if refs_note is not None and images else
                    " Ảnh đính kèm ĐẦU TIÊN là khung hình mở đầu: tạo video trực tiếp từ đúng ảnh này (image-to-video), KHÔNG"
                    " tạo ảnh mới. Các ảnh sau là ảnh tham chiếu nhân vật / sản phẩm. GIỮ NGUYÊN khuôn mặt từng nhân vật"
                    " như trong ảnh (dáng mặt, mắt, mũi, miệng, màu da, tuổi, kiểu tóc) suốt video — không vẽ lại, không làm"
                    " đẹp, không đổi mặt. Khi chuyển yêu cầu cho công cụ tạo video, chép NGUYÊN VĂN đoạn IDENTITY LOCK."
                    if images else "")
            marker = _send(page, box, f"Hãy tạo 1 video tỉ lệ {aspect}, dài khoảng {duration}, độ phân giải {resolution} "
                                      f"theo mô tả sau.{refs} {ONLY_MEDIA} Chỉ trả về video.\n{prompt}")
            log(f"Đã gửi prompt (mã {marker}) — Muse đang tạo video, thường 2–4 phút…")
            state = _watch(page, marker, lambda s: s.get("videos", 0) > 0, timeout_s, check_cancel, log, on_progress,
                           baseline=baseline, send=lambda m: _send(page, box, m), what="video")
            log("Muse đã tạo xong video — đang tải về…")
            _save_video(ctx, page, Path(out_path), log, state["marker"])
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def _media_ready(page, marker: str, timeout_s: int = 90) -> bool:
    """Chờ ảnh bìa của video kết quả tải xong — Muse giải mã video chậm (lúc đầu chỉ là khung xám / 'Video not found'),
    bấm tải khi chưa xong sẽ không ra file."""
    began = time.time()
    while time.time() - began < timeout_s:
        page.evaluate(AFTER_MARKER_JS, marker)  # gắn lại data-va-target (khung có thể được vẽ lại)
        target = page.locator(TARGET).first
        if target.count():
            target.scroll_into_view_if_needed(timeout=10_000)
            if page.evaluate("""() => [...document.querySelectorAll('[data-va-target] img, [data-va-target] video')]
                                .some(e => (e.naturalWidth || e.videoWidth) > 0)"""):
                return True
        page.wait_for_timeout(2000)
    return False


def _save_video(ctx, page, out_path: Path, log, marker: str = "") -> None:
    """Tải video kết quả: chờ ảnh bìa → rê chuột lên đúng khung video → nút 'Download video';
    không có nút thì mở video lấy file. Ảnh bìa không tải được thì tải lại trang một lần."""
    if marker and not _media_ready(page, marker):
        log("Video trên Muse chưa tải xong — tải lại trang rồi thử lại", "warn")
        page.reload(wait_until="domcontentloaded")
        page.locator(BOX).first.wait_for(state="visible", timeout=30_000)
        if not _media_ready(page, marker):
            raise LLMError("Muse báo đã tạo video nhưng chưa xem được video (Video not found) — mở muse.ai để tải tay")
    target = page.locator(TARGET).first
    try:
        target.scroll_into_view_if_needed(timeout=10_000)
        target.hover()
        page.wait_for_timeout(800)
        button = page.locator(DOWNLOAD_VIDEO).last
        if button.count():
            with page.expect_download(timeout=120_000) as info:
                button.click()
            info.value.save_as(str(out_path))
            log(f"Đã tải video từ Muse: {info.value.suggested_filename}")
        else:  # dự phòng: mở video rồi lấy file từ thẻ <video> lớn nhất
            target.click()
            page.wait_for_timeout(3000)
            src = page.evaluate("""() => [...document.querySelectorAll('video')]
              .map(v => ({src: v.currentSrc || v.src, w: v.getBoundingClientRect().width})).filter(v => v.src)
              .sort((a, b) => b.w - a.w).map(v => v.src)[0] || ''""")
            if not src:
                raise LLMError("Không tìm thấy nút tải hay file video trên Muse — tải tay video vừa tạo trên muse.ai")
            out_path.write_bytes(download_video(ctx, page, src))
    except PWError as exc:
        raise LLMError(f"Không tải được video từ Muse: {exc}") from exc
    if out_path.stat().st_size < 20_000:
        raise LLMError("File video tải về từ Muse không hợp lệ")


# ---------------------------------------------------------------- viết chữ (storyboard, mô tả, content)
# Chữ Muse trả lời nằm SAU mã yêu cầu trong khung chat; giữ xuống dòng theo khối (đoạn, dòng, mục danh sách)
ANSWER_JS = r"""marker => {
  const log = document.querySelector("[role='log']") || document.querySelector('main') || document.body;
  const walk = document.createTreeWalker(log, NodeFilter.SHOW_TEXT);
  let anchor = null;
  while (walk.nextNode()) if (walk.currentNode.textContent.includes(marker)) anchor = walk.currentNode.parentElement;
  if (!anchor) return {sent: false, text: ''};
  const after = el => !!el && !anchor.contains(el) && !!(anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const block = el => el.closest('p, li, pre, h1, h2, h3, h4, h5, h6, tr, div') || el;
  let out = '', last = null;
  const walk2 = document.createTreeWalker(log, NodeFilter.SHOW_TEXT);
  while (walk2.nextNode()) {
    const el = walk2.currentNode.parentElement;
    if (!after(el) || el.closest('button')) continue;
    const b = block(el);
    if (last && b !== last) out += '\n';
    out += walk2.currentNode.textContent;
    last = b;
  }
  return {sent: true, text: out.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()};
}"""
LOG_TAIL_JS = """() => ((document.querySelector("[role='log']") || document.querySelector('main') || document.body)
  .innerText || '').slice(-400)"""
# Muse mới dùng lần đầu: hỏi đặt tên trợ lý (Beacon / Astro / Muse…) — gửi storyboard lúc này Muse sẽ hiểu sai
ONBOARDING = re.compile(r"(muốn gọi mình là gì|what (would|do) you (like to|want to) call me|what should i call)", re.I)
ONBOARDING_ERROR = ("Muse đang hỏi thiết lập ban đầu (“Bạn muốn gọi mình là gì?”) — mở Muse bằng profile trình duyệt "
                    "(Profile trình duyệt → Đăng nhập), chọn tên cho trợ lý rồi chạy lại.")
STABLE_S = 5      # chữ đứng yên bao lâu thì coi là Muse viết xong
GIVE_UP_S = 60    # chữ đứng yên lâu mà điều kiện complete() vẫn sai → trả về bản hiện có (bên gọi tự báo lỗi JSON)


class MuseChatProvider(BrowserChatProvider):
    """Muse viết chữ (storyboard, mô tả nhân vật, content…) trong "Main chat": gửi kèm mã yêu cầu, đọc toàn bộ chữ
    Muse trả lời sau mã đó. Bong bóng chat của Muse không có thuộc tính vai trò như ChatGPT nên không đếm bong bóng."""

    def __init__(self, channel: str = "chrome", show_browser: bool = False, timeout_s: int = 240) -> None:
        super().__init__(SITE, channel=channel, show_browser=show_browser, timeout_s=timeout_s)

    @property
    def supports_images(self) -> bool:
        return False

    def generate(self, prompt: str, images: list | None = None, complete=None) -> str:
        prompt += self.site.prompt_suffix
        with profile_session(SITE) as prof, sync_playwright() as pw:
            ctx, page, box = _open_chat(pw, self.channel, self.show_browser, prof)
            try:
                if ONBOARDING.search(page.evaluate(LOG_TAIL_JS) or ""):
                    raise LLMError(ONBOARDING_ERROR)
                marker = _send(page, box, prompt)
                return self._wait_text(page, marker, complete)
            except PWError as exc:
                raise LLMError(f"Muse: {exc}") from exc
            finally:
                try:
                    ctx.close()
                except PWError:
                    pass

    def _wait_text(self, page, marker: str, complete=None) -> str:
        began, last, since = time.time(), "", time.time()
        while time.time() - began < self.timeout_s:
            state = page.evaluate(ANSWER_JS, marker)
            if not state.get("sent") and time.time() - began > 30:
                raise LLMError("Không thấy tin nhắn vừa gửi trong khung chat Muse — giao diện Muse có thể đã thay đổi")
            text = state.get("text") or ""
            stop = page.locator(self.site.stop_selector)
            busy = bool(stop.count()) and stop.first.is_visible()
            if text != last:
                last, since = text, time.time()
            elif text and not busy:
                quiet = time.time() - since
                if (complete is None or complete(text)) and quiet >= STABLE_S:
                    return text
                if quiet >= GIVE_UP_S:
                    return text
            page.wait_for_timeout(1500)
        if last:
            return last
        raise LLMError(f"Muse chưa trả lời sau {self.timeout_s // 60} phút")
