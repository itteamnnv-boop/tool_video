import json
import re
import time
import unicodedata
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "video"


def unique_dir(path: Path) -> Path:
    """Tạo thư mục mới; nếu trùng tên (2 tác vụ cùng tiêu đề, cùng giây) thì thêm hậu tố _2, _3…"""
    candidate, n = path, 2
    while True:
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            candidate, n = path.with_name(f"{path.name}_{n}"), n + 1


# Windows: đọc đúng lúc luồng khác đang thay file (tmp → file thật) gặp PermissionError, và ngược lại → thử lại ngắn
RETRY_TRIES, RETRY_WAIT = 10, 0.05


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    for attempt in range(RETRY_TRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == RETRY_TRIES - 1:
                raise
            time.sleep(RETRY_WAIT)


def read_json(path: Path):
    for attempt in range(RETRY_TRIES):
        try:
            return json.loads(path.read_text("utf-8"))
        except (PermissionError, json.JSONDecodeError):
            if attempt == RETRY_TRIES - 1:
                raise
            time.sleep(RETRY_WAIT)
