// Strava import (frontend): the "Strava import" page (#/m/strava_import) and the "Strava"
// activity card. Uses only window.fitpush (docs/SDK.md).
(() => {
  "use strict";
  const sdk = window.fitpush;
  const esc = sdk.esc;
  const API = "/api/m/strava_import";
  const OPTIONS = [
    ["import_new", "Import activities you don't have yet"],
    ["sport", "Sport type"],
    ["name", "Titles"],
    ["gear", "Gear (bikes, shoes and their default sports; needs the Gear module)"],
    ["commute", "Tag commutes with #commute"],
    ["notes", "Descriptions and private notes"],
  ];

  async function post(file, opts, dryRun) {
    const body = new FormData();
    body.append("file", file);
    body.append("dry_run", String(dryRun));
    for (const [k] of OPTIONS) body.append(k, String(opts[k]));
    const res = await fetch(`${API}/import`, { method: "POST", body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
    return data;
  }

  function reportHtml(r) {
    const u = r.updated;
    const tile = (label, n) => `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${n}</div></div>`;
    const types = Object.entries(r.unmapped_types);
    const rows = r.changes.slice(0, 500).map((c) => `<tr>
        <td>${c.activity_id ? `<a href="#/activity/${c.activity_id}">${esc(c.name || c.strava_id)}</a>` : esc(c.name || c.strava_id)}</td>
        <td>${c.changes.map((x) => esc(x)).join("<br>")}</td></tr>`).join("");
    return `
      <div class="card">
        <h3>${r.dry_run ? "Preview: nothing has been changed yet" : "Import finished"}</h3>
        <p class="sub">${r.activities} activities in the export: ${r.matched} already here, ${r.imported} ${r.dry_run ? "would be imported" : "imported"}${r.no_file ? `, ${r.no_file} without a file (skipped)` : ""}.</p>
        <div class="tiles">${tile("Sport", u.sport)}${tile("Title", u.name)}${tile("Gear", u.gear)}${tile("Commute", u.commute)}${tile("Notes", u.notes)}</div>
        ${r.gear_items.length ? `<p><span class="muted">Gear:</span> ${r.gear_items.map((g) => `<span class="badge">${esc(g.name)}</span>`).join(" ")}</p>` : ""}
        ${types.length ? `<p class="si-warn">Unknown Strava types (sport left as is): ${types.map(([t, n]) => `${esc(t)} (${n})`).join(", ")}</p>` : ""}
        ${r.errors.length ? `<details class="si-warn"><summary>${r.errors.length} problem${r.errors.length === 1 ? "" : "s"}</summary><ul>${r.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></details>` : ""}
      </div>
      ${rows ? `<div class="card"><h3>Changes${r.changes.length > 500 ? " (first 500)" : ""}</h3>
        <div class="table-scroll"><table class="si-table"><thead><tr><th>Activity</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table></div></div>` : ""}`;
  }

  sdk.registerPage({
    module: "strava_import",
    label: "Strava import",
    icon: "📦",
    render(el, ctx) {
      el.innerHTML = `
        <div class="page-head"><div><h1>Strava import</h1>
          <div class="sub">Bring a Strava data export (the zip from Strava's "Download your data") into fit-push.</div></div></div>
        <form class="card si-form" id="si-form">
          <label class="si-file">Export zip <input type="file" name="file" accept=".zip,application/zip" required></label>
          <fieldset class="si-opts"><legend>Bring over</legend>
            ${OPTIONS.map(([k, label]) => `<label><input type="checkbox" name="${k}" checked> ${esc(label)}</label>`).join("")}
          </fieldset>
          <div class="si-actions">
            <button type="submit" class="btn" data-dry="1">Preview</button>
            <button type="submit" class="btn primary" data-dry="0">Import</button>
            <span class="muted" id="si-status" role="status"></span>
          </div>
        </form>
        <div id="si-report"></div>`;
      const form = el.querySelector("#si-form");
      const status = el.querySelector("#si-status");
      let busy = false;
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        if (busy) return;
        const file = form.elements.file.files[0];
        if (!file) return;
        const dryRun = ev.submitter?.dataset.dry !== "0";
        const opts = Object.fromEntries(OPTIONS.map(([k]) => [k, form.elements[k].checked]));
        busy = true;
        form.querySelectorAll("button").forEach((b) => (b.disabled = true));
        status.textContent = "Reading the export… large exports take a few minutes.";
        try {
          const report = await post(file, opts, dryRun);
          if (ctx.isStale()) return;
          el.querySelector("#si-report").innerHTML = reportHtml(report);
          status.textContent = "";
          if (!dryRun) sdk.toast("Strava export imported. Reload the page to refresh the activity list.");
        } catch (err) {
          if (ctx.isStale()) return;
          status.textContent = "";
          sdk.toast(`Import failed: ${err.message}`);
        } finally {
          busy = false;
          form.querySelectorAll("button").forEach((b) => (b.disabled = false));
        }
      });
    },
  });

  sdk.registerActivityCard({
    module: "strava_import",
    title: "Strava",
    order: 70,
    async render(el, ctx) {
      const s = await sdk.api(`${API}/activity/${ctx.activity.id}`);
      if (!s) return false; // no Strava data for this activity
      const text = (t) => esc(t).replace(/\n/g, "<br>");
      el.innerHTML = `
        ${s.description ? `<p>${text(s.description)}</p>` : ""}
        ${s.private_note ? `<p><span class="muted">Private note:</span> ${text(s.private_note)}</p>` : ""}
        <p class="muted si-small">${s.strava_type ? `${esc(s.strava_type)} · ` : ""}${s.gear ? `${esc(s.gear)} · ` : ""}
          <a href="https://www.strava.com/activities/${encodeURIComponent(s.strava_id)}" target="_blank" rel="noopener noreferrer">Open on Strava</a></p>`;
    },
  });
})();
