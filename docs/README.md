# CricDesk docs

*The numbers behind cricket, honestly modelled.* Live site: https://aaryan-nakhat.github.io/cricdesk/

## Start here

- [FIRST_RUN.md](FIRST_RUN.md) — from clone to your first query in a few commands.
- [RUNNING.md](RUNNING.md) — the two ways to run it (Docker or local `uv`), pipelines, environment variables.
- [CLI.md](CLI.md) — every `cricdesk` command and flag, plus the TUI and dashboard.

## How it works

- [METHODOLOGY.md](METHODOLOGY.md) — every model in plain English, with worked examples, the backtest and the honest limits. Read this first.
- [METRICS.md](METRICS.md) — exact formulas, filters and output columns for NGI, the twelve context metrics and the fielding boards.
- [SCOUT.md](SCOUT.md) — the scout module: tiers, the rating pipeline, cross-league look-alikes.
- [AUCTION_MATH.md](AUCTION_MATH.md) — the auction room step by step, from skill to crore to who wins the bidding.
- [IDENTITY.md](IDENTITY.md) — one id per player: match registries, the People Register, Wikidata and the taxonomy.
- [STUDY_GUIDE.md](STUDY_GUIDE.md) — the deep technical tour: model code, design choices, surfaces, CI.

## Reference

- [PIPELINE.md](PIPELINE.md) — the rebuild steps in order (`python -m cricdesk.pipeline`), resuming, and which steps refit a model.
- [ARCHITECTURE.md](ARCHITECTURE.md) — the pipeline end to end, the layers, what reads what, how it ships.
- [LEAGUES.md](LEAGUES.md) — the league registry (`config/leagues.toml`): every field, tiers and their fitted translations, and how to add a league with one entry.
- Competition rules (`config/competitions.toml`): one entry per auction / retention cycle (purse, squad limits, deadline), each rule sourced or marked assumed; read by Keep or release ([METHODOLOGY §10](METHODOLOGY.md#10-keep-or-release)). The field list is the comment at the top of the file.
- [API.md](API.md) — the FastAPI REST endpoints, with curl examples.
- [DOCKER.md](DOCKER.md) — the image and Compose layout, and why it's built that way.
- Module READMEs: [`metrics`](../src/cricdesk/metrics/README.md), [`scout/ratings`](../src/cricdesk/scout/ratings/README.md), [`web_parity`](../src/cricdesk/web_parity/README.md), [`auction`](../src/cricdesk/auction/README.md), [`scripts`](../scripts/README.md).

## Project

- [ROADMAP.md](ROADMAP.md) — shipped, next, later, and out of scope.
- [CHANGELOG.md](CHANGELOG.md) — what changed, release by release.
- [DECISIONS.md](DECISIONS.md) — the design log: dated choices and why (some since reversed).
