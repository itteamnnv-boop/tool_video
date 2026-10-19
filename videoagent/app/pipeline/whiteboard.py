"""Video vẽ tay bảng trắng (whiteboard) từ lời dẫn / phụ đề SRT, dùng bộ dựng của
geeklee/srt-whiteboard-animation (MIT): mỗi cảnh = 1 ảnh line-art nền giấy kem → tay cầm bút vẽ lần lượt từng vùng đúng
lúc câu phụ đề tương ứng được đọc.

Repo gốc là “skill” cho AI agent (agent tự nhìn ảnh để khoanh vùng). App tự động hoá phần đó:
1. Ảnh line-art: model ảnh vẽ theo quy chuẩn của skill (nền #F5EBD7, nét xám đậm, chỉ điểm xuyết đỏ / cam / xanh,
   không chữ) và xếp các cụm hình theo đúng thứ tự câu, có khoảng trống giữa các cụm.
2. Khoanh vùng tự động (OpenCV): tìm các cụm nét trên nền giấy → chia thành N vùng theo thứ tự đọc → mỗi vùng gắn một
   câu, bắt đầu đúng giây câu đó → annotation.json đúng định dạng của skill.
3. Dựng: scripts/render_stream_whiteboard.py của skill (venv riêng: opencv, numpy, PyAV, Pillow).

Cài đặt: lần đầu tải repo (commit cố định) từ GitHub vào DATA_DIR/tools/srt-whiteboard rồi chạy scripts/prepare_env.py
(tạo .venv riêng trong thư mục đó). Cần Python 3 trong máy.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from ..paths import DATA_DIR

REPO = "geeklee/srt-whiteboard-animation"
COMMIT = "696a7243c0e6ffb6827676e539c2ca5ebae2bf6b"
TOOL_DIR = DATA_DIR / "tools" / "srt-whiteboard"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_REGIONS = 4  # số vùng vẽ tối đa mỗi cảnh (ảnh rõ, tay vẽ không quá vụn)
PAPER = "#F5EBD7"
STYLE = (f"Hand-drawn whiteboard line-art illustration on warm beige old paper (solid background {PAPER}). Dark grey "
         "pencil / marker sketch lines, clean outlines, simple flat light shading. Only small conceptual accents in red, "
         "orange or blue — no other strong colors, no gradients, no complex textures, no photo realism. "
         "NO text, no letters, no numbers, no captions, no watermark, no logos. "
         "Each group is a separate cluster of drawings with clear EMPTY paper between groups (do not overlap).")


class WhiteboardError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- cài đặt
def _venv_python() -> Path:
    return TOOL_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _system_python() -> str | None:
    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        return str(exe)
    return shutil.which("python") or shutil.which("python3") or shutil.which("py")


def status() -> dict:
    return {"installed": _venv_python().is_file() and (TOOL_DIR / "scripts" / "render_stream_whiteboard.py").is_file(),
            "python": bool(_system_python()), "commit": COMMIT[:7]}


def ensure_installed(log) -> Path:
    """Tải repo (zip, commit cố định) + tạo venv riêng với opencv / numpy / PyAV / Pillow. Trả về python của venv."""
    if status()["installed"]:
        return _venv_python()
    python = _system_python()
    if not python:
        raise WhiteboardError("Không tìm thấy Python 3 trong máy — cài Python (python.org) rồi mở lại app")
    if not (TOOL_DIR / "scripts" / "render_stream_whiteboard.py").is_file():
        log(f"Đang tải bộ dựng whiteboard ({REPO}@{COMMIT[:7]}, MIT)…")
        url = f"https://codeload.github.com/{REPO}/zip/{COMMIT}"
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — URL cố định
                data = resp.read()
        except OSError as exc:
            raise WhiteboardError(f"Không tải được {REPO}: {exc}") from exc
        tmp = TOOL_DIR.with_name("srt-whiteboard.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            root = zf.namelist()[0].split("/")[0]
            zf.extractall(tmp)
        shutil.rmtree(TOOL_DIR, ignore_errors=True)
        (tmp / root).replace(TOOL_DIR)
        shutil.rmtree(tmp, ignore_errors=True)
    log("Đang tạo môi trường Python riêng cho bộ dựng whiteboard (opencv, numpy, PyAV, Pillow — lần đầu)…")
    proc = subprocess.run([python, str(TOOL_DIR / "scripts" / "prepare_env.py")], cwd=TOOL_DIR, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1800, creationflags=NO_WINDOW,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})  # script in chữ Trung Quốc
    if proc.returncode != 0 or not _venv_python().is_file():
        raise WhiteboardError(f"Cài môi trường whiteboard lỗi: {(proc.stdout + proc.stderr).strip()[-600:]}")
    log("Đã cài bộ dựng whiteboard", "ok")
    return _venv_python()


def _run(args: list, cwd: Path, timeout: int, check_cancel=None) -> str:
    log_path = Path(cwd) / ".wb.log"
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen([str(_venv_python()), *args], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        deadline = time.time() + timeout
        try:
            while proc.poll() is None:
                if check_cancel:
                    check_cancel()
                if time.time() > deadline:
                    raise WhiteboardError(f"Dựng whiteboard quá {timeout // 60} phút — đã dừng")
                time.sleep(0.4)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            raise
    out = log_path.read_text("utf-8", errors="replace")
    if proc.returncode != 0:
        raise WhiteboardError(out.strip()[-800:] or f"exit {proc.returncode}")
    return out


# ---------------------------------------------------------------------------- SRT
TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def parse_srt(text: str) -> list[dict]:
    """[{start, end, text}] (giây) từ nội dung SRT."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", (text or "").strip()):
        lines = [x.strip() for x in block.strip().splitlines() if x.strip()]
        idx = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if idx is None:
            continue
        times = TIME_RE.findall(lines[idx])
        if len(times) < 2:
            continue
        sec = lambda t: int(t[0]) * 3600 + int(t[1]) * 60 + int(t[2]) + int(t[3].ljust(3, "0")) / 1000  # noqa: E731
        body = re.sub(r"<[^>]+>|\{[^}]*\}", "", " ".join(lines[idx + 1:])).strip()
        if body:
            cues.append({"start": round(sec(times[0]), 3), "end": round(sec(times[1]), 3), "text": body})
    return sorted(cues, key=lambda c: c["start"])


