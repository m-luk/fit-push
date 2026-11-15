"""Segments: a stretch of track (start -> end) that efforts on any activity are matched to.

A segment is cut from one activity's GPS track. Another activity has an *effort*
on it when it passes near the segment start, later near the segment end, covers
a similar distance in between, and stays on the segment's line the whole way
(checked both ways: the effort follows the segment and the segment is covered by
the effort, so shortcuts and detours don't count). One activity can have several
efforts on the same segment, e.g. one per lap.

Indices refer to the cleaned point sequence (see ``analytics.window_columns``).
"""
from __future__ import annotations

import numpy as np

from .analytics import _prepare, analyse, window_columns

EARTH_R = 6_371_000.0
ENDPOINT_RADIUS = 25.0      # how close an effort must pass the segment start / end (m)
CORRIDOR = 30.0             # 95 % of points must stay within this of the other line (m)
LENGTH_RANGE = (0.8, 1.25)  # effort GPS length vs segment GPS length
MIN_SEGMENT_M = 100.0
GEOMETRY_STEP_M = 5.0       # stored segment line: a point every ~5 m ...
MAX_SEGMENT_POINTS = 20_000 # ... up to 100 km
COMPARE_STEP_M = 10.0       # both lines are compared at this spacing, whatever their length


class SegmentError(ValueError):
    pass


def _xy(lat, lon, lat0, lon0):
    x = np.radians(np.asarray(lon) - lon0) * EARTH_R * np.cos(np.radians(lat0))
    y = np.radians(np.asarray(lat) - lat0) * EARTH_R
    return x, y


def _path_len(x, y) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])


def _resample(x, y, step=COMPARE_STEP_M):
    """Points every ``step`` metres along the line (at least 2)."""
    d = _path_len(x, y)
    g = np.linspace(0, d[-1], max(2, int(d[-1] / step) + 1))
    return np.interp(g, d, x), np.interp(g, d, y)


def _near_fraction(ax, ay, bx, by, radius) -> float:
    """Share of A's points that have a B point within ``radius`` (spatial grid, any length)."""
    cell = radius
    grid: dict[tuple[int, int], list[int]] = {}
    for k, key in enumerate(zip(np.floor(bx / cell).astype(int), np.floor(by / cell).astype(int))):
        grid.setdefault(key, []).append(k)
    near = 0
    for px, py in zip(ax, ay):
        cx, cy = int(np.floor(px / cell)), int(np.floor(py / cell))
        cand = [k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in grid.get((cx + dx, cy + dy), ())]
        if cand and np.min(np.hypot(bx[cand] - px, by[cand] - py)) <= radius:
            near += 1
    return near / len(ax)


def build_segment(cols: dict[str, list], start: int, end: int, sport: str = "unknown") -> dict:
    """Geometry and reference stats for the segment cut from points ``start..end``."""
    w = window_columns(cols, start, end)
    lat, lon = np.array(w["lat"], dtype=float), np.array(w["lon"], dtype=float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    if ok.sum() < 5:
        raise SegmentError("the selection has no GPS track")
    lat, lon = lat[ok], lon[ok]
    lat0, lon0 = float(lat.mean()), float(lon.mean())
    x, y = _xy(lat, lon, lat0, lon0)
    length = float(_path_len(x, y)[-1])
    if length < MIN_SEGMENT_M:
        raise SegmentError(f"a segment must be at least {MIN_SEGMENT_M:.0f} m long")
    # A point about every 5 m: dense enough that matching never sees gaps.
    n = int(min(MAX_SEGMENT_POINTS, max(20, length / GEOMETRY_STEP_M)))
    d = _path_len(x, y)
    g = np.linspace(0, d[-1], n)
    plat, plon = np.interp(g, d, lat), np.interp(g, d, lon)
    summary = analyse(w, sport)["summary"]
    return {
        "points": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(plat, plon)],
        "gps_length_m": round(length, 1),
        "distance_m": summary["distance_m"],
        "elev_gain_m": summary["elev_gain_m"],
        "bbox": [float(plat.min()), float(plon.min()), float(plat.max()), float(plon.max())],
    }


