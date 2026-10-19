"""Công cụ cho dây chuyền chiến dịch: đọc trang web sản phẩm, Markdown → HTML/PDF, trang xem ảnh/video.

Ảnh và video của chiến dịch do chức năng Tạo hình ảnh / Tạo video của hệ thống làm (xem pipeline.py) —
module này không vẽ ảnh, không đặt chữ.
"""
import html as htmllib
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


# ====================================================================== đọc trang web sản phẩm
def _text_of(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", html)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", html))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def read_pages(urls: list, log, check_cancel, max_pages: int = 6) -> list[dict]:
    """Đọc các link người dùng đưa + vài trang sản phẩm/giới thiệu CÙNG tên miền. Không đi sang tên miền khác."""
    pages, seen = [], set()
    for url in urls:
        start = urlsplit(url)
        if start.scheme not in ("http", "https") or not start.hostname:
            continue
        queue = [url]
        while queue and len(pages) < max_pages:
            check_cancel()
            link = queue.pop(0).split("#")[0]
            if link in seen:
                continue
            seen.add(link)
            try:
                resp = requests.get(link, timeout=20, headers={"User-Agent": UA})
            except requests.RequestException as exc:
                log(f"Không đọc được {link}: {exc}", "warn")
                continue
            if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
                log(f"Bỏ qua {link} (HTTP {resp.status_code})", "warn")
                continue
            resp.encoding = resp.apparent_encoding or resp.encoding
            raw = resp.text
            title = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
            imgs = [urljoin(link, m) for m in re.findall(r'(?i)<img[^>]+src=["\']([^"\']+)["\']', raw)]
            og = re.findall(r'(?i)<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', raw)
            pages.append({"url": link, "title": htmllib.unescape(title.group(1).strip()) if title else "",
                          "text": _text_of(raw)[:12000],
                          "images": [u for u in og + imgs if re.search(r"\.(png|jpe?g|webp)", u, re.I)][:12]})
            log(f"Đã đọc trang: {link}")
            if link == url:  # thêm vài trang cùng tên miền có vẻ là trang sản phẩm / giới thiệu
                for href in re.findall(r'(?i)<a[^>]+href=["\']([^"\'#]+)', raw):
                    nxt = urljoin(link, href)
                    if urlsplit(nxt).hostname == start.hostname and re.search(r"san-pham|product|gioi-thieu|about", nxt, re.I):
                        queue.append(nxt)
    return pages


def download_image(url: str, dest: Path) -> Path | None:
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": UA})
    except requests.RequestException:
        return None
    head = resp.content[:4]
    if resp.status_code == 200 and (head == b"\x89PNG" or head[:3] == b"\xff\xd8\xff" or head == b"RIFF"):
        dest.write_bytes(resp.content)
        return dest
    return None


# ====================================================================== Markdown → HTML / PDF
PAGE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;600;800&display=swap');
body{font-family:'Be Vietnam Pro','Segoe UI',sans-serif;max-width:760px;margin:32px auto;padding:0 20px;color:#1b1f1a;line-height:1.6}
h1,h2,h3{line-height:1.25} h1{font-size:26px} pre{white-space:pre-wrap;background:#f5f7f2;border:1px solid #dfe5d8;
border-radius:10px;padding:16px;font-family:inherit;font-size:15px} table{border-collapse:collapse} td,th{border:1px solid #ddd;padding:6px 10px}
img{max-width:100%} .gallery{display:flex;gap:16px;flex-wrap:wrap} .gallery figure{margin:0;width:340px}
"""


def md_to_html(md_text: str, title: str) -> str:
    import markdown

    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>{htmllib.escape(title)}</title>'
            f"<style>{PAGE_CSS}</style></head><body>{body}</body></html>")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle", timeout=60000)
            page.pdf(path=str(pdf_path), format="A4", print_background=True,
                     margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        finally:
            browser.close()


def gallery_html(cdir: Path, title: str, images: list[dict]) -> str:
    figs = "".join(
        f'<figure><img src="05-hinh-anh/{htmllib.escape(i["file"])}"><figcaption><b>{htmllib.escape(i["key"])}</b> · '
        f'{htmllib.escape(i.get("idea", ""))}</figcaption></figure>'
        for i in images if (cdir / "05-hinh-anh" / i["file"]).exists())
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Ảnh · {htmllib.escape(title)}</title>'
            f'<style>{PAGE_CSS}</style></head><body><h1>Ảnh chiến dịch: {htmllib.escape(title)}</h1>'
            f'<div class="gallery">{figs}</div></body></html>')


def video_html(title: str, videos: list[dict]) -> str:
    """Trang xem các video chiến dịch: videos = [{key, label, file}] (file tương đối với thư mục chiến dịch)."""
    figs = "".join(f'<figure><video src="{htmllib.escape(v["file"])}" controls playsinline></video><figcaption>'
                   f'<b>{htmllib.escape(v["key"])}</b> · {htmllib.escape(v.get("label", ""))}</figcaption></figure>'
                   for v in videos)
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Video · {htmllib.escape(title)}</title>'
            f'<style>{PAGE_CSS} video{{display:block;width:100%;border-radius:12px;background:#000}}</style></head>'
            f'<body><h1>Video chiến dịch: {htmllib.escape(title)}</h1><div class="gallery">{figs}</div></body></html>')
