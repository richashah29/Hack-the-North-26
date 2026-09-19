"""Step 4: parse cached project HTML into corpus rows."""
import re

from bs4 import BeautifulSoup

# Devpost's README template, in I/we variants. Map a heading onto a stable key.
SECTION_KEYS = [
    ("sec_inspiration",     ("inspiration",)),
    ("sec_what_it_does",    ("what it does", "what it do")),
    ("sec_how_built",       ("how i built", "how we built", "how it's built", "how its built")),
    ("sec_challenges",      ("challenge",)),
    ("sec_accomplishments", ("accomplishment",)),
    ("sec_learned",         ("what i learned", "what we learned", "what i've learned", "what we've learned")),
    ("sec_whats_next",      ("what's next", "whats next", "what is next")),
]

HTN_HOST = re.compile(r"hackthenorth(\d{4})?\.devpost\.com")


def _section_key(heading: str):
    h = heading.lower().strip()
    for key, needles in SECTION_KEYS:
        if any(n in h for n in needles):
            return key
    return None


def _submissions(soup):
    """Return (htn_year, htn_prizes, all_prizes) from the 'Submitted to' block."""
    htn_year, htn_prizes, all_prizes = None, [], []
    for block in soup.select("#submissions .software-list-content"):
        link = block.select_one("p a[href]")
        href = link.get("href", "") if link else ""
        m = HTN_HOST.search(href)
        prizes = []
        for li in block.select("ul.no-bullet li"):
            # The <li> is "<span class=winner>Winner</span> <prize name>"
            span = li.select_one("span.winner")
            if span:
                span.extract()
            name = li.get_text(" ", strip=True)
            if name:
                prizes.append(name)
        all_prizes += prizes
        if m:
            # hackthenorth.devpost.com (no digits) is the 2014 edition.
            htn_year = int(m.group(1)) if m.group(1) else 2014
            htn_prizes += prizes
    return htn_year, htn_prizes, all_prizes


def parse(html: str, slug: str, gallery_year: int) -> dict:
    s = BeautifulSoup(html, "lxml")

    def txt(sel):
        el = s.select_one(sel)
        return el.get_text(" ", strip=True) if el else ""

    # Everything read off the whole page must be read BEFORE the cleanup below,
    # which removes those nodes from the tree: the tag list, the video embed in
    # #gallery and the repo link in nav.app-links all live in what we strip.
    built = [li.get_text(strip=True).lower() for li in s.select("#built-with li")]
    built = [b for b in built if b]
    team = s.select(".software-team-member") or s.select("#app-team li")
    hrefs = [a.get("href") or "" for a in s.select("a")]
    has_video = bool(s.select_one('iframe[src*="youtube"], iframe[src*="vimeo"]'))
    htn_year, htn_prizes, _ = _submissions(s)

    body_el = s.select_one("#app-details-left")
    if body_el:
        # Drop the media strip, the tag list and the link nav. They are not prose:
        # left in, they inflate word counts and make any two projects sharing a
        # stack look textually similar for the wrong reason.
        for junk in body_el.select("#gallery, #built-with, nav.app-links"):
            junk.decompose()
    description = body_el.get_text("\n", strip=True) if body_el else ""

    sections = {key: "" for key, _ in SECTION_KEYS}
    if body_el:
        cur = None
        for node in body_el.find_all(["h1", "h2", "h3", "p", "li"]):
            if node.name in ("h1", "h2", "h3"):
                cur = _section_key(node.get_text(" ", strip=True))
            elif cur:
                sections[cur] += node.get_text(" ", strip=True) + "\n"
    sections = {k: v.strip() for k, v in sections.items()}

    return {
        "slug": slug,
        "year": htn_year or gallery_year,
        "url": f"https://devpost.com/software/{slug}",
        "title": txt("#app-title") or txt("h1"),
        "tagline": txt("#software-header p.large") or txt("p.large"),
        "description": description,
        **sections,
        "built_with": built,
        "n_built_with": len(built),
        "team_size": max(1, len(team)),
        "desc_words": len(description.split()),
        "has_video": has_video,
        "has_repo": any("github.com" in h for h in hrefs),
        "prizes": htn_prizes,
        "n_prizes": len(htn_prizes),
        # Devpost's own view of finalist status; reconciled with the museum in build.py
        "_finalist_devpost": any("finalist" in p.lower() for p in htn_prizes),
        "_gallery_year": gallery_year,
    }
