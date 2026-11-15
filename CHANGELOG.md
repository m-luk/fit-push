# Changelog

All notable changes to fit-push are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
How to update it: see "Changelog" in `AGENTS.md`.

## [Unreleased]

### Added

- Module SDK 1.1: modules can import files, rename activities, change their sport and
  offer services to other modules.
- **Gear** module: track shoes, bikes, skis, boats and other equipment with total
  distance, moving time, activity count, last use and a "replace after" distance limit.
  Choose default gear for a sport or a whole sport group (e.g. all cycling); new
  activities get it automatically, and each activity's gear can be changed by hand.
- Guided tour on a simulated park run that walks through the real controls (charts,
  selection, trimmed view, map colouring, laps, segments, tags, filters, modules); it can
  be skipped step by step, resumes after a reload and removes its demo data on exit.
- Desktop app: single-file executable with Python bundled, portable folder and a
  per-user Windows installer; it opens the browser, reuses a running instance and picks
  a free port. Releases are built and published from `vX.Y.Z` tags on GitHub and GitLab.
- Module system: optional features in `modules/<id>/` built on a versioned SDK, with
  contained errors, a Modules page with manuals, and `--core-only` / `--modules`.
- **All activities map** module: every route on one map, filtered by sport, tag and
  date, coloured by sport or date.
- Activity tags, with tag filters.
- Per-user data directory with an automatic database backup on every start, plus
  `--list-backups` and `--restore`.
- Sport catalogue: road, gravel and mountain biking, walking, hiking, skiing, ski touring,
  sailing, kayaking and swimming, with sport names from FIT, TCX, Strava and Garmin mapped
  to it; the sport picker groups sports by family.
- Segments cut from a selection, a lap, a trimmed view or a whole activity, matched
  against every activity, with leaderboards and links between segments and activities.
- Track colour patterns (rainbow, turbo, viridis, …) and reversed patterns on the map.
- Repeating lap detection with a laps view (per-lap table, lap-time chart, comparisons),
  an enlargeable map and track colouring by speed, elevation, heart rate, power or
  speed difference.
- Trimmed views of a chart selection (kept in the URL), export of a selection or a whole
  activity to GPX, TCX or FIT, and saving a selection as a new activity.
- Import of FIT, GPX and TCX files (optionally gzipped) into SQLite, with summaries,
  synced stream charts, map, splits, heart-rate zones, TRIMP, NP/IF/TSS, power curve,
  best efforts, dashboard trends and personal records.

### Changed

- Renamed from fit-git to fit-push. Data from the old data directory (or the repository's
  `data/activities.db`) is copied on first start; `FITGIT_*` environment variables and
  saved browser preferences still work.
- Pages and static files are served with `Cache-Control: no-cache`, so a normal refresh
  picks up a new version.

[Unreleased]: https://github.com/m-luk/fit-push/commits/HEAD
