"""Classify provider messages without treating every limit as a daily quota."""
import re

NOTICE_HELP = {
    "DAILY_LIMIT": "Tài khoản đã chạm hạn mức ngày. Kiểm tra thời điểm làm mới hạn mức trên nhà cung cấp.",
    "INSUFFICIENT_CREDITS": "Tài khoản không đủ credit/lượt tạo cho yêu cầu này. Kiểm tra số dư và quyền dùng model trên nhà cung cấp.",
    "CONCURRENCY_LIMIT": "Tài khoản đã đạt số video đang tạo cùng lúc. Chờ video hiện tại hoàn tất rồi kiểm tra chat trước khi thử lại.",
    "RATE_LIMIT": "Nhà cung cấp đang giới hạn tần suất yêu cầu. Chờ theo thời gian được thông báo trước khi thử lại.",
    "ACCOUNT_LIMIT": "Nhà cung cấp đang giới hạn tài khoản. Kiểm tra thông báo gốc để biết điều kiện và thời gian áp dụng.",
    "CONTENT_POLICY": "Nhà cung cấp chặn nội dung hoặc ảnh tham chiếu.",
}
ACCOUNT_LIMIT_CODES = {"DAILY_LIMIT", "INSUFFICIENT_CREDITS", "CONCURRENCY_LIMIT", "RATE_LIMIT", "ACCOUNT_LIMIT"}


def classify_notice(text):
    rules = (
        ("CONCURRENCY_LIMIT", r"(?:only|maximum|max|limit).{0,35}\d+\s*videos?.{0,35}(?:same time|at once|at a time|simultaneous|concurrent)|(?:concurrent|simultaneous).{0,25}(?:limit|tasks?|videos?)|tối đa.{0,15}\d+.{0,20}video.{0,20}cùng lúc|正在生成.{0,15}(?:上限|最多)|同时.{0,15}(?:视频|任务).{0,15}(?:上限|最多)"),
        ("INSUFFICIENT_CREDITS", r"(?:insufficient|not enough|out of|no remaining).{0,20}(?:credits?|points?|balance)|(?:credits?|points?|balance).{0,20}(?:insufficient|exhausted|used up)|không đủ.{0,20}(?:credit|điểm|lượt|số dư)|hết.{0,10}credit|(?:积分|余额|点数|额度)不足"),
        ("DAILY_LIMIT", r"daily.{0,25}(?:limit|quota)|(?:limit|quota|maximum).{0,80}(?:today|per day)|try again tomorrow|hết hạn mức.{0,15}(?:ngày|hôm nay)|giới hạn.{0,35}(?:hôm nay|trong ngày)|(?:今日|当天|每日).{0,25}(?:上限|用完|次数)|今日.*上限"),
        ("RATE_LIMIT", r"rate.?limit|too many requests|try again in \d+|quá nhiều yêu cầu|thử lại sau \d+|请求过于频繁|操作频繁"),
        ("ACCOUNT_LIMIT", r"quota exceeded|account.{0,25}(?:limit|restricted)|(?:limit|quota).{0,25}(?:reached|exceeded)|hết hạn mức|limit tài khoản|tài khoản.{0,25}(?:giới hạn|hết lượt)|次数已用完|生成.{0,15}上限|次数.{0,10}上限"),
        ("CONTENT_POLICY", r"content policy|violat|nội dung.*(?:chặn|vi phạm)|ảnh.*bị chặn|不符合|违规"),
    )
    for code, pattern in rules:
        if re.search(pattern, str(text), re.I | re.S):
            return code
    return None
