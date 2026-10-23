"""📱 Mô phỏng livestream TikTok — APP vẽ toàn bộ giao diện live (Pillow, font tiếng Việt) theo từng khung hình rồi
ghép lên clip bằng ffmpeg (đẩy khung RGBA qua stdin).

Có: chủ kênh (avatar, tên, nút theo dõi) · người xem (avatar + số người xem DO NGƯỜI DÙNG NHẬP, 0 = ẩn) · nút ✕ ·
bình luận trượt lên lần lượt · "… vừa tham gia" · tim bay bên phải · thẻ sản phẩm ghim (ảnh, tên, giá người dùng nhập,
nút Mua) · thanh dưới (ô bình luận, giỏ hàng, quà, chia sẻ) · banner tặng quà (tuỳ chọn, mặc định tắt).
App KHÔNG tự bịa số người xem / lượt thích / đã bán — chỉ hiện số người dùng nhập.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .. import ffmpeg
from .live_chat import AVATAR_COLORS, FONT_BOLD, FONT_REGULAR, NAMES, _font, _wrap, clean_comments

FPS = 15
RED = (254, 44, 85)
ORANGE = (255, 106, 0)
VISIBLE = 5
GIFTS = ("Hoa hồng", "Trái tim", "Kẹo mút", "Bó hoa")


def clean_config(raw) -> dict:
    """Cấu hình mô phỏng livestream của dự án (sửa ở ⚙ dự án → 📱 Livestream TikTok)."""
    raw = raw if isinstance(raw, dict) else {}
    text = lambda k, n: " ".join(str(raw.get(k) or "").split())[:n]  # noqa: E731
    try:
        viewers = max(0, min(9_999_999, int(str(raw.get("viewers") or 0).replace(".", "").replace(",", ""))))
    except ValueError:
        viewers = 0
    comments = [" ".join(x.split())[:90] for x in str(raw.get("comments") or "").splitlines() if x.strip()][:30]
    return {"on": bool(raw.get("on")), "channel": text("channel", 40), "viewers": viewers,
            "avatar": str(raw.get("avatar") or "")[:1000],  # avatar / logo kênh người dùng tải lên ("" = avatar trống)
            "hearts": raw.get("hearts", True) is not False, "joins": raw.get("joins", True) is not False,
            "gifts": bool(raw.get("gifts")), "cart": bool(raw.get("cart")), "product_name": text("product_name", 70),
            "price": text("price", 24), "comments": "\n".join(comments)}


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "M"
    if n >= 1000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "K"
    return str(n)


def _circle(img: Image.Image, size: int) -> Image.Image:
    img = ImageOps.fit(img.convert("RGBA"), (size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _initial_avatar(name: str, size: int, seed: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=AVATAR_COLORS[seed % len(AVATAR_COLORS)] + (255,))
    f = _font(FONT_BOLD, int(size * 0.46))
    d.text((size / 2, size / 2), (name.split() or ["?"])[-1][:1].upper(), font=f, fill=(255, 255, 255, 255), anchor="mm")
    return img


def _blank_avatar(size: int) -> Image.Image:
    """Avatar kênh khi người dùng chưa tải ảnh: hình người xám trung tính (không tự tạo ảnh / chữ cái)."""
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, big - 1, big - 1), fill=(120, 124, 130, 255))
    d.ellipse((big * 0.34, big * 0.2, big * 0.66, big * 0.52), fill=(225, 227, 230, 255))
    d.ellipse((big * 0.18, big * 0.58, big * 0.82, big * 1.12), fill=(225, 227, 230, 255))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def _heart(size: int, color: tuple) -> Image.Image:
    big = size * 4  # vẽ to rồi thu nhỏ → viền mịn (Pillow không khử răng cưa hình vẽ)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = big * 0.27
    d.ellipse((big * 0.5 - 2 * r, big * 0.12, big * 0.5, big * 0.12 + 2 * r), fill=color + (255,))
    d.ellipse((big * 0.5, big * 0.12, big * 0.5 + 2 * r, big * 0.12 + 2 * r), fill=color + (255,))
    d.polygon([(big * 0.5 - 2 * r + 4, big * 0.12 + r * 1.25), (big * 0.5 + 2 * r - 4, big * 0.12 + r * 1.25),
               (big * 0.5, big * 0.92)], fill=color + (255,))
    return img.resize((size, size), Image.LANCZOS)


def _fade(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return img
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda a: int(a * max(0.0, alpha))))
    return out


class LiveSim:
    def __init__(self, cfg: dict, width: int, height: int, *, seed: str = "", avatar: str = "", product: str = "") -> None:
        self.cfg, self.w, self.h = cfg, width, height
        self.s = min(width, height) / 720 * (1.0 if height >= width else 0.75)
        self.rng_base = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        self.avatar = avatar if avatar and Path(avatar).is_file() else ""
        self.product = product if product and Path(product).is_file() else ""
        self.bottom = int(height - 92 * self.s)  # mép trên thanh dưới
        self.static = self._static()
        self.hearts = [_heart(int(34 * self.s), c) for c in ((254, 44, 85), (255, 119, 160), (255, 196, 0), (255, 82, 82))]
        self.card = self._product_card() if cfg.get("cart") and (cfg.get("product_name") or self.product) else None

    # ---------------------------------------------------------------- lớp tĩnh: thanh trên + thanh dưới
    def _static(self) -> Image.Image:
        s, w, h = self.s, self.w, self.h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # chủ kênh: avatar, tên, nút theo dõi
        x, y, ph = int(14 * s), int(36 * s), int(60 * s)
        name = self.cfg.get("channel") or "Kênh của tôi"
        fn, ff = _font(FONT_BOLD, int(22 * s)), _font(FONT_BOLD, int(19 * s))
        while d.textlength(name, font=fn) > 200 * s and len(name) > 4:
            name = name[:-2] + "…"
        name_w = int(d.textlength(name, font=fn))
        follow_w = int(d.textlength("+ Theo dõi", font=ff) + 26 * s)
        d.rounded_rectangle((x, y, x + ph + int(10 * s) + name_w + follow_w + int(18 * s), y + ph), radius=ph // 2,
                            fill=(0, 0, 0, 90))
        av_size = ph - int(8 * s)
        av = _circle(Image.open(self.avatar), av_size) if self.avatar else _blank_avatar(av_size)
        img.alpha_composite(av, (x + int(4 * s), y + int(4 * s)))
        tx = x + ph + int(6 * s)
        d.text((tx, y + ph / 2), name, font=fn, fill=(255, 255, 255, 255), anchor="lm")
        bx = tx + name_w + int(10 * s)
        d.rounded_rectangle((bx, y + int(12 * s), bx + follow_w, y + ph - int(12 * s)), radius=int(18 * s), fill=RED + (255,))
        d.text((bx + follow_w / 2, y + ph / 2), "+ Theo dõi", font=ff, fill=(255, 255, 255, 255), anchor="mm")
        # người xem (số do người dùng nhập) + nút đóng
        cx = w - int(14 * s)
        k, cy0, lw = int(11 * s), y + ph // 2, max(2, int(3 * s))  # nút đóng ✕ (vẽ nét — font không có ký tự này)
        d.line((cx - 2 * k, cy0 - k, cx, cy0 + k), fill=(255, 255, 255, 235), width=lw)
        d.line((cx - 2 * k, cy0 + k, cx, cy0 - k), fill=(255, 255, 255, 235), width=lw)
        cx -= int(48 * s)
        if self.cfg.get("viewers"):
            label = fmt_count(self.cfg["viewers"])
            fv = _font(FONT_BOLD, int(20 * s))
            vw = int(d.textlength(label, font=fv) + 24 * s)
            d.rounded_rectangle((cx - vw, y + int(12 * s), cx, y + ph - int(12 * s)), radius=int(18 * s), fill=(0, 0, 0, 90))
            d.text((cx - vw / 2, y + ph / 2), label, font=fv, fill=(255, 255, 255, 255), anchor="mm")
            cx -= vw + int(8 * s)
        size = int(40 * s)
        for i in range(3):
            av = _initial_avatar(NAMES[(self.rng_base + i * 5) % len(NAMES)], size, self.rng_base + i)
            img.alpha_composite(av, (cx - size - i * int(26 * s), y + (ph - size) // 2))
        # thanh dưới: ô bình luận + icon
        by, bh = int(h - 78 * s), int(56 * s)
        d.rounded_rectangle((int(14 * s), by, int(w * 0.5), by + bh), radius=bh // 2, fill=(0, 0, 0, 95))
        d.text((int(34 * s), by + bh / 2), "Thêm bình luận...", font=_font(FONT_REGULAR, int(21 * s)),
               fill=(255, 255, 255, 200), anchor="lm")
        icons = (["cart"] if self.cfg.get("cart") else []) + ["gift", "share", "more"]
        ix = w - int(14 * s)
        for kind in reversed(icons):
            ix -= bh
            self._icon(d, kind, ix, by, bh)
            ix -= int(10 * s)
        return img

    @staticmethod
    def _icon(d: ImageDraw.ImageDraw, kind: str, x: int, y: int, size: int) -> None:
        d.ellipse((x, y, x + size, y + size), fill=ORANGE + (255,) if kind == "cart" else (0, 0, 0, 95))
        cx, cy, u = x + size / 2, y + size / 2, size / 56
        white, lw = (255, 255, 255, 255), max(2, int(3 * size / 56))
        if kind == "cart":  # túi mua hàng
            d.rounded_rectangle((cx - 13 * u, cy - 6 * u, cx + 13 * u, cy + 15 * u), radius=int(4 * u), outline=white, width=lw)
            d.arc((cx - 8 * u, cy - 17 * u, cx + 8 * u, cy + 1 * u), 180, 360, fill=white, width=lw)
        elif kind == "gift":  # hộp quà
            d.rectangle((cx - 14 * u, cy - 4 * u, cx + 14 * u, cy + 15 * u), outline=white, width=lw)
            d.rectangle((cx - 16 * u, cy - 10 * u, cx + 16 * u, cy - 4 * u), fill=white)
            d.line((cx, cy - 10 * u, cx, cy + 15 * u), fill=white, width=lw)
        elif kind == "share":  # mũi tên chia sẻ
            d.polygon([(cx + 15 * u, cy - 2 * u), (cx + 2 * u, cy - 14 * u), (cx + 2 * u, cy - 7 * u), (cx - 14 * u, cy - 4 * u),
                       (cx - 14 * u, cy + 13 * u), (cx - 4 * u, cy + 3 * u), (cx + 2 * u, cy + 3 * u), (cx + 2 * u, cy + 10 * u)],
                      fill=white)
        else:  # ⋯
            for k in (-1, 0, 1):
                d.ellipse((cx + k * 10 * u - 3 * u, cy - 3 * u, cx + k * 10 * u + 3 * u, cy + 3 * u), fill=white)

    # ---------------------------------------------------------------- thẻ sản phẩm ghim
    def _product_card(self) -> Image.Image:
        s = self.s
        cw, ch = int(min(self.w * 0.62, 430 * s)), int(118 * s)
        img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=int(16 * s), fill=(255, 255, 255, 245))
        th = ch - int(20 * s)
        if self.product:
            thumb = ImageOps.fit(Image.open(self.product).convert("RGBA"), (th, th))
            mask = Image.new("L", (th, th), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, th - 1, th - 1), radius=int(10 * s), fill=255)
            img.paste(thumb, (int(10 * s), int(10 * s)), mask)
        tx = int(12 * s) + (th + int(10 * s) if self.product else 0)
        fn = _font(FONT_BOLD, int(19 * s))
        for i, ln in enumerate(_wrap(d, self.cfg.get("product_name") or "Sản phẩm", fn, cw - tx - int(12 * s))[:2]):
            d.text((tx, int(12 * s) + i * int(24 * s)), ln, font=fn, fill=(22, 24, 35, 255))
        if self.cfg.get("price"):
            d.text((tx, ch - int(14 * s)), self.cfg["price"], font=_font(FONT_BOLD, int(22 * s)), fill=RED + (255,),
                   anchor="ls")
        fb = _font(FONT_BOLD, int(19 * s))
        bw = int(d.textlength("Mua", font=fb) + 34 * s)
        d.rounded_rectangle((cw - bw - int(12 * s), ch - int(48 * s), cw - int(12 * s), ch - int(12 * s)),
                            radius=int(18 * s), fill=RED + (255,))
        d.text((cw - bw / 2 - int(12 * s), ch - int(30 * s)), "Mua", font=fb, fill=(255, 255, 255, 255), anchor="mm")
        return img

    # ---------------------------------------------------------------- bình luận
    def _bubble(self, name: str, text: str, seed: int, kind: str = "comment") -> Image.Image:
        s = self.s
        max_w = int(self.w * 0.66)
        fname, ftext = _font(FONT_BOLD, int(19 * s)), _font(FONT_REGULAR, int(21 * s))
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        if kind == "join":
            label = f"{name} vừa tham gia"
            wj, hj = int(probe.textlength(label, font=ftext) + 28 * s), int(38 * s)
            img = Image.new("RGBA", (wj, hj), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, wj - 1, hj - 1), radius=hj // 2, fill=(0, 0, 0, 70))
            d.text((int(14 * s), hj / 2), label, font=ftext, fill=(255, 255, 255, 210), anchor="lm")
            return img
        av, pad = int(40 * s), int(10 * s)
        lines = _wrap(probe, text, ftext, max_w - av - 3 * pad)
        h = max(av + 2 * pad, int(30 * s) + int(27 * s) * len(lines) + pad)
        wb = min(max_w, av + 3 * pad + int(max(probe.textlength(name, font=fname),
                                                  *(probe.textlength(x, font=ftext) for x in lines))))
        img = Image.new("RGBA", (wb, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, wb - 1, h - 1), radius=int(18 * s), fill=(0, 0, 0, 80))
        img.alpha_composite(_initial_avatar(name, av, seed), (pad // 2, (h - av) // 2))
        tx = pad // 2 + av + pad
        d.text((tx, int(8 * s)), name, font=fname, fill=(255, 255, 255, 165))
        for i, ln in enumerate(lines):
            d.text((tx, int(32 * s) + i * int(27 * s)), ln, font=ftext, fill=(255, 255, 255, 255))
        return img

    def timeline(self, comments: list[str], duration: float, *, history=()) -> list[dict]:
        """Lịch xuất hiện: bình luận (chia đều trong cảnh) + "vừa tham gia" xen giữa; history = bình luận cảnh trước
        (đã hiện sẵn từ giây 0 cho liền mạch giữa các cảnh)."""
        rng = random.Random(self.rng_base)
        events = [{"at": -1.0, "img": self._bubble(NAMES[(self.rng_base + 11 * i) % len(NAMES)], c, self.rng_base + i)}
                  for i, c in enumerate(list(history)[-VISIBLE:])]
        step = max(0.8, (duration - 0.8) / max(1, len(comments)))
        for i, c in enumerate(comments):
            at = 0.5 + i * step + rng.uniform(-0.15, 0.15)
            if self.cfg.get("joins") and i % 2 == 1:
                events.append({"at": at - step / 2, "join": True,
                               "img": self._bubble(NAMES[(self.rng_base + 13 * i) % len(NAMES)], "", 0, "join")})
            events.append({"at": at, "img": self._bubble(NAMES[(self.rng_base + 7 * i + 3) % len(NAMES)], c,
                                                         self.rng_base + 7 * i + 3)})
        events.sort(key=lambda e: e["at"])
        return events

    def frame(self, t: float, events: list[dict], *, caption: str = "", t0: float = 0.0) -> Image.Image:
        s, img = self.s, self.static.copy()
        g = t + t0  # thời điểm trong cả video → tim / quà liền mạch giữa các cảnh
        if self.cfg.get("hearts", True):  # tim bay bên phải
            for k in range(max(0, int((g - 2.4) / 0.32)), int(g / 0.32) + 1):
                age = g - k * 0.32
                if not 0 <= age <= 2.4:
                    continue
                rnd = random.Random(self.rng_base + k)
                p = age / 2.4
                x = self.w - int(70 * s) + math.sin(age * 3 + rnd.random() * 6) * 22 * s - rnd.random() * 30 * s
                y = self.bottom - int(40 * s) - p * 420 * s
                img.alpha_composite(_fade(self.hearts[rnd.randrange(len(self.hearts))], 1 - p ** 2), (int(x), int(y)))
        # bình luận: trượt lên khi có cái mới, tối đa VISIBLE, cái mới hiện dần
        shown = [e for e in events if e["at"] <= t]
        joins = [e for e in shown if e.get("join") and t - e["at"] < 1.6]
        chat = [e for e in shown if not e.get("join")][-VISIBLE:]
        gap, left = int(8 * s), int(14 * s)
        y = self.bottom - int(14 * s)
        if joins:
            j = joins[-1]
            y -= j["img"].height
            img.alpha_composite(_fade(j["img"], min(1, (t - j["at"]) / 0.25)), (left, y))
            y -= gap
        heights = sum(e["img"].height + gap for e in chat)
        last = chat[-1] if chat else None
        slide = (1 - min(1.0, (t - last["at"]) / 0.25)) * (last["img"].height + gap) if last and last["at"] >= 0 else 0
        cy = int(y - heights + slide)
        for e in chat:
            img.alpha_composite(_fade(e["img"], min(1.0, (t - e["at"]) / 0.25) if e["at"] >= 0 else 1.0), (left, cy))
            cy += e["img"].height + gap
        top = int(y - heights) - gap
        if self.card is not None:  # thẻ sản phẩm ghim
            top -= self.card.height
            img.alpha_composite(self.card, (left, top))
            top -= gap
        if caption:  # chữ trên màn của cảnh (ưu đãi / lời kêu gọi)
            d = ImageDraw.Draw(img)
            fc = _font(FONT_BOLD, int(22 * s))
            tw = d.textlength(caption, font=fc)
            top -= int(42 * s)
            d.rounded_rectangle((left, top, left + tw + int(30 * s), top + int(40 * s)), radius=int(20 * s),
                                fill=ORANGE + (235,))
            d.text((left + int(15 * s), top + int(20 * s)), caption, font=fc, fill=(255, 255, 255, 255), anchor="lm")
        if self.cfg.get("gifts"):  # banner tặng quà (tuỳ chọn): trượt vào từ trái mỗi 7 giây
            gt = g % 7.0
            if gt < 2.6:
                rnd = random.Random(self.rng_base + int(g // 7))
                banner = self._gift(NAMES[rnd.randrange(len(NAMES))], GIFTS[rnd.randrange(len(GIFTS))])
                x = int(-banner.width + min(1, gt / 0.3) * (banner.width + left))
                img.alpha_composite(_fade(banner, 1 if gt < 2.2 else 1 - (gt - 2.2) / 0.4), (x, int(self.h * 0.42)))
        return img

    def _gift(self, name: str, gift: str) -> Image.Image:
        s = self.s
        fn, fg = _font(FONT_BOLD, int(19 * s)), _font(FONT_REGULAR, int(18 * s))
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        h = int(56 * s)
        w = int(max(probe.textlength(name, font=fn), probe.textlength(f"đã tặng {gift}", font=fg)) + h + 70 * s)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(160, 40, 170, 200))
        img.alpha_composite(_initial_avatar(name, h - int(10 * s), 5), (int(5 * s), int(5 * s)))
        d.text((h + int(4 * s), int(8 * s)), name, font=fn, fill=(255, 255, 255, 255))
        d.text((h + int(4 * s), int(31 * s)), f"đã tặng {gift}", font=fg, fill=(255, 235, 160, 255))
        img.alpha_composite(self.hearts[0], (w - int(46 * s), (h - self.hearts[0].height) // 2))
        return img


def burn(video: Path, cfg: dict, comments, duration: float, *, caption: str = "", seed: str = "", t0: float = 0.0,
         history=(), avatar: str = "", product: str = "") -> None:
    """Ghép giao diện livestream lên video (ghi đè file)."""
    w, h = ffmpeg.video_size(video)
    sim = LiveSim(cfg, w, h, seed=seed, avatar=avatar, product=product)
    events = sim.timeline(clean_comments(comments), duration, history=clean_comments(history))
    out = video.with_name(video.stem + "_live.mp4")
    proc = ffmpeg.popen_stdin(["-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(FPS),
                               "-i", "-", "-filter_complex", "[0:v][1:v]overlay=0:0:eof_action=repeat[v]", "-map", "[v]",
                               "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                               "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", f"{duration:.3f}", str(out)])
    try:
        for k in range(int(math.ceil(duration * FPS)) + 1):
            proc.stdin.write(sim.frame(k / FPS, events, caption=caption, t0=t0).tobytes())
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass  # ffmpeg dừng sớm → lỗi đọc ở stderr bên dưới
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise ffmpeg.FFmpegError(err.strip()[-1500:] or "ffmpeg lỗi khi ghép giao diện livestream")
    out.replace(video)


def preview(cfg: dict, width: int, height: int, *, background: str = "", avatar: str = "", product: str = "",
            comments=None) -> Image.Image:
    """Ảnh xem trước (giây 4,6) trên nền ảnh khung đầu / nền tối."""
    sim = LiveSim(cfg, width, height, seed="preview", avatar=avatar, product=product)
    sample = clean_comments(comments) or ["Dùng cho cây gì vậy shop?", "Bao nhiêu ký một bao ạ?",
                                          "Ship về Cần Thơ được không?", "Có hướng dẫn cách bón không?"]
    base = (ImageOps.fit(Image.open(background).convert("RGBA"), (width, height)) if background and Path(background).is_file()
            else Image.new("RGBA", (width, height), (38, 52, 40, 255)))
    base.alpha_composite(sim.frame(4.6, sim.timeline(sample[:4], 5.0)))
    return base.convert("RGB")
