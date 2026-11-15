# CLAUDE.md

All project conventions live in **AGENTS.md**. Read it before making changes and
follow it; it is imported below so it is always in context.

@AGENTS.md

## Claude Code specifics

- **Decide core vs module first** (table at the top of AGENTS.md). For module work
  load the `module-development` skill and read only `modules/RULES.md`,
  `docs/SDK.md` and the module folder; do not read `app/` for module work.
- **Frontend work** in the core (`app/static/`): load the `ui-development` skill
  before writing code, and `ui-verify` to check the result in a real browser before
  reporting it done.
- Before every commit run the quality gates: `python scripts/run.py --tests`,
  `ruff check . && ruff format --check .`, `ty check`, `python scripts/modules.py check`.
- Servers you start for checks: use a scratch `FITGIT_DB` (or `--db`), a
  non-default port and `--no-backup`, and stop them when done.
- Keep AGENTS.md current: new conventions, invariants or gotchas go there (not here).
