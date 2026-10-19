"""VideoAgent — tạo video ngắn bằng AI. Chạy: python main.py"""
import logging
import os

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
