# web_parity

The Python twin of the website's Scout and Auction logic. The React site computes the Scout look-alikes
and the auction Monte-Carlo in the browser (TypeScript); the CLI, TUI and Streamlit are Python. This
package reads **the same exported JSON** and applies **the same algorithms, constants and seeded RNG**,
so every surface shows identical results, trial for trial.

| File | Mirrors | What's in it |
|---|---|---|
| `loader.py` | `site/src/lib/data.ts` | `load_auction_pool`, `load_retentions`, `load_scout_index`, `load_activity_index`, `load_keep`: read `site/public/data/<collection>/*.json` (written by `scripts/export_site.py`) |
| `pricing.py` | `site/src/lib/auction.ts` | `est_value` (skill → crore: `1.1 × e^(0.95 × value) × role weight`, clamped 0.3–27), `price_tier` (base-price bands), `TIER_PENALTY` (per-league discount) |
| `scout.py` | `site/src/lib/scout.ts` | `similar_to` (same role, seam/spin for bowlers, similarity `1 − Δz / 2.5`), `gem_threshold` / `is_gem` |
| `keep.py` | `site/src/lib/keep.ts` | Keep or release: `assess` (price on the pool's curve vs salary → Keep / Release / Borderline + reason), `market_for` (free agents + other teams' release calls), `evaluate` (purse left, slots, role gaps filled cheapest-first, warnings), `to_csv_rows`; locked by `test_scripts/test_keep_parity.py` |
| `auction.py` | `site/src/lib/auction.ts` | `build_pool`, `ARCHETYPES`, `IPL_TEAMS_DEFAULT`, `default_retentions`, `simulate_auction` (retentions, budget-aware bidding, second-price clearing within each team's purse, two-phase fill, ~300 seeded trials) |
| `bidplan.py` | `site/src/lib/bidplan.ts` | Bid plan: `build_context` (Keep or release's plans, places opened, the pool or an official register), `rival_prices` (the simulator's rivals → price to beat per run), `strength` / `best_xi`, `plan` (the λ bidding rule, max bids, fallback chains, the likely squad), `to_csv_rows`; `follow_plan` (Python only, for `scripts/bidplan_backtest.py`); locked by `test_scripts/test_bidplan_parity.py` |

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
