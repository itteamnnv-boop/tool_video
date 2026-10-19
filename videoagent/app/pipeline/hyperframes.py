"""Hậu kỳ đồ hoạ động bằng HyperFrames (HeyGen, mã nguồn mở, Apache 2.0): HTML + GSAP → video, dựng NGAY TRÊN MÁY.

Luồng (Studio → ✨ Hậu kỳ AI → Kiểu: HyperFrames):
1. compose() ghép video như thường nhưng KHÔNG chèn phụ đề ASS → base.mp4 (đã có giọng, nhạc, SFX).
2. App dựng khung composition: base.mp4 làm lớp nền (giữ âm thanh), gsap.min.js cục bộ, logo, window.CAPTIONS (mốc
   thời gian từng từ + từ khoá), window.SCENES. Model chat (mặc định Claude trình duyệt) chỉ viết phần sáng tạo:
   CSS + HTML lớp phủ + mã GSAP (phụ đề động, hook, dải tên, thẻ kết…).
3. `hyperframes lint` → lỗi thì nhờ model sửa 1 lần → `hyperframes render` → final.mp4.

Cài đặt: lần đầu chạy `npm install hyperframes gsap` (phiên bản cố định) vào DATA_DIR/tools/hyperframes. Cần Node.js 22+,
FFmpeg + FFprobe trong PATH. Luôn tắt telemetry (HYPERFRAMES_NO_TELEMETRY, DO_NOT_TRACK).
"""
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from ..paths import DATA_DIR
from .subtitles import _lines, scene_words

TOOLS_DIR = DATA_DIR / "tools" / "hyperframes"
HF_VERSION, GSAP_VERSION = "0.8.170", "3.15.0"
NODE_MIN = 22
COMP_ID = "root"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_HINT = ("Cần Node.js 22+ (https://nodejs.org) và FFmpeg có ffprobe (Windows: winget install Gyan.FFmpeg), "
                "rồi mở lại app")


class HyperFramesError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- cài đặt / gọi CLI
def _env() -> dict:
    env = {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_SKIP_SKILLS": "1"}
    for name, key in (("ffmpeg", "FFMPEG_PATH"), ("ffprobe", "FFPROBE_PATH")):
        found = shutil.which(name)
        if found:
            env.setdefault(key, found)
    return env


def _cli() -> Path:
    return TOOLS_DIR / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")


def status() -> dict:
    """Tình trạng cho giao diện: có Node / ffprobe chưa, đã cài HyperFrames chưa."""
    node = shutil.which("node")
    version = ""
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15,
                                     creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = ""
    major = int(re.sub(r"\D.*", "", version.lstrip("v")) or 0) if version else 0
    return {"node": version, "node_ok": major >= NODE_MIN, "ffprobe": bool(shutil.which("ffprobe")),
            "installed": _cli().is_file(), "version": HF_VERSION}


def ensure_installed(log) -> Path:
    st = status()
    if not st["node_ok"]:
        raise HyperFramesError(f"Chưa có Node.js {NODE_MIN}+ (đang: {st['node'] or 'không có'}) — {INSTALL_HINT}")
    if not st["ffprobe"]:
        raise HyperFramesError(f"Chưa có ffprobe trong PATH — {INSTALL_HINT}")
    if st["installed"]:
        return _cli()
    npm = shutil.which("npm")
    if not npm:
        raise HyperFramesError(f"Không tìm thấy npm — {INSTALL_HINT}")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    pkg = TOOLS_DIR / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps({"name": "videoagent-hyperframes", "private": True}), "utf-8")
    log(f"Đang cài HyperFrames {HF_VERSION} + GSAP {GSAP_VERSION} (lần đầu, cần internet)…")
    proc = subprocess.run([npm, "install", f"hyperframes@{HF_VERSION}", f"gsap@{GSAP_VERSION}", "--no-fund", "--no-audit"],
                          cwd=TOOLS_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=_env(), timeout=900, creationflags=NO_WINDOW)
    if proc.returncode != 0 or not _cli().is_file():
        raise HyperFramesError(f"Cài HyperFrames lỗi: {(proc.stderr or proc.stdout).strip()[-600:]}")
    _run(["telemetry", "disable"], TOOLS_DIR, timeout=120)
    log("Đang tải Chrome dùng để dựng video (lần đầu)…")
    _run(["browser", "ensure"], TOOLS_DIR, timeout=900)
    log("Đã cài HyperFrames", "ok")
    return _cli()


