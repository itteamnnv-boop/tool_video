"""Hậu kỳ đồ hoạ động bằng Remotion (React → video), dựng NGAY TRÊN MÁY.

Luồng (Hậu kỳ → ✨ Hậu kỳ AI → Kiểu: Remotion):
1. compose() ghép video như thường nhưng KHÔNG chèn phụ đề ASS → final.mp4 (đã có giọng, nhạc, SFX).
2. Model chat (mặc định Claude trình duyệt) chỉ trả KẾ HOẠCH DỰNG dạng JSON (màu, kiểu phụ đề, hook, tiêu đề cảnh, chữ nhấn,
   zoom nhấn, thẻ kết) — app kiểm tra + giới hạn mọi giá trị. Không chạy mã do model viết → dựng ổn định.
3. Dự án Remotion cố định (assets/remotion_post: PostVideo.tsx) nhận props.json → `remotion render` → final.mp4.

Cài đặt: lần đầu chép dự án mẫu vào DATA_DIR/tools/remotion + `npm install` (phiên bản cố định) + tải Chrome dựng hình.
Cần Node.js 18+. Remotion tự kèm ffmpeg riêng.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import ffmpeg
from ..osutil import kill_tree
from ..paths import ASSETS_DIR, DATA_DIR
from . import hyperframes as _hf
from .hyperframes import FONT_FILES, nfc

timeline_data = _hf.timeline_data  # dùng chung mốc phụ đề / cảnh với HyperFrames

TEMPLATE_DIR = ASSETS_DIR / "remotion_post"
TOOLS_DIR = DATA_DIR / "tools" / "remotion"
COMP_ID = "PostVideo"
NODE_MIN = 18
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_HINT = "Cần Node.js 18+ (https://nodejs.org) rồi mở lại app"
STAMP = ".template-hash"

CAPTION_STYLES = {"karaoke": "từng từ sáng dần theo giọng đọc", "pop": "cả dòng bật ra",
                  "box": "chữ trong ô nền, từ khoá đổi nền", "bounce": "từng từ nảy ra đúng lúc đọc"}
HOOK_STYLES = {"slam": "đập mạnh vào giữa", "slide": "trượt từ trái", "typewriter": "gõ chữ"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class RemotionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- cài đặt / gọi CLI
def _env() -> dict:
    return {**os.environ, "REMOTION_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}


def _cli() -> Path:
    return TOOLS_DIR / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")


def _template_hash() -> str:
    h = hashlib.sha1()
    for f in sorted(p for p in TEMPLATE_DIR.rglob("*") if p.is_file()):
        h.update(f.relative_to(TEMPLATE_DIR).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def _deps_hash() -> str:
    return hashlib.sha1((TEMPLATE_DIR / "package.json").read_bytes()).hexdigest()


def status() -> dict:
    """Tình trạng cho giao diện: có Node chưa, đã cài Remotion chưa."""
    node = shutil.which("node")
    version = ""
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15,
                                     creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
    major = int(re.sub(r"\D.*", "", version.lstrip("v")) or 0) if version else 0
    pkg = json.loads((TEMPLATE_DIR / "package.json").read_text("utf-8"))
    return {"node": version, "node_ok": major >= NODE_MIN, "installed": _cli().is_file(),
            "version": pkg["dependencies"]["remotion"]}


def ensure_installed(log) -> Path:
    st = status()
    if not st["node_ok"]:
        raise RemotionError(f"Chưa có Node.js {NODE_MIN}+ (đang: {st['node'] or 'không có'}) — {INSTALL_HINT}")
    stamp = TOOLS_DIR / STAMP
    current = _template_hash()
    if st["installed"] and stamp.is_file() and stamp.read_text("utf-8").strip() == current:
        return _cli()
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    old_pkg = (TOOLS_DIR / "package.json").read_bytes() if (TOOLS_DIR / "package.json").is_file() else b""
    shutil.rmtree(TOOLS_DIR / "src", ignore_errors=True)
    shutil.copytree(TEMPLATE_DIR / "src", TOOLS_DIR / "src")
    for name in ("package.json", "tsconfig.json"):
        shutil.copy2(TEMPLATE_DIR / name, TOOLS_DIR / name)
    if not st["installed"] or hashlib.sha1(old_pkg).hexdigest() != _deps_hash():
        npm = shutil.which("npm")
        if not npm:
            raise RemotionError(f"Không tìm thấy npm — {INSTALL_HINT}")
        log(f"Đang cài Remotion {st['version']} (lần đầu, cần internet, ~1–3 phút)…")
        proc = subprocess.run([npm, "install", "--no-fund", "--no-audit"], cwd=TOOLS_DIR, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_env(), timeout=900, creationflags=NO_WINDOW)
        if proc.returncode != 0 or not _cli().is_file():
            raise RemotionError(f"Cài Remotion lỗi: {(proc.stderr or proc.stdout).strip()[-600:]}")
        log("Đang tải Chrome dùng để dựng video (lần đầu)…")
        res = _run(["browser", "ensure"], TOOLS_DIR, timeout=900)
        if res.returncode != 0:
            raise RemotionError(f"Tải Chrome cho Remotion lỗi: {res.stdout.strip()[-600:]}")
        log("Đã cài Remotion", "ok")
    stamp.write_text(current, "utf-8")
    return _cli()


def _run(args: list, cwd: Path, timeout: int = 600, check_cancel=None, log_dir: Path | None = None) -> subprocess.CompletedProcess:
    """Chạy CLI remotion; check_cancel() được gọi định kỳ — huỷ thì dừng cả cây tiến trình (node → Chrome)."""
    log_path = Path(log_dir or cwd) / f".remotion-{args[0]}.log"  # ghi ra file — không kẹt PIPE khi CLI in nhiều
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen([str(_cli()), *args], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                env=_env(), creationflags=NO_WINDOW, start_new_session=os.name != "nt")
        deadline = time.time() + timeout
        try:
            while proc.poll() is None:
                if check_cancel:
                    check_cancel()
                if time.time() > deadline:
                    raise RemotionError(f"Remotion chạy quá {timeout // 60} phút — đã dừng")
                time.sleep(0.5)
        except BaseException:
            if proc.poll() is None:
                kill_tree(proc)
            raise
    out = re.sub(r"\x1b\[[0-9;]*m", "", log_path.read_text("utf-8", errors="replace"))
    return subprocess.CompletedProcess(args, proc.returncode, out, "")


# ---------------------------------------------------------------------------- kế hoạch dựng (model chọn, app kiểm)
def build_prompt(scenes: list, captions: list, *, width: int, height: int, duration: float, hook: str,
                 brand: str = "") -> str:
    preview = "\n".join(f"- Cảnh {s['index']} [{s['start']:.1f}s → {s['end']:.1f}s] {s['headline']}: {s['narration']}"
                        for s in scenes)
    keys = sorted({w["t"] for c in captions for w in c["words"] if w.get("k")})
    lines = "\n".join(f"  [{c['start']:.1f}s] " + " ".join(w["t"] for w in c["words"]) for c in captions[:60])
    cap_styles = "; ".join(f"{k} = {v}" for k, v in CAPTION_STYLES.items())
    hook_styles = "; ".join(f"{k} = {v}" for k, v in HOOK_STYLES.items())
    return f"""Bạn là biên tập viên hậu kỳ video ngắn TikTok / Reels. Video {width}×{height}, dài {duration:.1f} giây, đã có
