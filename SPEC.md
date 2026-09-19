# Prior Art — build spec

Drop this at the repo root. It's written to be handed to Cursor as context.

---

## What this is

A web app over a scraped corpus of every Hack the North project since 2014 (~2,000 submissions, ~161 labelled finalists). A user types a project idea; the app embeds it, places it on a 2D map of twelve years of projects, shows its nearest historical neighbours with finalist status, and gives a calibrated probability that it would be a finalist.

This is a 20-hour hackathon build demoed live to judges standing 4–6 feet from a laptop. Optimise for: works reliably, readable from a distance, no build step.

## Hard constraints

- **Python 3.11 + FastAPI backend. Plain HTML/CSS/JS frontend served by FastAPI.**
- **No React, no Next, no Vite, no npm, no bundler, no TypeScript.** A build step that breaks at 2am is a project-ending risk. One `index.html`, one `app.js`, one `style.css`.
- No Docker. No database server — parquet and JSON files on disk.
- Everything must run from `uvicorn server:app --reload` with no other services.
- Never run dimensionality reduction, model training, or bulk embedding inside a request handler. Precompute to disk; serve files.

## Layout

```
schema.py          # shared record definition (agreed with Richa at 09:00)
sample.json        # 20 hand-written rows matching schema — build against this first
data/
  corpus.parquet   # arrives from Richa at 13:30
  embeddings.npy   # precomputed, row order matches corpus
  map.json         # precomputed 2D coords + metadata for the client
  model.pkl        # fitted classifier + calibrator + UMAP transform
  findings.json    # chart data from Richa
build.py           # offline: embed → reduce → train → write the files above
server.py          # FastAPI
web/
  index.html
  app.js
  style.css
```

## Data contract

Richa produces `data/corpus.parquet` with one row per project:

```python
{
  "slug": str,          # devpost slug, unique, the join key
  "year": int,          # 2014..2025
  "title": str,
  "tagline": str,       # one-liner
  "description": str,   # full body text
  "sections": dict,     # {"inspiration": str, "challenges": str, ...}
  "built_with": list,   # tech tags
  "team_size": int,
  "has_video": bool,
  "has_repo": bool,
  "prizes": list,
  "finalist": bool,     # THE LABEL
}
```

`sample.json` is a list of 20 of these, hand-written. **Build and test everything against `sample.json` until 13:30.** Loading code must accept either source behind one function so the swap is a one-line change:

```python
def load_corpus(path="data/corpus.parquet"):
    """Falls back to sample.json when the parquet isn't there yet."""
```

If you need a field the schema doesn't have, add it to `schema.py`, push, and tell Richa — then keep working with a default value. Never block on her.

---

## build.py — the offline pipeline

Run manually whenever the corpus updates. Writes everything the server reads.

1. **Embed.** `text = title + ". " + tagline + ". " + description[:4000]` per project. Use OpenAI `text-embedding-3-small`, batched 100 at a time. **Cache by slug in `data/emb_cache.json`** so a re-run only embeds new rows — you will re-run this several times and re-embedding 2,000 projects each time will eat your afternoon and your credits. Write `embeddings.npy` with row order matching the corpus.

2. **Reduce.** Fit UMAP (`n_neighbors=15, min_dist=0.1, n_components=2`) on all embeddings. **Persist the fitted reducer** — you need `.transform()` on the user's new input at request time. Write `map.json`:
   ```json
   {"points": [{"x": 1.2, "y": -3.4, "slug": "...", "title": "...",
                "year": 2024, "finalist": true, "tagline": "..."}],
    "bounds": {"x0":..., "y0":..., "x1":..., "y1":...}}
   ```
   If UMAP is slow or flaky, fall back to `sklearn.manifold.TSNE` or even PCA. The map existing matters far more than which algorithm made it.

3. **Train.** Features = PCA of embeddings down to ~50 dims, concatenated with structured features (`team_size`, `has_video`, `has_repo`, `len(built_with)`, `len(description)`, `len(prizes)`, `year`).
   - Model: `LogisticRegression(class_weight='balanced')` first. Try `HistGradientBoostingClassifier` second; keep whichever wins honestly.
   - **Validation: leave-one-year-out, not a random split.** Each year has a fixed number of finalist slots and taste shifts over time, so a random split leaks both the base rate and the era. Implement with `sklearn.model_selection.LeaveOneGroupOut`, groups = `year`.
   - Report mean AUC across held-out years, with the per-year spread. Write it into `model.pkl` metadata so the UI can display it.
   - Wrap in `CalibratedClassifierCV(method='isotonic')` so the displayed probability means something.
   - **A modest AUC (0.6–0.7) is the expected, honest result. Do not tune toward a big number by leaking.** The UI shows the real figure.

