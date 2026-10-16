"""Bước thiết kế khung hình — vòng lặp agent: điền template → đo tràn chữ → AI rút gọn → thử lại."""
from pathlib import Path

from jinja2 import TemplateError

from ..templates_registry import Template, registry
from .scene_context import build_context
from .script_writer import shorten_fields

MAX_ROUNDS = 3


def design_scene(renderer, template: Template, job: dict, scene: dict, html_path: Path, llm, log) -> None:
    for round_no in range(1, MAX_ROUNDS + 1):
        try:
            html = registry.render(template, build_context(job, scene))
        except TemplateError as exc:
            raise ValueError(f"Template '{template.name}' lỗi cú pháp Jinja2: {exc}") from exc
        html_path.write_text(html, "utf-8")
        overflow = renderer.overflow(html_path)
        if not overflow:
            return
        if round_no == MAX_ROUNDS:
            log(f"Khung {scene['index']}: chữ vẫn tràn ({', '.join(overflow)}) — giữ bản hiện tại", "warn")
            return
        log(f"Khung {scene['index']}: chữ tràn ({', '.join(overflow)}) → AI rút gọn", "warn")
        scene.update(shorten_fields(llm, scene, overflow))
