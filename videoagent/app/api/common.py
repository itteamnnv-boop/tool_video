"""Dùng chung cho các nhóm API: logger, khuôn trả về cho JS ({ok: true, …} / {ok: false, error})."""
import logging

log = logging.getLogger("app.api")  # giữ tên logger cũ


def _ok(**data) -> dict:
    return {"ok": True, **data}


def _fail(exc: Exception) -> dict:
    if isinstance(exc, UnicodeError):  # lỗi mã hoá ký tự là lỗi của app (không phải người dùng) → ghi đủ traceback để sửa
        log.error("Lỗi mã hoá ký tự: %s", exc, exc_info=exc)
    return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------- Studio Muse AI · dây chuyền (mhub_*)
def _hub_call(key: str, fn, *args):
    from ..llm.base import LLMError
    from ..muse_hub import HubError
    from ..muse_script import ScriptError
    from ..studio import StudioError

    try:
        return _ok(**{key: fn(*args)})
    except (HubError, ScriptError, LLMError, StudioError, ValueError, OSError) as exc:
        return _fail(exc)
