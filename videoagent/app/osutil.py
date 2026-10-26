"""Thao tác phụ thuộc hệ điều hành (Windows / macOS / Linux): mở file / thư mục, hiện file trong Explorer / Finder,
dừng cả cây tiến trình."""
import os
import signal
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def open_path(path) -> None:
    """Mở file / thư mục bằng ứng dụng mặc định (Explorer, Finder…)."""
    path = str(path)
    if IS_WIN:
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["open" if IS_MAC else "xdg-open", path])


def reveal(path) -> None:
    """Mở thư mục chứa file và chọn sẵn file đó."""
    path = Path(path)
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_path(path.parent if path.is_file() else path)


def kill_tree(proc: subprocess.Popen) -> None:
    """Dừng tiến trình và mọi tiến trình con của nó (Node, Chrome… do nó mở)."""
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        return
    try:  # macOS / Linux: tiến trình con được mở với start_new_session=True → dừng cả nhóm
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
