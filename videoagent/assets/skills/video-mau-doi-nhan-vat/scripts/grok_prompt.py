"""In danh sách clip cần tạo bằng Grok Imagine (ảnh → video có tiếng) kèm prompt, ảnh nguồn và tên file tải về.

python -P grok_prompt.py --project D:/CapCut/<TenDuAn> [--shot s01]

Hai loại clip:
  1. Clip hình  (hinh = "tao_moi")       : ảnh 04_anh/<id>.png → file <id>.mp4
     - giong = "clip": nhân vật nói lời thoại trong hình (khớp khẩu hình)
     - giong khác: clip câm, chỉ chuyển động (hanh_dong)
  2. Clip giọng (giong = "giong_rieng")  : ảnh 04_anh/<giong_anh>.png (cảnh nhân vật lộ mặt) → file <id>_giong.mp4
     - chỉ lấy tiếng: nhân vật mới đọc lời của cảnh <id>
Thời lượng gợi ý: 6s nếu cảnh <= 5,5s, ngược lại 10s. Dùng shot["grok_prompt"] / shot["grok_prompt_giong"] nếu đã viết tay.
"""
import argparse, json
from pathlib import Path


def say(data, text):
    giong = data.get("nhan_vat", {}).get("giong", "cheerful young Southern Vietnamese female voice")
    return (f"She speaks Vietnamese in a {giong}, natural lip sync, lively and fluent, no pauses, "
            f"she says: \"{text}\"")


def prompt_hinh(data, s):
    if s.get("grok_prompt"):
        return s["grok_prompt"]
    parts = [s["hanh_dong"].rstrip(".") + "."] if s.get("hanh_dong") else []
    parts.append(s.get("camera") or "Static camera, the framing stays exactly like the first frame.")
    if s.get("giong") == "clip" and s.get("dialogue"):
        parts.append(say(data, s["dialogue"]))
    else:
        parts.append("Nobody speaks, no voice.")
    parts.append("No on-screen text, no subtitles, no music.")
    return " ".join(parts)


def prompt_giong(data, s):
    if s.get("grok_prompt_giong"):
        return s["grok_prompt_giong"]
    return ("She looks at the camera and talks warmly with small natural hand gestures. Static camera. "
            + say(data, s["dialogue"]) + " No on-screen text, no music.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--shot")
    a = ap.parse_args()
    data = json.loads((Path(a.project) / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    for s in data["shots"]:
        if a.shot and s["id"] != a.shot:
            continue
        dur = s["end"] - s["start"]
        sec = "6s" if dur <= 5.5 else "10s"
        if s.get("hinh") == "tao_moi":
            print(f"=== {s['id']}.mp4  [clip hình, {dur:.1f}s → {sec}, 720p]  ảnh: 04_anh/{s['id']}.png")
            print(prompt_hinh(data, s) + "\n")
        if s.get("giong") == "giong_rieng":
            src = s.get("giong_anh") or next((x["id"] for x in data["shots"] if x.get("giong") == "clip"), s["id"])
            print(f"=== {s['id']}_giong.mp4  [clip giọng, {sec}, 720p]  ảnh: 04_anh/{src}.png")
            print(prompt_giong(data, s) + "\n")


if __name__ == "__main__":
    main()
