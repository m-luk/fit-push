"""Core: analytics (distance, moving time, elevation, zones, power, splits, efforts)."""

import pytest

from app.analytics import activity_to_columns, analyse
from app.parsers import parse_file
from tests.samples import synthetic_track, to_fit, to_gpx


def test_analytics_running():
    act = parse_file("run.gpx", to_gpx(synthetic_track()))
    r = analyse(activity_to_columns(act), act.sport, {"max_hr": 190, "rest_hr": 60})
    s = r["summary"]
    assert s["distance_m"] == pytest.approx(5220, rel=0.005)
    assert s["elapsed_s"] == 1800
    assert s["moving_s"] == pytest.approx(1740, abs=2)  # 60 s pause excluded
    assert s["avg_speed_ms"] == pytest.approx(3.0, rel=0.01)
    assert s["elev_gain_m"] == pytest.approx(22.6, abs=2)
    assert s["elev_loss_m"] == pytest.approx(40, abs=2)
    assert s["avg_hr"] > 120 and s["max_hr"] == 170
    assert len(r["splits"]) == 6  # 5 full km + remainder
    assert r["splits"][0]["moving_s"] == pytest.approx(333.3, abs=1)
    efforts = {e["distance_m"]: e["time_s"] for e in r["best_efforts"]}
    assert efforts[1000] == pytest.approx(333.3, abs=1)
    assert sum(z["time_s"] for z in r["hr_zones"]) == pytest.approx(1800, abs=2)
    assert r["track"] and len(r["series"]["distance_m"]) <= 1500


def test_analytics_power():
    act = parse_file("ride.fit", to_fit(synthetic_track(with_power=True), sport=2))
    r = analyse(activity_to_columns(act), act.sport, {"ftp": 250})
    s = r["summary"]
    assert 195 < s["avg_power"] < 210
    assert s["normalized_power"] >= s["avg_power"]
    assert s["intensity_factor"] == pytest.approx(s["normalized_power"] / 250, abs=0.01)
    assert s["tss"] > 0 and s["work_kj"] > 300
    curve = {p["duration_s"]: p["value"] for p in r["power_curve"]}
    assert curve[5] >= curve[60] >= curve[1200]


def test_analytics_without_gps_or_time():
    cols = {"t": [None] * 3, "lat": [None] * 3, "lon": [None] * 3, "ele": [1, 2, 3]}
    r = analyse(cols)
    assert r["summary"]["has_time"] is False and r["track"] is None
