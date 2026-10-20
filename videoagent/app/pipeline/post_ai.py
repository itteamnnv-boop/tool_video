"""Hậu kỳ AI (Studio, sau bước làm cảnh — trước khi ghép): nhờ model chat (mặc định Claude trình duyệt) đọc lời dẫn
từng cảnh rồi chọn từ khoá cần tô nổi trên phụ đề, hiệu ứng âm thanh gắn vào đúng từ, câu "hook" đầu video và mức
nhạc nền. App tự áp dụng bằng ffmpeg (phụ đề ASS + SFX tự tổng hợp + nhạc nền nhỏ lại khi có giọng nói).

Model chỉ CHỌN trong lời dẫn có sẵn (không viết lại lời) → phụ đề luôn khớp giọng đọc.
"""
import re

from ..llm.base import extract_json
from .subtitles import scene_words
from .transitions import SOUNDS

SFX_KEYS = ("pop", "ding", "impact", "whoosh", "swoosh", "riser", "click")
BGM_LEVELS = {"nhe": 0.08, "vua": 0.12, "manh": 0.18}
MAX_KEYWORDS, MAX_CUES = 3, 2  # mỗi cảnh
CUE_VOLUME = {"impact": 0.9, "ding": 0.7, "riser": 0.6}  # còn lại 0.65
HOOK_MAX = 60  # ký tự

_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _norm(text: str) -> str:
    return _WORD.sub(" ", str(text).lower()).strip()


def build_prompt(scenes: list[dict]) -> str:
    """scenes: [{"index", "headline", "narration", "duration"}] — cảnh không lời vẫn liệt kê để model hiểu nhịp."""
    lines = []
    for s in scenes:
        text = " ".join(str(s.get("narration") or "").split()) or "(không lời — chỉ có hình)"
        lines.append(f"Cảnh {s['index']} ({s['duration']:.0f} giây) — {s.get('headline') or ''}: {text}")
    sounds = ", ".join(f"{k} = {SOUNDS[k][0]}" for k in SFX_KEYS)
    return f"""Bạn là biên tập viên hậu kỳ video ngắn TikTok / Reels. Video dọc đã dựng xong với lời dẫn từng cảnh:
<loi_dan>
{chr(10).join(lines)}
</loi_dan>

Nhiệm vụ: làm phụ đề và âm thanh NỔI BẬT, cuốn hút nhưng không lố. KHÔNG viết lại lời dẫn.
- "tu_khoa": mỗi cảnh có lời chọn 1–{MAX_KEYWORDS} từ / cụm từ quan trọng nhất (tên sản phẩm, con số, giá, lợi ích, cảm xúc
  mạnh) — phải chép NGUYÊN VĂN từ lời dẫn của đúng cảnh đó (để tô màu trên phụ đề). Cảnh không lời: [].
- "am_thanh": mỗi cảnh 0–{MAX_CUES} hiệu ứng, mỗi hiệu ứng gắn vào một từ có trong lời dẫn cảnh đó:
  {{"tu": "<từ nguyên văn>", "loai": "<mã>"}}. Mã: {sounds}.
  Cảnh không lời: tối đa 1 hiệu ứng hợp với hình (đặt ở đầu cảnh), ghi {{"tu": "", "loai": "<mã>"}}.
  Gợi ý: ding cho giá / ưu đãi / kết quả tốt, impact cho cao trào / tiết lộ, pop cho ý liệt kê, riser ngay trước cao trào,
  whoosh / swoosh khi chuyển ý. Dùng tiết chế — tổng cả video khoảng 1 hiệu ứng mỗi 6–8 giây.
- "hook": tiêu đề ngắn (tối đa 7 từ, tiếng Việt) hiện ở đầu video để giữ người xem, đúng nội dung, không bịa thông tin.
- "nhac_nen": "nhe" | "vua" | "manh" — mức nhạc nền hợp với nội dung (cảm xúc nhẹ nhàng → nhe, sôi động → manh).

Chỉ trả về MỘT object JSON (không giải thích), ví dụ:
{{"hook": "…", "nhac_nen": "vua", "canh": [{{"so": 1, "tu_khoa": ["…"], "am_thanh": [{{"tu": "…", "loai": "pop"}}]}}]}}"""


