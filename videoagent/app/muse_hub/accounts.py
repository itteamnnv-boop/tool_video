"""Studio Muse AI · tài khoản Muse (profile trình duyệt) + đọc hạn mức."""
import threading

from .. import browser_profiles

from . import common as _c
from .common import QUOTA_JS, SITE, parse_quota


class AccountsMixin:
    # ------------------------------------------------------------ trạng thái cho giao diện
    def accounts(self) -> list:
        """Profile Muse của hệ thống (màn Profile trình duyệt) + cấu hình riêng của Studio Muse AI."""
        out = []
        for p in browser_profiles.list_profiles():
            if SITE not in p.get("sites", []):
                continue
            cfg = self.hub["accounts"].setdefault(p["id"], {"enabled": True, "threads": 1})
            out.append({"id": p["id"], "name": p["name"], "busy": p.get("busy", ""), "exists": p.get("exists", False),
                        "enabled": cfg.get("enabled", True), "threads": int(cfg.get("threads") or 1),
                        "quota": cfg.get("quota"), "logged_in": cfg.get("logged_in"),
                        "last_used_at": cfg.get("last_used_at", 0), "error": cfg.get("error", ""),
                        "running": sum(1 for a in self._running.values() if a == p["id"]),
                        "checking": p["id"] in self._quota_busy})
        return out

    def set_account(self, pid: str, patch: dict) -> dict:
        cfg = self.hub["accounts"].setdefault(pid, {"enabled": True, "threads": 1})
        if "enabled" in patch:
            cfg["enabled"] = bool(patch["enabled"])
        if "threads" in patch:
            try:
                cfg["threads"] = max(1, min(5, int(patch["threads"])))
            except (TypeError, ValueError):
                pass
        if patch.get("relogin"):  # vừa đăng nhập lại → bỏ dấu "chưa đăng nhập" để nhận task
            cfg.update(logged_in=None, error="")
        self._save()
        self._wake.set()
        self._push()
        return self.state()

    def refresh_quota(self, pid: str = "") -> None:
        """Đọc lại hạn mức (1 tài khoản hoặc tất cả, chạy nền). Tài khoản đang chạy task thì bỏ qua (profile đang mở)."""
        ids = [pid] if pid else [a["id"] for a in self.accounts() if a["enabled"]]
        for i in ids:
            if i in self._quota_busy or i in self._running.values():
                continue
            self._quota_busy.add(i)
            threading.Thread(target=self._quota_worker, args=(i,), daemon=True).start()
        self._push()

    def _quota_worker(self, pid: str) -> None:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright

        from ..llm.browser_chat import _launch
        from ..llm.muse_browser import BOX

        cfg = self.hub["accounts"].setdefault(pid, {"enabled": True, "threads": 1})
        try:
            with browser_profiles.task_context(pid), browser_profiles.profile_session(SITE, "Muse · hạn mức") as prof, \
                    sync_playwright() as pw:
                ctx = _launch(pw, self.settings.get("browser_channel"), visible=True, offscreen=True, profile=prof)
                try:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto("https://muse.ai", wait_until="domcontentloaded", timeout=60_000)
                    try:
                        page.locator(BOX).first.wait_for(state="visible", timeout=30_000)
                    except PWError:
                        cfg.update(logged_in=False, error="Chưa đăng nhập Muse")
                        return
                    page.wait_for_timeout(4000)  # chờ trang tải đủ các file JS
                    q = parse_quota(page.evaluate(QUOTA_JS))
                    cfg.update(logged_in=True, error="" if q else "Không đọc được hạn mức (Muse đổi giao diện?)")
                    if q:
                        cfg["quota"] = q
                finally:
                    try:
                        ctx.close()
                    except PWError:
                        pass
        except Exception as exc:  # profile bận / trình duyệt lỗi → báo trên thẻ tài khoản
            cfg["error"] = str(exc)[:200]
        finally:
            self._quota_busy.discard(pid)
            self._save()
            self._wake.set()
            self._push()
