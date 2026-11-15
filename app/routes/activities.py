"""Activities: upload, list, analysis (incl. trimmed views), laps, export, clip, tags."""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import writers
from ..analytics import cumulative_distance, window_columns
from ..core import Core, Invalid
from . import get_core

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

router = APIRouter(prefix="/api", tags=["activities"])
CoreDep = Annotated[Core, Depends(get_core)]
WindowStart = Annotated[int | None, Query(ge=0, description="first point index (inclusive)")]
WindowEnd = Annotated[int | None, Query(ge=1, description="last point index (inclusive)")]


class ActivityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sport: str | None = Field(default=None, min_length=1, max_length=40)


class ClipIn(BaseModel):
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class TagsIn(BaseModel):
    tags: list[str] = Field(max_length=50)


@router.post("/activities")
async def upload(core: CoreDep, files: Annotated[list[UploadFile], File(...)]):
    imported, duplicates, errors = [], [], []
    for f in files:
        fname = f.filename or "upload"
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append({"filename": fname, "error": "file too large"})
            continue
        try:
            res = core.import_file(fname, data)
        except Invalid as exc:
            errors.append({"filename": fname, "error": str(exc)})
            continue
        status = res.pop("status")
        (imported if status == "imported" else duplicates).append(res)
    return {"imported": imported, "duplicates": duplicates, "errors": errors}


@router.get("/activities")
def list_activities(core: CoreDep, sport: str | None = None, tag: str | None = None):
    return core.store.list_activities(sport, tag)


@router.get("/activities/{activity_id}")
def get_activity(
    core: CoreDep,
    activity_id: int,
    split: str = Query("km", pattern="^(km|mi)$"),
    start: WindowStart = None,
    end: WindowEnd = None,
):
    """Full analysis. ``start``/``end`` give a temporary trimmed view (nothing is saved)."""
    return core.analysis(activity_id, 1609.344 if split == "mi" else 1000.0, start, end)


@router.get("/activities/{activity_id}/laps")
def get_laps(core: CoreDep, activity_id: int):
    """Detected repeating laps with per-lap summaries (404 when the track has none)."""
    return core.lap_report(activity_id)


@router.get("/activities/{activity_id}/export")
def export_activity(
    core: CoreDep,
    activity_id: int,
    format: str = Query("gpx", pattern="^(gpx|tcx|fit)$"),
    start: WindowStart = None,
    end: WindowEnd = None,
):
    """Download the activity (or the trimmed window) as a new GPX/TCX/FIT file."""
    row = core.row(activity_id)
    cols, window = core.window(row, start, end)
    cols = window_columns(cols) if window is None else cols  # always export cleaned points
    name = row["name"] + (" (trimmed)" if window else "")
    try:
        if format == "gpx":
            data = writers.to_gpx(cols, name, row["sport"])
        else:
            writer = writers.to_tcx if format == "tcx" else writers.to_fit
            data = writer(cols, name, row["sport"], cumulative_distance(cols))
    except writers.ExportError as exc:
        raise Invalid(str(exc)) from exc
    stem = re.sub(r"[^\w\-]+", "_", name).strip("_") or "activity"
    fname = f"{stem}.{format}"
    disposition = (
        f"attachment; filename=\"{fname.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{quote(fname)}"
    )
    return Response(data, media_type=writers.FORMATS[format], headers={"Content-Disposition": disposition})


@router.post("/activities/{activity_id}/clip", status_code=201)
def clip_activity(core: CoreDep, activity_id: int, body: ClipIn):
    """Save the window ``start..end`` as a new, independent activity."""
    return core.clip(activity_id, body.start, body.end, body.name)


@router.patch("/activities/{activity_id}")
def patch_activity(core: CoreDep, activity_id: int, patch: ActivityPatch):
    return core.update_activity(activity_id, patch.name, patch.sport)


@router.put("/activities/{activity_id}/tags")
def put_tags(core: CoreDep, activity_id: int, body: TagsIn):
    """Replace the activity's tags; returns the normalised list."""
    return {"tags": core.set_tags(activity_id, body.tags)}


@router.get("/tags")
def list_tags(core: CoreDep):
    """All tags with the number of activities carrying each."""
    return core.store.all_tags()


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(core: CoreDep, activity_id: int):
    core.delete_activity(activity_id)


@router.get("/activities/{activity_id}/segments")
def activity_segments(core: CoreDep, activity_id: int):
    core.row(activity_id, with_points=False)
    return core.store.efforts_for_activity(activity_id)