def complete(text: str) -> bool:
    data = extract_json(text)
    return isinstance(data, dict) and isinstance(data.get("canh"), list)


def _find(words: list[dict], phrase: str) -> list[int]:
    """Vị trí các từ (trong danh sách từ của cảnh) khớp cụm từ; [] nếu không thấy."""
    target = _norm(phrase).split()
    tokens = [_norm(w["text"]) for w in words]
    if not target:
        return []
    for i in range(len(tokens) - len(target) + 1):
        if tokens[i:i + len(target)] == target:
            return list(range(i, i + len(target)))
    return []


def apply_plan(data: dict, scenes: list[dict], offsets: list[float], voice_lead: float, *, subs: bool, audio: bool,
               log=None) -> dict:
    """Ghép kết quả model vào job: scenes[k]["highlight"] (vị trí từ cần tô), job "sfx_cues" (giây tuyệt đối),
    "subtitle_hook", "bgm_volume", "duck_bgm". Bỏ qua mọi thứ model trả sai (từ không có trong lời, mã âm lạ)."""
    by_index = {}
    for raw in data.get("canh") or []:
        try:
            by_index[int(raw.get("so"))] = raw
        except (TypeError, ValueError, AttributeError):
            continue
    cues, skipped = [], 0
    for k, scene in enumerate(scenes):
        raw = by_index.get(scene["index"]) or {}
        words = scene_words(scene)
        if subs:
            marks = set()
            for phrase in (raw.get("tu_khoa") or [])[:MAX_KEYWORDS]:
                found = _find(words, phrase)
                skipped += not found
                marks.update(found)
            scene["highlight"] = sorted(marks)
        if audio:
            if not words:  # cảnh không lời: không có từ để gắn → 1 hiệu ứng ở đầu cảnh (trước đây bị bỏ hết)
                key = next((str((c or {}).get("loai") or "").lower() for c in raw.get("am_thanh") or []
                            if str((c or {}).get("loai") or "").lower() in SFX_KEYS), "")
                if key:
                    cues.append({"t": round(offsets[k] + 0.25, 3), "key": key, "vol": CUE_VOLUME.get(key, 0.65)})
                continue
            for cue in (raw.get("am_thanh") or [])[:MAX_CUES]:
                key = str((cue or {}).get("loai") or "").lower()
                found = _find(words, (cue or {}).get("tu") or "") if key in SFX_KEYS else []
                if not found:
                    skipped += 1
                    continue
                at = offsets[k] + voice_lead + words[found[0]]["start"]
                if key == "riser":  # riser vút lên ĐẾN đúng từ đó
                    at -= SOUNDS["riser"][1] * 0.85
                cues.append({"t": round(max(0.0, at), 3), "key": key, "vol": CUE_VOLUME.get(key, 0.65)})
    job = {}
    if audio:
        job.update(sfx_cues=cues, duck_bgm=True)
        level = str(data.get("nhac_nen") or "").lower()
        if level in BGM_LEVELS:
            job["bgm_volume"] = BGM_LEVELS[level]
    hook = " ".join(str(data.get("hook") or "").split())[:HOOK_MAX]
    if subs:
        job["subtitle_fx"] = True
        if hook:
            job["subtitle_hook"] = hook
    if log:
        parts = []
        if subs:
            parts.append(f"tô nổi {sum(len(s.get('highlight') or []) for s in scenes)} từ")
            if hook:
                parts.append(f"hook “{hook}”")
        if audio:
            parts.append(f"{len(cues)} hiệu ứng âm thanh")
            if "bgm_volume" in job:
                parts.append(f"nhạc nền {data.get('nhac_nen')}")
        log("Hậu kỳ AI: " + " · ".join(parts) + (f" (bỏ {skipped} gợi ý không khớp lời dẫn)" if skipped else ""))
    return job
