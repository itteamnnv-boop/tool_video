"""🧠 Cài / cập nhật / đăng nhập CLI model chữ ngay trên phần mềm (Cài đặt → Trình duyệt → Cách gọi model chữ).

- Node.js / npm: kiểm tra; chưa có → cài bằng winget (OpenJS.NodeJS.LTS) trong nền, không có winget → mở nodejs.org.
- CLI qua npm: `npm i -g <gói>` (cập nhật: `<gói>@latest`); muse-cli (Python): uv / pipx / pip --user, chưa có Python →
  cài Python 3.12 bằng winget. Đăng nhập muse-cli = cookie (app/llm/muse_cli.py), không qua Terminal.
- Mỗi lúc chỉ 1 việc cài, chạy nền, nhật ký từng dòng (giao diện hỏi job()), huỷ được; xong → nạp lại PATH của
  Windows (CLI / Node vừa cài dùng được ngay, không cần mở lại app) + xoá bộ nhớ trạng thái CLI.
- Đăng nhập cần tương tác (mở trình duyệt xác thực) → mở 1 cửa sổ Terminal chạy sẵn lệnh đăng nhập.
Chạy bằng quyền người dùng thường; không tự xin quyền quản trị.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import cli_chat

NODE_URL = "https://nodejs.org/en/download"
NODE_WINGET = ["install", "-e", "--id", "OpenJS.NodeJS.LTS", "--accept-source-agreements", "--accept-package-agreements"]
_job: dict = {"running": False, "site": "", "action": "", "log": [], "ok": None, "error": "", "started": 0.0, "ended": 0.0}
_proc: dict = {"p": None}
_lock = threading.Lock()
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def refresh_path() -> None:
    """Nạp lại PATH từ registry (Windows): Node / CLI vừa cài thêm thư mục vào PATH người dùng / máy."""
    if os.name != "nt":
        return
    try:
        import winreg

        parts = []
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, r"Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                continue
        npm_dir = os.path.join(os.environ.get("APPDATA", ""), "npm")
        merged, seen = [], set()
        for p in ";".join([os.environ.get("PATH", ""), *parts, npm_dir]).split(";"):
            if p and p.lower() not in seen:
                seen.add(p.lower())
                merged.append(p)
        os.environ["PATH"] = ";".join(merged)
    except Exception:  # noqa: BLE001
        pass


def node_status() -> dict:
    npm = shutil.which("npm") or ""
    node = shutil.which("node") or ""
    version = ""
    if node:
        try:
            out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=15, creationflags=NOWIN)
            version = (out.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {"npm": npm, "node": node, "version": version, "winget": shutil.which("winget") or "",
            "powershell": shutil.which("powershell") or shutil.which("pwsh") or ""}


PY_URL = "https://www.python.org/downloads/windows/"
PY_WINGET = ["install", "-e", "--id", "Python.Python.3.12", "--accept-source-agreements", "--accept-package-agreements"]
_py_cache: dict = {}


def python_status(refresh: bool = False) -> dict:
    """Cách cài muse-cli (Python ≥ 3.10): uv → pipx → Python (py launcher / python). Không dùng Python đóng gói trong app
    (bản build PyInstaller) và bỏ qua lối tắt "python" mở Microsoft Store (chạy --version không ra phiên bản)."""
    if _py_cache and not refresh:
        return dict(_py_cache)
    found = {"uv": shutil.which("uv") or "", "pipx": shutil.which("pipx") or "", "python": [], "version": "", "ok": False}
    # Python trong môi trường ảo (VD .venv của app khi chạy từ mã nguồn) không cài --user được → dùng Python gốc của nó
    probe = ("import sys,os;b=getattr(sys,'_base_executable','') or os.path.join(sys.base_prefix,'python.exe');"
             "print('%d.%d.%d' % sys.version_info[:3]);print(int(sys.prefix!=sys.base_prefix));print(b)")
    cands = [[shutil.which(c[0]) or "", *c[1:]] for c in (["py", "-3"], ["python"], ["python3"])]
    seen: set = set()
    while cands:
        cand = cands.pop(0)
        exe = cand[0]
        if not exe or exe.lower() in seen:
            continue
        seen.add(exe.lower())
        try:
            out = subprocess.run([*cand, "-c", probe], capture_output=True, text=True, timeout=15, creationflags=NOWIN)
        except (OSError, subprocess.SubprocessError):
            continue
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode != 0 or len(lines) < 3 or not lines[0][:1].isdigit():
            continue
        ver, in_venv, base = lines[0].strip(), lines[1].strip() == "1", lines[2].strip()
        if in_venv:
            if base and os.path.isfile(base):
                cands.insert(0, [base])
            continue
        major, minor = (int(x) for x in ver.split(".")[:2])
        if (major, minor) >= (3, 10):
            found.update(python=cand, version=ver, ok=True)
            break
        found["version"] = found["version"] or ver  # có Python nhưng quá cũ
    found["ok"] = bool(found["uv"] or found["pipx"] or found["python"])
    _py_cache.clear()
    _py_cache.update(found)
    return dict(found)


def _muse_command(action: str) -> list[str]:
    """Cài muse-cli: uv tool → pipx → pip --user. Cập nhật: `muse-cli update` (tự biết cách đã cài)."""
    from . import muse_cli

    if action == "update":
        path = cli_chat.which("muse")
        if path:
            return [path, "update"]
    st = python_status(refresh=True)
    if st["uv"]:
        return [st["uv"], "tool", "install", "--upgrade", muse_cli.PYPI]
    if st["pipx"]:
        return [st["pipx"], "install", "--force", muse_cli.PYPI]
    if st["python"]:
        return [*st["python"], "-m", "pip", "install", "--user", "--upgrade", muse_cli.PYPI]
    raise RuntimeError("Chưa có Python 3.10+ (hoặc uv / pipx) để cài muse-cli — bấm “Cài Python” trước")


def job() -> dict:
    with _lock:
        return {**_job, "log": _job["log"][-200:]}


def _command(site: str, action: str) -> list[str]:
    """action: install | update | node | python."""
    st = node_status()
    if action in ("node", "python"):
        if not st["winget"]:
            raise RuntimeError("no-winget")
        return [st["winget"], *(NODE_WINGET if action == "node" else PY_WINGET)]
    if site == "muse":
        return _muse_command(action)
    pkg = cli_chat.NPM_PKG.get(site)
    if not pkg:
        raise RuntimeError("Hãng không hợp lệ")
    if not st["npm"]:
        raise RuntimeError("Chưa có Node.js / npm — bấm “Cài Node.js” trước")
    return [st["npm"], "i", "-g", f"{pkg}@latest" if action == "update" else pkg]


def start(site: str, action: str) -> dict:
    """Bắt đầu cài / cập nhật trong nền. Đang có việc khác → lỗi."""
    with _lock:
        if _job["running"]:
            raise RuntimeError(f"Đang chạy {_job['action']} {_job['site'] or 'Node.js'} — chờ xong hoặc Huỷ")
    try:
        cmd = _command(site, action)
    except RuntimeError as exc:
        if str(exc) == "no-winget":  # không có winget → mở trang tải Node.js / Python
            url = PY_URL if action == "python" else NODE_URL
            webbrowser.open(url)
            return {"opened": url}
        raise
    with _lock:
        _job.update(running=True, site=site if action not in ("node", "python") else "", action=action, ok=None, error="",
                    log=[f"$ {' '.join(cmd)}"], started=time.time(), ended=0.0, cancelled=False)
    threading.Thread(target=_run, args=(cmd, site, action), daemon=True, name="cli-install").start()
    return job()


def _run(cmd: list[str], site: str, action: str) -> None:
    ok, error = False, ""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace", creationflags=NOWIN)
        _proc["p"] = p
        for line in p.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                with _lock:
                    _job["log"].append(line[:500])
        p.wait()
        ok = p.returncode == 0
        if not ok:
            error = f"Mã thoát {p.returncode}"
            tail = " ".join(_job["log"][-6:]).lower()
            if any(w in tail for w in ("eacces", "eperm", "administrator", "access is denied")):
                error += " — cần quyền quản trị: mở Terminal bằng quyền Administrator rồi chạy lệnh ở dòng đầu nhật ký"
    except OSError as exc:
        error = f"Không chạy được: {exc}"
    finally:
        _proc["p"] = None
        refresh_path()
        with cli_chat._status_lock:
            cli_chat._status_cache.clear()
        _py_cache.clear()
        if ok and action not in ("node", "python") and not cli_chat.which(site):
            ok, error = False, "Đã chạy xong nhưng chưa thấy lệnh CLI trong PATH — mở lại app rồi bấm ↻ Kiểm tra lại"
        with _lock:
            if _job.get("cancelled"):
                ok, error = False, "Đã huỷ"
            _job.update(running=False, ok=ok, error=error, ended=time.time(), cancelled=False)
            _job["log"].append("✓ Xong" if ok else f"✗ {error}")


def cancel() -> bool:
    p = _proc.get("p")
    if p is None:
        return False
    with _lock:
        _job["cancelled"] = True
    try:
        p.kill()
    except OSError:
        pass
    return True


def login(site: str) -> dict:
    """Mở cửa sổ Terminal chạy lệnh đăng nhập CLI (cần tương tác: mở trình duyệt xác thực)."""
    if site not in cli_chat.LOGIN_ARGS:
        raise RuntimeError("Hãng này không đăng nhập bằng CLI" + (" — nhập xAI API key" if site == "grok" else ""))
    path = cli_chat.which(site)
    if not path:
        raise RuntimeError(f"Chưa cài {cli_chat.CLIS[site]['name']}")
    args = [path, *cli_chat.LOGIN_ARGS[site]]
    title = f"VideoAgent - Dang nhap {cli_chat.CLIS[site]['name']}"
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", title, "cmd", "/k", *args], creationflags=NOWIN)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", path])
    else:
        term = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or ""
        if not term:
            raise RuntimeError(f"Mở Terminal rồi chạy: {' '.join(args)}")
        subprocess.Popen([term, "--", *args])
    return {"command": " ".join(args)}
