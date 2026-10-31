"""The exported site data after the player-master pass: the identity contract on players.json and
profiles, links that resolve, numeric JSON, windowed match counts, capped / retired rules.

Skipped on a snapshot exported before the player master existed (players.json rows without
`display_name`); point `CRICDESK_SITE_DATA` at another export to check that one instead."""

from __future__ import annotations

import json
import re

import pytest

from cricdesk import leagues
from cricdesk.config import SITE_DATA
from cricdesk.scout.identity import countries

IDX = SITE_DATA / "collections.json"
COLLECTIONS = (
    [c["collection"] for c in json.loads(IDX.read_text(encoding="utf-8"))] if IDX.exists() else []
)
CONTRACT = {
    "display_name": str,
    "full_name": str,
    "aliases": list,
    "capped": bool,
    "active": bool,
    "retired": bool,
}
NULLABLE = (
    "country",
    "team",
    "batting_hand",
    "bowling_arm",
    "bowling_category",
    "bowling_style",
    "primary_role",
)
NUMERIC_STRING = re.compile(r"^-?\d+(?:\.\d+)?$")


def _load(*parts):
    return json.loads(SITE_DATA.joinpath(*parts).read_text(encoding="utf-8"))


def _players(col: str) -> list[dict]:
    rows = _load(col, "players.json")
    if rows and "display_name" not in rows[0]:
        pytest.skip("site data predates the player master — re-run scripts/export_site.py")
    return rows


def _exported(col: str) -> bool:
    return (SITE_DATA / col / "players.json").exists()


@pytest.mark.parametrize("col", COLLECTIONS)
def test_players_carry_the_identity_contract(col):
    players = _players(col)
    codes = countries.all_codes()
    for p in players:
        for k, t in CONTRACT.items():
            assert isinstance(p.get(k), t), (col, p["cricsheet_id"], k, p.get(k))
        for k in NULLABLE:
            assert k in p, (col, p["cricsheet_id"], k)
        assert p["country"] is None or p["country"] in codes
        assert p["bowling_category"] in (None, "seam", "spin")
        assert p["primary_role"] in (None, "batter", "bowler", "allrounder", "wk_batter")
        # every name a player goes by is searchable
        assert p["name"] in p["aliases"] or p["name"] == p["display_name"]
    assert len({p["cricsheet_id"] for p in players}) == len(players)


@pytest.mark.parametrize("col", COLLECTIONS)
def test_every_player_has_a_profile_with_identity(col):
    players = _players(col)
    for p in players:
        f = SITE_DATA / col / "profiles" / f"{p['cricsheet_id']}.json"
        assert f.exists(), (col, p["name"])
    sample = _load(col, "profiles", f"{players[0]['cricsheet_id']}.json")
    assert set(CONTRACT) | set(NULLABLE) <= set(sample["identity"])


