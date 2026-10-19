"""Engine tạo hình ảnh: OpenAI (mặc định), Gemini / Grok / Dola qua trình duyệt, Gemini API (Nano Banana)."""
import subprocess
from pathlib import Path

from .. import ffmpeg

DEFAULT_ENGINE = "openai_api"
ENGINES = {
    "openai_api": {
        "name": "OpenAI · GPT Image (API key)",
        "aspects": ["1:1", "9:16", "16:9", "2:3", "3:2", "4:5"], "counts": [1, 2, 3, 4], "max_images": 10,
        "quality": True,
        "note": "Model chính. Dùng OpenAI API key trong Cài đặt (tính phí theo ảnh). Nhận tối đa 10 ảnh tham chiếu.",
    },
    "chatgpt_browser": {
        "name": "OpenAI · ChatGPT (trình duyệt)", "browser": True,
        "aspects": ["1:1", "9:16", "16:9", "2:3", "3:2", "4:5"], "counts": [1, 2, 3, 4], "max_images": 10,
        "note": "Dùng tài khoản ChatGPT đã đăng nhập (chatgpt.com) — không cần API key, có giới hạn lượt theo gói. "
                "Nhiều ảnh = xin lần lượt từng ảnh trong cùng cuộc trò chuyện (mỗi ảnh ~30–90 giây).",
    },
    "gemini_browser": {
        "name": "Gemini · Tạo hình ảnh (trình duyệt)", "browser": True,
        "aspects": ["1:1", "9:16", "16:9", "3:4", "4:3"], "counts": [1], "max_images": 10,
        "note": "Công cụ 'Tạo hình ảnh' của gemini.google.com — tài khoản miễn phí dùng được. Mỗi lần 1 ảnh, "
                "gửi kèm tối đa 10 ảnh tham chiếu.",
    },
    "grok_browser": {
        "name": "Grok Imagine · Image (trình duyệt)", "browser": True,
        "aspects": ["9:16", "16:9", "1:1", "2:3", "3:2"], "counts": [1, 2, 4], "max_images": 10,
        "note": "grok.com/imagine chế độ Image — cần đăng nhập Grok.",
    },
    "dola_browser": {
        "name": "Dola · Seedream (trình duyệt)", "browser": True,
        "aspects": ["9:16", "16:9", "1:1", "2:3", "3:4", "4:3"], "counts": [1, 2, 4], "max_images": 4,
        "note": "Dola AI Creation → Image (Seedream) — cần đăng nhập Dola.",
    },
    "muse_browser": {
        "name": "Meta · Muse (trình duyệt)", "browser": True,
        "aspects": ["1:1", "9:16", "16:9", "3:4", "4:3"], "counts": [1, 2, 4], "max_images": 4,
        "note": "Trợ lý Muse của Meta (muse.ai, Muse Image) — cần đăng nhập Muse trong Profile trình duyệt. "
                "Tính năng mới: giao diện Muse đổi thì có thể cần cập nhật app.",
    },
    "gemini_api": {
        "name": "Gemini · Nano Banana (API key)",
        "aspects": ["1:1", "9:16", "16:9", "3:4", "4:3", "2:3", "3:2"], "counts": [1, 2, 3, 4], "max_images": 3,
        "note": "Gemini API key trong Cài đặt (model ảnh: gemini_image_model).",
    },
}
EXT = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}


def normalize(engine: str, aspect: str, count: int) -> tuple[str, int]:
    spec = ENGINES[engine]
    aspect = aspect if aspect in spec["aspects"] else spec["aspects"][0]
    fitting = [c for c in spec["counts"] if c <= max(1, count)]
    return aspect, (fitting[-1] if fitting else spec["counts"][0])


