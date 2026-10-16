"""Cầu nối JS ↔ Python cho pywebview (window.pywebview.api.<method>)."""
import json
import logging
import os
import threading

import webview

from . import __version__, library
from .config import settings
from .genres import GENRES
from .license import LicenseError, LicenseManager
from . import browser_profiles, image_library
from .llm.image_engines import DEFAULT_ENGINE as DEFAULT_IMAGE_ENGINE
from .llm.image_engines import ENGINES as IMAGE_ENGINES
from .llm.video_engines import ENGINES
from .pipeline.image_job import ImageRunner
from .pipeline import ASPECTS, scene_dir_name
from .pipeline.orchestrator import JobRunner
from .pipeline.tts import RATES, VOICES
from .templates_registry import registry

log = logging.getLogger(__name__)


def _ok(**data) -> dict:
    return {"ok": True, **data}


def _fail(exc: Exception) -> dict:
    return {"ok": False, "error": str(exc)}


class Api:
    def __init__(self) -> None:
        self._window = None
        self._license = LicenseManager(settings, on_change=lambda st: self._emit("license", st))
        self._runner = JobRunner(settings, self._license, self._emit)
        self._images = ImageRunner(settings, self._license, self._emit)
        from .facebook import FacebookManager
        self._facebook = FacebookManager()
        from .facebook_ads import AdsManager
        self._ads = AdsManager(self._facebook)

    def attach(self, window) -> None:
        self._window = window
        self._license.start_heartbeat()

    def _emit(self, event: str, data) -> None:
        if self._window is None:
            return
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        try:
            self._window.evaluate_js(f"window.__onBackend && window.__onBackend({payload})")
        except Exception:  # cửa sổ đang đóng / chưa sẵn sàng
            log.debug("emit %s thất bại", event, exc_info=True)

    # ------------------------------------------------------------------ khởi tạo & cài đặt
    def bootstrap(self) -> dict:
        return {
            "version": __version__,
            "settings": settings.all(),
            "categories": registry.categories(),
            "template_count": len(registry.listed()),
            "video_engines": ENGINES,
            "image_engines": IMAGE_ENGINES,
            "default_image_engine": DEFAULT_IMAGE_ENGINE,
            "image_templates": [t.as_dict() for t in registry.image_templates()],
            "image_running": self._images.running,
            "tasks": self._runner.pool.list(),
            "image_tasks": self._images.pool.list(),
            "profiles": browser_profiles.list_profiles(),
            "profile_sites": browser_profiles.SITE_NAMES,
            "genres": GENRES,
            "voices": VOICES,
            "rates": RATES,
            "aspects": list(ASPECTS),
            "license": self._license.status(),
            "running": self._runner.running,
        }

    def save_settings(self, values: dict) -> dict:
        return settings.update(values)

    def pick_output_dir(self) -> dict:
        folder_dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder_dialog, directory=str(settings.output_dir))
        if result:
            settings.update({"output_dir": result[0] if isinstance(result, (list, tuple)) else result})
        return settings.all()

    def pick_music_dir(self) -> dict:
        folder_dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder_dialog)
        if result:
            settings.update({"music_dir": result[0] if isinstance(result, (list, tuple)) else result})
        return settings.all()

    def pick_files(self, kind: str) -> list:
        """kind = 'layout' (1 ảnh hoặc HTML) | 'products' (nhiều ảnh)."""
        file_types = {
            "layout": ("Layout mẫu (*.png;*.jpg;*.jpeg;*.webp;*.html;*.htm)",),
            # pywebview chỉ nhận mô tả gồm chữ/số/khoảng trắng (không có "/", "-"...)
            "products": ("Ảnh và video (*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.m4v)",),
            "image": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp)",),
            "image_or_video": ("Ảnh và video (*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.m4v)",),
            "images_multi": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp)",),
            "media": ("Ảnh và video (*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.m4v)",),
        }.get(kind)
        if file_types is None:
            return []
        open_dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        result = self._window.create_file_dialog(open_dialog, allow_multiple=kind in ("products", "images_multi"), file_types=file_types)
        return list(result or [])

    def open_output_dir(self) -> dict:
        os.startfile(settings.output_dir)
        return _ok()

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
        return self._images.pool if kind == "image" else self._runner.pool

    def list_tasks(self, kind: str = "video") -> list:
        return self._pool(kind).list()

    def task_logs(self, kind: str, task_id: str) -> list:
        return self._pool(kind).logs(task_id)

    def clear_tasks(self, kind: str = "video") -> dict:
        self._pool(kind).clear_finished()
        return _ok(tasks=self._pool(kind).list())

    # ------------------------------------------------------------------ profile trình duyệt
    def _profiles_call(self, fn, *args) -> dict:
        try:
            return _ok(profiles=fn(*args))
        except browser_profiles.ProfileError as exc:
            return _fail(exc)

    def profiles_list(self) -> dict:
        return _ok(profiles=browser_profiles.list_profiles())

    def profiles_create(self, name: str, sites: list, channel: str = "") -> dict:
        return self._profiles_call(browser_profiles.create, name, sites, channel)

    def profiles_update(self, profile_id: str, name=None, sites=None, channel=None) -> dict:
        return self._profiles_call(browser_profiles.update, profile_id, name, sites, channel)

    def profiles_delete(self, profile_id: str) -> dict:
        return self._profiles_call(browser_profiles.delete, profile_id)

    # ------------------------------------------------------------------ tạo hình ảnh
    def start_image_job(self, form: dict) -> dict:
        settings.update({"last_image_form": form})
        try:
            return _ok(task=self._images.start(form))
        except (ValueError, RuntimeError) as exc:
            return _fail(exc)

    def search_pinterest(self, keyword: str, limit: int = 12) -> dict:
        from .llm.base import LLMError
        from .llm.pinterest import search

        try:
            return _ok(results=search(keyword, limit=max(1, min(30, int(limit)))))
        except LLMError as exc:
            return _fail(exc)

    # ------------------------------------------------------------------ fanpage Facebook
    def _fb_call(self, fn, *args) -> dict:
        from .facebook import FacebookError

        try:
            return _ok(fb=fn(*args))
        except FacebookError as exc:
            return _fail(exc)

    def fb_state(self) -> dict:
        return _ok(fb=self._facebook.state())

    def fb_save_app(self, app_id: str, app_secret: str, graph_version: str = "") -> dict:
        return self._fb_call(self._facebook.save_app, app_id, app_secret, graph_version)

    def fb_connect_token(self, token: str) -> dict:
        return self._fb_call(self._facebook.connect_token, token)

    def open_url(self, url: str) -> dict:
        import webbrowser

        if str(url).startswith("https://"):
            webbrowser.open(url)
        return _ok()

    def fb_logout(self) -> dict:
        return self._fb_call(self._facebook.logout)

    def fb_load_pages(self) -> dict:
        return self._fb_call(self._facebook.load_pages)

    def fb_set_connected(self, page_id: str, connected: bool) -> dict:
        return self._fb_call(self._facebook.set_connected, page_id, connected)

    def fb_post(self, page_id: str, message: str, file_path: str = "") -> dict:
        from .facebook import FacebookError

        try:
            return _ok(post=self._facebook.post(page_id, message, file_path))
        except (FacebookError, OSError) as exc:
            return _fail(exc)

    # ------------------------------------------------------------------ quảng cáo Facebook
    def _ads_call(self, key: str, fn, *args) -> dict:
        from .facebook import FacebookError

        try:
            return _ok(**{key: fn(*args)})
        except FacebookError as exc:
            return _fail(exc)

    def ads_status(self) -> dict:
        return _ok(ads=self._ads.status())

    def ads_accounts(self) -> dict:
        return self._ads_call("accounts", self._ads.accounts)

    def ads_overview(self, account_id: str, date_preset: str) -> dict:
        return self._ads_call("overview", self._ads.overview, account_id, date_preset)

    def ads_list(self, account_id: str, level: str, parent_id: str, date_preset: str) -> dict:
        return self._ads_call("data", self._ads.list, account_id, level, parent_id, date_preset)

    def ads_set_status(self, object_id: str, status: str) -> dict:
        return self._ads_call("result", self._ads.set_status, object_id, status)

    def ads_set_budget(self, account_id: str, object_id: str, daily_budget) -> dict:
        return self._ads_call("result", self._ads.set_budget, account_id, object_id, daily_budget)

    def ads_page_posts(self, page_id: str, after: str = "") -> dict:
        return self._ads_call("posts", self._ads.page_posts, page_id, after)

    def ads_create_boost(self, form: dict) -> dict:
        return self._ads_call("result", self._ads.create_boost, form)

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

    def open_images_folder(self, job_id: str = "") -> dict:
        try:
            folder = (image_library.job_path(settings.output_dir, job_id) if job_id
                      else image_library.root(settings.output_dir))
            os.startfile(folder)
            return _ok()
        except image_library.ImageLibraryError as exc:
            return _fail(exc)

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

    # ------------------------------------------------------------------ đăng nhập
    def browser_login(self, provider: str = "gemini_browser", profile_id: str = "") -> dict:
        """Mở cửa sổ đăng nhập model trong profile chỉ định (rỗng = profile rảnh đầu tiên được gán cho model)."""
        from .llm.browser_chat import SITES, open_login_window

        site = provider.removesuffix("_browser")
        if site not in SITES:
            return _fail(ValueError(f"Provider '{provider}' không dùng trình duyệt"))
        name = SITES[site].name
        profiles = {p["id"]: p for p in browser_profiles.list_profiles()}
        if profile_id and profile_id not in profiles:
            return _fail(ValueError("Không tìm thấy profile"))
        if profile_id and profiles[profile_id]["busy"]:
            return _fail(ValueError(f"Profile “{profiles[profile_id]['name']}” đang được dùng — chờ tác vụ xong"))
        label = f"{name} · {profiles[profile_id]['name']}" if profile_id else name

        def run():
            self._emit("toast", {"message": f"Đăng nhập {label} trong cửa sổ trình duyệt, xong thì đóng cửa sổ đó."})
            self._emit("profiles", {"profiles": browser_profiles.list_profiles()})
            try:
                with browser_profiles.task_context(profile_id):
                    open_login_window(site, settings.get("browser_channel"))
                self._emit("toast", {"message": f"Đã lưu phiên đăng nhập {label}", "level": "ok"})
            except Exception as exc:  # lỗi mở trình duyệt hiển thị cho người dùng
                self._emit("toast", {"message": f"Không mở được trình duyệt: {exc}", "level": "error"})
            finally:
                self._emit("profiles", {"profiles": browser_profiles.list_profiles()})

        threading.Thread(target=run, daemon=True).start()
        return _ok()

    def license_login(self) -> dict:
        try:
            return _ok(license=self._license.login())
        except LicenseError as exc:
            return _fail(exc)

    def license_logout(self) -> dict:
        return _ok(license=self._license.logout())

    def license_refresh(self) -> dict:
        return _ok(license=self._license.verify())
