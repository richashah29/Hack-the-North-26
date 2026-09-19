"""Pull this year's Devpost prize tracks and rank them against a project."""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from schema import ROOT

CACHE = ROOT / "data" / "tracks_cache.json"
PRIZES_PATH = ROOT / "data" / "prizes.json"


def prizes_file() -> Path:
    raw = (os.getenv("PRIZES_PATH") or "").strip()
    return Path(raw).expanduser() if raw else PRIZES_PATH


HEAD = {"User-Agent": "PriorArt-HTN2026"}
YEAR_HOST = re.compile(r"hackthenorth(\d{4})?\.devpost\.com", re.I)
STOP = set(ENGLISH_STOP_WORDS) | {
    "best",
    "use",
    "hack",
    "north",
    "winner",
    "winners",
    "track",
    "prize",
    "prizes",
    "api",
    "mlh",
    "sponsored",
    "sponsor",
    "challenge",
    "hackathon",
    "project",
    "projects",
    "build",
    "built",
    "using",
    "https",
    "com",
    "www",
}

PROJECT_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    (
        "hardware",
        (
            "hardware",
            "embedded",
            "qnx",
            "robot",
            "firmware",
            "pcb",
            "arduino",
            "raspberry",
            "sensor",
            "sensors",
            "wearable",
            "lidar",
            "bracket bot",
            "lelamp",
            "whiteout",
            "ardupilot",
            "mavlink",
            "rover",
            "quadcopter",
            "microcontroller",
            "esp32",
        ),
    ),
    (
        "blockchain",
        (
            "ethereum",
            "ethglobal",
            "solana",
            "blockchain",
            "web3",
            "solidity",
            "crypto",
            "ledger",
            "ripple",
            "tether",
            "thru",
        ),
    ),
    (
        "ai",
        (
            "openai",
            "llm",
            "llms",
            "groq",
            "cohere",
            "cerebras",
            "gemini",
            "chatgpt",
            "codex",
            "windsurf",
            "devin",
        ),
    ),
    ("voice", ("voice", "vapi", "speech", "voiceflow", "elevenlabs")),
    ("maps", ("mappedin", "indoor mapping", "navigation", "mapping")),
    ("devtools", ("warp", "sentry", "graphite", "codegen", "terraform")),
    ("shopping", ("shopify", "shopping")),
]

# Prize pages reuse MLH boilerplate ("raspberry pi", "agent", …). Title + brand only.
TRACK_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    (
        "hardware",
        (
            "hardware",
            "embedded",
            "qnx",
            "robot",
            "firmware",
            "bracket bot",
            "lelamp",
            "whiteout",
            "ardupilot",
            "spectacles",
            "physical world",
        ),
    ),
    (
        "blockchain",
        (
            "ethereum",
            "ethglobal",
            "solana",
            "blockchain",
            "web3",
            "ripple",
            "tether",
            "thru",
            "ledger",
        ),
    ),
    (
        "ai",
        (
            "openai",
            "groq",
            "cohere",
            "cerebras",
            "gemini",
            "chatgpt",
            "codex",
            "windsurf",
            "devin",
            "databricks",
            "snowflake",
        ),
    ),
    ("voice", ("vapi", "speech", "voiceflow", "elevenlabs")),
    ("maps", ("mappedin", "indoor mapping")),
    ("devtools", ("warp", "sentry", "graphite", "codegen", "terraform")),
    ("shopping", ("shopify", "shopping")),
]

# How strongly the sponsor SDK/API shows up. Code beats README beats the one-liner.
LAYER_WEIGHT = {"code": 1.0, "readme": 0.55, "prompt": 0.3, "absent": 0.0}

# Adjacent stack that makes a missing stream reachable (not a rewrite).
BRIDGE = {
    "hardware": (
        "hardware",
        "firmware",
        "arduino",
        "raspberry",
        "pcb",
        "lidar",
        "sensor",
        "embedded",
        "c++",
        ".ino",
        "esp32",
    ),
    "blockchain": ("solidity", "ethereum", "web3", "solana", "crypto", "web3.js"),
    "ai": ("python", "javascript", "typescript", "pytorch", "openai", "llm", "jupyter"),
    "voice": ("audio", "webrtc", "voice", "speech", "speak", "tts", "elevenlabs"),
    "maps": ("python", "javascript", "opencv", "lidar", "map"),
    "devtools": ("python", "javascript", "typescript", "go", "rust"),
    "shopping": ("shopify", "commerce", "merchant", "cart"),
}

