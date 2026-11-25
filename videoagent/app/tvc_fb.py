"""📣 Trợ lý TVC · bài Facebook: cầu nối giữa Claude (công cụ MCP trong app) và Quản lý bài đăng / Fanpage của app.

- Claude KHÔNG thấy token: chỉ nhận id + tên Fanpage đã kết nối; mọi lời gọi Graph API do app làm (PostStore → FacebookManager).
- fb_create_post: lưu bài CHỜ DUYỆT (chưa đăng gì) vào Quản lý bài đăng + ghi <dự án>/09_facebook/post.json để màn hiển thị.
- publish(): chỉ chạy sau khi người dùng bấm "Đăng ngay" trên thẻ xác nhận (tvc_claude kiểm tra mã xác nhận 1 lần).
- File poster / video phải nằm trong thư mục gốc TVC (Claude không thể bắt app chép file tuỳ ý ra ngoài).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .util import read_json, write_json

FB_DIR = "09_facebook"
KINDS = {"reel": "Reels (video dọc) + nội dung", "feed": "Video thường + nội dung", "poster": "Poster (ảnh) + nội dung"}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".webm")


class TvcFbError(RuntimeError):
    pass


class TvcFacebook:
    def __init__(self, facebook, posts, viewer, on_change=None) -> None:
        self.facebook = facebook
        self.posts = posts
        self.viewer = viewer
        self.on_change = on_change or (lambda: None)

    # ------------------------------------------------------------------ Fanpage (chỉ id + tên)
    def pages(self) -> list[dict]:
        if self.facebook is None:
            return []
        try:
            pages = self.facebook.state().get("pages") or []
        except Exception:  # noqa: BLE001 — chưa cấu hình Facebook
            return []
        return [{"id": str(p.get("id")), "name": str(p.get("name") or p.get("id"))} for p in pages if p.get("connected")]

    # ------------------------------------------------------------------ file trong dự án
    def _proj(self, name: str) -> Path:
        return self.viewer._proj(name)  # kiểm tên + có du_an.json

    def _file(self, proj: Path, raw: str, exts: tuple) -> Path | None:
        raw = str(raw or "").strip()
        if not raw:
            return None
        p = Path(raw)
        p = (p if p.is_absolute() else proj / p).resolve()
        try:
            p.relative_to(self.viewer.root().resolve())
        except ValueError:
            raise TvcFbError(f"File phải nằm trong thư mục {self.viewer.root()}: {raw}") from None
        if not p.is_file() or p.suffix.lower() not in exts:
            raise TvcFbError(f"Không thấy file hợp lệ ({'/'.join(exts)}): {raw}")
        return p

    @staticmethod
    def _meta_path(proj: Path) -> Path:
        return proj / FB_DIR / "post.json"

    def meta(self, proj: Path) -> dict:
        f = self._meta_path(proj)
        try:
            data = read_json(f) if f.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _write_meta(self, proj: Path, **fields) -> dict:
        data = {**self.meta(proj), **fields, "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        f = self._meta_path(proj)
        f.parent.mkdir(parents=True, exist_ok=True)
        write_json(f, data)
        return data

    # ------------------------------------------------------------------ tạo bài chờ duyệt
    def create(self, project: str, caption: str, poster: str = "", video: str = "", page_id: str = "",
               kind: str = "reel") -> dict:
        proj = self._proj(project)
        caption = str(caption or "").strip()
        if not caption:
            raise TvcFbError("Thiếu nội dung bài viết")
        poster_p = self._file(proj, poster, IMAGE_EXT)
        video_p = self._file(proj, video, VIDEO_EXT)
        if not poster_p and not video_p:
            raise TvcFbError("Cần poster hoặc video")
        kind = kind if kind in KINDS else ("reel" if video_p else "poster")
        if kind != "poster" and not video_p:
            kind = "poster"
        pages = self.pages()
        page = next((p for p in pages if p["id"] == str(page_id)), pages[0] if pages else None)
        (proj / FB_DIR).mkdir(parents=True, exist_ok=True)
        (proj / FB_DIR / "bai_viet.md").write_text(caption, "utf-8")
        files = [str(x) for x in (video_p, poster_p) if x]
        post = self.posts.pending_new(source="tvc", source_name=f"Trợ lý TVC · {project}",
                                      kind="reel" if kind == "reel" else "feed", caption=caption, files=files,
                                      page_id=page["id"] if page else "", page=page["name"] if page else "")
        meta = self._write_meta(proj, post_id=post["id"], kind=kind, page_id=page["id"] if page else "",
                                page=page["name"] if page else "", caption=caption,
                                poster=str(poster_p or ""), video=str(video_p or ""), status="pending", url="", error="")
        self.on_change()
        return {"post_id": post["id"], "status": "pending", "kind": kind, "page": meta["page"], "pages": pages,
                "note": "Bài đã lưu CHỜ DUYỆT trong Quản lý bài đăng (chưa đăng). Gọi fb_publish để người dùng xác nhận."}

    def card(self, post_id: str) -> dict:
        """Dữ liệu thẻ xác nhận đăng (nội dung, poster, video, Fanpage) — không có token."""
        proj, meta = self._find(post_id)
        return {"post_id": post_id, "project": proj.name, "caption": meta.get("caption", ""), "kind": meta.get("kind", "reel"),
                "kinds": [{"value": k, "label": v} for k, v in KINDS.items()],
                "page_id": meta.get("page_id", ""), "pages": self.pages(),
                "poster": self.viewer.url(Path(meta["poster"])) if meta.get("poster") else "",
                "video": self.viewer.url(Path(meta["video"])) if meta.get("video") else ""}

    def _find(self, post_id: str) -> tuple[Path, dict]:
        root = self.viewer.root()
        for f in root.glob(f"*/{FB_DIR}/post.json"):
            try:
                meta = read_json(f)
            except (OSError, ValueError):
                continue
            if isinstance(meta, dict) and meta.get("post_id") == post_id:
                return f.parent.parent, meta
        raise TvcFbError("Không thấy bài này trong dự án TVC — tạo lại bằng fb_create_post")

    # ------------------------------------------------------------------ đăng (sau khi người dùng xác nhận)
    def publish(self, post_id: str, page_id: str, kind: str, caption: str) -> dict:
        proj, meta = self._find(post_id)
        kind = kind if kind in KINDS else meta.get("kind", "reel")
        caption = str(caption or meta.get("caption") or "").strip()
        if not page_id:
            raise TvcFbError("Chưa chọn Fanpage")
        if kind != "poster" and not meta.get("video"):
            raise TvcFbError("Bài không có video")
        if kind == "poster" and not meta.get("poster"):
            raise TvcFbError("Bài không có poster")

        def apply(p):
            p["caption"] = caption
            p["kind"] = "reel" if kind == "reel" else "feed"
            names = p.get("files") or []
            if kind == "poster":
                p["files"] = [n for n in names if n.lower().endswith(IMAGE_EXT)]
            else:  # video lên trước; poster giữ trong bài để dùng chạy quảng cáo / đăng sau
                p["files"] = sorted(names, key=lambda n: not n.lower().endswith(VIDEO_EXT))

        self.posts._update(post_id, apply)
        res = self.posts.publish(post_id, [page_id], True)
        ok = [r for r in res.get("results") or [] if r.get("post_id") or r.get("url")]
        err = "; ".join(r.get("error") for r in res.get("results") or [] if r.get("error"))
        page = next((p["name"] for p in self.pages() if p["id"] == page_id), page_id)
        self._write_meta(proj, kind=kind, caption=caption, page_id=page_id, page=page,
                         status="posted" if ok else "error", url=(ok[0].get("url") if ok else ""), error=err[:500],
                         fb_post_id=(ok[0].get("post_id") if ok else ""))  # Reels: có thể là id video → tvc_ads tra lại
        if caption != meta.get("caption"):
            (proj / FB_DIR / "bai_viet.md").write_text(caption, "utf-8")
        self.on_change()
        if not ok:
            raise TvcFbError(f"Facebook báo lỗi: {err or 'không rõ'}")
        return {"status": "posted", "page": page, "url": ok[0].get("url", ""), "post_id": post_id}

    @staticmethod
    def text(data, error: bool = False) -> dict:
        out = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
        if error:
            out["is_error"] = True
        return out
