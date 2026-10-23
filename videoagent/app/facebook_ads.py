"""Quản lý quảng cáo Facebook (Meta Marketing API) — dùng chung User Access Token với FacebookManager.

Cần thêm quyền ads_read (xem) và ads_management (bật/tắt, đổi ngân sách, tạo quảng cáo) khi tạo token.
Mọi quảng cáo tạo từ app đều ở trạng thái PAUSED — người dùng tự bật khi đã kiểm tra, tránh tiêu tiền ngoài ý muốn.
"""
import json
import re
import time
from datetime import datetime, timedelta

import requests

from .facebook import RATE, FacebookError, FacebookManager

ADS_PERMISSIONS = ("ads_read", "ads_management")
DATE_PRESETS = ("today", "yesterday", "last_7d", "last_30d", "this_month", "last_month", "maximum")
INSIGHT_FIELDS = "spend,impressions,reach,clicks,ctr,cpc,cpm,frequency,actions"
LEVELS = {  # level → (đường dẫn con của đối tượng cha, các trường)
    "campaign": ("campaigns", "id,name,objective,status,effective_status,daily_budget,lifetime_budget,"
                              "budget_remaining,start_time,stop_time"),
    "adset": ("adsets", "id,name,status,effective_status,daily_budget,lifetime_budget,budget_remaining,"
                        "optimization_goal,start_time,end_time,campaign_id"),
    "ad": ("ads", "id,name,status,effective_status,adset_id,campaign_id,creative{thumbnail_url,object_story_id}"),
}
# Hành động hiển thị ở cột "Kết quả" (thứ tự ưu tiên)
RESULT_ACTIONS = (
    ("onsite_conversion.messaging_conversation_started_7d", "tin nhắn"),
    ("lead", "khách tiềm năng"),
    ("offsite_conversion.fb_pixel_purchase", "mua hàng"),
    ("link_click", "lượt nhấp link"),
    ("video_view", "lượt xem video"),
    ("post_engagement", "tương tác"),
)
# Mục tiêu khi tạo quảng cáo từ bài viết của page
OBJECTIVES = {
    "engagement": {"name": "Tương tác bài viết", "objective": "OUTCOME_ENGAGEMENT",
                   "optimization_goal": "POST_ENGAGEMENT", "destination_type": "ON_POST"},
    "reach": {"name": "Tiếp cận nhiều người", "objective": "OUTCOME_AWARENESS", "optimization_goal": "REACH"},
    "video": {"name": "Lượt xem video (ThruPlay)", "objective": "OUTCOME_ENGAGEMENT",
              "optimization_goal": "THRUPLAY", "destination_type": "ON_VIDEO"},
}
# Tiền tệ không có đơn vị lẻ — ngân sách gửi lên Meta giữ nguyên (các tiền tệ khác nhân 100)
NO_MINOR_UNIT = {"VND", "JPY", "KRW", "IDR", "CLP", "COP", "CRC", "HUF", "ISK", "PYG", "TWD"}
STATUSES = ("ACTIVE", "PAUSED")
ACCOUNTS_TTL = 600  # giây — danh sách tài khoản QC dùng chung cho mọi màn (đỡ tốn lượt gọi API của App)


