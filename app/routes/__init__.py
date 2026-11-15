"""HTTP routes of the core, one small router per area. They only translate HTTP to
``app.core.Core`` calls; all logic lives in the core service."""

from __future__ import annotations

from fastapi import Request

from ..core import Core


def get_core(request: Request) -> Core:
    return request.app.state.core
