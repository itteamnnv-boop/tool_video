"""API · Quảng cáo Facebook + Trợ lý quảng cáo Meta."""
from ..config import settings

from .common import _fail, _ok, log


class AdsApi:
    # ------------------------------------------------------------------ quảng cáo Facebook
    def _ads_call(self, key: str, fn, *args) -> dict:
        from ..facebook import FacebookError

        try:
            return _ok(**{key: fn(*args)})
        except FacebookError as exc:
            return _fail(exc)

    def ads_status(self) -> dict:
        return _ok(ads=self._ads.status())

    def ads_accounts(self, refresh: bool = False) -> dict:
        return self._ads_call("accounts", self._ads.accounts, bool(refresh))

    def ads_overview(self, account_id: str, date_preset: str) -> dict:
        return self._ads_call("overview", self._ads.overview, account_id, date_preset)

    def ads_list(self, account_id: str, level: str, parent_id: str, date_preset: str) -> dict:
        return self._ads_call("data", self._ads.list, account_id, level, parent_id, date_preset)

    def ads_set_status(self, object_id: str, status: str) -> dict:
        return self._ads_call("result", self._ads.set_status, object_id, status)

    def ads_set_budget(self, account_id: str, object_id: str, daily_budget) -> dict:
        return self._ads_call("result", self._ads.set_budget, account_id, object_id, daily_budget)

    def ads_page_posts(self, page_id: str, after: str = "") -> dict:
        return self._ads_call("posts", self._ads.page_posts, page_id, after)

    def ads_create_boost(self, form: dict) -> dict:
        return self._ads_call("result", self._ads.create_boost, form)

    # ------------------------------------------------------------------ 🤖 trợ lý quảng cáo Meta
    def _adbot(self, key: str, fn, *args, **kwargs) -> dict:
        from ..ad_assistant import AssistantError
        from ..facebook import FacebookError
        from ..llm.base import LLMError
        from ..studio import StudioError

        try:
            return _ok(**{key: fn(*args, **kwargs)})
        except (AssistantError, FacebookError, LLMError, StudioError, OSError, ValueError) as exc:
            return _fail(exc)

    def adbot_meta(self) -> dict:
        from ..ad_assistant import STATUSES
        from ..content_writer import models
        from ..facebook_ads import OBJECTIVES

        return _ok(models=models(settings), objectives={k: v["name"] for k, v in OBJECTIVES.items()}, statuses=STATUSES,
                   ads=self._ads.status())

    def adbot_list(self) -> dict:
        return self._adbot("plans", self._adbot_store().list)

    def adbot_get(self, pid: str) -> dict:
        return self._adbot("plan", self._adbot_store().get, pid)

    def adbot_create(self, data: dict | None = None) -> dict:
        return self._adbot("plan", self._adbot_store().create, data or {})

    def adbot_save(self, pid: str, data: dict) -> dict:
        return self._adbot("plan", self._adbot_store().save, pid, data or {})

    def adbot_clone(self, pid: str) -> dict:
        return self._adbot("plan", self._adbot_store().clone, pid)

    def adbot_delete(self, pid: str) -> dict:
        return self._adbot("deleted", lambda: self._adbot_store().delete(pid) or True)

    def adbot_chat(self, pid: str, message: str, model: str = "chatgpt_browser", profile: str = "",
                   show_browser: bool = False) -> dict:
        """Gửi yêu cầu cho model (1–3 phút với model trình duyệt): trả lời + tự điền form bản nháp."""
        return self._adbot("plan", self._adbot_store().chat, pid, message, model=model, profile=profile,
                           show_browser=bool(show_browser), log=lambda m, level="info": log.info("adbot: %s", m))

    def adbot_submit(self, pid: str) -> dict:
        return self._adbot("plan", self._adbot_store().submit, pid)

    def adbot_approve(self, pid: str, mode: str, confirmed: bool = False) -> dict:
        """Duyệt: paused = tạo tạm dừng · schedule = chạy theo giờ bắt đầu · now = chạy ngay (2 cách cuối tiêu tiền thật,
        giao diện đã hỏi xác nhận → confirmed=True)."""
        return self._adbot("plan", self._adbot_store().approve, pid, str(mode or ""), bool(confirmed))

    def adbot_interests(self, query: str) -> dict:
        return self._adbot("items", self._ads.search_interests, query, 10)

    # ------------------------------------------------------------------ yêu cầu quảng cáo từ nhóm chat (adreq_*)
    def _adreq(self):
        if getattr(self, "_adreq_obj", None) is None:
            from ..ad_requests import AdRequests

            self._adreq_obj = AdRequests(settings, self._ads, self._facebook)
        return self._adreq_obj

    def _adreq_call(self, key: str, fn, *args, **kwargs) -> dict:
        from ..ad_requests import AdRequestError
        from ..facebook import FacebookError
        from ..llm.base import LLMError
        from ..studio import StudioError

        try:
            return _ok(**{key: fn(*args, **kwargs)})
        except (AdRequestError, FacebookError, LLMError, StudioError, OSError, ValueError) as exc:
            return _fail(exc)

    def adreq_meta(self) -> dict:
        from ..ad_requests import ACTIONS, OPS, STATUS

        return _ok(actions=ACTIONS, ops={k: v[0] for k, v in OPS.items()}, statuses=STATUS,
                   account=settings.get("adreq_account") or "")

    def adreq_list(self) -> dict:
        return self._adreq_call("requests", self._adreq().list)

    def adreq_add(self, text: str, account_id: str, use_ai: bool = False, model: str = "", profile: str = "",
                  mode: str = "", show_browser: bool = True, note: str = "") -> dict:
        """Dán tin nhắn nhóm → tách yêu cầu + đối chiếu tài khoản → thao tác ĐỀ XUẤT (chưa chạy gì).
        mode=claude: Claude trên claude.ai (đã kết nối MCP quảng cáo) đọc tin / rà soát tài khoản — chỉ đọc."""
        if account_id:
            settings.update({"adreq_account": account_id})
        return self._adreq_call("requests", self._adreq().add, text, account_id, use_ai=bool(use_ai), model=model,
                                profile=profile, mode=str(mode or ""), show_browser=bool(show_browser), note=str(note or ""),
                                log=lambda m, level="info": log.info("adreq: %s", m))

    # ---- trò chuyện với Claude (claude.ai + MCP quảng cáo) → yêu cầu chờ duyệt
    def adchat_list(self) -> dict:
        return self._adreq_call("chats", self._adreq().chats)

    def adchat_get(self, cid: str) -> dict:
        return self._adreq_call("chat", self._adreq().chat_get, cid)

    def adchat_new(self, account_id: str = "") -> dict:
        return self._adreq_call("chat", self._adreq().chat_new, account_id)

    def adchat_delete(self, cid: str) -> dict:
        return self._adreq_call("ok", lambda: self._adreq().chat_delete(cid) or True)

    def adchat_send(self, cid: str, message: str, account_id: str, show_browser: bool = True) -> dict:
        """1 lượt chat với Claude (1–15 phút). Trạng thái (đang chờ, chờ quyền công cụ…) đẩy lên qua sự kiện adchat_status."""
        if account_id:
            settings.update({"adreq_account": account_id})

        def status(m, level="info"):
            log.info("adchat: %s", m)
            self._emit("adchat_status", {"chat": cid, "text": str(m), "level": level})

        return self._adreq_call("result", self._adreq().chat, cid, message, account_id, show_browser=bool(show_browser),
                                log=status)

    def adreq_update(self, rid: str, data: dict, account_id: str) -> dict:
        return self._adreq_call("request", self._adreq().update, rid, data or {}, account_id)

    def adreq_set_ops(self, rid: str, data: dict) -> dict:
        return self._adreq_call("request", self._adreq().set_ops, rid, data or {})

    def adreq_execute(self, rid: str, confirmed: bool = False, confirmed_spend: bool = False) -> dict:
        """Chạy các thao tác đã tick — CHỈ khi người dùng bấm Duyệt (confirmed) + xác nhận riêng nếu tiêu tiền."""
        by = self._adbot_store().approver()
        return self._adreq_call("request", self._adreq().execute, rid, confirmed is True, confirmed_spend is True, by)

    def adreq_reject(self, rid: str) -> dict:
        return self._adreq_call("request", self._adreq().reject, rid)

    def adreq_delete(self, ids: list) -> dict:
        return self._adreq_call("deleted", self._adreq().delete, ids or [])

    def adreq_refresh(self, account_id: str) -> dict:
        """Tải lại danh sách nhóm / quảng cáo của tài khoản (sau khi đổi trên Ads Manager)."""
        return self._adreq_call("index", lambda: {k: len(v) if isinstance(v, list) else v
                                                  for k, v in self._adreq().index(account_id, refresh=True).items()})

    # ---- nghe nhóm Zalo (zca-js, không chính thức) → yêu cầu chờ duyệt
    def _zalo_call(self, fn, *args) -> dict:
        from ..zalo_listener import ZaloError

        try:
            res = fn(*args)
            return _ok(state=self._zalo.state(), **({"result": res} if isinstance(res, dict) else {}))
        except (ZaloError, OSError, ValueError) as exc:
            return _fail(exc)

    def zalo_state(self) -> dict:
        return _ok(state=self._zalo.state())

    def zalo_enable(self, on: bool) -> dict:
        """Bật / tắt nghe Zalo ngay (và nhớ cho lần mở app sau)."""
        settings.update({"zalo_listen": bool(on)})
        return self._zalo_call(self._zalo.start if on else self._zalo.stop)

    def zalo_set_groups(self, ids: list) -> dict:
        settings.update({"zalo_groups": [str(i) for i in ids or []][:50]})
        return _ok(state=self._zalo.state())

    def zalo_set_names(self, text: str) -> dict:
        """Tên nhóm cần nghe (mỗi dòng 1 nhóm) — chỉ nghe các nhóm khớp tên."""
        names = [n.strip() for n in str(text or "").replace(";", "\n").split("\n") if n.strip()][:20]
        settings.update({"zalo_group_names": "\n".join(names)})
        return _ok(state=self._zalo.state())

    def zalo_set_auto(self, mode: str, show_claude: bool = True) -> dict:
        from ..zalo_listener import AUTO_MODES

        if mode not in AUTO_MODES:
            return _fail("Chế độ không hợp lệ")
        settings.update({"zalo_auto": mode, "zalo_show_claude": bool(show_claude)})
        return _ok(state=self._zalo.state())

    def zalo_refresh_groups(self) -> dict:
        return self._zalo_call(self._zalo.refresh_groups)

    def zalo_logout(self) -> dict:
        settings.update({"zalo_listen": False})
        return self._zalo_call(self._zalo.logout)

    def zalo_send_claude(self, ids: list) -> dict:
        """Gửi các tin Zalo đã chọn cho Claude phân tích → yêu cầu chờ duyệt (1–15 phút)."""
        from ..ad_requests import AdRequestError
        from ..facebook import FacebookError
        from ..llm.base import LLMError
        from ..studio import StudioError

        try:
            return _ok(result=self._zalo.send_to_claude(ids or []), state=self._zalo.state())
        except Exception as exc:  # noqa: BLE001 — lỗi trình duyệt / Meta / Claude đều báo lên giao diện
            if not isinstance(exc, (AdRequestError, FacebookError, LLMError, StudioError, OSError, ValueError, RuntimeError)):
                raise
            return _fail(exc)

    def zalo_clear_inbox(self) -> dict:
        return self._zalo_call(self._zalo.clear_inbox)

    def _adbot_store(self):
        if getattr(self, "_adbot_obj", None) is None:
            from ..ad_assistant import AdAssistant

            self._adbot_obj = AdAssistant(settings, self._ads, self._license)
        return self._adbot_obj
