"""🎞 Mẫu video của màn Grok Canvas: phong cách hình + Master Prompt + khung cảnh quay + kiểu nối cảnh.

Khối Video chọn 1 mẫu → chỉ cần vật liệu (ảnh nhân vật / sản phẩm / bối cảnh) + lời thoại:
- "Không tách" (build="one"): khối tự chia lời thành các đoạn vừa 1 clip, 1 lượt model chữ viết prompt từng đoạn theo
  Master Prompt (lỗi → điền theo khung cảnh của mẫu), quay lần lượt từng đoạn rồi ghép thành 1 video
  (canvas.CanvasRunner._make_templated).
- "Tách khối" (build="split"): dùng cơ chế tách khối Video có sẵn; mỗi khối con lấy prompt theo khung cảnh của mẫu.

Mẫu có sẵn nằm trong file này (BUILTIN); mẫu người dùng tạo / sửa / nhân bản lưu ở <thư mục dữ liệu>/video_templates/.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .paths import DATA_DIR

USER_DIR = DATA_DIR / "video_templates"
MAX_SEGMENTS = 12  # khối Ghép / 1 video tối đa 12 đoạn
CONTINUITY = {"cut": "✂ Cắt cảnh — đoạn nào cũng quay từ ảnh vật liệu (giữ mặt / nhãn tốt nhất)",
              "flow": "⛓ Liền mạch — đoạn sau quay tiếp từ khung cuối đoạn trước (chuyển cảnh mượt)"}
MATERIALS = {"character": "🧍 Nhân vật", "product": "📦 Sản phẩm", "scene": "🏞 Bối cảnh"}

BUILTIN = [
    {"id": "tvc-san-pham", "name": "Giới thiệu sản phẩm (TVC)", "icon": "📦", "continuity": "cut", "segments": 3,
     "desc": "Quảng cáo ngắn kiểu TVC: mở đầu ấn tượng, cận sản phẩm, người dẫn giới thiệu, chốt kêu gọi mua",
     "materials": ["character", "product", "scene"],
     "style": "premium photorealistic TV commercial, clean soft key light with gentle rim light, rich true-to-life colors, "
              "shallow depth of field, smooth gimbal movement, 4K advertising look",
     "master": "Write a short, high-end TV commercial. Open with a striking hero shot, then show the product up close, "
               "then the presenter introducing it with confidence, and close on the product with the presenter in a "
               "warm call to action. Every shot must look like a premium brand commercial.",
     "shots": ["Hero opening: the presenter stands in the setting holding the product at chest height, front label to "
               "camera; slow dolly-in",
               "Product close-up: the product on a clean surface, soft light sweeps across the label; slow orbit",
               "Presenter medium shot: speaks to camera with natural hand gestures toward the product; locked camera",
               "Closing: the presenter smiles and raises the product next to the face, label facing camera; slight "
               "push-in"]},
    {"id": "chuyen-gia", "name": "Chuyên gia tư vấn nói trước camera", "icon": "🎓", "continuity": "flow", "segments": 3,
     "desc": "Một người nói liền mạch trước camera như chuyên gia tư vấn — hợp lời thoại dài, giải thích",
     "materials": ["character", "product"],
     "style": "natural documentary interview look, soft window light, neutral professional background, eye-level camera, "
              "realistic skin tones, calm and trustworthy mood",
     "master": "Write one continuous expert talking-head video. The same presenter speaks directly to camera the whole "
               "time in the same place; only subtle changes of framing and gesture between parts so the cuts feel "
               "seamless.",
     "shots": ["Medium shot: the expert looks into the camera and starts explaining, calm open gestures; locked camera",
               "Same framing, slightly closer: the expert keeps explaining and briefly holds up the product; very slow "
               "push-in",
               "Same place: the expert nods and gives a friendly recommendation to camera; locked camera"]},
    {"id": "review-ugc", "name": "Review / cảm nhận khách hàng (UGC)", "icon": "🤳", "continuity": "flow", "segments": 3,
     "desc": "Video kiểu khách hàng tự quay bằng điện thoại: cầm sản phẩm, kể cảm nhận tự nhiên",
     "materials": ["character", "product"],
     "style": "authentic handheld smartphone selfie video, vertical framing, natural daylight, slight natural handheld "
              "shake, casual real-life setting, no studio look",
     "master": "Write an authentic user-generated review. The customer films themself on a phone, talks casually and "
               "shows the product; it must feel real and unpolished, not like an advertisement.",
     "shots": ["Selfie framing: the customer greets the viewer and lifts the product into frame; handheld",
               "The customer turns the product to show the label up close while talking; handheld",
               "The customer smiles and gives a thumbs up with the product; handheld"]},
    {"id": "huong-dan", "name": "Hướng dẫn sử dụng", "icon": "🧪", "continuity": "cut", "segments": 4,
     "desc": "Từng bước dùng sản phẩm: chuẩn bị, thao tác, kết quả — người dẫn vừa làm vừa nói",
     "materials": ["character", "product", "scene"],
     "style": "clear instructional video, bright even daylight, clean framing that shows hands and product clearly, "
              "stable camera, realistic",
     "master": "Write a step-by-step how-to video. Each part shows exactly one step of using the product with the hands "
               "and product clearly visible, in a logical order from preparation to result.",
     "shots": ["The presenter introduces the product to camera, holding it clearly; locked camera",
               "Close-up of hands opening and measuring the product; 45-degree locked camera",
               "Hands applying the product in the real setting; slow follow",
               "The presenter shows the finished result and recommends the product; slow push-in"]},
    {"id": "truoc-sau", "name": "Trước – sau", "icon": "🔁", "continuity": "cut", "segments": 3,
     "desc": "So sánh tình trạng trước khi dùng và sau khi dùng sản phẩm, chốt bằng sản phẩm",
     "materials": ["character", "product", "scene"],
     "style": "realistic commercial look, consistent framing between before and after shots, natural daylight, "
              "the 'before' slightly dull, the 'after' vivid and healthy",
     "master": "Write a before-and-after story: first the problem, then the product being used, then the improved "
               "result from a matching angle, ending on the product. Only show results that the dialogue states.",
     "shots": ["Before: the problem in the setting, the presenter looks concerned; slow pan",
               "The presenter uses the product in the same place; locked camera",
               "After: the same place looking better, the presenter smiles holding the product; slow push-in"]},
    {"id": "nha-vuon", "name": "Kể chuyện nhà vườn", "icon": "🌾", "continuity": "flow", "segments": 3,
     "desc": "Câu chuyện người làm vườn đi trong vườn, kể trải nghiệm — cảm xúc, gần gũi",
     "materials": ["character", "product", "scene"],
     "style": "warm cinematic storytelling, golden-hour sunlight, lush Southern Vietnamese orchard, gentle camera "
              "movement, emotional and authentic",
     "master": "Write a warm farmer storytelling video. The same farmer walks through the orchard and tells the story "
               "to camera; the journey is continuous, each part continues the walk naturally.",
     "shots": ["The farmer walks between the fruit trees toward camera and starts talking; slow backward tracking",
               "The farmer stops, touches the leaves and fruit while talking; gentle orbit",
               "The farmer holds the product in the orchard and smiles to camera; slow push-in"]},
]
ID_RE = re.compile(r"[a-z0-9-]{3,60}")


def _clean(tpl: dict) -> dict:
    shots = [" ".join(str(s).split())[:600] for s in tpl.get("shots") or [] if str(s).strip()][:MAX_SEGMENTS]
    try:
        segments = max(1, min(MAX_SEGMENTS, int(tpl.get("segments") or len(shots) or 3)))
    except (TypeError, ValueError):
        segments = 3
    return {"id": str(tpl.get("id") or ""), "name": str(tpl.get("name") or "Mẫu video").strip()[:80],
            "icon": str(tpl.get("icon") or "🎞")[:4], "desc": str(tpl.get("desc") or "").strip()[:300],
            "continuity": tpl.get("continuity") if tpl.get("continuity") in CONTINUITY else "cut",
            "segments": segments, "materials": [m for m in tpl.get("materials") or [] if m in MATERIALS],
            "style": " ".join(str(tpl.get("style") or "").split())[:800],
            "master": str(tpl.get("master") or "").strip()[:3000],
            "shots": shots or ["The presenter speaks to camera holding the product; locked camera"]}


def _user_files() -> list[Path]:
    return sorted(USER_DIR.glob("*.json")) if USER_DIR.is_dir() else []


def list_templates() -> list[dict]:
    """Mẫu có sẵn rồi tới mẫu của người dùng (mẫu người dùng trùng id mẫu có sẵn = bản đã sửa, thay chỗ mẫu đó)."""
    users = {}
    for f in _user_files():
        try:
            data = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id") == f.stem:
            users[f.stem] = {**_clean(data), "user": True, "updated": data.get("updated") or 0}
    out = [{**users.pop(t["id"]), "builtin": True, "edited": True} if t["id"] in users
           else {**_clean(t), "user": False, "builtin": True} for t in BUILTIN]
    return out + sorted(users.values(), key=lambda t: -float(t.get("updated") or 0))


def get(tid: str) -> dict | None:
    return next((t for t in list_templates() if t["id"] == tid), None) if tid else None


def save(tpl: dict) -> dict:
    """Lưu mẫu người dùng. Không có id → mẫu mới. Sửa mẫu có sẵn → lưu bản sửa cùng id (xoá bản sửa = về mặc định)."""
    data = _clean(tpl)
    if not ID_RE.fullmatch(data["id"]):
        base = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")[:30] or "mau"
        data["id"] = f"{base if len(base) >= 3 else 'mau-' + base}-{int(time.time() * 1000) % 10 ** 8}".strip("-")
    USER_DIR.mkdir(parents=True, exist_ok=True)
    data["updated"] = time.time()
    (USER_DIR / f"{data['id']}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return get(data["id"]) or data


def delete(tid: str) -> bool:
    """Xoá mẫu người dùng / bản sửa của mẫu có sẵn (mẫu có sẵn trở về mặc định). False = không có gì để xoá."""
    path = USER_DIR / f"{tid}.json"
    if not ID_RE.fullmatch(tid or "") or not path.is_file():
        return False
    path.unlink()
    return True


def shot_for(tpl: dict, k: int, n: int) -> str:
    """Khung cảnh cho đoạn k (1..n): đoạn đầu = cảnh đầu, đoạn cuối = cảnh cuối, giữa = xoay vòng các cảnh giữa."""
    shots = tpl["shots"]
    if k == 1 or len(shots) == 1:
        return shots[0]
    if k == n:
        return shots[-1]
    mid = shots[1:-1] or shots
    return mid[(k - 2) % len(mid)]


def fallback_prompt(tpl: dict, k: int, n: int, idea: str = "") -> str:
    """Prompt đoạn k điền theo khung cảnh của mẫu (không gọi AI)."""
    parts = [shot_for(tpl, k, n).rstrip(".") + "."]
    if idea.strip():
        parts.append("Context: " + " ".join(idea.split())[:600])
    return " ".join(parts)


def finish_prompt(tpl: dict, text: str, k: int, n: int) -> str:
    """Gắn phong cách + nối cảnh của mẫu vào prompt đoạn k (cả prompt AI viết lẫn prompt điền theo khung)."""
    parts = [text.strip()]
    if tpl["style"]:
        parts.append(f"Style: {tpl['style']}.")
    if n > 1:
        parts.append(f"Part {k} of {n} of one video: keep exactly the same person, outfit, product and setting"
                     + (" and continue seamlessly from the previous part." if tpl["continuity"] == "flow" else "."))
    return " ".join(p for p in parts if p)[:2000]


WRITER = """You are a senior commercial video director writing prompts for {model} (image-to-video, {secs}-second clips).

