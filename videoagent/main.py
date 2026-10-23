"""VideoAgent — tạo video ngắn bằng AI. Chạy: python main.py"""
import logging
import os
import sys

# Windows mặc định ghi chữ bằng cp1252 (console, file mở không ghi encoding, tiến trình con…) → tiếng Việt báo lỗi
# "'charmap' codec can't encode". Bản exe chạy ở chế độ UTF-8 (build.ps1: --python-option "X utf8"); khi chạy từ mã
# nguồn thì ép console sang UTF-8, và tiến trình con (python phụ, node…) kế thừa UTF-8.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):  # exe dạng cửa sổ: không có console (None)
        pass

import webview

from app.api import Api
from app.paths import LOG_FILE
from app.server import start_server


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("VIDEOAGENT_DEBUG") == "1" else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.getLogger("app").info("Khởi động VideoAgent · Python UTF-8 mode=%s · stdout=%s",
                                  sys.flags.utf8_mode, getattr(sys.stdout, "encoding", None))
    url = start_server()
    api = Api()
    # cửa sổ không viền: thanh tiêu đề Windows gộp vào header của app (nút thu nhỏ / phóng to / đóng vẽ trong UI).
    # VIDEOAGENT_NATIVE_FRAME=1 → dùng lại khung cửa sổ Windows như cũ.
    frameless = os.environ.get("VIDEOAGENT_NATIVE_FRAME") != "1"
    window = webview.create_window(
        "Video Agent Tool", url=url, js_api=api, width=1600, height=980,
        min_size=(1200, 760), background_color="#0b0f0c", frameless=frameless, easy_drag=False,
    )
    api.attach(window)
    webview.start(debug=os.environ.get("VIDEOAGENT_DEBUG") == "1")


if __name__ == "__main__":
    main()
