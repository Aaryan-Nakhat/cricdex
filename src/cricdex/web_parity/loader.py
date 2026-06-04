"""Load the same exported JSON the static web app fetches.

`scripts/export_site.py` cooks these from the DuckDB into
`site/public/data/<collection>/`. Both surfaces read these exact files, so
the *inputs* are identical; `pricing`/`scout`/`auction` then apply identical
*logic*.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cricdex.config import ROOT

# Where export_site.py writes (ROOT = repo root, see cricdex.config).
SITE_DATA = ROOT / "site" / "public" / "data"


def _base(base: Path | str | None) -> Path:
    return Path(base) if base else SITE_DATA


def _read(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `uv run python scripts/export_site.py` first."
        )
    return json.loads(path.read_text())


def load_auction_pool(collection: str = "ipl", base: Path | str | None = None) -> list[dict]:
    """Every active rated player priced for the auction (cross-collection)."""
    return _read(_base(base) / collection / "auction_pool.json")


def load_retentions(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """{"mega": {team: [{cricsheet_id, name, price}]}} — real 2025 lists."""
    return _read(_base(base) / collection / "retentions.json")


def load_scout_index(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """{"ipl": [...], "smat": [...], "bbl": [...]} look-alike index."""
    return _read(_base(base) / collection / "scout_index.json")
