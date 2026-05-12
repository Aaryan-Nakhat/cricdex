"""Smoke tests for the comparator pure helpers."""

from __future__ import annotations

import polars as pl

from cricdex.comparator import compare as cmp


def test_safe_get_returns_none_on_empty():
    assert cmp._safe_get(pl.DataFrame(), "batter", "X", "v") is None


def test_safe_get_returns_none_for_missing_player():
    df = pl.DataFrame({"batter": ["A", "B"], "v": [1.0, 2.0]})
    assert cmp._safe_get(df, "batter", "C", "v") is None


def test_safe_get_returns_float_on_hit():
    df = pl.DataFrame({"batter": ["A"], "v": [3.14]})
    out = cmp._safe_get(df, "batter", "A", "v")
    assert isinstance(out, float)
    assert abs(out - 3.14) < 1e-6


def test_safe_get_handles_decimal_strings():
    df = pl.DataFrame({"batter": ["A"], "v": ["12.5"]})
    out = cmp._safe_get(df, "batter", "A", "v")
    assert out == 12.5
