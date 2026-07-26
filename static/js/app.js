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
      <div class="solve-row">
        <button type="button" class="btn ghost solve-btn">Solve this</button>
        <button type="button" class="btn ghost variants-btn">A/B variants</button>
      </div>
      <div class="solve-mount" hidden></div>
      <div class="variants-mount" hidden></div>
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
    const solveBtn = card.querySelector(".solve-btn");
    const solveMount = card.querySelector(".solve-mount");
    if (solveBtn && solveMount) {
      if (lead.ask_id) {
        solveBtn.addEventListener("click", () =>
          solveSingleAsk(lead.ask_id, solveMount, solveBtn)
        );
      } else {
        solveBtn.disabled = true;
        solveBtn.title = "This ask has no stored id to solve against";
      }
    }
    const varBtn = card.querySelector(".variants-btn");
    const varMount = card.querySelector(".variants-mount");
    if (varBtn && varMount && lead.ask_id) {
      varBtn.addEventListener("click", () =>
        loadVariants(lead.ask_id, varMount, varBtn)
      );
    }

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

/* ── Masonry layout ─────────────────────────────────── */

let masonryPanels = null;
let masonryCols = 0;
let masonryTimer = null;

function masonryColumnCount(width) {
  if (width >= 1500) return 3;
  if (width >= 900) return 2;
  return 1;
}

/**
 * Place each panel in whichever column is currently shortest. CSS multi-column
 * balances by height and leaves a void under the short column, so we pack
 * manually. Panels keep their listeners because the nodes are moved, not cloned.
 */
function layoutMasonry() {
  const host = $(".panel-columns");
  if (!host) return;
  if (!masonryPanels) {
    masonryPanels = Array.from(host.children).filter((el) =>
      el.classList.contains("panel")
    );
  }
  masonryCols = masonryColumnCount(host.clientWidth);

  const cols = masonryCols;
  const columns = [];
  host.textContent = "";
  for (let i = 0; i < cols; i += 1) {
    const col = document.createElement("div");
    col.className = "mcol";
    host.appendChild(col);
    columns.push(col);
  }
  for (const panel of masonryPanels) {
    let shortest = columns[0];
    for (const col of columns) {
      if (col.offsetHeight < shortest.offsetHeight) shortest = col;
    }
    shortest.appendChild(panel);
  }
}

function scheduleMasonry() {
  clearTimeout(masonryTimer);
  masonryTimer = setTimeout(layoutMasonry, 120);
}

/* ── AI engine ──────────────────────────────────────── */

let aiMode = "heuristic";

async function loadAiStatus() {
  try {
    const s = await api("/api/ai/status");
    aiMode = s.mode || "heuristic";
    const pill = $("#ai-mode-pill");
    if (pill) {
      pill.textContent = s.generative ? `${aiMode} · generative` : "free heuristic mode";
      pill.classList.toggle("generative", !!s.generative);
    }
  } catch {
    /* non-fatal */
  }
}

function offerContext() {
  return {
    offer: ($("#radar-offer").value || "").trim(),
    niche: ($("#radar-niche").value || "").trim(),
  };
}

function chip(text, cls = "stat-chip") {
  const el = document.createElement("span");
  el.className = cls;
  el.innerHTML = text;
  return el;
}

