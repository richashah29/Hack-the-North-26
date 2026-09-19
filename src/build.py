"""Steps 4-6: parse everything, join labels, QA, ship corpus.parquet."""
import json
import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import schema  # noqa: E402

from fetch import ROOT, path_for  # noqa: E402
from parse import parse  # noqa: E402

SLUGS_JSON = ROOT / "data" / "slugs.json"
FINALISTS_JSON = ROOT / "data" / "finalists.json"


def build() -> pd.DataFrame:
    slugs = json.loads(SLUGS_JSON.read_text())
    finalists = json.loads(FINALISTS_JSON.read_text())

    rows, missing = [], 0
    for slug, meta in slugs.items():
        p = path_for(f"https://devpost.com/software/{slug}")
        if not p.exists():
            missing += 1
            continue
        row = parse(p.read_text(encoding="utf-8"), slug, meta["year"])
        # Fall back to the gallery's copy when the project page yields nothing.
        row["title"] = row["title"] or meta.get("gallery_title", "")
        row["tagline"] = row["tagline"] or meta.get("gallery_tagline", "")
        rows.append(row)

    print(f"parsed {len(rows)} projects ({missing} not yet crawled)")
    df = pd.DataFrame(rows)

    # --- the join ------------------------------------------------------
    df["_finalist_museum"] = df.slug.isin(finalists)
    df["finalist"] = df._finalist_museum | df._finalist_devpost
    df["label_source"] = [
        "museum+devpost" if (m and d) else "museum" if m else "devpost" if d else "none"
        for m, d in zip(df._finalist_museum, df._finalist_devpost)
    ]
    df["museum_url"] = [
        f"https://museum.hackthenorth.com/{s}" if m else ""
        for s, m in zip(df.slug, df._finalist_museum)
    ]

    # --- QA ------------------------------------------------------------
    qa(df, finalists)

    # --- conform to the contract ---------------------------------------
    df = df[list(schema.COLUMNS)]
    for col, (dtype, _) in schema.COLUMNS.items():
        if dtype != "object":
            df[col] = df[col].astype(dtype)
    return df.sort_values(["year", "slug"]).reset_index(drop=True)


def qa(df, finalists):
    print("\n=== rows per year ===")
    per_year = df.groupby("year").agg(
        n=("slug", "size"),
        finalists=("finalist", "sum"),
        empty_desc=("description", lambda s: int((s.str.len() < 50).sum())),
        empty_title=("title", lambda s: int((s == "").sum())),
        median_words=("desc_words", "median"),
    )
    print(per_year.to_string())

    print("\n=== label reconciliation (museum vs Devpost prize text) ===")
    both = int((df._finalist_museum & df._finalist_devpost).sum())
    only_m = int((df._finalist_museum & ~df._finalist_devpost).sum())
    only_d = int((~df._finalist_museum & df._finalist_devpost).sum())
    print(f"  agree (both say finalist): {both}")
    print(f"  museum only:               {only_m}")
    print(f"  devpost only:              {only_d}")
    if only_m:
        print("   museum-only:", df[df._finalist_museum & ~df._finalist_devpost].slug.tolist()[:12])
    if only_d:
        print("   devpost-only:", df[~df._finalist_museum & df._finalist_devpost].slug.tolist()[:12])

    unmatched = set(finalists) - set(df.slug)
    print(f"\n  museum finalists not found in corpus: {len(unmatched)}")
    if unmatched:
        print("   ", sorted(unmatched)[:15])

    mismatch = df[df.year != df._gallery_year]
    print(f"\n  year disagreements (submission block vs gallery): {len(mismatch)}")
    if len(mismatch):
        print(mismatch[["slug", "_gallery_year", "year"]].head(10).to_string(index=False))


def main():
    df = build()
    schema.validate(df)
    print("\ncontract: OK")

    out = ROOT / schema.CORPUS_PATH
    df.to_parquet(out, index=False)
    print(f"-> {out}  ({len(df)} rows, {out.stat().st_size/1e6:.1f} MB)")

    # A real 20-row sample so Sara can swap off her fake fixture immediately.
    sample = pd.concat([
        df[df.finalist].head(10),
        df[~df.finalist].head(10),
    ])
    sample_path = ROOT / schema.SAMPLE_PATH
    sample_path.write_text(sample.to_json(orient="records", indent=1))
    print(f"-> {sample_path}  ({len(sample)} rows)")


if __name__ == "__main__":
    main()
