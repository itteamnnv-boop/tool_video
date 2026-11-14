"""🧑‍💼 HeyGen API (v3) — video avatar / ảnh biết nói đọc lời thoại.

Khoá: Cài đặt → API key → HeyGen (settings.heygen_api_key — chỉ dùng được khi bật "Dùng model qua API key").
Tạo video tốn credit HeyGen; lấy danh sách avatar / giọng thì không tốn.

  • POST /v3/assets            (multipart "file") → data.asset_id          — ảnh người nói (chế độ Ảnh biết nói)
  • POST /v3/videos            type avatar | image → data.video_id
  • GET  /v3/videos/{id}       data.status pending | processing | completed | failed, data.video_url, failure_message
  • GET  /v3/avatars/looks     data[], has_more, next_token                — avatar (look id = avatar_id)
  • GET  /v3/models/audio/voices  type private | public, language          — giọng đọc
"""
from __future__ import annotations

import json
import time
from pathlib import Path

BASE = "https://api.heygen.com"
ASPECTS = ("9:16", "16:9", "1:1", "4:5")
RESOLUTIONS = ("720p", "1080p")
MAX_SCRIPT = 5000  # ký tự / video (giữ an toàn — dài hơn thì tách nhiều khối)
POLL_EVERY = 10  # giây
TIMEOUT = 40 * 60  # chờ tối đa 40 phút / video
CACHE_NAME = "heygen_lists.json"


class HeyGenError(RuntimeError):
    pass


def _http():
    import requests

    return requests


def _check(resp) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    if resp.status_code >= 400 or err:
        msg = (err or {}).get("message") if isinstance(err, dict) else (str(err) if err else "")
        code = (err or {}).get("code") if isinstance(err, dict) else ""
        if resp.status_code in (401, 403):
            raise HeyGenError("HeyGen từ chối khoá API — kiểm tra lại HeyGen API key trong Cài đặt → API key")
        if resp.status_code == 429:
            raise HeyGenError("HeyGen báo gửi quá nhiều yêu cầu (429) — đợi một lát rồi chạy lại")
        raise HeyGenError(f"HeyGen lỗi {resp.status_code}{f' ({code})' if code else ''}: {msg or resp.text[:200]}")
    return data if isinstance(data, dict) else {}


