"""Synthetic activity generators (GPX, TCX and binary FIT) for tests and demos."""
from __future__ import annotations

import math
import struct
from datetime import datetime, timedelta, timezone

START = datetime(2026, 11, 1, 8, 0, 0, tzinfo=timezone.utc)
LAT0, LON0 = 52.2297, 21.0122
M_PER_DEG_LAT = 111_195.0


def synthetic_track(seconds=1800, speed=3.0, pause=(600, 660), start=START, with_power=False):
    """Straight-ish track heading north at ``speed`` m/s with a pause window.

    Returns a list of dicts with t, lat, lon, ele, hr, cad, power, dist.
    """
    pts, dist = [], 0.0
    for i in range(seconds + 1):
        if i > 0 and not (pause[0] <= i < pause[1]):
            dist += speed
        pts.append({
            "t": start + timedelta(seconds=i),
            "lat": LAT0 + dist / M_PER_DEG_LAT,
            "lon": LON0,
            "ele": 100 + 20 * math.sin(dist / 1000.0),
            "hr": 120 + min(50, i / 30),
            "cad": 0 if pause[0] <= i < pause[1] else 85,
            "power": (200 + 50 * math.sin(i / 60)) if with_power and not (pause[0] <= i < pause[1]) else (0 if with_power else None),
            "dist": dist,
        })
    return pts


def to_gpx(pts, name="Morning Run", sport="running") -> bytes:
    rows = []
    for p in pts:
        rows.append(
            f'<trkpt lat="{p["lat"]:.7f}" lon="{p["lon"]:.7f}"><ele>{p["ele"]:.1f}</ele>'
            f'<time>{p["t"].strftime("%Y-%m-%dT%H:%M:%SZ")}</time><extensions><gpxtpx:TrackPointExtension>'
            f'<gpxtpx:hr>{int(p["hr"])}</gpxtpx:hr><gpxtpx:cad>{int(p["cad"])}</gpxtpx:cad>'
            f'</gpxtpx:TrackPointExtension></extensions></trkpt>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        f'<trk><name>{name}</name><type>{sport}</type><trkseg>{"".join(rows)}</trkseg></trk></gpx>'
    ).encode()


def to_tcx(pts, sport="Biking") -> bytes:
    rows = []
    for p in pts:
        watts = f'<Extensions><ns3:TPX><ns3:Watts>{int(p["power"])}</ns3:Watts></ns3:TPX></Extensions>' \
            if p.get("power") is not None else ""
        rows.append(
            f'<Trackpoint><Time>{p["t"].strftime("%Y-%m-%dT%H:%M:%S.000Z")}</Time>'
            f'<Position><LatitudeDegrees>{p["lat"]:.7f}</LatitudeDegrees>'
            f'<LongitudeDegrees>{p["lon"]:.7f}</LongitudeDegrees></Position>'
            f'<AltitudeMeters>{p["ele"]:.1f}</AltitudeMeters><DistanceMeters>{p["dist"]:.1f}</DistanceMeters>'
            f'<HeartRateBpm><Value>{int(p["hr"])}</Value></HeartRateBpm><Cadence>{int(p["cad"])}</Cadence>'
            f'{watts}</Trackpoint>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">'
        f'<Activities><Activity Sport="{sport}"><Id>{pts[0]["t"].isoformat()}</Id>'
        f'<Lap StartTime="{pts[0]["t"].isoformat()}"><Track>{"".join(rows)}</Track></Lap>'
        '<Creator><Name>Test Device</Name></Creator></Activity></Activities></TrainingCenterDatabase>'
    ).encode()


# ----------------------------------------------------------------------------- FIT writer

_CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z


def _crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def _definition(local: int, global_num: int, fields) -> bytes:
    out = struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
    for num, size, base in fields:
        out += struct.pack("<BBB", num, size, base)
    return out


def _fit_ts(dt: datetime) -> int:
    return int(dt.timestamp()) - FIT_EPOCH


def to_fit(pts, sport: int = 1) -> bytes:
    """Encode points as a minimal FIT activity (sport: 1=running, 2=cycling)."""
    body = b""
    # file_id: type, manufacturer, product, time_created
    body += _definition(0, 0, [(0, 1, 0x00), (1, 2, 0x84), (2, 2, 0x84), (4, 4, 0x86)])
    body += struct.pack("<BBHHI", 0, 4, 1, 1, _fit_ts(pts[0]["t"]))
    # record: timestamp, lat, long, altitude, hr, cadence, distance, speed, power
    rec_fields = [(253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85), (2, 2, 0x84), (3, 1, 0x02),
                  (4, 1, 0x02), (5, 4, 0x86), (6, 2, 0x84), (7, 2, 0x84)]
    body += _definition(1, 20, rec_fields)
    prev = None
    for p in pts:
        speed = 0.0 if prev is None else p["dist"] - prev["dist"]
        power = p.get("power")
        body += struct.pack(
            "<BIiiHBBIHH", 1, _fit_ts(p["t"]),
            round(p["lat"] / 180.0 * 2**31), round(p["lon"] / 180.0 * 2**31),
            round((p["ele"] + 500) * 5), int(p["hr"]), int(p["cad"]),
            round(p["dist"] * 100), round(speed * 1000),
            0xFFFF if power is None else int(power),  # 0xFFFF = invalid
        )
        prev = p
    # session: timestamp, sport, sub_sport
    body += _definition(2, 18, [(253, 4, 0x86), (5, 1, 0x00), (6, 1, 0x00)])
    body += struct.pack("<BIBB", 2, _fit_ts(pts[-1]["t"]), sport, 0)

    header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(body), b".FIT")
    header += struct.pack("<H", _crc(header))
    data = header + body
    return data + struct.pack("<H", _crc(data))
