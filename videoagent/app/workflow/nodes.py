"""Định nghĩa các block của Workflow (cổng vào/ra, ô cấu hình) và cách chạy từng block.

Kiểu dữ liệu trên cổng: text (chuỗi), images (danh sách ảnh), video (file video), any (block Kết quả).
Một cổng vào nhận được nhiều dây ("multi"): văn bản nối bằng dòng trống, ảnh/video gộp thành danh sách.
Giao diện dựng form cấu hình từ "fields" — chỉ cần khai báo ở đây.
"""
import json
import shutil
from pathlib import Path

from ..content_writer import BROWSER_MODELS, CLAUDE_MODELS as CONTENT_CLAUDE, DEFAULT_TEMPLATE as CONTENT_TEMPLATE
from ..content_writer import FIELDS as CONTENT_FIELDS, OPENAI_MODELS as CONTENT_OPENAI
from ..llm.image_engines import ENGINES as IMAGE_ENGINES
from ..llm.video_engines import ENGINES as VIDEO_ENGINES
from ..pipeline.tts import RATES as TTS_RATES, VOICES as TTS_VOICES

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
TEXT_PROVIDERS = {
    "claude_api": "Claude API (Anthropic)",
    "gemini_api": "Gemini API (API key)",
    "gemini_browser": "Gemini (trình duyệt)",
    "grok_browser": "Grok (trình duyệt)",
    "chatgpt_browser": "ChatGPT (trình duyệt)",
    "claude_browser": "Claude (trình duyệt)",
    "muse_browser": "Meta · Muse (trình duyệt)",
}
CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# Block Tạo content bài viết: cùng danh sách model với app/content_writer.py
CONTENT_MODELS = {**{k: f"{v} (trình duyệt)" for k, v in BROWSER_MODELS.items()}, "gemini_api": "Gemini API (API key)",
                  **{f"api:{m}": f"Claude · {m}" for m in CONTENT_CLAUDE}, **{f"api:{m}": f"OpenAI · {m}" for m in CONTENT_OPENAI}}
# Block Tạo ảnh: vai trò từng ảnh gửi kèm (ghi vào cuối prompt theo đúng thứ tự tải lên model)
INPUT_ROLES = {
    "product": {"label": "Ảnh sản phẩm (giữ nguyên sản phẩm)", "role": "product photo",
                "prompt": "keep this exact product — packaging, logo, label text, colors and proportions must stay identical"},
    "general": {"label": "Ảnh tham chiếu chung", "role": "reference image",
                "prompt": "use it as a visual reference for subject, style and composition"},
}
REF_ROLES = {
    "model": {"label": "Người mẫu / nhân vật", "role": "model reference",
              "prompt": "use this person (face, hair, body type) as the model in the new image"},
    "style": {"label": "Phong cách / bố cục / màu sắc", "role": "style reference",
              "prompt": "use it only for composition, pose, lighting, colors and mood — do not copy its content, text or logos"},
    "scene": {"label": "Bối cảnh / nền", "role": "background reference",
              "prompt": "use this place as the background setting"},
    "general": {"label": "Tham chiếu chung", "role": "reference image",
                "prompt": "use it as a visual reference for subject, style and composition"},
}


# Block Đăng bài / Lên lịch: kiểu đăng
POST_TYPES = {
    "feed": "Ảnh/video kèm bài viết (feed)",
    "text": "Chỉ bài viết (chữ)",
    "media": "Chỉ ảnh/video (không chữ)",
    "reel": "Reels (video dọc)",
    "story": "Story (ảnh/video hiện 24 giờ)",
}
SCHEDULABLE = ("feed", "text", "media", "reel")  # Facebook không cho hẹn giờ Story
SOURCE_PORT = {"text": "caption", "images": "media", "video": "media"}  # tài nguyên từ flow → cổng của block Đăng bài


def virtual_edges(wf: dict) -> dict:
    """Tài nguyên tick trong block Đăng bài (config.sources = [{node, port}]) → dây ảo tới cổng Caption / Ảnh-video.
    Runner dùng như dây thật: thứ tự chạy, bỏ qua khi block nguồn lỗi, chạy thử dùng lại kết quả."""
    nodes = {n["id"]: n for n in wf.get("nodes") or []}
    edges = [e for e in wf.get("edges") or [] if not e.get("virtual")]
    seen = {(e["from"], e["out"], e["to"], e["in"]) for e in edges}
    for n in nodes.values():
        if n["type"] not in ("fb_post", "fb_schedule"):
            continue
        for src in (n.get("config") or {}).get("sources") or []:
            other = nodes.get(str((src or {}).get("node")))
            if not other or other["id"] == n["id"]:
                continue
            out = next((o for o in NODE_TYPES[other["type"]]["outputs"] if o["key"] == src.get("port")), None)
            if not out or out["type"] not in SOURCE_PORT:
                continue
            key = (other["id"], out["key"], n["id"], SOURCE_PORT[out["type"]])
            if key not in seen:
                seen.add(key)
                edges.append({"from": key[0], "out": key[1], "to": key[2], "in": key[3], "virtual": True})
    return {**wf, "edges": edges}


def _opts(mapping: dict) -> list:
    return [{"value": k, "label": v if isinstance(v, str) else v["name"]} for k, v in mapping.items()]


def _transition_opts(kind: str) -> list:
    from ..pipeline import transitions

    return transitions.options()[kind]


def _transition_keys() -> list:
    from ..pipeline import transitions

    return list(transitions.TRANSITIONS)


def _sound_keys() -> list:
    from ..pipeline import transitions

    return list(transitions.SOUNDS)


def _union(key: str) -> list:
    seen = []
    for spec in VIDEO_ENGINES.values():
        seen += [v for v in spec[key] if v not in seen]
    return seen


