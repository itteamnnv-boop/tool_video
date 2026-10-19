"""Giọng đọc bằng edge-tts (miễn phí, cần internet), kèm mốc thời gian từng từ cho phụ đề karaoke."""
import asyncio
import re
import threading
import time
from pathlib import Path

import edge_tts

VOICES = [
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My — nữ"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh — nam"},
    {"id": "en-US-AriaNeural", "name": "Aria — nữ (English)"},
    {"id": "en-US-GuyNeural", "name": "Guy — nam (English)"},
]
RATES = ["-10%", "+0%", "+10%", "+20%"]
# Vai giọng (người nói trong cảnh): edge-tts tiếng Việt chỉ có 1 giọng nữ + 1 giọng nam → chỉnh cao độ / tốc độ
# để gần với trẻ em, người trẻ, trung niên, người già. "" = giọng mặc định của dự án.
# key: (nhãn, giọng gốc, cao độ Hz, tốc độ % cộng thêm, mô tả tiếng Anh cho model video có tiếng)
ROLES = {
    "": ("Mặc định của dự án", "", 0, 0, ""),
    "narrator_f": ("Người dẫn chuyện — nữ", "vi-VN-HoaiMyNeural", 0, 0, "a warm female narrator voice"),
    "narrator_m": ("Người dẫn chuyện — nam", "vi-VN-NamMinhNeural", 0, 0, "a warm male narrator voice"),
    "girl": ("Bé gái", "vi-VN-HoaiMyNeural", 45, 8, "a little girl's high-pitched child voice (about 7 years old)"),
    "boy": ("Bé trai", "vi-VN-HoaiMyNeural", 28, 8, "a little boy's child voice (about 8 years old)"),
    "young_f": ("Cô gái trẻ", "vi-VN-HoaiMyNeural", 8, 3, "a bright young woman's voice (about 20 years old)"),
    "young_m": ("Chàng trai trẻ", "vi-VN-NamMinhNeural", 6, 3, "a young man's voice (about 20 years old)"),
    "woman": ("Phụ nữ trung niên", "vi-VN-HoaiMyNeural", -8, -3, "a mature middle-aged woman's voice"),
    "man": ("Đàn ông trung niên", "vi-VN-NamMinhNeural", -8, -3, "a deep middle-aged man's voice"),
    "old_f": ("Bà cụ", "vi-VN-HoaiMyNeural", -20, -12, "an elderly grandmother's slow, slightly raspy voice"),
    "old_m": ("Ông cụ", "vi-VN-NamMinhNeural", -18, -12, "an elderly grandfather's slow, low, slightly raspy voice"),
    "teen_f": ("Thiếu nữ (15–18 tuổi)", "vi-VN-HoaiMyNeural", 18, 5, "a cheerful teenage girl's voice (about 16)"),
    "teen_m": ("Thiếu niên (15–18 tuổi)", "vi-VN-NamMinhNeural", 14, 5, "a teenage boy's voice (about 16)"),
    "mc_f": ("MC nữ — năng động", "vi-VN-HoaiMyNeural", 4, 10, "an energetic, upbeat female host voice"),
    "mc_m": ("MC nam — năng động", "vi-VN-NamMinhNeural", 3, 10, "an energetic, upbeat male host voice"),
    "soft_f": ("Nữ nhẹ nhàng, tâm tình", "vi-VN-HoaiMyNeural", -4, -8, "a soft, gentle, intimate female voice"),
    "deep_m": ("Nam trầm, uy lực", "vi-VN-NamMinhNeural", -14, -6, "a deep, powerful, authoritative male voice"),
    # giọng đa ngôn ngữ (Microsoft) đọc được tiếng Việt nhưng hơi lơ lớ — thêm âm sắc khác hẳn cho nhiều nhân vật,
    # hợp vai người nước ngoài / vai cách điệu
    "intl_f1": ("Nữ khác 1 — Ava (đa ngôn ngữ, hơi lơ lớ)", "en-US-AvaMultilingualNeural", 0, 0,
                "a warm female voice with a slight foreign accent"),
    "intl_f2": ("Nữ khác 2 — Emma (đa ngôn ngữ, hơi lơ lớ)", "en-US-EmmaMultilingualNeural", 0, 0,
                "a bright female voice with a slight foreign accent"),
    "intl_f3": ("Nữ khác 3 — Vivienne (đa ngôn ngữ, hơi lơ lớ)", "fr-FR-VivienneMultilingualNeural", 0, 0,
                "an elegant female voice with a slight French accent"),
    "intl_m1": ("Nam khác 1 — Andrew (đa ngôn ngữ, hơi lơ lớ)", "en-US-AndrewMultilingualNeural", 0, 0,
                "a friendly male voice with a slight foreign accent"),
    "intl_m2": ("Nam khác 2 — Brian (đa ngôn ngữ, hơi lơ lớ)", "en-US-BrianMultilingualNeural", 0, 0,
                "a relaxed male voice with a slight foreign accent"),
    "intl_m3": ("Nam khác 3 — Hyunsu (đa ngôn ngữ, hơi lơ lớ)", "ko-KR-HyunsuMultilingualNeural", 0, 0,
                "a young male voice with a slight Korean accent"),
}


