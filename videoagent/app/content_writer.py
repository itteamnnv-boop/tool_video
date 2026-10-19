"""Block "Tạo content bài viết": viết bài đăng Facebook bán hàng theo MẪU người dùng đưa, đúng thông tin sản phẩm.

- Model: chat trình duyệt (ChatGPT / Gemini / Grok / Dola — dùng profile đã đăng nhập), Gemini API, Claude API, OpenAI API
  (mọi khoá API nhập ở màn hình Cài đặt → API & kết nối).
- Mẫu chỉ để bắt chước bố cục, emoji, giọng văn; thông tin sản phẩm người dùng nhập là nguồn sự thật duy nhất.
- Kiểm tra sau khi viết: giá, số điện thoại, website, địa chỉ phải có NGUYÊN VĂN; không được xuất hiện giá / số điện thoại
  lạ (AI bịa hoặc chép từ mẫu).
- Lịch sử lưu ở DATA_DIR/content/history.json (200 lần gần nhất).
"""
import re
import time
import uuid
from datetime import datetime

from .browser_profiles import task_context
from .paths import DATA_DIR
from .util import read_json, write_json

HISTORY_FILE = DATA_DIR / "content" / "history.json"
HISTORY_MAX = 200
MAX_VARIANTS = 3
DEFAULT_TEMPLATE = """🌱 Bà con nào cây chậm đọt, rễ yếu, cây bị suy
tham khảo ngay Đạm ORGANIC nha
👉 ĐẠM ORGANIC BOSS 1 giúp bổ sung dinh dưỡng, hỗ trợ cây ra rễ, phục hồi sau thu hoạch, dưỡng đọt và xanh lá.
✅ Hỗ trợ phục hồi cây sau thời gian mang trái.
✅ Dưỡng rễ, giúp cây phát triển tốt hơn.
✅ Bổ sung dinh dưỡng cho cây ra đọt, phát triển lá.
✅ Sử dụng cho sầu riêng, mít, cam, bưởi và nhiều loại cây trồng khác.
💥 Chỉ 539.000đ/XÔ 22KG
Bà con đang dưỡng cây, kéo đọt hay phục hồi vườn sau thu hoạch thì tham khảo dòng này nha!
📞 0915 283 059 (Kiều Duy)
💬 Cần tư vấn cách sử dụng cho vườn mình, bà con cứ để lại bình luận hoặc nhắn tin trực tiếp nhé!
Website:https://phanbonkingfarm.com.vn/
Địa chỉ: 79 Nguyễn Thiện Thành, Khóm 4, Phường Hòa Thuận, Tỉnh Vĩnh Long
#DamOrganic #Boss1 #PhanBonHuuCo #DuongRe #PhucHoiCay #DiDot #XanhLa #SauRieng #CayAnTrai"""

# Thông tin sản phẩm: key → (nhãn, bắt buộc). Thứ tự = thứ tự đưa vào prompt.
FIELDS = {
    "name": ("Tên sản phẩm", True),
    "line": ("Dòng / loại sản phẩm (VD: Đạm Organic)", False),
    "problem": ("Vấn đề của cây trồng mà sản phẩm giải quyết", False),
    "benefits": ("Công dụng / lợi ích (mỗi dòng 1 ý)", True),
    "crops": ("Cây trồng phù hợp", False),
    "price": ("Giá bán", False),
    "spec": ("Quy cách (VD: Xô 22kg)", False),
    "promo": ("Khuyến mãi / ưu đãi", False),
    "hotline": ("Số điện thoại", False),
    "contact": ("Tên người tư vấn", False),
    "website": ("Website", False),
    "address": ("Địa chỉ", False),
    "hashtags": ("Hashtag gợi ý", False),
    "notes": ("Ghi chú thêm cho người viết", False),
}
VERBATIM = ("price", "hotline", "website", "address")  # phải có nguyên văn trong bài nếu người dùng nhập

BROWSER_MODELS = {"chatgpt_browser": "ChatGPT", "claude_browser": "Claude", "gemini_browser": "Gemini",
                  "grok_browser": "Grok", "dola_browser": "Dola", "muse_browser": "Muse (Meta)"}
CLAUDE_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
OPENAI_MODELS = ("gpt-5", "gpt-5-mini")

SYSTEM = ("Bạn là chuyên viên viết content bán hàng nông nghiệp trên Facebook cho bà con nông dân Việt Nam: giọng gần gũi "
          "(\"bà con\", \"nha\", \"nhé\"), câu ngắn, dễ đọc trên điện thoại. Bạn tuyệt đối không bịa thông tin sản phẩm.")


