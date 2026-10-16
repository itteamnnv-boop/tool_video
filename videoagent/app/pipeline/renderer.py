"""Dựng khung hình: mở HTML bằng Chromium headless, tua animation từng frame và đẩy ảnh vào ffmpeg.

Tua bằng Web Animations API (document.getAnimations) nên kết quả ổn định, không phụ thuộc tốc độ máy.
Template có animation bằng JS có thể khai báo window.__tick(ms) để được gọi mỗi frame.
"""
import subprocess
from pathlib import Path

from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .. import ffmpeg
from ..ffmpeg import FFmpegError
from . import Cancelled

SEEK_JS = """t => {
  if (window.__VA) return window.__VA.seek(t);
  document.getAnimations().forEach(a => { a.pause(); a.currentTime = t; });
}"""
OVERFLOW_JS = "() => window.__VA ? window.__VA.overflow() : []"
READY_JS = "async () => { await document.fonts.ready; if (window.__VA) window.__VA.fit(); }"


def install_chromium() -> None:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    exe = compute_driver_executable()
    cmd = [str(p) for p in exe] if isinstance(exe, (tuple, list)) else [str(exe)]
    subprocess.run([*cmd, "install", "chromium"], env=get_driver_env(), check=True,
                   creationflags=ffmpeg.NO_WINDOW)


def launch_chromium(pw, log=None):
    try:
        return pw.chromium.launch()
    except PWError as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        if log:
            log("Lần chạy đầu: đang tải Chromium (Playwright)…")
        install_chromium()
        return pw.chromium.launch()


class SceneRenderer:
    def __init__(self, width: int, height: int, fps: int = 30, *, cancel=None, log=None) -> None:
        # Viewport bằng nửa kích thước xuất, device_scale_factor=2 → ảnh đúng độ phân giải và chữ sắc nét.
        self.width, self.height, self.fps = width, height, fps
        self._cancel, self._log = cancel, log

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = launch_chromium(self._pw, self._log)
        self._ctx = self._browser.new_context(
            viewport={"width": self.width // 2, "height": self.height // 2}, device_scale_factor=2,
        )
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._ctx.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except PWError:
                pass

    def _open(self, html_path: Path):
        page = self._ctx.new_page()
        page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except PWError:
            pass  # font online chậm/không có mạng → dùng font hệ thống
        page.evaluate(READY_JS)
        page.evaluate(SEEK_JS, 0)
        return page

    def overflow(self, html_path: Path) -> list[str]:
        page = self._open(html_path)
        try:
            page.evaluate(SEEK_JS, 60_000)  # đo ở trạng thái cuối, khi mọi chữ đã hiện
            return page.evaluate(OVERFLOW_JS)
        finally:
            page.close()

    def render(self, html_path: Path, out_path: Path, duration: float, thumb_path: Path | None = None,
               on_progress=None, background: tuple[Path, float] | None = None) -> None:
        """background = (clip, giây bắt đầu): chụp lớp HTML nền trong suốt (PNG) rồi ffmpeg ghép đè lên video."""
        page = self._open(html_path)
        frames = max(1, round(duration * self.fps))
        thumb_at = min(frames - 1, int(frames * 0.6))
        encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                  "-r", self.fps, "-movflags", "+faststart", str(out_path)]
        video_thumb = None
        if background is None:
            shot = {"type": "jpeg", "quality": 92}
            proc = ffmpeg.popen_stdin(["-f", "image2pipe", "-framerate", self.fps, "-c:v", "mjpeg", "-i", "-", *encode])
        else:
            clip, start = background
            page.evaluate("() => document.documentElement.classList.add('va-render')")
            shot = {"type": "png", "omit_background": True}
            w, h = self.width, self.height
            graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={self.fps},setsar=1[bg];"
                     "[bg][1:v]overlay=0:0:shortest=1,format=yuv420p[v]")
            proc = ffmpeg.popen_stdin([
                "-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", str(clip),
                "-f", "image2pipe", "-framerate", self.fps, "-c:v", "png", "-i", "-",
                "-filter_complex", graph, "-map", "[v]", "-an", *encode,
            ])
            thumb_path, video_thumb = None, thumb_path  # lớp PNG trong suốt không làm thumbnail được
        try:
            for i in range(frames):
                if self._cancel is not None and self._cancel.is_set():
                    raise Cancelled()
                page.evaluate(SEEK_JS, i * 1000 / self.fps)
                buf = page.screenshot(**shot)
                proc.stdin.write(buf)
                if thumb_path is not None and i == thumb_at:
                    thumb_path.write_bytes(buf)
                if on_progress and i % 15 == 0:
                    on_progress(i / frames)
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace")
            if proc.wait() != 0:
                raise FFmpegError(err[-1500:] or "ffmpeg lỗi khi mã hoá khung hình")
            if background is not None and video_thumb is not None:
                ffmpeg.run(["-ss", f"{duration * 0.6:.3f}", "-i", out_path, "-frames:v", "1", "-q:v", "3", video_thumb])
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        finally:
            page.close()
