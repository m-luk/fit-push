"""Tests for the adventures module. Run: python -m pytest modules/adventures -q"""

import json
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


class FakeOverpass:
    """A local stand-in for the Overpass API: records queries, answers with canned elements."""

    def __init__(self, elements):
        import http.server
        import threading

        self.queries: list[str] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                from urllib.parse import parse_qs

                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                fake.queries.append(parse_qs(body)["data"][0])
                data = json.dumps({"elements": elements}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/interpreter"


PARK_INSIDE = {
    "type": "area",
    "id": 1,
    "tags": {"name": "Kampinoski Park Narodowy", "name:en": "Kampinos National Park", "boundary": "national_park"},
}
CITY = {"type": "node", "id": 2, "lat": 52.26, "lon": 21.01, "tags": {"name": "Warszawa", "place": "city"}}
VILLAGE = {"type": "node", "id": 3, "lat": 52.25, "lon": 21.012, "tags": {"name": "Wieś", "place": "village"}}
PARK_NEAR = {
    "type": "relation",
    "id": 4,
    "center": {"lat": 52.4, "lon": 21.0},
    "tags": {"name": "Far Park", "boundary": "protected_area", "protect_class": "2"},
}
RANGE_INSIDE = {"type": "area", "id": 5, "tags": {"name": "Pasmo", "natural": "mountain_range"}}
RANGE_NEAR = {
    "type": "node",
    "id": 6,
    "lat": 52.5,
    "lon": 21.0,
    "tags": {"name": "Far Range", "natural": "mountain_range"},
}
RANGE_NEARER = {
    "type": "way",
    "id": 7,
    "center": {"lat": 52.3, "lon": 21.0},
    "tags": {"name": "Near Range", "natural": "mountain_range"},
}


def test_place_lookup_names_the_trip(make_client, monkeypatch):
    fake = FakeOverpass([PARK_INSIDE, CITY, VILLAGE])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake.url)
    client = make_client(modules="adventures")
    ids = traverse(client)
    place = client.post(f"{API}/place", json={"activity_ids": ids}).json()
    assert place["name"] == "2026-11 Kampinos National Park, Warszawa"  # a city beats a closer village
    assert place["park"]["inside"] and place["city"]["name"] == "Warszawa"
    lat, lon = place["point"]
    assert (round(lat, 3), round(lon, 3)) == (lat, lon)  # only a rounded point leaves the machine
    assert len(fake.queries) == 1 and f"is_in({lat},{lon})" in fake.queries[0]
    adv = client.post(f"{API}/adventures", json={"name": place["name"], "activity_ids": ids, "place": place}).json()
    assert adv["place"]["park"]["name"] == "Kampinos National Park"
    assert client.post(f"{API}/adventures/{adv['id']}/place").json()["name"] == place["name"]


def test_place_lookup_nearest_park_and_switch_off(make_client, monkeypatch):
    fake = FakeOverpass([PARK_NEAR, VILLAGE])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake.url)
    client = make_client(modules="adventures")
    ids = traverse(client)
    place = client.post(f"{API}/place", json={"activity_ids": ids}).json()
    assert place["park"]["name"] == "Far Park" and not place["park"]["inside"] and place["park"]["distance_m"] > 1000
    assert place["name"] == "2026-11 Far Park, Wieś"
    client.put(f"{API}/settings", json={"osm_names": False})
    assert client.post(f"{API}/place", json={"activity_ids": ids}).status_code == 422
    assert len(fake.queries) == 1


def test_place_lookup_errors(make_client, monkeypatch):
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", "http://127.0.0.1:9/nothing-listens-here")
    client = make_client(modules="adventures")
    ids = traverse(client, days=(0, 1))
    r = client.post(f"{API}/place", json={"activity_ids": ids})
    assert r.status_code == 422 and "OpenStreetMap" in r.json()["detail"]
    assert client.post(f"{API}/place", json={"activity_ids": [9999]}).status_code == 422  # no GPS to look up


def test_suggestion_details_and_preview_tracks(make_client):
    client = make_client(modules="adventures")
    ids = traverse(client)
    s = client.get(f"{API}/suggestions").json()[0]
    assert [a["id"] for a in s["activities"]] == ids and s["activities"][0]["name"] == "Ride"
    lines = client.get(f"{API}/tracks?ids={','.join(map(str, ids))},9999,x").json()
    assert [t["id"] for t in lines] == ids and all(len(t["track"]) > 10 for t in lines)


def test_place_lookup_mountain_range(make_client, monkeypatch):
    fake = FakeOverpass([RANGE_NEAR, RANGE_NEARER, CITY])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake.url)
    client = make_client(modules="adventures")
    ids = traverse(client)
    place = client.post(f"{API}/place", json={"activity_ids": ids}).json()
    assert place["range"]["name"] == "Near Range" and not place["range"]["inside"] and place["park"] is None
    assert place["name"] == "2026-11 Near Range, Warszawa"  # without a park the range names the trip
    assert "natural=mountain_range" in fake.queries[0]
    fake2 = FakeOverpass([RANGE_INSIDE, PARK_INSIDE, CITY])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake2.url)
    place = client.post(f"{API}/place", json={"activity_ids": ids}).json()
    assert place["range"] == {"name": "Pasmo", "inside": True, "distance_m": 0.0}
    assert place["park"]["name"] == "Kampinos National Park"
    assert place["name"] == "2026-11 Kampinos National Park, Warszawa"  # a park beats the range
    adv = client.post(f"{API}/adventures", json={"name": "x", "activity_ids": ids, "place": place}).json()
    assert adv["place"]["range"]["name"] == "Pasmo"
