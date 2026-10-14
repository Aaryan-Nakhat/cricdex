"""Shared SQL pieces for the ball-by-ball tables (`balls_<collection>` / `matches_<collection>`)."""

from __future__ import annotations

import re

_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")


def table_suffix(collection: str) -> str:
    """The `<collection>` part of a table name. Only lowercase letters, digits and `_` get through, so a name that
    reaches here from the API or the CLI can't inject SQL (DuckDB can read local files)."""
    suffix = collection.strip().replace("-", "_")
    if not _SAFE_NAME.match(suffix):
        raise ValueError(f"not a collection name: {collection!r}")
    return suffix


# Runs charged to the bowler: off the bat plus wides and no-balls. Byes and leg-byes aren't the bowler's.
BOWLER_RUNS = "(runs_batter + CASE WHEN extras_type IN ('wides', 'noballs') THEN COALESCE(runs_extras, 0) ELSE 0 END)"

# Every innings of a multi-day match, but only the two main innings of a limited-overs one (super overs decide a
# tie; they aren't part of anyone's batting or bowling record).
MAIN_INNINGS = "(innings_idx <= 1 OR match_type IN ('Test', 'MDM'))"

# Dismissals credited to the bowler.
BOWLER_WICKET = (
    "(wicket_kind IS NOT NULL AND wicket_kind NOT IN "
    "('run out', 'retired hurt', 'retired out', 'retired not out', 'obstructing the field'))"
)

# A batter's innings ended (everything but retired hurt / not out, which let them come back).
DISMISSAL = "(wicket_kind IS NOT NULL AND wicket_kind NOT IN ('retired hurt', 'retired not out'))"
