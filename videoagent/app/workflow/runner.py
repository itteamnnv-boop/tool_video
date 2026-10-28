"""Chạy workflow: kiểm tra hợp lệ → sắp thứ tự block theo dây nối → chạy tuần tự trong hàng đợi tác vụ.

Mỗi lần chạy = một thư mục <thư mục video>/_workflows/<id>/<YYYYmmdd_HHMMSS>/ (run.json + kết quả từng block).
Block lỗi → các block phụ thuộc vào nó được đánh dấu "bỏ qua"; block không liên quan vẫn chạy tiếp.
"""
import json
from datetime import datetime
from pathlib import Path

from ..pipeline import Cancelled
from ..pipeline.tasks import TaskPool
from . import store
from .nodes import (NODE_TYPES, POST_TYPES, SCHEDULABLE, VIDEO_ENGINES, NodeContext, NodeSkipped, config_of, publish_time,
                    run_node, template_engine, template_missing, video_template, virtual_edges)
from .store import WorkflowError


def _ports(node: dict, side: str) -> dict:
    return {p["key"]: p for p in NODE_TYPES[node["type"]][side]}


def validate(wf: dict) -> list:
    """Danh sách vấn đề [{node, level: error|warn, message}] — giao diện hiện ở bước 02, lúc chạy thì chặn lỗi."""
    issues = []
    wf = virtual_edges(wf)  # tài nguyên tick trong block Đăng bài = dây ảo
    nodes = {n["id"]: n for n in wf.get("nodes") or []}
    if not nodes:
        return [{"node": "", "level": "error", "message": "Workflow chưa có block nào — kéo block từ bảng bên trái"}]
    incoming = {nid: [] for nid in nodes}
    for e in wf.get("edges") or []:
        a, b = nodes.get(e["from"]), nodes.get(e["to"])
        if not a or not b:
            continue
        out, inp = _ports(a, "outputs").get(e["out"]), _ports(b, "inputs").get(e["in"])
        if not out or not inp:
            issues.append({"node": e["to"], "level": "error", "message": "Dây nối tới cổng không tồn tại"})
        elif inp["type"] != "any" and inp["type"] != out["type"]:
            issues.append({"node": e["to"], "level": "error", "message": f"Dây {out['label']} → {inp['label']} sai kiểu dữ liệu"})
        incoming[e["to"]].append(e)
    if not any(n["type"] == "output" for n in nodes.values()):
        issues.append({"node": "", "level": "warn", "message": "Chưa có block Kết quả — kết quả vẫn nằm trong thư mục từng block"})
    need_key = False
    for nid, n in nodes.items():
        cfg, kind = config_of(n), n["type"]
        wired = {e["in"] for e in incoming[nid]}
        if kind == "input_text" and not str(cfg.get("text") or "").strip() and not cfg.get("ask"):
            issues.append({"node": nid, "level": "error", "message": "Văn bản đang trống"})
        if kind in ("input_image", "input_video") and not cfg.get("files") and not cfg.get("ask"):
            issues.append({"node": nid, "level": "error", "message": "Chưa chọn file"})
        if kind == "gen_video" and cfg.get("template"):
            found = video_template(cfg["template"])
            if found is None:
                issues.append({"node": nid, "level": "error", "message": "Template video không còn tồn tại — chọn template khác"})
            else:
                engine = template_engine(found, cfg.get("engine"))
                if any(a.get("keep_video") for a in found.attachments) and not (VIDEO_ENGINES.get(engine) or {}).get("video_input"):
                    issues.append({"node": nid, "level": "error",
                                   "message": f"Template “{found.name}” cần gửi video gốc — chọn model Grok hoặc Dola (trình duyệt)"})
                missing = [] if cfg.get("ask_vars") else template_missing(cfg, wired)
                if missing:
                    issues.append({"node": nid, "level": "error", "message": "Template còn thiếu: " + ", ".join(missing)})
        elif kind in ("gen_image", "gen_video") and "prompt" not in wired and not str(cfg.get("prompt") or "").strip():
            issues.append({"node": nid, "level": "error", "message": "Chưa có prompt — nối dây từ Văn bản/AI hoặc nhập prompt"})
        if kind == "ai_text" and not str(cfg.get("prompt") or "").strip() and "text" not in wired:
            issues.append({"node": nid, "level": "error", "message": "Block AI chưa có yêu cầu"})
        if kind in ("concat_video", "output") and not incoming[nid]:
            issues.append({"node": nid, "level": "error", "message": "Chưa có dây nối vào"})
        if kind == "ai_text" and cfg.get("provider") == "claude_api":
            need_key = True
        if kind in ("fb_post", "fb_schedule"):
            if not cfg.get("page_id"):
                issues.append({"node": nid, "level": "error", "message": "Chưa chọn Fanpage"})
            ptype = cfg.get("post_type") if cfg.get("post_type") in POST_TYPES else "feed"
            ins = {e["in"] for e in incoming[nid]}
            media_types = {(_ports(nodes[e["from"]], "outputs").get(e["out"]) or {}).get("type")
                           for e in incoming[nid] if e["in"] == "media"}
            has_caption = "caption" in ins or bool(str(cfg.get("caption") or "").strip())
            if kind == "fb_schedule" and ptype not in SCHEDULABLE:
                issues.append({"node": nid, "level": "error", "message": "Facebook không cho hẹn giờ Story"})
            elif ptype == "text" and not has_caption:
                issues.append({"node": nid, "level": "error", "message": "“Chỉ bài viết” cần caption — tick văn bản trong Tài nguyên từ flow"})
            elif ptype in ("media", "story") and "media" not in ins:
                issues.append({"node": nid, "level": "error", "message": f"“{POST_TYPES[ptype]}” cần ảnh/video — tick trong Tài nguyên từ flow"})
            elif ptype == "reel" and "video" not in media_types:
                issues.append({"node": nid, "level": "error", "message": "Reels cần video — tick 1 video trong Tài nguyên từ flow"})
            elif not incoming[nid] and not has_caption:
                issues.append({"node": nid, "level": "error", "message": "Chưa có caption hoặc ảnh/video để đăng"})
            if kind == "fb_schedule":
                try:
                    publish_time(cfg)
                except ValueError as exc:
                    issues.append({"node": nid, "level": "warn" if cfg.get("mode") != "at" else "error", "message": str(exc)})
            if not cfg.get("confirm", True):
                issues.append({"node": nid, "level": "warn", "message": "Đang tắt “Duyệt trước khi đăng” — bài sẽ đăng tự động khi chạy"})
        if kind == "whiteboard_video":
            if "text" not in wired and not str(cfg.get("text") or "").strip() and not cfg.get("srt"):
                issues.append({"node": nid, "level": "error", "message": "Nhập SRT / kịch bản, chọn file .srt hoặc nối dây vào cổng"})
            from ..pipeline import whiteboard as wbm

            if not wbm.status()["installed"] and not wbm.status()["python"]:
                issues.append({"node": nid, "level": "error", "message": "Whiteboard cần Python 3 trên máy để cài bộ dựng"})
        if kind == "studio_video":
            if "idea" not in wired and len(str(cfg.get("idea") or "").strip()) < 10:
                issues.append({"node": nid, "level": "error", "message": "Nhập ý tưởng video hoặc nối dây vào cổng Ý tưởng"})
            if not cfg.get("preset") and str(cfg.get("model") or "").startswith("api:"):
                from ..campaign.ai import key_status

                if not key_status().get("openai" if "gpt" in str(cfg.get("model")) else "anthropic"):
                    issues.append({"node": nid, "level": "error", "message": "Model viết storyboard cần API key — nhập ở Cài đặt"})
        if kind == "storyboard_video":
            if "request" not in wired and len(str(cfg.get("request") or "").strip()) < 10:
                issues.append({"node": nid, "level": "error", "message": "Nhập yêu cầu video hoặc nối dây vào cổng Yêu cầu"})
            if str(cfg.get("model") or "").startswith("api:"):
                from ..campaign.ai import key_status

                if not key_status().get("openai" if "gpt" in str(cfg.get("model")) else "anthropic"):
                    issues.append({"node": nid, "level": "error", "message": "Model viết storyboard cần API key — nhập ở Cài đặt"})
        if kind == "fb_ad":
            if not cfg.get("account_id"):
                issues.append({"node": nid, "level": "error", "message": "Chưa chọn tài khoản quảng cáo"})
            if "post" not in wired:
                issues.append({"node": nid, "level": "error", "message": "Nối cổng Bài viết từ block Đăng bài Facebook"})
            try:
                if float(cfg.get("daily_budget") or 0) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                issues.append({"node": nid, "level": "error", "message": "Ngân sách mỗi ngày phải lớn hơn 0"})
    if need_key:
        from ..campaign.ai import get_key

        if not get_key():
            issues.append({"node": "", "level": "error", "message": "Chưa có khoá Anthropic API (Cài đặt → API & kết nối)"})
    try:
        order(wf)
    except WorkflowError as exc:
        issues.append({"node": "", "level": "error", "message": str(exc)})
    return issues


