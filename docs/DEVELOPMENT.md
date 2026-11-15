# Developing fit-push

Conventions for contributors and AI agents are in [AGENTS.md](../AGENTS.md); module authors start
with [modules/RULES.md](../modules/RULES.md) and [SDK.md](SDK.md).

## Running from source

The quickest way is the run script (any OS, any Python 3.10+). It creates
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