function renderBrief(b) {
  $("#ai-brief").hidden = false;
  const score = Number(b.demand_score || 0);
  $("#ai-score").textContent = score;
  $("#ai-score-ring").style.setProperty("--pct", String(score));
  $("#ai-verdict").textContent = b.verdict || "—";
  $("#ai-reasoning").textContent = b.reasoning || "";

  const st = b.stats || {};
  const chips = $("#ai-stat-chips");
  chips.innerHTML = "";
  [
    [`<b>${st.total ?? 0}</b> asks analysed`],
    [`<b>${st.zero_reply ?? 0}</b> zero-reply`],
    [`<b>${st.fresh_7d ?? 0}</b> from last 7d`],
    [`<b>${st.contactable ?? 0}</b> reachable`],
    [`avg silence <b>${st.avg_silence ?? 0}</b>`],
  ].forEach(([html]) => chips.appendChild(chip(html)));

  const cl = $("#ai-clusters");
  cl.innerHTML = "";
  for (const c of b.clusters || []) {
    const row = document.createElement("div");
    row.className = "cluster-row";
    const ex = (c.examples || [])[0];
    row.innerHTML = `
      <div class="cluster-head">
        <span class="cluster-theme">${escapeHtml(c.theme || "")}</span>
        <span class="cluster-meta">${c.count} asks · ${c.share}% · silence ${c.avg_silence}</span>
      </div>
      <div class="cluster-bar"><i style="width:${Math.max(3, Number(c.share) || 0)}%"></i></div>
      ${ex && ex.quote ? `<p class="cluster-example">“${escapeHtml(ex.quote)}”</p>` : ""}
    `;
    cl.appendChild(row);
  }
  if (!(b.clusters || []).length) {
    cl.innerHTML = `<p class="empty">No clusters yet — run a Demand Radar scan first.</p>`;
  }

  const voc = $("#ai-voc");
  voc.innerHTML = "";
  for (const v of b.voice_of_customer || []) voc.appendChild(chip(escapeHtml(v), "voc-chip"));
  if (!(b.voice_of_customer || []).length) {
    voc.innerHTML = `<span class="empty">No quotes captured yet.</span>`;
  }

  const pains = $("#ai-pains");
  pains.innerHTML = "";
  for (const p of b.top_pains || []) {
    const li = document.createElement("li");
    li.innerHTML =
      `${p.frequency ? `<span class="pain-freq">${p.frequency}x</span>` : ""}` +
      `<strong>${escapeHtml(p.pain || "")}</strong>` +
      `${p.evidence ? `<em>“${escapeHtml(p.evidence)}”</em>` : ""}`;
    pains.appendChild(li);
  }

  const acts = $("#ai-actions-list");
  acts.innerHTML = "";
  for (const a of b.next_actions || []) {
    const li = document.createElement("li");
    li.appendChild(document.createTextNode(a));
    acts.appendChild(li);
  }

  const risk = $("#ai-risk");
  if (b.riskiest_assumption) {
    risk.hidden = false;
    risk.textContent = `Riskiest assumption: ${b.riskiest_assumption}`;
  } else {
    risk.hidden = true;
  }
}

