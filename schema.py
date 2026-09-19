"""The corpus contract between the data lane (Richa) and the app (Sara).

One row per Devpost project submitted to a Hack the North hackathon, 2014-2026.
`slug` is the primary key and joins to museum.hackthenorth.com/<slug>.

If a column changes, it changes HERE first and both of us reload.
The app loader accepts this column set and also the nested `sections` dict
used in sample.json, so neither lane blocks the other.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# name -> (pandas dtype, description)
COLUMNS = {
    # --- identity -------------------------------------------------------
    "slug":         ("string", "Devpost slug. PRIMARY KEY. devpost.com/software/<slug>"),
    "year":         ("int16",  "HTN edition the project was submitted to (2014-2026)"),
    "url":          ("string", "Canonical Devpost project URL"),
    "museum_url":   ("string", "museum.hackthenorth.com/<slug> if a finalist, else ''"),

    # --- text -----------------------------------------------------------
    "title":        ("string", "Project name"),
    "tagline":      ("string", "One-line pitch under the title"),
    "description":  ("string", "Full README body text, sections concatenated"),
    "sec_inspiration":     ("string", "Devpost prompt: Inspiration"),
    "sec_what_it_does":    ("string", "Devpost prompt: What it does"),
    "sec_how_built":       ("string", "Devpost prompt: How I/we built it"),
    "sec_challenges":      ("string", "Devpost prompt: Challenges I/we ran into"),
    "sec_accomplishments": ("string", "Devpost prompt: Accomplishments I'm/we're proud of"),
    "sec_learned":         ("string", "Devpost prompt: What I/we learned"),
    "sec_whats_next":      ("string", "Devpost prompt: What's next for X"),

    # --- features -------------------------------------------------------
    "built_with":   ("object", "list[str] of lowercase tech tags"),
    "n_built_with": ("int16",  "len(built_with)"),
    "team_size":    ("int16",  "Number of listed team members (min 1)"),
    "desc_words":   ("int32",  "Whitespace word count of description"),
    "has_video":    ("bool",   "Embedded YouTube/Vimeo iframe present"),
    "has_repo":     ("bool",   "A github.com link appears anywhere on the page"),

    # --- outcome (the labels) -------------------------------------------
    "finalist":     ("bool",   "Top-~12 finalist for its year. THE LABEL."),
    "prizes":       ("object", "list[str] of HTN prize strings won, verbatim"),
    "n_prizes":     ("int16",  "len(prizes)"),
    "label_source": ("string", "'museum+devpost' | 'museum' | 'devpost' | 'none'"),
}

# Years the museum covers, and therefore where `finalist` is trustworthy.
# HTN 2026 is being judged right now: its rows are real but UNLABELLED, which is
# exactly the population a judge's query represents.
LABELLED_YEARS = range(2014, 2026)

SAMPLE_PATH = "data/sample.json"
CORPUS_PATH = "data/corpus.parquet"
DEFAULT_PARQUET = ROOT / CORPUS_PATH
_APP_SAMPLE = ROOT / "sample.json"


def _resolve(p: str | Path) -> Path:
    """Absolute paths win; relative ones hang off the repo root, not the cwd."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else ROOT / p


def corpus_path() -> Path:
    """Where the corpus lives. CORPUS_PATH in .env overrides the default.

    Read lazily on purpose: server.py does `from schema import ROOT` before it
    calls load_dotenv(), so anything resolved at import time would miss the .env.
    """
    return _resolve(os.environ.get("CORPUS_PATH") or CORPUS_PATH)

SECTION_KEYS = (
    ("inspiration", "sec_inspiration"),
    ("what it does", "sec_what_it_does"),
    ("how built", "sec_how_built"),
    ("challenges", "sec_challenges"),
    ("accomplishments", "sec_accomplishments"),
    ("learned", "sec_learned"),
    ("what's next", "sec_whats_next"),
)