IGNORE_TITLE = (
    "finalist",
    "godaddy",
    "domain name",
    "beginner hack",
    "raffle",
    "hot sauce",
)

GENERIC_NEEDLE = STOP | {
    "hardware",
    "software",
    "system",
    "agent",
    "cloud",
    "labs",
    "lab",
    "computer",
    "human",
    "dynamics",
    "americas",
    "live",
    "challenge",
    "company",
    "award",
    "application",
    "mobile",
    "experience",
    "consumer",
    "payment",
    "garden",
    "shopping",
    "developer",
    "tool",
    "beginner",
    "sovereign",
    "signal",
    "noise",
    "north",
}
BRAND_ALIASES = {
    "sentry": ("sentry", "sentry_sdk", "@sentry"),
    "openai": ("openai", "codex"),
    "qnx": ("qnx",),
    "solana": ("solana",),
    "cerebras": ("cerebras",),
    "cohere": ("cohere",),
    "groq": ("groq",),
    "gemini": ("gemini",),
    "shopify": ("shopify",),
    "warp": ("warp",),
    "databricks": ("databricks",),
    "snowflake": ("snowflake",),
    "mongodb": ("mongodb", "mongo"),
    "auth0": ("auth0",),
    "elevenlabs": ("elevenlabs", "eleven labs"),
    "vapi": ("vapi",),
    "elastic": ("elasticsearch", "elastic"),
    "baseten": ("baseten",),
    "gptzero": ("gptzero",),
    "expo": ("expo", "react native"),
    "cloudflare": ("cloudflare", "workers"),
    "browserbase": ("browserbase",),
    "composio": ("composio",),
    "devin": ("devin",),
    "bracket": ("bracket bot", "bracketbot"),
    "lelamp": ("lelamp",),
    "thru": ("thru",),
    "tether": ("tether", "qvac", "pear"),
    "ardupilot": ("ardupilot", "mavlink", "whiteout"),
}

_WIN_RE = re.compile(
    r"\b(won|winner|winners|awarded|took home|first place|second place|third place)\b",
    re.I,
)
_FINALIST_CLAIM_RE = re.compile(
    r"\b(?:was|were|is|are|named|became)\s+(?:a\s+)?finalists?\b", re.I
)
_PRIZE_SPAN_RE = re.compile(
    r"""
    \bbest\s+use\s+of\s+(?:(?!(?:would|will|that|which|because)\b)[\w][\w+&/'’.-]*\s*){1,6}
    |
    \bbest\s+[\w][\w .&+/'’-]{0,40}?\s*(?:prize|prizes|challenge|track|award|hack|agent|tool|app|experience)\b
    |
    \b[\w][\w .&+/'’-]{1,50}\s+(?:prizes|prize|challenge|tracks|track|awards|award)\b
    """,
    re.I | re.X,
)
_GENERIC_PRIZE_SPANS = {
    "prize",
    "prizes",
    "the prize",
    "a prize",
    "this prize",
    "sponsor prize",
    "sponsor prizes",
    "prize track",
    "prize tracks",
    "sponsor track",
    "sponsor tracks",
    "track",
    "tracks",
    "the track",
    "this track",
    "challenge",
    "the challenge",
    "this challenge",
    "a challenge",
    "award",
    "the award",
    "an award",
    "best",
    "best use",
    "best use of",
    "hack",
    "the hack",
}
_PRIZE_FILLER = {
    "the",
    "a",
    "an",
    "best",
    "use",
    "of",
    "prize",
    "prizes",
    "challenge",
    "track",
    "tracks",
    "award",
    "hack",
    "with",
    "and",
    "for",
    "by",
}


