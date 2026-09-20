"""Fetch a public GitHub repo so /api/ask can embed README + stack, not just a one-liner."""

from __future__ import annotations

import base64
import os
import re
from typing import Any

import httpx

REPO_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$",
    re.IGNORECASE,
)

HARDWARE_MARKERS = (
    ".ino",
    "platformio",
    "kicad",
    "firmware",
    "arduino",
    "stm32",
    "esp32",
    "esp8266",
    "raspberry",
    "rpi",
    ".brd",
    ".sch",
    "pcb",
    "hardware",
)


def parse_github_url(url: str) -> tuple[str, str] | None:
    text = (url or "").strip()
    if not text:
        return None
    m = REPO_RE.search(text.split()[0].rstrip("/"))
    if not m:
        return None
    repo = m.group("repo")
    if repo.lower() in {"issues", "pulls", "actions", "settings"}:
        return None
    return m.group("owner"), repo


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "WinTheNorth-HTN2026",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(client: httpx.Client, url: str) -> dict | list | None:
    try:
        r = client.get(url)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def fetch_repo(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """Public metadata only. On any failure return {ok: False} — never raise."""
    parsed = parse_github_url(url)
    if not parsed:
        return {"ok": False, "error": "not a github.com/owner/repo URL"}
    owner, repo = parsed
    try:
        with httpx.Client(headers=_headers(), timeout=timeout, follow_redirects=True) as client:
            meta = _get(client, f"https://api.github.com/repos/{owner}/{repo}")
            if not isinstance(meta, dict):
                return {"ok": False, "error": f"could not read {owner}/{repo} (private or missing)"}

            readme_text = ""
            readme = _get(client, f"https://api.github.com/repos/{owner}/{repo}/readme")
            if isinstance(readme, dict) and readme.get("content"):
                try:
                    readme_text = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
                except Exception:
                    readme_text = ""

            languages = _get(client, f"https://api.github.com/repos/{owner}/{repo}/languages")
            lang_names = list(languages.keys()) if isinstance(languages, dict) else []

            branch = meta.get("default_branch") or "main"
            tree = _get(
                client,
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
            )
            files: list[str] = []
            if isinstance(tree, dict):
                for item in (tree.get("tree") or [])[:250]:
                    if item.get("type") == "blob" and item.get("path"):
                        files.append(str(item["path"]))

            blob = " ".join(files).lower() + " " + readme_text.lower()
            hardware = any(m in blob for m in HARDWARE_MARKERS)

            return {
                "ok": True,
                "full_name": f"{owner}/{repo}",
                "description": (meta.get("description") or "")[:400],
                "languages": lang_names[:12],
                "topics": list(meta.get("topics") or [])[:12],
                "readme": readme_text[:4500],
                "files": files[:80],
                "hardware": hardware,
                "error": None,
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def compose_embed_text(prompt: str, repo: dict[str, Any] | None) -> str:
    parts: list[str] = []
    prompt = (prompt or "").strip()
    if prompt:
        parts.append(prompt)
    if repo and repo.get("ok"):
        parts.append(f"GitHub {repo['full_name']}. {repo.get('description') or ''}".strip())
        langs = repo.get("languages") or []
        if langs:
            parts.append("Tech stack: " + ", ".join(langs))
        topics = repo.get("topics") or []
        if topics:
            parts.append("Topics: " + ", ".join(topics))
        if repo.get("hardware"):
            parts.append("This is a hardware or firmware project.")
        files = repo.get("files") or []
        if files:
            parts.append("Repository files: " + ", ".join(files[:60]))
        readme = (repo.get("readme") or "").strip()
        if readme:
            parts.append("README:\n" + readme)
    text = "\n\n".join(parts).strip()
    return text[:8000]
