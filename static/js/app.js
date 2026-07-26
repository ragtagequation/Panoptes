const $ = (sel) => document.querySelector(sel);

let pollTimer = null;
let activeJobId = null;
let discoverTimer = null;
let discoverClockTimer = null;
let discoverStartedAt = null;
let lastDiscover = null;
let radarTimer = null;
let radarClockTimer = null;
let radarStartedAt = null;
let lastRadar = null;

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function formatEstimateRange(low, high) {
  const fmt = (sec) => {
    if (sec < 60) return `${Math.max(15, Math.round(sec / 5) * 5)}s`;
    const mins = sec / 60;
    if (mins < 10) return `${mins.toFixed(1).replace(/\.0$/, "")} min`;
    return `${Math.round(mins)} min`;
  };
  if (!low || !high) return "—";
  return `~${fmt(low)}–${fmt(high)}`;
}

function selectedSources() {
  const sources = [];
  if ($("#src-reddit").checked) sources.push("reddit");
  if ($("#src-web").checked) sources.push("web");
  if ($("#src-github").checked) sources.push("github");
  return sources;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || `Request failed (${res.status})`);
  }
  return data;
}

function setStatus(el, text, isError = false) {
  el.hidden = !text;
  el.textContent = text || "";
  el.classList.toggle("error", isError);
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function switchMode(mode) {
  const radar = mode === "radar";
  $("#mode-radar").hidden = !radar;
  $("#mode-discover").hidden = radar;
  $("#tab-radar").classList.toggle("active", radar);
  $("#tab-discover").classList.toggle("active", !radar);
}

/* ── Radar ─────────────────────────────────────────── */

async function refreshRadarEstimate() {
  const target = Number($("#radar-target").value || 25);
  const params = new URLSearchParams({
    target: String(target),
    scrape_sites: String($("#radar-sites").checked),
    deepen: String($("#radar-deepen").checked),
  });
  try {
    const est = await api(`/api/radar/estimate?${params}`);
    $("#radar-estimate").textContent = formatEstimateRange(
      est.estimate_low_seconds,
      est.estimate_high_seconds
    );
  } catch {
    $("#radar-estimate").textContent = formatEstimateRange(40 + target * 2, 80 + target * 5);
  }
}

function startRadarClock(estimateHigh = null) {
  radarStartedAt = Date.now();
  const box = $("#radar-timer-box");
  const line = $("#radar-timer-line");
  box.hidden = false;
  box.classList.add("running");
  line.hidden = false;
  const tick = () => {
    const elapsed = (Date.now() - radarStartedAt) / 1000;
    $("#radar-timer").textContent = formatDuration(elapsed);
    const estText = estimateHigh
      ? ` · est. up to ${formatDuration(estimateHigh)}`
      : "";
    line.textContent = `Timer ${formatDuration(elapsed)}${estText}`;
  };
  tick();
  if (radarClockTimer) clearInterval(radarClockTimer);
  radarClockTimer = setInterval(tick, 250);
}

function stopRadarClock(finalSeconds = null) {
  if (radarClockTimer) {
    clearInterval(radarClockTimer);
    radarClockTimer = null;
  }
  $("#radar-timer-box").classList.remove("running");
  const elapsed =
    finalSeconds != null
      ? finalSeconds
      : radarStartedAt
        ? (Date.now() - radarStartedAt) / 1000
        : 0;
  $("#radar-timer").textContent = formatDuration(elapsed);
  $("#radar-timer-line").hidden = false;
  $("#radar-timer-line").textContent = `Finished in ${formatDuration(elapsed)}`;
}

function draftBlock(label, text) {
  if (!text) return "";
  return `
    <details class="draft">
      <summary>${escapeHtml(label)}</summary>
      <pre></pre>
      <button type="button" class="btn ghost copy-btn">Copy</button>
    </details>
  `;
}

function renderRadar(job) {
  $("#radar-results").hidden = false;
  const badge = $("#radar-badge");
  badge.textContent = job.status;
  badge.className = `badge ${job.status}`;
  $("#radar-message").textContent = job.message || "";
  const leads = job.leads || [];
  const stats = job.stats || {};
  $("#radar-count").textContent =
    `${leads.length} asks · ${stats.contactable ?? 0} contactable · ` +
    `${stats.zero_replies ?? 0} zero-reply · ${stats.deepened ?? 0} deepened · ` +
    `avg silence ${stats.avg_silence ?? "—"}`;

  if (job.status === "running" || job.status === "queued") {
    if (job.elapsed_seconds != null) {
      $("#radar-timer").textContent = formatDuration(job.elapsed_seconds);
    }
    const high = job.estimate_high_seconds;
    $("#radar-timer-line").hidden = false;
    $("#radar-timer-line").textContent = high
      ? `Timer ${formatDuration(job.elapsed_seconds || 0)} · est. up to ${formatDuration(high)}`
      : `Timer ${formatDuration(job.elapsed_seconds || 0)}`;
  }

  const cards = $("#radar-cards");
  cards.innerHTML = "";
  for (const lead of leads.slice(0, 80)) {
    const card = document.createElement("article");
    card.className = "ask-card";
    const quote = lead.ask_quote || lead.evidence || "";
    const askUrl = lead.ask_url || "";
    const contactBits = [
      lead.email ? `✉ ${lead.email}` : null,
      lead.phone ? `☎ ${lead.phone}` : null,
      lead.website ? lead.website.replace(/^https?:\/\//, "").slice(0, 36) : null,
    ].filter(Boolean);
    const drafts = [
      ["Public reply", lead.public_reply],
      ["DM / email", lead.dm_or_email],
      ["Call opener", lead.call_opener],
      ["SMS", lead.sms],
    ].filter(([, t]) => t);
    card.innerHTML = `
      <div class="ask-meta">
        <span class="silence">${escapeHtml(String(lead.silence_score ?? "—"))}</span>
        <span class="ask-label">${escapeHtml(lead.silence_label || "")}</span>
        <span class="ask-context">${escapeHtml(lead.context || lead.platform || "")}</span>
        <span class="ask-age">${lead.age_days != null ? `${lead.age_days}d` : ""} · ${lead.num_comments ?? 0} replies</span>
      </div>
      <blockquote>${escapeHtml(quote.slice(0, 320))}</blockquote>
      <div class="ask-links">
        ${askUrl ? `<a href="${escapeHtml(askUrl)}" target="_blank" rel="noopener">Open ask</a>` : ""}
        <span>u/${escapeHtml(lead.username || "?")}</span>
        ${contactBits.length ? `<span class="ask-contact">${escapeHtml(contactBits.join(" · "))}</span>` : `<span class="ask-contact muted">public reply opportunity</span>`}
        ${(lead.deepened_platforms || []).length ? `<span class="ask-contact">deepened: ${escapeHtml((lead.deepened_platforms || []).join(", "))}</span>` : ""}
      </div>
      ${drafts.map(([label, text]) => draftBlock(label, text)).join("")}
      <div class="outcome-row">
        <select class="outcome-select" data-ask="${escapeHtml(lead.ask_id || "")}">
          <option value="">Outcome…</option>
          <option value="replied" ${lead.outcome === "replied" ? "selected" : ""}>Replied</option>
          <option value="booked" ${lead.outcome === "booked" ? "selected" : ""}>Booked</option>
          <option value="ignored" ${lead.outcome === "ignored" ? "selected" : ""}>Ignored</option>
          <option value="skipped" ${lead.outcome === "skipped" ? "selected" : ""}>Skipped</option>
        </select>
      </div>
    `;
    const draftEls = card.querySelectorAll(".draft");
    draftEls.forEach((el, i) => {
      const text = drafts[i][1];
      el.querySelector("pre").textContent = text;
      el.querySelector(".copy-btn").addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(text);
          el.querySelector(".copy-btn").textContent = "Copied";
          setTimeout(() => { el.querySelector(".copy-btn").textContent = "Copy"; }, 1200);
        } catch { /* ignore */ }
      });
    });
    cards.appendChild(card);
  }

  cards.querySelectorAll(".outcome-select").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const askId = sel.dataset.ask;
      const outcome = sel.value;
      if (!askId || !outcome) return;
      try {
        await api(`/api/radar/outcome/${encodeURIComponent(askId)}`, {
          method: "POST",
          body: JSON.stringify({ outcome, status: outcome }),
        });
      } catch (err) {
        setStatus($("#radar-status"), err.message, true);
      }
    });
  });

  const actions = $("#radar-actions");
  actions.innerHTML = "";
  if (job.files && job.files.radar_csv) {
    const a = document.createElement("a");
    a.className = "btn primary";
    a.href = `/api/exports/${encodeURIComponent(job.files.radar_csv)}`;
    a.textContent = "Download radar CSV";
    actions.appendChild(a);
  }
  if (job.files && job.files.instantly_csv) {
    const a = document.createElement("a");
    a.className = "btn ghost";
    a.href = `/api/exports/${encodeURIComponent(job.files.instantly_csv)}`;
    a.textContent = "Instantly CSV";
    actions.appendChild(a);
  }
}

