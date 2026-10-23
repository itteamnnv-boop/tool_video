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
  common.py — logger, _ok / _fail, _hub_call
"""
from .ads import AdsApi
from .campaign import CampaignApi
from .cast import CastApi
from .content import ContentApi
from .core import CoreApi
from .facebook import FacebookApi
from .media import MediaApi
from .musehub import MuseHubApi
from .profiles import ProfilesApi
from .seedance import SeedanceApi
from .studio import StudioApi
from .system import SystemApi
from .workflow import WorkflowApi


class Api(CoreApi, WorkflowApi, MediaApi, SeedanceApi, ProfilesApi, FacebookApi, AdsApi, CampaignApi, StudioApi,
          CastApi, ContentApi, MuseHubApi, SystemApi):
    """Đối tượng duy nhất đưa cho pywebview (js_api)."""


__all__ = ["Api"]
