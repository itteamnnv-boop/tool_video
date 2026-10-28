"""Trợ lý Canvas: Claude (claude.ai qua trình duyệt đã đăng nhập) làm người ĐIỀU PHỐI + ĐÁNH GIÁ quy trình Canvas.

Mỗi lượt: app gửi ảnh chụp trạng thái Canvas (node, prompt, cấu hình, kết quả, lỗi, nhóm) + (tuỳ chọn) ảnh kết quả / khung
hình video → Claude trả lời + 1 khối JSON {tra_loi, danh_gia, de_xuat}. Đề xuất là thao tác trong danh mục cho phép (sửa
prompt / chữ / cấu hình / model, đặt tên, thêm khối, nối / bỏ nối, chạy) — app kiểm tra từng đề xuất và CHỈ thực hiện khi
người dùng bấm Áp dụng. Không có thao tác xoá; đăng bài vẫn luôn qua bước duyệt của khối Đăng bài.
Cuộc trò chuyện lưu theo từng Canvas (assistant.json) và nối tiếp đúng thread trên claude.ai.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .llm.base import extract_json
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.video_engines import ENGINES as VIDEO_ENGINES
from .util import read_json, write_json

MAX_MESSAGES = 200
MAX_OPS = 8
MAX_IMAGES = 6
OPTION_KEYS = ("engine", "aspect", "count", "duration", "resolution")
OPS = ("set_prompt", "set_text", "set_config", "set_option", "set_title", "add_node", "connect", "disconnect", "run")
RUN_MODES = ("node", "to", "from", "all")
SYSTEM = ("Bạn là trợ lý điều phối và giám khảo cho quy trình tạo nội dung (ảnh, video, bài đăng) trên Canvas của app "
          "VideoAgent. Bạn chỉ đọc dữ liệu được gửi và ĐỀ XUẤT; mọi thay đổi do người dùng bấm áp dụng.")

RULES = """Vai trò của bạn:
1. ĐIỀU PHỐI: hiểu mục tiêu người dùng, đề xuất cách dựng / sửa quy trình (thêm khối, nối dây, viết prompt, chọn model,
   thứ tự chạy) để ra kết quả tốt nhất với ít lượt tạo nhất.
2. ĐÁNH GIÁ: chấm kết quả (ảnh / khung hình video đính kèm, chữ AI viết, bài đăng) theo mục tiêu: đúng sản phẩm, rõ thông
   điệp, chất lượng hình, chữ tiếng Việt đúng dấu, hợp kênh đăng (TikTok / Reels / Facebook). Chỉ ra lỗi cụ thể theo node.

