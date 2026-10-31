"""Competition rules: one entry per auction / retention cycle, read from `config/competitions.toml`.

The league registry (`cricdesk.leagues`) says which leagues exist and how strong they are; this file
says what a franchise may do in one cycle of one of them: purse, squad limits, overseas cap, how
many players it may keep and what a kept player costs. The "Keep or release" calculator
(`cricdesk.web_parity.keep` ⇄ `site/src/lib/keep.ts`) reads it, so a new league's cycle is a TOML
entry plus a squads file, not a code change.

Every rule is either backed by a `[[competition.source]]` or listed in `assumed`; the loader
refuses anything else, so a guess can't pass for a fact.

Lookup order: `$CRICDESK_COMPETITIONS` → `<repo>/config/competitions.toml` → the copy shipped
inside the installed package (`cricdesk/competitions.toml`).

    python -m cricdesk.competitions list
    python -m cricdesk.competitions check
    python -m cricdesk.competitions json [key]      # what the website's keep page carries
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from cricdesk import leagues

SCHEMA = 1
KEY_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CYCLES = frozenset({"mega", "mini"})
RETAINED_COSTS = frozenset({"salary", "slabs"})
SOURCE_STATUS = frozenset({"official", "reported"})

_ROOT = Path(__file__).resolve().parents[2]
_PKG_COPY = Path(__file__).resolve().parent / "competitions.toml"
_REPO_COPY = _ROOT / "config" / "competitions.toml"

# the rule fields: each must be sourced or listed in `assumed`
RULE_FIELDS = (
    "retention_deadline",
    "auction_date",
    "auction_venue",
    "purse",
    "squad_min",
    "squad_max",
    "overseas_max",
    "max_retained",
    "max_overseas_retained",
    "rtm_cards",
    "retained_cost",
    "replacements_retainable",
    "overseas_fee_cap",
    "min_purse_spend_share",
)


class CompetitionError(ValueError):
    """The competitions file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Source:
    about: str
    status: str
    title: str
    url: str
    date: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Competition:
    key: str
    name: str
    league: str
    season: int
    cycle: str
    currency: str
    unit: str
    squads: str
    retention_deadline: str
    auction_date: str
    auction_venue: str
    purse: float
    squad_min: int
    squad_max: int
    overseas_max: int
    max_retained: int = 0
    max_overseas_retained: int = 0
    rtm_cards: int = 0
    retained_cost: str = "salary"
    retention_slabs: tuple[float, ...] = ()
    uncapped_retention_slab: float = 0.0
    replacements_retainable: bool = True
    overseas_fee_cap: float = 0.0
    min_purse_spend_share: float = 0.0
    assumed: tuple[str, ...] = ()
    source: tuple[Source, ...] = field(default_factory=tuple)

    @property
    def squads_path(self) -> Path:
        from cricdesk.config import DATA_DIR

        p = Path(self.squads)
        return p if p.is_absolute() else DATA_DIR / p

    def rules(self) -> dict[str, Any]:
        """The numbers the calculator uses (the web and Python read the same dict)."""
        return {
            "purse": self.purse,
            "squad_min": self.squad_min,
            "squad_max": self.squad_max,
            "overseas_max": self.overseas_max,
            "max_retained": self.max_retained,
            "max_overseas_retained": self.max_overseas_retained,
            "replacements_retainable": self.replacements_retainable,
            # what a kept player costs the purse (web_parity/keep.py `retention_costs`)
            "retained_cost": self.retained_cost,
            "retention_slabs": list(self.retention_slabs),
            "uncapped_retention_slab": self.uncapped_retention_slab,
        }


_FIELDS = set(Competition.__dataclass_fields__)
_REQUIRED = (
    "key",
    "name",
    "league",
    "season",
    "cycle",
    "currency",
    "unit",
    "squads",
    "retention_deadline",
    "auction_date",
    "auction_venue",
    "purse",
    "squad_min",
    "squad_max",
    "overseas_max",
)


def _iso(v: Any, where: str) -> str:
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise CompetitionError(f"{where}: {v!r} isn't an ISO date (YYYY-MM-DD)") from None


