"""Nghe tin nhắn nhóm Zalo → yêu cầu quảng cáo chờ duyệt (Cài đặt chung → Zalo).

Dùng zca-js (thư viện KHÔNG chính thức, đăng nhập Zalo bằng tài khoản cá nhân — có thể trái điều khoản Zalo / bị khoá
tài khoản; nên dùng tài khoản phụ). Cầu nối Node `assets/zalo_bridge.mjs` CHỈ ĐỌC: đăng nhập QR, liệt kê nhóm, nghe tin
nhóm — không gửi tin, không thao tác gì trên Zalo.

- zca-js cài 1 lần vào DATA_DIR/tools/zalo (cần Node.js ≥ 18 + npm, có internet).
- Phiên đăng nhập (cookie / imei) lưu ở DATA_DIR/zalo/credentials.json — chỉ trên máy, không bao giờ gửi lên giao diện.
- Tin của các nhóm được chọn → hộp tin (DATA_DIR/zalo/inbox.json) → tuỳ chế độ (settings zalo_auto):
  off = chỉ gom tin · rules = tự phân tích bằng luật (không tốn lượt AI) · claude = gom tin mới, gửi Claude phân tích.
  Mọi thao tác quảng cáo vẫn chỉ là ĐỀ XUẤT — chạy khi người dùng duyệt ở Trợ lý quảng cáo.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime

from .paths import ASSETS_DIR, DATA_DIR

log = logging.getLogger(__name__)
ZCA_VERSION = "2.2.0"  # khoá phiên bản (đã đọc API của bản này)
TOOLS_DIR = DATA_DIR / "tools" / "zalo"
ZALO_DIR = DATA_DIR / "zalo"
CREDS_FILE = ZALO_DIR / "credentials.json"
INBOX_FILE = ZALO_DIR / "inbox.json"
MAX_INBOX = 400
CLAUDE_DEBOUNCE = 45  # giây: gom tin mới rồi mới gửi Claude 1 lần
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
AUTO_MODES = {"off": "Chỉ gom tin (tự xem / gửi Claude)", "rules": "Tự phân tích bằng luật → yêu cầu chờ duyệt",
              "claude": "Gom tin mới → tự gửi Claude phân tích"}


class ZaloError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ZaloListener:
    def __init__(self, settings, emit, adreq_factory) -> None:
        self.settings, self._emit, self._adreq = settings, emit, adreq_factory
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._pending: list = []  # tin chờ gửi Claude (chế độ claude)
        self._timer: threading.Timer | None = None
        # last = tin gần nhất của nhóm đang nghe · ignored = số tin của nhóm khác đã bỏ qua (để người dùng biết app vẫn nghe)
        self.st = {"status": "off", "message": "", "qr": "", "account": "", "groups": [], "error": "", "since": "",
                   "last": None, "ignored": 0}

    # ------------------------------------------------------------------ trạng thái cho giao diện
    def state(self) -> dict:
        with self._lock:
            inbox = self._inbox()
            return {**self.st, "enabled": bool(self.settings.get("zalo_listen")),
                    "watched": sorted(self.watched_ids()), "picked": list(self.settings.get("zalo_groups") or []),
                    "group_names": "\n".join(self.names()), "auto": self.settings.get("zalo_auto") or "rules",
                    "show_claude": bool(self.settings.get("zalo_show_claude", True)),
                    "auto_modes": AUTO_MODES, "logged_in": CREDS_FILE.is_file(),
                    "inbox": inbox[-60:][::-1], "new": sum(1 for m in inbox if m.get("status") == "new")}

    def _push(self) -> None:
        self._emit("zalo_status", self.state())

    def _set(self, **kw) -> None:
        with self._lock:
            self.st.update(kw)
        self._push()

    # ------------------------------------------------------------------ cài zca-js + chạy cầu nối
    @staticmethod
    def _node_npm() -> tuple[str, str]:
        node, npm = shutil.which("node"), shutil.which("npm")
        if not node or not npm:
            raise ZaloError("Chưa có Node.js — cài Node.js 18 trở lên (nodejs.org) rồi bật lại")
        return node, npm

    def _install(self, npm: str) -> None:
        pkg = TOOLS_DIR / "node_modules" / "zca-js" / "package.json"
        if pkg.is_file():
            try:
                if json.loads(pkg.read_text("utf-8")).get("version") == ZCA_VERSION:
                    return
            except (OSError, ValueError):
                pass
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        (TOOLS_DIR / "package.json").write_text(json.dumps({"name": "videoagent-zalo", "private": True, "type": "module"}), "utf-8")
        self._set(status="installing", message=f"Đang cài zca-js {ZCA_VERSION} (lần đầu, cần internet)…", error="")
        proc = subprocess.run([npm, "install", f"zca-js@{ZCA_VERSION}", "--no-fund", "--no-audit"], cwd=TOOLS_DIR,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                              creationflags=NO_WINDOW)
        if proc.returncode != 0:
            raise ZaloError("Cài zca-js lỗi: " + (proc.stderr or proc.stdout).strip()[-400:])

    def start(self) -> None:
        """Bật nghe (chạy nền). Đã chạy thì thôi."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            self._stop.clear()
        threading.Thread(target=self._run, daemon=True, name="zalo-listener").start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
                proc.stdin.flush()
                proc.wait(5)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                proc.kill()
        self._set(status="off", message="Đã tắt nghe Zalo", qr="")

    def shutdown(self) -> None:
        """Tắt app: dừng tiến trình Node (không phát sự kiện — cửa sổ có thể đã đóng)."""
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def logout(self) -> None:
        """Đăng xuất: dừng + xoá phiên đăng nhập đã lưu (lần sau phải quét QR lại)."""
        self.stop()
        CREDS_FILE.unlink(missing_ok=True)
        self._set(account="", groups=[], message="Đã đăng xuất Zalo khỏi app")

    def refresh_groups(self) -> None:
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.stdin.write(json.dumps({"cmd": "groups"}) + "\n")
            proc.stdin.flush()

    def _run(self) -> None:
        tries = 0
        while not self._stop.is_set():
            try:
                node, npm = self._node_npm()
                self._install(npm)
                shutil.copy2(ASSETS_DIR / "zalo_bridge.mjs", TOOLS_DIR / "zalo_bridge.mjs")
                ZALO_DIR.mkdir(parents=True, exist_ok=True)
                proc = subprocess.Popen([node, "zalo_bridge.mjs", str(CREDS_FILE)], cwd=TOOLS_DIR, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                        errors="replace", creationflags=NO_WINDOW)
                with self._lock:
                    self._proc = proc
                self._set(status="starting", message="Đang khởi động Zalo…", error="", since=_now())
                for line in proc.stdout:
                    self._on_line(line)
                code = proc.wait()
                err = (proc.stderr.read() or "").strip()[-400:]
            except ZaloError as exc:
                self._set(status="error", message=str(exc), error=str(exc))
                return
            except (OSError, subprocess.SubprocessError) as exc:
                self._set(status="error", message=f"Không chạy được Node: {exc}", error=str(exc))
                return
            if self._stop.is_set():
                return
            tries += 1
            if tries > 5:  # rớt liên tục → dừng hẳn, báo người dùng (không lặp vô hạn)
                self._set(status="error", message="Zalo ngắt kết nối nhiều lần — bật lại ở Cài đặt", error=err or f"exit {code}")
                return
            self._set(status="reconnecting", message=f"Mất kết nối Zalo — thử lại ({tries}/5)…", error=err)
            self._stop.wait(min(60, 5 * tries))

    # ------------------------------------------------------------------ sự kiện từ cầu nối
    def _on_line(self, line: str) -> None:
        try:
            ev = json.loads(line)
        except ValueError:
            return
        kind = ev.get("type")
        if kind == "qr":
            img = str(ev.get("image") or "")
            self._set(status="need_qr", qr=img if img.startswith("data:") else f"data:image/png;base64,{img}",
                      message="Quét mã QR bằng ứng dụng Zalo trên điện thoại (Zalo → Quét QR)")
        elif kind == "status":
            self._set(status=ev.get("status") or "connecting", message=ev.get("message") or "",
                      **({"qr": ""} if ev.get("status") in ("connected", "connecting") else {}))
        elif kind == "login":
            self._set(status="connecting", account=ev.get("name") or "", qr="", message="Đã đăng nhập — đang kết nối…")
        elif kind == "groups":
            self._set(groups=ev.get("groups") or [])
        elif kind == "closed":
            dup = ev.get("code") in (3000, 3003)
            self._set(status="kicked" if dup else "reconnecting",
                      message="Zalo Web đang mở ở nơi khác nên phiên nghe bị ngắt — đóng Zalo Web rồi bật lại" if dup
                      else "Mất kết nối Zalo — đang thử lại…")
        elif kind == "error":
            log.warning("Zalo bridge [%s]: %s", ev.get("stage"), ev.get("message"))
            self._set(error=f"{ev.get('stage')}: {ev.get('message')}")
        elif kind == "message":
            self._on_message(ev)

    # ------------------------------------------------------------------ hộp tin + tạo yêu cầu
    def _inbox(self) -> list:
        try:
            return json.loads(INBOX_FILE.read_text("utf-8")).get("messages", [])
        except (OSError, ValueError, AttributeError):
            return []

    def _save_inbox(self, items: list) -> None:
        ZALO_DIR.mkdir(parents=True, exist_ok=True)
        tmp = INBOX_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"messages": items[-MAX_INBOX:]}, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(INBOX_FILE)

    def _update_msgs(self, ids: set, **kw) -> None:
        with self._lock:
            items = self._inbox()
            for m in items:
                if m["id"] in ids:
                    m.update(kw)
            self._save_inbox(items)

    def names(self) -> list[str]:
        raw = self.settings.get("zalo_group_names") or ""
        return [n.strip() for n in str(raw).replace(";", "\n").split("\n") if n.strip()][:20]

    def watched_ids(self) -> set:
        """Nhóm được nghe = nhóm khớp TÊN đã cài (không phân biệt dấu / hoa thường; gõ phần đầu tên cũng khớp)
        + nhóm tick thêm theo id. Nhóm khác bị bỏ qua hoàn toàn."""
        from .ad_requests import norm

        wanted = [norm(n) for n in self.names()]
        ids = {str(i) for i in self.settings.get("zalo_groups") or []}
        for g in self.st.get("groups") or []:
            gn = norm(g.get("name"))
            if any(w and (gn == w or (len(w) >= 6 and gn.startswith(w))) for w in wanted):
                ids.add(str(g["id"]))
        return ids

    def _on_message(self, ev: dict) -> None:
        names = {g["id"]: g["name"] for g in self.st.get("groups") or []}
        if str(ev.get("group")) not in self.watched_ids():  # chỉ các nhóm khớp tên / được chọn
            with self._lock:
                self.st["ignored"] += 1
            log.info("Zalo: bỏ qua tin nhóm %s (không theo dõi)", names.get(str(ev.get("group")), ev.get("group")))
            return
        ts = int(ev.get("ts") or 0) / 1000 or time.time()
        msg = {"id": uuid.uuid4().hex[:10], "msgId": str(ev.get("msgId") or ""), "group": str(ev["group"]),
               "group_name": names.get(str(ev["group"]), str(ev["group"])), "from": str(ev.get("from") or ""),
               "text": str(ev.get("text") or "")[:8000], "at": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
               "status": "new", "requests": []}
        with self._lock:
            items = self._inbox()
            if msg["msgId"] and any(m.get("msgId") == msg["msgId"] for m in items[-200:]):
                return  # tin trùng (kết nối lại)
            items.append(msg)
            self._save_inbox(items)
            self.st["last"] = {"at": msg["at"], "group": msg["group_name"], "from": msg["from"]}
        log.info("Zalo: nhận tin nhóm %s từ %s", msg["group_name"], msg["from"])
        self._push()
        mode = self.settings.get("zalo_auto") or "rules"
        if mode == "rules":
            threading.Thread(target=self._process_rules, args=([msg],), daemon=True).start()
        elif mode == "claude":
            with self._lock:
                self._pending.append(msg)
                if self._timer:
                    self._timer.cancel()
                self._timer = threading.Timer(CLAUDE_DEBOUNCE, self._flush_claude)
                self._timer.daemon = True
                self._timer.start()

    def _account(self) -> str:
        return self.settings.get("adreq_account") or "__all__"

    def _process_rules(self, msgs: list) -> None:
        """Phân tích bằng luật (không tốn lượt AI): tin có Page / nhóm / link / việc → yêu cầu chờ duyệt."""
        from .ad_requests import AdRequestError
        from .facebook import FacebookError

        for m in msgs:
            text = f"{m['from']}\n{m['text']}" if m["from"] else m["text"]
            try:
                reqs = self._adreq().add(text, "__all__", mode="rules")
            except AdRequestError:
                self._update_msgs({m["id"]}, status="skipped", note="Không phải yêu cầu quảng cáo")
                continue
            except (FacebookError, OSError) as exc:
                self._update_msgs({m["id"]}, status="error", note=str(exc)[:300])
                continue
            for r in reqs:
                self._adreq().tag_origin(r["id"], {"zalo_group": m["group_name"], "zalo_from": m["from"], "zalo_msg": m["id"]})
            self._update_msgs({m["id"]}, status="done", requests=[r["id"] for r in reqs])
            self._emit("adreq_changed", {"source": "zalo", "count": len(reqs)})
        self._push()

    def _flush_claude(self) -> None:
        with self._lock:
            batch, self._pending = self._pending, []
        if batch:
            try:
                self.send_to_claude([m["id"] for m in batch])
            except Exception:  # lỗi đã ghi vào hộp tin (status=error) — không làm chết luồng hẹn giờ
                log.exception("Gửi tin Zalo cho Claude lỗi")

    def send_to_claude(self, ids: list) -> dict:
        """Gửi các tin (theo id hộp tin) cho Claude trong cuộc trò chuyện "Zalo" → yêu cầu chờ duyệt."""
        items = [m for m in self._inbox() if m["id"] in set(ids)]
        if not items:
            raise ZaloError("Không có tin nào để gửi")
        text = "Tin nhắn mới từ nhóm Zalo (phân tích các yêu cầu quảng cáo, đề xuất thao tác):\n\n" + "\n\n".join(
            f"[{m['at'][11:16]} · nhóm {m['group_name']}] {m['from']}:\n{m['text']}" for m in items)
        adreq = self._adreq()
        cid = self.settings.get("zalo_chat_id") or ""
        try:
            adreq.chat_get(cid)
        except Exception:  # cuộc trò chuyện Zalo cũ đã xoá → tạo mới
            chat = adreq.chat_new(self._account())
            chat["title"] = "📥 Tin nhóm Zalo"
            adreq._put_chat(chat)
            cid = chat["id"]
            self.settings.update({"zalo_chat_id": cid})
        self._update_msgs({m["id"] for m in items}, status="sending")
        self._push()
        try:
            res = adreq.chat(cid, text, self._account(), show_browser=bool(self.settings.get("zalo_show_claude", True)),
                             log=lambda msg, level="info": self._emit("adchat_status", {"chat": cid, "text": str(msg), "level": level}))
        except Exception as exc:
            self._update_msgs({m["id"] for m in items}, status="error", note=str(exc)[:300])
            self._push()
            raise
        reqs = res.get("requests") or []
        for r in reqs:
            adreq.tag_origin(r["id"], {"zalo_group": items[0]["group_name"], "zalo_msg": ",".join(m["id"] for m in items)})
        self._update_msgs({m["id"] for m in items}, status="done", requests=[r["id"] for r in reqs])
        self._emit("adreq_changed", {"source": "zalo", "count": len(reqs)})
        self._push()
        return res

    def clear_inbox(self) -> None:
        with self._lock:
            self._save_inbox([])
        self._push()
