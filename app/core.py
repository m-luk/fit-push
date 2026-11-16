"""The core service: every operation that changes or derives data goes through here.

Routes (``app/routes``) are thin HTTP adapters over this class, and modules get a
read-mostly facade of it through ``app.sdk``. Keeping orchestration in one place
is what keeps the invariants in AGENTS.md true: derived data (summaries, lap
cache, segment efforts) is refreshed on every change, and events are emitted
so modules can react.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from . import sports, tutorial
from .analytics import ANALYSIS_VERSION, _prepare, activity_to_columns, analyse, point_count, window_columns
from .events import EventBus
from .laps import detect_laps, lap_report
from .parsers import ParseError, normalise_sport, parse_file
from .segments import SegmentError, build_segment, effort_stats, find_efforts
from .storage import Store

MAX_TAGS = 20
TAG_RE = re.compile(r"[^\w\- ]+", re.UNICODE)


class NotFound(LookupError):
    """Requested object does not exist (HTTP 404)."""


class Invalid(ValueError):
    """Request cannot be fulfilled with the given input (HTTP 422)."""


def stored_summary(result: dict) -> dict:
    """What is persisted for list/stats views: the summary plus small aggregates."""
    return {
        **result["summary"],
        "best_efforts": result["best_efforts"],
        "power_curve": result["power_curve"],
        "hr_zones": result["hr_zones"],
    }


def normalise_tags(tags: list[str]) -> list[str]:
    """Lower-case, trimmed, de-duplicated tags of letters, digits, space, '-' and '_' (max 32 chars)."""
    out: list[str] = []
    for t in tags:
        t = " ".join(TAG_RE.sub("", str(t)).lower().split())[:32].strip()
        if t and t not in out:
            out.append(t)
    if len(out) > MAX_TAGS:
        raise Invalid(f"at most {MAX_TAGS} tags per activity")
    return sorted(out)


class Core:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.events = EventBus()
        self._lap_cache: dict[tuple[int, str], dict | None] = {}

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict:
        return self.store.get_settings()

    def update_settings(self, values: dict) -> dict:
        settings = self.store.set_settings(values)
        if values:  # zones / TSS / TRIMP depend on settings -> refresh stored summaries
            for aid in self.store.all_ids():
                row = self.row(aid)
                self.store.update(aid, summary=stored_summary(analyse(row["points"], row["sport"], settings)))
            self.events.emit("settings.changed", settings=settings)
        return settings

    def refresh_stale_summaries(self) -> int:
        """Recompute stored summaries made by an older analysis (once per ANALYSIS_VERSION).

        Activities are immutable, but how they are analysed improves; a summary stored by an
        older version would disagree with the activity page. Returns how many were refreshed.
        """
        if self.store.get_meta("analysis_version") == ANALYSIS_VERSION:
            return 0
        settings, ids = self.settings(), self.store.all_ids()
        for aid in ids:
            row = self.row(aid)
            try:
                self.store.update(aid, summary=stored_summary(analyse(row["points"], row["sport"], settings)))
            except ValueError:
                continue  # keep the old summary of an activity the analysis cannot read
        self.store.set_meta("analysis_version", ANALYSIS_VERSION)
        return len(ids)

    # ------------------------------------------------------------------ activities
    def row(self, activity_id: int, with_points: bool = True) -> dict:
        row = self.store.get(activity_id, with_points)
        if not row:
            raise NotFound("activity not found")
        return row

    def window(self, row: dict, start: int | None, end: int | None) -> tuple[dict, dict | None]:
        """(columns, window info) for points ``start..end``; the whole activity when both are None."""
        if start is None and end is None:
            return row["points"], None
        total = point_count(row["points"])
        try:
            cols = window_columns(row["points"], start, end)
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
        return cols, {"start": start or 0, "end": total - 1 if end is None else end, "total_points": total}

    def import_file(self, filename: str, data: bytes) -> dict:
        """Parse and store one uploaded file. Returns {status: imported|duplicate, ...}."""
        sha = hashlib.sha256(data).hexdigest()
        if (existing := self.store.find_by_hash(sha)) is not None:
            return {"status": "duplicate", "filename": filename, "id": existing}
        try:
            act = parse_file(filename, data)
            cols = activity_to_columns(act)
            result = analyse(cols, act.sport, self.settings())
        except (ParseError, ValueError) as exc:
            raise Invalid(str(exc)) from exc
        new_id = self._add(
            sha256=sha,
            filename=filename,
            source_format=act.source_format,
            device=act.device,
            name=act.name,
            sport=act.sport,
            result=result,
            cols=cols,
        )
        return {"status": "imported", "filename": filename, "id": new_id, "name": act.name, "sport": act.sport}

    def peek_file(self, filename: str, data: bytes) -> dict:
        """Parse a file without storing it: {sha256, duplicate_of, name, sport, start_time}.

        Lets importers match a file to an activity that came from a different copy of it
        (same start time, other bytes) before deciding to import.
        """
        sha = hashlib.sha256(data).hexdigest()
        try:
            act = parse_file(filename, data)
            t = _prepare(activity_to_columns(act))["t"]
        except (ParseError, ValueError) as exc:
            raise Invalid(str(exc)) from exc
        start = datetime.fromtimestamp(float(t[0]), tz=UTC).isoformat() if len(t) and t[0] == t[0] else None
        return {
            "sha256": sha,
            "duplicate_of": self.store.find_by_hash(sha),
            "name": act.name,
            "sport": act.sport,
            "start_time": start,
        }

    def clip(self, activity_id: int, start: int | None, end: int | None, name: str | None) -> dict:
        """Save points ``start..end`` as a new activity (duplicate-safe)."""
        row = self.row(activity_id)
        cols, window = self.window(row, start, end)
        if window is None:
            raise Invalid("start or end required")
        sha = hashlib.sha256(f"clip:{row['sha256']}:{window['start']}:{window['end']}".encode()).hexdigest()
        if (existing := self.store.find_by_hash(sha)) is not None:
            return {"id": existing, "duplicate": True}
        try:
            result = analyse(cols, row["sport"], self.settings())
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
        name = name or f"{row['name']} (clip)"
        new_id = self._add(
            sha256=sha,
            filename=row["filename"],
            source_format=row["source_format"],
            device=row["device"],
            name=name,
            sport=row["sport"],
            result=result,
            cols=cols,
        )
        return {"id": new_id, "duplicate": False, "name": name}

    def _add(self, *, result: dict, cols: dict, sport: str, **meta) -> int:
        new_id = self.store.add(summary=stored_summary(result), points=cols, sport=sport, **meta)
        self._match_activity({"id": new_id, "sport": sport, "points": cols})
        self.events.emit("activity.imported", activity_id=new_id)
        return new_id

    def update_activity(self, activity_id: int, name: str | None = None, sport: str | None = None) -> dict:
        row = self.row(activity_id)
        fields: dict = {"name": name}
        if sport:
            row["sport"] = normalise_sport(sport)
            fields["sport"] = row["sport"]
            fields["summary"] = stored_summary(analyse(row["points"], row["sport"], self.settings()))
        self.store.update(activity_id, **fields)
        if sport:  # moving time depends on the sport
            self._match_activity(row)
        changed = [k for k in ("name", "sport") if fields.get(k) is not None]
        if changed:
            self.events.emit("activity.updated", activity_id=activity_id, fields=changed)
        return self.row(activity_id, with_points=False)

    def set_tags(self, activity_id: int, tags: list[str]) -> list[str]:
        self.row(activity_id, with_points=False)
        tags = normalise_tags(tags)
        self.store.set_tags(activity_id, tags)
        self.events.emit("activity.updated", activity_id=activity_id, fields=["tags"])
        return tags

    def delete_activity(self, activity_id: int) -> None:
        if not self.store.delete(activity_id):
            raise NotFound("activity not found")
        self.events.emit("activity.deleted", activity_id=activity_id)

    def analysis(
        self, activity_id: int, split_m: float = 1000.0, start: int | None = None, end: int | None = None
    ) -> dict:
        """Full analysis for the activity page; ``start``/``end`` give a temporary trimmed view."""
        row = self.row(activity_id)
        cols, window = self.window(row, start, end)
        result = analyse(cols, row["sport"], self.settings(), split_m)
        if window is not None:
            result["series"]["idx"] = [i + window["start"] for i in result["series"]["idx"]]
        result["window"] = window
        det = self.laps(row)
        result["laps"] = None if det is None else {k: det[k] for k in ("count", "start", "end", "lap_distance_m")}
        result["segment_efforts"] = self.store.efforts_for_activity(activity_id)
        meta = {
            k: row[k]
            for k in ("id", "filename", "source_format", "device", "name", "sport", "start_time", "created_at", "tags")
        }
        return {**meta, **result}

    # ------------------------------------------------------------------ laps
    def laps(self, row: dict) -> dict | None:
        """Lap detection, cached by (id, sha256): points never change."""
        key = (row["id"], row["sha256"])
        if key not in self._lap_cache:
            if len(self._lap_cache) > 256:
                self._lap_cache.clear()
            self._lap_cache[key] = detect_laps(row["points"])
        return self._lap_cache[key]

    def lap_report(self, activity_id: int) -> dict:
        row = self.row(activity_id)
        det = self.laps(row)
        if det is None:
            raise NotFound("no repeating laps detected")
        return lap_report(row["points"], row["sport"], self.settings(), det)

    # ------------------------------------------------------------------ segments
    def _match(self, segment: dict, row: dict) -> int:
        efforts = [
            {"start": i, "end": j, "stats": effort_stats(row["points"], i, j, row["sport"])}
            for i, j in find_efforts(segment, row["points"])
        ]
        self.store.set_efforts(segment["id"], row["id"], efforts)
        return len(efforts)

    def _match_activity(self, row: dict) -> None:
        for seg in self.store.list_segments():
            self._match(seg, row)

    def _match_segment(self, seg: dict) -> int:
        return sum(self._match(seg, self.row(aid)) for aid in self.store.all_ids())

    def segment(self, segment_id: int) -> dict:
        seg = self.store.get_segment(segment_id)
        if not seg:
            raise NotFound("segment not found")
        return seg

    def segment_detail(self, segment_id: int) -> dict:
        seg = self.segment(segment_id)
        efforts = self.store.efforts_for_segment(segment_id)
        by_activity: dict[int, dict] = {}
        for e in efforts:  # ordered best first, so the first effort per activity is its best
            a = by_activity.setdefault(
                e["activity_id"],
                {
                    "activity_id": e["activity_id"],
                    "name": e["activity_name"],
                    "sport": e["activity_sport"],
                    "start_time": e["activity_start"],
                    "efforts": 0,
                    "best": e,
                },
            )
            a["efforts"] += 1
        activities = sorted(by_activity.values(), key=lambda a: a["start_time"] or "", reverse=True)
        return {**seg, "efforts": efforts, "activities": activities}

    def create_segment(self, activity_id: int, start: int, end: int, name: str | None) -> dict:
        row = self.row(activity_id)
        try:
            geometry = build_segment(row["points"], start, end, row["sport"])
        except (SegmentError, ValueError) as exc:
            raise Invalid(str(exc)) from exc
        seg_id = self.store.add_segment(
            name=name or f"{row['name']} segment", sport=row["sport"], source_activity_id=row["id"], geometry=geometry
        )
        self._match_segment(self.segment(seg_id))
        self.events.emit("segment.changed", segment_id=seg_id)
        return self.segment_detail(seg_id)

    def rename_segment(self, segment_id: int, name: str) -> dict:
        self.segment(segment_id)
        self.store.rename_segment(segment_id, name)
        self.events.emit("segment.changed", segment_id=segment_id)
        return self.segment_detail(segment_id)

    def rescan_segment(self, segment_id: int) -> dict:
        self._match_segment(self.segment(segment_id))
        self.events.emit("segment.changed", segment_id=segment_id)
        return self.segment_detail(segment_id)

    def delete_segment(self, segment_id: int) -> None:
        if not self.store.delete_segment(segment_id):
            raise NotFound("segment not found")
        self.events.emit("segment.deleted", segment_id=segment_id)

    # ------------------------------------------------------------------ tutorial
    def _tutorial_ids(self) -> list[int]:
        rows = self.store.run("SELECT id FROM activities WHERE device = ? ORDER BY id", (tutorial.DEVICE,))
        return [r["id"] for r in rows]

    def tutorial_status(self) -> dict:
        found = self.store.find_by_hash(tutorial.SHA256)
        return {"activity_id": found, "activities": len(self._tutorial_ids())}

    def start_tutorial(self) -> dict:
        """Create the simulated run of the tutorial (or reuse it). Tagged ``tutorial``."""
        if (existing := self.store.find_by_hash(tutorial.SHA256)) is not None:
            return {"activity_id": existing, "created": False}
        act = tutorial.simulated_run()
        cols = activity_to_columns(act)
        new_id = self._add(
            sha256=tutorial.SHA256,
            filename="tutorial-run.fit",
            source_format=act.source_format,
            device=act.device,
            name=act.name,
            sport=act.sport,
            result=analyse(cols, act.sport, self.settings()),
            cols=cols,
        )
        self.store.set_tags(new_id, ["tutorial"])
        return {"activity_id": new_id, "created": True}

    def end_tutorial(self) -> dict:
        """Remove the tutorial run, clips saved from it and segments created on them."""
        ids = self._tutorial_ids()
        segments = [s["id"] for s in self.store.list_segments() if s.get("source_activity_id") in ids]
        for seg_id in segments:
            self.delete_segment(seg_id)
        for act_id in ids:
            self.delete_activity(act_id)
        return {"activities": len(ids), "segments": len(segments)}

    # ------------------------------------------------------------------ catalogue
    @staticmethod
    def sports() -> list[dict]:
        return sports.catalogue()