def _competition(raw: dict[str, Any], where: str, check_league: bool = True) -> Competition:
    unknown = set(raw) - _FIELDS
    if unknown:
        raise CompetitionError(f"{where}: unknown field(s) {sorted(unknown)}")
    missing = [f for f in _REQUIRED if f not in raw]
    if missing:
        raise CompetitionError(f"{where}: missing field(s) {missing}")
    d = dict(raw)
    w = f"competition {d['key']!r}"
    if not KEY_NAME.match(str(d["key"])):
        raise CompetitionError(f"{w}: key must be lowercase letters, digits and `_`")
    if check_league and not leagues.exists(str(d["league"])):
        raise CompetitionError(f"{w}: league {d['league']!r} isn't in config/leagues.toml")
    if d["cycle"] not in CYCLES:
        raise CompetitionError(f"{w}: cycle must be one of {sorted(CYCLES)}")
    for k in ("retention_deadline", "auction_date"):
        d[k] = _iso(d[k], f"{w}: {k}")
    if d["retention_deadline"] > d["auction_date"]:
        raise CompetitionError(f"{w}: the retention deadline falls after the auction")
    for k in ("purse", "overseas_fee_cap", "min_purse_spend_share", "uncapped_retention_slab"):
        if k in d:
            d[k] = float(d[k])
    if d["purse"] <= 0:
        raise CompetitionError(f"{w}: purse must be positive")
    for k in (
        "squad_min",
        "squad_max",
        "overseas_max",
        "max_retained",
        "max_overseas_retained",
        "rtm_cards",
        "season",
    ):
        if k in d and (not isinstance(d[k], int) or isinstance(d[k], bool) or d[k] < 0):
            raise CompetitionError(f"{w}: {k} must be a whole number ≥ 0")
    if not 0 < d["squad_min"] <= d["squad_max"]:
        raise CompetitionError(f"{w}: need 0 < squad_min ≤ squad_max")
    if d["overseas_max"] > d["squad_max"]:
        raise CompetitionError(f"{w}: overseas_max can't exceed squad_max")
    if d.get("max_retained", 0) > d["squad_max"]:
        raise CompetitionError(f"{w}: max_retained can't exceed squad_max")
    if not 0 <= d.get("min_purse_spend_share", 0.0) <= 1:
        raise CompetitionError(f"{w}: min_purse_spend_share is a share between 0 and 1")
    if d.get("retained_cost", "salary") not in RETAINED_COSTS:
        raise CompetitionError(f"{w}: retained_cost must be one of {sorted(RETAINED_COSTS)}")
    slabs = d.get("retention_slabs") or []
    if d.get("retained_cost") == "slabs" and not slabs:
        raise CompetitionError(f"{w}: retained_cost = 'slabs' needs `retention_slabs`")
    d["retention_slabs"] = tuple(float(x) for x in slabs)
    assumed = d.get("assumed") or []
    if isinstance(assumed, str):
        raise CompetitionError(f"{w}: `assumed` is a list of field names")
    bad = sorted(set(assumed) - set(RULE_FIELDS))
    if bad:
        raise CompetitionError(f"{w}: `assumed` names unknown rule field(s) {bad}")
    d["assumed"] = tuple(assumed)
    srcs = []
    for i, s in enumerate(d.get("source") or []):
        sw = f"{w}: source #{i + 1}"
        if not isinstance(s, dict) or not {"about", "status", "title", "url"} <= set(s):
            raise CompetitionError(f"{sw} needs `about`, `status`, `title` and `url`")
        extra = set(s) - set(Source.__dataclass_fields__)
        if extra:
            raise CompetitionError(f"{sw}: unknown field(s) {sorted(extra)}")
        if s["about"] != "general" and s["about"] not in RULE_FIELDS:
            raise CompetitionError(f"{sw}: `about` {s['about']!r} isn't a rule field or 'general'")
        if s["status"] not in SOURCE_STATUS:
            raise CompetitionError(f"{sw}: status must be one of {sorted(SOURCE_STATUS)}")
        if not str(s["url"]).startswith(("http://", "https://")):
            raise CompetitionError(f"{sw}: url must be a web address")
        srcs.append(
            Source(
                about=s["about"],
                status=s["status"],
                title=str(s["title"]),
                url=str(s["url"]),
                date=_iso(s["date"], sw) if s.get("date") else None,
                note=str(s.get("note", "")),
            )
        )
    d["source"] = tuple(srcs)
    sourced = {s.about for s in srcs}
    for f in RULE_FIELDS:
        if f not in sourced and f not in d["assumed"]:
            raise CompetitionError(f"{w}: `{f}` has no source; cite one or list it in `assumed`")
    return Competition(**d)