def _norm_prize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load_prize_tracks(path: Path | None = None) -> list[dict[str, str]]:
    """HTN 2026 sponsor tracks. Coach may name only these."""
    src = path or prizes_file()
    if not src.exists():
        return []
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("tracks") or raw.get("prizes") or []
    else:
        rows = []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            name = row.strip()
            sponsor = name.split(":", 1)[0].strip() if ":" in name else ""
            aliases: list[str] = []
        elif isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            sponsor = str(row.get("sponsor") or "").strip()
            raw_aliases = row.get("aliases") or []
            aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
            if not sponsor and ":" in name:
                sponsor = name.split(":", 1)[0].strip()
        else:
            continue
        key = name.lower()
        if not name or key in seen or "finalist" in key:
            continue
        seen.add(key)
        out.append({"name": name, "sponsor": sponsor, "aliases": aliases})
    return out


def prize_prompt_names(tracks: list[dict[str, str]] | None = None) -> list[str]:
    tracks = tracks if tracks is not None else load_prize_tracks()
    return [t["name"] for t in tracks if t.get("name")]


def _allowed_prize_index(
    tracks: list[dict[str, str]],
) -> tuple[list[str], set[str]]:
    names: list[str] = []
    sponsors: set[str] = set()
    skip_parts = {
        "computer",
        "human",
        "labs",
        "lab",
        "company",
        "dynamics",
        "americas",
        "data",
        "live",
        "best",
        "use",
        "north",
    }
    for t in tracks:
        name = _norm_prize(t.get("name") or "")
        if name:
            names.append(name)
        sponsor = _norm_prize(t.get("sponsor") or "")
        if len(sponsor) >= 3:
            sponsors.add(sponsor)
            for part in sponsor.split():
                if len(part) >= 4 and part not in skip_parts:
                    sponsors.add(part)
        for alias in t.get("aliases") or []:
            a = _norm_prize(str(alias))
            if len(a) >= 3:
                names.append(a)
                if len(a.split()) == 1:
                    sponsors.add(a)
        m = re.search(r"best use of .+", t.get("name") or "", re.I)
        if m:
            names.append(_norm_prize(m.group(0)))
    names = sorted({n for n in names if n}, key=len, reverse=True)
    return names, sponsors


def _span_is_allowed(span: str, names: list[str], sponsors: set[str]) -> bool:
    n = _norm_prize(span)
    if not n or n in _GENERIC_PRIZE_SPANS:
        return True
    for a in names:
        if len(a) >= 8 and (a in n or n in a):
            return True
        if 4 <= len(a) < 8 and a == n:
            return True
    tokens = [tok for tok in n.split() if tok not in _PRIZE_FILLER]
    for tok in tokens:
        if tok in sponsors:
            return True
    joined = " ".join(tokens)
    for s in sponsors:
        if " " in s and s in n:
            return True
        if len(s) >= 4 and joined == s:
            return True
    return False


