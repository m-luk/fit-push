"""Module system contract: every installed module follows the rules, and modules can
never take the core down. Runs in CI next to the core suite."""

from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

from app.modules import discover
from tests.helpers import upload
from tests.samples import synthetic_track, to_gpx

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("modules_cli", ROOT / "scripts" / "modules.py")
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

MODULES = discover()


@pytest.mark.parametrize("info", MODULES, ids=[m.id for m in MODULES])
def test_module_follows_rules(info):
    errors, _ = cli.check_module(info)
    assert not errors, "\n".join(errors)


def test_generated_docs_are_current():
    assert not cli.docs_outdated(), "run: python scripts/modules.py docs"


def test_core_only_mode(make_client):
    client = make_client(modules="none")
    mods = client.get("/api/modules").json()
    assert all(m["status"] == "disabled" for m in mods)
    assert client.get("/api/activities").status_code == 200


def _write_module(base: Path, mid: str, backend: str, extra: dict | None = None) -> None:
    d = base / mid
    (d / "tests").mkdir(parents=True)
    manifest = {
        "id": mid,
        "name": mid,
        "version": "1.0.0",
        "summary": "test module",
        "owner": {"github": "tester"},
        "sdk": "1",
        "provides": ["api", "events"],
        **(extra or {}),
    }
    (d / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "README.md").write_text("# x\n", encoding="utf-8")
    (d / "MANUAL.md").write_text("# x\n", encoding="utf-8")
    (d / "backend.py").write_text(textwrap.dedent(backend), encoding="utf-8")


def test_broken_modules_do_not_break_core(make_client, tmp_path):
    mods = tmp_path / "mods"
    _write_module(mods, "crashes", "def register(ctx):\n    raise RuntimeError('boom')\n")
    _write_module(
        mods,
        "bad_handler",
        """
        def register(ctx):
            def explode(**kw):
                raise ValueError("handler failed")
            ctx.on("activity.imported", explode)

            @ctx.router.get("/ok")
            def ok():
                return {"ok": True}
        """,
    )
    _write_module(mods, "needs_missing", "def register(ctx):\n    pass\n", {"depends": ["not_there"]})
    _write_module(mods, "wrong_sdk", "def register(ctx):\n    pass\n", {"sdk": "99"})

    client = make_client(modules="all", modules_dir=mods)
    status = {m["id"]: m for m in client.get("/api/modules").json()}
    assert status["crashes"]["status"] == "error" and "boom" in status["crashes"]["errors"][0]
    assert status["needs_missing"]["status"] == "error"
    assert status["wrong_sdk"]["status"] == "error"
    assert status["bad_handler"]["status"] == "loaded"
    assert client.get("/api/m/bad_handler/ok").json() == {"ok": True}

    aid = upload(client, "run.gpx", to_gpx(synthetic_track()))  # emits activity.imported -> handler raises
    assert client.get(f"/api/activities/{aid}").status_code == 200
    errs = {m["id"]: m["errors"] for m in client.get("/api/modules").json()}
    assert any("handler failed" in e for e in errs["bad_handler"])


def test_module_db_is_sandboxed(make_client):
    from app.core import Core
    from app.sdk import ModuleDB

    client = make_client(modules="none")
    db = ModuleDB(client.app.state.core, "demo")
    assert isinstance(client.app.state.core, Core)
    db.script(f"CREATE TABLE IF NOT EXISTS {db.table('notes')} (id INTEGER PRIMARY KEY, text TEXT);")
    db.execute(f"INSERT INTO {db.table('notes')} (text) VALUES (?)", ("hi",))
    assert db.query(f"SELECT text FROM {db.table('notes')}") == [{"text": "hi"}]
    for sql in (
        "DELETE FROM activities",
        "DROP TABLE activities",
        "UPDATE settings SET value = 1",
        "INSERT INTO segments (name) VALUES ('x')",
        "PRAGMA foreign_keys = OFF",
    ):
        with pytest.raises(PermissionError):
            db.execute(sql)
    with pytest.raises(PermissionError):
        db.script(f"CREATE TABLE {db.table('ok')} (x); DROP TABLE activities")


def test_scaffold_requires_filled_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_DIR", tmp_path)
    assert cli.cmd_new("my_mod", "someone", "My mod", ["page", "api"]) == 0
    info = next(i for i in discover(tmp_path) if i.id == "my_mod")
    errors, _ = cli.check_module(info)
    assert any("placeholders" in e for e in errors)  # creators must write intent + manual
    assert (tmp_path / "my_mod" / "tests" / "test_my_mod.py").is_file()


def test_module_services_and_core_actions(make_client, tmp_path):
    """Modules can offer services to each other, and import/update activities via the SDK."""
    mods = tmp_path / "mods"
    _write_module(
        mods,
        "provider",
        """
        def register(ctx):
            ctx.provide("double", lambda x: 2 * x)
        """,
    )
    _write_module(
        mods,
        "broken_provider",
        """
        def register(ctx):
            ctx.provide("x", lambda: 1)
            raise RuntimeError("late failure")
        """,
    )
    _write_module(
        mods,
        "consumer",
        """
        from fastapi import Request

        from app.sdk import Invalid

        def register(ctx):
            @ctx.router.get("/svc")
            def svc():
                double = ctx.service("provider", "double")
                return {
                    "double": double(21) if double else None,
                    "missing": ctx.service("nope", "x") is None,
                    "broken": ctx.service("broken_provider", "x") is None,
                }

            @ctx.router.post("/load")
            async def load(request: Request):
                data = await request.body()
                peek = ctx.core.peek_file("a.gpx", data)
                first = ctx.core.import_file("a.gpx", data)
                again = ctx.core.import_file("a.gpx", data)
                peek2 = ctx.core.peek_file("a.gpx", data)
                act = ctx.core.update_activity(first["id"], name="Renamed", sport="Hike")
                try:
                    ctx.core.peek_file("bad.gpx", b"not xml")
                    bad = False
                except Invalid:
                    bad = True
                return {"peek": peek, "first": first, "again": again, "peek2": peek2, "act": act, "bad": bad}
        """,
    )
    client = make_client(modules="all", modules_dir=mods)
    assert client.get("/api/m/consumer/svc").json() == {"double": 42, "missing": True, "broken": True}

    r = client.post("/api/m/consumer/load", content=to_gpx(synthetic_track())).json()
    assert r["peek"]["duplicate_of"] is None and r["peek"]["start_time"]
    assert r["first"]["status"] == "imported"
    assert r["again"] == {**r["again"], "status": "duplicate", "id": r["first"]["id"]}
    assert r["peek2"]["duplicate_of"] == r["first"]["id"]
    assert r["peek"]["start_time"] == client.get(f"/api/activities/{r['first']['id']}").json()["start_time"]
    assert r["act"]["name"] == "Renamed" and r["act"]["sport"] == "hiking"
    assert r["bad"] is True
