"""Vẽ khung livestream kiểu chung (PNG trong suốt 1080x1920) + ảnh bình luận theo từng clip.
KHÔNG dùng logo/giao diện thương hiệu của nền tảng nào (TikTok, Shopee...).

python -P tao_overlay.py --project D:/CapCut/TenDuAn
Ra: 04_anh/overlay/khung_live.png, 04_anh/overlay/binh_luan_<clip_id>.png
"""
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
FONT_DIR = "C:/Windows/Fonts/"
COLORS = [(255, 200, 80), (130, 220, 255), (170, 255, 150), (255, 160, 200)]


def font(size, bold=False):
    for name in (("arialbd.ttf", "Arial Bold.ttf") if bold else ("arial.ttf", "Arial.ttf")):
        try:
            return ImageFont.truetype(FONT_DIR + name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def heart(d, cx, cy, s, fill):
    r = s / 4
    d.ellipse((cx - 2 * r, cy - r, cx, cy + r), fill=fill)
    d.ellipse((cx, cy - r, cx + 2 * r, cy + r), fill=fill)
    d.polygon([(cx - 2 * r + 1, cy + r * 0.3), (cx + 2 * r - 1, cy + r * 0.3), (cx, cy + 2.2 * r)], fill=fill)


def circle(img, size):
    img = img.resize((size, size))
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), m)
    return out


