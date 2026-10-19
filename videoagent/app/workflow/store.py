"""Lưu workflow (DATA_DIR/workflows/<id>.json), mẫu dựng sẵn và lịch sử lần chạy (<thư mục video>/_workflows/<id>/<lần chạy>/)."""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from ..paths import DATA_DIR
from ..util import slugify
from .nodes import NODE_TYPES, defaults

WF_DIR = DATA_DIR / "workflows"
_lock = threading.Lock()


class WorkflowError(RuntimeError):
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _path(wf_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{3,80}", wf_id or ""):
        raise WorkflowError("Mã workflow không hợp lệ")
    return WF_DIR / f"{wf_id}.json"


def _node(nid, kind, x, y, **config):
    return {"id": nid, "type": kind, "x": x, "y": y, "config": {**defaults(kind), **config}}


def _edge(a, out, b, inp):
    return {"from": a, "out": out, "to": b, "in": inp}


PRESETS = {
    "anh-thanh-video": {
        "name": "Ảnh → Video", "desc": "Ảnh sản phẩm/nhân vật + prompt → Grok Imagine tạo video 9:16",
        "nodes": [_node("n1", "input_image", 60, 60, label="Ảnh sản phẩm"),
                  _node("n2", "input_text", 60, 300, label="Prompt video",
                        text="Cô gái cầm sản phẩm giới thiệu trên cánh đồng lúa, ánh nắng sớm, máy quay lia chậm"),
                  _node("n3", "gen_video", 420, 160),
                  _node("n4", "output", 780, 190, name="video")],
        "edges": [_edge("n1", "images", "n3", "images"), _edge("n2", "text", "n3", "prompt"), _edge("n3", "video", "n4", "items")],
    },
    "y-tuong-anh-video": {
        "name": "Ý tưởng → AI → Ảnh → Video", "desc": "AI viết prompt từ ý tưởng, vẽ ảnh bìa rồi dựng video từ ảnh đó",
        "nodes": [_node("n1", "input_text", 40, 60, label="Ý tưởng / sản phẩm", text="Phân bón NPK giúp lúa xanh tốt, bông chắc hạt"),
                  _node("n2", "input_image", 40, 320, label="Ảnh sản phẩm"),
                  _node("n3", "ai_text", 360, 60),
                  _node("n4", "gen_image", 680, 300, prompt="ảnh dọc 9:16, có người mẫu cầm sản phẩm, ánh sáng tự nhiên"),
                  _node("n5", "gen_video", 1000, 80),
                  _node("n6", "output", 1320, 200, name="ket-qua")],
        "edges": [_edge("n1", "text", "n3", "text"), _edge("n2", "images", "n3", "images"), _edge("n3", "text", "n4", "prompt"),
                  _edge("n2", "images", "n4", "images"), _edge("n4", "images", "n5", "images"), _edge("n3", "text", "n5", "prompt"),
                  _edge("n4", "images", "n6", "items"), _edge("n5", "video", "n6", "items")],
    },
    "hai-canh-ghep": {
        "name": "2 cảnh → Ghép video", "desc": "AI viết 2 cảnh, tạo 2 video rồi ghép thành 1 video dài",
        "nodes": [_node("n1", "input_text", 40, 200, label="Nội dung quảng cáo", text="Giới thiệu phân bón hữu cơ cho rau sạch"),
                  _node("n2", "ai_text", 360, 40, prompt="Viết prompt video cảnh MỞ ĐẦU (nêu vấn đề) cho: {{input}}. Chỉ trả về prompt."),
                  _node("n3", "ai_text", 360, 360, prompt="Viết prompt video cảnh KẾT (giải pháp + kêu gọi mua) cho: {{input}}. Chỉ trả về prompt."),
                  _node("n4", "gen_video", 680, 40), _node("n5", "gen_video", 680, 360),
                  _node("n6", "concat_video", 1000, 200), _node("n7", "output", 1300, 220, name="video-ghep")],
        "edges": [_edge("n1", "text", "n2", "text"), _edge("n1", "text", "n3", "text"), _edge("n2", "text", "n4", "prompt"),
                  _edge("n3", "text", "n5", "prompt"), _edge("n4", "video", "n6", "videos"), _edge("n5", "video", "n6", "videos"),
                  _edge("n6", "video", "n7", "items")],
    },
}


def presets() -> list:
    return [{"id": k, "name": v["name"], "desc": v["desc"], "nodes": len(v["nodes"])} for k, v in PRESETS.items()]


def list_workflows() -> list:
    WF_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for path in WF_DIR.glob("*.json"):
        try:
            wf = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        nodes = sorted(wf.get("nodes", []), key=lambda n: (n.get("x", 0), n.get("y", 0)))
        out.append({"id": wf["id"], "name": wf.get("name", ""), "desc": wf.get("desc", ""), "nodes": len(nodes),
                    "edges": len(wf.get("edges", [])), "types": [n["type"] for n in nodes],
                    "created_at": wf.get("created_at"), "updated_at": wf.get("updated_at"), "last_run": wf.get("last_run")})
    return sorted(out, key=lambda w: w.get("updated_at") or "", reverse=True)


def get(wf_id: str) -> dict:
    path = _path(wf_id)
    if not path.exists():
        raise WorkflowError("Không tìm thấy workflow")
    return json.loads(path.read_text("utf-8"))


def clean(wf: dict) -> dict:
    """Chỉ giữ cấu trúc hợp lệ: block có kiểu đã biết, dây nối giữa 2 block tồn tại, không trùng."""
    nodes = []
    for n in wf.get("nodes") or []:
        if n.get("type") not in NODE_TYPES or not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", str(n.get("id", ""))):
            continue
        keys = {f["key"] for f in NODE_TYPES[n["type"]]["fields"]}
        nodes.append({"id": str(n["id"]), "type": n["type"], "x": round(float(n.get("x") or 0)), "y": round(float(n.get("y") or 0)),
                      "config": {k: v for k, v in (n.get("config") or {}).items() if k in keys}})
    ids = {n["id"] for n in nodes}
    edges, seen = [], set()
    for e in wf.get("edges") or []:
        key = (e.get("from"), e.get("out"), e.get("to"), e.get("in"))
        if e.get("from") in ids and e.get("to") in ids and e.get("from") != e.get("to") and key not in seen:
            seen.add(key)
            edges.append({"from": e["from"], "out": e["out"], "to": e["to"], "in": e["in"]})
    return {"nodes": nodes, "edges": edges}


def save(wf: dict) -> dict:
    name = str(wf.get("name") or "").strip()[:80] or "Workflow mới"
    with _lock:
        WF_DIR.mkdir(parents=True, exist_ok=True)
        wf_id = wf.get("id") or ""
        if not wf_id:
            base, n = f"wf-{slugify(name, 40)}", 1
            wf_id = base
            while (WF_DIR / f"{wf_id}.json").exists():
                n += 1
                wf_id = f"{base}-{n}"
        path = _path(wf_id)
        old = json.loads(path.read_text("utf-8")) if path.exists() else {}
        record = {"id": wf_id, "name": name, "desc": str(wf.get("desc") or "").strip()[:300], **clean(wf),
                  "created_at": old.get("created_at", now()), "updated_at": now(), "last_run": old.get("last_run")}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(path)
    return record


def from_preset(preset_id: str) -> dict:
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise WorkflowError("Không có mẫu này")
    return save({"name": preset["name"], "desc": preset["desc"], "nodes": json.loads(json.dumps(preset["nodes"])),
                 "edges": list(preset["edges"])})


def duplicate(wf_id: str) -> dict:
    wf = get(wf_id)
    return save({**wf, "id": "", "name": f"{wf['name']} (bản sao)"})


def delete(wf_id: str) -> None:
    path = _path(wf_id)
    if path.exists():
        path.unlink()  # chỉ xoá định nghĩa workflow; kết quả các lần chạy vẫn giữ trong thư mục video


def mark_run(wf_id: str, run_id: str, status: str) -> None:
    with _lock:
        path = _path(wf_id)
        if path.exists():
            wf = json.loads(path.read_text("utf-8"))
            wf["last_run"] = {"id": run_id, "status": status, "at": now()}
            path.write_text(json.dumps(wf, ensure_ascii=False, indent=2), "utf-8")


# ---------------------------------------------------------------------- lần chạy
def runs_root(output_dir, wf_id: str) -> Path:
    _path(wf_id)
    return Path(output_dir) / "_workflows" / wf_id


_run_lock = threading.Lock()


def save_run(run_dir: Path, data: dict) -> None:
    """Ghi run.json nguyên tử; khoá + thử lại vì Windows báo 'Access denied' khi file đang được đọc ở luồng khác."""
    import time

    with _run_lock:
        tmp = run_dir / "run.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        for attempt in range(10):
            try:
                tmp.replace(run_dir / "run.json")
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05)


def list_runs(output_dir, wf_id: str) -> list:
    base = runs_root(output_dir, wf_id)
    out = []
    if base.exists():
        for d in sorted(base.iterdir(), reverse=True):
            try:
                data = json.loads((d / "run.json").read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({k: data.get(k) for k in ("id", "status", "started_at", "ended_at", "error", "test")})
    return out[:50]


def get_run(output_dir, wf_id: str, run_id: str) -> dict:
    if not re.fullmatch(r"\d{8}_\d{6}(_\d+)?", run_id or ""):
        raise WorkflowError("Mã lần chạy không hợp lệ")
    path = runs_root(output_dir, wf_id) / run_id / "run.json"
    if not path.exists():
        raise WorkflowError("Không tìm thấy lần chạy")
    return json.loads(path.read_text("utf-8"))