class AdsManager:
    def __init__(self, fb: FacebookManager) -> None:
        self._fb = fb
        self._currency: dict[str, str] = {}  # act_id → tiền tệ (để đổi ngân sách)
        self._accounts: tuple[float, list] | None = None  # (lúc lấy, danh sách) — đệm ACCOUNTS_TTL giây

    # ------------------------------------------------------------------ tiện ích
    @property
    def _token(self) -> str:
        token = self._fb._data.get("user_token")
        if not token:
            raise FacebookError("Chưa kết nối Facebook — nhập User Access Token ở Cài đặt → API & kết nối")
        return token

    def _get(self, path: str, **params) -> dict:
        return self._fb._get(path, access_token=self._token, **params)

    def _all(self, path: str, **params) -> list:
        items, after = [], None
        params.setdefault("limit", 100)  # nơi gọi có thể đặt limit riêng (VD 200 khi tải cả tài khoản)
        for _ in range(20):  # tối đa 20 trang × limit
            if after:
                params["after"] = after
            data = self._get(path, **params)
            items += data.get("data", [])
            paging = data.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if not paging.get("next") or not after:
                break
        return items

    def _post(self, path: str, **data) -> dict:
        payload = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in data.items()}
        payload["access_token"] = self._token
        RATE.check(path)
        try:
            resp = requests.post(f"{self._fb._graph}/{path}", data=payload, timeout=60)
        except requests.RequestException as exc:
            raise FacebookError(f"Không kết nối được Facebook: {exc}") from exc
        RATE.observe(resp, path)
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {}
        if resp.status_code != 200 or "error" in body:
            RATE.fail(resp, body, path)
        return body

    @staticmethod
    def _act(account_id: str) -> str:
        account_id = str(account_id or "").strip()
        if not account_id.removeprefix("act_").isdigit():
            raise FacebookError("Tài khoản quảng cáo không hợp lệ")
        return account_id if account_id.startswith("act_") else f"act_{account_id}"

    @staticmethod
    def _check_id(object_id: str) -> str:
        object_id = str(object_id or "").strip()
        if not object_id.replace("_", "").isdigit():
            raise FacebookError("ID không hợp lệ")
        return object_id

    @staticmethod
    def _factor(currency: str) -> int:
        return 1 if (currency or "").upper() in NO_MINOR_UNIT else 100

    def _money(self, minor, currency: str):
        return None if minor in (None, "") else round(int(minor) / self._factor(currency), 2)

    @staticmethod
    def _insights(raw: dict | None) -> dict:
        row = ((raw or {}).get("data") or [{}])[0]
        actions = {a.get("action_type"): float(a.get("value") or 0) for a in row.get("actions") or []}
        result = next(({"count": actions[k], "label": label} for k, label in RESULT_ACTIONS if actions.get(k)), None)
        num = lambda k: float(row[k]) if row.get(k) not in (None, "") else 0.0  # noqa: E731
        return {"spend": num("spend"), "impressions": int(num("impressions")), "reach": int(num("reach")),
                "clicks": int(num("clicks")), "ctr": num("ctr"), "cpc": num("cpc"), "cpm": num("cpm"),
                "frequency": num("frequency"), "result": result}

    # ------------------------------------------------------------------ đọc
    def status(self) -> dict:
        perms = self._fb._data.get("permissions", [])
        return {"logged_in": bool(self._fb._data.get("user_token")),
                "missing_permissions": [p for p in ADS_PERMISSIONS if p not in perms],
                "objectives": {k: v["name"] for k, v in OBJECTIVES.items()},
                "pages": [{"id": p["id"], "name": p.get("name", "")} for p in self._fb._data.get("pages", [])]}

    def accounts(self, refresh: bool = False) -> list:
        """Tài khoản quảng cáo của người dùng — đệm 10 phút; lỗi (VD bị Meta giới hạn) mà có bản cũ thì dùng bản cũ."""
        hit = self._accounts
        if hit and not refresh and time.time() - hit[0] < ACCOUNTS_TTL:
            return [dict(a) for a in hit[1]]
        try:
            out = self._load_accounts(force=refresh)  # bấm làm mới = thao tác tay → gọi thật
        except FacebookError:
            if hit:
                return [dict(a) for a in hit[1]]
            raise
        self._accounts = (time.time(), out)
        return [dict(a) for a in out]

    def _load_accounts(self, force: bool = False) -> list:
        rows = self._all("me/adaccounts", _force=force, fields="id,account_id,name,account_status,currency,timezone_name,"
                                                 "amount_spent,balance,spend_cap,business{name}")
        out = []
        for a in rows:
            cur = a.get("currency", "")
            self._currency[a["id"]] = cur
            out.append({"id": a["id"], "account_id": a.get("account_id", ""), "name": a.get("name", ""),
                        "currency": cur, "timezone": a.get("timezone_name", ""),
                        "active": a.get("account_status") == 1, "status_code": a.get("account_status"),
                        "amount_spent": self._money(a.get("amount_spent"), cur),
                        "balance": self._money(a.get("balance"), cur),
                        "spend_cap": self._money(a.get("spend_cap"), cur) if a.get("spend_cap") not in ("0", 0) else None,
                        "business": (a.get("business") or {}).get("name", "")})
        return out

    def _currency_of(self, act: str) -> str:
        if act not in self._currency:
            self._currency[act] = self._get(act, fields="currency").get("currency", "")
        return self._currency[act]

    def overview(self, account_id: str, date_preset: str = "last_7d") -> dict:
        act = self._act(account_id)
        preset = date_preset if date_preset in DATE_PRESETS else "last_7d"
        return {"currency": self._currency_of(act), "insights": self._insights(self._get(f"{act}/insights",
                fields=INSIGHT_FIELDS, date_preset=preset))}

    def list(self, account_id: str, level: str, parent_id: str = "", date_preset: str = "last_7d") -> dict:
        """Danh sách chiến dịch / nhóm quảng cáo / quảng cáo kèm số liệu theo khoảng thời gian."""
        if level not in LEVELS:
            raise FacebookError("Cấp quảng cáo không hợp lệ")
        act = self._act(account_id)
        preset = date_preset if date_preset in DATE_PRESETS else "last_7d"
        edge, fields = LEVELS[level]
        owner = self._check_id(parent_id) if parent_id else act
        rows = self._all(f"{owner}/{edge}", fields=f"{fields},insights.date_preset({preset}){{{INSIGHT_FIELDS}}}")
        cur = self._currency_of(act)
        items = []
        for r in rows:
            creative = r.get("creative") or {}
            items.append({
                "id": r["id"], "name": r.get("name", ""), "status": r.get("status"),
                "effective_status": r.get("effective_status"), "objective": r.get("objective", ""),
                "optimization_goal": r.get("optimization_goal", ""),
                "daily_budget": self._money(r.get("daily_budget"), cur),
                "lifetime_budget": self._money(r.get("lifetime_budget"), cur),
                "start_time": r.get("start_time"), "end_time": r.get("stop_time") or r.get("end_time"),
                "thumbnail": creative.get("thumbnail_url", ""), "post_id": creative.get("object_story_id", ""),
                "insights": self._insights(r.get("insights")),
            })
        items.sort(key=lambda i: (i["effective_status"] != "ACTIVE", -i["insights"]["spend"]))
        return {"level": level, "currency": cur, "items": items}

    # ------------------------------------------------------------------ thay đổi (có tiền thật — UI phải xác nhận)
    def set_status(self, object_id: str, status: str) -> dict:
        status = str(status).upper()
        if status not in STATUSES:
            raise FacebookError("Trạng thái chỉ được ACTIVE hoặc PAUSED")
        self._post(self._check_id(object_id), status=status)
        return {"id": object_id, "status": status}

    def set_budget(self, account_id: str, object_id: str, daily_budget) -> dict:
        try:
            amount = float(daily_budget)
        except (TypeError, ValueError):
            raise FacebookError("Ngân sách phải là số") from None
        if amount <= 0:
            raise FacebookError("Ngân sách phải lớn hơn 0")
        cur = self._currency_of(self._act(account_id))
        self._post(self._check_id(object_id), daily_budget=int(round(amount * self._factor(cur))))
        return {"id": object_id, "daily_budget": amount, "currency": cur}

    # ------------------------------------------------------------------ tạo quảng cáo từ bài viết của page
    POST_FIELDS = "id,message,story,created_time,full_picture,permalink_url,status_type"
    POST_STATS = ("reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares,"
                  "is_eligible_for_promotion")

    def page_posts(self, page_id: str, after: str = "") -> dict:
        """Bài viết đã đăng của page (25 bài/lần) kèm tương tác; `after` = con trỏ trang tiếp theo."""
        page = self._fb._page(page_id)
        token = page.get("access_token")
        if not token:
            raise FacebookError("Thiếu page token — tải lại danh sách Fanpage")
        params = {"access_token": token, "limit": 25}
        if after:
            params["after"] = after
        path = f"{self._check_id(page_id)}/published_posts"
        try:
            data = self._fb._get(path, fields=f"{self.POST_FIELDS},{self.POST_STATS}", **params)
        except FacebookError:  # một số trường thống kê có thể bị chặn theo quyền/phiên bản → lấy bản cơ bản
            data = self._fb._get(path, fields=self.POST_FIELDS, **params)
        posts = []
        for p in data.get("data", []):
            count = lambda key: ((p.get(key) or {}).get("summary") or {}).get("total_count")  # noqa: E731
            posts.append({
                "id": p["id"], "message": (p.get("message") or p.get("story") or "")[:500],
                "created_time": p.get("created_time"), "picture": p.get("full_picture", ""),
                "link": p.get("permalink_url", ""), "type": p.get("status_type", ""),
                "reactions": count("reactions"), "comments": count("comments"),
                "shares": (p.get("shares") or {}).get("count", 0 if "reactions" in p else None),
                "eligible": p.get("is_eligible_for_promotion"),
            })
        paging = data.get("paging") or {}
        return {"posts": posts, "after": ((paging.get("cursors") or {}).get("after") or "") if paging.get("next") else ""}

    def search_interests(self, query: str, limit: int = 6) -> list:
        """Sở thích (detailed targeting) của Meta theo từ khoá → [{id, name, size, path}] để nhắm quảng cáo."""
        query = " ".join(str(query or "").split())[:80]
        if not query:
            return []
        data = self._get("search", type="adinterest", q=query, limit=max(1, min(25, int(limit))), locale="vi_VN")
        return [{"id": str(r["id"]), "name": r.get("name", ""), "path": " › ".join(r.get("path") or []),
                 "size": r.get("audience_size_upper_bound") or r.get("audience_size") or 0}
                for r in data.get("data", []) if r.get("id")]

    def create_ad_in_adset(self, account_id: str, adset_id: str, post_id: str, status: str = "PAUSED",
                           confirmed_by: str = "", name: str = "") -> dict:
        """Thêm 1 quảng cáo (bài viết có sẵn của page) vào NHÓM QUẢNG CÁO CÓ SẴN. Mặc định PAUSED;
        ACTIVE (chạy ngay, tiêu tiền) BẮT BUỘC có confirmed_by — người dùng đã duyệt trong app."""
        status = str(status or "PAUSED").upper()
        if status not in STATUSES:
            raise FacebookError("Trạng thái chỉ được ACTIVE hoặc PAUSED")
        if status == "ACTIVE" and not str(confirmed_by or "").strip():
            raise FacebookError("Chạy quảng cáo cần người dùng xác nhận duyệt — chưa có xác nhận nên không tạo")
        act = self._act(account_id)
        adset_id = self._check_id(adset_id)
        story = str(post_id or "").strip()
        if not re.fullmatch(r"\d+_\d+", story):
            raise FacebookError("Thiếu id bài viết dạng <page>_<bài> — kiểm tra lại link bài")
        name = (name or "").strip() or f"VideoAgent {datetime.now():%d/%m %H:%M} · {story.split('_')[1]}"
        creative = self._post(f"{act}/adcreatives", name=f"{name} — creative", object_story_id=story)
        ad = self._post(f"{act}/ads", name=name, adset_id=adset_id, creative={"creative_id": creative["id"]}, status=status)
        return {"ad_id": ad["id"], "creative_id": creative["id"], "adset_id": adset_id, "post_id": story, "status": status}

    def create_boost(self, form: dict) -> dict:
        """Tạo chiến dịch → nhóm quảng cáo → quảng cáo từ 1 bài viết có sẵn.
        Mặc định PAUSED. status=ACTIVE (chạy ngay / chạy theo lịch start_at) tiêu tiền thật → BẮT BUỘC có confirmed_by
        (người dùng đã bấm duyệt trong app); thiếu thì từ chối."""
        status = str(form.get("status") or "PAUSED").upper()
        if status not in STATUSES:
            raise FacebookError("Trạng thái chỉ được ACTIVE hoặc PAUSED")
        if status == "ACTIVE" and not str(form.get("confirmed_by") or "").strip():
            raise FacebookError("Chạy quảng cáo cần người dùng xác nhận duyệt — chưa có xác nhận nên không tạo")
        act = self._act(form.get("account_id"))
        page_id = self._check_id(form.get("page_id"))
        post_id = self._check_id(form.get("post_id"))
        goal = OBJECTIVES.get(form.get("objective") or "engagement")
        if goal is None:
            raise FacebookError("Mục tiêu quảng cáo không hợp lệ")
        try:
            budget, days = float(form.get("daily_budget") or 0), int(form.get("days") or 0)
            age_min, age_max = int(form.get("age_min") or 18), int(form.get("age_max") or 65)
        except (TypeError, ValueError):
            raise FacebookError("Ngân sách, số ngày và độ tuổi phải là số") from None
        if budget <= 0 or not 1 <= days <= 90:
            raise FacebookError("Nhập ngân sách/ngày > 0 và số ngày chạy từ 1 đến 90")
        if not 13 <= age_min <= age_max <= 65:
            raise FacebookError("Độ tuổi phải trong khoảng 13–65")
        countries = [c.strip().upper() for c in str(form.get("countries") or "VN").split(",") if c.strip()]
        if not countries or any(len(c) != 2 or not c.isalpha() for c in countries):
            raise FacebookError("Quốc gia nhập mã 2 chữ, cách nhau dấu phẩy (VD: VN, US)")
        cur = self._currency_of(act)
        name = (form.get("name") or "").strip() or f"VideoAgent {datetime.now():%d/%m %H:%M}"
        story_id = post_id if "_" in post_id else f"{page_id}_{post_id}"

        targeting = {"geo_locations": {"countries": countries}, "age_min": age_min, "age_max": age_max,
                     "targeting_automation": {"advantage_audience": 0}}
        genders = {"male": [1], "female": [2]}.get(form.get("gender"))
        if genders:
            targeting["genders"] = genders
        interests = [{"id": str(i["id"]), "name": str(i.get("name") or "")} for i in form.get("interests") or []
                     if isinstance(i, dict) and str(i.get("id") or "").isdigit()][:25]
        if interests:  # sở thích chi tiết (OR giữa các mục)
            targeting["flexible_spec"] = [{"interests": interests}]

        now = datetime.now().astimezone()
        start = now + timedelta(minutes=3 if status == "ACTIVE" else 10)
        if form.get("start_at"):  # lịch chạy: giờ máy (datetime-local) → Meta tự bắt đầu đúng giờ
            try:
                wanted = datetime.fromisoformat(str(form["start_at"]))
            except ValueError:
                raise FacebookError("Giờ bắt đầu không hợp lệ") from None
            wanted = wanted.astimezone() if wanted.tzinfo else wanted.replace(tzinfo=now.tzinfo)
            if wanted > start:
                start = wanted
            if wanted > now + timedelta(days=180):
                raise FacebookError("Giờ bắt đầu quá xa (tối đa 6 tháng tới)")

        campaign = self._post(f"{act}/campaigns", name=name, objective=goal["objective"], status=status,
                              special_ad_categories=[], is_adset_budget_sharing_enabled="false")
        created = {"campaign_id": campaign["id"]}
        try:
            adset = {"name": f"{name} — nhóm", "campaign_id": campaign["id"], "status": status,
                     "daily_budget": int(round(budget * self._factor(cur))), "billing_event": "IMPRESSIONS",
                     "optimization_goal": goal["optimization_goal"], "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                     "promoted_object": {"page_id": page_id}, "targeting": targeting,
                     "start_time": start.isoformat(timespec="seconds"),
                     "end_time": (start + timedelta(days=days)).isoformat(timespec="seconds")}
            if goal.get("destination_type"):
                adset["destination_type"] = goal["destination_type"]
            created["adset_id"] = self._post(f"{act}/adsets", **adset)["id"]
            creative = self._post(f"{act}/adcreatives", name=f"{name} — creative", object_story_id=story_id)
            created["ad_id"] = self._post(f"{act}/ads", name=f"{name} — quảng cáo", adset_id=created["adset_id"],
                                          creative={"creative_id": creative["id"]}, status=status)["id"]
        except FacebookError as exc:  # dọn chiến dịch dở dang để không để rác trong Ads Manager
            try:
                self._post(campaign["id"], status="DELETED")
            except FacebookError:
                pass
            raise FacebookError(f"{exc} (đã huỷ chiến dịch tạo dở)") from exc
        return {**created, "name": name, "status": status, "start_time": start.isoformat(timespec="minutes"),
                "end_time": (start + timedelta(days=days)).isoformat(timespec="minutes"), "currency": cur,
                "daily_budget": budget, "max_spend": budget * days}
