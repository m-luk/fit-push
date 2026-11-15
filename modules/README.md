# Modules

Optional features that live next to the core and plug into it through a small,
versioned SDK. The core (everything under `app/`) works on its own; modules add
pages, activity cards, API endpoints or reactions to events.

- **Registry:** [INDEX.md](INDEX.md) (generated) lists every module with its owner.
- **Rules:** [RULES.md](RULES.md). Read them before writing a module.
- **SDK reference:** [../docs/SDK.md](../docs/SDK.md).
- **All manuals in one file:** [../docs/MODULES_MANUAL.md](../docs/MODULES_MANUAL.md) (generated).
- **In the app:** the **Modules** button in the top bar shows each module's status,
  owner, manual and intent.

## Running with or without modules

```bash
python scripts/run.py                         # core + every module with enabled_by_default
python scripts/run.py --core-only             # core only (also: FITPUSH_MODULES=none)
python scripts/run.py --modules activity_map  # core + the listed modules
```

A module that fails to load, or whose code throws, is switched off and reported on
the Modules page. The core and the other modules keep running.

## Creating a module

```bash
python scripts/modules.py new my_feature --owner <github-id> --name "My feature" --provides page,api
# 1. write README.md (intent) first, 2. code, 3. tests, 4. MANUAL.md
python scripts/modules.py check my_feature
python scripts/modules.py docs
python -m pytest -q
```

`modules/_template/` holds the scaffold the `new` command copies.
