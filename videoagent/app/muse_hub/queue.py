"""Studio Muse AI · hàng đợi task: thêm, huỷ / chạy lại, dừng, vòng điều phối, chạy 1 task trên Muse."""
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import browser_profiles

from . import common as _c
from .common import HubError, QUOTA_HINT, RATIOS, VIDEO_SECONDS, _uid, compose_images, now_ms, plan


class QueueMixin:
    # ------------------------------------------------------------ task
    def add_tasks(self, form: dict) -> dict:
        kind = "video" if form.get("kind") == "video" else "image"
        prompts = [str(p).strip() for p in (form.get("prompts") or []) if str(p).strip()]
        if not prompts:
            raise HubError("Nhập ít nhất 1 prompt (mỗi khối cách nhau 1 dòng trống = 1 task)")
        ratio = form.get("ratio") if form.get("ratio") in RATIOS else ""
        try:  # độ dài video Muse tạo (giây) — chọn ở tab Studio
            seconds = int(form.get("duration") or 10)
        except (TypeError, ValueError):
            seconds = 10
        seconds = seconds if seconds in VIDEO_SECONDS else 10
        images = [str(p) for p in (form.get("images") or []) if Path(str(p)).is_file()]
        pairing = form.get("pairing") == "pair"  # ghép cặp: ảnh thứ i cho prompt thứ i; dùng chung: mọi prompt cùng ảnh
        project = form.get("project") or self.hub["current"]
        created = []
        from .. import muse_script as ms

        with self._lock:
            mine = [g for g in self.groups if (g.get("project") or "default") == project]
            batch = max((int(g.get("batch") or 0) for g in mine), default=0) + 1
            no = max((int(g.get("no") or 0) for g in mine), default=0)
            for i, prompt in enumerate(prompts[:200]):
                own = ([images[i]] if i < len(images) else []) if pairing else images
                refs, notes = compose_images(prompt, self.hub, own, self._take_rotate)
                base = {"project": project, "kind": kind, "ratio": ratio, "images": refs, "notes": notes,
                        "status": "queued", "account": "", "attempts": 0, "started_at": 0, "finished_at": 0,
                        "files": [], "error": "", "log": []}
                if kind == "video" and seconds > ms.MUSE_CLIP_MAX:
                    # Muse làm mỗi clip tối đa ~10 giây → chia đoạn ≤ 10s (mỗi đoạn 1 lệnh), xong app tự ghép đúng độ dài
                    no += 1
                    title = next((x.strip() for x in prompt.splitlines() if x.strip()), "Video")
                    title = ms.HEADER_RE.sub("", title).strip() or title
                    g = {"id": _uid("g"), "project": project, "mode": "split", "ratio": ratio, "status": "running",
                         "created_at": now_ms() + i, "outputs": [], "bgm": False, "versions": 1, "version": 1,
                         "batch": batch, "no": no, "title": title[:70], "method": "direct", "duration": str(seconds),
                         "merge": True, "scenes": [prompt[:2000]]}
                    self.groups.append(g)
                    parts = ms.split_prompt(prompt, seconds)
                    for k, (sec, part) in enumerate(parts, 1):
                        task = {**base, "id": _uid("tk"), "prompt": part[:6000], "created_at": now_ms() + i * 100 + k,
                                "duration": sec, "role": "scene", "scene": k, "group": g["id"],
                                "notes": [*notes, f"Phần {k}/{len(parts)} của video {seconds}s — xong tự ghép"]}
                        self.tasks.append(task)
                        created.append(task["id"])
                    continue
                task = {**base, "id": _uid("tk"), "prompt": prompt[:6000], "created_at": now_ms() + i}
                if kind == "video":
                    task["duration"] = seconds
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

    def _run(self, task_id: str, acc_id: str) -> None:
        from ..llm.base import LLMError
        from ..llm.muse_browser import muse_images, muse_video
        from ..pipeline import Cancelled

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
