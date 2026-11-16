"""Tests for the adventures module. Run: python -m pytest modules/adventures -q"""

from datetime import timedelta

from tests.helpers import upload
from tests.samples import M_PER_DEG_LAT, START, synthetic_track, to_gpx

API = "/api/m/adventures"
LEG_M = 3.0 * (1800 - 60)  # a synthetic_track goes 5220 m north


def act(client, day, north_m=0.0, east_deg=0.0, speed=3.0, hour=8, name="Ride"):
    """Upload a 30 min track heading north, starting ``north_m`` north of the sample origin on day ``day``."""
    pts = synthetic_track(speed=speed, start=START + timedelta(days=day, hours=hour - 8))
    for p in pts:
        p["lat"] += north_m / M_PER_DEG_LAT
        p["lon"] += east_deg
    return upload(client, f"{name}-{day}-{hour}-{north_m}-{east_deg}.gpx", to_gpx(pts, name=name))


def traverse(client, days=(0, 1, 2), east_deg=0.0):
    """Each day starts where the previous one ended (reached at 3 m/s)."""
    return [act(client, d, north_m=i * LEG_M, east_deg=east_deg) for i, d in enumerate(days)]


def test_detects_traverse_and_multiday(make_client):
    client = make_client(modules="adventures")
    trav = traverse(client)
    base = [act(client, d, east_deg=1.0) for d in (10, 11, 12)]  # same start, far from the traverse
    act(client, 30, east_deg=2.0)  # a lone activity is never an adventure
    got = {s["type"]: s for s in client.get(f"{API}/suggestions").json()}
    assert set(got) == {"traverse", "multiday"}
    assert got["traverse"]["activity_ids"] == trav and got["traverse"]["days"] == 3
    assert got["multiday"]["activity_ids"] == base
    assert got["traverse"]["key"] == ",".join(map(str, sorted(trav)))
    assert abs(got["traverse"]["distance_m"] - 3 * LEG_M) < 50


def test_gap_and_distance_limits(make_client):
    client = make_client(modules="adventures")
    a = act(client, 0)
    b = act(client, 2, north_m=LEG_M)  # one empty day in between: allowed by default
    act(client, 5, north_m=2 * LEG_M)  # two empty days: a new group
    far = act(client, 3, north_m=LEG_M + 25_000)  # starts 25 km from any end: not linked
    sugg = client.get(f"{API}/suggestions").json()
    assert [s["activity_ids"] for s in sugg] == [[a, b]]
    assert far not in sugg[0]["activity_ids"]
    # raise the limits: everything chains
    r = client.put(f"{API}/settings", json={"max_gap_days": 2, "traverse_max_m": 40_000})
    assert r.status_code == 200 and r.json()["max_gap_days"] == 2
    assert len(client.get(f"{API}/suggestions").json()[0]["activity_ids"]) == 4


def test_settings_filter_sports_and_tags(make_client):
    client = make_client(modules="adventures")
    ids = traverse(client)
    client.put(f"/api/activities/{ids[1]}/tags", json={"tags": ["Commute"]})
    s = client.get(f"{API}/settings").json()
    assert s["exclude_tags"] == ["commute"] and s["sports"] == [] and s["traverse_max_m"] == 10_000
    # the commute is skipped; the remaining days are 2 apart with one empty day between: still linked
    assert client.get(f"{API}/suggestions").json()[0]["activity_ids"] == [ids[0], ids[2]]
    client.put(f"{API}/settings", json={"exclude_tags": []})
    assert client.get(f"{API}/suggestions").json()[0]["activity_ids"] == ids
    client.put(f"{API}/settings", json={"exclude_tags": [], "sports": ["cycling"]})  # the tracks are runs
    assert client.get(f"{API}/suggestions").json() == []
    assert client.put(f"{API}/settings", json={"sports": ["nope"]}).status_code == 422
    assert client.put(f"{API}/settings", json={"max_gap_days": -1}).status_code == 422


def test_home_is_not_an_adventure(make_client):
    client = make_client(modules="adventures")
    for week in range(8):  # daily-ish training from home in 8 different weeks
        act(client, week * 7)
        act(client, week * 7 + 1)
    assert client.get(f"{API}/suggestions").json() == []
    client.put(f"{API}/settings", json={"home_weeks": 0})
    assert client.get(f"{API}/suggestions").json()  # with the home rule off they group again


