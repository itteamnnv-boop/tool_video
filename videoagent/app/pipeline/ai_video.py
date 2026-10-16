"""Template video AI (Grok Imagine): điền biến vào prompt, chuẩn hoá video tải về thành final.mp4."""
import re
import shutil
from pathlib import Path

from .. import ffmpeg
from . import scene_dir_name

VAR_RE = re.compile(r"\{(\w+)\}")
EMPTY_QUOTE_LINE = re.compile(r"^\s*[“\"'‘]\s*[”\"'’]\s*$")


def collect_variables(template, raw: dict | None) -> dict:
    values = {v["key"]: (str((raw or {}).get(v["key"], "")).strip() or v.get("default", ""))[:300]
              for v in template.variables}
    missing = [v["label"] for v in template.variables if v.get("required", True) and not values[v["key"]]]
    if missing:
        raise ValueError("Hãy điền: " + ", ".join(missing))
    return values


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}


def collect_attachments(template, raw: dict | None) -> list[tuple[dict, Path]]:
    """Ảnh tham chiếu người dùng đính kèm, theo thứ tự khai báo trong meta.json."""
    out = []
    for spec in template.attachments:
        value = str((raw or {}).get(spec["key"]) or "").strip()
        if not value and spec.get("default"):  # ảnh mẫu đóng gói sẵn trong thư mục template
            out.append((spec, template.path / spec["default"]))
            continue
        if not value:
            if spec.get("required"):
                raise ValueError(f"Hãy chọn: {spec['label']}")
            continue
        path = Path(value)
        allowed = IMAGE_EXT | (VIDEO_EXT if spec.get("video") else set())
        if not path.is_file() or path.suffix.lower() not in allowed:
            raise ValueError(f"{spec['label']}: file không hợp lệ hoặc không còn tồn tại ({path.name})")
        out.append((spec, path))
    return out


def reference_sentence(specs: list[dict]) -> str:
    """Câu thêm vào cuối prompt, mô tả vai trò từng ảnh theo đúng thứ tự tải lên Grok."""
    if not specs:
        return ""
    parts = [f"image {i} = {s['role']}: {s['prompt']}" for i, s in enumerate(specs, 1)]
    return " Reference images are attached in this order — " + "; ".join(parts) + "."


def import_attachments(job_dir: Path, attachments: list[tuple[dict, Path]]) -> list[Path]:
    """Chép ảnh vào <video>/assets/; file video (layout) được cắt 1 khung hình ở giây thứ 1."""
    asset_dir = job_dir / "assets"
    asset_dir.mkdir(exist_ok=True)
    images = []
    for spec, src in attachments:
        if src.suffix.lower() in VIDEO_EXT:
            target = asset_dir / f"{spec['key']}.jpg"
            seek = "1" if ffmpeg.media_duration(src) > 1.5 else "0"
            ffmpeg.run(["-ss", seek, "-i", src, "-frames:v", "1", "-q:v", "2", target])
        else:
            target = asset_dir / f"{spec['key']}{src.suffix.lower()}"
            shutil.copy2(src, target)
        images.append(target)
    return images


BRIEF_LIMIT = 3500  # ký tự prompt mẫu đưa vào kịch bản (tránh prompt quá dài cho Gemini Browser)


def as_regular_job_form(template, variables: dict, attachments: list, form: dict) -> dict:
    """Gemini Browser: biến template video AI thành job thường — Gemini viết kịch bản từ prompt mẫu, app tự dựng.

    Ảnh sản phẩm người dùng tự chọn (không phải ảnh mẫu của template) → dựng kiểu 'Sản phẩm nổi' với ảnh đó.
    """
    facts = [f"- {v['label']}: {variables[v['key']]}" for v in template.variables if variables.get(v["key"])]
    topic = "\n".join([f"Tạo video quảng cáo theo mẫu “{template.name}”.", "Thông tin chính:", *facts, "",
                       "Kịch bản mẫu tham khảo (giữ ý tưởng, nhịp cảnh và lời thoại tiếng Việt):",
                       fill_prompt(template.prompt, variables)[:BRIEF_LIMIT]])
    out = {**form, "topic": topic, "template": "ai", "genre": "promo"}
    own_product = next((path for spec, path in attachments
                        if spec["key"] == "product" and template.path not in path.parents), None)
    if own_product is not None and own_product.suffix.lower() in IMAGE_EXT:
        out.update(genre="product_layout", product_style="showcase", product_files=[str(own_product)], layout_file="")
    return out


def fill_prompt(prompt: str, variables: dict) -> str:
    """Thay {Bien} bằng giá trị người dùng; đổi nháy thẳng thành nháy cong để không vỡ câu trích trong prompt."""
    def repl(match):
        value = variables.get(match.group(1))
        if value is None:  # không phải biến của template → giữ nguyên
            return match.group(0)
        return value.replace("'", "’").replace('"', "”")

    filled = VAR_RE.sub(repl, prompt)
    # biến tuỳ chọn để trống → bỏ dòng chỉ còn cặp ngoặc rỗng (vd. “”)
    return "\n".join(line for line in filled.split("\n") if not EMPTY_QUOTE_LINE.match(line))


TARGET_SIZE = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "2:3": (1080, 1620), "3:2": (1620, 1080)}


def _fit_filter(raw: Path, aspect: str) -> list[str]:
    """Video sai tỉ lệ (Grok bỏ qua lựa chọn, hoặc lấy theo ảnh đính kèm) → đưa về đúng khung, phần dư phủ nền mờ."""
    target = TARGET_SIZE.get(aspect)
    if not target:
        return []
    width, height = ffmpeg.video_size(raw)
    tw, th = target
    if abs(width / height - tw / th) < 0.02:
        return []
    graph = (f"[0:v]split[a][b];[a]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur=24:2[bg];"
             f"[b]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return ["-vf", graph]


def finalize(raw: Path, job_dir: Path, aspect: str = "9:16", log=None) -> dict:
    """H.264 + AAC chuẩn, đúng tỉ lệ khung, cân âm lượng (thêm track im lặng nếu không có tiếng), tạo thumbnail."""
    final = job_dir / "final.mp4"
    fit = _fit_filter(raw, aspect)
    if fit and log:
        width, height = ffmpeg.video_size(raw)
        log(f"Grok trả video {width}x{height} — đưa về đúng tỉ lệ {aspect} (nền mờ)", "warn")
    video = [*fit, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart"]
    if ffmpeg.has_audio(raw):
        ffmpeg.run(["-i", raw, *video, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "44100", final])
    else:
        ffmpeg.run(["-i", raw, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v:0", "-map", "1:a",
                    *video, "-c:a", "aac", "-shortest", final])
    duration = ffmpeg.media_duration(final)
    width, height = ffmpeg.video_size(final)
    sdir = job_dir / "scenes" / scene_dir_name(1)
    sdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, sdir / "scene.mp4")
    ffmpeg.run(["-ss", f"{duration * 0.4:.2f}", "-i", final, "-frames:v", "1", "-q:v", "3", sdir / "thumb.jpg"])
    return {"duration": round(duration, 3), "width": width, "height": height}