def _board_rows(col: str):
    for f in sorted((SITE_DATA / col / "leaderboards").glob("*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            yield f.name, r
    phase = SITE_DATA / col / "phase.json"
    if phase.exists():
        for board in json.loads(phase.read_text(encoding="utf-8")).values():
            for r in (*board.get("batters", []), *board.get("bowlers", [])):
                yield "phase.json", r


@pytest.mark.parametrize("col", COLLECTIONS)
def test_every_board_link_resolves_to_a_profile(col):
    players = _players(col)
    by_name = {p["name"]: p["cricsheet_id"] for p in players}
    dead = []
    for board, r in _board_rows(col):
        who = r.get("name") or r.get("batter") or r.get("bowler") or r.get("fielder")
        cid = r.get("cricsheet_id") or by_name.get(who)
        if not cid or not (SITE_DATA / col / "profiles" / f"{cid}.json").exists():
            dead.append((board, who))
    assert not dead, f"{col}: {len(dead)} dead links, e.g. {dead[:5]}"


def test_scout_and_auction_links_resolve_to_a_profile():
    target = leagues.auction_target().key
    _players(target)
    dead = []
    for tier, rows in _load(target, "scout_index.json").items():
        for r in rows:
            col = r.get("profile_collection")
            if col and not _exported(col):
                continue  # a partial export: that league wasn't cooked this time
            f = SITE_DATA / (col or target) / "profiles" / f"{r['cricsheet_id']}.json"
            if not f.exists():
                dead.append((tier, r["name"]))
    for r in _load(target, "auction_pool.json"):
        col = r.get("profile_collection") or target
        if not _exported(col):
            continue
        if not (SITE_DATA / col / "profiles" / f"{r['cricsheet_id']}.json").exists():
            dead.append(("auction", r["name"]))
    assert not dead, f"{len(dead)} dead links, e.g. {dead[:5]}"


def _numeric_strings(obj, path=""):
    text_keys = ("name", "batter", "bowler", "fielder", "season", "a", "b", "venue", "batters")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in text_keys or k.endswith("_id") or k.startswith("key_") or "date" in k:
                continue
            if k.endswith("name") or k.endswith("_qid"):
                continue
            yield from _numeric_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _numeric_strings(v, path)
    elif isinstance(obj, str) and NUMERIC_STRING.match(obj):
        yield path, obj


@pytest.mark.parametrize("col", COLLECTIONS)
def test_no_numbers_stored_as_strings(col):
    _players(col)
    files = [
        *sorted((SITE_DATA / col / "leaderboards").glob("*.json")),
        *(SITE_DATA / col / f for f in ("players.json", "phase.json", "records.json", "meta.json")),
        *sorted((SITE_DATA / col / "profiles").glob("*.json"))[:40],
    ]
    bad = []
    for f in files:
        if f.exists():
            bad += [(f.name, *x) for x in _numeric_strings(json.loads(f.read_text("utf-8")))]
    assert not bad, f"{col}: numbers as strings, e.g. {bad[:5]}"


@pytest.mark.parametrize("col", COLLECTIONS)
def test_window_boards_count_matches_inside_the_window(col):
    # keyed by Cricsheet id: two different players can share a scorecard name in one league
    players = {p["cricsheet_id"]: p for p in _players(col) if p.get("cricsheet_id")}
    meta = _load(col, "meta.json")

    def _key(r):
        return r.get("cricsheet_id") or (
            r.get("name") or r.get("batter") or r.get("bowler") or r.get("fielder")
        )

    for win in meta.get("windows", []):
        for f in sorted((SITE_DATA / col / "leaderboards").glob(f"*.{win}.json")):
            base = SITE_DATA / col / "leaderboards" / f.name.replace(f".{win}", "")
            career = {_key(r): r for r in json.loads(base.read_text("utf-8"))}
            for r in json.loads(f.read_text("utf-8")):
                who = _key(r)
                full = (players.get(who) or {}).get("matches") or (career.get(who) or {}).get(
                    "matches"
                )
                if full:
                    assert r["matches"] <= full, (f.name, who)
        # a one-year window can't hold more than a couple of seasons of matches for anyone
        if win == "last1y" and col == "ipl":
            rows = _load(col, "leaderboards", f"counter_attack.{win}.json")
            assert all(r["matches"] <= 30 for r in rows)


CAPPED_STARS = {
    "dbe50b21": "Hardik Pandya",
    "2e81a32d": "Bhuvneshwar Kumar",
    "b0482a1d": "Tilak Varma",
    "5bb1a1c4": "Ishant Sharma",
    "1e66c162": "Jaydev Unadkat",
}


def test_capped_stars_are_capped_and_out_of_the_uncapped_pool():
    target = leagues.auction_target().key
    players = {p["cricsheet_id"]: p for p in _players(target)}
    for cid, name in CAPPED_STARS.items():
        if cid in players:
            assert players[cid]["capped"], name
    idx = _load(target, "scout_index.json")
    for lg in leagues.scout_pools():
        if lg.scout_group != "uncapped":
            continue
        for r in idx.get(lg.tier, []):
            assert not r.get("capped"), r["name"]
            assert r["cricsheet_id"] not in CAPPED_STARS, r["name"]


def test_retired_players_are_out_of_the_auction_pool():
    target = leagues.auction_target().key
    players = {p["cricsheet_id"]: p for p in _players(target)}
    retired = {cid for cid, p in players.items() if p["retired"]}
    pool = {r["cricsheet_id"] for r in _load(target, "auction_pool.json")}
    assert not retired & pool
    # Ashwin and Russell retired from the IPL (see data/curated/player_overrides.json)
    for cid in ("495d42a5", "bbd41817"):
        if cid in players:
            assert players[cid]["retired"] and players[cid]["team"] is None


@pytest.mark.parametrize("col", COLLECTIONS)
def test_display_names_are_unique_within_a_league(col):
    """Namesakes carry their country (or years) so they don't read as one player merged wrongly."""
    names = [p["display_name"] for p in _players(col)]
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, (col, dup[:5])


def test_display_names_are_how_fans_say_them():
    target = leagues.auction_target().key
    players = {p["cricsheet_id"]: p for p in _players(target)}
    expect = {
        "ba607b88": "Virat Kohli",
        "a4cc73aa": "Sanju Samson",
        "dbe50b21": "Hardik Pandya",
        "6c19c6e5": "Yashasvi Jaiswal",
    }
    for cid, name in expect.items():
        if cid in players:
            assert players[cid]["display_name"] == name
            assert players[cid]["name"] in players[cid]["aliases"]


def test_hardik_is_a_seam_bowling_allrounder():
    target = leagues.auction_target().key
    players = {p["cricsheet_id"]: p for p in _players(target)}
    if "dbe50b21" in players:
        p = players["dbe50b21"]
        assert (p["primary_role"], p["bowling_category"], p["bowling_arm"]) == (
            "allrounder",
            "seam",
            "right",
        )


@pytest.mark.parametrize("col", COLLECTIONS)
def test_stale_leagues_are_flagged(col):
    meta = _load(col, "meta.json")
    _players(col)
    assert isinstance(meta.get("stale"), bool)
