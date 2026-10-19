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


def scene_words(scene: dict) -> list[dict]:
    """Mốc thời gian từng từ (edge-tts); không có thì chia đều lời dẫn theo thời lượng giọng."""
    words = scene.get("words") or []
    if words:
        return words
    tokens = scene.get("narration", "").split()
    if not tokens:
        return []
    step = float(scene.get("voice_duration") or len(tokens) * 0.35) / len(tokens)
    return [{"text": t, "start": i * step, "end": (i + 1) * step} for i, t in enumerate(tokens)]


_scene_words = scene_words  # tên cũ

# Hậu kỳ AI (job["subtitle_fx"]): từ khoá tô vàng + to hơn, mỗi dòng bật lên (pop-in), câu hook ở đầu video
HIGHLIGHT_ON = "{\\1c&H0000D5FF&\\2c&H0000D5FF&\\fscx118\\fscy118}"   # vàng cam (BGR), luôn nổi kể cả trước khi đọc tới
HIGHLIGHT_OFF = "{\\1c&H004DF0D4&\\2c&H00FFFFFF&\\fscx100\\fscy100}"  # trở lại màu Karaoke
POP_IN = "{\\fad(60,0)\\fscx82\\fscy82\\t(0,140,\\fscx100\\fscy100)}"
HOOK_START, HOOK_END = 0.15, 3.2


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


def _srt_ts(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(cues: list[dict]) -> str:
    """[{start, end, text}] (giây) → nội dung file .srt."""
    blocks = [f"{i}\n{_srt_ts(c['start'])} --> {_srt_ts(max(c['end'], c['start'] + 0.3))}\n{' '.join(c['text'].split())}"
              for i, c in enumerate([c for c in cues if (c.get("text") or "").strip()], 1)]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def build_srt(job: dict) -> str:
    """Phụ đề .srt của video đã ghép (cùng cách chia dòng + mốc với phụ đề karaoke) — rỗng nếu không có lời."""
    cues, offset = [], 0.0
    for scene in job["scenes"]:
        base = offset + float(job.get("voice_lead", VOICE_LEAD))
        lines = _lines(scene_words(scene))
        for li, line in enumerate(lines):
            end = base + line[-1]["end"] + 0.15
            if li + 1 < len(lines):
                end = min(end, base + lines[li + 1][0]["start"])
            cues.append({"start": base + line[0]["start"], "end": end, "text": " ".join(w["text"] for w in line)})
        offset += scene["duration"]
    return srt_text(cues)


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
        # hook: chữ đen trên khung vàng, giữa phía trên
        f"Style: Hook,Arial,{round(font_size * 1.05)},&H00101010,&H00101010,&H0000D5FF,&H0000D5FF,-1,0,0,0,100,100,0,0,3,"
        f"{max(6, font_size // 4)},0,8,{margin_h},{margin_h},{round(height * 0.11)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fx = bool(job.get("subtitle_fx"))
    if fx and job.get("subtitle_hook"):
        out.append(f"Dialogue: 1,{_ts(HOOK_START)},{_ts(HOOK_END)},Hook,,0,0,0,,"
                   f"{{\\fad(150,300)\\fscx70\\fscy70\\t(0,180,\\fscx100\\fscy100)}}{_escape(job['subtitle_hook'])}")
    offset = 0.0
    for scene in job["scenes"]:
        base = offset + float(job.get("voice_lead", VOICE_LEAD))
        marks = set(scene.get("highlight") or []) if fx else set()
        lines = _lines([{**w, "i": i} for i, w in enumerate(scene_words(scene))])
        for li, line in enumerate(lines):
            start = base + line[0]["start"]
            end = base + line[-1]["end"] + 0.15
            if li + 1 < len(lines):
                end = min(end, base + lines[li + 1][0]["start"])
            parts = []
            for wi, word in enumerate(line):
                nxt = line[wi + 1]["start"] if wi + 1 < len(line) else word["end"]
                text = _escape(word["text"])
                if word["i"] in marks:
                    text = HIGHLIGHT_ON + text + HIGHLIGHT_OFF
                parts.append(f"{{\\k{max(1, round((nxt - word['start']) * 100))}}}{text}")
            out.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Karaoke,,0,0,0,,{POP_IN if fx else ''}{' '.join(parts)}")
        offset += scene["duration"]
    return "\n".join(out) + "\n"
