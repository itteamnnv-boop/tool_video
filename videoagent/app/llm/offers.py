"""Model trình duyệt (Muse, ChatGPT…) không tạo ảnh / video mà ĐỀ XUẤT phương án khác hoặc hỏi lại
("Em có thể làm phiên bản khác… Chị muốn em làm một trong hai phương án đó không?").

Cài đặt offer_mode:
- "ask" (mặc định): gửi form duyệt lên giao diện (sự kiện offer_request) — Đồng ý / Trả lời khác / Dừng;
  không ai trả lời trong TIMEOUT_S giây → tự đồng ý để tác vụ (chạy hàng loạt, chạy đêm) không bị kẹt.
- "auto": tự đồng ý ngay.
"""
import re
import threading
import time
import uuid

from .base import LLMError

# câu hỏi lại / đề xuất phương án (tiếng Việt + tiếng Anh)
OFFER = re.compile(r"(\?|bạn có muốn|anh có muốn|chị có muốn|có muốn (mình|em|tôi)|muốn (mình|em|tôi) (làm|tạo|thử)|"
                   r"phương án|phiên bản (khác|an toàn|nhẹ)|có thể (thử|làm|tạo)|thay vì|would you like|do you want|"
                   r"shall i|should i|i can (try|create|make)|instead|alternative)", re.I)
AGREE = ("Đồng ý, bạn cứ làm theo phương án bạn vừa đề xuất (có nhiều phương án thì chọn phương án đầu tiên) và tạo "
         "luôn, giữ đúng tỉ lệ khung hình, không cần hỏi lại.")
NO_ASK = " Làm luôn, không cần hỏi lại."
TIMEOUT_S = 180
MODES = {"ask": "Hỏi tôi (form duyệt; không trả lời sau 3 phút thì tự đồng ý)", "auto": "Tự đồng ý đề xuất"}

_cfg = {"settings": None, "emit": None}
_pending: dict[str, dict] = {}
_lock = threading.Lock()


def configure(settings, emit) -> None:
    """Gọi một lần khi app khởi động (Api): đọc cài đặt offer_mode + kênh gửi sự kiện lên giao diện."""
    _cfg.update(settings=settings, emit=emit)


def looks_like_offer(text: str) -> bool:
    return bool(OFFER.search(text or ""))


def resolve(site: str, text: str, log, check_cancel, what: str = "ảnh") -> str:
    """Câu trả lời gửi lại cho model khi nó đề xuất / hỏi lại. Người dùng chọn Dừng → LLMError."""
    settings, emit = _cfg["settings"], _cfg["emit"]
    mode = (settings.get("offer_mode") if settings is not None else None) or "ask"
    short = " ".join((text or "").split())[-220:]
    if mode == "auto" or emit is None:
        log(f"{site} đề xuất thay vì tạo {what} — tự đồng ý: “{short}”", "warn")
        return AGREE
    rid = uuid.uuid4().hex[:10]
    slot = {"event": threading.Event(), "answer": None}
    with _lock:
        _pending[rid] = slot
    emit("offer_request", {"id": rid, "site": site, "what": what, "text": (text or "")[-1500:], "timeout": TIMEOUT_S})
    log(f"{site} đề xuất thay vì tạo {what}: “{short}” — đang chờ bạn duyệt (form trong app; "
        f"không trả lời sau {TIMEOUT_S // 60} phút thì tự đồng ý)", "warn")
    try:
        end = time.time() + TIMEOUT_S
        while time.time() < end and not slot["event"].wait(1):
            check_cancel()
    finally:
        with _lock:
            _pending.pop(rid, None)
        emit("offer_closed", {"id": rid})
    answer = slot["answer"]
    if answer is None:
        log(f"Không có trả lời sau {TIMEOUT_S // 60} phút — tự đồng ý đề xuất của {site}", "warn")
        return AGREE
    if answer.get("always") and settings is not None:
        settings.update({"offer_mode": "auto"})
        log("Từ giờ tự đồng ý khi model đề xuất phương án khác (đổi lại ở ⚙ Cài đặt)")
    if answer.get("choice") == "stop":
        raise LLMError(f"Đã dừng: bạn không đồng ý đề xuất của {site} — “{short}”")
    custom = " ".join(str(answer.get("text") or "").split())[:1500]
    if answer.get("choice") == "custom" and custom:
        log(f"Gửi {site} trả lời của bạn: “{custom[:160]}”")
        return custom + NO_ASK
    log(f"Bạn đồng ý đề xuất của {site}")
    return AGREE


def answer(rid: str, choice: str, text: str = "", always: bool = False) -> bool:
    """Giao diện gửi lựa chọn cho form duyệt; False nếu form đã hết hạn / không còn."""
    with _lock:
        slot = _pending.get(str(rid))
    if slot is None:
        return False
    slot["answer"] = {"choice": choice if choice in ("agree", "custom", "stop") else "agree", "text": text,
                      "always": bool(always)}
    slot["event"].set()
    return True


def pending() -> list[str]:
    with _lock:
        return list(_pending)
