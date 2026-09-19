"""Shared project record. Agreed with Richa before either lane writes more.

If you need a field this file does not have, add it here, push, and tell Richa —
then keep working with a default. Never block on her.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SAMPLE_PATH = ROOT / "sample.json"
DEFAULT_PARQUET = ROOT / "data" / "corpus.parquet"

FIELDS = (
    "slug",
    "year",
    "title",
    "tagline",
    "description",
    "sections",
    "built_with",
    "team_size",
    "has_video",
    "has_repo",
    "prizes",
    "finalist",
)


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
        sections=_as_dict(row.get("sections")),
        built_with=[str(x) for x in _as_list(row.get("built_with"))],
        team_size=max(1, int(row.get("team_size") or 1)),
        has_video=_as_bool(row.get("has_video")),
        has_repo=_as_bool(row.get("has_repo")),
        prizes=[str(x) for x in _as_list(row.get("prizes"))],
        finalist=_as_bool(row.get("finalist")),
    )


def load_corpus(path: str | Path = DEFAULT_PARQUET) -> list[Project]:
    """Falls back to sample.json when the parquet isn't there yet."""
    parquet = Path(path)
    if parquet.exists():
        import pandas as pd

        df = pd.read_parquet(parquet)
        rows = df.to_dict(orient="records")
        projects = [project_from_row(r) for r in rows if r.get("slug")]
        if projects:
            return projects
    if not SAMPLE_PATH.exists():
        raise FileNotFoundError(
            f"No corpus at {parquet} and no {SAMPLE_PATH}. "
            "Add sample.json or wait for Richa's parquet."
        )
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return [project_from_row(r) for r in raw]


def corpus_source(path: str | Path = DEFAULT_PARQUET) -> str:
    parquet = Path(path)
    if parquet.exists():
        return str(parquet)
    return str(SAMPLE_PATH)
