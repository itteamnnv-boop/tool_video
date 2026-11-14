"""📋 Tác vụ Canvas: 1 flow (bảng Canvas) chạy được NHIỀU tác vụ — mỗi tác vụ là 1 bảng chạy riêng chép từ flow
(ẩn khỏi danh sách Canvas, kết quả không đè lên nhau), mang đầu vào riêng (các ô "❓ Hỏi khi chạy" của flow).

- Bảng tác vụ: board["task_of"] = mã flow, board["task"] = {name, status, inputs, created_at, started_at, ended_at,
  run, error}. status: queued | running | done | partial | error | cancelled | interrupted.
- Chép flow: giữ khối Ảnh tải lên, khối 🔒 khoá và ảnh 📎 đính kèm (kèm file); khối khác về trạng thái chưa chạy.
- Hàng đợi: tối đa N tác vụ chạy cùng lúc (cài đặt "<prefix>task_parallel", mặc định 2); còn lại chờ, tự chạy khi có
  chỗ. Khối dùng chung 1 model trình duyệt vẫn chạy lần lượt (giới hạn sẵn có của Canvas).
- Đầu vào 1 tác vụ: {mã khối: {"prompt", "dialogue", "config": {...}, "file": đường dẫn ảnh}}.
"""
from __future__ import annotations

import copy
import shutil
import threading
import time
import uuid
from pathlib import Path

from .util import read_json


def now() -> str:
    from .canvas import now as canvas_now  # cùng định dạng giờ với bảng Canvas

    return canvas_now()


TASK_DEFAULT_PARALLEL = 2
TASK_MAX_PARALLEL = 6
MAX_TASKS_PER_CREATE = 50
FINAL = ("done", "partial", "error", "cancelled", "interrupted")
ACTIVE_TASK = ("running", "reviewing")  # reviewing = 🤖 trợ lý đang chấm / giao làm lại (vẫn giữ chỗ chạy cùng lúc)
AUTO_FINAL = ("passed", "failed", "stopped")
AUTO_STALE = 30 * 60  # 🤖 đang chấm mà không có gì đổi quá 30 phút (app tắt giữa chừng) → gián đoạn
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