class ContentError(RuntimeError):
    pass


# ---------------------------------------------------------------- danh sách model
def models(settings) -> list[dict]:
    """Model dùng được cho block này, kèm trạng thái sẵn sàng (có khoá / cần đăng nhập)."""
    from .campaign import ai

    keys = ai.key_status()
    out = [{"id": mid, "name": f"{name} (trình duyệt)", "group": "Trình duyệt — tài khoản đã đăng nhập", "ready": True,
            "site": mid.removesuffix("_browser"), "note": f"Cần đăng nhập {name} trong Profile trình duyệt"}
           for mid, name in BROWSER_MODELS.items()]
    out.append({"id": "gemini_api", "name": f"Gemini API ({settings.get('gemini_model') or 'gemini-2.5-flash'})",
                "group": "API key", "ready": bool(settings.get("gemini_api_key")), "note": "Gemini API key ở Cài đặt → API & kết nối"})
    out += [{"id": f"api:{m}", "name": f"Claude · {m}", "group": "API key", "ready": keys["anthropic"],
             "note": "Khoá Anthropic ở Cài đặt → API & kết nối"} for m in CLAUDE_MODELS]
    out += [{"id": f"api:{m}", "name": f"OpenAI · {m}", "group": "API key", "ready": keys["openai"],
             "note": "Khoá OpenAI ở Cài đặt → API & kết nối"} for m in OPENAI_MODELS]
    return out


# ---------------------------------------------------------------- prompt
def clean_form(form: dict, required: bool = True) -> dict:
    """required=False: thông tin sản phẩm có thể đến từ văn bản (VD: dây nối trong Workflow) nên không bắt buộc ô nào."""
    product = {k: re.sub(r"[ \t]+", " ", str((form.get("product") or {}).get(k) or "")).strip()[:3000] for k in FIELDS}
    missing = [label for k, (label, need) in FIELDS.items() if need and not product[k]]
    if missing and required:
        raise ContentError("Hãy nhập: " + ", ".join(missing))
    template = str(form.get("template") or "").strip() or DEFAULT_TEMPLATE
    count = max(1, min(MAX_VARIANTS, int(form.get("count") or 1)))
    return {"product": product, "template": template[:4000], "count": count,
            "extra": str(form.get("extra") or "").strip()[:1000]}


def build_prompt(data: dict) -> str:
    product = data["product"]
    facts = "\n".join(f"- {FIELDS[k][0]}: {v}" for k, v in product.items() if v)
    verbatim = [FIELDS[k][0] for k in VERBATIM if product[k]]
    return f"""Viết bài đăng Facebook bán hàng cho sản phẩm dưới đây, theo đúng MẪU.

MẪU BÀI VIẾT (chỉ để bắt chước bố cục — KHÔNG chép thông tin sản phẩm trong mẫu):
<mau>
{data['template']}
</mau>

THÔNG TIN SẢN PHẨM (nguồn sự thật DUY NHẤT):
{facts}

QUY TẮC BẮT BUỘC:
1. Giữ đúng bố cục của mẫu: cùng thứ tự các khối, cùng emoji đầu dòng (🌱 👉 ✅ 💥 📞 💬 …), cùng kiểu dòng Website / Địa chỉ /
   hashtag cuối bài, độ dài tương đương. Số dòng ✅ theo số công dụng thực có (3–5 dòng).
2. Chỉ dùng thông tin trong THÔNG TIN SẢN PHẨM. {('Chép NGUYÊN VĂN, không đổi định dạng: ' + ', '.join(verbatim) + '.') if verbatim else ''}
   Thông tin nào không có thì BỎ HẲN dòng đó trong bài (không để trống, không tự nghĩ ra giá, số điện thoại, website,
   địa chỉ, khối lượng, thành phần, cam kết).
3. Tuyệt đối không dùng tên sản phẩm, giá, số điện thoại, website, địa chỉ, người tư vấn của MẪU.
4. Dòng mở đầu nêu đúng vấn đề của bà con mà sản phẩm giải quyết; dòng 👉 giới thiệu tên sản phẩm VIẾT HOA như mẫu.
5. Hashtag: 6–10 cái, tiếng Việt không dấu viết liền (VD #PhanBonHuuCo), về tên sản phẩm, công dụng, cây trồng.
6. Không dùng markdown (**, ##), không giải thích, không thêm lời chào ngoài bài.
{('7. Yêu cầu thêm của người dùng: ' + data['extra']) if data['extra'] else ''}
Viết {data['count']} phiên bản khác nhau về câu mở đầu và cách diễn đạt (giữ đúng thông tin). Đặt MỖI phiên bản giữa thẻ
<bai> và </bai>, ngoài các thẻ không viết gì khác."""


