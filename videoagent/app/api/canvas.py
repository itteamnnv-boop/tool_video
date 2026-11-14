"""API · Canvas (canvas_*): bảng node ảnh / video kiểu Kling Canvas — tạo, nối, sửa, phóng to, tải về."""
import shutil
from pathlib import Path

import webview

from ..osutil import open_path
from ..config import settings

from .common import _fail, _ok


class _FlowCanvasView:
    """Api nhìn qua màn Grok Canvas: mọi thuộc tính lấy từ Api, riêng _canvas là runner Flow, trợ lý riêng và
    sự kiện fcanvas_* — dùng lại nguyên các hàm canvas_* (không đổi trạng thái chung, an toàn khi nhiều luồng gọi)."""

    def __init__(self, api) -> None:
        self._api = api
        self._canvas = api._fcanvas
        self._canvas_assist = api._fcanvas_assist()
        self._emit = api._fcanvas.emit  # canvas_* → fcanvas_*

    def __getattr__(self, name):
        return getattr(self._api, name)

    def _assist(self):
        """🤖 Trợ lý của màn Grok Canvas (trước đây __getattr__ trả nhầm trợ lý của Canvas thường → "Không tìm thấy bảng")."""
        return self._canvas_assist


class CanvasApi:
    def _fcanvas_assist(self):
        if not hasattr(self, "_fcanvas_assist_obj"):
            from ..canvas_assistant import CanvasAssistant

            self._fcanvas_assist_obj = CanvasAssistant(self._fcanvas, settings, emit=self._fcanvas.emit)
        return self._fcanvas_assist_obj

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
        return _ok(meta=self._canvas.meta())  # màn Grok Canvas: kèm model định sẵn, khối không có ô chọn model

    # ---- 🎥 màn Grok Canvas: model định sẵn (Cài đặt của màn) — chữ, ảnh, video, trợ lý điều phối
    def fcanvas_models_get(self) -> dict:
        from .. import api_mode, browser_profiles
        from ..canvas import SCREEN_OFF_VIDEO, flow_models
        from ..content_writer import models as text_models
        from ..llm.image_engines import ENGINES as IMAGE_ENGINES
        from ..llm.video_engines import ENGINES as VIDEO_ENGINES

        texts = [{"value": m["id"], "label": m["name"], "site": m.get("site", "")} for m in text_models(settings)]
        site = lambda v: v.removesuffix("_browser") if v.endswith("_browser") else ""  # noqa: E731
        return _ok(models=flow_models(settings), options={
            "text": texts, "assist": texts,
            "image": [{"value": k, "label": v["name"], "site": site(k)}
                      for k, v in api_mode.engines(IMAGE_ENGINES, settings).items()],
            "video": [{"value": k, "label": v["name"], "site": site(k)}
                      for k, v in api_mode.engines(VIDEO_ENGINES, settings).items() if k not in SCREEN_OFF_VIDEO]},
            profiles=[{"id": p["id"], "name": p["name"], "sites": p.get("sites", [])}
                      for p in browser_profiles.list_profiles()])

    def fcanvas_models_save(self, values: dict) -> dict:
        """Lưu model định sẵn của màn Grok Canvas (= đổi cách chạy quy trình → cần mở khoá như sửa Canvas)."""
        locked = self._canvas_locked()
        if locked:
            return locked
        keys = [f"fcanvas_{a}_{b}" for a in ("model", "profile") for b in ("text", "image", "video", "assist")]
        settings.update({k: str(v or "") for k, v in (values or {}).items() if k in keys})
        return self.fcanvas_models_get()

    # ---- 📋 tác vụ: 1 flow chạy nhiều tác vụ (mỗi tác vụ 1 bảng chạy riêng, đầu vào riêng, hàng đợi)
    def canvas_tasks(self, bid: str = "") -> dict:
        return self._cv("result", self._canvas.tasks, str(bid or ""))

    def canvas_task_create(self, bid: str, items: list) -> dict:
        """Tạo tác vụ cho flow (mỗi item {"name", "inputs"}) — chạy quy trình, không sửa flow → không cần mở khoá."""
        return self._cv("created", self._canvas.create_tasks, bid, items or [])

    def canvas_task_cancel(self, tid: str) -> dict:
        return self._cv("done", lambda: self._canvas.task_cancel(tid) or True)

    def canvas_task_resume(self, tid: str) -> dict:
        return self._cv("done", lambda: self._canvas.task_resume(tid) or True)

    def canvas_task_delete(self, tid: str) -> dict:
        return self._cv("done", lambda: self._canvas.task_delete(tid) or True)

    def canvas_task_clear(self, statuses: list) -> dict:
        return self._cv("removed", self._canvas.task_clear, list(statuses or []))

    def canvas_task_cancel_all(self) -> dict:
        return self._cv("cancelled", self._canvas.task_cancel_all)

    def canvas_task_parallel(self, n=None) -> dict:
        """Số tác vụ chạy cùng lúc: n = None → đọc; có số → lưu (1–6)."""
        return self._cv("parallel", lambda: self._canvas.task_parallel() if n is None else self._canvas.set_task_parallel(n))

    # ---- 🎞 mẫu video (Grok Canvas): mẫu có sẵn + mẫu người dùng (dùng chung mọi bảng)
    def canvas_video_templates(self) -> dict:
        from .. import video_templates as vt

        return _ok(templates=vt.list_templates(), continuity=vt.CONTINUITY, materials=vt.MATERIALS,
                   max_segments=vt.MAX_SEGMENTS)

    def canvas_video_template_save(self, tpl: dict) -> dict:
        """Lưu mẫu (mới / sửa / nhân bản) — đổi cách khối Video chạy → cần mở khoá như sửa Canvas."""
        from .. import video_templates as vt

        locked = self._canvas_locked()
        if locked:
            return locked
        if not isinstance(tpl, dict) or not str(tpl.get("name") or "").strip():
            return {"ok": False, "error": "Nhập tên mẫu"}
        saved = vt.save(tpl)
        return _ok(template=saved, templates=vt.list_templates())

    def canvas_video_template_delete(self, tid: str) -> dict:
        """Xoá mẫu của bạn / bỏ bản sửa của mẫu có sẵn (mẫu có sẵn về mặc định)."""
        from .. import video_templates as vt

        locked = self._canvas_locked()
        if locked:
            return locked
        if not vt.delete(str(tid or "")):
            return {"ok": False, "error": "Mẫu có sẵn không xoá được (chỉ bỏ được bản bạn đã sửa)"}
        return _ok(templates=vt.list_templates())

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
    def canvas_preview(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False,
                       skip: list | None = None) -> dict:
        """Bảng xem trước lượt chạy: khối nào chạy (vì sao), dùng lại, khoá, bỏ chọn; tốn lượt model gì; lỗi cần sửa."""
        return self._cv("plan", lambda: self._canvas.preview(bid, mode, target, bool(fresh), list(skip or [])))

    def canvas_run_flow(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False,
                        skip: list | None = None) -> dict:
        return self._cv("board", lambda: self._canvas.run_flow(bid, mode, target, bool(fresh), skip=list(skip or [])))

    # ---- 🔒 khoá kết quả / 🕘 phiên bản / ↶ hoàn tác / 📜 nhật ký
    def canvas_lock(self, bid: str, nid: str, on: bool = True) -> dict:
        """Khoá = đổi cách chạy quy trình (không tạo lại khối này) → cần mở khoá như mọi thao tác sửa."""
        return self._cv_edit("result", self._canvas.set_lock, bid, nid, bool(on))

    def canvas_restore_version(self, bid: str, nid: str, idx: int) -> dict:
        """Chọn lại 1 phiên bản kết quả cũ (như chọn 1 trong các ảnh đã tạo) — không cần mở khoá."""
        return self._cv("result", self._canvas.restore_version, bid, nid, int(idx))

    def canvas_undo(self, bid: str) -> dict:
        return self._cv_edit("result", self._canvas.undo, bid)

    def canvas_redo(self, bid: str) -> dict:
        return self._cv_edit("result", self._canvas.redo, bid)

    def canvas_log(self, bid: str, kind: str, ref: str) -> dict:
        return self._cv("entries", self._canvas.log_entries, bid, kind, ref)

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

    def canvas_approve(self, bid: str, nid: str, approved: bool, caption: str | None = None, page_id: str = "") -> dict:
        """Duyệt / từ chối node Đăng bài đang chờ (bấm trên Canvas) — app không tự đăng khi chưa duyệt.
        page_id: khối chưa chọn Fanpage → chọn lúc duyệt."""
        return self._cv("result", self._canvas.approve, bid, nid, approved, caption, page_id)

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

    def canvas_analyze_dialogue(self, bid: str, nid: str) -> dict:
        """🎧 Khối Hậu kỳ: phân tích lời thoại từ video đầu vào → điền ô Lời đọc / phụ đề (nghe bằng Gemini API: vài giây
        mỗi video). Như sửa ô của khối khi chạy → không cần mở khoá."""
        return self._cv("result", self._canvas.analyze_dialogue, bid, nid)

    def canvas_update_nodes(self, bid: str, changes: list) -> dict:
        return self._cv("board", self._canvas.update_nodes, bid, changes)

    def canvas_connect(self, bid: str, src: str, dst: str, on: bool = True) -> dict:
        return self._cv_edit("board", self._canvas.connect, bid, src, dst, on)

    def canvas_delete_node(self, bid: str, nid: str) -> dict:
        return self._cv_edit("board", self._canvas.delete_node, bid, nid)

    def canvas_reorder_inputs(self, bid: str, nid: str, ids: list) -> dict:
        """Đổi thứ tự dây nối vào 1 khối (thứ tự gửi model / ghép) = sửa quy trình → cần mở khoá."""
        return self._cv_edit("board", self._canvas.reorder_inputs, bid, nid, list(ids or []))

    # ---- nhóm / ghi chú (kiểu sticky note n8n)
    def canvas_add_group(self, bid: str, data: dict | None = None) -> dict:
        return self._cv_edit("result", self._canvas.add_group, bid, data or {})

    def canvas_update_group(self, bid: str, gid: str, patch: dict | None = None, moves: list | None = None) -> dict:
        return self._cv_edit("board", self._canvas.update_group, bid, gid, patch or {}, moves or [])

    def canvas_delete_group(self, bid: str, gid: str) -> dict:
        return self._cv_edit("board", self._canvas.delete_group, bid, gid)

    def canvas_duplicate(self, bid: str, nid: str) -> dict:
        return self._cv_edit("result", self._canvas.duplicate, bid, nid)

    def canvas_convert(self, bid: str, nid: str, kind: str, wtype: str = "") -> dict:
        """🔁 Đổi loại khối tại chỗ (giữ mã, vị trí, tên, chữ, dây nối hợp kiểu) — hoàn tác được."""
        return self._cv_edit("result", self._canvas.convert, bid, nid, kind, wtype)

    # ---- nhiều node đang quét chọn
    def canvas_auto_split(self, bid: str, nid: str) -> dict:
        """✂ Lời thoại dài → tự tách + ghép ngay (không cần bấm Tách); lời vừa clip → result.split = False.
        Tự động như khi chạy → không cần mở khoá quản trị."""
        return self._cv("result", self._canvas.auto_split, bid, nid)

    def canvas_heygen_lists(self, refresh: bool = False) -> dict:
        """🧑‍💼 Avatar + giọng HeyGen cho ô chọn của khối Video HeyGen (tải lại = gọi HeyGen API, không tốn credit).
        Trả lại ô cấu hình đã điền danh sách — không bao giờ trả khoá API."""
        from ..canvas import heygen_fields
        from ..llm import heygen_api
        from ..workflow import nodes as wfn

        try:
            if refresh:
                heygen_api.refresh(self._canvas.settings.get("heygen_api_key"))
            data = heygen_api.cached()
            return _ok(fields=heygen_fields(wfn.NODE_TYPES["heygen_video"]["fields"]),
                       avatars=len(data.get("avatars") or []), voices=len(data.get("voices") or []))
        except Exception as exc:  # mạng / khoá sai → báo rõ, ô chọn giữ danh sách cũ
            return _fail(exc)

    def canvas_add_ref(self, bid: str, nid: str, role: str = "") -> dict:
        """📎 Chọn ảnh trên máy → ảnh tham chiếu đính kèm ngay trong khối Ảnh (nhân vật / sản phẩm / bối cảnh / phong cách)."""
        locked = self._canvas_locked()
        if locked:
            return locked
        paths = self.pick_files("images_multi")
        if not paths:
            return _ok(result=None)
        return self._cv("result", self._canvas.add_refs, bid, nid, paths, role or "")

    def canvas_qc(self, bid: str, nid: str, decision: str, notes: str = "", checks: list | None = None,
                  by: str = "") -> dict:
        """✅ Kiểm duyệt clip / bản cuối (🎬 Product Video Studio): approved / rejected (kèm lý do) / reset."""
        return self._cv("board", self._canvas.qc, bid, nid, decision, notes or "", checks or [], by or "")

    def canvas_split_video(self, bid: str, nid: str) -> dict:
        """✂ Lời thoại dài → nhiều node Video (tách ở cuối câu, nối sẵn vào khối phía sau)."""
        return self._cv_edit("result", self._canvas.split_video, bid, nid)

    def canvas_duplicate_nodes(self, bid: str, ids: list) -> dict:
        return self._cv_edit("result", self._canvas.duplicate_nodes, bid, list(ids or []))

    def canvas_delete_nodes(self, bid: str, ids: list) -> dict:
        return self._cv_edit("board", self._canvas.delete_nodes, bid, list(ids or []))

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

    def canvas_assist_pick_files(self) -> dict:
        """Chọn ảnh / tài liệu đính kèm cho tin nhắn gửi trợ lý."""
        return _ok(files=[{"path": p, "name": Path(p).name} for p in self.pick_files("assist")])

    def canvas_assist_send(self, bid: str, message: str, attach: bool = True, show_browser: bool = False,
                           build: bool = False, files: list | None = None, mcp: bool | None = None,
                           mcp_note: str | None = None) -> dict:
        """1 lượt hỏi Claude (30 giây – vài phút). Trạng thái đẩy lên qua sự kiện canvas_assist.
        build = 🧩 Dựng: Claude dựng thật lên Canvas (= sửa quy trình → cần mở khoá như mọi thao tác sửa).
        mcp = 🔌 Claude CHỈ ĐỌC dữ liệu qua connector MCP của claude.ai (nhớ lựa chọn + ghi chú nguồn vào Cài đặt)."""
        def status(m, level="info", *a, **k):
            self._emit("canvas_assist", {"board": bid, "text": str(m), "level": level})

        if build:
            locked = self._canvas_locked()
            if locked:
                return locked
        if mcp is not None or mcp_note is not None:
            settings.update({k: v for k, v in (("assist_mcp", None if mcp is None else bool(mcp)),
                                               ("assist_mcp_note", None if mcp_note is None else str(mcp_note)[:400]))
                             if v is not None})
        return self._assist_call("chat", self._assist().chat, bid, message, attach=bool(attach),
                                 show_browser=bool(show_browser), log=status, build=bool(build),
                                 files=[str(f) for f in files or []], mcp=bool(settings.get("assist_mcp")),
                                 mcp_note=str(settings.get("assist_mcp_note") or ""))

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


# ---------------------------------------------------------------------- 🎥 màn Grok Canvas (fcanvas_*)
# Mỗi hàm canvas_* có bản fcanvas_* chạy qua runner Flow (bảng riêng, model định sẵn, sự kiện fcanvas_*).
def _flow_method(name: str):
    def method(self, *args, **kwargs):
        return getattr(CanvasApi, name)(_FlowCanvasView(self), *args, **kwargs)

    method.__name__ = f"f{name}"
    method.__doc__ = f"Grok Canvas — như {name} (bảng riêng, model định sẵn ở Cài đặt của màn)."
    return method


for _name in [n for n in vars(CanvasApi) if n.startswith("canvas_")]:
    setattr(CanvasApi, f"f{_name}", _flow_method(_name))
