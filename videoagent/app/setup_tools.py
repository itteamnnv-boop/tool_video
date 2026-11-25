"""🧰 Cài đặt công cụ: danh mục mọi công cụ NGOÀI app mà các màn cần (Node, Python + gói, ffmpeg, Claude Code, Codex,
capcut-cli, skill TVC, Remotion, CapCut…) — kiểm tra trạng thái, cài / cập nhật ONLINE (winget / npm / pip) theo hàng đợi
chạy nền, mở đăng nhập, xuất báo cáo cho người hỗ trợ.

- Mọi lệnh cài chạy bằng quyền người dùng thường, chỉ khi người dùng bấm (Cài / Cài tất cả còn thiếu — có xác nhận).
- Báo cáo không chứa token / cookie (module này không đọc chúng; chỉ kiểm tra file đăng nhập CÓ hay không).
- Skill TVC KHÔNG đóng gói kèm app: người dùng chọn file .skill (zip) → giải nén vào ~/.claude/skills/<tên>.
- Dùng lại phần cài CLI có sẵn (app/llm/cli_install.py): nạp lại PATH, trạng thái Node / Python, cài muse-cli, đăng nhập.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .llm import cli_install
from .paths import DATA_DIR, ROOT

BUNDLED_SKILLS = ROOT / "skills"  # skill TVC chép nguyên bản vào gói cài (VideoAgent.spec: datas skills)

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PIP_PKGS = {"pillow": "PIL", "numpy": "numpy", "scipy": "scipy", "fonttools": "fontTools", "faster-whisper": "faster_whisper"}
CLAUDE_EXT = "fcoeoabgfenejglbffodgkkbkcdhcgfn"  # Claude in Chrome
SKILLS = ("tvc-livestream-capcut", "tvc-livestream-capcut-muse", "video-mau-doi-nhan-vat")
GROUPS = {"base": "Nền tảng", "cli": "Công cụ dòng lệnh (CLI)", "tvc": "Trợ lý TVC", "extra": "Tuỳ chọn"}
STATES = {"ok": "Sẵn sàng", "missing": "Chưa cài", "old": "Phiên bản cũ", "login": "Chưa đăng nhập", "unknown": "Không rõ"}
WINGET_FINE = (-1978335189, -1978335212, -1978335135)  # winget: đã cài sẵn / không có bản mới — không phải lỗi


class SetupError(RuntimeError):
    pass


# ---------------------------------------------------------------------- tiện ích
def _run(cmd: list, timeout: int = 20, cwd: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, encoding="utf-8",
                           errors="replace", creationflags=NOWIN)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


def _which(name: str) -> str:
    return shutil.which(name) or ""


def _ver(text: str) -> str:
    m = re.search(r"\d+\.\d+(?:\.\d+)?", text or "")
    return m.group(0) if m else ""


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) if v else ()


def _winget(pkg: str) -> list:
    return ["winget", "install", "-e", "--id", pkg, "--silent", "--accept-source-agreements", "--accept-package-agreements"]


def _res(state: str, version: str = "", path: str = "", detail: str = "") -> dict:
    return {"state": state, "version": version, "path": path, "detail": detail}


def _reg_value(paths: list, name: str) -> str:
    if os.name != "nt":
        return ""
    import winreg

    for root, key in paths:
        try:
            with winreg.OpenKey(root, key) as k:
                return str(winreg.QueryValueEx(k, name)[0])
        except OSError:
            continue
    return ""


# ---------------------------------------------------------------------- kiểm tra từng công cụ
def chk_webview2(_ctx) -> dict:
    if os.name != "nt":
        return _res("ok", detail="Không cần trên hệ điều hành này")
    import winreg

    guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    v = _reg_value([(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                    (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}"),
                    (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}")], "pv")
    return _res("ok", v) if v and v != "0.0.0.0" else _res("missing", detail="Cửa sổ app cần WebView2")


def chk_chrome(_ctx) -> dict:
    from .llm.chrome_pool import _chrome_exe

    for ch, label in (("chrome", "Chrome"), ("msedge", "Edge")):
        try:
            exe = _chrome_exe(ch)
        except Exception:  # noqa: BLE001
            exe = ""
        if exe and Path(exe).is_file():
            return _res("ok", label, exe)
    return _res("missing", detail="Cần Google Chrome (hoặc Edge) cho model qua trình duyệt / Claude in Chrome")


def chk_node(_ctx) -> dict:
    st = cli_install.node_status()
    if not st["node"]:
        return _res("missing")
    v = _ver(st["version"])
    if _vt(v) and _vt(v) < (18,):
        return _res("old", v, st["node"], "Cần Node.js 18 trở lên")
    return _res("ok", v, st["node"], "" if st["npm"] else "Thiếu npm")


def chk_python(_ctx) -> dict:
    st = cli_install.python_status(refresh=True)
    if st["python"]:
        return _res("ok", st["version"], " ".join(st["python"]))
    if st["version"]:
        return _res("old", st["version"], detail="Cần Python 3.10 trở lên")
    return _res("missing", detail="Script của skill TVC chạy bằng Python của máy")


def _py() -> list:
    return cli_install.python_status().get("python") or []


def chk_pip(_ctx) -> dict:
    py = _py()
    if not py:
        return _res("missing", detail="Cài Python trước")
    code = ("import json,importlib.metadata as m\nout={}\nfor n in %r:\n try: out[n]=m.version(n)\n except Exception: "
            "out[n]=''\nprint(json.dumps(out))") % list(PIP_PKGS)
    rc, out = _run([*py, "-c", code], 40)
    try:
        vers = json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        return _res("unknown", detail=out[:200])
    miss = [n for n, v in vers.items() if not v]
    have = ", ".join(f"{n} {v}" for n, v in vers.items() if v)
    return _res("missing" if miss else "ok", have, detail=f"Thiếu: {', '.join(miss)}" if miss else "")


def chk_ffmpeg(_ctx) -> dict:
    exe = _which("ffmpeg")
    if not exe:
        return _res("missing", detail="Skill TVC gọi ffmpeg / ffprobe trong PATH (app đã có ffmpeg riêng)")
    rc, out = _run([exe, "-version"])
    probe = bool(_which("ffprobe"))
    return _res("ok" if probe else "missing", _ver(out), exe, "" if probe else "Thiếu ffprobe")


def chk_claude(_ctx) -> dict:
    from .tvc_claude import native_claude

    exe = native_claude()
    if not exe:
        return _res("missing", detail="Trợ lý TVC cần Claude Code bản .exe (bản npm claude.cmd không chạy được với SDK)")
    rc, out = _run([exe, "--version"])
    if not (Path.home() / ".claude" / ".credentials.json").is_file():
        return _res("login", _ver(out), exe, "Chưa thấy đăng nhập Claude — bấm Đăng nhập")
    return _res("ok", _ver(out), exe)


def _cli(bin_name: str):
    def check(_ctx) -> dict:
        exe = _which(bin_name)
        if not exe:
            return _res("missing")
        rc, out = _run([exe, "--version"])
        return _res("ok", _ver(out), exe)
    return check


def chk_codex(ctx) -> dict:
    r = _cli("codex")(ctx)
    if r["state"] != "ok":
        return r
    rc, out = _run([r["path"], "login", "status"])
    if "logged in" not in out.lower():
        return {**r, "state": "login", "detail": "Chưa đăng nhập ChatGPT — bấm Đăng nhập"}
    return r


def chk_muse(_ctx) -> dict:
    from .llm import cli_chat

    exe = cli_chat.which("muse")
    return _res("ok", path=exe) if exe else _res("missing")


def bundled_skill(name: str) -> Path | None:
    """Skill đóng gói kèm app (<app>/skills/<tên>, chép nguyên bản lúc build) — không có → None."""
    for base in (BUNDLED_SKILLS, ROOT / "assets" / "skills"):  # <app>/skills, rồi bản trong assets/skills
        d = base / name
        if (d / "SKILL.md").is_file():
            return d
    return None


def skill_hash(d: Path) -> str:
    """Mã băm nội dung skill (đường dẫn + nội dung từng file; bỏ __pycache__ / .bak) để so bản đang cài với bản trong gói."""
    import hashlib

    m = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        m.update(f.relative_to(d).as_posix().encode())
        m.update(f.read_bytes())
    return m.hexdigest()[:12]


def chk_skill(name: str):
    def check(_ctx) -> dict:
        f = Path.home() / ".claude" / "skills" / name / "SKILL.md"
        bundle = bundled_skill(name)
        if not f.is_file():
            return _res("missing", detail="Có trong gói cài — bấm Cài từ gói" if bundle else
                        "Chọn file .skill để cài (lấy từ máy đã có skill)")
        m = re.search(r"^version:\s*(\S+)", f.read_text("utf-8", errors="replace")[:2000], re.M)
        r = _res("ok", m.group(1) if m else "", str(f.parent))
        if bundle is not None and skill_hash(f.parent) != skill_hash(bundle):
            r.update(bundle_diff=True, detail="Khác bản trong gói cài (bản trên máy có thể mới hơn hoặc cũ hơn)")
        return r
    return check


def _remotion_dir(ctx) -> Path:
    return Path(ctx["tvc_root"]) / "_remotion" / "live-overlay"


def chk_remotion(ctx) -> dict:
    d = _remotion_dir(ctx)
    if not (d / "package.json").is_file():
        return _res("missing", path=str(d), detail="Chưa có thư mục dự án Remotion — chép từ máy cũ (<gốc TVC>\\_remotion)")
    if not (d / "node_modules").is_dir():
        return _res("missing", path=str(d), detail="Chưa cài thư viện npm của Remotion — bấm Cài")
    return _res("ok", path=str(d))


def chk_capcut(_ctx) -> dict:
    apps = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps"
    vers = sorted((p.name for p in apps.iterdir() if p.is_dir() and (p / "CapCut.exe").is_file()), key=_vt) \
        if apps.is_dir() else []
    return _res("ok", vers[-1], str(apps / vers[-1])) if vers else _res("missing", detail="Cần CapCut để mở draft")


def chk_ext(_ctx) -> dict:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    for prof in (base.iterdir() if base.is_dir() else []):
        ext = prof / "Extensions" / CLAUDE_EXT
        if ext.is_dir():
            vers = sorted((p.name for p in ext.iterdir()), key=_vt)
            return _res("ok", vers[-1].split("_")[0] if vers else "", detail=f"Profile Chrome: {prof.name}")
    return _res("missing", detail="Bước tạo clip Grok của skill cần extension Claude in Chrome")


def chk_whisper(_ctx) -> dict:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    d = hub / "models--Systran--faster-whisper-medium"
    return _res("ok", "medium", str(d)) if d.is_dir() else _res(
        "missing", detail="Skill video mẫu chép lời bằng model medium (~1,5 GB, tải 1 lần)")


def chk_zalo(_ctx) -> dict:
    pkg = DATA_DIR / "tools" / "zalo" / "node_modules" / "zca-js" / "package.json"
    if not pkg.is_file():
        return _res("missing", detail="Chỉ cần khi nghe yêu cầu quảng cáo từ nhóm Zalo (Cài đặt → Zalo)")
    try:
        return _res("ok", json.loads(pkg.read_text("utf-8")).get("version", ""))
    except (OSError, ValueError):
        return _res("ok")


def chk_facebook(ctx) -> dict:
    fb = ctx.get("facebook")
    if fb is None:
        return _res("unknown")
    try:
        st = fb.state()
    except Exception as exc:  # noqa: BLE001
        return _res("unknown", detail=str(exc)[:200])
    pages = [p for p in st.get("pages") or [] if p.get("connected")]
    if not st.get("user") and not pages:
        return _res("login", detail="Chưa kết nối Facebook (Cài đặt → Facebook · Meta)")
    user = st.get("user") if isinstance(st.get("user"), dict) else {}
    return _res("ok", f"{len(pages)} Fanpage", detail=user.get("name", ""))


# ---------------------------------------------------------------------- danh mục
def _npm(pkg: str) -> dict:
    return {"cmds": lambda ctx, a: [["npm", "i", "-g", f"{pkg}@latest" if a == "update" else pkg]], "needs": "node"}


TOOLS = [
    {"key": "webview2", "group": "base", "name": "Microsoft Edge WebView2", "used": ["Cửa sổ app"], "need": True,
     "check": chk_webview2, "cmds": lambda c, a: [_winget("Microsoft.EdgeWebView2Runtime")],
     "url": "https://developer.microsoft.com/microsoft-edge/webview2/"},
    {"key": "chrome", "group": "base", "name": "Google Chrome", "used": ["Model qua trình duyệt", "Trợ lý TVC"], "need": True,
     "check": chk_chrome, "cmds": lambda c, a: [_winget("Google.Chrome")], "url": "https://www.google.com/chrome/"},
    {"key": "node", "group": "base", "name": "Node.js LTS + npm", "used": ["CLI", "Remotion", "Zalo"], "need": True,
     "check": chk_node, "cmds": lambda c, a: [_winget("OpenJS.NodeJS.LTS")], "url": cli_install.NODE_URL},
    {"key": "python", "group": "base", "name": "Python 3.12", "used": ["Script skill TVC", "muse-cli"], "need": True,
     "check": chk_python, "cmds": lambda c, a: [_winget("Python.Python.3.12")], "url": cli_install.PY_URL},
    {"key": "pip", "group": "base", "name": "Gói Python: " + ", ".join(PIP_PKGS), "used": ["Script skill TVC"], "need": True,
     "check": chk_pip, "needs": "python",
     "cmds": lambda c, a: [[*_py(), "-m", "pip", "install", "--user", "--upgrade", *PIP_PKGS]]},
    {"key": "ffmpeg", "group": "base", "name": "FFmpeg (trong PATH)", "used": ["Script skill TVC"], "need": True,
     "check": chk_ffmpeg, "cmds": lambda c, a: [_winget("Gyan.FFmpeg")], "url": "https://www.gyan.dev/ffmpeg/builds/"},
    {"key": "claude", "group": "cli", "name": "Claude Code (bản .exe)", "used": ["Trợ lý TVC", "Model chữ"], "need": True,
     "check": chk_claude, "login": "claude", "url": "https://docs.claude.com/en/docs/claude-code/setup",
     "cmds": lambda c, a: [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                            "irm https://claude.ai/install.ps1 | iex"]]},
    {"key": "codex", "group": "cli", "name": "OpenAI Codex CLI", "used": ["Ảnh cảnh skill TVC", "Model chữ"], "need": True,
     "check": chk_codex, "login": "chatgpt", **_npm("@openai/codex")},
    {"key": "capcut_cli", "group": "cli", "name": "capcut-cli", "used": ["Dựng draft CapCut (skill TVC)"], "need": True,
     "check": _cli("capcut-cli"), **_npm("capcut-cli")},
    {"key": "gemini", "group": "cli", "name": "Gemini CLI", "used": ["Model chữ (tuỳ chọn)"], "need": False,
     "check": _cli("gemini"), "login": "gemini", **_npm("@google/gemini-cli")},
    {"key": "grok", "group": "cli", "name": "Grok CLI (cộng đồng)", "used": ["Model chữ (tuỳ chọn)"], "need": False,
     "check": _cli("grok"), **_npm("@vibe-kit/grok-cli")},
    {"key": "muse", "group": "cli", "name": "muse-cli (cộng đồng)", "used": ["Skill TVC bản Muse", "Model chữ"], "need": False,
     "check": chk_muse, "needs": "python", "cmds": lambda c, a: [cli_install._muse_command(a)]},
    *[{"key": f"skill:{n}", "group": "tvc", "name": f"Skill {n}", "used": ["Trợ lý TVC"], "need": n == "tvc-livestream-capcut",
       "check": chk_skill(n), "skill": n} for n in SKILLS],
    {"key": "remotion", "group": "tvc", "name": "Remotion live-overlay (thư viện npm)", "used": ["Khung live (skill TVC)"],
     "need": True, "check": chk_remotion, "needs": "node",
     "cmds": lambda c, a: [["npm", "install", "--no-audit", "--no-fund", {"cwd": str(_remotion_dir(c))}]]},
    {"key": "capcut", "group": "tvc", "name": "CapCut", "used": ["Mở draft"], "need": True, "check": chk_capcut,
     "url": "https://www.capcut.com/download"},
    {"key": "claude_ext", "group": "tvc", "name": "Extension Claude in Chrome", "used": ["Clip Grok (skill TVC)"],
     "need": True, "check": chk_ext, "url": f"https://chromewebstore.google.com/detail/{CLAUDE_EXT}"},
    {"key": "facebook", "group": "tvc", "name": "Kết nối Facebook", "used": ["Đăng bài", "Quảng cáo"], "need": False,
     "check": chk_facebook, "open": "facebook"},
    {"key": "whisper", "group": "extra", "name": "Model faster-whisper medium", "used": ["Skill video mẫu"], "need": False,
     "check": chk_whisper, "needs": "pip",
     "cmds": lambda c, a: [[*_py(), "-c", "from faster_whisper import WhisperModel; "
                                         "WhisperModel('medium', device='cpu', compute_type='int8'); print('OK')"]]},
    {"key": "zalo", "group": "extra", "name": "zca-js (nghe nhóm Zalo)", "used": ["Yêu cầu quảng cáo từ Zalo"], "need": False,
     "check": chk_zalo, "open": "zalo"},
]
BY_KEY = {t["key"]: t for t in TOOLS}
TVC_NEEDS = {"chrome", "node", "python", "pip", "ffmpeg", "claude", "codex", "capcut_cli", "skill:tvc-livestream-capcut",
             "remotion", "capcut", "claude_ext"}
NO_UPDATE = {"webview2", "remotion", "whisper"}


def _installable(t: dict) -> bool:
    """Cài tự động được: có lệnh cài, hoặc là skill có sẵn trong gói cài."""
    return bool(t.get("cmds")) or bool(t.get("skill") and bundled_skill(t["skill"]))


# ---------------------------------------------------------------------- trạng thái + hàng đợi cài
class SetupTools:
    def __init__(self, settings, facebook=None, on_change=None) -> None:
        self.settings = settings
        self.facebook = facebook
        self.on_change = on_change or (lambda: None)
        self._lock = threading.RLock()
        self._status: dict = {}
        self._checked = 0.0
        self._job = {"running": False, "queue": [], "current": "", "done": [], "log": [], "started": 0.0, "ended": 0.0,
                     "cancelled": False}
        self._proc = None

    def _ctx(self) -> dict:
        return {"tvc_root": str(self.settings.get("tvc_root") or "D:/CapCut"), "facebook": self.facebook}

    # ---- kiểm tra
    def check(self, keys: list | None = None) -> dict:
        cli_install.refresh_path()
        ctx = self._ctx()
        todo = [t for t in TOOLS if not keys or t["key"] in keys]

        def one(t):
            try:
                return t["key"], t["check"](ctx)
            except Exception as exc:  # noqa: BLE001 — 1 công cụ lỗi không làm hỏng cả bảng
                return t["key"], _res("unknown", detail=str(exc)[:200])

        results = dict(one(t) for t in todo if t["key"] == "python")  # Python trước: gói pip / muse dùng kết quả
        with ThreadPoolExecutor(max_workers=8) as pool:
            results.update(pool.map(one, [t for t in todo if t["key"] != "python"]))
        with self._lock:
            for k, r in results.items():
                self._status[k] = {**r, "checked": datetime.now().strftime("%H:%M:%S")}
            self._checked = time.time()
        return self.state()

    def _row(self, t: dict) -> dict:
        st = self._status.get(t["key"]) or {"state": "unknown"}
        return {"key": t["key"], "group": t["group"], "name": t["name"], "used": t["used"], "need": t["need"],
                **st, "state_label": STATES.get(st.get("state"), ""), "can_install": _installable(t),
                "can_update": (bool(t.get("cmds")) and t["key"] not in NO_UPDATE) or bool(st.get("bundle_diff")),
                "bundle": bool(t.get("skill") and bundled_skill(t["skill"])), "login": bool(t.get("login")),
                "skill": t.get("skill", ""), "url": t.get("url", ""), "open": t.get("open", "")}

    def state(self) -> dict:
        with self._lock:
            rows = [self._row(t) for t in TOOLS]
            job = {**self._job, "queue": list(self._job["queue"]), "done": list(self._job["done"]),
                   "log": self._job["log"][-300:]}
            checked = bool(self._checked)
        need = [r for r in rows if r["need"]]
        bad = [r for r in need if r["state"] != "ok"]
        tvc = [r["name"] for r in rows if r["key"] in TVC_NEEDS and r["state"] != "ok"]
        return {"tools": rows, "groups": GROUPS, "states": STATES, "job": job, "checked": checked,
                "summary": {"ready": len(need) - len(bad), "need": len(need), "missing": len(bad) if checked else 0,
                            "tvc_missing": tvc if checked else [],
                            "auto": [r["key"] for r in bad if r["can_install"] and r["state"] in ("missing", "old")]}}

    # ---- cài / cập nhật (hàng đợi, chạy nền)
    def install(self, keys: list, action: str = "install") -> dict:
        if action not in ("install", "update"):
            raise SetupError("Thao tác không hợp lệ")
        keys = [k for k in keys or [] if k in BY_KEY and _installable(BY_KEY[k])]
        if not keys:
            raise SetupError("Không có mục nào cài tự động được — xem hướng dẫn của từng mục")
        order = [t["key"] for t in TOOLS]
        keys = sorted(dict.fromkeys(keys), key=order.index)  # Node / Python trước các thứ cần chúng
        with self._lock:
            if self._job["running"]:
                raise SetupError("Đang cài — chờ xong hoặc bấm Dừng")
            self._job.update(running=True, queue=[{"key": k, "action": action} for k in keys], current="", done=[],
                             log=[], started=time.time(), ended=0.0, cancelled=False)
        threading.Thread(target=self._worker, daemon=True, name="setup-tools").start()
        return self.state()

    def cancel(self) -> bool:
        with self._lock:
            if not self._job["running"]:
                return False
            self._job["cancelled"] = True
            self._job["queue"] = []
            p = self._proc
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass
        return True

    def _log(self, line: str) -> None:
        with self._lock:
            self._job["log"].append(line[:500])

    def _worker(self) -> None:
        try:
            while True:
                with self._lock:
                    if not self._job["queue"] or self._job["cancelled"]:
                        break
                    item = self._job["queue"].pop(0)
                    self._job["current"] = item["key"]
                t = BY_KEY[item["key"]]
                ok, err = self._do(t, item["action"])
                self.check([t["key"], "pip", "muse"] if t["key"] == "python" else [t["key"]])
                if ok and (self._status.get(t["key"]) or {}).get("state") not in ("ok", "login"):
                    ok, err = False, "Đã chạy xong nhưng kiểm tra lại vẫn chưa thấy — mở lại app hoặc xem nhật ký"
                with self._lock:
                    self._job["done"].append({"key": t["key"], "name": t["name"], "ok": ok, "error": err})
                self._log(f"{'✓' if ok else '✗'} {t['name']}" + (f" — {err}" if err else ""))
                self.on_change()
        finally:
            with self._lock:
                if self._job["cancelled"]:
                    self._job["log"].append("⏹ Đã dừng")
                self._job.update(running=False, current="", ended=time.time())
            self.on_change()

    def _do(self, t: dict, action: str) -> tuple[bool, str]:
        if t.get("skill"):  # skill: chép từ gói cài (không cần mạng)
            return self._skill_from_bundle(t["skill"])
        need = t.get("needs")
        if need and (self._status.get(need) or {}).get("state") != "ok":
            self.check([need])
            if (self._status.get(need) or {}).get("state") != "ok":
                return False, f"Cần “{BY_KEY[need]['name']}” trước"
        try:
            cmds = t["cmds"](self._ctx(), action)
        except Exception as exc:  # noqa: BLE001 — VD chưa có Python cho muse-cli
            return False, str(exc)
        self._log(f"▶ {t['name']}")
        for raw in cmds:
            opts = raw[-1] if raw and isinstance(raw[-1], dict) else {}
            cmd = [str(c) for c in raw if not isinstance(c, dict)]
            exe = shutil.which(cmd[0]) or (cmd[0] if Path(cmd[0]).is_file() else "")
            if not exe:
                if cmd[0] == "winget":
                    return False, f"Máy chưa có winget — tải thủ công: {t.get('url', '')}"
                return False, f"Không thấy lệnh {cmd[0]}"
            if opts.get("cwd") and not Path(opts["cwd"]).is_dir():
                return False, f"Không thấy thư mục {opts['cwd']}"
            self._log(f"$ {' '.join([Path(exe).name, *cmd[1:]])}")
            try:
                p = subprocess.Popen([exe, *cmd[1:]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                     cwd=opts.get("cwd"), creationflags=NOWIN)
            except OSError as exc:
                return False, f"Không chạy được: {exc}"
            with self._lock:
                self._proc = p
            for line in p.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if line and not re.fullmatch(r"[\s\-\\|/█▒░.%0-9KMGBkb]*", line):  # bỏ dòng thanh tiến độ
                    self._log("  " + line)
            p.wait()
            with self._lock:
                self._proc = None
                cancelled = self._job["cancelled"]
            cli_install.refresh_path()
            if cancelled:
                return False, "Đã dừng"
            if p.returncode != 0 and not (cmd[0] == "winget" and p.returncode in WINGET_FINE):
                tail = " ".join(self._job["log"][-6:]).lower()
                hint = " — cần quyền quản trị: chạy lệnh ở nhật ký trong Terminal (Administrator)" \
                    if any(w in tail for w in ("eacces", "eperm", "access is denied", "administrator")) else ""
                return False, f"Mã thoát {p.returncode}{hint}"
        cli_install._py_cache.clear()
        return True, ""

    # ---- skill từ gói cài (<app>/skills) — bản đang có đổi tên .bak-…, không xoá
    @staticmethod
    def _backup(dest: Path) -> str:
        if not dest.exists():
            return ""
        stamp = f"{dest.name}.bak-{datetime.now():%Y%m%d%H%M%S}"
        backup, k = dest.with_name(stamp), 1
        while backup.exists():  # 2 lần thay trong cùng 1 giây → thêm số, không ghi đè bản sao cũ
            k += 1
            backup = dest.with_name(f"{stamp}-{k}")
        dest.rename(backup)
        return str(backup)

    def _skill_from_bundle(self, name: str) -> tuple[bool, str]:
        src = bundled_skill(name)
        if src is None:
            return False, "Gói cài không có skill này — chọn file .skill"
        dest = Path.home() / ".claude" / "skills" / name
        self._log(f"▶ Skill {name} (từ gói cài)")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            backup = self._backup(dest)
            if backup:
                self._log(f"  bản cũ giữ lại: {Path(backup).name}")
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except OSError as exc:
            return False, f"Không chép được: {exc}"
        self._log(f"  đã chép vào {dest}")
        return True, ""

    # ---- skill từ file .skill (zip)
    def install_skill(self, path: str) -> dict:
        src = Path(str(path or ""))
        if not src.is_file() or src.suffix.lower() not in (".skill", ".zip"):
            raise SetupError("Chọn file .skill (hoặc .zip)")
        try:
            zf = zipfile.ZipFile(src)
        except zipfile.BadZipFile as exc:
            raise SetupError("File .skill hỏng (không phải zip)") from exc
        with zf:
            names = zf.namelist()
            tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
            if len(tops) != 1 or f"{next(iter(tops))}/SKILL.md" not in names:
                raise SetupError("File .skill phải có đúng 1 thư mục chứa SKILL.md")
            name = next(iter(tops))
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name) or name in (".", ".."):
                raise SetupError("Tên skill không hợp lệ")
            dest_root = Path.home() / ".claude" / "skills"
            dest_root.mkdir(parents=True, exist_ok=True)
            root = dest_root.resolve()
            for n in names:  # chặn đường dẫn thoát ra ngoài (zip-slip)
                target = (root / n).resolve()
                if root not in target.parents:
                    raise SetupError(f"File .skill có đường dẫn không an toàn: {n}")
            dest = dest_root / name
            backup = self._backup(dest)  # bản cũ → giữ lại cạnh bên (không xoá)
            zf.extractall(dest_root)
        if f"skill:{name}" in BY_KEY:
            self.check([f"skill:{name}"])
        return {"name": name, "path": str(dest), "backup": backup}

    # ---- đăng nhập
    def login(self, key: str) -> dict:
        t = BY_KEY.get(key)
        if not t or not t.get("login"):
            raise SetupError("Mục này không đăng nhập ở đây")
        if t["login"] == "claude":
            from .tvc_claude import native_claude

            exe = native_claude()
            if not exe:
                raise SetupError("Chưa cài Claude Code (.exe)")
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", "start", "VideoAgent - Dang nhap Claude", "cmd", "/k", exe, "/login"],
                                 creationflags=NOWIN)
            return {"command": f"{exe} /login"}
        return cli_install.login(t["login"])

    # ---- báo cáo cho người hỗ trợ (không có token / cookie)
    def report(self) -> str:
        from . import __version__

        st = self.state()
        lines = [f"VideoAgent {__version__} · {platform.platform()} · {datetime.now():%Y-%m-%d %H:%M}",
                 f"Sẵn sàng {st['summary']['ready']}/{st['summary']['need']} mục cần thiết", ""]
        home = str(Path.home())
        for g, label in GROUPS.items():
            lines.append(f"[{label}]")
            for r in [x for x in st["tools"] if x["group"] == g]:
                mark = {"ok": "✓", "missing": "✗", "old": "⚠", "login": "🔑"}.get(r["state"], "?")
                extra = " · ".join(x for x in (r.get("version"), r.get("detail")) if x)
                path = (r.get("path") or "").replace(home, "~")
                lines.append(f"  {mark} {r['name']}{' (cần)' if r['need'] else ''}: {r['state_label']}"
                             + (f" — {extra}" if extra else "") + (f" [{path}]" if path else ""))
            lines.append("")
        job = st["job"]
        if job["done"]:
            lines.append("[Lần cài gần nhất]")
            lines += [f"  {'✓' if d['ok'] else '✗'} {d['name']}" + (f" — {d['error']}" if d["error"] else "")
                      for d in job["done"]]
        return "\n".join(lines).strip()


# ---------------------------------------------------------------------- tự kiểm bản build (build.ps1: VideoAgent.exe --selfcheck)
SELFCHECK_MODULES = ("webview", "playwright", "edge_tts", "google.genai", "anthropic", "jinja2", "imageio_ffmpeg", "requests",
                     "PIL", "markdown", "yt_dlp", "curl_cffi", "claude_agent_sdk", "app.api", "app.server", "app.setup_tools")


def selfcheck(out_file: str = "") -> int:
    """Nạp mọi thư viện + claude.exe đi kèm SDK; ghi kết quả ra file (exe dạng cửa sổ không có console). 0 = ổn."""
    import importlib

    bad, lines = [], []
    for m in SELFCHECK_MODULES:
        try:
            importlib.import_module(m)
            lines.append(f"OK {m}")
        except Exception as exc:  # noqa: BLE001
            bad.append(m)
            lines.append(f"FAIL {m}: {exc}")
    try:
        import claude_agent_sdk

        base = Path(claude_agent_sdk.__file__).parent / "_bundled"
        found = next((p for p in (base / "claude.exe", base / "claude") if p.is_file()), None)
        # thiếu chỉ cảnh báo: Trợ lý TVC vẫn chạy được bằng Claude Code cài trên máy (~/.local/bin/claude)
        lines.append(f"OK claude đi kèm SDK: {found.name}" if found else f"WARN không thấy claude đi kèm SDK ({base})")
    except Exception:  # noqa: BLE001
        pass
    for n in SKILLS:  # skill đóng gói kèm (VideoAgent.spec datas skills)
        if bundled_skill(n) is not None:
            lines.append(f"OK skill {n}")
        else:
            bad.append(f"skill {n}")
            lines.append(f"FAIL skill {n}: thiếu trong gói ({BUNDLED_SKILLS})")
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        lines.append(f"OK ffmpeg {get_ffmpeg_exe()}")
    except Exception as exc:  # noqa: BLE001
        bad.append("ffmpeg")
        lines.append(f"FAIL ffmpeg: {exc}")
    text = "\n".join(lines + [f"RESULT {'FAIL ' + ', '.join(bad) if bad else 'OK'}"])
    if out_file:
        Path(out_file).write_text(text, "utf-8")
    else:
        print(text)
    return 1 if bad else 0
