// Gear (frontend): registers the "Gear" page (#/m/gear) and the "Gear" activity card. Uses only window.fitpush.
(() => {
  "use strict";
  const sdk = window.fitpush;
  const esc = sdk.esc;
  const API = "/api/m/gear";
  const KIND = {
    shoes: ["👟", "Shoes"], bike: ["🚲", "Bike"], skis: ["🎿", "Skis"], boat: ["🛶", "Boat"], other: ["🎒", "Other"],
  };
  const GROUP = {
    running: "All running", cycling: "All cycling", foot: "All walking & hiking", skiing: "All skiing",
    water: "All water sports", swimming: "All swimming", other: "All other",
  };
  const kindIcon = (k) => (KIND[k] || KIND.other)[0];
  const kindName = (k) => (KIND[k] || KIND.other)[1];
  const send = (path, method, body) => sdk.api(`${API}${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  // Distances are stored in metres; inputs use the user's distance unit.
  const unitM = () => (sdk.fmt.units().distL === "mi" ? 1609.344 : 1000);
  const targetLabel = (t) => {
    const [type, key] = t.split(":");
    return type === "family" ? GROUP[key] || `All ${key}` : `${sdk.sports.icon(key)} ${sdk.sports.name(key)}`;
  };

  // ---- Gear page --------------------------------------------------------------------------
  sdk.registerPage({
    module: "gear",
    label: "Gear",
    icon: "👟",
    async render(el, ctx) {
      let data = null, editing = null; // editing: null | "new" | gear id
      // view state (URL): view=nogear lists activities without gear, sport filters that list
      let view = ctx.params.get("view") === "nogear" ? "nogear" : "gear";
      let sportFilter = ctx.params.get("sport") || "";
      let noGear = [], picked = new Set(), lastClicked = null;
      // focused view of one item (URL: item=<id>)
      let focus = +ctx.params.get("item") || null, detail = null;
      let year = ctx.params.get("year") || null; // limits the focused view to one year (URL: year=2026)
      // setParams replaces the whole URL state, so always write all of it
      const saveUrl = () => ctx.setParams({ view: view === "nogear" ? "nogear" : null, sport: view === "nogear" ? sportFilter : null, item: focus, year });
      const detailUrl = () => `/gear/${focus}/detail${year ? `?year=${encodeURIComponent(year)}` : ""}`;
      el.innerHTML = `
        <div class="page-head"><div><h1>Gear</h1><div class="sub" id="gr-sub">Loading…</div></div>
          <div class="gr-head-actions">
            <span class="seg" role="group" aria-label="View">
              <button type="button" data-view="gear">Gear</button><button type="button" data-view="nogear" id="gr-nogear-btn">No gear</button></span>
            <button type="button" class="btn primary" id="gr-add">Add gear</button></div></div>
        <div class="gr-detail" id="gr-detail"><div id="gr-d-top"></div>
          <div class="card gr-mapcard" id="gr-mapcard" hidden><h3>Map</h3><div id="gr-map" class="gr-map"></div><div class="gr-small muted" id="gr-mapnote"></div></div>
          <div class="card gr-chartcard" id="gr-chartcard" hidden><h3>Over time</h3>
            <div class="gr-charts">
              <figure class="gr-chartbox"><figcaption class="gr-small muted" id="gr-cap-dist"></figcaption><div class="gr-canvas"><canvas id="gr-ch-dist" role="img" aria-label="Cumulative distance over time"></canvas></div></figure>
              <figure class="gr-chartbox"><figcaption class="gr-small muted" id="gr-cap-vert"></figcaption><div class="gr-canvas"><canvas id="gr-ch-vert" role="img" aria-label="Cumulative vertical meters over time"></canvas></div></figure>
            </div></div>
          <div id="gr-d-acts"></div></div>
        <div id="gr-notice"></div>
        <div id="gr-new"></div>
        <div class="gr-grid" id="gr-list"></div>
        <div id="gr-batch"></div>`;
      const $ = (s) => el.querySelector(s);

      async function load() {
        if (focus && view !== "gear") focus = null;
        let [d, list, det] = await Promise.all([
          send("/gear", "GET"),
          view === "nogear" ? send("/unassigned", "GET") : null,
          focus ? send(detailUrl(), "GET").catch(() => null) : null,
        ]);
        if (ctx.isStale()) return;
        if (det && year && !det.by_year.some((r) => r.year === year)) { // a year without activities: show all
          year = null; saveUrl();
          det = await send(detailUrl(), "GET").catch(() => null);
          if (ctx.isStale()) return;
        }
        data = d;
        detail = det;
        if (focus && !det) { focus = null; year = null; saveUrl(); } // deleted or unknown item
        if (list) {
          noGear = list;
          if (sportFilter && !list.some((a) => a.sport === sportFilter)) {
            sportFilter = "";
            if (view === "nogear") ctx.setParams({ view, sport: null });
          }
          const ids = new Set(list.map((a) => a.id));
          picked = new Set([...picked].filter((id) => ids.has(id)));
        }
        draw();
        drawMap().catch((e) => sdk.toast(e.message));
      }

      function setView(v) {
        view = v; picked.clear(); lastClicked = null; focus = null; year = null;
        saveUrl();
        load().catch((e) => sdk.toast(e.message));
      }

      // ---- activities without gear: filter, select, add one item to all selected
      const shown = () => noGear.filter((a) => !sportFilter || a.sport === sportFilter);

      function drawBatch() {
        const box = $("#gr-batch");
        if (view !== "nogear") { box.innerHTML = ""; return; }
        if (!noGear.length) { box.innerHTML = '<div class="card muted">Every activity has gear.</div>'; return; }
        const rows = shown();
        const sports = [...new Set(noGear.map((a) => a.sport))];
        const usable = data.gear.filter((g) => !g.retired);
        const u = sdk.fmt.units();
        const sportOpt = (k) => `<option value="${esc(k)}"${k === sportFilter ? " selected" : ""}>${esc(sdk.sports.icon(k))} ${esc(sdk.sports.name(k))} (${noGear.filter((a) => a.sport === k).length})</option>`;
        const picker = usable.length
          ? `<select id="gr-pick" aria-label="Gear to add">${usable.map((g) => `<option value="${g.id}">${kindIcon(g.kind)} ${esc(g.name)}</option>`).join("")}</select>
             <button type="button" class="btn primary small" id="gr-batch-add">Add to selected</button>`
          : '<span class="muted gr-small">Add gear first to assign it here.</span>';
        const row = (a) => `<tr data-aid="${a.id}">
            <td class="gr-cb"><input type="checkbox" data-pick="${a.id}" aria-label="Select ${esc(a.name)}"${picked.has(a.id) ? " checked" : ""}></td>
            <td class="gr-date">${a.start_time ? esc(sdk.fmt.day(a.start_time)) : "–"}</td>
            <td class="gr-name"><a href="#/activity/${a.id}">${esc(a.name)}</a></td>
            <td>${esc(sdk.sports.icon(a.sport))} ${esc(sdk.sports.name(a.sport))}</td>
            <td class="num">${a.distance_m ? esc(sdk.fmt.dist(a.distance_m, 1)) : "–"}</td></tr>`;
        box.innerHTML = `<div class="card gr-batch">
          <div class="gr-batch-bar">
            <select id="gr-sport" aria-label="Filter by sport"><option value="">All sports (${noGear.length})</option>${sports.map(sportOpt).join("")}</select>
            <span class="muted gr-small" id="gr-selcount" role="status"></span>
            <span class="gr-spacer"></span>${picker}
          </div>
          <div class="table-scroll gr-batch-scroll"><table class="gr-table">
            <thead><tr><th class="gr-cb"><input type="checkbox" id="gr-all" aria-label="Select all shown activities"></th>
              <th>Date</th><th>Activity</th><th>Sport</th><th class="num">Distance (${esc(u.distL)})</th></tr></thead>
            <tbody>${rows.map(row).join("")}</tbody></table></div></div>`;
        syncPicked();
      }

      function syncPicked() {
        const rows = shown(), n = rows.filter((a) => picked.has(a.id)).length;
        const all = $("#gr-all");
        if (all) { all.checked = n > 0 && n === rows.length; all.indeterminate = n > 0 && n < rows.length; }
        if ($("#gr-selcount")) $("#gr-selcount").textContent = `${n} of ${rows.length} selected`;
        if ($("#gr-batch-add")) $("#gr-batch-add").disabled = n === 0;
      }

      async function addToSelected() {
        const gid = +$("#gr-pick").value, ids = shown().filter((a) => picked.has(a.id)).map((a) => a.id);
        const g = data.gear.find((x) => x.id === gid);
        if (!ids.length || !g) return;
        try {
          const r = await send("/assign", "POST", { gear_id: gid, activity_ids: ids });
          sdk.toast(`${g.name} added to ${r.updated} activit${r.updated === 1 ? "y" : "ies"}`);
          picked.clear(); lastClicked = null;
          await load();
        } catch (e) { sdk.toast(e.message); }
      }

      function stats(g) {
        const u = sdk.fmt.units();
        const used = `${g.activities} activit${g.activities === 1 ? "y" : "ies"}${g.moving_s ? ` · ${esc(sdk.fmt.dur(g.moving_s))}` : ""}`;
        const last = g.last_used ? ` · last ${esc(sdk.fmt.day(g.last_used))}` : "";
        let bar = "";
        if (g.limit_m) {
          const pct = (g.distance_m / g.limit_m) * 100;
          bar = `<div class="gr-bar${pct >= 100 ? " over" : pct >= 85 ? " near" : ""}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(Math.min(pct, 100))}" aria-label="Share of distance limit used"><span style="width:${Math.min(pct, 100).toFixed(1)}%"></span></div>
            <div class="gr-small ${pct >= 100 ? "gr-over" : "muted"}">${Math.round(pct)}% of ${esc(sdk.fmt.dist(g.limit_m, 0))} ${u.distL}${pct >= 100 ? " · time to replace" : ""}</div>`;
        }
        return `<div class="gr-dist"><span class="gr-num">${esc(sdk.fmt.dist(g.distance_m, 1))}</span> <span class="unit">${u.distL}</span></div>
          <div class="gr-small muted">${used}${last}</div>${bar}`;
      }

      function itemCard(g) {
        if (editing === g.id) return `<div class="card gr-item">${form(g)}</div>`;
        const defs = g.defaults.length
          ? g.defaults.map((t) => `<span class="badge">${esc(targetLabel(t))}</span>`).join(" ")
          : '<span class="muted">none</span>';
        return `<div class="card gr-item${g.retired ? " gr-retired" : ""}" data-id="${g.id}">
          <div class="gr-head"><span class="gr-icon" aria-hidden="true">${kindIcon(g.kind)}</span>
            <div class="gr-title"><h3><button type="button" class="gr-name-link" data-focus="${g.id}" title="Show details and activities">${esc(g.name)}</button></h3><div class="gr-small muted">${esc(kindName(g.kind))}${g.notes ? ` · ${esc(g.notes)}` : ""}</div></div>
            ${g.retired ? '<span class="badge muted">Retired</span>' : ""}</div>
          ${stats(g)}
          <div class="gr-defaults"><span class="gr-small muted">Default for</span> ${defs}</div>
          <div class="gr-actions">
            <button type="button" class="btn small" data-act="edit">Edit</button>
            <button type="button" class="btn small" data-act="retire">${g.retired ? "Unretire" : "Retire"}</button>
            <button type="button" class="btn small danger" data-act="delete">Delete</button>
          </div></div>`;
      }

      function targetBoxes(g, kind) {
        const owner = new Map(data.defaults.filter((d) => d.kind === kind && d.gear_id !== g?.id).map((d) => [d.target, d.gear_id]));
        const names = new Map(data.gear.map((x) => [x.id, x.name]));
        const mine = new Set(g ? g.defaults : []);
        const box = (t, label) => {
          const taken = owner.has(t) ? ` <span class="muted gr-small">(now ${esc(names.get(owner.get(t)) || "?")})</span>` : "";
          return `<label class="gr-check"><input type="checkbox" name="target" value="${esc(t)}"${mine.has(t) ? " checked" : ""}> ${esc(label)}${taken}</label>`;
        };
        return Object.entries(data.groups).map(([fam, sports]) => {
          const rows = sports.length > 1 ? [box(`family:${fam}`, GROUP[fam] || `All ${fam}`)] : [];
          rows.push(...sports.map((s) => box(`sport:${s}`, `${sdk.sports.icon(s)} ${sdk.sports.name(s)}`)));
          return `<div class="gr-fam">${rows.join("")}</div>`;
        }).join("");
      }

      function form(g) {
        const m = unitM(), u = sdk.fmt.units().distL, kind = g ? g.kind : "shoes";
        const num = (v) => (v ? +(v / m).toFixed(1) : "");
        return `<form class="gr-form" data-form="${g ? g.id : "new"}">
          <h3>${g ? "Edit gear" : "New gear"}</h3>
          <div class="gr-fields">
            <label>Name <input name="name" required maxlength="100" value="${esc(g ? g.name : "")}" placeholder="e.g. Pegasus 41"></label>
            <label>Kind <select name="kind">${Object.keys(KIND).map((k) => `<option value="${k}"${k === kind ? " selected" : ""}>${kindIcon(k)} ${kindName(k)}</option>`).join("")}</select></label>
            <label>Starting distance (${u}) <input name="start" type="number" min="0" step="0.1" value="${num(g?.start_m)}" placeholder="0"></label>
            <label>Replace after (${u}) <input name="limit" type="number" min="0" step="1" value="${num(g?.limit_m)}" placeholder="no limit"></label>
            <label class="gr-wide">Notes <input name="notes" maxlength="500" value="${esc(g ? g.notes : "")}"></label>
          </div>
          <fieldset class="gr-targets"><legend>Default for <span class="muted gr-small">new activities of these sports get this gear (a sport beats its group)</span></legend>
            <div class="gr-target-list">${targetBoxes(g, kind)}</div></fieldset>
          <div class="gr-actions"><button type="submit" class="btn primary small">Save</button>
            <button type="button" class="btn small" data-act="cancel">Cancel</button></div>
        </form>`;
      }

      // ---- focused view: one item, its statistics and activities
      function drawDetail() {
        const box = $("#gr-d-top"), actsBox = $("#gr-d-acts");
        const g = focus && detail ? data.gear.find((x) => x.id === focus) : null;
        if (!g) { box.innerHTML = actsBox.innerHTML = ""; return; }
        const s = detail.stats, u = sdk.fmt.units();
        const tile = (label, value, sub = "") => `<div class="gr-tile"><div class="gr-small muted">${esc(label)}</div>
          <div class="gr-tile-v">${value}</div>${sub ? `<div class="gr-small muted">${sub}</div>` : ""}</div>`;
        const tiles = [
          tile("Distance", `${esc(sdk.fmt.dist(s.distance_m, 1))} <span class="unit">${u.distL}</span>`,
            g.start_m && !year ? `incl. ${esc(sdk.fmt.dist(g.start_m, 1))} ${u.distL} start` : ""),
          tile("Activities", String(s.activities)),
          tile("Moving time", s.moving_s ? esc(sdk.fmt.dur(s.moving_s)) : "–"),
          tile("Elevation gain", s.elev_gain_m ? `${esc(sdk.fmt.ele(s.elev_gain_m))} <span class="unit">${u.eleL}</span>` : "–"),
          tile("Average per activity", s.avg_distance_m ? `${esc(sdk.fmt.dist(s.avg_distance_m, 1))} <span class="unit">${u.distL}</span>` : "–"),
          tile("Average speed", s.avg_speed_ms ? `${esc(sdk.fmt.speed(s.avg_speed_ms))} <span class="unit">${u.speedL}</span>` : "–"),
          tile("First used", s.first_used ? esc(sdk.fmt.day(s.first_used)) : "–"),
          tile("Last used", s.last_used ? esc(sdk.fmt.day(s.last_used)) : "–"),
          // the activity link sits to the right of the value and is cut with an ellipsis, so the tile keeps its size
          s.longest ? tile("Longest", `<span class="gr-tile-row"><span>${esc(sdk.fmt.dist(s.longest.distance_m, 1))} <span class="unit">${u.distL}</span></span>
            <a class="gr-tile-link" href="#/activity/${s.longest.id}" title="${esc(s.longest.name)}">${esc(s.longest.name)}</a></span>`) : "",
        ].join("");
        const part = (rows, label) => rows.length > 1
          ? `<div class="card"><h3>${label}</h3><table class="gr-table"><tbody>${rows.join("")}</tbody></table></div>` : "";
        const line = (name, r) => `<tr><td>${name}</td><td class="num">${r.activities}</td>
          <td class="num">${esc(sdk.fmt.dist(r.distance_m, 1))} ${u.distL}</td><td class="num">${r.moving_s ? esc(sdk.fmt.dur(r.moving_s)) : "–"}</td></tr>`;
        const sports = part(detail.by_sport.map((r) => line(`${esc(sdk.sports.icon(r.sport))} ${esc(sdk.sports.name(r.sport))}`, r)), "By sport");
        // a click on a year limits everything above and below to it; click it again (or "All years") to undo
        const yearRow = (r) => line(`<button type="button" class="gr-link gr-yearbtn" data-year="${esc(r.year)}" aria-pressed="${r.year === year}" title="${r.year === year ? "Show all years" : `Show only ${esc(r.year)}`}">${esc(r.year)}</button>`, r)
          .replace("<tr>", `<tr class="gr-yr${r.year === year ? " gr-yr-on" : ""}" data-year="${esc(r.year)}">`);
        const years = part(detail.by_year.map(yearRow), "By year");
        const yearBar = year ? `<div class="gr-yearbar"><span>Showing only <b>${esc(year)}</b></span>
          <button type="button" class="btn small" data-year="${esc(year)}">All years</button></div>` : "";
        const acts = detail.activities.length
          ? `<div class="table-scroll gr-batch-scroll"><table class="gr-table"><thead><tr><th>Date</th><th>Activity</th><th>Sport</th>
              <th class="num">Distance (${esc(u.distL)})</th><th class="num">Time</th><th class="num">Elevation (${esc(u.eleL)})</th></tr></thead>
              <tbody>${detail.activities.map((a) => `<tr><td class="gr-date">${a.start_time ? esc(sdk.fmt.day(a.start_time)) : "–"}</td>
                <td class="gr-name"><a href="#/activity/${a.id}">${esc(a.name)}</a></td>
                <td>${esc(sdk.sports.icon(a.sport))} ${esc(sdk.sports.name(a.sport))}</td>
                <td class="num">${a.distance_m ? esc(sdk.fmt.dist(a.distance_m, 1)) : "–"}</td>
                <td class="num">${a.moving_s ? esc(sdk.fmt.dur(a.moving_s)) : "–"}</td>
                <td class="num">${a.elev_gain_m ? esc(sdk.fmt.ele(a.elev_gain_m)) : "–"}</td></tr>`).join("")}</tbody></table></div>`
          : '<div class="muted">No activities use this item yet.</div>';
        box.innerHTML = `<div class="gr-detail">
          <div><button type="button" class="btn small ghost" data-act="back">← All gear</button></div>
          ${itemCard(g)}
          ${yearBar}
          <div class="gr-tiles">${tiles}</div>
          ${sports || years ? `<div class="gr-split">${sports}${years}</div>` : ""}</div>`;
        actsBox.innerHTML = `<div class="card"><h3>Activities${year ? ` in ${esc(year)}` : ""} (${detail.activities.length})</h3>${acts}</div>`;
      }

      // ---- running totals over time: distance travelled and vertical metres, one point per activity
      let charts = null, spanDays = 0;
      function drawCharts() {
        const card = $("#gr-chartcard");
        const dated = focus && detail ? detail.activities.filter((a) => a.start_time).sort((a, b) => a.start_time.localeCompare(b.start_time)) : [];
        card.hidden = !dated.length;
        if (!dated.length) return;
        const u = sdk.fmt.units(), dm = unitM(), em = u.eleL === "ft" ? 3.28084 : 1;
        const g = data.gear.find((x) => x.id === focus);
        let d = year ? 0 : g.start_m / dm, v = 0; // the starting distance belongs to no year
        const t0 = Date.parse(dated[0].start_time), t1 = Math.max(Date.parse(dated.at(-1).start_time), t0 + 864e5); // at least a day wide
        spanDays = (t1 - t0) / 864e5;
        const dist = year ? [] : [{ x: t0, y: d }], vert = [{ x: t0, y: 0 }];
        for (const a of dated) {
          const x = Date.parse(a.start_time);
          d += a.distance_m / dm; v += a.elev_gain_m * em;
          dist.push({ x, y: d }); vert.push({ x, y: v });
        }
        if (year) dist.unshift({ x: t0, y: 0 });
        $("#gr-cap-dist").textContent = `Distance travelled (${u.distL}) · ${sdk.fmt.num(d, 0)} ${u.distL} total`;
        $("#gr-cap-vert").textContent = `Vertical metres (${u.eleL}) · ${sdk.fmt.num(v, 0)} ${u.eleL} total`;
        const mk = (canvas, series, color, unit) => ({
          type: "line",
          data: { datasets: [{ data: series, borderColor: color, backgroundColor: color + "33", fill: "start", borderWidth: 2, stepped: "before", pointRadius: series.length < 40 ? 3 : 0, pointHoverRadius: 4 }] },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
            interaction: { mode: "nearest", axis: "x", intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: sdk.chartStyle.tooltip({ callbacks: {
                title: (items) => sdk.fmt.day(new Date(items[0].parsed.x).toISOString()),
                label: (item) => `${sdk.fmt.num(item.parsed.y, 0)} ${unit}`,
              } }),
            },
            scales: (() => {
              const s = sdk.chartStyle.scales();
              // short spans need the day, long ones only month and year (read live: the span changes with the year)
              s.x.ticks.callback = (val) => new Date(val).toLocaleDateString(undefined, spanDays < 120 ? { day: "numeric", month: "short" } : { month: "short", year: "2-digit" });
              s.x.min = t0; s.x.max = t1;
              s.y.min = 0; s.y.beginAtZero = true;
              return s;
            })(),
          },
        });
        if (charts) { // same canvases: swap the data (the year or the item changed)
          charts.dist.data.datasets[0].data = dist; charts.vert.data.datasets[0].data = vert;
          for (const c of [charts.dist, charts.vert]) { c.options.scales.x.min = t0; c.options.scales.x.max = t1; c.update(); }
          return;
        }
        charts = {
          dist: sdk.chart($("#gr-ch-dist"), mk("dist", dist, sdk.css("--m-speed"), u.distL)),
          vert: sdk.chart($("#gr-ch-vert"), mk("vert", vert, sdk.css("--m-elevation"), u.eleL)),
        };
      }

      // ---- map of every activity that used the focused item (one map, refilled when the focus changes)
      let map = null, mapLayer = null, markerLayer = null, mapFor = null, mapItems = [];

      // Big markers: activities that start close together (in screen pixels) share one marker with a
      // count; clicking it zooms to fit those activities. Re-grouped on every zoom; an activity whose
      // route is already drawn large (>= 80 px across) gets no marker.
      function drawMarkers() {
        markerLayer.clearLayers();
        const R = 44, VISIBLE = 80, groups = [];
        for (const it of mapItems) {
          // a route that is drawn large enough to see needs no marker
          const sw = map.latLngToLayerPoint(it.bounds.getSouthWest()), ne = map.latLngToLayerPoint(it.bounds.getNorthEast());
          if (Math.hypot(ne.x - sw.x, ne.y - sw.y) >= VISIBLE) continue;
          const p = map.latLngToLayerPoint(it.start);
          const grp = groups.find((g) => Math.hypot(g.x - p.x, g.y - p.y) < R);
          if (grp) { grp.items.push(it); grp.x += (p.x - grp.x) / grp.items.length; grp.y += (p.y - grp.y) / grp.items.length; }
          else groups.push({ x: p.x, y: p.y, items: [it] });
        }
        for (const g of groups) {
          const n = g.items.length, size = n > 1 ? 40 + Math.min(16, 4 * String(n).length) : 34;
          const names = g.items.slice(-3).map((i) => esc(i.t.name)).join("<br>");
          const title = n > 1 ? `${n} activities: zoom in` : "Zoom to this activity";
          const icon = L.divIcon({ className: "gr-mk-wrap", iconSize: [size, size],
            html: `<span class="gr-mk" style="width:${size}px;height:${size}px">${n > 1 ? n : "▶"}</span>` });
          L.marker(map.layerPointToLatLng([g.x, g.y]), { icon, title, keyboard: true, riseOnHover: true })
            .bindTooltip(`${names}${n > 3 ? `<br>+${n - 3} more` : ""}`, { direction: "top", offset: [0, -size / 2] })
            .on("click", () => {
              const b = L.latLngBounds(g.items.flatMap((i) => [i.bounds.getSouthWest(), i.bounds.getNorthEast()]));
              map.fitBounds(b, { padding: [48, 48], animate: false, maxZoom: 16 });
            })
            .addTo(markerLayer);
        }
      }
      async function drawMap() {
        const card = $("#gr-mapcard");
        if (!focus || !detail) { card.hidden = true; mapFor = null; return; }
        const key = `${focus}|${year || ""}`;
        if (mapFor === key) return; // already drawn (edits redraw the page, not the map)
        const id = focus, yr = year;
        const tracks = await send(`/gear/${id}/tracks${yr ? `?year=${encodeURIComponent(yr)}` : ""}`, "GET");
        if (ctx.isStale() || focus !== id || year !== yr) return;
        mapFor = key;
        card.hidden = !tracks.length;
        if (!tracks.length) return;
        if (!map) { // created while visible
          map = sdk.map($("#gr-map"));
          mapLayer = L.layerGroup().addTo(map);
          markerLayer = L.layerGroup().addTo(map);
          map.on("zoomend", drawMarkers);
        }
        mapLayer.clearLayers();
        mapItems = tracks.map((t) => ({ t, start: t.track[0], bounds: L.latLngBounds(t.track) }));
        const casing = sdk.css("--map-casing"), ramp = [1, 2, 3, 4, 5, 6, 7].map((i) => sdk.css(`--ov-${i}`));
        const days = tracks.map((t) => t.start_time).filter(Boolean).sort();
        const t0 = days.length ? Date.parse(days[0]) : 0, t1 = days.length ? Date.parse(days.at(-1)) : 0;
        let bounds = null;
        for (const t of tracks) { // oldest first, colour by date (old → new) so recent routes are on top
          const color = t.start_time && t1 > t0 ? ramp[Math.min(6, Math.floor(((Date.parse(t.start_time) - t0) / (t1 - t0)) * 7))] : ramp[6];
          L.polyline(t.track, { color: casing, weight: 5, opacity: 0.5, interactive: false }).addTo(mapLayer);
          const line = L.polyline(t.track, { color, weight: 3, opacity: 0.9 })
            .bindTooltip(`${esc(t.name)}<br><span class="muted">${esc(sdk.fmt.day(t.start_time))} · ${esc(sdk.fmt.dist(t.distance_m, 1))} ${sdk.fmt.units().distL}</span>`, { sticky: true })
            .on("mouseover", (e) => e.target.setStyle({ weight: 5, opacity: 1 }).bringToFront())
            .on("mouseout", (e) => e.target.setStyle({ weight: 3, opacity: 0.9 }))
            .on("click", () => sdk.navigate(`#/activity/${t.id}`))
            .addTo(mapLayer);
          bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
        }
        map.invalidateSize();
        if (bounds) map.fitBounds(bounds, { padding: [24, 24], animate: false });
        drawMarkers(); // fitBounds fires no zoomend when the zoom does not change
        $("#gr-mapnote").textContent = `${tracks.length} route${tracks.length === 1 ? "" : "s"} with GPS${days.length > 1 ? ", older to newer" : ""} · click a marker to zoom in, a route to open it`;
      }

      function draw() {
        const focused = !!(focus && detail);
        $("#gr-detail").hidden = !focused;
        drawDetail();
        drawCharts();
        el.querySelectorAll("[data-view]").forEach((b) => {
          b.classList.toggle("active", b.dataset.view === view);
          b.setAttribute("aria-pressed", String(b.dataset.view === view));
        });
        $("#gr-nogear-btn").textContent = `No gear (${data.no_gear})`;
        $("#gr-add").hidden = view !== "gear" || focused;
        $("#gr-list").hidden = $("#gr-new").hidden = view !== "gear" || focused;
        drawBatch();
        const active = data.gear.filter((g) => !g.retired).length;
        $("#gr-sub").textContent = data.gear.length
          ? `${active} in use${data.gear.length > active ? `, ${data.gear.length - active} retired` : ""}`
          : "Track shoes, bikes and other equipment.";
        $("#gr-notice").innerHTML = data.unassigned && data.defaults.length && !focused
          ? `<div class="card gr-notice"><span>${data.unassigned} activit${data.unassigned === 1 ? "y has" : "ies have"} no gear yet.</span>
              <button type="button" class="btn small" id="gr-apply">Apply defaults</button></div>`
          : "";
        $("#gr-new").innerHTML = editing === "new" ? `<div class="card gr-item gr-new">${form(null)}</div>` : "";
        $("#gr-list").innerHTML = data.gear.length || editing === "new"
          ? data.gear.map(itemCard).join("")
          : '<div class="card muted">No gear yet. Use <b>Add gear</b> to add your shoes or bike, and choose which sports use it by default.</div>';
        el.querySelector("form [name=name]")?.focus();
      }

      async function save(f) {
        const id = f.dataset.form, m = unitM();
        const val = (n) => f.elements[n].value.trim();
        const body = {
          name: val("name"), kind: val("kind"), notes: val("notes"),
          start_m: val("start") ? +val("start") * m : 0,
          limit_m: val("limit") && +val("limit") > 0 ? +val("limit") * m : id === "new" ? null : 0,
        };
        if (id === "new" && body.limit_m === null) delete body.limit_m;
        const targets = [...f.querySelectorAll("[name=target]:checked")].map((c) => c.value);
        try {
          const g = id === "new" ? await send("/gear", "POST", body) : await send(`/gear/${id}`, "PATCH", body);
          if (id === "new") { editing = g.id; f.dataset.form = String(g.id); } // a retry must not add it twice
          await send(`/gear/${g.id}/defaults`, "PUT", { targets });
          editing = null;
          sdk.toast(id === "new" ? `Added ${body.name}` : `Saved ${body.name}`);
          await load();
        } catch (e) { sdk.toast(e.message); }
      }

      let pendingDelete = null, deleteTimer = null;
      el.addEventListener("submit", (ev) => { ev.preventDefault(); save(ev.target); });
      el.addEventListener("change", (ev) => {
        if (ev.target.id === "gr-sport") {
          sportFilter = ev.target.value; picked.clear(); lastClicked = null;
          ctx.setParams({ view: "nogear", sport: sportFilter });
          drawBatch();
          return;
        }
        if (ev.target.id === "gr-all") {
          for (const a of shown()) ev.target.checked ? picked.add(a.id) : picked.delete(a.id);
          el.querySelectorAll("[data-pick]").forEach((c) => (c.checked = ev.target.checked));
          syncPicked();
          return;
        }
        if (ev.target.name !== "kind") return;
        const f = ev.target.form, g = data.gear.find((x) => String(x.id) === f.dataset.form);
        const checked = new Set([...f.querySelectorAll("[name=target]:checked")].map((c) => c.value));
        f.querySelector(".gr-target-list").innerHTML = targetBoxes(g ? { ...g, defaults: [...checked] } : { id: null, defaults: [...checked] }, ev.target.value);
      });
      el.addEventListener("click", async (ev) => {
        const vb = ev.target.closest("[data-view]");
        if (vb) { if (vb.dataset.view !== view) setView(vb.dataset.view); return; }
        const fb = ev.target.closest("[data-focus]");
        if (fb) {
          focus = +fb.dataset.focus; editing = null; year = null;
          saveUrl();
          load().catch((e) => sdk.toast(e.message));
          return;
        }
        if (ev.target.closest("[data-act=back]")) {
          focus = null; editing = null; year = null;
          saveUrl();
          load().catch((e) => sdk.toast(e.message));
          return;
        }
        const yb = ev.target.closest("[data-year]"); // pick a year in "By year"; the same year again (or "All years") clears it
        if (yb) {
          year = yb.dataset.year === year ? null : yb.dataset.year;
          saveUrl();
          load().catch((e) => sdk.toast(e.message));
          return;
        }
        if (ev.target.closest("#gr-batch-add")) { addToSelected(); return; }
        const row = ev.target.closest("tr[data-aid]");
        if (row && !ev.target.closest("a")) {
          // a click anywhere on the row toggles it; Shift+click sets the whole range from the last row
          const id = +row.dataset.aid, box = row.querySelector("[data-pick]");
          if (ev.target !== box) box.checked = !box.checked;
          const on = box.checked, ids = shown().map((a) => a.id);
          if (ev.shiftKey && lastClicked !== null && ids.includes(lastClicked)) {
            const [i, j] = [ids.indexOf(lastClicked), ids.indexOf(id)].sort((x, y) => x - y);
            for (const rid of ids.slice(i, j + 1)) on ? picked.add(rid) : picked.delete(rid);
            el.querySelectorAll("[data-pick]").forEach((c) => (c.checked = picked.has(+c.dataset.pick)));
          } else if (on) picked.add(id);
          else picked.delete(id);
          lastClicked = id;
          syncPicked();
          return;
        }
        if (ev.target.closest("#gr-add")) { editing = "new"; draw(); return; }
        if (ev.target.closest("#gr-apply")) {
          try {
            const r = await send("/apply-defaults", "POST");
            sdk.toast(`Default gear added to ${r.updated} activit${r.updated === 1 ? "y" : "ies"}`);
            await load();
          } catch (e) { sdk.toast(e.message); }
          return;
        }
        const b = ev.target.closest("[data-act]");
        if (!b) return;
        if (b.dataset.act === "cancel") { editing = null; draw(); return; }
        const id = +b.closest("[data-id]")?.dataset.id;
        const g = data.gear.find((x) => x.id === id);
        if (!g) return;
        try {
          if (b.dataset.act === "edit") { editing = id; draw(); }
          else if (b.dataset.act === "retire") {
            await send(`/gear/${id}`, "PATCH", { retired: !g.retired });
            sdk.toast(g.retired ? `${g.name} is back in use` : `${g.name} retired`);
            await load();
          } else if (b.dataset.act === "delete") {
            if (pendingDelete !== id) { // two-step: the first click asks, the second deletes
              pendingDelete = id; b.textContent = "Confirm delete";
              clearTimeout(deleteTimer);
              deleteTimer = setTimeout(() => { pendingDelete = null; if (b.isConnected) b.textContent = "Delete"; }, 4000);
              return;
            }
            pendingDelete = null;
            await send(`/gear/${id}`, "DELETE");
            sdk.toast(`Deleted ${g.name}`);
            await load();
          }
        } catch (e) { sdk.toast(e.message); }
      });
      ctx.onCleanup(() => clearTimeout(deleteTimer));
      await load();
    },
  });

  // ---- Activity header line (compact, under the title and tags) -----------------------------
  sdk.registerActivityCard({
    module: "gear",
    title: "Gear",
    order: 60,
    placement: "header",
    async render(el, ctx) {
      const aid = ctx.activity.id;
      let [items, mine] = await Promise.all([send("/items", "GET"), send(`/activity/${aid}`, "GET")]);
      if (!items.length) return false;
      let choosing = false;

      function draw() {
        if (choosing) {
          const have = new Set(mine.gear.map((g) => g.id));
          const opts = items.filter((g) => !g.retired || have.has(g.id));
          el.innerHTML = `<form class="gr-line gr-choose">${opts.map((g) => `<label class="gr-check">
              <input type="checkbox" name="gear" value="${g.id}"${have.has(g.id) ? " checked" : ""}> ${kindIcon(g.kind)} ${esc(g.name)}${g.retired ? ' <span class="muted gr-small">(retired)</span>' : ""}</label>`).join("")}
            <button type="submit" class="btn primary small">Save</button>
            <button type="button" class="btn small ghost" data-act="cancel">Cancel</button></form>`;
          return;
        }
        const how = mine.manual ? "chosen by hand" : `default for ${sdk.sports.name(mine.sport)}`;
        const chips = mine.gear.length
          ? mine.gear.map((g) => `<a class="gr-chip" href="#/m/gear?item=${g.id}" title="${esc(kindName(g.kind))} · ${esc(how)}">${kindIcon(g.kind)} ${esc(g.name)}</a>`).join("")
          : '<span class="muted">none</span>';
        el.innerHTML = `<div class="gr-line">${chips}
          <button type="button" class="gr-link" data-act="change">${mine.gear.length ? "Change" : "Add"}</button>
          ${mine.manual ? '<button type="button" class="gr-link" data-act="reset" title="Use the default gear of this sport">Reset</button>' : ""}</div>`;
      }

      el.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const ids = [...ev.target.querySelectorAll("[name=gear]:checked")].map((c) => +c.value);
        try { mine = await send(`/activity/${aid}`, "PUT", { gear_ids: ids }); choosing = false; draw(); sdk.toast("Gear saved"); }
        catch (e) { sdk.toast(e.message); }
      });
      el.addEventListener("click", async (ev) => {
        const act = ev.target.closest("[data-act]")?.dataset.act;
        if (act === "change") { choosing = true; draw(); el.querySelector("input")?.focus(); }
        else if (act === "cancel") { choosing = false; draw(); }
        else if (act === "reset") {
          try { mine = await send(`/activity/${aid}/reset`, "POST"); draw(); sdk.toast("Gear reset to defaults"); }
          catch (e) { sdk.toast(e.message); }
        }
      });
      draw();
    },
  });
})();
