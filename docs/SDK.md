# fit-push module SDK (version 1.1)

Everything a module may use from the core. If you need something that is not here,
do not reach into `app/` internals: propose an SDK addition as a separate core change
(see `modules/RULES.md`, rule 3). The SDK major version is `1`; modules declare it in
`module.json` as `"sdk": "1"`.

## Backend: `backend.py`

```python
from app.sdk import ModuleContext  # the only allowed import from the core


def register(ctx: ModuleContext) -> None: ...
```

`register` runs once at start-up. If it raises, the module is switched off and the
error shows on the Modules page; the core keeps running.

### `ctx` attributes

| Name | What it is |
|---|---|
| `ctx.id` | the module id (`"activity_map"`) |
| `ctx.manifest` | the parsed `module.json` |
| `ctx.dir` | `Path` of the module folder (read-only use) |
| `ctx.router` | FastAPI `APIRouter`, mounted at **`/api/m/<id>`**. Define routes with `@ctx.router.get("/x")`. |
| `ctx.core` | `CoreAPI`, see below |
| `ctx.db` | `ModuleDB`, see below |
| `ctx.on(event, handler)` | call `handler(**payload)` after a core event |
| `ctx.log` | `logging.Logger` named `fitpush.module.<id>` |
| `ctx.provide(name, fn)` | offer `fn` to other modules as a service *(1.1)* |
| `ctx.service(module_id, name)` | another module's service, or `None` when that module is not loaded *(1.1)* |

### `ctx.core` (CoreAPI)

| Method | Returns |
|---|---|
| `list_activities(sport=None, tag=None)` | newest first; each has `id, name, sport, start_time, filename, source_format, device, created_at, summary` (dict, SI units: `distance_m`, `moving_s`, `elapsed_s`, `avg_speed_ms`, `avg_hr`, `elev_gain_m`, `has_gps`, …), `tags` (list) |
| `activity(id)` | the same fields for one activity; raises `NotFound` |
| `points(id)` | cleaned point columns `{t, lat, lon, ele, hr, cad, power, speed, temp, dist}` (lists, `None` for gaps; `t` = UNIX seconds). Indices match all other indices in the app. |
| `analyse(cols, sport)` | the core analysis of point columns: `summary`, `series`, `splits`, `hr_zones`, `power_curve`, `best_efforts` |
| `track(id, step_m=20, max_points=600)` | GPS line `[[lat, lon], ...]`, thinned to ~`step_m` spacing |
| `sports()` | sport catalogue: `key, label, icon, family, pace, moving_ms, cadence_unit` |
| `settings()` | athlete settings `{max_hr, rest_hr, ftp}` |
| `tags()` | `[{tag, count}]` |
| `segments()` | segments (without geometry) with effort counts |
| `set_tags(id, tags)` | replace an activity's tags (normalised; emits `activity.updated`) |
| `peek_file(filename, data)` | parse a FIT/GPX/TCX file (optionally `.gz`) without storing it: `{sha256, duplicate_of, name, sport, start_time}`; `duplicate_of` is the id of an activity with the same bytes or `None`. *(1.1)* |
| `import_file(filename, data)` | import a file like an upload: `{status: "imported" \| "duplicate", id, ...}`; emits `activity.imported` for new ones. *(1.1)* |
| `update_activity(id, name=None, sport=None)` | rename and/or change the sport (summary, segment efforts refreshed; emits `activity.updated`); returns the activity like `activity()`. *(1.1)* |

Exceptions: `from app.sdk import NotFound, Invalid`. Raising them in a route gives
HTTP 404 / 422.

`peek_file` and `import_file` raise `Invalid` for files the core cannot read.

### Services between modules *(1.1)*

A module can let others use one of its functions without them touching its tables:

```python
ctx.provide("assign", assign)  # in module "gear"
assign = ctx.service("gear", "assign")  # in another module, when needed
if assign:  # None: gear is not loaded
    assign(activity_id, gear_id)
```

Look services up when you use them, not in `register` (load order is only guaranteed
for modules listed in `depends`). Errors raised by a service propagate to the caller,
so call them where your own errors are contained (a route or an event handler). A
provider documents its services in its README; treat them as part of its contract.

### Events

| Event | Payload |
|---|---|
| `activity.imported` | `activity_id` (upload or clip) |
| `activity.updated` | `activity_id`, `fields` (list of `name`, `sport`, `tags`) |
| `activity.deleted` | `activity_id` |
| `settings.changed` | `settings` |
| `segment.changed` | `segment_id` |
| `segment.deleted` | `segment_id` |

Handlers run synchronously after the core change has been committed. Keep them quick.
A failing handler is logged and shown on the Modules page; it never breaks the core.

### `ctx.db` (ModuleDB)

SQLite in the app's database, restricted to your own tables:

