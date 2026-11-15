"""Segments: create from an activity stretch, list, detail with leaderboard, rename, delete, rescan."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core import Core
from . import get_core

router = APIRouter(prefix="/api/segments", tags=["segments"])
CoreDep = Annotated[Core, Depends(get_core)]


class SegmentIn(BaseModel):
    activity_id: int
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class SegmentPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("", status_code=201)
def create_segment(core: CoreDep, body: SegmentIn):
    """Cut a segment from an activity (points start..end) and match it against every activity."""
    return core.create_segment(body.activity_id, body.start, body.end, body.name)


@router.get("")
def list_segments(core: CoreDep):
    return [{k: v for k, v in s.items() if k != "points"} for s in core.store.list_segments()]


@router.get("/{segment_id}")
def get_segment(core: CoreDep, segment_id: int):
    """Segment geometry, all efforts (best time first) and the activities that contain it."""
    return core.segment_detail(segment_id)


@router.patch("/{segment_id}")
def rename_segment(core: CoreDep, segment_id: int, body: SegmentPatch):
    return core.rename_segment(segment_id, body.name)


@router.delete("/{segment_id}", status_code=204)
def delete_segment(core: CoreDep, segment_id: int):
    core.delete_segment(segment_id)


@router.post("/{segment_id}/rescan")
def rescan_segment(core: CoreDep, segment_id: int):
    """Re-match the segment against every stored activity."""
    return core.rescan_segment(segment_id)
