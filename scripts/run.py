#!/usr/bin/env python3
"""Run fit-git (or its tests) from any OS with any Python 3.10+ on PATH.

Creates ``.venv`` on first run, (re)installs requirements when they change,
then runs the app or pytest with the venv's interpreter.

    python scripts/run.py                    # http://127.0.0.1:8000
    python scripts/run.py --port 9000 --reload
    python scripts/run.py --host 0.0.0.0
    python scripts/run.py --tests [pytest args...]
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
STAMP = VENV / ".fitgit-requirements"


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
    subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                    "-r", files[-1]], cwd=ROOT, check=True)
    # remember both the plain and the dev digest, so a dev install also covers a plain run
    plain = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    STAMP.write_text(" ".join(sorted({digest, plain} if dev else {digest})))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart when Python files change")
    ap.add_argument("--tests", action="store_true", help="run pytest instead of the app")
    args, extra = ap.parse_known_args()

    py = ensure_venv()
    ensure_requirements(py, dev=args.tests)

    if args.tests:
        cmd = [str(py), "-m", "pytest", "-q", *extra]
    else:
        cmd = [str(py), "-m", "app", "--host", args.host, "--port", str(args.port)]
        if args.reload:
            cmd.append("--reload")
        print(f"fit-git on http://{args.host}:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode or 1)
