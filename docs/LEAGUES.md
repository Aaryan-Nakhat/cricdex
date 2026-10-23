# Leagues: the registry and how to add one

Every competition CricDex knows is one `[[league]]` entry in
[`config/leagues.toml`](../config/leagues.toml). Nothing else in the code names a league: ingest,
the exporter, pricing, the Scout pools, the auction pool and its nationality rule, the API's
collection check, every CLI / TUI / Streamlit picker, the Makefile and the refresh workflow all read
this file through `cricdex.leagues`. The exporter copies it to `site/public/data/leagues.json`,
which is where the web app gets its labels, Scout panels and each league's fitted translation onto the
IPL.

So **adding a league is one TOML entry and an ingest**, never a code change.

## Add a league in four steps

1. **Find its Cricsheet file.** Every competition on <https://cricsheet.org/matches/> has a JSON
   download such as `psl_male_json.zip`. Check it exists:

   ```bash
   curl -sI https://cricsheet.org/downloads/psl_male_json.zip | head -1   # HTTP/1.1 200 OK
   ```

2. **Add an entry** to `config/leagues.toml` (copy a similar league and edit it):

   ```toml
   [[league]]
   key = "psl"                       # table suffix (balls_psl), site folder, ?c= value
   name = "Pakistan Super League (PSL)"
   short = "PSL"
   zips = ["psl_male_json.zip"]      # several zips are merged into one collection by match id
   gender = "male"                   # male | female | mixed
   kind = "league"                   # league | domestic | international | mixed
   country = "Pakistan"
   tier = "psl"                      # a [tiers.*] key: its pooling group in the translation fit
   export = true                     # cook it into the site / CLI / TUI / dashboard snapshot
   active = true
   order = 70                        # display order (lower first)
   scout_pool = true                 # a Scout look-alike panel
   scout_group = "overseas"          # peers | uncapped | overseas
   scout_title = "Overseas · PSL"
   scout_subtitle = "Pakistan Super League of the same mould"
   draftable = true                  # its players can be drafted into the Auction room
   auction_pool = true               # feeds the cross-league auction pool
   ```

   A new strength tier goes next to the others:

   ```toml
   [tiers.psl]
   group = "overseas_a"   # the leagues it is pooled with when its translation onto the IPL is fitted
   note = "Pakistan Super League: strong overseas league."
   ```

   No number goes here: how a rating there carries over to the IPL is fitted (below). Until it is, the
   league takes its group's typical translation, with the spread between the group's leagues added to
   its uncertainty.

3. **Check it:** `uv run python -m cricdex.leagues check` (or `make leagues`). The loader refuses
   duplicate keys, unknown fields, a missing tier, a malformed zip name, a pool that isn't
   exported, two Scout pools on one tier, and so on, with a message naming the entry.

4. **Ingest, rate, compute, export:**

   ```bash
   uv run python scripts/ingest_cricsheet.py ingest -c psl --force
   uv run python scripts/scout_rate.py -c psl --advi-steps 12000
   uv run python scripts/compute_metrics.py all -c psl
   uv run python scripts/export_site.py       # every exported league; also writes leagues.json
   ```

   The Auction pool and Scout read every league's ratings at once, so the export goes last. A
   league that is in the registry but not yet ingested is skipped with a warning (its Scout panel
   is empty, it is left out of the auction pool), never an error.

That's all: the league appears in the web app's league menu, the CLI / TUI / Streamlit pickers,
Scout, the auction pool, `GET /v1/leagues` and the refresh workflow's default list.

## Fields

| Field | Meaning |
|---|---|
| `key` | Collection id: lowercase letters, digits and `_`; can't end in a time-window suffix (`_last1y`, `_last3y`). |
| `name`, `short` | Display label and abbreviation. |
| `zips` | Cricsheet download file(s) under `https://cricsheet.org/downloads/`. |
| `gender`, `kind`, `country` | Descriptive; `country` is a region for mixed / international collections. |
| `order` | Display order everywhere (league menu, `collections.json`, pickers, Scout panels). |
| `tier` | A `[tiers.*]` key. Required for a Scout or auction pool. |
| `export` | Cooked into the site snapshot. Pools require it. |
| `active` | Still being played (descriptive for now). |
| `scout_pool`, `scout_group`, `scout_title`, `scout_subtitle` | A Scout panel. Exactly one `peers` pool, which must be the auction target; `scout_index.json` is keyed by tier, so two pools can't share one. |
| `draftable` | Players can be drafted from this panel into the Auction room (only those eligible for the auction). |
| `gem_pool` | The uncapped-gem board is drawn from this pool (at most one; SMAT). |
| `auction_pool` | Feeds the cross-league auction pool, its ratings translated onto the IPL (below). |
| `auction_target` | The competition the auction pool is priced for (exactly one when any pool exists; the IPL). |
| `auction_nationalities` | On the target only: the allow-list of free-agent nationalities (empty = every nation not excluded). |
| `auction_excluded_nationalities` | On the target only: the deny-list, which always wins (Pakistan for the IPL). |
| `[[league.era]]` | Optional, repeatable: `key` (lowercase letters and digits), `name`, `since` (ISO date). Each era is a stretch with its own scoring level, exported as one more recomputed leaderboard window (`era_<key>`, every match on or after `since`) next to "last year" and "last 3 years". The IPL has `impact` ("Impact Player era", since 2023-03-31). |

