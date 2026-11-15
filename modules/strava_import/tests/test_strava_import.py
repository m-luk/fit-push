"""Tests for the strava_import module. Run: python -m pytest modules/strava_import -q"""

from __future__ import annotations

import csv
import gzip
import io
import zipfile
from datetime import timedelta

from tests.helpers import upload
from tests.samples import START, synthetic_track, to_fit, to_gpx

API = "/api/m/strava_import"
HEADER = [
    "Identyfikator aktywności", "Data aktywności", "Nazwa aktywności", "Rodzaj aktywności", "Opis aktywności",
    "Czas całkowity", "Dystans", "Maksymalne tętno", "Względny wysiłek", "Aktywność w ramach dojazdu",
    "Prywatna notatka dotycząca aktywności", "Sprzęt do aktywności fizycznej", "Nazwa pliku", "Waga sportowca",
]  # fmt: skip
DAY2, DAY3 = START + timedelta(days=1), START + timedelta(days=2)


def row(sid, name, typ, file, gear="", commute=False, desc="", note=""):
    return [sid, "1 lis 2026, 09:00:00", name, typ, desc, "1800", "5,4", "", "", str(commute).lower(), note, gear, file, ""]  # fmt: skip


def export(rows, root="export_1/") -> bytes:
    def table(header, body):
        out = io.StringIO()
        csv.writer(out).writerows([header, *body])
        return out.getvalue().encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(root + "activities.csv", table(HEADER, rows))
        z.writestr(
            root + "bikes.csv",
            table(
                ["Nazwa roweru", "Marka roweru", "Model roweru", "Domyślne rodzaje sportów dla rowerów"],
                [["Gejos", "Unibike", "Geos", "Jazda|Jazda na rowerze gravelowym"]],
            ),
        )
        z.writestr(
            root + "shoes.csv",
            table(
                ["Nazwa buta", "Marka buta", "Model buta", "Domyślne rodzaje sportów dla obuwia"],
                [["Zejściówki", "La Sportiva", "TX4 GTX", ""]],
            ),
        )
        z.writestr(root + "activities/1.fit.gz", gzip.compress(to_fit(synthetic_track(), sport=1)))
        z.writestr(root + "activities/2.gpx.gz", gzip.compress(to_gpx(synthetic_track(start=DAY2), sport="cycling")))
        z.writestr(root + "activities/3.gpx", to_gpx(synthetic_track(start=DAY3), name="Road", sport="road"))
        z.writestr(root + "media/photo.jpg", b"not read")
    return buf.getvalue()


ROWS = [
    row("101", "Na szczyt", "Wędrówka", "activities/1.fit.gz", "La Sportiva TX4 GTX Zejściówki", desc="Piękny dzień", note="kolano"),
    row("102", "Do pracy", "Jazda", "activities/2.gpx.gz", "Gejos", commute=True),
    row("103", "Szosa", "Jazda", "activities/3.gpx"),
    row("104", "Bez pliku", "Trening", ""),
    row("105", "Joga", "Joga", "activities/1.fit.gz"),
]  # fmt: skip


def send(client, data: bytes, **opts):
    form = {k: str(v).lower() for k, v in opts.items()}
    return client.post(f"{API}/import", files={"file": ("export.zip", data, "application/zip")}, data=form)


def by_name(client):
    return {a["name"]: a for a in client.get("/api/activities").json()}


def test_import_matches_updates_and_is_idempotent(make_client):
    client = make_client(modules="strava_import,gear")
    # The hike was uploaded before from the device as GPX (other bytes, same start time).
    hike_id = upload(client, "device.gpx", to_gpx(synthetic_track(), name="Run"))
    road_id = upload(client, "road.gpx", to_gpx(synthetic_track(start=DAY3), name="Road", sport="road"))

    preview = send(client, export(ROWS), dry_run=True).json()
    assert preview["dry_run"] and preview["matched"] == 3 and preview["imported"] == 1 and preview["no_file"] == 1
    assert len(client.get("/api/activities").json()) == 2  # nothing written
    assert client.get(f"{API}/activity/{hike_id}").json() is None

    r = send(client, export(ROWS)).json()
    assert (r["matched"], r["imported"], r["no_file"]) == (3, 1, 1)
    assert r["unmapped_types"] == {"Joga": 1}
    acts = by_name(client)
    assert set(acts) == {"Joga", "Do pracy", "Szosa"}  # row 105 (same file as 101) renamed it last
    hike = client.get(f"/api/activities/{hike_id}").json()
    assert hike["sport"] == "hiking" and hike["id"] == acts["Joga"]["id"]
    assert acts["Do pracy"]["sport"] == "cycling" and acts["Do pracy"]["tags"] == ["commute"]
    assert acts["Szosa"]["id"] == road_id and acts["Szosa"]["sport"] == "road_cycling"  # generic Ride kept road

    notes = client.get(f"{API}/activity/{hike_id}").json()
    assert notes["strava_id"] == "105" and notes["description"] == "" and notes["gear"] == ""

    gear = {g["name"]: g for g in client.get("/api/m/gear/gear").json()["gear"]}
    assert gear["Gejos"]["kind"] == "bike" and gear["Gejos"]["notes"] == "Unibike Geos"
    assert sorted(gear["Gejos"]["defaults"]) == ["sport:cycling", "sport:gravel_cycling"]
    assert gear["Zejściówki"]["kind"] == "shoes" and gear["Zejściówki"]["activities"] == 1
    ride = client.get(f"/api/m/gear/activity/{acts['Do pracy']['id']}").json()
    assert [g["name"] for g in ride["gear"]] == ["Gejos"] and ride["manual"]

    again = send(client, export(ROWS[:4])).json()
    assert again["imported"] == 0 and again["matched"] == 3
    assert again["updated"]["sport"] == 0 and again["updated"]["commute"] == 0
    assert again["updated"]["name"] == 1  # "Joga" -> "Na szczyt" (row 105 left out)
    assert client.get(f"{API}/activity/{hike_id}").json()["private_note"] == "kolano"
    assert len(client.get("/api/m/gear/gear").json()["gear"]) == 2

    client.delete(f"/api/activities/{hike_id}")
    assert client.get(f"{API}/activity/{hike_id}").status_code == 404


def test_options_and_without_gear_module(make_client):
    client = make_client(modules="strava_import")
    r = send(client, export(ROWS[1:3]), name=False, commute=False).json()
    assert r["imported"] == 2 and r["updated"]["name"] == 0 and r["updated"]["commute"] == 0
    assert any("Gear module" in e for e in r["errors"])
    assert all(not a["tags"] for a in client.get("/api/activities").json())
    assert send(client, export(ROWS[1:2]), import_new=False).json()["matched"] == 1


def test_bad_uploads(make_client):
    client = make_client(modules="strava_import")
    assert send(client, b"not a zip").status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    assert "activities.csv" in send(client, buf.getvalue()).json()["detail"]
    broken = [row("1", "x", "Jazda", "activities/bad.gpx")]
    data = io.BytesIO(export(broken))
    with zipfile.ZipFile(data, "a") as z:
        z.writestr("export_1/activities/bad.gpx", b"<gpx")
    r = send(client, data.getvalue()).json()
    assert r["errors"] and r["imported"] == 0
