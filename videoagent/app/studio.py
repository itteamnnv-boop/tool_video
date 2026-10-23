"""Studio: ý tưởng → storyboard (sửa được) → tạo từng cảnh (ảnh khung đầu → video AI) → ghép video dài có giọng đọc,
phụ đề, nhạc nền.

- Storyboard: model văn bản (chat trình duyệt / Gemini API / Claude / OpenAI — cùng danh sách với Tạo content) viết
  mô tả nhân vật + phong cách chung và 5–10 cảnh (lời đọc tiếng Việt, prompt ảnh, prompt chuyển động, số giây).
- Cảnh: ảnh khung đầu qua hàng đợi Tạo hình ảnh (kèm ảnh tham chiếu nhân vật/sản phẩm để nhất quán) → clip qua hàng đợi
  Tạo video (template ẩn studio-canh, model video chọn trong dự án). Các cảnh chạy song song theo giới hạn từng trang.
- Ghép: đọc giọng từng cảnh (edge-tts), chỉnh clip đúng độ dài lời đọc (cắt / giữ khung cuối), rồi dùng lại compose()
  của Tạo video (phụ đề karaoke, hiệu ứng, nhạc nền, cân âm lượng). Video cuối là 1 mục trong Thư viện video.
- Dự án lưu ở <thư mục video>/_studio/<id>/project.json (+ refs/, scenes/NN/frame.png, clip.mp4).
"""
import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import ffmpeg, model_prefs
from .browser_profiles import task_context
from .image_library import IMAGES_DIR
from .library import save_job
from .llm.base import LLMError, extract_json
from .pipeline import ref_video as rvm
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.video_engines import ENGINES as VIDEO_ENGINES
from .pipeline import SCENE_TAIL, VOICE_LEAD, Cancelled, scene_dir_name
from .pipeline import live_chat, live_sim, post_ai, transitions
from .pipeline.assets import extract_audio
from .pipeline.composer import compose
from .pipeline.tasks import TaskPool
from .pipeline.tts import RATES, ROLES, VOICES, role_voice, synthesize, synthesize_lines
from .util import read_json, slugify, unique_dir, write_json

log = logging.getLogger(__name__)
STUDIO_DIR = "_studio"
# Studio Muse AI: dự án riêng (thư mục _studio_muse, sự kiện mstudio_*), mọi bước chỉ dùng Muse (muse.ai)
MUSE_DIR = "_studio_muse"
MUSE_LOCK = {"model": "muse_browser", "image_engine": "muse_browser", "video_engine": "muse_browser",
             "post_model": "muse_browser"}
SCENE_TEMPLATE = "studio-canh"
WIDTH, HEIGHT, FPS = 1080, 1920, 30  # mặc định: video dọc 9:16 (Reels / TikTok)
# tỉ lệ khung hình → (nhãn, kích thước video ghép, mô tả tiếng Anh cho prompt ảnh, mô tả tiếng Việt cho storyboard)
ASPECTS = {"9:16": ("Dọc 9:16 — TikTok, Reels, Shorts", (1080, 1920), "Vertical 9:16", "dọc 9:16"),
           "16:9": ("Ngang 16:9 — YouTube, Facebook", (1920, 1080), "Horizontal 16:9 widescreen", "ngang 16:9"),
           "1:1": ("Vuông 1:1 — bài đăng Facebook / Instagram", (1080, 1080), "Square 1:1", "vuông 1:1")}
# chất lượng clip = độ phân giải yêu cầu model video tạo (model không hỗ trợ → tự dùng mức gần nhất)
QUALITIES = {"480p": "480p — nhanh nhất, nhẹ", "720p": "720p — cân bằng (mặc định)",
             "1080p": "1080p — nét nhất, tạo clip lâu hơn"}
MAX_CLONE_REFS = 10


def frame_size(options: dict) -> tuple[int, int]:
    return ASPECTS.get(options.get("aspect") or "9:16", ASPECTS["9:16"])[1]


# ---------------------------------------------------------------- hồ sơ nhân vật + lời thoại nhiều giọng
MAX_CHARACTERS, MAX_LINES = 8, 12


def _flat(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def clean_characters(raw) -> list[dict]:
    """Hồ sơ nhân vật cố định: tên, ngoại hình (EN), trang phục cố định (EN), vai giọng lồng tiếng."""
    out, seen = [], set()
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        name = _flat(c.get("name") or c.get("ten"), 40)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        voice = c.get("voice") if c.get("voice") is not None else c.get("giong")
        out.append({"name": name, "look": _flat(c.get("look") or c.get("ngoai_hinh"), 500),
                    "outfit": _flat(c.get("outfit") or c.get("trang_phuc"), 400),
                    "voice": voice if voice in ROLES else ""})
    return out[:MAX_CHARACTERS]


def merge_cast(characters: list[dict], fixed: list[dict]) -> list[dict]:
    """Nhân vật cố định (màn Nhân vật & Layout): ngoại hình lấy nguyên mô tả đã duyệt, trang phục theo ảnh tham chiếu."""
    out = [dict(c) for c in characters]
    for f in fixed:
        desc = _flat(f.get("description") or f.get("summary"), 500)
        hit = next((c for c in out if c["name"].lower() == f["name"].lower()), None)
        if hit is None:
            out.append({"name": _flat(f["name"], 40), "look": desc, "outfit": "", "voice": ""})
        else:
            hit.update(look=desc or hit["look"], outfit="")
    return out[:MAX_CHARACTERS]


def clean_lines(raw, names: list[str]) -> list[dict]:
    """Câu thoại của cảnh: who = tên nhân vật đang nói ("" = người dẫn chuyện), text, tone (cảm xúc / giọng điệu)."""
    by_lower = {n.lower(): n for n in names}
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = _flat(item.get("text") or item.get("cau"), 400).replace('"', "'")
        if not text:
            continue
        who = _flat(item.get("who") if item.get("who") is not None else item.get("ai"), 40)
        out.append({"who": by_lower.get(who.lower(), ""), "text": text,
                    "tone": _flat(item.get("tone") or item.get("cam_xuc"), 80)})
    return out[:MAX_LINES]


def lines_text(lines: list[dict]) -> str:
    return " ".join(line["text"] for line in lines or [])[:1200]


def voice_map(characters: list[dict], options: dict) -> dict:
    """Tên nhân vật → (giọng, tốc độ, cao độ). Hai nhân vật trùng giọng → lệch cao độ ±6 Hz để nghe khác nhau."""
    used, out = {}, {}
    for c in characters or []:
        voice, rate, pitch = role_voice(c.get("voice") or "", options["voice"], options["rate"])
        n = used.get((voice, pitch), 0)
        used[(voice, pitch)] = n + 1
        if n:
            pitch = f"{int(pitch.rstrip('Hz')) + (6 if n % 2 else -6) * ((n + 1) // 2):+d}Hz"
        out[c["name"]] = (voice, rate, pitch)
    return out


def character_sheet(chars: list[dict], title: str = "", lock_outfit: bool = True) -> str:
    title = title or ("Characters in this scene — the SAME people in every scene (same face, age, hairstyle"
                      + (" and outfit)" if lock_outfit else "; clothes may change per scene)"))
    label = "Outfit (never changes)" if lock_outfit else "Usual outfit (use it unless the scene action says other clothes)"
    return "\n".join([title + ":"] + [f"- {c['name']}: {c['look'].rstrip('. ')}." + (f" {label}: {c['outfit']}"
                                                                        if c.get("outfit") else "") for c in chars])


FACE_LOCK = ("IDENTITY LOCK (highest priority): every person is EXACTLY the same person as in the first frame and the "
             "character reference image — identical face (face shape, eyes, nose, mouth, eyebrows, jawline), skin tone, "
             "apparent age, hairstyle and body type from the first to the last frame. Do NOT regenerate, redraw, "
             "beautify, age or swap any face; no face morphing when talking, smiling or turning the head; keep the "
             "first frame as the exact starting image.")


def identity_lock(scene: dict, options: dict, bible: dict | None = None) -> str:
    """Câu khoá nhân vật đặt ĐẦU prompt clip (model video, nhất là Muse, hay vẽ lại mặt): khuôn mặt luôn giữ nguyên;
    trang phục giữ như bảng nhân vật (lock_outfit) hoặc giữ đúng như khung đầu của cảnh này."""
    bible = bible or {}
    roster = bible.get("characters") or []
    names = scene.get("cast") if isinstance(scene.get("cast"), list) else [c["name"] for c in roster]
    people = [c for c in roster if c["name"] in names]
    fixed = options.get("cast_characters") or options.get("cast_combo")
    if not (people or fixed):
        return ""
    lock_outfit = options.get("lock_outfit", True)
    who = "; ".join(f"{c['name']}: {_clip_text(' '.join((c.get('look') or '').split()), 260)}" for c in people)
    if not who and bible.get("nhan_vat"):
        who = _clip_text(" ".join(bible["nhan_vat"].split()), 600)
    wear = "; ".join(f"{c['name']} wears {_clip_text(' '.join(c['outfit'].split()), 160)}" for c in people if c.get("outfit"))
    outfit = ("OUTFIT LOCK: same clothes, colours and accessories as the character sheet for the whole clip"
              + (f" ({wear})." if wear else ".")) if lock_outfit else (
        "Clothes: keep exactly the clothes shown in the first frame for the whole clip (they may differ from the "
        "reference image) — only the clothes may differ, never the face.")
    return " ".join(x for x in (FACE_LOCK, f"Characters: {who}." if who else "", outfit) if x)[:1500]


MIN_SCENES, MAX_SCENES = 5, 10
LENGTHS = (10, 15, 20, 30, 45, 60, 75, 90)
SHORT_SCENES = {10: 1, 15: 1, 20: 2}  # video ngắn: 1 cảnh (một cú máy liền, hợp Grok 10–15s) / 2 cảnh


def split_narration(text: str, count: int) -> list[str]:
    """Chia văn bản thành count đoạn lời đọc theo câu, độ dài gần đều (không cắt giữa câu; ít câu hơn clip → clip sau trống)."""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?…])\s+|\n+", text or "") if x.strip()]
    n = len(sentences)
    if n <= count:  # ít câu: mỗi clip 1 câu, clip sau trống
        return [(sentences[k] if k < n else "")[:1200] for k in range(count)]
    total = sum(len(x) for x in sentences)
    parts, start, acc = [], 0, 0
    for k in range(count):
        end = start
        if k == count - 1:
            end = n
        else:  # lấy câu tới khi vượt mốc độ dài của clip này, chừa mỗi clip sau ít nhất 1 câu
            while end < n - (count - 1 - k) and (end == start or acc + len(sentences[end]) / 2 <= total * (k + 1) / count):
                acc += len(sentences[end])
                end += 1
        parts.append(" ".join(sentences[start:end])[:1200])
        start = end
    return parts


def no_storyboard(options: dict) -> bool:
    """Tắt bước viết storyboard (chỉ với nguồn ý tưởng + AI video; video phân tích / whiteboard luôn cần storyboard)."""
    return (options.get("storyboard") is False and options.get("source_mode") != "video"
            and options.get("scene_style") != "whiteboard")


def framing(scene: dict, options: dict) -> str:
    """Câu tiếng Anh về cỡ cảnh + góc máy của cảnh (cảnh ghi đè dự án; auto / mix → để storyboard tự quyết)."""
    shot = scene.get("shot") if scene.get("shot") in SHOT_SIZES else options.get("shot_size")
    angle = scene.get("angle") if scene.get("angle") in CAMERA_ANGLES else options.get("camera_angle")
    parts = [x for x in ((SHOT_SIZES.get(shot) or ("", ""))[1], (CAMERA_ANGLES.get(angle) or ("", ""))[1]) if x]
    return ("CAMERA FRAMING (must follow): " + "; ".join(parts) + ".") if parts else ""


def scene_count(length: int) -> int:
    """Số cảnh storyboard theo độ dài video: ngắn (≤20s) 1–2 cảnh, còn lại ~8 giây / cảnh (5–10 cảnh)."""
    if length in SHORT_SCENES:
        return SHORT_SCENES[length]
    return max(MIN_SCENES, min(MAX_SCENES, round(length / 8)))
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SCENE_FIELDS = ("title", "narration", "speaker", "image_prompt", "motion_prompt", "seconds", "shot", "angle")
# cỡ cảnh / góc máy: mã → (nhãn tiếng Việt, câu tiếng Anh chèn vào prompt). Dự án chọn chung, từng cảnh ghi đè được;
# "auto" = model storyboard tự chọn theo từng cảnh; "mix" = xen kẽ toàn / trung / cận theo nhịp truyện
SHOT_SIZES = {
    "auto": ("Tự động — AI chọn theo từng cảnh", ""),
    "mix": ("Đa dạng — xen kẽ toàn / trung / cận", ""),
    "wide": ("Toàn cảnh — thấy cả bối cảnh", "wide shot: the whole setting is visible, people small in the frame"),
    "full": ("Toàn thân — thấy từ đầu tới chân", "full shot: the person is visible from head to toe"),
    "medium": ("Trung cảnh — từ thắt lưng trở lên", "medium shot: the person framed from the waist up"),
    "medium_close": ("Cận trung — từ ngực trở lên", "medium close-up: the person framed from the chest up"),
    "close": ("Cận mặt", "close-up: the face fills most of the frame"),
    "extreme": ("Đặc tả — chi tiết (tay, sản phẩm)", "extreme close-up on a detail (hands, product, eyes)"),
}
CAMERA_ANGLES = {
    "auto": ("Tự động — AI chọn theo từng cảnh", ""),
    "eye": ("Ngang tầm mắt", "eye-level camera"),
    "front": ("Nhìn thẳng ống kính — nói với người xem (livestream)",
              "frontal camera, the person faces the lens and looks straight into it, talking to the viewer"),
    "three_quarter": ("Góc nghiêng 3/4", "three-quarter angle, the person turned slightly to the side"),
    "low": ("Góc thấp — nhìn lên (uy lực)", "low-angle camera looking up at the subject"),
    "high": ("Góc cao — nhìn xuống", "high-angle camera looking down at the subject"),
    "ots": ("Qua vai", "over-the-shoulder shot"),
    "top": ("Từ trên xuống (flat lay)", "top-down overhead shot"),
    "pov": ("Góc nhìn nhân vật (POV)", "first-person point-of-view shot"),
}
# Ghép: giữ trọn chuyển động của clip — tua nhanh/chậm nhẹ để khớp lời đọc thay vì cắt cụt hoặc đứng hình lâu
MAX_SPEED, MIN_SPEED = 1.25, 0.8  # tua nhanh / chậm tối đa (mắt khó nhận ra)
BREATH = 2.0  # cảnh được dài hơn lời đọc tối đa ngần này giây (để clip chạy hết, có nhịp nghỉ)
SILENT_MAX = 8.0  # cảnh không lời: giữ clip tối đa ngần này giây
BATCH_MAX = 20  # tạo hàng loạt: tối đa số ý tưởng mỗi lần
RUNNING_SCENE = ("frame_running", "clip_running")
STORYBOARD_TIMEOUT = 480  # giây chờ model chat trình duyệt viết xong storyboard
# Ràng buộc prompt (người dùng chọn ở Cài đặt dự án): những thứ không được có trong ảnh khung đầu và clip
BANS = {"text": ("Không chữ trên hình", "no text"), "subtitles": ("Không phụ đề", "no subtitles"),
        "logos": ("Không logo", "no logos"), "watermark": ("Không watermark", "no watermark")}
REF_PROMPT = "use it as a visual reference for subject, style and composition"  # vai trò ảnh tham chiếu (mặc định)
# Logo thương hiệu (chỉ dùng khi KHÔNG tick "Không logo"): gửi kèm model ảnh + tuỳ chọn đóng logo thật lên góc video
LOGO_REF = {"role": "brand logo", "prompt": "reproduce this exact logo (same shape, colours and lettering, never distorted) "
                                            "only where a brand logo naturally appears in the scene"}
LOGO_CORNERS = {"none": "Không đóng lên video", "tr": "Góc trên phải", "tl": "Góc trên trái",
                "br": "Góc dưới phải", "bl": "Góc dưới trái"}
LOGO_WIDTH, LOGO_MARGIN = 200, 48  # px trên khung 1080×1920
MAX_CAST = 3  # số nhân vật cố định tối đa mỗi dự án
DIRECT_MAX = 8  # số ảnh ⭐ tối đa mỗi mục dùng thẳng làm khung đầu (chia lần lượt cho các cảnh)
DIRECT_STORY_IMAGES = 4  # số ảnh ⭐ gửi kèm model viết storyboard
DIRECT_SKIP = {"sheet", "expressions"}  # ảnh ⭐ nhiều ô / nhiều góc — không dùng làm khung đầu
# Cách tạo khung đầu khi đã chọn nhân vật / layout: keep = sửa ảnh layout ⭐ (chỉ thay sản phẩm + chữ trên giao diện) ·
# direct = dùng thẳng ảnh ⭐ · ai = model ảnh tạo khung mới mỗi cảnh. "" = tự chọn (có layout → keep, chỉ nhân vật → direct)
FRAME_MODES = ("", "keep", "direct", "ai")
OVERLAY_COMMENTS, OVERLAY_TEXT = 6, 80  # số bình luận / độ dài mỗi dòng chữ trên giao diện layout
CHAT_ELEMENTS = {"live", "chat", "comments"}  # thành phần giao diện layout có khung bình luận
KEEP_NOTE = """GIỮ NGUYÊN LAYOUT — khung đầu mọi cảnh là ẢNH LAYOUT CỐ ĐỊNH{attached}; app chỉ THAY SẢN PHẨM{product} và CHỮ
trên giao diện, giữ nguyên người, trang phục, tư thế, bối cảnh và mọi chi tiết giao diện. Vì vậy:
- Không đổi địa điểm, không thêm người; "prompt_anh" chỉ tả ngắn khung hình layout.
- "prompt_chuyen_dong" là trọng tâm: MỘT hành động của người trong layout (nói với khán giả, giơ / chỉ vào sản phẩm,
  mỉm cười, gật đầu…) + chuyển động máy rất nhẹ — lớp giao diện đứng yên.
{ui_rule}"""
KEEP_UI_RULE = """- Mỗi cảnh thêm "noi_dung_layout": {{"binh_luan": [3–{n} bình luận NGẮN của người xem, hợp nội dung cảnh], "chu": "chữ
  ngắn trên màn (tên sản phẩm / ưu đãi / lời kêu gọi), có thể để trống"}}. Bình luận: ưu tiên dùng / phỏng theo bình luận
  thật của khách dưới đây; được thêm câu hỏi, lời chào trung tính (giá, cách dùng, ship, xin tư vấn…). KHÔNG bịa lời
  chứng thực kết quả (năng suất, khỏi bệnh, tăng X%…), KHÔNG bịa số lượt thích / người xem / đã bán.{real}"""
ANALYSIS_FIELDS = ("muc_tieu", "khach_hang", "san_pham", "thong_diep", "cam_xuc", "hook", "goc_tiep_can", "luu_y",
                   "can_bo_sung")
ANALYSIS_LABELS = {"muc_tieu": "Mục tiêu", "khach_hang": "Người xem mục tiêu", "san_pham": "Sản phẩm / điểm nổi bật",
                   "thong_diep": "Thông điệp chính", "cam_xuc": "Cảm xúc / giọng điệu", "hook": "Gợi ý mở đầu (hook)",
                   "goc_tiep_can": "Hướng kể chuyện", "luu_y": "Lưu ý", "can_bo_sung": "Nên bổ sung"}
ANALYZE_PROMPT = """Bạn là chuyên gia chiến lược nội dung video ngắn bán hàng. Hãy PHÂN TÍCH ý tưởng video dưới đây.
<y_tuong>
{idea}
</y_tuong>
Bối cảnh dự án:
{context}
Trả về MỘT object JSON (tiếng Việt, không markdown):
{{"muc_tieu": "video nhằm đạt gì", "khach_hang": "người xem mục tiêu (nghề, nhu cầu, nỗi lo)",
 "san_pham": "sản phẩm / dịch vụ và điểm nổi bật (theo ảnh nếu có; không bịa thông số)", "thong_diep": "1 thông điệp chính",
 "cam_xuc": "cảm xúc / giọng điệu nên dùng", "hook": ["3 cách mở đầu cụ thể cho 3 giây đầu"],
 "goc_tiep_can": ["2–3 hướng kể chuyện phù hợp"], "luu_y": ["điều cần tránh (hứa hẹn quá mức, so sánh sai…)"],
 "can_bo_sung": ["thông tin còn thiếu người dùng nên bổ sung (giá, ưu đãi, cách dùng…)"]}}"""
REWRITE_PROMPT = """Bạn là biên kịch video ngắn bán hàng. Viết lại ý tưởng thành BẢN Ý TƯỞNG HOÀN CHỈNH để viết storyboard,
bám theo phân tích (người dùng đã duyệt / sửa).
<y_tuong_goc>
{idea}
</y_tuong_goc>
<phan_tich>
{analysis}
</phan_tich>
Bối cảnh dự án:
{context}
Yêu cầu: 1 đoạn 120–220 từ tiếng Việt, cụ thể và hình dung được: hook mở đầu, diễn biến mở – thân – kết, nhân vật làm gì
(dùng đúng nhân vật cố định nếu có), sản phẩm xuất hiện thế nào, thông điệp, lời kêu gọi cuối. Không bịa thông số, giá,
cam kết hiệu quả mà người dùng chưa cung cấp.
Chỉ trả về MỘT object JSON: {{"y_tuong": "…", "ten": "tên dự án ngắn"}}"""


