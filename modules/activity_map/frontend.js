// All activities map (frontend): registers the "Map" page (#/m/activity_map). Uses only window.fitpush.
(() => {
  "use strict";
  const sdk = window.fitpush;
  const esc = sdk.esc;
  const PRESETS = { all: "All time", d30: "Last 30 days", d90: "Last 90 days", y1: "Last 12 months", ytd: "This year" };

  function presetRange(key) {
    const today = new Date(), iso = (d) => d.toISOString().slice(0, 10), back = (days) => iso(new Date(today - days * 864e5));
    return { all: ["", ""], d30: [back(30), ""], d90: [back(90), ""], y1: [back(365), ""], ytd: [`${today.getFullYear()}-01-01`, ""] }[key] || ["", ""];
  }

  sdk.registerPage({
    module: "activity_map",
    label: "Map",
    icon: "🗺️",
    async render(el, ctx) {
      const facets = await sdk.api("/api/m/activity_map/facets");
      if (ctx.isStale()) return;
      const p = ctx.params;
      const st = {
        sports: new Set((p.get("sports") || "").split(",").filter(Boolean)),
        tags: new Set((p.get("tags") || "").split(",").filter(Boolean)),
        from: p.get("from") || "", to: p.get("to") || "", color: p.get("color") === "date" ? "date" : "sport",
      };
      // Colour slots follow the sport (catalogue order of sports present in the data), so
      // filtering never repaints a sport. Past 8 sports, the rest share a neutral "Other".
      const present = sdk.sports.list().map((s) => s.key).filter((k) => facets.sports[k])
        .concat(Object.keys(facets.sports).filter((k) => !sdk.sports.get(k)));
      const slot = new Map(present.map((k, i) => [k, i < 8 ? `--cat-${i + 1}` : "--cat-other"]));
      const sportColor = (k) => sdk.css(slot.get(k) || "--cat-other");

      el.innerHTML = `
        <div class="page-head"><div><h1>All activities</h1><div class="sub" id="am-status">Loading…</div></div></div>
        <div class="card am-filters">
          <div class="am-row"><span class="am-label">Sports</span><div class="am-chips" id="am-sports"></div></div>
          ${facets.tags.length ? `<div class="am-row"><span class="am-label">Tags</span><div class="am-chips" id="am-tags"></div></div>` : ""}
          <div class="am-row"><span class="am-label">Dates</span>
            <select id="am-preset" aria-label="Date range preset">${Object.entries(PRESETS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}<option value="custom">Custom…</option></select>
            <label class="am-date">from <input type="date" id="am-from" value="${esc(st.from)}"></label>
            <label class="am-date">to <input type="date" id="am-to" value="${esc(st.to)}"></label>
            <span class="am-spacer"></span>
            <span class="am-label">Colour by</span>
            <span class="seg" role="group" aria-label="Colour by"><button data-color="sport">Sport</button><button data-color="date">Date</button></span>
          </div>
        </div>
        <div class="card am-map-card"><div id="am-map" class="am-map"></div></div>`;
      const $ = (s) => el.querySelector(s);

      const chip = (kind, key, label, color, n) => `<button type="button" class="am-chip" data-${kind}="${esc(key)}" aria-pressed="false">
          ${color ? `<span class="am-sw" style="background:${color}"></span>` : ""}${esc(label)} <span class="muted">${n}</span></button>`;
      $("#am-sports").innerHTML = present.map((k) => chip("sport", k, `${sdk.sports.icon(k)} ${sdk.sports.name(k)}`, sportColor(k), facets.sports[k])).join("");
      if ($("#am-tags")) $("#am-tags").innerHTML = facets.tags.map((t) => chip("tag", t.tag, `#${t.tag}`, null, t.count)).join("");

      const map = sdk.map($("#am-map"));
      const layer = L.layerGroup().addTo(map);
      const legend = L.control({ position: "bottomleft" });
      legend.onAdd = () => L.DomUtil.create("div", "map-legend am-legend");
      legend.addTo(map);
      let fitted = false, timer = null, seq = 0;

      function syncControls() {
        el.querySelectorAll("[data-sport]").forEach((b) => b.setAttribute("aria-pressed", String(st.sports.has(b.dataset.sport))));
        el.querySelectorAll("[data-tag]").forEach((b) => b.setAttribute("aria-pressed", String(st.tags.has(b.dataset.tag))));
        el.querySelectorAll("[data-color]").forEach((b) => b.classList.toggle("active", b.dataset.color === st.color));
        $("#am-from").value = st.from; $("#am-to").value = st.to;
        const preset = Object.keys(PRESETS).find((k) => { const [f, t] = presetRange(k); return f === st.from && t === st.to; });
        $("#am-preset").value = preset || "custom";
        ctx.setParams({ sports: [...st.sports].join(","), tags: [...st.tags].join(","), from: st.from, to: st.to, color: st.color === "date" ? "date" : "" });
      }

      async function load() {
        syncControls();
        const q = new URLSearchParams();
        if (st.sports.size) q.set("sports", [...st.sports].join(","));
        if (st.tags.size) q.set("tags", [...st.tags].join(","));
        if (st.from) q.set("from", st.from);
        if (st.to) q.set("to", st.to);
        const mine = ++seq;
        const data = await sdk.api(`/api/m/activity_map/tracks?${q}`);
        if (mine !== seq || ctx.isStale()) return; // a newer filter change won
        draw(data.activities);
      }

      function draw(acts) {
        layer.clearLayers();
        const days = acts.map((a) => a.start_time).filter(Boolean).sort();
        const t0 = days.length ? Date.parse(days[0]) : 0, t1 = days.length ? Date.parse(days.at(-1)) : 0;
        const ramp = [1, 2, 3, 4, 5, 6, 7].map((i) => sdk.css(`--ov-${i}`));
        const dateColor = (a) => (a.start_time && t1 > t0 ? ramp[Math.min(6, Math.floor(((Date.parse(a.start_time) - t0) / (t1 - t0)) * 7))] : ramp[6]);
        // Oldest first, so recent routes are drawn on top.
        const ordered = [...acts].sort((x, y) => (x.start_time || "").localeCompare(y.start_time || ""));
        let bounds = null, dist = 0;
        for (const a of ordered) {
          const color = st.color === "date" ? dateColor(a) : sportColor(a.sport);
          const line = L.polyline(a.track, { color, weight: 2.5, opacity: 0.8 })
            .bindTooltip(`${sdk.sports.icon(a.sport)} ${esc(a.name)}<br><span class="muted">${esc(sdk.fmt.day(a.start_time))} · ${sdk.fmt.dist(a.distance_m || 0)} ${sdk.fmt.units().distL}</span>`, { sticky: true })
            .on("mouseover", (e) => e.target.setStyle({ weight: 5, opacity: 1 }).bringToFront())
            .on("mouseout", (e) => e.target.setStyle({ weight: 2.5, opacity: 0.8 }))
            .on("click", () => sdk.navigate(`#/activity/${a.id}`))
            .addTo(layer);
          bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
          dist += a.distance_m || 0;
        }
        if (bounds && !fitted) { map.fitBounds(bounds, { padding: [24, 24], animate: false }); fitted = true; }
        if (!bounds) map.setView([20, 0], 2, { animate: false });
        $("#am-status").textContent = acts.length
          ? `${acts.length} activit${acts.length === 1 ? "y" : "ies"} · ${sdk.fmt.dist(dist, 0)} ${sdk.fmt.units().distL} · click a route to open it`
          : "No activities with GPS match these filters.";
        const lg = legend.getContainer();
        if (st.color === "date") {
          lg.innerHTML = `<div class="lg-title">Date</div><div class="lg-ramp">${ramp.map((c) => `<span style="background:${c}"></span>`).join("")}</div>
            <div class="lg-labels"><span>${esc(sdk.fmt.day(days[0]) || "–")}</span><span>${esc(sdk.fmt.day(days.at(-1)) || "–")}</span></div>`;
        } else {
          const shown = [...new Set(acts.map((a) => a.sport))].sort((x, y) => present.indexOf(x) - present.indexOf(y));
          lg.innerHTML = `<div class="lg-title">Sport</div>${shown.map((k) => `<div class="am-lg-row"><span class="am-sw" style="background:${sportColor(k)}"></span>${esc(sdk.sports.name(k))}</div>`).join("") || '<span class="muted">–</span>'}`;
        }
      }

      const reload = () => { clearTimeout(timer); timer = setTimeout(load, 150); };
      el.addEventListener("click", (ev) => {
        const b = ev.target.closest("[data-sport],[data-tag],[data-color]");
        if (!b) return;
        if (b.dataset.color) st.color = b.dataset.color;
        else {
          const set = b.dataset.sport ? st.sports : st.tags, key = b.dataset.sport || b.dataset.tag;
          if (set.has(key)) set.delete(key); else set.add(key);
          fitted = false;
        }
        reload();
      });
      $("#am-preset").addEventListener("change", (e) => {
        if (e.target.value === "custom") { $("#am-from").focus(); return; }
        [st.from, st.to] = presetRange(e.target.value);
        fitted = false; reload();
      });
      for (const id of ["#am-from", "#am-to"]) {
        $(id).addEventListener("change", () => { st.from = $("#am-from").value; st.to = $("#am-to").value; fitted = false; reload(); });
      }
      ctx.onCleanup(() => clearTimeout(timer));
      await load();
    },
  });
})();
