# fit-git

A self-hosted web app for visualising and analysing activity files from sports
devices. A Python (FastAPI) backend parses and analyses the files; a light
JavaScript frontend renders maps and charts.

## Supported files

| Format | Source | Notes |
|---|---|---|
| **FIT** (`.fit`) | Garmin, Wahoo, Coros, Suunto, Hammerhead, Zwift… | GPS, altitude, HR, cadence, power, speed, temperature, distance, sport |
| **GPX** (`.gpx`) | Strava/Komoot exports, most apps | Garmin TrackPointExtension (HR, cadence, temp) and power extensions |
| **TCX** (`.tcx`) | Garmin Connect, Polar, TrainingPeaks | HR, cadence, distance, speed and watts (ActivityExtension) |
| gzip (`*.gz`) | Strava bulk export | Any of the above, compressed |

The format comes from the file extension, or from the file contents when the
name has no usable extension.

## Analytics

Per activity:

- distance (from the device when present, otherwise GPS haversine), elapsed and moving time (auto-pause detection, with thresholds per sport)
- average and max speed / pace, elevation gain and loss (smoothed, with hysteresis), elevation range
- heart rate: average and max, time in 5 zones (% of max HR), Banister TRIMP
- power: average, max, Normalized Power, Intensity Factor, TSS, work (kJ), power curve (5 s – 60 min)
- cadence and temperature
- per-km / per-mile splits (moving pace, elevation, HR, power)
- best efforts (fastest 400 m … marathon for running; 5–100 km for cycling)
- charts that share one hover position (elevation, pace/speed, HR, power, cadence, temperature), with the hovered point marked on the map

### Trimming and cutting

Drag across any chart to select a section. The selection is highlighted on
every chart and on the map. From the selection bar you can:

- **View selection**: open a *temporary* trimmed view. All stats, charts,
  splits, zones and best efforts are recalculated for that section only. The
  range is kept in the URL (`#/activity/3?start=600&end=1800`), so the stored
  activity never changes. You can trim again inside a trimmed view.
- **Cut to new file**: download the section as GPX, TCX or FIT. The exported
  files import back into this app and into other tools; FIT files contain
  file_id, record, lap, session and activity messages with valid CRCs.
- **Save as activity**: store the section as a new, independent activity.

The full activity can also be exported in any of the three formats.

### Laps

When a track obviously repeats (a running track, a criterium circuit, a loop
ridden twice), the activity page shows **Repeating laps detected** with an
**Analyze laps** button. Detection works on GPS alone, so it doesn't depend on
the device's lap button or auto-lap settings:

- candidate "gates" along the track are tested; for each, every pass through it
  (always in the same direction) is found;
- consecutive laps must agree in length (within 12 %) and in shape (laps are
  resampled and compared with the median lap);
- the gate explaining the longest run of such laps wins, so warm-up before the
  first lap and cool-down after the last are left out.

The laps view is a temporary trimmed view from the first lap's start to the
last lap's end. It adds:

- **Summary** comparing the whole activity, all laps, the average lap, the
  fastest lap and the selected lap;
- **Lap times** chart with the average marked (click a dot to select that lap);
- **Laps** table with time, difference from the average, pace or speed, HR,
  power, cadence and climbing. Click a row or use the ↑/↓ keys. The selected lap
  is highlighted on the charts and the map, and can be viewed, cut to a file or
  saved like any other selection.

### Map

- **Enlarge / Minimize** switches the map between its card and a near
  full-screen view (Esc minimizes).
- **Colour track by** speed or pace, elevation, heart rate, power, or
  **speed Δ vs average** (blue = slower, gray = about average, red = faster). The
  scale is clipped to the 5th–95th percentile so a GPS spike can't flatten it,
  and a legend shows the range. With a section or lap selected, only that part
  stays coloured and the rest fades, so overlapping laps can be compared.
- **Colours** picks the colour pattern: the default (blue, or blue–red for the
  speed Δ), Rainbow, Turbo, Red hot, Viridis, Plasma, Cool–warm, Green → red or
  Grayscale; **⇄ Reverse** flips it.
- **✚ Pick section**: click the start, then the end of a stretch on the track to
  select it (where the track passes a spot several times, the first pass after
  the previous click is used).

### Segments

A segment is a stretch of track (start → end) whose times are compared across
all activities. Select a stretch (drag across a chart, **✚ Pick section** on
the map, or a lap in the laps view) and click **Create segment**; the same
button in the page header turns the whole activity into a segment, and in the
trimmed-view banner it uses the trimmed part.

