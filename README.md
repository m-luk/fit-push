<p align="center">
  <img src="app/static/logo.svg" width="120" alt="fit-push logo: a runner drawn as a git branch graph">
</p>

<h1 align="center">fit-push</h1>

<p align="center"><b>Your training files, analysed on your own computer.</b><br>
Drop in files from your watch or bike computer and get charts, maps, laps, segments and records.<br>
No account, no cloud: your data stays on your machine.</p>

---

## What you can do

- **Import anything common.** FIT files from Garmin, Wahoo, Coros, Suunto and others, plus
  GPX and TCX (also zipped as `.gz`). Drag a whole folder of files onto the page;
  duplicates are skipped.
- **See every workout in detail.** Distance, moving time, pace or speed, elevation, heart
  rate zones, power (normalized power, TSS, power curve), cadence and temperature, with
  synced charts and a map you can colour by speed, heart rate, elevation and more.
- **Zoom into any part.** Drag across a chart to select a stretch, view it on its own, save
  it as a new activity, or download it as GPX, TCX or FIT.
- **Analyse laps automatically.** Track sessions and repeated loops are detected, with a
  table and chart comparing every lap.
- **Race yourself on segments.** Turn any stretch into a segment; every activity that
  covers it lands on a leaderboard.
- **Find things fast.** Tag activities (`#race`, `#commute`), filter by sport and tag, and
  see all your routes on one big map.
- **Track progress.** Weekly and monthly totals, personal records per sport and an
  all-time power curve.

Sports: running, cycling (road, gravel, MTB), walking, hiking, skiing, ski touring,
sailing, kayaking and swimming.

New here? Click **🎓 Tour** in the app: a few hands-on minutes on a simulated run that show
every feature. Your own data is not touched.

## Get started

### Download (Windows, macOS, Linux)

Get the latest release from the project's **Releases** page. Python is included; there is
nothing else to install.

- **Windows:** run `fit-push-<version>-windows-x64-setup.exe` to install it with a
  Start-menu entry (no admin rights needed), or just double-click
  `fit-push-<version>-windows-x64.exe` to run it without installing.
- **macOS / Linux:** download `fit-push-<version>-<system>`, make it executable
  (`chmod +x`) and run it.

fit-push opens in its own window (an app window of Edge, Chrome or Brave; otherwise a
browser tab); drop your activity files onto the page. Closing the fit-push window (or the
small console window next to it) stops fit-push; on Windows you can pin the window to the
taskbar to start fit-push from there. Starting it again while it runs just opens another
fit-push window. `--no-app-window` opens a normal browser tab instead.

### From source

You need [Python 3.12 or newer](https://www.python.org/downloads/).

```bash
git clone <this repository> fit-push
cd fit-push
python scripts/run.py
```

fit-push opens in its own window, like the desktop app. The first start takes a minute
while it installs what it needs; later starts are instant. Close the window (or press
**Ctrl+C**) to stop it. `python scripts/run.py --no-desktop` runs only the server, at
**http://127.0.0.1:8000**.

## Your data is safe

- Everything is stored on your computer: in `%LOCALAPPDATA%\fit-push` on Windows,
  `~/Library/Application Support/fit-push` on macOS and `~/.local/share/fit-push` on Linux.
- A backup is made automatically every time the app starts. If something ever goes wrong:
  ```bash
  fit-push --restore latest              # the downloaded app (fit-push.exe on Windows)
  python scripts/run.py --restore latest # from source
  ```
- Coming from **fit-git** (the old name)? Your activities are copied over on the first
  start; nothing is deleted.

More in [Your data, backups and restore](docs/DATA.md).

## Extras

Optional features ("modules") can be switched on and off. Built in: **🗺️ Map**, all
your routes on one map, filtered by sport, tag and date. The **Modules** button in the
app lists every module with its manual. Run without any with
`python scripts/run.py --core-only`.

## Documentation

| | |
|---|---|
| [User guide](docs/USER_GUIDE.md) | every feature, page by page |
| [Your data](docs/DATA.md) | where data is stored, backups, restore, moving it |
| [Module manuals](docs/MODULES_MANUAL.md) | manuals of the optional features |
| [Developing fit-push](docs/DEVELOPMENT.md) | running from source, tests, linting, CI, releases, layout |
| [Writing a module](modules/README.md) | how friends can add features ([rules](modules/RULES.md), [SDK](docs/SDK.md)) |
| [HTTP API](docs/API.md) | the JSON API, for scripting |
| [AGENTS.md](AGENTS.md) | conventions for contributors and AI coding agents |

## License

[MIT](LICENSE). Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
