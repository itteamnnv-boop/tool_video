"""Chặng 5 → 7b của chiến dịch: kế hoạch nội dung theo Fanpage, sản xuất ảnh/video bằng chức năng Tạo hình ảnh /
Tạo video của hệ thống, rồi lập kế hoạch đăng theo từng page (album / video / ảnh đơn, có hẹn giờ).

Quy mô mặc định ("vừa phải"): 2 ảnh quảng cáo × VARIANTS phương án (trưởng phòng chọn ảnh đẹp nhất), 1 ảnh sản phẩm
studio, 1 poster (chỉ khi phù hợp), tối đa MAX_VIDEOS video dùng chung cho các page.
Mọi tác vụ ảnh/video giao cho hàng đợi của trang Tạo hình ảnh / Tạo video → chạy song song theo giới hạn của trang đó,
hiện ở trang đó và vào thư viện chung; chiến dịch chờ kết quả rồi chép về thư mục chiến dịch.
"""
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from ..image_library import IMAGES_DIR
from ..llm.image_engines import ENGINES as IMAGE_ENGINES
from ..pipeline import Cancelled
from ..pipeline.assets import PRODUCT_GENRE, STYLE_TEMPLATES
from ..pipeline.tts import VOICES
from ..templates_registry import registry
from . import store, tools
from .ai import extract_file, extract_json
from .store import CampaignError

IMAGE_KEYS = ("c1-a", "c1-b")  # 2 ảnh quảng cáo chính (album)
EXTRA_IMAGES = {  # ảnh phụ làm bằng template ảnh của hệ thống: key → (template id, nhãn, tỉ lệ)
    "studio": ("anh-san-pham-studio", "Ảnh sản phẩm studio", "1:1"),
    "poster": ("poster-nong-nghiep", "Poster quảng cáo", "9:16"),
}
TEXT_ENGINES = {"openai_api", "chatgpt_browser", "gemini_api", "gemini_browser"}  # vẽ chữ tiếng Việt đọc được
VARIANTS = 2  # số phương án mỗi ảnh quảng cáo
VIDEO_KINDS = {"sale": "Video bán hàng", "template": "Video AI theo template", "explainer": "Video kiến thức",
               "ai": "Video AI từ ảnh (Grok)"}
VIDEO_KIND_CHOICES = ("auto", *VIDEO_KINDS)  # "auto" = trưởng phòng chọn
EXPLAINER_GENRES = {"explainer": "Giải thích kiến thức", "listicle": "Top / Danh sách", "story": "Kể chuyện"}
AI_VIDEO_TEMPLATE = "anh-thanh-video"
AI_VIDEO_ENGINE = "grok_browser"  # engine video cho template video AI không cố định engine
MAX_VIDEOS = 2
VIDEO_TOPIC_LIMIT = 2500
POST_TYPES = {"album": "Album ảnh", "video": "Video", "anh": "Ảnh đơn"}
SCHEDULE_MIN = timedelta(minutes=20)  # Facebook: hẹn giờ ≥ 10 phút, ≤ 30 ngày (giữ biên an toàn)
SCHEDULE_MAX = timedelta(days=28)
PROGRESS_RE = re.compile(r"^- ([\w-]+): xong", re.M)
TIME_FORMAT = "%Y-%m-%d %H:%M"


def video_templates() -> list:
    """Template video AI dùng được tự động: không cần video gốc / nhiều bước, ảnh đính kèm chỉ là sản phẩm/nhân vật/layout."""
    out = []
    for t in registry.listed():
        if t.kind != "ai_video" or t.image_steps or any(a.get("keep_video") for a in t.attachments):
            continue
        if any(a.get("required") and a["key"] not in ("product", "character", "layout") for a in t.attachments):
            continue
        out.append(t)
    return out


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.strptime(str(text or "").strip()[:16], TIME_FORMAT)
    except ValueError:
        return None


def schedule_error(when: datetime) -> str:
    now = datetime.now()
    if when < now + SCHEDULE_MIN:
        return f"giờ hẹn phải sau bây giờ ít nhất {int(SCHEDULE_MIN.total_seconds() // 60)} phút"
    if when > now + SCHEDULE_MAX:
        return f"giờ hẹn tối đa {SCHEDULE_MAX.days} ngày tới"
    return ""


