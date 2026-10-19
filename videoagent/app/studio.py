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
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .browser_profiles import task_context
from .image_library import IMAGES_DIR
from .library import save_job
from .llm.base import LLMError, extract_json
from .pipeline import ref_video as rvm
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.video_engines import ENGINES as VIDEO_ENGINES
from .pipeline import SCENE_TAIL, VOICE_LEAD, Cancelled, scene_dir_name
from .pipeline import post_ai, transitions
from .pipeline.assets import extract_audio
from .pipeline.composer import compose
from .pipeline.tasks import TaskPool
from .pipeline.tts import RATES, ROLES, VOICES, role_voice, synthesize, synthesize_lines
from .util import read_json, slugify, unique_dir, write_json

STUDIO_DIR = "_studio"
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


def character_sheet(chars: list[dict], title: str = "Characters in this scene — the SAME people in every scene "
                                                    "(same face, age, hairstyle and outfit)") -> str:
    return "\n".join([title + ":"] + [f"- {c['name']}: {c['look'].rstrip('. ')}." + (f" Outfit (never changes): {c['outfit']}"
                                                                        if c.get("outfit") else "") for c in chars])


POLISH_PROMPT = """Bạn là đạo diễn hình ảnh. Viết lại "prompt_anh" và "prompt_chuyen_dong" của từng cảnh dưới đây cho CHI TIẾT,
CHUYÊN NGHIỆP hơn để model tạo ảnh / video ra hình đẹp, đúng ý — giữ nguyên nội dung câu chuyện của từng cảnh.
Video: {aspect}. Phong cách chung: {style}
Nhân vật (đã có hồ sơ cố định, app tự chèn khuôn mặt + trang phục — KHÔNG tả lại): {names}

Quy tắc:
- "prompt_anh" (tiếng Anh, 60–110 từ) theo thứ tự: cỡ cảnh + góc máy → nhân vật (gọi đúng TÊN) đang làm gì, tư thế, biểu cảm
  → bố cục, tiền cảnh / hậu cảnh, đạo cụ, chi tiết bối cảnh → ánh sáng, thời điểm trong ngày → ống kính, độ sâu trường ảnh
  → không khí, tông màu. KHÔNG tả khuôn mặt, tuổi, tóc, quần áo; KHÔNG chữ, logo, watermark trên hình.
- "prompt_chuyen_dong" (tiếng Anh, 25–50 từ): MỘT hành động chính rõ ràng của nhân vật + chuyển động máy (dolly in, pan,
  tracking, crane, static…) + nhịp độ; vừa với số giây của cảnh; không cắt cảnh.
- Không thêm nhân vật mới, không đổi bối cảnh đã có, không đổi thứ tự cảnh.
- Trong chuỗi JSON KHÔNG dùng dấu ngoặc kép " — dùng ‘ ’ nếu cần.

Các cảnh (JSON):
{scenes}

Chỉ trả về MỘT object JSON: {{"canh":[{{"canh":1,"prompt_anh":"…","prompt_chuyen_dong":"…"}}]}} — đủ {count} cảnh."""
MIN_SCENES, MAX_SCENES = 5, 10
LENGTHS = (30, 45, 60, 75, 90)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SCENE_FIELDS = ("title", "narration", "speaker", "image_prompt", "motion_prompt", "seconds")
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
    def __init__(self, settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        path = Path(self.settings.output_dir) / STUDIO_DIR
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
        return read_json(self.dir(pid) / "project.json")

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
            "auto": bool(raw.get("auto")),
            # video tham khảo (link / file) đã phân tích: dùng khi viết storyboard hay không + cách dùng
            "ref_video_use": bool(raw.get("ref_video_use")),
            "ref_video_mode": raw.get("ref_video_mode") if raw.get("ref_video_mode") in ("inspire", "close") else "inspire",
            # sau khi viết storyboard: model viết lại prompt ảnh / chuyển động từng cảnh chi tiết hơn (thêm 1 lượt hỏi)
            "prompt_polish": bool(raw.get("prompt_polish")),
            # tỉ lệ khung hình (ảnh khung đầu, clip, video ghép) + chất lượng clip model video tạo
            "aspect": raw.get("aspect") if raw.get("aspect") in ASPECTS else "9:16",
            "quality": raw.get("quality") if raw.get("quality") in QUALITIES else "720p",
            # lồng tiếng AI (TTS); tắt → nhân vật nói lời dẫn ngay trong clip, ghép dùng tiếng gốc của clip
            "dub": bool(raw.get("dub", True)),
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
            "cast_combo": str(raw.get("cast_combo") or ""),  # bộ kết hợp nhân vật + layout
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
            "voices": VOICES, "rates": RATES, "speakers": [{"value": k, "label": v[0]} for k, v in ROLES.items()],
            "scenes": [MIN_SCENES, MAX_SCENES], **transitions.options(),
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


def clip_refs(cast: dict) -> dict:
    """Ảnh gửi kèm khung đầu khi tạo clip (template studio-canh): ref1 = nhân vật cố định, ref2 = sản phẩm (ưu tiên)
    hoặc bối cảnh / dàn cảnh. Không dùng nhân vật / layout cố định → {} (chỉ gửi khung đầu như cũ)."""
    refs = (cast or {}).get("refs") or []

    def pick(test, skip=""):
        return next((r["path"] for r in refs if test(r.get("role") or "") and r["path"] != skip
                     and Path(r["path"]).is_file()), "")

    person = pick(lambda r: r.startswith("character reference")) or pick(lambda r: r.startswith("scene reference"))
    other = (pick(lambda r: r == "product photo", person) or pick(lambda r: r.startswith("layout"), person)
             or pick(lambda r: r.startswith("scene reference"), person))
    return {k: v for k, v in (("ref1", person), ("ref2", other)) if v}


def clip_variables(scene: dict, options: dict, bible: dict | None = None) -> dict:
    """Biến cho template cảnh: {MoTa} = chuyển động / máy quay, {LoiThoai} = nhân vật nói đúng "Lời đọc" của cảnh.
    Lồng tiếng AI: nhân vật vẫn mấp máy môi + cử chỉ theo đúng câu (tiếng clip bị thay bằng giọng đọc khi ghép);
    giọng gốc: model video phải nói to rõ đúng nguyên văn câu đó, không nhạc nền. Cảnh không lời → bỏ dòng thoại."""
    motion = " ".join((scene.get("motion_prompt") or scene.get("image_prompt") or "").split())[:700]
    roster = {c["name"]: c for c in (bible or {}).get("characters") or []}
    if options.get("cast_characters") or options.get("cast_layout") or options.get("cast_combo") or roster:
        motion = ("Keep every character exactly as in the first frame — same face, age, skin tone, body type, style, "
                  "outfit and hairstyle (no face change, no ageing, no beautify) — and the same location. " + motion)[:700]
    narration = " ".join((scene.get("narration") or "").split()).replace('"', "'")[:450]
    dub, ban = options.get("dub", True), negative_line(options)
    lines = [ln for ln in scene.get("lines") or [] if ln.get("text")]
    if lines:  # lời thoại nhiều nhân vật: ai nói, cảm xúc, chất giọng
        def label(ln: dict) -> str:
            if not ln.get("who"):
                return "Voice-over narrator (off-screen" + (f", {ln['tone']}" if ln.get("tone") else "") + ")"
            desc = ROLES.get((roster.get(ln["who"]) or {}).get("voice") or "", ROLES[""])[4]
            extra = ", ".join(x for x in (ln.get("tone"), desc) if x)
            return ln["who"] + (f" ({extra})" if extra else "")
        said = "; ".join(f'{label(ln)}: "{ln["text"]}"' for ln in lines)
        if dub:
            line = ("each speaking character lip-syncs their own line with matching facial expression, emotion and "
                    "gestures (voice-over lines are not spoken on screen): " + said)
        else:
            line = ("each character speaks their own line out loud in Vietnamese, word for word, each with a distinct voice "
                    "matching the description, clearly audible and lip-synced, no background music; voice-over narrator "
                    "lines are heard off-screen: " + said)
        return {"MoTa": motion, "LoiThoai": line[:700], "CamKy": ban}
    if not narration:
        return {"MoTa": motion, "LoiThoai": "", "CamKy": ban}
    role = ROLES.get(scene.get("speaker") or "", ROLES[""])[4]
    who = f" with {role}" if role else ""
    if dub:
        line = (f"the on-screen character says exactly this line{who}, with natural lip movements, facial expression "
                f"and gestures matching the words: \"{narration}\"")
    else:
        line = (f"the on-screen character speaks exactly this line out loud{who}, word for word in the original "
                f"language (Vietnamese pronunciation), clearly audible and lip-synced, no background music: \"{narration}\"")
    return {"MoTa": motion, "LoiThoai": line, "CamKy": ban}


def ask_model(settings, options: dict, prompt: str, *, complete=None, what: str = "viết storyboard", log=None,
              check_cancel=None, system: str = "") -> str:
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
            provider.timeout_s = STORYBOARD_TIMEOUT
            log(f"Đang chờ {provider.site.name} {what} (tối đa {STORYBOARD_TIMEOUT // 60} phút)"
                + (" — đang hiện cửa sổ trình duyệt" if options.get("show_browser") else ""))
            return provider.generate(system + "\n\n" + prompt, complete=complete)
        return provider.generate(system + "\n\n" + prompt)


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

    def __init__(self, settings, license_mgr, emit, images, videos) -> None:
        self.settings = settings
        self.license = license_mgr
        self.images, self.videos = images, videos
        self.cast = None  # CastRunner (màn Nhân vật & Layout) — api.py gắn vào
        self._emit = emit
        self.store = Store(settings)
        self.pool = TaskPool("studio_", emit, lambda: settings.get("max_parallel_studio") or 2)
        self._active: dict[str, str] = {}

    # ------------------------------------------------------------ công khai
    def public(self, project: dict) -> dict:
        base = Path(self.settings.output_dir)
        pdir = base / STUDIO_DIR / project["id"]

        def url(rel: str) -> str:
            path = pdir / rel if rel else None
            return f"/media/{STUDIO_DIR}/{project['id']}/{rel}?v={int(path.stat().st_mtime)}" if path and path.is_file() else ""

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
                "final_url": (f"/media/{final['job_id']}/final.mp4?v={int(final_path.stat().st_mtime)}"
                              if final_path and final_path.is_file() else "")}

    def running_ids(self) -> list:
        live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
        return [pid for pid, task in self._active.items() if task in live]

    def _push(self, project: dict) -> None:
        self._emit("studio_update", self.public(project))

    def create(self, form: dict) -> dict:
        idea = str(form.get("idea") or "").strip()
        if len(idea) < 10:
            raise StudioError("Hãy mô tả ý tưởng video (ít nhất 1 câu)")
        options = clean_options(form.get("options") or {}, self.settings)
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
        project = {"id": pid, "name": name, "idea": idea, "created_at": now(), "options": options, "refs": refs,
                   "logo": copy_logo(pdir, form["logo"]) if form.get("logo") else "",
                   "ref_video": rvm.copy_sheet(rvm.clean(form.get("ref_video")), pdir),
                   "bible": {}, "scenes": [], "status": "draft", "error": "", "final": {}}
        self.store.save(project)
        return {"project": self.public(project), "task": self.start(pid, "storyboard")}

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
        options = {**(form.get("options") or {}), "auto": True}
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
            if isinstance(data.get("options"), dict):
                p["options"] = clean_options({**p["options"], **data["options"]}, self.settings)
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
                    sc = {"index": i, **{k: prev.get(k) or "" for k in ("frame", "clip", "status", "error")}}
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
                    if sc["image_prompt"] != prev.get("image_prompt"):
                        sc.update(frame="", clip="", status="")
                    elif speech or sc["motion_prompt"] != prev.get("motion_prompt") or sc["seconds"] != prev.get("seconds"):
                        sc.update(clip="", status="frame" if sc.get("frame") else "")
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
                   "options": clean_options(src.get("options") or {}, self.settings), "refs": refs, "logo": logo,
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
        if action not in ("storyboard", "scenes", "assemble", "make", "post", "polish"):
            raise StudioError("Việc không hợp lệ")
        project = self.store.load(pid)
        if pid in self.running_ids():
            raise StudioError("Dự án đang chạy — chờ xong hoặc bấm Dừng")
        if action != "storyboard" and not project.get("scenes"):
            raise StudioError("Chưa có storyboard — bấm Tạo storyboard trước")
        if action == "post":
            pdir = self.store.dir(pid)
            if any(not s.get("clip") or not (pdir / s["clip"]).is_file() for s in project["scenes"]):
                raise StudioError("Chưa đủ clip các cảnh — bấm ▶ Làm video trước, rồi mới chạy hậu kỳ AI")
            # chạy hậu kỳ chủ động → bật luôn tuỳ chọn (Ghép lại sau này cũng có hậu kỳ)
            project = self.store.update(pid, lambda p: p["options"].update(post_ai=True))
        title = {"storyboard": "Storyboard", "scenes": "Làm cảnh", "assemble": "Ghép video", "make": "Làm video",
                 "post": "Hậu kỳ AI", "polish": "Chuốt prompt"}[action]
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
            if action == "storyboard":
                self._storyboard(pid)
                if self.store.load(pid)["options"].get("prompt_polish"):
                    self._polish(pid, strict=False)
                if self.store.load(pid)["options"].get("auto"):
                    action = "make"  # "Tự làm luôn": storyboard xong → làm cảnh → ghép
            if action == "polish":
                self._polish(pid, strict=True)
            if action in ("scenes", "make"):
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
    def _ask(self, options: dict, prompt: str, complete=None, what: str = "viết storyboard") -> str:
        return ask_model(self.settings, options, prompt, complete=complete, what=what, log=self._log,
                         check_cancel=self.pool.check_cancel)

    def _storyboard(self, pid: str) -> None:
        p = self.store.load(pid)
        o = p["options"]
        self.pool.progress(3, "Đang viết storyboard", "script")
        allowed = video_engine_durations(o["video_engine"])
        count = max(MIN_SCENES, min(MAX_SCENES, round(o["length"] / 8)))
        refs = len(p.get("refs") or [])
        cast = self._cast(o, 0)  # chỉ cần mô tả (ảnh gửi ở bước tạo ảnh khung đầu)
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
        prompt = f"""Viết storyboard cho 1 video {ASPECTS[o['aspect']][3]} dài khoảng {o['length']} giây theo ý tưởng:
<y_tuong>
{p['idea']}
</y_tuong>
{('Phong cách hình ảnh mong muốn: ' + o['style']) if o['style'] else ''}
{(f'Người dùng có {refs} ảnh tham chiếu (nhân vật / sản phẩm) — mô tả nhân vật khớp với ảnh, model ảnh sẽ nhận các ảnh này.') if refs else ''}
{cast_text}
{rvm.storyboard_block(p.get("ref_video"), o.get("ref_video_mode", "inspire")) if o.get("ref_video_use") else ""}
{'PHONG CÁCH: video vẽ tay bảng trắng (whiteboard) — "prompt_anh" mô tả hình minh hoạ đơn giản, rõ ý (đồ vật, người, biểu tượng, sơ đồ), không chữ; mỗi câu lời dẫn là 1 ý vẽ được; "prompt_chuyen_dong" để trống.' if o.get('scene_style') == 'whiteboard' else ''}

YÊU CẦU:
- Đúng {count} cảnh, mạch truyện rõ: mở đầu gây chú ý (3 giây đầu), diễn biến, cao trào, kết + lời kêu gọi (nếu là quảng cáo).
- "nhan_vat_ds": HỒ SƠ NHÂN VẬT (tối đa {MAX_CHARACTERS}) — mỗi người: "ten" (tên ngắn, dùng nhất quán cả bài);
  "ngoai_hinh" (tiếng Anh: giới tính, tuổi cụ thể, dân tộc, khuôn mặt, kiểu + màu tóc, vóc dáng — CỐ ĐỊNH mọi cảnh);
  "trang_phuc" (tiếng Anh: MỘT bộ trang phục cố định — loại áo / quần / váy, màu, chất liệu, giày, phụ kiện);
  "giong" (giọng lồng tiếng, đúng một mã: {', '.join(k for k in ROLES if k)}; mỗi nhân vật một giọng KHÁC nhau, hợp tuổi
  và giới tính — trẻ em girl/boy, thiếu niên teen_f/teen_m, người già old_f/old_m).
  "nhan_vat": mô tả sản phẩm / đạo cụ chính (tiếng Anh, nếu có). "phong_cach": phong cách hình ảnh chung (ánh sáng, màu, ống kính), tiếng Anh.
- Mỗi cảnh: "tieu_de" (tiếng Việt, ngắn); "nhan_vat_canh": tên các nhân vật XUẤT HIỆN trong khung hình ([] nếu không có ai);
  "thoai": lời thoại / lời dẫn của cảnh theo thứ tự — mỗi câu {{"ai": tên nhân vật đang nói, hoặc "dan_chuyen" nếu là lời bình
  bên ngoài; "cau": câu tiếng Việt tự nhiên; "cam_xuc": cảm xúc / giọng điệu ngắn (vd. hào hứng, thì thầm, nghiêm túc)}};
  tổng khoảng 2,5 từ/giây theo số giây của cảnh; cảnh chỉ có hình thì "thoai": [];
  "giong": mã giọng của người dẫn chuyện (narrator_f / narrator_m / mc_f…);
  "prompt_anh" (tiếng Anh) theo công thức: cỡ cảnh + góc máy → nhân vật (gọi bằng TÊN) đang làm gì, tư thế, biểu cảm →
  bố cục, tiền cảnh / hậu cảnh, đạo cụ → ánh sáng, thời điểm → ống kính, độ sâu trường ảnh → không khí, tông màu.
  KHÔNG tả lại khuôn mặt, tuổi, tóc, quần áo (app tự chèn hồ sơ nhân vật); KHÔNG chữ trên hình;
  "prompt_chuyen_dong" (tiếng Anh): MỘT hành động chính của nhân vật + chuyển động máy (dolly in, pan, tracking, static…)
  + nhịp độ, vừa trong số giây của cảnh; "giay": một trong {allowed}.
- Không chữ, logo, watermark trong hình. Không nội dung nhạy cảm.
- Bên trong các chuỗi JSON KHÔNG dùng dấu ngoặc kép " — trích dẫn / tên sản phẩm dùng ‘ ’ hoặc viết thường.

Chỉ trả về MỘT object JSON (không markdown, không giải thích):
{{"nhan_vat_ds":[{{"ten":"…","ngoai_hinh":"…","trang_phuc":"…","giong":"young_f"}}],"nhan_vat":"…","phong_cach":"…","canh":[{{"tieu_de":"…","nhan_vat_canh":["…"],"thoai":[{{"ai":"…","cau":"…","cam_xuc":"…"}}],"giong":"narrator_f","prompt_anh":"…","prompt_chuyen_dong":"…","giay":{allowed[-1]}}}]}}"""
        self._log(f"Đang viết storyboard {count} cảnh (~{o['length']} giây)…")
        data, text = None, ""
        for attempt in (1, 2):
            text = self._ask(o, prompt if attempt == 1 else prompt + "\n\nLẦN TRƯỚC CHƯA NHẬN ĐƯỢC JSON HỢP LỆ — không hỏi lại, "
                             "tự quyết định mọi chi tiết còn thiếu và chỉ trả đúng 1 object JSON.",
                             complete=storyboard_complete)
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
        for i, raw in enumerate(data["canh"][:MAX_SCENES], 1):
            lines = clean_lines(raw.get("thoai"), names)
            on_screen = raw.get("nhan_vat_canh")
            scenes.append({"index": i, "title": str(raw.get("tieu_de") or f"Cảnh {i}")[:120],
                           "narration": (lines_text(lines) or str(raw.get("loi_doc") or "").strip())[:1200],
                           "lines": lines,
                           **({"cast": [n for n in names if n.lower() in {_flat(x, 40).lower() for x in on_screen}]}
                              if isinstance(on_screen, list) and names else {}),
                           "speaker": raw.get("giong") if raw.get("giong") in ROLES else "",
                           "image_prompt": str(raw.get("prompt_anh") or "").strip()[:1500],
                           "motion_prompt": str(raw.get("prompt_chuyen_dong") or "").strip()[:600],
                           "seconds": fit_seconds(o["video_engine"], raw.get("giay")), "frame": "", "clip": "",
                           "status": "", "error": ""})
        bible = {"nhan_vat": str(data.get("nhan_vat") or "")[:1500], "phong_cach": str(data.get("phong_cach") or "")[:600]}
        if cast["characters"]:  # nhân vật cố định: dùng nguyên mô tả đã duyệt, không để model diễn đạt lại
            bible["nhan_vat"] = "; ".join(f"{c['name']}: {c.get('description') or c.get('summary', '')}"
                                          for c in cast["characters"])[:1500]
        if characters:
            bible["characters"] = characters
        self._set(pid, scenes=scenes, bible=bible, final={})
        self._log(f"Storyboard xong: {len(scenes)} cảnh · ~{sum(s['seconds'] for s in scenes)} giây hình"
                  + (f" · {len(characters)} nhân vật: " + ", ".join(
                      f"{c['name']} ({ROLES.get(c['voice'] or '', ROLES[''])[0]})" for c in characters) if characters else ""),
                  "ok")

    def _polish(self, pid: str, strict: bool) -> None:
        """✨ Chuốt prompt: model viết lại prompt ảnh / chuyển động từng cảnh chi tiết hơn (giữ nhân vật, câu chuyện).
        Cảnh đổi prompt ảnh → bỏ ảnh + clip cũ; đổi prompt chuyển động → bỏ clip. strict=False: lỗi chỉ cảnh báo."""
        p = self.store.load(pid)
        o, scenes = p["options"], p.get("scenes") or []
        if not scenes:
            raise StudioError("Chưa có storyboard để chuốt prompt")
        bible = p.get("bible") or {}
        payload = [{"canh": s["index"], "giay": s["seconds"], "tieu_de": s["title"], "nhan_vat": s.get("cast", []),
                    "loi": (s.get("narration") or "")[:240], "prompt_anh": s["image_prompt"],
                    "prompt_chuyen_dong": s["motion_prompt"]} for s in scenes]
        prompt = POLISH_PROMPT.format(aspect=ASPECTS[o["aspect"]][3], style=bible.get("phong_cach") or o.get("style") or "",
                                      names=", ".join(c["name"] for c in bible.get("characters") or []) or "(không có)",
                                      scenes=json.dumps(payload, ensure_ascii=False), count=len(scenes))

        def complete(text: str) -> bool:
            try:
                data = extract_json(text)
            except ValueError:
                return False
            return isinstance(data, dict) and len(data.get("canh") or []) >= len(scenes)

        self.pool.progress(8, "Đang chuốt prompt từng cảnh", "script")
        self._log(f"✨ Đang chuốt prompt {len(scenes)} cảnh…")
        try:
            data = extract_json(self._ask(o, prompt, complete=complete, what="chuốt prompt"))
            items = {int(x.get("canh") or 0): x for x in data.get("canh") or [] if isinstance(x, dict)}
        except (ValueError, StudioError, LLMError, AttributeError, TypeError) as exc:
            if strict:
                raise StudioError(f"Chuốt prompt lỗi: {exc}") from exc
            self._log(f"Chuốt prompt lỗi — giữ prompt cũ: {exc}", "warn")
            return
        changed = 0

        def apply(proj):
            nonlocal changed
            for sc in proj["scenes"]:
                item = items.get(sc["index"]) or {}
                img = _flat(item.get("prompt_anh"), 1500)
                mot = _flat(item.get("prompt_chuyen_dong"), 600)
                if img and img != sc["image_prompt"]:
                    sc.update(image_prompt=img, frame="", clip="", status="")
                    changed += 1
                if mot and mot != sc["motion_prompt"]:
                    sc["motion_prompt"] = mot
                    if sc.get("clip"):
                        sc.update(clip="", status="frame" if sc.get("frame") else "")
            proj["final"] = {}
        self._push(self.store.update(pid, apply))
        self._log(f"✨ Đã chuốt prompt {changed}/{len(scenes)} cảnh", "ok")

    # ---- 2. cảnh: ảnh khung đầu → clip
    def _scene_update(self, pid: str, index: int, **fields) -> None:
        def apply(p):
            for sc in p["scenes"]:
                if sc["index"] == index:
                    sc.update(fields)
        self._push(self.store.update(pid, apply))

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
        locked = fixed_people or bool(layout)
        return "\n".join(x for x in (
            f"{ASPECTS.get(options.get('aspect') or '9:16', ASPECTS['9:16'])[2]} cinematic frame, scene {sc['index']} "
            "of a story video.",
            f"Visual style: {bible.get('phong_cach')}" if bible.get("phong_cach") else "",
            # có nhân vật / bối cảnh cố định: mô tả riêng của cảnh đặt TRƯỚC, ràng buộc cố định đặt SAU để thắng
            # các chi tiết trái ngược (quần áo, nơi chốn) do storyboard viết
            f"Scene action: {strip_outfit(sc['image_prompt']) if fixed_people else sc['image_prompt']}" if locked else "",
            (f"Fixed characters (keep exactly as their reference images, identical in every scene): {chars}" if chars else
             character_sheet(in_scene) if in_scene else "" if roster else
             f"Characters (keep exactly the same in every scene): {bible.get('nhan_vat')}" if bible.get("nhan_vat") else ""),
            character_sheet(extra, "Other characters in this scene (same face, age and outfit in every scene)")
            if chars and extra else "",
            f"Product / key props: {bible.get('nhan_vat')}" if roster and bible.get("nhan_vat") and not chars else "",
            (f"Fixed setting — match the layout reference image (same location, props, composition and lighting; camera "
             f"distance may change): {layout.get('description') or layout.get('summary') or ''}") if layout else "",
            ("Keep the social-media UI overlay from the layout reference (same elements, positions and texts) on top of "
             "the scene.") if layout and ((layout.get("ui") or {}).get("elements")) else "",
            (f"Scene reference: {cast['combo'].get('description') or cast['combo'].get('summary') or ''}"
             if cast.get("combo") else ""),
            "" if locked else sc["image_prompt"],
            ("IDENTITY LOCK: every character is the SAME person as in their reference image / character description — identical face "
             "(face shape, eyes, nose, mouth, eyebrows), skin tone, body type, personal style (makeup, look, vibe) and "
             "the SAME apparent age. Do not make anyone younger, older, slimmer or prettier, do not beautify, "
             "stylise or swap faces, and ignore any age or facial description in the scene action that conflicts.")
            if fixed_people else "",
            ("OUTFIT LOCK: every character wears EXACTLY the same clothes, accessories and hairstyle as in their "
             "reference image / outfit description — same garment types, colours and patterns. Do not change, add or remove any clothing, even "
             "if the scene action mentions other clothes.") if fixed_people else "",
            ("SETTING LOCK: the scene happens in EXACTLY the location of the setting / scene reference image — same "
             "background, furniture, props, colours and lighting; only the camera angle and distance may change. Ignore "
             "any other location mentioned in the scene action.") if layout else "",
            "Attached images show the characters / product — keep their faces, outfits and packaging identical." if has_refs else "",
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
        refs = [r for r in p.get("refs") or [] if Path(r).is_file()][
            :max(0, spec["max_images"] - (1 if logo else 0) - len(cast["refs"]))]
        if cast["characters"] or cast["layout"]:
            self._log("Dùng " + " · ".join(
                [f"nhân vật {', '.join(c['name'] for c in cast['characters'])}"] * bool(cast["characters"])
                + [f"layout {cast['layout']['name']}"] * bool(cast["layout"])) + f" ({len(cast['refs'])} ảnh tham chiếu)")
        frame_tasks, clip_tasks, errors = {}, {}, []
        try:
            for sc in targets:  # 1) ảnh khung đầu (song song)
                if what == "clip" or (has(sc, "frame") and not (indexes and what in ("both", "frame"))):
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
                clip_tasks[idx] = self.videos.start({
                    "template": SCENE_TEMPLATE, "provider": o["video_engine"], "ai_duration": f"{sc['seconds']}s",
                    "ai_aspect": o["aspect"], "ai_resolution": o["quality"],
                    "variables": clip_variables(sc, o, bible),
                    # khung đầu + (nhân vật / sản phẩm hoặc bối cảnh cố định) → model video giữ đúng người, đồ, cảnh
                    "attachments": {"image": str(pdir / sc["frame"]), **clip_refs(cast)},
                    "show_browser": bool(o.get("show_browser")), "browser_profile": o.get("video_profile", "")})
                self._scene_update(pid, idx, status="clip_running", error="")
            if clip_tasks:
                self._log(f"Đã giao {len(clip_tasks)} clip cho Tạo video ({VIDEO_ENGINES[o['video_engine']]['name']})")
            for k, (idx, task_id) in enumerate(clip_tasks.items(), 1):  # 3) chờ clip
                self.pool.progress(10 + 60 * (k - 1) / len(clip_tasks), f"Đang chờ clip cảnh {idx} ({k}/{len(clip_tasks)})", "clip")
                try:
                    result = self._wait(self.videos, task_id, f"Clip cảnh {idx}")
                    dest = pdir / "scenes" / scene_dir_name(idx) / "clip.mp4"
                    shutil.copy2(Path(self.settings.output_dir) / result["id"] / "final.mp4", dest)
                    self._scene_update(pid, idx, clip=dest.relative_to(pdir).as_posix(), status="done")
                    self._log(f"Xong cảnh {idx} ({k}/{len(clip_tasks)})", "ok")
                except (StudioError, OSError) as exc:
                    errors.append(f"cảnh {idx}: {exc}")
                    self._scene_update(pid, idx, status="error", error=str(exc))
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
        o, pdir = clean_options(p["options"], self.settings), self.store.dir(pid)
        missing = [s["index"] for s in p["scenes"] if not s.get("clip") or not (pdir / s["clip"]).is_file()]
        if missing:
            raise StudioError(f"Cảnh {', '.join(map(str, missing))} chưa có clip — làm cảnh trước khi ghép")
        created = datetime.now()
        job_dir = unique_dir(Path(self.settings.output_dir) / f"{slugify(p['name'])}_{created:%Y%m%d_%H%M%S}")
        scenes, total = [], len(p["scenes"])
        width, height = frame_size(o)
        voices = voice_map((p.get("bible") or {}).get("characters") or [], o)  # giọng riêng từng nhân vật
        dub = o.get("dub", True) or o.get("scene_style") == "whiteboard"  # whiteboard không có tiếng gốc
        if not dub:
            self._log("Không lồng tiếng AI — dùng giọng nói / âm thanh gốc của từng clip")
        for k, sc in enumerate(p["scenes"], 1):
            self.pool.check_cancel()
            self.pool.progress(5 + 70 * (k - 1) / total, f"Đang chuẩn bị cảnh {k}/{total}", "post")
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
        if not dub:  # tiếng gốc bắt đầu ngay đầu cảnh; nhạc nền nhỏ lại để không lấn giọng nói gốc
            job.update(voice_lead=0.0, original_audio=True, bgm_volume=round(job["bgm_volume"] * 0.6, 3))
        self._log(f"Chuyển cảnh: {transitions.TRANSITIONS[o['transition']][0]} {o['transition_duration']:g}s · "
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
        logo = project_logo(p)
        if logo and o.get("logo_overlay", "none") != "none":
            self.pool.progress(96, "Đang đóng logo lên video", "post")
            stamp_logo(job_dir / "final.mp4", logo, o["logo_overlay"])
            self._log(f"Đã đóng logo · {LOGO_CORNERS[o['logo_overlay']].lower()}")
        save_job(job_dir, job)
        self._set(pid, final={"job_id": job_dir.name, "duration": job["duration"], "at": now(), "post": post_info})
        self._log(f"Đã xong video {job['duration']:.0f} giây — có trong Thư viện video", "ok")
        self.pool.progress(100, "Hoàn tất", "finish")
