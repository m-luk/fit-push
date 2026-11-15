"""Core: the tutorial's simulated run is complete, reusable and removed without a trace."""

from __future__ import annotations

from app import tutorial
from app.analytics import activity_to_columns, analyse
from app.laps import detect_laps
from tests.helpers import upload
from tests.samples import lap_track, to_gpx


def test_simulated_run_has_everything_the_tour_shows():
    act = tutorial.simulated_run()
    cols = activity_to_columns(act)
    s = analyse(cols, "running", {})["summary"]
    assert 6500 < s["distance_m"] < 8000
    assert s["avg_hr"] and s["avg_cadence"]
    assert s["elev_gain_m"] > 20
    det = detect_laps(cols)
    assert det is not None
    assert det["count"] == len(tutorial.LAP_SPEEDS)
    # Deterministic apart from the start time.
    again = tutorial.simulated_run(start=act.points[0].t)
    assert [p.lat for p in again.points] == [p.lat for p in act.points]


def test_tutorial_lifecycle(client):
    assert client.get("/api/tutorial").json() == {"activity_id": None, "activities": 0}
    mine = upload(client, "mine.gpx", to_gpx(lap_track()))

    r = client.post("/api/tutorial").json()
    assert r["created"]
    aid = r["activity_id"]
    assert client.post("/api/tutorial").json() == {"activity_id": aid, "created": False}
    a = client.get(f"/api/activities/{aid}").json()
    assert a["name"] == tutorial.NAME
    assert a["tags"] == ["tutorial"]
    laps = client.get(f"/api/activities/{aid}/laps").json()
    assert laps["count"] == len(tutorial.LAP_SPEEDS)

    # What the tour lets the user make: a clip and a segment (from a lap of the clip and of the run).
    lap = laps["laps"][1]
    clip = client.post(f"/api/activities/{aid}/clip", json={"start": 0, "end": 900}).json()["id"]
    seg = client.post("/api/segments", json={"activity_id": aid, "start": lap["start"], "end": lap["end"]})
    assert seg.status_code == 201
    assert len(seg.json()["efforts"]) >= len(tutorial.LAP_SPEEDS) - 1
    client.post("/api/segments", json={"activity_id": clip, "start": 100, "end": 400})
    assert client.get("/api/tutorial").json() == {"activity_id": aid, "activities": 2}

    assert client.delete("/api/tutorial").json() == {"activities": 2, "segments": 2}
    assert client.get("/api/tutorial").json() == {"activity_id": None, "activities": 0}
    assert [x["id"] for x in client.get("/api/activities").json()] == [mine]
    assert client.get("/api/segments").json() == []
    assert client.get("/api/tags").json() == []


def test_user_segments_survive_the_tutorial_cleanup(client):
    mine = upload(client, "mine.gpx", to_gpx(lap_track()))
    det = client.get(f"/api/activities/{mine}/laps").json()
    lap = det["laps"][0]
    seg = client.post("/api/segments", json={"activity_id": mine, "start": lap["start"], "end": lap["end"]}).json()
    client.post("/api/tutorial")
    client.delete("/api/tutorial")
    assert [s["id"] for s in client.get("/api/segments").json()] == [seg["id"]]