def order(wf: dict) -> list:
    """Sắp thứ tự topo (Kahn); khi nhiều block cùng sẵn sàng thì chạy theo vị trí trên canvas (trái → phải)."""
    wf = virtual_edges(wf)
    nodes = {n["id"]: n for n in wf.get("nodes") or []}
    indeg = {nid: 0 for nid in nodes}
    out = {nid: [] for nid in nodes}
    for e in wf.get("edges") or []:
        if e["from"] in nodes and e["to"] in nodes:
            indeg[e["to"]] += 1
            out[e["from"]].append(e["to"])
    pos = lambda i: (nodes[i]["x"], nodes[i]["y"])  # noqa: E731
    ready = sorted([n for n, d in indeg.items() if d == 0], key=pos)
    result = []
    while ready:
        nid = ready.pop(0)
        result.append(nid)
        for nxt in out[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=pos)
    if len(result) != len(nodes):
        raise WorkflowError("Dây nối tạo thành vòng lặp — workflow phải chạy một chiều từ trái sang phải")
    return result


def ancestors(wf: dict, nid: str) -> set:
    """Mọi block nằm phía trước nid (theo dây nối)."""
    found, stack = set(), [nid]
    while stack:
        cur = stack.pop()
        for e in wf.get("edges") or []:
            if e["to"] == cur and e["from"] not in found:
                found.add(e["from"])
                stack.append(e["from"])
    return found


