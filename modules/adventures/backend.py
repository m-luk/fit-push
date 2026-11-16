"""Adventures (backend): group activities into traverses and multi-day trips, detect them.

Endpoints (under /api/m/adventures): see README.md, "How it works".
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel, Field

from app.sdk import Invalid, ModuleContext, NotFound

TYPES = ("traverse", "multiday")
TYPE_LABEL = {"traverse": "Traverse", "multiday": "Multi-day"}
P2P_SHARE = 0.5  # traverse: at least this share of activities must end away from where they started


def classify(starts: list, ends: list, link_m: float, radius_m: float) -> tuple[str, float]:
    """Traverse when the activities (in time order) form one continuous line that goes
    somewhere: every start lies within ``link_m`` of the previous end, and at least half of
    the activities are point-to-point (end more than ``radius_m`` from their start).
    Anything else is multi-day. Returns the type and the largest gap between tracks."""
    gaps = [haversine(e, s) for e, s in zip(ends, starts[1:], strict=False)]
    p2p = sum(haversine(s, e) > radius_m for s, e in zip(starts, ends, strict=True))
    biggest = max(gaps, default=0.0)
    traverse = len(starts) >= 2 and biggest <= link_m and p2p >= P2P_SHARE * len(starts)
    return ("traverse" if traverse else "multiday"), biggest


DEFAULTS: dict = {
    "sports": [],  # empty: any sport, mixed adventures allowed
    "exclude_tags": ["commute"],
    "max_gap_days": 1,  # calendar days without activity allowed between two days of one adventure
    "traverse_link_m": 1_000.0,  # traverse: each start within this distance of the previous end
    "area_radius_m": 20_000.0,  # grouping: a start within this distance of a start or end of the trip so far
    "base_radius_m": 2_000.0,  # one spot: a loop ends this close to its start; home spots have this size
    "min_days": 2,
    "home_weeks": 15,  # a spot with starts in this many different weeks is "home"; 0 = off
    "home_radius_m": 10_000.0,  # activities starting and ending this close to home are everyday training
}


class SettingsIn(BaseModel):
    sports: list[str] = Field(default_factory=list, max_length=100)
    exclude_tags: list[str] = Field(default_factory=list, max_length=100)
    max_gap_days: int = Field(default=1, ge=0, le=30)
    traverse_link_m: float = Field(default=1_000.0, ge=50, le=50_000)
    area_radius_m: float = Field(default=20_000.0, ge=100, le=200_000)
    base_radius_m: float = Field(default=2_000.0, gt=0, le=100_000)
    min_days: int = Field(default=2, ge=1, le=60)
    home_weeks: int = Field(default=15, ge=0, le=1000)
    home_radius_m: float = Field(default=10_000.0, ge=0, le=100_000)


class AdventureIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["traverse", "multiday"] = "traverse"
    activity_ids: list[int] = Field(default_factory=list, max_length=1000)


class AdventurePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: Literal["traverse", "multiday"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class MembersIn(BaseModel):
    activity_ids: list[int] = Field(max_length=1000)


# Summary tiles of the adventure view. The frontend renders them; the backend keeps the
# choice: defaults per adventure type, optionally replaced for one adventure.
TILE_KEYS = (
    "distance", "moving", "elapsed", "elev_gain", "avg_speed", "avg_hr", "days", "span",
    "activities", "highest", "longest_day", "biggest_climb", "fastest_day", "slowest_day",
    "avg_day_distance", "avg_day_moving", "avg_day_elev", "avg_act_distance", "avg_act_moving",
)  # fmt: skip
DEFAULT_TILES = {
    "traverse": [
        "distance", "moving", "elev_gain", "avg_speed", "days", "activities", "highest",
        "longest_day", "biggest_climb", "fastest_day", "slowest_day", "avg_day_distance",
    ],
    "multiday": [
        "distance", "moving", "elev_gain", "days", "activities", "highest", "biggest_climb",
        "longest_day", "avg_day_distance", "avg_day_elev", "avg_act_distance",
    ],
}  # fmt: skip


class TilesIn(BaseModel):
    keys: list[str] | None = Field(default=None, max_length=len(TILE_KEYS))  # None: back to the defaults
    scope: Literal["adventure", "type"] = "adventure"


class KeyIn(BaseModel):
    key: str = Field(min_length=1, max_length=20_000)


def haversine(a: list[float], b: list[float]) -> float:
    """Distance in metres between two [lat, lon] points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(min(1.0, h)))


