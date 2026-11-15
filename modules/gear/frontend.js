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
      el.innerHTML = `
        <div class="page-head"><div><h1>Gear</h1><div class="sub" id="gr-sub">Loading…</div></div>
          <div><button type="button" class="btn primary" id="gr-add">Add gear</button></div></div>
        <div id="gr-notice"></div>
        <div id="gr-new"></div>
        <div class="gr-grid" id="gr-list"></div>`;
      const $ = (s) => el.querySelector(s);

      async function load() {
        const d = await send("/gear", "GET");
        if (ctx.isStale()) return;
        data = d;
        draw();
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
            <div class="gr-title"><h3>${esc(g.name)}</h3><div class="gr-small muted">${esc(kindName(g.kind))}${g.notes ? ` · ${esc(g.notes)}` : ""}</div></div>
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

      function draw() {
        const active = data.gear.filter((g) => !g.retired).length;
        $("#gr-sub").textContent = data.gear.length
          ? `${active} in use${data.gear.length > active ? `, ${data.gear.length - active} retired` : ""}`
          : "Track shoes, bikes and other equipment.";
        $("#gr-notice").innerHTML = data.unassigned && data.defaults.length
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
          await send(`/gear/${g.id}/defaults`, "PUT", { targets });
          editing = null;
          sdk.toast(id === "new" ? `Added ${body.name}` : `Saved ${body.name}`);
          await load();
        } catch (e) { sdk.toast(e.message); }
      }

      let pendingDelete = null, deleteTimer = null;
      el.addEventListener("submit", (ev) => { ev.preventDefault(); save(ev.target); });
      el.addEventListener("change", (ev) => {
        if (ev.target.name !== "kind") return;
        const f = ev.target.form, g = data.gear.find((x) => String(x.id) === f.dataset.form);
        const checked = new Set([...f.querySelectorAll("[name=target]:checked")].map((c) => c.value));
        f.querySelector(".gr-target-list").innerHTML = targetBoxes(g ? { ...g, defaults: [...checked] } : { id: null, defaults: [...checked] }, ev.target.value);
      });
      el.addEventListener("click", async (ev) => {
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

  // ---- Activity card ----------------------------------------------------------------------
  sdk.registerActivityCard({
    module: "gear",
    title: "Gear",
    order: 60,
    async render(el, ctx) {
      const aid = ctx.activity.id;
      let [list, mine] = await Promise.all([send("/gear", "GET"), send(`/activity/${aid}`, "GET")]);
      if (!list.gear.length) return false;
      let choosing = false;

      function draw() {
        if (choosing) {
          const have = new Set(mine.gear.map((g) => g.id));
          const opts = list.gear.filter((g) => !g.retired || have.has(g.id));
          el.innerHTML = `<form class="gr-choose"><div class="gr-target-list">${opts.map((g) => `<label class="gr-check">
              <input type="checkbox" name="gear" value="${g.id}"${have.has(g.id) ? " checked" : ""}> ${kindIcon(g.kind)} ${esc(g.name)}${g.retired ? ' <span class="muted gr-small">(retired)</span>' : ""}</label>`).join("")}</div>
            <div class="gr-actions"><button type="submit" class="btn primary small">Save</button>
              <button type="button" class="btn small" data-act="cancel">Cancel</button></div></form>`;
          return;
        }
        const chips = mine.gear.length
          ? mine.gear.map((g) => `<span class="badge gr-chip">${kindIcon(g.kind)} ${esc(g.name)}</span>`).join(" ")
          : '<span class="muted">No gear</span>';
        const how = mine.manual ? "Chosen by hand" : `Default for ${esc(sdk.sports.name(mine.sport))}`;
        el.innerHTML = `<div class="gr-card"><div class="gr-chips">${chips}</div>
          <div class="gr-actions"><span class="gr-small muted">${how}</span>
            <button type="button" class="btn small" data-act="change">Change</button>
            ${mine.manual ? '<button type="button" class="btn small" data-act="reset">Reset to defaults</button>' : ""}
            <button type="button" class="btn small ghost" data-act="page">Manage gear</button></div></div>`;
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
        else if (act === "page") sdk.navigate("#/m/gear");
        else if (act === "reset") {
          try { mine = await send(`/activity/${aid}/reset`, "POST"); draw(); sdk.toast("Gear reset to defaults"); }
          catch (e) { sdk.toast(e.message); }
        }
      });
      draw();
    },
  });
})();
