"""Tests for the gear module. Run: python -m pytest modules/gear -q"""

from tests.helpers import upload
from tests.samples import START, synthetic_track, to_fit, to_gpx

API = "/api/m/gear"


def _gear(client, name, kind, **extra):
    res = client.post(f"{API}/gear", json={"name": name, "kind": kind, **extra})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _ids(client, aid):
    return [g["id"] for g in client.get(f"{API}/activity/{aid}").json()["gear"]]


def _items(client):
    return {g["id"]: g for g in client.get(f"{API}/gear").json()["gear"]}


def test_crud_and_validation(make_client):
    client = make_client(modules="gear")
    gid = _gear(client, " Pegasus ", "shoes", start_m=50_000, limit_m=800_000, notes="blue")
    g = _items(client)[gid]
    assert (g["name"], g["kind"], g["distance_m"], g["limit_m"], g["retired"]) == (
        "Pegasus",
        "shoes",
        50_000,
        800_000,
        False,
    )
    assert client.patch(f"{API}/gear/{gid}", json={"retired": True, "limit_m": 0}).json()["limit_m"] is None
    assert _items(client)[gid]["retired"] is True
    assert client.post(f"{API}/gear", json={"name": "x", "kind": "spaceship"}).status_code == 422
    assert client.post(f"{API}/gear", json={"name": "", "kind": "bike"}).status_code == 422
    assert client.patch(f"{API}/gear/999", json={"name": "y"}).status_code == 404
    assert client.put(f"{API}/gear/{gid}/defaults", json={"targets": ["sport:nope"]}).status_code == 422
    assert client.delete(f"{API}/gear/{gid}").status_code == 204
    assert _items(client) == {}


def test_defaults_sport_beats_group(make_client):
    client = make_client(modules="gear")
    road = _gear(client, "Road bike", "bike")
    mtb = _gear(client, "MTB", "bike")
    shoes = _gear(client, "Shoes", "shoes")
    client.put(f"{API}/gear/{road}/defaults", json={"targets": ["family:cycling"]})
    client.put(f"{API}/gear/{mtb}/defaults", json={"targets": ["sport:mountain_biking"]})
    client.put(f"{API}/gear/{shoes}/defaults", json={"targets": ["sport:running", "family:cycling"]})

    ride = upload(client, "ride.fit", to_fit(synthetic_track(with_power=True), sport=2))
    assert sorted(_ids(client, ride)) == sorted([road, shoes])
    run = upload(client, "run.gpx", to_gpx(synthetic_track(start=START.replace(day=3))))
    assert _ids(client, run) == [shoes]

    # Changing the sport re-applies defaults; the sport default beats the group default.
    client.patch(f"/api/activities/{ride}", json={"sport": "mountain_biking"})
    assert sorted(_ids(client, ride)) == sorted([mtb, shoes])

    # One default per target and kind: taking a target moves it.
    client.put(f"{API}/gear/{road}/defaults", json={"targets": ["family:cycling", "sport:mountain_biking"]})
    assert _items(client)[mtb]["defaults"] == []
    # Retired gear is never assigned automatically.
    client.patch(f"{API}/gear/{shoes}", json={"retired": True})
    run2 = upload(client, "run2.gpx", to_gpx(synthetic_track(start=START.replace(day=5))))
    assert _ids(client, run2) == []


def test_kind_change_moves_defaults(make_client):
    client = make_client(modules="gear")
    a = _gear(client, "A", "other")
    b = _gear(client, "B", "bike")
    client.put(f"{API}/gear/{a}/defaults", json={"targets": ["family:cycling"]})
    client.put(f"{API}/gear/{b}/defaults", json={"targets": ["family:cycling"]})
    client.patch(f"{API}/gear/{a}", json={"kind": "bike"})
    items = _items(client)
    assert (items[a]["defaults"], items[b]["defaults"]) == (["family:cycling"], [])


def test_manual_choice_and_reset(make_client):
    client = make_client(modules="gear")
    shoes = _gear(client, "Shoes", "shoes")
    trail = _gear(client, "Trail shoes", "shoes")
    client.put(f"{API}/gear/{shoes}/defaults", json={"targets": ["family:running", "family:foot"]})
    run = upload(client, "run.gpx", to_gpx(synthetic_track()))
    res = client.put(f"{API}/activity/{run}", json={"gear_ids": [trail]}).json()
    assert res["manual"] is True and [g["id"] for g in res["gear"]] == [trail]
    client.patch(f"/api/activities/{run}", json={"sport": "hiking"})
    assert _ids(client, run) == [trail]  # manual choice survives a sport change
    assert client.put(f"{API}/activity/{run}", json={"gear_ids": [999]}).status_code == 404
    assert client.get(f"{API}/activity/999").status_code == 404
    res = client.post(f"{API}/activity/{run}/reset").json()
    assert res["manual"] is False and [g["id"] for g in res["gear"]] == [shoes]


