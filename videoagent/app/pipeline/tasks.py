"""Hàng đợi tác vụ chạy song song (dùng chung cho Tạo video và Tạo ảnh).

- Mỗi tác vụ chạy trong một thread riêng; tối đa `limit()` tác vụ chạy cùng lúc, phần còn lại ở trạng thái "chờ".
- Runner gọi `pool.current` để lấy tác vụ của thread hiện tại (log, tiến trình, cờ huỷ riêng từng tác vụ).
- Sự kiện gửi lên UI luôn kèm "task" (id tác vụ) + sự kiện `<prefix>tasks` chứa danh sách tác vụ mỗi khi trạng thái đổi.
"""
from __future__ import annotations  # TaskPool có phương thức tên `list` — tránh che kiểu list trong chú thích

import logging
import threading
from collections import deque
from datetime import datetime

from ..browser_profiles import task_context
from . import Cancelled

log = logging.getLogger(__name__)
MAX_LOG = 400
KEEP_FINISHED = 30
ACTIVE = ("queued", "running")


class Task:
    def __init__(self, task_id: str, title: str, meta: dict) -> None:
        self.id = task_id
        self.title = title
        self.meta = meta
        self.status = "queued"
        self.pct = 0.0
        self.stage = "prepare"
        self.status_text = "Đang chờ tới lượt"
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.result = None
        self.error = ""
        self.cancel_event = threading.Event()
        self.logs: deque = deque(maxlen=MAX_LOG)
        self.data: dict = {}  # chỗ runner lưu trạng thái riêng (VD: thư mục đang tạo dở)

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "pct": self.pct, "stage": self.stage,
                "status_text": self.status_text, "created_at": self.created_at, "error": self.error,
                "result": self.result, **self.meta}


