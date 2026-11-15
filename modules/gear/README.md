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

Services for other modules (`ctx.service("gear", name)`, used by importers):

- `ensure(name, kind="other", notes="") -> id`: the item with that name (case-insensitive),
  created when missing.
- `assign(activity_id, gear_id)`: use the item on the activity, replacing its gear of the
  same kind; counts as a manual choice.
- `add_defaults(gear_id, sports) -> [targets]`: make the item the default for these sport
  keys where its kind has no default yet (existing defaults are never taken over).

Frontend: the **Gear** page (`#/m/gear`) lists items with totals and a limit bar, with
forms to add/edit them and pick their defaults, and a **No gear** view (`?view=nogear`,
`&sport=`) listing activities without gear with checkboxes to add an item to many at
once; the **Gear** activity card shows and
changes the gear of one activity (hidden while no gear exists).

## Data

Reads activities (sport, distance, moving time, start) and the sport catalogue through
the SDK. Stores `m_gear_items` (the gear), `m_gear_defaults` (target, kind -> gear),
`m_gear_use` (activity -> gear) and `m_gear_manual` (activities whose gear was chosen
by hand).