def settings_text(o: dict, p: dict) -> str:
    """Cài đặt dự án (wizard bước ②–④) dạng ràng buộc cho model phân tích / viết lại ý tưởng / viết storyboard."""
    engine = VIDEO_ENGINES.get(o.get("video_engine"), {})
    durs = video_engine_durations(o["video_engine"]) if o.get("video_engine") in VIDEO_ENGINES else [10]
    voice = next((v["name"] for v in VOICES if v["id"] == o.get("voice")), o.get("voice") or "")
    fm = frame_mode(o)
    lines = [f"- Khung hình {ASPECTS[o['aspect']][3]}, dài ~{o['length']} giây ≈ {scene_count(o['length'])} cảnh"
             + (f"; model video {engine.get('name', '')}: mỗi clip {'/'.join(map(str, durs))} giây (tối đa {max(durs)}s) — "
                "lời thoại mỗi cảnh phải nói hết trong thời lượng clip" if o.get("scene_style") != "whiteboard" else ""),
             f"- Kiểu dựng cảnh: {SCENE_STYLES.get(o.get('scene_style') or 'video', '')}"]
    if o.get("cast_layout") or o.get("cast_combo") or o.get("cast_characters"):
        lines.append("- Khung đầu: " + {"keep": "GIỮ NGUYÊN layout cố định, chỉ thay sản phẩm + chữ — mọi cảnh cùng bối cảnh",
                                        "direct": "dùng thẳng ảnh ⭐ có sẵn của nhân vật / dàn cảnh — không vẽ cảnh mới",
                                        "ai": "AI vẽ khung mới mỗi cảnh, giữ đúng nhân vật / bối cảnh cố định"}[fm])
    if o.get("dub", True) or o.get("scene_style") == "whiteboard":
        lines.append(f"- Âm thanh: lồng tiếng AI giọng {voice} (tốc độ {o.get('rate') or '+0%'})")
    else:
        lines.append("- Âm thanh: nhân vật nói GIỌNG GỐC ngay trong clip (model video tạo tiếng) — câu thoại ngắn, tự nhiên")
    extras = [x for x in ("phụ đề" if o.get("subtitles") else "", "nhạc nền" if o.get("bgm") else "",
                          "hậu kỳ AI (tô từ khoá, hook)" if o.get("post_ai") else "") if x]
    if extras:
        lines.append("- Hậu kỳ: " + ", ".join(extras))
    if (o.get("live") or {}).get("on"):
        lines.append("- Dạng video: LIVESTREAM bán hàng — người bán nói trực tiếp với người xem, có bình luận người xem")
    if o.get("style"):
        lines.append(f"- Phong cách hình ảnh: {o['style']}")
    shot, angle = o.get("shot_size") or "auto", o.get("camera_angle") or "auto"
    if shot != "auto" or angle != "auto":
        lines.append("- Góc máy: " + "; ".join(x for x in (
            f"cỡ cảnh {SHOT_SIZES[shot][0]}" if shot != "auto" else "",
            f"góc {CAMERA_ANGLES[angle][0]}" if angle != "auto" else "") if x)
            + (" — đổi cỡ cảnh theo nhịp truyện, cảnh liền nhau không cùng cỡ" if shot == "mix" else ""))
    if p.get("logo") and o.get("logo_overlay", "none") != "none":
        lines.append("- Có logo thương hiệu đóng ở góc video")
    if o.get("lock_outfit", True) and o.get("cast_characters"):
        lines.append("- Nhân vật giữ nguyên trang phục ở mọi cảnh")
    ban = negative_line(o)
    if ban:
        lines.append(f"- Ràng buộc hình: {ban}")
    return "CÀI ĐẶT DỰ ÁN (người dùng đã chọn — phải bám theo):\n" + "\n".join(lines)


MASTER_PROMPT = """Create ONE photorealistic {aspect} key visual for a short sales video.
People: {people}
Product: the product in the product reference image(s) — {product_note}
Setting: {setting}
Composition: the people naturally present / hold the product toward the camera, mid shot, clean background around them.
Keep every person exactly as their reference image (face, skin tone, apparent age, hair, body type, outfit) — no beautify,
de-age or ageing — and keep the product exactly as its reference (packaging, shape, colours, label text, logo).
Natural light, sharp focus, realistic proportions. No extra people. No added text or watermark."""


def master_path(p: dict) -> Path | None:
    """Ảnh tổng hợp (⓪) của dự án nếu đã có file."""
    path = Path(str((p.get("master") or {}).get("path") or ""))
    return path if (p.get("master") or {}).get("path") and path.is_file() else None


def needs_master(o: dict, p: dict) -> bool:
    """Cần bước ⓪ khi có ít nhất 2 trong 3: layout / bộ kết hợp · nhân vật · ảnh sản phẩm (và bật master_on)."""
    if not o.get("master_on", True) or o.get("scene_style") == "whiteboard":
        return False
    kinds = [bool(o.get("cast_layout") or o.get("cast_combo")), bool(o.get("cast_characters")),
             bool([r for r in p.get("refs") or [] if Path(r).is_file()])]
    return sum(kinds) >= 2


def _try_json(text):
    try:
        return extract_json(text)
    except ValueError:
        return None


def format_analysis(data: dict) -> str:
    """Phân tích ý tưởng → chữ dễ đọc, sửa được (bước 2 dùng nguyên văn phần này)."""
    out = []
    for k in ANALYSIS_FIELDS:
        v = data.get(k)
        if isinstance(v, list):
            items = [str(x).strip() for x in v if str(x).strip()]
            if items:
                out.append(f"{ANALYSIS_LABELS[k]}:\n" + "\n".join(f"- {x}" for x in items))
        elif str(v or "").strip():
            out.append(f"{ANALYSIS_LABELS[k]}: {str(v).strip()}")
    return "\n".join(out)[:6000]


KEEP_PROMPT = """Edit the FIRST attached image (a fixed layout). Keep EVERYTHING identical except the parts listed below:
the person (face, hair, outfit, pose and framing), background, composition, camera angle, lighting and colours, and every
on-screen interface element in exactly the same position, size and style (badges, avatars, icons, buttons, hearts,
comment panel, input bar).
Only change:
{changes}
Do not add any other person, text or logo. Do not change anything else. Photorealistic, sharp."""
DIRECT_NOTE = """KHUNG ĐẦU CÓ SẴN — mỗi cảnh BẮT ĐẦU từ một ảnh có sẵn của nhân vật / dàn cảnh cố định{attached}; app KHÔNG tạo
ảnh mới, model video chỉ làm chuyển động từ ảnh đó. Vì vậy:
- Giữ đúng bối cảnh, trang phục, tư thế mở đầu như trong ảnh; không viết cảnh ở địa điểm khác hay có người lạ.
- "prompt_chuyen_dong" là trọng tâm: MỘT hành động chính bắt đầu từ khung hình đó (nói, cầm / giới thiệu sản phẩm, quay
  người, bước tới…) + chuyển động máy nhẹ (dolly in, pan, handheld…), vừa trong số giây của cảnh.
- "prompt_anh" chỉ tả ngắn khung hình có sẵn (để tham khảo); đa dạng các cảnh bằng hành động, biểu cảm, chuyển động máy."""
SCENE_STYLES = {"video": "AI video — ảnh khung đầu → model video làm chuyển động",
                "whiteboard": "Whiteboard — vẽ tay bảng trắng theo lời dẫn (srt-whiteboard-animation, dựng trên máy)"}
POST_STYLES = {"basic": "Cơ bản — phụ đề tô nổi từ khoá (nhanh)",
               "hyperframes": "HyperFrames — đồ hoạ động: phụ đề chạy chữ, hook, thẻ kết (dựng trên máy, ~3 phút / phút video)"}


def storyboard_complete(text: str) -> bool:
    """Câu trả lời chat đã là storyboard JSON đầy đủ (đọc được, có cảnh, cảnh cuối đủ prompt)."""
    data = extract_json(text)
    scenes = data.get("canh") if isinstance(data, dict) else None
    return bool(scenes) and isinstance(scenes[-1], dict) and bool(scenes[-1].get("prompt_anh"))
SYSTEM = ("Bạn là đạo diễn kiêm biên kịch video ngắn trên mạng xã hội. Bạn viết storyboard rõ ràng, cảnh nối mạch, "
          "nhân vật và bối cảnh nhất quán giữa các cảnh, lời đọc tiếng Việt tự nhiên.")


class StudioError(RuntimeError):
    pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- lưu trữ
class Store:
    def __init__(self, settings, folder: str = STUDIO_DIR) -> None:
        self.settings = settings
        self.folder = folder
        self.options_hook = None  # Studio thường: model dự án luôn theo Cài đặt → Model AI (dùng chung)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        path = Path(self.settings.output_dir) / self.folder
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{6,60}", pid or ""):
            raise StudioError("Mã dự án không hợp lệ")
        path = self.root / pid
        if not (path / "project.json").is_file():
            raise StudioError("Không tìm thấy dự án")
        return path

    def load(self, pid: str) -> dict:
        project = read_json(self.dir(pid) / "project.json")
        if self.options_hook and isinstance(project.get("options"), dict):
            project["options"] = self.options_hook(project["options"])
        return project

    def save(self, project: dict) -> dict:
        project["updated_at"] = now()
        with self._lock:
            write_json(self.root / project["id"] / "project.json", project)
        return project

    def update(self, pid: str, fn) -> dict:
        with self._lock:
            path = self.dir(pid) / "project.json"
            project = read_json(path)
            fn(project)
            project["updated_at"] = now()
            write_json(path, project)
        return project

    def list(self) -> list[dict]:
        items = []
        for folder in self.root.iterdir():
            try:
                items.append(read_json(folder / "project.json"))
            except (OSError, ValueError):
                continue
        return sorted(items, key=lambda p: p.get("updated_at") or "", reverse=True)


# ---------------------------------------------------------------- tiện ích
def video_engine_durations(engine: str) -> list[int]:
    return [int(d.rstrip("s")) for d in VIDEO_ENGINES[engine]["durations"]]


def fit_seconds(engine: str, seconds) -> int:
    """Số giây cảnh → thời lượng model video hỗ trợ (gần nhất)."""
    allowed = video_engine_durations(engine)
    try:
        want = float(seconds)
    except (TypeError, ValueError):
        want = allowed[-1]
    return min(allowed, key=lambda d: abs(d - want))


SPEAK_RATE = 3.8  # từ (âm tiết) tiếng Việt / giây — 5 giây ≈ 16 từ, 10 giây ≈ 35 từ, 15 giây ≈ 54 từ (không nói vội)
LINE_GAP, SPEECH_PAD = 0.35, 0.8  # nghỉ giữa các câu · khoảng đầu + cuối cảnh


def speech_seconds(scene: dict) -> float:
    """Ước lượng số giây cần để nói hết lời thoại / lời dẫn của cảnh (0 = cảnh không lời)."""
    texts = [ln["text"] for ln in scene.get("lines") or [] if ln.get("text")] or (
        [scene["narration"]] if (scene.get("narration") or "").strip() else [])
    words = sum(len(t.split()) for t in texts)
    return round(words / SPEAK_RATE + LINE_GAP * max(0, len(texts) - 1) + SPEECH_PAD, 1) if words else 0.0


def seconds_for_speech(engine: str, seconds, scene: dict) -> int:
    """Số giây clip: không ngắn hơn thời gian nói hết lời của cảnh (lấy mức model hỗ trợ ≥ cần; vượt mức dài nhất
    thì dùng mức dài nhất — cảnh đó cần rút gọn lời / tách cảnh)."""
    allowed = video_engine_durations(engine)
    current = fit_seconds(engine, seconds)
    need = speech_seconds(scene)
    if need <= current:
        return current
    return next((d for d in sorted(allowed) if d >= need), max(allowed))


def speech_overflow(engine: str, scene: dict) -> float:
    """Số giây lời thoại dư so với clip dài nhất model hỗ trợ (>0 → sẽ bị ngắt câu)."""
    return round(max(0.0, speech_seconds(scene) - max(video_engine_durations(engine))), 1)


def clean_options(raw: dict, settings) -> dict:
    image_engine = raw.get("image_engine") or (settings.get("last_image_form") or {}).get("engine") or "openai_api"
    if image_engine not in IMAGE_ENGINES:
        image_engine = "openai_api"
    video_engine = raw.get("video_engine") if raw.get("video_engine") in VIDEO_ENGINES else "grok_browser"
    voice = raw.get("voice") if raw.get("voice") in {v["id"] for v in VOICES} else "vi-VN-HoaiMyNeural"
    try:
        length = int(raw.get("length") or 60)
    except (TypeError, ValueError):
        length = 60
    return {"model": str(raw.get("model") or "chatgpt_browser"), "text_profile": str(raw.get("text_profile") or ""),
            "length": max(LENGTHS[0], min(LENGTHS[-1], length)), "style": str(raw.get("style") or "").strip()[:300],
            "image_engine": image_engine, "image_profile": str(raw.get("image_profile") or ""),
            "video_engine": video_engine, "video_profile": str(raw.get("video_profile") or ""),
            "voice": voice, "rate": raw.get("rate") if raw.get("rate") in RATES else "+0%",
            "subtitles": bool(raw.get("subtitles", True)), "bgm": bool(raw.get("bgm", True)),
            # chế độ chạy: auto = các bước chạy liên tục tới video · review = dừng sau mỗi bước để duyệt / sửa
            "flow": raw.get("flow") if raw.get("flow") in ("auto", "review") else ("auto" if raw.get("auto") else "review"),
            "auto": raw.get("flow") == "auto" if raw.get("flow") in ("auto", "review") else bool(raw.get("auto")),
            # nguồn ý tưởng: phân tích ý tưởng + AI viết lại ý tưởng trước khi viết storyboard
            "idea_steps": bool(raw.get("idea_steps", True)),
            # viết storyboard (model viết từng cảnh để duyệt) · tắt = app chia ý tưởng thành các clip nối tiếp, làm video luôn
            "storyboard": bool(raw.get("storyboard", True)),
            # video tham khảo (link / file) đã phân tích: dùng khi viết storyboard hay không + cách dùng
            "ref_video_use": bool(raw.get("ref_video_use")),
            # nguồn kịch bản: idea = ý tưởng người dùng viết · video = chuyển thể toàn bộ vật liệu của video phân tích
            "source_mode": "video" if raw.get("source_mode") == "video" else "idea",
            "ref_video_mode": raw.get("ref_video_mode") if raw.get("ref_video_mode") in ("inspire", "close") else "inspire",
            # sau khi viết storyboard: model viết lại prompt ảnh / chuyển động từng cảnh chi tiết hơn (thêm 1 lượt hỏi)
            # tỉ lệ khung hình (ảnh khung đầu, clip, video ghép) + chất lượng clip model video tạo
            "aspect": raw.get("aspect") if raw.get("aspect") in ASPECTS else "9:16",
            "quality": raw.get("quality") if raw.get("quality") in QUALITIES else "720p",
            # lồng tiếng AI (TTS); tắt → nhân vật nói lời dẫn ngay trong clip, ghép dùng tiếng gốc của clip
            "dub": bool(raw.get("dub", True)),
            # nhân vật: khuôn mặt LUÔN khoá; trang phục khoá (giống nhau mọi cảnh) hoặc đổi theo mô tả từng cảnh
            "lock_outfit": bool(raw.get("lock_outfit", True)),
            # cỡ cảnh / góc máy chung của dự án (từng cảnh ghi đè được ở storyboard)
            "shot_size": raw.get("shot_size") if raw.get("shot_size") in SHOT_SIZES else "auto",
            "camera_angle": raw.get("camera_angle") if raw.get("camera_angle") in CAMERA_ANGLES else "auto",
            # ràng buộc prompt: cấm chữ / phụ đề / logo / watermark + câu cấm thêm; câu mô tả ảnh tham chiếu
            "bans": [k for k in BANS if k in (raw["bans"] if isinstance(raw.get("bans"), list) else BANS)],
            "negative_extra": " ".join(str(raw.get("negative_extra") or "").split())[:300],
            "ref_note": bool(raw.get("ref_note", True)),
            "logo_overlay": raw.get("logo_overlay") if raw.get("logo_overlay") in LOGO_CORNERS else "none",
            # hậu kỳ AI sau khi có đủ clip, trước khi ghép: model chat (mặc định Claude trình duyệt) chọn từ khoá tô nổi
            # trên phụ đề + hiệu ứng âm thanh gắn vào từ + hook + mức nhạc nền (app/pipeline/post_ai.py)
            "post_ai": bool(raw.get("post_ai")),
            "post_model": str(raw.get("post_model") or "claude_browser"),
            "post_profile": str(raw.get("post_profile") or ""),
            "post_subs": bool(raw.get("post_subs", True)),
            "post_audio": bool(raw.get("post_audio", True)),
            # kiểu hậu kỳ: basic = phụ đề ASS nổi bật; hyperframes = đồ hoạ động HTML/GSAP dựng bằng HyperFrames trên máy
            "post_style": raw.get("post_style") if raw.get("post_style") in POST_STYLES else "basic",
            # kiểu dựng cảnh: video = ảnh khung đầu → model video; whiteboard = line-art + tay vẽ theo lời dẫn
            "scene_style": raw.get("scene_style") if raw.get("scene_style") in SCENE_STYLES else "video",
            "wb_quality": raw.get("wb_quality") if raw.get("wb_quality") in ("fast", "hd") else "fast",
            "wb_hand": bool(raw.get("wb_hand", True)),
            # nhân vật / layout cố định từ màn Nhân vật & Layout (không chọn = không dùng)
            "cast_characters": [str(c) for c in raw.get("cast_characters") or [] if c][:MAX_CAST]
            if isinstance(raw.get("cast_characters"), list) else [],
            "cast_layout": str(raw.get("cast_layout") or ""),
            "cast_combo": "",  # đã bỏ "bộ kết hợp" (ảnh tổng hợp ⓪ thay thế) — dự án cũ vẫn giữ nhân vật + layout của bộ
            # đã chọn nhân vật / bộ kết hợp → dùng thẳng ảnh ⭐ làm khung đầu mỗi cảnh (không tạo ảnh nhân vật mới)
            "cast_direct": bool(raw.get("cast_direct", True)),
            "frame_mode": raw.get("frame_mode") if raw.get("frame_mode") in FRAME_MODES else "",
            # giữ layout có khung bình luận: app tự vẽ bình luận chạy như livestream (chữ chuẩn), model không vẽ chữ
            "chat_overlay": bool(raw.get("chat_overlay", True)),
            "transition_on": bool(raw.get("transition_on", True)),  # công tắc chuyển cảnh khi ghép
            # ⓪ ghép layout + nhân vật + sản phẩm thành 1 ảnh tổng hợp trước — các bước sau dùng ảnh này
            "master_on": bool(raw.get("master_on", True)),
            # 📱 mô phỏng livestream TikTok: app vẽ toàn bộ giao diện live lên video khi ghép
            "live": live_sim.clean_config(raw.get("live")),
            "ref_prompt": " ".join(str(raw.get("ref_prompt") or "").split())[:300] or REF_PROMPT,
            "show_browser": bool(raw.get("show_browser")),  # hiện cửa sổ Chrome khi model chạy qua trình duyệt
            # chuyển cảnh + âm chuyển cảnh khi ghép (mặc định: hoà trộn 0,5 giây + whoosh)
            **transitions.clean(raw.get("transition") or "fade", raw.get("transition_duration") or 0.5,
                                raw.get("transition_sound") or "whoosh",
                                raw.get("transition_volume") if raw.get("transition_volume") is not None else 0.6)}


def meta(settings) -> dict:
    """Danh sách lựa chọn cho giao diện Studio."""
    from .content_writer import models

    return {"text_models": models(settings), "lengths": list(LENGTHS),
            "image_engines": {k: {"name": v["name"], "browser": bool(v.get("browser")), "note": v.get("note", "")}
                              for k, v in IMAGE_ENGINES.items()},
            "video_engines": {k: {"name": v["name"], "durations": v["durations"], "note": v.get("note", "")}
                              for k, v in VIDEO_ENGINES.items()},
            "bans": [{"value": k, "label": v[0]} for k, v in BANS.items()], "ref_prompt_default": REF_PROMPT,
            "logo_corners": [{"value": k, "label": v} for k, v in LOGO_CORNERS.items()],
            "post_styles": [{"value": k, "label": v} for k, v in POST_STYLES.items()],
            "scene_styles": [{"value": k, "label": v} for k, v in SCENE_STYLES.items()],
            "aspects": [{"value": k, "label": v[0]} for k, v in ASPECTS.items()],
            "ref_video_modes": [{"value": k, "label": v} for k, v in rvm.MODES.items()],
            "qualities": [{"value": k, "label": v} for k, v in QUALITIES.items()],
            "shot_sizes": [{"value": k, "label": v[0]} for k, v in SHOT_SIZES.items()],
            "camera_angles": [{"value": k, "label": v[0]} for k, v in CAMERA_ANGLES.items()],
            "voices": VOICES, "rates": RATES, "speakers": [{"value": k, "label": v[0]} for k, v in ROLES.items()],
            "scenes": [MIN_SCENES, MAX_SCENES], "length_scenes": {str(n): scene_count(n) for n in LENGTHS},
            **transitions.options(), "shared_models": model_prefs.get(settings),
            "default_image_engine": (settings.get("last_image_form") or {}).get("engine") or "openai_api"}


def project_logo(project: dict) -> Path | None:
    """Logo của dự án nếu có file và người dùng cho phép logo (bỏ tick "Không logo")."""
    logo = Path(project.get("logo") or "")
    allowed = "logos" not in project.get("options", {}).get("bans", list(BANS))
    return logo if allowed and project.get("logo") and logo.is_file() else None


