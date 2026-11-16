"""Core: display preferences (map defaults, activity-page tiles per sport)."""


def test_defaults(client):
    p = client.get("/api/preferences").json()
    assert p == {"map_overlay": "none", "map_palette": "default", "map_reverse": False, "tiles": {}}


def test_map_defaults_are_saved(client):
    r = client.put("/api/preferences", json={"map_overlay": "speed", "map_palette": "turbo", "map_reverse": True})
    assert r.status_code == 200
    assert client.get("/api/preferences").json()["map_overlay"] == "speed"
    # a partial update keeps the other values
    p = client.put("/api/preferences", json={"map_palette": "viridis"}).json()
    assert p["map_overlay"] == "speed" and p["map_palette"] == "viridis" and p["map_reverse"] is True


def test_tiles_merge_per_sport_and_reset(client):
    client.put("/api/preferences", json={"tiles": {"running": ["distance", "avg_hr", "distance"]}})
    p = client.put("/api/preferences", json={"tiles": {"skiing": ["down_count"]}}).json()
    assert p["tiles"] == {"running": ["distance", "avg_hr"], "skiing": ["down_count"]}
    p = client.put("/api/preferences", json={"tiles": {"running": None}}).json()
    assert p["tiles"] == {"skiing": ["down_count"]}


def test_preferences_do_not_touch_athlete_settings(client):
    before = client.get("/api/settings").json()
    client.put("/api/preferences", json={"map_overlay": "hr"})
    assert client.get("/api/settings").json() == before


def test_invalid_keys_rejected(client):
    assert client.put("/api/preferences", json={"map_overlay": "<script>"}).status_code == 422
    assert client.put("/api/preferences", json={"tiles": {"running": ["Bad Key"]}}).status_code == 422


def test_sport_catalogue_has_default_tiles(client):
    sports = {s["key"]: s for s in client.get("/api/sports").json()}
    assert sports["skiing"]["tiles"][0] == "down_count"
    assert "up_time" in sports["ski_touring"]["tiles"]
    assert "avg_power" in sports["cycling"]["tiles"]
    assert sports["unknown"]["tiles"]  # generic list