def _run(args: list, cwd: Path, timeout: int = 600, check_cancel=None) -> subprocess.CompletedProcess:
    """Chạy CLI hyperframes; check_cancel() được gọi định kỳ — huỷ thì dừng cả cây tiến trình."""
    log_path = Path(cwd) / f".hf-{args[0]}.log"  # ghi ra file (không dùng PIPE → không kẹt khi CLI in nhiều)
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen([str(_cli()), *args], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                env=_env(), creationflags=NO_WINDOW)
        deadline = time.time() + timeout
        try:
            while proc.poll() is None:
                if check_cancel:
                    check_cancel()
                if time.time() > deadline:
                    raise HyperFramesError(f"HyperFrames chạy quá {timeout // 60} phút — đã dừng")
                time.sleep(0.5)
        except BaseException:
            _kill(proc)
            raise
    out = re.sub(r"\x1b\[[0-9;]*m", "", log_path.read_text("utf-8", errors="replace"))
    return subprocess.CompletedProcess(args, proc.returncode, out, "")


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":  # .cmd → node → chrome: dừng cả cây tiến trình
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        proc.kill()


# ---------------------------------------------------------------------------- font tiếng Việt
# HyperFrames tự đổi font hệ thống sang font Google tương đương (VD 'Segoe UI' → Roboto, Impact → font tiêu đề không có
# dấu tiếng Việt) rồi TẢI lúc dựng → chữ có dấu dễ vỡ / sai font / mất mạng thì rơi về font mặc định. Nhúng sẵn bộ
# Segoe UI của Windows (đủ dấu tiếng Việt) dưới tên riêng: family đã có @font-face thì HyperFrames giữ nguyên, không tải.
FONT_FAMILY = "VA Viet"
FONT_FILES = ((400, "segoeui.ttf"), (600, "seguisb.ttf"), (700, "segoeuib.ttf"), (900, "seguibl.ttf"))
FALLBACK_FAMILY = "Be Vietnam Pro"  # máy không có Segoe UI → font Google có tiếng Việt, HyperFrames tự tải


def nfc(text: str) -> str:
    """Tiếng Việt dạng dựng sẵn (NFC): dấu dính liền chữ, không bị tách rời khi hiệu ứng tách / đếm ký tự."""
    return unicodedata.normalize("NFC", text or "")


FONT_DECL = re.compile(r"(font-family\s*:\s*)[^;}\"`<]+", re.I)      # CSS / style inline
FONT_JS = re.compile(r"(fontFamily\s*[=:]\s*)(['`])[^'`]*\2")            # el.style.fontFamily = '...'
FONT_SHORTHAND = re.compile(r"(\bfont\s*:\s*[^;}\"`<]*?\d+(?:px|em|rem|%)(?:\s*/\s*[\d.]+\w*)?\s+)[^;}\"`<]+", re.I)


def force_font(code: str, family: str) -> str:
    """Thay mọi font model tự chọn bằng font tiếng Việt đã nhúng (font không có @font-face → lint HyperFrames báo lỗi,
    font hiển thị lại thiếu dấu)."""
    code = FONT_DECL.sub(lambda m: f"{m.group(1)}{family}", code)
    code = FONT_SHORTHAND.sub(lambda m: f"{m.group(1)}{family}", code)
    return FONT_JS.sub(lambda m: f"{m.group(1)}{m.group(2)}{family}{m.group(2)}", code)


