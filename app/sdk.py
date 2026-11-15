"""Module SDK (backend): the only part of the app a module's ``backend.py`` may import.

A module exposes ``register(ctx: ModuleContext) -> None``. Through ``ctx`` it gets:

- ``ctx.router``: a FastAPI ``APIRouter`` mounted at ``/api/m/<module id>``;
- ``ctx.core``: read-mostly access to activities, points, analysis, sports, tags, segments;
- ``ctx.db``: SQLite access restricted to the module's own tables (``ctx.db.table("x")``
  gives the prefixed name ``m_<id>_x``);
- ``ctx.on(event, handler)``: react to core events (see ``app.events.EVENTS``);
- ``ctx.log``: a logger named after the module.

Everything here is a stable contract (``SDK_VERSION``). Breaking changes bump the
major version; modules declare the major they target in ``module.json`` (``"sdk": "1"``).
Full reference: docs/SDK.md.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from fastapi import APIRouter

from .analytics import _prepare, analyse, window_columns
from .core import Core, Invalid, NotFound

SDK_VERSION = "1.0"

__all__ = ["SDK_VERSION", "CoreAPI", "Invalid", "ModuleContext", "ModuleDB", "NotFound"]

_WRITE = re.compile(
    r"^\s*(?:insert\s+(?:or\s+\w+\s+)?into|replace\s+into|update(?:\s+or\s+\w+)?|delete\s+from"
    r"|create\s+(?:unique\s+)?(?:table|index|view|trigger)\s+(?:if\s+not\s+exists\s+)?"
    r"|drop\s+(?:table|index|view|trigger)\s+(?:if\s+exists\s+)?|alter\s+table)\s*[\"`\[]?(\w+)",
    re.IGNORECASE,
)
_READ = re.compile(r"^\s*(?:select|with)\b", re.IGNORECASE)


class ModuleDB:
    """SQLite access for one module. Writes may only touch tables/indexes named ``m_<id>_*``.

    Read the core's data through ``ctx.core``, not with SQL: core tables may change.
    """

    def __init__(self, core: Core, module_id: str) -> None:
        self._store = core.store
        self.prefix = f"m_{module_id}_"

    def table(self, name: str) -> str:
        """Prefixed table (or index) name for this module."""
        return self.prefix + name

    def _check(self, sql: str) -> None:
        m = _WRITE.match(sql)
        if m:
            if not m.group(1).lower().startswith(self.prefix):
                raise PermissionError(f"modules may only write their own tables ({self.prefix}*): {sql[:80]!r}")
        elif not _READ.match(sql):
            raise PermissionError(f"statement not allowed for modules: {sql[:80]!r}")

    def execute(self, sql: str, args: tuple | list = ()) -> list[dict]:
        """Run one statement; returns rows for SELECT/WITH, [] otherwise."""
        self._check(sql)
        return self._store.run(sql, args)

    def query(self, sql: str, args: tuple | list = ()) -> list[dict]:
        return self.execute(sql, args)

    def script(self, sql: str) -> None:
        """Run several ';'-separated statements (e.g. CREATE TABLE IF NOT EXISTS ...)."""
        for stmt in (s for s in sql.split(";") if s.strip()):
            self._check(stmt)
        self._store.run(sql, script=True)


class CoreAPI:
    """What a module may read (and the few things it may do) in the core."""

    def __init__(self, core: Core) -> None:
        self._core = core

    # activities
    def list_activities(self, sport: str | None = None, tag: str | None = None) -> list[dict]:
        """Newest first: id, name, sport, start_time, filename, summary (dict), tags (list)."""
        return self._core.store.list_activities(sport, tag)

    def activity(self, activity_id: int) -> dict:
        """Metadata + stored summary + tags (no points). Raises NotFound."""
        return self._core.row(activity_id, with_points=False)

    def points(self, activity_id: int) -> dict[str, list]:
        """Cleaned point columns (t, lat, lon, ele, hr, cad, power, speed, temp, dist). Indices match
        every other index in the app (trim windows, laps, segment efforts)."""
        return window_columns(self._core.row(activity_id)["points"])

    def analyse(self, cols: dict[str, list], sport: str = "unknown") -> dict:
        """Run the core analysis on point columns (e.g. a window you cut from ``points``)."""
        return analyse(cols, sport, self._core.settings())

    def track(self, activity_id: int, step_m: float = 20.0, max_points: int = 600) -> list[list[float]]:
        """GPS line as [[lat, lon], ...], thinned to about one point every ``step_m`` metres."""
        a = _prepare(self._core.row(activity_id)["points"])
        lat, lon = a["lat"], a["lon"]
        ok = np.isfinite(lat) & np.isfinite(lon)
        lat, lon = lat[ok], lon[ok]
        if len(lat) < 2:
            return []
        x = np.radians(lon) * 6_371_000 * np.cos(np.radians(np.mean(lat)))
        y = np.radians(lat) * 6_371_000
        d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        step = max(step_m, d[-1] / max_points)
        keep = np.unique(np.searchsorted(d, np.arange(0, d[-1], step)))
        keep = np.append(keep, len(lat) - 1) if keep[-1] != len(lat) - 1 else keep
        return [[round(float(lat[i]), 5), round(float(lon[i]), 5)] for i in keep]

    # catalogue & settings
    def sports(self) -> list[dict]:
        return self._core.sports()

    def settings(self) -> dict:
        return self._core.settings()

    def tags(self) -> list[dict]:
        """[{tag, count}] for all tags in use."""
        return self._core.store.all_tags()

    def segments(self) -> list[dict]:
        return [{k: v for k, v in s.items() if k != "points"} for s in self._core.store.list_segments()]

    # actions a module may take (they keep core invariants and emit events)
    def set_tags(self, activity_id: int, tags: list[str]) -> list[str]:
        return self._core.set_tags(activity_id, tags)


@dataclass
class ModuleContext:
    id: str
    manifest: dict
    dir: Path
    core: CoreAPI
    db: ModuleDB
    router: APIRouter
    _on: Callable[[str, Callable], None]
    log: logging.Logger = field(init=False)

    def __post_init__(self) -> None:
        self.log = logging.getLogger(f"fitpush.module.{self.id}")

    def on(self, event: str, handler: Callable) -> None:
        """Call ``handler(**payload)`` after a core event (errors are caught and reported)."""
        self._on(event, handler)
