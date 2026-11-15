"""Run the app: ``python -m app [options]``. See ``python -m app --help``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from . import paths


def main() -> int:
    ap = argparse.ArgumentParser(description="fit-git activity analytics server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart when Python files change")
    ap.add_argument("--data-dir", help=f"data directory (default: {paths.default_data_dir()})")
    ap.add_argument("--db", help="database file (default: <data dir>/activities.db)")
    mods = ap.add_mutually_exclusive_group()
    mods.add_argument("--core-only", action="store_true", help="run without any modules")
    mods.add_argument("--modules", help="comma-separated module ids to load (default: all enabled)")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic backup before starting")
    ap.add_argument("--list-backups", action="store_true", help="list database backups and exit")
    ap.add_argument("--restore", metavar="NAME", help="restore a backup ('latest' or a file name) and exit")
    args = ap.parse_args()

    # Settings travel as environment variables so the uvicorn factory (and --reload workers) see them.
    if args.data_dir:
        os.environ["FITGIT_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.db:
        os.environ["FITGIT_DB"] = str(Path(args.db).expanduser().resolve())
    if args.core_only:
        os.environ["FITGIT_MODULES"] = "none"
    elif args.modules:
        os.environ["FITGIT_MODULES"] = args.modules

    db = paths.db_path()
    if args.list_backups:
        backups = paths.list_backups(db)
        print(f"database: {db}\nbackups in {paths.backups_dir(db)}:" if backups else f"no backups for {db}")
        for b in backups:
            print(f"  {b.name}  ({b.stat().st_size / 1e6:.1f} MB)")
        return 0
    if args.restore:
        src = paths.restore(db, args.restore)
        print(f"restored {src.name} -> {db} (previous database saved as a pre-restore backup)")
        return 0

    if not args.no_backup and (copy := paths.backup(db)):
        print(f"backup: {copy}")
    print(f"database: {db}")
    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
