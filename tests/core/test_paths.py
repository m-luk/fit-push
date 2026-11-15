"""Core: data directory per OS, legacy migration, backups and restore."""

import sqlite3
from pathlib import Path

import pytest

from app import paths


@pytest.mark.parametrize(
    "platform,env,expected",
    [
        ("win32", {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, Path(r"C:\Users\x\AppData\Local") / "fit-git"),
        ("win32", {}, Path("/home/x") / "AppData" / "Local" / "fit-git"),
        ("darwin", {}, Path("/home/x") / "Library" / "Application Support" / "fit-git"),
        ("linux", {}, Path("/home/x") / ".local" / "share" / "fit-git"),
        ("linux", {"XDG_DATA_HOME": "/data/xdg"}, Path("/data/xdg") / "fit-git"),
    ],
)
def test_default_data_dir(platform, env, expected):
    assert paths.default_data_dir(platform, env, Path("/home/x")) == expected


def _db(path: Path, rows: int) -> None:
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS t (x)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    c.close()


def _count(path: Path) -> int:
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        c.close()


def test_db_path_env_and_legacy_migration(tmp_path, monkeypatch):
    legacy = tmp_path / "repo" / "data" / "activities.db"
    legacy.parent.mkdir(parents=True)
    _db(legacy, 3)
    monkeypatch.setattr(paths, "LEGACY_DB", legacy)
    monkeypatch.delenv("FITGIT_DB", raising=False)
    monkeypatch.setenv("FITGIT_DATA_DIR", str(tmp_path / "data"))
    db = paths.db_path()
    assert db == tmp_path / "data" / "activities.db" and _count(db) == 3 and legacy.is_file()
    monkeypatch.setenv("FITGIT_DB", str(tmp_path / "other.db"))
    assert paths.db_path() == tmp_path / "other.db"


def test_backup_rotation_and_restore(tmp_path, monkeypatch):
    db = tmp_path / "activities.db"
    assert paths.backup(db) is None  # nothing to back up yet
    _db(db, 1)
    stamps = iter(f"2026-01-01 00:00:{s:02d}" for s in range(60))

    class FakeNow:
        @staticmethod
        def now():
            from datetime import datetime

            return datetime.fromisoformat(next(stamps))

    monkeypatch.setattr(paths, "datetime", FakeNow)
    for _ in range(4):
        paths.backup(db, keep=2)
    assert len(paths.list_backups(db)) == 2  # rotation keeps the newest automatic copies

    _db(db, 5)  # the "program broke the data" case
    restored = paths.restore(db, "latest")
    assert _count(db) == 1 and restored.name.endswith("-auto.db")
    pre = [b for b in paths.list_backups(db) if b.name.endswith("-pre-restore.db")]
    assert len(pre) == 1 and _count(pre[0]) == 6  # the broken state was kept too
    with pytest.raises(FileNotFoundError):
        paths.restore(db, "nope.db")
