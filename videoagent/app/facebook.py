"""Kết nối Facebook + quản lý Fanpage (Graph API).

Luồng: người dùng lấy User Access Token trên Graph API Explorer → dán vào app → app kiểm tra token (/me,
/me/permissions) → (tuỳ chọn, nếu có App ID + Secret của đúng app đó) đổi sang token dài hạn → /me/accounts trả
danh sách page kèm page token tương ứng. Dữ liệu lưu cục bộ ở DATA_DIR/facebook.json.
"""
import json
import threading
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

    def _get(self, path: str, **params) -> dict:
        try:
            resp = requests.get(f"{self._graph}/{path}", params=params, timeout=30)
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or "error" in data:
            raise FacebookError(f"Facebook báo lỗi: {data.get('error', {}).get('message', resp.text[:200])}")
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
            info = self._get(app_id, fields="name", access_token=f"{app_id}|{secret}")
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
        me = self._get("me", fields="id,name,picture{url}", access_token=token)  # token sai/hết hạn → lỗi rõ ràng
        long_lived, expires_in = False, 0
        if self._data["app_id"] and self._data["app_secret"]:
            token, expires_in, long_lived = self._long_lived(token)
        if not expires_in:
            expires_in = self._expires_in(token)
        perms = self._get("me/permissions", access_token=token).get("data", [])
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
            data = self._get("oauth/access_token", grant_type="fb_exchange_token", client_id=self._data["app_id"],
                             client_secret=self._data["app_secret"], fb_exchange_token=token)
            return data["access_token"], int(data.get("expires_in") or 60 * 24 * 3600), True
        except (FacebookError, KeyError):
            return token, 0, False  # vẫn dùng được token ngắn hạn

    def _expires_in(self, token: str) -> int:
        """Thời gian còn lại của token (debug_token cần app token → chỉ khi đã nhập App ID/Secret)."""
        if not (self._data["app_id"] and self._data["app_secret"]):
            return 0
        try:
            info = self._get("debug_token", input_token=token,
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
            raise FacebookError("Chưa có User Access Token — dán token từ Graph API Explorer trước")
        connected = {p["id"] for p in self._data.get("pages", []) if p.get("connected")}
        pages, after = [], None
        while True:
            params = {"fields": "id,name,category,picture{url},fan_count,link,access_token,tasks", "limit": 100,
                      "access_token": token}
            if after:
                params["after"] = after
            data = self._get("me/accounts", **params)
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

    def post(self, page_id: str, message: str, file_path: str = "") -> dict:
        """Đăng bài lên page đã kết nối: chữ, ảnh (/photos) hoặc video (/videos)."""
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
                                                                           "access_token": token}, timeout=60)
            elif path.suffix.lower() in IMAGE_EXT:
                with open(path, "rb") as fh:
                    resp = requests.post(f"{self._graph}/{page_id}/photos", data={"caption": message,
                                         "access_token": token}, files={"source": (path.name, fh)}, timeout=300)
            elif path.suffix.lower() in VIDEO_EXT:
                with open(path, "rb") as fh:
                    resp = requests.post(f"https://graph-video.facebook.com/{self._data.get('graph_version') or DEFAULT_VERSION}"
                                         f"/{page_id}/videos", data={"description": message, "access_token": token},
                                         files={"source": (path.name, fh)}, timeout=1800)
            else:
                raise FacebookError("Chỉ đăng được ảnh (png/jpg/webp) hoặc video (mp4/mov/webm)")
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or "error" in data:
            raise FacebookError(f"Facebook báo lỗi: {data.get('error', {}).get('message', resp.text[:200])}")
        return {"id": data.get("post_id") or data.get("id"), "page": page["name"]}
