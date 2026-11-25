"""Tạo clip nói (người mẫu tự nói tiếng Việt, khớp khẩu hình) bằng tác tử Muse của Meta (muse.ai) qua muse-cli.

Mỗi clip: đẩy ảnh cảnh 04_anh/codex/<id>.png lên máy ảo Muse (fs.write) → gửi prompt image-to-video vào
một side chat riêng của dự án → chờ Muse trả video → tải về 05_grok_video/<id>.mp4 (giữ tên thư mục để
build_draft.py dùng chung) → kiểm tra thời lượng, kích thước, có tiếng.

python -P muse_video.py --project D:/CapCut/TenDuAn [--clip v1 --clip v2] [--print] [--force] [--wait 900]

Cần: `pip install muse-cli` và đã đăng nhập (`python -m muse_cli status` chạy được).
"""
import argparse, base64, io, json, subprocess, sys, time
from pathlib import Path

try:
    from muse_cli import cli as mc
except ImportError:
    sys.exit("Chưa cài muse-cli: pip install --user muse-cli (rồi đăng nhập theo SKILL.md của muse-cli)")

TPL_EN = ("Authentic vertical smartphone livestream footage, slight handheld micro-movement, natural light. "
          "The Vietnamese woman is a lively, energetic online sales host. {action} She speaks very fast, crisp and decisive (short punchy delivery, no drawn-out vowels, no pauses) in "
          "Vietnamese with a {voice}, natural lip sync, expressive hand gestures, she says: \"{dialogue}\" "
          "Keep her face, outfit and the product label unchanged and legible. No background music, no subtitles, no text.")

TPL = """Tạo đúng MỘT video từ ảnh (image-to-video), dùng ảnh {img} làm khung hình đầu tiên.
Yêu cầu bắt buộc:
- Dài {secs} giây, khung DỌC 9:16 (vd 720x1280), một cảnh liền, không ghép, không chuyển cảnh.
- Giữ nguyên khuôn mặt, trang phục, bối cảnh và nhãn sản phẩm như trong ảnh.
- Người phụ nữ TỰ NÓI tiếng Việt, khớp khẩu hình, đọc ĐÚNG NGUYÊN VĂN lời thoại bên dưới, không thêm bớt chữ.
- Không nhạc nền, không phụ đề, không chèn chữ hay logo.
- Đặt tên file: {name}. Không hỏi lại, làm ngay rồi gửi video.

Lời thoại: "{dialogue}"

Prompt video (tiếng Anh):
{en}"""


REFUSALS = ("không khả dụng", "not available", "unavailable", "không hỗ trợ", "khu vực", "region",
            "không thể tạo", "giới hạn", "hết lượt", "rate limit", "quota", "bị chặn", "403",
            "chưa làm được", "không làm được")


def load(proj):
    return json.loads((proj / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))


