# All activities map

## Intent

See every recorded route on one big map, to answer "where have I been training?"
and to compare places across time and sports. A single activity's map is in the
core; this module adds the cross-activity view, which needs its own page and
filters and is not needed to analyse one workout, so it is a separate module.

## How it works

The backend endpoint `/api/m/activity_map/tracks` lists activities through
`ctx.core.list_activities()` and filters them by sports, tags and a date range. It
returns each GPS line thinned with `ctx.core.track()` (about one point every 25 m,
at most 400 points), cached in memory per activity and dropped on the
`activity.deleted` event. `/api/m/activity_map/facets` returns the sports, tags and
date span that exist, for the filter controls.

The frontend registers the **Map** page (`#/m/activity_map`). It draws the lines
with `fitgit.map()`, colours them by sport (categorical `--cat-*` tokens, legend
toggles, tooltips) or by date (sequential blue `--ov-*` ramp), and keeps the
filters in the URL so a view can be bookmarked.

## Data

Reads activities, tags and GPS points through the SDK. Stores nothing: no tables,
only an in-memory cache of thinned tracks.
