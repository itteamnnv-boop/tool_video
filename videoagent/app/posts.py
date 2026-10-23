"""Quản lý bài đăng Facebook: lưu mọi bài (nháp / đã đăng / hẹn giờ / lỗi) cùng BẢN SAO ảnh–video để sửa và đăng lại.

- Bài đăng thành công từ Thư viện video, Workflow, Chiến dịch tự được lưu ở đây (record).
- Người dùng tạo / sửa bài nháp, rồi đăng (lại) lên một hoặc nhiều Fanpage — có thể hẹn giờ.
- Mỗi lần đăng ghi lại: Fanpage, thời điểm, ai xác nhận, link bài / lỗi. Không bao giờ tự đăng: publish() chỉ chạy
  khi giao diện gửi confirmed=True (người dùng bấm xác nhận).
- Lên lịch (app tự đăng): người dùng xác nhận lịch (giờ + Fanpage) → bài ở trạng thái "queued"; bộ hẹn giờ (PostScheduler)
  đăng đúng giờ khi app đang mở. Bài lên lịch vẫn sửa được nội dung / đổi giờ / huỷ lịch / đăng ngay. Mở app trễ quá
  GRACE giây so với giờ hẹn → KHÔNG tự đăng, chuyển "missed" (lỡ lịch) chờ người dùng quyết định.
  Khác "scheduled" = hẹn giờ trên chính Facebook (Facebook tự đăng, 10 phút → 30 ngày, không sửa được từ app).

Dữ liệu: DATA_DIR/posts/posts.json; file: DATA_DIR/posts/media/<id>/ (phục vụ qua /post-media/, chỉ ảnh/video).
"""
import getpass
import json
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .paths import DATA_DIR

POSTS_DIR = DATA_DIR / "posts"
POSTS_FILE = POSTS_DIR / "posts.json"
MEDIA_DIR = POSTS_DIR / "media"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
POST_TYPES = {  # cùng danh sách với block Đăng bài Facebook (workflow)
    "feed": "Ảnh/video kèm bài viết (feed)",
    "text": "Chỉ bài viết (chữ)",
    "media": "Chỉ ảnh/video (không chữ)",
    "reel": "Reels (video dọc)",
    "story": "Story (ảnh/video hiện 24 giờ)",
}
SCHEDULABLE = ("feed", "text", "media", "reel")
SCHEDULE_MIN, SCHEDULE_MAX = 10 * 60, 30 * 24 * 3600  # Facebook: hẹn giờ 10 phút → 30 ngày
APP_SCHEDULE_MIN, APP_SCHEDULE_MAX = 60, 365 * 24 * 3600  # lên lịch app tự đăng: 1 phút → 1 năm
GRACE = 15 * 60  # mở app trễ hơn giờ hẹn quá 15 phút → không tự đăng (lỡ lịch), chờ người dùng
SOURCES = {"manual": "Tạo tay", "quick": "Đăng nhanh (Fanpage)", "library": "Thư viện video", "workflow": "Workflow",
           "campaign": "Chiến dịch"}
MAX_POSTS = 3000
MAX_FILES = 10
_LOCK = threading.RLock()  # chung mọi PostStore (API, Workflow, Chiến dịch cùng ghi posts.json)


class PostError(RuntimeError):
    pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def who() -> str:
    return f"{getpass.getuser()} (ứng dụng trên máy này)"


