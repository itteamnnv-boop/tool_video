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
        pass
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_escape_inner_quotes(candidate))
    except json.JSONDecodeError:
        if not CURLY.search(candidate):
            raise
    # trang chat hiển thị markdown (vd. claude.ai) đổi " thành “ ” → đổi lại rồi đọc lần nữa
    return json.loads(_escape_inner_quotes(CURLY.sub('"', candidate)))


CURLY = re.compile("[“”„‟″]")


def _escape_inner_quotes(text: str) -> str:
    """Sửa lỗi hay gặp của model: dấu " nằm TRONG chuỗi (vd. "Dùng "BOSS 1" nhé") — dấu " chỉ là kết thúc chuỗi khi
    ký tự kế tiếp (bỏ khoảng trắng) là , : } ] ; còn lại coi là chữ và thêm \\ phía trước."""
    out, in_str, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if in_str and ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
            else:
                rest = text[i + 1:].lstrip()
                if not rest or rest[0] in ",:}]":
                    in_str = False
                else:
                    out.append('\\"')
                    i += 1
                    continue
        elif in_str and ch == "\n":
            out.append("\\n")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
