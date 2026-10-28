"""API · Khởi tạo, cửa sổ không viền, cài đặt, chọn file / thư mục, đăng nhập trình duyệt, giấy phép."""
import atexit
import json
import os
import threading
import webview

from ..osutil import open_path
from .. import __version__, browser_profiles
from ..config import settings
from ..genres import GENRES
from ..license import LicenseError, LicenseManager
from ..llm.image_engines import DEFAULT_ENGINE as DEFAULT_IMAGE_ENGINE, ENGINES as IMAGE_ENGINES
from ..llm.video_engines import ENGINES
from ..pipeline import ASPECTS
from ..pipeline.image_job import ImageRunner
from ..pipeline.orchestrator import JobRunner
from ..pipeline.tts import RATES, VOICES
from ..posts import PostScheduler, PostStore
from ..templates_registry import registry

from .common import _fail, _ok, log


def _popup_rect(compact: bool = False) -> tuple[int, int, int, int]:
    """Khung cửa sổ popup cho link ngoài: ~70% vùng làm việc (trừ taskbar), căn giữa. Trả về (x, y, rộng, cao).
    compact = khung dọc nhỏ (~520×920, như điện thoại) sát mép phải — xem bài đăng mà vẫn thấy app."""
    try:
        import ctypes
        from ctypes import wintypes

        area = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
        left, top, sw, sh = area.left, area.top, area.right - area.left, area.bottom - area.top
    except (AttributeError, OSError):
        left, top, sw, sh = 0, 0, 1600, 900
    if compact:
        w, h = min(520, sw), min(920, int(sh * 0.92))
        return left + sw - w - 16, top + (sh - h) // 2, w, h
    w, h = max(900, int(sw * 0.7)), max(640, int(sh * 0.78))
    w, h = min(w, sw), min(h, sh)
    return left + (sw - w) // 2, top + (sh - h) // 2, w, h


