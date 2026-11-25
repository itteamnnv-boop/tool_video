"""Chuyển clip Grok đã tải (Downloads/<prefix>_<clip_id>.mp4) vào 05_grok_video/<clip_id>.mp4 và kiểm tra.

python -P collect_downloads.py --project D:/CapCut/TenDuAn --prefix tenduan
"""
import argparse, json, os, shutil, subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--prefix", required=True, help="tiền tố tên file đã đặt khi tải (a.download = '<prefix>_<id>.mp4')")
    ap.add_argument("--downloads", default=str(Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"))
    a = ap.parse_args()
    proj = Path(a.project)
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    dst_dir = proj / "05_grok_video"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for c in data["clips"]:
        src = Path(a.downloads) / f"{a.prefix}_{c['id']}.mp4"
        dst = dst_dir / f"{c['id']}.mp4"
        if src.exists():
            shutil.move(str(src), dst)
        if not dst.exists():
            print(f"{c['id']}: THIẾU (chưa tải về {src.name})")
            continue
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                            "-of", "json", str(dst)], capture_output=True, text=True)
        j = json.loads(r.stdout or "{}")
        v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
        has_a = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
        print(f"{c['id']}: {v.get('width')}x{v.get('height')} {float(j.get('format', {}).get('duration', 0)):.2f}s "
              f"{'có tiếng' if has_a else 'KHÔNG CÓ TIẾNG'}")


if __name__ == "__main__":
    main()
