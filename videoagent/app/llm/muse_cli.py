"""muse.ai qua muse-cli (cộng đồng, github.com/nikships/muse-cli — không chính thức, giao thức có thể đổi).

- Cài: `uv tool install muse-cli` / `pipx install muse-cli` / `py -m pip install --user muse-cli` (Python ≥ 3.10).
  Lệnh là `muse-cli` (tên `muse` thuộc Muse Code) — pip --user đặt vào %APPDATA%\\Python\\Python3xx\\Scripts (thường không
  nằm trong PATH) → find() tìm thêm ở đó.
- Đăng nhập: file cookie ~/.config/muse-cli/cookies.txt (cần `hatch_sess`). App ghi file này từ profile Muse của app
  (hỏi xác nhận trước) hoặc từ cookie người dùng dán tay. Không gửi cookie lên giao diện.
- Việc chữ: mỗi lượt mở 1 side chat mới (`session-start`), `send --thread <id> --wait N` → JSON `.reply.text`, xong thì
  lưu trữ side chat (`session-archive`) — không gửi vào "Main chat" có lịch sử cũ.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .base import LLMError

NAME = "muse.ai CLI (muse-cli, cộng đồng)"
PYPI = "muse-cli"
MAX_PROMPT = 28_000  # dòng lệnh Windows tối đa ~32k ký tự (prompt đi qua tham số, muse-cli không đọc stdin)
EXIT_HINT = {2: "chưa đăng nhập / cookie muse.ai hết hạn — 🔑 Đăng nhập lại", 3: "lỗi cổng muse.ai", 4: "quá thời gian"}
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def cookies_file() -> Path:
    return Path.home() / ".config" / "muse-cli" / "cookies.txt"


def find() -> str:
    """Đường dẫn muse-cli: PATH → thư mục Scripts của pip --user / Python cài cho 1 người → ~/.local/bin (uv, pipx)."""
    hit = shutil.which("muse-cli")
    if hit:
        return hit
    appdata, local = os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")
    pats = [str(Path.home() / ".local" / "bin" / "muse-cli.exe")]
    if appdata:
        pats.append(os.path.join(appdata, "Python", "Python3*", "Scripts", "muse-cli.exe"))
    if local:
        pats.append(os.path.join(local, "Programs", "Python", "Python3*", "Scripts", "muse-cli.exe"))
        # Python bản Microsoft Store: pip --user cài vào LocalCache của gói
        pats.append(os.path.join(local, "Packages", "PythonSoftwareFoundation.Python.3*", "LocalCache", "local-packages",
                                 "Python3*", "Scripts", "muse-cli.exe"))
    for pat in pats:
        found = sorted(glob.glob(pat), reverse=True)
        if found:
            return found[0]
    return ""


# ---- cookie đăng nhập
def parse_cookies(text: str) -> dict:
    """Cookie dán tay / đọc file: "a=b; c=d" | JSON {"hatch_sess": …} | Netscape cookie jar (chỉ dòng muse.ai)."""
    text = str(text or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    out = {}
    if "\t" in text:  # Netscape: domain flag path secure expiry name value
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) >= 7 and not line.startswith("# ") and "muse.ai" in parts[0]:
                out[parts[5].strip()] = parts[6].strip()
        if out:
            return out
    text = text.removeprefix("Cookie:").removeprefix("cookie:").strip()
    for part in text.replace("\n", ";").split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            if name.strip() and value.strip():
                out[name.strip()] = value.strip()
    return out


def cookie_state() -> dict:
    """Đã có cookie đăng nhập chưa (chỉ kiểm tra có hatch_sess — không đọc ra giá trị)."""
    path = cookies_file()
    try:
        has = bool(parse_cookies(path.read_text("utf-8", errors="replace")).get("hatch_sess"))
    except OSError:
        has = False
    updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m %H:%M") if has else ""
    return {"logged_in": has, "file": str(path), "updated": updated}


def save_cookies(pairs: dict) -> dict:
    """Ghi cookies.txt cho muse-cli ("name=value; …"), giữ bản cũ ở .bak. Thiếu hatch_sess → lỗi, không ghi."""
    pairs = {k: v for k, v in (pairs or {}).items() if k and v and ";" not in k and "\n" not in v}
    if not pairs.get("hatch_sess"):
        raise LLMError("Không thấy cookie hatch_sess — cần đăng nhập muse.ai trước (hoặc dán đủ cookie có hatch_sess)")
    path = cookies_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".txt.bak"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("; ".join(f"{k}={v}" for k, v in pairs.items()) + "\n", "utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    return cookie_state()


def cookies_from_profile(channel: str = "") -> dict:
    """Mở profile Muse của app (ẩn), vào muse.ai (chỉ đọc, không gửi tin) → cookie muse.ai. Chưa đăng nhập → lỗi."""
    from playwright.sync_api import sync_playwright

    from .. import browser_profiles
    from .browser_chat import _launch

    mine = [p for p in browser_profiles.list_profiles() if "muse" in (p.get("sites") or [])]
    if not mine:
        raise LLMError("Chưa có profile trình duyệt nào gán cho Muse — vào Profile trình duyệt để gán và đăng nhập muse.ai")
    if all(p["id"] in browser_profiles.busy_ids() for p in mine):
        raise LLMError("Profile Muse đang bận chạy tác vụ — thử lại khi xong")
    with browser_profiles.profile_session("muse", "muse-cli · lấy đăng nhập") as prof, sync_playwright() as pw:
        ctx = _launch(pw, channel, visible=True, offscreen=True, profile=prof)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://muse.ai/", wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2500)
            except Exception:  # noqa: BLE001 — mạng chậm vẫn đọc được cookie đã lưu trong profile
                pass
            pairs = {c["name"]: c["value"] for c in ctx.cookies("https://muse.ai")}
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    if not pairs.get("hatch_sess"):
        raise LLMError(f"Profile “{prof['name']}” chưa đăng nhập muse.ai (không có cookie hatch_sess)")
    return pairs


# ---- gọi muse-cli
def call(path: str, args: list[str], *, timeout_s: int = 60, check_cancel=None) -> dict:
    """Chạy `muse-cli <args>` → JSON (mọi lệnh in JSON ra stdout; lỗi là chữ ở stderr + mã thoát 2/3/4)."""
    from .cli_chat import exec_cmd

    with tempfile.TemporaryDirectory(prefix="va-muse-") as tmp:
        env = {**os.environ, "NO_COLOR": "1", "MUSE_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": "utf-8"}
        code, out, err = exec_cmd([path, *args], cwd=tmp, env=env, stdin_text=None, timeout_s=timeout_s,
                                  check_cancel=check_cancel, name=NAME)
    if code != 0:
        why = next((x.strip() for x in reversed((err or out or "").splitlines()) if x.strip()), f"mã thoát {code}")[:300]
        hint = EXIT_HINT.get(code, "")
        raise LLMError(f"{NAME} lỗi: {why}" + (f" — {hint}" if hint and hint not in why else ""))
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise LLMError(f"{NAME} trả về không phải JSON: {out[:200]}") from exc
    return data if isinstance(data, dict) else {"value": data}


def check(path: str) -> dict:
    """`muse-cli status`: kiểm tra đăng nhập (đọc số phiên / danh tính — không gửi tin nhắn, không hỏi model)."""
    data = call(path, ["status"], timeout_s=60)
    ident = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    who = next((str(ident.get(k)) for k in ("name", "display_name", "username", "email") if ident.get(k)), "")
    return {"ok": True, "who": who, "sessions": data.get("sessions")}


def ask(path: str, prompt: str, *, timeout_s: int = 900, check_cancel=None) -> str:
    """1 lượt hỏi chữ: side chat mới → send --thread --wait → .reply.text → lưu trữ side chat."""
    prompt = str(prompt or "").strip()
    if len(prompt) > MAX_PROMPT:
        raise LLMError(f"Prompt quá dài cho muse-cli ({len(prompt):,} ký tự, tối đa {MAX_PROMPT:,}) — chạy bằng trình duyệt")
    started = call(path, ["session-start", "--title", f"VideoAgent {datetime.now():%d/%m %H:%M:%S}"], timeout_s=60,
                   check_cancel=check_cancel)
    sid = str(started.get("session_id") or started.get("id") or "")
    if not sid:
        raise LLMError(f"{NAME}: không mở được cuộc trò chuyện mới (không có session_id)")
    try:
        wait = max(30, int(timeout_s) - 30)
        res = call(path, ["send", prompt, "--thread", sid, "--wait", str(wait)], timeout_s=wait + 60,
                   check_cancel=check_cancel)
        reply = res.get("reply") if isinstance(res.get("reply"), dict) else {}
        text = str(reply.get("text") or "").strip()
        if not text:
            raise LLMError(f"{NAME}: Muse chưa trả lời trong {wait // 60} phút ({res.get('note') or 'không có reply'})")
        return text
    finally:
        try:
            call(path, ["session-archive", sid], timeout_s=30)
        except LLMError:
            pass
