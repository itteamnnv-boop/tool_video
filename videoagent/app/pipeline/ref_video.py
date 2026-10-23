"""Video tham khảo cho Studio: tải video (link YouTube / TikTok / Facebook… qua yt-dlp, hoặc file trên máy) → phân tích
ý tưởng (hook, cấu trúc cảnh theo thời gian, nhịp dựng, phong cách hình, góc máy, lời thoại, âm thanh) → bản tóm tắt
tiếng Việt sửa được, dùng (hoặc không) khi viết storyboard.

Ít tốn lượt AI: máy tự cắt các khung đổi cảnh (ffmpeg) ghép thành 1 ảnh lưới có ghi mốc giây + đếm số cảnh cắt, lấy
tiêu đề / mô tả / phụ đề (nếu link có) → hỏi model MỘT lần. Model xem được hình: Gemini (trình duyệt / API),
Claude / OpenAI API; model khác chỉ đọc chữ (tiêu đề, mô tả, phụ đề, số liệu nhịp dựng).
"""
import base64
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .. import ffmpeg

VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
MAX_SECONDS = 15 * 60          # video dài hơn chỉ phân tích 15 phút đầu
MAX_BYTES = 400 * 1024 * 1024  # giới hạn tải về
SHEET_FRAMES = 12              # số khung trên ảnh lưới
DIR_NAME = "_studio_refvideo"
VISION_MODELS = ("gemini_browser", "gemini_api")  # + mọi "api:<claude / gpt>"
MODES = {"inspire": "Lấy cảm hứng — cấu trúc, nhịp, cách mở / kết, phong cách hình",
         "close": "Bám sát — làm kịch bản tương tự (cùng cấu trúc, nhịp) cho sản phẩm / nội dung của tôi"}


class RefVideoError(RuntimeError):
    pass


def is_link(source: str) -> bool:
    return bool(re.match(r"https?://", (source or "").strip(), re.I))


def can_see_images(model: str) -> bool:
    return model in VISION_MODELS or model.startswith("api:")


# ---------------------------------------------------------------- lấy video
def _vtt_text(path: Path) -> str:
    """Phụ đề .vtt / .srt → chữ (bỏ mốc thời gian, thẻ, dòng lặp của phụ đề tự động)."""
    out, last = [], ""
    for line in path.read_text("utf-8", errors="replace").splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or "-->" in line or line.isdigit() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if line != last:
            out.append(line)
            last = line
    return " ".join(out)[:6000]


def fetch(source: str, work: Path, log) -> dict:
    """Link → tải video (≤720p) + tiêu đề, mô tả, phụ đề; file → kiểm tra. Trả về {path, title, description, duration,
    subtitles, uploader}."""
    source = (source or "").strip()
    work.mkdir(parents=True, exist_ok=True)
    if not is_link(source):
        path = Path(source)
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXT:
            raise RefVideoError("Chọn file video (.mp4, .mov, .webm…) hoặc dán link video")
        return {"path": path, "title": path.stem, "description": "", "duration": ffmpeg.media_duration(path),
                "subtitles": "", "uploader": ""}
    try:
        import yt_dlp
    except ImportError as exc:
        raise RefVideoError("Thiếu thư viện yt-dlp — chạy: pip install yt-dlp") from exc
    log("Đang tải video tham khảo từ link…")
    opts = {"outtmpl": str(work / "video.%(ext)s"), "quiet": True, "no_warnings": True, "noprogress": True,
            "noplaylist": True, "max_filesize": MAX_BYTES, "merge_output_format": "mp4", "no_color": True,
            "format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
            # ít ngôn ngữ phụ đề (không lấy bản dịch tự động en-*, vi-*) để YouTube không chặn 429 "Too Many Requests"
            "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["vi", "en"],
            # trỏ thẳng file exe: ffmpeg của imageio tên "ffmpeg-win-x86_64-v….exe" → trỏ thư mục thì yt-dlp không thấy
            # (lỗi "requested merging of multiple formats but ffmpeg is not installed")
            "subtitlesformat": "vtt/srt/best", "ffmpeg_location": str(ffmpeg.FFMPEG)}
    clean = lambda exc: re.sub(r"\x1b\[[0-9;]*m|\[[0-9;]*m", "", str(exc)).strip()[-300:]  # noqa: E731 — bỏ mã màu
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source, download=True)
    except Exception as exc:  # yt-dlp ném nhiều kiểu lỗi (link riêng tư, cần đăng nhập, bị chặn…)
        if not re.search(r"subtitle|429|Too Many Requests", clean(exc), re.I):
            raise RefVideoError(f"Không tải được video từ link: {clean(exc)}") from exc
        # chỉ phụ đề lỗi / bị chặn → tải lại video KHÔNG kèm phụ đề (phân tích vẫn chạy bằng hình)
        log("Không tải được phụ đề (máy chủ chặn tạm thời) — tải video không kèm phụ đề…")
        for f in work.glob("video*"):
            f.unlink(missing_ok=True)
        opts.update(writesubtitles=False, writeautomaticsub=False)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source, download=True)
        except Exception as exc2:
            raise RefVideoError(f"Không tải được video từ link: {clean(exc2)}") from exc2
    files = [p for p in work.glob("video.*") if p.suffix.lower() in VIDEO_EXT]
    if not files:
        raise RefVideoError("Tải xong nhưng không thấy file video (link có thể là ảnh / bài viết)")
    subs = next((p for p in sorted(work.glob("video*.vtt")) + sorted(work.glob("video*.srt"))), None)
    return {"path": files[0], "title": str(info.get("title") or "")[:200],
            "description": str(info.get("description") or "")[:2000],
            "duration": float(info.get("duration") or 0) or ffmpeg.media_duration(files[0]),
            "subtitles": _vtt_text(subs) if subs else "", "uploader": str(info.get("uploader") or "")[:100]}


