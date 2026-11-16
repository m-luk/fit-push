# Changelog

All notable changes to fit-push are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
How to update it: see "Changelog" in `AGENTS.md`.

## [Unreleased]

### Added

- **Adventures** module: group activities into traverses (chained tracks) and multi-day
  trips (outings from one base on consecutive days), with totals, a per-day table, the
  fastest and slowest day, averages per day and per activity, and one map coloured by
  activity, by day or as a single total line. It proposes adventures automatically;
  sports, excluded tags (default `commute`), the allowed gap between days (default 1
  day) and the traverse distance (default 10 km) can be changed. Proposals unfold to show
  their activities on a small map. Adventures are named after the national park (or mountain
  range) and nearest city found on OpenStreetMap (`YYYY-MM Park, City`); this sends one rounded point of the
  route per proposal (looked up once, in the background) and can be switched off. Saved
  adventures show at once while detection runs in the background.

## [0.4.0] - 2026-11-16

### Added

- The desktop app opens fit-push in its own window with the fit-push name and icon (app
  mode of Edge, Chrome or Brave) instead of a browser tab; `--no-app-window` keeps the
  tab. The window's title bar follows the light/dark theme. Closing the window stops
  fit-push (`--no-stop-with-window` keeps it running). On Windows the window has its own
  taskbar button, and pinning it gives a fit-push icon that starts fit-push again.
- Developers can add a **fit-push (dev)** launcher to the Start menu / app menu with
  `python scripts/devapp.py install`: it starts the working copy with auto-reload and
  opens the browser, like the desktop app.
- `python -m app --desktop` gives a run from source the desktop app's behaviour: open the
  browser, reuse a running instance, fall back to a free port.

### Removed

- Support for Python 3.10 and 3.11 when running from source: fit-push now needs Python
  3.12 or newer (the desktop app bundles its own Python and is not affected).

## [0.3.1] - 2026-11-15

### Fixed

- Unrealistic max speeds (e.g. 80–200 km/h on a city bike ride), mostly with watches using
  smart recording: speed now comes from the device's speed reading when the file has
  one, otherwise from distance over at least 5 seconds, with short spikes filtered out.
  Distance covered while GPS was lost is spread over the gap instead of arriving in one
  jump, which also corrects moving time and best efforts. Existing activities are
  recomputed once on the next start.

## [0.3.0] - 2026-11-15

### Added

- **Gear** module: a **No gear** view lists activities without gear (filterable by
  sport); select several (Shift+click for a range) and add an item to all of them at once.
- **Strava import** module: import a Strava data export (zip). New activities are
  imported; ones you already have are recognised and get their Strava title, sport type,
  bike or shoes (with their default sports), commute tag, description and private note.
  Preview shows every change before anything is written.
- Module SDK 1.2: modules can import files, rename activities, change their sport, offer
  services to other modules and place an activity card as a compact line in the
  activity header.
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

- The section tabs (Activities, Segments and module pages) moved from the sidebar to the
  top bar next to the logo, with each page's icon beside its name; on narrow screens they
  form their own scrollable row.
- Renamed from fit-git to fit-push. Data from the old data directory (or the repository's
  `data/activities.db`) is copied on first start; `FITGIT_*` environment variables and
  saved browser preferences still work.
- Pages and static files are served with `Cache-Control: no-cache`, so a normal refresh
  picks up a new version.

[Unreleased]: https://github.com/m-luk/fit-push/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/m-luk/fit-push/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/m-luk/fit-push/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/m-luk/fit-push/releases/tag/v0.3.0