def parse(
    text: str, path: Path | str = "<string>", check_league: bool = True
) -> dict[str, Competition]:
    """Parse + validate competitions TOML text (used by `load` and by tests)."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise CompetitionError(f"{path}: not valid TOML ({e})") from e
    if raw.get("schema") != SCHEMA:
        raise CompetitionError(f"{path}: expected `schema = {SCHEMA}`")
    out: dict[str, Competition] = {}
    for i, c in enumerate(raw.get("competition") or []):
        comp = _competition(c, f"{path}: [[competition]] #{i + 1}", check_league)
        if comp.key in out:
            raise CompetitionError(f"{path}: duplicate competition {comp.key!r}")
        out[comp.key] = comp
    if not out:
        raise CompetitionError(f"{path}: no [[competition]] entries")
    return out


def registry_path() -> Path:
    env = os.environ.get("CRICDESK_COMPETITIONS")
    if env:
        return Path(env)
    return _REPO_COPY if _REPO_COPY.exists() else _PKG_COPY


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, Competition]:
    return parse(Path(path).read_text(encoding="utf-8"), path)


def load() -> dict[str, Competition]:
    path = registry_path()
    if not path.exists():
        raise CompetitionError(f"competitions file not found at {path}")
    return _load(str(path), path.stat().st_mtime)


def get(key: str) -> Competition:
    comps = load()
    if key not in comps:
        raise KeyError(f"unknown competition {key!r} — known: {', '.join(comps)}")
    return comps[key]


def default() -> Competition:
    """The newest cycle (latest season, then latest auction)."""
    return max(load().values(), key=lambda c: (c.season, c.auction_date))


# ---- squads ----------------------------------------------------------------------------------


def load_squads(comp: Competition) -> dict[str, Any]:
    """The competition's squads file ({squads: {team: [rows]}, ...})."""
    p = comp.squads_path
    if not p.exists():
        raise CompetitionError(f"{comp.key}: squads file {p} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def squad_rows(comp: Competition, squads: dict[str, Any] | None = None) -> dict[str, list[dict]]:
    """team → the players a team can choose to keep this cycle: every squad row except a player
    who retired or was released by his franchise (a "released" / board-request withdrawal), and,
    when `replacements_retainable` is off, a replacement signing; nor a player banned from the
    season (the availability file's "banned": pulled out after being bought, 2 seasons out)."""
    squads = squads if squads is not None else load_squads(comp)
    banned = {c for c, why in unavailable(comp.season).items() if why == "banned"}
    out: dict[str, list[dict]] = {}
    for team, rows in (squads.get("squads") or {}).items():
        keep: list[dict] = []
        for r in rows:
            if r.get("retired") or r.get("cricsheet_id") in banned:
                continue
            wd = r.get("withdrawn")
            if isinstance(wd, str) and ("release" in wd.lower() or "bcci" in wd.lower()):
                continue
            if r.get("acquired") == "replacement" and not comp.replacements_retainable:
                continue
            keep.append(r)
        out[team] = keep
    return out


def availability_path(league: str = "ipl") -> Path:
    """data/curated/<league>_availability.json: announced retirements and auction opt-outs, sourced."""
    return _ROOT / "data" / "curated" / f"{league}_availability.json"


def load_availability(league: str = "ipl") -> dict[str, dict]:
    """cricsheet id → the reviewed availability record (status, scope, date, seasons, _evidence);
    {} when there is no file."""
    p = availability_path(league)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def unavailable(
    season: int, league: str = "ipl", records: dict[str, dict] | None = None
) -> dict[str, str]:
    """cricsheet id → why he can't be bought at the auction for `season`: "retired" (announced, any
    scope, dated before that season), "not_registered" (he skipped that season's auction) or
    "banned" (barred from that season's auction, e.g. an overseas player who pulled out after being
    bought: banned from the tournament and the player auction for 2 seasons, IPL Player
    Regulations 2025-27)."""
    recs = load_availability(league) if records is None else records
    out: dict[str, str] = {}
    for cid, r in recs.items():
        st = r.get("status")
        if st == "retired" and int(str(r.get("date") or "0000")[:4]) < season:
            out[cid] = "retired"
        elif st in ("not_registered", "banned") and season in (r.get("seasons") or []):
            out[cid] = st
    return out


def eligibility_notes(
    season: int, league: str = "ipl", records: dict[str, dict] | None = None
) -> dict[str, str]:
    """cricsheet id → a note for a player kept in the pool whose eligibility for `season` is open
    (status "unconfirmed": no ruling yet, e.g. a Bangladesh player after the BCCI had KKR release
    Mustafizur Rahman in January 2026). The pages flag him; he isn't dropped."""
    recs = load_availability(league) if records is None else records
    return {
        cid: str(r.get("note") or "eligibility unconfirmed")
        for cid, r in recs.items()
        if r.get("status") == "unconfirmed" and season in (r.get("seasons") or [])
    }


# IPL Player Regulations 2025-27, item 7 (IPL Governing Council, 28 Sep 2024, iplt20.com): "A capped
# Indian player will become uncapped, if the player has in the last five calendar years preceding the
# year in which the relevant Season is held, not played in the starting XI in International Cricket
# (Test match, ODI, Twenty20 International) or does not have a Central Contract with BCCI. This will
# be applicable for Indian Players only." The data have no central-contract list, so a player with no
# international in those five years is taken to have none (a central contract goes to current
# internationals). METHODOLOGY §10.
UNCAPPED_LAPSE_YEARS = 5


def ipl_capped(rec: dict, season: int) -> bool:
    """Whether a player counts as capped for the IPL `season` (the set he comes up in, the
    retention slabs): any international appearance (the player master's `capped`), except that an
    Indian whose last one (`last_international`, YYYY-MM-DD) falls before the five calendar years
    preceding the season counts as uncapped again."""
    if not rec.get("capped"):
        return False
    if rec.get("country") != "IND":
        return True
    last = str(rec.get("last_international") or "")
    if not last[:4].isdigit():
        return True  # capped, but no date to apply the lapse to
    return int(last[:4]) >= season - UNCAPPED_LAPSE_YEARS


def slab_holder(squads: dict[str, Any], team: str, row: dict) -> str | None:
    """ "capped" / "uncapped" when `row` is a player `team` retained at the cycle's mega auction and
    still holds that retention (the squads file's `mega_retentions_2025`), else None. A player who
    joined by trade costs his salary at his new team (the slab stays with the retaining one).
    METHODOLOGY §10; web_parity/keep.py `slab_charge`."""
    block = ((squads.get("mega_retentions_2025") or {}).get("teams") or {}).get(team) or {}
    if row.get("acquired") == "trade" or (row.get("trade") or {}).get("from") not in (None, team):
        return None
    for kind in ("capped", "uncapped"):
        if row.get("name") in (block.get(kind) or []):
            return kind
    return None


def site_payload(comp: Competition) -> dict[str, Any]:
    """What the keep page carries about the rules (sources and assumptions included)."""
    d = asdict(comp)
    d.pop("squads")
    d["rules"] = comp.rules()
    d["source"] = [asdict(s) for s in comp.source]
    d["assumed"] = list(comp.assumed)
    d["retention_slabs"] = list(comp.retention_slabs)
    return d


def _main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "check":
        comps = load()
        for c in comps.values():
            if not c.squads_path.exists():
                print(f"error: {c.key}: squads file {c.squads_path} missing", file=sys.stderr)
                return 1
        print(f"ok: {len(comps)} competition(s) ({registry_path()})")
        return 0
    if cmd == "list":
        print("\n".join(load()))
        return 0
    if cmd == "json":
        comp = get(argv[1]) if len(argv) > 1 else default()
        print(json.dumps(site_payload(comp), indent=2, ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv[1:]))
    except CompetitionError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