def copy_logo(pdir: Path, src: str) -> str:
    """Chép logo vào thư mục dự án (logo.<đuôi>, thay logo cũ). src rỗng → xoá logo. Trả về đường dẫn mới / ""."""
    for old in pdir.glob("logo.*"):
        old.unlink()
    if not src:
        return ""
    path = Path(str(src))
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
        raise StudioError("Logo phải là ảnh PNG / JPG / WEBP")
    dest = pdir / f"logo{path.suffix.lower()}"
    shutil.copy2(path, dest)
    return str(dest)


def stamp_logo(video: Path, logo: Path, corner: str) -> None:
    """Đóng logo thật (giữ nền trong suốt của PNG) lên một góc video, giữ nguyên âm thanh."""
    m = LOGO_MARGIN
    x = f"main_w-overlay_w-{m}" if corner in ("tr", "br") else str(m)
    y = f"main_h-overlay_h-{m + 220}" if corner in ("br", "bl") else str(m + 40)  # chừa chỗ phụ đề / giao diện app
    out = video.with_name(video.stem + "_logo.mp4")
    ffmpeg.run(["-i", video, "-i", logo, "-filter_complex",
                f"[1:v]scale={LOGO_WIDTH}:-1,format=rgba[lg];[0:v][lg]overlay={x}:{y}:format=auto,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-c:a", "copy", "-movflags", "+faststart", out])
    out.replace(video)


def negative_line(options: dict) -> str:
    """Câu cấm cuối prompt theo lựa chọn của dự án, vd. "No text, no subtitles, no logos, no watermark."
    Dự án cũ (chưa có "bans") → cấm đủ 4 như trước. Bỏ hết + không có câu thêm → không có câu cấm."""
    bans = options.get("bans", list(BANS))
    parts = [BANS[k][1] for k in BANS if k in bans]
    line = (", ".join(parts).capitalize() + ".") if parts else ""
    extra = (options.get("negative_extra") or "").strip()
    if extra:
        extra = extra[0].upper() + extra[1:] + ("" if extra[-1] in ".!?" else ".")
    return " ".join(x for x in (line, extra) if x)


# Nhân vật cố định: bỏ cụm tả quần áo trong mô tả cảnh (storyboard cũ hay viết "in a red ao dai", "wearing a suit")
# để model ảnh lấy trang phục từ ảnh tham chiếu
GARMENT = (r"(?:dress|gown|shirt|t-shirt|polo|blouse|top|skirt|jeans|pants|trousers|shorts|suit|jacket|coat|hoodie|"
           r"sweater|uniform|outfit|clothes|clothing|ao dai|áo dài|apron|overalls|vest|hat|cap|scarf)s?")
OUTFIT_RE = re.compile(r",?\s*\b(?:wearing|dressed in|dressed as|clad in|in)\s+(?:a|an|her|his|their|the)?\s*"
                       r"(?:[\w-]+\s+){0,4}?" + GARMENT + r"\b", re.I)


def strip_outfit(text: str) -> str:
    return " ".join(OUTFIT_RE.sub("", text or "").split()).strip(" ,")


def frame_mode(options: dict) -> str:
    """Cách tạo khung đầu thực tế của dự án: keep (giữ layout, thay sản phẩm + chữ) | direct (ảnh ⭐) | ai (tạo mới)."""
    has_layout = bool(options.get("cast_layout") or options.get("cast_combo"))
    if not (has_layout or options.get("cast_characters")) or options.get("scene_style") == "whiteboard":
        return "ai"
    mode = options.get("frame_mode") or ""
    if not mode:  # tự chọn (dự án cũ tắt "dùng thẳng ảnh ⭐" → ai)
        mode = "ai" if options.get("cast_direct") is False else "keep" if has_layout else "direct"
    return "direct" if mode == "keep" and not has_layout else mode


def clean_overlay(raw) -> dict:
    """Nội dung giao diện layout của 1 cảnh: {"comments": [...], "caption": "..."} (rỗng → {})."""
    if not isinstance(raw, dict):
        return {}
    comments = raw.get("comments", raw.get("binh_luan"))
    if isinstance(comments, str):
        comments = comments.splitlines()
    comments = [" ".join(str(c).replace('"', "'").split())[:OVERLAY_TEXT] for c in comments or [] if str(c).strip()]
    caption = " ".join(str(raw.get("caption", raw.get("chu")) or "").replace('"', "'").split())[:OVERLAY_TEXT]
    out = {"comments": comments[:OVERLAY_COMMENTS], "caption": caption}
    return out if out["comments"] or out["caption"] else {}


def clip_refs(cast: dict, product: str = "") -> dict:
    """Ảnh gửi kèm khung đầu khi tạo clip (template studio-canh): ref1 = nhân vật cố định, ref2 = sản phẩm (ưu tiên ảnh
    sản phẩm của dự án `product`, rồi của bộ kết hợp) hoặc bối cảnh / dàn cảnh. Không có gì → {} (chỉ gửi khung đầu)."""
    refs = list((cast or {}).get("refs") or [])
    if product and Path(product).is_file():  # ảnh sản phẩm người dùng tải lên ở dự án — giữ đúng bao bì trong clip
        refs.insert(0, {"path": product, "role": "product photo"})

    def pick(test, skip=""):
        return next((r["path"] for r in refs if test(r.get("role") or "") and r["path"] != skip
                     and Path(r["path"]).is_file()), "")

    person = pick(lambda r: r.startswith("character reference")) or pick(lambda r: r.startswith("scene reference"))
    other = (pick(lambda r: r == "product photo", person) or pick(lambda r: r.startswith("layout"), person)
             or pick(lambda r: r.startswith("scene reference"), person))
    return {k: v for k, v in (("ref1", person), ("ref2", other)) if v}


def _clip_speech(scene: dict, options: dict, bible: dict | None = None) -> dict:
    """Phần ②④⑤ của prompt clip: {MoTa} = chuyển động / máy quay, {LoiThoai} = nhân vật nói đúng "Lời đọc" của cảnh.
    Lồng tiếng AI: nhân vật vẫn mấp máy môi + cử chỉ theo đúng câu (tiếng clip bị thay bằng giọng đọc khi ghép);
    giọng gốc: model video phải nói to rõ đúng nguyên văn câu đó, không nhạc nền. Cảnh không lời → bỏ dòng thoại."""
    motion = " ".join((scene.get("motion_prompt") or scene.get("image_prompt") or "").split())[:700]
    roster = {c["name"]: c for c in (bible or {}).get("characters") or []}
    if options.get("cast_layout") or options.get("cast_combo"):
        motion = ("Same location as in the first frame. " + motion)[:700]
    if frame_mode(options) == "keep":  # giữ layout: lớp giao diện (huy hiệu, icon, khung bình luận) đứng yên, chữ không nhoè
        motion = ("Keep every on-screen interface element and its text from the first frame fixed, sharp and unchanged; "
                  "only the person moves. " + motion)[:800]
    frame_rule = framing(scene, options) if frame_mode(options) == "ai" else ""
    if frame_rule:
        motion = (frame_rule + " Keep this framing for the whole shot. " + motion)[:900]
    lock = {"KhoaNhanVat": identity_lock(scene, options, bible)}
    narration = _clip_text(" ".join((scene.get("narration") or "").split()).replace('"', "'"), 900)
    secs = int(float(scene.get("seconds") or 0))
    timing = (f" Pace the speech so EVERY line is spoken completely within {max(2, secs - 1)} seconds — "
              f"never cut off mid-sentence, finish the last word, then a brief silent beat." if secs else "")
    dub, ban = options.get("dub", True), negative_line(options)
    lines = [ln for ln in scene.get("lines") or [] if ln.get("text")]
    if lines:  # lời thoại nhiều nhân vật: ai nói, cảm xúc, chất giọng
        def label(ln: dict) -> str:
            if not ln.get("who"):
                return "Voice-over narrator (off-screen" + (f", {ln['tone']}" if ln.get("tone") else "") + ")"
            desc = ROLES.get((roster.get(ln["who"]) or {}).get("voice") or "", ROLES[""])[4]
            extra = ", ".join(x for x in (ln.get("tone"), desc) if x)
            return ln["who"] + (f" ({extra})" if extra else "")
        said = "; ".join(f'{label(ln)}: "{_clip_text(ln["text"], 300)}"' for ln in lines)
        if dub:
            line = ("each speaking character lip-syncs their own line with matching facial expression, emotion and "
                    "gestures (voice-over lines are not spoken on screen): " + said)
        else:
            line = ("each character speaks their own line out loud in Vietnamese, word for word, each with a distinct voice "
                    "matching the description, clearly audible and lip-synced, no background music; voice-over narrator "
                    "lines are heard off-screen: " + said)
        return {"MoTa": motion, "LoiThoai": _clip_text(line, 1400 - len(timing)) + timing, "CamKy": ban, **lock}
    if not narration:
        return {"MoTa": motion, "LoiThoai": "", "CamKy": ban, **lock}
    role = ROLES.get(scene.get("speaker") or "", ROLES[""])[4]
    who = f" with {role}" if role else ""
    if dub:
        line = (f"the on-screen character says exactly this line{who}, with natural lip movements, facial expression "
                f"and gestures matching the words: \"{narration}\"")
    else:
        line = (f"the on-screen character speaks exactly this line out loud{who}, word for word in the original "
                f"language (Vietnamese pronunciation), clearly audible and lip-synced, no background music: \"{narration}\"")
    return {"MoTa": motion, "LoiThoai": line + timing, "CamKy": ban, **lock}


CLIP_NEGATIVE = ("No extra people, no face change, no outfit change, no change to the product packaging or label, "
                 "no deformed hands, no extra fingers, no morphing, no cuts.")


def clip_variables(scene: dict, options: dict, bible: dict | None = None, refs: dict | None = None,
                   product: bool = False, ui: bool = False) -> dict:
    """Biến template cảnh theo công thức 7 phần, đúng thứ tự trong prompt (phần khoá càng ở đầu càng giữ chắc):
    ① thông số → ② khoá nhân vật → ③ khoá bối cảnh / sản phẩm → ④ hành động (mốc giây) → ⑤ lời thoại → ⑥ âm thanh → ⑦ cấm.
    refs = ảnh gửi kèm khung đầu (clip_refs); product = có ảnh sản phẩm cần giữ bao bì; ui = layout có giao diện + chữ."""
    out = _clip_speech(scene, options, bible)
    refs = refs or {}
    secs = int(float(scene.get("seconds") or 0)) or 10
    images, n = ["image 1 = the opening frame"], 2
    for key, what in (("ref1", "character reference"),
                      ("ref2", "product reference" if product else "product / setting reference")):
        if refs.get(key):
            images.append(f"image {n} = {what}")
            n += 1
    aspect = ASPECTS.get(options.get("aspect") or "9:16", ASPECTS["9:16"])[2]
    out["ThongSo"] = (f"{aspect} video, {secs} seconds, {options.get('quality') or '720p'}, image-to-video "
                      f"({'; '.join(images)}): animate the opening frame exactly — do not create a new image. "
                      "ONE continuous shot from start to end: no cuts, no scene changes, no transitions.")
    keep_ui = ui and frame_mode(options) == "keep"
    out["KhoaBoiCanh"] = " ".join(x for x in (
        "SETTING LOCK: keep the location, background, props and lighting exactly as in the opening frame for the whole clip.",
        ("PRODUCT LOCK: the product stays 100% identical to the product reference — same shape, cap / lid, label, colours "
         "and logo; never redraw, invent or warp the label text; keep the product at a medium distance (no extreme "
         "close-up on small label text).") if product else "",
        "Keep every on-screen interface element and its text exactly as in the opening frame; do not add any new text."
        if keep_ui else "") if x)
    out["AmThanh"] = ("No background music, no sound effects, no extra voices — the voice-over and music are added in editing."
                      if options.get("dub", True) else
                      "Only the spoken line(s) and light natural ambience — no background music, no singing, no other voices."
                      if out.get("LoiThoai") else "Light natural ambience only — no music, no speech.")
    # giữ giao diện livestream: cấm "chữ / phụ đề" sẽ xoá mất chữ của layout → bỏ 2 mục đó, đã dặn giữ nguyên chữ ở ③
    bans = options.get("bans", list(BANS))
    ban = negative_line({**options, "bans": [b for b in bans if b not in ("text", "subtitles")]} if keep_ui else options)
    out["CamKy"] = " ".join(x for x in (ban, CLIP_NEGATIVE) if x)
    return out


