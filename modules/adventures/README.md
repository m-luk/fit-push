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

- **Traverse**: one continuous line that goes somewhere. In time order, every activity
  starts within `traverse_link_m` (default 1 km) of where the previous one ended, and at
  least half of the activities are point-to-point (they end more than `base_radius_m`
  from their start). A loop from camp in between is fine; a bus ride is not.
- **Multi-day**: every other group: outings from one base, hut to hut with gaps, a trip
  with loops from a few places.

**Autodetect** walks the candidate activities in time order (GPS and a start time, the
allowed sports, none of the excluded tags, not yet in an adventure). An activity joins
the current group when at most `max_gap_days` calendar days without activity lie between
it and the group's last day, and it starts within `traverse_link_m` of the previous end
or within `base_radius_m` (default 2 km) of any start or end of the group. Starts at a
**home** location (a place with starts in at least `home_weeks` different weeks) never
link, so everyday training from home is not proposed. A group with at least `min_days`
days becomes a proposal, typed by the rule above (`max_gap_m` is its largest gap between
the end of one track and the start of the next). Dismissed proposals are remembered and
not shown again.

The adventure view also gives the highest point (`ele_max_m` of the activity summaries),
the longest day and the day with the biggest climb, and per activity a thinned line
(~25 m) with elevation, speed and heart rate per point, so the map can be coloured by a
measure like the activity map.

Endpoints (under `/api/m/adventures`):

- `GET /settings`, `PUT /settings`: detection settings `{sports, exclude_tags,
  max_gap_days, traverse_link_m, base_radius_m, min_days, home_weeks, osm_names}`; `sports` empty =
  any sport (mixed adventures allowed); `exclude_tags` defaults to `["commute"]`.
- `GET /suggestions`: proposals `{key, type, name, activity_ids, first_day, last_day,
  days, max_gap_m, distance_m, activities}`; `POST /suggestions/dismiss` `{key}`; `POST /suggestions/reset`
  forgets dismissed proposals.
- `GET /adventures`: all adventures with totals; `POST /adventures` `{name, type,
  activity_ids}`.
- `GET /adventures/{id}`: activities (with day number and track), totals, per-day rows,
  fastest/slowest day, averages per day and per activity; `PATCH` `{name, type, notes}`;
  `PUT /adventures/{id}/activities` `{activity_ids}`; `DELETE` (keeps the activities and
  forgets dismissed proposals that contain any of them, so they can be proposed again).
- `GET /activities?from=&to=`: compact activity list for the "add activities" picker.
- `GET /tracks?ids=1,2`: GPS lines for the map preview of an unfolded proposal
  (proposals also carry `activities` with id, name, sport, start time and distance).
- `GET /activity/{id}`: adventures containing one activity (for the header line).

Events: `activity.deleted` removes the activity from adventures (an adventure left empty
is deleted); start/end points are cached in memory per activity id.

UI: page **Adventures** (`#/m/adventures`, one adventure at `#/m/adventures?id=<id>`)
with the saved adventures (shown at once), then the proposals (detected in the
background; **Detect again** runs detection once more), settings and the adventure view: tiles, per-day table and a
map coloured by activity, by day or as one total line, with a day filter. A header line
on activity pages links to the adventures the activity belongs to.

## Data

Reads activities, summaries, tags and thinned GPS tracks through `ctx.core`. Stores
`m_adventures_adventures` (id, name, type, notes, created_at),
`m_adventures_members` (adventure_id, activity_id), `m_adventures_settings`
(key, JSON value) and `m_adventures_dismissed` (proposal key = sorted activity ids).
