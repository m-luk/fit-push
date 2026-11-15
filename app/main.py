"""FastAPI application: upload, store, analyse and visualise activity files."""
from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import sports, writers
from .analytics import activity_to_columns, analyse, cumulative_distance, point_count, window_columns
from .laps import detect_laps, lap_report
from .segments import SegmentError, build_segment, effort_stats, find_efforts
from .parsers import ParseError, normalise_sport, parse_file
from .storage import Store

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

WindowStart = Annotated[int | None, Query(ge=0, description="first point index (inclusive)")]
WindowEnd = Annotated[int | None, Query(ge=1, description="last point index (inclusive)")]


class ActivityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sport: str | None = Field(default=None, min_length=1, max_length=40)


class ClipIn(BaseModel):
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class SegmentIn(BaseModel):
    activity_id: int
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class SegmentPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SettingsIn(BaseModel):
    max_hr: int | None = Field(default=None, ge=100, le=250)
    rest_hr: int | None = Field(default=None, ge=25, le=120)
    ftp: int | None = Field(default=None, ge=50, le=600)


def _stored_summary(result: dict) -> dict:
    """What we persist for list/stats views: summary + small aggregates."""
    return {
        **result["summary"],
        "best_efforts": result["best_efforts"],
        "power_curve": result["power_curve"],
        "hr_zones": result["hr_zones"],
    }


