"""Cài đặt người dùng, lưu ở %APPDATA%/VideoAgent/settings.json."""
import json
import threading
from pathlib import Path

from .paths import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS = {
    "pronounce": "KINGER = Kinh gơ",  # 🗣 từ điển phát âm (mỗi dòng "viết = đọc") — áp cho giọng đọc, phụ đề giữ chữ gốc
    "output_dir": str(Path.home() / "Videos" / "VideoAgent"),
    "browser_engine": "cdp",  # cdp = Chrome thật (cờ tối thiểu, không headless) · playwright = cách cũ
    "browser_keepalive": False,  # kiểu HaoHao: giữ Chrome mở sẵn cho mỗi profile, task dùng lại (cần chế độ cdp)
    "show_browser": False,  # cài đặt chung: hiện cửa sổ Chrome khi model chạy qua trình duyệt (tắt = chạy ẩn, ẩn cả icon taskbar)
    "provider": "gemini_browser",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "veo_model": "veo-3.1-generate-preview",  # model Veo khi tạo video AI bằng Gemini API
    # 🎥 màn Grok Canvas: model định sẵn (Cài đặt của màn) + profile trình duyệt từng loại ("" = tự chọn profile)
    "fcanvas_model_text": "chatgpt_browser", "fcanvas_model_image": "chatgpt_browser",
    "fcanvas_model_video": "grok_browser", "fcanvas_model_assist": "claude_browser",
    # 📋 tác vụ Canvas: số tác vụ chạy cùng lúc (còn lại chờ) — Canvas / Grok Canvas
    "canvas_task_parallel": 2, "fcanvas_task_parallel": 2,
    # 🧠 cách gọi model CHỮ theo hãng: "browser" (trình duyệt) | "cli" (Claude Code / Codex / Gemini CLI / Grok CLI);
    # CLI lỗi → lượt đó chạy bằng trình duyệt (llm_cli_fallback)
    "llm_mode_claude": "browser", "llm_mode_chatgpt": "browser", "llm_mode_gemini": "browser", "llm_mode_grok": "browser",
    "llm_mode_muse": "browser", "llm_cli_fallback": True,
    "grok_cli_key": "",  # xAI API key cho Grok CLI (chỉ truyền vào lượt chạy Grok CLI)
    # 🎬 Trợ lý TVC: Claude Code chạy skill tvc-livestream-capcut — thư mục làm việc ("" = D:/CapCut), model Claude ("" = mặc
    # định của Claude Code)
    "tvc_root": "", "tvc_claude_model": "", "tvc_rubric": "",
    # 🔒 màn bị khoá bằng mật khẩu quản trị (Cài đặt → Bảo mật → Khoá màn hình) — mã màn (data-view) ở thanh bên
    "locked_screens": [],
    "fcanvas_profile_text": "", "fcanvas_profile_image": "", "fcanvas_profile_video": "", "fcanvas_profile_assist": "",
    "flow_project_url": "",  # 🎬 Google Flow: dự án app dùng chung cho mọi video (tự nhớ lần đầu tạo; xoá trống = tạo dự án mới)
    "openai_api_key": "",  # dùng chung: Tạo hình ảnh (GPT Image) + model văn bản OpenAI (Chiến dịch, Tạo content)
    "anthropic_api_key": "",  # Claude: Chiến dịch, Tạo content, Workflow
    "heygen_api_key": "",  # 🧑‍💼 khối Video HeyGen (Canvas / Workflow) — app/llm/heygen_api.py
    "use_api_models": False,  # 🔑 tắt = CHỈ dùng model trình duyệt: ẩn + không dùng mọi khoá API (app/api_mode.py)
    "openai_image_model": "gpt-image-1",  # model chính của trang Tạo hình ảnh
    "gemini_image_model": "gemini-2.5-flash-image",
    "last_image_form": {},
    # Model AI dùng chung (Cài đặt → Model AI): mọi màn hình dùng chung, trừ trang đặc thù (Studio Muse AI, Seedance…)
    "model_text": "chatgpt_browser",  # viết storyboard, phân tích / viết lại ý tưởng, mô tả nhân vật, content, chiến dịch
    "model_text_profile": "",
    "model_image": "",  # trống = model của lần Tạo hình ảnh gần nhất (hoặc GPT Image API)
    "model_image_profile": "",
    "model_video": "grok_browser",
    "model_video_profile": "",
    "model_post": "claude_browser",  # hậu kỳ AI
    "model_post_profile": "",
    "model_vision": "gemini_browser",  # phân tích video tham khảo (cần model xem được hình)
    "browser_channel": "chrome",  # chrome | msedge | chromium
    "fps": 30,
    "max_parallel_video": 2,  # số video tạo song song tối đa
    "max_parallel_image": 2,  # số tác vụ tạo ảnh song song tối đa
    "music_dir": "",
    "bgm_volume": 0.12,
    "cleanup_temp": True,
    "splash_seconds": 1,
    "menus": {},  # Cài đặt → Chức năng: {view: true/false} bật / tắt từng mục menu (thiếu = theo mặc định)  # màn Loading khi mở app: hiện tối thiểu bấy nhiêu giây (0 = vào ngay khi tải xong)
    "adreq_account": "",  # Trợ lý quảng cáo → Chat với Claude: tài khoản quảng cáo dùng lần trước
    # Zalo (zca-js, không chính thức): nghe tin nhóm → yêu cầu quảng cáo chờ duyệt
    "zalo_listen": False,
    "zalo_groups": [],  # id nhóm Zalo được theo dõi (chọn thêm từ danh sách)
    # tên nhóm cần nghe (mỗi dòng 1 nhóm; không phân biệt dấu / hoa thường; gõ phần đầu tên cũng khớp)
    "zalo_group_names": "VIDEO, HÌNH ẢNH, BÀI VIẾT PR",
    "zalo_auto": "rules",  # off | rules | claude
    "zalo_chat_id": "",  # cuộc trò chuyện Claude dành cho tin Zalo
    "zalo_show_claude": True,  # chế độ claude: hiện cửa sổ Claude (để bấm cho phép công cụ MCP)
    "assist_mcp": False,  # Trợ lý Canvas: cho Claude CHỈ ĐỌC dữ liệu qua connector MCP của claude.ai
    "assist_mcp_note": "",  # ghi chú nguồn dữ liệu cho trợ lý (VD "Drive thư mục Sản phẩm, bảng giá trên Sheets")
    "license_server": "",  # để trống = chế độ phát triển (bỏ qua license)
    "last_form": {},
}


