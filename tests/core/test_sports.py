"""Core: sport catalogue and sport-name normalisation."""

import pytest

from app.analytics import activity_to_columns, analyse
from app.parsers import parse_file
from tests.helpers import upload as _upload
from tests.samples import synthetic_track, to_fit, to_gpx


@pytest.mark.parametrize(
    "raw,sub,expected",
    [
        ("cycling", "road", "road_cycling"),  # FIT sport + sub_sport
        ("cycling", "mountain", "mountain_biking"),
        ("cycling", "gravel_cycling", "gravel_cycling"),
        ("cycling", "generic", "cycling"),
        ("e_biking", "e_bike_mountain", "mountain_biking"),
        ("alpine_skiing", "backcountry", "ski_touring"),
        ("alpine_skiing", "resort", "skiing"),
        ("running", "trail", "running"),
        ("sailing", "whitewater", "sailing"),  # sub-sport never switches sport family
        ("kayaking", None, "kayaking"),
        ("GravelRide", None, "gravel_cycling"),  # Strava activity types
        ("MountainBikeRide", None, "mountain_biking"),
        ("AlpineSki", None, "skiing"),
        ("BackcountrySki", None, "ski_touring"),
        ("Sail", None, "sailing"),
        ("Kayaking", None, "kayaking"),
        ("Hike", None, "hiking"),
        ("road_biking", None, "road_cycling"),  # Garmin names
        ("Biking", None, "cycling"),  # TCX
        ("cross_country_skiing", None, "cross_country_skiing"),  # unknown: kept
        ("", None, "unknown"),
    ],
)
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
    assert {
        "road_cycling",
        "gravel_cycling",
        "mountain_biking",
        "skiing",
        "ski_touring",
        "sailing",
        "kayaking",
        "hiking",
    } <= set(cat)
    assert cat["hiking"]["pace"] and not cat["sailing"]["pace"] and cat["gravel_cycling"]["cadence_unit"] == "rpm"
    assert client.get(f"/api/activities/{aid}").json()["sport"] == "ski_touring"
