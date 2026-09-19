# Prior Art — data lane (Richa)

## What we're building

We scraped every Hack the North project since 2014 — roughly 2,000 submissions, 161 of which were finalists. A judge types in a project idea, and our app shows them where it lands among twelve years of history: its nearest neighbours, which of those won, and what actually correlates with winning here.

Nobody has ever assembled this dataset. That's the whole pitch.

## Your job, in one sentence

Own the corpus end to end: crawl it, parse it, label it, analyse it.

**The only deadline that matters to you: `corpus.parquet` in the repo by 13:30.** Sara is building the entire app against a fake 20-row sample until then, so she is not blocked — but she can't show real data to a judge until you ship. Partial is fine. Eight years on time beats twelve years at 16:00.

You also do the talking at judging. The dataset is the story, and it frees Sara to concentrate on driving the laptop.

---

## Setup (09:00, 5 min)

```bash
pip install httpx beautifulsoup4 pandas pyarrow lxml matplotlib
mkdir -p raw data
```

We agree `schema.py` together at 09:00 before either of us writes anything else. Twenty minutes, then we split.

---

## Step 1 — The slug test (09:20, 10 min)

Museum URLs look like `museum.hackthenorth.com/chessmate-nwygvq`. That random suffix is Devpost's slug format. If the same slug works on Devpost, our labels join to our data on an exact key and we skip an hour of fuzzy title matching.

```python
import httpx
for slug in ["chessmate-nwygvq", "pulsegrip", "dejavu", "spyder"]:
    r = httpx.get(f"https://devpost.com/software/{slug}",
                  follow_redirects=True, timeout=20)
    print(slug, r.status_code)
```

- **All 200** → brilliant. Labels join on `slug`. Skip to Step 2.
- **Mostly 404** → fall back to matching on normalised title + year. Budget one hour, hand-fix the stragglers. Tell Sara immediately so she knows labels arrive later.

**Done when:** you know which join strategy you're using.

---

## Step 2 — Find every year's gallery (09:30, 20 min)

Known good:

- 2014 → `https://hackthenorth.devpost.com`
- 2024 → `https://hackthenorth2024.devpost.com`
- 2025 → `https://hackthenorth2025.devpost.com`
- 2026 → `https://hackthenorth2026.devpost.com`

Probe 2015–2023 with the same pattern:

```python
import httpx
years = {}
for y in range(2015, 2026):
    url = f"https://hackthenorth{y}.devpost.com/project-gallery"
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20)
        if r.status_code == 200:
            years[y] = f"https://hackthenorth{y}.devpost.com"
            print("OK  ", y)
        else:
            print("MISS", y, r.status_code)
    except Exception as e:
        print("ERR ", y, e)
```

Any year that misses, search Devpost manually for "Hack the North <year>" — a couple of the early ones may live on `challengepost.com` or use a different slug. **Spend at most 20 minutes on this.** Eleven years is still a twelve-year dataset minus one; don't lose the morning to 2016.

**Done when:** you have a dict `{year: base_url}`.

---

## Step 3 — Crawl (start by 10:00, runs in background)

**Save raw HTML to disk before parsing anything.** Your parser will have bugs — everyone's does — and re-crawling 2,000 pages because of a typo is how you lose the afternoon. Scrape once, parse a hundred times.

```python
# scrape.py
import httpx, hashlib, pathlib, time
from bs4 import BeautifulSoup

RAW = pathlib.Path('raw'); RAW.mkdir(exist_ok=True)
HEAD = {'User-Agent': 'HTN2026-student-research/1.0 (richa@youremail)'}

def fetch(url, delay=0.5):
    key = RAW / (hashlib.sha1(url.encode()).hexdigest() + '.html')
    if key.exists():
        return key.read_text(encoding='utf-8')      # never re-fetch
    r = httpx.get(url, headers=HEAD, timeout=25, follow_redirects=True)
    r.raise_for_status()
    key.write_text(r.text, encoding='utf-8')
    with (RAW / 'index.tsv').open('a', encoding='utf-8') as f:
        f.write(f"{key.name}\t{url}\n")
    time.sleep(delay)                                # be a good citizen
    return r.text

def gallery_slugs(html):
    soup = BeautifulSoup(html, 'lxml')
    out = set()
    for a in soup.select('a[href*="/software/"]'):
        slug = a['href'].split('/software/')[-1].split('?')[0].strip('/')
        if slug and '/' not in slug:
            out.add(slug)
    return out

# Phase A: walk each year's gallery pages until a page adds nothing new
all_slugs = {}                      # slug -> year
for year, base in years.items():
    seen = set()
    for page in range(1, 40):
        html = fetch(f"{base}/project-gallery?page={page}")
        new = gallery_slugs(html) - seen
        if not new:
            break
        seen |= new
        print(year, "page", page, "+", len(new))
    for s in seen:
        all_slugs.setdefault(s, year)
    print(f"== {year}: {len(seen)} projects")

# Phase B: the project pages themselves
for i, slug in enumerate(all_slugs):
    try:
        fetch(f"https://devpost.com/software/{slug}")
    except Exception as e:
        print("skip", slug, e)
    if i % 50 == 0:
        print(f"{i}/{len(all_slugs)}")
```

At half a second per request the whole crawl is roughly 20–30 minutes. **Start it, then write the parser while it runs.** Don't sit and watch it.

If you start getting 429s or connection resets: raise `delay` to 1.5 and restart. The cache means you resume where you left off, losing nothing.

**Done when:** `raw/` has a few thousand files.

---

## Step 4 — Parser (11:00–12:30)

