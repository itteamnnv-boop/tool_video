"""API · Studio (ý tưởng → storyboard → cảnh → video) + Studio Muse AI (mstudio_*), whiteboard, SRT."""
import webview

from ..config import settings

from .common import _fail, _ok, log


class _MuseStudioView:
    """Api nhìn qua Studio Muse AI: mọi thuộc tính lấy từ Api, riêng _studio là runner Muse — dùng lại nguyên các
    hàm studio_* cho màn Studio Muse AI (không đổi trạng thái chung, an toàn khi nhiều luồng gọi cùng lúc)."""

    def __init__(self, api) -> None:
        self._api = api
        self._studio = api._studio_muse

    def __getattr__(self, name):
        return getattr(self._api, name)


class StudioApi:
    # ---- thư viện chiến dịch
    # ---- Studio: ý tưởng → storyboard → cảnh → video dài
    def _st(self, key: str, fn, *args) -> dict:
        from ..studio import StudioError

        try:
            return _ok(**{key: fn(*args)})
        except (StudioError, ValueError, OSError) as exc:
            return _fail(exc)

    def studio_meta(self) -> dict:
        from ..studio import meta

        return _ok(meta=meta(settings))

    def studio_list(self) -> dict:
        return self._st("projects", lambda: [self._studio.public(p) for p in self._studio.store.list()])

    def studio_get(self, pid: str) -> dict:
        return self._st("project", lambda: self._studio.public(self._studio.store.load(pid)))

    def studio_create(self, form: dict) -> dict:
        return self._st("result", self._studio.create, form)

    def studio_create_batch(self, form: dict) -> dict:
        """Tạo hàng loạt: mỗi dòng ý tưởng = 1 dự án, tự viết storyboard → làm cảnh → ghép."""
        return self._st("result", self._studio.create_batch, form)

    def studio_resume_all(self) -> dict:
        """Chạy tiếp mọi dự án Studio chưa có video."""
        return self._st("result", self._studio.resume_all)

    def transition_sound_preview(self, key: str) -> dict:
        """Nghe thử âm chuyển cảnh: trả về file wav dạng data URL (âm tự tổng hợp, lưu cache)."""
        import base64

        from ..pipeline import transitions

        try:
            path = transitions.sound_file(str(key or ""))
        except Exception as exc:  # ffmpeg lỗi khi tạo âm
            return _fail(exc)
        return _ok(data=("data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode()) if path else "")

    def studio_voice_preview(self, text: str, speaker: str, voice: str, rate: str) -> dict:
        """Nghe thử lời dẫn một cảnh với vai giọng đã chọn (edge-tts, cần internet): trả về mp3 dạng data URL."""
        import base64
        import tempfile
        from pathlib import Path

        from ..pipeline.tts import role_voice, synthesize

        text = " ".join(str(text or "").split())[:300] or "Xin chào, đây là giọng đọc thử."
        tts_voice, tts_rate, pitch = role_voice(str(speaker or ""), str(voice or "vi-VN-HoaiMyNeural"), str(rate or "+0%"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "preview.mp3"
            try:
                synthesize(text, tts_voice, tts_rate, out, retries=2, pitch=pitch)
            except Exception as exc:  # mạng / edge-tts lỗi
                return _fail(exc)
            return _ok(data="data:audio/mpeg;base64," + base64.b64encode(out.read_bytes()).decode())

    def hyperframes_status(self) -> dict:
        """Node.js / ffprobe / HyperFrames đã sẵn sàng chưa (hiện ở ✨ Hậu kỳ AI → Kiểu HyperFrames)."""
        from ..pipeline import hyperframes

        return _ok(status=hyperframes.status())

    def whiteboard_status(self) -> dict:
        """Bộ dựng srt-whiteboard-animation đã tải + cài chưa (lần đầu dựng sẽ tự cài)."""
        from ..pipeline import whiteboard

        return _ok(status=whiteboard.status())

    def whiteboard_make_srt(self, text: str, voice: str = "", rate: str = "") -> dict:
        """Tự tạo SRT từ kịch bản thường (giọng AI đọc để lấy mốc) — trả về SRT + file giọng đọc khớp mốc."""
        from ..pipeline import whiteboard
        from ..pipeline.tts import TTSError

        try:
            return _ok(**whiteboard.make_srt(text, voice or "vi-VN-HoaiMyNeural", rate or "+0%"))
        except (whiteboard.WhiteboardError, TTSError, OSError) as exc:
            return _fail(exc)

    def save_srt(self, text: str, name: str = "phu-de.srt") -> dict:
        """Lưu nội dung SRT ra file người dùng chọn (hộp thoại Lưu)."""
        from pathlib import Path

        if not str(text or "").strip():
            return _fail("Chưa có nội dung SRT")
        save_dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        result = self._window.create_file_dialog(save_dialog, save_filename=name, file_types=("Phụ đề SRT (*.srt)",))
        if not result:
            return _ok(path="")
        path = Path(result if isinstance(result, str) else result[0])
        if path.suffix.lower() != ".srt":
            path = path.with_suffix(".srt")
        path.write_text(str(text).replace("\r\n", "\n"), "utf-8-sig")
        return _ok(path=str(path))

    def whiteboard_read_srt(self, path: str) -> dict:
        """Đọc file .srt người dùng chọn → nội dung để hiện / sửa trong ô SRT."""
        from pathlib import Path

        from ..pipeline import whiteboard

        file = Path(str(path or ""))
        if file.suffix.lower() != ".srt" or not file.is_file():
            return _fail("Chọn file phụ đề .srt")
        if file.stat().st_size > 2_000_000:
            return _fail("File SRT quá lớn (tối đa 2 MB)")
        text = whiteboard.read_srt_file(file)
        return _ok(text=text, cues=len(whiteboard.parse_srt(text)), name=file.name)

    def studio_logs(self, pid: str) -> dict:
        """Tác vụ gần nhất của dự án (đang chạy hoặc vừa xong) + nhật ký — mở dự án giữa chừng vẫn thấy tiến trình."""
        task_id = self._studio._active.get(pid)
        task = next((t for t in self._studio.pool.list() if t["id"] == task_id), None) if task_id else None
        if task is None:
            return _ok(task=None, logs=[])
        return _ok(task=task, logs=self._studio.pool.logs(task_id))

    def studio_analyze_video(self, source: str, model: str = "gemini_browser", profile: str = "",
                             show_browser: bool = False) -> dict:
        """🎬 Video tham khảo: link (YouTube / TikTok / Facebook…) hoặc file → phân tích hook, cấu trúc, nhịp, phong cách
        (1 lượt hỏi model; Gemini / Claude API / OpenAI API xem được ảnh khung hình). Chạy 1–3 phút."""
        from pathlib import Path

        from ..pipeline import ref_video

        try:
            result = ref_video.analyze(str(source or ""), settings, model=str(model or "gemini_browser"),
                                       profile=str(profile or ""), show_browser=bool(show_browser),
                                       log=lambda m, level="info": log.info("ref video: %s", m))
        except Exception as exc:  # tải link / model / ffmpeg lỗi → báo nguyên nhân cho người dùng
            return _fail(exc)
        rel = Path(result["sheet"]).relative_to(settings.output_dir).as_posix() if result.get("sheet") else ""
        return _ok(result={**result, "sheet_url": f"/media/{rel}" if rel else ""})

    def studio_ref_thumbs(self, paths: list) -> dict:
        """Ảnh thu nhỏ (data URL) của ảnh sản phẩm vừa chọn trên máy — để xem ngay khi viết ý tưởng."""
        import base64
        import io
        from pathlib import Path

        from PIL import Image

        out = {}
        for raw in (paths or [])[:6]:
            path = Path(str(raw))
            if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            try:
                with Image.open(path) as img:
                    img.thumbnail((180, 180))
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, "JPEG", quality=80)
                out[str(raw)] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            except OSError:
                continue
        return _ok(thumbs=out)

    def studio_live_preview(self, options: dict, pid: str = "", refs: list | None = None) -> dict:
        """📱 Xem trước giao diện livestream (1 khung, data URL) — nền là ảnh khung đầu cảnh 1 của dự án nếu có."""
        import base64
        import io
        from pathlib import Path

        from ..pipeline import live_sim
        from ..studio import StudioError, frame_size

        try:
            o = self._studio._clean(options or {})
            p = self._studio.store.load(pid) if pid else {"refs": [r for r in refs or [] if Path(str(r)).is_file()]}
            background = ""
            if pid:
                first = next((s for s in p.get("scenes") or [] if s.get("frame")), None)
                background = str(self._studio.store.dir(pid) / first["frame"]) if first else ""
            w, h = frame_size(o)
            avatar, product = self._studio._live_assets(o, p)
            scene_comments = next(((s.get("overlay") or {}).get("comments") for s in p.get("scenes") or []
                                   if (s.get("overlay") or {}).get("comments")), None)
            img = live_sim.preview(o["live"], w // 2, h // 2, background=background, avatar=avatar, product=product,
                                   comments=scene_comments or (o["live"].get("comments") or "").splitlines())
        except (StudioError, OSError, ValueError) as exc:
            return _fail(exc)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return _ok(image="data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())

    def studio_clone(self, pid: str, mode: str = "storyboard", name: str = "", refs: list | None = None) -> dict:
        """Nhân bản dự án Studio: idea | storyboard | media (xem StudioRunner.clone); refs = ảnh tham chiếu mới
        (None = chép nguyên ảnh của dự án gốc)."""
        return self._st("project", self._studio.clone, pid, mode, name, refs)

    def studio_set_logo(self, pid: str, path: str = "") -> dict:
        """Tải lên / bỏ (path rỗng) logo thương hiệu của dự án Studio."""
        return self._st("project", self._studio.set_logo, pid, path)

    def studio_save(self, pid: str, data: dict) -> dict:
        return self._st("project", self._studio.save, pid, data)

    def studio_start(self, pid: str, action: str, indexes: list | None = None, what: str = "both") -> dict:
        return self._st("task", self._studio.start, pid, action, indexes or [], what)

    # ---- mẫu dự án tự thêm (Bước 0) — kể cả mẫu tạo từ video trending
    def studio_kinds_save(self, kind: dict) -> dict:
        """Lưu (thêm / sửa) mẫu dự án của người dùng; trả về danh sách mẫu mới + mã mẫu vừa lưu."""
        from .. import studio_kinds
        from ..studio import kinds_meta

        try:
            _, key = studio_kinds.save(kind or {})
        except (ValueError, OSError) as exc:
            return _fail(exc)
        return _ok(kinds=kinds_meta(), key=key)

    def studio_kinds_delete(self, key: str) -> dict:
        from .. import studio_kinds
        from ..studio import kinds_meta

        try:
            studio_kinds.delete(str(key or ""))
        except OSError as exc:
            return _fail(exc)
        return _ok(kinds=kinds_meta())

    def studio_kind_from_video(self, source: str, model: str = "gemini_browser", profile: str = "",
                               show_browser: bool = False) -> dict:
        """🔥 Mẫu từ video trending: phân tích video (1 lượt model) → bản nháp mẫu (hook, cấu trúc cảnh, nhịp, phong cách)."""
        from .. import studio_kinds
        from ..studio import LENGTHS

        res = self.studio_analyze_video(source, model, profile, show_browser)
        if not res.get("ok"):
            return res
        return _ok(draft=studio_kinds.from_video(res["result"], LENGTHS))

    def studio_import_storyboard(self, pid: str, text: str) -> dict:
        """Dán JSON storyboard model đã viết (app chưa lấy được câu trả lời) → thành các cảnh, không hỏi model lại."""
        return self._st("project", self._studio.import_storyboard, pid, text)

    def studio_prompts(self, pid: str) -> dict:
        """Bước 4: sinh prompt ảnh + prompt video cho mọi cảnh (lỗi đỏ ở bước kiểm tra → báo lỗi, không sinh)."""
        return self._st("project", self._studio.prompts, pid)

    def studio_export(self, pid: str, fmt: str = "json") -> dict:
        """Bước 5: xuất JSON (schema cho dev) / Excel storyboard vào <dự án>/export/."""
        return self._st("result", self._studio.export, pid, fmt)

    def studio_open_export(self, pid: str) -> dict:
        """Mở thư mục chứa file đã xuất."""
        return self._st("folder", self._studio.open_export, pid)

    def studio_cancel(self, pid: str) -> dict:
        return _ok(cancelled=self._studio.cancel(pid))

    def studio_delete(self, pid: str) -> dict:
        return self._st("deleted", lambda: self._studio.delete(pid) or True)

    # ---------------------------------------------------------------------- Studio Muse AI (mstudio_*)
    # Như studio_* nhưng chạy qua runner Muse (_studio_muse) — mọi bước chỉ dùng Muse.
    def _mstudio(self, name: str, *args, **kwargs):
        if name == "analyze_video":  # video tham khảo cũng do Muse phân tích
            args = (args[0] if args else kwargs.pop("source", ""), "muse_browser", *args[2:])
            kwargs.pop("model", None)
        return getattr(StudioApi, f"studio_{name}")(_MuseStudioView(self), *args, **kwargs)

    def mstudio_meta(self, *args, **kwargs):
        """Studio Muse AI — như studio_meta, mọi bước chỉ dùng Muse."""
        return self._mstudio("meta", *args, **kwargs)

    def mstudio_ref_thumbs(self, *args, **kwargs):
        """Studio Muse AI — như studio_ref_thumbs."""
        return self._mstudio("ref_thumbs", *args, **kwargs)

    def mstudio_live_preview(self, *args, **kwargs):
        """Studio Muse AI — như studio_live_preview."""
        return self._mstudio("live_preview", *args, **kwargs)

    def mstudio_list(self, *args, **kwargs):
        """Studio Muse AI — như studio_list, mọi bước chỉ dùng Muse."""
        return self._mstudio("list", *args, **kwargs)

    def mstudio_get(self, *args, **kwargs):
        """Studio Muse AI — như studio_get, mọi bước chỉ dùng Muse."""
        return self._mstudio("get", *args, **kwargs)

    def mstudio_create(self, *args, **kwargs):
        """Studio Muse AI — như studio_create, mọi bước chỉ dùng Muse."""
        return self._mstudio("create", *args, **kwargs)

    def mstudio_create_batch(self, *args, **kwargs):
        """Studio Muse AI — như studio_create_batch, mọi bước chỉ dùng Muse."""
        return self._mstudio("create_batch", *args, **kwargs)

    def mstudio_resume_all(self, *args, **kwargs):
        """Studio Muse AI — như studio_resume_all, mọi bước chỉ dùng Muse."""
        return self._mstudio("resume_all", *args, **kwargs)

    def mstudio_voice_preview(self, *args, **kwargs):
        """Studio Muse AI — như studio_voice_preview, mọi bước chỉ dùng Muse."""
        return self._mstudio("voice_preview", *args, **kwargs)

    def mstudio_logs(self, *args, **kwargs):
        """Studio Muse AI — như studio_logs, mọi bước chỉ dùng Muse."""
        return self._mstudio("logs", *args, **kwargs)

    def mstudio_analyze_video(self, *args, **kwargs):
        """Studio Muse AI — như studio_analyze_video, mọi bước chỉ dùng Muse."""
        return self._mstudio("analyze_video", *args, **kwargs)

    def mstudio_clone(self, *args, **kwargs):
        """Studio Muse AI — như studio_clone, mọi bước chỉ dùng Muse."""
        return self._mstudio("clone", *args, **kwargs)

    def mstudio_set_logo(self, *args, **kwargs):
        """Studio Muse AI — như studio_set_logo, mọi bước chỉ dùng Muse."""
        return self._mstudio("set_logo", *args, **kwargs)

    def mstudio_save(self, *args, **kwargs):
        """Studio Muse AI — như studio_save, mọi bước chỉ dùng Muse."""
        return self._mstudio("save", *args, **kwargs)

    def mstudio_start(self, *args, **kwargs):
        """Studio Muse AI — như studio_start, mọi bước chỉ dùng Muse."""
        return self._mstudio("start", *args, **kwargs)

    def mstudio_cancel(self, *args, **kwargs):
        """Studio Muse AI — như studio_cancel, mọi bước chỉ dùng Muse."""
        return self._mstudio("cancel", *args, **kwargs)

    def mstudio_delete(self, *args, **kwargs):
        """Studio Muse AI — như studio_delete, mọi bước chỉ dùng Muse."""
        return self._mstudio("delete", *args, **kwargs)
