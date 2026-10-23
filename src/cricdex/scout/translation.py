"""League translations: a rating in another league, on the IPL rating's scale, and the blend of a
player's leagues (docs/METHODOLOGY.md §6d).

Fitted by `scripts/league_translation_fit.py` into `config/league_translation.json`: per league and
per role (batter / bowler),

    IPL rating ≈ a + b · (league rating),   translation sd `tsd`,   posterior covariance `cov` of (a, b)

from every player seen in both (time-matched, selection on the rating handled by regressing on it,
leagues pooled hierarchically within their `[tiers.*] group` of config/leagues.toml). A translated
rating is a Gaussian on the IPL rating scale:

    mean = a + b x,    var = b² sd_x² + tsd² + [1 x] cov [1 x]ᵀ

and a player's sources (his IPL rating and every translated league rating) are combined by precision
(`combine`). This replaced the hand-set per-league discounts, the guessed translation sd and the
300-ball switch on 2026-10-23 (audit item 5).

Lookup order for the model: `$CRICDEX_TRANSLATION` → `<repo>/config/league_translation.json` → the
copy shipped inside the package (`cricdex/scout/league_translation.json`).
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

from cricdex import leagues

ROLES = ("batter", "bowler")
_PATHS = (
    Path(__file__).resolve().parents[3] / "config" / "league_translation.json",
    Path(__file__).resolve().parent / "league_translation.json",
)


@lru_cache(maxsize=4)
def load_model(path: str | None = None) -> dict:
    """The fitted translation model ($CRICDEX_TRANSLATION, else config/league_translation.json, else
    the package copy). Raises FileNotFoundError when there is none: a league rating is never moved
    onto the IPL by a made-up number."""
    cands = [Path(path)] if path else []
    env = os.environ.get("CRICDEX_TRANSLATION")
    if env:
        cands.append(Path(env))
    cands += list(_PATHS)
    for p in cands:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "no league translation model: run `uv run python scripts/league_translation_fit.py fit`"
    )


def table(col: str, role: str, model: dict | None = None, which: str = "roles") -> dict | None:
    """The translation row {a, b, tsd, cov, …} of a league and role (`role` "batter" | "bowler";
    `which` = "roles" for the shipped fit, "roles_le2024" for the one backtests of 2025+ use).
    None for the auction target (its ratings need no translation). A league in the registry with
    no fitted row (added after the fit) takes its pooling group's typical league."""
    if leagues.get(col).auction_target:
        return None
    m = (model or load_model())[which][role]
    row = m["leagues"].get(col)
    if row is None:
        reg = leagues.load()
        group = reg.tiers[leagues.get(col).tier].group
        row = m["groups"].get(group)
        if row is None:
            raise KeyError(f"no translation for {col!r} ({role}) and none for its group {group!r}")
    return row


def translate_parts(t: dict, value: float, sd: float | None) -> tuple[float, float, float]:
    """(mean, the variance of his own rating and of the fitted line, the translation variance) on the
    IPL rating scale of a league rating `value` (its sd) through row `t`. The first variance is
    independent from league to league; the translation variance (`tsd²`: how far a player's IPL level
    sits from what his league numbers imply) is his own, shared by all his leagues."""
    s = sd if isinstance(sd, int | float) and math.isfinite(sd) else 0.0
    a, b, tsd = float(t["a"]), float(t["b"]), float(t["tsd"])
    c = t.get("cov") or [[0.0, 0.0], [0.0, 0.0]]
    par = c[0][0] + 2 * value * c[0][1] + value * value * c[1][1]
    return a + b * value, (b * s) ** 2 + max(par, 0.0), tsd**2


def translate_row(t: dict, value: float, sd: float | None) -> tuple[float, float]:
    """(mean, sd) on the IPL rating scale of a league rating `value` (its sd) through row `t`."""
    mu, var, tvar = translate_parts(t, value, sd)
    return mu, math.sqrt(var + tvar)


