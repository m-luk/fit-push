"""Parsers for sports device files: GPX, TCX and FIT (optionally gzip-compressed).

Every parser returns an :class:`Activity` with a flat list of :class:`Point`
records. Missing channels are ``None``; analytics decide what they can compute.
"""
from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

SEMICIRCLE = 180.0 / 2**31


class ParseError(ValueError):
    pass


@dataclass
class Point:
    t: datetime | None = None
    lat: float | None = None
    lon: float | None = None
    ele: float | None = None
    hr: float | None = None
    cad: float | None = None
    power: float | None = None
    speed: float | None = None  # m/s as reported by the device
    temp: float | None = None
    dist: float | None = None  # cumulative metres as reported by the device


@dataclass
class Activity:
    name: str | None = None
    sport: str = "unknown"
    source_format: str = ""
    device: str | None = None
    points: list[Point] = field(default_factory=list)


SPORT_ALIASES = {
    "running": "running", "run": "running", "trail_running": "running", "treadmill": "running",
    "cycling": "cycling", "biking": "cycling", "bike": "cycling", "ride": "cycling",
    "mountain_biking": "cycling", "road_biking": "cycling", "virtual_ride": "cycling",
    "e_biking": "cycling",
    "walking": "walking", "walk": "walking",
    "hiking": "hiking", "hike": "hiking",
    "swimming": "swimming", "swim": "swimming",
}


def normalise_sport(raw: str | None) -> str:
    if not raw:
        return "unknown"
    key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    return SPORT_ALIASES.get(key, key or "unknown")


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# --------------------------------------------------------------------------- GPX

def parse_gpx(data: bytes) -> Activity:
    import gpxpy
    import gpxpy.gpx

    try:
        gpx = gpxpy.parse(io.BytesIO(data).read().decode("utf-8-sig", errors="replace"))
    except gpxpy.gpx.GPXException as exc:
        raise ParseError(f"invalid GPX: {exc}") from exc

    act = Activity(source_format="gpx", device=gpx.creator)
    sources = []
    for trk in gpx.tracks:
        act.name = act.name or trk.name
        if trk.type:
            act.sport = normalise_sport(trk.type)
        for seg in trk.segments:
            sources.extend(seg.points)
    if not sources:  # fall back to routes, then waypoints
        for rte in gpx.routes:
            act.name = act.name or rte.name
            sources.extend(rte.points)
    act.name = act.name or gpx.name

    for p in sources:
        pt = Point(t=_utc(p.time), lat=p.latitude, lon=p.longitude, ele=_float(p.elevation))
        for ext in getattr(p, "extensions", None) or []:
            for el in ext.iter():
                name = _local(el.tag).lower()
                val = _float(el.text)
                if val is None:
                    continue
                if name in ("hr", "heartrate"):
                    pt.hr = val
                elif name in ("cad", "cadence"):
                    pt.cad = val
                elif name in ("power", "watts"):
                    pt.power = val
                elif name in ("atemp", "wtemp", "temp"):
                    pt.temp = val
                elif name == "speed":
                    pt.speed = val
        act.points.append(pt)
    return act


# --------------------------------------------------------------------------- TCX

def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el, *path):
    for name in path:
        if el is None:
            return None
        el = _child(el, name)
    return el.text if el is not None else None


def parse_tcx(data: bytes) -> Activity:
    try:
        root = ET.fromstring(data.lstrip())
    except ET.ParseError as exc:
        raise ParseError(f"invalid TCX: {exc}") from exc

    act = Activity(source_format="tcx")
    for activity in root.iter():
        if _local(activity.tag) != "Activity":
            continue
        act.sport = normalise_sport(activity.get("Sport"))
        creator = _child(activity, "Creator")
        if creator is not None:
            act.device = _text(creator, "Name")
        notes = _text(activity, "Notes")
        if notes:
            act.name = notes.strip()[:120]
        for tp in activity.iter():
            if _local(tp.tag) != "Trackpoint":
                continue
            t = _text(tp, "Time")
            pt = Point(
                t=_utc(datetime.fromisoformat(t.strip().replace("Z", "+00:00"))) if t else None,
                lat=_float(_text(tp, "Position", "LatitudeDegrees")),
                lon=_float(_text(tp, "Position", "LongitudeDegrees")),
                ele=_float(_text(tp, "AltitudeMeters")),
                dist=_float(_text(tp, "DistanceMeters")),
                hr=_float(_text(tp, "HeartRateBpm", "Value")),
                cad=_float(_text(tp, "Cadence")),
            )
            ext = _child(tp, "Extensions")
            if ext is not None:
                for el in ext.iter():
                    name = _local(el.tag)
                    if name == "Speed":
                        pt.speed = _float(el.text)
                    elif name == "Watts":
                        pt.power = _float(el.text)
                    elif name == "RunCadence" and pt.cad is None:
                        pt.cad = _float(el.text)
            act.points.append(pt)
        break  # one activity per file
    return act


