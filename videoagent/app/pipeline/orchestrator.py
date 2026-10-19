"""Điều phối 6 bước: Chuẩn bị → Kịch bản → Lời thoại → Dựng hình → Hậu kỳ → Hoàn thiện.

Chạy trong thread nền, báo tiến trình cho UI qua callback emit(event, data).
"""
import logging
import shutil
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

from .. import ffmpeg
from ..library import load_job, save_job, summary
from ..llm import make_provider
from ..llm.gemini_veo import VeoUnavailable
from ..llm.video_engines import ENGINES, normalize_options
from ..llm.video_engines import generate as generate_video
from ..llm.image_engines import ENGINES as IMAGE_ENGINES
from ..llm.image_engines import fit_aspect, save_images
from ..llm.image_engines import generate as generate_image
from ..templates_registry import registry
from ..util import slugify, unique_dir
from . import ASPECTS, SCENE_TAIL, VOICE_LEAD, Cancelled, scene_dir_name
from .assets import (PRESENTER_GUIDE, PRODUCT_GENRE, STYLE_TEMPLATES, assign_media, custom_template, extract_audio,
                     images_for_ai, import_assets)
from .scene_context import is_video_name
from .assets import validate as validate_assets
from ..browser_profiles import task_context
from .ai_video import (as_regular_job_form, collect_attachments, collect_variables, dedupe_attachments, fill_prompt, finalize,
                       import_attachments, prepare_video_refs, reference_sentence, step_inputs, template_prompt,
                       video_inputs)
from .composer import compose
from .renderer import SceneRenderer
from .scene_designer import design_scene
from .script_writer import write_script
from .tasks import TaskPool
from .tts import RATES, VOICES, synthesize

log = logging.getLogger(__name__)
VOICE_IDS = {v["id"] for v in VOICES}
POST_STEPS = 5


@dataclass
class JobRequest:
    topic: str
    genre: str = "trailer"
    template: str = "ai"
    provider: str = "gemini_browser"
    show_browser: bool = False
    aspect: str = "9:16"
    seconds: float = 8.0
    num_scenes: int = 4
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"
    subtitles: bool = True
    bgm: bool = True
    layout_file: str = ""
    product_files: tuple = ()
    product_style: str = "showcase"
    brand: str = ""
    comment_name: str = ""
    comment_text: str = ""
    price: str = ""
    old_price: str = ""
    perk: str = ""
    contact: str = ""
    keep_audio: bool = False

    @classmethod
    def from_form(cls, form: dict) -> "JobRequest":
        topic = str(form.get("topic") or "").strip()
        if not topic:
            raise ValueError("Hãy nhập nội dung video")
        req = cls(
            topic=topic,
            genre=str(form.get("genre") or "trailer"),
            template=str(form.get("template") or "ai"),
            provider=str(form.get("provider") or "gemini_browser"),
            show_browser=bool(form.get("show_browser")),
            aspect=form.get("aspect") if form.get("aspect") in ASPECTS else "9:16",
            seconds=min(20.0, max(3.0, float(form.get("seconds") or 8))),
            num_scenes=min(20, max(1, int(form.get("scenes") or 4))),
            voice=form.get("voice") if form.get("voice") in VOICE_IDS else "vi-VN-HoaiMyNeural",
            rate=form.get("rate") if form.get("rate") in RATES else "+0%",
            subtitles=bool(form.get("subtitles", True)),
            bgm=bool(form.get("bgm", True)),
            layout_file=str(form.get("layout_file") or ""),
            product_files=tuple(str(p) for p in form.get("product_files") or []),
            product_style=form.get("product_style") if form.get("product_style") in STYLE_TEMPLATES else "showcase",
            brand=str(form.get("brand") or "").strip()[:60],
            comment_name=str(form.get("comment_name") or "").strip()[:40],
            comment_text=str(form.get("comment_text") or "").strip()[:120],
            price=str(form.get("price") or "").strip()[:40],
            old_price=str(form.get("old_price") or "").strip()[:40],
            perk=str(form.get("perk") or "").strip()[:60],
            contact=str(form.get("contact") or "").strip()[:60],
            keep_audio=bool(form.get("keep_audio")),
        )
        if req.genre == PRODUCT_GENRE:
            validate_assets(req.layout_file, req.product_files, req.product_style)  # báo lỗi ngay khi bấm Tạo video
        return req


