"""Studio Muse AI · khởi tạo, lưu trạng thái, trạng thái gửi giao diện, cài đặt, dự án."""
import threading
from datetime import datetime
from pathlib import Path

from . import common as _c
from .common import DEFAULT_SETTINGS, HubError, MAX_IMAGES, OUT_DIR, RATIOS, STATUS, VIDEO_SECONDS, _read_json, _uid, _write_json, asset_url, now_ms, usable, weekly_out


class CoreMixin:
    def __init__(self, settings, emit) -> None:
        self.settings = settings  # cài đặt chung của app (thư mục video, trình duyệt)
        self._emit = emit
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._running: dict[str, str] = {}  # task_id → account_id
        self._cancel: dict[str, threading.Event] = {}
        self._quota_busy: set[str] = set()
        self._stopped = False
        self.hub = _read_json(_c.STORE / "hub.json", {})
        self.hub.setdefault("settings", {})
        self.hub["settings"] = {**DEFAULT_SETTINGS, **self.hub["settings"]}
        self.hub.setdefault("accounts", {})  # profile_id → {enabled, threads, quota, logged_in, last_used_at}
        self.hub.setdefault("projects", [{"id": "default", "name": "Mặc định", "paused": False}])
        self.hub.setdefault("current", "default")
        self.hub.setdefault("characters", [])
        self.hub.setdefault("templates", [])
        self.hub.setdefault("model", {"on": False, "images": []})
        self.hub["model"].setdefault("character", "")  # id nhân vật làm người mẫu ("" = ảnh tải riêng)
        self.hub.setdefault("rotate", {"on": False, "images": [], "idx": 0})
        self.tasks = _read_json(_c.STORE / "tasks.json", [])
        self.groups = _read_json(_c.STORE / "groups.json", [])  # video từ tab Kịch bản / LadiPage (gom các task của 1 video)
        for t in self.tasks:  # app tắt giữa chừng: task đang chạy chưa có kết quả → chờ chạy lại (chưa tính lượt)
            if t["status"] == "processing":
                t.update(status="queued", account="", error="App tắt khi đang chạy — đã xếp hàng lại")
                t["attempts"] = max(0, int(t.get("attempts") or 0) - 1)
        self._save()
        threading.Thread(target=self._loop, daemon=True, name="muse-hub").start()

    # ------------------------------------------------------------ lưu / phát sự kiện
    def _save(self) -> None:
        with self._lock:
            _write_json(_c.STORE / "hub.json", self.hub)
            _write_json(_c.STORE / "tasks.json", self.tasks)
            _write_json(_c.STORE / "groups.json", self.groups)

    def _push(self) -> None:
        self._emit("mhub_state", self.state())

    def out_root(self) -> Path:
        path = Path(self.settings.output_dir) / OUT_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def state(self) -> dict:
        with self._lock:
            accs = self.accounts()
            now = now_ms()
            for a in accs:
                a["usable"] = usable(a, self.hub["settings"], now)
                a["weekly_out"] = weekly_out(a.get("quota"))
            urls = lambda imgs: [{"path": p, "url": asset_url(p)} for p in imgs or []]  # noqa: E731
            return {"settings": self.hub["settings"], "accounts": accs, "projects": self.hub["projects"],
                    "current": self.hub["current"],
                    "characters": [{**c, "images": urls(c.get("images"))} for c in self.hub["characters"]],
                    "templates": self.hub["templates"],
                    "model": {**self.hub["model"], "images": urls(self.hub["model"]["images"])},
                    "rotate": {**self.hub["rotate"], "images": urls(self.hub["rotate"]["images"])},
                    "stopped": self._stopped,
                    "tasks": [self._public(t) for t in self.tasks], "statuses": STATUS, "ratios": list(RATIOS), "video_seconds": list(VIDEO_SECONDS),
                    "max_images": MAX_IMAGES, "out_dir": str(self.out_root()),
                    "groups": [self._public_group(g) for g in self.groups], "bgm_dir": str(self.bgm_dir())}

    def _public(self, t: dict) -> dict:
        base = Path(self.settings.output_dir)
        files = []
        for f in t.get("files") or []:
            p = Path(f)
            if not p.is_file():
                continue
            try:
                url = f"/media/{p.relative_to(base).as_posix()}?v={int(p.stat().st_mtime)}"
            except ValueError:
                url = ""
            files.append({"path": str(p), "name": p.name, "url": url,
                          "video": p.suffix.lower() in (".mp4", ".mov", ".webm")})
        return {**t, "files": files, "running": t["id"] in self._running,
                "image_urls": [asset_url(p) for p in t.get("images") or []]}

    # ------------------------------------------------------------ cài đặt / tài khoản
    def set_settings(self, patch: dict) -> dict:
        s = self.hub["settings"]
        clamp = {"max_accounts": (1, 20), "total_threads": (1, 50), "limit_image": (1, 60), "limit_video": (5, 120),
                 "retries": (0, 3)}
        for k, v in (patch or {}).items():
            if k in clamp:
                try:
                    s[k] = max(clamp[k][0], min(clamp[k][1], int(v)))
                except (TypeError, ValueError):
                    pass
            elif k == "mode" and v in ("rotate", "sequential"):
                s[k] = v
            elif k in ("use_topup", "keep_going", "show_browser"):
                s[k] = bool(v)
            elif k == "bgm_dir" and (not v or Path(str(v)).is_dir()):
                s[k] = str(v or "")
            elif k == "bgm_volume":
                try:
                    s[k] = max(0.02, min(0.6, float(v)))
                except (TypeError, ValueError):
                    pass
        self._save()
        self._wake.set()
        self._push()
        return self.state()

    # ------------------------------------------------------------ dự án
    def project(self, action: str, pid: str = "", name: str = "") -> dict:
        projects = self.hub["projects"]
        if action == "add":
            new = {"id": _uid("p"), "name": " ".join(str(name).split())[:60] or "Dự án mới", "paused": False}
            projects.append(new)
            self.hub["current"] = new["id"]
        elif action == "select" and any(p["id"] == pid for p in projects):
            self.hub["current"] = pid
        elif action == "rename":
            for p in projects:
                if p["id"] == pid:
                    p["name"] = " ".join(str(name).split())[:60] or p["name"]
        elif action == "pause":
            for p in projects:
                if p["id"] == pid:
                    p["paused"] = not p.get("paused")
        elif action == "delete":
            if pid == "default":
                raise HubError("Không xoá được dự án Mặc định")
            for t in self.tasks:
                if t.get("project") == pid and t["id"] in self._cancel:
                    self._cancel[t["id"]].set()
            self.tasks = [t for t in self.tasks if t.get("project") != pid]  # file đã tải vẫn giữ trên ổ đĩa
            self.hub["projects"] = [p for p in projects if p["id"] != pid]
            if self.hub["current"] == pid:
                self.hub["current"] = "default"
        self._save()
        self._wake.set()
        self._push()
        return self.state()

    def _task(self, task_id: str) -> dict | None:
        return next((t for t in self.tasks if t["id"] == task_id), None)

    def _log(self, task_id: str, msg: str) -> None:
        t = self._task(task_id)
        if t is not None:
            t.setdefault("log", []).append(f"{datetime.now():%H:%M:%S} {msg}")
            t["log"] = t["log"][-40:]
            self._emit("mhub_log", {"id": task_id, "line": t["log"][-1]})
