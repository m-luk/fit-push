"""The simulated run used by the in-app tutorial.

A deterministic 5-lap park run (warm-up, five ~1 km loops with a small hill, cool-down) with
heart rate, cadence, elevation and temperature, so every feature the tour shows has
something to work on. It is stored like any activity but marked with ``DEVICE``; everything
derived from it (clips keep the device, segments keep their source activity) is removed
again by ``Core.end_tutorial``.
"""

from __future__ import annotations

import bisect
import hashlib
import itertools
import math
import random
from datetime import UTC, datetime, timedelta

from .parsers import Activity, Point

DEVICE = "fit-push tutorial"
NAME = "Tutorial run"
SHA256 = hashlib.sha256(b"fit-push:tutorial:v1").hexdigest()

# A park far from anyone's home; the map shows real tiles around it.
LAT0, LON0 = 51.5045, -0.1650
M_PER_DEG = 111_195.0
LOOP_RX, LOOP_RY = 210.0, 110.0  # ellipse radii (m): ~1.03 km per lap
LAP_SPEEDS = [3.55, 3.75, 4.25, 3.85, 4.45]  # m/s; lap 3 is a fast one, lap 5 the kick
WARMUP_M, COOLDOWN_M = 1200.0, 800.0
RUN_OUT_M = 200.0  # the cool-down jogs on along the loop before leaving it


def _loop_table(steps: int = 4000) -> tuple[list[float], list[tuple[float, float]]]:
    pts = [
        (LOOP_RX * math.cos(2 * math.pi * k / steps), LOOP_RY * math.sin(2 * math.pi * k / steps))
        for k in range(steps + 1)
    ]
    cum = [0.0]
    for a, b in itertools.pairwise(pts):
        cum.append(cum[-1] + math.dist(a, b))
    return cum, pts


_CUM, _PTS = _loop_table()
LOOP_M = _CUM[-1]


def _on_loop(s: float) -> tuple[float, float]:
    """Point at arc length ``s`` on the loop (linear interpolation in the table)."""
    s %= LOOP_M
    k = min(bisect.bisect_right(_CUM, s), len(_CUM) - 1)
    (x0, y0), (x1, y1) = _PTS[k - 1], _PTS[k]
    f = (s - _CUM[k - 1]) / ((_CUM[k] - _CUM[k - 1]) or 1.0)
    return x0 + f * (x1 - x0), y0 + f * (y1 - y0)


def simulated_run(start: datetime | None = None, seed: int = 11) -> Activity:
    """The tutorial activity, starting at ``start`` (default: yesterday 07:00 UTC)."""
    if start is None:
        start = datetime.now(UTC).replace(hour=7, minute=0, second=0, microsecond=0) - timedelta(days=1)
    rnd = random.Random(seed)
    laps = len(LAP_SPEEDS)
    gate = _on_loop(0.0)
    total = WARMUP_M + laps * LOOP_M + COOLDOWN_M
    cos_lat = math.cos(math.radians(LAT0))
    rho, nx, ny = 0.97, 0.0, 0.0  # GPS error drifts slowly (AR(1))
    kick = 2.0 * math.sqrt(1 - rho * rho)
    hr = 95.0
    pts: list[Point] = []
    dist, i = 0.0, 0
    while dist <= total:
        on = dist - WARMUP_M
        lap = int(on // LOOP_M) if 0 <= on < laps * LOOP_M else None
        if lap is None and 0 <= on < laps * LOOP_M + RUN_OUT_M:
            speed = 2.9
            x, y = _on_loop(on)
            ele = 28.0 + 6.0 * (1 - math.cos(2 * math.pi * (on % LOOP_M) / LOOP_M))
        elif lap is None:
            speed = 2.9 + 0.2 * math.sin(i / 40)
            if on < 0:  # approach the loop from the north-east
                back = -on
                x, y = gate[0] + 0.6 * back, gate[1] + 0.8 * back
            else:  # leave to the south-east
                exit_x, exit_y = _on_loop(RUN_OUT_M)
                off = on - laps * LOOP_M - RUN_OUT_M
                x, y = exit_x + 0.3 * off, exit_y + 0.95 * off
            ele = 28.0 + 0.004 * abs(x - gate[0])
        else:
            speed = LAP_SPEEDS[lap] * (1 - 0.06 * math.sin(2 * math.pi * (on % LOOP_M) / LOOP_M))  # slower uphill
            x, y = _on_loop(on)
            ele = 28.0 + 6.0 * (1 - math.cos(2 * math.pi * (on % LOOP_M) / LOOP_M))
        nx, ny = rho * nx + rnd.gauss(0, kick), rho * ny + rnd.gauss(0, kick)
        target = 72 + 18 * speed + (8 if lap is not None and lap >= 2 else 0)
        hr += (target - hr) / 25  # heart rate follows effort with a lag
        pts.append(
            Point(
                t=start + timedelta(seconds=i),
                lat=LAT0 + (y + ny) / M_PER_DEG,
                lon=LON0 + (x + nx) / (M_PER_DEG * cos_lat),
                ele=round(ele + rnd.gauss(0, 0.15), 1),
                hr=round(hr + rnd.gauss(0, 1.0)),
                cad=round(76 + 4.5 * speed + rnd.gauss(0, 0.8)),
                temp=12.0 + i / 1800,
                dist=dist,
            )
        )
        dist += speed
        i += 1
    return Activity(name=NAME, sport="running", source_format="demo", device=DEVICE, points=pts)
