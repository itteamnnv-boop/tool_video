"""🔌 Kết nối MCP (mcp_*): quản lý máy chủ MCP của app — thêm / sửa / xoá, kiểm tra kết nối, quyền từng công cụ, thử gọi,
nhật ký, nhập từ Claude Desktop. Token / header / biến môi trường KHÔNG BAO GIỜ trả về giao diện (mcp_hub.public che hết).
Thay đổi cấu hình / quyền / thử gọi cần mở khoá quản trị (như sửa Canvas)."""
from .. import mcp_hub as hub
from .common import _fail, _ok


class McpApi:
    def _mcp(self, key: str, fn, *args, locked: bool = False, **kwargs) -> dict:
        if locked:
            denied = self._canvas_locked()
            if denied:
                return denied
        try:
            return _ok(**{key: fn(*args, **kwargs)})
        except Exception as exc:  # cấu hình sai / máy chủ lỗi → báo rõ trên giao diện
            return _fail(exc)

    def mcp_list(self) -> dict:
        return self._mcp("servers", hub.list_servers)

    def mcp_save(self, data: dict) -> dict:
        return self._mcp("server", hub.save_server, data or {}, locked=True)

    def mcp_delete(self, sid: str) -> dict:
        return self._mcp("deleted", lambda: hub.delete_server(sid) or sid, locked=True)

    def mcp_flag(self, sid: str, key: str, value: bool) -> dict:
        return self._mcp("server", hub.set_flag, sid, key, bool(value), locked=True)

    def mcp_allow(self, sid: str, tool: str, allowed: bool) -> dict:
        return self._mcp("server", hub.set_allowed, sid, tool, bool(allowed), locked=True)

    def mcp_check(self, sid: str) -> dict:
        """Kết nối thử + đọc danh sách công cụ (vài giây; lần đầu npx / uvx có thể tải gói ~1 phút)."""
        return self._mcp("server", hub.check, sid)

    def mcp_call(self, sid: str, tool: str, args: dict | None = None) -> dict:
        return self._mcp("result", hub.call_tool, sid, tool, args or {}, via="thử", locked=True)

    def mcp_logs(self) -> dict:
        return self._mcp("logs", hub.logs)

    def mcp_clear_logs(self) -> dict:
        return self._mcp("logs", lambda: hub.clear_logs() or [], locked=True)

    def mcp_import_desktop(self) -> dict:
        return self._mcp("imported", hub.import_claude_desktop, locked=True)

    def mcp_desktop_path(self) -> dict:
        p = hub.claude_desktop_file()
        return _ok(path=str(p), exists=p.is_file())
