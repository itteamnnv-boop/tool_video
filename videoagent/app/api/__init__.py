"""Cầu nối JS ↔ Python cho pywebview (window.pywebview.api.<method>).

Mỗi nhóm tính năng 1 file (mixin), lớp Api ghép tất cả lại — JS gọi giống hệt trước:
  core.py — Khởi tạo, cửa sổ không viền, cài đặt, chọn file / thư mục, đăng nhập trình duyệt, giấy phép
  workflow.py — Workflow kéo thả block (wf_*)
  media.py — Tạo video / hình ảnh, hàng đợi tác vụ, thư viện video / ảnh, sửa khung cảnh HTML
  seedance.py — Seedance Studio Pro
  profiles.py — Profile trình duyệt
  facebook.py — Fanpage Facebook + quản lý bài đăng
  ads.py — Quảng cáo Facebook + Trợ lý quảng cáo Meta
  campaign.py — Chiến dịch (phòng marketing AI) + thư viện chiến dịch
  studio.py — Studio (ý tưởng → storyboard → cảnh → video) + Studio Muse AI (mstudio_*), whiteboard, SRT
  cast.py — Nhân vật & layout cố định
  content.py — Tạo content bài viết (quản lý + tạo, lấy thông tin từ link)
  musehub.py — Studio Muse AI · dây chuyền (mhub_*): tài khoản, hàng đợi, tư liệu, kịch bản, LadiPage, video mẫu, hậu kỳ, thư viện
  system.py — Tiến trình chung của hệ thống (nút ⏳ trên thanh tiêu đề): system_progress / system_cancel
  canvas.py — Canvas (canvas_*): bảng node ảnh / video kiểu Kling Canvas
  channel.py — Trợ lý nuôi kênh (ch_*): Claude điều phối + chấm, model ảnh trình duyệt tạo ảnh từ tài nguyên của kênh
  mcp.py — Kết nối MCP (mcp_*): máy chủ MCP của app, quyền từng công cụ, thử gọi, nhật ký (Trợ lý Canvas đọc dữ liệu)
  common.py — logger, _ok / _fail, _hub_call
"""
from .ads import AdsApi
from .campaign import CampaignApi
from .canvas import CanvasApi
from .cast import CastApi
from .channel import ChannelApi
from .content import ContentApi
from .core import CoreApi
from .facebook import FacebookApi
from .mcp import McpApi
from .media import MediaApi
from .musehub import MuseHubApi
from .profiles import ProfilesApi
from .seedance import SeedanceApi
from .studio import StudioApi
from .system import SystemApi
from .workflow import WorkflowApi


class Api(CoreApi, WorkflowApi, MediaApi, SeedanceApi, ProfilesApi, FacebookApi, AdsApi, CampaignApi, StudioApi,
          CastApi, ContentApi, MuseHubApi, SystemApi, CanvasApi, ChannelApi, McpApi):
    """Đối tượng duy nhất đưa cho pywebview (js_api)."""

    def _screen_locked(self, screen: str) -> dict | None:
        """🔒 Màn bị khoá (Cài đặt → Bảo mật → Khoá màn hình) và chưa mở khoá → trả lỗi cho lệnh của màn đó."""
        from ..config import settings

        lock = self._admin_lock()
        if screen == "settings":  # 📣 Fanpage nằm trong Cài đặt → cần Cài đặt đang mở khoá (đã đặt mật khẩu)
            if not lock.has_password():
                return None
        elif screen not in (settings.get("locked_screens") or []):
            return None
        if lock.unlocked():
            lock.touch()
            return None
        return {"ok": False, "locked": True, "screen": screen,
                "error": f"Màn “{SCREEN_NAMES.get(screen, screen)}” đang khoá — nhập mật khẩu quản trị để dùng"}

    def screen_locks(self) -> dict:
        """Danh sách màn bị khoá (giao diện hiện 🔒 và hỏi mật khẩu khi mở)."""
        from ..config import settings

        return {"ok": True, "locked": list(settings.get("locked_screens") or [])}


# 🔒 lệnh backend của từng màn bị chặn khi màn đó khoá (thao tác ghi / dữ liệu nhạy cảm). Lệnh đọc dùng chung với màn
# khác (fb_state, ads_status, ads_accounts…) và đăng bài từ quy trình Canvas / lịch đã duyệt vẫn chạy bình thường.
SCREEN_NAMES = {"settings": "Cài đặt", "ads": "Quảng cáo Facebook", "posts": "Quản lý bài đăng"}
SCREEN_APIS = {
    # 📣 Fanpage Facebook đã chuyển vào Cài đặt → Facebook · Meta: theo khoá Cài đặt
    "settings": ("fb_save_app", "fb_connect_token", "fb_logout", "fb_load_pages", "fb_set_connected", "fb_post"),
    "ads": ("ads_overview", "ads_list", "ads_set_status", "ads_set_budget", "ads_page_posts", "ads_create_boost"),
    "posts": ("post_save", "post_delete", "post_publish", "post_schedule", "post_reject", "post_unschedule",
              "post_publish_now"),
}


def _guard(screen: str, fn):
    import functools

    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        return self._screen_locked(screen) or fn(self, *args, **kwargs)
    return wrapped


for _screen, _names in SCREEN_APIS.items():
    for _name in _names:
        if hasattr(Api, _name):
            setattr(Api, _name, _guard(_screen, getattr(Api, _name)))

__all__ = ["Api"]
