/* fit-push frontend: plain JS + Chart.js + Leaflet. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ state & utils
  const state = {
    units: lsGet("units") || "metric",
    activities: [],
    sport: "",
    charts: [],
    hoverIdx: null,
    current: null,
    period: "week",
    metric: "distance_m",
    overlay: lsGet("overlay") || "none",
    palette: lsGet("palette") || "default",
    paletteReverse: lsGet("paletteReverse") === "1",
    selListeners: [], // called after every selection change (laps view, segments card)
    effort: null,     // selected segment effort {id, name, range}
    segments: [],
    tags: [],         // [{tag, count}]
    tagFilter: "",
    modules: [],      // GET /api/modules
    tab: "activities",
    pick: null,       // map "pick start/end" mode
    lap: null,        // selected lap number in the laps view
    lapRange: null,   // its series range, to notice when the selection moves elsewhere
  };
  const $ = (sel, root = document) => root.querySelector(sel);
  const main = $("#main");

  // Preferences saved under the app's old name ("fitgit:") are still read; new writes use "fitpush:".
  function lsGet(k) { try { return localStorage.getItem("fitpush:" + k) ?? localStorage.getItem("fitgit:" + k); } catch { return null; } }
  function lsSet(k, v) { try { localStorage.setItem("fitpush:" + k, v); } catch { /* ignore */ } }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return res.status === 204 ? null : res.json();
  }
  api.text = async (path) => {
    const res = await fetch(path);
    if (!res.ok) throw new Error(res.statusText);
    return res.text();
  };

  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
  }

  // ------------------------------------------------------------------ units & formatting
  // Sport catalogue comes from GET /api/sports (app/sports.py is the single source).
  let SPORTS = new Map();
  const sportInfo = (s) => SPORTS.get(s);
  const isPace = (s) => !!sportInfo(s)?.pace;
  const cadenceUnit = (s) => sportInfo(s)?.cadence_unit || "spm";
  const FAMILY_LABEL = { running: "Running", cycling: "Cycling", foot: "Walking & hiking", skiing: "Winter", water: "Water", swimming: "Swimming", other: "Other" };
  // <option>s grouped by family; a sport that isn't in the catalogue (from an unusual file) is kept on top.
  function sportSelectOptions(current) {
    const opt = (k) => `<option value="${esc(k)}" ${k === current ? "selected" : ""}>${esc(sportName(k))}</option>`;
    const groups = new Map();
    for (const s of SPORTS.values()) (groups.get(s.family) || groups.set(s.family, []).get(s.family)).push(s.key);
    return (SPORTS.has(current) ? "" : opt(current)) + [...groups].map(([fam, keys]) =>
      keys.length === 1 ? opt(keys[0]) : `<optgroup label="${esc(FAMILY_LABEL[fam] || fam)}">${keys.map(opt).join("")}</optgroup>`).join("");
  }
  async function loadSports() { SPORTS = new Map((await api("/api/sports")).map((x) => [x.key, x])); }
  const UNITS = {
    metric: { dist: 1000, distL: "km", speed: 3.6, speedL: "km/h", ele: 1, eleL: "m", split: "km" },
    imperial: { dist: 1609.344, distL: "mi", speed: 2.23694, speedL: "mph", ele: 3.28084, eleL: "ft", split: "mi" },
  };
  const u = () => UNITS[state.units];
  const fmtNum = (v, d = 1) => (v == null ? "–" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
  const fmtDist = (m, d = 2) => fmtNum(m / u().dist, d);
  const fmtEle = (m) => (m == null ? "–" : fmtNum(m * u().ele, 0));
  function fmtDur(s) {
    if (s == null) return "–";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  }
  const paceSec = (ms) => (ms && ms > 0.3 ? u().dist / ms : null);
  const fmtPace = (ms) => { const p = paceSec(ms); return p == null || p > 3600 ? "–" : fmtDur(p); };
  const fmtSpeed = (ms) => (ms == null ? "–" : fmtNum(ms * u().speed, 1));
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "No date");
  const fmtDay = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "");
  const sportIcon = (s) => sportInfo(s)?.icon || "⏱️";
  const sportName = (s) => sportInfo(s)?.label || (s || "unknown").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  function effortLabel(m) {
    const named = { 1609.344: "1 mile", 21097.5: "Half marathon", 42195: "Marathon" };
    if (named[m]) return named[m];
    return m >= 1000 ? `${m / 1000} km` : `${m} m`;
  }
  const durLabel = (s) => (s < 60 ? `${s}s` : s < 3600 ? `${s / 60} min` : `${s / 3600} h`);

  // ------------------------------------------------------------------ theme & units controls
  function applyTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    // title bar of an app window / installed app follows the top bar
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = css("--surface-1");
  }
  applyTheme(lsGet("theme"));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(lsGet("theme")));
  $("#theme-btn").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    applyTheme(next); lsSet("theme", next); route();
  });
  function syncUnitButtons() {
    document.querySelectorAll("[data-units]").forEach((b) => b.classList.toggle("active", b.dataset.units === state.units));
  }
  document.querySelectorAll("[data-units]").forEach((b) => b.addEventListener("click", () => {
    state.units = b.dataset.units; lsSet("units", state.units); syncUnitButtons(); renderList(); renderSegList(); route();
  }));
  syncUnitButtons();

  // ------------------------------------------------------------------ upload
  async function upload(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    toast(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`);
    try {
      const r = await api("/api/activities", { method: "POST", body: fd });
      const parts = [];
      if (r.imported.length) parts.push(`${r.imported.length} imported`);
      if (r.duplicates.length) parts.push(`${r.duplicates.length} already present`);
      if (r.errors.length) parts.push(`${r.errors.length} failed: ${r.errors.map((e) => `${e.filename} (${e.error})`).join(", ")}`);
      toast(parts.join(" · ") || "Nothing imported");
      await Promise.all([loadList(), loadSegments()]);
      if (r.imported.length === 1) location.hash = `#/activity/${r.imported[0].id}`;
      else route();
    } catch (e) { toast("Upload failed: " + e.message); }
  }
  $("#file-input").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });
  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; document.body.classList.add("dragging"); });
  window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragging");
    upload(e.dataTransfer.files);
  });

  // ------------------------------------------------------------------ settings
  $("#settings-btn").addEventListener("click", async () => {
    const s = await api("/api/settings");
    const f = $("#settings-form");
    for (const k of ["max_hr", "rest_hr", "ftp"]) f.elements[k].value = s[k];
    $("#settings-dialog").showModal();
  });
  $("#settings-dialog").addEventListener("close", async () => {
    if ($("#settings-dialog").returnValue !== "save") return;
    const f = $("#settings-form");
    const body = Object.fromEntries(["max_hr", "rest_hr", "ftp"].map((k) => [k, Number(f.elements[k].value)]));
    try {
      await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      toast("Settings saved — analytics recalculated");
      await loadList(); route();
    } catch (e) { toast("Could not save: " + e.message); }
  });

  // ------------------------------------------------------------------ sidebar list
  async function loadList() {
    state.activities = await api("/api/activities");
    const sports = [...new Set(state.activities.map((a) => a.sport))].sort();
    const sel = $("#sport-filter");
    if (!sports.includes(state.sport)) state.sport = "";
    sel.innerHTML = `<option value="">All sports</option>` +
      sports.map((s) => `<option value="${esc(s)}" ${s === state.sport ? "selected" : ""}>${esc(sportName(s))}</option>`).join("");
    renderList();
  }
  $("#sport-filter").addEventListener("change", (e) => { state.sport = e.target.value; renderList(); route(); });

  function renderList() {
    const items = state.activities.filter((a) => (!state.sport || a.sport === state.sport) && (!state.tagFilter || (a.tags || []).includes(state.tagFilter)));
    $("#count").textContent = `${items.length} activit${items.length === 1 ? "y" : "ies"}`;
    const ul = $("#activity-list");
    if (!items.length) { ul.innerHTML = `<li class="empty">No activities yet.</li>`; return; }
    const cur = state.current?.id;
    ul.innerHTML = items.map((a) => {
      const s = a.summary;
      const bits = [fmtDay(a.start_time)];
      if (s.distance_m) bits.push(`${fmtDist(s.distance_m)} ${u().distL}`);
      if (s.moving_s) bits.push(fmtDur(s.moving_s));
      return `<li><a href="#/activity/${a.id}" class="${a.id === cur ? "active" : ""}">
        <span class="icon" aria-hidden="true">${sportIcon(a.sport)}</span>
        <span class="name">${esc(a.name)}</span>
        <span class="meta">${esc(bits.filter(Boolean).join(" · "))}</span></a></li>`;
    }).join("");
  }

  // ------------------------------------------------------------------ charts common
  function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; state.hoverIdx = null; }

  function baseScales(xTitle) {
    const grid = { color: css("--grid"), drawTicks: false };
    const ticks = { color: css("--text-muted"), font: { size: 11 }, padding: 6 };
    return {
      x: { type: "linear", grid, ticks: { ...ticks, maxTicksLimit: 10 }, border: { display: false }, title: { display: !!xTitle, text: xTitle, color: css("--text-muted") } },
      y: { grid, ticks: { ...ticks, maxTicksLimit: 4 }, border: { display: false } },
    };
  }

  // Crosshair plugin: vertical line + dot at the shared hover index.
  const crosshair = {
    id: "crosshair",
    beforeDatasetsDraw(chart) {
      // Shade the drag selection (shared across all synced charts).
      const sel = state.sel;
      const ds = chart.data.datasets[0];
      if (!sel || !chart.$synced || !ds.data[sel.i0] || !ds.data[sel.i1]) return;
      const { ctx, chartArea, scales } = chart;
      const x0 = Math.max(chartArea.left, scales.x.getPixelForValue(ds.data[sel.i0].x));
      const x1 = Math.min(chartArea.right, scales.x.getPixelForValue(ds.data[sel.i1].x));
      ctx.save();
      ctx.fillStyle = css("--sel-fill");
      ctx.fillRect(x0, chartArea.top, x1 - x0, chartArea.bottom - chartArea.top);
      ctx.strokeStyle = css("--sel-edge"); ctx.lineWidth = 1.5;
      for (const x of [x0, x1]) { ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke(); }
      ctx.restore();
    },
    afterDatasetsDraw(chart) {
      const i = state.hoverIdx;
      const ds = chart.data.datasets[0];
      if (i == null || !chart.$synced || !ds.data[i]) return;
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(ds.data[i].x);
      if (x < chartArea.left || x > chartArea.right) return;
      ctx.save();
      ctx.strokeStyle = css("--text-muted"); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      const yv = ds.data[i].y;
      if (yv != null) {
        const y = scales.y.getPixelForValue(yv);
        ctx.fillStyle = ds.borderColor; ctx.strokeStyle = css("--surface-1"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
      ctx.restore();
    },
  };
  Chart.register(crosshair);

  // ------------------------------------------------------------------ dashboard
  // Remove the Leaflet map *before* its container leaves the page: a pending zoom/pan
  // animation on a detached map throws "_leaflet_pos" errors.
  function disposeMap() {
    runCleanups(); // module pages/cards free their maps and charts too
    if (!map) return;
    map.off(); map.stop(); map.remove(); map = null;
  }

  // Each navigation bumps the token; an async render that finds a newer token after an
  // await stops, so two overlapping navigations never draw into each other's page.
  let renderToken = 0;
  const newRender = () => ++renderToken;
  const stale = (token) => token !== renderToken;

  async function renderDashboard() {
    const token = newRender();
    disposeMap();
    destroyCharts();
    state.current = null; renderList();
    if (!state.activities.length) {
      main.innerHTML = `<div class="welcome"><h1>Your training, analysed</h1>
        <p class="muted">Upload activity files from your watch, bike computer or app — FIT, GPX and TCX are supported (gzipped too). Drag them anywhere on this page or use <b>Upload</b>.</p>
        <p><button class="btn primary" data-tour-start>🎓 Take the guided tour</button></p>
        <p class="muted small-note">A few minutes, hands-on, on a simulated run. Your data is not touched.</p></div>`;
      return;
    }
    main.innerHTML = `<div class="spinner">Loading…</div>`;
    const q = new URLSearchParams({ period: state.period });
    if (state.sport) q.set("sport", state.sport);
    const st = await api(`/api/stats?${q}`);
    if (stale(token)) return;
    const t = st.totals;
    const metricDefs = {
      distance_m: { label: `Distance (${u().distL})`, f: (v) => v / u().dist },
      moving_s: { label: "Moving time (h)", f: (v) => v / 3600 },
      elev_gain_m: { label: `Elevation gain (${u().eleL})`, f: (v) => v * u().ele },
      load: { label: "Training load (TSS / TRIMP)", f: (v) => v },
      count: { label: "Activities", f: (v) => v },
    };
    main.innerHTML = `
      <div class="page-head"><div><h1>${state.sport ? esc(sportName(state.sport)) : "All activities"}</h1>
        <div class="sub">Totals and trends across ${t.count} activit${t.count === 1 ? "y" : "ies"}</div></div></div>
      <div class="tiles">
        ${tile("Activities", fmtNum(t.count, 0))}
        ${tile("Distance", fmtDist(t.distance_m || 0, 0), u().distL)}
        ${tile("Moving time", fmtNum((t.moving_s || 0) / 3600, 1), "h")}
        ${tile("Elevation gain", fmtEle(t.elev_gain_m || 0), u().eleL)}
        ${t.tss ? tile("Total TSS", fmtNum(t.tss, 0)) : ""}
        ${t.trimp ? tile("Total TRIMP", fmtNum(t.trimp, 0)) : ""}
      </div>
      <div class="card"><h2><span id="trend-title"></span>
        <span style="display:flex;gap:8px;flex-wrap:wrap">
          <select id="metric-sel" aria-label="Metric">${Object.entries(metricDefs).map(([k, d]) => `<option value="${k}" ${k === state.metric ? "selected" : ""}>${esc(d.label)}</option>`).join("")}</select>
          <span class="seg" role="group" aria-label="Period"><button data-period="week">Weekly</button><button data-period="month">Monthly</button></span>
        </span></h2>
        <div class="chart-wrap tall"><canvas id="trend"></canvas></div>
      </div>
      <div class="grid two" style="margin-top:16px">
        ${Object.entries(st.records).map(([sp, recs]) => recordsCard(sp, recs)).join("")}
        ${st.power_curve.length ? `<div class="card"><h2>Power curve — all-time best</h2><div class="chart-wrap tall"><canvas id="pc-all"></canvas></div></div>` : ""}
      </div>`;
    document.querySelectorAll("[data-period]").forEach((b) => {
      b.classList.toggle("active", b.dataset.period === state.period);
      b.addEventListener("click", () => { state.period = b.dataset.period; renderDashboard(); });
    });
    $("#metric-sel").addEventListener("change", (e) => { state.metric = e.target.value; renderDashboard(); });

    const def = metricDefs[state.metric];
    $("#trend-title").textContent = `${def.label} per ${state.period}`;
    const periods = st.periods;
    const labels = periods.map((p) => {
      const d = new Date(p.period_start + "T00:00:00");
      return state.period === "week" ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
    });
    const color = css("--m-speed");
    state.charts.push(new Chart($("#trend"), {
      type: "bar",
      data: { labels, datasets: [{ data: periods.map((p) => def.f(p[state.metric] || 0)), backgroundColor: color, hoverBackgroundColor: color, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", maxBarThickness: 28, categoryPercentage: 0.9, barPercentage: 0.9 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: tooltipStyle({ callbacks: {
          title: (it) => (state.period === "week" ? "Week of " : "") + new Date(periods[it[0].dataIndex].period_start + "T00:00:00").toLocaleDateString(undefined, { dateStyle: "medium" }),
          label: (it) => {
            const p = periods[it.dataIndex];
            return [`${def.label}: ${fmtNum(it.raw, state.metric === "count" ? 0 : 1)}`, `${p.count} activit${p.count === 1 ? "y" : "ies"}`];
          } } }) },
        scales: { x: { ...baseScales().x, type: "category", grid: { display: false } }, y: { ...baseScales().y, beginAtZero: true } },
      },
    }));
    if (st.power_curve.length) powerCurveChart($("#pc-all"), st.power_curve, true);
  }

  function tooltipStyle(extra = {}) {
    return {
      backgroundColor: css("--surface-1"), titleColor: css("--text-primary"), bodyColor: css("--text-secondary"),
      borderColor: css("--border"), borderWidth: 1, padding: 10, displayColors: false, cornerRadius: 8, ...extra,
    };
  }

  function recordsCard(sport, recs) {
    if (!recs.length) return "";
    const pace = isPace(sport);
    return `<div class="card"><h2>${sportIcon(sport)} ${esc(sportName(sport))} — best efforts</h2><div class="table-scroll"><table>
      <thead><tr><th>Distance</th><th>Time</th><th>${pace ? "Pace /" + u().distL : "Speed " + u().speedL}</th><th>Activity</th></tr></thead><tbody>
      ${recs.map((r) => { const ms = r.distance_m / r.time_s; return `<tr><td>${effortLabel(r.distance_m)}</td><td>${fmtDur(r.time_s)}</td>
        <td>${pace ? fmtPace(ms) : fmtSpeed(ms)}</td>
        <td><a href="#/activity/${r.activity_id}">${esc(fmtDay(r.date) || r.activity_name)}</a></td></tr>`; }).join("")}
      </tbody></table></div></div>`;
  }

  function powerCurveChart(canvas, curve, withLinks) {
    const color = css("--m-power");
    state.charts.push(new Chart(canvas, {
      type: "line",
      data: { datasets: [{ data: curve.map((p) => ({ x: p.duration_s, y: p.value })), borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: css("--surface-1"), pointBorderWidth: 2, tension: 0.25 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: { legend: { display: false }, tooltip: tooltipStyle({ callbacks: {
          title: (it) => `Best ${durLabel(it[0].raw.x)}`,
          label: (it) => {
            const lines = [`${fmtNum(it.raw.y, 0)} W`];
            const p = curve[it.dataIndex];
            if (withLinks && p.date) lines.push(fmtDay(p.date));
            return lines;
          } } }) },
        scales: {
          x: { ...baseScales().x, type: "logarithmic", afterBuildTicks: (ax) => { ax.ticks = curve.map((p) => ({ value: p.duration_s })); }, ticks: { ...baseScales().x.ticks, callback: (v) => durLabel(v) } },
          y: { ...baseScales().y, title: { display: true, text: "Watts", color: css("--text-muted") } },
        },
        onClick: withLinks ? (evt, els) => { if (els[0]) location.hash = `#/activity/${curve[els[0].index].activity_id}`; } : undefined,
      },
    }));
  }

  function tile(label, value, unit = "") {
    return `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div></div>`;
  }

  // ------------------------------------------------------------------ activity view
  let map, hoverMarker, selLine, baseLine, overlayLayer, legendCtl, trackBounds;
  let mapMarkers = [];

  const activityHash = (id, w, laps) => `#/activity/${id}` + (w ? `?start=${w.start}&end=${w.end}${laps ? "&laps=1" : ""}` : "");
  function windowQuery(w) { return w ? `&start=${w.start}&end=${w.end}` : ""; }
  function exportLinks(a, w) {
    const timed = !!a.series.time_s;
    return ["gpx", "tcx", "fit"].map((f) => {
      const disabled = f !== "gpx" && !timed;
      return disabled
        ? `<span class="btn small" aria-disabled="true" title="${f.toUpperCase()} needs timestamps">${f.toUpperCase()}</span>`
        : `<a class="btn small" href="/api/activities/${a.id}/export?format=${f}${windowQuery(w)}" download>${f.toUpperCase()}</a>`;
    }).join("");
  }
  // In-page replacement for prompt() (which some embedded browsers block). Resolves to null on cancel.
  function askName(title, hint, def, okLabel) {
    const dlg = $("#name-dialog"), input = $("#name-form").elements.name;
    $("#name-title").textContent = title;
    $("#name-hint").textContent = hint;
    $("#name-ok").textContent = okLabel;
    input.value = def;
    dlg.returnValue = "";
    return new Promise((resolve) => {
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok" ? (input.value.trim() || def) : null), { once: true });
      dlg.showModal();
      input.select();
    });
  }

  async function saveClip(a, w, suggested) {
    const def = suggested || `${a.name} (clip)`;
    const name = await askName("Save as activity", "The selected stretch becomes a new, separate activity.", def, "Save");
    if (name === null) return;
    try {
      const r = await api(`/api/activities/${a.id}/clip`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: w.start, end: w.end, name: name.trim() || def }),
      });
      toast(r.duplicate ? "This selection was already saved — opening it" : "Saved as a new activity");
      await loadList();
      location.hash = `#/activity/${r.id}`;
    } catch (e) { toast("Could not save: " + e.message); }
  }

  async function renderActivity(id, win, opts = {}) {
    const token = newRender();
    disposeMap();
    destroyCharts();
    state.sel = null; state.lap = null; state.lapRange = null; state.effort = null; state.named = null; state.selListeners = [];
    endPick();
    main.innerHTML = `<div class="spinner">Analysing…</div>`;
    let a, laps = null;
    try {
      const lapsReq = opts.laps && win ? api(`/api/activities/${id}/laps`).catch(() => null) : null;
      a = await api(`/api/activities/${id}?split=${u().split}${windowQuery(win)}`);
      laps = await lapsReq;
    } catch (e) {
      if (stale(token)) return;
      main.innerHTML = `<div class="welcome"><h1>Not found</h1><p class="muted">${esc(e.message)}</p><a href="#/">Back to dashboard</a></div>`; return;
    }
    if (stale(token)) return;
    state.current = a; renderList();
    const lapsMode = !!(laps && a.window);
    // Segment efforts inside the current view (indices are absolute, like the window).
    const efforts = (a.segment_efforts || []).filter((e) => !a.window || (e.start >= a.window.start && e.end <= a.window.end));
    const s = a.summary;
    const pace = isPace(a.sport);

    const tiles = [
      s.distance_m ? tile("Distance", fmtDist(s.distance_m), u().distL) : "",
      s.moving_s != null ? tile("Moving time", fmtDur(s.moving_s)) : "",
      s.elapsed_s != null ? tile("Elapsed time", fmtDur(s.elapsed_s)) : "",
      s.avg_speed_ms ? (pace ? tile("Avg pace", fmtPace(s.avg_speed_ms), "/" + u().distL) : tile("Avg speed", fmtSpeed(s.avg_speed_ms), u().speedL)) : "",
      s.max_speed_ms && !pace ? tile("Max speed", fmtSpeed(s.max_speed_ms), u().speedL) : "",
      s.elev_gain_m != null ? tile("Elevation gain", fmtEle(s.elev_gain_m), u().eleL) : "",
      s.avg_hr ? tile("Avg heart rate", fmtNum(s.avg_hr, 0), "bpm") : "",
      s.max_hr ? tile("Max heart rate", fmtNum(s.max_hr, 0), "bpm") : "",
      s.avg_power ? tile("Avg power", fmtNum(s.avg_power, 0), "W") : "",
      s.normalized_power ? tile("Normalized power", fmtNum(s.normalized_power, 0), "W") : "",
      s.intensity_factor ? tile("Intensity factor", fmtNum(s.intensity_factor, 2)) : "",
      s.tss ? tile("TSS", fmtNum(s.tss, 0)) : "",
      s.work_kj ? tile("Work", fmtNum(s.work_kj, 0), "kJ") : "",
      s.trimp ? tile("TRIMP", fmtNum(s.trimp, 0)) : "",
      s.avg_cadence ? tile("Avg cadence", fmtNum(s.avg_cadence, 0), cadenceUnit(a.sport)) : "",
      s.avg_temp_c != null ? tile("Avg temp", fmtNum(s.avg_temp_c, 0), "°C") : "",
    ].join("");

    main.innerHTML = `
      <div class="page-head">
        <div style="flex:1;min-width:240px">
          <input class="title-input" id="name-input" value="${esc(a.name)}" aria-label="Activity name" maxlength="200">
          <div class="sub">${sportIcon(a.sport)} ${esc(fmtDate(a.start_time))} · ${esc(a.source_format.toUpperCase())}${a.device ? " · " + esc(a.device) : ""}</div>
          <div class="tag-row" id="tag-row"></div>
          <div class="module-head" id="module-head"></div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${a.window ? "" : `<span class="export-group" aria-label="Export full activity"><span class="muted">Export</span>${exportLinks(a, null)}</span>`}
          ${a.track && !a.window ? `<button class="btn" id="seg-act-btn" title="Make the whole activity a segment and find it in all activities">Create segment</button>` : ""}
          <select id="sport-sel" aria-label="Sport">${sportSelectOptions(a.sport)}</select>
          <button class="btn danger" id="del-btn">Delete</button>
        </div>
      </div>
      ${a.laps && !lapsMode ? `<div class="lap-hint" role="status">
        <div><span aria-hidden="true">🔁</span> <strong>Repeating laps detected</strong> — ${a.laps.count} × ${fmtDist(a.laps.lap_distance_m)} ${u().distL}</div>
        <a class="btn small primary" href="${activityHash(a.id, a.laps, true)}">Analyze laps</a></div>` : ""}
      ${a.window ? `<div class="trim-banner" role="status">
        <div><strong>${lapsMode ? `Laps view — ${laps.count} laps` : "Trimmed view"}</strong> — ${fmtDist(s.distance_m || 0)} ${u().distL}${s.elapsed_s != null ? ` · ${fmtDur(s.elapsed_s)}` : ""}
          <span class="muted">(${lapsMode ? "warm-up and cool-down left out; " : `points ${a.window.start}–${a.window.end} of ${a.window.total_points}; `}temporary, the original is unchanged)</span></div>
        <div class="trim-actions">
          <span class="export-group"><span class="muted">Cut to new file</span>${exportLinks(a, a.window)}</span>
          <button class="btn small" id="clip-btn">Save as activity</button>
          ${a.track ? `<button class="btn small" id="seg-act-btn" title="Make this ${lapsMode ? "laps section" : "trimmed view"} a segment and find it in all activities">Create segment</button>` : ""}
          <a class="btn small primary" href="${activityHash(a.id)}">Show full activity</a>
        </div></div>` : ""}
      <div class="tiles">${tiles}</div>
      <div class="stack">
        ${lapsMode ? `<div class="card"><h2><span>Summary</span><span class="muted" style="font-weight:400" id="lap-stats"></span></h2><div id="lap-compare"></div></div>` : ""}
        ${lapsMode || a.track ? `<div class="${lapsMode && a.track ? "grid two" : "stack"}">
          ${lapsMode ? `<div class="card"><h2><span>Lap times</span><span class="muted" style="font-weight:400">click a lap to select it</span></h2><div class="chart-wrap lap-chart-wrap"><canvas id="lap-chart"></canvas></div></div>` : ""}
          ${a.track ? `<div class="map-slot"><div class="card map-card" id="map-card">
            <div class="map-head">
              <span class="ov-controls">
                <label class="ov-label">Colour track by <select id="ov-sel"></select></label>
                <label class="ov-label" id="pal-wrap">Colours <select id="pal-sel">${Object.entries(PALETTES).map(([k, p]) => `<option value="${k}" ${k === state.palette ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
                <button class="btn small" id="pal-rev" aria-pressed="${state.paletteReverse}" title="Reverse the colour order">⇄ Reverse</button>
              </span>
              <span class="ov-controls">
                <button class="btn small" id="map-pick" aria-pressed="false" title="Click the start, then the end of a section on the track">✚ Pick section</button>
                <button class="btn small" id="map-size" aria-pressed="false" title="Enlarge map">⤢ Enlarge</button>
              </span>
            </div>
            <div id="map"></div></div></div>` : ""}
        </div>` : ""}
        ${lapsMode ? `<div class="card"><h2><span>Laps</span><span class="muted" style="font-weight:400">click a row, then ↑/↓ to step through</span></h2><div class="table-scroll lap-list" id="lap-list"></div></div>` : ""}
        ${efforts.length ? `<div class="card" id="seg-card"><h2><span>Segments</span><span class="muted" style="font-weight:400">${efforts.length} effort${efforts.length === 1 ? "" : "s"} · click a row to show it</span></h2>
          <div class="table-scroll lap-list" id="seg-list">${segEffortsTable(a, efforts)}</div></div>` : ""}
        <div class="card" id="charts-card"><h2><span>Data streams</span>
          ${a.series.time_s ? `<span class="seg" role="group" aria-label="X axis"><button data-x="distance">Distance</button><button data-x="time">Time</button></span>` : ""}</h2>
          <div class="readout" id="readout"><span class="muted">Hover a chart to inspect values${a.track ? " and locate the point on the map" : ""}. Drag across a chart to select a section.</span></div>
          <div class="sel-bar" id="sel-bar" hidden></div>
          <div id="charts"></div>
        </div>
        <div id="module-cards" class="stack"></div>
        <div class="grid two">
          ${a.hr_zones ? `<div class="card"><h2>Heart-rate zones <span class="muted" style="font-weight:400">max ${a.settings_used.max_hr} bpm</span></h2>${zonesHtml(a.hr_zones)}</div>` : ""}
          ${a.splits.length ? `<div class="card"><h2>Splits per ${u().split}</h2>${splitsHtml(a.splits, pace)}</div>` : ""}
          ${a.best_efforts.length ? `<div class="card"><h2>Best efforts</h2>${effortsHtml(a.best_efforts, pace)}</div>` : ""}
          ${a.power_curve?.length ? `<div class="card"><h2>Power curve <span class="muted" style="font-weight:400">FTP ${a.settings_used.ftp} W</span></h2><div class="chart-wrap tall"><canvas id="pc"></canvas></div></div>` : ""}
        </div>
      </div>`;

    $("#name-input").addEventListener("change", async (e) => {
      const name = e.target.value.trim();
      if (!name) { e.target.value = a.name; return; }
      await api(`/api/activities/${a.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      a.name = name; toast("Renamed"); loadList();
    });
    $("#name-input").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
    $("#sport-sel").addEventListener("change", async (e) => {
      await api(`/api/activities/${a.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sport: e.target.value }) });
      await loadList(); renderActivity(a.id);
    });
    $("#clip-btn")?.addEventListener("click", () => saveClip(a, a.window));
    $("#seg-act-btn")?.addEventListener("click", () =>
      createSegment(a, a.window || { start: 0, end: a.summary.points - 1 }, a.window ? `${a.name} (part)` : a.name));
    $("#del-btn").addEventListener("click", async () => {
      if (!confirm(`Delete “${a.name}”? This cannot be undone.`)) return;
      await api(`/api/activities/${a.id}`, { method: "DELETE" });
      toast("Activity deleted"); await Promise.all([loadList(), loadSegments()]); location.hash = "#/";
    });

    renderTagEditor(a);
    if (a.track) drawMap(a, lapsMode ? laps : null);
    let xMode = lsGet("xmode") === "time" && a.series.time_s ? "time" : "distance";
    if (!a.series.distance_m.at(-1)) xMode = a.series.time_s ? "time" : "distance";
    const setX = (mode) => {
      xMode = mode; lsSet("xmode", mode);
      document.querySelectorAll("[data-x]").forEach((b) => b.classList.toggle("active", b.dataset.x === mode));
      drawStreams(a, xMode);
    };
    document.querySelectorAll("[data-x]").forEach((b) => b.addEventListener("click", () => setX(b.dataset.x)));
    setX(xMode);
    if (a.power_curve?.length) powerCurveChart($("#pc"), a.power_curve, false);
    if (lapsMode) renderLaps(a, laps);
    if (efforts.length) wireSegEfforts(a, efforts);
    renderModuleCards(a);
    if (opts.effort) {
      const e = efforts.find((x) => x.id === opts.effort);
      if (e) { selectEffort(a, e); $("#seg-card")?.scrollIntoView({ block: "center" }); }
      else toast("That segment effort is not in this view");
    }
  }

  // ------------------------------------------------------------------ segments on an activity
  function segEffortsTable(a, efforts) {
    const pace = isPace(a.sport);
    const has = (k) => efforts.some((e) => e[k] != null);
    return `<table><thead><tr><th>Segment</th><th>Time</th><th>${pace ? "Pace" : "Speed"}</th>${has("avg_hr") ? "<th>Avg HR</th>" : ""}${has("avg_power") ? "<th>Power</th>" : ""}<th>Rank</th><th></th></tr></thead><tbody>
      ${efforts.map((e) => `<tr data-effort="${e.id}" tabindex="0" aria-selected="false">
        <td class="name-cell"><a href="#/segment/${e.segment_id}" title="Open segment">${esc(e.segment_name)}</a></td>
        <td>${fmtDur(e.elapsed_s)}</td>
        <td>${e.speed_ms == null ? "–" : pace ? `${fmtPace(e.speed_ms)} /${u().distL}` : `${fmtSpeed(e.speed_ms)} ${u().speedL}`}</td>
        ${has("avg_hr") ? `<td>${fmtNum(e.avg_hr, 0)}</td>` : ""}${has("avg_power") ? `<td>${fmtNum(e.avg_power, 0)}</td>` : ""}
        <td>${rankBadge(e)}</td>
        <td><a class="btn small" href="${activityHash(a.id, e)}" title="Trimmed view of this effort">View</a></td></tr>`).join("")}
      </tbody></table>`;
  }
  const rankBadge = (e) => (e.rank === 1 ? `<span class="badge pr">🏆 Best</span>` : `<span class="muted">${e.rank} / ${e.of}</span>`);

  function selectEffort(a, e) {
    const idx = a.series.idx;
    state.sel = { i0: nearestIdx(idx, e.start), i1: nearestIdx(idx, e.end) };
    state.lap = null; state.lapRange = null;
    state.effort = { id: e.id, name: e.segment_name, range: { ...state.sel } };
    renderSelection(a);
  }

  function wireSegEfforts(a, efforts) {
    const list = $("#seg-list");
    const pick = (id) => {
      if (state.effort?.id === id) { state.sel = null; renderSelection(a); return; }
      selectEffort(a, efforts.find((e) => e.id === id));
    };
    list.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return; // links navigate
      const tr = ev.target.closest("tr[data-effort]");
      if (tr) pick(Number(tr.dataset.effort));
    });
    list.addEventListener("keydown", (ev) => {
      const tr = ev.target.closest("tr[data-effort]");
      if (tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); pick(Number(tr.dataset.effort)); }
    });
    state.selListeners.push(() => list.querySelectorAll("tr[data-effort]").forEach((tr) =>
      tr.setAttribute("aria-selected", String(Number(tr.dataset.effort) === state.effort?.id))));
  }

  async function createSegment(a, w, suggested) {
    const def = suggested || (state.lap ? `${a.name} lap` : `${a.name} segment`);
    const name = await askName("Create segment", "All activities that follow this stretch, now and later, get an effort on it.", def, "Create");
    if (name === null) return;
    toast("Creating segment and searching all activities…");
    try {
      const s = await api("/api/segments", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ activity_id: a.id, start: w.start, end: w.end, name: name.trim() || def }),
      });
      toast(`Segment created — ${s.efforts.length} effort${s.efforts.length === 1 ? "" : "s"} in ${s.activities.length} activit${s.activities.length === 1 ? "y" : "ies"}`);
      await loadSegments();
      location.hash = `#/segment/${s.id}`;
    } catch (e) { toast("Could not create segment: " + e.message); }
  }

  // Map "pick section": click the start, then the end on the track.
  function nearestOnTrack(se, latlng, after = -1) {
    const p = map.latLngToContainerPoint(latlng);
    const cand = [];
    let best = Infinity;
    for (let k = after + 1; k < se.lat.length; k++) {
      if (se.lat[k] == null || se.lon[k] == null) continue;
      const q = map.latLngToContainerPoint([se.lat[k], se.lon[k]]);
      const d = Math.hypot(p.x - q.x, p.y - q.y);
      cand.push([k, d]);
      best = Math.min(best, d);
    }
    if (best > 25) return null; // pixels: the click must be on (or right next to) the track
    // Where the track passes the spot several times (laps), take the first pass.
    return cand.find(([, d]) => d <= best + 6)[0];
  }

  function startPick(a) {
    if (state.pick) { endPick(); return; }
    state.sel = null; renderSelection(a);
    state.pick = { a, i0: null, marker: null };
    $("#map-pick").setAttribute("aria-pressed", "true");
    $("#map").classList.add("picking");
    toast("Click the START of the section on the track");
    map.on("click", onPickClick);
  }

  function onPickClick(ev) {
    const pk = state.pick;
    if (!pk) return;
    const se = pk.a.series;
    const k = nearestOnTrack(se, ev.latlng, pk.i0 ?? -1);
    if (k == null) { toast(pk.i0 == null ? "Click on the track to set the start" : "Click on the track, after the start, to set the end"); return; }
    if (pk.i0 == null) {
      pk.i0 = k;
      pk.marker = L.circleMarker([se.lat[k], se.lon[k]], { radius: 7, color: css("--surface-1"), weight: 2, fillColor: css("--sel-edge"), fillOpacity: 1 }).addTo(map);
      toast("Now click the END of the section");
      return;
    }
    const a = pk.a, i0 = pk.i0;
    endPick();
    state.sel = { i0, i1: k };
    renderSelection(a);
    $("#sel-bar")?.scrollIntoView({ block: "nearest" });
  }

  function endPick() {
    if (!state.pick) return;
    state.pick.marker?.remove();
    state.pick = null;
    if (map) map.off("click", onPickClick);
    $("#map-pick")?.setAttribute("aria-pressed", "false");
    $("#map")?.classList.remove("picking");
  }

  // ------------------------------------------------------------------ map
  function drawMap(a, laps) {
    disposeMap();
    const track = a.track;
    map = L.map("map", { scrollWheelZoom: false, preferCanvas: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    baseLine = L.polyline(track, { color: css("--accent"), weight: 4, opacity: 0.9, interactive: false }).addTo(map);
    trackBounds = baseLine.getBounds();
    map.fitBounds(trackBounds, { padding: [20, 20] });
    overlayLayer = L.layerGroup().addTo(map);
    const dot = (latlng, color) => L.circleMarker(latlng, { radius: 6, color: css("--surface-1"), weight: 2, fillColor: color, fillOpacity: 1 }).addTo(map);
    mapMarkers = [dot(track[0], css("--m-elevation")).bindTooltip("Start"), dot(track.at(-1), css("--text-primary")).bindTooltip("Finish")];
    if (laps?.gate) {
      mapMarkers.push(L.circleMarker(laps.gate, { radius: 7, color: css("--text-primary"), weight: 3, fillColor: css("--surface-1"), fillOpacity: 1 })
        .addTo(map).bindTooltip("Lap start / finish"));
    }
    hoverMarker = L.circleMarker(track[0], { radius: 7, color: css("--surface-1"), weight: 2, fillColor: css("--m-hr"), opacity: 0, fillOpacity: 0, interactive: false }).addTo(map);
    legendCtl = L.control({ position: "bottomleft" });
    legendCtl.onAdd = () => { const d = L.DomUtil.create("div", "map-legend"); d.hidden = true; return d; };
    legendCtl.addTo(map);

    const defs = overlayDefs(a);
    if (!defs.some((d) => d.key === state.overlay)) state.overlay = "none";
    const sel = $("#ov-sel");
    sel.innerHTML = `<option value="none">Nothing (route only)</option>` +
      defs.map((d) => `<option value="${d.key}" ${d.key === state.overlay ? "selected" : ""}>${esc(d.label)}</option>`).join("");
    sel.addEventListener("change", () => { state.overlay = sel.value; lsSet("overlay", sel.value); drawOverlay(a); });
    $("#pal-sel").addEventListener("change", (e) => { state.palette = e.target.value; lsSet("palette", state.palette); drawOverlay(a); });
    $("#pal-rev").addEventListener("click", (e) => {
      state.paletteReverse = !state.paletteReverse; lsSet("paletteReverse", state.paletteReverse ? "1" : "0");
      e.currentTarget.setAttribute("aria-pressed", String(state.paletteReverse)); drawOverlay(a);
    });
    $("#map-size").addEventListener("click", () => setMapExpanded(!$("#map-card").classList.contains("expanded")));
    $("#map-pick").addEventListener("click", () => startPick(a));
    if (new URLSearchParams(location.search).has("debug")) window.__fitpushMap = map; // for UI tests
    drawOverlay(a);
  }

  function setMapExpanded(on) {
    const card = $("#map-card");
    if (!card || !map) return;
    const slot = card.parentElement;
    slot.style.height = on ? `${card.offsetHeight}px` : ""; // keep the page from jumping
    card.classList.toggle("expanded", on);
    document.body.classList.toggle("map-open", on);
    const b = $("#map-size");
    b.setAttribute("aria-pressed", String(on));
    b.textContent = on ? "⤡ Minimize" : "⤢ Enlarge";
    b.title = on ? "Minimize map (Esc)" : "Enlarge map";
    if (on) map.scrollWheelZoom.enable(); else map.scrollWheelZoom.disable();
    map.invalidateSize({ animate: false });
    // No animation: a zoom animation still pending when the page changes makes Leaflet's
    // transition-end timer run on a removed map ("_leaflet_pos" error).
    map.fitBounds(selLine ? selLine.getBounds() : trackBounds, { padding: [30, 30], animate: false });
  }

  // Colour patterns for the track overlay (stops low -> high). "default" uses the theme tokens:
  // one-hue blue for magnitudes and blue <-> gray <-> red for the speed delta.
  const PALETTES = {
    default: { label: "Default (blue / blue–red)" },
    rainbow: { label: "Rainbow", stops: ["#2b00ff", "#0080ff", "#00e0ff", "#00e060", "#c0f000", "#ffb000", "#ff2000"] },
    turbo: { label: "Turbo", stops: ["#30123b", "#4662d7", "#36aaf9", "#1ae4b6", "#72fe5e", "#c7ef34", "#fabb36", "#f66b19", "#ca2a04", "#7a0403"] },
    hot: { label: "Red hot", stops: ["#1a0000", "#600000", "#b00000", "#ff2000", "#ff8000", "#ffd000", "#ffff80", "#ffffff"] },
    viridis: { label: "Viridis", stops: ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"] },
    plasma: { label: "Plasma", stops: ["#0d0887", "#46039f", "#7201a8", "#9c179e", "#bd3786", "#d8576b", "#ed7953", "#fb9f3a", "#fdca26", "#f0f921"] },
    coolwarm: { label: "Cool–warm", stops: ["#3b4cc0", "#7092f3", "#aac7fd", "#dddddd", "#f7b89c", "#e7745b", "#b40426"] },
    traffic: { label: "Green → red", stops: ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#fc8d59", "#d73027"] },
    gray: { label: "Grayscale", stops: ["#f2f2f2", "#bdbdbd", "#878787", "#525252", "#1a1a1a"] },
  };
  const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  function sampleStops(stops, n) {
    const rgb = stops.map(hexRgb);
    return Array.from({ length: n }, (_, k) => {
      const p = (k / (n - 1)) * (rgb.length - 1), i = Math.min(Math.floor(p), rgb.length - 2), f = p - i;
      return "#" + rgb[i].map((c, j) => Math.round(c + (rgb[i + 1][j] - c) * f).toString(16).padStart(2, "0")).join("");
    });
  }
  function paletteSteps(diverging) {
    const pal = PALETTES[state.palette] || PALETTES.default;
    const steps = pal.stops ? sampleStops(pal.stops, 12)
      : Array.from({ length: 7 }, (_, i) => css(`--${diverging ? "dv" : "ov"}-${i + 1}`));
    return state.paletteReverse ? steps.reverse() : steps;
  }

  function quantile(sorted, q) {
    if (!sorted.length) return null;
    const p = (sorted.length - 1) * q, lo = Math.floor(p), hi = Math.ceil(p);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (p - lo);
  }

  // Parameters that can colour the track. Values are per series point (same index as lat/lon).
  function overlayDefs(a) {
    const se = a.series, pace = isPace(a.sport), defs = [];
    const moving = (v) => (v != null && v >= 0.3 ? v : null);
    if (se.speed_ms && se.distance_m.at(-1) > 0) {
      defs.push({ key: "speed", label: pace ? "Pace" : "Speed", values: se.speed_ms.map(moving),
        fmt: (v) => (pace ? `${fmtPace(v)} /${u().distL}` : `${fmtSpeed(v)} ${u().speedL}`),
        // pace numbers run opposite to speed, so "≤" would read backwards
        ends: pace ? (lo, hi, f) => [`${f(lo)} or slower`, `${f(hi)} or faster`] : null });
    }
    if (se.elevation_m) defs.push({ key: "elevation", label: "Elevation", values: se.elevation_m, fmt: (v) => `${fmtEle(v)} ${u().eleL}` });
    if (se.hr) defs.push({ key: "hr", label: "Heart rate", values: se.hr, fmt: (v) => `${fmtNum(v, 0)} bpm` });
    if (se.power) defs.push({ key: "power", label: "Power", values: se.power, fmt: (v) => `${fmtNum(v, 0)} W` });
    const avg = a.summary.avg_speed_ms;
    if (se.speed_ms && avg) {
      defs.push({ key: "delta", label: "Speed Δ vs average", diverging: true,
        values: se.speed_ms.map((v) => (moving(v) == null ? null : v - avg)),
        fmt: (v) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmtSpeed(Math.abs(v))} ${u().speedL}`,
        note: `average ${pace ? `${fmtPace(avg)} /${u().distL}` : `${fmtSpeed(avg)} ${u().speedL}`}` });
    }
    return defs;
  }

  function drawOverlay(a) {
    if (!map) return;
    overlayLayer.clearLayers();
    const def = overlayDefs(a).find((d) => d.key === state.overlay);
    const legend = legendCtl.getContainer();
    for (const id of ["#pal-wrap", "#pal-rev"]) { const el = $(id); if (el) el.hidden = !def; }
    if (!def) {
      baseLine.setStyle({ opacity: 0.9 });
      legend.hidden = true;
      raiseMapMarks();
      return;
    }
    baseLine.setStyle({ opacity: 0 });
    const steps = paletteSteps(def.diverging);
    const vals = def.values.filter((v) => v != null).sort((x, y) => x - y);
    let lo, hi;
    if (def.diverging) { // symmetric around 0 so the gray middle step means "average"
      const lim = quantile(vals.map(Math.abs).sort((x, y) => x - y), 0.95) || 1;
      lo = -lim; hi = lim;
    } else {             // clip outliers (GPS spikes, stops) to the 5th–95th percentile
      lo = quantile(vals, 0.05); hi = quantile(vals, 0.95);
      if (!(hi - lo > 1e-9)) hi = lo + 1;
    }
    const bin = (v) => (v == null ? -1 : Math.max(0, Math.min(steps.length - 1, Math.floor(((v - lo) / (hi - lo)) * steps.length))));

    // With a selection (e.g. one lap), only that part keeps full colour; the rest fades,
    // so overlapping laps don't hide each other.
    const sel = state.sel, inSel = (k) => !sel || (k >= sel.i0 && k <= sel.i1);
    const se = a.series, pts = [];
    for (let k = 0; k < se.lat.length; k++) {
      if (se.lat[k] != null && se.lon[k] != null) pts.push({ ll: [se.lat[k], se.lon[k]], b: bin(def.values[k]), on: inSel(k) });
    }
    const drawRuns = (subset, weight, opacity, casing) => {
      for (const part of subset) {
        if (part.length < 2) continue;
        if (casing) L.polyline(part.map((p) => p.ll), { color: css("--map-casing"), weight: weight + 3.5, opacity, interactive: false }).addTo(overlayLayer);
        let run = [part[0].ll], cur = part[0].b;
        const flush = () => L.polyline(run, { color: cur < 0 ? css("--text-muted") : steps[cur], weight, opacity, lineJoin: "round", interactive: false }).addTo(overlayLayer);
        for (let k = 1; k < part.length; k++) {
          run.push(part[k].ll);
          if (part[k].b !== cur || k === part.length - 1) { flush(); run = [part[k].ll]; cur = part[k].b; }
        }
      }
    };
    const split = (on) => { // contiguous stretches inside / outside the selection (joined at the edges)
      const parts = [];
      let cur = null;
      for (let k = 0; k < pts.length; k++) {
        if (pts[k].on === on) { cur ||= k > 0 ? [pts[k - 1]] : []; cur.push(pts[k]); }
        else if (cur) { cur.push(pts[k]); parts.push(cur); cur = null; }
      }
      if (cur) parts.push(cur);
      return parts;
    };
    if (sel) drawRuns(split(false), 3, 0.25, false);
    // Casing under the coloured line keeps pale steps visible on any map tile.
    drawRuns(sel ? split(true) : [pts], 4.5, 1, true);
    const [loTxt, hiTxt] = def.ends ? def.ends(lo, hi, def.fmt)
      : def.diverging ? [`slower ${def.fmt(lo)}`, `faster ${def.fmt(hi)}`]
      : [`≤ ${def.fmt(lo)}`, `≥ ${def.fmt(hi)}`];
    legend.hidden = false;
    legend.innerHTML = `<div class="lg-title">${esc(def.label)}${def.note ? ` <span class="muted">(${esc(def.note)})</span>` : ""}</div>
      <div class="lg-ramp">${steps.map((c) => `<span style="background:${c}"></span>`).join("")}</div>
      <div class="lg-labels"><span>${esc(loTxt)}</span>${def.diverging ? "<span>avg</span>" : ""}<span>${esc(hiTxt)}</span></div>
      ${sel ? `<div class="muted lg-note">Colour shows the selection; the rest is faded.</div>` : ""}`;
    raiseMapMarks();
  }

  // Keep markers above the track; with an overlay, the selection becomes a halo underneath.
  function raiseMapMarks() {
    if (selLine) {
      if (state.overlay !== "none" && overlayLayer.getLayers().length) selLine.setStyle({ weight: 16, opacity: 0.55 }).bringToBack();
      else selLine.setStyle({ weight: 6, opacity: 0.95 }).bringToFront();
    }
    mapMarkers.forEach((m) => m.bringToFront());
    hoverMarker?.bringToFront();
  }

  function streamDefs(a) {
    const se = a.series;
    const pace = isPace(a.sport);
    const defs = [];
    if (se.elevation_m) defs.push({ key: "elevation", label: `Elevation (${u().eleL})`, color: "--m-elevation", fill: true, y: se.elevation_m.map((v) => (v == null ? null : v * u().ele)), fmt: (v) => `${fmtNum(v, 0)} ${u().eleL}` });
    if (se.speed_ms && se.distance_m.at(-1) > 0) {
      if (pace) {
        // Pace: clamp slow stretches (stops) so the axis stays readable; faster = higher.
        const ys = se.speed_ms.map((v) => { const p = paceSec(v); return p == null || p > 1200 ? null : p; });
        defs.push({ key: "pace", label: `Pace (/${u().distL})`, color: "--m-speed", y: ys, reverse: true, fmt: (v) => `${fmtDur(v)} /${u().distL}`, tick: (v) => fmtDur(v) });
      } else {
        defs.push({ key: "speed", label: `Speed (${u().speedL})`, color: "--m-speed", y: se.speed_ms.map((v) => (v == null ? null : v * u().speed)), fmt: (v) => `${fmtNum(v, 1)} ${u().speedL}` });
      }
    }
    if (se.hr) defs.push({ key: "hr", label: "Heart rate (bpm)", color: "--m-hr", y: se.hr, fmt: (v) => `${fmtNum(v, 0)} bpm` });
    if (se.power) defs.push({ key: "power", label: "Power (W, 5 s avg)", color: "--m-power", y: se.power, fmt: (v) => `${fmtNum(v, 0)} W` });
    if (se.cadence) defs.push({ key: "cadence", label: `Cadence (${cadenceUnit(a.sport)})`, color: "--m-cadence", y: se.cadence, fmt: (v) => fmtNum(v, 0) });
    if (se.temp_c) defs.push({ key: "temp", label: "Temperature (°C)", color: "--m-temp", y: se.temp_c, fmt: (v) => `${fmtNum(v, 0)} °C` });
    return defs;
  }

  function drawStreams(a, xMode) {
    state.charts.filter((c) => c.$synced).forEach((c) => c.destroy());
    state.charts = state.charts.filter((c) => !c.$synced);
    const se = a.series;
    const xs = xMode === "time" ? se.time_s : se.distance_m.map((d) => d / u().dist);
    const xTitle = xMode === "time" ? "Elapsed time" : `Distance (${u().distL})`;
    const defs = streamDefs(a);
    const box = $("#charts");
    if (!defs.length) { box.innerHTML = `<p class="muted">This file has no sensor streams to plot.</p>`; return; }
    box.innerHTML = defs.map((d, i) => `<div class="chart-block"><div class="chart-title"><span class="sw" style="background:var(${d.color})"></span>${esc(d.label)}</div>
      <div class="chart-wrap" style="${i === defs.length - 1 ? "height:150px" : ""}"><canvas data-key="${d.key}"></canvas></div></div>`).join("");

    const xMin = xs[0], xMax = xs.at(-1);
    defs.forEach((d, i) => {
      const color = css(d.color);
      const last = i === defs.length - 1;
      const scales = baseScales(last ? xTitle : "");
      scales.x.min = xMin; scales.x.max = xMax;
      scales.x.ticks.display = last;
      scales.x.ticks.callback = xMode === "time" ? (v) => fmtDur(v) : (v) => fmtNum(v, xMax < 10 ? 1 : 0);
      scales.y.reverse = !!d.reverse;
      if (d.tick) scales.y.ticks.callback = d.tick;
      scales.y.afterFit = (ax) => { ax.width = 56; }; // align plot areas across charts
      const chart = new Chart(box.querySelector(`canvas[data-key="${d.key}"]`), {
        type: "line",
        data: { datasets: [{ data: xs.map((x, j) => ({ x, y: d.y[j] })), borderColor: color, borderWidth: 2, pointRadius: 0, spanGaps: true, tension: 0,
          fill: d.fill ? "start" : false, backgroundColor: color + "33" }] },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
          events: [], // hover is handled by our own sync listeners
          layout: { padding: { right: 12 } }, // same plot width on every chart (last one has x labels)
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          scales,
        },
      });
      chart.$synced = true; chart.$def = d;
      state.charts.push(chart);
      const canvas = chart.canvas;
      const idxAt = (clientX) => {
        const rect = canvas.getBoundingClientRect();
        return nearestIdx(xs, chart.scales.x.getValueForPixel(clientX - rect.left));
      };
      // Drag to select a section; a plain click clears the selection.
      canvas.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        state.drag = { from: idxAt(e.clientX), moved: false };
      });
      canvas.addEventListener("mousemove", (e) => {
        const i = idxAt(e.clientX);
        if (state.drag && i !== state.drag.from) {
          state.drag.moved = true;
          state.sel = { i0: Math.min(state.drag.from, i), i1: Math.max(state.drag.from, i) };
        }
        setHover(i, a, xs, xMode);
      });
      canvas.addEventListener("touchmove", (e) => { if (e.touches[0]) setHover(idxAt(e.touches[0].clientX), a, xs, xMode); }, { passive: true });
      canvas.addEventListener("mouseleave", () => { if (!state.drag) setHover(null, a, xs, xMode); });
    });
    state.onDragEnd = () => {
      if (!state.drag.moved) state.sel = null;
      state.drag = null;
      renderSelection(a);
    };
    renderSelection(a);
  }

  window.addEventListener("mouseup", () => { if (state.drag) state.onDragEnd?.(); });
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (state.pick) { endPick(); return; }
    if ($("#map-card.expanded")) { setMapExpanded(false); return; }
    if (state.sel && state.current) { state.sel = null; renderSelection(state.current); }
  });

  function renderSelection(a) {
    const sel = state.sel;
    const same = (r) => sel && r && sel.i0 === r.i0 && sel.i1 === r.i1;
    // A drag or Clear replaces a selected lap / segment effort.
    if (state.lap && !same(state.lapRange)) { state.lap = null; state.lapRange = null; }
    if (state.effort && !same(state.effort.range)) state.effort = null;
    if (state.named && !same(state.named.range)) state.named = null;
    try { drawSelection(a, sel); } finally { state.selListeners.forEach((f) => f()); }
  }

  // Label of the current selection: a lap, a segment effort, or a free selection.
  function selectionLabel(a) {
    if (state.lap) return { title: `Lap ${state.lap}`, noun: "lap", name: `${a.name} – lap ${state.lap}` };
    if (state.effort) return { title: `Segment “${state.effort.name}”`, noun: "effort", name: `${a.name} – ${state.effort.name}` };
    if (state.named) return { title: state.named.name, noun: "selection", name: `${a.name} – ${state.named.name}` };
    return { title: "Selection", noun: "selection", name: undefined };
  }

  function drawSelection(a, sel) {
    state.charts.filter((c) => c.$synced).forEach((c) => c.draw());
    const bar = $("#sel-bar");
    if (!bar) return;
    const se = a.series;
    if (selLine) { selLine.remove(); selLine = null; }
    if (state.overlay !== "none" && map) drawOverlay(a); // re-fade around the new selection
    if (!sel || se.idx[sel.i1] - se.idx[sel.i0] < 1) { bar.hidden = true; bar.innerHTML = ""; return; }
    const w = { start: se.idx[sel.i0], end: se.idx[sel.i1] };
    const dist = se.distance_m[sel.i1] - se.distance_m[sel.i0];
    const dur = se.time_s ? se.time_s[sel.i1] - se.time_s[sel.i0] : null;
    const from = se.time_s ? fmtDur(se.time_s[sel.i0]) : `${fmtDist(se.distance_m[sel.i0])} ${u().distL}`;
    const to = se.time_s ? fmtDur(se.time_s[sel.i1]) : `${fmtDist(se.distance_m[sel.i1])} ${u().distL}`;
    bar.hidden = false;
    const lbl = selectionLabel(a);
    bar.innerHTML = `<div><strong>${esc(lbl.title)}</strong> ${fmtDist(dist)} ${u().distL}${dur != null ? ` · ${fmtDur(dur)}` : ""}
        <span class="muted">(${from} → ${to})</span></div>
      <div class="trim-actions">
        <a class="btn small primary" href="${activityHash(a.id, w)}">View ${lbl.noun}</a>
        <span class="export-group"><span class="muted">Cut to new file</span>${exportLinks(a, w)}</span>
        <button class="btn small" id="sel-save">Save as activity</button>
        ${se.lat && !state.effort ? `<button class="btn small" id="sel-segment" title="Make this stretch a segment and find it in all activities">Create segment</button>` : ""}
        <button class="btn small ghost" id="sel-clear" title="Clear selection (Esc)">Clear</button>
      </div>`;
    $("#sel-save").addEventListener("click", () => saveClip(a, w, lbl.name));
    $("#sel-segment")?.addEventListener("click", () => createSegment(a, w));
    $("#sel-clear").addEventListener("click", () => { state.sel = null; renderSelection(a); });
    if (map && se.lat) {
      const pts = [];
      for (let k = sel.i0; k <= sel.i1; k++) if (se.lat[k] != null && se.lon[k] != null) pts.push([se.lat[k], se.lon[k]]);
      if (pts.length > 1) selLine = L.polyline(pts, { color: css("--sel-edge"), weight: 6, opacity: 0.95, interactive: false }).addTo(map);
      raiseMapMarks();
    }
  }

  function nearestIdx(xs, v) {
    let lo = 0, hi = xs.length - 1;
    if (v <= xs[lo]) return lo;
    if (v >= xs[hi]) return hi;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] < v) lo = mid; else hi = mid; }
    return v - xs[lo] < xs[hi] - v ? lo : hi;
  }

  function setHover(i, a, xs, xMode) {
    state.hoverIdx = i;
    const synced = state.charts.filter((c) => c.$synced);
    synced.forEach((c) => c.draw());
    const ro = $("#readout");
    if (i == null) {
      ro.innerHTML = `<span class="muted">Hover a chart to inspect values.</span>`;
      if (hoverMarker) hoverMarker.setStyle({ opacity: 0, fillOpacity: 0 });
      return;
    }
    const se = a.series;
    const parts = [];
    parts.push(`<span><b>${fmtDist(se.distance_m[i])}</b> ${u().distL}</span>`);
    if (se.time_s) parts.push(`<span><b>${fmtDur(se.time_s[i])}</b> elapsed</span>`);
    synced.forEach((c) => {
      const v = c.$def.y[i];
      parts.push(`<span><span class="sw" style="background:var(${c.$def.color})"></span>${v == null ? "–" : `<b>${esc(c.$def.fmt(v))}</b>`}</span>`);
    });
    ro.innerHTML = parts.join("");
    if (hoverMarker && se.lat && se.lat[i] != null) {
      hoverMarker.setLatLng([se.lat[i], se.lon[i]]).setStyle({ opacity: 1, fillOpacity: 1 });
    }
  }

  // ------------------------------------------------------------------ laps view
  function renderLaps(a, r) {
    const pace = isPace(a.sport);
    const laps = r.laps, st = r.lap_time_stats;
    const withUnit = (v, f, unit) => (v == null ? "–" : `${f(v)}${unit ? " " + unit : ""}`);
    const speedTxt = (ms) => (ms == null ? "–" : pace ? `${fmtPace(ms)} /${u().distL}` : `${fmtSpeed(ms)} ${u().speedL}`);
    const signed = (s) => (s == null ? "–" : `${s > 0 ? "+" : s < 0 ? "−" : "±"}${fmtNum(Math.abs(s), 1)} s`);

    if (st) {
      $("#lap-stats").textContent = `${laps.length} × ${fmtDist(r.lap_distance_m)} ${u().distL} · avg ${fmtDur(st.mean_s)} · spread ±${fmtNum(st.stdev_s, 1)} s`;
    }

    // "Average lap": mean of the per-lap values; speed from summed distance / summed moving time.
    const mean = (k) => { const v = laps.map((l) => l[k]).filter((x) => x != null); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
    const avgLap = Object.fromEntries(["distance_m", "elapsed_s", "moving_s", "elev_gain_m", "avg_hr", "max_hr", "avg_power", "avg_cadence"].map((k) => [k, mean(k)]));
    const sumMov = laps.reduce((s, l) => s + (l.moving_s || 0), 0);
    avgLap.avg_speed_ms = sumMov ? laps.reduce((s, l) => s + (l.distance_m || 0), 0) / sumMov : null;
    const fastest = st ? laps[st.best_index - 1] : null;

    const rows = [
      ["Distance", (c) => withUnit(c.distance_m, (v) => fmtDist(v), u().distL), "distance_m"],
      ["Time", (c) => fmtDur(c.elapsed_s), "elapsed_s"],
      ["Moving time", (c) => fmtDur(c.moving_s), "moving_s"],
      [pace ? "Avg pace (moving)" : "Avg speed (moving)", (c) => speedTxt(c.avg_speed_ms), "avg_speed_ms"],
      ["Elevation gain", (c) => withUnit(c.elev_gain_m, fmtEle, u().eleL), "elev_gain_m"],
      ["Avg heart rate", (c) => withUnit(c.avg_hr, (v) => fmtNum(v, 0), "bpm"), "avg_hr"],
      ["Max heart rate", (c) => withUnit(c.max_hr, (v) => fmtNum(v, 0), "bpm"), "max_hr"],
      ["Avg power", (c) => withUnit(c.avg_power, (v) => fmtNum(v, 0), "W"), "avg_power"],
      ["Avg cadence", (c) => withUnit(c.avg_cadence, (v) => fmtNum(v, 0), cadenceUnit(a.sport)), "avg_cadence"],
    ].filter(([, , k]) => r.whole[k] != null || r.section[k] != null);

    const renderCompare = () => {
      const sel = state.lap ? laps[state.lap - 1] : null;
      const cols = [
        ["Whole activity", r.whole], ["All laps", r.section], ["Average lap", avgLap],
        [fastest ? `Fastest (lap ${fastest.index})` : "Fastest lap", fastest],
        [sel ? `Lap ${sel.index}` : "Selected lap", sel],
      ];
      $("#lap-compare").innerHTML = `<div class="table-scroll"><table class="cmp"><thead><tr><th></th>${cols.map(([h], i) => `<th class="${i === 4 ? "sel-col" : ""}">${esc(h)}</th>`).join("")}</tr></thead><tbody>
        ${rows.map(([label, f]) => `<tr><th scope="row">${esc(label)}</th>${cols.map(([, c], i) => `<td class="${i === 4 ? "sel-col" : ""}">${c ? f(c) : '<span class="muted">–</span>'}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>${state.lap ? "" : `<p class="muted small-note">Select a lap in the list or the chart to compare it.</p>`}`;
    };

    const has = (k) => laps.some((l) => l[k] != null);
    const cols = [
      ["Lap", (l) => `${l.index}`],
      ["Time", (l) => fmtDur(l.elapsed_s)],
      ["Δ avg", (l) => signed(l.delta_s)],
      [pace ? "Pace" : "Speed", (l) => speedTxt(l.lap_speed_ms)],
      ["Distance", (l) => withUnit(l.distance_m, (v) => fmtDist(v), u().distL)],
      ...(has("avg_hr") ? [["Avg HR", (l) => fmtNum(l.avg_hr, 0)], ["Max HR", (l) => fmtNum(l.max_hr, 0)]] : []),
      ...(has("avg_power") ? [["Power", (l) => fmtNum(l.avg_power, 0)]] : []),
      ...(has("avg_cadence") ? [["Cadence", (l) => fmtNum(l.avg_cadence, 0)]] : []),
      ...(has("elev_gain_m") ? [["Elev +", (l) => fmtEle(l.elev_gain_m)]] : []),
      ["", (l) => (st && l.index === st.best_index ? '<span class="badge">fastest</span>' : st && l.index === st.worst_index ? '<span class="badge muted">slowest</span>' : "")],
    ];
    const list = $("#lap-list");
    list.innerHTML = `<table><thead><tr>${cols.map(([h]) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>
      ${laps.map((l) => `<tr data-lap="${l.index}" tabindex="0" aria-selected="false">${cols.map(([, f]) => `<td>${f(l)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    list.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-lap]"); if (tr) selectLap(Number(tr.dataset.lap)); });
    list.addEventListener("keydown", (e) => {
      const tr = e.target.closest("tr[data-lap]");
      if (!tr) return;
      const k = Number(tr.dataset.lap);
      const next = e.key === "ArrowDown" ? k + 1 : e.key === "ArrowUp" ? k - 1 : (e.key === "Enter" || e.key === " ") ? k : null;
      if (next == null || next < 1 || next > laps.length) return;
      e.preventDefault();
      selectLap(next);
      list.querySelector(`tr[data-lap="${next}"]`).focus();
    });

    // Lap-time chart: dots (not bars: a zero baseline would hide the differences) + average line.
    const ink = css("--m-speed"), selC = css("--sel-edge");
    const avgLine = {
      id: "avgLine",
      afterDatasetsDraw(chart) {
        if (!st) return;
        const { ctx, chartArea, scales } = chart;
        const y = scales.y.getPixelForValue(st.mean_s);
        ctx.save();
        ctx.strokeStyle = css("--text-muted"); ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(chartArea.left, y); ctx.lineTo(chartArea.right, y); ctx.stroke();
        ctx.setLineDash([]); ctx.fillStyle = css("--text-muted"); ctx.font = "11px system-ui, sans-serif"; ctx.textAlign = "right";
        ctx.fillText(`avg ${fmtDur(st.mean_s)}`, chartArea.right, y - 4);
        ctx.restore();
      },
    };
    const lapChart = new Chart($("#lap-chart"), {
      type: "line",
      data: { labels: laps.map((l) => l.index), datasets: [{ data: laps.map((l) => l.elapsed_s), borderColor: ink, borderWidth: 2, tension: 0,
        pointRadius: 4, pointHoverRadius: 7, pointBackgroundColor: ink, pointBorderColor: css("--surface-1"), pointBorderWidth: 2, pointHitRadius: 12 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, tooltip: tooltipStyle({ callbacks: {
          title: (it) => `Lap ${laps[it[0].dataIndex].index}`,
          label: (it) => { const l = laps[it.dataIndex]; return [`${fmtDur(l.elapsed_s)} (${signed(l.delta_s)} vs avg)`, speedTxt(l.lap_speed_ms), ...(l.avg_hr ? [`${fmtNum(l.avg_hr, 0)} bpm avg`] : [])]; },
        } }) },
        scales: {
          x: { ...baseScales("Lap").x, type: "category", grid: { display: false } },
          y: { ...baseScales().y, grace: "10%", ticks: { ...baseScales().y.ticks, callback: (v) => fmtDur(v) } },
        },
        onHover: (evt, els) => { evt.native.target.style.cursor = els.length ? "pointer" : "default"; },
        onClick: (evt) => {
          const el = lapChart.getElementsAtEventForMode(evt, "index", { intersect: false }, false)[0];
          if (el) selectLap(laps[el.index].index);
        },
      },
      plugins: [avgLine],
    });
    state.charts.push(lapChart);

    const refresh = () => {
      list.querySelectorAll("tr[data-lap]").forEach((tr) => tr.setAttribute("aria-selected", String(Number(tr.dataset.lap) === state.lap)));
      const ds = lapChart.data.datasets[0];
      ds.pointBackgroundColor = laps.map((l) => (l.index === state.lap ? selC : ink));
      ds.pointRadius = laps.map((l) => (l.index === state.lap ? 7 : 4));
      lapChart.update("none");
      renderCompare();
    };
    function selectLap(k) {
      if (k === state.lap) { state.sel = null; renderSelection(a); return; } // click again to deselect
      const lap = laps[k - 1];
      const idx = a.series.idx;
      state.sel = { i0: nearestIdx(idx, lap.start), i1: nearestIdx(idx, lap.end) };
      state.lap = k; state.lapRange = { ...state.sel };
      renderSelection(a);
      const row = list.querySelector(`tr[data-lap="${k}"]`);
      row?.scrollIntoView({ block: "nearest" });
    }
    state.selListeners.push(refresh);
    refresh();
  }

  function zonesHtml(zones) {
    const total = zones.reduce((s, z) => s + z.time_s, 0) || 1;
    const max = Math.max(...zones.map((z) => z.time_s), 1);
    return zones.map((z) => `<div class="zone-row" title="${fmtDur(z.time_s)} in zone ${z.zone}">
      <div class="lbl">Z${z.zone}<small>${z.max_bpm ? `${z.min_bpm}–${z.max_bpm}` : `≥ ${z.min_bpm}`} bpm</small></div>
      <div class="zone-track"><div class="zone-fill" style="width:${(z.time_s / max) * 100}%;background:var(--seq-${z.zone})"></div></div>
      <div class="val">${fmtDur(z.time_s)} · ${Math.round((z.time_s / total) * 100)}%</div></div>`).join("");
  }

  function splitsHtml(splits, pace) {
    const speeds = splits.map((s) => s.speed_ms || 0);
    const max = Math.max(...speeds, 0.001);
    const hasHr = splits.some((s) => s.avg_hr != null), hasPw = splits.some((s) => s.avg_power != null);
    return `<div class="table-scroll"><table><thead><tr><th>${u().split}</th><th>${pace ? "Pace" : "Speed"}</th><th class="bar-cell"></th><th>Elev +</th>${hasHr ? "<th>HR</th>" : ""}${hasPw ? "<th>Power</th>" : ""}</tr></thead><tbody>
      ${splits.map((s) => `<tr><td>${s.distance_m < (u().dist * 0.99) ? fmtDist(s.distance_m) : s.index}</td>
        <td>${pace ? fmtPace(s.speed_ms) : fmtSpeed(s.speed_ms)}</td>
        <td class="bar-cell"><div class="inline-bar" style="width:${((s.speed_ms || 0) / max) * 100}%"></div></td>
        <td>${fmtEle(s.elev_gain_m)}</td>${hasHr ? `<td>${fmtNum(s.avg_hr, 0)}</td>` : ""}${hasPw ? `<td>${fmtNum(s.avg_power, 0)}</td>` : ""}</tr>`).join("")}
      </tbody></table></div>`;
  }

  function effortsHtml(efforts, pace) {
    return `<div class="table-scroll"><table><thead><tr><th>Distance</th><th>Time</th><th>${pace ? "Pace" : "Speed"}</th><th>Starts at</th></tr></thead><tbody>
      ${efforts.map((e) => { const ms = e.distance_m / e.time_s; return `<tr><td>${effortLabel(e.distance_m)}</td><td>${fmtDur(e.time_s)}</td>
        <td>${pace ? `${fmtPace(ms)} /${u().distL}` : `${fmtSpeed(ms)} ${u().speedL}`}</td><td>${fmtDur(e.start_offset_s)}</td></tr>`; }).join("")}
      </tbody></table></div>`;
  }

  // ------------------------------------------------------------------ segments pages
  async function loadSegments() {
    state.segments = await api("/api/segments");
    renderSegList();
  }

  function renderSegList() {
    const items = state.segments;
    $("#seg-count").textContent = `${items.length} segment${items.length === 1 ? "" : "s"}`;
    const ul = $("#segment-list");
    if (!items.length) { ul.innerHTML = `<li class="empty">No segments yet.</li>`; return; }
    ul.innerHTML = items.map((s) => {
      const bits = [`${fmtDist(s.distance_m)} ${u().distL}`, `${s.effort_count} effort${s.effort_count === 1 ? "" : "s"}`];
      if (s.best_s != null) bits.push(`best ${fmtDur(s.best_s)}`);
      return `<li><a href="#/segment/${s.id}" class="${s.id === state.currentSegment ? "active" : ""}">
        <span class="icon" aria-hidden="true">${sportIcon(s.sport)}</span>
        <span class="name">${esc(s.name)}</span><span class="meta">${esc(bits.join(" · "))}</span></a></li>`;
    }).join("");
  }

  // Nav highlight; the sidebar shows segments on segment pages and activities everywhere else.
  /** Narrow screens: scroll the navigation bar so the current tab is visible. */
  function revealTab() {
    const nav = $(".main-nav"), on = nav?.querySelector("a.active");
    if (!nav || !on || nav.scrollWidth <= nav.clientWidth) return;
    const r = on.getBoundingClientRect(), nr = nav.getBoundingClientRect();
    nav.scrollLeft += r.left - nr.left - (nr.width - r.width) / 2;
  }

  // The sticky sidebar sits below the top bar, whose height depends on wrapping.
  (() => {
    const bar = document.querySelector(".topbar");
    if (!bar || typeof ResizeObserver === "undefined") return;
    const set = () => document.documentElement.style.setProperty("--topbar-h", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
    new ResizeObserver(set).observe(bar);
    set();
  })();

  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll("[data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    revealTab();
    document.fonts?.ready.then(revealTab);  // tab widths change once the web font is in
    $("#tab-activities").hidden = tab === "segments";
    $("#tab-segments").hidden = tab !== "segments";
  }

  function leaveActivity() {
    destroyCharts(); endPick();
    disposeMap();
    state.current = null; state.sel = null; state.selListeners = [];
  }

  async function renderSegmentsPage() {
    const token = newRender();
    leaveActivity(); state.currentSegment = null;
    await loadSegments(); renderList();
    if (stale(token)) return;
    const segs = state.segments;
    main.innerHTML = `
      <div class="page-head"><div><h1>Segments</h1>
        <div class="sub">Stretches of track compared across all your activities</div></div></div>
      ${segs.length ? `<div class="card"><div class="table-scroll"><table class="seg-overview"><thead><tr><th>Segment</th><th>Sport</th><th>Distance</th><th>Elev +</th><th>Efforts</th><th>Activities</th><th>Best time</th></tr></thead><tbody>
        ${segs.map((s) => `<tr><td class="name-cell"><a href="#/segment/${s.id}">${esc(s.name)}</a></td><td>${sportIcon(s.sport)} ${esc(sportName(s.sport))}</td>
          <td>${fmtDist(s.distance_m)} ${u().distL}</td><td>${fmtEle(s.elev_gain_m)} ${u().eleL}</td><td>${s.effort_count}</td><td>${s.activity_count}</td><td>${fmtDur(s.best_s)}</td></tr>`).join("")}
        </tbody></table></div></div>` : ""}
      <div class="card how-to"><h2>Creating a segment</h2>
        <ol>
          <li>Open an activity.</li>
          <li>Select the stretch: drag across any chart, click <b>✚ Pick section</b> on the map and click its start and end on the track, or pick a lap in the laps view.</li>
          <li>Click <b>Create segment</b> in the selection bar.</li>
        </ol>
        <p class="muted">Every activity, stored or uploaded later, that follows the same line from the segment start to its end gets an effort on it, so you can compare times. Several passes in one activity (laps) count as separate efforts.</p></div>`;
  }

  async function renderSegment(id) {
    const token = newRender();
    leaveActivity(); renderList();
    main.innerHTML = `<div class="spinner">Loading segment…</div>`;
    let s;
    try { s = await api(`/api/segments/${id}`); }
    catch (e) { if (stale(token)) return; main.innerHTML = `<div class="welcome"><h1>Segment not found</h1><p class="muted">${esc(e.message)}</p><a href="#/segments">All segments</a></div>`; return; }
    if (stale(token)) return;
    state.currentSegment = s.id;
    renderSegList();
    const pace = isPace(s.sport);
    const speedTxt = (ms) => (ms == null ? "–" : pace ? `${fmtPace(ms)} /${u().distL}` : `${fmtSpeed(ms)} ${u().speedL}`);
    const best = s.efforts[0];
    const effortHref = (e) => `#/activity/${e.activity_id}?effort=${e.id}`;
    const has = (k) => s.efforts.some((e) => e[k] != null);
    main.innerHTML = `
      <div class="page-head">
        <div style="flex:1;min-width:240px">
          <input class="title-input" id="seg-name" value="${esc(s.name)}" aria-label="Segment name" maxlength="200">
          <div class="sub">${sportIcon(s.sport)} Segment · ${esc(sportName(s.sport))} · ${s.source_activity_id ? `cut from <a href="#/activity/${s.source_activity_id}">this activity</a>` : "source activity deleted"}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button class="btn" id="seg-rescan" title="Search all stored activities again">Rescan activities</button>
          <button class="btn danger" id="seg-del">Delete</button>
        </div>
      </div>
      <div class="tiles">
        ${tile("Distance", fmtDist(s.distance_m), u().distL)}
        ${s.elev_gain_m != null ? tile("Elevation gain", fmtEle(s.elev_gain_m), u().eleL) : ""}
        ${tile("Efforts", fmtNum(s.efforts.length, 0))}
        ${tile("Activities", fmtNum(s.activities.length, 0))}
        ${best ? tile("Best time", fmtDur(best.elapsed_s)) : ""}
        ${best?.speed_ms ? (pace ? tile("Best pace", fmtPace(best.speed_ms), "/" + u().distL) : tile("Best speed", fmtSpeed(best.speed_ms), u().speedL)) : ""}
      </div>
      <div class="grid two">
        <div class="card"><div id="map" class="seg-map"></div></div>
        <div class="card" id="seg-efforts"><h2><span>Best efforts</span><span class="muted" style="font-weight:400">fastest first</span></h2>
          ${s.efforts.length ? `<div class="table-scroll lap-list"><table><thead><tr><th>#</th><th>Time</th><th>${pace ? "Pace" : "Speed"}</th>${has("avg_hr") ? "<th>Avg HR</th>" : ""}${has("avg_power") ? "<th>Power</th>" : ""}<th>Date</th><th>Activity</th></tr></thead><tbody>
            ${s.efforts.map((e) => `<tr><td>${e.rank === 1 ? "🏆" : e.rank}</td><td><a href="${effortHref(e)}" title="Show this effort in the activity">${fmtDur(e.elapsed_s)}</a></td><td>${speedTxt(e.speed_ms)}</td>
              ${has("avg_hr") ? `<td>${fmtNum(e.avg_hr, 0)}</td>` : ""}${has("avg_power") ? `<td>${fmtNum(e.avg_power, 0)}</td>` : ""}
              <td>${esc(fmtDay(e.start_time || e.activity_start))}</td><td class="name-cell"><a href="${effortHref(e)}">${esc(e.activity_name)}</a></td></tr>`).join("")}
            </tbody></table></div>` : `<p class="muted">No efforts yet. Activities that follow this line will appear here.</p>`}
        </div>
      </div>
      <div class="card"><h2><span>Activities with this segment</span><span class="muted" style="font-weight:400">newest first</span></h2>
        ${s.activities.length ? `<div class="table-scroll"><table><thead><tr><th>Date</th><th>Activity</th><th>Sport</th><th>Efforts</th><th>Best time</th><th>Rank</th></tr></thead><tbody>
          ${s.activities.map((x) => `<tr><td>${esc(fmtDay(x.start_time))}</td><td class="name-cell"><a href="#/activity/${x.activity_id}">${esc(x.name)}</a></td>
            <td>${sportIcon(x.sport)} ${esc(sportName(x.sport))}</td><td>${x.efforts}</td>
            <td><a href="${effortHref(x.best)}" title="Show the best effort in the activity">${fmtDur(x.best.elapsed_s)}</a></td><td>${rankBadge(x.best)}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="muted">None yet.</p>`}
      </div>`;

    map = L.map("map", { scrollWheelZoom: false, preferCanvas: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    L.polyline(s.points, { color: css("--map-casing"), weight: 8, interactive: false }).addTo(map);
    const line = L.polyline(s.points, { color: css("--sel-edge"), weight: 5, interactive: false }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [24, 24] });
    const dot = (ll, color, label) => L.circleMarker(ll, { radius: 7, color: css("--surface-1"), weight: 2, fillColor: color, fillOpacity: 1 }).addTo(map).bindTooltip(label);
    dot(s.points[0], css("--m-elevation"), "Segment start");
    dot(s.points.at(-1), css("--text-primary"), "Segment end");

    $("#seg-name").addEventListener("change", async (e) => {
      const name = e.target.value.trim();
      if (!name) { e.target.value = s.name; return; }
      await api(`/api/segments/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      s.name = name; toast("Renamed"); loadSegments();
    });
    $("#seg-name").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
    $("#seg-rescan").addEventListener("click", async () => {
      toast("Searching all activities…");
      const r = await api(`/api/segments/${s.id}/rescan`, { method: "POST" });
      toast(`${r.efforts.length} effort${r.efforts.length === 1 ? "" : "s"} found`);
      await loadSegments(); renderSegment(s.id);
    });
    $("#seg-del").addEventListener("click", async () => {
      if (!confirm(`Delete segment “${s.name}”? Its efforts are removed too; activities are not touched.`)) return;
      await api(`/api/segments/${s.id}`, { method: "DELETE" });
      toast("Segment deleted"); await loadSegments(); location.hash = "#/segments";
    });
  }

  // ------------------------------------------------------------------ tags (core)
  async function loadTags() {
    state.tags = await api("/api/tags");
    renderTagFilter();
  }

  function renderTagFilter() {
    const sel = $("#tag-filter");
    if (!sel) return;
    if (!state.tags.some((t) => t.tag === state.tagFilter)) state.tagFilter = "";
    sel.hidden = !state.tags.length;
    sel.innerHTML = `<option value="">All tags</option>` +
      state.tags.map((t) => `<option value="${esc(t.tag)}" ${t.tag === state.tagFilter ? "selected" : ""}>#${esc(t.tag)} (${t.count})</option>`).join("");
  }

  function renderTagEditor(a) {
    const row = $("#tag-row");
    if (!row) return;
    const draw = (focus) => {
      row.innerHTML = a.tags.map((t) => `<span class="tag">#${esc(t)}<button type="button" data-rm="${esc(t)}" aria-label="Remove tag ${esc(t)}" title="Remove">×</button></span>`).join("") +
        `<input id="tag-input" class="tag-input" list="tag-suggest" placeholder="+ add tag" aria-label="Add a tag" maxlength="32">
         <datalist id="tag-suggest">${state.tags.filter((t) => !a.tags.includes(t.tag)).map((t) => `<option value="${esc(t.tag)}">`).join("")}</datalist>`;
      if (focus) $("#tag-input").focus();
    };
    const save = async (tags, focus) => {
      try {
        a.tags = (await api(`/api/activities/${a.id}/tags`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags }) })).tags;
        await Promise.all([loadTags(), loadList()]);
        draw(focus);
      } catch (e) { toast("Could not save tags: " + e.message); }
    };
    row.addEventListener("click", (ev) => { const b = ev.target.closest("[data-rm]"); if (b) save(a.tags.filter((t) => t !== b.dataset.rm)); });
    row.addEventListener("change", (ev) => { // Enter, a datalist pick, or leaving the field
      const v = ev.target.id === "tag-input" ? ev.target.value.trim() : "";
      if (v) save([...a.tags, v], true);
    });
    draw(false);
  }

  // ------------------------------------------------------------------ module SDK (window.fitpush)
  // The only API frontend modules may use; documented in docs/SDK.md. Keep it stable.
  const modulePages = new Map(); // page id -> {module, id, label, icon, render}
  const moduleCards = [];        // {module, title, order, render}
  let pageCleanups = [];
  function runCleanups() {
    for (const f of pageCleanups.splice(0)) { try { f(); } catch (e) { console.error(e); } }
  }
  const moduleOf = (def) => def.module || /\/m\/([^/]+)\//.exec(document.currentScript?.src || "")?.[1] || "unknown";

  function showModuleError(el, module, err) {
    console.error(`[module ${module}]`, err);
    el.innerHTML = `<div class="module-error" role="alert">⚠ The <b>${esc(module)}</b> module failed: ${esc(err?.message || err)}.
      The rest of the app is unaffected. <a href="#/modules/${esc(module)}">Module info</a></div>`;
  }

  const sdk = Object.freeze({
    version: "1.0",
    /** A page with its own sidebar tab, routed at #/m/<id>. render(el, ctx) may be async. */
    registerPage(def) {
      const module = moduleOf(def), id = def.id || module;
      modulePages.set(id, { module, id, label: def.label || id, icon: def.icon || "🧩", render: def.render });
      renderNav();
    },
    /** A card on every activity page. render(el, ctx) returns false to hide the card for that activity.
     *  placement "header": a compact line under the title and tags instead of a card below the charts. */
    registerActivityCard(def) {
      moduleCards.push({
        module: moduleOf(def), title: def.title, order: def.order ?? 100, render: def.render,
        placement: def.placement === "header" ? "header" : "card",
      });
      moduleCards.sort((x, y) => x.order - y.order);
    },
    api, toast, esc, css, askName,
    navigate: (hash) => { location.hash = hash; },
    fmt: Object.freeze({ num: fmtNum, dist: fmtDist, ele: fmtEle, dur: fmtDur, pace: fmtPace, speed: fmtSpeed, date: fmtDate, day: fmtDay, units: () => ({ ...u() }) }),
    sports: Object.freeze({ list: () => [...SPORTS.values()], get: sportInfo, icon: sportIcon, name: sportName, isPace }),
    tags: () => state.tags.map((t) => ({ ...t })),
    /** Leaflet map with the standard tiles; removed automatically when the page changes. */
    map(el, opts = {}) {
      const m = L.map(el, { preferCanvas: true, scrollWheelZoom: true, ...opts });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(m);
      pageCleanups.push(() => { m.off(); m.stop(); m.remove(); });
      return m;
    },
    /** Chart.js chart with the app's axis/tooltip styling helpers; destroyed when the page changes. */
    chart(canvas, config) { const c = new Chart(canvas, config); pageCleanups.push(() => c.destroy()); return c; },
    chartStyle: Object.freeze({ scales: baseScales, tooltip: tooltipStyle }),
  });
  window.fitpush = sdk;

  async function loadModules() {
    try { state.modules = await api("/api/modules"); } catch { state.modules = []; }
    const load = (tag, attrs) => new Promise((resolve) => {
      const el = Object.assign(document.createElement(tag), attrs);
      el.onload = () => resolve(true);
      el.onerror = () => resolve(false);
      document.head.append(el);
    });
    await Promise.all(state.modules.filter((m) => m.css).map((m) => load("link", { rel: "stylesheet", href: `/m/${m.id}/frontend.css` })));
    for (const m of state.modules.filter((x) => x.frontend)) { // one by one, in a stable order
      if (!(await load("script", { src: `/m/${m.id}/frontend.js` }))) {
        m.status = "error"; m.errors.push("frontend.js failed to load");
      }
    }
    renderNav();
  }

  function renderNav() {
    const nav = $(".main-nav");
    if (!nav) return;
    nav.innerHTML = `<a href="#/" data-tab="activities">Activities</a><a href="#/segments" data-tab="segments">Segments</a>` +
      [...modulePages.values()].map((p) => `<a href="#/m/${esc(p.id)}" data-tab="page:${esc(p.id)}" title="${esc(p.label)} (module: ${esc(p.module)})">${p.icon ? `<span class="nav-icon" aria-hidden="true">${esc(p.icon)}</span>` : ""}${esc(p.label)}</a>`).join("");
    setTab(state.tab || "activities");
  }

  async function renderModulePage(pageId, query) {
    const token = newRender();
    leaveActivity(); renderList();
    const page = modulePages.get(pageId);
    if (!page) {
      main.innerHTML = `<div class="welcome"><h1>Page not available</h1><p class="muted">The module providing “${esc(pageId)}” is not loaded (the app may be running core-only).</p><a href="#/modules">Modules</a></div>`;
      return;
    }
    main.innerHTML = `<div class="module-page" data-module="${esc(page.module)}"></div>`;
    const el = main.firstElementChild;
    const ctx = {
      params: new URLSearchParams(query || ""),
      /** Store page state in the URL (bookmarkable) without re-rendering. */
      setParams(obj) {
        const q = new URLSearchParams(Object.entries(obj).filter(([, v]) => v != null && v !== ""));
        history.replaceState(null, "", `#/m/${pageId}${q.toString() ? "?" + q : ""}`);
      },
      onCleanup: (f) => pageCleanups.push(f),
      isStale: () => stale(token),
      sdk,
    };
    try { await page.render(el, ctx); } catch (e) { if (!stale(token)) showModuleError(el, page.module, e); }
  }

  function renderModuleCards(a) {
    const box = $("#module-cards"), head = $("#module-head");
    if (!box) return;
    for (const card of moduleCards) {
      const el = document.createElement("div");
      el.dataset.module = card.module;
      if (card.placement === "header" && head) {
        el.className = "module-head-item";
        el.innerHTML = `<span class="module-head-label" title="${esc(card.title)} (module: ${esc(card.module)})">${esc(card.title)}</span><div class="module-body"></div>`;
        head.append(el);
      } else {
        el.className = "card module-card";
        el.innerHTML = `<h2><span>${esc(card.title)}</span><span class="muted module-badge" title="Provided by a module">${esc(card.module)}</span></h2><div class="module-body"></div>`;
        box.append(el);
      }
      const ctx = {
        activity: a,
        /** Highlight absolute point indices start..end on charts and map, labelled in the selection bar. */
        select: (start, end, label) => selectNamed(a, start, end, label),
        onCleanup: (f) => pageCleanups.push(f),
        sdk,
      };
      const fail = (e) => showModuleError(el.querySelector(".module-body"), card.module, e);
      try {
        const r = card.render(el.querySelector(".module-body"), ctx);
        if (r === false) el.remove();
        else if (r && typeof r.then === "function") r.then((v) => { if (v === false) el.remove(); }, fail);
      } catch (e) { fail(e); }
    }
  }

  function selectNamed(a, start, end, label) {
    const idx = a.series.idx;
    state.sel = { i0: nearestIdx(idx, start), i1: nearestIdx(idx, end) };
    state.lap = null; state.lapRange = null; state.effort = null;
    state.named = { name: String(label || "Selection"), range: { ...state.sel } };
    renderSelection(a);
  }

  // ------------------------------------------------------------------ modules page (+ docs)
  // Minimal, safe Markdown -> HTML for module READMEs and manuals (text is escaped first).
  function markdown(md, { dropTitle = false } = {}) {
    if (dropTitle) md = md.replace(/^\s*#\s+[^\n]*\n/, ""); // the page already shows the title
    const inline = (s) => esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|#)[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = [];
    const lines = md.replace(/\r\n/g, "\n").split("\n");
    for (let i = 0; i < lines.length;) {
      const l = lines[i];
      if (/^```/.test(l)) {
        const code = [];
        for (i++; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
        out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); i++; continue;
      }
      const h = /^(#{1,4})\s+(.*)$/.exec(l);
      if (h) { const n = Math.min(4, h[1].length + 1); out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue; }
      if (/^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l)) {
        const ordered = /^\s*\d+\./.test(l), items = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
          let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, "");
          // indented lines that are not a new item continue the current one
          for (; i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i]); i++) item += " " + lines[i].trim();
          items.push(`<li>${inline(item)}</li>`);
        }
        out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`); continue;
      }
      if (/^\|.*\|\s*$/.test(l)) {
        const rows = [];
        for (; i < lines.length && /^\|.*\|\s*$/.test(lines[i]); i++) if (!/^\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|").map((c) => c.trim()));
        out.push(`<div class="table-scroll"><table class="md-table">${rows.map((r, k) => `<tr>${r.map((c) => (k ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`)).join("")}</tr>`).join("")}</table></div>`); continue;
      }
      if (/^>\s?/.test(l)) {
        const q = [];
        for (; i < lines.length && /^>\s?/.test(lines[i]); i++) q.push(inline(lines[i].replace(/^>\s?/, "")));
        out.push(`<blockquote>${q.join("<br>")}</blockquote>`); continue;
      }
      if (!l.trim()) { i++; continue; }
      const para = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|\||>)/.test(lines[i]); i++) para.push(inline(lines[i]));
      out.push(`<p>${para.join(" ")}</p>`);
    }
    return out.join("\n");
  }

  async function renderModulesPage(moduleId) {
    const token = newRender();
    leaveActivity(); renderList();
    const mods = state.modules || [];
    const badge = (m) => `<span class="badge status-${esc(m.status)}">${esc(m.status)}</span>`;
    const owner = (m) => (m.owner?.github ? `<a href="https://github.com/${esc(m.owner.github)}" target="_blank" rel="noopener">@${esc(m.owner.github)}</a>` : "–");
    if (!moduleId) {
      main.innerHTML = `<div class="page-head"><div><h1>Modules</h1>
          <div class="sub">Optional features in <code>modules/</code>. Each has an owner, an intent and a manual.</div></div></div>
        ${mods.length ? `<div class="grid two">${mods.map((m) => `<div class="card module-tile">
          <h2><span>${esc(m.name)} <span class="muted" style="font-weight:400">v${esc(m.version || "?")}</span></span>${badge(m)}</h2>
          <p>${esc(m.summary || "")}</p>
          <p class="muted">Owner ${owner(m)}${m.maintainers?.length ? ` · maintainers ${m.maintainers.map((x) => `@${esc(x)}`).join(", ")}` : ""} · provides ${esc((m.provides || []).join(", "))}</p>
          ${Object.keys(m.services || {}).length ? `<p class="muted">Services: ${Object.entries(m.services).map(([k, v]) => `<code>${esc(k)}</code> ${esc(v)}`).join(", ")}</p>` : ""}
          ${Object.keys(m.uses || {}).length ? `<p class="muted">Uses: ${Object.entries(m.uses).flatMap(([mid, s]) => Object.entries(s).map(([k, v]) => `<code>${esc(mid)}.${esc(k)}</code> ${esc(v)}.x`)).join(", ")}</p>` : ""}
          ${m.errors?.length ? `<div class="module-error">${m.errors.map(esc).join("<br>")}</div>` : ""}
          <a class="btn small" href="#/modules/${esc(m.id)}">Manual &amp; intent</a></div>`).join("")}</div>`
          : `<div class="card"><p class="muted">No modules installed. See <code>modules/RULES.md</code> to create one.</p></div>`}
        <p class="muted small-note">Run with <code>python -m app --core-only</code> to start without modules.</p>`;
      return;
    }
    const m = mods.find((x) => x.id === moduleId);
    main.innerHTML = `<div class="spinner">Loading…</div>`;
    const [manual, readme] = await Promise.all(["manual", "readme"].map((d) => api.text(`/api/modules/${moduleId}/docs/${d}`).catch(() => null)));
    if (stale(token)) return;
    main.innerHTML = `<div class="page-head"><div><h1>${esc(m?.name || moduleId)}</h1>
        <div class="sub">${m ? `${badge(m)} v${esc(m.version || "?")} · owner ${owner(m)}` : "not installed"} · <a href="#/modules">All modules</a></div></div></div>
      <div class="grid two docs-grid">
        <div class="card md"><h2><span>Manual</span></h2>${manual ? markdown(manual, { dropTitle: true }) : '<p class="muted">No manual.</p>'}</div>
        <div class="card md"><h2><span>Intent</span><span class="muted" style="font-weight:400">README.md</span></h2>${readme ? markdown(readme, { dropTitle: true }) : '<p class="muted">No README.</p>'}</div>
      </div>`;
  }

  // ------------------------------------------------------------------ tutorial (guided tour)
  // A hands-on tour on a simulated run (POST /api/tutorial). Each step points at a real
  // control and waits until the user has done the thing (polled `done()`); "Skip step"
  // runs `auto()` so later steps still find what they need. Exit (or Esc inside the card)
  // leaves at any time and offers to remove the demo data (DELETE /api/tutorial).
  const tour = { on: false, i: 0, id: null, timer: null, seen: null, doneAt: 0, ask: false, base: {} };
  const tourHash = (q = "") => `#/activity/${tour.id}${q}`;
  const onTourRun = () => state.current?.id === tour.id;
  const fullRun = () => onTourRun() && !state.current.window;
  const lapsView = () => onTourRun() && !!state.current.window && /[?&]laps=1/.test(location.hash);
  const clickEl = (sel) => { const el = $(sel); if (el) el.click(); return !!el; };
  const go = (hash) => { if (location.hash !== hash) location.hash = hash; };

  const TOUR = [
    { title: "Welcome to fit-push 👋", center: true,
      body: `This tour works on a <b>simulated 5-lap park run</b>, so your own activities are not touched.
        Each step asks you to try something and moves on once you have. <b>Skip step</b> does it for you,
        <b>Exit</b> (or Esc) leaves the tour at any time.`, next: "Start the tour" },
    { title: "Open an activity", target: () => $(`#activity-list a[href="#/activity/${tour.id}"]`),
      body: "Your activities are listed here, newest first. Click <b>Tutorial run</b> to open it.",
      page: "#/", done: fullRun, auto: () => go(tourHash()) },
    { title: "The summary", target: () => $(".tiles"), page: "run",
      body: "Distance, moving time, pace, elevation, heart rate, cadence… all worked out from the raw file on your computer.",
      next: "Next" },
    { title: "Data streams", target: () => $("#charts-card"), page: "run",
      body: "Move the pointer over a chart. The values appear above the charts and a dot follows on the map.",
      done: () => state.hoverIdx != null },
    { title: "Select a stretch", target: () => $("#charts"), page: "run",
      body: "Now <b>drag across a chart</b> to select a part of the run, for example the middle.",
      done: () => onTourRun() && !!state.sel && !$("#sel-bar")?.hidden,
      auto: () => {
        const a = state.current, n = a.series.idx.length;
        state.sel = { i0: Math.round(n * 0.35), i1: Math.round(n * 0.6) };
        renderSelection(a);
      } },
    { title: "The selection bar", target: () => $("#sel-bar"), page: "run",
      body: "It shows the stretch's distance and time. You can export it, save it as an activity or turn it into a segment. Click <b>View selection</b> to zoom in on it.",
      done: () => onTourRun() && !!state.current.window && !lapsView(),
      auto: () => { if (!clickEl("#sel-bar a.btn.primary")) go(tourHash("?start=600&end=1200")); } },
    { title: "A trimmed view", target: () => $(".trim-banner"),
      body: "Every number on the page now covers just this stretch. It is temporary; the original stays as it is. Click <b>Show full activity</b> to go back.",
      done: fullRun, auto: () => go(tourHash()) },
    { title: "Colour the track", target: () => $("#ov-sel"), page: "run",
      body: "Colour the route on the map by a measure: choose <b>Pace</b>, <b>Heart rate</b> or <b>Elevation</b>.",
      done: () => state.overlay !== "none",
      auto: () => { const s = $("#ov-sel"); if (s) { s.value = "speed"; s.dispatchEvent(new Event("change")); } } },
    { title: "Colour patterns", target: () => $("#pal-wrap"), page: "run",
      body: "Pick a colour pattern you like (Red hot, Viridis, Rainbow…). ⇄ reverses it.",
      done: () => state.palette !== tour.base.palette || state.paletteReverse !== tour.base.reverse, next: "Next" },
    { title: "A bigger map", target: () => $("#map-size"), page: "run",
      body: "Click <b>⤢ Enlarge</b>. The big map zooms with the mouse wheel.",
      done: () => !!$("#map-card.expanded"), auto: () => setMapExpanded(true) },
    { title: "…and back", target: () => $("#map-size"), page: "run",
      body: "Click <b>⤡ Minimize</b> (or press Esc) to bring the map back into the page.",
      done: () => onTourRun() && !$("#map-card.expanded"), auto: () => setMapExpanded(false) },
    { title: "Laps found", target: () => $(".lap-hint"), page: "run",
      body: "fit-push noticed that this run repeats a loop. Click <b>Analyze laps</b>.",
      done: lapsView, auto: () => { if (!clickEl(".lap-hint a")) go(tourHash("?laps=1")); } },
    { title: "Compare laps", target: () => $("#lap-list"), page: "laps",
      body: "Every lap side by side. <b>Click a lap</b> (try the fastest) to compare it with the whole run and the average lap in the summary above. ↑/↓ steps through them.",
      done: () => lapsView() && state.lap != null, auto: () => clickEl('#lap-list tr[data-lap="3"]') },
    { title: "Make it a segment", target: () => $("#sel-segment"), page: "laps",
      body: "Segments are stretches you can race against yourself. Click <b>Create segment</b> and confirm the name. Every pass of the loop becomes an effort.",
      done: () => /^#\/segment\/\d+/.test(location.hash),
      auto: async () => {
        const a = state.current;
        if (!a?.series || !state.sel) { go(tourHash("?laps=1")); return; }
        const s = await api("/api/segments", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ activity_id: a.id, start: a.series.idx[state.sel.i0], end: a.series.idx[state.sel.i1], name: "Tutorial loop" }) });
        await loadSegments(); go(`#/segment/${s.id}`);
      } },
    { title: "The leaderboard", target: () => $("#seg-efforts"),
      body: "Each lap is an effort, fastest first. Click a time to jump to that effort in its activity. New uploads that follow this loop show up here by themselves.",
      next: "Next" },
    { title: "All segments", target: () => $('[data-tab="segments"]'),
      body: "The <b>Segments</b> tab lists all of them, with the best time of each.", next: "Next" },
    { title: "Tag it", target: () => $("#tag-row"), page: "run",
      body: "Tags help you find activities again. Type a tag, for example <b>intervals</b>, and press Enter.",
      done: () => onTourRun() && (state.current.tags || []).some((t) => t !== "tutorial"),
      auto: async () => {
        const a = state.current;
        a.tags = (await api(`/api/activities/${a.id}/tags`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tags: [...a.tags, "intervals"] }) })).tags;
        await Promise.all([loadTags(), loadList()]); renderTagEditor(a);
      } },
    { title: "Filter the list", target: () => ($("#tag-filter")?.hidden ? $("#sport-filter") : $("#tag-filter")),
      body: "Show only one sport or one tag in the list here.", next: "Next" },
    { title: "Extras", target: () => $('.topbar a[href="#/modules"]'),
      body: () => `Optional features are <b>modules</b>${modulePages.size ? `, such as ${[...modulePages.values()].map((p) => `<b>${esc(p.icon)} ${esc(p.label)}</b>`).join(", ")} in the tabs` : ""}. The <b>Modules</b> button lists them with their manuals.`,
      next: "Next" },
    { title: "Your turn", target: () => $(".topbar label.btn.primary"),
      body: "That's the tour! Upload your own FIT, GPX or TCX files here, or drop them anywhere on the page. You can take the tour again with the <b>Tour</b> button.",
      next: "Finish", finish: true },
  ];

  function tourSave() {
    try { if (tour.on) sessionStorage.setItem("fitpush:tour", JSON.stringify({ i: tour.i, id: tour.id })); else sessionStorage.removeItem("fitpush:tour"); } catch { /* ignore */ }
  }

  async function startTour(resume) {
    if (tour.on) return;
    let r;
    try { r = await api("/api/tutorial", { method: "POST" }); } catch (e) { toast("Could not start the tour: " + e.message); return; }
    tour.id = r.activity_id;
    if (r.created) await Promise.all([loadList(), loadTags()]);
    Object.assign(tour, { on: true, i: resume?.id === tour.id ? resume.i : 0, seen: null, ask: false,
      base: { palette: state.palette, reverse: state.paletteReverse } });
    // Clear list filters that could hide the tutorial run.
    if (state.sport || state.tagFilter) { state.sport = ""; state.tagFilter = ""; $("#sport-filter").value = ""; renderTagFilter(); renderList(); }
    document.body.insertAdjacentHTML("beforeend", `
      <div class="tour-ring" id="tour-ring" hidden></div>
      <section class="tour-card" id="tour-card" role="dialog" aria-labelledby="tour-title" aria-live="polite" tabindex="-1"></section>`);
    $("#tour-card").addEventListener("click", onTourClick);
    $("#tour-card").addEventListener("keydown", (e) => {
      // Esc minimizes an enlarged map first (the app's own handler), then leaves the tour.
      if (e.key !== "Escape" || $("#map-card.expanded")) return;
      e.stopPropagation(); tourAsk();
    });
    tourShow();
    tour.timer = setInterval(tourTick, 250);
  }

  function tourStep() { return TOUR[tour.i]; }

  // Is the step's page showing? "run" = the full tutorial run, "laps" = its laps view.
  function tourOnPage(st) {
    if (st.page === "run") return fullRun();
    if (st.page === "laps") return lapsView();
    return true;
  }
  const tourPageHash = (st) => (st.page === "run" ? tourHash() : st.page === "laps" ? tourHash("?laps=1") : st.page);

  function tourShow() {
    const st = tourStep(), card = $("#tour-card");
    if (!card) return;
    tour.seen = null; tour.doneAt = 0;
    tourSave();
    if (tour.ask) {
      card.innerHTML = `<h2 id="tour-title">Leave the tour?</h2>
        <p>The tutorial run, and any clips or segments you made from it, can be removed now. Your own data is never touched.</p>
        <div class="tour-actions"><button class="btn primary" data-tour="remove">Remove demo data</button>
          <button class="btn" data-tour="keep">Keep it</button>
          ${tourStep().finish ? "" : `<button class="btn ghost" data-tour="back">Back to the tour</button>`}</div>`;
    } else {
      const body = typeof st.body === "function" ? st.body() : st.body;
      const action = !!st.done && !st.next;
      card.innerHTML = `<div class="tour-progress" aria-hidden="true"><span style="width:${((tour.i + 1) / TOUR.length) * 100}%"></span></div>
        <div class="tour-meta muted">${tour.i ? `Step ${tour.i} of ${TOUR.length - 1}` : "Guided tour"}${action ? ` · <span class="tour-todo">your turn</span>` : ""}</div>
        <h2 id="tour-title">${esc(st.title)}</h2><p>${body}</p>
        <p class="tour-away muted" hidden>${st.page ? `This step is on another page. <button class="btn small" data-tour="there">Take me there</button>` : "Not on this page: use <b>Back</b>, or <b>Skip step</b>."}</p>
        <div class="tour-actions">
          ${st.next ? `<button class="btn primary" data-tour="next">${esc(st.next)}</button>` : ""}
          ${tour.i && !st.finish ? `<button class="btn" data-tour="skip" title="${st.auto ? "Do this step for me and go on" : "Go to the next step"}">Skip step</button>` : ""}
          ${tour.i > 1 ? `<button class="btn ghost" data-tour="prev" title="Previous step">Back</button>` : ""}
          <button class="btn ghost" data-tour="exit" title="Leave the tour (Esc)">Exit</button>
        </div>`;
      const t = st.target?.();
      if (t) t.scrollIntoView({ block: "center", behavior: "auto" });
    }
    card.focus({ preventScroll: true });
    const ring = $("#tour-ring");
    ring?.classList.add("jump"); // a new step: no slide from the previous target
    tourPlace();
    requestAnimationFrame(() => ring?.classList.remove("jump"));
  }

  async function onTourClick(e) {
    const b = e.target.closest("[data-tour]");
    if (!b) return;
    const act = b.dataset.tour, st = tourStep();
    if (act === "next") { if (st.finish) tourAsk(); else tourGo(tour.i + 1); }
    else if (act === "prev") tourGo(tour.i - 1);
    else if (act === "exit") tourAsk();
    else if (act === "back") { tour.ask = false; tourShow(); }
    else if (act === "there") go(tourPageHash(st));
    else if (act === "skip") {
      b.disabled = true;
      try {
        if (st.page && !tourOnPage(st)) { go(tourPageHash(st)); await tourWait(() => tourOnPage(st)); }
        await st.auto?.();
      } catch (err) { toast("Could not do that step: " + err.message); }
      tourGo(tour.i + 1);
    } else if (act === "remove" || act === "keep") endTour(act === "remove");
  }

  // Wait (up to 8 s) for an async page render to finish.
  async function tourWait(cond) {
    for (let k = 0; k < 32 && !cond(); k++) await new Promise((r) => setTimeout(r, 250));
  }

  function tourGo(i) {
    tour.i = Math.max(0, Math.min(TOUR.length - 1, i));
    tour.ask = false;
    tourShow();
  }

  function tourAsk() { tour.ask = true; tourShow(); }

  async function endTour(remove) {
    clearInterval(tour.timer);
    tour.on = false; tour.ask = false; tourSave();
    $("#tour-card")?.remove(); $("#tour-ring")?.remove();
    if ($("#map-card.expanded")) setMapExpanded(false);
    if (!remove) { toast("Tour closed. The tutorial run stays in your list (tag #tutorial)."); return; }
    try {
      const r = await api("/api/tutorial", { method: "DELETE" });
      await Promise.all([loadList(), loadSegments(), loadTags()]);
      toast(`Demo data removed (${r.activities} activit${r.activities === 1 ? "y" : "ies"}, ${r.segments} segment${r.segments === 1 ? "" : "s"})`);
    } catch (e) { toast("Could not remove the demo data: " + e.message); }
    if (location.hash === "#/" || !location.hash) route(); else location.hash = "#/";
  }

  function tourTick() {
    if (!tour.on) return;
    const st = tourStep();
    tourPlace();
    if (tour.ask) return;
    const away = $("#tour-card .tour-away");
    if (away) away.hidden = !(st.page && !tourOnPage(st)) && !!(st.center || st.target?.());
    if (!st.done) return;
    let ok = false;
    try { ok = !!st.done(); } catch { ok = false; }
    if (!ok) { tour.doneAt = 0; return; }
    if (st.next) { // optional action: just highlight the button
      $('#tour-card [data-tour="next"]')?.classList.add("tour-ready");
      return;
    }
    if (!tour.doneAt) {
      tour.doneAt = Date.now();
      const todo = $("#tour-card .tour-todo");
      if (todo) { todo.textContent = "✓ done"; todo.classList.add("ok"); }
      return;
    }
    if (Date.now() - tour.doneAt > 700) tourGo(tour.i + 1);
  }

  // Ring around the step's target and the card next to it (docked at the bottom on phones).
  function tourPlace() {
    const card = $("#tour-card"), ring = $("#tour-ring");
    if (!card || !ring) return;
    const st = tourStep();
    const t = !tour.ask && !st.center ? st.target?.() : null;
    const r = t && t.offsetParent !== null ? t.getBoundingClientRect() : null;
    const vw = window.innerWidth, vh = window.innerHeight;
    if (r && r.width && r.bottom > 0 && r.top < vh) {
      ring.hidden = false;
      Object.assign(ring.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
    } else ring.hidden = true;
    const narrow = vw < 640;
    card.classList.toggle("docked", narrow);
    if (narrow) { Object.assign(card.style, { left: "", top: "" }); return; }
    const cw = card.offsetWidth, ch = card.offsetHeight, gap = 14, pad = 16;
    let x, y;
    if (!r || ring.hidden) { x = (vw - cw) / 2; y = Math.max(pad, (vh - ch) / 2); }
    else {
      x = Math.min(Math.max(pad, r.left), vw - cw - pad);
      if (r.bottom + gap + ch < vh - pad) y = r.bottom + gap;
      else if (r.top - gap - ch > pad) y = r.top - gap - ch;
      else { // beside the target, or the bottom-right corner when it fills the screen
        x = r.right + gap + cw < vw - pad ? r.right + gap : r.left - gap - cw > pad ? r.left - gap - cw : vw - cw - pad;
        y = Math.min(Math.max(pad, r.top), vh - ch - pad);
      }
    }
    Object.assign(card.style, { left: `${Math.round(x)}px`, top: `${Math.round(y)}px` });
  }
  window.addEventListener("resize", () => tour.on && tourPlace());
  window.addEventListener("scroll", () => tour.on && tourPlace(), { passive: true, capture: true });

  $("#tour-btn").addEventListener("click", () => startTour());
  main.addEventListener("click", (e) => { if (e.target.closest("[data-tour-start]")) startTour(); });
  function resumeTour() {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem("fitpush:tour") || "null"); } catch { saved = null; }
    if (saved) startTour(saved);
  }

  // ------------------------------------------------------------------ router
  function route() {
    document.body.classList.remove("map-open");
    const mod = location.hash.match(/^#\/m\/([a-z0-9_-]+)(?:\?(.*))?$/);
    if (mod) { setTab(`page:${mod[1]}`); renderModulePage(mod[1], mod[2]); return; }
    const docs = location.hash.match(/^#\/modules(?:\/([a-z0-9_]+))?$/);
    if (docs) { setTab("modules"); renderModulesPage(docs[1]); return; }
    if (location.hash.startsWith("#/segment")) {
      setTab("segments");
      const sm = location.hash.match(/^#\/segment\/(\d+)/);
      if (sm) renderSegment(Number(sm[1])); else renderSegmentsPage();
      return;
    }
    setTab("activities");
    state.currentSegment = null;
    const m = location.hash.match(/^#\/activity\/(\d+)(?:\?(.*))?$/);
    if (!m) { renderDashboard(); return; }
    const q = new URLSearchParams(m[2] || "");
    const start = Number(q.get("start")), end = Number(q.get("end"));
    const win = q.has("start") && q.has("end") && Number.isInteger(start) && Number.isInteger(end) && end > start
      ? { start, end } : null;
    renderActivity(Number(m[1]), win, { laps: q.get("laps") === "1", effort: q.has("effort") ? Number(q.get("effort")) : null });
  }
  window.addEventListener("hashchange", route);
  $("#tag-filter").addEventListener("change", (e) => { state.tagFilter = e.target.value; renderList(); });
  loadSports()
    .then(() => Promise.all([loadList(), loadSegments(), loadTags(), loadModules()]))
    .then(() => { route(); resumeTour(); }).catch((e) => { main.innerHTML = `<div class="welcome"><h1>Cannot reach the server</h1><p class="muted">${esc(e.message)}</p></div>`; });
})();
