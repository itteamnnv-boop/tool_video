"""Lưu trữ chiến dịch + thư viện (sản phẩm, ảnh tham chiếu, người mẫu, phong cách, mẫu content, vai trò AI).

- Chiến dịch: <thư mục video>/_campaigns/<YYYY-MM-DD>-<slug>/ — giữ đúng tên file bàn giao của dây chuyền
  (00-brief.md, 01-y-tuong.md, …) để dùng chung với dữ liệu cũ; trạng thái ở campaign.json.
- Thư viện: DATA_DIR/campaign/. Không xoá/ghi đè chiến dịch cũ: ghi đè file nào thì cất bản cũ vào _cu/.
"""
import json
import re
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ..paths import DATA_DIR
from ..util import slugify, unique_dir

LIB = DATA_DIR / "campaign"
AGENTS_DIR = Path(r"D:\00_DuAnTest\maketing\.claude")  # nguồn system prompt gốc (.claude/agents/*.md)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

STAGES = [  # (key, tên, vai trò, file bàn giao)
    ("0", "Tạo thư mục", "he-thong", ""),
    ("1", "Brief giao việc", "truong-phong-marketing", "00-brief.md"),
    ("2", "5 ý tưởng", "nv-y-tuong", "01-y-tuong.md"),
    ("3", "Chọn ý tưởng", "truong-phong-marketing", "02-chon-y-tuong.md"),
    ("4", "Viết content", "nv-content", "03-content.md"),
    ("5", "Kế hoạch nội dung", "truong-phong-marketing", "04-chon-content.md"),
    ("6", "Làm ảnh", "nv-hinh-anh", "05-hinh-anh.html"),
    ("6b", "Video", "nv-video", "07-video.html"),
    ("7", "Duyệt", "truong-phong-marketing", "06-danh-gia.md"),
    ("7b", "Kiểm duyệt đăng", "nv-dang-bai-facebook", "08-dang-bai/ke-hoach-dang.md"),
    ("7c", "Đăng Facebook", "nv-dang-bai-facebook", "08-dang-bai/da-dang.md"),
    ("8", "Báo cáo", "he-thong", "bao-cao.md"),
]
STAGE_KEYS = [s[0] for s in STAGES]
ROLES = {
    "truong-phong-marketing": {"name": "Trưởng phòng", "model": "claude-opus-5-5", "effort": "high"},
    "nv-y-tuong": {"name": "NV ý tưởng", "model": "claude-sonnet-5-5", "effort": "medium", "web": True},
    "nv-content": {"name": "NV content", "model": "claude-opus-5-5", "effort": "high"},
    "nv-hinh-anh": {"name": "NV hình ảnh", "model": "claude-sonnet-5-5", "effort": "medium", "web": True},
    "nv-dang-bai-facebook": {"name": "NV đăng bài", "model": "claude-sonnet-5-5", "effort": "medium"},
    "nv-video": {"name": "NV video", "model": "claude-sonnet-5-5", "effort": "medium"},
}
# Thông tin sản phẩm: price = giá gốc, sale_price = giá khuyến mãi, promo = mô tả ưu đãi, label = mô tả nhãn (so nhãn)
PRODUCT_FIELDS = ("name", "code", "spec", "price", "sale_price", "promo", "hotline", "label")
STATUSES = {"draft": "Nháp", "running": "Đang chạy", "waiting": "Chờ người dùng", "approved": "Đã duyệt",
            "posted": "Đã đăng", "error": "Lỗi", "cancelled": "Đã huỷ", "done": "Hoàn tất"}
