"""Tutorial: the simulated run the in-app tour works on."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..core import Core
from . import get_core

router = APIRouter(prefix="/api/tutorial", tags=["tutorial"])
CoreDep = Annotated[Core, Depends(get_core)]


@router.get("")
def status(core: CoreDep):
    """``{activity_id | null, activities}``: is the tutorial run present?"""
    return core.tutorial_status()


@router.post("")
def start(core: CoreDep):
    """Create the tutorial run (or return the existing one): ``{activity_id, created}``."""
    return core.start_tutorial()


@router.delete("")
def end(core: CoreDep):
    """Remove the tutorial run, clips of it and segments made on them: ``{activities, segments}``."""
    return core.end_tutorial()
