"""FastAPI application: upload, store, analyse and visualise activity files."""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analytics import activity_to_columns, analyse
from .parsers import ParseError, normalise_sport, parse_file
from .storage import Store

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class ActivityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sport: str | None = Field(default=None, min_length=1, max_length=40)


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
            imported.append({"filename": fname, "id": new_id, "name": act.name, "sport": act.sport})
        return {"imported": imported, "duplicates": duplicates, "errors": errors}

    @app.get("/api/activities")
    def list_activities(sport: str | None = None):
        return store.list(sport)

    @app.get("/api/activities/{activity_id}")
    def get_activity(activity_id: int, split: str = Query("km", pattern="^(km|mi)$")):
        row = store.get(activity_id)
        if not row:
            raise HTTPException(404, "activity not found")
        result = _analyse_row(row, 1609.344 if split == "mi" else 1000.0)
        meta = {k: row[k] for k in ("id", "filename", "source_format", "device", "name", "sport",
                                    "start_time", "created_at")}
        return {**meta, **result}

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
        return store.get(activity_id, with_points=False)

    @app.delete("/api/activities/{activity_id}", status_code=204)
    def delete_activity(activity_id: int):
        if not store.delete(activity_id):
            raise HTTPException(404, "activity not found")

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