DEFAULT_STYLES = [
    {"id": "sexy-tao-bao", "name": "Sexy táo bạo",
     "prompt": "người mẫu nữ nóng bỏng, tự tin, trang phục bó sát tôn dáng, thần thái cuốn hút (trang nhã, không phản cảm)"},
    {"id": "goi-cam", "name": "Gợi cảm", "prompt": "người mẫu nữ gợi cảm nhẹ nhàng, trang phục nữ tính, ánh nhìn duyên dáng"},
    {"id": "thanh-lich", "name": "Thanh lịch – Văn phòng", "prompt": "người mẫu trang phục công sở thanh lịch, phong thái chuyên nghiệp"},
    {"id": "giu-nhu-mau", "name": "Giữ như ảnh mẫu", "prompt": "giữ phong cách, trang phục, tư thế giống người trong ảnh tham chiếu (gương mặt khác)"},
]
DEFAULT_TEMPLATE = """<TÊN SẢN PHẨM IN HOA> – <LỢI ÍCH CHÍNH IN HOA, ≤ 8 từ> <1 emoji>
<Cây/đối tượng> đang vào giai đoạn <giai đoạn> mà:
❌ <nỗi đau 1>
❌ <nỗi đau 2>
❌ <nỗi đau 3>
👉 Đừng lo! Đã có <TÊN SẢN PHẨM> – giải pháp giúp:
✅ <lợi ích 1>
✅ <lợi ích 2>
✅ <lợi ích 3>
✅ <lợi ích 4>
<1 câu: phù hợp cho đối tượng nào, giai đoạn nào.>
🏷️ Sản phẩm: <TÊN SẢN PHẨM đầy đủ>
🔖 Mã SP: <mã sản phẩm>
📦 <quy cách đóng gói>
💰 Giá: <giá gốc>đ ➜ Giá khuyến mãi: <giá KM>đ
HOTLINE: <số hotline>
📩 Inbox ngay để được tư vấn <nội dung tư vấn>
"""

_lock = threading.RLock()


class CampaignError(RuntimeError):
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, data) -> None:
    """Ghi JSON nguyên tử. Windows báo 'Access is denied' khi file đang được luồng khác/antivirus đọc → khoá + thử lại."""
    import time

    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        for attempt in range(20):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)


# ====================================================================== chiến dịch
def root(output_dir) -> Path:
    return Path(output_dir) / "_campaigns"


def campaign_dir(output_dir, cid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{3,90}", cid or ""):
        raise CampaignError("Mã chiến dịch không hợp lệ")
    path = root(output_dir) / cid
    if not (path / "campaign.json").exists():
        raise CampaignError("Không tìm thấy chiến dịch")
    return path


def new_campaign_dir(output_dir, name: str) -> Path:
    """Thư mục mới <ngày>-<slug>; trùng thì thêm -2, -3 (không ghi đè chiến dịch cũ)."""
    slug = "-".join(slugify(name, 60).split("-")[:5]) or "chien-dich"
    base = root(output_dir) / f"{datetime.now():%Y-%m-%d}-{slug}"
    candidate, n = base, 2
    while True:
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            candidate, n = base.with_name(f"{base.name}-{n}"), n + 1


def load(path: Path) -> dict:
    data = _read(path / "campaign.json", None)
    if data is None:
        raise CampaignError("campaign.json hỏng hoặc không đọc được")
    return data


def save(path: Path, data: dict) -> None:
    with _lock:
        data["updated_at"] = now()
        _write(path / "campaign.json", data)


def keep_old(path: Path) -> None:
    """Trước khi ghi lại một file bàn giao: cất bản cũ vào _cu/<thời gian>-<tên> (quy tắc không ghi đè)."""
    if path.exists():
        backup = path.parent / "_cu" / f"{datetime.now():%Y%m%d_%H%M%S}-{path.name}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)


def write_file(cdir: Path, rel: str, text: str) -> Path:
    path = cdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    keep_old(path)
    path.write_text(text, "utf-8")
    return path


def summary(path: Path, data: dict | None = None) -> dict:
    data = data or load(path)
    thumb = next((f"05-hinh-anh/{f}" for f in ("c1-a.png", "c1-b.png") if (path / "05-hinh-anh" / f).exists()), "")
    if not thumb:
        first = (data.get("inputs") or {}).get("products") or []
        thumb = f"inputs/san-pham/{first[0]}" if first else ""
    return {"id": path.name, "name": data.get("name", ""), "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"), "status": data.get("status", "draft"),
            "product": (data.get("product") or {}).get("name", ""), "thumb": thumb,
            "verdict": (data.get("verdict") or {}).get("verdict", ""), "cost": data.get("cost", {}),
            "posts": len([p for p in data.get("posts", []) if p.get("url")]), "version": data.get("version", 1),
            "waiting": data.get("waiting")}


