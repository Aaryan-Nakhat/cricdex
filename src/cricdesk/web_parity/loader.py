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

from cricdesk.config import SITE_DATA

# SITE_DATA (from cricdesk.config) is where export_site.py writes.


def _base(base: Path | str | None) -> Path:
    return Path(base) if base else SITE_DATA


def _read(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `uv run python scripts/export_site.py` first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_auction_pool(collection: str = "ipl", base: Path | str | None = None) -> list[dict]:
    """Every active rated player priced for the auction (cross-collection)."""
    return _read(_base(base) / collection / "auction_pool.json")


def load_retentions(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """{"mega": {team: [{cricsheet_id, name, price}]}} — real 2025 lists."""
    return _read(_base(base) / collection / "retentions.json")


def load_scout_index(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """{"ipl": [...], "smat": [...], "bbl": [...]} look-alike index."""
    return _read(_base(base) / collection / "scout_index.json")


def load_activity_index(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """cricsheet_id -> {leagues, last_ipl, last_any, home_league, age, p_play} — cross-league
    activity and the chance he plays a match (P(plays), METHODOLOGY §6c). Empty dict if not
    exported yet."""
    path = _base(base) / collection / "activity_index.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_keep(collection: str = "ipl", base: Path | str | None = None) -> dict:
    """Keep or release: the competition's rules, every squad player (salary, value, tags, age,
    last season) and the pool free agents' tags."""
    return _read(_base(base) / collection / "keep.json")


def load_bidplan_rivals(collection: str = "ipl", base: Path | str | None = None) -> dict | None:
    """Bid plan: every franchise's default plan, each seeing the others' (the export's
    bidplan_rivals.json, `bidplan.rival_plan_bids`): {team: {player id: [max bid, share landed]}}, or
    None when not exported (the rivals then bid by the demand model alone)."""
    path = _base(base) / collection / "bidplan_rivals.json"
    return json.loads(path.read_text(encoding="utf-8")).get("teams") if path.exists() else None


def load_auction_register(collection: str = "ipl", base: Path | str | None = None) -> list | None:
    """Bid plan: the official auction list once published ([{id, base_price}], copied by the
    export from data/curated/<league>_auction_register.json), else None (the pool is inferred)."""
    path = _base(base) / collection / "auction_register.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
