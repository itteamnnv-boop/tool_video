"""Render preview MP4 mô phỏng draft (clip giọng gốc + khung live + bình luận + phụ đề tô từ khoá, pop-up).
(`capcut render` hỏng với ffmpeg 9 vì -filter_complex_script đã bị bỏ.)

python -P render_preview.py --project D:/CapCut/TenDuAn
Ra: 08_preview/<draft_name>_preview.mp4
"""
import argparse, json, subprocess
from pathlib import Path

FPS = 30


def ass_time(x):
    cs = round(x * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    a = ap.parse_args()
    proj = Path(a.project)
    spec_dir = proj / "07_capcut_spec"
    spec = json.loads((spec_dir / "spec.json").read_text(encoding="utf-8"))
    tracks = {t["name"]: t["items"] for t in spec["tracks"]}
    out_dir = proj / "08_preview"
    out_dir.mkdir(exist_ok=True)

    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "", "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginL, MarginR, MarginV, BorderStyle, Outline, Shadow",
           "Style: Sub,Arial,70,&H00FFFFFF,&H00000000,&H90000000,-1,2,70,70,620,1,7,4",
           "", "[Events]", "Format: Layer, Start, End, Style, Text"]
    ranges = {o["target"]: o["ranges"] for o in spec["operations"] if o["op"] == "text-ranges"}
    for it in tracks.get("phu_de", []):
        txt, parts = it["text"], []
        for r in ranges.get(it["ref"], [{"start": 0, "end": len(txt), "font_color": "#FFFFFF"}]):
            seg = txt[r["start"]:r["end"]]
            parts.append("{\\c&H4DE1FF&\\fs84}" + seg + "{\\c&HFFFFFF&\\fs70}" if r["font_color"].upper() != "#FFFFFF" else seg)
        pop = "{\\fscx70\\fscy70\\t(0,160,\\fscx108\\fscy108)\\t(160,240,\\fscx100\\fscy100)}"
        ass.append(f"Dialogue: 0,{ass_time(it['start'])},{ass_time(it['start'] + it['duration'])},Sub,{pop}{''.join(parts)}")
    (out_dir / "preview.ass").write_text("\n".join(ass), encoding="utf-8-sig")

    cmd, fc, vl = ["ffmpeg", "-v", "error", "-y"], [], []
    clips = tracks["clip_live"]
    for i, it in enumerate(clips):
        d = it["duration"]
        cmd += ["-ss", str(it.get("sourceStart", 0)), "-t", str(d), "-i", str((spec_dir / it["path"]).resolve())]
        fc.append(f"[{i}:v:0]fps={FPS},scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                  f"tpad=stop_mode=clone:stop_duration=1,trim=duration={d},setpts=PTS-STARTPTS,setsar=1[v{i}]")
        fc.append(f"[{i}:a:0]atrim=duration={d},asetpts=PTS-STARTPTS,volume={it.get('volume', 1.0)},afade=t=in:d=0.04,"
                  f"afade=t=out:st={d - 0.06}:d=0.06,apad=whole_dur={d}[a{i}]")
        vl.append(f"[v{i}][a{i}]")
    n = len(clips)
    fc.append("".join(vl) + f"concat=n={n}:v=1:a=1[base][avo]")
    idx, cur = n, "[base]"
    cm = tracks.get("binh_luan", [])
    if cm:
        labels = []
        for k, it in enumerate(cm):
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(it["duration"]), "-i", str((spec_dir / it["path"]).resolve())]
            fc.append(f"[{idx}:v]format=rgba,trim=duration={it['duration']},setpts=PTS-STARTPTS[c{k}]")
            labels.append(f"[c{k}]")
            idx += 1
        fc.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[cm]")
        fc.append(f"{cur}[cm]overlay=0:0:format=auto[b1]")
        cur = "[b1]"
    if tracks.get("khung_live"):
        fr = tracks["khung_live"][0]
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(fr["duration"]), "-i", str((spec_dir / fr["path"]).resolve())]
        fc.append(f"{cur}[{idx}:v]overlay=0:0:format=auto[b2]")
        cur = "[b2]"
        idx += 1
    if tracks.get("khung_live_dong"):  # khung live động (Remotion, video có alpha)
        dyn = tracks["khung_live_dong"][0]
        src = (spec_dir / dyn["path"]).resolve()
        if src.suffix.lower() == ".webm":
            cmd += ["-c:v", "libvpx-vp9"]  # dùng decoder libvpx để giữ kênh alpha
        cmd += ["-i", str(src)]
        fc.append(f"[{idx}:v]format=yuva444p,setpts=PTS-STARTPTS[dyn]")
        fc.append(f"{cur}[dyn]overlay=0:0:format=auto:eof_action=pass[b3]")
        cur = "[b3]"
        idx += 1
    fc.append(f"{cur}subtitles=preview.ass,format=yuv420p[vout]")
    beds = []
    for tname, fin, fout in (("nhac_nen", 0.3, 1.5), ("tap_am", 0.5, 1.0)):  # nhạc nền + tạp âm, trộn dưới giọng
        if tracks.get(tname):
            mu = tracks[tname][0]
            cmd += ["-i", str((spec_dir / mu["path"]).resolve())]
            fc.append(f"[{idx}:a]volume={mu.get('volume', 0.15)},afade=t=in:d={fin},"
                      f"afade=t=out:st={max(0, mu['duration'] - fout)}:d={fout}[{tname}]")
            beds.append(f"[{tname}]")
            idx += 1
    if beds:
        fc.append(f"[avo]{''.join(beds)}amix=inputs={1 + len(beds)}:duration=first:normalize=0[aout]")
    else:
        fc.append("[avo]anull[aout]")
    (out_dir / "filter.txt").write_text(";\n".join(fc), encoding="utf-8")
    out = f"{spec['name']}_preview.mp4"
    cmd += ["-/filter_complex", "filter.txt", "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", out]
    subprocess.run(cmd, cwd=out_dir, check=True)
    print("OK ->", out_dir / out)


if __name__ == "__main__":
    main()
