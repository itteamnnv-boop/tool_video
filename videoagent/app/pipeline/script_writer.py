"""Bước Kịch bản: AI viết nội dung từng khung hình (và chọn template nếu được yêu cầu)."""
import json
import re

from ..genres import WORDS_PER_SECOND, get_genre
from ..llm import LLMError, LLMProvider
from ..llm.prompts import SCRIPT_PROMPT, SHORTEN_PROMPT, TEMPLATE_BLOCK
from . import VOICE_LEAD, SCENE_TAIL

TEXT_FIELDS = ("kicker", "headline", "highlight", "subtext", "stat", "narration")
FIT_FIELDS = ("kicker", "headline", "subtext", "stat")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _clean(value) -> str:
    text = _EMOJI.sub("", str(value or ""))
    text = re.sub(r"[*#_`]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def write_script(llm: LLMProvider | None, req, ai_templates: list | None = None, images: list | None = None,
                 extra: str = "") -> dict:
    if llm is None:
        return offline_script(req)
    genre = get_genre(req.genre)
    speak = max(2.0, req.seconds - VOICE_LEAD - SCENE_TAIL)
    words_max = max(6, round(speak * WORDS_PER_SECOND))
    template_block, template_field = "", ""
    if ai_templates:
        options = "\n".join(f"- {t.id}: {t.name} — {t.description}" for t in ai_templates)
        template_block = TEMPLATE_BLOCK.format(options=options)
        template_field = '\n  "template_id": "id template đã chọn",'
    if images:
        template_block += (f"Đính kèm {len(images)} ảnh sản phẩm: mô tả đúng sản phẩm trong ảnh; không bịa giá, "
                           "thông số hay thương hiệu nếu người dùng không cung cấp.\n")
    template_block += extra
    prompt = SCRIPT_PROMPT.format(
        topic=req.topic, genre_name=genre["name"], genre_guide=genre["guide"], tone=genre["tone"],
        num_scenes=req.num_scenes, seconds=round(req.seconds, 1), aspect=req.aspect,
        words_min=max(4, round(words_max * 0.7)), words_max=words_max,
        headline_words=genre["headline_words"], template_block=template_block, template_field=template_field,
    )
    return normalize_script(llm.generate_json(prompt, images=images), req)


def normalize_script(data, req) -> dict:
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict):
        raise LLMError("AI trả về kịch bản sai định dạng")
    scenes = []
    for raw in (data.get("scenes") or [])[: req.num_scenes]:
        if not isinstance(raw, dict):
            continue
        scene = {f: _clean(raw.get(f)) for f in TEXT_FIELDS}
        scene["kicker"] = scene["kicker"].upper()
        scene["trend"] = raw.get("trend") if raw.get("trend") in ("up", "down", "flat") else "flat"
        if not scene["headline"]:
            scene["headline"] = " ".join(scene["narration"].split()[:7])
        if not scene["narration"]:
            scene["narration"] = ". ".join(filter(None, [scene["headline"], scene["subtext"]]))
        if scene["headline"]:
            scenes.append(scene)
    if not scenes:
        raise LLMError("AI không trả về khung hình nào")
    features = [_clean(f) for f in data.get("features") or [] if isinstance(f, str) and _clean(f)][:4]
    return {
        "title": _clean(data.get("title")) or scenes[0]["headline"],
        "template_id": _clean(data.get("template_id")),
        "features": [" ".join(f.split()[:4]) for f in features],
        "scenes": scenes,
    }


def offline_script(req) -> dict:
    """Kịch bản dựng sẵn khi chọn provider Offline — để thử pipeline mà không cần AI."""
    core = re.sub(r"^(hãy\s+)?(tạo|làm|dựng)\s+(một\s+|1\s+)?video\s+(về|giới thiệu)?\s*", "", req.topic.strip(), flags=re.I)
    core = core.rstrip(".!? ") or req.topic.strip()
    short = " ".join(core.split()[:6])
    beats = [
        ("TỔNG QUAN", f"{short[:1].upper()}{short[1:]}", "Nhìn nhanh bức tranh toàn cảnh", "up",
         f"Hôm nay chúng ta cùng điểm qua {core}."),
        ("ĐIỂM NÓNG", "Những điều đáng chú ý nhất", "Các chi tiết nổi bật bạn cần biết", "up",
         "Đây là những điểm đang được quan tâm nhiều nhất lúc này."),
        ("GÓC NHÌN", "Vì sao điều này quan trọng", "Tác động trực tiếp đến mỗi chúng ta", "down",
         "Hiểu đúng vấn đề giúp bạn đưa ra quyết định tốt hơn."),
        ("TIẾP THEO", "Điều gì đang chờ phía trước", "Những tín hiệu cần theo dõi sát", "flat",
         "Hãy cùng theo dõi những diễn biến tiếp theo trong thời gian tới."),
        ("KẾT LUẬN", "Theo dõi để không bỏ lỡ", "Cập nhật mỗi ngày cùng kênh", "up",
         "Đừng quên theo dõi để cập nhật thông tin mới nhất nhé."),
    ]
    scenes = []
    for i in range(req.num_scenes):
        beat = beats[-1] if i == req.num_scenes - 1 and i > 0 else beats[min(i, len(beats) - 2)]
        kicker, headline, subtext, trend, narration = beat
        scenes.append({"kicker": kicker, "headline": headline, "highlight": headline.split()[-1],
                       "subtext": subtext, "stat": "", "trend": trend, "narration": narration})
    return {"title": short, "template_id": "", "scenes": scenes}


def shorten_fields(llm: LLMProvider | None, scene: dict, fields: list[str]) -> dict:
    """Agent sửa lỗi tràn chữ: nhờ AI viết gọn lại; không có AI thì cắt bớt từ."""
    fields = [f for f in fields if f in FIT_FIELDS and scene.get(f)]
    if not fields:
        return {}
    if llm is not None:
        current = json.dumps({f: scene[f] for f in fields}, ensure_ascii=False, indent=1)
        try:
            data = llm.generate_json(SHORTEN_PROMPT.format(fields=", ".join(fields), current=current))
            if isinstance(data, dict):
                out = {k: _clean(v) for k, v in data.items() if k in fields or k == "highlight"}
                out = {k: v for k, v in out.items() if v}
                if out:
                    return out
        except LLMError:
            pass
    return {f: _truncate(scene[f]) for f in fields}


def _truncate(text: str, ratio: float = 0.7) -> str:
    words = text.split()
    keep = max(1, int(len(words) * ratio))
    return " ".join(words[:keep]) + ("…" if keep < len(words) else "")
