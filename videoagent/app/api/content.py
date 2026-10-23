"""API · Tạo content bài viết (quản lý + tạo, lấy thông tin từ link)."""
from ..config import settings

from .common import _fail, _ok, log


class ContentApi:
    # ---- Tạo content bài viết
    def content_models(self) -> dict:
        from .. import content_writer as cw
        from ..campaign import store

        products = [{k: p.get(k, "") for k in ("id", "name", "code", "spec", "price", "sale_price", "promo", "hotline",
                                                 "label", "links")} for p in store.products()]
        return _ok(models=cw.models(settings), fields={k: {"label": v[0], "required": v[1]} for k, v in cw.FIELDS.items()},
                   template=cw.DEFAULT_TEMPLATE, max_variants=cw.MAX_VARIANTS, products=products)

    def content_generate(self, form: dict) -> dict:
        from .. import content_writer as cw

        try:
            return _ok(result=cw.generate(form, settings))
        except (cw.ContentError, ValueError) as exc:
            return _fail(exc)
        except Exception as exc:  # lỗi trình duyệt / mạng của model
            log.exception("Tạo content lỗi")
            return _fail(exc)

    def content_from_link(self, url: str, model: str, profile: str = "") -> dict:
        """Đọc link trang sản phẩm → model trích thông tin → điền form Viết content (người dùng xem lại rồi mới viết)."""
        from .. import content_writer as cw

        try:
            return _ok(result=cw.from_link(str(url or ""), str(model or ""), settings, profile=str(profile or ""),
                                           show_browser=bool(settings.get("show_browser")),
                                           log=lambda m, level="info": log.info("content-link: %s", m)))
        except (cw.ContentError, ValueError) as exc:
            return _fail(exc)
        except Exception as exc:  # lỗi trình duyệt / mạng của model
            log.exception("Lấy thông tin từ link lỗi")
            return _fail(exc)

    def content_update(self, entry_id: str, index: int, text: str) -> dict:
        """Quản lý content: lưu bài đã sửa tay (tự kiểm tra lại thông tin)."""
        from .. import content_writer as cw

        try:
            return _ok(entry=cw.update_variant(str(entry_id or ""), int(index or 0), str(text or "")))
        except (cw.ContentError, ValueError) as exc:
            return _fail(exc)

    def content_delete_many(self, ids: list) -> dict:
        from .. import content_writer as cw

        return _ok(items=cw.delete_many(list(ids or [])))

    def content_history(self) -> dict:
        from .. import content_writer as cw

        return _ok(items=cw.history())

    def content_delete(self, entry_id: str) -> dict:
        from .. import content_writer as cw

        return _ok(items=cw.delete_history(entry_id))
