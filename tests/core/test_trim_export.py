"""Core: temporary trimmed views, export to GPX/TCX/FIT, clips."""

import pytest

from app.analytics import activity_to_columns, analyse
from app.parsers import parse_file
from tests.helpers import upload as _upload
from tests.samples import synthetic_track, to_fit, to_gpx


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
    import io

    import fitdecode

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