def day_of(start_time: str | None) -> date | None:
    try:
        return date.fromisoformat((start_time or "")[:10])
    except ValueError:
        return None


def stats(rows: list[dict]) -> dict:
    """Totals of activity-like rows (distance_m, moving_s, elapsed_s, elev_gain_m)."""
    dist = sum(r["distance_m"] for r in rows)
    moving = sum(r["moving_s"] for r in rows)
    return {
        "distance_m": dist,
        "moving_s": moving,
        "elapsed_s": sum(r["elapsed_s"] for r in rows),
        "elev_gain_m": sum(r["elev_gain_m"] for r in rows),
        "avg_speed_ms": dist / moving if moving > 0 else None,
    }


def avg_hr(rows: list[dict]) -> float | None:
    """Heart rate averaged over the activities that have one, weighted by moving time."""
    hr = [(r["avg_hr"], r["moving_s"]) for r in rows if r.get("avg_hr") and r["moving_s"] > 0]
    total = sum(t for _, t in hr)
    return sum(h * t for h, t in hr) / total if total else None


def register(ctx: ModuleContext) -> None:
    ctx.db.script(f"""
        CREATE TABLE IF NOT EXISTS {ctx.db.table("adventures")} (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("members")} (
            adventure_id INTEGER NOT NULL, activity_id INTEGER NOT NULL, PRIMARY KEY (adventure_id, activity_id));
        CREATE INDEX IF NOT EXISTS {ctx.db.table("members_act")} ON {ctx.db.table("members")} (activity_id);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("settings")} (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("dismissed")} (key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("tiles")} (adventure_id INTEGER PRIMARY KEY, keys TEXT NOT NULL)
    """)
    adv_t, mem_t = ctx.db.table("adventures"), ctx.db.table("members")
    set_t, dis_t, tiles_t = ctx.db.table("settings"), ctx.db.table("dismissed"), ctx.db.table("tiles")
    # Settings saved before the area rule (version 2) kept the old defaults; drop those so
    # the new defaults apply, but keep what the user chose differently.
    if not ctx.db.query(f"SELECT 1 FROM {set_t} WHERE key = 'settings_version'"):
        for key, old in (("home_weeks", "8"), ("traverse_max_m", None)):
            for r in ctx.db.query(f"SELECT value FROM {set_t} WHERE key = ?", (key,)):
                if old is None or r["value"] == old:
                    ctx.db.execute(f"DELETE FROM {set_t} WHERE key = ?", (key,))
        ctx.db.execute(f"INSERT INTO {set_t} (key, value) VALUES ('settings_version', '2')")

    ends_cache: dict[int, tuple[list[float], list[float]] | None] = {}  # id -> (start, end); points never change
    tracks: dict[int, list] = {}
    profiles: dict[int, dict] = {}  # id -> thinned line with values for colouring the map

    def on_deleted(activity_id: int) -> None:
        ends_cache.pop(activity_id, None)
        tracks.pop(activity_id, None)
        profiles.pop(activity_id, None)
        ctx.db.execute(f"DELETE FROM {mem_t} WHERE activity_id = ?", (activity_id,))
        ctx.db.execute(f"DELETE FROM {adv_t} WHERE id NOT IN (SELECT DISTINCT adventure_id FROM {mem_t})")
        ctx.db.execute(f"DELETE FROM {tiles_t} WHERE adventure_id NOT IN (SELECT id FROM {adv_t})")

    ctx.on("activity.deleted", on_deleted)

    # ---- helpers -------------------------------------------------------------------------
    def track(aid: int) -> list:
        if aid not in tracks:
            tracks[aid] = ctx.core.track(aid, step_m=25, max_points=500)
        return tracks[aid]

    def profile(aid: int, step_m: float = 25.0, max_points: int = 800) -> dict:
        """The GPS line thinned to ~``step_m`` with elevation, speed and heart rate per point
        (speed from the distance and time between kept points; None across pauses)."""
        if aid in profiles:
            return profiles[aid]
        c = ctx.core.points(aid)
        idx = [
            i for i, (la, lo) in enumerate(zip(c["lat"], c["lon"], strict=True)) if la is not None and lo is not None
        ]
        pts = [[c["lat"][i], c["lon"][i]] for i in idx]
        total = sum(haversine(a, b) for a, b in itertools.pairwise(pts))
        step = max(step_m, total / max_points)
        keep, run = [0] if idx else [], 0.0
        for k in range(1, len(idx)):
            run += haversine(pts[k - 1], pts[k])
            if run >= step or k == len(idx) - 1:
                keep.append(k)
                run = 0.0
        out: dict = {"track": [pts[k] for k in keep], "ele": [], "speed": [], "hr": []}
        for j, k in enumerate(keep):
            i = idx[k]
            out["ele"].append(c["ele"][i])
            out["hr"].append(c["hr"][i])
            speed = None
            if j and c["t"][i] is not None and c["t"][idx[keep[j - 1]]] is not None:
                dt = c["t"][i] - c["t"][idx[keep[j - 1]]]
                if 0 < dt <= 120:
                    speed = haversine(pts[keep[j - 1]], pts[k]) / dt
            out["speed"].append(speed)
        if len(out["speed"]) > 1:
            out["speed"][0] = out["speed"][1]
        profiles[aid] = out
        return out

    def ends(aid: int) -> tuple[list[float], list[float]] | None:
        if aid not in ends_cache:
            line = track(aid)
            ends_cache[aid] = (line[0], line[-1]) if len(line) >= 2 else None
        return ends_cache[aid]

    def type_tiles() -> dict[str, list[str]]:
        """Tile defaults per adventure type: the user's choice, else the built-in ones."""
        rows = ctx.db.query(f"SELECT value FROM {set_t} WHERE key = 'tiles'")
        saved = json.loads(rows[0]["value"]) if rows else {}
        return {t: saved.get(t) or list(DEFAULT_TILES[t]) for t in TYPES}

    def tiles_of(adv: dict) -> dict:
        """The tiles an adventure shows and where they come from (adventure / type / default)."""
        own = ctx.db.query(f"SELECT keys FROM {tiles_t} WHERE adventure_id = ?", (adv["id"],))
        if own:
            return {"keys": json.loads(own[0]["keys"]), "source": "adventure"}
        rows = ctx.db.query(f"SELECT value FROM {set_t} WHERE key = 'tiles'")
        saved = (json.loads(rows[0]["value"]) if rows else {}).get(adv["type"])
        return {"keys": saved or list(DEFAULT_TILES[adv["type"]]), "source": "type" if saved else "default"}

    def settings() -> dict:
        out = dict(DEFAULTS)
        for r in ctx.db.query(f"SELECT key, value FROM {set_t}"):
            if r["key"] in out:
                out[r["key"]] = json.loads(r["value"])
        return out

    def adventure(adv_id: int) -> dict:
        rows = ctx.db.query(f"SELECT * FROM {adv_t} WHERE id = ?", (adv_id,))
        if not rows:
            raise NotFound(f"adventure {adv_id} not found")
        return rows[0]

    def member_ids(adv_id: int) -> list[int]:
        return [
            r["activity_id"] for r in ctx.db.query(f"SELECT activity_id FROM {mem_t} WHERE adventure_id = ?", (adv_id,))
        ]

    def set_members(adv_id: int, ids: list[int]) -> None:
        known = {a["id"] for a in ctx.core.list_activities()}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise NotFound(f"activities not found: {', '.join(map(str, unknown[:10]))}")
        ctx.db.execute(f"DELETE FROM {mem_t} WHERE adventure_id = ?", (adv_id,))
        for aid in dict.fromkeys(ids):
            ctx.db.execute(f"INSERT INTO {mem_t} (adventure_id, activity_id) VALUES (?, ?)", (adv_id, aid))

    def row(a: dict) -> dict:
        s = a["summary"] or {}
        return {
            "id": a["id"],
            "name": a["name"],
            "sport": a["sport"],
            "start_time": a["start_time"],
            "tags": a["tags"],
            "distance_m": float(s.get("distance_m") or 0),
            "moving_s": float(s.get("moving_s") or 0),
            "elapsed_s": float(s.get("elapsed_s") or 0),
            "elev_gain_m": float(s.get("elev_gain_m") or 0),
            "ele_max_m": s.get("ele_max_m"),
            "avg_hr": s.get("avg_hr"),
            "has_gps": bool(s.get("has_gps")),
        }

    def members(adv_id: int, acts: dict[int, dict]) -> list[dict]:
        rows = [row(acts[i]) for i in member_ids(adv_id) if i in acts]
        return sorted(rows, key=lambda r: r["start_time"] or "")

    def overview(adv: dict, rows: list[dict]) -> dict:
        days = sorted({d for r in rows if (d := day_of(r["start_time"]))})
        return {
            **adv,
            "activities": len(rows),
            "days": len(days),
            "first_day": days[0].isoformat() if days else None,
            "last_day": days[-1].isoformat() if days else None,
            "span_days": (days[-1] - days[0]).days + 1 if days else 0,
            "sports": sorted({r["sport"] for r in rows}),
            **stats(rows),
        }

    # ---- detection -----------------------------------------------------------------------
    def detect() -> list[dict]:
        cfg = settings()
        want_sports, skip_tags = set(cfg["sports"]), {t.lower() for t in cfg["exclude_tags"]}
        taken = {r["activity_id"] for r in ctx.db.query(f"SELECT DISTINCT activity_id FROM {mem_t}")}
        dismissed = {r["key"] for r in ctx.db.query(f"SELECT key FROM {dis_t}")}
        gps = [a for a in ctx.core.list_activities() if a["summary"].get("has_gps") and day_of(a["start_time"])]
        gps.sort(key=lambda a: a["start_time"])
        located = [(a, d, *e) for a in gps if (d := day_of(a["start_time"])) and (e := ends(a["id"]))]

        # home: places (clusters of starts) used in many different weeks, from every GPS activity
        radius = cfg["base_radius_m"]
        clusters: list[tuple[list[float], set]] = []
        for _, day, start, _ in located:
            week = day.isocalendar()[:2]
            hit = next((c for c in clusters if haversine(c[0], start) <= radius), None)
            (hit[1].add(week) if hit else clusters.append((start, {week})))
        homes = [c[0] for c in clusters if cfg["home_weeks"] and len(c[1]) >= cfg["home_weeks"]]

        def at_home(p: list[float]) -> bool:
            return any(haversine(h, p) <= cfg["home_radius_m"] for h in homes)

        groups: list[dict] = []
        cur: dict | None = None
        for a, day, start, end in located:
            if a["id"] in taken or (want_sports and a["sport"] not in want_sports):
                continue
            if skip_tags & {t.lower() for t in a["tags"]}:
                continue
            home_start = at_home(start)
            if home_start and at_home(end):  # everyday training near home ends any trip
                cur = None
                continue
            # joins: close in time, not from home, and starting at the previous end or in the
            # same area as the trip so far (neighbouring valleys, the next hut, the last camp);
            # a start near home that ends away can only begin a trip
            joins = (
                cur is not None
                and not home_start
                and (day - cur["last"]).days - 1 <= cfg["max_gap_days"]
                and (
                    haversine(cur["ends"][-1], start) <= cfg["traverse_link_m"]
                    or any(haversine(p, start) <= cfg["area_radius_m"] for p in cur["starts"] + cur["ends"])
                )
            )
            if not joins:
                cur = {"base": start, "acts": [], "starts": [], "ends": [], "days": set()}
                groups.append(cur)
            assert cur is not None
            cur["acts"].append(a)
            cur["starts"].append(start)
            cur["ends"].append(end)
            cur["days"].add(day)
            cur["last"] = day

        out = []
        for g in groups:
            ids = sorted(a["id"] for a in g["acts"])
            key = ",".join(map(str, ids))
            if len(ids) < 2 or len(g["days"]) < cfg["min_days"] or key in dismissed:
                continue
            kind, biggest_gap = classify(g["starts"], g["ends"], cfg["traverse_link_m"], radius)
            first, last = min(g["days"]).isoformat(), max(g["days"]).isoformat()
            rows = [row(a) for a in g["acts"]]
            out.append(
                {
                    "key": key,
                    "type": kind,
                    "name": f"{TYPE_LABEL[kind]} {first}" + (f" to {last}" if last != first else ""),
                    "activity_ids": [r["id"] for r in rows],
                    "first_day": first,
                    "last_day": last,
                    "days": len(g["days"]),
                    "max_gap_m": biggest_gap,
                    "sports": sorted({r["sport"] for r in rows}),
                    "distance_m": sum(r["distance_m"] for r in rows),
                    "moving_s": sum(r["moving_s"] for r in rows),
                    "activities": [
                        {k: r[k] for k in ("id", "name", "sport", "start_time", "distance_m")} for r in rows
                    ],
                }
            )
        return sorted(out, key=lambda s: s["first_day"], reverse=True)

    # ---- settings and suggestions --------------------------------------------------------
    @ctx.router.get("/settings")
    def get_settings() -> dict:
        return {**settings(), "defaults": DEFAULTS}

    @ctx.router.put("/settings")
    def put_settings(body: SettingsIn) -> dict:
        known = {s["key"] for s in ctx.core.sports()}
        bad = [s for s in body.sports if s not in known]
        if bad:
            raise Invalid(f"unknown sports: {', '.join(bad)}")
        values = body.model_dump()
        values["exclude_tags"] = sorted({t.strip().lstrip("#").lower() for t in body.exclude_tags if t.strip()})
        for key, value in values.items():
            ctx.db.execute(f"INSERT OR REPLACE INTO {set_t} (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        return get_settings()

    @ctx.router.get("/suggestions")
    def suggestions() -> list[dict]:
        return detect()

    @ctx.router.post("/suggestions/dismiss", status_code=204)
    def dismiss(body: KeyIn) -> None:
        ctx.db.execute(f"INSERT OR IGNORE INTO {dis_t} (key) VALUES (?)", (body.key,))

    @ctx.router.post("/suggestions/reset")
    def reset_dismissed() -> dict:
        n = len(ctx.db.query(f"SELECT key FROM {dis_t}"))
        ctx.db.execute(f"DELETE FROM {dis_t}")
        return {"restored": n}

    # ---- adventures ----------------------------------------------------------------------
    @ctx.router.get("/adventures")
    def list_adventures() -> list[dict]:
        acts = {a["id"]: a for a in ctx.core.list_activities()}
        out = [overview(adv, members(adv["id"], acts)) for adv in ctx.db.query(f"SELECT * FROM {adv_t}")]
        return sorted(out, key=lambda a: a["first_day"] or a["created_at"], reverse=True)

    @ctx.router.post("/adventures", status_code=201)
    def create(body: AdventureIn) -> dict:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        ctx.db.execute(
            f"INSERT INTO {adv_t} (name, type, created_at) VALUES (?, ?, ?)", (body.name.strip(), body.type, now)
        )
        adv_id = ctx.db.query(f"SELECT max(id) AS id FROM {adv_t}")[0]["id"]
        try:
            set_members(adv_id, body.activity_ids)
        except NotFound:
            ctx.db.execute(f"DELETE FROM {adv_t} WHERE id = ?", (adv_id,))
            raise
        return detail(adv_id)

    @ctx.router.get("/adventures/{adv_id}")
    def detail(adv_id: int) -> dict:
        adv = adventure(adv_id)
        rows = members(adv_id, {a["id"]: a for a in ctx.core.list_activities()})
        out = overview(adv, rows)
        first = day_of(out["first_day"])
        by_day: dict[str, list[dict]] = {}
        for r in rows:
            d = day_of(r["start_time"])
            r["day"] = (d - first).days + 1 if d and first else None
            r["avg_speed_ms"] = r["distance_m"] / r["moving_s"] if r["moving_s"] > 0 else None
            line = profile(r["id"]) if r["has_gps"] else {"track": [], "ele": [], "speed": [], "hr": []}
            r["track"], r["values"] = line["track"], {k: line[k] for k in ("ele", "speed", "hr")}
            if d:
                by_day.setdefault(d.isoformat(), []).append(r)
        days = [
            {
                "date": d,
                "day": rs[0]["day"],
                "activities": len(rs),
                "activity_ids": [r["id"] for r in rs],
                "ele_max_m": max((r["ele_max_m"] for r in rs if r["ele_max_m"] is not None), default=None),
                **stats(rs),
            }
            for d, rs in sorted(by_day.items())
        ]
        top = max((r for r in rows if r["ele_max_m"] is not None), key=lambda r: r["ele_max_m"], default=None)
        timed = [d for d in days if d["avg_speed_ms"]]
        n_days, n_acts = len(days) or 1, len(rows) or 1
        keys = ("distance_m", "moving_s", "elev_gain_m")
        out.update(
            {
                "activity_list": rows,
                "per_day": days,
                "fastest_day": max(timed, key=lambda d: d["avg_speed_ms"])["date"] if len(timed) > 1 else None,
                "slowest_day": min(timed, key=lambda d: d["avg_speed_ms"])["date"] if len(timed) > 1 else None,
                "longest_day": max(days, key=lambda d: d["distance_m"])["date"] if len(days) > 1 else None,
                "shortest_day": min(days, key=lambda d: d["distance_m"])["date"] if len(days) > 1 else None,
                "biggest_climb_day": max(days, key=lambda d: d["elev_gain_m"])["date"] if days else None,
                "highest_point": {
                    "ele_m": top["ele_max_m"],
                    "activity_id": top["id"],
                    "name": top["name"],
                    "day": top["day"],
                }
                if top
                else None,
                "avg_per_day": {k: out[k] / n_days for k in keys},
                "avg_per_activity": {k: out[k] / n_acts for k in keys},
                "avg_hr": avg_hr(rows),
                "tiles": tiles_of(adv),
                "tile_keys": list(TILE_KEYS),
            }
        )
        return out

    @ctx.router.patch("/adventures/{adv_id}")
    def edit(adv_id: int, body: AdventurePatch) -> dict:
        adventure(adv_id)
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                ctx.db.execute(f"UPDATE {adv_t} SET {key} = ? WHERE id = ?", (value.strip(), adv_id))
        return detail(adv_id)

    @ctx.router.put("/adventures/{adv_id}/activities")
    def put_members(adv_id: int, body: MembersIn) -> dict:
        adventure(adv_id)
        set_members(adv_id, body.activity_ids)
        return detail(adv_id)

    @ctx.router.put("/adventures/{adv_id}/tiles")
    def put_tiles(adv_id: int, body: TilesIn) -> dict:
        """Choose and order the tiles: for this adventure (``scope: adventure``), or as the
        default of its type (``scope: type``, which also drops this adventure's own choice).
        ``keys: null`` goes back to the defaults of that scope."""
        adv = adventure(adv_id)
        if body.keys is not None:
            bad = [k for k in body.keys if k not in TILE_KEYS]
            if bad or not body.keys:
                raise Invalid(f"unknown tiles: {', '.join(bad)}" if bad else "choose at least one tile")
        keys = list(dict.fromkeys(body.keys)) if body.keys is not None else None
        if body.scope == "adventure":
            if keys is None:
                ctx.db.execute(f"DELETE FROM {tiles_t} WHERE adventure_id = ?", (adv_id,))
            else:
                ctx.db.execute(
                    f"INSERT OR REPLACE INTO {tiles_t} (adventure_id, keys) VALUES (?, ?)", (adv_id, json.dumps(keys))
                )
        else:
            rows = ctx.db.query(f"SELECT value FROM {set_t} WHERE key = 'tiles'")
            saved = json.loads(rows[0]["value"]) if rows else {}
            saved[adv["type"]] = keys
            saved = {t: v for t, v in saved.items() if v}
            ctx.db.execute(f"INSERT OR REPLACE INTO {set_t} (key, value) VALUES ('tiles', ?)", (json.dumps(saved),))
            ctx.db.execute(f"DELETE FROM {tiles_t} WHERE adventure_id = ?", (adv_id,))
        return tiles_of(adventure(adv_id))

    @ctx.router.get("/tiles")
    def get_tiles() -> dict:
        """Tile defaults per type and every tile key."""
        return {"types": type_tiles(), "builtin": DEFAULT_TILES, "keys": list(TILE_KEYS)}

    @ctx.router.delete("/adventures/{adv_id}", status_code=204)
    def delete(adv_id: int) -> None:
        """Remove an adventure; its activities are kept and can be proposed again (also
        when an earlier proposal with them was dismissed)."""
        adventure(adv_id)
        freed = set(member_ids(adv_id))
        for r in ctx.db.query(f"SELECT key FROM {dis_t}"):
            if freed & {int(i) for i in r["key"].split(",") if i.isdigit()}:
                ctx.db.execute(f"DELETE FROM {dis_t} WHERE key = ?", (r["key"],))
        ctx.db.execute(f"DELETE FROM {mem_t} WHERE adventure_id = ?", (adv_id,))
        ctx.db.execute(f"DELETE FROM {tiles_t} WHERE adventure_id = ?", (adv_id,))
        ctx.db.execute(f"DELETE FROM {adv_t} WHERE id = ?", (adv_id,))

    # ---- preview tracks --------------------------------------------------------------------
    @ctx.router.get("/tracks")
    def preview_tracks(ids: str = "") -> list[dict]:
        """GPS lines of the given activity ids (comma-separated), for proposal previews."""
        want = [int(i) for i in ids.split(",") if i.strip().isdigit()][:200]
        known = {a["id"]: a for a in ctx.core.list_activities()}
        return [{"id": i, "track": track(i)} for i in want if i in known and known[i]["summary"].get("has_gps")]

    # ---- pickers and the activity page ---------------------------------------------------
    @ctx.router.get("/activities")
    def activities(
        date_from: Annotated[date | None, Query(alias="from")] = None,
        date_to: Annotated[date | None, Query(alias="to")] = None,
    ) -> list[dict]:
        """Compact activity list (oldest first) with the adventures each one is in."""
        where: dict[int, list[int]] = {}
        for r in ctx.db.query(f"SELECT adventure_id, activity_id FROM {mem_t}"):
            where.setdefault(r["activity_id"], []).append(r["adventure_id"])
        out = []
        for a in ctx.core.list_activities():
            d = day_of(a["start_time"])
            if (date_from and (not d or d < date_from)) or (date_to and (not d or d > date_to)):
                continue
            out.append({**row(a), "adventures": where.get(a["id"], [])})
        return sorted(out, key=lambda r: r["start_time"] or "")

    @ctx.router.get("/activity/{activity_id}")
    def of_activity(activity_id: int) -> list[dict]:
        a = ctx.core.activity(activity_id)
        rows = ctx.db.query(
            f"SELECT a.* FROM {adv_t} a JOIN {mem_t} m ON m.adventure_id = a.id WHERE m.activity_id = ? ORDER BY a.id",
            (activity_id,),
        )
        acts = {x["id"]: x for x in ctx.core.list_activities()}
        out = []
        for adv in rows:
            ov = overview(adv, members(adv["id"], acts))
            first, d = day_of(ov["first_day"]), day_of(a["start_time"])
            ov["day"] = (d - first).days + 1 if d and first else None
            out.append(ov)
        return out
