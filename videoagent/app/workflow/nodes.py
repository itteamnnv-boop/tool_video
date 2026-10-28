"""Định nghĩa các block của Workflow (cổng vào/ra, ô cấu hình) và cách chạy từng block.

Kiểu dữ liệu trên cổng: text (chuỗi), images (danh sách ảnh), video (file video), any (block Kết quả).
Một cổng vào nhận được nhiều dây ("multi"): văn bản nối bằng dòng trống, ảnh/video gộp thành danh sách.
Giao diện dựng form cấu hình từ "fields" — chỉ cần khai báo ở đây.
"""
import json
import shutil
from pathlib import Path

from ..osutil import open_path
from ..content_writer import BROWSER_MODELS, CLAUDE_MODELS as CONTENT_CLAUDE, DEFAULT_TEMPLATE as CONTENT_TEMPLATE
from ..content_writer import FIELDS as CONTENT_FIELDS, OPENAI_MODELS as CONTENT_OPENAI
from ..llm.image_engines import ENGINES as IMAGE_ENGINES
from ..llm.video_engines import ENGINES as VIDEO_ENGINES
from ..pipeline.tts import RATES as TTS_RATES, VOICES as TTS_VOICES
from ..pipeline.vieneu_tts import PRESET_VOICES as VIENEU_VOICES

# khối Lồng tiếng VieNeu → phân tích video: phong cách lời đọc model viết
DUB_TONES = {"ban_hang": "Bán hàng — hook, lợi ích, kêu gọi mua", "review": "Review / trải nghiệm thật",
             "ke_chuyen": "Kể chuyện cảm xúc", "huong_dan": "Hướng dẫn / giải thích từng bước", "tin_tuc": "Tin tức / thông báo"}
