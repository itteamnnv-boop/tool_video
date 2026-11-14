"""Trợ lý nuôi kênh: khung chat với Claude (claude.ai qua trình duyệt) làm theo 1 SKILL điều phối người dùng sửa được —
hỏi đủ thông tin cần thiết, gợi ý, tổng hợp yêu cầu rồi dựng + chạy trọn quy trình Ảnh → Video → Hậu kỳ → Đăng bài.

Mỗi kênh là 1 bảng Canvas (board.json có "channel": true) — chạy bằng chính bộ máy Canvas (khối, kiểm tra trước khi
chạy, đăng bài chờ duyệt, tự điều phối chấm / làm lại); cuộc trò chuyện là trợ lý Canvas của bảng đó (assistant.json).
Skill: bản mặc định đóng gói ở assets/skills/nuoi-kenh.md; bản người dùng sửa lưu ở <DATA_DIR>/skills/nuoi-kenh.md.
"""
from __future__ import annotations

from datetime import datetime

from .paths import ASSETS_DIR, DATA_DIR
from .util import read_json

SKILL_NAME = "nuoi-kenh.md"
DEFAULT_SKILL = ASSETS_DIR / "skills" / SKILL_NAME
USER_SKILL = DATA_DIR / "skills" / SKILL_NAME
MAX_SKILL_CHARS = 30000
# Hồ sơ yêu cầu (trình bày kiểu Chiến dịch): Claude điền dần qua cuộc trò chuyện; mục trống = còn thiếu
BRIEF_FIELDS = {
    "muc_tieu": "Mục tiêu & kênh đăng",
    "san_pham": "Sản phẩm (ảnh, tên, công dụng, giá / SĐT nếu đăng bán)",
    "nhan_vat": "Nhân vật",
    "boi_canh": "Bối cảnh & góc máy",
    "dinh_dang": "Định dạng (số ảnh / cảnh, tỉ lệ, thời lượng)",
    "loi_thoai": "Lời thoại · giọng đọc · phụ đề · nhạc",
    "y_tuong": "Ý tưởng / thông điệp chính",
    "dang_bai": "Đăng bài (Fanpage, thời điểm, caption)",
}
# gửi kèm MỖI lượt (không nằm trong skill người dùng sửa → sửa skill không làm hỏng định dạng)
BRIEF_FORMAT = ("HỒ SƠ YÊU CẦU: trong khối ```json luôn thêm 3 trường:\n"
                "\"ho_so\": {" + ", ".join(f"\"{k}\": \"{v} — tóm tắt điều đã biết, \\\"\\\" nếu chưa có\"" for k, v in BRIEF_FIELDS.items())
                + "},\n\"con_thieu\": [\"câu hỏi ngắn cho người dùng về thông tin còn thiếu, tối đa 4 câu\"],\n"
                "\"san_sang\": true khi đã đủ thông tin để dựng và chạy cả quy trình (người dùng đã chốt), ngược lại false.\n"
                "Ghi lại toàn bộ hồ sơ mỗi lượt (giữ điều đã biết, thêm điều mới). Mục không cần cho việc này ghi \"không cần\".")


class ChannelError(ValueError):
    pass


# ------------------------------------------------------------------ skill điều phối
def default_skill() -> str:
    try:
        return DEFAULT_SKILL.read_text("utf-8")
    except OSError:
        return ""


def skill_text() -> str:
    """Skill đang dùng: bản người dùng sửa (nếu có) — không thì bản mặc định."""
    try:
        text = USER_SKILL.read_text("utf-8")
        if text.strip():
            return text
    except OSError:
        pass
    return default_skill()


def skill_info() -> dict:
    return {"text": skill_text(), "custom": USER_SKILL.is_file(), "path": str(USER_SKILL)}


def save_skill(text: str) -> dict:
    text = str(text or "").replace("\r\n", "\n").strip()
    if len(text) < 50:
        raise ChannelError("Skill quá ngắn — viết hướng dẫn điều phối cho Claude (hoặc bấm Khôi phục mặc định)")
    if len(text) > MAX_SKILL_CHARS:
        raise ChannelError(f"Skill dài quá {MAX_SKILL_CHARS} ký tự — rút gọn bớt")
    USER_SKILL.parent.mkdir(parents=True, exist_ok=True)
    USER_SKILL.write_text(text + "\n", "utf-8")
    return skill_info()


def reset_skill() -> dict:
    USER_SKILL.unlink(missing_ok=True)
    return skill_info()


# ------------------------------------------------------------------ kênh = bảng Canvas có cờ "channel"
def list_channels(canvas) -> list[dict]:
    out = []
    for b in canvas.list():
        try:
            board = read_json(canvas.root / b["id"] / "board.json")
        except (OSError, ValueError):
            continue
        if board.get("channel"):
            out.append(b)
    return out


def create_channel(canvas, name: str = "") -> dict:
    name = " ".join(str(name or "").split())[:80] or f"Kênh {datetime.now():%d/%m %H:%M}"
    bid = canvas.create(name)["id"]
    canvas._edit(bid, lambda board: board.update(channel=True))
    return canvas.public(canvas.load(bid))


def run_check(canvas, bid: str, fresh: bool = False) -> tuple[dict, list[dict]]:
    """Trước khi chạy cả quy trình: kế hoạch chạy + những thứ còn thiếu (lỗi) kèm tên khối để khung chat hỏi người dùng."""
    board = canvas.load(bid)
    plan = canvas.plan(board, "all", "", fresh)
    nodes = {n["id"]: n for n in board["nodes"]}
    issues = []
    for i in canvas.check(board, plan["run"]):
        if i["level"] != "error":
            continue
        n = nodes.get(i["node"]) or {}
        issues.append({**i, "title": n.get("title") or canvas.label(n) if n else i["node"],
                       "wtype": n.get("wtype", ""), "kind": n.get("kind", "")})
    return plan, issues
