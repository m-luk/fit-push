---
name: ui-development
description: How to build and change the fit-push frontend (app/static/index.html, app.js, style.css) - architecture of app.js, routing and view state, design tokens and dataviz rules, charts (Chart.js), map (Leaflet), the selection model, dialogs and accessibility. Use before adding or changing any page, card, chart, map feature, control or style in this project.
---

# fit-push UI development

The frontend is one page with no build step: `index.html` (shell, sidebar,
dialogs), `app.js` (one IIFE, ~1300 lines), `style.css` (tokens and components).
Chart.js 4.4.1 and Leaflet 1.9.4 come from cdnjs. Read the relevant section of
`app.js` before changing it; reuse its helpers instead of adding new ones.

After the change, verify it in a browser with the **ui-verify** skill.

## Map of app.js

| Section (search for the `// ----` banner) | What lives there |
|---|---|
| state & utils | `state`, `$`, `esc` (always escape interpolated text), `css("--token")`, `api(path, opts)` (throws `Error(detail)`), `toast(msg)`, `lsGet/lsSet` |
| units & formatting | `UNITS`, `u()`, `fmtNum/fmtDist/fmtEle/fmtDur/fmtPace/fmtSpeed/fmtDate/fmtDay`, `PACE_SPORTS`, `SPORT_ICON`, `sportName` |
| theme, upload, settings, sidebar list | top bar controls, drag & drop upload, `loadList/renderList` |
| charts common | `destroyCharts`, `baseScales`, the global `crosshair` plugin (hover line + shaded selection on `$synced` charts), `tooltipStyle` |
| dashboard | `renderDashboard`, `recordsCard`, `powerCurveChart`, `tile` |
| activity view | `renderActivity(id, win, opts)`, `exportLinks`, `askName`, `saveClip` |
| map | `drawMap`, `setMapExpanded`, `PALETTES/paletteSteps`, `overlayDefs/drawOverlay`, `raiseMapMarks` |
| streams & selection | `streamDefs`, `drawStreams`, `renderSelection` → `drawSelection`, `selectionLabel`, `setHover`, `nearestIdx` |
| segments on an activity | `segEffortsTable`, `selectEffort`, `wireSegEfforts`, `createSegment`, map pick (`startPick/onPickClick/endPick`) |
| laps view | `renderLaps` (summary table, lap-time chart, lap list) |
| segments pages | `loadSegments`, `renderSegList`, `setTab`, `leaveActivity`, `renderSegmentsPage`, `renderSegment` |
| tags (core) | `loadTags`, `renderTagFilter` (sidebar), `renderTagEditor` (chips under the activity title) |
| module SDK (window.fitpush) | the frozen `sdk` object, `registerPage` / `registerActivityCard`, `pageCleanups` + `runCleanups` (called from `disposeMap`), `loadModules` (CSS + scripts from `/m/<id>/`), `renderNav`, `renderModulePage`, `renderModuleCards`, `selectNamed`, `showModuleError` |
| modules page (+ docs) | `markdown()` (small, escaping renderer), `renderModulesPage` (`#/modules`, `#/modules/<id>`) |
| router | `route()` parses the hash and calls a `render*` function |

`window.fitpush` is a **public contract** for modules (docs/SDK.md). Adding to it is
a core change: document it in docs/SDK.md and keep old calls working. Every new
extension point must contain module errors (`try/catch` → `showModuleError`) and
register cleanups so navigation frees maps and charts.

## Routing and state

- **URL hash = view state**: `#/` dashboard, `#/activity/{id}` with optional
  `start`, `end` (trimmed view, absolute cleaned indices), `laps=1`, `effort={id}`;
  `#/segments`, `#/segment/{id}`. Anything a user may want to bookmark or link
  to belongs in the hash; parse it in `route()` and pass it via `opts`.
- `localStorage` (`lsGet/lsSet`, prefix `fitpush:`) only for per-viewer
  preferences: units, theme, x-axis mode, overlay, palette. Never for data.
- A `render*` function owns `main.innerHTML` completely: build the markup
  string, assign once, then attach listeners. Call `destroyCharts()` and
  `disposeMap()` (or `leaveActivity()`) first so Chart.js instances and the
  Leaflet map are freed *before* their elements leave the page.
- Async renders start with `const token = newRender();` and check
  `if (stale(token)) return;` after **every** `await`. Otherwise a slow older
  navigation draws over a newer page.
- `renderActivity` resets per-view state: `state.sel`, `state.lap`,
  `state.effort`, `state.selListeners`, map pick.

## Indices and the selection model

- `a.series` arrays are downsampled (≤ 1500 points); `a.series.idx[k]` is the
  absolute cleaned index of series point `k`. Convert absolute → series with
  `nearestIdx(a.series.idx, absolute)`, series → absolute with `se.idx[k]`.
- `state.sel = {i0, i1}` holds **series** positions. Always change it through
  `renderSelection(a)`, which redraws the charts' shaded band, the map's
  selection line or overlay fade and the selection bar, and then calls every
  function in `state.selListeners`.
