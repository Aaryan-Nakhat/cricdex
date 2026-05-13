"""GRPO self-play trainer for the auction RL env.

GRPO (Group Relative Policy Optimization, DeepSeek 2024) drops the value
head of PPO and instead computes a group-relative advantage by sampling
G trajectories from the same starting state and z-scoring their returns:

    advantage_i = (R_i - mean(R_group)) / (std(R_group) + eps)

Loss:

    L = - E[ adv * log_prob(action) ] - beta * H(policy)

Clipping (ratio = exp(logp - logp_old)) is included so the policy
update stays within a trust region.

Why GRPO over PPO here
----------------------
- Auction reward is sparse and terminal-ish (per-round shaped reward,
  but mostly the squad-quality signal lands at episode end).
- Value head on a single rare reward signal is hard to fit; group
  z-score is a direct, low-variance baseline.
- ~30% fewer params + 1× fewer forward passes per step than PPO.

Output
------
`policy.zip` — torch state-dict + a small metadata JSON (state_dim,
n_actions, training stats). Loadable via `load_policy(path)`.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from cricdex.auction.rl_env import N_BUCKETS, STATE_DIM, AuctionEnv


class PolicyMLP(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_actions: int = N_BUCKETS, hidden: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
            nn.Linear(hidden, n_actions),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    @torch.no_grad()
    def act(self, obs: np.ndarray, greedy: bool = False) -> int:
        x = torch.from_numpy(obs).float().unsqueeze(0)
        logits = self(x).squeeze(0)
        if greedy:
            return int(torch.argmax(logits).item())
        return int(torch.distributions.Categorical(logits=logits).sample().item())


def _rollout(env: AuctionEnv, policy: PolicyMLP, deterministic: bool = False):
    obs = env.reset()
    obs_buf, act_buf, logp_buf, rew_buf = [], [], [], []
    done = False
    while not done:
        x = torch.from_numpy(obs).float().unsqueeze(0)
        logits = policy(x).squeeze(0)
        dist = torch.distributions.Categorical(logits=logits)
        a = torch.argmax(logits) if deterministic else dist.sample()
        logp = dist.log_prob(a)
        next_obs, r, done, _ = env.step(int(a.item()))
        obs_buf.append(obs)
        act_buf.append(int(a.item()))
        logp_buf.append(float(logp.item()))
        rew_buf.append(r)
        obs = next_obs
    return (
        np.array(obs_buf, dtype=np.float32),
        np.array(act_buf, dtype=np.int64),
        np.array(logp_buf, dtype=np.float32),
        np.array(rew_buf, dtype=np.float32),
    )


def train(
    pool,
    epochs: int = 200,
    group_size: int = 8,
    lr: float = 3e-4,
    entropy_beta: float = 0.01,
    clip_eps: float = 0.2,
    seed: int = 42,
    n_franchises: int = 4,
    purse: float = 90.0,
    out_path: Path | str = "auction_policy.pt",
    verbose: bool = True,
    franchises: list[dict] | None = None,
) -> dict:
    torch.manual_seed(seed)
    np.random.seed(seed)
    policy = PolicyMLP()
    optim = torch.optim.Adam(policy.parameters(), lr=lr)

    history: list[dict] = []
    for epoch in range(epochs):
        env = AuctionEnv(
            pool,
            n_franchises=n_franchises,
            purse=purse,
            seed=seed + epoch,
            franchises=franchises,
        )
        group_obs, group_act, group_logp, group_R = [], [], [], []
        for _ in range(group_size):
            obs, act, logp, rew = _rollout(env, policy)
            group_obs.append(obs)
            group_act.append(act)
            group_logp.append(logp)
            group_R.append(float(rew.sum()))
        R = np.array(group_R, dtype=np.float32)
        adv = (R - R.mean()) / (R.std() + 1e-6)

        # broadcast advantage over each trajectory's steps
        flat_obs = np.concatenate(group_obs, axis=0)
        flat_act = np.concatenate(group_act, axis=0)
        flat_old_logp = np.concatenate(group_logp, axis=0)
        flat_adv = np.concatenate(
            [np.full(len(o), adv[i], dtype=np.float32) for i, o in enumerate(group_obs)]
        )

        x = torch.from_numpy(flat_obs)
        a = torch.from_numpy(flat_act)
        old_logp = torch.from_numpy(flat_old_logp)
        adv_t = torch.from_numpy(flat_adv)

        # one PPO-style clipped update per epoch (keeps it cheap on CPU)
        logits = policy(x)
        dist = torch.distributions.Categorical(logits=logits)
        logp = dist.log_prob(a)
        ratio = torch.exp(logp - old_logp)
        unclipped = ratio * adv_t
        clipped = torch.clamp(ratio, 1 - clip_eps, 1 + clip_eps) * adv_t
        policy_loss = -torch.min(unclipped, clipped).mean()
        entropy = dist.entropy().mean()
        loss = policy_loss - entropy_beta * entropy

        optim.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(policy.parameters(), 0.5)
        optim.step()

        history.append(
            {
                "epoch": epoch,
                "mean_return": float(R.mean()),
                "std_return": float(R.std()),
                "policy_loss": float(policy_loss.item()),
                "entropy": float(entropy.item()),
            }
        )
        if verbose and epoch % max(1, epochs // 10) == 0:
            print(
                f"epoch {epoch:4d} | meanR {R.mean():7.2f} | stdR {R.std():6.2f} | "
                f"H {entropy.item():.3f} | loss {policy_loss.item():.4f}"
            )

    save_policy(policy, history, out_path)
    return {"history": history, "out_path": str(out_path)}


def save_policy(policy: PolicyMLP, history: list[dict], path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    torch.save(policy.state_dict(), buf)
    meta = {
        "state_dim": STATE_DIM,
        "n_actions": N_BUCKETS,
        "history_tail": history[-10:],
        "epochs": len(history),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("policy.pt", buf.getvalue())
        zf.writestr("meta.json", json.dumps(meta, indent=2))


def load_policy(path: Path | str) -> PolicyMLP:
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zf:
        with zf.open("policy.pt") as fp:
            state = torch.load(BytesIO(fp.read()), map_location="cpu", weights_only=True)
    model = PolicyMLP()
    model.load_state_dict(state)
    model.eval()
    return model
