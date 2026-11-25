"""Tạo ảnh khung đầu cho từng cảnh bằng Codex CLI: dựng lại khung hình video mẫu, THAY NHÂN VẬT bằng ảnh nhân vật mới.

python -P tao_anh.py --project D:/CapCut/<TenDuAn> [--only s01 s03] [--workers 4] [--print]

Cảnh cần ảnh: "hinh": "tao_moi". (Clip giọng riêng "giong_rieng" dùng lại ảnh của cảnh khác — "giong_anh" — nên không tạo ảnh.)
Tham chiếu: ảnh 1 = khung video mẫu (shot["khung"], mặc định 01_phan_tich/canh/<id>_a.png),
            ảnh 2 = 00_input/nhan_vat.png.  Ra: 04_anh/<id>.png (bỏ qua ảnh đã có — xoá để tạo lại).
Lưu ý: prompt PHẢI đứng trước `-i` (cờ -i nuốt mọi tham số sau nó).
"""
import argparse, json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tao_sheet_nhan_vat import nhan_vats, sheet_paths  # noqa: E402  (dùng chung quy ước nhân vật + đường dẫn sheet)

INSTR = ("Use your image generation tool in reference/edit mode with the attached images ({refs}) to generate ONE "
         "{khung} image. Prompt: \"{prompt}\". Then copy the resulting PNG into the current "
         "directory as {out}. Do not do anything else. Reply with the saved path.")

MAC_DINH = ("Recreate image 1 as faithfully as possible: identical camera angle, framing, lens, lighting, color grade, "
            "background and every prop, the same product with its label exactly as in image 1, the same body pose, "
            "hand gesture and facial expression{trang_phuc}. {thay_nguoi} "
            "Remove all on-screen text, captions and subtitles that appear in image 1 (clean frame, no text overlay). "
            "Photorealistic, natural skin, sharp focus.{them}")


def ref_plan(proj, data, shot):
    """Danh sách ảnh tham chiếu [(tên trong 04_anh, nguồn, mô tả)] và số thứ tự ảnh của từng nhân vật.
    Mỗi nhân vật: ảnh gốc + 2 ảnh storyboard (00_input/sheet/<vai>_mat.png, _toan_than.png) nếu đã tạo
    bằng tao_sheet_nhan_vat.py."""
    plan = [(f"ref_khung_{shot['id']}.png", proj / (shot.get("khung") or f"01_phan_tich/canh/{shot['id']}_a.png"),
             "frame from the reference video")]
    so = []
    nvs = nhan_vats(data)
    for k, n in enumerate(nvs, 1):
        tag = "" if len(nvs) == 1 else f"_{k}"
        who = f"the new {n.get('vai') or 'person'}"
        items = [(f"ref_nhan_vat{tag}.png", proj / n["anh"], f"photo of {who}")]
        mat, than = sheet_paths(proj, n)
        if mat.exists():
            items.append((f"ref_nhan_vat{tag}_mat.png", mat, f"face turnaround sheet of {who}, all angles"))
        if than.exists():
            items.append((f"ref_nhan_vat{tag}_toan_than.png", than, f"full-body turnaround sheet of {who} in the outfit"))
        so.append(list(range(len(plan) + 1, len(plan) + 1 + len(items))))
        plan += items
    return plan, so


def ds_anh(nums):
    return f"image {nums[0]}" if len(nums) == 1 else "images " + ", ".join(map(str, nums[:-1])) + f" and {nums[-1]}"


def build_prompt(data, shot, so):
    if shot.get("image_prompt"):
        return shot["image_prompt"]
    nvs = nhan_vats(data)
    tps = [f"the {n['vai']} wears {n['trang_phuc']}" if n.get("vai") else n["trang_phuc"]
           for n in nvs if n.get("trang_phuc", "").strip()]
    trang_phuc = f", but the outfit: {'; '.join(tps)}" if tps else " and the same outfit"
    goc = ("Use the turnaround sheets to get the face and body right from this exact camera angle "
           "(profile, three-quarter, back or close-up). " if any(len(x) > 1 for x in so) else "")
    if len(nvs) == 1:
        thay = (f"Replace ONLY the person: the person must be the one in {ds_anh(so[0])} — same face, facial features, "
                f"hairstyle, hair color and skin tone. {goc}")
    else:
        each = "; ".join(f"the {n['vai']} must be the person in {ds_anh(s)} (same face, facial features, hairstyle, "
                         f"hair color and skin tone; keep any glasses)" for n, s in zip(nvs, so))
        thay = (f"Replace ONLY the people's identities: {each}. Do not swap or mix their faces. {goc}"
                "If a person is seen from behind or too small to show the face, keep matching hair and build.")
    them = f" Shot notes: {shot['mo_ta'].rstrip('.')}." if shot.get("mo_ta") else ""
    return MAC_DINH.format(trang_phuc=trang_phuc, thay_nguoi=thay.strip(), them=them)


def khung(data):
    w, h = data.get("width", 1080), data.get("height", 1920)
    if w > h:
        return "landscape 16:9 (1536x1024)"
    return "square 1:1 (1024x1024)" if w == h else "portrait 9:16 (1024x1536)"


def run(codex, proj, data, shot, timeout):
    outdir = proj / "04_anh"
    out = f"{shot['id']}.png"
    if (outdir / out).exists():
        return shot["id"], "đã có"
    plan, so = ref_plan(proj, data, shot)
    refs = []
    for name, src, _ in plan:
        if not src.exists():
            return shot["id"], f"thiếu {src}"
        shutil.copy(src, outdir / name)
        refs.append(name)
    parts = ", ".join(f"image {i} = {name} ({desc})" for i, (name, _, desc) in enumerate(plan, 1))
    prompt = INSTR.format(refs=parts, khung=khung(data), prompt=build_prompt(data, shot, so), out=out)
    cmd = [codex, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(outdir), prompt, "-i", *refs]
    try:
        p = subprocess.run(cmd, cwd=outdir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        (outdir / f"_log_{shot['id']}.txt").write_text(p.stdout[-4000:] + "\n" + p.stderr[-2000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        return shot["id"], "hết giờ"
    return shot["id"], "OK" if (outdir / out).exists() else "LỖI (xem _log)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--print", action="store_true", help="chỉ in prompt, không chạy Codex")
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    shots = [s for s in data["shots"] if s.get("hinh") == "tao_moi" and (not a.only or s["id"] in a.only)]
    thieu = [str(p.relative_to(proj)) for n in nhan_vats(data) for p in sheet_paths(proj, n) if not p.exists()]
    if thieu:
        print("! Chưa có ảnh storyboard nhân vật (" + ", ".join(thieu) + ") — nên chạy tao_sheet_nhan_vat.py trước "
              "để nhân vật bám sát hơn ở mọi góc máy.")
    if a.print:
        for s in shots:
            plan, so = ref_plan(proj, data, s)
            print(f"[{s['id']}] refs: {[p[0] for p in plan]}\n{build_prompt(data, s, so)}\n")
        return
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex:
        sys.exit("Không tìm thấy codex CLI (npm i -g @openai/codex, rồi codex login).")
    (proj / "04_anh").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for sid, st in ex.map(lambda s: run(codex, proj, data, s, a.timeout), shots):
            print(f"{sid}: {st}")


if __name__ == "__main__":
    main()