DUB_WPS = 2.8  # chữ / giây khi lồng tiếng tiếng Việt (chừa thở, đọc rõ)
DUB_PROMPT = """Bạn là biên kịch lồng tiếng video ngắn (TikTok / Reels / Facebook). Ảnh lưới đính kèm là các khung hình của video,
mỗi khung ghi mốc thời gian (phút:giây) ở góc trên-trái.
Video dài {dur:.1f} giây. Mốc đổi cảnh (giây): {cuts}.
{hint}
Phong cách: {tone}.

Viết LỜI ĐỌC tiếng Việt để lồng vào video, chia thành các đoạn khớp với cảnh:
- Mỗi đoạn nói về đúng thứ đang hiện trên hình trong khoảng thời gian của đoạn; đoạn đầu bắt đầu từ 0.3 giây.
- Tốc độ đọc khoảng {wps} chữ / giây: đoạn dài t giây tối đa t × {wps} chữ. Không cần lấp kín mọi giây — chừa nghỉ tự nhiên.
- Đoạn đầu là câu mở gây chú ý; đoạn cuối chốt ý / kêu gọi hành động nếu hợp phong cách.
- Không bịa giá / số liệu / thông tin không có trên hình hoặc trong thông tin được cung cấp.
- Viết số, đơn vị, từ viết tắt thành chữ dễ đọc (VD: "20kg" → "hai mươi ký", "BOSS 1" → "BOSS một").
Trả về đúng MỘT khối ```json:
{{"doan": [{{"bat_dau": 0.3, "ket_thuc": 3.5, "loi": "câu đọc"}}]}}"""

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
    "dub_vieneu": {
        "name": "Lồng tiếng VieNeu", "group": "create", "icon": "🎙",
        "desc": "Đọc lời thoại tiếng Việt bằng VieNeu-TTS (chạy trên máy, giọng có sẵn hoặc nhân bản từ file giọng mẫu) "
                "rồi ghép vào video — thay tiếng gốc hoặc giữ tiếng gốc nhỏ làm nền",
        "inputs": [{"key": "video", "type": "video", "label": "Video cần lồng tiếng"},
                   {"key": "text", "type": "text", "label": "Lời đọc (tuỳ chọn)", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video đã lồng tiếng"}],
        "fields": [
            {"key": "script_mode", "label": "Lời đọc lấy từ", "type": "select", "default": "manual",
             "options": [{"value": "manual", "label": "Lời đọc nhập / chữ từ khối nối vào"},
                         {"value": "analyze", "label": "🎬 Phân tích video → viết lời đọc khớp từng cảnh"}]},
            {"key": "analyze_model", "label": "Model xem video & viết lời", "type": "select", "default": "claude_browser",
             "options": [{"value": "claude_browser", "label": "Claude (trình duyệt)"},
                         {"value": "gemini_browser", "label": "Gemini (trình duyệt)"},
                         {"value": "chatgpt_browser", "label": "ChatGPT (trình duyệt)"}],
             "when": {"script_mode": ["analyze"]}},
            {"key": "tone", "label": "Phong cách lời đọc", "type": "select", "default": "ban_hang",
             "options": [{"value": k, "label": v} for k, v in DUB_TONES.items()], "when": {"script_mode": ["analyze"]}},
            {"key": "script", "label": "Lời đọc — hoặc ý chính / thông tin sản phẩm khi phân tích video (ghép sau chữ khối nối vào)",
             "type": "textarea", "default": ""},
            {"key": "voice", "label": "Giọng đọc VieNeu", "type": "select", "default": "Ngọc Huyền",
             "options": [{"value": v, "label": f"{v} — {d}"} for v, d in VIENEU_VOICES]},
            {"key": "ref_audio", "label": "Hoặc nhân bản giọng từ file mẫu (3–15 giây, rõ tiếng, không nhạc — có file thì dùng thay giọng trên)",
             "type": "files", "kind": "audio", "default": [], "single": True},
            {"key": "mix", "label": "Tiếng gốc của video", "type": "select", "default": "replace",
             "options": [{"value": "replace", "label": "Thay bằng giọng đọc"},
                         {"value": "duck", "label": "Giữ tiếng gốc nhỏ làm nền"}]},
            {"key": "orig_volume", "label": "Âm lượng tiếng gốc (0–1)", "type": "number", "default": "0.15",
             "when": {"mix": ["duck"]}},
            {"key": "fit", "label": "Lời đọc dài hơn video", "type": "select", "default": "extend",
             "options": [{"value": "extend", "label": "Giữ khung cuối cho đủ lời"},
                         {"value": "cut", "label": "Cắt theo độ dài video"}]},
            {"key": "lead", "label": "Bắt đầu đọc sau (giây)", "type": "number", "default": "0.3"},
        ],
    },
    "post_video": {
        "name": "Hậu kỳ video", "group": "create", "icon": "🎞",
        "desc": "Ghép các video nối vào + lồng tiếng AI / giữ tiếng gốc + chuyển cảnh + phụ đề + nhạc nền; hậu kỳ AI "
                "(Claude chọn hook, từ khoá nổi bật, hiệu ứng âm thanh) + đồ hoạ động Remotion / HyperFrames",
        "inputs": [{"key": "videos", "type": "video", "label": "Video (theo thứ tự nối)", "multi": True},
                   {"key": "text", "type": "text", "label": "Lời đọc / kịch bản (tuỳ chọn)", "multi": True}],
        "outputs": [{"key": "video", "type": "video", "label": "Video hậu kỳ"}],
        "fields": [
            {"key": "name", "label": "Tên video", "type": "text", "default": ""},
            {"key": "script", "label": "Lời đọc / phụ đề từng video (mỗi đoạn cách 1 dòng trống = 1 video, theo thứ tự nối)",
             "type": "textarea", "default": ""},
            {"key": "audio", "label": "Âm thanh", "type": "select", "default": "original",
             "options": [{"value": "original", "label": "Giữ tiếng gốc của video"},
                         {"value": "tts", "label": "Lồng tiếng AI theo lời đọc"},
                         {"value": "mute", "label": "Không lời (chỉ nhạc + âm)"}]},
            {"key": "voice", "label": "Giọng đọc AI", "type": "select", "default": "vi-VN-HoaiMyNeural",
             "options": [{"value": v["id"], "label": v["name"]} for v in TTS_VOICES], "when": {"audio": ["tts"]}},
            {"key": "rate", "label": "Tốc độ đọc", "type": "select", "default": "+0%",
             "options": [{"value": r, "label": r} for r in TTS_RATES], "when": {"audio": ["tts"]}},
            {"key": "aspect", "label": "Khung hình", "type": "select", "default": "9:16",
             "options": [{"value": a, "label": a} for a in ("9:16", "16:9", "1:1", "4:5")]},
            {"key": "transition", "label": "Chuyển cảnh", "type": "select", "default": "fade",
             "options": _transition_opts("transitions")},
            {"key": "transition_duration", "label": "Thời lượng chuyển cảnh", "type": "select", "default": "0.5",
             "options": [{"value": str(d), "label": f"{d} giây"} for d in (0.3, 0.5, 0.8, 1.0)],
             "when": {"transition": [k for k in _transition_keys() if k != "none"]}},
            {"key": "transition_sound", "label": "Âm chuyển cảnh", "type": "select", "default": "whoosh",
             "options": _transition_opts("sounds")},
            {"key": "subtitles", "label": "Phụ đề (từ lời đọc)", "type": "check", "default": True},
            {"key": "bgm", "label": "Nhạc nền", "type": "check", "default": True},
            {"key": "bgm_volume", "label": "Âm lượng nhạc nền (0–0.5)", "type": "number", "default": "0.12", "when": {"bgm": [True]}},
            {"key": "post_ai", "label": "✨ Hậu kỳ AI (hook, từ khoá nổi bật, hiệu ứng âm thanh)", "type": "check", "default": True},
            {"key": "post_model", "label": "Model hậu kỳ", "type": "select", "default": "claude_browser",
             "options": [{"value": "claude_browser", "label": "Claude (trình duyệt)"}, {"value": "muse_browser", "label": "Meta · Muse (trình duyệt)"},
                         {"value": "chatgpt_browser", "label": "ChatGPT (trình duyệt)"}, {"value": "gemini_browser", "label": "Gemini (trình duyệt)"}],
             "when": {"post_ai": [True]}},
            {"key": "post_style", "label": "Kiểu hậu kỳ", "type": "select", "default": "remotion",
             "options": [{"value": "remotion", "label": "Remotion — phụ đề động, hook, tiêu đề cảnh, chữ nhấn, zoom nhấn, thẻ kết (cần Node.js 18+)"},
                         {"value": "hyperframes", "label": "HyperFrames — đồ hoạ động do model tự thiết kế (cần Node.js 22+)"},
                         {"value": "basic", "label": "Cơ bản — phụ đề tô nổi từ khoá"}], "when": {"post_ai": [True]}},
            {"key": "post_subs", "label": "Tô nổi từ khoá trên phụ đề", "type": "check", "default": True, "when": {"post_ai": [True]}},
            {"key": "post_audio", "label": "Hiệu ứng âm thanh AI chọn", "type": "check", "default": True, "when": {"post_ai": [True]}},
        ],
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
        ],
    },
    "storyboard_video": {
        "name": "Storyboard (phân cảnh)", "group": "ai", "icon": "🧭",
        "desc": "AI phân tích yêu cầu (mục tiêu, người xem, thông điệp) → viết storyboard từng cảnh: mô tả, prompt video, "
                "lời thoại. Trên Canvas: chạy xong tự tách mỗi cảnh thành 1 node Video riêng + 1 khối Ghép video",
        "inputs": [{"key": "request", "type": "text", "label": "Yêu cầu", "multi": True},
                   {"key": "images", "type": "images", "label": "Vật liệu ảnh (sản phẩm / nhân vật / bối cảnh)", "multi": True},
                   {"key": "videos", "type": "video", "label": "Vật liệu video", "multi": True}],
        "outputs": [{"key": "storyboard", "type": "text", "label": "Storyboard"},
                    {"key": "text", "type": "text", "label": "Lời dẫn"}],
        "fields": [
            {"key": "request", "label": "Yêu cầu video (thêm sau văn bản nối vào cổng Yêu cầu)", "type": "textarea", "default": ""},
            {"key": "model", "label": "Model phân tích & viết storyboard", "type": "select", "default": "claude_browser",
             "options": [{"value": k, "label": v} for k, v in CONTENT_MODELS.items()]},
            {"key": "scenes", "label": "Số cảnh", "type": "select", "default": "auto",
             "options": [{"value": "auto", "label": "AI tự chọn (3–6)"}] + [{"value": str(n), "label": f"{n} cảnh"} for n in range(2, 9)]},
            {"key": "style", "label": "Phong cách hình ảnh (tuỳ chọn)", "type": "text", "default": ""},
            {"key": "speech", "label": "Lời thoại từng cảnh (lấy từ storyboard)", "type": "select", "default": "character",
             "options": [{"value": "character", "label": "Nhân vật trong cảnh nói lời thoại của cảnh"},
                         {"value": "narrator", "label": "Lời dẫn ngoài khung (model video đọc)"},
                         {"value": "none", "label": "Clip không lời — lời dẫn ra cổng Lời dẫn để lồng tiếng"}]},
            {"key": "aspect", "label": "Tỉ lệ khung hình", "type": "select", "default": "9:16",
             "options": [{"value": a, "label": a} for a in _union("aspects")]},
            {"key": "duration", "label": "Thời lượng mỗi cảnh (node Video tách ra dùng thời lượng này)", "type": "select",
             "default": "6s",
             "options": [{"value": d, "label": d} for d in sorted(_union("durations"), key=lambda s: int(s.rstrip("s")))]},
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
            {"key": "timing", "label": "Thời điểm đăng", "type": "select", "default": "now",
             "options": [{"value": "now", "label": "Đăng ngay"},
                         {"value": "app", "label": "Lên lịch — app tự đăng (sửa / đăng ngay ở màn Bài đăng)"}]},
            {"key": "mode", "label": "Lên lịch", "type": "select", "default": "delay", "when": {"timing": ["app"]},
             "options": [{"value": "delay", "label": "Sau một khoảng thời gian"}, {"value": "at", "label": "Vào ngày giờ cụ thể"}]},
            {"key": "delay_hours", "label": "Đăng sau (giờ)", "type": "number", "default": "2",
             "when": {"timing": ["app"], "mode": ["delay"]}},
            {"key": "publish_at", "label": "Ngày giờ đăng", "type": "datetime", "default": "",
             "when": {"timing": ["app"], "mode": ["at"]}},
            {"key": "sources", "label": "Tài nguyên từ flow (tick để dùng — không cần nối dây)", "type": "flow_sources",
             "default": []},
            {"key": "caption", "label": "Caption (thêm sau caption đầu vào)", "type": "textarea", "default": "",
             "when": {"post_type": ["feed", "text", "reel"]}},
            {"key": "confirm", "label": "Duyệt trước khi đăng (dừng chờ bạn bấm Đồng ý)", "type": "check", "default": True},
        ],
    },
    "fb_schedule": {
        "name": "Lên lịch đăng bài", "group": "output", "icon": "🗓",
        "desc": "Lên lịch đăng feed / Reels: app tự đăng (sửa, đăng ngay ở màn Bài đăng) hoặc hẹn giờ trên Facebook",
        "inputs": [{"key": "caption", "type": "text", "label": "Caption", "multi": True},
                   {"key": "media", "type": "any", "label": "Ảnh / video", "multi": True}],
        "outputs": [{"key": "post", "type": "post", "label": "Bài hẹn giờ"}],
        "fields": [
            {"key": "page_id", "label": "Fanpage", "type": "fb_page", "default": ""},
            {"key": "post_type", "label": "Kiểu đăng", "type": "select", "default": "feed",
             "options": [{"value": k, "label": v} for k, v in POST_TYPES.items() if k in SCHEDULABLE]},
            {"key": "sources", "label": "Tài nguyên từ flow (tick để dùng — không cần nối dây)", "type": "flow_sources",
             "default": []},
            {"key": "via", "label": "Ai đăng khi tới giờ", "type": "select", "default": "facebook",
             "options": [{"value": "app", "label": "App tự đăng — sửa / đổi lịch / đăng ngay ở màn Bài đăng (cần mở app)"},
                         {"value": "facebook", "label": "Facebook tự đăng — 10 phút → 30 ngày, gửi rồi không sửa từ app"}]},
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
    if kind == "storyboard_video":
        return _storyboard_video(ctx, cfg, _text(inputs.get("request", [])), _files(inputs.get("images", [])),
                                 _files(inputs.get("videos", [])))
    if kind == "dub_vieneu":
        return {"video": _dub_vieneu(ctx, cfg, _files(inputs.get("video", [])), inputs.get("text", []))}
    if kind == "post_video":
        return {"video": _post_video(ctx, cfg, _files(inputs.get("videos", [])), inputs.get("text", []))}
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
               "transition", "transition_sound", "post_ai", "post_model", "post_style", "show_browser")


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


STORY_WPS = 2.8  # chữ / giây lời thoại mỗi cảnh (chừa 1 giây đầu / cuối clip)
STORY_PROMPT = """Bạn là đạo diễn kiêm biên kịch video ngắn (quảng cáo, TikTok / Reels / Facebook).
YÊU CẦU CỦA NGƯỜI DÙNG:
{request}
{materials}
Bước 1 — PHÂN TÍCH yêu cầu: mục tiêu video, người xem, thông điệp chính, giọng điệu, nhân vật / sản phẩm / bối cảnh phải giữ
nhất quán, điều cần tránh. Chỗ nào yêu cầu không nói rõ thì tự chọn hợp lý và ghi vào "gia_dinh".
Bước 2 — STORYBOARD {count} cảnh. Mỗi cảnh là 1 clip {secs} giây do model video AI quay, khung {aspect}{style}:
- Cảnh 1 là hook gây chú ý ngay 2 giây đầu; cảnh cuối chốt thông điệp / kêu gọi hành động nếu hợp mục tiêu.
- Mỗi cảnh 1 hành động chính, diễn vừa trong {secs} giây; các cảnh nối mạch thành 1 câu chuyện.
- "prompt": prompt TIẾNG ANH tự đủ nghĩa cho model video (chủ thể, hành động, bối cảnh, ánh sáng, góc máy, chuyển động máy);
  mô tả nhân vật / sản phẩm y hệt nhau ở mọi cảnh để giữ nhất quán; không có chữ trên hình trừ khi yêu cầu ghi rõ.
- "loi_thoai": lời nói tiếng Việt CỦA ĐÚNG CẢNH ĐÓ, khớp với việc đang diễn ra trên hình của cảnh, khoảng {words} chữ
  (nói kịp trong {secs} giây); số / đơn vị viết thành chữ; "" nếu cảnh không cần lời.
  NẾU YÊU CẦU ĐÃ CÓ SẴN LỜI THOẠI / LỜI ĐỌC: chia ĐÚNG NGUYÊN VĂN lời đó cho các cảnh theo thứ tự (không viết lại, không bỏ,
  không thêm câu; không lặp 1 câu ở 2 cảnh) và dựng hình mỗi cảnh minh hoạ đúng câu được chia — lời dài thì tăng số cảnh.
{materials_rule}- Không bịa giá, số liệu, thông tin không có trong yêu cầu.
Trả về đúng MỘT khối ```json:
{{"phan_tich": {{"muc_tieu": "", "nguoi_xem": "", "thong_diep": "", "giong_dieu": "", "giu_nhat_quan": "", "gia_dinh": ""}},
 "tieu_de": "tên ngắn của video",
 "nhan_vat": "mô tả tiếng Anh nhân vật / sản phẩm xuất hiện xuyên suốt (\\"\\" nếu không có)",
 "canh": [{{"so": 1, "noi_dung": "cảnh này diễn ra gì (tiếng Việt)", "prompt": "English video prompt", "loi_thoai": "lời tiếng Việt", "vat_lieu": ["Ảnh 1"]}}]}}"""
STORY_ANALYSIS = {"muc_tieu": "Mục tiêu", "nguoi_xem": "Người xem", "thong_diep": "Thông điệp", "giong_dieu": "Giọng điệu",
                  "giu_nhat_quan": "Giữ nhất quán", "gia_dinh": "Giả định"}


def _story_parse(text: str) -> tuple[dict, list[dict]]:
    """Storyboard từ câu trả lời của model → (dữ liệu gốc, [{noi_dung, prompt, loi}]). Chấp nhận khoá tiếng Việt /
    tiếng Anh, mảng gốc hoặc nằm trong canh / scenes / storyboard."""
    from ..llm.base import extract_json

    try:
        data = extract_json(text)
    except ValueError:
        return {}, []
    items = data
    if isinstance(data, dict):
        items = next((v for k, v in data.items() if isinstance(v, list) and str(k).lower() in (
            "canh", "cảnh", "scenes", "scene", "storyboard", "shots")), None) \
            or next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
    else:
        data = {}
    scenes = []
    for d in items if isinstance(items, list) else []:
        if not isinstance(d, dict):
            continue
        low = {str(k).lower(): v for k, v in d.items()}

        def pick(*keys):
            return next((" ".join(str(low[k]).split()) for k in keys if str(low.get(k) or "").strip()), "")
        prompt = pick("prompt", "prompt_video", "video_prompt", "visual", "hinh_anh", "mo_ta_en")
        if not prompt:
            continue
        scene = {"noi_dung": pick("noi_dung", "nội dung", "mo_ta", "mô tả", "description", "summary") or prompt[:120],
                 "prompt": prompt[:2000],
                 "loi": pick("loi_thoai", "lời thoại", "loi", "lời", "loi_doc", "dialogue", "narration", "voiceover")[:600]}
        used = next((low[k] for k in ("vat_lieu", "vật liệu", "materials", "assets", "refs") if k in low), None)
        if used is not None:  # có khoá vật liệu (kể cả []) → node cảnh chỉ nối đúng vật liệu này
            scene.update(_story_materials(used))
        scenes.append(scene)
    return data, scenes


def _story_materials(value) -> dict:
    """["Ảnh 1", "Video 2"] / [1, 3] / "Ảnh 1, Ảnh 2" → {"anh": [1], "video": [2]} (số thứ tự bắt đầu từ 1)."""
    import re

    items = value if isinstance(value, list) else re.split(r"[,;]", str(value or ""))
    out = {"anh": [], "video": []}
    for it in items:
        text = str(it).strip().lower()
        num = re.search(r"\d+", text)
        if not num:
            continue
        key = "video" if "video" in text or "clip" in text else "anh"
        if int(num.group()) not in out[key]:
            out[key].append(int(num.group()))
    return out


def _story_material_text(cfg: dict, refs: list, videos: list) -> dict:
    """Danh sách vật liệu gửi model (đánh số đúng thứ tự ảnh đính kèm) + quy tắc chọn vật liệu cho từng cảnh.
    Tên vật liệu: Canvas truyền tên khối nối vào (cfg["_materials"]); không có thì dùng tên file."""
    names = cfg.get("_materials") or {}
    if not refs and not videos:
        return {"materials": "", "materials_rule": ""}
    lines = ["VẬT LIỆU ĐÍNH KÈM (ảnh gửi kèm theo đúng thứ tự dưới đây — nhìn kỹ để mô tả đúng sản phẩm / nhân vật):"]
    lines += [f"- Ảnh {i}: {(names.get('anh') or [])[i - 1] if i <= len(names.get('anh') or []) else p.stem}"
              for i, p in enumerate(refs, 1)]
    lines += [f"- Video {i}: {(names.get('video') or [])[i - 1] if i <= len(names.get('video') or []) else p.stem}"
              " (chỉ biết tên, không xem được)" for i, p in enumerate(videos, 1)]
    rule = ('- "vat_lieu": các vật liệu cảnh đó cần (VD ["Ảnh 1", "Video 1"]) — chỉ chọn thứ thực sự xuất hiện / được dùng '
            'trong cảnh (sản phẩm cận cảnh → ảnh sản phẩm; người nói → ảnh nhân vật); [] nếu cảnh không cần vật liệu nào.')
    return {"materials": "\n".join(lines), "materials_rule": rule}


def _story_markdown(data: dict, scenes: list[dict], secs: int) -> str:
    analysis = data.get("phan_tich") if isinstance(data.get("phan_tich"), dict) else {}
    lines = [f"# {str(data.get('tieu_de') or 'Storyboard').strip()}", "", "## Phân tích yêu cầu"]
    lines += [f"- **{label}:** {' '.join(str(analysis[k]).split())}" for k, label in STORY_ANALYSIS.items()
              if str(analysis.get(k) or "").strip()] or ["- (model không ghi phân tích)"]
    if str(data.get("nhan_vat") or "").strip():
        lines += ["", f"**Nhân vật / sản phẩm xuyên suốt:** {data['nhan_vat']}"]
    lines += ["", "## Storyboard"]
    for i, s in enumerate(scenes):
        lines += ["", f"### Cảnh {i + 1} · {i * secs}–{(i + 1) * secs}s", s["noi_dung"],
                  f"- Lời thoại: {s['loi'] or '(không lời)'}", f"- Prompt: {s['prompt']}"]
        if "anh" in s:
            used = [f"Ảnh {k}" for k in s["anh"]] + [f"Video {k}" for k in s["video"]]
            lines.append(f"- Vật liệu: {', '.join(used) or '(không dùng)'}")
    return "\n".join(lines) + "\n"


def _storyboard_video(ctx, cfg, request_in: str, refs: list[Path], videos: list[Path] = ()) -> dict:
    """Block Storyboard (phân cảnh): model phân tích yêu cầu + viết storyboard (JSON). Chỉ viết storyboard — quay video do
    các node Video từng cảnh làm (Canvas tự tách: canvas.CanvasRunner._split_scenes). Hỏng định dạng → hỏi lại 1 lần.
    Trả về storyboard (markdown), text (lời dẫn), scenes [{noi_dung, prompt đầy đủ cho model video, loi}]."""
    from ..studio import ask_model

    request = _text([request_in, cfg.get("request")])
    if len(request) < 10:
        raise ValueError("Cần yêu cầu video (ít nhất 1 câu) — nối dây vào cổng Yêu cầu hoặc nhập ở ô Yêu cầu video")
    options = {"aspect": str(cfg.get("aspect") or "9:16"), "duration": str(cfg.get("duration") or "6s")}
    secs = int(options["duration"].rstrip("s") or 6)
    count = str(cfg.get("scenes") or "auto")
    words = max(4, int((secs - 1) * STORY_WPS))
    style = str(cfg.get("style") or "").strip()
    prompt = STORY_PROMPT.format(
        request=request[:6000], secs=secs, aspect=options["aspect"], words=words,
        count=f"đúng {count}" if count.isdigit() else "từ 3 đến 6 (tự chọn theo độ phức tạp của yêu cầu)",
        style=f", phong cách hình ảnh: {style}" if style else "", **_story_material_text(cfg, refs, videos))
    model = str(cfg.get("model") or "claude_browser")
    ctx.log(f"Đang nhờ {CONTENT_MODELS.get(model, model)} phân tích yêu cầu và viết storyboard…")
    ctx.progress(0.02)
    ask = {"model": model, "text_profile": "", "show_browser": False, "timeout": 900}
    system = "Bạn là đạo diễn video ngắn. Làm đúng định dạng được yêu cầu."
    images = [str(p) for p in refs[:4]] or None
    raw = ask_model(ctx.settings, ask, prompt, complete=lambda t: bool(_story_parse(t)[1]), what="viết storyboard",
                    log=ctx.log, check_cancel=ctx.check_cancel, system=system, images=images)
    (ctx.dir / "tra-loi-model.txt").write_text(str(raw or ""), "utf-8")
    data, scenes = _story_parse(str(raw or ""))
    if not scenes:
        ctx.log("Câu trả lời chưa đúng định dạng — hỏi lại model, chỉ xin JSON storyboard…", "warn")
        raw = ask_model(ctx.settings, dict(ask), prompt + "\n\nLƯU Ý: lần trước bạn chưa trả đúng định dạng. CHỈ trả về "
                        "đúng 1 khối ```json như mẫu trên — không viết gì khác.", complete=lambda t: bool(_story_parse(t)[1]),
                        what="viết lại storyboard (JSON)", log=ctx.log, check_cancel=ctx.check_cancel, system=system,
                        images=images)
        (ctx.dir / "tra-loi-model-lan-2.txt").write_text(str(raw or ""), "utf-8")
        data, scenes = _story_parse(str(raw or ""))
    if not scenes:
        raise ValueError(f"Model không trả về storyboard hợp lệ (đã hỏi lại 1 lần) — xem {ctx.dir / 'tra-loi-model.txt'}; "
                         "thử lại hoặc đổi model")
    scenes = scenes[:int(count)] if count.isdigit() else scenes[:8]
    board = _story_markdown(data, scenes, secs)
    narration = "\n\n".join(s["loi"] for s in scenes if s["loi"])
    (ctx.dir / "storyboard.md").write_text(board, "utf-8")
    (ctx.dir / "storyboard.json").write_text(json.dumps({**data, "canh": scenes}, ensure_ascii=False, indent=2), "utf-8")
    (ctx.dir / "loi-dan.txt").write_text(narration, "utf-8")
    ctx.log(f"Storyboard “{str(data.get('tieu_de') or '').strip() or 'không tên'}”: {len(scenes)} cảnh × {secs}s", "ok")
    for i, s in enumerate(scenes):
        ctx.log(f"  Cảnh {i + 1}: {s['noi_dung']}")
    # prompt đầy đủ từng cảnh cho node Video: + nhân vật xuyên suốt + phong cách. Lời thoại KHÔNG ghép vào prompt —
    # node Video lấy lời thoại của đúng cảnh ở ô 💬 (Canvas: _dialogue_text) và tự dặn model nói / không nói
    subject = " ".join(str(data.get("nhan_vat") or "").split())
    full = []
    for s in scenes:
        parts = [s["prompt"]]
        if subject and subject.lower() not in s["prompt"].lower():
            parts.append(f"Consistent subject across all scenes: {subject}.")
        if style:
            parts.append(f"Visual style: {style}.")
        full.append({**s, "prompt": "\n\n".join(parts)})
    ctx.progress(1.0)
    return {"storyboard": board, "text": narration, "scenes": full}


def _dub_vieneu(ctx, cfg, videos: list[Path], texts: list) -> str:
    """Khối Lồng tiếng VieNeu: lời đọc → giọng VieNeu (WAV 48 kHz) → ghép vào video (thay / giữ nhỏ tiếng gốc)."""
    from .. import ffmpeg
    from ..pipeline import vieneu_tts

    if not videos:
        raise ValueError("Khối Lồng tiếng chưa có video — nối node Video / Ghép video / Video đầu vào vào")
    src = videos[0]
    text = "\n\n".join(str(t).strip() for t in [*texts, cfg.get("script") or ""] if str(t or "").strip())
    analyze = cfg.get("script_mode") == "analyze"
    if not text and not analyze:
        raise ValueError("Chưa có lời đọc — nhập ở ô Lời đọc, nối khối chữ (Văn bản, AI viết…) vào, "
                         "hoặc chọn “Phân tích video → viết lời đọc”")
    ref = next(iter(_files(cfg.get("ref_audio") or [])), None)
    segs = _dub_plan(ctx, cfg, src, text) if analyze else None  # lời đọc theo từng cảnh (có mốc giờ)
    if segs:
        text = "\n".join(s["text"] for s in segs)
    ctx.log(f"VieNeu: {len(text.split())} chữ" + (f" · {len(segs)} đoạn theo cảnh" if segs else "") + " · "
            + (f"nhân bản giọng từ {ref.name}" if ref else f"giọng {cfg.get('voice') or 'mặc định'}"))
    ctx.progress(0.35 if segs else 0.05)
    try:
        if segs:
            wavs = vieneu_tts.synthesize_many([(s["text"], ctx.dir / "doan" / f"{i + 1:02d}.wav") for i, s in enumerate(segs)],
                                              voice=str(cfg.get("voice") or ""), ref_audio=str(ref or ""),
                                              log=ctx.log, check_cancel=ctx.check_cancel)
        else:
            voice = vieneu_tts.synthesize(text, ctx.dir / "giong-doc.wav", voice=str(cfg.get("voice") or ""),
                                          ref_audio=str(ref or ""), log=ctx.log, check_cancel=ctx.check_cancel)
    except vieneu_tts.VieNeuError as exc:
        raise ValueError(str(exc)) from exc
    (ctx.dir / "loi-doc.txt").write_text(text, "utf-8")
    ctx.progress(0.8)
    lead = max(0.0, min(5.0, _num(cfg.get("lead"), 0.3)))
    if segs:  # ghép các đoạn đúng mốc cảnh thành 1 track giọng (mốc đã tính sẵn → không cộng thêm độ trễ)
        voice = _voice_track(segs, wavs, ctx.dir / "giong-doc.wav", ctx.log)
        lead = 0.0
    vdur = ffmpeg.media_duration(src)
    adur = ffmpeg.media_duration(voice) + lead
    extend = cfg.get("fit", "extend") == "extend" and adur > vdur + 0.05
    total = adur + 0.3 if extend else vdur
    ms = int(round(lead * 1000))
    chains = [f"[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms},apad[v1]"]
    if cfg.get("mix") == "duck" and ffmpeg.has_audio(src):
        vol = max(0.0, min(1.0, _num(cfg.get("orig_volume"), 0.15)))
        chains += [f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.3f},apad[v0]",
                   "[v0][v1]amix=inputs=2:duration=longest:normalize=0[aout]"]
    else:
        chains.append("[v1]anull[aout]")
    vmap = "0:v:0"
    if extend:  # lời dài hơn video → giữ khung cuối cho đủ lời
        chains.append(f"[0:v]tpad=stop_mode=clone:stop_duration={total - vdur + 0.1:.2f}[vout]")
        vmap = "[vout]"
    dest = ctx.dir / "video.mp4"
    ffmpeg.run(["-i", src, "-i", voice, "-filter_complex", ";".join(chains), "-map", vmap, "-map", "[aout]",
                *(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18"] if extend else ["-c:v", "copy"]),
                "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}", "-movflags", "+faststart", dest])
    ctx.progress(1.0)
    ctx.log(f"Đã lồng tiếng: {adur - lead:.1f} giây lời đọc" + (f" · kéo dài video tới {total:.1f} giây" if extend else ""), "ok")
    return str(dest)


def _dub_plan(ctx, cfg, video: Path, hint: str) -> list[dict]:
    """Phân tích video (ảnh lưới khung hình có mốc giây + mốc đổi cảnh) → model nhìn hình viết lời đọc theo từng đoạn
    khớp cảnh: [{start, end, text}], đã sắp xếp, nằm trong video, số chữ vừa thời lượng."""
    from .. import ffmpeg
    from ..pipeline import ref_video
    from ..studio import ask_model

    dur = ffmpeg.media_duration(video)
    work = ctx.dir / "phan-tich"
    work.mkdir(parents=True, exist_ok=True)
    ctx.log("Đang cắt khung hình + dò mốc đổi cảnh để phân tích video…")
    sheet, info = ref_video.contact_sheet(video, work, dur)
    cuts = [round(t, 1) for t in ref_video._scene_times(video, dur)][:40]
    hint_block = (f"Thông tin / ý chính người dùng cung cấp (bám theo, viết lại cho khớp hình):\n{hint[:3000]}"
                  if hint else "Không có thông tin thêm — viết theo những gì thấy trên hình.")
    prompt = DUB_PROMPT.format(dur=dur, cuts=", ".join(map(str, cuts)) or "không rõ (1 cảnh liền)", hint=hint_block,
                               tone=DUB_TONES.get(cfg.get("tone"), DUB_TONES["ban_hang"]), wps=DUB_WPS)
    model = cfg.get("analyze_model") or "claude_browser"
    ctx.log(f"Đang nhờ {model.split('_')[0].title()} xem video ({len(info['frames'])} khung) và viết lời đọc theo cảnh…")

    options = {"model": model, "text_profile": "", "show_browser": False, "timeout": 600}
    raw = ask_model(ctx.settings, options, prompt, complete=lambda t: bool(_dub_items(t)), what="xem video và viết lời đọc",
                    log=ctx.log, check_cancel=ctx.check_cancel, images=[sheet])
    (work / "tra-loi-model.txt").write_text(str(raw or ""), "utf-8")  # câu trả lời gốc — để xem lại khi lỗi
    items = _dub_items(raw)
    if not items:  # trả lời sai định dạng (viết chữ, thiếu JSON…) → hỏi lại 1 lần, chỉ xin JSON
        ctx.log("Câu trả lời chưa đúng định dạng — hỏi lại model, chỉ xin JSON lời đọc theo cảnh…", "warn")
        retry = (prompt + "\n\nLƯU Ý: lần trước bạn chưa trả đúng định dạng. CHỈ trả về đúng 1 khối ```json "
                 '{"doan": [{"bat_dau": số giây, "ket_thuc": số giây, "loi": "câu đọc"}]} — không viết gì khác.')
        raw = ask_model(ctx.settings, dict(options), retry, complete=lambda t: bool(_dub_items(t)),
                        what="viết lại lời đọc (JSON)", log=ctx.log, check_cancel=ctx.check_cancel, images=[sheet])
        (work / "tra-loi-model-lan-2.txt").write_text(str(raw or ""), "utf-8")
        items = _dub_items(raw)
    if not items:
        raise ValueError("Model không trả về lời đọc theo cảnh hợp lệ (đã hỏi lại 1 lần) — xem câu trả lời ở "
                         f"{work / 'tra-loi-model.txt'}; thử lại hoặc đổi model")
    segs = []
    for start, end, text in items:
        start = max(0.0, min(dur - 0.3, start if start is not None else 0.0))
        end = max(start + 0.5, min(dur, end if end is not None else start + 3))
        segs.append({"start": round(start, 2), "end": round(end, 2), "text": " ".join(text.split())[:600]})
    segs.sort(key=lambda s: s["start"])
    if not segs:
        raise ValueError("Model không viết được lời đọc nào cho video này")
    (ctx.dir / "loi-doc-theo-canh.json").write_text(json.dumps({"doan": segs}, ensure_ascii=False, indent=2), "utf-8")
    for s in segs:
        ctx.log(f"  {s['start']:5.1f}–{s['end']:5.1f}s: {s['text']}")
    return segs


def _secs(value):
    """Mốc giờ model viết: 3.5 / "3,5" / "3.5s" / "0:03" / "00:01:02.5" → giây (None nếu không đọc được)."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip().lower().replace(",", ".").rstrip("s").strip()
    if not s:
        return None
    try:
        if ":" in s:
            total = 0.0
            for part in s.split(":"):
                total = total * 60 + float(part)
            return total
        return float(s)
    except ValueError:
        return None


def _dub_items(text: str) -> list[tuple]:
    """Lời đọc theo cảnh từ câu trả lời của model → [(bắt đầu, kết thúc, câu)]. Chấp nhận nhiều dạng: {"doan": […]},
    mảng gốc, khoá tiếng Việt / tiếng Anh (bat_dau / start, ket_thuc / end, loi / text…), mốc "0:03";
    không có JSON thì đọc các dòng "0:00 – 0:04: câu đọc"."""
    import re

    from ..llm.base import extract_json

    try:
        data = extract_json(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        data = next((v for k, v in data.items() if isinstance(v, list) and k.lower() in (
            "doan", "đoạn", "doans", "segments", "segment", "scenes", "canh", "cảnh", "loi_doc", "items")), None) \
            or next((v for v in data.values() if isinstance(v, list)), None)
    out = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict):
            continue
        low = {str(k).lower(): v for k, v in d.items()}
        line = next((low[k] for k in ("loi", "lời", "loi_doc", "text", "noi_dung", "nội dung", "cau", "câu", "voiceover",
                                      "narration") if str(low.get(k) or "").strip()), "")
        if not line:
            continue
        start = next((_secs(low[k]) for k in ("bat_dau", "bắt đầu", "start", "tu", "từ", "from", "begin") if k in low), None)
        end = next((_secs(low[k]) for k in ("ket_thuc", "kết thúc", "end", "den", "đến", "to", "stop") if k in low), None)
        if start is None and isinstance(low.get("thoi_gian") or low.get("time"), str):  # "0:00-0:04"
            times = re.findall(r"\d+(?::\d+)*(?:[.,]\d+)?", low.get("thoi_gian") or low.get("time"))
            start, end = (_secs(times[0]) if times else None), (_secs(times[1]) if len(times) > 1 else None)
        out.append((start, end, str(line)))
    if out:
        return out
    for m in re.finditer(r"^\W*(\d+(?::\d+)?(?:[.,]\d+)?)\s*s?\s*[-–—~→]+\s*(\d+(?::\d+)?(?:[.,]\d+)?)\s*s?\s*[:：\]\)]\s*(.+)$",
                         str(text or ""), re.M):  # không có JSON: dòng "0:00 – 0:04: câu đọc"
        out.append((_secs(m.group(1)), _secs(m.group(2)), m.group(3).strip().strip('"“”')))
    return out


def _voice_track(segs: list[dict], wavs: list[Path], dest: Path, log) -> Path:
    """Đặt từng đoạn giọng vào đúng mốc cảnh: đoạn dài hơn chỗ trống → đọc nhanh tối đa 1.3×; vẫn tràn → đẩy đoạn sau lùi."""
    from .. import ffmpeg

    t, parts = 0.0, []
    for i, (s, w) in enumerate(zip(segs, wavs)):
        a = ffmpeg.media_duration(w)
        start = max(s["start"], t + 0.12) if i else s["start"]
        last = i + 1 == len(segs)  # đoạn cuối: không có đoạn sau để nhường chỗ → đọc tốc độ thường (khung cuối giữ đủ lời)
        room = float("inf") if last else max(0.6, segs[i + 1]["start"] - start - 0.1)
        tempo = min(1.3, a / room) if a > room else 1.0
        parts.append((w, start, tempo))
        t = start + a / tempo
        if tempo > 1.0:
            log(f"Đoạn {i + 1} hơi dài so với cảnh → đọc nhanh {tempo:.2f}×" + (" (vẫn lấn sang cảnh sau)" if a / tempo > room else ""))
    args, chains = [], []
    for i, (w, start, tempo) in enumerate(parts):
        args += ["-i", w]
        ms = int(round(start * 1000))
        chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo{f',atempo={tempo:.3f}' if tempo > 1.0 else ''},"
                      f"adelay={ms}|{ms}[s{i}]")
    mix = "".join(f"[s{i}]" for i in range(len(parts)))
    chains.append(f"{mix}amix=inputs={len(parts)}:duration=longest:normalize=0[out]" if len(parts) > 1 else "[s0]anull[out]")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-ar", "48000", dest])
    return dest


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def split_script(texts: list, count: int) -> list[str]:
    """Lời đọc cho từng video: các đoạn cách dòng trống (hoặc từng dòng nếu số dòng = số video), theo thứ tự nối;
    thừa đoạn → gộp vào video cuối; 1 đoạn → video đầu."""
    import re

    text = "\n\n".join(str(t).strip() for t in texts if str(t or "").strip())
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(parts) == 1 and len(lines) == count > 1:
        parts = lines
    if len(parts) > count:
        parts = parts[:count - 1] + [" ".join(parts[count - 1:])]
    return [" ".join(p.split()) for p in parts] + [""] * (count - len(parts))


def _post_video(ctx, cfg, videos: list[Path], texts: list) -> str:
    """Khối Hậu kỳ video: chạy đúng pipeline Hậu kỳ (Studio Muse AI) với model chọn được (mặc định Claude trình duyệt)."""
    from .. import muse_post

    if not videos:
        raise ValueError("Khối Hậu kỳ video chưa có video — nối node Video / Ghép video / Video đầu vào vào")
    script = split_script([*texts, cfg.get("script") or ""], len(videos))
    if cfg.get("audio") == "tts" and not any(script):
        ctx.log("Lồng tiếng AI nhưng chưa có lời đọc — video sẽ không lời (nhập lời đọc hoặc nối node chữ vào)", "warn")
    form = {**cfg, "name": str(cfg.get("name") or "").strip() or "Hậu kỳ video",
            "clips": [{"path": str(v), "text": script[i], "title": f"Cảnh {i + 1}"} for i, v in enumerate(videos)]}
    ctx.log(f"Hậu kỳ {len(videos)} video · âm thanh: {cfg.get('audio')} · "
            + (f"hậu kỳ AI {muse_post.POST_MODELS.get(cfg.get('post_model'), '')} + {cfg.get('post_style')}" if cfg.get("post_ai") else "không hậu kỳ AI"))
    try:
        final, info = muse_post.produce(ctx.settings, form, log=ctx.log, check_cancel=ctx.check_cancel,
                                        progress=lambda pct, stage: ctx.progress(float(pct) / 100))
    except muse_post.PostError as exc:
        raise ValueError(str(exc)) from exc
    dest = ctx.dir / "video.mp4"
    shutil.copy2(final, dest)
    (ctx.dir / "hau-ky.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), "utf-8")
    return str(dest)


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


def publish_time(cfg: dict, app: bool = False) -> int:
    """Thời điểm hẹn giờ (Unix) từ cấu hình block; báo lỗi nếu ngoài khoảng cho phép (Facebook: 10 phút → 30 ngày;
    app tự đăng: 1 phút → 1 năm)."""
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
    if app:
        from ..posts import APP_SCHEDULE_MAX, APP_SCHEDULE_MIN

        if not APP_SCHEDULE_MIN <= when - now <= APP_SCHEDULE_MAX:
            raise ValueError("Giờ lên lịch phải sau bây giờ ít nhất 1 phút (tối đa 1 năm)")
    elif not SCHEDULE_MIN <= when - now <= SCHEDULE_MAX:
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
    # lên lịch app tự đăng: block Đăng bài chọn “Lên lịch”, hoặc block Lên lịch chọn “App tự đăng”
    app_queue = (cfg.get("via") == "app") if schedule else (cfg.get("timing") == "app")
    if schedule and not app_queue and kind not in SCHEDULABLE:
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
    queue_at = publish_time(cfg, app=True) if app_queue else None
    scheduled_at = publish_time(cfg) if schedule and not app_queue else None
    when = datetime.fromtimestamp(scheduled_at or queue_at).strftime("%H:%M %d/%m/%Y") if (scheduled_at or queue_at) else ""
    schedule = bool(scheduled_at or queue_at)
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
    if app_queue:  # không đăng bây giờ: lưu vào Quản lý bài đăng, app tự đăng đúng giờ (sửa / đăng ngay ở đó)
        from ..posts import PostStore

        post = PostStore(fb).queue_new(source="workflow", source_name=f"Workflow · {ctx.services.get('workflow_name', '')}",
                                       kind=kind, caption=caption, files=files if kind != "text" else [],
                                       page_id=page_id, at=queue_at, by=ctx.services.get("by", ""))
        result = {"kind": "post", "post_id": "", "page_id": page_id, "page": page["name"], "url": "", "scheduled": True,
                  "queued": True, "local_post": post["id"], "when": when,
                  "media": "video" if videos else "images" if images else "text", "caption": caption[:300], "post_type": kind}
        (ctx.dir / "bai-viet.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
        ctx.log(f"Đã lên lịch đăng lúc {when} lên “{page['name']}” — sửa / đổi lịch / đăng ngay ở màn Quản lý bài đăng", "ok")
        return result
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
        open_path(out_dir)
    return items