def clean_api_key(value) -> str:
    """Khoá API dán vào ô Cài đặt hay dính khoảng trắng / xuống dòng / chữ thừa (dán 2 lần, dán kèm ghi chú).
    API (OpenAI, Anthropic, Gemini) báo sai khoá nếu gửi nguyên chuỗi → lấy đúng 1 khoá: phần bắt đầu bằng sk- (OpenAI,
    Anthropic) hoặc AIza (Gemini) nếu có, không thì phần đầu tiên; bỏ dấu nháy bao quanh."""
    raw = str(value or "").strip().strip("\"'")
    parts = raw.split()
    if len(parts) <= 1:
        return raw
    return next((p for p in parts if p.startswith(("sk-", "AIza"))), parts[0]).strip("\"'")


class Settings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            try:
                self._data.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        for key in [k for k in self._data if k.endswith("_api_key")]:  # khoá lưu từ trước dính khoảng trắng / chữ thừa
            self._data[key] = clean_api_key(self._data[key])

    def _api_off(self) -> bool:
        return not self._data.get("use_api_models", False)

    def get(self, key: str, default=None):
        if key.endswith("_api_key") and self._api_off():  # 🔑 chỉ dùng model trình duyệt → không khoá API nào được dùng
            return ""
        value = self._data.get(key, DEFAULTS.get(key, default))
        return clean_api_key(value) if key.endswith("_api_key") else value  # khoá đã lưu từ trước vẫn được làm sạch

    def all(self) -> dict:
        data = dict(self._data)
        if self._api_off():  # khoá API đang ẩn → không gửi lên giao diện
            data.update({k: "" for k in data if k.endswith("_api_key")})
        return data

    def update(self, values: dict) -> dict:
        with self._lock:
            off = self._api_off()  # trạng thái TRƯỚC lần lưu này: ô khoá đang ẩn / che → không bao giờ ghi khoá
            for key, value in (values or {}).items():
                if key.endswith("_api_key") and off:  # (kể cả lần bật lại: ô đang rỗng vì bị che → không xoá khoá đã lưu)
                    continue
                if key in DEFAULTS:
                    self._data[key] = clean_api_key(value) if key.endswith("_api_key") else value
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
