"""Tìm ảnh tham khảo trên Pinterest (không cần đăng nhập) và tải về làm ảnh tham chiếu cho Tạo hình ảnh.

Dùng trình duyệt Chromium riêng (không phải profile của app) nên không tranh chấp với các tác vụ khác.
"""
import re
from pathlib import Path
from urllib.parse import quote

import requests
from playwright.sync_api import Error as PWError
from playwright.sync_api import sync_playwright

from .base import LLMError

SEARCH_URL = "https://www.pinterest.com/search/pins/?q={q}&rs=typed"
PINS_JS = """() => [...document.querySelectorAll('img[src*="i.pinimg.com"]')]
  .filter(i => i.naturalWidth >= 150 && !/\\/(60x60|75x75|30x30)\\//.test(i.src))
  .map(i => ({src: i.currentSrc || i.src, alt: i.alt || ''}))"""
SIZE_RE = re.compile(r"/(\d+x|originals)/")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0 Safari/537.36")


def _sized(url: str, size: str) -> str:
    return SIZE_RE.sub(f"/{size}/", url, count=1)


def search(keyword: str, limit: int = 12, log=print) -> list[dict]:
    """Trả về [{thumb, url, alt}] — thumb (236px) để xem trước, url (736px) để tải về."""
    keyword = (keyword or "").strip()
    if not keyword:
        raise LLMError("Hãy nhập từ khoá tìm ảnh Pinterest")
    results, seen = [], set()
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except PWError as exc:
            raise LLMError(f"Không mở được trình duyệt để tìm Pinterest: {exc}") from exc
        try:
            page = browser.new_context(viewport={"width": 1280, "height": 1400}, locale="vi-VN").new_page()
            page.goto(SEARCH_URL.format(q=quote(keyword)), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5000)
            for _ in range(6):
                for pin in page.evaluate(PINS_JS):
                    key = SIZE_RE.sub("/", pin["src"])
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({"thumb": _sized(pin["src"], "236x"), "url": _sized(pin["src"], "736x"),
                                    "alt": pin["alt"]})
                if len(results) >= limit:
                    break
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1500)
        except PWError as exc:
            raise LLMError(f"Lỗi khi tìm Pinterest: {exc}") from exc
        finally:
            browser.close()
    if not results:
        raise LLMError(f"Không tìm thấy ảnh Pinterest cho “{keyword}”")
    log(f"Pinterest: tìm thấy {len(results)} ảnh cho “{keyword}”")
    return results[:limit]


def download(urls: list[str], out_dir: Path, log=print) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, url in enumerate(urls, 1):
        data = b""
        for candidate in (url, _sized(url, "474x")):  # bản 736px có thể không tồn tại → lùi về 474px
            try:
                resp = requests.get(candidate, headers={"User-Agent": UA, "Referer": "https://www.pinterest.com/"},
                                    timeout=30)
            except requests.RequestException:
                continue
            if resp.ok and resp.content[:3] in (b"\xff\xd8\xff", b"\x89PN", b"RIF"):
                data = resp.content
                break
        if not data:
            log(f"Không tải được ảnh Pinterest {i}: {url}", "warn")
            continue
        ext = ".png" if data[:3] == b"\x89PN" else ".webp" if data[:3] == b"RIF" else ".jpg"
        path = out_dir / f"pin_{i}{ext}"
        path.write_bytes(data)
        paths.append(path)
    return paths
