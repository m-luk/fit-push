"""Run the app: ``python -m app [options]``. See ``python -m app --help``.

The packaged desktop build (``fit-push.exe``) runs the same entry point; when frozen it
opens the browser by default, reuses an instance that is already running and falls back
to a free port when 8000 is taken.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
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


# Chromium-based browsers support app windows (`--app=URL`): no tabs or address bar, the
# page's title and icon in the taskbar.
_BROWSERS = {
    "win32": {
        "edge": [r"Microsoft\Edge\Application\msedge.exe"],
        "chrome": [r"Google\Chrome\Application\chrome.exe"],
        "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
    },
    "darwin": {
        "chrome": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "edge": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        "brave": ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    },
    "linux": {
        "chrome": ["google-chrome", "google-chrome-stable"],
        "chromium": ["chromium", "chromium-browser"],
        "edge": ["microsoft-edge", "microsoft-edge-stable"],
        "brave": ["brave-browser", "brave"],
    },
}


_CHROMIUM_EXES = ("msedge.exe", "chrome.exe", "brave.exe", "chromium.exe", "vivaldi.exe")


def _default_browser_windows() -> str | None:
    """Executable of the user's default browser on Windows when it is Chromium-based."""
    if sys.platform != "win32":
        return None
    try:
        import shlex
        import winreg

        key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            prog = str(winreg.QueryValueEx(k, "ProgId")[0])
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog + r"\shell\open\command") as k:
            command = str(winreg.QueryValueEx(k, "")[0])
        exe = shlex.split(command, posix=False)[0].strip('"')
    except (ImportError, OSError, ValueError, IndexError):
        return None
    return exe if Path(exe).name.lower() in _CHROMIUM_EXES and Path(exe).is_file() else None


def app_browser() -> str | None:
    """Path of a Chromium-based browser that can open an app window (the default one first)."""
    plat = "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"
    if plat == "win32" and (default := _default_browser_windows()):
        return default
    table = _BROWSERS[plat]
    for name in table:
        for entry in table[name]:
            if plat == "win32":
                roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
                found = next((p for r in roots if r and (p := Path(r) / entry).is_file()), None)
            elif plat == "darwin":
                found = Path(entry) if Path(entry).is_file() else None
            else:
                found = shutil.which(entry)
            if found:
                return str(found)
    return None


def open_url(url: str, app_window: bool) -> bool:
    """Open the app in its own browser window (fit-push name and icon), else in a browser tab.

    Returns True when an app window was opened.
    """
    if app_window and (exe := app_browser()):
        # Detached from our console: stopping the server with a console Ctrl+C must not reach the browser.
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
        try:
            subprocess.Popen(
                [exe, f"--app={url}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=sys.platform != "win32",
                creationflags=flags,
            )
            return True
        except OSError:
            pass
    webbrowser.open(url)
    return False


def _open_when_ready(host: str, port: int, url: str, app_window: bool, stop_with_window: bool) -> None:
    from . import taskbar

    end = time.monotonic() + 60.0
    while time.monotonic() < end:
        if running_instance(host, port, timeout=0.5):
            if open_url(url, app_window):
                # own taskbar button + pin that relaunches fit-push; stop when the last window closes
                watched = stop_with_window and taskbar.watch_app_windows(_stopped_with_window)
                if not watched:
                    taskbar.tag_app_windows()
            return
        time.sleep(0.25)


def _stopped_with_window() -> None:
    from . import taskbar

    print("fit-push window closed: stopping the server", flush=True)
    taskbar.stop_server()


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
    ap.add_argument(
        "--desktop",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="behave like the desktop app: open the browser, reuse a running instance, "
        "pick a free port if the default is taken (default: on in the desktop app)",
    )
    ap.add_argument(
        "--app-window",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="open fit-push in its own window (Edge, Chrome or Brave app mode) instead of a browser tab",
    )
    ap.add_argument(
        "--stop-with-window",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="stop the server when the last fit-push app window is closed (Windows)",
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
    desktop = frozen() if args.desktop is None else args.desktop
    open_browser = desktop if args.open is None else args.open
    if args.reload and frozen():
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
            if open_browser and open_url(f"http://{host}:{port}/", args.app_window):
                from . import taskbar

                taskbar.tag_app_windows()  # the running server's watcher counts this window too
            return 0
        if not port_free(host, port):
            port = free_port(host)

    if not args.no_backup and (copy := paths.backup(db)):
        print(f"backup: {copy}")
    url = f"http://{host}:{port}/"
    print(f"database: {db}")
    print(f"fit-push {__version__} running at {url}" + ("  (close this window to stop)" if desktop else ""))
    if open_browser:
        threading.Thread(
            target=_open_when_ready, args=(host, port, url, args.app_window, args.stop_with_window), daemon=True
        ).start()

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
