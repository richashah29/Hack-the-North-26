"""Generate DATASET.md from the corpus itself, so the numbers are never stale."""
import pathlib
import sys

import pandas as pd

from fetch import ROOT

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

TEMPLATE = """# Hack the North, 2014-2025

{n_projects:,} project submissions across {n_years} years of Hack the North, with
{n_finalists} finalist labels. Assembled {date} from Devpost's public project
galleries and museum.hackthenorth.com.

As far as we know nobody has put this together before. Devpost gives you one
hackathon at a time; the museum gives you the winners without the field they beat.
The interesting object is the pair.

## Provenance

| | |
|---|---|
| Projects | Devpost galleries, `hackthenorth{{year}}.devpost.com/project-gallery` |
| Finalist labels | `museum.hackthenorth.com` ({n_museum} slugs) cross-checked against Devpost prize text |
| Join key | Devpost `slug`, exact - no fuzzy matching |
| Label agreement | {agree_pct:.1f}% of finalists confirmed by both sources |
| Crawl | ~0.7s/request, single-threaded, cached. `robots.txt` permits it |

## Coverage

{coverage}

2026 is absent on purpose: its gallery was still empty while HTN 2026 was being
judged. That is the population a judge's query represents - an unlabelled project
being compared against everything that came before.

## Columns

{columns}

## Known limits

- `team_size` counts Devpost profiles listed on the submission, which undercounts
  teams where someone never joined the Devpost entry.
- `has_repo` is any `github.com` link on the page, which includes links to
  libraries used rather than the team's own repo.
- Finalist counts are higher in 2020 ({n2020}) and 2021 ({n2021}); those were the
  virtual years and HTN recognised more projects. Not a join error.
- Prize tracks in 2014 were unnamed - every award reads "Winner" - so 2014
  finalist labels rest on the museum alone.
- `description` is the writeup only. The tag list and link nav are stripped, so
  two projects sharing a stack are not textually similar for that reason.
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
