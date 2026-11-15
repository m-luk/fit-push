"""Core: file parsing (FIT / GPX / TCX / gzip) and format detection."""

import gzip

import pytest

from app.parsers import ParseError, parse_file
from tests.samples import synthetic_track, to_fit, to_gpx, to_tcx


@pytest.mark.parametrize(
    "fname,builder,sport",
    [
        ("run.gpx", lambda: to_gpx(synthetic_track()), "running"),
        ("ride.tcx", lambda: to_tcx(synthetic_track(with_power=True)), "cycling"),
        ("run.fit", lambda: to_fit(synthetic_track(), sport=1), "running"),
        ("ride.fit", lambda: to_fit(synthetic_track(with_power=True), sport=2), "cycling"),
    ],
)
def test_parse_formats(fname, builder, sport):
    act = parse_file(fname, builder())
    assert len(act.points) == 1801
    assert act.sport == sport
    p = act.points[100]
    assert p.t is not None and p.hr == pytest.approx(123, abs=1)
    assert p.lat == pytest.approx(52.2297 + 300 / 111_195, abs=1e-5)
    assert p.ele == pytest.approx(100 + 20 * __import__("math").sin(0.3), abs=0.3)


def test_fit_channels_and_detection_without_extension():
    data = to_fit(synthetic_track(with_power=True), sport=2)
    act = parse_file("download", data)  # sniffed from the ".FIT" header
    assert act.source_format == "fit"
    p = act.points[10]
    assert p.power is not None and p.dist == pytest.approx(30.0)
    assert p.speed == pytest.approx(3.0)


def test_fit_missing_power_is_none():
    act = parse_file("run.fit", to_fit(synthetic_track()))
    assert all(p.power is None for p in act.points)


def test_gzip_fit():
    data = gzip.compress(to_fit(synthetic_track()))
    act = parse_file("run.fit.gz", data)
    assert act.source_format == "fit" and len(act.points) == 1801


def test_unsupported_file():
    with pytest.raises(ParseError):
        parse_file("notes.txt", b"hello")
