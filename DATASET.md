# The Dataset

3,443 Hack the North projects over 12 years with 161 finalists.

We created our dataset using both Devpost and the Hack the North museum. Devpost has every project ever submitted, but only one hackathon at a time. The Hack the North museum has all the finalists, but not the hundreds of projects they
beat. We put them together so understand what did people build, and what project actually won?

## How we got it

Every year of HTN has its own Devpost site, and they're all named the same way -
`hackthenorth2019.devpost.com`, `hackthenorth2024.devpost.com`, and so on. 2014 is
just `hackthenorth.devpost.com`, because it was the first one.

We used two passes:

**1. Walk through the galleries.** Each year's hackathon project gallery has 24 projects for each page. We keep asking for the next page until one comes back with nothing new on it. That gives us a pile of slugs, the `chessmate-nwygvq` bit on the end of a Devpost URL.

**2. Go get every project page.** Grab the links for each individual project; all 3,443 of them, one at a time, half a second apart.

Everything we fetch gets written to disk immediately. Once the HTML is on disk we pull each project description apart: title, tagline, the Devpost prompt sections (Inspiration, What it does, Challenges I ran into...), the tech tags, how many people were on the team, whether there's a demo video, whether anyone linked a repo.

## How we know who won

The museum lists all 161 finalists, and its URLs use the exact same slugs Devpost does. So the join is exact.

Devpost also prints prizes on the project page itself, which reconfirms our opinion. The two sources agree on 79% of finalists. The disagreements are only in the early years like 2014 where there were no named prize tracks and every award read "Winner". In this case, only the museum knows what being a finalist meant.

## What the dataset looks like

There's one row per project.

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

A couple of things that jump out of that table. Writeups have got a lot longer. 131
words in 2014 became an average of 465 words in 2025. And look at the video column in 2020 and 2021: 72%, against 15% the year before. Those were the virtual years, when a demo video was the only way anyone was going to see the project work.

The columns of the dataset:

| column | type | meaning |
|---|---|---|
| `slug` | string | Devpost slug. PRIMARY KEY. devpost.com/software/<slug> |
| `year` | int16 | Calendar year of the edition (2014-2026) |
| `event` | string | Hackathon family: 'Hack the North' | 'UofTHacks' | 'GenAI Genesis' |
| `event_id` | string | Unique edition id, e.g. 'htn-2019', 'uofthacks-vi' |
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
| `finalist` | bool | THE LABEL. For HTN: museum-verified top ~12 (4.7%). For other events: won any prize. NOT comparable across events. |
| `won_prize` | bool | Won any Devpost prize. Computed identically everywhere, so THIS is the label to use when pooling events (HTN 11.2%). |
| `prizes` | object | list[str] of prize strings won at this event, verbatim |
| `n_prizes` | int16 | len(prizes) |
| `label_source` | string | 'museum+devpost' | 'museum' | 'devpost' | 'none' |

## Things to know before you trust a number

- `team_size` counts people listed on the Devpost submission. If someone on the team never joined the entry, they're invisible to us.
- `has_repo` means a `github.com` link appears somewhere on the page. Sometimes that's the team's repo, sometimes it's a library they used.
- 2020 and 2021 have more finalists than usual (23 and 17) as those were the virtual years.
- 2014's labels rest on the museum alone, for the unnamed-prize-track reason above.
- `description` is the writeup only. We strip the tag list and the link navigation out of it, so two projects don't look similar just because they both used React.