class CanvasTasksMixin:
    """Gắn vào CanvasRunner (dùng self.root, self.load, self._save, self._edit, self.run_flow, self.pool, …)."""

    _tasks_lock = threading.RLock()

    # ------------------------------------------------------------------ cài đặt
    def task_parallel(self) -> int:
        try:
            n = int(self.settings.get(f"{self.prefix}task_parallel") or TASK_DEFAULT_PARALLEL)
        except (TypeError, ValueError):
            n = TASK_DEFAULT_PARALLEL
        return max(1, min(TASK_MAX_PARALLEL, n))

    def set_task_parallel(self, n) -> int:
        try:
            value = max(1, min(TASK_MAX_PARALLEL, int(n)))
        except (TypeError, ValueError):
            value = TASK_DEFAULT_PARALLEL
        self.settings.update({f"{self.prefix}task_parallel": value})
        self.tasks_tick()
        return value

    # ------------------------------------------------------------------ tạo
    def create_tasks(self, bid: str, items: list) -> list[str]:
        """Tạo các tác vụ cho flow bid (mỗi item: {"name", "inputs"}) → xếp hàng; trả mã bảng tác vụ."""
        from .canvas import CanvasError

        flow = self.load(bid)
        if flow.get("task_of"):
            raise CanvasError("Đây là bảng của 1 tác vụ — tạo tác vụ từ flow gốc")
        if not flow["nodes"]:
            raise CanvasError("Flow chưa có khối nào")
        items = [i for i in (items or []) if isinstance(i, dict)][:MAX_TASKS_PER_CREATE] or [{}]
        made = [self._new_task_board(flow, item, k, len(items)) for k, item in enumerate(items, 1)]
        self.tasks_tick()
        return made

    def _new_task_board(self, flow: dict, item: dict, k: int, total: int) -> str:
        from .canvas import ACTIVE

        tid = f"t-{uuid.uuid4().hex[:12]}"
        src_dir, dst_dir = self.root / flow["id"], self.root / tid
        (dst_dir / "nodes").mkdir(parents=True, exist_ok=True)
        board = copy.deepcopy(flow)
        board.pop("schedule", None)
        stamp = now()

        def keep(rel: str) -> str:
            path = src_dir / rel
            if rel and path.is_file():
                (dst_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst_dir / rel)
            return rel

        for n in board["nodes"]:
            for r in n.get("ref_files") or []:
                keep(r.get("file", ""))
            if n["kind"] == "upload" or n.get("locked"):
                n["files"] = [keep(f) for f in n.get("files") or []]
                n["versions"] = []
                if n.get("status") in ACTIVE:
                    n["status"] = "done" if n["files"] else "idle"
                continue
            n.update(files=[], out={}, status="idle", pct=0, error="", task="", approval={}, versions=[], pick=0,
                     stage="")
            for key in ("sig", "done_at", "secs", "made", "log_at", "qc"):
                n.pop(key, None)
        inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
        name = " ".join(str(item.get("name") or "").split())[:80] or self._task_name(flow, inputs, k, total)
        board.update(id=tid, name=name, created_at=stamp, updated_at=stamp, runs=[], run_seq=0, task_of=flow["id"],
                     task={"name": name, "status": "queued", "created_at": stamp, "started_at": "", "ended_at": "",
                           "run": "", "error": "", "inputs": self._input_summary(flow, inputs),
                           "order": time.time_ns(),  # thứ tự hàng đợi (tạo cùng 1 giây vẫn đúng thứ tự)
                           "raw": {k: {kk: vv for kk, vv in v.items() if kk in ("prompt", "dialogue", "config", "file")}
                                   for k, v in inputs.items() if isinstance(v, dict)}})  # ⧉ nhân bản tác vụ
        self._save(board)
        self._apply_inputs(tid, inputs)
        self._copy_auto(flow["id"], tid, item.get("auto"))
        return tid

    # ------------------------------------------------------------------ 🤖 tự điều phối
    def _assist_file(self, bid: str) -> Path:
        return self.root / bid / "assistant.json"

    def _auto_of(self, bid: str) -> dict:
        try:
            data = read_json(self._assist_file(bid)) if self._assist_file(bid).is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _copy_auto(self, flow_id: str, tid: str, override) -> None:
        """Tác vụ mang theo cài đặt 🤖 Tự điều phối của flow (tiêu chí, điểm đạt, số vòng); override = chỉnh riêng lượt tạo."""
        from .util import write_json

        auto = dict(self._auto_of(flow_id).get("auto") or {})
        if isinstance(override, dict):
            for k in ("on", "criteria", "pass_score", "rounds", "attach"):
                if k in override:
                    auto[k] = override[k]
        if auto.get("on") and not str(auto.get("criteria") or "").strip():
            auto["on"] = False  # chưa có tiêu chí → không tự điều phối
        if auto:
            write_json(self._assist_file(tid), {"chat_url": "", "messages": [], "auto": auto})

    def _auto_info(self, bid: str) -> dict:
        data = self._auto_of(bid)
        auto, state = data.get("auto") or {}, data.get("auto_state") or {}
        if not auto.get("on") and not state:
            return {}
        msgs = [m for m in data.get("messages") or [] if isinstance(m.get("auto"), dict)]
        last = msgs[-1] if msgs else {}
        return {"on": bool(auto.get("on")), "status": state.get("status", ""), "round": int(state.get("round") or 0),
                "rounds": int(auto.get("rounds") or 2), "score": (last.get("auto") or {}).get("score"),
                "pass_score": auto.get("pass_score"),
                "note": str((last.get("auto") or {}).get("note") or last.get("text") or last.get("error") or "")[:240],
                "at": state.get("at", "")}

    @staticmethod
    def _task_name(flow: dict, inputs: dict, k: int, total: int) -> str:
        for change in inputs.values():  # tên = giá trị chữ đầu tiên người dùng nhập
            if not isinstance(change, dict):
                continue
            for v in [change.get("prompt"), change.get("dialogue"), *(change.get("config") or {}).values()]:
                text = " ".join(str(v or "").split())
                if isinstance(v, str) and len(text) >= 2 and not text.startswith(("http://", "https://")):
                    return text[:60]
        return f"{flow['name']} #{k}" if total > 1 else f"{flow['name']} · tác vụ"

    def _input_summary(self, flow: dict, inputs: dict) -> list[dict]:
        out = []
        nodes = {n["id"]: n for n in flow["nodes"]}
        for nid, change in inputs.items():
            n = nodes.get(nid)
            if n is None or not isinstance(change, dict):
                continue
            label = n.get("title") or self.label(n)
            for key, value in [("Prompt", change.get("prompt")), ("Lời thoại", change.get("dialogue")),
                               *((k, v) for k, v in (change.get("config") or {}).items())]:
                if value not in (None, "") and not isinstance(value, (dict, list, bool)):
                    out.append({"node": nid, "label": f"{label} · {key}", "value": str(value)[:300]})
            if change.get("file"):
                out.append({"node": nid, "label": f"{label} · Ảnh", "value": Path(str(change["file"])).name})
        return out[:20]

    def _apply_inputs(self, tid: str, inputs: dict) -> None:
        """Đầu vào riêng của tác vụ → khối của bảng tác vụ (ô cấu hình chỉ nhận đúng ô của khối; ảnh chép vào bảng)."""
        changes = []
        ids = {n["id"]: n for n in self.load(tid)["nodes"]}
        for nid, change in (inputs or {}).items():
            n = ids.get(nid)
            if n is None or not isinstance(change, dict):
                continue
            ch = {"id": nid}
            if n["kind"] in ("image", "video"):
                if "prompt" in change:
                    ch["prompt"] = str(change["prompt"] or "")
                if "dialogue" in change and n["kind"] == "video":
                    ch["dialogue"] = str(change["dialogue"] or "")
            if n["kind"] == "wf" and isinstance(change.get("config"), dict):
                ch["config"] = change["config"]
            if len(ch) > 1:
                changes.append(ch)
            file = Path(str(change.get("file") or ""))
            if n["kind"] == "upload" and file.is_file() and file.suffix.lower() in IMAGE_EXT:
                rel = f"nodes/{nid}_in_{uuid.uuid4().hex[:6]}{file.suffix.lower()}"
                shutil.copy2(file, self.root / tid / rel)

                def put(b, nid=nid, rel=rel):
                    self._node(b, nid).update(files=[rel], pick=0, status="done", error="")
                self._edit(tid, put)
        if changes:
            self.update_nodes(tid, changes, record=False)

    # ------------------------------------------------------------------ hàng đợi
    def _task_boards(self) -> list[dict]:
        out = []
        for f in self.root.glob("t-*/board.json"):
            try:
                b = read_json(f)
            except (OSError, ValueError):
                continue
            if b.get("task_of"):
                out.append(b)
        return out

    def _set_task(self, tid: str, **fields) -> None:
        def apply(b):
            b.setdefault("task", {}).update(fields)
        try:
            self._edit(tid, apply)
        except Exception:  # noqa: BLE001 — bảng đã xoá
            pass

    def tasks_tick(self) -> list[str]:
        """Đồng bộ trạng thái tác vụ + chạy tác vụ đang chờ khi còn chỗ. Trả mã tác vụ vừa chạy."""
        from .canvas import CanvasError

        started = []
        with self._tasks_lock:
            boards = self._task_boards()
            live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
            running = 0
            for b in boards:
                t = b.get("task") or {}
                if t.get("status") == "reviewing":  # 🤖 trợ lý xong (đạt / chưa đạt / dừng) → kết thúc tác vụ
                    state = self._auto_of(b["id"]).get("auto_state") or {}
                    last_run = (b.get("runs") or [{}])[-1]
                    stamp = str(state.get("at") or "").replace("T", " ")  # trợ lý ghi ISO (có "T")
                    if state.get("status") in AUTO_FINAL and stamp >= str(t.get("review_since") or ""):
                        st = state["status"]
                        self._set_task(b["id"], status="done" if st != "failed" else "partial", ended_at=now(),
                                       error="" if st != "failed" else "🤖 Chưa đạt tiêu chí sau các vòng làm lại — cần bạn xem lại")
                    elif last_run.get("status") != "running" and self._auto_stale(state, t):
                        self._set_task(b["id"], status="interrupted", ended_at=now(),
                                       error="🤖 Tự điều phối bị gián đoạn — mở 🤖 Trợ lý để xem / chạy tiếp")
                    else:
                        running += 1
                    continue
                if t.get("status") != "running":
                    continue
                rec = next((r for r in b.get("runs") or [] if r["id"] == t.get("run")), None)
                if rec and rec.get("status") not in ("running", None):
                    self._set_task(b["id"], status=rec["status"] if rec["status"] in FINAL else "error",
                                   ended_at=t.get("ended_at") or now())
                elif rec and rec.get("task") not in live:
                    self._set_task(b["id"], status="interrupted", ended_at=now(),
                                   error="Bị gián đoạn (app tắt / tác vụ dừng giữa chừng) — bấm ▶ Chạy tiếp")
                else:
                    running += 1
            room = self.task_parallel() - running
            waiting = sorted((b for b in boards if (b.get("task") or {}).get("status") == "queued"),
                             key=lambda b: ((b.get("task") or {}).get("created_at") or "",
                                            int((b.get("task") or {}).get("order") or 0)))
            for b in waiting[:max(0, room)]:
                resume = bool((b.get("task") or {}).get("resume"))
                try:
                    self._task_start(b["id"], fresh=not resume)
                    started.append(b["id"])
                except CanvasError as exc:
                    msg = str(exc)
                    done = resume and "Không có node nào cần chạy" in msg  # chạy tiếp nhưng mọi khối đã xong
                    self._set_task(b["id"], status="done" if done else "error", ended_at=now(), resume=False,
                                   error="" if done else msg[:300])
        return started

    @staticmethod
    def _auto_stale(state: dict, task: dict) -> bool:
        from datetime import datetime

        stamp = str(state.get("at") or task.get("review_since") or "")
        try:
            return (datetime.now() - datetime.fromisoformat(stamp.replace(" ", "T"))).total_seconds() > AUTO_STALE
        except ValueError:
            return False

    def _task_start(self, tid: str, fresh: bool = True) -> None:
        board = self.run_flow(tid, "all", "", fresh, label="📋 Tác vụ" + ("" if fresh else " · chạy tiếp"))
        rec = (board.get("runs") or [{}])[-1]
        self._set_task(tid, status="running", run=rec.get("id", ""), started_at=now(), ended_at="", error="",
                       resume=False)
        self.emit("canvas_task", {"task": tid, "status": "running"})

    def _task_finished(self, tid: str, status: str) -> None:
        """Lượt chạy của bảng tác vụ xong (gọi từ cuối CanvasRunner._flow) → ghi trạng thái, chạy tác vụ đang chờ."""
        try:
            board = self.load(tid)
        except Exception:  # noqa: BLE001
            return
        if not board.get("task_of"):
            return
        cur = (board.get("task") or {}).get("status")
        if cur in ACTIVE_TASK and status != "cancelled" and (self._auto_of(tid).get("auto") or {}).get("on"):
            self._set_task(tid, status="reviewing", review_since=now(), last_run=status)  # 🤖 trợ lý chấm tiếp
            self.emit("canvas_task", {"task": tid, "status": "reviewing"})
            return
        if cur in ACTIVE_TASK:
            self._set_task(tid, status=status if status in FINAL else "error", ended_at=now())
        self.emit("canvas_task", {"task": tid, "status": status})
        threading.Thread(target=self.tasks_tick, daemon=True, name="canvas-tasks-tick").start()

    # ------------------------------------------------------------------ thao tác
    def task_cancel(self, tid: str) -> None:
        board = self.load(tid)
        was = (board.get("task") or {}).get("status")
        # ghi "Đã dừng" TRƯỚC: trợ lý dừng xong sẽ đồng bộ hàng đợi — không được ghi đè thành "Xong"
        self._set_task(tid, status="cancelled", ended_at=now(), resume=False)
        if was == "reviewing" and callable(getattr(self, "on_auto_stop", None)):
            try:
                self.on_auto_stop(tid)  # 🤖 dừng tự điều phối (và lượt làm lại đang chạy)
            except Exception:  # noqa: BLE001
                pass
        if was in ACTIVE_TASK:
            self.cancel_flow(tid)

    def task_resume(self, tid: str) -> None:
        """▶ Chạy tiếp: xếp hàng lại; khi tới lượt chỉ chạy khối chưa xong / lỗi (giữ khối đã xong)."""
        from .canvas import CanvasError

        board = self.load(tid)
        if (board.get("task") or {}).get("status") in ("running", "queued", "reviewing"):
            raise CanvasError("Tác vụ đang chạy / đang chờ")
        self._set_task(tid, status="queued", error="", resume=True, ended_at="")
        self.tasks_tick()

    def task_delete(self, tid: str) -> None:
        from .canvas import CanvasError

        board = self.load(tid)
        if not board.get("task_of"):
            raise CanvasError("Không phải tác vụ")
        if (board.get("task") or {}).get("status") in ACTIVE_TASK:
            self.task_cancel(tid)
        self.delete(tid)

    def task_clear(self, statuses: list) -> int:
        """Xoá hàng loạt tác vụ theo trạng thái (VD: các tác vụ đã xong)."""
        n = 0
        for b in self._task_boards():
            if (b.get("task") or {}).get("status") in (statuses or []):
                try:
                    self.task_delete(b["id"])
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
        return n

    def task_cancel_all(self) -> int:
        n = 0
        for b in self._task_boards():
            if (b.get("task") or {}).get("status") in ("running", "queued", "reviewing"):
                self.task_cancel(b["id"])
                n += 1
        return n

    # ------------------------------------------------------------------ danh sách
    def tasks(self, bid: str = "") -> dict:
        self.tasks_tick()
        flows, out = {}, []
        for b in self._task_boards():
            if bid and b["task_of"] != bid:
                continue
            t = b.get("task") or {}
            if b["task_of"] not in flows:
                try:
                    flows[b["task_of"]] = self.load(b["task_of"])["name"]
                except Exception:  # noqa: BLE001 — flow gốc đã xoá
                    flows[b["task_of"]] = "(flow đã xoá)"
            rec = next((r for r in b.get("runs") or [] if r["id"] == t.get("run")), None) or {}
            states = list((rec.get("nodes") or {}).values())
            consumed = {i for n in b["nodes"] for i in n.get("inputs") or []}
            results = []
            for n in b["nodes"]:  # kết quả cuối: khối không có khối nào phía sau, đã có file
                if n["id"] in consumed or not n.get("files") or n["kind"] == "upload":
                    continue
                rel = n["files"][min(int(n.get("pick") or 0), len(n["files"]) - 1)]
                url = self._url(b["id"], rel)
                if url:
                    results.append({"node": n["id"], "title": n.get("title") or self.label(n), "url": url,
                                    "video": Path(rel).suffix.lower() in (".mp4", ".mov", ".webm")})
            size = sum(f.stat().st_size for f in (self.root / b["id"]).rglob("*") if f.is_file())
            out.append({"id": b["id"], "name": b["name"], "flow": b["task_of"], "flow_name": flows[b["task_of"]],
                        "status": t.get("status") or "queued", "created_at": t.get("created_at", ""),
                        "started_at": t.get("started_at", ""), "ended_at": t.get("ended_at", ""),
                        "error": t.get("error", ""), "inputs": t.get("inputs") or [], "raw": t.get("raw") or {},
                        "done": sum(1 for s in states if s == "done"), "total": len(states),
                        "current": rec.get("current", ""), "results": results[:4], "size": size,
                        "auto": self._auto_info(b["id"]),
                        "folder": str(self.root / b["id"])})
        out.sort(key=lambda x: x["created_at"], reverse=True)
        stats = {s: sum(1 for x in out if x["status"] == s)
                 for s in ("queued", "running", "reviewing", "done", "partial", "error", "cancelled", "interrupted")}
        return {"tasks": out, "stats": {**stats, "total": len(out)}, "parallel": self.task_parallel(),
                "flows": [{"id": k, "name": v} for k, v in flows.items()]}
