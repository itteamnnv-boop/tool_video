"""Render bản xem trước MP4 từ 07_capcut_spec/timeline.json (đoạn video + nhạc + phụ đề nhiều tầng bằng drawtext).

python -P xem_truoc.py --project D:/CapCut/<TenDuAn> [--out 08_xem_truoc/xem_truoc.mp4]

Phụ đề trong bản xem trước là ước lượng (font Windows: Arial / Times Bold Italic); bản chính là chữ CapCut trong draft.
Kèm ảnh lưới 08_xem_truoc/luoi.png (mỗi 0,5s một khung) để kiểm tra nhanh.
"""
import argparse, json, subprocess, sys
from pathlib import Path

FONTS = "C\\:/Windows/Fonts/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", default="08_xem_truoc/xem_truoc.mp4")
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    tl = json.loads((proj / "07_capcut_spec" / "timeline.json").read_text(encoding="utf-8"))
    W, H = tl["width"], tl["height"]
    out = proj / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    txt_dir = proj / "07_capcut_spec" / "_txt"
    txt_dir.mkdir(exist_ok=True)

    ins, n = [], len(tl["shots"])
    for s in tl["shots"]:
        ins += ["-i", str(proj / s["file"])]
    chain = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][a0]"
    if tl.get("music"):
        ins += ["-i", str(proj / tl["music"]["path"])]
        chain += f";[{n}:a]volume={tl['music']['volume']}[m];[a0][m]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        chain += ";[a0]anull[a]"
    draws = []
    for i, ln in enumerate(tl["lines"]):
        st = tl["kieu"][ln["kieu"]]
        tf = txt_dir / f"l{i}.txt"
        tf.write_text(ln["text"], encoding="utf-8")
        ycen = H / 2 * (1 - float(ln["y"]))
        a0, a1 = ln["start"], ln["end"]
        glow = ":borderw=3:bordercolor=white@0.35" if st.get("italic") else ":borderw=1:bordercolor=black@0.35"
        tpath = tf.as_posix().replace(":", "\\:")
        draws.append(
            f"drawtext=fontfile='{FONTS}{st['font']}':textfile='{tpath}':"
            f"fontsize={st['px']}:fontcolor={st['color']}:x=(w-text_w)/2:y={ycen:.0f}-text_h/2"
            f"{glow}:shadowcolor=black@0.7:shadowx=3:shadowy=3:"
            f"alpha='min(1,(t-{a0})/0.25)':enable='between(t,{a0},{a1})'")
    chain += ";[v0]" + (",".join(draws) if draws else "null") + "[v]"
    cmd = ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", chain, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(r.stderr[-2000:])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out), "-vf", "fps=2,scale=240:-2,tile=6x4",
                    "-frames:v", "1", str(out.parent / "luoi.png")])
    print(f"Xem trước: {out} ({tl['total']:.2f}s) | lưới: {out.parent / 'luoi.png'}")


if __name__ == "__main__":
    main()
