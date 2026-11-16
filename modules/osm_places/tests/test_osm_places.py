"""Tests for the osm_places service module. Run: python -m pytest modules/osm_places -q

Never reaches the real Overpass API: a local fake server answers instead."""

import http.server
import json
import threading
from urllib.parse import parse_qs

import pytest

from app.sdk import Invalid


class FakeOverpass:
    """A local stand-in for the Overpass API: records queries, answers with canned elements."""

    def __init__(self, elements, status=200):
        self.queries: list[str] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                fake.queries.append(parse_qs(body)["data"][0])
                data = json.dumps({"elements": elements}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/interpreter"


PARK = {
    "type": "area",
    "id": 1,
    "tags": {"name": "Kampinoski PN", "name:en": "Kampinos NP", "boundary": "national_park"},
}
PARK_NEAR = {
    "type": "relation",
    "id": 2,
    "center": {"lat": 52.4, "lon": 21.0},
    "tags": {"name": "Far Park", "boundary": "protected_area", "protect_class": "2"},
}
RANGE_NEAR = {
    "type": "way",
    "id": 3,
    "center": {"lat": 52.3, "lon": 21.0},
    "tags": {"name": "Pasmo", "natural": "mountain_range"},
}
RANGE_FAR = {
    "type": "node",
    "id": 4,
    "lat": 52.6,
    "lon": 21.0,
    "tags": {"name": "Far Range", "natural": "mountain_range"},
}
CITY = {"type": "node", "id": 5, "lat": 52.26, "lon": 21.01, "tags": {"name": "Warszawa", "place": "city"}}
VILLAGE = {"type": "node", "id": 6, "lat": 52.25, "lon": 21.012, "tags": {"name": "Wieś", "place": "village"}}


def services(client):
    return client.app.state.module_services["osm_places"]


def test_place_finds_park_range_and_town(make_client, monkeypatch):
    fake = FakeOverpass([PARK, RANGE_NEAR, RANGE_FAR, CITY, VILLAGE])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake.url)
    client = make_client(modules="osm_places")
    p = services(client)["place"](52.23456, 21.01234)
    assert p["point"] == [52.235, 21.012]  # rounded before it was sent
    assert "is_in(52.235,21.012)" in fake.queries[0] and "52.23456" not in fake.queries[0]
    assert p["park"] == {"name": "Kampinos NP", "inside": True, "distance_m": 0.0, "kind": None}
    assert p["range"]["name"] == "Pasmo" and not p["range"]["inside"]  # the nearer range
    assert p["city"]["name"] == "Warszawa" and p["city"]["kind"] == "city"  # a city beats a closer village
    assert p["source"] == "openstreetmap" and p["fetched_at"]


def test_nearest_park_and_village_fallback(make_client, monkeypatch):
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", FakeOverpass([PARK_NEAR, VILLAGE]).url)
    client = make_client(modules="osm_places")
    p = services(client)["place"](52.23, 21.01)
    assert p["park"]["name"] == "Far Park" and not p["park"]["inside"] and p["park"]["distance_m"] > 10_000
    assert p["range"] is None and p["city"]["name"] == "Wieś" and p["city"]["kind"] == "village"


def test_answers_are_stored_per_rounded_point(make_client, monkeypatch):
    fake = FakeOverpass([CITY])
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", fake.url)
    client = make_client(modules="osm_places")
    place = services(client)["place"]
    first = place(52.2301, 21.0101)
    assert place(52.2299, 21.0099) == first  # same rounded point: no second request
    assert len(fake.queries) == 1
    place(52.23, 21.01, refresh=True)
    assert len(fake.queries) == 2


def test_errors(make_client, monkeypatch):
    client = make_client(modules="osm_places")
    place = services(client)["place"]
    with pytest.raises(Invalid):
        place("north", 21.0)
    with pytest.raises(Invalid):
        place(95.0, 21.0)
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", "http://127.0.0.1:9/nothing-listens-here")
    with pytest.raises(Invalid, match="OpenStreetMap lookup failed"):
        place(52.0, 21.0)
    monkeypatch.setenv("FITPUSH_OVERPASS_URL", FakeOverpass([], status=500).url)
    with pytest.raises(Invalid):
        place(52.0, 21.0)


def test_service_module_contract(make_client):
    client = make_client(modules="osm_places")
    mod = next(m for m in client.get("/api/modules").json() if m["id"] == "osm_places")
    assert mod["status"] == "loaded" and mod["services"] == {"place": "1.0", "about": "1.0"}
    assert not mod["frontend"]  # a service module has no UI
    assert client.app.state.module_service_versions["osm_places"] == {"place": "1.0", "about": "1.0"}
    about = services(client)["about"]()
    assert about["rounding_decimals"] == 3 and "100 m" in about["sends"]
    assert client.get("/m/osm_places/frontend.js").status_code == 404
