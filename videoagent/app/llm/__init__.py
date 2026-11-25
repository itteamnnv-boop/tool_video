from .base import LLMError, LLMProvider


def make_provider(provider: str, settings, *, show_browser: bool = False, cli: bool = True) -> LLMProvider | None:
    """Trả về provider AI; None = chế độ offline (kịch bản dựng sẵn, không gọi AI).
    cli=False: luôn dùng trình duyệt (VD Tra cứu web cần model tự tìm trên mạng — CLI chạy chế độ an toàn, tắt web)."""
    if provider == "gemini_api":
        from .gemini_api import GeminiAPIProvider
        return GeminiAPIProvider(settings.get("gemini_api_key"), settings.get("gemini_model"))
    if provider == "muse_browser":  # Muse: đọc câu trả lời theo mã yêu cầu (bong bóng chat không có vai trò)
        from .muse_browser import MuseChatProvider
        muse = MuseChatProvider(channel=settings.get("browser_channel"), show_browser=show_browser)
        from . import cli_chat  # 🧠 Muse chọn CLI (muse-cli của muse.ai) → việc chữ qua CLI, lỗi → trình duyệt

        if cli and cli_chat.mode(settings, "muse") == "cli":  # hết lượt / credit → luôn sang trình duyệt
            return cli_chat.CliChatProvider("muse", fallback=muse,
                                            fallback_all=settings.get("llm_cli_fallback", True) is not False)
        return muse
    if provider.endswith("_browser"):
        from .browser_chat import BrowserChatProvider
        site = provider.removesuffix("_browser")
        browser = BrowserChatProvider(site, channel=settings.get("browser_channel"), show_browser=show_browser)
        from . import cli_chat  # 🧠 Cài đặt → Trình duyệt → Cách gọi model chữ: hãng này chọn CLI → chạy qua CLI

        if cli and site in cli_chat.CLIS and cli_chat.mode(settings, site) == "cli":
            # lỗi CLI → trình duyệt nếu bật llm_cli_fallback; CLI hết lượt / hết credit → LUÔN sang trình duyệt
            return cli_chat.CliChatProvider(site, fallback=browser,
                                            fallback_all=settings.get("llm_cli_fallback", True) is not False)
        return browser
    return None


__all__ = ["LLMError", "LLMProvider", "make_provider"]