def fit_text(d, text, f, maxw):
    while d.textlength(text, font=f) > maxw and len(text) > 2:
        text = text[:-2].rstrip() + "…"
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    proj = Path(a.project)
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    ov = data.get("overlay", {})
    out = proj / "04_anh" / "overlay"
    out.mkdir(parents=True, exist_ok=True)

    fr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(fr)
    for y in range(260):  # gradient tối nhẹ trên/dưới cho chữ UI dễ đọc
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(120 * (1 - y / 260))))
    for y in range(H - 700, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * ((y - (H - 700)) / 700))))

    # thanh shop: avatar + tên + lượt thích + theo dõi
    d.rounded_rectangle((30, 50, 560, 150), 50, fill=(0, 0, 0, 110))
    model_png = proj / "00_input" / "nguoi_mau.png"
    src = model_png if model_png.exists() else proj / "00_input" / "san_pham.png"
    mi = Image.open(src).convert("RGB")
    box = ov.get("avatar_box")
    if not box:  # mặc định: hình vuông quanh mặt, ước lượng 1/3 trên giữa ảnh chân dung
        side = int(min(mi.width, mi.height) * 0.42)
        cx, cy = mi.width // 2, int(mi.height * 0.32)
        box = [max(0, cx - side // 2), max(0, cy - side // 2), cx + side // 2, cy + side // 2]
    fr.alpha_composite(circle(mi.crop(tuple(box)), 84), (40, 58))
    d.text((140, 60), fit_text(d, data.get("shop_name") or "Shop", font(34, True), 270), font=font(34, True), fill="white")
    d.text((140, 104), f"{ov.get('likes', '12,5K')} lượt thích", font=font(24), fill=(230, 230, 230))
    d.rounded_rectangle((420, 72, 545, 128), 28, fill=(255, 64, 98))
    d.text((483, 100), "+ Theo dõi", font=font(22, True), fill="white", anchor="mm")
    # LIVE + người xem + đóng
    d.rounded_rectangle((600, 70, 720, 126), 10, fill=(255, 32, 80))
    d.text((660, 98), "LIVE", font=font(32, True), fill="white", anchor="mm")
    d.rounded_rectangle((732, 70, 920, 126), 28, fill=(0, 0, 0, 120))
    d.ellipse((750, 88, 772, 108), outline="white", width=3)
    d.ellipse((757, 94, 765, 102), fill="white")
    d.text((785, 98), ov.get("viewers", "3.268"), font=font(28, True), fill="white", anchor="lm")
    d.text((1010, 98), "×", font=font(54), fill="white", anchor="mm")
    for (x, y, s, c) in [(985, 1180, 46, (255, 70, 110, 230)), (1010, 1080, 34, (255, 140, 170, 200)),
                         (965, 990, 28, (255, 90, 130, 170)), (1000, 905, 22, (255, 170, 190, 140))]:
        heart(d, x, y, s, c)

    # thẻ giỏ hàng
    card = (700, 1430, 1050, 1720)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((card[0] + 6, card[1] + 10, card[2] + 6, card[3] + 10), 26, fill=(0, 0, 0, 120))
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    d.rounded_rectangle(card, 26, fill=(255, 255, 255, 245))
    prod = Image.open(proj / "00_input" / "san_pham.png").convert("RGBA")
    prod.thumbnail((150, 150))
    fr.alpha_composite(prod, (card[0] + 12 + (150 - prod.width) // 2, card[1] + 14 + (150 - prod.height) // 2))
    tx, tw = card[0] + 172, card[2] - card[0] - 182
    d.text((tx, card[1] + 22), fit_text(d, ov.get("product_title", ""), font(30, True), tw), font=font(30, True), fill=(20, 110, 40))
    d.text((tx, card[1] + 60), fit_text(d, ov.get("product_line2", ""), font(26, True), tw), font=font(26, True), fill=(230, 90, 0))
    d.text((tx, card[1] + 98), fit_text(d, ov.get("product_line3", ""), font(22), tw), font=font(22), fill=(60, 60, 60))
    if ov.get("hotline"):
        d.text((card[0] + 18, card[1] + 182), f"Hotline: {ov['hotline']}", font=font(26, True), fill=(200, 20, 40))
    d.rounded_rectangle((card[0] + 18, card[1] + 222, card[2] - 18, card[3] - 14), 22, fill=(255, 64, 98))
    d.text(((card[0] + card[2]) // 2, card[1] + 248), "MUA NGAY", font=font(30, True), fill="white", anchor="mm")
    d.rounded_rectangle((card[0] - 4, card[1] - 70, card[0] + 220, card[1] - 14), 28, fill=(255, 170, 0))
    d.text((card[0] + 108, card[1] - 42), "Giỏ hàng (1)", font=font(28, True), fill="white", anchor="mm")

    # ô bình luận + nút
    d.rounded_rectangle((30, 1770, 640, 1850), 40, fill=(255, 255, 255, 60))
    d.text((70, 1810), "Nói gì đó...", font=font(30), fill=(240, 240, 240), anchor="lm")
    for x in (700, 800, 900, 1000):
        d.ellipse((x - 38, 1772, x + 38, 1848), fill=(255, 255, 255, 60))
    heart(d, 1000, 1806, 38, (255, 64, 98, 255))
    d.text((700, 1810), "♪", font=font(40, True), fill="white", anchor="mm")
    d.text((800, 1808), "+", font=font(48, True), fill="white", anchor="mm")
    d.text((900, 1800), "•••", font=font(30, True), fill="white", anchor="mm")
    fr.save(out / "khung_live.png")

    # bình luận theo clip (font Arial không vẽ emoji màu → dùng ♥ thay emoji)
    for c in data["clips"]:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        y = 1700
        for k, (name, text) in enumerate(reversed(c.get("comments", []))):
            nf, tf = font(28, True), font(30)
            line = f"{name}  "
            wname = dd.textlength(line, font=nf)
            text = fit_text(dd, text, tf, 630 - 34 - wname - 24)
            bw = int(34 + wname + dd.textlength(text, font=tf) + 24)
            y -= 74
            dd.rounded_rectangle((30, y, 30 + bw, y + 62), 31, fill=(0, 0, 0, 120))
            dd.text((50, y + 31), line, font=nf, fill=COLORS[k % len(COLORS)], anchor="lm")
            dd.text((50 + wname, y + 31), text, font=tf, fill="white", anchor="lm")
        dd.rounded_rectangle((30, y - 70, 420, y - 16), 27, fill=(255, 170, 0, 170))
        dd.text((50, y - 43), "♥ 25 người vừa tham gia", font=font(26, True), fill="white", anchor="lm")
        im.save(out / f"binh_luan_{c['id']}.png")
    print("OK:", sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main()
