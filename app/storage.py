"""SQLite persistence. Raw points are stored zlib-compressed as column JSON."""
from __future__ import annotations

import json
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .analytics import DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    source_format TEXT NOT NULL,
    device TEXT,
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    start_time TEXT,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    points BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_activities_start ON activities(start_time);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

LIST_COLUMNS = "id, filename, source_format, device, name, sport, start_time, created_at, summary"


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._tx() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @staticmethod
    def _row(row, with_points=False) -> dict:
        d = dict(row)
        d["summary"] = json.loads(d["summary"])
        if with_points:
            d["points"] = json.loads(zlib.decompress(d["points"]))
        return d

    # ---------------------------------------------------------------- activities
    def find_by_hash(self, sha: str) -> int | None:
        with self._tx() as c:
            r = c.execute("SELECT id FROM activities WHERE sha256 = ?", (sha,)).fetchone()
        return r["id"] if r else None

    def add(self, *, sha256, filename, source_format, device, name, sport, summary, points) -> int:
        blob = zlib.compress(json.dumps(points, separators=(",", ":")).encode(), 6)
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO activities (sha256, filename, source_format, device, name, sport,"
                " start_time, created_at, summary, points) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sha256, filename, source_format, device, name, sport, summary.get("start_time"),
                 datetime.now(timezone.utc).isoformat(), json.dumps(summary), blob),
            )
            return cur.lastrowid

    def list(self, sport: str | None = None) -> list[dict]:
        q = f"SELECT {LIST_COLUMNS} FROM activities"
        args: tuple = ()
        if sport:
            q += " WHERE sport = ?"
            args = (sport,)
        q += " ORDER BY COALESCE(start_time, created_at) DESC"
        with self._tx() as c:
            return [self._row(r) for r in c.execute(q, args).fetchall()]

    def get(self, activity_id: int, with_points=True) -> dict | None:
        cols = "*" if with_points else LIST_COLUMNS
        with self._tx() as c:
            r = c.execute(f"SELECT {cols} FROM activities WHERE id = ?", (activity_id,)).fetchone()
        return self._row(r, with_points) if r else None

    def update(self, activity_id: int, **fields) -> None:
        allowed = {"name", "sport", "summary", "start_time"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return
        if "summary" in fields:
            fields["summary"] = json.dumps(fields["summary"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE activities SET {sets} WHERE id = ?", (*fields.values(), activity_id))

    def delete(self, activity_id: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM activities WHERE id = ?", (activity_id,)).rowcount > 0

    def all_ids(self) -> list[int]:
        with self._tx() as c:
            return [r["id"] for r in c.execute("SELECT id FROM activities").fetchall()]

    # ---------------------------------------------------------------- settings
    def get_settings(self) -> dict:
        with self._tx() as c:
            rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {**DEFAULT_SETTINGS, **{r["key"]: json.loads(r["value"]) for r in rows}}

    def set_settings(self, values: dict) -> dict:
        with self._tx() as c:
            for k, v in values.items():
                c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
        return self.get_settings()
