"""Template video AI (Grok Imagine): điền biến vào prompt, chuẩn hoá video tải về thành final.mp4."""
import hashlib
import re
import shutil
from pathlib import Path

from .. import ffmpeg
from . import scene_dir_name

VAR_RE = re.compile(r"\{(\w+)\}")
EMPTY_QUOTE_LINE = re.compile(r"^\s*[“\"'‘]\s*[”\"'’]\s*$")


def collect_variables(template, raw: dict | None) -> dict:
    values = {v["key"]: (str((raw or {}).get(v["key"], "")).strip() or v.get("default", ""))[:int(v.get("max") or 300)]
              for v in template.variables}  # "max" trong meta.json: độ dài tối đa của biến (mặc định 300 ký tự)
    missing = [v["label"] for v in template.variables if v.get("required", True) and not values[v["key"]]]
    if missing:
        raise ValueError("Hãy điền: " + ", ".join(missing))
    return values


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}


def file_digest(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dedupe_attachments(attachments: list[tuple[dict, Path]], log=None) -> list[tuple[dict, Path]]:
    """Bỏ file đính kèm trùng NỘI DUNG (cùng một ảnh ở 2 vai trò, vd. ảnh ⭐ nhân vật trùng ảnh mẫu layout / ảnh dàn cảnh,
    hoặc ảnh dự án trùng ảnh nhân vật) — ChatGPT… thấy 2 ảnh giống hệt sẽ từ chối / đòi gửi lại. Vai trò của ảnh bị bỏ
    gộp vào ảnh giữ lại (câu "Reference images are attached in this order…" vẫn khớp thứ tự). Logo luôn giữ vị trí cuối."""
    out: list[tuple[dict, Path]] = []
    keys: list[str] = []
    for spec, path in attachments:
        try:
            key = file_digest(Path(path))
        except OSError:
            key = str(path)
        if key not in keys:
            out.append((spec, path))
            keys.append(key)
            continue
        i = keys.index(key)
        kept, kept_path = out[i]
        merged_role = " + ".join(x for x in (kept.get("role"), spec.get("role")) if x)
        merged_prompt = "; also ".join(x for x in (kept.get("prompt"), spec.get("prompt")) if x)
        if "logo" in str(spec.get("role") or "").lower():  # ảnh trùng là logo → dời về cuối (prompt: ảnh cuối là logo)
            out.pop(i)
            keys.pop(i)
            out.append(({**spec, "role": merged_role, "prompt": merged_prompt}, path))
            keys.append(key)
        else:
            out[i] = ({**kept, "role": merged_role, "prompt": merged_prompt}, kept_path)
        if log:
            log(f"Bỏ ảnh đính kèm trùng: “{spec.get('label') or spec.get('role')}” giống hệt "
                f"“{kept.get('label') or kept.get('role')}” — gửi 1 lần, gộp vai trò", "warn")
    return out


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
        allowed = VIDEO_EXT if spec.get("keep_video") else IMAGE_EXT | (VIDEO_EXT if spec.get("video") else set())
        if not path.is_file() or path.suffix.lower() not in allowed:
            raise ValueError(f"{spec['label']}: file không hợp lệ hoặc không còn tồn tại ({path.name})")
        out.append((spec, path))
    return out


def reference_sentence(specs: list[dict]) -> str:
    """Câu thêm vào cuối prompt, mô tả vai trò từng ảnh/video theo đúng thứ tự tải lên Grok."""
    if not specs:
        return ""
    parts = [f"{'video' if s.get('keep_video') else 'image'} {i} = {s['role']}: {s['prompt']}"
             for i, s in enumerate(specs, 1)]
    noun = "files" if any(s.get("keep_video") for s in specs) else "images"
    return f" Reference {noun} are attached in this order — " + "; ".join(parts) + "."


def import_attachments(job_dir: Path, attachments: list[tuple[dict, Path]]) -> list[Path]:
    """Chép ảnh vào <video>/assets/; file video (layout) được cắt 1 khung hình ở giây thứ 1,
    trừ khi spec có keep_video (video gốc gửi nguyên file cho engine)."""
    asset_dir = job_dir / "assets"
    asset_dir.mkdir(exist_ok=True)
    images = []
    for spec, src in attachments:
        if src.suffix.lower() in VIDEO_EXT and not spec.get("keep_video"):
            target = asset_dir / f"{spec['key']}.jpg"
            seek = "1" if ffmpeg.media_duration(src) > 1.5 else "0"
            ffmpeg.run(["-ss", seek, "-i", src, "-frames:v", "1", "-q:v", "2", target])
        else:
            target = asset_dir / f"{spec['key']}{src.suffix.lower()}"
            shutil.copy2(src, target)
        images.append(target)
    return images


# Template nhiều bước (image_steps): các bước tạo ảnh chạy lần lượt trước khi tạo video. Mỗi bước
# {key, label, engine, aspect, prompt, inputs}; inputs trỏ tới file người dùng đính kèm hoặc kết quả bước trước
# (theo key). video_inputs chọn file gửi cho bước tạo video. `files` = {key: (spec, path)}.

def step_inputs(step: dict, files: dict) -> list[tuple[dict, Path]]:
    """Ảnh gửi cho một bước tạo ảnh — file video được cắt 1 khung hình (nhân vật + bối cảnh)."""
    out = []
    for item in step.get("inputs", []):
        if item["key"] in files:
            spec, path = files[item["key"]]
            out.append(({**spec, **item, "key": f"{step['key']}_{item['key']}", "keep_video": False}, path))
    return out


def video_inputs(template, files: dict) -> list[tuple[dict, Path]]:
    """File gửi cho bước tạo video theo video_inputs (role/prompt của mục ghi đè spec gốc)."""
    return [({**files[item["key"]][0], **item}, files[item["key"]][1])
            for item in template.video_inputs if item["key"] in files]


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


def has_video_reference(attachments: list[tuple[dict, Path]]) -> bool:
    """Ô tham chiếu (send_video) là file video VÀ được gửi nguyên video (prepare_video_refs: model nhận được video)."""
    return any(spec.get("send_video") and spec.get("keep_video") and Path(path).suffix.lower() in VIDEO_EXT
               for spec, path in attachments)


def template_prompt(template, variables: dict, attachments: list[tuple[dict, Path]], override: str = "") -> str:
    """Prompt template đã điền biến:
    - có video tham chiếu và template có video_prompt → dùng prompt riêng cho video tham chiếu;
    - biến tự ghép (computed, vd. {FULL_SCRIPT} = các câu thoại nối lại) điền sau các biến người dùng nhập;
    - biến tuỳ chọn để trống → bỏ cả dòng chứa nó; override = prompt đã sửa riêng (workflow)."""
    values = dict(variables)
    for key, pattern in (template.computed or {}).items():
        values[key] = " ".join(fill_prompt(pattern, variables).split())
    source = override or (template.video_prompt if template.video_prompt and has_video_reference(attachments)
                          else template.prompt)
    empty = [f"{{{k}}}" for k, value in values.items() if not str(value).strip()]
    source = "\n".join(line for line in source.split("\n") if not any(m in line for m in empty))
    return fill_prompt(source, values)


def prepare_video_refs(attachments: list[tuple[dict, Path]], engine_spec: dict, log=None) -> list[tuple[dict, Path]]:
    """Ô send_video là file video: model nhận được video (Grok / Dola) → gửi nguyên video (keep_video);
    model khác → giữ như cũ (cắt 1 khung hình làm ảnh tham chiếu)."""
    out = []
    for spec, path in attachments:
        if spec.get("send_video") and Path(path).suffix.lower() in VIDEO_EXT:
            if engine_spec.get("video_input"):
                spec = {**spec, "keep_video": True, "role": spec.get("video_role", spec["role"]),
                        "prompt": spec.get("video_prompt", spec["prompt"])}
            elif log:
                log(f"{engine_spec.get('name', 'Model')} không nhận file video — dùng 1 khung hình của "
                    f"“{spec.get('label', spec['key'])}” làm ảnh tham chiếu (nên chọn Grok hoặc Dola)", "warn")
        out.append((spec, path))
    return out


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