class TaskPool:
    def __init__(self, prefix: str, emit, limit) -> None:
        self._prefix = prefix  # "" cho video, "image_" cho ảnh
        self._emit = emit
        self._limit = limit  # hàm trả về số tác vụ chạy song song tối đa (đọc từ Cài đặt mỗi lần)
        self._tasks: dict[str, Task] = {}
        self._cond = threading.Condition()
        self._seq = 0
        self._local = threading.local()

    # ------------------------------------------------------------------ truy vấn
    @property
    def current(self) -> Task:
        task = getattr(self._local, "task", None)
        if task is None:
            raise RuntimeError("Không ở trong thread tác vụ")
        return task

    @property
    def running(self) -> bool:
        with self._cond:
            return any(t.status in ACTIVE for t in self._tasks.values())

    def list(self) -> list[dict]:
        with self._cond:
            return [t.summary() for t in self._tasks.values()]

    def logs(self, task_id: str) -> list[dict]:
        with self._cond:
            task = self._tasks.get(task_id)
            return list(task.logs) if task else []

    # ------------------------------------------------------------------ điều khiển
    def submit(self, title: str, target, *args, meta: dict | None = None, profile: str = "") -> str:
        with self._cond:
            self._seq += 1
            task = Task(f"{self._prefix or 'v'}{self._seq}", title[:120], {**(meta or {}), "profile": profile})
            self._tasks[task.id] = task
            self._trim()
        threading.Thread(target=self._worker, args=(task, profile, target, args), daemon=True,
                         name=f"task-{task.id}").start()
        self._broadcast()
        return task.id

    def cancel(self, task_id: str = "") -> int:
        """Huỷ một tác vụ (hoặc tất cả nếu task_id rỗng). Trả về số tác vụ bị huỷ."""
        with self._cond:
            targets = [t for t in self._tasks.values() if t.status in ACTIVE and (not task_id or t.id == task_id)]
            for t in targets:
                t.cancel_event.set()
            self._cond.notify_all()
        return len(targets)

    def wait(self, task_id: str, check_cancel=None, poll: float = 0.5) -> dict:
        """Chờ một tác vụ kết thúc (gọi từ thread KHÁC, VD: chiến dịch chờ tác vụ ảnh/video), trả về summary.
        check_cancel() ném Cancelled (phía chờ bị huỷ) → huỷ luôn tác vụ đang chờ rồi ném tiếp."""
        while True:
            with self._cond:
                task = self._tasks.get(task_id)
                if task is None:
                    raise RuntimeError(f"Không còn tác vụ {task_id}")
                if task.status not in ACTIVE:
                    return task.summary()
                self._cond.wait(poll)
            if check_cancel is not None:
                try:
                    check_cancel()
                except Cancelled:
                    self.cancel(task_id)
                    raise

    def clear_finished(self) -> None:
        with self._cond:
            for tid in [t.id for t in self._tasks.values() if t.status not in ACTIVE]:
                del self._tasks[tid]
        self._broadcast()

    # ------------------------------------------------------------------ dùng trong runner
    def log(self, message: str, level: str = "info") -> None:
        task = self.current
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "message": message, "level": level, "task": task.id}
        task.logs.append(entry)
        self._emit(f"{self._prefix}log", entry)

    def progress(self, pct: float, status: str, stage: str) -> None:
        task = self.current
        task.pct, task.stage = round(min(100.0, pct), 1), stage
        if status:
            task.status_text = status
        self._emit(f"{self._prefix}progress", {"pct": task.pct, "status": task.status_text, "stage": stage,
                                               "task": task.id})

    def check_cancel(self) -> None:
        if self.current.cancel_event.is_set():
            raise Cancelled()

    # ------------------------------------------------------------------ nội bộ
    def _trim(self) -> None:
        finished = [t for t in self._tasks.values() if t.status not in ACTIVE]
        for t in finished[:-KEEP_FINISHED] if len(finished) > KEEP_FINISHED else []:
            del self._tasks[t.id]

    def _broadcast(self) -> None:
        self._emit(f"{self._prefix}tasks", {"tasks": self.list()})

    def _set(self, task: Task, status: str, **fields) -> None:
        with self._cond:
            task.status = status
            for k, v in fields.items():
                setattr(task, k, v)
            self._cond.notify_all()
        self._broadcast()

    def _wait_slot(self, task: Task) -> None:
        with self._cond:
            while True:
                if task.cancel_event.is_set():
                    raise Cancelled()
                running = sum(1 for t in self._tasks.values() if t.status == "running")
                if running < max(1, int(self._limit() or 1)):
                    task.status = "running"
                    task.status_text = "Bắt đầu"
                    return
                self._cond.wait(0.5)

    def _worker(self, task: Task, profile: str, target, args) -> None:
        self._local.task = task
        try:
            self._wait_slot(task)
        except Cancelled:
            self._set(task, "cancelled", status_text="Đã huỷ khi đang chờ")
            self._emit(f"{self._prefix}cancelled", {"task": task.id})
            return
        self._broadcast()
        self._emit(f"{self._prefix}started", {"task": task.id, "title": task.title})
        try:
            with task_context(profile, check_cancel=self.check_cancel, log=self.log):
                result = target(*args)
            self._set(task, "done", result=result, pct=100.0, status_text="Hoàn tất")
            self._emit(f"{self._prefix}done", {"task": task.id, "result": result})
        except Cancelled:
            self.log("Đã dừng theo yêu cầu", "warn")
            self._set(task, "cancelled", status_text="Đã dừng")
            self._emit(f"{self._prefix}cancelled", {"task": task.id})
        except Exception as exc:  # báo mọi lỗi lên UI thay vì làm chết thread
            log.exception("Tác vụ %s lỗi", task.id)
            self.log(f"Lỗi: {exc}", "error")
            self._set(task, "error", error=str(exc), status_text="Lỗi")
            self._emit(f"{self._prefix}error", {"task": task.id, "message": str(exc)})
        finally:
            self._local.task = None