def generate(engine: str, prompt: str, *, aspect: str, count: int, quality: str, images: list[Path], settings,
             show_browser: bool, log, check_cancel) -> list[bytes]:
    browser = dict(aspect=aspect, count=count, images=images, channel=settings.get("browser_channel"),
                   show_browser=show_browser, log=log, check_cancel=check_cancel)
    if engine == "openai_api":
        from .openai_images import generate_images
        return generate_images(prompt, Path("."), api_key=settings.get("openai_api_key"),
                               model=settings.get("openai_image_model"), aspect=aspect, count=count,
                               quality=quality, images=images, log=log)
    if engine == "chatgpt_browser":
        from .browser_images import chatgpt_images
        return chatgpt_images(prompt, **browser)
    if engine == "gemini_browser":
        from .browser_images import gemini_images
        return gemini_images(prompt, **browser)
    if engine == "grok_browser":
        from .browser_images import grok_images
        return grok_images(prompt, **browser)
    if engine == "dola_browser":
        from .browser_images import dola_images
        return dola_images(prompt, **browser)
    if engine == "muse_browser":
        from .muse_browser import muse_images
        return muse_images(prompt, **browser)
    if engine == "gemini_api":
        return _gemini_api(prompt, settings=settings, aspect=aspect, count=count, images=images, log=log,
                           check_cancel=check_cancel)
    raise ValueError(f"Engine ảnh không hỗ trợ: {engine}")


def _gemini_api(prompt: str, *, settings, aspect: str, count: int, images: list[Path], log, check_cancel) -> list[bytes]:
    from google import genai
    from google.genai import types

    from .base import LLMError

    api_key = settings.get("gemini_api_key")
    if not api_key:
        raise LLMError("Chưa nhập Gemini API key trong Cài đặt")
    client = genai.Client(api_key=api_key)
    model = settings.get("gemini_image_model") or "gemini-2.5-flash-image"
    contents = [prompt, *(types.Part.from_bytes(data=Path(p).read_bytes(), mime_type="image/png") for p in images)]
    config = {"response_modalities": ["IMAGE", "TEXT"]}
    if hasattr(types, "ImageConfig"):
        config["image_config"] = types.ImageConfig(aspect_ratio=aspect)
    out = []
    for i in range(count):
        check_cancel()
        log(f"Gemini API ({model}) đang tạo ảnh {i + 1}/{count}…")
        try:
            resp = client.models.generate_content(model=model, contents=contents,
                                                  config=types.GenerateContentConfig(**config))
        except Exception as exc:  # lỗi quota/mạng/model của SDK
            raise LLMError(f"Gemini API lỗi: {exc}") from exc
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    out.append(part.inline_data.data)
    if not out:
        raise LLMError("Gemini API không trả ảnh nào")
    return out[:count]


def save_images(datas: list[bytes], out_dir: Path) -> list[Path]:
    paths = []
    for i, data in enumerate(datas, 1):
        ext = next((e for magic, e in EXT.items() if data.startswith(magic)), ".png")
        path = out_dir / f"img_{i}{ext}"
        path.write_bytes(data)
        paths.append(path)
    return paths


def fit_aspect(path: Path, aspect: str) -> bool:
    """Cắt giữa ảnh cho đúng tỉ lệ đã chọn (model trả kích thước cố định). Trả True nếu đã cắt."""
    try:
        aw, ah = (int(x) for x in aspect.split(":"))
        width, height = ffmpeg.video_size(path)
    except (ValueError, ffmpeg.FFmpegError):
        return False
    if abs(width / height - aw / ah) < 0.02:
        return False
    if width / height > aw / ah:
        cw, ch = round(height * aw / ah) // 2 * 2, height
    else:
        cw, ch = width, round(width * ah / aw) // 2 * 2
    tmp = path.with_name(f"{path.stem}.fit{path.suffix}")
    try:
        ffmpeg.run(["-i", path, "-vf", f"crop={cw}:{ch}", "-frames:v", "1", tmp])
    except ffmpeg.FFmpegError:
        return False
    tmp.replace(path)
    return True
