"""Hậu kỳ: ghép khung → lồng giọng → SFX + nhạc nền → phụ đề → cân âm lượng → final.mp4.

Chạy ffmpeg với cwd = thư mục video và đường dẫn tương đối để tránh lỗi escape đường dẫn Windows/Unicode.
"""
import shutil
from pathlib import Path

from .. import ffmpeg
from ..ffmpeg import FFmpegError
from . import VOICE_LEAD, scene_dir_name
from . import sfx
from .subtitles import build_ass


def _offsets(scenes: list[dict]) -> list[float]:
    out, acc = [], 0.0
    for scene in scenes:
        out.append(acc)
        acc += scene["duration"]
    return out


def compose(job_dir: Path, job: dict, *, log, check_cancel, music_dir: str = "", cleanup: bool = True) -> Path:
    scenes = job["scenes"]
    voice_lead = float(job.get("voice_lead", VOICE_LEAD))  # 0 khi giữ tiếng gốc video (khớp khẩu hình)
    offsets = _offsets(scenes)
    total = sum(s["duration"] for s in scenes)
    tmp = job_dir / "tmp"
    tmp.mkdir(exist_ok=True)

    log("Đang ghép các khung")
    (tmp / "concat.txt").write_text(
        "".join(f"file '../scenes/{scene_dir_name(s['index'])}/scene.mp4'\n" for s in scenes), "utf-8")
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", "tmp/concat.txt", "-c", "copy", "tmp/video.mp4"], cwd=job_dir)
    check_cancel()

    log("Đang lồng giọng đọc")
    args, chains, labels = [], [], []
    for k, scene in enumerate(scenes):
        args += ["-i", f"scenes/{scene_dir_name(scene['index'])}/voice.mp3"]
        delay = int((offsets[k] + voice_lead) * 1000)
        chains.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={delay}:all=1[v{k}]")
        labels.append(f"[v{k}]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[out]")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{total:.3f}",
                "-c:a", "pcm_s16le", "tmp/voice.wav"], cwd=job_dir)
    check_cancel()

    log("Đang thêm hiệu ứng âm thanh")
    whoosh = sfx.whoosh()
    args, chains, labels = [], [], []
    for k, off in enumerate(offsets):
        args += ["-i", whoosh]
        chains.append(f"[{k}:a]volume=0.55,adelay={int(max(0.0, off - 0.12) * 1000)}:all=1[s{k}]")
        labels.append(f"[s{k}]")
    if job.get("bgm", True):
        music = sfx.background_music(music_dir)
        n = len(offsets)
        args += ["-stream_loop", "-1", "-i", music]
        chains.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume={job.get('bgm_volume', 0.12)},"
                      f"afade=t=in:d=1,afade=t=out:st={max(0.0, total - 1.5):.2f}:d=1.5[bg]")
        labels.append("[bg]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[out]")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{total:.3f}",
                "-c:a", "pcm_s16le", "tmp/fx.wav"], cwd=job_dir)
    check_cancel()

    video_in = "tmp/video.mp4"
    if job.get("subtitles"):
        log("Đang thêm phụ đề")
        (tmp / "subs.ass").write_text(build_ass(job, job.get("subtitle_margin", 0.07)), "utf-8")
        try:
            ffmpeg.run(["-i", "tmp/video.mp4", "-vf", "subtitles=tmp/subs.ass", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "tmp/video_subs.mp4"], cwd=job_dir)
            video_in = "tmp/video_subs.mp4"
        except FFmpegError as exc:
            log(f"Không chèn được phụ đề, bỏ qua: {exc}", "warn")
        check_cancel()

    log("Đang cân âm lượng")
    ffmpeg.run([
        "-i", video_in, "-i", "tmp/voice.wav", "-i", "tmp/fx.wav",
        "-filter_complex",
        "[1:a][2:a]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", f"{total:.3f}", "-movflags", "+faststart", "final.mp4",
    ], cwd=job_dir)

    if cleanup:
        shutil.rmtree(tmp, ignore_errors=True)
    return job_dir / "final.mp4"
