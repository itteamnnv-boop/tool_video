"""🔌 Client MCP (Model Context Protocol) gọn của app — không cần thư viện mcp: JSON-RPC 2.0 qua
  • stdio: chạy lệnh trên máy (npx / uvx / python …), mỗi dòng 1 thông điệp JSON
  • http : Streamable HTTP (POST JSON; máy chủ trả application/json hoặc text/event-stream; giữ Mcp-Session-Id)
Chỉ dùng: initialize → tools/list → tools/call. Mọi lỗi → McpError (thông báo tiếng Việt)."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time

PROTOCOL = "2025-06-18"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class McpError(RuntimeError):
    pass


class _Stdio:
    def __init__(self, command: str, args: list[str], env: dict, cwd: str = "") -> None:
        exe = shutil.which(command) or command  # Windows: npx → npx.cmd
        try:
            self.proc = subprocess.Popen([exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         env={**os.environ, **env}, cwd=cwd or None, creationflags=NO_WINDOW,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as exc:
            raise McpError(f"Không chạy được lệnh “{command}”: {exc}") from exc
        self.inbox: queue.Queue = queue.Queue()
        self.err: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.inbox.put(json.loads(line))
            except ValueError:
                continue  # dòng log lẫn vào stdout
        self.inbox.put(None)

    def _read_err(self):
        for line in self.proc.stderr:
            self.err.append(line.rstrip())
            del self.err[:-20]

    def send(self, msg: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except OSError as exc:
            raise McpError("Máy chủ MCP đã dừng: " + self._tail()) from exc

    def _tail(self) -> str:
        return " | ".join(x for x in self.err[-3:] if x)[:400] or "không có thông báo"

    def request(self, msg: dict, timeout: float) -> dict:
        self.send(msg)
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise McpError(f"Máy chủ MCP không trả lời sau {timeout:g} giây")
            try:
                got = self.inbox.get(timeout=min(left, 0.5))
            except queue.Empty:
                if self.proc.poll() is not None and self.inbox.empty():
                    raise McpError("Máy chủ MCP đã thoát: " + self._tail())
                continue
            if got is None:
                raise McpError("Máy chủ MCP đã thoát: " + self._tail())
            if isinstance(got, dict) and got.get("id") == msg["id"] and ("result" in got or "error" in got):
                return got
            if isinstance(got, dict) and "method" in got and "id" in got:  # máy chủ hỏi ngược (ping…) → trả rỗng
                self.send({"jsonrpc": "2.0", "id": got["id"], "result": {}})

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            from .osutil import kill_tree

            kill_tree(self.proc)


class _Http:
    def __init__(self, url: str, headers: dict) -> None:
        import httpx

        self.url = url
        self.session = ""
        self.headers = {**headers, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        self.client = httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True)

    def _post(self, msg: dict, timeout: float):
        import httpx

        h = dict(self.headers)
        if self.session:
            h["Mcp-Session-Id"] = self.session
        if msg.get("method") != "initialize":
            h["MCP-Protocol-Version"] = PROTOCOL
        try:
            res = self.client.post(self.url, json=msg, headers=h, timeout=httpx.Timeout(30.0, read=timeout))
        except httpx.HTTPError as exc:
            raise McpError(f"Không kết nối được {self.url}: {exc}") from exc
        if res.status_code in (401, 403):
            raise McpError(f"Máy chủ MCP từ chối ({res.status_code}) — kiểm tra token / header xác thực")
        if res.status_code >= 400:
            raise McpError(f"Máy chủ MCP lỗi HTTP {res.status_code}: {res.text[:300]}")
        if res.headers.get("mcp-session-id"):
            self.session = res.headers["mcp-session-id"]
        return res

    def send(self, msg: dict) -> None:
        self._post(msg, 30)

    def request(self, msg: dict, timeout: float) -> dict:
        res = self._post(msg, timeout)
        ctype = res.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for block in res.text.replace("\r\n", "\n").split("\n\n"):
                data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
                if not data:
                    continue
                try:
                    got = json.loads(data)
                except ValueError:
                    continue
                if isinstance(got, dict) and got.get("id") == msg["id"]:
                    return got
            raise McpError("Máy chủ MCP không trả kết quả cho yêu cầu")
        try:
            return res.json()
        except ValueError as exc:
            raise McpError(f"Máy chủ MCP trả dữ liệu lạ: {res.text[:200]}") from exc

    def close(self) -> None:
        try:
            if self.session:
                self.client.delete(self.url, headers={**self.headers, "Mcp-Session-Id": self.session})
        except Exception:
            pass
        self.client.close()


class McpSession:
    """with McpSession(server) as s: s.tools(); s.call(name, args)"""

    def __init__(self, server: dict, timeout: float = 60) -> None:
        self.server, self.timeout, self._id, self.info = server, timeout, 0, {}

    def __enter__(self):
        s = self.server
        if s.get("kind") == "http":
            if not str(s.get("url") or "").startswith(("http://", "https://")):
                raise McpError("Địa chỉ máy chủ MCP phải bắt đầu bằng http:// hoặc https://")
            self.t = _Http(s["url"], dict(s.get("headers") or {}))
        else:
            if not str(s.get("command") or "").strip():
                raise McpError("Chưa nhập lệnh chạy máy chủ MCP")
            self.t = _Stdio(s["command"].strip(), [str(a) for a in s.get("args") or []], dict(s.get("env") or {}),
                            str(s.get("cwd") or ""))
        try:
            res = self._rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                           "clientInfo": {"name": "VideoAgent", "version": "1.0"}}, timeout=max(self.timeout, 90))
            self.info = res.get("serverInfo") or {}
            self.t.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.t.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.t.close()

    def _rpc(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self._id += 1
        got = self.t.request({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}, timeout or self.timeout)
        if got.get("error"):
            err = got["error"]
            raise McpError(f"{method}: {err.get('message') if isinstance(err, dict) else err}")
        return got.get("result") or {}

    def tools(self) -> list[dict]:
        out, cursor = [], None
        for _ in range(20):  # phân trang
            res = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            out += [t for t in res.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return out

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        """→ (chữ kết quả, có lỗi?). Ảnh / file nhị phân chỉ ghi chú, không gửi nội dung."""
        res = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        parts = []
        for c in res.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                parts.append(str(c.get("text") or ""))
            elif c.get("type") == "resource" and isinstance(c.get("resource"), dict):
                r = c["resource"]
                parts.append(str(r.get("text") or f"[tài nguyên {r.get('uri', '')}]"))
            else:
                parts.append(f"[{c.get('type', 'nội dung')} — không hiển thị]")
        if not parts and res.get("structuredContent") is not None:
            parts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
        return "\n".join(parts).strip(), bool(res.get("isError"))
