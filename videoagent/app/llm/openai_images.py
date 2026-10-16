"""OpenAI Images API (GPT Image): tạo ảnh từ prompt, hoặc chỉnh/ghép từ ảnh tham chiếu (/images/edits)."""
import base64
from pathlib import Path

import requests

from .base import LLMError

API = "https://api.openai.com/v1/images"
DEFAULT_MODEL = "gpt-image-1"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
PORTRAIT = {"9:16", "2:3", "3:4", "4:5"}
LANDSCAPE = {"16:9", "3:2", "4:3", "21:9"}


def size_for(aspect: str) -> str:
    """GPT Image chỉ có 3 kích thước — app cắt lại đúng tỉ lệ sau khi tải về."""
    if aspect in PORTRAIT:
        return "1024x1536"
    if aspect in LANDSCAPE:
        return "1536x1024"
    return "1024x1024"


def generate_images(prompt: str, out_dir: Path, *, api_key: str, model: str = "", aspect: str = "1:1",
                    count: int = 1, quality: str = "auto", images: list[Path] | None = None, log=print) -> list[bytes]:
    if not api_key:
        raise LLMError("Chưa nhập OpenAI API key trong Cài đặt")
    out: list[bytes] = []
    for _ in range(count):  # model có thể trả ít ảnh hơn n (vd. chỉ hỗ trợ n=1) → gọi bù cho đủ
        out += _request(prompt, api_key=api_key, model=model, aspect=aspect, n=count - len(out), quality=quality,
                        images=images, log=log)
        if len(out) >= count:
            break
        log(f"OpenAI mới trả {len(out)}/{count} ảnh — gọi thêm…")
    return out[:count]


def _request(prompt: str, *, api_key: str, model: str, aspect: str, n: int, quality: str,
             images: list[Path] | None, log) -> list[bytes]:
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"model": model or DEFAULT_MODEL, "prompt": prompt, "n": n, "size": size_for(aspect),
              "quality": quality or "auto"}
    try:
        if images:  # /images/edits nhận nhiều ảnh tham chiếu (image[])
            files = [("image[]", (p.name, Path(p).read_bytes(), MIME.get(Path(p).suffix.lower(), "image/png")))
                     for p in images]
            log(f"Gửi prompt + {len(images)} ảnh tham chiếu cho OpenAI ({params['model']})…")
            resp = requests.post(f"{API}/edits", headers=headers, timeout=600,
                                 data={k: str(v) for k, v in params.items()}, files=files)
        else:
            log(f"Gửi prompt cho OpenAI ({params['model']})…")
            resp = requests.post(f"{API}/generations", headers=headers, json=params, timeout=600)
    except requests.RequestException as exc:
        raise LLMError(f"Không kết nối được OpenAI: {exc}") from exc
    if resp.status_code != 200:
        try:
            message = resp.json().get("error", {}).get("message", "")
        except ValueError:
            message = resp.text[:300]
        raise LLMError(f"OpenAI lỗi {resp.status_code}: {message}")
    out = []
    for item in resp.json().get("data", []):
        if item.get("b64_json"):
            out.append(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            out.append(requests.get(item["url"], timeout=120).content)
    if not out:
        raise LLMError("OpenAI không trả ảnh nào")
    return out
