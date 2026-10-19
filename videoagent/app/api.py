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
from .posts import POST_TYPES, SCHEDULABLE, PostStore
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
        from .llm import offers  # model trình duyệt đề xuất / hỏi lại → form duyệt hoặc tự đồng ý

        offers.configure(settings, self._emit)
        self._images = ImageRunner(settings, self._license, self._emit)
        from .seedance.studio import Studio
        self._seedance = Studio(settings, self._license, self._emit)
        from .facebook import FacebookManager
        self._facebook = FacebookManager()
        from .facebook_ads import AdsManager
        self._ads = AdsManager(self._facebook)
        self._posts = PostStore(self._facebook)  # Quản lý bài đăng (lưu + đăng lại)
        from .campaign.pipeline import CampaignRunner
        from .campaign.ai import migrate_legacy_keys
        migrate_legacy_keys()  # khoá cũ nhập ở Thư viện chiến dịch → Cài đặt
        self._campaigns = CampaignRunner(settings, self._license, self._facebook, self._emit,
                                         images=self._images, videos=self._runner, ads=self._ads)
        from .cast import CastRunner
        self._cast = CastRunner(settings, self._license, self._emit, images=self._images)  # Nhân vật & Layout
        from .studio import StudioRunner
        self._studio = StudioRunner(settings, self._license, self._emit, images=self._images, videos=self._runner)
        self._studio.cast = self._cast  # Studio dùng nhân vật / layout cố định
        from .workflow.runner import WorkflowRunner
        self._workflows = WorkflowRunner(settings, self._license, self._emit, facebook=self._facebook, ads=self._ads,
                                         studio=self._studio)

    # ------------------------------------------------------------------ workflow (kéo thả block)
    def _wf(self, key: str, fn, *args) -> dict:
        from .workflow.store import WorkflowError

        try:
            return _ok(**{key: fn(*args)})
        except (WorkflowError, ValueError, OSError) as exc:
            return _fail(exc)

    def wf_meta(self) -> dict:
        from .workflow import nodes, store

        return _ok(meta=nodes.meta(), presets=store.presets(), running=self._workflows.running_ids())

    def wf_list(self) -> dict:
        from .workflow import store

        items = store.list_workflows()
        for wf in items:  # số lần chạy (đọc thư mục kết quả, tối đa 50 lần gần nhất)
            try:
                wf["runs"] = len(store.list_runs(settings.output_dir, wf["id"]))
            except store.WorkflowError:
                wf["runs"] = 0
        return _ok(workflows=items, running=self._workflows.running_ids(), presets=store.presets())

    def wf_get(self, wf_id: str) -> dict:
        from .workflow import runner, store

        def run():
            wf = store.get(wf_id)
            return {**wf, "issues": runner.validate(wf), "running": wf_id in self._workflows.running_ids()}

        return self._wf("workflow", run)

    def wf_save(self, wf: dict) -> dict:
        from .workflow import runner, store

        def run():
            saved = store.save(wf)
            return {**saved, "issues": runner.validate(saved), "running": saved["id"] in self._workflows.running_ids()}

        return self._wf("workflow", run)

    def wf_validate(self, wf: dict) -> dict:
        from .workflow import runner, store

        return self._wf("issues", lambda: runner.validate({**wf, **store.clean(wf)}))

    def wf_from_preset(self, preset_id: str) -> dict:
        from .workflow import store

        return self._wf("workflow", store.from_preset, preset_id)

    def wf_duplicate(self, wf_id: str) -> dict:
        from .workflow import store

        return self._wf("workflow", store.duplicate, wf_id)

    def wf_delete(self, wf_id: str) -> dict:
        from .workflow import store

        if wf_id in self._workflows.running_ids():
            return _fail(ValueError("Workflow đang chạy — dừng trước khi xoá"))
        return self._wf("deleted", lambda: store.delete(wf_id) or True)

    def wf_run(self, wf_id: str, overrides: dict | None = None) -> dict:
        return self._wf("result", self._workflows.run, wf_id, overrides or {})

    def wf_video_templates(self) -> dict:
        """Template video AI dùng được trong block Tạo video (của app + của bạn) và danh sách nhóm."""
        from .templates_registry import CATEGORIES

        items = [t.as_dict() for t in registry.listed() if t.kind == "ai_video"]
        for t in items:
            t["attachments"] = [{k: a.get(k) for k in ("key", "label", "hint", "role", "prompt", "required", "video", "keep_video", "send_video")}
                                | {"has_default": bool(a.get("default"))} for a in t["attachments"]]
            t["steps"] = [{"key": s["key"], "label": s.get("label", s["key"]), "engine": s.get("engine", ""),
                           "aspect": s.get("aspect", ""), "prompt": s.get("prompt", ""),
                           "inputs": [{"key": i["key"], "role": i.get("role", "")} for i in s.get("inputs", [])]}
                          for s in t.pop("image_steps")]
            t["video_inputs"] = [{"key": i["key"], "role": i.get("role", "")} for i in t.get("video_inputs") or []]
        items.sort(key=lambda t: (not t["user"], t["name"].lower()))
        return _ok(templates=items, categories=[{"id": c["id"], "name": c["name"], "icon": c["icon"]} for c in CATEGORIES])

    def wf_save_video_template(self, data: dict) -> dict:
        try:
            return _ok(template=registry.save_user_template(data or {}).as_dict())
        except (ValueError, OSError) as exc:
            return _fail(exc)

    def wf_delete_video_template(self, template_id: str) -> dict:
        try:
            registry.delete_user_template(template_id)
            return _ok()
        except (ValueError, OSError) as exc:
            return _fail(exc)

    def wf_test_plan(self, wf_id: str, node_id: str, fresh: bool = False) -> dict:
        """Xem trước khi chạy thử 1 block: block nào chạy thật, block nào dùng lại kết quả cũ."""
        return self._wf("plan", self._workflows.plan_public, wf_id, node_id, bool(fresh))

    def wf_run_node(self, wf_id: str, node_id: str, fresh: bool = False) -> dict:
        """Chạy thử 1 block (kèm các block phía trước còn thiếu kết quả)."""
        return self._wf("result", self._workflows.run, wf_id, {}, node_id, bool(fresh))

    def wf_approve(self, wf_id: str, run_id: str, node_id: str, approved: bool, caption: str | None = None) -> dict:
        return self._wf("result", self._workflows.approve, wf_id, run_id, node_id, bool(approved), caption)

    def wf_fb_options(self) -> dict:
        """Fanpage đã kết nối + tài khoản quảng cáo cho ô chọn của block Facebook (không trả token)."""
        pages = [{"id": p["id"], "name": p["name"]} for p in self._facebook.state().get("pages", []) if p.get("connected")]
        accounts, error = [], ""
        try:
            accounts = [{"id": a["id"], "name": a["name"] or a["account_id"], "currency": a.get("currency", ""),
                         "active": a.get("active")} for a in self._ads.accounts()]
        except Exception as exc:  # chưa có quyền ads_read / chưa kết nối — block Tạo quảng cáo sẽ báo
            error = str(exc)
        return _ok(pages=pages, accounts=accounts, accounts_error=error)

    def wf_cancel(self, wf_id: str) -> dict:
        return _ok(cancelled=self._workflows.cancel(wf_id))

    def wf_runs(self, wf_id: str) -> dict:
        from .workflow import store

        return self._wf("runs", store.list_runs, settings.output_dir, wf_id)

    def wf_run_get(self, wf_id: str, run_id: str) -> dict:
        from .workflow import store

        return self._wf("run", lambda: self._workflows.public(store.get_run(settings.output_dir, wf_id, run_id)))

    def wf_open_run(self, wf_id: str, run_id: str) -> dict:
        from .workflow import store

        def run():
            store.get_run(settings.output_dir, wf_id, run_id)
            os.startfile(store.runs_root(settings.output_dir, wf_id) / run_id)
            return True

        return self._wf("opened", run)

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
            "video": ("Video (*.mp4;*.mov;*.webm;*.m4v)",),
            "images_multi": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp)",),
            "seedance_images": ("Ảnh (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.avif)",),
            "media": ("Ảnh và video (*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.m4v)",),
            "srt": ("Phụ đề SRT (*.srt)",),
            "audio": ("Âm thanh (*.mp3;*.wav;*.m4a;*.aac;*.ogg;*.flac)",),
        }.get(kind)
        if file_types is None:
            return []
        open_dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        result = self._window.create_file_dialog(open_dialog, allow_multiple=kind in ("products", "images_multi", "seedance_images"), file_types=file_types)
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

    # ------------------------------------------------------------------ Seedance Studio Pro
    def seedance_state(self) -> dict:
        return _ok(studio=self._seedance.snapshot())

    def seedance_action(self, action: str, data=None) -> dict:
        data = data or {}
        studio = self._seedance
        try:
            result = None
            if action == "config":
                result = studio.save_config(data)
            elif action == "import":
                result = studio.import_prompts(data.get("text", ""), data.get("filename", ""))
            elif action == "images":
                result = studio.import_images(data.get("paths", []))
            elif action == "image_data":
                result = studio.import_image_data(data.get("name", ""), data.get("dataUrl", ""))
            elif action == "job":
                studio.change_job(data["id"], data["action"], data.get("text", ""))
            elif action == "image":
                studio.change_image(data["id"], data["action"])
            elif action == "start":
                result = studio.start(data.get("config", {}), data.get("ids"))
            elif action == "history":
                result = studio.start(data.get("config", {}), history_url=data.get("url", ""))
            elif action == "stop":
                studio.stop()
            elif action == "download":
                studio.download(data["id"])
            elif action == "watermark":
                studio.remove_watermark(data["id"], data.get("rectangle", {}))
            elif action == "open":
                studio.open_media(data["id"])
            elif action == "link":
                studio.link_media(data["id"], data["sceneId"])
            elif action == "zip":
                studio.export_zip(data.get("ids"))
            elif action == "export":
                result = studio.export_project()
            else:
                raise ValueError("Thao tác Studio không hợp lệ")
            return _ok(result=result, studio=studio.snapshot())
        except Exception as exc:
            return _fail(exc)

    # ------------------------------------------------------------------ hàng đợi tác vụ (kind = video | image)
    def _pool(self, kind: str):
        if kind == "campaign":
            return self._campaigns.pool
        if kind == "workflow":
            return self._workflows.pool
        if kind == "studio":
            return self._studio.pool
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
            res = self._facebook.post(page_id, message, file_path)
        except (FacebookError, OSError) as exc:
            return _fail(exc)
        try:  # lưu vào Quản lý bài đăng để sửa / đăng lại; lỗi lưu không ảnh hưởng bài đã đăng
            from .posts import who

            self._posts.record(source="quick", source_name=res.get("page", ""), kind="text" if not file_path else "feed",
                               caption=message, files=[file_path] if file_path else [], page_id=page_id,
                               page=res.get("page", ""), result=res, by=who())
        except Exception:
            log.exception("Không lưu được bài vào Quản lý bài đăng")
        return _ok(post=res)

    # ------------------------------------------------------------------ quản lý bài đăng (lưu + đăng lại)
    def _post_call(self, key: str, fn, *args) -> dict:
        from .facebook import FacebookError
        from .posts import PostError

        try:
            return _ok(**{key: fn(*args)})
        except (PostError, FacebookError, OSError) as exc:
            return _fail(exc)

    def post_list(self) -> dict:
        return _ok(posts=self._posts.list(), types=[{"value": k, "label": v} for k, v in POST_TYPES.items()],
                   schedulable=list(SCHEDULABLE))

    def post_save(self, data: dict) -> dict:
        """Tạo / sửa bài (nháp hoặc bài đã đăng — sửa rồi đăng lại)."""
        return self._post_call("post", self._posts.save, data or {})

    def post_delete(self, pid: str) -> dict:
        return self._post_call("ok", lambda: self._posts.delete(pid) or True)

    def post_publish(self, pid: str, page_ids: list, confirmed: bool = False, scheduled_at: int | None = None) -> dict:
        """Đăng (lại) bài — chỉ khi người dùng đã bấm xác nhận (confirmed=True); ghi lại ai xác nhận, lúc nào."""
        return self._post_call("result", self._posts.publish, pid, page_ids or [], confirmed is True,
                               int(scheduled_at) if scheduled_at else None)

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

    # ------------------------------------------------------------------ chiến dịch (phòng marketing AI)
    def _camp(self, key: str, fn, *args) -> dict:
        from .campaign.store import CampaignError

        try:
            return _ok(**{key: fn(*args)})
        except (CampaignError, ValueError, OSError) as exc:
            return _fail(exc)

    def _cdir(self, cid: str):
        from .campaign import store

        return store.campaign_dir(settings.output_dir, cid)

    def campaign_overview(self) -> dict:
        from .campaign import ai, store

        return _ok(campaigns=store.list_campaigns(settings.output_dir), stats=store.stats(settings.output_dir),
                   running=self._campaigns.running_ids(), keys=ai.key_status(), statuses=store.STATUSES,
                   stages=[{"key": k, "name": n, "role": r, "file": f} for k, n, r, f in store.STAGES])

    def campaign_create(self, form: dict) -> dict:
        return self._camp("result", self._campaigns.create, form)

    def campaign_get(self, cid: str) -> dict:
        import json as _json

        from .campaign import store
        from .campaign.store import CampaignError

        try:
            cdir = self._cdir(cid)
            data = store.load(cdir)
        except CampaignError as exc:
            return _fail(exc)
        rel = lambda p: f"/media/_campaigns/{cid}/{p}"  # noqa: E731
        files = {}
        for name in ("00-brief.md", "01-y-tuong.md", "02-chon-y-tuong.md", "03-content.md", "04-chon-content.md",
                     "06-danh-gia.md", "08-dang-bai/ke-hoach-dang.md", "08-dang-bai/da-dang.md", "thong-tin-web.md",
                     "bao-cao.md", "05-hinh-anh/prompt-ai.md", "05-hinh-anh/y-tuong-anh.md"):
            path = cdir / name
            files[name] = path.read_text("utf-8") if path.exists() else ""
        from .campaign.media import EXTRA_IMAGES, IMAGE_KEYS

        url = lambda p: f"{rel(p)}?v={int((cdir / p).stat().st_mtime)}" if (cdir / p).exists() else ""  # noqa: E731
        images = []
        for key in (*IMAGE_KEYS, *(k for k in EXTRA_IMAGES if k in (data.get("images") or {}))):
            info = (data.get("images") or {}).get(key, {})
            images.append({**info, "key": key, "exists": (cdir / "05-hinh-anh" / f"{key}.png").exists(),
                           "url": url(f"05-hinh-anh/{key}.png"),
                           "variant_urls": [url(f"05-hinh-anh/{key}-pa{i}.png") for i in range(1, int(info.get("variants") or 0) + 1)
                                            if (cdir / "05-hinh-anh" / f"{key}-pa{i}.png").exists()]})
        videos = [{**v, "url": url(v["file"])} for v in sorted((data.get("videos") or {}).values(), key=lambda v: v["key"])
                  if (cdir / v["file"]).exists()]
        if not videos and (cdir / "07-video" / "video.mp4").exists():  # chiến dịch cũ: 1 video
            videos = [{**(data.get("video") or {}), "key": "video", "label": "Video", "file": "07-video/video.mp4",
                       "url": url("07-video/video.mp4")}]
        inputs = {kind: [rel(f"inputs/{sub}/{f}") for f in (data.get("inputs") or {}).get(kind, [])]
                  for kind, sub in (("products", "san-pham"), ("refs", "tham-chieu"), ("models", "nguoi-mau"))}
        logs = []
        log_file = cdir / "nhat-ky.jsonl"
        if log_file.exists():
            for line in log_file.read_text("utf-8").splitlines()[-400:]:
                try:
                    logs.append(_json.loads(line))
                except ValueError:
                    continue
        pdf = cdir / "03-content.pdf"
        pages = [{"id": p["id"], "name": p["name"], "category": p.get("category", "")}
                 for p in self._facebook.state().get("pages", []) if p.get("connected")]
        return _ok(campaign={**data, "files": files, "images_view": images, "videos_view": videos, "inputs_view": inputs,
                             "logs": logs,
                             "running": cid in self._campaigns.running_ids(),
                             "content_html": rel("03-content.html") if (cdir / "03-content.html").exists() else "",
                             "has_pdf": pdf.exists(), "folder": str(cdir), "fb_pages": pages})

    def campaign_cancel(self, cid: str) -> dict:
        return _ok(cancelled=self._campaigns.cancel(cid))

    def campaign_resume(self, cid: str) -> dict:
        return self._camp("task", self._campaigns.resume, cid)

    def campaign_answer(self, cid: str, answers: str) -> dict:
        return self._camp("task", self._campaigns.answer_brief, cid, answers)

    def campaign_pick_idea(self, cid: str, number: int) -> dict:
        return self._camp("task", self._campaigns.pick_idea, cid, int(number))

    def campaign_approve_manually(self, cid: str) -> dict:
        return self._camp("task", self._campaigns.approve_manually, cid)

    def campaign_rerun_from(self, cid: str, stage: str) -> dict:
        return self._camp("result", self._campaigns.new_version, cid, stage)

    def campaign_duplicate(self, cid: str) -> dict:
        return self._camp("result", self._campaigns.duplicate, cid)

    def campaign_rewrite_content(self, cid: str, note: str = "") -> dict:
        return self._camp("task", self._campaigns.start, cid, "", "content", note or "Viết lại content mới, cùng ý tưởng.")

    def campaign_redraw(self, cid: str, key: str, note: str = "") -> dict:
        if key not in ("c1-a", "c1-b"):
            return _fail(ValueError("Ảnh không hợp lệ"))
        return self._camp("task", self._campaigns.start, cid, "", "image", note, key)

    def campaign_remake_video(self, cid: str) -> dict:
        return self._camp("task", self._campaigns.start, cid, "", "video")

    def campaign_save_content(self, cid: str, text: str) -> dict:
        """Sửa trực tiếp content → tự xuất lại HTML/PDF (bản cũ cất vào _cu/)."""
        from .campaign import store, tools

        def run():
            cdir = self._cdir(cid)
            if not text.strip():
                raise ValueError("Content trống")
            store.write_file(cdir, "03-content.md", text)
            html = store.write_file(cdir, "03-content.html", tools.md_to_html(text, f"Content · {store.load(cdir)['name']}"))
            store.keep_old(cdir / "03-content.pdf")
            tools.html_to_pdf(html, cdir / "03-content.pdf")
            self._campaigns._log(cdir, "Người dùng sửa content — đã xuất lại HTML/PDF")
            return True

        return self._camp("saved", run)

    def campaign_publish(self, cid: str, items: list, confirmed: bool = False) -> dict:
        from .facebook import FacebookError

        try:
            return _ok(result=self._campaigns.publish(cid, items, confirmed is True))
        except FacebookError as exc:
            return _fail(exc)
        except Exception as exc:  # CampaignError / lỗi đọc file
            return _fail(exc)

    def campaign_open(self, cid: str, rel: str = "") -> dict:
        def run():
            cdir = self._cdir(cid)
            target = (cdir / rel).resolve() if rel else cdir
            if not target.is_relative_to(cdir.resolve()) or not target.exists():
                raise ValueError("Không tìm thấy file")
            os.startfile(target)
            return True

        return self._camp("opened", run)

    def campaign_zip(self, cid: str) -> dict:
        import shutil as _shutil

        from .campaign import store

        def run():
            cdir = self._cdir(cid)
            zip_dir = store.root(settings.output_dir) / "_zip"
            zip_dir.mkdir(parents=True, exist_ok=True)
            path = _shutil.make_archive(str(zip_dir / cid), "zip", cdir)
            os.startfile(zip_dir)
            return path

        return self._camp("path", run)

    def campaign_history(self) -> dict:
        from .campaign import store

        calls = store.ai_calls()
        per = {}
        for c in store.list_campaigns(settings.output_dir):
            per[c["id"]] = {"name": c["name"], "usd": (c.get("cost") or {}).get("usd", 0),
                            "tokens_in": (c.get("cost") or {}).get("tokens_in", 0),
                            "tokens_out": (c.get("cost") or {}).get("tokens_out", 0),
                            "images": (c.get("cost") or {}).get("images") or (c.get("cost") or {}).get("grok_images", 0),
                            "videos": (c.get("cost") or {}).get("videos", 0),
                            "calls": (c.get("cost") or {}).get("calls", 0), "created_at": c.get("created_at")}
        return _ok(posts=store.post_history(), calls=calls[:300], per_campaign=per)

    # ---- thư viện chiến dịch
    # ---- Studio: ý tưởng → storyboard → cảnh → video dài
    def _st(self, key: str, fn, *args) -> dict:
        from .studio import StudioError

        try:
            return _ok(**{key: fn(*args)})
        except (StudioError, ValueError, OSError) as exc:
            return _fail(exc)

    def studio_meta(self) -> dict:
        from .studio import meta

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

        from .pipeline import transitions

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

        from .pipeline.tts import role_voice, synthesize

        text = " ".join(str(text or "").split())[:300] or "Xin chào, đây là giọng đọc thử."
        tts_voice, tts_rate, pitch = role_voice(str(speaker or ""), str(voice or "vi-VN-HoaiMyNeural"), str(rate or "+0%"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "preview.mp3"
            try:
                synthesize(text, tts_voice, tts_rate, out, retries=2, pitch=pitch)
            except Exception as exc:  # mạng / edge-tts lỗi
                return _fail(exc)
            return _ok(data="data:audio/mpeg;base64," + base64.b64encode(out.read_bytes()).decode())

    # ------------------------------------------------------------------ nhân vật & layout cố định
    def _cast_call(self, key: str, fn, *args) -> dict:
        from .cast import CastError

        try:
            return _ok(**{key: fn(*args)})
        except (CastError, OSError, ValueError) as exc:
            return _fail(exc)

    def cast_meta(self) -> dict:
        from .cast import CHARACTER_PRESETS, MAX_COMBO_CHARS, MAX_PRODUCTS, UI_ELEMENTS
        from .content_writer import models

        return _ok(presets=[{"key": k, "label": v[0], "aspect": v[1]} for k, v in CHARACTER_PRESETS.items()],
                   ui_elements=[{"key": k, "label": v[0]} for k, v in UI_ELEMENTS.items()], max_combo_chars=MAX_COMBO_CHARS,
                   max_products=MAX_PRODUCTS,
                   image_engines={k: {"name": v["name"], "browser": bool(v.get("browser")), "aspects": v["aspects"],
                                      "counts": v["counts"]} for k, v in IMAGE_ENGINES.items()},
                   text_models=models(settings))

    def cast_list(self, kind: str) -> dict:
        return self._cast_call("items", self._cast.list, kind)

    def cast_get(self, kind: str, cid: str) -> dict:
        return self._cast_call("item", self._cast.get, kind, cid)

    def cast_create(self, kind: str, data: dict | None = None) -> dict:
        return self._cast_call("item", self._cast.create, kind, data or {})

    def cast_save(self, kind: str, cid: str, data: dict) -> dict:
        return self._cast_call("item", self._cast.save, kind, cid, data or {})

    def cast_delete(self, kind: str, cid: str) -> dict:
        return self._cast_call("ok", lambda: self._cast.delete(kind, cid) or True)

    def cast_duplicate(self, kind: str, cid: str) -> dict:
        return self._cast_call("item", self._cast.duplicate, kind, cid)

    def cast_add_photos(self, kind: str, cid: str, files: list | None = None, role: str = "") -> dict:
        """role = "product": ảnh sản phẩm của bộ kết hợp (nhân vật cầm / giới thiệu sản phẩm)."""
        files = files if files is not None else self.pick_files("images_multi")
        if not files:
            return _ok(item=None)
        return self._cast_call("item", self._cast.add_photos, kind, cid, files, str(role or ""))

    def cast_tasks(self) -> dict:
        """Tác vụ của màn Nhân vật & Layout (đang chạy + gần đây) — thẻ Tiến trình."""
        return _ok(tasks=self._cast.pool.list())

    def cast_task_logs(self, task_id: str) -> dict:
        return _ok(logs=self._cast.pool.logs(str(task_id or "")))

    def cast_set_image(self, kind: str, cid: str, name: str, opts: dict) -> dict:
        opts = opts or {}
        return self._cast_call("item", self._cast.set_image, kind, cid, name, opts.get("starred"), opts.get("base"),
                               bool(opts.get("remove")))

    def cast_presets(self, kind: str, cid: str) -> dict:
        return self._cast_call("presets", self._cast.presets, kind, cid)

    def cast_describe(self, kind: str, cid: str, options: dict) -> dict:
        return self._cast_call("task", self._cast.describe, kind, cid, options or {})

    def cast_generate(self, kind: str, cid: str, req: dict) -> dict:
        return self._cast_call("task", self._cast.generate, kind, cid, req or {})

    def cast_cancel(self, task_id: str = "") -> dict:
        return _ok(cancelled=self._cast.pool.cancel(task_id))

    def hyperframes_status(self) -> dict:
        """Node.js / ffprobe / HyperFrames đã sẵn sàng chưa (hiện ở ✨ Hậu kỳ AI → Kiểu HyperFrames)."""
        from .pipeline import hyperframes

        return _ok(status=hyperframes.status())

    def offer_answer(self, rid: str, choice: str, text: str = "", always: bool = False) -> dict:
        """Form duyệt đề xuất của model: choice = agree | custom (kèm text) | stop; always = từ giờ tự đồng ý."""
        from .llm import offers

        if not offers.answer(rid, choice, text, always):
            return _fail("Form duyệt đã hết hạn (đã tự đồng ý) hoặc tác vụ đã dừng")
        return _ok()

    def whiteboard_status(self) -> dict:
        """Bộ dựng srt-whiteboard-animation đã tải + cài chưa (lần đầu dựng sẽ tự cài)."""
        from .pipeline import whiteboard

        return _ok(status=whiteboard.status())

    def whiteboard_make_srt(self, text: str, voice: str = "", rate: str = "") -> dict:
        """Tự tạo SRT từ kịch bản thường (giọng AI đọc để lấy mốc) — trả về SRT + file giọng đọc khớp mốc."""
        from .pipeline import whiteboard
        from .pipeline.tts import TTSError

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

        from .pipeline import whiteboard

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

        from .pipeline import ref_video

        try:
            result = ref_video.analyze(str(source or ""), settings, model=str(model or "gemini_browser"),
                                       profile=str(profile or ""), show_browser=bool(show_browser),
                                       log=lambda m, level="info": log.info("ref video: %s", m))
        except Exception as exc:  # tải link / model / ffmpeg lỗi → báo nguyên nhân cho người dùng
            return _fail(exc)
        rel = Path(result["sheet"]).relative_to(settings.output_dir).as_posix() if result.get("sheet") else ""
        return _ok(result={**result, "sheet_url": f"/media/{rel}" if rel else ""})

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

    def studio_cancel(self, pid: str) -> dict:
        return _ok(cancelled=self._studio.cancel(pid))

    def studio_delete(self, pid: str) -> dict:
        return self._st("deleted", lambda: self._studio.delete(pid) or True)

    # ---- Tạo content bài viết
    def content_models(self) -> dict:
        from . import content_writer as cw
        from .campaign import store

        products = [{k: p.get(k, "") for k in ("id", "name", "code", "spec", "price", "sale_price", "promo", "hotline",
                                                 "label", "links")} for p in store.products()]
        return _ok(models=cw.models(settings), fields={k: {"label": v[0], "required": v[1]} for k, v in cw.FIELDS.items()},
                   template=cw.DEFAULT_TEMPLATE, max_variants=cw.MAX_VARIANTS, products=products)

    def content_generate(self, form: dict) -> dict:
        from . import content_writer as cw

        try:
            return _ok(result=cw.generate(form, settings))
        except (cw.ContentError, ValueError) as exc:
            return _fail(exc)
        except Exception as exc:  # lỗi trình duyệt / mạng của model
            log.exception("Tạo content lỗi")
            return _fail(exc)

    def content_history(self) -> dict:
        from . import content_writer as cw

        return _ok(items=cw.history())

    def content_delete(self, entry_id: str) -> dict:
        from . import content_writer as cw

        return _ok(items=cw.delete_history(entry_id))

    def camp_library(self) -> dict:
        from .campaign import ai, store

        lib = store.library()
        for rid, role in lib["roles"].items():
            role["versions"] = [{"at": v["at"], "chars": len(v.get("prompt", ""))} for v in role.get("versions", [])]
        return _ok(library=lib, keys=ai.key_status(), models=ai.MODEL_CHOICES,
                   image_engine=self._campaigns.default_image_engine())

    def camp_save_product(self, item: dict, new_images: list | None = None) -> dict:
        from .campaign import store

        return self._camp("products", store.save_product, item, new_images or [])

    def camp_delete_product(self, pid: str) -> dict:
        from .campaign import store

        return self._camp("products", store.delete_product, pid)

    def camp_add_refs(self, files: list, tags: list) -> dict:
        from .campaign import store

        return self._camp("refs", store.add_refs, files, tags)

    def camp_update_ref(self, file: str, tags: list) -> dict:
        from .campaign import store

        return self._camp("refs", store.update_ref, file, tags)

    def camp_delete_ref(self, file: str) -> dict:
        from .campaign import store

        return self._camp("refs", store.delete_ref, file)

    def camp_save_model(self, item: dict, image: str = "") -> dict:
        from .campaign import store

        return self._camp("models", store.save_model, item, image)

    def camp_delete_model(self, mid: str) -> dict:
        from .campaign import store

        return self._camp("models", store.delete_model, mid)

    def camp_save_styles(self, items: list) -> dict:
        from .campaign import store

        return self._camp("styles", store.save_styles, items)

    def camp_save_template(self, text: str) -> dict:
        from .campaign import store

        return self._camp("template", store.save_content_template, text)

    def camp_save_role(self, rid: str, prompt=None, model=None, effort=None) -> dict:
        from .campaign import store

        def run():
            roles = store.save_role(rid, prompt, model, effort)
            return {k: {**v, "versions": [{"at": x["at"], "chars": len(x.get("prompt", ""))} for x in v.get("versions", [])]}
                    for k, v in roles.items()}

        return self._camp("roles", run)

    def camp_role_version(self, rid: str, index: int) -> dict:
        from .campaign import store

        def run():
            versions = store.roles()[rid].get("versions", [])
            return versions[int(index)]["prompt"]

        return self._camp("prompt", run)

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
