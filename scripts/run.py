#!/usr/bin/env python3
"""Run fit-push (or its tests) from any OS with any Python 3.12+ on PATH.

Creates ``.venv`` on first run, (re)installs requirements when they change,
then runs the app or pytest with the venv's interpreter.

    python scripts/run.py                    # app window, like the desktop app
    python scripts/run.py --no-desktop       # plain server on http://127.0.0.1:8000, no window
    python scripts/run.py --port 9000 --reload
    python scripts/run.py --host 0.0.0.0
    python scripts/run.py --tests [pytest args...]
    python scripts/run.py --core-only            # any `python -m app` option is passed through
    python scripts/run.py --list-backups / --restore latest

By default the app runs like the desktop app: it opens in its own window (Edge, Chrome
or Brave app mode) with the fit-push icon once the server is ready, closing the window
stops the server and stopping the server (Ctrl+C, closing the console) closes the window.
A server of this checkout that is already running is reused; port 8000 taken by anything
else (e.g. an installed fit-push) means a free port is picked.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
STAMP = VENV / ".fitpush-requirements"
ICON_DIR = ROOT / "build" / "devapp"  # app/taskbar.py reads the window icon from here
ICON_REQUIREMENT = "pillow>=10.4"  # only to draw the icon once (as in requirements-release.txt)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv() -> Path:
    py = venv_python()
    if not py.exists():
        print("Creating virtual environment in .venv ...", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    return py


def ensure_requirements(py: Path, dev: bool) -> None:
    files = ["requirements.txt"] + (["requirements-dev.txt"] if dev else [])
    digest = hashlib.sha256(b"".join((ROOT / f).read_bytes() for f in files)).hexdigest()
    installed = STAMP.read_text().split() if STAMP.exists() else []
    if digest in installed:
        return
    print(f"Installing {files[-1]} ...", flush=True)
    subprocess.run(
        [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", files[-1]], cwd=ROOT, check=True
    )
    # remember both the plain and the dev digest, so a dev install also covers a plain run
    plain = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    STAMP.write_text(" ".join(sorted({digest, plain} if dev else {digest})))


def make_icon(py: Path, install: bool = False) -> Path | None:
    """Render the logo with the venv's Pillow (installing it first when ``install``); None without Pillow."""
    out = ICON_DIR / ("fit-push.ico" if sys.platform == "win32" else "fit-push.png")
    cmd = [str(py), str(ROOT / "packaging" / "make_icon.py"), str(out)]
    if subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 0:
        return out
    if not install:
        return None
    print(f"Installing {ICON_REQUIREMENT} to draw the window icon (once) ...", flush=True)
    pip = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", ICON_REQUIREMENT]
    if subprocess.run(pip, cwd=ROOT).returncode != 0:
        return None
    return out if subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 0 else None


def prepare_window(py: Path, argv: list[str]) -> None:
    """Taskbar identity of the app window (Windows): the fit-push icon, and a pin that runs this again."""
    if sys.platform != "win32":
        return
    icon = ICON_DIR / "fit-push.ico"
    if not icon.is_file() and make_icon(py, install=True) is None:
        print("note: could not draw the fit-push icon; the window keeps the browser's icon", flush=True)
    # A pinned window relaunches this exact command (devapp.py sets its own before calling us).
    os.environ.setdefault(
        "FITPUSH_RELAUNCH", subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), *argv])
    )


def main() -> int:
    if sys.version_info < (3, 12):  # noqa: UP036 - runs before the venv, on any python on PATH
        print(f"fit-push needs Python 3.12 or newer (this is {sys.version.split()[0]})", file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, help="port (default 8000)")
    ap.add_argument("--reload", action="store_true", help="restart when Python files change")
    ap.add_argument("--tests", action="store_true", help="run pytest instead of the app")
    ap.add_argument(
        "--desktop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run like the desktop app: open its own window, stop with it (default); --no-desktop: server only",
    )
    args, extra = ap.parse_known_args()

    py = ensure_venv()
    ensure_requirements(py, dev=args.tests)

    if args.tests:
        cmd = [str(py), "-m", "pytest", "-q", *extra]
    else:
        # Everything else (--core-only, --modules, --data-dir, --db, --no-backup, --restore, ...) goes to the app.
        # --port only when given, so `--desktop` can reuse a running instance / pick a free port.
        cmd = [str(py), "-m", "app", "--host", args.host, "--desktop" if args.desktop else "--no-desktop", *extra]
        if args.port is not None:
            cmd += ["--port", str(args.port)]
        if args.reload:
            cmd.append("--reload")
        if args.desktop and not {"--list-backups", "--restore", "--help", "-h", "--version"} & set(extra):
            prepare_window(py, sys.argv[1:])
        print("Starting fit-push (Ctrl+C to stop) ...", flush=True)
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode or 1)
