"""The corpus contract between the data lane (Richa) and the app (Sara).

One row per Devpost project submitted to a Hack the North hackathon, 2014-2026.
`slug` is the primary key and joins to museum.hackthenorth.com/<slug>.

If a column changes, it changes HERE first and both of us reload.
"""

# name -> (pandas dtype, description)
COLUMNS = {
    # --- identity -------------------------------------------------------
    "slug":         ("string", "Devpost slug. PRIMARY KEY. devpost.com/software/<slug>"),
    "year":         ("int16",  "HTN edition the project was submitted to (2014-2026)"),
    "url":          ("string", "Canonical Devpost project URL"),
    "museum_url":   ("string", "museum.hackthenorth.com/<slug> if a finalist, else ''"),

    # --- text -----------------------------------------------------------
    "title":        ("string", "Project name"),
    "tagline":      ("string", "One-line pitch under the title"),
    "description":  ("string", "Full README body text, sections concatenated"),
    "sec_inspiration":     ("string", "Devpost prompt: Inspiration"),
    "sec_what_it_does":    ("string", "Devpost prompt: What it does"),
    "sec_how_built":       ("string", "Devpost prompt: How I/we built it"),
    "sec_challenges":      ("string", "Devpost prompt: Challenges I/we ran into"),
    "sec_accomplishments": ("string", "Devpost prompt: Accomplishments I'm/we're proud of"),
    "sec_learned":         ("string", "Devpost prompt: What I/we learned"),
    "sec_whats_next":      ("string", "Devpost prompt: What's next for X"),

    # --- features -------------------------------------------------------
    "built_with":   ("object", "list[str] of lowercase tech tags"),
    "n_built_with": ("int16",  "len(built_with)"),
    "team_size":    ("int16",  "Number of listed team members (min 1)"),
    "desc_words":   ("int32",  "Whitespace word count of description"),
    "has_video":    ("bool",   "Embedded YouTube/Vimeo iframe present"),
    "has_repo":     ("bool",   "A github.com link appears anywhere on the page"),

    # --- outcome (the labels) -------------------------------------------
    "finalist":     ("bool",   "Top-~12 finalist for its year. THE LABEL."),
    "prizes":       ("object", "list[str] of HTN prize strings won, verbatim"),
    "n_prizes":     ("int16",  "len(prizes)"),
    "label_source": ("string", "'museum+devpost' | 'museum' | 'devpost' | 'none'"),
}

# Years the museum covers, and therefore where `finalist` is trustworthy.
# HTN 2026 is being judged right now: its rows are real but UNLABELLED, which is
# exactly the population a judge's query represents.
LABELLED_YEARS = range(2014, 2026)

SAMPLE_PATH = "data/sample.json"
CORPUS_PATH = "data/corpus.parquet"


def validate(df):
    """Raise if the corpus violates the contract. Called before every ship."""
    problems = []

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        problems.append(f"missing columns: {missing}")
    extra = [c for c in df.columns if c not in COLUMNS]
    if extra:
        problems.append(f"undeclared columns: {extra}")

    if df.slug.duplicated().any():
        dupes = df.slug[df.slug.duplicated()].tolist()[:5]
        problems.append(f"duplicate slugs: {dupes}")
    if df.slug.eq("").any():
        problems.append("empty slugs present")
    if not df.year.between(2014, 2026).all():
        problems.append(f"years out of range: {sorted(set(df.year) - set(range(2014, 2027)))}")
    if df.team_size.lt(1).any():
        problems.append("team_size < 1")

    for y in LABELLED_YEARS:
        n = int(df[df.year == y].finalist.sum())
        if n == 0:
            problems.append(f"{y}: ZERO finalists - the join failed for that year")
        elif not 5 <= n <= 25:
            problems.append(f"{y}: {n} finalists, expected ~12")

    if problems:
        raise AssertionError("corpus contract violated:\n  - " + "\n  - ".join(problems))
    return True
