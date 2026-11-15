"""Small helpers shared by core and module tests."""

from __future__ import annotations

from app.analytics import activity_to_columns
from app.parsers import parse_file
from tests.samples import to_gpx


def upload(client, filename: str, data: bytes) -> int:
    """Upload one file through the API and return the new activity id."""
    res = client.post("/api/activities", files=[("files", (filename, data, "application/octet-stream"))]).json()
    return res["imported"][0]["id"]


def cols(pts: list[dict]) -> dict[str, list]:
    """Point columns for synthetic points (via a GPX round trip, like a real import)."""
    return activity_to_columns(parse_file("x.gpx", to_gpx(pts)))
