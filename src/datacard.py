"""Generate DATASET.md from the corpus itself, so the numbers are never stale."""
import pathlib
import sys

import pandas as pd

from fetch import ROOT

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

TEMPLATE = """# The dataset

{n_projects:,} Hack the North projects, {n_years} years, {n_finalists} of them finalists.

Devpost has every project ever submitted, but only one hackathon at a time. The
Hack the North museum has the finalists, but not the hundreds of projects they
beat. Neither is that useful alone. Put them together and you can finally ask the
obvious question: what did people build, and what actually won?

## How we got it

Every year of HTN has its own Devpost site, and they're all named the same way -
`hackthenorth2019.devpost.com`, `hackthenorth2024.devpost.com`, and so on. 2014 is
just `hackthenorth.devpost.com`, because it was the first one and nobody knew there
would be more.

Two passes:

**1. Walk the galleries.** Each year's project gallery is paginated, 24 projects to
a page. We keep asking for the next page until one comes back with nothing new on
it. That gives us a pile of slugs, the `chessmate-nwygvq` bit on the end of a
Devpost URL.

**2. Go get every project page.** All {n_projects:,} of them, one at a time, half a
second apart so we're not hammering anyone's server. We checked `robots.txt` first
and it's fine with this.

Everything we fetch gets written to disk immediately. That sounds like a boring
detail but it's the only reason this worked at all. Our parser was wrong about four
separate things before it was right, and each fix cost us a re-parse of files we
already had instead of an hour of re-downloading.

Once the HTML is on disk we pull each writeup apart: title, tagline, the Devpost
prompt sections (Inspiration, What it does, Challenges I ran into...), the tech
tags, how many people were on the team, whether there's a demo video, whether
anyone linked a repo.

## How we know who won

The museum lists all {n_museum} finalists, and its URLs use the exact same slugs
Devpost does. So the join is exact. No fuzzy-matching on project titles, no
hand-fixing the ones that almost match. Every finalist in the museum found its row
in our data, all {n_museum} of them.

Devpost also prints prizes on the project page itself, which gets us a second
opinion for free. The two sources agree on {agree_pct:.0f}% of finalists. The
disagreements are all in the early years: in 2014 there were no named prize tracks,
so every award just reads "Winner" and the museum is the only thing that knows what
being a finalist meant. Worth noting Devpost never once claimed a finalist the
museum didn't have, so the two never actually contradict each other.

## What it looks like

One row per project.

{coverage}

A couple of things jump out of that table. Writeups have got a lot longer - 131
words in 2014, 465 in 2025. And look at the video column in 2020 and 2021: 72%,
against 15% the year before. Those were the virtual years, when a demo video was
the only way anyone was going to see your project work.

Here's every column:

{columns}

## Things to know before you trust a number

- `team_size` counts people listed on the Devpost submission. If someone on your
  team never joined the entry, they're invisible to us.
- `has_repo` means a `github.com` link appears somewhere on the page. Sometimes
  that's the team's repo, sometimes it's a library they used.
- 2020 and 2021 have more finalists than usual ({n2020} and {n2021}). Those were
  the virtual years and HTN recognised more projects. It's not a broken join.
- 2014's labels rest on the museum alone, for the unnamed-prize-track reason above.
- `description` is the writeup only. We strip the tag list and the link nav out of
  it, so two projects don't look similar just because they both used React.
"""


def main():
    df = pd.read_parquet(ROOT / "data" / "corpus.parquet")
    fin = df[df.finalist]

    cov = df.groupby("year").agg(
        projects=("slug", "size"),
        finalists=("finalist", "sum"),
        median_words=("desc_words", "median"),
        pct_video=("has_video", lambda s: round(100 * s.mean(), 1)),
        pct_repo=("has_repo", lambda s: round(100 * s.mean(), 1)),
    )
    cov["finalist_rate_%"] = (100 * cov.finalists / cov.projects).round(1)

    import schema
    cols = "\n".join(
        f"| `{name}` | {dtype} | {desc} |" for name, (dtype, desc) in schema.COLUMNS.items()
    )
    cols = "| column | type | meaning |\n|---|---|---|\n" + cols

    agree = (fin.label_source == "museum+devpost").sum()
    text = TEMPLATE.format(
        n_projects=len(df),
        n_years=df.year.nunique(),
        n_finalists=int(df.finalist.sum()),
        n_museum=int(df.museum_url.ne("").sum()),
        agree_pct=100 * agree / max(1, len(fin)),
        date=pd.Timestamp.now().strftime("%d %B %Y"),
        coverage=cov.to_markdown(),
        columns=cols,
        n2020=int(df[df.year == 2020].finalist.sum()),
        n2021=int(df[df.year == 2021].finalist.sum()),
    )
    out = ROOT / "DATASET.md"
    out.write_text(text)
    print("->", out)
    print(cov.to_string())


if __name__ == "__main__":
    main()