---

## server.py — API

```
GET  /                 → web/index.html
GET  /api/map          → data/map.json (cache in memory on startup)
GET  /api/findings     → data/findings.json
POST /api/ask          → body {"text": "..."}
```

`/api/ask` returns:

```json
{
  "point": {"x": 0.4, "y": 1.9},
  "neighbours": [
    {"slug":"pathsense-athy2r","title":"PathSense","year":2024,
     "tagline":"...","finalist":true,"similarity":0.83}
  ],
  "probability": 0.21,
  "model": {"auc": 0.67, "auc_spread": [0.58, 0.74], "n_train": 1974, "n_finalists": 161}
}
```

Implementation: embed the input (one API call), `reducer.transform()` for coords, cosine similarity against `embeddings.npy` for top-5 neighbours, `model.predict_proba()` for the probability. Everything else is already in memory.

**Error handling matters here** — this endpoint runs live in front of a judge. Wrap the embedding call in a try/except with a 10s timeout; on failure return neighbours computed from a local TF-IDF fallback rather than a 500. A degraded answer beats a crash.

---

## Frontend

Two views, toggled by a tab: **Explore** (default) and **Findings**.

### Explore

- **The map, filling most of the screen.** Render ~2,000 points on a `<canvas>`, never as DOM nodes. Non-finalists as small muted dots, finalists larger and in the accent colour. Hover shows a tooltip with title + year. This must be visible and populated on load, before any input — the map at rest is the first thing a judge sees.
- **An input, prominent, above or beside the map:** "Describe your project." Submit on Enter.
- **On submit:** animate the new point in (a brief pulse ring), draw connecting lines to the 5 neighbours, and highlight them.
- **Results panel:** the 5 neighbour cards (title, year, tagline, finalist badge) and the probability.
- **Type sizing: the probability renders at 48px minimum.** Judges stand 4–6 feet back; most teams render their headline number at 14px and nobody past the first row can read it. Directly under it, in small text: the AUC, the number of training projects, and the words "leave-one-year-out". That caveat line is a credibility feature, not a disclaimer — do not hide it.
- **Lead with neighbours, not the number.** Neighbours are more interesting, more defensible, and don't depend on the classifier working at all.

### Findings

Three or four charts from `findings.json`. Each captioned with the actual claim ("Demo videos don't predict finalists"), not a chart title. Canvas or inline SVG, drawn by hand — do not add a charting library.

### Visual

Dark theme. The map is the hero; everything else is quiet around it. One accent colour, used only for finalists and the active point. No gradients, no rounded-everything, no emoji.

---

## Build order (acceptance criteria per step)

1. **FastAPI serves `index.html`; `/api/map` returns sample data.** Done when the page loads and logs the JSON.
2. **Canvas renders points from `/api/map`.** Done when 20 sample dots appear, correctly coloured, with working hover.
3. **`/api/ask` embeds input and returns neighbours from the sample.** Done when typing text returns 5 plausible neighbours.
4. **UI wires input → new point → neighbour cards.** Done when the full round trip works on sample data. **This is the whole demo, working, on fake data — reach it before 13:00.**
5. **Swap in the real corpus.** Done when 2,000 points render and neighbours are real projects.
6. **Classifier + LOYO CV + calibration.** Done when `/api/ask` returns a probability and a real AUC.
7. **Findings view.**
8. **Sentry** — tracing plus session replay (two products beyond error monitoring, which their prize requires). Tracing will genuinely show that the embedding call is the bottleneck; cache it and note the before/after number, because that's the sentence you say to their judge.
9. **Polish:** type sizes, the pulse animation, empty states.

## Cut order if behind

Cut from the bottom: Findings view → classifier (ship neighbours + map only) → Sentry.
**Never cut the map.** It needs only embeddings and cosine similarity and it's the thing that makes people stop walking.

## Non-goals

No auth, no persistence of user queries, no mobile layout, no dark/light toggle, no tests beyond a smoke check on `/api/ask`, no deployment — it runs on a laptop on a table.
