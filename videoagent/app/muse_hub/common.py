"""Studio Muse AI — hằng số, kho dữ liệu (STORE) và hàm thuần dùng chung (điều phối, hạn mức, ghép ảnh tham chiếu)."""
import base64
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .. import browser_profiles
from ..paths import DATA_DIR

STORE = DATA_DIR / "muse_hub"
OUT_DIR = "_muse_hub"
SITE = "muse"
MAX_IMAGES = 3  # Muse nhận tối đa 3 ảnh đính kèm / lệnh (app/llm/video_engines.py)
RATIOS = ("9:16", "16:9", "1:1", "4:3", "3:4")
VIDEO_SECONDS = (5, 8, 10, 15, 20, 25, 30, 40, 50, 60)  # độ dài 1 video Muse (tab Studio — tạo lẻ)
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
            "topup_label": str(sub.get("topupRowValueLabel") or ""), "checked_at": now_ms(),
            # số token bổ sung (Additional token) còn lại / tổng — hiện ở tab Tài khoản
            "topup_balance": left if isinstance(left, (int, float)) else None,
            "topup_total": total if isinstance(total, (int, float)) else None}


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
def model_character(studio: dict) -> dict | None:
    """Nhân vật đang được chọn làm người mẫu cố định (None = dùng ảnh tải riêng)."""
    cid = (studio.get("model") or {}).get("character")
    return next((c for c in studio.get("characters") or [] if cid and c.get("id") == cid), None)


def compose_images(prompt: str, studio: dict, task_images: list, take_rotate) -> tuple[list, list]:
    """Thứ tự: người mẫu cố định → nhân vật có tên trong prompt → 1 ảnh luân phiên → ảnh của task. Bỏ trùng, tối đa
    MAX_IMAGES. Người mẫu cố định là ảnh tải riêng, hoặc ảnh của 1 nhân vật đã chọn (model["character"]).
    Trả về (ảnh, ghi chú)."""
    notes, out = [], []
    model = studio.get("model") or {}
    if model.get("on"):
        hero = model_character(studio)
        out += (hero.get("images") if hero else model.get("images")) or []
        if hero:
            notes.append("Người mẫu: " + hero["name"])
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
