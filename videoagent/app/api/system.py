"""Tiến trình chung của hệ thống (nút ⏳ trên thanh tiêu đề): gom mọi tác vụ đang chạy / đang chờ / vừa xong của các màn
— Tạo video, Tạo ảnh, Studio, Studio Muse, Chiến dịch, Workflow, Nhân vật & Layout, Studio Muse AI (hàng đợi Muse, video
kịch bản, hậu kỳ), Seedance. Chỉ đọc trạng thái trong bộ nhớ (không đọc đĩa) để gọi thường xuyên vẫn nhẹ."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from .common import _fail, _ok

RECENT = 12  # số tác vụ đã kết thúc hiển thị ở mục "Gần đây"
RECENT_MS = 6 * 3600 * 1000  # chỉ lấy tác vụ kết thúc trong 6 giờ qua

# trạng thái riêng của từng nguồn → nhóm chung: running | queued | done | failed | cancelled
_POOL = {"queued": "queued", "running": "running", "done": "done", "error": "failed", "cancelled": "cancelled"}
_HUB = {"queued": "queued", "waiting": "queued", "review": "queued", "processing": "running",
        "succeeded": "done", "failed": "failed", "cancelled": "cancelled"}
_HUB_TEXT = {"waiting": "Chờ storyboard", "review": "Chờ duyệt storyboard", "queued": "Chờ tài khoản Muse rảnh"}
_GROUP = {"running": "running", "finishing": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}
_POST = {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}


def _ms(value) -> int:
    """created_at của TaskPool là chuỗi ISO, của Muse là mili-giây → đổi hết về mili-giây."""
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except ValueError:
        return 0


VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_RESULTS = 4


def _kind(name: str) -> str:
    ext = Path(str(name).split("?")[0]).suffix.lower()
    return "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else ""


def _pool_results(result) -> list:
    """Kết quả TaskPool (dict tuỳ màn) → [{kind, url}]: final_url (video), files[].url (ảnh), url / video_url."""
    if not isinstance(result, dict):
        return []
    out = []
    if result.get("final_url") and result.get("has_final", True):
        out.append({"kind": "video", "url": result["final_url"]})
    for key in ("video_url", "url"):
        if isinstance(result.get(key), str) and _kind(result[key]):
            out.append({"kind": _kind(result[key]), "url": result[key]})
    for f in result.get("files") or []:
        url = f.get("url") if isinstance(f, dict) else ""
        if url and _kind(url):
            out.append({"kind": _kind(url), "url": url})
    return out[:MAX_RESULTS]


def _first_line(text, n: int = 90) -> str:
    line = next((x.strip() for x in str(text or "").splitlines() if x.strip()), "")
    return line if len(line) <= n else line[: n - 1] + "…"


class SystemApi:
    def _file_results(self, paths) -> list:
        """File trong thư mục lưu → [{kind, url, path}] (URL /media/ của server nội bộ)."""
        base, out = Path(self._settings_output()), []
        for f in paths or []:
            p = Path(f)
            if not _kind(p.name) or not p.is_file():
                continue
            try:
                url = f"/media/{p.relative_to(base).as_posix()}?v={int(p.stat().st_mtime)}"
            except ValueError:
                continue
            out.append({"kind": _kind(p.name), "url": url, "path": str(p)})
        return out[:MAX_RESULTS]

    def _settings_output(self) -> str:
        from ..config import settings
        return settings.output_dir

    def _results(self, item: dict) -> None:
        """Gắn kết quả + cách mở thư mục cho tác vụ đã xong (chỉ gọi cho ≤ RECENT mục — có đọc đĩa)."""
        src, raw = item["source"], item.pop("_raw", None)
        if src in ("mhub", "mgroup"):
            res = self._file_results(raw)
            item["results"] = res
            if res:
                item["folder"] = {"api": "mhub_open", "args": [res[0]["path"]]}
        elif src == "post":
            item["results"] = []
        elif src == "mpost":
            res = self._file_results([raw] if raw else [])
            item["results"] = res
            if res:
                item["folder"] = {"api": "open_video_folder", "args": [Path(res[0]["path"]).parent.name]}
        else:
            item["results"] = _pool_results(raw)
            rid = raw.get("id") if isinstance(raw, dict) else ""
            if rid and src == "video":
                item["folder"] = {"api": "open_video_folder", "args": [rid]}
            elif rid and src == "image":
                item["folder"] = {"api": "open_images_folder", "args": [rid]}
        for r in item["results"]:
            r.pop("path", None)

    def _pools(self) -> list:
        """(mã nguồn, tên hiển thị, màn mở khi bấm, TaskPool)."""
        return [("video", "Tạo video", "create", self._runner.pool),
                ("image", "Tạo hình ảnh", "images", self._images.pool),
                ("studio", "Studio", "studio", self._studio.pool),
                ("mstudio", "Studio Muse", "mstudio", self._studio_muse.pool),
                ("campaign", "Chiến dịch", "camp-list", self._campaigns.pool),
                ("workflow", "Workflow", "workflow", self._workflows.pool),
                ("cast", "Nhân vật & Layout", "cast", self._cast.pool)]

    def system_progress(self) -> dict:
        items = []
        for src, label, view, pool in self._pools():
            for t in pool.list():
                items.append({"source": src, "label": label, "view": view, "id": t["id"], "title": t.get("title") or "",
                              "status": _POOL.get(t.get("status"), "running"), "pct": float(t.get("pct") or 0),
                              "text": t.get("error") or t.get("status_text") or "", "created": _ms(t.get("created_at")),
                              "started": 0, "cancel": True, "_raw": t.get("result")})
        hub = self._muse_hub
        with hub._lock:  # hàng đợi Muse: task video / ảnh (task của video kịch bản cũng nằm ở đây)
            tasks = [dict(t) for t in hub.tasks]
            groups = [dict(g) for g in hub.groups]
        for t in tasks:
            status = _HUB.get(t.get("status"), "queued")
            log = t.get("log") or []
            text = t.get("error") or (log[-1][9:] if status == "running" and log else _HUB_TEXT.get(t.get("status"), ""))
            items.append({"source": "mhub", "label": "Studio Muse AI", "view": "mstudio", "tab": "progress", "id": t["id"],
                          "title": f"{'🎬' if t.get('kind') == 'video' else '🖼'} {_first_line(t.get('prompt'))}",
                          "status": status, "pct": 0, "text": text, "created": _ms(t.get("created_at")),
                          "started": int(t.get("started_at") or 0), "finished": int(t.get("finished_at") or 0),
                          "cancel": status in ("queued", "running"), "grouped": bool(t.get("group")),
                          "_raw": t.get("files") or []})
        for g in groups:  # video từ Kịch bản / LadiPage / Video mẫu — gom nhiều task + ghép
            status = _GROUP.get(g.get("status"), "running")
            items.append({"source": "mgroup", "label": "Muse · Kịch bản", "view": "mstudio", "tab": "script", "id": g["id"],
                          "title": f"🎞 {_first_line(g.get('title'))}", "status": status, "pct": 0,
                          "text": g.get("error") or ("Đang ghép các đoạn…" if g.get("status") == "finishing" else ""),
                          "created": _ms(g.get("created_at")), "started": 0, "finished": int(g.get("finished_at") or 0),
                          "cancel": False, "_raw": g.get("outputs") or []})
        for j in list(self._muse_post.jobs.values()):  # tab Hậu kỳ
            status = _POST.get(j.get("status"), "running")
            items.append({"source": "mpost", "label": "Muse · Hậu kỳ", "view": "mstudio", "tab": "post", "id": j["id"],
                          "title": f"✂ {j.get('name') or 'Hậu kỳ'}", "status": status, "pct": float(j.get("pct") or 0),
                          "text": j.get("error") or j.get("stage") or "", "created": _ms(j.get("created_at")),
                          "started": 0, "cancel": status in ("queued", "running"), "_raw": j.get("path") or ""})
        if self._seedance.running:  # Seedance chạy theo lô — 1 dòng tổng
            items.append({"source": "seedance", "label": "Seedance", "view": "seedance", "id": "seedance",
                          "title": "Seedance — đang gửi / tải video", "status": "running", "pct": 0,
                          "text": f"{len(self._seedance.workers)} luồng đang chạy", "created": 0, "started": 0,
                          "cancel": False})

        items += self._post_items()
        now = int(time.time() * 1000)
        active = [i for i in items if i["status"] in ("running", "queued")]
        active.sort(key=lambda i: (i["status"] != "running", i["created"]))
        ended = [i for i in items if i["status"] not in ("running", "queued")
                 and now - (i.get("finished") or i["created"] or now) < RECENT_MS]
        ended.sort(key=lambda i: -(i.get("finished") or i["created"]))
        ended = ended[:RECENT]
        for i in ended:
            if i["status"] == "done":
                self._results(i)
        for i in items:
            i.pop("_raw", None)
        return _ok(running=sum(i["status"] == "running" for i in active), queued=sum(i["status"] == "queued" for i in active),
                   active=active, recent=ended, now=now)

    def _post_items(self) -> list:
        """Bài lên lịch (app tự đăng): đang chờ giờ → queued; vừa đăng theo lịch / lỗi / lỡ lịch → mục gần đây."""
        out = []
        with self._posts._lock:
            posts = self._posts._load()
        for p in posts:
            sch, auto = p.get("schedule"), p.get("auto")
            base = {"source": "post", "label": "Bài đăng · lịch", "view": "posts", "id": p["id"],
                    "title": f"📣 {p.get('title') or 'Bài đăng'}", "pct": 0, "started": 0}
            if sch and p.get("status") == "queued":
                when = datetime.fromtimestamp(sch["at"]).strftime("%H:%M %d/%m")
                out.append({**base, "status": "running" if sch.get("running") else "queued",
                            "text": f"Đăng lúc {when} → {', '.join(sch.get('pages') or [])}",
                            "created": int(sch["at"]) * 1000, "cancel": not sch.get("running")})
            elif auto:
                out.append({**base, "status": "done" if auto.get("ok") else "failed", "created": auto["at"],
                            "finished": auto["at"], "url": auto.get("url", ""), "cancel": False,
                            "text": auto.get("error") or f"{auto.get('how', 'Đã đăng theo lịch')}"})
        return out

    def system_cancel(self, source: str, item_id: str) -> dict:
        """Dừng 1 tác vụ từ bảng tiến trình chung."""
        if not str(item_id or "").strip():
            return _fail("Thiếu mã tác vụ")  # pool.cancel("") = huỷ TẤT CẢ — không cho đi đường này
        pools = {src: pool for src, _, _, pool in self._pools()}
        if source in pools:
            return _ok(cancelled=pools[source].cancel(str(item_id)))
        if source == "mhub":
            self._muse_hub.task_action([str(item_id)], "cancel")
            return _ok(cancelled=1)
        if source == "mpost":
            self._muse_post.cancel(str(item_id))
            return _ok(cancelled=1)
        if source == "post":  # bài lên lịch → huỷ lịch (bài về Nháp, vẫn giữ trong Quản lý bài đăng)
            from ..posts import PostError

            try:
                self._posts.unschedule(str(item_id))
            except PostError as exc:
                return _fail(exc)
            return _ok(cancelled=1)
        return _fail("Tác vụ này không dừng được từ đây — mở màn của nó để dừng")
