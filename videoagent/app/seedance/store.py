"""SQLite checkpoints; image blobs live on disk, outside the UI process."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .domain import DEFAULT_CONFIG


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "studio.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")
        self.db.commit()
        # A crash after submit is ambiguous: never silently resend it.
        for job in self.list("jobs"):
            if job["status"] in ("preparing", "attaching", "submitting", "submitted", "generating", "downloading"):
                self.put("jobs", {**job, "status": "interrupted", "error": "App đã đóng khi đang xử lý; kiểm tra chat trước khi thử lại.", "code": "INTERRUPTED"})

    def list(self, kind):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM records WHERE kind=? ORDER BY rowid", (kind,))]

    def get(self, kind, id):
        with self.lock:
            row = self.db.execute("SELECT data FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, kind, data):
        with self.lock:
            self.db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                            (kind, data["id"], json.dumps(data, ensure_ascii=False)))
            self.db.commit()
        return data

    def update(self, kind, id, **values):
        with self.lock:
            record = self.get(kind, id)
            if not record:
                raise ValueError("Không tìm thấy bản ghi")
            return self.put(kind, {**record, **values, "updatedAt": now()})

    def delete(self, kind, id):
        with self.lock:
            self.db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, id))
            self.db.commit()

    def config(self):
        return {**DEFAULT_CONFIG, **(self.get("settings", "config") or {}).get("values", {})}

    def event(self, message, *, job_id="", level="info", code="", **details):
        with self.lock:
            self.put("events", {"id": uid(), "timestamp": now(), "message": message, "jobId": job_id,
                                "level": level, "code": code, **details})
            self.db.execute("DELETE FROM records WHERE kind='events' AND rowid NOT IN (SELECT rowid FROM records WHERE kind='events' ORDER BY rowid DESC LIMIT 2000)")
            self.db.commit()
