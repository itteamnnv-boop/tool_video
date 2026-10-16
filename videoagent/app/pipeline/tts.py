"""Giọng đọc bằng edge-tts (miễn phí, cần internet), kèm mốc thời gian từng từ cho phụ đề karaoke."""
import asyncio
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


class TTSError(RuntimeError):
    pass


async def _synthesize(text: str, voice: str, rate: str, out_path: Path) -> list[dict]:
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # edge-tts < 7 không có tham số boundary (mặc định đã là WordBoundary)
        communicate = edge_tts.Communicate(text, voice, rate=rate)
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


def synthesize(text: str, voice: str, rate: str, out_path: Path, retries: int = 3) -> list[dict]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return asyncio.run(_synthesize(text, voice, rate, out_path))
        except Exception as exc:  # edge-tts ném lỗi mạng/websocket nhiều kiểu
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise TTSError(f"Không tạo được giọng đọc (edge-tts): {last_error}")