def group_scenes(cues: list[dict], target: float = 10.0, max_len: float = 16.0) -> list[list[dict]]:
    """Gộp câu phụ đề thành cảnh ~target giây, mỗi cảnh ≤ MAX_REGIONS*2 câu."""
    scenes, cur = [], []
    for c in cues:
        if cur and (c["end"] - cur[0]["start"] > max_len or len(cur) >= MAX_REGIONS * 2
                    or c["start"] - cur[0]["start"] >= target):
            scenes.append(cur)
            cur = []
        cur.append(c)
    if cur:
        scenes.append(cur)
    return scenes


def regions_for(lines: list[dict]) -> list[dict]:
    """Gộp các câu của một cảnh thành ≤ MAX_REGIONS nhóm (mỗi nhóm = 1 vùng vẽ). lines: [{start, end, text}] (giây,
    tính từ đầu cảnh)."""
    n = min(len(lines), MAX_REGIONS)
    groups = [lines[round(i * len(lines) / n): round((i + 1) * len(lines) / n)] for i in range(n)] if n else []
    return [{"start": g[0]["start"], "end": g[-1]["end"], "text": " ".join(x["text"] for x in g)} for g in groups if g]


def line_art_prompt(groups: list[dict], *, aspect: str, hint: str = "") -> str:
    order = "top to bottom" if aspect in ("9:16", "3:4", "4:5") else "left to right"
    parts = "\n".join(f"{i}. {g['text']}" for i, g in enumerate(groups, 1))
    return (f"{STYLE}\nComposition: {len(groups)} separate groups of drawings arranged from {order}, in this exact "
            f"order, each group illustrating one idea (draw simple objects / people / icons that show the idea — the "
            f"sentences are in Vietnamese, do NOT write them):\n{parts}"
            + (f"\nVisual hint for the whole scene: {hint}" if hint else ""))


