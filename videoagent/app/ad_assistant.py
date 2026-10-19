"""🤖 Trợ lý quảng cáo Meta: chat với model (trình duyệt / API) → model phân tích yêu cầu và ĐIỀN FORM quảng cáo
(mục tiêu, bài viết, ngân sách, thời gian, độ tuổi, giới tính, quốc gia, sở thích) → bản nháp chờ duyệt →
người dùng duyệt: tạo tạm dừng / lên lịch chạy / chạy ngay.

An toàn tiền quảng cáo: model CHỈ đề xuất. Mọi chiến dịch tạo bằng facebook_ads.create_boost; chạy ngay / theo lịch
(ACTIVE) chỉ khi người dùng bấm duyệt + xác nhận trong app — ghi lại người duyệt và thời điểm.
"""
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .facebook import FacebookError
from .facebook_ads import OBJECTIVES
from .llm.base import extract_json
from .paths import DATA_DIR

STORE = DATA_DIR / "ad_assistant"
MAX_CHAT = 60
STATUSES = {"draft": "Nháp", "pending": "Chờ duyệt", "paused": "Đã tạo — tạm dừng", "scheduled": "Đã lên lịch",
            "running": "Đang chạy", "error": "Lỗi"}
MODES = {"paused": "PAUSED", "schedule": "ACTIVE", "now": "ACTIVE"}
DEFAULT_FORM = {"account_id": "", "page_id": "", "post_id": "", "post_preview": "", "post_picture": "",
                "objective": "engagement", "name": "",
                "daily_budget": "", "days": 7, "start_at": "", "countries": "VN", "age_min": 22, "age_max": 55,
                "gender": "all", "interests": []}

PROMPT = """Bạn là chuyên gia chạy quảng cáo Meta (Facebook / Instagram) cho doanh nghiệp Việt Nam. Hãy trò chuyện với người
dùng, PHÂN TÍCH yêu cầu và ĐIỀN FORM quảng cáo (quảng bá 1 bài viết có sẵn của fanpage) sao cho hiệu quả nhất.

Mục tiêu có thể chọn: {objectives}
Tiền tệ tài khoản quảng cáo: {currency}. Fanpage: {page}.
Bài viết gần đây của fanpage (id · tương tác · nội dung):
{posts}

FORM HIỆN TẠI (JSON): {form}

Lịch sử trò chuyện:
{history}

Người dùng vừa nói: <<{message}>>

Quy tắc:
- Trả lời tiếng Việt, ngắn gọn, giải thích lý do chọn thông số; hỏi lại nếu thiếu thông tin quan trọng (sản phẩm, khu vực, ngân sách).
- Chỉ ĐỀ XUẤT — không bao giờ nói đã chạy quảng cáo; người dùng sẽ tự duyệt.
- "objective": một trong {keys}. "daily_budget": số (theo {currency}). "days": 1–90. "age_min"/"age_max": 18–65.
  "gender": all | male | female. "countries": mã 2 chữ cách dấu phẩy (VN…). "start_at": "YYYY-MM-DDTHH:MM" hoặc "" (chạy sớm nhất).
  "post_id": chọn bài phù hợp nhất trong danh sách (hoặc "" nếu chưa có bài phù hợp).
  "interest_keywords": 3–6 sở thích để nhắm (tiếng Anh, đúng kiểu sở thích của Meta, vd. Agriculture, Organic farming).
- Chỉ điền những trường cần đổi; trường không đổi thì bỏ qua.

Chỉ trả về MỘT object JSON:
{{"tra_loi": "…", "form": {{"objective": "…", "name": "…", "daily_budget": 100000, "days": 7, "start_at": "", "countries": "VN",
 "age_min": 25, "age_max": 55, "gender": "all", "post_id": "…"}}, "interest_keywords": ["…"],
 "chien_luoc": "chiến lược ngắn: đối tượng, thông điệp, cách tối ưu", "kpi": "kết quả dự kiến (ước lượng, ghi rõ là ước lượng)"}}"""


