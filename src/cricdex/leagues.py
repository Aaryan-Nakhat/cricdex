"""The league registry: every competition CricDex knows, read from `config/leagues.toml`.

One list drives ingest (which Cricsheet zip(s) a collection comes from), the exporter (which
leagues are cooked, in what order), pricing (each strength tier's discount), Scout pools, the
auction pool and its nationality rule, the API allow-list, every collection picker and the refresh
workflow. Adding a league is a TOML entry, not a code change (docs/LEAGUES.md).

Lookup order for the file: `$CRICDEX_LEAGUES` → `<repo>/config/leagues.toml` → the copy shipped
inside the installed package (`cricdex/leagues.toml`).

    python -m cricdex.leagues list [--exported | --scout | --auction] [--sep " "]
    python -m cricdex.leagues check
    python -m cricdex.leagues json            # the site payload (what leagues.json carries)
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from cricdex.common.sql import ERA_PREFIX, WINDOW_SUFFIXES, WINDOWS, base_suffix, is_window

CRICSHEET_BASE = "https://cricsheet.org/downloads"
SCHEMA = 1

GENDERS = frozenset({"male", "female", "mixed"})
KINDS = frozenset({"league", "international", "domestic", "mixed"})
SCOUT_GROUPS = frozenset({"peers", "uncapped", "overseas"})
# A Cricsheet download name: lowercase words, digits and `_`, ending in `_json.zip`.
ZIP_NAME = re.compile(r"^[a-z0-9_()\-]+_json\.zip$")
KEY_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
ERA_KEY = re.compile(r"^[a-z][a-z0-9]*$")

_PKG_COPY = Path(__file__).resolve().parent / "leagues.toml"
_REPO_COPY = Path(__file__).resolve().parents[2] / "config" / "leagues.toml"


class RegistryError(ValueError):
    """The registry file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Tier:
    key: str
    discount: float
    calibrated: bool
    note: str = ""
    # How uncertain it is to translate a rating from this tier into IPL terms (runs per 100 balls).
    # Cross-league pooling weights each league by 1 / (rating sd² + translation_sd²), so IPL
    # evidence (0) dominates whenever a player has it and provisional discounts count least.
    translation_sd: float = 0.0


@dataclass(frozen=True)
class Era:
    """A stretch of a league's history with its own scoring level (e.g. the IPL's Impact Player era),
    exported as the recomputed window `era_<key>` (matches on or after `since`)."""

    key: str
    name: str
    since: str  # ISO date

    @property
    def window(self) -> str:
        return f"{ERA_PREFIX}{self.key}"


@dataclass(frozen=True)
class League:
    key: str
    name: str
    short: str
    zips: tuple[str, ...]
    gender: str
    kind: str
    country: str
    order: int
    tier: str | None = None
    export: bool = False
    active: bool = True
    scout_pool: bool = False
    scout_group: str | None = None
    scout_title: str | None = None
    scout_subtitle: str | None = None
    draftable: bool = False
    gem_pool: bool = False
    auction_pool: bool = False
    auction_target: bool = False
    auction_nationalities: tuple[str, ...] = ()
    auction_excluded_nationalities: tuple[str, ...] = ()
    era: tuple[Era, ...] = ()

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(f"{CRICSHEET_BASE}/{z}" for z in self.zips)

    def auction_eligible(self, country: str | None) -> bool:
        """May a free agent from `country` enter this competition's auction pool? The deny-list
        always wins; an empty allow-list admits every other nation. An unknown country only passes
        an empty allow-list. Every spelling is normalised first (RSA = ZAF, WI = WIN)."""
        from cricdex.scout.identity.countries import normalise

        code = normalise(country)
        if code in {normalise(c) for c in self.auction_excluded_nationalities}:
            return False
        if not self.auction_nationalities:
            return True
        return code is not None and code in {normalise(c) for c in self.auction_nationalities}


@dataclass(frozen=True)
class Registry:
    path: Path
    tiers: dict[str, Tier]
    leagues: tuple[League, ...]  # sorted by `order`

    def get(self, key: str) -> League:
        for lg in self.leagues:
            if lg.key == key:
                return lg
        raise KeyError(key)


# ---- loading + validation ---------------------------------------------------------------------

_LEAGUE_FIELDS = set(League.__dataclass_fields__)
_REQUIRED = ("key", "name", "short", "zips", "gender", "kind", "country", "order")


def registry_path() -> Path:
    env = os.environ.get("CRICDEX_LEAGUES")
    if env:
        return Path(env)
    return _REPO_COPY if _REPO_COPY.exists() else _PKG_COPY