Luôn trả lời bằng tiếng Việt, ngắn gọn. Cuối câu trả lời có ĐÚNG MỘT khối ```json như sau:
{
  "tra_loi": "câu trả lời cho người dùng (markdown đơn giản: - gạch đầu dòng, **đậm**)",
  "danh_gia": null hoặc {"diem": 0-10, "tom_tat": "1-2 câu", "van_de": ["vấn đề cụ thể"],
                         "node": [{"id": "n3", "diem": 0-10, "nhan_xet": "nhận xét ngắn"}]},
  "de_xuat": [ ...tối đa 8 thao tác, [] nếu không cần... ]
}
Các thao tác được phép trong "de_xuat" (mỗi thao tác thêm "ly_do": "vì sao"):
- {"op": "set_prompt", "node": "n3", "prompt": "..."}   node Ảnh / Video: prompt viết trực tiếp; khối AI viết: yêu cầu
- {"op": "set_text", "node": "n1", "text": "..."}       khối Văn bản
- {"op": "set_config", "node": "n5", "config": {"khoá": "giá trị"}}   chỉ khoá có trong danh sách ô của khối đó
- {"op": "set_option", "node": "n3", "key": "engine|aspect|count|duration|resolution", "value": "..."}  giá trị phải có
  trong danh mục model bên dưới
- {"op": "set_title", "node": "n3", "title": "..."}
- {"op": "add_node", "ref": "moi1", "kind": "image|video|wf", "wtype": "(khi kind = wf)", "title": "...", "prompt": "...",
   "from": ["n2"]}   thêm khối, nối từ các khối "from"; "ref" để các thao tác sau dùng thay cho id (VD connect từ "moi1")
- {"op": "connect", "from": "n2", "to": "n5"} / {"op": "disconnect", "from": "n2", "to": "n5"}
- {"op": "run", "mode": "node|to|from|all", "node": "n3"}   chạy (người dùng xác nhận, TỐN lượt model — chỉ đề xuất khi
   đã sửa xong hoặc cần tạo lại)
Quy tắc: KHÔNG đề xuất xoá; không bịa giá / số liệu / thông tin sản phẩm không có trong dữ liệu; prompt Ảnh / Video viết
chi tiết, rõ bố cục / ánh sáng / phong cách; chữ hiển thị trong ảnh giữ tiếng Việt có dấu đúng chính tả. Khối Đăng bài
luôn chờ người dùng duyệt trước khi đăng (trừ khối đã bật tự đăng) — nhắc người dùng kiểm tra trước khi chạy khối đó."""

FIRST = """{rules}

DANH MỤC KHỐI & MODEL:
{catalog}

TRẠNG THÁI CANVAS HIỆN TẠI:
{snapshot}

YÊU CẦU CỦA NGƯỜI DÙNG:
{message}"""

NEXT = """TRẠNG THÁI CANVAS HIỆN TẠI (đã cập nhật):
{snapshot}

YÊU CẦU CỦA NGƯỜI DÙNG:
{message}

(Nhắc lại: trả lời kèm đúng 1 khối ```json {{"tra_loi", "danh_gia", "de_xuat"}} như quy ước; chỉ dùng thao tác được phép.)"""


class AssistantError(ValueError):
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _short(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class _ChatAssistant:
    """Phần chat của trợ lý: hỏi Claude, lọc đề xuất, áp dụng (CanvasAssistant = phần này + AutoPilot, cuối file)."""
    def __init__(self, runner, settings, emit=None) -> None:
        self.runner = runner
        self.settings = settings
        self.emit = emit or (lambda *a, **k: None)
        self._lock = threading.Lock()
        self._busy: set[str] = set()
        self._stopped: set[str] = set()  # bấm Dừng tự điều phối → bỏ các vòng còn lại

    # ------------------------------------------------------------------ lưu trữ
    def _path(self, bid: str) -> Path:
        return self.runner.dir(bid) / "assistant.json"

    def load(self, bid: str) -> dict:
        path = self._path(bid)
        try:
            data = read_json(path) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        data.setdefault("chat_url", "")
        data.setdefault("messages", [])
        data["busy"] = bid in self._busy
        return data

    def _save(self, bid: str, data: dict) -> dict:
        data = {k: v for k, v in data.items() if k != "busy"}
        data["messages"] = data["messages"][-MAX_MESSAGES:]
        write_json(self._path(bid), data)
        return {**data, "busy": bid in self._busy}

    def clear(self, bid: str) -> dict:
        """Cuộc trò chuyện mới (lượt sau mở thread mới trên claude.ai, gửi lại quy tắc + danh mục)."""
        if bid in self._busy:
            raise AssistantError("Trợ lý đang trả lời — chờ xong rồi mới bắt đầu cuộc trò chuyện mới")
        return self._save(bid, {"chat_url": "", "messages": []})

    # ------------------------------------------------------------------ dữ liệu gửi Claude
    @staticmethod
    def catalog() -> str:
        from .canvas import wf_types

        lines = ["Khối (kind = wf, wtype):"]
        for key, spec in wf_types().items():
            ins = ", ".join(f"{p['key']}:{p['type']}" for p in spec["inputs"]) or "—"
            outs = ", ".join(p["type"] for p in spec["outputs"]) or "—"
            fields = []
            for f in spec["fields"]:
                opts = [str(o.get("value")) for o in f.get("options") or []][:8]
                fields.append(f"{f['key']}" + (f"({'/'.join(opts)})" if opts else f"[{f.get('type', '')}]"))
            lines.append(f"- {key}: {spec['name']} — vào {ins} → ra {outs} — ô: {', '.join(fields) or '—'}")
        lines.append("Node Ảnh (kind = image) — engine: " + "; ".join(
            f"{k} ({v['name']}; aspect {'/'.join(v['aspects'])}; count {'/'.join(map(str, v['counts']))})"
            for k, v in IMAGE_ENGINES.items()))
        lines.append("Node Video (kind = video) — engine: " + "; ".join(
            f"{k} ({v['name']}; duration {'/'.join(map(str, v['durations']))}; resolution {'/'.join(map(str, v['resolutions']))}; "
            f"aspect {'/'.join(v['aspects'])})" for k, v in VIDEO_ENGINES.items()))
        lines.append("Ảnh / Video nhận chữ từ khối nối vào làm prompt (prompt_src: '' = ghép chữ nối vào + prompt viết thêm, "
                     "'own' = chỉ prompt viết, id khối = chỉ chữ khối đó). Ảnh tải lên (kind = upload) chỉ do người dùng chọn.")
        return "\n".join(lines)

    def snapshot(self, board: dict) -> str:
        from .canvas import wf_types

        r = self.runner
        bid = board["id"]
        specs = wf_types()
        lines = [f"Canvas “{board['name']}” — {len(board['nodes'])} node"]
        for n in board["nodes"]:
            kind = n["kind"]
            name = specs[n["wtype"]]["name"] if kind == "wf" and n.get("wtype") in specs else \
                {"image": "Ảnh", "video": "Video", "upload": "Ảnh tải lên"}.get(kind, kind)
            head = [f"- {n['id']} · {name}" + (f" “{_short(n.get('title'), 60)}”" if n.get("title") else ""),
                    f"trạng thái: {n.get('status') or 'idle'}"]
            if kind in ("image", "video"):
                head.append(" ".join(f"{k}={n.get(k)}" for k in OPTION_KEYS if n.get(k) not in (None, "")))
                if n.get("prompt_src"):
                    head.append(f"prompt_src={n['prompt_src']}")
            if n.get("inputs"):
                head.append("nối vào: " + ", ".join(n["inputs"]))
            if n.get("ask"):
                head.append("❓hỏi khi chạy")
            if n.get("auto_post"):
                head.append("🚀tự đăng")
            lines.append(" · ".join(x for x in head if x))
            if kind in ("image", "video") and (n.get("prompt") or "").strip():
                lines.append(f"    prompt: {_short(n['prompt'], 700)}")
            if kind == "video" and (n.get("dialogue") or n.get("dialogue_src")):
                lines.append(f"    lời thoại: {_short(n.get('dialogue'), 300)}" + (f" (lấy từ {n['dialogue_src']})" if n.get("dialogue_src") else ""))
            if kind == "wf":
                cfg = {k: v for k, v in (n.get("config") or {}).items() if v not in ("", None, [], {})}
                if cfg:
                    lines.append("    cấu hình: " + _short(json.dumps(cfg, ensure_ascii=False), 700))
            outs = r._outputs(bid, n)
            files = n.get("files") or []
            if kind in ("image", "upload", "video") and files:
                lines.append(f"    kết quả: {len(files)} {'video' if kind == 'video' else 'ảnh'}" +
                             (f" (đang chọn số {int(n.get('pick') or 0) + 1})" if len(files) > 1 else ""))
            if kind == "wf" and outs.get("text") and n.get("wtype") != "input_text":
                lines.append(f"    chữ kết quả: {_short(outs['text'], 900)}")
            if kind == "wf" and outs.get("video"):
                lines.append("    kết quả: 1 video")
            post = (n.get("out") or {}).get("post") or {}
            if post.get("url"):
                lines.append(f"    đã đăng: {post.get('page', '')} · {post['url']}")
            if n.get("status") == "error" and n.get("error"):
                lines.append(f"    lỗi: {_short(n['error'], 300)}")
        for g in board.get("groups") or []:
            inside = [n["id"] for n in board["nodes"]
                      if g["x"] <= n["x"] < g["x"] + g["w"] and g["y"] <= n["y"] < g["y"] + g["h"]]
            lines.append(f"Nhóm “{_short(g.get('title'), 60)}”: {', '.join(inside) or 'trống'}"
                         + (f" — ghi chú: {_short(g.get('note'), 400)}" if g.get("note") else ""))
        runs = board.get("runs") or []
        if runs:
            last = runs[-1]
            lines.append(f"Lần chạy gần nhất: {last.get('label', '')} — {last.get('status', '')}")
        return "\n".join(lines)

    def result_images(self, board: dict) -> list[Path]:
        """Ảnh kết quả (ảnh đang chọn của node Ảnh / Tải lên) + 1 khung hình giữa mỗi video → bản thu nhỏ để gửi Claude."""
        from PIL import Image

        bid = board["id"]
        folder = self.runner.dir(bid) / "assistant"
        folder.mkdir(exist_ok=True)
        out = []
        for n in reversed(board["nodes"]):  # node mới nhất trước
            if len(out) >= MAX_IMAGES:
                break
            files = n.get("files") or []
            if not files or n["kind"] not in ("image", "upload", "video"):
                continue
            src = Path(self.runner._abs(bid, files[min(int(n.get("pick") or 0), len(files) - 1)]))
            dest = folder / f"{n['id']}.jpg"
            try:
                if n["kind"] == "video":
                    dur = ffmpeg.media_duration(src)
                    ffmpeg.run(["-ss", f"{max(0.0, dur / 2):.2f}", "-i", src, "-frames:v", "1", "-vf", "scale='min(1024,iw)':-2", dest])
                else:
                    with Image.open(src) as im:
                        im = im.convert("RGB")
                        im.thumbnail((1024, 1024))
                        im.save(dest, "JPEG", quality=85)
            except Exception:  # file hỏng / định dạng lạ → bỏ qua ảnh đó
                continue
            out.append(dest)
        return list(reversed(out))

    # ------------------------------------------------------------------ lọc đề xuất
    def clean_ops(self, board: dict, ops) -> tuple[list, int]:
        """Giữ đề xuất hợp lệ (đúng loại, node có thật, giá trị trong danh mục); trả (đề xuất, số bị bỏ)."""
        from .canvas import wf_types

        specs = wf_types()
        nodes = {n["id"]: n for n in board["nodes"]}
        ops = ops if isinstance(ops, list) else []
        # khối mới khai báo ở bất kỳ đâu trong danh sách (Claude hay đặt "nối từ moi1" trước "thêm khối moi1")
        refs: dict[str, str] = {str(o["ref"])[:20]: str(o["ref"])[:20] for o in ops
                                if isinstance(o, dict) and o.get("op") == "add_node" and o.get("ref")}
        kept, dropped = [], 0
        for raw in ops:
            if len(kept) >= MAX_OPS:
                dropped += 1
                continue
            op = self._clean_op(raw, nodes, refs, specs)
            if op is None:
                dropped += 1
                continue
            kept.append(op)
        return kept, dropped

    def _clean_op(self, raw, nodes: dict, refs: dict, specs: dict):
        if not isinstance(raw, dict) or raw.get("op") not in OPS:
            return None
        kind = raw["op"]
        why = _short(raw.get("ly_do"), 300)
        known = lambda x: str(x or "") in nodes or str(x or "") in refs  # noqa: E731
        label = lambda x: (f"{x} “{_short(nodes[x].get('title'), 40)}”" if x in nodes and nodes[x].get("title")  # noqa: E731
                           else f"{x} (khối mới)" if x in refs else str(x))
        nid = str(raw.get("node") or "")
        if kind in ("set_prompt", "set_text", "set_config", "set_option", "set_title") and nid not in nodes:
            return None
        node = nodes.get(nid)
        if kind == "set_prompt":
            text = str(raw.get("prompt") or "").strip()
            if not text or not (node["kind"] in ("image", "video") or (node["kind"] == "wf" and any(
                    f["key"] == "prompt" for f in specs.get(node.get("wtype"), {}).get("fields", [])))):
                return None
            return {"op": kind, "node": nid, "prompt": text[:4000], "ly_do": why, "label": f"Sửa prompt {label(nid)}"}
        if kind == "set_text":
            text = str(raw.get("text") or "").strip()
            if not text or node.get("wtype") != "input_text":
                return None
            return {"op": kind, "node": nid, "text": text[:8000], "ly_do": why, "label": f"Sửa chữ khối {label(nid)}"}
        if kind == "set_config":
            if node["kind"] != "wf" or not isinstance(raw.get("config"), dict):
                return None
            keys = {f["key"] for f in specs.get(node.get("wtype"), {}).get("fields", [])}
            cfg = {k: v for k, v in raw["config"].items() if k in keys and k not in ("page_id", "account_id")}
            if not cfg:  # Fanpage / tài khoản quảng cáo: người dùng tự chọn
                return None
            return {"op": kind, "node": nid, "config": cfg, "ly_do": why,
                    "label": f"Đổi cấu hình {label(nid)}: " + ", ".join(cfg)}
        if kind == "set_option":
            key, value = str(raw.get("key") or ""), raw.get("value")
            if node["kind"] not in ("image", "video") or key not in OPTION_KEYS or not self._option_ok(node, key, value):
                return None
            return {"op": kind, "node": nid, "key": key, "value": value, "ly_do": why,
                    "label": f"Đổi {key} của {label(nid)} → {value}"}
        if kind == "set_title":
            title = _short(raw.get("title"), 60)
            return {"op": kind, "node": nid, "title": title, "ly_do": why, "label": f"Đặt tên {nid}: “{title}”"} if title else None
        if kind == "add_node":
            nk, wtype = str(raw.get("kind") or ""), str(raw.get("wtype") or "")
            if nk not in ("image", "video", "wf") or (nk == "wf" and wtype not in specs):
                return None
            src = [str(x) for x in raw.get("from") or [] if known(x)][:5]
            ref = str(raw.get("ref") or f"moi{len(refs) + 1}")[:20]
            refs[ref] = ref
            name = specs[wtype]["name"] if nk == "wf" else {"image": "Ảnh", "video": "Video"}[nk]
            return {"op": kind, "ref": ref, "kind": nk, "wtype": wtype if nk == "wf" else "",
                    "title": _short(raw.get("title"), 60), "prompt": str(raw.get("prompt") or "").strip()[:4000],
                    "from": src, "ly_do": why,
                    "label": f"Thêm khối {name}" + (f" “{_short(raw.get('title'), 40)}”" if raw.get("title") else "")
                             + (f" nối từ {', '.join(src)}" if src else "")}
        if kind in ("connect", "disconnect"):
            a, b = str(raw.get("from") or ""), str(raw.get("to") or "")
            if not (known(a) and known(b)) or a == b:
                return None
            return {"op": kind, "from": a, "to": b, "ly_do": why,
                    "label": f"{'Nối' if kind == 'connect' else 'Bỏ nối'} {label(a)} → {label(b)}"}
        if kind == "run":
            mode = str(raw.get("mode") or "all")
            if mode not in RUN_MODES or (mode != "all" and nid not in nodes):
                return None
            what = {"all": "toàn bộ quy trình", "node": f"node {label(nid)}", "to": f"đến {label(nid)}",
                    "from": f"từ {label(nid)}"}[mode]
            return {"op": kind, "mode": mode, "node": nid if mode != "all" else "", "ly_do": why, "label": f"▶ Chạy {what}"}
        return None

    @staticmethod
    def _option_ok(node: dict, key: str, value) -> bool:
        engines = IMAGE_ENGINES if node["kind"] == "image" else VIDEO_ENGINES
        if key == "engine":
            return value in engines
        spec = engines.get(node.get("engine")) or {}
        allowed = {"aspect": spec.get("aspects"), "count": spec.get("counts"), "duration": spec.get("durations"),
                   "resolution": spec.get("resolutions")}.get(key) or []
        return str(value) in {str(x) for x in allowed}

    # ------------------------------------------------------------------ hỏi Claude
    def chat(self, bid: str, message: str, *, attach: bool = True, show_browser: bool = False, log=None) -> dict:
        from .studio import ask_model

        message = str(message or "").strip()
        if not message:
            raise AssistantError("Nhập yêu cầu cho trợ lý")
        with self._lock:
            if bid in self._busy:
                raise AssistantError("Trợ lý đang trả lời yêu cầu trước — chờ xong đã")
            self._busy.add(bid)
        log = log or (lambda *a, **k: None)
        try:
            board = self.runner.load(bid)
            chat = self.load(bid)
            images = self.result_images(board) if attach else []
            chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "user", "text": message[:8000], "at": now(),
                                     "images": len(images)})
            self._save(bid, chat)
            snap = self.snapshot(board)
            if chat.get("chat_url"):
                prompt = NEXT.format(snapshot=snap, message=message[:8000])
            else:  # lượt đầu (hoặc thread cũ mất): gửi quy tắc + danh mục
                history = "\n".join(f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {_short(m.get('text'), 500)}"
                                    for m in chat["messages"][:-1][-8:])
                prompt = FIRST.format(rules=RULES, catalog=self.catalog(), snapshot=snap, message=message[:8000])
                if history:
                    prompt = f"Tóm tắt trò chuyện trước:\n{history}\n\n{prompt}"
            if images:
                prompt += f"\n\n(Đính kèm {len(images)} ảnh kết quả / khung hình video, theo thứ tự node trên Canvas.)"
            options = {"model": "claude_browser", "show_browser": bool(show_browser), "timeout": 900,
                       "chat_url": chat.get("chat_url", "")}
            log(f"Đang hỏi Claude{f' (kèm {len(images)} ảnh)' if images else ''}…")
            try:
                raw = ask_model(self.settings, options, prompt, complete=lambda t: _parse(t) is not None,
                                what="trả lời (trợ lý Canvas)", log=log, system=SYSTEM, images=images or None)
            except Exception as exc:
                chat = self.load(bid)
                chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "assistant", "text": "",
                                         "error": _short(exc, 500), "at": now()})
                self._save(bid, chat)
                raise
            data = _parse(raw) or {}
            ops, dropped = self.clean_ops(self.runner.load(bid), data.get("de_xuat"))
            chat = self.load(bid)
            if options.get("_last_url"):
                chat["chat_url"] = options["_last_url"]
            text = str(data.get("tra_loi") or "").strip() or _strip_json(raw)
            chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "assistant", "text": text[:8000],
                                     "eval": _clean_eval(data.get("danh_gia")), "ops": ops, "refs": {},
                                     "dropped": dropped, "at": now()})
            return self._save(bid, chat)
        finally:
            self._busy.discard(bid)

    # ------------------------------------------------------------------ áp dụng 1 đề xuất
    def apply(self, bid: str, mid: str, idx: int) -> dict:
        from .canvas import CanvasError

        chat = self.load(bid)
        msg = next((m for m in chat["messages"] if m.get("id") == mid and m.get("role") == "assistant"), None)
        if msg is None or not (0 <= int(idx) < len(msg.get("ops") or [])):
            raise AssistantError("Không tìm thấy đề xuất")
        op = msg["ops"][int(idx)]
        if op.get("applied"):
            raise AssistantError("Đề xuất này đã áp dụng")
        if op["op"] == "run":
            raise AssistantError("Đề xuất chạy được thực hiện qua nút ▶ (có hộp xác nhận)")
        refs = msg.setdefault("refs", {})
        r = self.runner

        def real(x):
            x = str(x or "")
            if x in refs:
                return refs[x]
            if any(o.get("op") == "add_node" and o.get("ref") == x for o in msg["ops"]):
                raise AssistantError(f"Áp dụng đề xuất “thêm khối {x}” trước")
            return x

        board = r.load(bid)
        try:
            if op["op"] == "set_prompt":
                node = r._node(board, real(op["node"]))
                if node["kind"] == "wf":
                    r.update_nodes(bid, [{"id": node["id"], "config": {"prompt": op["prompt"]}}])
                else:  # prompt đang lấy từ 1 khối nối vào → chuyển sang dùng prompt trợ lý viết
                    src = r._prompt_src(node)
                    patch = {"id": node["id"], "prompt": op["prompt"], **({"prompt_src": "own"} if src not in ("", "own") else {})}
                    r.update_nodes(bid, [patch])
                applied = node["id"]
            elif op["op"] == "set_text":
                r.update_nodes(bid, [{"id": real(op["node"]), "config": {"text": op["text"]}}])
                applied = real(op["node"])
            elif op["op"] == "set_config":
                r.update_nodes(bid, [{"id": real(op["node"]), "config": op["config"]}])
                applied = real(op["node"])
            elif op["op"] == "set_option":
                r.update_nodes(bid, [{"id": real(op["node"]), op["key"]: op["value"]}])
                applied = real(op["node"])
            elif op["op"] == "set_title":
                r.update_nodes(bid, [{"id": real(op["node"]), "title": op["title"]}])
                applied = real(op["node"])
            elif op["op"] == "add_node":
                src = [real(x) for x in op.get("from") or []]
                x, y = self._spot(board, src)
                res = r.add_node(bid, op["kind"], x, y, src, op.get("prompt", "") if op["kind"] != "wf" else "", op.get("wtype", ""))
                nid = res["node"]["id"]
                patch = {"id": nid, **({"title": op["title"]} if op.get("title") else {})}
                if op["kind"] == "wf" and op.get("prompt"):
                    patch["config"] = {"text" if op.get("wtype") == "input_text" else "prompt": op["prompt"]}
                if len(patch) > 1:
                    r.update_nodes(bid, [patch])
                refs[op["ref"]] = nid
                applied = nid
            elif op["op"] in ("connect", "disconnect"):
                r.connect(bid, real(op["from"]), real(op["to"]), op["op"] == "connect")
                applied = True
            else:
                raise AssistantError("Thao tác không hỗ trợ")
        except CanvasError as exc:
            raise AssistantError(str(exc)) from exc
        chat = self.load(bid)
        for m in chat["messages"]:
            if m.get("id") == mid:
                m["ops"][int(idx)]["applied"] = applied
                m["refs"] = refs
        return {"chat": self._save(bid, chat), "board": r.public(r.load(bid)), "node": applied if isinstance(applied, str) else ""}

    @staticmethod
    def _size(n: dict) -> tuple[float, float]:
        """Cỡ ước lượng của node trên Canvas (kèm ô prompt bên dưới khi chọn) — để khối mới không đè lên."""
        if n["kind"] == "wf":
            return 300, 360
        w = float(n.get("w") or 0)
        try:
            a, b = (float(x) for x in str(n.get("aspect") or "9:16").split(":"))
            ratio = b / a
        except (ValueError, ZeroDivisionError):
            ratio = 16 / 9
        w = w or (340 if ratio < 1 else 230)
        return w, w * ratio + 60

    def _spot(self, board: dict, src: list) -> tuple[float, float]:
        """Chỗ đặt khối mới: bên phải khối nguồn xa nhất (hoặc bên phải toàn bộ Canvas), dịch xuống tới chỗ trống."""
        nodes = {n["id"]: n for n in board["nodes"]}
        base = [nodes[s] for s in src if s in nodes]
        if base:
            x, y = max(n["x"] + self._size(n)[0] for n in base) + 140, min(n["y"] for n in base)
        else:
            x = max((n["x"] + self._size(n)[0] for n in board["nodes"]), default=0) + 140
            y = min((n["y"] for n in board["nodes"]), default=0)
        W, H, gap = 300, 360, 40

        def hit(px, py):
            return any(px < n["x"] + self._size(n)[0] + gap and px + W + gap > n["x"]
                       and py < n["y"] + self._size(n)[1] + gap and py + H + gap > n["y"] for n in board["nodes"])

        for _ in range(60):
            if not hit(x, y):
                break
            y += 80
        return x, y


AUTO_DEFAULT = {"on": False, "criteria": "", "pass_score": 8.0, "rounds": 2, "attach": True}
AUTO_ACTIVE = ("reviewing", "reworking")
MAX_REWORK = 4
REWORK_WF = ("ai_text", "content_post", "post_video", "concat_video", "studio_video", "storyboard_video", "whiteboard_video")

REVIEW = """Bạn đang TỰ ĐIỀU PHỐI quy trình Canvas này. Quy trình vừa chạy xong: “{label}” — {status}.
Đây là lần chấm sau {done} vòng làm lại (tối đa {rounds} vòng làm lại).