def _font_css(folder: Path) -> str:
    """@font-face cho FONT_FAMILY (chép font vào folder/fonts) + ép mọi chữ lớp phủ dùng font đó (đè CSS của model)."""
    fonts_dir = Path(os.environ.get("WINDIR") or r"C:\Windows") / "Fonts"
    faces = []
    for weight, name in FONT_FILES:
        src = fonts_dir / name
        if src.is_file():
            (folder / "fonts").mkdir(exist_ok=True)
            shutil.copy2(src, folder / "fonts" / name)
            faces.append(f"@font-face{{font-family:'{FONT_FAMILY}';src:url('fonts/{name}') format('truetype');"
                         f"font-weight:{weight};font-style:normal;font-display:block}}")
    family = f"'{FONT_FAMILY}'" if faces else f"'{FALLBACK_FAMILY}'"
    return "\n".join(faces + [
        f"#root,#root *:not(#base){{font-family:{family},sans-serif !important;font-synthesis:none}}",
        # dấu chồng trên chữ hoa (Ể, Ỗ, Ữ) bị cắt khi khối chữ overflow:hidden + line-height sát → chừa khoảng trên
        "#root [style*='overflow'],#root .line,#root .word,#root .cap,#root .caption{padding-top:.18em}",
    ])


# ---------------------------------------------------------------------------- dữ liệu cho model + khung composition
def timeline_data(scenes: list[dict], voice_lead: float) -> tuple[list, list]:
    """CAPTIONS (dòng phụ đề ≤5 từ, mốc tuyệt đối, k = từ khoá) + SCENES (mốc từng cảnh) cho composition."""
    captions, scene_list, offset = [], [], 0.0
    for scene in scenes:
        start = offset
        marks = set(scene.get("highlight") or [])
        words = [{**w, "i": i} for i, w in enumerate(scene_words(scene))]
        base = offset + voice_lead
        for line in _lines(words):
            captions.append({"scene": scene["index"], "start": round(base + line[0]["start"], 2),
                             "end": round(base + line[-1]["end"] + 0.15, 2),
                             "words": [{"t": nfc(w["text"]), "s": round(base + w["start"], 2), "e": round(base + w["end"], 2),
                                        **({"k": 1} if w["i"] in marks else {})} for w in line]})
        offset += scene["duration"]
        scene_list.append({"index": scene["index"], "start": round(start, 2), "end": round(offset, 2),
                           "headline": nfc(scene.get("headline", "")), "narration": nfc(scene.get("narration", ""))})
    for a, b in zip(captions, captions[1:]):  # dòng sau bắt đầu → dòng trước tắt (không chồng chữ)
        a["end"] = min(a["end"], b["start"])
    return captions, scene_list


