# AGENTS.md: working on fit-git

Guidelines for AI coding agents (and humans) changing this repository. Read this
first; it is the single source of project conventions. Tool-specific files
(`CLAUDE.md`, …) only point here and add tool-specific notes.

## What this is

A local web app that imports sports-device files (FIT, GPX, TCX, optionally
gzipped), stores them in SQLite and shows analytics: summaries, charts, map,
splits, HR zones, power curve, best efforts, trimmed views and exports, repeating
lap detection, and segments (stretches of track compared across activities).

- Backend: Python 3.10+, FastAPI, numpy, gpxpy, fitdecode, SQLite (stdlib).
- Frontend: one page, plain JavaScript (no build step), Chart.js 4 and Leaflet 1.9
  from cdnjs, OpenStreetMap tiles.

## Commands

```bash
python scripts/run.py                 # creates .venv, installs deps, serves http://127.0.0.1:8000
python scripts/run.py --reload        # restart on Python changes
python scripts/run.py --tests         # install dev deps, run pytest (extra args pass through)
.venv/Scripts/python -m pytest -q     # (Windows) tests directly; .venv/bin/python elsewhere
node --check app/static/app.js        # syntax check the frontend
```

VS Code tasks (`.vscode/tasks.json`) wrap the same commands: **fit-git: run**
(Ctrl+Shift+B), **run (auto-reload)**, **tests**. They are `process` tasks that
start Python directly; keep them that way (shell tasks broke under cmd / Git Bash).

The database defaults to `data/activities.db`; `FITGIT_DB` overrides it. Use a
scratch DB (or a *copy* of the real one) for experiments, never the real file.

**After changing Python code, restart the server**: it does not reload unless
started with `--reload`. Static files are served with `Cache-Control: no-cache`,
so a normal browser refresh picks up JS/CSS changes.

## Layout

```
app/
  parsers.py    FIT / GPX / TCX (+gzip) -> Activity(points); sport normalisation
  analytics.py  numpy metrics: distance, moving time, elevation, zones, NP/TSS,
                power curve, splits, best efforts, chart series (downsampled)
  laps.py       repeating-lap detection (GPS "gate" passes) and lap reports
  segments.py   segment geometry and effort matching
  writers.py    GPX / TCX / FIT writers (export, "cut to new file")
  storage.py    SQLite: activities (zlib JSON point columns), settings, segments, efforts
  main.py       FastAPI app factory create_app(db_path) and all routes
  static/       index.html, app.js, style.css (the whole frontend)
tests/
  samples.py    synthetic tracks (straight, 400 m track laps) + GPX/TCX/FIT encoders
  test_app.py   parser, analytics, API, laps, segments tests
scripts/run.py  cross-platform launcher (venv, deps, run / tests)
.claude/skills/ UI development and UI verification skills (see below)
```

## Core invariants (don't break these)

1. **One index space.** Points are stored raw. `analytics._prepare` cleans them
   (sorts by time, drops duplicate timestamps). Every index exchanged with the
   frontend or stored in the DB (trim windows `start`/`end`, `series.idx`, lap
   boundaries, segment efforts) refers to the **cleaned** sequence of the
   **whole** activity. A trimmed view offsets `series.idx` so it stays absolute.
2. **Activities are immutable.** Points never change after import; derived data
   is recomputed: summaries when settings or sport change, lap detection is
   cached by `(id, sha256)`, segment efforts are re-matched on upload, clip,
   sport change, segment creation and rescan. A new feature that derives data
   from points must hook into the same places.
3. **SI units in the backend** (m, s, m/s, °C, W, bpm). Unit conversion and
   formatting happen only in the frontend (`UNITS`, `fmt*` helpers).
4. **Duplicates by content hash.** Uploads are keyed by sha256 of the file;
   clips by `sha256("clip:{source sha}:{start}:{end}")`.
