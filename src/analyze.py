"""Step 7: the three questions, with effect sizes.

Every chart exports its underlying numbers as JSON for Sara to render, plus a
PNG as backup. Captions state the claim, not the axes.
"""
import json
import math
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from fetch import ROOT  # noqa: E402

OUT = ROOT / "data" / "findings"
FIG = ROOT / "data" / "figures"
LABELLED = range(2014, 2026)

CATEGORIES = {
    "LLM / genAI": r"openai|gpt|llm|langchain|anthropic|claude|gemini|huggingface|cohere|groq|ollama|rag\b|llama",
    "ML / AI (classic)": r"tensorflow|pytorch|keras|scikit|sklearn|opencv|nltk|spacy|ml\b|machine-learning",
    "Blockchain / crypto": r"blockchain|ethereum|solidity|web3|nft|bitcoin|smart-contract|hyperledger",
    "VR / AR": r"\bvr\b|\bar\b|oculus|unity|vuforia|hololens|arkit|arcore|leap-motion|myo",
    "Mobile": r"android|ios|swift|react-native|flutter|kotlin|xamarin",
    "Cloud / infra": r"aws|azure|gcp|google-cloud|docker|kubernetes|firebase|heroku|vercel",
}

IMPACT = r"\b(?:accessib|healthcare|patients?|disabilit|climate|sustainab|poverty|equity|underserved|crisis|mental health|diagnos|safety|refugee|inequal|social good|nonprofit|carbon|emission)"
PLAYFUL = r"\b(?:fun|game|silly|meme|joke|playful|ridiculous|absurd|chaos|shenanigan|for the lols|troll|goofy|useless|cursed|hackathon vibes)"


def cohens_d(a, b):
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (a.mean() - b.mean()) / pooled if pooled else float("nan")


def wilson(k, n, z=1.96):
    """Wilson score interval - honest CIs on small per-year finalist counts."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0, c - h), min(1, c + h))


# --------------------------------------------------------------------------
def q1_correlates(df):
    """What actually separates finalists from everyone else?"""
    f = df[df.finalist]
    n = df[~df.finalist]

    # n_prizes WOULD leak: being a finalist IS a prize. Strip finalist prizes.
    df = df.copy()
    df["n_other_prizes"] = [
        sum(1 for p in ps if "finalist" not in p.lower()) for ps in df.prizes
    ]
    f, n = df[df.finalist], df[~df.finalist]

    rows = []
    for col in ["team_size", "desc_words", "n_built_with", "n_other_prizes"]:
        rows.append({
            "feature": col,
            "kind": "continuous",
            "finalist_mean": round(float(f[col].mean()), 2),
            "other_mean": round(float(n[col].mean()), 2),
            "finalist_median": float(f[col].median()),
            "other_median": float(n[col].median()),
            "cohens_d": round(cohens_d(f[col], n[col]), 3),
        })
    for col in ["has_video", "has_repo"]:
        pf, pn = f[col].mean(), n[col].mean()
        rows.append({
            "feature": col,
            "kind": "binary",
            "finalist_rate": round(float(pf), 3),
            "other_rate": round(float(pn), 3),
            "pct_point_diff": round(float((pf - pn) * 100), 1),
            "risk_ratio": round(float(pf / pn), 2) if pn else None,
        })
    return rows


def q2_tech_arc(df):
    """Share of each year's projects using each technology family."""
    out = []
    for year in sorted(set(df.year) & set(LABELLED)):
        sub = df[df.year == year]
        tags = [" ".join(t) for t in sub.built_with]
        rec = {"year": int(year), "n_projects": len(sub)}
        for name, pat in CATEGORIES.items():
            hits = sum(1 for t in tags if re.search(pat, t))
            rec[name] = round(hits / len(sub), 4) if len(sub) else 0.0
        out.append(rec)
    return out


def q3_framing(df):
    """Does 'solving a real problem' framing beat playful framing?"""
    text = (df.title.fillna("") + " " + df.tagline.fillna("") + " " +
            df.sec_inspiration.fillna("") + " " + df.sec_what_it_does.fillna("")).str.lower()
    df = df.assign(
        impact=text.str.contains(IMPACT, regex=True),
        playful=text.str.contains(PLAYFUL, regex=True),
    )
    groups = {
        "impact framing only": df[df.impact & ~df.playful],
        "playful framing only": df[~df.impact & df.playful],
        "both": df[df.impact & df.playful],
        "neither": df[~df.impact & ~df.playful],
    }
    out = []
    for name, sub in groups.items():
        k, n = int(sub.finalist.sum()), len(sub)
        lo, hi = wilson(k, n)
        out.append({
            "group": name, "n": n, "finalists": k,
            "finalist_rate": round(k / n, 4) if n else 0.0,
            "ci95_low": round(lo, 4), "ci95_high": round(hi, 4),
        })
    return out


# --------------------------------------------------------------------------
def plot_tech_arc(arc):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    years = [r["year"] for r in arc]
    for name in CATEGORIES:
        ax.plot(years, [r[name] * 100 for r in arc], marker="o", ms=3.5, lw=2, label=name)
    ax.set_xlabel("Hack the North year")
    ax.set_ylabel("% of that year's projects")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.25)
    ax.set_title("Twelve years of what people actually built", loc="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG / "tech_arc.png", dpi=160)
    plt.close(fig)


def plot_correlates(rows):
    cont = [r for r in rows if r["kind"] == "continuous"]
    fig, ax = plt.subplots(figsize=(8, 4))
    names = [r["feature"] for r in cont]
    ds = [r["cohens_d"] for r in cont]
    ax.barh(names, ds, color=["#2a9d8f" if d > 0 else "#e76f51" for d in ds])
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("Cohen's d  (finalist vs. everyone else)")
    ax.set_title("Effect sizes, not p-values", loc="left", fontsize=12)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "correlates.png", dpi=160)
    plt.close(fig)


def plot_framing(rows):
    fig, ax = plt.subplots(figsize=(8, 4))
    names = [r["group"] for r in rows]
    rates = [r["finalist_rate"] * 100 for r in rows]
    err = [[(r["finalist_rate"] - r["ci95_low"]) * 100 for r in rows],
           [(r["ci95_high"] - r["finalist_rate"]) * 100 for r in rows]]
    ax.bar(names, rates, yerr=err, capsize=5, color="#264653")
    ax.set_ylabel("% that became finalists")
    ax.set_title("Framing vs. outcome (95% Wilson CIs)", loc="left", fontsize=12)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "framing.png", dpi=160)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(ROOT / "data" / "corpus.parquet")
    lab = df[df.year.isin(LABELLED)]
    print(f"analysing {len(lab)} labelled projects ({int(lab.finalist.sum())} finalists), "
          f"{len(df) - len(lab)} unlabelled 2026 rows held out\n")

    q1 = q1_correlates(lab)
    q2 = q2_tech_arc(lab)
    q3 = q3_framing(lab)

    for name, data in [("correlates", q1), ("tech_arc", q2), ("framing", q3)]:
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1))

    print("=== Q1: what correlates with being a finalist ===")
    print(pd.DataFrame(q1).to_string(index=False))
    print("\n=== Q2: technology arc (share of year's projects) ===")
    print(pd.DataFrame(q2).to_string(index=False))
    print("\n=== Q3: impact vs playful framing ===")
    print(pd.DataFrame(q3).to_string(index=False))

    plot_tech_arc(q2)
    plot_correlates(q1)
    plot_framing(q3)
    print(f"\nfigures -> {FIG}")


if __name__ == "__main__":
    main()
