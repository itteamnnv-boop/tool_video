"""Persistent scheduler, isolated profile workers and streaming MP4/ZIP exports."""
import hashlib
import json
import shutil
import threading
import time
import zipfile
from pathlib import Path

import requests

from ..osutil import open_path
from .. import browser_profiles
from ..paths import DATA_DIR
from .domain import PRESETS, StudioError, distribute, normalize_config, parse_prompts
from .provider import BrowserAdapter, allowed_url
from .notices import ACCOUNT_LIMIT_CODES
from .store import Store, now, uid

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".gif": "image/gif", ".avif": "image/avif"}
RETRYABLE = {"failed", "cancelled", "interrupted"}


class Studio:
    def __init__(self, settings, license_manager, emit, root=None, adapter_factory=BrowserAdapter):
        self.settings, self.license, self.emit = settings, license_manager, emit
        self.store = Store(root or DATA_DIR / "seedance")
        self.adapter_factory = adapter_factory
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.running = False
        self.exporting = False
        self.workers = []
        self.downloads = set()
        self.cleaning = set()
        self.account_limits = {}

    def snapshot(self):
        with self.lock:
            jobs, images, media = (self.store.list(k) for k in ("jobs", "images", "media"))
            return {"config": self.store.config(), "jobs": jobs, "images": images, "media": media,
                    "events": self.store.list("events")[-300:], "running": self.running, "exporting": self.exporting,
                    "workers": list(self.workers), "presets": {k: v[0] for k, v in PRESETS.items()},
                    "cleaning": list(self.cleaning),
                    "accountLimits": dict(self.account_limits),
                    "presetPrompts": {k: v[1] for k, v in PRESETS.items()},
                    "profiles": browser_profiles.list_profiles(),
                    "counts": {"total": len(jobs), "queued": sum(j["status"] == "queued" for j in jobs),
                               "submitted": sum(bool(j.get("submittedAt")) for j in jobs),
                               "ready": len({m.get("sceneId") for m in media if m.get("sceneId")}),
                               "downloaded": sum(bool(m.get("path") and Path(m["path"]).is_file()) for m in media),
                               "failed": sum(j["status"] in RETRYABLE for j in jobs)}}

    def publish(self):
        self.emit("seedance", self.snapshot())

    def event(self, message, job_id="", level="info", code="", **details):
        self.store.event(message, job_id=job_id, level=level, code=code, **details)

    def check(self):
        if self.stop_event.is_set():
            raise StudioError("CANCELLED", "Đã dừng thao tác tự động")

    def check_account(self, profile):
        self.check()
        with self.lock:
            notice = self.account_limits.get(profile)
        if notice:
            raise StudioError("CANCELLED", "Đã dừng gửi thêm bằng profile này do giới hạn tài khoản: " + notice["code"])

    def _idle(self):
        if self.running:
            raise ValueError("Dừng batch hiện tại trước khi thay đổi hàng đợi")

    def save_config(self, values):
        cfg = normalize_config(values)
        self.store.put("settings", {"id": "config", "values": cfg})
        return cfg

    def import_prompts(self, text, filename=""):
        rows = parse_prompts(text, filename)
        with self.lock:
            self._idle()
            if len(self.store.list("jobs")) + len(rows) > 2000:
                raise ValueError("Tối đa 2.000 cảnh trong studio; xoá cảnh cũ trước khi nhập thêm")
            for row in rows:
                self.store.put("jobs", {"id": uid(), **row, "status": "queued", "attempt": 0,
                                        "batchId": "", "imageId": "", "createdAt": now(), "error": "", "code": ""})
            self.event(f"Đã nhập {len(rows)} cảnh từ {filename or 'văn bản'}")
        self.publish()
        return len(rows)

    def import_images(self, paths):
        from PIL import Image

        with self.lock:
            self._idle()
            existing = self.store.list("images")
            if len(existing) + len(paths) > 200:
                raise ValueError("Thư viện tối đa 200 ảnh")
            folder = self.store.root / "images"
            folder.mkdir(exist_ok=True)
            errors, count = [], 0
            for raw in paths:
                source = Path(raw)
                try:
                    suffix = source.suffix.lower()
                    if suffix not in IMAGE_TYPES or not source.is_file():
                        raise ValueError("Định dạng ảnh không được hỗ trợ")
                    if source.stat().st_size > 25 * 1024 * 1024:
                        raise ValueError("Ảnh vượt quá 25 MB")
                    with Image.open(source) as im:
                        im.verify()
                    id = uid()
                    target = folder / (id + suffix)
                    shutil.copyfile(source, target)
                    self.store.put("images", {"id": id, "name": source.name, "path": str(target),
                                             "url": "/seedance-image/" + target.name, "size": target.stat().st_size,
                                             "type": IMAGE_TYPES[suffix], "order": len(existing) + count,
                                             "status": "queued", "addedAt": now()})
                    count += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"{source.name}: {exc}")
            self.event(f"Đã nhập {count} ảnh" + ("; " + "; ".join(errors) if errors else ""))
        self.publish()
        return {"count": count, "errors": errors}

    def import_image_data(self, name, data_url):
        import base64

        suffix = Path(str(name)).suffix.lower()
        if suffix not in IMAGE_TYPES or not isinstance(data_url, str) or len(data_url) > 36 * 1024 * 1024:
            raise ValueError("Ảnh không hợp lệ hoặc vượt quá 25 MB")
        if not data_url.startswith("data:image/") or "," not in data_url:
            raise ValueError("Dữ liệu ảnh không hợp lệ")
        folder = self.store.root / "imports"
        folder.mkdir(exist_ok=True)
        temp = folder / (uid() + suffix)
        try:
            payload = base64.b64decode(data_url.split(",", 1)[1], validate=True)
            if len(payload) > 25 * 1024 * 1024:
                raise ValueError("Ảnh vượt quá 25 MB")
            temp.write_bytes(payload)
            result = self.import_images([str(temp)])
            if result["count"]:
                image = self.store.list("images")[-1]
                self.store.update("images", image["id"], name=Path(str(name)).name)
                self.publish()
            return result
        finally:
            temp.unlink(missing_ok=True)

    def change_job(self, id, action, text=""):
        with self.lock:
            self._idle()
            jobs = self.store.list("jobs") if id == "all" else [self.store.get("jobs", id)]
            for job in filter(None, jobs):
                if action == "delete":
                    self.store.delete("jobs", job["id"])
                elif action == "retry" and job["status"] in RETRYABLE:
                    media = [m for m in self.store.list("media") if m.get("sceneId") == job["id"]]
                    if media:
                        downloaded = any(m.get("path") and Path(m["path"]).is_file() for m in media)
                        self.store.update("jobs", job["id"], status="completed" if downloaded else "media_ready", error="", code="")
                    else:
                        self.store.update("jobs", job["id"], status="queued", error="", code="", submittedAt=None, submissionAttempted=False)
                elif action == "edit" and job["status"] == "queued" and text.strip():
                    self.store.update("jobs", job["id"], text=text.strip(), title=text.strip().splitlines()[0][:100])
            self.publish()

    def change_image(self, id, action):
        with self.lock:
            self._idle()
            images = sorted(self.store.list("images"), key=lambda x: x["order"])
            selected = images if id == "all" else [i for i in images if i["id"] == id]
            if action == "delete":
                for image in selected:
                    if any(j.get("imageId") == image["id"] and j["status"] == "queued" for j in self.store.list("jobs")):
                        raise ValueError("Ảnh đang ghép với cảnh chờ; xoá cảnh đó trước")
                for image in selected:
                    Path(image["path"]).unlink(missing_ok=True)
                    self.store.delete("images", image["id"])
            elif action in ("up", "down") and selected:
                index = images.index(selected[0])
                other = index + (-1 if action == "up" else 1)
                if 0 <= other < len(images):
                    images[index], images[other] = images[other], images[index]
                    for order, image in enumerate(images):
                        self.store.update("images", image["id"], order=order)
            elif action == "reset":
                for image in selected:
                    self.store.update("images", image["id"], status="queued")
            self.publish()

    def link_media(self, media_id, scene_id):
        with self.lock:
            self._idle()
            media = self.store.get("media", media_id)
            job = self.store.get("jobs", scene_id)
            if not media or not job:
                raise ValueError("Không tìm thấy video hoặc cảnh")
            if self.exporting or media_id in self.downloads:
                raise ValueError("Chờ tải/xuất video xong trước khi thay đổi cảnh liên kết")
            old_scene = media.get("sceneId")
            self.store.update("media", media_id, sceneId=scene_id, title=job["title"])
            if old_scene and old_scene != scene_id and self.store.get("jobs", old_scene):
                remaining = [m for m in self.store.list("media") if m.get("sceneId") == old_scene]
                if not remaining:
                    self.store.update("jobs", old_scene, status="interrupted", mediaId="", code="MEDIA_UNLINKED", error="Video đã được gắn sang cảnh khác; kiểm tra lại cuộc trò chuyện")
            downloaded = bool(media.get("path") and Path(media["path"]).is_file())
            self.store.update("jobs", scene_id, status="completed" if downloaded else "media_ready", mediaId=media_id,
                              chatUrl=media.get("chatUrl", ""), error="", code="")
            self.event("Đã gắn video từ thư viện với cảnh", scene_id)
        self.publish()

    def start(self, config, ids=None, history_url=None):
        with self.lock:
            self._idle()
            self.license.require_active()
            cfg = normalize_config(config)
            profiles = {p["id"]: p for p in browser_profiles.list_profiles()}
            for id in cfg["profileIds"]:
                if id not in profiles or cfg["provider"] not in profiles[id]["sites"]:
                    raise ValueError(f"Profile {id} chưa được gán cho {cfg['provider']}")
            jobs = [j for j in self.store.list("jobs") if j["status"] == "queued" and (not ids or j["id"] in ids)]
            if history_url is None and not jobs:
                raise ValueError("Chưa có cảnh đang chờ; nhập kịch bản hoặc thử lại cảnh lỗi")
            if history_url is not None and not allowed_url(history_url, cfg["provider"]):
                raise ValueError("Dán URL cuộc trò chuyện HTTPS trên đúng nhà cung cấp đã chọn")
            if cfg["mode"] == "image" and history_url is None:
                images = sorted((i for i in self.store.list("images") if i["status"] == "queued"), key=lambda x: x["order"])
                paired, unused = [], list(images)
                # Existing pairs survive a cancelled batch or an explicit retry.
                reserved = {j.get("imageId") for j in jobs if j.get("imageId")}
                unused = [i for i in unused if i["id"] not in reserved]
                for job in jobs:
                    image = self.store.get("images", job.get("imageId", "")) if job.get("imageId") else (unused.pop(0) if unused else None)
                    if image:
                        job = self.store.update("jobs", job["id"], imageId=image["id"])
                        paired.append(job)
                self.event(f"Img2Vid: {len(paired)} cặp; {len(jobs) - len(paired)} cảnh và {len(unused)} ảnh chưa ghép")
                jobs = paired
                if not jobs:
                    raise ValueError("Nhập ảnh tham chiếu để ghép với các cảnh")
            self.save_config(cfg)
            batch_id = uid()
            self.stop_event.clear()
            self.account_limits = {}
            self.running = True
            self.workers = []
            output = self.settings.output_dir / "_seedance" / batch_id
            output.mkdir(parents=True, exist_ok=True)
            for job in jobs:
                self.store.update("jobs", job["id"], batchId=batch_id, config=cfg, attempt=job["attempt"] + 1, error="", code="")
            group_size = 1 if cfg["mode"] == "image" else 2
            queues = distribute(jobs, len(cfg["profileIds"]) * cfg["tabsPerProfile"], group_size)
            thread = threading.Thread(target=self._coordinate, args=(cfg, queues, output, history_url), daemon=True, name="seedance")
            thread.start()
            self.event("Bắt đầu quét lịch sử" if history_url is not None else f"Bắt đầu batch {len(jobs)} cảnh")
        self.publish()
        return {"batchId": batch_id, "count": len(jobs)}

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if self.running:
                self.event("Đã yêu cầu dừng; không gửi cảnh tiếp theo. Render trên dịch vụ có thể vẫn tiếp tục.")
        self.publish()

    def _coordinate(self, cfg, queues, output, history_url):
        threads = []
        try:
            for index, profile in enumerate(cfg["profileIds"]):
                lanes = queues[index * cfg["tabsPerProfile"]:(index + 1) * cfg["tabsPerProfile"]]
                if not any(lanes) and history_url is None:
                    continue
                t = threading.Thread(target=self._profile_worker, args=(profile, cfg, lanes, output, history_url), daemon=True)
                t.start()
                threads.append(t)
            for thread in threads:
                thread.join()
        finally:
            with self.lock:
                for job in self.store.list("jobs"):
                    if job.get("batchId") == output.name and job["status"] == "queued":
                        self.store.update("jobs", job["id"], status="cancelled", code="CANCELLED", error="Batch đã dừng trước khi gửi")
                self.running = False
                self.workers = []
                self.event("Batch đã dừng" if self.stop_event.is_set() else "Đã kết thúc batch")
            self.publish()

    def _profile_worker(self, profile, cfg, queues, output, history_url):
        from playwright.sync_api import sync_playwright
        from ..llm.browser_chat import _launch

        context = None
        try:
            with browser_profiles.task_context(profile, check_cancel=self.check), browser_profiles.profile_session(cfg["provider"], "Seedance Studio Pro") as prof, sync_playwright() as pw:
                self.check()
                context = _launch(pw, self.settings.get("browser_channel"), visible=cfg["showBrowser"], offscreen=not cfg["showBrowser"], profile=prof)
                try:
                    generators = []
                    for tab_index, queue in enumerate(queues):
                        if not queue and (history_url is None or tab_index):
                            continue
                        page = context.new_page()
                        adapter = self.adapter_factory(context, page, cfg, self.check,
                                                       lambda text: self.event(text, profileId=profile))
                        adapter.before_submit = lambda: self.check_account(profile)
                        worker_id = f"{profile}:{tab_index + 1}"
                        with self.lock:
                            self.workers.append({"id": worker_id, "profileId": profile, "tab": tab_index + 1, "status": "ready"})
                        adapter.open(history_url or "")
                        generators.append(self._lane(adapter, queue, cfg, profile, worker_id, output, history_url))
                    # Cooperative lane scheduling keeps Playwright objects on their owning thread.
                    while generators:
                        for gen in list(generators):
                            try:
                                next(gen)
                            except StopIteration:
                                generators.remove(gen)
                        if generators:
                            # Playwright's event loop must run to consume responses.
                            context.pages[-1].wait_for_timeout(800)
                finally:
                    context.close()
        except Exception as exc:
            code = getattr(exc, "code", "BROWSER_ERROR")
            self.event(str(exc), level="error", code=code, profileId=profile)
            for queue in queues:
                for job in queue:
                    current = self.store.get("jobs", job["id"])
                    if current and current["status"] not in ("completed", "media_ready", "failed", "cancelled"):
                        self.store.update("jobs", job["id"], status="cancelled" if code == "CANCELLED" else "failed", error=str(exc), code=code)
            self.publish()

    def _lane(self, adapter, queue, cfg, profile, worker_id, output, history_url):
        if history_url is not None:
            try:
                yield from adapter.scan_history(lambda item: self._media(item, None, adapter, cfg, output, profile))
            except Exception as exc:
                self.event(str(exc), level="error", code=getattr(exc, "code", "HISTORY_FAILED"))
            self.publish()
            return
        for index, job in enumerate(queue):
            try:
                self.check_account(profile)
                if index and (cfg["mode"] == "image" or index % 2 == 0):
                    until = time.monotonic() + cfg["delaySeconds"]
                    self.event(f"Chờ {cfg['delaySeconds']} giây trước New Chat", job["id"], workerId=worker_id)
                    self.publish()
                    while time.monotonic() < until:
                        self.check()
                        yield
                    yield from adapter.new_chat()

                def checkpoint(status, **details):
                    self.check()
                    if status in ("preparing", "submitting"):
                        self.check_account(profile)
                    if status == "submitting":
                        details["submissionAttempted"] = True
                    self.store.update("jobs", job["id"], status=status, profileId=profile, workerId=worker_id, **details)
                    if status == "submitted" and cfg["mode"] == "image" and job.get("imageId"):
                        self.store.update("images", job["imageId"], status="attached", attachmentVerifiedAt=now())
                    self.event(status, job["id"], step=status, workerId=worker_id)
                    self.publish()

                checkpoint("preparing")
                image = self.store.get("images", job.get("imageId", "")) if cfg["mode"] == "image" else None
                yield from adapter.execute(job, image, checkpoint,
                                           lambda item: self._media(item, job, adapter, cfg, output, profile))
            except Exception as exc:
                code = getattr(exc, "code", "PROVIDER_ERROR")
                self.store.update("jobs", job["id"], status="cancelled" if code == "CANCELLED" else "failed", error=str(exc), code=code,
                                  chatUrl=adapter.page.url, providerMessage=getattr(exc, "provider_message", ""))
                self.event(str(exc), job["id"], level="error", code=code, workerId=worker_id, profileId=profile)
                # Block new submissions from the affected account; keep collecting already-running renders.
                if code in ACCOUNT_LIMIT_CODES:
                    with self.lock:
                        self.account_limits[profile] = {"code": code, "message": str(exc), "timestamp": now()}
                if code == "CONTENT_POLICY":
                    self.stop_event.set()
                for remaining in queue[index + 1:]:
                    self.store.update("jobs", remaining["id"], status="cancelled", code="CANCELLED", error="Lane đã dừng sau lỗi; chưa gửi cảnh này")
                self.publish()
                return

    def _media(self, item, job, adapter, cfg, output, profile):
        with self.lock:
            key = hashlib.sha256((item.get("providerVideoId") or item["url"].split("?", 1)[0]).encode()).hexdigest()
            existing = self.store.get("media", key)
            if not existing:
                existing = next((m for m in self.store.list("media") if m["url"].split("?", 1)[0] == item["url"].split("?", 1)[0]), None)
            if existing:
                # Signed URLs can expire; scanning refreshes the locator.
                self.store.update("media", existing["id"], **item)
                return
            record = self.store.put("media", {**item, "id": key, "sceneId": job["id"] if job else "",
                "title": job["title"] if job else "Video từ lịch sử", "provider": cfg["provider"], "profileId": profile,
                "chatUrl": adapter.page.url, "createdAt": now(), "path": "", "error": "", "outputDir": str(output)})
            if job:
                self.store.update("jobs", job["id"], status="media_ready", mediaId=key, chatUrl=adapter.page.url)
            self.event("Đã tìm thấy video", job["id"] if job else "", source=item.get("source", ""))
        self.publish()
        # The same policy is used for DOM and provider-response discoveries.
        if cfg["autoDownload"] and not cfg["zipMode"]:
            try:
                self._download(record, adapter.context.cookies())
            except Exception:
                pass  # A download failure does not invalidate a successfully generated video.

    def _download(self, record, cookies=None, cancellable=True):
        id = record["id"]
        with self.lock:
            fresh = self.store.get("media", id)
            if fresh.get("cleanPath") and Path(fresh["cleanPath"]).is_file():
                return Path(fresh["cleanPath"])
            if fresh.get("path") and Path(fresh["path"]).is_file():
                return Path(fresh["path"])
            if id in self.downloads:
                raise ValueError("Video đang được tải")
            self.downloads.add(id)
        target = Path(record["outputDir"]) / (id[:16] + ".mp4")
        temp = target.with_suffix(".part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if record.get("sceneId"):
                self.store.update("jobs", record["sceneId"], status="downloading") if self.store.get("jobs", record["sceneId"]) else None
            self.publish()
            with requests.Session() as session:
                for cookie in cookies or []:
                    session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie.get("path", "/"))
                url = record["url"]
                for _ in range(6):
                    if not allowed_url(url):
                        raise StudioError("DOWNLOAD_FAILED", "URL media nằm ngoài danh sách CDN hỗ trợ")
                    response = session.get(url, stream=True, timeout=(15, 30), allow_redirects=False,
                                           headers={"Referer": record.get("chatUrl", "https://www.dola.com/")})
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers["Location"])
                        response.close()
                        continue
                    response.raise_for_status()
                    total = 0
                    with response, temp.open("wb") as fh:
                        for chunk in response.iter_content(256 * 1024):
                            if cancellable:
                                self.check()
                            total += len(chunk)
                            if total > 1024 * 1024 * 1024:
                                raise StudioError("DOWNLOAD_FAILED", "Video vượt quá giới hạn 1 GB/file")
                            fh.write(chunk)
                    break
                else:
                    raise StudioError("DOWNLOAD_FAILED", "Quá nhiều chuyển hướng khi tải video")
            from ..ffmpeg import video_size, media_duration
            width, height = video_size(temp)
            duration = media_duration(temp)
            temp.replace(target)
            self.store.update("media", id, path=str(target), localUrl=self._local_url(target), downloadedAt=now(),
                              width=width, height=height, duration=duration, error="")
            if record.get("sceneId") and self.store.get("jobs", record["sceneId"]):
                self.store.update("jobs", record["sceneId"], status="completed", completedAt=now())
            self.event(f"Đã tải MP4 · {width}×{height} · {duration:.1f}s", record.get("sceneId", ""))
            return target
        except Exception as exc:
            self.store.update("media", id, error=str(exc))
            if record.get("sceneId") and self.store.get("jobs", record["sceneId"]):
                self.store.update("jobs", record["sceneId"], status="media_ready", error=str(exc), code="DOWNLOAD_FAILED")
            self.event(f"Tải video lỗi: {exc}", record.get("sceneId", ""), level="error", code="DOWNLOAD_FAILED")
            raise
        finally:
            temp.unlink(missing_ok=True)
            with self.lock:
                self.downloads.discard(id)
            self.publish()

    def _local_url(self, path):
        from urllib.parse import quote
        try:
            return "/media/" + quote(Path(path).relative_to(self.settings.output_dir).as_posix())
        except ValueError:
            return ""  # An older output folder can still be opened via the native file action.

    def download(self, id):
        record = self.store.get("media", id)
        if not record:
            raise ValueError("Không tìm thấy video")
        def run():
            try:
                self._download(record, cancellable=False)
            except Exception:
                pass  # recorded in durable event log
        threading.Thread(target=run, daemon=True).start()

    def remove_watermark(self, id, rectangle):
        from .watermark import logo_rectangle, remove_logo
        from ..ffmpeg import video_size

        with self.lock:
            record = self.store.get("media", id)
            if not record or not record.get("path") or not Path(record["path"]).is_file():
                raise ValueError("Tải MP4 về máy trước khi gỡ watermark")
            if id in self.cleaning or id in self.downloads or self.exporting:
                raise ValueError("Video đang được xử lý/tải/xuất; chờ hoàn tất trước")
            logo_rectangle(rectangle, *video_size(Path(record["path"])))
            self.cleaning.add(id)
        def run():
            target = Path(record["path"]).with_name(Path(record["path"]).stem + "_clean.mp4")
            try:
                rect = remove_logo(record["path"], target, rectangle)
                self.store.update("media", id, cleanPath=str(target), cleanUrl=self._local_url(target),
                                  watermarkStatus="local_processed", logoRectangle=rect, cleanedAt=now(), error="")
                self.event("Đã xử lý vùng watermark, giữ nguyên MP4 gốc", record.get("sceneId", ""))
                self.emit("toast", {"message": "Đã gỡ vùng watermark; bản xử lý được dùng khi mở/xuất ZIP.", "level": "ok"})
            except Exception as exc:
                self.store.update("media", id, error=str(exc))
                self.event(f"Gỡ watermark thất bại: {exc}", level="error", code="WATERMARK_FAILED")
            finally:
                with self.lock:
                    self.cleaning.discard(id)
                self.publish()
        threading.Thread(target=run, daemon=True, name="seedance-watermark").start()
        self.publish()

    def export_zip(self, ids=None):
        with self.lock:
            if self.exporting:
                raise ValueError("Đang xuất ZIP")
            if self.cleaning:
                raise ValueError("Chờ gỡ watermark xong trước khi xuất ZIP")
            records = [m for m in self.store.list("media") if not ids or m["id"] in ids]
            scene_order = {j["id"]: i for i, j in enumerate(self.store.list("jobs"))}
            records.sort(key=lambda m: scene_order.get(m.get("sceneId"), len(scene_order)))
            if not records:
                raise ValueError("Chưa có video để xuất ZIP")
            if len(records) > 500:
                raise ValueError("Mỗi ZIP tối đa 500 video")
            self.exporting = True

        def run():
            folder = self.settings.output_dir / "_seedance" / "exports"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / ("Seedance_" + uid()[:12] + ".zip")
            temp = target.with_suffix(".part")
            try:
                total = 0
                with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    for index, record in enumerate(records, 1):
                        try:
                            if total >= 10 * 1024 ** 3:
                                raise ValueError("Đã đạt giới hạn ZIP 10 GB")
                            path = self._download(record, cancellable=False)
                            total += path.stat().st_size
                            if total > 10 * 1024 ** 3:
                                raise ValueError("ZIP vượt quá giới hạn 10 GB")
                            archive.write(path, f"{index:04d}_{record['id'][:12]}.mp4")
                        except Exception as exc:
                            archive.writestr(f"{index:04d}_error.txt", str(exc))
                        self.event(f"ZIP: {index}/{len(records)} file")
                        self.publish()
                temp.replace(target)
                self.store.put("exports", {"id": uid(), "path": str(target), "url": self._local_url(target), "createdAt": now()})
                self.event(f"Đã xuất ZIP: {target.name}")
                self.emit("toast", {"message": "Đã xuất ZIP trong thư mục _seedance/exports", "level": "ok"})
            except Exception as exc:
                self.event(f"Xuất ZIP thất bại: {exc}", level="error", code="ZIP_FAILED")
            finally:
                temp.unlink(missing_ok=True)
                with self.lock:
                    self.exporting = False
                self.publish()
        threading.Thread(target=run, daemon=True).start()
        self.publish()

    def export_project(self):
        target = self.settings.output_dir / "_seedance" / ("project_" + uid()[:12] + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 1, "config": self.store.config(),
                                    "scenes": [{"title": j["title"], "text": j["text"]} for j in self.store.list("jobs")],
                                    "jobs": self.store.list("jobs"), "events": self.store.list("events")}, ensure_ascii=False, indent=2), "utf-8")
        return str(target)

    def open_media(self, id):
        record = self.store.get("media", id)
        if not record or not record.get("path") or not Path(record["path"]).is_file():
            raise ValueError("Tải video về máy trước khi mở file")
        open_path(record.get("cleanPath") or record["path"])
