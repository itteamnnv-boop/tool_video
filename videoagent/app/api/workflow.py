"""API · Workflow kéo thả block (wf_*)."""
import os

from ..config import settings
from ..templates_registry import registry

from .common import _fail, _ok


class WorkflowApi:
    # ------------------------------------------------------------------ workflow (kéo thả block)
    def _wf(self, key: str, fn, *args) -> dict:
        from ..workflow.store import WorkflowError

        try:
            return _ok(**{key: fn(*args)})
        except (WorkflowError, ValueError, OSError) as exc:
            return _fail(exc)

    def wf_meta(self) -> dict:
        from ..workflow import nodes, store

        return _ok(meta=nodes.meta(), presets=store.presets(), running=self._workflows.running_ids())

    def wf_list(self) -> dict:
        from ..workflow import store

        items = store.list_workflows()
        for wf in items:  # số lần chạy (đọc thư mục kết quả, tối đa 50 lần gần nhất)
            try:
                wf["runs"] = len(store.list_runs(settings.output_dir, wf["id"]))
            except store.WorkflowError:
                wf["runs"] = 0
        return _ok(workflows=items, running=self._workflows.running_ids(), presets=store.presets())

    def wf_get(self, wf_id: str) -> dict:
        from ..workflow import runner, store

        def run():
            wf = store.get(wf_id)
            return {**wf, "issues": runner.validate(wf), "running": wf_id in self._workflows.running_ids()}

        return self._wf("workflow", run)

    def wf_save(self, wf: dict) -> dict:
        from ..workflow import runner, store

        def run():
            saved = store.save(wf)
            return {**saved, "issues": runner.validate(saved), "running": saved["id"] in self._workflows.running_ids()}

        return self._wf("workflow", run)

    def wf_validate(self, wf: dict) -> dict:
        from ..workflow import runner, store

        return self._wf("issues", lambda: runner.validate({**wf, **store.clean(wf)}))

    def wf_from_preset(self, preset_id: str) -> dict:
        from ..workflow import store

        return self._wf("workflow", store.from_preset, preset_id)

    def wf_duplicate(self, wf_id: str) -> dict:
        from ..workflow import store

        return self._wf("workflow", store.duplicate, wf_id)

    def wf_delete(self, wf_id: str) -> dict:
        from ..workflow import store

        if wf_id in self._workflows.running_ids():
            return _fail(ValueError("Workflow đang chạy — dừng trước khi xoá"))
        return self._wf("deleted", lambda: store.delete(wf_id) or True)

    def wf_run(self, wf_id: str, overrides: dict | None = None) -> dict:
        return self._wf("result", self._workflows.run, wf_id, overrides or {})

    def wf_video_templates(self) -> dict:
        """Template video AI dùng được trong block Tạo video (của app + của bạn) và danh sách nhóm."""
        from ..templates_registry import CATEGORIES

        items = [t.as_dict() for t in registry.listed() if t.kind == "ai_video"]
        for t in items:
            t["attachments"] = [{k: a.get(k) for k in ("key", "label", "hint", "role", "prompt", "required", "video", "keep_video", "send_video")}
                                | {"has_default": bool(a.get("default"))} for a in t["attachments"]]
            t["steps"] = [{"key": s["key"], "label": s.get("label", s["key"]), "engine": s.get("engine", ""),
                           "aspect": s.get("aspect", ""), "prompt": s.get("prompt", ""),
                           "inputs": [{"key": i["key"], "role": i.get("role", "")} for i in s.get("inputs", [])]}
                          for s in t.pop("image_steps")]
            t["video_inputs"] = [{"key": i["key"], "role": i.get("role", "")} for i in t.get("video_inputs") or []]
        items.sort(key=lambda t: (not t["user"], t["name"].lower()))
        return _ok(templates=items, categories=[{"id": c["id"], "name": c["name"], "icon": c["icon"]} for c in CATEGORIES])

    def wf_save_video_template(self, data: dict) -> dict:
        try:
            return _ok(template=registry.save_user_template(data or {}).as_dict())
        except (ValueError, OSError) as exc:
            return _fail(exc)

    def wf_delete_video_template(self, template_id: str) -> dict:
        try:
            registry.delete_user_template(template_id)
            return _ok()
        except (ValueError, OSError) as exc:
            return _fail(exc)

    def wf_test_plan(self, wf_id: str, node_id: str, fresh: bool = False) -> dict:
        """Xem trước khi chạy thử 1 block: block nào chạy thật, block nào dùng lại kết quả cũ."""
        return self._wf("plan", self._workflows.plan_public, wf_id, node_id, bool(fresh))

    def wf_run_node(self, wf_id: str, node_id: str, fresh: bool = False) -> dict:
        """Chạy thử 1 block (kèm các block phía trước còn thiếu kết quả)."""
        return self._wf("result", self._workflows.run, wf_id, {}, node_id, bool(fresh))

    def wf_approve(self, wf_id: str, run_id: str, node_id: str, approved: bool, caption: str | None = None) -> dict:
        return self._wf("result", self._workflows.approve, wf_id, run_id, node_id, bool(approved), caption)

    def wf_fb_options(self) -> dict:
        """Fanpage đã kết nối + tài khoản quảng cáo cho ô chọn của block Facebook (không trả token)."""
        pages = [{"id": p["id"], "name": p["name"]} for p in self._facebook.state().get("pages", []) if p.get("connected")]
        accounts, error = [], ""
        try:
            accounts = [{"id": a["id"], "name": a["name"] or a["account_id"], "currency": a.get("currency", ""),
                         "active": a.get("active")} for a in self._ads.accounts()]
        except Exception as exc:  # chưa có quyền ads_read / chưa kết nối — block Tạo quảng cáo sẽ báo
            error = str(exc)
        return _ok(pages=pages, accounts=accounts, accounts_error=error)

    def wf_cancel(self, wf_id: str) -> dict:
        return _ok(cancelled=self._workflows.cancel(wf_id))

    def wf_runs(self, wf_id: str) -> dict:
        from ..workflow import store

        return self._wf("runs", store.list_runs, settings.output_dir, wf_id)

    def wf_run_get(self, wf_id: str, run_id: str) -> dict:
        from ..workflow import store

        return self._wf("run", lambda: self._workflows.public(store.get_run(settings.output_dir, wf_id, run_id)))

    def wf_open_run(self, wf_id: str, run_id: str) -> dict:
        from ..workflow import store

        def run():
            store.get_run(settings.output_dir, wf_id, run_id)
            os.startfile(store.runs_root(settings.output_dir, wf_id) / run_id)
            return True

        return self._wf("opened", run)
