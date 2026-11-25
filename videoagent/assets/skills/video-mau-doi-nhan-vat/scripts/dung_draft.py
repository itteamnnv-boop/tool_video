"""Dựng lại video mẫu với nhân vật mới → các đoạn chuẩn hoá + draft CapCut (phụ đề nhiều tầng là chữ CapCut gốc).

python -P dung_draft.py --project D:/CapCut/<TenDuAn> [--no-compile] [--skip-missing] [--max-speed 1.3]

Mỗi cảnh (du_an.json → shots[]):
  hinh  = "tao_moi" : hình lấy từ clip mới 05_video/<id>.mp4 (Grok, nhân vật mới / khung sạch chữ)
          "giu_goc" : hình cắt từ video mẫu [start, end] — CHỈ khi cảnh không lộ nhân vật VÀ không có chữ dính cứng
  giong = "clip"        : tiếng của chính clip 05_video/<id>.mp4 (nhân vật nói trong hình, khớp khẩu hình)
          "giong_rieng" : tiếng từ clip nói riêng 05_video/<id>_giong.mp4 (nhân vật mới đọc lời cảnh này
                          ngoài hình — dùng cho cảnh cận sản phẩm/tay, nhân vật không lộ mặt)
          "goc"         : giữ tiếng gốc của video mẫu (chỉ khi không có giọng nhân vật cũ, vd chỉ có nhạc/tạp âm)
          "khong"       : im lặng
Lời nói mới được đặt vào đúng chỗ lời nói gốc bắt đầu trong cảnh; nói dài hơn → tăng tốc (<= --max-speed,
giữ cao độ), vẫn dài hơn → kéo dài cảnh (phụ đề của cảnh co giãn theo).
Ra: 06_doan/<id>.mp4, 03_nhac/nhac_nen.wav (nếu có), 07_capcut_spec/{spec.json,timeline.json}, draft CapCut.
"""
import argparse, json, os, re, shutil, subprocess, sys, unicodedata
from pathlib import Path

CLI = shutil.which("capcut-cli") or shutil.which("capcut-cli.cmd") or "capcut-cli"

KIEU_MAC_DINH = {  # đo từ video mẫu đã duyệt (canvas-n26): dẫn nhỏ trắng / nhấn nghiêng tím nhạt / IN HOA đậm
    "dan":  {"size": 6,  "px": 48,  "color": "#FFFFFF", "bold": False, "italic": False, "y": -0.45,
             "font": "arial.ttf", "delay": 0.0, "anim": "fade-in"},
    "nhan": {"size": 12, "px": 100, "color": "#E8D5FF", "bold": True, "italic": True, "y": -0.57,
             "font": "timesbi.ttf", "delay": 0.12, "anim": "pop-up"},
    "hoa":  {"size": 10, "px": 82,  "color": "#FFFFFF", "bold": True, "italic": False, "y": -0.68,
             "font": "arialbd.ttf", "delay": 0.24, "anim": "pop-up"},
}


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"Lỗi: {' '.join(map(str, cmd[:6]))}…\n{r.stderr[-1500:]}")
    return r


