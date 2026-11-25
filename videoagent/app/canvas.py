"""Canvas — bảng node kiểu Kling Canvas: node Ảnh (prompt → model ảnh, ảnh nối vào = ảnh tham chiếu để sửa / ghép),
node Video (ảnh nối vào = khung đầu → model video), node Tải lên (ảnh của người dùng). Mỗi bảng lưu ở
<output_dir>/_canvas/<id>/board.json, file của node ở nodes/ (UI xem qua /media/_canvas/...).
Tạo ảnh / video dùng chung ImageRunner / JobRunner của app (đúng model, profile, giới hạn song song đã cài)."""
from __future__ import annotations  # CanvasRunner.list() che tên kiểu list trong chú thích kiểu

import copy
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import ffmpeg, model_prefs
from .image_library import IMAGES_DIR
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.image_engines import normalize as normalize_image
from .llm.video_engines import ENGINES as VIDEO_ENGINES
from .pipeline import Cancelled
from .pipeline.tasks import TaskPool
from .canvas_tasks import CanvasTasksMixin
from .util import read_json, slugify, write_json

CANVAS_DIR = "_canvas"
VIDEO_TEMPLATE = "canvas-video"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_NODES = 200
MAX_INPUTS = 10
MAX_UPSCALE_SIDE = 4096  # phóng to 2× nhưng cạnh dài tối đa 4096px
EDITABLE = ("x", "y", "title", "prompt", "engine", "aspect", "count", "duration", "resolution", "pick", "first_frame", "ask", "dialogue", "voice",
            "dialogue_src", "auto_post", "to_posts", "prompt_src", "w", "ask_fields", "auto_split",
            "template", "build", "tpl_ai", "ask_pos", "optional")  # ask_pos: thứ tự trong hộp ❓ Kiểm tra trước khi chạy; 🎞 template / build / tpl_ai: mẫu video (Grok Canvas); to_posts: 📥 lưu Quản lý bài đăng chờ duyệt; ask_fields: ô hỏi khi chạy ([] = mọi ô)
NODE_W = (120, 800)  # cỡ node Ảnh / Video / Ảnh tải lên kéo được (px, theo chiều rộng); w = 0 → cỡ mặc định
VIDEO_REF_SLOTS = ("ref1", "ref2", "ref3", "ref4", "ref5")  # ô ảnh tham chiếu của template canvas-video
# block của Workflow dùng được trên Canvas (chạy bằng chính workflow.nodes.run_node). Tạo ảnh / video là node riêng.
WF_TYPES = ("input_text", "ai_text", "web_research", "mcp_product", "content_post","input_video", "concat_video", "dub_vieneu", "post_video", "edit_pro", "studio_video",
            "heygen_video", "storyboard_video", "product_studio", "whiteboard_video", "fb_post", "fb_schedule", "fb_ad", "output")
MAX_RUNS = 20  # lịch sử chạy giữ trong board.json
PARALLEL = 3  # khối chạy CÙNG LÚC trong 1 lượt (Cài đặt: canvas_parallel) — nhánh độc lập không phải chờ nhau
# khối dựng / xử lý video trên máy (ffmpeg, Whisper, Remotion…): nặng CPU → 1 khối 1 lúc
HEAVY_LOCAL = ("concat_video", "post_video", "edit_pro", "dub_vieneu", "whiteboard_video", "studio_video", "output",
               "input_video")
# menu 🧩 Khối: ẩn hẳn (trùng luồng khác — khối cũ trên bảng vẫn chạy) / gom vào "Khối nâng cao" (ít dùng)
WF_MENU_HIDDEN = ("studio_video",)  # = Storyboard → tách cảnh → Ghép video, mà luồng đó sửa được từng cảnh
WF_ADVANCED = ("whiteboard_video", "dub_vieneu", "fb_schedule", "fb_ad")
POST_TYPES = ("fb_post", "fb_schedule", "fb_ad")  # khối đăng / lên lịch / quảng cáo: không bao giờ tự chạy lại khi làm lại
# khối Nhóm / ghi chú (kiểu sticky note n8n): chỉ để gom + ghi chú, không tham gia chạy quy trình
GROUP_COLORS = ("yellow", "green", "blue", "purple", "red", "gray")
MAX_GROUPS = 100
WF_HIDDEN = {"sources", "confirm", "ask", "label"}  # Canvas nối dây thay "tài nguyên từ flow"; đăng bài LUÔN chờ duyệt
ACTIVE = ("queued", "running", "waiting")
MAX_VERSIONS = 5  # mỗi khối giữ kết quả hiện tại + 4 bản trước (tạo lại không xoá ngay bản cũ — chọn lại được)
NO_VERSIONS = (*POST_TYPES, "output", "input_text", "input_video")  # khối không giữ phiên bản kết quả
MAX_UNDO = 40  # số bước hoàn tác mỗi bảng (trong phiên làm việc, không lưu qua lần mở app)
UNDO_MERGE = 8  # giây: gõ / kéo liên tục trên cùng khối gộp thành 1 bước hoàn tác
GC_AGE = 600  # giây: file kết quả không còn ai dùng (khối đã xoá, phiên bản cũ đã bỏ) quá 10 phút mới dọn
# trường kết quả / trạng thái chạy của node: hoàn tác chỉ trả lại cấu trúc (khối, dây, prompt, cấu hình, khoá…) — kết quả
# đang có giữ nguyên (kết quả cũ nằm ở Phiên bản); khối đã xoá được trả lại nguyên vẹn cả kết quả
RUNTIME = ("status", "pct", "stage", "error", "task", "approval", "files", "out", "pick", "sig", "sig_own", "versions",
           "secs", "done_at", "log_at", "made")  # made = prompt / yêu cầu đã dùng để tạo kết quả hiện tại
# dấu vân tay node: đổi 1 trong các trường này (hoặc kết quả khối phía trước đổi) → lần chạy quy trình sau chạy lại node
SIG_KEYS = ("kind", "wtype", "prompt", "engine", "aspect", "count", "duration", "resolution", "first_frame", "config",
            "dialogue", "voice", "dialogue_src", "auto_post", "prompt_src", "scene", "angles", "ref_files",
            "template", "build", "tpl_ai")
SIG_V = 2  # phiên bản công thức dấu vân tay (2 = khối trước đã có kết quả → dùng dấu lúc nó tạo kết quả)
# vai trò từng dây nối vào ("cổng có tên"): node Video — ảnh là khung đầu / tham chiếu; Edit Pro — video chính / clip
# minh hoạ. Không chọn = tự động theo thứ tự nối (như trước)
# 📎 khối Ảnh: vai trò ảnh tham chiếu nối vào → nhãn + lời dặn gửi model ảnh cho đúng ảnh đó
IMAGE_REF_ROLES = {
    "character": ("character / model reference",
                  "keep exactly this person's face, hairstyle, body shape and outfit — same person in the new image"),
    "product": ("product photo",
                "keep the product exactly as in this photo: shape, packaging, label, text and colors — do not redraw, "
                "translate or invent label text"),
    "scene": ("background / setting reference", "use this place as the setting / background of the new image"),
    "style": ("style reference", "copy only the composition, lighting and color mood — not the subject"),
}
ROLES = {"video": ("first", "ref"), "edit_pro": ("main", "clip"), "image": tuple(IMAGE_REF_ROLES),
         "product_studio": ("character", "product")}
# khối viết storyboard → Canvas tự tách mỗi cảnh 1 khối Video + khối Ghép (🎬 Product Video Studio dùng chung đường ống)
STORY_TYPES = ("storyboard_video", "product_studio")
# 🧍 / 📦 khối Ảnh preset "bảng nhiều góc": 1 ảnh gồm nhiều góc của CÙNG nhân vật / sản phẩm (dựng từ ảnh nối vào) → nối vào
# Video / Ảnh bìa / Storyboard làm ảnh tham chiếu giữ nhất quán khuôn mặt, trang phục, bao bì ở mọi góc máy
ANGLES = {
    "character": {
        "title": "🧍 Góc nhân vật", "what": "person",
        "prompt": "Character reference turnaround sheet of the SAME person shown in the reference photo(s). Five views in "
                  "ONE horizontal row, left to right: full-body front view, full-body three-quarter view, full-body side "
                  "profile, full-body back view, and a head-and-shoulders close-up of the face. Neutral relaxed standing "
                  "pose, plain light-grey seamless studio background, soft even lighting, same scale in every view. Keep "
                  "the exact face, age, skin tone, hairstyle, body shape and outfit (same clothes, colors, shoes, "
                  "accessories) identical in every view. Photorealistic, sharp focus, no text, no labels, no captions, "
                  "no extra people."},
    "product": {
        "title": "📦 Góc sản phẩm", "what": "product",
        "prompt": "Product reference sheet of the EXACT product shown in the reference photo(s). Five views in ONE "
                  "horizontal row, left to right: front view, three-quarter view, side view, back view, and top view. "
                  "Plain white seamless background, soft even studio lighting, same scale in every view. Keep the "
                  "packaging shape, material, colors, logo, label layout and label text exactly as in the reference — "
                  "do not redesign, translate or invent any text. Photorealistic product photography, no props, no "
                  "people, no captions, no extra copies."},
}
ANGLE_NOTE = ("Any reference image showing several views of the same {what} side by side is a multi-view reference "
              "sheet — use it ONLY to keep the "
              "identity consistent (face, outfit, packaging, label) from any camera angle. Render ONE normal shot: never "
              "a grid, collage, split screen, turnaround layout or multiple copies of the same {what}.")
# lý do 1 khối sẽ chạy trong lượt (hiện ở bảng xem trước lượt chạy)
WHY = {"fresh": "Làm lại từ đầu", "set": "Được giao làm lại", "target": "Khối bạn chọn chạy", "error": "Lần trước bị lỗi",
       "new": "Chưa chạy lần nào", "unfinished": "Lần trước chưa xong (đã dừng)", "own": "Bạn đã sửa prompt / cấu hình",
       "input": "Đầu vào đã đổi (khối phía trước có kết quả mới)", "changed": "Có thay đổi so với lần chạy trước",
       "upstream": "Khối phía trước chạy lại", "from": "Nằm sau khối bạn chọn"}
LOCAL_USE = "Trên máy (không tốn lượt)"
ENHANCE_SYSTEM = ("Bạn viết prompt cho model tạo {what}. Viết lại prompt người dùng thành MỘT đoạn prompt tiếng Anh "
                  "rõ ràng, cụ thể (chủ thể, hành động, bối cảnh, ánh sáng, góc máy{motion}), màu tươi sáng tự nhiên, "
                  "da người giữ kết cấu thật, không làm mịn. Giữ nguyên ý và mọi chữ / tên sản phẩm người dùng ghi. "
                  "Chỉ trả về đoạn prompt, không giải thích.")


# 💬 lời thoại của node Video: giọng → mô tả cho model video (tiếng nói gốc trong clip, khớp khẩu hình)
VOICES = {
    "": ("Theo người trong ảnh", ""),
    "young_f": ("Nữ trẻ", "a bright young Vietnamese woman's voice"),
    "young_m": ("Nam trẻ", "a clear young Vietnamese man's voice"),
    "mid_f": ("Nữ trung niên", "a warm middle-aged Vietnamese woman's voice"),
    "mid_m": ("Nam trung niên", "a deep, steady middle-aged Vietnamese man's voice"),
    "narrator": ("Lời dẫn ngoài khung", "an off-screen Vietnamese narrator (nobody on screen moves their lips)"),
}
WORDS_PER_SEC = 3.2  # tiếng Việt nói tự nhiên ~3 chữ / giây; trừ 1 giây đầu / cuối


def dialogue_words(node: dict) -> int:
    """Số chữ sẽ nói (bỏ phần "Tên:" đầu mỗi dòng)."""
    return len(re.sub(r"(?m)^[^:\n]{1,30}:\s*", "", node.get("dialogue") or "").split())


def dialogue_limit(node: dict) -> int:
    secs = int(str(node.get("duration") or "10s").rstrip("s") or 10)
    return max(4, int((secs - 1) * WORDS_PER_SEC))


def dialogue_prompt(node: dict) -> str:
    """Câu lời thoại cho prompt video: nói đúng nguyên văn tiếng Việt, khớp khẩu hình, nói xong trong thời lượng clip."""
    from .pronounce import apply as say  # 🗣 tên riêng đọc đúng (VD KINGER → Kinh gơ)

    lines = [" ".join(say(x).split()) for x in (node.get("dialogue") or "").splitlines() if x.strip()]
    if not lines:
        return ""
    voice = VOICES.get(node.get("voice") or "", VOICES[""])[1]
    if node.get("voice_note"):  # giọng cố định từ hồ sơ Storyboard (mọi cảnh cùng 1 giọng)
        voice = f"this exact same voice in every clip — {node['voice_note']}" + (f" ({voice})" if voice else "")
    said = "; ".join(f'"{x}"' if ":" not in x[:31] else f'{x.split(":", 1)[0].strip()}: "{x.split(":", 1)[1].strip()}"'
                     for x in lines)
    secs = int(str(node.get("duration") or "10s").rstrip("s") or 10)
    who = "an off-screen narrator says" if node.get("voice") == "narrator" else "the on-screen character speaks"
    return (f"DIALOGUE: {who} these exact lines out loud in Vietnamese, word for word, clearly audible"
            + (f", in {voice}" if voice else "") + ", with natural lip-sync, expressions and gestures matching the words: "
            + said + f". Pace the speech so every line finishes within {max(2, secs - 1)} seconds — never cut off "
            "mid-sentence. Keep only the voice and light natural ambience — no background music covering the voice, "
            "no subtitles or on-screen text unless the motion description asks for them.")


_SPEAKER = re.compile(r"^([^:\n]{1,30}):\s*(.*)$")