VIDEO TEMPLATE: {name}
Direction: {master}
Visual style for EVERY part: {style}
Shot pattern of this template (follow this order; first part = first shot, last part = last shot):
{shots}
Transitions: {continuity}

The video has EXACTLY {n} parts of {secs} seconds. Spoken Vietnamese line of each part (already fixed — do NOT change,
translate or repeat it; just make the action fit what is being said):
{lines}
{idea}Attached images (materials, in order): {materials}

Rules for each part prompt (plain English, under 90 words):
- One main action and one main camera movement; describe composition, action, camera, lighting.
- Use the same presenter, outfit, product and setting as the attached images in every part; never invent another
  person or product, never describe on-screen text, captions, logos appearing, cuts or morphing.
- Make the action match the spoken line of that part (gestures, showing the product when it is mentioned).

Return ONLY one ```json block: {{"parts": [{{"part": 1, "prompt": "..."}}, ...]}} with exactly {n} items."""


def writer_prompt(tpl: dict, lines: list[str], *, secs: int, model: str, idea: str, materials: list[str]) -> str:
    n = len(lines)
    return WRITER.format(
        model=model, secs=secs, name=tpl["name"], master=tpl["master"] or tpl["desc"], style=tpl["style"] or "realistic",
        shots="\n".join(f"{i}. {s}" for i, s in enumerate(tpl["shots"], 1)),
        continuity="each part continues seamlessly from the last frame of the previous part (same place, same moment)"
        if tpl["continuity"] == "flow" else "clean cuts between parts; every part starts from the material images",
        n=n, lines="\n".join(f"Part {i}: " + (f'"{x}"' if x else "(no dialogue)") for i, x in enumerate(lines, 1)),
        idea=f"Extra idea / context from the user: {' '.join(idea.split())[:1500]}\n" if idea.strip() else "",
        materials=", ".join(materials) or "(none)")


def parse_parts(text: str, n: int) -> list[str] | None:
    """Câu trả lời model → n prompt (thiếu / sai định dạng → None)."""
    raw = str(text or "")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S) or re.search(r"(\{.*\})", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    parts = data.get("parts") if isinstance(data, dict) else None
    if not isinstance(parts, list):
        return None
    out = [" ".join(str(p.get("prompt") if isinstance(p, dict) else p or "").split()) for p in parts]
    out = [x for x in out if x]
    return out[:n] if len(out) >= n else None
