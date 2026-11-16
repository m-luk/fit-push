# Gear

## Intent

Track how much each piece of equipment (shoes, bikes, skis, boats, …) has been used,
so you know when shoes are worn out or a chain is due. People who record with several
devices rarely get gear into their files, so the module assigns gear automatically:
you pick a **default gear for a discipline** (e.g. running) **or for a whole group of
disciplines** (e.g. all cycling), and every imported activity gets it. You can still
change the gear of any single activity. Not everyone tracks gear, and it needs its own
page and card, so it is a module rather than core.

## How it works

Backend (`/api/m/gear/...`):

- `GET /gear`: gear items with usage totals (activities, distance including the
  starting distance, moving time, last use), default rules, kinds and sport groups.
- `GET /items`: the items only, without totals (cheap; used by the activity header line).
- `POST /gear`, `PATCH /gear/{id}`, `DELETE /gear/{id}`: manage items (name, kind,
  notes, starting distance, distance limit, retired).
- `PUT /gear/{id}/defaults` `{targets: ["sport:running", "family:cycling", ...]}`: the
  disciplines (`sport:<key>`) and groups (`family:<family>`, the sport catalogue's
  families) this item is the default for. There is at most one default per target and
  kind, so taking a target moves it from another item of the same kind.
- `GET /activity/{id}`, `PUT /activity/{id}` `{gear_ids: [...]}` (manual choice),
  `POST /activity/{id}/reset` (back to defaults).
- `POST /apply-defaults`: give defaults to activities that have no gear yet (e.g.
  activities imported before the module or before the defaults were set).
- `GET /unassigned` (`?sport=`): activities without any gear, newest first (`id, name,
  sport, start_time, distance_m`); `GET /gear` also returns their count as `no_gear`.
- `POST /assign` `{gear_id, activity_ids: [...]}`: add one item to many activities at
  once (replacing their gear of the same kind; counts as a manual choice).

Resolution: for each kind, a default for the exact sport wins over a default for its
group; retired items are never assigned automatically.

Events: `activity.imported` assigns defaults; `activity.updated` with a sport change
re-assigns defaults unless the gear was chosen manually; `activity.deleted` removes the
activity's rows. Changing defaults never rewrites past activities.

Frontend: the **Gear** page (`#/m/gear`) lists items with totals and a limit bar, with
forms to add/edit them and pick their defaults, and a **No gear** view (`?view=nogear`,
`&sport=`) listing activities without gear with checkboxes to add an item to many at
once. On activity pages a compact **Gear** line under the title and tags (an activity
card with `placement: "header"`, SDK 1.2) shows the activity's gear as chips with
**Change** / **Reset**; it is hidden while no gear exists.

## Services

Versioned services for other modules (declared in `module.json` `services`; consumers
declare them in `uses`, e.g. `{"gear": {"ensure": 1}}`). All three are `1.0`. Call them
from your routes or event handlers; errors propagate to the caller.

- `ensure(name, kind="other", notes="") -> id`: the item with that name (case-insensitive),
  created when missing. Raises `Invalid` for an empty name or an unknown kind; names are
  cut to 100 characters.
- `assign(activity_id, gear_id) -> None`: use the item on the activity, replacing its gear
  of the same kind; counts as a manual choice. Raises `NotFound` for an unknown activity
  or item.
- `add_defaults(gear_id, sports) -> [targets]`: make the item the default for these sport
  keys where its kind has no default yet (existing defaults are never taken over).
  Returns the targets added (`"sport:<key>"`); unknown sport keys are skipped.

Used by: **strava_import** (gear from a Strava export).

## Data

Reads activities (sport, distance, moving time, start) and the sport catalogue through
the SDK. Stores `m_gear_items` (the gear), `m_gear_defaults` (target, kind -> gear),
`m_gear_use` (activity -> gear) and `m_gear_manual` (activities whose gear was chosen
by hand).
