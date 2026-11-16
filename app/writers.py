"""Writers that serialise point columns back to GPX, TCX and FIT files.

Input is the column dict used everywhere else (``t`` = epoch seconds, ``None``
for missing samples), normally already windowed via
``analytics.window_columns``.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from . import sports

FORMATS = {
    "gpx": "application/gpx+xml",
    "tcx": "application/vnd.garmin.tcx+xml",
    "fit": "application/vnd.ant.fit",
}


class ExportError(ValueError):
    pass


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _rows(cols: dict) -> list[dict]:
    keys = list(cols)
    n = len(cols["t"])
    return [{k: cols[k][i] for k in keys} for i in range(n)]


# --------------------------------------------------------------------------- GPX


def to_gpx(cols: dict, name: str, sport: str) -> bytes:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<gpx version="1.1" creator="fit-push" xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
        'xmlns:gpxpx="http://www.garmin.com/xmlschemas/PowerExtension/v1">\n',
        f"<metadata><name>{escape(name)}</name>",
    ]
    if cols["t"] and cols["t"][0] is not None:
        out.append(f"<time>{_iso(cols['t'][0])}</time>")
    out.append(f"</metadata>\n<trk><name>{escape(name)}</name><type>{escape(sport)}</type><trkseg>\n")
    for p in _rows(cols):
        if p["lat"] is None or p["lon"] is None:
            continue  # GPX trackpoints require a position
        s = f'<trkpt lat="{p["lat"]:.7f}" lon="{p["lon"]:.7f}">'
        if p["ele"] is not None:
            s += f"<ele>{p['ele']:.1f}</ele>"
        if p["t"] is not None:
            s += f"<time>{_iso(p['t'])}</time>"
        tpx = ""
        if p["temp"] is not None:
            tpx += f"<gpxtpx:atemp>{p['temp']:.1f}</gpxtpx:atemp>"
        if p["hr"] is not None:
            tpx += f"<gpxtpx:hr>{round(p['hr'])}</gpxtpx:hr>"
        if p["cad"] is not None:
            tpx += f"<gpxtpx:cad>{round(p['cad'])}</gpxtpx:cad>"
        ext = f"<gpxtpx:TrackPointExtension>{tpx}</gpxtpx:TrackPointExtension>" if tpx else ""
        if p["power"] is not None:
            ext += f"<gpxpx:PowerInWatts>{round(p['power'])}</gpxpx:PowerInWatts>"
        if ext:
            s += f"<extensions>{ext}</extensions>"
        out.append(s + "</trkpt>\n")
    out.append("</trkseg></trk>\n</gpx>\n")
    return "".join(out).encode()


# --------------------------------------------------------------------------- TCX


def to_tcx(cols: dict, name: str, sport: str, distance: list[float]) -> bytes:
    rows = _rows(cols)
    if not rows or rows[0]["t"] is None:
        raise ExportError("TCX export needs timestamps")
    start = _iso(rows[0]["t"])
    total_time = (rows[-1]["t"] or rows[0]["t"]) - rows[0]["t"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">\n',
        f'<Activities><Activity Sport="{sports.get(sport).tcx}"><Id>{start}</Id>\n',
        f'<Lap StartTime="{start}"><TotalTimeSeconds>{total_time:.1f}</TotalTimeSeconds>'
        f"<DistanceMeters>{distance[-1] if distance else 0:.1f}</DistanceMeters>"
        "<Intensity>Active</Intensity><TriggerMethod>Manual</TriggerMethod><Track>\n",
    ]
    for p, d in zip(rows, distance):
        if p["t"] is None:
            continue
        s = f"<Trackpoint><Time>{_iso(p['t'])}</Time>"
        if p["lat"] is not None and p["lon"] is not None:
            s += (
                f"<Position><LatitudeDegrees>{p['lat']:.7f}</LatitudeDegrees>"
                f"<LongitudeDegrees>{p['lon']:.7f}</LongitudeDegrees></Position>"
            )
        if p["ele"] is not None:
            s += f"<AltitudeMeters>{p['ele']:.1f}</AltitudeMeters>"
        s += f"<DistanceMeters>{d:.1f}</DistanceMeters>"
        if p["hr"] is not None:
            s += f"<HeartRateBpm><Value>{round(p['hr'])}</Value></HeartRateBpm>"
        if p["cad"] is not None:
            s += f"<Cadence>{min(254, round(p['cad']))}</Cadence>"
        tpx = ""
        if p["speed"] is not None:
            tpx += f"<ns3:Speed>{p['speed']:.3f}</ns3:Speed>"
        if p["power"] is not None:
            tpx += f"<ns3:Watts>{round(p['power'])}</ns3:Watts>"
        if tpx:
            s += f"<Extensions><ns3:TPX>{tpx}</ns3:TPX></Extensions>"
        out.append(s + "</Trackpoint>\n")
    out.append(
        f"</Track></Lap><Notes>{escape(name)}</Notes>"
        "<Creator><Name>fit-push</Name></Creator></Activity></Activities>\n"
        "</TrainingCenterDatabase>\n"
    )
    return "".join(out).encode()


# --------------------------------------------------------------------------- FIT

_CRC_TABLE = [
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
]
FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z

# base types: (code, struct fmt, invalid value)
ENUM, UINT8, UINT16, SINT32, UINT32 = (
    (0x00, "B", 0xFF),
    (0x02, "B", 0xFF),
    (0x84, "H", 0xFFFF),
    (0x85, "i", 0x7FFFFFFF),
    (0x86, "I", 0xFFFFFFFF),
)
SINT8 = (0x01, "b", 0x7F)


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


class _FitMessage:
    def __init__(self, local: int, global_num: int, fields: list[tuple[int, tuple]]):
        self.local = local
        self.fields = fields
        self.fmt = "<B" + "".join(bt[1] for _, bt in fields)
        self.definition = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields)) + b"".join(
            struct.pack("<BBB", num, struct.calcsize("<" + bt[1]), bt[0]) for num, bt in fields
        )

    def data(self, *values) -> bytes:
        packed = []
        for v, (_, bt) in zip(values, self.fields):
            if v is None:
                packed.append(bt[2])
            else:
                v = int(round(v))
                lo, hi = _range(bt)
                packed.append(bt[2] if not lo <= v <= hi or v == bt[2] else v)
        return struct.pack(self.fmt, self.local, *packed)


def _range(bt) -> tuple[int, int]:
    size = struct.calcsize("<" + bt[1])
    if bt[1].islower():
        return -(2 ** (8 * size - 1)), 2 ** (8 * size - 1) - 1
    return 0, 2 ** (8 * size) - 1


def _fit_ts(ts: float) -> int:
    return int(round(ts)) - FIT_EPOCH


def to_fit(cols: dict, name: str, sport: str, distance: list[float]) -> bytes:
    """Encode a FIT activity file: file_id, event, records, lap, session, activity."""
    rows = [(p, d) for p, d in zip(_rows(cols), distance) if p["t"] is not None]
    if not rows:
        raise ExportError("FIT export needs timestamps")
    t0, t1 = rows[0][0]["t"], rows[-1][0]["t"]
    elapsed = t1 - t0
    total_dist = rows[-1][1] - rows[0][1] if distance else 0.0
    sport_id, sub_sport_id = sports.get(sport).fit
    semi = 2**31 / 180.0

    file_id = _FitMessage(0, 0, [(0, ENUM), (1, UINT16), (2, UINT16), (4, UINT32)])
    event = _FitMessage(1, 21, [(253, UINT32), (0, ENUM), (1, ENUM)])
    record = _FitMessage(
        2,
        20,
        [
            (253, UINT32),
            (0, SINT32),
            (1, SINT32),
            (2, UINT16),
            (3, UINT8),
            (4, UINT8),
            (5, UINT32),
            (6, UINT16),
            (7, UINT16),
            (13, SINT8),
        ],
    )
    lap = _FitMessage(
        3, 19, [(253, UINT32), (2, UINT32), (7, UINT32), (8, UINT32), (9, UINT32), (0, ENUM), (1, ENUM), (25, ENUM)]
    )
    session = _FitMessage(
        4,
        18,
        [
            (253, UINT32),
            (2, UINT32),
            (7, UINT32),
            (8, UINT32),
            (9, UINT32),
            (5, ENUM),
            (6, ENUM),
            (0, ENUM),
            (1, ENUM),
            (25, UINT16),
            (26, UINT16),
        ],
    )
    activity = _FitMessage(5, 34, [(253, UINT32), (0, UINT32), (1, UINT16), (2, ENUM), (3, ENUM), (4, ENUM)])

    body = bytearray()
    body += file_id.definition + file_id.data(4, 255, 0, _fit_ts(t0))  # type=activity, manufacturer=development
    body += event.definition + event.data(_fit_ts(t0), 0, 0)  # timer start
    body += record.definition
    d0 = rows[0][1]
    for p, d in rows:
        ele = p["ele"]
        body += record.data(
            _fit_ts(p["t"]),
            p["lat"] * semi if p["lat"] is not None else None,
            p["lon"] * semi if p["lon"] is not None else None,
            (ele + 500) * 5 if ele is not None else None,
            p["hr"],
            p["cad"],
            (d - d0) * 100 if d is not None else None,
            p["speed"] * 1000 if p["speed"] is not None else None,
            p["power"],
            p["temp"],
        )
    ts1 = _fit_ts(t1)
    body += event.data(ts1, 0, 4)  # timer stop_all
    body += lap.definition + lap.data(
        ts1, _fit_ts(t0), elapsed * 1000, elapsed * 1000, total_dist * 100, 9, 1, sport_id
    )
    body += session.definition + session.data(
        ts1, _fit_ts(t0), elapsed * 1000, elapsed * 1000, total_dist * 100, sport_id, sub_sport_id, 8, 1, 0, 1
    )
    body += activity.definition + activity.data(ts1, elapsed * 1000, 1, 0, 26, 1)

    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    header += struct.pack("<H", fit_crc(header))
    data = header + bytes(body)
    return data + struct.pack("<H", fit_crc(data))
