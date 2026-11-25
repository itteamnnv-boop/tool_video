"""Render KHUNG LIVE ĐỘNG bằng Remotion (tim bay, bình luận trượt lên, LIVE nhấp nháy, số người xem tăng,
giỏ hàng nảy, "... vừa tham gia") thành video trong suốt để đặt làm 1 track trong CapCut.

python -P remotion_overlay.py --project D:/CapCut/TenDuAn [--format prores|webm]
(build_draft.py --remotion gọi hàm render_overlay() sau khi tính xong mốc thời gian các clip.)

- Project Remotion dùng chung: D:/CapCut/_remotion/live-overlay (đổi bằng biến môi trường REMOTION_OVERLAY_DIR).
  Chưa có → chép template từ assets/remotion-live-overlay và `npm install` (lần đầu ~1–2 phút).
- Giấy phép Remotion: miễn phí cho cá nhân/tổ chức <= 3 người; công ty lớn hơn cần license.
  Có key → đặt biến môi trường REMOTION_LICENSE_KEY; không có → render với --is-production=false.
Ra: 04_anh/overlay/khung_live_dong.mov (ProRes 4444 alpha) hoặc .webm (VP9 alpha, rất nhẹ).
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path
from PIL import Image

SKILL = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL / "assets" / "remotion-live-overlay"
DEFAULT_DIR = Path(os.environ.get("REMOTION_OVERLAY_DIR", "D:/CapCut/_remotion/live-overlay"))
JOINERS = ["Anh Tư", "Cô Ba", "Chú Năm", "Chị Sáu", "Anh Hai", "Bác Bảy"]


def tool(name):
    return shutil.which(name) or shutil.which(name + ".cmd") or name


def ensure_project(rdir: Path):
    if not (rdir / "package.json").exists():
        print("Tạo project Remotion từ template:", rdir)
        rdir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(TEMPLATE, rdir, dirs_exist_ok=True)
    if not (rdir / "node_modules" / "remotion").exists():
        print("npm install (lần đầu)...")
        subprocess.run([tool("npm"), "install", "--no-audit", "--no-fund"], cwd=rdir, check=True)
    # luôn đồng bộ mã nguồn composition mới nhất từ skill
    for f in (TEMPLATE / "src").glob("*.ts*"):  # đồng bộ mọi file nguồn (LiveOverlay, ProductFx, Root, index)
        shutil.copy(f, rdir / "src" / f.name)


def avatar_crop(proj: Path, ov: dict) -> Image.Image:
    src = proj / "00_input" / "nguoi_mau.png"
    if not src.exists():
        src = proj / "00_input" / "san_pham.png"
    mi = Image.open(src).convert("RGB")
    box = ov.get("avatar_box")
    if not box:
        side = int(min(mi.width, mi.height) * 0.42)
        cx, cy = mi.width // 2, int(mi.height * 0.32)
        box = [max(0, cx - side // 2), max(0, cy - side // 2), cx + side // 2, cy + side // 2]
    return mi.crop(tuple(box)).resize((168, 168))


def render_overlay(proj: Path, data: dict, clip_times: list, total: float, fmt: str = "prores") -> Path:
    """clip_times: [(clip_id, start_s, end_s)] theo timeline đã cắt. Trả về đường dẫn video overlay."""
    rdir = DEFAULT_DIR
    ensure_project(rdir)
    key = data.get("name", proj.name)
    pub = rdir / "public" / key
    pub.mkdir(parents=True, exist_ok=True)
    ov = data.get("overlay", {})
    avatar_crop(proj, ov).save(pub / "avatar.png")
    prod = Image.open(proj / "00_input" / "san_pham.png").convert("RGBA")
    prod.thumbnail((300, 300))
    prod.save(pub / "product.png")

    comments = {c["id"]: c.get("comments", []) for c in data["clips"]}
    names = [n for c in data["clips"] for n, _ in c.get("comments", [])]
    props = {
        "durationSec": round(total, 3),
        "shopName": data.get("shop_name") or "Shop",
        "likes": ov.get("likes", "12,5K"),
        "viewers": int(str(ov.get("viewers", "2947")).replace(".", "").replace(",", "") or 2947),
        "productTitle": ov.get("product_title", ""),
        "productLine2": ov.get("product_line2", ""),
        "productLine3": ov.get("product_line3", ""),
        "hotline": ov.get("hotline", ""),
        "avatar": f"{key}/avatar.png",
        "product": f"{key}/product.png",
        "clips": [{"start": s, "end": e, "comments": comments.get(cid, [])} for cid, s, e in clip_times],
        "joiners": [n for n in JOINERS if n not in names][:5] or JOINERS,
        # hiệu ứng sản phẩm (mốc tuyệt đối trên timeline, do build_draft tính vào c["_fx_abs"])
        "fx": [f for c in data["clips"] for f in c.get("_fx_abs", [])],
    }
    props_path = rdir / "out" / f"{key}_props.json"
    props_path.parent.mkdir(exist_ok=True)
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

    raw = rdir / "out" / f"{key}_raw.mov"
    cmd = [tool("npx"), "remotion", "render", "LiveOverlay", str(raw), f"--props={props_path}"]
    lic = os.environ.get("REMOTION_LICENSE_KEY")
    cmd += [f"--license-key={lic}"] if lic else ["--is-production=false"]
    print("Remotion render", f"{total:.1f}s ...")
    subprocess.run(cmd, cwd=rdir, check=True)

    out_dir = proj / "04_anh" / "overlay"
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "webm":
        out = out_dir / "khung_live_dong.webm"
        enc = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-row-mt", "1",
               "-deadline", "good", "-cpu-used", "4"]
    else:  # ProRes 4444 nén vừa phải (qscale 12) — giữ alpha, nhẹ hơn ~40% so với bản gốc
        out = out_dir / "khung_live_dong.mov"
        enc = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-qscale:v", "12",
               "-vendor", "apl0"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), *enc, "-an", str(out)], check=True)
    raw.unlink(missing_ok=True)
    print("Overlay:", out, f"{out.stat().st_size / 1e6:.0f} MB")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--format", choices=["prores", "webm"], default="prores")
    a = ap.parse_args()
    proj = Path(a.project)
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    spec_p = proj / "07_capcut_spec" / "spec.json"
    if not spec_p.exists():
        sys.exit("Chưa có spec.json — chạy build_draft.py trước (hoặc build_draft.py --remotion).")
    spec = json.loads(spec_p.read_text(encoding="utf-8"))
    clips = next(t["items"] for t in spec["tracks"] if t["name"] == "clip_live")
    times = [(it["ref"].replace("clip_", ""), it["start"], it["start"] + it["duration"]) for it in clips]
    render_overlay(proj, data, times, times[-1][2], a.format)


if __name__ == "__main__":
    main()