TIÊU CHÍ ĐẠT (người dùng đặt):
{criteria}
Điểm đạt: từ {pass_score}/10.

Việc của bạn:
1. Chấm KẾT QUẢ hiện tại theo đúng tiêu chí trên (xem ảnh / khung hình video đính kèm nếu có, chữ kết quả trong trạng thái).
2. Khối nào chưa đạt → GIAO VIỆC LÀM LẠI cho đúng khối gây ra lỗi: viết yêu cầu cụ thể (sửa gì, giữ gì) và nếu cần thì prompt
   mới đầy đủ / cấu hình mới. Lỗi do khối viết prompt / viết chữ phía trước thì giao cho khối phía trước đó.
   Chỉ giao cho: node Ảnh, node Video, khối {wf}. KHÔNG giao cho khối Đăng bài / Lên lịch / Quảng cáo / Văn bản / Ảnh tải lên.
   Tối đa {max} khối. Đạt rồi thì "lam_lai": [].
3. Không bịa thông tin sản phẩm / giá / số liệu không có trong dữ liệu.

Trả về câu trả lời ngắn + ĐÚNG MỘT khối ```json:
{{"tra_loi": "nhận xét ngắn cho người dùng", "dat": true hoặc false, "diem": 0-10, "tom_tat": "1-2 câu",
  "van_de": ["vấn đề cụ thể"], "node": [{{"id": "n3", "dat": true hoặc false, "diem": 0-10, "nhan_xet": "..."}}],
  "lam_lai": [{{"node": "n3", "yeu_cau": "giao việc cụ thể", "prompt": "prompt mới đầy đủ (tuỳ chọn)",
               "config": {{"khoá": "giá trị"}} }}]}}
{catalog}
TRẠNG THÁI CANVAS SAU LẦN CHẠY:
{snapshot}"""


def _parse_review(text: str):
    try:
        data = extract_json(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and ("dat" in data or "lam_lai" in data) else None


def _auto_clean(cfg: dict, cur: dict) -> dict:
    out = {**AUTO_DEFAULT, **(cur or {})}
    if "on" in cfg:
        out["on"] = bool(cfg["on"])
    if "criteria" in cfg:
        out["criteria"] = str(cfg["criteria"] or "").strip()[:3000]
    if "pass_score" in cfg:
        try:
            out["pass_score"] = max(5.0, min(10.0, round(float(cfg["pass_score"]), 1)))
        except (TypeError, ValueError):
            pass
    if "rounds" in cfg:
        try:
            out["rounds"] = max(1, min(3, int(cfg["rounds"])))
        except (TypeError, ValueError):
            pass
    if "attach" in cfg:
        out["attach"] = bool(cfg["attach"])
    return out


class AutoPilot:
    """Tự điều phối (mixin của CanvasAssistant): chạy quy trình xong → Claude chấm theo tiêu chí → khối chưa đạt được giao
    yêu cầu (sửa prompt / cấu hình) và chạy lại ngay (chỉ khối đó + phía sau, KHÔNG khối đăng / quảng cáo) → chấm lại…
    tới khi đạt hoặc hết số vòng. Mỗi vòng ghi vào khung chat của trợ lý."""

    def set_auto(self, bid: str, cfg: dict) -> dict:
        chat = self.load(bid)
        auto = _auto_clean(cfg or {}, chat.get("auto"))
        if auto["on"] and not auto["criteria"]:
            raise AssistantError("Nhập tiêu chí đạt trước khi bật tự điều phối")
        chat["auto"] = auto
        state = chat.get("auto_state") or {}
        if not auto["on"] and state.get("status") in AUTO_ACTIVE:
            chat["auto_state"] = {**state, "status": "stopped", "at": now()}
        if auto["on"]:
            self._stopped.discard(bid)
        return self._save(bid, chat)

    def stop_auto(self, bid: str) -> dict:
        """Dừng vòng đang chạy: bỏ chấm / làm lại tiếp theo; lần chạy làm lại đang chạy thì dừng luôn."""
        self._stopped.add(bid)
        board = self.runner.load(bid)
        last = (board.get("runs") or [{}])[-1]
        if last.get("origin") == "autopilot" and last.get("status") == "running":
            self.runner.cancel_flow(bid)
        chat = self.load(bid)
        chat["auto_state"] = {**(chat.get("auto_state") or {}), "status": "stopped", "at": now()}
        out = self._save(bid, chat)
        self._notify(bid, "Đã dừng tự điều phối", "warn")
        return out

    def _set_state(self, bid: str, **fields) -> None:
        chat = self.load(bid)
        chat["auto_state"] = {**(chat.get("auto_state") or {}), **fields, "at": now()}
        self._save(bid, chat)

    def _notify(self, bid: str, text: str, level: str = "info", refresh: bool = True) -> None:
        self.emit("canvas_assist", {"board": bid, "text": text, "level": level, "refresh": refresh})

    def after_run(self, bid: str, rec: dict) -> None:
        """Hook khi chạy quy trình xong (gọi từ luồng chạy) → chấm ở luồng riêng."""
        chat = self.load(bid)
        auto = chat.get("auto") or {}
        if not auto.get("on") or rec.get("status") == "cancelled":
            return
        if rec.get("origin") == "autopilot":
            if bid in self._stopped:
                return
            done = int(rec.get("round") or 0)
        else:  # lần chạy do người dùng bấm → bắt đầu chuỗi chấm mới
            self._stopped.discard(bid)
            done = 0
        self._set_state(bid, status="reviewing", round=done, run=rec.get("id", ""))
        self._notify(bid, f"🤖 Quy trình chạy xong — Claude đang chấm theo tiêu chí{f' (sau vòng làm lại {done})' if done else ''}…")
        threading.Thread(target=self._review_safe, args=(bid, rec, done), daemon=True, name=f"canvas-auto-{bid}").start()

    def _review_safe(self, bid: str, rec: dict, done: int) -> None:
        try:
            self._review(bid, rec, done)
        except Exception as exc:  # noqa: BLE001 — luồng nền: ghi lỗi vào chat, không làm sập app
            chat = self.load(bid)
            chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "assistant", "text": "",
                                     "error": f"Tự điều phối lỗi: {_short(exc, 400)}", "at": now(), "auto": {"round": done}})
            chat["auto_state"] = {**(chat.get("auto_state") or {}), "status": "failed", "at": now()}
            self._save(bid, chat)
            self._notify(bid, f"Tự điều phối lỗi: {_short(exc, 200)}", "error")

    def _review(self, bid: str, rec: dict, done: int) -> None:
        import time

        from .studio import ask_model

        for _ in range(900):  # bạn đang hỏi trợ lý dở → chờ lượt đó xong (tối đa 15 phút)
            with self._lock:
                if bid not in self._busy:
                    self._busy.add(bid)
                    break
            time.sleep(1)
        else:
            raise AssistantError("Trợ lý bận quá lâu — bỏ lượt chấm này")
        try:
            chat = self.load(bid)
            auto = chat["auto"]
            board = self.runner.load(bid)
            images = self.result_images(board) if auto.get("attach", True) else []
            prompt = REVIEW.format(label=rec.get("label", ""), status=rec.get("status", ""), done=done, rounds=auto["rounds"],
                                   criteria=auto["criteria"], pass_score=auto["pass_score"], wf=", ".join(REWORK_WF),
                                   max=MAX_REWORK, snapshot=self.snapshot(board),
                                   catalog="" if chat.get("chat_url") else f"\nDANH MỤC KHỐI & MODEL:\n{self.catalog()}\n")
            if images:
                prompt += f"\n\n(Đính kèm {len(images)} ảnh kết quả / khung hình video, theo thứ tự node trên Canvas.)"
            options = {"model": "claude_browser", "show_browser": False, "timeout": 900, "chat_url": chat.get("chat_url", "")}
            chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "user", "at": now(), "images": len(images),
                                     "text": f"🤖 Tự chấm sau “{rec.get('label', '')}” theo tiêu chí: {_short(auto['criteria'], 300)}",
                                     "auto": {"round": done}})
            self._save(bid, chat)
            self._notify(bid, f"Đang hỏi Claude chấm kết quả{f' (kèm {len(images)} ảnh)' if images else ''}…", refresh=True)
            raw = ask_model(self.settings, options, prompt, complete=lambda t: _parse_review(t) is not None,
                            what="chấm kết quả (tự điều phối)", log=lambda m, *a, **k: self._notify(bid, str(m), refresh=False),
                            system=SYSTEM, images=images or None)
        finally:
            self._busy.discard(bid)
        data = _parse_review(raw) or {}
        ev = _clean_eval({**data, "node": data.get("node")})
        try:
            score = float(data.get("diem"))
        except (TypeError, ValueError):
            score = None
        passed = bool(data.get("dat")) or (score is not None and score >= float(auto["pass_score"]))
        board = self.runner.load(bid)
        items = [] if passed else self._clean_rework(board, data.get("lam_lai"))
        chat = self.load(bid)
        if options.get("_last_url"):
            chat["chat_url"] = options["_last_url"]
        msg = {"id": uuid.uuid4().hex[:8], "role": "assistant", "at": now(),
               "text": str(data.get("tra_loi") or "").strip()[:8000] or _strip_json(raw), "eval": ev, "ops": [],
               "auto": {"round": done, "passed": passed, "score": score, "rework": []}}
        if bid in self._stopped:
            msg["auto"]["note"] = "Đã dừng tự điều phối — không giao làm lại"
            chat["messages"].append(msg)
            chat["auto_state"] = {**chat.get("auto_state", {}), "status": "stopped", "at": now()}
            self._save(bid, chat)
            return self._notify(bid, "Đã dừng tự điều phối")
        if passed:
            chat["messages"].append(msg)
            chat["auto_state"] = {**chat.get("auto_state", {}), "status": "passed", "round": done, "at": now()}
            self._save(bid, chat)
            return self._notify(bid, f"✓ Kết quả ĐẠT tiêu chí{f' sau {done} vòng làm lại' if done else ''}"
                                     + (f" — {score:g}/10" if score is not None else ""), "ok")
        if done >= int(auto["rounds"]) or not items:
            msg["auto"]["note"] = (f"Đã làm lại {done} vòng (tối đa) mà vẫn chưa đạt — cần bạn xem lại" if items
                                   else "Chưa đạt nhưng Claude không giao được khối nào làm lại — cần bạn xem lại")
            chat["messages"].append(msg)
            chat["auto_state"] = {**chat.get("auto_state", {}), "status": "failed", "round": done, "at": now()}
            self._save(bid, chat)
            return self._notify(bid, "✗ " + msg["auto"]["note"], "warn")
        # giao việc làm lại: sửa prompt / cấu hình từng khối rồi chạy lại các khối đó (+ phía sau, trừ khối đăng)
        for it in items:
            self._apply_rework(board, it, done + 1)
        msg["auto"]["rework"] = [{"node": it["node"], "yeu_cau": it["yeu_cau"], "label": it["label"]} for it in items]
        chat["messages"].append(msg)
        chat["auto_state"] = {**chat.get("auto_state", {}), "status": "reworking", "round": done + 1, "at": now()}
        self._save(bid, chat)
        targets = [it["node"] for it in items]
        try:
            self.runner.run_flow(bid, "set", targets=targets, origin="autopilot", round_no=done + 1,
                                 label=f"🤖 Làm lại vòng {done + 1}: {', '.join(targets)}")
        except Exception as exc:  # noqa: BLE001 — VD còn lỗi cấu hình → báo, dừng chuỗi
            chat = self.load(bid)
            chat["messages"].append({"id": uuid.uuid4().hex[:8], "role": "assistant", "text": "", "at": now(),
                                     "error": f"Không chạy lại được: {_short(exc, 400)}", "auto": {"round": done + 1}})
            chat["auto_state"] = {**chat.get("auto_state", {}), "status": "failed", "at": now()}
            self._save(bid, chat)
            return self._notify(bid, f"Không chạy lại được: {_short(exc, 200)}", "error")
        self._notify(bid, f"🔁 Claude giao làm lại vòng {done + 1}: {', '.join(targets)}")

    def _clean_rework(self, board: dict, items) -> list:
        from .canvas import wf_types

        specs = wf_types()
        nodes = {n["id"]: n for n in board["nodes"]}
        out, seen = [], set()
        for it in items if isinstance(items, list) else []:
            if len(out) >= MAX_REWORK or not isinstance(it, dict):
                continue
            nid = str(it.get("node") or "")
            n = nodes.get(nid)
            if n is None or nid in seen or not (n["kind"] in ("image", "video") or (n["kind"] == "wf" and n.get("wtype") in REWORK_WF)):
                continue
            req = _short(it.get("yeu_cau"), 800)
            prompt = str(it.get("prompt") or "").strip()[:4000]
            keys = {f["key"] for f in specs.get(n.get("wtype"), {}).get("fields", [])} if n["kind"] == "wf" else set()
            cfg = {k: v for k, v in (it.get("config") or {}).items() if k in keys and k not in ("page_id", "account_id")} \
                if isinstance(it.get("config"), dict) else {}
            if not (req or prompt or cfg):
                continue
            seen.add(nid)
            name = specs[n["wtype"]]["name"] if n["kind"] == "wf" else {"image": "Ảnh", "video": "Video"}[n["kind"]]
            out.append({"node": nid, "yeu_cau": req, "prompt": prompt, "config": cfg,
                        "label": f"{nid} · {n.get('title') or name}"})
        return out

    def _apply_rework(self, board: dict, it: dict, round_no: int) -> None:
        r = self.runner
        n = r._node(board, it["node"])
        note = f"Yêu cầu sửa (vòng {round_no}): {it['yeu_cau']}" if it["yeu_cau"] else ""
        if n["kind"] in ("image", "video"):
            own = (n.get("prompt") or "").strip()
            prompt = it["prompt"] or "\n\n".join(x for x in (own, note) if x)
            patch = {"id": n["id"], "prompt": prompt}
            if r._prompt_src(n) not in ("", "own"):  # đang lấy prompt từ 1 khối → ghép chữ khối đó + yêu cầu sửa
                patch["prompt_src"] = ""
                if not it["prompt"]:
                    patch["prompt"] = note
            r.update_nodes(board["id"], [patch])
            return
        from .canvas import wf_types

        fields = wf_types()[n["wtype"]]["fields"]
        key = "prompt" if any(f["key"] == "prompt" for f in fields) else \
            next((f["key"] for f in fields if f.get("type") == "textarea"), "")
        cfg = dict(it["config"])
        if key and (it["prompt"] or note):
            cur = str((n.get("config") or {}).get(key) or "").strip()
            cfg[key] = it["prompt"] or "\n\n".join(x for x in (cur, note) if x)
        if cfg:
            r.update_nodes(board["id"], [{"id": n["id"], "config": cfg}])


def _parse(text: str):
    try:
        data = extract_json(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and ("tra_loi" in data or "de_xuat" in data or "danh_gia" in data) else None


def _strip_json(text: str) -> str:
    """Câu trả lời không có trường tra_loi → lấy phần chữ ngoài khối JSON."""
    return re.sub(r"```(?:json)?\s*.*?```", "", str(text or ""), flags=re.S).strip()


def _clean_eval(raw):
    if not isinstance(raw, dict):
        return None

    def score(v):
        try:
            return max(0.0, min(10.0, round(float(v), 1)))
        except (TypeError, ValueError):
            return None

    nodes = [{"id": str(x.get("id") or ""), "diem": score(x.get("diem")), "nhan_xet": _short(x.get("nhan_xet"), 300)}
             for x in raw.get("node") or [] if isinstance(x, dict) and x.get("id")][:20]
    out = {"diem": score(raw.get("diem")), "tom_tat": _short(raw.get("tom_tat"), 500),
           "van_de": [_short(v, 300) for v in raw.get("van_de") or [] if str(v or "").strip()][:12], "node": nodes}
    return out if out["diem"] is not None or out["tom_tat"] or out["van_de"] or nodes else None


class CanvasAssistant(_ChatAssistant, AutoPilot):
    """Trợ lý Canvas: chat đề xuất (bạn bấm Áp dụng) + tự điều phối (chấm theo tiêu chí → giao khối chưa đạt làm lại)."""
