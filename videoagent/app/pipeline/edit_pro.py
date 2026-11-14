"""Khối ✨ Edit Pro (Canvas / Workflow): edit trọn gói video nói chuyện (talking-head) theo skill "Bích Hạnh Edit Video
Bản VIP" ĐÃ CÀI trên máy (~/.claude/skills/bich-hanh-edit-video-vip) — app chỉ GỌI script của skill, không chép mã.

  1) beauty.py      làm đẹp (mịn da, sáng, nét, 1080p, 30fps) + đưa 3:4 / 16:9 về 9:16 nền mờ
  2) cut_silence.py cắt khoảng lặng
  3) transcribe.py  bóc lời tiếng Việt có mốc từng từ (faster-whisper, chạy trên máy)
  4) Claude (claude.ai trình duyệt) viết plan.json theo style-guide + mẫu của skill: phụ đề 3 tầng, zoom nhấn, thẻ lụa /
     thẻ kem, chữ ký, cảnh kết quả học viên, CTA — xem khung hình để chữ không che mặt
  5) render.py      xuất bản cuối 1080p + bản nhẹ cho điện thoại
Script skill cần Python có numpy, Pillow, fontTools, faster-whisper + ffmpeg / ffprobe trên PATH (cai-dat.bat của skill
cài sẵn). Thư mục làm việc ngắn, không dấu (Windows hay lỗi đường dẫn dài) — xoá sau khi xong.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .. import ffmpeg
from ..paths import DATA_DIR
from . import fx3d

SKILL_NAME = "bich-hanh-edit-video-vip"
NEEDED = ("numpy", "PIL", "fontTools", "faster_whisper")
SCRIPTS = ("beauty.py", "cut_silence.py", "transcribe.py", "render.py")

# faster-whisper ≤1.2 gọi av.open(..., metadata_errors=…) nhưng PyAV ≥15 đã bỏ tham số này
# → chạy transcribe.py của skill qua lớp vỏ: bỏ tham số khi PyAV không nhận (không sửa code skill).
AV_SHIM = (
    "import sys,os,runpy,inspect\n"
    "try:\n"
    " import av\n"
    " _o=av.open\n"
    " try: _ok='metadata_errors' in inspect.signature(_o).parameters\n"
    " except (TypeError,ValueError): _ok=False\n"
    " if not _ok:\n"
    "  def _open(*a,**k):\n"
    "   k.pop('metadata_errors',None); return _o(*a,**k)\n"
    "  av.open=_open\n"
    "except ImportError: pass\n"
    "s=sys.argv[1]; sys.argv=sys.argv[1:]; sys.path.insert(0,os.path.dirname(os.path.abspath(s)))\n"
    "runpy.run_path(s,run_name='__main__')\n"
)
LEVELS = ("off", "light", "medium", "strong")
# Theme có sẵn trong render.py của skill + theme app thêm (bảng màu cùng khoá với skill: accent = từ khoá nổi trên video,
# accent_dark = chữ trên thẻ nền sáng, tag / sig / line = nhãn nhỏ / chữ ký / gạch kẻ, silk_* = thẻ lụa tối, cream_* = thẻ
# nền sáng, card_shade = lớp phủ thẻ). Theme thêm được NẠP VÀO render.py lúc chạy (THEME_SHIM) — không sửa file của skill.
SKILL_THEMES = {"vang-den": "Vàng – đen (sang trọng)", "tim": "Tím Purple Love"}
EXTRA_THEMES = {
    "xanh-la": ("Xanh lá – nông nghiệp (tươi, gần gũi)", dict(
        accent="#A5D66B", accent_dark="#1F4D1A", tag="#C5E1A5", sig="#A5D66B", line="#2E7D32",
        silk_base=(8, 20, 10), silk_lite=(52, 110, 58), cream_a=(250, 252, 244), cream_b=(230, 240, 214), card_shade=(14, 32, 16))),
    "xanh-duong": ("Xanh dương – tin cậy, chuyên gia", dict(
        accent="#8EC5FF", accent_dark="#0D2A4A", tag="#90CAF9", sig="#8EC5FF", line="#1565C0",
        silk_base=(6, 12, 26), silk_lite=(40, 72, 130), cream_a=(247, 250, 255), cream_b=(225, 236, 250), card_shade=(10, 20, 40))),
    "do-vang": ("Đỏ – vàng (Tết, khuyến mãi)", dict(
        accent="#FFD54F", accent_dark="#7A0C0C", tag="#FFE082", sig="#FFD54F", line="#C62828",
        silk_base=(32, 4, 4), silk_lite=(140, 24, 20), cream_a=(255, 248, 235), cream_b=(250, 228, 200), card_shade=(48, 8, 8))),
    "cam": ("Cam năng động (trẻ trung)", dict(
        accent="#FFB74D", accent_dark="#4E2600", tag="#FFCC80", sig="#FFB74D", line="#EF6C00",
        silk_base=(24, 12, 4), silk_lite=(130, 66, 20), cream_a=(255, 250, 242), cream_b=(250, 232, 210), card_shade=(40, 20, 6))),
    "hong": ("Hồng pastel (làm đẹp, nữ tính)", dict(
        accent="#F8BBD0", accent_dark="#5A1030", tag="#F48FB1", sig="#F8BBD0", line="#C2185B",
        silk_base=(26, 8, 16), silk_lite=(130, 50, 86), cream_a=(255, 250, 252), cream_b=(248, 226, 236), card_shade=(42, 14, 26))),
    "ngoc-lam": ("Ngọc lam (tươi mát, hiện đại)", dict(
        accent="#7FE0D0", accent_dark="#053B36", tag="#80CBC4", sig="#7FE0D0", line="#00897B",
        silk_base=(4, 22, 22), silk_lite=(30, 110, 104), cream_a=(244, 253, 251), cream_b=(220, 243, 238), card_shade=(8, 34, 32))),
    "nau-dat": ("Nâu đất (mộc mạc, tự nhiên)", dict(
        accent="#D7B98E", accent_dark="#3E2A17", tag="#D7CCC8", sig="#D7B98E", line="#8D6E63",
        silk_base=(20, 14, 9), silk_lite=(104, 78, 54), cream_a=(250, 245, 236), cream_b=(236, 224, 206), card_shade=(34, 24, 16))),
    "trang-bac": ("Trắng – bạc (tối giản)", dict(
        accent="#E0E6EC", accent_dark="#1C1F24", tag="#CFD8DC", sig="#E0E6EC", line="#607D8B",
        silk_base=(14, 16, 18), silk_lite=(82, 90, 98), cream_a=(255, 255, 255), cream_b=(236, 239, 242), card_shade=(24, 26, 30))),
}
THEMES = (*SKILL_THEMES, *EXTRA_THEMES)
THEME_LABELS = {**SKILL_THEMES, **{k: v[0] for k, v in EXTRA_THEMES.items()}}
THEME_MARK = chr(10) + "T = dict(THEMES["  # dòng trong render.py ngay sau bảng THEMES — chèn theme thêm vào trước dòng này
# chạy render.py với bảng THEMES có thêm theme của app (đọc từ biến môi trường EP_THEMES); không đổi file của skill
THEME_SHIM = "\n".join([
    "import sys,os,json",
    "s=sys.argv[1]; sys.argv=sys.argv[1:]; sys.path.insert(0,os.path.dirname(os.path.abspath(s)))",
    "x={k:{a:(tuple(b) if isinstance(b,list) else b) for a,b in v.items()} for k,v in json.loads(os.environ['EP_THEMES']).items()}",
    "src=open(s,encoding='utf-8').read()",
    "m=chr(10)+'T = dict(THEMES['",
    "src=src.replace(m,chr(10)+'THEMES.update(__ep_themes__)'+m,1)",
    "g={'__name__':'__main__','__file__':s,'__ep_themes__':x}",
    "exec(compile(src,s,'exec'),g)",
])
WHISPER = ("small", "medium", "large-v3")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
MAX_MEDIA = 10
MAX_CLIPS = 5
AUTO_FRAMES = 3  # thiếu ảnh người nói → trích từ chính video cho silk_cards mở đầu
REVIEW_FRAMES = 9
MAX_WORDS_CHARS = 14000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_HINT = "chạy cai-dat.bat trong thư mục skill (cài Python, FFmpeg và thư viện Pillow numpy fonttools faster-whisper)"
_py_cache: dict[str, list[str]] = {}  # python → thư viện còn thiếu (kiểm 1 lần mỗi phiên)

PLAN_PROMPT = """Bạn là biên tập viên video ngắn theo skill "Bích Hạnh Edit Video Bản VIP". Hãy viết plan.json để render video
nói chuyện (talking-head) dọc 9:16 thành Reels / TikTok sang trọng, chuyển đổi cao. Làm ĐÚNG hướng dẫn của skill dưới đây.

