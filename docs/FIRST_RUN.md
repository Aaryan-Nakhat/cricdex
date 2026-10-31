# First-run onboarding

Path from zero to running queries.

---

## 1. Install (clone + uv)

```bash
git clone git@github.com:Aaryan-Nakhat/cricdesk.git
cd cricdesk
uv sync --extra ui      # CLI + TUI are in the base install; `ui` adds the Streamlit dashboard
uv run cricdesk --help
```

The repo already ships the exported data for every exported league (`site/public/data/`; the list is `config/leagues.toml`), so
`leaderboard`, `matchups`, `phase`, `form`, `partnerships`, `aging`, `scout`, `auction`, the TUI's
read-only tabs and the dashboard work straight after the clone. The CLI `profile`, `compare`,
`records` and `venues` commands and the REST API query the local DuckDB (`data/`), and the
Head-to-head tab/page reads the local Bayes ratings, so those need step 3 first.

## 2. Initialise (optional)

```bash
cricdesk init
```

Creates `~/.cricdesk/` with a `config.toml` (chmod 600 on macOS / Linux) and prompts for an LLM
model + key — optional, any provider via LiteLLM, used only for the player-taxonomy enrichment.
When you run from the cloned repo, data always stays in the repo's `data/` folder (set
`CRICDESK_DATA_DIR` to put it elsewhere).

## 3. Pull fresh data

```bash
cricdesk data ingest cricsheet -c ipl     # IPL ball-by-ball from Cricsheet (a few MB)
cricdesk data ingest ratings -c ipl       # Bayesian scout skills
cricdesk data ingest metrics -c ipl       # all leaderboards + rebuilds the site data
```

`cricsheet` and `ratings` skip a collection that's already loaded — pass `--force` to
re-download / refit. `metrics` always recomputes, then rebuilds that collection's site data so
every command reads the new numbers.

Check what landed:

```bash
cricdesk data status
```

## 4. First queries

```bash
cricdesk leaderboard ngi -c ipl --top 15
cricdesk profile "V Kohli"
cricdesk compare "V Kohli" "RG Sharma"
cricdesk records today
cricdesk scout look-alikes "V Kohli"          # IPL players; --pos opener|…|tailender, -k 8
cricdesk auction room --mode mega             # IPL; --purse / --trials / --squad-size
```

## 5. Browser preference?

```bash
cricdesk dashboard         # opens Streamlit on a free local port (prints the URL; needs --extra ui)
```

Same data, same artifacts. No drift.

## 6. Returning user

A few weeks later:

```bash
cricdesk data status                             # what's still fresh
cricdesk data ingest cricsheet --force -c ipl    # pull the latest matches
cricdesk data ingest metrics -c ipl              # recompute leaderboards + site data
cricdesk leaderboard ngi -c ipl --top 25         # see what's new
```

Or just jump back into the dashboard / TUI:

```bash
cricdesk dashboard
cricdesk                   # bare `cricdesk` opens the TUI
```
