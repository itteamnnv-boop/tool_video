"""Studio Muse AI — dây chuyền Muse: nhiều tài khoản (profile Muse của hệ thống) chạy song song, hạn mức tuần,
hàng đợi task ảnh / video có lịch sử, dự án, tư liệu (nhân vật, mẫu prompt, người mẫu cố định, ảnh luân phiên),
thư viện file + ghép video.

- Tài khoản = profile trình duyệt đã gán Muse (màn Profile trình duyệt) — không đăng nhập lại, không tạo profile riêng.
- Gửi / nhận: dùng bộ điều khiển Muse sẵn có (app/llm/muse_browser.py), chỉ định đúng profile bằng task_context.
- Hạn mức tuần: đọc chỉ đọc từ trang muse.ai đã đăng nhập (server action của trang Muse, không tốn lượt).
- Dữ liệu: <DATA_DIR>/muse_hub/{hub.json, tasks.json, assets/}; file kết quả: <thư mục video>/_muse_hub/<dự án>/.
"""
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import browser_profiles
from .paths import DATA_DIR

STORE = DATA_DIR / "muse_hub"
OUT_DIR = "_muse_hub"
SITE = "muse"
MAX_IMAGES = 3  # Muse nhận tối đa 3 ảnh đính kèm / lệnh (app/llm/video_engines.py)
RATIOS = ("9:16", "16:9", "1:1", "4:3", "3:4")
DEFAULT_SETTINGS = {"max_accounts": 2, "total_threads": 2, "mode": "rotate", "use_topup": True, "keep_going": False,
                    "limit_image": 5, "limit_video": 30, "show_browser": False, "retries": 1, "bgm_dir": "",
                    "bgm_volume": 0.15}
STATUS = {"queued": "Chờ chạy", "processing": "Đang chạy", "succeeded": "Xong", "failed": "Lỗi", "cancelled": "Đã huỷ",
          "waiting": "Chờ storyboard", "review": "Chờ duyệt storyboard"}
TERMINAL = ("succeeded", "failed", "cancelled")
QUOTA_HINT = re.compile(r"limit|quota|hạn mức|giới hạn|đã dùng hết|upgrade|nâng cấp", re.I)

# Đọc hạn mức tuần trên trang muse.ai đã đăng nhập: tìm id server action "fetchSubscriptionAction" trong các file JS
# trang đã tải (id đổi theo bản cập nhật của Muse) rồi gọi action đó — chỉ đọc, không tốn lượt.
QUOTA_JS = r"""async () => {
  let id = window.__vaQuotaAction || null;
  if (!id) {
    const srcs = performance.getEntriesByType('resource').map(e => e.name).filter(n => /\.js(\?|$)/.test(n));
    for (const src of srcs) {
      try {
        const t = await (await fetch(src)).text();
        const m = t.match(/createServerReference\)\("([0-9a-f]{20,})"[^)]*?"fetchSubscriptionAction"/);
        if (m) { id = m[1]; break; }
      } catch (e) {}
    }
    window.__vaQuotaAction = id;
  }
  if (!id) return {error: 'no_action'};
  const r = await fetch('/', {method: 'POST', body: '[{}]',
    headers: {'Next-Action': id, 'Accept': 'text/x-component', 'Content-Type': 'text/plain;charset=UTF-8'}});
  const line = (await r.text()).split('\n').find(l => l.startsWith('1:'));
  if (!line) return {error: 'no_data'};
  try { return JSON.parse(line.slice(2)); } catch (e) { return {error: 'bad_json'}; }
}"""


class HubError(RuntimeError):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- hạn mức
def parse_quota(data: dict) -> dict | None:
    """Kết quả fetchSubscriptionAction → {pct, resets_at (ms), status, tier, paid, topup_left (0..1|None), label…}."""
    sub = (data or {}).get("subscription") if isinstance(data, dict) else None
    if not isinstance(sub, dict):
        return None
    usage = sub.get("usage") or {}
    tier = sub.get("tier") or {}
    total, left = sub.get("topupTotal"), sub.get("topupBalance")
    return {"pct": float(usage.get("percentUsed") or 0), "resets_at": int(usage.get("resetsAt") or 0) * 1000,
            "status": str(usage.get("quotaStatus") or ""), "tier": str(tier.get("name") or ""),
            "paid": bool(tier.get("isPaid")),
            "topup_left": (left / total) if isinstance(left, (int, float)) and total else (0.0 if left == 0 else None),
            "label": str(sub.get("usageRowValueLabel") or ""), "subtitle": str(sub.get("statusSubtitle") or ""),
            "topup_label": str(sub.get("topupRowValueLabel") or ""), "checked_at": now_ms()}


def weekly_out(q: dict | None) -> bool:
    if not q:
        return False
    return q["pct"] >= 100 or bool(re.search(r"EXHAUST|EXCEED|DEPLET|LIMIT|OUT|BLOCK", q.get("status", ""), re.I))


