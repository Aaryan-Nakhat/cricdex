"""Regression tests for cricdesk.venues.profile.

Specifically guards the JOIN-USING ambiguity bug in phase_run_rates
that crashed the dashboard Venues page (Eden Gardens).
"""

from __future__ import annotations

import polars as pl
import pytest

from cricdesk.config import DATA_DIR
from cricdesk.venues import profile

DB = (
    DATA_DIR / "cricsheet" / "cricsheet.duckdb"
)  # same lookup as the code (honours CRICDESK_DATA_DIR)
needs_data = pytest.mark.skipif(not DB.exists(), reason="needs cricsheet duckdb")


@needs_data
def test_phase_run_rates_eden_gardens_does_not_crash():
    df = profile.phase_run_rates("Eden Gardens, Kolkata", "ipl")
    assert isinstance(df, pl.DataFrame)
    # Eden Gardens (one name per ground: "Eden Gardens, Kolkata") has hosted ~80 IPL matches by 2026, so phases exist.
    assert df.height >= 3, "expected at least powerplay/middle/death rows"
    assert {"phase", "match_type", "rpo", "dot_pct", "boundary_pct"}.issubset(df.columns)


@needs_data
def test_phase_run_rates_wankhede_does_not_crash():
    df = profile.phase_run_rates("Wankhede Stadium, Mumbai", "ipl")
    assert isinstance(df, pl.DataFrame)


@needs_data
def test_innings_totals_does_not_crash():
    df = profile.innings_totals("Eden Gardens, Kolkata", "ipl")
    assert isinstance(df, pl.DataFrame)


@needs_data
def test_chase_vs_set_does_not_crash():
    df = profile.chase_vs_set_winrate("Eden Gardens, Kolkata", "ipl")
    assert isinstance(df, pl.DataFrame)