# ---------------------------------------------------------------------------- khoanh vùng tự động (chạy trong venv)
ANNOTATE = r'''
import json, sys
import cv2, numpy as np
img_path, groups_path, out_path, total_ms = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
groups = json.load(open(groups_path, encoding="utf-8"))
img = cv2.imread(img_path)
h, w = img.shape[:2]
paper = np.median(img.reshape(-1, 3)[::97], axis=0)
diff = np.abs(img.astype(np.int16) - paper.astype(np.int16)).max(axis=2)
mask = (diff > 38).astype(np.uint8) * 255
k = max(3, int(min(w, h) * 0.02))
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
mask = cv2.dilate(mask, np.ones((k, k), np.uint8))
n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
comps = [(stats[i], cents[i]) for i in range(1, n) if stats[i][4] > w * h * 0.002]
vertical = h > w
axis = 1 if vertical else 0
want = len(groups)
boxes = []
if want and len(comps) >= want:
    comps.sort(key=lambda c: c[1][axis])
    centers = [c[1][axis] for c in comps]
    gaps = sorted(range(1, len(centers)), key=lambda i: centers[i] - centers[i - 1], reverse=True)[:want - 1]
    cuts = [0] + sorted(gaps) + [len(comps)]
    for a, b in zip(cuts, cuts[1:]):
        ss = [c[0] for c in comps[a:b]]
        boxes.append([min(s[0] for s in ss), min(s[1] for s in ss), max(s[0] + s[2] for s in ss), max(s[1] + s[3] for s in ss)])
else:
    if comps:
        x0 = min(c[0][0] for c in comps); y0 = min(c[0][1] for c in comps)
        x1 = max(c[0][0] + c[0][2] for c in comps); y1 = max(c[0][1] + c[0][3] for c in comps)
    else:
        x0, y0, x1, y1 = 0, 0, w, h
    for i in range(want):
        if vertical:
            boxes.append([x0, y0 + (y1 - y0) * i // want, x1, y0 + (y1 - y0) * (i + 1) // want])
        else:
            boxes.append([x0 + (x1 - x0) * i // want, y0, x0 + (x1 - x0) * (i + 1) // want, y1])
pad = int(min(w, h) * 0.015)
elements = []
for i, (g, b) in enumerate(zip(groups, boxes), 1):
    x0, y0 = max(0, b[0] - pad), max(0, b[1] - pad)
    x1, y1 = min(w, b[2] + pad), min(h, b[3] + pad)
    start = max(0, int(g["start"] * 1000))
    dur = int(max(1200, min((g["end"] - g["start"]) * 1000, total_ms - start - 200)))
    cx = (x0 + x1) // 2
    elements.append({"id": f"g{i}", "label": f"Vung {i}", "sequence": i, "narrativeRole": "auto",
                     "subtitle": g["text"], "type": "structure",
                     "region": {"x": int(x0), "y": int(y0), "width": int(x1 - x0), "height": int(y1 - y0)},
                     "reveal": {"direction": "top_to_bottom", "startMs": start, "durationMs": dur,
                                "maskPaddingPx": 22, "protectedRegions": []},
                     "handPath": {"start": [int(cx), int(y0 + 10)], "end": [int(cx), int(y1 - 10)], "easing": "easeInOut"}})
json.dump({"sceneId": "scene", "canvas": {"width": w, "height": h}, "storyBasis": " ".join(g["text"] for g in groups),
           "sceneDurationMs": total_ms, "elements": elements}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"regions={len(elements)} comps={len(comps)}")
'''


QUALITY = {"fast": 1080, "hd": 1920}  # cạnh dài tối đa khi dựng (hd ~3 lần lâu hơn)
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


