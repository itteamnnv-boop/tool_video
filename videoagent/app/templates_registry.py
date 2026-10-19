"""Thư viện template: templates/<nhóm>/<id>/meta.json (+ template.html với template HTML).

- Template HTML (mặc định): template.html Jinja2 → app dựng hình từng khung.
- Template video AI ("type": "ai_video"): chỉ có meta.json với prompt chứa biến {Bien}; app gửi prompt cho
  engine (vd. Grok Imagine) tạo video.
Thêm template mới = tạo thư mục mới; app tự nhận khi khởi động.
Template người dùng tự tạo (màn hình Workflow → Tạo video → + Tạo template) nằm ở <thư mục dữ liệu>/user_templates/<nhóm>/<id>/.
"""
import json
import random
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .paths import DATA_DIR, TEMPLATES_DIR
from .util import slugify

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
USER_TEMPLATES_DIR = DATA_DIR / "user_templates"
VAR_RE = re.compile(r"\{(\w+)\}")
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
    kind: str = "html"  # "html" | "ai_video" | "ai_image" | "whiteboard" (SRT → tay vẽ)
    engine: str = ""  # với ai_video: "grok_imagine"
    prompt: str = ""
    variables: tuple = field(default_factory=tuple)  # ({key, label, placeholder, required}, ...)
    options: dict = field(default_factory=dict)  # với ai_video: {aspect, duration, resolution}
    attachments: tuple = field(default_factory=tuple)  # ảnh tham chiếu: ({key, label, role, prompt, video}, ...)
    # với ai_video: các bước tạo ảnh chạy trước khi tạo video + file gửi cho bước video (xem ai_video.py)
    image_steps: tuple = field(default_factory=tuple)  # ({key, label, engine, aspect, prompt, inputs}, ...)
    video_inputs: tuple = field(default_factory=tuple)  # ({key, role, prompt}, ...)
    video_engine: str = ""  # với ai_video: cố định engine tạo video (vd. "grok_browser"), bỏ qua Provider đang chọn
    video_prompt: str = ""  # prompt dùng thay khi ô tham chiếu (send_video) là file video ("video_reference_prompt")
    computed: dict = field(default_factory=dict)  # biến tự ghép từ biến khác, vd. {"FULL_SCRIPT": "{HOOK} {CTA}"}
    user: bool = False  # template người dùng tự tạo (sửa / xoá được)

    @property
    def thumb(self) -> Path | None:
        return next((self.path / n for n in THUMB_NAMES if (self.path / n).exists()), None)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "category": self.category, "description": self.description,
                "tags": list(self.tags), "kind": self.kind, "engine": self.engine, "prompt": self.prompt,
                "variables": list(self.variables), "options": dict(self.options),
                "attachments": list(self.attachments), "image_steps": list(self.image_steps),
                "video_inputs": list(self.video_inputs), "video_engine": self.video_engine,
                "video_prompt": self.video_prompt, "computed": dict(self.computed),
                "has_thumb": self.thumb is not None, "user": self.user}


def _image_steps(raw) -> tuple:
    """Các bước image_steps trong meta.json; prompt dài được viết thành mảng dòng như prompt chính."""
    return tuple({**step, "prompt": "\n".join(step["prompt"]) if isinstance(step.get("prompt"), list)
                  else step.get("prompt", "")} for step in raw or [])


