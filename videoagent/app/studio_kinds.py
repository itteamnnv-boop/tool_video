"""Mẫu dự án Studio do người dùng tự thêm (kể cả mẫu tạo từ video trending) — lưu ở %APPDATA%/VideoAgent/studio_kinds.json.
Mỗi mẫu: key ("c_…"), label (tên, có thể có emoji), hint (mô tả ngắn trên thẻ), note (ghi chú gửi model viết storyboard),
presets (độ dài / tỉ lệ / cỡ cảnh / góc máy / phong cách điền sẵn), source (video gốc nếu tạo từ video trending)."""
import threading
import uuid

from .paths import DATA_DIR
from .util import read_json, write_json

FILE = DATA_DIR / "studio_kinds.json"
MAX_KINDS = 40
_lock = threading.Lock()


def _flat(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def load() -> list[dict]:
    try:
        data = read_json(FILE)
    except (OSError, ValueError):
        return []
    return [k for k in data if isinstance(k, dict) and str(k.get("key", "")).startswith("c_")] if isinstance(data, list) else []


def clean(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    label = _flat(raw.get("label"), 60)
    if len(label) < 2:
        raise ValueError("Đặt tên cho mẫu (ít nhất 2 ký tự)")
    note = str(raw.get("note") or "").strip()[:2500]
    if len(note) < 10:
        raise ValueError("Viết ghi chú cho AI (cấu trúc cảnh, giọng điệu…) — ít nhất 1 câu")
    p = raw.get("presets") if isinstance(raw.get("presets"), dict) else {}
    presets = {}
    try:
        if p.get("length"):
            presets["length"] = int(p["length"])
    except (TypeError, ValueError):
        pass
    for key in ("aspect", "shot_size", "camera_angle"):
        if p.get(key):
            presets[key] = _flat(p[key], 30)
    if p.get("style"):
        presets["style"] = _flat(p["style"], 300)
    src = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    key = str(raw.get("key") or "")
    return {"key": key if key.startswith("c_") else f"c_{uuid.uuid4().hex[:8]}", "label": label,
            "hint": _flat(raw.get("hint"), 160), "note": note, "presets": presets,
            **({"source": {"url": _flat(src.get("url"), 500), "title": _flat(src.get("title"), 200)}}
               if src.get("url") or src.get("title") else {})}


def save(raw: dict) -> tuple[list[dict], str]:
    item = clean(raw)
    with _lock:
        current = load()
        old = next((i for i, k in enumerate(current) if k["key"] == item["key"]), None)
        if old is None and len(current) >= MAX_KINDS:
            raise ValueError(f"Tối đa {MAX_KINDS} mẫu tự thêm — xoá bớt mẫu cũ")
        if old is None:
            current.append(item)
        else:
            current[old] = item
        write_json(FILE, current)
    return current, item["key"]


def delete(key: str) -> list[dict]:
    with _lock:
        items = [k for k in load() if k["key"] != key]
        write_json(FILE, items)
    return items


def from_video(rv: dict, lengths: tuple) -> dict:
    """Video trending đã phân tích (pipeline/ref_video) → bản nháp mẫu: giữ cấu trúc / nhịp / hook / phong cách,
    nội dung là của người dùng. Người dùng sửa rồi mới lưu."""
    d = rv.get("data") or {}
    title = _flat(rv.get("title") or d.get("chu_de") or "Video trending", 80)
    rows = d.get("canh") or []
    structure = "\n".join(
        f"- Cảnh {i} ({r.get('tu', '?')}–{r.get('den', '?')}s): {_flat(r.get('noi_dung'), 200)}"
        + (f" · hình: {_flat(r.get('hinh'), 120)}" if r.get("hinh") else "")
        + (f" · kiểu lời: {_flat(r.get('loi'), 120)}" if r.get("loi") else "") for i, r in enumerate(rows, 1))
    parts = [f"DẠNG VIDEO theo mẫu trending «{title}» — giữ CẤU TRÚC, nhịp dựng, cách mở đầu và phong cách hình của "
             "video gốc, nhưng nội dung, sản phẩm, nhân vật là của người dùng; KHÔNG chép nguyên văn lời thoại, thương "
             "hiệu hay nhân vật của video gốc."]
    for key, label in (("hook", "Cách mở đầu (hook)"), ("nhip", "Nhịp dựng"), ("loi_thoai", "Kiểu lời thoại"),
                       ("phong_cach", "Phong cách hình"), ("am_thanh", "Âm thanh")):
        if d.get(key):
            parts.append(f"{label}: {_flat(d[key], 300)}")
    if structure:
        parts.append(f"Cấu trúc gốc ({len(rows)} cảnh — viết số cảnh tương tự, mỗi cảnh cùng vai trò):\n{structure}")
    elif rv.get("brief"):
        parts.append("Tóm tắt video gốc:\n" + str(rv["brief"])[:1500])
    duration = float(rv.get("duration") or 0)
    length = min(lengths, key=lambda n: abs(n - duration)) if duration and lengths else None
    return {"label": f"🔥 {title[:50]}", "hint": _flat(d.get("hook") or d.get("chu_de") or "Theo cấu trúc video trending", 150),
            "note": "\n".join(parts)[:2500],
            "presets": {**({"length": length} if length else {}), **({"style": _flat(d["phong_cach"], 300)} if d.get("phong_cach") else {})},
            "source": {"url": _flat(rv.get("source"), 500), "title": title}}
