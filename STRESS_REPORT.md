# Stress report

Target: `http://127.0.0.1:8000`
Ran: 2026-09-19 09:54 EDT
**76 passed, 0 failed, 76 checks.**

Fixes applied so the bar would hold:
- UMAP transform serialized under a lock (concurrent `/api/ask` was killing the worker via Numba).
- OpenAI `max_retries=0` and 6s timeout; Gemini 8s budget; missing/invalid/slow keys fall back instead of hanging.
- `/api/ask` `source=tfidf` when embeddings fail; ES failure falls back to in-memory cosine (`source=local`).
- Load-time alignment: `len(corpus) == len(embeddings) == len(map points)` or a hard error. Missing embeddings/model boot on TF-IDF. Corrupt/missing prizes/event/map/corpus raise a clear startup error.
- `json_safe()` strips numpy / NaN / inf on every JSON response.
- Coach never 500s; invented prizes and win-claims are dropped; `time_budget=0` keeps moves and marks them infeasible.
- Frontend: in-flight guards, `—` for null/NaN AUC and probability, wrap long titles, catch a dead `/api/map`.

Acceptance bar: no judge-typed input and no dead dependency may hang, 500, blank the screen, or dump a stack trace. Everything degrades to a valid visible response within ~10 seconds.

## 1 input abuse

| Result | Case | Detail |
|---|---|---|
| PASS | ask empty string | status=400 0.01s HTTP 400 |
| PASS | ask whitespace only | status=400 0.00s HTTP 400 |
| PASS | ask single character | status=200 9.02s None |
| PASS | ask one emoji | status=200 2.01s None |
| PASS | ask 50000-char paste | status=422 0.01s HTTP 422 |
| PASS | ask Mandarin | status=200 1.83s None |
| PASS | ask Arabic RTL | status=200 1.78s None |
| PASS | ask accented French | status=200 1.69s None |
| PASS | ask pure numbers | status=200 1.96s None |
| PASS | ask pure punctuation | status=200 1.67s None |
| PASS | ask newlines | status=200 1.62s None |
| PASS | ask html script | status=200 1.82s None |
| PASS | ask sql-ish | status=200 2.90s None |
| PASS | ask null bytes | status=200 1.91s None |
| PASS | ask control chars | status=200 1.64s None |
| PASS | ask prompt injection | status=200 1.63s None |
| PASS | coach empty string | status=400 0.00s HTTP 400 |
| PASS | coach whitespace | status=400 0.00s HTTP 400 |
| PASS | coach emoji | status=200 6.12s None |
| PASS | coach 50000-char | status=422 0.01s HTTP 422 |
| PASS | coach prompt injection | status=200 8.38s None |
| PASS | coach html | status=200 8.83s None |
| PASS | malformed missing text | status=400 HTTP 400 |
| PASS | malformed wrong type text | status=422 HTTP 422 |
| PASS | malformed extra fields | status=200 None |
| PASS | malformed coach wrong type | status=422 HTTP 422 |
| PASS | malformed coach extra fields | status=200 None |
| PASS | non-JSON body | status=422 |

28/28 passed.

## 2 dependencies

| Result | Case | Detail |
|---|---|---|
| PASS | OpenAI missing → tfidf source | status=200 source=tfidf backend=tfidf 0.01s |
| PASS | Gemini missing → empty moves | status=200 moves=[] 0.01s |
| PASS | ES unconfigured still answers | source=tfidf |
| PASS | OpenAI invalid key → tfidf | status=200 source=tfidf 0.39s None |
| PASS | OpenAI timeout → tfidf | status=200 source=tfidf 6.36s hang=False |
| PASS | OpenAI rate-limit → tfidf | status=200 source=tfidf 0.35s |
| PASS | Gemini invalid JSON → empty moves | status=200 moves=[] 0.11s |
| PASS | Gemini invented prize dropped | status=200 n=0 0.05s |
| PASS | Gemini probability in text stripped/ignored | baseline=0.5455 blob='' |
| PASS | Gemini timeout → empty moves | status=200 8.03s hang=False |
| PASS | Elasticsearch down → local cosine | status=200 source=local backend=openai 0.68s |
| PASS | Elasticsearch slow → local/tfidf | status=200 source=local 3.02s hang=False |
| PASS | all three down /api/ask | status=200 source=tfidf 0.27s |
| PASS | all three down /api/coach | status=200 moves=[] 0.04s |

14/14 passed.

## 3 startup

