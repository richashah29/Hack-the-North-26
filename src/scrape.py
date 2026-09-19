"""Step 3: crawl.

Phase A walks each year's gallery to collect slugs (and the free metadata the
gallery already gives us). Phase B fetches every project page. Everything lands
in raw/ via the cache, so this is safe to interrupt and restart.
"""
import json
import sys

from bs4 import BeautifulSoup

from fetch import ROOT, YEARS, fetch

SLUGS_JSON = ROOT / "data" / "slugs.json"


def gallery_items(html):
    """Yield the per-project metadata the gallery page hands us for free."""
    soup = BeautifulSoup(html, "lxml")
    for item in soup.select(".gallery-item"):
        a = item.select_one("a[href*='/software/']")
        if not a:
            continue
        slug = a["href"].split("/software/")[-1].split("?")[0].strip("/")
        if not slug or "/" in slug:
            continue
        h5 = item.select_one("h5")
        tag = item.select_one("p.tagline")
        yield {
            "slug": slug,
            "software_id": item.get("data-software-id"),
            "gallery_title": h5.get_text(" ", strip=True) if h5 else "",
            "gallery_tagline": tag.get_text(" ", strip=True) if tag else "",
            "gallery_winner": bool(item.select_one(".entry-badge .winner, .entry-badge img.winner")),
        }


def phase_a():
    """Walk galleries until a page adds nothing new."""
    all_items = {}  # slug -> record
    for year, base in YEARS.items():
        seen = set()
        for page in range(1, 60):
            try:
                html = fetch(f"{base}/project-gallery?page={page}")
            except Exception as e:
                print(f"  {year} page {page} ERR {e}", flush=True)
                break
            new = [it for it in gallery_items(html) if it["slug"] not in seen]
            if not new:
                break
            for it in new:
                seen.add(it["slug"])
                # First year to claim a slug wins; a project is submitted once.
                if it["slug"] not in all_items:
                    all_items[it["slug"]] = {**it, "year": year}
            print(f"  {year} page {page} +{len(new)}", flush=True)
        print(f"== {year}: {len(seen)} projects", flush=True)

    SLUGS_JSON.parent.mkdir(exist_ok=True)
    SLUGS_JSON.write_text(json.dumps(all_items, indent=1))
    print(f"\nPhase A done: {len(all_items)} unique slugs -> {SLUGS_JSON}", flush=True)
    return all_items


def phase_b(all_items):
    """Fetch every project page."""
    slugs = list(all_items)
    failed = []
    for i, slug in enumerate(slugs, 1):
        try:
            fetch(f"https://devpost.com/software/{slug}")
        except Exception as e:
            failed.append(slug)
            print(f"  skip {slug}: {type(e).__name__}", flush=True)
        if i % 100 == 0:
            print(f"  {i}/{len(slugs)}", flush=True)
    print(f"\nPhase B done. {len(failed)} failures.", flush=True)
    if failed:
        (ROOT / "data" / "failed_slugs.json").write_text(json.dumps(failed, indent=1))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    items = json.loads(SLUGS_JSON.read_text()) if SLUGS_JSON.exists() and which == "b" else None
    if which in ("a", "all"):
        items = phase_a()
    if which in ("b", "all"):
        phase_b(items)
