"""Offline pipeline: embed → reduce → train → write artifacts the server reads.

Run manually whenever the corpus updates:

    python build.py

Never call this from a request handler.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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

from engine import DATA, EMB_PATH, MAP_PATH, MODEL_PATH, _bounds, _point_payload, _structured_features
from schema import load_corpus

load_dotenv()

CACHE_PATH = DATA / "emb_cache.json"
BATCH = 100


def _cache_load() -> dict[str, list[float]]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _cache_save(cache: dict[str, list[float]]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def embed_projects(projects) -> np.ndarray:
    cache = _cache_load()
    missing = [p for p in projects if p.slug not in cache]
    key = os.getenv("OPENAI_API_KEY")
    def _tfidf() -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(max_features=512)
        arr = vec.fit_transform([p.embed_text() for p in projects]).toarray().astype(np.float32)
        np.save(EMB_PATH, arr)
        print(f"Wrote TF-IDF {EMB_PATH} {arr.shape}")
        return arr

    if missing and not key:
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
                resp = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[p.embed_text() for p in batch],
                )
                for p, item in zip(batch, resp.data):
                    cache[p.slug] = list(item.embedding)
                _cache_save(cache)
                print(f"  {min(i + BATCH, len(missing))}/{len(missing)}")
        except Exception as e:
            print(f"OpenAI embed failed ({e}); falling back to TF-IDF.")
            return _tfidf()

    dim = len(next(iter(cache.values())))
    arr = np.zeros((len(projects), dim), dtype=np.float32)
    for i, p in enumerate(projects):
        arr[i] = np.array(cache[p.slug], dtype=np.float32)
    np.save(EMB_PATH, arr)
    print(f"Wrote {EMB_PATH} {arr.shape}")
    return arr


def reduce_map(projects, embeddings: np.ndarray):
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

    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    payload = {
        "points": [_point_payload(p, x, y) for p, x, y in zip(projects, xs, ys)],
        "bounds": _bounds(xs, ys),
    }
    MAP_PATH.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Wrote {MAP_PATH} ({len(payload['points'])} points)")
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
    }
    return blob


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    projects = load_corpus()
    print(f"Corpus: {len(projects)} rows, {sum(p.finalist for p in projects)} finalists")
    embeddings = embed_projects(projects)
    reducer, _ = reduce_map(projects, embeddings)
    blob = train(projects, embeddings)
    blob["reducer"] = reducer
    joblib.dump(blob, MODEL_PATH)
    print(f"Wrote {MODEL_PATH}  auc={blob['auc']} spread={blob['auc_spread']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
