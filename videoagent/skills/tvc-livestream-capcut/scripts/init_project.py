"""Khởi tạo dự án TVC livestream: cây thư mục chuẩn, ảnh đầu vào (PNG), ảnh tham chiếu Codex, du_an.json mẫu.

python -P init_project.py --root D:/CapCut --name TenDuAn --model anh_nguoi_mau.jpg --product anh_san_pham.webp
"""
import argparse, json, shutil
from pathlib import Path
from PIL import Image

DIRS = ["00_input", "01_y_tuong", "02_kich_ban", "04_anh/codex", "04_anh/overlay", "05_grok_video",
        "06_phu_de", "07_capcut_spec", "08_preview"]

TEMPLATE = {
    "name": "",
    "draft_name": "",
    "shop_name": "",
    "voice_style": "cheerful Southern Vietnamese accent",
    # nhạc nền người dùng đã duyệt (2026-11-18): dong_luc 124 BPM, giọng C, seed 18
    "music": {"style": "dong_luc", "bpm": 124, "key": "C", "seed": 18, "volume": 0.15},
    "ambience": {"style": "boc_xep", "seed": 3, "volume": 0.35, "vehicles": False},
    "toc_do_noi": 1.15,
    "overlay": {"product_title": "", "product_line2": "", "product_line3": "", "hotline": "",
                "viewers": "3.268", "likes": "12,5K", "avatar_box": None},
    "keywords": [],
    "clips": [
        {"id": f"v{i}", "image_prompt": "", "grok_action": "", "dialogue": "", "display": "", "comments": [],
         "fx": []}  # hiệu ứng sản phẩm — xem references/du_an_schema.md
        for i in range(1, 6)
    ],
}


def to_png(src, dst):
    im = Image.open(src)
    im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
    im.save(dst)
    return im.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--name", required=True, help="tên thư mục dự án, không dấu, không khoảng trắng")
    ap.add_argument("--model", help="ảnh người mẫu (bỏ trống nếu dùng người mẫu AI)")
    ap.add_argument("--product", required=True, help="ảnh sản phẩm")
    a = ap.parse_args()

    proj = Path(a.root) / a.name
    for d in DIRS:
        (proj / d).mkdir(parents=True, exist_ok=True)
    print("Dự án:", proj)
    print("  san_pham.png", to_png(a.product, proj / "00_input" / "san_pham.png"))
    shutil.copy(proj / "00_input" / "san_pham.png", proj / "04_anh" / "codex" / "ref_san_pham.png")
    if a.model:
        print("  nguoi_mau.png", to_png(a.model, proj / "00_input" / "nguoi_mau.png"))
        shutil.copy(proj / "00_input" / "nguoi_mau.png", proj / "04_anh" / "codex" / "ref_nguoi_mau.png")

    f = proj / "02_kich_ban" / "du_an.json"
    if f.exists():
        print("  du_an.json đã có — giữ nguyên")
    else:
        t = dict(TEMPLATE, name=a.name, draft_name=f"{a.name}_Live")
        f.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  tạo", f)


if __name__ == "__main__":
    main()