## Add an era

A rule change that moved scoring (the IPL's Impact Player, a new powerplay rule, a ball change) is
one table under its league:

```toml
[[league]]
key = "ipl"
# …
[[league.era]]
key = "impact"
name = "Impact Player era"
since = "2023-03-31"
```

Then re-export (`scripts/export_site.py -c <key>`): the exporter builds `balls_<key>_era_<era>` /
`matches_<key>_era_<era>`, runs every metric over it like the time windows, and lists it in that
league's `meta.json` (`windows`, `window_labels`), so the period selector on the site's Leaderboards,
the Streamlit Leaderboards page and the TUI's LEADERS tab offers it.
`python -m cricdex.leagues check` validates the entry; the eras are also in `leagues.json`. Eras
are display windows: the rating model doesn't need them, since it already fits a level per season.

## Tiers and translations

A rating is relative to its own league's average ball, so a +20 in SMAT isn't a +20 in the IPL. Each
league's rating is moved onto the IPL rating scale by a **translation fitted per league and per role**
(batter / bowler) on every player seen in both, `IPL rating ≈ a + b × league rating` with its own
translation sd, by `scripts/league_translation_fit.py` into `config/league_translation.json`
(read by `cricdex.scout.translation`; method and tests in [METHODOLOGY.md](METHODOLOGY.md) §6d). A
tier only names its **pooling `group`**: in the fit, a league's intercept and slope shrink toward its
group's mean (`india`: SMAT; `overseas_a`: BBL, SA20, PSL, ILT20, The Hundred; `overseas_b`: CPL, T20
Blast, MLC, BPL, LPL, Super Smash, CSA T20 Challenge; `reference`: the IPL), so a league with few
players who also reached the IPL borrows strength from similar leagues instead of copying one of their
numbers. After adding a league, refit: `uv run python scripts/league_translation_fit.py pairs` then
`fit` (about 15 minutes; the backtest cache needs its fits first,
`scripts/backtest_newcomers.py --leagues <key>`).

Until 2026-10-23 a tier carried one hand-set `discount` (SMAT 17, BBL / SA20 6, CPL / Blast 8.5; eight
leagues borrowed one of those), a guessed `translation_sd` and a `calibrated` flag; the loader now
refuses those keys. The export translates every rating (the pool's `value`, Scout's `ipl_value`), so
the web app and `web_parity/pricing.py` only ever price values already on the IPL scale.

## What ships today

`uv run python scripts/ingest_cricsheet.py list` prints the registry. Exported (the men's T20
product): IPL, SMAT (`indian_domestic_male`, from `sma_json.zip`), BBL, SA20, CPL, T20 Blast, PSL,
ILT20, The Hundred, MLC, BPL, LPL, Super Smash, CSA T20 Challenge, men's T20Is and "recently
played". In the registry but not exported yet: WPL, WBBL, The Hundred (women), women's T20Is,
recently played (women), men's and women's Tests and ODIs, and Cricsheet's `all` archive. They can
be ingested on request (`ingest_cricsheet.py all --include-unexported` ingests everything).

## Other registry files

`CRICDEX_LEAGUES=/path/to/leagues.toml` points every command at another registry, for example a
franchise group's own league list, without editing the repo copy. An installed `cricdex` package
carries a copy of the repo file.

## What is still competition-specific

The auction room itself models the IPL: the ten franchises, purse and squad rules, retentions,
"overseas" meaning not Indian, and the playing-time model (P(plays), fitted on IPL XIs). Those move into competition-rules
config in a later sprint; until then a different `auction_target` would price the pool for that
league but still run IPL auction rules.
