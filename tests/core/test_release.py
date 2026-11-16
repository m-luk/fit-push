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
    assert launcher.parser().parse_args([]).desktop is None
    assert launcher.parser().parse_args(["--desktop"]).desktop is True
    assert not launcher.frozen()


def test_desktop_mode_from_source_reuses_running_instance(monkeypatch, tmp_path):
    opened: list[tuple[str, bool]] = []
    monkeypatch.setattr(launcher, "running_instance", lambda host, port, timeout=1.0: __version__)
    monkeypatch.setattr(launcher, "open_url", lambda url, app_window: opened.append((url, app_window)))
    monkeypatch.setenv("FITPUSH_DB", str(tmp_path / "x.db"))
    assert launcher.main(["--desktop", "--reload"]) == 0
    assert launcher.main(["--desktop", "--no-app-window"]) == 0
    assert opened == [("http://127.0.0.1:8000/", True), ("http://127.0.0.1:8000/", False)]
    assert not (tmp_path / "backups").exists()  # returned before backing up / serving


def test_open_url_uses_app_window_or_falls_back_to_a_tab(monkeypatch):
    tabs: list[str] = []
    started: list[list[str]] = []
    monkeypatch.setattr(launcher.webbrowser, "open", tabs.append)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(launcher, "app_browser", lambda: "/x/chrome")
    assert launcher.open_url("http://h:1/", app_window=True) is True
    assert started == [["/x/chrome", "--app=http://h:1/"]] and not tabs
    assert launcher.open_url("http://h:1/", app_window=False) is False
    monkeypatch.setattr(launcher, "app_browser", lambda: None)
    assert launcher.open_url("http://h:1/", app_window=True) is False
    assert tabs == ["http://h:1/", "http://h:1/"] and len(started) == 1


def _fake_clock(monkeypatch, step: float = 0.5):
    from app import taskbar

    now = [0.0]
    monkeypatch.setattr(taskbar.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(taskbar.time, "sleep", lambda s: now.__setitem__(0, now[0] + step))
    return taskbar


def test_window_watcher_stops_after_the_last_window_closes(monkeypatch):
    taskbar = _fake_clock(monkeypatch)
    frames = iter([[], [7], [7, 8], [8], [], [9]] + [[]] * 100)  # a reload blip ([] then [9]) is not a close
    monkeypatch.setattr(taskbar, "_app_windows", lambda: next(frames))
    tagged: list[int] = []
    monkeypatch.setattr(taskbar, "_set_identity", lambda hwnd, ident: tagged.append(hwnd))
    closed: list[bool] = []
    ident = taskbar.Identity("fit-push.dev", "cmd", "fit-push (dev)", None)
    taskbar._watch_loop(ident, lambda: closed.append(True), grace=4.0, appear=60.0)
    assert closed == [True]
    assert tagged == [7, 8, 9]  # every new window once


def test_window_watcher_does_nothing_when_no_window_appears(monkeypatch):
    taskbar = _fake_clock(monkeypatch)
    monkeypatch.setattr(taskbar, "_app_windows", list)
    closed: list[bool] = []
    taskbar._watch_loop(None, lambda: closed.append(True), grace=4.0, appear=10.0)
    assert closed == []


def test_taskbar_identity_from_source(monkeypatch):
    from app import taskbar

    monkeypatch.setenv("FITPUSH_RELAUNCH", "py devapp.py launch --core-only")
    ident = taskbar.identity()
    assert ident and ident.app_id == "fit-push.dev" and ident.command == "py devapp.py launch --core-only"
    monkeypatch.delenv("FITPUSH_RELAUNCH")
    ident = taskbar.identity()
    assert ident and ident.command.endswith("devapp.py launch")


def test_manifest_is_served(client):
    r = client.get("/static/manifest.json")
    assert r.status_code == 200
    assert r.json()["name"] == "fit-push"
    assert 'rel="manifest"' in client.get("/").text


def _devapp():
    spec = importlib.util.spec_from_file_location("devapp", ROOT / "scripts" / "devapp.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_devapp_install_and_uninstall_linux_entry(monkeypatch, tmp_path):
    dev = _devapp()
    monkeypatch.setattr(dev.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(dev, "ensure_venv", lambda: Path("/venv/bin/python"))
    monkeypatch.setattr(dev, "ensure_requirements", lambda py, dev: None)
    monkeypatch.setattr(dev, "make_icon", lambda py: None)
    assert dev.main(["install", "--core-only"]) == 0
    entry = tmp_path / "applications" / "fit-push-dev.desktop"
    text = entry.read_text(encoding="utf-8")
    assert "Name=fit-push (dev)" in text
    assert "devapp.py" in text and " launch --core-only" in text
    assert "Terminal=true" in text
    assert dev.main(["uninstall"]) == 0
    assert not entry.exists()


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