def test_dismiss_and_reset(make_client):
    client = make_client(modules="adventures")
    traverse(client)
    key = client.get(f"{API}/suggestions").json()[0]["key"]
    assert client.post(f"{API}/suggestions/dismiss", json={"key": key}).status_code == 204
    assert client.get(f"{API}/suggestions").json() == []
    assert client.post(f"{API}/suggestions/reset").json() == {"restored": 1}
    assert len(client.get(f"{API}/suggestions").json()) == 1


def test_adventure_stats_and_crud(make_client):
    client = make_client(modules="adventures")
    ids = [act(client, 0, speed=3.0), act(client, 1, north_m=LEG_M, speed=4.0)]
    ids.append(act(client, 1, north_m=LEG_M * 2.33, speed=4.0, hour=14))  # second activity on day 2
    r = client.post(f"{API}/adventures", json={"name": " Coast ", "type": "traverse", "activity_ids": ids})
    assert r.status_code == 201
    adv = r.json()
    assert (adv["name"], adv["activities"], adv["days"], adv["span_days"]) == ("Coast", 3, 2, 2)
    assert [a["day"] for a in adv["activity_list"]] == [1, 2, 2]
    assert all(len(a["track"]) > 10 for a in adv["activity_list"])
    day1, day2 = adv["per_day"]
    assert day2["activities"] == 2 and day2["activity_ids"] == ids[1:]
    assert adv["fastest_day"] == day2["date"] and adv["slowest_day"] == day1["date"]
    assert adv["longest_day"] == day2["date"]
    assert abs(adv["avg_per_day"]["distance_m"] - adv["distance_m"] / 2) < 1e-6
    assert abs(adv["avg_per_activity"]["distance_m"] - adv["distance_m"] / 3) < 1e-6
    # members are no longer proposed
    assert client.get(f"{API}/suggestions").json() == []
    aid = adv["id"]
    assert client.get(f"{API}/adventures").json()[0]["id"] == aid
    assert (
        client.patch(f"{API}/adventures/{aid}", json={"type": "multiday", "notes": "windy"}).json()["type"]
        == "multiday"
    )
    assert client.put(f"{API}/adventures/{aid}/activities", json={"activity_ids": ids[:2]}).json()["activities"] == 2
    assert client.put(f"{API}/adventures/{aid}/activities", json={"activity_ids": [9999]}).status_code == 404
    assert client.post(f"{API}/adventures", json={"name": "x", "type": "loop"}).status_code == 422
    assert client.post(f"{API}/adventures", json={"name": "x", "activity_ids": [9999]}).status_code == 404
    assert len(client.get(f"{API}/adventures").json()) == 1  # the failed create left nothing behind
    on = client.get(f"{API}/activity/{ids[1]}").json()
    assert on[0]["id"] == aid and on[0]["day"] == 2
    picker = client.get(f"{API}/activities?from={day2['date']}").json()
    assert [a["id"] for a in picker] == ids[1:] and picker[0]["adventures"] == [aid]
    assert client.delete(f"{API}/adventures/{aid}").status_code == 204
    assert client.get(f"{API}/adventures/{aid}").status_code == 404


def test_activity_without_gps_or_deleted(make_client):
    client = make_client(modules="adventures")
    ids = traverse(client, days=(0, 1))
    t0 = START + timedelta(days=1, hours=5)
    pts = "".join(
        f"<Trackpoint><Time>{(t0 + timedelta(seconds=i)).strftime('%Y-%m-%dT%H:%M:%SZ')}</Time>"
        f"<DistanceMeters>{i * 3.0}</DistanceMeters></Trackpoint>"
        for i in range(0, 1800, 5)
    )
    tcx = (
        '<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="Running"><Id>{t0.isoformat()}</Id><Lap StartTime="{t0.isoformat()}">'
        f"<Track>{pts}</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
    )
    indoor = upload(client, "indoor.tcx", tcx.encode())
    adv = client.post(f"{API}/adventures", json={"name": "Trip", "activity_ids": [*ids, indoor]}).json()
    assert adv["activities"] == 3 and next(a for a in adv["activity_list"] if a["id"] == indoor)["track"] == []
    client.delete(f"/api/activities/{ids[0]}")
    assert client.get(f"{API}/adventures/{adv['id']}").json()["activities"] == 2
    for aid in (ids[1], indoor):
        client.delete(f"/api/activities/{aid}")
    assert client.get(f"{API}/adventures/{adv['id']}").status_code == 404  # empty adventures go away


def test_module_is_isolated(make_client):
    assert make_client(modules="none").get(f"{API}/adventures").status_code == 404
    client = make_client(modules="adventures")
    status = {m["id"]: m["status"] for m in client.get("/api/modules").json()}
    assert status["adventures"] == "loaded"
    assert client.get("/m/adventures/frontend.js").status_code == 200