class CoreApi:
    def __init__(self) -> None:
        self._window = None
        if os.name == "nt":  # trả lại nút taskbar cho Chrome bị bản cũ ẩn nhầm (ô nhỏ góc màn hình) — chạy nền, 1 lần
            from ..llm.browser_chat import _hide_offscreen_from_taskbar
            threading.Thread(target=_hide_offscreen_from_taskbar, daemon=True, name="taskbar-repair").start()
        self._license = LicenseManager(settings, on_change=lambda st: self._emit("license", st))
        self._runner = JobRunner(settings, self._license, self._emit)
        from ..llm import offers  # model trình duyệt đề xuất / hỏi lại → form duyệt hoặc tự đồng ý

        offers.configure(settings, self._emit)
        self._images = ImageRunner(settings, self._license, self._emit)
        from ..seedance.studio import Studio
        self._seedance = Studio(settings, self._license, self._emit)
        from ..facebook import FacebookManager
        self._facebook = FacebookManager()
        from ..facebook_ads import AdsManager
        self._ads = AdsManager(self._facebook)
        self._posts = PostStore(self._facebook)  # Quản lý bài đăng (lưu + đăng lại)
        # bài lên lịch (app tự đăng) — đăng đúng giờ khi app đang mở; xử lý xong báo giao diện tải lại danh sách
        self._post_scheduler = PostScheduler(self._posts, on_change=lambda: self._emit("posts_changed", {})).start()
        # nghe nhóm Zalo (Cài đặt chung → Zalo) — bật sẵn nếu lần trước đang bật; tắt app thì dừng tiến trình Node
        from ..zalo_listener import ZaloListener

        self._zalo = ZaloListener(settings, self._emit, lambda: self._adreq())
        if settings.get("zalo_listen"):
            self._zalo.start()
        atexit.register(self._zalo.shutdown)
        from ..campaign.pipeline import CampaignRunner
        from ..campaign.ai import migrate_legacy_keys
        migrate_legacy_keys()  # khoá cũ nhập ở Thư viện chiến dịch → Cài đặt
        self._campaigns = CampaignRunner(settings, self._license, self._facebook, self._emit,
                                         images=self._images, videos=self._runner, ads=self._ads)
        from ..cast import CastRunner
        self._cast = CastRunner(settings, self._license, self._emit, images=self._images)  # Nhân vật & Layout
        from ..studio import StudioRunner
        self._studio = StudioRunner(settings, self._license, self._emit, images=self._images, videos=self._runner)
        self._studio.cast = self._cast  # Studio dùng nhân vật / layout cố định
        from ..canvas import CanvasRunner
        self._canvas = CanvasRunner(settings, self._emit, images=self._images, videos=self._runner,
                                    facebook=self._facebook, ads=self._ads, studio=self._studio)  # Canvas
        # chạy quy trình xong → trợ lý Claude tự điều phối (chỉ khi Canvas đó bật): chấm theo tiêu chí, giao khối làm lại
        self._canvas.on_flow_done = lambda bid, rec: self._assist().after_run(bid, rec)
        from ..canvas_schedule import CanvasScheduler  # ⏰ lập lịch chạy Canvas (chạy khi app đang mở)

        self._canvas_scheduler = CanvasScheduler(self._canvas).start()
        # Studio Muse AI: cùng chức năng Studio, dự án riêng, mọi bước chỉ dùng Muse (sự kiện mstudio_*)
        self._studio_muse = StudioRunner(settings, self._license, self._emit, images=self._images, videos=self._runner,
                                         variant="muse")
        self._studio_muse.cast = self._cast
        from ..muse_hub import MuseHub
        self._muse_hub = MuseHub(settings, self._emit)  # Studio Muse AI: tài khoản, hàng đợi, tư liệu, thư viện
        from ..muse_post import PostRunner
        from ..pipeline.sfx import AUDIO_EXT

        def hub_music() -> str:  # nhạc nền: thư mục nhạc của Studio Muse AI (nếu có bài) → không thì thư mục ở Cài đặt
            folder = self._muse_hub.bgm_dir()
            return str(folder) if any(p.suffix.lower() in AUDIO_EXT for p in folder.iterdir()) else ""

        self._muse_post = PostRunner(settings, self._emit, music_dir=hub_music)  # tab Hậu kỳ của Studio Muse AI
        from ..workflow.runner import WorkflowRunner
        self._workflows = WorkflowRunner(settings, self._license, self._emit, facebook=self._facebook, ads=self._ads,
                                         studio=self._studio)
    def attach(self, window) -> None:
        self._window = window
        self._win_max = False
        self._license.start_heartbeat()

    # ------------------------------------------------------------------ cửa sổ không viền (header = thanh tiêu đề)
    def win_info(self) -> dict:
        w = self._window
        min_w, min_h = getattr(w, "min_size", (1200, 760)) if w else (1200, 760)
        return {"frameless": bool(w is not None and getattr(w, "frameless", False)),
                "maximized": getattr(self, "_win_max", False), "min_w": min_w, "min_h": min_h}

    def win_minimize(self) -> None:
        self._window.minimize()

    def win_close(self) -> None:
        self._window.destroy()

    def win_toggle_maximize(self) -> dict:
        self._win_max = getattr(self, "_win_max", False)
        if self._win_max:
            self._window.restore()
        else:
            self._maximize()
        self._win_max = not self._win_max
        return {"maximized": self._win_max}

    def _maximize(self) -> None:
        """Phóng to vừa vùng làm việc của màn hình (form không viền mặc định phóng to đè cả thanh taskbar)."""
        form = getattr(self._window, "native", None)
        try:
            from System import Func, Type
            from System.Drawing import Rectangle
            from System.Windows.Forms import FormWindowState, Screen

            def apply():
                screen = Screen.FromHandle(form.Handle)
                work, full = screen.WorkingArea, screen.Bounds
                form.MaximizedBounds = Rectangle(work.X - full.X, work.Y - full.Y, work.Width, work.Height)
                form.WindowState = FormWindowState.Maximized

            form.Invoke(Func[Type](apply))
        except Exception:  # không phải WinForms (macOS / Linux) → cách mặc định của pywebview
            self._window.maximize()

    def win_set_bounds(self, x: float, y: float, width: float, height: float) -> None:
        """Kéo giãn cửa sổ từ mép / góc (toạ độ CSS px) — 1 lệnh SetWindowPos để không giật."""
        w = self._window
        min_w, min_h = getattr(w, "min_size", (1200, 760))
        width, height = max(min_w, float(width)), max(min_h, float(height))
        form = getattr(w, "native", None)
        try:
            from ctypes import windll

            scale = form._scale
            windll.user32.SetWindowPos(form.Handle.ToInt32(), None, int(x * scale), int(y * scale),
                                       int(width * scale), int(height * scale), 0x0004 | 0x0010)  # NOZORDER|NOACTIVATE
        except Exception:
            w.resize(int(width), int(height))
            w.move(int(x), int(y))

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

    # ------------------------------------------------------------------ khoá màn Cài đặt (mật khẩu quản trị)
    def _admin_lock(self):
        if not hasattr(self, "_admin"):
            from ..admin_lock import AdminLock
            self._admin = AdminLock()
        return self._admin

    def settings_lock_state(self) -> dict:
        lock = self._admin_lock()
        lock.touch()  # mở / quay lại màn Cài đặt = còn thao tác → gia hạn mở khoá
        return _ok(lock=lock.state())

    def settings_unlock(self, password: str) -> dict:
        from ..admin_lock import LockError
        try:
            return _ok(lock=self._admin_lock().unlock(password))
        except LockError as exc:
            return _fail(exc)

    def settings_set_password(self, new: str, old: str = "") -> dict:
        from ..admin_lock import LockError
        try:
            return _ok(lock=self._admin_lock().set_password(new, old))
        except LockError as exc:
            return _fail(exc)

    def settings_lock(self) -> dict:
        return _ok(lock=self._admin_lock().lock())

    def save_settings(self, values: dict) -> dict:
        lock = self._admin_lock()
        values = lock.guard(values)  # Cài đặt đang khoá → không đổi khoá API / license / menu
        lock.touch()
        before = (settings.get("browser_engine"), settings.get("browser_keepalive"))
        result = settings.update(values)
        if before != (settings.get("browser_engine"), settings.get("browser_keepalive")):
            from ..llm import chrome_pool  # đổi cách điều khiển Chrome → đóng Chrome mở sẵn đang rảnh
            chrome_pool.stop_idle()
        return result

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
            "video": ("Video (*.mp4;*.mov;*.webm;*.m4v)",),
            "videos": ("Video (*.mp4;*.mov;*.webm;*.m4v)",),
            "images_multi": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp)",),
            "seedance_images": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.avif)",),
            "media": ("Ảnh và video (*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.m4v)",),
            "srt": ("Phụ đề SRT (*.srt)",),
            "audio": ("Âm thanh (*.mp3;*.wav;*.m4a;*.aac;*.ogg;*.flac)",),
            "docs": ("Tài liệu (*.txt;*.md;*.csv;*.json;*.docx;*.srt;*.vtt)",),
            "cast_refs": ("Ảnh và ghi chú (*.png;*.jpg;*.jpeg;*.webp;*.txt;*.md)",),
        }.get(kind)
        if file_types is None:
            return []
        open_dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        result = self._window.create_file_dialog(open_dialog, allow_multiple=kind in ("products", "images_multi", "seedance_images", "docs", "videos", "cast_refs"), file_types=file_types)
        return list(result or [])

    def open_output_dir(self) -> dict:
        open_path(settings.output_dir)
        return _ok()

    def open_url(self, url: str, compact: bool = False) -> dict:
        """Mở link ngoài thành cửa sổ popup gọn (~70% màn hình, căn giữa) bằng Chrome của người dùng (--app: không thanh
        tab / địa chỉ, giữ đăng nhập Facebook…). compact = cửa sổ dọc nhỏ sát mép phải (xem bài / Reels vừa đăng).
        Không có Chrome → trình duyệt mặc định như cũ."""
        import subprocess
        import webbrowser

        url = str(url or "")
        if not url.startswith("https://"):
            return _ok()
        try:
            from ..llm.chrome_pool import _chrome_exe

            exe = _chrome_exe("chrome")
        except RuntimeError:
            webbrowser.open(url)
            return _ok()
        x, y, w, h = _popup_rect(compact)
        subprocess.Popen([exe, f"--app={url}", f"--window-size={w},{h}", f"--window-position={x},{y}"])
        return _ok()

    def offer_answer(self, rid: str, choice: str, text: str = "", always: bool = False) -> dict:
        """Form duyệt đề xuất của model: choice = agree | custom (kèm text) | stop; always = từ giờ tự đồng ý."""
        from ..llm import offers

        if not offers.answer(rid, choice, text, always):
            return _fail("Form duyệt đã hết hạn (đã tự đồng ý) hoặc tác vụ đã dừng")
        return _ok()

    # ------------------------------------------------------------------ đăng nhập
    def browser_login(self, provider: str = "gemini_browser", profile_id: str = "") -> dict:
        """Mở cửa sổ đăng nhập model trong profile chỉ định (rỗng = profile rảnh đầu tiên được gán cho model)."""
        from ..llm.browser_chat import SITES, open_login_window

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
