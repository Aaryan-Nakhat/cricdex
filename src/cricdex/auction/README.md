# auction

IPL auction tooling — three complementary entry points sharing one
synthetic player pool generator (`solver.sample_pool`):

## Pipeline

1. `solver.py` — MILP squad optimiser via `scipy.optimize.milp`. Best
   single squad under purse, role-min, and overseas-cap constraints.
2. `simulator.py` — Monte-Carlo auction over N runs. Each franchise is
   a parameterised agent (purse, aggression, risk-jitter). Emits the
   realised-price distribution per player (min / p25 / median / p75 /
   max / sold-pct) plus a bid-probability sweep.
3. `real_pool.py` — real 429-player IPL pool (Bayes-skill projected
   value, normalised country codes, role from balls + ratings, manual
   collision overrides) + 6 `FRANCHISE_ARCHETYPES`.
4. `rl_env.py` — single-agent Gym-style env where slot 0 is the RL
   learner and the other N-1 franchises are MC opponents or one of
   the real-pool archetypes. 16-dim state, 11 discrete bid buckets,
   per-round shaped reward + terminal squad-quality bonus
   (`TERMINAL_VALUE_COEF * sum(projected_value)` minus
   `ROLE_UNFILL_PENALTY * unmet role minima`).
5. `grpo.py` — GRPO (Group Relative Policy Optimization, DeepSeek
   2024) trainer. No value head — group-relative advantage is the
   z-scored episode return across G rollouts from the same starting
   state. Saves a `policy.zip` (state-dict + meta), reloadable on CPU.
6. `advisor.py` — war-room substitute advisor. Joins graph
   `find_replacement` cohort onto the real_pool, filters by budget
   and role, scores composite of `shared_norm` + `value_norm`.
7. `scripts/train_auction_grpo.py` + `scripts/auction_advisor.py` —
   CLI fronts.

## Ship window

Oct/Nov 2026 pre-auction. Marketing blitz auction-week.

## Personality + PettingZoo

Per-franchise YAML extracted via Gemini from 10 yr bid history is
deferred (see `docs/DEFERRED.md`). The current MC opponent profiles
(`simulator.DEFAULT_FRANCHISES`) are uniform mid-aggression / mid-risk
agents — good enough for v1 RL training while the personality
extractor and full PettingZoo multi-agent self-play remain on the
year-2 roadmap.