def league_composite(parts: list[tuple[float, float, float]]) -> tuple[float, float, list[float]]:
    """One Gaussian on the IPL scale from several translated leagues (`translate_parts` rows): their
    means weighted by 1 / the independent variance, the translation variance added once (weighted
    the same way), not once per league — a player's gap between league numbers and IPL level is his,
    so playing six leagues doesn't make it six times smaller. Returns (mean, sd, weight shares)."""
    ws = [1.0 / max(v, 1e-6) for _, v, _ in parts]
    tot = sum(ws)
    mu = sum(w * m for w, (m, _, _) in zip(ws, parts, strict=True)) / tot
    tvar = sum(w * t for w, (_, _, t) in zip(ws, parts, strict=True)) / tot
    return mu, math.sqrt(1.0 / tot + tvar), [w / tot for w in ws]


def translate(
    col: str, role: str, value: float, sd: float | None, model: dict | None = None,
    which: str = "roles",
) -> tuple[float, float]:  # fmt: skip
    """A league rating on the IPL rating scale: (mean, sd). The auction target's own rating comes
    back unchanged."""
    t = table(col, role, model, which)
    if t is None:
        s = sd if isinstance(sd, int | float) and math.isfinite(sd) else 0.0
        return float(value), float(s)
    return translate_row(t, value, sd)


def combine(
    ipl: tuple[float, float] | None,
    others: list[tuple[float, float]],
    prior: tuple[float, float] | None = None,
) -> tuple[float, float, list[float]]:
    """Precision blend of Gaussian sources on the IPL rating scale: (value, sd, each source's share of
    the weight — the IPL first when given). With `prior` (mean, sd) the population prior each
    source's posterior already holds is divided out (an exact product of posteriors); the precision
    is kept positive."""
    srcs = ([ipl] if ipl else []) + list(others)
    if not srcs:
        raise ValueError("nothing to combine")
    ws = [1.0 / max(s, 1e-6) ** 2 for _, s in srcs]
    prec = sum(ws)
    num = sum(w * v for w, (v, _) in zip(ws, srcs, strict=True))
    if prior is not None and len(srcs) > 1:
        k = len(srcs) - 1
        p0 = 1.0 / prior[1] ** 2
        # never remove more than half of the evidence's precision
        k_eff = min(k * p0, 0.5 * prec) / p0
        prec -= k_eff * p0
        num -= k_eff * p0 * prior[0]
    shares = [w / sum(ws) for w in ws]
    return num / prec, prec**-0.5, shares


def blend(
    role: str,
    ipl: tuple[float, float] | None,
    other: dict[str, tuple[float, float]],
    model: dict | None = None,
    which: str = "roles",
) -> tuple[float, float, dict[str, float]]:
    """A player's value in one role from his IPL rating (value, sd) and his other leagues' ratings
    {league: (value, sd)}: each league translated onto the IPL scale, all combined by precision (the
    model's `blend` rule). Returns (value, sd, {league: share of the weight}) — the shares say which
    leagues the value rests on (the stale-evidence share). This is the continuous empirical-Bayes
    blend that replaced the 300-ball switch: a long IPL record dominates because its sd is small,
    not because of a cut-off."""
    m = model or load_model()
    target = leagues.auction_target().key
    cols = [c for c in other if table(c, role, m, which) is not None]
    parts = [translate_parts(table(c, role, m, which), *other[c]) for c in cols]
    prior = None
    if m.get("blend") == "product":
        p = m[which][role]["prior"]
        prior = (p["mean"], p["sd"])
    return blend_parts(ipl, dict(zip(cols, parts, strict=True)), prior, target)


def blend_parts(
    ipl: tuple[float, float] | None,
    parts: dict[str, tuple[float, float, float]],
    prior: tuple[float, float] | None,
    target: str = "ipl",
) -> tuple[float, float, dict[str, float]]:
    """`blend` on translated parts: the leagues as one composite (`league_composite`), then combined
    with the IPL rating by precision (`combine`). Shares: the IPL's, and the composite's split by
    each league's weight in it."""
    ev, lw = [], []
    if parts:
        mu, sd, lw = league_composite(list(parts.values()))
        ev = [(mu, sd)]
    v, sd, sh = combine(ipl, ev, prior)
    out: dict[str, float] = {}
    if ipl:
        out[target] = sh[0]
    if parts:
        comp = sh[-1]
        for c, w in zip(parts, lw, strict=True):
            out[c] = comp * w
    return v, sd, out


