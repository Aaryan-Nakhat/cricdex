"""Fan-facing display names.

Scorecards print initials ("V Kohli", "YBK Jaiswal"); registers keep legal names ("Yashasvi
Bhupendra Jaiswal"). Fans say "Virat Kohli" and "Yashasvi Jaiswal". The display name is chosen in
three steps:

1. **Candidate from open data**: the Wikidata English label (Wikipedia article titles follow the
   "common name" rule, so the label usually is the fan name), else the People Register variant
   that is the shortest made of full words (two or more words, no initials), else the scorecard
   name.
2. **LLM check**: the configured LLM (any provider, via LiteLLM — `cricdex.common.llm`) is asked,
   25 players a call, whether each candidate is how fans commonly refer to the player and, if
   not, for the common name. Answers are cached in `data/curated/player_names_llm.json`; a
   correction is accepted only when it keeps the player's surname (or another token the open data
   knows), so a confused answer can't rename someone into a different cricketer.
3. **Reviewed overrides** (`data/curated/player_overrides.json`, `display_name`) always win.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from loguru import logger

from cricdex.common.llm import LLMError
from cricdex.config import CURATED_DIR
from cricdex.scout.identity.sources import write_json

LLM_NAMES_CACHE = CURATED_DIR / "player_names_llm.json"
LLM_BATCH = 25
LLM_WORKERS = 6  # concurrent LLM calls

_INITIALS = re.compile(r"^(?:[A-Z]\.?){1,4}$")  # "MS", "V", "A.B.", "YBK"


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name.strip()) if t]


def is_full_words(name: str | None) -> bool:
    """Two or more words, none of them initials ("Virat Kohli" yes; "V Kohli", "MS Dhoni" no)."""
    if not name:
        return False
    toks = _tokens(name)
    if len(toks) < 2:
        return False
    for t in toks:
        core = t.strip(".,'-()")
        if not core:
            return False
        if _INITIALS.match(core) or (len(core) <= 2 and core.isupper()):
            return False
    return True


def clean_label(label: str | None) -> str | None:
    """A Wikidata / Wikipedia label without a disambiguator ("Spencer Johnson (cricketer)")."""
    if not label:
        return None
    s = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
    return s or None


def register_candidate(variants: list[str]) -> str | None:
    """The shortest full-word variant with two or more words (ties: alphabetical, for stability)."""
    good = sorted({v.strip() for v in variants if is_full_words(v)}, key=lambda v: (len(v), v))
    return good[0] if good else None


def longest_full_name(variants: list[str]) -> str | None:
    good = sorted({v.strip() for v in variants if is_full_words(v)}, key=lambda v: (-len(v), v))
    return good[0] if good else None


def candidate(scorecard: str, wikidata_label: str | None, variants: list[str]) -> tuple[str, str]:
    """(candidate name, source) — source is "wikidata", "register" or "scorecard"."""
    lab = clean_label(wikidata_label)
    if lab and not re.search(r"\d", lab):
        return lab, "wikidata"
    reg = register_candidate(variants)
    if reg:
        return reg, "register"
    return scorecard, "scorecard"


def _norm_tok(t: str) -> str:
    return re.sub(r"[^a-z]", "", t.lower())


def _close(a: str, b: str) -> bool:
    """Two name tokens that are the same name: equal, one a short form of the other ("phil" /
    "philip"), or a spelling variant ("liton" / "litton", "kusal" / "kushal")."""
    import difflib

    if a == b or (len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a))):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def plausible_correction(
    new: str, known_names: list[str], candidate: str = "", confidence: str | None = "high"
) -> bool:
    """May the LLM's corrected name replace the candidate? Guards against an answer that names a
    different cricketer (a newer player the model doesn't know gets a famous namesake's first name):

    - it must keep a token the open data already knows (normally the surname), and
    - every other word must be known too (or a short form / spelling variant of a known word),
      except a first name that spells out an initial of the candidate ("V Kohli" -> "Virat"), which
      needs a high-confidence answer.
    """
    known = {_norm_tok(t) for n in known_names if n for t in _tokens(n) if len(_norm_tok(t)) >= 2}
    toks = [_norm_tok(t) for t in _tokens(new) if _norm_tok(t)]
    if not any(t in known for t in toks if len(t) >= 3):
        return False
    initials = {
        c.lower()
        for t in _tokens(candidate)
        if _INITIALS.match(t.strip(".,")) or (len(t.strip(".")) <= 2 and t.strip(".").isupper())
        for c in t.strip(".,").replace(".", "")
    }
    firsts = {k[0] for k in known}
    for t in toks:
        if any(_close(t, k) for k in known):
            continue
        if len(t) <= 3 and all(c in firsts for c in t):
            continue  # initials of known names: "T Natarajan", "MS Dhoni", "KL Rahul"
        if t[0] in initials and confidence == "high":
            continue
        return False
    return True


# ---- LLM verification ----------------------------------------------------------------------------

SYS = (
    "You are a cricket expert who knows how fans, commentators and the media commonly refer to "
    "professional cricketers. Answer from knowledge you are sure of; if you don't know the player, "
    "keep the candidate."
)

PROMPT = (
    "For each cricketer below decide: is `candidate` how fans commonly refer to this player? "
    "If yes, return it unchanged. If not, return the common name (e.g. scorecard 'V Kohli' -> "
    "'Virat Kohli'; legal name 'Yashasvi Bhupendra Jaiswal' -> 'Yashasvi Jaiswal'; keep "
    "established initials such as 'MS Dhoni', 'KL Rahul', 'AB de Villiers'). Use the scorecard "
    "name, other known names and country to identify the player. Never invent a player.\n"
    'Return JSON {"players":[{"id":..., "display_name":..., "verdict":"confirmed"|"corrected"|'
    '"unknown", "confidence":"high"|"medium"|"low"}]} with one object per input, same order.'
)


def _ask(batch: list[dict]) -> list[dict]:
    from cricdex.common import llm

    res = llm.generate_json(SYS, f"{PROMPT}\n\nPlayers: {json.dumps(batch, ensure_ascii=False)}")
    if isinstance(res, list):  # some models answer with the bare array
        return res
    return res.get("players", []) if isinstance(res, dict) else []


def verify_with_llm(
    todo: list[dict[str, Any]],
    *,
    batch: int = LLM_BATCH,
    workers: int = LLM_WORKERS,
    limit: int = 0,
) -> dict[str, dict]:
    """Ask the LLM about every `todo` row ({id, candidate, scorecard, known_names, country}) whose
    candidate isn't cached yet, `batch` players a call and `workers` calls at a time. Returns the
    whole cache {cricsheet_id: answer}. Resumable: the cache is saved after every call."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from cricdex.common import llm
    from cricdex.scout.identity import taxonomy

    cache: dict[str, dict] = taxonomy.load_names(LLM_NAMES_CACHE)
    if not llm.configured():
        logger.warning("names: no LLM configured (LLM_MODEL in .env) — candidates stay unverified")
        return cache
    pending = [r for r in todo if cache.get(r["id"], {}).get("candidate") != r["candidate"]]
    if limit:
        pending = pending[:limit]
    logger.info(f"names: {len(todo)} players, {len(pending)} to verify with the LLM")
    lock = threading.Lock()
    chunks = [pending[i : i + batch] for i in range(0, len(pending), batch)]

    def run(chunk: list[dict]) -> int:
        payload = [
            {
                "id": r["id"],
                "candidate": r["candidate"],
                "scorecard": r["scorecard"],
                "other_names": r.get("known_names", [])[:8],
                "country": r.get("country"),
            }
            for r in chunk
        ]
        got: list[dict] = []
        for attempt in range(3):
            try:
                got = _ask(payload)
                break
            except LLMError as e:  # any provider error: retry, then skip
                logger.warning(f"names batch failed ({e}); attempt {attempt + 1}")
                time.sleep(3 * (attempt + 1))
        by_id = {str(g.get("id")): g for g in got if isinstance(g, dict)}
        n = 0
        with lock:
            for r in chunk:
                g = by_id.get(str(r["id"]))
                if not g:
                    continue
                # untrusted answer: bounded name, allow-listed verdict / confidence
                ans = taxonomy.clean_name_answer({**g, "candidate": r["candidate"]}, cid=r["id"])
                if ans is None:
                    continue
                cache[r["id"]] = ans
                n += 1
            write_json(LLM_NAMES_CACHE, cache)
        return n

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(run, c) for c in chunks]
        for i, f in enumerate(as_completed(futs), 1):
            done += f.result()
            if i % 5 == 0 or i == len(futs):
                logger.info(f"  names: {i}/{len(futs)} calls, {done} answers")
    return cache


def resolve(
    cid: str,
    scorecard: str,
    cand: str,
    cand_source: str,
    known_names: list[str],
    llm_cache: dict[str, dict],
    override: str | None,
) -> dict[str, Any]:
    """The final display name with its provenance: {display_name, name_source, name_check}."""
    if override:
        return {"display_name": override, "name_source": "override", "name_check": "reviewed"}
    ans = llm_cache.get(cid)
    if not ans or ans.get("candidate") != cand:
        return {"display_name": cand, "name_source": cand_source, "name_check": "unverified"}
    new = (ans.get("display_name") or "").strip()
    if not new or new == cand or ans.get("verdict") == "unknown":
        check = "llm_confirmed" if new == cand else "llm_unknown"
        return {"display_name": cand, "name_source": cand_source, "name_check": check}
    ok = plausible_correction(new, [scorecard, cand, *known_names], cand, ans.get("confidence"))
    if ans.get("confidence") == "low" or not ok:
        return {
            "display_name": cand,
            "name_source": cand_source,
            "name_check": "llm_rejected",
            "llm_suggestion": new,
        }
    return {"display_name": new, "name_source": "llm", "name_check": "llm_corrected", "was": cand}
