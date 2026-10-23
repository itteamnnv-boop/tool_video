"""HTTP server nội bộ (127.0.0.1): phục vụ giao diện, file video (hỗ trợ Range để tua) và xem trước template."""
import logging
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .config import settings
from .paths import CACHE_DIR, UI_DIR, DATA_DIR
from .pipeline import ASPECTS
from .templates_registry import registry
from .pipeline.scene_context import build_context

log = logging.getLogger(__name__)
CHUNK = 256 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8", ".json": "application/json",
         ".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png", ".svg": "image/svg+xml",
         ".mp3": "audio/mpeg", ".wav": "audio/wav"}
SAMPLE_SCENE = {
    "kicker": "CUNG CẦU CHAO ĐẢO", "headline": "Thị trường biến động mạnh hôm nay", "highlight": "biến động",
    "subtext": "Nhà đầu tư nín thở dõi theo từng nhịp nhảy múa của bảng điện tử.", "stat": "+3,2%",
    "trend": "up", "duration": 8,
}


def preview_html(template_id: str, aspect: str) -> str | None:
    template = registry.get(template_id)
    if template is None:
        return None
    scenes = [{**SAMPLE_SCENE, "index": i} for i in range(1, 5)]
    job = {"id": "preview", "title": "Xem trước template", "aspect": aspect if aspect in ASPECTS else "9:16",
           "scenes": scenes}
    return registry.render(template, build_context(job, scenes[0]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:
        log.debug(fmt, *args)

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        if path.startswith("/tpl/") and "/asset/" in path:
            template_id, name = path[len("/tpl/"):].split("/asset/", 1)
            template = registry.get(template_id)
            if template is None:
                return self.send_error(404)
            target = (template.path / name).resolve()
            if (not target.is_relative_to(template.path.resolve()) or not target.is_file()
                    or target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp")):
                return self.send_error(404)
            return self._send_file(target)
        if path.startswith("/tpl/") and path.endswith("/thumb"):
            template = registry.get(path[len("/tpl/"):-len("/thumb")])
            if template is None or template.thumb is None:
                return self.send_error(404)
            return self._send_file(template.thumb)
        if path.startswith("/tpl/") and path.endswith("/preview"):
            aspect = parse_qs(parts.query).get("aspect", ["9:16"])[0]
            html = preview_html(path[len("/tpl/"):-len("/preview")], aspect)
            if html is None:
                return self.send_error(404)
            return self._send_bytes(html.encode("utf-8"), TYPES[".html"])
        if path.startswith("/campaign-lib/"):
            # Thư viện chiến dịch: chỉ phục vụ ẢNH (không bao giờ trả keys.json hay file JSON khác)
            if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                return self.send_error(404)
            from .campaign import store as campaign_store

            base, rel = campaign_store.LIB, path[len("/campaign-lib/"):]
        elif path.startswith("/cast/"):
            # Nhân vật & Layout: chỉ phục vụ ẢNH (không bao giờ trả item.json)
            if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                return self.send_error(404)
            from .cast import CAST_DIR

            base, rel = CAST_DIR, path[len("/cast/"):]
        elif path.startswith("/post-media/"):
            # Quản lý bài đăng: chỉ phục vụ ảnh / video của bài (không bao giờ trả posts.json)
            if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".m4v"):
                return self.send_error(404)
            from .posts import MEDIA_DIR

            base, rel = MEDIA_DIR, path[len("/post-media/"):]
        elif path.startswith("/mhub-asset/"):
            # Studio Muse AI: ảnh tư liệu / ảnh tham chiếu đã chép vào kho riêng — chỉ phục vụ ẢNH (không trả *.json)
            if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                return self.send_error(404)
            from .muse_hub.common import STORE as MHUB_STORE

            base, rel = MHUB_STORE, path[len("/mhub-asset/"):]
        elif path.startswith("/seedance-image/"):
            base, rel = DATA_DIR / "seedance" / "images", path[len("/seedance-image/"):]
        elif path.startswith("/media/"):
            base, rel = settings.output_dir, path[len("/media/"):]
        else:
            base, rel = UI_DIR, path.lstrip("/") or "index.html"
        base = base.resolve()
        target = (base / rel).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            return self.send_error(404)
        size = parse_qs(parts.query).get("thumb", [""])[0]
        if size.isdigit() and target.suffix.lower() in THUMB_EXT:  # ảnh thu nhỏ cho lưới (đỡ giải mã ảnh gốc vài MB)
            thumb = make_thumb(target, int(size))
            if thumb is not None:
                return self._send_file(thumb, cache=True)
        self._send_file(target)

    def _send_bytes(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, cache: bool = False) -> None:
        size = path.stat().st_size
        ctype = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end, status = 0, size - 1, 200
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if match and size:
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last) if last else size - 1, size - 1)
            elif last:
                start = max(0, size - int(last))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        # ảnh thu nhỏ: URL đã kèm v=<mtime> + cỡ → cho trình duyệt giữ lại, quay lại màn không tải lại
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if cache else "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = fh.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass  # trình phát video huỷ request khi tua


