"""Browser check of the guided tour: once hands-on (doing every step), once by skipping.

    python ui_tour.py [--out DIR] [--port 8792] [--channel msedge|chrome|bundled] [--core-only]

Starts the app on an empty throw-away database (the tour must work for a new user),
runs the tour like a user would, checks that it advances by itself, that Exit removes the
demo data or keeps it, and that nothing logs a console error. Map tiles are blocked.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[4]
_VENV = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
VENV_PY = _VENV if _VENV.is_file() else Path(sys.executable)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "fitpush-tour"))
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--channel", default="msedge" if os.name == "nt" else "chrome")
    ap.add_argument("--core-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="fitpush-tour-"))
    env = {**os.environ, "FITPUSH_DB": str(tmp / "tour.db"), "FITPUSH_MODULES": "none" if args.core_only else "all"}
    server = subprocess.Popen(
        [str(VENV_PY), "-m", "app", "--port", str(args.port), "--no-backup", "--no-open"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{args.port}/"
    failures: list[str] = []
    errors: list[str] = []
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "api/version", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        with sync_playwright() as p:
            browser = p.chromium.launch(**({} if args.channel == "bundled" else {"channel": args.channel}))
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.route("**/*.tile.openstreetmap.org/**", lambda r: r.abort())
            page.on(
                "console", lambda m: m.type == "error" and "ERR_FAILED" not in m.text and errors.append(m.text)
            )  # tiles are blocked
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("dialog", lambda d: (errors.append(f"native dialog: {d.message}"), d.dismiss()))

            def step(name: str, fn) -> None:
                try:
                    fn()
                    print(f"ok    {name}")
                except Exception as exc:
                    failures.append(name)
                    print(f"FAIL  {name}: {str(exc).splitlines()[0]}")
                    page.screenshot(path=str(out / f"fail_{len(failures)}.png"))

            def title(expected: str, timeout: int = 8000) -> None:
                page.wait_for_function(
                    "t => document.querySelector('#tour-title')?.textContent.includes(t)", arg=expected, timeout=timeout
                )

            def tour(btn: str) -> None:
                page.click(f'#tour-card [data-tour="{btn}"]')

            page.goto(base)
            step("welcome offers the tour", lambda: page.click("[data-tour-start]"))
            step("intro card", lambda: title("Welcome"))
            page.screenshot(path=str(out / "t01_welcome.png"))
            tour("next")

            def open_run() -> None:
                title("Open an activity")
                page.wait_for_selector("#tour-ring:not([hidden])")
                page.screenshot(path=str(out / "t02_open.png"))
                page.click("#activity-list a")
                title("The summary")

            step("open the run from the list", open_run)
            tour("next")

            def hover_and_drag() -> None:
                title("Data streams")
                canvas = page.locator("#charts canvas").first
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                assert box
                page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
                page.mouse.move(box["x"] + box["width"] * 0.32, box["y"] + box["height"] / 2)
                title("Select a stretch")
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                assert box
                y = box["y"] + box["height"] / 2
                page.mouse.move(box["x"] + box["width"] * 0.35, y)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] * 0.5, y, steps=8)
                page.mouse.move(box["x"] + box["width"] * 0.6, y, steps=8)
                page.mouse.up()
                title("The selection bar")
                page.screenshot(path=str(out / "t03_selection.png"))

            step("hover, then drag a selection", hover_and_drag)

            def trim() -> None:
                page.click("#sel-bar a.btn.primary")
                title("A trimmed view")
                page.click(".trim-banner a.btn.primary")
                title("Colour the track")

            step("trimmed view and back", trim)

            def colours() -> None:
                page.select_option("#ov-sel", "hr")
                title("Colour patterns")
                page.select_option("#pal-sel", index=2)
                page.wait_for_selector('#tour-card [data-tour="next"].tour-ready')
                tour("next")
                title("A bigger map")
                page.click("#map-size")
                title("…and back")
                page.screenshot(path=str(out / "t04_map_expanded.png"))
                page.keyboard.press("Escape")  # focus is in the tour card: Esc minimizes the map first
                title("Laps found")
                assert page.locator("#tour-card").is_visible()

            step("overlay, palette, enlarge and Esc", colours)

            def laps_and_segment() -> None:
                page.click(".lap-hint a")
                title("Compare laps")
                page.click('#lap-list tr[data-lap="3"]')
                title("Make it a segment")
                page.screenshot(path=str(out / "t05_laps.png"))
                page.click("#sel-segment")
                page.click("#name-ok")
                title("The leaderboard")
                rows = page.locator("#seg-efforts tbody tr").count()
                assert rows >= 4, f"{rows} efforts"
                page.screenshot(path=str(out / "t06_leaderboard.png"))
                tour("next")
                title("All segments")
                tour("next")

            step("laps, segment, leaderboard", laps_and_segment)

            def tags() -> None:
                title("Tag it")
                page.wait_for_selector('#tour-card [data-tour="there"]', state="visible")
                tour("there")
                page.wait_for_selector("#tag-input")
                page.fill("#tag-input", "intervals")
                page.press("#tag-input", "Enter")
                title("Filter the list")
                tour("next")
                title("Extras")
                tour("next")
                title("Your turn")
                tour("next")
                title("Leave the tour?")
                page.screenshot(path=str(out / "t07_finish.png"))
                tour("remove")
                page.wait_for_selector("#tour-card", state="detached")
                page.wait_for_function(
                    "() => document.querySelector('#activity-list').textContent.includes('No activities')"
                )
                page.wait_for_function(
                    "() => document.querySelector('#segment-list').textContent.includes('No segments')"
                )

            step("tags, finish, demo data removed", tags)

            def skip_through() -> None:
                page.click("#tour-btn")
                title("Welcome")
                tour("next")
                for _ in range(40):
                    if page.locator('#tour-card [data-tour="skip"]').count() == 0:
                        break
                    tour("skip")
                    page.wait_for_timeout(150)
                title("Your turn", timeout=15000)
                # Every skipped step did its part: a segment and a tag exist.
                page.wait_for_function(
                    "() => document.querySelector('#segment-list').textContent.includes('Tutorial loop')"
                )
                assert "intervals" in page.locator("#tag-filter").inner_text()

            step("skip every step", skip_through)

            def keep_then_esc() -> None:
                tour("next")
                tour("keep")
                page.wait_for_selector("#tour-card", state="detached")
                assert "Tutorial run" in page.locator("#activity-list").inner_text()
                page.click("#tour-btn")
                title("Welcome")
                tour("next")
                title("Open an activity")
                page.keyboard.press("Escape")
                title("Leave the tour?")
                tour("back")
                title("Open an activity")
                page.emulate_media(color_scheme="dark")
                page.screenshot(path=str(out / "t08_dark.png"))
                page.emulate_media(color_scheme="light")

            step("keep the demo data, Esc asks, Back returns", keep_then_esc)

            def resume_and_mobile() -> None:
                page.reload()
                title("Open an activity")  # the tour resumes after a reload
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(400)
                assert "docked" in (page.get_attribute("#tour-card", "class") or "")
                page.screenshot(path=str(out / "t09_mobile.png"))
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390, f"page is {width}px wide"
                tour("exit")
                tour("remove")
                page.wait_for_selector("#tour-card", state="detached")

            step("resume after reload, phone layout, exit", resume_and_mobile)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    for e in errors:
        print(f"console error: {e}")
    print(f"screenshots in {out}")
    return 1 if failures or errors else 0


if __name__ == "__main__":
    sys.exit(main())