# ---------------------------------------------------------------- khung hình + nhịp dựng
def _scene_times(video: Path, limit: float) -> list[float]:
    """Mốc đổi cảnh (ffmpeg scene detection)."""
    import subprocess

    proc = subprocess.run([ffmpeg.FFMPEG, "-hide_banner", "-t", f"{limit:.1f}", "-i", str(video), "-vf",
                           "scale=320:-2,select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def contact_sheet(video: Path, work: Path, duration: float) -> tuple[Path, dict]:
    """Ảnh lưới SHEET_FRAMES khung (đầu video + các mốc đổi cảnh, rải đều) có ghi mốc giây + số liệu nhịp dựng."""
    from PIL import Image, ImageDraw

    limit = min(duration or MAX_SECONDS, MAX_SECONDS)
    cuts = _scene_times(video, limit)
    picks = sorted({0.3, *cuts})
    if len(picks) > SHEET_FRAMES:
        step = len(picks) / SHEET_FRAMES
        picks = [picks[int(i * step)] for i in range(SHEET_FRAMES)]
    if len(picks) < min(SHEET_FRAMES, max(4, int(limit // 3))):  # ít cảnh cắt → rải đều thêm
        picks = sorted({*picks, *(limit * (i + 0.5) / SHEET_FRAMES for i in range(SHEET_FRAMES))})[:SHEET_FRAMES]
    kept = []
    for t in picks:  # bỏ khung quá sát nhau (gần như trùng hình)
        if not kept or t - kept[-1] >= 0.6:
            kept.append(t)
    picks = kept
    thumbs = []
    for i, t in enumerate(picks):
        out = work / f"f{i:02d}.jpg"
        try:
            ffmpeg.run(["-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", out])
            thumbs.append((t, Image.open(out).convert("RGB")))
        except Exception:  # khung lỗi (cuối video) → bỏ qua
            continue
    if not thumbs:
        raise RefVideoError("Không cắt được khung hình nào từ video")
    w = max(im.width for _, im in thumbs)
    h = max(im.height for _, im in thumbs)
    cols = 4 if w <= h else 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for k, (t, im) in enumerate(thumbs):
        x, y = (k % cols) * w, (k // cols) * h
        sheet.paste(im, (x, y))
        label = f"{int(t // 60)}:{int(t % 60):02d}"
        draw.rectangle([x + 6, y + 6, x + 76, y + 34], fill=(0, 0, 0))
        draw.text((x + 12, y + 10), label, fill=(255, 220, 0))
    path = work / "sheet.jpg"
    sheet.save(path, quality=82)
    shots = max(1, len(cuts) + 1)
    return path, {"duration": round(duration, 1), "cuts": len(cuts), "avg_shot": round(limit / shots, 1),
                  "frames": [round(t, 1) for t, _ in thumbs], "vertical": h > w}


# ---------------------------------------------------------------- hỏi model
PROMPT = """Bạn là đạo diễn video ngắn. Hãy PHÂN TÍCH video tham khảo dưới đây để người dùng lấy ý tưởng làm video của họ.
{sheet_note}
Thông tin video:
- Tiêu đề: {title}
- Kênh: {uploader}
- Thời lượng: {duration} giây · khung {orient} · {cuts} lần cắt cảnh · trung bình {avg_shot} giây / cảnh
- Mô tả: {description}
- Phụ đề / lời thoại (nếu có): {subtitles}

Trả về MỘT object JSON (tiếng Việt, không markdown) — đây là VẬT LIỆU để dựng lại video, càng cụ thể càng tốt:
{{"chu_de": "video nói về gì, cho ai", "hook": "3 giây đầu gây chú ý thế nào",
 "canh": [{{"tu": 0, "den": 5, "noi_dung": "chuyện gì xảy ra, ai làm gì, cầm / giới thiệu gì",
   "hinh": "cỡ cảnh, góc máy, chuyển động máy, bố cục", "loi": "lời nói / thoại trong đoạn này (theo phụ đề nếu có, nếu
   không thì tóm ý)", "chu": "chữ hiện trên màn (nếu có)"}}],
 "nhan_vat": [{{"ten": "vai (vd. cô bán hàng)", "mo_ta": "ngoại hình, trang phục, thần thái"}}],
 "san_pham": "sản phẩm xuất hiện: loại, bao bì, cách cầm / trưng bày", "boi_canh": "địa điểm, đạo cụ, giao diện phủ
 (livestream, bình luận…) nếu có",
 "nhip": "nhịp dựng, độ dài cảnh, chuyển cảnh", "phong_cach": "màu, ánh sáng, bố cục, kiểu quay",
 "loi_thoai": "kiểu lời dẫn / thoại, giọng điệu, câu chốt", "am_thanh": "nhạc, hiệu ứng (đoán nếu không nghe được)",
 "diem_hay": ["điểm nên học"], "goi_y": "cách áp dụng cho video mới"}}
"canh" chia theo các đoạn / cảnh thật của video (khớp mốc giây trong ảnh lưới), tối đa 12 đoạn."""
MATERIAL_SCENES = 12
MATERIAL_KEYS = ("chu_de", "hook", "san_pham", "boi_canh", "nhip", "phong_cach", "loi_thoai", "am_thanh", "goi_y")


def clean_materials(raw) -> dict | None:
    """Vật liệu phân tích được (người dùng sửa được): trường chữ + nhân vật + từng cảnh. Không có gì → None."""
    if not isinstance(raw, dict):
        return None
    text = lambda v, n: " ".join(str(v or "").split())[:n]  # noqa: E731
    out = {k: text(raw.get(k), 1200) for k in MATERIAL_KEYS}
    rows = raw.get("canh") if isinstance(raw.get("canh"), list) else raw.get("cau_truc")
    scenes = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sc = {"tu": _num(r.get("tu")), "den": _num(r.get("den")), "noi_dung": text(r.get("noi_dung"), 600),
              "hinh": text(r.get("hinh"), 400), "loi": str(r.get("loi") or "").strip()[:800], "chu": text(r.get("chu"), 200)}
        if sc["noi_dung"] or sc["loi"] or sc["hinh"]:
            scenes.append(sc)
    out["canh"] = scenes[:MATERIAL_SCENES]
    out["nhan_vat"] = [{"ten": text(c.get("ten"), 60), "mo_ta": text(c.get("mo_ta"), 400)}
                       for c in raw.get("nhan_vat") or [] if isinstance(c, dict) and (c.get("ten") or c.get("mo_ta"))][:6]
    out["diem_hay"] = [text(x, 200) for x in raw.get("diem_hay") or [] if str(x).strip()][:8]
    return out if out["canh"] or any(out[k] for k in MATERIAL_KEYS) else None


def _num(v) -> float:
    try:
        return round(max(0.0, float(v)), 1)
    except (TypeError, ValueError):
        return 0.0


def _format(data: dict) -> str:
    parts = [p for p in (f"Chủ đề: {data.get('chu_de') or ''}", f"Hook: {data.get('hook') or ''}")
             if p.split(":", 1)[1].strip()]
    rows = data.get("canh") or data.get("cau_truc") or []
    if rows:
        parts.append("Cấu trúc:")
        for r in rows[:20]:
            if isinstance(r, dict):
                parts.append(f"- {r.get('tu', '?')}–{r.get('den', '?')}s: {r.get('noi_dung', '')}"
                             + (f" ({r.get('hinh')})" if r.get("hinh") else "")
                             + (f" — lời: “{r.get('loi')}”" if r.get("loi") else "")
                             + (f" — chữ trên màn: “{r.get('chu')}”" if r.get("chu") else ""))
    if data.get("nhan_vat"):
        parts.append("Nhân vật: " + "; ".join(f"{c.get('ten', '')}: {c.get('mo_ta', '')}" for c in data["nhan_vat"]
                                               if isinstance(c, dict)))
    for key, label in (("san_pham", "Sản phẩm"), ("boi_canh", "Bối cảnh"), ("nhip", "Nhịp dựng"),
                       ("phong_cach", "Phong cách hình"), ("loi_thoai", "Lời thoại"), ("am_thanh", "Âm thanh")):
        if data.get(key):
            parts.append(f"{label}: {data[key]}")
    if data.get("diem_hay"):
        parts.append("Điểm hay: " + "; ".join(str(x) for x in data["diem_hay"][:8]))
    if data.get("goi_y"):
        parts.append(f"Gợi ý áp dụng: {data['goi_y']}")
    return "\n".join(parts)[:5000]


def ask(model: str, prompt: str, sheet: Path | None, settings, *, profile: str, show_browser: bool, log,
        check_cancel) -> str:
    """Hỏi model (kèm ảnh lưới nếu model xem được hình)."""
    from ..browser_profiles import task_context
    from ..llm import make_provider

    if model.startswith("api:"):
        from ..campaign.ai import RoleAI

        pictures = [base64.b64encode(sheet.read_bytes()).decode()] if sheet else []
        return RoleAI("studio", log, check_cancel).complete(model[4:], "Bạn là đạo diễn video ngắn.", prompt,
                                                            max_tokens=4000, pictures=pictures)[0]
    provider = make_provider(model, settings, show_browser=show_browser)
    if provider is None:
        raise RefVideoError("Model phân tích không hợp lệ")
    images = None
    if sheet and provider.supports_images:
        images = [(sheet.read_bytes(), "image/jpeg")] if model == "gemini_api" else [str(sheet)]
    with task_context(profile, check_cancel=check_cancel, log=log):
        if model == "gemini_api":
            return provider.generate(prompt, images=images)
        return provider.generate(prompt, images=images, complete=lambda t: '"canh"' in t or "cau_truc" in t)


def analyze(source: str, settings, *, model: str, profile: str = "", show_browser: bool = False, log=None,
            check_cancel=None) -> dict:
    """Toàn bộ: lấy video → ảnh lưới + nhịp dựng → model → {source, title, duration, brief, sheet (đường dẫn)}."""
    from ..llm.base import extract_json

    log = log or (lambda *a, **k: None)
    check_cancel = check_cancel or (lambda: None)
    work = Path(settings.output_dir) / DIR_NAME / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    meta = fetch(source, work, log)
    check_cancel()
    log("Đang cắt khung hình + đo nhịp dựng…")
    sheet, stats = contact_sheet(Path(meta["path"]), work, float(meta["duration"] or 0))
    vision = can_see_images(model)
    prompt = PROMPT.format(
        sheet_note=("Ảnh đính kèm là lưới các khung hình chính theo thứ tự thời gian (số vàng góc trái = phút:giây)."
                    if vision else "(Model không xem được hình — chỉ dựa vào thông tin chữ và số liệu nhịp dựng.)"),
        title=meta["title"] or "(không có)", uploader=meta["uploader"] or "(không rõ)", duration=stats["duration"],
        orient="dọc" if stats["vertical"] else "ngang", cuts=stats["cuts"], avg_shot=stats["avg_shot"],
        description=" ".join(meta["description"].split())[:1500] or "(không có)",
        subtitles=meta["subtitles"][:5000] or "(không có — video không có phụ đề)")
    log(f"Đang nhờ {model} phân tích video ({'xem cả hình' if vision else 'chỉ đọc chữ'})…")
    text = ask(model, prompt, sheet if vision else None, settings, profile=profile, show_browser=show_browser,
               log=log, check_cancel=check_cancel)
    try:
        data = extract_json(text)
    except ValueError:
        data = None
    brief = _format(data) if isinstance(data, dict) else " ".join(str(text).split())[:5000]
    if not brief.strip():
        raise RefVideoError("Model không trả về phân tích — thử lại hoặc đổi model (Gemini xem được hình)")
    head = (f"Video tham khảo: {meta['title']} · {stats['duration']:.0f}s · {stats['cuts']} lần cắt cảnh · "
            f"~{stats['avg_shot']}s / cảnh")
    materials = clean_materials(data)
    result = {"source": source.strip(), "title": meta["title"], "duration": stats["duration"],
              "brief": f"{head}\n{brief}", "sheet": str(sheet), "vision": vision,
              **({"data": materials} if materials else {})}
    (work / "brief.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    if is_link(source):  # chỉ giữ ảnh lưới + phân tích; xoá video đã tải
        for f in work.glob("video.*"):
            f.unlink(missing_ok=True)
    for f in work.glob("f[0-9][0-9].jpg"):
        f.unlink(missing_ok=True)
    log("Đã phân tích video tham khảo", "ok")
    return result


def clean(raw) -> dict | None:
    """Dữ liệu video tham khảo lưu trong dự án (người dùng sửa được phần tóm tắt)."""
    if not isinstance(raw, dict):
        return None
    materials = clean_materials(raw.get("data"))
    brief = str(raw.get("brief") or "").strip()
    if materials:  # vật liệu là bản gốc người dùng sửa → tóm tắt dựng lại từ vật liệu (luôn khớp nhau)
        head = brief.splitlines()[0] if brief.startswith("Video tham khảo:") else f"Video tham khảo: {raw.get('title') or ''}"
        brief = f"{head}\n{_format(materials)}"
    if not brief:
        return None
    return {"source": str(raw.get("source") or "")[:1000], "title": str(raw.get("title") or "")[:200],
            "duration": float(raw.get("duration") or 0), "brief": brief[:8000],
            "sheet": str(raw.get("sheet") or "")[:1000], "vision": bool(raw.get("vision")),
            **({"data": materials} if materials else {})}


def materials_block(ref: dict | None) -> str:
    """Nguồn kịch bản = video phân tích: toàn bộ vật liệu (đã duyệt) để CHUYỂN THỂ thành storyboard."""
    data = (ref or {}).get("data")
    if not data:
        return f"<vat_lieu_video>\n{(ref or {}).get('brief') or ''}\n</vat_lieu_video>"
    lines = [f"{label}: {data[k]}" for k, label in (
        ("chu_de", "Chủ đề"), ("hook", "Hook"), ("san_pham", "Sản phẩm"), ("boi_canh", "Bối cảnh"),
        ("phong_cach", "Phong cách hình"), ("nhip", "Nhịp dựng"), ("loi_thoai", "Kiểu lời thoại"),
        ("am_thanh", "Âm thanh"), ("goi_y", "Ghi chú")) if data.get(k)]
    if data.get("nhan_vat"):
        lines.append("Nhân vật: " + "; ".join(f"{c['ten']} — {c['mo_ta']}" for c in data["nhan_vat"]))
    for i, sc in enumerate(data.get("canh") or [], 1):
        lines.append(f"Cảnh {i} ({sc['tu']:g}–{sc['den']:g}s): {sc['noi_dung']}"
                     + (f" | Hình: {sc['hinh']}" if sc["hinh"] else "") + (f" | Lời: “{sc['loi']}”" if sc["loi"] else "")
                     + (f" | Chữ trên màn: “{sc['chu']}”" if sc["chu"] else ""))
    return "<vat_lieu_video>\n" + "\n".join(lines) + "\n</vat_lieu_video>"


def storyboard_block(ref: dict | None, mode: str) -> str:
    """Đoạn chèn vào prompt viết storyboard."""
    if not ref or not ref.get("brief"):
        return ""
    how = ("BÁM SÁT cấu trúc từng đoạn, thời lượng, nhịp dựng, kiểu mở đầu / kết và kiểu lời thoại của video tham khảo, "
           "nhưng thay bằng sản phẩm, nhân vật, thông điệp theo ý tưởng của người dùng") if mode == "close" else (
           "LẤY CẢM HỨNG từ cấu trúc, nhịp dựng, cách mở đầu (hook) / kết, phong cách hình và góc máy của video tham "
           "khảo; nội dung theo ý tưởng của người dùng")
    return (f"VIDEO THAM KHẢO — {how}. KHÔNG chép nguyên văn lời thoại, tên thương hiệu, nhân vật hay logo của video đó.\n"
            f"<video_tham_khao>\n{ref['brief']}\n</video_tham_khao>")


def copy_sheet(ref: dict | None, dest_dir: Path) -> dict | None:
    """Chép ảnh lưới vào thư mục dự án (đường dẫn tương đối cho giao diện)."""
    if not ref:
        return None
    src = Path(ref.get("sheet") or "")
    if src.is_file() and src.parent != dest_dir:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / "ref_video.jpg"
        shutil.copy2(src, target)
        return {**ref, "sheet": str(target)}
    return ref