THUMB_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".m4v")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")
THUMB_DIR = CACHE_DIR / "thumbs"
_THUMB_LOCK = threading.Lock()
_THUMB_SLOTS = threading.Semaphore(4)  # lưới lớn mở lần đầu: tối đa 4 ảnh / ffmpeg tạo cùng lúc


def make_thumb(src: Path, size: int) -> Path | None:
    """Như _make_thumb, giới hạn số lượt tạo cùng lúc (ảnh đã có trong cache trả ngay)."""
    with _THUMB_SLOTS:
        return _make_thumb(src, size)


def _make_thumb(src: Path, size: int) -> Path | None:
    """Ảnh thu nhỏ JPEG (cạnh dài ≤ size, 64–1024 px) cache ở CACHE_DIR/thumbs theo đường dẫn + mtime + cỡ. Video → ảnh
    bìa lấy 1 khung hình (ffmpeg) — lưới không phải tải cả thẻ <video>. Lỗi → None (bên gọi trả file gốc)."""
    import hashlib

    size = max(64, min(1024, size))
    try:
        st = src.stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{src}|{st.st_mtime_ns}|{st.st_size}|{size}".encode("utf-8")).hexdigest()
    out = THUMB_DIR / key[:2] / f"{key}.jpg"
    if out.is_file():
        return out
    if src.suffix.lower() in VIDEO_EXT:
        from . import ffmpeg

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{key}.{threading.get_ident()}.tmp.jpg")
        scale = f"scale=w={size}:h={size}:force_original_aspect_ratio=decrease"
        for seek in ("0.5", "0"):  # video quá ngắn → lấy khung đầu
            try:
                ffmpeg.run(["-ss", seek, "-i", str(src), "-frames:v", "1", "-vf", scale, "-q:v", "4", str(tmp)])
            except Exception:
                continue
            if tmp.is_file() and tmp.stat().st_size:
                with _THUMB_LOCK:
                    tmp.replace(out)
                return out
        tmp.unlink(missing_ok=True)
        return None
    try:
        from PIL import Image

        with Image.open(src) as im:
            im.draft("RGB", (size, size))  # JPEG: giải mã sẵn ở cỡ nhỏ → nhanh
            im.thumbnail((size, size))
            if im.mode != "RGB":
                bg = Image.new("RGB", im.size, (11, 15, 12))  # nền tối của app cho ảnh trong suốt
                bg.paste(im, mask=im.convert("RGBA").split()[-1])
                im = bg
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(f".{threading.get_ident()}.tmp")
            im.save(tmp, "JPEG", quality=82, optimize=True)
        with _THUMB_LOCK:
            tmp.replace(out)
        return out
    except Exception:  # ảnh hỏng / định dạng lạ → dùng ảnh gốc
        log.debug("Không tạo được ảnh thu nhỏ %s", src, exc_info=True)
        return None


def start_server() -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    return f"http://127.0.0.1:{httpd.server_address[1]}/"