class PostStore:
    def __init__(self, facebook=None) -> None:
        self.facebook = facebook
        self._lock = _LOCK

    # ------------------------------------------------------------------ lưu trữ
    def _load(self) -> list[dict]:
        try:
            return json.loads(POSTS_FILE.read_text("utf-8")).get("posts", [])
        except (OSError, ValueError, AttributeError):
            return []

    def _save(self, posts: list[dict]) -> None:
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = POSTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"posts": posts[-MAX_POSTS:]}, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(POSTS_FILE)

    def _update(self, pid: str, fn) -> dict:
        with self._lock:
            posts = self._load()
            post = next((p for p in posts if p["id"] == pid), None)
            if post is None:
                raise PostError("Không tìm thấy bài đăng")
            fn(post)
            post["updated_at"] = now()
            self._save(posts)
            return post

    @staticmethod
    def _copy_media(pid: str, files: list) -> list[str]:
        """Chép file vào media/<id>/ (file đã nằm trong đó thì giữ nguyên). Trả về tên file (tương đối)."""
        folder = MEDIA_DIR / pid
        folder.mkdir(parents=True, exist_ok=True)
        names = []
        for raw in files[:MAX_FILES]:
            path = Path(str(raw))
            if path.parent.resolve() == folder.resolve() and path.is_file():
                names.append(path.name)
                continue
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
                raise PostError(f"File không hợp lệ: {path.name}")
            name = f"{len(names) + 1:02d}_{uuid.uuid4().hex[:6]}{path.suffix.lower()}"
            shutil.copy2(path, folder / name)
            names.append(name)
        for old in folder.iterdir():  # bỏ file không còn dùng
            if old.name not in names and old.is_file():
                old.unlink()
        return names

    def public(self, post: dict) -> dict:
        files = [{"name": n, "url": f"/post-media/{post['id']}/{n}", "path": str(MEDIA_DIR / post["id"] / n),
                  "video": Path(n).suffix.lower() in VIDEO_EXT, "exists": (MEDIA_DIR / post["id"] / n).is_file()}
                 for n in post.get("files") or []]
        pubs = post.get("publishes") or []
        ok = [p for p in pubs if p.get("post_id") or p.get("url")]
        sch = post.get("schedule")
        if sch:
            sch = {**sch, "when": datetime.fromtimestamp(sch["at"]).strftime("%H:%M %d/%m/%Y")}
        return {**post, "schedule": sch, "media": files, "type_label": POST_TYPES.get(post.get("kind"), post.get("kind", "")),
                "source_label": SOURCES.get(post.get("source"), post.get("source", "")),
                "posted_count": len(ok), "last_publish": pubs[-1] if pubs else None}

    # ------------------------------------------------------------------ đọc / sửa
    def list(self) -> list[dict]:
        with self._lock:
            posts = self._load()
            ids = {p["id"] for p in posts}
            if MEDIA_DIR.is_dir():  # dọn thư mục của bài đã xoá (lúc xoá file có thể đang bị khoá vì video đang phát)
                for folder in MEDIA_DIR.iterdir():
                    if folder.is_dir() and folder.name not in ids:
                        shutil.rmtree(folder, ignore_errors=True)
        posts.sort(key=lambda p: p.get("updated_at") or p.get("created_at") or "", reverse=True)
        return [self.public(p) for p in posts]

    def save(self, data: dict) -> dict:
        """Tạo mới / sửa bài (nháp hoặc bài đã đăng — sửa để đăng lại). data: {id?, title, caption, kind, files}."""
        kind = data.get("kind") if data.get("kind") in POST_TYPES else "feed"
        caption = str(data.get("caption") or "").strip()[:63000]
        title = " ".join(str(data.get("title") or "").split())[:120]
        files = [str(f) for f in data.get("files") or [] if f]
        if kind == "text":
            files = []
        if not caption and not files:
            raise PostError("Bài cần nội dung hoặc ảnh / video")
        pid = str(data.get("id") or "")
        with self._lock:
            posts = self._load()
            post = next((p for p in posts if p["id"] == pid), None) if pid else None
            if post is None:
                pid = f"p{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}"
                post = {"id": pid, "created_at": now(), "source": "manual", "source_name": "", "status": "draft",
                        "publishes": []}
                posts.append(post)
            post.update(title=title or caption[:60] or "Bài đăng", caption=caption, kind=kind,
                        files=self._copy_media(pid, files), updated_at=now())
            self._save(posts)
        return self.public(post)

    def delete(self, pid: str) -> None:
        with self._lock:
            posts = [p for p in self._load() if p["id"] != pid]
            self._save(posts)
        shutil.rmtree(MEDIA_DIR / pid, ignore_errors=True)

    # ------------------------------------------------------------------ ghi lại bài đăng từ nơi khác
    def record(self, *, source: str, source_name: str, kind: str, caption: str, files: list, page_id: str, page: str,
               result: dict, by: str, scheduled_at: int | None = None) -> dict:
        """Lưu bài vừa đăng thành công (Thư viện / Workflow / Chiến dịch) để quản lý + đăng lại. Bên gọi bỏ qua mọi
        lỗi ở đây — lưu lịch sử không được làm hỏng bài vừa đăng."""
        pid = f"p{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}"
        kind = kind if kind in POST_TYPES else ("text" if not files else "feed")
        entry = self._publish_entry(page_id, page, by, result=result, scheduled_at=scheduled_at)
        with self._lock:  # chép file + ghi bài trong cùng khoá (list() dọn thư mục không thuộc bài nào)
            try:
                names = self._copy_media(pid, [f for f in files if Path(str(f)).is_file()])
            except PostError:
                names = []
            post = {"id": pid, "created_at": now(), "updated_at": now(),
                    "source": source if source in SOURCES else "manual", "source_name": source_name[:120],
                    "title": (caption or source_name or "Bài đăng")[:60], "caption": caption or "", "kind": kind,
                    "files": names, "publishes": [entry], "status": "scheduled" if scheduled_at else "posted"}
            posts = self._load()
            posts.append(post)
            self._save(posts)
        return self.public(post)

    @staticmethod
    def _publish_entry(page_id: str, page: str, by: str, *, result: dict | None = None, error: str = "",
                       scheduled_at: int | None = None) -> dict:
        result = result or {}
        return {"page_id": page_id, "page": result.get("page") or page, "at": now(), "by": by,
                "post_id": result.get("id", ""), "url": result.get("url", ""), "error": error,
                "scheduled": datetime.fromtimestamp(scheduled_at).strftime("%H:%M %d/%m/%Y") if scheduled_at else ""}

    # ------------------------------------------------------------------ đăng / đăng lại
    def publish(self, pid: str, page_ids: list, confirmed: bool, scheduled_at: int | None = None) -> dict:
        """Đăng (lại) bài lên các Fanpage đã chọn. confirmed phải là True (người dùng đã bấm xác nhận trên giao diện)."""
        if confirmed is not True:
            raise PostError("Cần xác nhận đăng bài trên giao diện")
        if self.facebook is None:
            raise PostError("Chưa nối được dịch vụ Facebook")
        page_ids = [str(p) for p in page_ids or [] if p]
        if not page_ids:
            raise PostError("Chọn ít nhất 1 Fanpage")
        post = next((p for p in self._load() if p["id"] == pid), None)
        if post is None:
            raise PostError("Không tìm thấy bài đăng")
        kind = post.get("kind") if post.get("kind") in POST_TYPES else "feed"
        if scheduled_at:
            if kind not in SCHEDULABLE:
                raise PostError("Facebook không cho hẹn giờ Story")
            delta = int(scheduled_at) - time.time()
            if not SCHEDULE_MIN <= delta <= SCHEDULE_MAX:
                raise PostError("Facebook chỉ cho hẹn giờ từ 10 phút đến 30 ngày tính từ bây giờ")
        files = [str(MEDIA_DIR / pid / n) for n in post.get("files") or []]
        missing = [Path(f).name for f in files if not Path(f).is_file()]
        if missing:
            raise PostError(f"Thiếu file của bài: {', '.join(missing)} — sửa bài và chọn lại ảnh / video")
        images = [f for f in files if Path(f).suffix.lower() in IMAGE_EXT]
        videos = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT]
        caption = post.get("caption") or ""
        pages = {p["id"]: p for p in self.facebook.state().get("pages", [])}
        by, results = who(), []
        for page_id in page_ids:
            page_name = (pages.get(page_id) or {}).get("name", page_id)
            try:
                res = self._send(kind, page_id, caption, images, videos, scheduled_at)
                results.append(self._publish_entry(page_id, page_name, by, result=res, scheduled_at=scheduled_at))
            except Exception as exc:  # lỗi từng page: ghi lại, đăng tiếp page khác
                results.append(self._publish_entry(page_id, page_name, by, error=str(exc), scheduled_at=scheduled_at))

        def apply(p):
            p["publishes"] = (p.get("publishes") or []) + results
            if any(r["post_id"] or r["url"] for r in results):
                p["status"] = "scheduled" if scheduled_at else "posted"
            elif p.get("status") in ("draft", "queued", "missed"):
                p["status"] = "error"

        post = self._update(pid, apply)
        return {"post": self.public(post), "results": results}

    # ------------------------------------------------------------------ lên lịch (app tự đăng)
    def schedule(self, pid: str, page_ids: list, at: int, confirmed: bool, by: str = "") -> dict:
        """Lên lịch app tự đăng bài lúc `at` (Unix) lên các Fanpage. confirmed phải True — người dùng đã xác nhận lịch
        (giờ + Fanpage) trên giao diện / duyệt trong Workflow. Gọi lại = đổi giờ / Fanpage."""
        if confirmed is not True:
            raise PostError("Cần xác nhận lịch đăng trên giao diện")
        page_ids = [str(p) for p in page_ids or [] if p]
        if not page_ids:
            raise PostError("Chọn ít nhất 1 Fanpage")
        try:
            at = int(at)
        except (TypeError, ValueError):
            raise PostError("Chọn ngày giờ đăng") from None
        if not APP_SCHEDULE_MIN <= at - time.time() <= APP_SCHEDULE_MAX:
            raise PostError("Giờ đăng phải sau bây giờ ít nhất 1 phút (tối đa 1 năm)")
        pages = {p["id"]: p for p in self.facebook.state().get("pages", [])} if self.facebook else {}
        names = [(pages.get(i) or {}).get("name", i) for i in page_ids]

        def apply(p):
            if (p.get("schedule") or {}).get("running"):
                raise PostError("Bài đang được đăng — chờ xong rồi đổi lịch")
            files = [MEDIA_DIR / p["id"] / n for n in p.get("files") or []]
            missing = [f.name for f in files if not f.is_file()]
            if missing:
                raise PostError(f"Thiếu file của bài: {', '.join(missing)} — sửa bài và chọn lại ảnh / video")
            p["schedule"] = {"at": at, "page_ids": page_ids, "pages": names, "by": by or who(), "set_at": now()}
            p["status"] = "queued"
            p.pop("auto", None)

        return self.public(self._update(pid, apply))

    def unschedule(self, pid: str) -> dict:
        """Huỷ lịch đăng: bài về Nháp (hoặc Đã đăng nếu từng đăng thành công)."""
        def apply(p):
            if (p.get("schedule") or {}).get("running"):
                raise PostError("Bài đang được đăng — không huỷ được nữa")
            p.pop("schedule", None)
            p.pop("auto", None)
            ok = any(x.get("post_id") or x.get("url") for x in p.get("publishes") or [])
            p["status"] = "posted" if ok else "draft"

        return self.public(self._update(pid, apply))

    def _claim(self, pid: str) -> dict | None:
        """Giữ chỗ bài lên lịch để đăng (trong khoá) — chặn đăng trùng giữa bộ hẹn giờ và nút Đăng ngay."""
        with self._lock:
            posts = self._load()
            post = next((p for p in posts if p["id"] == pid), None)
            sch = (post or {}).get("schedule")
            if not sch or sch.get("running"):
                return None
            sch["running"] = True
            self._save(posts)
            return dict(sch)

    def _run_schedule(self, pid: str, sch: dict, label: str) -> dict:
        """Đăng bài đã giữ chỗ lên các Fanpage của lịch, rồi xoá lịch + ghi kết quả (auto) cho thông báo."""
        try:
            res = self.publish(pid, sch["page_ids"], True)
            results = res["results"]
            ok = [r for r in results if not r["error"]]
            auto = {"at": int(time.time() * 1000), "ok": bool(ok), "how": label,
                    "url": next((r["url"] for r in ok if r["url"]), ""),
                    "error": "; ".join(f"{r['page']}: {r['error']}" for r in results if r["error"])[:500]}
        except Exception as exc:  # lỗi chung (thiếu file, Facebook chưa nối…) → ghi lại, không làm chết bộ hẹn giờ
            res, auto = None, {"at": int(time.time() * 1000), "ok": False, "how": label, "url": "", "error": str(exc)[:500]}

        def apply(p):
            p.pop("schedule", None)
            p["auto"] = auto
            if not auto["ok"] and p.get("status") in ("queued", "missed"):
                p["status"] = "error"

        post = self._update(pid, apply)
        return {"post": self.public(post), "results": res["results"] if res else [], "error": auto["error"]}

    def publish_now(self, pid: str, confirmed: bool) -> dict:
        """Đăng ngay bài đang lên lịch / lỡ lịch (lên các Fanpage của lịch) — người dùng bấm xác nhận."""
        if confirmed is not True:
            raise PostError("Cần xác nhận đăng bài trên giao diện")
        sch = self._claim(pid)
        if sch is None:
            raise PostError("Bài không còn trong lịch đăng (đã đăng hoặc đang đăng)")
        return self._run_schedule(pid, sch, "Đăng ngay (bài lên lịch)")

    def run_due(self, grace: int = GRACE) -> int:
        """Bộ hẹn giờ gọi định kỳ: đăng các bài tới giờ. Trễ quá `grace` giây (app tắt lúc tới giờ) → lỡ lịch, không
        tự đăng. Trả về số bài đã xử lý (đăng / chuyển lỡ lịch)."""
        t = time.time()
        with self._lock:
            posts = self._load()
            due = [p for p in posts if p.get("status") == "queued" and (p.get("schedule") or {}).get("at", 1e18) <= t
                   and not p["schedule"].get("running")]
            late = {p["id"] for p in due if t - p["schedule"]["at"] > grace}
            for p in due:
                if p["id"] in late:
                    p["status"] = "missed"
                    p["auto"] = {"at": int(t * 1000), "ok": False, "how": "Lỡ lịch", "url": "",
                                 "error": "App không mở lúc tới giờ — chưa đăng. Bấm Đăng ngay hoặc đổi lịch."}
            if late:
                self._save(posts)
        for p in due:
            if p["id"] in late:
                continue
            sch = self._claim(p["id"])
            if sch is not None:
                self._run_schedule(p["id"], sch, f"Đăng theo lịch · {sch.get('by', '')}")
        return len(due)

    def queue_new(self, *, source: str, source_name: str, kind: str, caption: str, files: list, page_id: str,
                  at: int, by: str) -> dict:
        """Tạo bài mới + lên lịch app tự đăng (Workflow: block Đăng bài chọn “Lên lịch”, sau khi bạn duyệt)."""
        pid = f"p{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}"
        kind = kind if kind in POST_TYPES else ("text" if not files else "feed")
        with self._lock:
            names = self._copy_media(pid, [f for f in files if Path(str(f)).is_file()]) if kind != "text" else []
            posts = self._load()
            posts.append({"id": pid, "created_at": now(), "updated_at": now(),
                          "source": source if source in SOURCES else "manual", "source_name": source_name[:120],
                          "title": (caption or source_name or "Bài đăng")[:60], "caption": caption or "", "kind": kind,
                          "files": names, "publishes": [], "status": "draft"})
            self._save(posts)
        return self.schedule(pid, [page_id], at, True, by=by)

    def _send(self, kind: str, page_id: str, caption: str, images: list, videos: list, scheduled_at: int | None) -> dict:
        fb = self.facebook
        if kind == "text":
            if not caption:
                raise PostError("Bài “Chỉ bài viết” cần nội dung")
            return fb.post(page_id, caption, "", scheduled_at)
        if kind == "story":
            if not (images or videos):
                raise PostError("Story cần 1 ảnh hoặc video")
            return fb.post_story(page_id, (videos or images)[0])
        if kind == "media":
            caption = ""
        if kind == "reel":
            if not videos:
                raise PostError("Reels cần 1 video")
            return fb.post_reel(page_id, caption, videos[0], scheduled_at)
        if videos:
            return fb.post(page_id, caption, videos[0], scheduled_at)
        if images:
            return fb.post_album(page_id, caption, images, scheduled_at)
        if not caption:
            raise PostError("Bài không có nội dung")
        return fb.post(page_id, caption, "", scheduled_at)


class PostScheduler:
    """Thread nền: mỗi `every` giây đăng các bài lên lịch đã tới giờ (PostStore.run_due). on_change() khi có bài vừa
    xử lý — giao diện tải lại danh sách."""

    def __init__(self, store: PostStore, on_change=None, every: float = 20.0) -> None:
        self.store, self.on_change, self.every = store, on_change, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="post-scheduler")

    def start(self) -> "PostScheduler":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        import logging

        while not self._stop.is_set():
            try:
                if self.store.run_due() and self.on_change:
                    self.on_change()
            except Exception:  # bộ hẹn giờ không được chết vì 1 bài lỗi
                logging.getLogger(__name__).exception("Lỗi bộ hẹn giờ đăng bài")
            self._stop.wait(self.every)
