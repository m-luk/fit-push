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

Across activities: totals, weekly or monthly trend charts (distance, time,
elevation, training load, count), personal records per sport, and an all-time
power curve.

Athlete settings (max HR, resting HR, FTP) drive zones, TRIMP, IF and TSS.
Saving new settings recalculates every stored activity.

## Running

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
  storage.py    SQLite (zlib-compressed point columns)
  main.py       FastAPI routes + static frontend
  static/       index.html, app.js (Chart.js + Leaflet), style.css
tests/
```
