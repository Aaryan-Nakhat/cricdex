"""Wikidata enrichment: who gets enriched, and the name-search fallback can't attach the wrong person."""

from __future__ import annotations

import duckdb
import pytest

from cricdex.scout.ingest import wikidata


def _claim(value):
    if isinstance(value, str) and value.startswith("Q"):
        value = {"entity-type": "item", "id": value}
    return {"mainsnak": {"datavalue": {"value": value}}}


def _entity(desc="", occupations=(), p2697=(), p2698=()):
    claims = {}
    if occupations:
        claims["P106"] = [_claim(q) for q in occupations]
    if p2697:
        claims["P2697"] = [_claim(v) for v in p2697]
    if p2698:
        claims["P2698"] = [_claim(v) for v in p2698]
    return {"descriptions": {"en": {"value": desc}}, "claims": claims}


CRICKETER = wikidata.CRICKETER_QID


def test_must_be_a_cricketer():
    politician = _entity(desc="Pakistani politician", occupations=("Q82955",))
    assert not wikidata.entity_matches_player(politician, {"unique_name": "Abdul Nasir"})
    assert wikidata.entity_matches_player(
        _entity(occupations=(CRICKETER,)), {"unique_name": "Abdul Nasir"}
    )
    # description alone is enough when the occupation claim is missing
    assert wikidata.entity_matches_player(
        _entity(desc="Indian cricketer"), {"unique_name": "Abdul Nasir"}
    )


def test_register_cricinfo_id_must_match():
    player = {"unique_name": "A Khan", "statsguru_id": "625383"}
    right = _entity(occupations=(CRICKETER,), p2697=("625383",))
    wrong = _entity(occupations=(CRICKETER,), p2697=("111111",))
    no_ids = _entity(occupations=(CRICKETER,))
    assert wikidata.entity_matches_player(right, player)
    assert not wikidata.entity_matches_player(wrong, player)
    # the register knows his id but this namesake carries none: can't confirm, so no
    assert not wikidata.entity_matches_player(no_ids, player)


def test_secondary_cricinfo_and_cricbuzz_ids():
    player = {
        "unique_name": "A Khan",
        "statsguru_ids": ["625383", "999"],
        "register_cricbuzz_id": "8733",
    }
    assert wikidata.entity_matches_player(_entity(desc="cricketer", p2697=("999",)), player)
    assert wikidata.entity_matches_player(_entity(desc="cricketer", p2698=("8733",)), player)
    # one id agrees but the other names somebody else: reject
    assert not wikidata.entity_matches_player(
        _entity(desc="cricketer", p2697=("625383",), p2698=("1",)), player
    )


def test_float_register_ids_compare_as_integers():
    player = {"unique_name": "A Khan", "statsguru_id": 625383.0}
    assert wikidata.entity_matches_player(_entity(desc="cricketer", p2697=("625383",)), player)


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class _FakeClient:
    """Serves wbsearchentities hits + entity JSON from fixtures (no network)."""

    def __init__(self, hits, entities):
        self.hits, self.entities = hits, entities

    def get(self, url, params=None):
        if params and params.get("action") == "wbsearchentities":
            return _Resp({"search": self.hits})
        if params and params.get("action") == "query":
            return _Resp({"query": {"search": []}})  # the statsguru bridge finds nothing
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        return _Resp({"entities": {qid: self.entities[qid]}})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(wikidata, "SLEEP_BETWEEN_REQUESTS_S", 0)


def test_search_skips_the_wrong_namesake():
    hits = [
        {"id": "Q1", "description": "Pakistani cricketer"},
        {"id": "Q2", "description": "Indian cricketer"},
    ]
    entities = {
        "Q1": _entity(occupations=(CRICKETER,), p2697=("1",)),
        "Q2": _entity(occupations=(CRICKETER,), p2697=("2",)),
    }
    cx = _FakeClient(hits, entities)
    player = {"unique_name": "Abdul Nasir", "statsguru_id": "2"}
    assert wikidata.resolve_qid(player, cx) == "Q2"
    assert wikidata.resolve_qid({"unique_name": "Abdul Nasir", "statsguru_id": "3"}, cx) is None


def test_search_without_ids_refuses_an_ambiguous_name():
    hits = [
        {"id": "Q1", "description": "cricketer"},
        {"id": "Q2", "description": "cricketer"},
    ]
    entities = {"Q1": _entity(occupations=(CRICKETER,)), "Q2": _entity(occupations=(CRICKETER,))}
    assert wikidata.search_qid("Abdul Nasir", _FakeClient(hits, entities)) is None
    assert wikidata.search_qid("Abdul Nasir", _FakeClient(hits[:1], entities)) == "Q1"


@pytest.fixture
def reg_db(tmp_path):
    path = tmp_path / "reg.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE people (identifier TEXT, name TEXT, unique_name TEXT, key_cricinfo BIGINT, "
        "key_cricinfo_2 BIGINT, key_cricinfo_3 BIGINT, key_cricbuzz BIGINT)"
    )
    con.executemany(
        "INSERT INTO people VALUES (?,?,?,?,NULL,NULL,?)",
        [(f"id{i:03d}", f"P{i}", f"P{i}", 1000 + i, 2000 + i) for i in range(400)]
        + [("idsaini", "NA Saini", "NA Saini", 700, None)],
    )
    con.execute("CREATE TABLE balls_ipl (batter TEXT, bowler TEXT, non_striker TEXT)")
    # 400 players with 40 balls each (well past the old 300 cap) + one with 10
    con.execute(
        "INSERT INTO balls_ipl SELECT 'P' || (i // 40), 'Bowler X', NULL FROM range(16000) t(i)"
    )
    con.execute("INSERT INTO balls_ipl SELECT 'Navdeep Saini', 'Bowler X', NULL FROM range(10)")
    # a window copy must not count again
    con.execute("CREATE TABLE balls_ipl_last1y AS SELECT * FROM balls_ipl WHERE batter = 'P1'")
    con.execute("CREATE TABLE players_ipl (match_id TEXT, name TEXT, identifier TEXT)")
    con.execute("INSERT INTO players_ipl VALUES ('1', 'Navdeep Saini', 'idsaini')")
    con.close()
    return path


def test_register_players_has_no_top_300_cap(reg_db):
    players = wikidata._load_register_players(reg_db)
    assert len(players) == 400  # every player past DEFAULT_MIN_BALLS, not the top 300
    p = next(x for x in players if x["cricsheet_id"] == "id007")
    assert p["statsguru_id"] == "1007"
    assert p["statsguru_ids"] == ["1007"]
    assert p["register_cricbuzz_id"] == "2007"


def test_register_players_min_balls_and_registry_names(reg_db):
    players = wikidata._load_register_players(reg_db, min_balls=10)
    by_id = {p["cricsheet_id"]: p for p in players}
    # the scorecard says "Navdeep Saini"; only the match registry ties him to the register
    assert by_id["idsaini"]["unique_name"] == "NA Saini"


def test_register_players_ignore_window_tables(reg_db):
    players = wikidata._load_register_players(reg_db, min_balls=41)
    # P1 has 40 balls in balls_ipl; counting balls_ipl_last1y too would push him to 80
    assert players == []
