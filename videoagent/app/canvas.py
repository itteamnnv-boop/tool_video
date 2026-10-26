"""Canvas — bảng node kiểu Kling Canvas: node Ảnh (prompt → model ảnh, ảnh nối vào = ảnh tham chiếu để sửa / ghép),
node Video (ảnh nối vào = khung đầu → model video), node Tải lên (ảnh của người dùng). Mỗi bảng lưu ở
<output_dir>/_canvas/<id>/board.json, file của node ở nodes/ (UI xem qua /media/_canvas/...).
Tạo ảnh / video dùng chung ImageRunner / JobRunner của app (đúng model, profile, giới hạn song song đã cài)."""
from __future__ import annotations  # CanvasRunner.list() che tên kiểu list trong chú thích kiểu

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
EDITABLE = ("x", "y", "title", "prompt", "engine", "aspect", "count", "duration", "resolution", "pick", "first_frame")
VIDEO_REF_SLOTS = ("ref1", "ref2", "ref3", "ref4", "ref5")  # ô ảnh tham chiếu của template canvas-video
# block của Workflow dùng được trên Canvas (chạy bằng chính workflow.nodes.run_node). Tạo ảnh / video là node riêng.
WF_TYPES = ("input_text", "ai_text", "content_post", "input_video", "concat_video", "studio_video", "whiteboard_video",
            "fb_post", "fb_schedule", "fb_ad")
WF_HIDDEN = {"sources", "confirm", "ask", "label"}  # Canvas nối dây thay "tài nguyên từ flow"; đăng bài LUÔN chờ duyệt
ACTIVE = ("queued", "running", "waiting")
ENHANCE_SYSTEM = ("Bạn viết prompt cho model tạo {what}. Viết lại prompt người dùng thành MỘT đoạn prompt tiếng Anh "
                  "rõ ràng, cụ thể (chủ thể, hành động, bối cảnh, ánh sáng, góc máy{motion}), màu tươi sáng tự nhiên, "
                  "da người giữ kết cấu thật, không làm mịn. Giữ nguyên ý và mọi chữ / tên sản phẩm người dùng ghi. "
                  "Chỉ trả về đoạn prompt, không giải thích.")


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
        "defaults": {"image": prefs["model_image"] if prefs["model_image"] in IMAGE_ENGINES else "openai_api",
                     "video": prefs["model_video"] if prefs["model_video"] in VIDEO_ENGINES else "grok_browser",
                     "text": prefs["model_text"]},
    }


