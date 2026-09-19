"""Elasticsearch hybrid neighbour retrieval (BM25 + dense knn, manual RRF).

Optional. engine.py falls back to in-memory cosine if this is unconfigured
or throws. build.py skips indexing the same way. Never import this from a
request path except inside es_neighbours()'s try/except.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

INDEX = "projects"
DIMS = 1536
RRF_K = 60
FETCH = 20


def es_configured() -> bool:
    return bool((os.getenv("ES_URL") or "").strip())


def rrf_fuse(*ranked_lists: Iterable[str], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. rank is 1-based. Works on any license."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, slug in enumerate(ranked, start=1):
            if not slug:
                continue
            scores[slug] = scores.get(slug, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _client(*, request_timeout: float = 8.0):
    url = (os.getenv("ES_URL") or "").strip()
    if not url:
        raise RuntimeError("ES_URL unset")
    from elasticsearch import Elasticsearch

    kwargs: dict[str, Any] = {"request_timeout": request_timeout, "retry_on_timeout": False}
    key = (os.getenv("ES_API_KEY") or "").strip()
    if key:
        kwargs["api_key"] = key
    if url.startswith("http://") or url.startswith("https://"):
        return Elasticsearch(url, **kwargs)
    return Elasticsearch(cloud_id=url, **kwargs)


def _as_vector(query_embedding) -> list[float]:
    import numpy as np

    vec = np.asarray(query_embedding, dtype=float).ravel()
    if vec.size != DIMS:
        raise RuntimeError(f"query embedding dim {vec.size} != {DIMS}")
    return [float(x) for x in vec]


def _hit_slug(hit: dict[str, Any]) -> str:
    src = hit.get("_source") or {}
    return str(src.get("slug") or hit.get("_id") or "")


def _search_bm25(client, query_text: str, size: int) -> list[str]:
    text = (query_text or "").strip()
    if not text:
        return []
    resp = client.search(
        index=INDEX,
        query={
            "bool": {
                "should": [
                    {"match": {"title": text}},
                    {"match": {"tagline": text}},
                    {"match": {"description": text}},
                ]
            }
        },
        size=size,
        source=["slug"],
        request_timeout=2.5,
    )
    return [_hit_slug(h) for h in resp["hits"]["hits"] if _hit_slug(h)]


def _search_knn(client, query_vector: list[float], size: int) -> list[str]:
    resp = client.search(
        index=INDEX,
        knn={
            "field": "embedding",
            "query_vector": query_vector,
            "k": size,
            "num_candidates": max(100, size * 4),
        },
        size=size,
        source=["slug"],
        request_timeout=2.5,
    )
    return [_hit_slug(h) for h in resp["hits"]["hits"] if _hit_slug(h)]


def hybrid_neighbours(query_embedding, query_text: str, k: int = 5) -> list[tuple[str, float]]:
    """BM25 + knn, fused with manual RRF. Raises if ES is down or unconfigured."""
    if not es_configured():
        raise RuntimeError("ES_URL unset")
    query_vector = _as_vector(query_embedding)
    client = _client(request_timeout=2.5)
    fetch = max(FETCH, k)
    bm25 = _search_bm25(client, query_text, fetch)
    knn = _search_knn(client, query_vector, fetch)
    if not knn and not bm25:
        raise RuntimeError("Elasticsearch returned no neighbours")
    fused = rrf_fuse(knn, bm25)
    top = fused[:k]
    if not top:
        raise RuntimeError("RRF produced no neighbours")
    return top


def index_projects(projects, embeddings) -> int:
    """Create `projects` and bulk-index. Returns docs written. Raises on failure.

    Callers (build.py) must wrap this in try/except so a missing cluster
    never blocks map.json / model.pkl.
    """
    if not es_configured():
        print("Elasticsearch skipped: ES_URL unset")
        return 0
    import numpy as np

    arr = np.asarray(embeddings)
    if arr.ndim != 2 or arr.shape[0] != len(projects):
        raise RuntimeError(
            f"embeddings shape {getattr(arr, 'shape', None)} != corpus {len(projects)}"
        )
    if arr.shape[1] != DIMS:
        print(f"Elasticsearch skipped: embedding dim {arr.shape[1]} != {DIMS} (need text-embedding-3-small)")
        return 0

    from elasticsearch.helpers import bulk

    client = _client(request_timeout=30.0)
    info = client.info()
    print(f"Elasticsearch cluster {info.get('cluster_name', '?')} — indexing {len(projects)} projects")

    if client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    client.indices.create(
        index=INDEX,
        mappings={
            "properties": {
                "slug": {"type": "keyword"},
                "title": {"type": "text"},
                "tagline": {"type": "text"},
                "description": {"type": "text"},
                "year": {"type": "integer"},
                "finalist": {"type": "boolean"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": DIMS,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    )

    def actions():
        for i, p in enumerate(projects):
            yield {
                "_index": INDEX,
                "_id": p.slug,
                "_source": {
                    "slug": p.slug,
                    "title": p.title or "",
                    "tagline": p.tagline or "",
                    "description": (p.description or "")[:20000],
                    "year": int(p.year or 0),
                    "finalist": bool(p.finalist),
                    "embedding": [float(x) for x in arr[i]],
                },
            }

    ok, errors = bulk(client, actions(), chunk_size=100, raise_on_error=False)
    client.indices.refresh(index=INDEX)
    if errors:
        print(f"Elasticsearch bulk had {len(errors)} errors (first: {errors[0]})")
    print(f"Elasticsearch indexed {ok} docs into '{INDEX}'")
    return int(ok)
