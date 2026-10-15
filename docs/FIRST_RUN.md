# First-run onboarding

Path from zero to running queries.

---

## 1. Install (clone + uv)

```bash
git clone git@github.com:Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync --extra ui      # CLI + TUI are in the base install; `ui` adds the Streamlit dashboard
uv run cricdex --help
```

The repo already ships the exported data for all 8 collections (`site/public/data/`), so
`leaderboard`, `matchups`, `phase`, `form`, `partnerships`, `aging`, `scout`, `auction`, the TUI's
read-only tabs and the dashboard work straight after the clone. The CLI `profile`, `compare`,
`records` and `venues` commands and the REST API query the local DuckDB (`data/`), and the
Head-to-head tab/page reads the local Bayes ratings, so those need step 3 first.

## 2. Initialise (optional)

```bash
cricdex init
```

Creates `~/.cricdex/` with a `config.toml` (chmod 600 on macOS / Linux) and prompts for an LLM
model + key — optional, any provider via LiteLLM, used only for the player-taxonomy enrichment.
When you run from the cloned repo, data always stays in the repo's `data/` folder (set
`CRICDEX_DATA_DIR` to put it elsewhere).

## 3. Pull fresh data

```bash
cricdex data ingest cricsheet -c ipl     # IPL ball-by-ball from Cricsheet (a few MB)
cricdex data ingest ratings -c ipl       # Bayesian scout skills
cricdex data ingest metrics -c ipl       # all leaderboards + rebuilds the site data
```

`cricsheet` and `ratings` skip a collection that's already loaded — pass `--force` to
re-download / refit. `metrics` always recomputes, then rebuilds that collection's site data so
every command reads the new numbers.

Check what landed:

```bash
cricdex data status
```

## 4. First queries

```bash
cricdex leaderboard ngi -c ipl --top 15
cricdex profile "V Kohli"
cricdex compare "V Kohli" "RG Sharma"
cricdex records today
cricdex scout look-alikes "V Kohli"          # IPL players; --pos opener|…|tailender, -k 8
cricdex auction room --mode mega             # IPL; --purse / --trials / --squad-size
```

## 5. Browser preference?

```bash
cricdex dashboard         # opens Streamlit on a free local port (prints the URL; needs --extra ui)
```

Same data, same artifacts. No drift.

## 6. Returning user

A few weeks later:

```bash
cricdex data status                             # what's still fresh
cricdex data ingest cricsheet --force -c ipl    # pull the latest matches
cricdex data ingest metrics -c ipl              # recompute leaderboards + site data
cricdex leaderboard ngi -c ipl --top 25         # see what's new
```

Or just jump back into the dashboard / TUI:

```bash
cricdex dashboard
cricdex                   # bare `cricdex` opens the TUI
```