def build_prompt(scenes: list, captions: list, *, width: int, height: int, duration: float, hook: str, logo: bool,
                 brand: str = "") -> str:
    preview = "\n".join(f"- Cảnh {s['index']} [{s['start']:.1f}s → {s['end']:.1f}s] {s['headline']}: {s['narration']}"
                        for s in scenes)
    keys = sorted({w["t"] for c in captions for w in c["words"] if w.get("k")})
    logo_line = "- Ảnh logo: <img src='logo.png'> (PNG nền trong suốt)." if logo else "- Không có logo."
    return f"""Bạn là motion designer làm video ngắn TikTok / Reels. Video {width}×{height}, dài {duration:.1f} giây, đã có
hình + giọng đọc + nhạc. Hãy thiết kế LỚP ĐỒ HOẠ ĐỘNG phủ lên video bằng HyperFrames (HTML + CSS + GSAP).

Nội dung từng cảnh:
{preview}

App đã dựng sẵn (KHÔNG viết lại):
- <div id="root" data-composition-id="root" data-width="{width}" data-height="{height}"> có position:relative, overflow:hidden;
  video nền #base phủ kín, đã có âm thanh.
- window.CAPTIONS = mảng dòng phụ đề đúng nhịp giọng đọc: {{start, end, scene, words:[{{t: chữ, s: giây bắt đầu, e: giây kết thúc,
  k: 1 nếu là từ khoá}}]}} (mốc thời gian tính theo cả video). Từ khoá: {', '.join(keys[:40]) or '(chưa có)'}.
- window.SCENES = [{{index, start, end, headline, narration}}].
- Biến tl = gsap.timeline({{paused: true}}) đã tạo và đăng ký sẵn — chỉ việc thêm tween vào tl với vị trí thời gian tuyệt đối
  (tham số thứ 3), ví dụ tl.fromTo(el, {{opacity: 0}}, {{opacity: 1, duration: 0.3}}, 2.5).
{logo_line}
- Hook mở đầu: “{hook}”. {f'Thương hiệu / sản phẩm: {brand}.' if brand else ''}

Yêu cầu thiết kế:
- PHỤ ĐỀ ĐỘNG từ window.CAPTIONS (tạo phần tử bằng JS, gắn vào #root): mỗi dòng hiện đúng start→end, từng từ sáng lên
  đúng mốc s, từ khoá (k) nổi bật hơn (màu nhấn, to hơn, có hiệu ứng). Chữ to, đậm, viền / bóng đổ để đọc rõ trên mọi nền.
- Thẻ HOOK ở 3 giây đầu, phía trên; có thể thêm dải tên sản phẩm / con số nổi bật ở cảnh phù hợp; thẻ KẾT (lời kêu gọi
  {', logo' if logo else ''}) ở 3 giây cuối.
- Vùng an toàn: không đặt chữ ở 260px dưới cùng và 140px bên phải (nút của TikTok / Reels); phụ đề quanh 62–75% chiều cao.
- Chữ tiếng Việt có dấu: CHỈ dùng font-family: '{FONT_FAMILY}' (app đã nhúng sẵn, đủ dấu; độ đậm 400 / 600 / 700 / 900).
  Không dùng font khác (Impact, Anton, Bebas… không có dấu tiếng Việt). Không tải font / ảnh / script từ internet.
  Không thêm video khác.
- Dấu chồng trên chữ hoa (Ể, Ỗ, Ữ, Ặ…) không được bị cắt: line-height tối thiểu 1.35; khối chữ dùng overflow:hidden
  (hiệu ứng trượt chữ) phải có padding-top ≥ 0.2em. Tách chữ theo TỪ (split(' ')), KHÔNG tách từng ký tự.
- Chỉ dùng tl.set / tl.to / tl.from / tl.fromTo với thuộc tính: opacity, x, y, scale, scaleX, scaleY, rotation,
  width, height, visibility (dùng ease được). Mọi phần tử phủ bắt đầu ẩn (opacity 0) rồi tween hiện ra.
- Kết quả phải giống nhau mỗi lần dựng: KHÔNG Math.random, Date, setTimeout, setInterval, requestAnimationFrame, fetch.
- Mã viết nhiều dòng nhưng KHÔNG dùng chú thích // (chỉ /* */), luôn có dấu chấm phẩy. Trong css / html / js chỉ dùng
  dấu nháy đơn ' hoặc backtick `, KHÔNG dùng dấu nháy kép ".

Trả về MỘT object JSON trong một khối code ```json (không giải thích thêm):
{{"css": "<CSS cho lớp phủ>", "html": "<HTML phần tử tĩnh, có thể rỗng>", "js": "<mã JS dùng tl, CAPTIONS, SCENES>"}}"""


def fix_prompt(errors: list[str]) -> str:
    return ("HyperFrames báo lỗi khi kiểm tra composition của bạn:\n- " + "\n- ".join(errors)[:3000] +
            "\n\nSửa lỗi và trả lại ĐẦY ĐỦ object JSON {\"css\", \"html\", \"js\"} trong một khối code ```json, "
            "giữ nguyên các quy tắc trước (không //, không dấu nháy kép trong mã).")