def split_variants(text: str, count: int) -> list[str]:
    parts = [p.strip() for p in re.findall(r"<bai>(.*?)</bai>", text or "", re.S | re.I) if p.strip()]
    if not parts:  # model bỏ thẻ → coi cả câu trả lời là 1 bài
        stripped = re.sub(r"</?bai>", "", text or "", flags=re.I).strip()
        parts = [stripped] if stripped else []
    return [p.replace("**", "").strip() for p in parts[:count]]  # Facebook không hiểu markdown in đậm


# ---------------------------------------------------------------- xuống dòng theo mẫu
LABEL_LINES = ("Website", "Địa chỉ", "Hotline", "Fanpage", "Zalo")  # dòng nhãn hay gặp ở cuối bài


def _lead(line: str) -> str:
    """Emoji/biểu tượng mở đầu dòng của mẫu ("" nếu dòng bắt đầu bằng chữ, số hoặc #)."""
    match = re.match(r"([^\w\s#\"'(\[]+)", line.strip())
    return match.group(1).strip() if match else ""


def _split_before(line: str, words: str) -> list[str] | None:
    """Tách dòng trước lần xuất hiện ĐẦU TIÊN của `words` giữa dòng (không tách ngay sau emoji đầu dòng).
    None = không tách."""
    for match in re.finditer(rf"[ \t]+(?={re.escape(words)}\b)", line):
        head = line[:match.start()].strip()
        if head and _lead(head) != head:  # phía trước có chữ thật, không chỉ là emoji
            return [head, line[match.end():]]
    return None