def role_voice(role: str, voice: str, rate: str) -> tuple[str, str, str]:
    """Vai giọng → (giọng edge-tts, tốc độ, cao độ). Vai lạ / mặc định → giọng + tốc độ của dự án.
    Dự án chọn giọng tiếng Anh thì giữ giọng đó, chỉ đổi cao độ / tốc độ theo vai."""
    _, base, pitch, extra, _ = ROLES.get(role or "", ROLES[""])
    if not base:
        return voice, rate, "+0Hz"
    if not voice.startswith("vi-VN") and base.startswith("vi-VN"):  # dự án giọng tiếng Anh: giữ giọng dự án
        base = voice
    try:
        total = int(str(rate).rstrip("%")) + extra
    except ValueError:
        total = extra
    return base, f"{total:+d}%", f"{pitch:+d}Hz"


class TTSError(RuntimeError):
    pass


# có chữ cái (gồm tiếng Việt) hoặc chữ số để đọc
SPEAKABLE = re.compile(r"[0-9A-Za-zÀ-ɏḀ-ỿ]")
RETRY_DELAYS = (1.5, 3, 5, 8, 12)  # giây chờ giữa các lần thử lại
_SLOTS = threading.BoundedSemaphore(3)  # tối đa 3 lệnh đọc cùng lúc (gọi dồn dập dễ bị dịch vụ từ chối)


async def _synthesize(text: str, voice: str, rate: str, out_path: Path, pitch: str = "+0Hz") -> list[dict]:
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    except TypeError:  # edge-tts < 7 không có tham số boundary (mặc định đã là WordBoundary)
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    words = []
    with open(out_path, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": round(start, 3),
                              "end": round(start + chunk["duration"] / 1e7, 3)})
    return words


def synthesize_lines(parts: list[tuple], out_path: Path, gap: float = 0.25) -> list[dict]:
    """Nhiều câu thoại, mỗi câu một giọng: parts = [(câu, giọng, tốc độ, cao độ)] → nối thành out_path (mp3, nghỉ gap giây
    giữa các câu) + mốc từng từ đã dời theo vị trí câu (phụ đề vẫn khớp)."""
    from .. import ffmpeg

    if len(parts) == 1:
        text, voice, rate, pitch = parts[0]
        return synthesize(text, voice, rate, out_path, pitch=pitch)
    words, offset, files = [], 0.0, []
    for i, (text, voice, rate, pitch) in enumerate(parts):
        part = out_path.with_name(f"{out_path.stem}_line{i:02d}.mp3")
        for w in synthesize(text, voice, rate, part, pitch=pitch):
            words.append({**w, "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)})
        offset += ffmpeg.media_duration(part) + gap
        files.append(part)
    chain = "".join(f"[{i}:a]aresample=24000,aformat=sample_fmts=fltp:channel_layouts=mono,apad=pad_dur={gap}[a{i}];"
                    for i in range(len(files)))
    chain += "".join(f"[a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=0:a=1[out]"
    ffmpeg.run([*sum((["-i", str(f)] for f in files), []), "-filter_complex", chain, "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)])
    for f in files:
        f.unlink(missing_ok=True)
    return words


def _silence(out_path: Path, seconds: float = 0.4) -> None:
    from .. import ffmpeg

    ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.2f}", "-c:a", "libmp3lame",
                "-b:a", "48k", str(out_path)])


def synthesize(text: str, voice: str, rate: str, out_path: Path, retries: int = 6, pitch: str = "+0Hz") -> list[dict]:
    """Đọc text → out_path (mp3) + mốc từng từ. Dịch vụ edge-tts hay lỗi theo đợt ("No audio was received" dù tham số
    đúng) → thử lại giãn dần (~30 giây) và giới hạn số lệnh đọc cùng lúc. Câu không có chữ / số để đọc (emoji, ♪,
    dấu câu…) → khoảng lặng ngắn thay vì báo lỗi."""
    if not SPEAKABLE.search(text or ""):
        _silence(out_path)
        return []
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with _SLOTS:
                return asyncio.run(_synthesize(text, voice, rate, out_path, pitch))
        except Exception as exc:  # edge-tts ném lỗi mạng/websocket nhiều kiểu
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    raise TTSError(f"Không tạo được giọng đọc (edge-tts) sau {retries} lần thử — dịch vụ đọc của Microsoft đang lỗi "
                   f"hoặc mạng chập chờn, thử lại sau ít phút: {last_error}")
