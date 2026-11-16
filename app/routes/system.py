"""Settings, sport catalogue and cross-activity statistics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import __version__, paths
from ..core import Core
from . import get_core

router = APIRouter(prefix="/api", tags=["system"])
CoreDep = Annotated[Core, Depends(get_core)]


class SettingsIn(BaseModel):
    max_hr: int | None = Field(default=None, ge=100, le=250)
    rest_hr: int | None = Field(default=None, ge=25, le=120)
    ftp: int | None = Field(default=None, ge=50, le=600)


Key = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]


class PreferencesIn(BaseModel):
    map_overlay: Key | None = None
    map_palette: Key | None = None
    map_reverse: bool | None = None
    tiles: dict[Key, Annotated[list[Key], Field(max_length=60)] | None] | None = Field(default=None, max_length=100)


@router.get("/version")
def version():
    """Identifies a running fit-push (the desktop launcher uses it to find an open instance)."""
    return {"app": "fit-push", "version": __version__, "instance": paths.instance()}


@router.get("/sports")
def list_sports(core: CoreDep):
    """Sport catalogue for the UI: key, label, icon, family, pace, moving threshold, cadence unit."""
    return core.sports()


@router.get("/settings")
def get_settings(core: CoreDep):
    return core.settings()


@router.put("/settings")
def put_settings(core: CoreDep, body: SettingsIn):
    """Save athlete settings; stored summaries are recalculated."""
    return core.update_settings(body.model_dump(exclude_none=True))


@router.get("/preferences")
def get_preferences(core: CoreDep):
    return core.preferences()


@router.put("/preferences")
def put_preferences(core: CoreDep, body: PreferencesIn):
    """Display defaults (map colouring, tiles per sport); ``tiles: {sport: null}`` restores a sport's defaults."""
    return core.update_preferences(body.model_dump(exclude_unset=True, exclude_none=False))


@router.get("/stats")
def stats(core: CoreDep, sport: str | None = None, period: str = Query("week", pattern="^(week|month)$")):
    """Totals, gap-filled weekly/monthly periods, per-sport records and the all-time power curve."""
    rows = core.store.list_activities(sport)
    totals: dict[str, float] = defaultdict(float)
    buckets: dict[str, dict] = {}
    records: dict[str, dict[float, dict]] = defaultdict(dict)
    power_records: dict[int, dict] = {}
    by_sport: dict[str, int] = defaultdict(int)

    for r in rows:
        s = r["summary"]
        by_sport[r["sport"]] += 1
        totals["count"] += 1
        for key in ("distance_m", "moving_s", "elev_gain_m", "tss", "trimp"):
            totals[key] += s.get(key) or 0
        if r["start_time"]:
            start = datetime.fromisoformat(r["start_time"])
            key = (
                (start - timedelta(days=start.weekday())).date().isoformat()
                if period == "week"
                else start.strftime("%Y-%m-01")
            )
            b = buckets.setdefault(key, _empty_period(key))
            b["count"] += 1
            b["distance_m"] += s.get("distance_m") or 0
            b["moving_s"] += s.get("moving_s") or 0
            b["elev_gain_m"] += s.get("elev_gain_m") or 0
            b["load"] += s.get("tss") or s.get("trimp") or 0
        ref = {"activity_id": r["id"], "activity_name": r["name"], "date": r["start_time"]}
        for e in s.get("best_efforts") or []:
            cur = records[r["sport"]].get(e["distance_m"])
            if cur is None or e["time_s"] < cur["time_s"]:
                records[r["sport"]][e["distance_m"]] = {**e, **ref}
        for p in s.get("power_curve") or []:
            cur = power_records.get(p["duration_s"])
            if cur is None or p["value"] > cur["value"]:
                power_records[p["duration_s"]] = {**p, **ref}

    periods = fill_periods(sorted(buckets.values(), key=lambda b: b["period_start"]), period)
    return {
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "sports": dict(by_sport),
        "periods": periods,
        "records": {sp: sorted(v.values(), key=lambda e: e["distance_m"]) for sp, v in records.items()},
        "power_curve": [power_records[k] for k in sorted(power_records)],
    }


def _empty_period(key: str) -> dict:
    return {"period_start": key, "count": 0, "distance_m": 0.0, "moving_s": 0.0, "elev_gain_m": 0.0, "load": 0.0}


def fill_periods(periods: list[dict], period: str) -> list[dict]:
    """Insert empty buckets so gaps in training show up as zeros, not skipped bars."""
    if len(periods) < 2:
        return periods
    by_key = {p["period_start"]: p for p in periods}
    cur = datetime.fromisoformat(periods[0]["period_start"])
    end = datetime.fromisoformat(periods[-1]["period_start"])
    out = []
    while cur <= end:
        key = cur.date().isoformat()
        out.append(by_key.get(key) or _empty_period(key))
        cur = cur + timedelta(days=7) if period == "week" else (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
    return out