def _league(raw: dict[str, Any], where: str) -> League:
    unknown = set(raw) - _LEAGUE_FIELDS
    if unknown:
        raise RegistryError(f"{where}: unknown field(s) {sorted(unknown)}")
    missing = [f for f in _REQUIRED if f not in raw]
    if missing:
        raise RegistryError(f"{where}: missing field(s) {missing}")
    data = dict(raw)
    zips = data["zips"]
    if isinstance(zips, str) or not isinstance(zips, list) or not zips:
        raise RegistryError(f"{where}: `zips` must be a non-empty list of file names")
    data["zips"] = tuple(zips)
    for f in ("auction_nationalities", "auction_excluded_nationalities"):
        v = data.get(f) or ()
        if isinstance(v, str):
            raise RegistryError(f"{where}: `{f}` must be a list of country codes")
        data[f] = tuple(v)
    eras = data.get("era") or []
    if not isinstance(eras, list):
        raise RegistryError(f"{where}: `era` must be a list of [[league.era]] tables")
    parsed = []
    for i, e in enumerate(eras):
        if not isinstance(e, dict) or set(e) != {"key", "name", "since"}:
            raise RegistryError(f"{where}: era #{i + 1} needs exactly `key`, `name` and `since`")
        if not ERA_KEY.match(str(e["key"])):
            raise RegistryError(f"{where}: era key {e['key']!r} must be lowercase letters / digits")
        try:
            since = date.fromisoformat(str(e["since"])).isoformat()
        except ValueError:
            raise RegistryError(f"{where}: era {e['key']!r} `since` isn't an ISO date") from None
        parsed.append(Era(key=str(e["key"]), name=str(e["name"]), since=since))
    if len({e.key for e in parsed}) != len(parsed):
        raise RegistryError(f"{where}: duplicate era keys")
    data["era"] = tuple(parsed)
    return League(**data)


def validate(tiers: dict[str, Tier], leagues: list[League]) -> None:
    """Raise RegistryError on the first inconsistency."""
    seen: set[str] = set()
    for lg in leagues:
        w = f"league {lg.key!r}"
        if not KEY_NAME.match(lg.key):
            raise RegistryError(f"{w}: key must be lowercase letters, digits and `_`")
        if lg.key in seen:
            raise RegistryError(f"{w}: duplicate key")
        seen.add(lg.key)
        if lg.key.endswith(WINDOW_SUFFIXES) or is_window(lg.key) or "_era_" in lg.key:
            raise RegistryError(
                f"{w}: a key can't end in a time-window suffix {WINDOW_SUFFIXES} or contain `_era_`"
            )
        for z in lg.zips:
            if not ZIP_NAME.match(z):
                raise RegistryError(f"{w}: {z!r} isn't a Cricsheet `<name>_json.zip` file name")
        if lg.gender not in GENDERS:
            raise RegistryError(f"{w}: gender must be one of {sorted(GENDERS)}")
        if lg.kind not in KINDS:
            raise RegistryError(f"{w}: kind must be one of {sorted(KINDS)}")
        if lg.tier is not None and lg.tier not in tiers:
            raise RegistryError(f"{w}: unknown tier {lg.tier!r} (define [tiers.{lg.tier}])")
        if (lg.scout_pool or lg.auction_pool) and lg.tier is None:
            raise RegistryError(f"{w}: a scout or auction pool needs a `tier`")
        if (lg.scout_pool or lg.auction_pool or lg.auction_target) and not lg.export:
            raise RegistryError(f"{w}: pools read exported data, so set `export = true`")
        if lg.scout_pool:
            if lg.scout_group not in SCOUT_GROUPS:
                raise RegistryError(f"{w}: scout_group must be one of {sorted(SCOUT_GROUPS)}")
        elif lg.draftable or lg.gem_pool or lg.scout_group:
            raise RegistryError(f"{w}: scout flags need `scout_pool = true`")
        if lg.auction_target and not lg.auction_pool:
            raise RegistryError(f"{w}: the auction target must be in the auction pool")
        if (
            lg.auction_nationalities or lg.auction_excluded_nationalities
        ) and not lg.auction_target:
            raise RegistryError(f"{w}: auction nationality lists belong on the auction target")
        both = set(lg.auction_nationalities) & set(lg.auction_excluded_nationalities)
        if both:
            raise RegistryError(f"{w}: {sorted(both)} both allowed and excluded")
    scout = [lg for lg in leagues if lg.scout_pool]
    tiers_used = [lg.tier for lg in scout]
    if len(set(tiers_used)) != len(tiers_used):
        raise RegistryError("two scout pools share a tier: scout_index.json is keyed by tier")
    targets = [lg for lg in leagues if lg.auction_target]
    if any(lg.auction_pool for lg in leagues) and len(targets) != 1:
        raise RegistryError("exactly one league must be the `auction_target`")
    if sum(lg.gem_pool for lg in leagues) > 1:
        raise RegistryError("at most one league can be the `gem_pool`")
    peers = [lg for lg in scout if lg.scout_group == "peers"]
    if scout and (len(peers) != 1 or not peers[0].auction_target):
        raise RegistryError("Scout needs exactly one `peers` pool, the auction target")


