"""Uphill / downhill legs of skiing activities.

Ski touring alternates climbs (skins on) and descents; resort skiing alternates lift
rides and runs. Both come out of the same detection: the smoothed elevation profile is
cut at its turning points (a zigzag with a minimum swing, so GPS/barometer noise and
short rises inside a run don't split it), and every leg is trimmed at both ends where
the elevation barely changes (a summit break, a lift queue). What is left between
legs is a transition (resort: waiting at the lift or a break).

In resort skiing every climb counts as a lift ride: nobody skins up a piste.

All indices refer to the cleaned point sequence of the analysed columns (see
``analytics.window_columns``); ``Core.analysis`` shifts them for trimmed views.
"""

from __future__ import annotations

import itertools

import numpy as np

from . import sports
from .analytics import CHANNELS, _centered_median, _interp_nans, _prepare, _to_lists, analyse

MIN_SWING_M = 30.0  # smaller rises and drops stay part of the surrounding leg
FLAT_TOL_M = 4.0  # leg ends closer than this to the leg's start/end elevation are trimmed
MIN_LEG_S = 30.0  # shorter legs are noise (a tunnel, a fix jump)

LEG_FIELDS = (
    "elapsed_s",
    "moving_s",
    "distance_m",
    "avg_speed_ms",
    "max_speed_ms",
    "elev_gain_m",
    "elev_loss_m",
    "avg_hr",
    "max_hr",
    "avg_power",
    "avg_cadence",
)


def mode(sport: str) -> str | None:
    """``"touring"``, ``"resort"`` or ``None`` when the sport has no uphill/downhill legs."""
    if sport == "ski_touring":
        return "touring"
    if sports.get(sport).family == "skiing":
        return "resort"
    return None


def _turning_points(e: np.ndarray, swing: float) -> list[int]:
    """Indices of alternating extrema that differ by at least ``swing`` (zigzag)."""
    lo = hi = 0
    direction, ext = 0, 0
    pivots: list[int] = []
    for k in range(1, len(e)):
        v = e[k]
        if direction == 0:
            if v > e[hi]:
                hi = k
            if v < e[lo]:
                lo = k
            if e[hi] - e[lo] >= swing:
                if hi > lo:
                    pivots, direction, ext = [lo], 1, hi
                else:
                    pivots, direction, ext = [hi], -1, lo
        elif direction == 1:
            if v > e[ext]:
                ext = k
            elif e[ext] - v >= swing:
                pivots.append(ext)
                direction, ext = -1, k
        else:
            if v < e[ext]:
                ext = k
            elif v - e[ext] >= swing:
                pivots.append(ext)
                direction, ext = 1, k
    if direction != 0:
        pivots.append(ext)
    return pivots


def _trim(e: np.ndarray, i: int, j: int, up: bool) -> tuple[int, int]:
    """Drop the flat ends of leg ``i..j``: start when the climb/drop really starts, end when it stops."""
    seg = e[i : j + 1]
    if up:
        start = i + int(np.flatnonzero(seg <= e[i] + FLAT_TOL_M)[-1])
        end = i + int(np.flatnonzero(seg >= e[j] - FLAT_TOL_M)[0])
    else:
        start = i + int(np.flatnonzero(seg >= e[i] - FLAT_TOL_M)[-1])
        end = i + int(np.flatnonzero(seg <= e[j] + FLAT_TOL_M)[0])
    if end <= start:
        return i, j
    return start, end


def _num(x, nd=1):
    return None if x is None else round(float(x), nd)


def detect(cols: dict[str, list], sport: str, settings: dict | None = None) -> dict | None:
    """Uphill/downhill legs with per-leg stats and totals; ``None`` if not a ski activity or no legs."""
    kind = mode(sport)
    if kind is None:
        return None
    a = _prepare(cols)
    n = len(a["t"])
    if not a["has_time"] or np.isfinite(a["ele"]).sum() < max(10, 0.5 * n):
        return None
    e = _centered_median(_interp_nans(a["ele"]), 5)
    t = a["t"]
    pivots = _turning_points(e, MIN_SWING_M)
    if len(pivots) < 2:
        return None

    up_name, down_name = ("climb", "descent") if kind == "touring" else ("lift", "run")
    legs: list[dict] = []
    for i, j in itertools.pairwise(pivots):
        up = bool(e[j] > e[i])
        s, f = _trim(e, i, j, up)
        if t[f] - t[s] < MIN_LEG_S:
            continue
        sub = {c: a[c][s : f + 1] for c in CHANNELS}
        summ = analyse(_to_lists(sub), sport, settings)["summary"]
        vertical = float(abs(e[f] - e[s]))
        elapsed = float(t[f] - t[s])
        d = summ.get("distance_m")
        leg: dict = {
            "type": "up" if up else "down",
            "name": up_name if up else down_name,
            "start": int(s),
            "end": int(f),
            "start_offset_s": _num(t[s] - t[0], 0),
            "ele_start_m": _num(e[s]),
            "ele_end_m": _num(e[f]),
            "vertical_m": _num(vertical),
            "vertical_rate_mh": _num(vertical / elapsed * 3600, 0) if elapsed > 0 else None,
            **{k: summ.get(k) for k in LEG_FIELDS},
            "avg_grade_pct": _num(vertical / float(d) * 100) if d else None,
        }
        legs.append(leg)
    if not legs:
        return None
    counts = {"up": 0, "down": 0}
    for leg in legs:
        counts[leg["type"]] += 1
        leg["index"] = counts[leg["type"]]

    def totals(kind_: str) -> dict:
        ls = [lg for lg in legs if lg["type"] == kind_]
        elapsed = sum(lg["elapsed_s"] or 0 for lg in ls)
        moving = sum(lg["moving_s"] or 0 for lg in ls)
        dist = sum(lg["distance_m"] or 0 for lg in ls)
        vert = sum(lg["vertical_m"] or 0 for lg in ls)

        def wavg(k):
            pairs = [(lg[k], lg["elapsed_s"] or 0) for lg in ls if lg[k] is not None]
            w = sum(p[1] for p in pairs)
            return _num(sum(v * wt for v, wt in pairs) / w, 0) if w else None

        longest = max(ls, key=lambda lg: lg["distance_m"] or 0, default=None)
        return {
            "count": len(ls),
            "elapsed_s": _num(elapsed, 0),
            "moving_s": _num(moving, 0),
            "distance_m": _num(dist),
            "vertical_m": _num(vert),
            "avg_speed_ms": _num(dist / moving, 3) if moving else None,
            "max_speed_ms": max((lg["max_speed_ms"] for lg in ls if lg["max_speed_ms"] is not None), default=None),
            "vertical_rate_mh": _num(vert / elapsed * 3600, 0) if elapsed else None,
            "avg_hr": wavg("avg_hr"),
            "max_hr": max((lg["max_hr"] for lg in ls if lg["max_hr"] is not None), default=None),
            "longest_index": longest["index"] if longest else None,
            "longest_m": longest["distance_m"] if longest else None,
            "max_vertical_m": max((lg["vertical_m"] or 0 for lg in ls), default=None) if ls else None,
        }

    total_s = float(t[-1] - t[0])
    up_t, down_t = totals("up"), totals("down")
    return {
        "mode": kind,
        "labels": {"up": up_name, "down": down_name},
        "legs": legs,
        "up": up_t,
        "down": down_t,
        "other_s": _num(max(0.0, total_s - (up_t["elapsed_s"] or 0) - (down_t["elapsed_s"] or 0)), 0),
    }
