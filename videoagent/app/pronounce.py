"""🗣 Từ điển phát âm: tên riêng / thương hiệu giọng đọc tiếng Việt hay đọc sai (VD "KINGER" bị đánh vần từng chữ cái hoặc
ghép âm tiếng Việt). Cài đặt → Video & âm thanh → Từ điển phát âm, mỗi dòng "viết = đọc" (VD "KINGER = Kinh gơ").

Chỉ áp cho PHẦN ĐỌC (VieNeu, Edge TTS, lời thoại gửi model video) — phụ đề / chữ trên hình giữ nguyên chữ gốc:
Edge TTS trả mốc từng từ theo chữ đã đổi → restore_words gộp lại thành chữ gốc."""
from __future__ import annotations

import re

DEFAULT = "KINGER = Kinh gơ"
_SPLIT = re.compile(r"\s*(?:=>|=|→)\s*")
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def entries(raw: str | None = None) -> list[tuple[str, str]]:
    """Dòng "viết = đọc" → [(viết, đọc)], cụm dài trước (để "KINGER ĐẠI PHÁT" thắng "KINGER")."""
    if raw is None:
        from .config import settings

        raw = settings.get("pronounce")
        raw = DEFAULT if raw is None else raw
    out = []
    for line in str(raw or "").splitlines():
        parts = _SPLIT.split(line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out.append((" ".join(parts[0].split()), " ".join(parts[1].split())))
    return sorted(out, key=lambda e: -len(e[0]))


def _pattern(word: str) -> re.Pattern:
    # nguyên từ, không phân biệt hoa thường (KINGER / Kinger / kinger), không ăn vào giữa từ khác
    return re.compile(r"(?<![\w])" + r"\s+".join(map(re.escape, word.split())) + r"(?![\w])", re.IGNORECASE)


def apply(text: str, raw: str | None = None) -> str:
    """Chữ đưa vào giọng đọc: đổi tên riêng theo từ điển."""
    text = str(text or "")
    for write, say in entries(raw):
        text = _pattern(write).sub(say, text)
    return text


def unsay(text: str, raw: str | None = None) -> str:
    """Chữ NGHE lại từ âm thanh (phân tích lời thoại / bóc lời) → đổi cách đọc về đúng chữ viết ("Kinh gơ" → "KINGER")."""
    text = str(text or "")
    for write, say in sorted(entries(raw), key=lambda e: -len(e[1])):
        text = _pattern(say).sub(write, text)
    return text


def _norm(token: str) -> str:
    return _EDGE.sub("", str(token or "")).lower()


def restore_words(words: list[dict], original: str, raw: str | None = None) -> list[dict]:
    """Mốc từng từ (Edge TTS) của chữ đã đổi → gộp cụm phiên âm về đúng chữ gốc trong câu gốc (phụ đề không hiện "Kinh gơ")."""
    found = []  # (vị trí, các từ phiên âm, chữ gốc như trong câu) theo thứ tự xuất hiện
    for write, say in entries(raw):
        for m in _pattern(write).finditer(str(original or "")):
            found.append((m.start(), [_norm(t) for t in say.split()], m.group(0)))
    if not found or not words:
        return words
    pairs = [(toks, orig) for _, toks, orig in sorted(found)]
    out, i = [], 0
    while i < len(words):
        toks, orig = pairs[0] if pairs else ([], "")
        if not toks or [_norm(w.get("text")) for w in words[i:i + len(toks)]] != toks:
            out.append(words[i])
            i += 1
            continue
        last = words[i + len(toks) - 1]
        out.append({**words[i], "text": orig, "end": last.get("end", words[i].get("end"))})
        pairs.pop(0)
        i += len(toks)
    return out
