"""Nhiều profile trình duyệt (mỗi profile = một thư mục user-data riêng = một bộ tài khoản đăng nhập riêng).

- Mỗi profile được gán cho một hoặc nhiều model (gemini / grok / chatgpt / dola).
- Khi một tác vụ cần trình duyệt cho một model, app chọn profile RẢNH đầu tiên trong số profile được gán cho model đó;
  nếu tất cả đang bận thì chờ. Nhờ vậy nhiều tác vụ chạy song song khi có nhiều profile (nhiều tài khoản).
- Một thư mục profile chỉ mở được bởi một Chrome tại một thời điểm → mỗi profile có một khoá riêng.
- Tác vụ có thể chỉ định profile cụ thể (bỏ qua việc tự chọn) qua task_context(profile=...).

Profile "default" dùng lại thư mục cũ (gemini-profile) nên giữ nguyên các phiên đăng nhập đã có.
"""
import json
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime

from .paths import BROWSER_PROFILE_DIR, DATA_DIR
from .util import slugify

PROFILES_FILE = DATA_DIR / "browser_profiles.json"
PROFILES_ROOT = DATA_DIR / "browser-profiles"
SITE_NAMES = {"gemini": "Gemini", "grok": "Grok", "chatgpt": "ChatGPT", "dola": "Dola", "doubao": "Doubao",
              "muse": "Muse (Meta)", "claude": "Claude"}
LATER_SITES = ("claude",)  # model thêm sau khi đã có file profile (chưa có known_sites) — xem _load
CHANNELS = ("", "chrome", "msedge", "chromium")  # "" = theo Cài đặt chung
DEFAULT_ID = "default"
MAX_PROFILES = 30

_lock = threading.RLock()
_cond = threading.Condition(_lock)
_busy: dict[str, str] = {}  # profile_id → mô tả việc đang dùng
_local = threading.local()


class ProfileError(RuntimeError):
    pass


