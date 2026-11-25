"""🧠 Gọi model chữ qua CLI (Claude Code, OpenAI Codex, Gemini CLI, Grok CLI, muse-cli) thay cho trình duyệt.

Cài đặt → Trình duyệt → "Cách gọi model chữ": mỗi hãng chọn Trình duyệt | CLI (settings "llm_mode_<hãng>"). Khi chọn CLI,
mọi chỗ dùng "<hãng>_browser" cho VIỆC CHỮ (make_provider) chạy qua CLI — tạo ảnh / video vẫn qua trình duyệt.

An toàn: mỗi lần chạy trong 1 thư mục tạm trống, chế độ chỉ trả lời chữ (Claude tắt công cụ ghi / chạy lệnh / web,
Codex sandbox read-only, Gemini / Grok không tự duyệt thao tác), prompt gửi qua stdin, có giới hạn thời gian và dừng được.
Lỗi (chưa cài, chưa đăng nhập, hết lượt…) → nếu bật "llm_cli_fallback" thì lượt đó chạy bằng trình duyệt.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .base import LLMError, LLMProvider

TIMEOUT_S = 900
# hãng (= site của <site>_browser) → CLI
CLIS = {
    "claude": {"name": "Claude Code CLI", "bin": "claude", "install": "npm i -g @anthropic-ai/claude-code",
               "login": "chạy `claude` 1 lần trong Terminal rồi đăng nhập tài khoản Claude", "images": True},
    "chatgpt": {"name": "OpenAI Codex CLI", "bin": "codex", "install": "npm i -g @openai/codex",
                "login": "chạy `codex login` (đăng nhập tài khoản ChatGPT)", "images": True},
    "gemini": {"name": "Gemini CLI", "bin": "gemini", "install": "npm i -g @google/gemini-cli",
               "login": "chạy `gemini` 1 lần trong Terminal rồi đăng nhập Google", "images": False},
    "grok": {"name": "Grok CLI (cộng đồng)", "bin": "grok", "install": "npm i -g @vibe-kit/grok-cli",
             "login": "cần xAI API key (ô bên dưới) — tính tiền theo API, không dùng tài khoản grok.com",
             "images": False},
    # muse.ai: muse-cli (cộng đồng, Python — app/llm/muse_cli.py); đăng nhập = cookie muse.ai, mỗi lượt 1 side chat mới
    "muse": {"name": "muse.ai CLI (muse-cli, cộng đồng)", "bin": "muse-cli", "install": "py -m pip install --user muse-cli",
             "login": "lấy cookie đăng nhập muse.ai từ profile Muse của app hoặc dán tay (🔑 Đăng nhập)", "images": False},
}
# gói npm (cài / cập nhật) + lệnh đăng nhập (mở cửa sổ Terminal) — Grok dùng API key, Muse dùng cookie (không Terminal)
NPM_PKG = {"claude": "@anthropic-ai/claude-code", "chatgpt": "@openai/codex", "gemini": "@google/gemini-cli",
           "grok": "@vibe-kit/grok-cli"}
LOGIN_ARGS = {"claude": [], "chatgpt": ["login"], "gemini": []}
# Claude Code: chế độ chỉ trả lời — tắt công cụ chạy lệnh / sửa file / web / tác tử con (Read chỉ mở khi có ảnh)
CLAUDE_DENY = "Bash Edit Write MultiEdit NotebookEdit WebFetch WebSearch Task Glob Grep TodoWrite"
_status_cache: dict = {}
_status_lock = threading.Lock()


# ⏳ CLI hết lượt / hết credit (Codex "usage limit", Claude "limit reached", Gemini "quota", xAI "insufficient credits"…)
# → ghi nhớ đến giờ mở lại (đọc trong thông báo; không có thì QUOTA_COOLDOWN), trong thời gian đó việc chữ của hãng đó
# đi thẳng trình duyệt (không thử CLI mỗi lượt). Nhớ trong phiên chạy app.
QUOTA_RE = re.compile(r"usage limit|out of [\w\s]{0,30}usage|hit your (?:usage )?limit|limit reached|rate.?limit|quota|"
                      r"insufficient[_ ]?(?:quota|credit|balance|funds)|credit balance|no (?:more )?credits|out of credits|"
                      r"too many requests|resource.?exhausted|\b429\b", re.I)
QUOTA_COOLDOWN = 20 * 60
_exhausted: dict[str, dict] = {}


class CliQuotaError(LLMError):
    """CLI hết lượt / hết credit — lượt đó LUÔN chạy bằng trình duyệt (không phụ thuộc tuỳ chọn llm_cli_fallback)."""


def _reset_at(text: str, now: float | None = None) -> float | None:
    """Giờ mở lại trong thông báo CLI: "try again at 1:07 PM", "resets 3pm", "reset at 13:07", "|1767000000" (epoch),
    "in 2h 30m" / "in 45 minutes" → timestamp; không đọc được → None."""
    from datetime import datetime, timedelta

    now = time.time() if now is None else now
    text = str(text or "")
    m = re.search(r"\|(\d{10})\b", text)
    if m and float(m.group(1)) > now:
        return float(m.group(1))
    m = re.search(r"\bin\s+(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?", text, re.I)
    if m and (m.group(1) or m.group(2)):
        return now + int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    m = re.search(r"(?:again at|resets?(?: at)?|available (?:again )?at|until)\s+(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?",
                  text, re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    base = datetime.fromtimestamp(now)
    at = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at.timestamp() <= now:
        at += timedelta(days=1)
    return at.timestamp()


def is_quota_error(text: str) -> bool:
    return bool(QUOTA_RE.search(str(text or "")))


def mark_exhausted(site: str, text: str) -> dict:
    until = _reset_at(text) or (time.time() + QUOTA_COOLDOWN)
    line = next((x.strip() for x in str(text or "").splitlines() if QUOTA_RE.search(x)), str(text or "").strip())
    with _status_lock:
        _exhausted[site] = {"until": until, "msg": line.replace("❌", "").strip()[:240]}
    return quota_info(site)


def exhausted(site: str) -> dict | None:
    with _status_lock:
        q = _exhausted.get(site)
        if q and q["until"] <= time.time():
            _exhausted.pop(site, None)
            q = None
    return q


def clear_exhausted(site: str) -> None:
    with _status_lock:
        _exhausted.pop(site, None)


def quota_info(site: str) -> dict | None:
    """Cho giao diện: {"until": "13:07", "msg": …} khi CLI đang hết lượt."""
    from datetime import datetime

    q = exhausted(site)
    if not q:
        return None
    at = datetime.fromtimestamp(q["until"])
    day = "" if at.date() == datetime.now().date() else at.strftime(" %d/%m")
    return {"until": at.strftime("%H:%M") + day, "msg": q["msg"]}


def which(site: str) -> str:
    spec = CLIS.get(site)
    if site == "muse":
        from . import muse_cli

        return muse_cli.find()
    return (shutil.which(spec["bin"]) or "") if spec else ""


def status(site: str, refresh: bool = False) -> dict:
    """Đã cài chưa + phiên bản (chạy `<bin> --version`, không gọi model, không tốn lượt)."""
    spec = CLIS[site]
    with _status_lock:
        cached = _status_cache.get(site) if not refresh else None
    if cached is not None:
        return {**cached, "quota": quota_info(site)}  # ⏳ hết lượt: tính lại mỗi lần (hết hạn tự bỏ)
    path = which(site)
    version = ""
    if path:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, encoding="utf-8",
                                 errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            lines = (out.stdout or out.stderr or "").strip().splitlines()
            version = lines[0][:80] if lines and (out.returncode == 0 or site != "muse") else ""
        except (OSError, subprocess.SubprocessError):
            version = ""
    info = {"site": site, "name": spec["name"], "installed": bool(path), "path": path, "version": version,
            "install": spec["install"], "login": spec["login"], "images": spec["images"]}
    if site == "muse":  # đã có cookie đăng nhập chưa (chỉ xem file, không gọi muse.ai)
        from . import muse_cli

        info["muse_login"] = muse_cli.cookie_state()
    with _status_lock:
        _status_cache[site] = info
    return {**info, "quota": quota_info(site)}


def mode(settings, site: str) -> str:
    return "cli" if str(settings.get(f"llm_mode_{site}") or "browser") == "cli" else "browser"


CLI_SHORT = {"claude": "Claude Code", "chatgpt": "Codex", "gemini": "Gemini CLI", "grok": "Grok CLI", "muse": "muse-cli"}


def via_cli(settings, site: str) -> bool:
    """Việc chữ của hãng này đang chạy qua CLI thật (đã chọn CLI + đã cài) — dùng cho nhãn ô chọn model."""
    return site in CLIS and mode(settings, site) == "cli" and bool(which(site))


def label(settings, site: str, name: str) -> str:
    """Tên hiện ở ô chọn model chữ: "ChatGPT · CLI (Codex)" khi đang chạy CLI, không thì "ChatGPT (trình duyệt)"."""
    return f"{name} · CLI ({CLI_SHORT[site]})" if via_cli(settings, site) else f"{name} (trình duyệt)"


def exec_cmd(cmd: list[str], *, cwd, env, stdin_text, timeout_s: int, check_cancel=None, name: str = "CLI"):
    """Chạy lệnh (ẩn cửa sổ), gửi stdin, chờ có giới hạn thời gian + dừng được → (mã thoát, stdout, stderr)."""
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise LLMError(f"Không chạy được {name}: {exc}") from exc
    result: dict = {}

    def talk():
        try:
            result["out"], result["err"] = proc.communicate(stdin_text)
        except Exception as exc:  # noqa: BLE001
            result["exc"] = exc
    worker = threading.Thread(target=talk, daemon=True)
    worker.start()
    t0 = time.time()
    while worker.is_alive():
        worker.join(0.5)
        try:
            if check_cancel:
                check_cancel()
        except BaseException:
            proc.kill()
            raise
        if time.time() - t0 > timeout_s:
            proc.kill()
            raise LLMError(f"{name} quá {max(1, timeout_s // 60)} phút chưa trả lời")
    if "exc" in result:
        raise LLMError(f"{name} lỗi: {result['exc']}")
    return proc.returncode, (result.get("out") or "").strip(), (result.get("err") or "").strip()


def _command(site: str, path: str, images: list[Path]) -> tuple[list[str], str]:
    """Lệnh chạy + phần chữ thêm vào prompt (đường dẫn ảnh). Prompt luôn gửi qua stdin."""
    if site == "claude":
        cmd = [path, "-p", "--output-format", "text", "--disallowedTools", CLAUDE_DENY]
        cmd += ["--allowedTools", "Read"] if images else ["--disallowedTools", "Read"]
        note = ("\n\nẢnh đính kèm (đọc bằng công cụ Read, theo thứ tự):\n" + "\n".join(f"- {p}" for p in images)) if images else ""
        return cmd, note
    if site == "chatgpt":
        cmd = [path, "exec", "--sandbox", "read-only", "--skip-git-repo-check"]
        for p in images:
            cmd += ["-i", str(p)]
        return cmd + ["-"], ""
    return [path, "--prompt", "Trả lời đúng yêu cầu ở phần nội dung được gửi kèm (stdin)."], ""


def _image_files(images, folder: Path) -> list[Path]:
    """Ảnh đính kèm (đường dẫn hoặc (bytes, mime)) → file trong thư mục tạm của lượt chạy."""
    out = []
    for i, item in enumerate(images or [], 1):
        if isinstance(item, str) and item.startswith("data:image"):
            dest = folder / f"anh_{i}.png"
            dest.write_bytes(base64.b64decode(item.split(",", 1)[-1]))
            out.append(dest)
        elif isinstance(item, (str, Path)) and Path(item).is_file():
            dest = folder / f"anh_{i}{Path(item).suffix.lower() or '.png'}"
            shutil.copy2(item, dest)
            out.append(dest)
        elif isinstance(item, (tuple, list)) and item and isinstance(item[0], (bytes, bytearray)):
            ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(str(item[1]) if len(item) > 1 else "", ".png")
            dest = folder / f"anh_{i}{ext}"
            dest.write_bytes(bytes(item[0]))
            out.append(dest)
    return out


GROK_NO_KEY = ("Grok CLI chưa có xAI API key — nhập vào ô \"xAI API key cho Grok CLI\" (Cài đặt → Trình duyệt) rồi Lưu. "
               "Key lấy ở console.x.ai, tính tiền theo API (không dùng tài khoản grok.com)")


def grok_key(override: str = "") -> str:
    """xAI API key cho Grok CLI: ô đang gõ (chưa lưu) → Cài đặt → biến môi trường GROK_API_KEY → "(file)" nếu
    ~/.grok/user-settings.json đã có apiKey; không có → ""."""
    key = str(override or "").strip()
    if not key:
        from ..config import settings

        key = str(settings.get("grok_cli_key") or "").strip() or os.environ.get("GROK_API_KEY", "").strip()
    if key:
        return key
    try:
        import json

        data = json.loads((Path.home() / ".grok" / "user-settings.json").read_text("utf-8"))
        return "(file)" if isinstance(data, dict) and str(data.get("apiKey") or "").strip() else ""
    except (OSError, ValueError):
        return ""


def run(site: str, prompt: str, images=None, *, timeout_s: int = TIMEOUT_S, check_cancel=None,
        grok_key_override: str = "") -> str:
    """1 lượt hỏi qua CLI → câu trả lời (chữ). Lỗi → LLMError."""
    spec = CLIS.get(site)
    if spec is None:
        raise LLMError(f"Không có CLI cho '{site}'")
    path = which(site)
    if not path:
        raise LLMError(f"Chưa cài {spec['name']} — cài: {spec['install']}")
    if images and not spec["images"]:
        raise LLMError(f"{spec['name']} chưa nhận ảnh đính kèm")
    q = quota_info(site)
    if q:  # ⏳ đã biết hết lượt → không thử CLI, lượt này chạy bằng trình duyệt
        raise CliQuotaError(f"{spec['name']} hết lượt / hết credit đến {q['until']}")
    if site == "muse":  # muse-cli: side chat mới mỗi lượt, đọc JSON .reply.text
        from . import muse_cli

        try:
            return muse_cli.ask(path, prompt, timeout_s=timeout_s, check_cancel=check_cancel)
        except CliQuotaError:
            raise
        except LLMError as exc:
            if is_quota_error(str(exc)):
                q = mark_exhausted(site, str(exc))
                raise CliQuotaError(f"{spec['name']} hết lượt / hết credit đến {q['until']}: {exc}") from exc
            raise
    with tempfile.TemporaryDirectory(prefix="va-cli-") as tmp:
        folder = Path(tmp)
        files = _image_files(images, folder)
        cmd, note = _command(site, path, files)
        env = {**os.environ, "NO_COLOR": "1", "CI": "1"}
        if site == "grok":  # xAI API key (Cài đặt) chỉ truyền vào lượt chạy Grok CLI
            key = grok_key(grok_key_override)
            if not key:
                raise LLMError(GROK_NO_KEY)
            if key != "(file)":
                env["GROK_API_KEY"] = key
        code, out, err = exec_cmd(cmd, cwd=folder, env=env, stdin_text=prompt + note, timeout_s=timeout_s,
                                  check_cancel=check_cancel, name=spec["name"])
        if code != 0 or not out:
            low = (err + out).lower()
            if is_quota_error(err + "\n" + out) and not (site == "grok" and "api key required" in low):
                q = mark_exhausted(site, err + "\n" + out)
                raise CliQuotaError(f"{spec['name']} hết lượt / hết credit đến {q['until']} ({q['msg'][:160]})")
            if site == "grok" and "api key" in low and ("required" in low or "invalid" in low or "incorrect" in low):
                raise LLMError(GROK_NO_KEY if "required" in low else
                               "xAI API key của Grok CLI không đúng / hết hạn — nhập lại key ở Cài đặt → Trình duyệt rồi Lưu")
            why = (err or out or f"mã thoát {code}").splitlines()[-1][:300]
            why = why.replace("❌", "").strip().removeprefix("Error:").strip()
            hint = f" — {spec['login']}" if any(w in low for w in ("login", "log in", "auth", "api key", "unauthorized",
                                                                   "credential")) else ""
            raise LLMError(f"{spec['name']} lỗi: {why}{hint}")
        return out


class CliChatProvider(LLMProvider):
    """Provider chữ qua CLI; fallback = provider trình duyệt dùng khi CLI lỗi (bật "llm_cli_fallback")."""

    def __init__(self, site: str, fallback=None, fallback_all: bool = True) -> None:
        self.site_key = site
        self.name = f"{site}_cli"
        self.fallback = fallback
        self.fallback_all = fallback_all  # False = chỉ chạy lại bằng trình duyệt khi CLI hết lượt / hết credit
        self.last_url = ""  # chỉ có khi lượt này chạy lại bằng trình duyệt (để bên gọi nhắn tiếp đúng cuộc trò chuyện)
        self.timeout_s = TIMEOUT_S

    @property
    def supports_images(self) -> bool:
        return CLIS[self.site_key]["images"] or bool(self.fallback and self.fallback.supports_images)

    def generate(self, prompt: str, images: list | None = None, complete=None) -> str:
        from ..browser_profiles import _ctx

        ctx = _ctx()
        log = ctx.get("log") or (lambda *a, **k: None)
        try:
            log(f"🧠 Đang hỏi {CLIS[self.site_key]['name']} (CLI)…")
            text = run(self.site_key, prompt, images, timeout_s=int(self.timeout_s or TIMEOUT_S),
                       check_cancel=ctx.get("check_cancel"))
            if complete is not None and not complete(text):  # VD storyboard JSON cụt / sai → như trình duyệt: không nhận
                raise LLMError(f"{CLIS[self.site_key]['name']} trả lời chưa đúng định dạng")
            return text
        except LLMError as exc:
            quota = isinstance(exc, CliQuotaError)  # ⏳ hết lượt / hết credit → luôn sang trình duyệt
            if self.fallback is None or not (quota or self.fallback_all):
                raise
            log(f"{exc} → chạy {'bằng trình duyệt cho tới khi CLI có lượt lại' if quota else 'lượt này bằng trình duyệt'}",
                "warn")
            text = self.fallback.generate(prompt, images=images, complete=complete)
            self.last_url = str(getattr(self.fallback, "last_url", "") or "")
            return text
