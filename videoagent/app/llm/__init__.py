from .base import LLMError, LLMProvider


def make_provider(provider: str, settings, *, show_browser: bool = False) -> LLMProvider | None:
    """Trả về provider AI; None = chế độ offline (kịch bản dựng sẵn, không gọi AI)."""
    if provider == "gemini_api":
        from .gemini_api import GeminiAPIProvider
        return GeminiAPIProvider(settings.get("gemini_api_key"), settings.get("gemini_model"))
    if provider == "muse_browser":  # Muse: đọc câu trả lời theo mã yêu cầu (bong bóng chat không có vai trò)
        from .muse_browser import MuseChatProvider
        return MuseChatProvider(channel=settings.get("browser_channel"), show_browser=show_browser)
    if provider.endswith("_browser"):
        from .browser_chat import BrowserChatProvider
        return BrowserChatProvider(provider.removesuffix("_browser"), channel=settings.get("browser_channel"),
                                   show_browser=show_browser)
    return None


__all__ = ["LLMError", "LLMProvider", "make_provider"]
