"""Chuyển cảnh (ffmpeg xfade) + âm thanh chuyển cảnh tự tổng hợp — dùng chung cho Studio, Ghép video (Workflow), compose().

Giữ NGUYÊN mốc thời gian từng cảnh: mỗi cảnh (trừ cảnh cuối) được kéo dài thêm `d` giây bằng khung cuối, rồi xfade
bắt đầu đúng tại điểm hết cảnh → cảnh sau vẫn bắt đầu đúng giây cũ, tổng thời lượng không đổi, giọng đọc / phụ đề /
âm thanh không bị lệch.
"""
import random
from pathlib import Path

from .. import ffmpeg
from ..paths import CACHE_DIR

# key → (tên hiển thị, kiểu xfade của ffmpeg); "none" = cắt thẳng, "random" = mỗi lần chuyển một kiểu ngẫu nhiên
TRANSITIONS = {
    "none": ("Cắt thẳng (không hiệu ứng)", ""),
    "fade": ("Hoà trộn (crossfade)", "fade"),
    "fadeblack": ("Mờ dần qua đen", "fadeblack"),
    "fadewhite": ("Loé trắng", "fadewhite"),
    "dissolve": ("Tan hạt (dissolve)", "dissolve"),
    "slideleft": ("Trượt sang trái", "slideleft"),
    "slideup": ("Trượt lên", "slideup"),
    "smoothleft": ("Lướt mượt sang trái", "smoothleft"),
    "wipeleft": ("Lau ngang", "wipeleft"),
    "circleopen": ("Mở vòng tròn", "circleopen"),
    "radial": ("Quét kim đồng hồ", "radial"),
    "zoomin": ("Phóng to", "zoomin"),
    "hblur": ("Nhoè ngang", "hblur"),
    "pixelize": ("Vỡ điểm ảnh", "pixelize"),
    "vertopen": ("Mở cửa dọc", "vertopen"),
    "random": ("Ngẫu nhiên (đổi kiểu mỗi lần)", ""),
}
RANDOM_POOL = ["fade", "fadeblack", "slideleft", "slideup", "smoothleft", "wipeleft", "circleopen", "zoomin", "dissolve",
               "radial"]
DURATIONS = [0.3, 0.5, 0.8, 1.0]

# key → (tên hiển thị, độ dài giây, chuỗi lọc lavfi tạo âm) — tổng hợp bằng ffmpeg, không cần file âm thanh
SOUNDS = {
    "none": ("Không có", 0, ""),
    "whoosh": ("Whoosh (gió lướt)", 0.7, "anoisesrc=d=0.7:c=pink:r=44100:a=0.5,highpass=f=300,lowpass=f=5000,"
                                         "afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35"),
    "swoosh": ("Swoosh nhanh", 0.35, "anoisesrc=d=0.35:c=white:r=44100:a=0.45,highpass=f=1200,lowpass=f=9000,"
                                     "afade=t=in:d=0.12,afade=t=out:st=0.12:d=0.23"),
    "riser": ("Riser (vút lên)", 0.9, "aevalsrc='0.35*sin(2*PI*(200*t+700*t*t))':s=44100:d=0.9,"
                                      "afade=t=in:d=0.6,afade=t=out:st=0.75:d=0.15"),
    "pop": ("Pop", 0.18, "aevalsrc='0.6*sin(2*PI*(900-2600*t)*t)*exp(-22*t)':s=44100:d=0.18"),
    "click": ("Click", 0.08, "aevalsrc='0.7*sin(2*PI*2400*t)*exp(-90*t)':s=44100:d=0.08"),
    "impact": ("Impact (bùm trầm)", 0.9, "aevalsrc='0.9*sin(2*PI*(70-30*t)*t)*exp(-4.5*t)':s=44100:d=0.9,lowpass=f=400"),
    "ding": ("Ding (chuông)", 1.2, "aevalsrc='0.3*(sin(2*PI*1320*t)+0.6*sin(2*PI*2640*t)+0.3*sin(2*PI*3960*t))*exp(-3.5*t)'"
                                   ":s=44100:d=1.2"),
    "random": ("Ngẫu nhiên", 0, ""),
}
SOUND_POOL = ["whoosh", "swoosh", "riser", "pop", "impact"]


def options() -> dict:
    """Danh sách lựa chọn cho giao diện."""
    return {"transitions": [{"value": k, "label": v[0]} for k, v in TRANSITIONS.items()],
            "durations": DURATIONS,
            "sounds": [{"value": k, "label": v[0]} for k, v in SOUNDS.items()]}


