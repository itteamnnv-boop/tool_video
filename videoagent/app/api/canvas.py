"""API · Canvas (canvas_*): bảng node ảnh / video kiểu Kling Canvas — tạo, nối, sửa, phóng to, tải về."""
import shutil
from pathlib import Path

import webview

from ..osutil import open_path
from ..config import settings

from .common import _fail, _ok


class CanvasApi:
    def _cv(self, key: str, fn, *args) -> dict:
        from ..canvas import CanvasError

        try:
            return _ok(**{key: fn(*args)})
        except (CanvasError, ValueError, OSError) as exc:
            return _fail(exc)

    def _cv_edit(self, key: str, fn, *args) -> dict:
        """Thao tác SỬA quy trình (thêm / xoá / nối node, nhóm, đổi tên, nhân bản…) cần mở khoá bằng mật khẩu quản trị
        như Cài đặt. Chạy quy trình + hộp hỏi khi chạy (update_nodes, chọn file đầu vào) không cần."""
        return self._canvas_locked() or self._cv(key, fn, *args)

    def _canvas_locked(self) -> dict | None:
        lock = self._admin_lock()
        if lock.has_password() and not lock.unlocked():
            return {"ok": False, "locked": True, "error": "Quy trình Canvas đang khoá — nhập mật khẩu quản trị để chỉnh sửa"}
        lock.touch()
        return None

    def canvas_meta(self) -> dict:
        from ..canvas import meta

        return _ok(meta=meta(settings))

    def canvas_list(self) -> dict:
        return self._cv("boards", self._canvas.list)

    def canvas_create(self, name: str = "") -> dict:
        return self._cv_edit("board", self._canvas.create, name)

    def canvas_open(self, bid: str) -> dict:
        return self._cv("board", self._canvas.open, bid)

    def canvas_rename(self, bid: str, name: str) -> dict:
        return self._cv_edit("board", self._canvas.rename, bid, name)

    def canvas_duplicate_board(self, bid: str) -> dict:
        return self._cv_edit("board", self._canvas.duplicate_board, bid)

    def canvas_delete(self, bid: str) -> dict:
        return self._cv_edit("deleted", lambda: self._canvas.delete(bid) or True)

    def canvas_add_node(self, bid: str, kind: str, x: float = 0, y: float = 0, inputs: list | None = None,
                        prompt: str = "", wtype: str = "") -> dict:
        return self._cv_edit("result", self._canvas.add_node, bid, kind, x, y, inputs or [], prompt, wtype)

    # ---- chạy cả quy trình (như Workflow)
    def canvas_preview(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False) -> dict:
        """Kế hoạch chạy + lỗi cần sửa trước khi chạy (node nào chạy thật, node nào dùng lại kết quả)."""
        return self._cv("plan", self._canvas.preview, bid, mode, target, bool(fresh))

    def canvas_run_flow(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False) -> dict:
        return self._cv("board", self._canvas.run_flow, bid, mode, target, bool(fresh))

    def canvas_cancel_flow(self, bid: str) -> dict:
        return self._cv("cancelled", self._canvas.cancel_flow, bid)

    def canvas_sources(self) -> dict:
        """Workflow đã lưu + quy trình mẫu để nhập thành Canvas."""
        return self._cv("sources", self._canvas.sources)

    def canvas_import(self, source: str, ref: str) -> dict:
        return self._cv_edit("result", self._canvas.import_workflow, source, ref)

    def canvas_open_result(self, bid: str, nid: str) -> dict:
        """Mở thư mục khối Kết quả đã gom."""
        def run():
            folder = (self._canvas._node(self._canvas.load(bid), nid).get("out") or {}).get("folder")
            if not folder or not Path(folder).is_dir():
                raise ValueError("Chưa có thư mục kết quả — chạy khối này trước")
            open_path(folder)
            return True
        return self._cv("opened", run)

    def canvas_approve(self, bid: str, nid: str, approved: bool, caption: str | None = None) -> dict:
        """Duyệt / từ chối node Đăng bài đang chờ (bấm trên Canvas) — app không tự đăng khi chưa duyệt."""
        return self._cv("result", self._canvas.approve, bid, nid, approved, caption)

    def canvas_pick_files(self, kind: str) -> dict:
        """Chọn file cho ô cấu hình block (video, phụ đề .srt, âm thanh)."""
        return _ok(files=self.pick_files(kind))

    def canvas_upload(self, bid: str, x: float = 0, y: float = 0) -> dict:
        """Chọn ảnh trên máy → node Tải lên (mỗi ảnh 1 node, xếp dọc)."""
        locked = self._canvas_locked()
        if locked:
            return locked
        paths = self.pick_files("images_multi")
        if not paths:
            return _ok(result=None)
        result = None
        for i, path in enumerate(paths[:10]):
            res = self._cv("result", self._canvas.upload, bid, path, x, y + i * 360)
            if not res.get("ok"):
                return res
            result = res["result"]
        return _ok(result=result)

    def canvas_pick_input(self, bid: str, nid: str) -> dict:
        """Chọn file cho đầu vào: Ảnh đầu vào → 1 ảnh; khối Video đầu vào → 1 video (dùng khi hỏi lúc chạy quy trình)."""
        try:
            node = self._canvas._node(self._canvas.load(bid), nid)
        except Exception as exc:  # bảng / node không còn
            return _fail(exc)
        if node.get("wtype") == "input_video":
            paths = self.pick_files("video")
            if not paths:
                return _ok(result=None)
            return self._cv("result", lambda: {"board": self._canvas.update_nodes(
                bid, [{"id": nid, "config": {"files": paths[:1]}}]), "node": nid})
        # chọn ảnh đầu vào lúc chạy = một phần của việc CHẠY → không cần mở khoá (khác nút 🔄 Thay ảnh khi sửa Canvas)
        paths = self.pick_files("image")
        if not paths:
            return _ok(result=None)
        return self._cv("result", self._canvas.replace_image, bid, nid, paths[0])

    def canvas_replace_image(self, bid: str, nid: str) -> dict:
        """Chọn ảnh khác trên máy thay cho ảnh của node (giữ dây nối)."""
        paths = self.pick_files("image")
        if not paths:
            return _ok(result=None)
        return self._cv_edit("result", self._canvas.replace_image, bid, nid, paths[0])

    def canvas_update_nodes(self, bid: str, changes: list) -> dict:
        return self._cv("board", self._canvas.update_nodes, bid, changes)

    def canvas_connect(self, bid: str, src: str, dst: str, on: bool = True) -> dict:
        return self._cv_edit("board", self._canvas.connect, bid, src, dst, on)

    def canvas_delete_node(self, bid: str, nid: str) -> dict:
        return self._cv_edit("board", self._canvas.delete_node, bid, nid)

    # ---- nhóm / ghi chú (kiểu sticky note n8n)
    def canvas_add_group(self, bid: str, data: dict | None = None) -> dict:
        return self._cv_edit("result", self._canvas.add_group, bid, data or {})

    def canvas_update_group(self, bid: str, gid: str, patch: dict | None = None, moves: list | None = None) -> dict:
        return self._cv_edit("board", self._canvas.update_group, bid, gid, patch or {}, moves or [])

    def canvas_delete_group(self, bid: str, gid: str) -> dict:
        return self._cv_edit("board", self._canvas.delete_group, bid, gid)

    def canvas_duplicate(self, bid: str, nid: str) -> dict:
        return self._cv_edit("result", self._canvas.duplicate, bid, nid)

    def canvas_generate(self, bid: str, nid: str) -> dict:
        return self._cv("board", self._canvas.generate, bid, nid)

    def canvas_cancel(self, bid: str, nid: str) -> dict:
        return self._cv("cancelled", lambda: self._canvas.cancel(bid, nid) or True)

    def canvas_upscale(self, bid: str, nid: str) -> dict:
        return self._cv_edit("result", self._canvas.upscale, bid, nid)

    def canvas_enhance(self, bid: str, nid: str, model: str = "") -> dict:
        return self._cv_edit("task", self._canvas.enhance, bid, nid, model)

    def canvas_download(self, bid: str, nid: str) -> dict:
        """Lưu kết quả của node ra nơi người dùng chọn (hộp thoại Lưu)."""
        from ..canvas import CanvasError

        try:
            src = self._canvas.file_of(bid, nid)
        except (CanvasError, OSError) as exc:
            return _fail(exc)
        save_dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        kind = "Video (*.mp4)" if src.suffix == ".mp4" else f"Ảnh (*{src.suffix})"
        result = self._window.create_file_dialog(save_dialog, save_filename=f"canvas-{nid}{src.suffix}",
                                                 file_types=(kind,))
        if not result:
            return _ok(path="")
        dest = Path(result if isinstance(result, str) else result[0])
        if dest.suffix.lower() != src.suffix:
            dest = dest.with_suffix(src.suffix)
        shutil.copy2(src, dest)
        return _ok(path=str(dest))

    def canvas_open_folder(self, bid: str) -> dict:
        return self._cv("opened", lambda: open_path(self._canvas.dir(bid)) or True)

    # ---- ⏰ lập lịch chạy (đặt lịch = sửa quy trình → cần mở khoá)
    def canvas_schedule(self, bid: str, cfg: dict) -> dict:
        from ..canvas_schedule import set_schedule

        return self._cv_edit("board", lambda: set_schedule(self._canvas, bid, cfg or {}))

    # ---- 🤖 Trợ lý Canvas (Claude trình duyệt: điều phối + đánh giá; đề xuất chỉ chạy khi bạn bấm Áp dụng)
    def _assist(self):
        if not hasattr(self, "_canvas_assist"):
            from ..canvas_assistant import CanvasAssistant
            self._canvas_assist = CanvasAssistant(self._canvas, settings, emit=self._emit)
        return self._canvas_assist

    def _assist_call(self, key: str, fn, *args, **kwargs) -> dict:
        try:
            return _ok(**{key: fn(*args, **kwargs)})
        except Exception as exc:  # lỗi đề xuất / trình duyệt / chưa đăng nhập claude.ai → báo rõ, không treo giao diện
            return _fail(exc)

    def canvas_assist_get(self, bid: str) -> dict:
        return self._assist_call("chat", self._assist().load, bid)

    def canvas_assist_send(self, bid: str, message: str, attach: bool = True, show_browser: bool = False) -> dict:
        """1 lượt hỏi Claude (30 giây – vài phút). Trạng thái đẩy lên qua sự kiện canvas_assist."""
        def status(m, level="info", *a, **k):
            self._emit("canvas_assist", {"board": bid, "text": str(m), "level": level})

        return self._assist_call("chat", self._assist().chat, bid, message, attach=bool(attach),
                                 show_browser=bool(show_browser), log=status)

    def canvas_assist_apply(self, bid: str, mid: str, idx: int) -> dict:
        """Áp dụng 1 đề xuất của trợ lý = sửa quy trình → cần mở khoá như mọi thao tác sửa Canvas."""
        return self._canvas_locked() or self._assist_call("result", self._assist().apply, bid, mid, int(idx))

    def canvas_assist_clear(self, bid: str) -> dict:
        return self._assist_call("chat", self._assist().clear, bid)

    def canvas_assist_auto(self, bid: str, cfg: dict) -> dict:
        """Cấu hình tự điều phối (bật / tiêu chí / điểm đạt / số vòng): bật = cho Claude tự chạy lại khối → cần mở khoá."""
        return self._canvas_locked() or self._assist_call("chat", self._assist().set_auto, bid, cfg or {})

    def canvas_assist_stop(self, bid: str) -> dict:
        return self._assist_call("chat", self._assist().stop_auto, bid)
