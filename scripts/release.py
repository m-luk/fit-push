"""Release tooling: version, packaging into a desktop app, installer, checksums.

    python scripts/release.py version              print the version (app/__init__.py)
    python scripts/release.py bump 0.3.0           set the version in app/__init__.py and pyproject.toml
    python scripts/release.py check-tag v0.3.0     fail unless the tag matches the version
    python scripts/release.py build                build dist/ for this OS (see below)
    python scripts/release.py notes [v0.3.0]       release notes from git log since the previous tag
    python scripts/release.py publish-gitlab v0.3.0  (GitLab CI) upload dist/ to the package registry
                                                   and create the release with links to the files

``build`` needs ``pip install -r requirements-release.txt`` and produces, with Python bundled:
  * Windows: ``fit-push-<v>-windows-x64.exe`` (single file, double-click to run),
    ``fit-push-<v>-windows-x64-setup.exe`` (installer; needs Inno Setup's ISCC, skipped
    with a warning if it is missing, or an error with ``--require-installer``) and
    ``fit-push-<v>-windows-x64.zip`` (portable folder);
  * Linux / macOS: ``fit-push-<v>-<os>-<arch>`` (single file) and a ``.tar.gz`` portable folder;
  * ``SHA256SUMS.txt`` for everything above.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
INIT = ROOT / "app" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
VERSION_RE = re.compile(r'^__version__ = "([^"]+)"', re.M)
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def version() -> str:
    m = VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"no __version__ in {INIT}")
    return m.group(1)


def pyproject_version() -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def bump(new: str) -> None:
    if not SEMVER.match(new):
        raise SystemExit(f"not a semantic version: {new}")
    INIT.write_text(VERSION_RE.sub(f'__version__ = "{new}"', INIT.read_text(encoding="utf-8")), encoding="utf-8")
    text = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"', text, count=1), encoding="utf-8")
    print(f"version {new}; commit, then: git tag v{new} && git push --tags")


def check_tag(tag: str) -> None:
    v = version()
    if pyproject_version() != v:
        raise SystemExit(f"pyproject.toml has {pyproject_version()}, app/__init__.py has {v}")
    if tag.removeprefix("refs/tags/").removeprefix("v") != v:
        raise SystemExit(f"tag {tag} does not match version {v} (run: python scripts/release.py bump X.Y.Z)")
    print(f"tag {tag} matches version {v}")


def notes(tag: str | None) -> str:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()

    head = tag or "HEAD"
    prev = git("describe", "--tags", "--abbrev=0", f"{head}^") if git("tag") else ""
    log = git("log", "--pretty=format:- %s", f"{prev}..{head}" if prev else head)
    since = f" since {prev}" if prev else ""
    return (
        f"## fit-push {version()}\n\n"
        "Download the file for your system; Python is included, nothing else to install.\n\n"
        "- **Windows**: `...-setup.exe` installs fit-push with a Start-menu entry; `...-windows-x64.exe` "
        "runs without installing.\n"
        "- **Linux / macOS**: the single file `fit-push-...-<os>-<arch>` (make it executable), or the `.tar.gz`.\n\n"
        "Your data stays in your user data directory and is backed up on every start.\n\n"
        f"### Changes{since}\n\n{log}\n"
    )


# ----------------------------------------------------------------------------- build


def target() -> str:
    os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{os_name}-{arch}"


def stage_modules(dest: Path) -> Path:
    """Copy the shipped modules without tests, template and caches."""
    if dest.exists():
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns("tests", "__pycache__", "*.pyc")
    for folder in sorted((ROOT / "modules").iterdir()):
        if folder.is_dir() and not folder.name.startswith(("_", ".")):
            shutil.copytree(folder, dest / folder.name, ignore=ignore)
    for doc in ("README.md", "RULES.md", "INDEX.md"):
        if (ROOT / "modules" / doc).is_file():
            shutil.copy2(ROOT / "modules" / doc, dest / doc)
    return dest


def pyinstaller(onefile: bool, icon: Path | None, modules: Path, distpath: Path, name: str) -> Path:
    sep = os.pathsep
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(ROOT / "packaging" / "launcher.py"),
        "--name",
        name,
        "--noconfirm",
        "--clean",
        "--console",
        "--onefile" if onefile else "--onedir",
        "--distpath",
        str(distpath),
        "--workpath",
        str(BUILD / ("pyi-onefile" if onefile else "pyi-onedir")),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'app' / 'static'}{sep}app/static",
        "--add-data",
        f"{modules}{sep}modules",
        "--collect-submodules",
        "app",
        "--collect-submodules",
        "uvicorn",
        # Modules are loaded from files at run time; make sure what they may import is bundled.
        "--collect-submodules",
        "fastapi",
        "--hidden-import",
        "multipart",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "pytest",
    ]
    if icon:
        cmd += ["--icon", str(icon)]
    print("+", " ".join(cmd[3:6]), "...", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
    exe = ".exe" if sys.platform == "win32" else ""
    return distpath / (f"{name}{exe}" if onefile else name)


def find_iscc() -> str | None:
    candidates = [os.environ.get("ISCC", ""), shutil.which("iscc") or "", shutil.which("ISCC") or ""]
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [
                str(Path(base) / "Inno Setup 6" / "ISCC.exe"),
                str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
            ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(require_installer: bool) -> list[Path]:
    v, tgt = version(), target()
    base = f"fit-push-{v}-{tgt}"
    DIST.mkdir(exist_ok=True)
    for old in DIST.glob("fit-push-*"):
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    BUILD.mkdir(exist_ok=True)

    icon = None
    if sys.platform == "win32" or sys.platform == "darwin":
        icon = BUILD / "fit-push.ico"
        subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py"), str(icon)], check=True)
    modules = stage_modules(BUILD / "modules")
    out: list[Path] = []

    one = pyinstaller(True, icon, modules, BUILD / "onefile", "fit-push")
    single = DIST / (base + one.suffix)
    shutil.copy2(one, single)
    out.append(single)

    folder = pyinstaller(False, icon, modules, BUILD / "onedir", "fit-push")
    if sys.platform == "win32":
        out.append(Path(shutil.make_archive(str(DIST / base), "zip", folder.parent, folder.name)))
        iscc = find_iscc()
        if iscc and icon:
            subprocess.run(
                [
                    iscc,
                    "/Q",
                    f"/DAppVersion={v}",
                    f"/DSourceDir={folder}",
                    f"/DIconFile={icon}",
                    f"/DOutputDir={DIST}",
                    f"/DOutputBaseFilename={base}-setup",
                    str(ROOT / "packaging" / "installer.iss"),
                ],
                check=True,
            )
            out.append(DIST / f"{base}-setup.exe")
        elif require_installer:
            raise SystemExit("Inno Setup (ISCC.exe) not found; install it or set ISCC=<path>")
        else:
            print("warning: Inno Setup (ISCC.exe) not found, skipping the installer", file=sys.stderr)
    else:
        tgz = DIST / f"{base}.tar.gz"
        with tarfile.open(tgz, "w:gz") as tar:
            tar.add(folder, arcname=f"fit-push-{v}")
        out.append(tgz)

    sums = DIST / "SHA256SUMS.txt"
    lines = [f"{sha256(p)}  {p.name}" for p in out]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.append(sums)
    for p in out:
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size / 1e6:.1f} MB)")
    return out


def publish_gitlab(tag: str) -> None:
    """Upload dist/fit-push-* to the generic package registry and create the GitLab release.

    Uses the CI job token; run from GitLab CI with the build jobs' artifacts in dist/.
    """
    import json
    import urllib.request

    env = os.environ
    api, project, token = env["CI_API_V4_URL"], env["CI_PROJECT_ID"], env["CI_JOB_TOKEN"]
    files = sorted(p for p in DIST.glob("fit-push-*") if p.is_file())
    if not files:
        raise SystemExit("dist/ has no fit-push-* files")
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")
    registry = f"{api}/projects/{project}/packages/generic/fit-push/{tag.removeprefix('v')}"

    def call(method: str, url: str, data: bytes, ctype: str) -> None:
        req = urllib.request.Request(url, data=data, method=method, headers={"JOB-TOKEN": token, "Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=600) as r:
            print(f"{method} {url.rsplit('/', 1)[-1]}: {r.status}")

    links = []
    for p in [*files, sums]:
        call("PUT", f"{registry}/{p.name}", p.read_bytes(), "application/octet-stream")
        links.append({"name": p.name, "url": f"{registry}/{p.name}", "link_type": "package"})
    body = {
        "name": f"fit-push {tag.removeprefix('v')}",
        "tag_name": tag,
        "description": notes(tag),
        "assets": {"links": links},
    }
    call("POST", f"{api}/projects/{project}/releases", json.dumps(body).encode("utf-8"), "application/json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    sub.add_parser("bump").add_argument("new")
    sub.add_parser("check-tag").add_argument("tag")
    b = sub.add_parser("build")
    b.add_argument("--require-installer", action="store_true", help="fail on Windows if Inno Setup is missing")
    sub.add_parser("notes").add_argument("tag", nargs="?")
    sub.add_parser("publish-gitlab").add_argument("tag")
    args = ap.parse_args(argv)
    if args.cmd == "version":
        print(version())
    elif args.cmd == "bump":
        bump(args.new)
    elif args.cmd == "check-tag":
        check_tag(args.tag)
    elif args.cmd == "build":
        build(args.require_installer)
    elif args.cmd == "notes":
        print(notes(args.tag))
    elif args.cmd == "publish-gitlab":
        publish_gitlab(args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
