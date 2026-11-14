"""🎬 AI Product Video Studio (tài liệu yêu cầu v1.0 — 13/11/2026).

Khối Workflow / Canvas: dữ liệu sản phẩm ĐÃ DUYỆT + nhân vật + ảnh tham chiếu → AI Script Planner (Master Prompt mục 6)
→ storyboard từng cảnh (prompt tiếng Anh + lời thoại tiếng Việt RIÊNG + ảnh tham chiếu cần dùng) có Character Lock /
Product Lock. Định dạng cảnh giống khối Storyboard → Canvas tự tách mỗi cảnh 1 khối Video (Grok Imagine ở
màn Grok Canvas, Google Flow ở Canvas thường), duyệt từng clip, ghép, lồng giọng, phụ đề (canvas.CanvasRunner
._split_scenes + _studio_post). Grok: prompt cảnh = khung mở đầu (ảnh bìa) + 1 chuyển động (GROK_RULES).

Giới hạn (mục 1): prompt + ảnh tham chiếu KHÔNG bảo đảm tuyệt đối khuôn mặt / chữ trên nhãn — mỗi clip phải được người
duyệt; nhãn chữ nhỏ nên ghép ảnh sản phẩm gốc ở hậu kỳ.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ENVIRONMENTS = {
    "warehouse": "clean agricultural fertilizer warehouse in Southern Vietnam, tidy pallets, soft natural daylight",
    "orchard": "lush Southern Vietnamese fruit orchard, soft natural daylight",
    "studio": "clean professional product studio, plain backdrop, soft even commercial lighting",
}
CAMERAS = {"static": "locked camera, stable frame", "dolly": "one slow, subtle camera push-in (dolly-in)",
           "pan": "one slow, gentle pan"}
# giọng VieNeu miền Nam (lồng hậu kỳ) — mục 3.2
VOICES = {"female_south": ("Thùy Dung", "Southern Vietnamese female"), "male_south": ("Adam", "Southern Vietnamese male")}
CHECKLIST = [  # mục 10
    "Khuôn mặt nhân vật đúng bộ ảnh tham chiếu",
    "Trang phục, kiểu tóc và vóc dáng nhất quán",
    "Hình dáng bao bì, nắp và màu sắc đúng",
    "Nhãn, logo, chữ và tên sản phẩm không bị biến dạng hoặc thay đổi",
    "Công dụng, thành phần và thông điệp đã được phê duyệt",
    "Lời thoại chính xác, phát âm phù hợp (kiểm tra khẩu hình nếu nhân vật nói trực tiếp)",
    "Không có sản phẩm, logo hoặc vật thể ngoài ý muốn",
    "Bố cục / tỷ lệ khung hình phù hợp nền tảng đăng tải",
]
MASTER = """You are an AI Commercial Video Director and Prompt Engineer.

Your task is to create production-ready video prompts for {target}.

PRIMARY GOALS:
1. Maintain character consistency across all scenes.
2. Preserve the product's appearance and branding.
3. Introduce the product clearly and accurately.
4. Produce photorealistic advertising content for Vietnamese audiences.

INPUT DATA:
- Product name: {product_name}
- Product code: {product_code}
- Brand: {brand}
- Product facts (the ONLY facts you may use):
{facts}
- Product reference images: {product_images}
- Character reference images: {character_images}
- Character description: {character}
- Character lock: identity {lock_identity}, outfit {lock_outfit}
- Environment: {environment}
- Aspect ratio: {aspect}
- Total duration: {total} seconds
- Clip duration allowed by model: {clip} seconds (write EXACTLY {count} scenes of {clip} seconds)
- Video model: {model}
- Voice preference: {voice}
- Dialogue: {speech}
- Camera movement preference: {camera}
- Advertising message: {message}
{extra}
ATTACHED IMAGES (sent with this message, in this order):
{materials}

CHARACTER CONSISTENCY RULES:
- Use the same reference character in every scene.
- Preserve facial appearance, hairstyle, outfit and proportions.
- Do not introduce a different presenter.
- Use natural expression and simple movements.

PRODUCT FIDELITY RULES:
- Treat the product images as the visual source of truth.
- Preserve container shape, lid, label layout, logo and colors.
- Never redesign, translate, replace or invent packaging text.
- Keep the front label facing the camera when possible.