def test_totals_apply_defaults_and_cleanup(make_client):
    client = make_client(modules="gear")
    run = upload(client, "run.gpx", to_gpx(synthetic_track()))  # before any gear exists
    shoes = _gear(client, "Shoes", "shoes", start_m=1000)
    client.put(f"{API}/gear/{shoes}/defaults", json={"targets": ["sport:running"]})
    assert client.get(f"{API}/gear").json()["unassigned"] == 1
    assert client.post(f"{API}/apply-defaults").json() == {"updated": 1}
    assert client.post(f"{API}/apply-defaults").json() == {"updated": 0}
    dist = client.get(f"/api/activities/{run}").json()["summary"]["distance_m"]
    g = _items(client)[shoes]
    assert g["activities"] == 1 and abs(g["distance_m"] - (1000 + dist)) < 1e-6 and g["moving_s"] > 0
    assert g["last_used"].startswith("2026-11-01")
    assert client.delete(f"/api/activities/{run}").status_code == 204
    g = _items(client)[shoes]
    assert (g["activities"], g["distance_m"]) == (0, 1000)


def test_module_is_isolated(make_client):
    assert make_client(modules="none").get(f"{API}/gear").status_code == 404
    client = make_client(modules="gear")
    assert client.get("/api/activities").status_code == 200
    status = {m["id"]: m["status"] for m in client.get("/api/modules").json()}
    assert status["gear"] == "loaded"
    assert client.get("/m/gear/frontend.js").status_code == 200


def test_services_for_importers(make_client):
    client = make_client(modules="gear")
    svc = client.app.state.module_services["gear"]
    bike = svc["ensure"]("VSF", "bike", "VSF TX-Randonee")
    assert svc["ensure"]("vsf", "other") == bike  # found by name, not duplicated
    shoes = svc["ensure"]("Fugi", "shoes")
    assert svc["add_defaults"](bike, ["cycling", "no_such_sport"]) == ["sport:cycling"]
    other_bike = svc["ensure"]("Gejos", "bike")
    assert svc["add_defaults"](other_bike, ["cycling", "gravel_cycling"]) == ["sport:gravel_cycling"]

    aid = upload(client, "ride.gpx", to_gpx(synthetic_track(), sport="cycling"))
    assert _ids(client, aid) == [bike]  # default applied on import
    svc["assign"](aid, shoes)
    assert sorted(_ids(client, aid)) == sorted([bike, shoes])  # other kinds are kept
    svc["assign"](aid, other_bike)
    assert sorted(_ids(client, aid)) == sorted([other_bike, shoes])  # same kind replaced
    assert client.get(f"{API}/activity/{aid}").json()["manual"] is True


def test_unassigned_list_and_batch_assign(make_client):
    client = make_client(modules="gear")
    run = upload(client, "run.gpx", to_gpx(synthetic_track()))
    ride = upload(client, "ride.gpx", to_gpx(synthetic_track(start=START.replace(day=2)), sport="cycling"))
    assert client.get(f"{API}/gear").json()["no_gear"] == 2
    rows = client.get(f"{API}/unassigned").json()
    assert [r["id"] for r in rows] == [ride, run]  # newest first
    assert {"name", "sport", "start_time", "distance_m"} <= set(rows[0])
    assert [r["id"] for r in client.get(f"{API}/unassigned", params={"sport": "cycling"}).json()] == [ride]

    shoes, other_shoes = _gear(client, "Pegasus", "shoes"), _gear(client, "Speedgoat", "shoes")
    bike = _gear(client, "Gravel", "bike")
    assert client.post(f"{API}/assign", json={"gear_id": shoes, "activity_ids": [run, ride, run]}).json() == {
        "updated": 2
    }
    assert client.get(f"{API}/unassigned").json() == []
    assert client.get(f"{API}/gear").json()["no_gear"] == 0
    client.post(f"{API}/assign", json={"gear_id": bike, "activity_ids": [ride]})
    client.post(f"{API}/assign", json={"gear_id": other_shoes, "activity_ids": [ride]})
    assert sorted(_ids(client, ride)) == sorted([bike, other_shoes])  # same kind replaced, bike kept
    assert client.get(f"{API}/activity/{run}").json()["manual"] is True

    assert client.post(f"{API}/assign", json={"gear_id": 999, "activity_ids": [run]}).status_code == 404
    assert client.post(f"{API}/assign", json={"gear_id": shoes, "activity_ids": [run, 999]}).status_code == 404
    assert client.post(f"{API}/assign", json={"gear_id": shoes, "activity_ids": []}).status_code == 422
