"""🧊 Hiệu ứng 3D (three.js) cho khối ✨ Edit Pro — lớp RIÊNG của app, chồng lên video sau khi skill render xong
(không sửa / chép mã skill). Claude chọn hiệu ứng trong plan.json (khoá "fx3d"); app tách khoá đó ra trước khi đưa plan
cho render.py, rồi:
  1) mở assets/fx3d/fx3d.html (three.js chạy offline) bằng Chromium headless, tua từng khung theo thời gian → PNG nền
     trong suốt → fx{k}.mov (png + alpha)
  2) ffmpeg ghép đè các lớp lên final.mp4 (+ bản điện thoại, tự co theo kích thước), giữ nguyên tiếng.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .. import ffmpeg
from ..paths import ASSETS_DIR

FX_DIR = ASSETS_DIR / "fx3d"
HOST = "http://fx3d.local/"
FPS = 30
MAX_FX = 6
MIN_LEN, MAX_LEN = 1.2, 5.0
POSITIONS = ("top", "center", "bottom", "low")
# loại → (mô tả cho Claude, cần chữ?, số ảnh tối đa (0 = không dùng ảnh), vị trí mặc định)
FX_TYPES = {
    "title_3d": ("thẻ chữ 3D xoay vào + vệt sáng quét — tiêu đề mở đầu / từ khoá lớn / CTA (\"text\" ≤ 40 ký tự)", True, 0, "top"),
    "card_flip": ("ảnh lật 3D trên thẻ viền kim loại (\"media\": 1 ảnh; \"text\" chú thích tuỳ chọn)", False, 1, "center"),
    "cube": ("khối lập phương xoay, mỗi mặt 1 ảnh (\"images\": 1–6 ảnh) — khoe nhiều kết quả / sản phẩm", False, 6, "center"),
    "product_spin": ("ảnh sản phẩm xoay nghiêng trên vòng sáng, có bóng phản chiếu (\"media\": 1 ảnh, PNG nền trong càng đẹp)",
                     False, 1, "center"),
    "particles": ("hạt sáng bung ra rồi rơi — nhấn khoảnh khắc chốt / ưu đãi (không cần chữ, ảnh)", False, 0, "center"),
    "rings": ("vòng sáng 3D xoay quanh, chữ ở giữa nếu có \"text\" — nhấn con số / lợi ích", False, 0, "center"),
}
# màu cho lớp 3D theo theme (accent = màu nhấn, base / light = nền lụa tối)
SKILL_COLORS = {"vang-den": dict(accent="#E6C27A", base=(12, 10, 6), light=(70, 56, 30)),
                "tim": dict(accent="#C9A2FF", base=(20, 8, 34), light=(88, 48, 140))}
LAUNCH_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

PROMPT_RULE = """
=== HIỆU ỨNG 3D (three.js — app chồng lên SAU khi render, tuỳ chọn) ===
Có thể thêm khoá "fx3d": [{{"type": "...", "start": giây, "end": giây, "text": "...", "media": "tên ảnh", "images": [...],
"pos": "top|center|bottom|low"}}] — TỐI ĐA {max_fx} hiệu ứng, mỗi cái {min_len:g}–{max_len:g} giây, KHÔNG chồng giờ nhau, không
trùng lúc cảnh minh hoạ (broll); đặt "pos" sao cho KHÔNG che mặt / miệng người nói (xem khung hình). Dùng tiết chế, đúng lúc
nhấn mạnh (mở đầu, con số, chốt CTA); không có lý do thì để []. Chỉ dùng ảnh ở mục TÀI NGUYÊN (không dùng clip). Các loại:
{types}"""


def prompt_rule() -> str:
    types = "\n".join(f'- "{k}": {v[0]}' for k, v in FX_TYPES.items())
    return PROMPT_RULE.format(max_fx=MAX_FX, min_len=MIN_LEN, max_len=MAX_LEN, types=types)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def take(plan: dict, images: set[str], duration: float) -> tuple[list[dict], list[str]]:
    """Tách khoá "fx3d" khỏi plan (render.py của skill không biết khoá này) → (hiệu ứng hợp lệ, cảnh báo)."""
    raw = plan.pop("fx3d", None)
    out, warn, last_end = [], [], -1.0
    items = [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []
    for x in sorted(items, key=lambda x: x.get("start") if _num(x.get("start")) else 1e9):
        kind = str(x.get("type") or "")
        if kind not in FX_TYPES or not _num(x.get("start")):
            warn.append(f"Bỏ hiệu ứng 3D không hợp lệ: {kind or '?'}")
            continue
        _, need_text, max_img, pos = FX_TYPES[kind]
        start = max(0.0, float(x["start"]))
        end = float(x["end"]) if _num(x.get("end")) else start + 2.5
        end = min(start + MAX_LEN, max(start + MIN_LEN, end), duration or 1e9)
        if end - start < MIN_LEN * 0.8 or start < last_end:
            warn.append(f"Bỏ hiệu ứng 3D {kind} lúc {start:g}s (quá ngắn / chồng giờ hiệu ứng trước)")
            continue
        text = " ".join(str(x.get("text") or "").split())[:60]
        names = [x["media"]] if x.get("media") else list(x.get("images") or [])
        names = [str(n) for n in names if str(n) in images][:max_img]
        if need_text and not text:
            warn.append(f"Bỏ hiệu ứng 3D {kind} lúc {start:g}s (thiếu chữ)")
            continue
        if max_img and not names:
            warn.append(f"Bỏ hiệu ứng 3D {kind} lúc {start:g}s (ảnh không có trong tài nguyên)")
            continue
        out.append({"type": kind, "start": round(start, 2), "end": round(end, 2), "text": text, "images": names,
                    "pos": x.get("pos") if x.get("pos") in POSITIONS else pos})
        last_end = end
        if len(out) >= MAX_FX:
            break
    return out, warn


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def colors(theme: str) -> dict:
    from .edit_pro import EXTRA_THEMES

    if theme in EXTRA_THEMES:
        p = EXTRA_THEMES[theme][1]
        c = dict(accent=p["accent"], base=p["silk_base"], light=p["silk_lite"])
    else:
        c = SKILL_COLORS.get(theme, SKILL_COLORS["vang-den"])
    return {"accent": c["accent"], "base": _hex(c["base"]), "light": _hex(c["light"])}


def _serve(work: Path):
    """Trang chạy dưới địa chỉ ảo (ES module không nạp được từ file://): /media/* → ảnh trong thư mục làm việc."""
    def handler(route):
        name = route.request.url[len(HOST):].split("?")[0]
        base, rel = (work, name[len("media/"):]) if name.startswith("media/") else (FX_DIR, name)
        path = (base / rel).resolve()
        if base.resolve() not in path.parents or not path.is_file():
            return route.fulfill(status=404, body="")
        ctype = "application/javascript" if path.suffix == ".js" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        route.fulfill(status=200, body=path.read_bytes(), headers={"Content-Type": ctype, "Access-Control-Allow-Origin": "*"})
    return handler


def _launch(pw, log):
    from playwright.sync_api import Error as PWError

    from .renderer import install_chromium

    try:
        return pw.chromium.launch(args=LAUNCH_ARGS)
    except PWError as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        log("Lần chạy đầu: đang tải Chromium (Playwright)…")
        install_chromium()
        return pw.chromium.launch(args=LAUNCH_ARGS)


CAPTURE_JS = "t => { window.__fx.seek(t); return document.querySelector('canvas').toDataURL('image/png').split(',')[1]; }"


def render_layers(fx: list[dict], size: tuple[int, int], work: Path, theme: str, log, check_cancel=None) -> list[tuple[Path, float]]:
    """Mỗi hiệu ứng → fx{k}.mov (PNG có kênh alpha, đúng kích thước video) → [(file, giây bắt đầu)]."""
    from playwright.sync_api import sync_playwright

    w, h = size
    pal = colors(theme)
    layers = []
    with sync_playwright() as pw:
        browser = _launch(pw, log)
        try:
            ctx = browser.new_context(viewport={"width": w // 2, "height": h // 2}, device_scale_factor=2)
            ctx.route(HOST + "**", _serve(work))
            for k, item in enumerate(fx, 1):
                if check_cancel:
                    check_cancel()
                dur = item["end"] - item["start"]
                log(f"Hiệu ứng 3D {k}/{len(fx)}: {item['type']} ({item['start']:g}–{item['end']:g}s)…")
                page = ctx.new_page()
                try:
                    page.goto(HOST + "fx3d.html", wait_until="load", timeout=30_000)
                    page.wait_for_function("() => window.__fxReady === true", timeout=30_000)
                    page.evaluate("async () => { await document.fonts.ready; }")
                    page.evaluate("s => window.__fx.setup(s)", {
                        "type": item["type"], "dur": dur, "text": item["text"], "pos": item["pos"], "colors": pal,
                        "images": [f"media/{n}" for n in item["images"]]})
                    dest = work / f"fx{k}.mov"
                    proc = ffmpeg.popen_stdin(["-f", "image2pipe", "-framerate", FPS, "-c:v", "png", "-i", "-",
                                               "-c:v", "png", "-pix_fmt", "rgba", dest])
                    try:
                        for i in range(max(1, round(dur * FPS))):
                            if check_cancel and i % 10 == 0:
                                check_cancel()
                            proc.stdin.write(base64.b64decode(page.evaluate(CAPTURE_JS, i / FPS)))
                        proc.stdin.close()
                        err = proc.stderr.read().decode("utf-8", "replace")
                        if proc.wait() != 0:
                            raise ffmpeg.FFmpegError(err[-800:] or "ffmpeg lỗi khi mã hoá lớp 3D")
                    except BaseException:
                        proc.kill()
                        proc.wait()
                        raise
                    layers.append((dest, item["start"]))
                finally:
                    page.close()
            ctx.close()
        finally:
            browser.close()
    return layers


def composite(video: Path, layers: list[tuple[Path, float]], dest: Path) -> None:
    """Ghép các lớp 3D lên video (co lớp theo kích thước video — dùng chung cho bản 1080p và bản điện thoại)."""
    w, h = ffmpeg.video_size(video)
    args, graph, cur = ["-i", video], [], "0:v"
    for k, (path, start) in enumerate(layers, 1):
        args += ["-i", path]
        graph.append(f"[{k}:v]setpts=PTS-STARTPTS+{start:.3f}/TB,scale={w}:{h}[f{k}]")
        graph.append(f"[{cur}][f{k}]overlay=0:0:eof_action=pass[v{k}]")
        cur = f"v{k}"
    graph.append(f"[{cur}]format=yuv420p[v]")
    ffmpeg.run([*args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "0:a?", "-c:a", "copy",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-movflags", "+faststart", dest])


def apply(fx: list[dict], videos: list[Path], work: Path, theme: str, log, check_cancel=None) -> None:
    """Chồng hiệu ứng 3D lên từng video (thay tại chỗ). Lớp 3D dựng 1 lần theo kích thước video đầu."""
    if not fx or not videos:
        return
    layers = render_layers(fx, ffmpeg.video_size(videos[0]), work, theme, log, check_cancel)
    for v in videos:
        tmp = v.with_name(v.stem + "_fx3d.mp4")
        composite(v, layers, tmp)
        tmp.replace(v)
