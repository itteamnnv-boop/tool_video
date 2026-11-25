"""🎬 Trợ lý TVC (tvc_*): Claude Code chạy skill tvc-livestream-capcut điều khiển mọi bước; app hiển thị + tiếp nhận.
Sự kiện lên giao diện: tvc_chat (tin mới / cập nhật), tvc_chat_state (đang chạy, câu hỏi chờ), tvc_chat_project (dự án Claude
đang làm)."""
import atexit

from .common import _fail, _ok

SETTING_KEYS = ("tvc_root", "tvc_claude_model", "tvc_rubric")


class TvcApi:
    def _tvc(self):
        viewer = getattr(self, "_tvc_viewer", None)
        if viewer is None:
            from ..config import settings
            from ..tvc_assistant import TvcAssistant

            viewer = self._tvc_viewer = TvcAssistant(settings)
        return viewer

    def _tvcc(self):
        agent = getattr(self, "_tvc_agent", None)
        if agent is None:
            from ..config import settings
            from ..tvc_claude import TvcClaude
            from ..tvc_fb import TvcFacebook

            fb = TvcFacebook(getattr(self, "_facebook", None), getattr(self, "_posts", None), self._tvc(),
                             on_change=lambda: self._emit("posts_changed", {}))
            agent = self._tvc_agent = TvcClaude(settings, self._emit, self._tvc(),
                                                fb=fb if getattr(self, "_posts", None) is not None else None,
                                                ads=self._tvc_ads())
            atexit.register(agent.stop)  # tắt app → đóng phiên Claude Code
        return agent

    def _tvc_ads(self):
        """📈 yêu cầu quảng cáo (kế hoạch chờ duyệt ở Trợ lý quảng cáo); bảng dự án đọc trạng thái kế hoạch qua đây."""
        obj = getattr(self, "_tvc_ads_obj", None)
        if obj is None and getattr(self, "_ads", None) is not None:
            from ..tvc_ads import TvcAds

            obj = self._tvc_ads_obj = TvcAds(self._ads, self._adbot_store, getattr(self, "_facebook", None), self._tvc())
            self._tvc().ad_status = obj.plan_status
        return obj

    def tvc_ad_cancel(self, name: str) -> dict:
        """Huỷ yêu cầu quảng cáo của dự án (xoá kế hoạch CHỜ DUYỆT — chưa có gì trên Facebook)."""
        def go():
            ads = self._tvc_ads()
            if ads is None:
                raise ValueError("Chưa có phần quảng cáo")
            out = ads.cancel(str(name or ""))
            self._emit("adbot_changed", {"id": out.get("plan_id", "")})
            return out
        return self._tvc_call("request", go)

    def _tvc_call(self, key: str, fn, *args) -> dict:
        try:
            return _ok(**{key: fn(*args)})
        except Exception as exc:  # lỗi dữ liệu / Claude Code / thư mục → báo rõ trên màn
            return _fail(exc)

    # ---- môi trường + cài đặt
    def tvc_env(self) -> dict:
        """Claude Code CLI + Claude Agent SDK + skill TVC đã cài chưa (không gọi model)."""
        return self._tvc_call("env", self._tvc().env)

    def tvc_settings_get(self) -> dict:
        from ..config import settings

        return _ok(values={k: settings.get(k) or "" for k in SETTING_KEYS}, root=str(self._tvc().root()))

    def tvc_settings_save(self, values: dict) -> dict:
        from ..config import settings

        settings.update({k: str(v or "").strip()[:4000] for k, v in (values or {}).items() if k in SETTING_KEYS})
        return self.tvc_settings_get()

    def tvc_pick_root(self) -> dict:
        import webview

        from ..config import settings

        folder_dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder_dialog, directory=str(self._tvc().root()))
        if result:
            settings.update({"tvc_root": result[0] if isinstance(result, (list, tuple)) else result})
        return self.tvc_settings_get()

    # ---- xem dự án (chỉ đọc)
    def tvc_list(self) -> dict:
        return self._tvc_call("projects", self._tvc().projects)

    def tvc_get(self, name: str) -> dict:
        self._tvc_ads()  # gắn tra trạng thái kế hoạch quảng cáo cho bảng dự án
        return self._tvc_call("project", self._tvc().get, str(name or ""))

    def tvc_open(self, name: str, what: str = "project") -> dict:
        """Mở thư mục dự án / draft CapCut / file xem trước bằng Windows Explorer."""
        from pathlib import Path

        from ..osutil import open_path

        def go():
            info = self._tvc().get(str(name or ""))
            target = {"project": info["path"], "draft": info["draft_dir"]}.get(what, "")
            if what == "facebook" and (Path(info["path"]) / "09_facebook").is_dir():
                target = str(Path(info["path"]) / "09_facebook")
            if what == "preview" and info["state"]["preview"]:
                target = str(Path(info["path"]) / info["state"]["preview"])
            if not target:
                raise ValueError("Chưa có")
            open_path(target)
            return target
        return self._tvc_call("opened", go)

    # ---- chat với Claude Code
    def tvc_chat_state(self) -> dict:
        return self._tvc_call("state", self._tvcc().state)

    def tvc_chats(self) -> dict:
        return self._tvc_call("chats", self._tvcc().chats)

    def tvc_chat_new(self) -> dict:
        return self._tvc_call("state", self._tvcc().new_chat)

    def tvc_chat_open(self, cid: str) -> dict:
        return self._tvc_call("state", self._tvcc().open_chat, str(cid or ""))

    def tvc_chat_delete(self, cid: str) -> dict:
        return self._tvc_call("chats", self._tvcc().delete_chat, str(cid or ""))

    # ---- 🤖 tự động toàn bộ
    def tvc_auto_meta(self) -> dict:
        """Phiếu tự động: bộ tiêu chí đang dùng + Fanpage đã kết nối (id, tên — không token)."""
        def go():
            agent = self._tvcc()
            return {"rubric": agent.rubric(), "pages": agent.fb.pages() if agent.fb is not None else []}
        return self._tvc_call("meta", go)

    def tvc_auto_start(self, inputs: dict, cfg: dict) -> dict:
        """Chạy tự động toàn bộ (đã đủ đầu vào bắt buộc) — Claude tự duyệt các bước, chấm theo bộ tiêu chí."""
        return self._tvc_call("state", self._tvcc().auto_start, inputs or {}, cfg or {})

    def tvc_web_images(self, url: str) -> dict:
        """🌐 Ảnh sản phẩm trên trang (chỉ đọc) để người dùng chọn."""
        return self._tvc_call("web", self._tvc().web_images, str(url or ""))

    def tvc_web_images_save(self, urls: list, kind: str = "san_pham") -> dict:
        """Tải ảnh đã chọn (trong danh sách vừa tìm) về <gốc>/_input/<kind>."""
        return self._tvc_call("files", self._tvc().save_web_images, urls or [], str(kind or "san_pham"))

    def tvc_auto_stop(self) -> dict:
        return self._tvc_call("state", self._tvcc().auto_stop)

    def tvc_chat_hide(self, cid: str, hidden: bool = True) -> dict:
        """Ẩn / hiện 1 hội thoại khỏi dải lịch sử (không xoá)."""
        return self._tvc_call("chats", self._tvcc().set_hidden, str(cid or ""), bool(hidden))

    def tvc_chat_send(self, text: str) -> dict:
        """Gửi tin cho Claude (mở phiên Claude Code nếu chưa có — tốn lượt gói Claude của bạn)."""
        return self._tvc_call("state", self._tvcc().send, str(text or ""))

    def tvc_chat_answer(self, rid: str, data: dict) -> dict:
        """Trả lời câu hỏi lựa chọn / hộp xin quyền của Claude."""
        return self._tvc_call("state", self._tvcc().answer, str(rid or ""), dict(data or {}))

    def tvc_chat_stop(self) -> dict:
        """⏹ Dừng lượt Claude đang làm."""
        return self._tvc_call("stopped", self._tvcc().interrupt)

    def tvc_chat_upload(self, kind: str, paths: list) -> dict:
        """Ảnh bạn gửi → <gốc>/_input/nguoi_mau|san_pham (skill chờ ảnh ở đó)."""
        return self._tvc_call("files", self._tvc().upload_inputs, str(kind or ""), list(paths or []))