def list_campaigns(output_dir) -> list:
    out = []
    base = root(output_dir)
    if base.exists():
        for path in base.iterdir():
            if (path / "campaign.json").exists():
                try:
                    out.append(summary(path))
                except CampaignError:
                    continue
    return sorted(out, key=lambda c: c.get("created_at") or "", reverse=True)


def stats(output_dir) -> dict:
    items = list_campaigns(output_dir)
    week = (datetime.now() - timedelta(days=7)).isoformat()
    return {"total": len(items), "week": sum(1 for c in items if (c.get("created_at") or "") >= week),
            "posts": sum(c["posts"] for c in items), "running": sum(1 for c in items if c["status"] == "running"),
            "waiting": sum(1 for c in items if c["status"] == "waiting"),
            "cost_usd": round(sum((c.get("cost") or {}).get("usd", 0) for c in items), 4)}


# ====================================================================== thư viện
def _lib(name: str, default):
    return _read(LIB / name, default)


def _lib_save(name: str, data) -> None:
    with _lock:
        _write(LIB / name, data)


def import_image(src, dest_dir: Path, prefix: str = "") -> str:
    """Chép ảnh vào thư viện/chiến dịch; WEBP/JPG đổi sang PNG (giữ tên gốc đã chuẩn hoá)."""
    src = Path(src)
    if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
        raise CampaignError(f"Ảnh không hợp lệ: {src.name}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}{slugify(src.stem, 40) or 'anh'}"
    dest, n = dest_dir / f"{stem}.png", 2
    while dest.exists():
        dest, n = dest_dir / f"{stem}-{n}.png", n + 1
    if src.suffix.lower() == ".png":
        shutil.copy2(src, dest)
    else:
        from PIL import Image
        with Image.open(src) as im:
            im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(dest, "PNG")
    return dest.name


# ---- sản phẩm
def products() -> list:
    return _lib("products.json", [])


def save_product(item: dict, new_images: list | None = None) -> list:
    items = products()
    pid = item.get("id") or f"sp-{slugify(item.get('name') or 'san-pham', 30)}-{datetime.now():%H%M%S}"
    if not (item.get("name") or "").strip():
        raise CampaignError("Nhập tên sản phẩm")
    current = next((p for p in items if p["id"] == pid), None)
    record = {k: str(item.get(k) or "").strip() for k in PRODUCT_FIELDS}
    record["links"] = [u.strip() for u in item.get("links") or [] if str(u).strip().startswith(("http://", "https://"))]
    record["images"] = [f for f in (current or {}).get("images", []) if f in (item.get("images") or [])]
    for src in new_images or []:
        record["images"].append(import_image(src, LIB / "products" / pid))
    record.update(id=pid, updated_at=now(), created_at=(current or {}).get("created_at", now()))
    items = [p for p in items if p["id"] != pid] + [record]
    _lib_save("products.json", items)
    return items


def delete_product(pid: str) -> list:
    items = [p for p in products() if p["id"] != pid]
    _lib_save("products.json", items)
    return items


# ---- ảnh tham chiếu & người mẫu
def refs() -> list:
    return _lib("refs.json", [])


def add_refs(files: list, tags: list) -> list:
    items = refs()
    for src in files:
        items.append({"file": import_image(src, LIB / "refs"), "tags": [t.strip() for t in tags if t.strip()],
                      "created_at": now()})
    _lib_save("refs.json", items)
    return items


def update_ref(file: str, tags: list) -> list:
    items = refs()
    for r in items:
        if r["file"] == file:
            r["tags"] = [t.strip() for t in tags if t.strip()]
    _lib_save("refs.json", items)
    return items


def delete_ref(file: str) -> list:
    items = [r for r in refs() if r["file"] != file]
    _lib_save("refs.json", items)  # giữ file ảnh trên đĩa (không xoá ảnh tham chiếu)
    return items


def models() -> list:
    return _lib("models.json", [])


def save_model(item: dict, image: str = "") -> list:
    items = models()
    mid = item.get("id") or f"nm-{slugify(item.get('name') or 'nguoi-mau', 30)}-{datetime.now():%H%M%S}"
    if not (item.get("name") or "").strip():
        raise CampaignError("Nhập tên người mẫu")
    current = next((m for m in items if m["id"] == mid), {})
    record = {"id": mid, "name": item["name"].strip(), "profile": str(item.get("profile") or "").strip(),
              "file": current.get("file", ""), "created_at": current.get("created_at", now()), "updated_at": now()}
    if image:
        record["file"] = import_image(image, LIB / "models")
    if not record["file"]:
        raise CampaignError("Chọn ảnh người mẫu")
    _lib_save("models.json", [m for m in items if m["id"] != mid] + [record])
    return models()


def delete_model(mid: str) -> list:
    items = [m for m in models() if m["id"] != mid]
    _lib_save("models.json", items)
    return items


# ---- phong cách & mẫu content
def styles() -> list:
    return _lib("styles.json", DEFAULT_STYLES)


def save_styles(items: list) -> list:
    clean = [{"id": s.get("id") or slugify(s.get("name", ""), 30), "name": str(s.get("name", "")).strip(),
              "prompt": str(s.get("prompt", "")).strip()} for s in items if str(s.get("name", "")).strip()]
    _lib_save("styles.json", clean or DEFAULT_STYLES)
    return styles()


def content_template() -> str:
    path = LIB / "content-template.md"
    if path.exists():
        return path.read_text("utf-8")
    src = AGENTS_DIR / "mau-content.md"
    return src.read_text("utf-8") if src.exists() else DEFAULT_TEMPLATE


def save_content_template(text: str) -> str:
    LIB.mkdir(parents=True, exist_ok=True)
    keep_old(LIB / "content-template.md")
    (LIB / "content-template.md").write_text(text, "utf-8")
    return text


# ---- vai trò AI (system prompt có lịch sử phiên bản, model, effort)
def _strip_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text.replace("\r\n", "\n"), flags=re.S).strip()


