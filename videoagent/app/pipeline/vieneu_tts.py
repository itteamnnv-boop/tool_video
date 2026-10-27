"""Lồng tiếng tiếng Việt bằng VieNeu-TTS (github.com/pnnbao97/VieNeu-TTS, Apache 2.0) — chạy NGAY TRÊN MÁY (CPU, ONNX).

VieNeu nặng (onnxruntime + model vài trăm MB) nên cài vào môi trường Python RIÊNG: DATA_DIR/tools/vieneu/venv (lần đầu dùng,
cần internet), gọi qua tiến trình con assets/vieneu_worker.py → không đụng thư viện của app, dừng được giữa chừng.
Cần Python 3.10+ trên máy (python.org / Microsoft Store) để tạo môi trường riêng.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..osutil import kill_tree
from ..paths import ASSETS_DIR, DATA_DIR

VERSION = "3.8.3"  # bản vieneu cố định (PyPI, 23/09/2026)
TOOLS_DIR = DATA_DIR / "tools" / "vieneu"
WORKER = ASSETS_DIR / "vieneu_worker.py"
STAMP = ".installed"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
INSTALL_HINT = "Cần Python 3.10+ trên máy (https://www.python.org) để cài VieNeu, rồi mở lại app"
# giọng có sẵn của vieneu 3.8.3 (lấy từ list_preset_voices) — (id, mô tả); ⭐ = giọng VieNeu đánh dấu nổi bật
PRESET_VOICES = [
    ("Ngọc Huyền", "⭐ Nữ · Bắc · tự nhiên"), ("Trúc Ly", "⭐ Nữ · Bắc · tự nhiên"), ("Mai Anh", "⭐ Nữ · Bắc · tin tức"),
    ("Thùy Dung", "⭐ Nữ · Nam · tin tức"), ("Ngọc Trân", "⭐ Nữ · Trung · tự nhiên"), ("Hải Đăng", "⭐ Nam · Bắc · tự nhiên"),
    ("Adam bựa", "⭐ Nam · Bắc · tự nhiên"), ("Thiện Minh", "⭐ Nam · Bắc · kể chuyện"),
    ("Thiền Tâm Đức", "⭐ Nam · Bắc · kể chuyện"), ("Quang Sơn", "⭐ Nam · Trung · tự nhiên"),
    ("Đoan Trang", "Nữ · Bắc · tự nhiên"), ("Ngọc Linh", "Nữ · Bắc · kể chuyện"), ("Quỳnh Anh", "Nữ · Bắc · đọc truyện"),
    ("Thục Đoan", "Nữ · Nam · kể chuyện"), ("Mỹ Duyên", "Nữ · Nam · đọc truyện"), ("Kim Thanh", "Nữ · Nam · đọc truyện"),
    ("Minh Đức", "Nam · Bắc · tin tức"), ("Phạm Tuyên", "Nam · Bắc · tự nhiên"), ("Xuân Vĩnh", "Nam · Bắc · tự nhiên"),
    ("Thanh Bình", "Nam · Bắc · kể chuyện"), ("Quốc Tuấn", "Nam · Bắc · tự nhiên"), ("Thái Sơn", "Nam · Nam · kể chuyện"),
    ("Minh Triết", "Nam · Nam · tin tức"), ("Đức Trí", "Nam · Nam · đọc truyện"), ("Adam", "Nam · Nam · tự nhiên"),
]


class VieNeuError(RuntimeError):
    pass


def _venv_python() -> Path:
    return TOOLS_DIR / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _env() -> dict:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


def _py_version(cmd: list) -> tuple:
    try:
        out = subprocess.run([*cmd, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True,
                             text=True, timeout=30, creationflags=NO_WINDOW).stdout.strip()
        major, minor = (int(x) for x in out.split("."))
        return major, minor
    except (OSError, ValueError, subprocess.SubprocessError):
        return (0, 0)


def system_python() -> list | None:
    """Python 3.10+ để tạo môi trường riêng: Python đang chạy app (khi chạy từ mã nguồn), py launcher, python3 / python."""
    cands = []
    if not getattr(sys, "frozen", False):
        cands.append([getattr(sys, "_base_executable", "") or sys.executable])
    for args in (["py", "-3.12"], ["py", "-3.11"], ["py", "-3"], ["python3"], ["python"]):
        if shutil.which(args[0]):
            cands.append([shutil.which(args[0]), *args[1:]])
    for cmd in cands:
        if cmd[0] and _py_version(cmd) >= (3, 10):
            return cmd
    return None


def status() -> dict:
    installed = _venv_python().is_file() and (TOOLS_DIR / STAMP).is_file() \
        and (TOOLS_DIR / STAMP).read_text("utf-8").strip() == VERSION
    return {"installed": installed, "python": bool(installed or system_python()), "version": VERSION}


def ensure_installed(log) -> Path:
    if status()["installed"]:
        return _venv_python()
    py = system_python()
    if not py:
        raise VieNeuError(f"Không tìm thấy Python 3.10+ — {INSTALL_HINT}")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if not _venv_python().is_file():
        log("Đang tạo môi trường riêng cho VieNeu…")
        res = subprocess.run([*py, "-m", "venv", str(TOOLS_DIR / "venv")], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=600, creationflags=NO_WINDOW)
        if res.returncode != 0 or not _venv_python().is_file():
            raise VieNeuError(f"Tạo môi trường Python lỗi: {(res.stderr or res.stdout).strip()[-500:]}")
    log(f"Đang cài VieNeu-TTS {VERSION} (lần đầu, cần internet, vài phút)…")
    res = subprocess.run([str(_venv_python()), "-m", "pip", "install", "--no-input", f"vieneu=={VERSION}"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                         env=_env(), creationflags=NO_WINDOW)
    if res.returncode != 0:
        raise VieNeuError(f"Cài VieNeu lỗi: {(res.stderr or res.stdout).strip()[-600:]}")
    (TOOLS_DIR / STAMP).write_text(VERSION, "utf-8")
    log("Đã cài VieNeu-TTS", "ok")
    return _venv_python()


def _run_worker(args: list, *, log, check_cancel=None, timeout: int = 1800, cwd: Path | None = None) -> list[str]:
    """Chạy assets/vieneu_worker.py; chuyển dòng STAGE lên nhật ký; trả các dòng in ra. Huỷ → dừng cả cây tiến trình."""
    cwd = Path(cwd or TOOLS_DIR)
    log_path = cwd / ".vieneu.log"
    with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen([str(_venv_python()), str(WORKER), *args], cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                env=_env(), creationflags=NO_WINDOW, start_new_session=os.name != "nt")
        deadline, seen = time.time() + timeout, 0
        try:
            while proc.poll() is None:
                if check_cancel:
                    check_cancel()
                if time.time() > deadline:
                    raise VieNeuError(f"VieNeu chạy quá {timeout // 60} phút — đã dừng")
                seen = _relay(log_path, seen, log)
                time.sleep(0.4)
        except BaseException:
            if proc.poll() is None:
                kill_tree(proc)
            raise
    _relay(log_path, seen, log)
    lines = log_path.read_text("utf-8", errors="replace").splitlines()
    err = next((ln[6:] for ln in reversed(lines) if ln.startswith("ERROR ")), "")
    if proc.returncode != 0 or err:
        tail = err or "\n".join(lines[-6:])
        raise VieNeuError(f"VieNeu lỗi: {tail[-600:]}")
    return lines


def _relay(log_path: Path, seen: int, log) -> int:
    try:
        lines = log_path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return seen
    for ln in lines[seen:]:
        if ln.startswith("STAGE "):
            log(ln[6:])
    return len(lines)


def synthesize(text: str, out: Path, *, voice: str = "", ref_audio: str = "", log=None, check_cancel=None) -> Path:
    """Đọc text bằng VieNeu → file WAV (48 kHz). voice = tên giọng có sẵn; ref_audio = file giọng mẫu để nhân bản."""
    return synthesize_many([(text, out)], voice=voice, ref_audio=ref_audio, log=log, check_cancel=check_cancel)[0]


def synthesize_many(items: list, *, voice: str = "", ref_audio: str = "", log=None, check_cancel=None) -> list[Path]:
    """Đọc nhiều đoạn [(text, out.wav), …] trong 1 lần nạp model (lời đọc theo từng cảnh) → danh sách file WAV."""
    log = log or (lambda *a, **k: None)
    clean = [(re.sub(r"[ \t]+", " ", str(t or "")).strip(), Path(o)) for t, o in items]
    if not clean or any(not t for t, _ in clean):
        raise VieNeuError("Chưa có lời đọc")
    ensure_installed(log)
    folder = clean[0][1].parent
    folder.mkdir(parents=True, exist_ok=True)
    job = clean[0][1].with_suffix(".job.json")
    job.write_text(json.dumps({"items": [{"text": t, "out": str(o)} for t, o in clean], "voice": str(voice or "").strip(),
                               "ref_audio": str(ref_audio or "")}, ensure_ascii=False), "utf-8")
    _run_worker([str(job)], log=log, check_cancel=check_cancel, cwd=folder, timeout=1800 + 120 * len(clean))
    for _, out in clean:
        if not out.is_file() or out.stat().st_size < 1000:
            raise VieNeuError("VieNeu không tạo được file âm thanh")
    return [o for _, o in clean]


def list_voices(log=None) -> list:
    """[[tên, id], …] giọng có sẵn (cần đã cài; lần đầu nạp model)."""
    log = log or (lambda *a, **k: None)
    ensure_installed(log)
    lines = _run_worker(["--list"], log=log, timeout=900)
    raw = next((ln[7:] for ln in lines if ln.startswith("VOICES ")), "[]")
    try:
        return json.loads(raw)
    except ValueError:
        return []
