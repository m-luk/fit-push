"""Strava import (backend): bring a Strava data export (zip) into fit-push.

Endpoints (under /api/m/strava_import):
    POST /import            multipart: file (zip) + options; returns a report (dry_run: no writes)
    GET  /activity/{id}     Strava data stored for one activity (null when none)
"""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import File, Form, UploadFile

from app.sdk import Invalid, ModuleContext

MAX_FILE = 200 * 1024 * 1024  # largest single entry we read from the zip (zip bombs)
MATCH_S = 60  # same activity when the start times differ by at most this

# Strava activity type (squashed: lower case, no spaces/dashes) -> sport key. English and
# Polish names; Strava localises the type column to the account language.
TYPES = {
    "ride": "cycling",
    "jazda": "cycling",
    "ebikeride": "cycling",
    "jazdanarowerzeelektrycznym": "cycling",
    "virtualride": "cycling",
    "jazdawirtualna": "cycling",
    "velomobile": "cycling",
    "handcycle": "cycling",
    "mountainbikeride": "mountain_biking",
    "jazdanarowerzegórskim": "mountain_biking",
    "emountainbikeride": "mountain_biking",
    "jazdanaelektrycznymrowerzegórskim": "mountain_biking",
    "gravelride": "gravel_cycling",
    "jazdanarowerzegravelowym": "gravel_cycling",
    "run": "running",
    "bieganie": "running",
    "trailrun": "running",
    "biegterenowy": "running",
    "virtualrun": "running",
    "biegwirtualny": "running",
    "walk": "walking",
    "spacer": "walking",
    "hike": "hiking",
    "wędrówka": "hiking",
    "snowshoe": "hiking",
    "rakietyśnieżne": "hiking",
    "alpineski": "skiing",
    "narciarstwoalpejskie": "skiing",
    "nordicski": "skiing",
    "narciarstwobiegowe": "skiing",
    "snowboard": "skiing",
    "backcountryski": "ski_touring",
    "narciarstwoskiturowe": "ski_touring",
    "kayaking": "kayaking",
    "kajakarstwo": "kayaking",
    "canoe": "kayaking",
    "canoeing": "kayaking",
    "kajakarstwokanadyjskie": "kayaking",
    "rowing": "rowing",
    "wioślarstwo": "rowing",
    "sail": "sailing",
    "żeglarstwo": "sailing",
    "swim": "swimming",
    "pływanie": "swimming",
    "workout": "training",
    "trening": "training",
    "weighttraining": "training",
    "treningsiłowy": "training",
}
GENERIC = {"cycling"}  # never replaces a more specific sport of the same group


def squash(text: str) -> str:
    return re.sub(r"[\s_-]+", "", text.strip().lower())


def norm(text: str) -> str:
    return " ".join(text.split()).lower()


def read_csv(zf: zipfile.ZipFile, name: str | None) -> list[list[str]]:
    if name is None:
        return []
    with zf.open(name) as f:
        return list(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))


