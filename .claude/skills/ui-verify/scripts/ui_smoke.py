"""Browser smoke test for the fit-push UI (Playwright + installed Edge/Chrome).

Starts the app on a scratch database filled with synthetic activities, walks the
main flows, saves screenshots and fails on console errors or broken steps.

    <playwright-python> .claude/skills/ui-verify/scripts/ui_smoke.py --out <dir>
        [--port 8790] [--db-copy data/activities.db] [--channel msedge|chrome]

--db-copy works on a COPY of a real database (the original is never touched).
Map tiles are always blocked: real tracks must not leak to the tile server.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
_VENV = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
VENV_PY = _VENV if _VENV.is_file() else Path(sys.executable)  # CI: one environment for app + playwright

SAMPLES = """
import sys
from tests.samples import START, lap_track, synthetic_track, to_fit, to_gpx
out = sys.argv[1]
open(out + '/track.gpx', 'wb').write(to_gpx(lap_track(laps=8), name='Track session'))
open(out + '/track2.gpx', 'wb').write(to_gpx(lap_track(laps=5, lap_speeds=[4.5] * 5, seed=3, start=START.replace(day=9)), name='Fast track'))
open(out + '/ride.fit', 'wb').write(to_fit(synthetic_track(with_power=True), sport=2))
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory for screenshots")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--db-copy", help="run against a copy of this database instead of synthetic data")
    ap.add_argument("--channel", default="msedge")
    ap.add_argument("--core-only", action="store_true", help="start the app without modules")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fitpush-ui-"))
    db = work / "ui.db"
    if args.db_copy:
        shutil.copy(args.db_copy, db)

    env = {**os.environ, "FITPUSH_DB": str(db)}
    server = subprocess.Popen(
        [
            str(VENV_PY),
            "-m",
            "app",
            "--port",
            str(args.port),
            "--no-backup",
            *(["--core-only"] if args.core_only else []),
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{args.port}/"
    problems: list[str] = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "api/activities", timeout=1)
                break
            except OSError:
                time.sleep(0.3)
        if not args.db_copy:
            subprocess.run([str(VENV_PY), "-c", SAMPLES, str(work)], cwd=ROOT, check=True)
        problems += run_browser(base, out, work, args.channel, synthetic=not args.db_copy, core_only=args.core_only)
    finally:
        server.terminate()
        server.wait(10)
        shutil.rmtree(work, ignore_errors=True)
    print("\nRESULT:", "OK" if not problems else f"{len(problems)} problem(s)")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


def run_browser(base: str, out: Path, work: Path, channel: str, synthetic: bool, core_only: bool = False) -> list[str]:
    problems: list[str] = []
    current = ["start"]  # step name, so errors say where they happened
    with sync_playwright() as p:
        # channel: "msedge" / "chrome" use an installed browser; "bundled" uses Playwright's own Chromium.
        browser = p.chromium.launch(headless=True, **({} if channel == "bundled" else {"channel": channel}))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.route("**/*.tile.openstreetmap.org/**", lambda r: r.abort())
        page.on(
            "console",
            lambda m: (
                m.type == "error"
                and "ERR_FAILED" not in m.text
                and problems.append(f"[{current[0]}] console: {m.text}")
            ),
        )
        page.on(
            "pageerror",
            lambda e: problems.append(
                f"[{current[0]}] page error: {e} | "
                + " <- ".join(lp.strip() for lp in (e.stack or "").splitlines()[1:8])
            ),
        )
        page.on("dialog", lambda d: (problems.append(f"native dialog used: {d.message!r}"), d.dismiss()))

        def step(name, fn):
            current[0] = name
            try:
                fn()
                print("ok  ", name)
            except Exception as exc:
                problems.append(f"{name}: {exc}".splitlines()[0])
                print("FAIL", name)
                page.screenshot(path=out / f"fail_{name.replace(' ', '_')}.png", full_page=True)

        page.goto(base)
        if synthetic:
            step(
                "upload",
                lambda: (
                    page.set_input_files(
                        "#file-input", [str(work / f) for f in ("track.gpx", "track2.gpx", "ride.fit")]
                    ),
                    page.wait_for_function("document.querySelectorAll('#activity-list li a').length >= 3"),
                ),
            )
        step(
            "dashboard",
            lambda: (
                page.goto(base + "#/"),
                page.wait_for_selector("#trend"),
                page.screenshot(path=out / "01_dashboard.png", full_page=True),
            ),
        )

        first = page.evaluate("fetch('/api/activities').then(r => r.json()).then(a => a.at(-1).id)")
        laps_id = page.evaluate(
            "fetch('/api/activities').then(r => r.json()).then(async (all) => { for (const a of all) { const d = await (await fetch('/api/activities/' + a.id)).json(); if (d.laps) return a.id; } return null; })"
        )

        def activity():
            page.goto(base + f"#/activity/{first}")
            page.wait_for_selector("#charts canvas")
            page.wait_for_timeout(300)
            page.screenshot(path=out / "02_activity.png", full_page=True)

        step("activity page", activity)

        def overlays():
            for opt in page.locator("#ov-sel option").all():
                page.select_option("#ov-sel", opt.get_attribute("value"))
                page.wait_for_timeout(80)
            page.select_option("#pal-sel", "turbo")
            page.locator("#map-card").screenshot(path=out / "03_overlay.png")
            page.select_option("#ov-sel", "none")

        step("map overlays", overlays)

        def enlarge():
            page.click("#map-size")
            page.wait_for_selector("#map-card.expanded")
            page.keyboard.press("Escape")
            page.wait_for_selector("#map-card:not(.expanded)")

        step("map enlarge", enlarge)

        def drag_select():
            c = page.locator("#charts canvas").first
            c.scroll_into_view_if_needed()
            b = c.bounding_box()
            y = b["y"] + b["height"] / 2
            page.mouse.move(b["x"] + b["width"] * 0.3, y)
            page.mouse.down()
            page.mouse.move(b["x"] + b["width"] * 0.6, y, steps=6)
            page.mouse.up()
            page.wait_for_selector("#sel-bar:not([hidden])")

        step("chart drag selection", drag_select)

        if laps_id:

            def laps():
                page.goto(base + f"#/activity/{laps_id}")
                page.click(".lap-hint a")
                page.wait_for_selector('#lap-list tr[data-lap="2"]')
                page.click('#lap-list tr[data-lap="2"]')
                page.wait_for_selector("#sel-bar:not([hidden])")
                page.screenshot(path=out / "04_laps.png", full_page=True)

            step("laps view", laps)

            def segment():
                page.click("#sel-segment")
                page.wait_for_selector("#name-dialog[open]")
                page.fill("#name-dialog input", "UI smoke segment")
                page.click("#name-ok")
                page.wait_for_url("**#/segment/*")
                page.wait_for_selector("text=Best efforts")
                page.screenshot(path=out / "05_segment.png", full_page=True)
                page.locator(".lap-list tbody tr a").first.click()
                page.wait_for_selector('#seg-list tr[aria-selected="true"]')

            step("segment create + jump back", segment)

        step(
            "segments overview",
            lambda: (page.goto(base + "#/segments"), page.wait_for_selector("text=Creating a segment")),
        )

        def tags():
            page.goto(base + f"#/activity/{first}")
            page.wait_for_selector("#tag-input")
            page.fill("#tag-input", "Smoke Test")
            page.press("#tag-input", "Enter")
            page.wait_for_selector(".tag:has-text('#smoke test')")
            page.wait_for_selector("#tag-filter:not([hidden])")

        step("tags", tags)

        def modules_page():
            page.goto(base + "#/modules")
            page.wait_for_selector("text=Modules")
            page.wait_for_timeout(200)
            page.screenshot(path=out / "08_modules.png", full_page=True)
            if not core_only:
                page.click("a[href='#/modules/activity_map']")
                page.wait_for_selector(".md h3")
                page.screenshot(path=out / "09_module_manual.png", full_page=True)

        step("modules page + manual", modules_page)

        if core_only:

            def no_modules():
                if page.locator("[data-tab^='page:']").count():
                    raise AssertionError("module tabs shown in core-only mode")
                page.goto(base + "#/m/activity_map")
                page.wait_for_selector("text=Page not available")

            step("core-only: no module pages", no_modules)
        else:

            def map_module():
                page.goto(base + "#/m/activity_map")
                page.wait_for_selector("#am-map")
                page.wait_for_function("document.querySelector('#am-status').textContent.includes('activit')")
                page.locator("[data-sport]").first.click()
                page.wait_for_function("location.hash.includes('sports=')")
                page.click("[data-color=date]")
                page.wait_for_function("location.hash.includes('color=date')")
                page.wait_for_timeout(300)
                page.screenshot(path=out / "10_map_module.png", full_page=True)

            step("map module", map_module)

        def search():
            page.goto(base + "#/")
            page.wait_for_selector("#activity-list a")
            page.keyboard.press("Control+/")
            page.wait_for_selector("#search-dialog[open]")
            box = page.locator("#search-dialog").bounding_box()
            vp = page.viewport_size
            if abs((box["y"] + box["height"] / 2) - vp["height"] / 2) > 4:
                raise AssertionError(f"search box not vertically centred: {box}")
            if page.locator("#search-results li[role=option]").count() < 1:
                raise AssertionError("no results for an empty query")
            name = page.locator("#activity-list .name").first.inner_text()
            typo = name[:2] + name[3:] if len(name) > 4 else name  # a skipped letter still matches
            page.fill("#search-input", typo)
            page.wait_for_selector("#search-results li[role=option]")
            page.screenshot(path=out / "11_search.png")
            page.keyboard.press("Enter")
            page.wait_for_function("location.hash.startsWith('#/activity/')")
            if page.locator("#search-dialog[open]").count():
                raise AssertionError("search dialog still open after Enter")
            opened = page.evaluate("location.hash")
            page.keyboard.press("Control+/")
            page.wait_for_selector("#search-dialog[open]")
            page.wait_for_selector("#search-results li[role=option]")
            if page.locator("#search-results li").first.inner_text().find(name) < 0:
                raise AssertionError("history: the item opened last is not first in an empty search")
            page.keyboard.press("Escape")
            page.wait_for_function("!document.querySelector('#search-dialog[open]')")

        step("search (Ctrl+/)", search)

        def dark():
            page.goto(base + f"#/activity/{first}")
            page.wait_for_selector("#charts canvas")
            page.click("#theme-btn")
            page.wait_for_timeout(300)
            page.screenshot(path=out / "06_dark.png", full_page=True)
            page.click("#theme-btn")

        step("dark theme", dark)

        def mobile():
            page.set_viewport_size({"width": 390, "height": 844})
            for h in ("#/", f"#/activity/{first}", "#/segments"):
                page.goto(base + h)
                page.wait_for_timeout(500)
                sw = page.evaluate("document.documentElement.scrollWidth")
                if sw > 392:
                    raise AssertionError(f"horizontal scroll at 390 px on {h}: scrollWidth={sw}")
            page.screenshot(path=out / "07_mobile.png", full_page=True)

        step("mobile width", mobile)
        browser.close()
    return problems


if __name__ == "__main__":
    sys.exit(main())
