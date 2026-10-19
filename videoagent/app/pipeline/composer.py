"""Hậu kỳ: ghép khung → lồng giọng → SFX + nhạc nền → phụ đề → cân âm lượng → final.mp4.

Chạy ffmpeg với cwd = thư mục video và đường dẫn tương đối để tránh lỗi escape đường dẫn Windows/Unicode.
"""
import shutil
from pathlib import Path

from .. import ffmpeg
from ..ffmpeg import FFmpegError
from . import VOICE_LEAD, scene_dir_name
from . import sfx, transitions
from .subtitles import build_ass, build_srt


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

    kinds = transitions.plan(job.get("transition") or "none", len(scenes) - 1, seed=job.get("id"))
    if any(kinds):  # có chuyển cảnh (Studio): xfade giữ nguyên mốc thời gian từng cảnh
        d = min(float(job.get("transition_duration") or 0.5), min(s["duration"] for s in scenes) / 2)
        log(f"Đang ghép các khung + chuyển cảnh ({transitions.TRANSITIONS.get(job.get('transition'), ('',))[0]})")
        chains, out = transitions.video_graph([s["duration"] for s in scenes], kinds, d, fps=int(job.get("fps") or 30))
        args = sum((["-i", f"scenes/{scene_dir_name(s['index'])}/scene.mp4"] for s in scenes), [])
        ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", out, "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "19", "-pix_fmt", "yuv420p", "tmp/video.mp4"], cwd=job_dir)
    else:
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
    args, chains, labels = [], [], []
    if "transition_sound" in job:  # chọn âm chuyển cảnh (Studio): đặt tại các điểm chuyển cảnh
        keys = transitions.sound_plan(job["transition_sound"], len(scenes) - 1, seed=job.get("id"))
        volume = float(job.get("transition_volume", 0.6))
        for off, key in zip(offsets[1:], keys):
            path = transitions.sound_file(key)
            if path is None:
                continue
            k = len(labels)
            args += ["-i", path]
            start = max(0.0, off - (transitions.SOUNDS[key][1] * 0.8 if key == "riser" else 0.12))
            chains.append(f"[{k}:a]volume={volume},adelay={int(start * 1000)}:all=1[s{k}]")
            labels.append(f"[s{k}]")
    else:  # mặc định (Tạo video): whoosh ở đầu mỗi cảnh
        whoosh = sfx.whoosh()
        for k, off in enumerate(offsets):
            args += ["-i", whoosh]
            chains.append(f"[{k}:a]volume=0.55,adelay={int(max(0.0, off - 0.12) * 1000)}:all=1[s{k}]")
            labels.append(f"[s{k}]")
    for cue in job.get("sfx_cues") or []:  # hậu kỳ AI: hiệu ứng gắn vào đúng từ trong lời dẫn (giây tuyệt đối)
        path = transitions.sound_file(cue.get("key", ""))
        if path is None:
            continue
        k = len(labels)
        args += ["-i", path]
        chains.append(f"[{k}:a]volume={float(cue.get('vol', 0.65))},adelay={int(float(cue['t']) * 1000)}:all=1[s{k}]")
        labels.append(f"[s{k}]")
    if not labels:  # không có âm chuyển cảnh nào → 1 đoạn im lặng để giữ khung lọc
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        chains.append(f"[0:a]atrim=0:0.1[s0]")
        labels.append("[s0]")
    if job.get("bgm", True):
        music = sfx.background_music(music_dir)
        n = len(labels)
        args += ["-stream_loop", "-1", "-i", music]
        duck = bool(job.get("duck_bgm"))
        chains.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume={job.get('bgm_volume', 0.12)},"
                      f"afade=t=in:d=1,afade=t=out:st={max(0.0, total - 1.5):.2f}:d=1.5[{'bg0' if duck else 'bg'}]")
        if duck:  # nhạc nền tự nhỏ lại khi có giọng nói (sidechain theo giọng đọc), to lại lúc nghỉ
            args += ["-i", "tmp/voice.wav"]
            chains.append(f"[{n + 1}:a]aresample=44100,aformat=channel_layouts=stereo[sc]")
            chains.append("[bg0][sc]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=450[bg]")
        labels.append("[bg]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[out]")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{total:.3f}",
                "-c:a", "pcm_s16le", "tmp/fx.wav"], cwd=job_dir)
    check_cancel()

    video_in = "tmp/video.mp4"
    try:  # luôn kèm file phụ đề final.srt cạnh video (đăng YouTube / Facebook, sửa tay) — kể cả khi không chèn chữ
        srt = build_srt(job)
        if srt:
            (job_dir / "final.srt").write_text(srt, "utf-8")
    except (OSError, KeyError, ValueError) as exc:
        log(f"Không tạo được file final.srt: {exc}", "warn")
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