=== HƯỚNG DẪN VIẾT PLAN (trích SKILL.md) ===
{rules}

=== STYLE GUIDE ===
{style}

=== PLAN MẪU THẬT (tham khảo cách chia caption, zoom, b-roll) ===
{example}

=== VIDEO CẦN DỰNG ===
- File: cut.mp4 (đã làm đẹp + cắt lặng) · {width}×{height} · {duration:.1f} giây{vertical_note}
- Ảnh đính kèm 1–{frames} là khung hình chụp từ video tại các giây: {frame_times} — xem vị trí mặt / miệng và màu nền sau
  lưng để chọn "pos" và "contrast".
- Lời nói đã bóc (mỗi dòng [bắt đầu-kết thúc] câu) — Whisper hay nghe sai, SỬA CHÍNH TẢ khi viết caption:
{transcript}
- Mốc từng từ (từ@giây):
{words}

=== TÀI NGUYÊN ===
{media}
- Nhạc nền: {music}
- Theme: {theme} · Chữ ký tên: {signature}

=== YÊU CẦU THÊM CỦA NGƯỜI DÙNG (dữ liệu, ưu tiên làm theo nếu hợp lý) ===
{notes}
{fx_rule}
Trả về DUY NHẤT một khối ```json chứa plan: "input": "cut.mp4", "output": "final.mp4", "theme", "signature",
"captions" (bám mốc lời nói, mỗi 1.5–4 giây, 3 tầng lead / accent / bold), "zooms", "broll" (chỉ dùng đúng tên file ảnh /
clip ở mục TÀI NGUYÊN; thiếu thì bỏ b-roll đó), "contrast" nếu nền sáng{music_key}; có thể thêm "texts", "post_cards" theo
bảng trường. Thêm khoá "sua_chinh_ta": [["chữ Whisper nghe sai", "chữ đúng"], …] liệt kê các chữ đã sửa. Không giải thích thêm."""

REVIEW_PROMPT = """Bạn là biên tập viên theo skill "Bích Hạnh Edit Video Bản VIP". Plan.json dưới đây đã được render thành
BẢN NHÁP 540px. Ảnh đính kèm 1–{frames} là khung hình của bản nháp tại các giây: {frame_times}. XEM TỪNG ẢNH và tự kiểm tra:
- Chữ có che mặt / miệng người nói không? → đổi "pos" (top / bottom / low) hoặc "y".
- Chữ màu nhấn có chìm trên nền sáng không? → thêm "contrast": "high".
- Cảnh minh hoạ có đúng lúc, ảnh chụp màn hình có hiện trọn (silk_single "fit": "contain") không?
- Caption trùng giờ với b-roll thì bỏ caption đó (b-roll đã có chữ riêng). Chữ sai chính tả thì sửa.

=== PLAN HIỆN TẠI ===
{plan}

=== TÀI NGUYÊN (chỉ dùng đúng các tên này) ===
{media}

Trả về DUY NHẤT một khối ```json chứa plan đã sửa (giữ nguyên phần đã ổn, giữ khoá "sua_chinh_ta"). Thêm khoá
"nhan_xet": "<1–2 câu: đã sửa gì, hoặc 'đã ổn'>". Không giải thích thêm."""

PRIVACY_NOTE = ("Nhắc: nếu ảnh chụp màn hình kết quả có tên / ảnh đại diện của người khác, hãy làm mờ trước khi đăng nếu "
                "chưa xin phép họ")


class EditProError(RuntimeError):
    pass


# ------------------------------------------------------------------ kiểm tra môi trường
def skill_dir(settings) -> Path:
    custom = str(settings.get("edit_pro_skill_dir") or "").strip()
    return Path(custom) if custom else Path.home() / ".claude" / "skills" / SKILL_NAME


def _missing(python: list[str]) -> list[str]:
    key = " ".join(python)
    if key not in _py_cache:
        code = "import importlib.util as u,sys;print(','.join(m for m in sys.argv[1:] if u.find_spec(m) is None))"
        try:
            out = subprocess.run([*python, "-c", code, *NEEDED], capture_output=True, text=True, timeout=40,
                                 creationflags=NO_WINDOW)
            _py_cache[key] = [m for m in out.stdout.strip().split(",") if m] if out.returncode == 0 else list(NEEDED)
        except (OSError, subprocess.SubprocessError):
            _py_cache[key] = list(NEEDED)
    return _py_cache[key]


def _candidates(settings) -> list[list[str]]:
    custom = str(settings.get("edit_pro_python") or "").strip()
    out = [[custom]] if custom else []
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            out.append([found])
    if shutil.which("py"):
        out.append([shutil.which("py"), "-3"])
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if local.is_dir():
        out += [[str(p)] for p in sorted(local.glob("Python3*/python.exe"), reverse=True)]
    if not getattr(sys, "frozen", False):
        out.append([sys.executable])
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq


def status(settings) -> dict:
    """Skill / Python đủ thư viện / ffmpeg + ffprobe — để kiểm tra trước khi chạy và báo cách sửa."""
    sdir = skill_dir(settings)
    skill_ok = all((sdir / "scripts" / s).is_file() for s in SCRIPTS)
    python, missing = None, list(NEEDED)
    for cand in _candidates(settings):
        miss = _missing(cand)
        if not miss:
            python, missing = cand, []
            break
        if len(miss) < len(missing):
            missing = miss
    tools = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    problems = []
    if not skill_ok:
        problems.append(f"chưa cài skill “{SKILL_NAME}” ({sdir})")
    if python is None:
        problems.append("chưa có Python đủ thư viện cho skill (thiếu " + ", ".join(missing) + ")")
    if tools:
        problems.append("chưa có " + " / ".join(tools) + " trên PATH")
    return {"ok": not problems, "skill_dir": str(sdir), "python": python, "missing": missing, "tools": tools,
            "problems": problems, "hint": INSTALL_HINT}


# ------------------------------------------------------------------ chạy script
def _run(cmd: list, cwd: Path, log, check_cancel, what: str, env_extra: dict | None = None) -> None:
    """Chạy 1 script của skill; dòng in ra → nhật ký (thưa); bấm Dừng → dừng luôn tiến trình con."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(env_extra or {})}
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW,
                            start_new_session=os.name != "nt")
    tail: list[str] = []

    def reader():  # chỉ gom dòng — ghi nhật ký phải ở thread tác vụ (vòng chờ bên dưới)
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                tail.append(line)
                del tail[:-40]

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    last, shown = 0.0, ""
    try:
        while proc.poll() is None:
            if check_cancel:
                check_cancel()
            if tail and tail[-1] != shown and time.time() - last > 3:  # nhật ký thưa: không làm ngập
                shown, last = tail[-1], time.time()
                log(f"{what}: {shown[:160]}")
            time.sleep(0.5)
    except BaseException:
        from ..osutil import kill_tree

        kill_tree(proc)
        raise
    t.join(timeout=5)
    if proc.returncode != 0:
        raise EditProError(f"{what} lỗi: " + " | ".join(tail[-4:])[:600])


