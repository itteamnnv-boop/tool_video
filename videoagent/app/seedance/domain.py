"""Pure input parsing, configuration and prompt formatting."""
import csv
import io
import json
import re

PRESETS = {
    "cinematic": ("🎬 Hollywood 4K", "cinematic 4k 60fps, dynamic camera angle, hyperdetailed movie scene, blockbuster lighting"),
    "portrait": ("✨ Chân Dung 8K", "ultra photorealistic 8k portrait, natural skin textures, 85mm lens, cinematic studio lighting"),
    "action": ("🏎️ Hành Động", "high octane action scene, fast motion, intense camera angle, dramatic speed ramp, 4k"),
    "anime": ("🌸 Anime 60FPS", "makoto shinkai anime style, vibrant beautiful colors, 4k 60fps, emotional cinematic lighting"),
    "cyberpunk": ("🌌 Cyberpunk", "futuristic cyberpunk city, glowing neon reflections, rain puddles, volumetric mist, 8k"),
    "fantasy": ("🔮 Fantasy 3D", "mystical fantasy realm, magical glowing particles, ethereal atmosphere, unreal engine 5"),
}
DEFAULT_CONFIG = {
    "provider": "dola", "mode": "text", "prefix": "tạo video: ", "model": "2.5",
    "aspectRatio": "16:9", "duration": "10s", "directCreate": True,
    "preset": "", "autoDownload": True, "zipMode": False, "showBrowser": True,
    "profileIds": ["default"], "tabsPerProfile": 1, "delaySeconds": 30, "timeoutSeconds": 900,
    "preferUnwatermarked": True, "generationRoute": "auto",
}


class StudioError(RuntimeError):
    def __init__(self, code, message, provider_message=""):
        super().__init__(message)
        self.code = code
        self.provider_message = provider_message


def parse_prompts(text, filename=""):
    text = str(text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > 2_000_000:
        raise ValueError("Kịch bản vượt quá 2 MB")
    if not text:
        return []
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if ext == "json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("scenes", data.get("prompts"))
        if not isinstance(data, list):
            raise ValueError("JSON cần là mảng hoặc {scenes: [...]} / {prompts: [...]}")
        rows = data
    elif ext == "csv":
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            return []
        headers = [c.strip().lower() for c in reader[0]]
        key = next((k for k in ("text", "prompt", "content") if k in headers), None)
        if key:
            index = headers.index(key)
            title_index = headers.index("title") if "title" in headers else None
            rows = [{"text": r[index], "title": r[title_index] if title_index is not None and len(r) > title_index else ""}
                    for r in reader[1:] if len(r) > index]
        else:
            if any(len(r) > 1 for r in reader):
                raise ValueError("CSV nhiều cột cần tiêu đề text hoặc prompt; có thể thêm title")
            rows = [r[0] for r in reader if r]
    else:
        rows = re.split(r"\n[ \t]*\n+", text) if re.search(r"\n[ \t]*\n", text) else text.split("\n")
    result = []
    for row in rows:
        if isinstance(row, str):
            title, value = "", row
        elif isinstance(row, dict):
            title, value = row.get("title", ""), row.get("text", row.get("prompt", ""))
        else:
            raise ValueError("Mỗi cảnh phải là chuỗi hoặc đối tượng {title, text}")
        if not isinstance(value, str):
            raise ValueError("Nội dung cảnh phải là văn bản")
        if value.strip():
            result.append({"title": str(title or value.strip().splitlines()[0])[:100], "text": value.strip()})
    if len(result) > 1000:
        raise ValueError("Tối đa 1.000 cảnh mỗi lần nhập")
    return result


def normalize_config(values):
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in (values or {}).items() if k in DEFAULT_CONFIG}}
    choices = {"provider": ("dola", "doubao"), "mode": ("text", "image"), "model": ("2.5", "2.0"),
               "generationRoute": ("auto", "chat", "video"),
               "aspectRatio": ("16:9", "9:16", "1:1", "4:3", "21:9", "none"), "duration": ("5s", "10s", "15s")}
    for key, allowed in choices.items():
        if cfg[key] not in allowed:
            raise ValueError(f"Cấu hình {key} không được hỗ trợ")
    for key, low, high in (("tabsPerProfile", 1, 4), ("delaySeconds", 0, 300), ("timeoutSeconds", 60, 3600)):
        cfg[key] = max(low, min(high, int(cfg[key])))
    for key in ("directCreate", "autoDownload", "zipMode", "showBrowser", "preferUnwatermarked"):
        cfg[key] = bool(cfg[key])
    cfg["prefix"] = str(cfg["prefix"])[:200]
    if cfg["preset"] not in PRESETS:
        cfg["preset"] = ""
    if not isinstance(cfg["profileIds"], list) or not cfg["profileIds"]:
        raise ValueError("Chọn ít nhất một profile trình duyệt")
    cfg["profileIds"] = list(dict.fromkeys(str(p) for p in cfg["profileIds"]))[:8]
    if len(cfg["profileIds"]) * cfg["tabsPerProfile"] > 12:
        raise ValueError("Tối đa 12 tab chạy cùng lúc")
    return cfg


def format_prompt(text, cfg, *, video_mode=False):
    value = text.strip()
    if video_mode:
        value = re.sub(r"^(?:tạo\s*video|create\s*videos?)\s*:\s*", "", value, flags=re.I)
        if cfg["preset"] and PRESETS[cfg["preset"]][1] not in value:
            value += ", " + PRESETS[cfg["preset"]][1]
        return value
    prefix = cfg["prefix"].strip()
    if prefix and not value.casefold().startswith(prefix.casefold()):
        value = prefix + " " + value
    ratio = cfg["aspectRatio"]
    if ratio != "none":
        pattern = r"(?:tỉ lệ|tỷ lệ|ratio|aspect ratio)\s*:?\s*\d+:\d+"
        value = re.sub(pattern, f"tỉ lệ {ratio}", value, flags=re.I) if re.search(pattern, value, re.I) else value + f", tỉ lệ {ratio}"
    value = re.sub(r"(?:thời lượng|duration)\s*:?\s*\d+\s*(?:s|giây|seconds)?", "", value, flags=re.I)
    value = re.sub(r"(?:Seedance|model|mô hình)\s*2\.[05]", "", value, flags=re.I)
    value += f", thời lượng {cfg['duration']}, Seedance {cfg['model']}"
    if cfg["preset"]:
        value += ", " + PRESETS[cfg["preset"]][1]
    if cfg["directCreate"]:
        value += ", tạo video luôn không hỏi lại, gửi dưới dạng human artifact"
    return value


def distribute(items, workers, group_size=2):
    queues = [[] for _ in range(workers)]
    for i in range(0, len(items), group_size):
        queues[(i // group_size) % workers].extend(items[i:i + group_size])
    return queues
