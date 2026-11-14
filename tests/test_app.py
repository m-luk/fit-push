import gzip

import pytest
from fastapi.testclient import TestClient

from app.analytics import activity_to_columns, analyse
from app.main import create_app
from app.parsers import ParseError, parse_file
from tests.samples import synthetic_track, to_fit, to_gpx, to_tcx


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
