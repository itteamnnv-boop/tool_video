"""Nghe lại lời thoại trong video (Gemini API): tách tiếng bằng ffmpeg → Gemini chép nguyên văn lời nói.
Dùng cho khối Hậu kỳ video khi ô lời đọc để trống (phụ đề / lồng tiếng theo đúng tiếng gốc của video)."""
from pathlib import Path

from .. import ffmpeg
from ..llm.base import extract_json

MAX_SECONDS = 600  # chỉ nghe 10 phút đầu (video ngắn — đủ dùng, file tiếng nhỏ)
PROMPT = """Đây là phần tiếng của 1 video ngắn. Hãy CHÉP LẠI NGUYÊN VĂN lời người nói trong đoạn tiếng (giữ đúng ngôn ngữ
người nói, thường là tiếng Việt; thêm dấu câu cho dễ đọc). KHÔNG dịch, KHÔNG tóm tắt, KHÔNG thêm lời không có trong tiếng.
Bỏ qua nhạc, tiếng động, tiếng ồn. Không có lời người nói → để chuỗi rỗng.
Trả về MỘT object JSON: {"loi": "toàn bộ lời nói theo thứ tự"}"""


class SpeechError(RuntimeError):
    pass


def can_listen(settings) -> bool:
    return bool(settings.get("gemini_api_key"))


def transcribe(video: Path, settings, work: Path) -> str:
    """Lời nói trong video ("" nếu video không có tiếng / không có lời người nói)."""
    video = Path(video)
    if not ffmpeg.has_audio(video):
        return ""
    key = settings.get("gemini_api_key")
    if not key:
        raise SpeechError("Chưa nhập Gemini API key trong Cài đặt — cần để nghe lời thoại trong video")
    work.mkdir(parents=True, exist_ok=True)
    audio = work / f"{video.stem}_tieng.mp3"
    ffmpeg.run(["-i", video, "-t", str(MAX_SECONDS), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", audio])
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
    try:
        resp = client.models.generate_content(
            model=settings.get("gemini_model") or "gemini-2.5-flash", config=config,
            contents=[PROMPT, types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/mp3")])
    except Exception as exc:  # SDK ném nhiều loại lỗi mạng / quota khác nhau
        raise SpeechError(f"Gemini API lỗi khi nghe lời thoại: {exc}") from exc
    finally:
        audio.unlink(missing_ok=True)
    text = resp.text or ""
    try:
        data = extract_json(text)
    except ValueError:
        data = None
    said = data.get("loi") if isinstance(data, dict) else text
    return " ".join(str(said or "").split())
