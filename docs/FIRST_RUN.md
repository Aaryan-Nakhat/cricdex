# First-run onboarding

Path from zero to running queries.

---

## 1. Install (clone + uv)

```bash
git clone git@github.com:Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync --extra cli --extra ui   # CLI/TUI + Streamlit dashboard
uv run cricdex --help
```

## 2. Initialise

```bash
cricdex init
```

Creates `~/.cricdex/`, prompts for the Gemini key (optional — used for the
player-taxonomy enrichment; skip if you only want metrics / scout /
auction). Writes `~/.cricdex/config.toml` (chmod 600).

## 3. Pull data

```bash
cricdex data ingest cricsheet -c ipl     # ~600 MB ball-by-ball
cricdex data ingest ratings -c ipl       # Bayesian scout skills
cricdex data ingest metrics -c ipl       # all leaderboards
```

Each command skips if its output exists — pass `--force` to
regenerate.

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
cricdex scout look-alikes "V Kohli" -c ipl
cricdex auction room -c ipl
```

## 5. Browser preference?

```bash
cricdex dashboard         # opens Streamlit on :8501
```

Same data, same artifacts. No drift.

## 6. Returning user

A few weeks later:

```bash
cricdex data status                       # what's still fresh
cricdex data ingest cricsheet --force -c ipl   # pull latest balls
cricdex data ingest metrics --force -c ipl     # recompute leaderboards
cricdex leaderboard ngi -c ipl --top 25        # see what's new
```

Or just jump back into the dashboard / TUI:

```bash
cricdex dashboard
cricdex tui
```