def _clip_text(text: str, limit: int) -> str:
    """Rút gọn tới ranh giới câu / từ (không cắt giữa chữ — model video sẽ đọc câu cụt)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("; "))
    return cut[:end + 1] if end > limit * 0.6 else cut[:cut.rfind(" ")].rstrip(",;: ") + "…"


def ask_model(settings, options: dict, prompt: str, *, complete=None, what: str = "viết storyboard", log=None,
              check_cancel=None, system: str = "", images: list | None = None) -> str:
    """Hỏi model chữ theo options {model, text_profile, show_browser}: API (api:<model>) hoặc chat trình duyệt.
    Dùng chung cho Studio (storyboard, hậu kỳ) và màn Nhân vật & Layout (viết mô tả)."""
    system = system or SYSTEM
    log = log or (lambda *a, **k: None)
    model = options["model"]
    if model.startswith("api:"):
        from .campaign.ai import RoleAI

        return RoleAI("studio", log, check_cancel).complete(model[4:], system, prompt, max_tokens=8000)[0]
    from .llm import make_provider
    from .llm.browser_chat import BrowserChatProvider

    provider = make_provider(model, settings, show_browser=bool(options.get("show_browser")))
    if provider is None:
        raise StudioError("Model viết chữ không hợp lệ")
    with task_context(options.get("text_profile", ""), check_cancel=check_cancel, log=log):
        if isinstance(provider, BrowserChatProvider):
            # trả lời dài (storyboard 8–10 cảnh JSON) → chờ lâu hơn, và chỉ nhận câu trả lời khi JSON đã đọc được đủ
            # (ChatGPT hay dừng suy nghĩ giữa chừng → trước đây app lấy bản viết dở, JSON cụt)
            provider.timeout_s = int(options.get("timeout") or STORYBOARD_TIMEOUT)
            provider.start_url = str(options.get("chat_url") or "")  # tiếp tục đúng cuộc trò chuyện cũ (nếu có)
            log(f"Đang chờ {provider.site.name} {what} (tối đa {provider.timeout_s // 60} phút)"
                + (" — đang hiện cửa sổ trình duyệt" if options.get("show_browser") else ""))
            if images:  # ảnh đính kèm (vd. lưới khung hình video mẫu cho Muse) — chỉ khi bên gọi truyền vào
                return provider.generate(system + "\n\n" + prompt, images=images, complete=complete)
            text = provider.generate(system + "\n\n" + prompt, complete=complete)
            options["_last_url"] = provider.last_url  # bên gọi lưu lại để lần sau nhắn tiếp đúng cuộc trò chuyện
            return text
        return provider.generate(system + "\n\n" + prompt, images=images or None)


def _settled(scene: dict) -> str:
    """Trạng thái cảnh khi KHÔNG còn chạy: bỏ 'đang tạo…' (dừng / lỗi / app tắt giữa chừng)."""
    status = scene.get("status") or ""
    if status not in RUNNING_SCENE:
        return status
    return "done" if scene.get("clip") else "frame" if scene.get("frame") else ""


def fit_clip(clip_dur: float, voice_dur: float) -> tuple[float, float]:
    """Độ dài cảnh + tốc độ phát clip để GIỮ TRỌN chuyển động:
    - có lời đọc: cảnh dài theo lời đọc (+ tối đa BREATH giây cho clip chạy hết); clip dài hơn → tua nhanh tối đa
      MAX_SPEED (phần dư còn lại mới bị cắt); clip ngắn hơn → tua chậm tối đa MIN_SPEED (thiếu nữa mới giữ khung cuối);
    - không lời: giữ clip tối đa SILENT_MAX giây."""
    if clip_dur <= 0:
        return max(voice_dur + VOICE_LEAD + SCENE_TAIL, 1.0), 1.0
    if not voice_dur:
        return round(min(clip_dur, SILENT_MAX), 3), 1.0
    target = voice_dur + VOICE_LEAD + SCENE_TAIL
    if clip_dur >= target:
        duration = min(max(target, clip_dur / MAX_SPEED), target + BREATH)
        return round(duration, 3), round(min(clip_dur / duration, MAX_SPEED), 4)
    return round(target, 3), round(max(clip_dur / target, MIN_SPEED), 4)


# ---------------------------------------------------------------- runner
class StudioRunner:
    """Chạy việc của Studio trong hàng đợi riêng (sự kiện studio_*); ảnh/video giao cho hàng đợi Tạo ảnh / Tạo video."""

    def __init__(self, settings, license_mgr, emit, images, videos, variant: str = "studio") -> None:
        self.settings = settings
        self.license = license_mgr
        self.images, self.videos = images, videos
        self.cast = None  # CastRunner (màn Nhân vật & Layout) — api.py gắn vào
        self._emit = emit
        self.muse = variant == "muse"  # Studio Muse AI: khoá mọi model về Muse
        self.prefix = "mstudio_" if self.muse else "studio_"
        self.store = Store(settings, MUSE_DIR if self.muse else STUDIO_DIR)
        if not self.muse:
            self.store.options_hook = self._shared_models
        self.pool = TaskPool(self.prefix, emit, lambda: settings.get("max_parallel_studio") or 2)
        self._active: dict[str, str] = {}
        self._start_lock = threading.Lock()

    def _clean(self, raw: dict) -> dict:
        """Chuẩn hoá tuỳ chọn dự án; Studio Muse AI: viết storyboard, ảnh, clip, hậu kỳ luôn dùng Muse."""
        if self.muse:
            return {**clean_options(raw, self.settings), **MUSE_LOCK}
        return clean_options(model_prefs.apply_studio(raw, self.settings), self.settings)

    def _shared_models(self, options: dict) -> dict:
        """Dự án đã lưu (kể cả dự án cũ) đọc lên luôn dùng model ở Cài đặt → Model AI."""
        out = model_prefs.apply_studio(options, self.settings)
        if out["image_engine"] not in IMAGE_ENGINES:
            out["image_engine"] = options.get("image_engine") or "openai_api"
        if out["video_engine"] not in VIDEO_ENGINES:
            out["video_engine"] = options.get("video_engine") or "grok_browser"
        return out

    # ------------------------------------------------------------ công khai
    def public(self, project: dict) -> dict:
        base = Path(self.settings.output_dir)
        pdir = base / self.store.folder / project["id"]

        def url(rel: str) -> str:
            path = pdir / rel if rel else None
            return f"/media/{self.store.folder}/{project['id']}/{rel}?v={int(path.stat().st_mtime)}" if path and path.is_file() else ""

        final = project.get("final") or {}
        final_path = base / final["job_id"] / "final.mp4" if final.get("job_id") else None
        running = project["id"] in self.running_ids()
        status = project.get("status")
        if not running and status == "running":  # app tắt / tác vụ chết giữa chừng → không hiện "Đang chạy" mãi
            status = "interrupted"
        scenes = [{**s, "status": _settled(s) if not running else s.get("status", "")} for s in project.get("scenes") or []]
        return {**project, "running": running, "status": status,
                "scenes": [{**s, "frame_url": url(s.get("frame", "")), "clip_url": url(s.get("clip", ""))}
                           for s in scenes],
                "refs_view": [url(f"refs/{Path(r).name}") for r in project.get("refs") or []],
                "logo_url": url(Path(project["logo"]).name) if project.get("logo") else "",
                "ref_video_url": url("ref_video.jpg") if project.get("ref_video") else "",
                "master_url": url(Path(project["master"]["path"]).name) if (project.get("master") or {}).get("path") else "",
                "final_url": (f"/media/{final['job_id']}/final.mp4?v={int(final_path.stat().st_mtime)}"
                              if final_path and final_path.is_file() else "")}

    def running_ids(self) -> list:
        live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
        return [pid for pid, task in self._active.items() if task in live]

    def _push(self, project: dict) -> None:
        self._emit(f"{self.prefix}update", self.public(project))

    def create(self, form: dict) -> dict:
        idea = str(form.get("idea") or "").strip()
        options = self._clean(form.get("options") or {})
        if options["source_mode"] == "video":  # kịch bản từ video phân tích — không cần ý tưởng
            rv = rvm.clean(form.get("ref_video"))
            if not rv:
                raise StudioError("Nguồn kịch bản là video: dán link / chọn file rồi bấm 🔍 Phân tích trước")
            options["ref_video_use"] = True
            idea = idea or f"Chuyển thể video: {rv.get('title') or 'video phân tích'}"
        elif len(idea) < 10:
            raise StudioError("Hãy mô tả ý tưởng video (ít nhất 1 câu)")
        name = str(form.get("name") or "").strip()[:80] or idea[:60]
        pid = f"{slugify(name, 40)}-{uuid.uuid4().hex[:6]}"
        pdir = self.store.root / pid
        (pdir / "refs").mkdir(parents=True)
        refs = []
        for src in form.get("refs") or []:
            path = Path(str(src))
            if path.is_file() and path.suffix.lower() in IMAGE_EXT:
                dest = pdir / "refs" / f"{len(refs) + 1:02d}{path.suffix.lower()}"
                shutil.copy2(path, dest)
                refs.append(str(dest))
        self._pin_live_avatar(pdir, options)  # avatar kênh livestream → chép vào dự án
        project = {"id": pid, "name": name, "idea": idea, "created_at": now(), "options": options, "refs": refs,
                   "logo": copy_logo(pdir, form["logo"]) if form.get("logo") else "",
                   "ref_video": rvm.copy_sheet(rvm.clean(form.get("ref_video")), pdir),
                   "bible": {}, "scenes": [], "status": "draft", "error": "", "final": {}}
        self.store.save(project)
        return {"project": self.public(project), "task": self.start(pid, self._first_step(options, project))}

    @staticmethod
    def _after_master(o: dict) -> str:
        """Bước sau ảnh tổng hợp: nguồn ý tưởng + bật phân tích → Phân tích ý tưởng; còn lại → storyboard."""
        return "analyze" if o.get("source_mode") != "video" and o.get("idea_steps", True) else "storyboard"

    @classmethod
    def _first_step(cls, o: dict, p: dict | None = None) -> str:
        """Bước đầu: ⓪ ảnh tổng hợp (khi có ≥ 2 trong layout / nhân vật / sản phẩm) → ① phân tích → … → storyboard."""
        return "compose" if p is not None and needs_master(o, p) else cls._after_master(o)

    def create_batch(self, form: dict) -> dict:
        """Tạo hàng loạt: mỗi dòng ý tưởng = 1 dự án, cùng tuỳ chọn + ảnh tham chiếu, tự làm video luôn (auto).
        Các dự án vào hàng đợi Studio (chạy song song theo 'max_parallel_studio'), ảnh / clip theo giới hạn từng trang."""
        ideas = [line.strip(" -•\t") for line in str(form.get("idea") or "").splitlines()]
        ideas = [i for i in ideas if len(i) >= 10]
        if not ideas:
            raise StudioError("Hãy nhập ít nhất 1 ý tưởng (mỗi dòng 1 ý tưởng, tối thiểu 1 câu)")
        if len(ideas) > BATCH_MAX:
            raise StudioError(f"Tối đa {BATCH_MAX} ý tưởng mỗi lần (đang có {len(ideas)})")
        prefix = str(form.get("name") or "").strip()[:60]
        options = {**(form.get("options") or {}), "auto": True, "flow": "auto"}  # hàng loạt luôn chạy liên tục
        created = []
        for k, idea in enumerate(ideas, 1):
            name = f"{prefix} #{k}" if prefix else idea[:60]
            created.append(self.create({**form, "idea": idea, "name": name, "options": options}))
        return {"projects": [c["project"] for c in created], "tasks": [c["task"] for c in created]}

    def resume_all(self) -> dict:
        """Chạy tiếp mọi dự án chưa có video: chưa có storyboard → viết storyboard rồi làm; có rồi → làm cảnh còn thiếu + ghép."""
        started, skipped = [], []
        running = set(self.running_ids())
        for p in self.store.list():
            if p["id"] in running or (p.get("final") or {}).get("job_id"):
                continue
            try:
                if not p.get("scenes"):  # viết storyboard xong thì tự làm luôn
                    self.store.update(p["id"], lambda x: x["options"].update(auto=True))
                self.start(p["id"], "make" if p.get("scenes") else "storyboard")
                started.append(p["id"])
            except StudioError as exc:
                skipped.append(f"{p['name']}: {exc}")
        return {"started": started, "skipped": skipped}

    def save(self, pid: str, data: dict) -> dict:
        """Sửa storyboard / tuỳ chọn. Đổi prompt ảnh → bỏ ảnh + clip cũ; đổi prompt chuyển động / số giây → bỏ clip."""
        if pid in self.running_ids():
            raise StudioError("Dự án đang chạy — chờ xong hoặc bấm Dừng rồi sửa")

        def apply(p):
            if "name" in data:
                p["name"] = str(data["name"]).strip()[:80] or p["name"]
            if "idea" in data:
                p["idea"] = str(data["idea"]).strip()[:4000] or p["idea"]
            if isinstance(data.get("brief"), dict):  # bước 1–2: phân tích / ý tưởng viết lại do người dùng sửa
                b = p.setdefault("brief", {})
                for k in ("analysis_text", "idea_ai"):
                    if k in data["brief"]:
                        b[k] = str(data["brief"][k] or "").strip()[:6000]
            if isinstance(data.get("options"), dict):
                p["options"] = self._clean({**p["options"], **data["options"]})
                self._pin_live_avatar(self.store.dir(pid), p["options"])
            if "ref_video" in data:  # phân tích video tham khảo mới / sửa tóm tắt / bỏ video
                p["ref_video"] = rvm.copy_sheet(rvm.clean(data["ref_video"]), self.store.dir(pid))
            if isinstance(data.get("bible"), dict):
                old_chars = (p.get("bible") or {}).get("characters") or []
                p["bible"] = {k: str(v)[:1500] for k, v in data["bible"].items() if k in ("nhan_vat", "phong_cach")}
                chars = clean_characters(data["bible"]["characters"]) if "characters" in data["bible"] else old_chars
                if chars:
                    p["bible"]["characters"] = chars
            if isinstance(data.get("scenes"), list):
                old = {s["index"]: s for s in p.get("scenes") or []}
                scenes = []
                for i, raw in enumerate(data["scenes"], 1):
                    prev = old.get(raw.get("index")) or {}
                    sc = {"index": i, **{k: prev.get(k) or "" for k in ("frame", "clip", "status", "error", "frame_src")}}
                    overlay = clean_overlay(raw.get("overlay", prev.get("overlay")))  # chữ trên giao diện layout
                    if overlay:
                        sc["overlay"] = overlay
                    for k in SCENE_FIELDS:
                        sc[k] = str(raw.get(k, prev.get(k, "")) or "").strip()[:2000]
                    names = [c["name"] for c in (p.get("bible") or {}).get("characters") or []]
                    sc["lines"] = clean_lines(raw.get("lines", prev.get("lines")), names)
                    if sc["lines"]:  # lời đọc của cảnh = các câu thoại nối lại (phụ đề, whiteboard, hậu kỳ dùng chung)
                        sc["narration"] = lines_text(sc["lines"])
                    cast_raw = raw.get("cast", prev.get("cast"))
                    if isinstance(cast_raw, list):
                        sc["cast"] = [n for n in names if n in cast_raw]
                    sc["seconds"] = fit_seconds(p["options"]["video_engine"], sc["seconds"] or 10)
                    if sc["speaker"] not in ROLES:
                        sc["speaker"] = ""
                    # giọng gốc: lời dẫn / vai giọng nằm trong clip → đổi thì phải làm lại clip
                    # whiteboard: mốc tay vẽ lấy theo giọng đọc → đổi lời / vai giọng cũng phải dựng lại clip
                    speech = (not p["options"].get("dub", True) or p["options"].get("scene_style") == "whiteboard") and (any(
                        sc[k] != (prev.get(k) or "") for k in ("narration", "speaker")) or sc["lines"] != (prev.get("lines") or []))
                    # giữ layout: chữ trên giao diện nằm trong ảnh khung đầu → đổi chữ thì làm lại ảnh
                    # (app tự vẽ bình luận khi ghép → chữ không nằm trong ảnh, đổi chữ chỉ cần ghép lại)
                    keep_text = (frame_mode(p["options"]) == "keep" and not p["options"].get("chat_overlay", True)
                                 and overlay != clean_overlay(prev.get("overlay")))
                    if sc["image_prompt"] != prev.get("image_prompt") or keep_text:
                        sc.update(frame="", clip="", status="")
                    elif speech or sc["motion_prompt"] != prev.get("motion_prompt") or sc["seconds"] != prev.get("seconds"):
                        sc.update(clip="", status="frame" if sc.get("frame") else "")
                    if not sc.get("clip"):  # chưa có clip → số giây đủ nói hết lời (tránh ngắt câu cuối cảnh)
                        sc["seconds"] = seconds_for_speech(p["options"]["video_engine"], sc["seconds"], sc)
                    scenes.append(sc)
                p["scenes"] = scenes[:MAX_SCENES + 5]
                p["final"] = {}  # storyboard đổi → video cũ không còn khớp
        project = self.store.update(pid, apply)
        self._push(project)
        return self.public(project)

    def clone(self, pid: str, mode: str = "storyboard", name: str = "", refs: list | None = None) -> dict:
        """Nhân bản dự án (tuỳ chọn, ảnh tham chiếu, logo, ý tưởng luôn được chép).
        mode: idea = chỉ ý tưởng (viết storyboard lại) | storyboard = + nhân vật, phong cách, các cảnh (chưa có ảnh / clip)
        | media = + ảnh khung đầu và clip đã tạo (làm biến thể: chỉ sửa vài cảnh / đổi giọng, nhạc, hậu kỳ rồi ghép).
        refs: danh sách ảnh tham chiếu cho bản sao (giữ / bỏ ảnh cũ, thêm ảnh mới); None = chép nguyên ảnh của dự án gốc."""
        if mode not in ("idea", "storyboard", "media"):
            raise StudioError("Kiểu nhân bản không hợp lệ")
        src = self.store.load(pid)
        sdir = self.store.dir(pid)
        new_name = str(name or "").strip()[:80] or f"{src['name']} (bản sao)"
        nid = f"{slugify(new_name, 40)}-{uuid.uuid4().hex[:6]}"
        ndir = self.store.root / nid
        (ndir / "refs").mkdir(parents=True)
        new_refs = []
        for r in (src.get("refs") or []) if refs is None else refs:
            path = Path(str(r))
            if path.is_file() and path.suffix.lower() in IMAGE_EXT and len(new_refs) < MAX_CLONE_REFS:
                dest = ndir / "refs" / f"{len(new_refs) + 1:02d}{path.suffix.lower()}"
                shutil.copy2(path, dest)
                new_refs.append(str(dest))
        refs = new_refs
        logo = copy_logo(ndir, src["logo"]) if src.get("logo") and Path(src["logo"]).is_file() else ""
        scenes = []
        if mode != "idea":
            for sc in src.get("scenes") or []:
                item = {**sc, "frame": "", "clip": "", "status": "", "error": ""}
                if mode == "media":
                    for key in ("frame", "clip"):
                        rel = sc.get(key) or ""
                        if rel and (sdir / rel).is_file():
                            (ndir / rel).parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(sdir / rel, ndir / rel)
                            item[key] = rel
                    item["status"] = _settled(item)
                scenes.append(item)
        project = {"id": nid, "name": new_name, "idea": src["idea"], "created_at": now(),
                   "options": self._clean(src.get("options") or {}), "refs": refs, "logo": logo,
                   "ref_video": rvm.copy_sheet(rvm.clean(src.get("ref_video")), ndir),
                   "bible": dict(src.get("bible") or {}) if mode != "idea" else {}, "scenes": scenes,
                   "status": "ready" if scenes else "draft", "error": "", "final": {}, "cloned_from": pid}
        self.store.save(project)
        self._push(project)
        return self.public(project)

    def set_logo(self, pid: str, src: str) -> dict:
        """Tải lên / thay / bỏ (src rỗng) logo thương hiệu của dự án."""
        if pid in self.running_ids():
            raise StudioError("Dự án đang chạy — chờ xong hoặc bấm Dừng rồi đổi logo")
        logo = copy_logo(self.store.dir(pid), src)
        project = self.store.update(pid, lambda p: p.update(logo=logo))
        self._push(project)
        return self.public(project)

    def start(self, pid: str, action: str, indexes: list | None = None, what: str = "both") -> str:
        """action: storyboard | scenes | assemble | make (= scenes + assemble) | post (hậu kỳ AI tiếp trên video đã xong).
        what: both | frame | clip; với post: fresh = bỏ gợi ý đã lưu, hỏi model lại."""
        if action not in ("compose", "analyze", "rewrite", "storyboard", "scenes", "assemble", "make", "post"):
            raise StudioError("Việc không hợp lệ")
        # khoá kiểm tra "đang chạy" → đưa vào hàng đợi: pywebview gọi API trên nhiều luồng, bấm nhanh 2 lần
        # (hoặc 2 nút cùng lúc) trước đây lọt cả 2 lời gọi → chạy trùng bước (vd. AI viết lại ý tưởng 2 lần)
        with self._start_lock:
            return self._start(pid, action, indexes, what)

    def _start(self, pid: str, action: str, indexes: list | None, what: str) -> str:
        project = self.store.load(pid)
        if pid in self.running_ids():
            raise StudioError("Dự án đang chạy — chờ xong hoặc bấm Dừng")
        if action == "rewrite" and not (project.get("brief") or {}).get("analysis"):
            raise StudioError("Chưa phân tích ý tưởng — chạy bước 1 trước")
        if action not in ("compose", "analyze", "rewrite", "storyboard") and not project.get("scenes"):
            raise StudioError("Chưa có storyboard — bấm Tạo storyboard trước")
        if action == "post":
            pdir = self.store.dir(pid)
            if any(not s.get("clip") or not (pdir / s["clip"]).is_file() for s in project["scenes"]):
                raise StudioError("Chưa đủ clip các cảnh — bấm ▶ Làm video trước, rồi mới chạy hậu kỳ AI")
            # chạy hậu kỳ chủ động → bật luôn tuỳ chọn (Ghép lại sau này cũng có hậu kỳ)
            project = self.store.update(pid, lambda p: p["options"].update(post_ai=True))
        title = {"compose": "Ảnh tổng hợp", "analyze": "Phân tích ý tưởng", "rewrite": "AI viết lại ý tưởng", "storyboard": "Storyboard",
                 "scenes": "Làm cảnh", "assemble": "Ghép video", "make": "Làm video", "post": "Hậu kỳ AI"}[action]
        task = self.pool.submit(f"Studio · {title} · {project['name']}", self._run, pid, action,
                                [int(i) for i in indexes or []], what if what in ("both", "frame", "clip", "fresh") else "both",
                                meta={"studio": pid})
        self._active[pid] = task
        self._push(project)
        return task

    def cancel(self, pid: str) -> int:
        task = self._active.get(pid)
        return self.pool.cancel(task) if task else 0

    def delete(self, pid: str) -> None:
        if pid in self.running_ids():
            raise StudioError("Dự án đang chạy — bấm Dừng trước")
        shutil.rmtree(self.store.dir(pid), ignore_errors=True)

    # ------------------------------------------------------------ chạy
    def _log(self, message: str, level: str = "info") -> None:
        self.pool.log(message, level)

    def _set(self, pid: str, **fields) -> dict:
        project = self.store.update(pid, lambda p: p.update(fields))
        self._push(project)
        return project

    def _settle_scenes(self, pid: str, **fields) -> None:
        """Dừng / lỗi: cảnh đang 'đang tạo…' trả về trạng thái thật (có ảnh / có clip / trống)."""
        def apply(p):
            p.update(fields)
            for sc in p.get("scenes") or []:
                sc["status"] = _settled(sc)
        self._push(self.store.update(pid, apply))

    def _run(self, pid: str, action: str, indexes: list, what: str) -> dict:
        self.license.require_active()
        self._set(pid, status="running", error="")
        try:
            # các bước nối nhau: chạy liên tục (flow=auto) thì đi tiếp; duyệt từng bước thì dừng để người dùng xem / sửa
            auto = lambda: self.store.load(pid)["options"].get("flow") == "auto"  # noqa: E731
            if action == "compose":  # ⓪ ghép layout + nhân vật + sản phẩm thành 1 ảnh tổng hợp
                self._compose_master(pid)
                if auto():
                    action = self._after_master(self.store.load(pid)["options"])
            if action == "analyze":
                self._analyze(pid)
                if auto():
                    action = "rewrite"
            if action == "rewrite":
                self._rewrite(pid)
                if auto():
                    action = "storyboard"
            if action == "storyboard":
                if no_storyboard(self.store.load(pid)["options"]):
                    self._direct_story(pid)
                    action = "make"  # không storyboard: không có gì để duyệt → làm cảnh → ghép luôn
                else:
                    self._storyboard(pid)
                    if self.store.load(pid)["options"].get("auto"):
                        action = "make"  # "Tự làm luôn": storyboard xong → làm cảnh → ghép
            if action in ("scenes", "make"):
                if no_storyboard(self.store.load(pid)["options"]):
                    self._fill_narration(pid)
                self._scenes(pid, indexes, what)
            if action in ("assemble", "make"):
                self._assemble(pid)
            if action == "post":  # hậu kỳ tiếp trên video đã xong: dùng lại clip, chỉ hậu kỳ + ghép lại
                self._assemble(pid, post="strict", fresh=what == "fresh")
        except Cancelled:
            self._settle_scenes(pid, status="cancelled", error="Đã dừng")
            raise
        except Exception as exc:
            self._settle_scenes(pid, status="error", error=str(exc))
            raise
        done = bool((self.store.load(pid).get("final") or {}).get("job_id"))
        project = self._set(pid, status="done" if done else "ready")
        return {"studio": pid, "status": project["status"]}

    # ---- 1. storyboard
    def _ask(self, options: dict, prompt: str, complete=None, what: str = "viết storyboard", images=None) -> str:
        return ask_model(self.settings, options, prompt, complete=complete, what=what, log=self._log,
                         check_cancel=self.pool.check_cancel, images=images or None)

    # ---- 0. phân tích ý tưởng → AI viết lại ý tưởng (bước 1, 2 — nguồn ý tưởng)
    def _context(self, o: dict, p: dict) -> str:
        """Bối cảnh dự án cho bước phân tích / viết lại: nhân vật, layout, ảnh sản phẩm, livestream, độ dài."""
        cast = self._cast(o, 0)
        lines = [f"- Video {ASPECTS[o['aspect']][3]} ~{o['length']} giây"]
        if cast["characters"]:
            lines.append("- Nhân vật cố định: " + "; ".join(f"{c['name']} ({c.get('summary') or c.get('description', '')[:160]})"
                                                           for c in cast["characters"]))
        if cast["layout"]:
            lines.append(f"- Bối cảnh / layout cố định: {cast['layout'].get('summary') or cast['layout'].get('description', '')[:200]}")
        if cast.get("combo"):
            lines.append(f"- Dàn cảnh mẫu: {cast['combo'].get('summary') or cast['combo'].get('idea', '')[:200]}")
        if p.get("refs"):
            lines.append(f"- Có {len(p['refs'])} ảnh sản phẩm / tham chiếu (đính kèm nếu model xem được ảnh)")
        # toàn bộ cài đặt đã chọn ở wizard (model video, độ dài clip, lồng tiếng / giọng gốc, khung đầu, livestream…)
        return "\n".join(lines) + "\n" + settings_text(o, p)

    def _brief_refs(self, o: dict, p: dict) -> tuple[list | None, str]:
        """Ảnh gửi kèm bước ① / ② (model trình duyệt): nhân vật ⭐, dàn cảnh / layout, sản phẩm + danh sách ảnh nào là gì
        (thêm vào prompt). Ghi nhật ký để người dùng biết ảnh có được gửi."""
        refs = self._story_refs(o, p, {"base": None}, {})
        if refs and o["model"].startswith("api:"):
            self._log(f"Model API chưa nhận ảnh — {len(refs)} ảnh nhân vật / sản phẩm không được gửi; muốn AI xem ảnh, "
                      "chọn model trình duyệt (ChatGPT / Gemini / Claude) ở bước ③", "warn")
            return None, ""
        if not refs:
            return None, ""
        self._log(f"Gửi kèm {len(refs)} ảnh — " + ", ".join(label.split(" —")[0] for _, label in refs))
        note = "\nẢnh đính kèm (theo thứ tự):\n" + "\n".join(f"{i}. {label}" for i, (_, label) in enumerate(refs, 1))
        return [str(path) for path, _ in refs], note

    def _analyze(self, pid: str) -> None:
        p = self.store.load(pid)
        o = p["options"]
        self.pool.progress(3, "Đang phân tích ý tưởng", "brief")
        self._log("Bước 1 · Phân tích ý tưởng…")
        images, note = self._brief_refs(o, p)  # ảnh nhân vật + dàn cảnh / layout + sản phẩm
        prompt = ANALYZE_PROMPT.format(idea=p["idea"], context=self._context(o, p) + note)
        complete = lambda t: isinstance(_try_json(t), dict) and bool(_try_json(t).get("thong_diep"))  # noqa: E731
        text = self._ask(o, prompt, complete=complete, what="phân tích ý tưởng", images=images)
        data = _try_json(text)
        if not isinstance(data, dict):
            raise StudioError("Model không trả về phân tích hợp lệ — thử lại hoặc đổi model")
        analysis = {k: data.get(k) for k in ANALYSIS_FIELDS}
        self._set(pid, brief={**(p.get("brief") or {}), "analysis": analysis, "analysis_text": format_analysis(analysis),
                              "idea_ai": "", "analyzed_at": now()})
        self._log("Bước 1 xong — xem / sửa phân tích rồi duyệt để AI viết lại ý tưởng", "ok")

    def _rewrite(self, pid: str) -> None:
        p = self.store.load(pid)
        o, brief = p["options"], p.get("brief") or {}
        self.pool.progress(5, "AI đang viết lại ý tưởng", "brief")
        self._log("Bước 2 · AI viết lại ý tưởng theo phân tích…")
        images, note = self._brief_refs(o, p)
        prompt = REWRITE_PROMPT.format(idea=p["idea"], analysis=brief.get("analysis_text") or "",
                                       context=self._context(o, p) + note)
        complete = lambda t: isinstance(_try_json(t), dict) and len(str(_try_json(t).get("y_tuong") or "")) > 40  # noqa: E731
        text = self._ask(o, prompt, complete=complete, what="viết lại ý tưởng", images=images)
        data = _try_json(text)
        idea_ai = str((data or {}).get("y_tuong") or "").strip() if isinstance(data, dict) else ""
        if len(idea_ai) < 40:
            raise StudioError("Model không trả về ý tưởng viết lại hợp lệ — thử lại hoặc đổi model")
        self._set(pid, brief={**brief, "idea_ai": idea_ai[:4000], "rewritten_at": now()})
        self._log("Bước 2 xong — xem / sửa ý tưởng mới rồi duyệt để viết storyboard", "ok")

    def _direct_frames(self, o: dict, p: dict | None = None) -> dict:
        """Ảnh ⭐ dùng THẲNG làm khung đầu (tuỳ chọn cast_direct, kiểu dựng cảnh video): bộ kết hợp → nhân vật → layout.
        Trả {"combo": [path], "chars": {tên: [path]}, "layout": [path], "all": [path]} — rỗng nếu không dùng."""
        out = {"combo": [], "chars": {}, "layout": [], "all": []}
        if self.cast is None or frame_mode(o) != "direct":
            return out

        def starred(kind: str, cid: str) -> tuple[dict | None, list[Path]]:
            try:
                item = self.cast.get(kind, cid)
            except Exception:  # mục đã xoá — _cast đã ghi nhật ký
                return None, []
            # sheet nhân vật (16:9, nhiều góc) / lưới biểu cảm 2×2 không làm khung đầu video được → bỏ qua
            return item, [Path(im["path"]) for im in item["starred"] if Path(im["path"]).is_file()
                          and im.get("preset") not in DIRECT_SKIP][:DIRECT_MAX]

        if o.get("cast_combo"):
            out["combo"] = starred("combo", o["cast_combo"])[1]
        for cid in (o.get("cast_characters") or [])[:MAX_CAST]:
            item, paths = starred("character", cid)
            if item and paths:
                out["chars"][item["name"]] = paths
        if o.get("cast_layout"):
            out["layout"] = starred("layout", o["cast_layout"])[1]
        if p is not None and master_path(p) is not None:  # ⓪ ảnh tổng hợp → khung đầu ưu tiên
            out["combo"] = [master_path(p)]
        out["all"] = out["combo"] or [x for ps in out["chars"].values() for x in ps] or out["layout"]
        return out

    def _story_refs(self, o: dict, p: dict, keep: dict, direct: dict) -> list[tuple[Path, str]]:
        """Ảnh gửi model viết storyboard (tối đa 6, không trùng): khung đầu có sẵn → nhân vật ⭐ (1 ảnh / người, bỏ sheet)
        → bộ kết hợp / layout ⭐ → ảnh sản phẩm của dự án. Trả [(đường dẫn, nhãn cho model)]."""
        out: list[tuple[Path, str]] = []

        def add(path, label):
            path = Path(path) if path else None
            if path and path.is_file() and all(path != x for x, _ in out) and len(out) < 6:
                out.append((path, label))

        master = master_path(p)
        if master is not None:  # ⓪ đã có ảnh tổng hợp → CHỈ gửi ảnh tổng hợp + ảnh sản phẩm
            add(master, "ẢNH TỔNG HỢP — layout + nhân vật + sản phẩm đã ghép sẵn; là khung chuẩn của video "
                        "(đúng người, trang phục, bối cảnh, sản phẩm)")
            for r in (p.get("refs") or [])[:3]:
                add(r, "SẢN PHẨM — đúng bao bì, nhãn, màu")
            return out
        if keep.get("base") is not None:
            add(keep["base"], "ẢNH LAYOUT — khung đầu của mọi cảnh (giữ nguyên bối cảnh, giao diện)")
        for path in direct.get("all", [])[:2]:
            add(path, "ảnh ⭐ dùng làm khung đầu")
        if self.cast is not None:
            combo = {}
            if o.get("cast_combo"):
                try:
                    combo, paths = self.cast.references("combo", o["cast_combo"], 1)
                    for path in paths:
                        add(path, "dàn cảnh mẫu — nhân vật trong bối cảnh")
                except Exception:  # bộ đã xoá — _cast đã ghi nhật ký
                    combo = {}
            for cid in (o.get("cast_characters") or combo.get("characters") or [])[:MAX_CAST]:
                try:
                    item = self.cast.get("character", cid)
                except Exception:
                    continue
                pick = next((im["path"] for im in item["starred"] if Path(im["path"]).is_file()
                             and im.get("preset") not in DIRECT_SKIP), None) or next(
                    (im["path"] for im in item["starred"] if Path(im["path"]).is_file()), None)
                add(pick, f"NHÂN VẬT {item['name']} — đúng khuôn mặt, tóc, vóc dáng, trang phục")
            layout_id = o.get("cast_layout") or combo.get("layout") or ""
            if layout_id and keep.get("base") is None:
                try:
                    _, paths = self.cast.references("layout", layout_id, 1)
                    for path in paths:
                        add(path, "bối cảnh / layout cố định")
                except Exception:
                    pass
        for r in (p.get("refs") or [])[:3]:
            add(r, "SẢN PHẨM — đúng bao bì, nhãn, màu")
        return out

    def _copy_frame(self, pid: str, pdir: Path, sc: dict, src: Path) -> None:
        """Khung đầu = ảnh có sẵn (chép vào thư mục cảnh, giữ nguyên ảnh gốc) — không tốn lượt tạo ảnh."""
        sdir = pdir / "scenes" / scene_dir_name(sc["index"])
        sdir.mkdir(parents=True, exist_ok=True)
        for old in sdir.glob("frame.*"):
            old.unlink(missing_ok=True)
        dest = sdir / f"frame{src.suffix.lower()}"
        shutil.copy2(src, dest)
        sc.update(frame=dest.relative_to(pdir).as_posix(), clip="", frame_src=src.name)
        self._scene_update(pid, sc["index"], frame=sc["frame"], clip="", frame_src=src.name, status="frame", error="")

    def _char_refs(self, o: dict) -> list[dict]:
        """Ảnh ⭐ của nhân vật đã chọn (1 ảnh / người, bỏ sheet / lưới biểu cảm) — [{name, path, desc}]."""
        out = []
        if self.cast is None:
            return out
        ids = list(o.get("cast_characters") or [])
        if not ids and o.get("cast_combo"):
            try:
                ids = list(self.cast.get("combo", o["cast_combo"]).get("characters") or [])
            except Exception:
                ids = []
        for cid in ids[:MAX_CAST]:
            try:
                item = self.cast.get("character", cid)
            except Exception:
                continue
            pick = next((Path(im["path"]) for im in item["starred"] if Path(im["path"]).is_file()
                         and im.get("preset") not in DIRECT_SKIP), None) or next(
                (Path(im["path"]) for im in item["starred"] if Path(im["path"]).is_file()), None)
            if pick:
                out.append({"name": item["name"], "path": pick, "desc": item.get("description") or item.get("summary") or ""})
        return out

    def _compose_master(self, pid: str) -> None:
        """⓪ Ảnh tổng hợp: ghép layout + nhân vật + sản phẩm thành 1 ảnh hoàn chỉnh (model ảnh). Các bước sau (phân tích,
        storyboard, khung đầu) dùng ảnh này thay cho từng ảnh rời."""
        p = self.store.load(pid)
        o, pdir = p["options"], self.store.dir(pid)
        spec = IMAGE_ENGINES[o["image_engine"]]
        self.pool.progress(2, "Đang ghép ảnh tổng hợp (layout + nhân vật + sản phẩm)", "master")
        self._log("Bước ⓪ · Ghép layout + nhân vật + sản phẩm thành 1 ảnh tổng hợp…")
        if spec["max_images"] < 1:
            raise StudioError(f"{spec['name']} không nhận ảnh tham chiếu — chọn model ảnh khác (ChatGPT, Gemini…) ở bước ③ "
                              "để ghép ảnh tổng hợp, hoặc tắt “Ảnh tổng hợp” ở bước ②")
        o_keep = {**o, "frame_mode": "keep"}
        keep = self._keep_base(o_keep, {**p, "master": None})  # ảnh layout / bộ kết hợp làm nền (nếu có)
        src, task = None, None
        if keep["base"] is not None:  # có layout: SỬA ảnh layout — đặt đúng nhân vật, thay sản phẩm, dọn giao diện
            job = self._keep_job(o_keep, keep, {"index": 0, "overlay": {}}, spec)
            if job is None:
                src = Path(keep["base"])
        else:  # không có layout: ghép nhân vật + sản phẩm thành ảnh mới theo ý tưởng / phong cách
            chars = self._char_refs(o)[:max(0, spec["max_images"] - 1)]
            products = [Path(r) for r in p.get("refs") or [] if Path(r).is_file()][:max(0, spec["max_images"] - len(chars))]
            bans = [b for b in o.get("bans", list(BANS)) if b not in ("text", "logos")]  # chữ / logo in trên bao bì
            prompt = MASTER_PROMPT.format(
                aspect=ASPECTS[o["aspect"]][2],
                people="; ".join(f"{c['name']} (character reference) — {c['desc'][:220]}" for c in chars)
                or "one friendly Vietnamese salesperson",
                product_note="keep it identical" if products else "no specific product",
                setting=o.get("style") or " ".join(p["idea"].split())[:300])
            job = {"engine": o["image_engine"], "prompt": (prompt + " " + negative_line({**o, "bans": bans})).strip(),
                   "aspect": o["aspect"], "count": 1, "quality": "high", "refs": [],
                   "show_browser": bool(o.get("show_browser")), "ref_note": True,
                   "ref_prompt": o.get("ref_prompt") or REF_PROMPT, "browser_profile": o.get("image_profile", ""),
                   "extra_refs": [{"path": str(c["path"]), "role": f"character reference — {c['name']}",
                                   "prompt": "this is the exact person: keep face, hair, body type and outfit identical"}
                                  for c in chars]
                   + [{"path": str(x), "role": "product photo",
                       "prompt": "keep this exact product — packaging, logo, label text, colours and proportions identical"}
                      for x in products]}
        try:
            if src is None:
                task = self.images.start(job)
                result = self._wait(self.images, task, "Ảnh tổng hợp")
                src = Path(self.settings.output_dir) / IMAGES_DIR / result["id"] / result["files"][0]["name"]
        except Cancelled:
            if task:
                self.images.cancel(task)
            raise
        for old in pdir.glob("master.*"):
            old.unlink(missing_ok=True)
        dest = pdir / f"master{src.suffix.lower()}"
        shutil.copy2(src, dest)
        self._set(pid, master={"path": str(dest), "at": now()})
        self._log("Bước ⓪ xong — ảnh tổng hợp dùng cho phân tích ý tưởng, storyboard và khung đầu các cảnh", "ok")

    def _keep_base(self, o: dict, p: dict) -> dict:
        """Giữ layout: ảnh nền để sửa (⭐ mới nhất của bộ kết hợp, không có thì của layout), layout (giao diện, bình
        luận thật) và ảnh sản phẩm thay vào (ảnh tham chiếu của dự án + ảnh sản phẩm của bộ kết hợp, tối đa 3)."""
        out = {"base": None, "layout": None, "products": [], "ui": {}, "chars": [], "from_combo": False}
        if self.cast is None or frame_mode(o) != "keep":
            return out
        combo = None
        if o.get("cast_combo"):
            try:
                combo, paths = self.cast.references("combo", o["cast_combo"], 1)
                out["base"] = paths[0] if paths else None
                out["from_combo"] = bool(paths)  # ảnh bộ kết hợp đã có nhân vật trong bối cảnh
            except Exception:  # bộ đã xoá — _cast đã ghi nhật ký
                combo = None
        if not out["from_combo"]:  # nền là ảnh layout → nhân vật đã chọn phải được đặt / thay vào ảnh
            for cid in (o.get("cast_characters") or (combo or {}).get("characters") or [])[:MAX_CAST]:
                try:
                    item = self.cast.get("character", cid)
                except Exception:
                    continue
                pick = next((Path(im["path"]) for im in item["starred"] if Path(im["path"]).is_file()
                             and im.get("preset") not in DIRECT_SKIP), None) or next(
                    (Path(im["path"]) for im in item["starred"] if Path(im["path"]).is_file()), None)
                if pick:
                    out["chars"].append({"name": item["name"], "path": pick,
                                         "desc": item.get("description") or item.get("summary") or ""})
        layout_id = o.get("cast_layout") or (combo or {}).get("layout") or ""
        if layout_id:
            try:
                layout, paths = self.cast.references("layout", layout_id, 1)
                out["layout"] = layout
                out["base"] = out["base"] or (paths[0] if paths else None)
            except Exception:
                pass
        out["ui"] = (out["layout"] or {}).get("ui") or {}
        products = [Path(r) for r in p.get("refs") or [] if Path(r).is_file()]
        products += [Path(im["path"]) for im in (combo or {}).get("products") or [] if Path(im["path"]).is_file()]
        out["products"] = list(dict.fromkeys(products))[:3]
        master = master_path(p)
        if master is not None and out["base"] is not None:  # ⓪ đã có ảnh tổng hợp (nhân vật + sản phẩm + layout sạch)
            out.update(base=master, from_combo=True, master=True)
        return out

    @staticmethod
    def _chat_by_app(o: dict, keep: dict) -> bool:
        """Giữ layout + layout có khung bình luận + bật chat_overlay → bình luận do app vẽ khi ghép (chữ chuẩn)."""
        elements = set((keep.get("ui") or {}).get("elements") or [])
        if (o.get("live") or {}).get("on"):  # mô phỏng livestream vẽ cả bình luận → không vẽ khung bình luận riêng
            return False
        return keep.get("base") is not None and o.get("chat_overlay", True) and bool(elements & CHAT_ELEMENTS)

    def _live_assets(self, o: dict, p: dict) -> tuple[str, str]:
        """Mô phỏng livestream: avatar chủ kênh (ảnh ⭐ nhân vật đầu tiên) + ảnh sản phẩm (ảnh tham chiếu đầu của dự án,
        không có thì ảnh sản phẩm của bộ kết hợp)."""
        # avatar kênh = ảnh người dùng tải lên ở 📱 Livestream (không tự lấy ảnh nhân vật — trống thì avatar trung tính)
        live_avatar = str((o.get("live") or {}).get("avatar") or "")
        avatar = live_avatar if live_avatar and Path(live_avatar).is_file() else ""
        product = next((r for r in p.get("refs") or [] if Path(r).is_file()), "")
        if self.cast is not None and not product and o.get("cast_combo"):
            try:
                combo = self.cast.get("combo", o["cast_combo"])
            except Exception:
                combo = {}
            product = next((im["path"] for im in combo.get("products") or [] if Path(im["path"]).is_file()), "")
        return avatar, product

    @staticmethod
    def _pin_live_avatar(pdir: Path, options: dict) -> None:
        """Avatar kênh livestream chọn từ máy → chép vào thư mục dự án (không mất khi file gốc bị xoá / di chuyển)."""
        live = options.get("live") or {}
        src = Path(str(live.get("avatar") or ""))
        if not live.get("avatar") or not src.is_file() or src.parent == pdir:
            return
        if src.suffix.lower() not in IMAGE_EXT:
            live["avatar"] = ""
            return
        for old in pdir.glob("live_avatar.*"):
            old.unlink(missing_ok=True)
        dest = pdir / f"live_avatar{src.suffix.lower()}"
        shutil.copy2(src, dest)
        live["avatar"] = str(dest)

    @staticmethod
    def _keep_texts(keep: dict, sc: dict) -> dict:
        """Chữ trên giao diện của cảnh: nội dung storyboard viết; thiếu thì xoay vòng bình luận thật của khách."""
        ui = keep.get("ui") or {}
        if not ui.get("elements"):
            return {}
        ov = dict(sc.get("overlay") or {})
        real = [c for c in (ui.get("comments") or "").splitlines() if c.strip()]
        if not ov.get("comments") and real:
            start = (int(sc.get("index") or 1) - 1) * 3 % len(real)
            ov["comments"] = (real[start:] + real[:start])[:4]
        ov["comments"] = list(dict.fromkeys(c for c in ov.get("comments") or [] if str(c).strip()))  # bỏ dòng trùng
        if ui.get("channel"):
            ov["channel"] = ui["channel"]
        return ov

    def _keep_job(self, o: dict, keep: dict, sc: dict, spec: dict) -> dict | None:
        """Phiếu Tạo hình ảnh: SỬA ảnh layout — chỉ thay sản phẩm + chữ trên giao diện. None = không có gì để đổi
        (dùng nguyên ảnh layout, không tốn lượt tạo ảnh)."""
        texts = self._keep_texts(keep, sc)
        master = bool(keep.get("master"))  # nền = ảnh tổng hợp ⓪: đã có nhân vật + sản phẩm, giao diện đã dọn
        names_in = sc.get("cast") if isinstance(sc.get("cast"), list) else None
        chars = [] if master else [c for c in keep.get("chars") or [] if names_in is None or c["name"] in names_in] or keep.get("chars") or []
        chars = chars[:max(0, spec["max_images"] - 1)]
        products = [] if master else keep["products"][:max(0, spec["max_images"] - 1 - len(chars))]
        changes = []
        if chars:  # nền là layout: người trong ảnh phải là ĐÚNG nhân vật đã chọn
            changes.append("- The person: the person in the scene must be EXACTLY "
                           + " and ".join(f"{c['name']} (character reference image {i + 2}: {c['desc'][:300]})"
                                          for i, c in enumerate(chars))
                           + " — same face, skin tone, apparent age, hair, body type and outfit as the reference. If the "
                           "layout already shows a person, keep that person's pose, position and framing but give them "
                           "this exact identity and outfit; if it shows no person, place the character naturally in the "
                           "middle ground facing the camera, without covering or moving any interface element.")
        if products:
            changes.append("- The product: replace the product the person holds / presents with the product in the next "
                           "attached image(s) — exact packaging, shape, colours, label text and logo; same size, position "
                           "and grip as the original product.")
        if master and ((o.get("live") or {}).get("on") or self._chat_by_app(o, keep)):
            pass  # ảnh tổng hợp đã dọn giao diện / vùng bình luận
        elif (o.get("live") or {}).get("on") and (keep.get("ui") or {}).get("elements"):
            # app vẽ lại TOÀN BỘ giao diện livestream khi ghép → bỏ giao diện cũ của layout (tránh 2 lớp chồng nhau)
            changes.append("- The interface: remove EVERY on-screen interface element (badges, avatars, icons, buttons, "
                           "hearts, comment bubbles, input bar, all overlay text) so only the clean photographic scene "
                           "remains — a live-stream interface is added later. Fill the uncovered areas naturally.")
        elif self._chat_by_app(o, keep):  # app tự vẽ bình luận khi ghép → model chỉ làm sạch vùng bình luận, KHÔNG viết chữ
            changes.append("- The comment area: remove every comment bubble, avatar and chat message in the comment "
                           "panel so that area shows only the clean scene behind it (live comments are added later). "
                           "Keep the other interface elements (badges, icons, hearts, buttons, input bar) unchanged.")
        else:
            if texts.get("comments"):
                changes.append("- The comment bubbles in the comment panel read, top to bottom (Vietnamese, exact spelling, "
                               "legible, keep each bubble's avatar style): " + "; ".join(f"“{c}”" for c in texts["comments"]))
            if texts.get("caption"):
                changes.append(f"- The on-screen caption / product text reads: “{texts['caption']}”.")
            if texts.get("channel"):
                changes.append(f"- The channel name reads: “{texts['channel']}”.")
        if not changes:
            return None
        bans = [b for b in o.get("bans", list(BANS)) if b not in ("text", "logos")]  # giao diện cần chữ + logo sản phẩm
        prompt = KEEP_PROMPT.format(changes="\n".join(changes)) + " " + negative_line({**o, "bans": bans})
        return {"engine": o["image_engine"], "prompt": prompt.strip(), "aspect": o["aspect"], "count": 1,
                "quality": "high", "refs": [], "show_browser": bool(o.get("show_browser")),
                "extra_refs": [{"path": str(keep["base"]), "role": "image to edit",
                                "prompt": "keep everything identical; change only the listed parts"}]
                + [{"path": str(c["path"]), "role": f"character reference — {c['name']}",
                    "prompt": "this is the exact person: keep face, hair, body type and outfit identical"} for c in chars]
                + [{"path": str(x), "role": "product photo",
                    "prompt": "keep this exact product — packaging, logo, label text, colours and proportions identical"}
                   for x in products],
                "ref_note": True, "ref_prompt": o.get("ref_prompt") or REF_PROMPT,
                "browser_profile": o.get("image_profile", "")}

    @staticmethod
    def _pick_direct(direct: dict, sc: dict, current: str = "") -> Path | None:
        """Khung đầu có sẵn cho 1 cảnh: ảnh bộ kết hợp; không có thì ảnh của nhân vật xuất hiện trong cảnh; rồi layout.
        Nhiều ảnh → chia lần lượt theo số cảnh; làm lại ảnh 1 cảnh → lấy ảnh kế tiếp (khác ảnh đang dùng)."""
        names = [n for n in (sc.get("cast") or []) if n in direct["chars"]]
        pool = direct["combo"] or (direct["chars"][names[0]] if names else []) or direct["all"]
        if not pool:
            return None
        names_now = [p.name for p in pool]
        if current in names_now:
            return pool[(names_now.index(current) + 1) % len(pool)]
        return pool[(int(sc.get("index") or 1) - 1) % len(pool)]

    def _direct_story(self, pid: str) -> None:
        """Không viết storyboard: chia ý tưởng (bản AI viết lại nếu có) thành các clip nối tiếp, mỗi clip dài tối đa
        của model video. Không hỏi model viết; lời đọc = các câu của ý tưởng chia đều cho từng clip (sửa được trước khi làm)."""
        p = self.store.load(pid)
        o = p["options"]
        idea = self._direct_idea(p)
        if not idea:
            raise StudioError("Chưa có ý tưởng để làm video")
        longest = max(video_engine_durations(o["video_engine"]))
        count = max(1, min(MAX_SCENES, -(-o["length"] // longest)))
        self.pool.progress(3, f"Chia ý tưởng thành {count} clip (không storyboard)", "script")
        reads = split_narration(idea, count)
        scenes = []
        for i in range(1, count + 1):
            part = f"Part {i} of {count} — continue the action naturally from the previous part. " if count > 1 else ""
            scenes.append({"index": i, "title": f"Phần {i}/{count}" if count > 1 else "Video", "narration": reads[i - 1], "lines": [],
                           "speaker": "", "image_prompt": idea[:1500], "motion_prompt": (part + idea)[:600],
                           "seconds": longest, "frame": "", "clip": "", "status": "", "error": ""})
        self._set(pid, scenes=scenes, final={})
        self._warn_long_speech(scenes, o["video_engine"])
        self._log(f"Không storyboard: {count} clip × {longest}s từ ý tưởng, lời đọc lấy từ ý tưởng — làm video luôn", "ok")

    @staticmethod
    def _direct_idea(p: dict) -> str:
        return " ".join(str((p.get("brief") or {}).get("idea_ai") or p.get("idea") or "").split())

    def _fill_narration(self, pid: str) -> None:
        """Dự án đã chia clip trước đây (lời đọc trống) → điền lời đọc từ ý tưởng trước khi làm cảnh."""
        p = self.store.load(pid)
        scenes = p.get("scenes") or []
        if not scenes or any((s.get("narration") or "").strip() or s.get("lines") for s in scenes):
            return
        reads = split_narration(self._direct_idea(p), len(scenes))
        self._set(pid, scenes=[{**s, "narration": reads[k]} for k, s in enumerate(scenes)])
        self._log("Lời đọc đang trống — đã lấy các câu của ý tưởng chia cho từng clip", "info")

    def _storyboard(self, pid: str) -> None:
        p = self.store.load(pid)
        o = p["options"]
        self.pool.progress(3, "Đang viết storyboard", "script")
        allowed = video_engine_durations(o["video_engine"])
        count = scene_count(o["length"])
        # nguồn kịch bản = video phân tích: mỗi đoạn trong vật liệu = 1 cảnh, không dùng ý tưởng
        from_video = o.get("source_mode") == "video" and bool(p.get("ref_video"))
        mats = ((p.get("ref_video") or {}).get("data") or {}).get("canh") or [] if from_video else []
        if mats:
            count = max(1, min(MAX_SCENES, len(mats)))
        if count == 1 and max(allowed) < o["length"]:
            self._log(f"{VIDEO_ENGINES[o['video_engine']]['name']} tạo clip tối đa {max(allowed)}s — video 1 cảnh sẽ dài "
                      f"~{max(allowed)}s (muốn {o['length']}s: chọn Grok, clip 15s)", "warn")
        refs = len(p.get("refs") or [])
        cast = self._cast(o, 0)  # chỉ cần mô tả (ảnh gửi ở bước tạo ảnh khung đầu)
        shot, angle = o.get("shot_size") or "auto", o.get("camera_angle") or "auto"
        shot_rule = " ".join(x for x in (
            f'MỌI cảnh "co_canh" = {shot} ({SHOT_SIZES[shot][0]}).' if shot not in ("auto", "mix") else
            'Đổi "co_canh" theo nhịp: mở bằng toàn cảnh / trung cảnh, cận khi cảm xúc / chi tiết sản phẩm — 2 cảnh liền nhau '
            'không cùng cỡ.' if shot == "mix" else 'Chọn "co_canh" hợp nội dung từng cảnh.',
            f'MỌI cảnh "goc_may" = {angle} ({CAMERA_ANGLES[angle][0]}).' if angle != "auto" else
            'Chọn "goc_may" hợp nội dung từng cảnh.') if x)
        cast_text = "\n".join(x for x in (
            ("NHÂN VẬT CỐ ĐỊNH — bắt buộc dùng đúng những nhân vật này (tự đặt vai trò trong câu chuyện); trường "
             "\"nhan_vat_ds\" phải có đúng các nhân vật này (giữ nguyên tên; \"ngoai_hinh\" chép NGUYÊN VĂN mô tả "
             "tiếng Anh dưới đây):\n"
             + "\n".join(f"- {c['name']}: {c.get('description') or c.get('summary') or c.get('idea', '')}"
                         for c in cast["characters"])) if cast["characters"] else "",
            (f"BỐI CẢNH / LAYOUT CỐ ĐỊNH — mọi cảnh diễn ra tại đây (được đổi góc máy, khoảng cách), prompt_anh phải "
             f"giữ đúng bối cảnh này: {cast['layout'].get('description') or cast['layout'].get('summary', '')}")
            if cast["layout"] else "",
            (f"DÀN CẢNH MẪU (nhân vật trong bối cảnh — dùng cho các cảnh chính): "
             f"{cast['combo'].get('description') or cast['combo'].get('summary') or cast['combo'].get('idea', '')}")
            if cast.get("combo") else "",
            ("GIỮ NGUYÊN TRANG PHỤC: nhân vật cố định mặc ĐÚNG bộ đồ trong ảnh tham chiếu ở MỌI cảnh — trong "
             "‘prompt_anh’ / ‘prompt_chuyen_dong’ KHÔNG tả quần áo, phụ kiện, kiểu tóc, KHÔNG thay đồ.")
            if cast["characters"] else "",
            ("GIỮ NGUYÊN KHUÔN MẶT, PHONG CÁCH, ĐỘ TUỔI: nhân vật cố định là CÙNG MỘT NGƯỜI ở mọi cảnh — không đổi "
             "gương mặt, màu da, vóc dáng, phong cách (thần thái, trang điểm, gu ăn mặc) và ĐỘ TUỔI; không viết cảnh "
             "nhân vật lúc nhỏ / lúc già / sau nhiều năm, không tả tuổi hay nét mặt khác trong ‘prompt_anh’.")
            if cast["characters"] else "",
            ("GIỮ NGUYÊN BỐI CẢNH: KHÔNG chuyển sang địa điểm khác — ‘prompt_anh’ chỉ tả hành động, biểu cảm, góc máy, "
             "khoảng cách máy, đạo cụ trong bối cảnh cố định.")
            if cast["layout"] else "") if x)
        direct = self._direct_frames(o, p)  # dùng thẳng ảnh ⭐ làm khung đầu → storyboard viết theo đúng các ảnh đó
        story_images = [str(x) for x in direct["all"][:DIRECT_STORY_IMAGES]]
        if direct["all"]:
            cast_text += "\n" + DIRECT_NOTE.format(
                attached=f" ({len(story_images)} ảnh đính kèm — xem kỹ người, trang phục, bối cảnh, sản phẩm trong ảnh)"
                if not o["model"].startswith("api:") else "")
            self._log(f"Storyboard viết theo {len(direct['all'])} ảnh ⭐ có sẵn (gửi kèm {len(story_images)} ảnh cho model)"
                      if not o["model"].startswith("api:") else
                      f"Storyboard viết theo {len(direct['all'])} ảnh ⭐ có sẵn (model API chỉ đọc mô tả, không xem ảnh)")
        keep = self._keep_base(o, p)  # giữ nguyên layout: storyboard chỉ đổi sản phẩm + nội dung giao diện từng cảnh
        if keep["base"] is not None:
            ui = keep["ui"] or {}
            real = "\n".join(f"  • {c}" for c in (ui.get("comments") or "").splitlines() if c.strip())
            cast_text += "\n" + KEEP_NOTE.format(
                attached=" (ảnh layout đính kèm — xem danh sách ảnh bên dưới)" if not o["model"].startswith("api:") else "",
                product=" theo ảnh sản phẩm đính kèm" if keep["products"] else "",
                ui_rule=KEEP_UI_RULE.format(n=OVERLAY_COMMENTS, real=f"\nBình luận thật của khách:\n{real}" if real else "")
                if ui.get("elements") else "")
            self._log("Storyboard: giữ nguyên layout — chỉ viết hành động, lời thoại"
                      + (" + bình luận / chữ trên giao diện từng cảnh" if ui.get("elements") else ""))
        live = o.get("live") or {}
        if live.get("on") and not (keep["base"] is not None and (keep["ui"] or {}).get("elements")):
            # mô phỏng livestream: mỗi cảnh cũng cần bình luận người xem + chữ trên màn (app vẽ khi ghép)
            real = "\n".join(f"  • {c}" for c in (live.get("comments") or "").splitlines() if c.strip())
            cast_text += ("\nVIDEO LIVESTREAM — người trong cảnh đang livestream bán hàng, nói trực tiếp với người xem "
                          "(nhìn vào ống kính, trả lời bình luận). Giao diện live do app tự thêm: KHÔNG tả giao diện, chữ, "
                          "icon trong ‘prompt_anh’.\n"
                          + KEEP_UI_RULE.format(n=OVERLAY_COMMENTS, real=f"\nBình luận thật của khách:\n{real}" if real else ""))
            self._log("Storyboard: video livestream — viết thêm bình luận người xem / chữ trên màn từng cảnh")
        # ảnh gửi kèm model viết storyboard: khung đầu có sẵn (layout / bộ kết hợp / ảnh ⭐) + NHÂN VẬT + sản phẩm,
        # kèm danh sách ảnh nào là gì để model mô tả đúng người, bối cảnh, bao bì
        story_refs = self._story_refs(o, p, keep, direct)
        story_images = [str(path) for path, _ in story_refs]
        if story_refs and not o["model"].startswith("api:"):
            cast_text += "\nẢNH ĐÍNH KÈM (theo thứ tự) — xem kỹ, mô tả đúng người / trang phục / bối cảnh / sản phẩm trong ảnh:\n" \
                + "\n".join(f"{i}. {label}" for i, (_, label) in enumerate(story_refs, 1))
            self._log(f"Storyboard: gửi kèm {len(story_refs)} ảnh — " + ", ".join(label.split(" —")[0] for _, label in story_refs))
        elif story_refs:
            self._log(f"Model API chưa nhận ảnh — {len(story_refs)} ảnh nhân vật / layout / sản phẩm không được gửi; "
                      "muốn AI xem ảnh, chọn model trình duyệt", "warn")
        if from_video:
            total = int(sum(max(1.0, m["den"] - m["tu"]) for m in mats)) if mats else o["length"]
            source = f"""Chuyển thể video đã phân tích dưới đây thành storyboard cho 1 video {ASPECTS[o['aspect']][3]} dài khoảng {total} giây.
{rvm.materials_block(p.get("ref_video"))}
CÁCH CHUYỂN THỂ (vật liệu đã được người dùng duyệt — dùng TẤT CẢ):
- {f'Đúng {count} cảnh, mỗi cảnh ứng với 1 đoạn trong vật liệu theo đúng thứ tự' if mats else 'Theo đúng cấu trúc trong vật liệu'}: giữ nội dung, hành động, góc máy / bố cục, hook, nhịp, phong cách hình; "giay" gần nhất với độ dài đoạn.
- Lời thoại: dùng lời trong vật liệu (giữ ý và giọng điệu, chỉnh cho vừa thời lượng cảnh); tên thương hiệu / sản phẩm của video gốc đổi thành sản phẩm của người dùng nếu có.
- Nhân vật, sản phẩm, bối cảnh: đã chọn nhân vật / layout / ảnh sản phẩm cố định thì DÙNG CHÚNG thay cho video gốc; chưa chọn thì dựng theo mô tả trong vật liệu.
- Chữ trên màn trong vật liệu: đưa vào "noi_dung_layout"."chu" khi đang giữ layout; nếu không thì bỏ (không chữ trên hình)."""
            self._log(f"Nguồn kịch bản: video phân tích ({len(mats)} đoạn vật liệu) — không dùng ý tưởng")
        else:
            source = f"""Viết storyboard cho 1 video {ASPECTS[o['aspect']][3]} dài khoảng {o['length']} giây theo ý tưởng:
