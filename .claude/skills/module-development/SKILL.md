---
name: module-development
description: Create or change a fit-push module (an optional feature under modules/<id>/ that plugs into the core through the SDK) - scope it, scaffold it, write the intent README first, implement backend/frontend against docs/SDK.md only, test it, write the user manual, regenerate the registry and verify. Use whenever a feature request can live outside the core, or when editing anything under modules/.
---

# Building a fit-push module

A module is the smallest self-contained feature that makes sense. It lives in
`modules/<id>/` and talks to the core **only** through the SDK. That is what lets
many people add features without breaking each other, and what keeps your context
small: you never need to read `app/`.

## Read only this

1. `modules/RULES.md`: the rules (short, binding).
2. `docs/SDK.md`: everything you may call.
3. Your module folder, and `modules/activity_map/` as a worked example if useful.

Do **not** open `app/*.py` or `app/static/app.js` for module work. If the SDK lacks
something, stop and propose a core SDK change separately (see "When the SDK is not
enough").

## Decide: module or core?

Make it a module when the feature is optional, has its own page or card, or serves
some users but not all. Make it core when it changes the data model, the import or
analysis pipeline, or something every page relies on (for example tags or sports).
Split when the description needs "and also": two small modules beat one big one.

## Workflow

1. **Scaffold** (the owner is a GitHub id; never a name or e-mail):
   ```bash
   python scripts/modules.py new <id> --owner <github-id> --name "Readable name" --provides page,api
   ```
   `--provides` is any of `page`, `activity-card`, `api`, `events`; the unneeded
   template files are removed.
2. **Write `README.md` first.** It holds the intent: `## Intent` (problem, for whom,
   why a module), `## How it works` (endpoints `/api/m/<id>/...`, events, UI hooks) and
   `## Data` (what it reads and stores). Fill in `module.json` `summary`. If you can't
   write the intent in a paragraph, the scope is wrong.
3. **Backend** (`backend.py`, optional): `register(ctx)`. Use `ctx.router` for routes,
   `ctx.core` to read activities and points, `ctx.db.table()` for your own tables, and
   `ctx.on("activity.deleted", ...)` to clean up. Keep handlers fast; cache derived
   data in memory or in `m_<id>_*` tables, keyed by activity id.
4. **Frontend** (`frontend.js`, optional): an IIFE using `window.fitpush`:
   - `registerPage({module: "<id>", label, icon, render(el, ctx)})` for a new tab;
   - `registerActivityCard({module: "<id>", title, render(el, ctx)})` for a card on
     activity pages.

   Render only into `el`. After each `await`, `if (ctx.isStale()) return;`. Keep view
   state in `ctx.setParams`, maps via `sdk.map()`, charts via `sdk.chart()` (both are
   cleaned up for you), colours via `sdk.css("--token")`, all text through `sdk.esc`.
   Optional `frontend.css` with prefixed classes and token colours only.
5. **Tests** (`tests/test_<id>.py`): use `make_client(modules="<id>")`,
   `tests.helpers.upload` and `tests.samples` generators. Cover every endpoint, the
   filters or edge cases (no GPS, no time), and cleanup on `activity.deleted`.
6. **Manual** (`MANUAL.md`): `## What it does`, `## How to use` (numbered steps naming
   on-screen controls exactly), `## Limitations`. Users read it in the app.
7. **Check, document, test:**
   ```bash
   python scripts/modules.py check <id>       # rules, docs, imports, layout
   python scripts/modules.py docs             # registry + combined manual
   python -m pytest -q                         # core (both modes) + all modules
   ruff check . && ruff format --check .
   ```
8. **Verify the UI** with the ui-verify skill (the smoke test exercises module pages
   too; add a step for your page or card), and look at the screenshots in both themes
   and at 390 px.
9. **Commit** only your module folder plus the regenerated `modules/INDEX.md` and
   `docs/MODULES_MANUAL.md`.

## Changing an existing module

Read its `README.md` (intent) and `MANUAL.md` first. Keep the intent unless the owner
agrees to change it. Bump `version`, update both docs, re-run step 7. If you are not
the owner, note the change for them (PR description) rather than rewriting the module.

## When the SDK is not enough

Don't work around it (no `app.*` imports, no DOM access outside your element, no
private core endpoints). Instead make a **separate core change**:
- add the method to `app/sdk.py` (`CoreAPI` or `ModuleContext`) or the `fitpush`
  object in `app/static/app.js`;
- document it in `docs/SDK.md`;
- test it in `tests/`;
- for breaking changes, bump `SDK_VERSION` (major).

Then use it from the module.

## Common mistakes the checker or the tests catch

- `README.md` / `MANUAL.md` still contain `TODO`, or a required section is missing
  or too short.
- `from app.core import ...` (only `app.sdk` is allowed).
- `CREATE TABLE notes`: use `ctx.db.table("notes")`. Writes to core tables raise
  `PermissionError`.
- A frontend registration without `module: "<id>"`, or `prompt()` / `alert()`.
- Stale `modules/INDEX.md`: run `python scripts/modules.py docs`.
- An e-mail address anywhere in the module.