def clean(transition: str, duration, sound: str, volume) -> dict:
    try:
        d = float(duration)
    except (TypeError, ValueError):
        d = 0.5
    try:
        vol = float(volume)
    except (TypeError, ValueError):
        vol = 0.6
    return {"transition": transition if transition in TRANSITIONS else "fade",
            "transition_duration": min(max(d, 0.2), 1.5),
            "transition_sound": sound if sound in SOUNDS else "whoosh",
            "transition_volume": min(max(vol, 0.0), 1.5)}


def plan(transition: str, cuts: int, seed=None) -> list[str]:
    """Kiểu xfade cho từng chỗ chuyển cảnh ("" = cắt thẳng). Ngẫu nhiên: không lặp lại kiểu liền trước."""
    if transition == "random":
        rng, out = random.Random(seed), []
        for _ in range(cuts):
            out.append(rng.choice([t for t in RANDOM_POOL if not out or t != out[-1]]))
        return [TRANSITIONS[t][1] for t in out]
    return [TRANSITIONS.get(transition, TRANSITIONS["fade"])[1]] * cuts


def sound_plan(sound: str, cuts: int, seed=None) -> list[str]:
    if sound == "random":
        rng = random.Random(seed)
        return [rng.choice(SOUND_POOL) for _ in range(cuts)]
    return [sound if sound in SOUNDS and sound not in ("none", "random") else ""] * cuts


def sound_file(key: str) -> Path | None:
    """File wav của âm chuyển cảnh (tạo một lần, lưu cache)."""
    if not key or key not in SOUNDS or not SOUNDS[key][2]:
        return None
    path = CACHE_DIR / f"sfx_{key}.wav"
    if not path.exists():
        ffmpeg.run(["-f", "lavfi", "-i", SOUNDS[key][2], "-ac", "2", "-ar", "44100", path])
    return path


def video_graph(durations: list[float], kinds: list[str], d: float, fps: int = 30, pre: str = "") -> tuple[list[str], str]:
    """Filter_complex nối các input video [0:v]..[n-1:v] (đã cùng khung hình) có chuyển cảnh.
    Trả về (các chuỗi lọc, nhãn đầu ra). kinds[k] = kiểu xfade giữa cảnh k và k+1 ("" = cắt thẳng).
    Mỗi cảnh được cắt đúng durations[k] (xfade cần fps cố định + cùng định dạng điểm ảnh).
    pre: bộ lọc chạy trước cho mọi input (vd. "scale=…,pad=…," để đưa về cùng khung hình), kết thúc bằng dấu phẩy."""
    n = len(durations)
    chains, labels = [], []
    for k in range(n):  # cảnh có chuyển cảnh phía sau → kéo dài thêm d giây bằng khung cuối (giữ mốc thời gian)
        pad = d if k < n - 1 and kinds[k] else 0
        # kéo dài (khung cuối) TRƯỚC rồi mới cắt đúng độ dài: tpad đặt sau trim — hoặc sau setpts — không có tác dụng
        chains.append(f"[{k}:v]{pre}tpad=stop_mode=clone:stop_duration={pad + 1:.3f},"
                      f"trim=duration={durations[k] + pad:.3f},setpts=PTS-STARTPTS,"
                      f"fps={fps},format=yuv420p,setsar=1[p{k}]")  # fps cuối cùng: xfade cần tốc độ khung cố định
        labels.append(f"[p{k}]")
    cur, offset = labels[0], 0.0
    for k in range(1, n):
        offset += durations[k - 1]
        kind = kinds[k - 1]
        out = f"[x{k}]"
        if kind:
            chains.append(f"{cur}{labels[k]}xfade=transition={kind}:duration={d:.3f}:offset={offset:.3f}{out}")
        else:
            chains.append(f"{cur}{labels[k]}concat=n=2:v=1:a=0{out}")
        cur = out
    return chains, cur


def sound_track(offsets: list[float], keys: list[str], total: float, volume: float, out: Path, cwd: Path | None = None,
                lead: float = 0.12) -> bool:
    """Ghi file wav chỉ chứa âm chuyển cảnh đặt tại các mốc offsets (giây). Trả về False nếu không có âm nào."""
    args, chains, labels = [], [], []
    for off, key in zip(offsets, keys):
        path = sound_file(key)
        if path is None:
            continue
        k = len(labels)
        args += ["-i", str(path)]
        # âm bắt đầu hơi trước điểm chuyển (riser cần dồn lên tới điểm cắt)
        start = max(0.0, off - (SOUNDS[key][1] * 0.8 if key == "riser" else lead))
        chains.append(f"[{k}:a]volume={volume},adelay={int(start * 1000)}:all=1[s{k}]")
        labels.append(f"[s{k}]")
    if not labels:
        return False
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[out]")
    ffmpeg.run([*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", f"{total:.3f}",
                "-c:a", "pcm_s16le", out], cwd=cwd)
    return True
