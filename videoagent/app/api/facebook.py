"""API · Fanpage Facebook + quản lý bài đăng."""
from ..posts import POST_TYPES, SCHEDULABLE

from .common import _fail, _ok, log


class FacebookApi:
    # ------------------------------------------------------------------ fanpage Facebook
    def _fb_call(self, fn, *args) -> dict:
        from ..facebook import FacebookError

        try:
            return _ok(fb=fn(*args))
        except FacebookError as exc:
            return _fail(exc)

    def fb_state(self) -> dict:
        return _ok(fb=self._facebook.state())

    def fb_save_app(self, app_id: str, app_secret: str, graph_version: str = "") -> dict:
        return self._fb_call(self._facebook.save_app, app_id, app_secret, graph_version)

    def fb_connect_token(self, token: str) -> dict:
        return self._fb_call(self._facebook.connect_token, token)

    def fb_logout(self) -> dict:
        return self._fb_call(self._facebook.logout)

    def fb_load_pages(self) -> dict:
        return self._fb_call(self._facebook.load_pages)

    def fb_set_connected(self, page_id: str, connected: bool) -> dict:
        return self._fb_call(self._facebook.set_connected, page_id, connected)

    def fb_post(self, page_id: str, message: str, file_path: str = "") -> dict:
        from ..facebook import FacebookError

        try:
            res = self._facebook.post(page_id, message, file_path)
        except (FacebookError, OSError) as exc:
            return _fail(exc)
        try:  # lưu vào Quản lý bài đăng để sửa / đăng lại; lỗi lưu không ảnh hưởng bài đã đăng
            from ..posts import who

            self._posts.record(source="quick", source_name=res.get("page", ""), kind="text" if not file_path else "feed",
                               caption=message, files=[file_path] if file_path else [], page_id=page_id,
                               page=res.get("page", ""), result=res, by=who())
        except Exception:
            log.exception("Không lưu được bài vào Quản lý bài đăng")
        return _ok(post=res)

    # ------------------------------------------------------------------ quản lý bài đăng (lưu + đăng lại)
    def _post_call(self, key: str, fn, *args) -> dict:
        from ..facebook import FacebookError
        from ..posts import PostError

        try:
            return _ok(**{key: fn(*args)})
        except (PostError, FacebookError, OSError) as exc:
            return _fail(exc)

    def post_list(self) -> dict:
        return _ok(posts=self._posts.list(), types=[{"value": k, "label": v} for k, v in POST_TYPES.items()],
                   schedulable=list(SCHEDULABLE))

    def post_save(self, data: dict) -> dict:
        """Tạo / sửa bài (nháp hoặc bài đã đăng — sửa rồi đăng lại)."""
        return self._post_call("post", self._posts.save, data or {})

    def post_delete(self, pid: str) -> dict:
        return self._post_call("ok", lambda: self._posts.delete(pid) or True)

    def post_publish(self, pid: str, page_ids: list, confirmed: bool = False, scheduled_at: int | None = None) -> dict:
        """Đăng (lại) bài — chỉ khi người dùng đã bấm xác nhận (confirmed=True); ghi lại ai xác nhận, lúc nào."""
        return self._post_call("result", self._posts.publish, pid, page_ids or [], confirmed is True,
                               int(scheduled_at) if scheduled_at else None)

    def post_schedule(self, pid: str, page_ids: list, at: int, confirmed: bool = False) -> dict:
        """Lên lịch / đổi lịch app tự đăng (giờ + Fanpage) — chỉ khi người dùng đã xác nhận trên giao diện."""
        return self._post_call("post", self._posts.schedule, pid, page_ids or [], at, confirmed is True)

    def post_unschedule(self, pid: str) -> dict:
        return self._post_call("post", self._posts.unschedule, pid)

    def post_publish_now(self, pid: str, confirmed: bool = False) -> dict:
        """Đăng ngay bài đang lên lịch / lỡ lịch lên các Fanpage của lịch (người dùng bấm xác nhận)."""
        return self._post_call("result", self._posts.publish_now, pid, confirmed is True)
