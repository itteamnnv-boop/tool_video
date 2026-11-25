"""Phân tích video mẫu: tách cảnh, khung hình đại diện, chép lời (faster-whisper, mốc từng từ), lưới khung phụ đề.

python -P phan_tich_video.py --video <mau.mp4> --project D:/CapCut/<TenDuAn> [--threshold 0.3] [--model medium]

Ra (trong <project>/01_phan_tich/):
  phan_tich.json   — thông số video, danh sách cảnh (start/end, khung hình, lời trong cảnh), toàn bộ từ + mốc
  phan_tich.md     — bản đọc nhanh cho người
  canh/<sNN>_{a,b,c}.png — 3 khung (15%/50%/85%) mỗi cảnh, độ phân giải gốc
  luoi_canh.png    — lưới tất cả cảnh (mỗi hàng 1 cảnh)
  luoi_phu_de_<k>.png — khung mỗi 0,5s có ghi mốc giây, để đọc phụ đề/chuyển động
  am_thanh.wav     — tiếng 16 kHz mono (chép lời)
Đồng thời tạo <project>/02_kich_ban/du_an.json khung sườn nếu chưa có (không ghi đè).
"""
import argparse, json, re, shutil, subprocess
from pathlib import Path

FONT = "C\\:/Windows/Fonts/arialbd.ttf"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def probe(video):
    j = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(video)]).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    num, den = v["r_frame_rate"].split("/")
    return {"path": str(video), "width": v["width"], "height": v["height"],
            "fps": round(float(num) / float(den), 3), "duration": float(j["format"]["duration"]),
            "has_audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def scene_cuts(video, thr):
    r = run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", f"select='gt(scene,{thr})',showinfo",
             "-an", "-f", "null", "-"])
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def frame(video, t, out):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(out)])