def render_scene(image: Path, groups: list[dict], duration: float, out: Path, *, fps: int = 30, check_cancel=None,
                 ink_path: str = "grid", quality: str = "fast", hand: bool = True) -> Path:
    """Khoanh vùng tự động + dựng 1 cảnh whiteboard dài `duration` giây → out (mp4, không tiếng).
    groups: [{start, end, text}] — giây tính từ đầu cảnh, ≤ MAX_REGIONS nhóm."""
    work = out.parent / f"{out.stem}_wb"
    work.mkdir(parents=True, exist_ok=True)
    (work / "annotate.py").write_text(ANNOTATE, "utf-8")
    png = work / "scene.png"
    if image.suffix.lower() == ".png":
        shutil.copy2(image, png)
    else:  # skill đọc PNG — chuyển định dạng bằng OpenCV của venv
        _run(["-c", f"import cv2, sys; cv2.imwrite(sys.argv[2], cv2.imread(sys.argv[1]))", str(image), str(png)], work, 120)
    (work / "groups.json").write_text(json.dumps(groups, ensure_ascii=False), "utf-8")
    total_ms = int(duration * 1000)
    ann = work / "scene.annotation.json"
    _run([str(work / "annotate.py"), str(png), str(work / "groups.json"), str(ann), str(total_ms)], work, 180, check_cancel)
    raw = work / "scene-whiteboard.mp4"
    _run([str(TOOL_DIR / "scripts" / "render_stream_whiteboard.py"), str(png), str(ann), str(raw),
          str(TOOL_DIR / "assets" / "drawing-hand.png"), "--total-ms", str(total_ms), "--fps", str(fps),
          "--ink-path", ink_path, "--color-fill", "contour-wipe", "--cap-long-edge", str(QUALITY.get(quality, 1080)),
          *([] if hand else ["--bare-tip"])], work, 3600, check_cancel)
    if not raw.is_file():
        found = sorted(work.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise WhiteboardError("Bộ dựng whiteboard không tạo ra video")
        raw = found[-1]
    shutil.copy2(raw, out)
    return out


# ---------------------------------------------------------------------------- SRT / kịch bản → video hoàn chỉnh
LETTERS = re.compile(r"[0-9A-Za-z\u00C0-\u024F\u1E00-\u1EFF]")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
MAX_CUE_WORDS = 10  # câu dài hơn → cắt ở dấu phẩy / chấm phẩy, không thì sau ~10 từ


def _pieces(text: str) -> list[str]:
    """Kịch bản → các câu phụ đề (giữ nguyên chữ + dấu câu gốc)."""
    out = []
    for sentence in (s.strip() for s in SENTENCE_END.split(text or "")):
        toks = sentence.split()
        while len(toks) > MAX_CUE_WORDS:
            cut = next((i + 1 for i in range(MAX_CUE_WORDS - 1, 2, -1) if toks[i].endswith((",", ";", ":"))), None)
            if cut is None:  # không có dấu phẩy: chia đôi cho cân (tránh sót 1–2 từ lẻ ở dòng sau)
                cut = MAX_CUE_WORDS if len(toks) > 2 * MAX_CUE_WORDS else (len(toks) + 1) // 2
            out.append(" ".join(toks[:cut]))
            toks = toks[cut:]
        if toks:
            out.append(" ".join(toks))
    return out


def _align(pieces: list[str], words: list[dict]) -> list[dict]:
    """Gắn mốc thời gian từng từ (edge-tts, không kèm dấu câu) vào các câu gốc — khớp theo số chữ cái."""
    count = lambda s: len(LETTERS.findall(s))  # noqa: E731
    cues, wi = [], 0
    for piece in pieces:
        need, got, first = count(piece), 0, wi
        while wi < len(words) and got < need:
            got += count(words[wi]["text"])
            wi += 1
        if wi > first:
            cues.append({"start": round(words[first]["start"], 3), "end": round(words[wi - 1]["end"], 3), "text": piece})
    if cues and wi < len(words):  # còn sót từ cuối → kéo dài câu cuối
        cues[-1]["end"] = round(words[-1]["end"], 3)
    return cues


def cues_from_script(text: str, voice: str, rate: str, audio_out: Path) -> list[dict]:
    """Kịch bản thường (không phải SRT): đọc bằng giọng AI → câu phụ đề theo câu gốc, mốc lấy từ từng từ được đọc."""
    from .subtitles import _lines
    from .tts import synthesize

    words = synthesize(" ".join(text.split()), voice, rate, audio_out)
    cues = _align(_pieces(text), words)
    if cues:
        return cues
    return [{"start": round(line[0]["start"], 3), "end": round(line[-1]["end"], 3),
             "text": " ".join(w["text"] for w in line)} for line in _lines(words)]


def make_srt(text: str, voice: str, rate: str) -> dict:
    """Tự tạo SRT từ kịch bản: giọng AI đọc cả bài → file narration.mp3 + script.srt (mốc khớp đúng giọng đọc)."""
    import uuid
    from datetime import datetime

    from .subtitles import srt_text

    text = (text or "").strip()
    if not text:
        raise WhiteboardError("Chưa có kịch bản để tạo SRT")
    if is_srt(text):
        raise WhiteboardError("Nội dung đã là SRT")
    folder = DATA_DIR / "whiteboard" / "srt" / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True, exist_ok=True)
    cues = cues_from_script(text, voice, rate, folder / "narration.mp3")
    if not cues:
        raise WhiteboardError("Giọng đọc không trả về mốc thời gian — thử lại")
    srt = srt_text(cues)
    (folder / "script.srt").write_text(srt, "utf-8")
    return {"text": srt, "audio": str(folder / "narration.mp3"), "srt": str(folder / "script.srt"), "cues": len(cues)}