<y_tuong>
{(p.get('brief') or {}).get('idea_ai') or p['idea']}
</y_tuong>"""  # nguồn ý tưởng: ý tưởng AI viết lại (bước 2, đã duyệt) hoặc ý tưởng gốc; không dùng video tham khảo
        prompt = f"""{source}
{settings_text(o, p)}
{('Phong cách hình ảnh mong muốn: ' + o['style']) if o['style'] else ''}
{(f'Người dùng có {refs} ảnh tham chiếu (nhân vật / sản phẩm) — mô tả nhân vật khớp với ảnh, model ảnh sẽ nhận các ảnh này.') if refs else ''}
{cast_text}
{'PHONG CÁCH: video vẽ tay bảng trắng (whiteboard) — "prompt_anh" mô tả hình minh hoạ đơn giản, rõ ý (đồ vật, người, biểu tượng, sơ đồ), không chữ; mỗi câu lời dẫn là 1 ý vẽ được; "prompt_chuyen_dong" để trống.' if o.get('scene_style') == 'whiteboard' else ''}

YÊU CẦU:
{f'''- Đúng 1 cảnh — MỘT cú máy liền mạch dài ~{min(o["length"], max(allowed))} giây ("giay" = {max(d for d in allowed if d <= max(o["length"], min(allowed)))}): hook ngay giây đầu,
  hành động chính rõ ràng, kết bằng thông điệp / lời kêu gọi (nếu là quảng cáo); lời thoại ngắn, nói hết trong cảnh.''' if count == 1 else
f'''- Đúng {count} cảnh, mạch truyện rõ: mở đầu gây chú ý (3 giây đầu), diễn biến, cao trào, kết + lời kêu gọi (nếu là quảng cáo).'''}
- "nhan_vat_ds": HỒ SƠ NHÂN VẬT (tối đa {MAX_CHARACTERS}) — mỗi người: "ten" (tên ngắn, dùng nhất quán cả bài);
  "ngoai_hinh" (tiếng Anh: giới tính, tuổi cụ thể, dân tộc, khuôn mặt, kiểu + màu tóc, vóc dáng — CỐ ĐỊNH mọi cảnh);
  "trang_phuc" (tiếng Anh: MỘT bộ trang phục cố định — loại áo / quần / váy, màu, chất liệu, giày, phụ kiện);
  "giong" (giọng lồng tiếng, đúng một mã: {', '.join(k for k in ROLES if k)}; mỗi nhân vật một giọng KHÁC nhau, hợp tuổi
  và giới tính — trẻ em girl/boy, thiếu niên teen_f/teen_m, người già old_f/old_m).
  "nhan_vat": mô tả sản phẩm / đạo cụ chính (tiếng Anh, nếu có). "phong_cach": phong cách hình ảnh chung (ánh sáng, màu, ống kính), tiếng Anh.
