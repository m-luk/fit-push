"""Core: speed and distance stay realistic with GPS gaps, sparse recording and GPS settling."""

from __future__ import annotations

import math

import pytest

from app.analytics import ANALYSIS_VERSION, analyse
from tests.helpers import upload
from tests.samples import synthetic_track, to_gpx

V = 7.0  # m/s (25.2 km/h), a city bike ride
LAT0, LON0 = 52.0, 21.0
M_PER_DEG_LAT = 111_195.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(LAT0))


def ride(n=300, gap=None, device_dist=True, speed=True, t=None):
    """1 Hz ride east at V; ``gap=(a, b)``: no position for points a..b-1 while the device's
    distance stays frozen (the catch-up arrives at point b), like a watch losing GPS."""
    t = t or list(range(n))
    cols: dict[str, list] = {"t": [], "lat": [], "lon": [], "dist": [], "speed": []}
    for i, ti in enumerate(t):
        x = V * ti
        in_gap = gap is not None and gap[0] <= i < gap[1]
        cols["t"].append(1_700_000_000 + ti)
        cols["lat"].append(None if in_gap else LAT0)
        cols["lon"].append(None if in_gap else LON0 + x / M_PER_DEG_LON)
        cols["dist"].append(V * t[gap[0] - 1] if in_gap else x)
        cols["speed"].append(None if in_gap else V)
    if not device_dist:
        cols.pop("dist")
    if not speed:
        cols.pop("speed")
    return cols


@pytest.mark.parametrize("device_dist", [True, False], ids=["device distance", "gps distance"])
def test_gps_gap_does_not_make_a_speed_spike(device_dist):
    s = analyse(ride(gap=(100, 120), device_dist=device_dist, speed=False), "cycling")["summary"]
    assert s["max_speed_ms"] < V * 1.1  # was ~140 m in one second: 500 km/h
    assert s["distance_m"] == pytest.approx(V * 299, rel=0.01)  # total unchanged
    assert s["moving_s"] == pytest.approx(299, abs=2)  # the gap counts as moving, not as a stop


def test_sparse_recording_jitter_is_averaged_over_5_seconds():
    # "smart recording": a point every 6 s plus one a second later, each 1-s pair with
    # 4 m of position noise (would read as 4 m/s extra over a 1-s interval)
    times = sorted({k for b in range(0, 600, 6) for k in (b, b + 1)})
    cols = ride(t=times, speed=False, device_dist=False)
    for i in range(1, len(times), 2):
        cols["lon"][i] += 4.0 / M_PER_DEG_LON
    s = analyse(cols, "cycling")["summary"]
    assert s["max_speed_ms"] < V * 1.25


def test_device_speed_preferred_and_blips_ignored():
    cols = ride(device_dist=False)  # distance from GPS positions, so the settling jump counts
    cols["lon"][1] = LON0 + 250 / M_PER_DEG_LON  # GPS settling: 250 m off for one point
    cols["speed"][0] = 30.0  # bad first reading
    cols["speed"][150] = 35.0  # one-point blip
    r = analyse(cols, "cycling")
    assert r["summary"]["max_speed_ms"] == pytest.approx(V, rel=0.01)
    assert max(v for v in r["series"]["speed_ms"] if v is not None) == pytest.approx(V, rel=0.01)


def test_stale_summaries_are_recomputed_once(make_client):
    client = make_client(modules="none")
    aid = upload(client, "run.gpx", to_gpx(synthetic_track()))
    core = client.app.state.core
    good = core.row(aid, with_points=False)["summary"]["max_speed_ms"]
    assert core.store.get_meta("analysis_version") == ANALYSIS_VERSION
    assert core.refresh_stale_summaries() == 0  # already current

    core.store.update(aid, summary={**core.row(aid, with_points=False)["summary"], "max_speed_ms": 99.0})
    core.store.set_meta("analysis_version", ANALYSIS_VERSION - 1)
    assert core.refresh_stale_summaries() == 1
    assert core.row(aid, with_points=False)["summary"]["max_speed_ms"] == pytest.approx(good)
    assert core.store.get_meta("analysis_version") == ANALYSIS_VERSION
