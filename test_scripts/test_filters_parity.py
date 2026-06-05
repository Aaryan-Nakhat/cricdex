"""Parity lock: the Python FilterBar port (`cricdex.common.filters.apply_filters`)
must reproduce the canonical TS `applyFilters` (`site/src/lib/filters.ts`) on the
same fixture + filter cases. If this fails, the desktop filters have drifted from
the web. Skips (does not fail) if Node is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cricdex.common.filters import Filters, apply_filters

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# TS camelCase Filters key -> Python snake_case Filters field.
_KEYMAP = {
    "minMatches": "min_matches",
    "role": "role",
    "bowling": "bowling",
    "position": "position",
    "country": "country",
    "activity": "activity",
    "yearFrom": "year_from",
    "yearTo": "year_to",
}


def _node_dump() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    r = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "scripts/filters_parity_dump.ts"],
        cwd=SITE,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-500:]}")
    return json.loads(r.stdout)


def test_filters_parity():
    dump = _node_dump()
    fixture = dump["fixture"]
    for name, ts_filter in dump["cases"].items():
        f = Filters(**{_KEYMAP[k]: v for k, v in ts_filter.items()})
        py_ids = [str(r["id"]) for r in apply_filters(fixture, f)]
        assert (
            py_ids == dump["survivors"][name]
        ), f"case {name}: {py_ids} != {dump['survivors'][name]}"