- Mỗi cảnh: "tieu_de" (tiếng Việt, ngắn); "nhan_vat_canh": tên các nhân vật XUẤT HIỆN trong khung hình ([] nếu không có ai);
  "thoai": lời thoại / lời dẫn của cảnh theo thứ tự — mỗi câu {{"ai": tên nhân vật đang nói, hoặc "dan_chuyen" nếu là lời bình
  bên ngoài; "cau": câu tiếng Việt tự nhiên; "cam_xuc": cảm xúc / giọng điệu ngắn (vd. hào hứng, thì thầm, nghiêm túc)}};
  tổng số từ của cảnh KHÔNG vượt quá 3,8 × (giay − 0,8) (vd. 5 giây ≤ 16 từ, 10 giây ≤ 35 từ, 15 giây ≤ 54 từ) để nhân vật
  nói HẾT câu, không nói vội, khớp khẩu hình — lời dài thì chia sang cảnh sau; cảnh chỉ có hình thì "thoai": [];
  mỗi cảnh CHỈ MỘT nhân vật nói trên khung hình (2 người nói trong 1 clip → khẩu hình loạn) — muốn đối đáp thì mỗi lượt nói
  là 1 cảnh; lời dẫn chuyện ("dan_chuyen") đọc ngoài khung, không tính là người nói trên khung hình;
  "giong": mã giọng của người dẫn chuyện (narrator_f / narrator_m / mc_f…);
  "prompt_anh" (tiếng Anh) theo công thức: cỡ cảnh + góc máy → nhân vật (gọi bằng TÊN) đang làm gì, tư thế, biểu cảm →
  bố cục, tiền cảnh / hậu cảnh, đạo cụ → ánh sáng, thời điểm → ống kính, độ sâu trường ảnh → không khí, tông màu.
  KHÔNG tả lại khuôn mặt, tuổi, tóc, quần áo (app tự chèn hồ sơ nhân vật); KHÔNG chữ trên hình;
  "prompt_chuyen_dong" (tiếng Anh) viết THEO MỐC GIÂY, vd. "0-3s: looks at the camera, smiles and waves; 3-7s: lifts the
  product toward the camera; 7-10s: nods and points at the product" — cả cảnh tối đa 1–2 hành động chính, tay làm ít việc
  (KHÔNG vừa cầm vừa mở nắp vừa rót vừa chỉ → méo tay, thừa ngón); sản phẩm ở khoảng cách vừa, không dí sát chữ nhỏ trên nhãn;
  thêm 1 chuyển động máy (static, slow dolly in, pan…); mốc cuối đúng bằng "giay"; "giay": một trong {allowed}.
  "co_canh": cỡ cảnh, đúng một mã {', '.join(k for k in SHOT_SIZES if k not in ('auto', 'mix'))};
  "goc_may": góc máy, đúng một mã {', '.join(k for k in CAMERA_ANGLES if k != 'auto')}.
  {shot_rule}
- Không chữ, logo, watermark trong hình. Không nội dung nhạy cảm.
- Bên trong các chuỗi JSON KHÔNG dùng dấu ngoặc kép " — trích dẫn / tên sản phẩm dùng ‘ ’ hoặc viết thường.

