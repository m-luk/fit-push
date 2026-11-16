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
  max_gap_days, traverse_max_m, base_radius_m, min_days, home_weeks}`; `sports` empty =
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
(key, JSON value) and `m_adventures_dismissed` (proposal key = sorted activity ids).
