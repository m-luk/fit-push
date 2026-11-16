# OpenStreetMap places

## Intent

Several features want to say *where* something happened in words: "in Tatra National
Park, near Zakopane" names a trip better than coordinates. Asking OpenStreetMap is
also the only place where activity locations leave the machine, so it should happen in
one small, reviewed place with the privacy limits built in, not be copied into every
module that wants a place name. This is a **service module**: it has no page, no card and
no HTTP API; other modules call its versioned services through the SDK.

## How it works

One request to the OpenStreetMap Overpass API per new place (`FITPUSH_OVERPASS_URL`
overrides the endpoint; tests use a local fake). The query asks for:

- national parks (`boundary=national_park`, or `boundary=protected_area` with
  `protect_class=2`) containing the point, else the nearest within 25 km;
- mountain ranges (`natural=mountain_range`) containing the point, else the nearest
  within 60 km;
- the nearest `place=city|town` within 30 km, else the nearest village.

Built-in limits, so consumers cannot get them wrong: the point is rounded to 3 decimals
(~100 m) before it is sent; only the point is sent, never a track; answers are stored per
rounded point, so a place is asked once; requests run one at a time, at most one per
second. Consumers must still ask only on a user action (opening a page that shows the
result counts), offer a switch to turn lookups off, and say what is sent (rule 13 in
`modules/RULES.md`); `about()` gives them the wording.

## Services

Declared in `module.json` `services`; consumers declare what they use in `uses`, for
example `{"osm_places": {"place": 1}}`, and then call
`ctx.service("osm_places", "place")`, which is None when this module is not loaded or
offers another major version. Call services from routes or event handlers: errors
propagate to the caller.

- `place(lat, lon, refresh=False) -> dict` (1.0): the national park, mountain range and
  nearest city or town around a point:

  ```
  {"point": [lat, lon],            # the rounded point that was looked up
   "park":  Feature | None,
   "range": Feature | None,
   "city":  Feature | None,        # city or town; a village when there is none
   "source": "openstreetmap",
   "fetched_at": "2026-11-16T10:00:00+00:00"}
  Feature = {"name": str,          # English name when OpenStreetMap has one
             "inside": bool,       # the point lies inside the area
             "distance_m": float,  # 0 when inside; else to the centre / label point
             "kind": str | None}   # "city" / "town" / "village" for places
  ```

  Stored answers are returned without a request; `refresh=True` asks again. Raises
  `Invalid` for coordinates that are not numbers or out of range, and when the request
  fails or the answer cannot be read (no answer is stored then).
- `about() -> dict` (1.0): `{sends, endpoint, rounding_decimals, min_interval_s}`, for a
  consumer's settings text.

Used by: **adventures** (adventure names and the place line).

Changing a service: adding an optional argument or a result key is a minor bump
(`1.0` -> `1.1`); renaming, removing or changing the meaning of anything is a major bump
(`2.0`), which consumers that declared major 1 then no longer get. See docs/SDK.md,
"Services".

## Data

Reads nothing from the core. Stores `m_osm_places_cache` (rounded point -> the answer
above as JSON). Sends the rounded point to the Overpass endpoint; nothing else leaves
the machine.