An activity has an *effort* on a segment when it passes within 25 m of the
segment start, later within 25 m of its end, covers a similar distance in
between (80–125 %), and stays on the segment's line (95 % of points within
30 m, checked both ways, so shortcuts and detours don't count). Direction
matters, and one activity can have several efforts, for example one per lap.
New uploads are matched automatically; **Rescan activities** re-checks
everything.

- The **Segments** tab (sidebar) lists all segments; a segment page shows its
  map, a **best efforts** leaderboard (fastest first) and the **activities**
  that contain it. Each time links to that effort in its activity.
- On an activity, the **Segments** card lists its efforts with their rank
  (🏆 for the best time). Click a row to highlight the effort on the charts
  and map, use **View** for a trimmed view, or follow the name to the segment.

Across activities: totals, weekly or monthly trend charts (distance, time,
elevation, training load, count), personal records per sport, and an all-time
power curve.

Athlete settings (max HR, resting HR, FTP) drive zones, TRIMP, IF and TSS.
Saving new settings recalculates every stored activity.

## Running

The quickest way is the run script (any OS, any Python 3.10+). It creates
`.venv` and installs the requirements on first run, and again whenever they
change:

```bash
python scripts/run.py                        # http://127.0.0.1:8000
python scripts/run.py --port 9000 --reload   # --host 0.0.0.0 to expose on the LAN
python scripts/run.py --tests                # install dev requirements, run pytest
```

In VS Code, **Terminal → Run Build Task** (Ctrl+Shift+B) runs `fit-git: run`;
there are also `fit-git: run (auto-reload)` and `fit-git: tests` tasks.

Manual setup:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
python -m app                   # http://127.0.0.1:8000
```

Options: `python -m app --host 0.0.0.0 --port 8080 --reload`.
The database is stored at `data/activities.db`; set `FITGIT_DB` to change the path.

Drag files onto the page, or use **Upload**. You can upload many files at
once, and duplicate files are skipped by content hash.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/activities` | multipart upload (`files`, repeatable) |
| `GET` | `/api/activities?sport=` | list with summaries |
| `GET` | `/api/activities/{id}?split=km\|mi` | full analysis: summary, series, track, splits, zones, power curve, best efforts |
| `GET` | `/api/activities/{id}?start=&end=` | temporary trimmed view (point indices, inclusive; nothing is saved) |
| `GET` | `/api/activities/{id}/export?format=gpx\|tcx\|fit&start=&end=` | download full activity or trimmed section as a new file |
| `POST` | `/api/activities/{id}/clip` | `{start, end, name?}`: save section as new activity |
| `GET` | `/api/activities/{id}/laps` | detected laps with per-lap, lapped-section and whole-activity summaries (404 if none) |
| `GET` | `/api/activities/{id}/segments` | segment efforts in this activity, with rank |
| `POST` | `/api/segments` | `{activity_id, start, end, name?}`: create a segment and match all activities |
| `GET` | `/api/segments` | list with effort / activity counts and best time |
| `GET` | `/api/segments/{id}` | geometry, efforts (fastest first) and activities containing it |
| `PATCH` / `DELETE` | `/api/segments/{id}` | rename / delete (efforts are removed with it) |
| `POST` | `/api/segments/{id}/rescan` | re-match against every stored activity |
| `PATCH` | `/api/activities/{id}` | `{name, sport}` |
| `DELETE` | `/api/activities/{id}` | delete |
| `GET` | `/api/stats?sport=&period=week\|month` | totals, periods, records, all-time power curve |
| `GET/PUT` | `/api/settings` | `{max_hr, rest_hr, ftp}` |

Interactive docs are at `/docs`.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/samples.py` generates synthetic GPX, TCX and binary FIT files, including
a small FIT encoder, so the tests need no fixture files.

## Layout

```
app/
  parsers.py    FIT / GPX / TCX (+gzip) -> Activity(points)
  analytics.py  numpy-based metrics, splits, zones, power curve, best efforts
  writers.py    GPX / TCX / FIT writers (export, cut to new file)
  laps.py       repeating-lap detection and per-lap summaries
  segments.py   segment geometry and effort matching
  storage.py    SQLite (zlib-compressed point columns)
  main.py       FastAPI routes + static frontend
  static/       index.html, app.js (Chart.js + Leaflet), style.css
tests/
```
