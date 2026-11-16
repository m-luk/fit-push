"""Core: uphill/downhill legs of ski activities (ski touring climbs/descents, resort lifts/runs)."""

import pytest

from app import ski
from tests.helpers import cols, upload
from tests.samples import ski_track, synthetic_track, to_gpx


def _detect(pts, sport):
    r = ski.detect(cols(pts), sport)
    assert r is not None
    return r


@pytest.mark.parametrize(
    ("touring", "sport", "up", "down"), [(False, "skiing", "lift", "run"), (True, "ski_touring", "climb", "descent")]
)
def test_detects_alternating_legs(touring, sport, up, down):
    r = _detect(ski_track(cycles=3, touring=touring), sport)
    assert r["mode"] == ("touring" if touring else "resort")
    assert r["labels"] == {"up": up, "down": down}
    assert [lg["type"] for lg in r["legs"]] == ["up", "down"] * 3
    assert [lg["index"] for lg in r["legs"]] == [1, 1, 2, 2, 3, 3]
    # the 15 m rise inside every run does not split it, and every leg has ~400 m vertical
    for lg in r["legs"]:
        assert lg["vertical_m"] == pytest.approx(400, abs=12)
        assert lg["name"] == (up if lg["type"] == "up" else down)
    assert r["up"]["count"] == r["down"]["count"] == 3
    assert r["down"]["vertical_m"] == pytest.approx(1200, abs=30)
    # legs are ordered and don't overlap
    for a, b in zip(r["legs"], r["legs"][1:]):
        assert a["end"] <= b["start"]


def test_flat_ends_are_trimmed_into_breaks():
    r = _detect(ski_track(cycles=2), "skiing")
    lift = r["legs"][0]
    # 120 s queue at the bottom before the lift moves; lift ride ~200 s, not 200 + queue + top break
    assert 110 <= lift["start"] <= 130
    assert lift["elapsed_s"] == pytest.approx(200, abs=10)
    assert lift["vertical_rate_mh"] == pytest.approx(7200, rel=0.05)
    assert r["other_s"] > 2 * (120 + 90) - 40  # queues and top breaks


def test_run_stats():
    r = _detect(ski_track(cycles=2), "skiing")
    run = next(lg for lg in r["legs"] if lg["type"] == "down")
    assert run["max_speed_ms"] > run["avg_speed_ms"] > 8
    assert run["distance_m"] > 1500
    assert run["avg_grade_pct"] == pytest.approx(run["vertical_m"] / run["distance_m"] * 100, abs=0.2)
    assert r["down"]["longest_m"] >= run["distance_m"]


def test_not_for_other_sports_or_flat_tracks():
    assert ski.detect(cols(ski_track()), "running") is None
    gentle = [{**p, "ele": 100 + 10 * (i % 600) / 600} for i, p in enumerate(synthetic_track())]
    assert ski.detect(cols(gentle), "skiing") is None  # 10 m ups and downs: no legs


def test_analysis_includes_ski_legs(client):
    aid = upload(client, "ski.gpx", to_gpx(ski_track(cycles=2), name="Ski day", sport="skiing"))
    a = client.get(f"/api/activities/{aid}").json()
    assert a["sport"] == "skiing"
    assert a["ski"]["down"]["count"] == 2
    # a trimmed view reports legs inside it, with absolute indices
    run = a["ski"]["legs"][1]
    w = client.get(f"/api/activities/{aid}?start={run['start'] - 5}&end={run['end'] + 5}").json()
    assert w["ski"] is None or all(lg["start"] >= run["start"] - 5 for lg in w["ski"]["legs"])
    lift2 = a["ski"]["legs"][2]
    w2 = client.get(f"/api/activities/{aid}?start={run['start'] - 50}&end={lift2['end'] + 50}").json()
    assert [lg["type"] for lg in w2["ski"]["legs"]] == ["down", "up"]
    assert w2["ski"]["legs"][0]["start"] == pytest.approx(run["start"], abs=3)


def test_ski_legs_follow_the_sport(client):
    aid = upload(client, "ski.gpx", to_gpx(ski_track(cycles=2), name="Ski day", sport="running"))
    assert client.get(f"/api/activities/{aid}").json()["ski"] is None
    client.patch(f"/api/activities/{aid}", json={"sport": "ski_touring"})
    a = client.get(f"/api/activities/{aid}").json()
    assert a["ski"]["mode"] == "touring"
    assert a["ski"]["labels"]["up"] == "climb"