class MediaStages:
    """Mixin cho Ctx (pipeline.py): cần self.data, update, log, ai, runner, cdir, read, files_block, header,
    product_block, image_paths, references, person, stage4, export_content."""

    # ---------------------------------------------------------------- tiện ích
    def image_engine(self) -> str:
        engine = self.data["options"].get("image_engine") or ""
        return engine if engine in IMAGE_ENGINES else self.runner.default_image_engine()

    def chosen_pages(self) -> list[dict]:
        pages = [p for p in self.runner.facebook.state().get("pages", []) if p.get("connected")]
        return [p for p in pages if p["id"] in self.data["options"].get("pages", [])] or pages

    def _count(self, field: str, n: int = 1) -> None:
        fresh = self.data
        cost = {**{"images": 0, "videos": 0}, **fresh.get("cost", {})}
        cost[field] = cost.get(field, 0) + n
        self.update(cost=cost)

    def _wait_task(self, runner, task_id: str, what: str) -> dict:
        """Chờ tác vụ ở hàng đợi Tạo ảnh / Tạo video của hệ thống; huỷ chiến dịch → huỷ luôn tác vụ đó."""
        summary = runner.pool.wait(task_id, self.ai.check_cancel)
        if summary["status"] != "done" or not summary.get("result"):
            reason = summary.get("error") or {"cancelled": "đã bị huỷ"}.get(summary["status"], summary["status"])
            raise CampaignError(f"{what} không thành công ({task_id}): {reason}")
        return summary["result"]

    @staticmethod
    def _done(progress_file: Path) -> set:
        return set(PROGRESS_RE.findall(progress_file.read_text("utf-8"))) if progress_file.exists() else set()

    @staticmethod
    def _mark_done(progress_file: Path, key: str) -> None:
        with open(progress_file, "a", encoding="utf-8") as fh:
            fh.write(f"- {key}: xong ({store.now()})\n")

    def post_text(self) -> str:
        content = self.read("03-content.md")
        post = re.search(r"```[^\n]*\n(.*?)```", content, re.S)  # phần BÀI ĐĂNG nằm trong khối ```
        return (post.group(1) if post else content).strip()

    # ---------------------------------------------------------------- chặng 5: kế hoạch nội dung theo Fanpage
    def _catalog(self, engine: str) -> str:
        options = self.data["options"]
        products = self.image_paths("products")
        lines = ["TÀI NGUYÊN ỨNG DỤNG CÓ SẴN (chỉ chọn trong danh sách này):",
                 f"- 2 ảnh quảng cáo dọc 9:16 (c1-a, c1-b), bắt buộc có người; mỗi ảnh tạo {VARIANTS} phương án bằng "
                 f"{IMAGE_ENGINES[engine]['name']} rồi trưởng phòng chọn ảnh đẹp nhất.",
                 "- Chữ quảng cáo trên ảnh: " + ("model VẼ ĐƯỢC chữ tiếng Việt → ghi tiêu đề ngắn (≤ 8 từ) + nhãn giá thật "
                                                 "vào chỉ đạo." if engine in TEXT_ENGINES else
                                                 "model KHÔNG vẽ chuẩn chữ tiếng Việt → ảnh không có chữ quảng cáo."),
                 "- pinterest: từ khoá TIẾNG ANH để tìm ảnh tham khảo bố cục trên Pinterest (dùng khi thiếu ảnh tham chiếu)."]
        if products:
            lines.append("- studio: ảnh sản phẩm studio cao cấp 1:1 (template ảnh) — cần mô tả BoiCanh (bối cảnh, tiếng Việt).")
        if engine in TEXT_ENGINES:
            lines.append("- poster: poster quảng cáo 9:16 (template ảnh, hợp sản phẩm NÔNG NGHIỆP) — TieuDe, LoiIch; "
                         "null nếu sản phẩm không thuộc nông nghiệp.")
        if options.get("video"):
            forced = options.get("video_kind") or "auto"
            voices = ", ".join(f"{v['id']} ({v['name']})" for v in VOICES)
            lines += [f"- videos: tối đa {MAX_VIDEOS} video dọc 9:16 dùng chung cho các page"
                      + (f" — người dùng chỉ định loại '{forced}'." if forced != "auto" else ", chọn loại hợp mục tiêu:"),
                      "  * sale: video bán hàng dựng từ ảnh chiến dịch + ảnh sản phẩm, có giọng đọc, phụ đề, giá. Trường: "
                      f"kieu ({' | '.join(STYLE_TEMPLATES)}), giong ({voices}), binh_luan (câu hỏi khách ≤ 120 ký tự để "
                      "cảnh mở đầu trả lời), ten_khach.",
                      "  * explainer: video kiến thức/mẹo có giọng đọc. Trường: the_loai ("
                      + " | ".join(f"{k}={v}" for k, v in EXPLAINER_GENRES.items()) + "), chu_de, giong.",
                      "  * ai: Grok Imagine làm ảnh c1-a chuyển động (clip ngắn, không giọng đọc). Trường: mo_ta (chuyển động).",
                      "  * template: video AI theo template (Grok Imagine), điền ĐỦ mọi biến bằng tiếng Việt, không bịa giá. "
                      "Trường: template, variables {Bien: giá trị}. Danh sách template:"]
            for t in video_templates():
                fields = ", ".join(f"{v['key']}{'' if v.get('required', True) else '?'} ({v['label']})" for v in t.variables)
                lines.append(f"    · {t.id} — {t.name}: {t.description[:140]} | biến: {fields}")
        return "\n".join(lines)

    def stage5(self):
        engine = self.image_engine()
        pages = self.chosen_pages()
        task = (self.header("3: KE HOACH NOI DUNG & CHI DAO ANH/VIDEO") + "\n"
                + self.files_block("00-brief.md", "02-chon-y-tuong.md", "03-content.md") + "\n\n" + self.product_block()
                + "\n\nFANPAGE SẼ ĐĂNG: " + ("; ".join(f"{p['name']} (danh mục {p.get('category') or '—'}, "
                                                       f"{p.get('fan_count') or 0} người theo dõi)" for p in pages)
                                            or "(chưa kết nối — vẫn lập kế hoạch nội dung)")
                + "\n\n" + self._catalog(engine)
                + '\n\nTrả về <file name="04-chon-content.md">…</file>, dòng đầu `CONTENT DUOC CHON: 1`, trình bày kế hoạch '
                  "nội dung (ảnh nào, video nào, vì sao hợp từng Fanpage) và chỉ đạo bố cục/thông điệp từng ảnh. "
                  "Cuối câu trả lời thêm khối ```json {\"anh\":[{\"key\":\"c1-a\",\"y_tuong\":\"…\",\"bo_cuc\":\"…\","
                  '"tieu_de":"…","nhan_gia":"… (chỉ khi có giá thật)"},{"key":"c1-b",…}],"pinterest":"…",'
                  '"studio":{"BoiCanh":"…"}|null,"poster":{"TieuDe":"…","LoiIch":"…"}|null,'
                  '"videos":[{"key":"v1","loai":"sale|explainer|ai|template",…trường theo loại}]}```.')
        answer = self.ai.ask("truong-phong-marketing", task)
        text = extract_file(answer, "04-chon-content.md")
        if not text.lstrip().upper().startswith("CONTENT DUOC CHON"):
            text = "CONTENT DUOC CHON: 1\n" + text
        store.write_file(self.cdir, "04-chon-content.md", text)
        plan = extract_json(answer, {}) or {}
        if isinstance(plan, list):  # chỉ trả danh sách chỉ đạo ảnh
            plan = {"anh": plan}
        directions = plan.get("anh") or []
        mapped = {(d.get("key") if d.get("key") in IMAGE_KEYS else k): d for d, k in zip(directions, IMAGE_KEYS)}
        media_plan = {"pinterest": str(plan.get("pinterest") or "").strip()[:80],
                      "studio": plan.get("studio") if self.image_paths("products") and isinstance(plan.get("studio"), dict)
                      else None,
                      "poster": plan.get("poster") if engine in TEXT_ENGINES and isinstance(plan.get("poster"), dict) else None,
                      "videos": self._normalize_videos(plan.get("videos"))}
        self.update(directions={k: mapped.get(k, {"key": k}) for k in IMAGE_KEYS}, media_plan=media_plan)
        self.log("Kế hoạch nội dung: 2 ảnh quảng cáo"
                 + (" + ảnh studio" if media_plan["studio"] else "") + (" + poster" if media_plan["poster"] else "")
                 + (f" + {len(media_plan['videos'])} video ({', '.join(VIDEO_KINDS[v['loai']] for v in media_plan['videos'])})"
                    if media_plan["videos"] else ""), "ok")

    def _normalize_videos(self, raw) -> list[dict]:
        options = self.data["options"]
        if not options.get("video"):
            return []
        forced = options.get("video_kind") or "auto"
        templates = {t.id for t in video_templates()}
        out = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            kind = forced if forced != "auto" else item.get("loai")
            if kind == "template" and item.get("template") not in templates:
                kind = "sale"
            if kind not in VIDEO_KINDS:
                continue
            out.append({**item, "loai": kind, "key": f"v{len(out) + 1}"})
            if len(out) >= MAX_VIDEOS:
                break
        return out or [{"key": "v1", "loai": forced if forced != "auto" else "sale"}]

    # ---------------------------------------------------------------- chặng 6: ảnh (Tạo hình ảnh)
    def stage6(self):
        self.make_images()
        self.write_gallery()

    def _image_prompt(self, key: str, note: str, products, refs, person, engine: str, pinterest: bool) -> dict:
        """NV hình ảnh viết prompt cho 1 ảnh quảng cáo (gửi kèm ảnh mẫu để nhìn bố cục/sản phẩm)."""
        options = self.data["options"]
        style = next((s for s in store.styles() if s["name"] == options.get("style")), None)
        style_text = style["prompt"] if style else options.get("style", "")
        direction = (self.data.get("directions") or {}).get(key) or {"key": key}
        ordered = products[:1] + refs[:2] + person[:1]
        text_rule = (
            "Ảnh CÓ chữ quảng cáo do model ảnh vẽ luôn: đưa NGUYÊN VĂN vào prompt, đặt trong ngoặc kép, ghi rõ vị trí — "
            "tiêu đề ngắn (≤ 8 từ) và nhãn giá (CHỈ khi có giá thật); chữ tiếng Việt có dấu, to, rõ, ít chữ; không đặt "
            "chữ đè lên mặt người hoặc nhãn sản phẩm."
            if engine in TEXT_ENGINES else
            "Model ảnh này vẽ chữ tiếng Việt không chuẩn → KHÔNG yêu cầu vẽ bất kỳ chữ quảng cáo nào trong ảnh.")
        task = (self.header(f"VIẾT PROMPT ẢNH {key}") + "CONTENT CAN LAM: 1\n\n"
                + self.files_block("03-content.md", "04-chon-content.md", "thong-tin-web.md")
                + f"\n\nCHỈ ĐẠO CHO ẢNH {key}: {json.dumps(direction, ensure_ascii=False)}\n"
                + f"PHONG CÁCH NHÂN VẬT: {options.get('style')} — {style_text}\n"
                + (f"YÊU CẦU SỬA: {note}\n" if note else "")
                + f"\nẢnh gửi kèm theo thứ tự: {'1 = ảnh sản phẩm thật; ' if products else ''}"
                + f"{len(refs[:2])} ảnh tham chiếu bố cục{'; 1 ảnh người mẫu' if person else ''}"
                + ("; sau cùng là vài ảnh Pinterest CHỈ để lấy cảm hứng bố cục/màu" if pinterest else "")
                + f". Model ảnh ({IMAGE_ENGINES[engine]['name']}) nhận đúng các ảnh này theo cùng thứ tự.\n"
                + "Viết prompt (tiếng Anh, chữ quảng cáo giữ tiếng Việt) cho model vẽ ảnh dọc 9:16: nói rõ vai trò từng ảnh "
                  "đính kèm theo thứ tự; bám bố cục/góc máy/ánh sáng/bảng màu của ảnh tham chiếu, chỉ thay sản phẩm, gương "
                  "mặt, trang phục; BẮT BUỘC có người; sản phẩm vẽ lại giống ảnh sản phẩm (màu bao bì, chữ lớn trên nhãn, "
                  "khối lượng); không chép logo/giao diện app hay watermark.\n" + text_rule + "\n"
                + 'Trả lời bằng khối ```json {"y_tuong":"…","prompt":"…"}```.')
        plan = extract_json(self.ai.ask("nv-hinh-anh", task, images=ordered, web=False), {}) or {}
        if not str(plan.get("prompt") or "").strip():
            raise CampaignError(f"NV hình ảnh không trả về prompt cho ảnh {key}")
        return {**plan, "prompt": str(plan["prompt"]).strip(), "ordered": ordered}

    def _image_jobs(self, keys, note: str, force: bool, extras: bool, done: set, out: Path) -> dict:
        """Chuẩn bị form cho hàng đợi Tạo hình ảnh: ảnh quảng cáo (prompt NV hình ảnh, nhiều phương án, Pinterest khi
        thiếu tham chiếu) + ảnh phụ theo template ảnh (studio, poster)."""
        engine = self.image_engine()
        spec = IMAGE_ENGINES[engine]
        options = self.data["options"]
        plan = self.data.get("media_plan") or {}
        profile = options.get("image_profile") or options.get("browser_profile", "")  # browser_profile: chiến dịch cũ
        common = {"engine": engine, "show_browser": False, "browser_profile": profile, "quality": "high"}
        refs, products, person = self.references(), self.image_paths("products"), self.person()
        keyword = plan.get("pinterest") or (self.data.get("product") or {}).get("name") or ""
        use_pin = not refs and bool(keyword)
        if not refs and not use_pin:  # quy tắc 4
            raise CampaignError("Không có ảnh tham chiếu và không có từ khoá Pinterest — thêm ảnh rồi bấm Chạy tiếp")
        if use_pin:
            self.log(f"Không có ảnh tham chiếu → lấy ảnh tham khảo Pinterest: “{keyword}”")
        if not products:
            self.log("Không có ảnh sản phẩm — ảnh sẽ không vẽ bao bì có nhãn", "warn")
        jobs = {}
        for key in keys:
            if not force and key in done and (out / f"{key}.png").exists():
                self.log(f"Ảnh {key} đã xong — bỏ qua (theo tien-do.md)")
                continue
            self.ai.check_cancel()
            p = self._image_prompt(key, note, products, refs, person, engine, use_pin)
            refs_sent = p["ordered"][:spec["max_images"]]
            form = {**common, "prompt": p["prompt"], "aspect": "9:16",
                    "count": max(c for c in spec["counts"] if c <= VARIANTS), "refs": [str(x) for x in refs_sent]}
            if use_pin:
                form["pinterest"] = {"on": True, "keyword": keyword, "count": 2}
            jobs[key] = {"form": form, "plan": {**p, "refs_sent": refs_sent}, "extra": False}
        product_name = (self.data.get("product") or {}).get("name") or self.data["name"]
        for key, (template_id, label, aspect) in EXTRA_IMAGES.items() if extras else ():
            values = plan.get(key)
            if not values or (not force and key in done and (out / f"{key}.png").exists()) or not registry.get(template_id):
                continue
            variables = {"TenSanPham": product_name, **{k: str(v) for k, v in values.items() if v}}
            form = {**common, "template": template_id, "variables": variables, "aspect": aspect, "count": 1,
                    "refs": [str(x) for x in products[:1]]}
            jobs[key] = {"form": form, "plan": {"y_tuong": label, "prompt": f"Template {template_id}: "
                                                + json.dumps(variables, ensure_ascii=False),
                                                "refs_sent": products[:1]}, "extra": True, "label_name": label}
        return jobs

    def make_images(self, keys=IMAGE_KEYS, note: str = "", force: bool = False, extras: bool = True):
        """Chặng 6: giao cả loạt ảnh cho hàng đợi Tạo hình ảnh (chạy song song) → chờ → chọn phương án đẹp nhất →
        chép về 05-hinh-anh/ → so nhãn. Ảnh đã xong (tien-do.md) được bỏ qua khi chạy lại sau lỗi."""
        out = self.cdir / "05-hinh-anh"
        out.mkdir(parents=True, exist_ok=True)
        progress_file = out / "tien-do.md"
        jobs = self._image_jobs(keys, note, force, extras, self._done(progress_file), out)
        if not jobs:
            return
        engine = self.image_engine()
        products = self.image_paths("products")
        tasks = {}
        try:
            for key, job in jobs.items():
                tasks[key] = self.runner.images.start(job["form"])
                self.log(f"Đã giao ảnh {key} cho Tạo hình ảnh ({IMAGE_ENGINES[engine]['name']}) — tác vụ {tasks[key]}")
            errors = []
            for key, task_id in tasks.items():
                try:
                    result = self._wait_task(self.runner.images, task_id, f"Tạo ảnh {key}")
                except CampaignError as exc:
                    errors.append(str(exc))
                    self.log(str(exc), "error")
                    continue
                folder = self.runner.settings.output_dir / IMAGES_DIR / result["id"]
                paths = [folder / f["name"] for f in result.get("files") or [] if (folder / f["name"]).exists()]
                if not paths:
                    errors.append(f"Tạo ảnh {key}: không có file kết quả")
                    continue
                self._count("images", len(paths))
                pick = 0 if jobs[key]["extra"] else self._pick_variant(key, paths, products)
                final = out / f"{key}.png"
                store.keep_old(final)
                _save_png(paths[pick], final)
                if len(paths) > 1:
                    for i, p in enumerate(paths, 1):
                        _save_png(p, out / f"{key}-pa{i}.png")
                self._finish_image(key, jobs[key], final, products, engine, result["id"], progress_file,
                                   variants=len(paths), picked=pick + 1)
        except Cancelled:
            for task_id in tasks.values():
                self.runner.images.cancel(task_id)
            raise
        if errors:
            raise CampaignError("; ".join(errors))

    def _pick_variant(self, key: str, paths: list[Path], products) -> int:
        """Trưởng phòng xem các phương án (kèm ảnh sản phẩm thật) và chọn ảnh đẹp/đúng chỉ đạo nhất."""
        if len(paths) < 2:
            return 0
        direction = (self.data.get("directions") or {}).get(key) or {}
        ref = products[:1]
        task = (f"CHỌN PHƯƠNG ÁN ẢNH {key}. {'Ảnh 1 là sản phẩm thật; ' if ref else ''}các ảnh sau là {len(paths)} phương án "
                f"(phương án 1 = ảnh {len(ref) + 1}). Chỉ đạo: {json.dumps(direction, ensure_ascii=False)}.\n"
                "Chọn phương án đẹp, đúng chỉ đạo, sản phẩm giống thật, người tự nhiên, chữ (nếu có) đúng chính tả. "
                'Trả lời ```json {"chon": <số phương án>, "ly_do": "…"}```.')
        answer = extract_json(self.ai.ask("truong-phong-marketing", task, images=ref + paths, web=False), {}) or {}
        try:
            pick = min(len(paths), max(1, int(answer.get("chon") or 1))) - 1
        except (TypeError, ValueError):
            pick = 0
        self.log(f"Ảnh {key}: chọn phương án {pick + 1}/{len(paths)} — {answer.get('ly_do', '')}", "ok")
        return pick

    def _finish_image(self, key: str, job: dict, final: Path, products, engine: str, library_id: str,
                      progress_file: Path, variants: int = 1, picked: int = 1) -> None:
        out = final.parent
        plan = job["plan"]
        label = {"khop": None, "nhan_xet": "Không có ảnh sản phẩm để so nhãn"}
        if products:
            check = self.ai.ask("nv-hinh-anh", "SO NHÃN: ảnh 1 là sản phẩm thật, ảnh 2 là ảnh vừa tạo. So màu bao bì, "
                                "chữ lớn trên nhãn, khối lượng. Trả lời ```json {\"khop\": true|false, \"nhan_xet\": \"…\"}```.",
                                images=[products[0], final], web=False)
            label = extract_json(check, label) or label
            self.log(f"So nhãn {key}: {'khớp' if label.get('khop') else 'CHƯA KHỚP'} — {label.get('nhan_xet', '')}",
                     "ok" if label.get("khop") else "warn")
        images = self.data.get("images") or {}
        images[key] = {"file": final.name, "key": key, "idea": plan.get("y_tuong", ""), "prompt": plan["prompt"],
                       "refs": [p.name for p in plan["refs_sent"]], "label": label, "engine": engine,
                       "library_id": library_id, "extra": job["extra"], "name": job.get("label_name", ""),
                       "variants": variants, "picked": picked, "at": store.now()}
        self.update(images=images)
        with open(out / "y-tuong-anh.md", "a", encoding="utf-8") as fh:
            fh.write(f"## {key} ({store.now()})\n{plan.get('y_tuong', '')}\n\n")
        with open(out / "prompt-ai.md", "a", encoding="utf-8") as fh:
            fh.write(f"## {key} ({store.now()}) · {IMAGE_ENGINES[engine]['name']}\n"
                     f"Ảnh mẫu gửi kèm: {', '.join(p.name for p in plan['refs_sent'])}\n\n{plan['prompt']}\n\n")
        self._mark_done(progress_file, key)
        self.log(f"Đã xong ảnh {key} (thư viện ảnh: {library_id})", "ok")

    def image_files(self) -> list[str]:
        """Ảnh đã có, theo thứ tự hiển thị: 2 ảnh quảng cáo rồi ảnh phụ."""
        return [f"05-hinh-anh/{k}.png" for k in (*IMAGE_KEYS, *EXTRA_IMAGES)
                if (self.cdir / "05-hinh-anh" / f"{k}.png").exists()]

    def write_gallery(self):
        images = list((self.data.get("images") or {}).values())
        store.write_file(self.cdir, "05-hinh-anh.html", tools.gallery_html(self.cdir, self.data["name"], images))

    # ---------------------------------------------------------------- chặng 6b: video (Tạo video)
    def stage6b(self):
        if not self.data["options"].get("video"):
            return "skipped"
        self.make_videos()

    def _brand(self) -> str:
        pages = self.chosen_pages()
        return (pages[0]["name"] if pages else (self.data.get("product") or {}).get("name") or "")[:60]

    def _video_form(self, spec: dict, images: list[Path]) -> dict:
        options = self.data["options"]
        settings = self.runner.settings
        kind = spec["loai"]
        voice = spec.get("giong") if spec.get("giong") in {v["id"] for v in VOICES} else "vi-VN-HoaiMyNeural"
        grok = {"show_browser": False, "browser_profile": options.get("video_profile", "")}
        script = {"show_browser": False, "browser_profile": "", "provider": settings.get("provider") or "gemini_browser"}
        products = self.image_paths("products")[:1]
        p = self.data.get("product") or {}
        if kind == "ai":
            first = (self.data.get("images") or {}).get(images[0].stem) or {}
            motion = str(spec.get("mo_ta") or first.get("idea") or "Natural lively motion.")
            return {**grok, "template": AI_VIDEO_TEMPLATE, "variables": {"MoTa": motion[:300]},
                    "attachments": {"image": str(images[0])}}
        if kind == "template":
            t = registry.get(spec["template"])
            values = {str(k): str(v) for k, v in (spec.get("variables") or {}).items() if v}
            for var in t.variables:  # biến bắt buộc còn trống → giá trị an toàn từ sản phẩm
                if var.get("required", True) and not values.get(var["key"]):
                    values[var["key"]] = var.get("default") or p.get("name") or self.data["name"]
            person = self.person()
            files = {"product": products[0] if products else None, "character": person[0] if person else None,
                     "layout": images[0]}
            attachments = {a["key"]: str(files[a["key"]]) for a in t.attachments if files.get(a["key"])}
            return {**grok, "template": t.id, "variables": values, "attachments": attachments,
                    "provider": t.video_engine or AI_VIDEO_ENGINE}
        if kind == "explainer":
            genre = spec.get("the_loai") if spec.get("the_loai") in EXPLAINER_GENRES else "explainer"
            topic = "\n".join([str(spec.get("chu_de") or f"Kiến thức hữu ích về {p.get('name') or self.data['name']}"),
                               self.product_block(), "", "Thông điệp bài đăng (giữ đúng, không bịa giá/khuyến mãi):",
                               self.post_text()])[:VIDEO_TOPIC_LIMIT]
            return {**script, "topic": topic, "genre": genre, "template": "ai", "aspect": "9:16", "scenes": 5,
                    "seconds": 6, "voice": voice, "subtitles": True, "bgm": True}
        topic = "\n".join([f"Video bán hàng cho chiến dịch “{self.data['name']}”.", self.product_block(), "",
                           "Nội dung bài đăng đã duyệt (giữ thông điệp, không bịa giá/khuyến mãi):",
                           self.post_text()])[:VIDEO_TOPIC_LIMIT]
        sale = p.get("sale_price") or ""
        style = spec.get("kieu") if spec.get("kieu") in STYLE_TEMPLATES else options.get("video_style") or "presenter"
        return {**script, "topic": topic, "genre": PRODUCT_GENRE, "template": "ai",
                "product_files": [str(x) for x in images + products], "layout_file": "", "product_style": style,
                "aspect": "9:16", "scenes": 4, "seconds": 6, "voice": voice, "subtitles": True, "bgm": True,
                "brand": self._brand(), "comment_name": str(spec.get("ten_khach") or "")[:40],
                "comment_text": str(spec.get("binh_luan") or "")[:120], "price": sale or p.get("price") or "",
                "old_price": p.get("price") if sale else "", "perk": p.get("promo") or "", "contact": p.get("hotline") or ""}

    def make_videos(self, force: bool = False):
        """Giao các video trong kế hoạch cho hàng đợi Tạo video (chạy song song) → chờ → chép về 07-video/<key>.mp4."""
        images = [self.cdir / "05-hinh-anh" / f"{k}.png" for k in IMAGE_KEYS
                  if (self.cdir / "05-hinh-anh" / f"{k}.png").exists()]
        if not images:
            raise CampaignError("Chưa có ảnh chiến dịch để làm video — chạy chặng 6 trước")
        plan = (self.data.get("media_plan") or {}).get("videos") or self._normalize_videos([])
        out = self.cdir / "07-video"
        out.mkdir(exist_ok=True)
        progress_file = out / "tien-do.md"
        done = self._done(progress_file)
        tasks, errors = {}, []
        try:
            for spec in plan:
                key = spec["key"]
                if not force and key in done and (out / f"{key}.mp4").exists():
                    self.log(f"Video {key} đã xong — bỏ qua (theo tien-do.md)")
                    continue
                try:
                    tasks[key] = (spec, self.runner.videos.start(self._video_form(spec, images)))
                except (ValueError, CampaignError) as exc:  # form không hợp lệ (thiếu biến, file…) → báo, làm video khác
                    errors.append(f"{VIDEO_KINDS[spec['loai']]} {key}: {exc}")
                    continue
                self.log(f"Đã giao {VIDEO_KINDS[spec['loai']]} ({key}) cho Tạo video — tác vụ {tasks[key][1]}")
            for key, (spec, task_id) in tasks.items():
                try:
                    result = self._wait_task(self.runner.videos, task_id, f"{VIDEO_KINDS[spec['loai']]} {key}")
                except CampaignError as exc:
                    errors.append(str(exc))
                    self.log(str(exc), "error")
                    continue
                src = self.runner.settings.output_dir / result["id"] / "final.mp4"
                if not src.exists():
                    errors.append(f"Không thấy file video của tác vụ {task_id}")
                    continue
                dest = out / f"{key}.mp4"
                store.keep_old(dest)
                shutil.copy2(src, dest)
                self._count("videos")
                videos = self.data.get("videos") or {}
                videos[key] = {"key": key, "kind": spec["loai"], "label": VIDEO_KINDS[spec["loai"]],
                               "template": spec.get("template", ""), "file": f"07-video/{key}.mp4",
                               "library_id": result["id"], "duration": result.get("duration"), "at": store.now()}
                self.update(videos=videos)
                self._mark_done(progress_file, key)
                self.log(f"Đã xong {VIDEO_KINDS[spec['loai']]}: 07-video/{key}.mp4 (thư viện video: {result['id']})", "ok")
        except Cancelled:
            for _, task_id in tasks.values():
                self.runner.videos.cancel(task_id)
            raise
        videos = sorted((self.data.get("videos") or {}).values(), key=lambda v: v["key"])
        store.write_file(self.cdir, "07-video.html", tools.video_html(self.data["name"], videos))
        if errors:
            raise CampaignError("; ".join(errors))

    def video_files(self) -> list[str]:
        return [v["file"] for v in sorted((self.data.get("videos") or {}).values(), key=lambda v: v["key"])
                if (self.cdir / v["file"]).exists()]

    # ---------------------------------------------------------------- chặng 7b: kế hoạch đăng theo từng page
    def stage7b(self):
        from .pipeline import WaitUser

        data = self.data
        options = data["options"]
        if options.get("no_post"):
            self.log("Tuỳ chọn 'Không đăng' — bỏ qua kiểm duyệt và đăng bài")
            stages = data["stages"]
            stages["7c"] = {"status": "skipped", "ended": store.now()}
            self.update(stages=stages)
            return "skipped"
        pages = self.chosen_pages()
        images, videos = self.image_files(), self.video_files()
        schedule = options.get("schedule") or {}
        days = max(1, min(14, int(schedule.get("days") or 3)))
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        when = (f"HẸN GIỜ ĐĂNG: BẬT — rải bài trong {days} ngày bắt đầu từ {tomorrow}, chọn khung giờ vàng của khách "
                "hàng Việt Nam (11:00–13:00, 19:00–22:00); các page khác nhau lệch giờ nhau; ghi gio_dang dạng "
                "YYYY-MM-DD HH:MM (giờ Việt Nam)." if schedule.get("on") else
                'HẸN GIỜ ĐĂNG: TẮT — gio_dang để "" (đăng ngay khi người dùng đồng ý).')
        task = (self.header("1: KIEM DUYET & KE HOACH DANG THEO PAGE (không đăng gì)") + "\n"
                + self.files_block("06-danh-gia.md", "03-content.md", "04-chon-content.md")
                + "\n\nẢNH: " + (", ".join(images) or "(không có)") + "\nVIDEO: " + (", ".join(videos) or "(không có)")
                + "\nFANPAGE: " + ("; ".join(f"{p['name']} (page_id {p['id']}, danh mục {p.get('category') or '—'}, "
                                             f"{p.get('fan_count') or 0} người theo dõi)" for p in pages)
                                   or "(chưa kết nối Fanpage nào)")
                + f"\n{when}\n"
                + "Mỗi page lập 1–3 bài khác nhau (không đăng trùng y hệt giữa các page): loai album (2–4 ảnh), video "
                  "(đúng 1 file video) hoặc anh (1 ảnh); caption viết riêng hợp từng page (giữ thông điệp, không bịa "
                  "giá/khuyến mãi). Ưu tiên có ít nhất 1 bài video nếu có video.\n"
                + 'Trả về <file name="ke-hoach-dang.md">…</file> có dòng `PHAN QUYET DANG: SAN SANG` hoặc `CHUA DAT`. '
                  'Cuối câu trả lời thêm ```json {"phan_quyet_dang":"SAN SANG|CHUA DAT","bai":[{"stt":1,"page_id":"…",'
                  '"page":"…","loai":"album|video|anh","caption":"TOÀN VĂN caption","files":["…"],"gio_dang":""}],'
                  '"can_sua":[{"nhan_vien":"nv-content|nv-hinh-anh","noi_dung":"…"}]}```.')
        answer = self.ai.ask("nv-dang-bai-facebook", task)
        store.write_file(self.cdir, "08-dang-bai/ke-hoach-dang.md", extract_file(answer, "ke-hoach-dang.md"))
        result = extract_json(answer, {}) or {}
        if "CHUA" in (result.get("phan_quyet_dang") or "").upper():
            if int(data.get("post_revision", 0)) >= 1:
                raise WaitUser("post_stop", "Kiểm duyệt đăng vẫn CHƯA ĐẠT sau 1 vòng sửa — bạn xem kế hoạch đăng",
                               result.get("can_sua"))
            self.update(post_revision=1)
            notes = "\n".join(f"- {f.get('noi_dung')}" for f in result.get("can_sua") or [] if f.get("nhan_vien") == "nv-content")
            if notes:
                self.stage4(notes)
                self.export_content()
            return self.stage7b()
        plan = self._normalize_plan(result.get("bai") or [], pages, images, videos, bool(schedule.get("on")))
        self.update(plan=plan)
        self.log(f"Kế hoạch đăng SẴN SÀNG: {len(plan)} bài cho {len({p['page_id'] for p in plan})} page"
                 + (" (có hẹn giờ)" if any(p["gio_dang"] for p in plan) else "") + " — chờ bạn bấm 'Đồng ý đăng'", "ok")

    def _normalize_plan(self, posts: list, pages: list, images: list, videos: list, scheduled: bool) -> list[dict]:
        page_ids = {p["id"]: p["name"] for p in pages}
        plan = []
        for i, post in enumerate(posts, 1):
            if not isinstance(post, dict):
                continue
            files = [str(f) for f in post.get("files") or [] if (self.cdir / str(f)).exists()]
            kind = post.get("loai") if post.get("loai") in POST_TYPES else "album"
            vids = [f for f in files if f in videos] or videos[:1]
            imgs = [f for f in files if f in images] or images[:2]
            if kind == "video" and vids:
                files = vids[:1]
            else:
                kind = "anh" if kind == "anh" or len(imgs) < 2 else "album"
                files = imgs[:1] if kind == "anh" else imgs[:4]
            if not files:
                continue
            page_id = str(post.get("page_id") or "")
            page_id = page_id if page_id in page_ids else (pages[0]["id"] if pages else "")
            when = parse_time(post.get("gio_dang")) if scheduled else None
            if when and schedule_error(when):
                self.log(f"Bài {i}: giờ hẹn {when:%Y-%m-%d %H:%M} không hợp lệ ({schedule_error(when)}) — để trống", "warn")
                when = None
            plan.append({"stt": post.get("stt") or i, "page_id": page_id, "page": page_ids.get(page_id, post.get("page", "")),
                         "loai": kind, "caption": str(post.get("caption") or ""), "files": files,
                         "gio_dang": when.strftime(TIME_FORMAT) if when else ""})
        return plan


def _save_png(src: Path, dest: Path) -> None:
    from PIL import Image

    with Image.open(src) as im:
        im.convert("RGB").save(dest, "PNG")
