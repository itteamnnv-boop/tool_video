"""🔑 Chế độ model: mặc định CHỈ dùng model trên trình duyệt (tài khoản đã đăng nhập) — mọi model chạy bằng API key bị ẩn
và không được dùng. Bật lại ở Cài đặt → Model AI dùng chung → “Dùng model qua API key” (khoá setting use_api_models).

Khi tắt:
  • settings.get("<…>_api_key") trả "" (khoá đã lưu vẫn giữ trong file, không gửi giao diện) — campaign.ai.get_key
    cũng bỏ biến môi trường → không chỗ nào gọi được API
  • danh sách model (ảnh / video / chữ / ô chọn của khối) bỏ lựa chọn API
  • cấu hình cũ đang chọn model API → chạy bằng bản trình duyệt cùng hãng (browser_equiv), ghi nhật ký
"""
from __future__ import annotations

# model API → bản trình duyệt cùng hãng
EQUIV = {"claude_api": "claude_browser", "gemini_api": "gemini_browser", "openai_api": "chatgpt_browser"}
# ô cấu hình chứa model (khối Canvas / Workflow, cài đặt dùng chung)
MODEL_KEYS = ("provider", "model", "engine", "image_engine", "video_engine", "post_model", "analyze_model",
              "text_model", "vision_model", "story_model")


def enabled(settings=None) -> bool:
    if settings is None:
        from .config import settings as s

        settings = s
    data = getattr(settings, "_data", None)
    return bool(data.get("use_api_models", False)) if isinstance(data, dict) else bool(settings.get("use_api_models"))


def is_api(value) -> bool:
    v = str(value or "")
    return v in EQUIV or v.startswith("api:") or v.endswith("_api")


def browser_equiv(value) -> str:
    """Model API → bản trình duyệt cùng hãng (Claude → Claude, GPT / OpenAI → ChatGPT, Gemini / Veo → Gemini)."""
    v = str(value or "")
    if v in EQUIV:
        return EQUIV[v]
    low = v.lower()
    if "claude" in low or "anthropic" in low:
        return "claude_browser"
    if "gemini" in low or "veo" in low or "imagen" in low:
        return "gemini_browser"
    return "chatgpt_browser"


def engines(table: dict, settings=None) -> dict:
    """Bảng model (ảnh / video) cho giao diện: tắt API → bỏ model API."""
    return table if enabled(settings) else {k: v for k, v in table.items() if not is_api(k)}


def text_models(items: list, settings=None) -> list:
    return items if enabled(settings) else [m for m in items if not is_api(m.get("id"))]


def pick(value, table: dict | None = None, settings=None):
    """1 model đang chọn: tắt API mà đang là model API → bản trình duyệt (nếu bảng có)."""
    if enabled(settings) or not is_api(value):
        return value
    eq = browser_equiv(value)
    return eq if table is None or eq in table else next((k for k in table if not is_api(k)), value)


def fields(items: list, settings=None) -> list:
    """Ô cấu hình của khối: bỏ lựa chọn model API; mặc định là model API → bản trình duyệt."""
    if enabled(settings):
        return items
    out = []
    for f in items:
        opts = f.get("options")
        if isinstance(opts, list) and any(is_api(o.get("value")) for o in opts if isinstance(o, dict)):
            keep = [o for o in opts if not (isinstance(o, dict) and is_api(o.get("value")))]
            values = {o.get("value") for o in keep if isinstance(o, dict)}
            default = f.get("default")
            if is_api(default):
                eq = browser_equiv(default)
                default = eq if eq in values else (keep[0].get("value") if keep else "")
            f = {**f, "options": keep, "default": default}
        out.append(f)
    return out


def settings_view(data: dict, settings=None) -> dict:
    """Cài đặt gửi giao diện: model dùng chung (model_text / model_image …) đang là model API → hiện bản trình duyệt."""
    if enabled(settings):
        return data
    out = dict(data)
    for k, v in data.items():
        if k.startswith("model_") and not k.endswith("_profile") and is_api(v):
            out[k] = browser_equiv(v)
    form = out.get("last_image_form")
    if isinstance(form, dict) and is_api(form.get("engine")):
        out["last_image_form"] = {**form, "engine": browser_equiv(form["engine"])}
    return out


def config(cfg: dict, settings=None, log=None) -> dict:
    """Cấu hình khối khi CHẠY: tắt API → mọi ô model đang là model API đổi sang bản trình duyệt (ghi nhật ký)."""
    if enabled(settings) or not isinstance(cfg, dict):
        return cfg
    out = dict(cfg)
    for k in MODEL_KEYS:
        if is_api(out.get(k)):
            new = browser_equiv(out[k])
            if log:
                log(f"Chỉ dùng model trình duyệt: {out[k]} → {new}", "warn")
            out[k] = new
    return out