def cli(*args, check=True):
    r = subprocess.run([CLI, *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode not in (0, 1):
        sys.exit(f"capcut-cli {args[0]} lỗi: {r.stdout}{r.stderr}")
    return r


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def speech_span(path, thr=-35, min_sil=0.3):
    """(đầu, cuối) khoảng có tiếng nói trong file, theo silencedetect."""
    dur = duration(path)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        f"silencedetect=noise={thr}dB:d={min_sil}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]
    s0, s1 = 0.0, dur
    if starts and starts[0] <= 0.05 and ends:
        s0 = ends[0]
    if starts and (len(ends) < len(starts) or ends[-1] >= dur - 0.05):
        s1 = starts[-1] if starts[-1] > s0 else dur
    return s0, s1


def atempo(speed):
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    out.append(f"atempo={s:.4f}")
    return ",".join(out)


def build_segment(proj, data, shot, words, max_speed, W, H, FPS):
    """Tạo 06_doan/<id>.mp4; trả về (thời lượng mới, hệ số tốc độ) hoặc (None, None) nếu thiếu clip."""
    mau = Path(data["video_mau"])
    s, e = shot["start"], shot["end"]
    D = e - s
    hinh, giong = shot.get("hinh", "giu_goc"), shot.get("giong", "goc")
    if hinh not in ("tao_moi", "giu_goc") or giong not in ("clip", "giong_rieng", "goc", "khong"):
        sys.exit(f"{shot['id']}: hinh='{hinh}' / giong='{giong}' chưa hợp lệ — điền theo references/du_an_schema.md.")
    if hinh == "tao_moi" and giong == "goc":
        sys.exit(f"{shot['id']}: hinh=tao_moi không đi với giong=goc (giọng nhân vật cũ) — dùng 'clip' hoặc 'giong_rieng'.")
    clip = proj / "05_video" / f"{shot['id']}.mp4"
    voice = clip if giong == "clip" else proj / "05_video" / f"{shot['id']}_giong.mp4"
    if (hinh == "tao_moi" and not clip.exists()) or (giong in ("clip", "giong_rieng") and not voice.exists()):
        return None, None
    ws = [w for w in words if s - 0.05 <= (w["start"] + w["end"]) / 2 < e]
    w0, w1 = (ws[0]["start"] - s, ws[-1]["end"] - s) if ws else (0.15, D - 0.15)
    w0 = max(0.0, w0)
    window = max(0.3, w1 - w0)
    speed, newD, a0, a1 = 1.0, D, 0.0, 0.0
    if giong in ("clip", "giong_rieng"):
        a0, a1 = speech_span(voice)
        a0, a1 = max(0.0, a0 - 0.05), a1 + 0.12
        speech = a1 - a0
        speed = min(max_speed, max(1.0, speech / window))
        over = speech / speed - (D - w0 - 0.1)
        if over > 0:
            newD = D + over
    vf_fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
              f"tpad=stop_mode=clone:stop_duration=30")
    out = proj / "06_doan" / f"{shot['id']}.mp4"
    out.parent.mkdir(exist_ok=True)

    # --- nguồn hình
    if hinh == "tao_moi":
        cd = duration(clip)
        vspeed = speed if giong == "clip" else 1.0  # khớp khẩu hình: hình tăng tốc cùng tiếng
        st = max(0.0, a0 - w0 * speed) if giong == "clip" else 0.0  # lùi trước chỗ bắt đầu nói đúng w0 giây
        st = max(0.0, min(st, cd - newD * vspeed)) if cd > newD * vspeed else 0.0
        ins = ["-ss", f"{st:.3f}", "-i", str(clip)]
        fv = f"[0:v]setpts=(PTS-STARTPTS)/{vspeed:.4f},{vf_fit}[v]"
    else:
        ins = ["-ss", f"{s:.3f}", "-t", f"{D:.3f}", "-i", str(mau)]
        fv = f"[0:v]setpts=PTS-STARTPTS,{vf_fit}[v]"
    # --- nguồn tiếng
    if giong == "clip":
        fa = f"[0:a]{atempo(speed)},apad[a]"
    elif giong == "giong_rieng":
        ins += ["-ss", f"{a0:.3f}", "-t", f"{a1 - a0:.3f}", "-i", str(voice)]
        fa = f"[1:a]{atempo(speed)},adelay={int(w0 * 1000)}:all=1,apad[a]"
    elif giong == "goc":
        fa = "[0:a]apad[a]"
    else:
        ins += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        fa = "[1:a]anull[a]"
    sh(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", f"{fv};{fa}", "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{newD:.3f}", str(out)])
    return round(newD, 3), round(speed, 3)


def make_music(proj, data, total):
    cfg = data.get("am_thanh", {})
    mode = cfg.get("nhac", "khong")
    if mode == "khong":
        return None
    out = proj / "03_nhac" / "nhac_nen.wav"
    out.parent.mkdir(exist_ok=True)
    if mode == "file":
        src = Path(cfg["nhac_file"])
    elif mode == "tach_goc":
        src = proj / "03_nhac" / "nhac_goc_tach.wav"
        if not src.exists():
            sys.exit("Chưa có 03_nhac/nhac_goc_tach.wav — tách nhạc trước (xem SKILL.md bước 6, cần demucs).")
    else:
        sys.exit(f"am_thanh.nhac không hợp lệ: {mode}")
    sh(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src), "-af",
        f"apad,afade=t=out:st={max(0, total - 1.2):.2f}:d=1.2", "-t", f"{total + 0.05:.3f}",
        "-ar", "48000", "-ac", "2", str(out)])
    return out


