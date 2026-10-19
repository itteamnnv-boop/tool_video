"""Engine tạo video cho template video AI — chọn theo Provider AI người dùng đang dùng.

Mỗi engine khai báo giới hạn (thời lượng, độ phân giải, tỉ lệ, số ảnh tham chiếu) để UI hiện đúng lựa chọn
và orchestrator chuẩn hoá tuỳ chọn của template trước khi gửi.
"""
from pathlib import Path

ENGINES = {
    "grok_browser": {
        "name": "Grok Imagine (trình duyệt)",
        "durations": ["6s", "10s", "15s"], "resolutions": ["480p", "720p", "1080p"],
        "aspects": ["9:16", "16:9", "1:1", "2:3", "3:2"], "max_images": 10,
        "video_input": True,  # ô đính kèm nhận được file video (template có attachment keep_video)
        "note": "Cần đăng nhập grok.com (Provider Grok Browser → Đăng nhập).",
    },
    "gemini_browser": {
        "name": "Gemini · Veo (trình duyệt)",
        "durations": ["8s"], "resolutions": ["720p"], "aspects": ["9:16", "16:9"], "max_images": 3,
        "note": "Dùng công cụ 'Tạo video' (Veo) của tài khoản Gemini; không có Veo thì tự chuyển sang video thông thường. "
                "Gửi kèm tối đa 3 ảnh tham chiếu (nhật ký báo nếu Gemini nhận thiếu).",
        "regular_mode": True,  # có thể chọn 'Video thông thường' (Gemini viết kịch bản, app tự dựng)
    },
    "dola_browser": {
        "name": "Dola · Seedance (trình duyệt)",
        "durations": ["5s", "10s"], "resolutions": ["720p"],
        "aspects": ["9:16", "16:9", "1:1", "3:4", "4:3", "21:9"], "max_images": 4, "video_input": True,
        "note": "Dùng AI Creation → Video của dola.com (Seedance). Cần đăng nhập Dola (Provider Dola Browser → Đăng nhập).",
    },
    "muse_browser": {
        "name": "Meta · Muse Video (trình duyệt)",
        "durations": ["5s", "10s"], "resolutions": ["720p"], "aspects": ["9:16", "16:9", "1:1"], "max_images": 3,
        "note": "Trợ lý Muse của Meta (muse.ai). Muse Video đang mở dần — tài khoản chưa có thì Muse chỉ trả lời "
                "bằng chữ và app báo lỗi rõ. Cần đăng nhập Muse trong Profile trình duyệt.",
    },
    "gemini_api": {
        "name": "Gemini · Veo (API key)",
        "durations": ["4s", "6s", "8s"], "resolutions": ["720p", "1080p"], "aspects": ["9:16", "16:9"], "max_images": 3,
        "note": "Dùng Gemini API key trong Cài đặt (tính phí theo giây video). Tối đa 3 ảnh tham chiếu.",
    },
}


def _seconds(value: str) -> int:
    return int(str(value).rstrip("s") or 0)


def normalize_options(engine: str, options: dict) -> dict:
    """Đưa tuỳ chọn của template về giá trị engine hỗ trợ (thời lượng gần nhất không vượt quá, v.v.)."""
    spec = ENGINES[engine]
    out = dict(options)
    want = _seconds(options.get("duration") or spec["durations"][-1])
    fitting = [d for d in spec["durations"] if _seconds(d) <= want]
    out["duration"] = fitting[-1] if fitting else spec["durations"][0]
    if options.get("resolution") not in spec["resolutions"]:
        out["resolution"] = "720p" if "720p" in spec["resolutions"] else spec["resolutions"][-1]
    if options.get("aspect") not in spec["aspects"]:
        out["aspect"] = "9:16" if "9:16" in spec["aspects"] else spec["aspects"][0]
    return out


def generate(engine: str, prompt: str, out_path: Path, *, options: dict, images: list[Path], settings,
             show_browser: bool, log, check_cancel, on_progress) -> None:
    common = dict(aspect=options["aspect"], duration=options["duration"], resolution=options["resolution"],
                  images=images, log=log, check_cancel=check_cancel, on_progress=on_progress)
    if engine == "grok_browser":
        from .grok_imagine import generate_video
        generate_video(prompt, out_path, channel=settings.get("browser_channel"), show_browser=show_browser, **common)
    elif engine == "gemini_browser":
        from .gemini_veo import generate_video_browser
        generate_video_browser(prompt, out_path, channel=settings.get("browser_channel"), show_browser=show_browser,
                               **common)
    elif engine == "dola_browser":
        from .dola_video import generate_video as dola_generate
        dola_generate(prompt, out_path, channel=settings.get("browser_channel"), show_browser=show_browser, **common)
    elif engine == "muse_browser":
        from .muse_browser import muse_video
        muse_video(prompt, out_path, channel=settings.get("browser_channel"), show_browser=show_browser, **common)
    elif engine == "gemini_api":
        from .gemini_veo import generate_video_api
        generate_video_api(prompt, out_path, api_key=settings.get("gemini_api_key"), model=settings.get("veo_model"),
                           **common)
    else:
        raise ValueError(f"Engine không hỗ trợ: {engine}")
