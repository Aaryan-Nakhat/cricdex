# web_parity

The Python twin of the website's Scout and Auction logic. The React site computes the Scout look-alikes
and the auction Monte-Carlo in the browser (TypeScript); the CLI, TUI and Streamlit are Python. This
package reads **the same exported JSON** and applies **the same algorithms, constants and seeded RNG**,
so every surface shows identical results, trial for trial.

| File | Mirrors | What's in it |
|---|---|---|
| `loader.py` | `site/src/lib/data.ts` | `load_auction_pool`, `load_retentions`, `load_scout_index`, `load_activity_index`, `load_keep`: read `site/public/data/<collection>/*.json` (written by `scripts/export_site.py`) |
| `pricing.py` | `site/src/lib/auction.ts` | `est_value` (on-field worth, skill → crore: `4.03 × e^(0.0743 × (value − 0.5 × value_sd))`, from 0.3 cr up to a ceiling that rises with IPL balls, 13.5–27 cr), `price_tier` (base-price bands), `market_price` / `market_features` (the market price fitted to real IPL auctions, `config/price_model.json`; `value_input` picks the value it reads); a rating from another league comes in already translated (`scout/translation.py`; the per-league `TIER_PENALTY` was removed 2026-10-23) |
| `scout.py` | `site/src/lib/scout.ts` | `similar_to` (same role, seam/spin for bowlers, similarity `1 − Δz / 2.5`), `gem_threshold` / `is_gem` |
| `keep.py` | `site/src/lib/keep.ts` | Keep or release: `assess` (price on the pool's curve vs salary → Keep / Release / Borderline + reason), `market_for` (free agents + other teams' release calls), `evaluate` (purse left, slots, role gaps filled cheapest-first, warnings), `to_csv_rows`; locked by `test_scripts/test_keep_parity.py` |
| `auction.py` | `site/src/lib/auction.ts` | `build_pool`, `IPL_TEAMS_DEFAULT`, `default_retentions`, `auction_lots` (lots per open place, as real shortlists), `lot_sequence` (capped sets first), `DEMAND` (the fitted demand model, `config/auction_demand.json`), `ladder_next` (IPL bid increments), `simulate_auction` (retentions, every team bidding by the demand model within its purse, ladder clearing, an accelerated round, ~300 seeded trials) |
| `bidplan.py` | `site/src/lib/bidplan.ts` | Bid plan: `build_context` (Keep or release's plans, places opened, the pool or an official register), `rival_runs` / `rival_prices` (the simulator's rivals → price to beat per run, and the market's runs per crore: what the rivals' buys added to their squads ÷ what they paid, the value of an unspent crore), `strength` / `best_xi` / `bench_fill`, `plan` (the bidding rule: a crore worth what the later lots can still buy, `_MoneyValue`; `money=` picks the older rules for the replays; max bids, fallback chains, the likely squad), `to_csv_rows`; `buy_p` / `lot_p` (P(plays) of a lot once bought, used when keep.json carries a `buy_model`), `rival_plan_bids` / `_apply_rival_plans` (the other franchises' own plans, used when the export writes `bidplan_rivals.json`; both off since 2026-10-27, ROADMAP I18); `follow_plan` (Python only, for `scripts/bidplan_backtest.py`); locked by `test_scripts/test_bidplan_parity.py` |

## Use it

```bash
uv run cricdex scout look-alikes "V Kohli"
uv run cricdex auction room --mode mega --trials 300
```

```python
from cricdex.web_parity import build_pool, load_auction_pool, load_retentions, simulate_auction
```

## Keeping it identical

`test_scripts/test_web_parity.py` runs the TypeScript under Node and the Python here on the same inputs
and asserts the outputs match (including the LCG random sequence). It runs in CI, so change a constant
or a formula in **both** files in the same commit. The head-to-head engine has the same arrangement
(`scout/ratings/head_to_head.py` ⇄ `site/src/lib/headtohead.ts`, `test_scripts/test_h2h_parity.py`).

How the models work, in plain English: [`docs/METHODOLOGY.md` §5–7](../../../docs/METHODOLOGY.md#5-scout-look-alikes).
The auction step by step: [`docs/AUCTION_MATH.md`](../../../docs/AUCTION_MATH.md).
