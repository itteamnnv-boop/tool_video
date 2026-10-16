"""Thư viện ảnh đã tạo: <output_dir>/_images/<id>/{img_N.*, meta.json}."""
import shutil
from pathlib import Path
from urllib.parse import quote

from .util import read_json

IMAGES_DIR = "_images"
META = "meta.json"


class ImageLibraryError(RuntimeError):
    pass


def root(output_dir: Path) -> Path:
    path = output_dir / IMAGES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(output_dir: Path, job_id: str) -> Path:
    if not job_id or any(c in job_id for c in "/\\:") or job_id.startswith("."):
        raise ImageLibraryError("Mã bộ ảnh không hợp lệ")
    path = root(output_dir) / job_id
    if not (path / META).is_file():
        raise ImageLibraryError("Không tìm thấy bộ ảnh")
    return path


def summary(job_dir: Path, meta: dict) -> dict:
    files = []
    for name in meta.get("files", []):
        path = job_dir / name
        if path.exists():
            files.append({"name": name, "url": f"/media/{IMAGES_DIR}/{quote(job_dir.name)}/{quote(name)}"
                                                  f"?v={int(path.stat().st_mtime)}"})
    return {**{k: meta.get(k) for k in ("id", "title", "prompt", "engine", "engine_name", "aspect", "created_at")},
            "files": files}


def list_images(output_dir: Path) -> list[dict]:
    items = []
    for folder in root(output_dir).iterdir():
        if (folder / META).is_file():
            try:
                items.append(summary(folder, read_json(folder / META)))
            except (OSError, ValueError):
                continue
    return sorted(items, key=lambda m: m.get("created_at") or "", reverse=True)


def delete_images(output_dir: Path, job_id: str) -> None:
    shutil.rmtree(job_path(output_dir, job_id))
