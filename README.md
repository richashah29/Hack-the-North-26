# Prior Art

A map of every Hack the North project since 2014. Type an idea; see its nearest neighbours and a leave-one-year-out finalist probability.

Sara owns the app (`SPEC.md`). Richa owns the corpus (`RICHA.md`). The join key is `slug`.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://127.0.0.1:8000

Until `data/corpus.parquet` exists, the server loads `sample.json` (20 hand-written rows). Same `load_corpus()` either way.

## Offline artifacts

```bash
python build.py
```

Writes `data/embeddings.npy`, `data/map.json`, `data/model.pkl`. Cached embeddings live in `data/emb_cache.json` so a re-run only embeds new slugs. Needs `OPENAI_API_KEY` for real embeddings; without it, build.py falls back to TF-IDF.

## API

| Method | Path | |
|---|---|---|
| GET | `/` | `web/index.html` |
| GET | `/api/map` | 2D points |
| GET | `/api/findings` | chart data |
| POST | `/api/ask` | `{"text": "..."}` |

`/api/ask` uses OpenAI `text-embedding-3-small` when a key is present and embeddings are on disk. If that call fails or times out (10s), neighbours come from a local TF-IDF index instead of a 500.