# ------------------------------------------------------------------ lưu trữ
def _load() -> list[dict]:
    profiles = []
    if PROFILES_FILE.exists():
        try:
            profiles = json.loads(PROFILES_FILE.read_text("utf-8")).get("profiles", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            profiles = []
    if not any(p.get("id") == DEFAULT_ID for p in profiles):
        profiles.insert(0, {"id": DEFAULT_ID, "name": "Mặc định", "channel": "", "sites": list(SITE_NAMES),
                            "created_at": datetime.now().isoformat(timespec="seconds")})
    for p in profiles:
        p["sites"] = [s for s in p.get("sites", []) if s in SITE_NAMES]
        p.setdefault("channel", "")
        if p["id"] == DEFAULT_ID:  # model mới thêm sau này → tự gán cho profile Mặc định một lần (bỏ gán thì giữ nguyên)
            known = p.get("known_sites") or [s for s in SITE_NAMES if s not in LATER_SITES]
            p["sites"] += [s for s in SITE_NAMES if s not in known and s not in p["sites"]]
            p["known_sites"] = list(SITE_NAMES)
    return profiles


def _save(profiles: list[dict]) -> None:
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(PROFILES_FILE)


def profile_dir(profile_id: str):
    return BROWSER_PROFILE_DIR if profile_id == DEFAULT_ID else PROFILES_ROOT / profile_id


def _get(profiles: list[dict], profile_id: str) -> dict:
    found = next((p for p in profiles if p["id"] == profile_id), None)
    if found is None:
        raise ProfileError("Không tìm thấy profile")
    return found


# ------------------------------------------------------------------ quản lý (gọi từ API)
def list_profiles() -> list[dict]:
    with _lock:
        return [{**p, "busy": _busy.get(p["id"], ""), "exists": profile_dir(p["id"]).exists()} for p in _load()]


def create(name: str, sites: list | None = None, channel: str = "") -> list[dict]:
    name = (name or "").strip()[:40]
    if not name:
        raise ProfileError("Hãy nhập tên profile (VD: Grok – tài khoản 2)")
    with _lock:
        profiles = _load()
        if len(profiles) >= MAX_PROFILES:
            raise ProfileError(f"Tối đa {MAX_PROFILES} profile")
        base = slugify(name, 24) if slugify(name, 24) != "video" else "profile"
        pid, n = base, 2
        while any(p["id"] == pid for p in profiles) or pid == DEFAULT_ID:
            pid, n = f"{base}-{n}", n + 1
        profiles.append({"id": pid, "name": name, "channel": channel if channel in CHANNELS else "",
                         "sites": [s for s in (sites or []) if s in SITE_NAMES],
                         "created_at": datetime.now().isoformat(timespec="seconds")})
        _save(profiles)
    return list_profiles()


def update(profile_id: str, name: str | None = None, sites: list | None = None, channel: str | None = None) -> list[dict]:
    with _lock:
        profiles = _load()
        p = _get(profiles, profile_id)
        if name is not None:
            if not name.strip():
                raise ProfileError("Tên profile không được để trống")
            p["name"] = name.strip()[:40]
        if sites is not None:
            p["sites"] = [s for s in sites if s in SITE_NAMES]
        if channel is not None:
            p["channel"] = channel if channel in CHANNELS else ""
        _save(profiles)
        _cond.notify_all()  # tác vụ đang chờ có thể dùng được profile vừa gán thêm
    return list_profiles()


def delete(profile_id: str, remove_data: bool = True) -> list[dict]:
    if profile_id == DEFAULT_ID:
        raise ProfileError("Không xoá được profile Mặc định")
    with _lock:
        if profile_id in _busy:
            raise ProfileError("Profile đang được dùng — chờ tác vụ xong rồi xoá")
        profiles = _load()
        _get(profiles, profile_id)
        _save([p for p in profiles if p["id"] != profile_id])
    folder = profile_dir(profile_id)
    if remove_data and folder.exists() and folder.parent == PROFILES_ROOT:  # chỉ xoá thư mục do app tạo
        shutil.rmtree(folder, ignore_errors=True)
    return list_profiles()


def site_summary() -> dict:
    """Số profile gán cho mỗi model — UI hiển thị."""
    profiles = _load()
    return {s: [p["id"] for p in profiles if s in p["sites"]] for s in SITE_NAMES}


# ------------------------------------------------------------------ dùng trong tác vụ
@contextmanager
def task_context(profile: str = "", check_cancel=None, log=None):
    """Đặt ngữ cảnh cho thread tác vụ hiện tại: profile chỉ định (tuỳ chọn), hàm kiểm tra huỷ, hàm ghi log."""
    old = getattr(_local, "ctx", None)
    _local.ctx = {"profile": profile or "", "check_cancel": check_cancel, "log": log}
    try:
        yield
    finally:
        _local.ctx = old


def _ctx() -> dict:
    return getattr(_local, "ctx", None) or {"profile": "", "check_cancel": None, "log": None}


@contextmanager
def profile_session(site: str, purpose: str = ""):
    """Giữ một profile rảnh cho `site` trong suốt khối with. Trả về dict profile (id, name, dir, channel)."""
    ctx = _ctx()
    wanted = ctx["profile"]
    logged = False
    with _cond:
        while True:
            profiles = _load()
            if wanted:
                candidates = [p for p in profiles if p["id"] == wanted]
                if not candidates:
                    raise ProfileError(f"Profile '{wanted}' không còn tồn tại — chọn lại profile")
            else:
                candidates = [p for p in profiles if site in p["sites"]]
                if not candidates:
                    raise ProfileError(f"Chưa có profile nào được gán cho {SITE_NAMES.get(site, site)} — "
                                       "vào 'Profile trình duyệt' để gán")
            free = next((p for p in candidates if p["id"] not in _busy), None)
            if free is not None:
                _busy[free["id"]] = purpose or SITE_NAMES.get(site, site)
                break
            if not logged and ctx["log"]:
                names = ", ".join(p["name"] for p in candidates)
                ctx["log"](f"Đang chờ profile rảnh cho {SITE_NAMES.get(site, site)} ({names} đang bận)", "warn")
                logged = True
            if ctx["check_cancel"]:
                ctx["check_cancel"]()  # huỷ trong lúc chờ → ném Cancelled của runner
            _cond.wait(0.5)
    if ctx["log"]:
        ctx["log"](f"Dùng profile trình duyệt “{free['name']}” cho {SITE_NAMES.get(site, site)}")
    try:
        path = profile_dir(free["id"])
        path.mkdir(parents=True, exist_ok=True)
        yield {"id": free["id"], "name": free["name"], "dir": path, "channel": free.get("channel", "")}
    finally:
        with _cond:
            _busy.pop(free["id"], None)
            _cond.notify_all()


def busy_ids() -> dict:
    with _lock:
        return dict(_busy)
