"""All activities map (backend): thinned GPS lines of many activities, filtered.

Endpoints (under /api/m/activity_map):
    GET /facets   sports, tags and date span present in the data (for the filter UI)
    GET /tracks   ?sports=a,b&tags=x,y&from=YYYY-MM-DD&to=YYYY-MM-DD
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Query

from app.sdk import ModuleContext

STEP_M = 25.0
MAX_POINTS = 400


def _split(value: str | None) -> set[str]:
    return {v.strip() for v in (value or "").split(",") if v.strip()}


def register(ctx: ModuleContext) -> None:
    cache: dict[int, list] = {}  # activity id -> thinned [[lat, lon], ...]; points never change
    ctx.on("activity.deleted", lambda activity_id: cache.pop(activity_id, None))

    def line(activity_id: int) -> list:
        if activity_id not in cache:
            cache[activity_id] = ctx.core.track(activity_id, step_m=STEP_M, max_points=MAX_POINTS)
        return cache[activity_id]

    @ctx.router.get("/facets")
    def facets() -> dict:
        """What can be filtered: sports (with counts), tags and the date span of GPS activities."""
        acts = [a for a in ctx.core.list_activities() if a["summary"].get("has_gps")]
        sports: dict[str, int] = {}
        for a in acts:
            sports[a["sport"]] = sports.get(a["sport"], 0) + 1
        days = sorted(a["start_time"][:10] for a in acts if a["start_time"])
        return {
            "sports": sports,
            "tags": ctx.core.tags(),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "count": len(acts),
        }

    @ctx.router.get("/tracks")
    def tracks(
        sports: str | None = None,
        tags: str | None = None,
        date_from: Annotated[date | None, Query(alias="from")] = None,
        date_to: Annotated[date | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
    ) -> dict:
        """GPS lines of the activities matching every given filter (any of the sports, any of the tags)."""
        want_sports, want_tags = _split(sports), _split(tags)
        out = []
        for a in ctx.core.list_activities():
            day = (a["start_time"] or "")[:10]
            if (want_sports and a["sport"] not in want_sports) or (want_tags and not want_tags & set(a["tags"])):
                continue
            if (date_from and (not day or day < date_from.isoformat())) or (
                date_to and (not day or day > date_to.isoformat())
            ):
                continue
            if not a["summary"].get("has_gps") or len(points := line(a["id"])) < 2:
                continue
            out.append(
                {
                    "id": a["id"],
                    "name": a["name"],
                    "sport": a["sport"],
                    "start_time": a["start_time"],
                    "distance_m": a["summary"].get("distance_m"),
                    "tags": a["tags"],
                    "track": points,
                }
            )
            if len(out) >= limit:
                break
        return {"activities": out, "count": len(out)}
