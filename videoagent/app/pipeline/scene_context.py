"""Biến dữ liệu khung hình thành context cho template Jinja2."""
import random
import re

ASPECT_CLASS = {"9:16": "portrait", "16:9": "landscape", "1:1": "square", "4:5": "square"}
DEFAULT_PALETTE = {"accent": "#d4f06a", "bg": "#0d120e", "bg2": "#1f2a1a"}
# scene.html nằm ở <video>/scenes/NN/ → đường dẫn tương đối tới <video>/assets/
ASSET_PREFIX = "../../assets/"
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")


def is_video_name(name: str) -> bool:
    return name.lower().endswith(VIDEO_EXT)


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def split_words(headline: str, highlight: str) -> list[dict]:
    marks = {_norm(w) for w in (highlight or "").split()} - {""}
    return [{"text": w, "hl": _norm(w) in marks} for w in headline.split()]


def make_series(seed: str, trend: str, n: int = 14) -> list[float]:
    """Chuỗi số giả lập (0..100) theo xu hướng — dùng cho biểu đồ trang trí, không phải dữ liệu thật."""
    rnd = random.Random(seed)
    drift = {"up": 1.8, "down": -1.8}.get(trend, 0.0)
    value, out = 50.0, []
    for _ in range(n + 1):
        value += drift + rnd.uniform(-5, 5)
        out.append(value)
    lo, hi = min(out), max(out)
    span = (hi - lo) or 1
    return [round(12 + 76 * (v - lo) / span, 2) for v in out]


def make_candles(series: list[float]) -> list[dict]:
    n = len(series) - 1
    candles = []
    for i in range(n):
        o, c = series[i], series[i + 1]
        wick = abs(c - o) * 0.4 + 2.5
        candles.append({"x": round((i + 0.5) * 100 / n, 2), "top": round(100 - max(o, c), 2),
                        "height": round(max(abs(c - o), 1.2), 2), "wick_top": round(100 - max(o, c) - wick, 2),
                        "wick_bottom": round(100 - min(o, c) + wick, 2), "up": c >= o})
    return candles


def line_path(series: list[float]) -> str:
    step = 100 / (len(series) - 1)
    return " ".join(f"{'M' if i == 0 else 'L'}{i * step:.2f},{100 - v:.2f}" for i, v in enumerate(series))


def build_context(job: dict, scene: dict) -> dict:
    series = make_series(f"{job['id']}-{scene['index']}", scene.get("trend", "flat"))
    assets = job.get("assets") or {}
    products = [ASSET_PREFIX + name for name in assets.get("products") or []]
    palette = {**DEFAULT_PALETTE, **(assets.get("palette") or {})}
    comment = job.get("comment") or {}
    comment_name = comment.get("name", "")
    offer = job.get("offer") or {}
    media = scene.get("media") or {}  # cảnh dùng video nền: {"file", "start"}
    current = products[(scene["index"] - 1) % len(products)] if products else ""
    return {
        "bg_video": ASSET_PREFIX + media["file"] if media else "",
        "bg_start": media.get("start", 0),
        "offer_price": offer.get("price", ""),
        "offer_old_price": offer.get("old_price", ""),
        "offer_perk": offer.get("perk", ""),
        "offer_contact": offer.get("contact", ""),
        "features": job.get("features") or [],
        "comment_name": comment_name,
        "comment_text": comment.get("text", ""),
        "comment_initials": "".join(w[0] for w in comment_name.split()[-2:]).upper() or "KH",
        "product_image": "" if media or is_video_name(current) else current,
        "product_images": products,
        "layout_image": ASSET_PREFIX + assets["layout_image"] if assets.get("layout_image") else "",
        "accent": palette["accent"],
        "bg": palette["bg"],
        "bg2": palette["bg2"],
        "title": job.get("title", ""),
        "brand": job.get("brand", ""),
        "kicker": scene.get("kicker", ""),
        "headline": scene.get("headline", ""),
        "highlight": scene.get("highlight", ""),
        "words": split_words(scene.get("headline", ""), scene.get("highlight", "")),
        "subtext": scene.get("subtext", ""),
        "stat": scene.get("stat", ""),
        "trend": scene.get("trend", "flat"),
        "index": scene["index"],
        "index2": f"{scene['index']:02d}",
        "total": len(job["scenes"]),
        "duration": round(float(scene.get("duration", 8)), 2),
        "aspect": job.get("aspect", "9:16"),
        "aspect_class": ASPECT_CLASS.get(job.get("aspect"), "portrait"),
        "series": series,
        "candles": make_candles(series),
        "line_path": line_path(series),
    }
