# Module rules

These rules let many people (and their AI agents) extend fit-push in parallel
without breaking each other or the core, and without anyone having to load the
whole codebase into context. `python scripts/modules.py check` enforces the
machine-checkable ones, and CI runs it.

## What a module is

1. **Smallest thing that makes sense, self-contained.** One user-visible capability
   per module (a page, or a card, or an API), in one folder `modules/<id>/`. If a
   description of your module needs "and also", it is probably two modules. Backend
   plus frontend code over ~600 lines triggers a warning: split it.
2. **Standard layout only:**
   ```
   modules/<id>/
     module.json        manifest: id, name, version, summary, owner, sdk, provides
     README.md          intent (written FIRST, before code)
     MANUAL.md          user manual
     backend.py         optional: def register(ctx)
     frontend.js        optional: registers pages / activity cards via window.fitpush
     frontend.css       optional
     tests/test_<id>.py required
   ```
   The id is `snake_case` (`[a-z][a-z0-9_]{1,31}`) and equals the folder name.
3. **Talk to the core only through the SDK** (`docs/SDK.md`): backend imports
   nothing from `app` except `app.sdk`; frontend uses `window.fitpush` (and the
   globals `L`, `Chart`). Need more? Open a separate **core** change that extends the
   SDK (with tests and docs), then use it. Never patch core files in a module change.
4. **No dependencies on other modules** unless unavoidable. If you must, list them in
   `"depends"`; the module is then switched off when a dependency is missing.
5. **No new Python packages.** Modules may use the standard library plus `fastapi`,
   `pydantic`, `numpy`. Frontend: no external scripts beyond what the page loads.

## Ownership and docs

6. **Owner is a GitHub id**: `"owner": {"github": "<id>"}`, optional `"maintainers"`
   (GitHub ids). No names, e-mails or other personal data anywhere in a module.
7. **README.md is the intent**, written by the creator before the code, with
   `## Intent` (problem, for whom, why a module), `## How it works` (endpoints,
   events, UI hooks) and `## Data` (what it reads and stores). Agents and reviewers
   read this instead of the code.
8. **MANUAL.md is the user manual**, with `## What it does`, `## How to use`
   (numbered steps naming the on-screen controls exactly) and `## Limitations`.
   It appears in the app under **Modules**, so write it for users.
9. **Regenerate the registry and the combined manual** after any change to a
   manifest or manual: `python scripts/modules.py docs` (updates `modules/INDEX.md`
   and `docs/MODULES_MANUAL.md`). CI fails when they are stale.
10. **Bump `version`** (semver) when behaviour changes; note it in the README and add a
    user-facing entry under `[Unreleased]` in `CHANGELOG.md` (see AGENTS.md, "Changelog").

## Behaviour

11. **Namespaces:** API routes only under `/api/m/<id>/` (use `ctx.router`); database
    tables only `m_<id>_*` (use `ctx.db.table()`); `localStorage` keys
    `fitpush:m:<id>:*`; CSS classes with a short module prefix.
12. **Never break the core:** don't touch elements outside the one you are given,
    don't replace `window.fitpush`, don't call `prompt()`/`alert()`, handle missing data
    (no GPS, no HR, no time) gracefully, and keep event handlers fast.
13. **Privacy:** don't send activity data, locations or anything personal to external
    services. Map tiles via `sdk.map()` are the only exception, and they are already used
    by the core.
14. **Follow the UI conventions** (`.claude/skills/ui-development/SKILL.md`):
    colours from tokens (light and dark), escape all text with `sdk.esc`, view
    state in the URL (`ctx.setParams`), keyboard-usable controls, works at 390 px.

## Tests

15. `tests/test_<id>.py` covers the module's API and its main behaviour with
    synthetic data (`tests/samples.py`). Never use personal activity files.
16. Before you open a PR, all of these must pass:
    ```bash
    python scripts/modules.py check <id>
    python -m pytest -q                 # core (core-only and with all modules) + every module
    ruff check . && ruff format --check .
    ```
    and, for UI, the ui-verify smoke test (`.claude/skills/ui-verify/SKILL.md`).

## Getting started

```bash
python scripts/modules.py new <id> --owner <github-id> --name "Readable name" --provides page,api
```

Then follow the **module-development** skill (`.claude/skills/module-development/SKILL.md`).
