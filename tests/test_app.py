import gzip

import pytest
from fastapi.testclient import TestClient

from app.analytics import activity_to_columns, analyse
from app.main import create_app
from app.parsers import ParseError, parse_file
from tests.samples import START, lap_track, synthetic_track, to_fit, to_gpx, to_tcx


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "test.db")))


# ----------------------------------------------------------------------------- parsers

@pytest.mark.parametrize("fname,builder,sport", [
    ("run.gpx", lambda: to_gpx(synthetic_track()), "running"),
    ("ride.tcx", lambda: to_tcx(synthetic_track(with_power=True)), "cycling"),
    ("run.fit", lambda: to_fit(synthetic_track(), sport=1), "running"),
    ("ride.fit", lambda: to_fit(synthetic_track(with_power=True), sport=2), "cycling"),
])
def test_parse_formats(fname, builder, sport):
    act = parse_file(fname, builder())
    assert len(act.points) == 1801
    assert act.sport == sport
    p = act.points[100]
    assert p.t is not None and p.hr == pytest.approx(123, abs=1)
    assert p.lat == pytest.approx(52.2297 + 300 / 111_195, abs=1e-5)
    assert p.ele == pytest.approx(100 + 20 * __import__("math").sin(0.3), abs=0.3)


def test_fit_channels_and_detection_without_extension():
    data = to_fit(synthetic_track(with_power=True), sport=2)
    act = parse_file("download", data)  # sniffed from the ".FIT" header
    assert act.source_format == "fit"
    p = act.points[10]
    assert p.power is not None and p.dist == pytest.approx(30.0)
    assert p.speed == pytest.approx(3.0)


def test_fit_missing_power_is_none():
    act = parse_file("run.fit", to_fit(synthetic_track()))
    assert all(p.power is None for p in act.points)


def test_gzip_fit():
    data = gzip.compress(to_fit(synthetic_track()))
    act = parse_file("run.fit.gz", data)
    assert act.source_format == "fit" and len(act.points) == 1801


def test_unsupported_file():
    with pytest.raises(ParseError):
        parse_file("notes.txt", b"hello")


# ----------------------------------------------------------------------------- analytics

def test_analytics_running():
    act = parse_file("run.gpx", to_gpx(synthetic_track()))
    r = analyse(activity_to_columns(act), act.sport, {"max_hr": 190, "rest_hr": 60})
    s = r["summary"]
    assert s["distance_m"] == pytest.approx(5220, rel=0.005)
    assert s["elapsed_s"] == 1800
    assert s["moving_s"] == pytest.approx(1740, abs=2)  # 60 s pause excluded
    assert s["avg_speed_ms"] == pytest.approx(3.0, rel=0.01)
    assert s["elev_gain_m"] == pytest.approx(22.6, abs=2)
    assert s["elev_loss_m"] == pytest.approx(40, abs=2)
    assert s["avg_hr"] > 120 and s["max_hr"] == 170
    assert len(r["splits"]) == 6  # 5 full km + remainder
    assert r["splits"][0]["moving_s"] == pytest.approx(333.3, abs=1)
    efforts = {e["distance_m"]: e["time_s"] for e in r["best_efforts"]}
    assert efforts[1000] == pytest.approx(333.3, abs=1)
    assert sum(z["time_s"] for z in r["hr_zones"]) == pytest.approx(1800, abs=2)
    assert r["track"] and len(r["series"]["distance_m"]) <= 1500


def test_analytics_power():
    act = parse_file("ride.fit", to_fit(synthetic_track(with_power=True), sport=2))
    r = analyse(activity_to_columns(act), act.sport, {"ftp": 250})
    s = r["summary"]
    assert 195 < s["avg_power"] < 210
    assert s["normalized_power"] >= s["avg_power"]
    assert s["intensity_factor"] == pytest.approx(s["normalized_power"] / 250, abs=0.01)
    assert s["tss"] > 0 and s["work_kj"] > 300
    curve = {p["duration_s"]: p["value"] for p in r["power_curve"]}
    assert curve[5] >= curve[60] >= curve[1200]


def test_analytics_without_gps_or_time():
    cols = {"t": [None] * 3, "lat": [None] * 3, "lon": [None] * 3, "ele": [1, 2, 3]}
    r = analyse(cols)
    assert r["summary"]["has_time"] is False and r["track"] is None


# ----------------------------------------------------------------------------- API

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


# ----------------------------------------------------------------------------- trim / export / clip

def _upload(client, fname, data):
    return client.post("/api/activities", files=[("files", (fname, data, "x"))]).json()["imported"][0]["id"]