def register(ctx: ModuleContext) -> None:
    acts_t = ctx.db.table("activities")
    ctx.db.script(f"""
        CREATE TABLE IF NOT EXISTS {acts_t} (
            activity_id INTEGER PRIMARY KEY, strava_id TEXT NOT NULL, strava_type TEXT NOT NULL DEFAULT '',
            gear TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            private_note TEXT NOT NULL DEFAULT '', imported_at TEXT NOT NULL)
    """)

    def on_deleted(activity_id: int) -> None:
        ctx.db.execute(f"DELETE FROM {acts_t} WHERE activity_id = ?", (activity_id,))

    ctx.on("activity.deleted", on_deleted)

    @ctx.router.get("/activity/{activity_id}")
    def get_activity(activity_id: int) -> dict | None:
        """The Strava data of an activity, or null when it has none (404 for unknown ids)."""
        ctx.core.activity(activity_id)
        rows = ctx.db.query(f"SELECT * FROM {acts_t} WHERE activity_id = ?", (activity_id,))
        return rows[0] if rows else None

    @ctx.router.post("/import")
    def import_export(
        file: Annotated[UploadFile, File()],
        dry_run: Annotated[bool, Form()] = False,
        import_new: Annotated[bool, Form()] = True,
        sport: Annotated[bool, Form()] = True,
        name: Annotated[bool, Form()] = True,
        gear: Annotated[bool, Form()] = True,
        commute: Annotated[bool, Form()] = True,
        notes: Annotated[bool, Form()] = True,
    ) -> dict:
        try:
            zf = zipfile.ZipFile(file.file)
        except zipfile.BadZipFile as exc:
            raise Invalid("not a zip file; upload the Strava export as downloaded") from exc
        with zf:
            return run_import(zf, dry_run, import_new, sport, name, gear, commute, notes)

    def gear_call(name: str, *args: object) -> Any:
        """Call a service of the Gear module (checked to be loaded before use)."""
        fn = ctx.service("gear", name)
        if fn is None:
            raise Invalid("Gear module not loaded")
        return fn(*args)

    # ---- the import --------------------------------------------------------------------
    def run_import(
        zf: zipfile.ZipFile,
        dry_run: bool,
        import_new: bool,
        do_sport: bool,
        do_name: bool,
        do_gear: bool,
        do_commute: bool,
        do_notes: bool,
    ) -> dict:
        entries = {i.filename: i for i in zf.infolist() if not i.is_dir()}
        csv_name = min((n for n in entries if posixpath.basename(n) == "activities.csv"), key=len, default=None)
        if csv_name is None:
            raise Invalid("activities.csv not found: is this a Strava data export?")
        root = posixpath.dirname(csv_name)

        def entry(rel: str) -> zipfile.ZipInfo | None:
            return entries.get(posixpath.join(root, rel)) if rel else None

        rows = read_csv(zf, csv_name)
        if len(rows) < 2 or len(rows[0]) < 13:
            raise Invalid("activities.csv has an unexpected layout")

        report: dict = {
            "dry_run": dry_run,
            "activities": len(rows) - 1,
            "matched": 0,
            "imported": 0,
            "no_file": 0,
            "updated": {"sport": 0, "name": 0, "gear": 0, "commute": 0, "notes": 0},
            "gear_items": [],
            "unmapped_types": {},
            "errors": [],
            "changes": [],
        }
        has_gear = do_gear and all(ctx.service("gear", k) for k in ("ensure", "assign", "add_defaults"))
        if do_gear and not has_gear:
            report["errors"].append("Gear module not loaded: gear was skipped")
        families = {s["key"]: s["family"] for s in ctx.core.sports()}

        def map_type(raw: str) -> str | None:
            key = TYPES.get(squash(raw))
            if key is None and raw.strip():
                report["unmapped_types"][raw] = report["unmapped_types"].get(raw, 0) + 1
            return key

        # gear catalogue: "<name>" and "<brand> <model> <name>" -> (name, kind, notes, sports)
        catalogue: dict[str, tuple[str, str, str, list[str]]] = {}
        for fname, kind in (("bikes.csv", "bike"), ("shoes.csv", "shoes")):
            for r in read_csv(zf, e.filename if (e := entry(fname)) else None)[1:]:
                if len(r) < 3 or not r[0].strip():
                    continue
                g_name, brand, model = (x.strip() for x in r[:3])
                sports = list(dict.fromkeys(k for t in (r[3] if len(r) > 3 else "").split("|") if (k := map_type(t))))
                item = (g_name, kind, " ".join(x for x in (brand, model) if x), sports)
                catalogue[norm(g_name)] = item
                catalogue[norm(f"{brand} {model} {g_name}")] = item

        gear_ids: dict[str, int] = {}

        def gear_id(label: str, sport_key: str) -> int | None:
            item = catalogue.get(norm(label))
            if item is None:  # gear missing from bikes/shoes.csv: guess the kind from the sport
                fam = families.get(sport_key, "other")
                kind = {"cycling": "bike", "running": "shoes", "foot": "shoes"}.get(fam, "other")
                item = (label.strip(), kind, "", [])
            g_name, kind, g_notes, sports = item
            if g_name not in gear_ids and not dry_run:
                gear_ids[g_name] = gear_call("ensure", g_name, kind, g_notes)
                added = gear_call("add_defaults", gear_ids[g_name], sports)
                report["gear_items"].append({"name": g_name, "kind": kind, "defaults": added})
            elif g_name not in gear_ids:
                gear_ids[g_name] = 0
                report["gear_items"].append({"name": g_name, "kind": kind, "defaults": sports})
            return gear_ids[g_name] or None

        existing = []
        for a in ctx.core.list_activities():
            if a["start_time"] and a.get("device") != "fit-push tutorial":
                existing.append((datetime.fromisoformat(a["start_time"]).timestamp(), a["id"]))
        existing.sort()
        stored = {r["activity_id"]: r for r in ctx.db.query(f"SELECT * FROM {acts_t}")}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        def by_start(start: str | None) -> int | None:
            if not start:
                return None
            ts = datetime.fromisoformat(start).timestamp()
            best = min(existing, key=lambda e: abs(e[0] - ts), default=None)
            return best[1] if best and abs(best[0] - ts) <= MATCH_S else None

        for r in rows[1:]:
            if len(r) < 13:
                continue
            strava_id, s_name, s_type, desc, is_commute, note, s_gear, rel = (
                r[0].strip(), r[2].strip(), r[3].strip(), r[4].strip(), r[9].strip().lower() == "true",
                r[10].strip(), r[11].strip(), r[12].strip(),
            )  # fmt: skip
            info = entry(rel)
            if info is None:
                report["no_file"] += 1
                continue
            change = {"strava_id": strava_id, "name": s_name, "activity_id": None, "changes": []}
            try:
                if info.file_size > MAX_FILE:
                    raise Invalid(f"{rel}: file too large")
                data = zf.read(info)
                fname = posixpath.basename(rel)
                peek = ctx.core.peek_file(fname, data)
                aid = peek["duplicate_of"] or by_start(peek["start_time"])
                if aid is None:
                    if not import_new:
                        continue
                    change["changes"].append("new activity")
                    report["imported"] += 1
                    if dry_run:
                        report["changes"].append(change)
                        continue
                    aid = ctx.core.import_file(fname, data)["id"]
                    if peek["start_time"]:
                        existing.append((datetime.fromisoformat(peek["start_time"]).timestamp(), aid))
                else:
                    report["matched"] += 1
                change["activity_id"] = aid
                act = ctx.core.activity(aid)

                target = map_type(s_type) if do_sport else None
                if target and target != act["sport"]:
                    keep = target in GENERIC and families.get(act["sport"]) == families.get(target)
                    if not keep:
                        change["changes"].append(f"sport: {act['sport']} → {target}")
                        report["updated"]["sport"] += 1
                        if not dry_run:
                            act = ctx.core.update_activity(aid, sport=target)
                if do_name and s_name and s_name != act["name"]:
                    change["changes"].append(f"name: {act['name']} → {s_name}")
                    report["updated"]["name"] += 1
                    if not dry_run:
                        ctx.core.update_activity(aid, name=s_name)
                if has_gear and s_gear:
                    gid = gear_id(s_gear, target or act["sport"])
                    change["changes"].append(f"gear: {s_gear}")
                    report["updated"]["gear"] += 1
                    if gid:
                        gear_call("assign", aid, gid)
                if do_commute and is_commute and "commute" not in act["tags"]:
                    change["changes"].append("tag: commute")
                    report["updated"]["commute"] += 1
                    if not dry_run:
                        ctx.core.set_tags(aid, [*act["tags"], "commute"])
                old = stored.get(aid)
                if do_notes and (old is None or (old["description"], old["private_note"]) != (desc, note)):
                    if desc or note:
                        change["changes"].append("description / note")
                        report["updated"]["notes"] += 1
                    if not dry_run:
                        ctx.db.execute(
                            f"INSERT OR REPLACE INTO {acts_t} (activity_id, strava_id, strava_type, gear, "
                            f"description, private_note, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (aid, strava_id, s_type, s_gear, desc, note, now),
                        )
            except Invalid as exc:
                report["errors"].append(f"{rel}: {exc}")
                continue
            if change["changes"]:
                report["changes"].append(change)
        return report
