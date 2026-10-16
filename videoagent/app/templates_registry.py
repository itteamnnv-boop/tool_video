"""Thư viện template: templates/<nhóm>/<id>/meta.json (+ template.html với template HTML).

- Template HTML (mặc định): template.html Jinja2 → app dựng hình từng khung.
- Template video AI ("type": "ai_video"): chỉ có meta.json với prompt chứa biến {Bien}; app gửi prompt cho
  engine (vd. Grok Imagine) tạo video.
Thêm template mới = tạo thư mục mới; app tự nhận khi khởi động.
"""
import json
import random
import threading
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .paths import TEMPLATES_DIR

CATEGORIES = [
    {"id": "sales", "name": "Bán hàng & Quảng cáo", "icon": "◆"},
    {"id": "tech", "name": "Công nghệ & AI", "icon": "▶"},
    {"id": "news", "name": "Tin tức & Thời sự", "icon": "◎"},
    {"id": "finance", "name": "Tài chính & Đầu tư", "icon": "▥"},
    {"id": "education", "name": "Giáo dục & Kiến thức", "icon": "○"},
    {"id": "story", "name": "Giải trí & Kể chuyện", "icon": "◐"},
    {"id": "agri", "name": "Nông nghiệp", "icon": "🌾"},
    {"id": "food", "name": "Ẩm thực", "icon": "🍜"},
    {"id": "general", "name": "Đa dụng", "icon": "❖"},
]
SHARED_DIR = TEMPLATES_DIR / "_shared"
THUMB_NAMES = ("thumb.jpg", "thumb.png", "thumb.webp")


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    category: str
    description: str
    path: Path
    tags: tuple = field(default_factory=tuple)
    subtitle_margin: float = 0.07
    hidden: bool = False  # chỉ dùng nội bộ (vd. showcase của thể loại sản phẩm), không hiện trong danh sách chọn
    kind: str = "html"  # "html" | "ai_video"
    engine: str = ""  # với ai_video: "grok_imagine"
    prompt: str = ""
    variables: tuple = field(default_factory=tuple)  # ({key, label, placeholder, required}, ...)
    options: dict = field(default_factory=dict)  # với ai_video: {aspect, duration, resolution}
    attachments: tuple = field(default_factory=tuple)  # ảnh tham chiếu: ({key, label, role, prompt, video}, ...)

    @property
    def thumb(self) -> Path | None:
        return next((self.path / n for n in THUMB_NAMES if (self.path / n).exists()), None)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category, "description": self.description,
                "tags": list(self.tags), "kind": self.kind, "engine": self.engine, "prompt": self.prompt,
                "variables": list(self.variables), "options": dict(self.options),
                "attachments": list(self.attachments), "has_thumb": self.thumb is not None}


class TemplateRegistry:
    def __init__(self, root: Path = TEMPLATES_DIR) -> None:
        self.root = root
        self._envs: dict[str, Environment] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        templates = []
        for meta_file in sorted(self.root.glob("*/*/meta.json")):
            folder = meta_file.parent
            if folder.parent.name.startswith("_"):
                continue
            meta = json.loads(meta_file.read_text("utf-8"))
            kind = meta.get("type") if meta.get("type") in ("ai_video", "ai_image") else "html"
            prompt = meta.get("prompt", "")
            if isinstance(prompt, list):  # prompt dài viết thành mảng dòng cho dễ đọc
                prompt = "\n".join(prompt)
            if kind == "html" and not (folder / "template.html").exists():
                continue
            templates.append(Template(
                id=folder.name, name=meta.get("name", folder.name), category=folder.parent.name,
                description=meta.get("description", ""), path=folder, tags=tuple(meta.get("tags", [])),
                subtitle_margin=float(meta.get("subtitle_margin", 0.07)), hidden=bool(meta.get("hidden")),
                kind=kind, engine=meta.get("engine", ""), prompt=prompt,
                variables=tuple(meta.get("variables", [])), options=dict(meta.get("options", {})),
                attachments=tuple(meta.get("attachments", [])),
            ))
        self._templates = {t.id: t for t in templates}
        self._envs.clear()

    def all(self) -> list[Template]:
        """Template HTML chọn được — dùng cho 'Ngẫu nhiên' và 'AI chọn template'."""
        return [t for t in self._templates.values() if not t.hidden and t.kind == "html"]

    def listed(self) -> list[Template]:
        """Mọi template video hiện trong bộ chọn (HTML + video AI)."""
        return [t for t in self._templates.values() if not t.hidden and t.kind != "ai_image"]

    def image_templates(self) -> list[Template]:
        """Template ảnh (trang Tạo hình ảnh)."""
        return [t for t in self._templates.values() if not t.hidden and t.kind == "ai_image"]

    def get(self, template_id: str) -> Template | None:
        return self._templates.get(template_id)

    def in_category(self, category: str) -> list[Template]:
        return [t for t in self.all() if t.category == category]

    def categories(self) -> list[dict]:
        return [{**c, "templates": [t.as_dict() for t in self.listed() if t.category == c["id"]]} for c in CATEGORIES]

    def pick(self, choice: str) -> Template | None:
        """'random' | 'category:<id>' | '<template id>' → Template; 'ai' → None (để AI chọn)."""
        if choice == "random":
            return random.choice(self.all())
        if choice.startswith("category:"):
            pool = self.in_category(choice.split(":", 1)[1])
            return random.choice(pool) if pool else random.choice(self.all())
        found = self.get(choice)
        return found if found is not None and found.kind == "html" else None

    def guess(self, topic: str) -> Template:
        """Chọn template theo từ khoá khi AI không chọn được."""
        text = topic.lower()
        scored = [(sum(tag in text for tag in t.tags), t) for t in self.all()]
        best = max(score for score, _ in scored)
        pool = [t for score, t in scored if score == best]
        return random.choice(pool)

    def render(self, template: Template, context: dict) -> str:
        with self._lock:
            env = self._envs.get(template.id)
            if env is None:
                env = Environment(
                    loader=FileSystemLoader([str(template.path), str(SHARED_DIR)]),
                    autoescape=select_autoescape(["html"]),
                )
                self._envs[template.id] = env
        return env.get_template("template.html").render(**context)


registry = TemplateRegistry()