def _cut(text: str, cap: int) -> list[str]:
    """1 câu dài hơn cap chữ → cắt ở dấu phẩy / chấm phẩy / gạch, còn dài nữa thì cắt đều theo chữ."""
    parts, cur = [], []
    for piece in re.split(r"(?<=[,;:–—])\s+", text):
        words = piece.split()
        if cur and len(cur) + len(words) > cap:
            parts.append(" ".join(cur))
            cur = []
        while len(words) > cap:
            n = -(-len(words) // -(-len(words) // cap))  # chia đều, không khúc nào > cap
            parts.append(" ".join(words[:n]))
            words = words[n:]
        cur += words
    if cur:
        parts.append(" ".join(cur))
    return parts


def split_dialogue(text: str, limit: int) -> list[str]:
    """✂ Tách thông minh lời thoại dài thành nhiều đoạn, mỗi đoạn nói kịp trong 1 clip (≤ limit chữ): cắt ở cuối câu,
    câu quá dài mới cắt ở dấu phẩy; các đoạn dài gần bằng nhau; giữ "Tên:" người nói. Không gọi AI (không tốn lượt)."""
    units = []  # (người nói, câu, số dòng)
    for row, line in enumerate(x.strip() for x in str(text or "").splitlines()):
        if not line:
            continue
        m = _SPEAKER.match(line)
        who, body = (m.group(1).strip(), m.group(2)) if m and not re.match(r"^https?$", m.group(1).strip()) else ("", line)
        for sent in re.split(r"(?<=[.!?…])\s+", body):
            for part in _cut(sent.strip(), limit) if sent.strip() else []:
                units.append((who, part, row))
    total = sum(len(u[1].split()) for u in units)
    if not total:
        return []
    want = -(-total // limit)

    def pack(cap):
        chunks, cur, size = [], [], 0
        for u in units:
            n = len(u[1].split())
            if cur and size + n > cap:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(u)
            size += n
        return chunks + ([cur] if cur else [])

    chunks = pack(limit)
    for cap in range(-(-total // want), limit + 1):  # đoạn đều nhau nhất mà vẫn đúng số video tối thiểu
        trial = pack(cap)
        if len(trial) <= want:
            chunks = trial
            break

    def render(chunk):
        lines, last = [], None
        for who, part, row in chunk:
            if lines and (row, who) == last:
                lines[-1] += " " + part
            else:
                lines.append(f"{who}: {part}" if who else part)
            last = (row, who)
        return "\n".join(lines)

    return [render(c) for c in chunks]


class CanvasError(Exception):
    pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def meta(settings) -> dict:
    """Lựa chọn cho giao diện Canvas: model ảnh / video sẵn có trong hệ thống + model mặc định ở Cài đặt → Model AI."""
    from .content_writer import models

    from . import api_mode

    prefs = model_prefs.get(settings)
    images, videos = api_mode.engines(IMAGE_ENGINES, settings), api_mode.engines(VIDEO_ENGINES, settings)
    return {
        "image_engines": {k: {"name": v["name"], "aspects": v["aspects"], "counts": v["counts"],
                              "max_images": v["max_images"], "note": v.get("note", "")} for k, v in images.items()},
        "video_engines": {k: {"name": v["name"], "durations": v["durations"], "resolutions": v["resolutions"],
                              "aspects": v["aspects"], "max_images": v.get("max_images", 1),
                              "video_input": bool(v.get("video_input")), "note": v.get("note", "")}
                          for k, v in videos.items()},
        "text_models": models(settings),
        "wf_types": wf_types(),
        "voices": [{"value": k, "label": v[0]} for k, v in VOICES.items()],
        "words_per_sec": WORDS_PER_SEC,
        "defaults": {"image": prefs["model_image"] if prefs["model_image"] in images
                     else api_mode.pick("openai_api", images, settings),
                     "video": prefs["model_video"] if prefs["model_video"] in videos else "grok_browser",
                     "text": prefs["model_text"]},
    }


def _shown(wtype: str, key: str) -> bool:
    """Ô cấu hình block hiện trên Canvas: bỏ ô Canvas không dùng; riêng Video đầu vào giữ ô "Hỏi lại khi chạy"."""
    return key not in WF_HIDDEN or (wtype == "input_video" and key == "ask")


def wf_types() -> dict:
    """Block Workflow trên Canvas: cổng vào / ra + ô cấu hình (bỏ các ô Canvas không dùng)."""
    from .workflow import nodes as wfn

    from . import api_mode

    out = {k: {"name": s["name"], "icon": s["icon"], "desc": s["desc"], "group": s["group"], "inputs": s["inputs"],
               "outputs": s["outputs"], "fields": api_mode.fields([f for f in s["fields"] if _shown(k, f["key"])]),
               "menu": "hidden" if k in WF_MENU_HIDDEN else "advanced" if k in WF_ADVANCED else ""}
           for k, s in wfn.NODE_TYPES.items() if k in WF_TYPES}
    if "mcp_product" in out:  # 🔌 ô chọn kết nối / công cụ lấy từ màn Kết nối MCP (không có bí mật)
        out["mcp_product"]["fields"] = _mcp_fields(out["mcp_product"]["fields"])
    if "heygen_video" in out:  # 🧑‍💼 avatar / giọng đã tải từ HeyGen (lưu trên máy, không có khoá)
        out["heygen_video"]["fields"] = heygen_fields(out["heygen_video"]["fields"])
    return out


def heygen_fields(fields: list) -> list:
    from .llm import heygen_api

    return heygen_api.fill_fields(fields)


def _mcp_fields(fields: list) -> list:
    from . import mcp_hub

    try:
        servers = mcp_hub.server_options()
    except Exception:  # file cấu hình hỏng → ô chọn chỉ còn mặc định
        servers = []
    opts = {
        "server": [{"value": "", "label": "Tất cả kết nối đang bật"}] + [
            {"value": s["id"], "label": s["name"] + ("" if s["enabled"] else " (đang tắt)")} for s in servers],
        "tool": [{"value": "", "label": "— chọn công cụ —"}] + [
            {"value": f"{s['id']}::{t}", "label": f"{s['name']} · {t}"} for s in servers for t in s["tools"]],
    }
    return [{**f, "options": opts[f["key"]]} if f["key"] in opts else f for f in fields]


def out_types(node: dict) -> set:
    """Kiểu dữ liệu node đưa ra: images / video / text / post."""
    if node["kind"] in ("image", "upload"):
        return {"images"}
    if node["kind"] == "video":
        return {"video"}
    from .workflow import nodes as wfn

    return {o["type"] for o in wfn.NODE_TYPES[node["wtype"]]["outputs"]}


def in_types(node: dict) -> set:
    """Kiểu dữ liệu node nhận: Ảnh nhận ảnh tham chiếu + chữ; Video nhận ảnh (khung đầu, tham chiếu), video tham chiếu
    + chữ (thêm vào prompt)."""
    if node["kind"] == "image":
        return {"images", "text"}
    if node["kind"] == "video":
        return {"images", "video", "text"}
    if node["kind"] == "upload":  # 🖼 chỉ nhận ảnh sản phẩm từ khối Tra cứu web (connect() kiểm nguồn)
        return {"images"}
    from .workflow import nodes as wfn

    out = {"text"} if node["wtype"] == "output" else set()
    for p in wfn.NODE_TYPES[node["wtype"]]["inputs"]:
        out |= {"images", "video"} if p["type"] == "any" else {p["type"]}
    return out


def _model_label(key: str) -> str:
    from .workflow import nodes as wfn

    return wfn.TEXT_PROVIDERS.get(key) or wfn.CONTENT_MODELS.get(key) or key or "Model chữ"


FLOW_ENGINE = "flow_browser"  # 🎥 khối Google Flow (node Video cố định model này)

# ---------------------------------------------------------------------- 🎬 màn "Grok Canvas" (trước là Canvas Google Flow)
# Cùng chức năng Canvas, bảng riêng (_canvas_flow — giữ tên thư mục / sự kiện fcanvas_* để bảng cũ vẫn mở được); model
# ĐỊNH SẴN theo cài đặt của màn này (khoá cả lúc chạy): chữ + ảnh ChatGPT trình duyệt, video Grok Imagine, trợ lý điều
# phối Claude trình duyệt. Google Flow không dùng ở màn này (cài đặt cũ = Google Flow → tự chuyển sang Grok).
FLOW_CANVAS_DIR = "_canvas_flow"
GROK_ENGINE = "grok_browser"
FLOW_MODEL_DEFAULTS = {"text": "chatgpt_browser", "image": "chatgpt_browser", "video": GROK_ENGINE,
                       "assist": "claude_browser"}
SCREEN_OFF_VIDEO = (FLOW_ENGINE,)  # model video không dùng ở màn Grok Canvas
FLOW_TEXT_KEYS = ("provider", "post_model", "analyze_model", "text_model", "vision_model", "story_model")
FLOW_LOCKED_KEYS = (*FLOW_TEXT_KEYS, "image_engine", "video_engine")  # ô model của khối — ẩn ở màn Flow


def flow_models(settings) -> dict:
    """Model của màn Grok Canvas (Cài đặt của màn): {"text", "image", "video", "assist"} + profile trình duyệt."""
    from .content_writer import BROWSER_MODELS

    def text_ok(v: str) -> bool:
        return v in BROWSER_MODELS or v == "gemini_api" or v.startswith("api:")

    out = {}
    def video_ok(v: str) -> bool:
        return v in VIDEO_ENGINES and v not in SCREEN_OFF_VIDEO

    for key, ok in (("text", text_ok), ("image", IMAGE_ENGINES.__contains__), ("video", video_ok), ("assist", text_ok)):
        value = str(settings.get(f"fcanvas_model_{key}") or FLOW_MODEL_DEFAULTS[key])
        out[key] = value if ok(value) else FLOW_MODEL_DEFAULTS[key]
        out[f"{key}_profile"] = str(settings.get(f"fcanvas_profile_{key}") or "")
    return out


def _provider_like(value) -> bool:
    v = str(value or "")
    return v.endswith(("_browser", "_api")) or v.startswith("api:")


def lock_wf_config(wtype: str, cfg: dict, models: dict) -> dict:
    """Ô model của khối Workflow → model màn Flow (chữ / ảnh / video). Ô "model" chỉ đổi khi là model chữ (vd Tạo content);
    ô "model" là tên model Claude (khối AI viết khi chọn Claude API) giữ nguyên."""
    out = dict(cfg)
    for key in FLOW_TEXT_KEYS:
        if key in out:
            out[key] = models["text"]
    if _provider_like(out.get("model")):
        out["model"] = models["text"]
    if "image_engine" in out:
        out["image_engine"] = models["image"]
    if "video_engine" in out:
        out["video_engine"] = models["video"]
    if wtype in ("gen_image", "gen_video") and "engine" in out:
        out["engine"] = models["image" if wtype == "gen_image" else "video"]
    return out


def _flow_fields(fields: list) -> list:
    """Ô cấu hình khối ở màn Flow: bỏ ô chọn model (đã định sẵn ở Cài đặt của màn) + ô chỉ hiện theo các ô đó."""
    gone = {f["key"] for f in fields if f["key"] in FLOW_LOCKED_KEYS or (
        f["key"] == "model" and any(_provider_like(o.get("value")) for o in f.get("options") or [] if isinstance(o, dict)))}
    return [f for f in fields if f["key"] not in gone and not set((f.get("when") or {})) & gone]


def studio_clip(engine: str) -> str:
    """Độ dài mỗi cảnh Studio theo model video: Grok (6/10/15 giây) → 10 giây (15 giây hay trôi mặt / nhãn, 10 giây vẫn
    đủ 1–2 câu thoại); model khác → thời lượng dài nhất model hỗ trợ (Google Flow 8 giây)."""
    durations = (VIDEO_ENGINES.get(engine) or {}).get("durations") or ["8s"]
    return "10s" if engine == GROK_ENGINE and "10s" in durations else max(durations, key=lambda d: int(d.rstrip("s")))


def is_flow(node: dict) -> bool:
    return node.get("kind") == "video" and node.get("engine") == FLOW_ENGINE


def usage(node: dict) -> list:
    """1 lần chạy khối này dùng model / dịch vụ gì → [(nhãn, số lượt)] — cho bảng xem trước lượt chạy (tốn lượt gì)."""
    from . import api_mode
    from .workflow import nodes as wfn

    kind = node["kind"]
    if kind == "image":
        return [((IMAGE_ENGINES.get(api_mode.pick(node.get("engine"), IMAGE_ENGINES)) or {}).get("name") or "Model ảnh", 1)]
    if kind == "video":
        return [((VIDEO_ENGINES.get(api_mode.pick(node.get("engine"), VIDEO_ENGINES)) or {}).get("name") or "Model video", 1)]
    if kind != "wf":
        return []
    w = node["wtype"]
    cfg = api_mode.config({**wfn.defaults(w), **(node.get("config") or {})})  # 🔑 model sẽ dùng thật
    if w == "ai_text":
        p = cfg.get("provider") or ""
        return [(f"Claude API · {cfg.get('model')}" if p == "claude_api" else _model_label(p), 1)]
    if w == "web_research":
        p = cfg.get("provider") or ""
        return [(f"Claude API · {cfg.get('model')} (tìm web)" if p == "claude_api" else wfn.WEB_PROVIDERS.get(p, p), 1)]
    if w in ("content_post", "storyboard_video", "product_studio"):
        return [(_model_label(cfg.get("model")), 1)]
    if w == "post_video":
        return [(_model_label(cfg.get("post_model")), 1)] if cfg.get("post_ai") else [(LOCAL_USE, 1)]
    if w == "dub_vieneu":
        return ([(_model_label(cfg.get("analyze_model")), 1)] if cfg.get("script_mode") == "analyze" else []) \
            + [("VieNeu · trên máy", 1)]
    if w == "edit_pro":
        return [("Claude (trình duyệt)", 2 if cfg.get("review", True) else 1), ("Whisper · trên máy", 1)]
    if w == "studio_video":
        return [("Studio · nhiều lượt ảnh + video", 1)]
    if w == "heygen_video":
        return [("HeyGen API · 1 video (tốn credit HeyGen)", 1)]
    if w == "whiteboard_video":
        return [(f"{(IMAGE_ENGINES.get(cfg.get('image_engine')) or {}).get('name', 'Model ảnh')} · nhiều ảnh", 1)]
    if w in ("fb_post", "fb_schedule"):
        return [("Facebook · đăng bài", 1)]
    if w == "fb_ad":
        return [("Facebook · quảng cáo (tạm dừng)", 1)]
    return [(LOCAL_USE, 1)]


def _short(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


class CanvasRunner(CanvasTasksMixin):  # 📋 tác vụ: 1 flow chạy nhiều tác vụ (app/canvas_tasks.py)
    def __init__(self, settings, emit, images=None, videos=None, facebook=None, ads=None, studio=None,
                 variant: str = "canvas") -> None:
        self.on_flow_done = None  # hook: (bid, bản ghi lần chạy) khi chạy quy trình xong — trợ lý Claude tự điều phối
        self.settings = settings
        # 🎥 variant "flow" = màn Canvas Google Flow: bảng riêng, sự kiện fcanvas_*, model định sẵn (flow_models)
        self.flow = variant == "flow"
        self.dirname = FLOW_CANVAS_DIR if self.flow else CANVAS_DIR
        self.prefix = "fcanvas_" if self.flow else "canvas_"
        self.emit = (lambda e, d: emit(f"f{e}" if str(e).startswith("canvas_") else e, d)) if self.flow else emit
        self.images = images
        self.videos = videos
        self.facebook, self.ads, self.studio = facebook, ads, studio  # block Đăng bài / Quảng cáo / Video dài
        self.pool = TaskPool(self.prefix, emit, lambda: settings.get("max_parallel_canvas") or 4)
        self._lock = threading.RLock()
        self._approvals: dict[tuple, dict] = {}  # (bảng, node) → {"event", "decision"} — đăng bài chờ duyệt
        # lượt chạy quy trình đang chạy được nối dài (Storyboard tách cảnh → node Video mới chạy luôn trong lượt đó)
        self._grow: dict[str, bool] = {}  # bảng → lượt sắp chạy có được nối dài không (Chạy toàn bộ / Chạy từ đây)
        self._live: dict[str, tuple] = {}  # bảng → (mã lượt, danh sách node theo thứ tự — nối thêm được khi đang chạy)
        self._trash: set[Path] = set()  # file kết quả cũ chưa xoá được (Windows: đang mở xem trên Canvas) → xoá lại sau
        self._trash_lock = threading.Lock()
        # ↶ hoàn tác / ↷ làm lại theo bảng: mỗi bước = trạng thái cần trả lại của các khối / nhóm bị thao tác đó đổi
        self._undo: dict[str, list] = {}
        self._redo: dict[str, list] = {}
        self._batch: dict[str, int] = {}  # bảng → thread đang gom nhiều thao tác thành 1 bước (trợ lý Dựng, nhân bản…)

    # ------------------------------------------------------------------ lưu trữ
    @property
    def root(self) -> Path:
        path = Path(self.settings.output_dir) / self.dirname
        path.mkdir(parents=True, exist_ok=True)
        return path

    def models(self) -> dict | None:
        """Màn Canvas Google Flow: model định sẵn; Canvas thường: None (mỗi khối tự chọn model)."""
        return flow_models(self.settings) if self.flow else None

    def meta(self) -> dict:
        """Lựa chọn cho giao diện; màn Flow: kèm model định sẵn + ô cấu hình khối không có ô chọn model."""
        out = meta(self.settings)
        if not self.flow:
            return out
        m = self.models()
        names = {**{x["id"]: x["name"] for x in out["text_models"]}}
        out["flow"] = {**m, "names": {"text": names.get(m["text"], m["text"]), "assist": names.get(m["assist"], m["assist"]),
                                      "image": IMAGE_ENGINES[m["image"]]["name"], "video": VIDEO_ENGINES[m["video"]]["name"]}}
        out["wf_types"] = {k: {**s, "fields": _flow_fields(s["fields"])} for k, s in out["wf_types"].items()}
        out["defaults"] = {**out["defaults"], "image": m["image"], "video": m["video"], "text": m["text"]}
        return out

    def _as_run(self, node: dict) -> dict:
        """Khối như lúc CHẠY: màn Flow → ô model của khối Workflow theo model định sẵn (bảng xem trước, kiểm tra)."""
        if not self.flow or node.get("kind") != "wf":
            return node
        from .workflow import nodes as wfn

        return {**node, "config": lock_wf_config(node["wtype"], {**wfn.defaults(node["wtype"]), **(node.get("config") or {})},
                                                 self.models())}

    def _lock_models(self, board: dict) -> dict:
        """Màn Flow: khối Ảnh / Video luôn dùng model định sẵn (đổi model ở Cài đặt của màn → khối chạy lại lần sau)."""
        m = self.models()
        for node in board.get("nodes") or []:
            if node.get("kind") in ("image", "video"):
                want = m["image" if node["kind"] == "image" else "video"]
                if node.get("engine") != want:
                    node["engine"] = want
                    self._fit_options(node)
        return board

    def dir(self, bid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{6,60}", bid or ""):
            raise CanvasError("Mã bảng không hợp lệ")
        path = self.root / bid
        if not (path / "board.json").is_file():
            raise CanvasError("Không tìm thấy bảng")
        return path

    def load(self, bid: str) -> dict:
        board = read_json(self.dir(bid) / "board.json")
        if board.get("sig_v") != SIG_V:  # bảng cũ → chuyển dấu vân tay 1 lần (không chạy lại hàng loạt)
            with self._lock:
                board = read_json(self.dir(bid) / "board.json")
                if board.get("sig_v") != SIG_V:
                    self._migrate_sigs(board)
                    board["sig_v"] = SIG_V
                    write_json(self.root / bid / "board.json", board)
        return self._lock_models(board) if self.flow else board

    def _save(self, board: dict) -> dict:
        board["updated_at"] = now()
        write_json(self.root / board["id"] / "board.json", board)
        return board

    def _edit(self, bid: str, fn, undo: str = "", key: str = "") -> dict:
        """Sửa board.json trong khoá. undo = tên bước hoàn tác (thao tác sửa quy trình của người dùng / trợ lý);
        key = gộp các lần sửa liên tiếp cùng key (gõ prompt, kéo khối) thành 1 bước."""
        with self._lock:
            board = self.load(bid)
            before = self._capture(board) if undo and self._batch.get(bid) != threading.get_ident() else None
            fn(board)
            if before is not None:
                self._record(bid, before, board, undo, key)
            return self._save(board)

    # ------------------------------------------------------------------ ↶ hoàn tác / ↷ làm lại
    @staticmethod
    def _struct(item: dict | None):
        """Phần cấu trúc của node / nhóm (bỏ kết quả, trạng thái chạy) — để biết thao tác có đổi gì không."""
        return None if item is None else {k: v for k, v in item.items() if k not in RUNTIME}

    @staticmethod
    def _capture(board: dict) -> dict:
        return {"nodes": {n["id"]: copy.deepcopy(n) for n in board["nodes"]},
                "groups": {g["id"]: copy.deepcopy(g) for g in board.get("groups") or []}}

    def _record(self, bid: str, before: dict, board: dict, label: str, key: str = "") -> None:
        """Ghi 1 bước hoàn tác: trạng thái TRƯỚC thao tác của các khối / nhóm bị thao tác đổi (None = chưa có → hoàn tác
        thì gỡ đi). Không đổi gì → không ghi. Bước mới → xoá các bước ↷ làm lại."""
        after = self._capture(board)
        diff = {}
        for part in ("nodes", "groups"):
            ids = set(before[part]) | set(after[part])
            diff[part] = {i: before[part].get(i) for i in ids
                          if self._struct(before[part].get(i)) != self._struct(after[part].get(i))}
        if not diff["nodes"] and not diff["groups"]:
            return
        stack = self._undo.setdefault(bid, [])
        top = stack[-1] if stack else None
        if key and top and top.get("key") == key and time.time() - top["t"] < UNDO_MERGE:
            for part in ("nodes", "groups"):  # gộp: giữ trạng thái trước lần sửa ĐẦU TIÊN
                for i, state in diff[part].items():
                    top[part].setdefault(i, state)
            top["t"] = time.time()
        else:
            stack.append({"label": label, "key": key, "t": time.time(), **diff})
            del stack[:-MAX_UNDO]
        self._redo.pop(bid, None)

    @contextmanager
    def batch(self, bid: str, label: str):
        """Gom mọi thao tác sửa trong khối with (cùng thread) thành 1 bước hoàn tác — VD trợ lý Dựng 20 thao tác."""
        me = threading.get_ident()
        if self._batch.get(bid) == me:  # lồng nhau → bước ngoài cùng ghi
            yield
            return
        with self._lock:
            before = self._capture(self.load(bid))
            self._batch[bid] = me
        try:
            yield
        finally:
            with self._lock:
                if self._batch.get(bid) == me:
                    self._batch.pop(bid, None)
                try:
                    self._record(bid, before, self.load(bid), label)
                except CanvasError:  # bảng đã xoá
                    pass

    def undo_info(self, bid: str) -> dict:
        u, r = self._undo.get(bid) or [], self._redo.get(bid) or []
        return {"undo": u[-1]["label"] if u else "", "redo": r[-1]["label"] if r else ""}

    def undo(self, bid: str) -> dict:
        return self._step(bid, self._undo, self._redo, "hoàn tác")

    def redo(self, bid: str) -> dict:
        return self._step(bid, self._redo, self._undo, "làm lại")

    def _step(self, bid: str, src: dict, dst: dict, verb: str) -> dict:
        with self._lock:
            stack = src.get(bid) or []
            if not stack:
                raise CanvasError(f"Không còn thao tác nào để {verb}")
            board = self.load(bid)
            entry = stack[-1]
            cur = {n["id"]: n for n in board["nodes"]}
            busy = [i for i in entry["nodes"] if (cur.get(i) or {}).get("status") in ACTIVE]
            if busy:
                raise CanvasError(f"Khối {', '.join(busy)} đang chạy — chờ xong rồi {verb}")
            stack.pop()
            back = {"label": entry["label"], "key": "", "t": time.time(),
                    "nodes": {i: copy.deepcopy(cur.get(i)) for i in entry["nodes"]},
                    "groups": {i: copy.deepcopy(next((g for g in board.get("groups") or [] if g["id"] == i), None))
                               for i in entry["groups"]}}
            self._restore(board, entry)
            dst.setdefault(bid, []).append(back)
            del dst[bid][:-MAX_UNDO]
            self._save(board)
        return {"board": self.public(board), "label": entry["label"]}

    def _restore(self, board: dict, entry: dict) -> None:
        """Trả các khối / nhóm về trạng thái trong bước hoàn tác: khối còn trên bảng → lấy lại cấu trúc, GIỮ kết quả đang có;
        khối đã xoá → đặt lại nguyên vẹn (cả kết quả); khối thao tác đó thêm vào → gỡ đi."""
        cur = {n["id"]: n for n in board["nodes"]}
        for nid, state in entry["nodes"].items():
            now_node = cur.get(nid)
            if state is None:
                if now_node is not None:
                    board["nodes"].remove(now_node)
                continue
            node = copy.deepcopy(state)
            same = (state.get("kind"), state.get("wtype") or "") == ((now_node or {}).get("kind"), (now_node or {}).get("wtype") or "")
            if now_node is not None and same:
                node = {k: v for k, v in node.items() if k not in RUNTIME}
                node.update({k: now_node[k] for k in RUNTIME if k in now_node})
                board["nodes"][board["nodes"].index(now_node)] = node
            elif now_node is not None:  # 🔁 hoàn tác / làm lại Đổi khối: kết quả thuộc đúng loại khối đó → trả nguyên vẹn
                if node.get("status") in ACTIVE:
                    node.update(status="idle", pct=0, task="", approval={}, stage="")
                board["nodes"][board["nodes"].index(now_node)] = node
            else:
                if node.get("status") in ACTIVE:
                    node.update(status="idle", pct=0, task="", approval={}, stage="")
                board["nodes"].append(node)
        groups = {g["id"]: g for g in board.get("groups") or []}
        for gid, state in entry["groups"].items():
            if state is None:
                groups.pop(gid, None)
            else:
                groups[gid] = copy.deepcopy(state)
        board["groups"] = list(groups.values())
        ids = {n["id"] for n in board["nodes"]}
        for n in board["nodes"]:  # dây / nguồn chữ trỏ tới khối không còn → bỏ
            n["inputs"] = [i for i in n.get("inputs") or [] if i in ids]
            for k in ("dialogue_src", "prompt_src"):
                if n.get(k) and n[k] not in ids and n[k] != "own":
                    n[k] = ""
            self._drop_roles(n)

    # ------------------------------------------------------------------ dọn file không còn dùng
    @staticmethod
    def _refs(nodes) -> set:
        out = set()
        for n in nodes:
            if not n:
                continue
            for item in [n, *(n.get("versions") or [])]:
                out.update(item.get("files") or [])
                out.update(r.get("file") for r in item.get("ref_files") or [] if r.get("file"))  # 📎 ảnh tham chiếu
                out.update(v for v in (item.get("out") or {}).values() if isinstance(v, str) and v.startswith("nodes/"))
        return out

    def _gc(self, bid: str) -> int:
        """Xoá file trong nodes/ không còn khối / phiên bản / bước hoàn tác nào dùng (cũ hơn GC_AGE, tránh file đang ghi)
        + nhật ký của khối đã xoá. Trả số file đã xoá."""
        with self._lock:
            try:
                board = self.load(bid)
            except CanvasError:
                return 0
            keep = self._refs(board["nodes"])
            alive = {n["id"] for n in board["nodes"]}
            for stack in (self._undo.get(bid) or [], self._redo.get(bid) or []):
                for entry in stack:
                    keep |= self._refs(entry["nodes"].values())
                    alive |= {i for i, s in entry["nodes"].items() if s}
            cutoff, gone = time.time() - GC_AGE, 0
            folder = self.root / bid / "nodes"
            for f in folder.iterdir() if folder.is_dir() else []:
                try:
                    old = f.is_file() and f.stat().st_mtime < cutoff
                except OSError:
                    continue
                if old and f"nodes/{f.name}" not in keep:
                    self._unlink(f)
                    gone += 1
            logs = self.root / bid / "logs"
            for f in logs.glob("node-*.jsonl") if logs.is_dir() else []:
                if f.stem[5:] not in alive:
                    self._unlink(f)
            return gone

    @staticmethod
    def _node(board: dict, nid: str) -> dict:
        node = next((n for n in board["nodes"] if n["id"] == nid), None)
        if node is None:
            raise CanvasError("Không tìm thấy node")
        return node

    def _url(self, bid: str, rel: str) -> str:
        path = self.root / bid / rel
        return f"/media/{self.dirname}/{bid}/{rel}?v={int(path.stat().st_mtime)}" if path.is_file() else ""

    def public_node(self, bid: str, node: dict) -> dict:
        from . import api_mode

        out = {**node, "urls": [u for u in (self._url(bid, f) for f in node.get("files") or []) if u]}
        if node.get("ref_files"):  # 📎 ảnh tham chiếu trong khối → ảnh nhỏ trên thẻ
            out["ref_urls"] = [{"url": self._url(bid, r.get("file", "")), "role": r.get("role") or "", "file": r.get("file")}
                               for r in node["ref_files"]]
        if node.get("qc_required"):  # ✅ trạng thái kiểm duyệt của ĐÚNG file hiện tại (tạo lại → chờ duyệt lại)
            out["qc_state"] = self.qc_state(node)
        if not api_mode.enabled(self.settings):  # 🔑 hiện model sẽ dùng thật (model API cũ → bản trình duyệt)
            if node["kind"] in ("image", "video") and api_mode.is_api(node.get("engine")):
                out["engine"] = api_mode.pick(node["engine"], IMAGE_ENGINES if node["kind"] == "image" else VIDEO_ENGINES)
            elif node["kind"] == "wf" and isinstance(node.get("config"), dict):
                out["config"] = api_mode.config(node["config"], self.settings)
        if node.get("versions"):  # 🕘 phiên bản trước: link xem + chữ (khối chữ) để chọn lại
            out["vers"] = [{"urls": [u for u in (self._url(bid, f) for f in v.get("files") or []) if u],
                            "text": _short((v.get("out") or {}).get("text"), 400), "at": v.get("at", ""),
                            "prompt": v.get("prompt", ""), "pick": v.get("pick", 0)} for v in node["versions"]]
        return out

    def public(self, board: dict) -> dict:
        return {**board, "nodes": [self.public_node(board["id"], n) for n in board["nodes"]],
                "undo": self.undo_info(board["id"])}

    def _push(self, bid: str, nid: str) -> None:
        """Báo UI 1 node vừa đổi (trạng thái, %, file mới)."""
        try:
            board = self.load(bid)
            self.emit("canvas_node", {"board": bid, "node": self.public_node(bid, self._node(board, nid))})
        except (CanvasError, OSError):
            pass

    # ------------------------------------------------------------------ bảng
    def list(self) -> list[dict]:
        out = []
        for f in self.root.glob("*/board.json"):
            try:
                b = read_json(f)
            except (OSError, ValueError):
                continue
            if b.get("task_of"):  # 📋 bảng chạy của 1 tác vụ — xem ở màn Tác vụ
                continue
            thumb = next((self._url(b["id"], n["files"][min(int(n.get("pick") or 0), len(n["files"]) - 1)])
                          for n in reversed(b["nodes"]) if n.get("files") and n["kind"] != "video"), "")
            runs = b.get("runs") or []
            last = runs[-1] if runs else None
            kinds = {n["id"]: (n.get("wtype") or n["kind"]) for n in b["nodes"]}
            out.append({"id": b["id"], "name": b["name"], "updated_at": b.get("updated_at", ""),
                        "created_at": b.get("created_at", ""), "nodes": len(b["nodes"]),
                        "edges": sum(len(n.get("inputs") or []) for n in b["nodes"]), "thumb": thumb,
                        "chain": [kinds[i] for i in self._topo(b)][:14],  # thứ tự chạy → chuỗi biểu tượng trên thẻ
                        "runs": len(runs), "runs_today": sum(1 for r in runs if str(r.get("at", ""))[:10] == now()[:10]),
                        "last_run": {k: last.get(k) for k in ("id", "label", "status", "at", "ended")} if last else None,
                        "running": any(n.get("status") in ACTIVE for n in b["nodes"]),
                        "schedule": self._schedule_info(b.get("schedule"))})
        return sorted(out, key=lambda x: x["updated_at"], reverse=True)

    @staticmethod
    def _schedule_info(s: dict | None) -> dict | None:
        """Lịch chạy cho thẻ ở màn danh sách (kèm mô tả bằng chữ)."""
        from .canvas_schedule import describe

        return {**s, "desc": describe(s)} if s else None

    def duplicate_board(self, bid: str) -> dict:
        """Nhân bản cả Canvas (node, dây nối, ảnh / video đã tạo) — bản sao chưa có lịch sử chạy."""
        src = self.dir(bid)
        board = self.load(bid)
        name = f"{board['name']} (bản sao)"[:80]
        new = f"{slugify(name, 30) or 'canvas'}-{uuid.uuid4().hex[:6]}"
        shutil.copytree(src, self.root / new, ignore=shutil.ignore_patterns("runs", "logs"))
        board.update(id=new, name=name, created_at=now(), runs=[], run_seq=0)
        for n in board["nodes"]:
            if n.get("status") in ACTIVE:
                n.update(status="idle", pct=0, task="", approval={})
            n.pop("log_at", None)
        return self.public(self._save(board))

    def create(self, name: str = "") -> dict:
        name = " ".join(str(name or "").split())[:80] or f"Canvas {datetime.now():%d/%m %H:%M}"
        bid = f"{slugify(name, 30) or 'canvas'}-{uuid.uuid4().hex[:6]}"
        (self.root / bid / "nodes").mkdir(parents=True, exist_ok=True)
        board = {"id": bid, "name": name, "created_at": now(), "updated_at": now(), "seq": 0, "nodes": [], "sig_v": SIG_V}
        return self.public(self._save(board))

    def open(self, bid: str) -> dict:
        def fix(board):  # app tắt giữa chừng → node đang chạy không còn tác vụ nào theo dõi
            live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
            for n in board["nodes"]:
                if n.get("status") in ACTIVE and n.get("task") not in live:
                    n.update(status="error", error="Đã dừng (app được mở lại) — bấm Tạo lại", pct=0, approval={})
        board = self._edit(bid, fix)
        try:  # dọn file của khối đã xoá / phiên bản đã bỏ (không còn bước hoàn tác nào cần)
            self._gc(bid)
        except OSError:
            pass
        return self.public(board)

    def rename(self, bid: str, name: str) -> dict:
        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise CanvasError("Tên bảng trống")
        return self.public(self._edit(bid, lambda b: b.update(name=name)))

    def delete(self, bid: str) -> None:
        path = self.dir(bid)
        for n in self.load(bid)["nodes"]:
            if n.get("status") in ACTIVE and n.get("task"):
                self.pool.cancel(n["task"])
        shutil.rmtree(path, ignore_errors=True)
        self._undo.pop(bid, None)
        self._redo.pop(bid, None)

    # ------------------------------------------------------------------ node
    def _defaults(self, kind: str) -> dict:
        info = meta(self.settings)["defaults"]
        from . import api_mode

        info = {**info, "image": api_mode.pick(info["image"], IMAGE_ENGINES, self.settings),
                "video": api_mode.pick(info["video"], VIDEO_ENGINES, self.settings)}
        if self.flow:  # 🎬 màn Grok Canvas: model định sẵn
            m = self.models()
            info.update(image=m["image"], video=m["video"])
        elif kind == "flow":  # 🎥 khối Google Flow = khối Video cố định model Google Flow
            info["video"] = FLOW_ENGINE
        elif kind == "video" and info["video"] == FLOW_ENGINE:  # Google Flow là khối riêng → khối Video thường dùng Grok
            info["video"] = "grok_browser"
        if kind in ("video", "flow"):
            spec = VIDEO_ENGINES[info["video"]]
            return {"engine": info["video"], "aspect": "9:16" if "9:16" in spec["aspects"] else spec["aspects"][0],
                    "duration": "10s" if "10s" in spec["durations"] else spec["durations"][-1],
                    "resolution": "720p" if "720p" in spec["resolutions"] else spec["resolutions"][0],
                    "first_frame": True}
        spec = IMAGE_ENGINES[info["image"]]
        return {"engine": info["image"], "aspect": "9:16" if "9:16" in spec["aspects"] else spec["aspects"][0],
                "count": 1}

    def _new_node(self, board: dict, kind: str, x: float, y: float, inputs: list, prompt: str, wtype: str = "") -> dict:
        if len(board["nodes"]) >= MAX_NODES:
            raise CanvasError(f"Mỗi bảng tối đa {MAX_NODES} node")
        preset = kind  # "flow" → node Video cố định model Google Flow
        kind = "video" if kind == "flow" else kind
        board["seq"] = int(board.get("seq") or 0) + 1
        ids = {n["id"] for n in board["nodes"]}
        node = {"id": f"n{board['seq']}", "kind": kind, "x": float(x), "y": float(y), "title": "",
                "prompt": str(prompt or "")[:4000], "inputs": [i for i in (inputs or []) if i in ids][:MAX_INPUTS],
                "files": [], "pick": 0, "status": "idle", "pct": 0, "error": "", "task": ""}
        if kind == "wf":
            from .workflow import nodes as wfn

            from . import api_mode

            node.update(wtype=wtype, out={}, approval={},  # 🔑 mặc định model API → bản trình duyệt khi đang tắt API
                        config=api_mode.config({k: v for k, v in wfn.defaults(wtype).items() if _shown(wtype, k)},
                                               self.settings))
            if self.flow and wtype == "product_studio":  # 🎬 Grok Canvas: ảnh bìa từng cảnh (duyệt) → Grok cho chuyển động
                node["config"]["mode"] = "frames"
        elif kind == "upload":
            node["ask"] = False  # ❓ hỏi chọn ảnh mỗi lần chạy quy trình
        else:
            node.update(self._defaults(preset))
        board["nodes"].append(node)
        return node

    def _result(self, bid: str, board: dict, nid: str) -> dict:
        return {"board": self.public(board), "node": self.public_node(bid, self._node(board, nid))}

    def add_node(self, bid: str, kind: str, x: float = 0, y: float = 0, inputs: list | None = None,
                 prompt: str = "", wtype: str = "") -> dict:
        if kind not in ("image", "video", "flow", "wf", "upload") or (kind == "wf" and wtype not in WF_TYPES):
            raise CanvasError("Loại node không hợp lệ")
        holder = {}

        def add(b):
            node = self._new_node(b, kind, x, y, [] if kind == "upload" else inputs or [], prompt, wtype)
            if kind == "upload":  # Ảnh đầu vào trống: chọn ảnh sau, hoặc để hỏi khi chạy quy trình
                node.update(title="Ảnh đầu vào", ask=True)
            holder["node"] = node
        name = wf_types()[wtype]["name"] if kind == "wf" else {"image": "Ảnh", "video": "Video", "flow": "Google Flow",
                                                                "upload": "Ảnh đầu vào"}[kind]
        board = self._edit(bid, add, undo=f"Thêm khối {name}")
        return self._result(bid, board, holder["node"]["id"])

    def upload(self, bid: str, path: str, x: float = 0, y: float = 0) -> dict:
        src = Path(path or "")
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
            raise CanvasError("Chọn file ảnh (png, jpg, webp)")
        holder = {}

        def add(board):
            node = self._new_node(board, "upload", x, y, [], "")
            rel = f"nodes/{node['id']}_up{src.suffix.lower()}"
            shutil.copy2(src, self.root / bid / rel)
            node.update(title=src.stem[:60], files=[rel], status="done", pct=100, done_at=now())
            holder["node"] = node
        board = self._edit(bid, add, undo=f"Tải ảnh lên “{src.stem[:30]}”")
        return self._result(bid, board, holder["node"]["id"])

    def replace_image(self, bid: str, nid: str, path: str) -> dict:
        """Thay ảnh của node ảnh (tải lên hoặc ảnh AI đã tạo) bằng ảnh khác trên máy — giữ vị trí + dây nối;
        node phía sau thấy đầu vào đổi → lần chạy quy trình sau tự chạy lại."""
        src = Path(path or "")
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
            raise CanvasError("Chọn file ảnh (png, jpg, webp)")

        def apply(board):
            node = self._node(board, nid)
            if node["kind"] not in ("upload", "image"):
                raise CanvasError("Chỉ thay được ảnh của node ảnh")
            if node.get("status") in ACTIVE:
                raise CanvasError("Node đang chạy — chờ xong hoặc bấm Dừng")
            rel = f"nodes/{nid}_up{int(time.time())}{src.suffix.lower()}"
            shutil.copy2(src, self.root / bid / rel)
            self._archive(node)  # ảnh cũ vào 🕘 Phiên bản (chọn lại được) — không xoá ngay
            node.update(files=[rel], pick=0, status="done", pct=100, error="", stage="", done_at=now(),
                        made=f"Ảnh của bạn: {src.name}"[:300])
            if node["kind"] == "upload":
                node["title"] = src.stem[:60]
            else:  # ảnh AI bị thay bằng ảnh của bạn → ghi chú để biết, và coi như đã có kết quả mới nhất
                node["title"] = f"ảnh thay: {src.stem[:40]}"
                node["sig"], node["sig_own"] = self._sig(board, nid, raw=True), self._sig_own(node)
        board = self._edit(bid, apply)
        return self._result(bid, board, nid)

    def update_nodes(self, bid: str, changes: list, record: bool = True) -> dict:
        """Lưu vị trí / prompt / tuỳ chọn của các node (UI gửi sau khi kéo thả, gõ prompt, đổi model).
        record = ghi bước ↶ hoàn tác (tắt khi app tự điền, VD lời thoại vừa phân tích)."""
        def apply(board):
            for ch in changes or []:
                node = next((n for n in board["nodes"] if n["id"] == ch.get("id")), None)
                if node is None:
                    continue
                for k in EDITABLE:
                    if k in ch:
                        node[k] = float(ch[k]) if k in ("x", "y") else ch[k]
                if "ask_fields" in ch:  # ❓ chỉ hỏi các ô này khi chạy (rỗng = hỏi mọi ô)
                    raw = ch["ask_fields"] if isinstance(ch["ask_fields"], list) else []
                    node["ask_fields"] = list(dict.fromkeys(str(x)[:60] for x in raw if str(x).strip()))[:40]
                    if not node["ask_fields"]:
                        node.pop("ask_fields")
                if "w" in ch:
                    node["w"] = max(NODE_W[0], min(NODE_W[1], round(float(ch["w"])))) if ch["w"] else 0
                if "ask_pos" in ch:  # ❓ thứ tự trong hộp Kiểm tra trước khi chạy (không ảnh hưởng chạy lại)
                    try:
                        node["ask_pos"] = max(0, min(999, int(ch["ask_pos"])))
                    except (TypeError, ValueError):
                        node.pop("ask_pos", None)
                if isinstance(ch.get("roles"), dict):  # vai trò dây nối vào: chỉ nhận dây đang nối + vai trò hợp lệ
                    allowed = ROLES.get(node.get("wtype") or node["kind"], ())
                    roles = {k: v for k, v in ch["roles"].items() if k in (node.get("inputs") or []) and v in allowed}
                    if roles:
                        node["roles"] = roles
                    else:
                        node.pop("roles", None)
                if node["kind"] == "wf":
                    if isinstance(ch.get("config"), dict):  # chỉ nhận đúng các ô của block đó
                        keys = {f["key"] for f in wf_types()[node["wtype"]]["fields"]}
                        node["config"].update({k: v for k, v in ch["config"].items() if k in keys})
                    if "out_text" in ch:  # sửa chữ kết quả (bài viết, prompt AI viết…) trước khi dùng tiếp
                        node.setdefault("out", {})["text"] = str(ch["out_text"])[:20000]
                    continue
                if isinstance(ch.get("ref_files"), list) and node["kind"] in ("image", "video"):
                    # 📎 ảnh tham chiếu trong khối: chỉ đổi vai trò / thứ tự / bỏ ảnh ĐÃ có (thêm ảnh qua add_refs)
                    have = {r.get("file") for r in node.get("ref_files") or []}
                    node["ref_files"] = [{"file": r["file"], "role": r.get("role") if r.get("role") in IMAGE_REF_ROLES else ""}
                                         for r in ch["ref_files"] if isinstance(r, dict) and r.get("file") in have][:MAX_INPUTS]
                    if not node["ref_files"]:
                        node.pop("ref_files")
                if node["kind"] == "video" and any(k in ch for k in ("template", "build", "tpl_ai")):
                    from . import video_templates as vt  # 🎞 mẫu video: id phải có thật, cách dựng one / split

                    if not node.get("template") or vt.get(str(node["template"])) is None:
                        node.pop("template", None)
                    if "build" in ch or node.get("template"):  # không mẫu + chưa chọn → giữ cách cũ (theo auto_split)
                        node["build"] = node["build"] if node.get("build") in ("split", "story") else "one"
                    node["tpl_ai"] = node.get("tpl_ai") is not False
                if "angles" in ch and node["kind"] == "image":  # 🧍 / 📦 preset bảng nhiều góc ("" = ảnh thường)
                    node["angles"] = ch["angles"] if ch["angles"] in ANGLES else ""
                node["prompt"] = str(node.get("prompt") or "")[:4000]
                node["pick"] = max(0, min(int(node.get("pick") or 0), max(0, len(node.get("files") or []) - 1)))
                self._fit_options(node)
        ids = sorted({str(ch.get("id")) for ch in changes or [] if ch.get("id")})
        moved = all(set(ch) <= {"id", "x", "y"} for ch in changes or [])
        label = ("Di chuyển " if moved else "Sửa ") + (", ".join(ids[:3]) + ("…" if len(ids) > 3 else "") if ids else "khối")
        return self.public(self._edit(bid, apply, undo=label if record else "",
                                      key=("move:" if moved else "edit:") + ",".join(ids)))

    @staticmethod
    def _fit_options(node: dict) -> None:
        """Model đổi → tỉ lệ / số ảnh / thời lượng / độ phân giải về giá trị model đó hỗ trợ."""
        if node["kind"] == "image":
            if node.get("engine") not in IMAGE_ENGINES:
                from . import api_mode

                node["engine"] = api_mode.pick("openai_api", IMAGE_ENGINES)
            node["aspect"], node["count"] = normalize_image(node["engine"], node.get("aspect") or "",
                                                            int(node.get("count") or 1))
        elif node["kind"] == "video":
            from .llm.video_engines import resolve as resolve_video

            node["engine"] = resolve_video(node.get("engine"))  # model đã bỏ (AI Studio) → model thay thế (Flow)
            if node.get("engine") not in VIDEO_ENGINES:
                node["engine"] = "grok_browser"
            spec = VIDEO_ENGINES[node["engine"]]
            for key, opts in (("aspect", spec["aspects"]), ("duration", spec["durations"]),
                              ("resolution", spec["resolutions"])):
                if node.get(key) not in opts:
                    node[key] = opts[0]

    def _reaches(self, board: dict, start: str, goal: str) -> bool:
        """start có nằm phía trên goal không (đi ngược theo inputs từ goal)."""
        seen, stack = set(), [goal]
        while stack:
            cur = stack.pop()
            if cur == start:
                return True
            if cur not in seen:
                seen.add(cur)
                stack.extend(next((n["inputs"] for n in board["nodes"] if n["id"] == cur), []))
        return False

    @staticmethod
    def label(node: dict) -> str:
        if node["kind"] == "wf":
            return wf_types()[node["wtype"]]["name"]
        if is_flow(node):
            return "Google Flow"  # màn Grok Canvas: khối Flow cũ đã tự đổi sang Grok khi mở bảng (_lock_models)
        return {"image": "Ảnh", "video": "Video", "upload": "Ảnh tải lên"}[node["kind"]]

    def connect(self, bid: str, src: str, dst: str, on: bool = True) -> dict:
        def apply(board):
            target, source = self._node(board, dst), self._node(board, src)
            if not on:
                target["inputs"] = [i for i in target["inputs"] if i != src]
                if target.get("dialogue_src") == src:  # bỏ nối nguồn lời thoại → quay về tự nhập
                    target["dialogue_src"] = ""
                self._drop_roles(target)
                return
            outs = out_types(source)
            if target["kind"] == "upload" and source.get("wtype") != "web_research":
                raise CanvasError("Ảnh tải lên chỉ nhận ảnh sản phẩm từ khối 🌐 Tra cứu web (tìm được ảnh thì thay ảnh này)")
            if src == dst or not outs & in_types(target):
                raise CanvasError(f"“{self.label(target)}” không nhận được đầu ra của “{self.label(source)}”")
            if self._reaches(board, dst, src):
                raise CanvasError("Không nối vòng tròn")
            if src in target["inputs"]:
                return
            if len(target["inputs"]) >= MAX_INPUTS:
                raise CanvasError(f"Mỗi node nhận tối đa {MAX_INPUTS} dây nối")
            target["inputs"] = target["inputs"] + [src]
        return self.public(self._edit(bid, apply, undo=f"{'Nối' if on else 'Bỏ nối'} {src} → {dst}"))

    @staticmethod
    def _drop_roles(node: dict) -> None:
        """Bỏ vai trò của dây không còn nối."""
        roles = {k: v for k, v in (node.get("roles") or {}).items() if k in (node.get("inputs") or [])}
        if roles:
            node["roles"] = roles
        else:
            node.pop("roles", None)

    def reorder_inputs(self, bid: str, nid: str, ids: list) -> dict:
        """Đổi thứ tự dây nối vào (thứ tự gửi model / ghép video / vật liệu storyboard) — hoàn tác được."""
        def apply(board):
            node = self._node(board, nid)
            cur = list(node.get("inputs") or [])
            if sorted(ids or []) != sorted(cur):
                raise CanvasError("Danh sách đầu vào không khớp — tải lại Canvas")
            node["inputs"] = list(ids)
        return self.public(self._edit(bid, apply, undo=f"Đổi thứ tự đầu vào {nid}"))

    def delete_node(self, bid: str, nid: str) -> dict:
        """Xoá 1 node (dừng nếu đang chạy, gỡ dây nối tới nó). File kết quả GIỮ LẠI tới khi không còn bước hoàn tác nào cần
        (↶ hoàn tác trả lại khối nguyên vẹn) — dọn khi mở lại bảng."""
        def apply(board):
            node = self._node(board, nid)
            if node.get("status") in ACTIVE and node.get("task"):
                self.pool.cancel(node["task"])
            board["nodes"] = [n for n in board["nodes"] if n["id"] != nid]
            for n in board["nodes"]:
                n["inputs"] = [i for i in n.get("inputs") or [] if i != nid]
                if n.get("dialogue_src") == nid:
                    n["dialogue_src"] = ""
                if n.get("prompt_src") == nid:
                    n["prompt_src"] = ""
                self._drop_roles(n)
        return self.public(self._edit(bid, apply, undo=f"Xoá khối {nid}"))

    # ------------------------------------------------------------------ nhóm / ghi chú
    @staticmethod
    def _clean_group(group: dict, src: dict) -> None:
        for k in ("x", "y"):
            if k in src:
                group[k] = round(float(src[k]))
        for k, lo in (("w", 180), ("h", 110)):
            if k in src:
                group[k] = max(lo, min(20000, round(float(src[k]))))
        if "title" in src:
            group["title"] = " ".join(str(src["title"] or "").split())[:80]
        if "note" in src:
            group["note"] = str(src["note"] or "")[:5000]
        if src.get("color") in GROUP_COLORS:
            group["color"] = src["color"]

    def add_group(self, bid: str, data: dict | None = None) -> dict:
        made = {}

        def add(board):
            groups = board.setdefault("groups", [])
            if len(groups) >= MAX_GROUPS:
                raise CanvasError(f"Tối đa {MAX_GROUPS} nhóm mỗi Canvas")
            board["gseq"] = int(board.get("gseq") or 0) + 1
            group = {"id": f"g{board['gseq']}", "x": 0, "y": 0, "w": 440, "h": 280, "title": "Nhóm mới", "note": "",
                     "color": "yellow"}
            self._clean_group(group, data or {})
            groups.append(group)
            made["id"] = group["id"]
        board = self._edit(bid, add, undo="Thêm nhóm")
        return {"board": self.public(board), "group": made["id"]}

    def update_group(self, bid: str, gid: str, patch: dict | None = None, moves: list | None = None) -> dict:
        """Sửa nhóm (vị trí, cỡ, tên, ghi chú, màu); moves = vị trí mới của các node kéo theo nhóm (lưu cùng lúc)."""
        def apply(board):
            group = next((g for g in board.get("groups") or [] if g["id"] == gid), None)
            if group is None:
                raise CanvasError("Không tìm thấy nhóm")
            self._clean_group(group, patch or {})
            for m in moves or []:
                node = next((n for n in board["nodes"] if n["id"] == m.get("id")), None)
                if node is not None:
                    node["x"], node["y"] = float(m["x"]), float(m["y"])
        return self.public(self._edit(bid, apply, undo=f"Sửa nhóm {gid}", key=f"group:{gid}"))

    def delete_group(self, bid: str, gid: str) -> dict:
        """Xoá khung nhóm — các node bên trong giữ nguyên."""
        def apply(board):
            board["groups"] = [g for g in board.get("groups") or [] if g["id"] != gid]
        return self.public(self._edit(bid, apply, undo=f"Xoá nhóm {gid}"))

    def duplicate(self, bid: str, nid: str) -> dict:
        node = self._node(self.load(bid), nid)
        if node["kind"] == "upload":
            raise CanvasError("Node tải lên không nhân bản được — tải ảnh lên lại")
        with self.batch(bid, f"Nhân bản {nid}"):
            res = self.add_node(bid, node["kind"], node["x"] + 40, node["y"] + 40, node["inputs"], node.get("prompt", ""),
                                node.get("wtype", ""))
            keep = {k: node[k] for k in ("engine", "aspect", "count", "duration", "resolution", "config") if k in node}
            board = self.update_nodes(bid, [{"id": res["node"]["id"], **keep}])
        board = self.public(self.load(bid))
        return {"board": board, "node": next(n for n in board["nodes"] if n["id"] == res["node"]["id"])}

    # ------------------------------------------------------------------ 🔁 đổi loại khối
    CONVERT_TEXT = ("prompt", "text", "topic", "product", "idea", "request")  # ô chữ chính của khối wf (ưu tiên trước)

    def _node_text(self, node: dict) -> str:
        if node["kind"] in ("image", "video"):
            return str(node.get("prompt") or "").strip()
        cfg = node.get("config") or {}
        return next((str(cfg[k]).strip() for k in self.CONVERT_TEXT if str(cfg.get(k) or "").strip()), "")

    def convert(self, bid: str, nid: str, kind: str, wtype: str = "") -> dict:
        """🔁 Đổi loại khối TẠI CHỖ: giữ mã khối, vị trí, tên, chữ (prompt / nội dung → ô chữ chính của khối mới) và các dây
        nối còn hợp kiểu; dây không hợp bị gỡ (báo lại). Kết quả cũ bỏ — ↶ hoàn tác trả lại nguyên khối cũ."""
        if kind not in ("image", "video", "flow", "wf") or (kind == "wf" and wtype not in WF_TYPES):
            raise CanvasError("Loại khối không hợp lệ")
        wtype = wtype if kind == "wf" else ""
        name = wf_types()[wtype]["name"] if kind == "wf" else {"image": "Ảnh", "video": "Video", "flow": "Google Flow"}[kind]
        info = {}

        def apply(board):
            node = self._node(board, nid)
            if node["kind"] == "upload":
                raise CanvasError("Khối Ảnh tải lên không đổi loại được — thêm khối mới rồi nối ảnh vào")
            if node.get("status") in ACTIVE:
                raise CanvasError("Khối đang chạy — chờ xong hoặc bấm Dừng")
            same = (node["kind"] == "video" and kind in ("video", "flow") and is_flow(node) == (kind == "flow")) \
                or (node["kind"] == kind and kind != "video" and (node.get("wtype") or "") == wtype)
            if same:
                raise CanvasError(f"Khối {nid} đã là “{name}”")
            old = self.label(node)
            fresh = self._new_node({"nodes": [], "seq": 0}, kind, node["x"], node["y"], [], "", wtype)
            fresh.update(id=nid, title=node.get("title", ""), **({"w": node["w"]} if node.get("w") else {}))
            text = self._node_text(node)
            if text:
                if kind != "wf":
                    fresh["prompt"] = text[:4000]
                else:
                    keys = {f["key"] for f in wf_types()[wtype]["fields"]}
                    key = next((k for k in self.CONVERT_TEXT if k in keys), None)
                    if key:
                        fresh["config"][key] = text[:8000]
            nodes = {n["id"]: n for n in board["nodes"]}
            accepts = in_types(fresh)
            fresh["inputs"] = [i for i in node.get("inputs") or [] if i in nodes and out_types(nodes[i]) & accepts]
            lost_in = [i for i in node.get("inputs") or [] if i not in fresh["inputs"]]
            gives, lost_out = out_types(fresh), []
            for n in board["nodes"]:
                if n["id"] != nid and nid in (n.get("inputs") or []) and (
                        not gives & in_types(n) or (n["kind"] == "upload" and wtype != "web_research")):
                    n["inputs"] = [i for i in n["inputs"] if i != nid]
                    for key in ("prompt_src", "dialogue_src"):
                        if n.get(key) == nid:
                            n[key] = ""
                    self._drop_roles(n)
                    lost_out.append(n["id"])
            board["nodes"][board["nodes"].index(node)] = fresh  # giữ thứ tự node (vẽ / chạy)
            info.update(old=old, lost_in=lost_in, lost_out=lost_out, kept_text=bool(text) and (
                kind != "wf" or any(k in fresh["config"] and fresh["config"][k] == text[:8000] for k in self.CONVERT_TEXT)))

        board = self._edit(bid, apply, undo=f"Đổi khối {nid} → {name}")
        return {"board": self.public(board), "node": self.public_node(bid, self._node(board, nid)), "name": name, **info}

    # ------------------------------------------------------------------ nhiều node (quét chọn trên Canvas)
    COPY_KEYS = ("engine", "aspect", "count", "duration", "resolution", "config", "title", "prompt_src", "dialogue_src",
                 "dialogue", "voice", "first_frame", "w", "ask", "auto_post", "to_posts", "auto_split")

    PART_KEYS = ("engine", "aspect", "duration", "resolution", "voice", "voice_note", "first_frame", "w", "template")

    @staticmethod
    def _build_mode(node: dict) -> str:
        """Cách dựng lời dài của khối Video chung: "one" = 🎬 Không tách (khối tự chia + quay + ghép bên trong),
        "split" = ✂ Tách khối (khối Video con + khối Ghép), "single" = 1 video (tắt tự tách, khối cũ không mẫu).
        Có mẫu: mặc định "one". Không mẫu chưa chọn: theo ô tự tách cũ (auto_split, mặc định bật = "split")."""
        if node.get("build") in ("split", "story"):  # 🧭 story = Tách khối + AI phân tích lời → prompt riêng, nối ⛓
            return node["build"]
        if node.get("template") or node.get("build") == "one":
            return "one"
        return "single" if node.get("auto_split") is False else "split"

    @staticmethod
    def _parts_of(board: dict, pid: str) -> list:
        """Các video con tách từ khối Video chung pid, theo thứ tự phần 1 → N."""
        return sorted((n for n in board["nodes"] if n.get("part_of") == pid), key=lambda n: int(n.get("part") or 0))

    def split_video(self, bid: str, nid: str, auto: bool = False) -> dict:
        """✂ Khối Video CHUNG giữ nguyên (ảnh, ý tưởng / prompt từ khối ngoài, lời thoại đầy đủ); lời dài → các video con
        tách ra từ nó (dây từ khối chung), mỗi con nói 1 đoạn vừa clip (cắt ở cuối câu). Khi chạy, con dùng ảnh / video /
        prompt của khối chung. Các con được GHÉP lại thành 1 (khối Ghép phía sau có sẵn → nối vào; chưa có → tự thêm
        "Ghép …", khối phía sau như Hậu kỳ / Đăng bài lấy video đã ghép). Gọi lại khi kịch bản đổi → đồng bộ: thêm / bớt
        con, cập nhật lời từng phần. auto = tự tách (kể cả lúc khối chung đang trong lượt chạy)."""
        info = {}

        def apply(board):
            node = self._node(board, nid)
            if node["kind"] != "video" or node.get("part_of"):
                raise CanvasError("Chỉ tách được khối Video chung (không phải 1 phần đã tách)")
            if node.get("status") in ACTIVE and not auto:
                raise CanvasError("Node đang chạy — dừng rồi tách")
            spoken = self._dialogue_text(bid, board, node).strip()
            limit = dialogue_limit(node)
            chunks = split_dialogue(spoken, limit)
            parts = self._parts_of(board, nid)
            if self._build_mode(node) == "one" and parts:  # 🎬 về "Không tách" → gỡ khối con
                chunks = []
            if len(chunks) < 2:
                if not parts:
                    raise CanvasError(f"Lời thoại vừa 1 video (≤ {limit} chữ cho {node.get('duration') or '10s'}) — không cần tách")
                chunks = []  # lời đã ngắn lại → bỏ các phần, khối chung tự quay 1 video
            if len(chunks) > MAX_INPUTS:
                raise CanvasError(f"Lời thoại quá dài ({len(chunks)} video) — khối Ghép nhận tối đa {MAX_INPUTS} video, "
                                  "hãy rút gọn lời hoặc tăng thời lượng clip")
            if len(board["nodes"]) + max(0, len(chunks) - len(parts)) + 1 > MAX_NODES:
                raise CanvasError(f"Mỗi bảng tối đa {MAX_NODES} node")
            base = node.get("title") or "Video"
            ar = str(node.get("aspect") or "9:16").split(":")
            try:
                tall = float(ar[1]) / float(ar[0])
            except (ValueError, ZeroDivisionError, IndexError):
                tall = 16 / 9
            w = float(node.get("w") or 240)
            step = w * tall + 120
            made, kept, changed = [], [], False
            story = self._build_mode(node) == "story"  # 🧭 prompt riêng từng cảnh (phân tích lời) + nối ⛓ liền mạch
            scenes = {s.get("loi"): s for s in (node.get("story") or {}).get("scenes") or [] if isinstance(s, dict)}
            for k, text in enumerate(chunks, 1):
                if k <= len(parts):
                    c = parts[k - 1]
                    changed = changed or c.get("dialogue") != text
                else:
                    c = self._new_node(board, "video", node["x"] + w + 160, node["y"] + step * (k - 1), [nid], "")
                    made.append(c["id"])
                prompt = ""
                if story:  # lời đoạn không đổi → giữ prompt (kể cả bạn đã sửa); đổi → prompt cảnh khớp lời (nếu có)
                    prompt = c.get("prompt", "") if c.get("dialogue") == text and c.get("prompt") else \
                        str((scenes.get(text) or {}).get("prompt") or "")
                prev = kept[-1] if story and kept else ""
                changed = changed or (c.get("chain_from") or "") != prev or (c.get("prompt") or "") != prompt
                c.update({key: json.loads(json.dumps(node[key])) for key in self.PART_KEYS if key in node})
                c.update(inputs=[prev, nid] if prev else [nid], part_of=nid, part=k, dialogue=text, dialogue_src="",
                         prompt=prompt, prompt_src="own", auto_split=False, title=f"{base} · {k}/{len(chunks)}")
                if prev:
                    c["chain_from"] = prev  # ⛓ quay tiếp từ khung cuối video khối trước
                else:
                    c.pop("chain_from", None)
                c.pop("roles", None)
                kept.append(c["id"])
            gone = [c["id"] for c in parts[len(chunks):]]
            board["nodes"] = [n for n in board["nodes"] if n["id"] not in gone]
            old = {nid, *kept, *gone}
            ids = kept or [nid]

            def regroup(ins, rep):  # thay cụm (khối chung / các phần cũ) bằng rep, giữ đúng chỗ, không trùng
                out, put = [], False
                for x in ins:
                    if x in old:
                        if not put:
                            out += [r for r in rep if r not in out]
                            put = True
                    elif x not in out:
                        out.append(x)
                return out

            down = [m for m in board["nodes"] if m["id"] not in kept and old & set(m.get("inputs") or [])]
            joins = [m for m in down if m.get("wtype") == "concat_video"]
            unlinked, merge = [], ""
            for m in joins:
                new = regroup(m.get("inputs") or [], ids)
                if len(new) > MAX_INPUTS:
                    unlinked.append(m["id"])
                    continue
                m["inputs"] = new
            mine = next((m for m in joins if m.get("split_of") == nid), None) or (joins[0] if joins else None)
            if mine is None and kept:  # chưa có khối Ghép → thêm: các phần 1 → N thành 1 video
                mine = self._new_node(board, "wf", node["x"] + 2 * w + 320, node["y"] + step * (len(kept) - 1) / 2,
                                      list(kept), "", "concat_video")
                mine.update(title=f"Ghép {base}", split_of=nid)
                mine["config"]["aspect"] = node.get("aspect") if node.get("aspect") in ("9:16", "16:9", "1:1") else "9:16"
                made.append(mine["id"])
            if mine is not None:
                merge = mine["id"]
                for m in down:  # khối phía sau (Hậu kỳ, Đăng bài…) lấy video đã ghép
                    if m.get("wtype") != "concat_video":
                        m["inputs"] = regroup(m.get("inputs") or [], [merge])
            node["split_n"] = len(kept)
            info.update(nodes=kept, parts=len(kept), made=made, gone=gone, unlinked=unlinked, chunks=chunks, merge=merge,
                        relinked=[m["id"] for m in down], changed=bool(made or gone or changed))

        board = self._edit(bid, apply, undo=f"Tách lời thoại {nid}")
        if info.get("gone"):
            self.emit("canvas_drop", {"board": bid, "nodes": info["gone"]})
        return {"board": self.public(board), **info}

    def _wants_split(self, bid: str, board: dict, node: dict) -> bool:
        """Khối Video chung cần tách / đồng bộ các phần: bật tự tách và (lời dài hơn mức nói kịp, hoặc đã có phần)."""
        if node["kind"] != "video" or node.get("part_of") or node.get("locked"):
            return False
        mode = self._build_mode(node)  # chọn "✂ Tách khối" → luôn tự tách (kể cả khi đã tắt ô tự tách cũ)
        if mode == "single":
            return False
        if mode == "one":  # 🎬 "Không tách": khối tự chia + ghép bên trong
            return bool(self._parts_of(board, node["id"]))  # còn khối con của lần "Tách khối" trước → gỡ
        if self._parts_of(board, node["id"]):
            return True
        spoken = self._dialogue_text(bid, board, node).strip()
        return bool(spoken) and dialogue_words({"dialogue": spoken}) > dialogue_limit(node)

    def auto_split(self, bid: str, nid: str) -> dict:
        """✂ Tự tách ngay (không chờ bấm nút, không chờ chạy): lời thoại (tự nhập / lấy từ khối kịch bản) dài → video con
        tách từ khối chung + ghép; kịch bản đổi → đồng bộ lại. split = có thay đổi."""
        board = self.load(bid)
        node = self._node(board, nid)
        if node.get("status") in ACTIVE or not self._wants_split(bid, board, node):
            return {"split": False}
        try:
            res = self.split_video(bid, nid)
        except CanvasError as exc:
            return {"split": False, "error": str(exc)}
        return {"split": res["changed"], **res}

    def _announce_split(self, bid: str, nid: str, res: dict, why: str = "") -> None:
        for i in [nid, *res["nodes"], *([res["merge"]] if res["merge"] else []), *res["relinked"]]:
            if self._has(self.load(bid), i):
                self._push(bid, i)
        self.pool.log(f"✂ {nid}{why}: tách {res['parts']} video từ khối chung ({', '.join(res['nodes'])})"
                      + (f", ghép lại ở {res['merge']}" if res["merge"] else "") if res["parts"]
                      else f"✂ {nid}: lời đã vừa 1 clip — bỏ các phần tách, khối chung tự quay", "ok")

    def _split_readers(self, bid: str, sid: str) -> None:
        """Khối kịch bản / lời thoại sid vừa có chữ → khối Video chung lấy lời từ nó (không trong lượt chạy) tự tách /
        đồng bộ ngay; khối đang trong lượt chạy để bộ chạy làm lúc tới lượt."""
        try:
            readers = [n["id"] for n in self.load(bid)["nodes"] if n["kind"] == "video" and n.get("dialogue_src") == sid]
        except CanvasError:
            return
        for vid in readers:
            res = self.auto_split(bid, vid)
            if res.get("split"):
                self._announce_split(bid, vid, res, f" (lời từ {sid})")

    def _auto_split(self, bid: str, board: dict, node: dict, order: list, rid: str) -> bool:
        """✂ Bộ chạy: ngay trước khối Video chung (khối phía trước đã xong → biết lời thoại thật) → tách / đồng bộ các
        video con + khối Ghép, nối vào lượt đang chạy. Không hỏi lại. True = bảng vừa đổi."""
        if not self._wants_split(bid, board, node):
            return False
        nid = node["id"]
        try:
            res = self.split_video(bid, nid, auto=True)
        except CanvasError as exc:
            self.pool.log(f"{nid}: lời thoại dài nhưng chưa tự tách được ({exc}) — quay 1 video", "warn")
            return False
        add = [i for i in res["nodes"] + ([res["merge"]] if res["merge"] else []) if i not in order]
        if not add and not res["changed"]:
            return False
        at = order.index(nid) + 1 if nid in order else len(order)
        order[at:at] = add
        for i in add:
            self._set_node(bid, i, status="queued", pct=0, error="", task=node.get("task") or "")
            self._run_record(bid, rid, node=(i, "queued"))
        self._announce_split(bid, nid, res)
        return True

    def duplicate_nodes(self, bid: str, ids: list, dx: float = 60, dy: float = 60) -> dict:
        """Nhân bản nhiều node 1 lần: dây nối GIỮA các node được chọn chuyển sang bản sao (cả nhóm như 1 khối mới),
        dây từ node ngoài nhóm giữ nguyên. Node Tải lên không nhân bản (bản sao vẫn nối vào ảnh gốc)."""
        made = {}

        def apply(board):
            picked = [n for n in board["nodes"] if n["id"] in set(ids or []) and n["kind"] != "upload"]
            if not picked:
                raise CanvasError("Chưa chọn node nào nhân bản được (node Tải lên không nhân bản)")
            for src in picked:
                copy = self._new_node(board, src["kind"], src["x"] + dx, src["y"] + dy, [], src.get("prompt", ""),
                                      src.get("wtype", ""))
                copy.update({k: json.loads(json.dumps(src[k])) for k in self.COPY_KEYS if k in src})
                made[src["id"]] = copy
            for src in picked:  # nối lại: node trong nhóm → bản sao của nó; node ngoài nhóm → giữ
                copy = made[src["id"]]
                copy["inputs"] = [made[i]["id"] if i in made else i for i in src.get("inputs") or []][:MAX_INPUTS]
                for key in ("prompt_src", "dialogue_src"):
                    if copy.get(key) in made:
                        copy[key] = made[copy[key]]["id"]
        board = self._edit(bid, apply, undo=f"Nhân bản {len(ids or [])} khối")
        return {"board": self.public(board), "nodes": [c["id"] for c in made.values()]}

    def delete_nodes(self, bid: str, ids: list) -> dict:
        """Xoá nhiều node 1 lần (dừng node đang chạy, gỡ dây nối tới chúng). File kết quả giữ tới khi dọn (hoàn tác được)."""
        gone = set(ids or [])

        def apply(board):
            for node in board["nodes"]:
                if node["id"] in gone and node.get("status") in ACTIVE and node.get("task"):
                    self.pool.cancel(node["task"])
            board["nodes"] = [n for n in board["nodes"] if n["id"] not in gone]
            for n in board["nodes"]:
                n["inputs"] = [i for i in n.get("inputs") or [] if i not in gone]
                for key in ("dialogue_src", "prompt_src"):
                    if n.get(key) in gone:
                        n[key] = ""
                self._drop_roles(n)
        return self.public(self._edit(bid, apply, undo=f"Xoá {len(gone)} khối"))

    def file_of(self, bid: str, nid: str) -> Path:
        node = self._node(self.load(bid), nid)
        files = node.get("files") or []
        if not files:
            raise CanvasError("Node chưa có kết quả")
        path = self.root / bid / files[min(int(node.get("pick") or 0), len(files) - 1)]
        if not path.is_file():
            raise CanvasError("File kết quả đã bị xoá")
        return path

    def _abs(self, bid: str, rel: str) -> str:
        return str(self.root / bid / rel)

    def _outputs(self, bid: str, src: dict) -> dict:
        """Đầu ra của 1 node để đưa sang node phía sau: {images: [đường dẫn], video, text, post}."""
        files = src.get("files") or []
        if src["kind"] in ("image", "upload"):
            return {"images": [self._abs(bid, files[min(int(src.get("pick") or 0), len(files) - 1)])]} if files else {}
        if src["kind"] == "video":
            return {"video": self._abs(bid, files[0])} if files else {}
        out = dict(src.get("out") or {})
        if src.get("wtype") == "input_text" and not out.get("text"):  # Văn bản: dùng luôn chữ đang gõ, không cần Chạy
            out["text"] = str((src.get("config") or {}).get("text") or "").strip()
        if out.get("video"):
            out["video"] = self._abs(bid, out["video"])
        if out.get("images"):
            out["images"] = [self._abs(bid, x) for x in out["images"]]
        return {k: v for k, v in out.items() if v}

    def _input_text(self, bid: str, board: dict, node: dict) -> str:
        """Chữ từ node nối vào (AI viết prompt, Văn bản…) — thêm vào đầu prompt ảnh / video
        (trừ khối được chọn làm nguồn lời thoại của node Video)."""
        texts = []
        src = self._prompt_src(node)
        if src == "own":
            return ""
        for iid in [src] if src else node.get("inputs") or []:
            if iid == node.get("dialogue_src") and iid != src:
                continue
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] == "wf":
                scene = self._scene_for(src, node)
                text = str(scene.get("prompt") if scene is not None else self._outputs(bid, src).get("text") or "").strip()
                if scene and node["kind"] == "image" and text and scene.get("khung"):  # 🎞 dựng lại đúng khung storyboard
                    text = ("Recreate the FIRST reference image (one frame of the approved storyboard) as a single realistic "
                            f"{node.get('aspect') or '9:16'} still photo: same setting, same person, outfit, pose and "
                            "expression, same product and packaging, same composition and camera angle — only reframe to "
                            "fill the format. No panel borders, no grid, no collage, no text or captions.\n"
                            "This is the opening frame of the video shot:\n" + text)
                elif scene and node["kind"] == "image" and text:  # 🖼 ảnh bìa cảnh = khung mở đầu của clip
                    # nói rõ là ảnh MỚI (không có ảnh gốc): "this video shot" làm ChatGPT tưởng là sửa ảnh, đòi tải ảnh lên
                    text = ("Create ONE brand-new still photo from this text description (text-to-image — there is no "
                            "source photo to edit). It shows only the very first moment of the video shot described "
                            "below: depict the starting state, ignore camera moves and actions that happen later. Sharp, "
                            "no motion blur, no text or captions on the image.\nShot description:\n" + text)
                elif scene and not self._dialogue_text(bid, board, node).strip():  # cảnh không lời → dặn model không nói
                    text += "\n\nNo dialogue or speech — only natural ambience; no subtitles or on-screen text."
                if text:
                    texts.append(text)
        return "\n\n".join(texts)

    @staticmethod
    def _scene_for(src: dict, node: dict) -> dict | None:
        """Node Video tách từ Storyboard (node.scene = k): cảnh thứ k của khối Storyboard src ({} nếu storyboard không còn
        cảnh đó); None nếu không phải cặp Storyboard → node cảnh."""
        k = int(node.get("scene") or 0)
        if src.get("wtype") not in STORY_TYPES or k < 1:
            return None
        scenes = (src.get("out") or {}).get("scenes") or []
        return scenes[k - 1] if k <= len(scenes) else {}

    def _angle_prompt(self, board: dict, node: dict, prompt: str) -> str:
        """🧍 / 📦 Khối bảng nhiều góc: prompt preset + ghi chú của bạn. Khối nhận ảnh từ bảng nhiều góc (Video, Ảnh bìa…):
        dặn model chỉ dùng để giữ nhận diện, không vẽ / quay ra lưới nhiều góc."""
        preset = ANGLES.get(node.get("angles") or "")
        if preset:
            return preset["prompt"] + (f"\n\nAdditional details from the user: {prompt}" if prompt.strip() else "")
        whats = {ANGLES[src["angles"]]["what"] for src in (self._node(board, i) for i in node.get("inputs") or []
                                                            if self._has(board, i))
                 if src.get("angles") in ANGLES and src.get("files")}
        if not whats:
            return prompt
        what = whats.pop() if len(whats) == 1 else "person / product"
        return "\n\n".join(x for x in (prompt, ANGLE_NOTE.format(what=what)) if x)

    def _scene_frame(self, board: dict, node: dict) -> Path | None:
        """🎞 Khung storyboard của cảnh (ảnh bìa / video tách từ Storyboard có tấm storyboard nối vào) — None nếu không có."""
        sid = node.get("cover_of") or node.get("scene_of")
        if not sid or not self._has(board, sid):
            return None
        scene = self._scene_for(self._node(board, sid), node) or {}
        path = Path(str(scene.get("khung") or ""))
        return path if scene.get("khung") and path.is_file() else None

    @staticmethod
    def _prompt_src(node: dict) -> str:
        """Nguồn prompt của node Ảnh / Video: "" = ghép chữ khối nối vào + prompt viết thêm (mặc định), "own" = chỉ prompt
        viết trực tiếp, id khối = chỉ lấy chữ khối đó (khối đã bỏ nối → về mặc định)."""
        src = str(node.get("prompt_src") or "")
        if src in ("", "own"):
            return src
        return src if src in (node.get("inputs") or []) else ""

    def _own_prompt(self, node: dict) -> str:
        """Prompt viết trực tiếp trên node — bỏ qua khi node lấy prompt từ 1 khối nối vào."""
        src = self._prompt_src(node)
        return "" if src not in ("", "own") else (node.get("prompt") or "").strip()

    def _dialogue_text(self, bid: str, board: dict, node: dict) -> str:
        """Lời thoại của node Video: chữ của khối nguồn đã chọn (Văn bản, AI viết…) nếu còn nối, không thì tự nhập."""
        sid = node.get("dialogue_src") or ""
        if sid and sid in (node.get("inputs") or []):
            src = next((n for n in board["nodes"] if n["id"] == sid), None)
            if src is not None:
                scene = self._scene_for(src, node)  # node cảnh của Storyboard → lời thoại đúng cảnh đó
                return str(scene.get("loi") if scene is not None else self._outputs(bid, src).get("text") or "").strip()
        return str(node.get("dialogue") or "")

    def add_refs(self, bid: str, nid: str, paths: list, role: str = "") -> dict:
        """📎 Ảnh tham chiếu đính kèm NGAY trong khối Ảnh (hiện nhỏ trên thẻ khối, không tạo khối tải lên riêng)."""
        files = [Path(p) for p in paths or [] if Path(p).is_file() and Path(p).suffix.lower() in IMAGE_EXT]
        if not files:
            raise CanvasError("Chọn file ảnh (png, jpg, webp)")
        role = role if role in IMAGE_REF_ROLES else ""

        def apply(board):
            node = self._node(board, nid)
            if node["kind"] not in ("image", "video"):
                raise CanvasError("Chỉ khối Ảnh / Video (Google Flow) đính kèm được ảnh tham chiếu")
            refs = list(node.get("ref_files") or [])
            stamp = time.time_ns()
            for k, src in enumerate(files, 1):
                if len(refs) >= MAX_INPUTS:
                    break
                rel = f"nodes/{nid}_ref_{stamp}_{k}{src.suffix.lower()}"
                shutil.copy2(src, self.root / bid / rel)
                refs.append({"file": rel, "role": role})
            node["ref_files"] = refs
        board = self._edit(bid, apply, undo=f"Đính kèm ảnh tham chiếu vào {nid}")
        return {"board": self.public(board), "node": self.public_node(bid, self._node(board, nid))}

    def _ref_paths(self, bid: str, node: dict) -> list[tuple[Path, str]]:
        """📎 (đường dẫn, vai trò) ảnh tham chiếu đính kèm trong khối."""
        out = []
        for r in node.get("ref_files") or []:
            path = self.root / bid / str(r.get("file") or "")
            if r.get("file") and path.is_file():
                out.append((path, r.get("role") or ""))
        return out

    def _input_images(self, bid: str, board: dict, node: dict) -> list[Path]:
        out = [p for p, _ in self._ref_paths(bid, node)] if node.get("kind") in ("image", "video") else []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] in ("image", "upload") and src.get("files"):
                path = self.root / bid / src["files"][min(int(src.get("pick") or 0), len(src["files"]) - 1)]
                if path.is_file():
                    out.append(path)
        return out

    def _image_roles(self, bid: str, board: dict, node: dict) -> dict:
        """📎 Khối Ảnh: đường dẫn ảnh nối vào → vai trò (nhân vật / sản phẩm / bối cảnh / phong cách) đã chọn."""
        roles = node.get("roles") or {}
        out = {str(p): r for p, r in self._ref_paths(bid, node) if r in IMAGE_REF_ROLES}  # 📎 ảnh trong khối
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if roles.get(iid) in IMAGE_REF_ROLES and src and src["kind"] in ("image", "upload") and src.get("files"):
                out[str(self.root / bid / src["files"][min(int(src.get("pick") or 0), len(src["files"]) - 1)])] = roles[iid]
        return out

    def _video_images(self, bid: str, board: dict, node: dict) -> tuple[list[Path], bool]:
        """Ảnh nối vào node Video theo vai trò → (ảnh theo thứ tự gửi, có khung mở đầu không). Ảnh đặt "Khung đầu" đứng đầu;
        không đặt → ảnh đầu tiên không phải "Tham chiếu" làm khung đầu nếu bật ô Ảnh đầu làm khung mở đầu."""
        roles = node.get("roles") or {}
        pairs = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] in ("image", "upload") and src.get("files"):
                path = self.root / bid / src["files"][min(int(src.get("pick") or 0), len(src["files"]) - 1)]
                if path.is_file():
                    pairs.append((iid, path))
        # 📎 ảnh thành phần đính kèm trong khối (Google Flow: nhân vật / sản phẩm / bối cảnh) — sau ảnh nối dây
        pairs += [(f"ref:{k}", p) for k, (p, _) in enumerate(self._ref_paths(bid, node))]
        pinned = [p for i, p in pairs if roles.get(i) == "first"][:1]
        if not pinned and node.get("first_frame", True):
            pinned = [p for i, p in pairs if roles.get(i) != "ref"][:1]
        rest = [p for _, p in pairs if p not in pinned]
        return pinned + rest, bool(pinned)

    def _input_videos(self, bid: str, board: dict, node: dict) -> list[Path]:
        """Video từ node nối vào (node Video, Ghép video, Video dài…) — làm video tham chiếu."""
        out = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            video = self._outputs(bid, src).get("video") if src else ""
            if video and Path(video).is_file():
                out.append(Path(video))
        return out

    # ------------------------------------------------------------------ tạo ảnh / video
    def generate(self, bid: str, nid: str) -> dict:
        head = self._node(self.load(bid), nid)
        if head["kind"] == "video" and not head.get("part_of") and head.get("status") not in ACTIVE:
            self.auto_split(bid, nid)  # ✂ lời dài → tách / đồng bộ trước
            board = self.load(bid)
            parts = [p["id"] for p in self._parts_of(board, nid)]
            if parts:
                merge = [n["id"] for n in board["nodes"] if n.get("split_of") == nid]
                return self.run_flow(bid, "set", only=[nid, *parts, *merge],
                                     label=f"Tạo {len(parts)} video tách từ {nid} + ghép")
        with self._lock:
            board = self.load(bid)
            node = self._node(board, nid)
            if node["kind"] == "upload":
                raise CanvasError("Node tải lên không cần tạo")
            if node.get("status") in ACTIVE:
                raise CanvasError("Node đang chạy")
            if node.get("locked"):
                raise CanvasError("Khối đang khoá 🔒 — mở khoá để tạo lại (kết quả cũ vẫn nằm ở 🕘 Phiên bản)")
            if node["kind"] == "wf":
                task = self.pool.submit(f"Canvas · {self.label(node)}", self._run_wf, bid, nid,
                                        meta={"board": bid, "node": nid})
                node.update(status="queued", pct=0, error="", task=task, approval={})
                self._save(board)
                self._push(bid, nid)
                return self.public(self.load(bid))
            # ✂ video con: ảnh / ý tưởng / prompt lấy từ khối Video chung (giống lúc chạy — _run)
            head = node.get("part_of")
            src = self._node(board, head) if head and self._has(board, head) else node
            refs = self._input_images(bid, board, src)
            text_in = self._input_text(bid, board, src)
            own = self._own_prompt(src)
            if node["kind"] == "video" and not (refs or self._input_videos(bid, board, src) or own or text_in):
                raise CanvasError("Video cần ảnh / video nối vào, hoặc prompt mô tả (tạo video từ chữ)")
            if node.get("angles") in ANGLES and not (refs or own or text_in):
                raise CanvasError(f"{ANGLES[node['angles']]['title']}: nối ảnh "
                                  f"{'nhân vật' if node['angles'] == 'character' else 'sản phẩm'} vào (hoặc mô tả ở prompt)")
            if node["kind"] == "image" and not (own or text_in or node.get("angles") in ANGLES):
                raise CanvasError("Ảnh chưa có prompt — viết prompt, hoặc nối khối chữ (Văn bản, AI viết…) vào và chạy khối đó")
            if node["kind"] == "image" and refs and IMAGE_ENGINES[node["engine"]]["max_images"] < 1:
                raise CanvasError(f"{IMAGE_ENGINES[node['engine']]['name']} không nhận ảnh tham chiếu — đổi model "
                                  "hoặc bỏ nối")
            what = "Video" if node["kind"] == "video" else "Ảnh"
            task = self.pool.submit(f"Canvas · {what} — {(own or text_in)[:60]}", self._run, bid, nid,
                                    meta={"board": bid, "node": nid})
            node.update(status="queued", pct=0, error="", task=task)
            self._save(board)
        self._push(bid, nid)
        return self.public(self.load(bid))

    def cancel(self, bid: str, nid: str) -> None:
        node = self._node(self.load(bid), nid)
        if node.get("task"):
            self.pool.cancel(node["task"])

    def _set_node(self, bid: str, nid: str, **fields) -> None:
        def apply(board):
            node = next((n for n in board["nodes"] if n["id"] == nid), None)
            if node is not None:
                node.update(fields)
        try:
            self._edit(bid, apply)
        except CanvasError:  # bảng đã xoá trong lúc chạy
            return
        self._push(bid, nid)

    def _run(self, bid: str, nid: str) -> dict:
        self._log_to(bid, nid=nid)
        self._set_node(bid, nid, status="running", pct=1, log_at=now())
        t0 = time.time()
        try:
            board = self.load(bid)
            node = self._node(board, nid)
            sig = (self._sig(board, nid, raw=True), self._sig_own(node))  # dấu lúc BẮT ĐẦU (sửa giữa chừng → chạy lại sau)
            parts = self._parts_of(board, nid) if node["kind"] == "video" else []
            if parts and self._build_mode(node) == "one":  # 🎬 Không tách: khối tự quay + ghép
                parts = []
            if parts:  # ✂ khối Video chung: các video con quay từng đoạn → khối chung không quay
                stage = f"✂ Chia {len(parts)} video: {', '.join(p['id'] for p in parts)}"
                if self._build_mode(node) == "story":  # 🧭 phân tích lời thoại → prompt riêng từng khối con
                    stage = self._story_analyze(bid, nid)
                self._finish(bid, nid, sig, status="done", pct=100, error="", files=[], pick=0, done_at=now(),
                             secs=round(time.time() - t0, 1), stage=stage,
                             made=_short(self._own_prompt(node) or self._input_text(bid, board, node), 300))
                return {"board": bid, "node": nid, "files": []}
            head = self._node(board, node["part_of"]) if node.get("part_of") and self._has(board, node["part_of"]) else None
            from . import api_mode

            table = IMAGE_ENGINES if node["kind"] == "image" else VIDEO_ENGINES
            engine = api_mode.pick(node.get("engine"), table, self.settings)
            if engine != node.get("engine"):  # 🔑 chỉ dùng model trình duyệt: node cũ chọn model API → bản trình duyệt
                self.pool.log(f"{nid}: chỉ dùng model trình duyệt — {node.get('engine')} → {engine}", "warn")
                node = {**node, "engine": engine}
                self._fit_options(node)
            src = head or node  # ✂ video con: ảnh / video / ý tưởng lấy từ khối Video chung
            refs = self._input_images(bid, board, src)
            prompt = "\n\n".join(x for x in (self._input_text(bid, board, src), self._own_prompt(src)) if x)
            prompt = self._angle_prompt(board, node, prompt)
            tpl = self._template(src) if node["kind"] == "video" else None
            story = head is not None and self._build_mode(head) == "story" and (node.get("prompt") or "").strip()
            if story:  # 🧭 khối con của Storyboard: prompt riêng của cảnh (đã gồm khung đầu / "ends with …")
                from . import video_templates as vt

                total = len(self._parts_of(board, head["id"]))
                k = int(node.get("part") or 1)
                own = node["prompt"].strip()
                prompt = vt.finish_prompt(tpl, own, k, total) if tpl is not None else (
                    f"{own}\n\nPart {k} of {total} of one continuous video: keep exactly the same person, outfit, product and "
                    "setting as the other parts; start exactly where the previous part ended.")
            elif head is not None and tpl is not None:  # 🎞 mẫu "Tách khối": khối con k lấy khung cảnh k của mẫu
                from . import video_templates as vt

                total = len(self._parts_of(board, head["id"]))
                k = int(node.get("part") or 1)
                prompt = vt.finish_prompt(tpl, vt.fallback_prompt(tpl, k, total, prompt), k, total)
            elif head is not None:
                total = len(self._parts_of(board, head["id"]))
                prompt += (f"\n\nThis is part {node.get('part')} of {total} of one continuous video: keep exactly the "
                           "same person, outfit, product and setting as the other parts; continue naturally.")
            if node["kind"] == "video":
                refs, first = self._video_images(bid, board, {**src, "first_frame": node.get("first_frame")})
                videos = self._input_videos(bid, board, src)
                frame = self._scene_frame(board, node)
                covered = any(self._node(board, i).get("cover_of") for i in node.get("inputs") or [] if self._has(board, i))
                if frame is not None and not covered:  # 🎞 tắt ảnh bìa: khung storyboard của cảnh làm khung đầu
                    refs, first = [frame, *refs], True
                if node.get("chain_from"):  # ⛓ liền mạch: khung cuối video cảnh trước = khung đầu cảnh này
                    prev = self._outputs(bid, self._node(board, node["chain_from"])).get("video")                         if self._has(board, node["chain_from"]) else ""
                    videos = [v for v in videos if str(v) != str(prev)]
                    tail = self._last_frame(bid, nid, Path(prev)) if prev else None
                    if tail is not None:
                        refs, first = [tail, *refs], True
                        self.pool.log(f"⛓ Quay tiếp từ khung cuối video {node['chain_from']}")
                    else:
                        first = bool(refs)  # cảnh trước chưa có video → quay từ ảnh bìa (không liền mạch)
                        self.pool.log(f"Cảnh trước ({node['chain_from']}) chưa có video — quay từ ảnh bìa", "warn")
                node = {**node, "dialogue": self._dialogue_text(bid, board, node), "first_frame": first}
                mode = self._build_mode(node)
                long = dialogue_words({"dialogue": node["dialogue"]}) > dialogue_limit(node)
                if tpl is not None and head is None and mode == "one":  # 🎞 Không tách: chia + ghép bên trong
                    files = self._make_templated(bid, node, tpl, refs, videos, prompt)
                elif tpl is None and head is None and mode == "one" and long:  # 🎬 không mẫu, Không tách, lời dài
                    files = self._make_templated(bid, node, None, refs, videos, prompt)
                elif tpl is not None and head is None:  # 🎞 Tách khối nhưng lời vừa 1 clip → 1 video theo mẫu
                    from . import video_templates as vt

                    one = vt.finish_prompt(tpl, vt.fallback_prompt(tpl, 1, 1, prompt), 1, 1)
                    files = self._make_video(bid, node, refs, videos, one)
                else:
                    files = self._make_video(bid, node, refs, videos, prompt)
            else:
                frame = self._scene_frame(board, node)
                if frame is not None:  # 🎞 ảnh bìa cảnh k: khung k của tấm storyboard là ảnh tham chiếu chính (đứng đầu)
                    room = IMAGE_ENGINES[node["engine"]]["max_images"]
                    refs = [frame, *refs][:max(1, room)] if room > 0 else refs
                node = {**node, "_ref_roles": self._image_roles(bid, board, node)}  # 📎 nhân vật / sản phẩm / …
                files = self._make_image(bid, node, refs, prompt)
        except Cancelled:
            self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng")
            raise
        except Exception as exc:
            self._set_node(bid, nid, status="error", pct=0, error=str(exc)[:300])
            raise
        self._finish(bid, nid, sig, status="done", pct=100, error="", files=files, pick=0, stage="", done_at=now(),
                     secs=round(time.time() - t0), made=_short(prompt, 300))
        return {"board": bid, "node": nid, "files": files}

    @staticmethod
    def _made(node: dict) -> str:
        """Yêu cầu chính của khối (prompt / ý tưởng / chủ đề…) — ghi kèm kết quả để 🕘 Phiên bản hiện đúng bản đó tạo từ gì."""
        cfg = node.get("config") or {}
        return _short(node.get("prompt") or next((str(cfg[k]) for k in ("prompt", "request", "idea", "topic", "text", "sp_name")
                                                  if cfg.get(k)), ""), 300)

    @staticmethod
    def _archive(node: dict) -> list:
        """Kết quả đang có của node → đầu danh sách 🕘 Phiên bản (giữ tối đa MAX_VERSIONS - 1 bản cũ). Trả các bản bị bỏ
        (file của chúng được dọn sau, khi không còn bước hoàn tác nào cần)."""
        if node.get("wtype") in NO_VERSIONS:
            return []
        files = list(node.get("files") or [])
        out = copy.deepcopy(node.get("out") or {}) if node["kind"] == "wf" else {}
        if not files and not (out.get("text") or out.get("video") or out.get("scenes")):
            return []
        ver = {"files": files, "out": out, "pick": int(node.get("pick") or 0), "sig": node.get("sig", ""),
               "sig_own": node.get("sig_own", ""), "at": node.get("done_at", ""),
               "prompt": node.get("made") if "made" in node else CanvasRunner._made(node)}
        vers = [ver, *(node.get("versions") or [])]
        node["versions"] = vers[:MAX_VERSIONS - 1]
        return vers[MAX_VERSIONS - 1:]

    def _finish(self, bid: str, nid: str, sig: tuple, **fields) -> None:
        """Node vừa có kết quả mới: cất kết quả cũ vào 🕘 Phiên bản rồi ghi kết quả mới + dấu vân tay (lúc bắt đầu chạy)."""
        dropped = []

        def apply(board):
            node = next((n for n in board["nodes"] if n["id"] == nid), None)
            if node is None:
                return
            dropped.extend(self._archive(node))
            node.update(fields)
            node["sig"], node["sig_own"] = sig
        try:
            self._edit(bid, apply)
        except CanvasError:  # bảng đã xoá trong lúc chạy
            return
        self._push(bid, nid)
        if dropped:
            self._gc(bid)

    def restore_version(self, bid: str, nid: str, idx: int) -> dict:
        """🕘 Dùng lại 1 phiên bản cũ: bản đang có cất vào Phiên bản, bản chọn thành kết quả hiện tại (khối phía sau thấy
        đầu vào đổi → lần chạy sau chạy lại chúng)."""
        def apply(board):
            node = self._node(board, nid)
            if node.get("status") in ACTIVE:
                raise CanvasError("Khối đang chạy — chờ xong đã")
            vers = list(node.get("versions") or [])
            if not 0 <= int(idx) < len(vers):
                raise CanvasError("Không còn phiên bản này")
            ver = vers.pop(int(idx))
            if any(not (self.root / bid / f).is_file() for f in ver.get("files") or []):
                raise CanvasError("File của phiên bản này đã bị xoá")
            node["versions"] = vers
            self._archive(node)
            node.update(files=list(ver.get("files") or []), pick=int(ver.get("pick") or 0), status="done", pct=100,
                        error="", stage="", done_at=ver.get("at") or now(), made=ver.get("prompt", ""))
            if node["kind"] == "wf":
                node["out"] = copy.deepcopy(ver.get("out") or {})
            # bản chọn = kết quả bạn chấp nhận cho cấu hình hiện tại → lần chạy sau không tự tạo lại khối này
            node["sig"], node["sig_own"] = self._sig(board, nid, raw=True), self._sig_own(node)
        board = self._edit(bid, apply)
        self._push(bid, nid)
        return self._result(bid, board, nid)

    def set_lock(self, bid: str, nid: str, on: bool) -> dict:
        """🔒 Khoá kết quả: lần chạy quy trình (kể cả Làm lại tất cả, trợ lý tự làm lại) luôn giữ nguyên kết quả khối này
        dù khối phía trước đổi; khối phía sau coi như đầu vào không đổi. Mở khoá → chạy lại nếu cấu hình đã đổi."""
        def apply(board):
            node = self._node(board, nid)
            if on:
                if self._passive(node) or node.get("wtype") in (*POST_TYPES, "output"):
                    raise CanvasError("Khối này không cần khoá (không tạo nội dung bằng model)")
                if node.get("status") != "done":
                    raise CanvasError("Chỉ khoá được khối đã có kết quả")
                if not node.get("sig"):
                    node["sig"], node["sig_own"] = self._sig(board, nid, raw=True), self._sig_own(node)
            node["locked"] = bool(on)
        board = self._edit(bid, apply, undo=f"{'Khoá' if on else 'Mở khoá'} {nid}")
        self._push(bid, nid)
        return self._result(bid, board, nid)

    def _follow(self, runner, task_id: str, bid: str, nid: str, span: tuple | None = None) -> dict:
        """Chờ tác vụ ảnh / video, chuyển % sang node (UI thấy tiến trình); dừng node → huỷ luôn tác vụ đó.
        span = (k, n): tác vụ là đoạn k / n của 1 khối (🎞 mẫu video) → % chung của khối + nhãn "Đoạn k/n"."""
        last = -1.0
        while True:
            try:
                self.pool.check_cancel()
            except Cancelled:
                runner.pool.cancel(task_id)
                raise
            item = next((t for t in runner.pool.list() if t["id"] == task_id), None)
            if item is None:
                raise CanvasError("Tác vụ đã bị xoá")
            if item["status"] not in ("queued", "running"):
                break
            pct = max(1.0, float(item.get("pct") or 0) * 0.98)
            text = item.get("status_text") or ""
            if span:
                pct, text = ((span[0] - 1) + pct / 100) / span[1] * 95, f"🎞 Đoạn {span[0]}/{span[1]} · {text}"
            if abs(pct - last) >= 2:
                last = pct
                self.pool.progress(pct, text, "run")
                self._set_node(bid, nid, pct=round(pct), stage=text)
            time.sleep(1)
        summary = runner.pool.wait(task_id)
        if summary["status"] != "done" or not summary.get("result"):
            # nhật ký chi tiết của tác vụ ảnh / video (bước trình duyệt…) → ghi vào nhật ký Canvas để xem lại sau
            for entry in runner.pool.logs(task_id)[-12:]:
                self.pool.log(f"  ↳ {entry.get('message', '')}", "error" if entry.get("level") == "error" else "warn")
            raise CanvasError(summary.get("error") or "Tạo không thành công")
        return summary["result"]

    def _profile(self, kind: str, engine: str) -> str:
        """Profile trình duyệt đã gán ở Cài đặt → Model AI (chỉ khi node dùng đúng model mặc định đó); màn Flow: profile ở
        Cài đặt của màn."""
        if self.flow:
            return self.models().get(f"{kind}_profile", "")
        prefs = model_prefs.get(self.settings)
        return prefs.get(f"model_{kind}_profile", "") if engine == prefs.get(f"model_{kind}") else ""

    def _make_image(self, bid: str, node: dict, refs: list[Path], prompt: str) -> list[str]:
        refs = refs[:IMAGE_ENGINES[node["engine"]]["max_images"]]
        roles = node.get("_ref_roles") or {}
        if refs:
            named = [IMAGE_REF_ROLES[roles[str(p)]][0] for p in refs if str(p) in roles]
            self.pool.log(f"Gửi kèm {len(refs)} ảnh tham chiếu" + (f" ({', '.join(named)})" if named else ""))

        def ref(i: int, p: Path) -> dict:
            role = IMAGE_REF_ROLES.get(roles.get(str(p), ""))
            if role:  # 📎 ảnh đã đặt vai trò → nói rõ cho model ảnh này dùng để làm gì
                return {"path": str(p), "role": f"reference image {i + 1}: {role[0]}", "prompt": role[1]}
            return {"path": str(p), "role": f"reference image {i + 1}",
                    "prompt": "use this image as the prompt says (edit it, or keep its subject / product)"}

        task = self.images.start({
            "engine": node["engine"], "prompt": prompt, "aspect": node["aspect"],
            "count": int(node.get("count") or 1), "quality": "high", "refs": [], "show_browser": False,
            "extra_refs": [ref(i, p) for i, p in enumerate(refs)],
            "ref_note": True, "browser_profile": self._profile("image", node["engine"])})
        result = self._follow(self.images, task, bid, node["id"])
        src_dir = Path(self.settings.output_dir) / IMAGES_DIR / result["id"]
        stamp, files = int(time.time()), []
        for i, f in enumerate(result.get("files") or []):
            src = src_dir / f["name"]
            if src.is_file():
                rel = f"nodes/{node['id']}_{stamp}_{i + 1}{src.suffix.lower()}"
                shutil.copy2(src, self.root / bid / rel)
                files.append(rel)
        if not files:
            raise CanvasError("Model không trả ảnh nào")
        return files

    def video_plan(self, node: dict, images: list, videos: list) -> dict:
        """Chia file nối vào node Video thành ô đính kèm của template: ảnh đầu = khung mở đầu (nếu bật), các ảnh
        sau = ảnh tham chiếu, 1 video tham chiếu; tổng số file không vượt giới hạn của model video."""
        limit = max(1, int(VIDEO_ENGINES[node["engine"]].get("max_images") or 1))
        images, videos = list(images), list(videos)[:1]
        plan, dropped = {}, 0
        if videos:
            limit -= 1
        if images and node.get("first_frame", True):
            plan["image"] = str(images.pop(0))
            limit -= 1
        for slot in VIDEO_REF_SLOTS:
            if images and limit > 0:
                plan[slot] = str(images.pop(0))
                limit -= 1
        dropped = len(images)
        if videos:
            plan["vref"] = str(videos[0])
        return {"attachments": plan, "dropped": dropped}

    def _make_video(self, bid: str, node: dict, images: list[Path], videos: list[Path], prompt: str) -> list[str]:
        plan = self.video_plan(node, images, videos)
        att = plan["attachments"]
        if plan["dropped"]:
            self.pool.log(f"{VIDEO_ENGINES[node['engine']]['name']} nhận tối đa "
                          f"{VIDEO_ENGINES[node['engine']]['max_images']} file — bỏ {plan['dropped']} ảnh cuối", "warn")
        refs = sum(1 for k in att if k in VIDEO_REF_SLOTS)
        self.pool.log("Gửi kèm: " + ", ".join(x for x in ("1 ảnh khung đầu" if "image" in att else "",
                                                          f"{refs} ảnh tham chiếu" if refs else "",
                                                          "1 video tham chiếu" if "vref" in att else "") if x))
        lead = ("Image-to-video: animate the opening frame (the first attached image) — do not create a new image."
                if "image" in att else
                "Create a new video that uses the attached references — keep every person, product and place in them "
                "identical." if att else "Text-to-video: create the video from this description.")
        if any(k == "image" or k in VIDEO_REF_SLOTS for k in att):  # 🖼 ảnh đính kèm ưu tiên hơn chữ ý tưởng
            lead += (" The attached image(s) take priority over the text: keep the same person (face, age, hair, "
                     "outfit), the same product and packaging and the same setting exactly as in the images. Use the text "
                     "only for actions, motion, camera and mood; if the text describes a different person, product or "
                     "place, ignore that part and follow the images.")
        motion = prompt or ("Bring this image to life with natural, subtle motion; keep every person, product and "
                            "detail exactly as in the image.")
        task = self.videos.start({
            "template": VIDEO_TEMPLATE, "provider": node["engine"], "ai_duration": node["duration"],
            "ai_aspect": node["aspect"], "ai_resolution": node["resolution"],
            "variables": {"KhungDau": lead, "MoTa": motion, "LoiThoai": dialogue_prompt(node)},
            "attachments": att, "show_browser": False, "topic": "Canvas",
            "browser_profile": self._profile("video", node["engine"])})
        result = self._follow(self.videos, task, bid, node["id"], node.get("_span"))
        src = Path(self.settings.output_dir) / result["id"] / "final.mp4"
        if not src.is_file():
            raise CanvasError("Không thấy file video kết quả")
        rel = f"nodes/{node['id']}_{int(time.time())}.mp4"
        shutil.copy2(src, self.root / bid / rel)
        return [rel]

    @staticmethod
    def _template(node: dict) -> dict | None:
        """🎞 Mẫu video khối Video đang dùng (mẫu đã xoá → None = khối Video thường)."""
        if node.get("kind") != "video" or not node.get("template"):
            return None
        from . import video_templates as vt

        return vt.get(str(node["template"]))

    def _template_prompts(self, node: dict, tpl: dict, lines: list, idea: str, images: list) -> list[str]:
        """1 lượt model chữ viết prompt cho mọi đoạn theo Master Prompt của mẫu; tắt AI / lỗi → điền theo khung cảnh."""
        from . import video_templates as vt

        n = len(lines)
        fill = [vt.fallback_prompt(tpl, k, n, idea) for k in range(1, n + 1)]
        if node.get("tpl_ai") is False:
            return fill
        from .studio import ask_model
        from .workflow.nodes import CONTENT_MODELS

        m = self.models() or {}
        model = m.get("text") or self.settings.get("fcanvas_model_text") or "chatgpt_browser"
        secs = int(str(node.get("duration") or "10s").rstrip("s") or 10)
        ask = vt.writer_prompt(tpl, lines, secs=secs, model=VIDEO_ENGINES[node["engine"]]["name"], idea=idea,
                               materials=[f"Image {i}" for i in range(1, len(images[:4]) + 1)])
        self.pool.log(f"🎞 {CONTENT_MODELS.get(model, model)} viết prompt {n} đoạn theo mẫu “{tpl['name']}”…")
        try:
            raw = ask_model(self.settings, {"model": model, "text_profile": m.get("text_profile", ""),
                                            "show_browser": False, "timeout": 600}, ask,
                            complete=lambda t: bool(vt.parse_parts(t, n)), what="viết prompt theo mẫu video",
                            log=self.pool.log, check_cancel=self.pool.check_cancel,
                            images=[str(p) for p in images[:4]] or None)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — model chữ lỗi → vẫn quay được theo khung mẫu
            self.pool.log(f"Model chữ lỗi ({str(exc)[:160]}) — điền prompt theo khung cảnh của mẫu", "warn")
            return fill
        got = vt.parse_parts(raw, n)
        if not got:
            self.pool.log("Model chữ trả sai định dạng — điền prompt theo khung cảnh của mẫu", "warn")
            return fill
        return got

    STORY_PROMPT = """Bạn là đạo diễn video ngắn. Lời thoại dưới đây ĐÃ được chia sẵn thành {n} đoạn theo thứ tự. Mỗi đoạn là 1 clip
{secs} giây do model video AI ({model}) quay, khung {aspect}. Các clip được quay NỐI TIẾP: khung ĐẦU clip sau = khung CUỐI
clip trước, rồi ghép thành 1 video liền mạch.
Ý tưởng / bối cảnh chung: {idea}
{tpl}{materials}
LỜI THOẠI TỪNG ĐOẠN (đã chốt — KHÔNG viết lại, KHÔNG đưa lời vào prompt):
{lines}
Bước 1 — PHÂN TÍCH lời thoại: nội dung chính, ai nói, cảm xúc, nhịp kể; nhân vật / sản phẩm / bối cảnh phải giữ nhất quán.
Bước 2 — STORYBOARD đúng {n} cảnh, cảnh k = đoạn k:
- "noi_dung": tiếng Việt, 1 câu — hình ảnh diễn ra khi nói đúng đoạn lời đó (minh hoạ đúng ý câu nói).
- "goc_quay": tiếng Việt — cỡ cảnh · góc máy · chuyển động máy (máy đặt dưới đất; KHÔNG drone / flycam trừ khi ý tưởng yêu cầu).
- "prompt": TIẾNG ANH, tự đủ nghĩa: chủ thể, hành động khi nói đoạn lời, bối cảnh, ánh sáng, góc máy. Cảnh 2 trở đi BẮT ĐẦU
  đúng trạng thái kết thúc của cảnh trước (cùng bối cảnh, ánh sáng, vị trí / tư thế nhân vật); mọi cảnh KẾT THÚC bằng
  "ends with …" mô tả khung cuối. Mô tả nhân vật / trang phục / sản phẩm y hệt nhau ở mọi cảnh. Không chữ trên hình.
Trả về đúng MỘT khối ```json:
{{"phan_tich": "tóm tắt phân tích (tiếng Việt)", "nhan_vat": "English: nhân vật / sản phẩm cố định (\\"\\" nếu không có)",
 "canh": [{{"so": 1, "noi_dung": "", "goc_quay": "", "prompt": "English video prompt ... ends with ..."}}]}}
Mảng "canh" có ĐÚNG {n} phần tử."""

    @staticmethod
    def _story_parse(text: str, n: int) -> tuple[dict, list]:
        """Câu trả lời storyboard → (dữ liệu, [{noi_dung, goc_quay, prompt}] đúng n cảnh có prompt) — sai → (…, [])."""
        from .llm.base import extract_json

        try:
            data = extract_json(str(text or ""))
        except Exception:  # noqa: BLE001
            return {}, []
        rows = data.get("canh") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != n:
            return (data if isinstance(data, dict) else {}), []
        out = [{"noi_dung": str(r.get("noi_dung") or "").strip()[:400], "goc_quay": str(r.get("goc_quay") or "").strip()[:200],
                "prompt": str(r.get("prompt") or "").strip()[:2500]} for r in rows if isinstance(r, dict)]
        return data, out if len(out) == n and all(s["prompt"] for s in out) else []

    def _story_analyze(self, bid: str, nid: str) -> str:
        """🧭 Khối Video chung (Storyboard): 1 lượt model chữ phân tích lời thoại ĐÃ chia (nguyên văn, vừa clip) → prompt
        riêng từng khối con (khung đầu = khung cuối cảnh trước, "ends with …"). Lời / ý tưởng / mẫu không đổi và các khối
        con đã có prompt → không hỏi lại (không tốn lượt). Model lỗi / sai định dạng → khối con dùng prompt chung (cảnh báo)."""
        board = self.load(bid)
        head = self._node(board, nid)
        parts = self._parts_of(board, nid)
        lines = [str(p.get("dialogue") or "") for p in parts]
        idea = "\n\n".join(x for x in (self._input_text(bid, board, head), self._own_prompt(head)) if x).strip()
        tpl = self._template(head)
        key = hashlib.md5(json.dumps([lines, idea, head.get("template"), head.get("duration"), head.get("aspect"),
                                      head.get("engine")], ensure_ascii=False).encode()).hexdigest()[:16]
        if (head.get("story") or {}).get("key") == key and all((p.get("prompt") or "").strip() for p in parts):
            return f"🧭 Storyboard {len(parts)} cảnh (đã phân tích — sửa prompt ở từng khối con)"
        from .studio import ask_model
        from .workflow.nodes import CONTENT_MODELS

        n = len(parts)
        refs = self._input_images(bid, board, head)
        m = self.models() or {}
        model = m.get("text") or self.settings.get("fcanvas_model_text") or "chatgpt_browser"
        secs = int(str(head.get("duration") or "10s").rstrip("s") or 10)
        tpl_txt = ""
        if tpl is not None:
            tpl_txt = (f"MẪU VIDEO “{tpl['name']}”: phong cách {tpl.get('style') or ''}. Master Prompt: "
                       f"{tpl.get('master') or ''}\n")
        mats = f"Ảnh vật liệu đính kèm ({len(refs[:4])} ảnh): nhân vật / sản phẩm / bối cảnh phải giống ảnh.\n" if refs else ""
        ask = self.STORY_PROMPT.format(
            n=n, secs=secs, model=VIDEO_ENGINES.get(head.get("engine") or "", {}).get("name", "AI"),
            aspect=head.get("aspect") or "9:16", idea=idea or "(không có — dựng hình theo lời thoại)", tpl=tpl_txt,
            materials=mats, lines="\n".join(f"Đoạn {k}: “{t}”" for k, t in enumerate(lines, 1)))
        self._set_node(bid, nid, pct=5, stage=f"🧭 {CONTENT_MODELS.get(model, model)} phân tích lời thoại {n} cảnh")
        self.pool.log(f"🧭 {nid}: {CONTENT_MODELS.get(model, model)} phân tích lời thoại → storyboard {n} cảnh liền mạch…")
        scenes, data, why = [], {}, ""
        try:
            raw = ask_model(self.settings, {"model": model, "text_profile": m.get("text_profile", ""), "show_browser": False,
                                            "timeout": 600}, ask, complete=lambda t: bool(self._story_parse(t, n)[1]),
                            what="phân tích lời thoại (storyboard)", log=self.pool.log, check_cancel=self.pool.check_cancel,
                            images=[str(p) for p in refs[:4]] or None)
            data, scenes = self._story_parse(raw, n)
            why = "" if scenes else "model trả sai định dạng"
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — model chữ lỗi → vẫn quay được bằng prompt chung
            why = str(exc)[:160]
        char = str(data.get("nhan_vat") or "").strip() if isinstance(data, dict) else ""

        def apply(b):
            h = self._node(b, nid)
            h["story"] = {"key": key if scenes else "", "at": now(), "analysis": str(data.get("phan_tich") or "")[:1500]
                          if isinstance(data, dict) else "", "error": why,
                          "scenes": [{**s, "loi": lines[i]} for i, s in enumerate(scenes)]}
            for i, p in enumerate(self._parts_of(b, nid)):
                if i < len(scenes):
                    p["prompt"] = (f"{scenes[i]['prompt']}\n\nConsistent character / product: {char}" if char
                                   else scenes[i]["prompt"])
                    p["story_scene"] = {"noi_dung": scenes[i]["noi_dung"], "goc_quay": scenes[i]["goc_quay"]}
        self._edit(bid, apply)
        for p in parts:
            self._push(bid, p["id"])
        if not scenes:
            self.pool.log(f"🧭 {nid}: chưa phân tích được lời thoại ({why}) — khối con quay bằng prompt chung", "warn")
            return f"🧭 Chưa phân tích được ({why}) — dùng prompt chung"
        self.pool.log(f"🧭 {nid}: storyboard {n} cảnh — mỗi khối con có prompt riêng, nối ⛓ liền mạch", "ok")
        return f"🧭 Storyboard {n} cảnh liền mạch: {', '.join(p['id'] for p in parts)}"

    def story_analyze(self, bid: str, nid: str) -> dict:
        """🧭 Nút "Phân tích lời thoại": tách / đồng bộ khối con rồi chạy RIÊNG khối chung (1 lượt model chữ, chưa quay video)
        — luôn phân tích lại (bỏ kết quả cũ), prompt khối con được thay bằng bản mới."""
        board = self.load(bid)
        node = self._node(board, nid)
        if node["kind"] != "video" or node.get("part_of") or self._build_mode(node) != "story":
            raise CanvasError("Chọn 🧭 Storyboard ở khối Video chung trước")
        if node.get("status") in ACTIVE:
            raise CanvasError("Khối đang chạy — chờ xong hoặc dừng")
        self.auto_split(bid, nid)
        if not self._parts_of(self.load(bid), nid):
            raise CanvasError("Lời thoại vừa 1 clip — không cần storyboard nhiều cảnh")

        def clear(b):
            h = self._node(b, nid)
            h.pop("story", None)
            for p in self._parts_of(b, nid):
                p["prompt"] = ""
                p.pop("story_scene", None)
        self._edit(bid, clear)
        return self.run_flow(bid, "set", only=[nid], label=f"🧭 Phân tích lời thoại {nid}")

    @staticmethod
    def _plain_prompt(idea: str, k: int, n: int) -> str:
        """🎬 Khối không mẫu, "Không tách": prompt đoạn k/n = prompt của khối + câu giữ liền mạch (không tốn lượt model chữ)."""
        if n <= 1:
            return idea
        return (f"{idea}\n\nThis is part {k} of {n} of one continuous video: keep exactly the same person, outfit, product "
                "and setting as the other parts; continue naturally from the previous part.").strip()

    def _make_templated(self, bid: str, node: dict, tpl: dict | None, images: list, videos: list, idea: str) -> list[str]:
        """🎞 Mẫu "Không tách": chia lời thành các đoạn vừa 1 clip → prompt từng đoạn (Master Prompt) → quay lần lượt
        (liền mạch: đoạn sau quay từ khung cuối đoạn trước) → ghép 1 video. Đoạn đã quay giữ lại (thư mục tpl/<nid>):
        chạy lại sau lỗi chỉ quay đoạn còn thiếu; đổi lời / mẫu / ảnh / prompt → làm lại từ đầu.
        tpl = None: khối không dùng mẫu chọn "🎬 Không tách" — cùng cách chia / quay liền mạch / ghép, prompt từng đoạn
        = prompt của khối + câu giữ liền mạch (_plain_prompt)."""
        from types import SimpleNamespace

        from . import video_templates as vt
        from .workflow.nodes import _concat

        nid = node["id"]
        spoken = (node.get("dialogue") or "").strip()
        lines = split_dialogue(spoken, dialogue_limit(node)) if spoken else []
        lines = lines or ([spoken] if spoken else [""] * (tpl["segments"] if tpl else 1))
        if len(lines) > vt.MAX_SEGMENTS:
            raise CanvasError(f"Lời thoại quá dài ({len(lines)} đoạn) — tối đa {vt.MAX_SEGMENTS} đoạn, hãy rút gọn lời "
                              "hoặc tăng thời lượng clip")
        n = len(lines)
        work = self.root / bid / "tpl" / nid
        work.mkdir(parents=True, exist_ok=True)
        stamp = [(str(p), p.stat().st_mtime if p.is_file() else 0) for p in [*images, *videos]]
        t = tpl or {}
        key = hashlib.md5(json.dumps([t.get("shots"), t.get("style"), t.get("master"), t.get("continuity"), lines,
                                      idea, stamp, node.get("engine"), node.get("duration"), node.get("aspect"),
                                      node.get("resolution"), node.get("voice"), node.get("tpl_ai") is not False],
                                     ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
        state_file = work / "plan.json"
        state = read_json(state_file) if state_file.is_file() else {}
        if state.get("key") != key or len(state.get("clips") or []) != n:
            state = {"key": key, "lines": lines, "prompts": [], "clips": [""] * n}
        if len(state.get("prompts") or []) != n:
            if tpl is None:  # 🎬 không mẫu: prompt của khối + câu giữ liền mạch, không gọi model chữ
                self.pool.log(f"🎬 Không tách: chia lời thành {n} đoạn × {node.get('duration')} · liền mạch, ghép trong khối")
                state["prompts"] = [self._plain_prompt(idea, k, n) for k in range(1, n + 1)]
            else:
                self.pool.log(f"🎞 Mẫu “{tpl['name']}”: {n} đoạn × {node.get('duration')} · "
                              + ("liền mạch" if tpl["continuity"] == "flow" else "cắt cảnh"))
                self._set_node(bid, nid, pct=1, stage=f"🎞 Viết prompt {n} đoạn")
                raw = self._template_prompts(node, tpl, lines, idea, images)
                state["prompts"] = [vt.finish_prompt(tpl, raw[k - 1], k, n) for k in range(1, n + 1)]
            write_json(state_file, state)
        flow = tpl is None or tpl["continuity"] == "flow"
        clips = state["clips"]
        for k in range(1, n + 1):
            done = work / clips[k - 1] if clips[k - 1] else None
            if done is not None and done.is_file():
                self.pool.log(f"🎞 Đoạn {k}/{n}: đã có từ lần chạy trước — giữ lại")
                continue
            imgs, first, vids = list(images), node.get("first_frame", True), list(videos)
            if flow and k > 1:
                tail = self._last_frame(bid, f"{nid}_seg{k}", work / clips[k - 2])
                if tail is not None:
                    imgs, first, vids = [tail], True, []
                    self.pool.log(f"⛓ Đoạn {k}/{n}: quay tiếp từ khung cuối đoạn {k - 1}")
                else:
                    self.pool.log(f"Đoạn {k}/{n}: không lấy được khung cuối đoạn trước — quay từ ảnh vật liệu", "warn")
            self.pool.log(f"🎞 Đoạn {k}/{n}" + (f": “{_short(lines[k - 1], 80)}”" if lines[k - 1] else ""))
            self._set_node(bid, nid, stage=f"🎞 Đoạn {k}/{n}", pct=round((k - 1) / n * 95))
            sub = {**node, "dialogue": lines[k - 1], "first_frame": first, "_span": (k, n)}
            rel = self._make_video(bid, sub, imgs, vids, state["prompts"][k - 1])[0]
            name = f"seg{k}_{time.time_ns()}.mp4"
            shutil.move(str(self.root / bid / rel), work / name)
            clips[k - 1] = name
            write_json(state_file, state)
        self._set_node(bid, nid, stage=f"🎞 Ghép {n} đoạn", pct=96)
        paths = [work / c for c in clips]
        if n == 1:
            final = paths[0]
        else:
            self.pool.log(f"🎞 Ghép {n} đoạn thành 1 video…")
            ctx = SimpleNamespace(dir=work, log=lambda msg, level="info": self.pool.log(msg, level))
            aspect = node.get("aspect") if node.get("aspect") in ("9:16", "16:9", "1:1") else "9:16"
            final = Path(_concat(ctx, {"aspect": aspect, "transition": "none"}, paths))
        rel = f"nodes/{nid}_{int(time.time())}.mp4"
        shutil.copy2(final, self.root / bid / rel)
        return [rel]

    def _last_frame(self, bid: str, nid: str, video: Path) -> Path | None:
        """Khung cuối của video (ffmpeg, trên máy) → nodes/<nid>_tail.png; lỗi → None."""
        if not video.is_file():
            return None
        out = self.root / bid / "nodes" / f"{nid}_tail.png"
        try:
            ffmpeg.run(["-sseof", "-0.25", "-i", video, "-frames:v", "1", "-q:v", "2", "-update", "1", out])
        except ffmpeg.FFmpegError as exc:
            self.pool.log(f"Không lấy được khung cuối video: {exc}", "warn")
            return None
        return out if out.is_file() and out.stat().st_size else None

    def _unlink(self, path: Path) -> None:
        """Xoá file kết quả cũ. Windows khoá file đang mở (video đang phát / xem trước trên Canvas, máy chủ media đang
        gửi) → WinError 32: KHÔNG báo lỗi khối (kết quả mới đã xong), để xoá lại ở lần sau."""
        with self._trash_lock:
            pending = [p for p in self._trash if p != path]
            self._trash.clear()
        for p in [path, *pending]:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                with self._trash_lock:
                    self._trash.add(p)

    # ------------------------------------------------------------------ block Workflow (viết content, đăng bài…)
    def _wf_inputs(self, bid: str, board: dict, node: dict, spec: dict) -> dict:
        """Đầu ra các node nối vào → đúng cổng của block theo kiểu dữ liệu (chữ → text, ảnh → images, video → video,
        ảnh / video → cổng 'any' như Ảnh / video của Đăng bài, bài viết → post)."""
        values = {p["key"]: [] for p in spec["inputs"]}
        order = list(node.get("inputs") or [])
        roles = node.get("roles") or {}
        if node.get("wtype") == "edit_pro" and roles:  # Edit Pro: video đặt "Video chính" đứng đầu, "Clip" không làm chính
            mains = [i for i in order if roles.get(i) == "main"][:1] or [i for i in order if roles.get(i) != "clip"][:1]
            order = mains + [i for i in order if i not in mains]
        for iid in order:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src is None:
                continue
            out = self._outputs(bid, src)
            for p in spec["inputs"]:
                kind = p["type"]
                if kind == "any":
                    values[p["key"]] += list(out.get("images") or []) + ([out["video"]] if out.get("video") else [])
                    if node["wtype"] == "output" and out.get("text"):  # khối Kết quả gom cả chữ (bài viết, prompt…)
                        values[p["key"]].append(out["text"])
                elif kind in out:
                    values[p["key"]].append(out[kind])
        return values

    def _media_url(self, path: str) -> str:
        """Ảnh / video sắp đăng (nằm trong thư mục video) → URL xem trước trên ô duyệt."""
        try:
            rel = Path(path).resolve().relative_to(Path(self.settings.output_dir).resolve())
        except (ValueError, OSError):
            return ""
        return f"/media/{rel.as_posix()}"

    def _wait_approval(self, bid: str, nid: str, payload: dict) -> dict:
        """Block Đăng bài / Lên lịch: dừng chờ người dùng bấm Đồng ý / Từ chối trên node (Canvas luôn bắt duyệt)."""
        slot = {"event": threading.Event(), "decision": None}
        self._approvals[(bid, nid)] = slot
        show = {k: v for k, v in payload.items() if k != "scheduled_at"}
        show["media_urls"] = [u for u in (self._media_url(f) for f in payload.get("files") or []) if u]
        self._set_node(bid, nid, status="waiting", approval=show, stage="Chờ bạn duyệt")
        self.emit("toast", {"message": f"Canvas: bài đăng lên “{payload.get('page', '')}” đang chờ bạn duyệt", "level": "warn"})
        try:
            while not slot["event"].wait(0.5):
                self.pool.check_cancel()  # bấm Dừng trong lúc chờ duyệt
        finally:
            self._approvals.pop((bid, nid), None)
        decision = slot["decision"]
        if decision.get("caption") is None:
            decision["caption"] = payload.get("caption", "")
        self._set_node(bid, nid, status="running", approval={}, stage="")
        return decision

    def _review_notify(self, bid: str, nid: str, board: dict, post: dict) -> None:
        """📥 Khối đăng vừa lưu bài chờ duyệt → báo giao diện (🔔 thông báo + chuông) và tải lại Quản lý bài đăng."""
        rv = post.get("review") or {}
        self.emit("posts_changed", {})
        self.emit("post_review", {"id": post["id"], "title": post.get("title", ""), "board": board.get("name", ""),
                                  "board_id": bid, "node": nid, "page": ", ".join(rv.get("pages") or []),
                                  "when": rv.get("when", "now"), "when_text": post.get("review", {}).get("when_text", ""),
                                  "thumb": next((m["url"] for m in post.get("media") or [] if m.get("exists")), "")})

    def approve(self, bid: str, nid: str, approved: bool, caption: str | None = None, page_id: str = "") -> dict:
        """page_id: 📣 khối chưa chọn Fanpage → chọn ngay lúc duyệt."""
        import getpass

        slot = self._approvals.get((bid, nid))
        if slot is None:
            raise CanvasError("Node này không còn chờ duyệt")
        slot["decision"] = {"approved": bool(approved), "caption": caption, "by": f"{getpass.getuser()} (máy này)",
                            "at": now(), "page_id": str(page_id or "")}
        slot["event"].set()
        return {"node": nid, "approved": bool(approved)}

    def _run_wf(self, bid: str, nid: str) -> dict:
        from .workflow import nodes as wfn

        self._log_to(bid, nid=nid)
        self._set_node(bid, nid, status="running", pct=1, error="", log_at=now())
        t0 = time.time()
        board = self.load(bid)
        node = self._node(board, nid)
        sig = (self._sig(board, nid, raw=True), self._sig_own(node))  # dấu lúc BẮT ĐẦU chạy
        spec = wfn.NODE_TYPES[node["wtype"]]
        last = [-1.0]

        def progress(frac):
            pct = round(100 * max(0.0, min(1.0, float(frac))))
            if pct - last[0] >= 2:
                last[0] = pct
                self.pool.progress(pct, "", "run")
                self._set_node(bid, nid, pct=max(1, pct))

        # đăng bài chờ duyệt — trừ khi bạn bật "🚀 Tự đăng không cần duyệt" cho khối đó; Canvas nối dây nên không
        # dùng "tài nguyên từ flow"
        is_post = node["wtype"] in ("fb_post", "fb_schedule")
        confirm = not (node.get("auto_post") and is_post)
        if not confirm:
            self.pool.log(f"{nid}: 🚀 tự đăng không cần duyệt (đã bật cho khối này)", "warn")
        # 📥 lưu vào Quản lý bài đăng chờ duyệt (không dừng Canvas) — tự đăng bật thì tự đăng thắng
        review = "posts" if is_post and confirm and node.get("to_posts") else ""
        cfg0 = dict(node.get("config") or {})
        if self.flow:  # 🎥 màn Flow: ô model của khối → model định sẵn (kể cả ô mặc định chưa lưu trong cấu hình)
            from .workflow import nodes as wfn0

            cfg0 = lock_wf_config(node["wtype"], {**wfn0.defaults(node["wtype"]), **cfg0}, self.models())
        # "review" chỉ gắn cho khối Đăng — Storyboard / Edit Pro có ô "review" riêng (tự kiểm tra), không được ghi đè
        wnode = {"id": nid, "type": node["wtype"], "config": {**cfg0, "confirm": confirm, "sources": [],
                                                             **({"review": review} if is_post else {})}}
        materials = self._materials(bid, board, node) if node["wtype"] in STORY_TYPES else None
        if node["wtype"] == "product_studio":  # 🎬 vai trò từng ảnh (nhân vật / sản phẩm) + thời lượng clip của model video
            roles = node.get("roles") or {}
            eng = self._studio_engine()
            wnode["config"].update(_ref_roles=[roles.get(i, "") for i in (materials or {}).get("anh", [])],
                                   _clip_secs=int(studio_clip(eng).rstrip("s")),
                                   _video_model=VIDEO_ENGINES[eng]["name"],
                                   _text_profile=(self.models() or {}).get("text_profile", ""))
        if materials:  # Storyboard: tên khối vật liệu (đúng thứ tự ảnh / video gửi model) để model chọn vật liệu từng cảnh
            wnode["config"]["_materials"] = {k: [self._material_name(self._node(board, i)) for i in ids]
                                             for k, ids in materials.items()}
            # các khối chữ nối vào (đúng thứ tự dây) → Storyboard: khối nối SAU CÙNG là yêu cầu chính, còn lại tham khảo
            wnode["config"]["_requests"] = [
                {"id": i, "name": self._material_name(src), "text": str(self._outputs(bid, src).get("text") or "").strip()}
                for i in node.get("inputs") or [] if self._has(board, i)
                for src in [self._node(board, i)] if str(self._outputs(bid, src).get("text") or "").strip()]
            # 🧍 / 📦 Ảnh k là bảng nhiều góc → không nhận nhầm là tấm storyboard
            wnode["config"]["_angles"] = [k for k, i in enumerate(materials.get("anh") or [], 1)
                                          if self._node(board, i).get("angles") in ANGLES]
        if node["wtype"] == "post_video":  # Hậu kỳ: lời thoại đã biết của từng video nối vào (đúng thứ tự cổng video)
            wnode["config"]["_dialogues"] = self._post_sources(bid, board, node)[1]
        services = {"facebook": self.facebook, "ads": self.ads, "studio": self.studio,
                    "workflow_name": f"Canvas · {board['name']}",
                    "approve": lambda payload: self._wait_approval(bid, nid, payload),
                    "review_notify": lambda post: self._review_notify(bid, nid, board, post)}
        ctx = wfn.NodeContext(self.settings, self.root / bid / "runs", wnode, self.pool.log, self.pool.check_cancel,
                              progress, services)
        try:
            gate = self._qc_gate(board, node)  # 🎬 Studio: ghép / đăng chỉ sau khi người duyệt (không phải lỗi — chờ)
            if gate:
                self.pool.log(f"{nid}: {gate}", "warn")
                raise wfn.NodeSkipped(gate)
            inputs = self._wf_inputs(bid, board, node, spec)
            result = wfn.run_node(ctx, inputs)
        except wfn.NodeSkipped as exc:
            self._set_node(bid, nid, status="idle", pct=0, error=str(exc), approval={}, stage="")
            return {"board": bid, "node": nid, "skipped": True}
        except Cancelled:
            self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng", approval={}, stage="")
            raise
        except Exception as exc:
            self._set_node(bid, nid, status="error", pct=0, error=str(exc)[:300], approval={}, stage="")
            raise
        out, files, stamp = {}, [], int(time.time())
        for key, value in result.items():
            if key == "video" and value and Path(str(value)).is_file():
                src = Path(str(value))
                rel = f"nodes/{nid}_{stamp}{src.suffix.lower() or '.mp4'}"
                shutil.copy2(src, self.root / bid / rel)
                out["video"], files = rel, [rel]
            elif key in ("text", "ad") and value:
                out["text"] = str(value)
            elif key == "images" and value:  # 🖼 Tra cứu web: ảnh sản phẩm tìm được
                rels = []
                for k, p in enumerate(value if isinstance(value, list) else [value]):
                    src = Path(str(p))
                    if src.is_file():
                        rel = f"nodes/{nid}_{stamp}_{k}{src.suffix.lower() or '.jpg'}"
                        shutil.copy2(src, self.root / bid / rel)
                        rels.append(rel)
                if rels:
                    out["images"] = rels
            elif key == "script" and value and not str((node.get("config") or {}).get("script") or "").strip():
                # Hậu kỳ: ô lời đọc để trống → điền lời thoại vừa phân tích để bạn sửa (lần sau dùng bản đã sửa)
                self.update_nodes(bid, [{"id": nid, "config": {"script": str(value)}}], record=False)
                b = self.load(bid)  # ô vừa điền chính là lời đã dùng → dấu vân tay tính cả ô này (không tự chạy lại)
                sig = (self._sig(b, nid, raw=True), self._sig_own(self._node(b, nid)))
            elif key == "scenes" and isinstance(value, list):  # Storyboard: các cảnh → node Video từng cảnh đọc từ đây
                out["scenes"] = value
                out["materials"] = materials or {"anh": [], "video": []}  # Ảnh k / Video k của model → id khối vật liệu
            elif key == "studio" and isinstance(value, dict):  # 🎬 checklist, cảnh báo, kế hoạch cảnh của Studio
                out["studio"] = value
            elif key == "sheet" and value:  # 🎞 Ảnh {sheet} là tấm storyboard (mỗi cảnh dựng từ 1 khung của nó)
                out["sheet"] = int(value)
            elif key == "items":
                folder = str(ctx.dir.parent / str(wnode["config"].get("name") or "ket-qua"))
                out.update(folder=folder, text=f"Đã gom {len(value or [])} kết quả vào thư mục:\n{folder}")
            elif key == "post" and isinstance(value, dict):
                # thẻ bài đăng trên Canvas: thời gian + ảnh / khung hình của file đã đăng (lấy từ đầu vào Ảnh / video)
                media = next((p for p in inputs.get("media") or [] if isinstance(p, str) and Path(p).is_file()), "")
                out["post"] = {**value, "at": now(), "thumb": self._media_url(media) if media else ""}
                where = value.get("url") or value.get("post_id") or ""
                out["text"] = (f"📥 Đã lưu vào Quản lý bài đăng — chờ duyệt đăng lên “{value.get('page', '')}”"
                               if value.get("pending") else
                               f"{'Đã lên lịch ' + value.get('when', '') if value.get('scheduled') else 'Đã đăng'} lên "
                               f"“{value.get('page', '')}”" + (f": {where}" if where else ""))
        if result.get("storyboard"):  # Storyboard: khung hiện storyboard; lời dẫn giữ riêng
            out.update(narration=out.get("text", ""), text=str(result["storyboard"]))
        timing = {} if node["wtype"] in POST_TYPES else {"secs": round(time.time() - t0)}  # khối đăng: có chờ duyệt
        self._finish(bid, nid, sig, status="done", pct=100, error="", out=out, files=files, pick=0, stage="", approval={},
                     done_at=now(), made=self._made(node), **timing)
        if node["wtype"] in STORY_TYPES and out.get("scenes"):
            self._split_scenes(bid, nid)
        if node["wtype"] == "web_research":
            self._feed_uploads(bid, nid, out.get("images") or [])
        self._split_readers(bid, nid)
        return {"board": bid, "node": nid}

    WEB_MISSING = "🖼 Không tìm thấy ảnh sản phẩm trên web — bấm ⬆ Chọn ảnh để tải ảnh lên rồi chạy lại"

    def _feed_uploads(self, bid: str, nid: str, rels: list) -> None:
        """🖼 Khối Ảnh tải lên nối từ khối Tra cứu web nid: web có ảnh sản phẩm → THAY ảnh (ảnh cũ vào 🕘 Phiên bản);
        không có → giữ ảnh đang có, hoặc (khối trống) báo cần tải ảnh lên — khối dùng ảnh phía sau được bỏ qua."""
        result = {}

        def apply(board):
            for u in board["nodes"]:
                if u["kind"] != "upload" or nid not in (u.get("inputs") or []):
                    continue
                if rels:
                    src = self.root / bid / rels[0]
                    files = u.get("files") or []
                    cur = self.root / bid / files[min(int(u.get("pick") or 0), len(files) - 1)] if files else None
                    if cur is not None and cur.is_file() and cur.read_bytes() == src.read_bytes():
                        u["error"], result[u["id"]] = "", "same"
                        continue
                    rel = f"nodes/{u['id']}_web{int(time.time())}{src.suffix.lower()}"
                    shutil.copy2(src, self.root / bid / rel)
                    self._archive(u)
                    u.update(files=[rel], pick=0, status="done", pct=100, error="", stage="", done_at=now(),
                             made=f"Ảnh sản phẩm lấy từ web (khối {nid})")
                    result[u["id"]] = "web"
                elif u.get("files"):
                    u.update(status="done", error="")
                    result[u["id"]] = "kept"
                else:
                    u.update(status="error", error=self.WEB_MISSING)
                    result[u["id"]] = "missing"
        try:
            self._edit(bid, apply)
        except CanvasError:
            return
        for uid, what in result.items():
            self._push(bid, uid)
            self.pool.log({"web": f"🖼 {uid}: đã thay bằng ảnh sản phẩm tìm trên web",
                           "same": f"🖼 {uid}: ảnh sản phẩm trên web giống ảnh đang có",
                           "kept": f"🖼 {uid}: web không có ảnh sản phẩm — giữ ảnh bạn đã tải lên",
                           "missing": f"🖼 {uid}: {self.WEB_MISSING}"}[what],
                          "warn" if what in ("kept", "missing") else "ok")

    @staticmethod
    def _has(board: dict, nid: str) -> bool:
        return any(n["id"] == nid for n in board["nodes"])

    def _post_sources(self, bid: str, board: dict, node: dict) -> tuple[list[Path], list[str]]:
        """Khối Hậu kỳ: (video nối vào theo thứ tự cổng, lời thoại đã biết của từng video đó)."""
        videos, known = [], []
        for src in (self._node(board, i) for i in node.get("inputs") or [] if self._has(board, i)):
            video = self._outputs(bid, src).get("video")
            if video and Path(video).is_file():
                videos.append(Path(video))
                known.append(self._known_speech(bid, board, src))
        return videos, known

    def analyze_dialogue(self, bid: str, nid: str) -> dict:
        """🎧 Phân tích lời thoại từ video đầu vào của khối Hậu kỳ (không chạy hậu kỳ) → điền ô Lời đọc / phụ đề để sửa."""
        from .workflow import nodes as wfn

        board = self.load(bid)
        node = self._node(board, nid)
        if node.get("wtype") != "post_video":
            raise CanvasError("Chỉ khối Hậu kỳ video phân tích lời thoại")
        videos, known = self._post_sources(bid, board, node)
        if not videos:
            raise CanvasError("Khối chưa có video đầu vào — nối node Video / Ghép video và chạy chúng trước")
        notes = []
        script = wfn.analyze_dialogue(self.settings, videos, known, self.root / bid / "runs" / nid,
                                      lambda m, *a, **k: notes.append(str(m)))
        text = wfn.script_text(script)
        if not text:
            raise CanvasError("Không tìm thấy lời thoại trong video đầu vào" + (f" — {notes[0]}" if notes else ""))
        return {"board": self.update_nodes(bid, [{"id": nid, "config": {"script": text}}]), "script": text,
                "notes": notes[-10:]}

    def _known_speech(self, bid: str, board: dict, src: dict, depth: int = 0) -> str:
        """Lời thoại đã biết của 1 video nối vào: node Video → lời thoại của nó; Ghép video → nối lời các video con theo
        thứ tự; video khác (Video đầu vào, Hậu kỳ…) → "" (khối Hậu kỳ nghe lại tiếng nếu được chọn)."""
        if src["kind"] == "video":  # bỏ tên người nói đầu dòng ("Cô gái: …") — phụ đề chỉ hiện lời
            return " ".join(re.sub(r"(?m)^[^:\n]{1,30}:\s*", "", self._dialogue_text(bid, board, src)).split())
        if src.get("wtype") == "concat_video" and depth < 6:
            kids = [self._node(board, i) for i in src.get("inputs") or [] if self._has(board, i)]
            return " ".join(t for t in (self._known_speech(bid, board, k, depth + 1) for k in kids) if t)
        return ""

    def _materials(self, bid: str, board: dict, node: dict) -> dict:
        """Khối vật liệu nối vào Storyboard theo đúng thứ tự ảnh / video gửi model (như _wf_inputs): {anh: [id], video: [id]}."""
        mats = {"anh": [], "video": []}
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            out = self._outputs(bid, src) if src is not None else {}
            mats["anh"] += [iid for p in out.get("images") or [] if Path(p).is_file()]
            if out.get("video") and Path(out["video"]).is_file():
                mats["video"].append(iid)
        return mats

    def _material_name(self, node: dict) -> str:
        return f"{node.get('title') or self.label(node)} (khối {node['id']})"

    SCENE_GAP_Y, SCENE_GAP_X = 470, 400  # node cảnh (cao ~430px) xếp dọc bên phải khối Storyboard, khối Ghép xa thêm 1 cột
    COVER_GAP_Y = 760  # có ảnh bìa: thẻ ảnh bìa cao hơn (ảnh + mô tả + ý tưởng + góc quay + lời thoại bên dưới)

    def _split_scenes(self, bid: str, sid: str) -> list:
        """Storyboard xong → mỗi cảnh 1 khối 🖼 Ảnh bìa (tạo ảnh khung đầu từ prompt cảnh + ảnh nhân vật / sản phẩm; thẻ hiện
        ảnh + mô tả + lời thoại cảnh) → 1 node Video quay từ ảnh bìa đó (lời thoại đúng cảnh) + 1 khối Ghép video nối các
        cảnh theo thứ tự. Tắt ảnh bìa (cover = off) → node Video nhận thẳng ảnh vật liệu như trước. Đã có thì giữ nguyên node
        cũ (model, thời lượng bạn đã đổi) — chỉ thêm cảnh còn thiếu, đổi tên theo nội dung mới. Ảnh bìa tạo NGAY (kể cả khi
        chỉ chạy riêng khối Storyboard); video chờ bạn duyệt ảnh bìa (cover_wait) rồi mới quay. Trả về id các node vừa tạo."""
        created, touched, covers, dropped = [], [], [], []
        pre = self.load(bid)
        count = len((self._node(pre, sid).get("out") or {}).get("scenes") or [])
        clear = bool(self._old_scenes(pre, sid))

        def apply(board):
            sb = self._node(board, sid)
            out = sb.get("out") or {}
            cfg, scenes = self._story_cfg(sb), out.get("scenes") or []
            ids = {n["id"] for n in board["nodes"]}
            raw_anh = (out.get("materials") or {}).get("anh") or []
            sheet_id = raw_anh[out["sheet"] - 1] if 0 < int(out.get("sheet") or 0) <= len(raw_anh) else ""
            # 🎞 tấm storyboard: không gửi tấm ghép nhiều khung cho ảnh bìa / video (model sẽ vẽ ra lưới) — dùng từng khung
            mats = {k: [i for i in v if i in ids] for k, v in (out.get("materials") or {}).items()}
            if sheet_id:
                mats["anh"] = [i if i != sheet_id else None for i in mats.get("anh", [])]  # giữ số thứ tự Ảnh k
            every = [i for i in dict.fromkeys(mats.get("anh", []) + mats.get("video", [])) if i]  # mọi khối vật liệu
            engine = str(cfg.get("cover") or "")
            with_cover = engine != "off"
            gap_y = self.COVER_GAP_Y if with_cover else self.SCENE_GAP_Y

            def chosen(scene):  # vật liệu model chọn cho cảnh (Ảnh k → khối thứ k); model không ghi → dùng tất cả
                has = scene.get("co_nv", True)  # cảnh không có nhân vật / sản phẩm → không gửi ảnh họ (model sẽ chèn họ vào)
                if "anh" not in scene:
                    return every if has else []
                pick = [mats["anh"][k - 1] for k in scene.get("anh") or [] if 0 < k <= len(mats.get("anh", []))]
                if has and cfg.get("always_refs", True):  # giữ nhất quán: ảnh nhân vật / sản phẩm gửi ở mọi cảnh CÓ họ
                    pick += mats.get("anh", [])
                pick += [mats["video"][k - 1] for k in scene.get("video") or [] if 0 < k <= len(mats.get("video", []))]
                return [i for i in dict.fromkeys(pick) if i]

            voice_note = " ".join(str(cfg.get("master_voice") or "").split())[:300]  # 🗣 giọng cố định mọi cảnh

            # 🧹 clear flow cũ: ảnh bìa / video của cảnh đã đổi nội dung (hoặc cảnh thừa) → xoá hẳn cùng kết quả cũ, tạo
            # khối mới bên dưới; video mới giữ model / thời lượng / độ phân giải bạn đã chọn ở cảnh cùng số
            gone = self._old_scenes(board, sid)
            carry = {int(n.get("scene") or 0): {k: n[k] for k in ("engine", "duration", "resolution") if n.get(k)}
                     for n in board["nodes"] if n["id"] in gone and n.get("scene_of") == sid}
            if gone:
                own = sb.get("task") or ""  # tác vụ lượt đang chạy (khối trong lượt dùng chung) — không huỷ cả lượt
                for n in board["nodes"]:
                    if n["id"] in gone and n.get("status") in ACTIVE and n.get("task") and n["task"] != own:
                        self.pool.cancel(n["task"])
                board["nodes"] = [n for n in board["nodes"] if n["id"] not in gone]
                for n in board["nodes"]:
                    n["inputs"] = [i for i in n.get("inputs") or [] if i not in gone]
                    for key in ("dialogue_src", "prompt_src"):
                        if n.get(key) in gone:
                            n[key] = ""
                    if n.get("chain_from") in gone:
                        n.pop("chain_from")
                    self._drop_roles(n)
                for rec in board.get("runs") or []:  # lượt cũ / lượt đang chạy không còn nhắc tới khối đã xoá
                    if rec.get("review"):
                        rec["review"] = [i for i in rec["review"] if i not in gone]
                    if rec.get("status") == "running":
                        for i in gone:
                            (rec.get("nodes") or {}).pop(i, None)
                dropped.extend(sorted(gone))
            fresh = {k: self._scene_hash(s) for k, s in enumerate(scenes, 1)}

            mine = {int(n.get("scene") or 0): n for n in board["nodes"] if n.get("scene_of") == sid}
            cov = {int(n.get("scene") or 0): n for n in board["nodes"] if n.get("cover_of") == sid}
            speech = cfg.get("speech") or "character"
            chain = cfg.get("noi_canh", "chain") != "cut" and not sheet_id  # 🎞 mỗi cảnh quay từ đúng khung của nó

            def link(n, k, cover):
                """⛓ Liền mạch: video cảnh k nối từ video cảnh k-1 (khung cuối cảnh trước = khung đầu cảnh này), ảnh bìa
                cảnh k thành ảnh tham chiếu. Cắt cảnh: bỏ dây nối đó, ảnh bìa lại là khung đầu."""
                old, prev = n.get("chain_from"), mine.get(k - 1)
                ins = [i for i in n.get("inputs") or [] if i != old]
                roles = {r: v for r, v in (n.get("roles") or {}).items() if r != old}
                if chain and prev is not None:
                    n["chain_from"] = prev["id"]
                    ins = [prev["id"], *ins]
                    if cover is not None:
                        roles[cover["id"]] = "ref"
                else:
                    n.pop("chain_from", None)
                    if cover is not None and roles.get(cover["id"]) == "ref":
                        roles.pop(cover["id"])
                n["inputs"] = ins[:MAX_INPUTS]
                if roles:
                    n["roles"] = roles
                else:
                    n.pop("roles", None)

            for k, scene in enumerate(scenes, 1):
                title = f"Cảnh {k} · {scene.get('noi_dung') or ''}"[:60]
                use = chosen(scene)[:MAX_INPUTS - 1]
                row_x, row_y = sb["x"] + self.SCENE_GAP_X, sb["y"] + (k - 1) * gap_y
                cover = cov.get(k)
                if with_cover:  # 🖼 ảnh bìa cảnh k: prompt cảnh + ảnh vật liệu (model ảnh nhận được bao nhiêu gửi bấy nhiêu)
                    if cover is None:
                        cover = self._new_node(board, "image", row_x, row_y, [], "")
                        cover.update(scene=k, cover_of=sid, prompt_src=sid, count=1, aspect=cfg.get("aspect") or cover["aspect"],
                                     scene_hash=fresh[k])
                        if engine in IMAGE_ENGINES:
                            cover["engine"] = engine
                        self._fit_options(cover)
                        cov[k] = cover
                        created.append(cover["id"])
                        if k in mine:  # board cũ (cảnh chưa có ảnh bìa): video lùi sang phải nhường chỗ ảnh bìa
                            mine[k].update(x=row_x + self.SCENE_GAP_X, y=row_y)
                    else:
                        touched.append(cover["id"])
                    room = IMAGE_ENGINES[cover["engine"]]["max_images"]
                    refs = [i for i in use if i in mats.get("anh", [])][:max(0, room)]
                    keep = [i for i in cover.get("inputs") or [] if i != sid and i not in every and i != sheet_id]
                    cover.update(title=f"🖼 Ảnh bìa cảnh {k}", inputs=[sid, *refs, *keep][:MAX_INPUTS])
                    covers.append(cover["id"])
                lead = [cover["id"]] if with_cover else []
                feed = [] if with_cover else use  # có ảnh bìa: video quay từ ảnh bìa (đã mang nhân vật / sản phẩm)
                # 🗣 ai nói: lời dẫn ngoài khung (cảnh b-roll / không nhân vật) hay người trong cảnh nói (khớp môi)
                who = "narrator" if speech == "narrator" or scene.get("kieu") == "dan" else ""
                if k in mine:  # giữ model / thời lượng bạn đã đổi; cập nhật tên + vật liệu theo storyboard mới
                    n = mine[k]
                    keep = [i for i in n.get("inputs") or [] if i != sid and i not in every and i not in lead
                            and i != n.get("chain_from") and i != sheet_id]
                    n.update(title=title, inputs=[*lead, sid, *feed, *keep][:MAX_INPUTS])
                    if with_cover:
                        n["first_frame"] = True
                    if speech != "none" and not n.get("dialogue_src") and not str(n.get("dialogue") or "").strip():
                        n.update(dialogue_src=sid, voice=who)
                    elif n.get("dialogue_src") == sid and n.get("voice", "") in ("", "narrator"):
                        n["voice"] = who  # lời lấy từ storyboard → giọng theo kiểu lời của cảnh mới
                    if voice_note:
                        n["voice_note"] = voice_note
                    else:
                        n.pop("voice_note", None)
                    link(n, k, cover if with_cover else None)
                    touched.append(n["id"])
                    continue
                n = self._new_node(board, "video", row_x + (self.SCENE_GAP_X if with_cover else 0), row_y,
                                   [*lead, sid, *feed], "")
                n.update(title=title, scene=k, scene_of=sid, prompt_src=sid, first_frame=with_cover,
                         aspect=cfg.get("aspect") or n["aspect"], duration=cfg.get("duration") or n["duration"],
                         scene_hash=fresh[k])
                n.update(carry.get(k) or {})  # model / thời lượng bạn đã chọn ở video cảnh cũ cùng số
                if speech != "none":  # mặc định: lời thoại của đúng cảnh lấy từ storyboard
                    n.update(dialogue_src=sid, voice=who)
                if voice_note:
                    n["voice_note"] = voice_note
                self._fit_options(n)
                link(n, k, cover if with_cover else None)
                mine[k] = n
                created.append(n["id"])
            joined = next((n for n in board["nodes"] if n.get("concat_of") == sid), None)
            order = [mine[k]["id"] for k in sorted(mine) if k <= len(scenes)]
            right = max([sb["x"] + self.SCENE_GAP_X] + [mine[k]["x"] for k in mine]) + self.SCENE_GAP_X
            if joined is None:
                joined = self._new_node(board, "wf", right, sb["y"], order, "", "concat_video")
                joined.update(title="Ghép các cảnh", concat_of=sid)
                joined["config"]["aspect"] = cfg.get("aspect") if cfg.get("aspect") in ("9:16", "16:9", "1:1") else "9:16"
                created.append(joined["id"])
            else:  # cảnh mới nối thêm vào khối Ghép, giữ đúng thứ tự cảnh 1 → N (dây khác của bạn giữ nguyên)
                others = [i for i in joined.get("inputs") or [] if i not in {n["id"] for n in mine.values()}]
                joined["inputs"] = (order + others)[:MAX_INPUTS]
                if joined["x"] < right:  # video vừa lùi sang phải (thêm ảnh bìa) → khối Ghép lùi theo
                    joined["x"] = right
                touched.append(joined["id"])
            if sb.get("wtype") == "product_studio":  # 🎬 duyệt từng clip, Flow, vai trò ảnh bìa, lồng giọng + phụ đề
                dropped.extend(self._studio_post(board, sb, joined, mine, cov, created, touched))
        # clear flow cũ → ghi 1 bước ↶ hoàn tác (lấy lại khối cảnh cũ cùng kết quả của chúng)
        board = self._edit(bid, apply, undo=f"Storyboard {sid}: làm mới các cảnh" if clear else "")
        if dropped:
            self.emit("canvas_drop", {"board": bid, "nodes": dropped})
            self.pool.log(f"Storyboard {sid}: {count} cảnh — đã xoá {len(dropped)} khối ảnh bìa / video của storyboard cũ, "
                          "tạo lại theo storyboard mới (↶ Hoàn tác để lấy lại)", "warn")
        for nid in dict.fromkeys([*created, *touched]):  # node mới → UI thêm vào bảng; node cũ → UI cập nhật tên / dây
            self.emit("canvas_node", {"board": bid, "node": self.public_node(bid, self._node(board, nid))})
        if created:
            kinds = Counter(self._node(board, i)["kind"] for i in created)
            self.pool.log(f"Storyboard {sid}: đã tách {kinds['video']} node Video theo cảnh"
                          + (f" + {kinds['image']} ảnh bìa" if kinds["image"] else "")
                          + (" + khối Ghép các cảnh" if kinds["wf"] else ""), "ok")
        cfg = self._story_cfg(self._node(board, sid))
        self._extend_flow(bid, sid, created, covers, hold=bool(covers) and cfg.get("cover_wait", True))
        return created

    # ------------------------------------------------------------------ 🎬 Product Video Studio
    def _studio_engine(self) -> str:
        """Model video quay các cảnh Studio: màn Grok Canvas → model video định sẵn (Grok); Canvas thường → Google Flow."""
        return (self.models() or {}).get("video") or FLOW_ENGINE

    def _story_cfg(self, sb: dict) -> dict:
        """Cấu hình tách cảnh của khối viết storyboard. Product Video Studio → quy về các ô của Storyboard: Ingredients =
        video nhận thẳng ảnh nhân vật + sản phẩm (không ảnh bìa); Frames = ảnh bìa từng cảnh (duyệt rồi quay); cắt cảnh;
        lồng giọng hậu kỳ → clip không lời; thời lượng = thời lượng clip lớn nhất model video hỗ trợ."""
        cfg = dict(sb.get("config") or {})
        if sb.get("wtype") != "product_studio":
            return cfg
        from .workflow import nodes as wfn

        cfg = {**wfn.defaults("product_studio"), **cfg}
        spec = VIDEO_ENGINES[self._studio_engine()]
        clip = studio_clip(self._studio_engine()) if spec else "8s"
        direct = cfg.get("voice") != "none" and cfg.get("speech") == "direct"
        return {**cfg, "cover": "" if cfg.get("mode") == "frames" else "off", "cover_wait": True, "always_refs": True,
                "master_voice": "", "speech": "character" if direct else "none", "noi_canh": "cut",
                "aspect": cfg.get("aspect") or "9:16", "duration": clip}

    def _studio_post(self, board: dict, sb: dict, joined: dict, mine: dict, cov: dict, created: list,
                     touched: list) -> list:
        """🎬 Sau khi tách cảnh: clip cảnh bắt buộc duyệt, quay bằng model video của Studio; ảnh bìa mang vai trò ảnh
        (nhân vật / sản phẩm); lồng giọng miền Nam (VieNeu) + phụ đề sau khối Ghép; khối cuối cần duyệt trước khi đăng."""
        from .workflow.product_studio import VOICES

        sid, raw = sb["id"], {**(sb.get("config") or {})}
        roles = sb.get("roles") or {}
        eng = self._studio_engine()
        for k in sorted(mine):
            n = mine[k]
            n["qc_required"] = True
            if n.get("engine") != eng:
                n["engine"] = eng
                self._fit_options(n)
            if raw.get("mode", "ingredients") != "frames":
                n["first_frame"] = False  # Ingredients to Video: ảnh nhân vật + sản phẩm là thành phần, không là khung đầu
        for c in cov.values():
            picked = {i: roles[i] for i in c.get("inputs") or [] if roles.get(i) in IMAGE_REF_ROLES}
            if picked:
                c["roles"] = picked
        parts = {n.get("studio_part"): n for n in board["nodes"] if n.get("studio_of") == sid}
        voice, speech = raw.get("voice") or "female_south", raw.get("speech") or "direct"
        narration = "\n\n".join(s.get("loi", "") for s in (sb.get("out") or {}).get("scenes") or [] if s.get("loi"))
        final = joined

        def part(key: str, wtype: str, src: dict, title: str) -> dict:
            n = parts.get(key)
            if n is None:
                n = self._new_node(board, "wf", src["x"] + self.SCENE_GAP_X, src["y"], [src["id"]], "", wtype)
                n.update(title=title, studio_of=sid, studio_part=key)
                parts[key] = n
                created.append(n["id"])
            else:
                if src["id"] not in (n.get("inputs") or []):
                    n["inputs"] = [src["id"], *(n.get("inputs") or [])][:MAX_INPUTS]
                touched.append(n["id"])
            return n

        if voice in VOICES and speech == "voiceover" and narration:
            dub = part("dub", "dub_vieneu", joined, f"🗣 Lồng giọng {VOICES[voice][0]}")
            dub["config"].update(script_mode="manual", script=narration, voice=VOICES[voice][0], mix="duck",
                                 orig_volume="0.15", fit="extend")
            final = dub
            if raw.get("subs", True):
                subs = part("subs", "post_video", dub, "💬 Phụ đề")
                subs["config"].update(script=narration, audio="original", subtitles=True, post_ai=False, bgm=False,
                                      aspect=raw.get("aspect") or "9:16", transition="none", transition_sound="none")
                final = subs
        # chế độ không còn lồng giọng / phụ đề (VD đổi sang "nhân vật nói trong clip") → gỡ khối lồng giọng / phụ đề cũ
        # (trừ khối 🔒 khoá), khối phía sau đang nối vào chúng nối lại sang khối cuối mới
        used = {id(final), id(joined)} | ({id(parts["dub"])} if final is not joined and "dub" in parts else set())
        stale = [n for k, n in parts.items() if id(n) not in used and not n.get("locked")]
        gone = {n["id"] for n in stale}
        if gone:
            board["nodes"] = [n for n in board["nodes"] if n["id"] not in gone]
            for n in board["nodes"]:
                if any(i in gone for i in n.get("inputs") or []):
                    ins = [final["id"] if i in gone else i for i in n.get("inputs") or []]
                    n["inputs"] = [i for i in dict.fromkeys(ins) if i != n["id"]]
                    self._drop_roles(n)
                    touched.append(n["id"])
            created[:] = [i for i in created if i not in gone]
            touched[:] = [i for i in touched if i not in gone]
        for n in (joined, *[p for p in parts.values() if p["id"] not in gone]):
            n.pop("qc_final", None)
            if n is not final:
                n.pop("qc_required", None)
        final.update(qc_required=True, qc_final=True)
        return sorted(gone)

    @staticmethod
    def _qc_file(node: dict) -> str:
        files = node.get("files") or []
        return files[0] if files else ""

    def _qc_ok(self, node: dict) -> bool:
        """Đã duyệt ĐÚNG file kết quả hiện tại (tạo lại clip → phải duyệt lại)."""
        qc = node.get("qc") or {}
        return qc.get("status") == "approved" and bool(qc.get("file")) and qc.get("file") == self._qc_file(node)

    def qc_state(self, node: dict) -> str:
        if not node.get("qc_required"):
            return ""
        qc = node.get("qc") or {}
        if not self._qc_file(node):
            return "empty"
        if qc.get("file") != self._qc_file(node):
            return "pending"
        return qc.get("status") or "pending"

    def qc(self, bid: str, nid: str, decision: str, notes: str = "", checks: list | None = None, by: str = "") -> dict:
        """✅ Kiểm duyệt 1 clip / bản cuối: approved / rejected (bắt buộc lý do) / reset. Ghi người duyệt, thời điểm, các
        mục checklist đã đối chiếu và lịch sử (mục 10)."""
        if decision not in ("approved", "rejected", "reset"):
            raise CanvasError("Quyết định kiểm duyệt không hợp lệ")
        if decision == "rejected" and not str(notes or "").strip():
            raise CanvasError("Ghi lý do từ chối (VD: nhãn bị méo, sai khuôn mặt) để làm lại đúng chỗ")

        def apply(board):
            n = self._node(board, nid)
            cur = self._qc_file(n)
            if decision != "reset" and not cur:
                raise CanvasError("Khối chưa có kết quả để duyệt — tạo clip trước")
            entry = {"status": "pending" if decision == "reset" else decision, "notes": str(notes or "")[:1000],
                     "checks": [str(c)[:200] for c in checks or []][:24], "by": str(by or "")[:80], "at": now(),
                     "file": cur}
            hist = ((n.get("qc") or {}).get("history") or [])[-19:]
            n["qc"] = {**entry, "history": hist + [entry]}
        board = self._edit(bid, apply, undo=f"Kiểm duyệt {nid}")  # bấm từ giao diện (ngoài tác vụ) → lịch sử lưu ở khối
        self._push(bid, nid)
        return self.public(board)

    def _qc_gate(self, board: dict, node: dict) -> str:
        """Lý do CHƯA được chạy (rỗng = chạy được): khối Ghép của Studio chờ duyệt mọi clip; khối Đăng chờ duyệt bản cuối
        + dữ liệu sản phẩm đã kiểm duyệt (mục 5.3, nguyên tắc phát hành)."""
        nodes = {n["id"]: n for n in board["nodes"]}
        studio = nodes.get(node.get("concat_of") or "")
        if node.get("wtype") == "concat_video" and studio and studio.get("wtype") == "product_studio" \
                and (studio.get("config") or {}).get("qc_gate", True):
            wait = [f"{i}{' (từ chối)' if (nodes[i].get('qc') or {}).get('status') == 'rejected' else ''}"
                    for i in node.get("inputs") or [] if i in nodes and nodes[i].get("qc_required") and not self._qc_ok(nodes[i])]
            if wait:
                return (f"⏸ Chờ duyệt clip: {', '.join(wait)} — xem từng clip, bấm ✅ Duyệt (hoặc ❌ Từ chối rồi tạo lại) "
                        "rồi chạy lại khối Ghép")
        if node.get("wtype") in POST_TYPES:
            for i in node.get("inputs") or []:
                src = nodes.get(i)
                if not src:
                    continue
                if src.get("qc_required") and not self._qc_ok(src):
                    return f"⏸ Video {i} chưa được duyệt cuối — xem lại, bấm ✅ Duyệt rồi mới đăng"
        return ""

    @staticmethod
    def _scene_hash(scene: dict) -> str:
        """Dấu nội dung 1 cảnh storyboard — khối cảnh tạo từ nội dung khác → là flow cũ."""
        return hashlib.md5(json.dumps(scene, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def _old_scenes(self, board: dict, sid: str) -> set:
        """Ảnh bìa / video thuộc Storyboard sid nhưng tạo từ nội dung cảnh khác storyboard hiện tại (cảnh đã đổi, cảnh
        thừa, board cũ chưa có dấu) — không tính khối 🔒 khoá."""
        scenes = (self._node(board, sid).get("out") or {}).get("scenes") or []
        fresh = {k: self._scene_hash(s) for k, s in enumerate(scenes, 1)}
        return {n["id"] for n in board["nodes"] if sid in (n.get("scene_of"), n.get("cover_of")) and not n.get("locked")
                and n.get("scene_hash") != fresh.get(int(n.get("scene") or 0))}

    def _stale(self, board: dict, nid: str) -> bool:
        """Khối cần (tạo) lại: chưa có kết quả / lỗi / đầu vào hay prompt đã đổi — và không khoá."""
        n = self._node(board, nid)
        return not n.get("locked") and (n.get("status") != "done" or n.get("sig") != self._sig(board, nid))

    def _extend_flow(self, bid: str, sid: str, new: list, covers: list | None = None, hold: bool = False) -> None:
        """Storyboard vừa tách cảnh. Ảnh bìa (mới / cần tạo lại) luôn chạy ngay: đang trong 1 lượt chạy → nối vào lượt đó,
        không thì mở 1 lượt "Ảnh bìa các cảnh". Video cảnh + khối Ghép: lượt Chạy toàn bộ / Chạy từ đây → chạy luôn, trừ
        khi hold (chờ duyệt ảnh bìa) → rút video cảnh và mọi khối phía sau chúng khỏi lượt này."""
        board = self.load(bid)
        covers = [c for c in covers or [] if self._has(board, c) and self._stale(board, c)]
        live = self._live.get(bid)
        if not live:
            if covers:
                try:
                    self.run_flow(bid, "set", only=covers, label="Ảnh bìa các cảnh")
                except CanvasError as exc:
                    self.pool.log(f"Chưa tạo được ảnh bìa ({exc}) — bấm ▶ Chạy toàn bộ để tạo", "warn")
            return
        rid, order, mode = live
        task = self._node(board, sid).get("task") or ""  # tác vụ của lượt chạy (node trong lượt dùng chung)
        if hold:
            scenes = [n["id"] for n in board["nodes"] if n.get("scene_of") == sid]
            after = set(scenes).union(*(self._related(board, v, False) for v in scenes)) - set(covers)
            drop = [nid for nid in order if nid in after]
            for nid in drop:
                order.remove(nid)
                n = self._node(board, nid)
                if n.get("status") == "queued":
                    self._set_node(bid, nid, status="done" if n.get("files") or n.get("out") else "idle", task="")

            def unlist(b):
                rec = next((r for r in b.get("runs") or [] if r["id"] == rid), None)
                if rec is not None:
                    for nid in drop:
                        rec["nodes"].pop(nid, None)
                    rec["review"] = sorted(set(rec.get("review") or []) | after)  # khối chờ bạn duyệt ảnh bìa rồi chạy
            self._edit(bid, unlist)
            self.pool.log("🖼 Ảnh bìa các cảnh tạo xong sẽ dừng chờ bạn duyệt — ảnh nào chưa ưng thì sửa prompt / bấm Tạo "
                          "lại, rồi bấm ▶ Chạy toàn bộ để quay video", "ok")
        grow = list(covers)
        if mode in ("all", "from") and not hold:
            grow += [nid for nid in new if self._node(board, nid)["kind"] != "image"]
        concat = next((n["id"] for n in board["nodes"] if n.get("concat_of") == sid and n["id"] in order), None)
        for nid in grow:
            if nid in order:
                continue
            if concat is not None and self._node(board, nid)["kind"] in ("video", "image"):
                order.insert(order.index(concat), nid)
            else:
                order.append(nid)
            self._set_node(bid, nid, status="queued", pct=0, error="", task=task)
            self._run_record(bid, rid, node=(nid, "queued"))

    # ------------------------------------------------------------------ chạy cả quy trình (như Workflow)
    @staticmethod
    def _topo(board: dict) -> list[str]:
        """Thứ tự chạy: node phía trước chạy trước; cùng lúc sẵn sàng thì trái → phải, trên → dưới."""
        nodes = {n["id"]: n for n in board["nodes"]}
        kids = {nid: [] for nid in nodes}
        need = {}
        for n in nodes.values():
            ins = [i for i in n.get("inputs") or [] if i in nodes]
            need[n["id"]] = len(ins)
            for i in ins:
                kids[i].append(n["id"])
        pos = lambda nid: (nodes[nid]["x"], nodes[nid]["y"])  # noqa: E731
        ready, out = sorted((k for k, v in need.items() if v == 0), key=pos), []
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for k in kids[cur]:
                need[k] -= 1
                if need[k] == 0:
                    ready.append(k)
            ready.sort(key=pos)
        return out

    @staticmethod
    def _related(board: dict, nid: str, up: bool) -> set:
        """Mọi node phía trước (up) hoặc phía sau của nid."""
        nodes = {n["id"]: n for n in board["nodes"]}
        seen, stack = set(), [nid]
        while stack:
            cur = stack.pop()
            nxt = nodes[cur]["inputs"] if up else [n["id"] for n in nodes.values() if cur in (n.get("inputs") or [])]
            for x in nxt:
                if x in nodes and x not in seen:
                    seen.add(x)
                    stack.append(x)
        return seen

    def _sig(self, board: dict, nid: str, memo: dict | None = None, raw: bool = False) -> str:
        """Dấu vân tay node = cấu hình + prompt + model + dấu của node phía trước và kết quả chúng đưa sang.
        Không đổi → lần chạy quy trình sau dùng lại kết quả, không tạo lại (không tốn lượt).
        Khối 🔒 khoá: dùng dấu đã lưu (kết quả giữ nguyên → khối phía sau thấy đầu vào không đổi). raw = tính mới cho
        chính node nid (bỏ qua khoá) — lúc ghi dấu sau khi chạy / chọn lại phiên bản."""
        memo = {} if memo is None else memo
        if nid in memo and not raw:
            return memo[nid]
        node = next(n for n in board["nodes"] if n["id"] == nid)
        if node.get("locked") and node.get("sig") and not raw:
            memo[nid] = node["sig"]
            return memo[nid]
        ins = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src is not None:
                # khối trước đã có kết quả → dùng dấu lúc nó TẠO ra kết quả đó (sửa prompt khối trước mà chưa chạy lại
                # thì kết quả nó đưa sang vẫn vậy → khối này không phải chạy lại); chưa có kết quả / khối nhập → dấu hiện tại
                up = src["sig"] if src.get("status") == "done" and src.get("sig") and not self._passive(src) \
                    else self._sig(board, iid, memo)
                ins.append([up, src.get("files"), src.get("pick"), (src.get("out") or {}).get("text")])
        # vai trò dây nối chỉ thêm vào khi có (khối chưa đặt vai trò giữ nguyên dấu cũ → không bị chạy lại)
        text = json.dumps([{k: node.get(k) for k in SIG_KEYS}, node.get("files") if node["kind"] == "upload" else None, ins]
                          + self._sig_extra(node), sort_keys=True, ensure_ascii=False, default=str)
        sig = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        if not raw:
            memo[nid] = sig
        return sig

    def _sig_legacy(self, board: dict, nid: str, memo: dict) -> str:
        """Công thức dấu vân tay cũ (trước khi có 🔒 khoá / bỏ chọn): dùng khi chuyển dữ liệu bảng cũ (_migrate_sigs)."""
        if nid in memo:
            return memo[nid]
        node = next(n for n in board["nodes"] if n["id"] == nid)
        ins = [[self._sig_legacy(board, i, memo), s.get("files"), s.get("pick"), (s.get("out") or {}).get("text")]
               for i in node.get("inputs") or [] for s in [next((n for n in board["nodes"] if n["id"] == i), None)] if s]
        text = json.dumps([{k: node.get(k) for k in SIG_KEYS}, node.get("files") if node["kind"] == "upload" else None, ins],
                          sort_keys=True, ensure_ascii=False, default=str)
        memo[nid] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return memo[nid]

    def _migrate_sigs(self, board: dict) -> None:
        """Bảng tạo trước bản này: khối có dấu khớp công thức cũ (= kết quả còn mới) → ghi lại dấu theo công thức mới,
        để lần chạy đầu sau khi cập nhật KHÔNG chạy lại hàng loạt (tốn lượt). Khối đã cũ sẵn thì để nguyên (chạy lại như
        trước)."""
        nodes = {n["id"]: n for n in board["nodes"]}
        memo = {}
        fresh = {nid for nid, n in nodes.items() if n.get("status") == "done" and n.get("sig")
                 and n["sig"] == self._sig_legacy(board, nid, memo)}
        for nid in self._topo(board):  # khối trước ghi xong mới tới khối sau (công thức mới đọc dấu đã lưu của khối trước)
            if nid in fresh:
                nodes[nid]["sig"] = self._sig(board, nid, raw=True)
                nodes[nid].setdefault("sig_own", self._sig_own(nodes[nid]))

    @staticmethod
    def _sig_own(node: dict) -> str:
        """Dấu của riêng node (prompt, model, cấu hình…, không tính đầu vào) — biết "bạn đã sửa khối này" hay "đầu vào đổi"."""
        text = json.dumps([{k: node.get(k) for k in SIG_KEYS}, node.get("files") if node["kind"] == "upload" else None]
                          + CanvasRunner._sig_extra(node), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _sig_extra(node: dict) -> list:
        """Trường thêm sau này chỉ vào dấu vân tay khi CÓ (khối không dùng giữ nguyên dấu cũ → không bị chạy lại):
        vai trò dây nối, giọng cố định từ hồ sơ Storyboard."""
        return ([node["roles"]] if node.get("roles") else []) + ([{"voice_note": node["voice_note"]}] if node.get("voice_note") else [])

    @staticmethod
    def _web_links(nodes: dict, ins: list) -> list:
        """🖼 Khối Tra cứu web cấp ảnh cho các khối Ảnh tải lên trong ins (khối dùng ảnh đó phải chờ / chạy theo chúng)."""
        return [j for i in ins if i in nodes and nodes[i]["kind"] == "upload"
                for j in nodes[i].get("inputs") or [] if j in nodes]

    @staticmethod
    def _passive(node: dict) -> bool:
        """Node không cần chạy: ảnh tải lên, Văn bản (đưa thẳng chữ đang gõ sang node sau)."""
        return node["kind"] == "upload" or node.get("wtype") == "input_text"

    def plan(self, board: dict, mode: str = "all", target: str = "", fresh: bool = False, targets: list | None = None,
             skip: list | None = None) -> dict:
        """Kế hoạch chạy: {run: [node chạy thật theo thứ tự], reuse: [node dùng lại kết quả], scope: [mọi node liên quan],
        why: {node chạy: {code, up}}, held: [🔒 khối khoá — giữ kết quả], skipped: [khối bạn bỏ chọn], blocked: [khối phải
        bỏ vì khối phía trước không chạy mà chưa có kết quả]}.
        mode = all | to (chạy đến target: node phía trước + target) | from (target + node phía sau)
        | set (làm lại các node targets + node phía sau chúng — BỎ khối đăng bài / lên lịch / quảng cáo).
        skip = khối bỏ chọn ở bảng xem trước (lượt này giữ kết quả cũ của chúng, không làm khối phía sau phải chạy lại)."""
        if mode not in ("all", "to", "from", "set"):
            raise CanvasError("Kiểu chạy không hợp lệ")
        nodes = {n["id"]: n for n in board["nodes"]}
        if mode == "set":
            targets = [t for t in targets or [] if t in nodes]
            if not targets:
                raise CanvasError("Chưa có khối nào để làm lại")
            scope = set(targets).union(*(self._related(board, t, False) for t in targets))
            scope = {nid for nid in scope if nodes[nid].get("wtype") not in POST_TYPES}
            target = ""
        elif mode != "all":
            self._node(board, target)
        if mode != "set":
            scope = (set(n["id"] for n in board["nodes"]) if mode == "all" else
                     self._related(board, target, True) | {target} if mode == "to" else
                     self._related(board, target, False) | {target})
        skip = set(skip or [])
        memo, run, reuse, why, held, skipped, blocked = {}, [], [], {}, [], [], []
        dead = set()  # khối lượt này không có kết quả để đưa sang khối sau (bỏ chọn / khoá mà chưa có kết quả)
        for nid in self._topo(board):
            if nid not in scope:
                continue
            node = nodes[nid]
            if self._passive(node):
                continue
            ins = [i for i in node.get("inputs") or [] if i in nodes]
            done = node.get("status") == "done"
            if node.get("locked") and done:  # 🔒 giữ kết quả, không làm khối sau phải chạy lại
                held.append(nid)
                continue
            if nid in skip or node.get("locked"):
                skipped.append(nid)
                if not done:
                    dead.add(nid)
                continue
            if any(i in dead for i in ins):
                blocked.append(nid)
                dead.add(nid)
                continue
            up = [i for i in ins + self._web_links(nodes, ins) if i in run]  # 🖼 ảnh từ web đổi → chạy lại
            if fresh:
                code = "fresh"
            elif mode == "set" and nid in targets:
                code = "set"
            elif mode in ("to", "from") and nid == target:
                code = "target"
            elif node.get("status") == "error":
                code = "error"
            elif not done:
                code = "unfinished" if node.get("files") or node.get("out") else "new"
            elif node.get("sig") != self._sig(board, nid, memo):
                code = ("own" if node.get("sig_own") != self._sig_own(node) else "input") if node.get("sig_own") else "changed"
            elif up:
                code = "upstream"
            else:
                code = "from" if mode == "from" else ""
            if code:
                run.append(nid)
                why[nid] = {"code": code, "text": WHY[code], "up": up}
            else:
                reuse.append(nid)
        return {"run": run, "reuse": reuse, "scope": sorted(scope), "why": why, "held": held, "skipped": skipped,
                "blocked": blocked}

    def check(self, board: dict, ids: list) -> list:
        """Lỗi / cảnh báo trước khi chạy: khối bật "✏ Không bắt buộc nhập" (node.optional) → lỗi thiếu đầu vào của nó thành
        cảnh báo, khối vẫn chạy với giá trị đang có (để trống prompt / ô vẫn chạy)."""
        nodes = {n["id"]: n for n in board["nodes"]}
        out = []
        for i in self._check_raw(board, ids):
            n = nodes.get(i["node"])
            if i["level"] == "error" and n is not None and n.get("optional"):
                i = {**i, "level": "warn", "optional": True,
                     "message": f"✏ Không bắt buộc nhập — vẫn chạy: {i['message']}"}
            out.append(i)
        return out

    def _check_raw(self, board: dict, ids: list) -> list:
        """Lỗi / cảnh báo trước khi chạy (như Workflow): [{node, level: error|warn, message}]."""
        issues = []
        nodes = {n["id"]: n for n in board["nodes"]}
        add = lambda nid, level, msg: issues.append({"node": nid, "level": level, "message": msg})  # noqa: E731
        for nid in ids:
            n = nodes[nid]
            srcs = [nodes[i] for i in n.get("inputs") or [] if i in nodes]
            got = set().union(*(out_types(x) for x in srcs)) if srcs else set()
            psrc = self._prompt_src(n)
            own = self._own_prompt(n)
            text_in = False if psrc == "own" else "text" in out_types(nodes[psrc]) if psrc else "text" in got
            has_img = "images" in got or bool(n.get("ref_files")) or bool(n.get("angles"))
            if n["kind"] == "image" and not own and not text_in and not has_img:
                add(nid, "error", "Ảnh chưa có prompt và chưa nối ảnh nào (viết prompt, nối khối chữ hoặc nối ảnh vào)")
            elif n["kind"] == "video" and not ({"images", "video"} & got) and not text_in and not own:
                add(nid, "error", "Video chưa có ảnh / video đầu vào hoặc prompt")
            scene_src = nodes.get(n.get("scene_of") or "")
            if n["kind"] == "video" and scene_src is not None and scene_src.get("status") == "done" \
                    and self._scene_for(scene_src, n) == {} and scene_src["id"] not in ids:
                add(nid, "error", f"Storyboard {scene_src['id']} không còn cảnh {n.get('scene')} — xoá node này hoặc viết lại storyboard")
            prev = nodes.get(n.get("chain_from") or "")
            if n["kind"] == "video" and prev is not None and prev.get("status") != "done" and prev["id"] not in ids:
                add(nid, "warn", f"Liền mạch: video cảnh trước ({prev['id']}) chưa có — cảnh này sẽ quay từ ảnh bìa, không nối liền")
            spoken = self._dialogue_text(board["id"], board, n) if n["kind"] == "video" else ""
            if n["kind"] == "video" and n.get("dialogue_src") and not spoken:
                src = nodes.get(n["dialogue_src"])
                if src is not None and src.get("status") != "done" and src.get("wtype") != "input_text" \
                        and src["id"] not in ids:
                    add(nid, "warn", f"Lời thoại lấy từ {src['id']} nhưng khối đó chưa có chữ — chạy nó trước (hoặc chạy cả quy trình)")
            if n["kind"] == "video" and spoken.strip() and not self._parts_of(board, nid):
                words, limit = dialogue_words({"dialogue": spoken}), dialogue_limit(n)
                if words > limit:
                    parts = len(split_dialogue(spoken, limit))
                    if n.get("auto_split") is False:
                        add(nid, "warn", f"Lời thoại {words} chữ — dài so với clip {n.get('duration')} (nên ≤ {limit} chữ), "
                                         f"dễ nói vội / bị cắt — ✂ tách thành {parts} video")
                    else:
                        add(nid, "warn", f"Lời thoại {words} chữ — dài so với clip {n.get('duration')} (≤ {limit} chữ/clip): "
                                         f"✂ sẽ tách thành {parts} video con (khối chung giữ nguyên) rồi ghép lại thành 1")
                    issues[-1]["split"] = parts
            elif n["kind"] == "wf":
                from . import api_mode

                # 🔑 chỉ dùng model trình duyệt: model API cũ sẽ chạy bằng bản trình duyệt → không báo thiếu khoá API
                cfg, kind = api_mode.config(self._as_run(n).get("config") or {}, self.settings), n["wtype"]
                if kind in ("fb_post", "fb_schedule") and not cfg.get("page_id"):
                    if n.get("auto_post"):  # tự đăng không dừng chờ duyệt → phải chọn trước
                        add(nid, "error", "Chưa chọn Fanpage (khối đang bật 🚀 Tự đăng — chọn Fanpage trước khi chạy)")
                    else:  # 📣 chọn Fanpage lúc duyệt đăng bài (hoặc ở Quản lý bài đăng)
                        add(nid, "warn", "Chưa chọn Fanpage — chọn lúc duyệt đăng bài")
                if kind in ("fb_post", "fb_schedule") and not srcs and not str(cfg.get("caption") or "").strip():
                    add(nid, "error", "Chưa có gì để đăng — nối chữ (caption) và / hoặc ảnh / video vào")
                if kind == "fb_ad":
                    if not cfg.get("account_id"):
                        add(nid, "error", "Chưa chọn tài khoản quảng cáo")
                    if "post" not in got:
                        add(nid, "error", "Nối khối Đăng bài Facebook vào khối Tạo quảng cáo")
                if kind == "concat_video" and "video" not in got:
                    add(nid, "error", "Ghép video chưa có video đầu vào")
                if kind == "dub_vieneu" and "video" not in got:
                    add(nid, "error", "Lồng tiếng chưa có video — nối node Video / Ghép video / Video đầu vào vào")
                if kind == "dub_vieneu" and "text" not in got and not str(cfg.get("script") or "").strip() \
                        and cfg.get("script_mode") != "analyze":  # phân tích video → model tự viết lời đọc
                    add(nid, "error", "Lồng tiếng chưa có lời đọc — nhập lời đọc hoặc nối khối chữ vào")
                if kind == "dub_vieneu":
                    from .pipeline import vieneu_tts

                    st = vieneu_tts.status()
                    if not st["python"]:
                        add(nid, "error", "Chưa có Python 3.10+ trên máy để cài VieNeu (python.org)")
                    elif not st["installed"]:
                        add(nid, "warn", "Lần chạy đầu app sẽ cài VieNeu-TTS + tải model (cần internet, vài phút)")
                if kind == "post_video" and "video" not in got:
                    add(nid, "error", "Hậu kỳ video chưa có video — nối node Video / Ghép video / Video đầu vào vào")
                style = cfg.get("post_style", "remotion")
                if kind == "post_video" and cfg.get("post_ai", True) and style == "hyperframes":
                    from .pipeline import hyperframes as hfm

                    st = hfm.status()
                    if not (st.get("node_ok") and st.get("ffprobe")):
                        add(nid, "warn", "HyperFrames cần Node.js 22+ và ffprobe trên máy — chưa có thì app tự dùng phụ đề nổi bật thường")
                if kind == "post_video" and cfg.get("post_ai", True) and style == "remotion":
                    from .pipeline import remotion_post

                    st = remotion_post.status()
                    if not st.get("node_ok"):
                        add(nid, "warn", "Remotion cần Node.js 18+ trên máy — chưa có thì app tự dùng phụ đề nổi bật thường")
                    elif not st.get("installed"):
                        add(nid, "warn", "Lần chạy đầu app sẽ cài Remotion (cần internet, ~1–3 phút)")
                if kind == "product_studio":  # 🎬 dữ liệu tối thiểu + Content Lock trước khi tốn lượt model
                    from .workflow import nodes as wfn0

                    scfg = {**wfn0.defaults(kind), **cfg}
                    if not str(scfg.get("p_name") or "").strip():
                        add(nid, "error", "Product Video Studio: nhập Tên sản phẩm")
                    if "images" not in got:
                        add(nid, "warn", "Chưa nối ảnh nhân vật / sản phẩm — bấm 📎 Nhân vật / 📦 Sản phẩm ở khối để thêm "
                                         "(không có ảnh thì khó giữ đúng mặt / bao bì)")
                    if not str(scfg.get("p_facts") or "").strip():
                        add(nid, "warn", "Chưa có thông tin sản phẩm — AI sẽ không nói về thành phần / công dụng")
                if kind == "heygen_video":
                    from .llm import heygen_api
                    from .workflow import nodes as wfn

                    hcfg = {**wfn.defaults(kind), **cfg}
                    if not api_mode.enabled(self.settings):
                        add(nid, "error", "Video HeyGen cần bật “Dùng model qua API key” (Cài đặt → Model AI)")
                    elif not self.settings.get("heygen_api_key"):
                        add(nid, "error", "Chưa có HeyGen API key — nhập ở Cài đặt → API key")
                    if "text" not in got and not str(hcfg.get("script") or "").strip():
                        add(nid, "error", "Video HeyGen chưa có lời thoại — nhập ô Lời thoại hoặc nối khối chữ vào")
                    if hcfg.get("mode") == "photo":
                        if "images" not in got:
                            add(nid, "error", "Ảnh biết nói: nối khối ảnh người nói (PNG / JPG) vào")
                        if not str(hcfg.get("voice_id") or "").strip():
                            add(nid, "error", "Ảnh biết nói cần chọn giọng đọc")
                    elif not str(hcfg.get("avatar_id") or "").strip():
                        add(nid, "error", "Video HeyGen chưa chọn avatar")
                    script = str(hcfg.get("script") or "").strip()
                    if len(script) > heygen_api.MAX_SCRIPT:
                        add(nid, "error", f"Lời thoại {len(script)} ký tự — HeyGen nhận tối đa {heygen_api.MAX_SCRIPT}")
                    add(nid, "warn", "Video HeyGen tốn credit HeyGen mỗi lần tạo")
                if kind == "ai_text" and not str(cfg.get("prompt") or "").strip():
                    add(nid, "error", "AI viết chưa có yêu cầu")
                if kind == "edit_pro":
                    from .pipeline import edit_pro

                    link = str(cfg.get("drive_link") or "").strip()
                    if "video" not in got and not link:
                        add(nid, "error", "Edit Pro: nối khối Video / Video đầu vào (video nói chuyện quay thô), hoặc "
                                          "dán link Google Drive")
                    elif link and not edit_pro.is_drive_link(link):
                        add(nid, "error", "Edit Pro: link không phải Google Drive (drive.google.com/…)")
                    if cfg.get("review", True):
                        add(nid, "warn", "Edit Pro dùng 2 lượt Claude (viết kịch bản + tự kiểm tra bản nháp)")

                    st = edit_pro.status(self.settings)
                    if not st["ok"]:
                        add(nid, "error", "Edit Pro: " + "; ".join(st["problems"]) + f" — {st['hint']}")
                if kind == "web_research" and not text_in and not str(cfg.get("topic") or "").strip() \
                        and not str(cfg.get("urls") or "").strip():
                    add(nid, "error", "Tra cứu web: nhập chủ đề / link, hoặc nối khối chữ vào")
                if kind == "web_research" and cfg.get("provider") in ("claude_api", "gemini_api"):
                    key = "anthropic_api_key" if cfg["provider"] == "claude_api" else "gemini_api_key"
                    if not self.settings.get(key):
                        add(nid, "error", f"Tra cứu web: chưa có khoá {'Anthropic' if key[0] == 'a' else 'Gemini'} "
                                          "API (Cài đặt → API & kết nối)")
                if kind == "mcp_product":
                    from . import mcp_hub

                    if not text_in and not str(cfg.get("product") or "").strip():
                        add(nid, "error", "Tra cứu MCP: nhập sản phẩm cần tra, hoặc nối khối chữ vào")
                    mtools = mcp_hub.tools_for(str(cfg.get("server") or ""))
                    if not mtools:
                        add(nid, "error", "Tra cứu MCP: chưa có kết nối MCP đang bật có công cụ được phép — mở 🔌 Kết nối MCP")
                    elif cfg.get("mode") == "tool" and not str(cfg.get("tool") or ""):
                        add(nid, "error", "Tra cứu MCP: chọn công cụ cần gọi")
                    elif cfg.get("mode") == "tool" and str(cfg["tool"]) not in {f"{t['sid']}::{t['name']}" for t in mtools}:
                        add(nid, "error", "Tra cứu MCP: công cụ đã chọn không còn được phép (hoặc kết nối đang tắt) — "
                                          "chọn lại, hoặc cho phép ở 🔌 Kết nối MCP")
                    if cfg.get("mode", "ai") != "tool" and cfg.get("provider", "claude_api") == "claude_api" \
                            and api_mode.enabled(self.settings) and not self.settings.get("anthropic_api_key"):
                        add(nid, "error", "Tra cứu MCP: chưa có khoá Anthropic API (Cài đặt → API & kết nối) — hoặc đổi model")
                if kind == "content_post" and not text_in and not (str(cfg.get("sp_name") or "").strip()
                                                                  and str(cfg.get("sp_benefits") or "").strip()):
                    add(nid, "error", "Tạo content: nhập Tên sản phẩm + Công dụng, hoặc nối chữ thông tin sản phẩm vào")
                if kind == "studio_video" and not text_in and not str(cfg.get("idea") or "").strip():
                    add(nid, "error", "Video dài chưa có ý tưởng")
                if kind == "storyboard_video" and not text_in and len(str(cfg.get("request") or "").strip()) < 10:
                    add(nid, "error", "Storyboard → Video chưa có yêu cầu (nhập hoặc nối khối chữ vào)")
                if kind == "whiteboard_video" and not text_in and not str(cfg.get("text") or "").strip() \
                        and not cfg.get("srt"):
                    add(nid, "error", "Whiteboard chưa có SRT / kịch bản")
                if kind == "input_video" and not cfg.get("files"):
                    add(nid, "error", "Chưa chọn video")
                if kind == "output" and not srcs:
                    add(nid, "warn", "Khối Kết quả chưa nối gì vào")
        feeding = {i for nid in ids for i in nodes[nid].get("inputs") or []}
        for n in nodes.values():  # ảnh đầu vào chưa có ảnh mà node phía sau cần dùng
            if n["kind"] == "upload" and n["id"] in feeding and not n.get("files") and n.get("inputs"):
                add(n["id"], "warn", "Chưa có ảnh — sẽ lấy ảnh sản phẩm từ khối Tra cứu web; web không có ảnh thì bạn cần "
                                     "tải ảnh lên (khối dùng ảnh phía sau được bỏ qua)")
            elif n["kind"] == "upload" and n["id"] in feeding and not n.get("files"):
                add(n["id"], "error", "Ảnh đầu vào chưa có ảnh — bấm ⬆ Chọn ảnh, hoặc bật ❓ Hỏi khi chạy")
        for n in nodes.values():  # Văn bản rỗng mà có node phía sau dùng
            if n.get("wtype") == "input_text" and not str((n.get("config") or {}).get("text") or "").strip() \
                    and any(n["id"] in (nodes[i].get("inputs") or []) for i in ids):
                add(n["id"], "error", "Văn bản đang trống")
        return issues

    def preview(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False, skip: list | None = None) -> dict:
        """Bảng xem trước lượt chạy: kế hoạch + lý do từng khối chạy + tốn lượt model gì + thời gian ước tính + lỗi cần sửa."""
        board = self.load(bid)
        plan = self.plan(board, mode, target, fresh, skip=skip)
        nodes = {n["id"]: n for n in board["nodes"]}
        scope = set(plan["scope"])
        # ❓ hỏi khi chạy: mọi khối bật "Hỏi khi chạy" (sửa prompt / cấu hình / chọn file) + ảnh đầu vào chưa có ảnh
        ask = [nid for nid in self._topo(board) if nid in scope and (
            nodes[nid].get("ask") or (nodes[nid]["kind"] == "upload" and not nodes[nid].get("files")
                                      and not nodes[nid].get("inputs")) or  # 🖼 ảnh lấy từ web → không hỏi chọn ảnh
            (nodes[nid].get("wtype") == "input_video" and (nodes[nid].get("config") or {}).get("ask")))]
        uses, secs, unknown = Counter(), 0, 0
        info = {}
        for nid in plan["run"]:
            n = nodes[nid]
            use = usage(self._as_run(n))
            for label, k in use:
                uses[label] += k
            if n.get("wtype") in POST_TYPES:  # khối đăng: thời gian = chờ bạn duyệt → không tính
                pass
            elif "secs" in n:
                secs += int(n["secs"] or 0)
            else:
                unknown += 1
            info[nid] = {"usage": use, "secs": n.get("secs") or 0}
        shown = [*plan["run"], *plan["reuse"], *plan["held"], *plan["skipped"], *plan["blocked"]]
        labels = {nid: {"name": self.label(nodes[nid]), "title": nodes[nid].get("title", ""), "kind": nodes[nid]["kind"],
                        "wtype": nodes[nid].get("wtype", ""), "status": nodes[nid].get("status", "")} for nid in shown}
        local = uses.pop(LOCAL_USE, 0)
        return {**plan, "ask": ask, "issues": self.check(board, plan["run"]), "info": info, "labels": labels,
                "usage": sorted(uses.items(), key=lambda kv: -kv[1]) + ([(LOCAL_USE, local)] if local else []),
                "est": {"secs": secs, "unknown": unknown},
                "posts": [nid for nid in plan["run"]
                          if nodes[nid].get("wtype") in ("fb_post", "fb_schedule", "fb_ad") and not nodes[nid].get("auto_post")
                          and not (nodes[nid].get("to_posts") and nodes[nid].get("wtype") != "fb_ad")],
                "review_posts": [nid for nid in plan["run"] if nodes[nid].get("wtype") in ("fb_post", "fb_schedule")
                                 and nodes[nid].get("to_posts") and not nodes[nid].get("auto_post")],
                "auto_posts": [nid for nid in plan["run"]
                               if nodes[nid].get("wtype") in ("fb_post", "fb_schedule") and nodes[nid].get("auto_post")]}

    def run_flow(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False, *, targets: list | None = None,
                 origin: str = "", round_no: int = 0, label: str = "", skip: list | None = None,
                 only: list | None = None) -> dict:
        """Chạy quy trình trong 1 tác vụ: lần lượt từng node theo thứ tự; node lỗi → bỏ qua nhánh phía sau nó,
        nhánh khác chạy tiếp; đăng bài vẫn dừng chờ duyệt. origin = "autopilot" khi trợ lý Claude giao làm lại (vòng round_no).
        skip = khối bạn bỏ chọn ở bảng xem trước (giữ kết quả cũ)."""
        with self._lock:
            board = self.load(bid)
            if any(n.get("status") in ACTIVE for n in board["nodes"]):
                raise CanvasError("Đang có node chạy — chờ xong hoặc bấm Dừng")
            if only:  # đúng các khối này, không kéo theo khối phía sau (VD: ảnh bìa các cảnh vừa tách từ Storyboard)
                plan = {"run": [i for i in self._topo(board) if i in only], "reuse": [], "held": [], "skipped": [],
                        "blocked": []}
            else:
                plan = self.plan(board, mode, target, fresh, targets, skip=skip)
            errors = [i for i in self.check(board, plan["run"]) if i["level"] == "error"]
            if errors:
                raise CanvasError("Quy trình còn lỗi: " + "; ".join(f"{i['node']}: {i['message']}" for i in errors[:4]))
            if not plan["run"]:
                raise CanvasError("Không có node nào cần chạy — mọi kết quả đã mới nhất (bấm “Chạy lại tất cả” để tạo lại)")
            runs = board.setdefault("runs", [])
            board["run_seq"] = int(board.get("run_seq") or 0) + 1
            rid = f"r{board['run_seq']}"
            label = label or {"all": "Chạy toàn bộ", "to": f"Chạy đến {target}", "from": f"Chạy từ {target}",
                              "set": "Làm lại " + ", ".join(targets or [])}[mode]
            record = {"id": rid, "label": label + (" (làm lại từ đầu)" if fresh else ""), "at": now(), "ended": "",
                      "status": "running", "nodes": {nid: "queued" for nid in plan["run"]},
                      "reused": plan["reuse"], "held": plan["held"], "skipped": plan["skipped"] + plan["blocked"],
                      "current": "", **({"origin": origin, "round": int(round_no)} if origin else {})}
            self._grow[bid] = mode  # Storyboard tách cảnh giữa chừng → ảnh bìa (+ video nếu all / from) chạy luôn lượt này
            task = self.pool.submit(f"Canvas · {board['name']} · {label}", self._flow, bid, rid, plan["run"],
                                    meta={"board": bid, "flow": rid})
            record["task"] = task
            for old in (runs + [record])[:-MAX_RUNS]:  # lượt cũ rơi khỏi lịch sử → bỏ luôn nhật ký của nó
                self._unlink(self.root / bid / "logs" / f"{old['id']}.jsonl")
            board["runs"] = (runs + [record])[-MAX_RUNS:]
            for nid in plan["run"]:
                self._node(board, nid).update(status="queued", pct=0, error="", task=task)
            self._save(board)
        self.emit("canvas_flow", {"board": bid, "run": record})
        return self.public(self.load(bid))

    def _run_record(self, bid: str, rid: str, **fields) -> dict:
        holder = {}

        def apply(board):
            rec = next((r for r in board.get("runs") or [] if r["id"] == rid), None)
            if rec is not None:
                for k, v in fields.items():
                    if k == "node":
                        rec["nodes"][v[0]] = v[1]
                    else:
                        rec[k] = v
                holder["rec"] = dict(rec)
        try:
            self._edit(bid, apply)
        except CanvasError:
            return {}
        if holder.get("rec"):
            self.emit("canvas_flow", {"board": bid, "run": holder["rec"]})
        return holder.get("rec") or {}

    def _slot(self, node: dict) -> str:
        """Nhóm tài nguyên của khối khi chạy song song: model trình duyệt (1 profile Chrome — ảnh / chữ / video cùng
        model dùng chung) và dựng video trên máy (nặng CPU) chạy 1 khối 1 lúc; model API chạy song song được."""
        from .workflow import nodes as wfn

        if node["kind"] in ("image", "video"):
            engine = node.get("engine") or ""
        elif node.get("wtype") in POST_TYPES:
            return ""  # đăng bài: phần lớn là chờ bạn duyệt → không giữ chỗ
        else:
            cfg = {**wfn.defaults(node["wtype"]), **(node.get("config") or {})}
            if node["wtype"] in HEAVY_LOCAL:
                return "local"
            engine = str(cfg.get("provider") or cfg.get("model") or "")
            if node["wtype"] == "ai_text" and engine == "claude_api":
                engine = f"api:{cfg.get('model')}"
        if not engine:
            return "local"
        return engine if engine.endswith("_browser") else f"api:{engine}"

    def _flow(self, bid: str, rid: str, order: list) -> dict:
        """Chạy 1 lượt: khối nào đủ đầu vào thì chạy ngay — nhiều nhánh độc lập chạy CÙNG LÚC (tối đa canvas_parallel khối,
        mỗi model trình duyệt / dựng trên máy 1 khối 1 lúc). Khối lỗi / bị bỏ qua → khối phía sau nó bỏ qua, nhánh khác chạy
        tiếp. order là danh sách sống (Storyboard tách cảnh giữa chừng → khối mới nối thêm vào)."""
        import queue

        bad: set = set()  # khối lỗi / bị bỏ qua trong lượt này → khối phía sau cũng bỏ qua
        mode = self._grow.pop(bid, "")
        if mode:
            self._live[bid] = (rid, order, mode)
        self._log_to(bid, rid=rid)  # 📜 nhật ký lượt chạy ghi ra file (xem lại ở Lịch sử, kể cả khi đã tắt app)
        task = self.pool.current
        limit = max(1, min(8, int(self.settings.get("canvas_parallel") or PARALLEL)))
        started, done, running, busy = set(), set(), {}, Counter()  # running: khối → nhóm tài nguyên
        finished: queue.Queue = queue.Queue()
        seq = [0]

        def work(nid: str, kind: str) -> None:
            with self.pool.adopt(task, f"{nid} · " if limit > 1 else ""):
                try:
                    res = self._run_wf(bid, nid) if kind == "wf" else self._run(bid, nid)
                    finished.put((nid, "skipped" if (res or {}).get("skipped") else "done", None))
                except Cancelled as exc:
                    finished.put((nid, "cancelled", exc))
                except Exception as exc:  # khối lỗi: ghi lại, nhánh phía sau bỏ qua, nhánh khác chạy tiếp
                    finished.put((nid, "error", exc))

        def collect(wait: float) -> None:
            try:
                item = finished.get(timeout=wait)
            except queue.Empty:
                return
            while True:
                nid, state, exc = item
                busy[running.pop(nid, "")] -= 1
                if state == "error":
                    self.pool.log(f"{nid} lỗi: {exc}", "error")
                if state in ("error", "skipped", "cancelled"):
                    bad.add(nid)
                done.add(nid)
                if state != "cancelled":
                    self._run_record(bid, rid, node=(nid, state), current=", ".join(running))
                try:
                    item = finished.get_nowait()
                except queue.Empty:
                    return

        try:
            while True:
                self.pool.check_cancel()
                board = self.load(bid)
                nodes = {n["id"]: n for n in board["nodes"]}
                pending = [nid for nid in order if nid not in started]
                if not pending and not running:
                    break
                for nid in pending:
                    if len(running) >= limit:
                        break
                    node = nodes.get(nid)
                    if node is None:  # khối đã bị xoá giữa chừng
                        started.add(nid)
                        done.add(nid)
                        continue
                    ins = [i for i in node.get("inputs") or [] if i in nodes]
                    if any(i in bad for i in ins):
                        started.add(nid)
                        done.add(nid)
                        bad.add(nid)
                        self._set_node(bid, nid, status="idle", pct=0, error="Bỏ qua — node phía trước lỗi / không chạy")
                        self._run_record(bid, rid, node=(nid, "skipped"))
                        continue
                    links = self._web_links(nodes, ins)  # 🖼 Ảnh tải lên lấy ảnh từ khối Tra cứu web → chờ khối đó
                    if any(i in order and i not in done for i in ins + links):
                        continue  # chờ khối phía trước trong lượt này xong
                    empty = [i for i in ins if nodes[i]["kind"] == "upload" and nodes[i].get("inputs")
                             and not nodes[i].get("files")]
                    if empty:  # web không có ảnh sản phẩm mà bạn chưa tải ảnh → không chạy với ảnh trống
                        started.add(nid)
                        done.add(nid)
                        bad.add(nid)
                        self._set_node(bid, nid, status="idle", pct=0,
                                       error=f"Bỏ qua — {', '.join(empty)} chưa có ảnh sản phẩm (tải ảnh lên rồi chạy lại)")
                        self._run_record(bid, rid, node=(nid, "skipped"))
                        continue
                    if node["kind"] == "video" and self._auto_split(bid, board, node, order, rid):
                        break  # ✂ vừa tách thành nhiều video + khối Ghép → đọc lại bảng rồi chạy tiếp
                    slot = self._slot(node)
                    if slot and busy[slot] >= (limit if slot.startswith("api:") else 1):
                        continue  # model / máy đang bận khối khác → khối sau, chạy được thì chạy trước
                    started.add(nid)
                    running[nid] = slot
                    busy[slot] += 1
                    seq[0] += 1
                    self.pool.log(f"[{seq[0]}/{len(order)}] ▶ {self.label(node)} {nid}"
                                  + (f" · song song: {', '.join(running)}" if len(running) > 1 else ""))
                    self._run_record(bid, rid, current=", ".join(running), node=(nid, "running"))
                    threading.Thread(target=work, args=(nid, node["kind"]), daemon=True, name=f"canvas-{bid}-{nid}").start()
                collect(0.5 if running else 0.05)
        except Cancelled:
            for _ in range(600):  # chờ các khối đang chạy dừng hẳn (chúng dùng chung nút Dừng của lượt)
                if not running:
                    break
                collect(0.5)
            for nid in order:
                n = next((x for x in self.load(bid)["nodes"] if x["id"] == nid), None)
                if n and n.get("status") in ACTIVE:
                    self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng", approval={}, stage="")
            self._run_record(bid, rid, status="cancelled", ended=now(), current="")
            self._task_finished(bid, "cancelled")  # 📋 bảng tác vụ → cập nhật trạng thái + chạy tác vụ đang chờ
            raise
        finally:
            self._live.pop(bid, None)
        rec = self._run_record(bid, rid, ended=now(), current="")
        states = list((rec.get("nodes") or {}).values())
        status = ("done" if all(x in ("done", "optional") for x in states) else "error" if "error" in states
                  else "partial")
        rec = self._run_record(bid, rid, status=status)
        self._task_finished(bid, status)  # 📋 bảng tác vụ → cập nhật trạng thái + chạy tác vụ đang chờ
        if self.on_flow_done:  # trợ lý Claude tự điều phối: chấm kết quả lần chạy này (chạy nền, không chặn hàng đợi)
            try:
                self.on_flow_done(bid, rec or {"id": rid, "status": status})
            except Exception as exc:  # noqa: BLE001 — lỗi trợ lý không làm hỏng lần chạy
                self.pool.log(f"Trợ lý tự điều phối lỗi: {exc}", "warn")
        return {"board": bid, "run": rid, "status": status}

    def cancel_flow(self, bid: str) -> int:
        board = self.load(bid)
        tasks = {n.get("task") for n in board["nodes"] if n.get("status") in ACTIVE and n.get("task")}
        return sum(self.pool.cancel(t) for t in tasks)

    # ------------------------------------------------------------------ 📜 nhật ký ra file
    def _log_to(self, bid: str, nid: str = "", rid: str = "") -> None:
        """Nhật ký tác vụ đang chạy ghi thêm ra file: lượt chạy (logs/<rid>.jsonl, chung cho mọi thread của lượt) + khối đang
        chạy (logs/node-<nid>.jsonl, riêng thread chạy khối đó, ghi mới mỗi lần khối chạy). Ngoài thread tác vụ → bỏ qua."""
        try:
            task = self.pool.current
        except RuntimeError:
            return
        folder = self.root / bid / "logs"
        folder.mkdir(exist_ok=True)
        if rid:
            task.data["log_files"] = [str(folder / f"{rid}.jsonl")]
        if nid:
            path = folder / f"node-{nid}.jsonl"
            try:
                path.write_text("", "utf-8")
            except OSError:
                pass
            self.pool.log_extra([str(path)])

    def log_entries(self, bid: str, kind: str, ref: str) -> list:
        """Nhật ký đã lưu: kind = run (1 lượt chạy) | node (lần chạy gần nhất của 1 khối)."""
        if not re.fullmatch(r"[a-z]\d{1,6}", ref or "") or kind not in ("run", "node"):
            raise CanvasError("Nhật ký không hợp lệ")
        path = self.dir(bid) / "logs" / (f"{ref}.jsonl" if kind == "run" else f"node-{ref}.jsonl")
        out = []
        if path.is_file():
            for line in path.read_text("utf-8", errors="replace").splitlines()[-3000:]:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    # ------------------------------------------------------------------ nhập Workflow / quy trình mẫu
    def _copy_upload(self, bid: str, board: dict, path: str, x: float, y: float) -> dict:
        node = self._new_node(board, "upload", x, y, [], "")
        rel = f"nodes/{node['id']}_up{Path(path).suffix.lower()}"
        shutil.copy2(path, self.root / bid / rel)
        node.update(title=Path(path).stem[:60], files=[rel], status="done", pct=100)
        return node

    def import_workflow(self, source: str, ref: str) -> dict:
        """Workflow đã lưu (source=workflow) hoặc quy trình mẫu (source=preset) → Canvas mới, giữ bố cục và dây nối.
        Tạo ảnh / Tạo video → node Ảnh / Video của Canvas; Ảnh đầu vào → node Tải lên (mỗi file 1 node)."""
        import copy

        from .workflow import nodes as wfn
        from .workflow import store as wfs

        if source == "preset":
            if ref not in wfs.PRESETS:
                raise CanvasError("Không có quy trình mẫu này")
            wf = copy.deepcopy(wfs.PRESETS[ref])
        else:
            try:
                wf = wfs.get(ref)
            except (wfs.WorkflowError, OSError) as exc:
                raise CanvasError(str(exc)) from exc
        bid = self.create(wf.get("name") or "Từ Workflow")["id"]
        notes, ids = [], {}
        xs = [n.get("x", 0) for n in wf.get("nodes") or []] or [0]
        ys = [n.get("y", 0) for n in wf.get("nodes") or []] or [0]
        place = lambda n: ((n.get("x", 0) - min(xs)) * 1.5, (n.get("y", 0) - min(ys)) * 1.7)  # noqa: E731

        def build(b):
            for n in wf.get("nodes") or []:
                cfg, kind = wfn.config_of(n), n["type"]
                x, y = place(n)
                if kind == "input_image":
                    files = [p for p in cfg.get("files") or [] if Path(p).is_file()][:6]
                    made = [self._copy_upload(bid, b, f, x, y + k * 380) for k, f in enumerate(files)]
                    if not made:  # chưa có ảnh: node ảnh đầu vào trống, hỏi chọn ảnh khi chạy quy trình
                        node = self._new_node(b, "upload", x, y, [], "")
                        node.update(title=cfg.get("label") or "Ảnh đầu vào", ask=True)
                        made.append(node)
                    for node in made:  # Workflow "Hỏi lại khi chạy" → ❓ hỏi chọn ảnh mỗi lần chạy
                        node["ask"] = bool(cfg.get("ask")) or not node.get("files")
                    ids[n["id"]] = [node["id"] for node in made]
                    continue
                if kind == "gen_image":
                    node = self._new_node(b, "image", x, y, [], str(cfg.get("prompt") or ""))
                    node.update(engine=cfg.get("engine") or node["engine"], aspect=cfg.get("aspect") or node["aspect"],
                                count=int(cfg.get("count") or 1))
                    if cfg.get("pinterest"):
                        notes.append(f"{node['id']}: Canvas chưa tìm ảnh Pinterest — tải ảnh tham khảo lên rồi nối vào")
                    refs = [p for p in cfg.get("refs") or [] if Path(p).is_file()][:4]
                    node["inputs"] += [self._copy_upload(bid, b, f, x - 400, y + k * 380)["id"] for k, f in enumerate(refs)]
                elif kind == "gen_video":
                    node = self._new_node(b, "video", x, y, [], str(cfg.get("prompt") or ""))
                    node.update(engine=cfg.get("engine") or node["engine"], aspect=cfg.get("aspect") or node["aspect"],
                                duration=cfg.get("duration") or node["duration"],
                                resolution=cfg.get("resolution") or node["resolution"])
                    if cfg.get("template"):
                        notes.append(f"{node['id']}: Canvas tạo video bằng prompt tự do — template “{cfg['template']}” "
                                     "không được chuyển, hãy viết lại prompt")
                elif kind in WF_TYPES:
                    node = self._new_node(b, "wf", x, y, [], "", kind)
                    keep = {f["key"] for f in wf_types()[kind]["fields"]}
                    node["config"].update({k: v for k, v in cfg.items() if k in keep})
                else:
                    notes.append(f"Bỏ qua khối không hỗ trợ: {n['type']}")
                    continue
                self._fit_options(node)
                ids[n["id"]] = [node["id"]]
            nodes = {x["id"]: x for x in b["nodes"]}
            for e in wf.get("edges") or []:
                for dst in ids.get(e.get("to"), []):
                    for src in ids.get(e.get("from"), []):
                        target = nodes[dst]
                        if src not in target["inputs"] and out_types(nodes[src]) & in_types(target) \
                                and len(target["inputs"]) < MAX_INPUTS:
                            target["inputs"].append(src)
        board = self._edit(bid, build)
        return {"board": self.public(board), "notes": notes}

    def sources(self) -> dict:
        """Workflow đã lưu + quy trình mẫu để nhập vào Canvas."""
        from .workflow import store as wfs

        return {"workflows": [{"id": w["id"], "name": w.get("name", ""), "nodes": w.get("nodes", 0)}
                              for w in wfs.list_workflows()], "presets": wfs.presets()}

    # ------------------------------------------------------------------ công cụ
    def upscale(self, bid: str, nid: str) -> dict:
        """Phóng to 2× trên máy (ffmpeg lanczos + làm nét nhẹ) → node ảnh mới nối từ node này. Không tốn lượt model."""
        src = self.file_of(bid, nid)
        node = self._node(self.load(bid), nid)
        if node["kind"] == "video":
            raise CanvasError("Chỉ phóng to được ảnh")
        w, h = ffmpeg.video_size(src)
        k = min(2.0, MAX_UPSCALE_SIDE / max(w, h))
        if k <= 1.01:
            raise CanvasError(f"Ảnh đã lớn ({w}×{h}) — không cần phóng thêm")
        nw, nh = round(w * k) // 2 * 2, round(h * k) // 2 * 2
        holder = {}

        def add(board):
            new = self._new_node(board, "upload", node["x"] + 300, node["y"], [], "")
            rel = f"nodes/{new['id']}_x2.png"
            ffmpeg.run(["-i", src, "-vf", f"scale={nw}:{nh}:flags=lanczos,unsharp=5:5:0.5:5:5:0", "-frames:v", "1",
                        self.root / bid / rel])
            new.update(title=f"Phóng to {nw}×{nh}", files=[rel], status="done", pct=100, source=nid, done_at=now())
            holder["node"] = new
        try:
            board = self._edit(bid, add, undo=f"Phóng to {nid}")
        except ffmpeg.FFmpegError as exc:
            raise CanvasError(f"Phóng to lỗi: {exc}") from exc
        return self._result(bid, board, holder["node"]["id"])

    def enhance(self, bid: str, nid: str, model: str = "") -> str:
        """✨ Viết lại prompt bằng model chữ (chạy nền — model trình duyệt mất 1–2 phút). Trả mã tác vụ."""
        node = self._node(self.load(bid), nid)
        if not (node.get("prompt") or "").strip():
            raise CanvasError("Viết vài chữ ý tưởng trước rồi bấm ✨")
        model = model or meta(self.settings)["defaults"]["text"]
        self._set_node(bid, nid, stage="Đang viết lại prompt…")
        return self.pool.submit("Canvas · viết lại prompt", self._enhance, bid, nid, model,
                                meta={"board": bid, "node": nid})

    def _enhance(self, bid: str, nid: str, model: str) -> dict:
        from .studio import ask_model

        try:
            node = self._node(self.load(bid), nid)
            video = node["kind"] == "video"
            system = ENHANCE_SYSTEM.format(what="video từ ảnh" if video else "ảnh",
                                           motion=", chuyển động theo mốc giây, máy quay" if video else "")
            text = ask_model(self.settings, {"model": model, "timeout": 240,
                                             "text_profile": model_prefs.get(self.settings).get("model_text_profile", "")},
                             f"Prompt người dùng:\n{node['prompt']}", what="viết lại prompt", log=self.pool.log,
                             check_cancel=self.pool.check_cancel, system=system)
            text = " ".join(str(text or "").strip().strip('"').split())[:4000]
            if not text:
                raise CanvasError("Model không trả prompt")
        except Exception:
            self._set_node(bid, nid, stage="")
            raise

        def apply(board):  # ↶ hoàn tác được (trả lại prompt bạn viết)
            node = next((n for n in board["nodes"] if n["id"] == nid), None)
            if node is not None:
                node.update(prompt=text, stage="")
        try:
            self._edit(bid, apply, undo=f"Viết lại prompt {nid}")
        except CanvasError:
            return {"board": bid, "node": nid, "prompt": text}
        self._push(bid, nid)
        return {"board": bid, "node": nid, "prompt": text}