def _section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i: j if j > 0 else None].strip()


def _plan_of(text: str) -> dict | None:
    from ..llm.base import extract_json

    try:
        data = extract_json(text or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("captions"), list) and data["captions"] else None


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _span(x) -> bool:
    return isinstance(x, dict) and _num(x.get("start")) and _num(x.get("end")) and x["end"] > x["start"]


def split_meta(plan: dict) -> tuple[dict, list[list[str]], str]:
    """Tách khoá báo cáo (không phải của render.py) → (plan, các chữ đã sửa chính tả, nhận xét tự kiểm tra)."""
    plan = dict(plan)
    fixes = [[str(a), str(b)] for a, b in (x for x in plan.pop("sua_chinh_ta", None) or []
                                           if isinstance(x, (list, tuple)) and len(x) == 2) if str(a) != str(b)]
    note = str(plan.pop("nhan_xet", "") or "").strip()
    return plan, fixes[:40], note[:500]


def clean_plan(plan: dict, *, theme: str, signature: str, music: str, media: set[str],
               credit: str = "") -> tuple[dict, list[str]]:
    """Ép các trường app quản lý + bỏ phụ đề / zoom / b-roll / chữ sai — trả (plan, cảnh báo)."""
    warn = []
    plan, _, _ = split_meta(plan)
    plan.update(input="cut.mp4", output="final.mp4")
    plan["theme"] = theme if theme in THEMES else (plan.get("theme") if plan.get("theme") in THEMES else "vang-den")
    if signature:
        plan["signature"] = signature
    plan["captions"] = [c for c in plan.get("captions") or [] if isinstance(c, dict)
                        and isinstance(c.get("start"), (int, float)) and any(c.get(k) for k in ("lead", "accent", "bold"))]
    plan["zooms"] = [z for z in plan.get("zooms") or [] if isinstance(z, dict) and isinstance(z.get("start"), (int, float))
                     and isinstance(z.get("end"), (int, float)) and z["end"] > z["start"]]
    broll = []
    for b in plan.get("broll") or []:
        if not _span(b):
            continue
        files = [b["media"]] if b.get("media") else list(b.get("images") or [])
        bad = [f for f in files if f not in media]
        if bad or not files:
            warn.append(f"Bỏ cảnh minh hoạ {b.get('type', '')} lúc {b.get('start')}s (ảnh không có: {', '.join(map(str, bad)) or '—'})")
            continue
        broll.append(b)
    plan["broll"] = broll
    plan["texts"] = [t for t in plan.get("texts") or [] if _span(t) and str(t.get("text") or "").strip() and _num(t.get("y"))]
    plan["post_cards"] = [o for o in plan.get("post_cards") or [] if _span(o)]
    for k in ("texts", "post_cards"):
        if not plan[k]:
            plan.pop(k)
    if music:
        plan["music"] = {**(plan.get("music") if isinstance(plan.get("music"), dict) else {}), "file": music}
        plan["music"].setdefault("volume", 0.12)
        if credit:
            plan["music"]["credit"] = credit
    else:
        plan.pop("music", None)
    if not plan["captions"]:
        raise EditProError("Claude không viết được phụ đề nào cho plan.json")
    return plan, warn