def _historical_prize_phrases(projects, names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in projects or []:
        for prize in getattr(p, "prizes", None) or []:
            if "finalist" in str(prize).lower():
                continue
            n = _norm_prize(str(prize))
            if n in seen:
                continue
            if len(n) < 12 and not re.search(r"\b(best|prize|challenge|award)\b", n):
                continue
            if any(len(a) >= 8 and (a in n or n in a) for a in names):
                continue
            seen.add(n)
            out.append(n)
    return out


def coach_move_violation(
    text: str,
    tracks: list[dict[str, str]] | None = None,
    projects=None,
) -> str | None:
    """Why a coach move should be dropped, or None if it is clean."""
    blob = text or ""
    if _WIN_RE.search(blob):
        return "claimed a win"
    tracks = tracks if tracks is not None else load_prize_tracks()
    names, sponsors = _allowed_prize_index(tracks)
    for m in _PRIZE_SPAN_RE.finditer(blob):
        span = m.group(0)
        if not _span_is_allowed(span, names, sponsors):
            return f"unnamed prize {span!r}"
    hist = _historical_prize_phrases(projects, names)
    norm_blob = _norm_prize(blob)
    for phrase in hist:
        if phrase and phrase in norm_blob:
            return f"historical prize {phrase!r}"
    if _FINALIST_CLAIM_RE.search(blob) and projects:
        low = blob.lower()
        ranked = sorted(
            (p for p in projects if (p.title or "") and len(p.title) >= 5),
            key=lambda p: len(p.title),
            reverse=True,
        )
        for p in ranked:
            title = p.title.lower()
            if title in low and not p.finalist:
                return f"non-finalist {p.title!r} called finalist"
    return None


def filter_coach_moves(
    specs: list[dict[str, Any]],
    tracks: list[dict[str, str]] | None = None,
    projects=None,
) -> list[dict[str, Any]]:
    tracks = tracks if tracks is not None else load_prize_tracks()
    kept: list[dict[str, Any]] = []
    for spec in specs:
        blob = " ".join(
            str(spec.get(k) or "")
            for k in ("label", "rationale", "reframed_description")
        )
        reason = coach_move_violation(blob, tracks=tracks, projects=projects)
        if reason:
            print(f"coach dropped move ({reason}): {spec.get('label')}")
            continue
        kept.append(spec)
    return kept


def parse_hackathon_url(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"20\d{2}", text):
        y = int(text)
        return "https://hackthenorth.devpost.com" if y == 2014 else f"https://hackthenorth{y}.devpost.com"
    m = YEAR_HOST.search(text)
    if m:
        return f"https://{m.group(0).lower()}"
    if "devpost.com" in text.lower():
        m2 = re.search(r"https?://[^\s]+devpost\.com[^\s]*", text, re.I)
        if m2:
            return m2.group(0).rstrip("/").split("?")[0]
    return None


def _load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")


def parse_prizes_html(page: str) -> list[dict[str, str]]:
    starts = list(re.finditer(r'<div[^>]*id="prize_\d+"[^>]*>', page))
    if not starts:
        starts = list(re.finditer(r'<div class="[^"]*\bend prize\b[^"]*"', page))
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else min(len(page), m.start() + 12000)
        chunk = page[m.start() : end]
        tm = re.search(r'class="prize-title".*?<div>\s*([^<]+)', chunk, re.S)
        if not tm:
            tm = re.search(r'class="prize-title"[^>]*>\s*([^<]+)', chunk)
        if not tm:
            continue
        name = html_lib.unescape(tm.group(1)).strip()
        if not name or name.lower() in seen:
            continue
        paras = re.findall(r"<p>(.*?)</p>", chunk, re.S)
        desc = " ".join(html_lib.unescape(re.sub("<[^>]+>", " ", p)) for p in paras)
        desc = re.sub(r"\s+", " ", desc).strip()
        seen.add(name.lower())
        out.append({"name": name, "description": desc[:1400]})
    return out


def fetch_tracks(url: str, timeout: float = 12.0) -> dict[str, Any]:
    parsed = parse_hackathon_url(url)
    if not parsed:
        return {"ok": False, "error": "not a Devpost hackathon URL (try hackthenorth2026.devpost.com)", "tracks": []}
    cache = _load_cache()
    if parsed in cache and cache[parsed].get("tracks"):
        return {"ok": True, "url": parsed, "tracks": cache[parsed]["tracks"], "error": None, "cached": True}
    try:
        r = httpx.get(parsed, headers=HEAD, follow_redirects=True, timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "error": f"Devpost returned {r.status_code}", "tracks": []}
        tracks = parse_prizes_html(r.text)
        if not tracks:
            return {"ok": False, "error": "no prize tracks found on that page", "tracks": []}
        cache[parsed] = {"tracks": tracks}
        _save_cache(cache)
        return {"ok": True, "url": parsed, "tracks": tracks, "error": None, "cached": False}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "tracks": []}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP and len(w) > 3}


def categorize(text: str, *, for_track: bool = False) -> set[str]:
    blob = (text or "").lower()
    source = TRACK_CATEGORIES if for_track else PROJECT_CATEGORIES
    hits = set()
    for name, needles in source:
        if any(n in blob for n in needles):
            hits.add(name)
    return hits


def _prize_overlap(track_name: str, prize: str) -> float:
    a, b = _tokens(track_name), _tokens(prize)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _project_blob(p) -> str:
    tags = " ".join(p.built_with or [])
    prizes = " ".join(p.prizes or [])
    return f"{p.title} {p.tagline} {p.description} {tags} {prizes}"


