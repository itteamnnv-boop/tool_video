"""In prompt Grok Imagine cho từng clip (để gõ vào ô prompt), ghép từ grok_action + dialogue trong du_an.json.

python -P grok_prompts.py --project D:/CapCut/TenDuAn [--clip v1]
"""
import argparse, json
from pathlib import Path

TPL = ("Authentic vertical smartphone livestream footage, static phone camera with slight handheld micro-movement. "
       "Animate the attached image exactly as it is: keep the woman's face, face shape, eyes, lips, skin tone, hair and "
       "outfit identical for the whole clip, same background, same product with unchanged label. Bright, clean, even lighting. "
       "The Vietnamese woman is a lively, energetic online sales host. {action} Natural, moderate facial expressions. "
       "She speaks very fast, crisp and decisive in Vietnamese with a {voice}: short punchy delivery, no drawn-out "
       "vowels, no pauses between phrases, natural lip sync, she says: \"{dialogue}\" "
       "No background music, no subtitles, no text.")


def build(data, c):
    return TPL.format(action=c.get("grok_action", "").strip(), voice=data.get("voice_style", "cheerful Southern Vietnamese accent"),
                      dialogue=c["dialogue"].strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--clip")
    a = ap.parse_args()
    data = json.loads((Path(a.project) / "02_kich_ban" / "du_an.json").read_text(encoding="utf-8"))
    for c in data["clips"]:
        if a.clip and c["id"] != a.clip:
            continue
        words = len(c["dialogue"].split())
        warn = "  (!) lời thoại dài, Grok 10s có thể nói vội/cắt — nên <= 30 từ" if words > 32 else ""
        print(f"=== {c['id']} ({words} từ){warn}\n{build(data, c)}\n")


if __name__ == "__main__":
    main()
