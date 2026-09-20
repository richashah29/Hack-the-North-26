"""Every hackathon edition we crawl. Single source of truth.

`event` is the family a judge filters on ("Hack the North"). `event_id` is the
individual edition and is unique. Years come from Devpost's own listed submission
dates, because UofTHacks numbers its editions in roman numerals and you cannot
read the calendar year off the slug.
"""
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Event:
    event_id: str   # "htn-2019", "uofthacks-vi"  -- unique per edition
    event: str      # "Hack the North"            -- the family, what you filter on
    edition: str    # "2019", "VI"                -- display label
    year: int
    base_url: str

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc


def _htn() -> list[Event]:
    out = [Event("htn-2014", "Hack the North", "2014", 2014, "https://hackthenorth.devpost.com")]
    out += [
        Event(f"htn-{y}", "Hack the North", str(y), y, f"https://hackthenorth{y}.devpost.com")
        for y in range(2015, 2027)
    ]
    return out


# UofTHacks 12 (Jan 2025) has no Devpost gallery -- 404. Eight of nine editions.
_UOFTHACKS = [
    ("uofthacks-v",    "V",    2018, "https://uofthacksv.devpost.com"),
    ("uofthacks-vi",   "VI",   2019, "https://uofthacksvi.devpost.com"),
    ("uofthacks-vii",  "VII",  2020, "https://uofthacksvii.devpost.com"),
    ("uofthacks-viii", "VIII", 2021, "https://uofthacksviii.devpost.com"),
    ("uofthacks-ix",   "IX",   2022, "https://uofthacks-ix.devpost.com"),
    ("uofthacks-x",    "X",    2023, "https://uofthacks-x.devpost.com"),
    ("uofthacks-11",   "11",   2024, "https://uofthacks-11.devpost.com"),
    ("uofthacks-13",   "13",   2026, "https://uofthacks-13.devpost.com"),
]

_GENAI = [
    ("genai-genesis-2024", "2024", 2024, "https://genai-genesis-2024.devpost.com"),
    ("genai-genesis-2025", "2025", 2025, "https://genai-genesis-2025.devpost.com"),
    ("genai-genesis-2026", "2026", 2026, "https://genai-genesis-2026.devpost.com"),
]

EVENTS: list[Event] = (
    _htn()
    + [Event(i, "UofTHacks", e, y, u) for i, e, y, u in _UOFTHACKS]
    + [Event(i, "GenAI Genesis", e, y, u) for i, e, y, u in _GENAI]
)

BY_ID = {e.event_id: e for e in EVENTS}
BY_HOST = {e.host: e for e in EVENTS}

# The default corpus is Hack the North alone: that is the demo, and its `finalist`
# label is the museum-verified top ~12 rather than "won any prize".
HTN_IDS = {e.event_id for e in EVENTS if e.event == "Hack the North"}

FAMILIES = ["Hack the North", "UofTHacks", "GenAI Genesis"]


def event_for_host(host: str) -> Event | None:
    """Resolve a Devpost hackathon host back to its edition."""
    return BY_HOST.get(host.lower().strip())