**Before writing this, open one real project page in your browser and inspect it.** Devpost's markup has drifted over twelve years and my selectors below are a starting point, not gospel. Check a 2015 page and a 2025 page — they will differ.

```python
# parse.py
from bs4 import BeautifulSoup

def parse(html, slug, year):
    s = BeautifulSoup(html, 'lxml')

    def txt(sel):
        el = s.select_one(sel)
        return el.get_text(' ', strip=True) if el else ''

    title   = txt('#app-title') or txt('h1')
    tagline = txt('#software-header p.large') or txt('p.large')

    body_el = s.select_one('#app-details-left')
    description = body_el.get_text('\n', strip=True) if body_el else ''

    sections, cur = {}, None
    if body_el:
        for node in body_el.find_all(['h2', 'h3', 'p', 'li']):
            if node.name in ('h2', 'h3'):
                cur = node.get_text(' ', strip=True).lower()
                sections.setdefault(cur, '')
            elif cur:
                sections[cur] += node.get_text(' ', strip=True) + '\n'

    built = [li.get_text(strip=True) for li in s.select('#built-with li')]
    team  = s.select('.software-team-member') or s.select('#app-team li')

    hrefs = [a.get('href') or '' for a in s.select('a')]
    return {
        "slug": slug,
        "year": year,
        "title": title,
        "tagline": tagline,
        "description": description,
        "sections": sections,
        "built_with": built,
        "team_size": max(1, len(team)),
        "has_video": bool(s.select_one('iframe[src*="youtube"], iframe[src*="vimeo"]')),
        "has_repo": any('github.com' in h for h in hrefs),
        "prizes": [e.get_text(strip=True) for e in s.select('.software-list-content .winner, .winner')],
        "finalist": False,      # filled in Step 5
    }
```

Parse everything, and **print a QA summary** — this matters more than it sounds:

```python
import pandas as pd
rows = [parse(open(f'raw/{h}').read(), slug, y) for ...]
df = pd.DataFrame(rows)
print(df.groupby('year').size())
print("empty descriptions:", (df.description.str.len() < 50).sum())
print("empty titles:", (df.title == '').sum())
```

If one year has a suspicious number of empty descriptions, its markup is different — write a fallback branch for that year, or drop it. **Don't let a silently-broken year into the corpus**; it'll wreck the analysis and you won't know why.

**Done when:** `df` has a sane row count per year and few empties.

---

## Step 5 — Join the labels (12:30–13:30)

The museum page lists all 161 finalists on one page, grouped by year:

```python
from bs4 import BeautifulSoup
html = fetch("https://museum.hackthenorth.com/")
soup = BeautifulSoup(html, 'lxml')

finalists = set()
for a in soup.select('a[href]'):
    href = a['href']
    if 'museum.hackthenorth.com/' in href or href.startswith('/'):
        slug = href.rstrip('/').split('/')[-1]
        if slug and slug not in ('', 'index'):
            finalists.add(slug)

print(len(finalists), "finalist slugs")   # expect ~161
df['finalist'] = df.slug.isin(finalists)
print(df.groupby('year').finalist.sum())  # expect ~12 per year
```

**Sanity check: roughly 12 finalists per year.** If a year shows 0, the join failed for that year — investigate before shipping. If the slug test in Step 1 failed, this is where you do the fuzzy title match instead.

---

## Step 6 — SHIP (13:30, hard)

```python
df.to_parquet('data/corpus.parquet')
```

Commit, push, tell Sara. **Do this at 13:30 even if it's imperfect.** She needs real data in the app with hours to spare, not minutes. You can push a better corpus at 15:00 and she'll just reload it.

---

## Step 7 — Analysis (14:00–16:00)

Answer these, with actual numbers:

1. **What correlates with being a finalist?** Team size, description length, has_video, has_repo, number of built-with tags, number of prize tracks entered. Compare finalist vs. non-finalist means, and report effect size — not just a p-value.
2. **The twelve-year technology arc.** Count `built_with` tags by year, normalised. Blockchain, VR, the LLM wave. This becomes the prettiest chart we have.
3. **Does "solving a real problem" help?** Keyword-flag descriptions for impact framing vs. playful framing, and compare finalist rates. Given what HTN says about wanting playful projects, this could be a genuinely spicy finding.

Export each chart's underlying numbers as JSON for Sara to render, plus a static PNG as backup. **Caption each chart with the actual claim** — "demo videos don't predict finalists" — not a chart title like "Video vs. outcome."

---

## Step 8 — The GPTZero pass (16:00–17:30)

Run project descriptions through the GPTZero API, aggregate the AI-likelihood score by year, and plot the curve. There should be a visible inflection around 2023.

**Aggregate only. Never name a team or a person.** This is both the right call and the better analysis — and we'll say so unprompted in the pitch.

If you're short on time, sample 100 projects per year rather than running all 2,000.

---

## When things break

| Problem | What to do |
|---|---|
| Devpost rate-limits you | Raise the delay to 1.5s, restart. The cache resumes you. Don't parallelise. |
| A year's markup is different | Write a fallback branch, or drop the year. Cap it at 30 minutes. |
| Slug join fails | Fuzzy match on normalised title + year, hand-fix the rest. One hour, capped. |
| You're behind at 15:00 | Cut Step 8 first, then Step 7 item 3. Steps 1–6 are the ones the demo needs. |
| Finalist counts look wrong | Stop and fix. A broken join silently ruins every number we show a judge. |

## The three times we're in the same place

- **09:20** — agree `schema.py` + write `sample.json` together, then split
- **13:30** — you ship `corpus.parquet`
- **18:00** — first full run of the demo, filmed

Text Sara the moment anything slips. Two people have no slack.
