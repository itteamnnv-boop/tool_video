from .base import LLMError, LLMProvider


class GeminiAPIProvider(LLMProvider):
    name = "gemini_api"
    supports_images = True

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMError("Chưa nhập Gemini API key trong Cài đặt")
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or "gemini-2.5-flash"

    def generate(self, prompt: str, images: list | None = None) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.9)
        contents = [prompt, *(types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images or [])]
        try:
            resp = self._client.models.generate_content(model=self._model, contents=contents, config=config)
        except Exception as exc:  # SDK ném nhiều loại lỗi mạng/quota khác nhau
            raise LLMError(f"Gemini API lỗi: {exc}") from exc
        if not resp.text:
            raise LLMError("Gemini API không trả về nội dung")
        return resp.text
