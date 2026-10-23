"""API · Nhân vật & layout cố định."""
from ..config import settings
from ..llm.image_engines import ENGINES as IMAGE_ENGINES

from .common import _fail, _ok


class CastApi:
    # ------------------------------------------------------------------ nhân vật & layout cố định
    def _cast_call(self, key: str, fn, *args) -> dict:
        from ..cast import CastError

        try:
            return _ok(**{key: fn(*args)})
        except (CastError, OSError, ValueError) as exc:
            return _fail(exc)

    def cast_meta(self) -> dict:
        from ..cast import CHARACTER_PRESETS, MAX_COMBO_CHARS, MAX_PRODUCTS, MAX_REFS, UI_ELEMENTS
        from ..content_writer import models

        return _ok(presets=[{"key": k, "label": v[0], "aspect": v[1]} for k, v in CHARACTER_PRESETS.items()],
                   ui_elements=[{"key": k, "label": v[0]} for k, v in UI_ELEMENTS.items()], max_combo_chars=MAX_COMBO_CHARS,
                   max_products=MAX_PRODUCTS, max_refs=MAX_REFS,
                   image_engines={k: {"name": v["name"], "browser": bool(v.get("browser")), "aspects": v["aspects"],
                                      "counts": v["counts"]} for k, v in IMAGE_ENGINES.items()},
                   text_models=models(settings))

    def cast_list(self, kind: str) -> dict:
        return self._cast_call("items", self._cast.list, kind)

    def cast_get(self, kind: str, cid: str) -> dict:
        return self._cast_call("item", self._cast.get, kind, cid)

    def cast_create(self, kind: str, data: dict | None = None) -> dict:
        return self._cast_call("item", self._cast.create, kind, data or {})

    def cast_save(self, kind: str, cid: str, data: dict) -> dict:
        return self._cast_call("item", self._cast.save, kind, cid, data or {})

    def cast_delete(self, kind: str, cid: str) -> dict:
        return self._cast_call("ok", lambda: self._cast.delete(kind, cid) or True)

    def cast_duplicate(self, kind: str, cid: str) -> dict:
        return self._cast_call("item", self._cast.duplicate, kind, cid)

    def cast_add_photos(self, kind: str, cid: str, files: list | None = None, role: str = "") -> dict:
        """role = "product": ảnh sản phẩm của bộ kết hợp (nhân vật cầm / giới thiệu sản phẩm) ·
        role = "ref": file đính kèm cho AI viết mô tả (ảnh tham khảo + ghi chú .txt / .md)."""
        files = files if files is not None else self.pick_files("cast_refs" if role == "ref" else "images_multi")
        if not files:
            return _ok(item=None)
        return self._cast_call("item", self._cast.add_photos, kind, cid, files, str(role or ""))

    def cast_tasks(self) -> dict:
        """Tác vụ của màn Nhân vật & Layout (đang chạy + gần đây) — thẻ Tiến trình."""
        return _ok(tasks=self._cast.pool.list())

    def cast_task_logs(self, task_id: str) -> dict:
        return _ok(logs=self._cast.pool.logs(str(task_id or "")))

    def cast_set_image(self, kind: str, cid: str, name: str, opts: dict) -> dict:
        opts = opts or {}
        return self._cast_call("item", self._cast.set_image, kind, cid, name, opts.get("starred"), opts.get("base"),
                               bool(opts.get("remove")))

    def cast_presets(self, kind: str, cid: str) -> dict:
        return self._cast_call("presets", self._cast.presets, kind, cid)

    def cast_describe(self, kind: str, cid: str, options: dict) -> dict:
        return self._cast_call("task", self._cast.describe, kind, cid, options or {})

    def cast_generate(self, kind: str, cid: str, req: dict) -> dict:
        return self._cast_call("task", self._cast.generate, kind, cid, req or {})

    def cast_cancel(self, task_id: str = "") -> dict:
        return _ok(cancelled=self._cast.pool.cancel(task_id))