def usable(acc: dict, settings: dict, now: int) -> bool:
    """Tài khoản nhận task mới: bật, chưa bị phát hiện đăng xuất, và hạn mức cho phép."""
    if not acc.get("enabled", True) or acc.get("logged_in") is False:
        return False
    q = acc.get("quota")
    if not q or not weekly_out(q):
        return True
    if q.get("resets_at") and now >= q["resets_at"]:
        return True  # đã qua ngày đặt lại — số liệu cũ hết hiệu lực
    if settings.get("use_topup") and (q.get("topup_left") or 0) > 0:
        return True
    return bool(settings.get("keep_going"))


def plan(tasks: list, accounts: list, settings: dict, running: dict, paused_projects: set, now: int) -> list:
    """Chọn (task, tài khoản) để bắt đầu ngay. running: {task_id: account_id} đang chạy."""
    total = max(1, int(settings.get("total_threads") or 1))
    max_acc = max(1, int(settings.get("max_accounts") or 1))
    load = {}
    for acc_id in running.values():
        load[acc_id] = load.get(acc_id, 0) + 1
    slots = total - len(running)
    out = []
    queue = sorted((t for t in tasks if t["status"] == "queued" and t.get("project") not in paused_projects),
                   key=lambda t: t["created_at"])
    pool = [a for a in accounts if usable(a, settings, now)]
    for task in queue:
        if slots <= 0:
            break
        active = {a for a, n in load.items() if n > 0}
        cands = [a for a in pool if load.get(a["id"], 0) < int(a.get("threads") or 1)
                 and (a["id"] in active or len(active) < max_acc)]
        if not cands:
            break
        if settings.get("mode") == "sequential":  # lấp đầy luồng tài khoản trước rồi mới sang tài khoản sau
            pick = cands[0]
        else:  # luân phiên: ít việc nhất → dùng ít hạn mức nhất → lâu chưa dùng nhất
            pick = min(cands, key=lambda a: (load.get(a["id"], 0), (a.get("quota") or {}).get("pct", 0),
                                             a.get("last_used_at", 0)))
        out.append((task["id"], pick["id"]))
        load[pick["id"]] = load.get(pick["id"], 0) + 1
        slots -= 1
    return out


# ---------------------------------------------------------------- ghép ảnh đính kèm cho mỗi prompt
def compose_images(prompt: str, studio: dict, task_images: list, take_rotate) -> tuple[list, list]:
    """Thứ tự: người mẫu cố định → nhân vật có tên trong prompt → 1 ảnh luân phiên → ảnh của task. Bỏ trùng, tối đa
    MAX_IMAGES. Trả về (ảnh, ghi chú)."""
    notes, out = [], []
    model = studio.get("model") or {}
    if model.get("on"):
        out += model.get("images") or []
    text = f" {prompt.lower()} "
    named = [c for c in studio.get("characters") or []
             if c.get("name") and re.search(rf"(?<!\w){re.escape(c['name'].lower())}(?!\w)", text)]
    for c in named:
        out += c.get("images") or []
    if named:
        notes.append("Nhân vật: " + ", ".join(c["name"] for c in named))
    rotate = studio.get("rotate") or {}
    if rotate.get("on") and rotate.get("images"):
        out.append(take_rotate())
    out += task_images or []
    seen, uniq = set(), []
    for p in out:
        if p and p not in seen and Path(p).is_file():
            seen.add(p)
            uniq.append(p)
    if len(uniq) > MAX_IMAGES:
        notes.append(f"Muse nhận tối đa {MAX_IMAGES} ảnh — bỏ {len(uniq) - MAX_IMAGES} ảnh cuối")
    return uniq[:MAX_IMAGES], notes


