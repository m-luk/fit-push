/* fit-git frontend: plain JS + Chart.js + Leaflet. */
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
  };
  const $ = (sel, root = document) => root.querySelector(sel);
  const main = $("#main");

  function lsGet(k) { try { return localStorage.getItem("fitgit:" + k); } catch { return null; } }
  function lsSet(k, v) { try { localStorage.setItem("fitgit:" + k, v); } catch { /* ignore */ } }
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

  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
  }

  // ------------------------------------------------------------------ units & formatting
  const PACE_SPORTS = new Set(["running", "walking", "hiking"]);
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
  const SPORT_ICON = { running: "🏃", cycling: "🚴", walking: "🚶", hiking: "🥾", swimming: "🏊" };
  const sportIcon = (s) => SPORT_ICON[s] || "⏱️";
  const sportName = (s) => (s || "unknown").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  function effortLabel(m) {
    const named = { 1609.344: "1 mile", 21097.5: "Half marathon", 42195: "Marathon" };
    if (named[m]) return named[m];
    return m >= 1000 ? `${m / 1000} km` : `${m} m`;
  }
  const durLabel = (s) => (s < 60 ? `${s}s` : s < 3600 ? `${s / 60} min` : `${s / 3600} h`);

  // ------------------------------------------------------------------ theme & units controls
  function applyTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  }
  applyTheme(lsGet("theme"));
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
    state.units = b.dataset.units; lsSet("units", state.units); syncUnitButtons(); renderList(); route();
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
      await loadList();
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
    const items = state.activities.filter((a) => !state.sport || a.sport === state.sport);
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
  async function renderDashboard() {
    destroyCharts();
    state.current = null; renderList();
    if (!state.activities.length) {
      main.innerHTML = `<div class="welcome"><h1>Your training, analysed</h1>
        <p class="muted">Upload activity files from your watch, bike computer or app — FIT, GPX and TCX are supported (gzipped too). Drag them anywhere on this page or use <b>Upload</b>.</p></div>`;
      return;
    }
    main.innerHTML = `<div class="spinner">Loading…</div>`;
    const q = new URLSearchParams({ period: state.period });
    if (state.sport) q.set("sport", state.sport);
    const st = await api(`/api/stats?${q}`);
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
    const pace = PACE_SPORTS.has(sport);
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
  let map, hoverMarker, selLine;

  const activityHash = (id, w) => `#/activity/${id}` + (w ? `?start=${w.start}&end=${w.end}` : "");
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
  async function saveClip(a, w) {
    const def = `${a.name} (clip)`;
    const name = prompt("Name for the new activity:", def);
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

  async function renderActivity(id, win) {
    destroyCharts();
    state.sel = null;
    main.innerHTML = `<div class="spinner">Analysing…</div>`;
    let a;
    try { a = await api(`/api/activities/${id}?split=${u().split}${windowQuery(win)}`); }
    catch (e) { main.innerHTML = `<div class="welcome"><h1>Not found</h1><p class="muted">${esc(e.message)}</p><a href="#/">Back to dashboard</a></div>`; return; }
    state.current = a; renderList();
    const s = a.summary;
    const pace = PACE_SPORTS.has(a.sport);
    const sportOpts = ["running", "cycling", "walking", "hiking", "swimming", "unknown"];
    if (!sportOpts.includes(a.sport)) sportOpts.unshift(a.sport);

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
      s.avg_cadence ? tile("Avg cadence", fmtNum(s.avg_cadence, 0), a.sport === "cycling" ? "rpm" : "spm") : "",
      s.avg_temp_c != null ? tile("Avg temp", fmtNum(s.avg_temp_c, 0), "°C") : "",
    ].join("");

    main.innerHTML = `
      <div class="page-head">
        <div style="flex:1;min-width:240px">
          <input class="title-input" id="name-input" value="${esc(a.name)}" aria-label="Activity name" maxlength="200">
          <div class="sub">${sportIcon(a.sport)} ${esc(fmtDate(a.start_time))} · ${esc(a.source_format.toUpperCase())}${a.device ? " · " + esc(a.device) : ""}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${a.window ? "" : `<span class="export-group" aria-label="Export full activity"><span class="muted">Export</span>${exportLinks(a, null)}</span>`}
          <select id="sport-sel" aria-label="Sport">${sportOpts.map((o) => `<option value="${esc(o)}" ${o === a.sport ? "selected" : ""}>${esc(sportName(o))}</option>`).join("")}</select>
          <button class="btn danger" id="del-btn">Delete</button>
        </div>
      </div>
      ${a.window ? `<div class="trim-banner" role="status">
        <div><strong>Trimmed view</strong> — ${fmtDist(s.distance_m || 0)} ${u().distL}${s.elapsed_s != null ? ` · ${fmtDur(s.elapsed_s)}` : ""}
          <span class="muted">(points ${a.window.start}–${a.window.end} of ${a.window.total_points}; temporary, the original is unchanged)</span></div>
        <div class="trim-actions">
          <span class="export-group"><span class="muted">Cut to new file</span>${exportLinks(a, a.window)}</span>
          <button class="btn small" id="clip-btn">Save as activity</button>
          <a class="btn small primary" href="${activityHash(a.id)}">Show full activity</a>
        </div></div>` : ""}
      <div class="tiles">${tiles}</div>
      <div class="stack">
        ${a.track ? `<div class="card"><div id="map"></div></div>` : ""}
        <div class="card" id="charts-card"><h2><span>Data streams</span>
          ${a.series.time_s ? `<span class="seg" role="group" aria-label="X axis"><button data-x="distance">Distance</button><button data-x="time">Time</button></span>` : ""}</h2>
          <div class="readout" id="readout"><span class="muted">Hover a chart to inspect values${a.track ? " and locate the point on the map" : ""}. Drag across a chart to select a section.</span></div>
          <div class="sel-bar" id="sel-bar" hidden></div>
          <div id="charts"></div>
        </div>
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
    $("#del-btn").addEventListener("click", async () => {
      if (!confirm(`Delete “${a.name}”? This cannot be undone.`)) return;
      await api(`/api/activities/${a.id}`, { method: "DELETE" });
      toast("Activity deleted"); await loadList(); location.hash = "#/";
    });

    if (a.track) drawMap(a.track);
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
  }

  function drawMap(track) {
    if (map) { map.remove(); map = null; }
    map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    const line = L.polyline(track, { color: css("--accent"), weight: 4, opacity: 0.9 }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [20, 20] });
    const dot = (latlng, color) => L.circleMarker(latlng, { radius: 6, color: css("--surface-1"), weight: 2, fillColor: color, fillOpacity: 1 }).addTo(map);
    dot(track[0], css("--m-elevation")).bindTooltip("Start");
    dot(track.at(-1), css("--text-primary")).bindTooltip("Finish");
    hoverMarker = L.circleMarker(track[0], { radius: 7, color: css("--surface-1"), weight: 2, fillColor: css("--m-hr"), opacity: 0, fillOpacity: 0 }).addTo(map);
  }

  function streamDefs(a) {
    const se = a.series;
    const pace = PACE_SPORTS.has(a.sport);
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
    if (se.cadence) defs.push({ key: "cadence", label: `Cadence (${a.sport === "cycling" ? "rpm" : "spm"})`, color: "--m-cadence", y: se.cadence, fmt: (v) => fmtNum(v, 0) });
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
    if (e.key === "Escape" && state.sel && state.current) { state.sel = null; renderSelection(state.current); }
  });

  function renderSelection(a) {
    state.charts.filter((c) => c.$synced).forEach((c) => c.draw());
    const bar = $("#sel-bar");
    if (!bar) return;
    const se = a.series;
    if (selLine) { selLine.remove(); selLine = null; }
    const sel = state.sel;
    if (!sel || se.idx[sel.i1] - se.idx[sel.i0] < 1) { bar.hidden = true; bar.innerHTML = ""; return; }
    const w = { start: se.idx[sel.i0], end: se.idx[sel.i1] };
    const dist = se.distance_m[sel.i1] - se.distance_m[sel.i0];
    const dur = se.time_s ? se.time_s[sel.i1] - se.time_s[sel.i0] : null;
    const from = se.time_s ? fmtDur(se.time_s[sel.i0]) : `${fmtDist(se.distance_m[sel.i0])} ${u().distL}`;
    const to = se.time_s ? fmtDur(se.time_s[sel.i1]) : `${fmtDist(se.distance_m[sel.i1])} ${u().distL}`;
    bar.hidden = false;
    bar.innerHTML = `<div><strong>Selection</strong> ${fmtDist(dist)} ${u().distL}${dur != null ? ` · ${fmtDur(dur)}` : ""}
        <span class="muted">(${from} → ${to})</span></div>
      <div class="trim-actions">
        <a class="btn small primary" href="${activityHash(a.id, w)}">View selection</a>
        <span class="export-group"><span class="muted">Cut to new file</span>${exportLinks(a, w)}</span>
        <button class="btn small" id="sel-save">Save as activity</button>
        <button class="btn small ghost" id="sel-clear" title="Clear selection (Esc)">Clear</button>
      </div>`;
    $("#sel-save").addEventListener("click", () => saveClip(a, w));
    $("#sel-clear").addEventListener("click", () => { state.sel = null; renderSelection(a); });
    if (map && se.lat) {
      const pts = [];
      for (let k = sel.i0; k <= sel.i1; k++) if (se.lat[k] != null && se.lon[k] != null) pts.push([se.lat[k], se.lon[k]]);
      if (pts.length > 1) selLine = L.polyline(pts, { color: css("--sel-edge"), weight: 6, opacity: 0.95 }).addTo(map);
      hoverMarker?.bringToFront();
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

  // ------------------------------------------------------------------ router
  function route() {
    const m = location.hash.match(/^#\/activity\/(\d+)(?:\?(.*))?$/);
    if (!m) { renderDashboard(); return; }
    const q = new URLSearchParams(m[2] || "");
    const start = Number(q.get("start")), end = Number(q.get("end"));
    const win = q.has("start") && q.has("end") && Number.isInteger(start) && Number.isInteger(end) && end > start
      ? { start, end } : null;
    renderActivity(Number(m[1]), win);
  }
  window.addEventListener("hashchange", route);
  loadList().then(route).catch((e) => { main.innerHTML = `<div class="welcome"><h1>Cannot reach the server</h1><p class="muted">${esc(e.message)}</p></div>`; });
})();
