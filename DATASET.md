# Hack the North, 2014-2025

3,443 project submissions across 12 years of Hack the North, with
161 finalist labels. Assembled from Devpost's public project
galleries and museum.hackthenorth.com.

As far as we know nobody has put this together before. Devpost gives you one
hackathon at a time; the museum gives you the winners without the field they beat.
What about combining both of these together?


## Coverage

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


## Columns

| column | type | meaning |
|---|---|---|
| `slug` | string | Devpost slug. PRIMARY KEY. devpost.com/software/<slug> |
| `year` | int16 | HTN edition the project was submitted to (2014-2026) |
| `url` | string | Devpost project URL |
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

## Known limits

- `team_size` counts Devpost profiles listed on the submission, which undercounts
  teams where someone never joined the Devpost entry.
- `has_repo` is any `github.com` link on the page, which includes links to
  libraries used rather than the team's own repo.
- Finalist counts are higher in 2020 (23) and 2021 (17); those were the
  virtual years and HTN recognised more projects.
- Prize tracks in 2014 were unnamed - every award reads "Winner" - so 2014
  finalist labels rest on the museum alone.
- `description` is the writeup only. The tag list and link nav are stripped, so
  two projects sharing a stack are not textually similar for that reason.
