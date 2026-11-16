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
- **Multi-day**: every other group: outings from one base, hikes from trailheads in
  neighbouring valleys, hut to hut with gaps, a trip with loops from a few places.

**Autodetect** walks the candidate activities in time order (GPS and a start time, the
allowed sports, none of the excluded tags, not yet in an adventure). An activity joins
the current group when at most `max_gap_days` calendar days without activity lie between
it and the group's last day, and it starts within `traverse_link_m` of the previous end
or within `area_radius_m` (default 20 km) of any start or end of the trip so far: the
*same area*, so trailheads in neighbouring valleys belong together (tuned on a real
Tatra week with starts 7-17 km apart). **Home** spots are clusters of starts
(`base_radius_m`, 2 km) used in at least `home_weeks` (default 15) different weeks. An
activity that starts and ends within `home_radius_m` (default 10 km) of a home spot is
everyday training: it is skipped and ends the current trip. One that starts near home but
ends away can begin a trip (leaving home on a traverse) but never joins one. A
mountain trailhead visited in a few weeks a year stays below `home_weeks`, so trips there
are found. A group with at least `min_days`
days becomes a proposal, typed by the rule above (`max_gap_m` is its largest gap between
the end of one track and the start of the next). Dismissed proposals are remembered and
not shown again.

The adventure view also gives the highest point (`ele_max_m` of the activity summaries),
the longest day and the day with the biggest climb, and per activity a thinned line
(~25 m) with elevation, speed and heart rate per point, so the map can be coloured by a
measure like the activity map.

Endpoints (under `/api/m/adventures`):

- `GET /settings`, `PUT /settings`: detection settings `{sports, exclude_tags,
  max_gap_days, traverse_link_m, area_radius_m, base_radius_m, min_days, home_weeks,
  home_radius_m}`; `sports` empty =
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
- `PUT /adventures/{id}/tiles` `{keys, scope}`: choose and order the summary tiles,
  `scope: "adventure"` for this adventure only or `"type"` as the default of its type
  (which also drops this adventure's own choice); `keys: null` goes back to the defaults
  of that scope. `GET /adventures/{id}` returns `tiles: {keys, source}` (`adventure`,
  `type` or `default`) and every `tile_keys`; `GET /tiles` the defaults per type.
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
(key, JSON value; `tiles` holds the tile defaults per type), `m_adventures_dismissed`
(proposal key = sorted activity ids) and `m_adventures_tiles` (adventure_id, its own
tile keys).