# --------------------------------------------------------------------------- FIT

def parse_fit(data: bytes) -> Activity:
    import fitdecode

    act = Activity(source_format="fit")
    try:
        with fitdecode.FitReader(
            io.BytesIO(data),
            check_crc=fitdecode.CrcCheck.WARN,
            error_handling=fitdecode.ErrorHandling.WARN,
        ) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    act.points.append(_fit_record(frame))
                elif frame.name in ("session", "sport"):
                    sport = _fit_get(frame, "sport")
                    sub = _fit_get(frame, "sub_sport")
                    if sport is not None and act.sport == "unknown":
                        act.sport = normalise_sport(sport)
                        if sub in ("virtual_activity", "indoor_cycling") and act.sport == "cycling":
                            act.sport = "cycling"
                    name = _fit_get(frame, "name")
                    if name and not act.name:
                        act.name = str(name)
                elif frame.name == "file_id":
                    manu = _fit_get(frame, "manufacturer")
                    prod = _fit_get(frame, "garmin_product") or _fit_get(frame, "product")
                    if manu:
                        act.device = " ".join(str(x) for x in (manu, prod) if x)
    except fitdecode.FitError as exc:
        if not act.points:
            raise ParseError(f"invalid FIT: {exc}") from exc
    return act


def _fit_get(frame, name):
    try:
        return frame.get_value(name, fallback=None)
    except Exception:  # noqa: BLE001 - fitdecode raises KeyError variants
        return None


def _fit_record(frame) -> Point:
    lat = _fit_get(frame, "position_lat")
    lon = _fit_get(frame, "position_long")
    ele = _fit_get(frame, "enhanced_altitude")
    if ele is None:
        ele = _fit_get(frame, "altitude")
    speed = _fit_get(frame, "enhanced_speed")
    if speed is None:
        speed = _fit_get(frame, "speed")
    ts = _fit_get(frame, "timestamp")
    return Point(
        t=_utc(ts) if isinstance(ts, datetime) else None,
        lat=lat * SEMICIRCLE if isinstance(lat, (int, float)) else None,
        lon=lon * SEMICIRCLE if isinstance(lon, (int, float)) else None,
        ele=_float(ele),
        hr=_float(_fit_get(frame, "heart_rate")),
        cad=_float(_fit_get(frame, "cadence")),
        power=_float(_fit_get(frame, "power")),
        speed=_float(speed),
        temp=_float(_fit_get(frame, "temperature")),
        dist=_float(_fit_get(frame, "distance")),
    )


# --------------------------------------------------------------------------- dispatch

PARSERS = {"gpx": parse_gpx, "tcx": parse_tcx, "fit": parse_fit}
SUPPORTED_EXTENSIONS = (".gpx", ".tcx", ".fit", ".gpx.gz", ".tcx.gz", ".fit.gz")


def detect_format(filename: str, data: bytes) -> str:
    name = filename.lower()
    for ext in ("gpx", "tcx", "fit"):
        if name.endswith("." + ext):
            return ext
    # sniff content
    if len(data) >= 12 and data[8:12] == b".FIT":
        return "fit"
    head = data[:2048].lower()
    if b"<gpx" in head:
        return "gpx"
    if b"<trainingcenterdatabase" in head:
        return "tcx"
    raise ParseError(f"unsupported file type: {filename}")


def parse_file(filename: str, data: bytes) -> Activity:
    if filename.lower().endswith(".gz") or data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise ParseError(f"invalid gzip: {exc}") from exc
        if filename.lower().endswith(".gz"):
            filename = filename[:-3]
    fmt = detect_format(filename, data)
    act = PARSERS[fmt](data)
    if not act.points:
        raise ParseError("file contains no track points")
    if not act.name:
        stem = filename.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        act.name = stem or "Activity"
    return act