hình + giọng đọc + nhạc. App dựng lớp đồ hoạ động bằng Remotion với các thành phần CÓ SẴN; bạn chỉ chọn KẾ HOẠCH DỰNG.

Nội dung từng cảnh:
{preview}

Phụ đề (app tự hiện đúng nhịp giọng đọc{', từ khoá tô màu nhấn' if keys else ''}):
{lines or '  (video không có lời)'}
Từ khoá: {', '.join(keys[:40]) or '(chưa có)'}
Hook gợi ý: “{hook}”. {f'Thương hiệu / sản phẩm: {brand}.' if brand else ''}

Trả về MỘT object JSON trong một khối code ```json (không giải thích thêm):
{{
  "theme": {{"accent": "#RRGGBB màu nhấn nổi bật", "text": "#RRGGBB màu chữ", "stroke": "#RRGGBB viền chữ (tối)",
            "panel": "#RRGGBBAA nền ô chữ bán trong suốt"}},
  "caption_style": "một trong: {cap_styles}",
  "caption_y": 0.55–0.78 (vị trí dòng phụ đề theo chiều cao, mặc định 0.68),
  "hook": {{"text": "câu hook ≤ 8 từ, gây tò mò", "style": "một trong: {hook_styles}", "duration": 1.5–3.5}},
  "titles": [{{"at": giây, "duration": 1.2–3, "text": "tiêu đề ngắn ≤ 6 từ cho cảnh"}}],
  "callouts": [{{"at": giây, "duration": 0.8–2, "text": "con số / chữ nhấn cực ngắn ≤ 3 từ, VD -30%, FREESHIP"}}],
  "zooms": [{{"at": giây, "duration": 0.5–2, "scale": 1.05–1.25}}],
  "end_card": {{"title": "câu chốt ≤ 8 từ", "cta": "lời kêu gọi ≤ 4 từ, VD Mua ngay", "seconds": 0–3.5}},
  "progress": true hoặc false (thanh tiến độ trên cùng)
}}

Quy tắc:
- Tiếng Việt có dấu, đúng chính tả; không bịa giá / số liệu không có trong nội dung.
- titles: tối đa 1 mỗi cảnh, đặt sau đầu cảnh ~0.2s, không trùng 3 giây hook. callouts: tối đa {max(1, round(duration / 6))},
  chỉ khi nội dung có con số / ưu đãi đáng nhấn, không trùng thời điểm với titles.
- zooms: nhấn đúng lúc nói từ khoá quan trọng (lấy mốc từ phụ đề), tối đa {max(1, round(duration / 4))}, không chồng nhau.
- Màu hợp nội dung / thương hiệu, tương phản cao (chữ sáng + viền tối). Mọi mốc thời gian nằm trong 0–{duration:.1f}s."""


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return default if x != x else max(lo, min(hi, x))  # NaN → mặc định


def _text(value, words: int, chars: int = 60) -> str:
    return nfc(" ".join(str(value or "").split()[:words]))[:chars]


def _color(value, default: str) -> str:
    value = str(value or "").strip()
    return value if HEX.match(value) else default


def _events(items, duration: float, *, limit: int, dur: tuple, text_words: int = 0, scale: tuple | None = None) -> list:
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        at = _num(it.get("at"), 0, max(0.0, duration - 0.3), -1)
        if at < 0:
            continue
        ev = {"at": round(at, 2), "duration": round(min(_num(it.get("duration"), *dur, dur[0]), duration - at), 2)}
        if text_words:
            ev["text"] = _text(it.get("text"), text_words, 40)
            if not ev["text"]:
                continue
        if scale:
            ev["scale"] = round(_num(it.get("scale"), *scale, 1.12), 3)
        if all(ev["at"] >= o["at"] + o["duration"] or ev["at"] + ev["duration"] <= o["at"] for o in out):  # không chồng
            out.append(ev)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda e: e["at"])


def parse_plan(data, duration: float, *, hook: str = "") -> dict:
    """Kế hoạch an toàn từ JSON model trả về: sai / thiếu thì dùng mặc định, mọi giá trị bị giới hạn."""
    if not isinstance(data, dict):
        raise RemotionError("Model không trả về kế hoạch dựng hợp lệ (cần object JSON)")
    theme = data.get("theme") if isinstance(data.get("theme"), dict) else {}
    hook_d = data.get("hook") if isinstance(data.get("hook"), dict) else {"text": data.get("hook")}
    end = data.get("end_card") if isinstance(data.get("end_card"), dict) else {}
    end_s = _num(end.get("seconds"), 0, min(3.5, duration / 3), 0)
    return {
        "theme": {"accent": _color(theme.get("accent"), "#FFD400"), "text": _color(theme.get("text"), "#FFFFFF"),
                  "stroke": _color(theme.get("stroke"), "#000000"), "panel": _color(theme.get("panel"), "#000000AA")},
        "caption_style": data.get("caption_style") if data.get("caption_style") in CAPTION_STYLES else "karaoke",
        "caption_y": round(_num(data.get("caption_y"), 0.55, 0.78, 0.68), 3),
        "hook": {"text": _text(hook_d.get("text") or hook, 10, 70),
                 "style": hook_d.get("style") if hook_d.get("style") in HOOK_STYLES else "slam",
                 "duration": round(_num(hook_d.get("duration"), 1.5, min(3.5, duration), min(2.5, duration)), 2)},
        "titles": _events(data.get("titles"), duration, limit=12, dur=(1.2, 3.0), text_words=8),
        "callouts": _events(data.get("callouts"), duration, limit=max(1, round(duration / 6)), dur=(0.8, 2.0), text_words=3),
        "zooms": _events(data.get("zooms"), duration, limit=max(1, round(duration / 4)), dur=(0.5, 2.0), scale=(1.03, 1.25)),
        "end_card": {"title": _text(end.get("title"), 10, 70), "cta": _text(end.get("cta"), 5, 30), "seconds": round(end_s, 2)},
        "progress": bool(data.get("progress", True)),
    }


def _fonts(folder: Path) -> list:
    """Chép Segoe UI (đủ dấu tiếng Việt) vào public dir; máy không có → Remotion dùng font hệ thống."""
    fonts_dir = Path(os.environ.get("WINDIR") or r"C:\Windows") / "Fonts"
    out = []
    for weight, name in FONT_FILES:
        src = fonts_dir / name
        if src.is_file():
            (folder / "fonts").mkdir(exist_ok=True)
            shutil.copy2(src, folder / "fonts" / name)
            out.append({"file": f"fonts/{name}", "weight": weight})
    return out


def write_project(folder: Path, base_video: Path, plan: dict, *, captions: list, scenes: list, width: int, height: int,
                  fps: int, duration: float) -> Path:
    """folder = public dir của lần dựng: base.mp4 + fonts + props.json."""
    folder.mkdir(parents=True, exist_ok=True)
    # mã hoá lại nền: khung đều (CFR), không B-frame, keyframe mỗi giây — compositor của Remotion đọc khung theo mốc
    # thời gian, video ghép crossfade + B-frame dễ báo "No frame found at position"
    ffmpeg.run(["-i", base_video, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                "-bf", "0", "-g", int(fps), "-r", int(fps), "-fps_mode", "cfr", "-pix_fmt", "yuv420p", "-c:a", "copy",
                "-movflags", "+faststart", folder / "base.mp4"])
    props = {"video": "base.mp4", "width": int(width), "height": int(height), "fps": int(fps), "duration": float(duration),
             "fonts": _fonts(folder), "captions": captions, "scenes": scenes, "plan": plan}
    path = folder / "props.json"
    path.write_text(json.dumps(props, ensure_ascii=False), "utf-8")
    return path


def render(folder: Path, out: Path, *, check_cancel=None, timeout: int = 2400) -> Path:
    args = ["render", "src/index.ts", COMP_ID, str(out), f"--props={folder / 'props.json'}", f"--public-dir={folder}",
            "--codec=h264", "--crf=18", "--audio-codec=aac", "--overwrite"]
    res = _run(args, TOOLS_DIR, timeout=timeout, check_cancel=check_cancel, log_dir=folder)
    if res.returncode != 0 or not out.is_file():
        raise RemotionError(f"Remotion dựng video lỗi: {res.stdout.strip()[-800:]}")
    return out