def test_trimmed_view_is_temporary(client):
    aid = _upload(client, "ride.fit", to_fit(synthetic_track(with_power=True), sport=2))
    full = client.get(f"/api/activities/{aid}").json()
    assert full["window"] is None and full["series"]["idx"][0] == 0

    view = client.get(f"/api/activities/{aid}?start=700&end=1300").json()
    assert view["window"] == {"start": 700, "end": 1300, "total_points": 1801}
    assert view["summary"]["elapsed_s"] == 600
    assert view["summary"]["distance_m"] == pytest.approx(1800, abs=5)  # no pause in 700..1300
    assert view["series"]["idx"][0] == 700 and view["series"]["idx"][-1] == 1300
    assert view["summary"]["start_time"] > full["summary"]["start_time"]

    # stored activity untouched
    again = client.get(f"/api/activities/{aid}").json()
    assert again["summary"]["elapsed_s"] == 1800
    assert client.get(f"/api/activities/{aid}?start=900&end=100").status_code == 422
    assert client.get(f"/api/activities/{aid}?start=0&end=99999").status_code == 422


@pytest.mark.parametrize("fmt", ["gpx", "tcx", "fit"])
def test_export_roundtrip(client, fmt):
    aid = _upload(client, "ride.fit", to_fit(synthetic_track(with_power=True), sport=2))
    r = client.get(f"/api/activities/{aid}/export?format={fmt}&start=700&end=1300")
    assert r.status_code == 200
    assert f".{fmt}" in r.headers["content-disposition"]
    act = parse_file(f"x.{fmt}", r.content)
    assert len(act.points) == 601
    assert act.sport == "cycling"
    assert act.points[0].power is not None and act.points[0].hr is not None
    res = analyse(activity_to_columns(act), act.sport)
    assert res["summary"]["elapsed_s"] == 600
    assert res["summary"]["distance_m"] == pytest.approx(1800, abs=5)

    # re-importing the exported file works and is a new activity
    assert _upload(client, f"trim.{fmt}", r.content) != aid


def test_export_full_fit_valid_crc(client):
    import fitdecode, io
    aid = _upload(client, "run.gpx", to_gpx(synthetic_track()))
    data = client.get(f"/api/activities/{aid}/export?format=fit").content
    names = []
    with fitdecode.FitReader(io.BytesIO(data), check_crc=fitdecode.CrcCheck.RAISE) as rd:
        names = [f.name for f in rd if isinstance(f, fitdecode.FitDataMessage)]
    assert {"file_id", "record", "lap", "session", "activity"} <= set(names)


def test_clip_creates_new_activity(client):
    aid = _upload(client, "run.gpx", to_gpx(synthetic_track()))
    r = client.post(f"/api/activities/{aid}/clip", json={"start": 0, "end": 599, "name": "First 10 min"})
    assert r.status_code == 201
    new_id = r.json()["id"]
    clip = client.get(f"/api/activities/{new_id}").json()
    assert clip["name"] == "First 10 min" and clip["summary"]["elapsed_s"] == 599
    assert client.post(f"/api/activities/{aid}/clip", json={"start": 0, "end": 599}).json()["duplicate"]
    assert client.post(f"/api/activities/{aid}/clip", json={}).status_code == 422
    assert len(client.get("/api/activities").json()) == 2


# ----------------------------------------------------------------------------- laps

def test_detect_laps_on_track():
    from app.laps import detect_laps
    act = parse_file("track.gpx", to_gpx(lap_track(laps=8)))
    det = detect_laps(activity_to_columns(act))
    assert det["count"] == 8
    assert det["lap_distance_m"] == pytest.approx(400, rel=0.03)
    # warm-up (600 m at 3 m/s = 200 s) and cool-down are excluded
    assert 185 <= det["start"] <= 205
    for a, b in zip(det["laps"], det["laps"][1:]):
        assert a["end"] == b["start"]


@pytest.mark.parametrize("pts", [synthetic_track(), lap_track(laps=1, cooldown=50)])
def test_no_laps_without_repeats(pts):
    from app.laps import detect_laps
    assert detect_laps(activity_to_columns(parse_file("x.gpx", to_gpx(pts)))) is None


def test_out_and_back_is_not_laps():
    from app.laps import detect_laps
    out = synthetic_track(seconds=600, pause=(0, 0))
    back = [{**p, "t": out[-1]["t"] + (p["t"] - out[0]["t"]) + __import__("datetime").timedelta(seconds=1)}
            for p in reversed(out)]
    for p, q in zip(back, reversed(out)):
        p["lat"] = q["lat"]
    assert detect_laps(activity_to_columns(parse_file("x.gpx", to_gpx(out + back)))) is None