# ---- the scheme this replaced, kept only as a baseline for the backtests ----------------------------
#
# Until 2026-10-23 (config/leagues.toml `[tiers.*] discount`): one number per league taken off every
# rating, both roles; a translation sd of 6.5 runs (a "calibrated" discount) or 10.5 (one borrowed from
# a similar league); and a role record of 300+ IPL balls standing alone (other leagues ignored).
LEGACY_DISCOUNTS: dict[str, tuple[float, float]] = {
    "indian_domestic_male": (17.0, 6.5), "bbl": (6.0, 6.5), "sa20": (6.0, 6.5),
    "cpl": (8.5, 6.5), "blast": (8.5, 6.5), "psl": (6.0, 10.5), "ilt20": (6.0, 10.5),
    "hundred_male": (6.0, 10.5), "mlc": (8.5, 10.5), "bpl": (8.5, 10.5), "lpl": (8.5, 10.5),
    "super_smash": (8.5, 10.5), "csa_t20_challenge": (8.5, 10.5),
}  # fmt: skip
LEGACY_TRUST_BALLS = 300


def legacy_blend(
    ipl: tuple[float, float, float] | None, other: dict[str, tuple[float, float]]
) -> tuple[float, float, dict[str, float]]:
    """The replaced scheme (baselines only): `ipl` = (value, sd, IPL balls in the role)."""
    target = leagues.auction_target().key
    if ipl and ipl[2] >= LEGACY_TRUST_BALLS:
        return ipl[0], ipl[1], {target: 1.0}
    ws: dict[str, float] = {}
    num = 0.0
    if ipl:
        ws[target] = 1.0 / max(ipl[1], 1e-6) ** 2
        num += ws[target] * ipl[0]
    for c, (v, s) in other.items():
        disc, tsd = LEGACY_DISCOUNTS[c]
        ws[c] = 1.0 / (s * s + tsd * tsd)
        num += ws[c] * (v - disc)
    tot = sum(ws.values())
    return num / tot, tot**-0.5, {c: w / tot for c, w in ws.items()}


def summary(model: dict | None = None, at: float = 10.0) -> dict[str, dict[str, float]]:
    """{league: {"batter": t, "bowler": t}}: what a league rating of `at` becomes on the IPL scale
    (for copy such as "a +10 SMAT batter ≈ +2 in the IPL")."""
    m = model or load_model()
    out: dict[str, dict[str, float]] = {}
    for role in ROLES:
        for col, t in m["roles"][role]["leagues"].items():
            out.setdefault(col, {})[role] = round(float(t["a"]) + float(t["b"]) * at, 1)
    return out


def summary_text(model: dict | None = None, at: float = 10.0) -> str:
    """One line of copy: "a +10 rating becomes: SMAT bat −3.4 / bowl +0.8, BBL …" (pool leagues in
    registry order)."""
    try:
        s = summary(model, at)
    except FileNotFoundError:
        return "no league translation fitted yet"
    parts = []
    for lg in leagues.auction_pool():
        t = s.get(lg.key)
        if lg.auction_target or not t:
            continue
        parts.append(f"{lg.short} bat {t['batter']:+.1f} / bowl {t['bowler']:+.1f}")
    return f"a +{at:g} rating becomes, in the IPL: " + ", ".join(parts)


def site_payload(model: dict | None = None) -> dict[str, dict] | None:
    """What leagues.json carries per league (`translation`): {"batter": {a, b, tsd, pairs}, "bowler":
    {…}} on the IPL rating scale, for display (the prices themselves come translated in the data)."""
    try:
        m = model or load_model()
    except FileNotFoundError:
        return None
    out: dict[str, dict] = {}
    for role in ROLES:
        for col, t in m["roles"][role]["leagues"].items():
            out.setdefault(col, {})[role] = {
                "a": round(float(t["a"]), 2), "b": round(float(t["b"]), 3),
                "tsd": round(float(t["tsd"]), 2), "pairs": int(t.get("pairs") or 0),
            }  # fmt: skip
    return out
