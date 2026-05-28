"""Build a real IPL auction pool for GRPO training.

Inputs (all already on disk in this repo):

- `data/metrics/scout_ratings_ipl.json` — NumPyro Bayesian batter +
  bowler skills (one row per (cricsheet_id, role)). Skills are on the
  log scale; positive = above average for the IPL.
- `data/cricsheet/cricsheet.duckdb` — ball-by-ball; we use
  `balls_ipl` for career balls and `balls_t20s_male` for nationality
  imputation (most-common team in men's T20Is is treated as the
  player's country).
- `data/cricsheet/cricsheet.duckdb.people` — the People Register, for
  human-readable names.

Outputs a polars DataFrame with the schema the auction env / MILP
solver consume:

    name             unique_name from People Register
    cricsheet_id     identifier (or 'unresolved:<name>')
    role             batter | bowler | all_rounder  (Bayes ratings split)
    country          'IN' for Indian, otherwise the dominant intl team
    is_overseas      country != 'IN'
    base_price       0.30 / 0.50 / 0.75 / 1.0 / 1.5 / 2.0 cr  (IPL tiers)
    projected_value  scaled Bayesian skill — 0.5 cr (replacement) to
                     12 cr (marquee). Used as the env's reward proxy.

Why this matters
----------------
The synthetic `solver.sample_pool` generator emits random names with
random projected_value and random country composition — fine for
testing the env wiring but useless as RL training data. With real
skill-driven `projected_value` and real nationality, the policy
actually has a signal worth learning: "Indian, high-skill, low-base
price" wins, which is what real auction strategy is.

Calibration
-----------
projected_value mapping is intentionally simple and reversible:

    base = exp(skill)                # log-skill → multiplicative effect
    role_floor = {'batter': 0.5, 'bowler': 0.5, 'all_rounder': 0.8}
    value = base * role_floor * 4.0  # ≈ marquee cohort lands at 8-12 cr

Override the scaling factors via `value_scale` to recalibrate.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import duckdb
import polars as pl

from cricdex.config import DATA_DIR

DEFAULT_RATINGS_PATH = DATA_DIR / "metrics" / "scout_ratings_ipl.json"
DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# IPL auction base-price tiers (cr). Real-world set bands.
PRICE_TIERS = [0.30, 0.50, 0.75, 1.0, 1.5, 2.0]

ROLE_FLOOR = {"batter": 0.5, "bowler": 0.5, "all_rounder": 0.8}

# Manual nationality overrides for People-Register name collisions.
# Cricsheet's IPL ball-by-ball uses bare unique_names; the JOIN against
# `people` picks whichever identifier comes first, which mis-attributes
# IPL balls to namesakes who actually represent another country in
# men's T20Is. Until a per-match registry lookup is wired, override by
# unique_name. Keep this list short and well-reasoned — every entry
# overrides the data flow.
NATIONALITY_OVERRIDES: dict[str, str] = {
    # Afghan leg-spinner (GT, SRH); JOIN picks the Nepali namesake.
    "Rashid Khan": "AF",
    # Pakistani-origin LSG pacer; t20s_male top team is the Hong Kong
    # namesake.
    "Mohsin Khan": "PK",
}


def _load_ratings(path: Path | str = DEFAULT_RATINGS_PATH) -> pl.DataFrame:
    rows = json.loads(Path(path).read_text())
    return pl.DataFrame(rows)


def _nationality_map(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Return cricsheet_id → ISO-ish country code based on the dominant
    team a player appeared for in men's T20Is. Players not in t20s_male
    fall back to None (caller decides — defaults to 'IN' for the IPL
    workflow since IPL eligibility is Indian by default unless we see
    them on a non-Indian intl team)."""
    try:
        rows = con.execute(
            """
            WITH appearances AS (
                SELECT batter AS name, batting_team AS team FROM balls_t20s_male
                UNION ALL
                SELECT bowler AS name, bowling_team AS team FROM balls_t20s_male
            ),
            ranked AS (
                SELECT
                    p.identifier AS cricsheet_id,
                    a.team,
                    COUNT(*) AS appearances,
                    ROW_NUMBER() OVER (
                        PARTITION BY p.identifier ORDER BY COUNT(*) DESC
                    ) AS rk
                FROM appearances a
                JOIN people p ON p.unique_name = a.name
                WHERE a.team IS NOT NULL AND p.identifier IS NOT NULL
                GROUP BY p.identifier, a.team
            )
            SELECT cricsheet_id, team
            FROM ranked WHERE rk = 1
            """
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except duckdb.CatalogException:
        return {}


def _ipl_career_balls(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    rows = con.execute(
        """
        WITH bats AS (
            SELECT p.identifier AS cid,
                   SUM(CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END) AS balls_faced
            FROM balls_ipl b
            JOIN people p ON p.unique_name = b.batter
            WHERE b.batter IS NOT NULL
            GROUP BY p.identifier
        ),
        bowls AS (
            SELECT p.identifier AS cid,
                   SUM(CASE WHEN extras_type IN ('wides') THEN 0 ELSE 1 END) AS balls_bowled
            FROM balls_ipl b
            JOIN people p ON p.unique_name = b.bowler
            WHERE b.bowler IS NOT NULL
            GROUP BY p.identifier
        )
        SELECT COALESCE(b.cid, k.cid) AS cid,
               COALESCE(b.balls_faced, 0) AS balls_faced,
               COALESCE(k.balls_bowled, 0) AS balls_bowled
        FROM bats b
        FULL OUTER JOIN bowls k ON b.cid = k.cid
        """
    ).fetchall()
    return {r[0]: {"balls_faced": int(r[1] or 0), "balls_bowled": int(r[2] or 0)} for r in rows}


def _name_map(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = con.execute("SELECT identifier, unique_name FROM people").fetchall()
    return {r[0]: r[1] for r in rows}


def _role_of(career: dict, ratings_role: str) -> str:
    """All-rounder only if substantive contribution in both disciplines
    (≥240 balls each, ~40 overs). Otherwise trust the Bayes primary
    role since the ratings fit explicitly modelled batter vs bowler."""
    bw = career.get("balls_bowled", 0)
    bt = career.get("balls_faced", 0)
    if bw >= 240 and bt >= 240:
        return "all_rounder"
    return ratings_role  # 'batter' or 'bowler' as fitted by Bayes


def _project_value(skill: float, role: str, value_scale: float = 10.0) -> float:
    """Map Bayes log-skill → IPL-realistic cr value.

    The top marquee cohort (skill ≈ +0.3) lands around 11-12 cr; the
    replacement-level cohort (skill ≈ -0.1) around 0.5-1.0 cr."""
    floor = ROLE_FLOOR.get(role, 0.5)
    return round(math.exp(skill) * floor * value_scale, 2)


def _base_price(value: float) -> float:
    """Pick the highest IPL base-price tier ≤ value/6 — base prices are
    well below projected value (auction bid-up does the rest)."""
    target = max(0.30, value / 6.0)
    chosen = PRICE_TIERS[0]
    for tier in PRICE_TIERS:
        if tier <= target:
            chosen = tier
    return chosen


def build_pool(
    ratings_path: Path | str = DEFAULT_RATINGS_PATH,
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 200,
    value_scale: float = 10.0,
) -> pl.DataFrame:
    """One row per IPL player who has cleared `min_balls` (faced or bowled)."""
    ratings = _load_ratings(ratings_path)
    # Collapse batter/bowler rows into one per cricsheet_id, keeping the
    # strongest (largest |skill|) signal as the primary role.
    ratings = ratings.with_columns(pl.col("skill").abs().alias("_abs_skill"))
    primary = (
        ratings.sort("_abs_skill", descending=True)
        .group_by("cricsheet_id", maintain_order=True)
        .first()
    )

    with duckdb.connect(str(db_path), read_only=True) as con:
        nat = _nationality_map(con)
        career = _ipl_career_balls(con)
        name_of = _name_map(con)

    # Normalise cricsheet's free-form team strings to short codes so the
    # downstream MILP `is_overseas` flag is consistent regardless of
    # whether a player resolved via the t20s_male nationality scan.
    country_codes = {
        "India": "IN",
        "Australia": "AU",
        "New Zealand": "NZ",
        "South Africa": "SA",
        "England": "EN",
        "Pakistan": "PK",
        "West Indies": "WI",
        "Sri Lanka": "SL",
        "Bangladesh": "BD",
        "Afghanistan": "AF",
        "Nepal": "NP",
        "Zimbabwe": "ZW",
        "Ireland": "IE",
        "Scotland": "SC",
        "Netherlands": "NL",
    }

    rows = []
    for r in primary.iter_rows(named=True):
        cid = r["cricsheet_id"]
        if cid.startswith("unresolved:"):
            continue
        c = career.get(cid, {"balls_faced": 0, "balls_bowled": 0})
        if c["balls_faced"] + c["balls_bowled"] < min_balls:
            continue
        role = _role_of(c, r["role"])
        name = name_of.get(cid, cid)
        if name in NATIONALITY_OVERRIDES:
            country = NATIONALITY_OVERRIDES[name]
        else:
            raw_country = nat.get(cid) or "India"
            country = country_codes.get(raw_country, raw_country)
        value = _project_value(r["skill"], role, value_scale=value_scale)
        base_price = _base_price(value)
        rows.append(
            {
                "name": name,
                "cricsheet_id": cid,
                "role": role,
                "country": country,
                "is_overseas": country != "IN",
                "base_price": base_price,
                "price": base_price,  # auction starts at base; env applies markup
                "projected_value": value,
                "skill": r["skill"],
                "balls_faced": c["balls_faced"],
                "balls_bowled": c["balls_bowled"],
            }
        )

    return pl.DataFrame(rows).sort("projected_value", descending=True)


FRANCHISE_ARCHETYPES: list[dict] = [
    # name, aggression, risk-jitter, role bias, overseas appetite, notes
    {
        "id": "MarqueeChaser",
        "purse": 90.0,
        "aggression": 1.35,
        "risk": 0.20,
        "role_mins": {"batter": 6, "bowler": 4, "all_rounder": 4, "keeper": 2},
    },
    {
        "id": "ValueHunter",
        "purse": 90.0,
        "aggression": 0.85,
        "risk": 0.30,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
    {
        "id": "OverseasHeavy",
        "purse": 90.0,
        "aggression": 1.15,
        "risk": 0.18,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
        "overseas_left": 8,
    },
    {
        "id": "IndianFocus",
        "purse": 90.0,
        "aggression": 1.05,
        "risk": 0.15,
        "role_mins": {"batter": 7, "bowler": 5, "all_rounder": 3, "keeper": 2},
        "overseas_left": 3,
    },
    {
        "id": "AllRounderStack",
        "purse": 90.0,
        "aggression": 1.10,
        "risk": 0.22,
        "role_mins": {"batter": 4, "bowler": 4, "all_rounder": 6, "keeper": 2},
    },
    {
        "id": "Balanced",
        "purse": 90.0,
        "aggression": 1.00,
        "risk": 0.15,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
]


# IPL 2024+ franchise roster keyed to bidding archetypes. The defaults
# are hand-picked from broad historical patterns (CSK = disciplined /
# balanced under Dhoni; MI + RCB = marquee-buyer-heavy; KKR = all-
# rounder stack with Russell/Narine; SRH + LSG = overseas-heavy in
# their respective eras; DC = Indian-talent focus; PBKS + RR = value-
# hunters; GT = balanced cap management). They're opinions, not facts
# — override per-team via `~/.cricdex/teams.yaml` or via the TUI /
# Streamlit per-team selectors.
IPL_TEAMS_DEFAULT: list[tuple[str, str]] = [
    ("CSK", "Balanced"),
    ("MI", "MarqueeChaser"),
    ("RCB", "MarqueeChaser"),
    ("KKR", "AllRounderStack"),
    ("DC", "IndianFocus"),
    ("PBKS", "ValueHunter"),
    ("SRH", "OverseasHeavy"),
    ("GT", "Balanced"),
    ("RR", "ValueHunter"),
    ("LSG", "OverseasHeavy"),
]

# All personality ids, exposed so UI code can populate dropdowns
# without re-deriving them from FRANCHISE_ARCHETYPES.
PERSONALITY_IDS: tuple[str, ...] = tuple(a["id"] for a in FRANCHISE_ARCHETYPES)
_PERSONALITY_BY_ID: dict[str, dict] = {a["id"]: a for a in FRANCHISE_ARCHETYPES}


def load_team_overrides(
    path: Path | None = None,
) -> list[tuple[str, str]] | None:
    """Read a YAML file mapping team → personality so power users can
    customise without touching code. File shape:

        teams:
          - {name: CSK,  personality: Balanced}
          - {name: MI,   personality: MarqueeChaser}
          ...

    Returns None if the file is missing / unreadable / malformed, so
    the caller falls back to `IPL_TEAMS_DEFAULT`. PyYAML is optional;
    we soft-fail if it's not installed.
    """
    if path is None:
        path = Path.home() / ".cricdex" / "teams.yaml"
    if not path.exists():
        return None
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None
    teams = data.get("teams")
    if not isinstance(teams, list):
        return None
    out: list[tuple[str, str]] = []
    for row in teams:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        personality = row.get("personality")
        if name and personality in _PERSONALITY_BY_ID:
            out.append((str(name), str(personality)))
    return out or None


def build_franchises(
    n: int = 10,
    purse: float = 90.0,
    teams: str | list[tuple[str, str]] = "real",
) -> list[dict]:
    """Return franchise dicts for the Monte-Carlo simulator.

    Args:
        n: how many franchises to emit (only consulted when `teams` is
            the string `'generic'`).
        purse: per-franchise budget; overrides the archetype default.
        teams: one of
            - `'real'` (default) — 10 real IPL teams with the
              history-based personalities in `IPL_TEAMS_DEFAULT`. If
              `~/.cricdex/teams.yaml` exists with a valid `teams:`
              list, those overrides win.
            - `'generic'` — `n` cycle-named F1, F2, … bidders rotating
              the 6 archetypes (the prior behaviour).
            - explicit `[(team_name, personality_id), ...]` — used by
              the TUI / Streamlit per-team dropdowns to pass exactly
              what the user picked.

    Each emitted dict carries `id` (the team name), the personality's
    `aggression / risk / role_mins / overseas_left`, and the caller's
    `purse`.
    """
    if teams == "real":
        pairs = load_team_overrides() or list(IPL_TEAMS_DEFAULT)
    elif teams == "generic":
        cycled = list(itertools.islice(itertools.cycle(FRANCHISE_ARCHETYPES), n))
        pairs = [(f"F{i + 1}", a["id"]) for i, a in enumerate(cycled)]
    elif isinstance(teams, list):
        pairs = teams
    else:
        raise ValueError(f"teams must be 'real' | 'generic' | list, got {teams!r}")

    out: list[dict] = []
    for team_name, personality_id in pairs:
        base = _PERSONALITY_BY_ID.get(personality_id)
        if base is None:
            raise ValueError(
                f"unknown personality `{personality_id}` for team `{team_name}` "
                f"(choose from {PERSONALITY_IDS})"
            )
        f = dict(base)
        f["id"] = team_name
        f["personality"] = personality_id
        f["purse"] = purse
        out.append(f)
    return out
