"""Core: repeating-lap detection and the laps report."""

import pytest

from app.analytics import activity_to_columns
from app.parsers import parse_file
from tests.helpers import upload as _upload
from tests.samples import lap_track, synthetic_track, to_gpx


def test_detect_laps_on_track():
    from app.laps import detect_laps

    act = parse_file("track.gpx", to_gpx(lap_track(laps=8)))
    det = detect_laps(activity_to_columns(act))
    assert det is not None
    assert det["count"] == 8
    assert det["lap_distance_m"] == pytest.approx(400, rel=0.03)
    # warm-up (600 m at 3 m/s = 200 s) and cool-down are excluded
    assert 185 <= det["start"] <= 205
    for a, b in zip(det["laps"], det["laps"][1:]):
        assert a["end"] == b["start"]


@pytest.mark.parametrize("pts", [synthetic_track(), lap_track(laps=1, cooldown=50)])
def test_no_laps_without_repeats(pts):
    from app.laps import detect_laps

    assert detect_laps(activity_to_columns(parse_file("x.gpx", to_gpx(pts)))) is None


def test_out_and_back_is_not_laps():
    from app.laps import detect_laps

    out = synthetic_track(seconds=600, pause=(0, 0))
    back = [
        {**p, "t": out[-1]["t"] + (p["t"] - out[0]["t"]) + __import__("datetime").timedelta(seconds=1)}
        for p in reversed(out)
    ]
    for p, q in zip(back, reversed(out)):
        p["lat"] = q["lat"]
    assert detect_laps(activity_to_columns(parse_file("x.gpx", to_gpx(out + back)))) is None


def test_laps_api(client):
    speeds = [4.0, 4.4, 4.2, 4.1]
    aid = _upload(client, "track.gpx", to_gpx(lap_track(laps=4, lap_speeds=speeds)))
    detail = client.get(f"/api/activities/{aid}").json()
    assert detail["laps"]["count"] == 4
    # also present in trimmed views, with absolute indices
    view = client.get(f"/api/activities/{aid}?start={detail['laps']['start']}&end={detail['laps']['end']}").json()
    assert view["laps"] == detail["laps"] and view["window"]["start"] == detail["laps"]["start"]

    rep = client.get(f"/api/activities/{aid}/laps").json()
    assert len(rep["laps"]) == 4
    times = [lp["elapsed_s"] for lp in rep["laps"]]
    for t, sp in zip(times, speeds):
        assert t == pytest.approx(400 / sp, abs=4)
    assert rep["lap_time_stats"]["best_index"] == 2 and rep["lap_time_stats"]["worst_index"] == 1
    assert sum(lp["delta_s"] for lp in rep["laps"]) == pytest.approx(0, abs=0.5)
    assert rep["section"]["distance_m"] == pytest.approx(1600, rel=0.02)
    assert rep["whole"]["distance_m"] > rep["section"]["distance_m"]
    assert rep["laps"][0]["avg_hr"] > 140

    plain = _upload(client, "run.gpx", to_gpx(synthetic_track()))
    assert client.get(f"/api/activities/{plain}").json()["laps"] is None
    assert client.get(f"/api/activities/{plain}/laps").status_code == 404
