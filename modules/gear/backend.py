"""Gear (backend): gear items, usage totals and default gear per sport or sport group.

Endpoints (under /api/m/gear):
    GET    /gear                      items with totals, defaults, kinds, sport groups
    POST   /gear                      add an item
    PATCH  /gear/{id}                 change an item (name, kind, notes, start_m, limit_m, retired)
    DELETE /gear/{id}                 remove an item (and its uses and defaults)
    PUT    /gear/{id}/defaults        {targets: ["sport:<key>" | "family:<family>", ...]}
    GET    /activity/{id}             gear of one activity
    PUT    /activity/{id}             {gear_ids: [...]}: manual choice
    POST   /activity/{id}/reset       back to the defaults
    POST   /apply-defaults            defaults for activities that have no gear yet
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.sdk import Invalid, ModuleContext, NotFound

KINDS = ["shoes", "bike", "skis", "boat", "other"]


class GearIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = "other"
    notes: str = Field(default="", max_length=500)
    start_m: float = Field(default=0.0, ge=0)
    limit_m: float | None = Field(default=None, gt=0)


class GearPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    start_m: float | None = Field(default=None, ge=0)
    limit_m: float | None = Field(default=None, ge=0)  # 0 clears the limit
    retired: bool | None = None


class TargetsIn(BaseModel):
    targets: list[str] = Field(max_length=100)


class ActivityGearIn(BaseModel):
    gear_ids: list[int] = Field(max_length=20)


def register(ctx: ModuleContext) -> None:
    items_t, defaults_t = ctx.db.table("items"), ctx.db.table("defaults")
    use_t, manual_t = ctx.db.table("use"), ctx.db.table("manual")
    ctx.db.script(f"""
        CREATE TABLE IF NOT EXISTS {ctx.db.table("items")} (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', start_m REAL NOT NULL DEFAULT 0, limit_m REAL,
            retired INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("defaults")} (
            target TEXT NOT NULL, kind TEXT NOT NULL, gear_id INTEGER NOT NULL, PRIMARY KEY (target, kind));
        CREATE TABLE IF NOT EXISTS {ctx.db.table("use")} (
            activity_id INTEGER NOT NULL, gear_id INTEGER NOT NULL, PRIMARY KEY (activity_id, gear_id));
        CREATE INDEX IF NOT EXISTS {ctx.db.table("use_gear")} ON {use_t} (gear_id);
        CREATE TABLE IF NOT EXISTS {ctx.db.table("manual")} (activity_id INTEGER PRIMARY KEY)
    """)

    # ---- helpers -------------------------------------------------------------------------
    def families() -> dict[str, str]:
        return {s["key"]: s["family"] for s in ctx.core.sports()}

    def item(gid: int) -> dict:
        rows = ctx.db.query(f"SELECT * FROM {items_t} WHERE id = ?", (gid,))
        if not rows:
            raise NotFound(f"gear {gid} not found")
        return rows[0]

    def check_kind(kind: str) -> str:
        if kind not in KINDS:
            raise Invalid(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
        return kind

    def default_ids(sport: str) -> list[int]:
        """Default gear for a sport: per kind, the sport's own default beats its group's."""
        targets = [f"sport:{sport}", f"family:{families().get(sport, 'other')}"]
        rows = ctx.db.query(
            f"SELECT d.target, d.kind, d.gear_id FROM {defaults_t} d JOIN {items_t} g ON g.id = d.gear_id "
            f"WHERE g.retired = 0 AND d.target IN (?, ?)",
            targets,
        )
        by_kind: dict[str, int] = {}
        for r in sorted(rows, key=lambda r: targets.index(r["target"]), reverse=True):
            by_kind[r["kind"]] = r["gear_id"]  # the sport row comes last and wins
        return sorted(by_kind.values())

    def set_use(aid: int, gear_ids: list[int]) -> None:
        ctx.db.execute(f"DELETE FROM {use_t} WHERE activity_id = ?", (aid,))
        for gid in dict.fromkeys(gear_ids):
            ctx.db.execute(f"INSERT INTO {use_t} (activity_id, gear_id) VALUES (?, ?)", (aid, gid))

    def apply_defaults(aid: int, sport: str | None = None) -> None:
        set_use(aid, default_ids(sport or ctx.core.activity(aid)["sport"]))

    def is_manual(aid: int) -> bool:
        return bool(ctx.db.query(f"SELECT 1 FROM {manual_t} WHERE activity_id = ?", (aid,)))

    def activity_gear(aid: int) -> dict:
        a = ctx.core.activity(aid)
        rows = ctx.db.query(
            f"SELECT g.* FROM {use_t} u JOIN {items_t} g ON g.id = u.gear_id WHERE u.activity_id = ? "
            f"ORDER BY g.kind, g.name",
            (aid,),
        )
        return {"activity_id": aid, "sport": a["sport"], "manual": is_manual(aid), "gear": rows}

    def missing(acts: list[dict]) -> list[tuple[int, list[int]]]:
        """Activities without gear (and not set by hand) that their sport's defaults would fill."""
        has = {r["activity_id"] for r in ctx.db.query(f"SELECT DISTINCT activity_id FROM {use_t}")}
        has |= {r["activity_id"] for r in ctx.db.query(f"SELECT activity_id FROM {manual_t}")}
        per_sport: dict[str, list[int]] = {}
        out = []
        for a in acts:
            if a["id"] not in has:
                if a["sport"] not in per_sport:
                    per_sport[a["sport"]] = default_ids(a["sport"])
                ids = per_sport[a["sport"]]
                if ids:
                    out.append((a["id"], ids))
        return out

    # ---- events --------------------------------------------------------------------------
    def on_imported(activity_id: int) -> None:
        apply_defaults(activity_id)

    def on_updated(activity_id: int, fields: list[str] | None = None, **_: object) -> None:
        if "sport" in (fields or []) and not is_manual(activity_id):
            apply_defaults(activity_id)

    def on_deleted(activity_id: int) -> None:
        ctx.db.execute(f"DELETE FROM {use_t} WHERE activity_id = ?", (activity_id,))
        ctx.db.execute(f"DELETE FROM {manual_t} WHERE activity_id = ?", (activity_id,))

    # ---- services for other modules (importers) --------------------------------------
    def svc_ensure(name: str, kind: str = "other", notes: str = "") -> int:
        """Id of the item called ``name`` (case-insensitive, any kind); created when missing."""
        name = name.strip()
        rows = ctx.db.query(f"SELECT id FROM {items_t} WHERE lower(name) = lower(?) ORDER BY id", (name,))
        if rows:
            return rows[0]["id"]
        return add_gear(GearIn(name=name, kind=check_kind(kind), notes=notes[:500]))["id"]

    def svc_assign(activity_id: int, gear_id: int) -> None:
        """Use ``gear_id`` on an activity, replacing its gear of the same kind (a manual choice)."""
        ctx.core.activity(activity_id)
        kind = item(gear_id)["kind"]
        keep = [g["id"] for g in activity_gear(activity_id)["gear"] if g["kind"] != kind and g["id"] != gear_id]
        set_use(activity_id, [*keep, gear_id])
        ctx.db.execute(f"INSERT OR IGNORE INTO {manual_t} (activity_id) VALUES (?)", (activity_id,))

    def svc_add_defaults(gear_id: int, sports: list[str]) -> list[str]:
        """Make the item the default for these sport keys where its kind has no default yet."""
        g, fams = item(gear_id), families()
        added = []
        for sport in dict.fromkeys(sports):
            target = f"sport:{sport}"
            if sport in fams and not ctx.db.query(
                f"SELECT 1 FROM {defaults_t} WHERE target = ? AND kind = ?", (target, g["kind"])
            ):
                ctx.db.execute(
                    f"INSERT INTO {defaults_t} (target, kind, gear_id) VALUES (?, ?, ?)", (target, g["kind"], gear_id)
                )
                added.append(target)
        return added

    ctx.provide("ensure", svc_ensure)
    ctx.provide("assign", svc_assign)
    ctx.provide("add_defaults", svc_add_defaults)

    ctx.on("activity.imported", on_imported)
    ctx.on("activity.updated", on_updated)
    ctx.on("activity.deleted", on_deleted)

    # ---- gear items ----------------------------------------------------------------------
    @ctx.router.get("/gear")
    def list_gear() -> dict:
        acts = {a["id"]: a for a in ctx.core.list_activities()}
        totals: dict[int, dict] = {}
        for u in ctx.db.query(f"SELECT activity_id, gear_id FROM {use_t}"):
            a = acts.get(u["activity_id"])
            if not a:
                continue
            t = totals.setdefault(u["gear_id"], {"activities": 0, "used_m": 0.0, "moving_s": 0.0, "last_used": None})
            t["activities"] += 1
            t["used_m"] += float(a["summary"].get("distance_m") or 0)
            t["moving_s"] += float(a["summary"].get("moving_s") or 0)
            if a["start_time"] and (t["last_used"] is None or a["start_time"] > t["last_used"]):
                t["last_used"] = a["start_time"]
        defaults = ctx.db.query(f"SELECT target, kind, gear_id FROM {defaults_t} ORDER BY target, kind")
        items = []
        for g in ctx.db.query(f"SELECT * FROM {items_t} ORDER BY retired, kind, name COLLATE NOCASE"):
            t = totals.get(g["id"], {"activities": 0, "used_m": 0.0, "moving_s": 0.0, "last_used": None})
            items.append(
                {
                    **g,
                    "retired": bool(g["retired"]),
                    **t,
                    "distance_m": g["start_m"] + t["used_m"],
                    "defaults": [d["target"] for d in defaults if d["gear_id"] == g["id"]],
                }
            )
        groups: dict[str, list[str]] = {}
        for s in ctx.core.sports():
            groups.setdefault(s["family"], []).append(s["key"])
        unassigned = len(missing(list(acts.values())))
        return {"gear": items, "defaults": defaults, "kinds": KINDS, "groups": groups, "unassigned": unassigned}

    @ctx.router.post("/gear", status_code=201)
    def add_gear(body: GearIn) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ctx.db.execute(
            f"INSERT INTO {items_t} (name, kind, notes, start_m, limit_m, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (body.name.strip(), check_kind(body.kind), body.notes.strip(), body.start_m, body.limit_m, now),
        )
        return ctx.db.query(f"SELECT * FROM {items_t} ORDER BY id DESC LIMIT 1")[0]

    @ctx.router.patch("/gear/{gear_id}")
    def edit_gear(gear_id: int, body: GearPatch) -> dict:
        g = item(gear_id)
        changes = body.model_dump(exclude_unset=True)
        if "kind" in changes:
            check_kind(changes["kind"])
        if changes.get("limit_m") == 0:
            changes["limit_m"] = None
        if "retired" in changes:
            changes["retired"] = int(bool(changes["retired"]))
        for key in ("name", "notes"):
            if isinstance(changes.get(key), str):
                changes[key] = changes[key].strip()
        for key, value in changes.items():
            ctx.db.execute(f"UPDATE {items_t} SET {key} = ? WHERE id = ?", (value, gear_id))
        if changes.get("kind", g["kind"]) != g["kind"]:
            targets = [
                d["target"] for d in ctx.db.query(f"SELECT target FROM {defaults_t} WHERE gear_id = ?", (gear_id,))
            ]
            set_defaults(gear_id, TargetsIn(targets=targets))
        return item(gear_id)

    @ctx.router.delete("/gear/{gear_id}", status_code=204)
    def delete_gear(gear_id: int) -> None:
        item(gear_id)
        for table in (use_t, defaults_t, items_t):
            ctx.db.execute(f"DELETE FROM {table} WHERE {'id' if table == items_t else 'gear_id'} = ?", (gear_id,))

    @ctx.router.put("/gear/{gear_id}/defaults")
    def set_defaults(gear_id: int, body: TargetsIn) -> dict:
        g = item(gear_id)
        fams = families()
        valid = {f"sport:{k}" for k in fams} | {f"family:{f}" for f in fams.values()}
        bad = [t for t in body.targets if t not in valid]
        if bad:
            raise Invalid(f"unknown targets: {', '.join(bad)}")
        ctx.db.execute(f"DELETE FROM {defaults_t} WHERE gear_id = ?", (gear_id,))
        for target in dict.fromkeys(body.targets):
            ctx.db.execute(
                f"INSERT OR REPLACE INTO {defaults_t} (target, kind, gear_id) VALUES (?, ?, ?)",
                (target, g["kind"], gear_id),
            )
        return {"gear_id": gear_id, "targets": list(dict.fromkeys(body.targets))}

    # ---- per activity --------------------------------------------------------------------
    @ctx.router.get("/activity/{activity_id}")
    def get_activity(activity_id: int) -> dict:
        return activity_gear(activity_id)

    @ctx.router.put("/activity/{activity_id}")
    def put_activity(activity_id: int, body: ActivityGearIn) -> dict:
        ctx.core.activity(activity_id)  # 404 for unknown activities
        for gid in body.gear_ids:
            item(gid)
        set_use(activity_id, body.gear_ids)
        ctx.db.execute(f"INSERT OR IGNORE INTO {manual_t} (activity_id) VALUES (?)", (activity_id,))
        return activity_gear(activity_id)

    @ctx.router.post("/activity/{activity_id}/reset")
    def reset_activity(activity_id: int) -> dict:
        ctx.db.execute(f"DELETE FROM {manual_t} WHERE activity_id = ?", (activity_id,))
        apply_defaults(activity_id)
        return activity_gear(activity_id)

    @ctx.router.post("/apply-defaults")
    def apply_all() -> dict:
        """Give default gear to activities that have none and were not set by hand."""
        todo = missing(ctx.core.list_activities())
        for aid, ids in todo:
            set_use(aid, ids)
        return {"updated": len(todo)}
