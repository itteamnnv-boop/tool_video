"""API · Tạo video / hình ảnh, hàng đợi tác vụ, thư viện video / ảnh, sửa khung cảnh HTML."""
import os

from .. import image_library, library
from ..config import settings
from ..pipeline import scene_dir_name

from .common import _fail, _ok


class MediaApi:
    # ------------------------------------------------------------------ tạo video
    def start_job(self, form: dict) -> dict:
        settings.update({"last_form": form, "provider": form.get("provider", settings.get("provider"))})
        try:
            return _ok(task=self._runner.start(form))
        except (ValueError, RuntimeError) as exc:
            return _fail(exc)

    def cancel_job(self, task_id: str = "") -> dict:
        return _ok(cancelled=self._runner.cancel(task_id))

    # ------------------------------------------------------------------ hàng đợi tác vụ (kind = video | image)
    def _pool(self, kind: str):
        if kind == "campaign":
            return self._campaigns.pool
        if kind == "workflow":
            return self._workflows.pool
        if kind == "studio":
            return self._studio.pool
        if kind == "mstudio":
            return self._studio_muse.pool
        return self._images.pool if kind == "image" else self._runner.pool

    def list_tasks(self, kind: str = "video") -> list:
        return self._pool(kind).list()

    def task_logs(self, kind: str, task_id: str) -> list:
        return self._pool(kind).logs(task_id)

    def clear_tasks(self, kind: str = "video") -> dict:
        self._pool(kind).clear_finished()
        return _ok(tasks=self._pool(kind).list())

    # ------------------------------------------------------------------ tạo hình ảnh
    def start_image_job(self, form: dict) -> dict:
        settings.update({"last_image_form": form})
        try:
            return _ok(task=self._images.start(form))
        except (ValueError, RuntimeError) as exc:
            return _fail(exc)

    def search_pinterest(self, keyword: str, limit: int = 12) -> dict:
        from ..llm.base import LLMError
        from ..llm.pinterest import search

        try:
            return _ok(results=search(keyword, limit=max(1, min(30, int(limit)))))
        except LLMError as exc:
            return _fail(exc)

    def cancel_image_job(self, task_id: str = "") -> dict:
        return _ok(cancelled=self._images.cancel(task_id))

    def list_images(self) -> list:
        return image_library.list_images(settings.output_dir)

    def delete_images(self, job_id: str) -> dict:
        try:
            image_library.delete_images(settings.output_dir, job_id)
            return _ok()
        except (image_library.ImageLibraryError, OSError) as exc:
            return _fail(exc)

    def open_images_folder(self, job_id: str = "", name: str = "") -> dict:
        """Mở thư mục ảnh trong Explorer; có bộ ảnh → chọn sẵn đúng file ảnh (name, mặc định ảnh đầu tiên)."""
        import subprocess

        try:
            if not job_id:
                os.startfile(image_library.root(settings.output_dir))
                return _ok()
            folder = image_library.job_path(settings.output_dir, job_id)
        except image_library.ImageLibraryError as exc:
            return _fail(exc)
        target = folder / name if name and "/" not in name and "\\" not in name else None
        if target is None or not target.is_file():
            target = next((p for p in sorted(folder.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")), None)
        if target is not None and target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            os.startfile(folder)
        return _ok(path=str(target or folder))

    # ------------------------------------------------------------------ thư viện
    def list_videos(self) -> list:
        return library.list_videos(settings.output_dir)

    def get_video(self, job_id: str) -> dict:
        try:
            job_dir, job = library.load_job(settings.output_dir, job_id)
            return _ok(video=library.detail(job_dir, job))
        except library.LibraryError as exc:
            return _fail(exc)

    def delete_video(self, job_id: str) -> dict:
        try:
            library.delete_video(settings.output_dir, job_id)
            return _ok()
        except (library.LibraryError, OSError) as exc:
            return _fail(exc)

    def open_video(self, job_id: str) -> dict:
        try:
            path = library.job_path(settings.output_dir, job_id) / "final.mp4"
            os.startfile(path if path.exists() else path.parent)
            return _ok()
        except library.LibraryError as exc:
            return _fail(exc)

    def open_video_folder(self, job_id: str) -> dict:
        """Mở thư mục chứa video trong Explorer, chọn sẵn file final.mp4 (để copy / kéo thả đi nơi khác)."""
        import subprocess

        try:
            path = library.job_path(settings.output_dir, job_id) / "final.mp4"
        except library.LibraryError as exc:
            return _fail(exc)
        if path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(path.parent)
        return _ok(path=str(path))

    def _scene_html_path(self, job_id: str, index: int):
        return library.job_path(settings.output_dir, job_id) / "scenes" / scene_dir_name(int(index)) / "scene.html"

    def get_scene_html(self, job_id: str, index: int) -> dict:
        try:
            return _ok(html=self._scene_html_path(job_id, index).read_text("utf-8"))
        except (library.LibraryError, OSError) as exc:
            return _fail(exc)

    def save_scene_html(self, job_id: str, index: int, html: str) -> dict:
        try:
            self._scene_html_path(job_id, index).write_text(html, "utf-8")
            return _ok()
        except (library.LibraryError, OSError) as exc:
            return _fail(exc)

    def rerender_scene(self, job_id: str, index: int) -> dict:
        try:
            return _ok(task=self._runner.rerender(job_id, int(index)))
        except RuntimeError as exc:
            return _fail(exc)
