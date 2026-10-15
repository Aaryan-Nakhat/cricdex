"""Every Streamlit page runs without an exception on the committed site data."""

from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1", reason="needs the `ui` extra")

DASH = Path(__file__).resolve().parents[1] / "src" / "cricdex" / "dashboard"
# pages that only read the exported JSON (Head-to-Head and Update Data need the local DuckDB / scripts)
PAGES = sorted(p for p in (DASH / "pages").glob("*.py") if not p.name.startswith(("4_", "10_")))


@pytest.mark.parametrize("page", [DASH / "app.py", *PAGES], ids=lambda p: p.name)
def test_page_renders(page):
    at = st_testing.AppTest.from_file(str(page), default_timeout=120)
    at.run()
    assert not at.exception, f"{page.name}: {at.exception}"