class AssistantError(RuntimeError):
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clean_form(raw: dict, base: dict | None = None) -> dict:
    """Chuẩn hoá form (giữ giá trị cũ khi trường mới không hợp lệ)."""
    form = {**DEFAULT_FORM, **(base or {})}
    raw = raw if isinstance(raw, dict) else {}
    for key in ("account_id", "page_id", "post_id"):
        if key in raw:
            form[key] = str(raw[key] or "").strip()[:60]
    if "post_preview" in raw:
        form["post_preview"] = str(raw["post_preview"] or "")[:300]
    if "post_picture" in raw:  # ảnh bài viết (hiện ở thẻ chiến lược) — chỉ nhận URL https
        pic = str(raw["post_picture"] or "").strip()
        form["post_picture"] = pic[:1000] if pic.startswith("https://") else ""
    if raw.get("objective") in OBJECTIVES:
        form["objective"] = raw["objective"]
    if "name" in raw:
        form["name"] = " ".join(str(raw["name"] or "").split())[:120]
    if "daily_budget" in raw:
        try:
            form["daily_budget"] = max(0.0, float(str(raw["daily_budget"]).replace(",", "").replace(" ", "") or 0)) or ""
        except ValueError:
            pass
    for key, lo, hi in (("days", 1, 90), ("age_min", 13, 65), ("age_max", 13, 65)):
        if key in raw:
            try:
                form[key] = max(lo, min(hi, int(float(raw[key]))))
            except (TypeError, ValueError):
                pass
    if form["age_min"] > form["age_max"]:
        form["age_min"], form["age_max"] = form["age_max"], form["age_min"]
    if raw.get("gender") in ("all", "male", "female"):
        form["gender"] = raw["gender"]
    if "countries" in raw:
        codes = [c.strip().upper() for c in str(raw["countries"] or "").split(",") if c.strip()]
        form["countries"] = ", ".join(c for c in codes if len(c) == 2 and c.isalpha()) or "VN"
    if "start_at" in raw:
        value = str(raw["start_at"] or "").strip()[:16]
        try:
            form["start_at"] = datetime.fromisoformat(value).strftime("%Y-%m-%dT%H:%M") if value else ""
        except ValueError:
            pass
    if isinstance(raw.get("interests"), list):
        form["interests"] = [{"id": str(i["id"]), "name": str(i.get("name") or "")[:80]} for i in raw["interests"]
                             if isinstance(i, dict) and str(i.get("id") or "").isdigit()][:25]
    return form


