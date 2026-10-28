"""Canvas — bảng node kiểu Kling Canvas: node Ảnh (prompt → model ảnh, ảnh nối vào = ảnh tham chiếu để sửa / ghép),
node Video (ảnh nối vào = khung đầu → model video), node Tải lên (ảnh của người dùng). Mỗi bảng lưu ở
<output_dir>/_canvas/<id>/board.json, file của node ở nodes/ (UI xem qua /media/_canvas/...).
Tạo ảnh / video dùng chung ImageRunner / JobRunner của app (đúng model, profile, giới hạn song song đã cài)."""
from __future__ import annotations  # CanvasRunner.list() che tên kiểu list trong chú thích kiểu

import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import ffmpeg, model_prefs
from .image_library import IMAGES_DIR
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.image_engines import normalize as normalize_image
from .llm.video_engines import ENGINES as VIDEO_ENGINES
from .pipeline import Cancelled
from .pipeline.tasks import TaskPool
from .util import read_json, slugify, write_json

CANVAS_DIR = "_canvas"
VIDEO_TEMPLATE = "canvas-video"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_NODES = 200
MAX_INPUTS = 10
MAX_UPSCALE_SIDE = 4096  # phóng to 2× nhưng cạnh dài tối đa 4096px
EDITABLE = ("x", "y", "title", "prompt", "engine", "aspect", "count", "duration", "resolution", "pick", "first_frame", "ask", "dialogue", "voice",
            "dialogue_src", "auto_post", "prompt_src", "w")
NODE_W = (120, 800)  # cỡ node Ảnh / Video / Ảnh tải lên kéo được (px, theo chiều rộng); w = 0 → cỡ mặc định
VIDEO_REF_SLOTS = ("ref1", "ref2", "ref3", "ref4", "ref5")  # ô ảnh tham chiếu của template canvas-video
# block của Workflow dùng được trên Canvas (chạy bằng chính workflow.nodes.run_node). Tạo ảnh / video là node riêng.
WF_TYPES = ("input_text", "ai_text", "content_post", "input_video", "concat_video", "dub_vieneu", "post_video", "studio_video", "storyboard_video",
            "whiteboard_video", "fb_post", "fb_schedule", "fb_ad", "output")
MAX_RUNS = 20  # lịch sử chạy giữ trong board.json
POST_TYPES = ("fb_post", "fb_schedule", "fb_ad")  # khối đăng / lên lịch / quảng cáo: không bao giờ tự chạy lại khi làm lại
# khối Nhóm / ghi chú (kiểu sticky note n8n): chỉ để gom + ghi chú, không tham gia chạy quy trình
GROUP_COLORS = ("yellow", "green", "blue", "purple", "red", "gray")
MAX_GROUPS = 100
WF_HIDDEN = {"sources", "confirm", "ask", "label"}  # Canvas nối dây thay "tài nguyên từ flow"; đăng bài LUÔN chờ duyệt
ACTIVE = ("queued", "running", "waiting")
ENHANCE_SYSTEM = ("Bạn viết prompt cho model tạo {what}. Viết lại prompt người dùng thành MỘT đoạn prompt tiếng Anh "
                  "rõ ràng, cụ thể (chủ thể, hành động, bối cảnh, ánh sáng, góc máy{motion}), màu tươi sáng tự nhiên, "
                  "da người giữ kết cấu thật, không làm mịn. Giữ nguyên ý và mọi chữ / tên sản phẩm người dùng ghi. "
                  "Chỉ trả về đoạn prompt, không giải thích.")


# 💬 lời thoại của node Video: giọng → mô tả cho model video (tiếng nói gốc trong clip, khớp khẩu hình)
VOICES = {
    "": ("Theo người trong ảnh", ""),
    "young_f": ("Nữ trẻ", "a bright young Vietnamese woman's voice"),
    "young_m": ("Nam trẻ", "a clear young Vietnamese man's voice"),
    "mid_f": ("Nữ trung niên", "a warm middle-aged Vietnamese woman's voice"),
    "mid_m": ("Nam trung niên", "a deep, steady middle-aged Vietnamese man's voice"),
    "narrator": ("Lời dẫn ngoài khung", "an off-screen Vietnamese narrator (nobody on screen moves their lips)"),
}
WORDS_PER_SEC = 3.2  # tiếng Việt nói tự nhiên ~3 chữ / giây; trừ 1 giây đầu / cuối


def dialogue_words(node: dict) -> int:
    """Số chữ sẽ nói (bỏ phần "Tên:" đầu mỗi dòng)."""
    return len(re.sub(r"(?m)^[^:\n]{1,30}:\s*", "", node.get("dialogue") or "").split())


def dialogue_limit(node: dict) -> int:
    secs = int(str(node.get("duration") or "10s").rstrip("s") or 10)
    return max(4, int((secs - 1) * WORDS_PER_SEC))


def dialogue_prompt(node: dict) -> str:
    """Câu lời thoại cho prompt video: nói đúng nguyên văn tiếng Việt, khớp khẩu hình, nói xong trong thời lượng clip."""
    lines = [" ".join(x.split()) for x in (node.get("dialogue") or "").splitlines() if x.strip()]
    if not lines:
        return ""
    voice = VOICES.get(node.get("voice") or "", VOICES[""])[1]
    said = "; ".join(f'"{x}"' if ":" not in x[:31] else f'{x.split(":", 1)[0].strip()}: "{x.split(":", 1)[1].strip()}"'
                     for x in lines)
    secs = int(str(node.get("duration") or "10s").rstrip("s") or 10)
    who = "an off-screen narrator says" if node.get("voice") == "narrator" else "the on-screen character speaks"
    return (f"DIALOGUE: {who} these exact lines out loud in Vietnamese, word for word, clearly audible"
            + (f", in {voice}" if voice else "") + ", with natural lip-sync, expressions and gestures matching the words: "
            + said + f". Pace the speech so every line finishes within {max(2, secs - 1)} seconds — never cut off "
            "mid-sentence. Keep only the voice and light natural ambience — no background music covering the voice, "
            "no subtitles or on-screen text unless the motion description asks for them.")


class CanvasError(Exception):
    pass


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def meta(settings) -> dict:
    """Lựa chọn cho giao diện Canvas: model ảnh / video sẵn có trong hệ thống + model mặc định ở Cài đặt → Model AI."""
    from .content_writer import models

    prefs = model_prefs.get(settings)
    return {
        "image_engines": {k: {"name": v["name"], "aspects": v["aspects"], "counts": v["counts"],
                              "max_images": v["max_images"], "note": v.get("note", "")} for k, v in IMAGE_ENGINES.items()},
        "video_engines": {k: {"name": v["name"], "durations": v["durations"], "resolutions": v["resolutions"],
                              "aspects": v["aspects"], "max_images": v.get("max_images", 1),
                              "video_input": bool(v.get("video_input")), "note": v.get("note", "")}
                          for k, v in VIDEO_ENGINES.items()},
        "text_models": models(settings),
        "wf_types": wf_types(),
        "voices": [{"value": k, "label": v[0]} for k, v in VOICES.items()],
        "words_per_sec": WORDS_PER_SEC,
        "defaults": {"image": prefs["model_image"] if prefs["model_image"] in IMAGE_ENGINES else "openai_api",
                     "video": prefs["model_video"] if prefs["model_video"] in VIDEO_ENGINES else "grok_browser",
                     "text": prefs["model_text"]},
    }


def _shown(wtype: str, key: str) -> bool:
    """Ô cấu hình block hiện trên Canvas: bỏ ô Canvas không dùng; riêng Video đầu vào giữ ô "Hỏi lại khi chạy"."""
    return key not in WF_HIDDEN or (wtype == "input_video" and key == "ask")


def wf_types() -> dict:
    """Block Workflow trên Canvas: cổng vào / ra + ô cấu hình (bỏ các ô Canvas không dùng)."""
    from .workflow import nodes as wfn

    return {k: {"name": s["name"], "icon": s["icon"], "desc": s["desc"], "group": s["group"], "inputs": s["inputs"],
                "outputs": s["outputs"], "fields": [f for f in s["fields"] if _shown(k, f["key"])]}
            for k, s in wfn.NODE_TYPES.items() if k in WF_TYPES}


def out_types(node: dict) -> set:
    """Kiểu dữ liệu node đưa ra: images / video / text / post."""
    if node["kind"] in ("image", "upload"):
        return {"images"}
    if node["kind"] == "video":
        return {"video"}
    from .workflow import nodes as wfn

    return {o["type"] for o in wfn.NODE_TYPES[node["wtype"]]["outputs"]}


def in_types(node: dict) -> set:
    """Kiểu dữ liệu node nhận: Ảnh nhận ảnh tham chiếu + chữ; Video nhận ảnh (khung đầu, tham chiếu), video tham chiếu
    + chữ (thêm vào prompt)."""
    if node["kind"] == "image":
        return {"images", "text"}
    if node["kind"] == "video":
        return {"images", "video", "text"}
    if node["kind"] == "upload":
        return set()
    from .workflow import nodes as wfn

    out = {"text"} if node["wtype"] == "output" else set()
    for p in wfn.NODE_TYPES[node["wtype"]]["inputs"]:
        out |= {"images", "video"} if p["type"] == "any" else {p["type"]}
    return out


