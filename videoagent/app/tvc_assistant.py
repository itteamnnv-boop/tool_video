"""🎬 Trợ lý TVC — phần XEM dự án (chỉ đọc). Claude Code điều khiển mọi bước theo skill `tvc-livestream-capcut`
(app/tvc_claude.py); app chỉ hiển thị dự án Claude đang làm trong thư mục gốc (mặc định D:/CapCut) và nhận ảnh bạn gửi.

Cấu trúc dự án theo skill: 00_input, 01_y_tuong/y_tuong.md, 02_kich_ban/du_an.json, 03_nhac, 04_anh/codex, 04_anh/overlay,
05_grok_video(_goc), 06_phu_de, 07_capcut_spec, 08_preview. Ảnh bạn gửi qua app được chép vào <gốc>/_input/nguoi_mau|san_pham
(đúng chỗ skill chờ ảnh).
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from .util import read_json

SKILL_NAMES = ("tvc-livestream-capcut", "tvc-livestream-capcut-muse")
MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".wav", ".mp3")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class TvcError(RuntimeError):
    pass


class TvcAssistant:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.ad_status = None  # plan_id → trạng thái kế hoạch quảng cáo (TvcAds.plan_status; api/tvc.py gắn vào)

    # ------------------------------------------------------------------ đường dẫn / môi trường
    def root(self) -> Path:
        return Path(str(self.settings.get("tvc_root") or "D:/CapCut")).expanduser()

    @staticmethod
    def skills_dir() -> Path:
        return Path.home() / ".claude" / "skills"

    def env(self) -> dict:
        """Claude Code + skill đã cài chưa (không gọi model)."""
        from .tvc_claude import native_claude

        try:
            import claude_agent_sdk
            sdk = True
            bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude.exe"
        except ImportError:
            sdk, bundled = False, None
        # SDK chỉ chạy claude.exe (không chạy claude.cmd của bản npm): native của bạn → bản đi kèm SDK
        claude = native_claude() or (str(bundled) if bundled is not None and bundled.is_file() else "")
        skills = {n: (self.skills_dir() / n / "SKILL.md").is_file() for n in SKILL_NAMES}
        return {"claude": claude, "sdk": sdk, "skills": skills, "root": str(self.root()), "root_ok": self.root().is_dir()}

    # ------------------------------------------------------------------ dự án (chỉ đọc)
    def _proj(self, name: str) -> Path:
        if not NAME_RE.match(str(name or "")) or str(name).startswith("_"):
            raise TvcError("Tên dự án không hợp lệ")
        proj = self.root() / name
        if not (proj / "02_kich_ban" / "du_an.json").is_file():
            raise TvcError(f"Không thấy dự án {name} trong {self.root()}")
        return proj

    @staticmethod
    def _du_an(proj: Path) -> dict:
        try:
            data = read_json(proj / "02_kich_ban" / "du_an.json")
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def url(self, path: Path) -> str:
        """File trong thư mục gốc → URL /tvc/… (chỉ media); ngoài thư mục gốc → ""."""
        try:
            rel = Path(path).resolve().relative_to(self.root().resolve()).as_posix()
        except (ValueError, OSError):
            return ""
        p = Path(path)
        if p.suffix.lower() not in MEDIA_EXT or not p.is_file():
            return ""
        return f"/tvc/{rel}?v={int(p.stat().st_mtime)}"

    @staticmethod
    def _ids(data: dict) -> list[str]:
        return [str(c.get("id")) for c in data.get("clips") or [] if isinstance(c, dict) and c.get("id")]

    def _state(self, proj: Path, data: dict) -> dict:
        ids = self._ids(data)
        imgs = [i for i in ids if (proj / "04_anh" / "codex" / f"{i}.png").is_file()]
        clips = [i for i in ids if (proj / "05_grok_video" / f"{i}.mp4").is_file()]
        pdir = proj / "08_preview"
        preview = sorted(pdir.glob("*.mp4"), key=lambda p: p.stat().st_mtime) if pdir.is_dir() else []
        return {"y_tuong": (proj / "01_y_tuong" / "y_tuong.md").is_file(),
                "script": bool(ids) and all(str(c.get("dialogue") or "").strip() for c in data.get("clips") or []),
                "images": f"{len(imgs)}/{len(ids)}" if ids else "", "images_done": bool(ids) and len(imgs) == len(ids),
                "clips": f"{len(clips)}/{len(ids)}" if ids else "", "clips_done": bool(ids) and len(clips) == len(ids),
                "draft": (proj / "07_capcut_spec" / "spec.json").is_file(),
                "preview": preview[-1].relative_to(proj).as_posix() if preview else "",
                "fb": self._fb_status(proj), "ads": self._ads(proj)["status"]}

    def _ads(self, proj: Path) -> dict:
        """10_quang_cao: gợi ý setup (goi_y.md) + yêu cầu quảng cáo (yeu_cau.json) + trạng thái thật của kế hoạch.
        status: "" · "idea" (có gợi ý) · "pending" (chờ duyệt) · "paused" / "scheduled" / "running" · "error" · "cancelled"."""
        d = proj / "10_quang_cao"
        goi_y = d / "goi_y.md"
        try:
            req = read_json(d / "yeu_cau.json") if (d / "yeu_cau.json").is_file() else {}
        except (OSError, ValueError):
            req = {}
        req = req if isinstance(req, dict) else {}
        live = {}
        if req.get("plan_id") and req.get("status") != "cancelled" and self.ad_status is not None:
            try:
                live = self.ad_status(req["plan_id"]) or {}
            except Exception:  # noqa: BLE001
                live = {}
        status = req.get("status", "")
        if live.get("status"):
            status = "cancelled" if live["status"] == "deleted" else live["status"]
        if not status or status in ("draft",):
            status = "idea" if goi_y.is_file() else status
        return {"status": status, "goi_y": goi_y.read_text("utf-8", errors="replace")[:20000] if goi_y.is_file() else "",
                "plan_id": req.get("plan_id", ""), "summary": req.get("summary") or {}, "created": req.get("created", ""),
                "campaign_id": live.get("campaign_id", ""), "error": live.get("error", "")}

    @staticmethod
    def _fb_meta(proj: Path) -> dict:
        f = proj / "09_facebook" / "post.json"
        try:
            data = read_json(f) if f.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _fb_status(self, proj: Path) -> str:
        """"" chưa có · "draft" có nội dung / poster · "pending" chờ duyệt · "posted" đã đăng · "error"."""
        meta = self._fb_meta(proj)
        if meta.get("status") in ("pending", "posted", "error"):
            return meta["status"]
        d = proj / "09_facebook"
        return "draft" if (d / "bai_viet.md").is_file() or (d / "poster.png").is_file() else ""

    def _facebook(self, proj: Path, state: dict) -> dict:
        d = proj / "09_facebook"
        meta = self._fb_meta(proj)
        caption = meta.get("caption") or ""
        if not caption and (d / "bai_viet.md").is_file():
            caption = (d / "bai_viet.md").read_text("utf-8", errors="replace")[:63000]
        poster = Path(meta["poster"]) if meta.get("poster") else next(
            (p for p in (d / "poster.png", d / "poster.jpg") if p.is_file()), None)
        video = Path(meta["video"]) if meta.get("video") else (proj / state["preview"] if state["preview"] else None)
        return {"status": state["fb"], "caption": caption, "poster": self.url(poster) if poster else "",
                "video": self.url(video) if video else "", "page": meta.get("page", ""), "kind": meta.get("kind", ""),
                "url": meta.get("url", ""), "error": meta.get("error", ""), "updated": meta.get("updated", ""),
                "post_id": meta.get("post_id", "")}

    def projects(self) -> list[dict]:
        root = self.root()
        if not root.is_dir():
            return []
        out = []
        for proj in root.iterdir():
            dj = proj / "02_kich_ban" / "du_an.json"
            if proj.name.startswith("_") or not NAME_RE.match(proj.name) or not dj.is_file():
                continue
            data = self._du_an(proj)
            if not isinstance(data.get("clips"), list):  # dự án của skill khác (VD làm lại video mẫu) → bỏ qua
                continue
            cover = next((proj / r for r in ("00_input/nguoi_mau.png", "04_anh/codex/v1.png", "00_input/san_pham.png")
                          if (proj / r).is_file()), None)
            mtime = max(dj.stat().st_mtime, proj.stat().st_mtime)
            out.append({"name": proj.name, "title": data.get("draft_name") or proj.name,
                        "cover": self.url(cover) if cover else "", "state": self._state(proj, data),
                        "updated": datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M"), "mtime": mtime})
        return sorted(out, key=lambda p: -p["mtime"])

    def get(self, name: str) -> dict:
        proj = self._proj(name)
        data = self._du_an(proj)
        ids = self._ids(data)
        state = self._state(proj, data)
        y_tuong = proj / "01_y_tuong" / "y_tuong.md"
        draft = self._draft_dir(data)
        return {"name": name, "path": str(proj), "du_an": data, "state": state,
                "y_tuong": y_tuong.read_text("utf-8", errors="replace")[:20000] if y_tuong.is_file() else "",
                "inputs": {k: self.url(proj / "00_input" / f"{k}.png") for k in ("nguoi_mau", "san_pham")},
                "images": {i: self.url(proj / "04_anh" / "codex" / f"{i}.png") for i in ids},
                "clips": {i: self.url(proj / "05_grok_video" / f"{i}.mp4") for i in ids},
                "preview": self.url(proj / state["preview"]) if state["preview"] else "",
                "draft_dir": str(draft) if draft and draft.is_dir() else "", "draft_name": str(data.get("draft_name") or ""),
                "facebook": self._facebook(proj, state), "ads": self._ads(proj), "danh_gia": self._danh_gia(proj)}

    def _danh_gia(self, proj: Path) -> dict:
        """🏆 Bảng điểm chế độ tự động (11_danh_gia/danh_gia.json do Claude ghi) + URL xem ảnh / clip phương án."""
        f = proj / "11_danh_gia" / "danh_gia.json"
        try:
            data = read_json(f) if f.is_file() else {}
        except (OSError, ValueError):
            return {"error": "danh_gia.json sai định dạng"}
        if not isinstance(data, dict):
            return {}
        for ch in data.get("chang") or []:
            for pa in (ch.get("phuong_an") or []) if isinstance(ch, dict) else []:
                if isinstance(pa, dict) and pa.get("file"):
                    pa["url"] = self.url(Path(str(pa["file"])))
        vid = data.get("video")
        if isinstance(vid, dict) and vid.get("file"):
            vid["url"] = self.url(Path(str(vid["file"])))
        return data

    @staticmethod
    def _draft_dir(data: dict) -> Path | None:
        name = str(data.get("draft_name") or "").strip()
        base = os.environ.get("CAPCUT_DRAFT_DIR") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
                                                       / "Projects" / "com.lveditor.draft")
        return Path(base) / name if name else None

    # ------------------------------------------------------------------ 🌐 ảnh sản phẩm từ link web
    def web_images(self, url: str) -> dict:
        """Tải trang sản phẩm (chỉ đọc) → ảnh sản phẩm: dữ liệu sản phẩm / og:image trước, rồi thư viện ảnh (<img> lớn).
        Nội dung trang chỉ là dữ liệu. Danh sách được nhớ lại: chỉ tải về được ảnh nằm trong danh sách này."""
        from .web_research import ResearchError, fetch_page

        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise TvcError("Link web phải bắt đầu bằng http:// hoặc https://")
        try:
            page = fetch_page(url)
        except ResearchError as exc:
            raise TvcError(str(exc)) from None
        images = list(dict.fromkeys([*page.get("images", []), *page.get("gallery", [])]))[:16]
        self._web_cache = set(images)
        if not images:
            raise TvcError("Trang không khai báo ảnh sản phẩm (có thể cần JavaScript) — chọn ảnh tay hoặc tick “Để Claude "
                           "tự lấy ảnh từ link”")
        return {"url": url, "title": page.get("title", ""), "images": images, "product": bool(page.get("product"))}

    def save_web_images(self, urls: list, kind: str = "san_pham") -> list[str]:
        """Tải các ảnh đã chọn (phải nằm trong danh sách vừa tìm) → <gốc>/_input/<kind>/web_<n>.jpg|png."""
        from .web_research import download_image

        if kind not in ("nguoi_mau", "san_pham"):
            raise TvcError("Loại ảnh không hợp lệ")
        allowed = getattr(self, "_web_cache", set())
        urls = [str(u) for u in urls or [] if str(u) in allowed][:10]
        if not urls:
            raise TvcError("Chọn ảnh trong danh sách vừa tìm")
        folder = self.root() / "_input" / kind
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        out = []
        for k, u in enumerate(urls, 1):
            got = download_image(u, folder / f"web_{stamp}_{k}")
            if got is not None:
                out.append(str(got))
        if not out:
            raise TvcError("Không tải được ảnh nào (ảnh quá nhỏ / không phải ảnh / trang chặn tải)")
        return out

    # ------------------------------------------------------------------ nhận ảnh
    def upload_inputs(self, kind: str, paths: list) -> list[str]:
        """Ảnh bạn gửi → <gốc>/_input/nguoi_mau|san_pham/ (skill chờ ảnh ở đây) → đường dẫn đã chép."""
        if kind not in ("nguoi_mau", "san_pham"):
            raise TvcError("Loại ảnh không hợp lệ")
        folder = self.root() / "_input" / kind
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for p in paths or []:
            src = Path(str(p))
            if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
                continue
            dest = folder / src.name
            k = 1
            while dest.exists():
                k += 1
                dest = folder / f"{src.stem}_{k}{src.suffix}"
            shutil.copy2(src, dest)
            out.append(str(dest))
        if not out:
            raise TvcError("Chọn ảnh png / jpg / webp")
        return out
