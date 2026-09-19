"""Step 5: finalist labels from museum.hackthenorth.com, grouped by year.

The museum page is one document with a section per year, so we walk the DOM in
order and attribute each project link to the most recent year heading above it.
"""
import json
import re

from bs4 import BeautifulSoup

from fetch import ROOT, fetch

MUSEUM = "https://museum.hackthenorth.com/"
YEAR_RE = re.compile(r"\b(20(?:1[4-9]|2[0-6]))\b")
NOT_A_PROJECT = {"", "index", "about", "home", "collection"}


def finalists_by_year() -> dict[str, int]:
    """Return {slug: year} for every finalist in the museum."""
    soup = BeautifulSoup(fetch(MUSEUM), "lxml")

    out: dict[str, int] = {}
    current_year = None
    # Walk the document in order: year headings set context for the links below.
    for el in soup.find_all(["h1", "h2", "h3", "h4", "section", "div", "a"]):
        if el.name == "a":
            href = el.get("href", "")
            if href.startswith("http") and "museum.hackthenorth.com" not in href:
                continue
            slug = href.split("?")[0].rstrip("/").split("/")[-1]
            if slug.lower() in NOT_A_PROJECT or "." in slug:
                continue
            # Year-navigation links ("2019") are not projects.
            if YEAR_RE.fullmatch(slug):
                continue
            if current_year and slug not in out:
                out[slug] = current_year
        else:
            text = el.get_text(" ", strip=True)
            # A short heading that is just a year switches the section.
            if len(text) < 40:
                m = YEAR_RE.search(text)
                if m:
                    current_year = int(m.group(1))
    return out


def main():
    fy = finalists_by_year()
    print(f"{len(fy)} finalist slugs")
    by_year: dict[int, int] = {}
    for y in fy.values():
        by_year[y] = by_year.get(y, 0) + 1
    for y in sorted(by_year):
        print(f"  {y}: {by_year[y]}")
    path = ROOT / "data" / "finalists.json"
    path.write_text(json.dumps(fy, indent=1, sort_keys=True))
    print("->", path)


if __name__ == "__main__":
    main()
