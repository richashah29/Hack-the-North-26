"""Steps 4-6: parse everything, join labels, QA, ship corpus.parquet."""
import json
import sys

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import schema  # noqa: E402

from events import HTN_IDS  # noqa: E402
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
        row = parse(p.read_text(encoding="utf-8"), slug, meta)
        # Fall back to the gallery's copy when the project page yields nothing.
        row["title"] = row["title"] or meta.get("gallery_title", "")
        row["tagline"] = row["tagline"] or meta.get("gallery_tagline", "")
        rows.append(row)

    print(f"parsed {len(rows)} projects ({missing} not yet crawled)")
    df = pd.DataFrame(rows)

    # --- the join ------------------------------------------------------
    is_htn = df.event_id.isin(HTN_IDS)

    # Hack the North has a museum listing its top ~12 per year, so its label stays
    # the strict one. No other event has an equivalent, so there the label is the
    # Devpost prize badge. Same column, two meanings -- `won_prize` is the one
    # that means the same thing everywhere.
    df["_finalist_museum"] = df.slug.isin(finalists)
    df["finalist"] = (is_htn & (df._finalist_museum | df._finalist_devpost)) | (~is_htn & df.won_prize)
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
    print("\n=== per event (the gate: no zero-winner events) ===")
    per_event = df.groupby(["event", "event_id"]).agg(
        projects=("slug", "size"),
        winners=("won_prize", "sum"),
        empty_desc=("description", lambda s: int((s.str.len() < 50).sum())),
        median_words=("desc_words", "median"),
    )
    per_event["win_%"] = (100 * per_event.winners / per_event.projects).round(1)
    per_event["empty_%"] = (100 * per_event.empty_desc / per_event.projects).round(1)
    print(per_event.to_string())

    broken = per_event[per_event.winners == 0]
    if len(broken):
        print(f"\n  !! {len(broken)} event(s) with ZERO winners - selector failed, drop them:")
        print(broken.to_string())
    dirty = per_event[per_event["empty_%"] > 25]
    if len(dirty):
        print(f"\n  !! {len(dirty)} event(s) with >25% empty descriptions - different markup:")
        print(dirty.to_string())

    print("\n=== rows per year (HTN) ===")
    per_year = df[df.event_id.isin(HTN_IDS)].groupby("year").agg(
        n=("slug", "size"),
        finalists=("finalist", "sum"),
        empty_desc=("description", lambda s: int((s.str.len() < 50).sum())),
        empty_title=("title", lambda s: int((s == "").sum())),
        median_words=("desc_words", "median"),
    )
    print(per_year.to_string())

    # HTN-only: the museum covers Hack the North and nothing else, and other
    # events have their own "Finalists" tracks that would pollute the comparison.
    print("\n=== label reconciliation, HTN only (museum vs Devpost prize text) ===")
    df = df[df.event_id.isin(HTN_IDS)]
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

    # Two corpora, one parse, so they can never drift apart.
    #   corpus.parquet       Hack the North alone - the default, the demo
    #   corpus_multi.parquet all three event families - the wider pool
    htn = df[df.event_id.isin(HTN_IDS)].reset_index(drop=True)

    schema.validate(htn, scope="htn")
    schema.validate(df, scope="multi")
    print("\ncontract: OK for both scopes")

    for frame, path, label in [
        (htn, ROOT / schema.CORPUS_PATH, "Hack the North"),
        (df, ROOT / schema.MULTI_CORPUS_PATH, "all events"),
    ]:
        frame.to_parquet(path, index=False)
        print(f"-> {path.name:22} {len(frame):>5} rows, "
              f"{int(frame.finalist.sum()):>4} labelled, {path.stat().st_size/1e6:.1f} MB  ({label})")

    # A real 20-row sample so Sara can swap off her fake fixture immediately.
    sample = pd.concat([htn[htn.finalist].head(10), htn[~htn.finalist].head(10)])
    sample_path = ROOT / schema.SAMPLE_PATH
    sample_path.write_text(sample.to_json(orient="records", indent=1))
    print(f"-> {sample_path.name} ({len(sample)} rows)")


if __name__ == "__main__":
    main()
