"""Gọi ffmpeg (bản đi kèm imageio-ffmpeg, không cần cài riêng)."""
import os
import re
import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

FFMPEG = get_ffmpeg_exe()
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class FFmpegError(RuntimeError):
    pass


def _base(args) -> list[str]:
    return [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]


def run(args, cwd: Path | None = None) -> None:
    proc = subprocess.run(
        _base(args), cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip()[-2000:] or f"ffmpeg exit {proc.returncode}")


def popen_stdin(args, cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        _base(args), cwd=cwd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=NO_WINDOW,
    )


def _probe(path: Path) -> str:
    """Thông tin luồng (stderr của `ffmpeg -i`), thay cho ffprobe vốn không có trong imageio-ffmpeg."""
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    ).stderr


def has_audio(path: Path) -> bool:
    return bool(re.search(r"Stream #\S+.*Audio:", _probe(path)))


def video_size(path: Path) -> tuple[int, int]:
    match = re.search(r"Stream #\S+.*Video:.*?, (\d{2,5})x(\d{2,5})[ ,\[]", _probe(path))
    if not match:
        raise FFmpegError(f"Không đọc được kích thước video: {path}")
    return int(match.group(1)), int(match.group(2))


def media_duration(path: Path) -> float:
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", _probe(path))
    if not match:
        raise FFmpegError(f"Không đọc được thời lượng: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)
