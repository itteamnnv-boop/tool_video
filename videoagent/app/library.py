"""Thư viện video đã xuất: mỗi video là một thư mục trong output_dir chứa job.json."""
import shutil
from pathlib import Path
from urllib.parse import quote

from .pipeline import scene_dir_name
from .util import read_json, write_json

JOB_FILE = "job.json"


class LibraryError(RuntimeError):
    pass


def job_path(root: Path, job_id: str) -> Path:
    if not job_id or any(c in job_id for c in "/\\:") or job_id.startswith("."):
        raise LibraryError("Mã video không hợp lệ")
    path = root / job_id
    if not (path / JOB_FILE).is_file():
        raise LibraryError("Không tìm thấy video trong thư viện")
    return path


def load_job(root: Path, job_id: str) -> tuple[Path, dict]:
    path = job_path(root, job_id)
    return path, read_json(path / JOB_FILE)


def save_job(job_dir: Path, job: dict) -> None:
    write_json(job_dir / JOB_FILE, job)


def _media_url(job_id: str, rel: str, path: Path) -> str:
    if not path.exists():
        return ""
    return f"/media/{quote(job_id)}/{rel}?v={int(path.stat().st_mtime)}"


def summary(job_dir: Path, job: dict) -> dict:
    job_id = job_dir.name
    scenes = job.get("scenes") or []
    thumb_rel = f"scenes/{scene_dir_name(scenes[0]['index'])}/thumb.jpg" if scenes else ""
    final = job_dir / "final.mp4"
    return {
        "id": job_id, "title": job.get("title", job_id), "topic": job.get("topic", ""),
        "aspect": job.get("aspect", "9:16"), "width": job.get("width"), "height": job.get("height"),
        "duration": round(float(job.get("duration") or 0), 3), "scene_count": len(scenes),
        "template_id": job.get("template_id", ""), "template_name": job.get("template_name", ""),
        "voice": job.get("voice", ""), "subtitles": bool(job.get("subtitles")), "bgm": bool(job.get("bgm")),
        "created_at": job.get("created_at", ""), "has_final": final.exists(),
        "final_url": _media_url(job_id, "final.mp4", final),
        "thumb_url": _media_url(job_id, thumb_rel, job_dir / thumb_rel) if thumb_rel else "",
    }


def detail(job_dir: Path, job: dict) -> dict:
    out = summary(job_dir, job)
    scenes = []
    for scene in job.get("scenes") or []:
        rel = f"scenes/{scene_dir_name(scene['index'])}"
        scenes.append({
            "index": scene["index"], "kicker": scene.get("kicker", ""), "headline": scene.get("headline", ""),
            "duration": scene.get("duration", 0),
            "thumb_url": _media_url(job_dir.name, f"{rel}/thumb.jpg", job_dir / rel / "thumb.jpg"),
            "html_url": _media_url(job_dir.name, f"{rel}/scene.html", job_dir / rel / "scene.html"),
            "video_url": _media_url(job_dir.name, f"{rel}/scene.mp4", job_dir / rel / "scene.mp4"),
        })
    out["scenes"] = scenes
    return out


def list_videos(root: Path) -> list[dict]:
    items = []
    for folder in root.iterdir():
        if not (folder / JOB_FILE).is_file():
            continue
        try:
            items.append(summary(folder, read_json(folder / JOB_FILE)))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(items, key=lambda v: v["created_at"], reverse=True)


def delete_video(root: Path, job_id: str) -> None:
    shutil.rmtree(job_path(root, job_id))
