import json
import re

RETRY_SUFFIX = "\n\nLƯU Ý: Lần trước bạn trả về JSON không hợp lệ. Chỉ trả về đúng MỘT object JSON hợp lệ, không markdown."


class LLMError(RuntimeError):
    pass


class LLMProvider:
    name = "base"

    # Provider gửi được ảnh kèm prompt hay không (images = [(bytes, mime_type), ...]).
    supports_images = False

    def generate(self, prompt: str, images: list | None = None) -> str:
        raise NotImplementedError

    def generate_json(self, prompt: str, retries: int = 1, images: list | None = None):
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            text = self.generate(prompt if attempt == 0 else prompt + RETRY_SUFFIX, images=images)
            try:
                return extract_json(text)
            except ValueError as exc:
                last_error = exc
        raise LLMError(f"AI trả về JSON không hợp lệ: {last_error}")


def extract_json(text: str):
    """Lấy JSON từ câu trả lời (chấp nhận ```json fences, chữ thừa, dấu phẩy cuối)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("không tìm thấy JSON")
    end = max(text.rfind("}"), text.rfind("]"))
    candidate = text[min(starts):end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
