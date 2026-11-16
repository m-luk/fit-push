# Developing fit-push

Conventions for contributors and AI agents are in [AGENTS.md](../AGENTS.md); module authors start
with [modules/RULES.md](../modules/RULES.md) and [SDK.md](SDK.md).

## Running from source

The quickest way is the run script (any OS, any Python 3.12+). It creates
`.venv` and installs the requirements on first run, and again whenever they
change:

```bash
python scripts/run.py                        # http://127.0.0.1:8000, core + modules
python scripts/run.py --core-only            # without modules (or --modules a,b)
python scripts/run.py --port 9000 --reload   # --host 0.0.0.0 to expose on the LAN
python scripts/run.py --tests                # install dev requirements, run pytest
```

In VS Code, **Terminal → Run Build Task** (Ctrl+Shift+B) runs `fit-push: run`;
there are also *run (auto-reload)*, *run (core only)*, *tests* and *lint + types*.

Manual setup: `python -m venv .venv`, activate it, `pip install -r requirements.txt`,
`python -m app` (see `python -m app --help`).

Drag files onto the page, or use **Upload**. You can upload many files at
once, and duplicate files are skipped by content hash.

## Quality gates

```bash
pip install -r requirements-dev.txt
python -m pytest -q                      # core runs twice: core-only and with all modules
ruff check . && ruff format --check .    # lint + format
ty check                                 # types
python scripts/modules.py check          # module rules + generated docs
```

CI (GitHub Actions and GitLab CI) runs the same gates on Linux, Windows and macOS,
plus a headless-browser UI smoke test. Conventions for contributors and AI agents
are in [AGENTS.md](../AGENTS.md). `tests/samples.py` generates synthetic GPX, TCX and
binary FIT files, so the tests need no fixture files.

## Desktop app and releases

The desktop app is the normal app frozen with [PyInstaller](https://pyinstaller.org) (Python
included), started by `packaging/launcher.py`, which runs `python -m app` with desktop
defaults: open the browser, reuse a running instance (`GET /api/version`), fall back to a
free port when 8000 is taken, keep the window open on a start-up error.

```bash
pip install -r requirements-release.txt   # PyInstaller + Pillow (for the icon)
python scripts/release.py build           # dist/ for this OS, see below
python scripts/release.py version         # 0.2.0 (app/__init__.py; pyproject.toml must match)
python scripts/release.py bump 0.3.0      # set the version in both places, date the CHANGELOG.md section
python scripts/release.py notes           # release notes: the CHANGELOG.md section (or commits since the last tag)
```

`build` writes to `dist/`:

| OS | Files |
|---|---|
| Windows | `fit-push-<v>-windows-x64.exe` (single file), `...-setup.exe` (Inno Setup installer, per user, no admin), `...-windows-x64.zip` (portable folder) |
| Linux, macOS | `fit-push-<v>-<os>-<arch>` (single file), `....tar.gz` (portable folder) |

plus `SHA256SUMS.txt`. The installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`); without it the installer is skipped with a warning
(`--require-installer` makes that an error). The icon is drawn from the logo by
`packaging/make_icon.py`; the installer script is `packaging/installer.iss`. Shipped modules
are bundled without their tests; `FITPUSH_MODULES_DIR` still points the app elsewhere.

### Making a release

1. Check that `CHANGELOG.md` `[Unreleased]` lists everything in the release, then
   `python scripts/release.py bump X.Y.Z` (sets the version and dates the changelog section;
   `release.py notes` then uses that section as the release notes), commit (`Release X.Y.Z`).
2. `git tag vX.Y.Z && git push --follow-tags`.
3. CI builds and publishes:
   - **GitHub** (`.github/workflows/release.yml`): checks the tag against the version, runs
     the tests, builds on Windows, Linux (Ubuntu 22.04, for an older glibc) and macOS,
     smoke-tests each single-file build and creates the GitHub release with the files and
     checksums. It can be re-run for an existing tag from the Actions tab.
   - **GitLab** (`build-linux`, `build-windows`, `release` jobs in `.gitlab-ci.yml`, tags
     only): builds Linux and Windows (SaaS Windows runner), uploads the files to the generic
     package registry and creates the release (`release.py publish-gitlab`). GitLab macOS
     runners need a paid plan, so macOS builds come from GitHub.

## Layout

```
app/
  main.py       app factory: store, core, routers, modules, static files
  core.py       core service: import, clip, tags, laps, segments, settings, events
  routes/       thin HTTP routers
  sdk.py        module SDK;  modules.py  module loader;  events.py  event bus
  paths.py      data directory and backups
  parsers.py    FIT / GPX / TCX (+gzip) -> Activity(points)
  analytics.py  numpy-based metrics, splits, zones, power curve, best efforts
  laps.py, segments.py, writers.py, sports.py, storage.py
  static/       index.html, app.js (Chart.js + Leaflet, window.fitpush), style.css
modules/        optional features (RULES.md, INDEX.md, _template/, <id>/)
docs/           SDK.md, MODULES_MANUAL.md
tests/          core/ tests, module contract, helpers, synthetic samples
scripts/        run.py, modules.py
```
