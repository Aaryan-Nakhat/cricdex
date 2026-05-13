"""Single-agent auction RL environment.

The RL franchise (slot 0) bids against N-1 Monte-Carlo opponent
franchises (parameterised aggression + risk-jitter, see
`auction.simulator`). State for the learner at each player-up-for-bid:

    own_purse_norm           (1)
    own_slots_left_norm      (1)
    own_role_need_norm[4]    (4)  # batter, bowler, all_rounder, keeper
    own_overseas_left_norm   (1)
    current_player_features  (7)  # role one-hot (4) + is_overseas (1)
                                  # + price_norm (1) + value_norm (1)
    opp_max_ceiling_norm     (1)  # strongest known competitor signal
    pool_remaining_norm      (1)
                             ----
                             16 dims

Action: discrete bid bucket, 0..N_BUCKETS-1. Index 0 = pass. Index k>=1
maps to bid = max(player.price, k * BUCKET_STEP * player.projected_value).
If chosen bid < second_ceiling among opponents, the agent loses the
player. If >= top opponent ceiling, agent wins at second_ceiling + 0.1.

Reward (shaped, per-round):
    +(projected_value - sale_price) when agent wins a player
    -illegal_action_penalty       when agent bids more than purse / role full
    0                              otherwise

Terminal: pool exhausted.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np
import polars as pl

from cricdex.auction.simulator import (
    DEFAULT_FRANCHISES,
    _bid_ceiling,
    _default_role_mins,
)

N_BUCKETS = 11  # 0=pass, 1..10 → bid at k * 0.3 * projected_value
BUCKET_STEP = 0.3
STATE_DIM = 16
ROLES = ("batter", "bowler", "all_rounder", "keeper")
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}


@dataclass
class FranchiseState:
    id: str
    purse: float
    slots_left: int
    need: dict
    overseas_left: int
    aggression: float
    risk: float
    roster: list = field(default_factory=list)


class AuctionEnv:
    def __init__(
        self,
        pool: pl.DataFrame,
        n_franchises: int = 4,
        learner_slot: int = 0,
        purse: float = 90.0,
        seed: int = 0,
    ) -> None:
        self.pool = pool
        self.n_franchises = n_franchises
        self.learner_slot = learner_slot
        self.purse = purse
        self.rng = random.Random(seed)

    def reset(self) -> np.ndarray:
        self.players = self.pool.to_dicts()
        self.rng.shuffle(self.players)
        self.state_idx = 0
        self.franchises: list[FranchiseState] = []
        for i in range(self.n_franchises):
            base = DEFAULT_FRANCHISES[i % len(DEFAULT_FRANCHISES)]
            self.franchises.append(
                FranchiseState(
                    id=f"F{i + 1}",
                    purse=self.purse,
                    slots_left=11,
                    need=dict(_default_role_mins()),
                    overseas_left=8,
                    aggression=base["aggression"],
                    risk=base["risk"],
                )
            )
        return self._obs()

    def _current_player(self) -> dict | None:
        if self.state_idx >= len(self.players):
            return None
        return self.players[self.state_idx]

    def _obs(self) -> np.ndarray:
        p = self._current_player()
        me = self.franchises[self.learner_slot]
        if p is None:
            return np.zeros(STATE_DIM, dtype=np.float32)
        role_oh = np.zeros(4, dtype=np.float32)
        role_oh[ROLE_IDX.get(p["role"], 0)] = 1.0
        opp_max = max(
            (
                _bid_ceiling(
                    {
                        "slots_left": f.slots_left,
                        "need": f.need,
                        "overseas_left": f.overseas_left,
                        "purse": f.purse,
                        "aggression": f.aggression,
                        "risk": f.risk,
                    },
                    p,
                    self.rng,
                )
                for i, f in enumerate(self.franchises)
                if i != self.learner_slot
            ),
            default=0.0,
        )
        own_needs = np.array([me.need.get(r, 0) / 5.0 for r in ROLES], dtype=np.float32)
        return np.concatenate(
            [
                np.array([me.purse / self.purse], dtype=np.float32),
                np.array([me.slots_left / 11.0], dtype=np.float32),
                own_needs,
                np.array([me.overseas_left / 8.0], dtype=np.float32),
                role_oh,
                np.array([float(p["is_overseas"])], dtype=np.float32),
                np.array([p["price"] / 20.0], dtype=np.float32),
                np.array([p["projected_value"] / 10.0], dtype=np.float32),
                np.array([opp_max / 20.0], dtype=np.float32),
                np.array(
                    [(len(self.players) - self.state_idx) / max(len(self.players), 1)],
                    dtype=np.float32,
                ),
            ]
        )

    def step(self, action: int) -> tuple[np.ndarray, float, bool, dict]:
        p = self._current_player()
        if p is None:
            return self._obs(), 0.0, True, {}
        me = self.franchises[self.learner_slot]

        # learner bid from bucket
        if action == 0:
            learner_bid = 0.0
        else:
            learner_bid = max(p["price"], float(action) * BUCKET_STEP * p["projected_value"])
        learner_legal = learner_bid <= me.purse
        if not learner_legal:
            learner_bid = 0.0

        # opponent ceilings
        opp_ceilings: list[tuple[float, int]] = []
        for i, f in enumerate(self.franchises):
            if i == self.learner_slot:
                continue
            ceil = _bid_ceiling(
                {
                    "slots_left": f.slots_left,
                    "need": f.need,
                    "overseas_left": f.overseas_left,
                    "purse": f.purse,
                    "aggression": f.aggression,
                    "risk": f.risk,
                },
                p,
                self.rng,
            )
            opp_ceilings.append((ceil, i))
        opp_ceilings.sort(reverse=True)
        top_opp_ceil = opp_ceilings[0][0] if opp_ceilings else 0.0
        second_opp_ceil = opp_ceilings[1][0] if len(opp_ceilings) > 1 else p["price"]

        reward = 0.0
        if learner_bid >= max(top_opp_ceil, p["price"]):
            # learner wins
            sale = round(max(p["price"], top_opp_ceil + 0.1), 2)
            sale = min(sale, learner_bid)
            me.purse -= sale
            me.slots_left -= 1
            me.roster.append(p["name"])
            if p["is_overseas"]:
                me.overseas_left -= 1
            if me.need.get(p["role"], 0) > 0:
                me.need[p["role"]] -= 1
            reward = float(p["projected_value"]) - sale
            if not learner_legal:
                reward -= 5.0  # penalty for impossible bid (still gets player but punished)
        else:
            # opponent wins (or unsold) — simulate sale among opponents
            if top_opp_ceil >= p["price"]:
                winner = self.franchises[opp_ceilings[0][1]]
                sale = round(max(p["price"], max(second_opp_ceil, learner_bid) + 0.1), 2)
                sale = min(sale, top_opp_ceil)
                winner.purse -= sale
                winner.slots_left -= 1
                if p["is_overseas"]:
                    winner.overseas_left -= 1
                if winner.need.get(p["role"], 0) > 0:
                    winner.need[p["role"]] -= 1

        self.state_idx += 1
        done = self.state_idx >= len(self.players)
        return self._obs(), reward, done, {}