class HeyGen:
    def __init__(self, api_key: str, session=None) -> None:
        if not str(api_key or "").strip():
            raise HeyGenError("Chưa có HeyGen API key — bật “Dùng model qua API key” (Cài đặt → Model AI) rồi nhập khoá "
                              "ở Cài đặt → API key")
        self.key = str(api_key).strip()
        self.http = session or _http()

    def _h(self, json_body: bool = True) -> dict:
        return {"x-api-key": self.key, "accept": "application/json",
                **({"content-type": "application/json"} if json_body else {})}

    def get(self, path: str, params: dict | None = None) -> dict:
        return _check(self.http.get(BASE + path, headers=self._h(False), params=params or {}, timeout=60))

    def post(self, path: str, body: dict) -> dict:
        return _check(self.http.post(BASE + path, headers=self._h(), data=json.dumps(body), timeout=120))

    # ------------------------------------------------------------------ danh sách
    def _pages(self, path: str, params: dict, cap: int) -> list:
        out, token = [], None
        while len(out) < cap:
            data = self.get(path, {**params, **({"token": token} if token else {})})
            out += [x for x in data.get("data") or [] if isinstance(x, dict)]
            token = data.get("next_token")
            if not data.get("has_more") or not token:
                break
        return out[:cap]

    def avatars(self, cap: int = 300) -> list[dict]:
        rows = []
        for own in ("private", "public"):
            rows += [{"id": a.get("id"), "name": a.get("name") or a.get("id"), "type": a.get("avatar_type") or "",
                      "own": own == "private", "voice": a.get("default_voice_id") or "",
                      "preview": a.get("preview_image_url") or "", "gender": a.get("gender") or ""}
                     for a in self._pages("/v3/avatars/looks", {"ownership": own, "limit": 50}, cap)
                     if a.get("id") and str(a.get("status") or "completed").lower() not in ("failed", "processing")]
        return rows

    def voices(self, cap: int = 300) -> list[dict]:
        rows = [{"id": v.get("voice_id"), "name": v.get("name") or v.get("voice_id"), "lang": v.get("language") or "",
                 "gender": v.get("gender") or "", "own": True}
                for v in self._pages("/v3/models/audio/voices", {"type": "private", "limit": 100}, cap)
                if v.get("voice_id") and str(v.get("status") or "ACTIVE").upper() == "ACTIVE"]
        for lang in ("vi", ""):  # giọng tiếng Việt trước, rồi giọng đa ngôn ngữ / còn lại
            params = {"type": "public", "limit": 50, **({"language": lang} if lang else {})}
            try:
                got = self._pages("/v3/models/audio/voices", params, cap)
            except HeyGenError:
                if lang:
                    continue  # mã ngôn ngữ không được nhận → lấy danh sách chung
                raise
            seen = {r["id"] for r in rows}
            rows += [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"], "lang": v.get("language") or "",
                      "gender": v.get("gender") or "", "own": False}
                     for v in got if v.get("voice_id") and v["voice_id"] not in seen]
        return rows

    # ------------------------------------------------------------------ tạo video
    def upload(self, path: Path) -> str:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        with open(path, "rb") as fh:
            resp = self.http.post(BASE + "/v3/assets", headers=self._h(False), files={"file": (path.name, fh, mime)},
                                  timeout=180)
        asset = (_check(resp).get("data") or {}).get("asset_id")
        if not asset:
            raise HeyGenError("HeyGen không trả mã ảnh sau khi tải lên")
        return asset

    def create(self, body: dict) -> str:
        vid = (self.post("/v3/videos", body).get("data") or {}).get("video_id")
        if not vid:
            raise HeyGenError("HeyGen không trả mã video")
        return vid

    def status(self, video_id: str) -> dict:
        return self.get(f"/v3/videos/{video_id}").get("data") or {}

    def wait(self, video_id: str, *, check_cancel=lambda: None, on_progress=lambda f: None, log=lambda *a, **k: None,
             sleep=time.sleep, timeout: float = TIMEOUT) -> str:
        t0, last = time.time(), ""
        while True:
            check_cancel()
            data = self.status(video_id)
            st = str(data.get("status") or "").lower()
            if st != last:
                log(f"HeyGen: {st or '…'}")
                last = st
            if st == "completed":
                if not data.get("video_url"):
                    raise HeyGenError("HeyGen báo xong nhưng không có link video")
                return data["video_url"]
            if st == "failed":
                raise HeyGenError(f"HeyGen tạo video lỗi: {data.get('failure_message') or data.get('failure_code') or 'không rõ'}")
            spent = time.time() - t0
            if spent > timeout:
                raise HeyGenError(f"HeyGen chưa xong sau {int(timeout // 60)} phút — video {video_id} vẫn có thể xong "
                                  "trên heygen.com")
            on_progress(min(0.9, 0.1 + spent / 600))  # ước lượng: video thường xong trong ~10 phút
            for _ in range(POLL_EVERY):
                check_cancel()
                sleep(1)

    def download(self, url: str, out: Path) -> Path:
        with self.http.get(url, stream=True, timeout=300) as resp:
            if resp.status_code >= 400:
                raise HeyGenError(f"Tải video HeyGen lỗi {resp.status_code}")
            with open(out, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    if chunk:
                        fh.write(chunk)
        if not out.is_file() or out.stat().st_size < 1024:
            raise HeyGenError("File video HeyGen tải về bị rỗng")
        return out


def body(*, mode: str, script: str, voice_id: str, avatar_id: str = "", asset_id: str = "", aspect: str = "9:16",
         resolution: str = "720p", speed: float = 1.0, title: str = "", expressiveness: str = "",
         motion_prompt: str = "") -> dict:
    """Thân yêu cầu POST /v3/videos — mode "avatar" (avatar HeyGen) hoặc "photo" (ảnh người nói)."""
    out: dict = {"type": "image", "image": {"type": "asset_id", "asset_id": asset_id}} if mode == "photo" \
        else {"type": "avatar", "avatar_id": avatar_id}
    out["script"] = script
    if voice_id:
        out["voice_id"] = voice_id
    out["aspect_ratio"] = aspect if aspect in ASPECTS else "9:16"
    out["resolution"] = resolution if resolution in RESOLUTIONS else "720p"
    if speed and abs(float(speed) - 1.0) > 1e-6:
        out["voice_settings"] = {"speed": max(0.5, min(1.5, float(speed)))}
    if title:
        out["title"] = title[:100]
    if mode == "photo":
        if expressiveness in ("low", "medium", "high"):
            out["expressiveness"] = expressiveness
        if motion_prompt.strip():
            out["motion_prompt"] = motion_prompt.strip()
    return out


# ---------------------------------------------------------------------- danh sách lưu trên máy (cho ô chọn)
def cache_path() -> Path:
    from ..paths import DATA_DIR

    return DATA_DIR / CACHE_NAME


def cached() -> dict:
    try:
        data = json.loads(cache_path().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def fill_fields(fields: list) -> list:
    """Ô chọn avatar / giọng của khối Video HeyGen ← danh sách đã tải (không có khoá)."""
    data = cached()

    def label(x: dict, kind: str) -> str:
        extra = [x.get("lang") if kind == "voice" else "", x.get("gender") or "", "của bạn" if x.get("own") else ""]
        return str(x.get("name") or x.get("id") or "") + "".join(f" · {e}" for e in extra if e)

    opts = {"heygen_avatar": [{"value": "", "label": "— chọn avatar —"}]
            + [{"value": a["id"], "label": label(a, "avatar")} for a in data.get("avatars") or [] if a.get("id")],
            "heygen_voice": [{"value": "", "label": "Giọng mặc định của avatar"}]
            + [{"value": v["id"], "label": label(v, "voice")} for v in data.get("voices") or [] if v.get("id")]}
    return [{**f, "options": opts[f["type"]], "loaded": bool(data.get("at"))} if f.get("type") in opts else f
            for f in fields]


def refresh(api_key: str, session=None) -> dict:
    client = HeyGen(api_key, session)
    data = {"avatars": client.avatars(), "voices": client.voices(), "at": int(time.time())}
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return data
