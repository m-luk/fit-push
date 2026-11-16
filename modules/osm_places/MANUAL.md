# OpenStreetMap places

## What it does

Finds the national park, the mountain range and the nearest city or town around a place
on your activities, using OpenStreetMap. It has no page of its own: other modules use it,
for example **Adventures** to name a trip "2026-07 Tatra National Park, Zakopane".

## How to use

1. Nothing to set up. Keep this module enabled (it is by default) for the modules that
   use it to show place names; the **Modules** page lists it as loaded.
2. Turn lookups on or off in the module that uses them (for Adventures:
   **Detection settings** → **Use OpenStreetMap for place names**).
3. To stop all lookups at once, start fit-push without this module, for example
   `python scripts/run.py --modules adventures,gear` (every module except this one).

## Limitations

- Needs an internet connection; a lookup takes a few seconds and runs at most once per
  second.
- Each lookup sends one point, rounded to about 100 m, to the OpenStreetMap Overpass API.
  Answers are remembered per point, so the same place is not asked again.
- OpenStreetMap often maps a mountain range as a label point or a ridge line, so a large
  range may be missed or a neighbouring one chosen; parks are found when the point is
  inside one or within 25 km of its centre.
