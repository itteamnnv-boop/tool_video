"""Model AI dùng chung (Cài đặt → Model AI): cài 1 lần, mọi màn hình dùng chung.
Trang đặc thù (Studio Muse AI, Seedance, Workflow từng nút…) giữ lựa chọn riêng, không đi qua đây."""

# khoá tuỳ chọn dự án Studio → khoá cài đặt chung
STUDIO_KEYS = {"model": "model_text", "text_profile": "model_text_profile",
               "image_engine": "model_image", "image_profile": "model_image_profile",
               "video_engine": "model_video", "video_profile": "model_video_profile",
               "post_model": "model_post", "post_profile": "model_post_profile"}
FALLBACK = {"model_text": "chatgpt_browser", "model_video": "grok_browser", "model_post": "claude_browser",
            "model_vision": "gemini_browser"}


def get(settings) -> dict:
    """Bộ model đang cài; model ảnh trống → model của lần Tạo hình ảnh gần nhất (hoặc GPT Image API)."""
    out = {key: str(settings.get(key) or "") or FALLBACK.get(key, "") for key in (*STUDIO_KEYS.values(), "model_vision")}
    out["model_image"] = out["model_image"] or (settings.get("last_image_form") or {}).get("engine") or "openai_api"
    return out


def apply_studio(options: dict, settings) -> dict:
    """Ghi đè model của dự án Studio bằng model dùng chung (dự án cũ cũng theo cài đặt mới)."""
    prefs = get(settings)
    return {**options, **{opt: prefs[key] for opt, key in STUDIO_KEYS.items()}}
