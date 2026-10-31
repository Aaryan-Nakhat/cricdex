"""Schema for the LLM answers: the player taxonomy and the display-name check.

An LLM answer is untrusted text. Every field it fills is checked here against a fixed allow-list
(roles, bowling styles, batting slots, hands, confidence, canonical country codes) or a bounded,
printable string (names). A value outside the list is dropped (set to None) with a logged warning;
a record that is not an object, or whose id is not a plain Cricsheet id, is skipped. Nothing here
calls an LLM.

Used when an answer is written (`scripts/enrich_taxonomy.py`, `names.verify_with_llm`) and again
when a cached file is read (`load_taxonomy`, `load_names`), so a hand-edited or old cache is held to
the same rules.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from loguru import logger

from cricdesk.scout.identity import countries

PRIMARY_ROLES = frozenset({"batter", "bowler", "allrounder", "wk_batter", "unknown"})
BOWLING_CATEGORIES = frozenset({"seam", "spin", "none", "unknown"})
BOWLING_STYLES = frozenset(
    {
        "right-arm-fast",
        "right-arm-fast-medium",
        "right-arm-medium",
        "off-spin",
        "leg-spin",
        "left-arm-orthodox",
        "left-arm-wrist-spin",
        "left-arm-fast",
        "left-arm-fast-medium",
        "left-arm-medium",
        "none",
        "unknown",
    }
)
BATTING_POSITIONS = frozenset(
    {"opener", "no3", "middle", "finisher", "lower", "tailender", "unknown"}
)
BATTING_HANDS = frozenset({"right", "left", "unknown"})
CONFIDENCE = frozenset({"high", "medium", "low"})
NAME_VERDICTS = frozenset({"confirmed", "corrected", "unknown"})

ENUM_FIELDS: dict[str, frozenset[str]] = {
    "primary_role": PRIMARY_ROLES,
    "bowling_category": BOWLING_CATEGORIES,
    "bowling_style": BOWLING_STYLES,
    "batting_position": BATTING_POSITIONS,
    "batting_hand": BATTING_HANDS,
    "confidence": CONFIDENCE,
}

MAX_NAME_LEN = 80
# Cricsheet ids are 8 hex characters; allow any short id of letters, digits, "_", "-" and ":".
_ID = re.compile(r"^[A-Za-z0-9_:\-]{1,40}$")


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


def clean_name(value: Any, *, field: str = "name", cid: str = "") -> str | None:
    """A player name: a string of at most MAX_NAME_LEN printable characters with at least one
    letter, whitespace collapsed. Anything else is None."""
    if value is None:
        return None
    if not isinstance(value, str):
        logger.warning(f"taxonomy {cid}: {field} is not a string ({type(value).__name__}); dropped")
        return None
    s = " ".join(value.split())
    if not s:
        return None
    bad = (
        len(s) > MAX_NAME_LEN
        or any(unicodedata.category(ch)[0] == "C" for ch in s)
        or any(ch in "<>{}[]\\`|" for ch in s)
        or not any(ch.isalpha() for ch in s)
    )
    if bad:
        logger.warning(f"taxonomy {cid}: {field} {value[:40]!r} is not a plain name; dropped")
        return None
    return s


def _enum(rec: dict, field: str, cid: str) -> str | None:
    v = rec.get(field)
    if v is None:
        return None
    s = v.strip().lower() if isinstance(v, str) else None
    if s in ENUM_FIELDS[field]:
        return s
    logger.warning(f"taxonomy {cid}: {field} {str(v)[:40]!r} not allowed; dropped")
    return None


def clean_country(value: Any, *, cid: str = "") -> str | None:
    """Any spelling of a cricket nation → its canonical code, only if that code is on the list
    `countries.all_codes()`; anything else is None (with a warning when a value was given)."""
    code = countries.normalise(value) if isinstance(value, str) else None
    if code and code in countries.all_codes():
        return code
    if isinstance(value, str) and value.strip().lower() in {"", "unknown", "none", "null"}:
        return None
    if value is not None:
        logger.warning(f"taxonomy {cid}: country {str(value)[:40]!r} not allowed; dropped")
    return None


def clean_record(rec: Any, *, cid: str = "") -> dict | None:
    """One taxonomy record, every field checked. None when `rec` is not an object."""
    if not isinstance(rec, dict):
        logger.warning(f"taxonomy {cid}: record is {type(rec).__name__}, not an object; skipped")
        return None
    out: dict[str, Any] = {
        "name": clean_name(rec.get("name"), field="name", cid=cid),
        "full_name": clean_name(rec.get("full_name"), field="full_name", cid=cid),
    }
    for field in ENUM_FIELDS:
        out[field] = _enum(rec, field, cid)
    out["country"] = clean_country(rec.get("country"), cid=cid)
    # a bowling style must agree with its category; a "none" category has no style
    style, cat = out["bowling_style"], out["bowling_category"]
    if cat == "none" and style not in (None, "none", "unknown"):
        logger.warning(f"taxonomy {cid}: style {style!r} with category 'none'; style dropped")
        out["bowling_style"] = None
    out["source"] = "llm"
    return out


def clean_taxonomy(raw: Any) -> dict[str, dict]:
    """A whole taxonomy mapping {cricsheet_id: record}, every record checked."""
    if not isinstance(raw, dict):
        logger.warning(f"taxonomy: file is {type(raw).__name__}, not an object; ignored")
        return {}
    out: dict[str, dict] = {}
    for cid, rec in raw.items():
        if not valid_id(cid):
            logger.warning(f"taxonomy: id {str(cid)[:40]!r} is not a player id; skipped")
            continue
        cleaned = clean_record(rec, cid=cid)
        if cleaned is not None:
            out[cid] = cleaned
    return out


def load_taxonomy(path: Path) -> dict[str, dict]:
    """Read and check `player_taxonomy.json` (missing → {})."""
    if not path.exists():
        return {}
    return clean_taxonomy(json.loads(path.read_text(encoding="utf-8")))


def clean_name_answer(rec: Any, *, cid: str = "") -> dict | None:
    """One display-name answer ({candidate, display_name, verdict, confidence}), checked. None when
    it is not an object or has no usable display name."""
    if not isinstance(rec, dict):
        logger.warning(f"names {cid}: answer is {type(rec).__name__}, not an object; skipped")
        return None
    display = clean_name(rec.get("display_name"), field="display_name", cid=cid)
    if not display:
        return None
    verdict = rec.get("verdict")
    verdict = verdict.strip().lower() if isinstance(verdict, str) else None
    if verdict is not None and verdict not in NAME_VERDICTS:
        logger.warning(f"names {cid}: verdict {verdict[:40]!r} not allowed; dropped")
        verdict = None
    conf = rec.get("confidence")
    conf = conf.strip().lower() if isinstance(conf, str) else None
    if conf is not None and conf not in CONFIDENCE:
        logger.warning(f"names {cid}: confidence {conf[:40]!r} not allowed; dropped")
        conf = None
    return {
        # the candidate is our own text (not the LLM's); kept verbatim so `names.resolve` matches it
        "candidate": cand if isinstance(cand := rec.get("candidate"), str) else None,
        "display_name": display,
        "verdict": verdict,
        "confidence": conf,
    }


def clean_names(raw: Any) -> dict[str, dict]:
    """A whole name-check cache {cricsheet_id: answer}, every answer checked."""
    if not isinstance(raw, dict):
        logger.warning(f"names: file is {type(raw).__name__}, not an object; ignored")
        return {}
    out: dict[str, dict] = {}
    for cid, rec in raw.items():
        if not valid_id(cid):
            logger.warning(f"names: id {str(cid)[:40]!r} is not a player id; skipped")
            continue
        cleaned = clean_name_answer(rec, cid=cid)
        if cleaned is not None:
            out[cid] = cleaned
    return out


def load_names(path: Path) -> dict[str, dict]:
    """Read and check `player_names_llm.json` (missing → {})."""
    if not path.exists():
        return {}
    return clean_names(json.loads(path.read_text(encoding="utf-8")))
