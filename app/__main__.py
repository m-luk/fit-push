"""Run the app: ``python -m app [options]``. See ``python -m app --help``.

The packaged desktop build (``fit-push.exe``) runs the same entry point; when frozen it
opens the browser by default, reuses an instance that is already running and falls back
to a free port when 8000 is taken.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__, paths

DEFAULT_PORT = 8000


def frozen() -> bool:
    """True inside the packaged executable (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def running_instance(host: str, port: int, timeout: float = 1.0) -> str | None:
    """Version of a fit-push already serving on host:port, else None."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/version", timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return info.get("version") if isinstance(info, dict) and info.get("app") == "fit-push" else None


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _open_when_ready(host: str, port: int, url: str, wait: float = 60.0) -> None:
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if running_instance(host, port, timeout=0.5):
            webbrowser.open(url)
            return
        time.sleep(0.25)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fit-push", description=f"fit-push {__version__}: activity analytics server")
    ap.add_argument("--version", action="version", version=f"fit-push {__version__}")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--port", type=int, help=f"port (default {DEFAULT_PORT}; the desktop app picks a free one if taken)"
    )
    ap.add_argument("--reload", action="store_true", help="restart when Python files change")
    ap.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="open the browser when the server is ready (default: on in the desktop app)",
    )
    ap.add_argument("--data-dir", help=f"data directory (default: {paths.default_data_dir()})")
    ap.add_argument("--db", help="database file (default: <data dir>/activities.db)")
    mods = ap.add_mutually_exclusive_group()
    mods.add_argument("--core-only", action="store_true", help="run without any modules")
    mods.add_argument("--modules", help="comma-separated module ids to load (default: all enabled)")
    ap.add_argument("--no-backup", action="store_true", help="skip the automatic backup before starting")
    ap.add_argument("--list-backups", action="store_true", help="list database backups and exit")
    ap.add_argument("--restore", metavar="NAME", help="restore a backup ('latest' or a file name) and exit")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    desktop = frozen()
    open_browser = desktop if args.open is None else args.open
    if args.reload and desktop:
        print("--reload is only available when running from source", file=sys.stderr)
        return 2

    # Settings travel as environment variables so the uvicorn factory (and --reload workers) see them.
    if args.data_dir:
        os.environ["FITPUSH_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.db:
        os.environ["FITPUSH_DB"] = str(Path(args.db).expanduser().resolve())
    if args.core_only:
        os.environ["FITPUSH_MODULES"] = "none"
    elif args.modules:
        os.environ["FITPUSH_MODULES"] = args.modules

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

    host, port = args.host, args.port or DEFAULT_PORT
    if desktop and args.port is None:
        # Double-clicking the app again just brings the running one up.
        if running_instance(host, port):
            print(f"fit-push is already running at http://{host}:{port}")
            if open_browser:
                webbrowser.open(f"http://{host}:{port}/")
            return 0
        if not port_free(host, port):
            port = free_port(host)

    if not args.no_backup and (copy := paths.backup(db)):
        print(f"backup: {copy}")
    url = f"http://{host}:{port}/"
    print(f"database: {db}")
    print(f"fit-push {__version__} running at {url}" + ("  (close this window to stop)" if desktop else ""))
    if open_browser:
        threading.Thread(target=_open_when_ready, args=(host, port, url), daemon=True).start()

    import uvicorn

    if args.reload:
        uvicorn.run("app.main:create_app", factory=True, host=host, port=port, reload=True)
    else:
        from .main import create_app

        uvicorn.run(create_app, factory=True, host=host, port=port)
    return 0


def desktop_main() -> int:
    """Entry point of the packaged app: keep the window open on errors so they can be read."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException as exc:  # pragma: no cover - interactive safety net
        if isinstance(exc, KeyboardInterrupt):
            return 0
        import traceback

        traceback.print_exc()
        if frozen():
            input("\nfit-push could not start. Press Enter to close this window.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