5. **Trimmed views are temporary.** `?start=&end=` never writes anything; only
   "Save as activity" (`/clip`) and "Create segment" persist.

## Backend conventions

- Create the app through `create_app(db_path)` (factory; uvicorn runs it with
  `factory=True`). No module-level app instance.
- Pydantic models and `Annotated` query aliases live at **module level** in
  `main.py` (`from __future__ import annotations` + aliases inside the factory
  caused `ForwardRef` errors).
- Validation errors → 422, missing objects → 404, raised as `HTTPException`.
  Domain modules raise `ValueError` subclasses (`ParseError`, `ExportError`,
  `SegmentError`); routes translate them.
- numpy for anything per-point; avoid Python loops over points except where a
  loop is clearer and bounded (e.g. spatial-grid lookups). Convert numpy scalars
  to `float`/`int` before returning JSON (`_num` helper in analytics).
- Geometry: compare tracks at a **fixed metre spacing**, never a fixed number of
  points (a 200-point comparison broke 40 km segments). Use local x/y metres
  (`_xy`/`_project`), not raw degrees.
- New dependencies only when clearly needed; add them to `requirements.txt`
  (runtime) or `requirements-dev.txt` (tests).
- Write text files with an explicit `encoding="utf-8"`: the Windows default
  (cp1252) once silently emptied the README.

## Frontend conventions (summary)

Use the **ui-development** skill (`.claude/skills/ui-development/SKILL.md`) for
any change under `app/static/`. Key rules:

- Plain JS in one IIFE; no frameworks or build step. External scripts only from
  cdnjs with pinned versions.
- Colours come from CSS tokens in `style.css`, defined for light **and** dark
  (`prefers-color-scheme` + `[data-theme]`). Read them with `css("--token")`.
- One y-axis per chart (small multiples); fixed colour per metric; legends
  and text in text tokens, never series colours.
- No `prompt()` / `alert()` for input: embedded browsers (e.g. VS Code) block
  them. Use `askName()` and `toast()`.
- View state lives in the URL hash (`#/activity/3?start=&end=&laps=1&effort=7`);
  per-viewer preferences in `localStorage` via `lsGet`/`lsSet` (wrapped in
  try/catch).
- Async `render*` functions guard every `await` with the render token
  (`newRender()` / `stale(token)`); dispose the Leaflet map before replacing
  the page, and never animate programmatic map moves (see the skill for why).
- Verify UI work in a real browser with the **ui-verify** skill before calling
  it done; `node --check` alone is not verification. Its smoke test caught two
  bugs that every quick check missed.

## Tests

- Every behaviour change gets a test in `tests/test_app.py`; every bug fix gets
  a regression test that fails without the fix.
- Build inputs with `tests/samples.py` (`synthetic_track`, `lap_track`,
  `to_gpx/to_tcx/to_fit`). Never commit or depend on real activity files.
- API tests use `TestClient(create_app(tmp_path / "test.db"))`.
- Run the full suite before committing; it takes a few seconds.

## Data and privacy

- `data/`, `*.db` and personal activity files (e.g. `*_ACTIVITY.fit` in the repo
  root) are the user's data: never commit, upload or paste them. Work on copies
  in a temp directory.
- GPS tracks reveal where someone lives and trains. Automated browser runs on
  real data must block map-tile requests (the ui-verify script does).

## Git

- Small, focused commits; imperative subject (≤ 72 chars), body says *why*.
- No attribution / co-author lines in commit messages.
- Stage files explicitly (`git add app tests README.md …`); check `git status`
  so untracked personal files never sneak in.
- Update `README.md` when user-visible behaviour or the API changes (feature
  sections + API table + layout).

## Environment notes

- Development happens on Windows with PowerShell 7 and Python from scoop;
  `python` is on PATH, the venv interpreter is `.venv\Scripts\python.exe`.
- Files are a mix of LF/CRLF; Git normalises on commit. When doing literal
  string replacement from a script, account for `\r\n`.
