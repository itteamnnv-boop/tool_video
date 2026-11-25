"""Dựng draft CapCut livestream (giọng gốc) từ du_an.json + clip Grok + overlay, rồi compile, lint, thêm pop-up.

python -P build_draft.py --project D:/CapCut/TenDuAn [--no-compile]

- Cắt khoảng lặng đầu/cuối mỗi clip (capcut-cli detect-silence), nối liền (cắt thẳng), giữ âm thanh gốc.
- Phủ khung live (cả video) + ảnh bình luận theo clip.
- Phụ đề: chia theo dấu câu (không ngắt trong số 0944.20.20.15), bắt dính ranh giới vào chỗ ngắt hơi,
  chữ trắng đậm + từ khoá vàng to hơn (text-ranges), viền đen, bóng, nền tối; hiệu ứng pop-up.
- Draft cũ cùng tên được đổi thành <tên>.bakN (không xoá).
Ra: 07_capcut_spec/spec.json, 06_phu_de/phu_de.srt, draft trong thư viện CapCut.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, unicodedata
from pathlib import Path

W, H, FPS = 1080, 1920, 30
MAX_WORDS = 9
BASE_SIZE, KW_SIZE = 10, 12
WHITE, YELLOW = "#FFFFFF", "#FFE14D"
SUB_Y = -0.3
CLI = shutil.which("capcut-cli") or shutil.which("capcut-cli.cmd") or "capcut-cli"


def cli(*args, check=True):
    r = subprocess.run([CLI, *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode not in (0, 1):
        sys.exit(f"capcut-cli {args[0]} lỗi: {r.stdout}{r.stderr}")
    return r


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return -1.0


def silence(path, thr, min_sil, pad):
    return json.loads(cli("detect-silence", path, "--threshold-db", thr, "--min-silence", min_sil, "--pad", pad).stdout)


def speech_span(path, dur):
    keeps = [k for k in silence(path, -35, 0.35, 0.05)["keeps"] if k["duration"] > 0.3]
    if not keeps:
        return 0.0, dur
    return keeps[0]["start"], keeps[-1]["end"]


def pauses(path):
    return [(s["start"] + s["end"]) / 2 for s in silence(path, -30, 0.1, 0)["silences"]]


def phrases(text, keywords=()):
    """Chia câu theo dấu câu, cụm dài chia đều <= MAX_WORDS từ; không ngắt dòng giữa một từ khoá nhiều chữ."""
    kw_words = [k.lower().split() for k in keywords if len(k.split()) > 1]
    out = []
    for part in re.split(r"(?<=[,.?!])\s+", text.strip()):
        words = part.split()
        if not words:
            continue
        low = [w.lower().strip(",.?!") for w in words]
        protected = set()  # chỉ số i: không được ngắt giữa words[i-1] và words[i]
        for kw in kw_words:
            for s in range(len(low) - len(kw) + 1):
                if low[s:s + len(kw)] == kw:
                    protected.update(range(s + 1, s + len(kw)))
        n = max(1, -(-len(words) // MAX_WORDS))
        size = -(-len(words) // n)
        cuts, i = [], size
        while i < len(words):
            j = i
            while j in protected and j < len(words):
                j += 1
            if j < len(words):
                cuts.append(j)
            i = j + size
        bounds = [0, *cuts, len(words)]
        out += [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:]) if b > a]
    return out


def keyword_ranges(text, keywords):
    marks = [False] * len(text)
    for kw in sorted(keywords, key=len, reverse=True):
        for m in re.finditer(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text, flags=re.IGNORECASE):
            if not any(marks[m.start():m.end()]):
                marks[m.start():m.end()] = [True] * (m.end() - m.start())
    out, i = [], 0
    while i < len(text):
        j = i
        while j < len(text) and marks[j] == marks[i]:
            j += 1
        out.append({"start": i, "end": j, "bold": True, "font_color": YELLOW if marks[i] else WHITE,
                    "font_size": KW_SIZE if marks[i] else BASE_SIZE})
        i = j
    return out


def build_spec(proj, data):
    nfc = lambda s: unicodedata.normalize("NFC", s)
    keywords = [nfc(k) for k in data.get("keywords", [])]
    video, cmts, subs, ops, srt, table = [], [], [], [], [], []
    t = 0.0
    for c in data["clips"]:
        src = proj / "05_grok_video" / f"{c['id']}.mp4"
        if not src.exists():
            sys.exit(f"Thiếu clip {src} — chạy collect_downloads.py trước.")
        w, h, clip_dur = probe(src)
        s0, s1 = speech_span(src, clip_dur)
        src_in = round(max(0.0, s0 - 0.15), 3)
        src_out = round(min(clip_dur - 0.01, s1 + 0.25), 3)
        dur = round(src_out - src_in, 3)
        cov = round(max(W / w, H / h) / min(W / w, H / h), 3)
        ref = f"clip_{c['id']}"
        video.append({"ref": ref, "path": f"../05_grok_video/{c['id']}.mp4", "type": "video", "start": round(t, 3),
                      "duration": dur, "sourceStart": src_in, "volume": float(data.get("voice_volume", 1.0)), "width": w, "height": h})
        cmt_png = proj / "04_anh" / "overlay" / f"binh_luan_{c['id']}.png"
        if cmt_png.exists():
            cmts.append({"ref": f"cmt_{c['id']}", "path": f"../04_anh/overlay/{cmt_png.name}", "type": "photo",
                         "start": round(t, 3), "duration": dur, "width": W, "height": H})
        # phụ đề
        ph = phrases(nfc(c.get("display") or c["dialogue"]), keywords)
        total = sum(len(p) for p in ph)
        bounds, cur = [s0], s0
        for p in ph[:-1]:
            cur += (s1 - s0) * len(p) / total
            bounds.append(cur)
        bounds.append(s1)
        pz = [x for x in pauses(src) if s0 < x < s1]
        for k in range(1, len(bounds) - 1):
            near = min(pz, key=lambda x: abs(x - bounds[k]), default=None)
            if near is not None and abs(near - bounds[k]) < 0.6 and bounds[k - 1] + 0.35 < near < bounds[k + 1] - 0.35:
                bounds[k] = near
        for k, p in enumerate(ph):
            a = round(t + bounds[k] - src_in, 3)
            b = round(t + bounds[k + 1] - src_in, 3)
            sref = f"sub_{c['id']}_{k}"
            subs.append({"ref": sref, "text": p, "start": a, "duration": round(b - a, 3),
                         "fontSize": BASE_SIZE, "color": WHITE,
                         "y": float(c.get("sub_y", data.get("sub_y", SUB_Y)))})
            ops.append({"op": "text-ranges", "target": sref, "ranges": keyword_ranges(p, keywords)})
            ops.append({"op": "text-style", "target": sref,
                        "style": {"borderWidth": 0.12, "borderColor": "#000000", "borderAlpha": 1,
                                  "shadow": True, "shadowColor": "#000000", "shadowAlpha": 0.7,
                                  "shadowDistance": 4, "shadowSmoothing": 0.4,
                                  "bgColor": "#000000", "bgAlpha": 0.45, "bgStyle": 1, "bgRoundRadius": 0.4}})
            srt.append((a, b, p))
        # hiệu ứng theo clip: "fx": [{"type": ..., "at": giây trong clip gốc} hoặc {"on": "từ khoá trong phụ đề"}]
        # "on" = bắt đầu đúng lúc dòng phụ đề chứa từ khoá xuất hiện (+ "delay" giây nếu có)
        kf = {0.0: cov, dur: cov}
        fx_abs = []
        mine = [s for s in subs if s["ref"].startswith(f"sub_{c['id']}_")]
        for f in c.get("fx", []):
            if "on" in f:
                key = nfc(f["on"]).lower()
                hit = next((s for s in mine if key in s["text"].lower()), None)
                if hit is None:
                    print(f"  ! fx {f['type']}: không thấy '{f['on']}' trong phụ đề {c['id']} — bỏ qua")
                    continue
                rel = round(hit["start"] - t + f.get("delay", 0), 3)
            else:
                rel = round(f.get("at", 0.5) - src_in, 3)
            if not 0 <= rel < dur:
                continue
            fx_abs.append({**f, "t": round(t + rel, 3), "end": round(t + dur, 3)})
            if f.get("zoom", f["type"] in ("reveal", "price", "gift")):  # zoom punch 12% rồi thả dần về
                for dt, k in ((-0.05, 1.0), (0.22, 1.12), (1.1, 1.07), (1.8, 1.0)):
                    tt = round(rel + dt, 3)
                    if 0 < tt < dur:
                        kf[tt] = round(cov * k, 3)
        c["_fx_abs"] = fx_abs
        ops += [{"op": "keyframe", "target": ref, "property": "uniform_scale", "time": tt, "value": v}
                for tt, v in sorted(kf.items())]
        table.append((c["id"], t, t + dur, c.get("display") or c["dialogue"]))
        t += dur

    tracks = [{"type": "video", "name": "clip_live", "items": video}]
    if cmts:
        tracks.append({"type": "video", "name": "binh_luan", "items": cmts})
    if (proj / "04_anh" / "overlay" / "khung_live.png").exists():
        tracks.append({"type": "video", "name": "khung_live", "items": [
            {"ref": "khung_live", "path": "../04_anh/overlay/khung_live.png", "type": "photo",
             "start": 0, "duration": round(t, 3), "width": W, "height": H}]})
    tracks.append({"type": "text", "name": "phu_de", "items": subs})
    spec = {"name": data.get("draft_name") or data["name"], "width": W, "height": H, "fps": FPS, "ratio": "9:16",
            "tracks": tracks, "operations": ops}
    (proj / "07_capcut_spec").mkdir(exist_ok=True)
    (proj / "07_capcut_spec" / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    def ts(x):
        ms = round(x * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    (proj / "06_phu_de").mkdir(exist_ok=True)
    (proj / "06_phu_de" / "phu_de.srt").write_text(
        "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{x}\n" for i, (a, b, x) in enumerate(srt, 1)), encoding="utf-8")
    return spec, table, t


def draft_root():
    return Path(os.environ.get("CAPCUT_DRAFT_DIR") or
                Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")


def capcut_running():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
        return "capcut.exe" in out
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--no-compile", action="store_true")
    ap.add_argument("--remotion", action="store_true",
                    help="khung live ĐỘNG bằng Remotion (video trong suốt) thay cho 2 track ảnh tĩnh")
    ap.add_argument("--overlay-format", choices=["prores", "webm"], default="prores")
    ap.add_argument("--rerender", action="store_true", help="bắt buộc render lại khung live động Remotion")
    ap.add_argument("--music", action="store_true",
                    help="tự tạo nhạc nền gốc (tao_nhac_nen.py) và thêm track audio nhac_nen dưới giọng người dẫn")
    ap.add_argument("--ambience", action="store_true",
                    help="tự tạo tạp âm nền gốc (tao_tap_am.py: tiếng nhà máy, xe nâng…) và thêm track audio tap_am")
    ap.add_argument("--no-ambience", action="store_true")
    ap.add_argument("--no-music", action="store_true",
                    help="KHÔNG thêm nhạc nền (để người dùng tự chọn nhạc thư viện trong CapCut)")
    ap.add_argument("--skip-missing", action="store_true",
                    help="bỏ qua clip chưa có file trong 05_grok_video (vd Grok hết lượt) thay vì dừng")
    a = ap.parse_args()
    proj = Path(a.project)
    data = json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    if a.skip_missing:
        missing = [c["id"] for c in data["clips"] if not (proj / "05_grok_video" / f"{c['id']}.mp4").exists()]
        if missing:
            print(f"Bỏ qua clip chưa có: {', '.join(missing)}")
            data["clips"] = [c for c in data["clips"] if c["id"] not in missing]
    spec, table, total = build_spec(proj, data)
    mcfg = data.get("music") or {}
    if (a.music or mcfg) and not a.no_music:
        if mcfg.get("file"):
            # nhạc người dùng cung cấp: cắt/lặp đúng độ dài timeline, chuyển WAV
            src = Path(mcfg["file"])
            wav = proj / "03_nhac" / "nhac_nen.wav"
            wav.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-stream_loop", "-1", "-i", str(src),
                            "-af", "apad", "-t", f"{total + 0.1:.3f}", "-ar", "48000", "-ac", "2", str(wav)], check=True)
            print(f"Nhạc nền (file): {src.name} -> {wav}")
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tao_nhac_nen import make_music
            wav = make_music(total, proj / "03_nhac" / "nhac_nen.wav", mcfg.get("style", "upbeat"), mcfg.get("bpm"),
                             mcfg.get("key", "G"), mcfg.get("seed", 7))
        spec["tracks"].append({"type": "audio", "name": "nhac_nen", "items": [
            {"ref": "nhac_nen", "path": f"../03_nhac/{wav.name}", "start": 0, "duration": round(total, 3),
             "volume": float(mcfg.get("volume", 0.15))}]})
        spec["operations"].append({"op": "audio-fade", "target": "nhac_nen", "fadeIn": 0.3, "fadeOut": 1.5})
        (proj / "07_capcut_spec" / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    acfg = data.get("ambience") or {}
    if (a.ambience or acfg) and not a.no_ambience:
        if acfg.get("file"):
            # tạp âm người dùng cung cấp: lặp/cắt đúng độ dài timeline
            awav = proj / "03_nhac" / "tap_am.wav"
            awav.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-stream_loop", "-1", "-i", str(acfg["file"]),
                            "-af", "apad", "-t", f"{total + 0.1:.3f}", "-ar", "48000", "-ac", "2", str(awav)], check=True)
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tao_tap_am import make_ambience
            awav = make_ambience(total, proj / "03_nhac" / "tap_am.wav", acfg.get("style", "nha_may"), acfg.get("seed", 3), bool(acfg.get("vehicles", False)))
        spec["tracks"].append({"type": "audio", "name": "tap_am", "items": [
            {"ref": "tap_am", "path": f"../03_nhac/{awav.name}", "start": 0, "duration": round(total, 3),
             "volume": float(acfg.get("volume", 0.25))}]})
        spec["operations"].append({"op": "audio-fade", "target": "tap_am", "fadeIn": 0.5, "fadeOut": 1.0})
        (proj / "07_capcut_spec" / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Tạp âm: {awav} ({acfg.get('style', 'nha_may')}, volume {acfg.get('volume', 0.25)})")
    if a.remotion:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from remotion_overlay import render_overlay
        ext = ".webm" if a.overlay_format == "webm" else ".mov"
        mov = proj / "04_anh" / "overlay" / f"khung_live_dong{ext}"
        if a.rerender or not mov.exists() or probe_duration(mov) < total - 0.1 or probe_duration(mov) > total + 0.2:
            mov = render_overlay(proj, data, [(cid, s, e) for cid, s, e, _ in table], total, a.overlay_format)
        else:
            print(f"Dùng lại khung live động đã có: {mov.name} (thêm --rerender để render lại)")
        tracks = [t for t in spec["tracks"] if t["name"] not in ("binh_luan", "khung_live")]
        tracks.insert(1, {"type": "video", "name": "khung_live_dong", "items": [
            {"ref": "khung_live_dong", "path": f"../04_anh/overlay/{mov.name}", "type": "video", "start": 0,
             # không vượt độ dài thật của file (Remotion làm tròn theo khung hình)
             "duration": math.floor(min(total, probe_duration(mov)) * 1000) / 1000,
             "volume": 0, "width": W, "height": H}]})
        spec["tracks"] = tracks
        (proj / "07_capcut_spec" / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    n_subs = len(next(t for t in spec["tracks"] if t["name"] == "phu_de")["items"])
    print(f"Timeline {total:.2f}s | {len(table)} clip | {n_subs} dòng phụ đề")
    for cid, s, e, txt in table:
        print(f"  {cid}  {s:5.1f}–{e:5.1f}s  {txt}")
    if a.no_compile:
        return

    spec_path = proj / "07_capcut_spec" / "spec.json"
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
    js = r.stdout[r.stdout.find("{"):]
    res = json.loads(js)
    if not res.get("ok"):
        sys.exit(f"Compile lỗi: {r.stdout}{r.stderr}")
    print("Draft:", res["draft_path"])
    cli("lint", d, "--fix", "-H", check=False)
    sub_ids = [v.strip() for k, v in res["refs"].items() if k.startswith("sub_")]
    fails = [sid for sid in sub_ids
             if cli("text-anim", d, sid, "--intro", "pop-up", "--intro-duration", "0.25s", "-q", check=False).returncode != 0]
    print(f"Pop-up: {len(sub_ids) - len(fails)}/{len(sub_ids)}")
    print(cli("lint", d, "-H", check=False).stdout.strip().splitlines()[-1])
    if extra:
        print("CapCut đang mở → hãy đóng hẳn và mở lại CapCut để thấy draft mới.")


if __name__ == "__main__":
    main()