def _near_runs(dd: np.ndarray, radius: float) -> list[int]:
    """Closest point of every contiguous run of points within ``radius``."""
    inside = dd < radius
    if not inside.any():
        return []
    edges = np.diff(np.concatenate([[0], inside.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [int(s + np.argmin(dd[s:e])) for s, e in zip(starts, ends)]


def _bbox_overlaps(seg_bbox, lat, lon, margin_deg=0.001) -> bool:
    return not (np.nanmax(lat) < seg_bbox[0] - margin_deg or np.nanmin(lat) > seg_bbox[2] + margin_deg
                or np.nanmax(lon) < seg_bbox[1] - margin_deg or np.nanmin(lon) > seg_bbox[3] + margin_deg)


def find_efforts(segment: dict, cols: dict[str, list]) -> list[tuple[int, int]]:
    """All non-overlapping (start, end) point-index pairs where the activity rides the segment."""
    a = _prepare(cols)
    gps = np.flatnonzero(np.isfinite(a["lat"]) & np.isfinite(a["lon"]))
    if len(gps) < 5:
        return []
    lat, lon = a["lat"][gps], a["lon"][gps]
    if not _bbox_overlaps(segment["bbox"], lat, lon):
        return []

    pts = np.asarray(segment["points"], dtype=float)
    lat0, lon0 = float(pts[:, 0].mean()), float(pts[:, 1].mean())
    sx, sy = _xy(pts[:, 0], pts[:, 1], lat0, lon0)
    x, y = _xy(lat, lon, lat0, lon0)
    d = _path_len(x, y)
    seg_len = float(segment["gps_length_m"])
    rsx, rsy = _resample(sx, sy)

    starts = _near_runs(np.hypot(x - sx[0], y - sy[0]), ENDPOINT_RADIUS)
    ends = _near_runs(np.hypot(x - sx[-1], y - sy[-1]), ENDPOINT_RADIUS)
    efforts, busy_end = [], None
    for i in starts:
        # Efforts don't overlap, except around a shared gate: on a loop segment one lap
        # ends where the next starts, and the two closest points may differ slightly.
        if busy_end is not None and d[i] < d[busy_end] - 2 * ENDPOINT_RADIUS:
            continue
        for j in ends:
            if j <= i:
                continue
            ratio = (d[j] - d[i]) / seg_len
            if ratio < LENGTH_RANGE[0]:
                continue
            if ratio > LENGTH_RANGE[1]:
                break
            if _follows(x[i:j + 1], y[i:j + 1], rsx, rsy):
                efforts.append((int(gps[i]), int(gps[j])))
                busy_end = j
                break
    return efforts


def _follows(ex, ey, sx, sy) -> bool:
    """Both lines stay within CORRIDOR of each other (95th percentile, both directions)."""
    if len(ex) < 2:
        return False
    rx, ry = _resample(ex, ey)
    return (_near_fraction(rx, ry, sx, sy, CORRIDOR) >= 0.95
            and _near_fraction(sx, sy, rx, ry, CORRIDOR) >= 0.95)


EFFORT_FIELDS = ("start_time", "elapsed_s", "moving_s", "distance_m", "avg_speed_ms",
                 "avg_hr", "max_hr", "avg_power", "avg_cadence", "elev_gain_m")


def effort_stats(cols: dict[str, list], start: int, end: int, sport: str) -> dict:
    s = analyse(window_columns(cols, start, end), sport)["summary"]
    out = {k: s.get(k) for k in EFFORT_FIELDS}
    # Segment times are clock times (like a stopwatch from start to end line).
    t, dist = out["elapsed_s"], out["distance_m"]
    out["speed_ms"] = round(dist / t, 3) if t and dist else None
    return out