def asset_url(path: str) -> str:
    """Ảnh trong kho Studio Muse AI → URL xem trước (route /mhub-asset/ của server nội bộ)."""
    try:
        return "/mhub-asset/" + Path(path).resolve().relative_to(STORE.resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def safe_name(folder: Path, name: str) -> Path:
    base = re.sub(r'[\\/:*?"<>|]+', " ", str(name or "")).strip().removesuffix(".mp4").strip() or "ghep-video"
    path, n = folder / f"{base}.mp4", 2
    while path.exists():
        path, n = folder / f"{base}-{n}.mp4", n + 1
    return path


# ---------------------------------------------------------------- trung tâm điều phối
class MuseHub:
    def __init__(self, settings, emit) -> None:
        self.settings = settings  # cài đặt chung của app (thư mục video, trình duyệt)
        self._emit = emit
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._running: dict[str, str] = {}  # task_id → account_id
        self._cancel: dict[str, threading.Event] = {}
        self._quota_busy: set[str] = set()
        self._stopped = False
        self.hub = _read_json(STORE / "hub.json", {})
        self.hub.setdefault("settings", {})
        self.hub["settings"] = {**DEFAULT_SETTINGS, **self.hub["settings"]}
        self.hub.setdefault("accounts", {})  # profile_id → {enabled, threads, quota, logged_in, last_used_at}
        self.hub.setdefault("projects", [{"id": "default", "name": "Mặc định", "paused": False}])
        self.hub.setdefault("current", "default")
        self.hub.setdefault("characters", [])
        self.hub.setdefault("templates", [])
        self.hub.setdefault("model", {"on": False, "images": []})
        self.hub.setdefault("rotate", {"on": False, "images": [], "idx": 0})
        self.tasks = _read_json(STORE / "tasks.json", [])
        self.groups = _read_json(STORE / "groups.json", [])  # video từ tab Kịch bản / LadiPage (gom các task của 1 video)
        for t in self.tasks:  # app tắt giữa chừng: task đang chạy chưa có kết quả → chờ chạy lại (chưa tính lượt)
            if t["status"] == "processing":
                t.update(status="queued", account="", error="App tắt khi đang chạy — đã xếp hàng lại")
                t["attempts"] = max(0, int(t.get("attempts") or 0) - 1)
        self._save()
        threading.Thread(target=self._loop, daemon=True, name="muse-hub").start()

    # ------------------------------------------------------------ lưu / phát sự kiện
    def _save(self) -> None:
        with self._lock:
            _write_json(STORE / "hub.json", self.hub)
            _write_json(STORE / "tasks.json", self.tasks)
            _write_json(STORE / "groups.json", self.groups)

    def _push(self) -> None:
        self._emit("mhub_state", self.state())

    def out_root(self) -> Path:
        path = Path(self.settings.output_dir) / OUT_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

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
                    "tasks": [self._public(t) for t in self.tasks], "statuses": STATUS, "ratios": list(RATIOS),
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

        from .llm.browser_chat import _launch
        from .llm.muse_browser import BOX

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

    # ------------------------------------------------------------ tư liệu
    def _copy_asset(self, src: str) -> str:
        p = Path(src)
        if not p.is_file():
            raise HubError(f"Không thấy ảnh: {src}")
        assets = STORE / "assets"
        if p.parent == assets:
            return str(p)
        assets.mkdir(parents=True, exist_ok=True)
        dest = assets / f"{uuid.uuid4().hex[:12]}{p.suffix.lower()}"
        shutil.copy2(p, dest)
        return str(dest)

    def _all_assets(self) -> list:
        return [*self.hub["model"]["images"], *self.hub["rotate"]["images"],
                *(i for c in self.hub["characters"] for i in c.get("images") or [])]

    def asset(self, kind: str, data: dict) -> dict:
        before = self._all_assets()
        data = data or {}
        if kind == "character":
            name = " ".join(str(data.get("name") or "").split())[:40]
            if not name:
                raise HubError("Nhập tên nhân vật (gõ đúng tên này trong prompt để tự gắn ảnh)")
            images = [self._copy_asset(i) for i in (data.get("images") or [])][:3]
            hit = next((c for c in self.hub["characters"] if c["id"] == data.get("id")), None)
            if hit:
                hit.update(name=name, images=images)
            else:
                self.hub["characters"].append({"id": _uid("c"), "name": name, "images": images})
        elif kind == "character_delete":
            self.hub["characters"] = [c for c in self.hub["characters"] if c["id"] != data.get("id")]
        elif kind == "template":
            text = str(data.get("text") or "").strip()[:4000]
            if not text:
                raise HubError("Mẫu prompt trống")
            name = " ".join(str(data.get("name") or "").split())[:60] or text[:40]
            hit = next((t for t in self.hub["templates"] if t["id"] == data.get("id")), None)
            if hit:
                hit.update(name=name, text=text)
            else:
                self.hub["templates"].append({"id": _uid("t"), "name": name, "text": text})
        elif kind == "template_delete":
            self.hub["templates"] = [t for t in self.hub["templates"] if t["id"] != data.get("id")]
        elif kind in ("model", "rotate"):
            box = self.hub[kind]
            if "on" in data:
                box["on"] = bool(data["on"])
            if "images" in data:
                box["images"] = [self._copy_asset(i) for i in data["images"]][:3 if kind == "model" else 20]
                if kind == "rotate":
                    box["idx"] = 0
        else:
            raise HubError("Loại tư liệu không hợp lệ")
        used = set(self._all_assets())  # ảnh bị bỏ khỏi danh sách → xoá bản chép
        for p in before:
            if p not in used and Path(p).parent == STORE / "assets":
                Path(p).unlink(missing_ok=True)
        self._save()
        self._push()
        return self.state()

    def import_images(self, paths: list) -> list:
        """Ảnh tham chiếu chọn từ máy → chép vào kho uploads (xem trước được, đường dẫn gốc đổi / xoá không hỏng)."""
        folder = STORE / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for src in paths or []:
            p = Path(str(src))
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                dest = folder / f"{uuid.uuid4().hex[:12]}{p.suffix.lower()}"
                shutil.copy2(p, dest)
                out.append({"path": str(dest), "url": asset_url(str(dest)), "name": p.name})
        return out

    def _take_rotate(self) -> str:
        r = self.hub["rotate"]
        imgs = r.get("images") or []
        if not imgs:
            return ""
        i = int(r.get("idx") or 0) % len(imgs)
        r["idx"] = i + 1
        return imgs[i]

    # ------------------------------------------------------------ task
    def add_tasks(self, form: dict) -> dict:
        kind = "video" if form.get("kind") == "video" else "image"
        prompts = [str(p).strip() for p in (form.get("prompts") or []) if str(p).strip()]
        if not prompts:
            raise HubError("Nhập ít nhất 1 prompt (mỗi khối cách nhau 1 dòng trống = 1 task)")
        ratio = form.get("ratio") if form.get("ratio") in RATIOS else ""
        images = [str(p) for p in (form.get("images") or []) if Path(str(p)).is_file()]
        pairing = form.get("pairing") == "pair"  # ghép cặp: ảnh thứ i cho prompt thứ i; dùng chung: mọi prompt cùng ảnh
        project = form.get("project") or self.hub["current"]
        created = []
        with self._lock:
            for i, prompt in enumerate(prompts[:200]):
                own = ([images[i]] if i < len(images) else []) if pairing else images
                refs, notes = compose_images(prompt, self.hub, own, self._take_rotate)
                task = {"id": _uid("tk"), "project": project, "kind": kind, "prompt": prompt[:6000], "ratio": ratio,
                        "images": refs, "notes": notes, "status": "queued", "account": "", "attempts": 0,
                        "created_at": now_ms() + i, "started_at": 0, "finished_at": 0, "files": [], "error": "",
                        "log": []}
                self.tasks.append(task)
                created.append(task["id"])
            self._save()
        self._wake.set()
        self._push()
        return {"created": created}

    def task_action(self, ids: list, action: str) -> dict:
        ids = set(ids or [])
        with self._lock:
            for t in self.tasks:
                if t["id"] not in ids:
                    continue
                if action == "cancel":
                    if t["id"] in self._cancel:
                        self._cancel[t["id"]].set()  # worker tự đặt trạng thái huỷ
                    elif t["status"] == "queued":
                        t.update(status="cancelled", finished_at=now_ms(), error="Đã huỷ")
                elif action == "retry" and t["status"] in ("failed", "cancelled", "succeeded"):
                    t.update(status="queued", attempts=0, error="", account="", started_at=0, finished_at=0)
                    g = next((x for x in self.groups if x["id"] == t.get("group")), None)
                    if g is not None:
                        g["status"] = "running"
            if action == "delete":
                for i in ids:
                    if i in self._cancel:
                        self._cancel[i].set()
                self.tasks = [t for t in self.tasks if t["id"] not in ids]
            self._save()
        self._wake.set()
        self._push()
        return self.state()

    def stop_all(self) -> dict:
        """Dừng tất cả: huỷ task đang chạy + tạm dừng hàng đợi (bấm Chạy tiếp để chạy lại)."""
        self._stopped = True
        for ev in list(self._cancel.values()):
            ev.set()
        self._push()
        return self.state()

    def resume(self) -> dict:
        self._stopped = False
        self._wake.set()
        self._push()
        return self.state()

    # ------------------------------------------------------------ vòng điều phối
    def _loop(self) -> None:
        import logging

        last_quota = 0.0
        while True:
            self._wake.wait(5)
            self._wake.clear()
            try:
                if time.time() - last_quota > 3600:  # mỗi giờ đọc lại hạn mức tài khoản đã qua ngày đặt lại
                    last_quota = time.time()
                    for a in self.accounts():
                        q = a.get("quota")
                        if a["enabled"] and q and q.get("resets_at") and now_ms() >= q["resets_at"]:
                            self.refresh_quota(a["id"])
                if self._stopped:
                    continue
                with self._lock:
                    paused = {p["id"] for p in self.hub["projects"] if p.get("paused")}
                    picks = plan(self.tasks, self.accounts(), self.hub["settings"], dict(self._running), paused,
                                 now_ms())
                    for task_id, acc_id in picks:
                        task = self._task(task_id)
                        task.update(status="processing", account=acc_id, started_at=now_ms(), error="")
                        task["attempts"] = int(task.get("attempts") or 0) + 1
                        self._running[task_id] = acc_id
                        self._cancel[task_id] = threading.Event()
                        threading.Thread(target=self._run, args=(task_id, acc_id), daemon=True).start()
                    if picks:
                        self._save()
                if picks:
                    self._push()
            except Exception:  # vòng điều phối không được chết
                logging.getLogger(__name__).exception("muse hub loop")

    def _task(self, task_id: str) -> dict | None:
        return next((t for t in self.tasks if t["id"] == task_id), None)

    def _log(self, task_id: str, msg: str) -> None:
        t = self._task(task_id)
        if t is not None:
            t.setdefault("log", []).append(f"{datetime.now():%H:%M:%S} {msg}")
            t["log"] = t["log"][-40:]
            self._emit("mhub_log", {"id": task_id, "line": t["log"][-1]})

    def _run(self, task_id: str, acc_id: str) -> None:
        from .llm.base import LLMError
        from .llm.muse_browser import muse_images, muse_video
        from .pipeline import Cancelled

        task = self._task(task_id)
        cancel = self._cancel[task_id]
        s = self.hub["settings"]
        project_dir = self.out_root() / (task.get("project") or "default")
        project_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        def check_cancel():
            if cancel.is_set():
                raise Cancelled()

        log = lambda m, level="info": self._log(task_id, m)  # noqa: E731
        error, files = "", []
        try:
            with browser_profiles.task_context(acc_id, check_cancel=check_cancel, log=log):
                images = [Path(p) for p in task.get("images") or [] if Path(p).is_file()]
                ratio = task.get("ratio") or "9:16"
                if task["kind"] == "video":
                    out = project_dir / f"{stamp}_{task_id[-6:]}.mp4"
                    muse_video(task["prompt"], out, channel=self.settings.get("browser_channel"),
                               show_browser=bool(s.get("show_browser")), aspect=ratio, images=images, log=log,
                               check_cancel=check_cancel, timeout_s=int(s["limit_video"]) * 60,
                               duration=f"{int(task.get('duration') or 10)}s", refs_note=task.get("refs_note"))
                    if not out.is_file() or out.stat().st_size < 10_000:  # kiểm tra file tải về
                        raise LLMError("File video tải về rỗng / hỏng")
                    files = [str(out)]
                else:
                    datas = muse_images(task["prompt"], aspect=ratio, count=1, images=images,
                                        channel=self.settings.get("browser_channel"),
                                        show_browser=bool(s.get("show_browser")), log=log, check_cancel=check_cancel,
                                        timeout_s=int(s["limit_image"]) * 60)
                    for k, data in enumerate(datas):
                        if len(data) < 2000:
                            continue
                        out = project_dir / f"{stamp}_{task_id[-6:]}_{k + 1}.png"
                        out.write_bytes(data)
                        files.append(str(out))
                    if not files:
                        raise LLMError("Muse không trả về ảnh")
        except Cancelled:
            error = "__cancel__"
        except Exception as exc:  # lỗi model / trình duyệt → ghi lý do vào task
            error = str(exc)[:600] or exc.__class__.__name__
        with self._lock:
            self._running.pop(task_id, None)
            self._cancel.pop(task_id, None)
            task = self._task(task_id)
            cfg = self.hub["accounts"].setdefault(acc_id, {"enabled": True, "threads": 1})
            cfg["last_used_at"] = now_ms()
            if task is not None:
                if error == "__cancel__":
                    task.update(status="cancelled", finished_at=now_ms(), error="Đã huỷ")
                elif not error:
                    task.update(status="succeeded", finished_at=now_ms(), files=files, error="")
                    self._log(task_id, f"Xong · {len(files)} file")
                elif "Chưa đăng nhập Muse" in error:  # tài khoản đăng xuất → nghỉ, task chuyển tài khoản khác
                    cfg.update(logged_in=False, error="Chưa đăng nhập Muse")
                    task.update(status="queued", account="", error=error, attempts=max(0, task["attempts"] - 1))
                elif QUOTA_HINT.search(error):  # nghi hết hạn mức → đọc lại hạn mức, task xếp hàng lại (không tính lượt)
                    task.update(status="queued", account="", error=error, attempts=max(0, task["attempts"] - 1))
                    threading.Thread(target=self.refresh_quota, args=(acc_id,), daemon=True).start()
                elif task["attempts"] <= int(s.get("retries", 1)):
                    task.update(status="queued", account="", error=f"Thử lại: {error}")
                    self._log(task_id, f"Lỗi — tự thử lại: {error[:160]}")
                else:
                    task.update(status="failed", finished_at=now_ms(), error=error)
                self._after_task(task)
            self._save()
        self._wake.set()
        self._push()

    # ------------------------------------------------------------ thư viện + ghép video
    def library(self, project: str = "") -> list:
        out = []
        for t in self.tasks:
            if t["status"] != "succeeded" or (project and t.get("project") != project):
                continue
            for f in self._public(t)["files"]:
                out.append({**f, "task": t["id"], "kind": t["kind"], "prompt": t["prompt"][:300],
                            "project": t.get("project"), "finished_at": t.get("finished_at")})
        return sorted(out, key=lambda x: x.get("finished_at") or 0, reverse=True)

    def merge(self, paths: list, name: str, project: str = "") -> dict:
        """Ghép nhiều video theo thứ tự (chạy nền, tiến độ qua sự kiện mhub_merge)."""
        from . import ffmpeg

        files = [Path(p) for p in paths or [] if Path(p).is_file()]
        if len(files) < 2:
            raise HubError("Chọn ít nhất 2 video để ghép")
        folder = self.out_root() / (project or self.hub["current"]) / "ghep"
        folder.mkdir(parents=True, exist_ok=True)
        out = safe_name(folder, name)
        job = uuid.uuid4().hex[:8]

        def run():
            err = self._merge_files(files, out, lambda pct: self._emit("mhub_merge", {"job": job, "pct": pct,
                                                                                         "path": str(out)}))
            self._emit("mhub_merge", {"job": job, "pct": -1 if err else 100, "path": str(out), "done": True,
                                      "error": err})

        threading.Thread(target=run, daemon=True).start()
        return {"job": job, "path": str(out)}

    def _merge_files(self, files: list, out: Path, progress=None) -> str:
        """Ghép video theo thứ tự (mã hoá lại cùng khung hình / fps / âm thanh). Trả về "" nếu xong, ngược lại là lỗi."""
        from . import ffmpeg

        try:
            durations = [ffmpeg.media_duration(f) for f in files]
            w, h = ffmpeg.video_size(files[0])
        except Exception as exc:  # file hỏng
            return str(exc)
        size = "1920:1080" if w > h else "1080:1920"
        inputs, chains = [], []
        for i, f in enumerate(files):
            inputs += ["-i", str(f)]
            chains.append(f"[{i}:v]scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2,"
                          f"setsar=1,fps=30,format=yuv420p[v{i}]")
            chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]" if ffmpeg.has_audio(f)
                          else f"anullsrc=r=44100:cl=stereo,atrim=duration={durations[i]:.3f}[a{i}]")
        chains.append("".join(f"[v{i}][a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=1:a=1[v][a]")
        args = [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                "-progress", "pipe:1", "-nostats", str(out)]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", creationflags=ffmpeg.NO_WINDOW)
        total = sum(durations) or 0
        for line in proc.stdout:
            if progress and line.startswith("out_time_us=") and total:
                try:
                    progress(min(99, round(int(line.split("=")[1]) / 1e6 / total * 100)))
                except ValueError:
                    pass
        err = proc.stderr.read()
        return "" if proc.wait() == 0 and out.is_file() else (err.strip()[-300:] or "ffmpeg lỗi")

    # ------------------------------------------------------------ Kịch bản / LadiPage → nhóm task
    def bgm_dir(self) -> Path:
        path = Path(self.hub["settings"].get("bgm_dir") or (self.out_root() / "nhac-nen"))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _public_group(self, g: dict) -> dict:
        tasks = [t for t in self.tasks if t.get("group") == g["id"]]
        base = Path(self.settings.output_dir)
        outs = []
        for f in g.get("outputs") or []:
            p = Path(f)
            if p.is_file():
                try:
                    url = f"/media/{p.relative_to(base).as_posix()}?v={int(p.stat().st_mtime)}"
                except ValueError:
                    url = ""
                outs.append({"path": str(p), "name": p.name, "url": url})
        sb = next((t for t in tasks if t.get("role") == "storyboard"), None)
        sb_files = self._public(sb)["files"] if sb else []
        return {**g, "outputs": outs, "storyboard": sb_files[0] if sb_files else None,
                "tasks": [{"id": t["id"], "role": t.get("role", ""), "status": t["status"], "scene": t.get("scene", 0),
                           "error": t.get("error", "")} for t in tasks]}

    def add_script(self, form: dict) -> dict:
        """Tab Kịch bản / LadiPage → nhóm task. form: {mode: script|image, text, method, ratio, duration, prefix, voice,
        presenter, character, merge, bgm, versions, product_images[], motions[], note, title}."""
        from . import muse_script as ms

        mode = "image" if form.get("mode") == "image" else "script"
        ratio = form.get("ratio") if form.get("ratio") in RATIOS else "9:16"
        method = form.get("method") if form.get("method") in ms.METHODS else "direct"
        duration = str(form.get("duration") or "10")
        if duration not in ms.DURATIONS:
            duration = "10"
        per_scene = duration == "per_scene"
        voice = form.get("voice") if form.get("voice") in ms.VOICES else "none"
        presenter = form.get("presenter") if form.get("presenter") in ("female", "male") else ""
        prefix = str(form.get("prefix") or "").strip()[:600]
        try:
            versions = max(1, min(5, int(form.get("versions") or 1)))
        except (TypeError, ValueError):
            versions = 1
        products = [str(p) for p in form.get("product_images") or [] if Path(str(p)).is_file()]  # mỗi ảnh = 1 bộ video
        shared = [str(p) for p in form.get("images") or [] if Path(str(p)).is_file()]  # gửi kèm MỌI video (LadiPage)
        dry = bool(form.get("dry"))  # "Xem lệnh sẽ gửi Muse": dựng prompt, không tạo task
        char = next((c for c in self.hub["characters"] if c["id"] == form.get("character")), None)
        char_imgs = [p for p in (char or {}).get("images", []) if Path(p).is_file()]
        project = form.get("project") or self.hub["current"]
        created = []

        def new_task(group, **kw):
            t = {"id": _uid("tk"), "project": project, "kind": "video", "prompt": "", "ratio": ratio, "images": [],
                 "notes": [], "status": "queued", "account": "", "attempts": 0, "created_at": now_ms() + len(created),
                 "started_at": 0, "finished_at": 0, "files": [], "error": "", "log": [], "group": group["id"]}
            t.update(kw)
            self.tasks.append(t)
            created.append(t["id"])
            return t

        def new_group(**kw):
            g = {"id": _uid("g"), "project": project, "mode": mode, "ratio": ratio, "status": "running",
                 "created_at": now_ms(), "outputs": [], "bgm": bool(form.get("bgm")), "versions": versions}
            g.update(kw)
            self.groups.append(g)
            return g

        with self._lock:
            n_tasks, n_groups, rot = len(self.tasks), len(self.groups), self.hub["rotate"].get("idx", 0)
            if mode == "image":
                if not products:
                    raise HubError("Chọn ít nhất 1 ảnh sản phẩm (mỗi ảnh = 1 video)")
                motions = [m for m in form.get("motions") or [] if m in ms.MOTIONS] or ["zoom"]
                prompt = ms.image_motion_prompt(motions, str(form.get("note") or ""))
                for product in products:
                    for v in range(versions):
                        g = new_group(title=Path(product).name[:60], method="direct", duration="10", merge=False,
                                      version=v + 1, scenes=[prompt])
                        new_task(g, role="video", prompt=prompt, duration=10, images=[product, *char_imgs][:MAX_IMAGES])
            else:
                videos = ms.parse_script(form.get("text"))
                if not videos:
                    raise HubError("Nhập kịch bản: mỗi dòng 1 cảnh, cách 1 dòng trống để sang video tiếp theo")
                for product in products or [None]:
                    for scenes in videos:
                        refs, _ = compose_images(" ".join(scenes), self.hub,
                                                 ([product] if product else []) + shared + char_imgs, self._take_rotate)
                        for v in range(versions):
                            title = str(form.get("title") or "").strip() or scenes[0]
                            g = new_group(title=title[:70], method=method, duration=duration, version=v + 1,
                                          scenes=scenes, merge=per_scene and len(scenes) > 1 and form.get("merge", True)
                                          is not False, voice=voice, presenter=presenter)
                            sb = None
                            if method in ("storyboard", "review"):
                                sb = new_task(g, role="storyboard", kind="image", images=list(refs),
                                              prompt=ms.storyboard_prompt(scenes, prefix=prefix, presenter=presenter))
                            extra = {"status": "waiting" if sb else "queued", "after": sb["id"] if sb else "",
                                     "refs_note": ms.STORYBOARD_REFS if sb else (ms.PRODUCT_REFS if refs else None)}
                            if per_scene:
                                for i, scene in enumerate(scenes, 1):
                                    new_task(g, role="scene", scene=i, duration=10, images=list(refs), **extra,
                                             prompt=ms.video_prompt([scene], seconds=10, prefix=prefix, voice=voice,
                                                                    presenter=presenter, storyboard=bool(sb),
                                                                    product=bool(product)))
                            else:
                                secs = ms.DURATIONS[duration]
                                new_task(g, role="video", duration=secs, images=list(refs), **extra,
                                         prompt=ms.video_prompt(scenes, seconds=secs, prefix=prefix, voice=voice,
                                                                presenter=presenter, storyboard=bool(sb),
                                                                product=bool(product or shared)))
            if dry:  # chỉ xem lệnh: trả prompt rồi bỏ các task / nhóm vừa dựng
                preview = [{"role": t.get("role"), "scene": t.get("scene", 0), "kind": t["kind"], "prompt": t["prompt"],
                            "images": len(t["images"]), "duration": t.get("duration", 0), "status": t["status"]}
                           for t in self.tasks[n_tasks:]]
                self.tasks, self.groups = self.tasks[:n_tasks], self.groups[:n_groups]
                self.hub["rotate"]["idx"] = rot
                return {"preview": preview, "groups": len(self.groups) - n_groups}
            self._save()
        self._wake.set()
        self._push()
        return {"created": created, "groups": len({self._task(i)["group"] for i in created})}

    def approve(self, group_id: str) -> dict:
        """Duyệt storyboard → các task video của nhóm vào hàng đợi."""
        with self._lock:
            n = 0
            for t in self.tasks:
                if t.get("group") == group_id and t["status"] == "review":
                    t["status"] = "queued"
                    n += 1
            if not n:
                raise HubError("Nhóm này không có video chờ duyệt")
            self._save()
        self._wake.set()
        self._push()
        return self.state()

    def delete_group(self, group_id: str) -> dict:
        ids = [t["id"] for t in self.tasks if t.get("group") == group_id]
        self.task_action(ids, "delete")
        with self._lock:
            self.groups = [g for g in self.groups if g["id"] != group_id]
            self._save()
        self._push()
        return self.state()

    def _after_task(self, task: dict) -> None:
        """Gọi trong khoá sau khi 1 task kết thúc: mở khoá task chờ storyboard + hoàn tất nhóm khi đủ."""
        g = next((x for x in self.groups if x["id"] == task.get("group")), None)
        if task.get("role") == "storyboard":
            for t in self.tasks:
                if t.get("after") != task["id"] or t["status"] != "waiting":
                    continue
                if task["status"] == "succeeded" and task.get("files"):
                    sb = task["files"][0]
                    t["images"] = [sb, *[p for p in t["images"] if p != sb]][:MAX_IMAGES]
                    t["status"] = "review" if g and g.get("method") == "review" else "queued"
                elif task["status"] in ("failed", "cancelled"):
                    t.update(status=task["status"], finished_at=now_ms(),
                             error="Storyboard không tạo được" if task["status"] == "failed" else "Đã huỷ")
            if task["status"] == "succeeded":
                return
        if g is None:
            return
        tasks = [t for t in self.tasks if t.get("group") == g["id"]]
        if any(t["status"] not in TERMINAL for t in tasks):
            return
        videos = [t for t in tasks if t.get("role") in ("video", "scene")]
        if not videos or any(t["status"] != "succeeded" for t in videos):
            g["status"] = "failed" if any(t["status"] == "failed" for t in tasks) else "cancelled"
            return
        g["status"] = "finishing"
        threading.Thread(target=self._finish_group, args=(g["id"],), daemon=True).start()

    def _finish_group(self, group_id: str) -> None:
        """Nhóm đủ video: ghép các cảnh (nếu làm từng cảnh) → lót nhạc nền (nếu bật, giữ cả bản không nhạc)."""
        import random

        g = next((x for x in self.groups if x["id"] == group_id), None)
        if g is None:
            return
        videos = sorted([t for t in self.tasks if t.get("group") == group_id and t.get("role") in ("video", "scene")],
                        key=lambda t: t.get("scene", 0))
        files = [Path(t["files"][0]) for t in videos if t.get("files")]
        folder = self.out_root() / (g.get("project") or "default") / "video"
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[\\/:*?"<>|]+', " ", g.get("title") or "")[:50].strip() or "video"
        outputs, err = [], ""
        if g.get("merge") and len(files) > 1:
            out = safe_name(folder, f"{stem} v{g.get('version', 1)}")
            err = self._merge_files(files, out)
            if not err:
                outputs.append(out)
        else:
            outputs = list(files)
        if not err and g.get("bgm"):
            tracks = [p for p in self.bgm_dir().iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")]
            if tracks:
                mixed = []
                for f in outputs:
                    out = safe_name(folder, f"{Path(f).stem} - nhac")
                    if not self._mix_bgm(Path(f), random.choice(tracks), out):
                        mixed.append(out)
                outputs += mixed
            else:
                err = f"Bật nhạc nền nhưng thư mục nhạc trống: {self.bgm_dir()}"
        with self._lock:
            g.update(outputs=[str(p) for p in outputs], status="done" if outputs else "failed", error=err)
            self._save()
        self._push()

    def _mix_bgm(self, video: Path, track: Path, out: Path) -> str:
        from . import ffmpeg

        vol = float(self.hub["settings"].get("bgm_volume") or 0.15)
        audio = ("[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]" if ffmpeg.has_audio(video)
                 else "[bg]anull[a]")
        try:
            ffmpeg.run(["-i", video, "-stream_loop", "-1", "-i", track, "-filter_complex",
                        f"[1:a]volume={vol:.2f}[bg];{audio}", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", out])
            return ""
        except Exception as exc:  # ffmpeg lỗi → giữ bản không nhạc
            return str(exc)[:200]

    # ------------------------------------------------------------ LadiPage
    def ladi_images(self, urls: list) -> list:
        """Tải ảnh sản phẩm đã chọn từ trang về kho uploads → [{path, url}] để gửi kèm Muse."""
        from . import muse_script as ms

        out = []
        for u in (urls or [])[:6]:
            p = ms.download_image(u, STORE / "uploads", uuid.uuid4().hex[:12])
            out.append({"path": str(p), "url": asset_url(str(p)), "name": Path(u.split("?")[0]).name})
        return out