def past_winners(track: dict[str, str] | str, projects, k: int = 3) -> list[dict[str, Any]]:
    if isinstance(track, str):
        name, desc = track, ""
    else:
        name, desc = track.get("name") or "", track.get("description") or ""
    cats = categorize(f"{name} {desc}", for_track=True)
    scored: list[tuple[float, Any, str]] = []
    for p in projects:
        blob = _project_blob(p)
        best = 0.0
        best_prize = ""
        for prize in p.prizes or []:
            if "finalist" in prize.lower():
                continue
            ov = _prize_overlap(name, prize)
            if cats & categorize(prize):
                ov = max(ov, 0.55)
            if ov > best:
                best, best_prize = ov, prize
        if best < 0.34 and "hardware" in cats and "hardware" in categorize(blob) and p.finalist:
            best = 0.36
            best_prize = "hardware-shaped finalist"
        if best >= 0.34:
            scored.append((best, p, best_prize))
    scored.sort(key=lambda t: (-t[0], -int(t[1].finalist), -t[1].year))
    out = []
    for ov, p, prize in scored[:k]:
        out.append(
            {
                "title": p.title,
                "year": p.year,
                "prize": prize,
                "finalist": p.finalist,
                "tagline": p.tagline,
            }
        )
    return out


def _won_family(project, family: str) -> bool:
    for prize in project.prizes or []:
        if "finalist" in prize.lower():
            continue
        if family in categorize(prize):
            return True
        low = prize.lower()
        if family == "hardware" and "hardware" in low:
            return True
        if family == "blockchain" and any(x in low for x in ("blockchain", "crypto", "eth", "solana")):
            return True
        if family == "ai" and any(x in low for x in ("mlh", "ai ", " llm", "openai")):
            return True
    return False


def family_prize_rate(projects, family: str | None) -> tuple[float, int, int]:
    """P(won a non-finalist prize in this family | project is family-shaped).

    The corpus records winners, not who submitted and lost, so this is likeness
    to historical winners — not P(win | submit to track).
    """
    n = max(1, len(projects))
    if family:
        shaped = [p for p in projects if family in categorize(_project_blob(p))]
        if len(shaped) >= 3:
            wins = sum(1 for p in shaped if _won_family(p, family))
            rate = wins / len(shaped)
            if rate > 0:
                return rate, wins, len(shaped)
    wins = sum(
        1
        for p in projects
        if any("finalist" not in (pr or "").lower() for pr in (p.prizes or []) if pr)
    )
    return wins / n, wins, n


def _evidence_layers(prompt: str, repo: dict[str, Any] | None) -> dict[str, str]:
    prompt_l = (prompt or "").lower()
    readme = ""
    code = ""
    if repo and repo.get("ok"):
        readme = f"{repo.get('readme') or ''} {repo.get('description') or ''}".lower()
        code = " ".join(repo.get("files") or []).lower()
        code += " " + " ".join(repo.get("languages") or []).lower()
        code += " " + " ".join(repo.get("topics") or []).lower()
    return {"prompt": prompt_l, "readme": readme, "code": code}


def _layer_for(needles: list[str], layers: dict[str, str]) -> str:
    for layer in ("code", "readme", "prompt"):
        blob = layers.get(layer) or ""
        if any(n and n in blob for n in needles):
            return layer
    return "absent"


def _sponsor_needles(name: str, desc: str) -> tuple[str, list[str]]:
    needles: list[str] = []
    brand = ""
    if ":" in name:
        left = name.split(":", 1)[0].strip()
        if left.lower() not in {"mlh", "hack the north"}:
            brand = left
            needles.append(left.lower())
            needles.extend(sorted(_tokens(left)))
    m = re.search(r"best use of ([a-z0-9 .+-]+)", name, re.I)
    if m:
        chunk = m.group(1).strip()
        if not brand:
            brand = chunk
        needles.append(chunk.lower())
        needles.extend(sorted(_tokens(chunk)))
    blob = f"{name} {desc}".lower()
    for canon, aliases in BRAND_ALIASES.items():
        if any(a in blob for a in aliases) or canon in blob:
            needles.extend(aliases)
            if not brand:
                brand = canon
    out: list[str] = []
    seen: set[str] = set()
    for n in needles:
        n = (n or "").strip().lower()
        if len(n) < 3 or n in GENERIC_NEEDLE or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return brand, out[:10]


