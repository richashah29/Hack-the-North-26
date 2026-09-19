(() => {
  const canvas = document.getElementById("map");
  const tooltip = document.getElementById("tooltip");
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const githubInput = document.getElementById("ask-github");
  const devpostInput = document.getElementById("ask-devpost");
  const askStatus = document.getElementById("ask-status");
  const askBtn = document.getElementById("ask-btn");
  const neighbourList = document.getElementById("neighbour-list");
  const neighboursEmpty = document.getElementById("neighbours-empty");
  const tracksPanel = document.getElementById("tracks-panel");
  const trackList = document.getElementById("track-list");
  const tracksEmpty = document.getElementById("tracks-empty");
  const tracksMethod = document.getElementById("tracks-method");
  const trackFilters = document.getElementById("track-filters");
  let tracksPayload = null;
  let trackFilter = "all";
  const probPanel = document.getElementById("prob-panel");
  const probNum = document.getElementById("prob-num");
  const probMeta = document.getElementById("prob-meta");
  const corpusMeta = document.getElementById("corpus-meta");
  const chartsEl = document.getElementById("charts");
  const findingsNote = document.getElementById("findings-note");
  const coachPanel = document.getElementById("coach-panel");
  const coachBtn = document.getElementById("coach-btn");
  const coachStatus = document.getElementById("coach-status");
  const coachList = document.getElementById("coach-list");
  const timeToggle = document.getElementById("coach-time-on");
  const coachTime = document.getElementById("coach-time");
  const coachHours = document.getElementById("coach-hours");
  const budgetInput = document.getElementById("coach-budget");
  let lastCoach = null;
  let budgetTouched = false;
  let askInFlight = false;
  let coachInFlight = false;

  const ACCENT = "#e8a317";
  const MUTE = "#3c3c42";
  const YOU = "#f4f0ea";

  let mapData = { points: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
  let query = null;
  let hover = null;
  let pulse = 0;
  let raf = 0;
  let lastIdeaText = "";
  let ghost = null;
  let ghostRaf = 0;

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    draw();
  }

  function project(pt) {
    const b = mapData.bounds;
    const pad = 36;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const x = pad + ((pt.x - b.x0) / (b.x1 - b.x0 || 1)) * (w - pad * 2);
    const y = pad + (1 - (pt.y - b.y0) / (b.y1 - b.y0 || 1)) * (h - pad * 2);
    return { x, y };
  }

  function hitTest(mx, my) {
    const pts = mapData.points;
    let best = null;
    let bestD = 12;
    for (const p of pts) {
      const s = project(p);
      const d = Math.hypot(s.x - mx, s.y - my);
      const rr = radii();
      const r = p.finalist ? rr.finalist + 4 : rr.mute + 4;
      if (d < Math.max(bestD, r + 3)) {
        best = p;
        bestD = d;
      }
    }
    if (query && query.point) {
      const s = project(query.point);
      if (Math.hypot(s.x - mx, s.y - my) < 14) best = { ...query.point, title: "Your idea", year: "", you: true };
    }
    return best;
  }

  function radii() {
    const n = mapData.points.length || 1;
    if (n > 400) return { mute: 2.2, finalist: 4, neighbour: 6 };
    if (n > 80) return { mute: 3.4, finalist: 6, neighbour: 8 };
    return { mute: 6, finalist: 9, neighbour: 11 };
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const r = radii();
    const muteFill = mapData.points.length > 200 ? MUTE : "#8a8883";

    const neighbourSlugs = new Set((query?.neighbours || []).map((n) => n.slug));

    for (const p of mapData.points) {
      if (p.finalist || neighbourSlugs.has(p.slug)) continue;
      const s = project(p);
      ctx.fillStyle = muteFill;
      ctx.beginPath();
      ctx.arc(s.x, s.y, r.mute, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const p of mapData.points) {
      if (!p.finalist) continue;
      const s = project(p);
      ctx.fillStyle = ACCENT;
      ctx.beginPath();
      ctx.arc(s.x, s.y, neighbourSlugs.has(p.slug) ? r.neighbour : r.finalist, 0, Math.PI * 2);
      ctx.fill();
    }

    if (query && query.point) {
      const origin = project(query.point);
      ctx.strokeStyle = "rgba(232,163,23,0.45)";
      ctx.lineWidth = 1;
      for (const n of query.neighbours) {
        const p = mapData.points.find((x) => x.slug === n.slug);
        if (!p) continue;
        const t = project(p);
        ctx.beginPath();
        ctx.moveTo(origin.x, origin.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
        ctx.strokeStyle = ACCENT;
        ctx.beginPath();
        ctx.arc(t.x, t.y, 7, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = "rgba(232,163,23,0.45)";
      }

      const r = 10 + pulse * 18;
      ctx.strokeStyle = `rgba(244,240,234,${1 - pulse})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, r, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = YOU;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, 5, 0, Math.PI * 2);
      ctx.fill();
    }

    if (ghost && ghost.from && ghost.to && query && query.point) {
      const a = project(ghost.from);
      const b = project(ghost.to);
      const t = ghost.t;
      const gx = a.x + (b.x - a.x) * t;
      const gy = a.y + (b.y - a.y) * t;
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = "rgba(244,240,234,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(gx, gy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(244,240,234,0.2)";
      ctx.strokeStyle = YOU;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(gx, gy, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }

  function tick() {
    if (query && pulse < 1) {
      pulse = Math.min(1, pulse + 0.03);
      draw();
      raf = requestAnimationFrame(tick);
    }
  }

  function showTooltip(p, ev) {
    if (!p) {
      tooltip.hidden = true;
      return;
    }
    tooltip.hidden = false;
    tooltip.textContent = p.you ? "Your idea" : `${p.title}  ·  ${p.year}`;
    const rect = canvas.getBoundingClientRect();
    tooltip.style.left = `${ev.clientX - rect.left}px`;
    tooltip.style.top = `${ev.clientY - rect.top}px`;
  }

  canvas.addEventListener("mousemove", (ev) => {
    const rect = canvas.getBoundingClientRect();
    hover = hitTest(ev.clientX - rect.left, ev.clientY - rect.top);
    canvas.style.cursor = hover ? "crosshair" : "default";
    showTooltip(hover, ev);
  });
  canvas.addEventListener("mouseleave", () => {
    hover = null;
    tooltip.hidden = true;
  });

  function renderNeighbours(items) {
    neighbourList.innerHTML = "";
    if (!items || !items.length) {
      neighboursEmpty.hidden = false;
      return;
    }
    neighboursEmpty.hidden = true;
    for (const n of items) {
      const li = document.createElement("li");
      li.className = "card" + (n.finalist ? " is-hit" : "");
      const title = n && n.title != null ? String(n.title) : "";
      const tagline = n && n.tagline != null ? String(n.tagline) : "";
      const year = n && n.year != null && n.year !== "" ? String(n.year) : "";
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(title)}</span>
          <span class="card-year">${escapeHtml(year)}</span>
        </div>
        <p class="card-tag">${escapeHtml(tagline)}</p>
        ${n.finalist ? '<div class="badge">Finalist</div>' : ""}
      `;
      neighbourList.appendChild(li);
    }
  }

  function clearGhost() {
    ghost = null;
    cancelAnimationFrame(ghostRaf);
    draw();
  }

  function playGhost(move) {
    if (!query || !query.point || !move || !move.new_point) return;
    ghost = { from: query.point, to: move.new_point, t: 0 };
    cancelAnimationFrame(ghostRaf);
    const step = () => {
      if (!ghost) return;
      ghost.t = Math.min(1, ghost.t + 0.07);
      draw();
      if (ghost.t < 1) ghostRaf = requestAnimationFrame(step);
    };
    ghostRaf = requestAnimationFrame(step);
  }

  function timeAwareOn() {
    return !!(timeToggle && timeToggle.checked);
  }

  function formatDelta(delta) {
    const pct = (Number(delta) || 0) * 100;
    const tenths = Math.round(pct * 10) / 10;
    const abs = Math.abs(tenths);
    const body = Number.isInteger(abs) ? String(abs) : abs.toFixed(1);
    if (tenths > 0) return `+${body}%`;
    if (tenths < 0) return `-${body}%`;
    return "0%";
  }

  function setCoachOpen(open) {
    const rail = document.querySelector(".rail");
    if (coachPanel) coachPanel.hidden = !open;
    if (rail) rail.classList.toggle("has-coach", !!open);
  }

  function formatHoursLeft(hours) {
    const n = Math.max(0, Number(hours) || 0);
    const shown = Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1);
    return `~${shown}h left in the build window`;
  }

  function formatEffort(hours) {
    const n = Math.max(0, Number(hours) || 0);
    const shown = Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1);
    return `~${shown}h effort`;
  }

  function budgetValue(payload) {
    if (budgetInput && budgetInput.value !== "") {
      const n = Number(budgetInput.value);
      if (Number.isFinite(n) && n >= 0) return n;
    }
    const fallback = payload && payload.time_budget_hours;
    return Number.isFinite(Number(fallback)) ? Number(fallback) : 0;
  }

  function syncTimeUi(payload) {
    const on = timeAwareOn();
    if (coachTime) coachTime.hidden = !on;
    if (!on) return;
    const hours = payload && payload.hours_remaining;
    if (coachHours) {
      coachHours.textContent = hours == null ? "" : formatHoursLeft(hours);
    }
    if (budgetInput && !budgetTouched && hours != null && hours !== "") {
      const n = Number(hours);
      budgetInput.value = Number.isFinite(n) ? String(Math.round(n * 10) / 10) : "";
    }
  }

  function renderCoach(payload) {
    if (!coachList) return;
    lastCoach = payload || lastCoach;
    coachList.innerHTML = "";
    syncTimeUi(payload);
    const moves = (payload && payload.moves) || [];
    if (!moves.length) {
      if (coachStatus) {
        coachStatus.hidden = false;
        coachStatus.textContent = "Coach is quiet. The core map still holds.";
      }
      return;
    }
    if (coachStatus) coachStatus.hidden = true;
    const aware = timeAwareOn();
    const budget = budgetValue(payload);
    for (const move of moves) {
      const li = document.createElement("li");
      const effort = Number(move.effort_hours);
      const feasible = aware ? effort <= budget : true;
      li.className = `card coach-card${aware && !feasible ? " is-late" : ""}`;
      const pct = (Number(move.delta) || 0) * 100;
      const signed = formatDelta(move.delta);
      let extra = "";
      if (aware) {
        extra = `<div class="coach-meta">
          <span class="coach-effort">${escapeHtml(formatEffort(effort))}</span>
          <span class="coach-badge${feasible ? " is-ok" : ""}">${feasible ? "feasible" : "too late"}</span>
        </div>`;
      }
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(move.label || "")}</span>
          <span class="coach-delta${pct < 0 ? " is-down" : ""}">${signed}</span>
        </div>
        <p class="card-tag">${escapeHtml(move.rationale || "")}</p>
        ${extra}
      `;
      li.addEventListener("mouseenter", () => playGhost(move));
      li.addEventListener("mouseleave", clearGhost);
      coachList.appendChild(li);
    }
  }

  if (timeToggle) {
    timeToggle.addEventListener("change", () => {
      if (lastCoach) renderCoach(lastCoach);
      else syncTimeUi(lastCoach);
    });
  }
  if (budgetInput) {
    budgetInput.addEventListener("input", () => {
      budgetTouched = true;
      if (lastCoach) renderCoach(lastCoach);
    });
  }

  if (coachBtn) {
    coachBtn.addEventListener("click", async () => {
      const text = lastIdeaText || (input && input.value.trim()) || "";
      if (!text || coachInFlight) return;
      coachInFlight = true;
      coachBtn.disabled = true;
      setCoachOpen(true);
      syncTimeUi(lastCoach);
      if (coachStatus) {
        coachStatus.hidden = false;
        coachStatus.textContent = "Scoring a few moves through the classifier…";
      }
      coachList.innerHTML = "";
      try {
        const body = { text };
        if (timeAwareOn() && budgetInput && budgetInput.value !== "") {
          const n = Number(budgetInput.value);
          if (Number.isFinite(n) && n >= 0) body.time_budget_hours = n;
        }
        const res = await fetch("/api/coach", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(await res.text());
        renderCoach(await res.json());
      } catch (err) {
        if (coachStatus) {
          coachStatus.hidden = false;
          coachStatus.textContent = "Coach skipped. Place it still works.";
        }
        console.error(err);
      } finally {
        coachInFlight = false;
        coachBtn.disabled = false;
      }
    });
  }

  function renderTracks(payload) {
    if (!tracksPanel) return;
    tracksPayload = payload || null;
    if (!payload) {
      tracksPanel.hidden = true;
      return;
    }
    tracksPanel.hidden = false;
    trackList.innerHTML = "";
    if (!payload.ok) {
      if (trackFilters) trackFilters.hidden = true;
      if (tracksMethod) {
        tracksMethod.hidden = true;
        tracksMethod.textContent = "";
      }
      tracksEmpty.hidden = false;
      tracksEmpty.textContent = payload.error || "Could not load prize tracks.";
      return;
    }
    if (tracksMethod) {
      tracksMethod.hidden = false;
      tracksMethod.textContent = "Each % is a sponsor-prize chance, not the 12 finalists. The arrow is if you ship the SDK.";
    }
    if (trackFilters) trackFilters.hidden = false;
    const rows = (payload.ranked || []).filter((row) => {
      if (trackFilter === "all") return true;
      if (trackFilter === "actionable") return row.action === "add" || row.action === "strengthen";
      return row.action === trackFilter;
    });
    if (!rows.length) {
      tracksEmpty.hidden = false;
      tracksEmpty.textContent = trackFilter === "actionable"
        ? "No add/strengthen moves. Try All, or a repo that actually touches a sponsor SDK."
        : "Nothing in this filter.";
      return;
    }
    tracksEmpty.hidden = true;
    const actionLabel = { add: "Add stream", strengthen: "Strengthen", defend: "In repo", skip: "Skip" };
    for (const row of rows) {
      const li = document.createElement("li");
      li.className = "card track-card";
      const now = Math.round((row.p_now ?? row.fit ?? 0) * 100);
      const iff = Math.round((row.p_if ?? row.p_now ?? 0) * 100);
      const lift = iff > now + 1 ? ` <span class="track-if">→ ${iff}% if you do this</span>` : "";
      const moves = (row.moves || []).map((m) => `<li>${escapeHtml(m)}</li>`).join("");
      const past = (row.past || [])
        .slice(0, 2)
        .map((p) => `${p.title} (${p.year}) won ${p.prize}`)
        .join("; ");
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(row.name)}</span>
          <span class="card-year">${now}%${lift}</span>
        </div>
        <span class="track-action">${escapeHtml(actionLabel[row.action] || row.action || "")}</span>
        ${moves ? `<ul class="track-moves">${moves}</ul>` : ""}
        ${past ? `<p class="card-tag">${escapeHtml(past)}</p>` : ""}
      `;
      trackList.appendChild(li);
    }
  }

  if (trackFilters) {
    trackFilters.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-filter]");
      if (!btn) return;
      trackFilter = btn.dataset.filter;
      trackFilters.querySelectorAll(".chip").forEach((c) => c.classList.toggle("is-on", c === btn));
      if (tracksPayload) renderTracks(tracksPayload);
    });
  }

  function renderProb(data) {
    probPanel.hidden = false;
    const p = Number(data && data.probability);
    if (!Number.isFinite(p)) {
      probNum.textContent = "—";
    } else {
      const pct = Math.round(Math.max(0, Math.min(1, p)) * 100);
      probNum.textContent = `${pct}%`;
    }
    const m = (data && data.model) || {};
    const aucNum = m.auc == null ? NaN : Number(m.auc);
    const auc = Number.isFinite(aucNum) ? aucNum.toFixed(2) : "—";
    const n = m.n_train ?? "—";
    const spread = Array.isArray(m.auc_spread) && m.auc_spread.length === 2
      && Number.isFinite(Number(m.auc_spread[0])) && Number.isFinite(Number(m.auc_spread[1]))
      ? ` (${Number(m.auc_spread[0]).toFixed(2)}–${Number(m.auc_spread[1]).toFixed(2)})`
      : "";
    let line = `Calibrated from corpus signals, not neighbour similarity.\nAUC ${auc}${spread}  ·  ${n} training projects  ·  leave-one-year-out`;
    const g = data.github;
    if (g && g.ok) {
      const bits = [g.full_name];
      if (g.languages && g.languages.length) bits.push(g.languages.slice(0, 4).join(", "));
      if (g.hardware) bits.push("hardware");
      line = `Read ${bits.join(" · ")}\n` + line;
    } else if (g && !g.ok) {
      line = `GitHub unread (${g.error || "failed"}). Used the prompt only.\n` + line;
    }
    if (Array.isArray(data.why) && data.why.length) {
      line += "\n" + data.why[0];
    }
    probMeta.textContent = line;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (askInFlight) return;
    const text = input.value.trim();
    const github = (githubInput && githubInput.value.trim()) || "";
    const devpost = (devpostInput && devpostInput.value.trim()) || "";
    if (!text && !github) {
      if (askStatus) {
        askStatus.hidden = false;
        askStatus.textContent = "Add a sentence or a GitHub link.";
      }
      return;
    }
    askInFlight = true;
    askBtn.disabled = true;
    if (askStatus) {
      askStatus.hidden = false;
      askStatus.textContent = github && devpost
        ? "Reading the repo and prize tracks…"
        : github
          ? "Reading the repo…"
          : devpost
            ? "Reading prize tracks…"
            : "";
    }
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, github, devpost }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      query = data;
      lastIdeaText = text;
      pulse = 0;
      ghost = null;
      cancelAnimationFrame(ghostRaf);
      cancelAnimationFrame(raf);
      renderNeighbours(data.neighbours || []);
      renderTracks(data.tracks);
      renderProb(data);
      if (coachPanel) {
        setCoachOpen(false);
        lastCoach = null;
        if (coachList) coachList.innerHTML = "";
        if (coachStatus) coachStatus.hidden = true;
        if (coachTime) coachTime.hidden = !timeAwareOn();
      }
      const neighbours = document.getElementById("neighbours");
      if (neighbours) {
        neighbours.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      if (askStatus) {
        const bits = [];
        const g = data.github;
        if (g && g.ok) bits.push(`README + stack from ${g.full_name}`);
        else if (g && !g.ok) bits.push("Could not read that repo. Placed from the prompt");
        const t = data.tracks;
        if (t && t.ok) bits.push(`ranked ${(t.ranked || []).length} of ${t.n} tracks`);
        else if (t && !t.ok) bits.push(t.error || "prize tracks unread");
        if (data.source === "elastic") bits.push("neighbours via Elasticsearch hybrid");
        if (bits.length) {
          askStatus.hidden = false;
          askStatus.textContent = bits.join(". ") + ".";
        } else {
          askStatus.hidden = true;
        }
      }
      draw();
      raf = requestAnimationFrame(tick);
    } catch (err) {
      neighboursEmpty.hidden = false;
      neighboursEmpty.textContent = "Could not place that idea. Try again.";
      if (askStatus) askStatus.hidden = true;
      console.error(err);
      } finally {
      askInFlight = false;
      askBtn.disabled = false;
    }
  });

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("is-on", b === btn));
      const view = btn.dataset.view;
      document.getElementById("view-explore").hidden = view !== "explore";
      document.getElementById("view-findings").hidden = view !== "findings";
      if (view === "explore") resize();
    });
  });

  function svgEl(name, attrs) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  }

  function drawBars(chart) {
    const svg = svgEl("svg", { viewBox: "0 0 400 220" });
    const bars = chart.bars || [];
    const max = Math.max(0.01, ...bars.map((b) => b.value));
    const bw = 400 / Math.max(bars.length, 1);
    bars.forEach((b, i) => {
      const h = (b.value / max) * 150;
      const x = i * bw + bw * 0.22;
      const y = 170 - h;
      const rect = svgEl("rect", {
        x, y, width: bw * 0.56, height: h,
        class: i === 0 ? "chart-bar" : "chart-bar-mute",
      });
      if (i === bars.length - 1 && i !== 0) rect.setAttribute("class", "chart-bar-mute");
      svg.appendChild(rect);
      const label = svgEl("text", { x: x + bw * 0.28, y: 190, "text-anchor": "middle", class: "chart-axis" });
      label.textContent = b.label;
      svg.appendChild(label);
      const val = svgEl("text", { x: x + bw * 0.28, y: y - 6, "text-anchor": "middle", class: "chart-axis" });
      val.textContent = `${(Number(b.value) * 100).toFixed(1)}%`;
      svg.appendChild(val);
    });
    return svg;
  }

  function drawLines(chart) {
    const svg = svgEl("svg", { viewBox: "0 0 400 220" });
    const series = chart.series || [];
    const years = [...new Set(series.flatMap((s) => s.points.map((p) => p.year)))].sort((a, b) => a - b);
    const values = series.flatMap((s) => s.points.map((p) => p.value));
    const max = Math.max(0.01, ...values);
    const xOf = (year) => 30 + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * 350;
    const yOf = (v) => 180 - (v / max) * 150;
    const classes = [
      "chart-line",
      "chart-line chart-line-2",
      "chart-line chart-line-3",
      "chart-line chart-line-4",
      "chart-line chart-line-5",
      "chart-line chart-line-6",
    ];
    series.forEach((s, i) => {
      const d = s.points
        .sort((a, b) => a.year - b.year)
        .map((p, idx) => `${idx ? "L" : "M"}${xOf(p.year)},${yOf(p.value)}`)
        .join(" ");
      svg.appendChild(svgEl("path", { d, class: classes[i % classes.length] }));
    });
    years.forEach((y, i) => {
      if (years.length > 8 && i % 2 === 1 && i !== years.length - 1) return;
      const t = svgEl("text", { x: xOf(y), y: 205, "text-anchor": "middle", class: "chart-axis" });
      t.textContent = String(y);
      svg.appendChild(t);
    });
    return svg;
  }

  function appendChart(chart) {
    const box = document.createElement("article");
    box.className = "chart";
    const h = document.createElement("h2");
    h.className = "chart-claim";
    h.textContent = chart.claim;
    box.appendChild(h);
    box.appendChild(chart.kind === "lines" ? drawLines(chart) : drawBars(chart));
    if (chart.kind === "lines" && chart.series) {
      const key = document.createElement("div");
      key.className = "chart-key";
      chart.series.forEach((s, i) => {
        const item = document.createElement("span");
        item.className = `chart-key-item chart-key-${(i % 6) + 1}`;
        item.textContent = s.label;
        key.appendChild(item);
      });
      box.appendChild(key);
    }
    chartsEl.appendChild(box);
  }

  function chartFromAiWriting(ai) {
    const years = ai.years || [];
    const probs = ai.ai_prob || [];
    if (!years.length || years.length !== probs.length) return null;
    return {
      claim: ai.claim || "Writing shifts toward AI-generated after 2023",
      kind: "lines",
      series: [
        {
          label: "mean AI-likelihood of sampled writeups",
          points: years.map((year, i) => ({ year, value: Number(probs[i]) || 0 })),
        },
      ],
    };
  }

  async function loadFindings() {
    try {
      const res = await fetch("/api/findings");
      const data = await res.json();
      if (data.source === "sample") {
        findingsNote.textContent = "Sample claims until Richa ships data/findings.json.";
      } else {
        findingsNote.textContent = "";
      }
      chartsEl.innerHTML = "";
      for (const chart of data.charts || []) {
        appendChart(chart);
      }
      const aiChart = data.ai_writing ? chartFromAiWriting(data.ai_writing) : null;
      if (aiChart) appendChart(aiChart);
    } catch (err) {
      if (findingsNote) findingsNote.textContent = "Findings did not load.";
      console.error(err);
    }
  }

  async function boot() {
    try {
      const [mapRes, cfgRes] = await Promise.all([fetch("/api/map"), fetch("/api/config")]);
      mapData = await mapRes.json();
      if (!mapData || !Array.isArray(mapData.points)) {
        mapData = { points: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
      }
      const cfg = await cfgRes.json();
      corpusMeta.textContent = `${cfg.n} projects  ·  ${cfg.n_finalists} finalists  ·  ${cfg.source}`;
      console.log("map", mapData);
      if (cfg.sentry_dsn) {
        const key = cfg.sentry_dsn.split("://")[1]?.split("@")[0];
        const s = document.createElement("script");
        s.src = `https://js.sentry-cdn.com/${key}.min.js`;
        s.crossOrigin = "anonymous";
        const init = () => {
          if (!window.Sentry) return;
          window.Sentry.init({
            dsn: cfg.sentry_dsn,
            tracesSampleRate: 1.0,
            replaysSessionSampleRate: 1.0,
            replaysOnErrorSampleRate: 1.0,
            integrations: [
              window.Sentry.browserTracingIntegration && window.Sentry.browserTracingIntegration(),
              window.Sentry.replayIntegration && window.Sentry.replayIntegration(),
            ].filter(Boolean),
          });
        };
        s.onload = () => {
          if (window.Sentry && window.Sentry.onLoad) window.Sentry.onLoad(init);
          else init();
        };
        document.head.appendChild(s);
      }
    } catch (err) {
      corpusMeta.textContent = "Could not load the map.";
      console.error(err);
    }
    resize();
    loadFindings();
  }

  window.addEventListener("resize", resize);
  boot();
})();