class TemplateRegistry:
    def __init__(self, root: Path = TEMPLATES_DIR, user_root: Path = USER_TEMPLATES_DIR) -> None:
        self.root = root
        self.user_root = user_root
        self._envs: dict[str, Environment] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        templates = []
        files = [(f, False) for f in sorted(self.root.glob("*/*/meta.json"))]
        files += [(f, True) for f in sorted(self.user_root.glob("*/*/meta.json"))] if self.user_root.exists() else []
        for meta_file, user in files:
            folder = meta_file.parent
            if folder.parent.name.startswith("_"):
                continue
            try:
                meta = json.loads(meta_file.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                if user:  # template người dùng hỏng không được làm hỏng cả thư viện
                    continue
                raise
            kind = meta.get("type") if meta.get("type") in ("ai_video", "ai_image", "whiteboard") else "html"
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
                attachments=tuple(meta.get("attachments", [])), image_steps=_image_steps(meta.get("image_steps")),
                video_inputs=tuple(meta.get("video_inputs", [])), video_engine=meta.get("video_engine", ""), user=user,
                video_prompt="\n".join(meta["video_reference_prompt"]) if isinstance(meta.get("video_reference_prompt"), list)
                else meta.get("video_reference_prompt", ""),
                computed=dict(meta.get("computed", {})),
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


    # ------------------------------------------------------------ template video AI người dùng tự tạo
    def save_user_template(self, data: dict) -> "Template":
        """Tạo mới / sửa template video AI của người dùng. Biến lấy từ {TenBien} trong prompt."""
        name = str(data.get("name") or "").strip()[:80]
        prompt = str(data.get("prompt") or "").strip()
        if not name:
            raise ValueError("Hãy đặt tên template")
        if not prompt:
            raise ValueError("Template chưa có prompt")
        category = data.get("category") if data.get("category") in {c["id"] for c in CATEGORIES} else "general"
        given = {str(v.get("key")): v for v in data.get("variables") or [] if isinstance(v, dict)}
        variables = []
        for key in dict.fromkeys(VAR_RE.findall(prompt)):
            v = given.get(key, {})
            variables.append({"key": key, "label": str(v.get("label") or key).strip()[:120],
                              "default": str(v.get("default") or "").strip()[:300],
                              "placeholder": str(v.get("placeholder") or "").strip()[:120],
                              "required": bool(v.get("required", True))})
        options = {k: str(v) for k, v in (data.get("options") or {}).items() if k in ("aspect", "duration", "resolution") and v}
        attachments = [{k: str(a.get(k) or "").strip()[:300] for k in ("key", "label", "hint", "role", "prompt")}
                       | {"required": bool(a.get("required"))}
                       | {k: True for k in ("video", "keep_video") if a.get(k)}
                       for a in data.get("attachments") or [] if isinstance(a, dict) and str(a.get("label") or "").strip()]
        for i, a in enumerate(attachments, 1):
            a["key"] = slugify(a["key"] or a["label"], 20) or f"ref{i}"
            a["role"] = a["role"] or "reference image"
            a["prompt"] = a["prompt"] or "use it as a visual reference"
        old = self.get(str(data.get("id") or ""))
        if old is not None and not old.user:
            raise ValueError("Template có sẵn của app không sửa được — hãy tạo bản sao")
        if old is not None:
            folder = old.path
            if folder.parent.name != category:  # đổi nhóm → chuyển thư mục
                target = self.user_root / category / folder.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(folder), str(target))
                folder = target
        else:
            base = "u-" + slugify(name, 40)
            tid, n = base, 2
            while self.get(tid) is not None or any(self.user_root.glob(f"*/{tid}")):
                tid, n = f"{base}-{n}", n + 1
            folder = self.user_root / category / tid
        folder.mkdir(parents=True, exist_ok=True)
        meta = {"type": "ai_video", "name": name, "description": str(data.get("description") or "").strip()[:300],
                "tags": ["của tôi"], "options": options, "variables": variables, "attachments": attachments,
                "prompt": prompt.split("\n")}
        tmp = folder / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(folder / "meta.json")
        self.reload()
        return self.get(folder.name)

    def delete_user_template(self, template_id: str) -> None:
        found = self.get(template_id)
        if found is None:
            raise ValueError("Không tìm thấy template")
        if not found.user:
            raise ValueError("Không xoá được template có sẵn của app")
        shutil.rmtree(found.path, ignore_errors=True)
        self.reload()


registry = TemplateRegistry()