def _hard_requirements(desc: str) -> list[str]:
    found = []
    for pat in (
        r"Hard requirements?:\s*(.+?)(?:Judging|Prizes|$)",
        r"Your project must ([^.]{12,160})",
        r"must use ([^.]{6,80})",
        r"To qualify[^.]*must ([^.]{12,160})",
    ):
        m = re.search(pat, desc or "", re.I | re.S)
        if not m:
            continue
        text = re.sub(r"\s+", " ", (m.group(1) if m.lastindex else m.group(0))).strip(" -:.")
        if text and text not in found:
            found.append(text[:180])
    return found[:2]


def _potential(track_cats: set[str], proj_cats: set[str], layers: dict[str, str], repo: dict | None) -> float:
    if proj_cats & track_cats:
        return 0.88
    blob = " ".join(layers.values())
    hits = 0
    n = 0
    for cat in track_cats or set():
        needles = BRIDGE.get(cat, ())
        if not needles:
            continue
        n += 1
        if any(x in blob for x in needles):
            hits += 1
    if n and hits:
        return 0.55 + 0.28 * (hits / n)
    if repo and repo.get("ok") and track_cats & {"devtools", "ai"}:
        return 0.62
    if not track_cats:
        return 0.42
    return 0.22


def _action(layer: str, potential: float) -> str:
    if layer == "code":
        return "defend"
    if layer in {"readme", "prompt"}:
        return "strengthen"
    if potential >= 0.55:
        return "add"
    return "skip"


def _track_probs(
    base: float, layer: str, potential: float, neighbour: bool, reachable: bool = True
) -> tuple[float, float]:
    evidence = LAYER_WEIGHT[layer]
    now = base * (0.14 + 0.86 * evidence) * (0.40 + 0.60 * potential)
    pot_if = max(potential, 0.72) if reachable else potential
    iff = base * 1.0 * (0.40 + 0.60 * pot_if)
    if neighbour:
        now *= 1.07
        iff *= 1.07
    return round(min(0.40, max(0.01, now)), 4), round(min(0.45, max(0.02, iff)), 4)


def _moves(action: str, brand: str, layer: str, track: dict, past: list, hard: list[str]) -> list[str]:
    label = brand or track["name"].split(":")[0]
    out: list[str] = []
    if action == "add":
        out.append(f"Not in the repo. Add a working {label} path — this is a new stream, not a polish.")
        if hard:
            out.append(hard[0])
        if past:
            w = past[0]
            out.append(
                f"{w['title']} ({w['year']}) won {w['prize']} in this family. Same shape; the current stream is {label}."
            )
    elif action == "strengthen":
        out.append(f"{label} only appears in the {layer}. Put the SDK in a committed file judges can grep.")
        out.append("Demo that path in three README steps so it is not a throwaway mention.")
        if hard:
            out.append(hard[0])
    else:
        out.append(f"{label} is already in code. Make that path the live demo, not a side file.")
        desc = (track.get("description") or "").lower()
        if "beyond" in desc or "two products" in desc or "meaningfully" in desc:
            out.append("The brief wants depth beyond installing the SDK.")
    return out[:3]