def create_app(db_path: str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("FITGIT_DB", str(Path("data") / "activities.db"))
    store = Store(db_path)
    app = FastAPI(title="fit-git", version="0.1.0")
    app.state.store = store

    def _analyse_row(row: dict, split_m: float = 1000.0) -> dict:
        return analyse(row["points"], row["sport"], store.get_settings(), split_m)

    # Lap detection depends only on the (immutable) points, so cache it per activity.
    lap_cache: dict[tuple[int, str], dict | None] = {}

    def _detect(row: dict) -> dict | None:
        key = (row["id"], row["sha256"])
        if key not in lap_cache:
            if len(lap_cache) > 256:
                lap_cache.clear()
            lap_cache[key] = detect_laps(row["points"])
        return lap_cache[key]

    # Segment matching: (segment, activity) pairs are re-matched whenever either side changes.
    def _match(segment: dict, row: dict) -> int:
        efforts = [{"start": i, "end": j, "stats": effort_stats(row["points"], i, j, row["sport"])}
                   for i, j in find_efforts(segment, row["points"])]
        store.set_efforts(segment["id"], row["id"], efforts)
        return len(efforts)

    def _match_activity(row: dict) -> None:
        for seg in store.list_segments():
            _match(seg, row)

    def _match_segment(seg: dict) -> int:
        return sum(_match(seg, store.get(aid)) for aid in store.all_ids())

    # ------------------------------------------------------------------ activities
    @app.post("/api/activities")
    async def upload(files: Annotated[list[UploadFile], File(...)]):
        imported, duplicates, errors = [], [], []
        settings = store.get_settings()
        for f in files:
            fname = f.filename or "upload"
            data = await f.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                errors.append({"filename": fname, "error": "file too large"})
                continue
            sha = hashlib.sha256(data).hexdigest()
            if (existing := store.find_by_hash(sha)) is not None:
                duplicates.append({"filename": fname, "id": existing})
                continue
            try:
                act = parse_file(fname, data)
                cols = activity_to_columns(act)
                result = analyse(cols, act.sport, settings)
            except (ParseError, ValueError) as exc:
                errors.append({"filename": fname, "error": str(exc)})
                continue
            new_id = store.add(
                sha256=sha, filename=fname, source_format=act.source_format, device=act.device,
                name=act.name, sport=act.sport, summary=_stored_summary(result), points=cols,
            )
            _match_activity({"id": new_id, "sport": act.sport, "points": cols})
            imported.append({"filename": fname, "id": new_id, "name": act.name, "sport": act.sport})
        return {"imported": imported, "duplicates": duplicates, "errors": errors}

    @app.get("/api/activities")
    def list_activities(sport: str | None = None):
        return store.list(sport)

    def _get_row(activity_id: int) -> dict:
        row = store.get(activity_id)
        if not row:
            raise HTTPException(404, "activity not found")
        return row

    def _window(row: dict, start: int | None, end: int | None) -> tuple[dict, dict | None]:
        """Return (columns, window-info). Without start/end the full activity is used."""
        if start is None and end is None:
            return row["points"], None
        total = point_count(row["points"])
        try:
            cols = window_columns(row["points"], start, end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return cols, {"start": start or 0, "end": total - 1 if end is None else end, "total_points": total}

    @app.get("/api/activities/{activity_id}")
    def get_activity(activity_id: int, split: str = Query("km", pattern="^(km|mi)$"),
                     start: WindowStart = None, end: WindowEnd = None):
        """Full analysis. ``start``/``end`` give a temporary trimmed view (nothing is saved)."""
        row = _get_row(activity_id)
        cols, window = _window(row, start, end)
        result = analyse(cols, row["sport"], store.get_settings(), 1609.344 if split == "mi" else 1000.0)
        if window is None:
            result["window"] = None
        else:
            offset = window["start"]
            result["series"]["idx"] = [i + offset for i in result["series"]["idx"]]
            result["window"] = window
        det = _detect(row)
        result["laps"] = None if det is None else {k: det[k] for k in ("count", "start", "end", "lap_distance_m")}
        result["segment_efforts"] = store.efforts_for_activity(activity_id)
        meta = {k: row[k] for k in ("id", "filename", "source_format", "device", "name", "sport",
                                    "start_time", "created_at")}
        return {**meta, **result}

    @app.get("/api/activities/{activity_id}/laps")
    def get_laps(activity_id: int):
        """Detected repeating laps with per-lap summaries (404 when the track has none)."""
        row = _get_row(activity_id)
        det = _detect(row)
        if det is None:
            raise HTTPException(404, "no repeating laps detected")
        return lap_report(row["points"], row["sport"], store.get_settings(), det)

    @app.get("/api/activities/{activity_id}/export")
    def export_activity(activity_id: int, format: str = Query("gpx", pattern="^(gpx|tcx|fit)$"),
                        start: WindowStart = None, end: WindowEnd = None):
        """Download the activity (or the trimmed window) as a new GPX/TCX/FIT file."""
        row = _get_row(activity_id)
        cols, window = _window(row, start, end)
        cols = window_columns(cols) if window is None else cols  # always export cleaned points
        name = row["name"] + (" (trimmed)" if window else "")
        try:
            if format == "gpx":
                data = writers.to_gpx(cols, name, row["sport"])
            else:
                dist = cumulative_distance(cols)
                writer = writers.to_tcx if format == "tcx" else writers.to_fit
                data = writer(cols, name, row["sport"], dist)
        except writers.ExportError as exc:
            raise HTTPException(422, str(exc)) from exc
        stem = re.sub(r"[^\w\-]+", "_", name).strip("_") or "activity"
        fname = f"{stem}.{format}"
        disposition = f"attachment; filename=\"{fname.encode('ascii', 'replace').decode()}\"; " \
                      f"filename*=UTF-8''{quote(fname)}"
        return Response(data, media_type=writers.FORMATS[format],
                        headers={"Content-Disposition": disposition})

    @app.post("/api/activities/{activity_id}/clip", status_code=201)
    def clip_activity(activity_id: int, body: ClipIn):
        """Save the window ``start..end`` as a new, independent activity."""
        row = _get_row(activity_id)
        cols, window = _window(row, body.start, body.end)
        if window is None:
            raise HTTPException(422, "start or end required")
        sha = hashlib.sha256(f"clip:{row['sha256']}:{window['start']}:{window['end']}".encode()).hexdigest()
        if (existing := store.find_by_hash(sha)) is not None:
            return {"id": existing, "duplicate": True}
        try:
            result = analyse(cols, row["sport"], store.get_settings())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        name = body.name or f"{row['name']} (clip)"
        new_id = store.add(
            sha256=sha, filename=row["filename"], source_format=row["source_format"], device=row["device"],
            name=name, sport=row["sport"], summary=_stored_summary(result), points=cols,
        )
        _match_activity({"id": new_id, "sport": row["sport"], "points": cols})
        return {"id": new_id, "duplicate": False, "name": name}

    @app.patch("/api/activities/{activity_id}")
    def patch_activity(activity_id: int, patch: ActivityPatch):
        row = store.get(activity_id)
        if not row:
            raise HTTPException(404, "activity not found")
        fields = {"name": patch.name}
        if patch.sport:
            row["sport"] = normalise_sport(patch.sport)
            fields["sport"] = row["sport"]
            fields["summary"] = _stored_summary(_analyse_row(row))
        store.update(activity_id, **fields)
        if patch.sport:  # moving time depends on the sport
            _match_activity(row)
        return store.get(activity_id, with_points=False)

    @app.delete("/api/activities/{activity_id}", status_code=204)
    def delete_activity(activity_id: int):
        if not store.delete(activity_id):
            raise HTTPException(404, "activity not found")

    # ------------------------------------------------------------------ segments
    def _get_segment(segment_id: int) -> dict:
        seg = store.get_segment(segment_id)
        if not seg:
            raise HTTPException(404, "segment not found")
        return seg

    @app.post("/api/segments", status_code=201)
    def create_segment(body: SegmentIn):
        """Cut a segment from an activity (points start..end) and match it against every activity."""
        row = _get_row(body.activity_id)
        try:
            geometry = build_segment(row["points"], body.start, body.end, row["sport"])
        except (SegmentError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        seg_id = store.add_segment(name=body.name or f"{row['name']} segment", sport=row["sport"],
                                   source_activity_id=row["id"], geometry=geometry)
        _match_segment(store.get_segment(seg_id))
        return _segment_detail(seg_id)

    @app.get("/api/segments")
    def list_segments():
        return [{k: v for k, v in s.items() if k != "points"} for s in store.list_segments()]

    def _segment_detail(segment_id: int) -> dict:
        seg = _get_segment(segment_id)
        efforts = store.efforts_for_segment(segment_id)
        by_activity: dict[int, dict] = {}
        for e in efforts:  # efforts are ordered best first, so the first one per activity is its best
            a = by_activity.setdefault(e["activity_id"], {
                "activity_id": e["activity_id"], "name": e["activity_name"], "sport": e["activity_sport"],
                "start_time": e["activity_start"], "efforts": 0, "best": e})
            a["efforts"] += 1
        activities = sorted(by_activity.values(), key=lambda a: a["start_time"] or "", reverse=True)
        return {**seg, "efforts": efforts, "activities": activities}

    @app.get("/api/segments/{segment_id}")
    def get_segment(segment_id: int):
        """Segment geometry, all efforts (best time first) and the activities that contain it."""
        return _segment_detail(segment_id)

    @app.patch("/api/segments/{segment_id}")
    def rename_segment(segment_id: int, body: SegmentPatch):
        _get_segment(segment_id)
        store.rename_segment(segment_id, body.name)
        return _segment_detail(segment_id)

    @app.delete("/api/segments/{segment_id}", status_code=204)
    def delete_segment(segment_id: int):
        if not store.delete_segment(segment_id):
            raise HTTPException(404, "segment not found")

    @app.post("/api/segments/{segment_id}/rescan")
    def rescan_segment(segment_id: int):
        """Re-match the segment against every stored activity."""
        _match_segment(_get_segment(segment_id))
        return _segment_detail(segment_id)

    @app.get("/api/activities/{activity_id}/segments")
    def activity_segments(activity_id: int):
        _get_row(activity_id)
        return store.efforts_for_activity(activity_id)

    # ------------------------------------------------------------------ sports
    @app.get("/api/sports")
    def list_sports():
        """Sport catalogue for the UI: key, label, icon, family, pace, moving threshold, cadence unit."""
        return sports.catalogue()

    # ------------------------------------------------------------------ settings
    @app.get("/api/settings")
    def get_settings():
        return store.get_settings()

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        values = body.model_dump(exclude_none=True)
        settings = store.set_settings(values)
        if values:  # zones / TSS / TRIMP depend on settings -> refresh stored summaries
            for aid in store.all_ids():
                row = store.get(aid)
                store.update(aid, summary=_stored_summary(analyse(row["points"], row["sport"], settings)))
        return settings

    # ------------------------------------------------------------------ stats
    @app.get("/api/stats")
    def stats(sport: str | None = None, period: str = Query("week", pattern="^(week|month)$")):
        rows = store.list(sport)
        totals = defaultdict(float)
        buckets: dict[str, dict] = {}
        records: dict[str, dict[float, dict]] = defaultdict(dict)
        power_records: dict[int, dict] = {}
        sports = defaultdict(int)

        for r in rows:
            s = r["summary"]
            sports[r["sport"]] += 1
            totals["count"] += 1
            for key in ("distance_m", "moving_s", "elev_gain_m", "tss", "trimp"):
                totals[key] += s.get(key) or 0
            if r["start_time"]:
                start = datetime.fromisoformat(r["start_time"])
                if period == "week":
                    key = (start - timedelta(days=start.weekday())).date().isoformat()
                else:
                    key = start.strftime("%Y-%m-01")
                b = buckets.setdefault(key, {"period_start": key, "count": 0, "distance_m": 0.0,
                                             "moving_s": 0.0, "elev_gain_m": 0.0, "load": 0.0})
                b["count"] += 1
                b["distance_m"] += s.get("distance_m") or 0
                b["moving_s"] += s.get("moving_s") or 0
                b["elev_gain_m"] += s.get("elev_gain_m") or 0
                b["load"] += s.get("tss") or s.get("trimp") or 0
            for e in s.get("best_efforts") or []:
                cur = records[r["sport"]].get(e["distance_m"])
                if cur is None or e["time_s"] < cur["time_s"]:
                    records[r["sport"]][e["distance_m"]] = {
                        **e, "activity_id": r["id"], "activity_name": r["name"], "date": r["start_time"]}
            for p in s.get("power_curve") or []:
                cur = power_records.get(p["duration_s"])
                if cur is None or p["value"] > cur["value"]:
                    power_records[p["duration_s"]] = {
                        **p, "activity_id": r["id"], "activity_name": r["name"], "date": r["start_time"]}

        periods = _fill_periods(sorted(buckets.values(), key=lambda b: b["period_start"]), period)
        return {
            "totals": {k: round(v, 1) for k, v in totals.items()},
            "sports": dict(sports),
            "periods": periods,
            "records": {sp: sorted(v.values(), key=lambda e: e["distance_m"]) for sp, v in records.items()},
            "power_curve": [power_records[k] for k in sorted(power_records)],
        }

    # ------------------------------------------------------------------ frontend
    @app.middleware("http")
    async def revalidate_frontend(request, call_next):
        # Make browsers re-check (ETag) the page and its JS/CSS on every load, so a
        # new version is picked up without a hard refresh.
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


def _fill_periods(periods: list[dict], period: str) -> list[dict]:
    """Insert empty buckets so gaps in training show up as zeros, not skipped bars."""
    if len(periods) < 2:
        return periods
    by_key = {p["period_start"]: p for p in periods}
    cur = datetime.fromisoformat(periods[0]["period_start"])
    end = datetime.fromisoformat(periods[-1]["period_start"])
    out = []
    while cur <= end:
        key = cur.date().isoformat()
        out.append(by_key.get(key) or {"period_start": key, "count": 0, "distance_m": 0.0,
                                       "moving_s": 0.0, "elev_gain_m": 0.0, "load": 0.0})
        if period == "week":
            cur += timedelta(days=7)
        else:
            cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
    return out
