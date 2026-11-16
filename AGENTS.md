# AGENTS.md: working on fit-push

Guidelines for AI coding agents (and humans) changing this repository. Read this
first: it is the single source of project conventions. Tool-specific files
(`CLAUDE.md`, …) only point here and add tool-specific notes.

## What this is

A local web app that imports sports-device files (FIT, GPX, TCX, optionally
gzipped), stores them in SQLite and shows analytics: summaries, charts, map,
splits, HR zones, power curve, best efforts, trimmed views and exports, repeating
lap detection, segments, tags. Optional features come as **modules**.

- Backend: Python 3.12+, FastAPI, numpy, gpxpy, fitdecode, SQLite (stdlib).
- Frontend: one page, plain JavaScript (no build step), Chart.js 4 and Leaflet 1.9
  from cdnjs, OpenStreetMap tiles.

## Core or module? Decide first

| Change | Where |
|---|---|
| Data model, import/parse/analysis pipeline, something every page relies on (activities, sports, tags, laps, segments, settings, storage) | **core** (`app/`) |
| An optional capability with its own page, activity card or API; useful to some users | **module** (`modules/<id>/`), see the **module-development** skill and `modules/RULES.md` |
| A module needs something the SDK lacks | a separate **core** change extending `app/sdk.py` / `window.fitpush`, documented in `docs/SDK.md` |

Modules must stay small (one capability), self-contained, owned (GitHub id) and
documented (`README.md` intent + `MANUAL.md`). Working on a module never requires
reading `app/`; that keeps the context small and the core safe.

## Commands

```bash
python scripts/run.py                    # venv + deps, then serve http://127.0.0.1:8000 (core + modules)
python scripts/run.py --core-only        # core only (any `python -m app` option passes through)
python scripts/run.py --tests            # pytest: core (twice: core-only + all modules) + module tests
python scripts/modules.py check          # module rules + generated docs up to date
python scripts/modules.py docs           # regenerate modules/INDEX.md + docs/MODULES_MANUAL.md
ruff check . && ruff format --check .    # lint + format (config in pyproject.toml)
ty check                                 # type check
node --check app/static/app.js           # JS syntax
python scripts/release.py build          # desktop app into dist/ (needs requirements-release.txt)
```

VS Code tasks: **run** (Ctrl+Shift+B), **run (auto-reload)**, **run (core only)**,
**tests**, **lint + types**, **build desktop app**. They are `process` tasks that start Python directly;
keep them that way (shell tasks broke under cmd / Git Bash).

**After changing Python code, restart the server** (or run it with `--reload`).
Static files are served `no-cache`, so a normal browser refresh picks up JS/CSS.

## Quality gates (CI runs exactly these)

GitHub Actions (`.github/workflows/ci.yml`) and GitLab CI (`.gitlab-ci.yml`) run:
- ruff check, ruff format --check, ty check, `node --check`;
- pytest on Linux/Windows/macOS and Python 3.12–3.13;
- `scripts/modules.py check`;
- the UI smoke test, with modules and core-only.

Run them locally before committing; a red gate is not "done".

## Data location and backups

The app was renamed from **fit-git** to **fit-push**. `app/paths.py` copies data from the
old name's data directory (and the repo's `data/activities.db`) on first start and still
reads `FITGIT_*` env vars and `fitgit:` localStorage keys. Keep those fallbacks.


`app/paths.py`. The database lives in the per-user data directory:
- Windows: `%LOCALAPPDATA%\fit-push`
- macOS: `~/Library/Application Support/fit-push`
- Linux: `$XDG_DATA_HOME/fit-push` (default `~/.local/share/fit-push`)

Override with `--data-dir` / `FITPUSH_DATA_DIR` or `--db` / `FITPUSH_DB`. The old
`<repo>/data/activities.db` is copied over once.

Every `python -m app` start first copies the database to `<data dir>/backups/`
(SQLite online backup; newest `FITPUSH_BACKUPS`=10 automatic copies kept).
`--list-backups` and `--restore latest|<file>` put one back, saving the current
database as a `pre-restore` copy first. Never weaken this safety net.

