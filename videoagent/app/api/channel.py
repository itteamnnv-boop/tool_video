"""Trợ lý nuôi kênh (ch_*): khung chat với Claude theo SKILL điều phối — hỏi đủ thông tin, gợi ý, tổng hợp yêu cầu rồi
dựng + chạy trọn quy trình trên 1 bảng Canvas riêng của kênh. Áp dụng đề xuất / duyệt bài / sửa khối / tự điều phối dùng
chung API canvas_* (bid = id kênh). Trạng thái đẩy lên qua sự kiện canvas_assist / canvas_flow / canvas_node."""
from .. import channel_assistant as chn
from .common import _fail, _ok


class ChannelApi:
    def _chn(self, key: str, fn, *args, **kwargs) -> dict:
        try:
            return _ok(**{key: fn(*args, **kwargs)})
        except Exception as exc:  # lỗi dữ liệu / file / trình duyệt / chưa đăng nhập claude.ai → báo rõ trên giao diện
            return _fail(exc)

    def ch_list(self) -> dict:
        return self._chn("channels", chn.list_channels, self._canvas)

    def ch_create(self, name: str = "") -> dict:
        return self._canvas_locked() or self._chn("board", chn.create_channel, self._canvas, name)

    def ch_delete(self, cid: str) -> dict:
        return self.canvas_delete(cid)

    # ---- skill điều phối
    def ch_skill_get(self) -> dict:
        return self._chn("skill", chn.skill_info)

    def ch_skill_save(self, text: str) -> dict:
        return self._canvas_locked() or self._chn("skill", chn.save_skill, text)

    def ch_skill_reset(self) -> dict:
        return self._canvas_locked() or self._chn("skill", chn.reset_skill)

    # ---- khung chat
    def ch_chat(self, cid: str, message: str, attach: bool = True, files: list | None = None, build: bool = False) -> dict:
        """1 lượt hỏi Claude theo skill (30 giây – vài phút). Ảnh / video đính kèm được thêm lên bảng làm node tài nguyên
        (= sửa quy trình → cần mở khoá như mọi thao tác sửa Canvas)."""
        if build or files:
            locked = self._canvas_locked()
            if locked:
                return locked

        def status(m, level="info", *a, **k):
            self._emit("canvas_assist", {"board": cid, "text": str(m), "level": level})

        return self._assist_call("chat", self._assist().chat, cid, message, attach=bool(attach), log=status,
                                 build=bool(build), files=[str(f) for f in files or []], skill=chn.skill_text(),
                                 keep_files=True, extra=chn.BRIEF_FORMAT)

    def ch_meta(self) -> dict:
        return _ok(brief_fields=chn.BRIEF_FIELDS)

    def ch_run(self, cid: str, fresh: bool = False) -> dict:
        """▶ Chạy cả quy trình (như nút Chạy toàn bộ của Canvas — không cần mở khoá). Còn thiếu (VD chưa chọn Fanpage)
        → trả danh sách issues để khung chat hỏi người dùng."""
        try:
            plan, issues = chn.run_check(self._canvas, cid, bool(fresh))
        except Exception as exc:  # bảng không còn
            return _fail(exc)
        if issues:
            return _ok(issues=issues, board=None)
        if not plan["run"]:
            return _fail("Không có khối nào cần chạy — mọi kết quả đã mới nhất (bấm “Chạy lại từ đầu” để tạo lại)")
        res = self.canvas_run_flow(cid, "all", "", bool(fresh))
        return _ok(issues=[], board=res["board"]) if res.get("ok") else res
