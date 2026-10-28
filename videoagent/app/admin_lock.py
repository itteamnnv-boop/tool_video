"""Khoá màn Cài đặt bằng mật khẩu quản trị.

Mật khẩu lưu dạng băm PBKDF2-SHA256 (+ salt ngẫu nhiên) trong DATA_DIR/admin_lock.json — không lưu mật khẩu gốc, không gửi
lên giao diện. Mở khoá có hiệu lực trong phiên chạy app, tự khoá sau UNLOCK_TTL giây không thao tác ở Cài đặt; thoát app là
khoá lại. Sai MAX_FAILS lần liền → chờ LOCKOUT giây mới nhập tiếp. Quên mật khẩu: xoá file admin_lock.json rồi đặt lại.
Chỉ bật ở bản build (PyInstaller); chạy từ mã nguồn (`python main.py`) → tắt, mọi thứ coi như đã mở khoá.
"""
import hashlib
import hmac
import os
import sys
import threading
import time
from datetime import datetime

from .paths import DATA_DIR
from .util import read_json, write_json

LOCK_FILE = DATA_DIR / "admin_lock.json"
ITERATIONS = 200_000
MIN_LEN = 4
MAX_FAILS, LOCKOUT = 5, 30
UNLOCK_TTL = 15 * 60
# khoá cài đặt nhạy cảm: chỉ sửa được khi Cài đặt đang mở khoá (màn khác không gửi các khoá này)
GUARDED = ("anthropic_api_key", "openai_api_key", "gemini_api_key", "license_server", "menus")


class LockError(ValueError):
    pass


def lock_enabled() -> bool:
    """Bản build (PyInstaller đặt sys.frozen) → bật khoá. Chạy `python main.py` → tắt; muốn thử khoá khi chạy mã nguồn thì
    đặt biến môi trường VIDEOAGENT_ADMIN_LOCK=1 (biến này chỉ bật được, không tắt được khoá ở bản build)."""
    return bool(getattr(sys, "frozen", False)) or os.environ.get("VIDEOAGENT_ADMIN_LOCK") == "1"


class AdminLock:
    def __init__(self, path=None) -> None:
        self.path = path or LOCK_FILE
        self._lock = threading.Lock()
        self._until = 0.0
        self._fails = 0
        self._blocked = 0.0

    def _data(self) -> dict:
        try:
            data = read_json(self.path)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("hash") and data.get("salt") else {}

    @staticmethod
    def _hash(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()

    def _matches(self, password: str) -> bool:
        data = self._data()
        if not data:
            return False
        digest = self._hash(str(password or ""), bytes.fromhex(data["salt"]), int(data.get("iter") or ITERATIONS))
        return hmac.compare_digest(digest, data["hash"])

    def has_password(self) -> bool:
        return bool(self._data())

    def unlocked(self) -> bool:
        if not lock_enabled():  # chạy từ mã nguồn → không khoá
            return True
        return self.has_password() and time.time() < self._until

    def state(self) -> dict:
        now = time.time()
        return {"has_password": self.has_password(), "unlocked": self.unlocked(), "disabled": not lock_enabled(),
                "retry_in": max(0, int(self._blocked - now + 0.999)), "ttl_min": UNLOCK_TTL // 60}

    def touch(self) -> None:
        """Còn thao tác ở Cài đặt → gia hạn thời gian mở khoá."""
        if self.unlocked():
            self._until = time.time() + UNLOCK_TTL

    def unlock(self, password: str) -> dict:
        with self._lock:
            now = time.time()
            if now < self._blocked:
                raise LockError(f"Nhập sai nhiều lần — thử lại sau {int(self._blocked - now) + 1} giây")
            if not self.has_password():
                raise LockError("Chưa đặt mật khẩu quản trị")
            if not self._matches(password):
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    self._fails, self._blocked = 0, now + LOCKOUT
                    raise LockError(f"Sai mật khẩu {MAX_FAILS} lần — chờ {LOCKOUT} giây rồi thử lại")
                raise LockError(f"Sai mật khẩu (còn {MAX_FAILS - self._fails} lần thử)")
            self._fails = 0
            self._until = now + UNLOCK_TTL
        return self.state()

    def set_password(self, new: str, old: str = "") -> dict:
        new = str(new or "")
        if len(new) < MIN_LEN:
            raise LockError(f"Mật khẩu cần ít nhất {MIN_LEN} ký tự")
        with self._lock:
            if self.has_password() and not self._matches(old):
                raise LockError("Mật khẩu hiện tại không đúng")
            salt = os.urandom(16)
            write_json(self.path, {"salt": salt.hex(), "hash": self._hash(new, salt), "iter": ITERATIONS,
                                   "updated_at": datetime.now().isoformat(timespec="seconds")})
            self._fails = 0
            self._until = time.time() + UNLOCK_TTL
        return self.state()

    def lock(self) -> dict:
        self._until = 0.0
        return self.state()

    def guard(self, values: dict) -> dict:
        """Bỏ các khoá cài đặt nhạy cảm khi Cài đặt đang khoá (đã đặt mật khẩu mà chưa mở khoá)."""
        if not lock_enabled() or not self.has_password() or self.unlocked():
            return values
        return {k: v for k, v in (values or {}).items() if k not in GUARDED}