def draft_root():
    return Path(os.environ.get("CAPCUT_DRAFT_DIR") or
                Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")


def capcut_running():
    try:
        return "capcut.exe" in subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--no-compile", action="store_true")
    ap.add_argument("--skip-missing", action="store_true", help="cảnh thiếu clip mới → tạm dùng hình + tiếng gốc")
    ap.add_argument("--max-speed", type=float, default=1.3)
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    W, H, FPS = data.get("width", 1080), data.get("height", 1920), data.get("fps", 30)
    words = json.loads((proj / "01_phan_tich" / "phan_tich.json").read_text(encoding="utf-8")).get("words", [])
    kieu = {k: {**v, **data.get("phu_de_kieu", {}).get(k, {})} for k, v in KIEU_MAC_DINH.items()}
    for k, v in data.get("phu_de_kieu", {}).items():
        kieu.setdefault(k, {**KIEU_MAC_DINH["dan"], **v})
    nfc = lambda x: unicodedata.normalize("NFC", x)

    video_items, lines, table, T = [], [], [], 0.0
    for shot in data["shots"]:
        newD, speed = build_segment(proj, data, shot, words, a.max_speed, W, H, FPS)
        if newD is None:
            if not a.skip_missing:
                sys.exit(f"Thiếu 05_video/{shot['id']}.mp4 (thêm --skip-missing để tạm dùng cảnh gốc).")
            print(f"  ! {shot['id']}: thiếu clip mới → tạm dùng hình + tiếng gốc")
            newD, speed = build_segment(proj, data, {**shot, "hinh": "giu_goc", "giong": "goc"},
                                        words, a.max_speed, W, H, FPS)
        D = shot["end"] - shot["start"]
        k = newD / D
        video_items.append({"ref": f"doan_{shot['id']}", "path": f"../06_doan/{shot['id']}.mp4", "type": "video",
                            "start": round(T, 3), "duration": newD, "volume": 1.0, "width": W, "height": H})
        for ev in shot.get("phu_de", []):
            t0 = T + (ev["t0"] - shot["start"]) * k
            t1 = min(T + newD, T + (ev["t1"] - shot["start"]) * k)
            for ln in ev["dong"]:
                kn = ln.get("kieu", "dan")
                a_ = round(t0 + kieu[kn]["delay"], 3)
                if t1 - a_ < 0.2:
                    continue
                lines.append({"text": nfc(ln["text"]), "kieu": kn, "start": a_, "end": round(t1, 3),
                              "y": ln.get("y", kieu[kn]["y"])})
        table.append((shot["id"], T, T + newD, speed, shot.get("hinh"), shot.get("giong"), shot.get("dialogue", "")))
        T += newD
    total = round(T, 3)

    tracks = [{"type": "video", "name": "video", "items": video_items}]
    ops = []
    for kname, st in kieu.items():
        items = []
        for i, ln in enumerate(l for l in lines if l["kieu"] == kname):
            ref = f"pd_{kname}_{i}"
            items.append({"ref": ref, "text": ln["text"], "start": ln["start"],
                          "duration": round(ln["end"] - ln["start"], 3), "fontSize": st["size"],
                          "color": st["color"], "y": float(ln["y"])})
            ops.append({"op": "text-ranges", "target": ref, "ranges": [
                {"start": 0, "end": len(ln["text"]), "bold": st["bold"], "italic": st["italic"],
                 "font_color": st["color"], "font_size": st["size"]}]})
            ops.append({"op": "text-style", "target": ref, "style": {
                "borderWidth": 0.06, "borderColor": "#000000", "borderAlpha": 0.35,
                "shadow": True, "shadowColor": "#000000", "shadowAlpha": 0.75,
                "shadowDistance": 3, "shadowSmoothing": 0.6}})
        if items:
            tracks.append({"type": "text", "name": f"phu_de_{kname}", "items": items})
    music = make_music(proj, data, total)
    mvol = float(data.get("am_thanh", {}).get("nhac_volume", 0.18))
    if music:
        tracks.append({"type": "audio", "name": "nhac_nen", "items": [
            {"ref": "nhac_nen", "path": f"../03_nhac/{music.name}", "start": 0, "duration": total, "volume": mvol}]})
    spec = {"name": data.get("draft_name") or data["name"], "width": W, "height": H, "fps": FPS, "ratio": "9:16" if H > W else ("16:9" if W > H else "1:1"),
            "tracks": tracks, "operations": ops}
    sd = proj / "07_capcut_spec"
    sd.mkdir(exist_ok=True)
    (sd / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (sd / "timeline.json").write_text(json.dumps({
        "width": W, "height": H, "fps": FPS, "total": total, "kieu": kieu, "lines": lines,
        "shots": [{"id": t[0], "start": round(t[1], 3), "duration": round(t[2] - t[1], 3),
                   "file": f"06_doan/{t[0]}.mp4"} for t in table],
        "music": {"path": f"03_nhac/{music.name}", "volume": mvol} if music else None},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Timeline {total:.2f}s (mẫu {data['shots'][-1]['end']:.2f}s) | {len(table)} cảnh | {len(lines)} dòng chữ")
    for sid, s0, s1, sp, hinh, giong, txt in table:
        print(f"  {sid} {s0:5.2f}–{s1:5.2f}s  x{sp:<5} {hinh}/{giong}  {txt}")
    if a.no_compile:
        return

    spec_path = sd / "spec.json"
    chk = cli("compile", spec_path, "--check", check=False)
    if '"ok":true' not in chk.stdout.replace(" ", ""):
        sys.exit(f"Spec không hợp lệ: {chk.stdout}{chk.stderr}")
    d = draft_root() / spec["name"]
    if d.exists():
        n = 1
        while Path(f"{d}.bak{n}").exists():
            n += 1
        d.rename(f"{d}.bak{n}")
        print(f"Draft cũ → {d.name}.bak{n}")
    extra = ["--force-write"] if capcut_running() else []
    r = cli("compile", spec_path, *extra, check=False)
    res = json.loads(r.stdout[r.stdout.find("{"):])
    if not res.get("ok"):
        sys.exit(f"Compile lỗi: {r.stdout}{r.stderr}")
    print("Draft:", res["draft_path"])
    cli("lint", d, "--fix", "-H", check=False)
    ok = n_all = 0
    for ref, sid in res["refs"].items():
        if not ref.startswith("pd_"):
            continue
        n_all += 1
        ok += cli("text-anim", d, sid.strip(), "--intro", kieu[ref.split("_")[1]]["anim"],
                  "--intro-duration", "0.3s", "-q", check=False).returncode == 0
    print(f"Hiệu ứng chữ: {ok}/{n_all}")
    print(cli("lint", d, "-H", check=False).stdout.strip().splitlines()[-1])
    if extra:
        print("CapCut đang mở → đóng hẳn và mở lại CapCut để thấy draft mới.")


if __name__ == "__main__":
    main()
