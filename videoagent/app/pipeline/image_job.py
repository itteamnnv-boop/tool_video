"""Tác vụ tạo hình ảnh: prompt (tự nhập hoặc template ảnh) → engine (OpenAI / Gemini / Grok / Dola) → _images/."""
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..image_library import IMAGES_DIR, summary
from ..llm.image_engines import ENGINES, fit_aspect, generate, normalize, save_images
from ..templates_registry import registry
from ..util import slugify, unique_dir, write_json
from . import Cancelled
from .tasks import TaskPool
from .ai_video import (IMAGE_EXT, collect_attachments, collect_variables, fill_prompt, import_attachments,
                       reference_sentence)

log = logging.getLogger(__name__)
FREE_REF = {"role": "reference image", "prompt": "use it as a visual reference for subject, style and composition"}
QUALITIES = {"auto", "low", "medium", "high"}
PCT_RE = re.compile(r"Đang tạo ảnh (\d{1,3})%")
PIN_MAX = 6
PIN_REF = {"role": "Pinterest reference", "prompt": ("use it only as inspiration for composition, style, colors and "
                                                    "mood — do not copy its watermark, text, logos or exact content")}


class ImageRunner:
    """Tạo ảnh — nhiều tác vụ chạy song song qua TaskPool (sự kiện image_*)."""

    def __init__(self, settings, license_mgr, emit) -> None:
        self.settings = settings
        self.license = license_mgr
        self.pool = TaskPool("image_", emit, lambda: settings.get("max_parallel_image") or 2)

    @property
    def running(self) -> bool:
        return self.pool.running

    def cancel(self, task_id: str = "") -> int:
        return self.pool.cancel(task_id)

    def start(self, form: dict) -> str:
        """Thêm một tác vụ tạo ảnh vào hàng đợi, trả về id tác vụ."""
        engine = str(form.get("engine") or "")
        if engine not in ENGINES:
            raise ValueError("Hãy chọn model tạo ảnh")
        template = registry.get(str(form.get("template") or ""))
        if template is not None and template.kind == "ai_image":
            variables = collect_variables(template, form.get("variables"))
            attachments = collect_attachments(template, {})  # ảnh mẫu đóng gói trong template
            prompt = fill_prompt(template.prompt, variables)
            title = " · ".join([template.name, *[v for v in variables.values() if v][:1]])
        else:
            prompt = str(form.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("Hãy nhập mô tả ảnh (prompt)")
            attachments, title = [], " ".join(prompt.split()[:8])
        for i, raw in enumerate(form.get("refs") or [], 1):
            path = Path(str(raw))
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
                raise ValueError(f"Ảnh tham chiếu không hợp lệ: {path.name}")
            attachments.append(({"key": f"ref{i}", "label": f"Ảnh tham chiếu {i}", **FREE_REF}, path))
        aspect, count = normalize(engine, str(form.get("aspect") or ""), int(form.get("count") or 1))
        quality = form.get("quality") if form.get("quality") in QUALITIES else "auto"
        pin = form.get("pinterest") or {}
        pinterest = None
        if pin.get("on"):
            keyword = str(pin.get("keyword") or "").strip()
            urls = [str(u) for u in pin.get("urls") or [] if str(u).startswith("https://i.pinimg.com/")]
            if not keyword and not urls:
                raise ValueError("Bật 'Tham khảo ảnh Pinterest' thì cần nhập từ khoá tìm kiếm")
            pinterest = {"keyword": keyword, "urls": urls[:PIN_MAX], "count": max(1, min(PIN_MAX, int(pin.get("count") or 3)))}
        job = dict(engine=engine, prompt=prompt, title=title, attachments=attachments, aspect=aspect, count=count,
                   quality=quality, show_browser=bool(form.get("show_browser")), pinterest=pinterest)
        return self.pool.submit(title, self._job, job, profile=str(form.get("browser_profile") or ""),
                                meta={"kind": "image", "engine": engine, "count": count})

    def _log(self, message: str, level: str = "info") -> None:
        self.pool.log(message, level)
        match = PCT_RE.search(message)  # engine trình duyệt báo "Đang tạo ảnh 42%"
        if match:
            self._progress(20 + 0.7 * int(match.group(1)), message, "generate")

    def _progress(self, pct: float, status: str, stage: str) -> None:
        self.pool.progress(pct, status, stage)

    def _pinterest_refs(self, pin: dict, job_dir: Path) -> list:
        """Tải ảnh Pinterest (đã chọn ở giao diện, hoặc tự tìm theo từ khoá) làm ảnh tham chiếu."""
        from ..llm import pinterest

        self._progress(6, "Đang lấy ảnh tham khảo Pinterest", "prepare")
        urls = pin["urls"]
        if not urls:
            self._log(f"Đang tìm ảnh Pinterest: “{pin['keyword']}”")
            urls = [r["url"] for r in pinterest.search(pin["keyword"], limit=pin["count"], log=self._log)]
        self._check_cancel()
        paths = pinterest.download(urls[:pin["count"]], job_dir / "pinterest", log=self._log)
        if not paths:
            self._log("Không tải được ảnh Pinterest nào — tạo ảnh không có tham khảo Pinterest", "warn")
        else:
            self._log(f"Đã tải {len(paths)} ảnh tham khảo Pinterest")
        return [({"key": f"pin{i}", "label": f"Pinterest {i}", **PIN_REF}, p) for i, p in enumerate(paths, 1)]

    def _check_cancel(self) -> None:
        self.pool.check_cancel()

    def _job(self, job: dict) -> dict:
        job_dir, meta = self._run(job)
        return summary(job_dir, meta)

    def _run(self, job: dict) -> tuple[Path, dict]:
        self._progress(3, "Đang chuẩn bị", "prepare")
        self._log("Đang chuẩn bị")
        self.license.require_active()
        spec = ENGINES[job["engine"]]
        created = datetime.now()
        job_dir = unique_dir(self.settings.output_dir / IMAGES_DIR / f"{slugify(job['title'])}_{created:%Y%m%d_%H%M%S}")
        try:
            attachments = list(job["attachments"])
            if job["pinterest"]:
                attachments += self._pinterest_refs(job["pinterest"], job_dir)
            if len(attachments) > spec["max_images"]:
                self._log(f"{spec['name']} nhận tối đa {spec['max_images']} ảnh tham chiếu — bỏ bớt ảnh thừa", "warn")
                attachments = attachments[:spec["max_images"]]
            prompt = job["prompt"] + reference_sentence([a[0] for a in attachments])
            refs = import_attachments(job_dir, attachments)
            self._log(f"{spec['name']} · {job['aspect']} · {job['count']} ảnh"
                      + (f" · {len(refs)} ảnh tham chiếu" if refs else ""))
            self._progress(12, f"Đang gửi prompt cho {spec['name']}", "send")
            datas = generate(job["engine"], prompt, aspect=job["aspect"], count=job["count"], quality=job["quality"],
                             images=refs, settings=self.settings, show_browser=job["show_browser"], log=self._log,
                             check_cancel=self._check_cancel)
        except BaseException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        self._progress(92, "Đang lưu ảnh", "download")
        paths = save_images(datas, job_dir)
        cropped = sum(fit_aspect(p, job["aspect"]) for p in paths)
        if cropped:
            self._log(f"Đã cắt {cropped} ảnh về đúng tỉ lệ {job['aspect']}")
        meta = {"id": job_dir.name, "title": job["title"], "prompt": prompt, "engine": job["engine"],
                "pinterest": (job["pinterest"] or {}).get("keyword", ""),
                "engine_name": spec["name"], "aspect": job["aspect"], "count": len(paths),
                "created_at": created.isoformat(timespec="seconds"), "files": [p.name for p in paths]}
        write_json(job_dir / "meta.json", meta)
        self._log(f"Đã tạo {len(paths)} ảnh", "ok")
        self._progress(100, "Hoàn tất", "finish")
        return job_dir, meta