class JobRunner:
    """Tạo video — nhiều tác vụ chạy song song qua TaskPool; trạng thái riêng của từng tác vụ nằm trong pool.current."""

    def __init__(self, settings, license_mgr, emit) -> None:
        self.settings = settings
        self.license = license_mgr
        self.pool = TaskPool("", emit, lambda: settings.get("max_parallel_video") or 2)

    @property
    def running(self) -> bool:
        return self.pool.running

    # Trạng thái riêng của tác vụ hiện tại (mỗi thread một tác vụ)
    @property
    def _cancel(self) -> threading.Event:
        return self.pool.current.cancel_event

    @property
    def _new_dir(self):
        return self.pool.current.data.get("new_dir")

    @_new_dir.setter
    def _new_dir(self, value) -> None:
        self.pool.current.data["new_dir"] = value

    def start(self, form: dict) -> str:
        """Thêm một tác vụ tạo video vào hàng đợi, trả về id tác vụ."""
        template = registry.get(str(form.get("template") or ""))
        profile = str(form.get("browser_profile") or "")
        title = (str(form.get("topic") or "").strip() or (template.name if template else "Video"))[:80]
        meta = {"provider": str(form.get("provider") or ""), "kind": "video"}
        spawn = lambda target, *args: self.pool.submit(title, self._wrap, target, *args, meta=meta, profile=profile)  # noqa: E731
        if template is not None and template.kind == "whiteboard":
            wb = self._whiteboard_form(template, form)
            meta["kind"] = "whiteboard"
            title = f"{template.name}" + (f" · {form.get('topic')}" if form.get("topic") else "")
            return self.pool.submit(title, self._wrap, self._run_whiteboard, template, wb, meta=meta,
                                    profile=wb["profile"])
        if template is not None and template.kind == "ai_video" and form.get("genre") != PRODUCT_GENRE:
            meta["kind"] = "ai_video"
            title = f"{template.name}" + (f" · {form.get('topic')}" if form.get("topic") else "")
            engine = template.video_engine or str(form.get("provider") or "")
            if engine not in ENGINES:
                raise ValueError("Template video AI cần Provider AI: Grok Browser, Gemini Browser, Dola Browser hoặc Gemini API")
            variables = collect_variables(template, form.get("variables"))
            attachments = collect_attachments(template, form.get("attachments"))
            if any(spec.get("keep_video") for spec, _ in attachments) and not ENGINES[engine].get("video_input"):
                raise ValueError(f"Template “{template.name}” cần gửi video gốc — chọn Provider Grok Browser hoặc Dola Browser")
            for step in template.image_steps:
                if (step.get("engine") or engine) not in IMAGE_ENGINES:
                    raise ValueError(f"Template “{template.name}”: engine ảnh của bước “{step.get('label', step['key'])}” không hợp lệ")
            regular_form = as_regular_job_form(template, variables, attachments, form)
            if engine == "gemini_browser" and form.get("gemini_mode") == "regular":
                # Gemini Browser · Video thông thường: Gemini viết kịch bản, app tự dựng (không dùng Veo)
                return spawn(self._run_new, JobRequest.from_form(regular_form))
            options = normalize_options(engine, {
                **template.options, **{k: form[f"ai_{k}"] for k in ("duration", "resolution", "aspect") if form.get(f"ai_{k}")}})
            fallback = regular_form if engine == "gemini_browser" else None
            # template nhiều bước: mỗi bước (key bước / "video") chọn profile trình duyệt riêng; "" = tự chọn profile rảnh
            step_profiles = ({str(k): str(v or "") for k, v in (form.get("step_profiles") or {}).items()}
                             if template.image_steps else None)
            return spawn(self._run_ai_video, template, variables, attachments, options, engine,
                         bool(form.get("show_browser")), fallback, step_profiles)
        return spawn(self._run_new, JobRequest.from_form(form))

    def rerender(self, job_id: str, index: int) -> str:
        return self.pool.submit(f"Dựng lại khung {index} · {job_id}", self._wrap, self._run_rerender, job_id, int(index),
                                meta={"kind": "rerender", "job_id": job_id, "index": int(index)})

    def cancel(self, task_id: str = "") -> int:
        return self.pool.cancel(task_id)

    # ------------------------------------------------------------------ internals
    def _wrap(self, target, *args) -> dict:
        try:
            return target(*args)
        except Cancelled:  # xoá thư mục video tạo dở của tác vụ này
            if self._new_dir is not None and not (self._new_dir / "final.mp4").exists():
                shutil.rmtree(self._new_dir, ignore_errors=True)
            raise

    def _log(self, message: str, level: str = "info") -> None:
        self.pool.log(message, level)

    def _progress(self, pct: float, status: str, stage: str) -> None:
        self.pool.progress(pct, status, stage)

    def _check_cancel(self) -> None:
        self.pool.check_cancel()

    def _post_logger(self, start: float, end: float):
        step = (end - start) / POST_STEPS
        counter = {"n": 0}

        def post_log(message: str, level: str = "info") -> None:
            self._log(message, level)
            if level == "info":
                self._progress(start + step * counter["n"], message, "post")
                counter["n"] += 1

        return post_log

    def _run_new(self, req: JobRequest) -> dict:
        s = self.settings
        self._progress(1, "Đang chuẩn bị", "prepare")
        self._log("Đang chuẩn bị")
        self.license.require_active()
        llm = make_provider(req.provider, s, show_browser=req.show_browser)
        product_mode = req.genre == PRODUCT_GENRE
        layout, products, template = None, [], None
        if product_mode:
            layout, products = validate_assets(req.layout_file, req.product_files, req.product_style)
        elif req.template != "ai":
            template = registry.pick(req.template) or registry.guess(req.topic)
        width, height = ASPECTS[req.aspect]
        fps = int(s.get("fps") or 30)

        self._progress(5, "Đang viết kịch bản", "script")
        self._log(f"Đang viết kịch bản ({llm.name if llm else 'offline'})")
        images = None
        if product_mode and llm is not None:
            if llm.supports_images:
                images = images_for_ai(products)
                self._log(f"Gửi kèm {len(images)} ảnh sản phẩm cho AI")
            else:
                self._log("Provider trình duyệt không gửi được ảnh — AI viết theo nội dung bạn nhập", "warn")
        ai_templates = registry.all() if template is None and llm is not None and not product_mode else None
        extra = ""
        if product_mode and req.product_style in ("presenter", "reel"):
            extra += PRESENTER_GUIDE
        if product_mode:
            offer_text = ", ".join(x for x in (f"giá {req.price}" if req.price else "",
                                               f"giá cũ {req.old_price}" if req.old_price else "", req.perk) if x)
            if offer_text:
                extra += f"Thông tin bán hàng do người bán cung cấp (dùng đúng, không đổi con số): {offer_text}.\n"
            extra += ('Thêm trường cấp cao "features": 2-4 lợi ích ngắn (mỗi lợi ích ≤ 3 từ) của sản phẩm, '
                      "rút từ nội dung người dùng, không bịa.\n")
            if req.product_style == "reel":
                extra += "Khung cuối nhắc giá ưu đãi và mời khách bình luận “TƯ VẤN” hoặc nhắn tin.\n"
        if product_mode and req.comment_text:
            extra += (f"Khung đầu trả lời bình luận thật của khách {req.comment_name or ''}: \"{req.comment_text}\" "
                      "(cảm ơn và trả lời đúng ý bình luận).\n")
        if req.brand:
            extra += f"Tên thương hiệu/shop: {req.brand}.\n"
        script = write_script(llm, req, ai_templates, images, extra)
        self._check_cancel()

        created = datetime.now()
        job_dir = unique_dir(s.output_dir / f"{slugify(script['title'])}_{created:%Y%m%d_%H%M%S}")
        self._new_dir = job_dir
        asset_info = None
        if product_mode:
            asset_info = import_assets(job_dir, layout, products)
            template = (custom_template(job_dir) if asset_info["layout_html"]
                        else registry.get(STYLE_TEMPLATES[req.product_style]))
            self._log(f"Tài liệu mẫu: {len(products)} ảnh sản phẩm"
                      + (f" · layout {layout.name}" if layout else " · layout showcase mặc định"))
        elif template is None:
            chosen = registry.get(script["template_id"])
            template = chosen if chosen and not chosen.hidden else registry.guess(req.topic)
        self._log(f"Kịch bản: “{script['title']}” · {len(script['scenes'])} khung · template {template.name}")
        job = {
            "id": job_dir.name, "title": script["title"], "topic": req.topic, "genre": req.genre,
            "template_id": template.id, "template_name": template.name, "aspect": req.aspect,
            "width": width, "height": height, "fps": fps, "voice": req.voice, "rate": req.rate,
            "subtitles": req.subtitles, "bgm": req.bgm, "bgm_volume": float(s.get("bgm_volume") or 0.12),
            "subtitle_margin": template.subtitle_margin, "created_at": created.isoformat(timespec="seconds"),
            "duration": 0,
            "scenes": [{"index": i, **scene, "duration": req.seconds} for i, scene in enumerate(script["scenes"], 1)],
        }
        if asset_info:
            job["assets"] = asset_info
        if req.brand:
            job["brand"] = req.brand
        if product_mode and req.comment_text:
            job["comment"] = {"name": req.comment_name, "text": req.comment_text}
        if product_mode:
            job["offer"] = {"price": req.price, "old_price": req.old_price, "perk": req.perk, "contact": req.contact}
            job["features"] = script.get("features") or []
        save_job(job_dir, job)
        scenes, n = job["scenes"], len(job["scenes"])

        names = (asset_info or {}).get("products") or []
        keep_audio = req.keep_audio and bool(names) and all(is_video_name(x) for x in names)
        if product_mode and req.keep_audio and not keep_audio:
            self._log("Giữ tiếng gốc chỉ dùng được khi mọi file sản phẩm đều là video — dùng giọng AI", "warn")
        self._progress(20, "Đang thu giọng đọc", "voice")
        if keep_audio:
            self._log("Dùng tiếng gốc của video (tắt giọng AI và phụ đề karaoke)")
            job["voice_lead"], job["subtitles"] = 0.0, False
            assign_media(job_dir, scenes, names)
            for scene in scenes:
                sdir = job_dir / "scenes" / scene_dir_name(scene["index"])
                sdir.mkdir(parents=True, exist_ok=True)
                media = scene["media"]
                extract_audio(job_dir / "assets" / media["file"], media["start"], scene["duration"], sdir / "voice.mp3")
                scene["words"], scene["voice_duration"] = [], scene["duration"]
        else:
            self._log("Đang thu giọng đọc")
            for k, scene in enumerate(scenes):
                self._check_cancel()
                sdir = job_dir / "scenes" / scene_dir_name(scene["index"])
                sdir.mkdir(parents=True, exist_ok=True)
                voice_path = sdir / "voice.mp3"
                scene["words"] = synthesize(scene["narration"], req.voice, req.rate, voice_path)
                scene["voice_duration"] = round(ffmpeg.media_duration(voice_path), 3)
                scene["duration"] = round(max(req.seconds, scene["voice_duration"] + VOICE_LEAD + SCENE_TAIL), 3)
                self._progress(20 + 14 * (k + 1) / n, f"Đang thu giọng đọc {k + 1}/{n}", "voice")
            if names:
                assign_media(job_dir, scenes, names)
        job["duration"] = round(sum(sc["duration"] for sc in scenes), 3)
        save_job(job_dir, job)

        with SceneRenderer(width, height, fps, cancel=self._cancel, log=self._log) as renderer:
            for k, scene in enumerate(scenes):
                self._check_cancel()
                sdir = job_dir / "scenes" / scene_dir_name(scene["index"])
                base = 35 + 50 * k / n
                label = f"{k + 1}/{n}"
                self._log(f"Đang thiết kế khung hình {label}")
                self._progress(base, f"Đang thiết kế khung hình {label}", "visual")
                design_scene(renderer, template, job, scene, sdir / "scene.html", llm, self._log)
                save_job(job_dir, job)
                self._log(f"Đang dựng khung hình {label}")
                renderer.render(
                    sdir / "scene.html", sdir / "scene.mp4", scene["duration"], sdir / "thumb.jpg",
                    on_progress=lambda f, b=base, lb=label: self._progress(
                        b + 50 / n * (0.1 + 0.9 * f), f"Đang dựng khung hình {lb}", "visual"),
                    background=self._background(job_dir, scene),
                )

        compose(job_dir, job, log=self._post_logger(86, 97), check_cancel=self._check_cancel,
                music_dir=s.get("music_dir"), cleanup=bool(s.get("cleanup_temp")))
        return self._finish(job_dir, job)

    def _run_ai_video(self, template, variables: dict, attachments: list, options: dict, engine: str,
                      show_browser: bool, fallback_form: dict | None = None,
                      step_profiles: dict | None = None) -> dict:
        """Template video AI: điền prompt (+ ảnh tham chiếu) → engine (Grok / Gemini Veo) tạo video → chuẩn hoá.
        Template có image_steps: chạy lần lượt các bước tạo ảnh trước, mỗi bước dùng profile trong step_profiles."""
        s = self.settings
        spec = ENGINES[engine]
        self._progress(2, "Đang chuẩn bị", "prepare")
        self._log("Đang chuẩn bị")
        self.license.require_active()
        attachments = dedupe_attachments(attachments, self._log)  # cùng 1 ảnh ở 2 vai trò → gửi 1 lần
        if len(attachments) > spec["max_images"]:
            dropped = ", ".join(a[0]["label"] for a in attachments[spec["max_images"]:])
            self._log(f"{spec['name']} nhận tối đa {spec['max_images']} ảnh — bỏ qua: {dropped}", "warn")
            attachments = attachments[:spec["max_images"]]
        if attachments:
            self._log("Ảnh tham chiếu: " + ", ".join(f"{a[0]['label']} ({a[1].name})" for a in attachments))
        aspect = options.get("aspect", "9:16")
        self._progress(8, "Đang điền prompt template", "script")
        self._log(f"Template video AI: {template.name} · {spec['name']} · {aspect} · "
                  f"{options.get('duration', '')} · {options.get('resolution', '')}")

        title = " · ".join([template.name, *[v for v in variables.values() if v][:1]])
        created = datetime.now()
        job_dir = unique_dir(s.output_dir / f"{slugify(title)}_{created:%Y%m%d_%H%M%S}")
        (job_dir / "tmp").mkdir()
        self._new_dir = job_dir
        raw = job_dir / "tmp" / "grok_raw.mp4"
        video_start = 12
        steps = template.image_steps
        if steps:
            files = {spec["key"]: (spec, path) for spec, path in attachments}
            span = 46 / len(steps)
            for i, step in enumerate(steps):
                with self._step_profile(step_profiles, step["key"]):
                    path = self._run_image_step(step, i, len(steps), files, variables, engine, job_dir,
                                                show_browser, 12 + span * i)
                files[step["key"]] = ({"key": step["key"], "label": step.get("label", step["key"])}, path)
            attachments = video_inputs(template, files)
            video_start = 60
        attachments = prepare_video_refs(attachments, spec, self._log)  # video tham chiếu → gửi nguyên video nếu model nhận
        prompt = template_prompt(template, variables, attachments) + reference_sentence([a[0] for a in attachments])
        self._log(f"Prompt: {prompt[:180]}…")
        images = import_attachments(job_dir, attachments)

        step_label = f"Bước {len(steps) + 1}/{len(steps) + 1}: " if steps else ""
        self._progress(video_start, f"{step_label}Đang tạo video bằng {spec['name']}", "visual")
        self._log(f"{step_label}Đang mở {spec['name']}")
        try:
            with self._step_profile(step_profiles, "video"):
                generate_video(
                    engine, prompt, raw, options=options, images=images, settings=s, show_browser=show_browser,
                    log=self._log, check_cancel=self._check_cancel,
                    on_progress=lambda pct: self._progress(video_start + (84 - video_start) * pct / 100,
                                                           f"{step_label}Đang tạo video {pct}%", "visual"),
                )
        except VeoUnavailable as exc:
            if fallback_form is None:
                raise
            self._log(f"{exc} → chuyển sang tạo video thông thường (Gemini viết kịch bản, app tự dựng)", "warn")
            shutil.rmtree(job_dir, ignore_errors=True)
            self._new_dir = None
            return self._run_new(JobRequest.from_form(fallback_form))
        self._log(f"Đã tải video từ {spec['name']}")

        self._progress(88, "Đang chuẩn hoá video & cân âm lượng", "post")
        self._log("Đang chuẩn hoá video & cân âm lượng")
        info = finalize(raw, job_dir, aspect, log=self._log)
        job = {
            "id": job_dir.name, "kind": "ai_video", "engine": engine, "title": title, "topic": prompt,
            "genre": "ai_video", "template_id": template.id, "template_name": template.name, "aspect": aspect,
            "width": info["width"], "height": info["height"], "fps": 30, "voice": "", "subtitles": False,
            "bgm": False, "created_at": created.isoformat(timespec="seconds"), "duration": info["duration"],
            "prompt": prompt, "variables": variables, "options": options,
            "attachments": {spec["key"]: img.name for (spec, _), img in zip(attachments, images)},
            "scenes": [{"index": 1, "kicker": "", "headline": title, "duration": info["duration"]}],
        }
        if s.get("cleanup_temp"):
            shutil.rmtree(job_dir / "tmp", ignore_errors=True)
        return self._finish(job_dir, job)

    @staticmethod
    def _whiteboard_form(template, form: dict) -> dict:
        """Kiểm tra form template whiteboard: nội dung SRT/kịch bản (gõ hoặc file .srt), audio, engine ảnh."""
        from pathlib import Path
        from . import whiteboard as wbm

        raw = dict(form.get("wb") or {})
        opts = template.options
        text = str(raw.get("text") or "").strip()
        srt_file = str(raw.get("srt") or "").strip()
        if srt_file:
            if not Path(srt_file).is_file():
                raise ValueError(f"Không còn file SRT: {Path(srt_file).name}")
            text = wbm.read_srt_file(srt_file)
        if not text:
            raise ValueError("Hãy dán nội dung SRT / kịch bản hoặc chọn file .srt")
        if wbm.is_srt(text) and not wbm.parse_srt(text):
            raise ValueError("Nội dung SRT không đọc được câu nào (kiểm tra mốc 00:00:01,000 --> 00:00:03,000)")
        audio = str(raw.get("audio") or "").strip()
        if audio and not Path(audio).is_file():
            raise ValueError(f"Không còn file âm thanh: {Path(audio).name}")
        engine = str(raw.get("image_engine") or opts.get("image_engine") or "")
        if engine not in IMAGE_ENGINES:
            raise ValueError("Chọn model tạo ảnh line-art cho whiteboard")
        aspect = str(raw.get("aspect") or opts.get("aspect") or "16:9")
        return {
            "text": text, "srt_name": Path(srt_file).name if srt_file else "", "audio": audio,
            "image_engine": engine, "profile": str(raw.get("profile") or "") if IMAGE_ENGINES[engine].get("browser") else "",
            "aspect": aspect if aspect in wbm.SIZES else "16:9",
            "quality": "hd" if raw.get("quality", opts.get("quality")) == "hd" else "fast",
            "hand": bool(raw.get("hand", opts.get("hand", True))),
            "subtitles": bool(raw.get("subtitles", opts.get("subtitles", True))),
            "voice": str(form.get("voice") or "vi-VN-HoaiMyNeural"), "rate": str(form.get("rate") or "+0%"),
            "hint": str(raw.get("hint") or "").strip()[:300],
            "show_browser": bool(form.get("show_browser")),
        }

    def _run_whiteboard(self, template, wb: dict) -> dict:
        """Template SRT Whiteboard: SRT/kịch bản → ảnh line-art từng cảnh → tay vẽ đúng mốc → ghép tiếng + phụ đề."""
        from pathlib import Path
        from . import whiteboard as wbm

        s = self.settings
        self._progress(2, "Đang chuẩn bị", "prepare")
        self.license.require_active()
        created = datetime.now()
        first = " ".join(wb["text"].split())[:40] if not wbm.is_srt(wb["text"]) else (wb["srt_name"] or "SRT")
        title = f"{template.name} · {first}"
        job_dir = unique_dir(s.output_dir / f"{slugify(title)}_{created:%Y%m%d_%H%M%S}")
        work = job_dir / "tmp"
        work.mkdir(parents=True)
        self._new_dir = job_dir
        self._progress(5, "Đang kiểm tra bộ dựng whiteboard", "prepare")
        wbm.ensure_installed(self._log)
        self._progress(8, "Đang đọc phụ đề / kịch bản", "script")
        audio = Path(wb["audio"]) if wb["audio"] else None
        cues, audio = wbm.load_cues(wb["text"], work, voice=wb["voice"], rate=wb["rate"], audio=audio)
        self._log(f"{len(cues)} câu phụ đề · {'file âm thanh đính kèm' if wb['audio'] else 'giọng AI ' + wb['voice']}")
        spec = IMAGE_ENGINES[wb["image_engine"]]
        self._log(f"Ảnh line-art: {spec['name']} · dựng {'nét (1920)' if wb['quality'] == 'hd' else 'nhanh (1080)'}"
                  f" · {'có' if wb['hand'] else 'không'} bàn tay")
        make_image = wbm.image_maker(wb["image_engine"], s, show_browser=wb["show_browser"], log=self._log,
                                     check_cancel=self._check_cancel)
        raw = wbm.build_video(
            cues, work / "wb", make_image=make_image, aspect=wb["aspect"], audio=audio, voice=wb["voice"],
            rate=wb["rate"], subtitles=wb["subtitles"], quality=wb["quality"], hand=wb["hand"], hint=wb["hint"],
            log=self._log, check_cancel=self._check_cancel,
            progress=lambda f, msg: self._progress(10 + 76 * f, msg, "visual"))
        self._progress(88, "Đang chuẩn hoá video & cân âm lượng", "post")
        info = finalize(raw, job_dir, wb["aspect"], log=self._log)
        if (raw.parent / "final.srt").is_file():
            shutil.copy2(raw.parent / "final.srt", job_dir / "final.srt")
        job = {
            "id": job_dir.name, "kind": "whiteboard", "engine": wb["image_engine"], "title": title,
            "topic": " ".join(c["text"] for c in cues)[:500], "genre": "whiteboard", "template_id": template.id,
            "template_name": template.name, "aspect": wb["aspect"], "width": info["width"], "height": info["height"],
            "fps": 30, "voice": "" if wb["audio"] else wb["voice"], "subtitles": wb["subtitles"], "bgm": False,
            "created_at": created.isoformat(timespec="seconds"), "duration": info["duration"],
            "options": {k: wb[k] for k in ("quality", "hand", "subtitles", "aspect", "image_engine")},
            "scenes": [{"index": 1, "kicker": "", "headline": title, "duration": info["duration"]}],
        }
        if s.get("cleanup_temp"):
            shutil.rmtree(work, ignore_errors=True)
        return self._finish(job_dir, job)

    def _step_profile(self, step_profiles: dict | None, key: str):
        """Template nhiều bước: dùng profile chọn cho bước `key` ("" = tự chọn profile rảnh gán cho model đó)."""
        if step_profiles is None:
            return nullcontext()
        return task_context(step_profiles.get(key, ""), check_cancel=self._check_cancel, log=self._log)

    def _run_image_step(self, step: dict, index: int, total: int, files: dict, variables: dict, video_engine: str,
                        job_dir, show_browser: bool, pct: float):
        """Một bước image_steps: gửi ảnh đầu vào (video → 1 khung hình) + prompt cho engine ảnh, trả về ảnh kết quả.
        Engine ảnh: step.engine (vd. chatgpt_browser), mặc định cùng nhà cung cấp với engine video."""
        engine = step.get("engine") or video_engine
        spec = IMAGE_ENGINES[engine]
        label = f"Bước {index + 1}/{total + 1}: {step.get('label', step['key'])}"
        inputs = step_inputs(step, files)[:spec["max_images"]]
        prompt = fill_prompt(step["prompt"], variables) + reference_sentence([a[0] for a in inputs])
        refs = import_attachments(job_dir, inputs)
        want = step.get("aspect", "9:16")
        aspect = want if want in spec["aspects"] else spec["aspects"][0]
        self._progress(pct, f"{label} ({spec['name']})", "visual")
        self._log(f"{label} · {spec['name']} · {aspect}")
        self._log(f"Prompt ảnh: {prompt[:180]}…")
        datas = generate_image(engine, prompt, aspect=aspect, count=1, quality="high", images=refs,
                               settings=self.settings, show_browser=show_browser, log=self._log,
                               check_cancel=self._check_cancel)
        out_dir = job_dir / "tmp" / step["key"]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = save_images(datas[:1], out_dir)[0]
        fit_aspect(path, aspect)
        self._log(f"Xong {label}", "ok")
        return path

    def _run_rerender(self, job_id: str, index: int) -> dict:
        s = self.settings
        self.license.require_active()
        job_dir, job = load_job(s.output_dir, job_id)
        if job.get("kind") in ("ai_video", "whiteboard"):
            raise ValueError("Video AI / whiteboard không render lại từng cảnh được — hãy tạo video mới")
        scene = next((sc for sc in job["scenes"] if sc["index"] == index), None)
        if scene is None:
            raise ValueError(f"Không có khung {index}")
        sdir = job_dir / "scenes" / scene_dir_name(index)
        self._log(f"Đang dựng lại khung hình {index}")
        self._progress(5, f"Đang dựng lại khung hình {index}", "visual")
        with SceneRenderer(job["width"], job["height"], job["fps"], cancel=self._cancel, log=self._log) as renderer:
            renderer.render(sdir / "scene.html", sdir / "scene.mp4", scene["duration"], sdir / "thumb.jpg",
                            on_progress=lambda f: self._progress(5 + 75 * f, f"Đang dựng lại khung hình {index}", "visual"),
                            background=self._background(job_dir, scene))
        compose(job_dir, job, log=self._post_logger(82, 97), check_cancel=self._check_cancel,
                music_dir=s.get("music_dir"), cleanup=bool(s.get("cleanup_temp")))
        return self._finish(job_dir, job)

    @staticmethod
    def _background(job_dir, scene: dict):
        media = scene.get("media")
        return (job_dir / "assets" / media["file"], float(media["start"])) if media else None

    def _finish(self, job_dir, job) -> dict:
        self._progress(98, "Đang lưu vào thư viện", "finish")
        self._log("Đang lưu vào thư viện")
        save_job(job_dir, job)
        self._log("Đã xong một video", "ok")
        self._progress(100, "Hoàn tất", "finish")
        return summary(job_dir, job)
