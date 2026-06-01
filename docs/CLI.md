# CricDex CLI reference

`cricdex` is the one console entry point — available after `uv sync`
(run as `uv run cricdex …`, or inside the activated venv).

```
cricdex                          show help
cricdex --version / -V           print version
cricdex --help / -h              top-level help
cricdex <subcommand> --help      per-subcommand help
```

Exit codes:

| code | meaning |
|---|---|
| 0 | success |
| 1 | user error (bad arguments / missing argument) |
| 2 | missing data (run `cricdex data ingest …` first) |
| 3 | missing credential (run `cricdex config set …`) |

---

## init

```
cricdex init
```

First-run wizard. Creates `$CRICDEX_HOME` (default `~/.cricdex/`),
prompts for the Gemini key (required for rules Q&A) and Jina key
(optional rerank), prints the next-step commands. Idempotent.

---

## config

```
cricdex config path
cricdex config get [KEY]
cricdex config set KEY VALUE
cricdex config unset KEY
cricdex config edit
```

Stored at `$CRICDEX_HOME/config.toml`, chmod 600. Allowed keys:
`gemini_api_key`, `gemini_tmp_url`, `gemini_tmp_api_key`,
`jina_api_key`, `qdrant_url`, `neo4j_uri`, `neo4j_user`,
`neo4j_password`.

Env vars override the file (e.g., `GEMINI_API_KEY=… cricdex rules ask …`).

---

## data

```
cricdex data status
cricdex data ingest <slice> [-c <collection>] [--force]
```

Slices: `cricsheet`, `rules`, `ratings`, `metrics`, `graph`.
Every ingest skips its output if it already exists — pass `--force`
to regenerate. `status` prints a table of every artifact + size +
last-updated.

---

## leaderboard

```
cricdex leaderboard <metric> [-c <collection>] [--top 25] [--json]
```

Metrics: `ngi`, `pressure_runs`, `intent_curve`, `dot_ball_recovery`,
`counter_attack`, `boundary_dependency`, `pressure_conversion`,
`wicket_quality`, `crease_longevity`, `slow_start_cost`. Reads
`$CRICDEX_HOME/data/metrics/<metric>_<collection>.json` — emit it
via `cricdex data ingest metrics` first.

---

## profile / compare / records / venues

```
cricdex profile "V Kohli" [-c ipl]
cricdex compare "V Kohli" "RG Sharma"
cricdex records today                        # on-this-day
cricdex records list                         # list record keys
cricdex records career_run_leaders --top-n 25
cricdex venues "Wankhede"
```

---

## rules

```
cricdex rules ask "what is the impact player rule" --formats ipl
```

Citation-grounded Q&A. Needs `gemini_api_key` (or the legacy
`gemini_tmp_url` proxy). Returns the answer + a list of cited
source clauses.

---

## scout

```
cricdex scout twins "V Kohli" --mode co_faced -k 10
cricdex scout twins "MS Dhoni" --mode teammates -k 10
cricdex scout find-replacement "JJ Bumrah" --role bowler \
    --max-balls-bowled 2000 --min-last-match 2023-01-01 -k 10
```

Graph-traversal player similarity over the populated scout Neo4j
graph. Needs `cricdex data ingest graph -c <collection>` first.

---

## auction

```
cricdex auction solve [--pool real|synthetic|<csv>] [--purse 120]
cricdex auction recommend "JJ Bumrah" --budget 8 --role bowler -n 5
cricdex auction simulate --n-sims 200 --top-n 20
cricdex auction train-grpo --pool real --epochs 8000 \
    --group-size 16 --diverse-franchises
```

MILP squad picker, war-room substitute advisor (composite of graph
similarity + Bayes value + budget), Monte-Carlo price-band sim,
GRPO RL policy trainer. `train-grpo` writes
`$CRICDEX_HOME/data/auction/policy.zip`.

---

## dashboard

```
cricdex dashboard
```

Launches the Streamlit dashboard on `http://localhost:8501`.
Streamlit reads the same `$CRICDEX_HOME/data/` so it's always in
sync with the CLI.

---

## tui

```
cricdex tui
```

Full Textual TUI for interactive browsing. Requires the `cli`
extra: `uv sync --extra cli`.