def advise_tracks(
    document: str,
    tracks: list[dict[str, str]],
    projects,
    k: int = 12,
    neighbour_slugs: list[str] | None = None,
    repo: dict[str, Any] | None = None,
    prompt: str = "",
    signals: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per sponsor track: current probability, counterfactual if you ship the SDK, and add vs strengthen.

    Action rule (the stream is the sponsor track, not the category):
      code evidence     → defend (already a stream; deepen the demo)
      readme/prompt     → strengthen (used weakly)
      absent + reachable stack → add (new stream)
      absent + no stack → skip
    Probability is family winner-rate × how real the integration is. It is not
    the 12-finalist number and not P(win | submitted) — we only have winners.
    """
    if not tracks:
        return []
    useful = [t for t in tracks if not any(bad in t["name"].lower() for bad in IGNORE_TITLE)]
    if not useful:
        useful = [t for t in tracks if "finalist" not in t["name"].lower()]
    prompt_text = prompt or (document or "")[:800]
    layers = _evidence_layers(prompt_text, repo)
    layers["prompt"] = (layers["prompt"] + " " + (document or "")[:1500]).lower()
    if signals and signals.get("tags"):
        layers["prompt"] += " " + " ".join(str(t).lower() for t in signals["tags"])
    if signals and signals.get("hardware"):
        layers["prompt"] += " hardware firmware sensors"
    proj_cats = categorize(document or prompt_text)
    if signals and signals.get("hardware"):
        proj_cats.add("hardware")
    by_slug = {p.slug: p for p in projects}
    ranked: list[dict[str, Any]] = []
    for t in useful:
        blob = f"{t['name']} {t.get('description') or ''}"
        title_cats = categorize(t["name"], for_track=True)
        track_cats = title_cats | categorize(blob, for_track=True)
        overlap_cats = title_cats if title_cats else track_cats
        brand, needles = _sponsor_needles(t["name"], t.get("description") or "")
        if not needles:
            needles = sorted(_tokens(t["name"]))[:6]
        layer = _layer_for(needles, layers)
        potential = _potential(track_cats, proj_cats, layers, repo)
        action = _action(layer, potential)
        family = next(iter(track_cats), None)
        base, wins, n_fam = family_prize_rate(projects, family)
        neighbour = False
        past = past_winners(t, projects) if (proj_cats & track_cats or action != "skip") else []
        for slug in (neighbour_slugs or [])[:5]:
            p = by_slug.get(slug)
            if not p:
                continue
            if track_cats & categorize(_project_blob(p)):
                neighbour = True
                break
            if any(_prize_overlap(t["name"], pr) >= 0.34 for pr in (p.prizes or []) if "finalist" not in pr.lower()):
                neighbour = True
                break
        p_now, p_if = _track_probs(base, layer, potential, neighbour, reachable=action != "skip")
        if action == "skip" and p_if < 0.08:
            continue
        hard = _hard_requirements(t.get("description") or "")
        moves = _moves(action, brand, layer, t, past if action != "skip" else [], hard)
        why = [
            f"{action}: {layer} evidence"
            + (f" · family rate {base:.0%} ({wins}/{n_fam})" if n_fam else ""),
        ]
        if neighbour:
            why.append("nearest neighbour sat in this prize family")
        ranked.append(
            {
                "name": t["name"],
                "brand": brand,
                "fit": p_if,
                "p_now": p_now,
                "p_if": p_if,
                "action": action,
                "layer": layer,
                "potential": round(potential, 3),
                "family": family,
                "family_rate": round(base, 3),
                "category": sorted(track_cats),
                "title_cats": sorted(overlap_cats),
                "blurb": (t.get("description") or "")[:220],
                "past": past if action != "skip" else [],
                "moves": moves,
                "why": why,
                "needles": needles[:6],
            }
        )
    ranked.sort(key=lambda row: (0 if row["action"] != "skip" else 1, -row["p_if"], -row["p_now"]))
    defend = [row for row in ranked if row["action"] == "defend"]
    strengthen = [row for row in ranked if row["action"] == "strengthen"]
    add = [row for row in ranked if row["action"] == "add" and row["potential"] >= 0.7]
    add.sort(
        key=lambda r: (
            -len(set(r.get("title_cats") or r.get("category") or []) & proj_cats),
            -r["p_if"],
        )
    )
    primary = [r for r in add if set(r.get("title_cats") or []) & proj_cats]
    secondary = [r for r in add if r not in primary]
    add = (primary[:4] + secondary[:2])[:5]
    picked = defend + strengthen[:4] + add[:5]
    picked.sort(
        key=lambda row: (
            {"defend": 0, "strengthen": 1, "add": 2}.get(row["action"], 9),
            -len(set(row.get("title_cats") or row.get("category") or []) & proj_cats),
            -row["p_if"],
        )
    )
    for row in picked[:k]:
        row.pop("title_cats", None)
        row.pop("needles", None)
    return picked[:k]


def rank_tracks(
    document: str,
    tracks: list[dict[str, str]],
    projects,
    k: int = 6,
    neighbour_slugs: list[str] | None = None,
    repo: dict[str, Any] | None = None,
    prompt: str = "",
    signals: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return advise_tracks(
        document,
        tracks,
        projects,
        k=k,
        neighbour_slugs=neighbour_slugs,
        repo=repo,
        prompt=prompt,
        signals=signals,
    )
