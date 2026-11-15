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
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    source_activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    geometry TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segment_efforts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    start_idx INTEGER NOT NULL,
    end_idx INTEGER NOT NULL,
    elapsed_s REAL,
    stats TEXT NOT NULL,
    UNIQUE (segment_id, activity_id, start_idx)
);
CREATE INDEX IF NOT EXISTS ix_efforts_segment ON segment_efforts(segment_id, elapsed_s);
CREATE INDEX IF NOT EXISTS ix_efforts_activity ON segment_efforts(activity_id);
CREATE TABLE IF NOT EXISTS activity_tags (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (activity_id, tag)
);
CREATE INDEX IF NOT EXISTS ix_tags_tag ON activity_tags(tag);
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
        self._conn.execute("PRAGMA foreign_keys = ON")
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
                (
                    sha256,
                    filename,
                    source_format,
                    device,
                    name,
                    sport,
                    summary.get("start_time"),
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(summary),
                    blob,
                ),
            )
            return cur.lastrowid

    def list_activities(self, sport: str | None = None, tag: str | None = None) -> list[dict]:
        q = f"SELECT {LIST_COLUMNS} FROM activities"
        where, args = [], []
        if sport:
            where.append("sport = ?")
            args.append(sport)
        if tag:
            where.append("id IN (SELECT activity_id FROM activity_tags WHERE tag = ?)")
            args.append(tag)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY COALESCE(start_time, created_at) DESC"
        with self._tx() as c:
            rows = [self._row(r) for r in c.execute(q, args).fetchall()]
            tags = self._tags_by_activity(c)
        for r in rows:
            r["tags"] = tags.get(r["id"], [])
        return rows

    def get(self, activity_id: int, with_points=True) -> dict | None:
        cols = "*" if with_points else LIST_COLUMNS
        with self._tx() as c:
            r = c.execute(f"SELECT {cols} FROM activities WHERE id = ?", (activity_id,)).fetchone()
            if not r:
                return None
            row = self._row(r, with_points)
            row["tags"] = self._tags_by_activity(c, activity_id).get(activity_id, [])
        return row

    # ---------------------------------------------------------------- tags
    @staticmethod
    def _tags_by_activity(c, activity_id: int | None = None) -> dict[int, list[str]]:
        q, args = "SELECT activity_id, tag FROM activity_tags", ()
        if activity_id is not None:
            q, args = q + " WHERE activity_id = ?", (activity_id,)
        out: dict[int, list[str]] = {}
        for r in c.execute(q + " ORDER BY tag", args).fetchall():
            out.setdefault(r["activity_id"], []).append(r["tag"])
        return out

    def set_tags(self, activity_id: int, tags: list[str]) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM activity_tags WHERE activity_id = ?", (activity_id,))
            c.executemany(
                "INSERT INTO activity_tags (activity_id, tag) VALUES (?, ?)", [(activity_id, t) for t in tags]
            )

    def all_tags(self) -> list[dict]:
        with self._tx() as c:
            rows = c.execute("SELECT tag, COUNT(*) AS count FROM activity_tags GROUP BY tag ORDER BY tag").fetchall()
        return [dict(r) for r in rows]

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
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, json.dumps(v)),
                )
        return self.get_settings()

    # ---------------------------------------------------------------- segments
    @staticmethod
    def _segment(row) -> dict:
        d = dict(row)
        d.update(json.loads(d.pop("geometry")))
        return d

    def add_segment(self, *, name: str, sport: str, source_activity_id: int, geometry: dict) -> int:
        with self._tx() as c:
            return c.execute(
                "INSERT INTO segments (name, sport, source_activity_id, created_at, geometry) VALUES (?,?,?,?,?)",
                (name, sport, source_activity_id, datetime.now(timezone.utc).isoformat(), json.dumps(geometry)),
            ).lastrowid

    def list_segments(self) -> list[dict]:
        q = """SELECT s.*, COUNT(e.id) AS effort_count, COUNT(DISTINCT e.activity_id) AS activity_count,
                      MIN(e.elapsed_s) AS best_s
               FROM segments s LEFT JOIN segment_efforts e ON e.segment_id = s.id
               GROUP BY s.id ORDER BY s.name COLLATE NOCASE"""
        with self._tx() as c:
            return [self._segment(r) for r in c.execute(q).fetchall()]

    def get_segment(self, segment_id: int) -> dict | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM segments WHERE id = ?", (segment_id,)).fetchone()
        return self._segment(r) if r else None

    def rename_segment(self, segment_id: int, name: str) -> bool:
        with self._tx() as c:
            return c.execute("UPDATE segments SET name = ? WHERE id = ?", (name, segment_id)).rowcount > 0

    def delete_segment(self, segment_id: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM segments WHERE id = ?", (segment_id,)).rowcount > 0

    def set_efforts(self, segment_id: int, activity_id: int, efforts: list[dict]) -> None:
        """Replace the efforts of one activity on one segment."""
        with self._tx() as c:
            c.execute("DELETE FROM segment_efforts WHERE segment_id = ? AND activity_id = ?", (segment_id, activity_id))
            c.executemany(
                "INSERT INTO segment_efforts (segment_id, activity_id, start_idx, end_idx, elapsed_s, stats)"
                " VALUES (?,?,?,?,?,?)",
                [
                    (segment_id, activity_id, e["start"], e["end"], e["stats"].get("elapsed_s"), json.dumps(e["stats"]))
                    for e in efforts
                ],
            )

    _EFFORT_SELECT = """
        SELECT e.id, e.segment_id, e.activity_id, e.start_idx AS start, e.end_idx AS "end", e.stats,
               s.name AS segment_name, a.name AS activity_name, a.sport AS activity_sport,
               a.start_time AS activity_start,
               RANK() OVER (PARTITION BY e.segment_id ORDER BY e.elapsed_s IS NULL, e.elapsed_s) AS rank,
               COUNT(*) OVER (PARTITION BY e.segment_id) AS "of"
        FROM segment_efforts e JOIN segments s ON s.id = e.segment_id JOIN activities a ON a.id = e.activity_id"""

    def _efforts(self, where: str, arg) -> list[dict]:
        q = f"SELECT * FROM ({self._EFFORT_SELECT}) WHERE {where} ORDER BY rank, start"
        with self._tx() as c:
            rows = [dict(r) for r in c.execute(q, (arg,)).fetchall()]
        for r in rows:
            r.update(json.loads(r.pop("stats")))
        return rows

    def efforts_for_segment(self, segment_id: int) -> list[dict]:
        return self._efforts("segment_id = ?", segment_id)

    def efforts_for_activity(self, activity_id: int) -> list[dict]:
        rows = self._efforts("activity_id = ?", activity_id)
        return sorted(rows, key=lambda r: r["start"])

    # ---------------------------------------------------------------- raw access (module SDK)
    def run(self, sql: str, args: tuple | list = (), *, script: bool = False) -> list[dict]:
        """Execute SQL under the store lock and return rows as dicts.

        Used by ``app.sdk.ModuleDB``, which restricts writes to the module's own tables.
        """
        with self._tx() as c:
            if script:
                c.executescript(sql)
                return []
            cur = c.execute(sql, args)
            return [dict(r) for r in cur.fetchall()] if cur.description else []
