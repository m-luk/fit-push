#!/usr/bin/env python3
"""Install this checkout as an app launcher for development ("editable install").

    python scripts/devapp.py install     # add a "fit-push (dev)" launcher to the Start menu / app menu
    python scripts/devapp.py uninstall   # remove it again
    python scripts/devapp.py launch      # what the launcher runs

The launcher starts *this repository* with ``--reload`` (Python changes restart the
server; JS/CSS are served no-cache, so a browser refresh picks them up) and behaves like
the desktop app: it opens the browser, reuses an instance that is already running and
picks a free port when 8000 is taken. It uses your normal data directory and backups.
Extra options after ``install`` (e.g. ``--core-only``, ``--data-dir X``) are baked into
the launcher.

Windows: a shortcut in the Start menu. Linux: a ``.desktop`` entry in
``~/.local/share/applications``. macOS: a ``.command`` file in ``~/Applications``.
The logo is used as the icon when Pillow is installed (``pip install pillow``).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "fit-push (dev)"
ICON_DIR = ROOT / "build" / "devapp"

sys.path.insert(0, str(ROOT / "scripts"))
from run import ensure_requirements, ensure_venv  # noqa: E402


def launcher_path() -> Path:
    if sys.platform == "win32":
        programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return programs / f"{NAME}.lnk"
    if sys.platform == "darwin":
        return Path.home() / "Applications" / f"{NAME}.command"
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "applications" / "fit-push-dev.desktop"


def make_icon(py: Path) -> Path | None:
    """Render the logo with the venv's Pillow; None (default icon) when Pillow is missing."""
    out = ICON_DIR / ("fit-push.ico" if sys.platform == "win32" else "fit-push.png")
    res = subprocess.run([str(py), str(ROOT / "packaging" / "make_icon.py"), str(out)], capture_output=True)
    if res.returncode != 0:
        print("note: Pillow not found in .venv, using the default icon (pip install pillow, then reinstall)")
        return None
    return out


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def install(extra: list[str]) -> int:
    py = ensure_venv()
    ensure_requirements(py, dev=False)
    icon = make_icon(py)
    script = ROOT / "scripts" / "devapp.py"
    dest = launcher_path()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        args = subprocess.list2cmdline([str(script), "launch", *extra])
        ps = "\n".join(
            [
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + ps_quote(str(dest)) + ")",
                "$s.TargetPath = " + ps_quote(str(py)),
                "$s.Arguments = " + ps_quote(args),
                "$s.WorkingDirectory = " + ps_quote(str(ROOT)),
                "$s.Description = " + ps_quote(f"fit-push from {ROOT} (auto-reload)"),
                *(["$s.IconLocation = " + ps_quote(f"{icon},0")] if icon else []),
                "$s.Save()",
            ]
        )
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True)
    elif sys.platform == "darwin":
        cmd = shlex.join([str(py), str(script), "launch", *extra])
        dest.write_text(f"#!/bin/sh\ncd {shlex.quote(str(ROOT))} && exec {cmd}\n", encoding="utf-8")
        dest.chmod(0o755)
    else:
        cmd = shlex.join([str(py), str(script), "launch", *extra])
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={NAME}",
            f"Comment=fit-push from {ROOT} (auto-reload)",
            f"Exec={cmd}",
            f"Path={ROOT}",
            "Terminal=true",
            "Categories=Development;Sports;",
            *([f"Icon={icon}"] if icon else []),
        ]
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        dest.chmod(0o755)
    print(f"installed {dest}\n  runs {ROOT} with --reload")
    return 0


def uninstall() -> int:
    dest = launcher_path()
    if dest.exists():
        dest.unlink()
        print(f"removed {dest}")
    else:
        print(f"nothing to remove ({dest} does not exist)")
    return 0


def launch(extra: list[str]) -> int:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(NAME)
    cmd = [sys.executable, str(ROOT / "scripts" / "run.py"), "--reload", "--desktop", *extra]
    # a pinned fit-push window relaunches exactly this (see app/taskbar.py)
    env = {**os.environ, "FITPUSH_RELAUNCH": subprocess.list2cmdline([sys.executable, __file__, "launch", *extra])}
    try:
        code = subprocess.call(cmd, cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 0
    if code not in (0, 130) and sys.stdin and sys.stdin.isatty():
        # keep the launcher's window open so the error can be read
        input(f"\nfit-push exited with code {code}. Press Enter to close this window.")
    return code


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("install", "uninstall", "launch"):
        print(__doc__)
        return 2
    cmd, extra = argv[0], argv[1:]
    if cmd == "install":
        return install(extra)
    if cmd == "uninstall":
        return uninstall()
    return launch(extra)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