def reflow(text: str, template: str) -> str:
    """Model trình duyệt hiển thị markdown nên xuống dòng đơn bị gộp thành dấu cách khi đọc lại → bài dồn 1 dòng.
    Khôi phục xuống dòng theo bố cục mẫu: trước emoji đầu dòng của mẫu, trước Website/Địa chỉ, trước cụm hashtag cuối,
    trước câu mở đầu giống các dòng chữ thường trong mẫu. Bài đã xuống dòng đủ thì giữ nguyên."""
    tpl_lines = [ln.strip() for ln in template.splitlines() if ln.strip()]
    if len(tpl_lines) < 3 or len([ln for ln in text.splitlines() if ln.strip()]) >= max(3, len(tpl_lines) // 2):
        return text
    out = text
    for lead in sorted({_lead(ln) for ln in tpl_lines} - {""}, key=len, reverse=True):
        out = re.sub(rf"[ \t]*(?<!^)({re.escape(lead)})", r"\n\1", out, flags=re.M)
    for label in LABEL_LINES:
        if any(ln.lower().startswith(label.lower()) for ln in tpl_lines):
            out = re.sub(rf"[ \t]+({re.escape(label)}\s*:)", r"\n\1", out, flags=re.I)
    out = re.sub(r"[ \t]+((?:#\w+[ \t]*){2,})$", r"\n\1", out.rstrip())  # cụm hashtag cuối bài
    starts = {" ".join(ln.split()[:2]) for ln in tpl_lines
              if not _lead(ln) and not ln.startswith("#") and len(ln.split()) >= 3
              and not any(ln.lower().startswith(lb.lower()) for lb in LABEL_LINES)}
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for words in starts:  # VD mẫu có dòng "tham khảo ngay…", "Bà con đang…" bắt đầu bằng chữ thường → tách 1 lần
        for i, ln in enumerate(lines):
            parts = _split_before(ln, words)
            if parts:
                lines[i:i + 1] = parts
                break
    return "\n".join(lines)


# ---------------------------------------------------------------- kiểm tra thông tin
def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


PRICE_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+\s*(?:đ|đồng|vnđ|vnd|k)?|\d+\s*(?:k|nghìn|ngàn|triệu)\b", re.I)
PHONE_RE = re.compile(r"(?:\+?84|0)(?:[\s.\-]?\d){8,10}")


def check(text: str, product: dict) -> list[str]:
    """Các điểm sai lệch so với thông tin sản phẩm (rỗng = đạt)."""
    issues = []
    body = _squash(text)
    if product["price"] and _squash(product["price"]) not in body and _digits(product["price"]) not in _digits(text):
        issues.append(f"Thiếu giá đúng nguyên văn: {product['price']}")
    if product["hotline"] and _digits(product["hotline"]) not in _digits(text):
        issues.append(f"Thiếu số điện thoại: {product['hotline']}")
    if product["website"]:
        site = re.sub(r"^https?://(www\.)?", "", product["website"].lower()).rstrip("/")
        if site not in body:
            issues.append(f"Thiếu website: {product['website']}")
    if product["address"] and _squash(product["address"]) not in body:
        issues.append(f"Địa chỉ không đúng nguyên văn: {product['address']}")
    given = _digits(" ".join(product[k] for k in ("price", "promo", "spec", "notes", "benefits")))
    for match in PRICE_RE.findall(text):
        if _digits(match) and _digits(match) not in given:
            issues.append(f"Có con số/giá không có trong thông tin sản phẩm: {match.strip()}")
    phones = _digits(product["hotline"] + " " + product["notes"])
    for match in PHONE_RE.findall(text):
        if _digits(match) not in phones:
            issues.append(f"Có số điện thoại lạ: {match.strip()}")
    return list(dict.fromkeys(issues))


# ---------------------------------------------------------------- gọi model
def _call(model: str, prompt: str, settings, profile: str, show_browser: bool, log) -> tuple[str, dict]:
    if model.startswith("api:"):
        from .campaign.ai import RoleAI
        from .campaign.store import CampaignError

        try:
            return RoleAI("content", log, lambda: None).complete(model[4:], SYSTEM, prompt)
        except CampaignError as exc:
            raise ContentError(str(exc)) from exc
    from .llm import LLMError, make_provider

    if model not in BROWSER_MODELS and model != "gemini_api":
        raise ContentError("Model không hợp lệ")
    try:
        provider = make_provider(model, settings, show_browser=show_browser)
        with task_context(profile, log=log):  # profile "" = tự chọn profile rảnh gán cho trang đó
            text = provider.generate(SYSTEM + "\n\n" + prompt)
    except LLMError as exc:
        raise ContentError(str(exc)) from exc
    return text, {"model": model}


def write_one(product: dict, template: str, extra: str, model: str, settings, *, source: str = "", profile: str = "",
              show_browser: bool = False, log=lambda *a: None, fix_issues: bool = True) -> tuple[str, list[str]]:
    """Viết 1 bài (dùng cho block Workflow). source = thông tin sản phẩm dạng văn bản từ block trước (coi là dữ liệu).
    Bài sai thông tin → tự viết lại 1 lần kèm danh sách lỗi. Trả về (bài, các điểm còn sai)."""
    notes = "\n".join(x for x in (str(product.get("notes") or "").strip(), source.strip()) if x)
    data = clean_form({"product": {**product, "notes": notes}, "template": template, "count": 1, "extra": extra},
                      required=not source.strip())
    prompt = build_prompt(data)
    text = ""
    for attempt in (1, 2):
        answer, _ = _call(model, prompt, settings, profile, show_browser, log)
        variants = split_variants(answer, 1)
        if not variants:
            raise ContentError("Model không trả về bài viết nào — thử lại hoặc đổi model")
        text = reflow(variants[0], data["template"])
        issues = check(text, data["product"])
        if not issues or not fix_issues or attempt == 2:
            return text, issues
        log(f"Bài viết sai {len(issues)} điểm so với thông tin sản phẩm — yêu cầu viết lại", "warn")
        prompt = (build_prompt(data) + "\n\nBẢN VỪA VIẾT CÒN SAI CÁC ĐIỂM SAU — viết lại cho đúng, vẫn đặt trong <bai></bai>:\n- "
                  + "\n- ".join(issues))
    return text, issues


def generate(form: dict, settings, log=lambda *a: None) -> dict:
    data = clean_form(form)
    model = str(form.get("model") or "")
    started = time.time()
    text, meta = _call(model, build_prompt(data), settings, str(form.get("browser_profile") or ""),
                       bool(form.get("show_browser")), log)
    variants = [{"text": t, "issues": check(t, data["product"])}
                for t in (reflow(v, data["template"]) for v in split_variants(text, data["count"]))]
    if not variants:
        raise ContentError("Model không trả về bài viết nào — thử lại hoặc đổi model")
    name = next((m["name"] for m in models(settings) if m["id"] == model), model)
    entry = {"id": uuid.uuid4().hex[:10], "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "model": model,
             "model_name": name, "product": data["product"]["name"], "variants": variants,
             "seconds": round(time.time() - started, 1), **{k: meta[k] for k in ("usd", "tokens_in", "tokens_out") if k in meta}}
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(HISTORY_FILE, [entry, *history()][:HISTORY_MAX])
    return entry


def history() -> list[dict]:
    return read_json(HISTORY_FILE) if HISTORY_FILE.exists() else []


def delete_history(entry_id: str) -> list[dict]:
    items = [h for h in history() if h.get("id") != entry_id]
    write_json(HISTORY_FILE, items)
    return items
