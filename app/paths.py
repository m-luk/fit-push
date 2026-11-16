"""Where fit-push keeps its data, and the safety backups made before every start.

Data directory (first match wins):
    1. ``--data-dir`` / env ``FITPUSH_DATA_DIR``
    2. Windows: ``%LOCALAPPDATA%\\fit-push``
       macOS:   ``~/Library/Application Support/fit-push``
       Linux:   ``$XDG_DATA_HOME/fit-push`` (default ``~/.local/share/fit-push``)

The database is ``<data dir>/activities.db`` unless ``--db`` / ``FITPUSH_DB`` names a
file. Data from earlier versions is carried over on first start, never moved or deleted:
the whole data directory of the old name (``.../fit-git``, with its backups) is copied,
or else ``<repo>/data/activities.db``. Old ``FITGIT_*`` environment variables still work.

Before the app starts, ``backup()`` copies the database (SQLite online backup, so
the copy is consistent) to ``<data dir>/backups/`` and keeps the newest
``FITPUSH_BACKUPS`` (default 10) copies. ``restore()`` puts one back, after saving
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

log = logging.getLogger("fitpush.paths")

APP_NAME = "fit-push"
OLD_APP_NAMES = ("fit-git",)  # earlier names of the app; their data directories are migrated
DB_NAME = "activities.db"
LEGACY_DB = Path(__file__).resolve().parent.parent / "data" / DB_NAME


def instance() -> str:
    """Which installation this is: the desktop executable, or the source checkout.

    A launcher only reuses a running server of the same installation, so starting a
    checkout never just opens an installed release (or another checkout) instead.
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    return str(Path(__file__).resolve().parent.parent)


def setting(name: str, default: str | None = None) -> str | None:
    """Environment setting ``FITPUSH_<name>``, falling back to the old ``FITGIT_<name>``."""
    return os.environ.get(f"FITPUSH_{name}") or os.environ.get(f"FITGIT_{name}") or default


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
    return Path(setting("DATA_DIR") or default_data_dir())


def db_path() -> Path:
    """Database location; creates the data directory and migrates a legacy database once."""
    if db := setting("DB"):
        return Path(db)
    folder = data_dir()
    path = folder / DB_NAME
    if not path.exists():
        migrate_old_data(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return path


def migrate_old_data(folder: Path) -> Path | None:
    """Copy data of an earlier app name / location into ``folder``; returns the source or None.

    Order: a sibling data directory with an old app name (copied whole, including
    backups), then the repository's ``data/activities.db``. Sources are never changed.
    """
    for old in OLD_APP_NAMES:
        old_dir = folder.with_name(old)
        if (old_dir / DB_NAME).is_file():
            shutil.copytree(old_dir, folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
            _sqlite_copy(old_dir / DB_NAME, folder / DB_NAME)  # consistent copy of the live database
            log.warning("copied data from %s to %s (the old directory is kept)", old_dir, folder)
            return old_dir
    if LEGACY_DB.is_file():
        _sqlite_copy(LEGACY_DB, folder / DB_NAME)
        log.warning("copied the database from %s to %s (the old file is kept)", LEGACY_DB, folder / DB_NAME)
        return LEGACY_DB
    return None


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
    keep = keep if keep is not None else int(setting("BACKUPS", "10") or 10)
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
