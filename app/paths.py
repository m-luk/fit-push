"""Where fit-git keeps its data, and the safety backups made before every start.

Data directory (first match wins):
    1. ``--data-dir`` / env ``FITGIT_DATA_DIR``
    2. Windows: ``%LOCALAPPDATA%\\fit-git``
       macOS:   ``~/Library/Application Support/fit-git``
       Linux:   ``$XDG_DATA_HOME/fit-git`` (default ``~/.local/share/fit-git``)

The database is ``<data dir>/activities.db`` unless ``--db`` / ``FITGIT_DB`` names a
file. A database from the old location (``<repo>/data/activities.db``) is copied
over on first start; the old file is left untouched.

Before the app starts, ``backup()`` copies the database (SQLite online backup, so
the copy is consistent) to ``<data dir>/backups/`` and keeps the newest
``FITGIT_BACKUPS`` (default 10) copies. ``restore()`` puts one back, after saving
the current database as a ``pre-restore`` copy first.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

log = logging.getLogger("fitgit.paths")

APP_NAME = "fit-git"
DB_NAME = "activities.db"
LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / DB_NAME


def default_data_dir(
    platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """The per-user data directory for ``platform`` (defaults: this machine)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    assert env is not None
    home = home or Path.home()
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / APP_NAME


def data_dir() -> Path:
    return Path(os.environ.get("FITGIT_DATA_DIR") or default_data_dir())


def db_path() -> Path:
    """Database location; creates the data directory and migrates a legacy database once."""
    if os.environ.get("FITGIT_DB"):
        return Path(os.environ["FITGIT_DB"])
    path = data_dir() / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and LEGACY_DB.is_file():
        _sqlite_copy(LEGACY_DB, path)
        log.warning("copied the database from %s to %s (the old file is kept)", LEGACY_DB, path)
    return path


def backups_dir(db: Path) -> Path:
    return db.parent / "backups"


def _sqlite_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def backup(db: Path, keep: int | None = None, label: str = "auto") -> Path | None:
    """Copy ``db`` into the backups folder and prune old automatic copies. None if there is no db yet."""
    if not db.is_file() or db.stat().st_size == 0:
        return None
    keep = keep if keep is not None else int(os.environ.get("FITGIT_BACKUPS", "10"))
    target = backups_dir(db) / f"{db.stem}-{datetime.now():%Y%m%d-%H%M%S}-{label}.db"
    _sqlite_copy(db, target)
    autos = sorted(backups_dir(db).glob(f"{db.stem}-*-auto.db"))
    for old in autos[:-keep] if keep > 0 else autos:
        old.unlink(missing_ok=True)
    return target


def list_backups(db: Path) -> list[Path]:
    """Newest first."""
    return sorted(backups_dir(db).glob(f"{db.stem}-*.db"), reverse=True)


def restore(db: Path, name: str = "latest") -> Path:
    """Replace ``db`` with a backup (``latest`` or a file name from ``list_backups``)."""
    candidates = [b for b in list_backups(db) if not b.name.endswith("-pre-restore.db")]
    if name == "latest":
        if not candidates:
            raise FileNotFoundError("no backups found")
        src = candidates[0]
    else:
        src = backups_dir(db) / name
        if not src.is_file():
            raise FileNotFoundError(f"backup {name!r} not found in {backups_dir(db)}")
    backup(db, label="pre-restore")
    for extra in (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copyfile(src, db)
    return src