BANNED = re.compile(r"\b(Math\.random|Date\.now|new Date|setTimeout|setInterval|requestAnimationFrame|fetch|"
                    r"XMLHttpRequest|eval)\b|import\s*\(|<script|<iframe|https?://", re.I)


def parse_design(data) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("js"), str) or not data["js"].strip():
        raise HyperFramesError("Model không trả về thiết kế hợp lệ (cần css, html, js)")
    design = {k: str(data.get(k) or "") for k in ("css", "html", "js")}
    banned = BANNED.search(design["js"] + design["html"] + design["css"])
    if banned:
        raise HyperFramesError(f"Thiết kế dùng thứ không cho phép: {banned.group(0)}")
    return design


def write_project(folder: Path, base_video: Path, design: dict, *, captions: list, scenes: list, width: int,
                  height: int, duration: float, logo: Path | None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "base.mp4"
    if not target.exists():
        try:
            os.link(base_video, target)  # cùng ổ → không tốn thêm dung lượng
        except OSError:
            shutil.copy2(base_video, target)
    shutil.copy2(TOOLS_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js", folder / "gsap.min.js")
    if logo is not None:
        shutil.copy2(logo, folder / "logo.png")
    data = json.dumps({"CAPTIONS": captions, "SCENES": scenes}, ensure_ascii=False).replace("</", "<\\/")
    font_css = _font_css(folder)
    family = FONT_FAMILY if (folder / "fonts").is_dir() else FALLBACK_FAMILY  # không nháy: an toàn trong style='...'
    design = {k: force_font(nfc(v), family) for k, v in design.items()}
    html = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<style>
html,body{{margin:0;background:#000}}
#root{{position:relative;width:{width}px;height:{height}px;overflow:hidden}}
#base{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
{nfc(design['css'])}
{font_css}
</style></head>
<body>
<div id="root" data-composition-id="{COMP_ID}" data-width="{width}" data-height="{height}" data-start="0" data-duration="{duration:.3f}">
<video id="base" class="clip" data-start="0" data-duration="{duration:.3f}" data-track-index="0" src="base.mp4" data-has-audio="true" playsinline></video>
{nfc(design['html'])}
<script src="gsap.min.js"></script>
<script>
(function () {{
var D = {data};
window.CAPTIONS = D.CAPTIONS; window.SCENES = D.SCENES;
var CAPTIONS = D.CAPTIONS, SCENES = D.SCENES;
var tl = gsap.timeline({{ paused: true }});
window.__timelines = window.__timelines || {{}};
window.__timelines['{COMP_ID}'] = tl;
{nfc(design['js'])}
}})();
</script>
</div>
</body></html>
"""
    (folder / "index.html").write_text(html, "utf-8")
    return folder


def lint(folder: Path) -> list[str]:
    """Lỗi (severity=error) của `hyperframes lint --json`; [] = hợp lệ."""
    res = _run(["lint", ".", "--json"], folder, timeout=180)
    try:
        data = json.loads(res.stdout[res.stdout.index("{"):])
    except ValueError:
        return [res.stdout.strip()[-1500:] or "hyperframes lint lỗi"]
    return [f"{f.get('code', '')}: {f.get('message', '')}" + (f" (gợi ý: {f['fixHint']})" if f.get("fixHint") else "")
            for f in data.get("findings") or [] if str(f.get("severity", "")).lower() == "error"]


def render(folder: Path, out: Path, *, fps: int, check_cancel=None, timeout: int = 2400) -> Path:
    res = _run(["render", ".", "-o", str(out), "-f", str(fps), "-q", "standard", "--strict", "--quiet"], folder,
               timeout=timeout, check_cancel=check_cancel)
    if res.returncode != 0 or not out.is_file():
        raise HyperFramesError(f"HyperFrames dựng video lỗi: {res.stdout.strip()[-800:]}")
    return out