def is_srt(text: str) -> bool:
    return bool(TIME_RE.search(text or "")) and "-->" in (text or "")


def _ass(cues: list[dict], width: int, height: int) -> str:
    from .subtitles import _escape, _ts

    size = round(min(width, height) * 0.05)
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding",
            f"Style: Sub,Arial,{size},&H00303030,&H00303030,&H00D7EBF5,&H00D7EBF5,-1,0,0,0,100,100,0,0,3,{max(6, size // 4)},0,2,"
            f"{width // 14},{width // 14},{round(height * 0.05)},1", "",
            "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    return "\n".join(head + [f"Dialogue: 0,{_ts(c['start'])},{_ts(c['end'])},Sub,,0,0,0,,{_escape(c['text'])}"
                             for c in cues]) + "\n"


def build_video(cues: list[dict], out_dir: Path, *, make_image, aspect: str = "16:9", audio: Path | None = None,
                voice: str = "vi-VN-HoaiMyNeural", rate: str = "+0%", subtitles: bool = True, quality: str = "fast",
                hand: bool = True, hint: str = "", log=None, check_cancel=None, progress=None) -> Path:
    """cues → video whiteboard hoàn chỉnh (out_dir/final.mp4). make_image(prompt, aspect, path) → Path ảnh line-art.
    Tiếng: file audio (giọng có sẵn, khớp mốc SRT) hoặc giọng AI đọc từng câu đúng mốc. Mốc thời gian giữ nguyên SRT."""
    from .. import ffmpeg
    from .tts import synthesize

    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a, **k: None)
    if not cues:
        raise WhiteboardError("Không có câu phụ đề nào")
    ensure_installed(log)
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = SIZES.get(aspect, SIZES["16:9"])
    scenes = group_scenes(cues)
    starts = [0.0] + [s[0]["start"] for s in scenes[1:]]
    total = max(cues[-1]["end"] + 1.0, (ffmpeg.media_duration(audio) if audio else 0))
    ends = starts[1:] + [total]
    log(f"Whiteboard: {len(cues)} câu → {len(scenes)} cảnh · {total:.0f} giây · {aspect}")
    clips = []
    for i, (scene, t0, t1) in enumerate(zip(scenes, starts, ends), 1):
        if check_cancel:
            check_cancel()
        groups = regions_for([{"start": max(0.0, c["start"] - t0), "end": c["end"] - t0, "text": c["text"]} for c in scene])
        progress((i - 1) / len(scenes), f"Cảnh {i}/{len(scenes)}: vẽ line-art")
        image = make_image(line_art_prompt(groups, aspect=aspect, hint=hint), aspect, out_dir / f"scene{i:02d}.png")
        progress((i - 0.5) / len(scenes), f"Cảnh {i}/{len(scenes)}: dựng tay vẽ")
        clip = render_scene(Path(image), groups, t1 - t0, out_dir / f"scene{i:02d}.mp4", check_cancel=check_cancel,
                            quality=quality, hand=hand)
        clips.append(clip)
        log(f"Cảnh {i}/{len(scenes)} xong ({t1 - t0:.1f}s, {len(groups)} vùng)", "ok")
    progress(0.95, "Ghép cảnh, giọng đọc, phụ đề")
    fit = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:"
           f"color=0x{PAPER[1:]},setsar=1,fps=30,format=yuv420p")
    args = sum((["-i", c] for c in clips), [])
    chain = ";".join(f"[{k}:v]{fit}[v{k}]" for k in range(len(clips))) + ";" + "".join(f"[v{k}]" for k in range(len(clips)))
    ffmpeg.run([*args, "-filter_complex", chain + f"concat=n={len(clips)}:v=1:a=0[v]", "-map", "[v]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", out_dir / "video.mp4"])
    if audio is None:  # giọng AI đọc từng câu đúng mốc SRT
        parts, chains = [], []
        for k, c in enumerate(cues):
            part = out_dir / f"cue{k:03d}.mp3"
            synthesize(c["text"], voice, rate, part)
            parts += ["-i", part]
            chains.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={int(c['start'] * 1000)}:all=1[a{k}]")
        chains.append("".join(f"[a{k}]" for k in range(len(cues))) + f"amix=inputs={len(cues)}:normalize=0,apad[a]")
        audio = out_dir / "voice.wav"
        ffmpeg.run([*parts, "-filter_complex", ";".join(chains), "-map", "[a]", "-t", f"{total:.3f}", audio])
    vf = []
    if subtitles:
        (out_dir / "subs.ass").write_text(_ass(cues, width, height), "utf-8")
        vf = ["-vf", "subtitles=subs.ass"]
    from .subtitles import srt_text

    (out_dir / "final.srt").write_text(srt_text(cues), "utf-8")  # file phụ đề kèm video
    final = out_dir / "final.mp4"
    ffmpeg.run(["-i", "video.mp4", "-i", Path(audio).resolve(), *vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
                "-movflags", "+faststart", "final.mp4"], cwd=out_dir)
    return final


