"""Âm thanh phụ: tiếng whoosh chuyển cảnh và nhạc nền (từ thư mục nhạc của người dùng hoặc pad tự tổng hợp)."""
import random
from pathlib import Path

from .. import ffmpeg
from ..paths import ASSETS_DIR, CACHE_DIR

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def whoosh() -> Path:
    path = CACHE_DIR / "whoosh.wav"
    if not path.exists():
        ffmpeg.run([
            "-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:r=44100:a=0.5",
            "-af", "highpass=f=300,lowpass=f=5000,afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35",
            "-ac", "2", path,
        ])
    return path


def ambient_pad() -> Path:
    path = CACHE_DIR / "pad.wav"
    if not path.exists():
        expr = ("0.06*sin(2*PI*110*t)*(0.6+0.4*sin(2*PI*0.2*t))"
                "+0.045*sin(2*PI*164.81*t)*(0.6+0.4*sin(2*PI*0.13*t+1))"
                "+0.035*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*0.07*t+2))")
        ffmpeg.run([
            "-f", "lavfi", "-i", f"aevalsrc={expr}:s=44100:d=40",
            "-af", "lowpass=f=1200,afade=t=in:d=0.5,afade=t=out:st=39.5:d=0.5", "-ac", "2", path,
        ])
    return path


def background_music(music_dir: str) -> Path:
    for folder in (Path(music_dir) if music_dir else None, ASSETS_DIR / "music"):
        if folder and folder.is_dir():
            tracks = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT]
            if tracks:
                return random.choice(tracks)
    return ambient_pad()