```python
T = ctx.db.table("notes")  # -> "m_<id>_notes"
ctx.db.script(f"CREATE TABLE IF NOT EXISTS {T} (activity_id INTEGER PRIMARY KEY, text TEXT)")
ctx.db.execute(f"INSERT OR REPLACE INTO {T} VALUES (?, ?)", (aid, text))
rows = ctx.db.query(f"SELECT * FROM {T} WHERE activity_id = ?", (aid,))  # list of dicts
```

Writes (`INSERT/UPDATE/DELETE/CREATE/DROP/ALTER`) to anything not named
`m_<id>_*` raise `PermissionError`. Read core data through `ctx.core`, not SQL.
Clean up your rows in an `activity.deleted` handler.

## Frontend: `frontend.js` (+ optional `frontend.css`)

Plain JavaScript (no build step), loaded after the core. Wrap it in an IIFE and use
only `window.fitpush` plus the page globals `L` (Leaflet 1.9.4) and `Chart`
(Chart.js 4.4.1).

```js
// <Name> (frontend): registers ... Uses only window.fitpush.
(() => {
  "use strict";
  const sdk = window.fitpush;
  sdk.registerPage({ module: "my_mod", label: "My page", icon: "🧩", async render(el, ctx) { ... } });
})();
```

### Registration

| Call | Effect |
|---|---|
| `sdk.registerPage({module, id?, label, icon?, render(el, ctx)})` | adds a sidebar tab and the route `#/m/<id>` (`id` defaults to the module id) |
| `sdk.registerActivityCard({module, title, order?, render(el, ctx)})` | adds a card on every activity page (below the data streams). Return `false` from `render` to hide it for that activity. |

`render` may be `async`. If it throws, the user sees an error box in your area and the
rest of the app keeps working.

**Page `ctx`:** `params` (`URLSearchParams` from the URL), `setParams(obj)` (store state
in the URL without re-rendering), `onCleanup(fn)`, `isStale()` (call after every `await`;
`true` means the user navigated away, so stop), `sdk`.

**Activity card `ctx`:** `activity` (the full analysis the page uses: `id, name, sport,
tags, summary, series` with `series.idx` absolute indices, `window`, `laps`,
`segment_efforts`), `select(start, end, label)` (highlight absolute point indices on the
charts and map, with your label in the selection bar), `onCleanup(fn)`, `sdk`.

### Helpers

| Name | Use |
|---|---|
| `sdk.api(path, opts)` | `fetch` + JSON; throws `Error(detail)` on HTTP errors. Your API is under `/api/m/<id>/`. |
| `sdk.toast(msg)` | short message at the bottom |
| `sdk.askName(title, hint, default, okLabel)` | in-page text dialog → `Promise<string or null>` (never use `prompt()`) |
| `sdk.esc(text)` | HTML-escape; **always** escape interpolated text |
| `sdk.css("--token")` | value of a design token (colours: `--m-*`, `--cat-1..8`, `--cat-other`, `--ov-1..7`, `--dv-1..7`, `--text-*`, `--surface-*`, `--accent`, `--sel-edge`) |
| `sdk.fmt.num/dist/ele/dur/pace/speed/date/day`, `sdk.fmt.units()` | formatting in the user's units (`units()` gives `distL`, `speedL`, `eleL`, …) |
| `sdk.sports.list()/get(key)/icon(key)/name(key)/isPace(key)` | sport catalogue |
| `sdk.tags()` | `[{tag, count}]` |
| `sdk.map(el, leafletOptions)` | Leaflet map with the standard tiles, removed automatically on navigation |
| `sdk.chart(canvas, config)` | Chart.js chart, destroyed automatically on navigation |
| `sdk.chartStyle.scales(xTitle)` / `.tooltip(extra)` | the core's axis and tooltip styling |
| `sdk.navigate(hash)` | go to `#/activity/12`, `#/m/other`, … |

Reuse the core's CSS classes (`card`, `page-head`, `sub`, `tiles/tile`, `btn`,
`seg`, `table-scroll`, `badge`, `muted`, `map-legend`, `lg-*`). Prefix your own
classes with a short module prefix (e.g. `am-` for activity_map) and use tokens for
every colour, so light and dark themes both work.

## Testing

`modules/<id>/tests/test_<id>.py` with the shared fixtures:

```python
from tests.helpers import upload  # upload(client, filename, bytes) -> id
from tests.samples import synthetic_track, lap_track, to_gpx, to_fit


def test_x(make_client):
    client = make_client(modules="my_mod")  # fresh database with just your module
    aid = upload(client, "run.gpx", to_gpx(synthetic_track()))
    assert client.get("/api/m/my_mod/x").status_code == 200
```

The core suite runs with all modules loaded as well as core-only, so a module that
breaks core behaviour fails CI even if its own tests pass.
