"""Detect repeating laps in a GPS track.

Idea: a lap course has a spot the athlete passes again and again, always in the
same direction and after roughly the same distance. We try a set of candidate
"gates" along the track, find every pass through each gate, and keep the gate
that explains the longest run of consecutive laps whose lengths *and* shapes
agree. Warm-up before the first pass and cool-down after the last are left out.

All indices refer to the cleaned point sequence (see ``analytics.window_columns``).
"""
from __future__ import annotations

import numpy as np

from .analytics import _distance, _prepare, analyse, window_columns

MIN_LAP_M = 150.0          # shorter "laps" are GPS jitter around the gate
MIN_LAPS = 2
LENGTH_TOLERANCE = 0.12    # each lap within ±12 % of the median lap length
CANDIDATES = 240
SHAPE_SAMPLES = 48
MAX_GRID = 20_000


def _project(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat0 = np.radians(np.nanmean(lat))
    x = np.radians(lon - np.nanmean(lon)) * 6_371_000 * np.cos(lat0)
    y = np.radians(lat - np.nanmean(lat)) * 6_371_000
    return x, y


def _passes(dd: np.ndarray, g: np.ndarray, radius: float) -> np.ndarray:
    """Grid positions where the track is closest to the gate, one per visit."""
    inside = dd < radius
    if not inside.any():
        return np.empty(0, dtype=int)
    edges = np.diff(np.concatenate([[0], inside.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    passes: list[int] = []
    for s, e in zip(starts, ends):
        k = s + int(np.argmin(dd[s:e]))
        if passes and g[k] - g[passes[-1]] < MIN_LAP_M:
            if dd[k] < dd[passes[-1]]:  # same visit (GPS wobble): keep the closer point
                passes[-1] = k
            continue
        passes.append(k)
    return np.asarray(passes, dtype=int)


def _longest_run(ok: np.ndarray) -> tuple[int, int]:
    """[start, end) of the longest run of True values."""
    best, cur_start, best_rng = 0, None, (0, 0)
    for i, v in enumerate(list(ok) + [False]):
        if v and cur_start is None:
            cur_start = i
        elif not v and cur_start is not None:
            if i - cur_start > best:
                best, best_rng = i - cur_start, (cur_start, i)
            cur_start = None
    return best_rng


def _evaluate(passes, g, xs, ys, heading_step):
    """Return (lap pass positions, length CV) for the best consistent lap run, or None."""
    if len(passes) < MIN_LAPS + 1:
        return None
    # Direction through the gate must agree, otherwise out-and-back passes mix in.
    n = len(xs)
    hx = xs[np.minimum(passes + heading_step, n - 1)] - xs[np.maximum(passes - heading_step, 0)]
    hy = ys[np.minimum(passes + heading_step, n - 1)] - ys[np.maximum(passes - heading_step, 0)]
    ang = np.arctan2(hy, hx)
    ref = np.angle(np.mean(np.exp(1j * ang)))
    same_dir = np.cos(ang - ref) > 0.5
    passes = passes[same_dir]
    if len(passes) < MIN_LAPS + 1:
        return None

    lengths = np.diff(g[passes])
    med = np.median(lengths)
    if med < MIN_LAP_M:
        return None
    ok = np.abs(lengths - med) <= LENGTH_TOLERANCE * med

    # Shape check: resample every lap by fraction of its length and compare to the median lap.
    frac = np.linspace(0, 1, SHAPE_SAMPLES)
    shapes = np.stack([
        np.stack([np.interp(g[a] + frac * (g[b] - g[a]), g, xs),
                  np.interp(g[a] + frac * (g[b] - g[a]), g, ys)], axis=1)
        for a, b in zip(passes[:-1], passes[1:])
    ])
    if ok.sum() >= MIN_LAPS:
        ref_shape = np.median(shapes[ok], axis=0)
        dev = np.mean(np.hypot(*(shapes - ref_shape).transpose(2, 0, 1)), axis=1)
        ok &= dev <= max(15.0, 0.04 * med)

    lo, hi = _longest_run(ok)
    if hi - lo < MIN_LAPS:
        return None
    laps = passes[lo:hi + 1]
    run = lengths[lo:hi]
    return laps, float(np.std(run) / np.mean(run))


def detect_laps(cols: dict[str, list]) -> dict | None:
    """Find repeating laps. Returns ``None`` unless the track obviously repeats."""
    a = _prepare(cols)
    gps = np.flatnonzero(np.isfinite(a["lat"]) & np.isfinite(a["lon"]))
    if len(gps) < 50:
        return None
    x, y = _project(a["lat"][gps], a["lon"][gps])
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    total = d[-1]
    if total < MIN_LAP_M * (MIN_LAPS + 0.5):
        return None

    step = max(3.0, total / MAX_GRID)
    g = np.arange(0.0, total, step)
    xs, ys = np.interp(g, d, x), np.interp(g, d, y)
    radius = max(20.0, 1.5 * step)
    heading_step = max(1, int(round(15.0 / step)))

    best = None  # (n_laps, -first_pass, -cv) -> laps
    for c in np.linspace(0, len(g) - 1, min(CANDIDATES, len(g))).astype(int):
        dd = np.hypot(xs - xs[c], ys - ys[c])
        res = _evaluate(_passes(dd, g, radius), g, xs, ys, heading_step)
        if res is None:
            continue
        laps, cv = res
        # More laps wins; then a gate every lap really runs through (not one just off the
        # course, e.g. on the approach road); then the earliest-reached gate (the natural
        # lap start); then the most even laps.
        tight = bool(np.median(dd[laps]) <= max(8.0, 0.4 * radius))
        key = (len(laps) - 1, tight, -round(g[laps[0]] / 50), -cv)
        if best is None or key > best[0]:
            best = (key, laps)
    if best is None:
        return None

    laps = best[1]
    # Grid position -> nearest original point index.
    pidx = gps[np.clip(np.searchsorted(d, g[laps]), 0, len(gps) - 1)]
    pidx = np.maximum.accumulate(pidx)
    lap_list = [
        {"index": i + 1, "start": int(s), "end": int(e)}
        for i, (s, e) in enumerate(zip(pidx[:-1], pidx[1:])) if e > s
    ]
    if len(lap_list) < MIN_LAPS:
        return None
    gate = gps[np.clip(np.searchsorted(d, g[laps[0]]), 0, len(gps) - 1)]
    # Report lengths with the same distance source as the analytics (device distance
    # when present); raw GPS path length is inflated by jitter.
    dist, _ = _distance(a, True)
    return {
        "count": len(lap_list),
        "start": lap_list[0]["start"],
        "end": lap_list[-1]["end"],
        "lap_distance_m": round(float(np.median([dist[l["end"]] - dist[l["start"]] for l in lap_list])), 1),
        "gate": [round(float(a["lat"][gate]), 6), round(float(a["lon"][gate]), 6)],
        "laps": lap_list,
    }


LAP_FIELDS = ("start_time", "distance_m", "elapsed_s", "moving_s", "avg_speed_ms", "max_speed_ms",
              "elev_gain_m", "elev_loss_m", "avg_hr", "max_hr", "avg_cadence", "avg_power",
              "max_power", "normalized_power", "avg_temp_c")


def _brief(summary: dict) -> dict:
    out = {k: summary.get(k) for k in LAP_FIELDS}
    # Lap speed is distance over the lap's clock time, as on a stopwatch.
    t, d = out["elapsed_s"], out["distance_m"]
    out["lap_speed_ms"] = round(d / t, 3) if t and d else None
    return out


def lap_report(cols: dict[str, list], sport: str, settings: dict, detection: dict) -> dict:
    """Per-lap summaries plus summaries of the whole activity and of the lapped section."""
    laps = []
    for lap in detection["laps"]:
        s = analyse(window_columns(cols, lap["start"], lap["end"]), sport, settings)["summary"]
        laps.append({**lap, **_brief(s)})
    section = analyse(window_columns(cols, detection["start"], detection["end"]), sport, settings)["summary"]
    whole = analyse(cols, sport, settings)["summary"]

    times = np.array([l["elapsed_s"] or np.nan for l in laps], dtype=float)
    stats = None
    if np.isfinite(times).any():
        mean = float(np.nanmean(times))
        for l, t in zip(laps, times):
            l["delta_s"] = round(float(t - mean), 1) if np.isfinite(t) else None
        stats = {
            "mean_s": round(mean, 1),
            "best_index": int(np.nanargmin(times)) + 1,
            "worst_index": int(np.nanargmax(times)) + 1,
            "stdev_s": round(float(np.nanstd(times)), 1),
            "cv_pct": round(float(np.nanstd(times) / mean * 100), 1) if mean else None,
        }
    return {
        **{k: detection[k] for k in ("count", "start", "end", "lap_distance_m", "gate")},
        "laps": laps,
        "lap_time_stats": stats,
        "whole": _brief(whole),
        "section": _brief(section),
    }
