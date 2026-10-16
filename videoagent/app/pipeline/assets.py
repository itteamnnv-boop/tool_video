"""Tài liệu mẫu người dùng tải lên cho thể loại "Theo layout & sản phẩm mẫu".

- Layout là ảnh (PNG/JPG/WEBP) → làm nền, lấy tông màu cho template showcase.
- Layout là HTML → dùng làm template Jinja2 (cùng biến như template có sẵn).
- Ảnh sản phẩm (1..10) → chép vào <video>/assets/, lần lượt xuất hiện qua các khung.
"""
import colorsys
import shutil
import subprocess
from pathlib import Path

from .. import ffmpeg
from ..ffmpeg import FFmpegError
from ..templates_registry import Template
from .scene_context import DEFAULT_PALETTE, VIDEO_EXT, is_video_name

PRODUCT_GENRE = "product_layout"
# Kiểu video của thể loại sản phẩm → template (khi không tải layout HTML)
STYLE_TEMPLATES = {"showcase": "san-pham-showcase", "presenter": "nguoi-mau-gioi-thieu", "reel": "reel-ban-hang"}
VIDEO_STYLES = {"presenter", "reel"}  # kiểu dùng được video quay thật làm nền
MAX_VIDEO_BYTES = 500 * 1024 * 1024
PRESENTER_GUIDE = ("Phong cách: video TikTok bán hàng, người mẫu/nhân viên shop cầm sản phẩm nói trực tiếp với khách "
                   "(xưng em, gọi khách là anh chị/cả nhà), thân thiện, tự nhiên như livestream.\n")
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
HTML_EXT = {".html", ".htm"}
MAX_PRODUCTS = 10
MAX_IMAGE_BYTES = 15 * 1024 * 1024


class AssetError(ValueError):
    pass


def validate(layout_file: str, product_files, style: str = "showcase") -> tuple[Path | None, list[Path]]:
    products = [Path(p) for p in (product_files or []) if p]
    if not products:
        raise AssetError("Hãy chọn ít nhất 1 ảnh/video sản phẩm")
    if len(products) > MAX_PRODUCTS:
        raise AssetError(f"Tối đa {MAX_PRODUCTS} ảnh/video sản phẩm")
    for path in products:
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in IMAGE_EXT and suffix not in VIDEO_EXT:
            raise AssetError(f"File sản phẩm không hợp lệ hoặc không còn tồn tại: {path.name}")
        if suffix in VIDEO_EXT:
            if style not in VIDEO_STYLES:
                raise AssetError("Kiểu 'Sản phẩm nổi' chỉ dùng ảnh — chọn kiểu 'Người mẫu' hoặc 'Reel bán hàng' để dùng video")
            if path.stat().st_size > MAX_VIDEO_BYTES:
                raise AssetError(f"Video quá lớn (>500 MB): {path.name}")
        elif path.stat().st_size > MAX_IMAGE_BYTES:
            raise AssetError(f"Ảnh quá lớn (>15 MB): {path.name}")
    layout = Path(layout_file) if layout_file else None
    if layout is not None and (not layout.is_file() or layout.suffix.lower() not in IMAGE_EXT.keys() | HTML_EXT):
        raise AssetError(f"Layout mẫu không hợp lệ hoặc không còn tồn tại: {layout.name}")
    return layout, products


def images_for_ai(products: list[Path]) -> list[tuple[bytes, str]]:
    return [(p.read_bytes(), IMAGE_EXT[p.suffix.lower()]) for p in products if p.suffix.lower() in IMAGE_EXT]


def assign_media(job_dir: Path, scenes: list[dict], names: list[str]) -> None:
    """Gán đoạn video nền cho từng cảnh: cảnh dùng video lấy đoạn tiếp theo của clip (hết clip thì quay lại đầu)."""
    lengths, used = {}, {}
    for scene in scenes:
        scene.pop("media", None)
        name = names[(scene["index"] - 1) % len(names)]
        if not is_video_name(name):
            continue
        if name not in lengths:
            lengths[name] = ffmpeg.media_duration(job_dir / "assets" / name)
        start = used.get(name, 0.0)
        if start + scene["duration"] > lengths[name]:
            start = 0.0
        scene["media"] = {"file": name, "start": round(start, 3)}
        used[name] = start + scene["duration"]


def extract_audio(clip: Path, start: float, duration: float, out_path: Path) -> None:
    """Cắt tiếng gốc của clip cho một cảnh; clip không có tiếng thì tạo khoảng lặng."""
    try:
        ffmpeg.run(["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", clip, "-vn", "-ac", "2", "-ar", "44100",
                    "-af", f"apad=whole_dur={duration:.3f}", out_path])
    except FFmpegError:
        ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{duration:.3f}", out_path])


def import_assets(job_dir: Path, layout: Path | None, products: list[Path]) -> dict:
    asset_dir = job_dir / "assets"
    asset_dir.mkdir(exist_ok=True)
    names = []
    for i, src in enumerate(products, 1):
        name = f"product_{i}{src.suffix.lower()}"
        shutil.copy2(src, asset_dir / name)
        names.append(name)
    info = {"products": names, "layout_image": "", "layout_html": False}
    if layout is not None:
        if layout.suffix.lower() in HTML_EXT:
            (job_dir / "layout").mkdir(exist_ok=True)
            shutil.copy2(layout, job_dir / "layout" / "template.html")
            info["layout_html"] = True
        else:
            name = f"layout{layout.suffix.lower()}"
            shutil.copy2(layout, asset_dir / name)
            info["layout_image"] = name
    info["palette"] = palette_from_image(asset_dir / (info["layout_image"] or names[0]))
    return info


def custom_template(job_dir: Path) -> Template:
    return Template(id=f"custom-{job_dir.name}", name="Layout HTML tải lên", category="custom",
                    description="", path=job_dir / "layout")


def average_color(path: Path) -> tuple[int, int, int]:
    proc = subprocess.run(
        [ffmpeg.FFMPEG, "-v", "error", "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1:flags=area",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, creationflags=ffmpeg.NO_WINDOW,
    )
    if proc.returncode != 0 or len(proc.stdout) < 3:
        raise FFmpegError(f"Không đọc được màu ảnh: {path.name}")
    return proc.stdout[0], proc.stdout[1], proc.stdout[2]


def _hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def palette_from_image(path: Path) -> dict:
    """Tông màu chủ đạo của ảnh → accent sáng + nền tối cùng tông."""
    try:
        r, g, b = average_color(path)
    except FFmpegError:
        return dict(DEFAULT_PALETTE)
    h, _, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if s < 0.08:  # ảnh gần như xám → nền trung tính, accent mặc định
        return {**DEFAULT_PALETTE, "bg": "#0e0e0f", "bg2": "#26262a"}
    return {"accent": _hex(h, 0.62, max(s, 0.7)), "bg": _hex(h, 0.08, min(s, 0.45)), "bg2": _hex(h, 0.2, min(s, 0.55))}
