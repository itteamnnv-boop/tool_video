"""Phụ đề karaoke dạng ASS (\\k) từ mốc thời gian từng từ của edge-tts."""
import re

from . import VOICE_LEAD

MAX_WORDS_PER_LINE = 5
_BREAK_AFTER = re.compile(r"[.,!?;:…]$")


def _ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _scene_words(scene: dict) -> list[dict]:
    words = scene.get("words") or []
    if words:
        return words
    tokens = scene.get("narration", "").split()
    if not tokens:
        return []
    step = float(scene.get("voice_duration") or len(tokens) * 0.35) / len(tokens)
    return [{"text": t, "start": i * step, "end": (i + 1) * step} for i, t in enumerate(tokens)]


def _lines(words: list[dict]) -> list[list[dict]]:
    lines, current = [], []
    for i, word in enumerate(words):
        if current and word["start"] - current[-1]["end"] > 0.6:
            lines.append(current)
            current = []
        current.append(word)
        if len(current) >= MAX_WORDS_PER_LINE or _BREAK_AFTER.search(word["text"]) or i == len(words) - 1:
            lines.append(current)
            current = []
    return lines


def build_ass(job: dict, subtitle_margin: float = 0.07) -> str:
    width, height = job["width"], job["height"]
    font_size = round(min(width, height) * 0.06)
    outline = max(2, font_size // 14)
    margin_h, margin_v = width // 12, round(height * subtitle_margin)
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Karaoke,Arial,{font_size},&H004DF0D4,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{outline},1,2,{margin_h},{margin_h},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    offset = 0.0
    for scene in job["scenes"]:
        base = offset + float(job.get("voice_lead", VOICE_LEAD))
        lines = _lines(_scene_words(scene))
        for li, line in enumerate(lines):
            start = base + line[0]["start"]
            end = base + line[-1]["end"] + 0.15
            if li + 1 < len(lines):
                end = min(end, base + lines[li + 1][0]["start"])
            parts = []
            for wi, word in enumerate(line):
                nxt = line[wi + 1]["start"] if wi + 1 < len(line) else word["end"]
                parts.append(f"{{\\k{max(1, round((nxt - word['start']) * 100))}}}{_escape(word['text'])}")
            out.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Karaoke,,0,0,0,,{' '.join(parts)}")
        offset += scene["duration"]
    return "\n".join(out) + "\n"
