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


LOG = """# Changelog

## [Unreleased]

### Added

- New thing.

## [0.1.0] - 2026-01-01

### Added

- First.

[Unreleased]: https://example.org/compare/v0.1.0...HEAD
[0.1.0]: https://example.org/releases/tag/v0.1.0
"""


def test_changelog_section():
    rel = _release()
    assert rel.changelog_section(LOG, "Unreleased") == "### Added\n\n- New thing."
    assert rel.changelog_section(LOG, "0.1.0") == "### Added\n\n- First."
    assert rel.changelog_section(LOG, "9.9.9") == ""


def test_changelog_release_moves_unreleased():
    rel = _release()
    out = rel.changelog_release(LOG, "0.2.0", "2026-02-02")
    assert rel.changelog_section(out, "Unreleased") == ""
    assert rel.changelog_section(out, "0.2.0") == "### Added\n\n- New thing."
    assert "## [0.2.0] - 2026-02-02" in out
    assert f"[Unreleased]: {rel.REPO_URL}/compare/v0.2.0...HEAD" in out
    assert f"[0.2.0]: {rel.REPO_URL}/compare/v0.1.0...v0.2.0" in out
    assert "[0.1.0]: https://example.org/releases/tag/v0.1.0" in out
    with pytest.raises(SystemExit):  # nothing left to release
        rel.changelog_release(out, "0.3.0", "2026-03-03")
    with pytest.raises(SystemExit):  # version already released
        rel.changelog_release(LOG, "0.1.0", "2026-03-03")


def test_first_release_links_to_the_tag():
    rel = _release()
    out = rel.changelog_release("# Changelog\n\n## [Unreleased]\n\n- A.\n", "1.0.0", "2026-04-04")
    assert out.endswith(
        f"[Unreleased]: {rel.REPO_URL}/compare/v1.0.0...HEAD\n[1.0.0]: {rel.REPO_URL}/releases/tag/v1.0.0\n"
    )


def test_repository_changelog_is_well_formed():
    rel = _release()
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text and "keepachangelog.com" in text
    released = rel.changelog_section(text, __version__)
    assert released or rel.changelog_section(text, "Unreleased")  # the current version is described somewhere
