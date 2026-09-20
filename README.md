# Prior Art

Every Hack the North project since 2014, in one searchable pile. Type in an idea
and find out whether someone already built it, and whether they made the top 12.

## Why

Every hackathon starts the same way. Four people, one table, and about twenty
minutes in somebody says "wait, has this been done already?" Nobody knows. You
search Devpost for five minutes, find nothing conclusive, and build it anyway.

We wanted a real answer. So we scraped all 3,443 Hack the North submissions going
back to 2014, worked out which 161 of them made finalist, and built something you
can type an idea into.

It shows you the closest projects from twelve years of history, what they were
built with, who was on the team, and how many of them won. It's not a fortune
teller. It's closer to: here's the neighbourhood your idea lives in, and here's how
that neighbourhood has done.

Turns out the honest answer to "will this win?" is usually **4.7%**, because that's
how many projects become finalists. But some neighbourhoods do better than others,
and that's the interesting part.

## Some things we found

- **Nobody used an LLM until 2022.** Then 19% of projects that year, 46% in 2023,
  59% in 2025. Nothing else in twelve years got picked up that fast.
- **Blockchain peaked in 2017** at 6.9% of projects and never really came back.
- **VR was 18% of everything in 2014.** It's 4.6% now.
- **Writeups got three times longer.** 131 words in 2014, 465 in 2025.
- **Demo videos exploded in 2020**, from 15% to 72%, and stayed high. Turns out
  when nobody can walk up to your table, you film the thing.
- **Being silly is not a penalty.** Projects that describe themselves in playful
  terms made finalist 6.4% of the time. Projects with earnest "solving a real
  problem" framing: 5.4%. That gap is well inside the error bars so we're not
  claiming jokes win, but the usual "make it useful" advice doesn't show up
  anywhere in the data.

## Beyond Hack the North

HTN on its own is the default. We also scraped **UofTHacks** (8 editions) and **GenAI
Genesis** (3), so you can ask the same question against a wider Toronto field — 4,680
projects instead of 3,443. Point `CORPUS_PATH` at `data/corpus_multi.parquet` to use it.

Worth knowing the two pools measure slightly different things. HTN publishes a museum of
its finalists, so there we know the real top ~12 each year. Nobody else does, so
elsewhere the only signal is the Devpost prize badge, which includes sponsor tracks. The
`won_prize` column means the same thing everywhere if you want to compare fairly.

The full dataset and how we built it is in [DATASET.md](DATASET.md).

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://127.0.0.1:8000

Until `data/corpus.parquet` exists, the server loads `sample.json` (20 hand-written
rows). Same `load_corpus()` either way. If the parquet lives somewhere else, point
`CORPUS_PATH` at it in your `.env`.

## Offline artifacts

```bash
python build.py
```

Writes `data/embeddings.npy`, `data/map.json`, `data/model.pkl`. Cached embeddings
live in `data/emb_cache.json` so a re-run only embeds new slugs. Needs
`OPENAI_API_KEY` for real embeddings; without it, build.py falls back to TF-IDF.

To rebuild the corpus itself from scratch, that's `src/scrape.py` then
`src/build.py`. Takes about 40 minutes, most of it waiting politely on Devpost.

## API

| Method | Path | |
|---|---|---|
| GET | `/` | `web/index.html` |
| GET | `/api/map` | 2D points |
| GET | `/api/findings` | chart data |
| POST | `/api/ask` | `{"text": "..."}` |

`/api/ask` uses OpenAI `text-embedding-3-small` when a key is present and
embeddings are on disk. If that call fails or times out (10s), neighbours come from
a local TF-IDF index instead of a 500.

## Who did what

Sara built the app ([SPEC.md](SPEC.md)). Richa built the corpus
([RICHA.md](RICHA.md)). The join key is `slug`.
