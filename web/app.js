(() => {
  const canvas = document.getElementById("map");
  const tooltip = document.getElementById("tooltip");
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const askBtn = document.getElementById("ask-btn");
  const neighbourList = document.getElementById("neighbour-list");
  const neighboursEmpty = document.getElementById("neighbours-empty");
  const probPanel = document.getElementById("prob-panel");
  const probNum = document.getElementById("prob-num");
  const probMeta = document.getElementById("prob-meta");
  const corpusMeta = document.getElementById("corpus-meta");
  const chartsEl = document.getElementById("charts");
  const findingsNote = document.getElementById("findings-note");

  const ACCENT = "#e8a317";
  const MUTE = "#3c3c42";
  const YOU = "#f4f0ea";

  let mapData = { points: [], bounds: { x0: -1, y0: -1, x1: 1, y1: 1 } };
  let query = null;
  let hover = null;
  let pulse = 0;
  let raf = 0;

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
    if (query) {
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

    if (query) {
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
    if (!items.length) {
      neighboursEmpty.hidden = false;
      return;
    }
    neighboursEmpty.hidden = true;
    for (const n of items) {
      const li = document.createElement("li");
      li.className = "card" + (n.finalist ? " is-hit" : "");
      li.innerHTML = `
        <div class="card-top">
          <span class="card-title">${escapeHtml(n.title)}</span>
          <span class="card-year">${n.year}</span>
        </div>
        <p class="card-tag">${escapeHtml(n.tagline || "")}</p>
        ${n.finalist ? '<div class="badge">Finalist</div>' : ""}
      `;
      neighbourList.appendChild(li);
    }
  }

  function renderProb(data) {
    probPanel.hidden = false;
    const pct = Math.round((data.probability || 0) * 100);
    probNum.textContent = `${pct}%`;
    const m = data.model || {};
    const auc = m.auc == null ? "—" : Number(m.auc).toFixed(2);
    const n = m.n_train ?? "—";
    const spread = Array.isArray(m.auc_spread) && m.auc_spread.length === 2
      ? ` (${Number(m.auc_spread[0]).toFixed(2)}–${Number(m.auc_spread[1]).toFixed(2)})`
      : "";
    probMeta.textContent = `AUC ${auc}${spread}  ·  ${n} training projects  ·  leave-one-year-out`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    askBtn.disabled = true;
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      query = data;
      pulse = 0;
      cancelAnimationFrame(raf);
      renderNeighbours(data.neighbours || []);
      renderProb(data);
      draw();
      raf = requestAnimationFrame(tick);
    } catch (err) {
      neighboursEmpty.hidden = false;
      neighboursEmpty.textContent = "Could not place that idea. Try again.";
      console.error(err);
    } finally {
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
      val.textContent = `${Math.round(b.value * 100)}%`;
      svg.appendChild(val);
    });
    return svg;
  }

  function drawLines(chart) {
    const svg = svgEl("svg", { viewBox: "0 0 400 220" });
    const series = chart.series || [];
    const years = [...new Set(series.flatMap((s) => s.points.map((p) => p.year)))].sort();
    const values = series.flatMap((s) => s.points.map((p) => p.value));
    const max = Math.max(0.01, ...values);
    const xOf = (year) => 30 + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * 350;
    const yOf = (v) => 180 - (v / max) * 150;
    const classes = ["chart-line", "chart-line chart-line-2", "chart-line chart-line-3"];
    series.forEach((s, i) => {
      const d = s.points
        .sort((a, b) => a.year - b.year)
        .map((p, idx) => `${idx ? "L" : "M"}${xOf(p.year)},${yOf(p.value)}`)
        .join(" ");
      svg.appendChild(svgEl("path", { d, class: classes[i % classes.length] }));
    });
    years.forEach((y) => {
      const t = svgEl("text", { x: xOf(y), y: 205, "text-anchor": "middle", class: "chart-axis" });
      t.textContent = String(y);
      svg.appendChild(t);
    });
    return svg;
  }

  async function loadFindings() {
    const res = await fetch("/api/findings");
    const data = await res.json();
    if (data.source === "sample") {
      findingsNote.textContent = "Sample claims until Richa ships data/findings.json.";
    } else {
      findingsNote.textContent = "";
    }
    chartsEl.innerHTML = "";
    for (const chart of data.charts || []) {
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
        key.textContent = chart.series.map((s) => s.label).join("   ·   ");
        box.appendChild(key);
      }
      chartsEl.appendChild(box);
    }
  }

  async function boot() {
    const [mapRes, cfgRes] = await Promise.all([fetch("/api/map"), fetch("/api/config")]);
    mapData = await mapRes.json();
    const cfg = await cfgRes.json();
    corpusMeta.textContent = `${cfg.n} projects  ·  ${cfg.n_finalists} finalists  ·  ${cfg.source}`;
    console.log("map", mapData);
    if (cfg.sentry_dsn) {
      const s = document.createElement("script");
      s.src = "https://browser.sentry-cdn.com/8.33.1/bundle.tracing.replay.min.js";
      s.crossOrigin = "anonymous";
      s.onload = () => {
        window.Sentry && window.Sentry.init({
          dsn: cfg.sentry_dsn,
          tracesSampleRate: 1.0,
          replaysSessionSampleRate: 1.0,
          integrations: [
            window.Sentry.browserTracingIntegration(),
            window.Sentry.replayIntegration(),
          ],
        });
      };
      document.head.appendChild(s);
    }
    resize();
    loadFindings();
  }

  window.addEventListener("resize", resize);
  boot();
})();
