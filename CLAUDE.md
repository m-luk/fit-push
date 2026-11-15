# CLAUDE.md

All project conventions live in **AGENTS.md**. Read it before making changes and
follow it; it is imported below so it is always in context.

@AGENTS.md

## Claude Code specifics

- **Frontend work** (anything under `app/static/`): load the `ui-development`
  skill before writing code, and the `ui-verify` skill to check the result in a
  real browser before reporting it done.
- Run `python scripts/run.py --tests` (or `.venv\Scripts\python.exe -m pytest -q`)
  before every commit.
- Servers you start for checks: use a scratch `FITGIT_DB` and a non-default
  port, and stop them when done.
- Keep AGENTS.md current: when a change adds a convention, invariant or gotcha,
  add it there (not here).
