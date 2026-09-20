"""Offline pipeline: embed → reduce → train → write artifacts the server reads.

Run manually whenever the corpus updates:

    python build.py

Never call this from a request handler.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import joblib
import numpy as np
from dotenv import load_dotenv
from sklearn.calibration import CalibratedClassifierCV
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from engine import DATA, EMB_PATH, MAP_PATH, MODEL_PATH, _bounds, _finalist_proba, _point_payload, _structured_features
from schema import CORPUS_PATH, ROOT, load_corpus, load_explore_corpus

load_dotenv()

CACHE_PATH = DATA / "emb_cache.json"
BATCH = 64
EMBED_RETRIES = 3


def _cache_load() -> dict[str, list[float]]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _cache_save(cache: dict[str, list[float]]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def _embed_input(project) -> str:
    text = (project.embed_text() or "").strip()
    return text if text else (project.slug or "project")


def _cache_dim(cache: dict[str, list[float]]) -> int:
    sample = next(iter(cache.values()), None)
    return len(sample) if isinstance(sample, list) else 0


def embed_projects(projects) -> np.ndarray:
    cache = _cache_load()
    missing = [p for p in projects if p.slug not in cache]
    key = os.getenv("OPENAI_API_KEY")
    def _tfidf() -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(max_features=512)
        arr = vec.fit_transform([_embed_input(p) for p in projects]).toarray().astype(np.float32)
        np.save(EMB_PATH, arr)
        print(f"Wrote TF-IDF {EMB_PATH} {arr.shape}")
        return arr

    if missing and not key:
        if _cache_dim(cache) >= 100:
            raise RuntimeError(
                f"{len(missing)} slugs need embeddings but OPENAI_API_KEY is unset. "
                "Not overwriting the OpenAI cache with TF-IDF."
            )
        print("No OPENAI_API_KEY; writing TF-IDF embeddings so the rest of the pipeline can run.")
        return _tfidf()

    if missing:
        from openai import OpenAI

        kwargs = {"api_key": key, "timeout": 60.0}
        base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base:
            kwargs["base_url"] = base
        client = OpenAI(**kwargs)
        print(f"Embedding {len(missing)} new rows ({len(cache)} cached).")
        try:
            for i in range(0, len(missing), BATCH):
                batch = missing[i : i + BATCH]
                last_err: Exception | None = None
                for attempt in range(EMBED_RETRIES):
                    try:
                        resp = client.embeddings.create(
                            model="text-embedding-3-small",
                            input=[_embed_input(p) for p in batch],
                        )
                        ordered = sorted(resp.data, key=lambda item: int(getattr(item, "index", 0)))
                        for p, item in zip(batch, ordered):
                            cache[p.slug] = list(item.embedding)
                        _cache_save(cache)
                        last_err = None
                        break
                    except Exception as exc:
                        last_err = exc
                        wait = 2 ** attempt
                        print(f"  batch {i // BATCH + 1} attempt {attempt + 1} failed ({exc}); retry in {wait}s")
                        time.sleep(wait)
                if last_err is not None:
                    raise last_err
                print(f"  {min(i + BATCH, len(missing))}/{len(missing)}")
        except Exception as e:
            if _cache_dim(cache) >= 100:
                still = sum(1 for p in projects if p.slug not in cache)
                raise RuntimeError(
                    f"OpenAI embed failed ({e}); {still} slugs still missing. "
                    "Cached OpenAI vectors were kept."
                ) from e
            print(f"OpenAI embed failed ({e}); falling back to TF-IDF.")
            return _tfidf()

    still = [p.slug for p in projects if p.slug not in cache]
    if still:
        raise RuntimeError(f"{len(still)} slugs still missing from emb_cache.json")

    dim = _cache_dim(cache)
    arr = np.zeros((len(projects), dim), dtype=np.float32)
    for i, p in enumerate(projects):
        arr[i] = np.array(cache[p.slug], dtype=np.float32)
    np.save(EMB_PATH, arr)
    print(f"Wrote {EMB_PATH} {arr.shape}")
    return arr


def place_unmapped(projects, embeddings: np.ndarray) -> None:
    """Keep the HTN UMAP. Sit extra-event rows in that space with the saved reducer."""
    if not MAP_PATH.exists():
        print("map.json missing — skip extra-event placement")
        return
    payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    points = list(payload.get("points") or [])
    by_slug = {str(pt.get("slug") or ""): pt for pt in points if pt and pt.get("slug")}
    index = {p.slug: i for i, p in enumerate(projects)}
    for p in projects:
        rec = by_slug.get(p.slug)
        if rec is None:
            continue
        rec["event"] = p.event or rec.get("event") or ""
        rec["title"] = str(p.title or rec.get("title") or "")
        rec["year"] = int(p.year or rec.get("year") or 0)
        rec["finalist"] = bool(p.finalist)
        rec["tagline"] = str(p.tagline or rec.get("tagline") or "")

    missing_i = [i for i, p in enumerate(projects) if p.slug not in by_slug]
    if not missing_i:
        xs = [float(pt.get("x") or 0) for pt in points]
        ys = [float(pt.get("y") or 0) for pt in points]
        payload["points"] = points
        payload["bounds"] = _bounds(xs, ys) if xs else payload.get("bounds") or {}
        MAP_PATH.write_text(json.dumps(payload), encoding="utf-8")
        print(f"map.json already has every explore slug ({len(points)} points)")
        return

    arr = np.nan_to_num(np.asarray(embeddings, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    reducer = None
    if MODEL_PATH.exists():
        try:
            reducer = joblib.load(MODEL_PATH).get("reducer")
        except Exception as extra:
            print(f"reducer load skipped ({extra})")
            reducer = None

    coords = None
    placed = "ridge"
    if reducer is not None:
        try:
            coords = np.asarray(reducer.transform(arr[missing_i]), dtype=float)
            placed = "umap"
            print(f"UMAP-transformed {len(missing_i)} extra-event projects onto the HTN map")
        except Exception as extra:
            print(f"UMAP transform skipped ({extra})")
            coords = None

    if coords is None:
        from sklearn.linear_model import Ridge

        rows: list[int] = []
        xy: list[list[float]] = []
        for slug, rec in by_slug.items():
            i = index.get(slug)
            if i is None:
                continue
            try:
                rows.append(i)
                xy.append([float(rec["x"]), float(rec["y"])])
            except (KeyError, TypeError, ValueError):
                continue
        if len(rows) < 20:
            print("not enough mapped points to place extra-event projects")
            return
        model = Ridge(alpha=10.0)
        model.fit(arr[rows], np.asarray(xy, dtype=float))
        coords = np.asarray(model.predict(arr[missing_i]), dtype=float)
        print(f"Ridge-projected {len(missing_i)} extra-event projects onto the HTN map")

    known_i = [index[slug] for slug in by_slug if slug in index]
    cluster_ids = [0] * len(missing_i)
    cluster_labels = ["theme 0"] * len(missing_i)
    if known_i:
        known = arr[known_i]
        miss = arr[missing_i]
        known = known / (np.linalg.norm(known, axis=1, keepdims=True) + 1e-9)
        miss = miss / (np.linalg.norm(miss, axis=1, keepdims=True) + 1e-9)
        nn = np.argmax(miss @ known.T, axis=1)
        for k, j in enumerate(nn):
            src = by_slug[projects[known_i[int(j)]].slug]
            cluster_ids[k] = int(src.get("cluster_id") or 0)
            cluster_labels[k] = str(src.get("cluster_label") or "theme 0")

    added = 0
    for k, i in enumerate(missing_i):
        rec = _point_payload(projects[i], float(coords[k][0]), float(coords[k][1]))
        rec["cluster_id"] = int(cluster_ids[k])
        rec["cluster_label"] = str(cluster_labels[k])
        rec["placed"] = placed
        points.append(rec)
        added += 1

    xs = [float(pt.get("x") or 0) for pt in points]
    ys = [float(pt.get("y") or 0) for pt in points]
    payload["points"] = points
    payload["bounds"] = _bounds(xs, ys) if xs else payload.get("bounds") or {}
    MAP_PATH.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {MAP_PATH} ({len(points)} points, +{added} extra-event)")


N_THEMES = 10
THEME_TERMS = 5


def _project_theme_text(project) -> str:
    tags = " ".join(project.built_with or [])
    return f"{project.title} {project.tagline} {project.description} {tags}"


def _fit_tfidf(texts: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer

    docs = [t if (t or "").strip() else "project" for t in texts]
    min_df = 1 if len(docs) < 20 else 2
    max_df = 1.0 if len(docs) < 8 else 0.7
    vec = TfidfVectorizer(
        max_features=4000,
        stop_words="english",
        min_df=min_df,
        max_df=max_df,
        ngram_range=(1, 1),
    )
    matrix = vec.fit_transform(docs)
    return vec, matrix


def _top_tfidf_terms(vec, matrix, member_idx: list[int], n_terms: int = THEME_TERMS) -> list[str]:
    if not member_idx:
        return []
    mean = np.asarray(matrix[member_idx].mean(axis=0)).ravel()
    names = vec.get_feature_names_out()
    order = mean.argsort()[::-1]
    terms: list[str] = []
    for j in order:
        if mean[j] <= 0:
            break
        token = str(names[j]).strip()
        if token and token not in terms:
            terms.append(token)
        if len(terms) >= n_terms:
            break
    return terms


def _terms_label(terms: list[str], cluster_id: int) -> str:
    return ", ".join(terms) if terms else f"theme {cluster_id}"


def _theme_name_ok(name: str) -> bool:
    words = [w for w in name.replace("_", " ").split() if w]
    return 1 <= len(words) <= 3 and all(len(w) < 32 for w in words)


def _gemini_theme_names(term_by_id: dict[int, str]) -> dict[int, str]:
    """One optional Gemini call. Empty dict on any failure — caller keeps TF-IDF labels."""
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key or not term_by_id:
        return {}
    try:
        import httpx
    except Exception as exc:
        print(f"Gemini theme names skipped ({exc})")
        return {}

    lines = "\n".join(f"{cid}: {terms}" for cid, terms in sorted(term_by_id.items()))
    prompt = (
        "Name each hackathon-project cluster with a short theme.\n"
        "Each line is cluster_id: TF-IDF terms from that cluster.\n"
        'Return STRICT JSON only: {"themes":[{"id":0,"name":"Vision Wearables"},...]}\n'
        "name is 1 to 3 words, Title Case. No quotes, no punctuation, no numbers.\n"
        "Stay close to the terms. Do not invent stacks that are not implied.\n\n"
        f"{lines}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    base = (
        os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    url = f"{base}/models/gemini-flash-lite-latest:generateContent"
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.post(url, params={"key": key}, json=payload)
        if r.status_code >= 400:
            print(f"Gemini theme names skipped (HTTP {r.status_code})")
            return {}
        body = r.json()
        parts = (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        raw = "".join(str(p.get("text") or "") for p in parts).strip()
        if not raw:
            print("Gemini theme names skipped (empty)")
            return {}
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        rows = parsed.get("themes") if isinstance(parsed, dict) else parsed
        if not isinstance(rows, list):
            print("Gemini theme names skipped (unusable JSON)")
            return {}
        out: dict[int, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                cid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            name = str(row.get("name") or "").strip()
            if cid in term_by_id and _theme_name_ok(name):
                out[cid] = name
        return out
    except Exception as exc:
        print(f"Gemini theme names skipped ({exc})")
        return {}


def _single_theme_bucket(projects) -> dict:
    n = len(projects)
    texts = [_project_theme_text(p) for p in projects]
    try:
        vec, matrix = _fit_tfidf(texts)
        terms = _top_tfidf_terms(vec, matrix, list(range(n))) if n else []
    except Exception:
        terms = []
    label = _terms_label(terms, 0)
    ids = [0] * n
    return {
        "ids": ids,
        "labels": [label] * n,
        "themes": [{"id": 0, "label": label, "count": n}],
    }


def cluster_themes(projects, embeddings: np.ndarray) -> dict:
    """KMeans + TF-IDF labels, optional Gemini rename. Never raises."""
    n = len(projects)
    try:
        if n == 0:
            return {"ids": [], "labels": [], "themes": []}
        emb = np.nan_to_num(np.asarray(embeddings, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        if emb.ndim != 2 or emb.shape[0] != n:
            raise ValueError(f"embeddings shape {getattr(emb, 'shape', None)} != n={n}")

        k = min(N_THEMES, n)
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=k, random_state=7, n_init=10)
        raw_ids = km.fit_predict(emb)
        ids = [int(c) for c in raw_ids]

        texts = [_project_theme_text(p) for p in projects]
        members: dict[int, list[int]] = {i: [] for i in range(k)}
        for idx, cid in enumerate(ids):
            members.setdefault(cid, []).append(idx)

        try:
            vec, matrix = _fit_tfidf(texts)
        except Exception as exc:
            print(f"TF-IDF theme labels skipped ({exc})")
            vec, matrix = None, None

        term_by_id: dict[int, str] = {}
        for cid in range(k):
            terms: list[str] = []
            if vec is not None and matrix is not None:
                try:
                    terms = _top_tfidf_terms(vec, matrix, members.get(cid) or [])
                except Exception as exc:
                    print(f"TF-IDF terms for cluster {cid} skipped ({exc})")
                    terms = []
            term_by_id[cid] = _terms_label(terms, cid)

        named = dict(term_by_id)
        for cid, name in _gemini_theme_names(term_by_id).items():
            named[cid] = name

        labels = [named.get(cid, term_by_id.get(cid, f"theme {cid}")) for cid in ids]
        themes = [
            {
                "id": int(cid),
                "label": str(named[cid]),
                "count": int(len(members.get(cid) or [])),
            }
            for cid in range(k)
            if members.get(cid)
        ]
        print("Themes:")
        for row in themes:
            print(f"  {row['id']}: {row['label']} (n={row['count']})")
        return {"ids": ids, "labels": labels, "themes": themes}
    except Exception as exc:
        print(f"KMeans theme clustering failed ({exc}); writing a single term-based bucket.")
        return _single_theme_bucket(projects)


def reduce_map(projects, embeddings: np.ndarray, clusters: dict | None = None):
    reducer = None
    coords = None
    try:
        from umap import UMAP

        reducer = UMAP(n_neighbors=min(15, max(2, len(projects) - 1)), min_dist=0.1, n_components=2, random_state=7)
        coords = reducer.fit_transform(embeddings)
        print("UMAP ok")
    except Exception as e:
        print(f"UMAP unavailable ({e}); falling back to PCA.")
        reducer = PCA(n_components=2, random_state=7)
        coords = reducer.fit_transform(embeddings)

    if clusters is None:
        clusters = cluster_themes(projects, embeddings)

    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    points = []
    for i, (p, x, y) in enumerate(zip(projects, xs, ys)):
        rec = _point_payload(p, x, y)
        rec["cluster_id"] = int(clusters["ids"][i]) if i < len(clusters["ids"]) else 0
        rec["cluster_label"] = str(clusters["labels"][i]) if i < len(clusters["labels"]) else "theme 0"
        points.append(rec)
    payload = {
        "points": points,
        "bounds": _bounds(xs, ys),
        "themes": list(clusters.get("themes") or []),
    }
    MAP_PATH.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {MAP_PATH} ({len(payload['points'])} points, {len(payload['themes'])} themes)")
    return reducer, coords


def _auc_safe(y_true, y_score) -> float | None:
    if len(set(y_true)) < 2:
        return None
    try:
        return float(roc_auc_score(y_true, y_score))
    except ValueError:
        return None


def train(projects, embeddings: np.ndarray):
    y = np.array([1 if p.finalist else 0 for p in projects], dtype=int)
    years = np.array([p.year for p in projects], dtype=int)
    n_pca = min(50, embeddings.shape[0] - 1, embeddings.shape[1])
    n_pca = max(2, n_pca)
    pca = PCA(n_components=n_pca, random_state=7)
    reduced = pca.fit_transform(embeddings)
    struct = np.array([_structured_features(p) for p in projects], dtype=float)
    x = np.hstack([reduced, struct])

    models = [
        (
            "logreg",
            Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("clf", LogisticRegression(class_weight="balanced", max_iter=400)),
                ]
            ),
        ),
        (
            "hgb",
            HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=80),
        ),
    ]

    logo = LeaveOneGroupOut()
    scores: dict[str, list[float]] = {name: [] for name, _ in models}

    for name, model in models:
        for train_idx, test_idx in logo.split(x, y, groups=years):
            if y[train_idx].sum() == 0 or y[train_idx].sum() == len(train_idx):
                continue
            model.fit(x[train_idx], y[train_idx])
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(x[test_idx])[:, 1]
            else:
                proba = model.decision_function(x[test_idx])
            auc = _auc_safe(y[test_idx], proba)
            if auc is not None:
                scores[name].append(auc)

    summary = {name: (float(np.mean(v)), v) for name, v in scores.items() if v}
    if not summary:
        print("LOYO produced no usable AUC (sample is small). Fitting logreg on all rows anyway.")
        winner_name = "logreg"
        winner = models[0][1]
        mean_auc, spread = 0.5, [0.5, 0.5]
    else:
        winner_name = max(summary, key=lambda n: summary[n][0])
        mean_auc, fold_aucs = summary[winner_name]
        spread = [float(min(fold_aucs)), float(max(fold_aucs))]
        winner = dict(models)[winner_name]
        print("LOYO AUC by model:")
        for name, (mu, folds) in summary.items():
            print(f"  {name}: mean={mu:.3f} folds={[round(a, 3) for a in folds]}")

    winner.fit(x, y)
    try:
        calibrated = CalibratedClassifierCV(winner, method="isotonic", cv=min(3, max(2, int(y.sum()))))
        calibrated.fit(x, y)
        model = calibrated
    except Exception as e:
        print(f"Calibration skipped ({e})")
        model = winner

    blob = {
        "model": model,
        "pca": pca,
        "reducer": None,  # filled by caller
        "auc": round(float(mean_auc), 3),
        "auc_spread": [round(spread[0], 3), round(spread[1], 3)],
        "n_train": int(len(projects)),
        "n_finalists": int(y.sum()),
        "winner": winner_name,
        "embed_space": "openai_or_tfidf",
        "p_ref": np.sort(_finalist_proba(model, x)),
    }
    return blob


def _htn_slice(explore, embeddings: np.ndarray):
    """Hack the North rows only. Finalist Score stays the museum model."""
    htn_path = ROOT / CORPUS_PATH
    if not htn_path.exists():
        return [], None
    htn = load_corpus(htn_path)
    index = {p.slug: i for i, p in enumerate(explore)}
    keep = [p for p in htn if p.slug in index]
    if not keep:
        return [], None
    arr = np.stack([embeddings[index[p.slug]] for p in keep]).astype(np.float32)
    return keep, arr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed the explore corpus and rebuild artifacts.")
    parser.add_argument(
        "--no-train",
        action="store_true",
        help="Keep the existing HTN classifier; still embed extras and refresh the map/index.",
    )
    args = parser.parse_args(argv)

    DATA.mkdir(parents=True, exist_ok=True)
    explore = load_explore_corpus()
    print(f"Explore corpus: {len(explore)} rows")
    embeddings = embed_projects(explore)
    htn, htn_emb = _htn_slice(explore, embeddings)
    print(f"HTN classifier corpus: {len(htn)} rows")

    try:
        from elastic import index_projects

        index_projects(explore, embeddings)
    except Exception as e:
        print(f"Elasticsearch index skipped ({e})")

    if args.no_train and MODEL_PATH.exists() and MAP_PATH.exists():
        place_unmapped(explore, embeddings)
        print("Kept existing HTN classifier. Extra events now use the shared embedding cache.")
        return 0

    train_projects = htn or explore
    train_emb = htn_emb if htn_emb is not None else embeddings
    print(f"Training Finalist Score on {len(train_projects)} HTN rows")
    clusters = cluster_themes(train_projects, train_emb)
    reducer, _ = reduce_map(train_projects, train_emb, clusters)
    blob = train(train_projects, train_emb)
    blob["reducer"] = reducer
    joblib.dump(blob, MODEL_PATH)
    print(f"Wrote {MODEL_PATH}  auc={blob['auc']} spread={blob['auc_spread']} p_ref={len(blob['p_ref'])}")
    place_unmapped(explore, embeddings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
