"""Đường dẫn tài nguyên (đóng gói PyInstaller được) và thư mục dữ liệu người dùng."""
import os
import sys
from pathlib import Path

APP_NAME = "VideoAgent"


def _resource_root() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if "WindowsApps" in sys.base_prefix:
        # Python bản Microsoft Store ảo hoá %APPDATA%: tiến trình con (ffmpeg, Chrome) không thấy file ghi vào đó.
        path = Path.home() / ".videoagent"
    else:
        path = Path(os.environ.get("APPDATA") or Path.home() / ".config") / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


ROOT = _resource_root()
UI_DIR = ROOT / "ui"
TEMPLATES_DIR = ROOT / "templates"
ASSETS_DIR = ROOT / "assets"

DATA_DIR = _data_dir()
CACHE_DIR = DATA_DIR / "cache"
BROWSER_PROFILE_DIR = DATA_DIR / "gemini-profile"
LOG_FILE = DATA_DIR / "videoagent.log"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