## Desktop app and releases

`scripts/release.py build` freezes the app with PyInstaller (Python bundled) into `dist/`:
a single-file executable, a portable folder and, on Windows, an Inno Setup installer.
Pushing a tag `vX.Y.Z` builds and publishes releases on GitHub and GitLab; the tag must
match `__version__` in `app/__init__.py` (and `pyproject.toml`): use
`release.py bump X.Y.Z`. Details in `docs/DEVELOPMENT.md`.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
and SemVer. **Every user-visible change adds an entry under `## [Unreleased]` in the
same commit** (core and modules alike; pure refactors, tests, CI and agent docs don't).

- Group entries under `### Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`,
  `Security` (in that order; only the groups you need). Create the group if missing.
- One bullet per change, written for users: what they can now do or what behaves
  differently, not how it was implemented. Name modules in bold (`**Gear** module: …`).
  Newest bullets on top within a group.
- Never edit a released `## [X.Y.Z] - YYYY-MM-DD` section (except to fix a plain mistake).
- Don't rename or move `## [Unreleased]` by hand: `release.py bump X.Y.Z` turns it into
  `## [X.Y.Z] - <today>`, opens a new empty `[Unreleased]` and updates the compare links
  at the bottom. It refuses to bump when `[Unreleased]` is empty. `release.py notes` uses
  the version's section as the GitHub/GitLab release notes (falling back to the git log).
- Choose the version from the entries: `Removed` or breaking API/SDK changes bump the
  major (minor while < 1.0), `Added` bumps the minor, only `Fixed` bumps the patch.

- Code must keep working **frozen**: find bundled files relative to `__file__` (as
  `app/main.py` and `app/modules.py` do), never relative to the working directory or the
  repo; new data folders need an `--add-data` in `release.py`, new dynamically imported
  packages a `--collect-submodules`.
- The launcher (`app/__main__.py`) uses `GET /api/version` to detect a running instance;
  keep that endpoint stable.

## Layout

```
app/
  main.py         create_app(db_path, modules, modules_dir): store, core, routers, modules, static
  core.py         Core service: ALL orchestration (import, clip, tags, laps cache, segment
                  matching, settings recompute) + events; NotFound -> 404, Invalid -> 422
  routes/         thin HTTP routers (activities, segments, system); no logic here
  events.py       EventBus (activity.imported/updated/deleted, settings.changed, segment.*)
  sdk.py          module SDK (versioned): ModuleContext, CoreAPI, ModuleDB
  modules.py      module discovery, manifest validation, isolated loading, /api/modules, /m/<id>/*
  paths.py        data directory, legacy migration, backups/restore
  parsers.py, analytics.py, laps.py, segments.py, writers.py, sports.py, storage.py
  static/         index.html, app.js (core UI + window.fitpush SDK), style.css
modules/
  RULES.md, README.md, INDEX.md (generated), _template/, <id>/ (one folder per module)
docs/
  USER_GUIDE.md, DATA.md, API.md, DEVELOPMENT.md   user and developer documentation
  SDK.md          the module contract;  MODULES_MANUAL.md (generated)
tests/
  core/           core tests by area;  helpers.py, samples.py (synthetic data)
  test_module_contract.py   rules for every module + isolation guarantees
conftest.py       fixtures: client (core-only AND all modules), make_client(modules=...)
scripts/          run.py (launcher), modules.py (new/check/docs/list), release.py (build/release)
packaging/        launcher.py (desktop entry point), installer.iss (Inno Setup), make_icon.py
.claude/skills/   ui-development, ui-verify, module-development
```

## Core invariants (don't break these)

1. **One index space.** Points are stored raw; `analytics._prepare` cleans them (sort
   by time, drop duplicate timestamps). Every index exchanged with the frontend, the
   DB or modules (trim windows, `series.idx`, laps, segment efforts, `ctx.core.points`)
   refers to the **cleaned** sequence of the **whole** activity.
2. **Activities are immutable; derived data is refreshed in `Core`.** When a change to
   `analytics.py` alters the stored summary of an existing activity, bump
   `ANALYSIS_VERSION`: the next start recomputes stored summaries once. Summaries on
   settings/sport change, lap cache by `(id, sha256)`, segment efforts on upload,
   clip, sport change, segment creation and rescan. New derived data hooks into the
   same `Core` methods, and the core emits an event for each change.
3. **SI units in the backend**; conversion only in the frontend (`UNITS`, `fmt*`).
4. **Duplicates by content hash**; clips by `sha256("clip:{sha}:{start}:{end}")`.
5. **Trimmed views are temporary**; only clip, segment creation and tags persist.
6. **Modules cannot break the core.** Loading errors, handler errors and frontend
   exceptions are contained and shown on the Modules page. Keep it that way:
   wrap every new extension point the same way.

## Backend conventions

- Logic goes in `Core` (or a domain module it calls), never in routes. Routes are
  one-liners over `Core` with Pydantic models at module level.
- Domain errors: raise `NotFound` / `Invalid` (or `ValueError` subclasses
  translated to `Invalid`); never `HTTPException` outside routes.
- numpy for anything per point; convert numpy scalars to `float`/`int` before
  JSON. Geometry is compared at a fixed metre spacing in local x/y metres.
- New dependencies only when clearly needed (`requirements.txt` /
  `requirements-dev.txt`). Write text files with `encoding="utf-8"`.
- Type hints on new code; `ty check` must pass. `ruff format` decides the layout.

## Frontend conventions (summary)

Use the **ui-development** skill for any change under `app/static/`, and the
**ui-verify** skill to check it in a browser. Key rules:

- Plain JS, one IIFE, no build step; cdnjs scripts with pinned versions.
- Colours from CSS tokens (light **and** dark); `css("--token")` in JS.
- One y-axis per chart; fixed colour per metric; text in text tokens.
- No `prompt()`/`alert()`; use `askName()` / `toast()`.
- View state in the URL hash; per-viewer preferences in `localStorage` (try/catch).
- Async renders guard every `await` with the render token; dispose maps (and module
  cleanups) before replacing the page; no animated programmatic map moves.
- `window.fitpush` is a public contract (docs/SDK.md): extend, don't break.
- The **guided tour** (`TOUR` in app.js, simulated run from `app/tutorial.py`) points at real
  controls by selector. Renaming or removing one of those ids/classes breaks a step:
  `ui_tour.py` (ui-verify) catches it. A new core feature worth showing gets a tour step.
- Tutorial data is marked by `device = "fit-push tutorial"` (clips keep it; segments keep
  their source activity); `DELETE /api/tutorial` removes exactly that. Never key it on tags.

## Tests

- Every behaviour change gets a test; every bug fix a regression test.
- Core tests in `tests/core/`, using `client` (runs core-only and with all modules)
  and `tests.helpers` / `tests.samples`. Module tests live in the module.
- Never commit or depend on real activity files.

## Data and privacy

- The database, backups and personal activity files (e.g. `*_ACTIVITY.fit`) are the
  user's data: never commit, upload or paste them; work on copies.
- GPS tracks reveal where someone lives. Automated browser runs on real data block
  map tiles (the ui-verify script does).
- Modules list owners by GitHub id only: no names or e-mails.

## Git

- Small, focused commits; imperative subject (≤ 72 chars), body says *why*.
- No attribution / co-author lines.
- Stage files explicitly; check `git status` so personal files never sneak in.
- User-visible change: add a `CHANGELOG.md` entry in the same commit (see "Changelog").
- Docs: `README.md` is the short, user-facing front page; details go in `docs/`
  (`USER_GUIDE.md` features, `DATA.md` storage/backups, `API.md`, `DEVELOPMENT.md`). Update
  the matching doc when behaviour or the API changes; regenerate module docs.

## Environment notes

- Development on Windows with PowerShell 7 and Python from scoop; the venv
  interpreter is `.venv\Scripts\python.exe`.
- Mixed LF/CRLF in the tree; when doing literal replacements from scripts, allow `\r\n`.