Chỉ trả về MỘT object JSON (không markdown, không giải thích):
{{"nhan_vat_ds":[{{"ten":"…","ngoai_hinh":"…","trang_phuc":"…","giong":"young_f"}}],"nhan_vat":"…","phong_cach":"…","canh":[{{"tieu_de":"…","nhan_vat_canh":["…"],"thoai":[{{"ai":"…","cau":"…","cam_xuc":"…"}}],"giong":"narrator_f","prompt_anh":"…","prompt_chuyen_dong":"…","co_canh":"medium","goc_may":"eye","giay":{allowed[-1]}}}]}}"""
        self._log(f"Đang viết storyboard {count} cảnh (~{o['length']} giây)…")
        data, text = None, ""
        for attempt in (1, 2):
            text = self._ask(o, prompt if attempt == 1 else prompt + "\n\nLẦN TRƯỚC CHƯA NHẬN ĐƯỢC JSON HỢP LỆ — không hỏi lại, "
                             "tự quyết định mọi chi tiết còn thiếu và chỉ trả đúng 1 object JSON.",
                             complete=storyboard_complete,
                             images=story_images if story_images and not o["model"].startswith("api:") else None)
            try:
                data = extract_json(text)
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get("canh"):
                break
            self._log(f"Lần {attempt}: model trả về không đúng JSON storyboard"
                      + (f" — mở đầu: “{' '.join(str(text).split())[:120]}”" if text else " (trả lời rỗng)"), "warn")
        if not isinstance(data, dict) or not data.get("canh"):
            raise StudioError("Model không trả về storyboard hợp lệ"
                              + (" (trả lời rỗng — kiểm tra đăng nhập / profile của model)" if not str(text).strip()
                                 else " — thử lại hoặc đổi model (Claude / Gemini API viết JSON ổn định hơn)"))
        characters = clean_characters(data.get("nhan_vat_ds"))
        if cast["characters"]:  # nhân vật cố định: ngoại hình lấy nguyên mô tả đã duyệt
            characters = merge_cast(characters, cast["characters"])
        names = [c["name"] for c in characters]
        scenes = []
        for i, raw in enumerate(data["canh"][:count if count < MIN_SCENES else MAX_SCENES], 1):  # video ngắn: đúng số cảnh
            lines = clean_lines(raw.get("thoai"), names)
            on_screen = raw.get("nhan_vat_canh")
            scenes.append({"index": i, "title": str(raw.get("tieu_de") or f"Cảnh {i}")[:120],
                           "narration": (lines_text(lines) or str(raw.get("loi_doc") or "").strip())[:1200],
                           "lines": lines,
                           **({"cast": [n for n in names if n.lower() in {_flat(x, 40).lower() for x in on_screen}]}
                              if isinstance(on_screen, list) and names else {}),
                           "speaker": raw.get("giong") if raw.get("giong") in ROLES else "",
                           "image_prompt": str(raw.get("prompt_anh") or "").strip()[:1500],
                           "shot": raw.get("co_canh") if raw.get("co_canh") in SHOT_SIZES else "",
                           "angle": raw.get("goc_may") if raw.get("goc_may") in CAMERA_ANGLES else "",
                           "motion_prompt": str(raw.get("prompt_chuyen_dong") or "").strip()[:600],
                           **({"overlay": clean_overlay(raw.get("noi_dung_layout"))}
                              if clean_overlay(raw.get("noi_dung_layout")) else {}),
                           "seconds": seconds_for_speech(o["video_engine"], raw.get("giay"),
                                                         {"lines": lines, "narration": str(raw.get("loi_doc") or "")}),
                           "frame": "", "clip": "",
                           "status": "", "error": ""})
        bible = {"nhan_vat": str(data.get("nhan_vat") or "")[:1500], "phong_cach": str(data.get("phong_cach") or "")[:600]}
        if cast["characters"]:  # nhân vật cố định: dùng nguyên mô tả đã duyệt, không để model diễn đạt lại
            bible["nhan_vat"] = "; ".join(f"{c['name']}: {c.get('description') or c.get('summary', '')}"
                                          for c in cast["characters"])[:1500]
        if characters:
            bible["characters"] = characters
        self._set(pid, scenes=scenes, bible=bible, final={})
        self._warn_long_speech(scenes, o["video_engine"])
        self._log(f"Storyboard xong: {len(scenes)} cảnh · ~{sum(s['seconds'] for s in scenes)} giây hình"
                  + (f" · {len(characters)} nhân vật: " + ", ".join(
                      f"{c['name']} ({ROLES.get(c['voice'] or '', ROLES[''])[0]})" for c in characters) if characters else ""),
                  "ok")

    def _warn_long_speech(self, scenes: list, engine: str) -> None:
        longest = max(video_engine_durations(engine))
        for sc in scenes:
            speakers = sorted({ln["who"] for ln in sc.get("lines") or [] if ln.get("text") and ln.get("who")})
            if len(speakers) > 1:
                self._log(f"Cảnh {sc['index']}: {len(speakers)} nhân vật cùng nói trong 1 clip ({', '.join(speakers)}) — "
                          "model video dễ loạn khẩu hình; nên tách mỗi lượt nói thành 1 cảnh", "warn")
            over = speech_overflow(engine, sc)
            if over > 0:
                self._log(f"Cảnh {sc['index']}: lời thoại cần ~{speech_seconds(sc):.0f}s nhưng clip tối đa {longest}s — "
                          f"rút gọn lời hoặc tách thành 2 cảnh để không bị ngắt câu", "warn")

    def _scene_update(self, pid: str, index: int, **fields) -> None:
        def apply(p):
            for sc in p["scenes"]:
                if sc["index"] == index:
                    sc.update(fields)
        self._push(self.store.update(pid, apply))

    def _parallel_hint(self, o: dict, count: int) -> None:
        """Nhật ký: chạy được bao nhiêu Chrome song song cho model video và vì sao chỉ chạy lần lượt (nếu vậy)."""
        engine = o["video_engine"]
        slots = int(self.settings.get("max_parallel_video") or 2)
        if not engine.endswith("_browser") or count < 2:
            return
        from .browser_profiles import SITE_NAMES, list_profiles

        site = engine.removesuffix("_browser")
        name = SITE_NAMES.get(site, site)
        mine = [p for p in list_profiles() if site in p.get("sites", [])]
        if o.get("video_profile"):
            self._log(f"Clip chạy LẦN LƯỢT vì đã chọn 1 profile cố định — chọn “Tự chọn profile rảnh” ở ⚙ dự án để "
                      f"mở nhiều Chrome cùng lúc", "warn")
            return
        n = min(slots, len(mine), count)
        self._log(f"Tạo song song {n} clip ({n} cửa sổ Chrome) · giới hạn {slots} ở Cài đặt → Số video tạo song song · "
                  f"{len(mine)} profile đã gán {name}")
        if len(mine) < min(slots, count):
            self._log(f"Muốn nhanh hơn: tạo thêm profile ở “Profile trình duyệt”, đăng nhập {name} (có thể dùng nhiều tài "
                      f"khoản) và gán cho {name} — mỗi profile chạy 1 Chrome", "warn")

    def _wait(self, runner, task_id: str, what: str) -> dict:
        summary = runner.pool.wait(task_id, self.pool.check_cancel)
        if summary["status"] != "done" or not summary.get("result"):
            raise StudioError(f"{what}: {summary.get('error') or summary['status']}")
        return summary["result"]

    def _cast(self, o: dict, budget: int = 99) -> dict:
        """Nhân vật / layout cố định đã chọn (màn Nhân vật & Layout): mô tả + ảnh ⭐ trong giới hạn số ảnh `budget`.
        Mục đã bị xoá thì bỏ qua (ghi nhật ký)."""
        out = {"characters": [], "layout": None, "combo": None, "refs": []}
        if self.cast is None:
            return out
        chars = [c for c in o.get("cast_characters") or [] if c][:MAX_CAST]
        layout = o.get("cast_layout") or ""
        if o.get("cast_combo"):  # bộ kết hợp: ảnh ⭐ (nhân vật đặt vào layout) gửi trước; thiếu thì lấy thành viên của bộ
            try:
                combo, paths = self.cast.references("combo", o["cast_combo"], min(1, budget))
                out["combo"] = combo
                out["refs"] += [{"path": str(p), "role": "scene reference (these people in this setting)",
                                 "prompt": "how the characters look together in the setting — keep identities, outfits "
                                           "and the setting consistent with it"} for p in paths]
                chars = chars or list(combo.get("characters") or [])[:MAX_CAST]
                layout = layout or combo.get("layout") or ""
                for im in (combo.get("products") or [])[:2]:  # ảnh sản phẩm của bộ kết hợp: giữ đúng bao bì, nhãn
                    if len(out["refs"]) < budget:
                        out["refs"].append({"path": im["path"], "role": "product photo",
                                            "prompt": "keep this exact product — packaging, logo, label text, colors "
                                                      "and proportions identical"})
            except Exception:
                self._log(f"Không còn bộ kết hợp “{o['cast_combo']}” — bỏ qua", "warn")
        per_char = 2 if len(chars) == 1 else 1
        for cid in chars:
            try:
                item, paths = self.cast.references("character", cid, min(per_char, max(0, budget - len(out["refs"]))))
            except Exception:  # nhân vật đã xoá
                self._log(f"Không còn nhân vật “{cid}” — bỏ qua", "warn")
                continue
            out["characters"].append(item)
            out["refs"] += [{"path": str(p), "role": f"character reference — {item['name']}",
                             "prompt": "this is the exact person: keep face, hair, body type and outfit identical"} for p in paths]
        if layout:
            try:
                item, paths = self.cast.references("layout", layout, min(1, max(0, budget - len(out["refs"]))))
                out["layout"] = item
                out["refs"] += [{"path": str(p), "role": "layout / setting reference",
                                 "prompt": "use this exact location, props, composition and lighting as the setting"}
                                for p in paths]
            except Exception:
                self._log(f"Không còn layout “{layout}” — bỏ qua", "warn")
        ui = ((out["layout"] or {}).get("ui") or {}).get("elements") or []
        if ui and budget and {"text", "logos"} & set(o.get("bans", ["text", "logos"])):
            self._log("Layout có giao diện mạng xã hội (chữ, icon) nhưng Ràng buộc prompt đang cấm chữ / logo — "
                      "bỏ tick “Không chữ” / “Không logo” ở ⚙ nếu muốn giữ giao diện", "warn")
        return out

    def _frame_prompt(self, bible: dict, sc: dict, has_refs: bool, options: dict, logo: bool = False,
                      cast: dict | None = None) -> str:
        cast = cast or {}
        chars = "; ".join(f"{c['name']}: {c.get('description') or c.get('summary') or ''}" for c in cast.get("characters") or [])
        layout = cast.get("layout")
        roster = bible.get("characters") or []
        names_in = sc.get("cast") if isinstance(sc.get("cast"), list) else [c["name"] for c in roster]
        in_scene = [c for c in roster if c["name"] in names_in]
        fixed_names = {c["name"].lower() for c in cast.get("characters") or []}
        extra = [c for c in in_scene if c["name"].lower() not in fixed_names]  # vai phụ (không có ảnh tham chiếu)
        fixed_people = bool(chars or cast.get("combo") or in_scene)
        lock_outfit = options.get("lock_outfit", True)
        locked = fixed_people or bool(layout)
        return "\n".join(x for x in (
            f"{ASPECTS.get(options.get('aspect') or '9:16', ASPECTS['9:16'])[2]} cinematic frame, scene {sc['index']} "
            "of a story video.",
            f"Visual style: {bible.get('phong_cach')}" if bible.get("phong_cach") else "",
            # có nhân vật / bối cảnh cố định: mô tả riêng của cảnh đặt TRƯỚC, ràng buộc cố định đặt SAU để thắng
            # các chi tiết trái ngược (quần áo, nơi chốn) do storyboard viết
            f"Scene action: {strip_outfit(sc['image_prompt']) if fixed_people and lock_outfit else sc['image_prompt']}"
            if locked else "",
            (f"Fixed characters (keep exactly as their reference images, identical in every scene): {chars}" if chars else
             character_sheet(in_scene, lock_outfit=lock_outfit) if in_scene else "" if roster else
             f"Characters (keep exactly the same in every scene): {bible.get('nhan_vat')}" if bible.get("nhan_vat") else ""),
            character_sheet(extra, "Other characters in this scene (same face and age in every scene)", lock_outfit)
            if chars and extra else "",
            f"Product / key props: {bible.get('nhan_vat')}" if roster and bible.get("nhan_vat") and not chars else "",
            (f"Fixed setting — match the layout reference image (same location, props, composition and lighting; camera "
             f"distance may change): {layout.get('description') or layout.get('summary') or ''}") if layout else "",
            ("Keep the social-media UI overlay from the layout reference (same elements, positions and texts) on top of "
             "the scene.") if layout and ((layout.get("ui") or {}).get("elements")) else "",
            (f"Scene reference: {cast['combo'].get('description') or cast['combo'].get('summary') or ''}"
             if cast.get("combo") else ""),
            "" if locked else sc["image_prompt"],
            framing(sc, options),
            ("IDENTITY LOCK: every character is the SAME person as in their reference image / character description — identical face "
             "(face shape, eyes, nose, mouth, eyebrows), skin tone, body type, personal style (makeup, look, vibe) and "
             "the SAME apparent age. Do not make anyone younger, older, slimmer or prettier, do not beautify, "
             "stylise or swap faces, and ignore any age or facial description in the scene action that conflicts.")
            if fixed_people else "",
            ("OUTFIT LOCK: every character wears EXACTLY the same clothes, accessories and hairstyle as in their "
             "reference image / outfit description — same garment types, colours and patterns. Do not change, add or remove any clothing, even "
             "if the scene action mentions other clothes.") if fixed_people and lock_outfit else
            ("OUTFIT: clothes follow the scene action (may differ from the reference image) — but the FACE, hair and "
             "identity stay exactly as the reference.") if fixed_people else "",
            ("SETTING LOCK: the scene happens in EXACTLY the location of the setting / scene reference image — same "
             "background, furniture, props, colours and lighting; only the camera angle and distance may change. Ignore "
             "any other location mentioned in the scene action.") if layout else "",
            ("PRODUCT LOCK: the product looks 100% identical to the attached product reference — same shape, cap / lid, "
             "label, colours and logo; never redraw, invent or warp the label text; show it at a medium distance (no "
             "extreme close-up on small label text). Keep faces and outfits identical to their references.")
            if has_refs else "",
            ("The LAST attached image is the brand logo: reproduce it exactly — same shape, colours and lettering, never "
             "distorted or redrawn — only where a brand logo naturally appears in this scene (product packaging, signage, "
             "uniform). Do not invent any other logo.") if logo else "",
            negative_line(options)) if x)

    def _scenes_whiteboard(self, pid: str, indexes: list, what: str) -> None:
        """Kiểu dựng cảnh Whiteboard: đọc lời dẫn (lấy mốc từng câu) → ảnh line-art nền giấy (hàng đợi Tạo hình ảnh,
        song song) → tay vẽ lần lượt từng vùng đúng lúc câu được đọc (srt-whiteboard-animation, chạy trên máy)."""
        from .pipeline import whiteboard as wbm
        from .pipeline.subtitles import _lines

        p = self.store.load(pid)
        o, pdir = p["options"], self.store.dir(pid)
        targets = [s for s in p["scenes"] if not indexes or s["index"] in indexes]
        has = lambda s, k: bool(s.get(k)) and (pdir / s[k]).is_file()  # noqa: E731
        spec = IMAGE_ENGINES[o["image_engine"]]
        wbm.ensure_installed(self._log)
        plans, frame_tasks, errors = {}, {}, []
        try:
            for sc in targets:  # 1) mốc thời gian từng câu (giọng đọc giống lúc ghép) + ảnh line-art
                need_frame = not (what == "clip" or (has(sc, "frame") and not (indexes and what in ("both", "frame"))))
                need_clip = what != "frame" and (need_frame or not has(sc, "clip") or bool(indexes and what in ("both", "clip")))
                if not (need_frame or need_clip):
                    continue
                sdir = pdir / "scenes" / scene_dir_name(sc["index"])
                sdir.mkdir(parents=True, exist_ok=True)
                if (sc.get("narration") or "").strip():
                    voice, rate, pitch = role_voice(sc.get("speaker", ""), o["voice"], o["rate"])
                    words = synthesize(sc["narration"], voice, rate, sdir / "wb_voice.mp3", pitch=pitch)
                    dur = ffmpeg.media_duration(sdir / "wb_voice.mp3") + 0.8
                    lines = [{"start": ln[0]["start"] + VOICE_LEAD, "end": ln[-1]["end"] + VOICE_LEAD,
                              "text": " ".join(w["text"] for w in ln)} for ln in _lines(words)]
                else:  # cảnh không lời: vẽ theo tiêu đề
                    dur = min(float(sc.get("seconds") or 6), SILENT_MAX)
                    lines = [{"start": 0.3, "end": dur - 0.3, "text": sc.get("title") or sc.get("image_prompt", "")[:80]}]
                plans[sc["index"]] = {"groups": wbm.regions_for(lines), "duration": dur, "clip": need_clip}
                if need_frame:
                    frame_tasks[sc["index"]] = self.images.start({
                        "engine": o["image_engine"], "aspect": o["aspect"], "count": 1, "quality": "high",
                        "prompt": wbm.line_art_prompt(plans[sc["index"]]["groups"], aspect=o["aspect"],
                                                      hint=sc.get("image_prompt", "")[:400]),
                        "show_browser": bool(o.get("show_browser")), "browser_profile": o.get("image_profile", "")})
                    self._scene_update(pid, sc["index"], status="frame_running", error="")
            if frame_tasks:
                self._log(f"Whiteboard: đã giao {len(frame_tasks)} ảnh line-art cho Tạo hình ảnh ({spec['name']})")
            for k, (idx, plan) in enumerate(plans.items(), 1):  # 2) chờ ảnh → dựng tay vẽ từng cảnh
                sdir = pdir / "scenes" / scene_dir_name(idx)
                try:
                    if idx in frame_tasks:
                        self.pool.progress(5 + 60 * (k - 1) / len(plans), f"Đang chờ ảnh line-art cảnh {idx}", "frame")
                        result = self._wait(self.images, frame_tasks[idx], f"Ảnh cảnh {idx}")
                        src = Path(self.settings.output_dir) / IMAGES_DIR / result["id"] / result["files"][0]["name"]
                        dest = sdir / f"frame{src.suffix.lower()}"
                        shutil.copy2(src, dest)
                        self._scene_update(pid, idx, frame=dest.relative_to(pdir).as_posix(), clip="", status="frame")
                    if not plan["clip"]:
                        continue
                    frame = next((s["frame"] for s in self.store.load(pid)["scenes"] if s["index"] == idx), "")
                    if not frame or not (pdir / frame).is_file():
                        raise StudioError("chưa có ảnh line-art")
                    self.pool.progress(5 + 60 * (k - 0.5) / len(plans), f"Đang dựng tay vẽ cảnh {idx} ({k}/{len(plans)})", "clip")
                    self._scene_update(pid, idx, status="clip_running", error="")
                    clip = wbm.render_scene(pdir / frame, plan["groups"], plan["duration"], sdir / "clip.mp4",
                                            check_cancel=self.pool.check_cancel, quality=o.get("wb_quality", "fast"),
                                            hand=o.get("wb_hand", True))
                    self._scene_update(pid, idx, clip=clip.relative_to(pdir).as_posix(), status="done")
                    self._log(f"Xong cảnh {idx} (whiteboard {plan['duration']:.1f}s, {len(plan['groups'])} vùng)", "ok")
                except (StudioError, OSError, wbm.WhiteboardError) as exc:
                    errors.append(f"cảnh {idx}: {exc}")
                    self._scene_update(pid, idx, status="error", error=str(exc)[:300])
        except Cancelled:
            for task_id in frame_tasks.values():
                self.images.cancel(task_id)
            raise
        if errors:
            raise StudioError(f"{len(errors)} cảnh lỗi — bấm làm lại từng cảnh: " + "; ".join(errors[:3]))

    def _scenes(self, pid: str, indexes: list, what: str) -> None:
        p = self.store.load(pid)
        if p["options"].get("scene_style") == "whiteboard":
            return self._scenes_whiteboard(pid, indexes, what)
        o, bible, pdir = p["options"], p.get("bible") or {}, self.store.dir(pid)
        targets = [s for s in p["scenes"] if not indexes or s["index"] in indexes]
        has = lambda s, k: bool(s.get(k)) and (pdir / s[k]).is_file()  # noqa: E731
        spec = IMAGE_ENGINES[o["image_engine"]]
        logo = project_logo(p)
        if logo and spec["max_images"] < 1:
            self._log(f"{spec['name']} không nhận ảnh tham chiếu — không gửi logo được", "warn")
            logo = None
        # thứ tự ảnh gửi model: ảnh dự án → nhân vật / layout cố định → logo (logo luôn CUỐI)
        cast = self._cast(o, spec["max_images"] - (1 if logo else 0))
        master = master_path(p)
        if master is not None and frame_mode(o) == "ai" and spec["max_images"] >= 1:
            # AI tạo khung mới: ảnh tổng hợp ⓪ là tham chiếu CHÍNH (đứng đầu), bớt ảnh rời cho vừa giới hạn của model
            budget = spec["max_images"] - (1 if logo else 0)
            cast["refs"] = ([{"path": str(master), "role": "scene reference (the complete key visual: these people with "
                                                            "this product in this setting)",
                              "prompt": "keep the people, outfits, product and setting consistent with it"}]
                            + cast["refs"])[:max(1, budget)]
        refs = [r for r in p.get("refs") or [] if Path(r).is_file()][
            :max(0, spec["max_images"] - (1 if logo else 0) - len(cast["refs"]))]
        if cast["characters"] or cast["layout"]:
            used = ([f"nhân vật {', '.join(c['name'] for c in cast['characters'])}"] if cast["characters"] else []) + (
                [f"layout {cast['layout']['name']}"] if cast["layout"] else [])  # chỉ đọc layout khi có (tránh None)
            self._log("Dùng " + " · ".join(used) + f" ({len(cast['refs'])} ảnh tham chiếu)")
        keep = self._keep_base(o, p)  # giữ nguyên layout: sửa ảnh layout ⭐ — chỉ thay sản phẩm + chữ trên giao diện
        if frame_mode(o) == "keep":
            if keep["base"] is None:
                self._log("Giữ nguyên layout: layout / bộ kết hợp chưa có ảnh ⭐ — model ảnh tạo khung đầu mới", "warn")
            else:
                parts = [x for x in (
                    f"đặt nhân vật {', '.join(c['name'] for c in keep['chars'])}" if keep["chars"] else "",
                    f"{len(keep['products'])} ảnh sản phẩm" if keep["products"] else "",
                    "chữ trên giao diện" if (keep["ui"] or {}).get("elements") else "") if x]
                self._log(f"Giữ nguyên layout “{(keep['layout'] or {}).get('name', 'bộ kết hợp')}” — chỉ thay "
                          + " + ".join(parts) if parts else
                          "Giữ nguyên layout — chưa có nhân vật / ảnh sản phẩm / giao diện để thay: dùng nguyên ảnh layout")
                if spec["max_images"] < 1:
                    self._log(f"{spec['name']} không nhận ảnh để sửa — dùng nguyên ảnh layout (không thay sản phẩm)", "warn")
        direct = self._direct_frames(o, p)  # đã chọn nhân vật / bộ kết hợp → ảnh ⭐ làm khung đầu, không tạo ảnh mới
        if direct["all"]:
            self._log(f"Dùng thẳng {len(direct['all'])} ảnh ⭐ ({'bộ kết hợp' if direct['combo'] else 'nhân vật' if direct['chars'] else 'layout'})"
                      " làm khung đầu — không tạo ảnh nhân vật mới (đổi ở ⚙ dự án → Cách tạo khung đầu)")
        frame_tasks, clip_tasks, errors = {}, {}, []
        try:
            for sc in targets:  # 1) ảnh khung đầu (song song)
                if what == "clip" or (has(sc, "frame") and not (indexes and what in ("both", "frame"))):
                    continue
                if keep["base"] is not None:  # giữ layout: sửa ảnh layout (không có gì để đổi → dùng nguyên ảnh)
                    job = self._keep_job(o, keep, sc, spec) if spec["max_images"] >= 1 else None
                    if job is None:
                        self._copy_frame(pid, pdir, sc, keep["base"])
                        continue
                    frame_tasks[sc["index"]] = self.images.start(job)
                    self._scene_update(pid, sc["index"], status="frame_running", error="")
                    continue
                pick = self._pick_direct(direct, sc, sc.get("frame_src", "") if indexes else "") if direct["all"] else None
                if pick is not None:  # khung đầu = ảnh ⭐ có sẵn (chép vào cảnh, giữ nguyên ảnh gốc)
                    self._copy_frame(pid, pdir, sc, pick)
                    continue
                frame_tasks[sc["index"]] = self.images.start({
                    "engine": o["image_engine"],
                    "prompt": self._frame_prompt(bible, sc, bool(refs), o, bool(logo), cast),
                    "aspect": o["aspect"], "extra_refs": cast["refs"] + ([{"path": str(logo), **LOGO_REF}] if logo else []),
                    "count": 1, "quality": "high", "refs": refs, "show_browser": bool(o.get("show_browser")),
                    "ref_note": o.get("ref_note", True), "ref_prompt": o.get("ref_prompt") or REF_PROMPT,
                    "browser_profile": o.get("image_profile", "")})
                self._scene_update(pid, sc["index"], status="frame_running", error="")
            if frame_tasks:
                self._log(f"Đã giao {len(frame_tasks)} ảnh khung đầu cho Tạo hình ảnh ({spec['name']})")
            for sc in targets:  # 2) ảnh cảnh nào xong → giao clip cảnh đó ngay
                idx = sc["index"]
                if idx in frame_tasks:
                    self.pool.progress(2 + 8 * len(clip_tasks) / max(1, len(targets)), f"Đang chờ ảnh cảnh {idx}", "frame")
                    try:
                        result = self._wait(self.images, frame_tasks[idx], f"Ảnh cảnh {idx}")
                        src = Path(self.settings.output_dir) / IMAGES_DIR / result["id"] / result["files"][0]["name"]
                        sdir = pdir / "scenes" / scene_dir_name(idx)
                        sdir.mkdir(parents=True, exist_ok=True)
                        dest = sdir / f"frame{src.suffix.lower()}"
                        shutil.copy2(src, dest)
                        sc.update(frame=dest.relative_to(pdir).as_posix(), clip="")
                        self._scene_update(pid, idx, frame=sc["frame"], clip="", status="frame")
                    except (StudioError, OSError) as exc:
                        errors.append(str(exc))
                        self._scene_update(pid, idx, status="error", error=str(exc))
                        continue
                if what == "frame" or not has(sc, "frame"):
                    continue
                if has(sc, "clip") and idx not in frame_tasks and not (indexes and what in ("both", "clip")):
                    continue
                sc_refs = clip_refs(cast, str(keep["products"][0]) if keep["products"] else "")
                clip_tasks[idx] = self.videos.start({
                    "template": SCENE_TEMPLATE, "provider": o["video_engine"], "ai_duration": f"{sc['seconds']}s",
                    "ai_aspect": o["aspect"], "ai_resolution": o["quality"],
                    "variables": clip_variables(sc, o, bible, sc_refs, product=bool(keep["products"]),
                                                ui=bool((keep["ui"] or {}).get("elements"))),
                    # khung đầu + (nhân vật / sản phẩm hoặc bối cảnh cố định) → model video giữ đúng người, đồ, cảnh
                    "attachments": {"image": str(pdir / sc["frame"]), **sc_refs},
                    "show_browser": bool(o.get("show_browser")), "browser_profile": o.get("video_profile", "")})
                self._scene_update(pid, idx, status="clip_running", error="")
            if clip_tasks:
                self._log(f"Đã giao {len(clip_tasks)} clip cho Tạo video ({VIDEO_ENGINES[o['video_engine']]['name']})")
                self._parallel_hint(o, len(clip_tasks))
            # 3) chờ clip — clip nào xong trước nhận trước; tiến trình = trung bình % của mọi clip đang tạo song song
            pending, finished = dict(clip_tasks), 0
            while pending:
                self.pool.check_cancel()
                live = {t["id"]: t for t in self.videos.pool.list()}
                for idx, task_id in list(pending.items()):
                    t = live.get(task_id)
                    if t is not None and t["status"] in ("queued", "running"):
                        continue
                    del pending[idx]
                    finished += 1
                    try:
                        result = self._wait(self.videos, task_id, f"Clip cảnh {idx}")
                        dest = pdir / "scenes" / scene_dir_name(idx) / "clip.mp4"
                        shutil.copy2(Path(self.settings.output_dir) / result["id"] / "final.mp4", dest)
                        self._scene_update(pid, idx, clip=dest.relative_to(pdir).as_posix(), status="done")
                        self._log(f"Xong cảnh {idx} ({finished}/{len(clip_tasks)})", "ok")
                    except (StudioError, OSError, RuntimeError) as exc:
                        errors.append(f"cảnh {idx}: {exc}")
                        self._scene_update(pid, idx, status="error", error=str(exc))
                running = [(i, live[t]) for i, t in pending.items() if live.get(t, {}).get("status") == "running"]
                share = (finished + sum(t["pct"] for _, t in running) / 100) / len(clip_tasks)
                detail = ", ".join(f"cảnh {i} {t['pct']:.0f}%" for i, t in running[:4])
                self.pool.progress(10 + 60 * share, f"Clip: {finished}/{len(clip_tasks)} xong"
                                   + (f" · đang tạo {len(running)} ({detail})" if running else "")
                                   + (f" · {len(pending) - len(running)} chờ Chrome rảnh" if len(pending) > len(running) else ""),
                                   "clip")
                if pending:
                    time.sleep(1)
        except Cancelled:
            for task_id in frame_tasks.values():
                self.images.cancel(task_id)
            for task_id in clip_tasks.values():
                self.videos.cancel(task_id)
            raise
        if errors:
            raise StudioError(f"{len(errors)} cảnh lỗi — bấm làm lại từng cảnh: " + "; ".join(errors[:3]))

    # ---- 3. ghép
    def _post_ai(self, pid: str, p: dict, o: dict, job: dict, strict: bool = False, fresh: bool = False) -> dict:
        """Hậu kỳ AI: nhờ model chat chọn từ khoá + hiệu ứng âm thanh + hook. Lỗi → ghép bình thường (không hỏng video).
        Gợi ý được lưu trong dự án; Ghép lại với lời dẫn + model như cũ thì dùng lại, không hỏi model nữa."""
        subs, audio = o.get("post_subs", True), o.get("post_audio", True)
        if subs and not o.get("subtitles"):
            self._log("Hậu kỳ AI: phụ đề đang tắt — chỉ làm phần âm thanh", "warn")
            subs = False
        if not (subs or audio):
            if strict:
                raise StudioError("Hậu kỳ AI không có việc gì: bật “Phụ đề” + “Phụ đề nổi bật”, hoặc “Âm thanh nổi bật” (⚙)")
            return {}
        scenes = job["scenes"]
        offsets = [sum(s["duration"] for s in scenes[:k]) for k in range(len(scenes))]
        sig = hashlib.sha1(json.dumps([o["post_model"], [(s["index"], s["narration"]) for s in scenes]],
                                      ensure_ascii=False).encode("utf-8")).hexdigest()
        cached = p.get("post_plan") or {}
        if not fresh and cached.get("sig") == sig and isinstance(cached.get("data"), dict):
            data = cached["data"]
            self._log("Hậu kỳ AI: lời dẫn không đổi — dùng lại gợi ý lần trước")
        else:
            self.pool.progress(77, "Hậu kỳ AI: đang nhờ model chọn từ khoá + hiệu ứng", "ai")
            try:
                text = self._ask({**o, "model": o["post_model"], "text_profile": o.get("post_profile", "")},
                                 post_ai.build_prompt(scenes), complete=post_ai.complete,
                                 what="chọn từ khoá nổi bật + hiệu ứng âm thanh (hậu kỳ AI)")
                data = extract_json(text)
                if not isinstance(data, dict):
                    raise ValueError("không phải JSON object")
            except Cancelled:
                raise
            except Exception as exc:  # model lỗi / chưa đăng nhập / JSON sai → vẫn ra video như bình thường
                if strict:  # người dùng bấm chạy hậu kỳ → báo lỗi, không ghép lại vô ích
                    raise StudioError(f"Hậu kỳ AI lỗi: {exc} — kiểm tra đăng nhập / profile của model hậu kỳ") from exc
                self._log(f"Hậu kỳ AI bị bỏ qua ({exc}) — ghép bình thường", "warn")
                return {}
            self._set(pid, post_plan={"sig": sig, "data": data, "at": now()})
        return post_ai.apply_plan(data, scenes, offsets, float(job.get("voice_lead", VOICE_LEAD)),
                                  subs=subs, audio=audio, log=self._log)

    def _hyperframes(self, pid: str, o: dict, job: dict, job_dir: Path, *, show_captions: bool, fresh: bool) -> dict:
        """Hậu kỳ HyperFrames: model (mặc định Claude trình duyệt) viết CSS + HTML + GSAP cho lớp đồ hoạ động, app kiểm tra
        (lint, sửa 1 lần) rồi dựng trên máy với final.mp4 làm nền. Thiết kế lưu trong dự án — Ghép lại dùng lại."""
        from .pipeline import hyperframes as hfm

        hfm.ensure_installed(self._log)
        p = self.store.load(pid)
        captions, scenes = hfm.timeline_data(job["scenes"], float(job.get("voice_lead", VOICE_LEAD)))
        if not show_captions:
            captions = []
        logo = project_logo(p)
        hook = job.get("subtitle_hook", "")
        width, height, duration = job["width"], job["height"], float(job["duration"])
        sig = hashlib.sha1(json.dumps([o["post_model"], captions, scenes, hook, bool(logo)], ensure_ascii=False)
                           .encode("utf-8")).hexdigest()
        folder = job_dir / "hyperframes"
        ask = {**o, "model": o["post_model"], "text_profile": o.get("post_profile", "")}
        complete = lambda t: isinstance(extract_json(t), dict) and "js" in extract_json(t)  # noqa: E731
        layout = dict(captions=captions, scenes=scenes, width=width, height=height, duration=duration, logo=logo)
        cached = ((p.get("post_plan") or {}).get("hf") or {})
        if not fresh and cached.get("sig") == sig and isinstance(cached.get("design"), dict):
            design = cached["design"]
            self._log("HyperFrames: lời dẫn không đổi — dùng lại thiết kế đồ hoạ lần trước")
            hfm.write_project(folder, job_dir / "final.mp4", design, **layout)
        else:
            prompt = hfm.build_prompt(scenes, captions, width=width, height=height, duration=duration, hook=hook,
                                      logo=bool(logo), brand=p.get("name", ""))
            self.pool.progress(84, "HyperFrames: đang nhờ model thiết kế đồ hoạ động", "ai")
            design = hfm.parse_design(extract_json(self._ask(ask, prompt, complete=complete,
                                                             what="thiết kế đồ hoạ động HyperFrames")))
            hfm.write_project(folder, job_dir / "final.mp4", design, **layout)
            errors = hfm.lint(folder)
            if errors:  # mỗi lần hỏi là 1 cuộc chat mới → gửi lại đề + bản trước + lỗi
                self._log(f"HyperFrames: thiết kế có {len(errors)} lỗi — nhờ model sửa", "warn")
                retry = (prompt + "\n\nBản trước của bạn:\n```json\n" + json.dumps(design, ensure_ascii=False)
                         + "\n```\n\n" + hfm.fix_prompt(errors))
                design = hfm.parse_design(extract_json(self._ask(ask, retry, complete=complete,
                                                                 what="sửa thiết kế HyperFrames")))
                hfm.write_project(folder, job_dir / "final.mp4", design, **layout)
                errors = hfm.lint(folder)
                if errors:
                    raise hfm.HyperFramesError("thiết kế vẫn lỗi: " + "; ".join(errors[:3]))
            self.store.update(pid, lambda x: x.setdefault("post_plan", {}).update(
                hf={"sig": sig, "design": design, "at": now()}))
        minutes = max(1, round(duration * 3 / 60))
        self.pool.progress(88, f"Đang dựng đồ hoạ động HyperFrames (~{minutes} phút)", "post")
        self._log(f"HyperFrames: đang dựng {duration:.0f} giây video trên máy (~{minutes} phút)…")
        started = time.time()
        out = hfm.render(folder, folder / "render.mp4", fps=int(job.get("fps") or FPS), check_cancel=self.pool.check_cancel)
        out.replace(job_dir / "final.mp4")
        if self.settings.get("cleanup_temp"):
            shutil.rmtree(folder, ignore_errors=True)
        self._log(f"HyperFrames: xong sau {time.time() - started:.0f} giây · {len(captions)} dòng phụ đề động", "ok")
        return {"captions": len(captions), "at": now()}

    def _assemble(self, pid: str, post: str = "", fresh: bool = False) -> None:
        """post: "" = theo tuỳ chọn dự án (lỗi hậu kỳ → ghép thường) | "strict" = bấm chạy hậu kỳ (lỗi → báo lỗi)."""
        p = self.store.load(pid)
        # dự án cũ (tạo trước khi có chuyển cảnh / ràng buộc prompt…) thiếu khoá → điền mặc định, tránh KeyError khi ghép
        o, pdir = self._clean(p["options"]), self.store.dir(pid)
        missing = [s["index"] for s in p["scenes"] if not s.get("clip") or not (pdir / s["clip"]).is_file()]
        if missing:
            raise StudioError(f"Cảnh {', '.join(map(str, missing))} chưa có clip — làm cảnh trước khi ghép")
        created = datetime.now()
        job_dir = unique_dir(Path(self.settings.output_dir) / f"{slugify(p['name'])}_{created:%Y%m%d_%H%M%S}")
        scenes, total = [], len(p["scenes"])
        width, height = frame_size(o)
        keep = self._keep_base(o, p)  # giữ layout có khung bình luận → app vẽ bình luận chạy lên từng cảnh
        chat = self._chat_by_app(o, keep)
        live = o.get("live") or {}
        live_assets, live_t0, live_prev = (self._live_assets(o, p) if live.get("on") else ("", "")), 0.0, []
        live_pool = [c for c in (live.get("comments") or "").splitlines() if c.strip()]
        if live.get("on"):
            self._log("📱 Mô phỏng livestream TikTok: app vẽ giao diện live (bình luận, tim, giỏ hàng…) lên từng cảnh")
        voices = voice_map((p.get("bible") or {}).get("characters") or [], o)  # giọng riêng từng nhân vật
        dub = o.get("dub", True) or o.get("scene_style") == "whiteboard"  # whiteboard không có tiếng gốc
        if not dub:
            self._log("Không lồng tiếng AI — dùng giọng nói / âm thanh gốc của từng clip")
        for k, sc in enumerate(p["scenes"], 1):
            self.pool.check_cancel()
            self.pool.progress(72 + 8 * (k - 1) / total, f"Ghép: đang chuẩn bị cảnh {k}/{total}", "post")
            sdir = job_dir / "scenes" / scene_dir_name(k)
            sdir.mkdir(parents=True)
            voice = sdir / "voice.mp3"
            words, vdur = [], 0.0
            clip = pdir / sc["clip"]
            clip_dur = ffmpeg.media_duration(clip)
            if not dub:  # tiếng gốc: giữ nguyên tốc độ clip (tua sẽ méo giọng), cắt tiếng theo đúng thời lượng
                duration, speed = clip_dur, 1.0
                extract_audio(clip, 0.0, duration, voice)
                vdur = duration
            elif any(ln.get("text") for ln in sc.get("lines") or []):  # nhiều câu thoại → mỗi câu giọng nhân vật nói
                narrator = role_voice(sc.get("speaker", ""), o["voice"], o["rate"])
                words = synthesize_lines([(ln["text"], *(voices.get(ln.get("who")) or narrator))
                                          for ln in sc["lines"] if ln.get("text")], voice)
                vdur = ffmpeg.media_duration(voice)
            elif sc.get("narration"):
                tts_voice, rate, pitch = role_voice(sc.get("speaker", ""), o["voice"], o["rate"])
                words = synthesize(sc["narration"], tts_voice, rate, voice, pitch=pitch)
                vdur = ffmpeg.media_duration(voice)
            else:  # cảnh chỉ có hình → giọng đọc rỗng (compose cần đủ file mỗi cảnh)
                ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.3", "-q:a", "9", voice])
            if dub:
                duration, speed = fit_clip(clip_dur, vdur)  # giữ trọn chuyển động, tua nhẹ cho khớp lời đọc
            pad = max(0.0, duration - clip_dur / speed) + 0.5  # thiếu hình (clip quá ngắn) → giữ khung cuối
            ffmpeg.run(["-i", clip, "-vf", ",".join([  # chuyển cảnh giữa các cảnh do compose() làm (xfade)
                f"setpts=PTS/{speed}",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1",
                f"fps={FPS}", f"tpad=stop_mode=clone:stop_duration={pad:.2f}", "format=yuv420p"]),
                "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                sdir / "scene.mp4"])
            if live.get("on"):  # giao diện livestream do app vẽ — liền mạch giữa các cảnh (tim, bình luận cũ trôi tiếp)
                ov = sc.get("overlay") or {}
                comments = list(ov.get("comments") or [])
                if not comments and live_pool:  # cảnh chưa có bình luận → lấy lần lượt từ danh sách bình luận của live
                    start = (k - 1) * 3 % len(live_pool)
                    comments = (live_pool[start:] + live_pool[:start])[:4]
                if not comments:
                    comments = self._keep_texts(keep, sc).get("comments") or []
                live_sim.burn(sdir / "scene.mp4", live, comments, duration, caption=ov.get("caption", ""),
                              seed=f"{pid}-live", t0=live_t0, history=live_prev, avatar=live_assets[0],
                              product=live_assets[1])
                live_t0 += duration
                live_prev = (live_prev + live_chat.clean_comments(comments))[-5:]
            elif chat:  # bình luận livestream do app vẽ (font tiếng Việt, hiện lần lượt) — không để model vẽ chữ
                texts = self._keep_texts(keep, sc)
                if live_chat.burn(sdir / "scene.mp4", texts.get("comments") or [], duration, sdir / "chat",
                                  caption=texts.get("caption", ""), seed=f"{pid}-{k}"):
                    self._log(f"Cảnh {k}: thêm {len(live_chat.clean_comments(texts.get('comments')))} bình luận livestream")
            ffmpeg.run(["-i", sdir / "scene.mp4", "-frames:v", "1", "-q:v", "3", sdir / "thumb.jpg"])
            scenes.append({"index": k, "kicker": "", "headline": sc["title"], "narration": sc.get("narration", ""),
                           "words": words, "voice_duration": vdur, "duration": duration})
            shown = min(clip_dur, duration * speed)
            self._log(f"Cảnh {k}: {duration:.1f}s" + (" · tiếng gốc" if not dub else f" · giọng {vdur:.1f}s" if vdur else " · không lời")
                      + (f" · clip {clip_dur:.1f}s ×{speed:g}" if speed != 1 else f" · clip {clip_dur:.1f}s")
                      + (f" · bỏ {clip_dur - shown:.1f}s cuối" if clip_dur - shown > 0.3 else ""))
        job = {"id": job_dir.name, "kind": "studio", "title": p["name"], "topic": p["idea"][:500], "genre": "studio",
               "template_id": "studio", "template_name": "Studio", "aspect": o["aspect"], "width": width, "height": height,
               "fps": FPS, "voice": o["voice"], "subtitles": o["subtitles"], "bgm": o["bgm"],
               "bgm_volume": self.settings.get("bgm_volume") or 0.12, "created_at": created.isoformat(timespec="seconds"),
               "duration": round(sum(s["duration"] for s in scenes), 3), "scenes": scenes, "studio": pid,
               **{k: o[k] for k in ("transition", "transition_duration", "transition_sound", "transition_volume")}}
        if not o.get("transition_on", True):  # tắt chuyển cảnh: nối thẳng, không âm (lựa chọn cũ vẫn giữ để bật lại)
            job.update(transition="none", transition_sound="none")
        if not dub:  # tiếng gốc bắt đầu ngay đầu cảnh; nhạc nền nhỏ lại để không lấn giọng nói gốc
            job.update(voice_lead=0.0, original_audio=True, bgm_volume=round(job["bgm_volume"] * 0.6, 3))
        self._log("Chuyển cảnh: tắt — các cảnh nối thẳng" if not o.get("transition_on", True) else
                  f"Chuyển cảnh: {transitions.TRANSITIONS[o['transition']][0]} {o['transition_duration']:g}s · "
                  f"âm: {transitions.SOUNDS[o['transition_sound']][0]}")
        post_info = {}
        if o.get("post_ai") or post:
            extra = self._post_ai(pid, p, o, job, strict=post == "strict", fresh=fresh)
            job.update(extra)
            if extra:  # tóm tắt hiện ở thẻ Video hoàn chỉnh
                post_info = {"model": o["post_model"], "hook": extra.get("subtitle_hook", ""),
                             "words": sum(len(s.get("highlight") or []) for s in job["scenes"]),
                             "cues": len(extra.get("sfx_cues") or []), "at": now()}
        # kiểu hậu kỳ HyperFrames: ghép video KHÔNG phụ đề ASS → model thiết kế lớp đồ hoạ động → dựng trên máy
        hf = (o.get("post_ai") or post) and o.get("post_style") == "hyperframes" and bool(post_info)
        subtitles = job["subtitles"]
        if hf:
            job["subtitles"] = False
        self.pool.progress(80, "Đang ghép giọng đọc, phụ đề, nhạc nền", "post")
        compose(job_dir, job, log=self._log, check_cancel=self.pool.check_cancel,
                music_dir=self.settings.get("music_dir") or "", cleanup=bool(self.settings.get("cleanup_temp")))
        if hf:
            try:
                post_info["hyperframes"] = self._hyperframes(pid, o, job, job_dir, show_captions=subtitles, fresh=fresh)
            except (Cancelled, StudioError):
                raise
            except Exception as exc:  # HyperFrames lỗi → phụ đề nổi bật thường (ASS), video vẫn ra
                if post == "strict":
                    raise StudioError(f"Hậu kỳ HyperFrames lỗi: {exc}") from exc
                self._log(f"HyperFrames lỗi ({exc}) — dùng phụ đề nổi bật thường", "warn")
                job["subtitles"] = subtitles
                compose(job_dir, job, log=self._log, check_cancel=self.pool.check_cancel,
                        music_dir=self.settings.get("music_dir") or "", cleanup=bool(self.settings.get("cleanup_temp")))
            job["subtitles"] = subtitles
        # đóng logo thật lên góc video (hậu kỳ) — không phụ thuộc "Không logo" (lệnh cấm đó chỉ dành cho model ảnh)
        logo = Path(p["logo"]) if p.get("logo") and Path(p["logo"]).is_file() else None
        if logo and o.get("logo_overlay", "none") != "none":
            self.pool.progress(96, "Đang đóng logo lên video", "post")
            stamp_logo(job_dir / "final.mp4", logo, o["logo_overlay"])
            self._log(f"Đã đóng logo · {LOGO_CORNERS[o['logo_overlay']].lower()}")
        save_job(job_dir, job)
        self._set(pid, final={"job_id": job_dir.name, "duration": job["duration"], "at": now(), "post": post_info})
        self._log(f"Đã xong video {job['duration']:.0f} giây — có trong Thư viện video", "ok")
        self.pool.progress(100, "Hoàn tất", "finish")
