"""Studio Muse AI — dây chuyền Muse: nhiều tài khoản (profile Muse của hệ thống) chạy song song, hạn mức tuần,
hàng đợi task ảnh / video có lịch sử, dự án, tư liệu (nhân vật, mẫu prompt, người mẫu cố định, ảnh luân phiên),
thư viện file + ghép video.

- Tài khoản = profile trình duyệt đã gán Muse (màn Profile trình duyệt) — không đăng nhập lại, không tạo profile riêng.
- Gửi / nhận: dùng bộ điều khiển Muse sẵn có (app/llm/muse_browser.py), chỉ định đúng profile bằng task_context.
- Hạn mức tuần: đọc chỉ đọc từ trang muse.ai đã đăng nhập (server action của trang Muse, không tốn lượt).
- Dữ liệu: <DATA_DIR>/muse_hub/{hub.json, tasks.json, assets/}; file kết quả: <thư mục video>/_muse_hub/<dự án>/.

Tách theo tính năng (mixin) — MuseHub ghép lại, dùng giống hệt trước:
  core.py — khởi tạo, lưu trạng thái, trạng thái gửi giao diện, cài đặt, dự án
  accounts.py — tài khoản Muse (profile trình duyệt) + đọc hạn mức
  assets.py — tư liệu (nhân vật, mẫu prompt, người mẫu, ảnh luân phiên) + nhập ảnh
  queue.py — hàng đợi task: thêm, huỷ / chạy lại, dừng, vòng điều phối, chạy 1 task trên Muse
  library.py — thư viện kết quả, tên dễ nhận biết, chuyển dự án, nguồn cho Hậu kỳ, ghép video
  groups.py — kịch bản → nhóm video (storyboard, từng cảnh, chia đoạn), duyệt, ghép + nhạc nền, LadiPage
  common.py — hằng số, STORE, hàm thuần dùng chung
"""
from . import common
from .common import (DEFAULT_SETTINGS, HubError, MAX_IMAGES, OUT_DIR, QUOTA_HINT, QUOTA_JS, RATIOS, SITE, STATUS,
                     STORE, TERMINAL, VIDEO_SECONDS, asset_url, compose_images, now_ms, parse_quota, plan, safe_name,
                     usable, weekly_out)
from .accounts import AccountsMixin
from .assets import AssetsMixin
from .core import CoreMixin
from .groups import GroupsMixin
from .library import LibraryMixin
from .queue import QueueMixin


class MuseHub(CoreMixin, AccountsMixin, AssetsMixin, QueueMixin, LibraryMixin, GroupsMixin):
    """Dây chuyền Studio Muse AI: tài khoản, hàng đợi, tư liệu, kịch bản, thư viện."""