async function pollRadar(jobId) {
  const job = await api(`/api/radar/${jobId}`);
  lastRadar = job;
  renderRadar(job);
  if (job.status === "completed" || job.status === "failed") {
    clearInterval(radarTimer);
    radarTimer = null;
    stopRadarClock(job.elapsed_seconds);
    $("#radar-btn").disabled = false;
    setStatus($("#radar-status"), job.message, job.status === "failed");
    loadExports();
    loadWatches();
  }
}

async function startRadar() {
  const status = $("#radar-status");
  const offer = $("#radar-offer").value.trim();
  if (offer.length < 3) {
    setStatus(status, "Enter your offer (a few words minimum).", true);
    return;
  }
  try {
    $("#radar-btn").disabled = true;
    setStatus(status, "Hunting unanswered demand…");
    const data = await api("/api/radar", {
      method: "POST",
      body: JSON.stringify({
        offer,
        niche: $("#radar-niche").value.trim(),
        company: $("#radar-company").value.trim(),
        target: Number($("#radar-target").value || 25),
        max_comments: Number($("#radar-max-comments").value || 2),
        require_contact: $("#radar-require-contact").checked,
        only_new: $("#radar-only-new").checked,
        include_web: $("#radar-web").checked,
        scrape_sites: $("#radar-sites").checked,
        deepen: $("#radar-deepen").checked,
      }),
    });
    if (data.estimate_low_seconds) {
      $("#radar-estimate").textContent = formatEstimateRange(
        data.estimate_low_seconds,
        data.estimate_high_seconds
      );
    }
    startRadarClock(data.estimate_high_seconds);
    if (radarTimer) clearInterval(radarTimer);
    await pollRadar(data.job_id);
    radarTimer = setInterval(() => pollRadar(data.job_id), 1500);
  } catch (err) {
    $("#radar-btn").disabled = false;
    stopRadarClock();
    setStatus(status, err.message, true);
  }
}

