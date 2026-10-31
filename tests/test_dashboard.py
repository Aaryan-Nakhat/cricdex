"""Every Streamlit page runs without an exception on the committed site data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1", reason="needs the `ui` extra")

DASH = Path(__file__).resolve().parents[1] / "src" / "cricdesk" / "dashboard"
# pages that only read the exported JSON (Head-to-Head and Update Data need the local DuckDB / scripts)
PAGES = sorted(p for p in (DASH / "pages").glob("*.py") if not p.name.startswith(("4_", "10_")))


@pytest.mark.parametrize("page", [DASH / "app.py", *PAGES], ids=lambda p: p.name)
def test_page_renders(page):
    at = st_testing.AppTest.from_file(str(page), default_timeout=120)
    at.run()
    assert not at.exception, f"{page.name}: {at.exception}"


# --- interactions ------------------------------------------------------------

PAGE = DASH / "pages"
SITE = DASH.parents[2] / "site" / "public" / "data"


def _app(name: str):
    at = st_testing.AppTest.from_file(str(PAGE / name), default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(elements) -> list[str]:
    return [e.value for e in elements]


def test_auction_result_survives_lookups_and_resets_on_settings():
    at = _app("7_Auction.py")
    at.number_input(key="trials").set_value(50).run()
    next(b for b in at.button if "Run simulation" in b.label).click().run()
    assert not at.exception, at.exception
    assert "auction_result" in at.session_state
    n_tables = len(at.dataframe)

    # looking a player up / switching the sample squad must not wipe the run
    at.selectbox(key="auction_search").select_index(1).run()
    at.selectbox(key="squad_team").select_index(1).run()
    assert not at.exception, at.exception
    assert "auction_result" in at.session_state
    assert len(at.dataframe) == n_tables + 1  # + the lookup table
    assert not any("Run simulation" in t for t in _texts(at.info))

    # a setting that shapes the result clears it
    at.number_input(key="purse_mega").set_value(100.0).run()
    assert "auction_result" not in at.session_state
    assert any("Run simulation" in t for t in _texts(at.info))


def test_scout_drafts_accumulate_across_picks():
    from cricdesk.web_parity import load_auction_pool, load_scout_index

    idx = load_scout_index("ipl")
    pool = {p["cricsheet_id"] for p in load_auction_pool("ipl")}

    # options are 'Name (League)': the league label comes from the registry, so match the player by
    # name (scorecard or display) across every Scout pool rather than mapping the label to a key
    by_name: dict[str, list[str]] = {}
    for rows in idx.values():
        for r in rows:
            for n in {r.get("name"), r.get("display_name")} - {None}:
                by_name.setdefault(n, []).append(r["cricsheet_id"])

    def eligible(ms) -> str | None:
        """Raw cid for the first prospect in the priced pool."""
        for label in ms.options:
            name = label.rsplit(" (", 1)[0]
            for cid in by_name.get(name, []):
                if cid in pool:
                    return cid
        return None

    at = _app("9_Scout.py")
    drafted: list[str] = []
    for p in sorted(idx["ipl"], key=lambda p: p["name"]):
        at.selectbox(key="scout-pick").set_value(p["cricsheet_id"]).run()
        ms = next(m for m in at.multiselect if m.label.startswith("Draft prospects"))
        cid = eligible(ms)
        if cid and cid not in drafted:
            ms.set_value([cid]).run()
            assert not at.exception, at.exception
            drafted.append(cid)
        if len(drafted) == 2:
            break
    assert len(drafted) == 2, "need two picks with a draftable prospect"
    # the first pick's draft survived switching to the second pick
    assert at.session_state["drafted"] == drafted


@pytest.mark.parametrize(
    ("page", "key", "heading"),
    [
        ("15_Partnerships.py", "partnerships-player", "Most productive partners"),
        ("16_Aging.py", "aging-player", None),
    ],
)
def test_optional_player_defaults_to_none(page, key, heading):
    at = _app(page)
    sel = at.selectbox(key=key)
    assert sel.value is None
    assert len(at.get("plotly_chart")) <= 1
    if heading:
        assert not any(heading in t for t in _texts(at.subheader))
    first = min(json.loads((SITE / "ipl" / "players.json").read_text()), key=lambda p: p["name"])
    sel.set_value(first["cricsheet_id"]).run()
    assert not at.exception, at.exception
    assert at.selectbox(key=key).value is not None
    if heading:
        assert any(heading in t for t in _texts(at.subheader))


def test_banner_time_is_utc():
    import datetime as dt

    at = _app("15_Partnerships.py")
    mtime = (SITE / "ipl" / "meta.json").stat().st_mtime
    want = dt.datetime.fromtimestamp(mtime, tz=dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    assert any(want in t for t in _texts(at.caption))


def test_profile_birth_date_is_formatted():
    at = _app("8_Player_Profile.py")  # defaults to V Kohli
    assert any("Born 5 Nov 1988" in t for t in _texts(at.caption))


def test_compare_players_sharing_a_short_name(tmp_path, monkeypatch):
    """Two picked players with the same scorecard name stay two columns."""
    import streamlit as st

    import cricdesk.dashboard._widgets as widgets
    import cricdesk.web_parity.loader as loader

    players = json.loads((SITE / "ipl" / "players.json").read_text())[:2]
    site = tmp_path / "data"
    (site / "ipl" / "profiles").mkdir(parents=True)
    for p, full in zip(players, ("Alpha B Same", "Beta B Same"), strict=True):
        src = SITE / "ipl" / "profiles" / f"{p['cricsheet_id']}.json"
        (site / "ipl" / "profiles" / src.name).write_text(src.read_text())
        p["name"], p["full_name"] = "AB Same", full
    (site / "ipl" / "players.json").write_text(json.dumps(players))
    (site / "ipl" / "meta.json").write_text("{}")
    (site / "collections.json").write_text(json.dumps([{"collection": "ipl"}]))
    monkeypatch.setattr(loader, "SITE_DATA", site)
    monkeypatch.setattr(widgets, "SITE_DATA", site)
    st.cache_data.clear()  # loaders cache on args, not on SITE_DATA
    try:
        at = st_testing.AppTest.from_file(str(PAGE / "5_Compare.py"), default_timeout=180)
        at.run()
        at.multiselect(key="compare-players").set_value([p["cricsheet_id"] for p in players])
        at.run()
    finally:
        st.cache_data.clear()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert [c for c in table.columns if c.startswith("AB Same")] == [
        f"AB Same ({p['cricsheet_id']})" for p in players
    ]


def _read_corrupt(path: str) -> None:
    from pathlib import Path

    from cricdesk.dashboard._widgets import read_json

    read_json(Path(path), {})


def test_corrupt_json_shows_an_error(tmp_path):
    bad = tmp_path / "records.json"
    bad.write_text('{"truncated": [')
    at = st_testing.AppTest.from_function(_read_corrupt, args=(str(bad),))
    at.run()
    assert not at.exception, at.exception
    assert any("records.json" in t for t in _texts(at.error))
