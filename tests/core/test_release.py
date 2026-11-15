"""Version, desktop launcher helpers and the release script (no PyInstaller needed)."""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

from app import __main__ as launcher
from app import __version__

ROOT = Path(__file__).resolve().parents[2]


def _release():
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["release"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_version_endpoint(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"app": "fit-push", "version": __version__}


def test_versions_agree():
    rel = _release()
    assert rel.version() == __version__
    assert rel.pyproject_version() == __version__


def test_check_tag():
    rel = _release()
    rel.check_tag(f"v{__version__}")
    rel.check_tag(f"refs/tags/v{__version__}")
    with pytest.raises(SystemExit):
        rel.check_tag("v999.0.0")


def test_bump_rejects_non_semver():
    with pytest.raises(SystemExit):
        _release().bump("1.2")


def test_staged_modules_leave_out_tests_and_template(tmp_path):
    staged = _release().stage_modules(tmp_path / "modules")
    names = {p.name for p in staged.iterdir()}
    assert "activity_map" in names
    assert "_template" not in names
    assert not list(staged.rglob("tests"))
    assert (staged / "activity_map" / "module.json").is_file()


def test_port_helpers():
    port = launcher.free_port("127.0.0.1")
    assert launcher.port_free("127.0.0.1", port)
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        assert not launcher.port_free("127.0.0.1", port)
        # Something that is not fit-push answers (or not): no instance is reported.
        assert launcher.running_instance("127.0.0.1", port, timeout=0.3) is None


def test_cli_parses_desktop_options():
    args = launcher.parser().parse_args(["--no-open", "--port", "9000", "--core-only"])
    assert args.open is False
    assert args.port == 9000
    assert args.core_only
    assert launcher.parser().parse_args([]).open is None
    assert not launcher.frozen()
