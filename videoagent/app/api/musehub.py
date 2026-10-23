"""API · Studio Muse AI · dây chuyền (mhub_*): tài khoản, hàng đợi, tư liệu, kịch bản, LadiPage, video mẫu, hậu kỳ, thư viện."""
import os
import webview

from ..config import settings

from .common import _fail, _hub_call, _ok, log


class MuseHubApi:
    def mhub_state(self) -> dict:
        return _ok(state=self._muse_hub.state())

    def mhub_settings(self, patch: dict) -> dict:
        return _hub_call("state", self._muse_hub.set_settings, patch or {})

    def mhub_account(self, pid: str, patch: dict) -> dict:
        return _hub_call("state", self._muse_hub.set_account, str(pid or ""), patch or {})

    def mhub_quota(self, pid: str = "") -> dict:
        """Đọc lại hạn mức tuần (1 tài khoản / tất cả) — mở muse.ai ở profile đó, chỉ đọc, không tốn lượt."""
        self._muse_hub.refresh_quota(str(pid or ""))
        return _ok()

    def mhub_login(self, pid: str) -> dict:
        """Đăng nhập Muse trong đúng profile hệ thống (dùng chung màn Profile trình duyệt)."""
        res = self.browser_login("muse_browser", str(pid or ""))
        if res.get("ok"):
            self._muse_hub.set_account(str(pid), {"relogin": True})
        return res

    def mhub_project(self, action: str, pid: str = "", name: str = "") -> dict:
        return _hub_call("state", self._muse_hub.project, str(action or ""), str(pid or ""), str(name or ""))

    def mhub_asset(self, kind: str, data: dict) -> dict:
        return _hub_call("state", self._muse_hub.asset, str(kind or ""), data or {})

    def mhub_add(self, form: dict) -> dict:
        return _hub_call("result", self._muse_hub.add_tasks, form or {})

    def mhub_tasks(self, ids: list, action: str) -> dict:
        return _hub_call("state", self._muse_hub.task_action, list(ids or []), str(action or ""))

    def mhub_stop(self) -> dict:
        return _ok(state=self._muse_hub.stop_all())

    def mhub_resume(self) -> dict:
        return _ok(state=self._muse_hub.resume())

    def mhub_import(self, paths: list) -> dict:
        return _hub_call("images", self._muse_hub.import_images, list(paths or []))

    def mhub_import_data(self, name: str, data_url: str) -> dict:
        """Ảnh kéo thả vào ô Ảnh sản phẩm (data URL) → kho uploads của Studio Muse AI."""
        return _hub_call("images", self._muse_hub.import_data, str(name or ""), str(data_url or ""))

    # ---- Kịch bản (mỗi dòng 1 cảnh, dòng trống = video mới) / Từ ảnh
    def mhub_script(self, form: dict) -> dict:
        return _hub_call("result", self._muse_hub.add_script, form or {})

    def mhub_approve(self, group_id: str) -> dict:
        """Duyệt storyboard của 1 video → các task video vào hàng đợi."""
        return _hub_call("state", self._muse_hub.approve, str(group_id or ""))

    def mhub_group_delete(self, group_id: str) -> dict:
        return _hub_call("state", self._muse_hub.delete_group, str(group_id or ""))

    def mhub_bgm(self, action: str = "open") -> dict:
        """Thư mục nhạc nền: open = mở thư mục; pick = chọn thư mục khác."""
        if action == "pick":
            folder_dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
            res = self._window.create_file_dialog(folder_dialog)
            return _ok(state=self._muse_hub.set_settings({"bgm_dir": str(res[0])}) if res else self._muse_hub.state())
        os.startfile(self._muse_hub.bgm_dir())
        return _ok()

    # ---- LadiPage → 3 kịch bản
    def mhub_ladi_fetch(self, url: str) -> dict:
        """Đọc landing page: tên sản phẩm, ảnh, giá, chữ trên trang (chỉ là dữ liệu)."""
        from .. import muse_script

        return _hub_call("page", muse_script.fetch_ladi, str(url or ""))

    def mhub_ladi_scripts(self, page: dict, no_price: bool = True, scenes: int = 3, seconds: int = 30,
                          profile: str = "", show_browser: bool = False) -> dict:
        """Muse viết 3 kịch bản phân cảnh từ dữ liệu trang (1–3 phút, chạy bằng profile Muse)."""
        from .. import muse_script

        def run():
            return muse_script.write_scripts(settings, page or {}, no_price=bool(no_price),
                                             scenes=max(2, min(8, int(scenes or 3))), seconds=int(seconds or 30),
                                             profile=str(profile or ""), show_browser=bool(show_browser),
                                             log=lambda m, level="info": log.info("ladi: %s", m))

        return _hub_call("result", run)

    def mhub_timeline(self, form: dict, show_browser: bool = False) -> dict:
        """Tab Studio: Muse viết prompt video dạng timeline (0–3s, 3–6s…) từ ý tưởng / kịch bản (1–3 phút)."""
        from .. import muse_script

        f = dict(form or {})

        def run():
            return muse_script.write_timeline(settings, str(f.get("idea") or ""), count=int(f.get("count") or 1),
                                              seconds=int(f.get("seconds") or 10), ratio=str(f.get("ratio") or ""),
                                              style=str(f.get("style") or ""), show_browser=bool(show_browser),
                                              log=lambda m, level="info": log.info("timeline: %s", m))

        return _hub_call("result", run)

    def mhub_ladi_images(self, urls: list) -> dict:
        return _hub_call("images", self._muse_hub.ladi_images, list(urls or []))

    # ---- Hậu kỳ: ghép video tuỳ chọn + lồng tiếng + chuyển cảnh + âm chuyển + phụ đề + nhạc + Hậu kỳ AI / HyperFrames
    def mhub_post_meta(self) -> dict:
        from .. import muse_post

        return _ok(meta=muse_post.meta())

    def mhub_post_state(self) -> dict:
        return _ok(state=self._muse_post.state())

    def mhub_post_start(self, form: dict) -> dict:
        from ..muse_post import PostError

        try:
            return _ok(job=self._muse_post.start(dict(form or {})))
        except PostError as exc:
            return _fail(exc)

    def mhub_post_probe(self, paths: list) -> dict:
        """Thời lượng các video chọn từ máy (để hiện trong danh sách cảnh)."""
        from pathlib import Path

        from .. import ffmpeg
        from ..muse_post import VIDEO_EXT

        out = []
        for p in (paths or [])[:40]:
            path = Path(str(p))
            if path.is_file() and path.suffix.lower() in VIDEO_EXT:
                try:
                    out.append({"path": str(path), "duration": ffmpeg.media_duration(path)})
                except ffmpeg.FFmpegError:
                    out.append({"path": str(path), "duration": 0})
        return _ok(items=out)

    def mhub_post_cancel(self, job_id: str) -> dict:
        return _ok(state=self._muse_post.cancel(str(job_id or "")))

    def mhub_post_open(self, path: str) -> dict:
        """Mở Explorer chọn sẵn video hậu kỳ (chỉ file final.mp4 trong thư mục lưu video)."""
        import subprocess
        from pathlib import Path

        root, target = Path(settings.output_dir).resolve(), Path(str(path or "")).resolve()
        if not target.is_relative_to(root) or target.name != "final.mp4" or not target.is_file():
            return _fail(ValueError("Không tìm thấy video hậu kỳ"))
        subprocess.Popen(["explorer", "/select,", str(target)])
        return _ok()

    # ---- Video mẫu: phân tích video (file / link) → Muse viết kịch bản tương tự cho nội dung mới
    def mhub_sample_prepare(self, source: str) -> dict:
        """Tải / đọc video mẫu, cắt khung đổi cảnh + ảnh lưới + nhịp dựng (máy tự làm, không tốn lượt AI)."""
        from .. import muse_sample

        return _hub_call("sample", muse_sample.prepare, str(source or ""),
                         lambda m, level="info": log.info("sample: %s", m))

    def mhub_sample_docs(self, paths: list) -> dict:
        from .. import muse_sample

        return _hub_call("docs", muse_sample.docs_info, list(paths or []))

    def mhub_sample_scripts(self, sample_id: str, form: dict, profile: str = "", show_browser: bool = False) -> dict:
        """Muse xem ảnh lưới video mẫu (+ ảnh sản phẩm, tài liệu) → phân tích + 1–3 kịch bản mới (1–3 phút)."""
        from .. import muse_sample

        def run():
            return muse_sample.write(settings, str(sample_id or ""), dict(form or {}), profile=str(profile or ""),
                                     show_browser=bool(show_browser),
                                     log=lambda m, level="info": log.info("sample: %s", m))

        return _hub_call("result", run)

    def mhub_library(self, project: str = "") -> dict:
        return _hub_call("items", self._muse_hub.library, str(project or ""))

    def mhub_move(self, paths: list, project: str) -> dict:
        """Thư viện: chuyển file đã chọn (và cả kịch bản chứa nó) sang dự án khác."""
        return _hub_call("result", self._muse_hub.move_to_project, list(paths or []), str(project or ""))

    def mhub_post_sources(self, project: str = "") -> dict:
        """Video cho tab Hậu kỳ, nhóm theo kịch bản (cảnh đúng thứ tự); project rỗng = mọi dự án."""
        return _hub_call("sources", self._muse_hub.post_sources, str(project or ""))

    def mhub_merge(self, paths: list, name: str = "", project: str = "") -> dict:
        return _hub_call("job", self._muse_hub.merge, list(paths or []), str(name or ""), str(project or ""))

    def mhub_open(self, path: str = "") -> dict:
        """Mở thư mục kết quả Studio Muse AI; có path → Explorer chọn sẵn đúng file (chỉ file trong thư mục kết quả)."""
        import subprocess
        from pathlib import Path

        root = self._muse_hub.out_root().resolve()
        target = Path(path).resolve() if path else root
        if not target.is_relative_to(root) or not target.exists():
            return _fail(ValueError("File không thuộc thư mục Studio Muse AI"))
        if target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            os.startfile(target)
        return _ok()
