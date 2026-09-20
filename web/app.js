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
  const probBase = document.getElementById("prob-base");
  const probWhy = document.getElementById("prob-why");
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

  const GOLD = "#C44B32";
  const FAINT = "#5F8A88";
  const INK = "#2A1810";
  const PREVIEW = "#3D9B96";
  const SAND = "#E8D4B8";
  const SKY = "#B8E8F2";
  // Map encoding: these two fills are used for NOTHING except base corpus dots.
  const WINNER_FILL = "#C62828";
  const NONWINNER_FILL = "#1E5AA8";
  // Search halos: not red, not blue, not white. Distinct from the base encoding.
  const SEARCH_PALETTE = ["#D4A017", "#2E8B57", "#8E44AD", "#1A9B8A", "#C47A0A"];
  const HALO_ALPHA_CAP = 0.28;
  const YEAR_MIN = 2014;
  const YEAR_MAX = 2025;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let mapData = { points: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
  let pointBySlug = new Map();
  let themeLayers = [];
  let themeInFlight = false;
  let themeSeq = 0;
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
  const themeForm = document.getElementById("theme-search");
  const themeInput = document.getElementById("theme-input");
  const themeBtn = document.getElementById("theme-btn");
  const themeNote = document.getElementById("theme-note");
  const themeLegend = document.getElementById("theme-legend");
  const chatPanel = document.getElementById("chat-panel");
  const chatFab = document.getElementById("chat-fab");
  const chatList = document.getElementById("chat-list");
  const chatHint = document.getElementById("chat-hint");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatBtn = document.getElementById("chat-btn");
  const chatStatus = document.getElementById("chat-status");
  const compareEl = document.getElementById("compare");
  const compareClear = document.getElementById("compare-clear");
  let preview = null;
  let lastPreviewText = "";
  let chatThread = [];
  let chatInFlight = false;
  let previewInFlight = false;

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
    if (preview && preview.point) {
      const s = project(preview.point);
      if (Math.hypot(s.x - mx, s.y - my) < 12 * Math.sqrt(view.scale)) {
        best = { ...preview.point, title: "Preview idea", year: "", you: true, preview: true };
      }
    }
    return best;
  }

  function radii() {
    const s = Math.min(3, Math.sqrt(view.scale));
    return { mute: 2.2 * s, finalist: 4.4 * s, neighbour: 6 * s, you: 6 * s };
  }

  function indexMapPoints() {
    pointBySlug = new Map();
    for (const p of mapData.points || []) {
      if (p && p.slug) pointBySlug.set(p.slug, p);
    }
  }

  function hexRgb(hex) {
    const h = String(hex || "").replace("#", "");
    if (h.length === 3) {
      return [
        parseInt(h[0] + h[0], 16),
        parseInt(h[1] + h[1], 16),
        parseInt(h[2] + h[2], 16),
      ];
    }
    if (h.length < 6) return [212, 160, 23];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }

  function nextSearchColor() {
    const used = new Set(themeLayers.map((l) => l.color));
    return SEARCH_PALETTE.find((c) => !used.has(c)) || SEARCH_PALETTE[0];
  }

  function ideaMatchesSearch(layer, ideaText) {
    const q = String((layer && layer.query) || "").trim().toLowerCase();
    const t = String(ideaText || "").trim().toLowerCase();
    if (!q || !t || q.length < 3) return false;
    if (t.includes(q) || (t.length >= 3 && q.includes(t))) return true;
    const tokens = q.split(/[^a-z0-9]+/i).filter((w) => w.length >= 4);
    if (!tokens.length) return false;
    return tokens.every((tok) => t.includes(tok));
  }

  function drawHalo(ctx, x, y, baseR, t, rgb) {
    const tt = t > 1 ? 1 : t < 0 ? 0 : t;
    const rad = baseR + 5 + 6 * tt;
    const a = Math.min(HALO_ALPHA_CAP, 0.10 + 0.18 * tt);
    ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;
    ctx.beginPath();
    ctx.arc(x, y, rad, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawOwnOutline(ctx, pt, stroke, withPulse) {
    if (!pt) return;
    const s = project(pt);
    const rad = radii().you;
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    ctx.setLineDash([]);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(s.x, s.y, rad, 0, Math.PI * 2);
    ctx.stroke();
    if (withPulse && !reducedMotion && pulse < 1) {
      ctx.globalAlpha = Math.max(0, 1 - pulse);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(s.x, s.y, rad + 4 + pulse * 16, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  function setThemeNote(text) {
    if (!themeNote) return;
    const msg = String(text || "").trim();
    themeNote.hidden = !msg;
    themeNote.textContent = msg;
    themeNote.classList.toggle("is-loading", msg.endsWith("…") && !reducedMotion);
  }

  function renderThemeLegend() {
    if (!themeLegend) return;
    themeLegend.hidden = themeLayers.length === 0;
    themeLegend.innerHTML = themeLayers.map((layer) => {
      const label = escapeHtml(layer.query);
      return `<li data-id="${layer.id}">
        <i class="theme-dot" style="background:${layer.color}"></i>
        <span>${label}</span>
        <button type="button" class="theme-x" data-remove="${layer.id}" aria-label="Remove ${label}">×</button>
      </li>`;
    }).join("");
  }

  function removeThemeLayer(id) {
    themeLayers = themeLayers.filter((l) => l.id !== id);
    renderThemeLegend();
    draw();
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const sky = ctx.createLinearGradient(0, 0, 0, h * 0.45);
    sky.addColorStop(0, SKY);
    sky.addColorStop(1, SAND);
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, w, h);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.shadowBlur = 0;
    ctx.setLineDash([]);
    const r = radii();
    const pts = visiblePoints();
    const pad = 24;
    const onScreen = (s) => s.x > -pad && s.y > -pad && s.x < w + pad && s.y < h + pad;

    // 1. BASE: every corpus project is a FILLED circle. Red = finalist, blue = not.
    //    Never stroke a base dot. Never recolor a base dot for search or neighbours.
    for (const p of pts) {
      const s = project(p);
      if (!onScreen(s)) continue;
      ctx.fillStyle = p.finalist ? WINNER_FILL : NONWINNER_FILL;
      ctx.beginPath();
      ctx.arc(s.x, s.y, p.finalist ? r.finalist : r.mute, 0, Math.PI * 2);
      ctx.fill();
    }

    if (query && query.point) {
      const origin = project(query.point);
      ctx.strokeStyle = "rgba(42,24,16,0.28)";
      ctx.lineWidth = 1;
      for (const n of query.neighbours || []) {
        const p = pointBySlug.get(n.slug) || (mapData.points || []).find((x) => x.slug === n.slug);
        if (!p || !inYear(p)) continue;
        const t = project(p);
        ctx.beginPath();
        ctx.moveTo(origin.x, origin.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
      }
    }

    // 2. SEARCH HALOS: transparent colored discs, larger than the base dot, alpha-capped.
    //    Additive-lite via overlapping source-over fills — never lighter (washes to white).
    if (themeLayers.length) {
      ctx.save();
      ctx.globalCompositeOperation = "source-over";
      for (const layer of themeLayers) {
        const maxSim = Number(layer.max_sim) || 0;
        if (!(maxSim > 0) || !Array.isArray(layer.matches)) continue;
        const rgb = hexRgb(layer.color);
        if (rgb.some((c) => !Number.isFinite(c))) continue;
        const seen = new Set();
        for (const m of layer.matches) {
          if (!m || seen.has(m.slug)) continue;
          seen.add(m.slug);
          const p = pointBySlug.get(m.slug);
          if (!p || !inYear(p)) continue;
          const s = project(p);
          if (!onScreen(s)) continue;
          const sim = Number(m.sim);
          const t = sim / maxSim;
          if (!Number.isFinite(t) || t <= 0) continue;
          const baseR = p.finalist ? r.finalist : r.mute;
          drawHalo(ctx, s.x, s.y, baseR, t, rgb);
        }
        // Own-idea / preview may also match a search: halo under the outline, never a fill of the marker.
        if (query && query.point && ideaMatchesSearch(layer, lastIdeaText)) {
          const s = project(query.point);
          if (onScreen(s)) drawHalo(ctx, s.x, s.y, r.you, 1, rgb);
        }
        if (preview && preview.point && ideaMatchesSearch(layer, lastPreviewText)) {
          const s = project(preview.point);
          if (onScreen(s)) drawHalo(ctx, s.x, s.y, r.you, 1, rgb);
        }
      }
      ctx.restore();
    }

    // 3. OWN-IDEA: outline only, no fill. Nothing else on the map uses this style.
    if (ghost && ghost.from && ghost.to && query && query.point) {
      const a = project(ghost.from);
      const b = project(ghost.to);
      const t = ghost.t;
      const gx = a.x + (b.x - a.x) * t;
      const gy = a.y + (b.y - a.y) * t;
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = "rgba(42,24,16,0.4)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(gx, gy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = PREVIEW;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(gx, gy, r.you, 0, Math.PI * 2);
      ctx.stroke();
    }

    if (preview && preview.point && query && query.point) {
      const a = project(query.point);
      const b = project(preview.point);
      ctx.save();
      ctx.globalAlpha = 0.7;
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = "rgba(61,155,150,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
      drawOwnOutline(ctx, preview.point, PREVIEW, false);
    }

    if (query && query.point) {
      drawOwnOutline(ctx, query.point, INK, true);
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
      tooltip.innerHTML = `<div class="tip-title">${p.preview ? "Preview idea" : "Your idea"}</div>`;
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
        <p class="twin-kicker">${kind === "win" ? "Closest finalist" : "Closest not a finalist"}</p>
        <p class="twin-title">${kind === "win" ? "No finalist in the nearest five." : "No non-finalist in the nearest five."}</p>`;
      return;
    }
    el.innerHTML = `
      <p class="twin-kicker">${kind === "win" ? "Closest finalist" : "Closest not a finalist"}</p>
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
    const n = Math.round(Number(delta) || 0);
    if (n > 0) return `+${n}`;
    if (n < 0) return `−${Math.abs(n)}`;
    return "0";
  }

  function scoreOf(data) {
    const s = Number(data && data.score);
    if (Number.isFinite(s)) return Math.max(0, Math.min(100, Math.round(s)));
    return null;
  }

  function formatScoreMove(move, baselineScore) {
    const neu = Number(move && move.new_score);
    const base = Number(baselineScore);
    if (Number.isFinite(neu) && Number.isFinite(base)) {
      const from = Math.round(base);
      const to = Math.round(neu);
      const d = to - from;
      const signed = d > 0 ? `+${d}` : d < 0 ? `−${Math.abs(d)}` : "0";
      return `${from} → ${to} (${signed})`;
    }
    if (move && move.score_delta != null) return formatDelta(move.score_delta);
    return formatDelta((Number(move && move.delta) || 0) * 100);
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
      const scoreDelta = move.score_delta != null
        ? Number(move.score_delta)
        : (Number(move.delta) || 0) * 100;
      const signed = formatScoreMove(move, payload && payload.baseline_score);
      const down = scoreDelta < -0.05;
      const zero = Math.abs(scoreDelta) < 0.05;
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
    const score = scoreOf(data);
    probNum.textContent = score == null ? "—" : String(score);
    const p = Number(data && data.probability);
    const m = (data && data.model) || {};
    const aucNum = m.auc == null ? NaN : Number(m.auc);
    const auc = Number.isFinite(aucNum) ? aucNum.toFixed(2) : "—";
    if (probBase) {
      if (score == null) {
        probBase.textContent = "Finalist Score is a percentile of the calibrated classifier, not a chance of winning.";
      } else {
        probBase.textContent = `resembles past finalists more than ${score}% of all HTN projects (2014–2025)`;
      }
    }
    if (probCaveat) {
      let cal = "—";
      if (Number.isFinite(p)) {
        cal = `${(Math.max(0, Math.min(1, p)) * 100).toFixed(1)}%`;
      }
      probCaveat.textContent = `calibrated finalist probability: ${cal} · AUC ${auc} · leave-one-year-out`;
    }
    if (probWhy) {
      probWhy.innerHTML = "";
      for (const line of (data.why || [])) {
        const li = document.createElement("li");
        li.textContent = String(line);
        probWhy.appendChild(li);
      }
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
    if (probMeta) probMeta.textContent = bits.join(" ");
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

  if (themeLegend) {
    themeLegend.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-remove]");
      if (!btn) return;
      removeThemeLayer(Number(btn.getAttribute("data-remove")));
    });
  }

  if (themeForm) {
    themeForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (themeInFlight) return;
      const text = (themeInput && themeInput.value.trim()) || "";
      if (!text) {
        setThemeNote("no matches");
        return;
      }
      themeInFlight = true;
      if (themeBtn) themeBtn.disabled = true;
      setThemeNote("Highlighting…");
      try {
        const res = await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        let data = {};
        try {
          data = await res.json();
        } catch (_) {
          data = {};
        }
        const seen = new Set();
        const matches = (Array.isArray(data.matches) ? data.matches : []).filter((m) => {
          if (!m || !m.slug || seen.has(m.slug)) return false;
          seen.add(m.slug);
          return true;
        });
        const maxSim = Number(data.max_sim);
        if (!res.ok || !matches.length || !(maxSim > 0)) {
          setThemeNote("no matches");
          return;
        }
        const key = text.toLowerCase();
        const existing = themeLayers.find((l) => l.key === key);
        if (existing) {
          existing.matches = matches;
          existing.max_sim = maxSim;
          existing.query = text;
          themeLayers = themeLayers.filter((l) => l !== existing).concat(existing);
        } else {
          if (themeLayers.length >= 5) themeLayers.shift();
          themeSeq += 1;
          themeLayers.push({
            id: themeSeq,
            key,
            query: text,
            color: nextSearchColor(),
            matches,
            max_sim: maxSim,
          });
        }
        setThemeNote("");
        renderThemeLegend();
        draw();
      } catch (_) {
        setThemeNote("no matches");
      } finally {
        themeInFlight = false;
        if (themeBtn) themeBtn.disabled = false;
      }
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
      preview = null;
      lastPreviewText = "";
      renderCompare(null, null);
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
      const viewName = btn.dataset.view;
      const explore = document.getElementById("view-explore");
      const findings = document.getElementById("view-findings");
      findings.hidden = viewName !== "findings";
      explore.hidden = viewName === "findings";
      if (viewName === "explore") resize();
    });
  });

  function setChatOpen(open) {
    if (!chatPanel) return;
    chatPanel.hidden = !open;
    if (chatFab) {
      chatFab.classList.toggle("is-open", open);
      chatFab.setAttribute("aria-expanded", open ? "true" : "false");
      chatFab.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    }
    if (open && chatInput) chatInput.focus();
  }

  if (chatFab) {
    chatFab.addEventListener("click", () => {
      setChatOpen(!!(chatPanel && chatPanel.hidden));
    });
  }
  const chatClose = document.getElementById("chat-close");
  if (chatClose) chatClose.addEventListener("click", () => setChatOpen(false));
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && chatPanel && !chatPanel.hidden) setChatOpen(false);
  });

  function pctLabel(data) {
    const p = Number(data && data.probability);
    if (!Number.isFinite(p)) return "—";
    return `${Math.round(Math.max(0, Math.min(1, p)) * 100)}%`;
  }

  function neighbourBits(data) {
    const ns = (data && data.neighbours) || [];
    const k = ns.filter((n) => n.finalist).length;
    const fin = ns.find((n) => n.finalist);
    const no = ns.find((n) => !n.finalist);
    const sig = (data && data.signals) || {};
    const tags = (sig.tags || []).slice(0, 6).join(", ");
    return {
      score: scoreOf(data),
      pct: pctLabel(data),
      hardware: sig.hardware ? "hardware" : "software",
      tags: tags || "no tags",
      nearestFin: fin ? fin.title : "none in nearest five",
      nearestNo: no ? no.title : "none in nearest five",
      k: `${k}/${ns.length || 5} neighbours were finalists`,
    };
  }

  function renderCompare(original, previewData) {
    if (!compareEl) return;
    if (!original || !previewData) {
      compareEl.hidden = true;
      compareEl.innerHTML = "";
      if (compareClear) compareClear.hidden = true;
      return;
    }
    const a = neighbourBits(original);
    const b = neighbourBits(previewData);
    const col = (kicker, s) => `
      <div class="compare-col">
        <p class="compare-kicker">${kicker}</p>
        <p class="compare-stat"><strong>${escapeHtml(s.score == null ? "—" : String(s.score))}</strong> Finalist Score</p>
        <p class="compare-stat">calibrated finalist probability: ${escapeHtml(s.pct)}</p>
        <p class="compare-stat">${escapeHtml(s.hardware)} · ${escapeHtml(s.tags)}</p>
        <p class="compare-stat">Nearest finalist: ${escapeHtml(s.nearestFin)}</p>
        <p class="compare-stat">Nearest not a finalist: ${escapeHtml(s.nearestNo)}</p>
        <p class="compare-stat">${escapeHtml(s.k)}</p>
      </div>`;
    compareEl.innerHTML = col("Original", a) + col("Preview", b);
    compareEl.hidden = false;
    if (compareClear) compareClear.hidden = false;
  }

  function clearPreview() {
    preview = null;
    lastPreviewText = "";
    renderCompare(null, null);
    draw();
  }

  function appendChat(role, html) {
    if (!chatList) return;
    const li = document.createElement("li");
    li.className = "chat-msg " + (role === "user" ? "is-you" : "is-bot");
    li.innerHTML = html;
    chatList.appendChild(li);
    if (chatHint) chatHint.hidden = true;
    chatList.scrollTop = chatList.scrollHeight;
    return li;
  }

  function renderFramings(framings) {
    if (!framings || !framings.length) return "";
    return framings.map((f) => `
      <div class="chat-framing">
        <p><strong>${escapeHtml(f.label || "Framing")}</strong> — ${escapeHtml(f.rationale || "")}</p>
        <p>${escapeHtml(f.text || "")}</p>
        <button type="button" class="preview-btn" data-preview-text="${escapeHtml(f.text || "")}">Preview this idea</button>
      </div>
    `).join("");
  }

  async function previewIdea(text) {
    const idea = String(text || "").trim();
    if (!idea || previewInFlight) return;
    if (!query) {
      if (chatStatus) {
        chatStatus.hidden = false;
        chatStatus.textContent = "Place an idea on Explore first, then preview a framing.";
      }
      return;
    }
    previewInFlight = true;
    if (chatStatus) {
      chatStatus.hidden = false;
      chatStatus.classList.add("is-loading");
      chatStatus.textContent = "Scoring the preview…";
    }
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: idea, github: "", devpost: "" }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      preview = data;
      lastPreviewText = idea;
      renderCompare(query, preview);
      draw();
      const quoted = `Finalist Score: original ${scoreOf(query) == null ? "—" : scoreOf(query)} · preview ${scoreOf(preview) == null ? "—" : scoreOf(preview)}. Calibrated probability ${pctLabel(query)} → ${pctLabel(preview)}. Chat did not invent this.`;
      chatThread.push({ role: "assistant", content: quoted });
      appendChat("assistant", `<p>${escapeHtml(quoted)}</p>`);
      if (chatStatus) {
        chatStatus.hidden = true;
        chatStatus.classList.remove("is-loading");
      }
    } catch (err) {
      if (chatStatus) {
        chatStatus.hidden = false;
        chatStatus.classList.remove("is-loading");
        chatStatus.textContent = "Could not preview that framing.";
      }
      console.error(err);
    } finally {
      previewInFlight = false;
    }
  }

  if (chatList) {
    chatList.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-preview-text]");
      if (!btn) return;
      previewIdea(btn.getAttribute("data-preview-text") || "");
    });
  }
  if (compareClear) compareClear.addEventListener("click", clearPreview);

  if (chatForm) {
    chatForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (chatInFlight) return;
      const text = (chatInput && chatInput.value.trim()) || "";
      if (!text) {
        if (chatStatus) {
          chatStatus.hidden = false;
          chatStatus.textContent = "Type a message.";
        }
        return;
      }
      chatInFlight = true;
      if (chatBtn) chatBtn.disabled = true;
      chatThread.push({ role: "user", content: text });
      appendChat("user", `<p>${escapeHtml(text)}</p>`);
      if (chatInput) chatInput.value = "";
      if (chatStatus) {
        chatStatus.hidden = false;
        chatStatus.classList.add("is-loading");
        chatStatus.textContent = "Reframing…";
      }
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: chatThread.slice(-8),
            idea: lastIdeaText || (input && input.value.trim()) || "",
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        const reply = String(data.reply || "Chat is quiet. Place it still works.");
        const framings = Array.isArray(data.framings) ? data.framings : [];
        chatThread.push({ role: "assistant", content: reply });
        appendChat("assistant", `<p>${escapeHtml(reply)}</p>${renderFramings(framings)}`);
        if (chatStatus) {
          chatStatus.hidden = true;
          chatStatus.classList.remove("is-loading");
        }
      } catch (err) {
        appendChat("assistant", "<p>Chat is quiet. Place it still works.</p>");
        if (chatStatus) {
          chatStatus.hidden = false;
          chatStatus.classList.remove("is-loading");
          chatStatus.textContent = "Chat is quiet. Place it still works.";
        }
        console.error(err);
      } finally {
        chatInFlight = false;
        if (chatBtn) chatBtn.disabled = false;
      }
    });
  }

  if (chatInput) {
    chatInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        chatForm.requestSubmit();
      }
    });
  }

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
    el.setAttribute("font-family", kind === "tick" || kind === "num" ? "JetBrains Mono, ui-monospace, monospace" : "Fraunces, Georgia, serif");
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
      indexMapPoints();
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
      indexMapPoints();
    }
    resize();
    loadFindings();
  }

  window.addEventListener("resize", resize);
  if (typeof ResizeObserver !== "undefined" && canvas) {
    new ResizeObserver(() => resize()).observe(canvas);
  }

  (function bindLayoutSplits() {
    const root = document.documentElement;
    const rail = document.querySelector(".rail");
    const splitX = document.getElementById("split-rail-x");
    const splitY = document.getElementById("split-rail-y");
    const railScroll = document.getElementById("rail-scroll");
    const RAIL_MIN = 260;
    const RAIL_MAX = 720;
    const MAIN_MIN = 88;
    try {
      const w = Number(localStorage.getItem("wtn-rail-w"));
      if (Number.isFinite(w) && w >= RAIL_MIN) {
        root.style.setProperty("--rail-w", `${Math.min(RAIL_MAX, w)}px`);
      }
      const h = Number(localStorage.getItem("wtn-rail-main-h"));
      if (Number.isFinite(h) && h >= MAIN_MIN) {
        root.style.setProperty("--rail-main-h", `${h}px`);
      }
    } catch (_) { /* ignore */ }

    function bind(el, kind) {
      if (!el) return;
      el.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        el.setPointerCapture(ev.pointerId);
        document.body.classList.add("is-resizing");
        if (kind === "y") document.body.classList.add("is-resizing-y");
        const move = (e) => {
          if (kind === "x") {
            const explore = document.querySelector(".explore");
            if (!explore) return;
            const left = explore.getBoundingClientRect().left;
            const next = Math.max(RAIL_MIN, Math.min(RAIL_MAX, e.clientX - left));
            root.style.setProperty("--rail-w", `${Math.round(next)}px`);
          } else if (rail && railScroll) {
            const top = railScroll.getBoundingClientRect().top;
            const south = document.getElementById("rail-south");
            const southMin = 120;
            const maxH = rail.getBoundingClientRect().height - southMin - 48;
            const next = Math.max(MAIN_MIN, Math.min(maxH, e.clientY - top));
            root.style.setProperty("--rail-main-h", `${Math.round(next)}px`);
            if (south) south.style.minHeight = `${southMin}px`;
          }
          resize();
        };
        const up = () => {
          document.body.classList.remove("is-resizing", "is-resizing-y");
          el.removeEventListener("pointermove", move);
          el.removeEventListener("pointerup", up);
          el.removeEventListener("pointercancel", up);
          try {
            const w = root.style.getPropertyValue("--rail-w").trim();
            const h = root.style.getPropertyValue("--rail-main-h").trim();
            if (w.endsWith("px")) localStorage.setItem("wtn-rail-w", String(parseInt(w, 10)));
            if (h.endsWith("px")) localStorage.setItem("wtn-rail-main-h", String(parseInt(h, 10)));
          } catch (_) { /* ignore */ }
          resize();
        };
        el.addEventListener("pointermove", move);
        el.addEventListener("pointerup", up);
        el.addEventListener("pointercancel", up);
      });
    }
    bind(splitX, "x");
    bind(splitY, "y");
  })();

  boot();
})();
