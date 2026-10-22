"""International appearances Cricsheet withholds (Afghanistan): the Wikipedia-revision method
(src/cricdex/scout/identity/withheld.py, docs/METHODOLOGY.md §1)."""

from __future__ import annotations

from cricdex.scout.identity import withheld as W


def _rev(ts: str, **counts: int) -> tuple[str, dict[str, tuple[int, str]]]:
    return ts, {k: (v, k) for k, v in counts.items()}


def test_each_increase_is_dated_at_the_revision_that_published_it():
    revs = [
        _rev("2023-01-01T00:00:00Z", a=10, b=3),  # the baseline (on or before the snapshot)
        _rev("2023-03-05T10:00:00Z", a=12, b=3),
        _rev("2023-06-01T10:00:00Z", a=13, b=4),
    ]
    got = W.appearances_from_revisions(revs, "2023-02-19")
    assert got == {"a": ["2023-03-05", "2023-03-05", "2023-06-01"], "b": ["2023-06-01"]}


def test_a_reverted_inflation_never_counts():
    """The count as of a revision is the lowest any later revision shows: a vandal's 99, reverted to
    11 the next day, adds one appearance (the one the later revision confirms), not 89."""
    revs = [
        _rev("2023-01-01T00:00:00Z", a=10),
        _rev("2023-04-01T00:00:00Z", a=99),
        _rev("2023-04-02T00:00:00Z", a=11),
    ]
    assert W.appearances_from_revisions(revs, "2023-02-19") == {"a": ["2023-04-01"]}


def test_a_blanked_table_is_skipped():
    revs = [
        _rev("2023-01-01T00:00:00Z", a=10, b=5, c=7),
        _rev("2023-04-01T00:00:00Z", a=0),  # lost most of its rows: a blanking or a parse failure
        _rev("2023-05-01T00:00:00Z", a=11, b=5, c=7),
    ]
    assert W.appearances_from_revisions(revs, "2023-02-19") == {"a": ["2023-05-01"]}


def test_parse_list_counts_reads_a_cap_list_row():
    text = (
        '{| class="wikitable"\n|-\n! scope="row" | {{sortname|Rashid|Khan}}\n'
        "| 2015 || 2026 || 118 || 400 ||<ref>"
        "[https://www.espncricinfo.com/cricketers/rashid-khan-793463 x]</ref>\n|-\n"
    )
    assert W.parse_list_counts(text) == {"793463": (118, "Rashid Khan")}
