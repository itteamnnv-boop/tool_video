"""Cài đặt người dùng, lưu ở %APPDATA%/VideoAgent/settings.json."""
import json
import threading
from pathlib import Path

from .paths import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS = {
    "output_dir": str(Path.home() / "Videos" / "VideoAgent"),
    "provider": "gemini_browser",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "veo_model": "veo-3.1-generate-preview",  # model Veo khi tạo video AI bằng Gemini API
    "openai_api_key": "",  # dùng chung: Tạo hình ảnh (GPT Image) + model văn bản OpenAI (Chiến dịch, Tạo content)
    "anthropic_api_key": "",  # Claude: Chiến dịch, Tạo content, Workflow
    "openai_image_model": "gpt-image-1",  # model chính của trang Tạo hình ảnh
    "gemini_image_model": "gemini-2.5-flash-image",
    "last_image_form": {},
    "browser_channel": "chrome",  # chrome | msedge | chromium
    "fps": 30,
    "max_parallel_video": 2,  # số video tạo song song tối đa
    "max_parallel_image": 2,  # số tác vụ tạo ảnh song song tối đa
    "music_dir": "",
    "bgm_volume": 0.12,
    "cleanup_temp": True,
    "license_server": "",  # để trống = chế độ phát triển (bỏ qua license)
    "last_form": {},
}


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            try:
                self._data.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def all(self) -> dict:
        return dict(self._data)

    def update(self, values: dict) -> dict:
        with self._lock:
            for key, value in (values or {}).items():
                if key in DEFAULTS:
                    self._data[key] = value
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(SETTINGS_FILE)
        return self.all()

    @property
    def output_dir(self) -> Path:
        path = Path(self.get("output_dir")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
