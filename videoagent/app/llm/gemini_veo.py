"""Gemini Veo: tạo video từ prompt qua Gemini API (API key) hoặc qua gemini.google.com (công cụ 'Tạo video').

Tài khoản Gemini không có công cụ 'Tạo video' → VeoUnavailable; orchestrator tự chuyển sang dựng video thường
(ai_video.as_regular_job_form).
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


class VeoUnavailable(LLMError):
    """Tài khoản Gemini (trình duyệt) không có công cụ tạo video Veo."""

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
DEFAULT_MODEL = "veo-3.1-generate-preview"
EXPECTED_S = 120  # thời gian tạo ước lượng, chỉ để vẽ thanh tiến trình


def generate_video_api(prompt: str, out_path: Path, *, api_key: str, model: str = "", aspect: str = "9:16",
                       duration: str = "8s", resolution: str = "720p", images: list[Path] | None = None,
                       log=print, check_cancel=lambda: None, on_progress=None, timeout_s: int = 900) -> None:
    if not api_key:
        raise LLMError("Chưa nhập Gemini API key trong Cài đặt (cần cho Veo qua API)")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = model or DEFAULT_MODEL
    config = dict(aspect_ratio=aspect, number_of_videos=1, duration_seconds=int(duration.rstrip("s")),
                  resolution=resolution)
    parts = [types.Image(image_bytes=Path(p).read_bytes(), mime_type=MIME.get(Path(p).suffix.lower(), "image/png"))
             for p in images or []]

    def start(cfg: dict, image=None):
        return client.models.generate_videos(model=model, prompt=prompt, image=image,
                                             config=types.GenerateVideosConfig(**cfg))

    try:
        if parts and hasattr(types, "VideoGenerationReferenceImage"):
            refs = [types.VideoGenerationReferenceImage(image=img, reference_type="asset") for img in parts[:3]]
            try:
                operation = start({**config, "reference_images": refs})
            except Exception as exc:  # model/tuỳ chọn không nhận ảnh tham chiếu → dùng ảnh đầu làm khung mở đầu
                log(f"Veo không nhận ảnh tham chiếu ({exc}) — dùng ảnh đầu tiên làm khung mở đầu", "warn")
                operation = start(config, image=parts[0])
        else:
            operation = start(config, image=parts[0] if parts else None)
    except Exception as exc:
        raise LLMError(f"Gemini API (Veo) lỗi: {exc}") from exc

    log(f"Đã gửi prompt — Veo ({model}) đang tạo video…")
    began = time.time()
    while not operation.done:
        check_cancel()
        if time.time() - began > timeout_s:
            raise LLMError("Veo chưa tạo xong video (hết thời gian chờ)")
        time.sleep(8)
        operation = client.operations.get(operation)
        if on_progress:
            on_progress(min(95, int((time.time() - began) / EXPECTED_S * 100)))
    if operation.error:
        raise LLMError(f"Veo báo lỗi: {operation.error}")
    videos = getattr(operation.response, "generated_videos", None) or []
    if not videos:
        reasons = getattr(operation.response, "rai_media_filtered_reasons", None)
        raise LLMError(f"Veo không trả video{f' (bị lọc: {reasons})' if reasons else ''}")
    client.files.download(file=videos[0].video)
    videos[0].video.save(str(out_path))


# --------------------------------------------------------------------------- gemini.google.com
TOOLS_BUTTON = ("button[aria-label='Nội dung tải lên và công cụ'], button[aria-label*='Upload and tools' i], "
                "button[aria-label*='tools' i]")
MORE_TOOLS = "button[aria-label='Công cụ khác'], button[aria-label*='More tools' i]"
MENU_ITEMS = "[role='menuitemcheckbox'], [role='menuitem']"
VIDEO_TOOL = re.compile(r"(Tạo video|Create video|Video|Veo)", re.I)
IMAGE_INPUT = "input[type='file'][accept*='image']"
NO_VEO = "Tài khoản Gemini này chưa có công cụ 'Tạo video' (Veo) — cần gói Google AI Pro/Ultra."


def generate_video_browser(prompt: str, out_path: Path, *, channel: str = "chrome", show_browser: bool = False,
                           aspect: str = "9:16", duration: str = "8s", resolution: str = "720p",
                           images: list[Path] | None = None, log=print, check_cancel=lambda: None, on_progress=None,
                           timeout_s: int = 900) -> None:
    site = SITES["gemini"]
    with profile_session("gemini") as prof, sync_playwright() as pw:
        try:
            ctx = _launch(pw, channel, visible=show_browser, profile=prof)
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt '{channel}': {exc}") from exc
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(site.url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWError:
                pass
            box = _find_box(page, site)
            _enable_video_tool(page)  # kiểm tra Veo trước khi tải ảnh: không có thì báo sớm
            if images:
                _upload_image(page, images[0], log)
            before = {v["src"] for v in page.evaluate(VIDEOS_JS)}
            box.click()
            type_multiline(page, f"Tạo video tỉ lệ {aspect}: " + prompt)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            log("Đã gửi prompt — Gemini (Veo) đang tạo video…")
            src = _wait_for_video(page, before, timeout_s, check_cancel, on_progress)
            data = _download(ctx, page, src)
            if len(data) < 20_000:
                raise LLMError("File video tải về từ Gemini không hợp lệ")
            Path(out_path).write_bytes(data)
        finally:
            try:
                ctx.close()
            except PWError:
                pass


def _find_box(page, site):
    deadline = time.time() + 25
    while time.time() < deadline:
        if any(marker in page.url for marker in site.login_markers):
            break
        for selector in site.input_selectors:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                return loc
        page.wait_for_timeout(500)
    raise LLMError("Chưa đăng nhập Gemini — chọn Gemini Browser và bấm 'Đăng nhập'.")


def _open_tools(page) -> None:
    page.locator(TOOLS_BUTTON).first.click()
    page.wait_for_timeout(1000)


def _enable_tool(page, pattern: re.Pattern, error: Exception) -> None:
    """Bật một công cụ trong menu 'Nội dung tải lên và công cụ' (tìm cả trong 'Các công cụ khác')."""
    _open_tools(page)
    for attempt in range(2):
        items = page.locator(MENU_ITEMS)
        for i in range(items.count()):
            item = items.nth(i)
            text = (item.inner_text() or "").strip()
            if item.is_visible() and pattern.search(text) and "Drive" not in text:
                if item.get_attribute("aria-checked") != "true":
                    item.click()
                    page.wait_for_timeout(800)
                else:
                    page.keyboard.press("Escape")
                return
        more = page.locator(MORE_TOOLS).first
        if attempt == 0 and more.count():
            more.click()
            page.wait_for_timeout(1000)
    page.keyboard.press("Escape")
    raise error


def _enable_video_tool(page) -> None:
    _enable_tool(page, VIDEO_TOOL, VeoUnavailable(NO_VEO))


def _upload_image(page, image: Path, log) -> None:
    _open_tools(page)
    file_input = page.locator(IMAGE_INPUT).first
    if not file_input.count():
        page.keyboard.press("Escape")
        log("Không tìm thấy ô tải ảnh trên Gemini — bỏ qua ảnh tham chiếu", "warn")
        return
    before = page.locator(PREVIEW_IMG).count()
    file_input.set_input_files(str(image))
    page.keyboard.press("Escape")
    deadline = time.time() + 45
    while time.time() < deadline and page.locator(PREVIEW_IMG).count() <= before:
        page.wait_for_timeout(700)
    page.wait_for_timeout(1500)
