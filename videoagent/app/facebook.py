"""Kết nối Facebook + quản lý Fanpage (Graph API).

Luồng: người dùng lấy User Access Token trên Graph API Explorer → dán vào app → app kiểm tra token (/me,
/me/permissions) → (tuỳ chọn, nếu có App ID + Secret của đúng app đó) đổi sang token dài hạn → /me/accounts trả
danh sách page kèm page token tương ứng. Dữ liệu lưu cục bộ ở DATA_DIR/facebook.json.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .paths import DATA_DIR

FB_FILE = DATA_DIR / "facebook.json"
EXPLORER_URL = "https://developers.facebook.com/tools/explorer/"
REQUIRED_PERMISSIONS = ("pages_show_list", "pages_read_engagement", "pages_manage_posts")
DEFAULT_VERSION = "v21.0"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


class FacebookError(RuntimeError):
    pass


class FacebookRateLimit(FacebookError):
    """Meta đang giới hạn số lượt gọi API (App / tài khoản quảng cáo) — app tạm ngừng gọi tới khi hết hạn."""


# Mã lỗi giới hạn lượt gọi của Meta: 4 = App, 17 = người dùng (2 mã này chặn cả app) · 32 = page, 613 = theo phút,
# 80000–80014 = tài khoản quảng cáo (chỉ chặn đúng đối tượng đó)
APP_CODES = {4, 17}
RATE_CODES = APP_CODES | {32, 613} | set(range(80000, 80015))
RATE_COOLDOWN = 5 * 60  # giây tạm ngừng TỰ ĐỘNG khi Meta không nói rõ thời gian
RATE_SOFT = 90  # % hạn mức App (header X-App-Usage) — vượt mức này thì các lệnh gọi tự động nghỉ 2 phút


class _RateGuard:
    """Dùng chung cho mọi lệnh gọi Graph API. Bị Meta giới hạn → các lệnh gọi TỰ ĐỘNG (tải nền, đối chiếu, Zalo…) tạm
    ngừng để Meta không khoá lâu hơn. Thao tác người dùng tự bấm (kết nối token, tải page, làm mới) luôn được gọi thật
    (force) — gọi thành công là mở khoá ngay. Giới hạn của 1 tài khoản QC / page chỉ chặn đúng đối tượng đó."""

    def __init__(self) -> None:
        self.until: dict[str, float] = {}  # "app" hoặc id đối tượng (act_…, id page) → hết tạm ngừng lúc
        self.usage = 0  # % cao nhất của App (call_count / total_time / total_cputime)

    @staticmethod
    def key(path: str) -> str:
        """Đối tượng của lệnh gọi: act_… / id số ở đầu đường dẫn; còn lại (me/…, search…) tính cho cả app."""
        parts = [x for x in str(path).split("?")[0].split("/") if x]
        if "graph.facebook.com" in parts:
            parts = parts[parts.index("graph.facebook.com") + 1:]
        if parts and re.fullmatch(r"v\d+\.\d+", parts[0]):
            parts = parts[1:]
        head = parts[0] if parts else ""
        return head if head.startswith("act_") or head.isdigit() else "app"

    def check(self, path: str = "", force: bool = False) -> None:
        if force:
            return
        now = time.time()
        for k in ("app", self.key(path)):
            left = self.until.get(k, 0) - now
            if left > 0:
                who = "App" if k == "app" else f"đối tượng {k}"
                raise FacebookRateLimit(
                    f"Facebook đang tạm giới hạn lượt gọi API của {who} (gọi quá nhiều) — app tạm ngừng tự gọi khoảng "
                    f"{max(1, round(left / 60))} phút để Meta không khoá lâu hơn. Bấm làm mới / kết nối lại để thử ngay; "
                    f"dữ liệu đã lưu vẫn dùng được.")

    def observe(self, resp, path: str = "") -> None:
        if resp.status_code == 200:  # Meta vừa trả lời bình thường → mở khoá đối tượng này (và cả app)
            self.until.pop("app", None)
            self.until.pop(self.key(path), None)
        try:
            app = json.loads(resp.headers.get("x-app-usage") or "{}")
            if app:
                self.usage = max(int(v or 0) for v in app.values())
            buc = json.loads(resp.headers.get("x-business-use-case-usage") or "{}")
            wait = max((int(u.get("estimated_time_to_regain_access") or 0) for rows in buc.values() for u in rows),
                       default=0)
        except (ValueError, TypeError, AttributeError):
            return
        if wait:  # giới hạn theo tài khoản QC / doanh nghiệp → chỉ chặn đối tượng của lệnh gọi này
            k = self.key(path)
            self.until[k] = max(self.until.get(k, 0), time.time() + wait * 60)
        if self.usage >= RATE_SOFT:
            self.until["app"] = max(self.until.get("app", 0), time.time() + 120)

    def fail(self, resp, data: dict, path: str = ""):
        """Lỗi từ Meta → FacebookRateLimit (kèm tạm ngừng) nếu là lỗi giới hạn lượt gọi, không thì FacebookError."""
        err = (data or {}).get("error") or {}
        msg = err.get("error_user_msg") or err.get("message") or resp.text[:200]
        code, sub = err.get("code"), err.get("error_subcode")
        if code in RATE_CODES or sub in RATE_CODES:
            k = "app" if code in APP_CODES or self.key(path) == "app" else self.key(path)
            self.until[k] = max(self.until.get(k, 0), time.time() + RATE_COOLDOWN)
            who = "của App" if k == "app" else f"của {k}"
            raise FacebookRateLimit(f"Facebook báo lỗi: {msg} — Meta đang giới hạn lượt gọi API {who}; app tạm ngừng "
                                    f"tự gọi 5 phút (hạn mức tính theo 1 giờ gần nhất). Dữ liệu đã lưu vẫn dùng được.")
        raise FacebookError(f"Facebook báo lỗi: {msg}")


RATE = _RateGuard()


class FacebookManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = {"app_id": "", "app_secret": "", "graph_version": DEFAULT_VERSION, "app_name": "",
                      "user": None, "user_token": "", "token_expires_at": None, "pages": []}
        if FB_FILE.exists():
            try:
                self._data.update(json.loads(FB_FILE.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    # ------------------------------------------------------------------ lưu / trạng thái
    def _save(self) -> None:
        with self._lock:
            tmp = FB_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(FB_FILE)

    def state(self) -> dict:
        """Trạng thái cho giao diện — không bao giờ trả App Secret hay token."""
        d = self._data
        return {
            "app_id": d["app_id"], "app_name": d.get("app_name", ""), "has_secret": bool(d["app_secret"]),
            "graph_version": d.get("graph_version") or DEFAULT_VERSION, "user": d.get("user"),
            "logged_in": bool(d.get("user_token")), "token_expires_at": d.get("token_expires_at"),
            "long_lived": bool(d.get("long_lived")), "permissions": d.get("permissions", []),
            "missing_permissions": [p for p in REQUIRED_PERMISSIONS if d.get("user_token")
                                    and p not in d.get("permissions", [])],
            "explorer_url": EXPLORER_URL,
            "pages": [{k: p.get(k) for k in ("id", "name", "category", "picture", "fan_count", "link", "connected")}
                      for p in d.get("pages", [])],
        }

    @property
    def _graph(self) -> str:
        return f"https://graph.facebook.com/{self._data.get('graph_version') or DEFAULT_VERSION}"

    def _get(self, path: str, _force: bool = False, **params) -> dict:
        """_force=True: thao tác người dùng tự bấm — gọi thật kể cả khi đang tạm ngừng vì bị Meta giới hạn."""
        RATE.check(path, _force)  # đang bị Meta giới hạn → lệnh gọi tự động không gọi thêm
        try:
            resp = requests.get(f"{self._graph}/{path}", params=params, timeout=30)
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        RATE.observe(resp, path)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code != 200 or "error" in data:
            RATE.fail(resp, data, path)
        return data

    # ------------------------------------------------------------------ App Meta
    def save_app(self, app_id: str, app_secret: str, graph_version: str = "") -> dict:
        app_id, app_secret = (app_id or "").strip(), (app_secret or "").strip()
        if not app_id.isdigit():
            raise FacebookError("App ID phải là dãy số (xem trong developers.facebook.com → App của bạn)")
        secret = app_secret or self._data["app_secret"]  # để trống = giữ secret cũ
        if not secret:
            raise FacebookError("Hãy nhập App Secret")
        version = (graph_version or DEFAULT_VERSION).strip()
        old = (self._data["app_id"], self._data["app_secret"], self._data.get("graph_version"))
        self._data.update(app_id=app_id, app_secret=secret, graph_version=version)
        try:  # kiểm tra App ID/Secret bằng app access token
            info = self._get(app_id, _force=True, fields="name", access_token=f"{app_id}|{secret}")
        except FacebookError:
            self._data.update(app_id=old[0], app_secret=old[1], graph_version=old[2])
            raise
        if old[0] and old[0] != app_id:  # đổi app → token cũ không còn hợp lệ
            self._data.update(user=None, user_token="", token_expires_at=None, pages=[])
        self._data["app_name"] = info.get("name", "")
        self._save()
        return self.state()

    # ------------------------------------------------------------------ User Access Token (Graph API Explorer)
    def connect_token(self, token: str) -> dict:
        """Nhận User Access Token dán từ Graph API Explorer → kiểm tra → (đổi dài hạn) → tải page + page token."""
        token = "".join((token or "").split())  # bỏ khoảng trắng/xuống dòng khi dán
        if len(token) < 20:
            raise FacebookError("Hãy dán User Access Token (chuỗi bắt đầu bằng EAA…) lấy từ Graph API Explorer")
        me = self._get("me", _force=True, fields="id,name,picture{url}", access_token=token)  # token sai/hết hạn → lỗi rõ ràng
        long_lived, expires_in = False, 0
        if self._data["app_id"] and self._data["app_secret"]:
            token, expires_in, long_lived = self._long_lived(token)
        if not expires_in:
            expires_in = self._expires_in(token)
        perms = self._get("me/permissions", _force=True, access_token=token).get("data", [])
        self._data.update(
            user={"id": me["id"], "name": me.get("name", ""),
                  "picture": ((me.get("picture") or {}).get("data") or {}).get("url", "")},
            user_token=token, long_lived=long_lived,
            permissions=[p["permission"] for p in perms if p.get("status") == "granted"],
            token_expires_at=(datetime.now() + timedelta(seconds=expires_in)).isoformat(timespec="seconds")
            if expires_in else None,
        )
        self._save()
        return self.load_pages()

    def _long_lived(self, token: str) -> tuple[str, int, bool]:
        """Đổi sang token dài hạn — chỉ được khi App ID/Secret là đúng app đã chọn trong Graph API Explorer."""
        try:
            data = self._get("oauth/access_token", _force=True, grant_type="fb_exchange_token", client_id=self._data["app_id"],
                             client_secret=self._data["app_secret"], fb_exchange_token=token)
            return data["access_token"], int(data.get("expires_in") or 60 * 24 * 3600), True
        except (FacebookError, KeyError):
            return token, 0, False  # vẫn dùng được token ngắn hạn

    def _expires_in(self, token: str) -> int:
        """Thời gian còn lại của token (debug_token cần app token → chỉ khi đã nhập App ID/Secret)."""
        if not (self._data["app_id"] and self._data["app_secret"]):
            return 0
        try:
            info = self._get("debug_token", _force=True, input_token=token,
                             access_token=f"{self._data['app_id']}|{self._data['app_secret']}").get("data", {})
            expires_at = int(info.get("expires_at") or 0)
            return max(0, expires_at - int(datetime.now().timestamp())) if expires_at else 0
        except FacebookError:
            return 0

    def logout(self) -> dict:
        self._data.update(user=None, user_token="", token_expires_at=None, pages=[], permissions=[], long_lived=False)
        self._save()
        return self.state()

    # ------------------------------------------------------------------ fanpage
    def load_pages(self) -> dict:
        token = self._data.get("user_token")
        if not token:
            raise FacebookError("Chưa có User Access Token — nhập ở Cài đặt → API & kết nối")
        connected = {p["id"] for p in self._data.get("pages", []) if p.get("connected")}
        pages, after = [], None
        while True:
            params = {"fields": "id,name,category,picture{url},fan_count,link,access_token,tasks", "limit": 100,
                      "access_token": token}
            if after:
                params["after"] = after
            data = self._get("me/accounts", _force=True, **params)
            for p in data.get("data", []):
                pages.append({"id": p["id"], "name": p.get("name", ""), "category": p.get("category", ""),
                              "picture": ((p.get("picture") or {}).get("data") or {}).get("url", ""),
                              "fan_count": p.get("fan_count"), "link": p.get("link", ""),
                              "access_token": p.get("access_token", ""), "tasks": p.get("tasks", []),
                              "connected": p["id"] in connected})
            after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
            if not (data.get("paging") or {}).get("next"):
                break
        self._data["pages"] = pages
        self._save()
        return self.state()

    def set_connected(self, page_id: str, connected: bool) -> dict:
        page = self._page(page_id)
        page["connected"] = bool(connected)
        self._save()
        return self.state()

    def _page(self, page_id: str) -> dict:
        page = next((p for p in self._data.get("pages", []) if p["id"] == page_id), None)
        if page is None:
            raise FacebookError("Không tìm thấy page — hãy tải lại danh sách")
        return page

    @staticmethod
    def _schedule(scheduled_at: int | None) -> dict:
        """Tham số hẹn giờ của Graph API: bài ở trạng thái chưa đăng, Facebook tự đăng lúc scheduled_publish_time."""
        if not scheduled_at:
            return {}
        return {"published": "false", "scheduled_publish_time": str(int(scheduled_at))}

    def _video_post(self, video_id: str, token: str) -> tuple[str, str]:
        """ID bài viết + link của video vừa tải (cần post_id để chạy quảng cáo cho bài video)."""
        for fields in ("post_id,permalink_url", "permalink_url"):
            try:
                info = requests.get(f"{self._graph}/{video_id}", params={"fields": fields, "access_token": token},
                                    timeout=30).json()
            except (requests.RequestException, ValueError):
                return "", ""
            if "error" not in info:
                link = info.get("permalink_url") or ""
                return info.get("post_id") or "", (f"https://www.facebook.com{link}" if link.startswith("/") else link)
        return "", ""

    def post_album(self, page_id: str, message: str, files: list, scheduled_at: int | None = None) -> dict:
        """Đăng nhiều ảnh trong một bài: tải từng ảnh ở chế độ chưa đăng (published=false) rồi gắn vào /feed.
        scheduled_at (Unix time) → hẹn giờ đăng."""
        page = self._page(page_id)
        if not page.get("connected"):
            raise FacebookError("Page chưa được kết nối")
        token = page.get("access_token")
        if not token:
            raise FacebookError("Thiếu page token — tạo lại User Access Token có quyền pages_manage_posts rồi dán lại")
        paths = [Path(f) for f in files if Path(f).suffix.lower() in IMAGE_EXT and Path(f).is_file()]
        if not paths:
            raise FacebookError("Không có ảnh hợp lệ để đăng")
        if len(paths) == 1:
            return self.post(page_id, message, str(paths[0]), scheduled_at)
        media = []
        try:
            for path in paths:
                with open(path, "rb") as fh:
                    resp = requests.post(f"{self._graph}/{page_id}/photos", data={"published": "false",
                                         "access_token": token}, files={"source": (path.name, fh)}, timeout=300)
                data = resp.json() if resp.content else {}
                if resp.status_code != 200 or "error" in data:
                    raise FacebookError(f"Facebook báo lỗi khi tải ảnh {path.name}: "
                                        f"{data.get('error', {}).get('message', resp.text[:200])}")
                media.append({"media_fbid": data["id"]})
            resp = requests.post(f"{self._graph}/{page_id}/feed", data={
                "message": (message or "").strip(), "attached_media": json.dumps(media), "access_token": token,
                **self._schedule(scheduled_at)}, timeout=60)
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or "error" in data:
            raise FacebookError(f"Facebook báo lỗi: {data.get('error', {}).get('message', resp.text[:200])}")
        post_id = data.get("id", "")
        return {"id": post_id, "page": page["name"], "scheduled": bool(scheduled_at),
                "url": f"https://www.facebook.com/{post_id}" if post_id else ""}

    # ------------------------------------------------------------------ Reels / Story (luồng tải lên rupload)
    def _page_token(self, page_id: str) -> tuple[dict, str]:
        page = self._page(page_id)
        if not page.get("connected"):
            raise FacebookError("Page chưa được kết nối")
        token = page.get("access_token")
        if not token:
            raise FacebookError("Thiếu page token — tạo lại User Access Token có quyền pages_manage_posts rồi nhập ở Cài đặt")
        return page, token

    def _call(self, method: str, url: str, timeout: int = 60, **kwargs) -> dict:
        RATE.check(url)
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        RATE.observe(resp, url)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code != 200 or "error" in data:
            RATE.fail(resp, data, url)
        return data

    def _upload_video(self, page_id: str, token: str, edge: str, path: Path) -> str:
        """Bước start + tải file lên rupload.facebook.com của Reels/Story video. Trả về video_id."""
        start = self._call("POST", f"{self._graph}/{page_id}/{edge}", data={"upload_phase": "start", "access_token": token})
        video_id, upload_url = start.get("video_id"), start.get("upload_url")
        if not video_id or not upload_url:
            raise FacebookError("Facebook không trả về video_id / upload_url khi bắt đầu tải video")
        with open(path, "rb") as fh:
            self._call("POST", upload_url, timeout=1800, data=fh, headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(path.stat().st_size)})
        return video_id

    def post_reel(self, page_id: str, message: str, file_path: str, scheduled_at: int | None = None) -> dict:
        """Đăng video dạng Reels (nên là video dọc 9:16, 3–90 giây). scheduled_at → hẹn giờ."""
        page, token = self._page_token(page_id)
        path = Path(file_path)
        if path.suffix.lower() not in VIDEO_EXT or not path.is_file():
            raise FacebookError("Reels cần 1 file video (mp4/mov/webm)")
        video_id = self._upload_video(page_id, token, "video_reels", path)
        finish = {"upload_phase": "finish", "video_id": video_id, "access_token": token,
                  "description": (message or "").strip(), "video_state": "SCHEDULED" if scheduled_at else "PUBLISHED"}
        if scheduled_at:
            finish["scheduled_publish_time"] = str(int(scheduled_at))
        self._call("POST", f"{self._graph}/{page_id}/video_reels", data=finish)
        post_id, link = ("", "") if scheduled_at else self._video_post(video_id, token)
        return {"id": post_id or video_id, "video_id": video_id, "page": page["name"], "scheduled": bool(scheduled_at),
                "url": link or f"https://www.facebook.com/reel/{video_id}"}

    def post_story(self, page_id: str, file_path: str) -> dict:
        """Đăng Story (ảnh hoặc video, hiện 24 giờ). Facebook không cho hẹn giờ Story và Story không có caption."""
        page, token = self._page_token(page_id)
        path = Path(file_path)
        if not path.is_file():
            raise FacebookError("Story cần 1 file ảnh hoặc video")
        if path.suffix.lower() in IMAGE_EXT:
            with open(path, "rb") as fh:
                photo = self._call("POST", f"{self._graph}/{page_id}/photos", timeout=300,
                                   data={"published": "false", "access_token": token}, files={"source": (path.name, fh)})
            data = self._call("POST", f"{self._graph}/{page_id}/photo_stories",
                              data={"photo_id": photo["id"], "access_token": token})
        elif path.suffix.lower() in VIDEO_EXT:
            video_id = self._upload_video(page_id, token, "video_stories", path)
            data = self._call("POST", f"{self._graph}/{page_id}/video_stories",
                              data={"upload_phase": "finish", "video_id": video_id, "access_token": token})
        else:
            raise FacebookError("Story chỉ nhận ảnh (png/jpg/webp) hoặc video (mp4/mov/webm)")
        post_id = data.get("post_id") or data.get("id") or ""
        return {"id": post_id, "page": page["name"], "scheduled": False,
                "url": f"https://www.facebook.com/stories/{page_id}" if post_id else ""}

    def post(self, page_id: str, message: str, file_path: str = "", scheduled_at: int | None = None) -> dict:
        """Đăng bài lên page đã kết nối: chữ, ảnh (/photos) hoặc video (/videos). scheduled_at → hẹn giờ đăng."""
        schedule = self._schedule(scheduled_at)
        page = self._page(page_id)
        if not page.get("connected"):
            raise FacebookError("Page chưa được kết nối")
        token = page.get("access_token")
        if not token:
            raise FacebookError("Thiếu page token — tạo lại User Access Token có quyền pages_manage_posts rồi dán lại")
        message = (message or "").strip()
        path = Path(file_path) if file_path else None
        try:
            if path is None:
                if not message:
                    raise FacebookError("Hãy nhập nội dung bài đăng")
                resp = requests.post(f"{self._graph}/{page_id}/feed", data={"message": message,
                                     "access_token": token, **schedule}, timeout=60)
            elif path.suffix.lower() in IMAGE_EXT:
                with open(path, "rb") as fh:
                    resp = requests.post(f"{self._graph}/{page_id}/photos", data={"caption": message,
                                         "access_token": token, **schedule}, files={"source": (path.name, fh)}, timeout=300)
            elif path.suffix.lower() in VIDEO_EXT:
                with open(path, "rb") as fh:
                    resp = requests.post(f"https://graph-video.facebook.com/{self._data.get('graph_version') or DEFAULT_VERSION}"
                                         f"/{page_id}/videos", data={"description": message, "access_token": token,
                                                                     **schedule},
                                         files={"source": (path.name, fh)}, timeout=1800)
            else:
                raise FacebookError("Chỉ đăng được ảnh (png/jpg/webp) hoặc video (mp4/mov/webm)")
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or "error" in data:
            raise FacebookError(f"Facebook báo lỗi: {data.get('error', {}).get('message', resp.text[:200])}")
        post_id, url = data.get("post_id") or "", ""
        if path is not None and path.suffix.lower() in VIDEO_EXT and not post_id and not scheduled_at:
            post_id, url = self._video_post(data.get("id", ""), token)  # /videos chỉ trả id video
        post_id = post_id or data.get("id", "")
        return {"id": post_id, "page": page["name"], "scheduled": bool(scheduled_at), "video_id": data.get("id", "")
                if path is not None and path.suffix.lower() in VIDEO_EXT else "",
                "url": url or (f"https://www.facebook.com/{post_id}" if post_id else "")}
