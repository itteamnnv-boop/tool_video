"""Studio Muse AI · kịch bản → nhóm video (storyboard, từng cảnh, chia đoạn), duyệt, ghép + nhạc nền, LadiPage."""
import re
import threading
import uuid
from pathlib import Path

from . import common as _c
from .common import HubError, MAX_IMAGES, RATIOS, TERMINAL, _uid, asset_url, compose_images, now_ms, safe_name


class GroupsMixin:
    # ------------------------------------------------------------ Kịch bản / LadiPage → nhóm task
    def bgm_dir(self) -> Path:
        path = Path(self.hub["settings"].get("bgm_dir") or (self.out_root() / "nhac-nen"))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _public_group(self, g: dict) -> dict:
        tasks = [t for t in self.tasks if t.get("group") == g["id"]]
        base = Path(self.settings.output_dir)
        outs = []
        for f in g.get("outputs") or []:
            p = Path(f)
            if p.is_file():
                try:
                    url = f"/media/{p.relative_to(base).as_posix()}?v={int(p.stat().st_mtime)}"
                except ValueError:
                    url = ""
                outs.append({"path": str(p), "name": p.name, "url": url})
        sb = next((t for t in tasks if t.get("role") == "storyboard"), None)
        sb_files = self._public(sb)["files"] if sb else []
        return {**g, "outputs": outs, "storyboard": sb_files[0] if sb_files else None,
                "tasks": [{"id": t["id"], "role": t.get("role", ""), "status": t["status"], "scene": t.get("scene", 0),
                           "error": t.get("error", "")} for t in tasks]}

    def add_script(self, form: dict) -> dict:
        """Tab Kịch bản / LadiPage → nhóm task. form: {mode: script|image, text, method, ratio, duration, prefix, voice,
        presenter, character, merge, bgm, versions, product_images[], motions[], note, title}."""
        from .. import muse_script as ms

        mode = "image" if form.get("mode") == "image" else "script"
        ratio = form.get("ratio") if form.get("ratio") in RATIOS else "9:16"
        method = form.get("method") if form.get("method") in ms.METHODS else "direct"
        duration = str(form.get("duration") or "10")
        if duration not in ms.DURATIONS:
            duration = "10"
        per_scene = duration == "per_scene"
        voice = form.get("voice") if form.get("voice") in ms.VOICES else "none"
        presenter = form.get("presenter") if form.get("presenter") in ("female", "male") else ""
        prefix = str(form.get("prefix") or "").strip()[:600]
        try:
            versions = max(1, min(5, int(form.get("versions") or 1)))
        except (TypeError, ValueError):
            versions = 1
        products = [str(p) for p in form.get("product_images") or [] if Path(str(p)).is_file()]  # mỗi ảnh = 1 bộ video
        shared = [str(p) for p in form.get("images") or [] if Path(str(p)).is_file()]  # gửi kèm MỌI video (LadiPage)
        dry = bool(form.get("dry"))  # "Xem lệnh sẽ gửi Muse": dựng prompt, không tạo task
        char = next((c for c in self.hub["characters"] if c["id"] == form.get("character")), None)
        char_imgs = [p for p in (char or {}).get("images", []) if Path(p).is_file()]
        project = form.get("project") or self.hub["current"]
        created = []

        def new_task(group, **kw):
            t = {"id": _uid("tk"), "project": project, "kind": "video", "prompt": "", "ratio": ratio, "images": [],
                 "notes": [], "status": "queued", "account": "", "attempts": 0, "created_at": now_ms() + len(created),
                 "started_at": 0, "finished_at": 0, "files": [], "error": "", "log": [], "group": group["id"]}
            t.update(kw)
            self.tasks.append(t)
            created.append(t["id"])
            return t

        # đánh số: mỗi video 1 số nối tiếp trong dự án (#01, #02…) đúng thứ tự trong kịch bản; batch = đợt tạo
        mine = [g for g in self.groups if (g.get("project") or "default") == project]
        numbering = {"batch": max((int(g.get("batch") or 0) for g in mine), default=0) + 1,
                     "no": max((int(g.get("no") or 0) for g in mine), default=0)}

        def new_group(**kw):
            numbering["no"] += 1
            g = {"id": _uid("g"), "project": project, "mode": mode, "ratio": ratio, "status": "running",
                 "created_at": now_ms(), "outputs": [], "bgm": bool(form.get("bgm")), "versions": versions,
                 "batch": numbering["batch"], "no": numbering["no"]}
            g.update(kw)
            self.groups.append(g)
            return g

        with self._lock:
            n_tasks, n_groups, rot = len(self.tasks), len(self.groups), self.hub["rotate"].get("idx", 0)
            if mode == "image":
                if not products:
                    raise HubError("Chọn ít nhất 1 ảnh sản phẩm (mỗi ảnh = 1 video)")
                motions = [m for m in form.get("motions") or [] if m in ms.MOTIONS] or ["zoom"]
                prompt = ms.image_motion_prompt(motions, str(form.get("note") or ""))
                for product in products:
                    for v in range(versions):
                        g = new_group(title=Path(product).name[:60], method="direct", duration="10", merge=False,
                                      version=v + 1, scenes=[prompt])
                        new_task(g, role="video", prompt=prompt, duration=10, images=[product, *char_imgs][:MAX_IMAGES])
            else:
                videos = ms.parse_script(form.get("text"))
                if not videos:
                    raise HubError("Nhập kịch bản: mỗi dòng 1 cảnh, cách 1 dòng trống để sang video tiếp theo")
                for product in products or [None]:
                    for scenes in videos:
                        refs, _ = compose_images(" ".join(scenes), self.hub,
                                                 ([product] if product else []) + shared + char_imgs, self._take_rotate)
                        for v in range(versions):
                            title = str(form.get("title") or "").strip() or scenes[0]
                            g = new_group(title=title[:70], method=method, duration=duration, version=v + 1,
                                          scenes=scenes, merge=per_scene and len(scenes) > 1 and form.get("merge", True)
                                          is not False, voice=voice, presenter=presenter)
                            sb = None
                            if method in ("storyboard", "review"):
                                sb = new_task(g, role="storyboard", kind="image", images=list(refs),
                                              prompt=ms.storyboard_prompt(scenes, prefix=prefix, presenter=presenter))
                            extra = {"status": "waiting" if sb else "queued", "after": sb["id"] if sb else "",
                                     "refs_note": ms.STORYBOARD_REFS if sb else (ms.PRODUCT_REFS if refs else None)}
                            if per_scene:
                                for i, scene in enumerate(scenes, 1):
                                    new_task(g, role="scene", scene=i, duration=10, images=list(refs), **extra,
                                             prompt=ms.video_prompt([scene], seconds=10, prefix=prefix, voice=voice,
                                                                    presenter=presenter, storyboard=bool(sb),
                                                                    product=bool(product)))
                            elif ms.DURATIONS[duration] > ms.MUSE_CLIP_MAX:
                                # Muse làm mỗi clip tối đa ~10 giây → chia đoạn ≤ 10s, chia cảnh cho từng đoạn, xong tự ghép
                                secs = ms.DURATIONS[duration]
                                parts = ms.split_seconds(secs)
                                n = len(parts)
                                chunks = ([scenes[round(j * len(scenes) / n):round((j + 1) * len(scenes) / n)] for j in range(n)]
                                          if len(scenes) >= n else [scenes] * n)
                                g["merge"] = True
                                start = 0
                                for k, (sec, chunk) in enumerate(zip(parts, chunks), 1):
                                    p = ms.video_prompt(chunk, seconds=sec, prefix=prefix, voice=voice, presenter=presenter,
                                                        storyboard=bool(sb), product=bool(product or shared))
                                    new_task(g, role="scene", scene=k, duration=sec, images=list(refs), **extra,
                                             prompt=p + "\n" + ms.part_note(k, n, start, start + sec, secs, sec))
                                    start += sec
                            else:
                                secs = ms.DURATIONS[duration]
                                new_task(g, role="video", duration=secs, images=list(refs), **extra,
                                         prompt=ms.video_prompt(scenes, seconds=secs, prefix=prefix, voice=voice,
                                                                presenter=presenter, storyboard=bool(sb),
                                                                product=bool(product or shared)))
            if dry:  # chỉ xem lệnh: trả prompt rồi bỏ các task / nhóm vừa dựng
                preview = [{"role": t.get("role"), "scene": t.get("scene", 0), "kind": t["kind"], "prompt": t["prompt"],
                            "images": len(t["images"]), "duration": t.get("duration", 0), "status": t["status"]}
                           for t in self.tasks[n_tasks:]]
                self.tasks, self.groups = self.tasks[:n_tasks], self.groups[:n_groups]
                self.hub["rotate"]["idx"] = rot
                return {"preview": preview, "groups": len(self.groups) - n_groups}
            self._save()
        self._wake.set()
        self._push()
        return {"created": created, "groups": len({self._task(i)["group"] for i in created})}

    def approve(self, group_id: str) -> dict:
        """Duyệt storyboard → các task video của nhóm vào hàng đợi."""
        with self._lock:
            n = 0
            for t in self.tasks:
                if t.get("group") == group_id and t["status"] == "review":
                    t["status"] = "queued"
                    n += 1
            if not n:
                raise HubError("Nhóm này không có video chờ duyệt")
            self._save()
        self._wake.set()
        self._push()
        return self.state()

    def delete_group(self, group_id: str) -> dict:
        ids = [t["id"] for t in self.tasks if t.get("group") == group_id]
        self.task_action(ids, "delete")
        with self._lock:
            self.groups = [g for g in self.groups if g["id"] != group_id]
            self._save()
        self._push()
        return self.state()

    def _after_task(self, task: dict) -> None:
        """Gọi trong khoá sau khi 1 task kết thúc: mở khoá task chờ storyboard + hoàn tất nhóm khi đủ."""
        g = next((x for x in self.groups if x["id"] == task.get("group")), None)
        if task.get("role") == "storyboard":
            for t in self.tasks:
                if t.get("after") != task["id"] or t["status"] != "waiting":
                    continue
                if task["status"] == "succeeded" and task.get("files"):
                    sb = task["files"][0]
                    t["images"] = [sb, *[p for p in t["images"] if p != sb]][:MAX_IMAGES]
                    t["status"] = "review" if g and g.get("method") == "review" else "queued"
                elif task["status"] in ("failed", "cancelled"):
                    t.update(status=task["status"], finished_at=now_ms(),
                             error="Storyboard không tạo được" if task["status"] == "failed" else "Đã huỷ")
            if task["status"] == "succeeded":
                return
        if g is None:
            return
        tasks = [t for t in self.tasks if t.get("group") == g["id"]]
        if any(t["status"] not in TERMINAL for t in tasks):
            return
        videos = [t for t in tasks if t.get("role") in ("video", "scene")]
        if not videos or any(t["status"] != "succeeded" for t in videos):
            g["status"] = "failed" if any(t["status"] == "failed" for t in tasks) else "cancelled"
            return
        g["status"] = "finishing"
        threading.Thread(target=self._finish_group, args=(g["id"],), daemon=True).start()

    def _finish_group(self, group_id: str) -> None:
        """Nhóm đủ video: ghép các cảnh (nếu làm từng cảnh) → lót nhạc nền (nếu bật, giữ cả bản không nhạc)."""
        import random

        g = next((x for x in self.groups if x["id"] == group_id), None)
        if g is None:
            return
        videos = sorted([t for t in self.tasks if t.get("group") == group_id and t.get("role") in ("video", "scene")],
                        key=lambda t: t.get("scene", 0))
        files = [Path(t["files"][0]) for t in videos if t.get("files")]
        folder = self.out_root() / (g.get("project") or "default") / "video"
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[\\/:*?"<>|]+', " ", g.get("title") or "")[:50].strip() or "video"
        outputs, err = [], ""
        if g.get("merge") and len(files) > 1:
            out = safe_name(folder, f"{stem} v{g.get('version', 1)}")
            err = self._merge_files(files, out)
            if not err:
                outputs.append(out)
        else:
            outputs = list(files)
        if not err and g.get("bgm"):
            tracks = [p for p in self.bgm_dir().iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac")]
            if tracks:
                mixed = []
                for f in outputs:
                    out = safe_name(folder, f"{Path(f).stem} - nhac")
                    if not self._mix_bgm(Path(f), random.choice(tracks), out):
                        mixed.append(out)
                outputs += mixed
            else:
                err = f"Bật nhạc nền nhưng thư mục nhạc trống: {self.bgm_dir()}"
        with self._lock:
            g.update(outputs=[str(p) for p in outputs], status="done" if outputs else "failed", error=err)
            self._save()
        self._push()

    def _mix_bgm(self, video: Path, track: Path, out: Path) -> str:
        from .. import ffmpeg

        vol = float(self.hub["settings"].get("bgm_volume") or 0.15)
        audio = ("[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]" if ffmpeg.has_audio(video)
                 else "[bg]anull[a]")
        try:
            ffmpeg.run(["-i", video, "-stream_loop", "-1", "-i", track, "-filter_complex",
                        f"[1:a]volume={vol:.2f}[bg];{audio}", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", out])
            return ""
        except Exception as exc:  # ffmpeg lỗi → giữ bản không nhạc
            return str(exc)[:200]

    # ------------------------------------------------------------ LadiPage
    def ladi_images(self, urls: list) -> list:
        """Tải ảnh sản phẩm đã chọn từ trang về kho uploads → [{path, url}] để gửi kèm Muse."""
        from .. import muse_script as ms

        out = []
        for u in (urls or [])[:6]:
            p = ms.download_image(u, _c.STORE / "uploads", uuid.uuid4().hex[:12])
            out.append({"path": str(p), "url": asset_url(str(p)), "name": Path(u.split("?")[0]).name})
        return out