async function runCockpit() {
  const status = $("#ai-status");
  const btn = $("#ai-cockpit-btn");
  try {
    btn.disabled = true;
    setStatus(status, "Running full intelligence suite (match · graph · personas · forecast · memory)…");
    const data = await api("/api/ai/cockpit", {
      method: "POST",
      body: JSON.stringify({ ...offerContext(), limit: 150 }),
    });
    renderCockpit(data);
    // Also hydrate the classic brief block from cockpit.brief
    if (data.brief) {
      renderBrief({
        ...data.brief,
        stats: data.stats,
        clusters: data.clusters,
        source: data.source,
        demand_score: data.brief.demand_score ?? data.stats?.demand_score,
      });
    }
    setStatus(status, `Cockpit ready (${data.source} · ${(data.capabilities || []).length} capabilities).`);
    scheduleMasonry();
  } catch (err) {
    setStatus(status, err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function renderCockpit(data) {
  $("#ai-cockpit").hidden = false;

  const strip = $("#ai-algo-strip");
  strip.innerHTML = "";
  for (const a of data.capabilities || []) {
    const el = document.createElement("span");
    el.className = "algo-chip";
    el.textContent = a.replace(/_/g, " ");
    strip.appendChild(el);
  }

  const score = Number(data.stats?.demand_score || data.brief?.demand_score || 0);
  $("#ai-cockpit-score").textContent = score;
  $("#ai-cockpit-score-ring").style.setProperty("--pct", String(score));
  $("#ai-cockpit-verdict").textContent = data.brief?.verdict || "—";
  $("#ai-cockpit-reasoning").textContent = data.brief?.reasoning || "";

  const chips = $("#ai-cockpit-chips");
  chips.innerHTML = "";
  const st = data.stats || {};
  const m = data.match || {};
  [
    [`<b>${st.total ?? 0}</b> asks`],
    [`top fit <b>${m.top_fit ?? 0}</b>`],
    [`<b>${m.decision_ready ?? 0}</b> decision-stage`],
    [`<b>${m.hire_intent ?? 0}</b> hire intent`],
    [`trend <b>${data.forecast?.trend || "—"}</b>`],
  ].forEach(([html]) => chips.appendChild(chip(html)));

  // Ranked matches
  const ranked = $("#ai-ranked");
  ranked.innerHTML = "";
  const ms = $("#ai-match-summary");
  ms.innerHTML = "";
  if (!(data.ranked || []).length) {
    ms.innerHTML = `<span class="empty">Enter an offer above, then re-run — BM25 needs something to match against.</span>`;
  } else {
    ms.appendChild(chip(`avg fit <b>${m.avg_fit ?? 0}</b>`));
    ms.appendChild(chip(`contactable in top 10: <b>${m.contactable_top ?? 0}</b>`));
    for (const r of (data.ranked || []).slice(0, 8)) {
      const row = document.createElement("div");
      row.className = "ranked-row";
      row.innerHTML =
        `<span class="fit-pill">${r.fit_score}% fit</span>` +
        `<span class="intent-pill">${escapeHtml(r.intent || "")}</span>` +
        `<span class="stage-pill">${escapeHtml(r.buying_stage || "")}</span>` +
        `<span class="odds-pill">${r.reply_odds}% reply odds</span>` +
        `<div style="margin-top:0.35rem"><strong>${escapeHtml(r.username || "")}</strong> — “${escapeHtml(r.quote || "")}”</div>`;
      ranked.appendChild(row);
    }
  }

  // Intel
  const il = $("#ai-intel-list");
  il.innerHTML = "";
  for (const p of (data.intel || []).slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "intel-row";
    row.innerHTML =
      `<span class="fit-pill">prio ${p.priority_score}</span>` +
      `<span class="intent-pill">${escapeHtml(p.intent)}</span>` +
      `<span class="stage-pill">${escapeHtml(p.buying_stage)}</span>` +
      `<span class="odds-pill">${p.urgency_label} urgency · ${p.reply_odds}% odds</span>` +
      `<div style="margin-top:0.3rem">“${escapeHtml(p.quote || "")}”</div>`;
    il.appendChild(row);
  }
  if (!(data.intel || []).length) {
    il.innerHTML = `<p class="empty">No asks to score yet.</p>`;
  }

  // Graph
  $("#ai-graph-insight").textContent = data.graph?.insight || "";
  const hubs = $("#ai-graph-hubs");
  hubs.innerHTML = "";
  for (const h of data.graph?.hubs || []) hubs.appendChild(chip(escapeHtml(h), "voc-chip"));
  for (const b of data.graph?.bridges || []) {
    const el = chip(escapeHtml(`bridge: ${b}`), "voc-chip");
    hubs.appendChild(el);
  }

  // Personas
  const pl = $("#ai-personas");
  pl.innerHTML = "";
  for (const p of data.personas || []) {
    const row = document.createElement("div");
    row.className = "persona-row";
    row.innerHTML =
      `<strong>${escapeHtml(p.name)}</strong> ` +
      `<span class="muted">${p.count} asks · ${p.share}% · urgency ${p.avg_urgency}</span>` +
      `<div style="margin-top:0.3rem">${escapeHtml(p.how_to_win || "")}</div>` +
      (p.example ? `<em style="display:block;margin-top:0.25rem;color:var(--muted)">“${escapeHtml(p.example)}”</em>` : "");
    pl.appendChild(row);
  }

  // Objections
  const ol = $("#ai-objections");
  ol.innerHTML = "";
  for (const o of data.objections || []) {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="pain-freq">${o.share}%</span>` +
      `<strong>${escapeHtml(o.objection)}</strong> (${o.count}x)` +
      `<em>${escapeHtml(o.counter || "")}</em>`;
    ol.appendChild(li);
  }
  if (!(data.objections || []).length) {
    ol.innerHTML = `<li class="empty">No recurring objections detected yet.</li>`;
  }

  // Forecast
  const fc = data.forecast || {};
  const fHost = $("#ai-forecast");
  fHost.innerHTML = "";
  const trend = document.createElement("div");
  trend.className = "trend";
  trend.textContent = (fc.trend || "unknown").replace(/_/g, " ");
  fHost.appendChild(trend);
  const fHint = document.createElement("p");
  fHint.className = "hint";
  fHint.textContent = fc.insight || "";
  fHost.appendChild(fHint);
  const fMetrics = document.createElement("div");
  fMetrics.className = "forecast-metrics";
  [
    [`7d <b>${fc.projected_7d ?? 0}</b>`],
    [`14d <b>${fc.projected_14d ?? 0}</b>`],
    [`30d <b>${fc.projected_30d ?? 0}</b>`],
    [`slope <b>${fc.slope_per_day ?? 0}</b>/day`],
    [`conf <b>${fc.confidence ?? 0}</b>%`],
  ].forEach(([html]) => fMetrics.appendChild(chip(html)));
  fHost.appendChild(fMetrics);

  // Memory
  const mem = data.memory || {};
  const mHost = $("#ai-memory");
  mHost.innerHTML = "";
  const mHint = document.createElement("p");
  mHint.className = "hint";
  mHint.textContent = mem.tagged
    ? `Tagged ${mem.tagged} · wins ${mem.wins} · losses ${mem.losses} · win rate ${mem.win_rate}%`
    : "No tagged outcomes yet — mark asks as booked / replied / ignored to train the outcome RAG loop.";
  mHost.appendChild(mHint);
  if (mem.top_win_words?.length) {
    const wrap = document.createElement("div");
    wrap.className = "voc-chips";
    wrap.style.marginTop = "0.4rem";
    for (const w of mem.top_win_words) wrap.appendChild(chip(escapeHtml(w), "voc-chip"));
    mHost.appendChild(wrap);
  }
}

async function runBrief() {
  const status = $("#ai-status");
  const btn = $("#ai-brief-btn");
  try {
    btn.disabled = true;
    setStatus(status, "Synthesising demand verdict…");
    const b = await api("/api/ai/brief", {
      method: "POST",
      body: JSON.stringify({ ...offerContext(), limit: 150 }),
    });
    renderBrief(b);
    setStatus(status, `Verdict ready (${b.source} mode).`);
  } catch (err) {
    setStatus(status, err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function renderOfferDoctor(d) {
  $("#ai-offer").hidden = false;
  const score = Number(d.score || 0);
  $("#ai-offer-score").textContent = score;
  $("#ai-offer-bar").style.width = `${score}%`;

  const probs = $("#ai-offer-problems");
  probs.innerHTML = "";
  for (const p of d.problems || []) {
    const li = document.createElement("li");
    li.textContent = p;
    probs.appendChild(li);
  }

  const wrap = $("#ai-offer-rewrite-wrap");
  if (d.rewrite) {
    wrap.hidden = false;
    $("#ai-offer-rewrite").textContent = d.headline ? `${d.headline} — ${d.rewrite}` : d.rewrite;
  } else {
    wrap.hidden = true;
  }

  const use = $("#ai-words-use");
  use.innerHTML = "";
  for (const w of d.words_to_use || []) use.appendChild(chip(escapeHtml(w), "voc-chip"));

  const drop = $("#ai-words-drop");
  drop.innerHTML = "";
  for (const w of d.jargon_to_drop || []) drop.appendChild(chip(escapeHtml(w), "voc-chip"));
}

async function runOfferDoctor() {
  const status = $("#ai-status");
  const btn = $("#ai-offer-btn");
  const offer = ($("#radar-offer").value || "").trim();
  if (offer.length < 3) {
    setStatus(status, "Enter your offer in the Demand Radar box first.", true);
    return;
  }
  try {
    btn.disabled = true;
    setStatus(status, "Diagnosing offer against buyer language…");
    const d = await api("/api/ai/offer-doctor", {
      method: "POST",
      body: JSON.stringify({ offer, limit: 150 }),
    });
    if (d.error) throw new Error(d.error);
    renderOfferDoctor(d);
    setStatus(status, `Offer diagnosed (${d.source} mode).`);
  } catch (err) {
    setStatus(status, err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function solutionCard(entry) {
  const s = entry.solution || entry;
  const intel = s.intel || {};
  const card = document.createElement("article");
  card.className = "solution-card";
  const steps = (s.steps || [])
    .map((st) => `<li><span><b>${escapeHtml(st.do || "")}</b> ${escapeHtml(st.how || "")}</span></li>`)
    .join("");
  const intelPills = intel.intent
    ? `<span class="intent-pill">${escapeHtml(intel.intent)}</span>` +
      `<span class="stage-pill">${escapeHtml(intel.buying_stage || "")}</span>` +
      `<span class="odds-pill">${intel.reply_odds ?? "—"}% odds</span>`
    : "";
  card.innerHTML = `
    <div class="sol-head">
      <span class="sol-conf">${Number(s.confidence || 0)}% confident</span>
      ${entry.username ? `<span>u/${escapeHtml(entry.username)}</span>` : ""}
      ${s.difficulty ? `<span>${escapeHtml(s.difficulty)}</span>` : ""}
      ${s.time_estimate ? `<span>${escapeHtml(s.time_estimate)}</span>` : ""}
      <span>${escapeHtml(s.source || "")}</span>
      ${intelPills}
    </div>
    ${s.diagnosis ? `<p class="sol-diag">${escapeHtml(s.diagnosis)}</p>` : ""}
    ${steps ? `<ol class="sol-steps">${steps}</ol>` : ""}
  `;
  if (s.deliverable) {
    const d = document.createElement("details");
    d.className = "draft";
    d.innerHTML = `<summary>Deliverable they can use</summary><pre></pre><button type="button" class="btn ghost copy-btn">Copy</button>`;
    d.querySelector("pre").textContent = s.deliverable;
    d.querySelector(".copy-btn").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(s.deliverable);
        d.querySelector(".copy-btn").textContent = "Copied";
        setTimeout(() => { d.querySelector(".copy-btn").textContent = "Copy"; }, 1200);
      } catch { /* ignore */ }
    });
    card.appendChild(d);
  }
  if (s.helpful_note) {
    const d = document.createElement("details");
    d.className = "draft";
    d.innerHTML = `<summary>Help-first note to send</summary><pre></pre><button type="button" class="btn ghost copy-btn">Copy</button>`;
    d.querySelector("pre").textContent = s.helpful_note;
    d.querySelector(".copy-btn").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(s.helpful_note);
        d.querySelector(".copy-btn").textContent = "Copied";
        setTimeout(() => { d.querySelector(".copy-btn").textContent = "Copy"; }, 1200);
      } catch { /* ignore */ }
    });
    card.appendChild(d);
  }
  if (s.error) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = s.error;
    card.appendChild(p);
  }
  return card;
}

async function runSolveBatch() {
  const status = $("#ai-status");
  const btn = $("#ai-solve-btn");
  try {
    btn.disabled = true;
    setStatus(status, "Solving the loudest silent asks…");
    const res = await api("/api/ai/solve-batch", {
      method: "POST",
      body: JSON.stringify({ ...offerContext(), limit: 5, only_zero_reply: true }),
    });
    const host = $("#ai-solution-list");
    host.innerHTML = "";
    for (const entry of res.solutions || []) host.appendChild(solutionCard(entry));
    if (!(res.solutions || []).length) {
      host.innerHTML = `<p class="empty">No stored asks yet — run a Demand Radar scan first.</p>`;
    }
    $("#ai-solutions").hidden = false;
    setStatus(status, `Solved ${res.count} ask${res.count === 1 ? "" : "s"}.`);
  } catch (err) {
    setStatus(status, err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function solveSingleAsk(askId, mount, button) {
  try {
    button.disabled = true;
    button.textContent = "Solving…";
    const res = await api("/api/ai/solve", {
      method: "POST",
      body: JSON.stringify({ ask_id: askId, ...offerContext() }),
    });
    mount.innerHTML = "";
    mount.appendChild(solutionCard(res));
    mount.hidden = false;
    button.textContent = "Re-solve";
  } catch (err) {
    mount.hidden = false;
    mount.innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
    button.textContent = "Solve this";
  } finally {
    button.disabled = false;
  }
}

async function loadVariants(askId, mount, button) {
  try {
    button.disabled = true;
    button.textContent = "Scoring…";
    const res = await api("/api/ai/variants", {
      method: "POST",
      body: JSON.stringify({ ask_id: askId, n: 4, ...offerContext() }),
    });
    mount.innerHTML = "";
    const list = document.createElement("div");
    list.className = "variant-list";
    for (const v of res.variants || []) {
      const card = document.createElement("div");
      card.className = "variant-card";
      card.innerHTML =
        `<div class="sol-head">` +
        `<span class="ev">EV ${v.ev_score}</span>` +
        `<span>${escapeHtml(v.angle || "")}</span>` +
        `<span>${escapeHtml(v.channel || "")}</span>` +
        `</div>` +
        (v.subject ? `<strong>${escapeHtml(v.subject)}</strong>` : "") +
        `<pre style="white-space:pre-wrap;margin:0.4rem 0 0;font-family:inherit;font-size:0.88rem"></pre>` +
        `<p class="muted" style="margin:0.35rem 0 0">${escapeHtml(v.why_it_works || "")}</p>` +
        `<button type="button" class="btn ghost copy-btn" style="margin-top:0.4rem">Copy</button>`;
      card.querySelector("pre").textContent = v.body || "";
      card.querySelector(".copy-btn").addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(v.body || "");
          card.querySelector(".copy-btn").textContent = "Copied";
          setTimeout(() => { card.querySelector(".copy-btn").textContent = "Copy"; }, 1200);
        } catch { /* ignore */ }
      });
      list.appendChild(card);
    }
    mount.appendChild(list);
    mount.hidden = false;
    button.textContent = "Re-score variants";
  } catch (err) {
    mount.hidden = false;
    mount.innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
    button.textContent = "A/B variants";
  } finally {
    button.disabled = false;
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
  host.innerHTML = "";
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
$("#ai-cockpit-btn").addEventListener("click", runCockpit);
$("#ai-brief-btn").addEventListener("click", runBrief);
$("#ai-solve-btn").addEventListener("click", runSolveBatch);
$("#ai-offer-btn").addEventListener("click", runOfferDoctor);

(async function init() {
  try {
    await Promise.all([
      loadHealth(),
      loadSettings(),
      loadExports(),
      refreshDiscoverEstimate(),
      refreshRadarEstimate(),
      loadWatches(),
      loadAiStatus(),
    ]);
    scheduleMasonry();
  } catch (err) {
    console.error(err);
    setStatus($("#radar-status"), `Failed to load: ${err.message}`, true);
  }

  // Panel heights change as exports load, jobs stream and watches render —
  // re-pack whenever any of them resizes.
  window.addEventListener("resize", scheduleMasonry);
  const host = $(".panel-columns");
  if (host && "ResizeObserver" in window) {
    const ro = new ResizeObserver(scheduleMasonry);
    for (const panel of Array.from(host.querySelectorAll(".panel"))) ro.observe(panel);
  }
})();
