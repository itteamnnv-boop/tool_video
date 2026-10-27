"""Lập lịch chạy quy trình Canvas: một lần / hằng ngày / các thứ trong tuần / cứ N phút.

Bộ hẹn giờ chạy nền khi app đang mở (kiểm tra mỗi 20 giây): tới giờ → chạy cả quy trình ("⏰ Chạy theo lịch"). Đang có node
chạy → lùi 5 phút. Lỡ giờ vì app tắt (quá 15 phút) → BỎ lượt đó (không chạy bù) và tính lượt kế tiếp. Đăng bài vẫn chờ
duyệt như chạy tay (trừ khối đã bật tự đăng); khối "Hỏi khi chạy" dùng giá trị đã lưu. Giờ theo giờ máy.
board["schedule"] = {on, mode, time "HH:MM", date "YYYY-MM-DD", days [0=T2…6=CN], every_min, fresh, next_at, last_at, last_note}
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

from .util import read_json

MODES = ("once", "daily", "weekly", "interval")
DAY_VI = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
MISS_GRACE = 15 * 60  # quá 15 phút so với giờ hẹn (app đang tắt) → bỏ lượt
BUSY_DELAY = 5 * 60   # đang có node chạy → lùi
EVERY_MIN = (15, 1440)

log = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def _hm(value) -> str:
    try:
        h, m = (int(x) for x in str(value or "").split(":")[:2])
    except ValueError:
        return "08:00"
    return f"{max(0, min(23, h)):02d}:{max(0, min(59, m)):02d}"


def clean(cfg: dict, cur: dict | None = None) -> dict:
    out = {"on": False, "mode": "daily", "time": "08:00", "date": "", "days": [0, 1, 2, 3, 4], "every_min": 60,
           "fresh": True, "next_at": "", "last_at": "", "last_note": "", **(cur or {})}
    if "on" in cfg:
        out["on"] = bool(cfg["on"])
    if cfg.get("mode") in MODES:
        out["mode"] = cfg["mode"]
    if "time" in cfg:
        out["time"] = _hm(cfg["time"])
    if "date" in cfg:
        try:
            out["date"] = date.fromisoformat(str(cfg["date"])[:10]).isoformat() if cfg["date"] else ""
        except ValueError:
            out["date"] = ""
    if "days" in cfg:
        out["days"] = sorted({int(d) for d in cfg.get("days") or [] if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
    if "every_min" in cfg:
        try:
            out["every_min"] = max(EVERY_MIN[0], min(EVERY_MIN[1], int(cfg["every_min"])))
        except (TypeError, ValueError):
            pass
    if "fresh" in cfg:
        out["fresh"] = bool(cfg["fresh"])
    return out


def next_time(s: dict, after: datetime) -> datetime | None:
    """Lượt chạy kế tiếp SAU thời điểm after (None = không còn lượt nào)."""
    if not s.get("on"):
        return None
    h, m = (int(x) for x in _hm(s.get("time")).split(":"))
    mode = s.get("mode")
    if mode == "once":
        try:
            dt = datetime.combine(date.fromisoformat(s.get("date") or ""), datetime.min.time()).replace(hour=h, minute=m)
        except ValueError:
            return None
        return dt if dt > after else None
    if mode == "interval":
        return (after + timedelta(minutes=int(s.get("every_min") or 60))).replace(microsecond=0)
    days = set(s.get("days") or []) if mode == "weekly" else set(range(7))
    if not days:
        return None
    for k in range(8):
        d = after.date() + timedelta(days=k)
        dt = datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)
        if d.weekday() in days and dt > after:
            return dt
    return None


def describe(s: dict | None) -> str:
    """Lịch bằng chữ cho thẻ / hộp thoại: "hằng ngày 08:00", "T2, T4, T6 lúc 08:00", "mỗi 2 giờ", "một lần 28/10 08:00"."""
    if not s:
        return ""
    t = _hm(s.get("time"))
    mode = s.get("mode")
    if mode == "once":
        try:
            return f"một lần {date.fromisoformat(s.get('date') or '').strftime('%d/%m')} {t}"
        except ValueError:
            return f"một lần {t}"
    if mode == "interval":
        n = int(s.get("every_min") or 60)
        return f"mỗi {n // 60} giờ" if n % 60 == 0 else f"mỗi {n} phút"
    if mode == "weekly":
        days = s.get("days") or []
        return ("hằng ngày" if len(days) == 7 else ", ".join(DAY_VI[d] for d in days) or "chưa chọn thứ") + f" lúc {t}"
    return f"hằng ngày {t}"


def set_schedule(runner, bid: str, cfg: dict) -> dict:
    """Lưu lịch của 1 Canvas (tính luôn lượt kế tiếp). Trả board công khai."""
    from .canvas import CanvasError

    def apply(board):
        s = clean(cfg or {}, board.get("schedule"))
        if s["on"]:
            if s["mode"] == "weekly" and not s["days"]:
                raise CanvasError("Chọn ít nhất 1 thứ trong tuần")
            if s["mode"] == "once" and not s["date"]:
                raise CanvasError("Chọn ngày chạy")
            nxt = next_time(s, datetime.now())
            if nxt is None:
                raise CanvasError("Thời điểm chạy đã qua — chọn giờ khác")
            s["next_at"] = _iso(nxt)
        else:
            s["next_at"] = ""
        board["schedule"] = s
    return runner.public(runner._edit(bid, apply))


class CanvasScheduler:
    """Thread nền: mỗi `every` giây chạy các Canvas tới giờ hẹn."""

    def __init__(self, runner, every: float = 20.0) -> None:
        self.runner, self.every = runner, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="canvas-scheduler")

    def start(self) -> "CanvasScheduler":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # bộ hẹn giờ không được chết vì 1 Canvas lỗi
                log.exception("Lỗi bộ hẹn giờ Canvas")
            self._stop.wait(self.every)

    def _update(self, bid: str, **fields) -> None:
        def apply(board):
            board["schedule"] = {**(board.get("schedule") or {}), **fields}
        try:
            self.runner._edit(bid, apply)
        except Exception:  # Canvas vừa bị xoá
            return
        self.runner.emit("canvas_schedule", {"board": bid, "schedule": fields})

    def tick(self, now: datetime | None = None) -> list[str]:
        """Chạy các Canvas tới giờ; trả danh sách id đã chạy (để kiểm thử)."""
        from .canvas import ACTIVE

        now = now or datetime.now()
        ran = []
        root = self.runner.root
        for f in root.glob("*/board.json"):
            try:
                board = read_json(f)
            except (OSError, ValueError):
                continue
            s = board.get("schedule") or {}
            if not s.get("on") or not s.get("next_at"):
                continue
            try:
                due = datetime.fromisoformat(s["next_at"])
            except ValueError:
                continue
            if due > now:
                continue
            bid = board["id"]
            if (now - due).total_seconds() > MISS_GRACE:  # app tắt lúc tới giờ → bỏ lượt, tính lượt sau
                nxt = next_time(s, now)
                self._update(bid, next_at=_iso(nxt), on=nxt is not None,
                             last_note=f"Bỏ lỡ lượt {due:%d/%m %H:%M} (app đang tắt) — không chạy bù")
                continue
            if any(n.get("status") in ACTIVE for n in board["nodes"]):
                self._update(bid, next_at=_iso(now + timedelta(seconds=BUSY_DELAY)),
                             last_note=f"Đang có node chạy lúc {now:%H:%M} — lùi 5 phút")
                continue
            try:
                self.runner.run_flow(bid, "all", "", bool(s.get("fresh", True)), origin="schedule",
                                     label="⏰ Chạy theo lịch")  # run_flow tự thêm "(làm lại từ đầu)" khi fresh
                note = f"Đã chạy lúc {now:%d/%m %H:%M}"
                ran.append(bid)
            except Exception as exc:  # còn lỗi cấu hình / không có gì cần chạy → ghi lại, vẫn tính lượt sau
                note = f"Không chạy được lúc {now:%d/%m %H:%M}: {str(exc)[:200]}"
            nxt = next_time(s, now)
            self._update(bid, last_at=_iso(now), last_note=note, next_at=_iso(nxt), on=nxt is not None)
        return ran
