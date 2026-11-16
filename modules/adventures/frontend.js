// Adventures (frontend): registers the "Adventures" page (#/m/adventures, one adventure at ?id=<id>)
// and a header line on activity pages. Uses only window.fitpush.
(() => {
  "use strict";
  const sdk = window.fitpush;
  const esc = sdk.esc;
  const API = "/api/m/adventures";
  const TYPES = { traverse: ["🧭", "Traverse"], multiday: ["🏕️", "Multi-day"] };
  const typeBadge = (t) => `<span class="badge adv-type">${(TYPES[t] || TYPES.traverse)[0]} ${esc((TYPES[t] || TYPES.traverse)[1])}</span>`;
  const send = (path, method = "GET", body) => sdk.api(`${API}${path}`, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const U = () => sdk.fmt.units();
  // "in Kampinos National Park · near Warszawa"
  const placeText = (p) => [p.park && `${p.park.inside ? "in" : "near"} ${p.park.name}`, p.range && `⛰️ ${p.range.name}`, p.city && `near ${p.city.name}`].filter(Boolean).join(" · ");
  const unitM = () => (U().distL === "mi" ? 1609.344 : 1000);
  const day = (iso) => (iso ? sdk.fmt.day(`${iso.slice(0, 10)}T12:00:00`) : "–"); // a calendar day, not a UTC instant
  const span = (a, b) => (a === b ? day(a) : `${day(a)} – ${day(b)}`);
  const dist = (m, d = 1) => `${esc(sdk.fmt.dist(m || 0, d))} ${U().distL}`;
  const plural = (n, w, pl = `${w}s`) => `${n} ${n === 1 ? w : pl}`;
  const nActs = (n) => plural(n, "activity", "activities");
  const tile = (label, value, unit = "") => `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div></div>`;
  // Speed or pace: pace only when every sport of the adventure is a pace sport.
  const speedFmt = (sports) => (sports.length && sports.every((s) => sdk.sports.isPace(s))
    ? { f: (ms) => sdk.fmt.pace(ms), unit: `/${U().distL}`, label: "Avg pace" }
    : { f: (ms) => sdk.fmt.speed(ms), unit: U().speedL, label: "Avg speed" });
  const sportIcons = (sports) => sports.map((s) => `<span title="${esc(sdk.sports.name(s))}">${esc(sdk.sports.icon(s))}</span>`).join("");
  // Colours for n ordered items (activities or days): categorical up to 8, then a sequential ramp.
  function palette(n) {
    if (n <= 8) return Array.from({ length: n }, (_, i) => sdk.css(`--cat-${i + 1}`));
    const ramp = [1, 2, 3, 4, 5, 6, 7].map((i) => sdk.css(`--ov-${i}`));
    return Array.from({ length: n }, (_, i) => ramp[Math.round((i / (n - 1)) * 6)]);
  }

  sdk.registerPage({
    module: "adventures",
    label: "Adventures",
    icon: "🧭",
    async render(el, ctx) {
      const id = +ctx.params.get("id");
      return id ? renderAdventure(el, ctx, id) : renderList(el, ctx);
    },
  });

  // ---- list: proposals, adventures, settings --------------------------------------------------
  async function renderList(el, ctx) {
    el.innerHTML = `
      <div class="page-head"><div><h1>Adventures</h1><div class="sub" id="adv-sub">Loading…</div></div>
        <div class="adv-actions"><button type="button" class="btn" id="adv-settings-btn" aria-expanded="false">Detection settings</button>
          <button type="button" class="btn primary" id="adv-new">New adventure</button></div></div>
      <div id="adv-settings" hidden></div>
      <div class="adv-grid" id="adv-list"></div>
      <div id="adv-sugg"></div>`;
    const $ = (s) => el.querySelector(s);
    let sugg = null, advs = [], cfg = null, seq = 0; // sugg: null while detection runs
    // expanded proposal keys; looked-up places by proposal key (a place, or {error} when the lookup failed)
    const open = new Set(), places = new Map();

    // Saved adventures show at once; detection and the place lookups follow in the background.
    async function load() {
      const mine = ++seq;
      [advs, cfg] = await Promise.all([send("/adventures"), send("/settings")]);
      if (ctx.isStale() || mine !== seq) return;
      sugg = null;
      drawList(); drawSugg(); drawSettings();
      const found = await send("/suggestions").catch((e) => { sdk.toast(`Detection failed: ${e.message}`); return []; });
      if (ctx.isStale() || mine !== seq) return;
      sugg = found;
      drawList(); drawSugg();
      prefetchPlaces(mine);
    }

    // Names for the proposals, one lookup at a time (the server keeps every result, so a place is
    // looked up once); each answer only updates its own row, so open previews stay as they are.
    async function prefetchPlaces(mine) {
      if (!cfg.osm_names) return;
      for (const s of sugg) {
        if (places.has(s.key)) continue;
        try { places.set(s.key, await send("/place", "POST", { activity_ids: s.activity_ids })); }
        catch (e) { places.set(s.key, { error: e.message }); }
        if (ctx.isStale() || mine !== seq) return;
        showPlace(s.key);
      }
    }

    const placeHtml = (key) => {
      const pl = places.get(key);
      if (!cfg.osm_names) return "";
      if (!pl) return '<span class="muted">finding place…</span>';
      if (pl.error) return '<span class="muted">place not found</span>';
      return pl.name ? `📍 ${esc(placeText(pl))}` : '<span class="muted">no park or town nearby</span>';
    };
    const showPlace = (key) => el.querySelectorAll("[data-place]").forEach((n) => { if (n.dataset.place === key) n.innerHTML = placeHtml(key); });

    function drawList() {
      $("#adv-sub").textContent = advs.length ? `${plural(advs.length, "adventure")}` : "Group trips: traverses and multi-day stays.";
      $("#adv-list").innerHTML = advs.map((a) => `<a class="card adv-card" href="#/m/adventures?id=${a.id}">
          <div class="adv-card-head"><h3>${esc(a.name)}</h3>${typeBadge(a.type)}</div>
          <div class="muted adv-small">${a.first_day ? esc(span(a.first_day, a.last_day)) : "No activities yet"}</div>
          <div class="adv-card-stats"><span><b>${dist(a.distance_m)}</b></span><span>${plural(a.days, "day")}</span>
            <span>${esc(sdk.fmt.dur(a.moving_s))}</span><span>${sportIcons(a.sports)}</span></div></a>`).join("")
        || (sugg && !sugg.length ? '<div class="card muted">No adventures yet. Use <b>New adventure</b>, or create one from a proposal.</div>' : "");
    }

    function drawSugg() {
      if (!sugg) {
        $("#adv-sugg").innerHTML = '<div class="card muted adv-empty" role="status"><span class="adv-spin" aria-hidden="true"></span> Looking for adventures in your activities…</div>';
        return;
      }
      $("#adv-sugg").innerHTML = sugg.length ? `<div class="card adv-sugg"><h2><span>Proposed adventures</span><span class="muted">${plural(sugg.length, "proposal")}</span></h2>
        <div class="table-scroll"><table class="adv-table"><tbody>${sugg.map((s) => `<tr data-key="${esc(s.key)}">
          <td><button type="button" class="adv-fold" data-act="fold" aria-expanded="${open.has(s.key)}" aria-label="Show the activities of this proposal">${open.has(s.key) ? "▾" : "▸"}</button> ${typeBadge(s.type)}</td><td>${esc(span(s.first_day, s.last_day))}<div class="adv-small adv-row-place" data-place="${esc(s.key)}">${placeHtml(s.key)}</div></td>
          <td>${plural(s.days, "day")} · ${nActs(s.activity_ids.length)}</td>
          <td class="num">${dist(s.distance_m)}</td><td>${sportIcons(s.sports)}</td>
          <td class="adv-row-actions"><button type="button" class="btn small primary" data-act="accept">Create</button>
            <button type="button" class="btn small ghost" data-act="dismiss">Dismiss</button></td></tr>${open.has(s.key) ? unfolded(s) : ""}`).join("")}</tbody></table></div></div>`
        : `<div class="card muted adv-empty">No new proposals. Detection looks for chained tracks (traverses) and outings from one base on consecutive days. <button type="button" class="adv-link" id="adv-undismiss">Show dismissed proposals again</button></div>`;
      drawPreviews();
    }

    // an unfolded proposal: its activities, a small map and the place it is in
    function unfolded(s) {
      return `<tr class="adv-unfold" data-key="${esc(s.key)}"><td colspan="6"><div class="adv-unfold-body">
        <div class="adv-preview" data-preview="${esc(s.key)}"></div>
        <div class="adv-unfold-list"><table class="adv-table"><tbody>${s.activities.map((a) => `<tr><td>${esc(day(a.start_time))}</td>
          <td>${esc(sdk.sports.icon(a.sport))} <a href="#/activity/${a.id}">${esc(a.name)}</a></td><td class="num">${dist(a.distance_m)}</td></tr>`).join("")}</tbody></table>
          ${cfg.osm_names ? `<div class="adv-place"><button type="button" class="btn small" data-act="place" title="Look the place up again on OpenStreetMap">Find place again</button> <span class="adv-small" data-place="${esc(s.key)}">${placeHtml(s.key)}</span></div>` : ""}</div></div></td></tr>`;
    }

    async function drawPreviews() {
      // old preview maps left the page with their rows; sdk.map() disposes them on navigation
      for (const box of el.querySelectorAll("[data-preview]")) {
        const s = sugg.find((x) => x.key === box.dataset.preview);
        const lines = await send(`/tracks?ids=${s.activity_ids.join(",")}`);
        if (ctx.isStale() || !box.isConnected) return;
        const map = sdk.map(box);
        const colors = palette(lines.length), casing = sdk.css("--map-casing");
        let bounds = null;
        lines.forEach((t, i) => {
          L.polyline(t.track, { color: casing, weight: 5, opacity: 0.6, interactive: false }).addTo(map);
          const l = L.polyline(t.track, { color: colors[i], weight: 3 }).addTo(map);
          bounds = bounds ? bounds.extend(l.getBounds()) : l.getBounds();
        });
        if (bounds) map.fitBounds(bounds, { padding: [12, 12], animate: false });
      }
    }

    function drawSettings() {
      const m = unitM(), u = U().distL;
      const want = new Set(cfg.sports);
      $("#adv-settings").innerHTML = `<form class="card adv-form" id="adv-cfg"><h2><span>Detection settings</span></h2>
        <div class="adv-fields">
          <label>Max days without activity between days <input name="max_gap_days" type="number" min="0" max="30" step="1" value="${cfg.max_gap_days}"></label>
          <label>Traverse: next start within (${u}) of an end <input name="traverse_max_m" type="number" min="0.1" step="0.1" value="${+(cfg.traverse_max_m / m).toFixed(2)}"></label>
          <label>Multi-day: starts within (${u}) of the base <input name="base_radius_m" type="number" min="0.1" step="0.1" value="${+(cfg.base_radius_m / m).toFixed(2)}"></label>
          <label>Minimum days <input name="min_days" type="number" min="1" max="60" step="1" value="${cfg.min_days}"></label>
          <label>Ignore home (a place used in this many weeks; 0 = off) <input name="home_weeks" type="number" min="0" step="1" value="${cfg.home_weeks}"></label>
          <label>Excluded tags (comma-separated) <input name="exclude_tags" value="${esc(cfg.exclude_tags.join(", "))}" placeholder="commute"></label>
        </div>
        <label class="adv-check"><input type="checkbox" name="osm_names"${cfg.osm_names ? " checked" : ""}> Use OpenStreetMap for place names
          <span class="muted adv-small">(to name proposals, one point of each route, rounded to about 100 m, is sent to the OpenStreetMap Overpass API when this page shows them; each place is looked up once)</span></label>
        <fieldset class="adv-sports"><legend>Sports that count <span class="muted adv-small">none ticked = any sport, mixed adventures allowed</span></legend>
          ${sdk.sports.list().map((s) => `<label class="adv-check"><input type="checkbox" name="sport" value="${esc(s.key)}"${want.has(s.key) ? " checked" : ""}> ${esc(s.icon)} ${esc(s.label)}</label>`).join("")}</fieldset>
        <div class="adv-actions"><button type="submit" class="btn primary small">Save and detect</button>
          <button type="button" class="btn small" id="adv-cfg-defaults">Restore defaults</button></div></form>`;
    }

    async function saveSettings(f) {
      const m = unitM(), v = (n) => f.elements[n].value;
      const body = {
        max_gap_days: +v("max_gap_days"), min_days: +v("min_days"), home_weeks: +v("home_weeks"),
        traverse_max_m: +v("traverse_max_m") * m, base_radius_m: +v("base_radius_m") * m,
        exclude_tags: v("exclude_tags").split(",").map((t) => t.trim()).filter(Boolean),
        sports: [...f.querySelectorAll("[name=sport]:checked")].map((c) => c.value),
        osm_names: f.elements.osm_names.checked,
      };
      try {
        await send("/settings", "PUT", body); sdk.toast("Settings saved");
        $("#adv-settings").hidden = true; $("#adv-settings-btn").setAttribute("aria-expanded", "false");
        await load();
      } catch (e) { sdk.toast(`Could not save: ${e.message}`); }
    }

    el.addEventListener("submit", (ev) => { ev.preventDefault(); saveSettings(ev.target); });
    el.addEventListener("click", async (ev) => {
      const t = ev.target;
      try {
        if (t.closest("#adv-settings-btn")) {
          const box = $("#adv-settings"); box.hidden = !box.hidden;
          t.closest("button").setAttribute("aria-expanded", String(!box.hidden));
        } else if (t.closest("#adv-cfg-defaults")) {
          const { defaults } = cfg; await send("/settings", "PUT", defaults); sdk.toast("Defaults restored"); await load();
        } else if (t.closest("#adv-undismiss")) {
          const r = await send("/suggestions/reset", "POST"); sdk.toast(`${plural(r.restored, "proposal")} restored`); await load();
        } else if (t.closest("#adv-new")) {
          const name = await sdk.askName("New adventure", "Name the trip; add its activities next.", "", "Create");
          if (!name) return;
          const a = await send("/adventures", "POST", { name, type: "traverse", activity_ids: [] });
          sdk.navigate(`#/m/adventures?id=${a.id}&edit=1`);
        } else if (t.closest("[data-act]")) {
          const s = sugg.find((x) => x.key === t.closest("[data-key]").dataset.key), act = t.closest("[data-act]").dataset.act;
          if (!s) return;
          if (act === "dismiss") { open.delete(s.key); await send("/suggestions/dismiss", "POST", { key: s.key }); await load(); return; }
          if (act === "fold") { open.has(s.key) ? open.delete(s.key) : open.add(s.key); drawSugg(); return; }
          if (act === "place") {
            places.delete(s.key); showPlace(s.key);
            try { places.set(s.key, await send("/place", "POST", { activity_ids: s.activity_ids, refresh: true })); }
            catch (e) { places.set(s.key, { error: e.message }); sdk.toast(e.message); }
            if (!ctx.isStale()) showPlace(s.key);
            return;
          }
          // default name: "YYYY-MM Park, City" from the place looked up in the background (never waited for here)
          const found = places.get(s.key), place = found && !found.error ? found : null;
          const fallback = `${TYPES[s.type][1]} ${span(s.first_day, s.last_day)}`;
          const name = await sdk.askName(`Create ${TYPES[s.type][1].toLowerCase()} adventure`, `${span(s.first_day, s.last_day)} · ${nActs(s.activity_ids.length)}`, place?.name || fallback, "Create");
          if (!name) return;
          const a = await send("/adventures", "POST", { name, type: s.type, activity_ids: s.activity_ids, place });
          sdk.navigate(`#/m/adventures?id=${a.id}`);
        }
      } catch (e) { sdk.toast(e.message); }
    });
    await load();
  }

  // ---- one adventure -------------------------------------------------------------------------
  async function renderAdventure(el, ctx, id) {
    let adv;
    try { adv = await send(`/adventures/${id}`); } catch (e) {
      if (ctx.isStale()) return;
      el.innerHTML = `<div class="card"><p>${esc(e.message)}</p><a href="#/m/adventures">Back to adventures</a></div>`;
      return;
    }
    if (ctx.isStale()) return;
    const st = {
      color: ["day", "total"].includes(ctx.params.get("color")) ? ctx.params.get("color") : "activity",
      day: +ctx.params.get("day") || 0, editing: ctx.params.get("edit") === "1",
    };
    el.innerHTML = `
      <div class="page-head"><div><a href="#/m/adventures" class="adv-back">← Adventures</a><h1 id="adv-title"></h1><div class="sub" id="adv-sub"></div></div>
        <div class="adv-actions">
          <span class="seg" role="group" aria-label="Adventure type">${Object.entries(TYPES).map(([k, [i, l]]) => `<button type="button" data-type="${k}">${i} ${l}</button>`).join("")}</span>
          <button type="button" class="btn" id="adv-rename">Rename</button>
          <button type="button" class="btn" id="adv-place" title="Find the national park, mountain range and nearest city on OpenStreetMap (sends one rounded point of the route)">Find place</button>
          <button type="button" class="btn" id="adv-edit" aria-expanded="false">Edit activities</button>
          <button type="button" class="btn danger" id="adv-delete">Delete</button></div></div>
      <div id="adv-picker"></div>
      <div class="tiles" id="adv-tiles"></div>
      <div class="card adv-map-card">
        <div class="adv-map-bar"><span class="adv-small muted">Colour by</span>
          <span class="seg" role="group" aria-label="Colour by"><button type="button" data-color="activity">Activity</button><button type="button" data-color="day">Day</button><button type="button" data-color="total">Total</button></span>
          <span class="adv-days" id="adv-days" role="group" aria-label="Show day"></span></div>
        <div id="adv-map" class="adv-map"></div></div>
      <div class="adv-hl" id="adv-hl"></div>
      <div class="card adv-perday-card"><h2><span>Per day</span><span class="muted adv-small">click a day to show it on the map</span></h2><div class="table-scroll" id="adv-perday"></div></div>
      <div class="card"><h2><span>Activities</span></h2><div class="table-scroll" id="adv-acts"></div></div>`;
    const $ = (s) => el.querySelector(s);
    const map = sdk.map($("#adv-map"));
    const layer = L.layerGroup().addTo(map);
    const legend = L.control({ position: "bottomleft" });
    legend.onAdd = () => L.DomUtil.create("div", "map-legend adv-legend");
    legend.addTo(map);
    let pendingDelete = false, deleteTimer = null;
    ctx.onCleanup(() => clearTimeout(deleteTimer));

    const colors = () => {
      const acts = adv.activity_list, days = adv.per_day;
      const actC = new Map(acts.map((a, i) => [a.id, palette(acts.length)[i]]));
      const dayC = new Map(days.map((d, i) => [d.day, palette(days.length)[i]]));
      return { actC, dayC, of: (a) => (st.color === "total" ? sdk.css("--accent") : st.color === "day" ? dayC.get(a.day) : actC.get(a.id)) };
    };

    function syncState() {
      ctx.setParams({ id, color: st.color === "activity" ? "" : st.color, day: st.day || "", edit: st.editing ? "1" : "" });
      el.querySelectorAll("[data-color]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.color === st.color)));
      el.querySelectorAll("[data-color]").forEach((b) => b.classList.toggle("active", b.dataset.color === st.color));
      el.querySelectorAll("[data-type]").forEach((b) => { b.classList.toggle("active", b.dataset.type === adv.type); b.setAttribute("aria-pressed", String(b.dataset.type === adv.type)); });
      el.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.day === st.day)));
    }

    function draw() {
      const sp = speedFmt(adv.sports);
      $("#adv-title").textContent = adv.name;
      $("#adv-sub").innerHTML = adv.first_day
        ? `${typeBadge(adv.type)} ${esc(span(adv.first_day, adv.last_day))} · ${plural(adv.days, "active day")} of ${adv.span_days} · ${sportIcons(adv.sports)}${adv.place?.name ? ` · 📍 ${esc(placeText(adv.place))}` : ""}`
        : `${typeBadge(adv.type)} No activities yet: use <b>Edit activities</b>.`;
      $("#adv-tiles").innerHTML = tile("Distance", esc(sdk.fmt.dist(adv.distance_m, 1)), U().distL) + tile("Moving time", esc(sdk.fmt.dur(adv.moving_s)))
        + tile("Elevation gain", esc(sdk.fmt.ele(adv.elev_gain_m)), U().eleL) + tile(sp.label, esc(sp.f(adv.avg_speed_ms)), sp.unit)
        + tile("Days", `${adv.days}<span class="unit">/ ${adv.span_days}</span>`) + tile("Activities", String(adv.activities));
      if (st.day && !adv.per_day.some((d) => d.day === st.day)) st.day = 0;
      $("#adv-days").innerHTML = adv.per_day.length > 1 ? [`<button type="button" class="adv-chip" data-day="0">All days</button>`]
        .concat(adv.per_day.map((d) => `<button type="button" class="adv-chip" data-day="${d.day}">Day ${d.day}</button>`)).join("") : "";
      drawTables(sp);
      drawMap(true);
      syncState();
    }

    function drawTables(sp) {
      const { actC, dayC } = colors();
      const mark = (d) => [d.date === adv.fastest_day && "fastest", d.date === adv.slowest_day && "slowest", d.date === adv.longest_day && "longest", d.date === adv.shortest_day && "shortest"]
        .filter(Boolean).map((w) => `<span class="badge adv-mark">${w}</span>`).join(" ");
      // highlights (fastest/slowest/longest day) and averages per day and per activity
      const byDate = new Map(adv.per_day.map((d) => [d.date, d]));
      const hl = (label, value, note, dd) => `<div class="adv-hl-item"${dd ? ` data-day="${dd.day}" role="button" tabindex="0"` : ""}><div class="adv-hl-label">${label}</div><div class="adv-hl-value">${value}</div><div class="muted adv-small">${note}</div></div>`;
      const dayHl = (label, date, what) => { const d = byDate.get(date); return d ? hl(label, `Day ${d.day}`, `${esc(day(d.date))} · ${what(d)}`, d) : ""; };
      const avgHl = (label, o) => hl(label, dist(o.distance_m), `${esc(sdk.fmt.dur(o.moving_s))} · ${esc(sdk.fmt.ele(o.elev_gain_m))} ${U().eleL}`);
      const pace = (d) => `${esc(sp.f(d.avg_speed_ms))} ${esc(sp.unit)}`;
      $("#adv-hl").innerHTML = adv.activities ? dayHl("Fastest day", adv.fastest_day, pace) + dayHl("Slowest day", adv.slowest_day, pace)
        + dayHl("Longest day", adv.longest_day, (d) => dist(d.distance_m)) + avgHl("Average per day", adv.avg_per_day)
        + avgHl("Average per activity", adv.avg_per_activity) : "";
      $("#adv-perday").innerHTML = adv.per_day.length ? `<table class="adv-table"><thead><tr><th>Day</th><th>Date</th><th class="num">Act.</th><th class="num">Distance (${U().distL})</th><th class="num">Moving</th><th class="num">Elev. (${U().eleL})</th><th class="num">${esc(sp.label.replace("Avg ", ""))} (${esc(sp.unit)})</th><th></th></tr></thead>
        <tbody>${adv.per_day.map((d) => `<tr data-day="${d.day}" tabindex="0" aria-selected="${d.day === st.day}"><td><span class="adv-sw" style="background:${dayC.get(d.day)}"></span>${d.day}</td><td>${esc(day(d.date))}</td><td class="num">${d.activities}</td>
          <td class="num">${esc(sdk.fmt.dist(d.distance_m, 1))}</td><td class="num">${esc(sdk.fmt.dur(d.moving_s))}</td><td class="num">${esc(sdk.fmt.ele(d.elev_gain_m))}</td><td class="num">${esc(sp.f(d.avg_speed_ms))}</td><td>${mark(d)}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">–</p>';
      $("#adv-acts").innerHTML = adv.activity_list.length ? `<table class="adv-table"><thead><tr><th>Day</th><th>Activity</th><th>Sport</th><th class="num">Distance (${U().distL})</th><th class="num">Moving</th><th class="num">Elev. (${U().eleL})</th></tr></thead>
        <tbody>${adv.activity_list.map((a) => `<tr><td><span class="adv-sw" style="background:${actC.get(a.id)}"></span>${a.day ?? "–"}</td><td><a href="#/activity/${a.id}">${esc(a.name)}</a>${a.track.length ? "" : ' <span class="muted adv-small">(no GPS)</span>'}</td>
          <td>${esc(sdk.sports.icon(a.sport))} ${esc(sdk.sports.name(a.sport))}</td><td class="num">${esc(sdk.fmt.dist(a.distance_m, 1))}</td><td class="num">${esc(sdk.fmt.dur(a.moving_s))}</td><td class="num">${esc(sdk.fmt.ele(a.elev_gain_m))}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">–</p>';
    }

    function drawMap(fit) {
      layer.clearLayers();
      const { actC, dayC, of } = colors(), casing = sdk.css("--map-casing");
      let bounds = null;
      for (const a of adv.activity_list) {
        if (a.track.length < 2) continue;
        const on = !st.day || a.day === st.day;
        L.polyline(a.track, { color: casing, weight: 5, opacity: on ? 0.6 : 0.15, interactive: false }).addTo(layer);
        const line = L.polyline(a.track, { color: of(a), weight: 3, opacity: on ? 0.95 : 0.2 })
          .bindTooltip(`Day ${a.day ?? "–"} · ${esc(sdk.sports.icon(a.sport))} ${esc(a.name)}<br><span class="muted">${esc(sdk.fmt.dist(a.distance_m, 1))} ${U().distL} · ${esc(sdk.fmt.dur(a.moving_s))}</span>`, { sticky: true })
          .on("click", () => sdk.navigate(`#/activity/${a.id}`)).addTo(layer);
        if (on) bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
      }
      if (fit && bounds) map.fitBounds(bounds, { padding: [24, 24], animate: false });
      if (fit && !bounds) map.setView([20, 0], 2, { animate: false });
      const row = (c, label) => `<div class="adv-lg-row"><span class="adv-sw" style="background:${c}"></span>${label}</div>`;
      const lg = legend.getContainer();
      const tracks = adv.activity_list.filter((a) => a.track.length >= 2);
      if (!tracks.length) { lg.innerHTML = '<span class="muted">No GPS tracks</span>'; return; }
      if (st.color === "total") lg.innerHTML = `<div class="lg-title">Total</div>${row(sdk.css("--accent"), `${esc(sdk.fmt.dist(adv.distance_m, 1))} ${U().distL}`)}`;
      else if (st.color === "day") lg.innerHTML = `<div class="lg-title">Day</div>${adv.per_day.map((d) => row(dayC.get(d.day), `Day ${d.day} · ${esc(day(d.date))}`)).join("")}`;
      else lg.innerHTML = `<div class="lg-title">Activity</div>${tracks.slice(0, 12).map((a) => row(actC.get(a.id), `${a.day ?? "–"} · ${esc(a.name)}`)).join("")}${tracks.length > 12 ? `<div class="muted">+${tracks.length - 12} more</div>` : ""}`;
    }

    // -- the activity picker (edit members)
    async function drawPicker() {
      const box = $("#adv-picker");
      $("#adv-edit").setAttribute("aria-expanded", String(st.editing));
      if (!st.editing) { box.innerHTML = ""; return; }
      const iso = (d) => d.toISOString().slice(0, 10), shift = (s, n) => iso(new Date(Date.parse(`${s}T12:00:00Z`) + n * 864e5));
      const from = box.dataset.from || (adv.first_day ? shift(adv.first_day, -3) : iso(new Date(Date.now() - 30 * 864e5)));
      const to = box.dataset.to || (adv.last_day ? shift(adv.last_day, 3) : iso(new Date()));
      Object.assign(box.dataset, { from, to });
      const list = await send(`/activities?from=${from}&to=${to}`);
      if (ctx.isStale()) return;
      const mine = new Set(box.dataset.picked ? box.dataset.picked.split(",").filter(Boolean).map(Number) : adv.activity_list.map((a) => a.id));
      box.dataset.picked = [...mine].join(",");
      box.innerHTML = `<form class="card adv-picker" id="adv-pick-form"><h2><span>Activities in this adventure</span><span class="muted adv-small" id="adv-pick-n"></span></h2>
        <div class="adv-actions"><label class="adv-small">from <input type="date" id="adv-from" value="${esc(from)}"></label><label class="adv-small">to <input type="date" id="adv-to" value="${esc(to)}"></label></div>
        <div class="table-scroll adv-pick-scroll"><table class="adv-table"><tbody>${list.map((a) => `<tr><td><input type="checkbox" name="pick" value="${a.id}" aria-label="Include ${esc(a.name)}"${mine.has(a.id) ? " checked" : ""}></td>
          <td>${esc(day(a.start_time))}</td><td>${esc(sdk.sports.icon(a.sport))} ${esc(a.name)}${a.has_gps ? "" : ' <span class="muted adv-small">(no GPS)</span>'}</td><td class="num">${dist(a.distance_m)}</td>
          <td class="muted adv-small">${a.adventures.filter((x) => x !== id).length ? "in another adventure" : ""}</td></tr>`).join("") || '<tr><td class="muted">No activities in these dates.</td></tr>'}</tbody></table></div>
        <div class="adv-actions"><button type="submit" class="btn primary small">Save</button><button type="button" class="btn small" id="adv-pick-cancel">Cancel</button></div></form>`;
      $("#adv-pick-n").textContent = `${mine.size} selected`;
    }

    el.addEventListener("change", (ev) => {
      const box = $("#adv-picker");
      if (ev.target.name === "pick") {
        const mine = new Set(box.dataset.picked.split(",").filter(Boolean).map(Number));
        ev.target.checked ? mine.add(+ev.target.value) : mine.delete(+ev.target.value);
        box.dataset.picked = [...mine].join(",");
        $("#adv-pick-n").textContent = `${mine.size} selected`;
      } else if (ev.target.id === "adv-from" || ev.target.id === "adv-to") {
        box.dataset.from = $("#adv-from").value; box.dataset.to = $("#adv-to").value;
        drawPicker().catch((e) => sdk.toast(e.message));
      }
    });
    el.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const box = $("#adv-picker"), ids = box.dataset.picked.split(",").filter(Boolean).map(Number);
      try {
        adv = await send(`/adventures/${id}/activities`, "PUT", { activity_ids: ids });
        st.editing = false; box.dataset.picked = box.dataset.from = box.dataset.to = "";
        drawPicker(); draw(); sdk.toast("Activities saved");
      } catch (e) { sdk.toast(e.message); }
    });
    el.addEventListener("keydown", (ev) => {
      const tr = ev.target.closest("[data-day][tabindex]");
      if (tr && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); tr.click(); }
    });
    el.addEventListener("click", async (ev) => {
      const t = ev.target;
      try {
        const c = t.closest("[data-color]"), d = t.closest("[data-day]"), ty = t.closest("[data-type]");
        if (c) { st.color = c.dataset.color; drawTables(speedFmt(adv.sports)); drawMap(false); syncState(); }
        else if (d && !t.closest("a")) {
          st.day = +d.dataset.day === st.day && d.tagName !== "BUTTON" ? 0 : +d.dataset.day;
          el.querySelectorAll("tr[data-day]").forEach((r) => r.setAttribute("aria-selected", String(+r.dataset.day === st.day)));
          drawMap(true); syncState();
        } else if (ty && ty.dataset.type !== adv.type) { adv = await send(`/adventures/${id}`, "PATCH", { type: ty.dataset.type }); draw(); }
        else if (t.closest("#adv-rename")) {
          const name = await sdk.askName("Rename adventure", "", adv.name, "Rename");
          if (name && name !== adv.name) { adv = await send(`/adventures/${id}`, "PATCH", { name }); draw(); }
        } else if (t.closest("#adv-place")) {
          sdk.toast("Looking up the place on OpenStreetMap…");
          const place = await send(`/adventures/${id}/place`, "POST");
          if (ctx.isStale()) return;
          if (!place.name) { sdk.toast("No national park or town found nearby"); return; }
          const name = place.name !== adv.name ? await sdk.askName("Rename to the place?", placeText(place), place.name, "Rename") : null;
          adv = name && name !== adv.name ? await send(`/adventures/${id}`, "PATCH", { name }) : await send(`/adventures/${id}`);
          draw();
        } else if (t.closest("#adv-edit") || t.closest("#adv-pick-cancel")) {
          st.editing = t.closest("#adv-edit") ? !st.editing : false;
          Object.assign($("#adv-picker").dataset, { picked: "", from: "", to: "" });
          syncState(); await drawPicker();
        } else if (t.closest("#adv-delete")) {
          const b = t.closest("button");
          if (!pendingDelete) { // two-step: the first click asks, the second deletes
            pendingDelete = true; b.textContent = "Confirm delete";
            deleteTimer = setTimeout(() => { pendingDelete = false; if (b.isConnected) b.textContent = "Delete"; }, 4000);
            return;
          }
          await send(`/adventures/${id}`, "DELETE");
          sdk.toast(`Deleted ${adv.name} (its activities are kept)`);
          sdk.navigate("#/m/adventures");
        }
      } catch (e) { sdk.toast(e.message); }
    });
    draw();
    await drawPicker();
  }

  // ---- activity page: the adventures this activity belongs to -------------------------------
  sdk.registerActivityCard({
    module: "adventures",
    title: "Adventure",
    order: 70,
    placement: "header",
    async render(el, ctx) {
      const list = await send(`/activity/${ctx.activity.id}`);
      if (!list.length) return false;
      el.innerHTML = `<div class="adv-line">${list.map((a) => `<a class="adv-chip" href="#/m/adventures?id=${a.id}">${(TYPES[a.type] || TYPES.traverse)[0]} ${esc(a.name)}${a.day ? ` <span class="muted">· day ${a.day} of ${a.span_days}</span>` : ""}</a>`).join("")}</div>`;
    },
  });
})();
