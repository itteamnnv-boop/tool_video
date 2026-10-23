"""API · Chiến dịch (phòng marketing AI) + thư viện chiến dịch."""
import os

from ..config import settings

from .common import _fail, _ok


class CampaignApi:
    # ------------------------------------------------------------------ chiến dịch (phòng marketing AI)
    def _camp(self, key: str, fn, *args) -> dict:
        from ..campaign.store import CampaignError

        try:
            return _ok(**{key: fn(*args)})
        except (CampaignError, ValueError, OSError) as exc:
            return _fail(exc)

    def _cdir(self, cid: str):
        from ..campaign import store

        return store.campaign_dir(settings.output_dir, cid)

    def campaign_overview(self) -> dict:
        from ..campaign import ai, store

        return _ok(campaigns=store.list_campaigns(settings.output_dir), stats=store.stats(settings.output_dir),
                   running=self._campaigns.running_ids(), keys=ai.key_status(), statuses=store.STATUSES,
                   stages=[{"key": k, "name": n, "role": r, "file": f} for k, n, r, f in store.STAGES])

    def campaign_create(self, form: dict) -> dict:
        return self._camp("result", self._campaigns.create, form)

    def campaign_get(self, cid: str) -> dict:
        import json as _json

        from ..campaign import store
        from ..campaign.store import CampaignError

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
        from ..campaign.media import EXTRA_IMAGES, IMAGE_KEYS

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
        from ..campaign import store, tools

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
        from ..facebook import FacebookError

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

        from ..campaign import store

        def run():
            cdir = self._cdir(cid)
            zip_dir = store.root(settings.output_dir) / "_zip"
            zip_dir.mkdir(parents=True, exist_ok=True)
            path = _shutil.make_archive(str(zip_dir / cid), "zip", cdir)
            os.startfile(zip_dir)
            return path

        return self._camp("path", run)

    def campaign_history(self) -> dict:
        from ..campaign import store

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

    def camp_library(self) -> dict:
        from ..campaign import ai, store

        lib = store.library()
        for rid, role in lib["roles"].items():
            role["versions"] = [{"at": v["at"], "chars": len(v.get("prompt", ""))} for v in role.get("versions", [])]
        return _ok(library=lib, keys=ai.key_status(), models=ai.MODEL_CHOICES,
                   image_engine=self._campaigns.default_image_engine())

    def camp_save_product(self, item: dict, new_images: list | None = None) -> dict:
        from ..campaign import store

        return self._camp("products", store.save_product, item, new_images or [])

    def camp_delete_product(self, pid: str) -> dict:
        from ..campaign import store

        return self._camp("products", store.delete_product, pid)

    def camp_add_refs(self, files: list, tags: list) -> dict:
        from ..campaign import store

        return self._camp("refs", store.add_refs, files, tags)

    def camp_update_ref(self, file: str, tags: list) -> dict:
        from ..campaign import store

        return self._camp("refs", store.update_ref, file, tags)

    def camp_delete_ref(self, file: str) -> dict:
        from ..campaign import store

        return self._camp("refs", store.delete_ref, file)

    def camp_save_model(self, item: dict, image: str = "") -> dict:
        from ..campaign import store

        return self._camp("models", store.save_model, item, image)

    def camp_delete_model(self, mid: str) -> dict:
        from ..campaign import store

        return self._camp("models", store.delete_model, mid)

    def camp_save_styles(self, items: list) -> dict:
        from ..campaign import store

        return self._camp("styles", store.save_styles, items)

    def camp_save_template(self, text: str) -> dict:
        from ..campaign import store

        return self._camp("template", store.save_content_template, text)

    def camp_save_role(self, rid: str, prompt=None, model=None, effort=None) -> dict:
        from ..campaign import store

        def run():
            roles = store.save_role(rid, prompt, model, effort)
            return {k: {**v, "versions": [{"at": x["at"], "chars": len(x.get("prompt", ""))} for x in v.get("versions", [])]}
                    for k, v in roles.items()}

        return self._camp("roles", run)

    def camp_role_version(self, rid: str, index: int) -> dict:
        from ..campaign import store

        def run():
            versions = store.roles()[rid].get("versions", [])
            return versions[int(index)]["prompt"]

        return self._camp("prompt", run)
