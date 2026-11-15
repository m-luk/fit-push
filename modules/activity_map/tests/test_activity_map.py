"""Tests for the activity_map module. Run: python -m pytest modules/activity_map -q"""

from tests.helpers import upload
from tests.samples import START, lap_track, synthetic_track, to_fit, to_gpx


def _setup(client):
    run = upload(client, "run.gpx", to_gpx(synthetic_track()))  # 1 Nov
    ride = upload(client, "ride.fit", to_fit(synthetic_track(with_power=True, start=START.replace(day=20)), sport=2))
    track = upload(client, "track.gpx", to_gpx(lap_track(laps=3, start=START.replace(month=10))))  # 1 Oct
    client.put(f"/api/activities/{ride}/tags", json={"tags": ["Commute"]})
    return run, ride, track


def test_tracks_filters(make_client):
    client = make_client(modules="activity_map")
    run, ride, track = _setup(client)
    get = lambda q="": {a["id"] for a in client.get(f"/api/m/activity_map/tracks{q}").json()["activities"]}  # noqa: E731
    assert get() == {run, ride, track}
    assert get("?sports=cycling") == {ride}
    assert get("?sports=cycling,running") == {run, ride, track}
    assert get("?tags=commute") == {ride}  # tags are normalised to lower case
    assert get("?from=2026-11-01") == {run, ride}
    assert get("?to=2026-10-31") == {track}
    assert get("?from=2026-11-10&sports=running") == set()
    assert client.get("/api/m/activity_map/tracks?from=nonsense").status_code == 422


def test_tracks_are_thinned_and_cached(make_client):
    client = make_client(modules="activity_map")
    run, *_ = _setup(client)
    acts = {a["id"]: a for a in client.get("/api/m/activity_map/tracks").json()["activities"]}
    line = acts[run]["track"]
    assert 100 < len(line) <= 400 and len(line[0]) == 2  # 5.2 km at ~25 m spacing
    assert client.delete(f"/api/activities/{run}").status_code == 204
    assert run not in {a["id"] for a in client.get("/api/m/activity_map/tracks").json()["activities"]}


def test_facets(make_client):
    client = make_client(modules="activity_map")
    _setup(client)
    f = client.get("/api/m/activity_map/facets").json()
    assert f["sports"] == {"running": 2, "cycling": 1}
    assert f["tags"] == [{"tag": "commute", "count": 1}]
    assert (f["first"], f["last"], f["count"]) == ("2026-10-01", "2026-11-20", 3)


def test_module_is_isolated(make_client):
    assert make_client(modules="none").get("/api/m/activity_map/facets").status_code == 404
    client = make_client(modules="activity_map")
    status = {m["id"]: m["status"] for m in client.get("/api/modules").json()}
    assert status["activity_map"] == "loaded"
    assert client.get("/m/activity_map/frontend.js").status_code == 200
    assert client.get("/m/activity_map/backend.py").status_code == 404  # only frontend files are served
