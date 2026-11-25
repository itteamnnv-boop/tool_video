"""Tạo ẢNH STORYBOARD NHÂN VẬT (character sheet) từ ảnh nhân vật bằng Codex CLI — chạy NGAY sau khi nhận ảnh nhân vật.

python -P tao_sheet_nhan_vat.py --project D:/CapCut/<TenDuAn> [--only bride] [--lam-lai] [--print]

Mỗi nhân vật (data["nhan_vats"] hoặc data["nhan_vat"]) ra 2 ảnh trong 00_input/sheet/:
  <slug>_mat.png       — 6 góc đầu/mặt: chính diện, 3/4 trái, nghiêng trái, 3/4 phải, nghiêng phải, cười tươi
  <slug>_toan_than.png — 5 góc toàn thân trong trang phục của video: trước, 3/4 trái, nghiêng, sau lưng, 3/4 phải
(slug = "vai" của nhân vật, hoặc "nhan_vat" khi chỉ có một người). Trang phục = "trang_phuc" nếu có, không thì
giữ trang phục trong ảnh. tao_anh.py tự gửi kèm 2 ảnh này làm tham chiếu, nên khung đầu (và clip Veo/Grok
dựng từ khung đầu) bám mặt/dáng nhân vật ở mọi góc máy — kể cả cảnh nghiêng, sau lưng, cận mặt.
Bỏ qua ảnh đã có (xoá file hoặc --lam-lai để tạo lại).
"""
import argparse, json, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

INSTR = ("Use your image generation tool in reference/edit mode with the attached image ({ref}) to generate ONE "
         "landscape 16:9 image (1536x1024). Prompt: \"{prompt}\". Then copy the resulting PNG into the current "
         "directory as {out}. Do not do anything else. Reply with the saved path.")

GIU_NGUOI = ("The person must be exactly the person in the reference photo: identical face shape, eyes, eyebrows, "
             "nose, lips, ears, skin tone, age, body build{kinh}. ")

MAT = ("Character reference sheet, head-and-shoulders turnaround of ONE person: six portraits of the same person "
       "arranged in a clean 3x2 grid — front view, three-quarter view facing left, full left profile, three-quarter "
       "view facing right, full right profile, and front view with a big natural smile showing teeth. "
       + GIU_NGUOI + "Hair: {toc}. Neutral relaxed expression except the smiling one. Soft even studio lighting, "
       "plain light grey seamless background, sharp focus, photorealistic, natural skin texture. "
       "No text, no labels, no numbers, no borders.")

TOAN_THAN = ("Character reference sheet, full-body turnaround of ONE person standing in a relaxed neutral pose: five "
             "full-length views of the same person side by side from head to shoes — front view, three-quarter view "
             "facing left, left side profile, back view, three-quarter view facing right. " + GIU_NGUOI +
             "Outfit, identical in all five views: {trang_phuc}. Hair: {toc}. Soft even studio lighting, plain light "
             "grey seamless background, the whole body visible in every view, photorealistic. "
             "No text, no labels, no numbers, no borders.")


def nhan_vats(data):
    if data.get("nhan_vats"):
        return data["nhan_vats"]
    nv = data.get("nhan_vat", {})
    return [dict(nv, anh=nv.get("anh", "00_input/nhan_vat.png"))]


def slug(nv):
    return re.sub(r"[^a-z0-9_]+", "_", (nv.get("vai") or "nhan_vat").lower()).strip("_") or "nhan_vat"


def sheet_paths(proj, nv):
    """Đường dẫn 2 ảnh sheet của nhân vật (dùng chung với tao_anh.py)."""
    d = proj / "00_input" / "sheet"
    return d / f"{slug(nv)}_mat.png", d / f"{slug(nv)}_toan_than.png"


def prompts(nv):
    tp = nv.get("trang_phuc", "").strip() or "exactly the same clothes as in the reference photo"
    toc = nv.get("toc", "").strip() or "the same hairstyle and hair color as in the reference photo"
    kinh = ", and the same glasses" if nv.get("kinh") else ""
    return (MAT.format(toc=toc, kinh=kinh), TOAN_THAN.format(trang_phuc=tp, toc=toc, kinh=kinh))


def run(codex, proj, nv, out, prompt, timeout):
    d = out.parent
    ref = f"ref_{slug(nv)}.png"
    shutil.copy(proj / nv["anh"], d / ref)
    cmd = [codex, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(d),
           INSTR.format(ref=ref, prompt=prompt, out=out.name), "-i", ref]
    try:
        p = subprocess.run(cmd, cwd=d, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        (d / f"_log_{out.stem}.txt").write_text(p.stdout[-4000:] + "\n" + p.stderr[-2000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        return out.name, "hết giờ"
    return out.name, "OK" if out.exists() else "LỖI (xem _log)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--only", nargs="*", help="chỉ các vai này (slug)")
    ap.add_argument("--lam-lai", action="store_true", help="xoá sheet cũ và tạo lại")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    jobs = []
    for nv in nhan_vats(data):
        if a.only and slug(nv) not in a.only:
            continue
        if not (proj / nv["anh"]).exists():
            sys.exit(f"Thiếu ảnh nhân vật {proj / nv['anh']}")
        for out, pr in zip(sheet_paths(proj, nv), prompts(nv)):
            if a.print:
                print(f"[{out.name}] {pr}\n")
                continue
            if a.lam_lai:
                out.unlink(missing_ok=True)
            if not out.exists():
                jobs.append((nv, out, pr))
    if a.print:
        return
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex:
        sys.exit("Không tìm thấy codex CLI (npm i -g @openai/codex, rồi codex login).")
    (proj / "00_input" / "sheet").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for name, st in ex.map(lambda j: run(codex, proj, j[0], j[1], j[2], a.timeout), jobs):
            print(f"{name}: {st}")
    if not jobs:
        print("Sheet đã có đủ (dùng --lam-lai để tạo lại).")


if __name__ == "__main__":
    main()
