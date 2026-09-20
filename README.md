# 🏔️ Win the North

Every Hack the North project since 2014, in one interactive space. Type in your idea
and find out whether someone already built it, whether they won, and how to make a few changes to win a prize.

## Why

Every hackathon starts the same way. A team, one table, and around half an hour in somebody asks "wait, has this been done already? Would it be a good idea?" Usually, nobody knows. You search Devpost for five minutes, find nothing definitive, and build it anyway.

We wanted a real answer. So we scraped all 3,443 Hack the North submissions going
back to the beginning in 2014, worked out which 161 of them made finalist, and built something you can type your idea into and find out.

Win the North shows you the most similar projects from the past twelve years of Hack the North, what they were built with, who was on the team, and how many of them won. It finds the neighbourhood the idea is in, and explains how that neighbourhood has done in competition.

Turns out the answer to "Will this win?" is usually **4.7%**, because that's
how many projects become finalists. But some neighbourhoods of ideas do better than others, and that's the interesting part.

## Some things we found

- **Nobody used an LLM until 2022.** Then 19% of projects that year, 46% in 2023,
  59% in 2025.
- **Blockchain peaked in 2017** at 6.9% of projects and never really came back.
- **VR was 18% of everything in 2014.** It's 4.6% now.
- **Being silly is not a penalty.** Projects that described themselves in playful
  terms made finalist 6.4% of the time. Projects with impactful "solving a real
  problem" framing made it 5.4% of the time.

## Beyond Hack the North

HTN on its own is the default search space. We also scraped **UofTHacks** (8 editions) and **GenAI Genesis** (3), so you can ask the same question within a wider area of projects in Toronto. Point `CORPUS_PATH` at `data/corpus_multi.parquet` to use it.

The default HTN search space, and the broader Toronto area project space measure slightly different things. Since HTN publishes a museum of its finalists, we know the real top ~12 each year. Nobody else does this, so elsewhere the only signal is the Devpost prize badge, which includes sponsor tracks. The `won_prize` column means the same thing everywhere if you want to compare fairly.

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