def _float(v, default: float, lo: float, hi: float) -> float:
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def _mmss(t) -> str:
    t = int(t) if _num(t) else 0
    return f"{t // 60}:{t % 60:02d}"


def _grab(src: Path, t: float, dest: Path, vf: str) -> bool:
    try:
        ffmpeg.run(["-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", vf, dest])
        return dest.is_file()
    except Exception:  # khung cuối video lỗi → bỏ qua
        return False


def _frames(src: Path, times: list[float], prefix: str, vf: str) -> tuple[list[Path], list[str]]:
    out, ok = [], []
    for k, t in enumerate(times):
        f = src.parent / f"{prefix}{k}.jpg"
        if _grab(src, t, f, vf):
            out.append(f)
            ok.append(f"{t:.1f}")
    return out, ok


def _review_times(plan: dict, dur: float) -> list[float]:
    """Khung kiểm tra bản nháp: giữa mỗi cảnh minh hoạ + rải đều phần còn lại."""
    mids = sorted({round((b["start"] + b["end"]) / 2, 2) for b in plan.get("broll") or []})[:4]
    rest = REVIEW_FRAMES - len(mids)
    even = [round(dur * (k + 0.5) / rest, 2) for k in range(rest)]
    return sorted(t for t in {*mids, *even} if 0 <= t < max(dur - 0.05, 0.1))


