"""Analytics over parsed activities.

Points are stored column-wise (``{"t": [...], "lat": [...], ...}``) with
``None`` for missing samples; ``t`` is UNIX epoch seconds.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from . import sports
from .parsers import Activity

CHANNELS = ("t", "lat", "lon", "ele", "hr", "cad", "power", "speed", "temp", "dist")

DEFAULT_SETTINGS = {"max_hr": 190, "rest_hr": 60, "ftp": 250}

POWER_CURVE_DURATIONS = [5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600]
HR_ZONE_BOUNDS = [0.6, 0.7, 0.8, 0.9]  # fraction of max HR; 5 zones
EARTH_R = 6371008.8
MAX_SERIES_POINTS = 1500
MAX_TRACK_POINTS = 2500
# Bump when the stored summary of an unchanged activity would come out differently; the
# core then recomputes stored summaries once on start (Core.refresh_stale_summaries).
ANALYSIS_VERSION = 2


# --------------------------------------------------------------------------- conversion


def activity_to_columns(act: Activity) -> dict[str, list]:
    cols: dict[str, list] = {c: [] for c in CHANNELS}
    for p in act.points:
        for c in CHANNELS:
            v = getattr(p, c)
            if c == "t" and v is not None:
                v = v.timestamp()
            cols[c].append(v)
    return cols


def _arr(values) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def _num(x, nd=1):
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return round(x, nd)


def _wmean(values: np.ndarray, weights: np.ndarray, *, skip_zero=False):
    mask = np.isfinite(values) & (weights > 0)
    if skip_zero:
        mask &= values > 0
    if not mask.any():
        return None
    return float(np.average(values[mask], weights=weights[mask]))


def _nanmax(values: np.ndarray):
    return float(np.nanmax(values)) if np.isfinite(values).any() else None


def _ffill(a: np.ndarray) -> np.ndarray:
    """Forward fill NaNs (leading NaNs back-filled)."""
    a = a.copy()
    ok = np.isfinite(a)
    if not ok.any():
        return a
    idx = np.where(ok, np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    a = a[idx]
    first = np.argmax(ok)
    a[:first] = a[first]
    return a


def _interp_nans(a: np.ndarray) -> np.ndarray:
    ok = np.isfinite(a)
    if ok.all() or not ok.any():
        return a
    x = np.arange(len(a))
    out = a.copy()
    out[~ok] = np.interp(x[~ok], x[ok], a[ok])
    return out


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _rolling_mean(a: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(a) < window:
        return a
    cs = np.cumsum(np.insert(a, 0, 0.0))
    out = (cs[window:] - cs[:-window]) / window
    pad = np.full(window - 1, out[0])
    return np.concatenate([pad, out])


def _centered_median(a: np.ndarray, window: int = 5) -> np.ndarray:
    if len(a) < window:
        return a
    half = window // 2
    padded = np.pad(a, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(view, axis=1)


def _nan_median(a: np.ndarray, window: int = 5) -> np.ndarray:
    """Centered median ignoring NaNs; near the ends it uses the points that exist (no edge
    padding, so a bad first or last value is not repeated into its own window)."""
    if len(a) < 2:
        return a
    half = window // 2
    padded = np.pad(a.astype(float), half, mode="constant", constant_values=np.nan)
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    out = np.full(len(a), np.nan)
    ok = np.isfinite(view).any(axis=1)
    out[ok] = np.nanmedian(view[ok], axis=1)
    return out


# --------------------------------------------------------------------------- preparation


def _prepare(cols: dict[str, list]) -> dict[str, Any]:
    a: dict[str, Any] = {c: _arr(cols.get(c, [])) for c in CHANNELS}
    n = len(a["t"])
    for c in CHANNELS:
        if len(a[c]) != n:
            a[c] = np.full(n, np.nan)

    # Keep only timed points when most points have timestamps; sort & dedupe.
    timed = np.isfinite(a["t"])
    if timed.sum() >= max(2, 0.5 * n):
        order = np.argsort(a["t"][timed], kind="stable")
        for c in CHANNELS:
            a[c] = a[c][timed][order]
        keep = np.concatenate([[True], np.diff(a["t"]) > 0])
        for c in CHANNELS:
            a[c] = a[c][keep]
        a["has_time"] = True
    else:
        a["has_time"] = False
    return a


def _to_lists(a: dict[str, np.ndarray]) -> dict[str, list]:
    return {c: [float(v) if math.isfinite(v) else None for v in a[c]] for c in CHANNELS}


def point_count(cols: dict[str, list]) -> int:
    """Number of points after cleaning (the index space used by windows)."""
    return len(_prepare(cols)["t"])


def window_columns(cols: dict[str, list], start: int | None = None, end: int | None = None) -> dict[str, list]:
    """Clean (sort/dedupe) the columns and keep points ``start..end`` inclusive.

    Indices refer to the cleaned point sequence, i.e. the ``series.idx`` values
    returned by :func:`analyse`.
    """
    a = _prepare(cols)
    n = len(a["t"])
    start = 0 if start is None else start
    end = n - 1 if end is None else end
    if not (0 <= start < end < n):
        raise ValueError(f"invalid window {start}..{end} for {n} points")
    return _to_lists({c: a[c][start : end + 1] for c in CHANNELS})


def cumulative_distance(cols: dict[str, list]) -> list[float]:
    """Cumulative distance (m) per cleaned point, using the same source as analytics."""
    a = _prepare(cols)
    has_gps = bool((np.isfinite(a["lat"]) & np.isfinite(a["lon"])).sum() >= 2)
    dist, _ = _distance(a, has_gps)
    return [float(d) for d in dist]


def _bridge_gps_gaps(a, d: np.ndarray) -> np.ndarray:
    """Spread the distance covered during a GPS gap evenly over the gap's duration.

    While a device has no position fix (tunnel, underpass, watch under a sleeve) its
    distance freezes; when the fix comes back the whole gap's distance arrives in one
    step, which reads as an absurd speed (and a fake best effort, and lost moving time).
    Points without a position between two points with one get the distance interpolated
    by time between those two. Totals and every point with a fix are unchanged.
    """
    fix = np.isfinite(a["lat"]) & np.isfinite(a["lon"])
    vi = np.flatnonzero(fix)
    if len(vi) < 2 or vi[-1] - vi[0] + 1 == len(vi):
        return d  # no position at all, or no gap between the first and last fix
    x = a["t"] if a["has_time"] else np.arange(len(d), dtype=float)
    inside = np.zeros(len(d), dtype=bool)
    inside[vi[0] : vi[-1] + 1] = True
    gap = inside & ~fix
    d = d.copy()
    d[gap] = np.interp(x[gap], x[vi], d[vi])
    return d


def _distance(a, has_gps) -> tuple[np.ndarray, str]:
    n = len(a["t"])
    dev = a["dist"]
    if np.isfinite(dev).sum() >= 0.9 * n and np.nanmax(dev) > 0:
        d = np.maximum.accumulate(_ffill(dev))
        d = d - d[0]
        return (_bridge_gps_gaps(a, d) if has_gps else d), "device"
    if has_gps:
        lat, lon = _ffill(a["lat"]), _ffill(a["lon"])
        step = np.concatenate([[0.0], haversine(lat[:-1], lon[:-1], lat[1:], lon[1:])])
        return _bridge_gps_gaps(a, np.cumsum(step)), "gps"
    if a["has_time"] and np.isfinite(a["speed"]).any():
        dt = np.concatenate([[0.0], np.diff(a["t"])])
        sp = np.nan_to_num(_ffill(a["speed"]))
        return np.cumsum(sp * np.clip(dt, 0, 10)), "speed"
    return np.zeros(n), "none"


def _elevation_gain(ele: np.ndarray, threshold: float = 2.0) -> tuple[float, float]:
    if not np.isfinite(ele).any():
        return 0.0, 0.0
    gain = loss = 0.0
    anchor = ele[0]
    for e in ele[1:]:
        diff = e - anchor
        if diff >= threshold:
            gain += diff
            anchor = e
        elif -diff >= threshold:
            loss -= diff
            anchor = e
    return gain, loss


def _resample_1hz(t: np.ndarray, values: np.ndarray, max_gap: float = 5.0) -> np.ndarray:
    """Step-resample a channel onto a 1 s grid. Gaps longer than ``max_gap`` are zero."""
    rel = t - t[0]
    grid = np.arange(0, int(rel[-1]) + 1, dtype=float)
    idx = np.clip(np.searchsorted(rel, grid, side="right") - 1, 0, len(rel) - 1)
    out = np.nan_to_num(values[idx])
    nxt = np.clip(idx + 1, 0, len(rel) - 1)
    gap = rel[nxt] - rel[idx]
    out[(gap > max_gap) & (grid - rel[idx] > max_gap)] = 0.0
    return out


def _best_averages(series_1hz: np.ndarray, durations) -> list[dict]:
    cs = np.concatenate([[0.0], np.cumsum(series_1hz)])
    out = []
    for d in durations:
        if d > len(series_1hz):
            break
        best = float(np.max((cs[d:] - cs[:-d]) / d))
        out.append({"duration_s": d, "value": round(best, 1)})
    return out


def _best_efforts(dist: np.ndarray, t: np.ndarray, targets) -> list[dict]:
    out = []
    if len(dist) < 2:
        return out
    for target in targets:
        if dist[-1] < target:
            break
        starts = dist <= dist[-1] - target
        if not starts.any():
            continue
        t_end = np.interp(dist[starts] + target, dist, t)
        dur = t_end - t[starts]
        i = int(np.argmin(dur))
        out.append(
            {
                "distance_m": target,
                "time_s": round(float(dur[i]), 1),
                "start_offset_s": round(float(t[starts][i] - t[0]), 1),
            }
        )
    return out


def _splits(dist, moving_time, ele_s, hr, power, unit_m=1000.0) -> list[dict]:
    total = dist[-1]
    if total < unit_m * 0.05:
        return []
    bounds = [*list(np.arange(0, total, unit_m)), total]
    if len(bounds) > 1 and bounds[-1] - bounds[-2] < 1:
        bounds.pop(-2)
    mt_at = np.interp(bounds, dist, moving_time)
    out = []
    for k in range(len(bounds) - 1):
        lo, hi = bounds[k], bounds[k + 1]
        mask = (dist >= lo) & (dist <= hi)
        seg_ele = ele_s[mask]
        gain = float(np.sum(np.clip(np.diff(seg_ele), 0, None))) if np.isfinite(seg_ele).sum() > 1 else None
        seg_dist = float(hi - lo)
        seg_t = float(mt_at[k + 1] - mt_at[k])
        out.append(
            {
                "index": k + 1,
                "distance_m": round(seg_dist, 1),
                "moving_s": round(seg_t, 1),
                "speed_ms": _num(seg_dist / seg_t, 3) if seg_t > 0 else None,
                "elev_gain_m": _num(gain),
                "avg_hr": _num(np.nanmean(hr[mask])) if np.isfinite(hr[mask]).any() else None,
                "avg_power": _num(np.nanmean(power[mask])) if np.isfinite(power[mask]).any() else None,
            }
        )
    return out


def _downsample_idx(n: int, target: int) -> np.ndarray:
    if n <= target:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, target).round().astype(int))


def _series_list(values: np.ndarray, idx: np.ndarray, nd=1):
    if not np.isfinite(values).any():
        return None
    return [_num(v, nd) for v in values[idx]]


# --------------------------------------------------------------------------- main entry


def analyse(
    cols: dict[str, list], sport: str = "unknown", settings: dict | None = None, split_m: float = 1000.0
) -> dict:
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    a = _prepare(cols)
    n = len(a["t"])
    if n == 0:
        raise ValueError("no usable points")
    has_time = a["has_time"]
    has_gps = bool((np.isfinite(a["lat"]) & np.isfinite(a["lon"])).sum() >= 2)

    t = a["t"] if has_time else np.arange(n, dtype=float)
    dt = np.concatenate([[0.0], np.diff(t)]) if has_time else np.zeros(n)
    dist, dist_source = _distance(a, has_gps)
    ddist = np.concatenate([[0.0], np.diff(dist)])

    # Moving detection: per-interval speed above sport threshold.
    if has_time:
        thr = sports.get(sport).moving_ms
        if dist[-1] > 0:
            seg_speed = np.divide(ddist, dt, out=np.zeros(n), where=dt > 0)
            moving = (seg_speed >= thr) & (dt > 0)
        else:  # indoor without distance: count everything sampled densely
            moving = (dt > 0) & (dt <= 10)
        moving_time = np.cumsum(np.where(moving, dt, 0.0))
        w = np.where(moving, np.clip(dt, 0, 10), 0.0)  # weights for channel averages
        elapsed = float(t[-1] - t[0])
    else:
        moving = np.zeros(n, dtype=bool)
        moving_time = np.zeros(n)
        w = np.ones(n)
        elapsed = None

    # Speed. Prefer the speed the device recorded (GPS Doppler or a wheel sensor): it does
    # not jump when positions do, unlike speed derived from distance, where GPS settling
    # after a fix (tens of metres in a second or two) reads as 100+ km/h.
    dev_speed = a["speed"]
    if np.isfinite(dev_speed).sum() >= 0.5 * n and np.nanmax(dev_speed) > 0:
        speed = _ffill(dev_speed)
        speed[: int(np.argmax(np.isfinite(dev_speed)))] = np.nan  # no speed before the first reading
    elif has_time and dist[-1] > 0:
        # From distance over at least ~5 s: look back to the last point 5 s or more earlier.
        # (Only points inside the last 5 s would shrink the window to a single interval
        # with sparse "smart" recording, where a few metres of GPS noise read as 70 km/h.)
        i0 = np.maximum(np.searchsorted(t, t - 5.0, side="right") - 1, 0)
        span = t - t[i0]
        speed = np.divide(dist - dist[i0], span, out=np.zeros(n), where=span > 0)
        speed[~np.isfinite(speed)] = 0
    elif np.isfinite(dev_speed).any():
        speed = _ffill(dev_speed)
    else:
        speed = np.full(n, np.nan)
    if np.isfinite(speed).any():
        speed = _nan_median(speed, 5)  # a one- or two-point blip never becomes the maximum

    # Elevation
    ele_raw = a["ele"]
    has_ele = bool(np.isfinite(ele_raw).sum() >= 2)
    ele_s = _centered_median(_interp_nans(ele_raw), 5) if has_ele else np.full(n, np.nan)
    gain, loss = _elevation_gain(ele_s) if has_ele else (None, None)

    hr, cad, power, temp = a["hr"], a["cad"], a["power"], a["temp"]
    has_hr = bool(np.isfinite(hr).any())
    has_power = bool(np.isfinite(power).any())

    moving_s = float(moving_time[-1]) if has_time else None
    summary = {
        "start_time": datetime.fromtimestamp(t[0], tz=timezone.utc).isoformat() if has_time else None,
        "distance_m": _num(dist[-1]),
        "distance_source": dist_source,
        "elapsed_s": _num(elapsed, 0),
        "moving_s": _num(moving_s, 0),
        "avg_speed_ms": _num(dist[-1] / moving_s, 3) if moving_s else None,
        "max_speed_ms": _num(_nanmax(speed), 3),
        "elev_gain_m": _num(gain),
        "elev_loss_m": _num(loss),
        "ele_min_m": _num(_nanmax(-ele_s) * -1) if has_ele else None,
        "ele_max_m": _num(_nanmax(ele_s)) if has_ele else None,
        "avg_hr": _num(_wmean(hr, w), 0),
        "max_hr": _num(_nanmax(hr), 0),
        "avg_cadence": _num(_wmean(cad, w, skip_zero=True), 0),
        "max_cadence": _num(_nanmax(cad), 0),
        "avg_power": _num(_wmean(power, w), 0),
        "max_power": _num(_nanmax(power), 0),
        "avg_temp_c": _num(_wmean(temp, w)),
        "points": n,
        "has_gps": has_gps,
        "has_time": has_time,
    }

    # Heart-rate zones + TRIMP
    zones = None
    if has_hr and has_time:
        max_hr, rest_hr = float(s["max_hr"]), float(s["rest_hr"])
        bounds = [b * max_hr for b in HR_ZONE_BOUNDS]
        zone_idx = np.digitize(np.nan_to_num(hr, nan=-1), bounds)
        hr_ok = np.isfinite(hr)
        zw = np.clip(dt, 0, 10)
        edges = [0] + [round(b) for b in bounds] + [round(max_hr)]
        zones = [
            {
                "zone": z + 1,
                "min_bpm": edges[z],
                "max_bpm": edges[z + 1] if z < 4 else None,
                "time_s": round(float(zw[hr_ok & (zone_idx == z)].sum()), 0),
            }
            for z in range(5)
        ]
        hrr = np.clip((hr - rest_hr) / max(max_hr - rest_hr, 1), 0, 1)
        trimp = np.nansum((zw / 60.0) * hrr * 0.64 * np.exp(1.92 * hrr))
        summary["trimp"] = _num(trimp, 0)

    # Power: NP, IF, TSS, work, power curve
    power_curve = None
    if has_power and has_time and n > 1:
        p1 = _resample_1hz(t, power)
        if len(p1) >= 30:
            np_ = float(np.mean(_rolling_mean(p1, 30)[29:] ** 4) ** 0.25)
            ftp = float(s["ftp"]) or None
            summary["normalized_power"] = _num(np_, 0)
            if ftp:
                if_ = np_ / ftp
                summary["intensity_factor"] = _num(if_, 2)
                summary["tss"] = _num(len(p1) * np_ * if_ / (ftp * 3600) * 100, 0)
        summary["work_kj"] = _num(float(np.nansum(np.nan_to_num(power) * np.clip(dt, 0, 10))) / 1000, 0)
        power_curve = _best_averages(p1, POWER_CURVE_DURATIONS)

    best_efforts = _best_efforts(dist, t, sports.get(sport).efforts) if has_time and dist[-1] > 0 else []
    splits = _splits(dist, moving_time, ele_s, hr, power, split_m) if has_time and dist[-1] > 0 else []

    # Series for charts (downsampled)
    idx = _downsample_idx(n, MAX_SERIES_POINTS)
    power_disp = _rolling_mean(np.nan_to_num(power), 5) if has_power else power
    series = {
        "idx": [int(i) for i in idx],
        "time_s": [_num(v - t[0], 0) for v in t[idx]] if has_time else None,
        "distance_m": [_num(v, 0) for v in dist[idx]],
        "elevation_m": _series_list(ele_s, idx),
        "speed_ms": _series_list(speed, idx, 2),
        "hr": _series_list(hr, idx, 0),
        "cadence": _series_list(cad, idx, 0),
        "power": _series_list(power_disp, idx, 0),
        "temp_c": _series_list(temp, idx),
        "lat": _series_list(a["lat"], idx, 6),
        "lon": _series_list(a["lon"], idx, 6),
    }

    track = None
    if has_gps:
        tidx = _downsample_idx(n, MAX_TRACK_POINTS)
        ok = np.isfinite(a["lat"][tidx]) & np.isfinite(a["lon"][tidx])
        track = [[round(float(la), 6), round(float(lo), 6)] for la, lo in zip(a["lat"][tidx][ok], a["lon"][tidx][ok])]

    return {
        "summary": summary,
        "series": series,
        "track": track,
        "splits": splits,
        "hr_zones": zones,
        "power_curve": power_curve,
        "best_efforts": best_efforts,
        "settings_used": s,
    }
