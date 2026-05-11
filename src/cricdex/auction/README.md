# auction

Multi-agent RL IPL auction simulator.

## Pipeline

1. `personality.py` — per-franchise YAML extracted via Gemini Pro from 10 yr bid history.
2. `env.py` — PettingZoo multi-agent env; state = (purse, slots, pool, current player); reward = realized squad NGI − overspend penalty; constraints via OR-Tools.
3. `simulator.py` — SB3 PPO self-play training + inference.

## Ship window

Oct/Nov 2026 pre-auction. Marketing blitz auction-week.
