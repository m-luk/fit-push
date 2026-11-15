# fit-push user guide

Everything fit-push can do, page by page. Back to the [README](../README.md).

## Guided tour

Click **🎓 Tour** in the top bar (or **Take the guided tour** on the empty start page). The
tour adds a simulated 5-lap park run, tagged `#tutorial`, and walks you through the app on
it: you open it, select a stretch, zoom in, colour the map, enlarge it, analyse the laps,
make a segment and tag the run. Each step waits until you have done it and then moves on.

- **Skip step** does the step for you, **Back** goes one step back.
- **Exit** (or Esc while the tour card has focus) leaves at any time and asks whether to
  remove the demo data: the tutorial run, clips you saved from it and segments made on them.
  Your own activities and segments are never touched. **Keep it** leaves the run in your list.
- Reloading the page continues the tour where you were.

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

- distance (from the device when present, otherwise GPS haversine), elapsed and moving time (auto-pause detection, with thresholds per sport); during a GPS gap (tunnel, underpass) the distance is spread over the gap instead of arriving in one jump when the fix returns
- average and max speed / pace (speed from the device's own speed reading when the file has one, otherwise from distance over at least 5 s; short spikes are filtered out), elevation gain and loss (smoothed, with hysteresis), elevation range
- heart rate: average and max, time in 5 zones (% of max HR), Banister TRIMP
- power: average, max, Normalized Power, Intensity Factor, TSS, work (kJ), power curve (5 s – 60 min)
- cadence and temperature
- per-km / per-mile splits (moving pace, elevation, HR, power)
- best efforts (fastest 400 m … marathon for running; 5–100 km for cycling)
- charts that share one hover position (elevation, pace/speed, HR, power, cadence, temperature), with the hovered point marked on the map

## Trimming and cutting

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

## Laps

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

## Map

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

## Segments

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

- The **Segments** tab (top navigation bar) lists all segments; a segment page shows its
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

## Tags

Add tags under an activity's title (type and press Enter; pick existing ones from
the suggestions; × removes). Tags are lower-cased and de-duplicated. Filter the
sidebar list by tag, and use them in modules (for example the map).

## Sports

Running, cycling (generic, road, gravel, MTB), walking, hiking, skiing, ski
touring, sailing, kayaking and swimming. Each has its own pace/speed display,
moving-time threshold and best-effort distances. Sports are recognised from FIT
sport + sub-sport, Strava/Garmin activity types and TCX; change one with the sport
picker on the activity page.

## Modules

Optional features (such as the **🗺️ Map** of all activities) are modules. The **Modules**
button in the top bar lists them with their manuals; all manuals are also collected in
[MODULES_MANUAL.md](MODULES_MANUAL.md).