def roles() -> dict:
    data = _lib("roles.json", {})
    for rid, spec in ROLES.items():
        role = data.setdefault(rid, {})
        role.setdefault("name", spec["name"])
        role.setdefault("model", spec["model"])
        role.setdefault("effort", spec["effort"])
        role.setdefault("web", spec.get("web", False))
        if not role.get("prompt"):
            src = AGENTS_DIR / "agents" / f"{rid}.md"
            role["prompt"] = _strip_frontmatter(src.read_text("utf-8")) if src.exists() else ""
            role["source"] = str(src) if src.exists() else ""
        role.setdefault("versions", [])
    return data


def save_role(rid: str, prompt: str | None = None, model: str | None = None, effort: str | None = None) -> dict:
    if rid not in ROLES:
        raise CampaignError("Vai trò không hợp lệ")
    data = roles()
    role = data[rid]
    if prompt is not None and prompt.strip() != role.get("prompt", "").strip():
        role["versions"] = (role.get("versions") or [])[-19:] + [{"at": now(), "prompt": role.get("prompt", "")}]
        role["prompt"] = prompt.strip()
    if model:
        role["model"] = model.strip()
    if effort in ("low", "medium", "high", "xhigh", "max"):
        role["effort"] = effort
    _lib_save("roles.json", data)
    return data


# ---- lịch sử đăng & chi phí
def log_post(entry: dict) -> None:
    items = _lib("posts-history.json", [])
    items.append({**entry, "at": now()})
    _lib_save("posts-history.json", items[-2000:])


def post_history() -> list:
    return list(reversed(_lib("posts-history.json", [])))


def log_ai_call(entry: dict) -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    with _lock, open(LIB / "ai-calls.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**entry, "at": now()}, ensure_ascii=False) + "\n")


def ai_calls(limit: int = 500) -> list:
    path = LIB / "ai-calls.jsonl"
    if not path.exists():
        return []
    lines = path.read_text("utf-8").splitlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def library() -> dict:
    return {"products": products(), "refs": refs(), "models": models(), "styles": styles(),
            "template": content_template(), "roles": roles(), "agents_dir": str(AGENTS_DIR)}


def refs_dir() -> Path:
    return LIB / "refs"


def models_dir() -> Path:
    return LIB / "models"


def product_dir(pid: str) -> Path:
    return LIB / "products" / pid


__all__ = ["CampaignError", "STAGES", "ROLES", "STATUSES", "unique_dir"]
