"""Tạo ảnh cảnh bằng Codex CLI (image_generation, đăng nhập ChatGPT), song song, có ảnh tham chiếu.

python -P gen_images.py --project D:/CapCut/TenDuAn [--only v1 v3] [--workers 5]
Ra: 04_anh/codex/<clip_id>.png (bỏ qua ảnh đã có — xoá file để tạo lại).
Lưu ý: prompt PHẢI đứng trước `-i` (cờ -i nhận nhiều file và nuốt mọi tham số sau nó).
"""
import argparse, json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

INSTR = ("Use your image generation tool (reference/edit mode with the attached images: {refs}) to generate ONE "
         "portrait 9:16 (1024x1536) image. Prompt: \"{prompt}\". Then copy the resulting PNG into the current "
         "directory as {out}. Do not do anything else. Reply with the saved path.")


def run(codex, outdir, clip, refs, timeout):
    out = f"{clip['id']}.png"
    if (outdir / out).exists():
        return clip["id"], "đã có"
    desc = ", ".join(f"image {i + 1} = {r}" for i, r in enumerate(refs)) or "none"
    prompt = INSTR.format(refs=desc, prompt=clip["image_prompt"], out=out)
    cmd = [codex, "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(outdir), prompt]
    if refs:
        cmd += ["-i", *refs]
    try:
        p = subprocess.run(cmd, cwd=outdir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        (outdir / f"_log_{clip['id']}.txt").write_text(p.stdout[-4000:] + "\n" + p.stderr[-2000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        return clip["id"], "hết giờ"
    return clip["id"], "OK" if (outdir / out).exists() else "LỖI (xem _log)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    proj = Path(a.project)
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    outdir = proj / "04_anh" / "codex"
    refs = [r for r in ("ref_nguoi_mau.png", "ref_san_pham.png") if (outdir / r).exists()]
    codex = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex:
        sys.exit("Không tìm thấy codex CLI (npm i -g @openai/codex, rồi codex login).")
    clips = [c for c in data["clips"] if c.get("image_prompt") and (not a.only or c["id"] in a.only)]
    with ThreadPoolExecutor(a.workers) as ex:
        for cid, st in ex.map(lambda c: run(codex, outdir, c, refs, a.timeout), clips):
            print(f"{cid}: {st}")


if __name__ == "__main__":
    main()