| Result | Case | Detail |
|---|---|---|
| PASS | missing embeddings.npy + model.pkl boots | rc=0 out='\nartifact fallback classifier skipped (This solver needs samples of at least 2 classes in the data, but the data contains only one class: np.int64(1))\nloaded corpus=8 embeddings=0 map=8\nLOAD_OK 8 0 8\n' err='' |
| PASS | missing embeddings logs fallback | logged |
| PASS | embeddings/corpus mismatch raises | rc=1   File "/Users/saraparvaresh/hackthenorth/engine.py", line 448, in _load_embeddings     raise RuntimeError( RuntimeError: embeddings.npy has 2 rows but corpus has 8. Neighbour rows would attach to the wrong projects. Rebuild with build.py.  |
| PASS | corrupt map.json raises | rc=1 meError: map.json unreadable at /var/folders/nf/db37b2sx22s5pws56n_h7vth0000gn/T/priorart-stress-dbtt5mgu/corrupt_map.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)  |
| PASS | map/corpus mismatch raises | rc=1 araparvaresh/hackthenorth/engine.py", line 470, in _load_map     raise RuntimeError( RuntimeError: map.json has 1 points but corpus has 8. The map would pin the wrong projects. Rebuild with build.py.  |
| PASS | missing prizes.json raises | rc=1 quire_prizes_file     raise RuntimeError(f"prizes.json missing at {src}") RuntimeError: prizes.json missing at /var/folders/nf/db37b2sx22s5pws56n_h7vth0000gn/T/priorart-stress-dbtt5mgu/no_prizes.json  |
| PASS | corrupt prizes.json raises | rc=1 Error: prizes.json unreadable at /var/folders/nf/db37b2sx22s5pws56n_h7vth0000gn/T/priorart-stress-dbtt5mgu/bad_prizes.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)  |
| PASS | missing event.json raises | rc=1  _require_event_file     raise RuntimeError(f"event.json missing at {src}") RuntimeError: event.json missing at /var/folders/nf/db37b2sx22s5pws56n_h7vth0000gn/T/priorart-stress-dbtt5mgu/no_event.json  |
| PASS | corrupt event.json raises | rc=1 able at {src}: {exc}") from exc RuntimeError: event.json unreadable at /var/folders/nf/db37b2sx22s5pws56n_h7vth0000gn/T/priorart-stress-dbtt5mgu/bad_event.json: Invalid isoformat string: 'not-a-date'  |
| PASS | corrupt corpus.parquet raises | rc=1 7vth0000gn/T/priorart-stress-dbtt5mgu/bad.parquet: Could not open Parquet input source '<Buffer>': Parquet magic bytes not found in footer. Either the file is corrupted or this is not a parquet file.  |

10/10 passed.

## 4 serialization

| Result | Case | Detail |
|---|---|---|
| PASS | json_safe strips numpy/nan/inf | {'a': 0.5, 'b': 3, 'c': [1.0, 2.0], 'd': 0.0, 'e': 0.0} |
| PASS | /api/config json-safe finite | status=200 bad=[] 0.02s |
| PASS | /api/map json-safe finite | status=200 bad=[] 0.04s |
| PASS | /api/findings json-safe finite | status=200 bad=[] 0.00s |
| PASS | /api/ask json-safe finite | status=200 |
| PASS | /api/coach json-safe finite | status=200 |

6/6 passed.

## 5 invariants

| Result | Case | Detail |
|---|---|---|
| PASS | ask probability in [0,1] | 0.0392 |
| PASS | AUC plausible or null | auc=0.764 |
| PASS | live corpus==map==embeddings | n=3443 map=3443 emb=3443 |
| PASS | time_budget=0 keeps moves, marks infeasible | n=3 feasible=[False, False, False] None |
| PASS | large budget → feasible | n=0 None |
| PASS | effort_hours numeric | [] |
| PASS | clock math no crash | hours=22.1 |

7/7 passed.

## 6 concurrency

| Result | Case | Detail |
|---|---|---|
| PASS | 20 simultaneous /api/ask | 20/20 wall=22.2s 500/hang=0 |
| PASS | responses not a single corrupted buffer | unique neighbour triples=10 |

2/2 passed.

## 7 frontend

| Result | Case | Detail |
|---|---|---|
| PASS | map is a canvas, not 3443 DOM nodes |  |
| PASS | long title CSS wraps |  |
| PASS | null title/tagline never print undefined |  |
| PASS | empty coach moves have a sentence |  |
| PASS | AUC null renders em dash |  |
| PASS | NaN probability renders em dash |  |
| PASS | ask in-flight guard |  |
| PASS | coach in-flight guard |  |
| PASS | boot catch so a dead /api/map is not a blank screen |  |

9/9 passed.

## Frontend notes (manual)

- Map draws 3,443 points on a single `<canvas>`, not DOM nodes.
- Neighbour / coach cards wrap long titles (`overflow-wrap: anywhere`).
- Missing narrative and empty coach moves render copy, never the word `undefined`.
- Place it / Coach me ignore double-clicks while a request is in flight.

Browser check on `http://127.0.0.1:8000/?v=9`: one `<canvas>`, corpus meta `3443 projects · 161 finalists`, Place it disabled while in flight then 5 neighbour cards at **5%**, Coach me disabled while in flight then 3 moves (`+4.9%` / `+2%` / `-2.9%`). Body text never contained `undefined`.

