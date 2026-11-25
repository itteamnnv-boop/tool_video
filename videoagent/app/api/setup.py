"""API · 🧰 Cài đặt công cụ (setup_*): trạng thái + cài online (winget / npm / pip) + skill từ file .skill + đăng nhập +
báo cáo. Sự kiện lên giao diện: setup_changed (hàng đợi cài đổi trạng thái)."""
import threading

from .common import _fail, _ok


class SetupApi:
    def _setup(self):
        obj = getattr(self, "_setup_obj", None)
        if obj is None:
            from ..config import settings
            from ..setup_tools import SetupTools

            obj = self._setup_obj = SetupTools(settings, getattr(self, "_facebook", None),
                                               on_change=lambda: self._emit("setup_changed", {}))
        return obj

    def _setup_call(self, key: str, fn, *args) -> dict:
        from ..setup_tools import SetupError

        try:
            return _ok(**{key: fn(*args)})
        except (SetupError, RuntimeError, OSError, ValueError) as exc:
            return _fail(exc)

    def setup_state(self) -> dict:
        """Trạng thái đã kiểm (không chạy lại kiểm tra)."""
        return _ok(state=self._setup().state())

    def setup_check(self, keys: list | None = None) -> dict:
        """Kiểm tra lại (tất cả hoặc vài mục) — vài giây, chạy lệnh --version của từng công cụ."""
        return self._setup_call("state", self._setup().check, keys or None)

    def setup_check_bg(self) -> dict:
        """Mở app: kiểm tra trong nền → sự kiện setup_changed (thanh bên hiện số mục còn thiếu)."""
        threading.Thread(target=lambda: (self._setup().check(), self._emit("setup_changed", {})), daemon=True,
                         name="setup-check").start()
        return _ok()

    def setup_install(self, keys: list, action: str = "install") -> dict:
        """Cài / cập nhật các mục (hàng đợi nền). Giao diện đã hỏi xác nhận danh sách trước khi gọi."""
        return self._setup_call("state", self._setup().install, keys or [], str(action or "install"))

    def setup_cancel(self) -> dict:
        return _ok(cancelled=self._setup().cancel(), state=self._setup().state())

    def setup_skill_install(self, path: str) -> dict:
        """Cài skill từ file .skill (zip) vào ~/.claude/skills (bản cũ đổi tên .bak-…, không xoá)."""
        res = self._setup_call("skill", self._setup().install_skill, str(path or ""))
        if res.get("ok"):
            res["state"] = self._setup().state()
        return res

    def setup_login(self, key: str) -> dict:
        return self._setup_call("login", self._setup().login, str(key or ""))

    def setup_report(self) -> dict:
        """Báo cáo tình trạng máy (không có token / cookie) để gửi người hỗ trợ."""
        return self._setup_call("report", self._setup().report)