def image_maker(engine: str, settings, *, show_browser: bool = False, log=None, check_cancel=None):
    """make_image(prompt, aspect, path) cho build_video: gọi engine tạo ảnh của app (1 ảnh / cảnh)."""
    from ..llm.image_engines import ENGINES as IMAGE_ENGINES
    from ..llm.image_engines import fit_aspect, save_images
    from ..llm.image_engines import generate as generate_image

    if engine not in IMAGE_ENGINES:
        raise WhiteboardError(f"Engine ảnh không hợp lệ: {engine}")
    spec = IMAGE_ENGINES[engine]

    def make_image(prompt: str, aspect: str, path: Path) -> Path:
        want = aspect if aspect in spec["aspects"] else spec["aspects"][0]
        datas = generate_image(engine, prompt, aspect=want, count=1, quality="high", images=[], settings=settings,
                               show_browser=show_browser, log=log or (lambda *a, **k: None), check_cancel=check_cancel)
        if not datas:
            raise WhiteboardError(f"{spec['name']} không trả ảnh")
        tmp = path.parent / f"_{path.stem}"
        tmp.mkdir(parents=True, exist_ok=True)
        saved = save_images(datas[:1], tmp)[0]
        fit_aspect(saved, aspect)
        target = path.with_suffix(saved.suffix)
        shutil.move(str(saved), target)
        shutil.rmtree(tmp, ignore_errors=True)
        return target

    return make_image


def load_cues(text: str, work_dir: Path, *, voice: str, rate: str, audio: Path | None = None) -> tuple[list, Path | None]:
    """Nội dung SRT → câu phụ đề (giữ mốc; audio đính kèm nếu có). Kịch bản thường → giọng AI đọc,
    mốc lấy theo từng từ, trả về luôn file giọng đọc để ghép."""
    text = (text or "").strip()
    if not text:
        raise WhiteboardError("Chưa có nội dung SRT hoặc kịch bản")
    if is_srt(text):
        cues = parse_srt(text)
        if not cues:
            raise WhiteboardError("File SRT không đọc được câu nào")
        return cues, audio
    work_dir.mkdir(parents=True, exist_ok=True)
    narration = work_dir / "narration.mp3"
    return cues_from_script(text, voice, rate, narration), narration


def read_srt_file(path: str | Path) -> str:
    """Đọc file .srt (UTF-8, UTF-8 BOM hoặc UTF-16)."""
    raw = Path(path).read_bytes()
    if raw.startswith(bytes([0xFF, 0xFE])) or raw.startswith(bytes([0xFE, 0xFF])):  # BOM UTF-16
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", "replace")