def _signature(node: dict, edges: list) -> str:
    """Dấu vân tay cấu hình 1 block — đổi cấu hình hoặc dây vào thì kết quả cũ không dùng lại được.
    Block đầu vào "hỏi khi chạy" bỏ qua text/files (mỗi lần chạy nhập khác nhau)."""
    cfg = dict(node.get("config") or {})
    if node["type"].startswith("input_") and cfg.get("ask"):
        cfg.pop("text", None), cfg.pop("files", None)
    wires = sorted((e["from"], e["out"], e["in"]) for e in edges if e["to"] == node["id"])
    return json.dumps([node["type"], cfg, wires], ensure_ascii=False, sort_keys=True)


def _alive(value) -> bool:
    """Kết quả cũ còn dùng được: mọi file nó trỏ tới vẫn còn trên máy."""
    if isinstance(value, list):
        return all(_alive(v) for v in value)
    if isinstance(value, dict):
        return all(_alive(v) for v in value.values())
    if isinstance(value, str) and 3 < len(value) < 400 and "\n" not in value:
        p = Path(value)
        if p.is_absolute() and p.suffix:
            return p.exists()
    return True


class WorkflowRunner:
    def __init__(self, settings, license_mgr, emit, facebook=None, ads=None, studio=None) -> None:
        self.settings = settings
        self.license = license_mgr
        self._emit = emit
        self.facebook, self.ads = facebook, ads
        self.studio = studio  # block Video dài từ storyboard chạy dự án Studio
        self.pool = TaskPool("workflow_", emit, lambda: settings.get("max_parallel_workflow") or 1)
        self._active: dict[str, str] = {}  # workflow_id → task id
        self._approvals: dict[tuple, dict] = {}  # (run_id, node_id) → {"event", "decision"}

    def approve(self, wf_id: str, run_id: str, node_id: str, approved: bool, caption: str | None = None) -> dict:
        """Người dùng duyệt / từ chối block Đăng bài đang chờ (bấm trên giao diện)."""
        import getpass

        slot = self._approvals.get((run_id, node_id))
        if slot is None:
            raise WorkflowError("Block này không còn chờ duyệt")
        slot["decision"] = {"approved": bool(approved), "caption": caption, "by": f"{getpass.getuser()} (máy này)",
                            "at": store.now()}
        slot["event"].set()
        return {"run": run_id, "node": node_id, "approved": bool(approved)}

    def _wait_approval(self, run_dir: Path, data: dict, nid: str, payload: dict) -> dict:
        import threading

        state = data["nodes"][nid]
        state.update(status="waiting", approval={k: v for k, v in payload.items() if k != "scheduled_at"})
        slot = {"event": threading.Event(), "decision": None}
        self._approvals[(data["id"], nid)] = slot
        self._push(run_dir, data)
        self._emit("toast", {"message": f"Workflow “{data['name']}”: có bài chờ bạn duyệt đăng", "level": "warn"})
        try:
            while not slot["event"].wait(0.5):
                self.pool.check_cancel()  # bấm Dừng trong lúc chờ duyệt
        finally:
            self._approvals.pop((data["id"], nid), None)
        decision = slot["decision"]
        if decision.get("caption") is None:
            decision["caption"] = payload.get("caption", "")
        state["approval"].update(decided_by=decision["by"], decided_at=decision["at"], approved=decision["approved"])
        state["status"] = "running"
        self._push(run_dir, data)
        return decision

    def running_ids(self) -> list:
        live = {t["id"] for t in self.pool.list() if t["status"] in ("queued", "running")}
        return [wf for wf, task in self._active.items() if task in live]

    def test_plan(self, wf: dict, target: str, fresh: bool = False) -> dict:
        """Kế hoạch chạy thử 1 block: block nào chạy thật, block phía trước nào dùng lại kết quả lần chạy trước.
        Dùng lại khi cấu hình + dây vào không đổi, file kết quả còn, và không block nào trước nó phải chạy lại."""
        wf = virtual_edges(wf)
        nodes = {n["id"]: n for n in wf["nodes"]}
        if target not in nodes:
            raise WorkflowError("Không tìm thấy block")
        sub = ancestors(wf, target) | {target}
        seq = [nid for nid in order(wf) if nid in sub]
        found: dict = {}
        if not fresh:
            sigs = {nid: _signature(nodes[nid], wf["edges"]) for nid in sub if nid != target}
            for row in store.list_runs(self.settings.output_dir, wf["id"])[:30]:
                if len(found) == len(sigs):
                    break
                try:
                    old = store.get_run(self.settings.output_dir, wf["id"], row["id"])
                except (WorkflowError, OSError, ValueError):
                    continue
                snap = {n["id"]: n for n in (old.get("snapshot") or {}).get("nodes", [])}
                for nid, sig in sigs.items():
                    st = old.get("nodes", {}).get(nid) or {}
                    if nid in found or nid not in snap or st.get("status") not in ("done", "cached") or not st.get("outputs"):
                        continue
                    if _signature(snap[nid], old["snapshot"].get("edges") or []) == sig and _alive(st["outputs"]):
                        found[nid] = {"outputs": st["outputs"], "run": st.get("from_run") or old["id"]}
        cached, execute = {}, []
        for nid in seq:
            ups = {e["from"] for e in wf["edges"] if e["to"] == nid}
            if nid in found and not (ups & set(execute)):
                cached[nid] = found[nid]
            else:
                execute.append(nid)
        return {"target": target, "order": seq, "execute": execute, "cached": cached}

    def plan_public(self, wf_id: str, target: str, fresh: bool = False) -> dict:
        plan = self.test_plan(store.get(wf_id), target, fresh)
        return {"target": target, "execute": plan["execute"], "cached": {k: v["run"] for k, v in plan["cached"].items()}}

    def run(self, wf_id: str, overrides: dict | None = None, target: str | None = None, fresh: bool = False) -> dict:
        """Chạy workflow đã lưu. overrides = {node_id: {text|files}} — input mới cho lần chạy này (bước 04 Tái sử dụng).
        target = chạy thử 1 block (kèm các block phía trước còn thiếu kết quả); fresh = chạy lại cả nhánh phía trước."""
        wf = store.get(wf_id)
        for node in wf["nodes"]:
            new = (overrides or {}).get(node["id"])
            if new and node["type"].startswith("input_"):
                node["config"] = {**node.get("config", {}), **{k: v for k, v in new.items() if k in ("text", "files")}}
            elif new and node["type"] == "gen_video":  # thông tin / file template nhập lúc chạy
                cfg = dict(node.get("config") or {})
                if isinstance(new.get("vars"), dict):
                    cfg["vars"] = {**(cfg.get("vars") or {}), **{str(k): str(v)[:300] for k, v in new["vars"].items()}}
                if isinstance(new.get("att"), dict):
                    cfg["att"] = {**(cfg.get("att") or {}), **{str(k): str(v or "") for k, v in new["att"].items()}}
                node["config"] = cfg
        wf = virtual_edges(wf)  # dây ảo nằm trong snapshot → chạy và truyền dữ liệu như dây thật
        plan = self.test_plan(wf, target, fresh) if target else None
        if plan:  # chỉ kiểm tra các block sẽ chạy thật
            keep = set(plan["order"])
            sub = {**wf, "nodes": [n for n in wf["nodes"] if n["id"] in keep],
                   "edges": [e for e in wf["edges"] if e["from"] in keep and e["to"] in keep]}
            errors = [i for i in validate(sub) if i["level"] == "error" and (not i["node"] or i["node"] in plan["execute"])]
        else:
            errors = [i for i in validate(wf) if i["level"] == "error"]
        for node in wf["nodes"]:  # block "hỏi khi chạy" mà vẫn trống → chặn lúc chạy (không chặn lúc thiết kế)
            if plan and node["id"] not in plan["execute"]:
                continue
            cfg = config_of(node)
            if node["type"] == "input_text" and not str(cfg.get("text") or "").strip():
                errors.append({"node": node["id"], "message": f"“{cfg.get('label')}” đang trống"})
            if node["type"] in ("input_image", "input_video") and not cfg.get("files"):
                errors.append({"node": node["id"], "message": f"“{cfg.get('label')}” chưa chọn file"})
            if node["type"] == "gen_video" and cfg.get("template") and cfg.get("ask_vars"):
                wired = {e["in"] for e in wf["edges"] if e["to"] == node["id"]}
                missing = template_missing(cfg, wired)
                if missing:
                    errors.append({"node": node["id"], "message": "Template còn thiếu: " + ", ".join(missing)})
        if errors:
            raise WorkflowError("Chưa chạy được: " + "; ".join(dict.fromkeys(e["message"] for e in errors[:5])))
        if wf_id in self.running_ids():
            raise WorkflowError("Workflow này đang chạy — chờ xong hoặc bấm Dừng")
        base = store.runs_root(self.settings.output_dir, wf_id)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir, n = base / stamp, 2
        while run_dir.exists():
            run_dir, n = base / f"{stamp}_{n}", n + 1
        run_dir.mkdir(parents=True)
        seq = plan["order"] if plan else order(wf)
        data = {"id": run_dir.name, "workflow": wf_id, "name": wf["name"], "status": "queued", "started_at": None,
                "ended_at": None, "error": "", "order": seq, "snapshot": wf,
                "nodes": {nid: {"status": "pending", "error": "", "outputs": {}} for nid in seq}}
        title = f"Workflow · {wf['name']}"
        if plan:
            data["test"] = {"target": target, "fresh": bool(fresh)}
            for nid, hit in plan["cached"].items():
                data["nodes"][nid] = {"status": "cached", "error": "", "outputs": hit["outputs"], "from_run": hit["run"]}
            kind = next(n["type"] for n in wf["nodes"] if n["id"] == target)
            title = f"Chạy thử {NODE_TYPES[kind]['name']} · {wf['name']}"
        store.save_run(run_dir, data)  # ghi trước khi đưa vào hàng đợi — thread chạy đọc lại file này
        task = self.pool.submit(title, self._execute, run_dir,
                                meta={"workflow": wf_id, "run": run_dir.name})
        self._active[wf_id] = task
        self._emit("workflow_run", self.public(data))  # file đã ghi ở trên; luồng chạy sẽ cập nhật tiếp
        return {"run": run_dir.name, "task": task}

    def cancel(self, wf_id: str) -> int:
        task = self._active.get(wf_id)
        return self.pool.cancel(task) if task else 0

    # ------------------------------------------------------------------ nội bộ
    def _push(self, run_dir: Path, data: dict) -> None:
        store.save_run(run_dir, data)
        self._emit("workflow_run", self.public(data))

    def public(self, data: dict) -> dict:
        """Đổi đường dẫn file kết quả sang URL /media/… để giao diện xem trước."""
        base = Path(self.settings.output_dir).resolve()

        def url(value):
            if isinstance(value, list):
                return [url(v) for v in value]
            if isinstance(value, str) and len(value) < 400:
                p = Path(value)
                try:
                    if p.is_file():
                        ext = p.suffix.lower()
                        return {"path": value, "name": p.name, "url": "/media/" + p.resolve().relative_to(base).as_posix(),
                                "kind": "video" if ext in (".mp4", ".mov", ".webm") else
                                "image" if ext in (".png", ".jpg", ".jpeg", ".webp") else "file"}
                except (ValueError, OSError):
                    pass
            return {"text": value, "kind": "text"} if isinstance(value, str) else value

        nodes = {nid: {**st, "outputs": {k: url(v) for k, v in st.get("outputs", {}).items()}}
                 for nid, st in data["nodes"].items()}
        return {k: v for k, v in data.items() if k != "snapshot"} | {"nodes": nodes}

    def _execute(self, run_dir: Path) -> dict:
        self.license.require_active()
        data = json.loads((run_dir / "run.json").read_text("utf-8"))
        wf = data["snapshot"]
        nodes = {n["id"]: n for n in wf["nodes"]}
        data.update(status="running", started_at=store.now())
        self._push(run_dir, data)
        values: dict = {}  # (block, cổng) → giá trị
        total, failed = sum(1 for st in data["nodes"].values() if st["status"] != "cached"), set()
        try:
            idx = -1
            for nid in data["order"]:
                self.pool.check_cancel()
                node, spec = nodes[nid], NODE_TYPES[nodes[nid]["type"]]
                state = data["nodes"][nid]
                if state["status"] == "cached":  # chạy thử: dùng lại kết quả block phía trước từ lần chạy cũ
                    for port, value in state["outputs"].items():
                        values[(nid, port)] = value
                    self.pool.log(f"↺ {spec['name']} ({nid}): dùng lại kết quả lần chạy {state.get('from_run')}")
                    continue
                idx += 1
                if {e["from"] for e in wf["edges"] if e["to"] == nid} & failed:
                    state["status"] = "skipped"
                    state["error"] = "Bỏ qua vì block phía trước lỗi"
                    failed.add(nid)
                    self._push(run_dir, data)
                    continue
                inputs: dict = {}
                for e in wf["edges"]:  # giữ thứ tự dây nối (VD: thứ tự video khi ghép)
                    if e["to"] == nid and (e["from"], e["out"]) in values:
                        inputs.setdefault(e["in"], []).append(values[(e["from"], e["out"])])
                state.update(status="running", started_at=store.now())
                self._push(run_dir, data)
                self.pool.log(f"▶ {spec['name']} ({nid})")
                self.pool.progress(100 * idx / total, f"{spec['name']} ({idx + 1}/{total})", "run")

                def node_progress(frac, i=idx, s=spec):
                    self.pool.progress(100 * (i + max(0.0, min(1.0, frac))) / total, f"{s['name']} {round(frac * 100)}%", "run")

                services = {"facebook": self.facebook, "ads": self.ads, "studio": self.studio, "workflow_name": wf.get("name", ""),                            "approve": lambda payload, n=nid: self._wait_approval(run_dir, data, n, payload)}
                ctx = NodeContext(self.settings, run_dir, node, self.pool.log, self.pool.check_cancel, node_progress, services)
                try:
                    outputs = run_node(ctx, inputs)
                except Cancelled:
                    raise
                except NodeSkipped as exc:  # bỏ qua có chủ đích (không duyệt đăng) — không tính là lỗi
                    state.update(status="skipped", error=str(exc), ended_at=store.now())
                    failed.add(nid)
                    self.pool.log(f"– {spec['name']}: {exc}", "warn")
                    self._push(run_dir, data)
                    continue
                except Exception as exc:  # lỗi 1 block: đánh dấu, các block phụ thuộc sẽ được bỏ qua
                    state.update(status="error", error=str(exc), ended_at=store.now())
                    failed.add(nid)
                    self.pool.log(f"✕ {spec['name']}: {exc}", "error")
                    self._push(run_dir, data)
                    continue
                for port, value in outputs.items():
                    values[(nid, port)] = value
                state.update(status="done", outputs=outputs, ended_at=store.now())
                self.pool.log(f"✓ {spec['name']} xong", "ok")
                self._push(run_dir, data)
        except Cancelled:
            for st in data["nodes"].values():
                if st["status"] in ("pending", "running", "waiting"):
                    st["status"] = "skipped" if st["status"] == "pending" else "error"
            data.update(status="cancelled", ended_at=store.now(), error="Đã dừng")
            self._push(run_dir, data)
            if not data.get("test"):
                store.mark_run(wf["id"], data["id"], "cancelled")
            raise
        first_error = next((st["error"] for st in data["nodes"].values() if st.get("status") == "error"), "")
        data.update(status="error" if first_error else "done", ended_at=store.now(), error=first_error)
        self._push(run_dir, data)
        if not data.get("test"):  # chạy thử 1 block không tính là "lần chạy gần nhất" của workflow
            store.mark_run(wf["id"], data["id"], data["status"])
        if first_error:
            raise WorkflowError(f"Workflow lỗi: {first_error}")
        self.pool.progress(100, "Hoàn tất", "run")
        return {"workflow": wf["id"], "run": data["id"]}