async function saveWatch() {
  const status = $("#radar-status");
  const offer = $("#radar-offer").value.trim();
  if (offer.length < 3) {
    setStatus(status, "Enter an offer before saving a watch.", true);
    return;
  }
  try {
    await api("/api/radar/watches", {
      method: "POST",
      body: JSON.stringify({
        offer,
        niche: $("#radar-niche").value.trim(),
        company: $("#radar-company").value.trim(),
        interval_hours: 6,
        max_comments: Number($("#radar-max-comments").value || 2),
        target: Number($("#radar-target").value || 25),
        enabled: true,
        deepen: $("#radar-deepen").checked,
      }),
    });
    setStatus(status, "Watch saved — re-scans every 6 hours while the app is running.");
    loadWatches();
  } catch (err) {
    setStatus(status, err.message, true);
  }
}

async function loadWatches() {
  try {
    const data = await api("/api/radar/watches");
    const list = $("#watch-list");
    const empty = $("#watch-empty");
    const watches = data.watches || [];
    list.innerHTML = "";
    empty.hidden = watches.length > 0;
    for (const w of watches) {
      const li = document.createElement("li");
      const last = w.last_run_at
        ? new Date(w.last_run_at * 1000).toLocaleString()
        : "never";
      li.innerHTML = `
        <div>
          <strong>${escapeHtml(w.offer || "").slice(0, 80)}</strong>
          <div class="muted">every ${escapeHtml(String(w.interval_hours))}h · last ${escapeHtml(last)}</div>
        </div>
        <span>
          <button type="button" class="btn ghost run-watch" data-id="${escapeHtml(w.id)}">Run now</button>
          <button type="button" class="btn ghost del-watch" data-id="${escapeHtml(w.id)}">Delete</button>
        </span>
      `;
      list.appendChild(li);
    }
    list.querySelectorAll(".run-watch").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await api(`/api/radar/watches/${btn.dataset.id}/run`, {
            method: "POST",
            body: "{}",
          });
          setStatus($("#radar-status"), "Watch run started…");
          startRadarClock();
          if (radarTimer) clearInterval(radarTimer);
          await pollRadar(res.job_id);
          radarTimer = setInterval(() => pollRadar(res.job_id), 1500);
        } catch (err) {
          setStatus($("#radar-status"), err.message, true);
        }
      });
    });
    list.querySelectorAll(".del-watch").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/radar/watches/${btn.dataset.id}`, { method: "DELETE" });
        loadWatches();
      });
    });
  } catch {
    /* ignore on first paint */
  }
}

/* ── Discover ───────────────────────────────────────── */

async function refreshDiscoverEstimate() {
  const target = Number($("#target-leads").value || 50);
  const params = new URLSearchParams({
    target_leads: String(target),
    reddit: String($("#src-reddit").checked),
    web: String($("#src-web").checked),
    github: String($("#src-github").checked),
    enrich_contacts: String($("#enrich-contacts").checked),
    scrape_sites: String($("#scrape-sites").checked),
    require_complete_contacts: String($("#require-complete").checked),
  });
  try {
    const est = await api(`/api/discover/estimate?${params}`);
    $("#discover-estimate").textContent = formatEstimateRange(
      est.estimate_low_seconds,
      est.estimate_high_seconds
    );
  } catch {
    const n = target;
    let low = 20 + n * 0.4;
    let high = 40 + n * 0.9;
    if ($("#scrape-sites").checked) {
      low += Math.min(n, 40) * 0.9;
      high += Math.min(n, 40) * 2;
    }
    if (!$("#enrich-contacts").checked) {
      low *= 0.45;
      high *= 0.45;
    }
    $("#discover-estimate").textContent = formatEstimateRange(low, high);
  }
}

function startDiscoverClock(estimateHigh = null) {
  discoverStartedAt = Date.now();
  const box = $("#discover-timer-box");
  const line = $("#discover-timer-line");
  box.hidden = false;
  box.classList.add("running");
  line.hidden = false;
  const tick = () => {
    const elapsed = (Date.now() - discoverStartedAt) / 1000;
    $("#discover-timer").textContent = formatDuration(elapsed);
    const estText = estimateHigh
      ? ` · est. up to ${formatDuration(estimateHigh)}`
      : "";
    line.textContent = `Timer ${formatDuration(elapsed)}${estText}`;
  };
  tick();
  if (discoverClockTimer) clearInterval(discoverClockTimer);
  discoverClockTimer = setInterval(tick, 250);
}

function stopDiscoverClock(finalSeconds = null) {
  if (discoverClockTimer) {
    clearInterval(discoverClockTimer);
    discoverClockTimer = null;
  }
  $("#discover-timer-box").classList.remove("running");
  const elapsed =
    finalSeconds != null
      ? finalSeconds
      : discoverStartedAt
        ? (Date.now() - discoverStartedAt) / 1000
        : 0;
  $("#discover-timer").textContent = formatDuration(elapsed);
  $("#discover-timer-line").hidden = false;
  $("#discover-timer-line").textContent = `Finished in ${formatDuration(elapsed)}`;
}

async function loadHealth() {
  const data = await api("/api/health");
  $("#version").textContent = `v${data.version}`;
  $("#proxy-pill").textContent = `proxy ${data.proxy}`;
}

const SECRET_FIELDS = [
  ["linkedin_cookie", "Paste li_at cookie"],
  ["hunter_api_key", "Email finder"],
  ["apollo_api_key", "People match"],
  ["firecrawl_api_key", "Site scrape upgrade"],
  ["openai_api_key", "Smarter outreach drafts"],
  ["anthropic_api_key", "Smarter outreach drafts"],
  ["google_places_api_key", "Business discovery"],
];

function renderProviderPills(providers = {}) {
  const host = $("#provider-pills");
  if (!host) return;
  const labels = {
    google_places: "Places",
    firecrawl: "Firecrawl",
    hunter: "Hunter",
    apollo: "Apollo",
    openai: "GPT",
    anthropic: "Claude",
    linkedin: "LinkedIn",
  };
  host.innerHTML = Object;
  for (const [key, label] of Object.entries(labels)) {
    const on = !!providers[key];
    const span = document.createElement("span");
    span.className = `provider-pill${on ? " on" : ""}`;
    span.textContent = on ? `${label} on` : `${label} off`;
    host.appendChild(span);
  }
}

async function loadSettings() {
  const s = await api("/api/settings");
  $("#proxy").value = s.proxy || "";
  $("#proxy_file").value = s.proxy_file || "";
  $("#free_proxy").checked = !!s.free_proxy;
  $("#delay_min").value = s.delay_min;
  $("#delay_max").value = s.delay_max;
  for (const [id, fallback] of SECRET_FIELDS) {
    const el = document.getElementById(id);
    if (!el) continue;
    const set = s[`${id}_set`];
    const preview = s[`${id}_preview`] || "";
    el.placeholder = set ? `Set (${preview})` : fallback;
    el.value = "";
  }
  $("#proxy-pill").textContent = `proxy ${s.proxy_status}`;
  renderProviderPills(s.providers || {});
}

async function saveSettings() {
  const status = $("#settings-status");
  try {
    const body = {
      proxy: $("#proxy").value.trim(),
      proxy_file: $("#proxy_file").value.trim(),
      free_proxy: $("#free_proxy").checked,
      delay_min: Number($("#delay_min").value),
      delay_max: Number($("#delay_max").value),
    };
    for (const [id] of SECRET_FIELDS) {
      const el = document.getElementById(id);
      const val = el ? el.value.trim() : "";
      if (val) body[id] = val;
    }

    await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
    for (const [id] of SECRET_FIELDS) {
      const el = document.getElementById(id);
      if (el) el.value = "";
    }
    await loadSettings();
    setStatus(status, "Settings saved. Active providers update on the next scan.");
  } catch (err) {
    setStatus(status, err.message, true);
  }
}

async function testProxy() {
  const status = $("#settings-status");
  try {
    const data = await api("/api/proxy/test", { method: "POST", body: "{}" });
    setStatus(status, data.ok ? `Proxy OK (${data.status})` : `Proxy failed (${data.status})`, !data.ok);
  } catch (err) {
    setStatus(status, err.message, true);
  }
}

async function loadExports() {
  const files = await api("/api/exports");
  const list = $("#exports-list");
  const empty = $("#exports-empty");
  list.innerHTML = "";
  empty.hidden = files.length > 0;
  for (const f of files) {
    const li = document.createElement("li");
    const kb = Math.max(1, Math.round(f.size / 1024));
    li.innerHTML = `
      <a href="/api/exports/${encodeURIComponent(f.name)}">${f.name}</a>
      <span>
        <span style="color:var(--muted);margin-right:0.75rem">${kb} KB</span>
        <button type="button" data-name="${f.name}">Delete</button>
      </span>
    `;
    li.querySelector("button").addEventListener("click", async () => {
      await api(`/api/exports/${encodeURIComponent(f.name)}`, { method: "DELETE" });
      loadExports();
    });
    list.appendChild(li);
  }
}

function renderJob(job) {
  $("#job-empty").hidden = true;
  $("#job-view").hidden = false;
  $("#job-platform").textContent = job.platform;
  const badge = $("#job-status");
  badge.textContent = job.status;
  badge.className = `badge ${job.status}`;
  $("#job-message").textContent = job.message || "";
  const pct = job.total ? Math.round((job.progress / job.total) * 100) : 0;
  $("#job-bar").style.width = `${pct}%`;
  $("#job-count").textContent = `${job.progress} / ${job.total}`;

  const tbody = $("#job-rows");
  tbody.innerHTML = "";
  for (const p of job.profiles || []) {
    const tr = document.createElement("tr");
    const name = p.full_name || p.name || "—";
    const handle = p.username || p.handle || "—";
    const email = p.email || "—";
    const score = p.lead_score ?? p.email_score ?? "—";
    tr.innerHTML = `<td>${escapeHtml(name)}</td><td>${escapeHtml(String(handle))}</td><td>${escapeHtml(String(email))}</td><td>${escapeHtml(String(score))}</td>`;
    tbody.appendChild(tr);
  }

  const dl = $("#download-btn");
  if (job.export_file) {
    dl.hidden = false;
    dl.href = `/api/exports/${encodeURIComponent(job.export_file)}`;
  } else {
    dl.hidden = true;
  }

  const errBox = $("#job-errors");
  if (job.errors && job.errors.length) {
    errBox.hidden = false;
    errBox.innerHTML = job.errors
      .map((e) => `<div>@${escapeHtml(e.username)} — ${escapeHtml(e.error)}</div>`)
      .join("");
  } else {
    errBox.hidden = true;
  }
}

async function pollJob(jobId) {
  const job = await api(`/api/jobs/${jobId}`);
  renderJob(job);
  if (job.status === "completed" || job.status === "failed") {
    clearInterval(pollTimer);
    pollTimer = null;
    $("#start-btn").disabled = false;
    setStatus($("#scrape-status"), job.message, job.status === "failed");
    loadExports();
    loadHealth();
  }
}

async function startScrape() {
  const status = $("#scrape-status");
  const raw = $("#usernames").value;
  const usernames = raw
    .split(/\r?\n|,/)
    .map((s) => s.trim())
    .filter(Boolean);

  if (!usernames.length) {
    setStatus(status, "Enter at least one username.", true);
    return;
  }

  try {
    $("#start-btn").disabled = true;
    setStatus(status, "Starting…");
    const data = await api("/api/scrape", {
      method: "POST",
      body: JSON.stringify({
        platform: $("#platform").value,
        usernames,
        enrich: $("#enrich").checked,
      }),
    });
    activeJobId = data.job_id;
    if (pollTimer) clearInterval(pollTimer);
    await pollJob(activeJobId);
    pollTimer = setInterval(() => pollJob(activeJobId), 1200);
  } catch (err) {
    $("#start-btn").disabled = false;
    setStatus(status, err.message, true);
  }
}

function renderDiscover(job) {
  $("#discover-results").hidden = false;
  const badge = $("#discover-badge");
  badge.textContent = job.status;
  badge.className = `badge ${job.status}`;
  $("#discover-message").textContent = job.message || "";
  const leads = job.leads || [];
  const stats = job.stats || {};
  const emailN = stats.with_email ?? leads.filter((l) => l.email).length;
  const phoneN = stats.with_phone ?? leads.filter((l) => l.phone).length;
  const target = job.target_leads || stats.target_leads || $("#target-leads").value;
  $("#discover-count").textContent = `${leads.length}/${target} leads · ${emailN} emails · ${phoneN} phones`;

  if (job.status === "running" || job.status === "queued") {
    if (job.elapsed_seconds != null) {
      $("#discover-timer").textContent = formatDuration(job.elapsed_seconds);
    }
    const high = job.estimate_high_seconds;
    $("#discover-timer-line").hidden = false;
    $("#discover-timer-line").textContent = high
      ? `Timer ${formatDuration(job.elapsed_seconds || 0)} · est. up to ${formatDuration(high)}`
      : `Timer ${formatDuration(job.elapsed_seconds || 0)}`;
  }

  const tbody = $("#discover-rows");
  tbody.innerHTML = "";
  for (const lead of leads.slice(0, 100)) {
    const tr = document.createElement("tr");
    const site = lead.website || "";
    const what = lead.what_they_do || lead.site_title || lead.evidence || "";
    tr.innerHTML = `
      <td>${escapeHtml(lead.username || "")}</td>
      <td>${escapeHtml(lead.platform || "")}</td>
      <td>${escapeHtml(lead.email || "—")}</td>
      <td>${escapeHtml(lead.phone || "—")}</td>
      <td>${site ? `<a href="${escapeHtml(site)}" target="_blank" rel="noopener">${escapeHtml(site.replace(/^https?:\/\//, "").slice(0, 28))}</a>` : "—"}</td>
      <td title="${escapeHtml(what)}">${escapeHtml(String(what).slice(0, 55))}</td>
      <td>${escapeHtml(String(lead.interest_score ?? ""))}</td>
    `;
    tbody.appendChild(tr);
  }

  const actions = $("#discover-actions");
  actions.innerHTML = "";
  const byPlatform = job.by_platform || {};
  for (const [platform, users] of Object.entries(byPlatform)) {
    if (!users.length) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn ghost";
    btn.textContent = `Send ${users.length} → ${platform} scrape`;
    btn.addEventListener("click", () => {
      $("#platform").value = platform;
      $("#usernames").value = users.join("\n");
      setStatus($("#discover-status"), `Loaded ${users.length} ${platform} handles into scrape form.`);
      $("#usernames").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    actions.appendChild(btn);
  }
  if (job.files && job.files.master_csv) {
    const a = document.createElement("a");
    a.className = "btn ghost";
    a.href = `/api/exports/${encodeURIComponent(job.files.master_csv)}`;
    a.textContent = "Download full CSV";
    actions.appendChild(a);
  }
  if (job.files && job.files.contacts_csv) {
    const a = document.createElement("a");
    a.className = "btn primary";
    a.href = `/api/exports/${encodeURIComponent(job.files.contacts_csv)}`;
    a.textContent = "Download contacts CSV";
    actions.appendChild(a);
  }
}

async function pollDiscover(jobId) {
  const job = await api(`/api/discover/${jobId}`);
  lastDiscover = job;
  renderDiscover(job);
  if (job.status === "completed" || job.status === "failed") {
    clearInterval(discoverTimer);
    discoverTimer = null;
    stopDiscoverClock(job.elapsed_seconds);
    $("#discover-btn").disabled = false;
    setStatus($("#discover-status"), job.message, job.status === "failed");
    loadExports();
  }
}

async function startDiscover() {
  const status = $("#discover-status");
  const topic = $("#topic").value.trim();
  if (topic.length < 2) {
    setStatus(status, "Enter a topic / niche.", true);
    return;
  }
  const sources = selectedSources();
  if (!sources.length) {
    setStatus(status, "Pick at least one source.", true);
    return;
  }

  const targetLeads = Number($("#target-leads").value || 50);

  try {
    $("#discover-btn").disabled = true;
    setStatus(status, `Searching for up to ${targetLeads} leads…`);
    const data = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({
        topic,
        company: $("#company").value.trim(),
        sources,
        target_leads: targetLeads,
        max_per_query: Math.min(100, Math.max(20, Math.round(targetLeads / 2))),
        enrich_contacts: $("#enrich-contacts").checked,
        scrape_sites: $("#scrape-sites").checked,
        require_complete_contacts: $("#require-complete").checked,
      }),
    });
    if (data.estimate_low_seconds && data.estimate_high_seconds) {
      $("#discover-estimate").textContent = formatEstimateRange(
        data.estimate_low_seconds,
        data.estimate_high_seconds
      );
    }
    startDiscoverClock(data.estimate_high_seconds);
    if (discoverTimer) clearInterval(discoverTimer);
    await pollDiscover(data.job_id);
    discoverTimer = setInterval(() => pollDiscover(data.job_id), 1500);
  } catch (err) {
    $("#discover-btn").disabled = false;
    stopDiscoverClock();
    setStatus(status, err.message, true);
  }
}

["target-leads", "src-reddit", "src-web", "src-github", "enrich-contacts", "scrape-sites", "require-complete"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", refreshDiscoverEstimate);
});

// Keep options coherent: complete contacts need enrichment + site scrape
const requireCompleteEl = document.getElementById("require-complete");
if (requireCompleteEl) {
  requireCompleteEl.addEventListener("change", () => {
    if (requireCompleteEl.checked) {
      $("#enrich-contacts").checked = true;
      $("#scrape-sites").checked = true;
    }
    refreshDiscoverEstimate();
  });
}
document.getElementById("enrich-contacts")?.addEventListener("change", () => {
  if (!$("#enrich-contacts").checked) {
    $("#require-complete").checked = false;
    $("#scrape-sites").checked = false;
  }
  refreshDiscoverEstimate();
});
document.getElementById("scrape-sites")?.addEventListener("change", () => {
  if ($("#scrape-sites").checked) {
    $("#enrich-contacts").checked = true;
  } else {
    $("#require-complete").checked = false;
  }
  refreshDiscoverEstimate();
});
["radar-target", "radar-sites", "radar-deepen"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", refreshRadarEstimate);
});

$("#tab-radar").addEventListener("click", () => switchMode("radar"));
$("#tab-discover").addEventListener("click", () => switchMode("discover"));
$("#radar-btn").addEventListener("click", startRadar);
$("#radar-watch-btn").addEventListener("click", saveWatch);
$("#start-btn").addEventListener("click", startScrape);
$("#discover-btn").addEventListener("click", startDiscover);
$("#save-settings").addEventListener("click", saveSettings);
$("#test-proxy").addEventListener("click", testProxy);

(async function init() {
  try {
    await Promise.all([
      loadHealth(),
      loadSettings(),
      loadExports(),
      refreshDiscoverEstimate(),
      refreshRadarEstimate(),
      loadWatches(),
    ]);
  } catch (err) {
    console.error(err);
    setStatus($("#radar-status"), `Failed to load: ${err.message}`, true);
  }
})();
