"""Remove a user-selected fixed logo region into a separate MP4 file."""
import subprocess
from pathlib import Path

from ..ffmpeg import FFMPEG, NO_WINDOW, FFmpegError, video_size


def logo_rectangle(values, width, height):
    try:
        x, y, w, h = (float(values[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Chọn vùng logo hợp lệ trên video") from exc
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w < 1 and 0 < h < 1 and x + w <= 1.00001 and y + h <= 1.00001):
        raise ValueError("Vùng logo phải nằm hoàn toàn trong khung hình")
    # delogo needs a border of source pixels to interpolate from.
    px, py = max(1, round(x * width)), max(1, round(y * height))
    pw, ph = min(round(w * width), width - px - 2), min(round(h * height), height - py - 2)
    if pw < 2 or ph < 2:
        raise ValueError("Vùng logo quá nhỏ hoặc quá sát mép video")
    return {"x": px, "y": py, "w": pw, "h": ph}


def remove_logo(source, target, rectangle):
    source, target = Path(source), Path(target)
    width, height = video_size(source)
    rect = logo_rectangle(rectangle, width, height)
    temporary = target.with_name(target.stem + ".part.mp4")
    try:
        result = subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a?", "-vf", "delogo=" + ":".join(f"{k}={v}" for k, v in rect.items()),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(temporary),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=900)
        if result.returncode:
            raise FFmpegError(result.stderr[-2000:])
        if video_size(temporary) != (width, height):
            raise FFmpegError("Video sau xử lý không giữ nguyên kích thước")
        temporary.replace(target)
        return rect
    finally:
        temporary.unlink(missing_ok=True)
