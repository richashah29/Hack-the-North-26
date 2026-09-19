# The dataset

3,443 Hack the North projects, 12 years, 161 of them finalists.

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

**2. Go get every project page.** All 3,443 of them, one at a time, half a
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

The museum lists all 161 finalists, and its URLs use the exact same slugs
Devpost does. So the join is exact. No fuzzy-matching on project titles, no
hand-fixing the ones that almost match. Every finalist in the museum found its row
in our data, all 161 of them.

Devpost also prints prizes on the project page itself, which gets us a second
opinion for free. The two sources agree on 79% of finalists. The
disagreements are all in the early years: in 2014 there were no named prize tracks,
so every award just reads "Winner" and the museum is the only thing that knows what
being a finalist meant. Worth noting Devpost never once claimed a finalist the
museum didn't have, so the two never actually contradict each other.

## What it looks like

One row per project.

|   year |   projects |   finalists |   median_words |   pct_video |   pct_repo |   finalist_rate_% |
|-------:|-----------:|------------:|---------------:|------------:|-----------:|------------------:|
|   2014 |        195 |          10 |          131   |        20   |       14.4 |               5.1 |
|   2015 |        236 |          12 |          249   |        28.4 |       61.4 |               5.1 |
|   2016 |        222 |          12 |          246.5 |        17.1 |       72.5 |               5.4 |
|   2017 |        217 |          14 |          269   |        15.7 |       70.5 |               6.5 |
|   2018 |        245 |          12 |          319   |         8.6 |       77.1 |               4.9 |
|   2019 |        319 |          13 |          322   |        15.4 |       72.1 |               4.1 |
|   2020 |        596 |          23 |          399   |        72.3 |       87.9 |               3.9 |
|   2021 |        446 |          17 |          390.5 |        72.6 |       79.4 |               3.8 |
|   2022 |        222 |          12 |          428.5 |        27.5 |       82.9 |               5.4 |
|   2023 |        250 |          12 |          449   |        30.4 |       85.2 |               4.8 |
|   2024 |        235 |          12 |          464   |        41.7 |       88.1 |               5.1 |
|   2025 |        260 |          12 |          465   |        60   |       90   |               4.6 |

A couple of things jump out of that table. Writeups have got a lot longer - 131
words in 2014, 465 in 2025. And look at the video column in 2020 and 2021: 72%,
against 15% the year before. Those were the virtual years, when a demo video was
the only way anyone was going to see your project work.

Here's every column:

| column | type | meaning |
|---|---|---|
| `slug` | string | Devpost slug. PRIMARY KEY. devpost.com/software/<slug> |
| `year` | int16 | HTN edition the project was submitted to (2014-2026) |
| `url` | string | Canonical Devpost project URL |
| `museum_url` | string | museum.hackthenorth.com/<slug> if a finalist, else '' |
| `title` | string | Project name |
| `tagline` | string | One-line pitch under the title |
| `description` | string | Full README body text, sections concatenated |
| `sec_inspiration` | string | Devpost prompt: Inspiration |
| `sec_what_it_does` | string | Devpost prompt: What it does |
| `sec_how_built` | string | Devpost prompt: How I/we built it |
| `sec_challenges` | string | Devpost prompt: Challenges I/we ran into |
| `sec_accomplishments` | string | Devpost prompt: Accomplishments I'm/we're proud of |
| `sec_learned` | string | Devpost prompt: What I/we learned |
| `sec_whats_next` | string | Devpost prompt: What's next for X |
| `built_with` | object | list[str] of lowercase tech tags |
| `n_built_with` | int16 | len(built_with) |
| `team_size` | int16 | Number of listed team members (min 1) |
| `desc_words` | int32 | Whitespace word count of description |
| `has_video` | bool | Embedded YouTube/Vimeo iframe present |
| `has_repo` | bool | A github.com link appears anywhere on the page |
| `finalist` | bool | Top-~12 finalist for its year. THE LABEL. |
| `prizes` | object | list[str] of HTN prize strings won, verbatim |
| `n_prizes` | int16 | len(prizes) |
| `label_source` | string | 'museum+devpost' | 'museum' | 'devpost' | 'none' |

## Things to know before you trust a number

- `team_size` counts people listed on the Devpost submission. If someone on your
  team never joined the entry, they're invisible to us.
- `has_repo` means a `github.com` link appears somewhere on the page. Sometimes
  that's the team's repo, sometimes it's a library they used.
- 2020 and 2021 have more finalists than usual (23 and 17). Those were
  the virtual years and HTN recognised more projects. It's not a broken join.
- 2014's labels rest on the museum alone, for the unnamed-prize-track reason above.
- `description` is the writeup only. We strip the tag list and the link nav out of
  it, so two projects don't look similar just because they both used React.
