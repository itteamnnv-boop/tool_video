"""Chrome mở sẵn cho từng profile (kiểu HaoHao — Cài đặt → Trình duyệt → "Giữ Chrome mở sẵn cho mỗi tài khoản").

- Mỗi profile 1 Chrome thật của máy chạy liên tục (không headless, cờ tối thiểu như chế độ Chrome thật). Task dùng lại
  Chrome đó: không phải mở Chrome / tải lại phiên mỗi lần → nhanh hơn, phiên đăng nhập luôn "nóng".
- Mỗi task (luồng riêng) kết nối CDP tới Chrome của profile qua cổng gỡ lỗi CHỈ TRÊN MÁY (127.0.0.1, cổng ngẫu nhiên do
  Chrome chọn — đọc từ file DevToolsActivePort), làm xong thì NGẮT KẾT NỐI chứ không đóng Chrome.
- Rảnh: cửa sổ đưa ra ngoài màn hình (ẩn icon taskbar) — hoặc hiện trên màn hình nếu bật "Hiện cửa sổ Chrome".
- Chrome rảnh quá IDLE_MIN phút tự đóng; app thoát → đóng hết. Người dùng tự đóng cửa sổ → lần sau tự mở lại.
"""
import atexit
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
IDLE_MIN = 20  # phút rảnh thì đóng Chrome của profile để nhẹ máy
HIDDEN_POS = (-32000, -32000)
SHOWN_POS = (80, 40)


def _chrome_exe(channel: str) -> str:
    """Đường dẫn trình duyệt thật theo kênh (chrome / msedge)."""
    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    rel = "Microsoft/Edge/Application/msedge.exe" if channel == "msedge" else "Google/Chrome/Application/chrome.exe"
    for r in roots:
        p = Path(r) / rel
        if r and p.is_file():
            return str(p)
    raise RuntimeError(f"Không tìm thấy {'Edge' if channel == 'msedge' else 'Chrome'} trên máy — cài Chrome hoặc "
                       f"tắt “Giữ Chrome mở sẵn” trong Cài đặt")


class _Host:
    def __init__(self, folder: Path, channel: str, proc: subprocess.Popen, port: int) -> None:
        self.folder, self.channel, self.proc, self.port = folder, channel, proc, port
        self.last_used = time.time()
        self.busy = 0

    def alive(self) -> bool:
        return self.proc.poll() is None


_hosts: dict[str, _Host] = {}
_lock = threading.RLock()
_reaper_started = False


def _key(folder: Path) -> str:
    return str(Path(folder).resolve()).lower()


def _read_port(folder: Path, since: float, timeout: float = 20.0) -> int:
    f = Path(folder) / "DevToolsActivePort"
    end = time.time() + timeout
    while time.time() < end:
        try:
            if f.is_file() and f.stat().st_mtime >= since - 1:
                port = int(f.read_text("utf-8").splitlines()[0])
                if port > 0:
                    return port
        except (OSError, ValueError, IndexError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Chrome không mở được cổng gỡ lỗi (profile đang bị một Chrome khác giữ?) — đóng các cửa sổ "
                       "Chrome của profile này rồi thử lại")


def ensure(folder: Path, channel: str, args: tuple, offscreen: bool) -> _Host:
    """Chrome của profile đang chạy (mở nếu chưa có / đã bị đóng)."""
    global _reaper_started
    folder = Path(folder)
    with _lock:
        host = _hosts.get(_key(folder))
        if host and host.alive():
            host.last_used = time.time()
            return host
        exe = _chrome_exe(channel)
        (folder / "DevToolsActivePort").unlink(missing_ok=True)
        x, y = HIDDEN_POS if offscreen else SHOWN_POS
        cmd = [exe, f"--user-data-dir={folder}", "--remote-debugging-port=0", *args,
               f"--window-position={x},{y}", "about:blank"]
        started = time.time()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            port = _read_port(folder, started)
        except RuntimeError:
            proc.kill()
            raise
        host = _Host(folder, channel, proc, port)
        _hosts[_key(folder)] = host
        log.info("Chrome mở sẵn: %s (cổng nội bộ %s)", folder.name, port)
        if not _reaper_started:
            _reaper_started = True
            threading.Thread(target=_reaper, daemon=True, name="chrome-pool-reaper").start()
        return host


