---
name: ui-verify
description: Verify fit-push frontend changes in a real headless browser (Playwright driving the installed Edge or Chrome) - one-time setup, the bundled smoke test covering dashboard, activity, map overlays, laps, segments, dark mode and 390 px width, and how to write a targeted check for a new feature. Use after any change to app/static/ and before reporting UI work as done.
---

# Verifying fit-push UI changes

`node --check` only proves the JS parses. UI work is done when it has run in a
browser without console errors and the screenshots have been looked at.

## One-time setup

Playwright lives in its own venv outside the project, so it never ends up in
`requirements*.txt`. It drives the installed Microsoft Edge (`channel="msedge"`),
so no browser download is needed.

```powershell
python -m venv $env:TEMP\fitpush-pw
& $env:TEMP\fitpush-pw\Scripts\python.exe -m pip install -q playwright
```

(Use your scratchpad directory instead of `$env:TEMP` if the session has one.
On Linux/macOS: `python3 -m venv /tmp/fitpush-pw` and `--channel chrome`, or
`playwright install chromium` and drop the channel.)

## Smoke test

```powershell
& $env:TEMP\fitpush-pw\Scripts\python.exe .claude\skills\ui-verify\scripts\ui_smoke.py --out $env:TEMP\fitpush-shots
```

It starts the app on port 8790 with a throw-away database and uploads synthetic
activities (two lap-track sessions and a ride with power). Then it checks:

- the dashboard and an activity page;
- every map overlay and a palette, plus enlarging the map and Esc;
- a drag selection on the charts;
- the laps view, creating a segment through the name dialog, and jumping from
  the leaderboard back to the activity;
- the segments overview;
- dark theme;
- no horizontal scroll at 390 px.

It prints `ok` / `FAIL` per step and exits non-zero on any failed step, console
error or native `prompt/alert/confirm` dialog. The server is stopped and the
temp database deleted afterwards.

- `--db-copy data/activities.db` runs against a **copy** of the real database.
  Use it when a bug only shows up with real files.
- `--port`: change it if 8790 is busy.

**Look at the screenshots** (`01_dashboard.png` … `07_mobile.png`, plus
`fail_*.png` for failures) with the Read tool. The script cannot see overlaps,
clipped columns or unreadable colours.

## Guided tour

```powershell
& $env:TEMP\fitpush-pw\Scripts\python.exe .claude\skills\ui-verify\scripts\ui_tour.py --out $env:TEMP\fitpush-tour
```

Runs the tour on an empty database twice: hands-on (every step done like a user) and by
skipping every step, then checks Exit (remove / keep demo data), Esc, resume after reload
and the docked card at 390 px. Run it after changing anything a tour step points at.

## Checking a new feature

Extend the smoke test with a `step(...)` for the new flow, or write a short
Playwright script for it. Keep these habits:

- Block map tiles: `page.route("**/*.tile.openstreetmap.org/**", lambda r: r.abort())`.
  Real tracks must not reach the tile server.
- Collect `console` errors and `pageerror`s, and fail on them.
- Assert on what the user sees (text in `#sel-bar`, row counts,
  `aria-selected`, URL hash), not on internal state.
- Before mouse interactions on charts or the map, call
  `scroll_into_view_if_needed()`. Off-screen canvases silently ignore drags.
- To click a map position, open the page with `?debug` before the hash
  (`/?debug#/activity/3`). That exposes the Leaflet map as `window.__fitpushMap`,
  so you can convert lat/lon with `latLngToContainerPoint`.
- Prefer `page.wait_for_selector` / `wait_for_url` over sleeps. Use short
  `wait_for_timeout(100–300)` only after canvas redraws.
- Screenshot both themes and 390 px width for any new layout.

## Reporting

Say what was exercised and what was not, including any step that could not run
(for example, no activity with laps in a `--db-copy` run). Mention that tiles
were blocked if map screenshots are part of the evidence.
