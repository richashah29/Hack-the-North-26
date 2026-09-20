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
  const twinsEl = document.getElementById("twins");
  const twinWin = document.getElementById("twin-win");
  const twinLose = document.getElementById("twin-lose");
  const tracksPanel = document.getElementById("tracks-panel");
  const trackList = document.getElementById("track-list");
  const tracksEmpty = document.getElementById("tracks-empty");
  const tracksMethod = document.getElementById("tracks-method");
  const trackFilters = document.getElementById("track-filters");
  let tracksPayload = null;
  let trackFilter = "all";
  const probPanel = document.getElementById("prob-panel");
  const probNum = document.getElementById("prob-num");
  const probCaveat = document.getElementById("prob-caveat");
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
  const yearHudNum = document.getElementById("year-hud-num");
  const yearHudSub = document.getElementById("year-hud-sub");
  const scrubPlay = document.getElementById("scrub-play");
  const scrubYear = document.getElementById("scrub-year");
  const scrubYearLabel = document.getElementById("scrub-year-label");
  const scrubFinalists = document.getElementById("scrub-finalists");
  const scrubAll = document.getElementById("scrub-all");
  let lastCoach = null;
  let budgetTouched = false;
  let askInFlight = false;
  let coachInFlight = false;

  const GOLD = "#E8B33D";
  const FAINT = "#626C78";
  const INK = "#ECEFF3";
  const YEAR_MIN = 2014;
  const YEAR_MAX = 2025;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let mapData = { points: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
  let query = null;
  let hover = null;
  let pulse = 0;
  let raf = 0;
  let lastIdeaText = "";
  let ghost = null;
  let ghostRaf = 0;
  let yearCap = null;
  let playTimer = null;
  let view = { scale: 1, tx: 0, ty: 0 };
  let drag = null;
  let pinch = null;
  const SCALE_MIN = 1;
  const SCALE_MAX = 14;
  const zoomInBtn = document.getElementById("zoom-in");
  const zoomOutBtn = document.getElementById("zoom-out");
  const zoomResetBtn = document.getElementById("zoom-reset");
  const zoomLevel = document.getElementById("zoom-level");

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    clampView();
    draw();
  }

  function layoutPoint(pt) {
    const b = mapData.bounds;
    const padX = 28;
    const padTop = 28;
    const padBottom = 88;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const x = padX + ((pt.x - b.x0) / (b.x1 - b.x0 || 1)) * (w - padX * 2);
    const y = padTop + (1 - (pt.y - b.y0) / (b.y1 - b.y0 || 1)) * Math.max(1, h - padTop - padBottom);
    return { x, y };
  }

  function project(pt) {
    const s = layoutPoint(pt);
    return {
      x: s.x * view.scale + view.tx,
      y: s.y * view.scale + view.ty,
    };
  }

  function clampView() {
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    if (view.scale <= SCALE_MIN + 0.001) {
      view.scale = SCALE_MIN;
      view.tx = 0;
      view.ty = 0;
      return;
    }
    // Keep the scaled map covering the canvas — no empty bands when panning.
    view.tx = Math.min(0, Math.max(w - w * view.scale, view.tx));
    view.ty = Math.min(0, Math.max(h - h * view.scale, view.ty));
  }

  function updateZoomUi() {
    if (zoomLevel) {
      const shown = view.scale < 10 ? view.scale.toFixed(1).replace(/\.0$/, "") : String(Math.round(view.scale));
      zoomLevel.textContent = `${shown}×`;
    }
    if (zoomOutBtn) zoomOutBtn.disabled = view.scale <= SCALE_MIN + 0.001;
    if (zoomInBtn) zoomInBtn.disabled = view.scale >= SCALE_MAX - 0.001;
  }

  function zoomAt(mx, my, factor) {
    const next = Math.min(SCALE_MAX, Math.max(SCALE_MIN, view.scale * factor));
    const ratio = next / (view.scale || 1);
    view.tx = mx - (mx - view.tx) * ratio;
    view.ty = my - (my - view.ty) * ratio;
    view.scale = next;
    clampView();
    updateZoomUi();
    draw();
  }

  function resetView() {
    view = { scale: 1, tx: 0, ty: 0 };
    updateZoomUi();
    draw();
  }

  function canvasCenter() {
    return { x: canvas.clientWidth / 2, y: canvas.clientHeight / 2 };
  }

  function inYear(p) {
    if (yearCap == null) return true;
    return Number(p.year) <= yearCap;
  }

  function visiblePoints() {
    return (mapData.points || []).filter(inYear);
  }

  function hitTest(mx, my) {
    const pts = visiblePoints();
    let best = null;
    let bestD = 10 * Math.sqrt(view.scale);
    const rr = radii();
    for (const p of pts) {
      const s = project(p);
      const d = Math.hypot(s.x - mx, s.y - my);
      const r = p.finalist ? rr.finalist + 4 : rr.mute + 4;
      if (d < Math.max(bestD, r + 3)) {
        best = p;
        bestD = d;
      }
    }
    if (query && query.point) {
      const s = project(query.point);
      if (Math.hypot(s.x - mx, s.y - my) < 12 * Math.sqrt(view.scale)) {
        best = { ...query.point, title: "Your idea", year: "", you: true };
      }
    }
    return best;
  }

  function radii() {
    const s = Math.min(3, Math.sqrt(view.scale));
    return { mute: 2.2 * s, finalist: 4.4 * s, neighbour: 6 * s, you: 6 * s };
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const r = radii();
    const pts = visiblePoints();
    const neighbourSlugs = new Set((query?.neighbours || []).map((n) => n.slug));
    const focused = !!(query && query.point);

    const pad = 24;
    const onScreen = (s) => s.x > -pad && s.y > -pad && s.x < w + pad && s.y < h + pad;

    for (const p of pts) {
      if (p.finalist || neighbourSlugs.has(p.slug)) continue;
      const s = project(p);
      if (!onScreen(s)) continue;
      ctx.globalAlpha = focused ? 0.28 : 1;
      ctx.fillStyle = FAINT;
      ctx.beginPath();
      ctx.arc(s.x, s.y, r.mute, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    for (const p of pts) {
      if (!p.finalist) continue;
      const s = project(p);
      if (!onScreen(s)) continue;
      ctx.globalAlpha = focused && !neighbourSlugs.has(p.slug) ? 0.4 : 1;
      ctx.fillStyle = GOLD;
      ctx.beginPath();
      ctx.arc(s.x, s.y, neighbourSlugs.has(p.slug) ? r.neighbour : r.finalist, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (query && query.point) {
      const origin = project(query.point);
      ctx.strokeStyle = "rgba(232,179,61,0.35)";
      ctx.lineWidth = 1;
      for (const n of query.neighbours) {
        const p = mapData.points.find((x) => x.slug === n.slug);
        if (!p || !inYear(p)) continue;
        const t = project(p);
        ctx.beginPath();
        ctx.moveTo(origin.x, origin.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
        ctx.strokeStyle = GOLD;
        ctx.beginPath();
        ctx.arc(t.x, t.y, 7, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = "rgba(232,179,61,0.35)";
      }

      const ring = 10 + pulse * 18;
      ctx.strokeStyle = `rgba(232,179,61,${1 - pulse})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, ring, 0, Math.PI * 2);
      ctx.stroke();

      ctx.shadowColor = "rgba(232,179,61,0.55)";
      ctx.shadowBlur = 16;
      ctx.fillStyle = GOLD;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, r.you, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, r.you + 3, 0, Math.PI * 2);
      ctx.stroke();
    }

    if (ghost && ghost.from && ghost.to && query && query.point) {
      const a = project(ghost.from);
      const b = project(ghost.to);
      const t = ghost.t;
      const gx = a.x + (b.x - a.x) * t;
      const gy = a.y + (b.y - a.y) * t;
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = "rgba(236,239,243,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(gx, gy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(236,239,243,0.2)";
      ctx.strokeStyle = GOLD;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(gx, gy, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }

  function tick() {
    if (query && pulse < 1) {
      pulse = Math.min(1, pulse + (reducedMotion ? 1 : 0.03));
      draw();
      raf = requestAnimationFrame(tick);
    }
  }

  function showTooltip(p, ev) {
    if (!p) {
      tooltip.hidden = true;
      tooltip.innerHTML = "";
      return;
    }
    tooltip.hidden = false;
    if (p.you) {
      tooltip.innerHTML = `<div class="tip-title">Your idea</div>`;
    } else {
      const badge = p.finalist ? `<span class="tip-badge">Finalist</span>` : "";
      tooltip.innerHTML = `<div class="tip-title">${escapeHtml(p.title || "")}</div>
        <div class="tip-meta"><span>${escapeHtml(String(p.year || ""))}</span>${badge}</div>`;
    }
    const rect = canvas.getBoundingClientRect();
    tooltip.style.left = `${ev.clientX - rect.left}px`;
    tooltip.style.top = `${ev.clientY - rect.top}px`;
  }

  canvas.addEventListener("mousemove", (ev) => {
    if (drag) {
      view.tx = drag.tx + (ev.clientX - drag.x);
      view.ty = drag.ty + (ev.clientY - drag.y);
      clampView();
      draw();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    hover = hitTest(ev.clientX - rect.left, ev.clientY - rect.top);
    canvas.style.cursor = hover ? "crosshair" : "grab";
    showTooltip(hover, ev);
  });
  canvas.addEventListener("mousedown", (ev) => {
    if (ev.button !== 0) return;
    drag = { x: ev.clientX, y: ev.clientY, tx: view.tx, ty: view.ty };
    canvas.style.cursor = "grabbing";
    tooltip.hidden = true;
  });
  window.addEventListener("mouseup", () => {
    drag = null;
    canvas.style.cursor = "grab";
  });
  canvas.addEventListener("mouseleave", () => {
    hover = null;
    tooltip.hidden = true;
  });
  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const factor = Math.exp(-ev.deltaY * 0.002);
    zoomAt(ev.clientX - rect.left, ev.clientY - rect.top, factor);
  }, { passive: false });
  canvas.addEventListener("dblclick", (ev) => {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    if (view.scale >= SCALE_MAX - 0.05) resetView();
    else zoomAt(ev.clientX - rect.left, ev.clientY - rect.top, 1.8);
  });

  canvas.addEventListener("touchstart", (ev) => {
    if (ev.touches.length === 2) {
      const a = ev.touches[0];
      const b = ev.touches[1];
      pinch = {
        dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
        scale: view.scale,
        tx: view.tx,
        ty: view.ty,
        cx: (a.clientX + b.clientX) / 2,
        cy: (a.clientY + b.clientY) / 2,
      };
      drag = null;
    } else if (ev.touches.length === 1) {
      const t = ev.touches[0];
      drag = { x: t.clientX, y: t.clientY, tx: view.tx, ty: view.ty };
    }
  }, { passive: true });
  canvas.addEventListener("touchmove", (ev) => {
    if (pinch && ev.touches.length === 2) {
      ev.preventDefault();
      const a = ev.touches[0];
      const b = ev.touches[1];
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      const rect = canvas.getBoundingClientRect();
      const next = Math.min(SCALE_MAX, Math.max(SCALE_MIN, pinch.scale * (dist / (pinch.dist || 1))));
      const ratio = next / (pinch.scale || 1);
      const mx = pinch.cx - rect.left;
      const my = pinch.cy - rect.top;
      view.scale = next;
      view.tx = mx - (mx - pinch.tx) * ratio;
      view.ty = my - (my - pinch.ty) * ratio;
      clampView();
      updateZoomUi();
      draw();
    } else if (drag && ev.touches.length === 1) {
      ev.preventDefault();
      const t = ev.touches[0];
      view.tx = drag.tx + (t.clientX - drag.x);
      view.ty = drag.ty + (t.clientY - drag.y);
      clampView();
      draw();
    }
  }, { passive: false });
  canvas.addEventListener("touchend", () => {
    pinch = null;
    drag = null;
  });

  if (zoomInBtn) {
    zoomInBtn.addEventListener("click", () => {
      const c = canvasCenter();
      zoomAt(c.x, c.y, 1.35);
    });
  }
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener("click", () => {
      const c = canvasCenter();
      zoomAt(c.x, c.y, 1 / 1.35);
    });
  }
  if (zoomResetBtn) zoomResetBtn.addEventListener("click", resetView);

  window.addEventListener("keydown", (ev) => {
    const explore = document.getElementById("view-explore");
    if (explore && explore.hidden) return;
    if (ev.target && ev.target.closest && ev.target.closest("input, textarea, button, select")) return;
    const c = canvasCenter();
    if (ev.key === "+" || ev.key === "=") zoomAt(c.x, c.y, 1.25);
    else if (ev.key === "-" || ev.key === "_") zoomAt(c.x, c.y, 1 / 1.25);
    else if (ev.key === "0") resetView();
  });

  function fmtN(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString("en-US");
  }

  function fmtPct(v, digits = 1) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return `${(n * 100).toFixed(digits)}%`;
  }

  function fmtSim(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "";
    if (n >= 0.15 && n <= 1) return `${Math.round(n * 100)}% similar`;
    return `sim ${n.toFixed(3)}`;
  }

  function renderTwinCard(el, kind, item) {
    if (!el) return;
    el.classList.toggle("is-empty", !item);
    if (!item) {
      el.innerHTML = `
        <p class="twin-kicker">${kind === "win" ? "Closest that made it" : "Closest that didn’t"}</p>
        <p class="twin-title">${kind === "win" ? "No finalist in the nearest five." : "No non-finalist in the nearest five."}</p>`;
      return;
    }
    el.innerHTML = `
      <p class="twin-kicker">${kind === "win" ? "Closest that made it" : "Closest that didn’t"}</p>
      <p class="twin-title">${escapeHtml(item.title || "Untitled")}</p>
      <p class="twin-meta">${escapeHtml(String(item.year || ""))} · ${escapeHtml(fmtSim(item.similarity))}</p>
      <p class="twin-tag">${escapeHtml(item.tagline || "")}</p>`;
  }

  function renderTwins(items) {
    if (!twinsEl) return;
    if (!items || !items.length) {
      twinsEl.hidden = true;
      return;
    }
    twinsEl.hidden = false;
    renderTwinCard(twinWin, "win", items.find((n) => n.finalist) || null);
    renderTwinCard(twinLose, "lose", items.find((n) => !n.finalist) || null);
  }

  function renderNeighbours(items) {
    neighbourList.innerHTML = "";
    if (!items || !items.length) {
      neighboursEmpty.hidden = false;
      neighboursEmpty.textContent = "Twelve years of submissions. Type an idea to see what it sits next to.";
      return;
    }
    neighboursEmpty.hidden = true;
    for (const n of items) {
      const li = document.createElement("li");
      li.className = "card" + (n.finalist ? " is-hit" : "");
      const title = n && n.title != null ? String(n.title) : "";
      const tagline = n && n.tagline != null ? String(n.tagline) : "";
      const year = n && n.year != null && n.year !== "" ? String(n.year) : "";
      const sim = fmtSim(n.similarity);
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(title || "Untitled")}</span>
          <span class="card-year">${escapeHtml(year)}</span>
        </div>
        <p class="card-tag">${escapeHtml(tagline)}</p>
        ${n.finalist ? '<div class="badge">Finalist</div>' : ""}
        ${sim ? `<div class="twin-meta">${escapeHtml(sim)}</div>` : ""}
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
    if (reducedMotion) {
      ghost = { from: query.point, to: move.new_point, t: 1 };
      draw();
      return;
    }
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
    if (tenths < 0) return `−${body}%`;
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
      const down = pct < -0.05;
      const zero = Math.abs(pct) < 0.05;
      let extra = "";
      if (aware) {
        extra = `<div class="coach-meta">
          <span class="coach-effort">${escapeHtml(formatEffort(effort))}</span>
          <span class="coach-badge${feasible ? " is-ok" : ""}">${feasible ? "feasible" : "too late"}</span>
        </div>`;
      }
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(move.label || "Untitled move")}</span>
          <span class="coach-delta${down ? " is-down" : zero ? " is-zero" : ""}">${signed}</span>
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
        coachStatus.classList.add("is-loading");
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
        if (coachStatus) coachStatus.classList.remove("is-loading");
        renderCoach(await res.json());
      } catch (err) {
        if (coachStatus) {
          coachStatus.hidden = false;
          coachStatus.classList.remove("is-loading");
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
          <span class="card-title">${escapeHtml(row.name || "Untitled track")}</span>
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
    const n = m.n_train != null ? fmtN(m.n_train) : "3,443";
    const spread = Array.isArray(m.auc_spread) && m.auc_spread.length === 2
      && Number.isFinite(Number(m.auc_spread[0])) && Number.isFinite(Number(m.auc_spread[1]))
      ? ` (${Number(m.auc_spread[0]).toFixed(2)}–${Number(m.auc_spread[1]).toFixed(2)})`
      : "";
    if (probCaveat) {
      probCaveat.textContent = `AUC ${auc}${spread} · leave-one-year-out · ${n} projects`;
    }
    const bits = [];
    const g = data.github;
    if (g && g.ok) {
      const name = g.full_name || "repo";
      const langs = (g.languages || []).slice(0, 4).join(", ");
      bits.push(`Read ${name}${langs ? ` · ${langs}` : ""}${g.hardware ? " · hardware" : ""}`);
    } else if (g && !g.ok) {
      bits.push(`GitHub unread (${g.error || "failed"}). Used the prompt only.`);
    }
    if (Array.isArray(data.why) && data.why.length) bits.push(String(data.why[0]));
    probMeta.textContent = bits.join(" ");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function finalistsThrough(cap) {
    return (mapData.points || []).filter((p) => p.finalist && (cap == null || Number(p.year) <= cap)).length;
  }

  function stopPlay() {
    if (playTimer) {
      clearTimeout(playTimer);
      playTimer = null;
    }
    if (scrubPlay) {
      scrubPlay.classList.remove("is-on");
      scrubPlay.textContent = "Play";
    }
  }

  function updateScrubber() {
    const all = yearCap == null;
    const label = all ? "All years" : String(yearCap);
    const nFin = finalistsThrough(yearCap);
    if (yearHudNum) yearHudNum.textContent = all ? "2014–2025" : String(yearCap);
    if (yearHudSub) {
      yearHudSub.textContent = all
        ? `${fmtN(nFin)} finalists`
        : `${fmtN(nFin)} finalists so far`;
    }
    if (scrubYearLabel) scrubYearLabel.textContent = label;
    if (scrubFinalists) {
      scrubFinalists.textContent = all
        ? `${fmtN(nFin)} finalists`
        : `${fmtN(nFin)} so far`;
    }
    if (scrubYear && !all) scrubYear.value = String(yearCap);
    if (scrubYear && all) scrubYear.value = String(YEAR_MAX);
  }

  function setYearCap(y, playing) {
    yearCap = y;
    if (!playing) stopPlay();
    updateScrubber();
    draw();
  }

  function playYears() {
    if (playTimer) {
      stopPlay();
      return;
    }
    if (scrubPlay) {
      scrubPlay.classList.add("is-on");
      scrubPlay.textContent = "Pause";
    }
    yearCap = YEAR_MIN;
    updateScrubber();
    draw();
    const stepMs = reducedMotion ? 80 : 420;
    const step = () => {
      if (yearCap == null || yearCap >= YEAR_MAX) {
        yearCap = YEAR_MAX;
        updateScrubber();
        draw();
        stopPlay();
        return;
      }
      yearCap += 1;
      updateScrubber();
      draw();
      playTimer = setTimeout(step, stepMs);
    };
    playTimer = setTimeout(step, stepMs);
  }

  if (scrubPlay) scrubPlay.addEventListener("click", playYears);
  if (scrubAll) {
    scrubAll.addEventListener("click", () => setYearCap(null));
  }
  if (scrubYear) {
    scrubYear.addEventListener("input", () => {
      setYearCap(Number(scrubYear.value));
    });
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
        askStatus.classList.remove("is-loading");
        askStatus.textContent = "Add a sentence or a GitHub link.";
      }
      return;
    }
    askInFlight = true;
    askBtn.disabled = true;
    if (askStatus) {
      askStatus.hidden = false;
      askStatus.classList.add("is-loading");
      askStatus.textContent = github && devpost
        ? "Reading the repo and prize tracks…"
        : github
          ? "Reading the repo…"
          : devpost
            ? "Reading prize tracks…"
            : "Placing your idea on twelve years of projects…";
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
      renderTwins(data.neighbours || []);
      renderNeighbours(data.neighbours || []);
      renderTracks(data.tracks);
      renderProb(data);
      if (coachPanel) {
        setCoachOpen(false);
        lastCoach = null;
        if (coachList) coachList.innerHTML = "";
        if (coachStatus) {
          coachStatus.hidden = true;
          coachStatus.classList.remove("is-loading");
        }
        if (coachTime) coachTime.hidden = !timeAwareOn();
      }
      const neighbours = document.getElementById("neighbours");
      if (neighbours) {
        neighbours.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
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
        askStatus.classList.remove("is-loading");
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
      if (twinsEl) twinsEl.hidden = true;
      if (askStatus) {
        askStatus.hidden = true;
        askStatus.classList.remove("is-loading");
      }
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

  function svgEl(name, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v != null && v !== "") el.setAttribute(k, String(v));
    }
    if (text != null) el.textContent = text;
    return el;
  }

  function svgText(attrs, text, kind) {
    const el = svgEl("text", { ...attrs, class: `chart-${kind}` }, text);
    el.setAttribute("font-size", kind === "label" || kind === "num" ? "12" : "11");
    el.setAttribute("font-family", kind === "tick" || kind === "num" ? "JetBrains Mono, ui-monospace, monospace" : "Space Grotesk, system-ui, sans-serif");
    return el;
  }

  function niceMax(v) {
    const p = Math.max(0, Number(v) || 0) * 100;
    if (p <= 8) return 0.08;
    if (p <= 10) return 0.10;
    if (p <= 25) return 0.25;
    if (p <= 50) return 0.50;
    if (p <= 60) return 0.60;
    if (p <= 75) return 0.75;
    return 1;
  }

  function ticksFor(max) {
    const p = max * 100;
    const step = p <= 10 ? 2 : p <= 25 ? 5 : p <= 60 ? 10 : 25;
    const out = [];
    for (let t = 0; t <= p + 0.01; t += step) out.push(t / 100);
    return out;
  }

  function insightCard(claim, context, svg, source) {
    const box = document.createElement("article");
    box.className = "chart";
    const h = document.createElement("h2");
    h.className = "chart-claim";
    h.textContent = claim || "";
    box.appendChild(h);
    if (context) {
      const p = document.createElement("p");
      p.className = "chart-context";
      p.textContent = context;
      box.appendChild(p);
    }
    const fig = document.createElement("div");
    fig.className = "chart-figure";
    fig.appendChild(svg);
    box.appendChild(fig);
    const src = document.createElement("p");
    src.className = "chart-source";
    src.textContent = source || "3,443 HTN projects, 2014–2025";
    box.appendChild(src);
    return box;
  }

  function contextFor(chart, meta) {
    const base = meta.baseline != null ? fmtPct(meta.baseline) : "4.7%";
    if (chart.id === "video") {
      return `Share of each group that became finalists. Dashed line is the corpus rate (${base}).`;
    }
    if (chart.id === "team") {
      return `Finalist rate by team size. Dashed line is the corpus rate (${base}).`;
    }
    if (chart.id === "framing") {
      return `Finalist rate by how the writeup is framed. Exclusive groups; dashed line is ${base}.`;
    }
    if (chart.id === "tech") {
      return "Share of that year’s projects whose built-with tags match each family. LLM, blockchain, and VR/AR are the story.";
    }
    return chart.unit || "";
  }

  function drawHBars(chart, meta) {
    const bars = chart.bars || [];
    const baseline = meta.baseline || 0;
    const rawMax = Math.max(baseline, ...bars.map((b) => Number(b.value) || 0));
    const max = niceMax(rawMax);
    const W = 640;
    const labelW = 108;
    const padL = 8;
    const padR = 120;
    const padT = 8;
    const padB = 28;
    const rowH = 44;
    const barH = 14;
    const H = padT + bars.length * rowH + padB;
    const plotX = padL + labelW;
    const plotW = W - plotX - padR;
    const svg = svgEl("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": chart.claim || "",
    });
    for (const t of ticksFor(max)) {
      const x = plotX + (t / max) * plotW;
      svg.appendChild(svgEl("line", { x1: x, x2: x, y1: padT, y2: H - padB, class: "chart-grid" }));
      svg.appendChild(svgText({
        x, y: H - 8, "text-anchor": "middle",
      }, `${Math.round(t * 100)}%`, "tick"));
    }
    if (baseline > 0 && baseline < max) {
      const bx = plotX + (baseline / max) * plotW;
      svg.appendChild(svgEl("line", { x1: bx, x2: bx, y1: padT, y2: H - padB, class: "chart-base" }));
    }
    bars.forEach((b, i) => {
      const y = padT + i * rowH + (rowH - barH) / 2;
      const val = Math.max(0, Number(b.value) || 0);
      const w = (val / max) * plotW;
      const n = Number(b.n);
      const k = Number.isFinite(n) ? Math.round(val * n) : null;
      svg.appendChild(svgText({
        x: plotX - 8, y: y + barH - 2, "text-anchor": "end",
      }, b.label || "", "label"));
      svg.appendChild(svgEl("rect", {
        x: plotX, y, width: Math.max(w, 1), height: barH,
        rx: 3, class: i === 0 ? "chart-bar" : "chart-bar-mute",
      }));
      svg.appendChild(svgText({
        x: W - 8, y: y + 6, "text-anchor": "end",
      }, fmtPct(val), "num"));
      if (k != null && Number.isFinite(n)) {
        svg.appendChild(svgText({
          x: W - 8, y: y + 20, "text-anchor": "end",
        }, `${fmtN(k)}/${fmtN(n)}`, "tick"));
      }
    });
    return svg;
  }

  const TECH_FOCUS = ["LLM / genAI", "Blockchain / crypto", "VR / AR"];
  const TECH_COLOR = {
    "LLM / genAI": GOLD,
    "Blockchain / crypto": "#8b7bb8",
    "VR / AR": "#5b8a72",
  };

  function drawTech(chart) {
    const series = chart.series || [];
    const years = [...new Set(series.flatMap((s) => (s.points || []).map((p) => p.year)))].sort((a, b) => a - b);
    const values = series.flatMap((s) => (s.points || []).map((p) => Number(p.value) || 0));
    const max = niceMax(Math.max(0.01, ...values));
    const W = 640;
    const padL = 44;
    const padR = 118;
    const padT = 16;
    const padB = 32;
    const H = 280;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const xOf = (year) => padL + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * plotW;
    const yOf = (v) => padT + plotH - (v / max) * plotH;
    const svg = svgEl("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": chart.claim || "",
    });
    for (const t of ticksFor(max)) {
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: yOf(t), y2: yOf(t), class: "chart-grid",
      }));
      svg.appendChild(svgText({
        x: padL - 8, y: yOf(t) + 4, "text-anchor": "end",
      }, `${Math.round(t * 100)}%`, "tick"));
    }
    const muted = series.filter((s) => !TECH_FOCUS.includes(s.label));
    const focused = series.filter((s) => TECH_FOCUS.includes(s.label));
    const drawSeries = (s, color, width, opacity) => {
      const pts = (s.points || []).slice().sort((a, b) => a.year - b.year);
      if (!pts.length) return;
      const d = pts.map((p, i) => `${i ? "L" : "M"}${xOf(p.year)},${yOf(Number(p.value) || 0)}`).join(" ");
      const path = svgEl("path", { d, class: "chart-line" });
      path.setAttribute("stroke", color);
      path.setAttribute("stroke-width", String(width));
      path.setAttribute("opacity", String(opacity));
      svg.appendChild(path);
      if (opacity < 1) return;
      const last = pts[pts.length - 1];
      const ly = yOf(Number(last.value) || 0);
      const end = svgText({
        x: xOf(last.year) + 8, y: Math.min(Math.max(ly + 4, padT + 12), padT + plotH),
      }, s.label.replace(" / crypto", "").replace(" / genAI", "").replace(" / AR", "/AR"), "end");
      end.style.fill = color;
      svg.appendChild(end);
    };
    muted.forEach((s) => drawSeries(s, FAINT, 1.25, 0.45));
    focused.forEach((s) => drawSeries(s, TECH_COLOR[s.label] || GOLD, 2.4, 1));
    years.forEach((y, i) => {
      if (years.length > 8 && i % 2 === 1 && i !== years.length - 1) return;
      svg.appendChild(svgText({
        x: xOf(y), y: H - 10, "text-anchor": "middle",
      }, String(y), "tick"));
    });
    return svg;
  }

  function drawAi(ai) {
    const years = ai.years || [];
    const probs = (ai.ai_prob || []).map((v) => Number(v) || 0);
    const ns = ai.n || [];
    const max = niceMax(Math.max(0.01, ...probs));
    const W = 640;
    const padL = 52;
    const padR = 56;
    const padT = 24;
    const padB = 32;
    const H = 220;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const xOf = (year) => padL + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * plotW;
    const yOf = (v) => padT + plotH - (v / max) * plotH;
    const svg = svgEl("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": ai.claim || "",
    });
    svg.appendChild(svgText({
      x: padL, y: 14,
    }, "AI-likelihood", "tick"));
    for (const t of ticksFor(max)) {
      svg.appendChild(svgEl("line", {
        x1: padL, x2: W - padR, y1: yOf(t), y2: yOf(t), class: "chart-grid",
      }));
      svg.appendChild(svgText({
        x: padL - 8, y: yOf(t) + 4, "text-anchor": "end",
      }, `${Math.round(t * 100)}%`, "tick"));
    }
    const d = years.map((year, i) => `${i ? "L" : "M"}${xOf(year)},${yOf(probs[i] || 0)}`).join(" ");
    const path = svgEl("path", { d, class: "chart-line" });
    path.setAttribute("stroke", GOLD);
    path.setAttribute("stroke-width", "2.5");
    svg.appendChild(path);
    if (years.includes(2023)) {
      const x = xOf(2023);
      const i23 = years.indexOf(2023);
      svg.appendChild(svgEl("line", {
        x1: x, x2: x, y1: padT, y2: padT + plotH, class: "chart-base",
      }));
      const ann = svgText({
        x: x + 8, y: Math.min(yOf(probs[i23] || 0) - 8, padT + plotH - 24),
      }, "ChatGPT →", "end");
      svg.appendChild(ann);
    }
    const lastI = years.length - 1;
    if (lastI >= 0) {
      const lx = xOf(years[lastI]);
      const ly = yOf(probs[lastI] || 0);
      const dot = svgEl("circle", { cx: lx, cy: ly, r: 4.5 });
      dot.setAttribute("fill", GOLD);
      svg.appendChild(dot);
      svg.appendChild(svgText({
        x: lx - 10, y: Math.max(ly - 10, padT + 4), "text-anchor": "end",
      }, fmtPct(probs[lastI]), "num"));
    }
    years.forEach((y, i) => {
      if (years.length > 8 && i % 2 === 1 && i !== years.length - 1) return;
      svg.appendChild(svgText({
        x: xOf(y), y: H - 10, "text-anchor": "middle",
      }, String(y), "tick"));
    });
    return { svg, nPerYear: ns[0] || 100 };
  }

  function appendChart(chart, meta) {
    let svg;
    if (chart.kind === "lines") svg = drawTech(chart);
    else svg = drawHBars(chart, meta);
    const source = `${fmtN(meta.n)} HTN projects, 2014–2025`;
    const card = insightCard(chart.claim, contextFor(chart, meta), svg, source);
    if (chart.kind === "lines" || chart.id === "framing") card.classList.add("chart-wide");
    chartsEl.appendChild(card);
  }

  function appendAiChart(ai, meta) {
    const { svg, nPerYear } = drawAi(ai);
    const context = `Mean GPTZero AI-likelihood on writeups — not “share of projects built with AI”. ${fmtN(nPerYear)} sampled writeups per year.`;
    const source = `class_probabilities.ai · ${fmtN(nPerYear)}/year · ${fmtN(meta.n)} labelled projects`;
    const card = insightCard(ai.claim, context, svg, source);
    card.classList.add("chart-wide");
    chartsEl.appendChild(card);
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
      const n = Number(data.n_projects) || 3443;
      const nFin = Number(data.n_finalists) || 161;
      const meta = { n, nFinalists: nFin, baseline: n ? nFin / n : 0 };
      const charts = data.charts || [];
      for (const chart of charts.filter((c) => c.kind !== "lines")) appendChart(chart, meta);
      for (const chart of charts.filter((c) => c.kind === "lines")) appendChart(chart, meta);
      if (data.ai_writing) appendAiChart(data.ai_writing, meta);
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
      corpusMeta.textContent = `${fmtN(cfg.n)} projects  ·  ${fmtN(cfg.n_finalists)} finalists  ·  ${cfg.source || "corpus"}`;
      updateScrubber();
      updateZoomUi();
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
  if (typeof ResizeObserver !== "undefined" && canvas) {
    new ResizeObserver(() => resize()).observe(canvas);
  }
  boot();
})();
