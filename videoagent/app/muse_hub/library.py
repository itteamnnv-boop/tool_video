"""Studio Muse AI · thư viện kết quả, tên dễ nhận biết, chuyển dự án, nguồn cho Hậu kỳ, ghép video."""
import subprocess
import threading
import uuid
from pathlib import Path

from . import common as _c
from .common import HubError, safe_name


class LibraryMixin:
    # ------------------------------------------------------------ thư viện + ghép video
    def move_to_project(self, paths: list, project: str) -> dict:
        """Chuyển các file đã chọn ở Thư viện sang dự án khác. File thuộc kịch bản → chuyển CẢ kịch bản (mọi cảnh +
        bản ghép) để không bị tách rời. File trên ổ đĩa giữ nguyên chỗ, chỉ đổi dự án mà task / kịch bản thuộc về."""
        if not any(p["id"] == project for p in self.hub["projects"]):
            raise HubError("Dự án không tồn tại")
        key = lambda p: str(Path(str(p)).resolve()).lower()  # noqa: E731
        want = {key(p) for p in paths or []}
        if not want:
            raise HubError("Chưa chọn file nào")
        with self._lock:
            hit = {t["id"] for t in self.tasks if any(key(f) in want for f in t.get("files") or [])}
            gids = {t.get("group") for t in self.tasks if t["id"] in hit and t.get("group")}
            gids |= {g["id"] for g in self.groups if any(key(f) in want for f in g.get("outputs") or [])}
            moved = hit | {t["id"] for t in self.tasks if t.get("group") in gids}
            for t in self.tasks:
                if t["id"] in moved:
                    t["project"] = project
            for g in self.groups:
                if g["id"] in gids:
                    g["project"] = project
            self._save()
        self._push()
        return {"tasks": len(moved), "groups": len(gids), "extra": len(moved - hit)}

    @staticmethod
    def _label(t: dict, groups: dict) -> str:
        """Tên dễ nhận biết của 1 file kết quả: "Tên kịch bản · Cảnh n" — không thuộc kịch bản thì dòng đầu prompt."""
        g = groups.get(t.get("group"))
        if g:
            part = ("Storyboard" if t.get("role") == "storyboard" else f"Cảnh {t['scene']}" if t.get("scene") else "")
            no = f"#{int(g['no']):02d}" if g.get("no") else ""
            return " · ".join(x for x in (no, str(g.get("title") or "Kịch bản"), part) if x)[:140]
        line = next((x.strip() for x in str(t.get("prompt") or "").splitlines() if x.strip()), "")
        return line[:140] or ("Video" if t.get("kind") == "video" else "Ảnh")

    def library(self, project: str = "") -> list:
        out = []
        groups = {g["id"]: g for g in self.groups}
        for t in self.tasks:
            if t["status"] != "succeeded" or (project and t.get("project") != project):
                continue
            label = self._label(t, groups)
            for f in self._public(t)["files"]:
                out.append({**f, "task": t["id"], "kind": t["kind"], "prompt": t["prompt"][:300], "label": label,
                            "project": t.get("project"), "finished_at": t.get("finished_at")})
        # bản ghép của nhóm (video dài chia đoạn / kịch bản từng cảnh / lót nhạc) — file khác với file của các task
        have = {str(Path(x["path"]).resolve()).lower() for x in out}
        for g in groups.values():
            if project and (g.get("project") or "default") != project:
                continue
            for o in self._public_group(g)["outputs"]:
                p = Path(o["path"])
                if str(p.resolve()).lower() in have:
                    continue
                n = sum(1 for t in self.tasks if t.get("group") == g["id"] and t.get("role") in ("video", "scene"))
                kind = "bản có nhạc nền" if p.stem.endswith(" - nhac") else f"bản ghép {n} đoạn"
                no = f"#{int(g['no']):02d} · " if g.get("no") else ""
                out.append({**o, "video": True, "task": "", "kind": "video", "prompt": str(g.get("title") or "")[:300],
                            "label": f"{no}{g.get('title') or 'Video'} · {kind}"[:140], "project": g.get("project"),
                            "finished_at": int(p.stat().st_mtime * 1000) if p.is_file() else g.get("created_at")})
        return sorted(out, key=lambda x: x.get("finished_at") or 0, reverse=True)

    def post_sources(self, project: str = "") -> dict:
        """Video để chọn ở tab Hậu kỳ, NHÓM THEO KỊCH BẢN (cảnh xếp đúng thứ tự Cảnh 1, 2, 3…) + bản đã ghép của kịch
        bản; video không thuộc kịch bản nào → "others". project rỗng = mọi dự án."""
        by_task = {t["id"]: t for t in self.tasks}
        groups = {g["id"]: g for g in self.groups if not project or (g.get("project") or "default") == project}
        scenes_of: dict[str, list] = {}
        others = []
        for f in self.library(project):
            if not f.get("video") or not f.get("task"):  # bản ghép của nhóm: thêm riêng ở khối kịch bản bên dưới
                continue
            t = by_task.get(f["task"]) or {}
            item = {**f, "scene": int(t.get("scene") or 0), "role": t.get("role", ""), "group": t.get("group", "")}
            if item["group"] in groups:
                scenes_of.setdefault(item["group"], []).append(item)
            else:
                others.append(item)
        out = []
        for gid, g in groups.items():
            items = sorted(scenes_of.get(gid, []), key=lambda x: (x["scene"], x.get("finished_at") or 0))
            # kết quả của kịch bản: bỏ file TRÙNG với cảnh (kịch bản 1 video / không ghép → kết quả chính là video đó),
            # gắn nhãn đúng loại: bản ghép nhiều cảnh / bản lót nhạc nền
            seen = {str(Path(x["path"]).resolve()).lower() for x in items}
            outputs = []
            for o in self._public_group(g)["outputs"]:
                if str(Path(o["path"]).resolve()).lower() in seen:
                    continue
                kind = "Bản có nhạc nền" if Path(o["path"]).stem.endswith(" - nhac") else f"Bản đã ghép ({len(items)} cảnh)"
                outputs.append({**o, "label": kind})
            if not items and not outputs:
                continue
            out.append({"id": gid, "title": (f"#{int(g['no']):02d} · " if g.get("no") else "") + g.get("title", ""),
                        "no": int(g.get("no") or 0), "batch": int(g.get("batch") or 0),
                        "project": g.get("project") or "default",
                        "version": g.get("version", 1), "versions": g.get("versions", 1), "created_at": g["created_at"],
                        "lines": list(g.get("scenes") or []), "scenes": items, "outputs": outputs})
        # đợt tạo mới nhất trên cùng; trong 1 đợt theo đúng số thứ tự kịch bản (#01 → #n)
        out.sort(key=lambda x: (-x["batch"], x["no"] or 0, -x["created_at"]))
        return {"groups": out, "others": others}

    def merge(self, paths: list, name: str, project: str = "") -> dict:
        """Ghép nhiều video theo thứ tự (chạy nền, tiến độ qua sự kiện mhub_merge)."""
        from .. import ffmpeg

        files = [Path(p) for p in paths or [] if Path(p).is_file()]
        if len(files) < 2:
            raise HubError("Chọn ít nhất 2 video để ghép")
        folder = self.out_root() / (project or self.hub["current"]) / "ghep"
        folder.mkdir(parents=True, exist_ok=True)
        out = safe_name(folder, name)
        job = uuid.uuid4().hex[:8]

        def run():
            err = self._merge_files(files, out, lambda pct: self._emit("mhub_merge", {"job": job, "pct": pct,
                                                                                         "path": str(out)}))
            self._emit("mhub_merge", {"job": job, "pct": -1 if err else 100, "path": str(out), "done": True,
                                      "error": err})

        threading.Thread(target=run, daemon=True).start()
        return {"job": job, "path": str(out)}

    def _merge_files(self, files: list, out: Path, progress=None) -> str:
        """Ghép video theo thứ tự (mã hoá lại cùng khung hình / fps / âm thanh). Trả về "" nếu xong, ngược lại là lỗi."""
        from .. import ffmpeg

        try:
            durations = [ffmpeg.media_duration(f) for f in files]
            w, h = ffmpeg.video_size(files[0])
        except Exception as exc:  # file hỏng
            return str(exc)
        size = "1920:1080" if w > h else "1080:1920"
        inputs, chains = [], []
        for i, f in enumerate(files):
            inputs += ["-i", str(f)]
            chains.append(f"[{i}:v]scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2,"
                          f"setsar=1,fps=30,format=yuv420p[v{i}]")
            chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]" if ffmpeg.has_audio(f)
                          else f"anullsrc=r=44100:cl=stereo,atrim=duration={durations[i]:.3f}[a{i}]")
        chains.append("".join(f"[v{i}][a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=1:a=1[v][a]")
        args = [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                "-progress", "pipe:1", "-nostats", str(out)]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", creationflags=ffmpeg.NO_WINDOW)
        total = sum(durations) or 0
        for line in proc.stdout:
            if progress and line.startswith("out_time_us=") and total:
                try:
                    progress(min(99, round(int(line.split("=")[1]) / 1e6 / total * 100)))
                except ValueError:
                    pass
        err = proc.stderr.read()
        return "" if proc.wait() == 0 and out.is_file() else (err.strip()[-300:] or "ffmpeg lỗi")