def parse(text: str, path: Path | str = "<string>") -> Registry:
    """Parse + validate registry TOML text (used by `load` and by tests)."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise RegistryError(f"{path}: not valid TOML ({e})") from e
    if raw.get("schema") != SCHEMA:
        raise RegistryError(f"{path}: expected `schema = {SCHEMA}`")
    tiers: dict[str, Tier] = {}
    for key, t in (raw.get("tiers") or {}).items():
        if not isinstance(t, dict) or "discount" not in t or "calibrated" not in t:
            raise RegistryError(f"{path}: [tiers.{key}] needs `discount` and `calibrated`")
        discount_v, calibrated_v = float(t["discount"]), bool(t["calibrated"])
        # default: none for the reference tier, more for a borrowed (uncalibrated) discount
        default_tsd = 0.0 if discount_v == 0 else (6.5 if calibrated_v else 10.5)
        tiers[key] = Tier(
            key=key,
            discount=discount_v,
            calibrated=calibrated_v,
            note=str(t.get("note", "")),
            translation_sd=float(t.get("translation_sd", default_tsd)),
        )
    leagues = [
        _league(lg, f"{path}: [[league]] #{i + 1}") for i, lg in enumerate(raw.get("league") or [])
    ]
    if not leagues:
        raise RegistryError(f"{path}: no [[league]] entries")
    validate(tiers, leagues)
    leagues.sort(key=lambda lg: (lg.order, lg.key))
    return Registry(path=Path(path), tiers=tiers, leagues=tuple(leagues))


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Registry:
    return parse(Path(path).read_text(encoding="utf-8"), path)


def load() -> Registry:
    """The registry (cached; re-read when the file changes)."""
    path = registry_path()
    if not path.exists():
        raise RegistryError(f"league registry not found at {path}")
    return _load(str(path), path.stat().st_mtime)


# ---- helpers ----------------------------------------------------------------------------------


def all() -> tuple[League, ...]:  # noqa: A001 — `leagues.all()` reads naturally
    """Every league, in display order."""
    return load().leagues


def keys() -> list[str]:
    return [lg.key for lg in all()]


def get(key: str) -> League:
    """The league for a collection key (a time-window key like `ipl_last1y` resolves to `ipl`)."""
    try:
        return load().get(base_key(key))
    except KeyError:
        raise KeyError(f"unknown league {key!r} — known: {', '.join(keys())}") from None


def exists(key: str) -> bool:
    try:
        get(key)
    except (KeyError, ValueError):
        return False
    return True


def exported() -> list[League]:
    return [lg for lg in all() if lg.export]


def exported_keys() -> list[str]:
    return [lg.key for lg in exported()]


def scout_pools() -> list[League]:
    """The Scout look-alike panels, in display order (keyed by tier in scout_index.json)."""
    return [lg for lg in all() if lg.scout_pool]


def auction_pool() -> list[League]:
    """Leagues feeding the cross-league auction pool."""
    return [lg for lg in all() if lg.auction_pool]


def auction_target() -> League:
    """The competition the auction pool is priced for (the IPL today)."""
    return next(lg for lg in all() if lg.auction_target)


def gem_pool() -> League | None:
    return next((lg for lg in all() if lg.gem_pool), None)


def tiers() -> dict[str, Tier]:
    return dict(load().tiers)


def tier_discounts() -> dict[str, float]:
    """tier key → value discount (what pricing's TIER_PENALTY is)."""
    return {k: t.discount for k, t in load().tiers.items()}


def discount(key: str) -> float:
    """The strength discount of a league (by collection key)."""
    lg = get(key)
    if lg.tier is None:
        raise KeyError(f"league {key!r} has no strength tier")
    return load().tiers[lg.tier].discount


def translation_sd(key: str) -> float:
    """How uncertain a league's ratings are once translated to IPL terms (by collection key)."""
    lg = get(key)
    if lg.tier is None:
        raise KeyError(f"league {key!r} has no strength tier")
    return load().tiers[lg.tier].translation_sd


def by_tier(tier: str) -> League:
    """The scout / auction league that uses a tier key (`smat` → indian_domestic_male)."""
    for lg in all():
        if lg.tier == tier and (lg.scout_pool or lg.auction_pool):
            return lg
    for lg in all():
        if lg.tier == tier:
            return lg
    raise KeyError(f"no league uses tier {tier!r}")


def auction_pool_summary(sep: str = " / ") -> dict[str, str]:
    """Plain-text pieces for "who's in the auction pool" copy: the overseas and uncapped free-agent
    leagues (short names) and each distinct tier discount, e.g. "BBL/SA20/PSL −6.0"."""
    reg = load()
    pool = [lg for lg in reg.leagues if lg.auction_pool and not lg.auction_target]
    by_disc: dict[float, list[str]] = {}
    for lg in pool:
        if lg.tier is not None:
            by_disc.setdefault(reg.tiers[lg.tier].discount, []).append(lg.short)
    return {
        "overseas": sep.join(lg.short for lg in pool if lg.scout_group != "uncapped"),
        "uncapped": sep.join(lg.short for lg in pool if lg.scout_group == "uncapped"),
        "discounts": ", ".join(f"{'/'.join(n)} −{d:.1f}" for d, n in sorted(by_disc.items())),
    }


def eras(key: str) -> tuple[Era, ...]:
    """A league's eras (by collection key), oldest first."""
    try:
        return tuple(sorted(get(key).era, key=lambda e: e.since))
    except (KeyError, ValueError):
        return ()


def window_labels(key: str) -> dict[str, str]:
    """window key → label for a league's recomputed windows (the time windows and its eras)."""
    out = {"last3y": "Last 3 yrs", "last1y": "Last 1 yr"}
    out.update({e.window: e.name for e in eras(key)})
    return out


def label(key: str) -> str:
    """Display name for a collection key (unknown keys come back unchanged)."""
    try:
        return get(key).name
    except (KeyError, ValueError):
        return key


def short(key: str) -> str:
    try:
        return get(key).short
    except (KeyError, ValueError):
        return key


def base_key(key: str) -> str:
    """`ipl_last1y` → `ipl`: the collection a time-window table was cut from."""
    return base_suffix(key)


def validate_collection(collection: str, *, exported_only: bool = False) -> str:
    """Return the collection if the registry knows it (a time window of a known league counts),
    else raise ValueError naming the valid keys — the API turns that into a 400."""
    pool = exported_keys() if exported_only else keys()
    try:
        base = base_key(collection)
    except ValueError:
        base = None
    if base not in pool:
        raise ValueError(f"unknown collection {collection!r}. Valid: {', '.join(pool)}")
    return collection


def site_payload() -> dict[str, Any]:
    """What `site/public/data/leagues.json` carries — everything the frontend needs."""
    reg = load()
    target = auction_target() if any(lg.auction_target for lg in reg.leagues) else None
    gem = gem_pool()
    return {
        "schema": SCHEMA,
        "tiers": {
            k: {"discount": t.discount, "calibrated": t.calibrated} for k, t in reg.tiers.items()
        },
        "leagues": [
            {
                "key": lg.key,
                "name": lg.name,
                "short": lg.short,
                "gender": lg.gender,
                "kind": lg.kind,
                "country": lg.country,
                "tier": lg.tier,
                "discount": reg.tiers[lg.tier].discount if lg.tier else None,
                "calibrated": reg.tiers[lg.tier].calibrated if lg.tier else None,
                "export": lg.export,
                "active": lg.active,
                "order": lg.order,
                "scout_pool": lg.scout_pool,
                "scout_group": lg.scout_group,
                "scout_title": lg.scout_title,
                "scout_subtitle": lg.scout_subtitle,
                "draftable": lg.draftable,
                "gem_pool": lg.gem_pool,
                "auction_pool": lg.auction_pool,
                "auction_target": lg.auction_target,
                "eras": [
                    {"key": e.key, "window": e.window, "name": e.name, "since": e.since}
                    for e in lg.era
                ],
            }
            for lg in reg.leagues
        ],
        "auction": {
            "target": target.key if target else None,
            "target_tier": target.tier if target else None,
            "eligible_nationalities": list(target.auction_nationalities) if target else [],
            "excluded_nationalities": (
                list(target.auction_excluded_nationalities) if target else []
            ),
        },
        "gem_tier": gem.tier if gem else None,
        # time windows a collection key may carry (`ipl_last1y`): window → days
        "windows": dict(WINDOWS),
    }


# ---- CLI --------------------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    import json

    cmd = argv[0] if argv else "list"
    if cmd == "check":
        reg = load()
        print(f"ok: {len(reg.leagues)} leagues, {len(reg.tiers)} tiers ({reg.path})")
        return 0
    if cmd == "json":
        print(json.dumps(site_payload(), indent=2))
        return 0
    if cmd == "list":
        sep = "\n"
        if "--sep" in argv:
            sep = argv[argv.index("--sep") + 1]
        rows = list(all())
        if "--exported" in argv:
            rows = [lg for lg in rows if lg.export]
        if "--scout" in argv:
            rows = [lg for lg in rows if lg.scout_pool]
        if "--auction" in argv:
            rows = [lg for lg in rows if lg.auction_pool]
        print(sep.join(lg.key for lg in rows))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv[1:]))
    except RegistryError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
