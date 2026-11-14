"""🔌 Quản lý kết nối MCP của app (màn “Kết nối MCP”): danh sách máy chủ, kiểm tra kết nối, quyền từng công cụ, nhật ký,
và cầu nối cho Trợ lý Canvas đọc dữ liệu.

An toàn:
  • token / header / biến môi trường chỉ lưu trên máy — public() che hết (giao diện chỉ thấy tên khoá + ••••••)
  • chỉ gọi công cụ ĐƯỢC PHÉP; công cụ máy chủ đánh dấu chỉ đọc (readOnlyHint) mặc định được phép, công cụ có thể ghi
    mặc định bị chặn (người dùng tự bật)
  • kết quả trả về là DỮ LIỆU (Trợ lý được dặn không làm theo chỉ dẫn trong đó)
Lưu: DATA_DIR/mcp/servers.json (cấu hình + danh sách công cụ đã đọc), DATA_DIR/mcp/log.json (100 lần gọi gần nhất)."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .mcp_client import McpError, McpSession
from .paths import DATA_DIR
from .util import read_json, write_json

STORE = DATA_DIR / "mcp"
MASK = "••••••"
MAX_LOG = 100
MAX_RESULT = 8000      # chữ kết quả tối đa mỗi lần gọi (gửi Trợ lý / hiện khi thử)
MAX_DESC = 500
MAX_SCHEMA = 1500
KINDS = ("stdio", "http")
_lock = threading.Lock()


class HubError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _servers_file() -> Path:
    return STORE / "servers.json"


def _log_file() -> Path:
    return STORE / "log.json"


def _load() -> list[dict]:
    try:
        data = read_json(_servers_file()) if _servers_file().is_file() else []
    except (OSError, ValueError):
        data = []
    return [s for s in data if isinstance(s, dict) and s.get("id")] if isinstance(data, list) else []


def _save(servers: list[dict]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    write_json(_servers_file(), servers)


def _get(servers: list[dict], sid: str) -> dict:
    s = next((x for x in servers if x["id"] == sid), None)
    if s is None:
        raise HubError("Không tìm thấy kết nối MCP này")
    return s


# ---------------------------------------------------------------------- dữ liệu cho giao diện (đã che bí mật)
_CRED = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")
_SECRET_ARG = re.compile(r"((?:token|key|secret|password|passwd|pwd)=)[^&\s]+", re.I)


def _mask_arg(a: str) -> str:
    """Tham số lệnh có mật khẩu (mongodb://user:pass@…, …?token=…) → che phần bí mật."""
    return _SECRET_ARG.sub(r"\1" + MASK, _CRED.sub(r"\1" + MASK + "@", str(a)))


def public(s: dict) -> dict:
    allowed = set(s.get("allowed") or [])
    tools = [{**t, "allowed": t["name"] in allowed} for t in s.get("tools") or []]
    return {
        "id": s["id"], "name": s.get("name", ""), "kind": s.get("kind", "stdio"), "command": s.get("command", ""),
        "args": [_mask_arg(a) for a in s.get("args") or []], "cwd": s.get("cwd", ""), "url": _mask_arg(s.get("url", "")),
        "env": [{"key": k, "set": bool(v)} for k, v in (s.get("env") or {}).items()],
        "headers": [{"key": k, "set": bool(v)} for k, v in (s.get("headers") or {}).items()],
        "enabled": bool(s.get("enabled", True)), "assistant": bool(s.get("assistant", True)),
        "status": s.get("status", "unchecked"), "error": s.get("error", ""), "checked_at": s.get("checked_at", ""),
        "server_info": s.get("server_info") or {}, "tools": tools,
        "allowed_count": sum(1 for t in tools if t["allowed"]),
    }


def list_servers() -> list[dict]:
    return [public(s) for s in _load()]


# ---------------------------------------------------------------------- thêm / sửa / xoá
def _pairs(rows, old: dict) -> dict:
    """[{key, value}] từ form → dict; value rỗng hoặc MASK = giữ giá trị cũ (giao diện không bao giờ thấy giá trị thật)."""
    out = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        key = str(r.get("key") or "").strip()
        if not key or not re.fullmatch(r"[A-Za-z0-9_\-.]{1,80}", key):
            continue
        val = str(r.get("value") if r.get("value") is not None else "")
        out[key] = old.get(key, "") if val in ("", MASK) else val
    return out


def save_server(data: dict) -> dict:
    data = data or {}
    name = " ".join(str(data.get("name") or "").split())[:60]
    kind = str(data.get("kind") or "stdio")
    if not name:
        raise HubError("Nhập tên kết nối")
    if kind not in KINDS:
        raise HubError("Kiểu kết nối không hợp lệ")
    with _lock:
        servers = _load()
        sid = str(data.get("id") or "")
        old = _get(servers, sid) if sid else {}
        if any(x["name"].lower() == name.lower() and x["id"] != sid for x in servers):
            raise HubError(f"Đã có kết nối tên “{name}”")
        s = {**old, "id": sid or "m" + uuid.uuid4().hex[:7], "name": name, "kind": kind,
             "enabled": bool(data.get("enabled", old.get("enabled", True))),
             "assistant": bool(data.get("assistant", old.get("assistant", True)))}
        if kind == "stdio":
            cmd = str(data.get("command") or "").strip()
            if not cmd:
                raise HubError("Nhập lệnh chạy máy chủ (VD npx, uvx, python)")
            args = data.get("args")
            args = [str(a) for a in args] if isinstance(args, list) else [a for a in str(args or "").splitlines() if a.strip()]
            masked = {_mask_arg(a): a for a in old.get("args") or []}  # giao diện gửi lại bản đã che → lấy lại bản gốc
            args = [masked.get(a.strip(), a.strip()) if MASK in a else a.strip() for a in args]
            s.update(command=cmd[:400], args=args[:40], cwd=str(data.get("cwd") or "").strip()[:400],
                     env=_pairs(data.get("env"), old.get("env") or {}), url="", headers={})
        else:
            url = str(data.get("url") or "").strip()
            if MASK in url and old.get("url") and _mask_arg(old["url"]) == url:
                url = old["url"]
            if not url.startswith(("http://", "https://")):
                raise HubError("Địa chỉ phải bắt đầu bằng http:// hoặc https://")
            s.update(url=url[:500], headers=_pairs(data.get("headers"), old.get("headers") or {}), command="", args=[],
                     cwd="", env={})
        if any(old.get(k) != s.get(k) for k in ("kind", "command", "args", "cwd", "env", "url", "headers")):
            s.update(status="unchecked", error="")  # đổi cách kết nối → phải kiểm tra lại
        servers = [s if x["id"] == s["id"] else x for x in servers] if old else [*servers, s]
        _save(servers)
        return public(s)


def delete_server(sid: str) -> None:
    with _lock:
        servers = _load()
        _get(servers, sid)
        _save([x for x in servers if x["id"] != sid])


def set_flag(sid: str, key: str, value: bool) -> dict:
    if key not in ("enabled", "assistant"):
        raise HubError("Thiết lập không hợp lệ")
    with _lock:
        servers = _load()
        s = _get(servers, sid)
        s[key] = bool(value)
        _save(servers)
        return public(s)


def set_allowed(sid: str, tool: str, allowed: bool) -> dict:
    with _lock:
        servers = _load()
        s = _get(servers, sid)
        if tool not in {t["name"] for t in s.get("tools") or []}:
            raise HubError("Không có công cụ này — bấm Kiểm tra kết nối để cập nhật danh sách")
        s["allowed"] = [t for t in s.get("allowed") or [] if t != tool] + ([tool] if allowed else [])
        _save(servers)
        return public(s)


# ---------------------------------------------------------------------- kiểm tra kết nối / gọi công cụ
def _tool_row(t: dict) -> dict:
    ann = t.get("annotations") if isinstance(t.get("annotations"), dict) else {}
    schema = json.dumps(t.get("inputSchema") or {}, ensure_ascii=False)
    return {"name": str(t["name"])[:120], "title": str(t.get("title") or ann.get("title") or "")[:120],
            "description": " ".join(str(t.get("description") or "").split())[:MAX_DESC],
            "read_only": ann.get("readOnlyHint") if isinstance(ann.get("readOnlyHint"), bool) else None,
            "destructive": ann.get("destructiveHint") if isinstance(ann.get("destructiveHint"), bool) else None,
            "schema": schema[:MAX_SCHEMA]}


def check(sid: str) -> dict:
    """Kết nối thử → đọc danh sách công cụ. Công cụ MỚI: chỉ đọc → cho phép sẵn; còn lại → chặn (người dùng tự bật)."""
    with _lock:
        s = dict(_get(_load(), sid))
    try:
        with McpSession(s) as ses:
            tools, info = [_tool_row(t) for t in ses.tools()], ses.info
        status, error = "ok", ""
    except McpError as exc:
        tools, info, status, error = None, None, "error", str(exc)[:500]
    with _lock:
        servers = _load()
        cur = _get(servers, sid)
        cur.update(status=status, error=error, checked_at=_now())
        if tools is not None:
            seen = set(cur.get("seen") or [])
            names = {t["name"] for t in tools}
            allowed = [t for t in cur.get("allowed") or [] if t in names]
            allowed += [t["name"] for t in tools if t["name"] not in seen and t["read_only"] is True and t["name"] not in allowed]
            cur.update(tools=tools, allowed=allowed, seen=sorted(seen | names),
                       server_info={k: str(v)[:80] for k, v in (info or {}).items() if k in ("name", "version", "title")})
        _save(servers)
        return public(cur)


def _log(entry: dict) -> None:
    with _lock:
        try:
            rows = read_json(_log_file()) if _log_file().is_file() else []
        except (OSError, ValueError):
            rows = []
        rows = (rows if isinstance(rows, list) else []) + [entry]
        STORE.mkdir(parents=True, exist_ok=True)
        write_json(_log_file(), rows[-MAX_LOG:])


def logs() -> list[dict]:
    try:
        rows = read_json(_log_file()) if _log_file().is_file() else []
    except (OSError, ValueError):
        rows = []
    return list(reversed(rows if isinstance(rows, list) else []))


def clear_logs() -> None:
    with _lock:
        if _log_file().is_file():
            _log_file().unlink()


def call_tool(sid: str, tool: str, args: dict | None = None, *, via: str = "thử") -> dict:
    """Gọi 1 công cụ ĐƯỢC PHÉP → {ok, text, error}. via = "thử" (màn quản lý) / "trợ lý" (Trợ lý Canvas)."""
    args = args if isinstance(args, dict) else {}
    with _lock:
        s = dict(_get(_load(), sid))
    if not s.get("enabled", True):
        raise HubError(f"Kết nối “{s['name']}” đang tắt")
    if tool not in (s.get("allowed") or []):
        raise HubError(f"Công cụ “{tool}” chưa được cho phép trên kết nối “{s['name']}”")
    entry = {"at": _now(), "server": s["name"], "sid": sid, "tool": tool, "via": via,
             "args": json.dumps(args, ensure_ascii=False)[:300]}
    try:
        with McpSession(s) as ses:
            text, is_err = ses.call(tool, args)
    except McpError as exc:
        _log({**entry, "ok": False, "error": str(exc)[:300], "chars": 0})
        return {"ok": False, "text": "", "error": str(exc)[:500]}
    full = len(text)
    text = text[:MAX_RESULT] + (f"\n… (cắt bớt, tổng {full} ký tự)" if full > MAX_RESULT else "")
    _log({**entry, "ok": not is_err, "error": text[:300] if is_err else "", "chars": full})
    return {"ok": not is_err, "text": text, "error": text[:500] if is_err else ""}


# ---------------------------------------------------------------------- cho Trợ lý Canvas
def tools_for(sid: str = "", *, assistant: bool = False) -> list[dict]:
    """Công cụ ĐƯỢC PHÉP của các kết nối đang bật (sid = chỉ 1 kết nối; assistant = chỉ kết nối bật “dùng cho Trợ lý”)."""
    out = []
    for s in _load():
        if not s.get("enabled", True) or (sid and s["id"] != sid) or (assistant and not s.get("assistant", True)):
            continue
        allowed = set(s.get("allowed") or [])
        for t in s.get("tools") or []:
            if t["name"] in allowed:
                out.append({"sid": s["id"], "server": s["name"], **t})
    return out


def assistant_tools() -> list[dict]:
    """Công cụ Trợ lý được dùng: kết nối đang bật + bật “dùng cho Trợ lý” + công cụ được phép."""
    return tools_for(assistant=True)


def server_options() -> list[dict]:
    """Ô chọn của khối Tra cứu MCP: kết nối + công cụ được phép (không có bí mật)."""
    return [{"id": s["id"], "name": s["name"], "enabled": bool(s.get("enabled", True)),
             "tools": [t for t in s.get("allowed") or [] if t in {x["name"] for x in s.get("tools") or []}]} for s in _load()]


def assistant_catalog(limit: int = 9000) -> str:
    return catalog(assistant_tools(), limit)


def catalog(tools: list[dict], limit: int = 9000) -> str:
    """Danh mục công cụ gửi model: id kết nối, tên công cụ, mô tả, schema tham số."""
    lines = []
    for t in tools:
        lines.append(f"- may_chu \"{t['sid']}\" ({t['server']}) · cong_cu \"{t['name']}\""
                     + (" [chỉ đọc]" if t.get("read_only") else "") + f": {t.get('description') or t.get('title') or ''}"
                     + f"\n  tham_so (JSON schema): {t.get('schema') or '{}'}")
    text = "\n".join(lines)
    return text[:limit] + ("\n… (còn công cụ khác)" if len(text) > limit else "")


# ---------------------------------------------------------------------- nhập từ Claude Desktop
def claude_desktop_file() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"


def import_claude_desktop(path: str | None = None) -> dict:
    """Thêm các máy chủ trong mcpServers của Claude Desktop (bỏ qua tên đã có). Chỉ đọc file đó, không sửa."""
    src = Path(path) if path else claude_desktop_file()
    if not src.is_file():
        raise HubError(f"Không thấy file cấu hình Claude Desktop ({src})")
    try:
        conf = json.loads(src.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise HubError(f"Không đọc được {src.name}: {exc}") from exc
    items = conf.get("mcpServers") if isinstance(conf, dict) else None
    if not isinstance(items, dict) or not items:
        raise HubError("File Claude Desktop chưa có máy chủ MCP nào (mcpServers)")
    have = {s["name"].lower() for s in _load()}
    added, skipped = [], []
    for name, c in items.items():
        if not isinstance(c, dict) or str(name).lower() in have:
            skipped.append(str(name))
            continue
        if c.get("url"):
            data = {"name": name, "kind": "http", "url": c["url"],
                    "headers": [{"key": k, "value": v} for k, v in (c.get("headers") or {}).items()]}
        else:
            data = {"name": name, "kind": "stdio", "command": c.get("command", ""), "args": list(c.get("args") or []),
                    "env": [{"key": k, "value": v} for k, v in (c.get("env") or {}).items()]}
        try:
            save_server(data)
            added.append(str(name))
        except HubError:
            skipped.append(str(name))
    return {"added": added, "skipped": skipped}
