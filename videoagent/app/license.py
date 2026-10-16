"""License ITNNV: đăng nhập Google qua web ITNNV, mỗi tài khoản gắn 1 máy, xác thực định kỳ.

Hợp đồng API giả định với server ITNNV (cấu hình `license_server` trong Cài đặt):
  GET  {server}/desktop/login?state=..&device=..&app=videoagent  → trang đăng nhập Google trên trình duyệt
  POST {server}/desktop/token   {"state"}                         → 200 {"token"} | 202 đang chờ
  POST {server}/license/verify  {"token","device","app"}          → 200 {"active","user":{name,email,avatar},
                                                                     "expires_at","message"} | 401/403
Để trống `license_server` (hoặc đặt biến môi trường VIDEOAGENT_DEV=1) = chế độ phát triển, bỏ qua license.
"""
import hashlib
import json
import logging
import os
import platform
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from .paths import DATA_DIR

log = logging.getLogger(__name__)
LICENSE_FILE = DATA_DIR / "license.json"
APP_ID = "videoagent"
LOGIN_TIMEOUT_S = 300
HEARTBEAT_S = 30 * 60


class LicenseError(RuntimeError):
    pass


def machine_id() -> str:
    raw = platform.node()
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                raw = winreg.QueryValueEx(key, "MachineGuid")[0] + raw
        except OSError:
            pass
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class LicenseManager:
    def __init__(self, settings, on_change=None) -> None:
        self.settings = settings
        self._on_change = on_change
        self._device = machine_id()
        self._token = ""
        self._state = {"active": False, "user": None, "expires_at": None, "days_left": None, "message": "Chưa đăng nhập"}
        if LICENSE_FILE.exists():
            try:
                self._token = json.loads(LICENSE_FILE.read_text("utf-8")).get("token", "")
            except (OSError, json.JSONDecodeError):
                pass

    @property
    def server(self) -> str:
        return (self.settings.get("license_server") or "").rstrip("/")

    @property
    def dev_mode(self) -> bool:
        return os.environ.get("VIDEOAGENT_DEV") == "1" or not self.server

    def status(self) -> dict:
        if self.dev_mode:
            return {"active": True, "dev": True, "user": {"name": "Người dùng thử", "email": "", "avatar": ""},
                    "expires_at": None, "days_left": None, "message": "Chưa cấu hình license server"}
        return {**self._state, "dev": False}

    def require_active(self) -> None:
        if not self.status()["active"]:
            raise LicenseError("License chưa kích hoạt hoặc đã hết hạn — hãy đăng nhập ITNNV.")

    def login(self) -> dict:
        if self.dev_mode:
            return self.status()
        state = secrets.token_urlsafe(16)
        query = urlencode({"state": state, "device": self._device, "app": APP_ID})
        webbrowser.open(f"{self.server}/desktop/login?{query}")
        deadline = time.time() + LOGIN_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(2)
            try:
                resp = requests.post(f"{self.server}/desktop/token", json={"state": state}, timeout=15)
            except requests.RequestException:
                continue
            if resp.status_code == 200 and resp.json().get("token"):
                self._token = resp.json()["token"]
                LICENSE_FILE.write_text(json.dumps({"token": self._token}), "utf-8")
                return self.verify()
        raise LicenseError("Hết thời gian chờ đăng nhập ITNNV")

    def logout(self) -> dict:
        self._token = ""
        LICENSE_FILE.unlink(missing_ok=True)
        self._set({"active": False, "user": None, "expires_at": None, "days_left": None, "message": "Đã đăng xuất"})
        return self.status()

    def verify(self) -> dict:
        if self.dev_mode:
            return self.status()
        if not self._token:
            self._set({**self._state, "active": False, "message": "Chưa đăng nhập"})
            return self.status()
        try:
            resp = requests.post(f"{self.server}/license/verify",
                                 json={"token": self._token, "device": self._device, "app": APP_ID}, timeout=15)
        except requests.RequestException as exc:
            log.warning("Không kết nối được license server: %s", exc)
            self._set({**self._state, "active": False, "message": "Không kết nối được máy chủ license"})
            return self.status()
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200:
            message = data.get("message") or ("Tài khoản đang gắn với máy khác" if resp.status_code == 403
                                              else "Phiên đăng nhập hết hạn")
            self._set({"active": False, "user": data.get("user"), "expires_at": None, "days_left": None, "message": message})
            return self.status()
        expires_at = data.get("expires_at")
        days_left = None
        if expires_at:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            days_left = max(0, (expiry - datetime.now(timezone.utc)).days)
        self._set({"active": bool(data.get("active")), "user": data.get("user"), "expires_at": expires_at,
                   "days_left": days_left, "message": data.get("message", "")})
        return self.status()

    def start_heartbeat(self) -> None:
        def loop():
            while True:
                self.verify()
                time.sleep(HEARTBEAT_S)

        threading.Thread(target=loop, daemon=True, name="license-heartbeat").start()

    def _set(self, state: dict) -> None:
        self._state = state
        if self._on_change:
            self._on_change(self.status())
