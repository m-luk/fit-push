"""Core: HTTP API for activities, settings, stats and the page itself."""

from tests.samples import synthetic_track, to_fit, to_gpx


def test_upload_list_detail_delete(client):
    files = [
        ("files", ("run.gpx", to_gpx(synthetic_track()), "application/gpx+xml")),
        ("files", ("ride.fit", to_fit(synthetic_track(with_power=True), sport=2), "application/octet-stream")),
        ("files", ("bad.fit", b"garbage", "application/octet-stream")),
    ]
    res = client.post("/api/activities", files=files).json()
    assert len(res["imported"]) == 2 and len(res["errors"]) == 1

    dup = client.post("/api/activities", files=[files[0]]).json()
    assert len(dup["duplicates"]) == 1

    items = client.get("/api/activities").json()
    assert len(items) == 2
    ride_id = next(i["id"] for i in items if i["sport"] == "cycling")

    detail = client.get(f"/api/activities/{ride_id}").json()
    assert detail["source_format"] == "fit"
    assert detail["summary"]["normalized_power"] > 0
    assert detail["series"]["power"] is not None

    patched = client.patch(f"/api/activities/{ride_id}", json={"name": "Evening ride"}).json()
    assert patched["name"] == "Evening ride"

    stats = client.get("/api/stats").json()
    assert stats["totals"]["count"] == 2
    assert stats["records"]["running"] and stats["power_curve"]
    assert stats["periods"][0]["count"] == 2

    assert client.delete(f"/api/activities/{ride_id}").status_code == 204
    assert client.get(f"/api/activities/{ride_id}").status_code == 404


def test_settings_recompute(client):
    client.post("/api/activities", files=[("files", ("run.fit", to_fit(synthetic_track()), "x"))])
    before = client.get("/api/activities").json()[0]["summary"]["hr_zones"]
    assert client.put("/api/settings", json={"max_hr": 175}).json()["max_hr"] == 175
    after = client.get("/api/activities").json()[0]["summary"]["hr_zones"]
    assert before != after
    assert client.put("/api/settings", json={"max_hr": 20}).status_code == 422


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert r.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