- Named selections: set `state.lap` + `state.lapRange`, or
  `state.effort = {id, name, range}` *before* calling `renderSelection`. When
  the user drags something else, the range no longer matches and the label
  falls back to "Selection" automatically. Add new kinds to `selectionLabel`.
- UI that highlights the current selection (table rows, chart points) pushes
  a refresh function onto `state.selListeners`.

## Design tokens (style.css)

Defined in `:root`, redefined for dark under
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) … }` **and**
`:root[data-theme="dark"]`. A new token must be added in all three places.

| Token | Use |
|---|---|
| `--bg`, `--surface-1`, `--surface-2`, `--border`, `--grid` | page, cards, hover / zebra, borders, chart grid |
| `--text-primary/secondary/muted` | all text, values, axis labels, legends |
| `--accent`, `--accent-ink`, `--danger` | primary buttons/links, destructive actions |
| `--m-speed --m-hr --m-power --m-cadence --m-elevation --m-temp` | fixed colour per metric, everywhere (charts, swatches) |
| `--seq-1…5` | ordinal blue ramp (HR zones) |
| `--sel-fill`, `--sel-edge` | the selection: chart band, map line, selected rows |
| `--ov-1…7`, `--dv-1…7`, `--map-casing` | map overlay: sequential blue, diverging blue–gray–red, line casing |
| `--radius` | card radius |

Components to reuse: `.card` (+ `h2` with a left `<span>` title and right muted
note), `.tiles/.tile`, `.grid.two`, `.stack`, `.btn` (`.primary`, `.ghost`,
`.danger`, `.small`, `[aria-pressed]`), `.seg` (segmented buttons), `.table-scroll`
(+ `.lap-list` for a scrolling table with sticky header), `.badge`, `.trim-banner`,
`.sel-bar`, `.lap-hint`, `.muted`.

## Charts and colour (dataviz rules)

- One y-axis per chart; several measures → small multiples sharing the x axis
  (see `drawStreams`). Never a dual-axis chart.
- Colour follows the metric (`--m-*`), never the series order or rank.
- Magnitude on a map/heat scale: one-hue sequential; signed deltas: diverging
  with a neutral midpoint. Classic maps (rainbow, turbo, …) are offered only
  as a user choice in `PALETTES`, never as the default.
- Lines 2 px, markers ≥ 8 px diameter with a 2 px `--surface-1` ring; bars
  start at zero. If differences are small relative to the value (lap times),
  use dots/lines with a non-zero axis, not bars.
- Every chart has a hover read-out (Chart.js tooltip via `tooltipStyle()`, or
  the synced crosshair + `#readout`). Synced stream charts set `events: []`
  and are driven by our own mouse handlers; mark them `chart.$synced = true`.
- Push every chart into `state.charts` so it is destroyed on navigation.
- Text (titles, legends, values) uses text tokens; a coloured swatch next to it
  carries identity.

## Map (Leaflet)

- Create with `L.map(el, { preferCanvas: true, scrollWheelZoom: false })`;
  everything is on one canvas, so z-order = `bringToFront/bringToBack`. After
  adding layers call `raiseMapMarks()` (markers, hover dot, selection).
- Track geometry for overlays comes from `a.series.lat/lon` (same index as the
  other series); `a.track` is only the plain route line.
- Changing the map container's size → `map.invalidateSize()` then refit.
- Programmatic `fitBounds`/`setView` on an already-shown map use
  `{ animate: false }`. A zoom animation still pending when the page changes
  makes Leaflet's transition timer throw `_leaflet_pos` on the removed map.
- Dark mode darkens tiles with a CSS filter; lines need `--map-casing` under
  them to stay visible on any tile.

## Dialogs, feedback, accessibility

- Input: `await askName(title, hint, default, okLabel)` (returns `null` on
  cancel). Confirmation of destructive actions: `confirm()` is still used for
  deletes; prefer a `<dialog>` for new flows.
- Feedback: `toast(msg)` for results and errors (`"Could not …: " + e.message`).
- Clickable table rows: `tabindex="0"`, `aria-selected`, Enter/Space and ↑/↓
  handlers, `:focus-visible` outline, and real `<a>` links for navigation
  (row click handlers must ignore clicks on links).
- Toggle buttons use `aria-pressed`. Esc closes the innermost thing first
  (map pick → enlarged map → selection).
- Layout must work at 390 px wide with no horizontal page scroll; wide tables
  go inside `.table-scroll`.

## Checklist before handing over

1. `node --check app/static/app.js` passes.
2. New colours are tokens with light and dark values.
3. All interpolated strings go through `esc()`.
4. Backend changes have pytest coverage; `python scripts/run.py --tests` passes.
5. Browser check done with the **ui-verify** skill (desktop, dark, 390 px),
   screenshots looked at, no console errors.
6. README feature section updated if behaviour changed.
