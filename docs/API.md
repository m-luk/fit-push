# HTTP API

fit-push is a local web app; its JSON API is what the page uses, and you can script it too.
Interactive documentation is served at `/docs` while the app runs.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/activities` | multipart upload (`files`, repeatable) |
| `GET` | `/api/activities?sport=&tag=` | list with summaries and tags |
| `GET` | `/api/activities/{id}?split=km\|mi` | full analysis: summary, series, track, splits, zones, power curve, best efforts, laps, segment efforts, tags |
| `GET` | `/api/activities/{id}?start=&end=` | temporary trimmed view (point indices, inclusive; nothing is saved) |
| `GET` | `/api/activities/{id}/export?format=gpx\|tcx\|fit&start=&end=` | download full activity or trimmed section as a new file |
| `POST` | `/api/activities/{id}/clip` | `{start, end, name?}`: save section as new activity |
| `GET` | `/api/activities/{id}/laps` | detected laps with per-lap, lapped-section and whole-activity summaries (404 if none) |
| `GET` | `/api/activities/{id}/segments` | segment efforts in this activity, with rank |
| `PUT` | `/api/activities/{id}/tags` | `{tags: [...]}`: replace tags, returns the normalised list |
| `GET` | `/api/tags` | all tags with counts |
| `PATCH` | `/api/activities/{id}` | `{name, sport}` |
| `DELETE` | `/api/activities/{id}` | delete |
| `POST` | `/api/segments` | `{activity_id, start, end, name?}`: create a segment and match all activities |
| `GET` | `/api/segments` | list with effort / activity counts and best time |
| `GET` | `/api/segments/{id}` | geometry, efforts (fastest first) and activities containing it |
| `PATCH` / `DELETE` | `/api/segments/{id}` | rename / delete (efforts are removed with it) |
| `POST` | `/api/segments/{id}/rescan` | re-match against every stored activity |
| `GET` | `/api/stats?sport=&period=week\|month` | totals, periods, records, all-time power curve |
| `GET/PUT` | `/api/settings` | `{max_hr, rest_hr, ftp}` |
| `GET` | `/api/sports` | sport catalogue |
| `GET` | `/api/tutorial` | `{activity_id, activities}`: is the tutorial run present |
| `POST` | `/api/tutorial` | create (or reuse) the tutorial run: `{activity_id, created}` |
| `DELETE` | `/api/tutorial` | remove the tutorial run, clips of it and segments made on them |
| `GET` | `/api/version` | `{app: "fit-push", version}` (identifies a running instance) |
| `GET` | `/api/modules` | modules with owner, status and errors |
| `GET` | `/api/modules/{id}/docs/readme\|manual` | a module's intent / manual (Markdown) |
| `*` | `/api/m/{module id}/...` | module APIs (see each module's README) |
