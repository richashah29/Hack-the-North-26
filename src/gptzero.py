"""Offline GPTZero enrichment over the corpus.

Run by Richa:

    python src/gptzero.py

Do not import this module from server.py or build.py. It is the only file
that talks to GPTZero, and it writes year-level aggregates only.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schema import load_corpus  # noqa: E402

load_dotenv(ROOT / ".env")

API_URL = "https://api.gptzero.me/v2/predict/text"
CACHE_PATH = ROOT / "data" / "gptzero_cache.json"
FINDINGS_PATH = ROOT / "data" / "findings.json"
PER_YEAR = 100
SEED = 2026
SLEEP = 0.3
MAX_CHARS = 5000

# Set after we see the first live response (or taken from cache).
_FIELD_USED: str | None = None


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def _nodes(payload: object) -> list[dict]:
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out
    docs = payload.get("documents")
    if isinstance(docs, list):
        out.extend(d for d in docs if isinstance(d, dict))
    out.append(payload)
    inner = payload.get("data") or payload.get("result")
    if isinstance(inner, dict):
        out.append(inner)
        docs2 = inner.get("documents")
        if isinstance(docs2, list):
            out.extend(d for d in docs2 if isinstance(d, dict))
    return out


def extract_ai_prob(payload: object) -> tuple[float | None, str]:
    """Prefer class_probabilities.ai, then average_generated_prob."""
    for node in _nodes(payload):
        probs = node.get("class_probabilities") or node.get("classProbabilities")
        if isinstance(probs, dict) and "ai" in probs:
            try:
                return float(probs["ai"]), "class_probabilities.ai"
            except (TypeError, ValueError):
                pass
    for node in _nodes(payload):
        if "average_generated_prob" in node:
            try:
                return float(node["average_generated_prob"]), "average_generated_prob"
            except (TypeError, ValueError):
                pass
    return None, ""


def _predict(client: httpx.Client, key: str, text: str, *, print_raw: bool) -> tuple[float | None, str]:
    r = client.post(
        API_URL,
        headers={"x-api-key": key, "Content-Type": "application/json"},
        json={"document": text[:MAX_CHARS]},
        timeout=30.0,
    )
    if r.status_code == 429:
        time.sleep(2.0)
        r = client.post(
            API_URL,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={"document": text[:MAX_CHARS]},
            timeout=30.0,
        )
    r.raise_for_status()
    payload = r.json()
    if print_raw:
        dumped = json.dumps(payload, indent=2, default=str)
        print("FIRST raw GPTZero response:")
        print(dumped[:4000])
        if len(dumped) > 4000:
            print(f"... truncated, {len(dumped)} chars")
    return extract_ai_prob(payload)


def _claim(years: list[int], probs: list[float]) -> str:
    pre = [p for y, p in zip(years, probs) if y <= 2022]
    post = [p for y, p in zip(years, probs) if y >= 2023]
    if pre and post and (sum(post) / len(post)) > (sum(pre) / len(pre) + 0.05):
        return "Writing shifts toward AI-generated after 2023"
    return "AI-likelihood of project writeups by year"


def _write_findings(years: list[int], probs: list[float], ns: list[int]) -> None:
    findings: dict = {}
    if FINDINGS_PATH.exists():
        try:
            findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            findings = {}
    # Year-level only. Never copy the per-slug cache into this file.
    findings["ai_writing"] = {
        "years": years,
        "ai_prob": probs,
        "n": ns,
        "claim": _claim(years, probs),
        "field": _FIELD_USED,
    }
    FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINDINGS_PATH.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    global _FIELD_USED
    key = (os.getenv("GPTZERO_API_KEY") or "").strip()
    if not key:
        print("Set GPTZERO_API_KEY in .env")
        return 1

    projects = load_corpus()
    by_year: dict[int, list] = defaultdict(list)
    for p in projects:
        if p.year and (p.description or "").strip():
            by_year[int(p.year)].append(p)
    if not by_year:
        print("corpus has no year+description rows")
        return 1

    cache = _load_cache()
    rng = random.Random(SEED)
    years_out: list[int] = []
    probs_out: list[float] = []
    n_out: list[int] = []
    printed_raw = False

    with httpx.Client(follow_redirects=True) as client:
        for year in sorted(by_year):
            pool = by_year[year]
            sample = rng.sample(pool, min(PER_YEAR, len(pool)))
            scores: list[float] = []
            fetched = 0
            for p in sample:
                hit = cache.get(p.slug)
                if isinstance(hit, dict) and isinstance(hit.get("prob"), (int, float)):
                    scores.append(float(hit["prob"]))
                    if _FIELD_USED is None and hit.get("field"):
                        _FIELD_USED = str(hit["field"])
                    continue
                try:
                    prob, field = _predict(
                        client, key, p.description, print_raw=not printed_raw
                    )
                    printed_raw = True
                    time.sleep(SLEEP)
                except Exception as exc:
                    print(f"  skip {year}: {type(exc).__name__}: {str(exc)[:120]}")
                    continue
                if prob is None:
                    print(f"  skip {year}: no AI-likelihood field in response")
                    continue
                if _FIELD_USED is None:
                    _FIELD_USED = field
                    print(f"Using AI-likelihood field: {field}")
                cache[p.slug] = {"prob": prob, "field": field}
                scores.append(prob)
                fetched += 1
            _save_cache(cache)
            if not scores:
                print(f"{year}: 0 scores")
                continue
            mean = sum(scores) / len(scores)
            years_out.append(year)
            probs_out.append(round(mean, 4))
            n_out.append(len(scores))
            print(f"{year}: mean={mean:.3f}  n={len(scores)}  fetched={fetched}")

    if _FIELD_USED:
        print(f"AI-likelihood field used: {_FIELD_USED}")
    else:
        print("AI-likelihood field used: none (no successful responses)")

    if not years_out:
        print("no year aggregates to write")
        return 1

    _write_findings(years_out, probs_out, n_out)
    print(f"wrote year-level ai_writing -> {FINDINGS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