def test_laps_api(client):
    speeds = [4.0, 4.4, 4.2, 4.1]
    aid = _upload(client, "track.gpx", to_gpx(lap_track(laps=4, lap_speeds=speeds)))
    detail = client.get(f"/api/activities/{aid}").json()
    assert detail["laps"]["count"] == 4
    # also present in trimmed views, with absolute indices
    view = client.get(f"/api/activities/{aid}?start={detail['laps']['start']}&end={detail['laps']['end']}").json()
    assert view["laps"] == detail["laps"] and view["window"]["start"] == detail["laps"]["start"]

    rep = client.get(f"/api/activities/{aid}/laps").json()
    assert len(rep["laps"]) == 4
    times = [l["elapsed_s"] for l in rep["laps"]]
    for t, sp in zip(times, speeds):
        assert t == pytest.approx(400 / sp, abs=4)
    assert rep["lap_time_stats"]["best_index"] == 2 and rep["lap_time_stats"]["worst_index"] == 1
    assert sum(l["delta_s"] for l in rep["laps"]) == pytest.approx(0, abs=0.5)
    assert rep["section"]["distance_m"] == pytest.approx(1600, rel=0.02)
    assert rep["whole"]["distance_m"] > rep["section"]["distance_m"]
    assert rep["laps"][0]["avg_hr"] > 140

    plain = _upload(client, "run.gpx", to_gpx(synthetic_track()))
    assert client.get(f"/api/activities/{plain}").json()["laps"] is None
    assert client.get(f"/api/activities/{plain}/laps").status_code == 404

# ----------------------------------------------------------------------------- segments

def _cols(pts):
    return activity_to_columns(parse_file("x.gpx", to_gpx(pts)))


def test_segment_matches_same_route_only_forward_and_on_course():
    from datetime import timedelta
    from app.segments import build_segment, find_efforts
    base = synthetic_track(seconds=900, pause=(0, 0))            # 2.7 km north
    seg = build_segment(_cols(base), 100, 500)                    # 1.2 km in the middle
    assert seg["distance_m"] == pytest.approx(1200, abs=5)

    later = [{**p, "t": p["t"] + timedelta(days=3)} for p in base]
    assert find_efforts(seg, _cols(later)) == [(100, 500)]

    back = list(reversed(base))                                   # same road, other direction
    for k, p in enumerate(back):
        p = back[k] = {**p, "t": base[k]["t"]}
    assert find_efforts(seg, _cols(back)) == []

    detour = [dict(p) for p in base]                              # leaves the road for 300 m
    for p in detour[250:350]:
        p["lon"] += 0.003
    assert find_efforts(seg, _cols(detour)) == []

    assert find_efforts(seg, _cols(lap_track())) == []            # somewhere else entirely


def test_segment_from_lap_matches_every_lap():
    from app.laps import detect_laps
    from app.segments import build_segment, find_efforts
    cols = _cols(lap_track(laps=6))
    lap = detect_laps(cols)["laps"][1]
    seg = build_segment(cols, lap["start"], lap["end"])
    assert len(find_efforts(seg, cols)) == 6


def test_segments_api(client):
    a1 = _upload(client, "a.gpx", to_gpx(lap_track(laps=4, lap_speeds=[4.0, 4.4, 4.2, 4.1])))
    lap = client.get(f"/api/activities/{a1}").json()["laps"]
    det = client.get(f"/api/activities/{a1}/laps").json()["laps"][0]

    r = client.post("/api/segments", json={"activity_id": a1, "start": det["start"], "end": det["end"], "name": "Track lap"})
    assert r.status_code == 201
    seg = r.json()
    assert seg["name"] == "Track lap" and len(seg["efforts"]) == lap["count"]
    times = [e["elapsed_s"] for e in seg["efforts"]]
    assert times == sorted(times) and seg["efforts"][0]["rank"] == 1
    assert seg["efforts"][0]["elapsed_s"] == pytest.approx(400 / 4.4, abs=4)

    # a later upload on the same track is matched automatically
    a2 = _upload(client, "b.gpx", to_gpx(lap_track(laps=3, lap_speeds=[4.6, 4.6, 4.6], seed=3, start=START.replace(day=8))))
    seg = client.get(f"/api/segments/{seg['id']}").json()
    assert len(seg["efforts"]) == lap["count"] + 3
    assert seg["efforts"][0]["activity_id"] == a2                  # new best time
    assert [a["activity_id"] for a in seg["activities"]] == [a2, a1]  # newest first
    assert seg["activities"][1]["efforts"] == lap["count"]

    # the activity side lists its efforts with their rank
    mine = client.get(f"/api/activities/{a1}").json()["segment_efforts"]
    assert len(mine) == lap["count"] and all(e["segment_name"] == "Track lap" for e in mine)
    assert mine == sorted(mine, key=lambda e: e["start"]) and mine[0]["of"] == lap["count"] + 3

    listed = client.get("/api/segments").json()
    assert listed[0]["effort_count"] == lap["count"] + 3 and listed[0]["activity_count"] == 2 and "points" not in listed[0]

    assert client.patch(f"/api/segments/{seg['id']}", json={"name": "Oval"}).json()["name"] == "Oval"
    assert client.delete(f"/api/activities/{a2}").status_code == 204   # efforts go with the activity
    assert len(client.get(f"/api/segments/{seg['id']}").json()["efforts"]) == lap["count"]
    assert len(client.post(f"/api/segments/{seg['id']}/rescan").json()["efforts"]) == lap["count"]
    assert client.post("/api/segments", json={"activity_id": a1, "start": 10, "end": 20}).status_code == 422  # too short
    assert client.delete(f"/api/segments/{seg['id']}").status_code == 204
    assert client.get(f"/api/activities/{a1}").json()["segment_efforts"] == []


