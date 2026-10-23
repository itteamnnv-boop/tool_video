"""Khung bình luận livestream do APP vẽ (Pillow + font tiếng Việt) rồi ghép lên clip bằng ffmpeg.

Model ảnh / video vẽ chữ tiếng Việt có dấu không ổn định (sai chính tả, trùng dòng, nhoè khi chuyển động) → khi giữ
layout có khung bình luận, model chỉ làm sạch vùng bình luận; app vẽ bong bóng (avatar, tên, chữ) sắc nét và cho bình
luận hiện lần lượt như livestream thật (mới nhất ở dưới, cũ trôi lên).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import ffmpeg

FONT_DIRS = (Path("C:/Windows/Fonts"),)
FONT_REGULAR = ("segoeui.ttf", "arial.ttf")
FONT_BOLD = ("segoeuib.ttf", "arialbd.ttf")
VISIBLE = 5  # số bình luận cùng lúc trên màn
# tên người xem minh hoạ (tên gọi phổ biến, không gắn với người thật)
NAMES = ("Thu Hà", "Minh Tuấn", "Ngọc Lan", "Văn Hùng", "Kim Oanh", "Đức Anh", "Thanh Tâm", "Hoàng Nam", "Mỹ Linh",
         "Quốc Bảo", "Bích Ngọc", "Tấn Phát", "Hồng Nhung", "Trung Kiên", "Phương Thảo", "Văn Lợi")
AVATAR_COLORS = ((236, 112, 99), (93, 173, 226), (88, 214, 141), (245, 176, 65), (175, 122, 197), (72, 201, 176),
                 (241, 148, 138), (133, 193, 233))


def _font(names: tuple, size: int):
    for d in FONT_DIRS:
        for n in names:
            if (d / n).is_file():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:3]


def clean_comments(comments) -> list[str]:
    """Bỏ dòng trống / trùng (model hay lặp lại 1 bình luận)."""
    out, seen = [], set()
    for c in comments or []:
        text = " ".join(str(c).split())[:90]
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _bubble(draw, x: int, y: int, name: str, text: str, scale: float, max_w: int, seed: int) -> int:
    """Vẽ 1 bong bóng bình luận tại (x, y) — trả về chiều cao đã dùng."""
    f_name, f_text = _font(FONT_BOLD, int(22 * scale)), _font(FONT_REGULAR, int(25 * scale))
    av, pad, gap = int(46 * scale), int(12 * scale), int(10 * scale)
    lines = _wrap(draw, text, f_text, max_w - av - gap - 2 * pad)
    line_h = int(31 * scale)
    h = max(av + 2 * int(6 * scale), pad + int(26 * scale) + line_h * len(lines) + pad // 2)
    w = min(max_w, av + gap + 2 * pad + int(max(draw.textlength(name, font=f_name),
                                               *(draw.textlength(ln, font=f_text) for ln in lines))))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=int(22 * scale), fill=(0, 0, 0, 105))
    color = AVATAR_COLORS[seed % len(AVATAR_COLORS)]
    ay = y + (h - av) // 2
    draw.ellipse((x + pad // 2, ay, x + pad // 2 + av, ay + av), fill=color + (255,))
    initial = name.split()[-1][:1].upper()
    fi = _font(FONT_BOLD, int(22 * scale))
    tw = draw.textlength(initial, font=fi)
    draw.text((x + pad // 2 + (av - tw) / 2, ay + av / 2), initial, font=fi, fill=(255, 255, 255, 255), anchor="lm")
    tx = x + pad // 2 + av + gap
    draw.text((tx, y + pad // 2 + int(4 * scale)), name, font=f_name, fill=(255, 255, 255, 170))
    for i, ln in enumerate(lines):
        draw.text((tx, y + pad // 2 + int(30 * scale) + i * line_h), ln, font=f_text, fill=(255, 255, 255, 255))
    return h


def render_states(comments: list[str], width: int, height: int, out_dir: Path, *, caption: str = "",
                  seed: str = "") -> list[Path]:
    """Ảnh PNG trong suốt cỡ khung video, trạng thái k = đã hiện k bình luận đầu (mới nhất ở dưới)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = min(width, height) / 1080 * (1.0 if height >= width else 0.8)
    base = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    names = [NAMES[(base + i * 7) % len(NAMES)] for i in range(len(comments))]
    left, bottom = int(width * 0.035), int(height * 0.115)  # chừa thanh nhập bình luận của giao diện phía dưới
    max_w = int(width * (0.66 if height >= width else 0.36))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    heights = [_bubble(probe, 0, 0, names[i], comments[i], scale, max_w, base + i) for i in range(len(comments))]
    paths = []
    for k in range(1, len(comments) + 1):
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        shown = list(range(k))[-VISIBLE:]
        y = height - bottom - sum(heights[i] for i in shown) - int(10 * scale) * (len(shown) - 1)
        if caption:  # chữ sản phẩm / ưu đãi: nhãn nổi phía trên khung bình luận
            fc = _font(FONT_BOLD, int(28 * scale))
            tw = draw.textlength(caption, font=fc)
            cy = y - int(64 * scale)
            draw.rounded_rectangle((left, cy, left + tw + int(36 * scale), cy + int(48 * scale)), radius=int(24 * scale),
                                   fill=(238, 77, 45, 230))
            draw.text((left + int(18 * scale), cy + int(24 * scale)), caption, font=fc, fill=(255, 255, 255, 255),
                      anchor="lm")
        for i in shown:
            _bubble(draw, left, y, names[i], comments[i], scale, max_w, base + i)
            y += heights[i] + int(10 * scale)
        path = out_dir / f"chat_{k:02d}.png"
        img.save(path)
        paths.append(path)
    return paths


def burn(video: Path, comments, duration: float, work: Path, *, caption: str = "", seed: str = "") -> bool:
    """Ghép khung bình luận chạy lần lượt lên video (ghi đè file). Không có bình luận → False (giữ nguyên)."""
    comments = clean_comments(comments)
    if not comments:
        return False
    w, h = ffmpeg.video_size(video)
    states = render_states(comments, w, h, work, caption=caption, seed=seed)
    start, end = 0.4, max(0.8, duration - 0.3)
    step = max(0.7, (end - start) / len(states))
    args, chain, last = ["-i", str(video)], [], "0:v"
    for k, png in enumerate(states):
        args += ["-i", str(png)]
        t0 = start + k * step
        t1 = start + (k + 1) * step if k + 1 < len(states) else duration + 1
        chain.append(f"[{last}][{k + 1}:v]overlay=0:0:enable='between(t,{t0:.2f},{t1:.2f})'[v{k + 1}]")
        last = f"v{k + 1}"
    out = video.with_name(video.stem + "_chat.mp4")
    ffmpeg.run([*args, "-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "copy", out])
    out.replace(video)
    return True