def transcribe(wav, model_name, lang):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("! Chưa có faster-whisper (pip install faster-whisper) — bỏ qua chép lời")
        return [], []
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as wf:  # tự đọc WAV 16 kHz mono (tránh lỗi PyAV lệch phiên bản)
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True, beam_size=5)
    words, segments = [], []
    for s in segs:
        segments.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()})
    return words, segments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--threshold", type=float, default=0.3, help="ngưỡng đổi cảnh (0.2 nhạy hơn, 0.4 ít cảnh hơn)")
    ap.add_argument("--min-shot", type=float, default=0.6, help="gộp cảnh ngắn hơn số giây này vào cảnh trước")
    ap.add_argument("--model", default="medium", help="faster-whisper: base/small/medium/large-v3")
    ap.add_argument("--lang", default="vi")
    ap.add_argument("--step", type=float, default=0.5, help="khoảng cách khung trong lưới phụ đề (giây)")
    a = ap.parse_args()

    video = Path(a.video)
    proj = Path(a.project).resolve()
    out = proj / "01_phan_tich"
    (out / "canh").mkdir(parents=True, exist_ok=True)
    info = probe(video)
    dur = info["duration"]
    print(f"Video {info['width']}x{info['height']} {info['fps']}fps {dur:.2f}s")

    # --- cảnh
    cuts = [c for c in scene_cuts(video, a.threshold) if a.min_shot <= c <= dur - a.min_shot]
    bounds = [0.0]
    for c in cuts:
        if c - bounds[-1] >= a.min_shot:
            bounds.append(round(c, 3))
    bounds.append(round(dur, 3))
    shots = []
    for i, (s, e) in enumerate(zip(bounds, bounds[1:]), 1):
        sid = f"s{i:02d}"
        kf = []
        for tag, f in (("a", 0.15), ("b", 0.5), ("c", 0.85)):
            p = out / "canh" / f"{sid}_{tag}.png"
            frame(video, s + (e - s) * f, p)
            kf.append(f"01_phan_tich/canh/{p.name}")
        shots.append({"id": sid, "start": s, "end": e, "duration": round(e - s, 3), "keyframes": kf})
    print(f"{len(shots)} cảnh: " + ", ".join(f"{x['id']} {x['start']:.2f}-{x['end']:.2f}" for x in shots))

    # lưới cảnh: mỗi hàng = 1 cảnh (3 khung), ghi id + mốc
    rows = []
    for sh in shots:
        row = out / f"_row_{sh['id']}.png"
        ins = sum((["-i", str(proj / k)] for k in sh["keyframes"]), [])
        label = f"{sh['id']}  {sh['start']:.2f}-{sh['end']:.2f}s"
        run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
             "[0:v]scale=-2:420[a];[1:v]scale=-2:420[b];[2:v]scale=-2:420[c];[a][b][c]hstack=3,"
             f"drawtext=fontfile='{FONT}':text='{label}':x=10:y=10:fontsize=30:fontcolor=yellow:box=1:boxcolor=black@0.6",
             str(row)])
        rows.append(row)
    ins = sum((["-i", str(r)] for r in rows), [])
    if len(rows) > 1:
        run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", f"vstack={len(rows)}", str(out / "luoi_canh.png")])
    else:
        shutil.copy(rows[0], out / "luoi_canh.png")
    for r in rows:
        r.unlink(missing_ok=True)

    # lưới phụ đề: khung mỗi a.step giây, 6 cột x 3 hàng mỗi ảnh, có mốc giây
    per = 18
    n = int(dur / a.step) + 1
    for k in range(0, n, per):
        t0 = k * a.step
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", str(video), "-vf",
             f"fps=1/{a.step},scale=300:-2,drawtext=fontfile='{FONT}':text='%{{pts\\:hms\\:{t0}}}':x=6:y=6:"
             "fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=6x3",
             "-frames:v", "1", str(out / f"luoi_phu_de_{k // per + 1}.png")])

    # --- tiếng + chép lời
    words, segments = [], []
    if info["has_audio"]:
        wav = out / "am_thanh.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)])
        print(f"Chép lời bằng faster-whisper {a.model}…")
        words, segments = transcribe(wav, a.model, a.lang)
    for sh in shots:
        ws = [w for w in words if sh["start"] - 0.05 <= (w["start"] + w["end"]) / 2 < sh["end"]]
        sh["words"] = ws
        sh["text"] = " ".join(w["word"] for w in ws)

    data = {"video": info, "threshold": a.threshold, "shots": shots, "segments": segments, "words": words}
    (out / "phan_tich.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [f"# Phân tích {video.name}", "",
          f"{info['width']}x{info['height']} · {info['fps']} fps · {dur:.2f}s · {len(shots)} cảnh", "",
          "| Cảnh | Thời gian | Lời |", "|---|---|---|"]
    md += [f"| {s['id']} | {s['start']:.2f}–{s['end']:.2f}s | {s['text']} |" for s in shots]
    md += ["", "## Lời theo câu (whisper)", ""] + [f"- {s['start']:.2f}–{s['end']:.2f}: {s['text']}" for s in segments]
    (out / "phan_tich.md").write_text("\n".join(md), encoding="utf-8")

    # --- khung sườn du_an.json (xem references/du_an_schema.md)
    dj = proj / "02_kich_ban" / "du_an.json"
    if not dj.exists():
        dj.parent.mkdir(parents=True, exist_ok=True)
        skel = {
            "name": proj.name, "draft_name": proj.name,
            "video_mau": str(video), "width": 1080, "height": 1920, "fps": 30,
            "nhan_vat": {"anh": "00_input/nhan_vat.png", "mo_ta": "", "trang_phuc": "",
                         "giong": "cheerful young Southern Vietnamese female voice"},
            "am_thanh": {"nhac": "khong", "nhac_file": "", "nhac_volume": 0.18},
            "phu_de_kieu": {},
            "shots": [{"id": s["id"], "start": s["start"], "end": s["end"],
                       "hinh": "?", "giong": "?", "mo_ta": "", "hanh_dong": "", "camera": "",
                       "dialogue": s["text"], "image_prompt": "", "grok_prompt": "",
                       "phu_de": []} for s in shots],
        }
        dj.write_text(json.dumps(skel, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Tạo khung sườn {dj}")
    print(f"Xong → {out}")


if __name__ == "__main__":
    main()