def is_drive_link(link: str) -> bool:
    return bool(re.match(r"https?://(drive|docs)\.google\.com/", (link or "").strip()))


def run(settings, *, video: Path | None, images: list[Path], music: Path | None, cfg: dict, notes: str, out_dir: Path,
        log, check_cancel=None, progress=None, clips: list[Path] | None = None, drive_link: str = "") -> dict:
    """Edit trọn gói → {video, phone, plan, transcript, report, check}. Lỗi môi trường / script / Claude → EditProError."""
    from ..studio import ask_model

    progress = progress or (lambda *a: None)
    st = status(settings)
    if not st["ok"]:
        raise EditProError("Edit Pro: " + "; ".join(st["problems"]) + f" — {INSTALL_HINT}")
    sdir, python = Path(st["skill_dir"]), st["python"]
    script = lambda name: str(sdir / "scripts" / name)  # noqa: E731
    work = DATA_DIR / "ep" / uuid.uuid4().hex[:8]  # ngắn, không dấu
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 0) lấy video: file trên máy, hoặc link Google Drive qua tai_drive.py của skill
        if video is not None:
            raw = work / f"raw{video.suffix.lower() or '.mp4'}"
            shutil.copy2(video, raw)
        else:
            link = (drive_link or "").strip()
            if not is_drive_link(link):
                raise EditProError("Edit Pro: chưa có video — nối khối Video, hoặc dán link Google Drive vào ô Link")
            if not (sdir / "scripts" / "tai_drive.py").is_file():
                raise EditProError(f"Edit Pro: skill thiếu scripts/tai_drive.py — {INSTALL_HINT}")
            log("Tải video từ Google Drive…")
            raw = work / "raw.mp4"
            _run([*python, script("tai_drive.py"), link, raw.name], work, log, check_cancel, "Tải Drive")
            if not raw.is_file() or raw.stat().st_size < 1024:
                raise EditProError("Không tải được video từ Drive — mở quyền chia sẻ “Bất kỳ ai có đường liên kết”")
        w, h = ffmpeg.video_size(raw)
        mode = str(cfg.get("vertical") or "auto")
        vertical = mode == "on" or (mode == "auto" and bool(w and h) and abs(w / h - 9 / 16) > 0.02)
        level = str(cfg.get("beauty") or "medium")
        level = level if level in LEVELS else "medium"
        check_png = None
        cur = raw
        if level != "off" or vertical:
            lv = level if level != "off" else "light"
            if level == "off":
                log("Video chưa dọc 9:16 — làm đẹp mức nhẹ để đưa về 9:16 nền mờ")
            if level != "off" and cfg.get("beauty_check", True):
                t = min(3.0, max(0.0, ffmpeg.media_duration(raw) / 2))
                try:
                    _run([*python, script("beauty.py"), raw.name, "check.png", "--frame", f"{t:.1f}", "--level", lv],
                         work, log, check_cancel, "Ảnh trước|sau")
                    if (work / "check.png").is_file():
                        check_png = out_dir / "truoc-sau.png"
                        shutil.copy2(work / "check.png", check_png)
                        log("Đã lưu ảnh so sánh trước | sau làm đẹp: truoc-sau.png")
                except EditProError as exc:  # chỉ là ảnh duyệt — không chặn quy trình
                    log(f"Không xuất được ảnh trước|sau: {exc}", "warn")
            log(f"1/5 Làm đẹp ({lv}){' + đưa về 9:16 nền mờ' if vertical else ''}…")
            _run([*python, script("beauty.py"), raw.name, "beauty.mp4", "--level", lv, *(["--vertical"] if vertical else [])],
                 work, log, check_cancel, "Làm đẹp")
            cur = work / "beauty.mp4"
        progress(0.2)
        if cfg.get("cut_silence", True):
            log("2/5 Cắt khoảng lặng…")
            _run([*python, script("cut_silence.py"), cur.name, "cut.mp4",
                  "--noise", f"{_float(cfg.get('silence_noise'), -32, -60, -10):g}",
                  "--min-silence", f"{_float(cfg.get('silence_min'), 0.45, 0.1, 3):g}",
                  "--pad", f"{_float(cfg.get('silence_pad'), 0.12, 0, 1):g}"], work, log, check_cancel, "Cắt lặng")
        else:
            shutil.copy2(cur, work / "cut.mp4")
        cut = work / "cut.mp4"
        progress(0.35)
        model = str(cfg.get("whisper") or "medium")
        model = model if model in WHISPER else "medium"
        log(f"3/5 Bóc lời tiếng Việt (Whisper {model} — lần đầu tải model, CPU chạy chậm)…")
        _run([*python, "-c", AV_SHIM, script("transcribe.py"), "cut.mp4", "--model", model, "--out-dir", "."], work, log,
             check_cancel, "Bóc lời")
        tpath = work / "cut.transcript.txt"
        transcript = tpath.read_text("utf-8") if tpath.is_file() else ""
        try:
            words = json.loads((work / "cut.words.json").read_text("utf-8"))
        except (OSError, ValueError):
            words = []
        if not transcript.strip() and not words:
            raise EditProError("Không bóc được lời nói nào (video không có tiếng / tiếng quá nhỏ)")
        progress(0.5)

        # khung hình kiểm tra (đính kèm trước) + ảnh minh hoạ / kết quả học viên (đính kèm sau) + clip + nhạc
        dur = ffmpeg.media_duration(cut)
        cw, ch = ffmpeg.video_size(cut)
        frames, times = _frames(cut, [round(dur * (k + 0.5) / 6, 2) for k in range(6)], "f", "scale=360:-2")
        media, lines, thumbs = set(), [], []
        user_imgs = [p for p in images if p.suffix.lower() in IMAGE_EXT][:MAX_MEDIA]
        for i, p in enumerate(user_imgs, 1):
            name = f"m{i}{p.suffix.lower()}"
            shutil.copy2(p, work / name)
            media.add(name)
            thumbs.append(work / name)
            lines.append(f"- {name}: ảnh người dùng nối vào thứ {i} (“{p.stem[:40]}”) = ảnh đính kèm số {len(frames) + i}")
        if cfg.get("auto_frames", True) and len(user_imgs) < AUTO_FRAMES:
            # skill: thiếu ảnh minh hoạ → trích khung hình đẹp từ chính video (bỏ phần nền mờ nếu đã đưa về 9:16)
            vf = "crop=iw:trunc(ih*0.75/2)*2:0:trunc(ih*0.125/2)*2" if vertical else "null"
            for k in range(AUTO_FRAMES):
                t = round(dur * (0.2 + 0.25 * k), 2)
                name = f"v{k + 1}.jpg"
                if _grab(cut, t, work / name, vf):
                    media.add(name)
                    lines.append(f"- {name}: khung hình người nói trích từ chính video (giây {t:.1f}) — dùng cho "
                                 "silk_cards mở đầu / cream_card khi thiếu ảnh")
        for i, p in enumerate([p for p in clips or [] if p.suffix.lower() in VIDEO_EXT and p.is_file()][:MAX_CLIPS], 1):
            name = f"c{i}{p.suffix.lower()}"
            shutil.copy2(p, work / name)
            media.add(name)
            lines.append(f"- {name}: CLIP video minh hoạ (“{p.stem[:40]}”, {ffmpeg.media_duration(work / name):.1f} giây) — "
                         "dùng làm \"media\" của silk_single / fullscreen / cream_card (tắt tiếng, tự lặp; chọn đoạn "
                         "bằng \"media_start\")")
        music_name = ""
        if music and music.is_file():
            music_name = f"nhac{music.suffix.lower()}"
            shutil.copy2(music, work / music_name)
        media_text = "\n".join(lines) or "- (không có ảnh / clip minh hoạ — bỏ b-roll cần ảnh)"
        credit = str(cfg.get("music_credit") or "").strip()[:120]

        skill_md = (sdir / "SKILL.md").read_text("utf-8")
        style_p = sdir / "references" / "style-guide.md"
        example_p = sdir / "references" / "example-plan-bich-hanh.json"
        use_fx = str(cfg.get("fx3d") or "auto") != "off"  # 🧊 hiệu ứng 3D three.js (lớp riêng của app)
        fx_images = {n for n in media if Path(n).suffix.lower() in IMAGE_EXT}
        words_text = " ".join(f"{x.get('w', '')}@{x.get('s', '')}" for x in words if isinstance(x, dict))[:MAX_WORDS_CHARS]
        prompt = PLAN_PROMPT.format(
            rules=_section(skill_md, "5. **Viết `plan.json`**", "6. **Render") + "\n\n" + _section(skill_md, "## plan.json", "## Lỗi hay gặp"),
            style=style_p.read_text("utf-8")[:9000] if style_p.is_file() else "",
            example=example_p.read_text("utf-8")[:9000] if example_p.is_file() else "",
            width=cw, height=ch, duration=dur,
            vertical_note=" · đã đưa về 9:16 nền mờ (zoom_anchor_y 0.35)" if vertical else "",
            frames=len(frames), frame_times=", ".join(times), transcript=transcript[:12000] or "(trống)",
            words=words_text or "(không có)", media=media_text,
            music=(music_name + (f" (credit: {credit})" if credit else "")) if music_name else "không có",
            theme=cfg.get("theme") or "vang-den",
            signature=str(cfg.get("signature") or "").strip() or "(không có — bỏ chữ ký)",
            notes=notes.strip()[:3000] or "(không có)",
            fx_rule=fx3d.prompt_rule() if use_fx else "",
            music_key=f', "music" với "file": "{music_name}"' if music_name else "")
        log("4/5 Claude đang viết kịch bản dựng (phụ đề 3 tầng, zoom, cảnh minh hoạ)…")
        options = {"model": "claude_browser", "show_browser": False, "timeout": 900}
        raw_plan = ask_model(settings, options, prompt, complete=lambda t: _plan_of(t) is not None,
                             what="viết plan.json (Edit Pro)", log=log, check_cancel=check_cancel,
                             images=[*frames, *thumbs][:16] or None)
        plan = _plan_of(raw_plan)
        if plan is None:
            raise EditProError("Claude không trả plan.json hợp lệ")
        clean = dict(theme=str(cfg.get("theme") or ""), signature=str(cfg.get("signature") or "").strip(),
                     music=music_name, media=media, credit=credit)
        # 🎨 theme app thêm → render.py chạy qua lớp vỏ nạp bảng màu (skill bản khác cấu trúc → về Vàng – đen)
        render, render_env = [*python, script("render.py")], None
        if clean["theme"] in EXTRA_THEMES:
            src = Path(script("render.py")).read_text("utf-8", errors="replace")
            if THEME_MARK in src:
                render = [*python, "-c", THEME_SHIM, script("render.py")]
                render_env = {"EP_THEMES": json.dumps({clean["theme"]: EXTRA_THEMES[clean["theme"]][1]})}
                log(f"Theme màu: {THEME_LABELS[clean['theme']]}")
            else:
                log(f"Skill bản này chưa nạp được theme “{THEME_LABELS[clean['theme']]}” — dùng Vàng – đen", "warn")
                clean["theme"] = "vang-den"
        _, fixes, _ = split_meta(plan)
        plan, warn = clean_plan(plan, **clean)
        fx, fx_warn = fx3d.take(plan, fx_images, dur)  # tách "fx3d" — render.py của skill không biết khoá này
        fx = fx if use_fx else []
        for msg in warn + (fx_warn if use_fx else []):
            log(msg, "warn")
        progress(0.62)

        # 6) skill: render nháp → xem khung hình → sửa plan (thêm 1 lượt Claude)
        review_note = ""
        if cfg.get("review", True):
            log("Render bản nháp 540px để tự kiểm tra…")
            (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), "utf-8")
            try:
                _run([*render, "plan.json", "--preview"], work, log, check_cancel, "Render nháp", render_env)
                prev = work / "final_preview.mp4"
                if not prev.is_file():
                    raise EditProError("render nháp không ra final_preview.mp4")
                pframes, ptimes = _frames(prev, _review_times(plan, ffmpeg.media_duration(prev) or dur), "p", "scale=270:-2")
                if not pframes:
                    raise EditProError("không trích được khung hình bản nháp")
                log(f"Claude đang xem {len(pframes)} khung bản nháp (chữ che mặt? chìm nền? b-roll đúng lúc?)…")
                fixed = _plan_of(ask_model(
                    settings, options, REVIEW_PROMPT.format(
                        frames=len(pframes), frame_times=", ".join(ptimes), media=media_text,
                        plan=json.dumps({**plan, "sua_chinh_ta": fixes}, ensure_ascii=False, indent=1)),
                    complete=lambda t: _plan_of(t) is not None, what="tự kiểm tra bản nháp (Edit Pro)", log=log,
                    check_cancel=check_cancel, images=pframes))
                if fixed is None:
                    raise EditProError("Claude không trả plan đã sửa")
                _, fixes2, review_note = split_meta(fixed)
                fixed, warn = clean_plan(fixed, **clean)
                fx2, _ = fx3d.take(fixed, fx_images, dur)
                fx = (fx2 or fx) if use_fx else []  # bản duyệt không nhắc hiệu ứng 3D → giữ hiệu ứng plan đầu
                for msg in warn:
                    log(msg, "warn")
                plan, fixes = fixed, fixes2 or fixes
                log(f"Tự kiểm tra: {review_note or 'đã cập nhật plan'}")
            except Exception as exc:  # bước duyệt lỗi → vẫn render bản cuối với plan đầu (trừ khi người dùng bấm Dừng)
                if check_cancel:
                    check_cancel()
                log(f"Bỏ qua bước tự kiểm tra bản nháp: {exc}", "warn")
        (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), "utf-8")
        shutil.copy2(work / "plan.json", out_dir / "plan.json")
        (out_dir / "loi-thoai.txt").write_text(transcript, "utf-8")
        progress(0.75)

        phone = bool(cfg.get("phone", True))
        log(f"5/5 Render bản cuối 1080p{' + bản điện thoại' if phone else ''}…")
        _run([*render, "plan.json", *([] if phone else ["--no-phone"])], work, log, check_cancel, "Render", render_env)
        final = work / "final.mp4"
        if not final.is_file():
            raise EditProError("Render xong nhưng không thấy final.mp4")
        if fx:  # 🧊 chồng hiệu ứng 3D (three.js) lên bản cuối + bản điện thoại; lỗi → giữ video không 3D
            log(f"Dựng {len(fx)} hiệu ứng 3D (three.js) và ghép lên video…")
            progress(0.9)
            try:
                fx3d.apply(fx, [p for p in (final, work / "final_dien-thoai.mp4") if p.is_file()], work,
                           clean["theme"], log, check_cancel)
            except Exception as exc:
                if check_cancel:
                    check_cancel()
                log(f"Không dựng được hiệu ứng 3D ({str(exc)[:300]}) — giữ video không có 3D", "warn")
                fx = []
        dest = out_dir / "edit-pro.mp4"
        shutil.copy2(final, dest)
        phone_dest = None
        if (work / "final_dien-thoai.mp4").is_file():
            phone_dest = out_dir / "edit-pro_dien-thoai.mp4"
            shutil.copy2(work / "final_dien-thoai.mp4", phone_dest)
        progress(1.0)

        # 8) báo lại: nơi lưu, chữ đã sửa chính tả, cảnh minh hoạ ở phút nào, nhắc quyền riêng tư
        broll = [f"{_mmss(b['start'])}–{_mmss(b['end'])} {b.get('type', '')}: "
                 f"{b.get('media') or ', '.join(map(str, b.get('images') or []))}"
                 + (f" ({b['tag']})" if b.get("tag") else "") for b in plan["broll"]]
        rep = [f"Video: {dest.name}" + (f" · bản điện thoại: {phone_dest.name}" if phone_dest else ""),
               f"{len(plan['captions'])} phụ đề · {len(plan['zooms'])} zoom · {len(plan['broll'])} cảnh minh hoạ",
               "Chữ đã sửa chính tả: " + ("; ".join(f"{a} → {b}" for a, b in fixes) if fixes else "(không có)"),
               "Cảnh minh hoạ:", *([f"  • {x}" for x in broll] or ["  (không có)"])]
        if fx:
            rep.append("Hiệu ứng 3D: " + "; ".join(
                f"{_mmss(f['start'])}–{_mmss(f['end'])} {f['type']}" + (f" “{f['text']}”" if f["text"] else "") for f in fx))
        if review_note:
            rep.append(f"Tự kiểm tra bản nháp: {review_note}")
        if check_png:
            rep.append(f"Ảnh trước | sau làm đẹp: {check_png.name}")
        if user_imgs:
            rep.append(PRIVACY_NOTE)
        report = "\n".join(rep)
        (out_dir / "bao-cao.txt").write_text(report, "utf-8")
        for line in rep:
            log(line, "warn" if line == PRIVACY_NOTE else "info")
        return {"video": str(dest), "phone": str(phone_dest) if phone_dest else "", "plan": str(out_dir / "plan.json"),
                "transcript": transcript, "report": report, "check": str(check_png) if check_png else "",
                "fixes": fixes, "review": review_note}
    finally:
        shutil.rmtree(work, ignore_errors=True)
