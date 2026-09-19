"""In-memory retrieval and scoring.

Precomputed artifacts (embeddings.npy, map.json, model.pkl) are preferred.
A local TF-IDF index is always built so /api/ask still answers if OpenAI dies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from schema import Project, ROOT, load_corpus

DATA = ROOT / "data"
MAP_PATH = DATA / "map.json"
EMB_PATH = DATA / "embeddings.npy"
MODEL_PATH = DATA / "model.pkl"

TECH_HINTS = (
    "python",
    "javascript",
    "typescript",
    "react",
    "node",
    "arduino",
    "raspberry",
    "pytorch",
    "tensorflow",
    "opencv",
    "swift",
    "kotlin",
    "java",
    "c++",
    "rust",
    "go",
    "solidity",
    "unity",
    "flutter",
    "fastapi",
    "flask",
    "django",
    "openai",
    "llm",
    "ble",
    "webrtc",
    "html",
    "css",
)

HARDWARE_HINTS = (
    "arduino",
    "raspberry",
    "rpi",
    "pcb",
    "firmware",
    "lidar",
    "servo",
    "sensor",
    "hardware",
    "wearable",
    "esp32",
    "stm32",
    "kicad",
    "platformio",
    "microcontroller",
    "soldering",
    "3d-print",
    "3d printed",
    "cane",
    "robot arm",
    "quadruped",
)


def _bounds(xs: list[float], ys: list[float], pad: float = 0.12) -> dict[str, float]:
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x0 == x1:
        x0, x1 = x0 - 1.0, x1 + 1.0
    if y0 == y1:
        y0, y1 = y0 - 1.0, y1 + 1.0
    dx, dy = x1 - x0, y1 - y0
    return {
        "x0": x0 - dx * pad,
        "y0": y0 - dy * pad,
        "x1": x1 + dx * pad,
        "y1": y1 + dy * pad,
    }


def _point_payload(project: Project, x: float, y: float) -> dict[str, Any]:
    return {
        "x": float(x),
        "y": float(y),
        "slug": project.slug,
        "title": project.title,
        "year": project.year,
        "finalist": project.finalist,
        "tagline": project.tagline,
    }


def _blob(project: Project) -> str:
    tags = " ".join(project.built_with or [])
    return f"{project.title} {project.tagline} {project.description} {tags}".lower()


def project_is_hardware(project: Project) -> bool:
    return any(h in _blob(project) for h in HARDWARE_HINTS)


def project_tags(project: Project) -> set[str]:
    tags = {t.lower() for t in (project.built_with or [])}
    blob = _blob(project)
    tags.update(t for t in TECH_HINTS if t in blob)
    return tags


def parse_signals(text: str, repo: dict[str, Any] | None = None) -> dict[str, Any]:
    lowered = (text or "").lower()
    if repo and repo.get("ok"):
        extra = " ".join(
            [
                repo.get("full_name") or "",
                repo.get("description") or "",
                " ".join(repo.get("languages") or []),
                " ".join(repo.get("files") or []),
                repo.get("readme") or "",
            ]
        ).lower()
        lowered = lowered + " " + extra
    tags = [t for t in TECH_HINTS if t in lowered]
    if repo and repo.get("ok"):
        for lang in repo.get("languages") or []:
            key = lang.lower()
            if key not in tags:
                tags.append(key)
    hardware = bool(repo and repo.get("hardware")) or any(h in lowered for h in HARDWARE_HINTS)
    team = 4
    m = re.search(r"\b(?:team(?: size)?|teammates?)\s*(?:of|:)?\s*([1-8])\b", lowered)
    if m:
        team = int(m.group(1))
    has_repo = 1.0 if (repo and repo.get("ok")) else (1.0 if "github" in lowered else 0.5)
    return {
        "hardware": hardware,
        "tags": tags,
        "team_size": team,
        "has_repo": has_repo,
        "n_tech": len(tags),
        "length": float(len(text or "")),
    }


def _structured_features(project: Project) -> list[float]:
    tags = project_tags(project)
    return [
        float(project.team_size),
        1.0 if project.has_video else 0.0,
        1.0 if project.has_repo else 0.0,
        float(len(tags)),
        float(len(project.description or "")),
        float(project.year),
        1.0 if project_is_hardware(project) else 0.0,
    ]


def query_features(signals: dict[str, Any], year: int = 2026) -> list[float]:
    return [
        float(signals["team_size"]),
        0.5,
        float(signals["has_repo"]),
        float(signals["n_tech"]),
        float(signals["length"]),
        float(year),
        1.0 if signals["hardware"] else 0.0,
    ]


def _group_rate(projects: list[Project], pred) -> float | None:
    rows = [p for p in projects if pred(p)]
    if len(rows) < 3:
        return None
    return sum(1 for p in rows if p.finalist) / len(rows)


def score_from_signals(projects: list[Project], signals: dict[str, Any]) -> tuple[float, list[str]]:
    """Empirical rates from the corpus — not neighbour win-rate."""
    n = max(1, len(projects))
    prior = sum(1 for p in projects if p.finalist) / n
    why: list[str] = []
    hw_rate = _group_rate(projects, project_is_hardware)
    sw_rate = _group_rate(projects, lambda p: not project_is_hardware(p))
    rate = prior
    if signals["hardware"] and hw_rate is not None:
        rate = hw_rate
        why.append(f"hardware-shaped projects finalisted at {hw_rate:.0%} here, not because a neighbour won")
    elif (not signals["hardware"]) and sw_rate is not None:
        rate = sw_rate
        why.append(f"software-shaped projects finalisted at {sw_rate:.0%} in this corpus")
    else:
        why.append(f"corpus base rate is {prior:.0%} finalists")

    tags = [t for t in signals.get("tags") or [] if t]
    if tags:
        fin = [p for p in projects if p.finalist]
        other = [p for p in projects if not p.finalist]
        deltas = []
        notable = []
        for tag in tags[:8]:
            if not fin or not other:
                break
            rf = sum(1 for p in fin if tag in project_tags(p)) / len(fin)
            rn = sum(1 for p in other if tag in project_tags(p)) / len(other)
            deltas.append(rf - rn)
            if abs(rf - rn) >= 0.08:
                notable.append(f"{tag} ({rf:.0%} of finalists vs {rn:.0%} otherwise)")
        if deltas:
            boost = float(np.mean(deltas))
            rate = rate + 0.25 * boost
            if notable:
                why.append("stack vs outcome: " + "; ".join(notable[:3]))
            else:
                why.append("named stack tags are not strongly tied to winning here")
    why.append("neighbours are context only — similarity is not the score")
    return float(max(0.03, min(0.55, rate))), why


def features_from_text(
    text: str,
    year: int = 2026,
    team_size: int = 4,
    has_video: bool = False,
    has_repo: bool = True,
    hardware: bool = False,
    extra_tech_tags: int = 0,
) -> list[float]:
    """Structured features for the classifier.

    Keyword args override the parsed text. /api/ask does not call this, so
    its parse_signals → query_features path stays identical. When hardware
    is true the built_with / n_tech count is bumped by one.
    """
    signals = parse_signals(text)
    n_tech = float(signals.get("n_tech") or 0) + int(extra_tech_tags or 0)
    if hardware:
        n_tech += 1.0
    return [
        float(team_size),
        1.0 if has_video else 0.0,
        1.0 if has_repo else 0.0,
        n_tech,
        float(len(text or "")),
        float(year),
        1.0 if hardware else 0.0,
    ]


class Engine:
    def __init__(self) -> None:
        self.projects: list[Project] = []
        self.by_slug: dict[str, Project] = {}
        self.map_data: dict[str, Any] = {"points": [], "bounds": {}}
        self.embeddings: np.ndarray | None = None
        self.model_blob: dict[str, Any] | None = None
        self.vectorizer: TfidfVectorizer | None = None
        self.tfidf: Any = None
        self.fallback_pca: PCA | None = None
        self.fallback_coords: np.ndarray | None = None
        self.openai_ok = bool(os.getenv("OPENAI_API_KEY"))
        self.source = "sample.json"

    def load(self) -> None:
        from schema import corpus_source

        self.projects = load_corpus()
        self.source = corpus_source()
        self.by_slug = {p.slug: p for p in self.projects}
        self._fit_fallback()
        self._load_embeddings()
        self._load_map()
        self._load_model()
        if self.model_blob is None:
            self._fit_fallback_model()

    def _fit_fallback(self) -> None:
        texts = [p.embed_text() for p in self.projects]
        self.vectorizer = TfidfVectorizer(max_features=4000, ngram_range=(1, 2))
        self.tfidf = self.vectorizer.fit_transform(texts)
        n = len(self.projects)
        n_comp = 2 if n > 2 else 1
        self.fallback_pca = PCA(n_components=n_comp, random_state=7)
        coords = self.fallback_pca.fit_transform(self.tfidf.toarray())
        if coords.shape[1] == 1:
            coords = np.column_stack([coords[:, 0], np.zeros(n)])
        # spread years a little so the sample map is not a smear
        years = np.array([p.year for p in self.projects], dtype=float)
        year_shift = (years - years.mean()) / (years.std() + 1e-6) * 0.35
        coords = coords.copy()
        coords[:, 0] += year_shift
        # tiny deterministic jitter so 20 sample dots don't stack
        for i, p in enumerate(self.projects):
            h = int(hashlib.md5(p.slug.encode()).hexdigest()[:8], 16) % 1000 / 1000.0
            coords[i, 0] += (h - 0.5) * 0.25
            coords[i, 1] += (1 - h - 0.5) * 0.25
        self.fallback_coords = coords

    def _load_embeddings(self) -> None:
        if EMB_PATH.exists():
            arr = np.load(EMB_PATH)
            if arr.shape[0] == len(self.projects):
                self.embeddings = arr
                return
        self.embeddings = None

    def _load_map(self) -> None:
        if MAP_PATH.exists():
            try:
                payload = json.loads(MAP_PATH.read_text(encoding="utf-8"))
                if payload.get("points"):
                    self.map_data = payload
                    return
            except json.JSONDecodeError:
                pass
        self.map_data = self._map_from_fallback()

    def _map_from_fallback(self) -> dict[str, Any]:
        assert self.fallback_coords is not None
        xs = [float(c[0]) for c in self.fallback_coords]
        ys = [float(c[1]) for c in self.fallback_coords]
        points = [
            _point_payload(p, x, y)
            for p, x, y in zip(self.projects, xs, ys)
        ]
        return {"points": points, "bounds": _bounds(xs, ys)}

    def _load_model(self) -> None:
        if MODEL_PATH.exists() and self.embeddings is not None:
            try:
                self.model_blob = joblib.load(MODEL_PATH)
                return
            except Exception:
                self.model_blob = None
        self.model_blob = None

    def _fit_fallback_model(self) -> None:
        """Small LOYO logreg on the in-memory TF-IDF so /api/ask has a number
        before build.py has run. Honest AUC; do not pretend it is the real model.
        """
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import LeaveOneGroupOut
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        y = np.array([1 if p.finalist else 0 for p in self.projects], dtype=int)
        years = np.array([p.year for p in self.projects], dtype=int)
        raw = self.tfidf.toarray()
        n_pca = min(20, raw.shape[0] - 1, raw.shape[1])
        n_pca = max(2, n_pca)
        pca = PCA(n_components=n_pca, random_state=7)
        reduced = pca.fit_transform(raw)
        struct = np.array([_structured_features(p) for p in self.projects], dtype=float)
        x = np.hstack([reduced, struct])
        pipe = Pipeline(
            [
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(class_weight="balanced", max_iter=400)),
            ]
        )
        folds = []
        for train_idx, test_idx in LeaveOneGroupOut().split(x, y, groups=years):
            if len(set(y[train_idx])) < 2 or len(set(y[test_idx])) < 2:
                continue
            pipe.fit(x[train_idx], y[train_idx])
            proba = pipe.predict_proba(x[test_idx])[:, 1]
            try:
                folds.append(float(roc_auc_score(y[test_idx], proba)))
            except ValueError:
                continue
        pipe.fit(x, y)
        try:
            model = CalibratedClassifierCV(pipe, method="isotonic", cv=min(3, max(2, int(y.sum()))))
            model.fit(x, y)
        except Exception:
            model = pipe
        mean_auc = float(np.mean(folds)) if folds else None
        spread = [float(min(folds)), float(max(folds))] if folds else []
        # 20-row sample routinely produces AUC 1.0. Don't show that to a judge.
        if mean_auc is not None and (mean_auc >= 0.98 or mean_auc <= 0.02 or len(folds) < 3):
            mean_auc = None
            spread = []
        self.model_blob = {
            "model": model,
            "pca": pca,
            "reducer": None,
            "auc": None if mean_auc is None else round(mean_auc, 3),
            "auc_spread": [round(s, 3) for s in spread],
            "n_train": len(self.projects),
            "n_finalists": int(y.sum()),
            "winner": "logreg-tfidf",
            "embed_space": "tfidf",
        }

    def neighbour_records(
        self, slugs_and_scores: list[tuple[str, float]]
    ) -> list[dict[str, Any]]:
        out = []
        for slug, sim in slugs_and_scores:
            p = self.by_slug.get(slug)
            if not p:
                continue
            out.append(
                {
                    "slug": p.slug,
                    "title": p.title,
                    "year": p.year,
                    "tagline": p.tagline,
                    "finalist": p.finalist,
                    "similarity": round(float(sim), 4),
                }
            )
        return out

    def _tfidf_neighbours(self, text: str, k: int = 5) -> tuple[list[tuple[str, float]], np.ndarray]:
        assert self.vectorizer is not None
        assert self.fallback_pca is not None
        assert self.fallback_coords is not None
        q = self.vectorizer.transform([text])
        sims = cosine_similarity(q, self.tfidf).ravel()
        order = np.argsort(-sims)[:k]
        pairs = [(self.projects[i].slug, float(sims[i])) for i in order]
        coords = self.fallback_pca.transform(q.toarray())[0]
        if coords.shape[0] == 1:
            coords = np.array([coords[0], 0.0])
        return pairs, coords

    def _openai_embed(self, text: str, timeout: float = 10.0) -> np.ndarray:
        from openai import OpenAI

        kwargs = {"api_key": os.getenv("OPENAI_API_KEY"), "timeout": timeout}
        base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base:
            kwargs["base_url"] = base
        client = OpenAI(**kwargs)
        resp = client.embeddings.create(model="text-embedding-3-small", input=text)
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _openai_neighbours(self, vec: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        assert self.embeddings is not None
        a = vec / (np.linalg.norm(vec) + 1e-9)
        b = self.embeddings / (np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-9)
        sims = b @ a
        order = np.argsort(-sims)[:k]
        return [(self.projects[i].slug, float(sims[i])) for i in order]

    def es_neighbours(
        self, query_embedding: np.ndarray, query_text: str, k: int = 5
    ) -> list[tuple[str, float]]:
        """Hybrid BM25 + dense knn via Elasticsearch, fused with manual RRF.

        Raises on any failure so ask() can fall back to in-memory cosine.
        """
        from elastic import hybrid_neighbours

        return hybrid_neighbours(query_embedding, query_text, k=k)

    def _openai_point(self, vec: np.ndarray) -> np.ndarray | None:
        if not self.model_blob:
            return None
        reducer = self.model_blob.get("reducer")
        if reducer is None:
            return None
        try:
            xy = reducer.transform(vec.reshape(1, -1))[0]
            return np.array(xy, dtype=float)
        except Exception:
            return None

    def _probability(
        self,
        embed_vec: np.ndarray | None,
        signals: dict[str, Any],
        struct: list[float] | np.ndarray | None = None,
    ) -> tuple[float | None, dict[str, Any]]:
        meta = {
            "auc": None,
            "auc_spread": [],
            "n_train": len(self.projects),
            "n_finalists": sum(1 for p in self.projects if p.finalist),
        }
        if not self.model_blob:
            return None, meta
        meta.update(
            {
                "auc": self.model_blob.get("auc"),
                "auc_spread": self.model_blob.get("auc_spread") or [],
                "n_train": self.model_blob.get("n_train", meta["n_train"]),
                "n_finalists": self.model_blob.get("n_finalists", meta["n_finalists"]),
            }
        )
        clf = self.model_blob.get("model")
        pca = self.model_blob.get("pca")
        if clf is None:
            return None, meta
        if embed_vec is None or pca is None:
            return None, meta
        try:
            reduced = pca.transform(embed_vec.reshape(1, -1))
            if struct is None:
                struct_arr = np.array(query_features(signals), dtype=float).reshape(1, -1)
            else:
                struct_arr = np.asarray(struct, dtype=float).reshape(1, -1)
            x = np.hstack([reduced, struct_arr])
            proba = clf.predict_proba(x)[0]
            # class 1 = finalist if present
            classes = list(getattr(clf, "classes_", [0, 1]))
            if 1 in classes:
                idx = classes.index(1)
            elif True in classes:
                idx = classes.index(True)
            else:
                idx = int(np.argmax(proba))
            return float(proba[idx]), meta
        except Exception:
            return None, meta

    def ask(self, text: str, github: str = "", devpost: str = "") -> dict[str, Any]:
        prompt = (text or "").strip()
        repo = None
        if github.strip():
            from github_repo import compose_embed_text, fetch_repo

            repo = fetch_repo(github)
            document = compose_embed_text(prompt, repo)
        else:
            from github_repo import compose_embed_text

            document = compose_embed_text(prompt, None)
        if not document:
            document = prompt

        signals = parse_signals(document, repo if repo and repo.get("ok") else None)

        used = "tfidf"
        embed_vec = None
        point = None
        pairs: list[tuple[str, float]] = []
        source = "local"

        if self.openai_ok and self.embeddings is not None:
            try:
                t0 = time.monotonic()
                embed_vec = self._openai_embed(document, timeout=10.0)
                if time.monotonic() - t0 > 10:
                    raise TimeoutError("embed exceeded 10s")
                xy = self._openai_point(embed_vec)
                if xy is None and self.fallback_pca is not None:
                    _, xy = self._tfidf_neighbours(document)
                point = {"x": float(xy[0]), "y": float(xy[1])}
                used = "openai"
            except Exception:
                used = "tfidf"

        if used == "tfidf":
            pairs, xy = self._tfidf_neighbours(document)
            point = {"x": float(xy[0]), "y": float(xy[1])}
            embed_vec = None
            source = "local"
            print("neighbours source=local (tfidf)")
        else:
            try:
                pairs = self.es_neighbours(embed_vec, document, k=5)
                source = "elastic"
                print("neighbours source=elastic")
            except Exception as exc:
                pairs = self._openai_neighbours(embed_vec)
                source = "local"
                print(f"neighbours source=local ({exc})")

        if embed_vec is None and self.model_blob and self.model_blob.get("embed_space") == "tfidf":
            assert self.vectorizer is not None
            embed_vec = self.vectorizer.transform([document]).toarray()[0]

        n = max(1, len(self.projects))
        clf_prob, model_meta = self._probability(embed_vec, signals)
        signal_prob, why = score_from_signals(self.projects, signals)
        if n >= 80 and clf_prob is not None:
            prob = 0.7 * float(clf_prob) + 0.3 * signal_prob
            why = ["classifier on stack/hardware signals + text"] + why
        else:
            # tiny sample or failed model: never use neighbour win-rate
            prob = signal_prob
            model_meta = {**model_meta, "auc": None, "auc_spread": []}

        tracks_out = None
        if (devpost or "").strip():
            from prizes import fetch_tracks, advise_tracks

            fetched = fetch_tracks(devpost)
            if fetched.get("ok"):
                ranked = advise_tracks(
                    document,
                    fetched["tracks"],
                    self.projects,
                    neighbour_slugs=[slug for slug, _ in pairs],
                    repo=repo if repo and repo.get("ok") else None,
                    prompt=prompt,
                    signals=signals,
                )
                tracks_out = {
                    "ok": True,
                    "url": fetched.get("url"),
                    "n": len(fetched["tracks"]),
                    "ranked": ranked,
                    "method": (
                        "Each % is this prize family in the corpus, gated on whether "
                        "the sponsor SDK is in code / README / prompt. The big number "
                        "is still the 12 finalists. p_if is the same track if you ship "
                        "the integration — we have winners, not losers, so this is likeness, not P(win|submit)."
                    ),
                    "error": None,
                }
            else:
                tracks_out = {
                    "ok": False,
                    "url": fetched.get("url"),
                    "n": 0,
                    "ranked": [],
                    "error": fetched.get("error") or "could not load prize tracks",
                }

        github_out = None
        if github.strip():
            if repo and repo.get("ok"):
                github_out = {
                    "ok": True,
                    "full_name": repo.get("full_name"),
                    "languages": repo.get("languages") or [],
                    "hardware": bool(repo.get("hardware")),
                    "error": None,
                }
            else:
                github_out = {
                    "ok": False,
                    "full_name": None,
                    "languages": [],
                    "hardware": False,
                    "error": (repo or {}).get("error") or "could not read repo",
                }

        return {
            "point": point,
            "neighbours": self.neighbour_records(pairs),
            "probability": round(float(max(0.0, min(1.0, prob))), 4),
            "model": model_meta,
            "backend": used,
            "source": source,
            "github": github_out,
            "why": why,
            "signals": {
                "hardware": signals["hardware"],
                "tags": signals["tags"][:8],
            },
            "tracks": tracks_out,
        }

    def _score_like_ask(
        self,
        embed_vec: np.ndarray | None,
        signals: dict[str, Any],
        struct: list[float] | np.ndarray | None = None,
        baseline_clf: float | None = None,
    ) -> float:
        """Same blend /api/ask uses. struct is only set for coach moves."""
        n = max(1, len(self.projects))
        clf_prob, _ = self._probability(embed_vec, signals, struct=struct)
        signal_prob, _ = score_from_signals(self.projects, signals)
        if n >= 80 and clf_prob is not None:
            prob = 0.7 * float(clf_prob) + 0.3 * signal_prob
        else:
            prob = signal_prob
            if (
                struct is not None
                and clf_prob is not None
                and baseline_clf is not None
            ):
                prob = float(prob) + (float(clf_prob) - float(baseline_clf))
        return float(max(0.0, min(1.0, prob)))

    def _embed_document(self, document: str) -> tuple[np.ndarray | None, dict[str, float]]:
        embed_vec = None
        point = {"x": 0.0, "y": 0.0}
        if self.openai_ok and self.embeddings is not None:
            try:
                embed_vec = self._openai_embed(document, timeout=10.0)
                xy = self._openai_point(embed_vec)
                if xy is None and self.fallback_pca is not None:
                    _, xy = self._tfidf_neighbours(document)
                point = {"x": float(xy[0]), "y": float(xy[1])}
            except Exception:
                embed_vec = None
        if embed_vec is None:
            _, xy = self._tfidf_neighbours(document)
            point = {"x": float(xy[0]), "y": float(xy[1])}
            if self.model_blob and self.model_blob.get("embed_space") == "tfidf":
                assert self.vectorizer is not None
                embed_vec = self.vectorizer.transform([document]).toarray()[0]
        return embed_vec, point

    def _openai_embed_batch(self, texts: list[str], timeout: float = 10.0) -> list[np.ndarray]:
        from openai import OpenAI

        kwargs = {"api_key": os.getenv("OPENAI_API_KEY"), "timeout": timeout}
        base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base:
            kwargs["base_url"] = base
        client = OpenAI(**kwargs)
        resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
        items = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        return [np.array(item.embedding, dtype=np.float32) for item in items]

    def _gemini_coach_moves(self, idea: str) -> list[dict[str, Any]]:
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY unset")
        import httpx

        system = (
            "You coach Hack the North teams. Return STRICT JSON only: "
            '{"moves":[{"label":str,"rationale":str,"reframed_description":str,'
            '"features":{"hardware":bool,"has_video":bool,"extra_tech_tags":int}}]}. '
            "Give three or four distinct moves. rationale is one sentence. "
            "reframed_description is the whole idea rewritten as if that move already shipped. "
            "SYSTEM RULE: NEVER output a probability or percentage. Numbers are forbidden "
            "in label, rationale, and reframed_description. extra_tech_tags is a small "
            "integer count of added stack tags in the features object only, never in prose. "
            "Do not mention scores, odds, percent, or how likely anything is."
        )
        user = (
            "Idea:\n"
            f"{idea[:2000]}\n\n"
            "Propose moves such as: ship a physical build, film a live demo, name a real stack, "
            "or tighten the story toward a judging-day demo. JSON only."
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-1.5-flash:generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=8.0) as client:
            r = client.post(url, params={"key": key}, json=payload)
            r.raise_for_status()
            body = r.json()
        parts = (
            (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        )
        raw = "".join(str(p.get("text") or "") for p in parts).strip()
        if not raw:
            raise RuntimeError("Gemini returned empty")
        return _parse_coach_moves(raw)

    def coach(self, idea: str) -> dict[str, Any]:
        """Propose 3–4 moves. Probabilities come from the classifier, never Gemini."""
        from github_repo import compose_embed_text

        document = compose_embed_text((idea or "").strip(), None) or (idea or "").strip()
        signals = parse_signals(document, None)
        gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        embed_vec = None
        if gemini_key or (self.openai_ok and len(self.projects) >= 80):
            embed_vec, _point = self._embed_document(document)
        elif self.model_blob and self.model_blob.get("embed_space") == "tfidf":
            assert self.vectorizer is not None
            embed_vec = self.vectorizer.transform([document]).toarray()[0]
        baseline_clf, _ = self._probability(embed_vec, signals)
        baseline = self._score_like_ask(embed_vec, signals)
        out: dict[str, Any] = {"baseline": round(float(baseline), 4), "moves": []}
        try:
            specs = self._gemini_coach_moves(document)
        except Exception as exc:
            print(f"coach gemini skipped ({exc})")
            return out
        specs = specs[:4]
        if not specs:
            return out
        texts = [s["reframed_description"] for s in specs]
        try:
            vectors = self._openai_embed_batch(texts)
        except Exception as exc:
            print(f"coach embed skipped ({exc})")
            return out
        moves = []
        for spec, vec in zip(specs, vectors):
            feats = spec.get("features") or {}
            hardware = bool(feats.get("hardware"))
            has_video = bool(feats.get("has_video"))
            extra = int(feats.get("extra_tech_tags") or 0)
            reframed = spec["reframed_description"]
            struct = features_from_text(
                reframed,
                team_size=4,
                has_video=has_video,
                has_repo=True,
                hardware=hardware,
                extra_tech_tags=extra,
            )
            move_signals = parse_signals(reframed)
            move_signals["hardware"] = hardware or bool(move_signals.get("hardware"))
            move_signals["n_tech"] = float(move_signals.get("n_tech") or 0) + extra
            if hardware:
                move_signals["n_tech"] = float(move_signals["n_tech"]) + 1
            new_prob = self._score_like_ask(
                vec, move_signals, struct=struct, baseline_clf=baseline_clf
            )
            xy = self._openai_point(vec)
            if xy is None and self.fallback_pca is not None:
                try:
                    _, xy = self._tfidf_neighbours(reframed)
                except Exception:
                    xy = np.array([0.0, 0.0])
            if xy is None:
                xy = np.array([0.0, 0.0])
            delta = float(new_prob) - float(baseline)
            moves.append(
                {
                    "label": spec["label"],
                    "rationale": spec["rationale"],
                    "new_prob": round(float(new_prob), 4),
                    "delta": round(delta, 4),
                    "new_point": {"x": float(xy[0]), "y": float(xy[1])},
                }
            )
        moves.sort(key=lambda m: -m["delta"])
        out["moves"] = moves
        return out


def _parse_coach_moves(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if isinstance(data, dict):
        rows = data.get("moves") or data.get("suggestions") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    moves = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        rationale = str(row.get("rationale") or "").strip()
        reframed = str(row.get("reframed_description") or "").strip()
        if not label or not reframed:
            continue
        label = re.sub(r"\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?\b", "", label)
        rationale = re.sub(r"\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?\b", "", rationale)
        label = re.sub(r"\s{2,}", " ", label).strip(" -–—")[:80]
        rationale = re.sub(r"\s{2,}", " ", rationale).strip()[:240]
        feats = row.get("features") if isinstance(row.get("features"), dict) else {}
        try:
            extra = int(feats.get("extra_tech_tags") or 0)
        except (TypeError, ValueError):
            extra = 0
        extra = max(0, min(8, extra))
        moves.append(
            {
                "label": label[:80],
                "rationale": rationale[:240],
                "reframed_description": reframed[:4000],
                "features": {
                    "hardware": bool(feats.get("hardware")),
                    "has_video": bool(feats.get("has_video")),
                    "extra_tech_tags": extra,
                },
            }
        )
    return moves[:4]


engine = Engine()
