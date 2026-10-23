"""Studio Muse AI · tư liệu (nhân vật, mẫu prompt, người mẫu, ảnh luân phiên) + nhập ảnh."""
import base64
import shutil
import uuid
from pathlib import Path

from . import common as _c
from .common import HubError, _uid, asset_url


class AssetsMixin:
    # ------------------------------------------------------------ tư liệu
    def _copy_asset(self, src: str) -> str:
        p = Path(src)
        if not p.is_file():
            raise HubError(f"Không thấy ảnh: {src}")
        assets = _c.STORE / "assets"
        if p.parent == assets:
            return str(p)
        assets.mkdir(parents=True, exist_ok=True)
        dest = assets / f"{uuid.uuid4().hex[:12]}{p.suffix.lower()}"
        shutil.copy2(p, dest)
        return str(dest)

    def _all_assets(self) -> list:
        return [*self.hub["model"]["images"], *self.hub["rotate"]["images"],
                *(i for c in self.hub["characters"] for i in c.get("images") or [])]

    def asset(self, kind: str, data: dict) -> dict:
        before = self._all_assets()
        data = data or {}
        if kind == "character":
            name = " ".join(str(data.get("name") or "").split())[:40]
            if not name:
                raise HubError("Nhập tên nhân vật (gõ đúng tên này trong prompt để tự gắn ảnh)")
            images = [self._copy_asset(i) for i in (data.get("images") or [])][:3]
            hit = next((c for c in self.hub["characters"] if c["id"] == data.get("id")), None)
            if hit:
                hit.update(name=name, images=images)
            else:
                self.hub["characters"].append({"id": _uid("c"), "name": name, "images": images})
        elif kind == "character_delete":
            self.hub["characters"] = [c for c in self.hub["characters"] if c["id"] != data.get("id")]
            if self.hub["model"].get("character") == data.get("id"):
                self.hub["model"]["character"] = ""  # nhân vật làm người mẫu bị xoá → về ảnh tải riêng
        elif kind == "template":
            text = str(data.get("text") or "").strip()[:4000]
            if not text:
                raise HubError("Mẫu prompt trống")
            name = " ".join(str(data.get("name") or "").split())[:60] or text[:40]
            hit = next((t for t in self.hub["templates"] if t["id"] == data.get("id")), None)
            if hit:
                hit.update(name=name, text=text)
            else:
                self.hub["templates"].append({"id": _uid("t"), "name": name, "text": text})
        elif kind == "template_delete":
            self.hub["templates"] = [t for t in self.hub["templates"] if t["id"] != data.get("id")]
        elif kind in ("model", "rotate"):
            box = self.hub[kind]
            if "on" in data:
                box["on"] = bool(data["on"])
            if kind == "model" and "character" in data:
                cid = str(data.get("character") or "")
                if cid and not any(c["id"] == cid for c in self.hub["characters"]):
                    raise HubError("Không thấy nhân vật này")
                box["character"] = cid
            if "images" in data:
                box["images"] = [self._copy_asset(i) for i in data["images"]][:3 if kind == "model" else 20]
                if kind == "rotate":
                    box["idx"] = 0
        else:
            raise HubError("Loại tư liệu không hợp lệ")
        used = set(self._all_assets())  # ảnh bị bỏ khỏi danh sách → xoá bản chép
        for p in before:
            if p not in used and Path(p).parent == _c.STORE / "assets":
                Path(p).unlink(missing_ok=True)
        self._save()
        self._push()
        return self.state()

    def import_images(self, paths: list) -> list:
        """Ảnh tham chiếu chọn từ máy → chép vào kho uploads (xem trước được, đường dẫn gốc đổi / xoá không hỏng)."""
        folder = _c.STORE / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for src in paths or []:
            p = Path(str(src))
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                dest = folder / f"{uuid.uuid4().hex[:12]}{p.suffix.lower()}"
                shutil.copy2(p, dest)
                out.append({"path": str(dest), "url": asset_url(str(dest)), "name": p.name})
        return out

    def import_data(self, name: str, data_url: str) -> list:
        """Ảnh kéo thả vào app (data URL) → kho uploads. Chỉ nhận png / jpg / webp, tối đa 20MB."""
        head, _, body = str(data_url or "").partition(",")
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(head[5:].split(";")[0])
        if not ext or ";base64" not in head:
            raise HubError(f"{name}: chỉ nhận ảnh PNG / JPG / WEBP")
        raw = base64.b64decode(body, validate=False)
        if len(raw) > 20 * 1024 * 1024:
            raise HubError(f"{name}: ảnh quá lớn (tối đa 20MB)")
        folder = _c.STORE / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{uuid.uuid4().hex[:12]}{ext}"
        dest.write_bytes(raw)
        return [{"path": str(dest), "url": asset_url(str(dest)), "name": str(name or dest.name)[:120]}]

    def _take_rotate(self) -> str:
        r = self.hub["rotate"]
        imgs = r.get("images") or []
        if not imgs:
            return ""
        i = int(r.get("idx") or 0) % len(imgs)
        r["idx"] = i + 1
        return imgs[i]
