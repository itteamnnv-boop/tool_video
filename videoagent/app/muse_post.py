"""Studio Muse AI — tab "Hậu kỳ": ghép các video người dùng chọn (thư viện / máy) + lồng tiếng AI (edge-tts) hoặc tiếng
gốc + chuyển cảnh + âm chuyển cảnh + phụ đề + nhạc nền + Hậu kỳ AI (Muse chọn từ khoá, hiệu ứng, hook) / HyperFrames.

Dùng lại đúng các bước ghép của Studio (StudioRunner._assemble): mỗi clip → scenes/NN/{scene.mp4, voice.mp3} rồi
app/pipeline/composer.compose(). Kết quả là 1 thư mục video trong thư mục lưu → hiện ở Thư viện video như video Studio.
Chạy nền, lần lượt từng video; tiến độ + nhật ký qua sự kiện "mhub_post".
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .library import save_job
from .llm.base import extract_json
from .pipeline import VOICE_LEAD, Cancelled, post_ai, scene_dir_name, transitions
from .pipeline.assets import extract_audio
from .pipeline.composer import compose
from .pipeline.tts import RATES, VOICES, role_voice, synthesize
from .studio import ASPECTS, FPS, LOGO_CORNERS, POST_STYLES, ask_model, fit_clip, stamp_logo
from .util import slugify, unique_dir

log = logging.getLogger(__name__)
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
AUDIO_MODES = {"tts": "Lồng tiếng AI (giọng đọc máy)", "original": "Giữ tiếng gốc của clip",
               "mute": "Không lời (chỉ nhạc + âm)"}
MAX_CLIPS = 40
KIND = "muse_post"


class PostError(RuntimeError):
    pass


def meta() -> dict:
    """Lựa chọn cho giao diện tab Hậu kỳ."""
    return {"aspects": [{"value": k, "label": v[0]} for k, v in ASPECTS.items()],
            "voices": VOICES, "rates": RATES, "audio_modes": [{"value": k, "label": v} for k, v in AUDIO_MODES.items()],
            "post_styles": [{"value": k, "label": v} for k, v in POST_STYLES.items()],
            "logo_corners": [{"value": k, "label": v} for k, v in LOGO_CORNERS.items() if k != "none"],
            **transitions.options()}


def clean(form: dict) -> dict:
    """Kiểm tra form từ giao diện → tuỳ chọn hợp lệ (clip phải là file video có thật)."""
    clips = []
    for c in (form.get("clips") or [])[:MAX_CLIPS]:
        p = Path(str((c or {}).get("path") or ""))
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
            raise PostError(f"Không tìm thấy video: {p.name or '(trống)'}")
        url = str(c.get("url") or "")
        clips.append({"path": str(p), "text": " ".join(str(c.get("text") or "").split())[:1200],
                      "title": str(c.get("title") or p.stem)[:120],
                      "url": url if url.startswith(("/media/", "/mhub-asset/")) else "",  # xem trước khi hậu kỳ lại
                      # mô tả nội dung cảnh (prompt gốc của video) → Hậu kỳ AI / HyperFrames hiểu cảnh kể cả khi không lời
                      "desc": " ".join(str(c.get("desc") or "").split())[:400]})
    if not clips:
        raise PostError("Thêm ít nhất 1 video để hậu kỳ")
    try:
        bgm_volume = max(0.0, min(0.5, float(form.get("bgm_volume", 0.12))))
    except (TypeError, ValueError):
        bgm_volume = 0.12
    return {"clips": clips, "name": " ".join(str(form.get("name") or "").split())[:80] or "Video hậu kỳ",
            "aspect": form.get("aspect") if form.get("aspect") in ASPECTS else "9:16",
            "audio": form.get("audio") if form.get("audio") in AUDIO_MODES else "tts",
            "voice": form.get("voice") if form.get("voice") in {v["id"] for v in VOICES} else "vi-VN-HoaiMyNeural",
            "rate": form.get("rate") if form.get("rate") in RATES else "+0%",
            "subtitles": bool(form.get("subtitles", True)), "bgm": bool(form.get("bgm", True)), "bgm_volume": bgm_volume,
            "post_ai": bool(form.get("post_ai")),
            "post_style": form.get("post_style") if form.get("post_style") in POST_STYLES else "basic",
            "post_subs": bool(form.get("post_subs", True)), "post_audio": bool(form.get("post_audio", True)),
            "show_browser": bool(form.get("show_browser")),
            # đóng logo (PNG nền trong suốt đẹp nhất) lên 1 góc video, sau cùng
            "logo": _logo(form.get("logo")),
            "logo_url": str(form.get("logo_url") or "")[:400] if str(form.get("logo_url") or "").startswith("/mhub-asset/") else "",
            "logo_corner": form.get("logo_corner") if form.get("logo_corner") in LOGO_CORNERS and form.get("logo_corner") != "none" else "tr",
            **transitions.clean(form.get("transition") or "fade", form.get("transition_duration") or 0.5,
                                form.get("transition_sound") or "whoosh",
                                form.get("transition_volume") if form.get("transition_volume") is not None else 0.6)}


def _logo(path) -> str:
    p = Path(str(path or ""))
    return str(p) if str(path or "") and p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else ""


class PostRunner:
    """Hàng đợi hậu kỳ (mỗi video 1 luồng, chạy lần lượt nhờ khoá — ghép + mã hoá nặng máy)."""

    def __init__(self, settings, emit, music_dir=None) -> None:
        self.settings, self._emit = settings, emit
        self._music_dir = music_dir or (lambda: "")
        self._lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}

    # ------------------------------------------------------------ công khai
    def start(self, form: dict) -> dict:
        opts = clean(form)
        jid = uuid.uuid4().hex[:10]
        self.jobs[jid] = {"id": jid, "name": opts["name"], "status": "queued", "pct": 0, "stage": "Chờ đến lượt",
                          "log": [], "created_at": int(time.time() * 1000), "clips": len(opts["clips"]),
                          "path": "", "url": "", "error": "", "post": {}}
        self._cancel[jid] = threading.Event()
        threading.Thread(target=self._worker, args=(jid, opts), daemon=True, name=f"muse-post-{jid}").start()
        self._push(jid)
        return self.jobs[jid]

    def cancel(self, jid: str) -> dict:
        ev = self._cancel.get(jid)
        if ev:
            ev.set()
        return self.state()

    def state(self) -> dict:
        return {"jobs": sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)[:20],
                "done": self.finished()}

    def finished(self) -> list:
        """Video hậu kỳ đã làm (đọc lại từ thư mục lưu — còn sau khi tắt app)."""
        out = []
        for jf in Path(self.settings.output_dir).glob("*/job.json"):
            try:
                job = json.loads(jf.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            final = jf.parent / "final.mp4"
            if not isinstance(job, dict) or job.get("kind") != KIND or not final.is_file():
                continue
            out.append({"id": jf.parent.name, "title": job.get("title", ""), "duration": job.get("duration", 0),
                        "aspect": job.get("aspect", ""), "created_at": job.get("created_at", ""), "path": str(final),
                        "clips": len(job.get("scenes") or []), "post": job.get("post_info") or {},
                        "url": f"/media/{jf.parent.name}/final.mp4?v={int(final.stat().st_mtime)}",
                        "form": self._form_of(jf.parent, job)})
        return sorted(out, key=lambda x: x["created_at"], reverse=True)[:30]

    @staticmethod
    def _form_of(job_dir: Path, job: dict) -> dict:
        """Thiết lập để "Hậu kỳ lại": clip gốc + tuỳ chọn đã lưu; video làm trước khi có lưu → dựng lại từ các cảnh đã
        chuẩn hoá còn trong thư mục video (scenes/NN/scene.mp4) + lời đọc / tuỳ chọn trong job.json."""
        if isinstance(job.get("post_form"), dict):
            return job["post_form"]
        clips = []
        for sc in job.get("scenes") or []:
            f = job_dir / "scenes" / scene_dir_name(int(sc.get("index") or 0)) / "scene.mp4"
            if f.is_file():
                clips.append({"path": str(f), "title": str(sc.get("headline") or f"Cảnh {sc.get('index')}"),
                              "text": str(sc.get("narration") or ""),
                              "url": f"/media/{job_dir.name}/scenes/{f.parent.name}/scene.mp4"})
        audio = "original" if job.get("original_audio") else "tts" if any(c["text"] for c in clips) else "mute"
        opts = {k: job[k] for k in ("aspect", "voice", "subtitles", "bgm", "bgm_volume", "transition",
                                    "transition_duration", "transition_sound", "transition_volume") if k in job}
        return {"clips": clips, "options": {**opts, "audio": audio, "name": job.get("title", "")}, "rebuilt": True}

    # ------------------------------------------------------------ nội bộ
    def _push(self, jid: str) -> None:
        self._emit("mhub_post", self.jobs[jid])

    def _log(self, jid: str, msg: str, level: str = "info") -> None:
        job = self.jobs[jid]
        job["log"] = [*job["log"], f"{datetime.now():%H:%M:%S} {msg}"][-60:]
        log.info("hậu kỳ %s: %s", jid, msg)
        self._push(jid)

    def _progress(self, jid: str, pct: float, stage: str) -> None:
        self.jobs[jid].update(pct=round(pct), stage=stage)
        self._push(jid)

    def _check(self, jid: str) -> None:
        if self._cancel[jid].is_set():
            raise Cancelled("Đã dừng")

    def _worker(self, jid: str, opts: dict) -> None:
        job = self.jobs[jid]
        with self._lock:
            if self._cancel[jid].is_set():
                job.update(status="cancelled", stage="Đã dừng")
                return self._push(jid)
            job.update(status="running", stage="Đang chuẩn bị")
            self._push(jid)
            try:
                final, info = self._run(jid, opts)
                job.update(status="done", pct=100, stage="Hoàn tất", path=str(final), post=info,
                           url=f"/media/{final.parent.name}/final.mp4?v={int(final.stat().st_mtime)}")
                self._log(jid, "Đã xong video — có trong Thư viện video", "ok")
            except Cancelled:
                job.update(status="cancelled", stage="Đã dừng")
                self._log(jid, "Đã dừng", "warn")
            except Exception as exc:  # ffmpeg / edge-tts / model lỗi → báo rõ trên thẻ
                log.exception("hậu kỳ lỗi")
                job.update(status="failed", stage="Lỗi", error=str(exc)[:500])
                self._log(jid, f"Lỗi: {exc}", "error")

    def _ask(self, o: dict, prompt: str, *, complete, what: str, jid: str) -> str:
        return ask_model(self.settings, {"model": "muse_browser", "text_profile": "", "show_browser": o["show_browser"]},
                         prompt, complete=complete, what=what, log=lambda m, *a, **k: self._log(jid, m),
                         check_cancel=lambda: self._check(jid))

    def _run(self, jid: str, o: dict) -> tuple[Path, dict]:
        check = lambda: self._check(jid)  # noqa: E731
        say = lambda m, *a, **k: self._log(jid, m)  # noqa: E731
        created = datetime.now()
        job_dir = unique_dir(Path(self.settings.output_dir) / f"{slugify(o['name'])}_{created:%Y%m%d_%H%M%S}")
        width, height = ASPECTS[o["aspect"]][1]
        scenes, total = [], len(o["clips"])
        for k, clip in enumerate(o["clips"], 1):
            check()
            self._progress(jid, 3 + 60 * (k - 1) / total, f"Đang chuẩn bị cảnh {k}/{total}")
            sdir = job_dir / "scenes" / scene_dir_name(k)
            sdir.mkdir(parents=True)
            src, voice = Path(clip["path"]), sdir / "voice.mp3"
            clip_dur = ffmpeg.media_duration(src)
            words, vdur, duration, speed = [], 0.0, clip_dur, 1.0
            if o["audio"] == "original":  # tiếng gốc: giữ tốc độ clip (tua sẽ méo giọng)
                extract_audio(src, 0.0, duration, voice)
                vdur = duration
            elif o["audio"] == "tts" and clip["text"]:
                tts_voice, rate, pitch = role_voice("", o["voice"], o["rate"])
                words = synthesize(clip["text"], tts_voice, rate, voice, pitch=pitch)
                vdur = ffmpeg.media_duration(voice)
                duration, speed = fit_clip(clip_dur, vdur)  # giữ trọn chuyển động, tua nhẹ cho khớp lời đọc
            else:  # không lời → giọng rỗng (compose cần đủ file mỗi cảnh)
                ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.3", "-q:a", "9", voice])
            pad = max(0.0, duration - clip_dur / speed) + 0.5  # thiếu hình (clip ngắn hơn lời) → giữ khung cuối
            ffmpeg.run(["-i", src, "-vf", ",".join([
                f"setpts=PTS/{speed}",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1",
                f"fps={FPS}", f"tpad=stop_mode=clone:stop_duration={pad:.2f}", "format=yuv420p"]),
                "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", sdir / "scene.mp4"])
            ffmpeg.run(["-i", sdir / "scene.mp4", "-frames:v", "1", "-q:v", "3", sdir / "thumb.jpg"])
            scenes.append({"index": k, "kicker": "", "headline": clip["title"], "narration": clip["text"], "desc": clip.get("desc", ""),
                           "words": words, "voice_duration": vdur, "duration": duration})
            kind = {"original": "tiếng gốc", "mute": "không lời"}.get(o["audio"]) or (f"giọng {vdur:.1f}s" if vdur else "không lời")
            say(f"Cảnh {k}: {duration:.1f}s · {kind}" + (f" · clip {clip_dur:.1f}s ×{speed:g}" if speed != 1 else f" · clip {clip_dur:.1f}s"))
        job = {"id": job_dir.name, "kind": KIND, "title": o["name"], "topic": o["name"], "genre": "studio",
               "template_id": KIND, "template_name": "Hậu kỳ Studio Muse AI", "aspect": o["aspect"],
               "width": width, "height": height, "fps": FPS, "voice": o["voice"],
               # phụ đề lấy từ lời đọc / lời thoại đã nhập cho từng cảnh
               "subtitles": o["subtitles"] and any(c["text"] for c in o["clips"]),
               "bgm": o["bgm"], "bgm_volume": o["bgm_volume"], "created_at": created.isoformat(timespec="seconds"),
               "duration": round(sum(s["duration"] for s in scenes), 3), "scenes": scenes,
               **{k: o[k] for k in ("transition", "transition_duration", "transition_sound", "transition_volume")}}
        if o["audio"] != "tts":  # tiếng gốc / không lời: không lùi lời đọc; nhạc nhỏ lại khi giữ tiếng gốc
            job["voice_lead"] = 0.0
            if o["audio"] == "original":
                job.update(original_audio=True, bgm_volume=round(o["bgm_volume"] * 0.6, 3))
        if o["subtitles"] and not job["subtitles"]:
            say("Phụ đề: chưa nhập lời đọc / lời thoại cho cảnh nào — bỏ phụ đề", "warn")
        say(f"Chuyển cảnh: {transitions.TRANSITIONS[o['transition']][0]} {o['transition_duration']:g}s · "
            f"âm: {transitions.SOUNDS[o['transition_sound']][0]} {round(o['transition_volume'] * 100)}%")
        info = self._post_ai(jid, o, job) if o["post_ai"] else {}
        # HyperFrames chạy độc lập với phần chọn từ khoá (video không lời vẫn có đồ hoạ động: hook, tiêu đề cảnh, thẻ kết)
        hf = o["post_ai"] and o["post_style"] == "hyperframes"
        subtitles = job["subtitles"]
        music = self._music_dir() or self.settings.get("music_dir") or ""
        cleanup = bool(self.settings.get("cleanup_temp"))
        if hf:
            job["subtitles"] = False
        self._progress(jid, 70, "Đang ghép giọng đọc, chuyển cảnh, phụ đề, nhạc nền")
        compose(job_dir, job, log=say, check_cancel=check, music_dir=music, cleanup=cleanup)
        if hf:
            try:
                info["hyperframes"] = self._hyperframes(jid, o, job, job_dir, show_captions=subtitles)
            except Cancelled:
                raise
            except Exception as exc:  # HyperFrames lỗi → phụ đề nổi bật thường (ASS), video vẫn ra
                say(f"HyperFrames lỗi ({exc}) — dùng phụ đề nổi bật thường", "warn")
                job["subtitles"] = subtitles
                compose(job_dir, job, log=say, check_cancel=check, music_dir=music, cleanup=cleanup)
            job["subtitles"] = subtitles
        if o["logo"]:
            self._progress(jid, 97, "Đang đóng logo lên video")
            try:
                stamp_logo(job_dir / "final.mp4", Path(o["logo"]), o["logo_corner"])
                say(f"Đã đóng logo · {LOGO_CORNERS[o['logo_corner']].lower()}", "ok")
                info["logo"] = o["logo_corner"]
            except Exception as exc:  # logo lỗi → video vẫn giữ, báo rõ
                say(f"Không đóng được logo: {exc}", "warn")
        job["post_info"] = info
        # lưu clip gốc + mọi tuỳ chọn → bấm "Hậu kỳ lại" nạp lại đúng như lúc làm
        job["post_form"] = {"clips": o["clips"], "options": {k: v for k, v in o.items() if k != "clips"}}
        save_job(job_dir, job)
        return job_dir / "final.mp4", info

    def _post_ai(self, jid: str, o: dict, job: dict) -> dict:
        """Muse chọn từ khoá tô nổi + hiệu ứng âm thanh + hook + mức nhạc (như Studio). Cảnh KHÔNG lời vẫn làm được: Muse
        đọc mô tả cảnh → hook + hiệu ứng đầu cảnh + mức nhạc. Lỗi → ghép bình thường."""
        scenes = job["scenes"]
        has_text = any(s["narration"] for s in scenes)
        subs, audio = bool(o["post_subs"] and job["subtitles"]), bool(o["post_audio"])
        if not has_text:
            self._log(jid, "Hậu kỳ AI: các cảnh chưa có lời đọc / lời thoại → không tô từ khoá; Muse làm hook + hiệu ứng "
                           "âm thanh + mức nhạc theo nội dung cảnh", "warn")
        # mô tả cho Muse: tên + nội dung cảnh (prompt gốc của video) — để hiểu cảnh cả khi không lời
        brief = [{**s, "headline": " — ".join(x for x in (s.get("headline"), s.get("desc")) if x)[:300]} for s in scenes]
        self._progress(jid, 64, "Hậu kỳ AI: Muse đang chọn hook, từ khoá, hiệu ứng")
        try:
            data = extract_json(self._ask(o, post_ai.build_prompt(brief), complete=post_ai.complete, jid=jid,
                                          what="chọn hook + từ khoá nổi bật + hiệu ứng âm thanh (hậu kỳ AI)"))
            if not isinstance(data, dict):
                raise ValueError("không phải JSON object")
        except Cancelled:
            raise
        except Exception as exc:  # model lỗi / chưa đăng nhập / JSON sai → vẫn ra video
            self._log(jid, f"Hậu kỳ AI bị bỏ qua ({exc}) — ghép bình thường", "warn")
            return {}
        offsets = [sum(s["duration"] for s in scenes[:k]) for k in range(len(scenes))]
        extra = post_ai.apply_plan(data, scenes, offsets, float(job.get("voice_lead", VOICE_LEAD)), subs=subs,
                                   audio=audio, log=lambda m, *a, **k: self._log(jid, m))
        hook = " ".join(str(data.get("hook") or "").split())[:post_ai.HOOK_MAX]
        if hook and not subs and not has_text:  # không phụ đề (video không lời) → vẫn hiện câu hook đầu video
            extra.update(subtitle_fx=True, subtitle_hook=hook)
            job["subtitles"] = True  # chỉ có dòng hook (các cảnh không có chữ)
            self._log(jid, f"Hậu kỳ AI: hiện hook “{hook}” ở đầu video")
        job.update(extra)
        return {"model": "muse_browser", "hook": extra.get("subtitle_hook", "") or hook,
                "words": sum(len(s.get("highlight") or []) for s in scenes), "cues": len(extra.get("sfx_cues") or [])}

    def _hyperframes(self, jid: str, o: dict, job: dict, job_dir: Path, *, show_captions: bool) -> dict:
        """Đồ hoạ động HyperFrames trên nền final.mp4 (Muse thiết kế, app kiểm tra + sửa 1 lần, dựng trên máy)."""
        from .pipeline import hyperframes as hfm

        hfm.ensure_installed(lambda m, *a, **k: self._log(jid, m))
        brief = [{**s, "headline": " — ".join(x for x in (s.get("headline"), s.get("desc")) if x)[:300]} for s in job["scenes"]]
        captions, scenes = hfm.timeline_data(brief, float(job.get("voice_lead", VOICE_LEAD)))
        if not show_captions:
            captions = []
        width, height, duration = job["width"], job["height"], float(job["duration"])
        folder = job_dir / "hyperframes"
        complete = lambda t: isinstance(extract_json(t), dict) and "js" in extract_json(t)  # noqa: E731
        layout = dict(captions=captions, scenes=scenes, width=width, height=height, duration=duration, logo=None)
        prompt = hfm.build_prompt(scenes, captions, width=width, height=height, duration=duration,
                                  hook=job.get("subtitle_hook", ""), logo=False, brand=o["name"])
        self._progress(jid, 84, "HyperFrames: Muse đang thiết kế đồ hoạ động")
        self._log(jid, "HyperFrames: đang nhờ Muse thiết kế đồ hoạ động (hook, tiêu đề cảnh, phụ đề động, thẻ kết)…")
        design = hfm.parse_design(extract_json(self._ask(o, prompt, complete=complete, jid=jid,
                                                         what="thiết kế đồ hoạ động HyperFrames")))
        hfm.write_project(folder, job_dir / "final.mp4", design, **layout)
        errors = hfm.lint(folder)
        if errors:  # mỗi lần hỏi là 1 cuộc chat mới → gửi lại đề + bản trước + lỗi
            self._log(jid, f"HyperFrames: thiết kế có {len(errors)} lỗi — nhờ Muse sửa", "warn")
            retry = (prompt + "\n\nBản trước của bạn:\n```json\n" + json.dumps(design, ensure_ascii=False)
                     + "\n```\n\n" + hfm.fix_prompt(errors))
            design = hfm.parse_design(extract_json(self._ask(o, retry, complete=complete, jid=jid,
                                                             what="sửa thiết kế HyperFrames")))
            hfm.write_project(folder, job_dir / "final.mp4", design, **layout)
            errors = hfm.lint(folder)
            if errors:
                raise PostError("thiết kế vẫn lỗi: " + "; ".join(errors[:3]))
        minutes = max(1, round(duration * 3 / 60))
        self._progress(jid, 88, f"Đang dựng đồ hoạ động HyperFrames (~{minutes} phút)")
        self._log(jid, f"HyperFrames: thiết kế hợp lệ — đang dựng {duration:.0f} giây video trên máy (~{minutes} phút)…")
        out = hfm.render(folder, folder / "render.mp4", fps=int(job.get("fps") or FPS),
                         check_cancel=lambda: self._check(jid))
        out.replace(job_dir / "final.mp4")
        self._log(jid, f"HyperFrames: xong · {len(captions)} dòng phụ đề động", "ok")
        return {"captions": len(captions)}
