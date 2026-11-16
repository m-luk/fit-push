"""OpenStreetMap places (backend): a service module, no page and no HTTP API.

Services (declared in module.json, documented in README.md "## Services"):
    place(lat, lon, refresh=False) -> {point, park, range, city, source, fetched_at}   1.0
    about() -> {sends, endpoint, rounding_decimals, min_interval_s}                     1.0
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from app.sdk import Invalid, ModuleContext

OVERPASS_URL = "https://overpass-api.de/api/interpreter"  # FITPUSH_OVERPASS_URL overrides it
DECIMALS = 3  # every point is rounded to ~100 m before it leaves the machine
MIN_INTERVAL_S = 1.0  # at most one request per second (Overpass fair use)
PARK_RADIUS_M, RANGE_RADIUS_M, TOWN_RADIUS_M = 25_000, 60_000, 30_000
PARK = "[boundary=national_park]"
PARK2 = '[boundary=protected_area][protect_class="2"]'  # IUCN category II = national park
RANGE = "[natural=mountain_range]"


def haversine(a: list[float], b: list[float]) -> float:
    """Distance in metres between two [lat, lon] points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(min(1.0, h)))


def endpoint() -> str:
    return os.environ.get("FITPUSH_OVERPASS_URL") or OVERPASS_URL


def query_for(lat: float, lon: float) -> str:
    """One Overpass request: areas containing the point, nearby parks and ranges, towns."""
    park_near, range_near = f"(around:{PARK_RADIUS_M},{lat},{lon})", f"(around:{RANGE_RADIUS_M},{lat},{lon})"
    return (
        f"[out:json][timeout:25];is_in({lat},{lon})->.a;"
        f"(area.a{PARK};area.a{PARK2};area.a{RANGE};);out tags;"
        f"(relation{park_near}{PARK};way{park_near}{PARK};relation{park_near}{PARK2};"
        f"nwr{range_near}{RANGE}[name];);out tags center;"
        f'node(around:{TOWN_RADIUS_M},{lat},{lon})[place~"^(city|town|village)$"][name];out tags;'
    )


def parse(point: list[float], elements: list[dict]) -> dict:
    """Overpass elements -> {park, range, city}: each the matching area containing the
    point, else the nearest match, as {name, inside, distance_m, kind} or None."""

    def name(e: dict) -> str:
        tags = e.get("tags") or {}
        return tags.get("name:en") or tags.get("name") or ""

    def where(e: dict) -> list[float] | None:
        c = e.get("center") or e
        return [c["lat"], c["lon"]] if "lat" in c and "lon" in c else None

    def best(kind) -> dict | None:
        found = [e for e in elements if name(e) and kind(e.get("tags") or {})]
        inside = [e for e in found if e.get("type") == "area"]
        if inside:
            return {"name": name(inside[0]), "inside": True, "distance_m": 0.0, "kind": None}
        near = [
            {
                "name": name(e),
                "inside": False,
                "distance_m": round(haversine(point, p), 1),
                "kind": e["tags"].get("place"),
            }
            for e in found
            if (p := where(e))
        ]
        return min(near, key=lambda x: x["distance_m"], default=None)

    return {
        "park": best(lambda t: t.get("boundary") == "national_park" or t.get("protect_class") == "2"),
        "range": best(lambda t: t.get("natural") == "mountain_range"),
        "city": best(lambda t: t.get("place") in ("city", "town")) or best(lambda t: t.get("place") == "village"),
    }


def register(ctx: ModuleContext) -> None:
    cache_t = ctx.db.table("cache")
    ctx.db.script(f"CREATE TABLE IF NOT EXISTS {ctx.db.table('cache')} (point TEXT PRIMARY KEY, value TEXT NOT NULL)")
    lock = threading.Lock()  # one request at a time, spaced by MIN_INTERVAL_S
    last = [0.0]

    def fetch(lat: float, lon: float) -> list[dict]:
        req = urllib.request.Request(
            endpoint(),
            data=urllib.parse.urlencode({"data": query_for(lat, lon)}).encode(),
            headers={"User-Agent": "fit-push"},
        )
        with lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except (OSError, ValueError) as exc:
                raise Invalid(f"OpenStreetMap lookup failed: {exc}") from exc
            finally:
                last[0] = time.monotonic()
        if not isinstance(data, dict) or not isinstance(data.get("elements", []), list):
            raise Invalid("OpenStreetMap lookup failed: unexpected answer")
        return data.get("elements", [])

    def place(lat: float, lon: float, refresh: bool = False) -> dict:
        """Service ``place`` 1.0: national park, mountain range and nearest city or town
        around a point (rounded to ``DECIMALS`` first). Answers are stored per rounded
        point; ``refresh`` asks again. Raises ``Invalid`` when the lookup fails."""
        try:
            point = [round(float(lat), DECIMALS), round(float(lon), DECIMALS)]
        except (TypeError, ValueError) as exc:
            raise Invalid("lat and lon must be numbers") from exc
        if not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180):
            raise Invalid("lat/lon out of range")
        key = f"{point[0]},{point[1]}"
        rows = ctx.db.query(f"SELECT value FROM {cache_t} WHERE point = ?", (key,))
        if rows and not refresh:
            return json.loads(rows[0]["value"])
        out = {
            "point": point,
            **parse(point, fetch(*point)),
            "source": "openstreetmap",
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        ctx.db.execute(f"INSERT OR REPLACE INTO {cache_t} (point, value) VALUES (?, ?)", (key, json.dumps(out)))
        return out

    def about() -> dict:
        """Service ``about`` 1.0: what a lookup sends, for consumers to show their users."""
        return {
            "sends": f"one point rounded to {DECIMALS} decimals (about 100 m) per new place",
            "endpoint": endpoint(),
            "rounding_decimals": DECIMALS,
            "min_interval_s": MIN_INTERVAL_S,
        }

    ctx.provide("place", place)
    ctx.provide("about", about)
