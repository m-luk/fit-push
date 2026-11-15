"""Core: activity tags (normalisation, API, list filter, events)."""

import pytest

from app.core import Invalid, normalise_tags
from tests.helpers import upload
from tests.samples import synthetic_track, to_gpx


def test_normalise_tags():
    assert normalise_tags(["  Race ", "race", "Long  Run", "x/y!", ""]) == ["long run", "race", "xy"]
    assert normalise_tags(["ä-trail_1"]) == ["ä-trail_1"]
    with pytest.raises(Invalid):
        normalise_tags([f"t{i}" for i in range(21)])


def test_tags_api(client):
    a = upload(client, "a.gpx", to_gpx(synthetic_track()))
    b = upload(client, "b.gpx", to_gpx(synthetic_track(speed=3.2)))
    assert client.put(f"/api/activities/{a}/tags", json={"tags": ["Race", "Spring"]}).json() == {
        "tags": ["race", "spring"]
    }
    client.put(f"/api/activities/{b}/tags", json={"tags": ["spring"]})
    assert client.get("/api/tags").json() == [{"tag": "race", "count": 1}, {"tag": "spring", "count": 2}]
    assert [x["id"] for x in client.get("/api/activities?tag=race").json()] == [a]
    assert client.get(f"/api/activities/{a}").json()["tags"] == ["race", "spring"]
    assert {x["id"]: x["tags"] for x in client.get("/api/activities").json()}[b] == ["spring"]
    assert client.put("/api/activities/999/tags", json={"tags": ["x"]}).status_code == 404
    client.delete(f"/api/activities/{b}")
    assert client.get("/api/tags").json() == [{"tag": "race", "count": 1}, {"tag": "spring", "count": 1}]


def test_events_emitted(client):
    seen = []
    core = client.app.state.core
    for ev in ("activity.imported", "activity.updated", "activity.deleted"):
        core.events.on(ev, lambda _ev=ev, **kw: seen.append((_ev, kw.get("fields"))), owner="test")
    a = upload(client, "a.gpx", to_gpx(synthetic_track()))
    client.put(f"/api/activities/{a}/tags", json={"tags": ["x"]})
    client.patch(f"/api/activities/{a}", json={"name": "Renamed"})
    client.delete(f"/api/activities/{a}")
    assert seen == [
        ("activity.imported", None),
        ("activity.updated", ["tags"]),
        ("activity.updated", ["name"]),
        ("activity.deleted", None),
    ]