def validate(df):
    """Raise if the corpus violates the contract. Called before every ship."""
    problems = []

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        problems.append(f"missing columns: {missing}")
    extra = [c for c in df.columns if c not in COLUMNS]
    if extra:
        problems.append(f"undeclared columns: {extra}")

    if df.slug.duplicated().any():
        dupes = df.slug[df.slug.duplicated()].tolist()[:5]
        problems.append(f"duplicate slugs: {dupes}")
    if df.slug.eq("").any():
        problems.append("empty slugs present")
    if not df.year.between(2014, 2026).all():
        problems.append(f"years out of range: {sorted(set(df.year) - set(range(2014, 2027)))}")
    if df.team_size.lt(1).any():
        problems.append("team_size < 1")

    for y in LABELLED_YEARS:
        n = int(df[df.year == y].finalist.sum())
        if n == 0:
            problems.append(f"{y}: ZERO finalists - the join failed for that year")
        elif not 5 <= n <= 25:
            problems.append(f"{y}: {n} finalists, expected ~12")

    if problems:
        raise AssertionError("corpus contract violated:\n  - " + "\n  - ".join(problems))
    return True


@dataclass
class Project:
    slug: str
    year: int
    title: str
    tagline: str
    description: str
    sections: dict[str, str] = field(default_factory=dict)
    built_with: list[str] = field(default_factory=list)
    team_size: int = 1
    has_video: bool = False
    has_repo: bool = False
    prizes: list[str] = field(default_factory=list)
    finalist: bool = False

    def embed_text(self) -> str:
        desc = (self.description or "")[:4000]
        return f"{self.title}. {self.tagline}. {desc}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "tolist"):
        try:
            return list(value.tolist())
        except Exception:
            pass
    return [value]


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {}


def _sections_from_row(row: dict[str, Any]) -> dict[str, str]:
    sections = _as_dict(row.get("sections"))
    if sections:
        return {str(k): str(v) for k, v in sections.items() if v}
    for label, key in SECTION_KEYS:
        text = row.get(key)
        if text:
            sections[label] = str(text)
    return sections


def project_from_row(row: dict[str, Any]) -> Project:
    """Coerce a parquet/json row into a Project. Unknown fields are ignored;
    missing fields get defaults so a newer corpus never blocks the server.
    """
    return Project(
        slug=str(row.get("slug") or ""),
        year=int(row.get("year") or 0),
        title=str(row.get("title") or ""),
        tagline=str(row.get("tagline") or ""),
        description=str(row.get("description") or ""),
        sections=_sections_from_row(row),
        built_with=[str(x) for x in _as_list(row.get("built_with"))],
        team_size=max(1, int(row.get("team_size") or 1)),
        has_video=_as_bool(row.get("has_video")),
        has_repo=_as_bool(row.get("has_repo")),
        prizes=[str(x) for x in _as_list(row.get("prizes"))],
        finalist=_as_bool(row.get("finalist")),
    )


def load_corpus(path: str | Path | None = None) -> list[Project]:
    """Falls back to sample.json when the parquet isn't there yet."""
    parquet = _resolve(path) if path is not None else corpus_path()
    if parquet.exists():
        import pandas as pd

        df = pd.read_parquet(parquet)
        rows = df.to_dict(orient="records")
        projects = [project_from_row(r) for r in rows if r.get("slug")]
        if projects:
            return projects
    for candidate in (_APP_SAMPLE, ROOT / SAMPLE_PATH):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            return [project_from_row(r) for r in raw]
    raise FileNotFoundError(
        f"No corpus at {parquet} and no sample.json. "
        "Add sample.json or wait for Richa's parquet."
    )


def corpus_source(path: str | Path | None = None) -> str:
    parquet = _resolve(path) if path is not None else corpus_path()
    if parquet.exists():
        return str(parquet)
    if _APP_SAMPLE.exists():
        return str(_APP_SAMPLE)
    return str(ROOT / SAMPLE_PATH)
