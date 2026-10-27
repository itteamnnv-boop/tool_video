"""Tiến trình lồng tiếng VieNeu-TTS — chạy bằng Python của môi trường riêng (DATA_DIR/tools/vieneu/venv), do app gọi.

  python vieneu_worker.py job.json   → đọc {"text", "voice", "ref_audio", "out"} → ghi file WAV
  python vieneu_worker.py --list     → in danh sách giọng có sẵn

Mỗi dòng in ra: "STAGE <chữ>" (tiến độ), "VOICES <json>", "DONE <đường dẫn>" hoặc "ERROR <chữ>".
"""
import json
import sys


def say(kind: str, text: str = "") -> None:
    print(f"{kind} {text}".rstrip(), flush=True)


def voices(tts) -> list:
    try:
        return [[str(label), str(vid)] for label, vid in tts.list_preset_voices()]
    except Exception:  # noqa: BLE001 — bản VieNeu khác API: bỏ qua danh sách giọng
        return []


def main() -> int:
    if len(sys.argv) < 2:
        say("ERROR", "thiếu tham số")
        return 2
    say("STAGE", "Đang nạp model VieNeu (chỉ lần đầu cần tải model về máy)…")
    from vieneu import Vieneu

    tts = Vieneu()
    if sys.argv[1] == "--list":
        say("VOICES", json.dumps(voices(tts), ensure_ascii=False))
        return 0
    with open(sys.argv[1], encoding="utf-8") as fh:
        job = json.load(fh)
    kwargs = {}
    if job.get("ref_audio"):
        kwargs.update(ref_audio=job["ref_audio"], denoise=True)
    elif job.get("voice"):
        names = voices(tts)
        want = str(job["voice"]).strip().lower()
        hit = next((vid for label, vid in names if want in (label.lower(), vid.lower())), None)
        if names and hit is None:
            say("ERROR", "Không có giọng “%s”. Giọng có sẵn: %s" % (job["voice"], ", ".join(label for label, _ in names)))
            return 3
        kwargs["voice"] = hit or job["voice"]
    # nhiều đoạn (lời đọc theo cảnh) đọc trong 1 lần nạp model; không có "items" = 1 đoạn {"text", "out"}
    items = job.get("items") or [{"text": job["text"], "out": job["out"]}]
    for i, item in enumerate(items, 1):
        say("STAGE", f"Đang đọc đoạn {i}/{len(items)}…" if len(items) > 1 else "Đang đọc lời thoại…")
        audio = tts.infer(item["text"], **kwargs)
        tts.save(audio, item["out"])
    say("DONE", items[-1]["out"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — báo lỗi gọn cho app
        say("ERROR", f"{type(exc).__name__}: {exc}")
        sys.exit(1)