FACTUAL ACCURACY RULES:
- Use only the product facts above.
- Never invent fertilizer composition, application rates,
  guarantees or quantitative efficacy.

VIDEO RULES:
- One main action and one main camera movement per scene.
- Maintain visual continuity across scenes.
- Prefer stable shots and realistic commercial lighting.
- Avoid extra products, unwanted text overlays and watermarks.
{model_rules}
DIALOGUE RULES:
- Write natural Southern Vietnamese dialogue when requested.
- Keep spoken content separate from video prompts.
- Use only the product facts and message above.
- Each scene's dialogue must be speakable within {words} Vietnamese words.

OUTPUT: return ONLY one ```json block with this structure (keys exactly as shown):
{{
  "metadata": {{"title": "...", "product": "...", "scene_count": {count}}},
  "character_lock": "one English sentence describing the locked presenter",
  "product_lock": "one English sentence describing the locked product",
  "scenes": [
    {{"scene_id": 1, "duration_seconds": {clip},
      "noi_dung": "mô tả ngắn cảnh bằng tiếng Việt (bố cục, hành động chính)",
      "camera": "one main camera movement",
      "prompt": "full English generation prompt for this scene (photorealistic, {aspect}, one action, one camera move)",
      "loi_thoai": "lời thoại tiếng Việt của cảnh (\\"\\" nếu không lời)",
      "vat_lieu": ["Ảnh 1", "Ảnh 2"],
      "nhan_vat_xuat_hien": true}}
  ]
}}
Focus on prompts that generate the most effective, consistent commercial video — no review notes or warnings."""
SYSTEM = "You are an AI Commercial Video Director. Follow the required JSON format exactly."
TARGETS = {"grok": "Grok Imagine (xAI image-to-video)", "flow": "Google Flow\nor an officially supported Google "
           "video-generation API"}
# Grok Imagine quay tốt nhất từ 1 ảnh khung mở đầu + prompt ngắn tả chuyển động; cùng prompt cảnh còn dùng tạo ảnh bìa
GROK_RULES = """
GROK IMAGINE RULES (the target video model):
- Each scene is ONE {clip}-second image-to-video shot: Grok animates an approved start frame{start_note}.
- Write every scene "prompt" in this exact shape (concise, under 90 words, plain English):
  "Start frame: <composition of the very first moment — presenter, product placement, setting, framing, lighting>.
   Motion: <ONE simple action of the presenter or product>. Camera: <ONE slow camera movement or locked>."
- The start frame must already show the presenter and the product exactly as approved; the motion must stay small
  and physically simple (hold, turn the bottle, point, nod, slight walk) so face and label do not drift.
- Never describe on-screen text, captions, logos appearing, scene cuts, morphing or several actions in one scene.
"""
FRAMES_NOTE = " (generated from the 'Start frame' part of the prompt, then reviewed by a human)"
INGREDIENTS_NOTE = " (Grok also receives the character / product reference images)"


def _target(cfg: dict) -> str:
    return "grok" if "grok" in str(cfg.get("_video_model") or "").lower() else "flow"


def _secs(cfg: dict) -> int:
    raw = cfg.get("total_custom") if str(cfg.get("total") or "") == "custom" else cfg.get("total")
    try:
        return max(4, min(120, int(float(str(raw or 15)))))
    except ValueError:
        return 15


def plan(cfg: dict) -> dict:
    """Thời lượng clip (theo model video), số cảnh, tổng thời lượng — dùng chung cho khối và Canvas."""
    clip = max(4, int(cfg.get("_clip_secs") or 8))
    total = _secs(cfg)
    return {"clip": clip, "total": total, "count": max(1, min(8, math.ceil(total / clip)))}


def _lock_text(cfg: dict, product: str, subject: bool, speech: str) -> str:
    """Khoá nhân vật / sản phẩm / camera / lời gắn CỐ ĐỊNH sau prompt MỌI cảnh (model có quên cũng không mất)."""
    parts = []
    if _target(cfg) == "grok" and cfg.get("mode") == "frames":  # Grok quay từ ảnh bìa đã duyệt → khoá theo ảnh bìa
        keep = "face, hairstyle" + (", outfit" if cfg.get("lock_outfit", True) else "")
        if subject and cfg.get("lock_identity", True):
            parts.append(f"Keep the presenter exactly as in the start frame (same {keep}); no other person appears.")
        parts.append(f"Keep the {product or 'product'} exactly as in the start frame: same container shape, lid, label "
                     "layout, logo and colors, front label facing the camera; never redesign or invent packaging text.")
        cam = CAMERAS.get(str(cfg.get("camera") or ""))
        if cam:
            parts.append(f"Camera: {cam}.")
        parts.append("No dialogue, no lip-sync, ambient sound only." if speech != "direct" else
                     "The presenter speaks the Vietnamese line naturally with a Southern accent.")
        parts.append("Small, smooth, realistic motion. No on-screen text, subtitles or watermarks.")
        return " ".join(parts)
    if subject and cfg.get("lock_identity", True):
        keep = "face, hairstyle, body proportions" + (" and outfit" if cfg.get("lock_outfit", True) else "")
        parts.append(f"Use the uploaded presenter as the exact character reference; preserve the same {keep}; "
                     "do not introduce a different presenter.")
    parts.append(f"Use the uploaded {product or 'product'} as the exact product reference: preserve container shape, "
                 "lid, label layout, logo and colors; keep the front label facing the camera; never redesign, "
                 "translate or invent packaging text.")
    cam = CAMERAS.get(str(cfg.get("camera") or ""))
    if cam:
        parts.append(f"Camera: {cam}.")
    parts.append("No dialogue, no lip-sync, ambient sound only." if speech != "direct" else
                 "The presenter speaks the Vietnamese line naturally with a Southern accent.")
    parts.append("No extra products, no on-screen text overlays, subtitles or watermarks.")
    return " ".join(parts)


def _materials(cfg: dict, refs: list) -> tuple[str, list, list]:
    names = (cfg.get("_materials") or {}).get("anh") or []
    roles = list(cfg.get("_ref_roles") or [])
    lines, chars, prods = [], [], []
    for i, p in enumerate(refs, 1):
        role = roles[i - 1] if i <= len(roles) else ""
        name = names[i - 1] if i <= len(names) else Path(str(p)).stem
        if role == "character" or (not role and re.search(r"nhân vật|nhan vat|character|người mẫu", name, re.I)):
            role = "character"
            chars.append(f"Ảnh {i}")
        elif role == "product" or (not role and re.search(r"sản phẩm|san pham|product|bao bì", name, re.I)):
            role = "product"
            prods.append(f"Ảnh {i}")
        label = {"character": "CHARACTER reference", "product": "PRODUCT reference"}.get(role, "reference")
        lines.append(f"- Ảnh {i}: {label} — {name}")
    return "\n".join(lines) or "- (no images attached)", chars, prods


def _markdown(cfg: dict, data: dict, scenes: list, p: dict) -> str:
    """Storyboard = prompt tạo video: thông tin dự án, khoá nhân vật / sản phẩm, từng cảnh (lời thoại + prompt)."""
    name = str(cfg.get("p_name") or "").strip()
    lines = [f"# 🎬 {str((data.get('metadata') or {}).get('title') or name or 'Product Video Studio').strip()}", "",
             "## Thông tin dự án",
             f"- Sản phẩm: **{name}**" + (f" ({cfg.get('p_code')})" if cfg.get("p_code") else "")
             + (f" · {cfg.get('p_brand')}" if cfg.get("p_brand") else ""),
             f"- Tỉ lệ {cfg.get('aspect') or '9:16'} · tổng ~{p['total']} giây · {p['count']} cảnh × {p['clip']} giây · "
             f"{'Frames to Video' if cfg.get('mode') == 'frames' else 'Ingredients to Video'}"]
    for key, title in (("character_lock", "🔒 Character Lock"), ("product_lock", "🔒 Product Lock")):
        if str(data.get(key) or "").strip():
            lines += ["", f"## {title}", str(data[key]).strip()]
    lines += ["", "## Các cảnh"]
    for i, s in enumerate(scenes, 1):
        refs = [f"Ảnh {k}" for k in s.get("anh") or []]
        lines += ["", f"### Cảnh {i} · {(i - 1) * p['clip']}–{i * p['clip']}s", s.get("noi_dung", "")]
        if s.get("goc_quay"):
            lines.append(f"- 🎥 Camera: {s['goc_quay']}")
        lines += [f"- 🗣 Lời thoại (VI): {s.get('loi') or '(không lời)'}", f"- 📎 Ảnh tham chiếu: {', '.join(refs) or 'tất cả'}",
                  "", "```text", s.get("prompt", ""), "```"]
    return "\n".join(lines) + "\n"


def run(ctx, cfg: dict, request_in: str, refs: list) -> dict:
    from ..studio import ask_model
    from .nodes import CONTENT_MODELS, STORY_WPS, _story_parse

    name = str(cfg.get("p_name") or "").strip()
    if not name:
        raise ValueError("Product Video Studio: nhập Tên sản phẩm")
    p = plan(cfg)
    voice = str(cfg.get("voice") or "female_south")
    speech = "none" if voice == "none" else str(cfg.get("speech") or "direct")
    env_key = str(cfg.get("environment") or "warehouse")
    environment = str(cfg.get("env_custom") or "").strip() if env_key == "custom" else ENVIRONMENTS.get(env_key, env_key)
    mats, chars, prods = _materials(cfg, refs)
    if not prods:
        ctx.log("Chưa có ảnh SẢN PHẨM (đặt vai trò 📦 Sản phẩm cho ảnh nối vào) — Product Lock yếu, dễ sai bao bì", "warn")
    if not chars:
        ctx.log("Chưa có ảnh NHÂN VẬT (đặt vai trò 🧍 Nhân vật) — Character Lock chỉ dựa vào mô tả", "warn")
    facts = "\n".join(f"  - {x.strip()}" for x in str(cfg.get("p_facts") or "").splitlines() if x.strip()) or "  - (none)"
    words = max(4, int((p["clip"] - 1) * STORY_WPS))
    model = str(cfg.get("model") or "chatgpt_browser")
    extra_req = " ".join(f"{request_in} {cfg.get('request') or ''}".split())[:3000]
    target = _target(cfg)
    rules = GROK_RULES.format(clip=p["clip"], start_note=FRAMES_NOTE if cfg.get("mode") == "frames"
                              else INGREDIENTS_NOTE) if target == "grok" else ""
    prompt = MASTER.format(
        target=TARGETS[target], model_rules=rules,
        product_name=name, product_code=cfg.get("p_code") or "(none)", brand=cfg.get("p_brand") or "(none)", facts=facts,
        product_images=", ".join(prods) or "(none attached)", character_images=", ".join(chars) or "(none attached)",
        character=" ".join(str(cfg.get("c_desc") or "").split()) or "(see character images)",
        lock_identity="ON" if cfg.get("lock_identity", True) else "off",
        lock_outfit="ON" if cfg.get("lock_outfit", True) else "off",
        environment=environment or "(choose a clean, realistic setting)", aspect=cfg.get("aspect") or "9:16",
        total=p["total"], clip=p["clip"], count=p["count"],
        model=cfg.get("_video_model") or ("Grok Imagine" if target == "grok" else "Google Flow (Veo)"),
        voice=VOICES[voice][1] if voice in VOICES else "no voice", words=words,
        speech={"none": "no dialogue at all", "voiceover": "silent clips — dialogue is a separate post-production "
                "voice-over (write it in loi_thoai)", "direct": "the presenter speaks the line on camera"}[speech],
        camera=CAMERAS.get(str(cfg.get("camera") or ""), "choose one slow, stable movement per scene"),
        message=" ".join(str(cfg.get("p_message") or "").split()) or "(none)",
        extra=f"- Additional request / script: {extra_req}\n" if extra_req else "", materials=mats)
    ctx.log(f"🎬 {CONTENT_MODELS.get(model, model)} lập kịch bản {p['count']} cảnh × {p['clip']}s cho “{name}”…")
    ctx.progress(0.05)
    ask = {"model": model, "text_profile": str(cfg.get("_text_profile") or ""), "show_browser": False, "timeout": 900}
    images = [str(x) for x in refs[:4]] or None
    raw = ask_model(ctx.settings, ask, prompt, complete=lambda t: bool(_story_parse(t)[1]), what="lập kịch bản quảng cáo",
                    log=ctx.log, check_cancel=ctx.check_cancel, system=SYSTEM, images=images)
    (ctx.dir / "tra-loi-model.txt").write_text(str(raw or ""), "utf-8")
    data, scenes = _story_parse(str(raw or ""))
    if not scenes:
        ctx.log("Câu trả lời chưa đúng định dạng — hỏi lại model, chỉ xin JSON…", "warn")
        raw = ask_model(ctx.settings, dict(ask), prompt + "\n\nIMPORTANT: return ONLY the ```json block described above.",
                        complete=lambda t: bool(_story_parse(t)[1]), what="lập lại kịch bản (JSON)", log=ctx.log,
                        check_cancel=ctx.check_cancel, system=SYSTEM, images=images)
        (ctx.dir / "tra-loi-model-lan-2.txt").write_text(str(raw or ""), "utf-8")
        data, scenes = _story_parse(str(raw or ""))
    if not scenes:
        raise ValueError(f"Model không trả về kịch bản hợp lệ (đã hỏi lại 1 lần) — xem {ctx.dir / 'tra-loi-model.txt'}")
    if len(scenes) > p["count"]:
        ctx.log(f"Model chia {len(scenes)} cảnh — giữ {p['count']} cảnh theo thời lượng", "warn")
        scenes = scenes[:p["count"]]
    for s in scenes:  # 🔒 khoá gắn cố định vào prompt mọi cảnh (model có quên cũng không mất)
        s["prompt"] = f"{s['prompt'].rstrip()} {_lock_text(cfg, name, s.get('co_nv', True), speech)}"[:2000]
        if speech == "none":
            s["loi"] = ""
        if speech == "voiceover":
            s["kieu"] = "dan"
    checklist = list(CHECKLIST)  # chỉ dùng cho hộp duyệt clip (✅ Duyệt), không in vào storyboard
    board = _markdown(cfg, data, scenes, p)
    narration = "\n\n".join(s["loi"] for s in scenes if s.get("loi"))
    project = {  # mục 8 — dữ liệu dự án
        "projectId": ctx.node.get("id", ""),
        "product": {"id": cfg.get("p_code") or "", "name": name, "brand": cfg.get("p_brand") or "",
                    "referenceImages": prods,
                    "facts": [x.strip() for x in str(cfg.get("p_facts") or "").splitlines() if x.strip()]},
        "character": {"referenceImages": chars, "description": str(cfg.get("c_desc") or ""), "voice": voice,
                      "lockIdentity": bool(cfg.get("lock_identity", True)), "lockOutfit": bool(cfg.get("lock_outfit", True))},
        "video": {"aspectRatio": cfg.get("aspect") or "9:16", "durationSeconds": p["total"],
                  "sceneDurationSeconds": p["clip"], "sceneCount": len(scenes), "environment": env_key,
                  "generationMode": cfg.get("mode") or "ingredients", "model": cfg.get("_video_model") or None,
                  "generateDialogue": speech == "direct"},
        "scenes": [{"sceneId": i, "durationSeconds": p["clip"], "visualPrompt": s["prompt"], "dialogue": s.get("loi", ""),
                    "referenceAssetIds": [f"Ảnh {k}" for k in s.get("anh") or []], "cameraMovement": s.get("goc_quay", ""),
                    "generationStatus": "pending", "videoUrl": None, "qcStatus": "pending", "qcNotes": ""}
                   for i, s in enumerate(scenes, 1)],
        "workflow": {"status": "draft"}}
    (ctx.dir / "storyboard.md").write_text(board, "utf-8")
    (ctx.dir / "du-an.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), "utf-8")
    ctx.log(f"🎬 Kịch bản “{name}”: {len(scenes)} cảnh × {p['clip']}s", "ok")
    ctx.progress(1.0)
    return {"storyboard": board, "text": narration, "scenes": scenes,
            "studio": {"checklist": checklist, "plan": p,
                       "voice": voice, "speech": speech, "mode": cfg.get("mode") or "ingredients",
                       "prompts": [s["prompt"] for s in scenes], "project": str(ctx.dir / "du-an.json")}}