NODE_TYPES = {
    # ------------------------------------------------------------------ đầu vào
    "input_text": {
        "name": "Văn bản / Prompt", "group": "input", "icon": "✎", "desc": "Ý tưởng, mô tả sản phẩm hoặc prompt",
        "inputs": [], "outputs": [{"key": "text", "type": "text", "label": "Văn bản"}],
        "fields": [
            {"key": "label", "label": "Tên biến (hiện khi chạy)", "type": "text", "default": "Nội dung"},
            {"key": "text", "label": "Nội dung", "type": "textarea", "default": ""},
            {"key": "ask", "label": "Hỏi lại khi chạy (đổi input → chạy lại)", "type": "check", "default": True},
        ],
    },
    "input_image": {
        "name": "Ảnh đầu vào", "group": "input", "icon": "🖼", "desc": "Ảnh sản phẩm, nhân vật, ảnh tham chiếu",
        "inputs": [], "outputs": [{"key": "images", "type": "images", "label": "Ảnh"}],
        "fields": [
            {"key": "label", "label": "Tên biến (hiện khi chạy)", "type": "text", "default": "Ảnh"},
            {"key": "files", "label": "Ảnh", "type": "files", "kind": "images_multi", "default": []},
            {"key": "ask", "label": "Hỏi lại khi chạy", "type": "check", "default": True},
        ],
    },
    "input_video": {
        "name": "Video đầu vào", "group": "input", "icon": "🎞", "desc": "Video có sẵn để ghép nối",
        "inputs": [], "outputs": [{"key": "video", "type": "video", "label": "Video"}],
        "fields": [
            {"key": "label", "label": "Tên biến", "type": "text", "default": "Video"},
            {"key": "files", "label": "Video", "type": "files", "kind": "media", "default": [], "single": True},
            {"key": "ask", "label": "Hỏi lại khi chạy", "type": "check", "default": False},
        ],
    },
    # ------------------------------------------------------------------ AI xử lý
    "ai_text": {
        "name": "AI viết / xử lý", "group": "ai", "icon": "✦", "desc": "Viết kịch bản, prompt ảnh/video từ đầu vào",
        "inputs": [{"key": "text", "type": "text", "label": "Văn bản", "multi": True},
                   {"key": "images", "type": "images", "label": "Ảnh (tuỳ chọn)", "multi": True}],
        "outputs": [{"key": "text", "type": "text", "label": "Kết quả"}],
        "fields": [
            {"key": "provider", "label": "Model AI", "type": "select", "options": _opts(TEXT_PROVIDERS), "default": "claude_api"},
            {"key": "model", "label": "Model Claude", "type": "select", "default": "claude-opus-5-5",
             "options": [{"value": m, "label": m} for m in CLAUDE_MODELS], "when": {"provider": ["claude_api"]}},
            {"key": "prompt", "label": "Yêu cầu (dùng {{input}} để chèn văn bản đầu vào)", "type": "textarea",
             "default": "Viết 1 prompt tạo video quảng cáo ngắn, dọc 9:16, lời thoại tiếng Việt, cho nội dung sau:\n{{input}}\n\n"
                        "Chỉ trả về prompt, không giải thích."},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False,
             "when": {"provider": ["gemini_browser", "grok_browser", "chatgpt_browser", "claude_browser", "muse_browser"]}},
        ],
    },
    "content_post": {
        "name": "Tạo content bài viết", "group": "ai", "icon": "📝",
        "desc": "Viết bài đăng bán hàng theo mẫu, đúng thông tin sản phẩm (tự kiểm tra giá, SĐT, website, địa chỉ)",
        "inputs": [{"key": "info", "type": "text", "label": "Thông tin sản phẩm (tuỳ chọn)", "multi": True}],
        "outputs": [{"key": "text", "type": "text", "label": "Bài viết"}],
        "fields": [
            {"key": "model", "label": "Model viết bài", "type": "select", "default": "chatgpt_browser",
             "options": [{"value": k, "label": v} for k, v in CONTENT_MODELS.items()]},
            *[{"key": f"sp_{k}", "label": label + (" *" if need else ""),
               "type": "textarea" if k in ("benefits", "problem", "notes") else "text", "default": ""}
              for k, (label, need) in CONTENT_FIELDS.items()],
            {"key": "template", "label": "Mẫu bài viết (AI bắt chước bố cục, emoji, giọng văn)", "type": "textarea",
             "default": CONTENT_TEMPLATE},
            {"key": "extra", "label": "Yêu cầu thêm (tuỳ chọn)", "type": "text", "default": ""},
            {"key": "strict", "label": "Dừng workflow nếu bài vẫn sai thông tin sau 1 lần viết lại", "type": "check",
             "default": True},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False,
             "when": {"model": [k for k in CONTENT_MODELS if k.endswith("_browser")]}},
        ],
    },
    # ------------------------------------------------------------------ tạo nội dung
    "gen_image": {
        "name": "Tạo ảnh", "group": "create", "icon": "◩", "desc": "OpenAI / Gemini / Grok / Dola vẽ ảnh",
        "inputs": [{"key": "prompt", "type": "text", "label": "Prompt", "multi": True},
                   {"key": "images", "type": "images", "label": "Ảnh sản phẩm", "multi": True},
                   {"key": "keyword", "type": "text", "label": "Từ khoá Pinterest", "multi": True}],
        "outputs": [{"key": "images", "type": "images", "label": "Ảnh"}],
        "fields": [
            {"key": "engine", "label": "Model tạo ảnh", "type": "select", "options": _opts(IMAGE_ENGINES), "default": "grok_browser"},
            {"key": "prompt", "label": "Prompt (thêm sau prompt đầu vào)", "type": "textarea", "default": ""},
            {"key": "input_role", "label": "Ảnh nối vào cổng “Ảnh sản phẩm” là", "type": "select", "default": "product",
             "options": [{"value": k, "label": v["label"]} for k, v in INPUT_ROLES.items()]},
            {"key": "refs", "label": "Ảnh tham chiếu đính kèm", "type": "files", "kind": "images_multi", "default": []},
            {"key": "ref_role", "label": "Ảnh tham chiếu dùng để", "type": "select", "default": "model", "when": {"refs": "*"},
             "options": [{"value": k, "label": v["label"]} for k, v in REF_ROLES.items()]},
            {"key": "aspect", "label": "Tỉ lệ", "type": "select", "default": "9:16",
             "options": [{"value": a, "label": a} for a in ["9:16", "16:9", "1:1", "4:5", "2:3", "3:2"]]},
            {"key": "count", "label": "Số ảnh", "type": "select", "default": "1",
             "options": [{"value": str(n), "label": str(n)} for n in (1, 2, 4)]},
            {"key": "pinterest", "label": "Tham khảo ảnh tìm trên Pinterest", "type": "check", "default": False},
            {"key": "pin_keyword", "label": "Từ khoá tìm (nên dùng tiếng Anh; trống = lấy theo prompt)", "type": "text",
             "default": "", "when": {"pinterest": [True]}},
            {"key": "pin_count", "label": "Số ảnh tham khảo", "type": "select", "default": "3", "when": {"pinterest": [True]},
             "options": [{"value": str(n), "label": str(n)} for n in range(1, 7)]},
            {"key": "pin_urls", "label": "Ảnh Pinterest đã chọn", "type": "pinterest", "default": [], "when": {"pinterest": [True]}},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False},
        ],
    },
    "gen_video": {
        "name": "Tạo video", "group": "create", "icon": "▶", "desc": "Grok Imagine / Veo / Seedance tạo video",
        "inputs": [{"key": "prompt", "type": "text", "label": "Prompt", "multi": True},
                   {"key": "images", "type": "images", "label": "Ảnh tham chiếu", "multi": True},
                   {"key": "videos", "type": "video", "label": "Video tham chiếu", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video"}],
        "fields": [
            {"key": "engine", "label": "Model tạo video", "type": "select", "options": _opts(VIDEO_ENGINES), "default": "grok_browser"},
            {"key": "template", "label": "Template video", "type": "video_template", "default": ""},
            {"key": "att", "label": "Ảnh / video template yêu cầu", "type": "template_files", "default": {}, "when": {"template": "*"}},
            {"key": "vars", "label": "Thông tin template yêu cầu", "type": "template_vars", "default": {}, "when": {"template": "*"}},
            {"key": "prompt_override", "label": "Prompt & quy trình của template", "type": "template_flow", "default": "",
             "when": {"template": "*"}},
            {"key": "var_input", "label": "Văn bản từ dây Prompt điền vào biến", "type": "template_var", "default": "",
             "when": {"template": "*"}},
            {"key": "ask_vars", "label": "Hỏi các thông tin template khi chạy workflow", "type": "check", "default": False,
             "when": {"template": "*"}},
            {"key": "prompt", "label": "Prompt (thêm sau prompt đầu vào / ghi chú thêm cho template)", "type": "textarea", "default": ""},
            {"key": "aspect", "label": "Tỉ lệ", "type": "select", "default": "9:16",
             "options": [{"value": a, "label": a} for a in _union("aspects")]},
            {"key": "duration", "label": "Thời lượng", "type": "select", "default": "10s",
             "options": [{"value": d, "label": d} for d in sorted(_union("durations"), key=lambda s: int(s.rstrip("s")))]},
            {"key": "resolution", "label": "Độ phân giải", "type": "select", "default": "720p",
             "options": [{"value": r, "label": r} for r in _union("resolutions")]},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False},
        ],
    },
    "concat_video": {
        "name": "Ghép video", "group": "create", "icon": "⧉", "desc": "Nối nhiều video thành 1 (theo thứ tự dây nối)",
        "inputs": [{"key": "videos", "type": "video", "label": "Video", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video ghép"}],
        "fields": [{"key": "aspect", "label": "Khung hình", "type": "select", "default": "9:16",
                    "options": [{"value": a, "label": a} for a in ["9:16", "16:9", "1:1"]]},
                   {"key": "transition", "label": "Chuyển cảnh", "type": "select", "default": "none",
                    "options": _transition_opts("transitions")},
                   {"key": "transition_duration", "label": "Thời lượng chuyển cảnh", "type": "select", "default": "0.5",
                    "options": [{"value": str(d), "label": f"{d} giây"} for d in (0.3, 0.5, 0.8, 1.0)],
                    "when": {"transition": [k for k in _transition_keys() if k != "none"]}},
                   {"key": "transition_sound", "label": "Âm chuyển cảnh", "type": "select", "default": "none",
                    "options": _transition_opts("sounds")},
                   {"key": "transition_volume", "label": "Âm lượng âm chuyển cảnh (0–1.5)", "type": "number", "default": "0.6",
                    "when": {"transition_sound": [k for k in _sound_keys() if k != "none"]}}],
    },
    "studio_video": {
        "name": "Video dài từ storyboard", "group": "create", "icon": "🎬",
        "desc": "Như màn Studio: ý tưởng → storyboard → ảnh + clip từng cảnh → giọng đọc, phụ đề, nhạc, chuyển cảnh, "
                "hậu kỳ AI → video 30–90 giây",
        "inputs": [{"key": "idea", "type": "text", "label": "Ý tưởng", "multi": True},
                   {"key": "images", "type": "images", "label": "Ảnh tham chiếu", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video"},
                    {"key": "text", "type": "text", "label": "Lời dẫn"}],
        "fields": [
            {"key": "idea", "label": "Ý tưởng (thêm sau văn bản nối vào cổng Ý tưởng)", "type": "textarea", "default": ""},
            {"key": "name", "label": "Tên dự án Studio (tuỳ chọn)", "type": "text", "default": ""},
            {"key": "preset", "label": "Lấy toàn bộ cài đặt từ dự án Studio (logo, ràng buộc prompt, profile, hậu kỳ…)",
             "type": "studio_preset", "default": ""},
            {"key": "length", "label": "Độ dài video", "type": "select", "default": "60", "when": {"preset": [""]},
             "options": [{"value": str(n), "label": f"~{n} giây"} for n in (30, 45, 60, 75, 90)]},
            {"key": "style", "label": "Phong cách hình ảnh (tuỳ chọn)", "type": "text", "default": "", "when": {"preset": [""]}},
            {"key": "prompt_polish", "label": "✨ Chuốt prompt từng cảnh bằng AI (thêm 1 lượt hỏi model)", "type": "check",
             "default": False, "when": {"preset": [""]}},
            {"key": "aspect", "label": "Tỉ lệ khung hình", "type": "select", "default": "9:16", "when": {"preset": [""]},
             "options": [{"value": "9:16", "label": "Dọc 9:16 — TikTok, Reels"}, {"value": "16:9", "label": "Ngang 16:9 — YouTube"},
                         {"value": "1:1", "label": "Vuông 1:1"}]},
            {"key": "quality", "label": "Chất lượng clip", "type": "select", "default": "720p", "when": {"preset": [""]},
             "options": [{"value": q, "label": q} for q in ("480p", "720p", "1080p")]},
            {"key": "model", "label": "Model viết storyboard", "type": "select", "default": "chatgpt_browser",
             "options": [{"value": k, "label": v} for k, v in CONTENT_MODELS.items()], "when": {"preset": [""]}},
            {"key": "image_engine", "label": "Model ảnh khung đầu", "type": "select", "default": "chatgpt_browser",
             "options": _opts(IMAGE_ENGINES), "when": {"preset": [""]}},
            {"key": "scene_style", "label": "Kiểu dựng cảnh", "type": "select", "default": "video",
             "options": [{"value": "video", "label": "Clip video AI (ảnh khung đầu → model video)"},
                         {"value": "whiteboard", "label": "Whiteboard vẽ tay (line-art, dựng trên máy)"}],
             "when": {"preset": [""]}},
            {"key": "video_engine", "label": "Model video từng cảnh", "type": "select", "default": "grok_browser",
             "options": _opts(VIDEO_ENGINES), "when": {"preset": [""], "scene_style": ["video"]}},
            {"key": "dub", "label": "Lồng tiếng AI (tắt = dùng giọng nói gốc của clip)", "type": "check", "default": True,
             "when": {"preset": [""]}},
            {"key": "voice", "label": "Giọng đọc", "type": "select", "default": "vi-VN-HoaiMyNeural",
             "options": [{"value": v["id"], "label": v["name"]} for v in TTS_VOICES], "when": {"preset": [""], "dub": [True]}},
            {"key": "rate", "label": "Tốc độ đọc", "type": "select", "default": "+0%",
             "options": [{"value": r, "label": r} for r in TTS_RATES], "when": {"preset": [""], "dub": [True]}},
            {"key": "subtitles", "label": "Phụ đề", "type": "check", "default": True, "when": {"preset": [""]}},
            {"key": "bgm", "label": "Nhạc nền", "type": "check", "default": True, "when": {"preset": [""]}},
            {"key": "transition", "label": "Chuyển cảnh", "type": "select", "default": "fade",
             "options": _transition_opts("transitions"), "when": {"preset": [""]}},
            {"key": "transition_sound", "label": "Âm chuyển cảnh", "type": "select", "default": "whoosh",
             "options": _transition_opts("sounds"), "when": {"preset": [""]}},
            {"key": "post_ai", "label": "✨ Hậu kỳ AI (phụ đề + âm thanh nổi bật)", "type": "check", "default": False,
             "when": {"preset": [""]}},
            {"key": "post_model", "label": "Model hậu kỳ", "type": "select", "default": "claude_browser",
             "options": [{"value": k, "label": v} for k, v in CONTENT_MODELS.items()],
             "when": {"preset": [""], "post_ai": [True]}},
            {"key": "post_style", "label": "Kiểu hậu kỳ", "type": "select", "default": "basic",
             "options": [{"value": "basic", "label": "Cơ bản — phụ đề tô nổi từ khoá"},
                         {"value": "hyperframes", "label": "HyperFrames — đồ hoạ động (cần Node.js 22+)"}],
             "when": {"preset": [""], "post_ai": [True]}},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False},
        ],
    },
    "whiteboard_video": {
        "name": "Whiteboard từ SRT / kịch bản", "group": "create", "icon": "✍",
        "desc": "Phụ đề SRT hoặc kịch bản → tranh line-art vẽ tay, bàn tay vẽ từng ý đúng lúc lời đọc "
                "(srt-whiteboard-animation, dựng trên máy)",
        "inputs": [{"key": "text", "type": "text", "label": "SRT / kịch bản", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video"},
                    {"key": "text", "type": "text", "label": "Lời đọc"}],
        "fields": [
            {"key": "text", "label": "SRT hoặc kịch bản (dùng khi không nối dây / thêm sau văn bản nối vào)",
             "type": "textarea", "default": ""},
            {"key": "srt", "label": "Hoặc file phụ đề .srt", "type": "files", "kind": "srt", "default": [], "single": True},
            {"key": "audio", "label": "Âm thanh lời đọc khớp SRT (trống = giọng AI)", "type": "files", "kind": "audio",
             "default": [], "single": True},
            {"key": "image_engine", "label": "Model vẽ ảnh line-art", "type": "select", "default": "gemini_browser",
             "options": _opts(IMAGE_ENGINES)},
            {"key": "aspect", "label": "Tỉ lệ", "type": "select", "default": "16:9",
             "options": [{"value": a, "label": a} for a in ("16:9", "9:16", "1:1")]},
            {"key": "voice", "label": "Giọng đọc AI", "type": "select", "default": "vi-VN-HoaiMyNeural",
             "options": [{"value": v["id"], "label": v["name"]} for v in TTS_VOICES]},
            {"key": "rate", "label": "Tốc độ đọc", "type": "select", "default": "+0%",
             "options": [{"value": r, "label": r} for r in TTS_RATES]},
            {"key": "quality", "label": "Chất lượng dựng", "type": "select", "default": "fast",
             "options": [{"value": "fast", "label": "Nhanh — cạnh dài 1080px"},
                         {"value": "hd", "label": "Nét — 1920px (~3 lần lâu hơn)"}]},
            {"key": "hint", "label": "Gợi ý phong cách hình (tuỳ chọn)", "type": "text", "default": ""},
            {"key": "hand", "label": "Hiện bàn tay cầm bút", "type": "check", "default": True},
            {"key": "subtitles", "label": "Chèn phụ đề", "type": "check", "default": True},
            {"key": "show_browser", "label": "Hiện trình duyệt", "type": "check", "default": False},
        ],
    },
    # ------------------------------------------------------------------ đầu ra: Facebook
    "fb_post": {
        "name": "Đăng bài Facebook", "group": "output", "icon": "📣",
        "desc": "Đăng feed (ảnh/video kèm bài viết, chỉ chữ, chỉ ảnh/video), Reels hoặc Story lên Fanpage",
        "inputs": [{"key": "caption", "type": "text", "label": "Caption", "multi": True},
                   {"key": "media", "type": "any", "label": "Ảnh / video", "multi": True}],
        "outputs": [{"key": "post", "type": "post", "label": "Bài viết"}],
        "fields": [
            {"key": "page_id", "label": "Fanpage", "type": "fb_page", "default": ""},
            {"key": "post_type", "label": "Kiểu đăng", "type": "select", "default": "feed",
             "options": [{"value": k, "label": v} for k, v in POST_TYPES.items()]},
            {"key": "sources", "label": "Tài nguyên từ flow (tick để dùng — không cần nối dây)", "type": "flow_sources",
             "default": []},
            {"key": "caption", "label": "Caption (thêm sau caption đầu vào)", "type": "textarea", "default": "",
             "when": {"post_type": ["feed", "text", "reel"]}},
            {"key": "confirm", "label": "Duyệt trước khi đăng (dừng chờ bạn bấm Đồng ý)", "type": "check", "default": True},
        ],
    },
    "fb_schedule": {
        "name": "Lên lịch đăng bài", "group": "output", "icon": "🗓", "desc": "Hẹn giờ Facebook tự đăng feed hoặc Reels",
        "inputs": [{"key": "caption", "type": "text", "label": "Caption", "multi": True},
                   {"key": "media", "type": "any", "label": "Ảnh / video", "multi": True}],
        "outputs": [{"key": "post", "type": "post", "label": "Bài hẹn giờ"}],
        "fields": [
            {"key": "page_id", "label": "Fanpage", "type": "fb_page", "default": ""},
            {"key": "post_type", "label": "Kiểu đăng", "type": "select", "default": "feed",
             "options": [{"value": k, "label": v} for k, v in POST_TYPES.items() if k in SCHEDULABLE]},
            {"key": "sources", "label": "Tài nguyên từ flow (tick để dùng — không cần nối dây)", "type": "flow_sources",
             "default": []},
            {"key": "mode", "label": "Thời điểm đăng", "type": "select", "default": "delay",
             "options": [{"value": "delay", "label": "Sau một khoảng thời gian"}, {"value": "at", "label": "Vào ngày giờ cụ thể"}]},
            {"key": "delay_hours", "label": "Đăng sau (giờ)", "type": "number", "default": "2", "when": {"mode": ["delay"]}},
            {"key": "publish_at", "label": "Ngày giờ đăng", "type": "datetime", "default": "", "when": {"mode": ["at"]}},
            {"key": "caption", "label": "Caption (thêm sau caption đầu vào)", "type": "textarea", "default": "",
             "when": {"post_type": ["feed", "text", "reel"]}},
            {"key": "confirm", "label": "Duyệt trước khi hẹn giờ", "type": "check", "default": True},
        ],
    },
    "fb_ad": {
        "name": "Tạo quảng cáo", "group": "output", "icon": "🎯", "desc": "Chạy quảng cáo cho bài vừa đăng (tạo ở trạng thái tạm dừng)",
        "inputs": [{"key": "post", "type": "post", "label": "Bài viết"}],
        "outputs": [{"key": "ad", "type": "text", "label": "Quảng cáo"}],
        "fields": [
            {"key": "account_id", "label": "Tài khoản quảng cáo", "type": "ad_account", "default": ""},
            {"key": "objective", "label": "Mục tiêu", "type": "select", "default": "engagement",
             "options": [{"value": "engagement", "label": "Tương tác bài viết"}, {"value": "reach", "label": "Tiếp cận nhiều người"},
                         {"value": "video", "label": "Lượt xem video (ThruPlay)"}]},
            {"key": "daily_budget", "label": "Ngân sách mỗi ngày (theo tiền tệ tài khoản)", "type": "number", "default": "100000"},
            {"key": "days", "label": "Số ngày chạy", "type": "number", "default": "7"},
            {"key": "countries", "label": "Quốc gia (mã, cách nhau dấu phẩy)", "type": "text", "default": "VN"},
            {"key": "age_min", "label": "Tuổi từ", "type": "number", "default": "22"},
            {"key": "age_max", "label": "Tuổi đến", "type": "number", "default": "55"},
            {"key": "gender", "label": "Giới tính", "type": "select", "default": "all",
             "options": [{"value": "all", "label": "Tất cả"}, {"value": "male", "label": "Nam"}, {"value": "female", "label": "Nữ"}]},
        ],
    },
    # ------------------------------------------------------------------ đầu ra
    "output": {
        "name": "Kết quả", "group": "output", "icon": "★", "desc": "Gom kết quả cuối vào thư mục lần chạy",
        "inputs": [{"key": "items", "type": "any", "label": "Kết quả", "multi": True}],
        "outputs": [],
        "fields": [{"key": "name", "label": "Tên thư mục kết quả", "type": "text", "default": "ket-qua"},
                   {"key": "open_folder", "label": "Mở thư mục khi xong", "type": "check", "default": False}],
    },
}
GROUPS = [("input", "Đầu vào"), ("ai", "AI xử lý"), ("create", "Tạo nội dung"), ("output", "Đầu ra")]


def defaults(node_type: str) -> dict:
    return {f["key"]: f.get("default") for f in NODE_TYPES[node_type]["fields"]}


def config_of(node: dict) -> dict:
    return {**defaults(node["type"]), **(node.get("config") or {})}


def meta() -> dict:
    return {"types": NODE_TYPES, "groups": GROUPS,
            "video_engines": {k: {**{f: v[f] for f in ("name", "durations", "resolutions", "aspects", "max_images", "note")},
                                  "video_input": bool(v.get("video_input"))} for k, v in VIDEO_ENGINES.items()},
            "image_engines": {k: {"name": v["name"], "aspects": v["aspects"], "counts": v["counts"], "note": v.get("note", "")}
                              for k, v in IMAGE_ENGINES.items()}}


# ====================================================================== chạy từng block
class NodeSkipped(Exception):
    """Block được bỏ qua có chủ đích (VD: bạn không duyệt đăng bài) — không tính là lỗi; block phía sau cũng bỏ qua."""


class NodeContext:
    def __init__(self, settings, run_dir: Path, node: dict, log, check_cancel, progress, services=None) -> None:
        self.settings = settings
        self.dir = run_dir / node["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.node, self.log, self.check_cancel, self.progress = node, log, check_cancel, progress
        self.services = services or {}  # facebook, ads, approve(payload) -> {"approved", "caption"}


def _text(values) -> str:
    return "\n\n".join(str(v).strip() for v in values if str(v or "").strip())


def _files(values) -> list[Path]:
    out = []
    for v in values:
        for p in (v if isinstance(v, list) else [v]):
            if p and Path(str(p)).is_file():
                out.append(Path(str(p)))
    return out


def run_node(ctx: NodeContext, inputs: dict) -> dict:
    cfg = config_of(ctx.node)
    kind = ctx.node["type"]
    if kind == "input_text":
        text = str(cfg.get("text") or "").strip()
        if not text:
            raise ValueError(f"“{cfg.get('label') or 'Văn bản'}” đang trống")
        (ctx.dir / "text.txt").write_text(text, "utf-8")
        return {"text": text}
    if kind in ("input_image", "input_video"):
        allowed = IMAGE_EXT if kind == "input_image" else VIDEO_EXT
        files = [Path(f) for f in cfg.get("files") or [] if Path(f).is_file() and Path(f).suffix.lower() in allowed]
        if not files:
            raise ValueError(f"“{cfg.get('label')}” chưa có file hợp lệ")
        copies = []
        for f in files:
            dest = ctx.dir / f.name
            shutil.copy2(f, dest)
            copies.append(str(dest))
        return {"images": copies} if kind == "input_image" else {"video": copies[0]}
    if kind == "ai_text":
        return {"text": _ai_text(ctx, cfg, _text(inputs.get("text", [])), _files(inputs.get("images", [])))}
    if kind == "content_post":
        return {"text": _content_post(ctx, cfg, _text(inputs.get("info", [])))}
    if kind == "gen_image":
        return {"images": _gen_image(ctx, cfg, _text(inputs.get("prompt", [])), _files(inputs.get("images", [])),
                                     _text(inputs.get("keyword", [])))}
    if kind == "gen_video":
        return {"video": _gen_video(ctx, cfg, _text(inputs.get("prompt", [])), _files(inputs.get("images", [])),
                                    _files(inputs.get("videos", [])))}
    if kind == "studio_video":
        return _studio_video(ctx, cfg, _text(inputs.get("idea", [])), _files(inputs.get("images", [])))
    if kind == "whiteboard_video":
        return _whiteboard_video(ctx, cfg, _text(inputs.get("text", [])))
    if kind == "concat_video":
        return {"video": _concat(ctx, cfg, _files(inputs.get("videos", [])))}
    if kind == "output":
        return {"items": _collect(ctx, cfg, inputs.get("items", []))}
    if kind in ("fb_post", "fb_schedule"):
        return {"post": _fb_post(ctx, cfg, _text(inputs.get("caption", [])), inputs.get("media", []), kind == "fb_schedule")}
    if kind == "fb_ad":
        return {"ad": _fb_ad(ctx, cfg, inputs.get("post", []))}
    raise ValueError(f"Block không hỗ trợ: {kind}")


# ---------------------------------------------------------------------- Facebook: đăng / hẹn giờ / quảng cáo
SCHEDULE_MIN, SCHEDULE_MAX = 10 * 60, 30 * 24 * 3600  # Facebook: hẹn giờ từ 10 phút đến 30 ngày


STUDIO_KEYS = ("length", "style", "aspect", "quality", "model", "image_engine", "scene_style", "video_engine", "dub", "voice", "rate", "subtitles", "bgm",
               "transition", "transition_sound", "post_ai", "post_model", "post_style", "show_browser", "prompt_polish")


def _studio_video(ctx, cfg, idea_in: str, refs: list) -> dict:
    """Block Video dài từ storyboard: tạo 1 dự án Studio thật rồi chạy trọn (storyboard → ảnh + clip → ghép, có hậu kỳ
    AI nếu bật) trong hàng đợi Studio. Nhật ký / tiến độ của Studio chuyển về block; dừng workflow → dừng dự án.
    Dự án vẫn nằm trong màn Studio để xem, sửa cảnh, ghép lại sau."""
    import time

    studio = ctx.services.get("studio")
    if studio is None:
        raise ValueError("Chưa nối được Studio")
    idea = _text([idea_in, cfg.get("idea")])
    if len(idea) < 10:
        raise ValueError("Cần ý tưởng video (ít nhất 1 câu) — nối dây vào cổng Ý tưởng hoặc nhập ở ô Ý tưởng")
    preset_id, logo, preset_refs = str(cfg.get("preset") or ""), "", []
    if preset_id:
        try:
            preset = studio.store.load(preset_id)
        except Exception as exc:  # dự án mẫu đã bị xoá
            raise ValueError("Không tìm thấy dự án Studio dùng làm cài đặt — chọn lại ở ô cài đặt") from exc
        options = dict(preset.get("options") or {})
        options["show_browser"] = bool(cfg.get("show_browser")) or bool(options.get("show_browser"))
        logo = preset.get("logo") or ""
        preset_refs = [r for r in preset.get("refs") or [] if Path(r).is_file()]
        ctx.log(f"Dùng cài đặt của dự án Studio “{preset.get('name')}”")
    else:
        options = {k: cfg.get(k) for k in STUDIO_KEYS}
        options["length"] = int(options.get("length") or 60)
    options["auto"] = True  # workflow: viết storyboard xong làm luôn cảnh + ghép
    name = str(cfg.get("name") or "").strip() or f"{ctx.services.get('workflow_name') or 'Workflow'} · {idea[:40]}"
    created = studio.create({"idea": idea, "name": name, "refs": [str(r) for r in refs][:6] or preset_refs,
                             "options": options, "logo": logo if logo and Path(logo).is_file() else ""})
    pid, task = created["project"]["id"], created["task"]
    ctx.log(f"Đã tạo dự án Studio “{created['project']['name']}” — xem chi tiết từng cảnh ở màn Studio")
    (ctx.dir / "studio.json").write_text(json.dumps({"project": pid, "name": created["project"]["name"]},
                                                    ensure_ascii=False), "utf-8")
    seen, summary = 0, {}
    try:
        while True:
            ctx.check_cancel()
            summary = next((t for t in studio.pool.list() if t["id"] == task), {"status": "error", "error": "Mất tác vụ"})
            logs = studio.pool.logs(task)
            for entry in logs[seen:]:  # nhật ký Studio → nhật ký workflow
                ctx.log(f"  {entry.get('message', '')}", entry.get("level", "info"))
            seen = len(logs)
            ctx.progress(float(summary.get("pct") or 0) / 100)
            if summary.get("status") in ("done", "error", "cancelled"):
                break
            time.sleep(1.5)
    except BaseException:
        studio.cancel(pid)  # dừng workflow → dừng luôn dự án Studio
        raise
    if summary.get("status") != "done":
        raise ValueError(f"Studio: {summary.get('error') or 'đã dừng'} — mở dự án “{name}” ở màn Studio để làm tiếp")
    project = studio.store.load(pid)
    job_id = (project.get("final") or {}).get("job_id")
    final = Path(ctx.settings.output_dir) / job_id / "final.mp4" if job_id else None
    if final is None or not final.is_file():
        raise ValueError("Studio chạy xong nhưng chưa có video hoàn chỉnh — mở dự án ở màn Studio để kiểm tra")
    dest = ctx.dir / "video.mp4"
    shutil.copy2(final, dest)
    narration = "\n".join(s["narration"].strip() for s in project.get("scenes") or [] if (s.get("narration") or "").strip())
    (ctx.dir / "loi-dan.txt").write_text(narration, "utf-8")
    ctx.log(f"Video {round(float(project['final'].get('duration') or 0))} giây · {len(project.get('scenes') or [])} cảnh", "ok")
    return {"video": str(dest), "text": narration}


def whiteboard_source(cfg: dict, text_in: str = "") -> str:
    """Nội dung block Whiteboard: file .srt (nếu chọn) → văn bản nối dây + ô SRT / kịch bản."""
    from ..pipeline import whiteboard as wbm

    srt = next((Path(f) for f in cfg.get("srt") or [] if Path(f).is_file()), None)
    if srt is not None:
        return wbm.read_srt_file(srt)
    return _text([text_in, cfg.get("text")])


def _whiteboard_video(ctx, cfg, text_in: str) -> dict:
    """Block Whiteboard: SRT (giữ mốc) hoặc kịch bản (giọng AI tạo mốc) → line-art từng cảnh → tay vẽ → video."""
    from ..pipeline import whiteboard as wbm
    from ..pipeline.ai_video import finalize

    text = whiteboard_source(cfg, text_in)
    if not text:
        raise ValueError("Chưa có SRT / kịch bản — nối dây vào cổng, nhập ở ô SRT hoặc chọn file .srt")
    engine = str(cfg.get("image_engine") or "gemini_browser")
    audio = next((Path(f) for f in cfg.get("audio") or [] if Path(f).is_file()), None)
    voice, rate = str(cfg.get("voice") or "vi-VN-HoaiMyNeural"), str(cfg.get("rate") or "+0%")
    aspect = cfg.get("aspect") if cfg.get("aspect") in wbm.SIZES else "16:9"
    wbm.ensure_installed(ctx.log)
    work = ctx.dir / "wb"
    cues, audio = wbm.load_cues(text, work, voice=voice, rate=rate, audio=audio)
    ctx.log(f"{len(cues)} câu · {'âm thanh đính kèm' if cfg.get('audio') else 'giọng AI ' + voice}")
    make_image = wbm.image_maker(engine, ctx.settings, show_browser=bool(cfg.get("show_browser")), log=ctx.log,
                                 check_cancel=ctx.check_cancel)
    raw = wbm.build_video(cues, work, make_image=make_image, aspect=aspect, audio=audio, voice=voice, rate=rate,
                          subtitles=bool(cfg.get("subtitles", True)), quality="hd" if cfg.get("quality") == "hd" else "fast",
                          hand=bool(cfg.get("hand", True)), hint=str(cfg.get("hint") or "")[:300], log=ctx.log,
                          check_cancel=ctx.check_cancel, progress=lambda f, msg: ctx.progress(0.95 * f))
    info = finalize(raw, ctx.dir, aspect, log=ctx.log)  # → ctx.dir/final.mp4 (H.264 + AAC, cân âm lượng)
    if (raw.parent / "final.srt").is_file():
        shutil.copy2(raw.parent / "final.srt", ctx.dir / "video.srt")
    dest = ctx.dir / "video.mp4"
    shutil.move(str(ctx.dir / "final.mp4"), dest)
    shutil.rmtree(ctx.dir / "scenes", ignore_errors=True)
    narration = "\n".join(c["text"] for c in cues) if wbm.is_srt(text) else text  # kịch bản thường → nguyên văn
    ctx.log(f"Video whiteboard {round(info['duration'])} giây · {info['width']}x{info['height']}", "ok")
    return {"video": str(dest), "text": narration}


def publish_time(cfg: dict) -> int:
    """Thời điểm hẹn giờ (Unix) từ cấu hình block; báo lỗi nếu ngoài khoảng Facebook cho phép."""
    import time
    from datetime import datetime

    now = time.time()
    if cfg.get("mode") == "at":
        raw = str(cfg.get("publish_at") or "").strip()
        try:
            when = datetime.fromisoformat(raw).timestamp()  # giờ máy (datetime-local)
        except ValueError:
            raise ValueError("Chọn ngày giờ đăng hợp lệ") from None
    else:
        try:
            when = now + float(cfg.get("delay_hours") or 0) * 3600
        except (TypeError, ValueError):
            raise ValueError("Số giờ hẹn đăng phải là số") from None
    if not SCHEDULE_MIN <= when - now <= SCHEDULE_MAX:
        raise ValueError("Facebook chỉ cho hẹn giờ từ 10 phút đến 30 ngày tính từ bây giờ")
    return int(when)


def _media(values) -> tuple[list[str], list[str]]:
    images, videos = [], []
    for v in values:
        for p in (v if isinstance(v, list) else [v]):
            path = Path(str(p)) if isinstance(p, str) and len(p) < 400 else None
            if path is not None and path.is_file():
                (images if path.suffix.lower() in IMAGE_EXT else videos if path.suffix.lower() in VIDEO_EXT else []).append(str(path))
    return images, videos


def _fb_post(ctx, cfg, caption_in: str, media_values: list, schedule: bool) -> dict:
    from datetime import datetime

    fb = ctx.services.get("facebook")
    if fb is None:
        raise ValueError("Chưa nối được dịch vụ Facebook")
    page_id = str(cfg.get("page_id") or "")
    page = next((p for p in fb.state().get("pages", []) if p["id"] == page_id), None)
    if not page:
        raise ValueError("Chưa chọn Fanpage (hoặc Fanpage chưa tải) — kết nối ở mục Fanpage Facebook")
    if not page.get("connected"):
        raise ValueError(f"Fanpage “{page['name']}” chưa bật Kết nối")
    kind = cfg.get("post_type") if cfg.get("post_type") in POST_TYPES else "feed"
    if schedule and kind not in SCHEDULABLE:
        raise ValueError("Facebook không cho hẹn giờ Story — dùng block Đăng bài Facebook")
    caption = _text([caption_in, cfg.get("caption")])
    images, videos = _media(media_values)
    if kind == "text":
        if images or videos:
            ctx.log("Kiểu “Chỉ bài viết” — bỏ qua ảnh/video được chọn", "warn")
        images, videos = [], []
        if not caption:
            raise ValueError("Kiểu “Chỉ bài viết” cần caption — tick văn bản trong Tài nguyên từ flow hoặc nhập caption")
    elif kind in ("media", "story"):
        caption = ""
        if not (images or videos):
            raise ValueError(f"Kiểu “{POST_TYPES[kind]}” cần ảnh/video — tick trong Tài nguyên từ flow")
    elif kind == "reel":
        if not videos:
            raise ValueError("Reels cần video — tick 1 video trong Tài nguyên từ flow")
        images = []
    if images and videos:
        ctx.log("Facebook không đăng chung ảnh và video trong 1 bài — chỉ đăng video", "warn")
        images = []
    if kind == "story" and len(images) + len(videos) > 1:
        ctx.log("Story chỉ đăng 1 file — dùng file đầu tiên", "warn")
    if not caption and not images and not videos:
        raise ValueError("Không có gì để đăng — tick caption/ảnh/video trong Tài nguyên từ flow hoặc nối dây")
    scheduled_at = publish_time(cfg) if schedule else None
    when = datetime.fromtimestamp(scheduled_at).strftime("%H:%M %d/%m/%Y") if scheduled_at else ""
    files = videos[:1] or (images[:1] if kind == "story" else images)
    if cfg.get("confirm", True):
        ctx.log(f"Chờ bạn duyệt {'hẹn giờ ' + when if schedule else 'đăng bài'} lên “{page['name']}”…", "warn")
        decision = ctx.services["approve"]({"page": page["name"], "page_id": page_id, "caption": caption, "files": files,
                                           "scheduled_at": scheduled_at, "when": when, "kind": "schedule" if schedule else "post",
                                           "post_type": kind, "post_type_label": POST_TYPES[kind]})
        if not decision.get("approved"):
            raise NodeSkipped("Bạn không duyệt đăng bài")
        caption = str(decision.get("caption", caption))
        ctx.log(f"Đã được duyệt bởi {decision.get('by', '')}")
    ctx.log(f"Đang {'hẹn giờ' if schedule else 'đăng'} {POST_TYPES[kind]} lên “{page['name']}”"
            + (f" lúc {when}" if when else "") + "…")
    if kind == "reel":
        res = fb.post_reel(page_id, caption, videos[0], scheduled_at)
    elif kind == "story":
        res = fb.post_story(page_id, files[0])
    elif videos:
        res = fb.post(page_id, caption, videos[0], scheduled_at)
    elif images:
        res = fb.post_album(page_id, caption, images, scheduled_at)
    else:
        res = fb.post(page_id, caption, "", scheduled_at)
    result = {"kind": "post", "post_id": res.get("id", ""), "page_id": page_id, "page": res.get("page", page["name"]),
              "url": res.get("url", ""), "scheduled": bool(scheduled_at), "when": when,
              "media": "video" if videos else "images" if images else "text", "caption": caption[:300],
              "post_type": kind}
    (ctx.dir / "bai-viet.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    try:
        from ..campaign import store as campaign_store

        campaign_store.log_post({"campaign": "workflow", "campaign_name": f"Workflow · {ctx.services.get('workflow_name', '')}",
                                 "page": result["page"], "page_id": page_id, "url": result["url"],
                                 "by": ctx.services.get("by", ""), "stt": ctx.node["id"]})
    except Exception:  # lịch sử chỉ để tra cứu — không làm hỏng bài vừa đăng
        pass
    try:  # Quản lý bài đăng: lưu bài (kèm bản sao ảnh / video) để sửa và đăng lại
        from ..posts import PostStore

        PostStore(fb).record(source="workflow", source_name=f"Workflow · {ctx.services.get('workflow_name', '')}",
                             kind=kind, caption=caption, files=files if kind != "text" else [], page_id=page_id,
                             page=page["name"], result=res, by=ctx.services.get("by", ""), scheduled_at=scheduled_at)
    except Exception:  # lưu lỗi không làm hỏng bài vừa đăng
        pass
    ctx.log(f"{'Đã hẹn giờ' if scheduled_at else 'Đã đăng'}: {result['url'] or result['post_id']}", "ok")
    return result


def _fb_ad(ctx, cfg, posts: list) -> str:
    post = next((p for p in posts if isinstance(p, dict) and p.get("post_id")), None)
    if post is None:
        raise ValueError("Chưa có bài viết — nối cổng Bài viết từ block Đăng bài Facebook")
    if post.get("scheduled"):
        raise ValueError("Bài hẹn giờ chưa được đăng nên chưa chạy quảng cáo được — dùng block Đăng bài Facebook")
    ads = ctx.services.get("ads")
    if ads is None:
        raise ValueError("Chưa nối được dịch vụ quảng cáo")
    if not cfg.get("account_id"):
        raise ValueError("Chưa chọn tài khoản quảng cáo")
    form = {k: cfg.get(k) for k in ("account_id", "objective", "daily_budget", "days", "countries", "age_min", "age_max", "gender")}
    form.update(page_id=post["page_id"], post_id=post["post_id"],
                name=f"Workflow · {ctx.services.get('workflow_name', '')} · {post['post_id'][-6:]}")
    ctx.log(f"Đang tạo quảng cáo cho bài {post['post_id']} (trạng thái TẠM DỪNG)…")
    res = ads.create_boost(form)
    text = (f"Đã tạo quảng cáo ở trạng thái TẠM DỪNG cho bài {post['post_id']} trên “{post.get('page', '')}”.\n"
            f"Chiến dịch {res.get('campaign_id')} · nhóm {res.get('adset_id')} · quảng cáo {res.get('ad_id')}.\n"
            "Kiểm tra rồi bật ở mục Quảng cáo Facebook khi sẵn sàng — chưa tiêu tiền.")
    (ctx.dir / "quang-cao.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), "utf-8")
    ctx.log("Đã tạo quảng cáo (tạm dừng)", "ok")
    return text


def _ai_text(ctx, cfg, text: str, images: list[Path]) -> str:
    template = str(cfg.get("prompt") or "{{input}}")
    prompt = template.replace("{{input}}", text) if "{{input}}" in template else (template + ("\n\n" + text if text else ""))
    if not prompt.strip():
        raise ValueError("Block AI chưa có yêu cầu (prompt)")
    provider = cfg.get("provider") or "claude_api"
    ctx.log(f"AI ({TEXT_PROVIDERS.get(provider, provider)}) đang xử lý…")
    if provider == "claude_api":
        answer = _claude(cfg.get("model") or "claude-opus-5-5", prompt, images)
    else:
        from ..llm import make_provider

        llm = make_provider(provider, ctx.settings, show_browser=bool(cfg.get("show_browser")))
        if llm is None:
            raise ValueError("Model AI không hợp lệ")
        answer = llm.generate(prompt, [str(p) for p in images] if getattr(llm, "supports_images", False) else None)
    answer = str(answer or "").strip()
    if not answer:
        raise ValueError("AI không trả về nội dung")
    (ctx.dir / "ket-qua.txt").write_text(answer, "utf-8")
    ctx.log(f"AI trả về {len(answer)} ký tự")
    return answer


def _content_post(ctx, cfg, info: str) -> str:
    """Block Tạo content bài viết: viết theo mẫu, kiểm tra giá/SĐT/website/địa chỉ, sai thì tự viết lại 1 lần."""
    from .. import content_writer as cw

    product = {k: str(cfg.get(f"sp_{k}") or "") for k in cw.FIELDS}
    if not info.strip() and not (product["name"].strip() and product["benefits"].strip()):
        raise ValueError("Block Tạo content: nhập Tên sản phẩm + Công dụng, hoặc nối dây Thông tin sản phẩm vào block")
    model = str(cfg.get("model") or "chatgpt_browser")
    ctx.log(f"Đang viết bài bằng {CONTENT_MODELS.get(model, model)}…")
    try:
        text, issues = cw.write_one(product, str(cfg.get("template") or ""), str(cfg.get("extra") or ""), model,
                                    ctx.settings, source=info, show_browser=bool(cfg.get("show_browser")), log=ctx.log)
    except cw.ContentError as exc:
        raise ValueError(str(exc)) from exc
    (ctx.dir / "bai-viet.txt").write_text(text, "utf-8")
    (ctx.dir / "kiem-tra.txt").write_text("\n".join(issues) or "Đạt: đúng giá, SĐT, website, địa chỉ; không có con số lạ",
                                          "utf-8")
    if issues:
        message = "Bài viết còn sai thông tin: " + "; ".join(issues)
        if cfg.get("strict", True):
            raise ValueError(message + " — sửa thông tin sản phẩm / mẫu rồi chạy lại, hoặc tắt “Dừng workflow nếu sai”")
        ctx.log(message, "warn")
    else:
        ctx.log("Bài viết đúng thông tin sản phẩm (giá, SĐT, website, địa chỉ)", "ok")
    return text


def _claude(model: str, prompt: str, images: list[Path]) -> str:
    """Claude API (Anthropic SDK) — fallback phía server khi bộ lọc an toàn từ chối."""
    import anthropic

    from ..campaign.ai import _jpeg_b64, get_key

    key = get_key()
    if not key:
        raise ValueError("Chưa có khoá Anthropic API — nhập ở Cài đặt → API & kết nối")
    client = anthropic.Anthropic(api_key=key, timeout=600.0, max_retries=2)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(p)}}
               for p in images[:6]] + [{"type": "text", "text": prompt}]
    try:
        resp = client.beta.messages.create(model=model, max_tokens=16000, messages=[{"role": "user", "content": content}],
                                           output_config={"effort": "medium"},
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.AuthenticationError as exc:
        raise ValueError("Khoá Anthropic API không hợp lệ") from exc
    except anthropic.RateLimitError as exc:
        raise ValueError("Claude API đang giới hạn tốc độ (429) — thử lại sau") from exc
    except anthropic.APIStatusError as exc:
        raise ValueError(f"Claude API lỗi {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ValueError("Không kết nối được Claude API") from exc
    if resp.stop_reason == "refusal":
        raise ValueError("Claude từ chối yêu cầu (bộ lọc an toàn) — sửa lại prompt")
    return "\n".join(b.text for b in resp.content if b.type == "text")


PIN_MAX = 6


def _pinterest_refs(ctx, cfg, keyword_in: str, prompt: str) -> list[Path]:
    """Ảnh Pinterest làm tham khảo: ảnh đã chọn trước ở giao diện, hoặc tự tìm theo từ khoá lúc chạy."""
    from ..llm import pinterest
    from ..llm.base import LLMError

    count = max(1, min(PIN_MAX, int(cfg.get("pin_count") or 3)))
    urls = [str(u) for u in cfg.get("pin_urls") or [] if str(u).startswith("https://i.pinimg.com/")][:PIN_MAX]
    keyword = ""
    if not urls:
        keyword = (keyword_in or str(cfg.get("pin_keyword") or "")).strip() or " ".join(prompt.split()[:8])
        keyword = " ".join(keyword.split())[:100]
        ctx.log(f"Đang tìm ảnh Pinterest: “{keyword}”")
        try:
            urls = [r["url"] for r in pinterest.search(keyword, limit=count, log=ctx.log)]
        except LLMError as exc:
            ctx.log(f"Không tìm được ảnh Pinterest ({exc}) — tạo ảnh không có tham khảo Pinterest", "warn")
            return []
    ctx.check_cancel()
    paths = pinterest.download(urls[:count] if keyword else urls, ctx.dir / "pinterest", log=ctx.log)
    (ctx.dir / "pinterest.json").write_text(json.dumps({"keyword": keyword, "urls": urls}, ensure_ascii=False, indent=2), "utf-8")
    if paths:
        ctx.log(f"Đã tải {len(paths)} ảnh tham khảo Pinterest")
    else:
        ctx.log("Không tải được ảnh Pinterest nào — tạo ảnh không có tham khảo Pinterest", "warn")
    return paths


def _gen_image(ctx, cfg, prompt_in: str, refs: list[Path], keyword_in: str = "") -> list[str]:
    from ..llm.image_engines import fit_aspect, generate, normalize, save_images
    from ..pipeline.ai_video import reference_sentence
    from ..pipeline.image_job import PIN_REF

    engine = cfg.get("engine") or "grok_browser"
    if engine not in IMAGE_ENGINES:
        raise ValueError("Model tạo ảnh không hợp lệ")
    prompt = _text([prompt_in, cfg.get("prompt")])
    if not prompt:
        raise ValueError("Block Tạo ảnh chưa có prompt (nối dây từ Văn bản/AI hoặc nhập prompt)")
    aspect, count = normalize(engine, str(cfg.get("aspect") or "9:16"), int(cfg.get("count") or 1))
    limit = IMAGE_ENGINES[engine]["max_images"]
    # thứ tự gửi: ảnh sản phẩm (cổng vào) → ảnh tham chiếu đính kèm ở block → ảnh Pinterest
    attached = [Path(f) for f in cfg.get("refs") or [] if Path(f).is_file() and Path(f).suffix.lower() in IMAGE_EXT]
    if len(attached) < len(cfg.get("refs") or []):
        ctx.log("Có ảnh tham chiếu đính kèm không còn trên máy — bỏ qua", "warn")
    role_in = INPUT_ROLES.get(cfg.get("input_role")) or INPUT_ROLES["product"]
    role_ref = REF_ROLES.get(cfg.get("ref_role")) or REF_ROLES["model"]
    items = [(role_in, p) for p in refs] + [(role_ref, p) for p in attached]
    if len(items) > limit:
        ctx.log(f"{IMAGE_ENGINES[engine]['name']} nhận tối đa {limit} ảnh tham chiếu — bỏ bớt ảnh thừa", "warn")
    items = items[:limit]
    if cfg.get("pinterest") and len(items) < limit:
        items += [(PIN_REF, p) for p in _pinterest_refs(ctx, cfg, keyword_in, prompt)[:limit - len(items)]]
    elif cfg.get("pinterest"):
        ctx.log("Đã đủ số ảnh tham chiếu tối đa của model — bỏ qua Pinterest", "warn")
    refs = [p for _, p in items]
    if refs:  # nói rõ vai trò từng ảnh: sản phẩm giữ nguyên, người mẫu / phong cách / bối cảnh, Pinterest chỉ lấy cảm hứng
        prompt = prompt.rstrip() + "\n\n" + reference_sentence([spec for spec, _ in items]).strip()
    ctx.log(f"{IMAGE_ENGINES[engine]['name']} · {aspect} · {count} ảnh" + (f" · {len(refs)} ảnh tham chiếu" if refs else ""))
    datas = generate(engine, prompt, aspect=aspect, count=count, quality="auto", images=refs, settings=ctx.settings,
                     show_browser=bool(cfg.get("show_browser")), log=ctx.log, check_cancel=ctx.check_cancel)
    if not datas:
        raise ValueError("Model không trả về ảnh nào")
    paths = save_images(datas, ctx.dir)
    for p in paths:
        fit_aspect(p, aspect)
    (ctx.dir / "prompt.txt").write_text(prompt, "utf-8")
    return [str(p) for p in paths]


def video_template(template_id: str):
    """Template video AI (prompt + biến + ảnh/video tham chiếu, kể cả template nhiều bước image_steps)."""
    from ..templates_registry import registry

    found = registry.get(str(template_id or ""))
    if found is None or found.kind != "ai_video":
        return None
    return found


def slot_ext(spec: dict) -> set:
    """Đuôi file một ô attachment nhận: keep_video = video gốc; video = ảnh hoặc video (cắt 1 khung hình); còn lại = ảnh."""
    return VIDEO_EXT if spec.get("keep_video") else IMAGE_EXT | (VIDEO_EXT if spec.get("video") else set())


def _slot_file(spec: dict, value) -> Path | None:
    path = Path(str(value or "")) if value else None
    return path if path is not None and path.is_file() and path.suffix.lower() in slot_ext(spec) else None


def template_engine(found, engine: str) -> str:
    """Template cố định engine (vd. "Nhảy theo trend" dùng Grok) thì dùng engine đó."""
    return found.video_engine if found is not None and found.video_engine in VIDEO_ENGINES else engine


def template_missing(cfg: dict, wired: set) -> list[str]:
    """Thông tin / ảnh / video bắt buộc của template còn thiếu. wired = các cổng vào đang có dây."""
    found = video_template(cfg.get("template"))
    if found is None:
        return []
    values = cfg.get("vars") or {}
    missing = [v["label"] for v in found.variables
               if v.get("required", True) and not str(values.get(v["key"]) or v.get("default") or "").strip()
               and not ("prompt" in wired and cfg.get("var_input") == v["key"])]
    files = cfg.get("att") or {}
    for spec in found.attachments:
        if not spec.get("required") or spec.get("default") or _slot_file(spec, files.get(spec["key"])):
            continue
        if ("videos" in wired if spec.get("keep_video") else "images" in wired or (spec.get("video") and "videos" in wired)):
            continue
        missing.append(spec["label"])
    return missing


def _template_attachments(found, cfg, images: list[Path], videos: list[Path]) -> list[tuple[dict, Path]]:
    """Ghép file cho từng ô của template: file chọn ở block → file từ dây nối (theo thứ tự) → ảnh mẫu của template."""
    chosen = cfg.get("att") or {}
    images, videos, out = list(images), list(videos), []
    for spec in found.attachments:
        path = _slot_file(spec, chosen.get(spec["key"]))
        if path is None and spec.get("keep_video"):
            path = videos.pop(0) if videos else None
        elif path is None:
            path = images.pop(0) if images else (videos.pop(0) if spec.get("video") and videos else None)
        if path is None and spec.get("default"):
            path = found.path / spec["default"]
        if path is None:
            if spec.get("required"):
                raise ValueError(f"Template cần: {spec['label']} — chọn file ở block hoặc nối dây vào block")
            continue
        out.append((spec, path))
    out += [({"key": f"ref{i}", "label": f"Ảnh thêm {i}", "role": "reference image", "prompt": "use it as a visual reference"}, p)
            for i, p in enumerate(images, 1)]
    return out


def _template_steps(ctx, found, cfg, files: dict, variables: dict, engine: str) -> list[tuple[dict, Path]]:
    """Template nhiều bước: chạy lần lượt các bước tạo ảnh (như trang Tạo video) → file gửi cho bước tạo video."""
    from ..llm.image_engines import ENGINES as IMAGE_ENGINES_ALL, fit_aspect, generate, save_images
    from ..pipeline.ai_video import fill_prompt, import_attachments, reference_sentence, step_inputs, video_inputs

    total = len(found.image_steps)
    for i, step in enumerate(found.image_steps):
        ctx.check_cancel()
        eng = step.get("engine") or engine
        if eng not in IMAGE_ENGINES_ALL:
            raise ValueError(f"Bước “{step.get('label', step['key'])}”: engine ảnh {eng} không hợp lệ")
        spec = IMAGE_ENGINES_ALL[eng]
        label = f"Bước {i + 1}/{total + 1}: {step.get('label', step['key'])}"
        inputs = step_inputs(step, files)[:spec["max_images"]]
        source = str((cfg.get("step_prompts") or {}).get(step["key"]) or "").strip() or step["prompt"]  # prompt bước đã sửa ở block
        prompt = fill_prompt(source, variables) + reference_sentence([a[0] for a in inputs])
        step_dir = ctx.dir / f"buoc-{i + 1}-{step['key']}"
        step_dir.mkdir(exist_ok=True)
        refs = import_attachments(step_dir, inputs)
        want = step.get("aspect", "9:16")
        aspect = want if want in spec["aspects"] else spec["aspects"][0]
        ctx.progress(0.6 * i / total)
        ctx.log(f"{label} · {spec['name']} · {aspect}")
        datas = generate(eng, prompt, aspect=aspect, count=1, quality="high", images=refs, settings=ctx.settings,
                         show_browser=bool(cfg.get("show_browser")), log=ctx.log, check_cancel=ctx.check_cancel)
        if not datas:
            raise ValueError(f"{label}: model không trả về ảnh")
        path = save_images(datas[:1], step_dir)[0]
        fit_aspect(path, aspect)
        (step_dir / "prompt.txt").write_text(prompt, "utf-8")
        files[step["key"]] = ({"key": step["key"], "label": step.get("label", step["key"])}, path)
        ctx.log(f"Xong {label}", "ok")
    return video_inputs(found, files)


def _template_video(ctx, found, cfg, prompt_in: str, images: list[Path], videos: list[Path], engine: str):
    """Prompt template đã điền biến + file tham chiếu đúng vai trò template (chạy các bước ảnh nếu có)."""
    from ..pipeline.ai_video import (collect_variables, import_attachments, prepare_video_refs, reference_sentence,
                                     template_prompt)

    raw = {k: v for k, v in (cfg.get("vars") or {}).items() if str(v or "").strip()}
    extra = [cfg.get("prompt")]
    if prompt_in and cfg.get("var_input") in {v["key"] for v in found.variables}:
        raw[cfg["var_input"]] = prompt_in[:300]
    else:
        extra.insert(0, prompt_in)
    variables = collect_variables(found, raw)
    # ô tham chiếu là video → prompt riêng cho video tham chiếu + gửi nguyên video (model nhận được video)
    attachments = prepare_video_refs(_template_attachments(found, cfg, images, videos), VIDEO_ENGINES[engine], ctx.log)
    prompt = template_prompt(found, variables, attachments, str(cfg.get("prompt_override") or "").strip())
    notes = _text(extra)
    if notes and not found.image_steps:
        prompt += "\n\nADDITIONAL NOTES:\n" + notes
    ctx.log(f"Template: {found.name}" + (" · " + ", ".join(f"{a[0].get('label', a[0]['key'])} ({a[1].name})" for a in attachments)
                                         if attachments else ""))
    if any(spec.get("keep_video") for spec, _ in attachments) and not VIDEO_ENGINES[engine].get("video_input"):
        raise ValueError(f"Template “{found.name}” cần gửi video gốc — chọn model Grok hoặc Dola (trình duyệt)")
    if found.image_steps:
        attachments = _template_steps(ctx, found, cfg, {spec["key"]: (spec, path) for spec, path in attachments}, variables, engine)
    limit = VIDEO_ENGINES[engine]["max_images"]
    if len(attachments) > limit:
        ctx.log(f"{VIDEO_ENGINES[engine]['name']} nhận tối đa {limit} file — bỏ qua: "
                + ", ".join(a[0].get("label", a[0]["key"]) for a in attachments[limit:]), "warn")
        attachments = attachments[:limit]
    files = import_attachments(ctx.dir, attachments) if attachments else []
    sentence = reference_sentence([a[0] for a in attachments]).strip()
    return prompt.rstrip() + ("\n\n" + sentence if sentence else ""), files


def _gen_video(ctx, cfg, prompt_in: str, refs: list[Path], ref_videos: list[Path] = ()) -> str:
    from ..llm.video_engines import generate, normalize_options
    from ..pipeline.ai_video import finalize

    engine = cfg.get("engine") or "grok_browser"
    found = video_template(cfg.get("template")) if cfg.get("template") else None
    if cfg.get("template") and found is None:
        raise ValueError("Template video không còn tồn tại — chọn template khác")
    fixed = template_engine(found, engine)
    if fixed != engine:
        ctx.log(f"Template “{found.name}” dùng cố định {VIDEO_ENGINES[fixed]['name']}")
        engine = fixed
    if engine not in VIDEO_ENGINES:
        raise ValueError("Model tạo video không hợp lệ")
    want = {k: cfg.get(k) for k in ("aspect", "duration", "resolution")}
    if found is not None and found.options.get("aspect"):  # khung hình đầu ra theo đúng template
        want["aspect"] = found.options["aspect"]
    options = normalize_options(engine, want)
    start = 0.6 if found is not None and found.image_steps else 0.0
    if found is not None:
        prompt, refs = _template_video(ctx, found, cfg, prompt_in, refs, list(ref_videos), engine)
    else:
        prompt = _text([prompt_in, cfg.get("prompt")])
        if ref_videos and VIDEO_ENGINES[engine].get("video_input"):
            refs = list(refs) + list(ref_videos)
        elif ref_videos:
            ctx.log(f"{VIDEO_ENGINES[engine]['name']} không nhận file video — bỏ qua video tham chiếu", "warn")
    if not prompt:
        raise ValueError("Block Tạo video chưa có prompt (nối dây từ Văn bản/AI, nhập prompt hoặc chọn template)")
    spec = VIDEO_ENGINES[engine]
    if len(refs) > spec["max_images"]:
        ctx.log(f"{spec['name']} nhận tối đa {spec['max_images']} ảnh — bỏ bớt ảnh thừa", "warn")
        refs = refs[:spec["max_images"]]
    ctx.log(f"{spec['name']} · {options['aspect']} · {options['duration']} · {options['resolution']}")
    raw = ctx.dir / "raw.mp4"
    generate(engine, prompt, raw, options=options, images=refs, settings=ctx.settings,
             show_browser=bool(cfg.get("show_browser")), log=ctx.log, check_cancel=ctx.check_cancel,
             on_progress=lambda pct: ctx.progress(start + (1 - start) * pct / 100))
    info = finalize(raw, ctx.dir, options["aspect"], log=ctx.log)
    (ctx.dir / "prompt.txt").write_text(prompt, "utf-8")
    ctx.log(f"Video {info.get('width')}x{info.get('height')} · {float(info.get('duration') or 0):.1f}s")
    want = float(str(options.get("duration") or "0").rstrip("s") or 0)
    if want and abs(float(info.get("duration") or 0) - want) > 3:  # lệch nhiều → có thể model không áp thời lượng / tải nhầm video
        ctx.log(f"Video dài {float(info.get('duration') or 0):.1f}s, khác {options['duration']} đã chọn — hãy xem lại video", "warn")
    return str(ctx.dir / "final.mp4")


def _concat(ctx, cfg, videos: list[Path]) -> str:
    from .. import ffmpeg

    if not videos:
        raise ValueError("Block Ghép video chưa có video đầu vào")
    if len(videos) == 1:
        return str(videos[0])
    from ..pipeline import transitions

    w, h = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}.get(cfg.get("aspect") or "9:16", (1080, 1920))
    n = len(videos)
    durs = [ffmpeg.media_duration(v) for v in videos]
    opts = transitions.clean(cfg.get("transition") or "none", cfg.get("transition_duration") or 0.5,
                             cfg.get("transition_sound") or "none", cfg.get("transition_volume") or 0.6)
    kinds = transitions.plan(opts["transition"], n - 1)
    d = min(opts["transition_duration"], min(durs) / 2)
    # hình: co + đệm về cùng khung → chuyển cảnh (giữ mốc thời gian: cảnh sau bắt đầu đúng lúc cảnh trước hết)
    pre = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
    chains, vout = transitions.video_graph(durs, kinds, d, pre=pre)
    args = sum((["-i", str(v)] for v in videos), [])
    # tiếng: tiếng gốc từng clip (không có → im lặng cùng độ dài) nối liền
    for i, v in enumerate(videos):
        src = f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo," if ffmpeg.has_audio(v) else "anullsrc=r=44100:cl=stereo,"
        chains.append(f"{src}apad,atrim=0:{durs[i]:.3f},asetpts=PTS-STARTPTS[a{i}]")
    chains.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
    # âm chuyển cảnh tại các điểm nối
    keys, labels, offset = transitions.sound_plan(opts["transition_sound"], n - 1), [], 0.0
    for k, key in enumerate(keys):
        offset += durs[k]
        path = transitions.sound_file(key)
        if path is None:
            continue
        idx = n + len(labels)
        args += ["-i", str(path)]
        start = max(0.0, offset - (transitions.SOUNDS[key][1] * 0.8 if key == "riser" else 0.12))
        chains.append(f"[{idx}:a]volume={opts['transition_volume']},adelay={int(start * 1000)}:all=1[s{len(labels)}]")
        labels.append(f"[s{len(labels)}]")
    aout = "[acat]"
    if labels:
        chains.append(f"[acat]{''.join(labels)}amix=inputs={len(labels) + 1}:normalize=0:dropout_transition=0:duration=first[amix]")
        aout = "[amix]"
    out = ctx.dir / "final.mp4"
    names = [transitions.TRANSITIONS[opts["transition"]][0]] + ([transitions.SOUNDS[opts["transition_sound"]][0]] if labels else [])
    ctx.log(f"Đang ghép {n} video · {' · '.join(names)}…")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", vout, "-map", aout, "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", out])
    return str(out)


def _collect(ctx, cfg, values: list) -> list:
    """Gom kết quả: file (ảnh/video) chép vào thư mục kết quả, văn bản ghi ra .txt."""
    import os

    name = "".join(c for c in str(cfg.get("name") or "ket-qua") if c.isalnum() or c in "-_ ").strip() or "ket-qua"
    out_dir = ctx.dir.parent / name
    out_dir.mkdir(parents=True, exist_ok=True)
    items, n = [], 0
    for value in values:
        for v in (value if isinstance(value, list) else [value]):
            n += 1
            path = Path(str(v)) if isinstance(v, str) and len(v) < 400 else None
            if path is not None and path.is_file():
                dest = out_dir / f"{n:02d}-{path.name}"
                shutil.copy2(path, dest)
                items.append(str(dest))
            elif str(v).strip():
                dest = out_dir / f"{n:02d}-van-ban.txt"
                dest.write_text(str(v), "utf-8")
                items.append(str(dest))
    (out_dir / "ket-qua.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
    ctx.log(f"Đã gom {len(items)} kết quả vào {out_dir.name}/")
    if cfg.get("open_folder"):
        os.startfile(out_dir)
    return items