def save(proj, data):
    (proj / "02_kich_ban" / "du_an.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_prompt(data, c, img, secs):
    en = TPL_EN.format(action=c.get("grok_action", "").strip(),
                       voice=data.get("voice_style", "cheerful Southern Vietnamese accent"),
                       dialogue=c["dialogue"].strip())
    return TPL.format(img=img, secs=secs, name=f"{data['name']}-{c['id']}", dialogue=c["dialogue"].strip(), en=en)


def upload(gw, local, remote):
    from PIL import Image
    im = Image.open(local).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    raw = buf.getvalue()
    # Mỗi khung Noise của gateway <= 64 KB → ghi từng mảnh 32 KB (mảnh đầu ghi đè, các mảnh sau nối thêm).
    step = 32 * 1024
    for i in range(0, len(raw), step):
        gw.call_json("fs.write", body={"path": remote, "data_base64": base64.b64encode(raw[i:i + step]).decode(),
                                       "overwrite": True, "append": i > 0, "create_parent": True})
    got = gw.call_json("fs.stat", body={"path": remote})
    size = (got.get("result") or got).get("size")
    if size is not None and size != len(raw):
        raise RuntimeError(f"tải ảnh lên Muse lỗi: {size} != {len(raw)} byte")
    return "/" + remote.lstrip("/")


def events(gw, thread, limit=30):
    return sorted(gw.call_json("chat.history", body={"limit": limit, "session_id": thread}).get("chat_events", []),
                  key=lambda e: e.get("seq") or 0)


def wait_video(gw, thread, baseline, timeout):
    """Chờ tới khi có file video mới (seq > baseline) rồi yên 15s. Trả (resources, lời nhắn cuối)."""
    deadline, found, last_seq, quiet, last_text = time.time() + timeout, [], baseline, time.time(), ""
    while time.time() < deadline:
        try:
            evs = events(gw, thread)
        except (mc.GatewayError, TimeoutError):
            time.sleep(5)
            continue
        for ev in evs:
            s = ev.get("seq") or 0
            if s <= baseline:
                continue
            if s > last_seq:
                last_seq, quiet = s, time.time()
            p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            if ev.get("event_name") == "message.assistant" and p.get("status"):
                t = p.get("display_text") or p.get("content") or ""
                if t and t not in last_text:
                    last_text = (last_text + " | " + t).strip(" |")  # gom mọi lời Muse nhắn (lời từ chối có thể nằm ở tin trước)
            for r in mc.event_resources(ev):
                is_vid = r.get("kind") == "video" or str(r.get("mime", "")).startswith("video") or r["path"].endswith(".mp4")
                if is_vid and r["path"] not in [x["path"] for x in found]:
                    found.append(r)
        if found and time.time() - quiet >= 15:
            return found, last_text
        # Muse từ chối hẳn (vd "video generation không khả dụng cho tài khoản này ở khu vực hiện tại") → dừng sớm.
        low = last_text.lower()
        if not found and time.time() - quiet >= 30 and any(k in low for k in REFUSALS):
            return found, last_text
        time.sleep(5)
    return found, last_text


def probe(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                              "-of", "json", str(path)], capture_output=True, text=True).stdout
        d = json.loads(out)
        v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
        has_a = any(s["codec_type"] == "audio" for s in d["streams"])
        return f"{v.get('width')}x{v.get('height')}, {float(d['format']['duration']):.1f}s, " + ("có tiếng" if has_a else "KHÔNG CÓ TIẾNG (!)")
    except Exception as e:  # noqa: BLE001
        return f"không đọc được ({e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--clip", action="append", help="id clip (lặp lại được); bỏ trống = mọi clip chưa có video")
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--wait", type=int, default=900, help="giây chờ mỗi clip")
    ap.add_argument("--force", action="store_true", help="tạo lại dù đã có 05_grok_video/<id>.mp4")
    ap.add_argument("--print", action="store_true", help="chỉ in prompt, không gửi")
    a = ap.parse_args()

    proj = Path(a.project)
    data = load(proj)
    out_dir = proj / "05_grok_video"
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = [c for c in data["clips"] if (not a.clip or c["id"] in a.clip)
             and (a.force or a.clip or not (out_dir / f"{c['id']}.mp4").exists())]
    if a.print:
        for c in clips:
            img = f"/workspace/tvc_uploads/{data['name']}/{c['id']}.jpg"
            print(f"=== {c['id']} ({len(c['dialogue'].split())} từ)\n{build_prompt(data, c, img, a.seconds)}\n")
        return
    if not clips:
        print("Mọi clip đã có video (dùng --force hoặc --clip để tạo lại).")
        return

    cfg = mc.load_config()
    gw = mc.connect(cfg)
    try:
        thread = data.get("muse_thread")
        if not thread:
            res = mc.start_session(gw, f"TVC {data['name']}")
            thread = res.get("session_id") or res.get("id")
            data["muse_thread"] = thread
            save(proj, data)
            print(f"Tạo side chat Muse: {thread}")
        ok = True
        for c in clips:
            cid = c["id"]
            src = proj / "04_anh" / "codex" / f"{cid}.png"
            if not src.exists():
                print(f"[{cid}] thiếu ảnh {src} — bỏ qua")
                ok = False
                continue
            img = upload(gw, src, f"workspace/tvc_uploads/{data['name']}/{cid}.jpg")
            baseline = max([e.get("seq") or 0 for e in events(gw, thread, 5)] or [0])
            prompt = build_prompt(data, c, img, a.seconds)
            gw._open("chat.stream", body={"items": [{"type": "text", "text": prompt}],
                                          "node_id": cfg["node_id"], "capabilities": {}, "session_id": thread})
            t0 = time.time()
            print(f"[{cid}] đã gửi ({len(c['dialogue'].split())} từ), chờ Muse tạo video…", flush=True)
            vids, text = wait_video(gw, thread, baseline, a.wait)
            if not vids:
                print(f"[{cid}] KHÔNG có video sau {int(time.time() - t0)}s. Muse nhắn: {text[:400]!r}")
                ok = False
                if any(k in text.lower() for k in REFUSALS):
                    print("Muse từ chối/giới hạn tạo video → dừng các clip còn lại, báo người dùng.")
                    break
                continue
            tmp = out_dir / "_muse_tmp"
            row = mc.save_resources(gw, vids[-1:], str(tmp), overwrite=True)[0]
            if "error" in row:
                print(f"[{cid}] lỗi tải: {row['error']}")
                ok = False
                continue
            dst = out_dir / f"{cid}.mp4"
            Path(row["file"]).replace(dst)
            c["muse_video"] = vids[-1]["path"]
            save(proj, data)
            print(f"[{cid}] OK {dst.name}: {probe(dst)} ({int(time.time() - t0)}s)"
                  + (f"  (Muse trả {len(vids)} video, lấy cái cuối)" if len(vids) > 1 else ""), flush=True)
        try:
            (out_dir / "_muse_tmp").rmdir()
        except OSError:
            pass
        sys.exit(0 if ok else 2)
    finally:
        gw.close()


if __name__ == "__main__":
    main()
