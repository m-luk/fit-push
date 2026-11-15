"""Core: segments, effort matching and the segments API."""

import pytest

from tests.helpers import cols as _cols
from tests.helpers import upload as _upload
from tests.samples import START, lap_track, synthetic_track, to_gpx


def test_segment_matches_same_route_only_forward_and_on_course():
    from datetime import timedelta

    from app.segments import build_segment, find_efforts

    base = synthetic_track(seconds=900, pause=(0, 0))  # 2.7 km north
    seg = build_segment(_cols(base), 100, 500)  # 1.2 km in the middle
    assert seg["distance_m"] == pytest.approx(1200, abs=5)

    later = [{**p, "t": p["t"] + timedelta(days=3)} for p in base]
    assert find_efforts(seg, _cols(later)) == [(100, 500)]

    back = list(reversed(base))  # same road, other direction
    for k, p in enumerate(back):
        p = back[k] = {**p, "t": base[k]["t"]}
    assert find_efforts(seg, _cols(back)) == []

    detour = [dict(p) for p in base]  # leaves the road for 300 m
    for p in detour[250:350]:
        p["lon"] += 0.003
    assert find_efforts(seg, _cols(detour)) == []

    assert find_efforts(seg, _cols(lap_track())) == []  # somewhere else entirely


def test_segment_from_lap_matches_every_lap():
    from app.laps import detect_laps
    from app.segments import build_segment, find_efforts

    cols = _cols(lap_track(laps=6))
    det = detect_laps(cols)
    assert det is not None
    lap = det["laps"][1]
    seg = build_segment(cols, lap["start"], lap["end"])
    assert len(find_efforts(seg, cols)) == 6


def test_segments_api(client):
    a1 = _upload(client, "a.gpx", to_gpx(lap_track(laps=4, lap_speeds=[4.0, 4.4, 4.2, 4.1])))
    lap = client.get(f"/api/activities/{a1}").json()["laps"]
    det = client.get(f"/api/activities/{a1}/laps").json()["laps"][0]

    r = client.post(
        "/api/segments", json={"activity_id": a1, "start": det["start"], "end": det["end"], "name": "Track lap"}
    )
    assert r.status_code == 201
    seg = r.json()
    assert seg["name"] == "Track lap" and len(seg["efforts"]) == lap["count"]
    times = [e["elapsed_s"] for e in seg["efforts"]]
    assert times == sorted(times) and seg["efforts"][0]["rank"] == 1
    assert seg["efforts"][0]["elapsed_s"] == pytest.approx(400 / 4.4, abs=4)

    # a later upload on the same track is matched automatically
    a2 = _upload(
        client, "b.gpx", to_gpx(lap_track(laps=3, lap_speeds=[4.6, 4.6, 4.6], seed=3, start=START.replace(day=8)))
    )
    seg = client.get(f"/api/segments/{seg['id']}").json()
    assert len(seg["efforts"]) == lap["count"] + 3
    assert seg["efforts"][0]["activity_id"] == a2  # new best time
    assert [a["activity_id"] for a in seg["activities"]] == [a2, a1]  # newest first
    assert seg["activities"][1]["efforts"] == lap["count"]

    # the activity side lists its efforts with their rank
    mine = client.get(f"/api/activities/{a1}").json()["segment_efforts"]
    assert len(mine) == lap["count"] and all(e["segment_name"] == "Track lap" for e in mine)
    assert mine == sorted(mine, key=lambda e: e["start"]) and mine[0]["of"] == lap["count"] + 3

    listed = client.get("/api/segments").json()
    assert (
        listed[0]["effort_count"] == lap["count"] + 3 and listed[0]["activity_count"] == 2 and "points" not in listed[0]
    )

    assert client.patch(f"/api/segments/{seg['id']}", json={"name": "Oval"}).json()["name"] == "Oval"
    assert client.delete(f"/api/activities/{a2}").status_code == 204  # efforts go with the activity
    assert len(client.get(f"/api/segments/{seg['id']}").json()["efforts"]) == lap["count"]
    assert len(client.post(f"/api/segments/{seg['id']}/rescan").json()["efforts"]) == lap["count"]
    assert (
        client.post("/api/segments", json={"activity_id": a1, "start": 10, "end": 20}).status_code == 422
    )  # too short
    assert client.delete(f"/api/segments/{seg['id']}").status_code == 204
    assert client.get(f"/api/activities/{a1}").json()["segment_efforts"] == []


def test_long_segment_matches_itself():
    # Regression: long segments were compared at a fixed 200 points (~200 m apart on a
    # 40 km route), so even the activity a segment was cut from did not match it.
    from app.segments import build_segment, find_efforts

    cols = _cols(synthetic_track(seconds=5000, speed=8.0, pause=(0, 0)))  # 40 km
    seg = build_segment(cols, 0, 5000)
    assert find_efforts(seg, cols) == [(0, 5000)]
