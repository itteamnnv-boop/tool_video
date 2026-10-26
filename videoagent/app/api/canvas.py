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

    def canvas_meta(self) -> dict:
        from ..canvas import meta

        return _ok(meta=meta(settings))

    def canvas_list(self) -> dict:
        return self._cv("boards", self._canvas.list)

    def canvas_create(self, name: str = "") -> dict:
        return self._cv("board", self._canvas.create, name)

    def canvas_open(self, bid: str) -> dict:
        return self._cv("board", self._canvas.open, bid)

    def canvas_rename(self, bid: str, name: str) -> dict:
        return self._cv("board", self._canvas.rename, bid, name)

    def canvas_delete(self, bid: str) -> dict:
        return self._cv("deleted", lambda: self._canvas.delete(bid) or True)

    def canvas_add_node(self, bid: str, kind: str, x: float = 0, y: float = 0, inputs: list | None = None,
                        prompt: str = "", wtype: str = "") -> dict:
        return self._cv("result", self._canvas.add_node, bid, kind, x, y, inputs or [], prompt, wtype)

    def canvas_approve(self, bid: str, nid: str, approved: bool, caption: str | None = None) -> dict:
        """Duyệt / từ chối node Đăng bài đang chờ (bấm trên Canvas) — app không tự đăng khi chưa duyệt."""
        return self._cv("result", self._canvas.approve, bid, nid, approved, caption)

    def canvas_pick_files(self, kind: str) -> dict:
        """Chọn file cho ô cấu hình block (video, phụ đề .srt, âm thanh)."""
        return _ok(files=self.pick_files(kind))

    def canvas_upload(self, bid: str, x: float = 0, y: float = 0) -> dict:
        """Chọn ảnh trên máy → node Tải lên (mỗi ảnh 1 node, xếp dọc)."""
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

    def canvas_update_nodes(self, bid: str, changes: list) -> dict:
        return self._cv("board", self._canvas.update_nodes, bid, changes)

    def canvas_connect(self, bid: str, src: str, dst: str, on: bool = True) -> dict:
        return self._cv("board", self._canvas.connect, bid, src, dst, on)

    def canvas_delete_node(self, bid: str, nid: str) -> dict:
        return self._cv("board", self._canvas.delete_node, bid, nid)

    def canvas_duplicate(self, bid: str, nid: str) -> dict:
        return self._cv("result", self._canvas.duplicate, bid, nid)

    def canvas_generate(self, bid: str, nid: str) -> dict:
        return self._cv("board", self._canvas.generate, bid, nid)

    def canvas_cancel(self, bid: str, nid: str) -> dict:
        return self._cv("cancelled", lambda: self._canvas.cancel(bid, nid) or True)

    def canvas_upscale(self, bid: str, nid: str) -> dict:
        return self._cv("result", self._canvas.upscale, bid, nid)

    def canvas_enhance(self, bid: str, nid: str, model: str = "") -> dict:
        return self._cv("task", self._canvas.enhance, bid, nid, model)

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
