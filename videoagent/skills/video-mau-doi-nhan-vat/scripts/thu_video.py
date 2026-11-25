"""Chuyển clip Grok đã tải (~/Downloads/<prefix>_<id>.mp4) vào <project>/05_video/<id>.mp4 và kiểm tra có tiếng.

python -P thu_video.py --project D:/CapCut/<TenDuAn> --prefix <prefix> [--downloads <thư mục>]
"""
import argparse, json, os, re, shutil, subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--downloads", default=str(Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"))
    a = ap.parse_args()
    dst = Path(a.project) / "05_video"
    dst.mkdir(parents=True, exist_ok=True)
    pat = re.compile(rf"^{re.escape(a.prefix)}_(.+?)(?: \(\d+\))?\.mp4$")
    found = sorted(Path(a.downloads).glob(f"{a.prefix}_*.mp4"), key=lambda p: p.stat().st_mtime)
    if not found:
        print("Không thấy file nào khớp", a.prefix)
    for f in found:
        m = pat.match(f.name)
        if not m:
            continue
        out = dst / f"{m.group(1)}.mp4"
        shutil.move(str(f), out)
        j = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                                       "-of", "json", str(out)], capture_output=True, text=True).stdout)
        audio = any(s["codec_type"] == "audio" for s in j.get("streams", []))
        print(f"{out.name}: {float(j['format']['duration']):.1f}s, {'có tiếng' if audio else 'KHÔNG CÓ TIẾNG'}")


if __name__ == "__main__":
    main()