def test_long_segment_matches_itself():
    # Regression: long segments were compared at a fixed 200 points (~200 m apart on a
    # 40 km route), so even the activity a segment was cut from did not match it.
    from app.segments import build_segment, find_efforts
    cols = _cols(synthetic_track(seconds=5000, speed=8.0, pause=(0, 0)))  # 40 km
    seg = build_segment(cols, 0, 5000)
    assert find_efforts(seg, cols) == [(0, 5000)]


# ----------------------------------------------------------------------------- sports

@pytest.mark.parametrize("raw,sub,expected", [
    ("cycling", "road", "road_cycling"),            # FIT sport + sub_sport
    ("cycling", "mountain", "mountain_biking"),
    ("cycling", "gravel_cycling", "gravel_cycling"),
    ("cycling", "generic", "cycling"),
    ("e_biking", "e_bike_mountain", "mountain_biking"),
    ("alpine_skiing", "backcountry", "ski_touring"),
    ("alpine_skiing", "resort", "skiing"),
    ("running", "trail", "running"),
    ("sailing", "whitewater", "sailing"),           # sub-sport never switches sport family
    ("kayaking", None, "kayaking"),
    ("GravelRide", None, "gravel_cycling"),         # Strava activity types
    ("MountainBikeRide", None, "mountain_biking"),
    ("AlpineSki", None, "skiing"),
    ("BackcountrySki", None, "ski_touring"),
    ("Sail", None, "sailing"),
    ("Kayaking", None, "kayaking"),
    ("Hike", None, "hiking"),
    ("road_biking", None, "road_cycling"),          # Garmin names
    ("Biking", None, "cycling"),                    # TCX
    ("cross_country_skiing", None, "cross_country_skiing"),  # unknown: kept
    ("", None, "unknown"),
])
def test_sport_normalisation(raw, sub, expected):
    from app.sports import normalise
    assert normalise(raw, sub) == expected


def test_every_catalogue_key_is_stable():
    from app.sports import SPORTS, normalise
    for key in SPORTS:
        assert normalise(key) == key  # what the UI sends back on PATCH


def test_fit_sub_sport_and_export_roundtrip(client):
    act = parse_file("mtb.fit", to_fit(synthetic_track(), sport=2, sub_sport=8))
    assert act.sport == "mountain_biking"
    aid = _upload(client, "mtb.fit", to_fit(synthetic_track(), sport=2, sub_sport=8))
    for fmt, expected in [("fit", "mountain_biking"), ("gpx", "mountain_biking"), ("tcx", "cycling")]:
        data = client.get(f"/api/activities/{aid}/export?format={fmt}").content
        assert parse_file(f"x.{fmt}", data).sport == expected, fmt
    # skiing family: ski touring counts slow uphill as moving, downhill skiing does not
    client.patch(f"/api/activities/{aid}", json={"sport": "ski_touring"})
    slow = activity_to_columns(parse_file("x.gpx", to_gpx(synthetic_track(speed=0.5, pause=(0, 0)))))
    assert analyse(slow, "ski_touring")["summary"]["moving_s"] > 1700
    assert analyse(slow, "skiing")["summary"]["moving_s"] == 0
    cat = {s["key"]: s for s in client.get("/api/sports").json()}
    assert {"road_cycling", "gravel_cycling", "mountain_biking", "skiing", "ski_touring", "sailing", "kayaking", "hiking"} <= set(cat)
    assert cat["hiking"]["pace"] and not cat["sailing"]["pace"] and cat["gravel_cycling"]["cadence_unit"] == "rpm"
    assert client.get(f"/api/activities/{aid}").json()["sport"] == "ski_touring"
