"""📈 Trợ lý TVC · quảng cáo: Claude gợi ý setup (10_quang_cao/goi_y.md) rồi tạo YÊU CẦU QUẢNG CÁO = Kế hoạch quảng cáo
trạng thái CHỜ DUYỆT trong màn Trợ lý quảng cáo (app/ad_assistant.py) cho đúng bài Facebook vừa đăng.

- Không tạo gì trên Facebook: duyệt (tạo TẠM DỪNG / lên lịch / chạy ngay — có xác nhận riêng) vẫn ở Trợ lý quảng cáo.
- Claude chỉ nhận id / tên / tiền tệ tài khoản quảng cáo; token ở trong app.
- Dữ liệu: <dự án>/10_quang_cao/yeu_cau.json {plan_id, status, account, summary, created}.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .util import read_json, write_json

ADS_DIR = "10_quang_cao"
LIVE = ("paused", "scheduled", "running")


class TvcAdsError(RuntimeError):
    pass


class TvcAds:
    def __init__(self, ads, adbot, facebook, viewer) -> None:
        self.ads = ads  # FacebookAds
        self.adbot = adbot  # () -> AdAssistant (tạo trễ như màn Trợ lý quảng cáo)
        self.facebook = facebook  # FacebookManager — tra lại id bài của Reels
        self.viewer = viewer

    # ------------------------------------------------------------------ chỉ đọc
    def accounts(self) -> list[dict]:
        if self.ads is None:
            return []
        return [{"id": a["id"], "name": a.get("name", ""), "currency": a.get("currency", ""), "active": bool(a.get("active"))}
                for a in self.ads.accounts()]

    @staticmethod
    def objectives() -> dict:
        from .facebook_ads import OBJECTIVES

        return {k: v["name"] for k, v in OBJECTIVES.items()}

    @staticmethod
    def _meta(proj: Path, name: str) -> dict:
        f = proj / name
        try:
            data = read_json(f) if f.is_file() else {}
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def plan_status(self, plan_id: str) -> dict:
        """Trạng thái thật của kế hoạch (người dùng có thể đã duyệt / xoá ở Trợ lý quảng cáo)."""
        if not plan_id:
            return {}
        try:
            plan = self.adbot().get(plan_id)
        except Exception:  # noqa: BLE001 — đã xoá
            return {"status": "deleted"}
        ap = plan.get("approval") or {}
        return {"status": plan.get("status", ""), "campaign_id": (ap.get("result") or {}).get("campaign_id", ""),
                "error": ap.get("error", ""), "approved_by": ap.get("by", "")}

    # ------------------------------------------------------------------ id bài để chạy quảng cáo
    def _post_id(self, fb: dict) -> str:
        """id bài dạng <page>_<post>. Reels vừa đăng đôi khi chỉ có id video → hỏi lại Facebook (token ở app)."""
        pid = str(fb.get("fb_post_id") or "")
        if "_" in pid:
            return pid
        vid = str(fb.get("fb_video_id") or pid)
        if vid and self.facebook is not None:
            try:
                _, token = self.facebook._page_token(fb.get("page_id", ""))
                found, _ = self.facebook._video_post(vid, token)
            except Exception:  # noqa: BLE001
                found = ""
            if found:
                return found if "_" in found else f"{fb.get('page_id')}_{found}"
        return ""

    # ------------------------------------------------------------------ tạo yêu cầu quảng cáo (kế hoạch chờ duyệt)
    def request(self, project: str, args: dict) -> dict:
        proj = self.viewer._proj(project)
        fb = self._meta(proj, "09_facebook/post.json")
        if fb.get("status") != "posted":
            raise TvcAdsError("Bài Facebook của dự án chưa đăng — đăng bài trước (fb_publish) rồi mới tạo yêu cầu quảng cáo")
        post_id = self._post_id(fb)
        if not post_id:
            raise TvcAdsError("Chưa lấy được id bài trên Facebook (Reels có thể cần vài phút) — thử lại sau ít phút")
        accounts = {a["id"]: a for a in self.accounts()}
        acc = str(args.get("account_id") or "")
        if acc and not acc.startswith("act_"):
            acc = f"act_{acc}"
        if acc not in accounts:
            raise TvcAdsError("account_id không có trong danh sách tài khoản (dùng fb_ad_accounts)")
        old = self._meta(proj, f"{ADS_DIR}/yeu_cau.json")
        if old.get("plan_id") and self.plan_status(old["plan_id"]).get("status") in ("pending", "draft", *LIVE):
            raise TvcAdsError(f"Dự án đã có yêu cầu quảng cáo {old['plan_id']} — người dùng huỷ trên app rồi mới tạo lại")
        store = self.adbot()
        keywords = [str(k) for k in args.get("interest_keywords") or [] if str(k).strip()][:6]
        interests, seen = [], set()
        for row in store._resolve_interests(keywords) if keywords else []:  # sở thích khớp nhất của mỗi từ khoá
            if row.get("keyword") not in seen:
                seen.add(row.get("keyword"))
                interests.append({"id": row["id"], "name": row.get("name", "")})
        name = str(args.get("name") or "").strip() or f"TVC {project} {datetime.now():%d/%m}"
        form = {"account_id": acc, "page_id": fb.get("page_id", ""), "post_id": post_id,
                "post_preview": " ".join(str(fb.get("caption") or "").split())[:300],
                "objective": args.get("objective") or "video", "name": name, "daily_budget": args.get("daily_budget"),
                "days": args.get("days") or 7, "start_at": args.get("start_at") or "", "countries": args.get("countries") or "VN",
                "age_min": args.get("age_min") or 22, "age_max": args.get("age_max") or 55,
                "gender": args.get("gender") or "all", "interests": interests}
        plan = store.create({"name": name, "form": form})
        plan = store.save(plan["id"], {"form": form, "strategy": str(args.get("strategy") or ""),
                                       "kpi": str(args.get("kpi") or "")})
        try:
            plan = store.submit(plan["id"])
        except Exception as exc:  # noqa: BLE001 — thiếu thông tin: xoá bản nháp hỏng, báo Claude sửa
            store.delete(plan["id"])
            raise TvcAdsError(str(exc)) from exc
        f = plan["form"]
        summary = {"name": plan["name"], "account": accounts[acc].get("name") or acc,
                   "currency": accounts[acc].get("currency", ""),
                   "objective": self.objectives().get(f["objective"], f["objective"]), "daily_budget": f["daily_budget"],
                   "days": f["days"], "start_at": f["start_at"], "countries": f["countries"],
                   "ages": f"{f['age_min']}–{f['age_max']}",
                   "gender": {"all": "Tất cả", "male": "Nam", "female": "Nữ"}.get(f["gender"], f["gender"]),
                   "interests": [i["name"] for i in f["interests"]], "page": fb.get("page", ""), "post_url": fb.get("url", ""),
                   "strategy": plan.get("strategy", "")[:600], "kpi": plan.get("kpi", "")[:300]}
        out = {"plan_id": plan["id"], "status": "pending", "account": acc, "summary": summary,
               "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        d = proj / ADS_DIR
        d.mkdir(parents=True, exist_ok=True)
        write_json(d / "yeu_cau.json", out)
        return out

    def cancel(self, project: str) -> dict:
        """Huỷ yêu cầu (xoá kế hoạch CHỜ DUYỆT). Kế hoạch đã tạo trên Meta thì không huỷ ở đây."""
        proj = self.viewer._proj(project)
        req = self._meta(proj, f"{ADS_DIR}/yeu_cau.json")
        if not req.get("plan_id") or req.get("status") == "cancelled":
            raise TvcAdsError("Dự án chưa có yêu cầu quảng cáo")
        st = self.plan_status(req["plan_id"]).get("status")
        if st in LIVE:
            raise TvcAdsError("Chiến dịch đã tạo trên Meta — bật / tắt ở màn Quảng cáo Facebook")
        if st != "deleted":
            self.adbot().delete(req["plan_id"])
        req["status"] = "cancelled"
        write_json(proj / ADS_DIR / "yeu_cau.json", req)
        return req

    @staticmethod
    def text(data, error: bool = False) -> dict:
        out = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
        if error:
            out["is_error"] = True
        return out
