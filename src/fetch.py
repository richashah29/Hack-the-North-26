"""Cached HTTP fetcher.

Scrape once, parse a hundred times: every URL is written to raw/ keyed by a hash
of the URL, and never re-fetched. A parser bug costs a re-parse, not a re-crawl.
"""
import hashlib
import pathlib
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
RAW.mkdir(exist_ok=True)

HEAD = {"User-Agent": "HTN2026-student-research/1.0 (sarasdragonz@gmail.com)"}

_client = httpx.Client(headers=HEAD, timeout=25, follow_redirects=True)

# Bumped to 1.5 if we start seeing 429s.
DELAY = 0.5


def path_for(url: str) -> pathlib.Path:
    return RAW / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def cached(url: str) -> bool:
    return path_for(url).exists()


def fetch(url: str, delay: float | None = None) -> str:
    """Return page text, from disk if we already have it."""
    key = path_for(url)
    if key.exists():
        return key.read_text(encoding="utf-8")
    r = _client.get(url)
    r.raise_for_status()
    key.write_text(r.text, encoding="utf-8")
    with (RAW / "index.tsv").open("a", encoding="utf-8") as f:
        f.write(f"{key.name}\t{url}\n")
    time.sleep(DELAY if delay is None else delay)
    return r.text


def fetch_ok(url: str, delay: float | None = None):
    """fetch() but returns None on HTTP error instead of raising."""
    try:
        return fetch(url, delay)
    except httpx.HTTPStatusError as e:
        return None if e.response.status_code == 404 else _raise(e)
    except Exception:
        return None


def _raise(e):
    raise e


YEARS = {
    2014: "https://hackthenorth.devpost.com",
    **{y: f"https://hackthenorth{y}.devpost.com" for y in range(2015, 2027)},
}