class AdAssistant:
    def __init__(self, settings, ads, license_mgr=None) -> None:
        self.settings = settings
        self.ads = ads
        self.license = license_mgr
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lưu trữ
    @staticmethod
    def _path(pid: str) -> Path:
        pid = str(pid or "")
        if not pid.replace("-", "").isalnum() or len(pid) > 40:
            raise AssistantError("Mã bản nháp không hợp lệ")
        return STORE / f"{pid}.json"

    def get(self, pid: str) -> dict:
        path = self._path(pid)
        if not path.is_file():
            raise AssistantError("Không tìm thấy bản nháp quảng cáo")
        return json.loads(path.read_text("utf-8"))

    def _save(self, plan: dict) -> dict:
        STORE.mkdir(parents=True, exist_ok=True)
        plan["updated_at"] = now()
        tmp = self._path(plan["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self._path(plan["id"]))
        return plan

    def list(self) -> list:
        out = []
        for f in STORE.glob("*.json") if STORE.is_dir() else []:
            try:
                p = json.loads(f.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            form = p.get("form") or {}
            ap = p.get("approval") or {}
            out.append({k: p.get(k) for k in ("id", "name", "status", "created_at", "updated_at")}
                       | {"budget": form.get("daily_budget"), "days": form.get("days"), "objective": form.get("objective"),
                          "start_at": form.get("start_at"), "countries": form.get("countries"),
                          "ages": f"{form.get('age_min')}–{form.get('age_max')}", "interests": len(form.get("interests") or []),
                          "post_preview": form.get("post_preview", ""), "post_picture": form.get("post_picture", ""),
                          "strategy": (p.get("strategy") or "")[:240], "messages": len(p.get("chat") or []),
                          "account_id": form.get("account_id", ""),
                          "currency": (ap.get("result") or {}).get("currency", ""),
                          "campaign_id": (ap.get("result") or {}).get("campaign_id", ""),
                          "approved_by": ap.get("by", ""), "approved_at": ap.get("at", ""), "error": ap.get("error", "")})
        return sorted(out, key=lambda x: x.get("updated_at") or "", reverse=True)

    def create(self, data: dict | None = None) -> dict:
        data = data or {}
        last = self.list()
        base = {}
        if last:  # bản nháp mới dùng lại tài khoản / fanpage của bản gần nhất
            try:
                prev = self.get(last[0]["id"])["form"]
                base = {"account_id": prev.get("account_id", ""), "page_id": prev.get("page_id", "")}
            except AssistantError:
                pass
        plan = {"id": f"ad-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}",
                "name": " ".join(str(data.get("name") or "").split())[:80] or f"Quảng cáo {datetime.now():%d/%m %H:%M}",
                "status": "draft", "created_at": now(), "form": clean_form(data.get("form") or {}, base),
                "interest_options": [], "strategy": "", "kpi": "", "chat": [], "approval": {}}
        return self._save(plan)

    def save(self, pid: str, data: dict) -> dict:
        with self._lock:
            plan = self.get(pid)
            if plan["status"] in ("scheduled", "running", "paused"):
                raise AssistantError("Quảng cáo đã tạo trên Meta — sửa / bật tắt ở màn Quảng cáo Facebook")
            if "name" in data:
                plan["name"] = " ".join(str(data["name"] or "").split())[:80] or plan["name"]
            if isinstance(data.get("form"), dict):
                plan["form"] = clean_form(data["form"], plan["form"])
                if plan["status"] == "pending":  # sửa sau khi gửi duyệt → về nháp, gửi duyệt lại
                    plan["status"] = "draft"
            for key in ("strategy", "kpi"):
                if key in data:
                    plan[key] = str(data[key] or "")[:2000]
            return self._save(plan)

    def clone(self, pid: str) -> dict:
        """Nhân bản chiến lược thành bản nháp mới (form + chiến lược; không chép lịch sử chat / kết quả duyệt)."""
        src = self.get(pid)
        plan = self.create({"name": f"{src['name']} (bản sao)"[:80], "form": src.get("form") or {}})
        plan.update(strategy=src.get("strategy", ""), kpi=src.get("kpi", ""), interest_options=src.get("interest_options") or [])
        return self._save(plan)

    def delete(self, pid: str) -> None:
        self._path(pid).unlink(missing_ok=True)

    # ------------------------------------------------------------------ chat → điền form
    def _posts(self, page_id: str) -> tuple[str, list]:
        """(danh sách bài gần đây cho prompt, các bài) của fanpage."""
        if not page_id:
            return "(chưa chọn fanpage)", []
        try:
            posts = self.ads.page_posts(page_id).get("posts", [])[:15]
        except FacebookError as exc:
            return f"(không đọc được bài viết: {exc})", []
        return "\n".join(f"- {p['id']} · {p.get('reactions') or 0} cảm xúc, {p.get('comments') or 0} bình luận · "
                         f"{' '.join((p.get('message') or '').split())[:140]}" for p in posts) or "(fanpage chưa có bài)", posts

    def chat(self, pid: str, message: str, *, model: str, profile: str = "", show_browser: bool = False, log=None) -> dict:
        """Gửi tin nhắn cho model; model trả lời + điền form. Trả về bản nháp đã cập nhật."""
        from .studio import ask_model

        message = " ".join(str(message or "").split())[:2000]
        if not message:
            raise AssistantError("Nhập yêu cầu trước")
        plan = self.get(pid)
        if plan["status"] in ("scheduled", "running", "paused"):
            raise AssistantError("Quảng cáo này đã tạo trên Meta — tạo bản nháp mới để lên quảng cáo khác")
        form = plan["form"]
        currency = ""
        if form.get("account_id"):
            try:
                currency = self.ads._currency_of(self.ads._act(form["account_id"]))
            except FacebookError:
                currency = ""
        pages = {p["id"]: p.get("name", "") for p in self.ads.status().get("pages", [])} if form.get("page_id") else {}
        history = "\n".join(f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['text'][:600]}"
                            for m in plan["chat"][-10:]) or "(chưa có)"
        posts_text, posts = self._posts(form.get("page_id"))
        prompt = PROMPT.format(
            objectives="; ".join(f"{k} = {v['name']}" for k, v in OBJECTIVES.items()), keys=", ".join(OBJECTIVES),
            currency=currency or "VND (chưa chọn tài khoản)",
            page=pages.get(form.get("page_id"), form.get("page_id") or "(chưa chọn)"), posts=posts_text,
            form=json.dumps({k: v for k, v in form.items() if k not in ("post_preview", "post_picture")}, ensure_ascii=False),
            history=history, message=message)

        def complete(text: str) -> bool:
            try:
                data = extract_json(text)
            except ValueError:
                return False
            return isinstance(data, dict) and bool(data.get("tra_loi"))

        text = ask_model(self.settings, {"model": model or "chatgpt_browser", "text_profile": profile,
                                         "show_browser": show_browser}, prompt, complete=complete,
                         what="phân tích quảng cáo", log=log,
                         system="Bạn là chuyên gia quảng cáo Meta. Chỉ đề xuất, không tự chạy quảng cáo.")
        try:
            data = extract_json(text)
        except ValueError:
            data = {"tra_loi": " ".join(str(text).split())[:2000]}
        if not isinstance(data, dict):
            data = {"tra_loi": str(data)[:2000]}
        plan = self.get(pid)  # đọc lại (người dùng có thể đã lưu trong lúc chờ)
        changes = data.get("form") if isinstance(data.get("form"), dict) else {}
        plan["form"] = clean_form(changes, plan["form"])
        if changes.get("post_id"):  # bài model chọn → xem trước + ảnh cho thẻ chiến lược
            post = next((x for x in posts if x.get("id") == plan["form"]["post_id"]), {})
            plan["form"] = clean_form({"post_preview": " ".join((post.get("message") or "").split()),
                                       "post_picture": post.get("picture") or ""}, plan["form"])
        keywords = [str(k).strip() for k in data.get("interest_keywords") or [] if str(k).strip()][:6]
        if keywords:
            options = self._resolve_interests(keywords, log)
            if options:
                plan["interest_options"] = options
                picked = {i["id"] for i in plan["form"]["interests"]}
                best = {}  # mỗi từ khoá chọn sẵn kết quả đầu tiên
                for o in options:
                    best.setdefault(o["keyword"], o)
                plan["form"]["interests"] += [{"id": o["id"], "name": o["name"]} for o in best.values() if o["id"] not in picked]
                plan["form"]["interests"] = plan["form"]["interests"][:25]
        for key, src in (("strategy", "chien_luoc"), ("kpi", "kpi")):
            if data.get(src):
                plan[key] = str(data[src])[:2000]
        if plan["name"].startswith("Quảng cáo ") and plan["form"].get("name"):
            plan["name"] = plan["form"]["name"][:80]
        plan["chat"] = (plan["chat"] + [{"role": "user", "text": message, "at": now()},
                                        {"role": "assistant", "text": str(data.get("tra_loi") or "(đã cập nhật form)")[:3000],
                                         "at": now(), "model": model,
                                         "changed": sorted(k for k in changes if k in DEFAULT_FORM) + (["interests"] if keywords else [])}])[-MAX_CHAT:]
        if plan["status"] == "pending":
            plan["status"] = "draft"
        return self._save(plan)

    def _resolve_interests(self, keywords: list, log=None) -> list:
        """Từ khoá sở thích model gợi ý → sở thích thật của Meta (id) để nhắm; lỗi / thiếu quyền thì bỏ qua."""
        out, seen = [], set()
        for kw in keywords:
            try:
                rows = self.ads.search_interests(kw, limit=3)
            except FacebookError as exc:
                if log:
                    log(f"Không tra được sở thích “{kw}”: {exc}")
                continue
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append({**r, "keyword": kw})
        return out[:24]

    # ------------------------------------------------------------------ duyệt
    def submit(self, pid: str) -> dict:
        plan = self.get(pid)
        problems = self.check(plan["form"])
        if problems:
            raise AssistantError("Chưa đủ thông tin: " + "; ".join(problems))
        if plan["status"] not in ("draft", "error"):
            raise AssistantError("Bản nháp không ở trạng thái gửi duyệt được")
        plan["status"] = "pending"
        plan["submitted_at"] = now()
        return self._save(plan)

    @staticmethod
    def check(form: dict) -> list:
        problems = []
        if not form.get("account_id"):
            problems.append("chọn tài khoản quảng cáo")
        if not form.get("page_id"):
            problems.append("chọn fanpage")
        if not form.get("post_id"):
            problems.append("chọn bài viết để quảng cáo")
        if not form.get("daily_budget"):
            problems.append("nhập ngân sách / ngày")
        return problems

    def approver(self) -> str:
        try:
            user = (self.license.status() or {}).get("user") or {}
            return user.get("email") or user.get("name") or "người dùng app"
        except Exception:  # license chưa sẵn sàng
            return "người dùng app"

    def approve(self, pid: str, mode: str, confirmed: bool) -> dict:
        """mode: paused (tạo tạm dừng) | schedule (chạy theo giờ bắt đầu) | now (chạy ngay). Chạy = tiêu tiền thật →
        cần confirmed=True (người dùng đã xác nhận trong hộp thoại)."""
        if mode not in MODES:
            raise AssistantError("Cách duyệt không hợp lệ")
        with self._lock:
            plan = self.get(pid)
            if plan["status"] not in ("pending", "error"):
                raise AssistantError("Chỉ duyệt được bản nháp đang chờ duyệt (bấm Gửi duyệt trước)")
            problems = self.check(plan["form"])
            if problems:
                raise AssistantError("Chưa đủ thông tin: " + "; ".join(problems))
            if MODES[mode] == "ACTIVE" and not confirmed:
                raise AssistantError("Chạy quảng cáo cần bạn xác nhận (tiêu tiền thật)")
            form = plan["form"]
            if mode == "schedule":
                if not form.get("start_at"):
                    raise AssistantError("Lên lịch cần giờ bắt đầu")
                if datetime.fromisoformat(form["start_at"]) <= datetime.now():
                    raise AssistantError("Giờ bắt đầu phải ở tương lai")
            who = self.approver()
            payload = {**form, "name": form.get("name") or plan["name"], "status": MODES[mode],
                       "start_at": form.get("start_at") if mode == "schedule" else "",
                       "confirmed_by": who if MODES[mode] == "ACTIVE" else ""}
            plan["approval"] = {"by": who, "at": now(), "mode": mode}
            try:
                result = self.ads.create_boost(payload)
            except FacebookError as exc:
                plan["status"] = "error"
                plan["approval"]["error"] = str(exc)[:500]
                self._save(plan)
                raise AssistantError(str(exc)) from exc
            plan["approval"]["result"] = result
            plan["status"] = {"paused": "paused", "schedule": "scheduled", "now": "running"}[mode]
            return self._save(plan)