def wf_types() -> dict:
    """Block Workflow trên Canvas: cổng vào / ra + ô cấu hình (bỏ các ô Canvas không dùng)."""
    from .workflow import nodes as wfn

    return {k: {"name": s["name"], "icon": s["icon"], "desc": s["desc"], "group": s["group"], "inputs": s["inputs"],
                "outputs": s["outputs"], "fields": [f for f in s["fields"] if f["key"] not in WF_HIDDEN]}
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

    out = set()
    for p in wfn.NODE_TYPES[node["wtype"]]["inputs"]:
        out |= {"images", "video"} if p["type"] == "any" else {p["type"]}
    return out


class CanvasRunner:
    def __init__(self, settings, emit, images=None, videos=None, facebook=None, ads=None, studio=None) -> None:
        self.settings = settings
        self.emit = emit
        self.images = images
        self.videos = videos
        self.facebook, self.ads, self.studio = facebook, ads, studio  # block Đăng bài / Quảng cáo / Video dài
        self.pool = TaskPool("canvas_", emit, lambda: settings.get("max_parallel_canvas") or 4)
        self._lock = threading.RLock()
        self._approvals: dict[tuple, dict] = {}  # (bảng, node) → {"event", "decision"} — đăng bài chờ duyệt

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
            out.append({"id": b["id"], "name": b["name"], "updated_at": b.get("updated_at", ""),
                        "nodes": len(b["nodes"]), "thumb": thumb})
        return sorted(out, key=lambda x: x["updated_at"], reverse=True)

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
                        config={k: v for k, v in wfn.defaults(wtype).items() if k not in WF_HIDDEN})
        elif kind != "upload":
            node.update(self._defaults(kind))
        board["nodes"].append(node)
        return node

    def _result(self, bid: str, board: dict, nid: str) -> dict:
        return {"board": self.public(board), "node": self.public_node(bid, self._node(board, nid))}

    def add_node(self, bid: str, kind: str, x: float = 0, y: float = 0, inputs: list | None = None,
                 prompt: str = "", wtype: str = "") -> dict:
        if kind not in ("image", "video", "wf") or (kind == "wf" and wtype not in WF_TYPES):
            raise CanvasError("Loại node không hợp lệ")
        holder = {}
        board = self._edit(bid, lambda b: holder.update(node=self._new_node(b, kind, x, y, inputs or [], prompt, wtype)))
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
        """Chữ từ node nối vào (AI viết prompt, Văn bản…) — thêm vào đầu prompt ảnh / video."""
        texts = []
        for iid in node.get("inputs") or []:
            src = next((n for n in board["nodes"] if n["id"] == iid), None)
            if src and src["kind"] == "wf":
                text = str(self._outputs(bid, src).get("text") or "").strip()
                if text:
                    texts.append(text)
        return "\n\n".join(texts)

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
            if node["kind"] == "video" and not (refs or self._input_videos(bid, board, node)):
                raise CanvasError("Nối ít nhất 1 ảnh hoặc video vào node Video trước khi tạo")
            if node["kind"] == "image" and not ((node.get("prompt") or "").strip() or text_in):
                raise CanvasError("Viết prompt cho ảnh (hoặc nối node chữ vào)")
            if node["kind"] == "image" and refs and IMAGE_ENGINES[node["engine"]]["max_images"] < 1:
                raise CanvasError(f"{IMAGE_ENGINES[node['engine']]['name']} không nhận ảnh tham chiếu — đổi model "
                                  "hoặc bỏ nối")
            what = "Video" if node["kind"] == "video" else "Ảnh"
            task = self.pool.submit(f"Canvas · {what} — {(node.get('prompt') or text_in)[:60]}", self._run, bid, nid,
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
            prompt = "\n\n".join(x for x in (self._input_text(bid, board, node), (node.get("prompt") or "").strip()) if x)
            if node["kind"] == "video":
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
                "identical.")
        motion = prompt or ("Bring this image to life with natural, subtle motion; keep every person, product and "
                            "detail exactly as in the image.")
        task = self.videos.start({
            "template": VIDEO_TEMPLATE, "provider": node["engine"], "ai_duration": node["duration"],
            "ai_aspect": node["aspect"], "ai_resolution": node["resolution"],
            "variables": {"KhungDau": lead, "MoTa": motion},
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

        # đăng bài luôn chờ duyệt; Canvas nối dây nên không dùng "tài nguyên từ flow"
        wnode = {"id": nid, "type": node["wtype"], "config": {**(node.get("config") or {}), "confirm": True, "sources": []}}
        services = {"facebook": self.facebook, "ads": self.ads, "studio": self.studio,
                    "workflow_name": f"Canvas · {board['name']}",
                    "approve": lambda payload: self._wait_approval(bid, nid, payload)}
        ctx = wfn.NodeContext(self.settings, self.root / bid / "runs", wnode, self.pool.log, self.pool.check_cancel,
                              progress, services)
        try:
            result = wfn.run_node(ctx, self._wf_inputs(bid, board, node, spec))
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
            elif key == "post" and isinstance(value, dict):
                out["post"] = value
                where = value.get("url") or value.get("post_id") or ""
                out["text"] = (f"{'Đã lên lịch ' + value.get('when', '') if value.get('scheduled') else 'Đã đăng'} lên "
                               f"“{value.get('page', '')}”" + (f": {where}" if where else ""))
        self._drop_old(bid, node)
        self._set_node(bid, nid, status="done", pct=100, error="", out=out, files=files, pick=0, stage="", approval={})
        return {"board": bid, "node": nid}

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
