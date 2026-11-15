# Strava import

## Intent

Strava lets you download all your data as one zip ("Download your data": an
`activities.csv`, the original activity files, `bikes.csv`, `shoes.csv`, …). Uploading
the activity files alone loses what you curated on Strava: titles, the activity type,
the bike or shoes, the commute flag, descriptions and private notes. This module reads
the whole zip and brings that data into fit-push: new activities are imported and
activities you already have are matched and updated. It serves people moving from (or
backing up) Strava, so it is a module rather than core.

## How it works

Backend (`/api/m/strava_import/...`):

- `POST /import` (multipart: `file` = the zip; form fields `dry_run`, `import_new`,
  `sport`, `name`, `gear`, `commute`, `notes`, each `true`/`false`, default `true`
  except `dry_run`): reads the export and returns a report
  `{activities, matched, imported, updated: {sport, name, gear, commute, notes},
  gear_items, unmapped_types, errors, changes: [...]}`. With `dry_run=true` nothing is
  written and the report lists what would change.
- `GET /activity/{id}`: the Strava data stored for one activity (Strava id, type, gear,
  description, private note), or `null` when it has none.

Reading the export: `activities.csv` is found anywhere in the zip. Columns are taken by
position (Strava localises the header and the type names; the first 13 columns are
stable: id, date, name, type, description, …, commute (9), private note (10), gear (11),
file (12)). Type names are mapped from English and Polish; unknown types are reported
and the sport is left alone.

Matching: each referenced activity file is parsed with `ctx.core.peek_file`. It is the
same activity when the bytes are identical or the start time is within 60 s of an
existing activity (so files uploaded earlier from the device match too). Otherwise it is
imported with `ctx.core.import_file`.

Updates (each can be switched off):

- **sport**: the Strava type, except that a generic Strava type ("Ride") never
  replaces a more specific sport of the same group (road, gravel, MTB);
- **name**: the Strava title;
- **gear** (needs the **Gear** module, used through its services `ensure`, `assign`,
  `add_defaults`): bikes and shoes from `bikes.csv` / `shoes.csv` become gear items
  (brand and model in the notes), their Strava default sports become gear defaults where
  none exist, and each activity gets its Strava gear (replacing gear of the same kind);
- **commute**: the tag `commute` is added to commutes;
- **notes**: description and private note are stored by this module and shown on the
  activity page.

Frontend: the **Strava import** page (`#/m/strava_import`) with a file picker, the
options, **Preview** (dry run) and **Import** buttons and the report; the **Strava**
activity card shows the description, private note and a link to the activity on Strava
(hidden for activities without Strava data).

## Data

Reads the uploaded zip (only `activities.csv`, `bikes.csv`, `shoes.csv` and the
activity files it references; nothing is kept on disk and nothing is sent anywhere).
Stores `m_strava_import_activities` (activity id -> Strava id, type, gear name,
description, private note, import time). Core data changes only through the SDK
(import, rename, sport, tags), gear through the Gear module's services.
