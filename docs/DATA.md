# Your data: where it lives, backups and restore

| OS | Data directory |
|---|---|
| Windows | `%LOCALAPPDATA%\fit-push` |
| macOS | `~/Library/Application Support/fit-push` |
| Linux | `$XDG_DATA_HOME/fit-push` (default `~/.local/share/fit-push`) |

The database is `activities.db` in that directory; `--data-dir` / `FITPUSH_DATA_DIR`
or `--db` / `FITPUSH_DB` move it. A database at the old location
(`data/activities.db` in the repository) is copied there on first start; the old
file is kept.

Every start first copies the database to `<data dir>/backups/` (the last 10 are
kept; `FITPUSH_BACKUPS` changes the number, `--no-backup` skips it). If something
breaks your data, stop the app and restore:

```bash
python scripts/run.py --list-backups
python scripts/run.py --restore latest       # or a file name from the list
```

The database you replace is saved as a `…-pre-restore.db` backup first.

## Coming from fit-git

fit-push was called fit-git before. On the first start it copies your data over: the whole
old data directory (`.../fit-git`, including backups) or, if that does not exist, the
repository's `data/activities.db`. The old files are left untouched, so you can delete them
yourself once you are happy. Settings saved in the browser and old `FITGIT_*` environment
variables keep working.
