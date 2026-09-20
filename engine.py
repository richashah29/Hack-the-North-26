"""In-memory retrieval and scoring.

Precomputed artifacts (embeddings.npy, map.json, model.pkl) are preferred.
A local TF-IDF index is always built so /api/ask still answers if OpenAI dies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from schema import Project, ROOT, load_corpus

DATA = ROOT / "data"


def _env_path(var: str, default: Path) -> Path:
    raw = (os.getenv(var) or "").strip()
    return Path(raw).expanduser() if raw else default


def map_path() -> Path:
    return _env_path("MAP_PATH", DATA / "map.json")


def emb_path() -> Path:
    return _env_path("EMB_PATH", DATA / "embeddings.npy")


def model_path() -> Path:
    return _env_path("MODEL_PATH", DATA / "model.pkl")


def event_path() -> Path:
    return _env_path("EVENT_PATH", DATA / "event.json")


# build.py and tests import these names; they follow env at import time.
MAP_PATH = DATA / "map.json"
EMB_PATH = DATA / "embeddings.npy"
MODEL_PATH = DATA / "model.pkl"
EVENT_PATH = DATA / "event.json"
FINDINGS_PATH = DATA / "findings.json"

GROUND_RULES = (
    "Use ONLY the CONTEXT below. If the answer isn't in it, say it's not in the data. "
    "Do not use outside knowledge. Do not invent projects, prizes, or numbers. "
    "Cite projects by name and year from CONTEXT. "
    "Never say a project 'won' a specific sponsor prize — we only know finalist status. "
    "Never invent a probability, percentage, or score. If you cite a number, copy it "
    "exactly from CONTEXT. Classifier scores are injected later, not by you."
)


def json_safe(obj: Any) -> Any:
    """Python JSON types only. Numpy / NaN / inf become numbers the UI can show."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        if val != val or val == float("inf") or val == float("-inf"):
            return 0.0
        return val
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def finite_unit(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return default
    if val != val or val == float("inf") or val == float("-inf"):
        return default
    return max(0.0, min(1.0, val))


def _finalist_proba(clf, X: np.ndarray) -> np.ndarray:
    """P(finalist) from the fitted classifier. Does not change the model."""
    proba = clf.predict_proba(X)
    classes = list(getattr(clf, "classes_", [0, 1]))
    if 1 in classes:
        idx = classes.index(1)
    elif True in classes:
        idx = classes.index(True)
    else:
        idx = min(1, int(proba.shape[1]) - 1) if getattr(proba, "ndim", 1) > 1 else 0
    p = np.asarray(proba[:, idx] if getattr(proba, "ndim", 1) > 1 else proba, dtype=np.float64)
    p = np.where(np.isfinite(p), p, 0.0)
    return np.clip(p, 0.0, 1.0)


def percentile_rank(p: float, dist: np.ndarray) -> int:
    """Fraction of dist with value <= p, times 100, rounded to 0–100."""
    if dist is None:
        return 0
    arr = np.asarray(dist, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0
    try:
        p_f = float(p)
    except (TypeError, ValueError):
        return 0
    if p_f != p_f or p_f == float("inf") or p_f == float("-inf"):
        return 0
    frac = float(np.searchsorted(arr, p_f, side="right")) / float(arr.size)
    return int(round(max(0.0, min(1.0, frac)) * 100.0))


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

VIDEO_HINTS = (
    "youtube",
    "demo video",
    "has a video",
    "filmed a demo",
    "live demo",
    "screen recording",
    "vimeo",
    "loom.com",
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
        "slug": str(project.slug),
        "title": str(project.title or ""),
        "year": int(project.year or 0),
        "finalist": bool(project.finalist),
        "tagline": str(project.tagline or ""),
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
    has_video = any(v in lowered for v in VIDEO_HINTS)
    team = 4
    m = re.search(r"\b(?:team(?: size)?|teammates?)\s*(?:of|:)?\s*([1-8])\b", lowered)
    if m:
        team = int(m.group(1))
    has_repo = 1.0 if (repo and repo.get("ok")) else (1.0 if "github" in lowered else 0.5)
    return {
        "hardware": hardware,
        "has_video": has_video,
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
        1.0 if signals.get("has_video") else 0.5,
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
    if signals.get("has_video"):
        vid_rate = _group_rate(projects, lambda p: p.has_video)
        if vid_rate is not None:
            why.append(f"projects with a demo video finalisted at {vid_rate:.0%} here")
            if vid_rate > rate:
                rate = 0.6 * rate + 0.4 * vid_rate

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
                why.append("named stack tags are not strongly tied to finalist status here")
    try:
        repo_n = 1.0 if isinstance(signals.get("has_repo"), bool) and signals.get("has_repo") else float(signals.get("has_repo") if signals.get("has_repo") is not None else 0.5)
    except (TypeError, ValueError):
        repo_n = 0.5
    if repo_n >= 0.99:
        repo_rate = _group_rate(projects, lambda p: p.has_repo)
        if repo_rate is not None and repo_rate > rate:
            rate = 0.7 * rate + 0.3 * repo_rate
    elif repo_n <= 0.01:
        no_repo_rate = _group_rate(projects, lambda p: not p.has_repo)
        if no_repo_rate is not None and no_repo_rate < rate:
            rate = 0.7 * rate + 0.3 * no_repo_rate
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
        self.openai_ok = bool((os.getenv("OPENAI_API_KEY") or "").strip())
        self.source = "sample.json"
        self.embeddings_norm: np.ndarray | None = None
        self.p_ref: np.ndarray = np.array([], dtype=np.float64)
        self._search_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._facts_block: str | None = None
        self._title_index: list[str] | None = None
        # UMAP/numba transform is not thread-safe; FastAPI runs sync routes
        # on a threadpool so two simultaneous /api/ask calls can kill the worker.
        self._umap_lock = threading.Lock()
        self.prize_memory = None

    def _openai_configured(self) -> bool:
        return bool((os.getenv("OPENAI_API_KEY") or "").strip())

    def load(self) -> None:
        from schema import corpus_source

        self.projects = load_corpus()
        self.source = corpus_source()
        self.by_slug = {p.slug: p for p in self.projects}
        self._require_prizes_file()
        self._require_event_file()
        from prizes import PrizeMemory

        self.prize_memory = PrizeMemory.load()
        self._fit_fallback()
        self._load_embeddings()
        self._load_map()
        self._load_model()
        if self.model_blob is None:
            if len(self.projects) <= 120:
                print("artifact model.pkl missing — fitting TF-IDF fallback classifier")
                self._fit_fallback_model()
            else:
                print("artifact model.pkl missing — scoring from corpus signals only")
        self._assert_aligned()
        self._ensure_p_ref()
        n = len(self.projects)
        n_emb = 0 if self.embeddings is None else int(self.embeddings.shape[0])
        n_map = len((self.map_data or {}).get("points") or [])
        n_pool = 0 if not self.prize_memory else len(self.prize_memory.winners)
        print(f"loaded corpus={n} embeddings={n_emb} map={n_map} p_ref={int(self.p_ref.size)} prize_winners={n_pool}")

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

    def _require_prizes_file(self) -> None:
        from prizes import prizes_file

        src = prizes_file()
        if not src.exists():
            raise RuntimeError(f"prizes.json missing at {src}")
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"prizes.json unreadable at {src}: {exc}") from exc
        tracks = raw if isinstance(raw, list) else (raw or {}).get("tracks")
        if not tracks:
            raise RuntimeError(f"prizes.json has no tracks at {src}")

    def _require_event_file(self) -> None:
        src = event_path()
        if not src.exists():
            raise RuntimeError(f"event.json missing at {src}")
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
            datetime.fromisoformat(str(raw.get("build_end") or ""))
        except Exception as exc:
            raise RuntimeError(f"event.json unreadable at {src}: {exc}") from exc

    def _assert_aligned(self) -> None:
        n = len(self.projects)
        if self.embeddings is not None and int(self.embeddings.shape[0]) != n:
            raise RuntimeError(
                f"embeddings.npy has {self.embeddings.shape[0]} rows but corpus has {n}. "
                "Neighbour rows would attach to the wrong projects. Rebuild with build.py."
            )
        n_map = len((self.map_data or {}).get("points") or [])
        if n_map and n_map != n:
            raise RuntimeError(
                f"map.json has {n_map} points but corpus has {n}. "
                "The map would pin the wrong projects. Rebuild with build.py."
            )

    def _load_embeddings(self) -> None:
        src = emb_path()
        if not src.exists():
            print(f"artifact embeddings.npy missing at {src} — TF-IDF fallback")
            self.embeddings = None
            self.embeddings_norm = None
            return
        try:
            arr = np.load(src)
        except Exception as exc:
            raise RuntimeError(f"embeddings.npy unreadable at {src}: {exc}") from exc
        if arr.shape[0] != len(self.projects):
            raise RuntimeError(
                f"embeddings.npy has {arr.shape[0]} rows but corpus has {len(self.projects)}. "
                "Neighbour rows would attach to the wrong projects. Rebuild with build.py."
            )
        self.embeddings = arr
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
        self.embeddings_norm = arr / norms

    def _load_map(self) -> None:
        src = map_path()
        if not src.exists():
            print(f"artifact map.json missing at {src} — PCA fallback coordinates")
            self.map_data = json_safe(self._map_from_fallback())
            return
        try:
            payload = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"map.json unreadable at {src}: {exc}") from exc
        points = payload.get("points") if isinstance(payload, dict) else None
        if not points:
            raise RuntimeError(f"map.json has no points at {src}")
        if len(points) != len(self.projects):
            raise RuntimeError(
                f"map.json has {len(points)} points but corpus has {len(self.projects)}. "
                "The map would pin the wrong projects. Rebuild with build.py."
            )
        self.map_data = json_safe(payload)

    def _load_model(self) -> None:
        src = model_path()
        if not src.exists():
            print(f"artifact model.pkl missing at {src}")
            self.model_blob = None
            return
        try:
            self.model_blob = joblib.load(src)
        except Exception as exc:
            print(f"artifact model.pkl unreadable at {src} ({exc}) — fallback")
            self.model_blob = None

    def _ensure_p_ref(self) -> None:
        """Sorted corpus P(finalist) from the same classifier /api/ask uses."""
        blob = self.model_blob or {}
        raw = blob.get("p_ref")
        arr = np.array([], dtype=np.float64)
        if raw is not None:
            arr = np.asarray(raw, dtype=np.float64).ravel()
            arr = arr[np.isfinite(arr)]
            arr = np.clip(arr, 0.0, 1.0)
        if arr.size and arr.size == len(self.projects):
            self.p_ref = np.sort(arr)
            return
        computed = self._compute_p_ref()
        self.p_ref = computed
        if self.model_blob is not None and computed.size:
            self.model_blob["p_ref"] = computed
        if computed.size:
            print(f"p_ref computed n={computed.size}")
        else:
            print("p_ref empty — Finalist Score will be 0 until the classifier can score the corpus")

    def _compute_p_ref(self) -> np.ndarray:
        if not self.model_blob or not self.projects:
            return np.array([], dtype=np.float64)
        clf = self.model_blob.get("model")
        pca = self.model_blob.get("pca")
        if clf is None or pca is None:
            return np.array([], dtype=np.float64)
        embed_space = str(self.model_blob.get("embed_space") or "")
        if embed_space == "tfidf" or self.embeddings is None:
            if self.tfidf is None:
                return np.array([], dtype=np.float64)
            emb = self.tfidf.toarray()
        else:
            emb = np.asarray(self.embeddings, dtype=float)
        if emb.shape[0] != len(self.projects):
            return np.array([], dtype=np.float64)
        try:
            reduced = pca.transform(emb)
            struct = np.array([_structured_features(p) for p in self.projects], dtype=float)
            x = np.hstack([reduced, struct])
            return np.sort(_finalist_proba(clf, x))
        except Exception as exc:
            print(f"p_ref compute skipped ({exc})")
            return np.array([], dtype=np.float64)

    def percentile_score(self, p: float) -> int:
        return percentile_rank(p, self.p_ref)

    def _map_from_fallback(self) -> dict[str, Any]:
        assert self.fallback_coords is not None
        xs = [float(c[0]) for c in self.fallback_coords]
        ys = [float(c[1]) for c in self.fallback_coords]
        points = [
            _point_payload(p, x, y)
            for p, x, y in zip(self.projects, xs, ys)
        ]
        return {"points": points, "bounds": _bounds(xs, ys)}

    def _fit_fallback_model(self) -> None:
        """Small LOYO logreg on the in-memory TF-IDF so /api/ask has a number
        before build.py has run. Honest AUC; do not pretend it is the real model.
        """
        try:
            self._fit_fallback_model_inner()
        except Exception as exc:
            print(f"artifact fallback classifier skipped ({exc})")
            self.model_blob = None

    def _fit_fallback_model_inner(self) -> None:
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
        try:
            splits = list(LeaveOneGroupOut().split(x, y, groups=years))
        except ValueError:
            splits = []
        for train_idx, test_idx in splits:
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
            "p_ref": np.sort(_finalist_proba(model, x)),
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
                    "slug": str(p.slug),
                    "title": str(p.title or ""),
                    "year": int(p.year or 0),
                    "tagline": str(p.tagline or ""),
                    "finalist": bool(p.finalist),
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

    def _openai_embed(self, text: str, timeout: float = 6.0) -> np.ndarray:
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY unset")
        from openai import OpenAI

        kwargs = {"api_key": key, "timeout": timeout, "max_retries": 0}
        base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base:
            kwargs["base_url"] = base
        client = OpenAI(**kwargs)
        resp = client.embeddings.create(model="text-embedding-3-small", input=text[:8000])
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _openai_neighbours(self, vec: np.ndarray, k: int = 5) -> list[tuple[str, float]]:
        assert self.embeddings is not None
        a = vec / (np.linalg.norm(vec) + 1e-9)
        b = self.embeddings_norm
        if b is None:
            b = self.embeddings / (np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-9)
        sims = b @ a
        order = np.argsort(-sims)[:k]
        return [(self.projects[i].slug, float(sims[i])) for i in order]

    def _cosine_for_slugs(
        self, vec: np.ndarray | None, pairs: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        """Keep Elasticsearch ranking; attach cosine for display.

        Hybrid RRF scores are 1/(60+rank) so every neighbour looks like 0.016.
        """
        if vec is None or not pairs or self.embeddings_norm is None:
            return pairs
        a = np.asarray(vec, dtype=np.float32).reshape(-1)
        if a.size != int(self.embeddings_norm.shape[1]):
            return pairs
        a = a / (np.linalg.norm(a) + 1e-9)
        index = {p.slug: i for i, p in enumerate(self.projects)}
        out: list[tuple[str, float]] = []
        for slug, fallback in pairs:
            i = index.get(slug)
            if i is None:
                out.append((slug, float(fallback)))
                continue
            sim = float(self.embeddings_norm[i] @ a)
            if sim != sim:
                sim = float(fallback)
            out.append((slug, sim))
        return out

    def search(self, text: str, k: int = 400, min_sim: float = 0.2) -> dict[str, Any]:
        """Cosine overlay. OpenAI space when embeddings.npy exists; else TF-IDF."""
        empty = {"matches": [], "max_sim": 0.0, "source": "empty", "n": 0}
        q = (text or "").strip()
        if not q:
            return json_safe(empty)
        key = q.casefold()
        hit = self._search_cache.get(key)
        if hit is not None:
            self._search_cache.move_to_end(key)
            return json_safe(hit)
        try:
            out = self._search_uncached(q, k=k, min_sim=min_sim)
        except Exception as exc:
            print(f"search failed ({exc})")
            out = empty
        if out.get("source") != "empty":
            self._search_cache[key] = out
            while len(self._search_cache) > 64:
                self._search_cache.popitem(last=False)
        return json_safe(out)

    def _search_uncached(self, q: str, k: int, min_sim: float) -> dict[str, Any]:
        empty = {"matches": [], "max_sim": 0.0, "source": "empty", "n": 0}
        if (
            self._openai_configured()
            and self.embeddings is not None
            and self.embeddings_norm is not None
        ):
            try:
                vec = self._openai_embed(q, timeout=6.0)
                a = vec / (np.linalg.norm(vec) + 1e-9)
                sims = self.embeddings_norm @ a
                return self._pack_search(sims, source="openai", k=k, min_sim=min_sim)
            except Exception as extra:
                print(f"search openai skipped ({extra})")
        try:
            if self.vectorizer is None or self.tfidf is None:
                return empty
            qv = self.vectorizer.transform([q])
            sims = cosine_similarity(qv, self.tfidf).ravel()
            return self._pack_search(sims, source="tfidf", k=k, min_sim=min_sim)
        except Exception as extra:
            print(f"search tfidf skipped ({extra})")
            return empty

    def _pack_search(
        self, sims: np.ndarray, source: str, k: int, min_sim: float
    ) -> dict[str, Any]:
        arr = np.asarray(sims, dtype=float).ravel()
        arr = np.where(np.isfinite(arr), arr, 0.0)
        if arr.size == 0:
            return {"matches": [], "max_sim": 0.0, "source": source, "n": 0}
        k = max(1, min(int(k), arr.size, 400))
        order = np.argsort(-arr)
        matches = []
        max_sim = 0.0
        for i in order:
            s = float(arr[i])
            if s < min_sim:
                break
            if len(matches) >= k:
                break
            matches.append({"slug": str(self.projects[int(i)].slug), "sim": round(s, 4)})
            if s > max_sim:
                max_sim = s
        return {
            "matches": matches,
            "max_sim": round(float(max_sim), 4) if matches else 0.0,
            "source": source,
            "n": len(matches),
        }

    def build_context(
        self, question_or_idea: str, vec: np.ndarray | None = None
    ) -> dict[str, Any]:
        """Compact factual block for Gemini. Numbers come from corpus artifacts."""
        q = (question_or_idea or "").strip()
        hits = self._cosine_hits(q, k=20, vec=vec) if q else []
        titles: list[str] = []
        lines = [
            self._what_prior_art(),
            "",
            "RELEVANT PROJECTS (title | year | finalist | similarity | tagline):",
        ]
        for proj, sim in hits:
            title = (proj.title or proj.slug or "").replace("|", "/").strip()
            tag = (proj.tagline or "").replace("|", "/")[:120].strip()
            flag = "Y" if proj.finalist else "N"
            year = int(proj.year) if proj.year else 0
            lines.append(f"- {title} | {year} | {flag} | {sim:.3f} | {tag}")
            if (proj.title or "").strip():
                titles.append(proj.title.strip())
        if not hits:
            lines.append("- none retrieved")
        from prizes import prize_prompt_lines, prize_prompt_names

        prize_names = prize_prompt_names()
        lines.extend(["", self._static_facts_block(), "", self._prize_block(prize_prompt_lines()), "", self._event_block()])
        return {
            "text": "\n".join(lines)[:12000],
            "titles": titles,
            "prizes": list(prize_names),
        }

    def _what_prior_art(self) -> str:
        return (
            "Prior Art maps Hack the North submissions from 2014–2025 and places a new idea "
            "next to real past projects. Finalist Score (0–100) is the percentile of the "
            "classifier's P(finalist) versus that corpus; 'finalist' means a top-12 project "
            "that year. We only know finalist status, not sponsor-track outcomes."
        )

    def _static_facts_block(self) -> str:
        if self._facts_block is not None:
            return self._facts_block
        n = len(self.projects)
        n_fin = sum(1 for p in self.projects if p.finalist)
        base = (100.0 * n_fin / n) if n else 0.0
        by_year: dict[int, list[int]] = {}
        for p in self.projects:
            row = by_year.setdefault(int(p.year), [0, 0])
            row[0] += 1
            if p.finalist:
                row[1] += 1
        year_bits = ", ".join(
            f"{y}: {counts[1]}/{counts[0]}" for y, counts in sorted(by_year.items())
        )
        auc = None
        if self.model_blob:
            try:
                raw = self.model_blob.get("auc")
                auc = float(raw) if raw is not None else None
                if auc is not None and (auc != auc or auc < 0.4 or auc > 1.0):
                    auc = None
            except (TypeError, ValueError):
                auc = None
        auc_line = f"{auc:.3f} leave-one-year-out" if auc is not None else "not available"
        lines = [
            f"CORPUS: {n} projects, {n_fin} finalists, base rate {base:.1f}%.",
            f"PER-YEAR FINALISTS (finalists/projects): {year_bits}.",
            f"MODEL AUC: {auc_line}.",
            "FINDINGS:",
        ]
        lines.extend(self._findings_lines())
        self._facts_block = "\n".join(lines)
        return self._facts_block

    def _findings_lines(self) -> list[str]:
        src = FINDINGS_PATH
        if not src.exists():
            return ["- findings.json not loaded"]
        try:
            payload = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            return ["- findings.json unreadable"]
        out: list[str] = []
        for chart in payload.get("charts") or []:
            if not isinstance(chart, dict):
                continue
            claim = str(chart.get("claim") or "").strip()
            if not claim:
                continue
            if chart.get("kind") == "bars":
                bits = []
                for bar in chart.get("bars") or []:
                    if not isinstance(bar, dict):
                        continue
                    label = str(bar.get("label") or "").strip()
                    try:
                        val = float(bar.get("value") or 0) * 100.0
                        nn = int(bar.get("n") or 0)
                    except (TypeError, ValueError):
                        continue
                    bits.append(f"{label} {val:.1f}% (n={nn})")
                extra = f": {', '.join(bits)}" if bits else ""
                out.append(f"- {claim}{extra}")
            else:
                out.append(f"- {claim}")
        ai = payload.get("ai_writing") if isinstance(payload.get("ai_writing"), dict) else {}
        claim = str((ai or {}).get("claim") or "").strip()
        if claim:
            out.append(f"- {claim}")
        return out or ["- no finding claims"]

    def _prize_block(self, names: list[str]) -> str:
        if not names:
            return "ALLOWED 2026 PRIZES: none. Do not name any prize, track, or award."
        body = "\n".join(
            n if str(n).startswith("- ") else f"- {n}" for n in names
        )
        return (
            "ALLOWED 2026 PRIZES (copy the name exactly or do not name one). "
            "The blurb is what the challenge actually is. "
            "Only mention a prize if the idea as written could enter that exact challenge. "
            "WHITEOUT, Bracket Bot, LeLamp, and QNX are not generic hardware prizes.\n"
            + body
        )

    def _event_block(self) -> str:
        src = event_path()
        remaining = hours_until_build_end()
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
            end = str(raw.get("build_end") or "")
            tz = str(raw.get("tz") or "")
        except Exception:
            end, tz = "", ""
        return (
            f"EVENT: Hack the North 2026. build_end {end or 'unknown'} ({tz or 'unknown'}). "
            f"Hours remaining until build_end: {remaining:.2f}."
        )

    def _cosine_hits(
        self, text: str, k: int = 20, vec: np.ndarray | None = None
    ) -> list[tuple[Project, float]]:
        n = len(self.projects)
        if n == 0:
            return []
        k = max(1, min(int(k), 20, n))
        sims = None
        if (
            vec is not None
            and self.embeddings_norm is not None
            and int(np.asarray(vec).reshape(-1).size) == int(self.embeddings_norm.shape[1])
        ):
            a = np.asarray(vec, dtype=float).reshape(-1)
            a = a / (np.linalg.norm(a) + 1e-9)
            sims = self.embeddings_norm @ a
        elif self._openai_configured() and self.embeddings_norm is not None and (text or "").strip():
            try:
                raw = self._openai_embed(text, timeout=6.0)
                a = raw / (np.linalg.norm(raw) + 1e-9)
                sims = self.embeddings_norm @ a
            except Exception as extra:
                print(f"context openai skipped ({extra})")
        if sims is None:
            try:
                if self.vectorizer is None or self.tfidf is None:
                    return []
                qv = self.vectorizer.transform([text or ""])
                sims = cosine_similarity(qv, self.tfidf).ravel()
            except Exception as extra:
                print(f"context tfidf skipped ({extra})")
                return []
        arr = np.asarray(sims, dtype=float).ravel()
        arr = np.where(np.isfinite(arr), arr, 0.0)
        order = np.argsort(-arr)[:k]
        out: list[tuple[Project, float]] = []
        for i in order:
            idx = int(i)
            if idx < 0 or idx >= n:
                continue
            out.append((self.projects[idx], float(arr[idx])))
        return out

    def _title_list(self) -> list[str]:
        if self._title_index is not None:
            return self._title_index
        names = sorted(
            {(p.title or "").strip() for p in self.projects if (p.title or "").strip() and len((p.title or "").strip()) >= 6},
            key=len,
            reverse=True,
        )
        self._title_index = names
        return names

    def _ungrounded_projects(self, text: str, ctx: dict[str, Any]) -> list[str]:
        blob = text or ""
        if not blob:
            return []
        allowed = {(t or "").strip().lower() for t in (ctx.get("titles") or []) if t}
        found: list[str] = []
        low = blob.lower()
        for title in self._title_list():
            key = title.lower()
            if key in allowed:
                continue
            if key not in low:
                continue
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(title) + r"(?![A-Za-z0-9])", blob, re.I):
                found.append(title)
        return found

    def _ground_validate(self, text: str, ctx: dict[str, Any], *, strip_all_pct: bool) -> tuple[str, list[str]]:
        from prizes import coach_move_violation, load_prize_tracks

        flags: list[str] = []
        out = text or ""
        for title in self._ungrounded_projects(out, ctx):
            flags.append(f"project {title}")
            out = re.sub(re.escape(title), "", out, flags=re.I)
        if re.search(
            r"\b(won|winner|winners|awarded|took home|first place|second place|third place)\b",
            out,
            re.I,
        ):
            flags.append("claimed a win")
            out = re.sub(
                r"\b(won|winner|winners|awarded|took home|first place|second place|third place)\b",
                "finalist",
                out,
                flags=re.I,
            )
        reason = coach_move_violation(out, tracks=load_prize_tracks(), projects=self.projects)
        if reason:
            flags.append(reason)
        if strip_all_pct:
            out = _strip_percents(out)
        else:
            out = _strip_unverified_percents(out, ctx.get("text") or "")
        out = re.sub(r"\s{2,}", " ", out).strip(" -–—,;.")
        return out, flags

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
            with self._umap_lock:
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
            return None, json_safe(meta)
        auc = self.model_blob.get("auc")
        try:
            auc_f = float(auc) if auc is not None else None
        except (TypeError, ValueError):
            auc_f = None
        if auc_f is not None and (auc_f != auc_f or auc_f < 0.4 or auc_f > 1.0):
            auc_f = None
        spread_raw = self.model_blob.get("auc_spread") or []
        spread = []
        for s in spread_raw:
            try:
                spread.append(round(float(s), 3))
            except (TypeError, ValueError):
                continue
        meta.update(
            {
                "auc": None if auc_f is None else round(float(auc_f), 3),
                "auc_spread": spread,
                "n_train": int(self.model_blob.get("n_train", meta["n_train"]) or meta["n_train"]),
                "n_finalists": int(self.model_blob.get("n_finalists", meta["n_finalists"]) or meta["n_finalists"]),
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
            return float(proba[idx]), json_safe(meta)
        except Exception:
            return None, json_safe(meta)

    def ask(self, text: str, github: str = "", devpost: str = "") -> dict[str, Any]:
        prompt = (text or "").strip()
        repo = None
        if github.strip():
            from github_repo import compose_embed_text, fetch_repo

            repo = fetch_repo(github, timeout=5.0)
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
        source = "tfidf"

        if self._openai_configured() and self.embeddings is not None:
            try:
                embed_vec = self._openai_embed(document, timeout=6.0)
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
            source = "tfidf"
            print("neighbours source=tfidf")
        else:
            try:
                pairs = self.es_neighbours(embed_vec, document, k=5)
                pairs = self._cosine_for_slugs(embed_vec, pairs)
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
        try:
            from prizes import advise_tracks, fetch_tracks, load_prize_tracks

            tracks = [dict(t) for t in load_prize_tracks()]
            fetched_url = None
            if (devpost or "").strip():
                fetched = fetch_tracks(devpost, timeout=6.0)
                if fetched.get("ok"):
                    fetched_url = fetched.get("url")
                    by_name = {
                        (t.get("name") or "").lower(): t for t in (fetched.get("tracks") or [])
                    }
                    for t in tracks:
                        extra = by_name.get((t.get("name") or "").lower())
                        if extra and extra.get("description"):
                            t["description"] = extra["description"]
            ranked = advise_tracks(
                document,
                tracks,
                self.projects,
                neighbour_slugs=[slug for slug, _ in pairs],
                repo=repo if repo and repo.get("ok") else None,
                prompt=prompt,
                signals=signals,
                prize_memory=self.prize_memory,
            )
            pool = self.prize_memory
            tracks_out = {
                "ok": True,
                "url": fetched_url,
                "n": len(tracks),
                "ranked": ranked,
                "n_winners": 0 if pool is None else len(pool.winners),
                "n_events": 0 if pool is None else pool.n_events,
                "pool_source": "" if pool is None else Path(pool.source).name,
                "method": (
                    "Likeness to labeled prize winners, pooled across events "
                    "for recurring MLH families (Gemini, ElevenLabs, MongoDB). "
                    "Niche tracks still get a cosine to the few labeled writeups. "
                    "This is not the 12-finalist score."
                ),
                "error": None,
            }
        except Exception as exc:
            tracks_out = {
                "ok": False,
                "url": None,
                "n": 0,
                "ranked": [],
                "error": str(exc)[:200] or "could not rank prize tracks",
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

        return json_safe(
            {
                "point": point,
                "neighbours": self.neighbour_records(pairs),
                "probability": round(finite_unit(prob), 4),
                "score": self.percentile_score(prob),
                "model": model_meta,
                "backend": used,
                "source": source,
                "github": github_out,
                "why": why,
                "signals": {
                    "hardware": bool(signals.get("hardware")),
                    "tags": [str(t) for t in (signals.get("tags") or [])[:8]],
                },
                "tracks": tracks_out,
            }
        )

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
        return finite_unit(prob)

    def _embed_document(self, document: str) -> tuple[np.ndarray | None, dict[str, float]]:
        embed_vec = None
        point = {"x": 0.0, "y": 0.0}
        if self._openai_configured() and self.embeddings is not None:
            try:
                embed_vec = self._openai_embed(document, timeout=6.0)
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

    def _openai_embed_batch(self, texts: list[str], timeout: float = 6.0) -> list[np.ndarray]:
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY unset")
        from openai import OpenAI

        kwargs = {"api_key": key, "timeout": timeout, "max_retries": 0}
        base = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base:
            kwargs["base_url"] = base
        client = OpenAI(**kwargs)
        resp = client.embeddings.create(
            model="text-embedding-3-small", input=[t[:8000] for t in texts]
        )
        items = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        return [np.array(item.embedding, dtype=np.float32) for item in items]

    def _gemini_raw(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int = 768,
        timeout: float = 8.0,
    ) -> str:
        key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY unset")
        import httpx

        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "maxOutputTokens": max(256, min(int(max_output_tokens), 2048)),
            },
        }
        last_err: Exception | None = None
        base = (
            os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        budget = max(4.0, min(float(timeout), 12.0))
        deadline = time.monotonic() + budget
        with httpx.Client(timeout=budget, transport=httpx.HTTPTransport(retries=0)) as client:
            for model in ("gemini-flash-lite-latest", "gemini-flash-latest"):
                remaining = deadline - time.monotonic()
                if remaining < 0.4:
                    break
                url = f"{base}/models/{model}:generateContent"
                try:
                    r = client.post(url, params={"key": key}, json=payload, timeout=remaining)
                except Exception as exc:
                    last_err = exc
                    continue
                if r.status_code >= 400:
                    last_err = RuntimeError(f"{model} {r.status_code}")
                    continue
                try:
                    body = r.json()
                except Exception as exc:
                    last_err = RuntimeError(f"{model} invalid json: {exc}")
                    continue
                parts = (
                    (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts"))
                    or []
                )
                raw = "".join(str(p.get("text") or "") for p in parts).strip()
                if not raw:
                    last_err = RuntimeError(f"{model} empty")
                    continue
                return raw
        raise last_err or RuntimeError("Gemini returned empty")

    def _gemini_coach_moves(self, idea: str, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        system = (
            GROUND_RULES
            + " You coach Hack the North teams. Return STRICT JSON only: "
            '{"moves":[{"label":str,"rationale":str,"reframed_description":str,'
            '"effort_hours":number,'
            '"features":{"hardware":bool,"has_video":bool,"has_repo":bool,"extra_tech_tags":int}}]}. '
            "Give three or four distinct moves. rationale is one sentence. "
            "reframed_description is the whole idea rewritten as if that move already shipped. "
            "You only phrase. effort_hours is hours for a four-person team. "
            "Do not decide feasibility. Numbers are forbidden in label, rationale, and "
            "reframed_description. extra_tech_tags and effort_hours live in JSON fields only. "
            "If you mention a past project, copy its title and year from CONTEXT. "
            "A move does not need a prize. Prefer a public GitHub, a filmed demo, a physical "
            "build of the idea they already described, or a named stack. "
            "If you mention a prize, the current idea must already fit that challenge. "
            "Do not steer a walking aid, cane, or generic sensor project into WHITEOUT, "
            "Bracket Bot, LeLamp, QNX, Dryft, CSE logs, Intact insurance, or another "
            "sponsor's closed challenge."
        )
        user = (
            "CONTEXT:\n"
            f"{(ctx.get('text') or '')[:12000]}\n\n"
            "Idea:\n"
            f"{idea[:2000]}\n\n"
            "Propose moves such as: ship a physical build of THIS idea, film a live demo, "
            "put the code on GitHub, name a real stack, or tighten the judging-day story. "
            "JSON only."
        )
        return _parse_coach_moves(self._gemini_raw(system, user))

    def coach(self, idea: str, time_budget_hours: float | None = None, github: str = "") -> dict[str, Any]:
        """Propose 3–4 moves. Probabilities come from the classifier, never Gemini.

        Feasibility is clock math on this process, not a Gemini decision.
        """
        from github_repo import compose_embed_text, fetch_repo

        remaining, budget = _coach_clock(time_budget_hours)
        prompt = (idea or "").strip()
        repo = None
        if (github or "").strip():
            repo = fetch_repo(github, timeout=5.0)
            document = compose_embed_text(prompt, repo if repo and repo.get("ok") else None) or prompt
        else:
            document = compose_embed_text(prompt, None) or prompt
        signals = parse_signals(document, repo if repo and repo.get("ok") else None)
        if (github or "").strip():
            signals["has_repo"] = 1.0
        gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        embed_vec = None
        if gemini_key or (self._openai_configured() and len(self.projects) >= 80):
            embed_vec, _point = self._embed_document(document)
        elif self.model_blob and self.model_blob.get("embed_space") == "tfidf":
            assert self.vectorizer is not None
            embed_vec = self.vectorizer.transform([document]).toarray()[0]
        baseline_clf, _ = self._probability(embed_vec, signals)
        baseline = self._score_like_ask(embed_vec, signals)
        baseline_score = self.percentile_score(baseline)
        out: dict[str, Any] = {
            "baseline": round(finite_unit(baseline), 4),
            "baseline_score": baseline_score,
            "moves": [],
            "hours_remaining": float(remaining),
            "time_budget_hours": float(budget),
        }
        from prizes import filter_coach_moves, load_prize_tracks

        tracks = load_prize_tracks()
        ctx = self.build_context(document, vec=embed_vec)
        try:
            specs = self._gemini_coach_moves(document, ctx)
        except Exception as exc:
            print(f"coach gemini skipped ({exc})")
            if _gemini_unavailable(exc):
                specs = _fallback_coach_specs(document, signals)
            else:
                return json_safe(out)
        if float(signals.get("has_repo") or 0) >= 1.0:
            specs = [
                s
                for s in specs
                if "github" not in str(s.get("label") or "").lower()
            ]
        kept = []
        for spec in specs:
            spec = _enrich_coach_features(spec, signals)
            drop = False
            for key in ("label", "rationale", "reframed_description"):
                val, flags = self._ground_validate(str(spec.get(key) or ""), ctx, strip_all_pct=True)
                spec[key] = val
                if any("unnamed prize" in f for f in flags):
                    drop = True
            if drop:
                print(f"coach dropped ungrounded prize: {spec.get('label')}")
                continue
            if spec.get("label") and spec.get("reframed_description"):
                feats = spec.get("features") if isinstance(spec.get("features"), dict) else {}
                if feats.get("has_video") and signals.get("has_video"):
                    continue
                if feats.get("hardware") and signals.get("hardware"):
                    continue
                if feats.get("has_repo") and float(signals.get("has_repo") or 0) >= 1.0:
                    continue
                kept.append(spec)
        specs = filter_coach_moves(kept, tracks=tracks, projects=self.projects, idea=prompt)[:6]
        have = {str(s.get("label") or "").lower() for s in specs}
        if float(signals.get("has_repo") or 0) < 1.0 and not any("github" in h for h in have):
            for extra_spec in _fallback_coach_specs(document, signals):
                if "github" in extra_spec["label"].lower():
                    specs.insert(0, extra_spec)
                    have.add(extra_spec["label"].lower())
                    break
        if len(specs) < 2:
            for extra_spec in _fallback_coach_specs(document, signals):
                if extra_spec["label"].lower() in have:
                    continue
                specs.append(extra_spec)
                have.add(extra_spec["label"].lower())
                if len(specs) >= 3:
                    break
        specs = specs[:6]
        if not specs:
            return json_safe(out)
        texts = [s["reframed_description"] for s in specs]
        try:
            vectors = self._openai_embed_batch(texts)
        except Exception as exc:
            print(f"coach embed skipped ({exc})")
            return json_safe(out)
        moves = []
        for spec, vec in zip(specs, vectors):
            moves.append(
                self._pack_coach_move(
                    spec,
                    signals,
                    embed_vec,
                    vec,
                    baseline,
                    baseline_clf,
                    baseline_score,
                    budget,
                )
            )
        moves = [m for m in moves if abs(int(m.get("score_delta") or 0)) >= 1]
        moves.sort(key=lambda m: -m["score_delta"])
        moves = moves[:4]
        for i, move in enumerate(moves):
            move["id"] = f"m{i}"
        out["moves"] = moves
        return json_safe(out)

    def _pack_coach_move(
        self,
        spec: dict[str, Any],
        signals: dict[str, Any],
        embed_vec: np.ndarray | None,
        vec: np.ndarray | None,
        baseline: float,
        baseline_clf: float | None,
        baseline_score: int,
        budget: float,
    ) -> dict[str, Any]:
        spec = _enrich_coach_features(spec, signals)
        feats = spec.get("features") or {}
        hardware = bool(feats.get("hardware"))
        has_video = bool(feats.get("has_video"))
        extra = int(feats.get("extra_tech_tags") or 0)
        reframed = str(spec.get("reframed_description") or "")
        move_signals = dict(signals)
        move_signals["hardware"] = hardware or bool(signals.get("hardware"))
        move_signals["has_video"] = has_video or bool(signals.get("has_video"))
        move_signals["n_tech"] = float(signals.get("n_tech") or 0) + extra
        if move_signals["hardware"] and not signals.get("hardware"):
            move_signals["n_tech"] = float(move_signals["n_tech"]) + 1
        move_signals["length"] = signals.get("length")
        blob = f"{spec.get('label') or ''} {spec.get('rationale') or ''}".lower()
        repo_hint = any(
            w in blob
            for w in ("github", "public repo", "publish the repo", "put the code on")
        )
        if repo_hint or feats.get("has_repo"):
            move_signals["has_repo"] = 1.0
        else:
            move_signals["has_repo"] = signals.get("has_repo")
        move_signals["team_size"] = signals.get("team_size") or 4
        struct = query_features(move_signals)
        # Score the same idea with the move's features. Re-embedding a paraphrase
        # was collapsing every rec to ~1 percentile (or randomly tanking it).
        score_vec = embed_vec if embed_vec is not None else vec
        new_prob = self._score_like_ask(
            score_vec, move_signals, struct=struct, baseline_clf=baseline_clf
        )
        new_score = self.percentile_score(new_prob)
        xy = self._openai_point(vec) if vec is not None else None
        if xy is None and self.fallback_pca is not None:
            try:
                _, xy = self._tfidf_neighbours(reframed)
            except Exception:
                xy = np.array([0.0, 0.0])
        if xy is None:
            xy = np.array([0.0, 0.0])
        delta = float(new_prob) - float(baseline)
        if delta != delta or abs(delta) == float("inf"):
            delta = 0.0
        delta = max(-1.0, min(1.0, delta))
        score_delta = int(new_score) - int(baseline_score)
        score_delta = max(-100, min(100, score_delta))
        effort = float(spec.get("effort_hours") or 4.0)
        if effort != effort or effort < 0:
            effort = 4.0
        return {
            "label": spec.get("label") or "Untitled move",
            "rationale": spec.get("rationale") or "",
            "reframed_description": reframed[:4000],
            "features": dict(feats),
            "new_prob": round(finite_unit(new_prob), 4),
            "delta": round(delta, 4),
            "new_score": new_score,
            "score_delta": score_delta,
            "new_point": {"x": float(xy[0]), "y": float(xy[1])},
            "effort_hours": round(float(effort), 2),
            "feasible": bool(effort <= budget),
        }

    def coach_stack(
        self,
        idea: str,
        specs: list[dict[str, Any]],
        github: str = "",
        time_budget_hours: float | None = None,
    ) -> dict[str, Any]:
        """Rescore a pin-stack of coach moves as one combined idea. No Gemini."""
        from github_repo import compose_embed_text

        remaining, budget = _coach_clock(time_budget_hours)
        prompt = (idea or "").strip()
        document = compose_embed_text(prompt, None) or prompt
        signals = parse_signals(document, None)
        if (github or "").strip():
            signals["has_repo"] = 1.0
        embed_vec = None
        try:
            embed_vec, _point = self._embed_document(document)
        except Exception as exc:
            print(f"coach stack embed skipped ({exc})")
            embed_vec = None
        baseline_clf, _ = self._probability(embed_vec, signals)
        baseline = self._score_like_ask(embed_vec, signals)
        baseline_score = self.percentile_score(baseline)
        clock = {
            "baseline": round(finite_unit(baseline), 4),
            "baseline_score": baseline_score,
            "hours_remaining": float(remaining),
            "time_budget_hours": float(budget),
        }
        cleaned: list[dict[str, Any]] = []
        for spec in specs or []:
            if not isinstance(spec, dict):
                continue
            cleaned.append(spec)
            if len(cleaned) >= 4:
                break
        if not cleaned:
            return json_safe(
                {
                    **clock,
                    "labels": [],
                    "label": "",
                    "new_prob": clock["baseline"],
                    "delta": 0.0,
                    "new_score": baseline_score,
                    "score_delta": 0,
                    "new_point": {"x": 0.0, "y": 0.0},
                    "effort_hours": 0.0,
                    "feasible": True,
                    "features": {},
                }
            )
        combined = _combine_coach_specs(cleaned, prompt)
        packed = self._pack_coach_move(
            combined,
            signals,
            embed_vec,
            None,
            baseline,
            baseline_clf,
            baseline_score,
            budget,
        )
        try:
            _vec, point = self._embed_document(combined["reframed_description"])
            packed["new_point"] = {"x": float(point["x"]), "y": float(point["y"])}
        except Exception as exc:
            print(f"coach stack point skipped ({exc})")
        packed["labels"] = [str(s.get("label") or "") for s in cleaned]
        packed.update(clock)
        return json_safe(packed)

    def chat(self, messages: list[dict[str, Any]], idea: str = "") -> dict[str, Any]:
        """Phrasing-only chat. Numbers come from /api/ask after Preview."""
        from prizes import coach_move_violation, load_prize_tracks

        cleaned: list[dict[str, str]] = []
        for row in messages or []:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            cleaned.append({"role": role, "content": content[:2000]})
        cleaned = cleaned[-8:]
        idea = (idea or "").strip()[:2000]
        empty = {"reply": "Chat could not answer. Place it still works.", "framings": []}
        if not cleaned:
            return json_safe(empty)
        seed = "\n".join(x for x in (idea, cleaned[-1]["content"]) if x).strip()
        ctx = self.build_context(seed)
        try:
            parsed = self._gemini_chat(cleaned, idea, ctx)
        except Exception as extra:
            print(f"chat gemini skipped ({extra})")
            return json_safe(empty)
        reply, flags = self._ground_validate(
            str(parsed.get("reply") or "").strip(), ctx, strip_all_pct=True
        )
        if flags:
            print(f"chat reply stripped ({flags})")
        reply = reply[:2000]
        tracks = load_prize_tracks()
        framings = []
        for i, row in enumerate(parsed.get("framings") or []):
            if not isinstance(row, dict):
                continue
            label, fl = self._ground_validate(str(row.get("label") or "").strip()[:80], ctx, strip_all_pct=True)
            text, ft = self._ground_validate(str(row.get("text") or "").strip()[:2000], ctx, strip_all_pct=True)
            rationale, fr = self._ground_validate(str(row.get("rationale") or "").strip()[:240], ctx, strip_all_pct=True)
            if fl or ft or fr:
                print(f"chat dropped framing ({fl or ft or fr}): {label}")
                continue
            if not label or not text:
                continue
            blob = f"{label} {rationale} {text}"
            reason = coach_move_violation(blob, tracks=tracks, projects=self.projects)
            if reason:
                print(f"chat dropped framing ({reason}): {label}")
                continue
            framings.append(
                {
                    "id": f"f{i}",
                    "label": label,
                    "text": text,
                    "rationale": rationale,
                }
            )
            if len(framings) >= 3:
                break
        if not reply:
            reply = "Here is a tighter framing. Preview it on the map if you want the classifier number."
        reply = _complete_chat_reply(reply, framings)
        return json_safe({"reply": reply, "framings": framings})

    def answer_question(self, question: str) -> dict[str, Any]:
        """Grounded Q&A. If Gemini fails, a short couldn't-answer — never 500."""
        quiet = {
            "reply": "Couldn't answer from the data.",
            "framings": [],
            "citations": [],
        }
        q = (question or "").strip()
        if not q:
            return json_safe(quiet)
        ctx = self.build_context(q)
        try:
            parsed = self._gemini_answer(q, ctx)
        except Exception as extra:
            print(f"answer gemini skipped ({extra})")
            return json_safe(quiet)
        reply, flags = self._ground_validate(
            str(parsed.get("reply") or "").strip(), ctx, strip_all_pct=False
        )
        if flags:
            print(f"answer stripped ({flags})")
            if any(f.startswith("project ") for f in flags):
                reply = "That's not in the data."
        if not reply:
            reply = quiet["reply"]
        allowed = {(t or "").strip().lower() for t in (ctx.get("titles") or [])}
        citations = []
        for row in parsed.get("citations") or []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title or title.lower() not in allowed:
                continue
            try:
                year = int(row.get("year") or 0)
            except (TypeError, ValueError):
                year = 0
            citations.append({"title": title[:120], "year": year})
            if len(citations) >= 8:
                break
        return json_safe({"reply": reply[:2000], "framings": [], "citations": citations})

    def _gemini_chat(
        self, messages: list[dict[str, str]], idea: str, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        system = (
            GROUND_RULES
            + " You help Hack the North teams reframe an idea. Return STRICT JSON only: "
            '{"reply":str,"framings":[{"label":str,"text":str,"rationale":str}]}. '
            "reply is 2 to 5 complete sentences that answer the question. Never open with "
            "'here are N ways' unless every item is finished inside reply. Give zero to two "
            "framings; each framing must include a full rewritten idea in text. "
            "You only phrase. Numbers are forbidden in reply, label, text, and rationale. "
            "You may say finalist. If you mention a past project, copy title and year from CONTEXT."
        )
        history = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        user = (
            "CONTEXT:\n"
            f"{(ctx.get('text') or '')[:12000]}\n\n"
            f"Current idea:\n{(idea or '(none placed yet)')[:2000]}\n\n"
            f"Conversation:\n{history}\n\nJSON only. Finish the reply."
        )
        return _parse_chat(self._gemini_raw(system, user, max_output_tokens=1024, timeout=10.0))

    def _gemini_answer(self, question: str, ctx: dict[str, Any]) -> dict[str, Any]:
        system = (
            GROUND_RULES
            + " Answer the question from CONTEXT only. Return STRICT JSON only: "
            '{"reply":str,"citations":[{"title":str,"year":int}]}. '
            "reply is a few sentences. citations are projects you named, copied from CONTEXT. "
            "If the answer isn't in CONTEXT, reply is exactly: That's not in the data. "
            "and citations is []."
        )
        user = (
            "CONTEXT:\n"
            f"{(ctx.get('text') or '')[:12000]}\n\n"
            f"Question:\n{question[:2000]}\n\nJSON only."
        )
        return _parse_answer(self._gemini_raw(system, user))


def _gemini_unavailable(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    msg = str(exc).lower()
    needles = (
        "unset",
        "timed out",
        "timeout",
        "connect",
        "network",
        "expecting property",
        "expecting value",
        "503",
        "429",
        "500",
        "404",
    )
    return any(n in msg for n in needles)


def _enrich_coach_features(spec: dict[str, Any], signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill hardware/video/repo flags from the move's label, not Gemini's booleans."""
    signals = signals or {}
    feats = spec.get("features") if isinstance(spec.get("features"), dict) else {}
    blob = " ".join(
        str(spec.get(k) or "") for k in ("label", "rationale")
    ).lower()
    hardware = any(
        w in blob for w in ("physical", "hardware", "sensor", "wearable", "prototype you can")
    )
    has_video = any(
        w in blob
        for w in ("video", "film", "youtube", "live demo", "demonstration", "screen recording")
    )
    has_repo = any(
        w in blob for w in ("github", "public repo", "publish the repo", "put the code on")
    )
    try:
        extra = int(feats.get("extra_tech_tags") or 0)
    except (TypeError, ValueError):
        extra = 0
    stackish = any(
        w in blob
        for w in ("name a real stack", "named stack", "name a concrete stack", "name real stack")
    )
    extra = 2 if stackish else 0
    if hardware and signals.get("hardware"):
        extra = 0
    spec["features"] = {
        "hardware": hardware,
        "has_video": has_video,
        "has_repo": has_repo,
        "extra_tech_tags": max(0, min(8, extra)),
    }
    return spec


def _combine_coach_specs(specs: list[dict[str, Any]], idea: str) -> dict[str, Any]:
    """Merge pinned moves into one spec so features OR and the map point is re-embedded."""
    core = (idea or "").strip()
    labels: list[str] = []
    rationales: list[str] = []
    additions: list[str] = []
    effort = 0.0
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        lab = str(spec.get("label") or "").strip()
        if lab:
            labels.append(lab)
        rat = str(spec.get("rationale") or "").strip()
        if rat:
            rationales.append(rat)
        try:
            hours = float(spec.get("effort_hours") or 0.0)
        except (TypeError, ValueError):
            hours = 0.0
        if hours != hours or hours < 0:
            hours = 0.0
        effort += hours
        ref = str(spec.get("reframed_description") or "").strip()
        if not ref:
            continue
        if core:
            n = min(48, len(core))
            prefix = core[:n]
            if prefix and ref.lower().startswith(prefix.lower()):
                rest = ref[len(core) :].strip() if len(ref) >= len(core) else ref
                additions.append(rest or ref)
            else:
                additions.append(ref)
        else:
            additions.append(ref)
    effort = max(0.0, min(168.0, effort))
    reframed = " ".join(x for x in [core, *additions] if x).strip()
    if not reframed:
        reframed = core or "stacked moves"
    return {
        "label": " + ".join(labels)[:160] or "Stacked moves",
        "rationale": " ".join(rationales)[:240] or "Stacked moves, rescored together.",
        "reframed_description": reframed[:4000],
        "effort_hours": effort,
    }


def _fallback_coach_specs(idea: str, signals: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Phrase-only moves when Gemini is down. No prize names."""
    core = (idea or "this project").strip() or "this project"
    signals = signals or {}
    specs: list[dict[str, Any]] = []
    if float(signals.get("has_repo") or 0) < 1.0:
        specs.append(
            {
                "label": "Put the code on GitHub",
                "rationale": "A public repo is what judges actually open; writeups without one look unfinished.",
                "reframed_description": f"{core} The working code is on a public GitHub repository.",
                "effort_hours": 1.5,
                "features": {"hardware": False, "has_video": False, "has_repo": True, "extra_tech_tags": 0},
            }
        )
    if not signals.get("has_video"):
        specs.append(
            {
                "label": "Film a live demo",
                "rationale": "A short video of it working is the fastest way to make the writeup feel real.",
                "reframed_description": f"{core} Includes a filmed live demo of the working prototype.",
                "effort_hours": 3.0,
                "features": {"hardware": False, "has_video": True, "has_repo": False, "extra_tech_tags": 0},
            }
        )
    if not signals.get("hardware"):
        specs.append(
            {
                "label": "Ship a physical build",
                "rationale": "A thing a judge can hold reads as more finished than a deck.",
                "reframed_description": f"{core} Built as a physical prototype you can demo in person.",
                "effort_hours": 6.0,
                "features": {"hardware": True, "has_video": False, "has_repo": False, "extra_tech_tags": 0},
            }
        )
    specs.extend(
        [
            {
                "label": "Name a real stack",
                "rationale": "Specific tools in the writeup read as a build, not a pitch.",
                "reframed_description": f"{core} Names a concrete stack and how each piece is used on judging day.",
                "effort_hours": 2.0,
                "features": {"hardware": False, "has_video": False, "has_repo": False, "extra_tech_tags": 2},
            },
            {
                "label": "Tighten the judging story",
                "rationale": "One sentence about what a judge should see in thirty seconds.",
                "reframed_description": f"{core} Opens with a thirty-second judging-day demo and what it proves.",
                "effort_hours": 2.0,
                "features": {"hardware": False, "has_video": False, "has_repo": False, "extra_tech_tags": 0},
            },
        ]
    )
    return specs[:4]


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
        label = re.sub(r"\b\d+(?:\.\d+)?%", "", label)
        rationale = re.sub(r"\b\d+(?:\.\d+)?%", "", rationale)
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
                "effort_hours": _parse_effort_hours(row.get("effort_hours")),
                "features": {
                    "hardware": bool(feats.get("hardware")),
                    "has_video": bool(feats.get("has_video")),
                    "has_repo": bool(feats.get("has_repo")),
                    "extra_tech_tags": extra,
                },
            }
        )
    return moves[:8]


def _strip_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _loads_jsonish(raw: str) -> Any:
    text = _strip_fence(raw)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError:
        return None


def _json_string_field(text: str, key: str) -> str:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"', text)
    if not m:
        return ""
    i = m.end()
    out: list[str] = []
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            out.append(ch)
            escaped = True
        elif ch == '"':
            break
        else:
            out.append(ch)
        i += 1
    raw = "".join(out)
    try:
        return json.loads('"' + raw + '"')
    except json.JSONDecodeError:
        return raw.replace("\\n", "\n").replace('\\"', '"')


def _recover_json_array(text: str, key: str) -> list[Any]:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*\[', text)
    if not m:
        return []
    chunk = text[m.end() - 1 :]
    try:
        arr, _ = json.JSONDecoder().raw_decode(chunk)
        return arr if isinstance(arr, list) else []
    except json.JSONDecodeError:
        pass
    out: list[Any] = []
    dec = json.JSONDecoder()
    i = 1
    while i < len(chunk):
        while i < len(chunk) and chunk[i] in " \n\r\t,":
            i += 1
        if i >= len(chunk) or chunk[i] in "]":
            break
        if chunk[i] != "{":
            break
        try:
            obj, end = dec.raw_decode(chunk[i:])
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            out.append(obj)
        i += end
    return out


def _looks_unfinished_reply(reply: str) -> bool:
    text = (reply or "").strip()
    if not text:
        return True
    low = text.lower()
    if text.endswith((",", ";", ":", "...", "…", "-")):
        return True
    intro = re.search(
        r"(?i)\b(here are|here is|below are|two ways|a few ways|try these|consider these)\b",
        low,
    )
    if intro and len(text) < 280:
        sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
        if len(sentences) < 2:
            return True
        if low.rstrip().endswith(("track", "prize", "ways", "way", "options", "option")):
            return True
    return False


def _complete_chat_reply(reply: str, framings: list[Any]) -> str:
    text = (reply or "").strip()
    if not _looks_unfinished_reply(text):
        return text
    if framings:
        n = sum(1 for row in framings if isinstance(row, dict))
        if n == 1:
            return "One concrete reframe is below. Preview it on the map if you want a classifier score."
        return "A few concrete reframes are below. Preview one on the map if you want a classifier score."
    return (
        "Name the sponsor product in the README and demo a real call to it. "
        "A related word in the pitch is not enough for a Best Use track."
    )


def _parse_chat(raw: str) -> dict[str, Any]:
    text = _strip_fence(raw)
    data = _loads_jsonish(text)
    if not isinstance(data, dict):
        data = {}
    rows = data.get("framings") or data.get("ideas") or []
    if not isinstance(rows, list) or not rows:
        rows = _recover_json_array(text, "framings") or _recover_json_array(text, "ideas")
    reply = str(data.get("reply") or "").strip() or _json_string_field(text, "reply")
    return {"reply": reply, "framings": rows if isinstance(rows, list) else []}


def _parse_answer(raw: str) -> dict[str, Any]:
    text = _strip_fence(raw)
    data = _loads_jsonish(text)
    if not isinstance(data, dict):
        data = {}
    rows = data.get("citations") or []
    if not isinstance(rows, list) or not rows:
        rows = _recover_json_array(text, "citations")
    reply = str(data.get("reply") or "").strip() or _json_string_field(text, "reply")
    return {"reply": reply, "citations": rows if isinstance(rows, list) else []}


def _strip_percents(s: str) -> str:
    text = re.sub(r"\b\d+(?:\.\d+)?%", "", s or "")
    return re.sub(r"\s{2,}", " ", text).strip()


def _strip_unverified_percents(text: str, context: str) -> str:
    allowed = set(re.findall(r"\b\d+(?:\.\d+)?%", context or ""))
    def keep(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0) in allowed else ""
    out = re.sub(r"\b\d+(?:\.\d+)?%", keep, text or "")
    return re.sub(r"\s{2,}", " ", out).strip()


def hours_until_build_end(
    now: datetime | None = None, path: Path | None = None
) -> float:
    """Hours left until data/event.json build_end. Never negative. File only."""
    src = path or event_path()
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
        end = datetime.fromisoformat(str(raw.get("build_end") or ""))
        tz_name = str(raw.get("tz") or "").strip()
        if end.tzinfo is None:
            end = end.replace(tzinfo=ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo)
    except Exception:
        return 0.0
    clock = now if now is not None else datetime.now().astimezone()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=end.tzinfo)
    return round(max(0.0, (end - clock).total_seconds() / 3600.0), 2)


def _coach_clock(time_budget_hours: float | None) -> tuple[float, float]:
    remaining = hours_until_build_end()
    if time_budget_hours is None:
        return remaining, remaining
    try:
        budget = max(0.0, float(time_budget_hours))
    except (TypeError, ValueError):
        budget = remaining
    return remaining, round(budget, 2)


def _parse_effort_hours(raw: Any) -> float:
    if isinstance(raw, bool):
        return 4.0
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(raw or ""))]
        val = max(nums) if nums else 4.0
    if val != val or val < 0:
        return 4.0
    return round(max(0.25, min(72.0, val)), 2)


engine = Engine()