def stop(folder: Path) -> None:
    """Đóng Chrome mở sẵn của profile (trước khi mở cửa sổ đăng nhập / khi rảnh lâu / app thoát)."""
    with _lock:
        host = _hosts.pop(_key(folder), None)
    if host and host.alive():
        host.proc.terminate()
        try:
            host.proc.wait(10)
        except subprocess.TimeoutExpired:
            host.proc.kill()


def stop_all() -> None:
    for h in list(_hosts.values()):
        stop(h.folder)


def stop_idle() -> None:
    """Đóng Chrome mở sẵn không có task nào đang dùng (Chrome đang chạy task tự đóng khi task xong)."""
    with _lock:
        idle = [h for h in _hosts.values() if not h.busy]
    for h in idle:
        stop(h.folder)


def _pool_enabled() -> bool:
    from .browser_chat import cdp_mode, keepalive_mode
    return cdp_mode() and keepalive_mode()


def running() -> list[dict]:
    with _lock:
        return [{"profile": h.folder.name, "port": h.port, "busy": h.busy, "idle_s": int(time.time() - h.last_used)}
                for h in _hosts.values() if h.alive()]


def any_alive() -> bool:
    with _lock:
        return any(h.alive() for h in _hosts.values())


def _reaper() -> None:
    while True:
        time.sleep(60)
        with _lock:
            idle = [h for h in _hosts.values() if h.alive() and not h.busy and time.time() - h.last_used > IDLE_MIN * 60]
            for k in [k for k, h in _hosts.items() if not h.alive()]:
                _hosts.pop(k, None)
        for h in idle:
            log.info("Đóng Chrome rảnh %s phút: %s", IDLE_MIN, h.folder.name)
            stop(h.folder)


atexit.register(stop_all)


class KeptContext:
    """Bọc BrowserContext của Chrome mở sẵn: mọi thao tác như context thường; close() chỉ dọn tab của task + đưa cửa sổ
    về chỗ (ẩn / hiện) + ngắt kết nối — KHÔNG đóng Chrome."""

    def __init__(self, browser, context, host: _Host, show: bool) -> None:
        self._browser, self._ctx, self._host, self._show = browser, context, host, show
        self._before = set(id(p) for p in context.pages)
        self._closed = False
        self._handlers = []
        host.busy += 1
        self._place(show)

    def __getattr__(self, name):
        return getattr(self._ctx, name)

    @property
    def pages(self):
        return self._ctx.pages

    def on(self, event, handler):
        if event == "close":  # Chrome không đóng khi task xong → gọi khi task ngắt kết nối
            self._handlers.append(handler)
            return None
        return self._ctx.on(event, handler)

    def _place(self, show: bool) -> None:
        """Đưa cửa sổ Chrome lên màn hình (show) hoặc ra ngoài màn hình."""
        try:
            page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            cdp = self._ctx.new_cdp_session(page)
            win = cdp.send("Browser.getWindowForTarget")["windowId"]
            x, y = SHOWN_POS if show else HIDDEN_POS
            cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"left": x, "top": y, "width": 1280,
                                                                               "height": 1043}})
            cdp.detach()
        except Exception as exc:  # cửa sổ đang bận / vừa đóng — không quan trọng
            log.debug("đặt vị trí cửa sổ Chrome: %s", exc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            pages = list(self._ctx.pages)
            keep = pages[0] if pages else None
            for p in pages:  # tab task mở thêm → đóng, giữ lại 1 tab để Chrome không tự thoát
                if id(p) not in self._before and p is not keep:
                    try:
                        p.close()
                    except Exception:
                        pass
            if not self._show:
                self._place(False)
        finally:
            self._host.busy = max(0, self._host.busy - 1)
            self._host.last_used = time.time()
            for h in self._handlers:
                try:
                    h(self)
                except Exception:
                    pass
            try:
                self._browser.close()  # kết nối CDP: chỉ ngắt kết nối, Chrome vẫn chạy
            except Exception:
                pass
            if not self._host.busy and not _pool_enabled():  # vừa tắt "Giữ Chrome mở sẵn" trong lúc task chạy
                stop(self._host.folder)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def connect(pw, folder: Path, channel: str, args: tuple, show: bool) -> KeptContext:
    host = ensure(folder, channel, args, offscreen=not show)
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{host.port}", timeout=30_000)
    except Exception:  # Chrome vừa bị đóng / treo → mở lại 1 lần
        stop(folder)
        host = ensure(folder, channel, args, offscreen=not show)
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{host.port}", timeout=30_000)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    return KeptContext(browser, context, host, show)
