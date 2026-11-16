# Adventures

## Intent

A trip is rarely one activity: a bikepacking traverse is a chain of daily rides, a hut
tour or a ski week is several outings from the same base. Single activities hide the
whole picture. This module lets users group activities into **adventures**, see them on
one map and read totals, per-day numbers, the fastest and slowest day and averages per
day and per activity. It also finds likely adventures on its own and proposes them.
It is a module because grouping trips is optional and needs its own page; the core data
model stays untouched (an adventure only references activity ids).

## How it works

Two adventure types:

- **Traverse**: a chain of tracks where each activity starts near where an earlier one
  ended (default: within 10 km).
- **Multi-day**: activities that start from the same base (default: within 2 km of the
  first start) on consecutive days.

**Autodetect** walks the candidate activities in time order (GPS and a start time, the
allowed sports, none of the excluded tags, not yet in an adventure). An activity joins
the current group when at most `max_gap_days` calendar days without activity lie between
it and the group's last day, and it starts within `traverse_max_m` of an end point of
the group or within `base_radius_m` of the group's base. Starts at a **home** location
(a place with starts in at least `home_weeks` different weeks) never link, so everyday
training from home is not proposed. A group with at least `min_days` days becomes a
proposal: multi-day when every start is near the base, otherwise traverse. Dismissed
proposals are remembered and not shown again.

Endpoints (under `/api/m/adventures`):

- `GET /settings`, `PUT /settings`: detection settings `{sports, exclude_tags,
  max_gap_days, traverse_max_m, base_radius_m, min_days, home_weeks, osm_names}`; `sports` empty =
  any sport (mixed adventures allowed); `exclude_tags` defaults to `["commute"]`.
- `GET /suggestions`: proposals `{key, type, name, activity_ids, first_day, last_day,
  days, distance_m}`; `POST /suggestions/dismiss` `{key}`; `POST /suggestions/reset`
  forgets dismissed proposals.
- `GET /adventures`: all adventures with totals; `POST /adventures` `{name, type,
  activity_ids}`.
- `GET /adventures/{id}`: activities (with day number and track), totals, per-day rows,
  fastest/slowest day, averages per day and per activity; `PATCH` `{name, type, notes}`;
  `PUT /adventures/{id}/activities` `{activity_ids}`; `DELETE`.
- `GET /activities?from=&to=`: compact activity list for the "add activities" picker.
- `GET /tracks?ids=1,2`: GPS lines for the map preview of an unfolded proposal
  (proposals also carry `activities` with id, name, sport, start time and distance).
- `POST /place` `{activity_ids}`: the national park and nearest city around the route,
  `{point, park: {name, inside, distance_m}, city: {name, kind, distance_m}, name}`, where
  `name` is the proposed adventure name `"YYYY-MM Park, City"` (only the parts found).
  `POST /adventures/{id}/place` does the same for an adventure and stores the result;
  `POST /adventures` accepts that result as `place`.

**OpenStreetMap lookup** (rule 13 exception): only on a user action (**Create** on a
proposal, **Find place**) and only when the `osm_names` setting is on (default). It sends
one point, the middle of the route rounded to 3 decimals (~100 m), to the Overpass API
(`FITPUSH_OVERPASS_URL` overrides the endpoint; tests use a local fake). The query
asks for national parks (`boundary=national_park` or `boundary=protected_area` with
`protect_class=2`) containing the point, else the nearest one within 25 km, and the
nearest `place=city|town` within 30 km (a village when there is none).
- `GET /activity/{id}`: adventures containing one activity (for the header line).

Events: `activity.deleted` removes the activity from adventures (an adventure left empty
is deleted); start/end points are cached in memory per activity id.

UI: page **Adventures** (`#/m/adventures`, one adventure at `#/m/adventures?id=<id>`)
with proposals, the list, settings and the adventure view: tiles, per-day table and a
map coloured by activity, by day or as one total line, with a day filter. A header line
on activity pages links to the adventures the activity belongs to.

## Data

Reads activities, summaries, tags and thinned GPS tracks through `ctx.core`. Stores
`m_adventures_adventures` (id, name, type, notes, created_at),
`m_adventures_members` (adventure_id, activity_id), `m_adventures_settings`
(key, JSON value), `m_adventures_dismissed` (proposal key = sorted activity ids) and
`m_adventures_places` (adventure_id, JSON of the looked-up park and city).