class CanvasRunner:
    def __init__(self, settings, emit, images=None, videos=None, facebook=None, ads=None, studio=None) -> None:
        self.on_flow_done = None  # hook: (bid, bản ghi lần chạy) khi chạy quy trình xong — trợ lý Claude tự điều phối
        self.settings = settings
        self.emit = emit
        self.images = images
        self.videos = videos
        self.facebook, self.ads, self.studio = facebook, ads, studio  # block Đăng bài / Quảng cáo / Video dài
        self.pool = TaskPool("canvas_", emit, lambda: settings.get("max_parallel_canvas") or 4)
        self._lock = threading.RLock()
        self._approvals: dict[tuple, dict] = {}  # (bảng, node) → {"event", "decision"} — đăng bài chờ duyệt
        # lượt chạy quy trình đang chạy được nối dài (Storyboard tách cảnh → node Video mới chạy luôn trong lượt đó)
        self._grow: dict[str, bool] = {}  # bảng → lượt sắp chạy có được nối dài không (Chạy toàn bộ / Chạy từ đây)
        self._live: dict[str, tuple] = {}  # bảng → (mã lượt, danh sách node theo thứ tự — nối thêm được khi đang chạy)

    # ------------------------------------------------------------------ lưu trữ
    @property
    def root(self) -> Path:
        path = Path(self.settings.output_dir) / CANVAS_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def dir(self, bid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{6,60}", bid or ""):
            raise CanvasError("Mã bảng không hợp lệ")
        path = self.root / bid
        if not (path / "board.json").is_file():
            raise CanvasError("Không tìm thấy bảng")
        return path

    def load(self, bid: str) -> dict:
        return read_json(self.dir(bid) / "board.json")

    def _save(self, board: dict) -> dict:
        board["updated_at"] = now()
        write_json(self.root / board["id"] / "board.json", board)
        return board

    def _edit(self, bid: str, fn) -> dict:
        with self._lock:
            board = self.load(bid)
            fn(board)
            return self._save(board)

    @staticmethod
    def _node(board: dict, nid: str) -> dict:
        node = next((n for n in board["nodes"] if n["id"] == nid), None)
        if node is None:
            raise CanvasError("Không tìm thấy node")
        return node

    def _url(self, bid: str, rel: str) -> str:
        path = self.root / bid / rel
        return f"/media/{CANVAS_DIR}/{bid}/{rel}?v={int(path.stat().st_mtime)}" if path.is_file() else ""

    def public_node(self, bid: str, node: dict) -> dict:
        return {**node, "urls": [u for u in (self._url(bid, f) for f in node.get("files") or []) if u]}

    def public(self, board: dict) -> dict:
        return {**board, "nodes": [self.public_node(board["id"], n) for n in board["nodes"]]}

    def _push(self, bid: str, nid: str) -> None:
        """Báo UI 1 node vừa đổi (trạng thái, %, file mới)."""
        try:
            board = self.load(bid)
            self.emit("canvas_node", {"board": bid, "node": self.public_node(bid, self._node(board, nid))})
        except (CanvasError, OSError):
            pass

    # ------------------------------------------------------------------ bảng
    def list(self) -> list[dict]:
        out = []
        for f in self.root.glob("*/board.json"):
            try:
                b = read_json(f)
            except (OSError, ValueError):
                continue
            thumb = next((self._url(b["id"], n["files"][min(int(n.get("pick") or 0), len(n["files"]) - 1)])
                          for n in reversed(b["nodes"]) if n.get("files") and n["kind"] != "video"), "")
            runs = b.get("runs") or []
            last = runs[-1] if runs else None
            kinds = {n["id"]: (n.get("wtype") or n["kind"]) for n in b["nodes"]}
            out.append({"id": b["id"], "name": b["name"], "updated_at": b.get("updated_at", ""),
                        "created_at": b.get("created_at", ""), "nodes": len(b["nodes"]),
                        "edges": sum(len(n.get("inputs") or []) for n in b["nodes"]), "thumb": thumb,
                        "chain": [kinds[i] for i in self._topo(b)][:14],  # thứ tự chạy → chuỗi biểu tượng trên thẻ
                        "runs": len(runs), "runs_today": sum(1 for r in runs if str(r.get("at", ""))[:10] == now()[:10]),
                        "last_run": {k: last.get(k) for k in ("id", "label", "status", "at", "ended")} if last else None,
                        "running": any(n.get("status") in ACTIVE for n in b["nodes"]),
                        "schedule": self._schedule_info(b.get("schedule"))})
        return sorted(out, key=lambda x: x["updated_at"], reverse=True)

    @staticmethod
    def _schedule_info(s: dict | None) -> dict | None:
        """Lịch chạy cho thẻ ở màn danh sách (kèm mô tả bằng chữ)."""
        from .canvas_schedule import describe

        return {**s, "desc": describe(s)} if s else None

    def duplicate_board(self, bid: str) -> dict:
        """Nhân bản cả Canvas (node, dây nối, ảnh / video đã tạo) — bản sao chưa có lịch sử chạy."""
        src = self.dir(bid)
        board = self.load(bid)
        name = f"{board['name']} (bản sao)"[:80]
        new = f"{slugify(name, 30) or 'canvas'}-{uuid.uuid4().hex[:6]}"
        shutil.copytree(src, self.root / new, ignore=shutil.ignore_patterns("runs"))
        board.update(id=new, name=name, created_at=now(), runs=[], run_seq=0)
        for n in board["nodes"]:
            if n.get("status") in ACTIVE:
                n.update(status="idle", pct=0, task="", approval={})
        return self.public(self._save(board))

    def create(self, name: str = "") -> dict:
        name = " ".join(str(name or "").split())[:80] or f"Canvas {datetime.now():%d/%m %H:%M}"
        bid = f"{slugify(name, 30) or 'canvas'}-{uuid.uuid4().hex[:6]}"
        (self.root / bid / "nodes").mkdir(parents=True, exist_ok=True)
        board = {"id": bid, "name": name, "created_at": now(), "updated_at": now(), "seq": 0, "nodes": []}
        return self.public(self._save(board))

    def open(self, bid: str) -> dict:
        def fix(board):  # app tắt giữa chừng → node đang chạy không còn tác vụ nào theo dõi
            live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
            for n in board["nodes"]:
                if n.get("status") in ACTIVE and n.get("task") not in live:
                    n.update(status="error", error="Đã dừng (app được mở lại) — bấm Tạo lại", pct=0, approval={})
        return self.public(self._edit(bid, fix))

    def rename(self, bid: str, name: str) -> dict:
        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise CanvasError("Tên bảng trống")
        return self.public(self._edit(bid, lambda b: b.update(name=name)))

    def delete(self, bid: str) -> None:
        path = self.dir(bid)
        for n in self.load(bid)["nodes"]:
            if n.get("status") in ACTIVE and n.get("task"):
                self.pool.cancel(n["task"])
        shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------------ node
    def _defaults(self, kind: str) -> dict:
        info = meta(self.settings)["defaults"]
        if kind == "video":
            spec = VIDEO_ENGINES[info["video"]]
            return {"engine": info["video"], "aspect": "9:16" if "9:16" in spec["aspects"] else spec["aspects"][0],
                    "duration": "10s" if "10s" in spec["durations"] else spec["durations"][-1],
                    "resolution": "720p" if "720p" in spec["resolutions"] else spec["resolutions"][0],
                    "first_frame": True}
        spec = IMAGE_ENGINES[info["image"]]
        return {"engine": info["image"], "aspect": "9:16" if "9:16" in spec["aspects"] else spec["aspects"][0],
                "count": 1}

    def _new_node(self, board: dict, kind: str, x: float, y: float, inputs: list, prompt: str, wtype: str = "") -> dict:
        if len(board["nodes"]) >= MAX_NODES:
            raise CanvasError(f"Mỗi bảng tối đa {MAX_NODES} node")
        board["seq"] = int(board.get("seq") or 0) + 1
        ids = {n["id"] for n in board["nodes"]}
        node = {"id": f"n{board['seq']}", "kind": kind, "x": float(x), "y": float(y), "title": "",
                "prompt": str(prompt or "")[:4000], "inputs": [i for i in (inputs or []) if i in ids][:MAX_INPUTS],
                "files": [], "pick": 0, "status": "idle", "pct": 0, "error": "", "task": ""}
        if kind == "wf":
            from .workflow import nodes as wfn

            node.update(wtype=wtype, out={}, approval={},
                        config={k: v for k, v in wfn.defaults(wtype).items() if _shown(wtype, k)})
        elif kind == "upload":
            node["ask"] = False  # ❓ hỏi chọn ảnh mỗi lần chạy quy trình
        else:
            node.update(self._defaults(kind))
        board["nodes"].append(node)
        return node

    def _result(self, bid: str, board: dict, nid: str) -> dict:
        return {"board": self.public(board), "node": self.public_node(bid, self._node(board, nid))}

    def add_node(self, bid: str, kind: str, x: float = 0, y: float = 0, inputs: list | None = None,
                 prompt: str = "", wtype: str = "") -> dict:
        if kind not in ("image", "video", "wf", "upload") or (kind == "wf" and wtype not in WF_TYPES):
            raise CanvasError("Loại node không hợp lệ")
        holder = {}

        def add(b):
            node = self._new_node(b, kind, x, y, [] if kind == "upload" else inputs or [], prompt, wtype)
            if kind == "upload":  # Ảnh đầu vào trống: chọn ảnh sau, hoặc để hỏi khi chạy quy trình
                node.update(title="Ảnh đầu vào", ask=True)
            holder["node"] = node
        board = self._edit(bid, add)
        return self._result(bid, board, holder["node"]["id"])

    def upload(self, bid: str, path: str, x: float = 0, y: float = 0) -> dict:
        src = Path(path or "")
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
            raise CanvasError("Chọn file ảnh (png, jpg, webp)")
        holder = {}

        def add(board):
            node = self._new_node(board, "upload", x, y, [], "")
            rel = f"nodes/{node['id']}_up{src.suffix.lower()}"
            shutil.copy2(src, self.root / bid / rel)
            node.update(title=src.stem[:60], files=[rel], status="done", pct=100)
            holder["node"] = node
        board = self._edit(bid, add)
        return self._result(bid, board, holder["node"]["id"])

    def replace_image(self, bid: str, nid: str, path: str) -> dict:
        """Thay ảnh của node ảnh (tải lên hoặc ảnh AI đã tạo) bằng ảnh khác trên máy — giữ vị trí + dây nối;
        node phía sau thấy đầu vào đổi → lần chạy quy trình sau tự chạy lại."""
        src = Path(path or "")
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
            raise CanvasError("Chọn file ảnh (png, jpg, webp)")

        def apply(board):
            node = self._node(board, nid)
            if node["kind"] not in ("upload", "image"):
                raise CanvasError("Chỉ thay được ảnh của node ảnh")
            if node.get("status") in ACTIVE:
                raise CanvasError("Node đang chạy — chờ xong hoặc bấm Dừng")
            rel = f"nodes/{nid}_up{int(time.time())}{src.suffix.lower()}"
            shutil.copy2(src, self.root / bid / rel)
            for old in node.get("files") or []:
                if old != rel:
                    (self.root / bid / old).unlink(missing_ok=True)
            node.update(files=[rel], pick=0, status="done", pct=100, error="", stage="")
            if node["kind"] == "upload":
                node["title"] = src.stem[:60]
            else:  # ảnh AI bị thay bằng ảnh của bạn → ghi chú để biết, và coi như đã có kết quả mới nhất
                node["title"] = f"ảnh thay: {src.stem[:40]}"
                node["sig"] = self._sig(board, nid)
        board = self._edit(bid, apply)
        return self._result(bid, board, nid)

    def update_nodes(self, bid: str, changes: list) -> dict:
        """Lưu vị trí / prompt / tuỳ chọn của các node (UI gửi sau khi kéo thả, gõ prompt, đổi model)."""
        def apply(board):
            for ch in changes or []:
                node = next((n for n in board["nodes"] if n["id"] == ch.get("id")), None)
                if node is None:
                    continue
                for k in EDITABLE:
                    if k in ch:
                        node[k] = float(ch[k]) if k in ("x", "y") else ch[k]
                if "w" in ch:
                    node["w"] = max(NODE_W[0], min(NODE_W[1], round(float(ch["w"])))) if ch["w"] else 0
                if node["kind"] == "wf":
                    if isinstance(ch.get("config"), dict):  # chỉ nhận đúng các ô của block đó
                        keys = {f["key"] for f in wf_types()[node["wtype"]]["fields"]}
                        node["config"].update({k: v for k, v in ch["config"].items() if k in keys})
                    if "out_text" in ch:  # sửa chữ kết quả (bài viết, prompt AI viết…) trước khi dùng tiếp
                        node.setdefault("out", {})["text"] = str(ch["out_text"])[:20000]
                    continue
                node["prompt"] = str(node.get("prompt") or "")[:4000]
                node["pick"] = max(0, min(int(node.get("pick") or 0), max(0, len(node.get("files") or []) - 1)))
                self._fit_options(node)
        return self.public(self._edit(bid, apply))

    @staticmethod
    def _fit_options(node: dict) -> None:
        """Model đổi → tỉ lệ / số ảnh / thời lượng / độ phân giải về giá trị model đó hỗ trợ."""
        if node["kind"] == "image":
            if node.get("engine") not in IMAGE_ENGINES:
                node["engine"] = "openai_api"
            node["aspect"], node["count"] = normalize_image(node["engine"], node.get("aspect") or "",
                                                            int(node.get("count") or 1))
        elif node["kind"] == "video":
            if node.get("engine") not in VIDEO_ENGINES:
                node["engine"] = "grok_browser"
            spec = VIDEO_ENGINES[node["engine"]]
            for key, opts in (("aspect", spec["aspects"]), ("duration", spec["durations"]),
                              ("resolution", spec["resolutions"])):
                if node.get(key) not in opts:
                    node[key] = opts[0]

    def _reaches(self, board: dict, start: str, goal: str) -> bool:
        """start có nằm phía trên goal không (đi ngược theo inputs từ goal)."""
        seen, stack = set(), [goal]
        while stack:
            cur = stack.pop()
            if cur == start:
                return True
            if cur not in seen:
                seen.add(cur)
                stack.extend(next((n["inputs"] for n in board["nodes"] if n["id"] == cur), []))
        return False

    @staticmethod
    def label(node: dict) -> str:
        if node["kind"] == "wf":
            return wf_types()[node["wtype"]]["name"]
        return {"image": "Ảnh", "video": "Video", "upload": "Ảnh tải lên"}[node["kind"]]

    def connect(self, bid: str, src: str, dst: str, on: bool = True) -> dict:
        def apply(board):
            target, source = self._node(board, dst), self._node(board, src)
            if not on:
                target["inputs"] = [i for i in target["inputs"] if i != src]
                if target.get("dialogue_src") == src:  # bỏ nối nguồn lời thoại → quay về tự nhập
                    target["dialogue_src"] = ""
                return
            outs = out_types(source)
            if src == dst or not outs & in_types(target):
                raise CanvasError(f"“{self.label(target)}” không nhận được đầu ra của “{self.label(source)}”")
            if self._reaches(board, dst, src):
                raise CanvasError("Không nối vòng tròn")
            if src in target["inputs"]:
                return
            if len(target["inputs"]) >= MAX_INPUTS:
                raise CanvasError(f"Mỗi node nhận tối đa {MAX_INPUTS} dây nối")
            target["inputs"] = target["inputs"] + [src]
        return self.public(self._edit(bid, apply))

    def delete_node(self, bid: str, nid: str) -> dict:
        def apply(board):
            node = self._node(board, nid)
            if node.get("status") in ACTIVE and node.get("task"):
                self.pool.cancel(node["task"])
            for rel in node.get("files") or []:
                (self.root / bid / rel).unlink(missing_ok=True)
            board["nodes"] = [n for n in board["nodes"] if n["id"] != nid]
            for n in board["nodes"]:
                n["inputs"] = [i for i in n.get("inputs") or [] if i != nid]
                if n.get("dialogue_src") == nid:
                    n["dialogue_src"] = ""
                if n.get("prompt_src") == nid:
                    n["prompt_src"] = ""
        return self.public(self._edit(bid, apply))

    # ------------------------------------------------------------------ nhóm / ghi chú
    @staticmethod
    def _clean_group(group: dict, src: dict) -> None:
        for k in ("x", "y"):
            if k in src:
                group[k] = round(float(src[k]))
        for k, lo in (("w", 180), ("h", 110)):
            if k in src:
                group[k] = max(lo, min(20000, round(float(src[k]))))
        if "title" in src:
            group["title"] = " ".join(str(src["title"] or "").split())[:80]
        if "note" in src:
            group["note"] = str(src["note"] or "")[:5000]
        if src.get("color") in GROUP_COLORS:
            group["color"] = src["color"]

    def add_group(self, bid: str, data: dict | None = None) -> dict:
        made = {}

        def add(board):
            groups = board.setdefault("groups", [])
            if len(groups) >= MAX_GROUPS:
                raise CanvasError(f"Tối đa {MAX_GROUPS} nhóm mỗi Canvas")
            board["gseq"] = int(board.get("gseq") or 0) + 1
            group = {"id": f"g{board['gseq']}", "x": 0, "y": 0, "w": 440, "h": 280, "title": "Nhóm mới", "note": "",
                     "color": "yellow"}
            self._clean_group(group, data or {})
            groups.append(group)
            made["id"] = group["id"]
        board = self._edit(bid, add)
        return {"board": self.public(board), "group": made["id"]}

    def update_group(self, bid: str, gid: str, patch: dict | None = None, moves: list | None = None) -> dict:
        """Sửa nhóm (vị trí, cỡ, tên, ghi chú, màu); moves = vị trí mới của các node kéo theo nhóm (lưu cùng lúc)."""
        def apply(board):
            group = next((g for g in board.get("groups") or [] if g["id"] == gid), None)
            if group is None:
                raise CanvasError("Không tìm thấy nhóm")
            self._clean_group(group, patch or {})
            for m in moves or []:
                node = next((n for n in board["nodes"] if n["id"] == m.get("id")), None)
                if node is not None:
                    node["x"], node["y"] = float(m["x"]), float(m["y"])
        return self.public(self._edit(bid, apply))

    def delete_group(self, bid: str, gid: str) -> dict:
        """Xoá khung nhóm — các node bên trong giữ nguyên."""
        def apply(board):
            board["groups"] = [g for g in board.get("groups") or [] if g["id"] != gid]
        return self.public(self._edit(bid, apply))

    def duplicate(self, bid: str, nid: str) -> dict:
        node = self._node(self.load(bid), nid)
        if node["kind"] == "upload":
            raise CanvasError("Node tải lên không nhân bản được — tải ảnh lên lại")
        res = self.add_node(bid, node["kind"], node["x"] + 40, node["y"] + 40, node["inputs"], node.get("prompt", ""),
                            node.get("wtype", ""))
        keep = {k: node[k] for k in ("engine", "aspect", "count", "duration", "resolution", "config") if k in node}
        board = self.update_nodes(bid, [{"id": res["node"]["id"], **keep}])
        return {"board": board, "node": next(n for n in board["nodes"] if n["id"] == res["node"]["id"])}

    # ------------------------------------------------------------------ nhiều node (quét chọn trên Canvas)
    COPY_KEYS = ("engine", "aspect", "count", "duration", "resolution", "config", "title", "prompt_src", "dialogue_src",
                 "dialogue", "voice", "first_frame", "w", "ask", "auto_post")

    def duplicate_nodes(self, bid: str, ids: list, dx: float = 60, dy: float = 60) -> dict:
        """Nhân bản nhiều node 1 lần: dây nối GIỮA các node được chọn chuyển sang bản sao (cả nhóm như 1 khối mới),
        dây từ node ngoài nhóm giữ nguyên. Node Tải lên không nhân bản (bản sao vẫn nối vào ảnh gốc)."""
        made = {}

        def apply(board):
            picked = [n for n in board["nodes"] if n["id"] in set(ids or []) and n["kind"] != "upload"]
            if not picked:
                raise CanvasError("Chưa chọn node nào nhân bản được (node Tải lên không nhân bản)")
            for src in picked:
                copy = self._new_node(board, src["kind"], src["x"] + dx, src["y"] + dy, [], src.get("prompt", ""),
                                      src.get("wtype", ""))
                copy.update({k: json.loads(json.dumps(src[k])) for k in self.COPY_KEYS if k in src})
                made[src["id"]] = copy
            for src in picked:  # nối lại: node trong nhóm → bản sao của nó; node ngoài nhóm → giữ
                copy = made[src["id"]]
                copy["inputs"] = [made[i]["id"] if i in made else i for i in src.get("inputs") or []][:MAX_INPUTS]
                for key in ("prompt_src", "dialogue_src"):
                    if copy.get(key) in made:
                        copy[key] = made[copy[key]]["id"]
        board = self._edit(bid, apply)
        return {"board": self.public(board), "nodes": [c["id"] for c in made.values()]}

    def delete_nodes(self, bid: str, ids: list) -> dict:
        """Xoá nhiều node 1 lần (dừng node đang chạy, xoá file kết quả, gỡ dây nối tới chúng)."""
        gone = set(ids or [])

        def apply(board):
            for node in board["nodes"]:
                if node["id"] not in gone:
                    continue
                if node.get("status") in ACTIVE and node.get("task"):
                    self.pool.cancel(node["task"])
                for rel in node.get("files") or []:
                    (self.root / bid / rel).unlink(missing_ok=True)
            board["nodes"] = [n for n in board["nodes"] if n["id"] not in gone]
            for n in board["nodes"]:
                n["inputs"] = [i for i in n.get("inputs") or [] if i not in gone]
                for key in ("dialogue_src", "prompt_src"):
                    if n.get(key) in gone:
                        n[key] = ""
        return self.public(self._edit(bid, apply))

    def file_of(self, bid: str, nid: str) -> Path:
        node = self._node(self.load(bid), nid)
        files = node.get("files") or []
        if not files:
            raise CanvasError("Node chưa có kết quả")
        path = self.root / bid / files[min(int(node.get("pick") or 0), len(files) - 1)]
        if not path.is_file():
            raise CanvasError("File kết quả đã bị xoá")
        return path

    def _abs(self, bid: str, rel: str) -> str:
        return str(self.root / bid / rel)

    def _outputs(self, bid: str, src: dict) -> dict:
        """Đầu ra của 1 node để đưa sang node phía sau: {images: [đường dẫn], video, text, post}."""
        files = src.get("files") or []
        if src["kind"] in ("image", "upload"):
            return {"images": [self._abs(bid, files[min(int(src.get("pick") or 0), len(files) - 1)])]} if files else {}
        if src["kind"] == "video":
            return {"video": self._abs(bid, files[0])} if files else {}
        out = dict(src.get("out") or {})
        if src.get("wtype") == "input_text" and not out.get("text"):  # Văn bản: dùng luôn chữ đang gõ, không cần Chạy
            out["text"] = str((src.get("config") or {}).get("text") or "").strip()
        if out.get("video"):
            out["video"] = self._abs(bid, out["video"])
        if out.get("images"):
            out["images"] = [self._abs(bid, x) for x in out["images"]]
        return {k: v for k, v in out.items() if v}

    def _input_text(self, bid: str, board: dict, node: dict) -> str:
        """Chữ từ node nối vào (AI viết prompt, Văn bản…) — thêm vào đầu prompt ảnh / video
        (trừ khối được chọn làm nguồn lời thoại của node Video)."""
        texts = []
        src = self._prompt_src(node)
        if src == "own":
            return ""
        for iid in [src] if src else node.get("inputs") or []:
            if iid == node.get("dialogue_src") and iid != src:
                continue
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] == "wf":
                scene = self._scene_for(src, node)
                text = str(scene.get("prompt") if scene is not None else self._outputs(bid, src).get("text") or "").strip()
                if scene and not self._dialogue_text(bid, board, node).strip():  # cảnh không lời → dặn model không nói
                    text += "\n\nNo dialogue or speech — only natural ambience; no subtitles or on-screen text."
                if text:
                    texts.append(text)
        return "\n\n".join(texts)

    @staticmethod
    def _scene_for(src: dict, node: dict) -> dict | None:
        """Node Video tách từ Storyboard (node.scene = k): cảnh thứ k của khối Storyboard src ({} nếu storyboard không còn
        cảnh đó); None nếu không phải cặp Storyboard → node cảnh."""
        k = int(node.get("scene") or 0)
        if src.get("wtype") != "storyboard_video" or k < 1:
            return None
        scenes = (src.get("out") or {}).get("scenes") or []
        return scenes[k - 1] if k <= len(scenes) else {}

    @staticmethod
    def _prompt_src(node: dict) -> str:
        """Nguồn prompt của node Ảnh / Video: "" = ghép chữ khối nối vào + prompt viết thêm (mặc định), "own" = chỉ prompt
        viết trực tiếp, id khối = chỉ lấy chữ khối đó (khối đã bỏ nối → về mặc định)."""
        src = str(node.get("prompt_src") or "")
        if src in ("", "own"):
            return src
        return src if src in (node.get("inputs") or []) else ""

    def _own_prompt(self, node: dict) -> str:
        """Prompt viết trực tiếp trên node — bỏ qua khi node lấy prompt từ 1 khối nối vào."""
        src = self._prompt_src(node)
        return "" if src not in ("", "own") else (node.get("prompt") or "").strip()

    def _dialogue_text(self, bid: str, board: dict, node: dict) -> str:
        """Lời thoại của node Video: chữ của khối nguồn đã chọn (Văn bản, AI viết…) nếu còn nối, không thì tự nhập."""
        sid = node.get("dialogue_src") or ""
        if sid and sid in (node.get("inputs") or []):
            src = next((n for n in board["nodes"] if n["id"] == sid), None)
            if src is not None:
                scene = self._scene_for(src, node)  # node cảnh của Storyboard → lời thoại đúng cảnh đó
                return str(scene.get("loi") if scene is not None else self._outputs(bid, src).get("text") or "").strip()
        return str(node.get("dialogue") or "")

    def _input_images(self, bid: str, board: dict, node: dict) -> list[Path]:
        out = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] in ("image", "upload") and src.get("files"):
                path = self.root / bid / src["files"][min(int(src.get("pick") or 0), len(src["files"]) - 1)]
                if path.is_file():
                    out.append(path)
        return out

    def _input_videos(self, bid: str, board: dict, node: dict) -> list[Path]:
        """Video từ node nối vào (node Video, Ghép video, Video dài…) — làm video tham chiếu."""
        out = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            video = self._outputs(bid, src).get("video") if src else ""
            if video and Path(video).is_file():
                out.append(Path(video))
        return out

    # ------------------------------------------------------------------ tạo ảnh / video
    def generate(self, bid: str, nid: str) -> dict:
        with self._lock:
            board = self.load(bid)
            node = self._node(board, nid)
            if node["kind"] == "upload":
                raise CanvasError("Node tải lên không cần tạo")
            if node.get("status") in ACTIVE:
                raise CanvasError("Node đang chạy")
            if node["kind"] == "wf":
                task = self.pool.submit(f"Canvas · {self.label(node)}", self._run_wf, bid, nid,
                                        meta={"board": bid, "node": nid})
                node.update(status="queued", pct=0, error="", task=task, approval={})
                self._save(board)
                self._push(bid, nid)
                return self.public(self.load(bid))
            refs = self._input_images(bid, board, node)
            text_in = self._input_text(bid, board, node)
            own = self._own_prompt(node)
            if node["kind"] == "video" and not (refs or self._input_videos(bid, board, node) or own or text_in):
                raise CanvasError("Video cần ảnh / video nối vào, hoặc prompt mô tả (tạo video từ chữ)")
            if node["kind"] == "image" and not (own or text_in):
                raise CanvasError("Ảnh chưa có prompt — viết prompt, hoặc nối khối chữ (Văn bản, AI viết…) vào và chạy khối đó")
            if node["kind"] == "image" and refs and IMAGE_ENGINES[node["engine"]]["max_images"] < 1:
                raise CanvasError(f"{IMAGE_ENGINES[node['engine']]['name']} không nhận ảnh tham chiếu — đổi model "
                                  "hoặc bỏ nối")
            what = "Video" if node["kind"] == "video" else "Ảnh"
            task = self.pool.submit(f"Canvas · {what} — {(own or text_in)[:60]}", self._run, bid, nid,
                                    meta={"board": bid, "node": nid})
            node.update(status="queued", pct=0, error="", task=task)
            self._save(board)
        self._push(bid, nid)
        return self.public(self.load(bid))

    def cancel(self, bid: str, nid: str) -> None:
        node = self._node(self.load(bid), nid)
        if node.get("task"):
            self.pool.cancel(node["task"])

    def _set_node(self, bid: str, nid: str, **fields) -> None:
        def apply(board):
            node = next((n for n in board["nodes"] if n["id"] == nid), None)
            if node is not None:
                node.update(fields)
        try:
            self._edit(bid, apply)
        except CanvasError:  # bảng đã xoá trong lúc chạy
            return
        self._push(bid, nid)

    def _run(self, bid: str, nid: str) -> dict:
        self._set_node(bid, nid, status="running", pct=1)
        try:
            board = self.load(bid)
            node = self._node(board, nid)
            refs = self._input_images(bid, board, node)
            prompt = "\n\n".join(x for x in (self._input_text(bid, board, node), self._own_prompt(node)) if x)
            if node["kind"] == "video":
                node = {**node, "dialogue": self._dialogue_text(bid, board, node)}  # lời thoại từ khối nguồn (nếu chọn)
                files = self._make_video(bid, node, refs, self._input_videos(bid, board, node), prompt)
            else:
                files = self._make_image(bid, node, refs, prompt)
        except Cancelled:
            self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng")
            raise
        except Exception as exc:
            self._set_node(bid, nid, status="error", pct=0, error=str(exc)[:300])
            raise
        self._set_node(bid, nid, status="done", pct=100, error="", files=files, pick=0, stage="")
        self._mark_sig(bid, nid)
        return {"board": bid, "node": nid, "files": files}

    def _follow(self, runner, task_id: str, bid: str, nid: str) -> dict:
        """Chờ tác vụ ảnh / video, chuyển % sang node (UI thấy tiến trình); dừng node → huỷ luôn tác vụ đó."""
        last = -1.0
        while True:
            try:
                self.pool.check_cancel()
            except Cancelled:
                runner.pool.cancel(task_id)
                raise
            item = next((t for t in runner.pool.list() if t["id"] == task_id), None)
            if item is None:
                raise CanvasError("Tác vụ đã bị xoá")
            if item["status"] not in ("queued", "running"):
                break
            pct = max(1.0, float(item.get("pct") or 0) * 0.98)
            if abs(pct - last) >= 2:
                last = pct
                self.pool.progress(pct, item.get("status_text") or "", "run")
                self._set_node(bid, nid, pct=round(pct), stage=item.get("status_text") or "")
            time.sleep(1)
        summary = runner.pool.wait(task_id)
        if summary["status"] != "done" or not summary.get("result"):
            raise CanvasError(summary.get("error") or "Tạo không thành công")
        return summary["result"]

    def _profile(self, kind: str, engine: str) -> str:
        """Profile trình duyệt đã gán ở Cài đặt → Model AI (chỉ khi node dùng đúng model mặc định đó)."""
        prefs = model_prefs.get(self.settings)
        return prefs.get(f"model_{kind}_profile", "") if engine == prefs.get(f"model_{kind}") else ""

    def _make_image(self, bid: str, node: dict, refs: list[Path], prompt: str) -> list[str]:
        refs = refs[:IMAGE_ENGINES[node["engine"]]["max_images"]]
        if refs:
            self.pool.log(f"Gửi kèm {len(refs)} ảnh nối vào làm ảnh tham chiếu")
        task = self.images.start({
            "engine": node["engine"], "prompt": prompt, "aspect": node["aspect"],
            "count": int(node.get("count") or 1), "quality": "high", "refs": [], "show_browser": False,
            "extra_refs": [{"path": str(p), "role": f"reference image {i + 1}",
                            "prompt": "use this image as the prompt says (edit it, or keep its subject / product)"}
                           for i, p in enumerate(refs)],
            "ref_note": True, "browser_profile": self._profile("image", node["engine"])})
        result = self._follow(self.images, task, bid, node["id"])
        src_dir = Path(self.settings.output_dir) / IMAGES_DIR / result["id"]
        stamp, files = int(time.time()), []
        for i, f in enumerate(result.get("files") or []):
            src = src_dir / f["name"]
            if src.is_file():
                rel = f"nodes/{node['id']}_{stamp}_{i + 1}{src.suffix.lower()}"
                shutil.copy2(src, self.root / bid / rel)
                files.append(rel)
        if not files:
            raise CanvasError("Model không trả ảnh nào")
        self._drop_old(bid, node)
        return files

    def video_plan(self, node: dict, images: list, videos: list) -> dict:
        """Chia file nối vào node Video thành ô đính kèm của template: ảnh đầu = khung mở đầu (nếu bật), các ảnh
        sau = ảnh tham chiếu, 1 video tham chiếu; tổng số file không vượt giới hạn của model video."""
        limit = max(1, int(VIDEO_ENGINES[node["engine"]].get("max_images") or 1))
        images, videos = list(images), list(videos)[:1]
        plan, dropped = {}, 0
        if videos:
            limit -= 1
        if images and node.get("first_frame", True):
            plan["image"] = str(images.pop(0))
            limit -= 1
        for slot in VIDEO_REF_SLOTS:
            if images and limit > 0:
                plan[slot] = str(images.pop(0))
                limit -= 1
        dropped = len(images)
        if videos:
            plan["vref"] = str(videos[0])
        return {"attachments": plan, "dropped": dropped}

    def _make_video(self, bid: str, node: dict, images: list[Path], videos: list[Path], prompt: str) -> list[str]:
        plan = self.video_plan(node, images, videos)
        att = plan["attachments"]
        if plan["dropped"]:
            self.pool.log(f"{VIDEO_ENGINES[node['engine']]['name']} nhận tối đa "
                          f"{VIDEO_ENGINES[node['engine']]['max_images']} file — bỏ {plan['dropped']} ảnh cuối", "warn")
        refs = sum(1 for k in att if k in VIDEO_REF_SLOTS)
        self.pool.log("Gửi kèm: " + ", ".join(x for x in ("1 ảnh khung đầu" if "image" in att else "",
                                                          f"{refs} ảnh tham chiếu" if refs else "",
                                                          "1 video tham chiếu" if "vref" in att else "") if x))
        lead = ("Image-to-video: animate the opening frame (the first attached image) — do not create a new image."
                if "image" in att else
                "Create a new video that uses the attached references — keep every person, product and place in them "
                "identical." if att else "Text-to-video: create the video from this description.")
        motion = prompt or ("Bring this image to life with natural, subtle motion; keep every person, product and "
                            "detail exactly as in the image.")
        task = self.videos.start({
            "template": VIDEO_TEMPLATE, "provider": node["engine"], "ai_duration": node["duration"],
            "ai_aspect": node["aspect"], "ai_resolution": node["resolution"],
            "variables": {"KhungDau": lead, "MoTa": motion, "LoiThoai": dialogue_prompt(node)},
            "attachments": att, "show_browser": False, "topic": "Canvas",
            "browser_profile": self._profile("video", node["engine"])})
        result = self._follow(self.videos, task, bid, node["id"])
        src = Path(self.settings.output_dir) / result["id"] / "final.mp4"
        if not src.is_file():
            raise CanvasError("Không thấy file video kết quả")
        rel = f"nodes/{node['id']}_{int(time.time())}.mp4"
        shutil.copy2(src, self.root / bid / rel)
        self._drop_old(bid, node)
        return [rel]

    def _drop_old(self, bid: str, node: dict) -> None:
        """Tạo lại → xoá kết quả cũ của node (giữ bảng gọn)."""
        for rel in node.get("files") or []:
            (self.root / bid / rel).unlink(missing_ok=True)

    # ------------------------------------------------------------------ block Workflow (viết content, đăng bài…)
    def _wf_inputs(self, bid: str, board: dict, node: dict, spec: dict) -> dict:
        """Đầu ra các node nối vào → đúng cổng của block theo kiểu dữ liệu (chữ → text, ảnh → images, video → video,
        ảnh / video → cổng 'any' như Ảnh / video của Đăng bài, bài viết → post)."""
        values = {p["key"]: [] for p in spec["inputs"]}
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src is None:
                continue
            out = self._outputs(bid, src)
            for p in spec["inputs"]:
                kind = p["type"]
                if kind == "any":
                    values[p["key"]] += list(out.get("images") or []) + ([out["video"]] if out.get("video") else [])
                    if node["wtype"] == "output" and out.get("text"):  # khối Kết quả gom cả chữ (bài viết, prompt…)
                        values[p["key"]].append(out["text"])
                elif kind in out:
                    values[p["key"]].append(out[kind])
        return values

    def _media_url(self, path: str) -> str:
        """Ảnh / video sắp đăng (nằm trong thư mục video) → URL xem trước trên ô duyệt."""
        try:
            rel = Path(path).resolve().relative_to(Path(self.settings.output_dir).resolve())
        except (ValueError, OSError):
            return ""
        return f"/media/{rel.as_posix()}"

    def _wait_approval(self, bid: str, nid: str, payload: dict) -> dict:
        """Block Đăng bài / Lên lịch: dừng chờ người dùng bấm Đồng ý / Từ chối trên node (Canvas luôn bắt duyệt)."""
        slot = {"event": threading.Event(), "decision": None}
        self._approvals[(bid, nid)] = slot
        show = {k: v for k, v in payload.items() if k != "scheduled_at"}
        show["media_urls"] = [u for u in (self._media_url(f) for f in payload.get("files") or []) if u]
        self._set_node(bid, nid, status="waiting", approval=show, stage="Chờ bạn duyệt")
        self.emit("toast", {"message": f"Canvas: bài đăng lên “{payload.get('page', '')}” đang chờ bạn duyệt", "level": "warn"})
        try:
            while not slot["event"].wait(0.5):
                self.pool.check_cancel()  # bấm Dừng trong lúc chờ duyệt
        finally:
            self._approvals.pop((bid, nid), None)
        decision = slot["decision"]
        if decision.get("caption") is None:
            decision["caption"] = payload.get("caption", "")
        self._set_node(bid, nid, status="running", approval={}, stage="")
        return decision

    def approve(self, bid: str, nid: str, approved: bool, caption: str | None = None) -> dict:
        import getpass

        slot = self._approvals.get((bid, nid))
        if slot is None:
            raise CanvasError("Node này không còn chờ duyệt")
        slot["decision"] = {"approved": bool(approved), "caption": caption, "by": f"{getpass.getuser()} (máy này)",
                            "at": now()}
        slot["event"].set()
        return {"node": nid, "approved": bool(approved)}

    def _run_wf(self, bid: str, nid: str) -> dict:
        from .workflow import nodes as wfn

        self._set_node(bid, nid, status="running", pct=1, error="")
        board = self.load(bid)
        node = self._node(board, nid)
        spec = wfn.NODE_TYPES[node["wtype"]]
        last = [-1.0]

        def progress(frac):
            pct = round(100 * max(0.0, min(1.0, float(frac))))
            if pct - last[0] >= 2:
                last[0] = pct
                self.pool.progress(pct, "", "run")
                self._set_node(bid, nid, pct=max(1, pct))

        # đăng bài chờ duyệt — trừ khi bạn bật "🚀 Tự đăng không cần duyệt" cho khối đó; Canvas nối dây nên không
        # dùng "tài nguyên từ flow"
        confirm = not (node.get("auto_post") and node["wtype"] in ("fb_post", "fb_schedule"))
        if not confirm:
            self.pool.log(f"{nid}: 🚀 tự đăng không cần duyệt (đã bật cho khối này)", "warn")
        wnode = {"id": nid, "type": node["wtype"], "config": {**(node.get("config") or {}), "confirm": confirm, "sources": []}}
        materials = self._materials(bid, board, node) if node["wtype"] == "storyboard_video" else None
        if materials:  # Storyboard: tên khối vật liệu (đúng thứ tự ảnh / video gửi model) để model chọn vật liệu từng cảnh
            wnode["config"]["_materials"] = {k: [self._material_name(self._node(board, i)) for i in ids]
                                             for k, ids in materials.items()}
        services = {"facebook": self.facebook, "ads": self.ads, "studio": self.studio,
                    "workflow_name": f"Canvas · {board['name']}",
                    "approve": lambda payload: self._wait_approval(bid, nid, payload)}
        ctx = wfn.NodeContext(self.settings, self.root / bid / "runs", wnode, self.pool.log, self.pool.check_cancel,
                              progress, services)
        try:
            inputs = self._wf_inputs(bid, board, node, spec)
            result = wfn.run_node(ctx, inputs)
        except wfn.NodeSkipped as exc:
            self._set_node(bid, nid, status="idle", pct=0, error=str(exc), approval={}, stage="")
            return {"board": bid, "node": nid, "skipped": True}
        except Cancelled:
            self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng", approval={}, stage="")
            raise
        except Exception as exc:
            self._set_node(bid, nid, status="error", pct=0, error=str(exc)[:300], approval={}, stage="")
            raise
        out, files, stamp = {}, [], int(time.time())
        for key, value in result.items():
            if key == "video" and value and Path(str(value)).is_file():
                src = Path(str(value))
                rel = f"nodes/{nid}_{stamp}{src.suffix.lower() or '.mp4'}"
                shutil.copy2(src, self.root / bid / rel)
                out["video"], files = rel, [rel]
            elif key in ("text", "ad") and value:
                out["text"] = str(value)
            elif key == "scenes" and isinstance(value, list):  # Storyboard: các cảnh → node Video từng cảnh đọc từ đây
                out["scenes"] = value
                out["materials"] = materials or {"anh": [], "video": []}  # Ảnh k / Video k của model → id khối vật liệu
            elif key == "items":
                folder = str(ctx.dir.parent / str(wnode["config"].get("name") or "ket-qua"))
                out.update(folder=folder, text=f"Đã gom {len(value or [])} kết quả vào thư mục:\n{folder}")
            elif key == "post" and isinstance(value, dict):
                # thẻ bài đăng trên Canvas: thời gian + ảnh / khung hình của file đã đăng (lấy từ đầu vào Ảnh / video)
                media = next((p for p in inputs.get("media") or [] if isinstance(p, str) and Path(p).is_file()), "")
                out["post"] = {**value, "at": now(), "thumb": self._media_url(media) if media else ""}
                where = value.get("url") or value.get("post_id") or ""
                out["text"] = (f"{'Đã lên lịch ' + value.get('when', '') if value.get('scheduled') else 'Đã đăng'} lên "
                               f"“{value.get('page', '')}”" + (f": {where}" if where else ""))
        if result.get("storyboard"):  # Storyboard: khung hiện storyboard; lời dẫn giữ riêng
            out.update(narration=out.get("text", ""), text=str(result["storyboard"]))
        self._drop_old(bid, node)
        self._set_node(bid, nid, status="done", pct=100, error="", out=out, files=files, pick=0, stage="", approval={})
        self._mark_sig(bid, nid)
        if node["wtype"] == "storyboard_video" and out.get("scenes"):
            self._split_scenes(bid, nid)
        return {"board": bid, "node": nid}

    def _materials(self, bid: str, board: dict, node: dict) -> dict:
        """Khối vật liệu nối vào Storyboard theo đúng thứ tự ảnh / video gửi model (như _wf_inputs): {anh: [id], video: [id]}."""
        mats = {"anh": [], "video": []}
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            out = self._outputs(bid, src) if src is not None else {}
            mats["anh"] += [iid for p in out.get("images") or [] if Path(p).is_file()]
            if out.get("video") and Path(out["video"]).is_file():
                mats["video"].append(iid)
        return mats

    def _material_name(self, node: dict) -> str:
        return f"{node.get('title') or self.label(node)} (khối {node['id']})"

    SCENE_GAP_Y, SCENE_GAP_X = 470, 400  # node cảnh (cao ~430px) xếp dọc bên phải khối Storyboard, khối Ghép xa thêm 1 cột

    def _split_scenes(self, bid: str, sid: str) -> list:
        """Storyboard xong → mỗi cảnh 1 node Video (prompt + lời thoại lấy đúng cảnh đó từ Storyboard, ảnh tham chiếu nối
        vào Storyboard nối luôn vào từng cảnh) + 1 khối Ghép video nối các cảnh theo thứ tự. Đã có thì giữ nguyên node cũ
        (model, thời lượng bạn đã đổi) — chỉ thêm cảnh còn thiếu, đổi tên theo nội dung mới. Đang chạy quy trình → node mới
        chạy luôn trong lượt đó. Trả về id các node vừa tạo."""
        created, touched = [], []

        def apply(board):
            sb = self._node(board, sid)
            out = sb.get("out") or {}
            cfg, scenes = sb.get("config") or {}, out.get("scenes") or []
            ids = {n["id"] for n in board["nodes"]}
            mats = {k: [i for i in v if i in ids] for k, v in (out.get("materials") or {}).items()}
            every = list(dict.fromkeys(mats.get("anh", []) + mats.get("video", [])))  # mọi khối vật liệu (không trùng)

            def chosen(scene):  # vật liệu model chọn cho cảnh (Ảnh k → khối thứ k); model không ghi → dùng tất cả
                if "anh" not in scene:
                    return every
                pick = [mats["anh"][k - 1] for k in scene.get("anh") or [] if 0 < k <= len(mats.get("anh", []))]
                pick += [mats["video"][k - 1] for k in scene.get("video") or [] if 0 < k <= len(mats.get("video", []))]
                return list(dict.fromkeys(pick))

            mine = {int(n.get("scene") or 0): n for n in board["nodes"] if n.get("scene_of") == sid}
            speech = cfg.get("speech") or "character"
            for k, scene in enumerate(scenes, 1):
                title = f"Cảnh {k} · {scene.get('noi_dung') or ''}"[:60]
                use = chosen(scene)[:MAX_INPUTS - 1]
                if k in mine:  # giữ model / thời lượng bạn đã đổi; cập nhật tên + vật liệu theo storyboard mới
                    n = mine[k]
                    keep = [i for i in n.get("inputs") or [] if i != sid and i not in every]  # dây bạn tự nối thêm
                    n.update(title=title, inputs=[sid, *use, *keep][:MAX_INPUTS])
                    if speech != "none" and not n.get("dialogue_src") and not str(n.get("dialogue") or "").strip():
                        n.update(dialogue_src=sid, voice="narrator" if speech == "narrator" else "")
                    touched.append(n["id"])
                    continue
                n = self._new_node(board, "video", sb["x"] + self.SCENE_GAP_X, sb["y"] + (k - 1) * self.SCENE_GAP_Y,
                                   [sid, *use], "")
                n.update(title=title, scene=k, scene_of=sid, prompt_src=sid, first_frame=False,
                         aspect=cfg.get("aspect") or n["aspect"], duration=cfg.get("duration") or n["duration"])
                if speech != "none":  # mặc định: lời thoại của đúng cảnh lấy từ storyboard
                    n.update(dialogue_src=sid, voice="narrator" if speech == "narrator" else "")
                self._fit_options(n)
                mine[k] = n
                created.append(n["id"])
            joined = next((n for n in board["nodes"] if n.get("concat_of") == sid), None)
            order = [mine[k]["id"] for k in sorted(mine) if k <= len(scenes)]
            if joined is None:
                joined = self._new_node(board, "wf", sb["x"] + 2 * self.SCENE_GAP_X, sb["y"], order, "", "concat_video")
                joined.update(title="Ghép các cảnh", concat_of=sid)
                joined["config"]["aspect"] = cfg.get("aspect") if cfg.get("aspect") in ("9:16", "16:9", "1:1") else "9:16"
                created.append(joined["id"])
            else:  # cảnh mới nối thêm vào khối Ghép, giữ đúng thứ tự cảnh 1 → N (dây khác của bạn giữ nguyên)
                others = [i for i in joined.get("inputs") or [] if i not in {n["id"] for n in mine.values()}]
                joined["inputs"] = (order + others)[:MAX_INPUTS]
                touched.append(joined["id"])
        board = self._edit(bid, apply)
        for nid in [*created, *touched]:  # node mới → UI thêm vào bảng; node cũ → UI cập nhật tên / dây
            self.emit("canvas_node", {"board": bid, "node": self.public_node(bid, self._node(board, nid))})
        if created:
            self.pool.log(f"Storyboard {sid}: đã tách {sum(1 for i in created if self._node(board, i)['kind'] == 'video')} "
                          "node Video theo cảnh" + (" + khối Ghép các cảnh" if any(
                              self._node(board, i)["kind"] == "wf" for i in created) else ""), "ok")
        self._extend_flow(bid, sid, created)
        return created

    def _extend_flow(self, bid: str, sid: str, new: list) -> None:
        """Lượt Chạy toàn bộ / Chạy từ đây đang chạy → node vừa tách chạy luôn: node cảnh chèn trước khối Ghép (nếu khối
        Ghép đã nằm trong lượt), không thì nối vào cuối."""
        live = self._live.get(bid)
        if not live or not new:
            return
        rid, order = live
        board = self.load(bid)
        task = self._node(board, sid).get("task") or ""  # tác vụ của lượt chạy (node trong lượt dùng chung)
        concat = next((n["id"] for n in board["nodes"] if n.get("concat_of") == sid and n["id"] in order), None)
        for nid in new:
            if nid in order:
                continue
            if concat is not None and self._node(board, nid)["kind"] == "video":
                order.insert(order.index(concat), nid)
            else:
                order.append(nid)
            self._set_node(bid, nid, status="queued", pct=0, error="", task=task)
            self._run_record(bid, rid, node=(nid, "queued"))

    # ------------------------------------------------------------------ chạy cả quy trình (như Workflow)
    @staticmethod
    def _topo(board: dict) -> list[str]:
        """Thứ tự chạy: node phía trước chạy trước; cùng lúc sẵn sàng thì trái → phải, trên → dưới."""
        nodes = {n["id"]: n for n in board["nodes"]}
        kids = {nid: [] for nid in nodes}
        need = {}
        for n in nodes.values():
            ins = [i for i in n.get("inputs") or [] if i in nodes]
            need[n["id"]] = len(ins)
            for i in ins:
                kids[i].append(n["id"])
        pos = lambda nid: (nodes[nid]["x"], nodes[nid]["y"])  # noqa: E731
        ready, out = sorted((k for k, v in need.items() if v == 0), key=pos), []
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for k in kids[cur]:
                need[k] -= 1
                if need[k] == 0:
                    ready.append(k)
            ready.sort(key=pos)
        return out

    @staticmethod
    def _related(board: dict, nid: str, up: bool) -> set:
        """Mọi node phía trước (up) hoặc phía sau của nid."""
        nodes = {n["id"]: n for n in board["nodes"]}
        seen, stack = set(), [nid]
        while stack:
            cur = stack.pop()
            nxt = nodes[cur]["inputs"] if up else [n["id"] for n in nodes.values() if cur in (n.get("inputs") or [])]
            for x in nxt:
                if x in nodes and x not in seen:
                    seen.add(x)
                    stack.append(x)
        return seen

    def _sig(self, board: dict, nid: str, memo: dict | None = None) -> str:
        """Dấu vân tay node = cấu hình + prompt + model + dấu của node phía trước và kết quả chúng đưa sang.
        Không đổi → lần chạy quy trình sau dùng lại kết quả, không tạo lại (không tốn lượt)."""
        memo = {} if memo is None else memo
        if nid in memo:
            return memo[nid]
        node = next(n for n in board["nodes"] if n["id"] == nid)
        keys = ("kind", "wtype", "prompt", "engine", "aspect", "count", "duration", "resolution", "first_frame", "config",
                "dialogue", "voice", "dialogue_src", "auto_post", "prompt_src", "scene")
        ins = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src is not None:
                ins.append([self._sig(board, iid, memo), src.get("files"), src.get("pick"),
                            (src.get("out") or {}).get("text")])
        raw = json.dumps([{k: node.get(k) for k in keys}, node.get("files") if node["kind"] == "upload" else None, ins],
                         sort_keys=True, ensure_ascii=False, default=str)
        memo[nid] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return memo[nid]

    def _mark_sig(self, bid: str, nid: str) -> None:
        def apply(board):
            node = next((n for n in board["nodes"] if n["id"] == nid), None)
            if node is not None:
                node["sig"] = self._sig(board, nid)
        try:
            self._edit(bid, apply)
        except CanvasError:
            pass

    @staticmethod
    def _passive(node: dict) -> bool:
        """Node không cần chạy: ảnh tải lên, Văn bản (đưa thẳng chữ đang gõ sang node sau)."""
        return node["kind"] == "upload" or node.get("wtype") == "input_text"

    def plan(self, board: dict, mode: str = "all", target: str = "", fresh: bool = False, targets: list | None = None) -> dict:
        """Kế hoạch chạy: {run: [node chạy thật theo thứ tự], reuse: [node dùng lại kết quả], scope: [mọi node liên quan]}.
        mode = all | to (chạy đến target: node phía trước + target) | from (target + node phía sau)
        | set (làm lại các node targets + node phía sau chúng — BỎ khối đăng bài / lên lịch / quảng cáo)."""
        if mode not in ("all", "to", "from", "set"):
            raise CanvasError("Kiểu chạy không hợp lệ")
        nodes = {n["id"]: n for n in board["nodes"]}
        if mode == "set":
            targets = [t for t in targets or [] if t in nodes]
            if not targets:
                raise CanvasError("Chưa có khối nào để làm lại")
            scope = set(targets).union(*(self._related(board, t, False) for t in targets))
            scope = {nid for nid in scope if nodes[nid].get("wtype") not in POST_TYPES}
            target = ""
        elif mode != "all":
            self._node(board, target)
        if mode != "set":
            scope = (set(n["id"] for n in board["nodes"]) if mode == "all" else
                     self._related(board, target, True) | {target} if mode == "to" else
                     self._related(board, target, False) | {target})
        memo, run, reuse = {}, [], []
        for nid in self._topo(board):
            if nid not in scope:
                continue
            node = nodes[nid]
            if self._passive(node):
                continue
            upstream_runs = any(i in run for i in node.get("inputs") or [])
            changed = node.get("status") != "done" or node.get("sig") != self._sig(board, nid, memo)
            if fresh or upstream_runs or changed or (mode in ("to", "from") and nid == target) or mode == "from" \
                    or (mode == "set" and nid in targets):
                run.append(nid)
            else:
                reuse.append(nid)
        return {"run": run, "reuse": reuse, "scope": sorted(scope)}

    def check(self, board: dict, ids: list) -> list:
        """Lỗi / cảnh báo trước khi chạy (như Workflow): [{node, level: error|warn, message}]."""
        issues = []
        nodes = {n["id"]: n for n in board["nodes"]}
        add = lambda nid, level, msg: issues.append({"node": nid, "level": level, "message": msg})  # noqa: E731
        for nid in ids:
            n = nodes[nid]
            srcs = [nodes[i] for i in n.get("inputs") or [] if i in nodes]
            got = set().union(*(out_types(x) for x in srcs)) if srcs else set()
            psrc = self._prompt_src(n)
            own = self._own_prompt(n)
            text_in = False if psrc == "own" else "text" in out_types(nodes[psrc]) if psrc else "text" in got
            if n["kind"] == "image" and not own and not text_in:
                add(nid, "error", "Ảnh chưa có prompt (viết prompt, hoặc nối khối chữ vào làm prompt)")
            elif n["kind"] == "video" and not ({"images", "video"} & got) and not text_in and not own:
                add(nid, "error", "Video chưa có ảnh / video đầu vào hoặc prompt")
            scene_src = nodes.get(n.get("scene_of") or "")
            if n["kind"] == "video" and scene_src is not None and scene_src.get("status") == "done" \
                    and self._scene_for(scene_src, n) == {} and scene_src["id"] not in ids:
                add(nid, "error", f"Storyboard {scene_src['id']} không còn cảnh {n.get('scene')} — xoá node này hoặc viết lại storyboard")
            spoken = self._dialogue_text(board["id"], board, n) if n["kind"] == "video" else ""
            if n["kind"] == "video" and n.get("dialogue_src") and not spoken:
                src = nodes.get(n["dialogue_src"])
                if src is not None and src.get("status") != "done" and src.get("wtype") != "input_text" \
                        and src["id"] not in ids:
                    add(nid, "warn", f"Lời thoại lấy từ {src['id']} nhưng khối đó chưa có chữ — chạy nó trước (hoặc chạy cả quy trình)")
            if n["kind"] == "video" and spoken.strip():
                words, limit = dialogue_words({"dialogue": spoken}), dialogue_limit(n)
                if words > limit:
                    add(nid, "warn", f"Lời thoại {words} chữ — dài so với clip {n.get('duration')} (nên ≤ {limit} chữ), dễ nói vội / bị cắt")
            elif n["kind"] == "wf":
                cfg, kind = n.get("config") or {}, n["wtype"]
                if kind in ("fb_post", "fb_schedule") and not cfg.get("page_id"):
                    add(nid, "error", "Chưa chọn Fanpage")
                if kind in ("fb_post", "fb_schedule") and not srcs and not str(cfg.get("caption") or "").strip():
                    add(nid, "error", "Chưa có gì để đăng — nối chữ (caption) và / hoặc ảnh / video vào")
                if kind == "fb_ad":
                    if not cfg.get("account_id"):
                        add(nid, "error", "Chưa chọn tài khoản quảng cáo")
                    if "post" not in got:
                        add(nid, "error", "Nối khối Đăng bài Facebook vào khối Tạo quảng cáo")
                if kind == "concat_video" and "video" not in got:
                    add(nid, "error", "Ghép video chưa có video đầu vào")
                if kind == "dub_vieneu" and "video" not in got:
                    add(nid, "error", "Lồng tiếng chưa có video — nối node Video / Ghép video / Video đầu vào vào")
                if kind == "dub_vieneu" and "text" not in got and not str(cfg.get("script") or "").strip() \
                        and cfg.get("script_mode") != "analyze":  # phân tích video → model tự viết lời đọc
                    add(nid, "error", "Lồng tiếng chưa có lời đọc — nhập lời đọc hoặc nối khối chữ vào")
                if kind == "dub_vieneu":
                    from .pipeline import vieneu_tts

                    st = vieneu_tts.status()
                    if not st["python"]:
                        add(nid, "error", "Chưa có Python 3.10+ trên máy để cài VieNeu (python.org)")
                    elif not st["installed"]:
                        add(nid, "warn", "Lần chạy đầu app sẽ cài VieNeu-TTS + tải model (cần internet, vài phút)")
                if kind == "post_video" and "video" not in got:
                    add(nid, "error", "Hậu kỳ video chưa có video — nối node Video / Ghép video / Video đầu vào vào")
                style = cfg.get("post_style", "remotion")
                if kind == "post_video" and cfg.get("post_ai", True) and style == "hyperframes":
                    from .pipeline import hyperframes as hfm

                    st = hfm.status()
                    if not (st.get("node_ok") and st.get("ffprobe")):
                        add(nid, "warn", "HyperFrames cần Node.js 22+ và ffprobe trên máy — chưa có thì app tự dùng phụ đề nổi bật thường")
                if kind == "post_video" and cfg.get("post_ai", True) and style == "remotion":
                    from .pipeline import remotion_post

                    st = remotion_post.status()
                    if not st.get("node_ok"):
                        add(nid, "warn", "Remotion cần Node.js 18+ trên máy — chưa có thì app tự dùng phụ đề nổi bật thường")
                    elif not st.get("installed"):
                        add(nid, "warn", "Lần chạy đầu app sẽ cài Remotion (cần internet, ~1–3 phút)")
                if kind == "ai_text" and not str(cfg.get("prompt") or "").strip():
                    add(nid, "error", "AI viết chưa có yêu cầu")
                if kind == "content_post" and not text_in and not (str(cfg.get("sp_name") or "").strip()
                                                                  and str(cfg.get("sp_benefits") or "").strip()):
                    add(nid, "error", "Tạo content: nhập Tên sản phẩm + Công dụng, hoặc nối chữ thông tin sản phẩm vào")
                if kind == "studio_video" and not text_in and not str(cfg.get("idea") or "").strip():
                    add(nid, "error", "Video dài chưa có ý tưởng")
                if kind == "storyboard_video" and not text_in and len(str(cfg.get("request") or "").strip()) < 10:
                    add(nid, "error", "Storyboard → Video chưa có yêu cầu (nhập hoặc nối khối chữ vào)")
                if kind == "whiteboard_video" and not text_in and not str(cfg.get("text") or "").strip() \
                        and not cfg.get("srt"):
                    add(nid, "error", "Whiteboard chưa có SRT / kịch bản")
                if kind == "input_video" and not cfg.get("files"):
                    add(nid, "error", "Chưa chọn video")
                if kind == "output" and not srcs:
                    add(nid, "warn", "Khối Kết quả chưa nối gì vào")
        feeding = {i for nid in ids for i in nodes[nid].get("inputs") or []}
        for n in nodes.values():  # ảnh đầu vào chưa có ảnh mà node phía sau cần dùng
            if n["kind"] == "upload" and n["id"] in feeding and not n.get("files"):
                add(n["id"], "error", "Ảnh đầu vào chưa có ảnh — bấm ⬆ Chọn ảnh, hoặc bật ❓ Hỏi khi chạy")
        for n in nodes.values():  # Văn bản rỗng mà có node phía sau dùng
            if n.get("wtype") == "input_text" and not str((n.get("config") or {}).get("text") or "").strip() \
                    and any(n["id"] in (nodes[i].get("inputs") or []) for i in ids):
                add(n["id"], "error", "Văn bản đang trống")
        return issues

    def preview(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False) -> dict:
        board = self.load(bid)
        plan = self.plan(board, mode, target, fresh)
        nodes = {n["id"]: n for n in board["nodes"]}
        scope = set(plan["scope"])
        # ❓ hỏi khi chạy: mọi khối bật "Hỏi khi chạy" (sửa prompt / cấu hình / chọn file) + ảnh đầu vào chưa có ảnh
        ask = [nid for nid in self._topo(board) if nid in scope and (
            nodes[nid].get("ask") or (nodes[nid]["kind"] == "upload" and not nodes[nid].get("files")) or
            (nodes[nid].get("wtype") == "input_video" and (nodes[nid].get("config") or {}).get("ask")))]
        return {**plan, "ask": ask, "issues": self.check(board, plan["run"]),
                "posts": [nid for nid in plan["run"]
                          if nodes[nid].get("wtype") in ("fb_post", "fb_schedule", "fb_ad") and not nodes[nid].get("auto_post")],
                "auto_posts": [nid for nid in plan["run"]
                               if nodes[nid].get("wtype") in ("fb_post", "fb_schedule") and nodes[nid].get("auto_post")]}

    def run_flow(self, bid: str, mode: str = "all", target: str = "", fresh: bool = False, *, targets: list | None = None,
                 origin: str = "", round_no: int = 0, label: str = "") -> dict:
        """Chạy quy trình trong 1 tác vụ: lần lượt từng node theo thứ tự; node lỗi → bỏ qua nhánh phía sau nó,
        nhánh khác chạy tiếp; đăng bài vẫn dừng chờ duyệt. origin = "autopilot" khi trợ lý Claude giao làm lại (vòng round_no)."""
        with self._lock:
            board = self.load(bid)
            if any(n.get("status") in ACTIVE for n in board["nodes"]):
                raise CanvasError("Đang có node chạy — chờ xong hoặc bấm Dừng")
            plan = self.plan(board, mode, target, fresh, targets)
            errors = [i for i in self.check(board, plan["run"]) if i["level"] == "error"]
            if errors:
                raise CanvasError("Quy trình còn lỗi: " + "; ".join(f"{i['node']}: {i['message']}" for i in errors[:4]))
            if not plan["run"]:
                raise CanvasError("Không có node nào cần chạy — mọi kết quả đã mới nhất (bấm “Chạy lại tất cả” để tạo lại)")
            runs = board.setdefault("runs", [])
            board["run_seq"] = int(board.get("run_seq") or 0) + 1
            rid = f"r{board['run_seq']}"
            label = label or {"all": "Chạy toàn bộ", "to": f"Chạy đến {target}", "from": f"Chạy từ {target}",
                              "set": "Làm lại " + ", ".join(targets or [])}[mode]
            record = {"id": rid, "label": label + (" (làm lại từ đầu)" if fresh else ""), "at": now(), "ended": "",
                      "status": "running", "nodes": {nid: "queued" for nid in plan["run"]},
                      "reused": plan["reuse"], "current": "",
                      **({"origin": origin, "round": int(round_no)} if origin else {})}
            self._grow[bid] = mode in ("all", "from")  # node Storyboard tách cảnh giữa chừng → chạy luôn trong lượt này
            task = self.pool.submit(f"Canvas · {board['name']} · {label}", self._flow, bid, rid, plan["run"],
                                    meta={"board": bid, "flow": rid})
            record["task"] = task
            board["runs"] = (runs + [record])[-MAX_RUNS:]
            for nid in plan["run"]:
                self._node(board, nid).update(status="queued", pct=0, error="", task=task)
            self._save(board)
        self.emit("canvas_flow", {"board": bid, "run": record})
        return self.public(self.load(bid))

    def _run_record(self, bid: str, rid: str, **fields) -> dict:
        holder = {}

        def apply(board):
            rec = next((r for r in board.get("runs") or [] if r["id"] == rid), None)
            if rec is not None:
                for k, v in fields.items():
                    if k == "node":
                        rec["nodes"][v[0]] = v[1]
                    else:
                        rec[k] = v
                holder["rec"] = dict(rec)
        try:
            self._edit(bid, apply)
        except CanvasError:
            return {}
        if holder.get("rec"):
            self.emit("canvas_flow", {"board": bid, "run": holder["rec"]})
        return holder.get("rec") or {}

    def _flow(self, bid: str, rid: str, order: list) -> dict:
        bad: set = set()  # node lỗi / bị bỏ qua trong lần chạy này → node phía sau cũng bỏ qua
        total = len(order)
        if self._grow.pop(bid, False):
            self._live[bid] = (rid, order)
        try:
            for i, nid in enumerate(order):
                self.pool.check_cancel()
                board = self.load(bid)
                node = next((n for n in board["nodes"] if n["id"] == nid), None)
                if node is None:
                    continue
                if any(x in bad for x in node.get("inputs") or []):
                    bad.add(nid)
                    self._set_node(bid, nid, status="idle", pct=0, error="Bỏ qua — node phía trước lỗi / không chạy")
                    self._run_record(bid, rid, node=(nid, "skipped"))
                    continue
                self.pool.log(f"[{i + 1}/{max(total, len(order))}] {self.label(node)} {nid}")
                self._run_record(bid, rid, current=nid, node=(nid, "running"))
                try:
                    result = self._run_wf(bid, nid) if node["kind"] == "wf" else self._run(bid, nid)
                except Cancelled:
                    raise
                except Exception as exc:  # node lỗi: ghi lại, nhánh phía sau bỏ qua, nhánh khác chạy tiếp
                    self.pool.log(f"{nid} lỗi: {exc}", "error")
                    bad.add(nid)
                    self._run_record(bid, rid, node=(nid, "error"))
                    continue
                if (result or {}).get("skipped"):
                    bad.add(nid)
                    self._run_record(bid, rid, node=(nid, "skipped"))
                else:
                    self._run_record(bid, rid, node=(nid, "done"))
        except Cancelled:
            for nid in order:
                n = next((x for x in self.load(bid)["nodes"] if x["id"] == nid), None)
                if n and n.get("status") in ACTIVE:
                    self._set_node(bid, nid, status="idle", pct=0, error="Đã dừng", approval={}, stage="")
            self._run_record(bid, rid, status="cancelled", ended=now(), current="")
            raise
        finally:
            self._live.pop(bid, None)
        rec = self._run_record(bid, rid, ended=now(), current="")
        states = list((rec.get("nodes") or {}).values())
        status = "done" if all(x == "done" for x in states) else "error" if "error" in states else "partial"
        rec = self._run_record(bid, rid, status=status)
        if self.on_flow_done:  # trợ lý Claude tự điều phối: chấm kết quả lần chạy này (chạy nền, không chặn hàng đợi)
            try:
                self.on_flow_done(bid, rec or {"id": rid, "status": status})
            except Exception as exc:  # noqa: BLE001 — lỗi trợ lý không làm hỏng lần chạy
                self.pool.log(f"Trợ lý tự điều phối lỗi: {exc}", "warn")
        return {"board": bid, "run": rid, "status": status}

    def cancel_flow(self, bid: str) -> int:
        board = self.load(bid)
        tasks = {n.get("task") for n in board["nodes"] if n.get("status") in ACTIVE and n.get("task")}
        return sum(self.pool.cancel(t) for t in tasks)

    # ------------------------------------------------------------------ nhập Workflow / quy trình mẫu
    def _copy_upload(self, bid: str, board: dict, path: str, x: float, y: float) -> dict:
        node = self._new_node(board, "upload", x, y, [], "")
        rel = f"nodes/{node['id']}_up{Path(path).suffix.lower()}"
        shutil.copy2(path, self.root / bid / rel)
        node.update(title=Path(path).stem[:60], files=[rel], status="done", pct=100)
        return node

    def import_workflow(self, source: str, ref: str) -> dict:
        """Workflow đã lưu (source=workflow) hoặc quy trình mẫu (source=preset) → Canvas mới, giữ bố cục và dây nối.
        Tạo ảnh / Tạo video → node Ảnh / Video của Canvas; Ảnh đầu vào → node Tải lên (mỗi file 1 node)."""
        import copy

        from .workflow import nodes as wfn
        from .workflow import store as wfs

        if source == "preset":
            if ref not in wfs.PRESETS:
                raise CanvasError("Không có quy trình mẫu này")
            wf = copy.deepcopy(wfs.PRESETS[ref])
        else:
            try:
                wf = wfs.get(ref)
            except (wfs.WorkflowError, OSError) as exc:
                raise CanvasError(str(exc)) from exc
        bid = self.create(wf.get("name") or "Từ Workflow")["id"]
        notes, ids = [], {}
        xs = [n.get("x", 0) for n in wf.get("nodes") or []] or [0]
        ys = [n.get("y", 0) for n in wf.get("nodes") or []] or [0]
        place = lambda n: ((n.get("x", 0) - min(xs)) * 1.5, (n.get("y", 0) - min(ys)) * 1.7)  # noqa: E731

        def build(b):
            for n in wf.get("nodes") or []:
                cfg, kind = wfn.config_of(n), n["type"]
                x, y = place(n)
                if kind == "input_image":
                    files = [p for p in cfg.get("files") or [] if Path(p).is_file()][:6]
                    made = [self._copy_upload(bid, b, f, x, y + k * 380) for k, f in enumerate(files)]
                    if not made:  # chưa có ảnh: node ảnh đầu vào trống, hỏi chọn ảnh khi chạy quy trình
                        node = self._new_node(b, "upload", x, y, [], "")
                        node.update(title=cfg.get("label") or "Ảnh đầu vào", ask=True)
                        made.append(node)
                    for node in made:  # Workflow "Hỏi lại khi chạy" → ❓ hỏi chọn ảnh mỗi lần chạy
                        node["ask"] = bool(cfg.get("ask")) or not node.get("files")
                    ids[n["id"]] = [node["id"] for node in made]
                    continue
                if kind == "gen_image":
                    node = self._new_node(b, "image", x, y, [], str(cfg.get("prompt") or ""))
                    node.update(engine=cfg.get("engine") or node["engine"], aspect=cfg.get("aspect") or node["aspect"],
                                count=int(cfg.get("count") or 1))
                    if cfg.get("pinterest"):
                        notes.append(f"{node['id']}: Canvas chưa tìm ảnh Pinterest — tải ảnh tham khảo lên rồi nối vào")
                    refs = [p for p in cfg.get("refs") or [] if Path(p).is_file()][:4]
                    node["inputs"] += [self._copy_upload(bid, b, f, x - 400, y + k * 380)["id"] for k, f in enumerate(refs)]
                elif kind == "gen_video":
                    node = self._new_node(b, "video", x, y, [], str(cfg.get("prompt") or ""))
                    node.update(engine=cfg.get("engine") or node["engine"], aspect=cfg.get("aspect") or node["aspect"],
                                duration=cfg.get("duration") or node["duration"],
                                resolution=cfg.get("resolution") or node["resolution"])
                    if cfg.get("template"):
                        notes.append(f"{node['id']}: Canvas tạo video bằng prompt tự do — template “{cfg['template']}” "
                                     "không được chuyển, hãy viết lại prompt")
                elif kind in WF_TYPES:
                    node = self._new_node(b, "wf", x, y, [], "", kind)
                    keep = {f["key"] for f in wf_types()[kind]["fields"]}
                    node["config"].update({k: v for k, v in cfg.items() if k in keep})
                else:
                    notes.append(f"Bỏ qua khối không hỗ trợ: {n['type']}")
                    continue
                self._fit_options(node)
                ids[n["id"]] = [node["id"]]
            nodes = {x["id"]: x for x in b["nodes"]}
            for e in wf.get("edges") or []:
                for dst in ids.get(e.get("to"), []):
                    for src in ids.get(e.get("from"), []):
                        target = nodes[dst]
                        if src not in target["inputs"] and out_types(nodes[src]) & in_types(target) \
                                and len(target["inputs"]) < MAX_INPUTS:
                            target["inputs"].append(src)
        board = self._edit(bid, build)
        return {"board": self.public(board), "notes": notes}

    def sources(self) -> dict:
        """Workflow đã lưu + quy trình mẫu để nhập vào Canvas."""
        from .workflow import store as wfs

        return {"workflows": [{"id": w["id"], "name": w.get("name", ""), "nodes": w.get("nodes", 0)}
                              for w in wfs.list_workflows()], "presets": wfs.presets()}

    # ------------------------------------------------------------------ công cụ
    def upscale(self, bid: str, nid: str) -> dict:
        """Phóng to 2× trên máy (ffmpeg lanczos + làm nét nhẹ) → node ảnh mới nối từ node này. Không tốn lượt model."""
        src = self.file_of(bid, nid)
        node = self._node(self.load(bid), nid)
        if node["kind"] == "video":
            raise CanvasError("Chỉ phóng to được ảnh")
        w, h = ffmpeg.video_size(src)
        k = min(2.0, MAX_UPSCALE_SIDE / max(w, h))
        if k <= 1.01:
            raise CanvasError(f"Ảnh đã lớn ({w}×{h}) — không cần phóng thêm")
        nw, nh = round(w * k) // 2 * 2, round(h * k) // 2 * 2
        holder = {}

        def add(board):
            new = self._new_node(board, "upload", node["x"] + 300, node["y"], [], "")
            rel = f"nodes/{new['id']}_x2.png"
            ffmpeg.run(["-i", src, "-vf", f"scale={nw}:{nh}:flags=lanczos,unsharp=5:5:0.5:5:5:0", "-frames:v", "1",
                        self.root / bid / rel])
            new.update(title=f"Phóng to {nw}×{nh}", files=[rel], status="done", pct=100, source=nid)
            holder["node"] = new
        try:
            board = self._edit(bid, add)
        except ffmpeg.FFmpegError as exc:
            raise CanvasError(f"Phóng to lỗi: {exc}") from exc
        return self._result(bid, board, holder["node"]["id"])

    def enhance(self, bid: str, nid: str, model: str = "") -> str:
        """✨ Viết lại prompt bằng model chữ (chạy nền — model trình duyệt mất 1–2 phút). Trả mã tác vụ."""
        node = self._node(self.load(bid), nid)
        if not (node.get("prompt") or "").strip():
            raise CanvasError("Viết vài chữ ý tưởng trước rồi bấm ✨")
        model = model or meta(self.settings)["defaults"]["text"]
        self._set_node(bid, nid, stage="Đang viết lại prompt…")
        return self.pool.submit("Canvas · viết lại prompt", self._enhance, bid, nid, model,
                                meta={"board": bid, "node": nid})

    def _enhance(self, bid: str, nid: str, model: str) -> dict:
        from .studio import ask_model

        try:
            node = self._node(self.load(bid), nid)
            video = node["kind"] == "video"
            system = ENHANCE_SYSTEM.format(what="video từ ảnh" if video else "ảnh",
                                           motion=", chuyển động theo mốc giây, máy quay" if video else "")
            text = ask_model(self.settings, {"model": model, "timeout": 240,
                                             "text_profile": model_prefs.get(self.settings).get("model_text_profile", "")},
                             f"Prompt người dùng:\n{node['prompt']}", what="viết lại prompt", log=self.pool.log,
                             check_cancel=self.pool.check_cancel, system=system)
            text = " ".join(str(text or "").strip().strip('"').split())[:4000]
            if not text:
                raise CanvasError("Model không trả prompt")
        except Exception:
            self._set_node(bid, nid, stage="")
            raise
        self._set_node(bid, nid, prompt=text, stage="")
        return {"board": bid, "node": nid, "prompt": text}
